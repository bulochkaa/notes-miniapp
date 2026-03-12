"""
FastAPI backend — serves both:
  • REST API for the Mini App frontend  (  /api/...  )
  • Telegram webhook                    (  /webhook  )
  • Static frontend files               (  /app/...  )
"""

import asyncio
import hashlib
import hmac
import json
import logging
import urllib.parse
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Optional

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardButton, InlineKeyboardMarkup,
    MenuButtonWebApp, Message as AioMessage,
    Update, WebAppInfo,
)
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import storage
from config import BOT_TOKEN, GROUP_ID, MINIAPP_URL, TOPICS, WEBHOOK_URL
from database import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher(storage=MemoryStorage())


# ────────────────────── Reminder background task ────────────────────

async def reminder_loop():
    logger.info("Reminder loop started.")
    MONTHS_RU = ['января','февраля','марта','апреля','мая','июня',
                 'июля','августа','сентября','октября','ноября','декабря']
    while True:
        try:
            due = await storage.get_due_reminders()
            for reminder in due:
                user_id   = reminder["user_id"]
                record_id = reminder["record_id"]
                emoji     = reminder.get("emoji", "🔔")
                record    = await storage.get_record(record_id)
                if not record:
                    continue

                cat   = record.get("category", "")
                title = record.get("title", "")
                desc  = record.get("description", "")
                link  = record.get("link", "")
                stars = "⭐" * record.get("rating", 0)
                tags  = "  ".join(f"#{t}" for t in record.get("tags", []))

                text = (
                    f"{emoji} <b>Напоминание!</b>\n\n"
                    f"┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
                    f"<b>{cat}</b>\n\n"
                    f"📌 <b>{title}</b>\n"
                )
                if stars:
                    text += f"⭐ {stars}\n"
                text += f"\n{desc}\n"
                if link:
                    text += f"\n🔗 {link}\n"
                if tags:
                    text += f"\n🏷  {tags}\n"
                text += "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"

                repeat = reminder.get("repeat_type")
                if repeat:
                    text += f"\n\n🔁 Повтор: {'каждую неделю' if repeat == 'weekly' else 'каждый месяц'}"

                try:
                    await bot.send_message(
                        user_id, text,
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                    )
                    logger.info(f"Reminder sent to {user_id} for record {record_id}")
                except Exception as e:
                    logger.error(f"Could not send reminder to {user_id}: {e}")

        except Exception as e:
            logger.error(f"Reminder loop error: {e}")

        await asyncio.sleep(60)


# ────────────────────── Startup / shutdown ──────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    reminder_task = asyncio.create_task(reminder_loop())
    if WEBHOOK_URL:
        await bot.set_webhook(WEBHOOK_URL)
        await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(
            text="Открыть заметки",
            web_app=WebAppInfo(url=MINIAPP_URL),
        ))
        logger.info(f"Webhook set: {WEBHOOK_URL}")
    yield
    reminder_task.cancel()
    await bot.session.close()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


# ────────────────────── Auth ─────────────────────────────────────────

ALLOWED_USERS = []
try:
    from config import ALLOWED_USERS as _au
    ALLOWED_USERS = _au
except Exception:
    pass


def validate_init_data(init_data: str) -> Optional[dict]:
    try:
        parsed   = dict(urllib.parse.parse_qsl(init_data, strict_parsing=True))
        received = parsed.pop("hash", "")
        data_str = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
        secret   = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        expected = hmac.new(secret, data_str.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, received):
            return None
        user = json.loads(parsed.get("user", "{}"))
        return user
    except Exception as e:
        logger.error(f"initData validation error: {e}")
        return None


def get_user_id(request: Request) -> int:
    init_data = request.headers.get("X-Init-Data", "")
    if not init_data:
        raise HTTPException(status_code=401, detail="Missing initData")
    user = validate_init_data(init_data)
    if not user:
        raise HTTPException(status_code=403, detail="Invalid initData")
    return int(user["id"])


# ────────────────────── Pydantic models ─────────────────────────────

class RecordCreate(BaseModel):
    category:     str
    title:        str
    description:  str
    link:         Optional[str]      = None
    photo:        Optional[str]      = None
    rating:       int                = 0
    tags:         list[str]          = []
    reminder_date: Optional[str]     = None   # ISO datetime string
    reminder_time: Optional[str]     = None   # "HH:MM"
    repeat_type:   Optional[str]     = None   # "weekly" | "monthly"
    reminder_emoji: Optional[str]    = None


class RecordUpdate(BaseModel):
    title:       Optional[str]       = None
    description: Optional[str]       = None
    link:        Optional[str]       = None
    rating:      Optional[int]       = None
    tags:        Optional[list[str]] = None


class ReminderCreate(BaseModel):
    record_id:    str
    remind_date:  str              # ISO date "YYYY-MM-DD"
    remind_time:  str = "09:00"   # "HH:MM"
    repeat_type:  Optional[str] = None
    emoji:        Optional[str] = None


# ────────────────────── REST API ─────────────────────────────────────

@app.get("/api/records")
async def list_records(
    request:  Request,
    category: Optional[str] = Query(None),
    q:        Optional[str] = Query(None),
    limit:    int           = Query(20, le=100),
    offset:   int           = Query(0),
):
    user_id = get_user_id(request)
    records = await storage.get_records(
        user_id=user_id, category=category, query=q,
        limit=limit, offset=offset,
    )
    return {"records": records, "count": len(records)}


@app.get("/api/records/{record_id}")
async def get_record(record_id: str, request: Request):
    user_id = get_user_id(request)
    record  = await storage.get_record(record_id)
    if not record or record.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Record not found")
    return record


@app.post("/api/records", status_code=201)
async def create_record(body: RecordCreate, request: Request):
    user_id = get_user_id(request)

    if body.category not in TOPICS:
        raise HTTPException(status_code=400, detail="Unknown category")

    record = {
        "user_id":     user_id,
        "category":    body.category,
        "title":       body.title,
        "description": body.description,
        "link":        body.link,
        "photo":       body.photo,
        "rating":      max(0, min(5, body.rating)),
        "tags":        body.tags,
    }

    text = _format_card(record)
    try:
        sent = await bot.send_message(
            GROUP_ID, text,
            message_thread_id=TOPICS[body.category],
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        record["message_id"] = sent.message_id
    except Exception as e:
        logger.error(f"Telegram send error: {e}")

    record_id = await storage.add_record(record)

    # Save reminder if date provided
    if body.reminder_date:
        try:
            date_str  = body.reminder_date[:10]          # "YYYY-MM-DD"
            time_str  = body.reminder_time or "09:00"
            remind_at = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            await storage.add_reminder(
                user_id, record_id, remind_at,
                remind_time=time_str,
                repeat_type=body.repeat_type,
                emoji=body.reminder_emoji,
            )
        except Exception as e:
            logger.warning(f"Invalid reminder: {e}")

    return {"id": record_id, **record}


@app.put("/api/records/{record_id}")
async def update_record(record_id: str, body: RecordUpdate, request: Request):
    user_id = get_user_id(request)
    record  = await storage.get_record(record_id)

    if not record or record.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Record not found")

    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    await storage.update_record(record_id, updates)

    updated = await storage.get_record(record_id)
    msg_id  = updated.get("message_id")
    if msg_id:
        try:
            await bot.edit_message_text(
                _format_card(updated), GROUP_ID, msg_id,
                parse_mode="HTML", disable_web_page_preview=True,
            )
        except Exception as e:
            logger.warning(f"Could not edit Telegram message: {e}")

    return updated


@app.delete("/api/records/{record_id}")
async def delete_record(record_id: str, request: Request):
    user_id = get_user_id(request)
    record  = await storage.get_record(record_id)

    if not record or record.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Record not found")

    msg_id = record.get("message_id")
    if msg_id:
        try:
            await bot.delete_message(GROUP_ID, msg_id)
        except Exception as e:
            logger.warning(f"Could not delete Telegram message: {e}")

    await storage.delete_record(record_id)
    return {"ok": True}


@app.get("/api/stats")
async def get_stats(request: Request):
    user_id = get_user_id(request)
    return await storage.get_stats(user_id=user_id)


@app.get("/api/categories")
async def get_categories():
    return {"categories": list(TOPICS.keys())}


# ────────────────────── Reminders API ────────────────────────────────

@app.get("/api/reminders")
async def list_reminders(request: Request):
    user_id = get_user_id(request)
    reminders = await storage.get_reminders(user_id)
    return {"reminders": reminders}


@app.post("/api/reminders", status_code=201)
async def create_reminder(body: ReminderCreate, request: Request):
    user_id = get_user_id(request)
    try:
        remind_at = datetime.strptime(
            f"{body.remind_date[:10]} {body.remind_time}", "%Y-%m-%d %H:%M"
        )
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid date/time")

    rid = await storage.add_reminder(
        user_id, body.record_id, remind_at,
        remind_time=body.remind_time,
        repeat_type=body.repeat_type,
        emoji=body.emoji,
    )
    return {"id": rid}


@app.delete("/api/reminders/{reminder_id}")
async def delete_reminder(reminder_id: str, request: Request):
    get_user_id(request)
    ok = await storage.delete_reminder(reminder_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True}


# ────────────────────── Share API ────────────────────────────────────

@app.post("/api/records/{record_id}/share")
async def share_record(record_id: str, request: Request):
    """Send the record card to the user's Saved Messages so they can forward it."""
    user_id = get_user_id(request)
    record  = await storage.get_record(record_id)
    if not record or record.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Record not found")

    text = _format_card(record)
    text += f"\n\n📤 <i>Поделиться через @YourBot</i>"
    try:
        await bot.send_message(
            user_id, text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.error(f"Share error: {e}")
        raise HTTPException(status_code=500, detail="Could not send")

    return {"ok": True}


# ────────────────────── Telegram webhook ────────────────────────────

@app.post("/webhook")
async def telegram_webhook(request: Request):
    data   = await request.json()
    update = Update.model_validate(data)
    await dp.feed_update(bot, update)
    return {"ok": True}


@dp.message(Command("start", "app"))
async def cmd_start(message: AioMessage):
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="📓 Открыть заметки",
            web_app=WebAppInfo(url=MINIAPP_URL),
        )
    ]])
    await message.answer(
        "👋 Привет! Нажми кнопку чтобы открыть свои заметки:",
        reply_markup=kb,
    )


# ────────────────────── Card formatter ──────────────────────────────

def _format_card(record: dict) -> str:
    sep   = "┄" * 18
    cat   = record.get("category", "")
    title = record.get("title", "")
    desc  = record.get("description", "")
    link  = record.get("link") or ""
    stars = "⭐" * record.get("rating", 0)
    tags  = "  ".join(f"#{t}" for t in record.get("tags", []))

    lines = [sep, f"<b>{cat}</b>", "", f"📌 <b>{title}</b>"]
    if stars: lines.append(f"⭐ {stars}")
    lines += ["", f"📝 {desc}"]
    if link:  lines += ["", f"🔗 <b>Ссылка</b>\n{link}"]
    if tags:  lines += ["", f"🏷  {tags}"]
    lines.append(sep)
    return "\n".join(lines)


# ────────────────────── Static files ────────────────────────────────

app.mount("/app", StaticFiles(directory="frontend", html=True), name="frontend")


@app.get("/")
async def root():
    return {"status": "ok", "miniapp": MINIAPP_URL}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

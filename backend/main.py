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
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardButton, InlineKeyboardMarkup,
    MenuButtonWebApp, Update, WebAppInfo,
)
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
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
    """Check every 60 seconds and send due reminders via Telegram."""
    logger.info("Reminder loop started.")
    while True:
        try:
            due = await storage.get_due_reminders()
            for reminder in due:
                user_id   = reminder["user_id"]
                record_id = reminder["record_id"]
                record    = await storage.get_record(record_id)
                if not record:
                    continue

                # Build card text
                cat   = record.get("category", "")
                title = record.get("title", "")
                desc  = record.get("description", "")
                link  = record.get("link", "")
                stars = "⭐" * record.get("rating", 0)
                tags  = "  ".join(f"#{t}" for t in record.get("tags", []))

                text = (
                    f"⏰ <b>Напоминание!</b>\n\n"
                    f"┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
                    f"<b>{cat}</b>\n\n"
                    f"🎥 <b>Название</b>\n{title}\n"
                )
                if stars:
                    text += f"\n⭐ <b>Оценка</b>  {stars}\n"
                text += f"\n📝 <b>Описание</b>\n{desc}\n"
                if link:
                    text += f"\n🔗 <b>Ссылка</b>\n{link}\n"
                if tags:
                    text += f"\n🏷  {tags}\n"
                text += "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"

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
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ────────────────────── Auth helpers ────────────────────────────────

def validate_init_data(init_data: str) -> Optional[dict]:
    """Validate Telegram WebApp initData and return parsed user dict."""
    try:
        parsed  = dict(urllib.parse.parse_qsl(init_data))
        hash_   = parsed.pop("hash", "")
        data_kv = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))

        secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        check  = hmac.new(secret, data_kv.encode(), hashlib.sha256).hexdigest()

        if not hmac.compare_digest(check, hash_):
            return None

        user = json.loads(parsed.get("user", "{}"))
        return user
    except Exception as e:
        logger.error(f"initData validation error: {e}")
        return None


def get_user_id(request: Request) -> int:
    """Extract and validate user_id from X-Init-Data header."""
    init_data = request.headers.get("X-Init-Data", "")
    if not init_data:
        raise HTTPException(status_code=401, detail="Missing initData")
    user = validate_init_data(init_data)
    if not user:
        raise HTTPException(status_code=403, detail="Invalid initData")
    return int(user["id"])


# ────────────────────── Pydantic models ─────────────────────────────

class RecordCreate(BaseModel):
    category:    str
    title:       str
    description: str
    link:        Optional[str] = None
    photo:       Optional[str] = None
    rating:      int           = 0
    tags:        list[str]     = []
    reminder_days: Optional[int] = None    # legacy
    reminder_date: Optional[str] = None    # ISO string from calendar


class RecordUpdate(BaseModel):
    title:       Optional[str]       = None
    description: Optional[str]       = None
    link:        Optional[str]       = None
    rating:      Optional[int]       = None
    tags:        Optional[list[str]] = None


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
    records = await storage.get_records(user_id=user_id, category=category, query=q,
                                         limit=limit, offset=offset)
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

    # Send to Telegram group
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

    if body.reminder_date:
        try:
            remind_at = datetime.fromisoformat(body.reminder_date.replace('Z', '+00:00'))
            await storage.add_reminder(user_id, record_id, remind_at)
        except Exception as e:
            logger.warning(f"Invalid reminder_date: {e}")
    elif body.reminder_days:
        remind_at = datetime.now() + timedelta(days=body.reminder_days)
        await storage.add_reminder(user_id, record_id, remind_at)

    return {"id": record_id, **record}


@app.put("/api/records/{record_id}")
async def update_record(record_id: str, body: RecordUpdate, request: Request):
    user_id = get_user_id(request)
    record  = await storage.get_record(record_id)

    if not record or record.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Record not found")

    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    await storage.update_record(record_id, updates)

    # Update in Telegram group
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


# ────────────────────── Telegram webhook ────────────────────────────

@app.post("/webhook")
async def telegram_webhook(request: Request):
    data   = await request.json()
    update = Update.model_validate(data)
    await dp.feed_update(bot, update)
    return {"ok": True}


# Handle /start and /app commands from the bot
from aiogram.filters import Command
from aiogram.types import Message as AioMessage

@dp.message(Command("start", "app"))
async def cmd_start(message: AioMessage):
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="📓 Открыть заметки",
            web_app=WebAppInfo(url=MINIAPP_URL),
        )
    ]])
    await message.answer(
        "👋 Привет! Нажми кнопку ниже, чтобы открыть твои заметки:",
        reply_markup=kb,
    )


# ────────────────────── Card formatter ──────────────────────────────

def _format_card(record: dict) -> str:
    cat   = record.get("category", "")
    title = record.get("title", "")
    desc  = record.get("description", "")
    link  = record.get("link")
    stars = "⭐" * record.get("rating", 0)
    tags  = "  ".join(f"#{t}" for t in record.get("tags", []))
    sep   = "┄" * 18
    try:
        date = datetime.fromisoformat(record.get("created_at", "")).strftime("%d.%m.%Y")
    except Exception:
        date = ""

    lines = [sep, f"<b>{cat}</b>"]
    if date:   lines.append(f"<i>📅 {date}</i>")
    lines += ["", "🎥 <b>Название</b>", title]
    if stars:  lines += ["", f"⭐ <b>Оценка</b>  {stars}"]
    lines += ["", "📝 <b>Описание</b>", desc]
    if link:   lines += ["", f"🔗 <b>Ссылка</b>\n{link}"]
    if tags:   lines += ["", f"🏷  {tags}"]
    lines.append(sep)
    return "\n".join(lines)


# ────────────────────── Static files ────────────────────────────────

app.mount("/app", StaticFiles(directory="frontend", html=True), name="frontend")

@app.get("/")
async def root():
    return {"status": "ok", "miniapp": MINIAPP_URL}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

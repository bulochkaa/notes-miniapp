import logging, calendar as cal_mod
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy import select, delete, update, func, or_
from sqlalchemy.exc import SQLAlchemyError
from database import AsyncSessionLocal, Record, Reminder, Category

logger = logging.getLogger(__name__)

# ── Records ──────────────────────────────────────────────────────────

async def add_record(record: dict) -> str:
    async with AsyncSessionLocal() as s:
        r = Record(**{k: record[k] for k in
            ['user_id','category','title','description'] if k in record},
            link=record.get('link'), photo=record.get('photo'),
            rating=record.get('rating',0), tags=record.get('tags',[]),
            message_id=record.get('message_id'))
        s.add(r); await s.commit(); await s.refresh(r); return r.id

async def get_records(user_id=None, category=None, query=None, limit=100, offset=0):
    async with AsyncSessionLocal() as s:
        stmt = select(Record).order_by(Record.created_at.desc())
        if user_id  is not None: stmt = stmt.where(Record.user_id == user_id)
        if category: stmt = stmt.where(Record.category == category)
        if query:
            q = f"%{query.lower()}%"
            stmt = stmt.where(or_(func.lower(Record.title).like(q), func.lower(Record.description).like(q)))
        stmt = stmt.offset(offset).limit(limit)
        return [_r(r) for r in (await s.execute(stmt)).scalars().all()]

async def get_record(rid: str) -> Optional[dict]:
    async with AsyncSessionLocal() as s:
        r = (await s.execute(select(Record).where(Record.id == rid))).scalar_one_or_none()
        return _r(r) if r else None

async def update_record(rid: str, updates: dict) -> bool:
    async with AsyncSessionLocal() as s:
        try:
            await s.execute(update(Record).where(Record.id == rid).values(**updates))
            await s.commit(); return True
        except SQLAlchemyError as e:
            await s.rollback(); logger.error(e); return False

async def delete_record(rid: str) -> Optional[dict]:
    async with AsyncSessionLocal() as s:
        r = (await s.execute(select(Record).where(Record.id == rid))).scalar_one_or_none()
        if not r: return None
        d = _r(r); await s.delete(r); await s.commit(); return d

async def get_stats(user_id=None) -> dict:
    async with AsyncSessionLocal() as s:
        stmt = select(Record.category, func.count(Record.id))
        if user_id is not None: stmt = stmt.where(Record.user_id == user_id)
        by_cat = {row[0]: row[1] for row in (await s.execute(stmt.group_by(Record.category))).all()}
        return {"by_category": by_cat, "total": sum(by_cat.values())}

def _r(r: Record) -> dict:
    return {"id":r.id,"user_id":r.user_id,"category":r.category,"title":r.title,
            "description":r.description,"link":r.link,"photo":r.photo,
            "rating":r.rating,"tags":r.tags or [],"message_id":r.message_id,
            "created_at":r.created_at.isoformat() if r.created_at else ""}

# ── Reminders ────────────────────────────────────────────────────────

async def add_reminder(user_id, record_id, remind_at, remind_time=None, repeat_type=None, emoji=None) -> str:
    async with AsyncSessionLocal() as s:
        r = Reminder(user_id=user_id, record_id=record_id, remind_at=remind_at,
                     remind_time=remind_time, repeat_type=repeat_type, emoji=emoji, is_active=True)
        s.add(r); await s.commit(); await s.refresh(r); return r.id

async def get_reminders(user_id: int, include_inactive=False) -> list[dict]:
    async with AsyncSessionLocal() as s:
        stmt = select(Reminder).where(Reminder.user_id == user_id)
        if not include_inactive:
            stmt = stmt.where(Reminder.is_active == True)
        stmt = stmt.order_by(Reminder.remind_at)
        reminders = (await s.execute(stmt)).scalars().all()
        out = []
        for rem in reminders:
            rec = await get_record(rem.record_id)
            out.append({"id":rem.id,"record_id":rem.record_id,
                "record_title":rec["title"] if rec else "Удалена",
                "record_cat":rec["category"] if rec else "",
                "remind_at":rem.remind_at.isoformat(),
                "remind_time":rem.remind_time,"repeat_type":rem.repeat_type,
                "emoji":rem.emoji or "🔔","is_active":rem.is_active})
        return out

async def delete_reminder(rid: str) -> bool:
    async with AsyncSessionLocal() as s:
        # Soft delete - mark inactive
        try:
            await s.execute(update(Reminder).where(Reminder.id == rid).values(is_active=False))
            await s.commit(); return True
        except SQLAlchemyError: return False

async def get_due_reminders() -> list[dict]:
    async with AsyncSessionLocal() as s:
        try:
            now = datetime.now()
            due = (await s.execute(select(Reminder).where(
                Reminder.remind_at <= now, Reminder.is_active == True))).scalars().all()
            out = []
            for r in due:
                out.append({"user_id":r.user_id,"record_id":r.record_id,"emoji":r.emoji or "🔔","repeat_type":r.repeat_type})
                if r.repeat_type == "weekly":
                    r.remind_at = r.remind_at + timedelta(weeks=1)
                elif r.repeat_type == "monthly":
                    m = r.remind_at.month + 1; y = r.remind_at.year + (1 if m > 12 else 0); m = m if m <= 12 else 1
                    try: r.remind_at = r.remind_at.replace(year=y, month=m)
                    except ValueError: r.remind_at = r.remind_at.replace(year=y, month=m, day=cal_mod.monthrange(y,m)[1])
                else:
                    r.is_active = False
            await s.commit(); return out
        except SQLAlchemyError as e:
            await s.rollback(); logger.error(f"get_due_reminders: {e}"); return []

# ── Custom categories ────────────────────────────────────────────────

async def get_categories(user_id: int) -> list[dict]:
    async with AsyncSessionLocal() as s:
        cats = (await s.execute(select(Category).where(Category.user_id == user_id)
                                .order_by(Category.name))).scalars().all()
        return [{"id":c.id,"name":c.name,"emoji":c.emoji,"color":c.color,"topic_id":c.topic_id} for c in cats]

async def add_category(user_id: int, name: str, emoji: str, color: str = None) -> dict:
    async with AsyncSessionLocal() as s:
        c = Category(user_id=user_id, name=name, emoji=emoji, color=color)
        s.add(c); await s.commit(); await s.refresh(c)
        return {"id":c.id,"name":c.name,"emoji":c.emoji,"color":c.color,"topic_id":c.topic_id}

async def delete_category(cat_id: str) -> bool:
    async with AsyncSessionLocal() as s:
        try:
            await s.execute(delete(Category).where(Category.id == cat_id))
            await s.commit(); return True
        except SQLAlchemyError: return False

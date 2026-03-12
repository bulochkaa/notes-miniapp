"""PostgreSQL-backed storage."""

import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select, delete, update, func, or_
from sqlalchemy.exc import SQLAlchemyError

from database import AsyncSessionLocal, Record, Reminder

logger = logging.getLogger(__name__)


# ────────────────────── Records ──────────────────────

async def add_record(record: dict) -> str:
    async with AsyncSessionLocal() as session:
        try:
            r = Record(
                user_id=record["user_id"], category=record["category"],
                title=record["title"],     description=record["description"],
                link=record.get("link"),   photo=record.get("photo"),
                rating=record.get("rating", 0), tags=record.get("tags", []),
                message_id=record.get("message_id"),
            )
            session.add(r)
            await session.commit()
            await session.refresh(r)
            return r.id
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"add_record error: {e}")
            raise


async def get_records(user_id=None, category=None, query=None, limit=100, offset=0):
    async with AsyncSessionLocal() as session:
        stmt = select(Record).order_by(Record.created_at.desc())
        if user_id is not None:
            stmt = stmt.where(Record.user_id == user_id)
        if category:
            stmt = stmt.where(Record.category == category)
        if query:
            q = f"%{query.lower()}%"
            stmt = stmt.where(or_(
                func.lower(Record.title).like(q),
                func.lower(Record.description).like(q),
            ))
        stmt = stmt.offset(offset).limit(limit)
        result = await session.execute(stmt)
        return [_to_dict(r) for r in result.scalars().all()]


async def get_record(record_id: str) -> Optional[dict]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Record).where(Record.id == record_id))
        r = result.scalar_one_or_none()
        return _to_dict(r) if r else None


async def update_record(record_id: str, updates: dict) -> bool:
    async with AsyncSessionLocal() as session:
        try:
            await session.execute(update(Record).where(Record.id == record_id).values(**updates))
            await session.commit()
            return True
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"update_record error: {e}")
            return False


async def delete_record(record_id: str) -> Optional[dict]:
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(select(Record).where(Record.id == record_id))
            r = result.scalar_one_or_none()
            if not r:
                return None
            d = _to_dict(r)
            await session.delete(r)
            await session.commit()
            return d
        except SQLAlchemyError as e:
            await session.rollback()
            return None


async def get_stats(user_id=None) -> dict:
    async with AsyncSessionLocal() as session:
        stmt = select(Record.category, func.count(Record.id))
        if user_id is not None:
            stmt = stmt.where(Record.user_id == user_id)
        stmt = stmt.group_by(Record.category)
        result = await session.execute(stmt)
        by_cat = {row[0]: row[1] for row in result.all()}
        return {"by_category": by_cat, "total": sum(by_cat.values())}


# ────────────────────── Reminders ──────────────────────

async def add_reminder(user_id: int, record_id: str, remind_at: datetime,
                       remind_time: str = None, repeat_type: str = None,
                       emoji: str = None) -> str:
    async with AsyncSessionLocal() as session:
        try:
            r = Reminder(
                user_id=user_id, record_id=record_id,
                remind_at=remind_at, remind_time=remind_time,
                repeat_type=repeat_type, emoji=emoji, is_active=True,
            )
            session.add(r)
            await session.commit()
            await session.refresh(r)
            return r.id
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"add_reminder error: {e}")
            raise


async def get_reminders(user_id: int) -> list[dict]:
    """Get all active reminders for a user (for the reminders screen)."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Reminder)
            .where(Reminder.user_id == user_id, Reminder.is_active == True)
            .order_by(Reminder.remind_at)
        )
        reminders = result.scalars().all()
        out = []
        for rem in reminders:
            record = await get_record(rem.record_id)
            out.append({
                "id":          rem.id,
                "record_id":   rem.record_id,
                "record_title": record["title"] if record else "Удалена",
                "record_cat":  record["category"] if record else "",
                "remind_at":   rem.remind_at.isoformat(),
                "remind_time": rem.remind_time,
                "repeat_type": rem.repeat_type,
                "emoji":       rem.emoji or "🔔",
                "is_active":   rem.is_active,
            })
        return out


async def delete_reminder(reminder_id: str) -> bool:
    async with AsyncSessionLocal() as session:
        try:
            await session.execute(delete(Reminder).where(Reminder.id == reminder_id))
            await session.commit()
            return True
        except SQLAlchemyError as e:
            await session.rollback()
            return False


async def get_due_reminders() -> list[dict]:
    """Return reminders that are due now, reschedule repeating ones."""
    async with AsyncSessionLocal() as session:
        try:
            now = datetime.now()
            result = await session.execute(
                select(Reminder).where(
                    Reminder.remind_at <= now,
                    Reminder.is_active == True,
                )
            )
            due = result.scalars().all()
            out = []
            for r in due:
                out.append({"user_id": r.user_id, "record_id": r.record_id,
                            "emoji": r.emoji or "🔔"})
                if r.repeat_type == "weekly":
                    r.remind_at = r.remind_at + timedelta(weeks=1)
                elif r.repeat_type == "monthly":
                    # Add ~1 month
                    m = r.remind_at.month + 1
                    y = r.remind_at.year + (1 if m > 12 else 0)
                    m = m if m <= 12 else 1
                    try:
                        r.remind_at = r.remind_at.replace(year=y, month=m)
                    except ValueError:
                        import calendar
                        last = calendar.monthrange(y, m)[1]
                        r.remind_at = r.remind_at.replace(year=y, month=m, day=last)
                else:
                    r.is_active = False
                await session.commit()
            return out
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"get_due_reminders error: {e}")
            return []


def _to_dict(r: Record) -> dict:
    return {
        "id": r.id, "user_id": r.user_id, "category": r.category,
        "title": r.title, "description": r.description, "link": r.link,
        "photo": r.photo, "rating": r.rating, "tags": r.tags or [],
        "message_id": r.message_id,
        "created_at": r.created_at.isoformat() if r.created_at else "",
    }

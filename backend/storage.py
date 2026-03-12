"""
PostgreSQL-backed storage — drop-in replacement for the JSON storage.
All functions are async and use SQLAlchemy sessions.
"""

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select, delete, update, func
from sqlalchemy.exc import SQLAlchemyError

from database import AsyncSessionLocal, Record, Reminder

logger = logging.getLogger(__name__)


# ────────────────────── Records ──────────────────────

async def add_record(record: dict) -> str:
    async with AsyncSessionLocal() as session:
        try:
            r = Record(
                user_id     = record["user_id"],
                category    = record["category"],
                title       = record["title"],
                description = record["description"],
                link        = record.get("link"),
                photo       = record.get("photo"),
                rating      = record.get("rating", 0),
                tags        = record.get("tags", []),
                message_id  = record.get("message_id"),
            )
            session.add(r)
            await session.commit()
            await session.refresh(r)
            return r.id
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"add_record error: {e}")
            raise


async def get_records(
    user_id:  Optional[int] = None,
    category: Optional[str] = None,
    query:    Optional[str] = None,
    limit:    int = 100,
    offset:   int = 0,
) -> list[dict]:
    async with AsyncSessionLocal() as session:
        stmt = select(Record).order_by(Record.created_at.desc())

        if user_id is not None:
            stmt = stmt.where(Record.user_id == user_id)
        if category:
            stmt = stmt.where(Record.category == category)
        if query:
            q = f"%{query.lower()}%"
            from sqlalchemy import or_
            from sqlalchemy import func as safunc
            stmt = stmt.where(or_(
                safunc.lower(Record.title).like(q),
                safunc.lower(Record.description).like(q),
            ))

        stmt = stmt.offset(offset).limit(limit)
        result = await session.execute(stmt)
        return [_to_dict(r) for r in result.scalars().all()]


async def get_record(record_id: str) -> Optional[dict]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Record).where(Record.id == record_id)
        )
        r = result.scalar_one_or_none()
        return _to_dict(r) if r else None


async def update_record(record_id: str, updates: dict) -> bool:
    async with AsyncSessionLocal() as session:
        try:
            await session.execute(
                update(Record).where(Record.id == record_id).values(**updates)
            )
            await session.commit()
            return True
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"update_record error: {e}")
            return False


async def delete_record(record_id: str) -> Optional[dict]:
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                select(Record).where(Record.id == record_id)
            )
            r = result.scalar_one_or_none()
            if not r:
                return None
            d = _to_dict(r)
            await session.delete(r)
            await session.commit()
            return d
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"delete_record error: {e}")
            return None


async def get_stats(user_id: Optional[int] = None) -> dict:
    async with AsyncSessionLocal() as session:
        stmt = select(Record.category, func.count(Record.id))
        if user_id is not None:
            stmt = stmt.where(Record.user_id == user_id)
        stmt = stmt.group_by(Record.category)
        result = await session.execute(stmt)
        rows = result.all()
        by_cat = {row[0]: row[1] for row in rows}
        total  = sum(by_cat.values())
        return {"by_category": by_cat, "total": total}


# ────────────────────── Reminders ──────────────────────

async def add_reminder(user_id: int, record_id: str, remind_at: datetime) -> None:
    async with AsyncSessionLocal() as session:
        try:
            r = Reminder(user_id=user_id, record_id=record_id, remind_at=remind_at)
            session.add(r)
            await session.commit()
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"add_reminder error: {e}")


async def get_due_reminders() -> list[dict]:
    async with AsyncSessionLocal() as session:
        try:
            now    = datetime.now()
            result = await session.execute(
                select(Reminder).where(Reminder.remind_at <= now)
            )
            due = result.scalars().all()
            if not due:
                return []
            ids = [r.id for r in due]
            out = [{"user_id": r.user_id, "record_id": r.record_id} for r in due]
            await session.execute(
                delete(Reminder).where(Reminder.id.in_(ids))
            )
            await session.commit()
            return out
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"get_due_reminders error: {e}")
            return []


# ────────────────────── Helper ──────────────────────

def _to_dict(r: Record) -> dict:
    return {
        "id":          r.id,
        "user_id":     r.user_id,
        "category":    r.category,
        "title":       r.title,
        "description": r.description,
        "link":        r.link,
        "photo":       r.photo,
        "rating":      r.rating,
        "tags":        r.tags or [],
        "message_id":  r.message_id,
        "created_at":  r.created_at.isoformat() if r.created_at else "",
    }

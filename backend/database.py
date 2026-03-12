"""
PostgreSQL database setup using SQLAlchemy async.
Tables are created automatically on first startup.
New columns are added via ALTER TABLE if missing.
"""

import os
import logging
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, Integer,
    String, Text, ARRAY, text,
)
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "").replace(
    "postgres://", "postgresql+asyncpg://"
).replace(
    "postgresql://", "postgresql+asyncpg://"
)

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Record(Base):
    __tablename__ = "records"

    id          = Column(String(8),   primary_key=True, default=lambda: str(uuid.uuid4())[:8])
    user_id     = Column(BigInteger,  nullable=False, index=True)
    category    = Column(String(64),  nullable=False)
    title       = Column(String(256), nullable=False)
    description = Column(Text,        nullable=False)
    link        = Column(Text,        nullable=True)
    photo       = Column(Text,        nullable=True)
    rating      = Column(Integer,     default=0)
    tags        = Column(ARRAY(Text), default=list)
    message_id  = Column(BigInteger,  nullable=True)
    created_at  = Column(DateTime,    default=datetime.now)


class Reminder(Base):
    __tablename__ = "reminders"

    id          = Column(String(8),  primary_key=True, default=lambda: str(uuid.uuid4())[:8])
    user_id     = Column(BigInteger, nullable=False, index=True)
    record_id   = Column(String(8),  nullable=False)
    remind_at   = Column(DateTime,   nullable=False)
    remind_time = Column(String(5),  nullable=True)
    repeat_type = Column(String(16), nullable=True)
    emoji       = Column(String(8),  nullable=True)
    is_active   = Column(Boolean,    default=True)


async def init_db():
    """Create tables and run migrations for new columns."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Migration: add new columns to reminders if they don't exist
    migrations = [
        "ALTER TABLE reminders ADD COLUMN IF NOT EXISTS remind_time VARCHAR(5)",
        "ALTER TABLE reminders ADD COLUMN IF NOT EXISTS repeat_type VARCHAR(16)",
        "ALTER TABLE reminders ADD COLUMN IF NOT EXISTS emoji VARCHAR(8)",
        "ALTER TABLE reminders ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE",
    ]
    async with engine.begin() as conn:
        for sql in migrations:
            try:
                await conn.execute(text(sql))
                logger.info(f"Migration OK: {sql[:50]}")
            except Exception as e:
                logger.warning(f"Migration skipped: {e}")

    logger.info("Database tables ready.")

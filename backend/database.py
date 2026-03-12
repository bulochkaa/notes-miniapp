"""
PostgreSQL database setup using SQLAlchemy async.
Tables are created automatically on first startup.
"""

import os
import logging
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, Integer,
    String, Text, ARRAY,
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

    id         = Column(String(8),  primary_key=True, default=lambda: str(uuid.uuid4())[:8])
    user_id    = Column(BigInteger, nullable=False, index=True)
    record_id  = Column(String(8),  nullable=False)
    remind_at  = Column(DateTime,   nullable=False)
    # New fields
    remind_time   = Column(String(5),   nullable=True)   # "09:00"
    repeat_type   = Column(String(16),  nullable=True)   # null | "weekly" | "monthly"
    emoji         = Column(String(8),   nullable=True)   # reminder emoji
    is_active     = Column(Boolean,     default=True)


async def init_db():
    """Create all tables if they don't exist."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables ready.")

import os, logging, uuid
from datetime import datetime
from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, String, Text, ARRAY, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL","").replace("postgres://","postgresql+asyncpg://").replace("postgresql://","postgresql+asyncpg://")
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

class Base(DeclarativeBase): pass

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
    is_archived = Column(Boolean,     default=False)
    is_pinned   = Column(Boolean,     default=False)
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

class Category(Base):
    __tablename__ = "categories"
    id       = Column(String(8),  primary_key=True, default=lambda: str(uuid.uuid4())[:8])
    user_id  = Column(BigInteger, nullable=False, index=True)
    name     = Column(String(64), nullable=False)
    emoji    = Column(String(8),  nullable=False, default="📁")
    color    = Column(String(16), nullable=True)
    topic_id = Column(Integer,    nullable=True)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    migrations = [
        "ALTER TABLE reminders ADD COLUMN IF NOT EXISTS remind_time VARCHAR(5)",
        "ALTER TABLE reminders ADD COLUMN IF NOT EXISTS repeat_type VARCHAR(16)",
        "ALTER TABLE reminders ADD COLUMN IF NOT EXISTS emoji VARCHAR(8)",
        "ALTER TABLE reminders ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE",
        "ALTER TABLE records   ADD COLUMN IF NOT EXISTS photo TEXT",
        "ALTER TABLE records   ADD COLUMN IF NOT EXISTS is_archived BOOLEAN DEFAULT FALSE",
        "ALTER TABLE records   ADD COLUMN IF NOT EXISTS is_pinned BOOLEAN DEFAULT FALSE",
    ]
    async with engine.begin() as conn:
        for sql in migrations:
            try: await conn.execute(text(sql))
            except Exception as e: logger.warning(f"Migration skipped: {e}")
    logger.info("Database tables ready.")

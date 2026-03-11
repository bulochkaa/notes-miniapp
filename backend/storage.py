"""
Async-safe JSON storage using a file lock so concurrent requests don't corrupt data.
For production use PostgreSQL instead.
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)
STORAGE_FILE = "data.json"
_lock = asyncio.Lock()


def _read_raw() -> dict:
    if not os.path.exists(STORAGE_FILE):
        return {"records": [], "reminders": []}
    try:
        with open(STORAGE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Storage read error: {e}")
        return {"records": [], "reminders": []}


def _write_raw(data: dict) -> None:
    with open(STORAGE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)


async def _load() -> dict:
    async with _lock:
        return _read_raw()


async def _save(data: dict) -> None:
    async with _lock:
        _write_raw(data)


# ────────────────────── Records ──────────────────────

async def add_record(record: dict) -> str:
    data = await _load()
    record["id"]         = str(uuid.uuid4())[:8]
    record["created_at"] = datetime.now().isoformat()
    data["records"].append(record)
    await _save(data)
    return record["id"]


async def get_records(
    user_id:  Optional[int] = None,
    category: Optional[str] = None,
    query:    Optional[str] = None,
    limit:    int = 100,
    offset:   int = 0,
) -> list[dict]:
    data    = await _load()
    records = data["records"]

    if user_id is not None:
        records = [r for r in records if r.get("user_id") == user_id]
    if category:
        records = [r for r in records if r.get("category") == category]
    if query:
        q       = query.lower()
        records = [
            r for r in records
            if q in r.get("title", "").lower()
            or q in r.get("description", "").lower()
            or q in " ".join(r.get("tags", [])).lower()
        ]

    records = list(reversed(records))          # newest first
    return records[offset : offset + limit]


async def get_record(record_id: str) -> Optional[dict]:
    for r in (await _load())["records"]:
        if r["id"] == record_id:
            return r
    return None


async def update_record(record_id: str, updates: dict) -> bool:
    data = await _load()
    for i, r in enumerate(data["records"]):
        if r["id"] == record_id:
            data["records"][i].update(updates)
            await _save(data)
            return True
    return False


async def delete_record(record_id: str) -> Optional[dict]:
    data   = await _load()
    before = len(data["records"])
    target = next((r for r in data["records"] if r["id"] == record_id), None)
    data["records"] = [r for r in data["records"] if r["id"] != record_id]
    if len(data["records"]) < before:
        await _save(data)
        return target
    return None


async def get_stats(user_id: Optional[int] = None) -> dict:
    records = await get_records(user_id=user_id, limit=9999)
    stats: dict[str, int] = {}
    for r in records:
        cat = r.get("category", "Другое")
        stats[cat] = stats.get(cat, 0) + 1
    return {"by_category": stats, "total": len(records)}


# ────────────────────── Reminders ──────────────────────

async def add_reminder(user_id: int, record_id: str, remind_at: datetime) -> None:
    data = await _load()
    data["reminders"].append({
        "id":        str(uuid.uuid4())[:8],
        "user_id":   user_id,
        "record_id": record_id,
        "remind_at": remind_at.isoformat(),
    })
    await _save(data)


async def get_due_reminders() -> list[dict]:
    data = await _load()
    now, due, remaining = datetime.now(), [], []
    for r in data["reminders"]:
        (due if datetime.fromisoformat(r["remind_at"]) <= now else remaining).append(r)
    if due:
        data["reminders"] = remaining
        await _save(data)
    return due

"""MongoDB connection — single AsyncIOMotorClient shared across the process."""
from __future__ import annotations

import asyncio
import logging
import os

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

logger = logging.getLogger("db")

MONGODB_URL = os.getenv("MONGODB_URL", "")
DB_NAME = os.getenv("MONGODB_DB", "genzpublic")

_client: AsyncIOMotorClient | None = None  # type: ignore[type-arg]
_connect_lock = asyncio.Lock()


def get_db() -> AsyncIOMotorDatabase:  # type: ignore[type-arg]
    if _client is None:
        raise RuntimeError("Database not connected — call connect_db() first")
    return _client[DB_NAME]


async def ensure_db() -> AsyncIOMotorDatabase:  # type: ignore[type-arg]
    """Connect on first use so the agent child can read app news without API lifespan."""
    if _client is not None:
        return get_db()
    async with _connect_lock:
        if _client is None:
            await connect_db()
        return get_db()


async def connect_db() -> None:
    global _client
    if not MONGODB_URL:
        raise RuntimeError("MONGODB_URL is not set")
    logger.info("Connecting to MongoDB…")
    _client = AsyncIOMotorClient(MONGODB_URL, serverSelectionTimeoutMS=6_000)
    await _client.admin.command("ping")  # fail fast if unreachable
    db = get_db()
    # Indexes — unique where upserts need it
    await db.devices.create_index("device_id", unique=True)
    await db.sessions.create_index("device_id")
    await db.sessions.create_index("started_at")
    await db.ip_trials.create_index("ip", unique=True)
    logger.info("MongoDB ready: db=%s", DB_NAME)


async def close_db() -> None:
    global _client
    if _client:
        _client.close()
        _client = None
        logger.info("MongoDB connection closed")

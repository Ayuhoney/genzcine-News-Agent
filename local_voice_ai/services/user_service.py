"""Device + session persistence backed by MongoDB."""
from __future__ import annotations

from datetime import datetime, timezone

from .db import get_db

_UTC = timezone.utc


# ── Devices ───────────────────────────────────────────────────────────────────

async def get_or_create_device(device_id: str) -> dict:
    """Return device doc, creating it on first visit."""
    db = get_db()
    now = datetime.now(_UTC)
    doc = await db.devices.find_one({"device_id": device_id}, {"_id": 0})
    if doc is None:
        doc = {
            "device_id": device_id,
            "onboarded": False,
            "avatar_face_id": None,
            "participant_name": None,
            "created_at": now,
            "last_seen": now,
        }
        await db.devices.insert_one({**doc})
    else:
        await db.devices.update_one(
            {"device_id": device_id},
            {"$set": {"last_seen": now}},
        )
    return doc


async def mark_onboarded(device_id: str) -> None:
    db = get_db()
    await db.devices.update_one(
        {"device_id": device_id},
        {"$set": {"onboarded": True, "last_seen": datetime.now(_UTC)}},
        upsert=True,
    )


async def save_avatar(device_id: str, face_id: str) -> None:
    db = get_db()
    await db.devices.update_one(
        {"device_id": device_id},
        {"$set": {"avatar_face_id": face_id, "last_seen": datetime.now(_UTC)}},
        upsert=True,
    )


async def save_participant_name(device_id: str, name: str) -> None:
    db = get_db()
    await db.devices.update_one(
        {"device_id": device_id},
        {"$set": {"participant_name": name, "last_seen": datetime.now(_UTC)}},
        upsert=True,
    )


# ── Sessions ──────────────────────────────────────────────────────────────────

async def log_session(
    device_id: str,
    participant_name: str,
    session_type: str,
    room_name: str,
    face_id: str | None,
) -> None:
    db = get_db()
    await db.sessions.insert_one(
        {
            "device_id": device_id,
            "participant_name": participant_name,
            "session_type": session_type,
            "room_name": room_name,
            "face_id": face_id,
            "started_at": datetime.now(_UTC),
            # filled by complete_session on disconnect
            "ended_at": None,
            "duration_seconds": None,
            "messages_count": None,
            "posture_analyses": None,
        }
    )


async def complete_session(
    device_id: str,
    room_name: str,
    duration_seconds: int,
    messages_count: int,
    posture_analyses: int,
) -> None:
    db = get_db()
    now = datetime.now(_UTC)
    secs = max(0, duration_seconds)
    await db.sessions.update_one(
        {"device_id": device_id, "room_name": room_name},
        {
            "$set": {
                "ended_at": now,
                "duration_seconds": secs,
                "messages_count": max(0, messages_count),
                "posture_analyses": max(0, posture_analyses),
            }
        },
    )
    # Accumulate trial seconds used (atomic — safe under concurrent sessions)
    await db.devices.update_one(
        {"device_id": device_id},
        {"$inc": {"trial_used_seconds": secs}, "$set": {"last_seen": now}},
        upsert=True,
    )


async def get_trial_status(device_id: str, ip: str = "") -> dict:
    """Return trial usage combining device_id + IP. is_premium bypasses the trial gate."""
    db = get_db()

    doc = await db.devices.find_one({"device_id": device_id}, {"_id": 0})
    if doc is None:
        device_used = 0
        is_premium = False
    else:
        device_used = int(doc.get("trial_used_seconds", 0))
        is_premium = bool(doc.get("is_premium", False))

    if is_premium:
        return {"trial_used_seconds": 0, "is_premium": True}

    # IP layer — catches localStorage-reset / incognito bypass
    ip_used = 0
    if ip:
        ip_doc = await db.ip_trials.find_one({"ip": ip}, {"_id": 0})
        if ip_doc:
            ip_used = int(ip_doc.get("trial_used_seconds", 0))

    return {
        "trial_used_seconds": max(device_used, ip_used),
        "is_premium": False,
    }


async def record_ip_trial_seconds(ip: str, seconds: int) -> None:
    """Accumulate trial seconds against an IP — called alongside complete_session."""
    if not ip or seconds <= 0:
        return
    db = get_db()
    await db.ip_trials.update_one(
        {"ip": ip},
        {"$inc": {"trial_used_seconds": seconds}, "$set": {"last_seen": datetime.now(_UTC)}},
        upsert=True,
    )


async def mark_premium(device_id: str) -> None:
    """Grant premium access — call this after payment confirmation."""
    db = get_db()
    await db.devices.update_one(
        {"device_id": device_id},
        {"$set": {"is_premium": True, "last_seen": datetime.now(_UTC)}},
        upsert=True,
    )

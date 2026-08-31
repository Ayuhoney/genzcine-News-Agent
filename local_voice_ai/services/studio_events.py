"""LiveKit data-channel events for GenzCine news-studio UIs (phone + web)."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from livekit import rtc

logger = logging.getLogger("studio")

STUDIO_TOPIC = "genzcine_studio"


async def publish_studio_event(room: rtc.Room | None, event: dict[str, Any]) -> None:
    """Publish a typed studio event to every connected client."""
    if room is None:
        return
    payload = {**event, "timestamp": event.get("timestamp", time.time())}
    try:
        await room.local_participant.publish_data(
            json.dumps(payload).encode(),
            reliable=True,
            topic=STUDIO_TOPIC,
        )
    except Exception:
        logger.exception("studio event publish failed: type=%s", event.get("type"))


def headline_article(article: dict[str, Any], *, index: int) -> dict[str, Any]:
    return {
        "id": f"h-{index}",
        "index": index,
        "title": article.get("title", ""),
        "description": article.get("description", ""),
        "source": article.get("source", ""),
        "pubDate": article.get("pubDate", ""),
        "link": article.get("link", ""),
    }

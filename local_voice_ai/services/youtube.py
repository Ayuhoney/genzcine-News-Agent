"""YouTube Data API v3 lookup — used by the agent's play_news_video tool.

Paired with NewsData.io (services/news.py): NewsData supplies the text
intelligence (headlines/summaries), this module supplies the visual
intelligence (a real, relevant video for the same story). Playback happens
client-side through YouTube's own embeddable iframe player — this module only
ever fetches metadata, never video/audio data.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional, TypedDict

import httpx

logger = logging.getLogger("youtube")

YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
EMBED_REFERER = "https://news.200.234.41.50.sslip.io/"


class VideoResult(TypedDict):
    video_id: str
    title: str
    thumbnail_url: str
    channel_title: str


async def _is_embed_playable(client: httpx.AsyncClient, video_id: str) -> bool:
    try:
        resp = await client.get(
            f"https://www.youtube.com/embed/{video_id}",
            headers={"Referer": EMBED_REFERER},
            timeout=3.5,
        )
        if resp.status_code != 200:
            return False
        text = resp.text
        if '"status":"UNPLAYABLE"' in text or '"status":"LOGIN_REQUIRED"' in text:
            return False
        return True
    except Exception:
        return True


async def search_news_video(query: str) -> Optional[VideoResult]:
    """Find the top relevant, embeddable YouTube video for query."""
    api_key = os.getenv("YOUTUBE_API_KEY", "")
    if not api_key:
        logger.warning("YOUTUBE_API_KEY not set — cannot search YouTube")
        return None

    clean_q = query.strip()[:100]
    if clean_q and "news" not in clean_q.lower() and len(clean_q) < 40:
        clean_q = f"{clean_q} news"

    params: dict[str, str] = {
        "part": "snippet",
        "q": clean_q,
        "type": "video",
        "order": "relevance",
        "maxResults": "5",
        "safeSearch": "strict",
        "videoEmbeddable": "true",
        "videoSyndicated": "true",
        "key": api_key,
    }

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(YOUTUBE_SEARCH_URL, params=params)
            if resp.status_code != 200:
                logger.warning("YouTube API returned %s: %s", resp.status_code, resp.text[:200])
                return None
            payload: dict[str, Any] = resp.json()
            items = payload.get("items") or []
            if not items:
                return None

            chosen = None
            for item in items:
                vid = (item.get("id") or {}).get("videoId")
                if not vid:
                    continue
                if await _is_embed_playable(client, str(vid)):
                    chosen = item
                    break
            if chosen is None:
                chosen = items[0]
    except (httpx.RequestError, httpx.HTTPError, ValueError):
        logger.exception("YouTube API request failed")
        return None

    video_id = (chosen.get("id") or {}).get("videoId")
    if not video_id:
        return None
    snippet = chosen.get("snippet") or {}
    title = snippet.get("title") or query
    thumbs = snippet.get("thumbnails") or {}
    thumb = (
        (thumbs.get("high") or {}).get("url")
        or (thumbs.get("medium") or {}).get("url")
        or (thumbs.get("default") or {}).get("url")
        or ""
    )
    return {
        "video_id": str(video_id),
        "title": str(title),
        "thumbnail_url": str(thumb),
        "channel_title": str(snippet.get("channelTitle") or ""),
    }

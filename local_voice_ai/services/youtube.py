"""YouTube Data API v3 lookup — used by the agent's ``play_news_video`` tool.

Paired with NewsData.io (``services/news.py``): NewsData supplies the text
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


class VideoResult(TypedDict):
    video_id: str
    title: str


async def search_news_video(query: str) -> Optional[VideoResult]:
    """Find the top relevant YouTube video for ``query``. Returns None on failure/no match."""
    api_key = os.getenv("YOUTUBE_API_KEY", "")
    if not api_key:
        logger.warning("YOUTUBE_API_KEY not set — cannot search YouTube")
        return None

    params: dict[str, str] = {
        "part": "snippet",
        "q": query[:100],
        "type": "video",
        "order": "relevance",
        "maxResults": "1",
        "safeSearch": "strict",
        "key": api_key,
    }

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(YOUTUBE_SEARCH_URL, params=params)
        if resp.status_code != 200:
            logger.warning("YouTube API returned %s: %s", resp.status_code, resp.text[:200])
            return None
        payload: dict[str, Any] = resp.json()
    except (httpx.RequestError, httpx.HTTPError, ValueError):
        logger.exception("YouTube API request failed")
        return None

    items = payload.get("items") or []
    if not items:
        return None
    item = items[0]
    video_id = (item.get("id") or {}).get("videoId")
    if not video_id:
        return None
    title = (item.get("snippet") or {}).get("title") or query
    return {"video_id": str(video_id), "title": str(title)}

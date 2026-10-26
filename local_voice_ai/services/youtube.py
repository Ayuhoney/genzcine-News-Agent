"""YouTube Data API v3 lookup — used by the agent's play_news_video tool.

Paired with NewsData.io (services/news.py): NewsData supplies the text
intelligence (headlines/summaries), this module supplies the visual
intelligence (a real, relevant video for the same story). Playback happens
client-side through YouTube's own embeddable iframe player — this module only
ever fetches metadata, never video/audio data.
"""
from __future__ import annotations

import asyncio
import html
import logging
import os
import re
import time
from typing import Any, Optional, TypedDict

import httpx

logger = logging.getLogger("youtube")

YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
EMBED_REFERER = "https://news.200.234.41.50.sslip.io/"

_VIDEO_CACHE_TTL = 12 * 3600  # 12 hours cache
_VIDEO_CACHE: dict[str, tuple[float, VideoResult]] = {}
_VIDEO_INFLIGHT: dict[str, asyncio.Future] = {}


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


_REPUTABLE_NEWS_CHANNELS = (
    "aaj tak", "abp news", "ndtv", "india today", "zee news", "bbc news",
    "ptc news", "times now", "republic", "news18", "dd news", "ani",
    "hindustan times", "the hindu", "times of india", "dainik bhaskar", "amar ujala",
)


def _clean_headline_for_search(text: str) -> str:
    """Strip news outlet attribution suffixes like ' - Hindustan Times' or quotes."""
    clean = (text or "").strip()
    clean = re.sub(r'["\']', '', clean)
    clean = re.sub(
        r"\s*[-|•–—]\s*(Hindustan Times|The Hindu|Times of India|NDTV.*|India Today|ANI|PTI|News18.*|Zee News|Amar Ujala|Dainik Bhaskar|Punjab Kesari|YouTube).*$",
        "",
        clean,
        flags=re.IGNORECASE,
    ).strip()
    return clean[:100]


async def search_news_video(query: str, language: str = "") -> Optional[VideoResult]:
    """Find the top relevant, embeddable YouTube video for query."""
    api_key = os.getenv("YOUTUBE_API_KEY", "")
    if not api_key:
        logger.warning("YOUTUBE_API_KEY not set — cannot search YouTube")
        return None

    clean_q = _clean_headline_for_search(query)
    if clean_q and "news" not in clean_q.lower() and len(clean_q) < 40:
        clean_q = f"{clean_q} news"

    lang_code = (language or "").split("-")[0].lower()
    cache_key = f"{clean_q.lower()}:{lang_code}"
    
    # 1. Check in-memory 12h cache
    cached = _VIDEO_CACHE.get(cache_key)
    if cached and (time.time() - cached[0]) < _VIDEO_CACHE_TTL:
        logger.info("YouTube video cache hit for %r -> %s", clean_q, cached[1]["video_id"])
        return cached[1]

    # 2. Check if identical search is already in flight (deduplicate)
    existing = _VIDEO_INFLIGHT.get(cache_key)
    if existing is not None and not existing.done():
        try:
            return await existing
        except Exception:
            pass

    loop = asyncio.get_running_loop()
    fut: asyncio.Future = loop.create_future()
    _VIDEO_INFLIGHT[cache_key] = fut

    try:
        params: dict[str, str] = {
            "part": "snippet",
            "q": clean_q,
            "type": "video",
            "order": "relevance",
            "maxResults": "7",
            "safeSearch": "strict",
            "videoEmbeddable": "true",
            "videoSyndicated": "true",
            "key": api_key,
        }
        if lang_code in ("hi", "pa", "bn", "ta", "te", "mr", "gu", "en"):
            params["relevanceLanguage"] = lang_code

        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(YOUTUBE_SEARCH_URL, params=params)
            if resp.status_code != 200:
                logger.warning("YouTube API returned %s: %s", resp.status_code, resp.text[:200])
                if not fut.done():
                    fut.set_result(None)
                return None
            payload: dict[str, Any] = resp.json()
            items = payload.get("items") or []
            if not items:
                if not fut.done():
                    fut.set_result(None)
                return None

            playable_items: list[dict[str, Any]] = []
            for item in items:
                vid = (item.get("id") or {}).get("videoId")
                if not vid:
                    continue
                if await _is_embed_playable(client, str(vid)):
                    playable_items.append(item)

            if not playable_items:
                chosen = items[0]
            else:
                # Prefer recognized news broadcast channels
                chosen = None
                for candidate in playable_items:
                    snippet = candidate.get("snippet") or {}
                    chan = str(snippet.get("channelTitle") or "").lower()
                    if any(rep in chan for rep in _REPUTABLE_NEWS_CHANNELS):
                        chosen = candidate
                        break
                if chosen is None:
                    chosen = playable_items[0]

        video_id = (chosen.get("id") or {}).get("videoId")
        if not video_id:
            if not fut.done():
                fut.set_result(None)
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
        res: VideoResult = {
            "video_id": str(video_id),
            "title": html.unescape(str(title)).strip(),
            "thumbnail_url": str(thumb),
            "channel_title": html.unescape(str(snippet.get("channelTitle") or "")).strip(),
        }
        _VIDEO_CACHE[cache_key] = (time.time(), res)
        if not fut.done():
            fut.set_result(res)
        return res
    except (httpx.RequestError, httpx.HTTPError, ValueError) as exc:
        logger.exception("YouTube API request failed")
        if not fut.done():
            fut.set_result(None)
        return None
    finally:
        if _VIDEO_INFLIGHT.get(cache_key) is fut:
            _VIDEO_INFLIGHT.pop(cache_key, None)


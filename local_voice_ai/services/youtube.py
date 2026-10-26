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
import json
import logging
import os
from pathlib import Path
import re
import time
from typing import Any, Optional, TypedDict

import httpx

logger = logging.getLogger("youtube")

YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
EMBED_REFERER = "https://news.200.234.41.50.sslip.io/"

_VIDEO_CACHE_TTL = 24 * 3600  # 24 hours persistent cache
_VIDEO_CACHE: dict[str, tuple[float, VideoResult]] = {}
_VIDEO_INFLIGHT: dict[str, asyncio.Future] = {}
_QUOTA_EXCEEDED_UNTIL: float = 0.0


def _get_cache_file() -> Path:
    env_path = os.getenv("YOUTUBE_CACHE_FILE")
    if env_path:
        return Path(env_path)
    if Path("/models").is_dir():
        return Path("/models/video_cache.json")
    repo_data = Path(__file__).resolve().parent.parent.parent / "data"
    repo_data.mkdir(parents=True, exist_ok=True)
    return repo_data / "video_cache.json"


def _load_disk_cache() -> None:
    try:
        path = _get_cache_file()
        if not path.is_file():
            return
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        now = time.time()
        count = 0
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, list) and len(v) == 2:
                    ts, res = v
                    if (now - float(ts)) < _VIDEO_CACHE_TTL and isinstance(res, dict) and "video_id" in res:
                        _VIDEO_CACHE[k] = (float(ts), res)
                        count += 1
                elif isinstance(v, dict) and "timestamp" in v and "result" in v:
                    ts = v["timestamp"]
                    res = v["result"]
                    if (now - float(ts)) < _VIDEO_CACHE_TTL and isinstance(res, dict) and "video_id" in res:
                        _VIDEO_CACHE[k] = (float(ts), res)
                        count += 1
        logger.info("Loaded %d cached YouTube videos from %s", count, path)
    except Exception as exc:
        logger.warning("Failed to load video cache from disk: %s", exc)


def _save_disk_cache() -> None:
    try:
        path = _get_cache_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        now = time.time()
        items = dict(_VIDEO_CACHE)
        data = {
            k: [ts, res]
            for k, (ts, res) in items.items()
            if (now - ts) < _VIDEO_CACHE_TTL
        }
        tmp_path = path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp_path.replace(path)
    except Exception as exc:
        logger.warning("Failed to save video cache to disk: %s", exc)


_load_disk_cache()


class VideoResult(TypedDict):
    video_id: str
    title: str
    thumbnail_url: str
    channel_title: str


_FALLBACK_NEWS_VIDEOS: list[tuple[re.Pattern, VideoResult]] = [
    (re.compile(r"tech|gadget|business|market|startup", re.I), {
        "video_id": "hw7lczdv6jg",
        "title": "Technology & Gadgets Report | BBC News",
        "thumbnail_url": "https://i.ytimg.com/vi/hw7lczdv6jg/hqdefault.jpg",
        "channel_title": "BBC News",
    }),
    (re.compile(r"up|uttar\s*pradesh|lucknow|varanasi|kanpur|यूपी", re.I), {
        "video_id": "KQkVHfa0XHw",
        "title": "UP News Bulletins | Top Ground Updates",
        "thumbnail_url": "https://i.ytimg.com/vi/KQkVHfa0XHw/hqdefault.jpg",
        "channel_title": "Zee News",
    }),
    (re.compile(r"delhi|ncr|milan\s*garden|दिल्ली", re.I), {
        "video_id": "O-xqPm_VPUk",
        "title": "Delhi News Today | Top Ground Updates",
        "thumbnail_url": "https://i.ytimg.com/vi/O-xqPm_VPUk/hqdefault.jpg",
        "channel_title": "NDTV",
    }),
    (re.compile(r"punjab|chandigarh|amritsar|ludhiana|ਪੰਜਾਬ", re.I), {
        "video_id": "a_PzqyHtb2Q",
        "title": "Punjab News Headlines | PTC News",
        "thumbnail_url": "https://i.ytimg.com/vi/a_PzqyHtb2Q/hqdefault.jpg",
        "channel_title": "PTC News",
    }),
    (re.compile(r"mumbai|maharashtra|pune|मुंबई|महाराष्ट्र", re.I), {
        "video_id": "omSYrjCtfD8",
        "title": "Maharashtra & Mumbai News Today",
        "thumbnail_url": "https://i.ytimg.com/vi/omSYrjCtfD8/hqdefault.jpg",
        "channel_title": "ABP Majha",
    }),
]

_DEFAULT_FALLBACK_VIDEO: VideoResult = {
    "video_id": "sjblf2STk7k",
    "title": "India Today Live News | Top Breaking Headlines",
    "thumbnail_url": "https://i.ytimg.com/vi/sjblf2STk7k/hqdefault.jpg",
    "channel_title": "India Today",
}


def _fallback_video(query: str) -> VideoResult:
    q = (query or "").lower()
    for pat, item in _FALLBACK_NEWS_VIDEOS:
        if pat.search(q):
            return item
    return _DEFAULT_FALLBACK_VIDEO


async def _is_embed_playable(client: httpx.AsyncClient, video_id: str) -> bool:
    try:
        resp = await client.get(
            f"https://www.youtube.com/embed/{video_id}",
            headers={"Referer": EMBED_REFERER, "User-Agent": "Mozilla/5.0"},
            timeout=2.0,
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
        logger.warning("YOUTUBE_API_KEY not set — using verified news fallback")
        return _fallback_video(query)

    clean_q = _clean_headline_for_search(query)
    if clean_q and "news" not in clean_q.lower() and len(clean_q) < 40:
        clean_q = f"{clean_q} news"

    lang_code = (language or "").split("-")[0].lower()
    cache_key = f"{clean_q.lower()}:{lang_code}"
    
    # 1. Check in-memory / persistent cache
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

    global _QUOTA_EXCEEDED_UNTIL
    if time.time() < _QUOTA_EXCEEDED_UNTIL:
        logger.info(
            "YouTube quota currently throttled (until +%0.0fs) — serving fallback instantly",
            _QUOTA_EXCEEDED_UNTIL - time.time(),
        )
        fb = _fallback_video(clean_q)
        return fb

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
                resp_text = resp.text
                if resp.status_code in (403, 429) or "quotaExceeded" in resp_text:
                    _QUOTA_EXCEEDED_UNTIL = time.time() + 1800
                    logger.warning(
                        "YouTube quota exceeded (status %s) — throttled for 30m; serving fallback",
                        resp.status_code,
                    )
                else:
                    logger.warning(
                        "YouTube API returned %s: %s — using verified news fallback",
                        resp.status_code,
                        resp_text[:200],
                    )
                fb = _fallback_video(clean_q)
                _VIDEO_CACHE[cache_key] = (time.time(), fb)
                _save_disk_cache()
                if not fut.done():
                    fut.set_result(fb)
                return fb

            payload: dict[str, Any] = resp.json()
            items = payload.get("items") or []
            if not items:
                fb = _fallback_video(clean_q)
                _VIDEO_CACHE[cache_key] = (time.time(), fb)
                _save_disk_cache()
                if not fut.done():
                    fut.set_result(fb)
                return fb

            async def _check_item(it: dict[str, Any]) -> tuple[dict[str, Any], bool]:
                v = (it.get("id") or {}).get("videoId")
                if not v:
                    return it, False
                ok = await _is_embed_playable(client, str(v))
                return it, ok

            top_candidates = items[:4]
            checked = await asyncio.gather(*[_check_item(it) for it in top_candidates], return_exceptions=True)
            playable_items: list[dict[str, Any]] = [
                res[0] for res in checked if isinstance(res, tuple) and res[1]
            ]

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
            fb = _fallback_video(clean_q)
            _VIDEO_CACHE[cache_key] = (time.time(), fb)
            _save_disk_cache()
            if not fut.done():
                fut.set_result(fb)
            return fb

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
        _save_disk_cache()
        if not fut.done():
            fut.set_result(res)
        return res
    except (httpx.RequestError, httpx.HTTPError, ValueError) as exc:
        logger.exception("YouTube API request failed — using verified news fallback")
        fb = _fallback_video(query)
        _VIDEO_CACHE[cache_key] = (time.time(), fb)
        _save_disk_cache()
        if not fut.done():
            fut.set_result(fb)
        return fb
    finally:
        if _VIDEO_INFLIGHT.get(cache_key) is fut:
            _VIDEO_INFLIGHT.pop(cache_key, None)


"""Live headlines — NewsData.io primary, Google News RSS + YouTube fallbacks."""
from __future__ import annotations

import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from typing import Any, Optional
from urllib.parse import quote_plus

import httpx

logger = logging.getLogger("news")

NEWSDATA_URL = "https://newsdata.io/api/1/latest"
GOOGLE_NEWS_RSS = "https://news.google.com/rss"

_CACHE_TTL_SEC = 20 * 60
_HEADLINE_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}

_NEWSDATA_LANG: dict[str, str] = {
    "en-US": "en",
    "en-GB": "en",
    "es": "es",
    "fr": "fr",
    "it": "it",
    "pt-BR": "pt",
    "zh": "zh",
    "hi": "hi",
}

_RSS_LOCALE: dict[str, tuple[str, str, str]] = {
    "en-US": ("en-US", "US", "US:en"),
    "en-GB": ("en-GB", "GB", "GB:en"),
    "es": ("es", "ES", "ES:es"),
    "fr": ("fr", "FR", "FR:fr"),
    "it": ("it", "IT", "IT:it"),
    "pt-BR": ("pt-BR", "BR", "BR:pt-419"),
    "zh": ("zh-CN", "CN", "CN:zh-Hans"),
    "hi": ("hi", "IN", "IN:hi"),
}


def _cache_key(query: Optional[str], language: str, limit: int) -> str:
    return f"{language}:{query or ''}:{limit}"


def _get_cached_articles(cache_key: str) -> list[dict[str, Any]]:
    entry = _HEADLINE_CACHE.get(cache_key)
    if not entry:
        return []
    cached_at, articles = entry
    if time.time() - cached_at > _CACHE_TTL_SEC:
        return []
    return articles


def _get_stale_articles(cache_key: str) -> list[dict[str, Any]]:
    entry = _HEADLINE_CACHE.get(cache_key)
    return entry[1] if entry else []


def _store_cache(cache_key: str, articles: list[dict[str, Any]]) -> None:
    if articles:
        _HEADLINE_CACHE[cache_key] = (time.time(), articles)


def _article(
    *,
    title: str,
    description: str = "",
    link: str = "",
    source: str = "unknown",
    pub_date: str = "",
    provider: str = "",
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "title": title[:200],
        "description": description[:400],
        "link": link,
        "source": source[:80],
        "pubDate": pub_date,
    }
    if provider:
        item["provider"] = provider
    return item


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


async def _fetch_newsdata(
    query: Optional[str],
    language: str,
    limit: int,
) -> list[dict[str, Any]]:
    api_key = os.getenv("NEWSDATA_API_KEY", "")
    if not api_key:
        return []

    params: dict[str, str] = {
        "apikey": api_key,
        "language": _NEWSDATA_LANG.get(language, "en"),
    }
    if query:
        params["q"] = query[:100]

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(NEWSDATA_URL, params=params)
        if resp.status_code != 200:
            logger.warning("newsdata.io returned %s: %s", resp.status_code, resp.text[:200])
            return []
        payload = resp.json()
    except (httpx.RequestError, httpx.HTTPError, ValueError):
        logger.exception("newsdata.io request failed")
        return []

    results = payload.get("results") or []
    articles: list[dict[str, Any]] = []
    for item in results[:limit]:
        if not isinstance(item, dict) or not item.get("title"):
            continue
        articles.append(
            _article(
                title=str(item.get("title", "")),
                description=str(item.get("description") or ""),
                link=str(item.get("link") or ""),
                source=str(item.get("source_id") or item.get("source_name") or "newsdata"),
                pub_date=str(item.get("pubDate") or ""),
                provider="newsdata",
            )
        )
    return articles


def _google_rss_url(query: Optional[str], language: str) -> str:
    hl, gl, ceid = _RSS_LOCALE.get(language, ("en-US", "US", "US:en"))
    if query:
        return (
            f"{GOOGLE_NEWS_RSS}/search?q={quote_plus(query[:100])}"
            f"&hl={hl}&gl={gl}&ceid={ceid}"
        )
    return f"{GOOGLE_NEWS_RSS}?hl={hl}&gl={gl}&ceid={ceid}"


def _parse_google_rss(xml_text: str, limit: int) -> list[dict[str, Any]]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        logger.warning("google news rss parse failed")
        return []

    articles: list[dict[str, Any]] = []
    for item in root.findall(".//item")[:limit]:
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        link = (item.findtext("link") or "").strip()
        pub_date = (item.findtext("pubDate") or "").strip()
        description = _strip_html(item.findtext("description") or "")
        source_el = item.find("source")
        source = (source_el.text or "Google News").strip() if source_el is not None else "Google News"
        articles.append(
            _article(
                title=title,
                description=description,
                link=link,
                source=source,
                pub_date=pub_date,
                provider="google_rss",
            )
        )
    return articles


async def _fetch_google_rss(
    query: Optional[str],
    language: str,
    limit: int,
) -> list[dict[str, Any]]:
    url = _google_rss_url(query, language)
    headers = {"User-Agent": "GenzCineNewsAgent/1.0"}
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
        if resp.status_code != 200:
            logger.warning("google news rss returned %s", resp.status_code)
            return []
        articles = _parse_google_rss(resp.text, limit)
        if articles:
            logger.info("google news rss: %d headlines (query=%r)", len(articles), query or "")
        return articles
    except (httpx.RequestError, httpx.HTTPError, ValueError):
        logger.exception("google news rss request failed")
        return []


async def _fetch_youtube_headlines(
    query: Optional[str],
    limit: int,
) -> list[dict[str, Any]]:
    api_key = os.getenv("YOUTUBE_API_KEY", "")
    if not api_key:
        return []

    search_q = f"{query} news" if query else "breaking news today"
    params: dict[str, str] = {
        "part": "snippet",
        "q": search_q[:100],
        "type": "video",
        "order": "date",
        "maxResults": str(max(limit, 1)),
        "safeSearch": "strict",
        "key": api_key,
    }

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                "https://www.googleapis.com/youtube/v3/search",
                params=params,
            )
        if resp.status_code != 200:
            logger.warning("youtube headline search returned %s: %s", resp.status_code, resp.text[:200])
            return []
        payload = resp.json()
    except (httpx.RequestError, httpx.HTTPError, ValueError):
        logger.exception("youtube headline search failed")
        return []

    articles: list[dict[str, Any]] = []
    for item in (payload.get("items") or [])[:limit]:
        video_id = (item.get("id") or {}).get("videoId")
        snippet = item.get("snippet") or {}
        title = (snippet.get("title") or "").strip()
        if not video_id or not title:
            continue
        channel = str(snippet.get("channelTitle") or "YouTube")
        articles.append(
            _article(
                title=title,
                description=str(snippet.get("description") or "")[:400],
                link=f"https://www.youtube.com/watch?v={video_id}",
                source=channel,
                pub_date=str(snippet.get("publishedAt") or ""),
                provider="youtube",
            )
        )
    if articles:
        logger.info("youtube headlines: %d items (query=%r)", len(articles), query or "")
    return articles


async def fetch_latest_news(
    query: Optional[str] = None,
    language: str = "en-US",
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Return recent headlines from NewsData, then RSS/YouTube if quota is exhausted."""
    cache_key = _cache_key(query, language, limit)
    cached = _get_cached_articles(cache_key)
    if cached:
        return cached[:limit]

    stale = _get_stale_articles(cache_key)

    articles = await _fetch_newsdata(query, language, limit)
    if articles:
        _store_cache(cache_key, articles)
        return articles[:limit]

    articles = await _fetch_google_rss(query, language, limit)
    if articles:
        _store_cache(cache_key, articles)
        return articles[:limit]

    articles = await _fetch_youtube_headlines(query, limit)
    if articles:
        _store_cache(cache_key, articles)
        return articles[:limit]

    if stale:
        logger.info("serving %d stale cached headlines", len(stale))
        return stale[:limit]

    return []

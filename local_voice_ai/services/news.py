"""Live headlines via NewsData.io — used by the agent's ``get_latest_news`` tool."""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

import httpx

logger = logging.getLogger("news")

NEWSDATA_URL = "https://newsdata.io/api/1/latest"

# NewsData.io only accepts a handful of two-letter language codes; map our
# session language codes onto the closest match (falls back to English).
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


async def fetch_latest_news(
    query: Optional[str] = None,
    language: str = "en-US",
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Return up to ``limit`` recent articles, optionally filtered by ``query``.

    Each article dict has ``title``, ``description``, ``link``, ``source``, ``pubDate``.
    Returns an empty list on any failure (missing key, network error, rate limit) —
    the caller is expected to handle that gracefully rather than raise.
    """
    api_key = os.getenv("NEWSDATA_API_KEY", "")
    if not api_key:
        logger.warning("NEWSDATA_API_KEY not set — cannot fetch news")
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
            {
                "title": str(item.get("title", ""))[:200],
                "description": str(item.get("description") or "")[:400],
                "link": str(item.get("link") or ""),
                "source": str(item.get("source_id") or item.get("source_name") or "unknown"),
                "pubDate": str(item.get("pubDate") or ""),
            }
        )
    return articles

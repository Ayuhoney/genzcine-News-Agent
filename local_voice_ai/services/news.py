"""Live headlines — community posts first, then India NewsData + Google RSS."""
from __future__ import annotations

import asyncio
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
GENZCINE_NEWS_API = os.getenv("GENZCINE_NEWS_API", "https://api.genzcine.com/v1/news")

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
    "en-US": ("en-IN", "IN", "IN:en"),
    "en-GB": ("en-GB", "GB", "GB:en"),
    "es": ("es", "ES", "ES:es"),
    "fr": ("fr", "FR", "FR:fr"),
    "it": ("it", "IT", "IT:it"),
    "pt-BR": ("pt-BR", "BR", "BR:pt-419"),
    "zh": ("zh-CN", "CN", "CN:zh-Hans"),
    "hi": ("hi", "IN", "IN:hi"),
}

_COMMUNITY_SOURCES = ("user", "citizen")
_MIN_COMMUNITY_TITLE_LEN = 12
_JUNK_TITLE = re.compile(
    r"\b(on[\s-]?road price|gold rate|silver rate|price in|rate today|aqi|"
    r"air quality|weather forecast|horoscope|numerology|lucky tips|birth numbers)\b",
    re.I,
)
_PLACE_ALIASES: dict[str, tuple[str, ...]] = {
    "firozpur": ("firozpur", "ferozepur", "ferozpore"),
    "mohali": ("mohali", "sas nagar", "s.a.s. nagar"),
    "chandigarh": ("chandigarh", "tricity"),
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
        "country": "in",
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
    hl, gl, ceid = _RSS_LOCALE.get(language, ("en-IN", "IN", "IN:en"))
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
    queries = []
    if query:
        if "news" not in query.lower():
            queries.append(f"{query} news")
        queries.append(query)
    else:
        queries.append(None)
    headers = {"User-Agent": "GenzCineNewsAgent/1.0"}
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            for rss_query in queries:
                url = _google_rss_url(rss_query, language)
                resp = await client.get(url, headers=headers)
                if resp.status_code != 200:
                    logger.warning("google news rss returned %s", resp.status_code)
                    continue
                articles = _parse_google_rss(resp.text, limit)
                if articles:
                    logger.info("google news rss: %d headlines (query=%r)", len(articles), query or "")
                    return articles
        return []
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


def _norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (title or "").lower())


def _community_title_ok(title: str) -> bool:
    text = (title or "").strip()
    if len(text) < _MIN_COMMUNITY_TITLE_LEN:
        return False
    words = [w for w in re.split(r"\s+", text) if re.search(r"[a-zA-Z\u0900-\u097F]", w)]
    if len(words) < 2:
        return False
    letters = re.findall(r"[a-zA-Z]", text)
    if letters:
        vowels = sum(1 for c in letters if c.lower() in "aeiou")
        if vowels / len(letters) < 0.25:
            return False
    return True


def _is_junk_title(title: str) -> bool:
    return bool(_JUNK_TITLE.search(title or ""))


def _query_aliases(query: str) -> tuple[str, ...]:
    key = query.strip().lower()
    return _PLACE_ALIASES.get(key, (key,))


def _mentions_query(article: dict[str, Any], query: str) -> bool:
    blob = f"{article.get('title') or ''} {article.get('description') or ''}".lower()
    return any(alias in blob for alias in _query_aliases(query) if alias)


def _geo_match_clause(value: str) -> dict[str, Any]:
    """Same idea as genzpublic-Backend: city/state/title/content/location."""
    rx = {"$regex": re.escape(value.strip()), "$options": "i"}
    return {
        "$or": [
            {"city": rx},
            {"state": rx},
            {"country": rx},
            {"location": rx},
            {"region": rx},
            {"title": rx},
            {"content": rx},
            {"tags": rx},
        ]
    }


def _merge_articles(*groups: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for group in groups:
        for article in group:
            key = _norm_title(str(article.get("title") or ""))
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(article)
            if len(merged) >= limit:
                return merged
    return merged


def _mix_buckets(*groups: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Round-robin published / local / global so one source cannot fill the bulletin."""
    seen: set[str] = set()
    mixed: list[dict[str, Any]] = []
    queues = [[article for article in group if article] for group in groups]
    while len(mixed) < limit and any(queues):
        progressed = False
        for queue in queues:
            while queue:
                article = queue.pop(0)
                key = _norm_title(str(article.get("title") or ""))
                if not key or key in seen:
                    continue
                seen.add(key)
                mixed.append(article)
                progressed = True
                break
            if len(mixed) >= limit:
                return mixed
        if not progressed:
            break
    return mixed


def _doc_pub_date(doc: dict[str, Any]) -> str:
    raw = doc.get("publishedAt") or doc.get("createdAt") or doc.get("updatedAt") or ""
    return str(raw)


async def _fetch_community_news(
    query: Optional[str],
    limit: int,
) -> list[dict[str, Any]]:
    """User/citizen posts from the GenzCine app Mongo `news` collection."""
    try:
        from .db import ensure_db

        db = await ensure_db()
    except Exception:
        logger.warning("community news skipped — Mongo unavailable", exc_info=True)
        return []

    filters: list[dict[str, Any]] = [
        {
            "$or": [
                {"status": {"$in": ["approved", "published"]}},
                {"status": {"$exists": False}},
            ]
        },
        {"source": {"$in": list(_COMMUNITY_SOURCES)}},
    ]
    if query and query.strip():
        filters.append(_geo_match_clause(query.strip()))

    articles: list[dict[str, Any]] = []
    try:
        cursor = (
            db.news.find({"$and": filters})
            .sort([("createdAt", -1), ("_id", -1)])
            .limit(max(limit * 2, 8))
        )
        async for doc in cursor:
            title = str(doc.get("title") or "").strip()
            if not _community_title_ok(title):
                continue
            author = str(doc.get("author") or "").strip() or "GenzCine viewer"
            description = str(doc.get("aiSummary") or doc.get("content") or "").strip()
            articles.append(
                _article(
                    title=title,
                    description=description,
                    link=str(doc.get("imageUrl") or ""),
                    source=f"GenzCine · {author}",
                    pub_date=_doc_pub_date(doc),
                    provider="community",
                )
            )
            if len(articles) >= limit:
                break
    except Exception:
        logger.exception("community news query failed")
        return []

    if articles:
        logger.info("community news: %d headlines (query=%r)", len(articles), query or "")
    return articles


def _from_genzcine_doc(item: dict[str, Any]) -> dict[str, Any] | None:
    title = str(item.get("title") or "").strip()
    if not title or _is_junk_title(title):
        return None
    source = str(item.get("source") or "").strip().lower()
    is_user = source in _COMMUNITY_SOURCES or item.get("isExternal") is False
    if is_user and not _community_title_ok(title):
        return None
    author = str(item.get("author") or "").strip()
    if is_user:
        provider = "community"
        label = f"GenzCine · {author or 'reporter'}"
    else:
        provider = "genzcine"
        label = author or str(item.get("source") or "GenzCine")
    return _article(
        title=title,
        description=str(item.get("aiSummary") or item.get("preview") or item.get("content") or ""),
        link=str(item.get("sourceUrl") or item.get("imageUrl") or ""),
        source=label,
        pub_date=str(item.get("createdAt") or item.get("updatedAt") or ""),
        provider=provider,
    )


async def _fetch_genzcine_api(params: dict[str, Any]) -> list[dict[str, Any]]:
    """Same public feed the website uses: GET https://api.genzcine.com/v1/news."""
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                GENZCINE_NEWS_API,
                params=params,
                headers={"User-Agent": "GenzCineNewsAgent/1.0", "Accept": "application/json"},
            )
        if resp.status_code != 200:
            logger.warning("genzcine news api returned %s", resp.status_code)
            return []
        payload = resp.json()
    except (httpx.RequestError, httpx.HTTPError, ValueError):
        logger.exception("genzcine news api request failed")
        return []

    data = payload.get("data") if isinstance(payload, dict) else None
    raw = (data or {}).get("articles") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return []
    articles: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        article = _from_genzcine_doc(item)
        if article:
            articles.append(article)
    return articles


async def _fetch_published_news(
    query: Optional[str],
    limit: int,
) -> list[dict[str, Any]]:
    """User-published reporter posts + GenzCine local/city feed."""
    city = (query or "").strip()
    requests: list = [
        _fetch_community_news(None, max(limit, 4)),
        _fetch_genzcine_api({"exclusive": "true", "limit": 20, "page": 1}),
    ]
    if city:
        requests.append(_fetch_genzcine_api({"city": city, "limit": 20, "page": 1}))
        requests.append(
            _fetch_genzcine_api({"category": "local", "city": city, "limit": 20, "page": 1})
        )
    else:
        requests.append(
            _fetch_genzcine_api({"category": "local", "country": "in", "limit": 20, "page": 1})
        )

    results = await asyncio.gather(*requests, return_exceptions=True)
    buckets: list[list[dict[str, Any]]] = []
    for result in results:
        if isinstance(result, Exception):
            logger.warning("published news source failed: %s", result)
            continue
        buckets.append(result)

    reporters = [a for group in buckets for a in group if a.get("provider") == "community"]
    app_local = [a for group in buckets for a in group if a.get("provider") != "community"]
    if city:
        matched_reporters = [a for a in reporters if _mentions_query(a, city)]
        other_reporters = [a for a in reporters if a not in matched_reporters][:2]
        matched_local = [a for a in app_local if _mentions_query(a, city)]
        merged = _merge_articles(matched_reporters, other_reporters, matched_local, limit=max(limit * 2, 8))
    else:
        merged = _merge_articles(reporters[:4], app_local, limit=max(limit * 2, 8))
    if merged:
        logger.info("published news: %d headlines (query=%r)", len(merged), query or "")
    return merged


async def fetch_latest_news(
    query: Optional[str] = None,
    language: str = "en-US",
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Mix published + local + global headlines in one bulletin."""
    cache_key = _cache_key(query, language, limit)
    cached = _get_cached_articles(cache_key)
    if cached:
        return cached[:limit]

    stale = _get_stale_articles(cache_key)
    city = (query or "").strip()

    published, rss, global_wire = await asyncio.gather(
        _fetch_published_news(query, limit),
        _fetch_google_rss(query, language, limit),
        _fetch_newsdata(None, language, limit),
    )
    rss = [a for a in rss if not _is_junk_title(str(a.get("title") or ""))]
    if city:
        rss = [a for a in rss if _mentions_query(a, city)]

    reporters = [a for a in published if a.get("provider") == "community"]
    app_local = [a for a in published if a.get("provider") == "genzcine"]
    global_wire = [a for a in global_wire if not _is_junk_title(str(a.get("title") or ""))]
    if city:
        local = _mix_buckets(app_local, rss, limit=max(limit, 6))
        if len(local) < 2:
            youtube_local = await _fetch_youtube_headlines(query, limit)
            local = _merge_articles(local, youtube_local, limit=max(limit, 6))
        world = _merge_articles(global_wire, limit=max(limit, 6))
    else:
        local = _merge_articles(app_local, limit=max(limit, 6))
        world = _merge_articles(global_wire, rss, limit=max(limit, 6))
    articles = _mix_buckets(reporters, local, world, limit=limit)

    if len(articles) < limit:
        youtube = await _fetch_youtube_headlines(query, limit)
        articles = _merge_articles(articles, youtube, limit=limit)

    if articles:
        _store_cache(cache_key, articles)
        return articles[:limit]

    if stale:
        logger.info("serving %d stale cached headlines", len(stale))
        return stale[:limit]

    return []

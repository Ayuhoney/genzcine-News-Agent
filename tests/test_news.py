"""Tests for headline fallbacks when NewsData.io is unavailable."""
from __future__ import annotations

import pytest

from local_voice_ai.services.news import (
    _HEADLINE_CACHE,
    _community_title_ok,
    _from_genzcine_doc,
    _google_rss_url,
    _is_junk_title,
    _mentions_query,
    _merge_articles,
    _mix_buckets,
    _parse_google_rss,
    fetch_latest_news,
)


SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Markets rally on inflation data - Reuters</title>
      <link>https://news.google.com/articles/example</link>
      <pubDate>Mon, 31 Aug 2026 10:00:00 GMT</pubDate>
      <description>&lt;p&gt;Stocks rose after cooler inflation.&lt;/p&gt;</description>
      <source url="https://reuters.com">Reuters</source>
    </item>
    <item>
      <title>India launches new satellite mission - BBC</title>
      <link>https://news.google.com/articles/example2</link>
      <pubDate>Mon, 31 Aug 2026 09:00:00 GMT</pubDate>
      <source url="https://bbc.com">BBC</source>
    </item>
  </channel>
</rss>
"""


def test_parse_google_rss_extracts_headlines():
    articles = _parse_google_rss(SAMPLE_RSS, limit=5)
    assert len(articles) == 2
    assert articles[0]["title"].startswith("Markets rally")
    assert articles[0]["source"] == "Reuters"
    assert articles[0]["provider"] == "google_rss"
    assert "Stocks rose" in articles[0]["description"]


@pytest.mark.asyncio
async def test_fetch_latest_news_falls_back_to_rss(monkeypatch):
    async def fake_community(*_args, **_kwargs):
        return []

    async def fake_newsdata(*_args, **_kwargs):
        return []

    async def fake_rss(_query, _language, limit):
        return _parse_google_rss(SAMPLE_RSS, limit)

    async def fake_youtube(*_args, **_kwargs):
        return []

    monkeypatch.setattr("local_voice_ai.services.news._fetch_published_news", fake_community)
    monkeypatch.setattr("local_voice_ai.services.news._fetch_newsdata", fake_newsdata)
    monkeypatch.setattr("local_voice_ai.services.news._fetch_google_rss", fake_rss)
    monkeypatch.setattr("local_voice_ai.services.news._fetch_youtube_headlines", fake_youtube)

    articles = await fetch_latest_news(language="en-US", limit=2)
    assert len(articles) == 2
    assert articles[0]["provider"] == "google_rss"


@pytest.mark.asyncio
async def test_fetch_latest_news_falls_back_to_youtube(monkeypatch):
    async def fake_community(*_args, **_kwargs):
        return []

    async def fake_newsdata(*_args, **_kwargs):
        return []

    async def fake_rss(*_args, **_kwargs):
        return []

    async def fake_youtube(_query, limit):
        return [
            {
                "title": "Breaking: Tech summit opens",
                "description": "Leaders gather.",
                "link": "https://www.youtube.com/watch?v=abc123",
                "source": "NDTV",
                "pubDate": "2026-08-31T10:00:00Z",
                "provider": "youtube",
            }
        ][:limit]

    monkeypatch.setattr("local_voice_ai.services.news._fetch_published_news", fake_community)
    monkeypatch.setattr("local_voice_ai.services.news._fetch_newsdata", fake_newsdata)
    monkeypatch.setattr("local_voice_ai.services.news._fetch_google_rss", fake_rss)
    monkeypatch.setattr("local_voice_ai.services.news._fetch_youtube_headlines", fake_youtube)

    articles = await fetch_latest_news(query="technology", limit=1)
    assert len(articles) == 1
    assert articles[0]["provider"] == "youtube"
    assert "youtube.com" in articles[0]["link"]


def test_google_rss_english_uses_india():
    url = _google_rss_url("Firozpur", "en-US")
    assert "gl=IN" in url
    assert "ceid=IN%3Aen" in url or "ceid=IN:en" in url
    assert "hl=en-IN" in url


def test_community_title_ok_filters_junk():
    assert _community_title_ok("NEET PAPER LEAK")
    assert _community_title_ok("Andheri flyover ke neeche bada pothole")
    assert not _community_title_ok("this")
    assert not _community_title_ok("genz")
    assert not _community_title_ok("gshkijfx bhfhjoi")


def test_junk_title_and_query_match():
    assert _is_junk_title("Silver Rate Today in Firozpur")
    assert _is_junk_title("Kia Sorento On Road Price Firozpur")
    assert _is_junk_title("Weekly Chinese Horoscope 7-3 Sept")
    assert not _is_junk_title("Firozpur police arrest two alleged extortionists")
    assert _mentions_query({"title": "Shootout in Ferozepur", "description": ""}, "Firozpur")
    assert not _mentions_query({"title": "Union Cabinet reshuffle", "description": ""}, "Firozpur")


def test_merge_articles_community_first():
    community = [
        {
            "title": "NEET PAPER LEAK",
            "provider": "community",
            "source": "GenzCine · Genzcine",
        }
    ]
    newsdata = [
        {"title": "US stocks fall after hours", "provider": "newsdata", "source": "wire"},
        {"title": "NEET paper leak", "provider": "newsdata", "source": "wire"},
    ]
    rss = [{"title": "Firozpur civic body starts night market", "provider": "google_rss"}]
    merged = _merge_articles(community, newsdata, rss, limit=3)
    assert merged[0]["provider"] == "community"
    assert merged[0]["title"] == "NEET PAPER LEAK"
    assert [a["provider"] for a in merged] == ["community", "newsdata", "google_rss"]


def test_mix_buckets_interleaves_published_local_global():
    published = [
        {"title": "User published story one", "provider": "community"},
        {"title": "User published story two", "provider": "community"},
    ]
    local = [
        {"title": "Mohali marathon this Sunday", "provider": "genzcine"},
        {"title": "Firozpur police arrest suspects", "provider": "google_rss"},
    ]
    world = [
        {"title": "Asian Games opening ceremony", "provider": "newsdata"},
        {"title": "UN climate talks resume", "provider": "newsdata"},
    ]
    mixed = _mix_buckets(published, local, world, limit=6)
    assert [a["provider"] for a in mixed] == [
        "community",
        "genzcine",
        "newsdata",
        "community",
        "google_rss",
        "newsdata",
    ]


@pytest.mark.asyncio
async def test_fetch_latest_news_puts_community_first(monkeypatch):
    async def fake_community(*_args, **_kwargs):
        return [
            {
                "title": "Andheri flyover ke neeche bada pothole",
                "description": "Two bikes slipped.",
                "link": "",
                "source": "GenzCine · citizen",
                "pubDate": "",
                "provider": "community",
            }
        ]

    async def fake_newsdata(*_args, **_kwargs):
        return [
            {
                "title": "Delhi, Mumbai to see more rain on Saturday",
                "description": "",
                "link": "",
                "source": "newsdata",
                "pubDate": "",
                "provider": "newsdata",
            }
        ]

    async def fake_rss(*_args, **_kwargs):
        return []

    async def fake_youtube(*_args, **_kwargs):
        return []

    monkeypatch.setattr("local_voice_ai.services.news._fetch_published_news", fake_community)
    monkeypatch.setattr("local_voice_ai.services.news._fetch_newsdata", fake_newsdata)
    monkeypatch.setattr("local_voice_ai.services.news._fetch_google_rss", fake_rss)
    monkeypatch.setattr("local_voice_ai.services.news._fetch_youtube_headlines", fake_youtube)

    _HEADLINE_CACHE.clear()
    articles = await fetch_latest_news(language="en-US", limit=2)
    assert articles[0]["provider"] == "community"
    assert articles[1]["provider"] == "newsdata"


def test_from_genzcine_doc_marks_reporter_and_local():
    reporter = _from_genzcine_doc(
        {
            "title": "Mohali night market opens on Sunday",
            "aiSummary": "Local vendors set up stalls.",
            "author": "sarojvermadbs",
            "source": "user",
            "isExternal": False,
            "sourceUrl": "https://genzcine.com/news/1",
        }
    )
    assert reporter is not None
    assert reporter["provider"] == "community"
    assert "sarojvermadbs" in reporter["source"]

    local = _from_genzcine_doc(
        {
            "title": "Punjab Youth Run 2026: AAP Holds 5.5 Km Marathon In Mohali",
            "preview": "Drug-free campaign.",
            "author": "Times of India",
            "source": "newsdata",
            "isExternal": True,
        }
    )
    assert local is not None
    assert local["provider"] == "genzcine"
    assert _from_genzcine_doc({"title": "genz", "source": "user", "isExternal": False}) is None

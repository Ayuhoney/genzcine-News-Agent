"""Tests for headline fallbacks when NewsData.io is unavailable."""
from __future__ import annotations

import pytest

from local_voice_ai.services.news import _parse_google_rss, fetch_latest_news


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
    async def fake_newsdata(*_args, **_kwargs):
        return []

    async def fake_rss(_query, _language, limit):
        return _parse_google_rss(SAMPLE_RSS, limit)

    async def fake_youtube(*_args, **_kwargs):
        return []

    monkeypatch.setattr("local_voice_ai.services.news._fetch_newsdata", fake_newsdata)
    monkeypatch.setattr("local_voice_ai.services.news._fetch_google_rss", fake_rss)
    monkeypatch.setattr("local_voice_ai.services.news._fetch_youtube_headlines", fake_youtube)

    articles = await fetch_latest_news(language="en-US", limit=2)
    assert len(articles) == 2
    assert articles[0]["provider"] == "google_rss"


@pytest.mark.asyncio
async def test_fetch_latest_news_falls_back_to_youtube(monkeypatch):
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

    monkeypatch.setattr("local_voice_ai.services.news._fetch_newsdata", fake_newsdata)
    monkeypatch.setattr("local_voice_ai.services.news._fetch_google_rss", fake_rss)
    monkeypatch.setattr("local_voice_ai.services.news._fetch_youtube_headlines", fake_youtube)

    articles = await fetch_latest_news(query="technology", limit=1)
    assert len(articles) == 1
    assert articles[0]["provider"] == "youtube"
    assert "youtube.com" in articles[0]["link"]

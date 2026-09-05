"""Offline India state/city keyword match — no NewsData / Groq / RSS calls."""
from __future__ import annotations

from local_voice_ai.agent import _correct_place_transcript
from local_voice_ai.services.india_places import (
    IN_STATES,
    IN_UTS,
    all_place_names,
    aliases_for,
)
from local_voice_ai.services.news import _google_rss_url, _mentions_query


ALIAS_PAIRS = (
    ("Firozpur", "Ferozepur police arrest two men"),
    ("Bengaluru", "Bangalore rains flood outer ring road"),
    ("Gurugram", "Gurgaon metro extension approved"),
    ("Mumbai", "Bombay high court hears plea"),
    ("Kolkata", "Calcutta port sees cargo rise"),
    ("Chennai", "Madras university announces results"),
    ("Odisha", "Orissa train services resume"),
    ("Puducherry", "Pondicherry beach festival begins"),
    ("Thiruvananthapuram", "Trivandrum airport expansion"),
    ("Prayagraj", "Allahabad Magh Mela crowd"),
    ("Kochi", "Cochin shipyard signs deal"),
    ("Mysuru", "Mysore Dasara dates announced"),
)


def test_all_states_uts_and_cities_self_match():
    names = all_place_names()
    assert len(IN_STATES) == 28
    assert len(IN_UTS) == 8
    assert len(names) >= 80
    failed = []
    for name in names:
        article = {"title": f"Live update from {name} today", "description": ""}
        if not _mentions_query(article, name):
            failed.append(name)
    assert failed == []


def test_common_indian_aliases_match():
    for query, title in ALIAS_PAIRS:
        assert _mentions_query({"title": title, "description": ""}, query), (query, title)


def test_spoken_place_names_stay_canonical():
    for name in ("Punjab", "Kerala", "Rajasthan", "Firozpur", "Mohali", "Delhi"):
        assert _correct_place_transcript(name) == name
    assert _correct_place_transcript("bangalore") == "Bengaluru"
    assert _correct_place_transcript("gurgaon") == "Gurugram"
    assert _correct_place_transcript("Frostburt") == "Firozpur"


def test_rss_stays_india_for_every_state():
    for name in IN_STATES:
        url = _google_rss_url(name, "en-US")
        assert "gl=IN" in url
        assert "ceid=IN:en" in url


def test_aliases_for_unknown_keeps_raw_keyword():
    assert aliases_for("Jaisalmer") == ("jaisalmer",)

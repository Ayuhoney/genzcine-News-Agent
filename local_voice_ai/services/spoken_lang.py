"""Detect Hindi / Punjabi / English from script, switch phrases, or Whisper."""

from __future__ import annotations

import re

_DEVANAGARI = re.compile(r"[\u0900-\u097F]")
_GURMUKHI = re.compile(r"[\u0A00-\u0A7F]")
_ARABIC = re.compile(r"[\u0600-\u06FF]")  # Urdu / Arabic keyboard

_HI_WHISPER = {"hi", "hin", "hindi", "hi-in", "ur", "urd", "urdu"}
_PA_WHISPER = {"pa", "pan", "punjabi", "pa-in", "pa-guru"}
_EN_WHISPER = {"en", "eng", "english", "en-us", "en-gb", "en-in"}

_PA_HINT = re.compile(
    r"sat\s*sri\s*akaa?l|"
    r"satsriakaa?l|"
    r"सत्\s*श्री\s*अकाल|"
    r"सत\s*श्री\s*अकाल|"
    r"सत्स्री\s*अकाल|"
    r"सत्स्रियकाल|"
    r"सत्स्रीकाल|"
    r"किद्द[ाां]|"
    r"खबरां|"
    r"\bvich\b|"
    r"\bkiddan\b|"
    r"\bki\s+haal\b|"
    r"\b(?:di|dian|diyan)\s+khabr",
    re.IGNORECASE,
)

# Explicit switch — user asked for a language, not just mentioned a place.
_EN_SWITCH = re.compile(
    r"(?:continue|speak|talk|switch|bolo|baat).{0,24}english|"
    r"english.{0,16}(?:continue|please|mein|me\b|bolo|baat)|"
    r"\bin english\b|"
    r"انگریزی",
    re.IGNORECASE,
)
_HI_SWITCH = re.compile(
    r"(?:speak|talk|switch|bolo|baat).{0,24}hindi|"
    r"hindi.{0,16}(?:mein|me\b|bolo|baat|please)|"
    r"\bin hindi\b|"
    r"हिंदी\s*में|हिन्दी\s*में|"
    r"ہندی",
    re.IGNORECASE,
)
_PA_SWITCH = re.compile(
    r"(?:speak|talk|switch|bolo|baat).{0,24}punjabi|"
    r"punjabi.{0,16}(?:mein|me\b|bolo|baat|please)|"
    r"\bin punjabi\b|"
    r"ਪੰਜਾਬੀ|"
    r"پنجابی",
    re.IGNORECASE,
)

_SARVAM_SCRIPT = {"hi": _DEVANAGARI, "pa": _GURMUKHI}


def _norm_whisper(language: str | None) -> str:
    return (language or "").strip().lower().replace("_", "-")


def has_sarvam_script(text: str, language: str) -> bool:
    """True if text has at least one character Sarvam accepts for this TTS lang."""
    pat = _SARVAM_SCRIPT.get(language)
    return bool(pat and pat.search(text or ""))


def detect_spoken_lang(text: str, whisper_lang: str | None = None) -> str | None:
    """Return 'hi', 'pa', 'en', or None if we should keep the current TTS.

    Explicit switch phrases and native scripts win. Urdu/Arabic script counts
    as Hindi unless the line is asking for Punjabi. Latin-only news without a
    Whisper label stays None so English sessions do not flip.
    """
    raw = text or ""
    if _EN_SWITCH.search(raw):
        return "en"
    if _GURMUKHI.search(raw) or _PA_SWITCH.search(raw) or _PA_HINT.search(raw):
        return "pa"
    if _HI_SWITCH.search(raw) or _DEVANAGARI.search(raw) or _ARABIC.search(raw):
        return "hi"

    w = _norm_whisper(whisper_lang)
    if not w:
        return None
    if w in _PA_WHISPER or w.startswith("pa-"):
        return "pa"
    if w in _HI_WHISPER or w.startswith("hi-") or w.startswith("ur"):
        return "hi"
    if w in _EN_WHISPER or w.startswith("en"):
        return "en"
    return None

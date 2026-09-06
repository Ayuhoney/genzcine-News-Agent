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
    r"(?:continue|\bspeak\b|\btalk\b|\bswitch\b|\bbolo\b|\bbaat\b).{0,24}\benglish\b|"
    r"\benglish\b.{0,16}(?:continue|please|mein|\bme\b|bolo|baat)|"
    r"\bin english\b|"
    r"انگریزی",
    re.IGNORECASE,
)
_HI_SWITCH = re.compile(
    r"(?:\bspeak\b|\btalk\b|\bswitch\b|\bbolo\b|\bbaat\b).{0,24}\bhindi\b|"
    r"\bhindi\b.{0,16}(?:mein|\bme\b|bolo|baat|please)|"
    r"\bin hindi\b|"
    r"हिंदी\s*में|हिन्दी\s*में|"
    r"ہندی",
    re.IGNORECASE,
)
_PA_SWITCH = re.compile(
    r"(?:\bspeak\b|\btalk\b|\bswitch\b|\bbolo\b|\bbaat\b).{0,24}\bpunjabi\b|"
    r"\bpunjabi\b.{0,16}(?:mein|\bme\b|bolo|baat|please)|"
    r"\bin punjabi\b|"
    r"ਪੰਜਾਬੀ|"
    r"پنجابی",
    re.IGNORECASE,
)

# Roman Hinglish — enough markers to switch TTS, not a single borrowed word.
_HINGLISH = re.compile(
    r"\b(?:mujhe|humko|khabar(?:ein|en|e)?|batao|bataiye|sunao|"
    r"kya\s+haal|kaise\s+ho|namaste|namaskar)\b",
    re.IGNORECASE,
)

# Whisper often dumps its own prompt, or the agent's ident, as "user" speech.
_STT_GARBAGE = re.compile(
    r"transcribe in|speaker is punjabi|label language|ddevanagari|"
    r"thank you for watching|satsang with mooji|"
    r"you're watching genzcine|speak any language, i.ll follow",
    re.IGNORECASE,
)


def is_stt_garbage(text: str) -> bool:
    """True when STT echoed the Whisper prompt or our own intro — not a real viewer line."""
    raw = (text or "").strip()
    if not raw:
        return True
    return bool(_STT_GARBAGE.search(raw))


_NEWS_ASK = re.compile(
    r"news|headline|khabar|khabr|\u0916\u092c\u0930|\u0a16\u0a2c\u0a30|batao|bataiye|tell\s+(?:me|us)|"
    r"suna[o]|dikha[o]|\u0926\u093f\u0916\u093e|\u0938\u0941\u0928\u093e|\u0a26\u0a71\u0a38",
    re.IGNORECASE,
)

# Instant spoken line while LLM instructions catch up — keeps the turn from freezing.
_LANG_BRIDGE = {
    "hi": "\u091c\u0940, \u0905\u092c \u0939\u093f\u0902\u0926\u0940 \u092e\u0947\u0902 \u092c\u093e\u0924 \u0915\u0930\u0924\u0940 \u0939\u0942\u0901\u0964",
    "pa": "\u0a1c\u0a40, \u0a39\u0a41\u0a23 \u0a2a\u0a70\u0a1c\u0a3e\u0a2c\u0a40 \u0a35\u0a3f\u0a71\u0a1a \u0a17\u0a71\u0a32 \u0a15\u0a30\u0a26\u0a40 \u0a39\u0a3e\u0a02\u0964",
    "en": "Alright — switching to English.",
}

_SARVAM_SCRIPT = {"hi": _DEVANAGARI, "pa": _GURMUKHI}


def language_bridge(code: str) -> str:
    """Short confirm line in the new TTS language."""
    return _LANG_BRIDGE.get(code, "")


def is_language_switch_only(text: str) -> bool:
    """True when the viewer only asked to change language, not for news."""
    raw = text or ""
    if _NEWS_ASK.search(raw):
        return False
    return bool(_EN_SWITCH.search(raw) or _HI_SWITCH.search(raw) or _PA_SWITCH.search(raw))


def _norm_whisper(language: str | None) -> str:
    return (language or "").strip().lower().replace("_", "-")


def has_sarvam_script(text: str, language: str) -> bool:
    """True if text has at least one character Sarvam accepts for this TTS lang."""
    pat = _SARVAM_SCRIPT.get(language)
    return bool(pat and pat.search(text or ""))


def tts_lang_for_text(text: str, spoken: str = "en") -> str:
    """Which TTS language to use. Native script is strict — never send it to Kokoro.

    Devanagari / Urdu → hi (Sarvam). Gurmukhi → pa (Sarvam). Latin stays on
    the current spoken engine so a Hindi session can still speak a Latin name.
    """
    raw = text or ""
    if _GURMUKHI.search(raw):
        return "pa"
    if _DEVANAGARI.search(raw) or _ARABIC.search(raw):
        return "hi"
    if spoken in {"hi", "pa", "en"}:
        return spoken
    return "en"


# A Whisper label alone (no script, no switch phrase) may only move the session
# when the viewer said enough for the label to mean something. "Mohali" or
# "Delhi news" tagged en-US must not flip a Hindi session to English.
_WHISPER_MIN_WORDS = 4


def detect_spoken_lang(
    text: str, whisper_lang: str | None = None, current: str | None = None
) -> str | None:
    """Return 'hi', 'pa', 'en', or None if we should keep the current TTS.

    Explicit switch phrases and native scripts win. Urdu/Arabic script counts
    as Hindi unless the line is asking for Punjabi. Latin-only news without a
    Whisper label stays None so English sessions do not flip. A bare Whisper
    label needs >= _WHISPER_MIN_WORDS words to move away from `current`.
    """
    raw = text or ""
    if is_stt_garbage(raw):
        return None
    if _EN_SWITCH.search(raw):
        return "en"
    if _GURMUKHI.search(raw) or _PA_SWITCH.search(raw) or _PA_HINT.search(raw):
        return "pa"
    if _HI_SWITCH.search(raw) or _DEVANAGARI.search(raw) or _ARABIC.search(raw):
        return "hi"
    if _HINGLISH.search(raw):
        return "hi"

    w = _norm_whisper(whisper_lang)
    if not w:
        return None
    if w in _PA_WHISPER or w.startswith("pa-"):
        guess = "pa"
    elif w in _HI_WHISPER or w.startswith("hi-") or w.startswith("ur"):
        guess = "hi"
    elif w in _EN_WHISPER or w.startswith("en"):
        guess = "en"
    else:
        return None
    if current and guess != current and len(raw.split()) < _WHISPER_MIN_WORDS:
        return None
    return guess

"""Detect Sarvam-supported languages from script, switch phrases, or Whisper.

Intersection of Whisper STT + Bulbul TTS + Sarvam-105B LLM = these 11:
  en, hi, pa, bn, ta, te, kn, ml, mr, gu, od
"""

from __future__ import annotations

import re

# Short session codes used everywhere (TTS, bridges, detect).
SARVAM_LANGS = ("en", "hi", "pa", "bn", "ta", "te", "kn", "ml", "mr", "gu", "od")

# Session / API language id → short TTS code.
SESSION_TO_SPOKEN = {
    "en-US": "en",
    "en-GB": "en",
    "en": "en",
    "hi": "hi",
    "pa": "pa",
    "bn": "bn",
    "ta": "ta",
    "te": "te",
    "kn": "kn",
    "ml": "ml",
    "mr": "mr",
    "gu": "gu",
    "od": "od",
    "or": "od",
}

# Short code → session language id (what Assistant._language stores).
SPOKEN_TO_SESSION = {
    "en": "en-US",
    "hi": "hi",
    "pa": "pa",
    "bn": "bn",
    "ta": "ta",
    "te": "te",
    "kn": "kn",
    "ml": "ml",
    "mr": "mr",
    "gu": "gu",
    "od": "od",
}

# Bulbul v3 language_code values.
SARVAM_TTS_CODE = {
    "en": "en-IN",
    "hi": "hi-IN",
    "pa": "pa-IN",
    "bn": "bn-IN",
    "ta": "ta-IN",
    "te": "te-IN",
    "kn": "kn-IN",
    "ml": "ml-IN",
    "mr": "mr-IN",
    "gu": "gu-IN",
    "od": "od-IN",
}

_DEVANAGARI = re.compile(r"[\u0900-\u097F]")  # Hindi + Marathi
_GURMUKHI = re.compile(r"[\u0A00-\u0A7F]")
_GUJARATI = re.compile(r"[\u0A80-\u0AFF]")
_BENGALI = re.compile(r"[\u0980-\u09FF]")
_ODIA = re.compile(r"[\u0B00-\u0B7F]")
_TAMIL = re.compile(r"[\u0B80-\u0BFF]")
_TELUGU = re.compile(r"[\u0C00-\u0C7F]")
_KANNADA = re.compile(r"[\u0C80-\u0CFF]")
_MALAYALAM = re.compile(r"[\u0D00-\u0D7F]")
_ARABIC = re.compile(r"[\u0600-\u06FF]")  # Urdu → treat as Hindi

# Script → default language (Devanagari defaults to Hindi; Whisper can flip to mr).
_SCRIPT_LANG = (
    (_GURMUKHI, "pa"),
    (_GUJARATI, "gu"),
    (_BENGALI, "bn"),
    (_ODIA, "od"),
    (_TAMIL, "ta"),
    (_TELUGU, "te"),
    (_KANNADA, "kn"),
    (_MALAYALAM, "ml"),
    (_DEVANAGARI, "hi"),
    (_ARABIC, "hi"),
)

_WHISPER_MAP: dict[str, str] = {
    "en": "en", "eng": "en", "english": "en", "en-us": "en", "en-gb": "en", "en-in": "en",
    "hi": "hi", "hin": "hi", "hindi": "hi", "hi-in": "hi",
    "ur": "hi", "urd": "hi", "urdu": "hi",
    "pa": "pa", "pan": "pa", "punjabi": "pa", "pa-in": "pa", "pa-guru": "pa",
    "bn": "bn", "ben": "bn", "bengali": "bn", "bn-in": "bn",
    "ta": "ta", "tam": "ta", "tamil": "ta", "ta-in": "ta",
    "te": "te", "tel": "te", "telugu": "te", "te-in": "te",
    "kn": "kn", "kan": "kn", "kannada": "kn", "kn-in": "kn",
    "ml": "ml", "mal": "ml", "malayalam": "ml", "ml-in": "ml",
    "mr": "mr", "mar": "mr", "marathi": "mr", "mr-in": "mr",
    "gu": "gu", "guj": "gu", "gujarati": "gu", "gu-in": "gu",
    "or": "od", "ori": "od", "odia": "od", "oriya": "od", "or-in": "od", "od": "od",
}

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

# name → code. Order matters for overlapping English names ("odia" before nothing).
_LANG_NAMES = (
    ("english", "en"),
    ("hindi", "hi"),
    ("punjabi", "pa"),
    ("bengali", "bn"),
    ("bangla", "bn"),
    ("tamil", "ta"),
    ("telugu", "te"),
    ("kannada", "kn"),
    ("malayalam", "ml"),
    ("marathi", "mr"),
    ("gujarati", "gu"),
    ("odia", "od"),
    ("oriya", "od"),
)

_SWITCH_VERB = r"(?:continue|\bspeak\b|\btalk\b|\bswitch\b|\bbolo\b|\bbaat\b|\bsunao\b)"


def _switch_re(name: str) -> re.Pattern[str]:
    return re.compile(
        rf"(?:{_SWITCH_VERB}).{{0,24}}\b{name}\b|"
        rf"\b{name}\b.{{0,16}}(?:continue|please|mein|\bme\b|bolo|baat)|"
        rf"\bin {name}\b",
        re.IGNORECASE,
    )


_SWITCHES: list[tuple[re.Pattern[str], str]] = [(_switch_re(n), c) for n, c in _LANG_NAMES]
# Native-script "in X" shortcuts.
_SWITCHES.extend(
    [
        (re.compile(r"हिंदी\s*में|हिन्दी\s*में|ہندی", re.I), "hi"),
        (re.compile(r"ਪੰਜਾਬੀ|پنجابی", re.I), "pa"),
        (re.compile(r"انگریزی", re.I), "en"),
        (re.compile(r"বাংলা(?:য়|তে)?", re.I), "bn"),
        (re.compile(r"தமிழில்|தமிழ்\s*ல", re.I), "ta"),
        (re.compile(r"తెలుగులో", re.I), "te"),
        (re.compile(r"ಕನ್ನಡದಲ್ಲಿ", re.I), "kn"),
        (re.compile(r"മലയാളത്തിൽ", re.I), "ml"),
        (re.compile(r"मराठी(?:त|मध्ये)", re.I), "mr"),
        (re.compile(r"ગુજરાતી(?:માં)?", re.I), "gu"),
        (re.compile(r"ଓଡ଼ିଆ(?:ରେ)?", re.I), "od"),
    ]
)

_HINGLISH = re.compile(
    r"\b(?:mujhe|humko|khabar(?:ein|en|e)?|batao|bataiye|sunao|"
    r"kya\s+haal|kaise\s+ho|namaste|namaskar)\b",
    re.IGNORECASE,
)

_STT_GARBAGE = re.compile(
    r"transcribe in|speaker is punjabi|label language|ddevanagari|"
    r"thank you for watching|satsang with mooji|"
    r"you're watching genzcine|speak any language, i.ll follow",
    re.IGNORECASE,
)

_NEWS_NOUN = re.compile(
    r"news|headline|khabar|khabr|\u0916\u092c\u0930|\u0a16\u0a2c\u0a30|"
    r"bulletin|headlines|\u0938\u092e\u093e\u091a\u093e\u0930",
    re.IGNORECASE,
)
_NEWS_VERB = re.compile(
    r"batao|bataiye|tell\s+(?:me|us)|suna[o]|dikha[o]|"
    r"\u0926\u093f\u0916\u093e|\u0938\u0941\u0928\u093e|\u0a26\u0a71\u0a38",
    re.IGNORECASE,
)


def is_news_ask(text: str) -> bool:
    """True when the viewer wants headlines — not generic 'batao/tell me' chit-chat."""
    raw = text or ""
    if _NEWS_NOUN.search(raw):
        return True
    # Verb alone is not enough unless a known place is in the line.
    if _NEWS_VERB.search(raw):
        try:
            from .india_places import extract_place

            if extract_place(raw):
                return True
        except Exception:
            pass
    return False


# Instant confirm while the LLM language addon catches up — same Priya voice.
_LANG_BRIDGE = {
    "en": "Alright — switching to English.",
    "hi": "\u091c\u0940, \u0905\u092c \u0939\u093f\u0902\u0926\u0940 \u092e\u0947\u0902 \u092c\u093e\u0924 \u0915\u0930\u0924\u0940 \u0939\u0942\u0901\u0964",
    "pa": "\u0a1c\u0a40, \u0a39\u0a41\u0a23 \u0a2a\u0a70\u0a1c\u0a3e\u0a2c\u0a40 \u0a35\u0a3f\u0a71\u0a1a \u0a17\u0a71\u0a32 \u0a15\u0a30\u0a26\u0a40 \u0a39\u0a3e\u0a02\u0964",
    "bn": "\u09a0\u09bf\u0995 \u0986\u099b\u09c7, \u098f\u09ac\u09be\u09b0 \u09ac\u09be\u0982\u09b2\u09be\u09df \u0995\u09a5\u09be \u09ac\u09b2\u099b\u09bf\u0964",
    "ta": "\u0b9a\u0bb0\u0bbf, \u0b87\u0baa\u0bcd\u0baa\u0bcb\u0ba4\u0bc1 \u0ba4\u0bae\u0bbf\u0bb4\u0bbf\u0bb2\u0bcd \u0baa\u0bc7\u0b9a\u0bc1\u0b95\u0bbf\u0bb1\u0bc7\u0ba9\u0bcd.",
    "te": "\u0c38\u0c30\u0c47, \u0c07\u0c2a\u0c4d\u0c2a\u0c41\u0c21\u0c41 \u0c24\u0c46\u0c32\u0c41\u0c17\u0c41\u0c32\u0c4b \u0c2e\u0c3e\u0c1f\u0c32\u0c3e\u0c21\u0c41\u0c24\u0c41\u0c28\u0c4d\u0c28\u0c3e\u0c28\u0c41.",
    "kn": "\u0cb8\u0cb0\u0cbf, \u0c88\u0c97 \u0c95\u0ca8\u0ccd\u0ca8\u0ca1\u0ca6\u0cb2\u0ccd\u0cb2\u0cbf \u0cae\u0cbe\u0ca4\u0ca8\u0cbe\u0ca1\u0cc1\u0ca4\u0ccd\u0ca4\u0cc7\u0ca8\u0cc6.",
    "ml": "\u0d36\u0d30\u0d3f, \u0d07\u0d28\u0d3f \u0d2e\u0d32\u0d2f\u0d3e\u0d33\u0d24\u0d4d\u0d24\u0d3f\u0d32\u0d4d \u0d38\u0d02\u0d38\u0d3e\u0d30\u0d3f\u0d15\u0d4d\u0d15\u0d41\u0d28\u0d4d\u0d28\u0d41.",
    "mr": "\u0920\u0940\u0915, \u0906\u0924\u093e\u092a\u093e\u0938\u0942\u0928 \u092e\u0930\u093e\u0920\u0940\u0924 \u092c\u094b\u0932\u0924\u0947.",
    "gu": "\u0aa0\u0ac0\u0a95, \u0ab9\u0ab5\u0ac7\u0aaa\u0a9b\u0ac0 \u0a97\u0ac1\u0a9c\u0ab0\u0abe\u0aa4\u0ac0\u0aae\u0abe\u0a82 \u0ab5\u0abe\u0aa4 \u0a95\u0ab0\u0ac1\u0a82.",
    "od": "\u0b20\u0b3f\u0b15, \u0b0f\u0b2c\u0b47 \u0b13\u0b21\u0b3c\u0b3f\u0b06\u0b30\u0b47 \u0b15\u0b25\u0b3e\u0b39\u0b47\u0b2c\u0b3f.",
}

# Covers LLM + news-tool silence so the avatar does not look frozen.
_THINKING_FILLER = {
    "en": "One second\u2026",
    "hi": "\u090f\u0915 \u0938\u0947\u0915\u0902\u0921\u2026",
    "pa": "\u0a07\u0a71\u0a15 \u0a38\u0a15\u0a3f\u0a70\u0a1f\u2026",
    "bn": "\u098f\u0995 \u09b8\u09c7\u0995\u09c7\u09a8\u09cd\u09a1\u2026",
    "ta": "\u0b92\u0bb0\u0bc1 \u0ba8\u0bca\u0b9f\u0bbf\u2026",
    "te": "\u0c12\u0c15\u0c4d\u0c15 \u0c15\u0c4d\u0c37\u0c23\u0c02\u2026",
    "kn": "\u0c92\u0c82\u0ca6\u0cc1 \u0c95\u0ccd\u0cb7\u0ca3\u2026",
    "ml": "\u0d12\u0d30\u0d41 \u0d28\u0d3f\u0d2e\u0d3f\u0d37\u0d02\u2026",
    "mr": "\u090f\u0915 \u0938\u0947\u0915\u0902\u0926\u2026",
    "gu": "\u0a8f\u0a95 \u0ab8\u0ac7\u0a95\u0aa8\u0acd\u0aa1\u2026",
    "od": "\u0b17\u0b4b\u0b1f\u0b3f\u0b0f \u0b38\u0b47\u0b15\u0b47\u0b23\u0b4d\u0b21\u2026",
}

# Native glue when Bulbul 422s on Latin-only text in an Indic session.
_SCRIPT_GLUE = {
    "hi": "\u091c\u0940\u0964 ",
    "pa": "\u0a1c\u0a40\u0964 ",
    "bn": "\u099c\u09bf\u0964 ",
    "ta": "\u0b9a\u0bb0\u0bbf. ",
    "te": "\u0c38\u0c30\u0c47. ",
    "kn": "\u0cb8\u0cb0\u0cbf. ",
    "ml": "\u0d36\u0d30\u0d3f. ",
    "mr": "\u091c\u0940. ",
    "gu": "\u0a9c\u0ac0. ",
    "od": "\u0b1c\u0b3f. ",
}

_SARVAM_SCRIPT = {
    "hi": _DEVANAGARI,
    "mr": _DEVANAGARI,
    "pa": _GURMUKHI,
    "gu": _GUJARATI,
    "bn": _BENGALI,
    "od": _ODIA,
    "ta": _TAMIL,
    "te": _TELUGU,
    "kn": _KANNADA,
    "ml": _MALAYALAM,
}


def is_stt_garbage(text: str) -> bool:
    """True when STT echoed the Whisper prompt or our own intro — not a real viewer line."""
    raw = (text or "").strip()
    if not raw:
        return True
    return bool(_STT_GARBAGE.search(raw))


def language_bridge(code: str) -> str:
    """Short confirm line in the new TTS language (same Priya voice)."""
    return _LANG_BRIDGE.get(code, "")


def thinking_filler(code: str) -> str:
    """Very short hold line while LLM / news fetch is in flight."""
    return _THINKING_FILLER.get(code, _THINKING_FILLER["en"])


def is_language_switch_only(text: str) -> bool:
    """True when the viewer only asked to change language, not for news."""
    raw = text or ""
    if is_news_ask(raw):
        return False
    return any(pat.search(raw) for pat, _ in _SWITCHES)


def _norm_whisper(language: str | None) -> str:
    return (language or "").strip().lower().replace("_", "-")


def has_sarvam_script(text: str, language: str) -> bool:
    """True if text has at least one native character for this TTS lang.

    English always returns True (Latin is native for en-IN).
    """
    if language == "en":
        return True
    pat = _SARVAM_SCRIPT.get(language)
    return bool(pat and pat.search(text or ""))


def script_glue(language: str) -> str:
    return _SCRIPT_GLUE.get(language, "")


def tts_lang_for_text(text: str, spoken: str = "en") -> str:
    """Which Sarvam language_code to use. Native script wins over session lang.

    Latin stays on the current spoken engine so a Hindi session can still speak
    a Latin name with the Hindi voice (Priya, hi-IN).
    """
    raw = text or ""
    for pat, code in _SCRIPT_LANG:
        if pat.search(raw):
            # Devanagari in an active Marathi session stays Marathi.
            if code == "hi" and spoken == "mr":
                return "mr"
            return code
    if spoken in SARVAM_LANGS:
        return spoken
    return "en"


_WHISPER_MIN_WORDS = 4


def detect_spoken_lang(
    text: str, whisper_lang: str | None = None, current: str | None = None
) -> str | None:
    """Return a short Sarvam code, or None to keep the current TTS language.

    Explicit switch phrases and native scripts win. A bare Whisper label needs
    >= _WHISPER_MIN_WORDS words to move away from `current`.
    """
    raw = text or ""
    if is_stt_garbage(raw):
        return None

    for pat, code in _SWITCHES:
        if pat.search(raw):
            return code

    if _PA_HINT.search(raw):
        return "pa"

    for pat, code in _SCRIPT_LANG:
        if pat.search(raw):
            if code == "hi" and current == "mr":
                return "mr"
            # Whisper can flip Devanagari → Marathi when labelled marathi.
            w = _norm_whisper(whisper_lang)
            if code == "hi" and (_WHISPER_MAP.get(w) == "mr" or w.startswith("mr")):
                return "mr"
            return code

    if _HINGLISH.search(raw):
        return "hi"

    w = _norm_whisper(whisper_lang)
    if not w:
        return None
    guess = _WHISPER_MAP.get(w)
    if guess is None:
        for prefix, code in (
            ("pa-", "pa"), ("hi-", "hi"), ("ur", "hi"), ("en", "en"),
            ("bn-", "bn"), ("ta-", "ta"), ("te-", "te"), ("kn-", "kn"),
            ("ml-", "ml"), ("mr-", "mr"), ("gu-", "gu"), ("or-", "od"), ("od-", "od"),
        ):
            if w.startswith(prefix):
                guess = code
                break
    if guess is None:
        return None
    if current and guess != current and len(raw.split()) < _WHISPER_MIN_WORDS:
        return None
    return guess

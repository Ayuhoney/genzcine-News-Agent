#!/usr/bin/env python3
"""Mock accuracy: language detect, TTS route, Sarvam HTTP/WS, Groq Whisper roundtrip."""
from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import time
import wave
from typing import Any

import httpx

from local_voice_ai.agent import _correct_place_transcript, _headline_spoken_line
from local_voice_ai.services.sarvam_tts import build_language_router, build_sarvam_tts
from local_voice_ai.services.spoken_lang import detect_spoken_lang

HI_NEWS = "\u092b\u093f\u0930\u094b\u091c\u092a\u0941\u0930 \u0915\u0940 \u0916\u092c\u0930 \u0926\u094b"
HI_ASK = (
    "\u092e\u0941\u091d\u0947 \u092e\u094b\u0939\u093e\u0932\u0940 \u0915\u0940 "
    "\u0924\u093e\u091c\u093c\u093e \u0916\u092c\u0930\u0947\u0902 \u0938\u0941\u0928\u093e\u0913"
)
HI_HELLO = "\u0928\u092e\u0938\u094d\u0924\u0947"
HI_LINE = (
    "\u0928\u092e\u0938\u094d\u0924\u0947, \u092e\u0948\u0902 \u091f\u0940\u0928\u093e \u0939\u0942\u0901\u0964 "
    "\u092b\u093f\u0930\u094b\u091c\u092a\u0941\u0930 \u0915\u0940 \u0906\u091c \u0915\u0940 \u0916\u092c\u0930\u0947\u0902\u0964"
)
PA_NEWS = (
    "\u0a38\u0a24 \u0a38\u0a4d\u0a30\u0a40 \u0a05\u0a15\u0a3e\u0a32 "
    "\u0a2e\u0a4b\u0a39\u0a3e\u0a32\u0a40 \u0a26\u0a40 \u0a16\u0a3c\u0a2c\u0a30"
)
PA_ASK = (
    "\u0a2b\u0a3c\u0a3f\u0a30\u0a4b\u0a1c\u0a3c\u0a2a\u0a41\u0a30 \u0a26\u0a40\u0a06\u0a02 "
    "\u0a16\u0a3c\u0a2c\u0a30\u0a3e\u0a02 \u0a26\u0a3f\u0a13"
)
PA_HELLO = "\u0a38\u0a24 \u0a38\u0a4d\u0a30\u0a40 \u0a05\u0a15\u0a3e\u0a32"
PA_LINE = (
    "\u0a38\u0a24 \u0a38\u0a4d\u0a30\u0a40 \u0a05\u0a15\u0a3e\u0a32, "
    "\u0a2e\u0a48\u0a02 \u0a1f\u0a40\u0a28\u0a3e \u0a39\u0a3e\u0a02\u0964 "
    "\u0a2e\u0a4b\u0a39\u0a3e\u0a32\u0a40 \u0a26\u0a40 \u0a16\u0a3c\u0a2c\u0a30\u0964"
)

PASS = 0
FAIL = 0
RESULTS: list[str] = []


def _ok(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        RESULTS.append(f"PASS  {name}" + (f"  {detail}" if detail else ""))
    else:
        FAIL += 1
        RESULTS.append(f"FAIL  {name}" + (f"  {detail}" if detail else ""))


def _pcm16_wav(pcm: bytes, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def _maybe_wav(raw: bytes, rate: int = 24000) -> tuple[bytes, str]:
    if raw[:4] == b"RIFF":
        return raw, "wav"
    if raw[:3] == b"ID3" or raw[:2] == b"\xff\xfb":
        return raw, "mp3"
    return _pcm16_wav(raw, rate), "pcm-wrapped"


def test_detect_spoken_lang() -> None:
    cases: list[tuple[str, str | None, str | None]] = [
        (HI_NEWS, None, "hi"),
        (HI_ASK, None, "hi"),
        (PA_NEWS, None, "pa"),
        (PA_ASK, None, "pa"),
        ("Give me Firozpur news", "en", "en"),
        ("Firozpur ki khabar do", "hi", "hi"),
        ("Mohali di khabar", "pa", "pa"),
        ("Firozpur news please", None, None),
        ("hello TINA", "en-US", "en"),
        (HI_HELLO, "en", "hi"),
        (PA_HELLO, "hi", "pa"),
        ("", "hi", "hi"),
        ("cricket score", "hin", "hi"),
        ("cricket score", "pa-guru", "pa"),
        ("  ", None, None),
        # Whisper often writes Punjabi as Hindi Devanagari.
        (
            "\u0938\u0924\u094d\u0938\u094d\u0930\u093f\u092f\u0915\u093e\u0932 "
            "\u092e\u0948\u0902 \u091f\u0940\u0928\u093e \u0939\u093e\u0902 "
            "\u092e\u094b\u0939\u093e\u0932\u0940 \u092d\u0940 \u0916\u092c\u0930",
            "Hindi",
            "pa",
        ),
        ("Sat Sri Akal, Mohali di khabar", "en", "pa"),
        (HI_ASK, "Hindi", "hi"),
        ("Continue in English.", None, "en"),
        ("Tell us about Delhi news.", None, None),
        ("No, can you still speak English with me?", None, "en"),
        ("Mujhe Aashika Nepal ka news batao.", None, "hi"),
        (
            "\u06a9\u06cc\u0627 \u062a\u0645 \u06c1\u0646\u062f\u06cc \u0645\u06cc\u06ba \u0628\u0627\u062a \u06a9\u0631 \u0633\u06a9\u062a\u06cc \u06c1\u0648\u061f",
            None,
            "hi",
        ),
        ("\u067e\u0646\u062c\u0627\u0628\u06cc \u0645\u06cc\u06ba \u0628\u0648\u0644\u0648", None, "pa"),
        ("\u0645\u062c\u06be\u06d2 \u062f\u0644\u06cc \u06a9\u06cc \u0646\u06cc\u0648\u0632", None, "hi"),
    ]
    hit = 0
    for text, whisper, expect in cases:
        got = detect_spoken_lang(text, whisper)
        ok = got == expect
        hit += int(ok)
        _ok(
            f"detect[{whisper or '-'}] {text[:28]!r}",
            ok,
            f"got={got} expect={expect}",
        )
    _ok("detect accuracy >= 90%", hit / len(cases) >= 0.90, f"{hit}/{len(cases)}")


def test_place_correction_vs_lang() -> None:
    original = HI_NEWS
    corrected = _correct_place_transcript(original)
    heard_after = detect_spoken_lang(corrected, None)
    heard_before = detect_spoken_lang(original, None)
    _ok("lang before place-correct stays hi", heard_before == "hi", f"got={heard_before}")
    if corrected != original and heard_after != "hi":
        _ok(
            "lang after place-correct lost script",
            False,
            f"corrected={corrected!r} heard={heard_after}",
        )
    else:
        _ok(
            "place-correct did not hide Hindi",
            heard_after == "hi" or corrected == original,
            f"corrected={corrected!r}",
        )

    hinglish = "Firozpur ki khabar do"
    fixed = _correct_place_transcript(hinglish)
    heard = detect_spoken_lang(fixed, "hi")
    _ok(
        "hinglish+whisper hi after place-correct",
        heard == "hi",
        f"text={fixed!r} heard={heard}",
    )


def test_headline_scripts() -> None:
    article = {"title": "Firozpur canal work starts", "description": "Officials inspect the site."}
    hi = _headline_spoken_line("TINA", article, is_first=True, language="hi")
    pa = _headline_spoken_line("TINA", article, is_first=True, language="pa")
    en = _headline_spoken_line("TINA", article, is_first=True, language="en-US")
    _ok("headline hi Devanagari", "\u092a\u0939\u0932\u0940" in hi or "\u0916\u092c\u0930" in hi, hi[:60])
    _ok("headline pa Gurmukhi", "\u0a16\u0a3c\u0a2c\u0a30" in pa, pa[:60])
    _ok("headline en English", "top story" in en.lower() and "Firozpur" in en, en[:60])
    _ok("detect headline hi", detect_spoken_lang(hi) == "hi")
    _ok("detect headline pa", detect_spoken_lang(pa) == "pa")


def test_router() -> None:
    from local_voice_ai.services.sarvam_tts import build_language_router

    router = build_language_router()
    _ok("router default sarvam:en", router.engine == "sarvam:en" and router.spoken == "en")
    _ok("set hi", router.set_spoken("hi") and router.engine == "sarvam:hi")
    _ok(
        "set pa",
        router.set_spoken("pa") and router.engine == "sarvam:pa" and router._sarvam._language == "pa",
    )
    _ok("set en back", router.set_spoken("en") is True and router.engine == "sarvam:en")
    router.set_spoken("hi")
    _ok("latin-only while hi stays hi", router._lang_for("To recap quickly: rain in Delhi.") == "hi")
    _ok(
        "devanagari while en uses hi",
        router._lang_for("\u0928\u092e\u0938\u094d\u0924\u0947 \u0926\u093f\u0932\u094d\u0932\u0940") == "hi",
    )
    router.set_spoken("en")
    _ok(
        "gurmukhi while en uses pa",
        router._lang_for("\u0a38\u0a24 \u0a38\u0a4d\u0a30\u0a40 \u0a05\u0a15\u0a3e\u0a32") == "pa",
    )
    _ok("latin english stays en", router._lang_for("You're watching GenzCine.") == "en")
    _ok("set ta", router.set_spoken("ta") and router.engine == "sarvam:ta")


async def test_sarvam_english() -> None:
    key = (os.getenv("SARVAM_API_KEY") or "").strip()
    if not key:
        _ok("sarvam english tts", False, "no key")
        return
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            t0 = time.perf_counter()
            r = await client.post(
                "https://api.sarvam.ai/text-to-speech/stream",
                headers={"api-subscription-key": key},
                json={
                    "text": "This is TINA with today's headlines.",
                    "language_code": "en-IN",
                    "target_language_code": "en-IN",
                    "model": "bulbul:v3",
                    "speaker": os.getenv("SARVAM_TTS_SPEAKER") or "priya",
                    "output_audio_codec": "linear16",
                    "speech_sample_rate": 24000,
                },
            )
            ms = round((time.perf_counter() - t0) * 1000)
            _ok(
                "sarvam english tts",
                r.status_code == 200 and len(r.content) > 2000,
                f"bytes={len(r.content)} ms={ms}",
            )
    except Exception as exc:
        _ok("sarvam english tts", False, str(exc))


async def _sarvam_http(key: str, text: str, lang: str) -> dict[str, Any]:
    t0 = time.perf_counter()
    async with httpx.AsyncClient(timeout=40) as client:
        r = await client.post(
            "https://api.sarvam.ai/text-to-speech/stream",
            headers={"api-subscription-key": key, "Content-Type": "application/json"},
            json={
                "text": text,
                "language_code": lang,
                "model": "bulbul:v3",
                "speaker": os.getenv("SARVAM_TTS_SPEAKER") or "priya",
                "output_audio_codec": "linear16",
                "speech_sample_rate": 24000,
            },
        )
    raw = r.content
    kind = "unknown"
    if raw[:4] == b"RIFF":
        kind = "wav"
    elif raw[:3] == b"ID3" or (len(raw) > 2 and raw[:2] == b"\xff\xfb"):
        kind = "mp3"
    elif r.status_code == 200:
        kind = "pcm-or-other"
    return {
        "status": r.status_code,
        "bytes": len(raw),
        "ms": round((time.perf_counter() - t0) * 1000),
        "ctype": r.headers.get("content-type", ""),
        "kind": kind,
        "audio": raw if r.status_code == 200 else b"",
        "err": r.text[:240] if r.status_code != 200 else "",
    }


async def test_sarvam_http(key: str) -> dict[str, bytes]:
    audio: dict[str, bytes] = {}
    hi = await _sarvam_http(key, HI_LINE, "hi-IN")
    _ok(
        "sarvam http hi",
        hi["status"] == 200 and hi["bytes"] > 2000,
        f"status={hi['status']} bytes={hi['bytes']} ms={hi['ms']} kind={hi['kind']} ctype={hi['ctype']} {hi['err']}",
    )
    if hi["audio"]:
        audio["hi"] = hi["audio"]
    pa = await _sarvam_http(key, PA_LINE, "pa-IN")
    _ok(
        "sarvam http pa",
        pa["status"] == 200 and pa["bytes"] > 2000,
        f"status={pa['status']} bytes={pa['bytes']} ms={pa['ms']} kind={pa['kind']} ctype={pa['ctype']} {pa['err']}",
    )
    if pa["audio"]:
        audio["pa"] = pa["audio"]
    return audio


async def test_sarvam_ws(key: str) -> None:
    import websockets

    ttfb = None
    chunks = 0
    audio_bytes = 0
    err = ""
    t0 = time.perf_counter()
    try:
        async with websockets.connect(
            "wss://api.sarvam.ai/text-to-speech/ws?model=bulbul:v3&send_completion_event=true",
            additional_headers={"api-subscription-key": key},
            open_timeout=8,
            close_timeout=5,
            max_size=8 * 1024 * 1024,
        ) as ws:
            await ws.send(
                json.dumps(
                    {
                        "type": "config",
                        "data": {
                            "speaker": os.getenv("SARVAM_TTS_SPEAKER") or "priya",
                            "language_code": "hi-IN",
                            "output_audio_codec": "linear16",
                            "speech_sample_rate": 24000,
                            "min_buffer_size": 30,
                            "max_chunk_length": 150,
                            "pace": 1.0,
                        },
                    }
                )
            )
            await ws.send(json.dumps({"type": "text", "data": {"text": HI_HELLO}}))
            await ws.send(
                json.dumps(
                    {
                        "type": "text",
                        "data": {
                            "text": "\u092e\u0948\u0902 \u091f\u0940\u0928\u093e \u0939\u0942\u0901\u0964"
                        },
                    }
                )
            )
            await ws.send(json.dumps({"type": "flush"}))
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=20)
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                kind = msg.get("type")
                payload = msg.get("data") or {}
                if kind == "audio":
                    b64 = payload.get("audio") or ""
                    if b64:
                        if ttfb is None:
                            ttfb = round((time.perf_counter() - t0) * 1000)
                        chunks += 1
                        audio_bytes += len(base64.b64decode(b64))
                elif kind == "event" and payload.get("event_type") == "final":
                    break
                elif kind == "error":
                    err = str(payload)[:200]
                    break
    except Exception as exc:
        err = str(exc)[:240]
    _ok(
        "sarvam ws stream",
        chunks > 0 and audio_bytes > 500 and not err,
        f"chunks={chunks} bytes={audio_bytes} ttfb_ms={ttfb} err={err}",
    )


async def test_whisper_roundtrip(audio: dict[str, bytes]) -> None:
    stt_url = (os.getenv("STT_BASE_URL") or "https://api.groq.com/openai/v1").rstrip("/")
    stt_key = os.getenv("STT_API_KEY") or ""
    model = os.getenv("STT_MODEL") or "whisper-large-v3"
    if not stt_key:
        _ok("whisper key", False, "STT_API_KEY missing")
        return
    expect = {"hi": "hi", "pa": "pa"}
    async with httpx.AsyncClient(timeout=45) as client:
        for code, raw in audio.items():
            wav, kind = _maybe_wav(raw)
            files = {"file": ("clip.wav", wav, "audio/wav")}
            data = {"model": model, "response_format": "verbose_json"}
            t0 = time.perf_counter()
            try:
                r = await client.post(
                    f"{stt_url}/audio/transcriptions",
                    headers={"Authorization": f"Bearer {stt_key}"},
                    files=files,
                    data=data,
                )
                ms = round((time.perf_counter() - t0) * 1000)
                if r.status_code != 200:
                    _ok(f"whisper {code}", False, f"status={r.status_code} {r.text[:180]}")
                    continue
                payload = r.json()
                text = (payload.get("text") or "").strip()
                wlang = payload.get("language")
                heard = detect_spoken_lang(text, wlang if isinstance(wlang, str) else None)
                ok = heard == expect[code]
                _ok(
                    f"whisper->detect {code}",
                    ok,
                    f"whisper={wlang} heard={heard} kind={kind} ms={ms} text={text[:80]!r}",
                )
            except Exception as exc:
                _ok(f"whisper {code}", False, str(exc)[:200])


async def main() -> int:
    test_detect_spoken_lang()
    test_place_correction_vs_lang()
    test_headline_scripts()
    test_router()
    await test_sarvam_english()
    key = (os.getenv("SARVAM_API_KEY") or "").strip()
    _ok("sarvam key present", bool(key and key.startswith("sk_")))
    audio: dict[str, bytes] = {}
    if key:
        audio = await test_sarvam_http(key)
        await test_sarvam_ws(key)
        if audio:
            await test_whisper_roundtrip(audio)
    print("\n".join(RESULTS))
    print(f"\nSCORE {PASS}/{PASS + FAIL}  fail={FAIL}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

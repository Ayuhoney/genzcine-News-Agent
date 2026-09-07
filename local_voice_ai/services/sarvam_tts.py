"""Sarvam Bulbul v3 — sole TTS for all session languages (en/hi/pa/bn/…).

Sentence-streamed: every finished sentence is synthesized the moment the LLM
emits it, and the next sentence starts after first audio of the current one.
Fixed lines (intro, bridges) come from a PCM disk cache — zero latency/cost
after the first play. One speaker (Priya) across every language = smooth
voice-matched transitions.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import time
import uuid
from pathlib import Path

import httpx
from livekit.agents import APIConnectionError, APIStatusError, tts
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, APIConnectOptions

from .spoken_lang import (
    SARVAM_LANGS,
    SARVAM_TTS_CODE,
    has_sarvam_script,
    script_glue,
    tts_lang_for_text,
)

logger = logging.getLogger("agent")

_SARVAM_HTTP = "https://api.sarvam.ai/text-to-speech/stream"
_SARVAM_MODEL = "bulbul:v3"
_SAMPLE_RATE = 24000

_SENT_END = re.compile(r"(?<=[.!?\u0964\u061f])[\"'\u201d\u2019)]?\s+")
_ABBREV = re.compile(r"\b(?:Dr|Mr|Mrs|Ms|St|No|Rs|vs|Lt|Gen|Col)\.$", re.IGNORECASE)
_MIN_SENTENCE_CHARS = 12
_PREFETCH = 1


def split_complete_sentences(buffer: str) -> tuple[list[str], str]:
    """Return (complete sentences, unfinished tail) for an incremental buffer."""
    out: list[str] = []
    start = 0
    for m in _SENT_END.finditer(buffer):
        head = buffer[start : m.start()].strip()
        if len(head) < _MIN_SENTENCE_CHARS or _ABBREV.search(head):
            continue
        out.append(head)
        start = m.end()
    return out, buffer[start:]


class _PcmCache:
    """Tiny content-addressed PCM cache on disk. Best-effort; never raises."""

    def __init__(self, root: str, *, max_chars: int = 400, max_files: int = 4000) -> None:
        self._root = Path(root)
        self._max_chars = max_chars
        self._max_files = max_files
        self._puts = 0
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            self._ok = os.access(self._root, os.W_OK)
        except Exception:
            self._ok = False
        if not self._ok:
            logger.warning("Sarvam PCM cache disabled — %s not writable", root)

    def _path(self, key: str) -> Path:
        return self._root / (hashlib.sha1(key.encode("utf-8")).hexdigest() + ".pcm")

    def cacheable(self, text: str) -> bool:
        return self._ok and 0 < len(text) <= self._max_chars

    def get(self, key: str) -> bytes | None:
        if not self._ok:
            return None
        try:
            p = self._path(key)
            if p.is_file():
                data = p.read_bytes()
                if data:
                    os.utime(p, None)
                    return data
        except Exception:
            pass
        return None

    def put(self, key: str, data: bytes) -> None:
        if not self._ok or not data:
            return
        try:
            tmp = self._path(key).with_suffix(".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, self._path(key))
            self._puts += 1
            if self._puts % 200 == 0:
                self._prune()
        except Exception:
            pass

    def _prune(self) -> None:
        files = sorted(self._root.glob("*.pcm"), key=lambda p: p.stat().st_mtime)
        excess = len(files) - self._max_files
        if excess > 0:
            for p in files[: excess + self._max_files // 4]:
                try:
                    p.unlink()
                except Exception:
                    pass


class SarvamTTS(tts.TTS):
    """Bulbul v3 over HTTP streaming. Non-streaming TTS — the router chunks sentences."""

    def __init__(
        self,
        *,
        api_key: str,
        speaker: str = "priya",
        language: str = "en",
        cache_dir: str | None = None,
    ) -> None:
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=_SAMPLE_RATE,
            num_channels=1,
        )
        self._api_key = api_key
        self._speaker = speaker
        self._language = language if language in SARVAM_TTS_CODE else "en"
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=45.0, write=10.0, pool=5.0),
            follow_redirects=True,
            limits=httpx.Limits(max_connections=8, max_keepalive_connections=4, keepalive_expiry=120),
        )
        self._cache = _PcmCache(cache_dir or os.getenv("SARVAM_TTS_CACHE_DIR", "/models/sarvam_tts_cache"))

    def set_language(self, language: str) -> None:
        if language in SARVAM_TTS_CODE:
            self._language = language

    def cache_key(self, text: str, language: str) -> str:
        return f"{_SARVAM_MODEL}|{self._speaker}|{SARVAM_TTS_CODE.get(language, 'en-IN')}|{text}"

    def synthesize(
        self,
        text: str,
        *,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> tts.ChunkedStream:
        return _SarvamChunkedStream(tts=self, input_text=text, conn_options=conn_options)

    async def aclose(self) -> None:
        await self._client.aclose()


class _SarvamChunkedStream(tts.ChunkedStream):
    """One sentence → Bulbul HTTP stream (or cache hit) → PCM frames."""

    def __init__(self, *, tts: SarvamTTS, input_text: str, conn_options: APIConnectOptions) -> None:
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)
        self._tts: SarvamTTS = tts

    async def _request(self, text: str, lang: str) -> httpx.Response:
        body = {
            "text": text[:3500],
            "language_code": lang,
            "target_language_code": lang,
            "model": _SARVAM_MODEL,
            "speaker": self._tts._speaker,
            "output_audio_codec": "linear16",
            "speech_sample_rate": _SAMPLE_RATE,
        }
        headers = {"api-subscription-key": self._tts._api_key, "Content-Type": "application/json"}
        req = self._tts._client.build_request("POST", _SARVAM_HTTP, headers=headers, json=body)
        return await self._tts._client.send(req, stream=True)

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        text = (self.input_text or "").strip()
        language = self._tts._language
        lang = SARVAM_TTS_CODE.get(language, "en-IN")
        output_emitter.initialize(
            request_id=str(uuid.uuid4()),
            sample_rate=_SAMPLE_RATE,
            num_channels=1,
            mime_type="audio/pcm",
        )
        if not text:
            output_emitter.flush()
            return

        cache = self._tts._cache
        key = self._tts.cache_key(text, language)
        cached = cache.get(key) if cache.cacheable(text) else None
        if cached is not None:
            logger.info("Sarvam cache hit lang=%s chars=%d", language, len(text))
            output_emitter.push(cached)
            output_emitter.flush()
            return

        t0 = time.perf_counter()
        resp: httpx.Response | None = None
        try:
            resp = await self._request(text, lang)
            if resp.status_code == 422 and not has_sarvam_script(text, language):
                # Latin wire copy on Indic session: re-speak as en-IN instead of glue hack.
                if language != "en":
                    await resp.aclose()
                    language = "en"
                    lang = SARVAM_TTS_CODE["en"]
                    key = self._tts.cache_key(text, language)
                    cached = cache.get(key) if cache.cacheable(text) else None
                    if cached is not None:
                        output_emitter.push(cached)
                        output_emitter.flush()
                        return
                    resp = await self._request(text, lang)
                else:
                    glue = script_glue(language)
                    if glue:
                        await resp.aclose()
                        resp = await self._request(glue + text, lang)
            # One retry on transient overload / upstream blip.
            if resp.status_code in (429, 500, 502, 503, 504):
                await resp.aclose()
                await asyncio.sleep(0.35)
                resp = await self._request(text, lang)
            if resp.status_code >= 400:
                err = (await resp.aread())[:400]
                raise APIStatusError(
                    f"Sarvam TTS {resp.status_code}: {err!r}",
                    status_code=resp.status_code,
                )
            buf = bytearray()
            first = None
            async for chunk in resp.aiter_bytes():
                if not chunk:
                    continue
                if first is None:
                    first = time.perf_counter() - t0
                output_emitter.push(chunk)
                buf += chunk
            output_emitter.flush()
            logger.info(
                "Sarvam lang=%s chars=%d ttfb=%dms audio=%.1fs",
                language, len(text), int((first or 0) * 1000), len(buf) / (_SAMPLE_RATE * 2),
            )
            if cache.cacheable(text):
                cache.put(key, bytes(buf))
        except APIStatusError:
            raise
        except Exception as exc:
            raise APIConnectionError(f"Sarvam TTS HTTP stream failed: {exc}") from exc
        finally:
            if resp is not None:
                await resp.aclose()


class LanguageRoutedTTS(tts.TTS):
    """Sarvam-only streaming TTS. Per-sentence language from script / session."""

    def __init__(self, *, sarvam: SarvamTTS) -> None:
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=True),
            sample_rate=sarvam.sample_rate,
            num_channels=sarvam.num_channels,
        )
        self._sarvam = sarvam
        self.spoken = "en"

    @property
    def engine(self) -> str:
        return f"sarvam:{self.spoken}"

    # Back-compat for older agent checks that looked at _indic.
    @property
    def _indic(self) -> SarvamTTS:
        return self._sarvam

    def set_spoken(self, language: str) -> bool:
        code = language if language in SARVAM_LANGS else "en"
        changed = code != self.spoken
        self.spoken = code
        self._sarvam.set_language(code)
        return changed

    def _lang_for(self, text: str | None = None) -> str:
        lang = tts_lang_for_text(text or "", self.spoken)
        self._sarvam.set_language(lang)
        return lang

    def synthesize(
        self,
        text: str,
        *,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> tts.ChunkedStream:
        self._lang_for(text)
        return self._sarvam.synthesize(text, conn_options=conn_options)

    def stream(
        self, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> tts.SynthesizeStream:
        return _SarvamSynthesizeStream(router=self, conn_options=conn_options)

    async def aclose(self) -> None:
        await self._sarvam.aclose()


class _SarvamSynthesizeStream(tts.SynthesizeStream):
    """LLM tokens → sentences → Sarvam, with one sentence prefetched."""

    def __init__(self, *, router: LanguageRoutedTTS, conn_options: APIConnectOptions) -> None:
        super().__init__(tts=router, conn_options=conn_options)
        self._router = router

    def _start(self, sentence: str) -> tts.ChunkedStream:
        lang = self._router._lang_for(sentence)
        logger.info("TTS sentence → sarvam:%s chars=%d", lang, len(sentence))
        return self._router._sarvam.synthesize(sentence)

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        output_emitter.initialize(
            request_id=str(uuid.uuid4()),
            sample_rate=self._router.sample_rate,
            num_channels=self._router.num_channels,
            mime_type="audio/pcm",
            stream=True,
        )
        output_emitter.start_segment(segment_id=str(uuid.uuid4()))

        slots = asyncio.Semaphore(1 + _PREFETCH)
        queue: asyncio.Queue[tts.ChunkedStream | None] = asyncio.Queue()
        first_audio = asyncio.Event()
        first_audio.set()

        async def _enqueue(sentence: str) -> None:
            await slots.acquire()
            await first_audio.wait()
            await queue.put(self._start(sentence))

        async def _forward_input() -> None:
            buffer = ""
            async for data in self._input_ch:
                if isinstance(data, self._FlushSentinel):
                    tail = buffer.strip()
                    buffer = ""
                    if tail:
                        await _enqueue(tail)
                    continue
                buffer += data if isinstance(data, str) else str(data)
                done, buffer = split_complete_sentences(buffer)
                for sentence in done:
                    await _enqueue(sentence)
            tail = buffer.strip()
            if tail:
                await _enqueue(tail)
            await queue.put(None)

        async def _drain() -> None:
            while True:
                stream = await queue.get()
                if stream is None:
                    return
                self._mark_started()
                first_audio.clear()
                try:
                    async with stream:
                        async for audio in stream:
                            frame = getattr(audio, "frame", None)
                            data = getattr(frame, "data", None) if frame is not None else None
                            if data:
                                first_audio.set()
                                output_emitter.push(bytes(data))
                finally:
                    first_audio.set()
                    slots.release()
                output_emitter.flush()

        tasks = [asyncio.create_task(_forward_input()), asyncio.create_task(_drain())]
        try:
            await asyncio.gather(*tasks)
        except APIStatusError:
            raise
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise APIConnectionError(f"Sarvam TTS stream failed: {exc}") from exc
        finally:
            for t in tasks:
                if not t.done():
                    t.cancel()
            while not queue.empty():
                item = queue.get_nowait()
                if item is not None:
                    try:
                        await item.aclose()
                    except Exception:
                        pass


def build_sarvam_tts() -> SarvamTTS | None:
    key = (os.getenv("SARVAM_API_KEY") or "").strip()
    if not key:
        return None
    speaker = (os.getenv("SARVAM_TTS_SPEAKER") or "priya").strip() or "priya"
    return SarvamTTS(api_key=key, speaker=speaker, language="en")


def build_language_router() -> LanguageRoutedTTS:
    """Sarvam-only router. Raises if the API key is missing — no Kokoro fallback."""
    sarvam = build_sarvam_tts()
    if sarvam is None:
        raise RuntimeError(
            "SARVAM_API_KEY is required — English and Indic TTS both run on Bulbul v3"
        )
    return LanguageRoutedTTS(sarvam=sarvam)

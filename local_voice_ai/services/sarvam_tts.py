"""Sarvam Bulbul v3 — HTTP streaming TTS, Kokoro stays for English."""

from __future__ import annotations

import logging
import os
import uuid

import httpx
from livekit.agents import APIConnectionError, APIStatusError, tts
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, APIConnectOptions

from .spoken_lang import has_sarvam_script

logger = logging.getLogger("agent")

_SARVAM_HTTP = "https://api.sarvam.ai/text-to-speech/stream"
_SAMPLE_RATE = 24000
_LANG = {"hi": "hi-IN", "pa": "pa-IN"}


class SarvamTTS(tts.TTS):
    """LiveKit TTS with native WebSocket streaming (HTTP stream as say() fallback)."""

    def __init__(
        self,
        *,
        api_key: str,
        speaker: str = "priya",
        language: str = "hi",
    ) -> None:
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=True),
            sample_rate=_SAMPLE_RATE,
            num_channels=1,
        )
        self._api_key = api_key
        self._speaker = speaker
        self._language = language if language in _LANG else "hi"
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=45.0, write=10.0, pool=5.0),
            follow_redirects=True,
        )

    def set_language(self, language: str) -> None:
        if language in _LANG:
            self._language = language

    def synthesize(
        self,
        text: str,
        *,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> tts.ChunkedStream:
        return _SarvamChunkedStream(tts=self, input_text=text, conn_options=conn_options)

    def stream(
        self, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> tts.SynthesizeStream:
        return _SarvamSynthesizeStream(tts=self, conn_options=conn_options)

    async def aclose(self) -> None:
        await self._client.aclose()


class _SarvamChunkedStream(tts.ChunkedStream):
    """HTTP /text-to-speech/stream — used by session.say() for a full line."""

    def __init__(self, *, tts: SarvamTTS, input_text: str, conn_options: APIConnectOptions) -> None:
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)
        self._tts: SarvamTTS = tts

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        if not has_sarvam_script(self.input_text, self._tts._language):
            output_emitter.initialize(
                request_id=str(uuid.uuid4()),
                sample_rate=_SAMPLE_RATE,
                num_channels=1,
                mime_type="audio/pcm",
            )
            output_emitter.flush()
            return
        lang = _LANG.get(self._tts._language, "hi-IN")
        body = {
            "text": self.input_text[:3500],
            "language_code": lang,
            "target_language_code": lang,
            "model": "bulbul:v3",
            "speaker": self._tts._speaker,
            "output_audio_codec": "linear16",
            "speech_sample_rate": _SAMPLE_RATE,
        }
        headers = {
            "api-subscription-key": self._tts._api_key,
            "Content-Type": "application/json",
        }
        try:
            async with self._tts._client.stream(
                "POST", _SARVAM_HTTP, headers=headers, json=body
            ) as resp:
                if resp.status_code >= 400:
                    err = (await resp.aread())[:400]
                    raise APIStatusError(
                        f"Sarvam TTS {resp.status_code}: {err!r}",
                        status_code=resp.status_code,
                    )
                output_emitter.initialize(
                    request_id=str(uuid.uuid4()),
                    sample_rate=_SAMPLE_RATE,
                    num_channels=1,
                    mime_type="audio/pcm",
                )
                async for chunk in resp.aiter_bytes():
                    if chunk:
                        output_emitter.push(chunk)
                output_emitter.flush()
        except APIStatusError:
            raise
        except Exception as exc:
            raise APIConnectionError(f"Sarvam TTS HTTP stream failed: {exc}") from exc


def _is_flush(stream: tts.SynthesizeStream, data: object) -> bool:
    return isinstance(data, stream._FlushSentinel) or "Flush" in type(data).__name__


class _SarvamSynthesizeStream(tts.SynthesizeStream):
    """LLM tokens → sentence buffer → Sarvam HTTP audio stream (WS 422 was killing voice)."""

    def __init__(self, *, tts: SarvamTTS, conn_options: APIConnectOptions) -> None:
        super().__init__(tts=tts, conn_options=conn_options)
        self._tts: SarvamTTS = tts

    async def _speak(self, text: str, output_emitter: tts.AudioEmitter) -> None:
        text = text.strip()
        if not text or not has_sarvam_script(text, self._tts._language):
            return
        lang = _LANG.get(self._tts._language, "hi-IN")
        body = {
            "text": text[:3500],
            "language_code": lang,
            "target_language_code": lang,
            "model": "bulbul:v3",
            "speaker": self._tts._speaker,
            "output_audio_codec": "linear16",
            "speech_sample_rate": _SAMPLE_RATE,
        }
        headers = {
            "api-subscription-key": self._tts._api_key,
            "Content-Type": "application/json",
        }
        self._mark_started()
        async with self._tts._client.stream(
            "POST", _SARVAM_HTTP, headers=headers, json=body
        ) as resp:
            if resp.status_code >= 400:
                err = (await resp.aread())[:400]
                raise APIStatusError(
                    f"Sarvam TTS {resp.status_code}: {err!r}",
                    status_code=resp.status_code,
                )
            async for chunk in resp.aiter_bytes():
                if chunk:
                    output_emitter.push(chunk)
        logger.info("Sarvam HTTP sentence lang=%s chars=%d", self._tts._language, len(text))

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        output_emitter.initialize(
            request_id=str(uuid.uuid4()),
            sample_rate=_SAMPLE_RATE,
            num_channels=1,
            mime_type="audio/pcm",
            stream=True,
        )
        output_emitter.start_segment(segment_id=str(uuid.uuid4()))
        pending: list[str] = []
        try:
            async for data in self._input_ch:
                if _is_flush(self, data):
                    await self._speak("".join(pending), output_emitter)
                    pending.clear()
                    continue
                piece = data if isinstance(data, str) else str(data)
                if piece.strip():
                    pending.append(piece)
            await self._speak("".join(pending), output_emitter)
            output_emitter.flush()
        except APIStatusError:
            raise
        except Exception as exc:
            raise APIConnectionError(f"Sarvam TTS stream failed: {exc}") from exc


class LanguageRoutedTTS(tts.TTS):
    """Kokoro (streamed) for English; Sarvam WebSocket for Hindi/Punjabi."""

    def __init__(self, *, english: tts.TTS, indic: SarvamTTS | None) -> None:
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=True),
            sample_rate=english.sample_rate,
            num_channels=english.num_channels,
        )
        self._english = english
        self._indic = indic
        self.spoken = "en"

    @property
    def engine(self) -> str:
        if self.spoken in _LANG and self._indic is not None:
            return f"sarvam-http:{self.spoken}"
        return "kokoro"

    def set_spoken(self, language: str) -> bool:
        code = language if language in {"en", "hi", "pa"} else "en"
        if code in _LANG and self._indic is None:
            logger.warning(
                "Sarvam TTS requested (%s) but SARVAM_API_KEY is unset — staying on Kokoro",
                code,
            )
            return False
        changed = code != self.spoken
        self.spoken = code
        if self._indic is not None and code in _LANG:
            self._indic.set_language(code)
        return changed

    def _active(self, text: str | None = None) -> tts.TTS:
        if self.spoken in _LANG and self._indic is not None:
            if text is None or has_sarvam_script(text, self.spoken):
                return self._indic
            logger.info("Sarvam skip Latin-only line — Kokoro fallback")
        return self._english

    def synthesize(
        self,
        text: str,
        *,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> tts.ChunkedStream:
        return self._active(text).synthesize(text, conn_options=conn_options)

    def stream(
        self, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> tts.SynthesizeStream:
        return self._active().stream(conn_options=conn_options)


def build_sarvam_tts() -> SarvamTTS | None:
    key = (os.getenv("SARVAM_API_KEY") or "").strip()
    if not key:
        return None
    speaker = (os.getenv("SARVAM_TTS_SPEAKER") or "priya").strip() or "priya"
    return SarvamTTS(api_key=key, speaker=speaker)

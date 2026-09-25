"""Sarvam Saaras speech-to-text for the voice agent.

Batch recognize after VAD, same shape as the previous Whisper path.
Language is left to Saaras auto-detect so a Hindi or Punjabi turn is not
forced into the session's starting language.
"""

from __future__ import annotations

import logging
import os
import uuid

import httpx
from livekit import rtc
from livekit.agents import APIConnectionError, APIStatusError, stt
from livekit.agents.types import NOT_GIVEN, APIConnectOptions, NotGivenOr

logger = logging.getLogger("agent")

_SARVAM_STT_HTTP = "https://api.sarvam.ai/speech-to-text"
_DEFAULT_MODEL = "saaras:v3"


def sarvam_stt_model() -> str:
    raw = (os.getenv("SARVAM_STT_MODEL") or os.getenv("STT_MODEL") or _DEFAULT_MODEL).strip()
    if raw.startswith(("saaras", "saarika")):
        return raw
    return _DEFAULT_MODEL


class SarvamSTT(stt.STT):
    def __init__(
        self,
        *,
        api_key: str,
        model: str | None = None,
        http_session: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(
            capabilities=stt.STTCapabilities(streaming=False, interim_results=False)
        )
        self._api_key = api_key
        self._model = model or sarvam_stt_model()
        self._client = http_session
        self._owns_client = http_session is None

    @property
    def model(self) -> str:
        return self._model

    @property
    def provider(self) -> str:
        return "sarvam"

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0))
        return self._client

    async def _recognize_impl(
        self,
        buffer: rtc.AudioFrame,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions,
    ) -> stt.SpeechEvent:
        del language, conn_options  # auto-detect; do not lock the session language
        frame = rtc.combine_audio_frames(buffer)
        if frame.samples_per_channel <= 0:
            return _empty_event()
        wav = frame.to_wav_bytes()
        try:
            resp = await self._http().post(
                _SARVAM_STT_HTTP,
                headers={"api-subscription-key": self._api_key},
                files={"file": ("audio.wav", wav, "audio/wav")},
                data={"model": self._model, "mode": "transcribe"},
            )
        except httpx.HTTPError as exc:
            raise APIConnectionError(f"Sarvam STT connection failed: {exc}") from exc
        if resp.status_code >= 400:
            raise APIStatusError(
                f"Sarvam STT {resp.status_code}: {resp.text[:300]}",
                status_code=resp.status_code,
            )
        body = resp.json()
        text = str(body.get("transcript") or body.get("text") or "").strip()
        lang = str(body.get("language_code") or body.get("language") or "en-IN")
        logger.info("sarvam stt lang=%s chars=%d", lang, len(text))
        return stt.SpeechEvent(
            type=stt.SpeechEventType.FINAL_TRANSCRIPT,
            request_id=str(body.get("request_id") or uuid.uuid4()),
            alternatives=[stt.SpeechData(language=lang, text=text)],
        )

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None


def _empty_event() -> stt.SpeechEvent:
    return stt.SpeechEvent(
        type=stt.SpeechEventType.FINAL_TRANSCRIPT,
        request_id=str(uuid.uuid4()),
        alternatives=[stt.SpeechData(language="en-IN", text="")],
    )

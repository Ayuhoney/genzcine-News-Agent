"""Sarvam Saaras speech-to-text for the voice agent.

Supports both real-time streaming recognition over WebSocket and batch
recognition fallback. Language defaults to 'unknown' (Sarvam auto-detect)
so turns in Hindi, Punjabi, Bengali, Marathi, English, etc. are accurately
identified without locking the session language.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import uuid

try:
    import aiohttp
except ImportError:
    aiohttp = None  # type: ignore[assignment]
import httpx
from livekit import rtc
from livekit.agents import APIConnectionError, APIStatusError, stt
from livekit.agents.types import NOT_GIVEN, APIConnectOptions, NotGivenOr

try:
    from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS
except ImportError:
    DEFAULT_API_CONNECT_OPTIONS = APIConnectOptions()  # type: ignore[assignment]

try:
    from livekit.plugins import sarvam
except ImportError:
    sarvam = None

logger = logging.getLogger("agent")

_SARVAM_STT_HTTP = "https://api.sarvam.ai/speech-to-text"
_DEFAULT_MODEL = "saaras:v3"


def sarvam_stt_model() -> str:
    raw = (os.getenv("SARVAM_STT_MODEL") or os.getenv("STT_MODEL") or _DEFAULT_MODEL).strip()
    if raw.startswith(("saaras", "saarika")):
        return raw
    return _DEFAULT_MODEL


class SarvamWebSocketStream(stt.RecognizeStream):
    """Direct WebSocket streaming recognizer for Sarvam Saaras STT."""

    def __init__(
        self,
        *,
        stt_instance: stt.STT,
        conn_options: APIConnectOptions,
        api_key: str,
        model: str,
        language: str = "unknown",
        sample_rate: int = 16000,
    ) -> None:
        super().__init__(stt=stt_instance, conn_options=conn_options, sample_rate=sample_rate)
        self._api_key = api_key
        self._model = model
        self._language = language or "unknown"
        self._sample_rate = sample_rate

    async def _run(self) -> None:
        url = (
            f"wss://api.sarvam.ai/speech-to-text/ws"
            f"?language-code={self._language}&model={self._model}&vad_signals=true"
        )
        headers = {
            "api-subscription-key": self._api_key,
        }

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60.0)) as ws_session:
            async with ws_session.ws_connect(url, headers=headers) as ws:
                logger.info(
                    "Connected to Sarvam STT streaming WebSocket (model=%s, lang=%s)",
                    self._model,
                    self._language,
                )

                async def _send_loop() -> None:
                    try:
                        async for item in self._input_ch:
                            if isinstance(item, self._FlushSentinel):
                                continue
                            wav = item.to_wav_bytes()
                            b64 = base64.b64encode(wav).decode("ascii")
                            payload = {
                                "audio": {
                                    "data": b64,
                                    "sample_rate": self._sample_rate,
                                    "encoding": "audio/wav",
                                }
                            }
                            await ws.send_json(payload)
                    except asyncio.CancelledError:
                        pass
                    except Exception as exc:
                        logger.warning("Sarvam STT ws send error: %s", exc)

                async def _recv_loop() -> None:
                    try:
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                try:
                                    body = json.loads(msg.data)
                                except Exception:
                                    continue
                                data = body.get("data", {}) if body.get("type") == "data" else body
                                transcript = str(data.get("transcript") or data.get("text") or "").strip()
                                if transcript:
                                    lang = str(data.get("language_code") or data.get("language") or self._language)
                                    req_id = str(data.get("request_id") or uuid.uuid4())
                                    logger.info("sarvam stt streaming transcript: %r (lang=%s)", transcript[:60], lang)
                                    self._event_ch.send_nowait(
                                        stt.SpeechEvent(
                                            type=stt.SpeechEventType.FINAL_TRANSCRIPT,
                                            request_id=req_id,
                                            alternatives=[stt.SpeechData(language=lang, text=transcript)],
                                        )
                                    )
                            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                break
                    except asyncio.CancelledError:
                        pass
                    except Exception as exc:
                        logger.warning("Sarvam STT ws recv error: %s", exc)

                send_task = asyncio.create_task(_send_loop())
                recv_task = asyncio.create_task(_recv_loop())
                try:
                    done, pending = await asyncio.wait(
                        [send_task, recv_task],
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                finally:
                    for task in (send_task, recv_task):
                        if not task.done():
                            task.cancel()


class SarvamSTT(stt.STT):
    def __init__(
        self,
        *,
        api_key: str,
        model: str | None = None,
        language: str = "unknown",
        http_session: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(
            capabilities=stt.STTCapabilities(
                streaming=True,
                interim_results=True,
                offline_recognize=True,
            )
        )
        self._api_key = api_key
        self._model = model or sarvam_stt_model()
        self._language = language
        self._client = http_session
        self._owns_client = http_session is None

        self._plugin_stt = None
        if sarvam is not None:
            try:
                self._plugin_stt = sarvam.STT(
                    language="unknown",
                    model=self._model,
                    api_key=self._api_key,
                )
            except Exception as exc:
                logger.warning("Sarvam plugin STT init skipped: %s", exc)

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

    def stream(
        self,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> stt.RecognizeStream:
        lang = str(language) if language != NOT_GIVEN and language else self._language
        if self._plugin_stt is not None:
            try:
                return self._plugin_stt.stream(
                    language=lang,
                    conn_options=conn_options,
                )
            except Exception as exc:
                logger.warning("Sarvam plugin stream failed (%s), falling back to WebSocketStream", exc)
        return SarvamWebSocketStream(
            stt_instance=self,
            conn_options=conn_options,
            api_key=self._api_key,
            model=self._model,
            language=lang,
        )

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
        if self._plugin_stt is not None:
            await self._plugin_stt.aclose()
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None


def _empty_event() -> stt.SpeechEvent:
    return stt.SpeechEvent(
        type=stt.SpeechEventType.FINAL_TRANSCRIPT,
        request_id=str(uuid.uuid4()),
        alternatives=[stt.SpeechData(language="en-IN", text="")],
    )

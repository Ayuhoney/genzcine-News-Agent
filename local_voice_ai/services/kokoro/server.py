"""Minimal OpenAI-compatible TTS server backed by the ``kokoro`` PyPI package.

Replaces the ``ghcr.io/remsky/kokoro-fastapi-cpu`` image with a small in-tree
service that exposes only what ``livekit.plugins.openai.TTS`` needs:

  - ``POST /v1/audio/speech``  → audio bytes, or streamed PCM when
    ``response_format=pcm`` / ``stream_format=audio``
  - ``GET  /v1/models``         → list of one model
  - ``GET  /health``            → readiness probe

The model is loaded once at startup and reused across requests.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import logging
import os
import re
import threading
import time
from contextlib import asynccontextmanager
from typing import Iterator, Optional

import numpy as np
import soundfile as sf
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger("kokoro")
logging.basicConfig(level=logging.INFO)

MODEL_ID = os.getenv("KOKORO_MODEL_ID", "kokoro")
LANG_CODE = os.getenv("KOKORO_LANG_CODE", "a")  # 'a' = American English
DEFAULT_VOICE = os.getenv("KOKORO_DEFAULT_VOICE", "af_nova")
SAMPLE_RATE = 24000

# Kokoro-82M language codes. The first letter of a voice id selects the
# language pipeline: af_nova -> 'a' (US English), hf_alpha -> 'h' (Hindi), ...
SUPPORTED_LANG_CODES = {
    "a",  # American English
    "b",  # British English
    "e",  # Spanish
    "f",  # French
    "h",  # Hindi
    "i",  # Italian
    "j",  # Japanese  (needs misaki[ja])
    "p",  # Brazilian Portuguese
    "z",  # Mandarin  (needs misaki[zh])
}

# One KPipeline per language, created lazily and cached (the 82M model weights
# are shared; each pipeline only adds that language's G2P frontend).
_pipelines: dict[str, object] = {}
_pipeline_locks: dict[str, threading.Lock] = {}
_espeak_fixed = False


def _lock_for(lang_code: str) -> threading.Lock:
    lock = _pipeline_locks.get(lang_code)
    if lock is None:
        lock = threading.Lock()
        _pipeline_locks[lang_code] = lock
    return lock


def _fix_espeak() -> None:
    """Point phonemizer at the system espeak-ng when it is installed.

    misaki configures phonemizer to use the bundled ``espeakng-loader`` wheel,
    whose shared library carries a broken compiled-in data path — espeak-ng
    then aborts the whole process at init ("Error processing file ...phontab").
    The system espeak-ng (apt install espeak-ng) always finds its own data.
    """
    global _espeak_fixed
    if _espeak_fixed:
        return
    _espeak_fixed = True
    try:
        import ctypes.util

        lib = ctypes.util.find_library("espeak-ng")
        if not lib:
            logger.warning("system espeak-ng not found — using bundled espeakng-loader")
            return
        # Import first so misaki's module-level path setup runs before our override.
        import misaki.espeak  # noqa: F401  # type: ignore[import-not-found]
        from phonemizer.backend.espeak.wrapper import (  # type: ignore[import-not-found]
            EspeakWrapper,
        )

        EspeakWrapper.set_library(lib)
        EspeakWrapper.set_data_path(None)  # None -> system default data
        logger.info("phonemizer using system espeak-ng: %s", lib)
    except Exception:
        logger.exception("espeak override failed — continuing with defaults")


def _get_pipeline(lang_code: str):
    pipeline = _pipelines.get(lang_code)
    if pipeline is None:
        logger.info("loading kokoro pipeline (lang=%s)", lang_code)
        from kokoro import KPipeline  # type: ignore[import-not-found]

        _fix_espeak()
        pipeline = KPipeline(lang_code=lang_code)
        _pipelines[lang_code] = pipeline
        logger.info("kokoro pipeline ready (lang=%s)", lang_code)
    return pipeline


def _lang_for_voice(voice: str) -> str:
    code = (voice or "")[:1].lower()
    return code if code in SUPPORTED_LANG_CODES else LANG_CODE


@asynccontextmanager
async def lifespan(app: FastAPI):
    _get_pipeline(LANG_CODE)  # preload the default language
    yield


app = FastAPI(title="Kokoro TTS Server", lifespan=lifespan)


class SpeechRequest(BaseModel):
    model: Optional[str] = None
    input: str
    voice: Optional[str] = None
    response_format: Optional[str] = "wav"
    speed: Optional[float] = 1.0
    stream: Optional[bool] = None
    stream_format: Optional[str] = None  # openai SDK sends "audio" | "sse"


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?।])\s+")


def _split_spoken_units(text: str) -> list[str]:
    """Kokoro often yields one blob for a whole paragraph. Split so the first
    sentence can stream out while later ones are still synthesizing."""
    clean = (text or "").strip()
    if not clean:
        return []
    parts = [p.strip() for p in _SENTENCE_SPLIT.split(clean) if p.strip()]
    return parts or [clean]


def _to_pcm16(audio: np.ndarray) -> bytes:
    pcm = np.clip(np.asarray(audio, dtype=np.float32), -1.0, 1.0)
    return (pcm * 32767.0).astype(np.int16).tobytes()


def _synth_unit(pipeline, text: str, voice: str, speed: float) -> Iterator[bytes]:
    for _, _, audio in pipeline(text, voice=voice, speed=speed):
        if hasattr(audio, "cpu"):
            audio = audio.cpu().numpy()
        chunk = _to_pcm16(audio)
        if chunk:
            yield chunk


def _iter_pcm_chunks(text: str, voice: str, speed: float) -> Iterator[bytes]:
    """Yield s16le PCM after each spoken sentence/clause."""
    lang = _lang_for_voice(voice)
    units = _split_spoken_units(text)
    with _lock_for(lang):
        pipeline = _get_pipeline(lang)
        for unit in units:
            yield from _synth_unit(pipeline, unit, voice, speed)


def _should_stream(req: SpeechRequest) -> bool:
    if req.stream:
        return True
    if (req.stream_format or "").lower() == "audio":
        return True
    return (req.response_format or "").lower() == "pcm"


def _synthesize(text: str, voice: str, speed: float) -> np.ndarray:
    lang = _lang_for_voice(voice)
    chunks: list[np.ndarray] = []
    with _lock_for(lang):
        pipeline = _get_pipeline(lang)
        for _, _, audio in pipeline(text, voice=voice, speed=speed):
            if hasattr(audio, "cpu"):
                audio = audio.cpu().numpy()
            chunks.append(np.asarray(audio, dtype=np.float32))
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(chunks)


def _encode(audio: np.ndarray, fmt: str) -> tuple[bytes, str]:
    fmt = (fmt or "wav").lower()
    buf = io.BytesIO()

    if fmt in {"mp3", "opus", "aac", "flac"}:
        try:
            sf.write(buf, audio, SAMPLE_RATE, format=fmt.upper())
            return buf.getvalue(), f"audio/{fmt}"
        except Exception:
            buf = io.BytesIO()  # fall through to wav

    sf.write(buf, audio, SAMPLE_RATE, format="WAV", subtype="PCM_16")
    return buf.getvalue(), "audio/wav"


@app.post("/v1/audio/speech")
async def speech(req: SpeechRequest) -> Response:
    if not _pipelines:
        raise HTTPException(status_code=503, detail="model not loaded")
    if not req.input:
        raise HTTPException(status_code=400, detail="input is required")

    voice = req.voice or DEFAULT_VOICE
    speed = float(req.speed or 1.0)
    loop = asyncio.get_running_loop()

    if _should_stream(req):
        queue: asyncio.Queue[bytes | Exception | None] = asyncio.Queue()

        def _produce() -> None:
            try:
                for chunk in _iter_pcm_chunks(req.input, voice, speed):
                    loop.call_soon_threadsafe(queue.put_nowait, chunk)
                loop.call_soon_threadsafe(queue.put_nowait, None)
            except Exception as exc:
                loop.call_soon_threadsafe(queue.put_nowait, exc)

        produce_task = loop.run_in_executor(None, _produce)

        async def _pcm_stream():
            first = True
            try:
                while True:
                    item = await queue.get()
                    if item is None:
                        break
                    if isinstance(item, Exception):
                        logger.exception("synthesis failed")
                        if first:
                            raise item
                        break
                    first = False
                    yield item
            finally:
                await produce_task

        return StreamingResponse(
            _pcm_stream(),
            media_type="audio/pcm",
            headers={
                "Cache-Control": "no-store",
                "X-Accel-Buffering": "no",
            },
        )

    try:
        audio = await loop.run_in_executor(None, _synthesize, req.input, voice, speed)
    except Exception as exc:
        logger.exception("synthesis failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    data, media_type = _encode(audio, req.response_format or "wav")
    return Response(content=data, media_type=media_type)


@app.get("/v1/models")
async def list_models() -> JSONResponse:
    return JSONResponse(
        {
            "object": "list",
            "data": [
                {
                    "id": MODEL_ID,
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": "hexgrad",
                }
            ],
        }
    )


@app.get("/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "model_loaded": bool(_pipelines),
        "languages_loaded": sorted(_pipelines.keys()),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Kokoro TTS Server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8880)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()

    if args.workers > 1:
        uvicorn.run(
            "local_voice_ai.services.kokoro.server:app",
            host=args.host,
            port=args.port,
            workers=args.workers,
            timeout_keep_alive=30,
            loop="uvloop",
        )
    else:
        uvicorn.run(app, host=args.host, port=args.port, timeout_keep_alive=30)

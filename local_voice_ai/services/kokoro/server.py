"""Minimal OpenAI-compatible TTS server backed by the ``kokoro`` PyPI package.

Replaces the ``ghcr.io/remsky/kokoro-fastapi-cpu`` image with a small in-tree
service that exposes only what ``livekit.plugins.openai.TTS`` needs:

  - ``POST /v1/audio/speech``  → audio bytes
  - ``GET  /v1/models``         → list of one model
  - ``GET  /health``            → readiness probe

The model is loaded once at startup and reused across requests.
"""

from __future__ import annotations

import argparse
import io
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Optional

import numpy as np
import soundfile as sf
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, Response
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
_espeak_fixed = False


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
    response_format: Optional[str] = "mp3"
    speed: Optional[float] = 1.0


def _synthesize(text: str, voice: str, speed: float) -> np.ndarray:
    pipeline = _get_pipeline(_lang_for_voice(voice))
    chunks: list[np.ndarray] = []
    for _, _, audio in pipeline(text, voice=voice, speed=speed):
        if hasattr(audio, "cpu"):
            audio = audio.cpu().numpy()
        chunks.append(np.asarray(audio, dtype=np.float32))
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(chunks)


def _encode(audio: np.ndarray, fmt: str) -> tuple[bytes, str]:
    fmt = (fmt or "mp3").lower()
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
    try:
        audio = _synthesize(req.input, voice, float(req.speed or 1.0))
    except Exception as exc:
        logger.exception("synthesis failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    data, media_type = _encode(audio, req.response_format or "mp3")
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
    args = parser.parse_args()

    uvicorn.run(app, host=args.host, port=args.port)

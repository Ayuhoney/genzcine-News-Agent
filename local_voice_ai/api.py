
from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import timedelta, timezone
from typing import Any, Optional

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from livekit import api as lk_api
from livekit.protocol.room import RoomConfiguration
from starlette.middleware.base import BaseHTTPMiddleware

from .config import Config
from .services.db import close_db, connect_db
from .services.user_service import (
    complete_session,
    get_or_create_device,
    get_trial_status,
    log_session,
    mark_onboarded,
    mark_premium,
    record_ip_trial_seconds,
    save_avatar,
    save_participant_name,
)

TRIAL_SECONDS = 300  # 5-minute free trial

logger = logging.getLogger("api")

# ── regex constants ────────────────────────────────────────────────────────────
_SAFE_NAME_RE = re.compile(r"[^\w\s\-\.]", flags=re.UNICODE)
_GROUP_ROOM_RE = re.compile(r"^group_room_\d{4}$")
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)
_MAX_NAME_LEN = 60

# ── Simli ──────────────────────────────────────────────────────────────────────
# API key is read from cfg (Config object) inside build_app — not hardcoded here
SIMLI_UPLOAD_URL = "https://api.simli.ai/faces/trinity"
SIMLI_STATUS_URL = "https://api.simli.ai/faces/trinity/generation_status"

_ALLOWED_FACE_IDS: frozenset[str] = frozenset(
    {
        "b9e5fba3-071a-4e35-896e-211c4d6eaa7b",  # NOVA
        "afdb6a3e-3939-40aa-92df-01604c23101c",  # ARIA
        "dd10cb5a-d31d-4f12-b69f-6db3383c006e",  # MARK
    }
)

# ── rate limiting ──────────────────────────────────────────────────────────────
_rate_store: dict[str, list[float]] = defaultdict(list)
_RATE_WINDOW = 60.0
_RATE_MAX = 25


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _is_rate_limited(ip: str) -> bool:
    now = time.monotonic()
    cutoff = now - _RATE_WINDOW
    history = [t for t in _rate_store[ip] if t > cutoff]
    _rate_store[ip] = history
    if len(history) >= _RATE_MAX:
        return True
    _rate_store[ip].append(now)
    return False


# ── input helpers ──────────────────────────────────────────────────────────────
def _sanitise_name(raw: Any) -> str:
    if not isinstance(raw, str):
        return "model"
    cleaned = _SAFE_NAME_RE.sub("", raw).strip()
    return cleaned[:_MAX_NAME_LEN] or "model"


def _valid_uuid(value: Any) -> str | None:
    if isinstance(value, str) and _UUID_RE.match(value.strip()):
        return value.strip().lower()
    return None


def _validate_room_name(room: Any) -> str | None:
    if not isinstance(room, str):
        return None
    room = room.strip()
    return room if _GROUP_ROOM_RE.match(room) else None


# ── request access logger ─────────────────────────────────────────────────────
_access_log = logging.getLogger("access")

class _AccessLogMiddleware(BaseHTTPMiddleware):
    _SKIP = {"/healthz", "/favicon.ico"}

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        if request.url.path in self._SKIP:
            return await call_next(request)
        t0 = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            ms = int((time.perf_counter() - t0) * 1000)
            _access_log.error("%s %s ERR %dms ip=%s — %s",
                              request.method, request.url.path, ms,
                              _client_ip(request), exc)
            raise
        ms = int((time.perf_counter() - t0) * 1000)
        level = logging.WARNING if response.status_code >= 400 else logging.INFO
        _access_log.log(level, "%s %s %d %dms ip=%s",
                        request.method, request.url.path,
                        response.status_code, ms, _client_ip(request))
        return response


# ── security headers ───────────────────────────────────────────────────────────
class _SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Any) -> Any:
        response = await call_next(request)
        response.headers.update(
            {
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "X-XSS-Protection": "1; mode=block",
                "Referrer-Policy": "strict-origin-when-cross-origin",
                "Permissions-Policy": "camera=(self), microphone=(self), geolocation=()",
            }
        )
        return response


# ── token minting ──────────────────────────────────────────────────────────────
# Kokoro-supported session languages offered in the UI
_SUPPORTED_LANGUAGES = {"en-US", "en-GB", "es", "fr", "it", "pt-BR", "zh"}


def _mint_token(
    cfg: Config,
    agent_name: Optional[str],
    session_type: str,
    room_name: str,
    participant_name: str,
    face_id: Optional[str] = None,
    voice: str = "",
    trial_seconds: int = -1,
    language: str = "en-US",
    anchor_name: str = "NOVA",
) -> dict[str, Any]:
    safe_identity = re.sub(r"[^\w\-]", "_", participant_name.lower())[:40]
    participant_identity = f"{safe_identity}_{random.randint(0, 9999)}"

    token = (
        lk_api.AccessToken(cfg.livekit_api_key, cfg.livekit_api_secret)
        .with_identity(participant_identity)
        .with_name(participant_name)
        .with_ttl(timedelta(minutes=30))
        .with_grants(
            lk_api.VideoGrants(
                room=room_name,
                room_join=True,
                can_publish=True,
                can_publish_data=True,
                can_subscribe=True,
            )
        )
    )

    room_cfg = RoomConfiguration(
        metadata=json.dumps({
            "face_id": face_id or cfg.simli_face_id,
            "voice": voice,
            "trial_seconds": trial_seconds,
            "language": language,
            "anchor_name": anchor_name,
        }),
        agents=[lk_api.RoomAgentDispatch(agent_name=agent_name)] if agent_name else [],
    )
    token = token.with_room_config(room_cfg)

    return {
        "serverUrl": cfg.livekit_url,
        "roomName": room_name,
        "sessionType": session_type,
        "participantName": participant_name,
        "participantToken": token.to_jwt(),
    }


# ── app factory ────────────────────────────────────────────────────────────────
def build_app(cfg: Config) -> FastAPI:

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # noqa: ARG001
        try:
            await connect_db()
        except Exception:
            logger.exception("MongoDB connection failed — device endpoints will be unavailable")
        yield
        await close_db()

    app = FastAPI(title="genzcine-ai", version="1.0.0", lifespan=lifespan)

    app.add_middleware(_AccessLogMiddleware)
    app.add_middleware(_SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://localhost:3001",
            "http://127.0.0.1:3000",
        ],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
        allow_credentials=True,
        max_age=600,
    )

    # ── Device state ─────────────────────────────────────────────────────────

    @app.get("/api/device")
    async def device_get(request: Request) -> JSONResponse:
        """Return device state (onboarded, saved avatar). Creates device on first call."""
        device_id = _valid_uuid(request.query_params.get("id"))
        if not device_id:
            raise HTTPException(status_code=400, detail="Missing or invalid device id.")
        try:
            doc = await get_or_create_device(device_id)
        except Exception:
            logger.exception("device_get failed: id=%s", device_id)
            # Graceful degradation — client falls back to onboarding
            return JSONResponse({"onboarded": False, "avatar_face_id": None, "participant_name": None})
        return JSONResponse(
            {
                "onboarded": doc.get("onboarded", False),
                "avatar_face_id": doc.get("avatar_face_id"),
                "participant_name": doc.get("participant_name"),
            },
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/api/device/onboard")
    async def device_onboard(request: Request) -> JSONResponse:
        """Mark device as having completed onboarding."""
        try:
            body = await request.json()
        except Exception:
            body = {}
        device_id = _valid_uuid(body.get("device_id"))
        if not device_id:
            raise HTTPException(status_code=400, detail="Missing or invalid device id.")
        try:
            await mark_onboarded(device_id)
        except Exception:
            logger.exception("device_onboard failed: id=%s", device_id)
        return JSONResponse({"ok": True})

    @app.post("/api/device/avatar")
    async def device_avatar(request: Request) -> JSONResponse:
        """Persist the user's chosen avatar face ID."""
        try:
            body = await request.json()
        except Exception:
            body = {}
        device_id = _valid_uuid(body.get("device_id"))
        face_id = _valid_uuid(body.get("face_id"))
        if not device_id:
            raise HTTPException(status_code=400, detail="Missing or invalid device id.")
        # Accept any valid UUID — including custom faces created via upload
        if not face_id:
            raise HTTPException(status_code=400, detail="Missing or invalid face id.")
        try:
            await save_avatar(device_id, face_id)
        except Exception:
            logger.exception("device_avatar failed: id=%s face=%s", device_id, face_id)
        return JSONResponse({"ok": True})

    # ── Connection details ────────────────────────────────────────────────────

    @app.post("/api/connection-details")
    async def connection_details(request: Request) -> JSONResponse:
        ip = _client_ip(request)
        if _is_rate_limited(ip):
            logger.warning("rate limit hit: ip=%s", ip)
            raise HTTPException(status_code=429, detail="Too many requests. Try again later.")

        try:
            body = await request.json()
            if not isinstance(body, dict):
                body = {}
        except Exception:
            body = {}

        # session type — whitelist
        session_type = body.get("session_type", "individual")
        if session_type not in ("individual", "group"):
            session_type = "individual"

        # participant name
        participant_name = _sanitise_name(body.get("participant_name"))

        # device id (optional — for session logging)
        device_id = _valid_uuid(body.get("device_id"))

        # face_id — must be a known preset or a valid UUID from upload
        raw_face = body.get("face_id", "")
        face_id: str | None = (
            raw_face if (isinstance(raw_face, str) and _UUID_RE.match(raw_face)) else None
        )

        # voice — kokoro TTS voice id (e.g. af_nova, am_michael)
        voice: str = body.get("voice", "") or ""

        # language — session language (whitelist, kokoro-supported)
        language = body.get("language", "en-US")
        if language not in _SUPPORTED_LANGUAGES:
            language = "en-US"

        # anchor_name — display name of the chosen news anchor persona
        anchor_name = _sanitise_name(body.get("anchor_name") or "NOVA")
        if anchor_name == "model":  # _sanitise_name's generic fallback — use ours instead
            anchor_name = "NOVA"

        # room assignment
        raw_room = body.get("room_name")
        requested_room = _validate_room_name(raw_room)
        if session_type == "group":
            if raw_room:
                if not requested_room:
                    logger.warning("invalid room name: raw=%r ip=%s", raw_room, ip)
                    raise HTTPException(
                        status_code=400,
                        detail="Invalid room code. Format should be group_room_XXXX (e.g. group_room_4231).",
                    )
                room_name = requested_room
                logger.info("group join: room=%s participant=%s ip=%s", room_name, participant_name, ip)
            else:
                room_name = f"group_room_{random.randint(1000, 9999)}"
                logger.info("group create: room=%s participant=%s ip=%s", room_name, participant_name, ip)
        else:
            room_name = f"voice_assistant_room_{random.randint(0, 9999)}"

        # agent name
        agent_name: Optional[str] = None
        try:
            agent_name = body.get("room_config", {}).get("agents", [{}])[0].get("agent_name")
            if agent_name and not isinstance(agent_name, str):
                agent_name = None
        except (AttributeError, IndexError, TypeError):
            agent_name = None

        # ── trial check ───────────────────────────────────────────────────────
        trial_remaining = TRIAL_SECONDS  # default: full trial for unknown devices
        if device_id:
            try:
                trial = await get_trial_status(device_id, ip=ip)
                if trial["is_premium"]:
                    trial_remaining = -1  # unlimited
                else:
                    trial_remaining = max(0, TRIAL_SECONDS - trial["trial_used_seconds"])
                    if trial_remaining == 0:
                        logger.info("trial exhausted: device=%s ip=%s", device_id, ip)
                        raise HTTPException(
                            status_code=402,
                            detail="trial_expired",
                        )
            except HTTPException:
                raise
            except Exception:
                logger.exception("trial check failed — defaulting to full trial: device=%s", device_id)

        # mint token — passes trial_seconds into room metadata so the agent enforces it server-side
        try:
            data = _mint_token(
                cfg, agent_name, session_type, room_name, participant_name,
                face_id, voice, trial_seconds=trial_remaining,
                language=language, anchor_name=anchor_name,
            )
        except Exception as exc:
            logger.exception("token minting failed: ip=%s", ip)
            raise HTTPException(status_code=500, detail="Session could not be created.") from exc

        data["trialRemainingSeconds"] = trial_remaining

        # persist to MongoDB (non-blocking best-effort)
        if device_id:
            try:
                await log_session(device_id, participant_name, session_type, room_name, face_id)
                await save_participant_name(device_id, participant_name)
            except Exception:
                logger.exception("MongoDB session log failed — non-fatal")

        return JSONResponse(data, headers={"Cache-Control": "no-store, no-cache, must-revalidate"})

    # ── Session end ───────────────────────────────────────────────────────────

    @app.post("/api/session/end")
    async def session_end(request: Request) -> JSONResponse:
        """Called by frontend on disconnect. Saves duration + stats to MongoDB."""
        try:
            body = await request.json()
        except Exception:
            body = {}

        device_id = _valid_uuid(body.get("device_id"))
        room_name = body.get("room_name", "")
        if not device_id or not isinstance(room_name, str) or not room_name.strip():
            return JSONResponse({"ok": False}, status_code=400)

        try:
            duration_seconds = max(0, int(body.get("duration_seconds", 0)))
            messages_count = max(0, int(body.get("messages_count", 0)))
            posture_analyses = max(0, int(body.get("posture_analyses", 0)))
        except (TypeError, ValueError):
            duration_seconds = messages_count = posture_analyses = 0

        ip = _client_ip(request)
        try:
            await complete_session(
                device_id,
                room_name.strip(),
                duration_seconds,
                messages_count,
                posture_analyses,
            )
            # Mirror seconds to IP collection for bypass prevention
            await record_ip_trial_seconds(ip, duration_seconds)
            logger.info(
                "session ended: device=%s room=%s duration=%ds msgs=%d poses=%d ip=%s",
                device_id, room_name, duration_seconds, messages_count, posture_analyses, ip,
            )
        except Exception:
            logger.exception("session_end DB write failed — non-fatal")

        return JSONResponse({"ok": True})

    # ── Simli custom face upload ──────────────────────────────────────────────

    @app.post("/api/avatar/create-face")
    async def create_face(
        request: Request,
        file: UploadFile = File(...),
        name: str = Form("My Custom Avatar"),
    ) -> JSONResponse:
        """Proxy to Simli face-creation API. Returns {face_id}."""
        ip = _client_ip(request)
        if _is_rate_limited(ip):
            raise HTTPException(status_code=429, detail="Too many requests. Try again later.")

        allowed_types = {"image/jpeg", "image/png", "image/webp", "image/heic"}
        content_type = (file.content_type or "").split(";")[0].strip().lower()
        if content_type not in allowed_types:
            raise HTTPException(status_code=400, detail="Image must be JPEG, PNG, WEBP, or HEIC.")

        image_data = await file.read(10 * 1024 * 1024)
        if len(image_data) == 10 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Image must be smaller than 10 MB.")

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                # ── Step 1: submit image to Simli Trinity ──────────────────
                resp = await client.post(
                    SIMLI_UPLOAD_URL,
                    headers={"x-simli-api-key": cfg.simli_api_key},           # fixed header
                    files={"image": (file.filename or "photo.jpg", image_data, content_type)},  # fixed field
                    params={"face_name": name[:80]},                       # fixed: query param not form
                    timeout=30.0,
                )

                if resp.status_code in (401, 403):
                    raise HTTPException(
                        status_code=402,
                        detail="Custom face creation requires a paid Simli plan. Contact GenzCine support.",
                    )
                if not resp.is_success:
                    try:
                        raw = resp.json()
                        detail = raw.get("detail") or raw.get("message") or resp.text[:200]
                    except Exception:
                        detail = resp.text[:200] or f"Avatar service error {resp.status_code}"
                    raise HTTPException(status_code=502, detail=str(detail))

                try:
                    payload = resp.json()
                except Exception:
                    raise HTTPException(status_code=502, detail="Avatar service returned invalid response.")

                face_id = (
                    payload.get("face_id")
                    or payload.get("faceId")
                    or payload.get("id")
                    or (payload.get("data") or {}).get("face_id")
                    or (payload.get("data") or {}).get("faceId")
                )
                if not face_id:
                    raise HTTPException(
                        status_code=502,
                        detail=f"Avatar service did not return a face ID. Response: {str(payload)[:200]}",
                    )

                # ── Step 2: poll until generation is ready (max 90 s) ──────
                face_id_str = str(face_id)
                for _ in range(18):  # 18 × 5 s = 90 s
                    await asyncio.sleep(5)
                    try:
                        st = await client.get(
                            SIMLI_STATUS_URL,
                            headers={"x-simli-api-key": cfg.simli_api_key},
                            params={"face_id": face_id_str},
                            timeout=10.0,
                        )
                        if st.is_success:
                            st_data = st.json() if st.text else {}
                            status_val = str(st_data.get("status", "")).lower()
                            if status_val in ("completed", "done", "ready", "success", "available"):
                                break
                            if status_val in ("failed", "error"):
                                raise HTTPException(status_code=502, detail="Avatar generation failed.")
                    except HTTPException:
                        raise
                    except Exception:
                        pass  # transient error — keep polling

        except HTTPException:
            raise
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Avatar service timed out. Try again.")
        except (httpx.ReadError, httpx.ConnectError, httpx.RemoteProtocolError) as exc:
            logger.warning(
                "Face upload: Simli dropped connection — likely free-tier restriction: ip=%s err=%s",
                ip, exc,
            )
            raise HTTPException(
                status_code=402,
                detail="Custom face creation requires a paid Simli plan. Contact GenzCine support to unlock.",
            ) from exc
        except Exception as exc:
            logger.exception("Face upload failed: ip=%s", ip)
            raise HTTPException(status_code=502, detail="Could not reach avatar service.") from exc

        logger.info("Custom face created: face_id=%s ip=%s", face_id_str, ip)
        return JSONResponse({"face_id": face_id_str})

    # ── Health ────────────────────────────────────────────────────────────────

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    # ── Frontend error reporting ───────────────────────────────────────────────
    _fe_log = logging.getLogger("frontend")

    @app.post("/api/log")
    async def frontend_log(request: Request) -> JSONResponse:
        """Receive client-side errors from the frontend."""
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"ok": False}, status_code=400)
        level   = str(body.get("level", "error")).lower()
        message = str(body.get("message", ""))[:500]
        context = str(body.get("context", ""))[:300]
        ip      = _client_ip(request)
        if level == "warn":
            _fe_log.warning("client %s — %s %s", ip, message, context)
        elif level == "info":
            _fe_log.info("client %s — %s %s", ip, message, context)
        else:
            _fe_log.error("client %s — %s %s", ip, message, context)
        return JSONResponse({"ok": True})

    # ── Static SPA ────────────────────────────────────────────────────────────

    if cfg.frontend_dir:
        static = StaticFiles(directory=cfg.frontend_dir, html=True)

        @app.get("/{path:path}")
        async def spa(path: str, request: Request) -> Any:
            try:
                return await static.get_response(path or "index.html", request.scope)
            except Exception:
                return FileResponse(f"{cfg.frontend_dir}/index.html")

    return app

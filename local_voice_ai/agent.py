import asyncio
import json
import logging
import os
import time
from typing import Any

from urllib.parse import urlparse

import httpx
from livekit import rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    JobProcess,
    RunContext,
    cli,
    function_tool,
    room_io,
)
from livekit.plugins import openai, silero, simli
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from .services.agent_errors import classify_agent_error
from .services.news import fetch_latest_news
from .services.studio_events import STUDIO_TOPIC, headline_article, publish_studio_event
from .services.youtube import search_news_video

logger = logging.getLogger("agent")

LIVEKIT_API_KEY    = os.getenv("LIVEKIT_API_KEY",    "devkey")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET", "secret")

# LLM — default to Groq's free-tier workhorse (higher daily limits than 70B)
LLM_BASE_URL = os.getenv("LLAMA_BASE_URL", "https://api.groq.com/openai/v1")
LLM_MODEL    = os.getenv("LLAMA_MODEL",    "llama-3.1-8b-instant")
LLM_API_KEY  = os.getenv("LLAMA_API_KEY",  "")

# STT
STT_BASE_URL = os.getenv("STT_BASE_URL", "https://api.groq.com/openai/v1")
STT_MODEL    = os.getenv("STT_MODEL",    "whisper-large-v3-turbo")
STT_API_KEY  = os.getenv("STT_API_KEY",  "")

# TTS (Kokoro local)
TTS_BASE_URL = os.getenv("TTS_BASE_URL", "http://127.0.0.1:8880/v1")
TTS_VOICE    = os.getenv("TTS_VOICE",    "af_nova")
TTS_API_KEY  = os.getenv("TTS_API_KEY",  "no-key-needed")

# Simli
SIMLI_API_KEY      = os.getenv("SIMLI_API_KEY",      "")
SIMLI_FACE_ID      = os.getenv("SIMLI_FACE_ID",      "cace3ef7-a4c4-425d-a8cf-a5358eb0c427")
SIMLI_LIVEKIT_URL  = os.getenv("SIMLI_LIVEKIT_URL",  "")  # public tunnel URL for Simli

def _is_local_service_url(url: str) -> bool:
    host = urlparse(url).hostname or ""
    return host in {"", "127.0.0.1", "localhost", "::1"}


def _llm_client_options() -> dict:
    """Cap completion length; local llama.cpp also needs a longer read timeout."""
    opts: dict = {
        "max_completion_tokens": int(os.getenv("LLM_MAX_COMPLETION_TOKENS", "150")),
    }
    if _is_local_service_url(LLM_BASE_URL):
        read_s = float(os.getenv("LLM_READ_TIMEOUT", "120"))
        opts["timeout"] = httpx.Timeout(connect=15.0, read=read_s, write=30.0, pool=5.0)
    return opts


NEWS_HEADLINE_LIMIT = int(os.getenv("NEWS_HEADLINE_LIMIT", "8"))
# Beat between auto headlines after TTS ends. ~1.2s = news-studio pace (not a long pause).
HEADLINE_CONTINUE_SECONDS = float(os.getenv("HEADLINE_CONTINUE_SECONDS", "1.2"))
_HEADLINE_BRIDGES = (
    "Next up in today's news.",
    "Also making headlines.",
    "In other news.",
    "Moving on.",
)

_TRIAL_WARN_SAY = (
    "Just a heads up — about one minute left in your free GenzCine trial. "
    "Visit genzcine dot com for unlimited live news with me."
)
_TRIAL_END_SAY = (
    "Your free trial has ended. Thanks for watching today's news with GenzCine! "
    "Unlock unlimited access at genzcine dot com. Goodbye for now!"
)


LLM_OPTS = _llm_client_options()

_BASE_INSTRUCTIONS = """
You are {anchor_name}, GenzCine's AI news anchor — live, warm, authoritative. GenzCine is a
media platform in Mohali, Punjab, India (genzcine.com).

TOOLS (required):
- get_latest_news: fetch real headlines. Call before reporting ANY current news. Never invent headlines.
- play_news_video: show a YouTube clip on the viewer's device. Say one short intro line first; stay quiet until notified it ended.

ON-AIR STYLE:
- You are live in a news studio. After the intro, keep the bulletin going — do not wait for the viewer.
- Headlines play automatically one after another. When the viewer speaks, answer briefly (1-3 sentences), then the bulletin continues.
- Use get_latest_news only if they ask about a topic you have not covered yet.
- If the viewer interrupts during a headline, stop and respond, then resume the bulletin.
- Voice only — no bullets, emojis, or lists read verbatim.

TRIAL (5 min): open strong with headlines; near 4 min mention genzcine dot com for unlimited access.
"""

# Session languages — Kokoro TTS lang codes: a/b (English), e, f, h, i, j, p, z.
# code -> (display name, extra instruction for the LLM)
_LANGUAGES: dict[str, tuple[str, str]] = {
    "en-US": ("English", ""),
    "en-GB": ("English", "Use British English spelling and phrasing."),
    "hi": ("Hindi", "Write Hindi in Devanagari script. Common English news and media terms "
           "(breaking news, live, anchor, headline, exclusive) may stay in English where natural."),
    "es": ("Spanish", ""),
    "fr": ("French", ""),
    "it": ("Italian", ""),
    "pt-BR": ("Brazilian Portuguese", ""),
    "zh": ("Mandarin Chinese", "Write in Simplified Chinese."),
}


def _language_addon(language: str) -> str:
    name, extra = _LANGUAGES.get(language, ("English", ""))
    if name == "English" and not extra:
        return ""
    return (
        "\n\n"
        "SESSION LANGUAGE:\n"
        f"The viewer chose {name} for this session. Speak ONLY in {name} from your very "
        f"first greeting to the end — every headline, comment, and question. "
        f"Do not switch to another language unless the viewer explicitly asks. {extra}"
    )


_GROUP_ADDON = (
    "\n\n"
    "GROUP SESSION MODE:\n"
    "You are currently broadcasting to a GROUP — multiple viewers watching together in the "
    "same room. Follow these additional guidelines:\n"
    "- Welcome each participant by name and make everyone feel included\n"
    "- Address the group as a whole for headlines and general coverage\n"
    "- Call on participants by name when they ask a question or react\n"
    "- Rotate attention fairly — do not focus on one viewer for too long\n"
    "- Keep individual responses short so the group broadcast keeps moving\n"
    "- Greet new participants who join mid-session by name"
)

# Default spoken line when error type can't be determined (TTS-only, no LLM).
_BUSY_FALLBACK = (
    "Hi — I'm having a little trouble reaching the news desk right now. "
    "Please disconnect and try again in a moment. I'll be right here when you're ready."
)


def _trim_description(text: str, *, limit: int = 100) -> str:
    clean = (text or "").strip()
    if len(clean) <= limit:
        return clean
    cut = clean[: limit - 3].rsplit(" ", 1)[0]
    return f"{cut}..."


def _headline_spoken_line(
    anchor_name: str,
    article: dict,
    *,
    is_first: bool = False,
    index: int = 0,
    viewer_name: str | None = None,
) -> str:
    title = str(article.get("title", "")).strip()
    desc = _trim_description(str(article.get("description", "")))
    if is_first:
        who = f" {viewer_name}" if viewer_name else ""
        greet = f"Hey{who}! I'm {anchor_name}, your GenzCine news anchor. This is today's news."
        body = f" {title}. {desc}" if desc else f" {title}."
        return f"{greet}{body}".strip()
    bridge = _HEADLINE_BRIDGES[index % len(_HEADLINE_BRIDGES)]
    body = f" {title}. {desc}" if desc else f" {title}."
    return f"{bridge}{body}".strip()


async def _refresh_headlines(agent: "Assistant", *, topic: str = "") -> bool:
    articles = await fetch_latest_news(
        query=topic or None,
        language=agent._language,
        limit=NEWS_HEADLINE_LIMIT,
    )
    if not articles:
        return False
    await agent._publish_headlines(articles, topic=topic)
    return True


# When True for a room, the next agent transcript is skipped (error TTS apology).
_skip_agent_transcript: dict[str, bool] = {}


async def _handle_agent_error(
    session: AgentSession,
    room: rtc.Room | None,
    err: Any,
    *,
    reason: str = "unknown",
    anchor_name: str = "NOVA",
    source: str = "",
) -> None:
    """Speak a specific apology via TTS and push a structured error to the studio UI."""
    info = classify_agent_error(err, source=source or reason)
    room_name = room.name if room else ""
    try:
        logger.warning("agent error (%s / %s): code=%s", reason, source, info.code)
        if room_name:
            _skip_agent_transcript[room_name] = True
        await publish_studio_event(room, info.to_studio_event(anchor_name=anchor_name))
        await session.say(info.spoken, allow_interruptions=True)
    except Exception:
        logger.exception("agent error handler failed — last-resort fallback")
        try:
            if room_name:
                _skip_agent_transcript[room_name] = True
            await publish_studio_event(
                room,
                classify_agent_error("unknown").to_studio_event(anchor_name=anchor_name),
            )
            await session.say(_BUSY_FALLBACK, allow_interruptions=True)
        except Exception:
            pass
    finally:
        if room_name:
            async def _clear_skip() -> None:
                await asyncio.sleep(4)
                _skip_agent_transcript.pop(room_name, None)
            asyncio.create_task(_clear_skip())


async def _say_busy_fallback(
    session: AgentSession,
    room: rtc.Room | None = None,
    *,
    reason: str = "llm_error",
    anchor_name: str = "NOVA",
) -> None:
    """Legacy entry — routes through structured error handler."""
    await _handle_agent_error(
        session, room, reason, reason=reason, anchor_name=anchor_name, source=reason
    )


async def _safe_generate_reply(
    session: AgentSession,
    room: rtc.Room | None,
    *,
    instructions: str,
    fallback_reason: str = "generate_reply_failed",
    anchor_name: str = "NOVA",
) -> bool:
    """Try LLM reply; on failure speak a structured error instead of going silent."""
    try:
        await session.generate_reply(instructions=instructions)
        return True
    except Exception as exc:
        logger.exception("generate_reply failed — %s", fallback_reason)
        await _handle_agent_error(
            session, room, exc,
            reason=fallback_reason,
            anchor_name=anchor_name,
            source="LLM",
        )
        return False


class Assistant(Agent):
    def __init__(
        self,
        session_type: str = "individual",
        room: rtc.Room | None = None,
        anchor_name: str = "NOVA",
        language: str = "en-US",
    ) -> None:
        self._session_type = session_type
        self._participants: dict[str, str] = {}  # identity -> display name
        self._room = room
        self._anchor_name = anchor_name
        self._language = language
        self._video_playing = False
        self._last_headlines: list[dict] = []
        self._headline_index = 0

        instructions = (
            _BASE_INSTRUCTIONS.format(anchor_name=anchor_name)
            + _language_addon(language)
            + (_GROUP_ADDON if session_type == "group" else "")
        )
        super().__init__(instructions=instructions)

    async def _publish_studio(self, event: dict) -> None:
        await publish_studio_event(self._room, event)

    async def _publish_headlines(self, articles: list[dict], *, topic: str = "") -> None:
        self._last_headlines = articles
        self._headline_index = 0
        items = [headline_article(a, index=i) for i, a in enumerate(articles)]
        await self._publish_studio(
            {
                "type": "headlines",
                "topic": topic,
                "articles": items,
                "activeIndex": 0,
                "activeHeadline": items[0] if items else None,
            }
        )

    async def _publish_headline_now(self) -> None:
        if not self._last_headlines:
            return
        idx = self._headline_index % len(self._last_headlines)
        article = headline_article(self._last_headlines[idx], index=idx)
        await self._publish_studio(
            {
                "type": "headline_now",
                "activeIndex": idx,
                "headline": article,
            }
        )
        self._headline_index += 1

    async def _deliver_headline_via_tts(
        self,
        *,
        is_first: bool = False,
        viewer_name: str | None = None,
    ) -> bool:
        """Speak the next headline via TTS only — no LLM call (saves tokens)."""
        if (
            not self._last_headlines
            or self._headline_index >= len(self._last_headlines)
        ):
            if not await _refresh_headlines(self):
                return False

        idx = self._headline_index % len(self._last_headlines)
        article = self._last_headlines[idx]
        text = _headline_spoken_line(
            self._anchor_name,
            article,
            is_first=is_first,
            index=idx,
            viewer_name=viewer_name,
        )
        await self._publish_headline_now()
        await self.session.say(text, allow_interruptions=True)
        return True

    @function_tool
    async def get_latest_news(self, context: RunContext, topic: str = "") -> str:
        """Fetch real, live news headlines — optionally filtered by topic.

        Always call this before reporting anything as current news; never invent
        headlines. Call again whenever the viewer asks about a new subject.

        Args:
            topic: Optional subject to search for (e.g. "technology", "cricket",
                "stock market", "Bollywood"). Leave empty for general top headlines.
        """
        articles = await fetch_latest_news(
            query=topic or None, language=self._language, limit=NEWS_HEADLINE_LIMIT
        )
        if not articles:
            await self._publish_studio(
                {
                    "type": "agent_error",
                    "code": "news_unavailable",
                    "title": "Headlines unavailable",
                    "message": "Live headlines couldn't be loaded right now.",
                    "retryable": True,
                    "retryAfterSeconds": 30,
                    "topic": topic or "",
                }
            )
            return (
                "No fresh headlines could be fetched right now. Tell the viewer briefly and "
                "naturally, then keep the conversation going without inventing news."
            )
        await self._publish_headlines(articles, topic=topic or "")
        lines = [f"- {a['title']} ({a['source']})" for a in articles]
        return (
            "Headlines fetched (titles only — expand briefly when speaking, do not invent):\n"
            + "\n".join(lines)
        )

    @function_tool
    async def play_news_video(self, context: RunContext, topic: str) -> str:
        """Find and play a real, relevant video clip full-screen on the viewer's device.

        Call this when the viewer asks to see footage, or when a story is clearly
        visual and a real clip would land better than a verbal description.

        Args:
            topic: What the video should be about (e.g. "SpaceX launch highlights",
                "India vs Australia match highlights").
        """
        if self._room is None:
            return "Video playback unavailable right now — continue reporting verbally."
        result = await search_news_video(topic)
        if result is None:
            await self._publish_studio(
                {"type": "video_error", "topic": topic, "message": "video_not_found"}
            )
            return f"Could not find a video for '{topic}' — continue reporting verbally."
        video_id = result["video_id"]
        video_title = result["title"]
        thumbnail = result.get("thumbnail_url", "")
        channel = result.get("channel_title", "")
        studio_video = {
            "type": "video_start",
            "videoId": video_id,
            "title": video_title,
            "topic": topic,
            "thumbnailUrl": thumbnail,
            "channelTitle": channel,
            "embedUrl": f"https://www.youtube.com/embed/{video_id}",
        }
        try:
            # Legacy topic — existing clients still listen here.
            legacy_payload = json.dumps(
                {
                    "type": "news_video",
                    "videoId": video_id,
                    "title": video_title,
                    "topic": topic,
                    "thumbnailUrl": thumbnail,
                    "channelTitle": channel,
                }
            )
            await self._room.local_participant.publish_data(
                legacy_payload.encode(), reliable=True, topic="news_video"
            )
            await self._publish_studio(studio_video)
            await self._publish_studio({"type": "studio_state", "mode": "video", "topic": topic})
        except Exception:
            logger.exception("play_news_video publish failed")
            return "Could not start the video — continue reporting verbally."
        logger.info("[%s] news video started: topic=%r video_id=%s", self._session_type, topic, video_id)
        self._video_playing = True
        return (
            f"Video '{video_title}' is now playing full-screen on the viewer's device. "
            "Say ONE short line introducing it, then stay quiet until notified it ended."
        )

    async def on_enter(self) -> None:
        try:
            room = self._room

            if room is not None:
                for identity, participant in room.remote_participants.items():
                    self._participants[identity] = participant.name or identity
                room.on("participant_connected", self._on_participant_connected)
                room.on("participant_disconnected", self._on_participant_disconnected)

            participant_names = list(self._participants.values())

            if self._session_type == "group":
                count = len(participant_names)
                name_list = ", ".join(participant_names) if participant_names else "everyone"
                if await _refresh_headlines(self):
                    greet = (
                        f"Hey {name_list}! I'm {self._anchor_name}, live with GenzCine News "
                        f"for our group of {count}. Here's what's happening right now."
                    )
                    await self.session.say(greet, allow_interruptions=True)
                    await self._deliver_headline_via_tts(is_first=False)
                else:
                    await self.session.say(
                        f"Hey {name_list}! I'm {self._anchor_name}. "
                        "Headlines are loading — hang tight.",
                        allow_interruptions=True,
                    )
            else:
                viewer_name = participant_names[0] if participant_names else None
                if await _refresh_headlines(self):
                    await self._deliver_headline_via_tts(
                        is_first=True,
                        viewer_name=viewer_name,
                    )
                else:
                    await self.session.say(
                        f"Hi! I'm {self._anchor_name}, your GenzCine news anchor. "
                        "Great to have you in the studio — what would you like to hear about today?",
                        allow_interruptions=True,
                    )
        except Exception as exc:
            logger.exception("[%s] on_enter failed — attempting fallback greeting", self._session_type)
            await _handle_agent_error(
                self.session,
                self._room,
                exc,
                reason="on_enter_exception",
                anchor_name=self._anchor_name,
            )

    def _on_participant_connected(self, participant: rtc.RemoteParticipant) -> None:
        try:
            name = participant.name or participant.identity
            self._participants[participant.identity] = name
            logger.info("[%s] participant joined: %s", self._session_type, name)
        except Exception:
            logger.exception("_on_participant_connected error")

    def _on_participant_disconnected(self, participant: rtc.RemoteParticipant) -> None:
        try:
            removed = self._participants.pop(participant.identity, participant.identity)
            logger.info("[%s] participant left: %s", self._session_type, removed)
        except Exception:
            logger.exception("_on_participant_disconnected error")


# ── Server setup ──────────────────────────────────────────────────────────────

server = AgentServer()


def prewarm(proc: JobProcess) -> None:
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


@server.rtc_session()
async def my_agent(ctx: JobContext) -> None:
    ctx.log_context_fields = {"room": ctx.room.name}

    # Detect session type from room name prefix set by the API
    session_type = "group" if ctx.room.name.startswith("group_room_") else "individual"

    logger.info(
        "agent session: type=%s stt=%s llm=%s tts=%s",
        session_type, STT_MODEL, LLM_MODEL, TTS_BASE_URL,
    )

    await ctx.connect()

    # Metadata is JSON: {"face_id": "...", "voice": "...", "trial_seconds": N,
    #                     "language": "hi", "anchor_name": "NOVA"}
    try:
        meta = json.loads(ctx.room.metadata or "{}")
        face_id = meta.get("face_id", "").strip() or SIMLI_FACE_ID
        voice = meta.get("voice", "").strip() or TTS_VOICE
        trial_seconds = int(meta.get("trial_seconds", -1))
        language = str(meta.get("language", "") or "en-US")
        anchor_name = str(meta.get("anchor_name", "") or "NOVA")
    except (json.JSONDecodeError, AttributeError, ValueError):
        face_id = (ctx.room.metadata or "").strip() or SIMLI_FACE_ID
        voice = TTS_VOICE
        trial_seconds = -1
        language = "en-US"
        anchor_name = "NOVA"

    if language not in _LANGUAGES:
        language = "en-US"

    logger.info(
        "session avatar: face_id=%s voice=%s trial_seconds=%s language=%s anchor_name=%s",
        face_id, voice, trial_seconds, language, anchor_name,
    )

    session = AgentSession(
        stt=openai.STT(base_url=STT_BASE_URL, model=STT_MODEL, api_key=STT_API_KEY),
        llm=openai.LLM(
            base_url=LLM_BASE_URL,
            model=LLM_MODEL,
            api_key=LLM_API_KEY,
            **LLM_OPTS,
        ),
        tts=openai.TTS(base_url=TTS_BASE_URL, model="tts-1", voice=voice, api_key=TTS_API_KEY),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        turn_handling={
            "interruption": {
                "enabled": True,
                "min_duration": 0.35,
                "min_words": 0,
                "resume_false_interruption": True,
                "false_interruption_timeout": 1.5,
            },
            "endpointing": {
                "min_delay": 0.35,
                "max_delay": 2.5,
            },
            "preemptive_generation": {
                "enabled": True,
                "preemptive_tts": True,
            },
        },
    )

    if SIMLI_API_KEY and face_id:
        try:
            simli_avatar = simli.AvatarSession(
                simli_config=simli.SimliConfig(
                    api_key=SIMLI_API_KEY,
                    face_id=face_id,
                ),
            )
            await simli_avatar.start(
                session,
                room=ctx.room,
                livekit_url=SIMLI_LIVEKIT_URL,
                livekit_api_key=LIVEKIT_API_KEY,
                livekit_api_secret=LIVEKIT_API_SECRET,
            )
            logger.info("Simli avatar started: face_id=%s", face_id)
        except Exception:
            logger.exception("Simli avatar failed to start — continuing as audio-only")
    else:
        logger.warning("SIMLI_API_KEY or face_id not set — avatar disabled")

    agent = Assistant(session_type=session_type, room=ctx.room, anchor_name=anchor_name, language=language)

    # When LLM/STT/TTS blow up mid-session (e.g. Groq 429), speak a calm
    # greeting-style apology via TTS instead of going silent. Debounced so
    # retry storms don't spam the viewer.
    _last_error_say_at = 0.0

    def _on_session_error(ev) -> None:
        nonlocal _last_error_say_at
        try:
            err = getattr(ev, "error", None)
            err_type = type(err).__name__ if err is not None else "unknown"
            # Prefer LLM failures — those are what leave the agent mute.
            source = getattr(ev, "source", None)
            source_name = type(source).__name__ if source is not None else ""
            if "TTS" in err_type or "TTS" in source_name:
                return  # can't speak if TTS itself is down
            now = time.monotonic()
            if now - _last_error_say_at < 45.0:
                return
            _last_error_say_at = now
            logger.warning("session error (%s / %s) — scheduling error handler", err_type, source_name)
            asyncio.create_task(
                _handle_agent_error(
                    session,
                    ctx.room,
                    err or err_type,
                    reason=f"session_error:{err_type}",
                    anchor_name=anchor_name,
                    source=source_name,
                )
            )
        except Exception:
            logger.exception("session error handler failed")

    session.on("error", _on_session_error)

    # ── Transcript relay for custom mobile clients ────────────────────────────
    # LiveKit lk.transcription sends CUMULATIVE partial text per stream id —
    # clients must REPLACE by itemId/streamId, NOT append. We only mirror
    # FINAL lines on the data channel to avoid duplicate walls of text.
    _TRANSCRIPT_TOPIC = "genzcine_transcript"
    _published_transcript_ids: set[str] = set()
    _agent_turn_index = 0

    async def _publish_transcript(
        *,
        role: str,
        text: str,
        is_final: bool = True,
        item_id: str = "",
        turn_index: int | None = None,
    ) -> None:
        clean = text.strip()
        if not clean:
            return
        # Skip partial STT — only finals. Partials caused append bugs on mobile UIs.
        if not is_final:
            return
        dedupe_key = item_id or f"{role}:{turn_index}:{clean[:80]}"
        if dedupe_key in _published_transcript_ids:
            return
        _published_transcript_ids.add(dedupe_key)
        try:
            event = {
                "type": "transcript",
                "role": role,
                "text": clean,
                "isFinal": True,
                "itemId": item_id or dedupe_key,
                "turnIndex": turn_index,
                # Clients: REPLACE caption for this itemId; never append partials.
                "updateMode": "replace",
                "timestamp": time.time(),
            }
            await ctx.room.local_participant.publish_data(
                json.dumps(event).encode(), reliable=True, topic=_TRANSCRIPT_TOPIC
            )
            await publish_studio_event(ctx.room, event)
        except Exception:
            logger.exception("transcript publish failed")

    def _on_user_input_transcribed(ev) -> None:
        try:
            if not ev.is_final:
                return
            asyncio.create_task(
                _publish_transcript(
                    role="user",
                    text=ev.transcript,
                    is_final=True,
                    item_id=ev.item_id or "",
                )
            )
        except Exception:
            logger.exception("_on_user_input_transcribed error")

    def _on_conversation_item_added(ev) -> None:
        nonlocal _agent_turn_index
        try:
            if _skip_agent_transcript.get(ctx.room.name):
                return  # error apology — UI uses agent_error event, not chat bubble
            item = ev.item
            role = getattr(item, "role", None)
            if role != "assistant":
                return
            text = getattr(item, "raw_text_content", None) or ""
            item_id = getattr(item, "id", "") or ""
            _agent_turn_index += 1
            asyncio.create_task(
                _publish_transcript(
                    role="agent",
                    text=text,
                    is_final=True,
                    item_id=item_id,
                    turn_index=_agent_turn_index,
                )
            )
        except Exception:
            logger.exception("_on_conversation_item_added error")

    session.on("user_input_transcribed", _on_user_input_transcribed)
    session.on("conversation_item_added", _on_conversation_item_added)

    await session.start(
        agent=agent,
        room=ctx.room,
        room_options=room_io.RoomOptions(
            # False = emit full agent lines once (fewer partial chunks on lk.transcription).
            # Mobile clients that append instead of replace by streamId break with partials.
            text_output=room_io.TextOutputOptions(sync_transcription=False),
        ),
    )

    await publish_studio_event(
        ctx.room,
        {
            "type": "agent_ready",
            "mode": "live",
            "anchorName": anchor_name,
            "language": language,
            "sessionType": session_type,
            "title": "You're live with " + anchor_name,
            "message": "Your AI news anchor is ready. Say hello or wait for today's headlines.",
        },
    )

    await publish_studio_event(
        ctx.room,
        {
            "type": "studio_state",
            "mode": "live",
            "anchorName": anchor_name,
            "language": language,
            "sessionType": session_type,
        },
    )

    # ── Continuous broadcast auto-continue ────────────────────────────────────
    # When the anchor finishes a headline, immediately queue the next one unless
    # the viewer is speaking or a video clip is playing.
    _broadcast_active = True
    _user_state = "listening"
    _continue_task: asyncio.Task | None = None
    _continue_failures = 0

    async def _schedule_broadcast_continue(
        *, delay: float = HEADLINE_CONTINUE_SECONDS
    ) -> None:
        nonlocal _continue_task, _continue_failures, _broadcast_active
        if _continue_task and not _continue_task.done():
            _continue_task.cancel()

        async def _go() -> None:
            nonlocal _continue_failures, _broadcast_active
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                return
            if (
                not _broadcast_active
                or agent._video_playing
                or not ctx.room.isconnected()
                or _user_state == "speaking"
            ):
                return
            ok = await agent._deliver_headline_via_tts(is_first=False)
            if ok:
                _continue_failures = 0
            else:
                _continue_failures += 1
                if _continue_failures >= 3:
                    _broadcast_active = False
                    logger.warning("broadcast auto-continue disabled after repeated failures")
                    try:
                        await session.say(
                            "That's the latest for now — ask me about any story anytime.",
                            allow_interruptions=True,
                        )
                    except Exception:
                        pass

        _continue_task = asyncio.create_task(_go())

    def _on_agent_state_changed(ev) -> None:
        try:
            if ev.old_state == "speaking" and ev.new_state in ("listening", "idle"):
                asyncio.create_task(_schedule_broadcast_continue())
        except Exception:
            logger.exception("_on_agent_state_changed error")

    def _on_user_state_changed(ev) -> None:
        nonlocal _user_state
        try:
            _user_state = ev.new_state
            if ev.new_state == "speaking" and _continue_task and not _continue_task.done():
                _continue_task.cancel()
        except Exception:
            logger.exception("_on_user_state_changed error")

    session.on("agent_state_changed", _on_agent_state_changed)
    session.on("user_state_changed", _on_user_state_changed)

    # ── News video data channel ─────────────────────────────────────────────
    _video_reply_at: dict[str, float] = {}  # topic -> last reply time (dedup in group rooms)

    async def _respond_to_video_end(topic: str, skipped: bool) -> None:
        try:
            agent._video_playing = False
            await publish_studio_event(
                ctx.room,
                {
                    "type": "video_end",
                    "topic": topic,
                    "skipped": skipped,
                },
            )
            await publish_studio_event(
                ctx.room,
                {"type": "studio_state", "mode": "live", "anchorName": anchor_name},
            )
            if skipped:
                await session.say(
                    "No problem — let's keep going with the news.",
                    allow_interruptions=True,
                )
            else:
                await session.say(
                    f"That was the clip on {topic}. Next up in today's bulletin.",
                    allow_interruptions=True,
                )
            asyncio.create_task(
                _schedule_broadcast_continue(delay=HEADLINE_CONTINUE_SECONDS)
            )
        except Exception as exc:
            logger.exception("video end reply failed")
            await _handle_agent_error(
                session, ctx.room, exc, reason="video_end_exception", anchor_name=anchor_name
            )

    def on_data_received(data_packet: rtc.DataPacket) -> None:
        try:
            payload = json.loads(data_packet.data.decode())
            msg_type = payload.get("type")
            if msg_type == "news_video_ended":
                topic = str(payload.get("topic", "that story"))
                skipped = bool(payload.get("skipped", False))
                # In group sessions every participant sends this when their
                # player closes — react only once per topic within a window.
                now = time.monotonic()
                if now - _video_reply_at.get(topic, float("-inf")) < 60.0:
                    return
                _video_reply_at[topic] = now
                loop = asyncio.get_event_loop()
                loop.create_task(_respond_to_video_end(topic, skipped))
        except Exception:
            logger.exception("on_data_received error")

    ctx.room.on("data_received", on_data_received)

    # ── Server-side trial enforcer ────────────────────────────────────────────
    # Runs even if the client patches its JS — agent disconnects itself.
    if trial_seconds > 0:
        async def _enforce_trial() -> None:
            warn_at = max(0, trial_seconds - 60)
            if warn_at > 0:
                await asyncio.sleep(warn_at)
                if ctx.room.isconnected():
                    try:
                        await session.say(_TRIAL_WARN_SAY, allow_interruptions=True)
                    except Exception:
                        pass
                await asyncio.sleep(60)
            else:
                await asyncio.sleep(trial_seconds)

            if ctx.room.isconnected():
                try:
                    await session.say(_TRIAL_END_SAY, allow_interruptions=True)
                    await asyncio.sleep(8)
                except Exception:
                    pass

            logger.info("trial enforcer: disconnecting room=%s after %ds", ctx.room.name, trial_seconds)
            try:
                await ctx.room.disconnect()
            except Exception:
                logger.exception("trial enforcer: disconnect failed")

        asyncio.create_task(_enforce_trial())
        logger.info("trial enforcer scheduled: %ds for room=%s", trial_seconds, ctx.room.name)


if __name__ == "__main__":
    cli.run_app(server)

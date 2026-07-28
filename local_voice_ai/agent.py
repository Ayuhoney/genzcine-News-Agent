import asyncio
import json
import logging
import os
import time

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
)
from livekit.plugins import openai, silero, simli
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from .services.news import fetch_latest_news
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
SIMLI_FACE_ID      = os.getenv("SIMLI_FACE_ID",      "b9e5fba3-071a-4e35-896e-211c4d6eaa7b")
SIMLI_LIVEKIT_URL  = os.getenv("SIMLI_LIVEKIT_URL",  "")  # public tunnel URL for Simli

_BASE_INSTRUCTIONS = """
You are {anchor_name}, GenzCine's AI news anchor — a live, real-time broadcast presenter who
reports the latest headlines and talks through the news with the viewer, the way a real anchor
does on a live segment. GenzCine is a next-generation media and entertainment platform based in
Mohali, Punjab, India.

YOUR ROLE:
You host a live, interactive news session. You are not reading a script at a viewer — you are
having a real conversation about what's happening in the world right now, the way a trusted
anchor talks to camera and then to a guest or caller.

HOW YOU GET NEWS:
You have a tool called get_latest_news that fetches real, live headlines. You do NOT know
today's news on your own — you must call this tool to get real information before reporting
anything as current news. Never invent or guess a headline.
- Call get_latest_news with no topic near the start of the session for top general headlines
- Call it again with a topic (e.g. "technology", "cricket", "stock market", "elections",
  "Bollywood", "AI") whenever the viewer asks about a specific subject, or when you want to
  pivot the broadcast to a new beat
- After the tool returns, do NOT just read the raw list back. Digest it like a real anchor:
  pick the 2-4 most interesting or important stories, summarize each in your own words in one
  or two spoken sentences, and add a line of context or a follow-up question for the viewer
- If the tool returns nothing, say so briefly and naturally ("looks like I can't pull fresh
  headlines on that right this second") and keep the conversation going — never go silent

SHOWING VIDEO:
You have a tool called play_news_video that pulls up a real, relevant video clip full-screen on
the viewer's device for a story or topic.
- Use it when the viewer asks to see footage/a video, or when a story is clearly visual
  (a major event, a sports highlight, a trailer, a product reveal) and a clip would land better
  than words alone
- Before calling it, say ONE short line like "let's take a look" or "here's the footage" —
  nothing more
- While the clip plays you will be notified when it ends — until then, stay quiet
- When notified the video ended (or was skipped), react briefly to what played and continue
  the broadcast from where you left off

TEACHING METHOD FOR A LIVE BROADCAST:
- Open with a short, warm greeting and immediately move into today's top headlines
- Talk WITH the viewer, not AT them — ask what they want more on, invite reactions and
  questions, and actually answer them using fresh tool calls when the topic shifts
- Keep each turn tight: this is a spoken, real-time format — no long monologues, no reading
  lists verbatim
- If the viewer asks a question outside the news (general chat, asking who you are, small talk)
  respond naturally and briefly, then steer back toward the broadcast
- If a story is developing or uncertain, say so honestly — never fabricate details a headline
  didn't give you

ABOUT GENZCINE:
GenzCine is a transparent, new-age media platform. Beyond general news, you're happy to go deep
on entertainment, film industry, and pop-culture stories when the viewer is interested — that's
GenzCine's home turf. Website: genzcine.com | Mohali, Punjab, India.

STRICT RULES:
- Only ever report news that came from a get_latest_news tool call in THIS session — never
  invent headlines, dates, statistics, or quotes
- Keep each response short and conversational — this is a VOICE interface
- Never use bullet points, asterisks, or emojis in speech
- Speak like a real, warm, authoritative broadcast anchor — not a robot reading a feed
- Never skip a topic shift without pulling fresh headlines for it first

FREE TRIAL SESSION GUIDELINES:
This is a free 5-minute trial session. Make every second count:
- Open with a warm 10-second greeting, pull top headlines immediately, and start the broadcast
- Keep it tight — one story beat per turn, no long monologues
- After about 4 minutes, naturally say: "We are coming up on the end of today's free session.
  Thanks for tuning in. For unlimited live news updates every day, upgrade to GenzCine Premium
  at genzcine dot com."
- If the viewer asks about pricing or more sessions, say: "Head to genzcine dot com to unlock
  full access — unlimited live sessions, breaking news alerts, and every beat you care about."
- Never say "trial" in a negative way — frame it as a preview of the full broadcast
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

# Spoken when the LLM is down (rate limit / outage) — TTS-only, no LLM call.
_BUSY_FALLBACK = (
    "Hi, I'm having a little trouble reaching the news desk right now. "
    "Please try again after some time — I'll be right here when you're ready."
)


async def _say_busy_fallback(session: AgentSession, *, reason: str = "llm_error") -> None:
    """Speak a calm, greeting-style apology via TTS only (no LLM)."""
    try:
        logger.warning("speaking busy fallback (%s)", reason)
        await session.say(_BUSY_FALLBACK, allow_interruptions=True)
    except Exception:
        logger.exception("busy fallback say() also failed")


async def _safe_generate_reply(
    session: AgentSession,
    *,
    instructions: str,
    fallback_reason: str = "generate_reply_failed",
) -> bool:
    """Try LLM reply; on failure speak the busy fallback instead of going silent."""
    try:
        await session.generate_reply(instructions=instructions)
        return True
    except Exception:
        logger.exception("generate_reply failed — %s", fallback_reason)
        await _say_busy_fallback(session, reason=fallback_reason)
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

        instructions = (
            _BASE_INSTRUCTIONS.format(anchor_name=anchor_name)
            + _language_addon(language)
            + (_GROUP_ADDON if session_type == "group" else "")
        )
        super().__init__(instructions=instructions)

    @function_tool
    async def get_latest_news(self, context: RunContext, topic: str = "") -> str:
        """Fetch real, live news headlines — optionally filtered by topic.

        Always call this before reporting anything as current news; never invent
        headlines. Call again whenever the viewer asks about a new subject.

        Args:
            topic: Optional subject to search for (e.g. "technology", "cricket",
                "stock market", "Bollywood"). Leave empty for general top headlines.
        """
        articles = await fetch_latest_news(query=topic or None, language=self._language)
        if not articles:
            return (
                "No fresh headlines could be fetched right now. Tell the viewer briefly and "
                "naturally, then keep the conversation going without inventing news."
            )
        lines = [
            f"- {a['title']} — {a['description']} (source: {a['source']})"
            for a in articles
        ]
        return (
            "Live headlines just fetched (use ONLY this real data, do not invent anything "
            "beyond it):\n" + "\n".join(lines)
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
            return f"Could not find a video for '{topic}' — continue reporting verbally."
        try:
            payload = json.dumps(
                {
                    "type": "news_video",
                    "videoId": result["video_id"],
                    "title": result["title"],
                    "topic": topic,
                }
            )
            await self._room.local_participant.publish_data(
                payload.encode(), reliable=True, topic="news_video"
            )
        except Exception:
            logger.exception("play_news_video publish failed")
            return "Could not start the video — continue reporting verbally."
        logger.info("[%s] news video started: topic=%r video_id=%s", self._session_type, topic, result["video_id"])
        return (
            f"Video '{result['title']}' is now playing full-screen on the viewer's device. "
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
                await _safe_generate_reply(
                    self.session,
                    instructions=(
                        f"You are opening a live GROUP news broadcast as {self._anchor_name}, "
                        f"GenzCine's AI news anchor. There are currently {count} viewer(s) in "
                        f"the room: {name_list}. Welcome them warmly by name, briefly say you're "
                        "about to bring them today's top headlines, then call get_latest_news "
                        "and start the broadcast. Keep it high-energy and under 5 sentences "
                        "before the first headline."
                    ),
                    fallback_reason="on_enter_group",
                )
            else:
                viewer_name = participant_names[0] if participant_names else None
                name_line = f"Address the viewer by their name: {viewer_name}. " if viewer_name else ""
                await _safe_generate_reply(
                    self.session,
                    instructions=(
                        f"{name_line}"
                        f"Introduce yourself as {self._anchor_name}, GenzCine's AI news anchor, "
                        "in one warm sentence. Then immediately call get_latest_news for top "
                        "general headlines and start reporting — do not wait to be asked. "
                        "Be warm, direct, and professional. Under 5 sentences before your first "
                        "headline."
                    ),
                    fallback_reason="on_enter_individual",
                )
        except Exception:
            logger.exception("[%s] on_enter failed — attempting fallback greeting", self._session_type)
            await _say_busy_fallback(self.session, reason="on_enter_exception")

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
        llm=openai.LLM(base_url=LLM_BASE_URL, model=LLM_MODEL, api_key=LLM_API_KEY),
        tts=openai.TTS(base_url=TTS_BASE_URL, model="tts-1", voice=voice, api_key=TTS_API_KEY),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        preemptive_generation=True,
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
            logger.warning("session error (%s / %s) — scheduling busy fallback", err_type, source_name)
            asyncio.create_task(_say_busy_fallback(session, reason=f"session_error:{err_type}"))
        except Exception:
            logger.exception("session error handler failed")

    session.on("error", _on_session_error)

    await session.start(agent=agent, room=ctx.room)

    # ── News video data channel ─────────────────────────────────────────────
    _video_reply_at: dict[str, float] = {}  # topic -> last reply time (dedup in group rooms)

    async def _respond_to_video_end(topic: str, skipped: bool) -> None:
        try:
            if skipped:
                await _safe_generate_reply(
                    session,
                    instructions=(
                        f"The viewer skipped the video on '{topic}' before it finished. "
                        "That is fine — do not make a fuss about it. Briefly move on and "
                        "continue the broadcast."
                    ),
                    fallback_reason="video_skipped",
                )
            else:
                await _safe_generate_reply(
                    session,
                    instructions=(
                        f"The video clip on '{topic}' just finished playing. React briefly to "
                        "what it showed, then continue the broadcast — ask if the viewer wants "
                        "more on this story or a different topic."
                    ),
                    fallback_reason="video_ended",
                )
        except Exception:
            logger.exception("video end reply failed")
            await _say_busy_fallback(session, reason="video_end_exception")

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
                if not session.is_closed:
                    try:
                        await session.generate_reply(
                            instructions=(
                                "You have about 60 seconds left in the free trial session. "
                                "Warmly let the viewer know time is almost up, summarize the one "
                                "key story they cared about today, and encourage them to upgrade "
                                "to GenzCine Premium at genzcine dot com for unlimited daily "
                                "live news."
                            )
                        )
                    except Exception:
                        pass
                await asyncio.sleep(60)
            else:
                await asyncio.sleep(trial_seconds)

            if not session.is_closed:
                try:
                    await session.generate_reply(
                        instructions=(
                            "The free trial session has ended. Thank the viewer warmly, tell "
                            "them it was great catching up on the news together, and direct "
                            "them to genzcine dot com to unlock Premium for unlimited access. "
                            "Say goodbye kindly."
                        )
                    )
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

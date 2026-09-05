import asyncio
import json
import logging
import os
import re
import time
from difflib import SequenceMatcher
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
from livekit.agents.tts import StreamAdapter
from livekit.plugins import openai, silero, simli
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from .services.agent_errors import classify_agent_error
from .services.india_places import all_place_names, canonical_place, extract_place, news_query_for
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
STT_MODEL    = os.getenv("STT_MODEL",    "whisper-large-v3")
STT_API_KEY  = os.getenv("STT_API_KEY",  "")
# Whisper maps Indian city names to English lookalikes ("Firozpur" → "Frostburt").
_STT_PROMPT = (
    "Indian news place names: Delhi, Mumbai, Kolkata, Chennai, Bengaluru, "
    "Hyderabad, Pune, Ahmedabad, Jaipur, Lucknow, Patna, Bhopal, Chandigarh, "
    "Punjab, Kerala, Tamil Nadu, Firozpur, Mohali."
)
_PLACE_ALIASES = {
    "firozpur": "Firozpur",
    "ferozepur": "Firozpur",
    "ferozpur": "Firozpur",
    "firazpur": "Firozpur",
    "firospur": "Firozpur",
    "frostburt": "Firozpur",
    "frostburg": "Firozpur",
    "frostburn": "Firozpur",
    "rospor": "Firozpur",
    "rose pour": "Firozpur",
    "rosepor": "Firozpur",
    "rose pur": "Firozpur",
    "it all spur": "Firozpur",
    "all spur": "Firozpur",
    "philosphy": "Firozpur",
    "bangalore": "Bengaluru",
    "gurgaon": "Gurugram",
    "chaldea girl": "Chandigarh",
    "chaldea": "Chandigarh",
    "chandi garh": "Chandigarh",
    "chander garh": "Chandigarh",
    "chandigrah": "Chandigarh",
    "calcutta": "Kolkata",
    "madras": "Chennai",
    "trivandrum": "Thiruvananthapuram",
    "orissa": "Odisha",
    "pondicherry": "Puducherry",
    "allahabad": "Prayagraj",
    "bombay": "Mumbai",
}
_KNOWN_PLACES = all_place_names() + (
    "Bangalore", "Gurgaon", "Calcutta", "Madras", "Trivandrum", "Orissa",
)


def _norm_place(text: str) -> str:
    return re.sub(r"[^a-z]", "", (text or "").lower())


def _correct_place_transcript(text: str) -> str:
    """Map common Whisper mishears of Indian cities back to the real name."""
    raw = (text or "").strip()
    if not raw:
        return raw
    known = canonical_place(raw)
    if known is not None:
        return known
    extracted = extract_place(raw)
    if extracted:
        return extracted
    key = " ".join(raw.lower().split())
    if key in _PLACE_ALIASES:
        return _PLACE_ALIASES[key]
    for alias, canon in sorted(_PLACE_ALIASES.items(), key=lambda item: -len(item[0])):
        if alias in key:
            return re.sub(re.escape(alias), canon, raw, count=1, flags=re.I)
    words = raw.split()
    compact = _norm_place(raw)
    if len(words) <= 5 and len(compact) >= 5:
        ranked: list[tuple[float, str]] = []
        for place in _KNOWN_PLACES:
            pname = _norm_place(place)
            if abs(len(pname) - len(compact)) > 3:
                continue
            ranked.append((SequenceMatcher(None, compact, pname).ratio(), place))
        ranked.sort(reverse=True)
        if (
            ranked
            and ranked[0][0] >= 0.74
            and (len(ranked) == 1 or ranked[0][0] - ranked[1][0] >= 0.06)
        ):
            return ranked[0][1]
    return raw

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


def _stt_language(language: str) -> str:
    """Groq Whisper wants a short ISO code (en, hi), not a locale (en-US)."""
    return (language or "en").split("-", 1)[0].lower() or "en"


def _llm_client_options() -> dict:
    """Voice-tuned Groq/OpenAI client: short replies, no thinking, sane timeouts."""
    local = _is_local_service_url(LLM_BASE_URL)
    read_s = float(os.getenv("LLM_READ_TIMEOUT", "120" if local else "30"))
    opts: dict = {
        "max_completion_tokens": int(os.getenv("LLM_MAX_COMPLETION_TOKENS", "120")),
        # qwen/qwen3.8-27b defaults to thinking mode on Groq — that burns the
        # token budget before any spoken words. Instruct mode is required.
        "reasoning_effort": os.getenv("LLM_REASONING_EFFORT", "none"),
        "temperature": float(os.getenv("LLM_TEMPERATURE", "0.7")),
        "timeout": httpx.Timeout(connect=5.0, read=read_s, write=8.0, pool=5.0),
    }
    if "groq.com" in (LLM_BASE_URL or ""):
        opts["extra_body"] = {"reasoning_format": "hidden"}
    return opts


def _build_tts(voice: str) -> StreamAdapter:
    """Rampwalk-style StreamAdapter (sentence-level) + Kokoro PCM HTTP streaming.

    Kokoro yields audio per clause. The server streams raw s16le as each clause
    finishes; livekit openai.TTS already consumes the body with
    with_streaming_response, so playback starts before the full line is done.
    StreamAdapter then parallelizes the next LLM sentence on the second worker.
    """
    from openai import AsyncClient

    client = AsyncClient(
        api_key=TTS_API_KEY or "no-key-needed",
        base_url=TTS_BASE_URL,
        max_retries=0,
        http_client=httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0),
            follow_redirects=True,
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
                keepalive_expiry=120,
            ),
        ),
    )
    raw_tts = openai.TTS(
        base_url=TTS_BASE_URL,
        model="tts-1",
        voice=voice,
        api_key=TTS_API_KEY,
        response_format="pcm",
        client=client,
    )
    return StreamAdapter(tts=raw_tts)


async def _warm_headline_cache(agent: "Assistant", query: str | None = None) -> None:
    """Fetch in the background so the LLM tool call hits cache (saves one RTT)."""
    try:
        await fetch_latest_news(
            query=query,
            language=agent._language,
            limit=NEWS_HEADLINE_LIMIT,
        )
    except Exception:
        logger.exception("headline cache warm failed")


NEWS_HEADLINE_LIMIT = int(os.getenv("NEWS_HEADLINE_LIMIT", "8"))
# 0 = next headline starts as soon as the anchor finishes the previous one.
HEADLINE_CONTINUE_SECONDS = float(os.getenv("HEADLINE_CONTINUE_SECONDS", "0"))
# After the viewer stops speaking, wait this long for the agent to respond before
# resuming the bulletin when no reply was generated (STT miss / LLM stall).
BULLETIN_RESUME_AFTER_USER_SECONDS = float(os.getenv("BULLETIN_RESUME_AFTER_USER_SECONDS", "10"))
# After the agent finishes a reply, keep the bulletin paused this long so the viewer
# can ask follow-ups. Timer resets on each new final STT line.
CONVERSATION_IDLE_SECONDS = float(os.getenv("CONVERSATION_IDLE_SECONDS", "12"))
REPLY_NUDGE_RETRIES = max(1, int(os.getenv("REPLY_NUDGE_RETRIES", "3")))
REPLY_NUDGE_DELAY_SECONDS = float(os.getenv("REPLY_NUDGE_DELAY_SECONDS", "1.2"))
REPLY_NUDGE_RETRY_GAP_SECONDS = float(os.getenv("REPLY_NUDGE_RETRY_GAP_SECONDS", "1.0"))
_HEADLINE_BRIDGES = (
    "Next up in today's news.",
    "Also making headlines.",
    "In other news.",
    "Moving on.",
)
_CONVERSATION_RESUME_LINES = (
    "Alright, back to today's headlines.",
    "Let's pick up the bulletin where we left off.",
    "Great question — here's more from today's news.",
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

SESSION START:
- You have already asked the viewer which city or region they want news for.
- As soon as they answer with any Indian city or state (e.g. "Jaipur", "Kerala", "Firozpur") or "national", call get_latest_news with that location as the topic, then immediately start the bulletin — no further questions.
- If they say something vague like "anything" or "you decide", call get_latest_news with topic="" for national headlines and start the bulletin.

ON-AIR STYLE:
- You are live in a news studio. After the location is set, keep the bulletin going — do not wait for the viewer.
- Headlines play automatically one after another. When the viewer speaks, answer in 1-2 short spoken sentences.
- After answering, stay ready for follow-ups — the viewer may ask another question before headlines resume.
- End replies naturally when helpful, e.g. "Want to know more?" or "Anything else on that story?"
- Never narrate your plan, list options, or give a long recap. Spoken news-anchor lines only.
- Use get_latest_news only if they ask about a topic you have not covered yet.
- Headlines are a mix: GenzCine published, local city news, and global/national wire. Cover all three; do not stay on one type.
- When a source is Dainik Bhaskar, Punjab Kesari, Amar Ujala, Dainik Jagran, The Hindu, Times of India, or Hindustan Times, name that paper once. If the title is in Hindi (or another Indian language) and you are speaking English, translate briefly — do not invent facts.
- If a headline is tagged [GenzCine community], introduce it as news published by a GenzCine reporter or viewer. Do not invent extra facts beyond the title.
- If a headline is tagged [GenzCine local], treat it as local news from the GenzCine app for the viewer's city.
- If the viewer interrupts during a headline, stop and respond — headlines resume only after they go quiet.
- Voice only — no bullets, emojis, or lists read verbatim.

TRIAL (10 min): open strong with headlines; near 9 min mention genzcine dot com for unlimited access.
IMPORTANT: Respond immediately and naturally — do NOT add <think> blocks, reasoning steps, or internal monologue. Spoken output only.
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
    if article.get("provider") == "community":
        title = f"From a GenzCine reporter: {title}"
    elif article.get("provider") == "genzcine":
        title = f"From GenzCine local: {title}"
    if is_first:
        who = f" {viewer_name}" if viewer_name else ""
        greet = f"Hey{who}! I'm {anchor_name}, your GenzCine news anchor. This is today's news."
        body = f" {title}. {desc}" if desc else f" {title}."
        return f"{greet}{body}".strip()
    bridge = _HEADLINE_BRIDGES[index % len(_HEADLINE_BRIDGES)]
    body = f" {title}. {desc}" if desc else f" {title}."
    return f"{bridge}{body}".strip()


async def _refresh_headlines(agent: "Assistant", *, topic: str = "") -> bool:
    query = news_query_for(topic or agent._preferred_location or None)
    articles = await fetch_latest_news(
        query=query,
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
        self._preferred_location: str = ""  # set by user at session start

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
        if topic:
            self._preferred_location = (
                news_query_for(_correct_place_transcript(topic.strip())) or ""
            )
        articles = await fetch_latest_news(
            query=self._preferred_location or None, language=self._language, limit=NEWS_HEADLINE_LIMIT
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
        lines = []
        for a in articles:
            if a.get("provider") == "community":
                tag = " [GenzCine community]"
            elif a.get("provider") == "genzcine":
                tag = " [GenzCine local]"
            else:
                tag = ""
            lines.append(f"- {a['title']} ({a['source']}){tag}")
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

        async def _video_watchdog() -> None:
            try:
                await asyncio.sleep(180)
            except asyncio.CancelledError:
                return
            if self._video_playing:
                logger.warning("video watchdog — clearing stuck video_playing after 180s")
                self._video_playing = False

        asyncio.create_task(_video_watchdog())
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
            asyncio.create_task(_warm_headline_cache(self))

            if self._session_type == "group":
                name_list = ", ".join(participant_names) if participant_names else "everyone"
                await self.session.say(
                    f"Hey {name_list}! I'm {self._anchor_name}. "
                    "Which Indian city or state do you want — or say national?",
                    allow_interruptions=True,
                )
            else:
                viewer_name = participant_names[0] if participant_names else None
                who = f" {viewer_name}" if viewer_name else ""
                await self.session.say(
                    f"Hey{who}! I'm {self._anchor_name}. "
                    "Which Indian city or state do you want — or say national?",
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

    # Simli routes TTS through DataStreamIO — audio pause/resume is not supported.
    _use_simli = bool(SIMLI_API_KEY and face_id)

    streamed_tts = _build_tts(voice)

    session = AgentSession(
        stt=openai.STT(
            base_url=STT_BASE_URL,
            model=STT_MODEL,
            api_key=STT_API_KEY,
            language=_stt_language(language),
            prompt=_STT_PROMPT,
        ),
        llm=openai.LLM(
            base_url=LLM_BASE_URL,
            model=LLM_MODEL,
            api_key=LLM_API_KEY,
            **LLM_OPTS,
        ),
        tts=streamed_tts,
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        turn_handling={
            "interruption": {
                "enabled": True,
                "min_duration": 0.25,
                "min_words": 0,
                # Simli avatar cannot pause mid-utterance; rely on session.interrupt().
                "resume_false_interruption": not _use_simli,
                "false_interruption_timeout": 1.0,
            },
            "endpointing": {
                "min_delay": 0.20,
                "max_delay": 1.2,
            },
            "preemptive_generation": {
                "enabled": True,
                "preemptive_tts": not _use_simli,
            },
        },
    )

    if _use_simli:
        simli_avatar = None
        simli_restart_attempts = 0
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

            @ctx.room.on("participant_disconnected")
            def _on_avatar_participant_left(participant: rtc.RemoteParticipant) -> None:
                nonlocal simli_restart_attempts
                identity = (participant.identity or "").lower()
                if participant.identity == ctx.room.local_participant.identity:
                    return
                if "simli" not in identity and "avatar" not in identity:
                    return
                logger.warning(
                    "Simli avatar participant disconnected: %s — attempting recovery",
                    participant.identity,
                )
                if simli_avatar is None or simli_restart_attempts >= 1:
                    return
                simli_restart_attempts += 1

                async def _restart_simli() -> None:
                    try:
                        await simli_avatar.start(
                            session,
                            room=ctx.room,
                            livekit_url=SIMLI_LIVEKIT_URL,
                            livekit_api_key=LIVEKIT_API_KEY,
                            livekit_api_secret=LIVEKIT_API_SECRET,
                        )
                        logger.info("Simli avatar restarted after disconnect")
                    except Exception:
                        logger.exception(
                            "Simli avatar restart failed — session continues (audio may be affected)"
                        )

                asyncio.create_task(_restart_simli())

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
    # Shared broadcast + user-turn state (handlers below mutate this dict).
    _bc: dict[str, Any] = {
        "active": True,
        "paused": False,
        "conversation_mode": False,
        "user_state": "listening",
        "user_turn_active": False,
        "agent_responding_to_user": False,
        "continue_task": None,
        "resume_task": None,
        "reply_nudge_task": None,
        "conversation_idle_task": None,
        "failures": 0,
        "resume_line_index": 0,
    }

    async def _publish_mode(mode: str) -> None:
        await publish_studio_event(
            ctx.room,
            {
                "type": "studio_state",
                "mode": mode,
                "anchorName": anchor_name,
                "language": language,
                "sessionType": session_type,
            },
        )

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

    def _cancel_conversation_idle() -> None:
        task = _bc.get("conversation_idle_task")
        if task and not task.done():
            task.cancel()

    def _mark_conversation_mode() -> None:
        _bc["conversation_mode"] = True
        _bc["paused"] = True

    async def _enter_conversation_mode() -> None:
        _mark_conversation_mode()
        await _publish_mode("conversation")

    async def _exit_conversation_and_resume_bulletin() -> None:
        if not _bc["conversation_mode"]:
            return
        _cancel_conversation_idle()
        _cancel_resume_task()
        _bc["conversation_mode"] = False
        _bc["user_turn_active"] = False
        _bc["agent_responding_to_user"] = False
        _bc["paused"] = False
        idx = int(_bc.get("resume_line_index", 0))
        _bc["resume_line_index"] = idx + 1
        bridge = _CONVERSATION_RESUME_LINES[idx % len(_CONVERSATION_RESUME_LINES)]
        logger.info("conversation idle — resuming bulletin with bridge")
        await _publish_mode("live")
        try:
            await session.say(bridge, allow_interruptions=True)
        except Exception:
            logger.exception("conversation resume bridge failed")
        await _continue_bulletin()

    def _schedule_conversation_idle() -> None:
        _cancel_conversation_idle()

        async def _wait() -> None:
            try:
                await asyncio.sleep(CONVERSATION_IDLE_SECONDS)
            except asyncio.CancelledError:
                return
            if (
                not _bc["conversation_mode"]
                or _bc["user_state"] == "speaking"
                or session.agent_state in ("speaking", "thinking")
                or _bc["agent_responding_to_user"]
                or agent._video_playing
                or not ctx.room.isconnected()
            ):
                return
            await _exit_conversation_and_resume_bulletin()

        _bc["conversation_idle_task"] = asyncio.create_task(_wait())

    async def _nudge_user_reply(transcript: str) -> None:
        """If LiveKit didn't start a reply after STT, trigger one explicitly (with retries)."""
        clean = transcript.strip()
        if not clean:
            return
        for attempt in range(REPLY_NUDGE_RETRIES):
            delay = REPLY_NUDGE_DELAY_SECONDS if attempt == 0 else REPLY_NUDGE_RETRY_GAP_SECONDS
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                return
            if (
                not _bc["paused"]
                or not _bc["user_turn_active"]
                or _bc["agent_responding_to_user"]
                or _bc["user_state"] == "speaking"
                or session.agent_state in ("speaking", "thinking")
            ):
                return
            logger.info(
                "mic picked up — nudging agent reply (%d/%d): %r",
                attempt + 1,
                REPLY_NUDGE_RETRIES,
                clean[:120],
            )
            try:
                await session.generate_reply(user_input=clean, allow_interruptions=True)
                _bc["agent_responding_to_user"] = True
                return
            except Exception:
                logger.exception("generate_reply nudge attempt %d failed", attempt + 1)
        logger.warning("all reply nudges exhausted — no agent response for: %r", clean[:120])

    def _cancel_reply_nudge() -> None:
        task = _bc.get("reply_nudge_task")
        if task and not task.done():
            task.cancel()

    def _on_user_input_transcribed(ev) -> None:
        try:
            if not ev.is_final:
                return
            text = _correct_place_transcript((ev.transcript or "").strip())
            if text and text != (ev.transcript or "").strip():
                logger.info("STT place correction: %r → %r", (ev.transcript or "")[:80], text)
            if text:
                logger.info("mic STT final: %r", text[:120])
                _bc["user_turn_active"] = True
                _bc["paused"] = True
                _cancel_conversation_idle()
                asyncio.create_task(
                    _warm_headline_cache(agent, text if not agent._preferred_location else None)
                )
                if not _bc["conversation_mode"]:
                    asyncio.create_task(_enter_conversation_mode())
            asyncio.create_task(
                _publish_transcript(
                    role="user",
                    text=text or ev.transcript,
                    is_final=True,
                    item_id=ev.item_id or "",
                )
            )
            if text:
                _cancel_reply_nudge()
                _bc["reply_nudge_task"] = asyncio.create_task(_nudge_user_reply(text))
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
    # Headlines run back-to-back. When the viewer speaks, pause the bulletin,
    # let STT + LLM answer, then resume headlines once the reply finishes.
    async def _continue_bulletin(*, delay: float = HEADLINE_CONTINUE_SECONDS) -> None:
        task = _bc.get("continue_task")
        if task and not task.done():
            task.cancel()

        async def _go() -> None:
            try:
                if delay > 0:
                    await asyncio.sleep(delay)
            except asyncio.CancelledError:
                return
            if (
                not _bc["active"]
                or _bc["paused"]
                or _bc["conversation_mode"]
                or _bc["user_turn_active"]
                or agent._video_playing
                or not ctx.room.isconnected()
                or _bc["user_state"] == "speaking"
                or session.agent_state in ("speaking", "thinking")
            ):
                return
            ok = await agent._deliver_headline_via_tts(is_first=False)
            if ok:
                _bc["failures"] = 0
            else:
                _bc["failures"] = int(_bc["failures"]) + 1
                if _bc["failures"] >= 3:
                    _bc["active"] = False
                    logger.warning("broadcast auto-continue disabled after repeated failures")
                    try:
                        await session.say(
                            "That's the latest for now — ask me about any story anytime.",
                            allow_interruptions=True,
                        )
                    except Exception:
                        pass

        _bc["continue_task"] = asyncio.create_task(_go())

    async def _resume_bulletin_after_user_turn() -> None:
        try:
            await asyncio.sleep(BULLETIN_RESUME_AFTER_USER_SECONDS)
        except asyncio.CancelledError:
            return
        if (
            not _bc["paused"]
            or _bc["conversation_mode"]
            or _bc["agent_responding_to_user"]
            or _bc["user_state"] == "speaking"
            or session.agent_state in ("speaking", "thinking")
            or agent._video_playing
        ):
            return
        logger.info("user quiet — resuming bulletin after no agent reply")
        _bc["user_turn_active"] = False
        _bc["paused"] = False
        await _publish_mode("live")
        await _continue_bulletin()

    def _cancel_resume_task() -> None:
        task = _bc.get("resume_task")
        if task and not task.done():
            task.cancel()

    def _on_agent_state_changed(ev) -> None:
        try:
            if ev.new_state in ("thinking", "speaking") and _bc["paused"]:
                _cancel_resume_task()
                _cancel_reply_nudge()
                _cancel_conversation_idle()
                if _bc["user_turn_active"]:
                    _bc["agent_responding_to_user"] = True
                    if ev.new_state == "speaking":
                        logger.info("agent responding to viewer")
                    else:
                        logger.info("agent thinking — holding bulletin and nudge")
            elif ev.old_state == "speaking" and ev.new_state in ("listening", "idle"):
                if _bc["user_turn_active"]:
                    if _bc["agent_responding_to_user"]:
                        logger.info(
                            "agent reply done — conversation window open (%ss)",
                            CONVERSATION_IDLE_SECONDS,
                        )
                        _bc["agent_responding_to_user"] = False
                        _mark_conversation_mode()
                        asyncio.create_task(_publish_mode("conversation"))
                        _schedule_conversation_idle()
                    # Headline was interrupted — wait for STT/reply, do not resume yet.
                elif not _bc["paused"]:
                    asyncio.create_task(_continue_bulletin())
        except Exception:
            logger.exception("_on_agent_state_changed error")

    def _on_user_state_changed(ev) -> None:
        try:
            _bc["user_state"] = ev.new_state
            if ev.new_state == "speaking":
                logger.info("viewer speaking — pausing bulletin")
                _bc["user_turn_active"] = True
                _bc["paused"] = True
                _cancel_resume_task()
                _cancel_reply_nudge()
                _cancel_conversation_idle()
                if not _bc["conversation_mode"]:
                    asyncio.create_task(_enter_conversation_mode())
                task = _bc.get("continue_task")
                if task and not task.done():
                    task.cancel()
                try:
                    session.interrupt(force=True)
                except Exception:
                    logger.exception("session.interrupt failed while user speaking")
            elif ev.new_state == "listening" and _bc["paused"] and _bc["user_turn_active"]:
                _cancel_resume_task()
                if not _bc["conversation_mode"]:
                    _bc["resume_task"] = asyncio.create_task(_resume_bulletin_after_user_turn())
                elif (
                    not _bc["agent_responding_to_user"]
                    and session.agent_state not in ("speaking", "thinking")
                ):
                    # Follow-up window — restart idle if speech did not trigger a new reply.
                    _schedule_conversation_idle()
        except Exception:
            logger.exception("_on_user_state_changed error")

    def _on_remote_track_published(
        publication: rtc.RemoteTrackPublication, participant: rtc.RemoteParticipant
    ) -> None:
        try:
            if publication.kind == rtc.TrackKind.KIND_AUDIO:
                logger.info(
                    "remote mic track published: participant=%s source=%s muted=%s",
                    participant.identity,
                    publication.source,
                    publication.muted,
                )
        except Exception:
            logger.exception("_on_remote_track_published error")

    ctx.room.on("track_published", _on_remote_track_published)

    session.on("agent_state_changed", _on_agent_state_changed)
    session.on("user_state_changed", _on_user_state_changed)

    # ── News video data channel ─────────────────────────────────────────────
    _video_reply_at: dict[str, float] = {}  # topic -> last reply time (dedup in group rooms)

    async def _respond_to_video_end(topic: str, skipped: bool) -> None:
        try:
            agent._video_playing = False
            _cancel_conversation_idle()
            _bc["conversation_mode"] = False
            _bc["user_turn_active"] = False
            _bc["agent_responding_to_user"] = False
            _bc["paused"] = False
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
            asyncio.create_task(_continue_bulletin())
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
                asyncio.get_running_loop().create_task(_respond_to_video_end(topic, skipped))
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

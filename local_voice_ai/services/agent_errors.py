"""Classify agent/LLM failures into user-facing spoken + UI messages."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AgentErrorInfo:
    code: str
    title: str
    message: str
    spoken: str
    retryable: bool = True
    retry_after_seconds: int = 120

    def to_studio_event(self, *, anchor_name: str = "NOVA") -> dict[str, Any]:
        return {
            "type": "agent_error",
            "code": self.code,
            "title": self.title,
            "message": self.message,
            "spokenText": self.spoken,
            "retryable": self.retryable,
            "retryAfterSeconds": self.retry_after_seconds,
            "anchorName": anchor_name,
        }


def _err_text(err: Any) -> str:
    if err is None:
        return ""
    for attr in ("message", "body", "detail"):
        val = getattr(err, attr, None)
        if val:
            return str(val)
    return str(err)


def classify_agent_error(err: Any, *, source: str = "") -> AgentErrorInfo:
    """Map an exception or session error to a stable code + copy for voice and UI."""
    text = _err_text(err).lower()
    source_l = source.lower()
    combined = f"{source_l} {text}"

    if any(x in combined for x in ("429", "rate limit", "rate_limit", "tokens per day", "tpd")):
        retry = 180
        m = re.search(r"try again in (\d+)m", text)
        if m:
            retry = int(m.group(1)) * 60
        return AgentErrorInfo(
            code="llm_rate_limit",
            title="High demand right now",
            message="GenzCine's news AI is temporarily at capacity. Please wait a few minutes and reconnect.",
            spoken=(
                "Thanks for tuning in — we're getting a lot of viewers right now and I need a "
                "quick breather. Give me two or three minutes and connect again. I'll be ready "
                "with today's headlines."
            ),
            retryable=True,
            retry_after_seconds=retry,
        )

    if any(x in combined for x in ("401", "403", "invalid api key", "unauthorized", "authentication")):
        return AgentErrorInfo(
            code="llm_auth",
            title="Service configuration issue",
            message="The news service couldn't authenticate. Our team has been notified.",
            spoken=(
                "I'm sorry — I'm having trouble connecting to the news desk on our end. "
                "Please try again in a little while."
            ),
            retryable=True,
            retry_after_seconds=300,
        )

    if "stt" in source_l or "speech" in combined and "transcri" in combined:
        return AgentErrorInfo(
            code="stt_error",
            title="Couldn't hear you",
            message="Microphone or speech recognition had a problem. Check your mic and try again.",
            spoken=(
                "I'm having a little trouble hearing you right now. "
                "Make sure your microphone is on and try speaking again."
            ),
            retryable=True,
            retry_after_seconds=30,
        )

    if any(x in combined for x in ("502", "503", "504", "timeout", "connection", "unavailable")):
        return AgentErrorInfo(
            code="service_unavailable",
            title="News desk offline",
            message="We couldn't reach the news service. Please try again shortly.",
            spoken=(
                "Looks like the news desk is briefly offline. "
                "Hang tight and reconnect in a minute — I'll have fresh headlines for you."
            ),
            retryable=True,
            retry_after_seconds=60,
        )

    if "news" in combined and ("no_headlines" in combined or "newsdata" in combined):
        return AgentErrorInfo(
            code="news_unavailable",
            title="Headlines unavailable",
            message="Live headlines couldn't be loaded right now. You can still chat with the anchor.",
            spoken=(
                "I couldn't pull fresh headlines just this second, but I'm still here — "
                "ask me about any topic and I'll try again."
            ),
            retryable=True,
            retry_after_seconds=30,
        )

    return AgentErrorInfo(
        code="llm_error",
        title="Something went wrong",
        message="The AI anchor hit a snag. Disconnect and try connecting again.",
        spoken=(
            "Hi — I'm having a little trouble reaching the news desk right now. "
            "Please disconnect and try again in a moment. I'll be right here when you're ready."
        ),
        retryable=True,
        retry_after_seconds=90,
    )


def api_error_payload(code: str, *, detail: str = "") -> dict[str, str]:
    """Structured JSON for HTTP errors (connection-details, etc.)."""
    mapping: dict[str, tuple[str, str]] = {
        "trial_expired": (
            "Free session used",
            "Your free trial time is up. Visit genzcine.com for unlimited live news.",
        ),
        "rate_limited": (
            "Too many requests",
            "Please wait a minute before connecting again.",
        ),
        "session_unavailable": (
            "Anchor offline",
            "NOVA couldn't start a session right now. Try again shortly.",
        ),
    }
    title, message = mapping.get(code, ("Error", detail or "Something went wrong."))
    return {"error": code, "title": title, "message": message, "detail": detail}

"""Regression mocks for mid-session silence (language switch + long thinking).

Replays the room-4788 failure mode:
  intro OK → Hindi Firozpur news → preemptive invalidated → long mute → user leaves.

These tests lock the silence-cover contract so that path cannot go quiet again
without a failing test.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from livekit.agents import StopResponse
from livekit.agents import llm as lk_llm

from local_voice_ai.agent import (
    Assistant,
    should_cover_language_switch_silence,
    should_speak_delayed_thinking_filler,
    should_wait_after_filler_speech,
)
from local_voice_ai.services.spoken_lang import language_bridge, thinking_filler


# ── Pure decision helpers (state-machine contract) ───────────────────────────


def test_language_switch_with_news_must_cover_silence() -> None:
    assert should_cover_language_switch_silence(switched=True, switch_only=False) is True
    assert should_cover_language_switch_silence(switched=True, switch_only=True) is False
    assert should_cover_language_switch_silence(switched=False, switch_only=False) is False


def test_news_ask_also_covers_silence_even_without_lang_switch() -> None:
    from local_voice_ai.agent import should_cover_turn_silence

    assert should_cover_turn_silence(switched=False, news_ask=True, switch_only=False) is True
    assert should_cover_turn_silence(switched=False, news_ask=False, switch_only=False) is False
    assert should_cover_turn_silence(switched=True, news_ask=True, switch_only=True) is False


def test_delayed_filler_only_while_silently_thinking() -> None:
    base = dict(
        agent_state="thinking",
        silence_filler_spoken=False,
        opening=False,
        connected=True,
        user_turn_active=True,
    )
    assert should_speak_delayed_thinking_filler(**base) is True
    assert should_speak_delayed_thinking_filler(**{**base, "silence_filler_spoken": True}) is False
    assert should_speak_delayed_thinking_filler(**{**base, "agent_state": "speaking"}) is False
    assert should_speak_delayed_thinking_filler(**{**base, "opening": True}) is False
    assert should_speak_delayed_thinking_filler(**{**base, "connected": False}) is False
    assert should_speak_delayed_thinking_filler(**{**base, "user_turn_active": False}) is False


def test_filler_end_must_wait_if_real_reply_in_flight() -> None:
    assert should_wait_after_filler_speech(agent_state="thinking") is True
    assert should_wait_after_filler_speech(agent_state="speaking") is True
    assert should_wait_after_filler_speech(agent_state="listening") is False
    assert should_wait_after_filler_speech(agent_state="idle") is False


def test_firozpur_scenario_decision_matrix() -> None:
    """Exact sequence from the broken session must never choose 'stay silent'."""
    # 1) Language flips mid-ask → immediate cover required
    assert should_cover_language_switch_silence(switched=True, switch_only=False)
    # 2) Immediate cover already spoken → delayed filler must not double
    assert not should_speak_delayed_thinking_filler(
        agent_state="thinking",
        silence_filler_spoken=True,
        opening=False,
        connected=True,
        user_turn_active=True,
    )
    # 3) Same lang, long news fetch, no prior filler → delayed cover required
    assert should_speak_delayed_thinking_filler(
        agent_state="thinking",
        silence_filler_spoken=False,
        opening=False,
        connected=True,
        user_turn_active=True,
    )
    # 4) Filler finished while LLM still thinking → do not open idle window
    assert should_wait_after_filler_speech(agent_state="thinking")


# ── Assistant.on_user_turn_completed mockups ─────────────────────────────────


@pytest.fixture
def assistant() -> Assistant:
    agent = Assistant(language="en-US", anchor_name="NOVA")
    agent.update_instructions = AsyncMock()
    agent.update_chat_ctx = AsyncMock()
    agent._tts_router = MagicMock()
    agent._tts_router.set_spoken = MagicMock()
    agent._say_language = AsyncMock()
    agent._last_whisper_lang = "hi"
    return agent


def _user_msg(text: str) -> lk_llm.ChatMessage:
    return lk_llm.ChatMessage(role="user", content=[text])


@pytest.mark.asyncio
async def test_hindi_firozpur_news_speaks_thinking_filler_immediately(
    assistant: Assistant,
) -> None:
    """Room-4788 mock: en session + Hindi city news must not go mute after lang flip."""
    turn_ctx = lk_llm.ChatContext.empty()
    spoken: list[tuple] = []

    async def _capture(code: str, text: str, *, wait: bool = True) -> None:
        spoken.append((code, text, wait))

    assistant._say_language = AsyncMock(side_effect=_capture)

    with (
        patch("local_voice_ai.agent._ctx_update_instructions") as upd,
        patch("local_voice_ai.agent._warm_headline_cache", new_callable=AsyncMock),
        patch("local_voice_ai.agent.asyncio.create_task", side_effect=lambda coro: coro.close() or MagicMock()),
    ):
        await assistant.on_user_turn_completed(
            turn_ctx,
            _user_msg("मुझे फिरोजपुर की खबर बताओ"),
        )

    assert assistant._language == "hi"
    assert assistant._silence_filler_spoken is True
    assert assistant._filler_speaking is True
    assert assistant._pending_lang_commit is True
    # TTS switched without committing agent instructions yet (preemptive-race fix).
    assistant.update_instructions.assert_not_awaited()
    upd.assert_called_once()
    assert spoken, "expected immediate thinking filler"
    code, line, wait = spoken[0]
    assert code == "hi"
    assert line == thinking_filler("hi")
    assert wait is False
    # Must not be the longer language-bridge line
    assert line != language_bridge("hi")


@pytest.mark.asyncio
async def test_switch_only_uses_bridge_not_filler_and_stops_llm(
    assistant: Assistant,
) -> None:
    turn_ctx = lk_llm.ChatContext.empty()
    spoken: list[tuple] = []

    async def _capture(code: str, text: str, *, wait: bool = True) -> None:
        spoken.append((code, text, wait))

    assistant._say_language = AsyncMock(side_effect=_capture)

    with (
        patch("local_voice_ai.agent._ctx_update_instructions"),
        patch("local_voice_ai.agent._warm_headline_cache", new_callable=AsyncMock),
        patch(
            "local_voice_ai.agent.asyncio.create_task",
            side_effect=lambda coro: coro.close() or MagicMock(),
        ),
    ):
        with pytest.raises(StopResponse):
            await assistant.on_user_turn_completed(
                turn_ctx,
                _user_msg("Hindi me bolo"),
            )

    assert spoken
    assert spoken[0][1] == language_bridge("hi")
    assert assistant._pending_lang_commit is False
    assistant.update_instructions.assert_awaited()


@pytest.mark.asyncio
async def test_same_language_news_speaks_thinking_filler(
    assistant: Assistant,
) -> None:
    """Already Hindi news ask — still cover the news-tool wait (no mute)."""
    assistant._language = "hi"
    spoken: list[tuple] = []

    async def _capture(code: str, text: str, *, wait: bool = True) -> None:
        spoken.append((code, text, wait))

    assistant._say_language = AsyncMock(side_effect=_capture)

    with (
        patch("local_voice_ai.agent._ctx_update_instructions") as upd,
        patch("local_voice_ai.agent._warm_headline_cache", new_callable=AsyncMock),
        patch(
            "local_voice_ai.agent.asyncio.create_task",
            side_effect=lambda coro: coro.close() or MagicMock(),
        ),
    ):
        await assistant.on_user_turn_completed(
            lk_llm.ChatContext.empty(),
            _user_msg("मुझे दिल्ली की खबर बताओ"),
        )

    assert spoken, "news ask must speak immediate filler"
    assert spoken[0][1] == thinking_filler("hi")
    assert assistant._silence_filler_spoken is True
    upd.assert_not_called()


@pytest.mark.asyncio
async def test_stt_garbage_stops_without_speech(assistant: Assistant) -> None:
    with pytest.raises(StopResponse):
        await assistant.on_user_turn_completed(
            lk_llm.ChatContext.empty(),
            _user_msg("thank you for watching"),
        )
    assistant._say_language.assert_not_awaited()

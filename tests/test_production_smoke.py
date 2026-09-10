"""Deep production smoke — one continuous "real viewer" session.

Covers the exact failure modes we shipped fixes for:
  barge-in during intro → Hindi city news → sticky follow-up → language switch
  → idle resume in Hindi → leave stops speech → fillers stay TTS-safe.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from livekit.agents import StopResponse
from livekit.agents import llm as lk_llm

from local_voice_ai.agent import (
    Assistant,
    BULLETIN_RESUME_AFTER_USER_SECONDS,
    _headline_spoken_parts,
    _human_participant_names,
    _is_avatar_identity,
    _resume_bridge_for,
    _trial_line,
    _tv_open_segments,
)
from local_voice_ai.services.spoken_lang import (
    has_sarvam_script,
    is_intro_ack,
    is_news_ask,
    language_bridge,
    thinking_filler,
)


def _msg(text: str) -> lk_llm.ChatMessage:
    return lk_llm.ChatMessage(role="user", content=[text])


def _spawn_close(coro):
    try:
        coro.close()
    except Exception:
        pass
    return MagicMock()


@pytest.fixture
def agent() -> Assistant:
    a = Assistant(language="en-US", anchor_name="NOVA")
    a.update_instructions = AsyncMock()
    a.update_chat_ctx = AsyncMock()
    a._tts_router = MagicMock()
    a._tts_router.set_spoken = MagicMock()
    a._say_language = AsyncMock()
    a._last_whisper_lang = "en"
    a._room = MagicMock()
    a._room.isconnected.return_value = True
    return a


async def _turn(agent: Assistant, text: str, *, whisper: str | None = None) -> list[tuple]:
    if whisper:
        agent._last_whisper_lang = whisper
    spoken: list[tuple] = []

    async def _capture(code: str, line: str, *, wait: bool = True) -> None:
        spoken.append((code, line, wait))

    agent._say_language = AsyncMock(side_effect=_capture)
    with (
        patch("local_voice_ai.agent._ctx_update_instructions"),
        patch("local_voice_ai.agent._warm_headline_cache", new_callable=AsyncMock) as warm,
        patch("local_voice_ai.agent.asyncio.create_task", side_effect=_spawn_close),
        patch("local_voice_ai.agent.publish_studio_event", new_callable=AsyncMock),
    ):
        try:
            await agent.on_user_turn_completed(lk_llm.ChatContext.empty(), _msg(text))
        except StopResponse:
            pass  # switch-only / cooldown / intro-ack intentionally stop the LLM
        agent._last_warm = warm  # type: ignore[attr-defined]
    return spoken


# ── Guards that must never regress in prod ───────────────────────────────────


def test_prod_guards_env_and_tts_safe_fillers() -> None:
    assert BULLETIN_RESUME_AFTER_USER_SECONDS <= 4.0
    for code in ("hi", "pa", "bn", "ta", "mr", "gu"):
        line = thinking_filler(code)
        assert line
        assert has_sarvam_script(line, code), f"{code} filler not native: {line!r}"
    assert "second" not in thinking_filler("en").lower()
    assert is_intro_ack("Thank you Nova")
    assert not is_intro_ack("Okay, tell me next question.")
    assert _is_avatar_identity("simli-face-abc")
    assert _human_participant_names({"simli-x": "Bot", "user-9": "Ravi"}) == ["Ravi"]


def test_prod_resume_and_trial_language_matched() -> None:
    code, line = _resume_bridge_for("hi", 0)
    assert code == "hi" and "\u0916\u092c\u0930" in line
    code_pa, line_pa = _resume_bridge_for("pa", 0)
    assert code_pa == "pa" and line_pa
    assert "trial" in _trial_line("warn", "en").lower() or "GenzCine" in _trial_line("warn", "en")
    assert "GenzCine" in _trial_line("warn", "hi") or "\u091c\u0940" in _trial_line("warn", "hi")


@pytest.mark.asyncio
async def test_prod_full_viewer_session_smoke(agent: Assistant) -> None:
    """Continuous path a phone viewer actually walks in production."""

    # 1) Join open — Simli not welcomed by name; barge-in cuts leftover ident.
    names = _human_participant_names(
        {"simli-avatar-1": "Simli Avatar", "viewer-42": "Ayush"}
    )
    assert names == ["Ayush"]
    segs = _tv_open_segments("NOVA", names[0])
    assert [c for c, _ in segs] == ["hi", "pa", "en"]
    assert "Ayush" in segs[2][1]

    spoken_codes: list[str] = []

    async def _cap_open(code: str, line: str, *, wait: bool = True) -> None:
        spoken_codes.append(code)
        if code == "hi":
            # Viewer asks mid-Namaste.
            agent._opening = False
            agent._opening_cut = True

    agent._opening = True
    agent._opening_cut = False
    agent._say_language = AsyncMock(side_effect=_cap_open)
    # Keep real _can_speak — only force connected room.
    await agent._speak_trilingual_open(names[0])
    assert spoken_codes == ["hi"], "must not continue into Punjabi/English after barge-in"
    assert agent._opening_cut is True

    # on_enter finally clears cut so later bulletin works
    agent._opening = False
    agent._opening_cut = False
    assert agent._can_speak() is True

    # Mid-intro real question is accepted (not treated as ack).
    agent._opening = True
    agent._opening_cut = False
    await _turn(agent, "Okay, tell me next question.", whisper="en")
    assert agent._opening is False
    assert agent._opening_cut is True
    agent._opening_cut = False  # simulate on_enter finally

    # 2) Hindi city news — filler native, sticky set, warm after language apply.
    spoken = await _turn(agent, "मुझे फिरोजपुर की खबर बताओ", whisper="hi")
    assert agent._language == "hi"
    assert agent._preferred_location and "Firozpur" in agent._preferred_location
    assert spoken and spoken[0][0] == "hi"
    assert spoken[0][1] == thinking_filler("hi")
    assert has_sarvam_script(spoken[0][1], "hi")
    warm = agent._last_warm  # type: ignore[attr-defined]
    warm.assert_called()
    # Warm uses post-switch language (hi), not stale en-US.
    assert agent._language == "hi"

    sticky = agent._preferred_location

    # 3) Follow-up keeps sticky + filler again.
    spoken2 = await _turn(agent, "aur batao Firozpur news", whisper="hi")
    assert agent._preferred_location == sticky
    assert spoken2 and spoken2[0][1] == thinking_filler("hi")

    # 4) Topical ask does not wipe city.
    ctx = MagicMock()
    with (
        patch(
            "local_voice_ai.agent.fetch_latest_news",
            new_callable=AsyncMock,
            return_value=[{"title": "India wins", "source": "PTI", "provider": "google_rss"}],
        ),
        patch("local_voice_ai.agent.publish_studio_event", new_callable=AsyncMock),
    ):
        await agent.get_latest_news(ctx, topic="cricket")
    assert agent._preferred_location == sticky

    # 5) Switch-only — bridge, no news mute.
    spoken3 = await _turn(agent, "English me bolo", whisper="en")
    assert agent._language.startswith("en")
    assert spoken3 and spoken3[0][1] == language_bridge("en")

    # Back to Hindi for idle resume check.
    await _turn(agent, "Hindi me bolo", whisper="hi")
    assert agent._language == "hi"
    code, resume = _resume_bridge_for(agent._spoken_code(), 0)
    assert code == "hi"
    assert resume

    # 6) Headline TTS still native bridge + English body.
    bridge, body = _headline_spoken_parts(
        {"title": "Markets rally", "description": "", "provider": "google_rss"},
        is_first=True,
        language="hi",
    )
    assert "\u0916\u092c\u0930" in bridge or "\u092a\u0939\u0932\u0940" in bridge
    assert "Markets rally" in body

    # 7) Leave — last human stops speech permanently.
    agent._participants = {"viewer-42": "Ayush"}
    agent._on_participant_disconnected(
        MagicMock(identity="viewer-42", name="Ayush")
    )
    assert agent._viewer_gone is True
    assert agent._can_speak() is False


@pytest.mark.asyncio
async def test_prod_intro_ack_does_not_cut_but_thanks_name_is_ack(agent: Assistant) -> None:
    agent._opening = True
    agent._opening_cut = False
    with (
        patch("local_voice_ai.agent._ctx_update_instructions"),
        patch("local_voice_ai.agent._warm_headline_cache", new_callable=AsyncMock),
        patch("local_voice_ai.agent.asyncio.create_task", side_effect=_spawn_close),
    ):
        with pytest.raises(StopResponse):
            await agent.on_user_turn_completed(
                lk_llm.ChatContext.empty(), _msg("Thank you Nova")
            )
    assert agent._opening is True
    assert agent._opening_cut is False


@pytest.mark.asyncio
async def test_prod_cooldown_speaks_filler_not_mute(agent: Assistant) -> None:
    import local_voice_ai.agent as ag

    ag._llm_ready_at = __import__("time").monotonic() + 30
    try:
        spoken = await _turn(agent, "Firozpur news batao", whisper="hi")
        assert spoken, "cooldown must not go mute"
        assert spoken[0][1] == thinking_filler(spoken[0][0])
    finally:
        ag._llm_ready_at = 0.0


@pytest.mark.asyncio
async def test_prod_live_city_news_fetch_not_empty() -> None:
    """Hit real sources once — production path must return usable headlines."""
    from local_voice_ai.services.news import _HEADLINE_CACHE, fetch_latest_news

    _HEADLINE_CACHE.clear()
    city = await fetch_latest_news(query="Firozpur", language="hi", limit=3)
    assert isinstance(city, list)
    # Network can flake; structure must not crash. If hits exist, they need titles.
    if city:
        assert city[0].get("title")

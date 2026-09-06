#!/usr/bin/env python3
"""Replay the live 429 storm and show why High-demand keeps coming back."""

from __future__ import annotations

from local_voice_ai.agent import _BASE_INSTRUCTIONS, _GROUP_ADDON, _language_addon
from local_voice_ai.services.agent_errors import classify_agent_error
from local_voice_ai.services.spoken_lang import detect_spoken_lang, is_language_switch_only, is_stt_garbage

# Groq on_demand qwen/qwen3.8-27b — from the live 429 body.
ITPM_LIMIT = 7000
TOKENS_PER_CALL = 1872  # live "Requested 1872"
LIVEKIT_RETRIES = 4  # attempt 1..4 in the logs

# Exact STT lines from room 8110 / job AJ_xcmJffhGU58A (17:42 session).
SESSION_STT = [
    "If the speaker is Punjabi, transcribe in Ddevanagari. Sat Sri Akal is always Punjabi.",
    "Thank you for watching!",
    "can you tell me a news in Punjabi?",
    "تم مجھے ہندی میں سن سکتی ہو",
    "Mujhe Aashika Nepal ka news batao.",
    "No, can you still speak English with me?",
]


def _tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _ok(name: str, cond: bool, detail: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  {mark}  {name}" + (f"  {detail}" if detail else ""))


def test_prompt_budget() -> int:
    prompt = (
        _BASE_INSTRUCTIONS.format(anchor_name="TINA")
        + _language_addon("en-US")
        + _GROUP_ADDON
    )
    est = _tokens(prompt)
    print("=== prompt size ===")
    print(f"  system chars={len(prompt)} est_tokens={est}")
    print(f"  live groq requested={TOKENS_PER_CALL} (tools+history on top)")
    print(f"  ITPM limit={ITPM_LIMIT}  => max clean calls/min={ITPM_LIMIT // TOKENS_PER_CALL}")
    _ok("one call uses >25% of the minute budget", TOKENS_PER_CALL > ITPM_LIMIT * 0.25)
    return est


def test_replay() -> None:
    print("\n=== replay STT (old detector, no garbage filter) ===")
    lang = "en"
    llm = 0
    for i, line in enumerate(SESSION_STT, 1):
        heard = detect_spoken_lang(line)
        # Simulate the OLD path: ignore garbage filter.
        from local_voice_ai.services import spoken_lang as sl

        raw_heard = None
        if sl._EN_SWITCH.search(line):
            raw_heard = "en"
        elif sl._GURMUKHI.search(line) or sl._PA_SWITCH.search(line) or sl._PA_HINT.search(line):
            raw_heard = "pa"
        elif sl._HI_SWITCH.search(line) or sl._DEVANAGARI.search(line) or sl._ARABIC.search(line):
            raw_heard = "hi"
        elif sl._HINGLISH.search(line):
            raw_heard = "hi"
        flip = raw_heard and raw_heard != lang
        if flip:
            lang = raw_heard
        # LiveKit preemptive + our generate_reply on flip/nudge
        calls = 2 if flip or not is_language_switch_only(line) else 1
        llm += calls
        print(
            f"  {i}. heard={raw_heard or '-':4} flip={bool(flip)} "
            f"garbage={is_stt_garbage(line)} llm_calls+={calls}  {line[:70]!r}"
        )
    retried = llm * LIVEKIT_RETRIES
    tokens = llm * TOKENS_PER_CALL
    tokens_retry = retried * TOKENS_PER_CALL
    print(f"\n  unique LLM turns={llm}  with 4 LiveKit retries={retried}")
    print(f"  tokens if accepted={tokens}  retry-storm hits={retried} (each 429 still retries)")
    _ok("session exceeds 7000 ITPM without retries", tokens > ITPM_LIMIT)
    _ok("retry storm is 4x worse", retried >= llm * 3)


def test_retry_after_parse() -> None:
    print("\n=== UI timer parse ===")
    groq = (
        "Error code: 429 - Rate limit reached ... Please try again in 12.917142857s."
    )
    info = classify_agent_error(groq, source="LLM")
    print(f"  groq said 12.9s  UI retryAfter={info.retry_after_seconds}s  code={info.code}")
    _ok("parses seconds not default 180", 12 <= info.retry_after_seconds <= 30)


def main() -> None:
    test_prompt_budget()
    test_replay()
    test_retry_after_parse()


if __name__ == "__main__":
    main()

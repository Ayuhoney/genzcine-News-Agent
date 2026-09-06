"""Tests for agent error classification."""

from local_voice_ai.services.agent_errors import classify_agent_error, api_error_payload


def test_rate_limit_classification() -> None:
    err = Exception(
        'Error code: 429 - {"message": "Rate limit reached ... try again in 3m18.72s"}'
    )
    info = classify_agent_error(err, source="LLM")
    assert info.code == "llm_rate_limit"
    assert info.retryable is True
    assert "capacity" in info.message.lower()
    assert info.retry_after_seconds == 180


def test_rate_limit_parses_seconds() -> None:
    err = Exception(
        "Rate limit reached for model on input tokens per minute (ITPM): "
        "Limit 7000, Used 6635, Requested 1872. Please try again in 12.917142857s."
    )
    info = classify_agent_error(err, source="LLM")
    assert info.code == "llm_rate_limit"
    assert 15 <= info.retry_after_seconds <= 25


def test_api_error_payload_trial() -> None:
    payload = api_error_payload("trial_expired")
    assert payload["error"] == "trial_expired"
    assert "title" in payload
    assert "message" in payload

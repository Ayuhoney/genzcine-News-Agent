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


def test_api_error_payload_trial() -> None:
    payload = api_error_payload("trial_expired")
    assert payload["error"] == "trial_expired"
    assert "title" in payload
    assert "message" in payload

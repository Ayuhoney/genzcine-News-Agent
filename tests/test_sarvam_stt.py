"""Sarvam STT uses Saaras and keeps the detected language on the transcript."""

from __future__ import annotations

import pytest
from livekit import rtc

from local_voice_ai.services.sarvam_stt import SarvamSTT, sarvam_stt_model


def test_whisper_model_name_does_not_override_saaras(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STT_MODEL", "whisper-large-v3")
    monkeypatch.delenv("SARVAM_STT_MODEL", raising=False)
    assert sarvam_stt_model() == "saaras:v3"


def test_explicit_saaras_model_is_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SARVAM_STT_MODEL", "saaras:v4")
    assert sarvam_stt_model() == "saaras:v4"


class _Resp:
    status_code = 200
    text = ""

    def json(self) -> dict:
        return {"transcript": "मुझे मोहाली की खबर बताओ", "language_code": "hi-IN"}


class _Client:
    def __init__(self) -> None:
        self.data: dict | None = None

    async def post(self, url: str, **kwargs):
        self.data = kwargs.get("data")
        assert url.endswith("/speech-to-text")
        assert kwargs["headers"]["api-subscription-key"] == "test-key"
        return _Resp()


@pytest.mark.asyncio
async def test_recognize_returns_sarvam_transcript_and_language() -> None:
    client = _Client()
    engine = SarvamSTT(api_key="test-key", model="saaras:v3", http_session=client)  # type: ignore[arg-type]
    frame = rtc.AudioFrame(
        data=b"\x00\x00" * 1600,
        sample_rate=16000,
        num_channels=1,
        samples_per_channel=1600,
    )
    event = await engine._recognize_impl(frame, language="en-US", conn_options=None)  # type: ignore[arg-type]
    assert event.alternatives[0].text.startswith("मुझे मोहाली")
    assert str(event.alternatives[0].language).startswith("hi")
    assert client.data is not None
    assert client.data["model"] == "saaras:v3"
    assert client.data["mode"] == "transcribe"
    assert "language_code" not in client.data

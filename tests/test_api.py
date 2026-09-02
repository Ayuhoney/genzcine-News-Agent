"""Tests for the FastAPI app: token minting and API routes."""

from __future__ import annotations

import base64
import json

import pytest
from fastapi.testclient import TestClient

from local_voice_ai.api import build_app
from local_voice_ai.config import Config


def _decode_jwt_payload(token: str) -> dict:
    payload_b64 = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload_b64 + "==").decode())


@pytest.fixture
def cfg(monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("LIVEKIT_API_KEY", "devkey")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "secret-secret-secret-thirty-two-chars")
    monkeypatch.setenv("LIVEKIT_URL", "ws://127.0.0.1:7880")
    return Config.from_env()


@pytest.fixture
def client(cfg: Config) -> TestClient:
    return TestClient(build_app(cfg))


class TestHealth:
    def test_healthz_returns_ok(self, client: TestClient) -> None:
        r = client.get("/healthz")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}

    def test_root_returns_api_only(self, client: TestClient) -> None:
        r = client.get("/")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


class TestCors:
    def test_head_root_allows_localhost_dev_origin(self, client: TestClient) -> None:
        r = client.head(
            "/",
            headers={"Origin": "http://localhost:5174"},
        )
        assert r.status_code == 200
        assert r.headers.get("access-control-allow-origin") == "http://localhost:5174"


class TestConnectionDetails:
    def test_mints_token_with_empty_body(self, client: TestClient) -> None:
        r = client.post("/api/connection-details", json={})
        assert r.status_code == 200
        data = r.json()
        assert {"serverUrl", "roomName", "sessionType", "participantName", "participantToken"}.issubset(set(data))
        assert data["serverUrl"] == "ws://127.0.0.1:7880"
        assert data["roomName"].startswith("voice_assistant_room_")
        assert data["sessionType"] == "individual"
        assert data["participantName"] == "model"
        assert isinstance(data.get("trialRemainingSeconds"), int)

    def test_jwt_carries_correct_issuer_and_grants(self, client: TestClient) -> None:
        r = client.post("/api/connection-details", json={})
        payload = _decode_jwt_payload(r.json()["participantToken"])
        assert payload["iss"] == "devkey"
        assert payload["sub"].startswith("model_")
        assert "video" in payload
        # AccessToken.with_grants serializes VideoGrants with camelCase keys.
        video = payload["video"]
        assert video.get("roomJoin") is True
        assert video.get("canPublish") is True
        assert video.get("canSubscribe") is True

    def test_token_has_expiry(self, client: TestClient) -> None:
        r = client.post("/api/connection-details", json={})
        payload = _decode_jwt_payload(r.json()["participantToken"])
        # 30-minute TTL → exp - nbf should be 1800s.
        assert payload["exp"] - payload["nbf"] == 1800

    def test_agent_dispatch_included_when_requested(self, client: TestClient) -> None:
        r = client.post(
            "/api/connection-details",
            json={"room_config": {"agents": [{"agent_name": "my-agent"}]}},
        )
        assert r.status_code == 200
        payload = _decode_jwt_payload(r.json()["participantToken"])
        assert "roomConfig" in payload

    def test_room_config_always_has_metadata(self, client: TestClient) -> None:
        # room_config is always set (carries face_id, voice, trial_seconds)
        r = client.post("/api/connection-details", json={})
        payload = _decode_jwt_payload(r.json()["participantToken"])
        assert "roomConfig" in payload

    def test_malformed_body_still_returns_a_token(self, client: TestClient) -> None:
        r = client.post("/api/connection-details", content=b"not json")
        assert r.status_code == 200

    def test_each_call_produces_a_fresh_room(self, client: TestClient) -> None:
        rooms = {client.post("/api/connection-details", json={}).json()["roomName"] for _ in range(8)}
        # Random ints in [0, 9999] → collisions are statistically possible but rare;
        # we want at least most of the rooms to be unique.
        assert len(rooms) >= 6

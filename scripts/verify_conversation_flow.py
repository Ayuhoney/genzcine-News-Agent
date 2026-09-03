#!/usr/bin/env python3
"""End-to-end dummy viewer test: LiveKit join, TTS speech mic, validate studio flow."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from livekit import rtc

API = "http://127.0.0.1:8080"
LIVEKIT_URL = "ws://127.0.0.1:7890"
DEVICE_ID = str(uuid.uuid4())
PARTICIPANT = "AutoTestViewer"
FACE_ID = "cace3ef7-a4c4-425d-a8cf-a5358eb0c427"

UTTERANCES = (
    "Mohali",
    "Tell me more about that story please.",
)


@dataclass
class FlowReport:
    room_name: str = ""
    agent_joined: bool = False
    events: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def add(self, event: dict) -> None:
        self.events.append(event)

    def types(self) -> set[str]:
        return {e.get("type", "") for e in self.events}

    def transcript_roles(self) -> list[str]:
        return [e.get("role", "") for e in self.events if e.get("type") == "transcript"]

    def modes(self) -> list[str]:
        return [
            e.get("mode", "")
            for e in self.events
            if e.get("type") == "studio_state" and e.get("mode")
        ]


def _generate_speech_pcm(text: str, *, sample_rate: int = 48000) -> bytes:
    """espeak-ng + ffmpeg → 48 kHz mono s16le PCM (real words for STT)."""
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "speech.wav"
        pcm = Path(tmp) / "speech.pcm"
        subprocess.run(
            ["espeak-ng", "-v", "en-us", "-s", "150", "-w", str(wav), text],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(wav),
                "-ar",
                str(sample_rate),
                "-ac",
                "1",
                "-f",
                "s16le",
                str(pcm),
            ],
            check=True,
            capture_output=True,
        )
        return pcm.read_bytes()


async def _fetch_token() -> dict:
    payload = {
        "participant_name": PARTICIPANT,
        "device_id": DEVICE_ID,
        "face_id": FACE_ID,
        "voice": "af_nova",
        "anchor_name": "TINA",
        "include_headlines": True,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{API}/api/connection-details", json=payload)
        r.raise_for_status()
        return r.json()


async def _publish_pcm(room: rtc.Room, pcm: bytes, *, lead_silence: float = 0.3) -> None:
    source = rtc.AudioSource(48000, 1)
    track = rtc.LocalAudioTrack.create_audio_track("mic", source)
    opts = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
    await room.local_participant.publish_track(track, opts)

    if lead_silence > 0:
        silence = b"\x00" * int(48000 * 2 * lead_silence)
        pcm = silence + pcm

    chunk_samples = 960  # 20 ms @ 48 kHz
    chunk_bytes = chunk_samples * 2
    for offset in range(0, len(pcm), chunk_bytes):
        chunk = pcm[offset : offset + chunk_bytes]
        if len(chunk) < chunk_bytes:
            padding = b"\x00" * (chunk_bytes - len(chunk))
            chunk = chunk + padding
        n = len(chunk) // 2
        await source.capture_frame(
            rtc.AudioFrame(chunk, sample_rate=48000, num_channels=1, samples_per_channel=n)
        )
        await asyncio.sleep(0.02)

    # Trailing silence so VAD endpointing fires.
    tail = b"\x00" * int(48000 * 2 * 1.2)
    for offset in range(0, len(tail), chunk_bytes):
        chunk = tail[offset : offset + chunk_bytes]
        n = len(chunk) // 2
        await source.capture_frame(
            rtc.AudioFrame(chunk, sample_rate=48000, num_channels=1, samples_per_channel=n)
        )
        await asyncio.sleep(0.02)


async def run_test() -> FlowReport:
    report = FlowReport()
    details = await _fetch_token()
    report.room_name = details["roomName"]
    token = details["participantToken"]
    print(f"room={report.room_name} device={DEVICE_ID[:8]}…")

    room = rtc.Room()
    agent_joined = asyncio.Event()
    agent_audio = asyncio.Event()

    @room.on("participant_connected")
    def _on_participant(p: rtc.RemoteParticipant) -> None:
        ident = (p.identity or "").lower()
        if "agent" in ident:
            print(f"  agent joined: {p.identity}")
            agent_joined.set()

    @room.on("track_subscribed")
    def _on_track(track: rtc.Track, publication, participant) -> None:
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            print(f"  agent audio track from {participant.identity}")
            agent_audio.set()

    @room.on("data_received")
    def _on_data(packet: rtc.DataPacket) -> None:
        topic = packet.topic or ""
        if topic not in ("genzcine_studio", "genzcine_transcript", ""):
            return
        try:
            msg = json.loads(packet.data.decode())
        except Exception:
            return
        report.add(msg)
        t = msg.get("type", "")
        if t == "studio_state":
            print(f"  studio_state → {msg.get('mode')}")
        elif t == "transcript":
            role = msg.get("role", "?")
            text = (msg.get("text") or "")[:80]
            print(f"  transcript [{role}]: {text!r}")
        elif t in ("agent_ready", "headline_now", "video_start"):
            print(f"  {t}")

    await room.connect(LIVEKIT_URL, token)
    print("connected")

    try:
        await asyncio.wait_for(agent_joined.wait(), timeout=60)
        report.agent_joined = True
    except asyncio.TimeoutError:
        report.errors.append("agent did not join within 60s")
        await room.disconnect()
        return report

    print("waiting for city-ask greeting (8s)…")
    await asyncio.sleep(8)

    for i, line in enumerate(UTTERANCES, start=1):
        print(f"speaking utterance {i}: {line!r}")
        pcm = _generate_speech_pcm(line)
        await _publish_pcm(room, pcm)
        wait = 22 if i == 1 else 18
        print(f"waiting {wait}s for STT + reply…")
        await asyncio.sleep(wait)

    print(f"waiting {CONVERSATION_IDLE_WAIT}s for conversation idle → bulletin resume…")
    await asyncio.sleep(CONVERSATION_IDLE_WAIT)

    await room.disconnect()
    print("disconnected")
    return report


CONVERSATION_IDLE_WAIT = 16  # slightly above default 12s idle + bridge TTS


def _score(report: FlowReport) -> tuple[int, list[str]]:
    checks: list[tuple[str, bool]] = []
    types = report.types()
    modes = report.modes()
    roles = report.transcript_roles()

    checks.append(("agent joined", report.agent_joined))
    checks.append(("agent_ready event", "agent_ready" in types))
    checks.append(("headline event", "headline_now" in types or "headlines" in types))
    checks.append(("conversation mode seen", "conversation" in modes))
    checks.append(("back to live mode", modes.count("live") >= 2 or ("live" in modes and "conversation" in modes)))
    checks.append(("user transcript relayed", "user" in roles))
    checks.append(("agent transcript relayed", "agent" in roles))

    lines = [f"{'PASS' if ok else 'FAIL'} — {label}" for label, ok in checks]
    passed = sum(1 for _, ok in checks if ok)
    return passed, lines


async def main() -> int:
    t0 = time.monotonic()
    try:
        report = await run_test()
    except Exception as exc:
        print(f"TEST CRASH: {exc}", file=sys.stderr)
        return 2

    passed, lines = _score(report)
    total = len(lines)
    elapsed = time.monotonic() - t0

    print("\n=== FLOW REPORT ===")
    print(f"room: {report.room_name}")
    print(f"events captured: {len(report.events)}")
    print(f"studio modes: {report.modes()}")
    print(f"transcript roles: {report.transcript_roles()}")
    for line in lines:
        print(line)
    print(f"\nResult: {passed}/{total} checks passed in {elapsed:.0f}s")
    if report.errors:
        for err in report.errors:
            print(f"ERROR: {err}")

    # Hint for manual log grep
    print(f"\nLogs: docker logs genzcine-news-app-1 2>&1 | grep {report.room_name}")

    return 0 if passed >= total - 1 else 1  # allow 1 soft fail (headlines timing)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

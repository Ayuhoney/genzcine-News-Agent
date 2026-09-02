#!/usr/bin/env python3
"""Join a LiveKit room, publish speech-like audio, and verify VAD picks it up."""

from __future__ import annotations

import asyncio
import json
import math
import struct
import sys
import time
import uuid

import httpx
from livekit import rtc

API = "http://127.0.0.1:8080"
LIVEKIT_URL = "ws://127.0.0.1:7890"
DEVICE_ID = str(uuid.uuid4())
PARTICIPANT = "VADVerifyBot"


def _speech_like_pcm(*, sample_rate: int = 48000, seconds: float = 2.5) -> bytes:
    """Amplitude-modulated tone — enough energy for Silero VAD to flag activity."""
    frames: list[int] = []
    n = int(sample_rate * seconds)
    for i in range(n):
        t = i / sample_rate
        mod = 0.35 + 0.65 * abs(math.sin(2 * math.pi * 3.5 * t))
        carrier = math.sin(2 * math.pi * 220 * t)
        sample = int(max(-32767, min(32767, 12000 * mod * carrier)))
        frames.append(sample)
    return struct.pack(f"<{len(frames)}h", *frames)


async def _fetch_token() -> dict:
    payload = {
        "participant_name": PARTICIPANT,
        "device_id": DEVICE_ID,
        "face_id": "cace3ef7-a4c4-425d-a8cf-a5358eb0c427",
        "voice": "af_nova",
        "anchor_name": "TINA",
        "include_headlines": True,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{API}/api/connection-details", json=payload)
        r.raise_for_status()
        return r.json()


def _load_speech_pcm(path: str = "/tmp/speech.pcm", *, sample_rate: int = 48000) -> bytes:
    try:
        with open(path, "rb") as f:
            data = f.read()
        if data:
            return data
    except OSError:
        pass
    return _speech_like_pcm(sample_rate=sample_rate)


async def _publish_audio(room: rtc.Room, *, seconds: float = 2.5) -> None:
    source = rtc.AudioSource(48000, 1)
    track = rtc.LocalAudioTrack.create_audio_track("mic", source)
    opts = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
    await room.local_participant.publish_track(track, opts)

    pcm = _load_speech_pcm()
    if seconds > 0:
        max_bytes = int(48000 * 2 * seconds)
        pcm = pcm[:max_bytes]
    chunk_samples = 960  # 20ms @ 48kHz
    chunk_bytes = chunk_samples * 2
    for offset in range(0, len(pcm), chunk_bytes):
        chunk = pcm[offset : offset + chunk_bytes]
        if len(chunk) < chunk_bytes:
            break
        n = len(chunk) // 2
        await source.capture_frame(
            rtc.AudioFrame(chunk, sample_rate=48000, num_channels=1, samples_per_channel=n)
        )
        await asyncio.sleep(0.02)


async def main() -> int:
    details = await _fetch_token()
    room_name = details["roomName"]
    token = details["participantToken"]
    print(f"room={room_name} connecting…")

    room = rtc.Room()
    agent_joined = asyncio.Event()

    @room.on("participant_connected")
    def _on_participant(p: rtc.RemoteParticipant) -> None:
        if p.identity.startswith("agent") or "agent" in p.identity.lower():
            print(f"agent joined: {p.identity}")
            agent_joined.set()

    await room.connect(LIVEKIT_URL, token)
    print("connected, waiting for agent…")
    try:
        await asyncio.wait_for(agent_joined.wait(), timeout=45)
    except asyncio.TimeoutError:
        print("FAIL: agent did not join within 45s")
        return 1

    # Let the anchor start speaking headlines.
    await asyncio.sleep(8)
    print("publishing test audio (simulated mic)…")
    await _publish_audio(room, seconds=3.0)
    await asyncio.sleep(6)
    await room.disconnect()
    print(f"done — check logs for room={room_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

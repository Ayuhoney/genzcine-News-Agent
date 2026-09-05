#!/usr/bin/env python3
"""LiveKit mock: speak Firozpur / Mohali / Chandigarh and check city pick-up."""
from __future__ import annotations

import asyncio
import json
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

import httpx
from livekit import rtc

API = "http://127.0.0.1:8080"
LIVEKIT_URL = "ws://127.0.0.1:7890"
CITIES = ("Firozpur", "Mohali", "Chandigarh", "Delhi", "national")
NEEDLES = {
    "Firozpur": ("firozpur", "ferozepur", "ferozpore"),
    "Mohali": ("mohali", "sas nagar"),
    "Chandigarh": ("chandigarh", "tricity"),
    "Delhi": ("delhi", "ncr"),
    "national": ("national", "india"),
}


def _pcm(text: str) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "s.wav"
        pcm = Path(tmp) / "s.pcm"
        subprocess.run(["espeak-ng", "-v", "en-us", "-s", "140", "-w", str(wav), text], check=True, capture_output=True)
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(wav), "-ar", "48000", "-ac", "1", "-f", "s16le", str(pcm)],
            check=True,
            capture_output=True,
        )
        return pcm.read_bytes()


async def _token(name: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"{API}/api/connection-details",
            json={
                "participant_name": name,
                "device_id": str(uuid.uuid4()),
                "face_id": "cace3ef7-a4c4-425d-a8cf-a5358eb0c427",
                "voice": "af_nova",
                "anchor_name": "TINA",
                "include_headlines": True,
            },
        )
        r.raise_for_status()
        return r.json()


async def _speak(room: rtc.Room, pcm: bytes) -> None:
    source = rtc.AudioSource(48000, 1)
    track = rtc.LocalAudioTrack.create_audio_track("mic", source)
    await room.local_participant.publish_track(
        track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
    )
    silence = b"\x00" * int(48000 * 2 * 0.4)
    data = silence + pcm + b"\x00" * int(48000 * 2 * 1.3)
    chunk = 960 * 2
    for offset in range(0, len(data), chunk):
        part = data[offset : offset + chunk]
        if len(part) < chunk:
            part += b"\x00" * (chunk - len(part))
        await source.capture_frame(
            rtc.AudioFrame(part, sample_rate=48000, num_channels=1, samples_per_channel=len(part) // 2)
        )
        await asyncio.sleep(0.02)


def _hits_city(text: str, city: str) -> bool:
    blob = (text or "").lower()
    return any(n in blob for n in NEEDLES[city])


async def mock_city(city: str) -> dict:
    details = await _token(f"Mock{city}")
    room_name = details["roomName"]
    print(f"\n=== {city} room={room_name} ===")
    room = rtc.Room()
    joined = asyncio.Event()
    user_lines: list[str] = []
    agent_lines: list[str] = []
    headlines: list[str] = []

    @room.on("participant_connected")
    def _p(p: rtc.RemoteParticipant) -> None:
        if "agent" in (p.identity or "").lower():
            joined.set()

    @room.on("data_received")
    def _d(packet: rtc.DataPacket) -> None:
        topic = packet.topic or ""
        if topic not in ("genzcine_studio", "genzcine_transcript", ""):
            return
        try:
            msg = json.loads(packet.data.decode())
        except Exception:
            return
        kind = msg.get("type", "")
        if kind == "transcript":
            text = (msg.get("text") or "").strip()
            role = msg.get("role", "")
            if role == "user" and text:
                user_lines.append(text)
                print(f"  user: {text[:90]!r}")
            elif role == "agent" and text:
                agent_lines.append(text)
                print(f"  agent: {text[:90]!r}")
        elif kind == "headlines":
            print(f"  topic={msg.get('topic')!r}")
            for art in msg.get("articles") or []:
                title = art.get("title") if isinstance(art, dict) else ""
                if title:
                    headlines.append(title)
                    print(f"  headline: {title[:80]}")
        elif kind == "headline_now":
            h = msg.get("headline") if isinstance(msg.get("headline"), dict) else {}
            title = h.get("title") or ""
            if title:
                headlines.append(title)
                print(f"  now: {title[:80]}")

    await room.connect(LIVEKIT_URL, details["participantToken"])
    try:
        await asyncio.wait_for(joined.wait(), timeout=45)
        print("  agent joined, wait greeting")
        await asyncio.sleep(8)
        await _speak(room, _pcm(city))
        await asyncio.sleep(22)
    finally:
        await room.disconnect()

    local_headlines = sum(1 for t in headlines if _hits_city(t, city))
    user_hit = any(_hits_city(t, city) for t in user_lines)
    if city == "national":
        picked = user_hit and len(headlines) >= 1
    else:
        picked = user_hit and local_headlines >= 1
    return {
        "city": city,
        "room": room_name,
        "user": user_lines,
        "agent": agent_lines[:6],
        "headlines": headlines[:8],
        "local_headlines": local_headlines,
        "picked": picked,
    }


async def main() -> int:
    t0 = time.monotonic()
    reports = []
    for city in CITIES:
        reports.append(await mock_city(city))
    print("\n=== MOCK SCORE ===")
    failed = 0
    for r in reports:
        ok = r["picked"]
        failed += 0 if ok else 1
        print(
            f"{'PASS' if ok else 'FAIL'} {r['city']}: user={r['user']!r} "
            f"local_headlines={r['local_headlines']} agent_lines={len(r['agent'])}"
        )
    print(f"elapsed {time.monotonic() - t0:.0f}s")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

#!/usr/bin/env python3
"""LiveKit mock: Kokoro TTS, VAD interrupt, Mohali + Chandigarh city pick-up."""
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
KOKORO = "http://127.0.0.1:8880"
CITIES = ("Mohali", "Chandigarh")
NEEDLES = {
    "Mohali": ("mohali", "sas nagar"),
    "Chandigarh": ("chandigarh", "tricity"),
}


def _pcm(text: str, rate: int = 140) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "s.wav"
        pcm = Path(tmp) / "s.pcm"
        subprocess.run(
            ["espeak-ng", "-v", "en-us", "-s", str(rate), "-w", str(wav), text],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(wav), "-ar", "48000", "-ac", "1", "-f", "s16le", str(pcm)],
            check=True,
            capture_output=True,
        )
        return pcm.read_bytes()


async def check_kokoro() -> dict:
    out = {"health": False, "tts_ms": None, "bytes": 0, "error": ""}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            h = await client.get(f"{KOKORO}/health")
            out["health"] = h.status_code == 200 and h.json().get("status") == "ok"
            t0 = time.perf_counter()
            r = await client.post(
                f"{KOKORO}/v1/audio/speech",
                json={"input": "This is TINA with today's headlines from Mohali.", "voice": "af_nova"},
            )
            out["tts_ms"] = round((time.perf_counter() - t0) * 1000)
            out["bytes"] = len(r.content)
            if r.status_code != 200 or len(r.content) < 2000:
                out["error"] = f"tts status={r.status_code} bytes={len(r.content)}"
    except Exception as exc:
        out["error"] = str(exc)
    return out


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


class Mic:
    def __init__(self) -> None:
        self.source = rtc.AudioSource(48000, 1)
        self.published = False

    async def publish(self, room: rtc.Room) -> None:
        if self.published:
            return
        track = rtc.LocalAudioTrack.create_audio_track("mic", self.source)
        await room.local_participant.publish_track(
            track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        )
        self.published = True

    async def say(self, text: str, *, rate: int = 130, lead: float = 0.35, tail: float = 1.1) -> None:
        pcm = _pcm(text, rate)
        data = (b"\x00" * int(48000 * 2 * lead)) + pcm + (b"\x00" * int(48000 * 2 * tail))
        chunk = 960 * 2
        for offset in range(0, len(data), chunk):
            part = data[offset : offset + chunk]
            if len(part) < chunk:
                part += b"\x00" * (chunk - len(part))
            await self.source.capture_frame(
                rtc.AudioFrame(part, sample_rate=48000, num_channels=1, samples_per_channel=len(part) // 2)
            )
            await asyncio.sleep(0.02)


def _city_hit(text: str, city: str) -> bool:
    blob = (text or "").lower()
    return any(n in blob for n in NEEDLES[city])


async def mock_city(city: str) -> dict:
    details = await _token(f"Vad{city}")
    print(f"\n=== {city} room={details['roomName']} ===")
    room = rtc.Room()
    joined = asyncio.Event()
    first_audio = asyncio.Event()
    t_connect = time.perf_counter()
    t_join = None
    t_greet_audio = None
    audio_frames = 0
    audio_after_city = 0
    audio_after_interrupt = 0
    phase = "greet"
    user_lines: list[str] = []
    agent_lines: list[str] = []
    headlines: list[str] = []
    modes: list[str] = []
    t_city_done = None
    t_city_audio = None
    t_interrupt_done = None
    t_interrupt_reply = None

    @room.on("participant_connected")
    def _p(p: rtc.RemoteParticipant) -> None:
        if "agent" in (p.identity or "").lower():
            nonlocal t_join
            t_join = time.perf_counter()
            joined.set()

    @room.on("track_subscribed")
    def _t(track: rtc.Track, _pub, participant) -> None:
        if track.kind != rtc.TrackKind.KIND_AUDIO:
            return

        async def _consume() -> None:
            nonlocal audio_frames, audio_after_city, audio_after_interrupt
            nonlocal t_greet_audio, t_city_audio, t_interrupt_reply
            stream = rtc.AudioStream(track)
            async for _frame in stream:
                audio_frames += 1
                if phase == "greet" and t_greet_audio is None:
                    t_greet_audio = time.perf_counter()
                    first_audio.set()
                elif phase == "city":
                    audio_after_city += 1
                    if t_city_audio is None:
                        t_city_audio = time.perf_counter()
                elif phase == "interrupt":
                    audio_after_interrupt += 1
                    if t_interrupt_reply is None:
                        t_interrupt_reply = time.perf_counter()

        asyncio.create_task(_consume())

    @room.on("data_received")
    def _d(packet: rtc.DataPacket) -> None:
        if (packet.topic or "") not in ("genzcine_studio", "genzcine_transcript", ""):
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
                    print(f"  headline: {title[:78]}")
        elif kind == "headline_now":
            h = msg.get("headline") if isinstance(msg.get("headline"), dict) else {}
            title = h.get("title") or ""
            if title:
                headlines.append(title)
                print(f"  now: {title[:78]}")
        elif kind == "studio_state" and msg.get("mode"):
            modes.append(msg["mode"])
            print(f"  mode={msg['mode']}")

    await room.connect(LIVEKIT_URL, details["participantToken"])
    mic = Mic()
    try:
        await asyncio.wait_for(joined.wait(), timeout=45)
        await mic.publish(room)
        print(f"  agent joined +{(t_join - t_connect):.2f}s")
        try:
            await asyncio.wait_for(first_audio.wait(), timeout=15)
            print(f"  greeting TTS audio +{(t_greet_audio - t_join):.2f}s after join")
        except asyncio.TimeoutError:
            print("  FAIL greeting TTS audio missing")
        await asyncio.sleep(2.5)

        phase = "city"
        spoken = "SAS Nagar" if city == "Mohali" else "Chandigarh"
        print(f"  speaking city {spoken!r} (want {city})")
        await mic.say(spoken, rate=125)
        t_city_done = time.perf_counter()
        await asyncio.sleep(16)

        local_n = sum(1 for t in headlines if _city_hit(t, city))
        print(f"  city local headlines={local_n} audio_frames_after_city={audio_after_city}")

        phase = "interrupt"
        print("  interrupting with follow-up")
        await mic.say("Wait, tell me more about that story please.", rate=145)
        t_interrupt_done = time.perf_counter()
        await asyncio.sleep(14)
    finally:
        await room.disconnect()

    user_hit = any(_city_hit(t, city) for t in user_lines)
    local_n = sum(1 for t in headlines if _city_hit(t, city))
    follow_up = any(
        "more" in t.lower() or "story" in t.lower() or "wait" in t.lower() for t in user_lines
    )
    replied = any(
        i for i, t in enumerate(agent_lines) if i > 0 and "which indian city" not in t.lower()
    )
    greet_s = (t_greet_audio - t_join) if t_greet_audio and t_join else None
    city_tts_s = (t_city_audio - t_city_done) if t_city_audio and t_city_done else None
    interrupt_s = (t_interrupt_reply - t_interrupt_done) if t_interrupt_reply and t_interrupt_done else None
    checks = {
        "agent_joined": t_join is not None,
        "greeting_tts": greet_s is not None and greet_s < 12,
        "city_stt": user_hit,
        "city_headlines": local_n >= 1,
        "bulletin_tts": audio_after_city >= 20,
        "vad_interrupt": follow_up or "conversation" in modes,
        "interrupt_reply_audio": audio_after_interrupt >= 10,
    }
    print(
        f"  timings greet={greet_s} city_tts={city_tts_s} interrupt_audio={interrupt_s} "
        f"modes={modes} checks={checks}"
    )
    return {
        "city": city,
        "room": details["roomName"],
        "user": user_lines,
        "local_headlines": local_n,
        "modes": modes,
        "greet_s": greet_s,
        "city_tts_s": city_tts_s,
        "interrupt_s": interrupt_s,
        "checks": checks,
        "audio_frames": audio_frames,
        "replied": replied,
    }


async def main() -> int:
    kokoro = await check_kokoro()
    print(
        f"KOKORO health={kokoro['health']} tts_ms={kokoro['tts_ms']} "
        f"bytes={kokoro['bytes']} err={kokoro['error']!r}"
    )
    reports = []
    failed = 0
    if not kokoro["health"] or kokoro["bytes"] < 2000:
        failed += 1
    for city in CITIES:
        reports.append(await mock_city(city))
    print("\n=== TTS / VAD / CITY SCORE ===")
    print(f"{'PASS' if kokoro['health'] and kokoro['bytes'] >= 2000 else 'FAIL'} Kokoro TTS")
    for r in reports:
        bad = [k for k, ok in r["checks"].items() if not ok]
        ok = not bad
        failed += 0 if ok else 1
        print(
            f"{'PASS' if ok else 'FAIL'} {r['city']}: local={r['local_headlines']} "
            f"greet={r['greet_s']} city_tts={r['city_tts_s']} "
            f"user={r['user'][:3]!r} fail={bad}"
        )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

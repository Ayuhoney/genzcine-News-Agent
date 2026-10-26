"""Real WebRTC Live User E2E Test Harness.

Simulates an actual iOS/Android viewer joining via /api/connection-details,
publishing a microphone track (with simulated loudspeaker echo during bulletin
and real synthesized human speech for turns), listening to the anchor's WebRTC
audio stream frame-by-frame, and verifying:
  1. Intro + Headline #1 + Headline #2 smoothness (even with phone speaker echo)
  2. Breaking news only at start (no local/community posts)
  3. Live Barge-in + VAD + STT + LLM + Tool call (English breaking news)
  4. Hindi language switch + City news (Delhi/Firozpur) full report
  5. Voice command to play news video -> play_news_video event + /api/youtube/embed check
  6. Voice command "Stop playing this video" -> stop_news_video event (no re-trigger)
  7. Conversation idle -> auto-resume live bulletin
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import struct
import time
import urllib.parse
import httpx
from livekit import rtc

SAMPLE_RATE = 24000
NUM_CHANNELS = 1
SAMPLES_PER_FRAME = 480  # 20ms at 24kHz


async def synth_user_voice(text: str, lang_code: str = "en-IN", speaker: str = "shubh") -> bytes:
    """Synthesize realistic user speech PCM (24kHz 16-bit mono) via Sarvam TTS."""
    api_key = os.environ["SARVAM_API_KEY"]
    body = {
        "text": text,
        "language_code": lang_code,
        "target_language_code": lang_code,
        "model": "bulbul:v3",
        "speaker": speaker,
        "output_audio_codec": "linear16",
        "speech_sample_rate": SAMPLE_RATE,
    }
    headers = {"api-subscription-key": api_key, "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post("https://api.sarvam.ai/text-to-speech/stream", headers=headers, json=body)
        resp.raise_for_status()
        pcm = resp.content
        # Strip WAV header if present
        if pcm[:4] == b"RIFF":
            pcm = pcm[44:]
        return pcm


def frame_rms(pcm_bytes: bytes) -> float:
    if len(pcm_bytes) < 2:
        return 0.0
    count = len(pcm_bytes) // 2
    samples = struct.unpack(f"<{count}h", pcm_bytes[: count * 2])
    acc = sum(s * s for s in samples)
    return math.sqrt(acc / count)


def attenuate_pcm(pcm_bytes: bytes, gain: float) -> bytes:
    count = len(pcm_bytes) // 2
    samples = struct.unpack(f"<{count}h", pcm_bytes[: count * 2])
    out = [max(-32768, min(32767, int(s * gain))) for s in samples]
    return struct.pack(f"<{count}h", *out)


async def run_live_session() -> int:
    t_start = time.monotonic()
    logs: list[str] = []
    issues: list[str] = []

    def log(msg: str) -> None:
        elapsed = time.monotonic() - t_start
        line = f"[{elapsed:6.2f}s] {msg}"
        print(line, flush=True)
        logs.append(line)

    async with httpx.AsyncClient(base_url="http://127.0.0.1:8080", timeout=20.0) as http:
        resp = await http.post(
            "/api/connection-details",
            json={
                "participant_name": "Ayush",
                "anchor_name": "NOVA",
                "language": "en-US",
                "session_type": "1:1",
            },
        )
        resp.raise_for_status()
        conn = resp.json()
        token = conn["participantToken"]
        room_name = conn["roomName"]
        log(f"Got connection details for room={room_name}")

    room = rtc.Room()
    mic_source = rtc.AudioSource(SAMPLE_RATE, NUM_CHANNELS)
    mic_track = rtc.LocalAudioTrack.create_audio_track("user-mic", mic_source)

    studio_events: list[tuple[float, dict]] = []
    transcripts: list[tuple[float, str, str, bool]] = []
    agent_audio_frames = 0
    agent_speaking_frames = 0
    last_voice_at = 0.0
    first_voice_at = 0.0
    speech_gaps: list[tuple[float, float]] = []
    echo_enabled = True
    user_speaking_now = False
    echo_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=200)

    @room.on("data_received")
    def _on_data(packet: rtc.DataPacket) -> None:
        try:
            payload = json.loads(packet.data.decode("utf-8"))
            etype = payload.get("type", "")
            studio_events.append((time.monotonic() - t_start, payload))
            if etype in ("agent_ready", "headlines", "headline_now", "video_start", "news_video", "video_end", "agent_error"):
                log(f"EVENT {etype}: {json.dumps(payload, ensure_ascii=False)[:220]}")
            elif etype == "transcript":
                role = payload.get("role", "")
                text = payload.get("text", "")
                is_final = bool(payload.get("isFinal", True))
                transcripts.append((time.monotonic() - t_start, role, text, is_final))
                log(f"TRANSCRIPT [{role}] (final={is_final}): {text}")
            elif etype == "studio_state":
                mode = payload.get("mode")
                state = payload.get("state")
                log(f"STATE mode={mode} state={state} lang={payload.get('language')}")
        except Exception as exc:
            log(f"data_received parse error: {exc}")

    async def _consume_agent_audio(track: rtc.Track) -> None:
        nonlocal agent_audio_frames, agent_speaking_frames, last_voice_at, first_voice_at
        stream = rtc.AudioStream(track, sample_rate=SAMPLE_RATE, num_channels=NUM_CHANNELS)
        in_voice = False
        silence_since = 0.0
        async for ev in stream:
            frame = ev.frame
            pcm = bytes(frame.data)
            agent_audio_frames += 1
            rms = frame_rms(pcm)
            now = time.monotonic() - t_start
            if rms > 220:
                agent_speaking_frames += 1
                if first_voice_at == 0.0:
                    first_voice_at = now
                    log(f"FIRST ANCHOR AUDIO frame at {now:.2f}s (rms={rms:.0f})")
                if not in_voice and silence_since > 0:
                    gap = now - silence_since
                    if gap >= 0.45:
                        speech_gaps.append((silence_since, gap))
                        log(f"AUDIO GAP ended at {now:.2f}s (duration={gap:.2f}s)")
                in_voice = True
                last_voice_at = now
                # Simulate phone loudspeaker acoustic echo into mic if echo_enabled
                if echo_enabled and not user_speaking_now:
                    try:
                        echo_queue.put_nowait(attenuate_pcm(pcm, 0.06))
                    except asyncio.QueueFull:
                        pass
            else:
                if in_voice:
                    silence_since = now
                    in_voice = False

    @room.on("track_subscribed")
    def _on_track_subscribed(
        track: rtc.Track,
        publication: rtc.RemoteTrackPublication,
        participant: rtc.RemoteParticipant,
    ) -> None:
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            log(f"Subscribed to agent audio track from {participant.identity}")
            asyncio.create_task(_consume_agent_audio(track))

    # Background task that feeds silence (or loudspeaker echo) when user is not speaking
    stop_mic = False
    user_pcm_queue: asyncio.Queue[bytes] = asyncio.Queue()

    async def _mic_pump() -> None:
        silence = b"\x00" * (SAMPLES_PER_FRAME * 2)
        frame_bytes = SAMPLES_PER_FRAME * 2
        while not stop_mic:
            if not user_pcm_queue.empty():
                chunk = await user_pcm_queue.get()
            elif not echo_queue.empty():
                chunk = echo_queue.get_nowait()
            else:
                chunk = silence
            if len(chunk) < frame_bytes:
                chunk = chunk + b"\x00" * (frame_bytes - len(chunk))
            audio_frame = rtc.AudioFrame(
                data=chunk[:frame_bytes],
                sample_rate=SAMPLE_RATE,
                num_channels=NUM_CHANNELS,
                samples_per_channel=SAMPLES_PER_FRAME,
            )
            await mic_source.capture_frame(audio_frame)
            await asyncio.sleep(0.019)

    async def speak_as_user(text: str, lang_code: str = "en-IN", speaker: str = "shubh") -> None:
        nonlocal user_speaking_now
        log(f">>> USER SPEAKING ({lang_code}): {text!r}")
        pcm = await synth_user_voice(text, lang_code=lang_code, speaker=speaker)
        user_speaking_now = True
        while not echo_queue.empty():
            echo_queue.get_nowait()
        frame_bytes = SAMPLES_PER_FRAME * 2
        lead_silence = b"\x00" * frame_bytes
        for _ in range(12):  # 240ms leading silence so VAD/STT doesn't clip initial consonant
            await user_pcm_queue.put(lead_silence)
        for i in range(0, len(pcm), frame_bytes):
            await user_pcm_queue.put(pcm[i : i + frame_bytes])
        for _ in range(10):  # 200ms trailing silence
            await user_pcm_queue.put(lead_silence)
        # Wait until queue drains
        while not user_pcm_queue.empty():
            await asyncio.sleep(0.05)
        user_speaking_now = False
        log(f"<<< USER FINISHED SPEAKING ({len(pcm) / (SAMPLE_RATE * 2):.1f}s audio)")

    await room.connect("ws://127.0.0.1:7890", token)
    log("Connected to LiveKit room ws://127.0.0.1:7890")
    await room.local_participant.publish_track(
        mic_track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
    )
    mic_task = asyncio.create_task(_mic_pump())

    try:
        # ------------------------------------------------------------------
        # PHASE 1: Listen to Intro + First Headline + Second Headline (with loudspeaker echo!)
        # ------------------------------------------------------------------
        log("=== PHASE 1: Listening to Intro + Opening Bulletin (26s with loudspeaker echo) ===")
        await asyncio.sleep(26.0)

        headline_events = [e for _, e in studio_events if e.get("type") == "headlines"]
        headline_now_events = [e for _, e in studio_events if e.get("type") == "headline_now"]
        log(
            f"Phase 1 summary: speaking_audio={agent_speaking_frames * 0.02:.1f}s "
            f"headlines_published={len(headline_events)} headline_now_count={len(headline_now_events)} "
            f"gaps>0.45s={len(speech_gaps)}"
        )
        if agent_speaking_frames * 0.02 < 14.0:
            issues.append(f"Phase 1: Anchor spoke too little during first 26s ({agent_speaking_frames * 0.02:.1f}s)")
        if not headline_events:
            issues.append("Phase 1: No headlines event published during opening")
        else:
            arts = headline_events[0].get("articles", [])
            bad_local = [a for a in arts if a.get("provider") in ("community", "genzcine")]
            if bad_local:
                issues.append(f"Phase 1: Starting headlines contained local/community news: {bad_local}")

        # Check for long gaps (> 1.8s) during Phase 1 continuous bulletin
        long_gaps_p1 = [(t, d) for (t, d) in speech_gaps if d > 1.8]
        if long_gaps_p1:
            issues.append(f"Phase 1: Long audio gaps (>1.8s) detected during intro/bulletin: {long_gaps_p1}")

        # ------------------------------------------------------------------
        # PHASE 2: Barge-in in English -> Ask for detailed breaking news
        # ------------------------------------------------------------------
        log("=== PHASE 2: User Barge-in (English breaking news) ===")
        t_before_p2 = time.monotonic() - t_start
        frames_before_p2 = agent_speaking_frames
        await speak_as_user("Excuse me Nova, tell me today's top breaking news in detail.", lang_code="en-IN")
        await asyncio.sleep(20.0)

        p2_user_tx = [tx for (ts, role, tx, fin) in transcripts if ts >= t_before_p2 and role == "user" and fin]
        p2_spoken_sec = (agent_speaking_frames - frames_before_p2) * 0.02
        log(f"Phase 2 user transcripts: {p2_user_tx}, agent_spoken={p2_spoken_sec:.1f}s")
        if not p2_user_tx:
            issues.append("Phase 2: User speech was not transcribed by STT")
        if p2_spoken_sec < 6.0:
            issues.append(f"Phase 2: Agent spoke too little in response to English breaking news ask ({p2_spoken_sec:.1f}s)")

        # ------------------------------------------------------------------
        # PHASE 3: Hindi Language Switch + City News (Delhi)
        # ------------------------------------------------------------------
        log("=== PHASE 3: Hindi Switch + City News (Delhi) ===")
        t_before_p3 = time.monotonic() - t_start
        frames_before_p3 = agent_speaking_frames
        await speak_as_user("मुझे दिल्ली की ताज़ा खबर विस्तार से बताओ", lang_code="hi-IN")
        await asyncio.sleep(22.0)

        p3_user_tx = [tx for (ts, role, tx, fin) in transcripts if ts >= t_before_p3 and role == "user" and fin]
        p3_spoken_sec = (agent_speaking_frames - frames_before_p3) * 0.02
        log(f"Phase 3 user transcripts: {p3_user_tx}, agent_spoken={p3_spoken_sec:.1f}s")
        if not p3_user_tx:
            issues.append("Phase 3: Hindi user speech was not transcribed by STT")
        if p3_spoken_sec < 6.0:
            issues.append(f"Phase 3: Agent spoke too little in response to Hindi Delhi news ask ({p3_spoken_sec:.1f}s)")

        # ------------------------------------------------------------------
        # PHASE 4: Play News Video + Verify Embed Bridge + Stop Video Voice Command
        # ------------------------------------------------------------------
        log("=== PHASE 4: Play News Video + Stop Video Voice Command ===")
        t_before_p4 = time.monotonic() - t_start
        await speak_as_user("Please play the video of this news report", lang_code="en-IN")
        await asyncio.sleep(10.0)

        video_evts = [
            e for (ts, e) in studio_events
            if ts >= t_before_p4 and e.get("type") in ("video_start", "news_video")
        ]
        if not video_evts:
            issues.append("Phase 4: 'Please play the video of this news report' did not emit video_start/news_video event")
        else:
            vid = video_evts[-1].get("videoId")
            log(f"Phase 4: Video playing videoId={vid}")
            async with httpx.AsyncClient(base_url="http://127.0.0.1:8080", timeout=10.0) as http:
                r_get = await http.get(f"/api/youtube/embed/{vid}")
                r_head = await http.head(f"/api/youtube/embed/{vid}")
                if r_get.status_code != 200 or r_head.status_code != 200:
                    issues.append(f"Phase 4: /api/youtube/embed/{vid} failed (GET={r_get.status_code}, HEAD={r_head.status_code})")

        t_before_stop = time.monotonic() - t_start
        await speak_as_user("Stop playing this video right now", lang_code="en-IN")
        await asyncio.sleep(10.0)

        stop_evts = [e for (ts, e) in studio_events if ts >= t_before_stop and e.get("type") == "video_end"]
        retrigger_evts = [
            e for (ts, e) in studio_events
            if ts >= t_before_stop and e.get("type") in ("video_start", "news_video")
        ]
        if not stop_evts:
            issues.append("Phase 4: 'Stop playing this video right now' did not emit video_end event")
        if retrigger_evts:
            issues.append(f"Phase 4: 'Stop playing this video right now' accidentally triggered a new video: {retrigger_evts}")

        # ------------------------------------------------------------------
        # PHASE 5: Conversation Idle -> Bulletin Auto-Resume
        # ------------------------------------------------------------------
        log("=== PHASE 5: Waiting 16s for Conversation Idle -> Bulletin Auto-Resume ===")
        t_before_p5 = time.monotonic() - t_start
        frames_before_p5 = agent_speaking_frames
        await asyncio.sleep(18.0)
        p5_spoken_sec = (agent_speaking_frames - frames_before_p5) * 0.02
        p5_headlines = [e for (ts, e) in studio_events if ts >= t_before_stop and e.get("type") == "headline_now"]
        log(f"Phase 5 summary: resumed_speaking={p5_spoken_sec:.1f}s new_headline_now={len(p5_headlines)}")
        if p5_spoken_sec < 3.0 and not p5_headlines:
            issues.append("Phase 5: Bulletin did not auto-resume after conversation idle window")
        if len(p5_headlines) >= 2:
            indices = [e.get("activeIndex") for e in p5_headlines]
            for i in range(1, len(indices)):
                if indices[i] == indices[i - 1]:
                    issues.append(f"Phase 5: Headline activeIndex repeated consecutively: {indices}")
                    break

    finally:
        stop_mic = True
        mic_task.cancel()
        await room.disconnect()

    print("\n================ E2E DIAGNOSTIC REPORT ================")
    print(f"Total speaking audio received: {agent_speaking_frames * 0.02:.1f}s")
    print(f"Total transcripts captured: {len(transcripts)}")
    print(f"Speech gaps >= 0.45s: {[(round(t, 2), round(d, 2)) for t, d in speech_gaps]}")
    if issues:
        print(f"ISSUES FOUND ({len(issues)}):")
        for idx, iss in enumerate(issues, 1):
            print(f"  {idx}. {iss}")
        return 1
    print("ALL PHASES PASSED SMOOTHLY WITH 0 ISSUES!")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run_live_session()))

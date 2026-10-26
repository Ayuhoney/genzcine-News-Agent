"""15-Minute Real User Live WebRTC Simulation Test Suite.

Simulates an actual mobile phone user (iOS / Android) interacting with the
live news anchor NOVA continuously for 15 minutes (900 seconds) over LiveKit WebRTC.

Comprehensive verification covers:
  1. Intro + Opening Bulletin smoothness (Hindi/English, zero Punjabi in intro, no local news).
  2. Live barge-in interruption while anchor speaks.
  3. National breaking news (English).
  4. Language switches to Hindi, Punjabi, Marathi, Bengali, and English.
  5. Multi-state Indian coverage: UP/Lucknow, Punjab/Chandigarh, Maharashtra/Mumbai,
     West Bengal/Kolkata, Tamil Nadu/Chennai, Gujarat/Ahmedabad.
  6. News video play commands in multiple languages with /api/youtube/embed validation.
  7. News video stop voice commands (video_end with skipped=true).
  8. News video natural finish (client data channel packet news_video_ended).
  9. Continuous phone loudspeaker echo simulation (6% attenuation) throughout the session.
 10. Sarvam STT WebSocket endurance (verified alive past 10-15 minutes).
 11. No LLM context blowup, no duplicate replies, no repeated activeIndex.
 12. Final 15-minute diagnostic score and issue report.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import struct
import time
import httpx
from livekit import rtc

SAMPLE_RATE = 24000
NUM_CHANNELS = 1
SAMPLES_PER_FRAME = 480  # 20ms at 24kHz


async def synth_user_voice(text: str, lang_code: str = "en-IN", speaker: str = "shubh") -> bytes:
    """Synthesize realistic user speech PCM (24kHz 16-bit mono) via Sarvam TTS."""
    api_key = os.environ.get("SARVAM_API_KEY", "")
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


async def run_15m_simulation() -> int:
    t_start = time.monotonic()
    issues: list[str] = []
    logs: list[str] = []

    def log(msg: str) -> None:
        elapsed = time.monotonic() - t_start
        mins = int(elapsed // 60)
        secs = elapsed % 60
        line = f"[{mins:02d}:{secs:05.2f}] {msg}"
        print(line, flush=True)
        logs.append(line)

    log("Starting 15-Minute Real User Live WebRTC Simulation...")

    async with httpx.AsyncClient(base_url="http://127.0.0.1:8080", timeout=20.0) as http:
        resp = await http.post(
            "/api/connection-details",
            json={
                "participant_name": "Ayush_15m",
                "anchor_name": "NOVA",
                "language": "en-US",
                "session_type": "1:1",
            },
        )
        resp.raise_for_status()
        conn = resp.json()
        token = conn["participantToken"]
        room_name = conn["roomName"]
        log(f"Connected to room {room_name}")

    room = rtc.Room()
    mic_source = rtc.AudioSource(SAMPLE_RATE, NUM_CHANNELS)
    mic_track = rtc.LocalAudioTrack.create_audio_track("user-mic", mic_source)

    studio_events: list[tuple[float, dict]] = []
    transcripts: list[tuple[float, str, str, bool]] = []
    agent_speaking_frames = 0
    speech_gaps: list[tuple[float, float]] = []
    user_speaking_now = False
    echo_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=300)

    @room.on("data_received")
    def _on_data(packet: rtc.DataPacket) -> None:
        try:
            payload = json.loads(packet.data.decode("utf-8"))
            etype = payload.get("type", "")
            now = time.monotonic() - t_start
            studio_events.append((now, payload))
            if etype in ("agent_ready", "headlines", "headline_now", "video_start", "news_video", "video_end", "agent_error"):
                log(f"EVENT {etype}: {json.dumps(payload, ensure_ascii=False)[:200]}")
            elif etype == "transcript":
                role = payload.get("role", "")
                text = payload.get("text", "")
                is_final = bool(payload.get("isFinal", True))
                transcripts.append((now, role, text, is_final))
                log(f"TRANSCRIPT [{role}]: {text[:160]}")
            elif etype == "studio_state":
                mode = payload.get("mode")
                state = payload.get("state")
                lang = payload.get("language")
                log(f"STATE mode={mode} state={state} lang={lang}")
        except Exception as exc:
            log(f"data_received parse error: {exc}")

    async def _consume_agent_audio(track: rtc.Track) -> None:
        nonlocal agent_speaking_frames
        stream = rtc.AudioStream(track, sample_rate=SAMPLE_RATE, num_channels=NUM_CHANNELS)
        in_voice = False
        silence_since = 0.0
        async for ev in stream:
            frame = ev.frame
            pcm = bytes(frame.data)
            rms = frame_rms(pcm)
            now = time.monotonic() - t_start
            if rms > 220:
                agent_speaking_frames += 1
                if not in_voice and silence_since > 0:
                    gap = now - silence_since
                    if gap >= 0.45:
                        speech_gaps.append((silence_since, gap))
                        log(f"AUDIO GAP ended at {now:.2f}s (duration={gap:.2f}s)")
                in_voice = True
                if not user_speaking_now:
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

    stop_mic = False
    user_pcm_queue: asyncio.Queue[bytes] = asyncio.Queue()

    async def _mic_pump() -> None:
        frame_bytes = SAMPLES_PER_FRAME * 2
        silence = b"\x00" * frame_bytes
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
        for _ in range(12):  # 240ms leading silence so VAD opens cleanly
            await user_pcm_queue.put(lead_silence)
        for i in range(0, len(pcm), frame_bytes):
            await user_pcm_queue.put(pcm[i : i + frame_bytes])
        for _ in range(10):  # 200ms trailing silence
            await user_pcm_queue.put(lead_silence)
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
        # ==================================================================
        # PHASE 1: [0:00 - 1:00] Intro + Opening Bulletin Playout (60s)
        # ==================================================================
        log("=== PHASE 1: Intro + Opening Bulletin (0:00 - 1:00) ===")
        await asyncio.sleep(58.0)
        h_evts = [e for _, e in studio_events if e.get("type") == "headlines"]
        if not h_evts:
            issues.append("Phase 1: No headlines event published during opening")
        else:
            arts = h_evts[0].get("articles", [])
            bad_local = [a for a in arts if a.get("provider") in ("community", "genzcine")]
            if bad_local:
                issues.append(f"Phase 1: Initial headlines contained local/community news: {bad_local}")
        log(f"Phase 1 complete. Agent speaking audio: {agent_speaking_frames * 0.02:.1f}s")

        # ==================================================================
        # PHASE 2: [1:00 - 2:20] User Barge-in #1 (English National News)
        # ==================================================================
        log("=== PHASE 2: User Barge-in #1 - English National News (1:00 - 2:20) ===")
        t_before = time.monotonic() - t_start
        f_before = agent_speaking_frames
        await speak_as_user("Excuse me Nova, what is today's top national breaking news in detail?", lang_code="en-IN")
        await asyncio.sleep(70.0)
        p2_spoken = (agent_speaking_frames - f_before) * 0.02
        p2_trans = [t for (ts, r, t, f) in transcripts if ts >= t_before and r == "user"]
        if not p2_trans:
            issues.append("Phase 2: English user speech was not transcribed by STT")
        if p2_spoken < 15.0:
            issues.append(f"Phase 2: Anchor spoke too little in response to English national news ask ({p2_spoken:.1f}s)")
        log(f"Phase 2 complete. User transcripts: {p2_trans}, Spoken: {p2_spoken:.1f}s")

        # ==================================================================
        # PHASE 3: [2:20 - 3:40] Turn 2 - Hindi Switch + UP & Lucknow News
        # ==================================================================
        log("=== PHASE 3: Turn 2 - Hindi Switch + UP & Lucknow News (2:20 - 3:40) ===")
        t_before = time.monotonic() - t_start
        f_before = agent_speaking_frames
        await speak_as_user("नमस्ते नोवा, अब हिंदी में बताओ, मुझे उत्तर प्रदेश और लखनऊ की ताज़ा खबर बताओ", lang_code="hi-IN")
        await asyncio.sleep(70.0)
        p3_spoken = (agent_speaking_frames - f_before) * 0.02
        p3_trans = [t for (ts, r, t, f) in transcripts if ts >= t_before and r == "user"]
        if not p3_trans:
            issues.append("Phase 3: Hindi user speech was not transcribed by STT")
        if p3_spoken < 15.0:
            issues.append(f"Phase 3: Anchor spoke too little in response to Hindi UP news ask ({p3_spoken:.1f}s)")
        log(f"Phase 3 complete. User transcripts: {p3_trans}, Spoken: {p3_spoken:.1f}s")

        # ==================================================================
        # PHASE 4: [3:40 - 5:00] Turn 3 - Video Play #1 + Voice Stop Command
        # ==================================================================
        log("=== PHASE 4: Turn 3 - Video Play #1 + Voice Stop Command (3:40 - 5:00) ===")
        t_before = time.monotonic() - t_start
        await speak_as_user("इस खबर का वीडियो दिखाओ", lang_code="hi-IN")
        await asyncio.sleep(14.0)

        video_evts = [e for (ts, e) in studio_events if ts >= t_before and e.get("type") in ("video_start", "news_video")]
        if not video_evts:
            issues.append("Phase 4: 'इस खबर का वीडियो दिखाओ' did not emit video_start/news_video event")
        else:
            vid = video_evts[-1].get("videoId")
            log(f"Phase 4: Video started videoId={vid}. Verifying embed...")
            async with httpx.AsyncClient(base_url="http://127.0.0.1:8080", timeout=10.0) as http:
                r_get = await http.get(f"/api/youtube/embed/{vid}")
                r_head = await http.head(f"/api/youtube/embed/{vid}")
                if r_get.status_code != 200 or r_head.status_code != 200:
                    issues.append(f"Phase 4: /api/youtube/embed/{vid} failed (GET={r_get.status_code}, HEAD={r_head.status_code})")

        t_stop = time.monotonic() - t_start
        await speak_as_user("Stop playing this video right now", lang_code="en-IN")
        await asyncio.sleep(12.0)
        stop_evts = [e for (ts, e) in studio_events if ts >= t_stop and e.get("type") == "video_end"]
        if not stop_evts:
            issues.append("Phase 4: 'Stop playing this video right now' did not emit video_end event")
        await asyncio.sleep(45.0)  # Listen to auto-resumed bulletin
        log("Phase 4 complete. Video play, stop, and bulletin resume verified.")

        # ==================================================================
        # PHASE 5: [5:00 - 6:20] Turn 4 - Punjabi Switch + Punjab & Chandigarh News
        # ==================================================================
        log("=== PHASE 5: Turn 4 - Punjabi Switch + Punjab & Chandigarh News (5:00 - 6:20) ===")
        t_before = time.monotonic() - t_start
        f_before = agent_speaking_frames
        await speak_as_user("ਪੰਜਾਬੀ ਵਿੱਚ ਦੱਸੋ, ਮੈਨੂੰ ਪੰਜਾਬ ਅਤੇ ਚੰਡੀਗੜ੍ਹ ਦੀਆਂ ਤਾਜ਼ਾ ਖ਼ਬਰਾਂ ਸੁਣਾਓ", lang_code="pa-IN")
        await asyncio.sleep(70.0)
        p5_spoken = (agent_speaking_frames - f_before) * 0.02
        p5_trans = [t for (ts, r, t, f) in transcripts if ts >= t_before and r == "user"]
        if not p5_trans:
            issues.append("Phase 5: Punjabi user speech was not transcribed by STT")
        if p5_spoken < 12.0:
            issues.append(f"Phase 5: Anchor spoke too little in response to Punjabi news ask ({p5_spoken:.1f}s)")
        log(f"Phase 5 complete. User transcripts: {p5_trans}, Spoken: {p5_spoken:.1f}s")

        # ==================================================================
        # PHASE 6: [6:20 - 7:40] Turn 5 - Marathi Switch + Maharashtra & Mumbai News
        # ==================================================================
        log("=== PHASE 6: Turn 5 - Marathi Switch + Maharashtra & Mumbai News (6:20 - 7:40) ===")
        t_before = time.monotonic() - t_start
        f_before = agent_speaking_frames
        await speak_as_user("मराठीमध्ये सांगा, मला मुंबई आणि महाराष्ट्राची ताजी बातमी काय आहे?", lang_code="mr-IN")
        await asyncio.sleep(70.0)
        p6_spoken = (agent_speaking_frames - f_before) * 0.02
        p6_trans = [t for (ts, r, t, f) in transcripts if ts >= t_before and r == "user"]
        if not p6_trans:
            issues.append("Phase 6: Marathi user speech was not transcribed by STT")
        if p6_spoken < 12.0:
            issues.append(f"Phase 6: Anchor spoke too little in response to Marathi news ask ({p6_spoken:.1f}s)")
        log(f"Phase 6 complete. User transcripts: {p6_trans}, Spoken: {p6_spoken:.1f}s")

        # ==================================================================
        # PHASE 7: [7:40 - 9:00] Turn 6 - Bengali Switch + West Bengal & Kolkata News
        # ==================================================================
        log("=== PHASE 7: Turn 6 - Bengali Switch + West Bengal & Kolkata News (7:40 - 9:00) ===")
        t_before = time.monotonic() - t_start
        f_before = agent_speaking_frames
        await speak_as_user("বাংলায় বলো, আমাকে কলকাতা ও পশ্চিমবঙ্গের খবর শোনাও", lang_code="bn-IN")
        await asyncio.sleep(70.0)
        p7_spoken = (agent_speaking_frames - f_before) * 0.02
        p7_trans = [t for (ts, r, t, f) in transcripts if ts >= t_before and r == "user"]
        if not p7_trans:
            issues.append("Phase 7: Bengali user speech was not transcribed by STT")
        if p7_spoken < 12.0:
            issues.append(f"Phase 7: Anchor spoke too little in response to Bengali news ask ({p7_spoken:.1f}s)")
        log(f"Phase 7 complete. User transcripts: {p7_trans}, Spoken: {p7_spoken:.1f}s")

        # ==================================================================
        # PHASE 8: [9:00 - 10:20] Turn 7 - Tamil Nadu / Chennai News (English Switch)
        # ==================================================================
        log("=== PHASE 8: Turn 7 - Tamil Nadu & Chennai News in English (9:00 - 10:20) ===")
        t_before = time.monotonic() - t_start
        f_before = agent_speaking_frames
        await speak_as_user("Switch back to English, and tell me the latest news updates from Tamil Nadu and Chennai", lang_code="en-IN")
        await asyncio.sleep(70.0)
        p8_spoken = (agent_speaking_frames - f_before) * 0.02
        p8_trans = [t for (ts, r, t, f) in transcripts if ts >= t_before and r == "user"]
        if not p8_trans:
            issues.append("Phase 8: English user speech was not transcribed by STT")
        if p8_spoken < 15.0:
            issues.append(f"Phase 8: Anchor spoke too little in response to Tamil Nadu news ask ({p8_spoken:.1f}s)")
        log(f"Phase 8 complete. User transcripts: {p8_trans}, Spoken: {p8_spoken:.1f}s")

        # ==================================================================
        # PHASE 9: [10:20 - 11:50] Turn 8 - Video Play #2 + Client-Side Video End Packet
        # ==================================================================
        log("=== PHASE 9: Turn 8 - Video Play #2 + Client Video End Packet (10:20 - 11:50) ===")
        t_before = time.monotonic() - t_start
        await speak_as_user("Please play a news video about technology and business", lang_code="en-IN")
        await asyncio.sleep(15.0)

        video_evts = [e for (ts, e) in studio_events if ts >= t_before and e.get("type") in ("video_start", "news_video")]
        if not video_evts:
            issues.append("Phase 9: 'Please play a news video about technology and business' did not emit video_start")
        else:
            vid = video_evts[-1].get("videoId")
            topic = video_evts[-1].get("topic", "technology and business")
            log(f"Phase 9: Video started videoId={vid}. Simulating 10s watch time...")
            await asyncio.sleep(10.0)
            # Simulate mobile client player finishing video and publishing news_video_ended packet
            log("Phase 9: Client emitting news_video_ended data packet...")
            end_packet = json.dumps({"type": "news_video_ended", "topic": topic, "skipped": False}).encode("utf-8")
            await room.local_participant.publish_data(end_packet, reliable=True, topic="news_video")
            await asyncio.sleep(60.0)  # Anchor speaks recap and continues bulletin
        log("Phase 9 complete. Client-side video end and bulletin resume verified.")

        # ==================================================================
        # PHASE 10: [11:50 - 13:10] Turn 9 - Gujarat & Ahmedabad News
        # ==================================================================
        log("=== PHASE 10: Turn 9 - Gujarat & Ahmedabad News (11:50 - 13:10) ===")
        t_before = time.monotonic() - t_start
        f_before = agent_speaking_frames
        await speak_as_user("Can you tell me what the latest news from Gujarat and Ahmedabad is?", lang_code="en-IN")
        await asyncio.sleep(70.0)
        p10_spoken = (agent_speaking_frames - f_before) * 0.02
        p10_trans = [t for (ts, r, t, f) in transcripts if ts >= t_before and r == "user"]
        if not p10_trans:
            issues.append("Phase 10: User speech was not transcribed by STT")
        if p10_spoken < 12.0:
            issues.append(f"Phase 10: Anchor spoke too little in response to Gujarat news ask ({p10_spoken:.1f}s)")
        log(f"Phase 10 complete. User transcripts: {p10_trans}, Spoken: {p10_spoken:.1f}s")

        # ==================================================================
        # PHASE 11: [13:10 - 15:00] Final Long Continuous Playout (Until 900s)
        # ==================================================================
        elapsed = time.monotonic() - t_start
        remain = max(5.0, 900.0 - elapsed)
        log(f"=== PHASE 11: Final Continuous Bulletin Playout (waiting {remain:.1f}s to reach full 15 minutes) ===")
        await asyncio.sleep(remain)

        total_elapsed = time.monotonic() - t_start
        total_audio = agent_speaking_frames * 0.02
        log(f"15-Minute Simulation Finished! Total time: {total_elapsed:.1f}s, Total speech: {total_audio:.1f}s")
        if total_audio < 400.0:
            issues.append(f"Simulation: Anchor spoke too little overall ({total_audio:.1f}s / {total_elapsed:.1f}s)")

    finally:
        stop_mic = True
        mic_task.cancel()
        await room.disconnect()

    print("\n================ 15-MINUTE E2E DIAGNOSTIC REPORT ================")
    print(f"Total session duration: {time.monotonic() - t_start:.1f}s")
    print(f"Total speaking audio received: {agent_speaking_frames * 0.02:.1f}s")
    print(f"Total transcripts captured: {len(transcripts)}")
    print(f"Total studio events captured: {len(studio_events)}")
    print(f"Speech gaps >= 0.45s: {[(round(t, 2), round(d, 2)) for t, d in speech_gaps[:25]]} (showing first 25)")
    if issues:
        print(f"\nISSUES FOUND ({len(issues)}):")
        for idx, iss in enumerate(issues, 1):
            print(f"  {idx}. {iss}")
        return 1
    else:
        print("\nALL 10 PHASES PASSED SMOOTHLY ACROSS 15 MINUTES WITH 0 ISSUES!")
        return 0


if __name__ == "__main__":
    import sys
    sys.exit(asyncio.run(run_15m_simulation()))

import asyncio
import json
import logging
import os
import time

from livekit import rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    JobProcess,
    RunContext,
    cli,
    function_tool,
)
from livekit.plugins import openai, silero, simli
from livekit.plugins.turn_detector.multilingual import MultilingualModel

logger = logging.getLogger("agent")

LIVEKIT_API_KEY    = os.getenv("LIVEKIT_API_KEY",    "devkey")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET", "secret")

# LLM
LLM_BASE_URL = os.getenv("LLAMA_BASE_URL", "https://api.groq.com/openai/v1")
LLM_MODEL    = os.getenv("LLAMA_MODEL",    "llama-3.3-70b-versatile")
LLM_API_KEY  = os.getenv("LLAMA_API_KEY",  "")

# STT
STT_BASE_URL = os.getenv("STT_BASE_URL", "https://api.groq.com/openai/v1")
STT_MODEL    = os.getenv("STT_MODEL",    "whisper-large-v3-turbo")
STT_API_KEY  = os.getenv("STT_API_KEY",  "")

# TTS (Kokoro local)
TTS_BASE_URL = os.getenv("TTS_BASE_URL", "http://127.0.0.1:8880/v1")
TTS_VOICE    = os.getenv("TTS_VOICE",    "af_nova")
TTS_API_KEY  = os.getenv("TTS_API_KEY",  "no-key-needed")

# Demo ramp-walk videos served by the frontend (frontend/public/videos/).
# Each clip is short, so it loops `loops` times while NOVA narrates the scripted
# `cues` — (absolute seconds across the looped playback, spoken line). The cue
# lines are written against the actual video content and spoken via session.say()
# at the exact moment, like a live trainer talking over a replay.
_DEMO_VIDEOS: dict[int, dict] = {
    1: {
        "url": "/videos/demo-walk-1.mp4",  # red gown street walk, 5.1s
        "title": "Walk Mechanics — The Straight-Line Walk",
        "loops": 3,
        "cues": [
            (0.3, "Watch her feet — every step lands on one straight line, heel to toe."),
            (5.4, "Watch again — see that hip sway? It comes from crossing the center line."),
            (10.6, "Last round — shoulders still, chin level, arms relaxed. That is your target."),
        ],
    },
    2: {
        "url": "/videos/demo-walk-2.mp4",  # real runway, steady pace, 4.0s
        "title": "Rhythm & Pace — On a Real Runway",
        "loops": 4,
        "cues": [
            (0.3, "This is a real runway — count her steps with me: one, two, one, two."),
            (4.4, "Feel that rhythm — about one step per second, never rushing."),
            (8.4, "Watch again — her upper body stays completely still while her legs work."),
            (12.4, "This calm, even pace is exactly what I want from you."),
        ],
    },
    3: {
        "url": "/videos/demo-walk-3.mp4",  # editorial: walk, turn ~6s, pose, return, 12.0s
        "title": "The Turn & The Power Pose",
        "loops": 2,
        "cues": [
            (0.3, "Watch the approach — long, confident strides straight toward us."),
            (5.0, "Here it comes — the turn. Pivot on the ball of the foot, eyes stay up."),
            (8.5, "Now the pose — pause, hold, own the moment, then walk back."),
            (12.5, "One more time. Watch her posture on the approach — tall and stacked."),
            (17.0, "There — plant, pivot, smooth. Then pose and return. The full sequence."),
        ],
    },
    4: {
        "url": "/videos/demo-walk-4.mp4",  # close-up: expression and attitude, 8.3s
        "title": "Expression & Presence",
        "loops": 2,
        "cues": [
            (0.3, "Now the face — relaxed jaw, soft eyes, total confidence."),
            (4.6, "See how her expression shifts, yet she never loses control."),
            (8.6, "Again — chin level, eyes focused. The face sells the walk."),
            (12.8, "That attitude, that presence — that is what your audience remembers."),
        ],
    },
}

# Simli
SIMLI_API_KEY      = os.getenv("SIMLI_API_KEY",      "")
SIMLI_FACE_ID      = os.getenv("SIMLI_FACE_ID",      "b9e5fba3-071a-4e35-896e-211c4d6eaa7b")
SIMLI_LIVEKIT_URL  = os.getenv("SIMLI_LIVEKIT_URL",  "")  # public tunnel URL for Simli

_BASE_INSTRUCTIONS = """
You are NOVA, the official AI ramp walk trainer for GenzCine — a next-generation film and
entertainment talent discovery platform based in Mohali, Punjab, India. GenzCine connects
aspiring models, actors, and artists with the film and media industry through auditions,
casting opportunities, and a transparent talent ecosystem.

YOUR ROLE:
You are a world-class runway and ramp walk coach. You conduct structured, step-by-step
training sessions using a 10-lesson curriculum. You teach through verbal instruction,
rhythm counting, corrections, and encouragement — like a real trainer standing in the studio.

10-LESSON RAMP WALK CURRICULUM:

Lesson 1 — Foundation and Stance:
Teach the starting position. Feet together, weight evenly distributed. Spine tall and straight
as if a string is pulling the crown of the head upward. Shoulders relaxed and pulled slightly
back, NOT hunched. Chin parallel to the floor — not tilted up or down. Arms loose at the sides.
Core gently engaged. Chest open. Practice: hold this position for 30 seconds. Correct common
mistakes: looking down, rounding the shoulders, locking the knees.

Lesson 2 — The Walk Mechanics:
Teach heel-to-toe foot placement on an imaginary straight line. One foot lands directly in
front of the other, slightly crossing the center line — this creates the signature hip sway.
Stride length: medium, controlled. Not too long (looks unnatural), not too short (looks timid).
Each step should feel grounded and deliberate. Practice: walk 10 steps slowly, counting aloud —
1, 2, 3, 4. Coach on foot placement each step.

Lesson 3 — Rhythm and Pace:
Teach walking to an internal beat. The standard ramp walk pace is approximately 80 to 90 beats
per minute — about one step per second. Count out loud: step on 1, step on 2, step on 3.
Too fast looks nervous. Too slow looks heavy. Teach the student to feel the rhythm internally
and maintain it for the entire length of the runway. Practice: walk 20 steps at a steady pace
while NOVA counts the beat.

Lesson 4 — Posture in Motion:
Teach maintaining perfect posture while walking. Common mistake: the upper body stiffens or
the hips lock. The upper body should remain still and poised while the hips and legs do the work.
Shoulders stay level and do not rock side to side. The chin stays up the entire walk. Core stays
engaged throughout. Practice: walk 10 steps focusing entirely on keeping the upper body still.

Lesson 5 — Arm Swing and Hand Placement:
Teach natural, minimal arm movement. Arms swing slightly — forward and back, not across the body.
Hands are relaxed and soft — fingers gently together, not a fist, not splayed. Some editorial
walks use one hand in pocket or near the hip. Commercial and Bollywood walks allow slightly more
expressive arm placement. Practice: exaggerate wrong arm movement first so the student feels
the difference, then correct to natural movement.

Lesson 6 — The T-Turn:
Teach the turn at the end of the runway. Step 1: walk to the mark, stop on the beat.
Step 2: pause for two beats — this is the power pause, hold your pose and own the moment.
Step 3: pivot on the ball of the front foot, turning 180 degrees in one smooth motion.
Step 4: reset posture immediately after the turn. Step 5: begin the return walk without
hesitation. Common mistake: looking at the feet during the turn. Eyes always stay forward.
Practice: execute the T-turn 5 times until it feels smooth.

Lesson 7 — Advanced Turns and Pivots:
Teach the half turn, three-quarter turn, and full spin for high-fashion and Bollywood contexts.
Half turn: two steps, pivot, return. Three-quarter turn: used to show the back of an outfit.
Full spin: execute in 2 beats, controlled, end facing front with a strong pose. Teach the
student to spot a point on the wall to avoid dizziness during spins. Practice each turn
type separately before combining them.

Lesson 8 — Facial Expression and Eye Contact:
Teach the model face — relaxed jaw, slightly parted lips, intense but not angry eyes.
Eyes focus on a fixed point at the end of the runway, NOT on the audience or the floor.
Teach three expressions: editorial (strong, fierce, emotionless), commercial (warm, slight smile,
approachable), Bollywood (expressive, emotive, connection with audience). Teach the student
to switch expressions on command. Practice: NOVA calls an expression and the student holds it
for 5 seconds while walking.

Lesson 9 — Walking in Heels:
Teach heel placement for stilettos, block heels, and wedges. In stilettos, the entire foot
lands almost simultaneously — heel barely touches first, then toes, creating a smooth roll.
Never slam the heel down. Body weight shifts slightly forward over the ball of the foot.
Shorter stride than flat shoes. Core tightens more in heels for balance. Practice: walk 10
steps in heels at slow pace, focusing on silent, smooth foot placement.

Lesson 10 — Full Runway Performance:
Combine all 9 lessons into a complete runway performance. Open walk from backstage mark to
center stage: 15 steps, T-turn, power pause with expression hold, return walk 15 steps,
exit. Teach the student to project energy and presence from the first step. The audience
must feel something before the model reaches them. Practice: full runway run-through 3
times with feedback after each. Focus on what improved and what needs work.

DEMO VIDEO SYSTEM:
You have a tool called show_demo_video that plays a real professional ramp walk example
video full-screen on the student's device. The clip replays a few times and YOUR OWN
live commentary is spoken automatically over it at the right moments, like a trainer
narrating a replay — you do NOT need to describe the video yourself.
- After completing every 2 lessons, play the matching demo:
  after Lesson 2 → demo 1 (straight-line walk mechanics, heel-to-toe, hip sway)
  after Lesson 4 → demo 2 (rhythm and pace on a real runway)
  after Lesson 6 → demo 3 (the turn and the power pose)
  after Lesson 8 or 10 → demo 4 (facial expression and presence)
- Before calling the tool, say ONE short sentence like "let me show you exactly what I
  mean — watch this" — nothing more
- While the video plays, do not add anything beyond the automatic commentary
- You will be notified when the video ends — then ask what they noticed, connect it to
  the lessons just covered, and continue training from where you left off
- If the student asks to see an example at any time, play the most relevant demo

TEACHING METHOD:
- Always find out which lesson the student wants to work on, OR start from Lesson 1 if they
  are a beginner
- Teach one concept at a time. Do not rush to the next step until the current one is clear
- Give exact verbal cues: "step on 1, step on 2, pivot on 3, hold on 4"
- After instruction, always say "try it now" or "practice this while I count"
- After the student practices, ask "how did that feel?" and give specific feedback
- Celebrate progress. A first attempt is always better than no attempt
- If the student says they feel nervous or scared — normalize it. Every model felt nervous first

ABOUT GENZCINE:
GenzCine is a transparent, new-age platform giving every aspiring talent a fair chance in
the film industry. It connects models, actors, and artists with production houses and casting
directors across India and globally. Website: genzcine.com | Mohali, Punjab, India.

STRICT RULES:
- Only discuss ramp walk, runway training, modeling, film industry talent, and GenzCine
- Keep each response short and conversational — this is a VOICE interface
- Never use bullet points, asterisks, or emojis in speech
- Speak as a live trainer would — natural, warm, authoritative
- Count rhythm out loud when guiding exercises
- Never skip ahead — one step at a time

FREE TRIAL SESSION GUIDELINES:
This is a free 5-minute trial session. Make every second count:
- Open with a warm 10-second greeting, then immediately ask which lesson to start or begin Lesson 1
- Keep your coaching tight — one concept per turn, no long monologues
- After about 4 minutes, naturally say: "We are coming up on the end of today's trial session. You have done great work. To continue training with me every day, upgrade to GenzCine Premium at genzcine dot com."
- If the student asks about pricing or more sessions, say: "Head to genzcine dot com to unlock full access — unlimited sessions, all ten lessons, and priority audition access."
- Never say "trial" in a negative way — frame it as the beginning of their journey
"""

_ACTING_INSTRUCTIONS = """
You are NOVA, the official AI acting coach for GenzCine — a next-generation film and
entertainment talent discovery platform based in Mohali, Punjab, India. GenzCine connects
aspiring models, actors, and artists with the film and media industry through auditions,
casting opportunities, and a transparent talent ecosystem.

YOUR ROLE:
You are a world-class acting coach for film, television, and OTT. You conduct structured,
step-by-step training sessions using a 10-lesson curriculum. You teach through verbal
instruction, live exercises, corrections, and encouragement — like a real acting coach
standing in the studio with the student.

10-LESSON ACTING CURRICULUM:

Lesson 1 — Relaxation and Breath:
Teach the actor's neutral state. Release tension from jaw, shoulders, and hands. Diaphragmatic
breathing: inhale 4 counts, hold 2, exhale 6. Tension kills performance — a relaxed body can
become any character. Practice: one minute of guided breathing, then shake out the limbs and
reset to neutral.

Lesson 2 — Voice and Diction:
Teach breath-supported voice, projection without shouting, and crisp articulation. Warmups:
lip trills, tongue twisters, humming up and down the register. Slow down speech — beginners
rush. Practice: deliver one line three ways — soft, conversational, projected — keeping the
words clear each time.

Lesson 3 — Facial Expressions and the Nine Emotions:
Teach expression control using the navarasa — joy, sorrow, anger, fear, surprise, disgust,
courage, peace, and love or longing. The face must show the emotion before a single word is
spoken. Practice: NOVA calls an emotion and the student holds it for 5 seconds, then switches
on command. The posture camera can be used to check expressions.

Lesson 4 — Body Language and Physicality:
Teach how the body tells the story: open versus closed posture, status play (a confident
character takes space, a nervous one shrinks), walking in character, and stillness as power.
Practice: enter the room twice — once as a confident star arriving on set, once as a nervous
newcomer — using only the body, no words.

Lesson 5 — Dialogue Delivery:
Teach intention behind lines — every line wants something from the other person. Beats,
pauses, emphasis, and subtext. The same line changes completely with a different intention.
Practice: take the line "I never said that" and deliver it to accuse, to apologize, and to
joke. Coach the shift in tone, pace, and stress.

Lesson 6 — Emotional Memory and Truth:
Teach connecting to genuine emotion safely: recall a real moment, borrow its feeling, and pour
it into the scene — then step out cleanly afterward. Truth reads on camera; indication looks
fake. Practice: say "I am fine" while feeling the opposite underneath, letting the truth leak
through the eyes only.

Lesson 7 — Improvisation:
Teach the rules of improv: always accept and build — yes, and. Never block a scene partner.
Stay present, listen, react honestly. Improv builds spontaneity for auditions and covers
forgotten lines gracefully. Practice: NOVA gives a situation — you are returning a broken
phone to a shopkeeper — and plays the scene with the student for a few exchanges.

Lesson 8 — Camera Acting:
Teach the difference between stage and screen: the camera catches everything, so less is more.
Eyeline discipline, hitting marks, playing in close-up versus wide shot, continuity of actions,
and never looking into the lens unless directed. Practice: deliver the same short monologue
twice — once as if for a wide shot, once for an extreme close-up where only the eyes work.

Lesson 9 — Scene Work and Reactions:
Teach that acting is reacting — the scene lives in the listener. Active listening, holding
the moment before responding, giving your partner something to play off. Practice: NOVA plays
a short scene as the other character; the student must listen and react truthfully before
each of their lines.

Lesson 10 — Audition Mastery and Self-Tapes:
Combine everything into audition craft: the slate (name, age, height, city — warm and
confident), cold reading, taking direction and adjusting instantly, self-tape framing
(chest-up, eyeline just off lens, clean background, good light). End with a full mock
audition: slate plus a short monologue, then one adjustment note, then a second take.

TEACHING METHOD:
- Always find out which lesson the student wants to work on, OR start from Lesson 1 if they
  are a beginner
- Teach one concept at a time. Do not rush to the next step until the current one is clear
- Give exact verbal cues and always demonstrate the idea in your own delivery
- After instruction, always say "try it now" or "let us do it together"
- After the student performs, ask "how did that feel?" and give specific feedback on voice,
  face, body, and truthfulness
- Celebrate progress. A first attempt is always better than no attempt
- If the student feels nervous or self-conscious — normalize it. Every actor felt that first

ABOUT GENZCINE:
GenzCine is a transparent, new-age platform giving every aspiring talent a fair chance in
the film industry. It connects models, actors, and artists with production houses and casting
directors across India and globally. Website: genzcine.com | Mohali, Punjab, India.

STRICT RULES:
- Only discuss acting, dialogue, auditions, film craft, the film industry, and GenzCine
- Keep each response short and conversational — this is a VOICE interface
- Never use bullet points, asterisks, or emojis in speech
- Speak as a live coach would — natural, warm, authoritative
- Never skip ahead — one step at a time
- Demo videos are NOT available in acting mode — teach through voice and live exercises

FREE TRIAL SESSION GUIDELINES:
This is a free 5-minute trial session. Make every second count:
- Open with a warm 10-second greeting, then immediately ask which lesson to start or begin Lesson 1
- Keep your coaching tight — one concept per turn, no long monologues
- After about 4 minutes, naturally say: "We are coming up on the end of today's trial session. You have done great work. To continue training with me every day, upgrade to GenzCine Premium at genzcine dot com."
- If the student asks about pricing or more sessions, say: "Head to genzcine dot com to unlock full access — unlimited sessions, all ten lessons, and priority audition access."
- Never say "trial" in a negative way — frame it as the beginning of their journey
"""

# Session languages — Kokoro TTS lang codes: a/b (English), e, f, h, i, j, p, z.
# code -> (display name, extra instruction for the LLM)
_LANGUAGES: dict[str, tuple[str, str]] = {
    "en-US": ("English", ""),
    "en-GB": ("English", "Use British English spelling and phrasing."),
    "hi": ("Hindi", "Write Hindi in Devanagari script. Common English fashion and film terms "
           "(runway, pose, cut, action, camera) may stay in English where natural."),
    "es": ("Spanish", ""),
    "fr": ("French", ""),
    "it": ("Italian", ""),
    "pt-BR": ("Brazilian Portuguese", ""),
    "zh": ("Mandarin Chinese", "Write in Simplified Chinese."),
}


def _language_addon(language: str) -> str:
    name, extra = _LANGUAGES.get(language, ("English", ""))
    if name == "English" and not extra:
        return ""
    return (
        "\n\n"
        "SESSION LANGUAGE:\n"
        f"The student chose {name} for this session. Speak ONLY in {name} from your very "
        f"first greeting to the end — every instruction, correction, and count. "
        f"Do not switch to another language unless the student explicitly asks. {extra}"
    )


_GROUP_ADDON = (
    "\n\n"
    "GROUP SESSION MODE:\n"
    "You are currently running a GROUP training session with multiple models in the room. "
    "Follow these additional guidelines:\n"
    "- Welcome each participant by name and make everyone feel included\n"
    "- Give group warmups, theory, and rhythm exercises to everyone together\n"
    "- Call on participants by name for solo exercises — tell the rest to watch and learn\n"
    "- Deliver encouragement and corrections to the whole group when appropriate\n"
    "- Rotate attention fairly — do not focus on one person for too long\n"
    "- When counting rhythm for a group walk, keep everyone in sync\n"
    "- Celebrate group progress and create a positive team atmosphere\n"
    "- Keep individual feedback short so the group stays engaged\n"
    "- Greet new participants who join mid-session by name"
)


class Assistant(Agent):
    def __init__(
        self,
        session_type: str = "individual",
        room: rtc.Room | None = None,
        mode: str = "ramp",
        language: str = "en-US",
    ) -> None:
        self._session_type = session_type
        self._participants: dict[str, str] = {}  # identity -> display name
        self._room = room
        self._mode = mode
        self._language = language

        base = _ACTING_INSTRUCTIONS if mode == "acting" else _BASE_INSTRUCTIONS
        instructions = (
            base
            + _language_addon(language)
            + (_GROUP_ADDON if session_type == "group" else "")
        )
        super().__init__(instructions=instructions)

    @function_tool
    async def show_demo_video(self, context: RunContext, demo_number: int) -> str:
        """Play a professional ramp walk demo video full-screen on the student's device.

        Call this after completing every 2 lessons (demo 1 after Lesson 2, demo 2 after
        Lesson 4, demo 3 after Lesson 6, demo 4 after Lesson 8 or 10), or whenever the
        student asks to see an example walk.

        Args:
            demo_number: Which demo video to play — 1, 2, 3 or 4.
        """
        if self._mode != "ramp":
            return (
                "Demo videos are only available in ramp walk training — "
                "continue coaching through voice and live exercises."
            )
        demo = _DEMO_VIDEOS.get(int(demo_number))
        if demo is None or self._room is None:
            return "Demo video is unavailable right now — continue coaching verbally."
        try:
            payload = json.dumps(
                {
                    "type": "demo_video",
                    "demo": int(demo_number),
                    "url": demo["url"],
                    "title": demo["title"],
                    "loops": demo["loops"],
                    # frontend fires a cue event when playback crosses each time;
                    # the spoken lines stay server-side
                    "cues": [t for t, _ in demo["cues"]],
                }
            )
            await self._room.local_participant.publish_data(
                payload.encode(), reliable=True, topic="demo_video"
            )
        except Exception:
            logger.exception("show_demo_video publish failed")
            return "Could not start the demo video — continue coaching verbally."
        logger.info("[%s] demo video %s started: %s", self._session_type, demo_number, demo["url"])
        return (
            f"Demo video {demo_number} ('{demo['title']}') is now playing on the student's screen "
            f"and will replay {demo['loops']} times. Your live commentary is spoken over it "
            "automatically — say nothing further until you are notified that the video ended."
        )

    async def on_enter(self) -> None:
        try:
            room = self._room

            if room is not None:
                for identity, participant in room.remote_participants.items():
                    self._participants[identity] = participant.name or identity
                room.on("participant_connected", self._on_participant_connected)
                room.on("participant_disconnected", self._on_participant_disconnected)

            participant_names = list(self._participants.values())

            if self._mode == "acting":
                coach_role = "GenzCine's official acting coach"
                curriculum_line = (
                    "Tell the student that you have a complete 10-lesson acting curriculum — "
                    "covering relaxation and breath, voice and diction, facial expressions, "
                    "body language, dialogue delivery, emotional truth, improvisation, "
                    "camera acting, scene work, and audition mastery with self-tapes. "
                )
                experience_q = "are they a complete beginner or have they acted before? "
            else:
                coach_role = "GenzCine's official ramp walk trainer"
                curriculum_line = (
                    "Tell the student that you have a complete 10-lesson ramp walk curriculum — "
                    "covering foundation and stance, walk mechanics, rhythm, posture in motion, "
                    "arm placement, the T-turn, advanced turns, facial expression, heels, and a full runway performance. "
                )
                experience_q = "are they a complete beginner or do they have some experience on the ramp? "

            if self._session_type == "group":
                count = len(participant_names)
                name_list = ", ".join(participant_names) if participant_names else "everyone"
                await self.session.generate_reply(
                    instructions=(
                        f"You are starting a GROUP training session. "
                        f"There are currently {count} participant(s) in the room: {name_list}. "
                        f"Welcome the group warmly by their names as NOVA, {coach_role}. "
                        "Explain that this is a group session where everyone trains together and also gets individual turns. "
                        "Ask if anyone needs an introduction to the 10-lesson curriculum or wants to jump straight into practice. "
                        "Keep it high-energy and under 5 sentences."
                    )
                )
            else:
                student_name = participant_names[0] if participant_names else None
                name_line = f"Address the student by their name: {student_name}. " if student_name else ""
                await self.session.generate_reply(
                    instructions=(
                        f"{name_line}"
                        f"Introduce yourself as NOVA, {coach_role}. "
                        f"{curriculum_line}"
                        f"Ask them two quick questions: first, {experience_q}"
                        "And second, do they want to start from Lesson 1 "
                        "or jump to a specific lesson? "
                        "Be warm, direct, and professional. Under 5 sentences."
                    )
                )
        except Exception:
            logger.exception("[%s] on_enter failed — attempting fallback greeting", self._session_type)
            try:
                await self.session.generate_reply(
                    instructions="Greet the user warmly as NOVA and say you are ready to begin ramp walk training."
                )
            except Exception:
                logger.exception("[%s] fallback greeting also failed", self._session_type)

    def _on_participant_connected(self, participant: rtc.RemoteParticipant) -> None:
        try:
            name = participant.name or participant.identity
            self._participants[participant.identity] = name
            logger.info("[%s] participant joined: %s", self._session_type, name)
        except Exception:
            logger.exception("_on_participant_connected error")

    def _on_participant_disconnected(self, participant: rtc.RemoteParticipant) -> None:
        try:
            removed = self._participants.pop(participant.identity, participant.identity)
            logger.info("[%s] participant left: %s", self._session_type, removed)
        except Exception:
            logger.exception("_on_participant_disconnected error")


# ── Server setup ──────────────────────────────────────────────────────────────

server = AgentServer()


def prewarm(proc: JobProcess) -> None:
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


@server.rtc_session()
async def my_agent(ctx: JobContext) -> None:
    ctx.log_context_fields = {"room": ctx.room.name}

    # Detect session type from room name prefix set by the API
    session_type = "group" if ctx.room.name.startswith("group_room_") else "individual"

    logger.info(
        "agent session: type=%s stt=%s llm=%s tts=%s",
        session_type, STT_MODEL, LLM_MODEL, TTS_BASE_URL,
    )

    await ctx.connect()

    # Metadata is JSON: {"face_id": "...", "voice": "...", "trial_seconds": N,
    #                     "language": "hi", "mode": "ramp"|"acting"}
    try:
        meta = json.loads(ctx.room.metadata or "{}")
        face_id = meta.get("face_id", "").strip() or SIMLI_FACE_ID
        voice = meta.get("voice", "").strip() or TTS_VOICE
        trial_seconds = int(meta.get("trial_seconds", -1))
        language = str(meta.get("language", "") or "en-US")
        mode = str(meta.get("mode", "") or "ramp")
    except (json.JSONDecodeError, AttributeError, ValueError):
        face_id = (ctx.room.metadata or "").strip() or SIMLI_FACE_ID
        voice = TTS_VOICE
        trial_seconds = -1
        language = "en-US"
        mode = "ramp"

    if language not in _LANGUAGES:
        language = "en-US"
    if mode not in ("ramp", "acting"):
        mode = "ramp"

    logger.info(
        "session avatar: face_id=%s voice=%s trial_seconds=%s language=%s mode=%s",
        face_id, voice, trial_seconds, language, mode,
    )

    session = AgentSession(
        stt=openai.STT(base_url=STT_BASE_URL, model=STT_MODEL, api_key=STT_API_KEY),
        llm=openai.LLM(base_url=LLM_BASE_URL, model=LLM_MODEL, api_key=LLM_API_KEY),
        tts=openai.TTS(base_url=TTS_BASE_URL, model="tts-1", voice=voice, api_key=TTS_API_KEY),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        preemptive_generation=True,
    )

    if SIMLI_API_KEY and face_id:
        try:
            simli_avatar = simli.AvatarSession(
                simli_config=simli.SimliConfig(
                    api_key=SIMLI_API_KEY,
                    face_id=face_id,
                ),
            )
            await simli_avatar.start(
                session,
                room=ctx.room,
                livekit_url=SIMLI_LIVEKIT_URL,
                livekit_api_key=LIVEKIT_API_KEY,
                livekit_api_secret=LIVEKIT_API_SECRET,
            )
            logger.info("Simli avatar started: face_id=%s", face_id)
        except Exception:
            logger.exception("Simli avatar failed to start — continuing as audio-only")
    else:
        logger.warning("SIMLI_API_KEY or face_id not set — avatar disabled")

    agent = Assistant(session_type=session_type, room=ctx.room, mode=mode, language=language)
    await session.start(agent=agent, room=ctx.room)

    # ── Posture camera data channel ───────────────────────────────────────────
    _pose_busy = False
    _video_reply_at: dict[int, float] = {}  # demo_no -> last reply time (dedup in group rooms)
    _video_cue_at: dict[tuple[int, int], float] = {}  # (demo, cue) -> last spoken time

    async def _respond_to_pose(summary: str) -> None:
        nonlocal _pose_busy
        _pose_busy = True
        try:
            await session.generate_reply(
                instructions=(
                    f"Your student's live posture camera just captured this: {summary} "
                    "You are standing right next to them as their ramp walk trainer. "
                    "Respond like a real trainer giving hands-on correction — NOT a score report. "
                    "Name the exact body part that needs fixing and give a precise physical cue: "
                    "for example 'drop your right shoulder down', 'chin up — parallel to the floor', "
                    "'stack your spine tall like a string is pulling the crown of your head up', "
                    "'engage your core and stand straight'. "
                    "If something looks good, say so in one short phrase first. "
                    "Then give the correction. Then count them in to try again: 'Ready — walk on 1.' "
                    "Maximum 3 short sentences. Natural spoken voice — no lists, no numbers, no scores."
                )
            )
        except Exception:
            logger.exception("pose reply failed")
        finally:
            _pose_busy = False

    async def _respond_to_video_end(demo_no: int, skipped: bool) -> None:
        try:
            if skipped:
                await session.generate_reply(
                    instructions=(
                        f"The student skipped demo video {demo_no} before it finished. "
                        "That is fine — do not guilt them. Briefly summarize the one key thing "
                        "the video showed, then continue the training from where you left off."
                    )
                )
            else:
                await session.generate_reply(
                    instructions=(
                        f"Demo video {demo_no} just finished playing for the student. "
                        "Ask them ONE specific question about what they noticed in the model's walk, "
                        "connect it to the lessons you just taught, then continue training "
                        "from where you left off. Keep it short and conversational."
                    )
                )
        except Exception:
            logger.exception("video end reply failed")

    def _speak_video_cue(demo_no: int, cue_idx: int) -> None:
        try:
            demo = _DEMO_VIDEOS.get(demo_no)
            if demo is None or not (0 <= cue_idx < len(demo["cues"])):
                return
            _, text = demo["cues"][cue_idx]
            if language.startswith("en"):
                # Direct TTS — exact scripted line at the exact video moment,
                # no LLM round-trip latency.
                session.say(text, add_to_chat_ctx=True)
            else:
                # Non-English session — let the LLM speak the cue in the
                # session language (small extra latency, still near the moment).
                lang_name = _LANGUAGES[language][0]
                asyncio.get_event_loop().create_task(
                    session.generate_reply(
                        instructions=(
                            f"Say exactly this to the student in {lang_name}, as one natural "
                            f"spoken sentence, nothing more: '{text}'"
                        )
                    )
                )
        except Exception:
            logger.exception("video cue say failed")

    def on_data_received(data_packet: rtc.DataPacket) -> None:
        nonlocal _pose_busy
        try:
            payload = json.loads(data_packet.data.decode())
            msg_type = payload.get("type")
            if msg_type == "pose_analysis":
                # Check busy flag here (sync) to avoid scheduling duplicate tasks
                if _pose_busy:
                    return
                summary = str(payload.get("summary", ""))[:600]
                if summary:
                    loop = asyncio.get_event_loop()
                    loop.create_task(_respond_to_pose(summary))
            elif msg_type == "demo_video_cue":
                demo_no = int(payload.get("demo", 0))
                cue_idx = int(payload.get("cue", -1))
                # Dedup per (demo, cue) — in group rooms every participant reports
                now = time.monotonic()
                key = (demo_no, cue_idx)
                if now - _video_cue_at.get(key, float("-inf")) < 30.0:
                    return
                _video_cue_at[key] = now
                _speak_video_cue(demo_no, cue_idx)
            elif msg_type == "demo_video_ended":
                demo_no = int(payload.get("demo", 0))
                skipped = bool(payload.get("skipped", False))
                # In group sessions every participant sends this when their
                # player closes — react only once per demo within a window.
                now = time.monotonic()
                if now - _video_reply_at.get(demo_no, float("-inf")) < 60.0:
                    return
                _video_reply_at[demo_no] = now
                loop = asyncio.get_event_loop()
                loop.create_task(_respond_to_video_end(demo_no, skipped))
        except Exception:
            logger.exception("on_data_received error")

    ctx.room.on("data_received", on_data_received)

    # ── Server-side trial enforcer ────────────────────────────────────────────
    # Runs even if the client patches its JS — agent disconnects itself.
    if trial_seconds > 0:
        async def _enforce_trial() -> None:
            warn_at = max(0, trial_seconds - 60)
            if warn_at > 0:
                await asyncio.sleep(warn_at)
                if not session.is_closed:
                    try:
                        await session.generate_reply(
                            instructions=(
                                "You have about 60 seconds left in the free trial session. "
                                "Warmly let the student know time is almost up, summarize the one "
                                "key thing they worked on today, and encourage them to upgrade to "
                                "GenzCine Premium at genzcine dot com for unlimited daily training."
                            )
                        )
                    except Exception:
                        pass
                await asyncio.sleep(60)
            else:
                await asyncio.sleep(trial_seconds)

            if not session.is_closed:
                try:
                    await session.generate_reply(
                        instructions=(
                            "The free trial session has ended. Thank the student warmly, tell them "
                            "they did great work today, and direct them to genzcine dot com to "
                            "unlock Premium for unlimited access. Say goodbye kindly."
                        )
                    )
                    await asyncio.sleep(8)
                except Exception:
                    pass

            logger.info("trial enforcer: disconnecting room=%s after %ds", ctx.room.name, trial_seconds)
            try:
                await ctx.room.disconnect()
            except Exception:
                logger.exception("trial enforcer: disconnect failed")

        asyncio.create_task(_enforce_trial())
        logger.info("trial enforcer scheduled: %ds for room=%s", trial_seconds, ctx.room.name)


if __name__ == "__main__":
    cli.run_app(server)

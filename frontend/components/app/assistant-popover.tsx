'use client';

import { Suspense, lazy, useCallback, useEffect, useRef, useState } from 'react';
import { RoomEvent } from 'livekit-client';
import { AnimatePresence, motion, useMotionValue } from 'motion/react';
import {
  BarVisualizer,
  VideoTrack,
  useRoomContext,
  useRoomInfo,
  useSessionContext,
  useSessionMessages,
  useVoiceAssistant,
} from '@livekit/components-react';
import {
  CaretDownIcon,
  MicrophoneIcon,
  MicrophoneSlashIcon,
  PhoneDisconnectIcon,
} from '@phosphor-icons/react/dist/ssr';
import * as PopoverPrimitive from '@radix-ui/react-popover';
import { ChatTranscript } from '@/components/app/chat-transcript';
import type { NewsVideo } from '@/components/app/news-video-player';
import { useInputControls } from '@/components/livekit/agent-control-bar/hooks/use-input-controls';
import { ScrollArea } from '@/components/livekit/scroll-area/scroll-area';
import { ANCHORS, LANGUAGES, VOICE_MAP } from '@/lib/anchors';
import { getDeviceId } from '@/lib/device';
import { cn } from '@/lib/utils';

const NewsVideoPlayer = lazy(() => import('@/components/app/news-video-player'));

const DESKTOP_BUTTON_SIZE = 96;
const PHONE_BUTTON_SIZE = 76;
const PHONE_SM_BUTTON_SIZE = 70;
const EDGE_MARGIN_DESKTOP = 20;
const EDGE_MARGIN_PHONE = 12;
const POPOVER_WIDTH_DESKTOP = 520;

type Phase = 'setup' | 'connecting' | 'live';

function readSafeInset(varName: string): number {
  if (typeof window === 'undefined') return 0;
  const raw = getComputedStyle(document.documentElement).getPropertyValue(varName).trim();
  const n = parseFloat(raw);
  return Number.isFinite(n) ? n : 0;
}

/** Phone / tablet layout metrics — updates on resize + orientation. */
function usePhoneLayout() {
  const [layout, setLayout] = useState({
    isPhone: false,
    isNarrow: false,
    buttonSize: DESKTOP_BUTTON_SIZE,
    edgeMargin: EDGE_MARGIN_DESKTOP,
    safeBottom: 0,
    safeTop: 0,
    safeLeft: 0,
    safeRight: 0,
  });

  useEffect(() => {
    const update = () => {
      const w = window.innerWidth;
      const isPhone = w < 640;
      const isNarrow = w < 400;
      setLayout({
        isPhone,
        isNarrow,
        buttonSize: isNarrow ? PHONE_SM_BUTTON_SIZE : isPhone ? PHONE_BUTTON_SIZE : DESKTOP_BUTTON_SIZE,
        edgeMargin: isPhone ? EDGE_MARGIN_PHONE : EDGE_MARGIN_DESKTOP,
        safeBottom: readSafeInset('--sab'),
        safeTop: readSafeInset('--sat'),
        safeLeft: readSafeInset('--sal'),
        safeRight: readSafeInset('--sar'),
      });
    };
    update();
    window.addEventListener('resize', update);
    window.addEventListener('orientationchange', update);
    // iOS Safari URL bar show/hide
    window.visualViewport?.addEventListener('resize', update);
    return () => {
      window.removeEventListener('resize', update);
      window.removeEventListener('orientationchange', update);
      window.visualViewport?.removeEventListener('resize', update);
    };
  }, []);

  return layout;
}

const AGENT_STATE_CONFIG: Record<string, { label: string; dotClass: string }> = {
  speaking: { label: 'Speaking', dotClass: 'bg-[#FF1F2D]' },
  listening: { label: 'Listening', dotClass: 'bg-emerald-400' },
  thinking: { label: 'Thinking', dotClass: 'bg-amber-400 animate-pulse' },
  initializing: { label: 'Starting', dotClass: 'bg-white/25 animate-pulse' },
  connecting: { label: 'Connecting', dotClass: 'bg-white/25 animate-pulse' },
  disconnected: { label: 'Offline', dotClass: 'bg-white/15' },
};

interface AssistantPopoverProps {
  faceId: string;
  language: string;
  name: string;
  canStart: boolean;
  isStarting?: boolean;
  startLabel: string;
  trialRemainingSeconds?: number;
  onTrialExpired?: () => void;
  onNameChange: (name: string) => void;
  onAnchorChange: (faceId: string, voice: string, language: string, anchorName: string) => void;
  onStart: () => void;
}

// Self-contained language dropdown — deliberately NOT portaled, so it always
// renders nested inside the popover card instead of floating off elsewhere.
function LanguagePicker({ value, onChange }: { value: string; onChange: (code: string) => void }) {
  const [open, setOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: PointerEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('pointerdown', onPointerDown);
    return () => document.removeEventListener('pointerdown', onPointerDown);
  }, [open]);

  const current = LANGUAGES.find((l) => l.code === value) ?? LANGUAGES[0];

  return (
    <div ref={wrapperRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="flex w-full items-center justify-between rounded-xl border border-white/[0.08] bg-white/[0.04] px-3 py-3 text-[13px] text-white sm:px-4 sm:py-3.5 sm:text-[14px]"
      >
        <span className="flex min-w-0 items-center gap-2 sm:gap-2.5">
          <span className="text-[16px] leading-none sm:text-[18px]">{current.flag}</span>
          <span className="truncate font-semibold">{current.label}</span>
          <span className="hidden truncate text-white/35 sm:inline">· {current.sub}</span>
          <span className="truncate text-white/35 sm:hidden">· {current.sub.split(' ')[0]}</span>
        </span>
        <CaretDownIcon
          weight="bold"
          className={cn('size-3.5 text-white/40 transition-transform', open && 'rotate-180')}
        />
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -4, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4, scale: 0.98 }}
            transition={{ duration: 0.15 }}
            role="listbox"
            className="absolute inset-x-0 top-[calc(100%+6px)] z-10 max-h-56 overflow-y-auto rounded-xl border border-white/[0.08] bg-[#1c1c1c] p-1 shadow-2xl"
          >
            {LANGUAGES.map((l) => (
              <button
                key={l.code}
                type="button"
                role="option"
                aria-selected={l.code === value}
                onClick={() => {
                  onChange(l.code);
                  setOpen(false);
                }}
                className={cn(
                  'flex w-full items-center gap-2.5 rounded-lg px-3 py-2.5 text-left text-[13px] transition-colors',
                  l.code === value
                    ? 'bg-[#FF1F2D]/15 text-white'
                    : 'text-white/60 hover:bg-white/[0.06] hover:text-white'
                )}
              >
                <span className="text-[16px] leading-none">{l.flag}</span>
                <span className="font-medium">{l.label}</span>
                <span className="text-white/30">· {l.sub}</span>
              </button>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function LoadStep({ done, label }: { done: boolean; label: string }) {
  return (
    <div className="flex items-center gap-3">
      <div className="relative flex h-5 w-5 shrink-0 items-center justify-center">
        {done ? (
          <motion.div
            initial={{ scale: 0 }}
            animate={{ scale: 1 }}
            className="flex h-5 w-5 items-center justify-center rounded-full bg-emerald-500/20"
          >
            <svg
              width="10"
              height="10"
              viewBox="0 0 12 12"
              fill="none"
              stroke="#34d399"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <polyline points="2,6 5,9 10,3" />
            </svg>
          </motion.div>
        ) : (
          <div className="h-4 w-4 animate-spin rounded-full border border-white/10 border-t-[#FF1F2D]" />
        )}
      </div>
      <span
        className={cn(
          'text-[13px] transition-colors duration-500',
          done ? 'text-white/45' : 'text-white/75'
        )}
      >
        {label}
      </span>
    </div>
  );
}

const GREETING_SEEN_KEY = 'gc_anchor_greeting_seen';

type SetupStep = 'greeting' | 'config';

function getGreetingSeen(): boolean {
  if (typeof window === 'undefined') return false;
  return localStorage.getItem(GREETING_SEEN_KEY) === '1';
}

function markGreetingSeen() {
  localStorage.setItem(GREETING_SEEN_KEY, '1');
}

function SetupStepIndicator({ step }: { step: SetupStep }) {
  return (
    <div className="flex items-center justify-center gap-1.5 px-4 pb-2 sm:px-7">
      <span
        aria-hidden
        className={cn(
          'h-1.5 rounded-full transition-all duration-300',
          step === 'greeting' ? 'w-5 bg-[#FF1F2D]' : 'w-1.5 bg-white/15'
        )}
      />
      <span
        aria-hidden
        className={cn(
          'h-1.5 rounded-full transition-all duration-300',
          step === 'config' ? 'w-5 bg-[#FF1F2D]' : 'w-1.5 bg-white/15'
        )}
      />
    </div>
  );
}

/** Auto-rotating intro copy for the selected anchor model. */
function AnchorIntroSlider({
  slides,
  resetKey,
}: {
  slides: string[];
  resetKey: string;
}) {
  const [index, setIndex] = useState(0);

  useEffect(() => {
    setIndex(0);
  }, [resetKey]);

  useEffect(() => {
    if (slides.length < 2) return;
    const id = setInterval(() => setIndex((i) => (i + 1) % slides.length), 4200);
    return () => clearInterval(id);
  }, [slides.length, resetKey]);

  return (
    <div className="px-4 pb-4 sm:px-7">
      <div className="relative min-h-[68px] sm:min-h-[76px]">
        <AnimatePresence mode="wait">
          <motion.p
            key={`${resetKey}-${index}`}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.28 }}
            className="text-[13.5px] leading-relaxed text-white/55 sm:text-[14.5px]"
          >
            {slides[index]}
          </motion.p>
        </AnimatePresence>
      </div>
      <div className="mt-3 flex items-center gap-1.5">
        {slides.map((_, i) => (
          <button
            key={i}
            type="button"
            onClick={() => setIndex(i)}
            aria-label={`Show intro ${i + 1} of ${slides.length}`}
            aria-current={i === index}
            className={cn(
              'h-1.5 rounded-full transition-all duration-300',
              i === index ? 'w-5 bg-[#FF1F2D]' : 'w-1.5 bg-white/15 hover:bg-white/30'
            )}
          />
        ))}
      </div>
    </div>
  );
}

// Full onboarding greeting — shown alone before anchor/language/name setup.
function OnboardingGreeting({
  slides,
  resetKey,
  onComplete,
}: {
  slides: string[];
  resetKey: string;
  onComplete: () => void;
}) {
  const [index, setIndex] = useState(0);
  const isLast = index === slides.length - 1;

  useEffect(() => {
    setIndex(0);
  }, [resetKey]);

  // Auto-advance until the last slide — last slide waits for Continue/Skip.
  useEffect(() => {
    if (isLast || slides.length < 2) return;
    const id = setInterval(() => setIndex((i) => Math.min(i + 1, slides.length - 1)), 4200);
    return () => clearInterval(id);
  }, [isLast, slides.length, resetKey]);

  const handleNext = () => {
    if (isLast) {
      markGreetingSeen();
      onComplete();
    } else {
      setIndex((i) => i + 1);
    }
  };

  return (
    <div className="flex flex-col px-4 pb-5 sm:px-7 sm:pb-7">
      <div className="relative min-h-[72px] sm:min-h-[88px]">
        <AnimatePresence mode="wait">
          <motion.p
            key={`${resetKey}-${index}`}
            initial={{ opacity: 0, x: 10 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -10 }}
            transition={{ duration: 0.28 }}
            className="text-[14px] leading-relaxed text-white/55 sm:text-[15px]"
          >
            {slides[index]}
          </motion.p>
        </AnimatePresence>
      </div>

      <div className="mt-4 flex items-center gap-1.5">
        {slides.map((_, i) => (
          <button
            key={i}
            type="button"
            onClick={() => setIndex(i)}
            aria-label={`Show intro slide ${i + 1} of ${slides.length}`}
            aria-current={i === index}
            className={cn(
              'h-1.5 rounded-full transition-all duration-300',
              i === index ? 'w-5 bg-[#FF1F2D]' : 'w-1.5 bg-white/15 hover:bg-white/30'
            )}
          />
        ))}
      </div>

      <div className="mt-5 flex items-center gap-4 sm:mt-6">
        <motion.button
          type="button"
          whileTap={{ scale: 0.97 }}
          onClick={handleNext}
          className="rounded-xl px-5 py-2.5 text-[13px] font-bold tracking-wide text-white transition-opacity hover:opacity-90"
          style={{ background: '#FF1F2D' }}
        >
          {isLast ? 'Continue →' : 'Next →'}
        </motion.button>
        {!isLast && (
          <button
            type="button"
            onClick={() => {
              markGreetingSeen();
              onComplete();
            }}
            className="shrink-0 text-[12.5px] text-white/30 transition-colors hover:text-white/55"
          >
            Skip
          </button>
        )}
      </div>
    </div>
  );
}

// Draggable circular avatar that opens an anchored popover. Setup, connecting,
// and the live call all morph inside this ONE popover — nothing ever
// navigates away from the landing page behind it.
export function AssistantPopover({
  faceId,
  language,
  name,
  canStart,
  isStarting = false,
  startLabel,
  trialRemainingSeconds,
  onTrialExpired,
  onNameChange,
  onAnchorChange,
  onStart,
}: AssistantPopoverProps) {
  const [open, setOpen] = useState(false);
  const [setupStep, setSetupStep] = useState<SetupStep>(() =>
    getGreetingSeen() ? 'config' : 'greeting'
  );
  const {
    isPhone,
    isNarrow,
    buttonSize,
    safeBottom,
    safeTop,
    safeLeft,
    safeRight,
  } = usePhoneLayout();
  const containerRef = useRef<HTMLDivElement>(null);
  const x = useMotionValue(0);
  const y = useMotionValue(0);
  const justDraggedRef = useRef(false);
  const buttonSizeRef = useRef(buttonSize);
  buttonSizeRef.current = buttonSize;

  const completeGreeting = useCallback(() => {
    markGreetingSeen();
    setSetupStep('config');
  }, []);

  // ── Live session plumbing ──────────────────────────────────────────────────
  const session = useSessionContext();
  const { messages } = useSessionMessages(session);
  const {
    state: agentState,
    audioTrack: agentAudioTrack,
    videoTrack: agentVideoTrack,
  } = useVoiceAssistant();
  const room = useRoomContext();
  const { name: roomName } = useRoomInfo();
  const { micTrackRef, microphoneToggle } = useInputControls({ saveUserChoices: true });

  const isConnected = session.isConnected;
  const fullyReady =
    agentState === 'listening' || agentState === 'speaking' || agentState === 'thinking';
  const phase: Phase = !isConnected ? 'setup' : fullyReady ? 'live' : 'connecting';
  const isAvatarVideo = agentVideoTrack !== undefined;
  const videoWidth = agentVideoTrack?.publication.dimensions?.width ?? 0;
  const videoHeight = agentVideoTrack?.publication.dimensions?.height ?? 0;
  const stateCfg = AGENT_STATE_CONFIG[agentState] ?? AGENT_STATE_CONFIG.disconnected;

  // Auto-open the popover the moment a call starts, so the morph is visible.
  useEffect(() => {
    if (isConnected) setOpen(true);
  }, [isConnected]);

  // Greet once per call — a brief "ready" banner the moment the anchor
  // actually becomes speak/listen-able, not just connected.
  const [showReadyBanner, setShowReadyBanner] = useState(false);
  const firstReadyRef = useRef(false);

  useEffect(() => {
    if (!isConnected) firstReadyRef.current = false;
  }, [isConnected]);

  useEffect(() => {
    if (fullyReady && !firstReadyRef.current) {
      firstReadyRef.current = true;
      setShowReadyBanner(true);
      const t = setTimeout(() => setShowReadyBanner(false), 4000);
      return () => clearTimeout(t);
    }
  }, [fullyReady]);

  // ── Trial countdown ────────────────────────────────────────────────────────
  const isPremium = trialRemainingSeconds === -1;
  const [timeLeft, setTimeLeft] = useState(-1);
  const trialEndedRef = useRef(false);

  useEffect(() => {
    if (isConnected) {
      trialEndedRef.current = false;
      setTimeLeft(trialRemainingSeconds ?? -1);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isConnected]);

  // ── Session stats + end-of-call save ──────────────────────────────────────
  const startTimeRef = useRef(0);
  const endSavedRef = useRef(false);
  const roomNameRef = useRef('');

  useEffect(() => {
    if (isConnected) {
      startTimeRef.current = Date.now();
      endSavedRef.current = false;
    }
  }, [isConnected]);

  useEffect(() => {
    if (roomName) roomNameRef.current = roomName;
  }, [roomName]);

  const saveSessionEnd = useCallback(() => {
    if (endSavedRef.current) return;
    endSavedRef.current = true;
    const deviceId = getDeviceId();
    const currentRoom = roomNameRef.current;
    if (!deviceId || !currentRoom) return;

    const duration = Math.round((Date.now() - startTimeRef.current) / 1000);
    const apiBase = process.env.NEXT_PUBLIC_API_URL ?? '';
    const payload = JSON.stringify({
      device_id: deviceId,
      room_name: currentRoom,
      duration_seconds: duration,
      messages_count: messages.length,
    });

    const sent = navigator.sendBeacon
      ? navigator.sendBeacon(
          `${apiBase}/api/session/end`,
          new Blob([payload], { type: 'application/json' })
        )
      : false;
    if (!sent) {
      fetch(`${apiBase}/api/session/end`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: payload,
        keepalive: true,
      }).catch(() => {});
    }
  }, [messages.length]);

  useEffect(() => {
    if (!isConnected && !endSavedRef.current && roomNameRef.current) {
      saveSessionEnd();
    }
  }, [isConnected, saveSessionEnd]);

  useEffect(() => {
    const handler = () => saveSessionEnd();
    window.addEventListener('pagehide', handler);
    window.addEventListener('beforeunload', handler);
    return () => {
      window.removeEventListener('pagehide', handler);
      window.removeEventListener('beforeunload', handler);
    };
  }, [saveSessionEnd]);

  useEffect(() => {
    if (!isConnected || isPremium || timeLeft <= 0) return;
    const id = setInterval(() => {
      setTimeLeft((t) => {
        const next = t - 1;
        if (next <= 0 && !trialEndedRef.current) {
          trialEndedRef.current = true;
          clearInterval(id);
          saveSessionEnd();
          session.end();
          onTrialExpired?.();
        }
        return Math.max(0, next);
      });
    }, 1000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isConnected, isPremium, saveSessionEnd, session, onTrialExpired]);

  // ── News video — the anchor triggers playback over the data channel ───────
  const [newsVideo, setNewsVideo] = useState<NewsVideo | null>(null);

  useEffect(() => {
    if (!room) return;
    const handler = (payload: Uint8Array) => {
      try {
        const msg = JSON.parse(new TextDecoder().decode(payload));
        if (msg?.type === 'news_video' && typeof msg.videoId === 'string') {
          setNewsVideo({
            videoId: msg.videoId,
            title: typeof msg.title === 'string' ? msg.title : 'Breaking News',
            topic: typeof msg.topic === 'string' ? msg.topic : 'this story',
          });
        }
      } catch {
        // not JSON / not for us — ignore
      }
    };
    room.on(RoomEvent.DataReceived, handler);
    return () => {
      room.off(RoomEvent.DataReceived, handler);
    };
  }, [room]);

  const handleNewsVideoClose = useCallback(
    (skipped: boolean) => {
      setNewsVideo((current) => {
        if (current && room) {
          room.localParticipant
            .publishData(
              new TextEncoder().encode(
                JSON.stringify({ type: 'news_video_ended', topic: current.topic, skipped })
              ),
              { reliable: true }
            )
            .catch(() => {});
        }
        return null;
      });
    },
    [room]
  );

  // ── Positioning (drag) ─────────────────────────────────────────────────────
  // Rests bottom-right on first paint / layout change. Clamp on resize so the
  // button never parks off-screen (esp. after rotation on phones).
  useEffect(() => {
    const placeBottomRight = () => {
      const el = containerRef.current;
      if (!el) return;
      const size = buttonSizeRef.current;
      const margin = isPhone ? EDGE_MARGIN_PHONE : EDGE_MARGIN_DESKTOP;
      const sab = readSafeInset('--sab');
      const sar = readSafeInset('--sar');
      x.set(el.clientWidth - size - margin - sar);
      y.set(el.clientHeight - size - margin - Math.max(sab, 8));
    };

    const id = requestAnimationFrame(placeBottomRight);

    const clampToViewport = () => {
      const el = containerRef.current;
      if (!el) return;
      const size = buttonSizeRef.current;
      const maxX = Math.max(0, el.clientWidth - size);
      const maxY = Math.max(0, el.clientHeight - size);
      x.set(Math.min(Math.max(x.get(), 0), maxX));
      y.set(Math.min(Math.max(y.get(), 0), maxY));
    };

    const onResize = () => {
      placeBottomRight();
      clampToViewport();
    };

    window.addEventListener('resize', onResize);
    window.addEventListener('orientationchange', onResize);
    window.visualViewport?.addEventListener('resize', onResize);

    return () => {
      cancelAnimationFrame(id);
      window.removeEventListener('resize', onResize);
      window.removeEventListener('orientationchange', onResize);
      window.visualViewport?.removeEventListener('resize', onResize);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isPhone, buttonSize]);

  const activeAvatar = ANCHORS.find((a) => a.id === faceId) ?? ANCHORS[0];

  const handleAnchorPick = (nextFaceId: string) => {
    const avatar = ANCHORS.find((a) => a.id === nextFaceId) ?? ANCHORS[0];
    const voice = (VOICE_MAP[language] ?? VOICE_MAP['en-US'])[avatar.slot];
    onAnchorChange(nextFaceId, voice, language, avatar.name);
  };

  const handleLanguagePick = (nextLanguage: string) => {
    const voice = (VOICE_MAP[nextLanguage] ?? VOICE_MAP['en-US'])[activeAvatar.slot];
    onAnchorChange(faceId, voice, nextLanguage, activeAvatar.name);
  };

  const handleGoLive = () => {
    if (!canStart) return;
    onStart();
  };

  const handleEndCall = () => {
    saveSessionEnd();
    session.end();
    setOpen(false);
  };

  // The avatar always shows a soft "available" pulse (CSS, always on); this
  // controls only the brighter overlay ring for open/connecting/live.
  const glowActive = open || phase !== 'setup';

  return (
    <div ref={containerRef} className="pointer-events-none fixed inset-0 z-[220]">
      <PopoverPrimitive.Root open={open} onOpenChange={setOpen}>
        <PopoverPrimitive.Trigger asChild>
          <motion.button
            drag
            dragConstraints={containerRef}
            dragMomentum={false}
            dragElastic={0.05}
            whileDrag={{ scale: 1.05 }}
            whileTap={{ scale: 0.96 }}
            onDragStart={() => {
              justDraggedRef.current = true;
            }}
            onDragEnd={() => {
              setTimeout(() => {
                justDraggedRef.current = false;
              }, 0);
            }}
            onClick={(e) => {
              if (justDraggedRef.current) {
                e.preventDefault();
                justDraggedRef.current = false;
              }
            }}
            style={{ x, y, position: 'absolute', top: 0, left: 0 }}
            aria-label={open ? 'Close anchor assistant' : 'Open anchor assistant'}
            className="pointer-events-auto flex touch-none items-center justify-center outline-none"
          >
            <span
              className="relative flex items-center justify-center"
              style={{ height: buttonSize, width: buttonSize }}
            >
              {/* Soft outer bloom */}
              <span
                aria-hidden
                className={cn(
                  'avatar-gemini-bloom absolute -inset-1 rounded-full',
                  glowActive && 'opacity-100'
                )}
              />
              {/* Gemini gradient ring only */}
              <span
                aria-hidden
                className={cn(
                  'avatar-gemini-ring absolute inset-0 rounded-full',
                  glowActive && 'avatar-gemini-ring-active'
                )}
              />
              <span
                className="relative overflow-hidden rounded-full border-2 border-[#0a0a0a] shadow-xl"
                style={{
                  height: Math.round(buttonSize * 0.84),
                  width: Math.round(buttonSize * 0.84),
                }}
              >
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={activeAvatar.image}
                  alt={activeAvatar.name}
                  draggable={false}
                  className="h-full w-full object-cover object-top"
                />
              </span>
            </span>
          </motion.button>
        </PopoverPrimitive.Trigger>

        <AnimatePresence>
          {open && (
            <PopoverPrimitive.Portal forceMount>
              <PopoverPrimitive.Content
                forceMount
                asChild
                side="top"
                align="end"
                sideOffset={isPhone ? 12 : 12}
                collisionPadding={{
                  // Extra top gap so the card never kisses / clips the status bar
                  top: Math.max(20, safeTop + 20),
                  bottom: Math.max(12, safeBottom + 8),
                  left: Math.max(10, safeLeft + 8),
                  right: Math.max(10, safeRight + 8),
                }}
                avoidCollisions
                aria-label={`${activeAvatar.name} anchor assistant`}
                onOpenAutoFocus={(e) => {
                  // Let the name input receive focus manually instead of the first
                  // focusable element (an anchor chip), which reads oddly to SRs.
                  e.preventDefault();
                }}
              >
                <motion.div
                  layout
                  initial={{ opacity: 0, scale: 0.95, y: 6 }}
                  animate={{ opacity: 1, scale: 1, y: 0 }}
                  exit={{ opacity: 0, scale: 0.95, y: 6 }}
                  transition={{ duration: 0.28, ease: 'easeOut' }}
                  className="pointer-events-auto relative z-[230]"
                  style={{
                    width: isPhone
                      ? `min(${POPOVER_WIDTH_DESKTOP}px, calc(100dvw - ${20 + safeLeft + safeRight}px))`
                      : POPOVER_WIDTH_DESKTOP,
                    maxWidth: `calc(100dvw - ${20 + safeLeft + safeRight}px)`,
                    // Always respect Radix available height — never force 100dvh
                    // (that was pushing the card into the top edge and clipping it).
                    maxHeight: 'var(--radix-popper-available-height, 80dvh)',
                    ...(phase === 'live'
                      ? {
                          height: 'var(--radix-popper-available-height, 80dvh)',
                        }
                      : {}),
                  }}
                >
                  {/* Arrow sits outside the clipped card below, so it isn't cut off */}
                  <PopoverPrimitive.Arrow
                    width={18}
                    height={9}
                    style={{ fill: 'rgba(17,17,17,0.72)' }}
                  />

                  <div
                    className="popover-border-glow relative flex h-full max-h-[inherit] flex-col overflow-hidden rounded-[22px] border backdrop-blur-2xl"
                    style={{
                      background:
                        'linear-gradient(180deg, rgba(26,26,26,0.62) 0%, rgba(17,17,17,0.72) 100%)',
                      borderColor: 'rgba(255,255,255,0.08)',
                    }}
                  >
                    <AnimatePresence mode="wait">
                      {phase === 'setup' && setupStep === 'greeting' && (
                        <motion.div
                          key="greeting"
                          initial={{ opacity: 0 }}
                          animate={{ opacity: 1 }}
                          exit={{ opacity: 0 }}
                          transition={{ duration: 0.18 }}
                          className="flex min-h-0 flex-col overflow-y-auto"
                        >
                          <div className="flex items-center gap-3 px-4 pt-5 pb-3 sm:gap-3.5 sm:px-7 sm:pt-7 sm:pb-4">
                            <span className="h-12 w-12 shrink-0 overflow-hidden rounded-full border border-white/10 sm:h-14 sm:w-14">
                              {/* eslint-disable-next-line @next/next/no-img-element */}
                              <img
                                src={activeAvatar.image}
                                alt={activeAvatar.name}
                                className="h-full w-full object-cover object-top"
                              />
                            </span>
                            <div className="min-w-0">
                              <p className="text-[16px] font-bold text-white sm:text-[18px]">
                                {activeAvatar.name}
                              </p>
                              <p className="text-[12px] text-white/40 sm:text-[12.5px]">
                                {activeAvatar.role}
                              </p>
                            </div>
                          </div>

                          <SetupStepIndicator step="greeting" />
                          <OnboardingGreeting
                            slides={activeAvatar.intros}
                            resetKey={activeAvatar.id}
                            onComplete={completeGreeting}
                          />
                        </motion.div>
                      )}

                      {phase === 'setup' && setupStep === 'config' && (
                        <motion.div
                          key="setup"
                          initial={{ opacity: 0 }}
                          animate={{ opacity: 1 }}
                          exit={{ opacity: 0 }}
                          transition={{ duration: 0.18 }}
                          className="flex min-h-0 flex-col overflow-y-auto overscroll-contain"
                        >
                          {/* Header */}
                          <div className="flex items-center gap-3 px-4 pt-5 pb-3 sm:gap-3.5 sm:px-7 sm:pt-7 sm:pb-4">
                            <span className="h-12 w-12 shrink-0 overflow-hidden rounded-full border border-white/10 sm:h-14 sm:w-14">
                              {/* eslint-disable-next-line @next/next/no-img-element */}
                              <img
                                src={activeAvatar.image}
                                alt={activeAvatar.name}
                                className="h-full w-full object-cover object-top"
                              />
                            </span>
                            <div className="min-w-0">
                              <p className="text-[16px] font-bold text-white sm:text-[18px]">
                                {activeAvatar.name}
                              </p>
                              <p className="text-[12px] text-white/40 sm:text-[12.5px]">
                                {activeAvatar.role}
                              </p>
                            </div>
                          </div>

                          <AnchorIntroSlider
                            slides={activeAvatar.intros}
                            resetKey={activeAvatar.id}
                          />

                          <div
                            className="mx-4 h-px sm:mx-7"
                            style={{ background: 'rgba(255,255,255,0.08)' }}
                          />

                          {/* Quick actions — switch anchor */}
                          <div className="px-4 pt-4 sm:px-7 sm:pt-5">
                            <p className="mb-2.5 font-mono text-[10px] tracking-[0.22em] text-white/30 uppercase">
                              Choose Anchor
                            </p>
                            <div className="flex gap-2 sm:gap-2.5">
                              {ANCHORS.map((av) => {
                                const isSel = av.id === faceId;
                                return (
                                  <button
                                    key={av.id}
                                    type="button"
                                    onClick={() => handleAnchorPick(av.id)}
                                    aria-pressed={isSel}
                                    className={cn(
                                      'flex-1 rounded-xl border py-2.5 text-[12px] font-bold tracking-wide transition-colors duration-150 sm:py-3 sm:text-[13px]',
                                      isSel
                                        ? 'border-[#FF1F2D]/60 text-white'
                                        : 'border-white/[0.08] text-white/40 hover:text-white/70'
                                    )}
                                    style={{
                                      background: isSel ? 'rgba(255,31,45,0.14)' : 'transparent',
                                    }}
                                  >
                                    {av.name}
                                  </button>
                                );
                              })}
                            </div>
                          </div>

                          {/* Language */}
                          <div className="relative px-4 pt-4 sm:px-7 sm:pt-5">
                            <LanguagePicker value={language} onChange={handleLanguagePick} />
                          </div>

                          {/* Name input */}
                          <div className="px-4 pt-4 sm:px-7 sm:pt-5">
                            <input
                              autoFocus={!isPhone}
                              type="text"
                              placeholder="Your name"
                              value={name}
                              maxLength={60}
                              onChange={(e) => onNameChange(e.target.value)}
                              onKeyDown={(e) => e.key === 'Enter' && handleGoLive()}
                              className="w-full rounded-xl border border-white/[0.08] bg-white/[0.04] px-4 py-3 text-[15px] text-white outline-none placeholder:text-white/25 focus:border-[#FF1F2D]/50 sm:py-3.5"
                            />
                          </div>

                          {/* Studio info — static, since there's one engine behind every anchor */}
                          <div className="px-4 pt-4 sm:px-7 sm:pt-5">
                            <div className="flex items-center justify-between rounded-xl border border-white/[0.06] bg-white/[0.02] px-4 py-3">
                              <span className="text-[11.5px] text-white/35">Model</span>
                              <span className="text-[11.5px] font-semibold text-white/60">
                                GenzCine Studio Engine
                              </span>
                            </div>
                          </div>

                          {/* CTA */}
                          <div
                            className="px-4 pt-5 pb-5 sm:px-7 sm:pt-6 sm:pb-7"
                            style={{
                              paddingBottom: isPhone
                                ? `max(1.25rem, ${safeBottom + 12}px)`
                                : undefined,
                            }}
                          >
                            <motion.button
                              whileTap={{ scale: canStart ? 0.97 : 1 }}
                              onClick={handleGoLive}
                              disabled={!canStart}
                              className={cn(
                                'w-full rounded-xl py-3.5 text-[15px] font-bold tracking-wide transition-opacity duration-150 sm:py-4',
                                canStart
                                  ? 'text-white hover:opacity-90'
                                  : 'cursor-not-allowed opacity-40'
                              )}
                              style={{
                                background: canStart ? '#FF1F2D' : 'rgba(255,255,255,0.08)',
                              }}
                            >
                              {isStarting ? 'Connecting…' : `${startLabel} →`}
                            </motion.button>
                          </div>
                        </motion.div>
                      )}

                      {phase === 'connecting' && (
                        <motion.div
                          key="connecting"
                          initial={{ opacity: 0 }}
                          animate={{ opacity: 1 }}
                          exit={{ opacity: 0 }}
                          transition={{ duration: 0.18 }}
                          className="flex flex-col items-center px-5 py-10 text-center sm:px-8 sm:py-14"
                        >
                          <span className="mb-6 h-16 w-16 overflow-hidden rounded-full border border-white/10">
                            {/* eslint-disable-next-line @next/next/no-img-element */}
                            <img
                              src={activeAvatar.image}
                              alt={activeAvatar.name}
                              className="h-full w-full object-cover object-top"
                            />
                          </span>
                          <p className="text-[18px] font-bold text-white">Going live…</p>
                          <p className="mt-1.5 mb-7 text-[13px] text-white/40">
                            {activeAvatar.name} is joining the broadcast
                          </p>
                          <div className="w-full max-w-[240px] space-y-4 text-left">
                            <LoadStep done={isConnected} label="Connecting to server" />
                            <LoadStep done={fullyReady} label="Starting your anchor" />
                          </div>
                          <button
                            onClick={handleEndCall}
                            className="mt-8 text-[12.5px] text-white/30 underline-offset-2 transition-colors hover:text-white/55"
                          >
                            Cancel
                          </button>
                        </motion.div>
                      )}

                      {phase === 'live' && (
                        <motion.div
                          key="live"
                          initial={{ opacity: 0 }}
                          animate={{ opacity: 1 }}
                          exit={{ opacity: 0 }}
                          transition={{ duration: 0.18 }}
                          className="flex h-full min-h-0 flex-col overflow-hidden"
                        >
                          {/* Video — takes remaining height after compact chat + controls */}
                          <div
                            className={cn(
                              'relative min-h-0 flex-1 overflow-hidden bg-black',
                              isPhone ? 'min-h-[160px]' : 'min-h-56 sm:min-h-64'
                            )}
                          >
                            <AnimatePresence>
                              {showReadyBanner && (
                                <motion.div
                                  key="ready-banner"
                                  initial={{ opacity: 0, y: -10 }}
                                  animate={{ opacity: 1, y: 0 }}
                                  exit={{ opacity: 0, y: -10 }}
                                  transition={{ duration: 0.3 }}
                                  className="absolute inset-x-2 top-2 z-10 flex items-center gap-2 rounded-full border border-emerald-500/25 bg-black/60 px-3 py-1.5 backdrop-blur-md sm:inset-x-3 sm:top-3 sm:px-3.5 sm:py-2"
                                >
                                  <span className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-emerald-400" />
                                  <p className="truncate text-[11px] font-medium text-emerald-200/90 sm:text-[12px]">
                                    {activeAvatar.name} is ready — start talking!
                                  </p>
                                </motion.div>
                              )}
                            </AnimatePresence>
                            {isAvatarVideo ? (
                              <VideoTrack
                                width={videoWidth}
                                height={videoHeight}
                                trackRef={agentVideoTrack}
                                className="h-full w-full object-cover"
                              />
                            ) : (
                              <>
                                {/* eslint-disable-next-line @next/next/no-img-element */}
                                <img
                                  src={activeAvatar.image}
                                  alt={activeAvatar.name}
                                  className="h-full w-full object-cover object-top"
                                />
                                <div className="absolute right-0 bottom-0 left-0 flex items-end justify-center bg-gradient-to-t from-black/70 to-transparent pt-10 pb-4">
                                  <div className="flex h-9 w-20 items-center justify-center overflow-hidden rounded-xl border border-white/10 bg-black/40 backdrop-blur-sm">
                                    <BarVisualizer
                                      barCount={5}
                                      state={agentState}
                                      options={{ minHeight: 5 }}
                                      trackRef={agentAudioTrack}
                                      className="flex h-full items-center justify-center gap-1"
                                    >
                                      <span className="min-h-2 w-1.5 rounded-full bg-white/20 transition-colors duration-150 data-[lk-highlighted=true]:bg-white data-[lk-muted=true]:bg-white/15" />
                                    </BarVisualizer>
                                  </div>
                                </div>
                              </>
                            )}
                            {!isPremium && timeLeft >= 0 && (
                              <span
                                className={cn(
                                  'absolute top-2 right-2 rounded-full border px-2 py-0.5 font-mono text-[10px] backdrop-blur-sm sm:top-3 sm:right-3 sm:px-2.5 sm:py-1 sm:text-[10.5px]',
                                  timeLeft <= 30
                                    ? 'animate-pulse border-red-500/40 bg-red-950/70 text-red-300'
                                    : timeLeft <= 60
                                      ? 'border-amber-500/30 bg-amber-950/60 text-amber-300'
                                      : 'border-white/10 bg-black/40 text-white/60'
                                )}
                              >
                                {String(Math.floor(timeLeft / 60)).padStart(2, '0')}:
                                {String(timeLeft % 60).padStart(2, '0')}
                              </span>
                            )}
                          </div>

                          {/* Info bar */}
                          <div className="flex shrink-0 items-center gap-2.5 border-b border-white/[0.06] px-3 py-2.5 sm:gap-3 sm:px-5 sm:py-3">
                            <span className="h-7 w-7 shrink-0 overflow-hidden rounded-full border border-white/10 sm:h-8 sm:w-8">
                              {/* eslint-disable-next-line @next/next/no-img-element */}
                              <img
                                src={activeAvatar.image}
                                alt={activeAvatar.name}
                                className="h-full w-full object-cover object-top"
                              />
                            </span>
                            <div className="min-w-0 flex-1">
                              <p className="truncate text-[13px] font-bold text-white sm:text-[13.5px]">
                                {activeAvatar.name}
                              </p>
                              <span className="flex items-center gap-1.5">
                                <span
                                  className={cn('h-1.5 w-1.5 rounded-full', stateCfg.dotClass)}
                                />
                                <span className="text-[11px] text-white/45">{stateCfg.label}</span>
                              </span>
                            </div>
                            <span className="shrink-0 rounded-full border border-emerald-500/25 bg-emerald-500/10 px-2 py-0.5 text-[9px] font-semibold tracking-wide text-emerald-300 uppercase sm:px-2.5 sm:py-1 sm:text-[10px]">
                              Connected
                            </span>
                          </div>

                          {/* Chat — compact fixed height, scrolls internally */}
                          <div className="mt-2 shrink-0 px-3 sm:mt-3 sm:px-5">
                            <ScrollArea className="h-24 overscroll-contain sm:h-32">
                              <ChatTranscript messages={messages} className="space-y-2 pb-1" />
                            </ScrollArea>
                          </div>

                          {/* Controls */}
                          <div
                            className="mt-2 flex shrink-0 items-center gap-2 border-t border-white/[0.06] px-3 pt-3 sm:mt-3 sm:gap-2.5 sm:px-5 sm:pt-4"
                            style={{
                              paddingBottom: `max(${isPhone ? 12 : 16}px, ${safeBottom + 8}px)`,
                            }}
                          >
                            <button
                              onClick={() => microphoneToggle.toggle()}
                              disabled={microphoneToggle.pending}
                              aria-pressed={microphoneToggle.enabled}
                              aria-label={
                                microphoneToggle.enabled ? 'Mute microphone' : 'Unmute microphone'
                              }
                              className={cn(
                                'flex h-11 w-11 shrink-0 items-center justify-center rounded-full border transition-colors sm:h-12 sm:w-12',
                                microphoneToggle.enabled
                                  ? 'border-white/10 bg-white/[0.06] text-white'
                                  : 'border-[#FF1F2D]/40 bg-[#FF1F2D]/15 text-[#FF1F2D]'
                              )}
                            >
                              {microphoneToggle.enabled ? (
                                <MicrophoneIcon weight="bold" className="size-[18px] sm:size-[19px]" />
                              ) : (
                                <MicrophoneSlashIcon
                                  weight="bold"
                                  className="size-[18px] sm:size-[19px]"
                                />
                              )}
                            </button>

                            <div className="flex min-w-0 flex-1 items-center gap-2">
                              <span className="font-mono text-[10px] tracking-wide text-white/30 uppercase">
                                You
                              </span>
                              <div className="flex h-5 flex-1 items-center gap-[3px] overflow-hidden">
                                {microphoneToggle.enabled ? (
                                  <BarVisualizer
                                    barCount={isNarrow ? 8 : 12}
                                    options={{ minHeight: 15 }}
                                    trackRef={micTrackRef}
                                    className="flex h-full w-full items-center gap-[3px]"
                                  >
                                    <span className="h-full min-h-1 w-1 rounded-full bg-white/15 transition-colors duration-150 data-[lk-highlighted=true]:bg-[#FF1F2D]" />
                                  </BarVisualizer>
                                ) : (
                                  <span className="text-[11px] text-white/25">Muted</span>
                                )}
                              </div>
                            </div>

                            <button
                              onClick={handleEndCall}
                              className="flex shrink-0 items-center gap-1.5 rounded-full bg-[#FF1F2D] px-4 py-2.5 text-[13px] font-bold text-white transition-opacity hover:opacity-90 sm:gap-2 sm:px-5 sm:py-3 sm:text-[13.5px]"
                            >
                              <PhoneDisconnectIcon weight="bold" className="size-[16px] sm:size-[17px]" />
                              End
                            </button>
                          </div>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>
                </motion.div>
              </PopoverPrimitive.Content>
            </PopoverPrimitive.Portal>
          )}
        </AnimatePresence>
      </PopoverPrimitive.Root>

      {/* News video overlay — a distinct visual moment the anchor triggers,
          intentionally full-screen since a popover can't do it justice. */}
      <AnimatePresence>
        {newsVideo && (
          <Suspense fallback={null}>
            <NewsVideoPlayer video={newsVideo} onClose={handleNewsVideoClose} />
          </Suspense>
        )}
      </AnimatePresence>
    </div>
  );
}

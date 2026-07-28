'use client';

import React, { Suspense, lazy, useCallback, useEffect, useRef, useState } from 'react';
import { RoomEvent } from 'livekit-client';
import { AnimatePresence, motion } from 'motion/react';
import {
  useRoomContext,
  useRoomInfo,
  useSessionContext,
  useSessionMessages,
  useVoiceAssistant,
} from '@livekit/components-react';
import type { AppConfig } from '@/app-config';
import { ChatTranscript } from '@/components/app/chat-transcript';
import type { DemoVideo } from '@/components/app/demo-video-player';
import { TileLayout } from '@/components/app/tile-layout';
import {
  AgentControlBar,
  type ControlBarControls,
} from '@/components/livekit/agent-control-bar/agent-control-bar';
import { getDeviceId } from '@/lib/device';
import { preloadPoseLandmarker } from '@/lib/mediapipe-preload';
import { cn } from '@/lib/utils';
import { ScrollArea } from '../livekit/scroll-area/scroll-area';

const PostureCamera = lazy(() => import('@/components/app/posture-camera'));
const DemoVideoPlayer = lazy(() => import('@/components/app/demo-video-player'));

// ── Loading step indicator ────────────────────────────────────────────────────
function LoadStep({ done, label }: { done: boolean; label: string }) {
  return (
    <div className="flex items-center gap-3">
      <div className="relative flex h-5 w-5 shrink-0 items-center justify-center">
        {done ? (
          <motion.div
            key="done"
            initial={{ scale: 0 }}
            animate={{ scale: 1 }}
            className="flex h-5 w-5 items-center justify-center rounded-full bg-green-500/20"
          >
            <svg
              width="10"
              height="10"
              viewBox="0 0 12 12"
              fill="none"
              stroke="#22c55e"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <polyline points="2,6 5,9 10,3" />
            </svg>
          </motion.div>
        ) : (
          <div className="h-4 w-4 animate-spin rounded-full border border-white/10 border-t-red-600" />
        )}
      </div>
      <span
        className={cn(
          'font-mono text-[11px] tracking-wide transition-colors duration-500',
          done ? 'text-white/50' : 'text-white/70'
        )}
      >
        {label}
      </span>
    </div>
  );
}

interface SessionViewProps {
  appConfig: AppConfig;
  groupRoomCode?: string | null;
  trialRemainingSeconds?: number;
  onTrialExpired?: () => void;
}

export const SessionView = ({
  appConfig,
  groupRoomCode,
  trialRemainingSeconds,
  onTrialExpired,
  ...props
}: React.ComponentProps<'section'> & SessionViewProps) => {
  const session = useSessionContext();
  const { messages } = useSessionMessages(session);
  const { state: agentState } = useVoiceAssistant();
  const { name: roomName } = useRoomInfo();
  const room = useRoomContext();

  const [chatOpen, setChatOpen] = useState(true);
  const [copied, setCopied] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [postureOpen, setPostureOpen] = useState(false);
  const [demoVideo, setDemoVideo] = useState<DemoVideo | null>(null);
  const scrollAreaRef = useRef<HTMLDivElement>(null);

  // ── Trial countdown ───────────────────────────────────────────────────────
  const isPremium = trialRemainingSeconds === -1;
  const [timeLeft, setTimeLeft] = useState<number>(isPremium ? -1 : (trialRemainingSeconds ?? 300));
  const trialEndedRef = useRef(false);

  const onTrialExpiredRef = useRef(onTrialExpired);
  useEffect(() => {
    onTrialExpiredRef.current = onTrialExpired;
  }, [onTrialExpired]);

  useEffect(() => {
    if (isPremium || timeLeft <= 0) return;
    const id = setInterval(() => {
      setTimeLeft((t) => {
        const next = t - 1;
        if (next <= 0 && !trialEndedRef.current) {
          trialEndedRef.current = true;
          clearInterval(id);
          saveSessionEnd();
          session.end();
          onTrialExpiredRef.current?.();
        }
        return Math.max(0, next);
      });
    }, 1000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isPremium]);

  // ── Readiness tracking ────────────────────────────────────────────────────
  const [mpReady, setMpReady] = useState(false);
  const [novaReadyBanner, setNovaReadyBanner] = useState(false);
  const firstReadyRef = useRef(false);

  const lkConnected = agentState !== 'connecting';
  const agentStarted = agentState !== 'connecting' && agentState !== 'initializing';
  const fullyReady =
    agentState === 'listening' || agentState === 'speaking' || agentState === 'thinking';

  // ── Session stats tracking ────────────────────────────────────────────────
  const startTimeRef = useRef<number>(Date.now());
  const postureCountRef = useRef(0);
  const endSavedRef = useRef(false);
  const roomNameRef = useRef('');

  // Keep roomNameRef in sync (roomName arrives after connect)
  useEffect(() => {
    if (roomName) roomNameRef.current = roomName;
  }, [roomName]);

  const saveSessionEnd = useCallback(() => {
    if (endSavedRef.current) return;
    endSavedRef.current = true;
    const deviceId = getDeviceId();
    const room = roomNameRef.current;
    if (!deviceId || !room) return;

    const duration = Math.round((Date.now() - startTimeRef.current) / 1000);
    const apiBase = process.env.NEXT_PUBLIC_API_URL ?? '';
    const payload = JSON.stringify({
      device_id: deviceId,
      room_name: room,
      duration_seconds: duration,
      messages_count: messages.length,
      posture_analyses: postureCountRef.current,
    });

    // sendBeacon works even when page is unloading
    const sent = navigator.sendBeacon
      ? navigator.sendBeacon(
          `${apiBase}/api/session/end`,
          new Blob([payload], { type: 'application/json' })
        )
      : false;

    // Fallback for browsers without sendBeacon
    if (!sent) {
      fetch(`${apiBase}/api/session/end`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: payload,
        keepalive: true,
      }).catch(() => {});
    }
  }, [messages.length]);

  // Fire saveSessionEnd when LiveKit disconnects
  useEffect(() => {
    if (!session.isConnected && endSavedRef.current === false && roomNameRef.current) {
      saveSessionEnd();
    }
  }, [session.isConnected, saveSessionEnd]);

  // Fire saveSessionEnd on page unload (browser close / navigate away)
  useEffect(() => {
    const handler = () => saveSessionEnd();
    window.addEventListener('pagehide', handler);
    window.addEventListener('beforeunload', handler);
    return () => {
      window.removeEventListener('pagehide', handler);
      window.removeEventListener('beforeunload', handler);
    };
  }, [saveSessionEnd]);

  const handlePostureAnalysisSent = useCallback(() => {
    postureCountRef.current += 1;
  }, []);

  // ── Demo video — NOVA triggers playback over the data channel ─────────────
  useEffect(() => {
    if (!room) return;
    const handler = (payload: Uint8Array) => {
      try {
        const msg = JSON.parse(new TextDecoder().decode(payload));
        if (msg?.type === 'demo_video' && typeof msg.url === 'string') {
          setDemoVideo({
            url: msg.url,
            title: typeof msg.title === 'string' ? msg.title : 'Ramp Walk Demo',
            demo: Number(msg.demo) || 0,
            loops: Math.max(1, Number(msg.loops) || 1),
            cues: Array.isArray(msg.cues)
              ? msg.cues.filter((t: unknown): t is number => typeof t === 'number')
              : [],
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

  const handleDemoVideoClose = useCallback(
    (skipped: boolean) => {
      setDemoVideo((current) => {
        if (current && room) {
          room.localParticipant
            .publishData(
              new TextEncoder().encode(
                JSON.stringify({ type: 'demo_video_ended', demo: current.demo, skipped })
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

  // Pre-load MediaPipe WASM in background while agent is connecting
  useEffect(() => {
    preloadPoseLandmarker().then(() => setMpReady(true));
  }, []);

  // Show "NOVA ready" banner exactly once — when she first becomes active
  useEffect(() => {
    if (fullyReady && !firstReadyRef.current) {
      firstReadyRef.current = true;
      setNovaReadyBanner(true);
      const t = setTimeout(() => setNovaReadyBanner(false), 4500);
      return () => clearTimeout(t);
    }
  }, [fullyReady]);

  useEffect(() => {
    if (groupRoomCode) setShowModal(true);
  }, [groupRoomCode]);

  useEffect(() => {
    const lastMessage = messages.at(-1);
    if (scrollAreaRef.current && lastMessage?.from?.isLocal === true) {
      scrollAreaRef.current.scrollTop = scrollAreaRef.current.scrollHeight;
    }
  }, [messages]);

  const handleCopy = () => {
    if (!groupRoomCode) return;
    navigator.clipboard.writeText(groupRoomCode).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  const controls: ControlBarControls = {
    leave: true,
    microphone: true,
    chat: appConfig.supportsChatInput,
    camera: appConfig.supportsVideoInput,
    screenShare: appConfig.supportsVideoInput,
  };

  return (
    <section className="relative h-full w-full overflow-hidden bg-[#080808]" {...props}>
      {/* ── Loading overlay — visible until NOVA is fully ready ── */}
      <AnimatePresence>
        {!fullyReady && (
          <motion.div
            key="loading-overlay"
            initial={{ opacity: 1 }}
            exit={{ opacity: 0, transition: { duration: 0.6, ease: 'easeOut' } }}
            className="fixed inset-0 z-[350] flex flex-col items-center justify-center bg-[#080808]"
          >
            {/* Ambient glow */}
            <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_60%_50%_at_50%_50%,rgba(230,57,70,0.06),transparent_70%)]" />

            {/* Logo / name */}
            <motion.div
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.1 }}
              className="relative mb-12 text-center"
            >
              <div className="mb-2 inline-block rounded-2xl border border-red-600/20 bg-red-600/[0.07] px-5 py-1.5">
                <span className="font-mono text-[10px] tracking-[0.3em] text-red-400/70 uppercase">
                  GenzCine
                </span>
              </div>
              <h1 className="text-4xl font-black tracking-tight text-white">NOVA</h1>
              <p className="mt-1.5 font-mono text-[11px] tracking-widest text-white/25 uppercase">
                AI Ramp Walk Trainer
              </p>
            </motion.div>

            {/* Steps */}
            <motion.div
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.25 }}
              className="w-56 space-y-4"
            >
              <LoadStep done={lkConnected} label="Connecting to server" />
              <LoadStep done={agentStarted} label="Starting NOVA" />
              <LoadStep done={mpReady} label="Loading camera AI" />
            </motion.div>

            {/* Waiting hint */}
            <motion.p
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 1.5 }}
              className="absolute bottom-16 font-mono text-[10px] tracking-widest text-white/15 uppercase"
            >
              Please wait…
            </motion.p>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── "NOVA ready" banner ── */}
      <AnimatePresence>
        {novaReadyBanner && (
          <motion.div
            key="nova-ready"
            initial={{ opacity: 0, y: -16 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -16 }}
            transition={{ duration: 0.35 }}
            className="fixed inset-x-4 z-[300] flex items-center gap-3 rounded-2xl border border-green-500/20 bg-[#070f07]/95 px-4 py-3 shadow-xl backdrop-blur-xl"
            style={{ top: 'max(env(safe-area-inset-top, 0px), 56px)' }}
          >
            <span className="h-2 w-2 animate-pulse rounded-full bg-green-500" />
            <p className="text-[13px] font-medium text-green-200/90">
              NOVA is ready — start talking!
            </p>
            {mpReady && (
              <span className="ml-auto font-mono text-[10px] text-green-500/40">Camera AI ✓</span>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── Group room code modal ── */}
      <AnimatePresence>
        {showModal && groupRoomCode && (
          <motion.div
            key="room-code-modal"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="fixed inset-0 z-[300] flex items-center justify-center"
          >
            <div
              className="absolute inset-0 bg-black/50 backdrop-blur-sm"
              onClick={() => setShowModal(false)}
            />
            <motion.div
              initial={{ scale: 0.9, opacity: 0, y: 10 }}
              animate={{ scale: 1, opacity: 1, y: 0 }}
              exit={{ scale: 0.9, opacity: 0, y: 10 }}
              transition={{ duration: 0.25, ease: 'easeOut' }}
              className="border-border bg-background relative z-10 mx-4 w-full max-w-sm rounded-2xl border p-6 shadow-2xl"
            >
              <button
                onClick={() => setShowModal(false)}
                className="text-muted-foreground hover:text-foreground absolute top-4 right-4 transition-colors"
              >
                <svg
                  width="18"
                  height="18"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <line x1="18" y1="6" x2="6" y2="18" />
                  <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </button>
              <div className="mb-5">
                <div className="bg-primary/10 text-primary mb-3 inline-flex items-center gap-1.5 rounded-full px-3 py-1 font-mono text-xs font-bold tracking-wider uppercase">
                  <span className="bg-primary h-1.5 w-1.5 rounded-full" />
                  Group Session Active
                </div>
                <h2 className="text-foreground text-lg font-semibold">Share this room code</h2>
                <p className="text-muted-foreground mt-1 text-sm">
                  Others can join by entering this code on the home screen.
                </p>
              </div>
              <div className="border-border bg-muted/40 mb-5 flex items-center justify-between rounded-xl border px-4 py-3">
                <span className="text-foreground font-mono text-base font-bold tracking-wide select-all">
                  {groupRoomCode}
                </span>
                <button
                  onClick={handleCopy}
                  className={cn(
                    'ml-3 flex items-center gap-1.5 rounded-lg px-3 py-1.5 font-mono text-xs font-semibold transition-all',
                    copied
                      ? 'bg-green-500/10 text-green-500'
                      : 'bg-primary/10 text-primary hover:bg-primary/20'
                  )}
                >
                  {copied ? 'Copied!' : 'Copy'}
                </button>
              </div>
              <button
                onClick={() => setShowModal(false)}
                className="bg-primary text-primary-foreground w-full rounded-xl py-2.5 font-mono text-sm font-bold tracking-wide transition-opacity hover:opacity-90"
              >
                Start Training →
              </button>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── Small group badge ── */}
      {groupRoomCode && !showModal && (
        <button
          onClick={() => setShowModal(true)}
          className="fixed top-4 right-4 z-[200] flex cursor-pointer items-center gap-2 rounded-full border border-white/10 bg-black/60 px-3 py-1.5 font-mono text-xs shadow-sm backdrop-blur-md transition-colors hover:bg-black/80"
        >
          <span className="h-1.5 w-1.5 rounded-full bg-green-500" />
          <span className="font-bold tracking-wider text-red-400 uppercase">Group</span>
          <span className="text-white/60">{groupRoomCode}</span>
        </button>
      )}

      {/* ── Trial countdown chip ── */}
      {!isPremium && timeLeft >= 0 && (
        <div
          className={cn(
            'fixed z-[200] flex items-center gap-2 rounded-full border px-3 py-1.5 font-mono text-xs shadow-sm backdrop-blur-md transition-colors',
            groupRoomCode ? 'top-14 right-4' : 'top-4 right-4',
            timeLeft <= 30
              ? 'animate-pulse border-red-500/40 bg-red-950/70 text-red-300'
              : timeLeft <= 60
                ? 'border-amber-500/30 bg-amber-950/60 text-amber-300'
                : 'border-white/10 bg-black/60 text-white/60'
          )}
        >
          <svg
            width="10"
            height="10"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.5"
            strokeLinecap="round"
          >
            <circle cx="12" cy="12" r="10" />
            <polyline points="12 6 12 12 16 14" />
          </svg>
          <span>
            {String(Math.floor(timeLeft / 60)).padStart(2, '0')}:
            {String(timeLeft % 60).padStart(2, '0')}
          </span>
          <span className="text-white/30">trial</span>
        </div>
      )}

      {/* ── Full-screen Simli avatar ── */}
      <TileLayout />

      {/* ── Gradient fade into glass panel ── */}
      <div
        className="pointer-events-none fixed inset-x-0 z-10 h-28 bg-gradient-to-t from-black/90 to-transparent"
        style={{ bottom: 240 }}
      />

      {/* ── Glass transcript + controls panel ── */}
      <div
        className="fixed inset-x-0 bottom-0 z-20 border-t border-white/[0.06] bg-[#080808]/80 backdrop-blur-2xl"
        style={{ paddingBottom: 'env(safe-area-inset-bottom, 0px)' }}
      >
        {/* Subtle top accent line */}
        <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-red-600/20 to-transparent" />

        {/* Centered on desktop, full width on mobile */}
        <div className="mx-auto w-full max-w-2xl lg:max-w-3xl">
          {/* Transcript label */}
          <div className="flex items-center gap-2 px-4 pt-2.5 pb-1">
            <span className="font-mono text-[9px] tracking-[0.22em] text-white/18 uppercase">
              Transcript
            </span>
            <div className="h-px flex-1 bg-white/[0.05]" />
          </div>

          {/* Messages — fixed height scroll area */}
          <ScrollArea ref={scrollAreaRef} className="h-[130px] px-3 sm:h-[148px] md:h-[180px]">
            <ChatTranscript hidden={!chatOpen} messages={messages} className="space-y-2 pb-1" />
          </ScrollArea>

          {/* Divider */}
          <div className="mx-3 h-px bg-white/[0.05]" />

          {/* Controls */}
          <div className="flex items-center gap-2 px-3 py-2.5">
            <AgentControlBar
              controls={controls}
              isConnected={session.isConnected}
              onDisconnect={session.end}
              onChatOpenChange={setChatOpen}
            />
            {/* Posture camera toggle */}
            <button
              onClick={() => setPostureOpen(true)}
              title="Open posture camera"
              className={cn(
                'flex h-10 w-10 shrink-0 items-center justify-center rounded-full border transition-all duration-200',
                postureOpen
                  ? 'border-red-600/60 bg-red-600/20 text-red-400'
                  : 'border-white/[0.08] bg-white/[0.05] text-white/50 hover:border-red-600/40 hover:text-white/80'
              )}
            >
              <svg
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <circle cx="12" cy="5" r="2" />
                <path d="M12 7v6" />
                <path d="M8 11l4 2 4-2" />
                <path d="M10 17v4" />
                <path d="M14 17v4" />
                <path d="M10 13l-2 4" />
                <path d="M14 13l2 4" />
              </svg>
            </button>
          </div>
        </div>
      </div>

      {/* Posture camera overlay */}
      <AnimatePresence>
        {postureOpen && (
          <Suspense fallback={null}>
            <PostureCamera
              onClose={() => setPostureOpen(false)}
              onAnalysisSent={handlePostureAnalysisSent}
            />
          </Suspense>
        )}
      </AnimatePresence>

      {/* Demo video overlay — triggered by NOVA after every 2 lessons */}
      <AnimatePresence>
        {demoVideo && (
          <Suspense fallback={null}>
            <DemoVideoPlayer video={demoVideo} onClose={handleDemoVideoClose} />
          </Suspense>
        )}
      </AnimatePresence>
    </section>
  );
};

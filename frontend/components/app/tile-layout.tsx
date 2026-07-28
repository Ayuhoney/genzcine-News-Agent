'use client';

import { useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion, useMotionValue } from 'motion/react';
import {
  BarVisualizer,
  VideoTrack,
  useRoomInfo,
  useVoiceAssistant,
} from '@livekit/components-react';

export const GLASS_PANEL_H = 240;

const MIN_W = 130;
const MAX_W = 340;
const MIN_H = 165;
const MAX_H = 460;

type CardState =
  | 'speaking'
  | 'listening'
  | 'thinking'
  | 'initializing'
  | 'connecting'
  | 'disconnected';

const STATE_CONFIG: Record<
  CardState,
  { label: string; dotClass: string; glow: string; borderColor: string }
> = {
  speaking: {
    label: 'Speaking',
    dotClass: 'bg-red-500',
    glow: '0 0 28px 6px rgba(230,57,70,0.22), 0 0 60px 18px rgba(230,57,70,0.07)',
    borderColor: 'rgba(230,57,70,0.35)',
  },
  listening: {
    label: 'Listening',
    dotClass: 'bg-emerald-400',
    glow: '0 0 22px 5px rgba(52,211,153,0.14), 0 0 50px 14px rgba(52,211,153,0.05)',
    borderColor: 'rgba(52,211,153,0.25)',
  },
  thinking: {
    label: 'Thinking',
    dotClass: 'bg-amber-400 animate-pulse',
    glow: '0 0 20px 4px rgba(251,191,36,0.10)',
    borderColor: 'rgba(251,191,36,0.20)',
  },
  initializing: {
    label: 'Starting',
    dotClass: 'bg-white/25 animate-pulse',
    glow: 'none',
    borderColor: 'rgba(255,255,255,0.07)',
  },
  connecting: {
    label: 'Connecting',
    dotClass: 'bg-white/25 animate-pulse',
    glow: 'none',
    borderColor: 'rgba(255,255,255,0.07)',
  },
  disconnected: {
    label: 'Offline',
    dotClass: 'bg-white/15',
    glow: 'none',
    borderColor: 'rgba(255,255,255,0.06)',
  },
};

export function TileLayout() {
  const containerRef = useRef<HTMLDivElement>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const x = useMotionValue(0);
  const y = useMotionValue(0);

  const [cardSize, setCardSize] = useState<{ w: number; h: number } | null>(null);

  const { metadata: roomMetadata } = useRoomInfo();

  // Metadata is JSON {"face_id":"...","voice":"..."}, fallback: plain face_id string
  const parsedMeta = (() => {
    try {
      return JSON.parse(roomMetadata ?? '{}');
    } catch {
      return {};
    }
  })();
  const activeFaceId: string = parsedMeta.face_id ?? roomMetadata ?? '';

  const NOVA = process.env.NEXT_PUBLIC_NOVA_FACE_ID ?? 'b9e5fba3-071a-4e35-896e-211c4d6eaa7b';
  const ARIA = process.env.NEXT_PUBLIC_ARIA_FACE_ID ?? 'afdb6a3e-3939-40aa-92df-01604c23101c';
  const MARK = process.env.NEXT_PUBLIC_MARK_FACE_ID ?? 'dd10cb5a-d31d-4f12-b69f-6db3383c006e';

  const FACE_NAMES: Record<string, string> = {
    [NOVA]: 'NOVA',
    [ARIA]: 'ARIA',
    [MARK]: 'MARK',
  };
  const FACE_IMAGES: Record<string, string> = {
    [NOVA]: '/avatar-nova.png',
    [ARIA]: '/avatar-aria.png',
    [MARK]: '/avatar-mark.png',
  };
  const avatarName = FACE_NAMES[activeFaceId] ?? 'NOVA';
  const avatarImage = FACE_IMAGES[activeFaceId] ?? '/avatar-nova.png';

  // Resize state
  const resizing = useRef(false);
  const lastPtr = useRef({ x: 0, y: 0 });

  const {
    state: agentState,
    audioTrack: agentAudioTrack,
    videoTrack: agentVideoTrack,
  } = useVoiceAssistant();

  const isAvatar = agentVideoTrack !== undefined;
  const videoWidth = agentVideoTrack?.publication.dimensions?.width ?? 0;
  const videoHeight = agentVideoTrack?.publication.dimensions?.height ?? 0;
  const cfg = STATE_CONFIG[agentState as CardState] ?? STATE_CONFIG.disconnected;

  // Centre card after first paint
  useEffect(() => {
    const id = requestAnimationFrame(() => {
      if (!containerRef.current || !cardRef.current) return;
      const cw = containerRef.current.clientWidth;
      const ew = cardRef.current.offsetWidth;
      const eh = cardRef.current.offsetHeight;
      x.set((cw - ew) / 2);
      y.set(16);
      setCardSize({ w: ew, h: eh });
    });
    return () => cancelAnimationFrame(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* ── Resize pointer handlers ── */
  const onResizeDown = (e: React.PointerEvent) => {
    // Prevent the parent drag from starting
    e.stopPropagation();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    resizing.current = true;
    lastPtr.current = { x: e.clientX, y: e.clientY };
  };

  const onResizeMove = (e: React.PointerEvent) => {
    if (!resizing.current) return;
    e.stopPropagation();
    const dx = e.clientX - lastPtr.current.x;
    const dy = e.clientY - lastPtr.current.y;
    lastPtr.current = { x: e.clientX, y: e.clientY };
    setCardSize((prev) => {
      if (!prev) return prev;
      return {
        w: Math.round(Math.max(MIN_W, Math.min(MAX_W, prev.w + dx))),
        h: Math.round(Math.max(MIN_H, Math.min(MAX_H, prev.h + dy))),
      };
    });
  };

  const onResizeUp = () => {
    resizing.current = false;
  };

  const cardStyle = cardSize
    ? { width: cardSize.w, height: cardSize.h }
    : { width: 'clamp(160px, 48vw, 224px)', height: 'clamp(205px, 61vw, 286px)' };

  return (
    <div
      ref={containerRef}
      className="fixed inset-x-0 top-0 z-10 overflow-hidden bg-[#080808]"
      style={{
        bottom: GLASS_PANEL_H,
        paddingTop: 'env(safe-area-inset-top, 0px)',
      }}
    >
      {/* Very subtle ambient glow */}
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_60%_40%_at_50%_40%,rgba(230,57,70,0.04),transparent_70%)]" />

      {/* ── Draggable wrapper ── */}
      <motion.div
        drag
        dragConstraints={containerRef}
        dragMomentum={false}
        dragElastic={0.04}
        style={{ x, y, position: 'absolute', top: 0, left: 0 }}
        whileDrag={{ scale: 1.015 }}
        className="cursor-grab touch-none active:cursor-grabbing"
      >
        {/* State-aware outer glow */}
        <motion.div
          animate={{ boxShadow: cfg.glow }}
          transition={{ duration: 0.7, ease: 'easeInOut' }}
          className="rounded-[26px]"
        >
          {/* Card shell — resizable */}
          <motion.div
            ref={cardRef}
            animate={{ borderColor: cfg.borderColor }}
            transition={{ duration: 0.6 }}
            className="relative overflow-hidden rounded-[26px] border"
            style={cardStyle}
          >
            <AnimatePresence mode="popLayout">
              {!isAvatar ? (
                <motion.div
                  key="audio"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.35 }}
                  className="relative h-full w-full"
                >
                  {/* Static avatar image fallback (shown when Simli is unavailable) */}
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={avatarImage}
                    alt={avatarName}
                    className="h-full w-full object-cover object-top"
                  />
                  {/* Audio visualizer overlay at bottom */}
                  <div className="absolute right-0 bottom-0 left-0 flex items-end justify-center bg-gradient-to-t from-black/60 to-transparent pt-8 pb-3">
                    <div className="flex h-8 w-16 items-center justify-center overflow-hidden rounded-xl border border-white/10 bg-black/40 backdrop-blur-sm">
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
                </motion.div>
              ) : (
                <motion.div
                  key="avatar"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.5 }}
                  className="relative h-full w-full bg-black"
                >
                  <VideoTrack
                    width={videoWidth}
                    height={videoHeight}
                    trackRef={agentVideoTrack}
                    className="h-full w-full object-cover"
                  />
                </motion.div>
              )}
            </AnimatePresence>

            {/* ── Resize handle — bottom-right corner ── */}
            <div
              className="absolute right-0 bottom-0 z-20 flex h-11 w-11 cursor-se-resize touch-none items-end justify-end pr-2 pb-2"
              onPointerDown={onResizeDown}
              onPointerMove={onResizeMove}
              onPointerUp={onResizeUp}
              onPointerCancel={onResizeUp}
            >
              {/* Triangular dot-grid grip icon */}
              <div className="flex flex-col items-end gap-[3.5px] opacity-45">
                <div className="flex gap-[3.5px]">
                  <div className="h-[3px] w-[3px] rounded-full bg-white" />
                  <div className="h-[3px] w-[3px] rounded-full bg-white" />
                  <div className="h-[3px] w-[3px] rounded-full bg-white" />
                </div>
                <div className="flex gap-[3.5px]">
                  <div className="h-[3px] w-[3px] rounded-full bg-white" />
                  <div className="h-[3px] w-[3px] rounded-full bg-white" />
                </div>
                <div className="flex gap-[3.5px]">
                  <div className="h-[3px] w-[3px] rounded-full bg-white" />
                </div>
              </div>
            </div>
          </motion.div>
        </motion.div>

        {/* Status label below card */}
        <div className="mt-2 flex items-center justify-between px-0.5">
          <div className="flex items-center gap-1.5">
            <span className={`h-1.5 w-1.5 rounded-full ${cfg.dotClass}`} />
            <span className="font-mono text-[9px] font-semibold tracking-[0.14em] text-white/45 uppercase">
              {avatarName}
            </span>
            <span className="font-mono text-[9px] text-white/22">· {cfg.label}</span>
          </div>
          {/* Drag indicator */}
          <div className="flex items-center gap-[2.5px] opacity-20">
            {[0, 1, 2, 3, 4, 5].map((i) => (
              <div
                key={i}
                className={`rounded-full bg-white ${i % 2 === 0 ? 'h-[3px] w-[3px]' : 'h-[2px] w-[2px] opacity-50'}`}
              />
            ))}
          </div>
        </div>
      </motion.div>
    </div>
  );
}

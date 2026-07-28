'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { useRoomContext } from '@livekit/components-react';
import type { PoseLandmarker } from '@mediapipe/tasks-vision';
import { getCachedLandmarker, preloadPoseLandmarker } from '@/lib/mediapipe-preload';
import { cn } from '@/lib/utils';

const BODY_CONNECTIONS: [number, number][] = [
  [11, 12],
  [11, 13],
  [13, 15],
  [12, 14],
  [14, 16],
  [11, 23],
  [12, 24],
  [23, 24],
  [23, 25],
  [25, 27],
  [24, 26],
  [26, 28],
];

const LIVE_INTERVAL_MS = 10_000; // auto-send every 10 s in live mode

interface Landmark {
  x: number;
  y: number;
  z: number;
  visibility?: number;
}

interface PostureMetrics {
  spineScore: number;
  shoulderScore: number;
  headScore: number;
  overall: number;
  tips: string[];
}

function calcMetrics(lm: Landmark[]): PostureMetrics | null {
  if (lm.length < 29) return null;

  const nose = lm[0];
  const lSh = lm[11];
  const rSh = lm[12];
  const lHip = lm[23];
  const rHip = lm[24];
  const lAnk = lm[27];
  const rAnk = lm[28];

  const vis = [lSh, rSh, lHip, rHip].every((p) => (p.visibility ?? 1) > 0.4);
  if (!vis) return null;

  const midShX = (lSh.x + rSh.x) / 2;
  const midShY = (lSh.y + rSh.y) / 2;
  const midHipX = (lHip.x + rHip.x) / 2;
  const midAnkX = (lAnk.x + rAnk.x) / 2;

  const maxDev = Math.max(
    Math.abs(midShX - midHipX),
    Math.abs(midHipX - midAnkX),
    Math.abs(midShX - midAnkX)
  );
  const spineScore = Math.round(Math.max(0, Math.min(100, 100 - maxDev * 450)));

  const shDiff = Math.abs(lSh.y - rSh.y);
  const shoulderScore = Math.round(Math.max(0, Math.min(100, 100 - shDiff * 700)));

  const headUp = nose.y < midShY;
  const headCentered = Math.abs(nose.x - midShX) < 0.12;
  const headScore = headUp && headCentered ? 100 : headUp ? 72 : headCentered ? 60 : 35;

  const overall = Math.round(spineScore * 0.45 + shoulderScore * 0.3 + headScore * 0.25);

  const tips: string[] = [];
  if (spineScore < 70) tips.push('Straighten your spine — stand tall');
  if (shoulderScore < 70) tips.push('Level your shoulders — relax them down');
  if (!headUp) tips.push('Chin up — look straight ahead');
  else if (!headCentered) tips.push('Center your head — do not tilt');
  if (overall >= 85) tips.push('Excellent posture! Keep walking.');
  else if (overall >= 70 && tips.length === 0) tips.push('Good — keep refining');

  return { spineScore, shoulderScore, headScore, overall, tips };
}

function drawSkeleton(
  ctx: CanvasRenderingContext2D,
  lm: Landmark[],
  w: number,
  h: number,
  score: number
) {
  const color = score >= 80 ? '#22c55e' : score >= 60 ? '#eab308' : '#ef4444';
  ctx.strokeStyle = color;
  ctx.lineWidth = 2.5;
  ctx.lineCap = 'round';
  for (const [a, b] of BODY_CONNECTIONS) {
    const p1 = lm[a];
    const p2 = lm[b];
    if (!p1 || !p2) continue;
    ctx.beginPath();
    ctx.moveTo(p1.x * w, p1.y * h);
    ctx.lineTo(p2.x * w, p2.y * h);
    ctx.stroke();
  }
  for (const idx of [0, 11, 12, 23, 24, 27, 28]) {
    const p = lm[idx];
    if (!p) continue;
    ctx.beginPath();
    ctx.arc(p.x * w, p.y * h, 5, 0, Math.PI * 2);
    ctx.fillStyle = '#ffffff';
    ctx.fill();
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.stroke();
  }
}

function MetricBar({ label, value }: { label: string; value: number }) {
  const clr = value >= 80 ? '#22c55e' : value >= 60 ? '#eab308' : '#ef4444';
  return (
    <div>
      <div className="mb-1 flex justify-between">
        <span className="font-mono text-[10px] tracking-wider text-white/40 uppercase">
          {label}
        </span>
        <span className="font-mono text-[10px] text-white/60">{value}%</span>
      </div>
      <div className="h-1.5 rounded-full bg-white/10">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${value}%`, backgroundColor: clr }}
        />
      </div>
    </div>
  );
}

interface Props {
  onClose: () => void;
  onAnalysisSent?: () => void;
}

export default function PostureCamera({ onClose, onAnalysisSent }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const landmarkerRef = useRef<PoseLandmarker | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const rafRef = useRef<number>(0);
  const lastTimeRef = useRef(-1);
  const mountedRef = useRef(true);
  const speakingRef = useRef(false);

  // Keep latest metrics accessible in callbacks without stale closure
  const metricsRef = useRef<PostureMetrics | null>(null);
  // Throttle: only setState when score changes by >2 pts
  const lastSetRef = useRef<PostureMetrics | null>(null);

  const [status, setStatus] = useState<'loading' | 'ready' | 'error' | 'denied'>('loading');
  const [metrics, setMetrics] = useState<PostureMetrics | null>(null);
  const [sent, setSent] = useState(false);
  const [liveMode, setLiveMode] = useState(false);
  const [facing, setFacing] = useState<'user' | 'environment'>('user');

  const room = useRoomContext();

  // ── build descriptive summary for NOVA — specific observations, not just scores ──
  function buildSummary(m: PostureMetrics): string {
    const parts: string[] = [];

    // Spine
    if (m.spineScore >= 88)
      parts.push('Spine: perfectly straight and tall — excellent vertical alignment.');
    else if (m.spineScore >= 72)
      parts.push('Spine: slight lean or tilt off center — needs minor straightening.');
    else if (m.spineScore >= 50)
      parts.push('Spine: noticeable forward lean or side tilt — body is not stacked vertically.');
    else
      parts.push(
        'Spine: significant misalignment — body is leaning heavily, needs immediate correction.'
      );

    // Shoulders
    if (m.shoulderScore >= 88) parts.push('Shoulders: perfectly level and relaxed.');
    else if (m.shoulderScore >= 70)
      parts.push('Shoulders: slightly uneven — one shoulder is a little higher than the other.');
    else if (m.shoulderScore >= 50)
      parts.push(
        'Shoulders: clearly uneven — one shoulder is noticeably raised, creating a visible tilt.'
      );
    else
      parts.push(
        'Shoulders: heavily uneven — one shoulder is much higher than the other, very visible problem.'
      );

    // Head
    if (m.headScore === 100) parts.push('Head: chin level, eyes forward, perfectly centered.');
    else if (m.headScore === 72)
      parts.push('Head: chin is up but gaze is drifting to one side — center the head.');
    else if (m.headScore === 60)
      parts.push(
        'Head: centered but chin is dropping down — needs to come up to parallel with the floor.'
      );
    else
      parts.push(
        'Head: chin is down and tilted to the side — must lift chin and look straight ahead.'
      );

    // Overall
    const verdict =
      m.overall >= 85
        ? 'Overall strong posture — nearly ready for the runway.'
        : m.overall >= 70
          ? 'Overall decent posture — a couple of corrections will make a real difference.'
          : m.overall >= 50
            ? 'Overall several posture issues — needs focused correction before walking.'
            : 'Overall posture needs significant work — build the foundation first.';
    parts.push(verdict);

    return parts.join(' ');
  }

  // ── send to NOVA via LiveKit data channel ─────────────────────────────────
  const sendToNova = useCallback(
    async (m: PostureMetrics) => {
      if (!room || speakingRef.current) return;
      speakingRef.current = true;
      setSent(true);
      try {
        await room.localParticipant.publishData(
          new TextEncoder().encode(
            JSON.stringify({ type: 'pose_analysis', summary: buildSummary(m) })
          ),
          { reliable: true }
        );
        onAnalysisSent?.();
      } catch (e) {
        console.error('publishData failed:', e);
      } finally {
        setTimeout(() => {
          setSent(false);
          speakingRef.current = false;
        }, 3000);
      }
    },
    [room, onAnalysisSent]
  );

  const tellNova = useCallback(() => {
    const m = metricsRef.current;
    if (m) void sendToNova(m);
  }, [sendToNova]);

  // ── live mode — auto-send every LIVE_INTERVAL_MS ─────────────────────────
  useEffect(() => {
    if (!liveMode) return;
    const id = setInterval(() => {
      const m = metricsRef.current;
      if (m && !speakingRef.current) void sendToNova(m);
    }, LIVE_INTERVAL_MS);
    return () => clearInterval(id);
  }, [liveMode, sendToNova]);

  // ── camera + MediaPipe init ───────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;

    async function startCamera(facingMode: 'user' | 'environment'): Promise<MediaStream | null> {
      try {
        return await navigator.mediaDevices.getUserMedia({
          video: { facingMode, width: { ideal: 640 }, height: { ideal: 480 } },
          audio: false,
        });
      } catch {
        return null;
      }
    }

    async function init() {
      setStatus('loading');
      setMetrics(null);
      metricsRef.current = null;
      lastSetRef.current = null;
      lastTimeRef.current = -1;

      // Camera — try requested facing, fall back to any camera
      let stream = await startCamera(facing);
      if (!stream) stream = await startCamera(facing === 'user' ? 'environment' : 'user');
      if (!stream) {
        if (!cancelled) setStatus('denied');
        return;
      }
      if (cancelled) {
        stream.getTracks().forEach((t) => t.stop());
        return;
      }
      streamRef.current = stream;

      const video = videoRef.current;
      if (video) {
        video.srcObject = stream;
        await video.play().catch(() => {});
      }

      // MediaPipe — use cached instance from preload (instant), else init fresh
      try {
        let landmarker: PoseLandmarker | null = getCachedLandmarker();

        if (!landmarker) {
          // Preload wasn't done yet — do it now (with GPU→CPU fallback)
          landmarker = await preloadPoseLandmarker();
        }

        if (cancelled) return;

        if (!landmarker) {
          setStatus('error');
          return;
        }

        landmarkerRef.current = landmarker;
        setStatus('ready');

        // Detection loop
        function detect() {
          if (!mountedRef.current) return;

          const vid = videoRef.current;
          const cvs = canvasRef.current;
          const lmk = landmarkerRef.current;
          if (!vid || !cvs || !lmk || vid.paused || vid.readyState < 2) {
            rafRef.current = requestAnimationFrame(detect);
            return;
          }

          if (vid.currentTime !== lastTimeRef.current) {
            lastTimeRef.current = vid.currentTime;
            cvs.width = vid.videoWidth;
            cvs.height = vid.videoHeight;
            const ctx2d = cvs.getContext('2d');
            if (!ctx2d) {
              rafRef.current = requestAnimationFrame(detect);
              return;
            }
            ctx2d.clearRect(0, 0, cvs.width, cvs.height);

            try {
              const result = lmk.detectForVideo(vid, performance.now());
              if (result.landmarks.length > 0) {
                const lm = result.landmarks[0] as Landmark[];
                const m = calcMetrics(lm);
                if (m) {
                  drawSkeleton(ctx2d, lm, cvs.width, cvs.height, m.overall);
                  metricsRef.current = m;
                  // Throttle: only re-render if scores shifted meaningfully
                  const prev = lastSetRef.current;
                  if (
                    !prev ||
                    Math.abs(m.overall - prev.overall) > 2 ||
                    Math.abs(m.spineScore - prev.spineScore) > 2 ||
                    Math.abs(m.shoulderScore - prev.shoulderScore) > 2
                  ) {
                    lastSetRef.current = m;
                    setMetrics(m);
                  }
                } else {
                  metricsRef.current = null;
                  setMetrics(null);
                }
              } else {
                metricsRef.current = null;
                setMetrics(null);
              }
            } catch {
              // detectForVideo throws if landmarker closed mid-frame — stop cleanly
              return;
            }
          }

          rafRef.current = requestAnimationFrame(detect);
        }

        rafRef.current = requestAnimationFrame(detect);
      } catch {
        if (!cancelled) setStatus('error');
      }
    }

    cancelAnimationFrame(rafRef.current);
    streamRef.current?.getTracks().forEach((t) => t.stop());
    // Do NOT close landmarker — it is a shared cached instance from preload
    landmarkerRef.current = null;
    streamRef.current = null;

    init();

    return () => {
      cancelled = true;
      mountedRef.current = false;
      cancelAnimationFrame(rafRef.current);
      streamRef.current?.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
      // Do NOT close landmarker — shared cached instance, reused on next open
      landmarkerRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [facing]); // re-run when camera facing changes

  // Reset mountedRef if facing changes (component stays mounted)
  useEffect(() => {
    mountedRef.current = true;
  }, [facing]);

  // ── render ────────────────────────────────────────────────────────────────
  const isMirrored = facing === 'user';

  return (
    <motion.div
      initial={{ opacity: 0, y: '100%' }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: '100%' }}
      transition={{ duration: 0.35, ease: 'easeOut' }}
      className="fixed inset-0 z-[250] bg-black"
    >
      {/* Camera feed */}
      <video
        ref={videoRef}
        className="absolute inset-0 h-full w-full object-cover"
        style={{ transform: isMirrored ? 'scaleX(-1)' : 'none' }}
        muted
        playsInline
      />

      {/* Skeleton canvas — mirrors to match video */}
      <canvas
        ref={canvasRef}
        className="pointer-events-none absolute inset-0 h-full w-full object-cover"
        style={{ transform: isMirrored ? 'scaleX(-1)' : 'none' }}
      />

      {/* Loading / error overlays */}
      <AnimatePresence>
        {status === 'loading' && (
          <motion.div
            key="loading"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="absolute inset-0 flex flex-col items-center justify-center bg-black/80"
          >
            <div className="mx-auto mb-3 h-8 w-8 animate-spin rounded-full border-2 border-white/10 border-t-red-600" />
            <p className="font-mono text-xs tracking-widest text-white/40 uppercase">
              Loading AI pose detection…
            </p>
          </motion.div>
        )}

        {(status === 'error' || status === 'denied') && (
          <motion.div
            key="error"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="absolute inset-0 flex flex-col items-center justify-center bg-black/90 px-8 text-center"
          >
            <p className="mb-2 text-lg font-bold text-red-400">
              {status === 'denied' ? 'Camera access denied' : 'Failed to load AI model'}
            </p>
            <p className="mb-6 font-mono text-xs text-white/30">
              {status === 'denied'
                ? 'Allow camera permission and try again.'
                : 'Check internet connection and reload.'}
            </p>
            <button
              onClick={onClose}
              className="rounded-xl bg-white/10 px-6 py-2.5 text-sm font-semibold text-white"
            >
              Close
            </button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── Top bar ── */}
      <div
        className="absolute inset-x-0 top-0 z-10 flex items-center justify-between bg-gradient-to-b from-black/80 to-transparent px-4 pb-8"
        style={{ paddingTop: 'max(env(safe-area-inset-top, 0px), 1rem)' }}
      >
        <div className="flex items-center gap-2">
          <span className="h-2 w-2 animate-pulse rounded-full bg-red-500" />
          <span className="font-mono text-[10px] tracking-[0.22em] text-white/60 uppercase">
            {liveMode ? 'Live Mode' : 'Pose Analysis'}
          </span>
        </div>

        <div className="flex items-center gap-2">
          {/* Camera flip */}
          <button
            onClick={() => setFacing((f) => (f === 'user' ? 'environment' : 'user'))}
            title="Flip camera"
            className="flex h-8 w-8 items-center justify-center rounded-full bg-black/40 text-white/70 backdrop-blur-sm transition-colors hover:bg-black/60"
          >
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M20 7h-9" />
              <path d="M14 17H5" />
              <circle cx="17" cy="17" r="3" />
              <circle cx="7" cy="7" r="3" />
            </svg>
          </button>

          {/* Close */}
          <button
            onClick={onClose}
            className="flex h-8 w-8 items-center justify-center rounded-full bg-black/40 text-white/70 backdrop-blur-sm transition-colors hover:bg-black/60"
          >
            <svg
              width="12"
              height="12"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.5"
              strokeLinecap="round"
            >
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
      </div>

      {/* Score circle */}
      <AnimatePresence>
        {metrics && (
          <motion.div
            key="score"
            initial={{ opacity: 0, scale: 0.8 }}
            animate={{ opacity: 1, scale: 1 }}
            className="absolute top-16 right-4 flex h-16 w-16 flex-col items-center justify-center rounded-full border-2 bg-black/60 backdrop-blur-sm"
            style={{
              borderColor:
                metrics.overall >= 80 ? '#22c55e' : metrics.overall >= 60 ? '#eab308' : '#ef4444',
            }}
          >
            <span
              className="text-xl leading-none font-black"
              style={{
                color:
                  metrics.overall >= 80 ? '#22c55e' : metrics.overall >= 60 ? '#eab308' : '#ef4444',
              }}
            >
              {metrics.overall}
            </span>
            <span className="font-mono text-[8px] text-white/30 uppercase">/100</span>
          </motion.div>
        )}
      </AnimatePresence>

      {/* No pose hint */}
      {status === 'ready' && !metrics && (
        <div className="absolute inset-x-0 top-1/2 flex -translate-y-1/2 flex-col items-center gap-2">
          <svg
            width="32"
            height="32"
            viewBox="0 0 24 24"
            fill="none"
            stroke="rgba(255,255,255,0.2)"
            strokeWidth="1.5"
          >
            <circle cx="12" cy="5" r="2" />
            <path d="M12 7v6m-4 4h8M8 17l-2 4m10-4 2 4" />
          </svg>
          <p className="font-mono text-[10px] tracking-widest text-white/30 uppercase">
            Step into frame
          </p>
          <p className="font-mono text-[9px] text-white/20">
            {facing === 'environment' ? 'Prop phone up — walk in front' : 'Selfie camera active'}
          </p>
        </div>
      )}

      {/* ── Bottom HUD ── */}
      <div
        className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/95 via-black/75 to-transparent"
        style={{ paddingBottom: 'max(env(safe-area-inset-bottom, 0px), 1.25rem)' }}
      >
        <div className="px-4 pt-12">
          {/* Metric bars */}
          <AnimatePresence>
            {metrics && (
              <motion.div
                key="metrics"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                className="mb-3 space-y-2.5"
              >
                <MetricBar label="Spine" value={metrics.spineScore} />
                <MetricBar label="Shoulders" value={metrics.shoulderScore} />
                <MetricBar label="Head" value={metrics.headScore} />
              </motion.div>
            )}
          </AnimatePresence>

          {/* Tips */}
          {metrics?.tips.map((tip, i) => (
            <p key={i} className="mb-1 font-mono text-[11px] text-white/45">
              {tip}
            </p>
          ))}

          {/* Live mode toggle */}
          <button
            onClick={() => setLiveMode((v) => !v)}
            className={cn(
              'mt-3 w-full rounded-2xl border py-3 text-[12px] font-semibold tracking-wide transition-all duration-200',
              liveMode
                ? 'border-red-600/50 bg-red-600/15 text-red-300'
                : 'border-white/[0.08] bg-white/[0.04] text-white/35 hover:text-white/55'
            )}
          >
            {liveMode ? '● Live — NOVA hears every 10s' : 'Live Mode (auto-feedback every 10s)'}
          </button>

          {/* Manual send */}
          <motion.button
            onClick={tellNova}
            disabled={!metrics || sent}
            whileTap={{ scale: metrics && !sent ? 0.97 : 1 }}
            className={cn(
              'mt-2 w-full rounded-2xl py-[15px] text-[13px] font-bold tracking-wide transition-all duration-200',
              metrics && !sent
                ? 'bg-red-600 text-white shadow-lg shadow-red-600/25 hover:bg-red-500'
                : 'cursor-not-allowed bg-white/[0.05] text-white/20'
            )}
          >
            {sent ? 'Sending to NOVA…' : 'Tell NOVA my posture →'}
          </motion.button>
        </div>
      </div>
    </motion.div>
  );
}

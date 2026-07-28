'use client';

import { useRef, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { cn } from '@/lib/utils';

export const NOVA_FACE_ID =
  process.env.NEXT_PUBLIC_NOVA_FACE_ID ?? 'b9e5fba3-071a-4e35-896e-211c4d6eaa7b';
export const ARIA_FACE_ID =
  process.env.NEXT_PUBLIC_ARIA_FACE_ID ?? 'afdb6a3e-3939-40aa-92df-01604c23101c';
export const MARK_FACE_ID =
  process.env.NEXT_PUBLIC_MARK_FACE_ID ?? 'dd10cb5a-d31d-4f12-b69f-6db3383c006e';

const FREE_AVATARS = [
  {
    id: NOVA_FACE_ID,
    name: 'NOVA',
    role: 'Ramp Walk Expert',
    image: '/avatar-nova.png',
    accentHex: '#E63946',
    glowRgba: 'rgba(230,57,70,0.35)',
    badgeClass: 'text-red-400',
    slot: 'nova' as const,
  },
  {
    id: ARIA_FACE_ID,
    name: 'ARIA',
    role: 'Runway Specialist',
    image: '/avatar-aria.png',
    accentHex: '#a78bfa',
    glowRgba: 'rgba(139,92,246,0.30)',
    badgeClass: 'text-violet-400',
    slot: 'aria' as const,
  },
  {
    id: MARK_FACE_ID,
    name: 'MARK',
    role: 'Male Ramp Coach',
    image: '/avatar-mark.png',
    accentHex: '#3b82f6',
    glowRgba: 'rgba(59,130,246,0.35)',
    badgeClass: 'text-blue-400',
    slot: 'mark' as const,
  },
];

// ── Session languages — self-hosted Kokoro supported ─────────────────────────
export const LANGUAGES = [
  { code: 'en-US', label: 'English', sub: 'US Accent', flag: '🇺🇸' },
  { code: 'en-GB', label: 'English', sub: 'British Accent', flag: '🇬🇧' },
  { code: 'es', label: 'Español', sub: 'Spanish', flag: '🇪🇸' },
  { code: 'fr', label: 'Français', sub: 'French', flag: '🇫🇷' },
  { code: 'it', label: 'Italiano', sub: 'Italian', flag: '🇮🇹' },
  { code: 'pt-BR', label: 'Português', sub: 'Brazilian Portuguese', flag: '🇧🇷' },
  { code: 'zh', label: '中文', sub: 'Mandarin Chinese', flag: '🇨🇳' },
];

// Kokoro voice per (language, trainer). Voice id prefix picks the language
// pipeline on the TTS server (af_ → US English, jf_ → Japanese, ...).
const VOICE_MAP: Record<string, { nova: string; aria: string; mark: string }> = {
  'en-US': { nova: 'af_nova', aria: 'af_bella', mark: 'am_michael' },
  'en-GB': { nova: 'bf_emma', aria: 'bf_isabella', mark: 'bm_george' },
  es: { nova: 'ef_dora', aria: 'ef_dora', mark: 'em_alex' },
  fr: { nova: 'ff_siwis', aria: 'ff_siwis', mark: 'ff_siwis' },
  it: { nova: 'if_sara', aria: 'if_sara', mark: 'im_nicola' },
  'pt-BR': { nova: 'pf_dora', aria: 'pf_dora', mark: 'pm_alex' },
  zh: { nova: 'zf_xiaoxiao', aria: 'zf_xiaoni', mark: 'zm_yunxi' },
};

// ── Training modes ────────────────────────────────────────────────────────────
export const TRAINING_MODES = [
  {
    id: 'ramp',
    label: 'Ramp Walk Trainer',
    sub: 'Runway, posture, turns & stage presence',
    icon: '👠',
  },
  {
    id: 'acting',
    label: 'Acting Coach',
    sub: 'Expressions, dialogue, camera & auditions',
    icon: '🎬',
  },
];

const PREMIUM_TRAINERS = [
  {
    name: 'ZARA',
    role: 'Editorial Coach',
    price: '₹1,000',
    gradientFrom: '#1a0533',
    gradientTo: '#0d0118',
    accent: '#c084fc',
    glow: 'rgba(192,132,252,0.18)',
  },
  {
    name: 'MIYA',
    role: 'Bollywood Trainer',
    price: '₹1,300',
    gradientFrom: '#1a1000',
    gradientTo: '#0d0800',
    accent: '#fbbf24',
    glow: 'rgba(251,191,36,0.18)',
  },
  {
    name: 'ELLE',
    role: 'International Pro',
    price: '₹1,500',
    gradientFrom: '#001a1a',
    gradientTo: '#000d0d',
    accent: '#34d399',
    glow: 'rgba(52,211,153,0.18)',
  },
];

const GENZCINE_PLANS = [
  { name: 'Starter', price: '₹999', period: '/mo', faces: '1 custom face', minutes: '1,000 min' },
  {
    name: 'Pro',
    price: '₹3,999',
    period: '/mo',
    faces: '5 custom faces',
    minutes: '5,500 min',
    highlight: true,
  },
  {
    name: 'Studio',
    price: '₹19,999',
    period: '/mo',
    faces: '30 custom faces',
    minutes: '27,500 min',
  },
];

type UploadState = 'idle' | 'loading' | 'success' | 'error';

// ── Selection check badge (same as avatar cards) ─────────────────────────────
function CheckBadge() {
  return (
    <motion.div
      initial={{ scale: 0, opacity: 0 }}
      animate={{ scale: 1, opacity: 1 }}
      exit={{ scale: 0, opacity: 0 }}
      transition={{ type: 'spring', stiffness: 500, damping: 24 }}
      className="absolute top-2 right-2 flex h-6 w-6 items-center justify-center rounded-full bg-red-600 shadow-lg shadow-red-600/50"
    >
      <svg
        width="10"
        height="10"
        viewBox="0 0 24 24"
        fill="none"
        stroke="white"
        strokeWidth="3.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <polyline points="20 6 9 17 4 12" />
      </svg>
    </motion.div>
  );
}

interface AvatarSelectViewProps {
  onSelect: (faceId: string, voice: string, language: string, trainingMode: string) => void;
}

export function AvatarSelectView({ onSelect }: AvatarSelectViewProps) {
  const [phase, setPhase] = useState<'trainer' | 'setup'>('trainer');
  const [selected, setSelected] = useState(NOVA_FACE_ID);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selectedPlan, setSelectedPlan] = useState<string | null>(null);
  const [language, setLanguage] = useState('en-US');
  const [trainingMode, setTrainingMode] = useState('ramp');

  // Upload state (lives inside drawer)
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploadPreview, setUploadPreview] = useState<string | null>(null);
  const [uploadState, setUploadState] = useState<UploadState>('idle');
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [customFaceId, setCustomFaceId] = useState<string | null>(null);
  const [uploadFile, setUploadFile] = useState<File | null>(null);

  const CUSTOM_ID = '__custom__';
  const isCustom = selected === CUSTOM_ID || (customFaceId !== null && selected === customFaceId);
  const freeAvatar = FREE_AVATARS.find((a) => a.id === selected);

  const effectiveFaceId = customFaceId ?? (selected !== CUSTOM_ID ? selected : NOVA_FACE_ID);
  const voiceSlot = isCustom ? 'nova' : (freeAvatar?.slot ?? 'nova');
  const effectiveVoice = (VOICE_MAP[language] ?? VOICE_MAP['en-US'])[voiceSlot];
  const ctaLabel = isCustom
    ? 'Train with My Avatar'
    : freeAvatar
      ? `Train with ${freeAvatar.name}`
      : 'Continue';

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (uploadPreview) URL.revokeObjectURL(uploadPreview);
    setUploadFile(file);
    setUploadPreview(URL.createObjectURL(file));
    setUploadState('idle');
    setUploadError(null);
    setCustomFaceId(null);
    setSelected(CUSTOM_ID);
  };

  const handleCreateFace = async () => {
    if (!uploadFile) return;
    setUploadState('loading');
    setUploadError(null);
    try {
      const formData = new FormData();
      formData.append('file', uploadFile);
      formData.append('name', 'My Custom Avatar');
      const apiBase = process.env.NEXT_PUBLIC_API_URL ?? '';
      const res = await fetch(`${apiBase}/api/avatar/create-face`, {
        method: 'POST',
        body: formData,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => null);
        throw new Error(err?.detail ?? `Failed (${res.status})`);
      }
      const data = (await res.json()) as { face_id: string };
      setCustomFaceId(data.face_id);
      setSelected(data.face_id);
      setUploadState('success');
    } catch (e) {
      setUploadError(e instanceof Error ? e.message : 'Upload failed');
      setUploadState('error');
    }
  };

  const clearUpload = () => {
    if (uploadPreview) URL.revokeObjectURL(uploadPreview);
    setUploadPreview(null);
    setUploadFile(null);
    setUploadState('idle');
    setUploadError(null);
    setCustomFaceId(null);
    if (isCustom) setSelected(NOVA_FACE_ID);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const trainerName = isCustom ? 'My Avatar' : (freeAvatar?.name ?? 'NOVA');

  return (
    <>
      <AnimatePresence mode="wait" initial={false}>
        {phase === 'trainer' ? (
          <motion.div
            key="phase-trainer"
            initial={{ opacity: 0, x: -40 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -40 }}
            transition={{ duration: 0.3, ease: 'easeOut' }}
            className="h-full"
          >
            <div className="flex h-full flex-col overflow-y-auto bg-[#080808]">
              {/* Ambient glow */}
              <div className="pointer-events-none fixed inset-x-0 top-0 h-60 bg-[radial-gradient(ellipse_80%_60%_at_50%_0%,rgba(230,57,70,0.08),transparent_70%)]" />

              {/* ── Header ── */}
              <div
                className="relative mx-auto flex w-full max-w-xl items-center justify-between px-5 md:max-w-2xl"
                style={{ paddingTop: 'max(env(safe-area-inset-top, 0px), 2.5rem)' }}
              >
                <div className="flex items-center gap-2">
                  <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-red-600">
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="white">
                      <polygon points="5 3 19 12 5 21 5 3" />
                    </svg>
                  </div>
                  <span className="text-[11px] font-bold tracking-[0.18em] text-white uppercase">
                    GenzCine
                  </span>
                </div>
                <span className="rounded-full border border-white/[0.08] px-2.5 py-0.5 font-mono text-[10px] tracking-widest text-white/20 uppercase">
                  1 / 2
                </span>
              </div>

              {/* ── Title ── */}
              <div className="mx-auto w-full max-w-xl px-5 pt-4 md:max-w-2xl">
                <p className="mb-1 font-mono text-[9px] tracking-[0.38em] text-white/20 uppercase">
                  Choose Your Trainer
                </p>
                <h1 className="text-[28px] leading-[1.0] font-black tracking-tight text-white md:text-4xl">
                  WHO <span className="text-red-500">TRAINS YOU?</span>
                </h1>
              </div>

              {/* ── FREE AVATARS ── */}
              <div className="mx-auto mt-5 w-full max-w-xl px-4 md:max-w-2xl">
                <p className="mb-3 font-mono text-[9px] tracking-[0.28em] text-white/20 uppercase">
                  Included Free
                </p>
                <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
                  {FREE_AVATARS.map((av) => {
                    const isSel = selected === av.id;
                    return (
                      <motion.button
                        key={av.id}
                        onClick={() => setSelected(av.id)}
                        whileTap={{ scale: 0.97 }}
                        className={cn(
                          'relative flex flex-col overflow-hidden rounded-2xl border transition-all duration-300',
                          isSel
                            ? av.accentHex === '#E63946'
                              ? 'border-red-500/70'
                              : 'border-violet-400/70'
                            : 'border-white/[0.07]'
                        )}
                        style={{ boxShadow: isSel ? `0 0 32px 4px ${av.glowRgba}` : 'none' }}
                      >
                        <div
                          className="relative w-full overflow-hidden"
                          style={{ paddingTop: '115%' }}
                        >
                          {/* eslint-disable-next-line @next/next/no-img-element */}
                          <img
                            src={av.image}
                            alt={av.name}
                            className="absolute inset-0 h-full w-full object-cover object-top"
                            draggable={false}
                          />
                          <div className="absolute inset-x-0 bottom-0 h-16 bg-gradient-to-t from-black/70 to-transparent" />
                          <div className="absolute bottom-2 left-2 rounded-full bg-black/60 px-2 py-0.5 font-mono text-[7px] tracking-widest text-white/50 uppercase backdrop-blur-md">
                            GenzCine
                          </div>
                          <AnimatePresence>
                            {isSel && (
                              <motion.div
                                initial={{ scale: 0, opacity: 0 }}
                                animate={{ scale: 1, opacity: 1 }}
                                exit={{ scale: 0, opacity: 0 }}
                                transition={{ type: 'spring', stiffness: 500, damping: 24 }}
                                className="absolute top-2 right-2 flex h-6 w-6 items-center justify-center rounded-full bg-red-600 shadow-lg shadow-red-600/50"
                              >
                                <svg
                                  width="10"
                                  height="10"
                                  viewBox="0 0 24 24"
                                  fill="none"
                                  stroke="white"
                                  strokeWidth="3.5"
                                  strokeLinecap="round"
                                  strokeLinejoin="round"
                                >
                                  <polyline points="20 6 9 17 4 12" />
                                </svg>
                              </motion.div>
                            )}
                          </AnimatePresence>
                        </div>
                        <div className="bg-[#0f0f0f] px-3 py-2.5">
                          <p className="font-mono text-[12px] font-bold tracking-[0.1em] text-white">
                            {av.name}
                          </p>
                          <p className="text-[10px] text-white/35">{av.role}</p>
                          <p
                            className={cn(
                              'mt-1 font-mono text-[8px] font-semibold uppercase',
                              av.badgeClass
                            )}
                          >
                            ● Free
                          </p>
                        </div>
                      </motion.button>
                    );
                  })}
                </div>
              </div>

              {/* ── PREMIUM TRAINERS ── */}
              <div className="mx-auto mt-5 w-full max-w-xl px-4 md:max-w-2xl">
                <div className="mb-3 flex items-center justify-between">
                  <p className="font-mono text-[9px] tracking-[0.28em] text-white/20 uppercase">
                    Premium Trainers
                  </p>
                  <span className="rounded-full bg-white/[0.04] px-2.5 py-0.5 font-mono text-[8px] text-white/20">
                    Coming Soon
                  </span>
                </div>
                <div className="grid grid-cols-3 gap-2.5">
                  {PREMIUM_TRAINERS.map((av) => (
                    <div
                      key={av.name}
                      className="flex flex-col overflow-hidden rounded-2xl"
                      style={{
                        background: `linear-gradient(180deg, ${av.gradientFrom} 0%, ${av.gradientTo} 100%)`,
                        boxShadow: `0 0 0 1px ${av.accent}18, inset 0 1px 0 ${av.accent}12`,
                      }}
                    >
                      {/* Portrait */}
                      <div className="relative overflow-hidden" style={{ paddingTop: '130%' }}>
                        {/* Deep glow from bottom */}
                        <div
                          className="absolute inset-0"
                          style={{
                            background: `radial-gradient(ellipse 90% 55% at 50% 105%, ${av.accent}28, transparent 65%)`,
                          }}
                        />

                        {/* Richer silhouette */}
                        <svg
                          viewBox="0 0 100 140"
                          className="absolute inset-x-0 bottom-0 w-full"
                          preserveAspectRatio="xMidYMax meet"
                        >
                          {/* Body glow */}
                          <ellipse
                            cx="50"
                            cy="120"
                            rx="42"
                            ry="30"
                            fill={av.accent}
                            fillOpacity="0.08"
                          />
                          {/* Shoulders */}
                          <path
                            d="M8,140 C8,108 22,96 50,91 C78,96 92,108 92,140 Z"
                            fill={av.accent}
                            fillOpacity="0.18"
                          />
                          {/* Neck */}
                          <rect
                            x="44"
                            y="62"
                            width="12"
                            height="16"
                            rx="4"
                            fill={av.accent}
                            fillOpacity="0.20"
                          />
                          {/* Head */}
                          <ellipse
                            cx="50"
                            cy="46"
                            rx="20"
                            ry="24"
                            fill={av.accent}
                            fillOpacity="0.22"
                          />
                          {/* Hair top */}
                          <ellipse
                            cx="50"
                            cy="26"
                            rx="22"
                            ry="10"
                            fill={av.accent}
                            fillOpacity="0.14"
                          />
                        </svg>

                        {/* Blur + dark overlay */}
                        <div
                          className="absolute inset-0"
                          style={{ background: 'rgba(0,0,0,0.38)', backdropFilter: 'blur(1.5px)' }}
                        />

                        {/* Top-right LOCK badge */}
                        <div
                          className="absolute top-2 right-2 flex h-6 w-6 items-center justify-center rounded-full"
                          style={{
                            background: `${av.accent}20`,
                            border: `1px solid ${av.accent}35`,
                          }}
                        >
                          <svg
                            width="10"
                            height="10"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke={av.accent}
                            strokeWidth="2"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            opacity="0.9"
                          >
                            <rect x="3" y="11" width="18" height="11" rx="2" />
                            <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                          </svg>
                        </div>

                        {/* Center label */}
                        <div className="absolute inset-x-0 bottom-3 flex justify-center">
                          <span
                            className="rounded-full px-2 py-0.5 font-mono text-[6.5px] font-bold tracking-[0.2em] uppercase"
                            style={{
                              background: `${av.accent}18`,
                              color: av.accent,
                              border: `1px solid ${av.accent}25`,
                            }}
                          >
                            Coming Soon
                          </span>
                        </div>
                      </div>

                      {/* Info */}
                      <div className="px-2.5 py-2.5" style={{ background: 'rgba(0,0,0,0.35)' }}>
                        <p
                          className="font-mono text-[10px] font-black tracking-[0.1em]"
                          style={{ color: av.accent, opacity: 0.8 }}
                        >
                          {av.name}
                        </p>
                        <p className="mt-0.5 text-[8.5px] text-white/30">{av.role}</p>
                        <p className="mt-1.5 font-mono text-[9px] font-bold text-white/20">
                          {av.price}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* ── UPLOAD YOUR PHOTO — PAYWALL ── */}
              <div className="mx-auto mt-4 w-full max-w-xl px-4 md:max-w-2xl">
                <div
                  className="overflow-hidden rounded-2xl"
                  style={{
                    border: '1px solid rgba(251,191,36,0.15)',
                    background: 'linear-gradient(135deg, #130e00, #0a0700)',
                  }}
                >
                  {/* Top row */}
                  <div className="flex items-center gap-3.5 p-4">
                    {/* Icon / preview */}
                    <div
                      className="relative h-14 w-14 shrink-0 overflow-hidden rounded-xl"
                      style={{
                        border: '1px solid rgba(251,191,36,0.18)',
                        background: 'rgba(251,191,36,0.05)',
                      }}
                    >
                      {uploadPreview && uploadState === 'success' ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          src={uploadPreview}
                          alt="preview"
                          className="h-full w-full object-cover object-top"
                        />
                      ) : (
                        <>
                          {uploadPreview && (
                            // eslint-disable-next-line @next/next/no-img-element
                            <img
                              src={uploadPreview}
                              alt="preview"
                              className="h-full w-full object-cover object-top opacity-30 blur-sm"
                            />
                          )}
                          <div className="absolute inset-0 flex items-center justify-center">
                            <svg
                              width="20"
                              height="20"
                              viewBox="0 0 24 24"
                              fill="none"
                              stroke="#fbbf24"
                              strokeWidth="1.4"
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              opacity="0.4"
                            >
                              <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z" />
                              <circle cx="12" cy="13" r="4" />
                            </svg>
                          </div>
                        </>
                      )}
                      {/* Lock overlay if not yet purchased */}
                      {uploadState !== 'success' && (
                        <div className="absolute inset-0 flex items-end justify-end p-1">
                          <div className="flex h-5 w-5 items-center justify-center rounded-full bg-black/70">
                            <svg
                              width="8"
                              height="8"
                              viewBox="0 0 24 24"
                              fill="none"
                              stroke="#fbbf24"
                              strokeWidth="2.2"
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              opacity="0.8"
                            >
                              <rect x="3" y="11" width="18" height="11" rx="2" />
                              <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                            </svg>
                          </div>
                        </div>
                      )}
                    </div>

                    <div className="flex-1">
                      <div className="flex items-center gap-1.5">
                        <p className="text-[13px] font-bold text-white/80">Upload Your Photo</p>
                        <span className="rounded-full bg-amber-500/15 px-1.5 py-0.5 font-mono text-[6.5px] font-bold tracking-widest text-amber-400/70 uppercase">
                          Premium
                        </span>
                      </div>
                      <p className="mt-0.5 text-[10.5px] text-white/28">
                        {uploadState === 'success'
                          ? 'Custom avatar active · Tap to change'
                          : 'Train with your own GenzCine AI face'}
                      </p>
                    </div>
                  </div>

                  {/* Divider */}
                  <div className="mx-4 h-px bg-amber-500/[0.08]" />

                  {/* Paywall strip */}
                  <div className="flex items-center gap-3 px-4 py-3">
                    <svg
                      width="13"
                      height="13"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="#fbbf24"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      opacity="0.5"
                      className="shrink-0"
                    >
                      <rect x="3" y="11" width="18" height="11" rx="2" />
                      <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                    </svg>
                    <p className="flex-1 text-[10px] text-white/25">
                      GenzCine custom face · contact support to unlock
                    </p>
                    <motion.button
                      onClick={() => setDrawerOpen(true)}
                      whileTap={{ scale: 0.96 }}
                      className="shrink-0 rounded-xl px-3.5 py-2 text-[11px] font-bold text-black transition-opacity hover:opacity-90"
                      style={{ background: 'linear-gradient(135deg, #fbbf24, #f59e0b)' }}
                    >
                      {uploadState === 'success' ? 'Change' : 'Buy Plan →'}
                    </motion.button>
                  </div>
                </div>
              </div>

              {/* CTA */}
              <div
                className="sticky bottom-0 mt-auto bg-gradient-to-t from-[#080808] via-[#080808]/90 to-transparent px-4 pt-4"
                style={{ paddingBottom: 'max(env(safe-area-inset-bottom, 0px), 1.25rem)' }}
              >
                <motion.button
                  onClick={() => setPhase('setup')}
                  whileTap={{ scale: 0.97 }}
                  className="mx-auto block w-full max-w-xl rounded-2xl bg-red-600 py-[15px] text-[13px] font-bold tracking-wide text-white shadow-lg shadow-red-600/25 transition-colors hover:bg-red-500 md:max-w-2xl"
                >
                  {ctaLabel} →
                </motion.button>
              </div>
            </div>
          </motion.div>
        ) : (
          <motion.div
            key="phase-setup"
            initial={{ opacity: 0, x: 40 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 40 }}
            transition={{ duration: 0.3, ease: 'easeOut' }}
            className="h-full"
          >
            <div className="flex h-full flex-col overflow-y-auto bg-[#080808]">
              {/* Ambient glow */}
              <div className="pointer-events-none fixed inset-x-0 top-0 h-60 bg-[radial-gradient(ellipse_80%_60%_at_50%_0%,rgba(230,57,70,0.08),transparent_70%)]" />

              {/* ── Header ── */}
              <div
                className="relative mx-auto flex w-full max-w-xl items-center justify-between px-5 md:max-w-2xl"
                style={{ paddingTop: 'max(env(safe-area-inset-top, 0px), 2.5rem)' }}
              >
                <div className="flex items-center gap-2">
                  <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-red-600">
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="white">
                      <polygon points="5 3 19 12 5 21 5 3" />
                    </svg>
                  </div>
                  <span className="text-[11px] font-bold tracking-[0.18em] text-white uppercase">
                    GenzCine
                  </span>
                </div>
                <button
                  onClick={() => setPhase('trainer')}
                  className="flex items-center gap-1.5 rounded-full border border-white/[0.07] px-3 py-1 font-mono text-[10px] text-white/30 transition-colors hover:text-white/60"
                >
                  ← Trainer
                </button>
              </div>

              {/* ── Title ── */}
              <div className="mx-auto w-full max-w-xl px-5 pt-4 md:max-w-2xl">
                <p className="mb-1 font-mono text-[9px] tracking-[0.38em] text-white/20 uppercase">
                  Set Up Your Session
                </p>
                <h1 className="text-[28px] leading-[1.0] font-black tracking-tight text-white md:text-4xl">
                  TRAIN <span className="text-red-500">YOUR WAY</span>
                </h1>
              </div>

              {/* ── TRAINING MODE ── */}
              <div className="mx-auto mt-5 w-full max-w-xl px-4 md:max-w-2xl">
                <p className="mb-3 font-mono text-[9px] tracking-[0.28em] text-white/20 uppercase">
                  Training Mode
                </p>
                <div className="grid grid-cols-2 gap-3">
                  {TRAINING_MODES.map((m) => {
                    const isSel = trainingMode === m.id;
                    return (
                      <motion.button
                        key={m.id}
                        onClick={() => setTrainingMode(m.id)}
                        whileTap={{ scale: 0.97 }}
                        className={cn(
                          'relative flex flex-col overflow-hidden rounded-2xl border p-4 text-left transition-all duration-300',
                          isSel
                            ? 'border-red-500/70 bg-red-600/[0.06]'
                            : 'border-white/[0.07] bg-[#0f0f0f]'
                        )}
                        style={{
                          boxShadow: isSel ? '0 0 32px 4px rgba(230,57,70,0.25)' : 'none',
                        }}
                      >
                        <span className="text-[30px] leading-none">{m.icon}</span>
                        <p className="mt-3 font-mono text-[12px] font-bold tracking-[0.06em] text-white">
                          {m.label}
                        </p>
                        <p className="mt-1 text-[10px] leading-snug text-white/35">{m.sub}</p>
                        <AnimatePresence>{isSel && <CheckBadge />}</AnimatePresence>
                      </motion.button>
                    );
                  })}
                </div>
              </div>

              {/* ── LANGUAGE ── */}
              <div className="mx-auto mt-6 w-full max-w-xl px-4 md:max-w-2xl">
                <p className="mb-3 font-mono text-[9px] tracking-[0.28em] text-white/20 uppercase">
                  Language
                </p>
                <div className="grid grid-cols-2 gap-2.5 md:grid-cols-3">
                  {LANGUAGES.map((l) => {
                    const isSel = language === l.code;
                    return (
                      <motion.button
                        key={l.code}
                        onClick={() => setLanguage(l.code)}
                        whileTap={{ scale: 0.97 }}
                        className={cn(
                          'relative flex items-center gap-3 overflow-hidden rounded-2xl border px-3.5 py-3 text-left transition-all duration-300',
                          isSel
                            ? 'border-red-500/70 bg-red-600/[0.06]'
                            : 'border-white/[0.07] bg-[#0f0f0f]'
                        )}
                        style={{
                          boxShadow: isSel ? '0 0 24px 2px rgba(230,57,70,0.20)' : 'none',
                        }}
                      >
                        <span className="text-[22px] leading-none">{l.flag}</span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[13px] font-bold text-white">
                            {l.label}
                          </span>
                          <span className="block truncate text-[9.5px] text-white/30">{l.sub}</span>
                        </span>
                        <AnimatePresence>{isSel && <CheckBadge />}</AnimatePresence>
                      </motion.button>
                    );
                  })}
                </div>
              </div>

              {/* CTA */}
              <div
                className="sticky bottom-0 mt-auto bg-gradient-to-t from-[#080808] via-[#080808]/90 to-transparent px-4 pt-6"
                style={{ paddingBottom: 'max(env(safe-area-inset-bottom, 0px), 1.25rem)' }}
              >
                <motion.button
                  onClick={() => {
                    onSelect(effectiveFaceId, effectiveVoice, language, trainingMode);
                  }}
                  whileTap={{ scale: 0.97 }}
                  className="mx-auto block w-full max-w-xl rounded-2xl bg-red-600 py-[15px] text-[13px] font-bold tracking-wide text-white shadow-lg shadow-red-600/25 transition-colors hover:bg-red-500 md:max-w-2xl"
                >
                  Start with {trainerName} →
                </motion.button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ══════════════════════════════════════════
          BOTTOM DRAWER — Upload Your Face
      ══════════════════════════════════════════ */}
      <AnimatePresence>
        {drawerOpen && (
          <>
            {/* Backdrop */}
            <motion.div
              key="backdrop"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.25 }}
              className="fixed inset-0 z-40 bg-black/70 backdrop-blur-sm"
              onClick={() => setDrawerOpen(false)}
            />

            {/* Drawer panel */}
            <motion.div
              key="drawer"
              initial={{ y: '100%' }}
              animate={{ y: 0 }}
              exit={{ y: '100%' }}
              transition={{ type: 'spring', stiffness: 340, damping: 38 }}
              className="fixed inset-x-0 bottom-0 z-50 mx-auto w-full max-w-xl overflow-hidden rounded-t-3xl bg-[#111111] shadow-2xl md:max-w-2xl"
              style={{ paddingBottom: 'max(env(safe-area-inset-bottom, 0px), 1.5rem)' }}
            >
              {/* Drag handle */}
              <div className="flex justify-center pt-3 pb-1">
                <div className="h-1 w-10 rounded-full bg-white/20" />
              </div>

              {/* Header */}
              <div className="flex items-center justify-between px-5 pt-2 pb-4">
                <div>
                  <div className="flex items-center gap-2">
                    <p className="text-[17px] font-bold text-white">Upload Your Face</p>
                    <span className="rounded-full bg-amber-500/15 px-2 py-0.5 font-mono text-[8px] tracking-wider text-amber-400/80 uppercase">
                      Premium
                    </span>
                  </div>
                  <p className="mt-0.5 text-[12px] text-white/35">
                    Create a personalized AI avatar with GenzCine
                  </p>
                </div>
                <button
                  onClick={() => setDrawerOpen(false)}
                  className="flex h-8 w-8 items-center justify-center rounded-full bg-white/[0.07] text-white/50 transition-colors hover:bg-white/10"
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

              {/* ── GenzCine Plans ── */}
              <div className="px-5 pb-4">
                <p className="mb-2.5 font-mono text-[9px] tracking-[0.28em] text-white/25 uppercase">
                  GenzCine Plan Required
                </p>
                <div className="grid grid-cols-3 gap-2">
                  {GENZCINE_PLANS.map((plan) => {
                    const isSel = selectedPlan === plan.name;
                    // Show highlight only when nothing is selected yet
                    const showDefaultHighlight = plan.highlight && selectedPlan === null;
                    return (
                      <motion.button
                        key={plan.name}
                        onClick={() => setSelectedPlan(plan.name)}
                        whileTap={{ scale: 0.96 }}
                        className={cn(
                          'flex flex-col rounded-xl border p-2.5 text-left transition-all duration-200',
                          isSel
                            ? 'border-amber-400/70 bg-amber-500/[0.13] shadow-[0_0_16px_2px_rgba(251,191,36,0.12)]'
                            : showDefaultHighlight
                              ? 'border-amber-500/40 bg-amber-500/[0.07]'
                              : 'border-white/[0.06] bg-white/[0.02]'
                        )}
                      >
                        {isSel && (
                          <span className="mb-1 self-start rounded-full bg-amber-400/25 px-1.5 py-0.5 font-mono text-[7px] tracking-wider text-amber-300 uppercase">
                            Selected
                          </span>
                        )}
                        {!isSel && showDefaultHighlight && (
                          <span className="mb-1 self-start rounded-full bg-amber-500/20 px-1.5 py-0.5 font-mono text-[7px] tracking-wider text-amber-400 uppercase">
                            Popular
                          </span>
                        )}
                        <p
                          className={cn(
                            'font-mono text-[11px] font-bold',
                            isSel
                              ? 'text-amber-300'
                              : showDefaultHighlight
                                ? 'text-amber-400'
                                : 'text-white/60'
                          )}
                        >
                          {plan.name}
                        </p>
                        <p
                          className={cn(
                            'mt-0.5 text-[15px] font-black',
                            isSel
                              ? 'text-amber-300'
                              : showDefaultHighlight
                                ? 'text-amber-400'
                                : 'text-white/70'
                          )}
                        >
                          {plan.price}
                          <span className="text-[9px] font-normal opacity-60">{plan.period}</span>
                        </p>
                        <p className="mt-1 text-[9px] text-white/30">{plan.faces}</p>
                        <p className="text-[9px] text-white/20">{plan.minutes}</p>
                      </motion.button>
                    );
                  })}
                </div>
                <p className="mt-2.5 font-mono text-[10px] text-white/20">
                  Contact GenzCine support to unlock custom face plans.
                </p>
              </div>

              <div className="mx-5 h-px bg-white/[0.06]" />

              {/* ── Upload locked ── */}
              <div className="px-5 pt-4 pb-1">
                <div className="relative overflow-hidden rounded-2xl border border-dashed border-white/[0.07]">
                  {/* Ghost UI behind */}
                  <div className="pointer-events-none flex flex-col items-center justify-center gap-3 py-9 opacity-[0.12] select-none">
                    <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-amber-500/30 bg-amber-500/10">
                      <svg
                        width="20"
                        height="20"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="#fbbf24"
                        strokeWidth="1.5"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      >
                        <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z" />
                        <circle cx="12" cy="13" r="4" />
                      </svg>
                    </div>
                    <p className="text-[13px] font-semibold text-white">Tap to choose photo</p>
                    <p className="text-[11px] text-white/60">JPG, PNG, WEBP, HEIC · Max 10 MB</p>
                  </div>
                  {/* Lock overlay */}
                  <div
                    className="absolute inset-0 flex flex-col items-center justify-center gap-3"
                    style={{ background: 'rgba(8,8,8,0.78)', backdropFilter: 'blur(3px)' }}
                  >
                    <div className="flex h-12 w-12 items-center justify-center rounded-full border border-white/[0.08] bg-white/[0.04]">
                      <svg
                        width="20"
                        height="20"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="white"
                        strokeWidth="1.5"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        opacity="0.35"
                      >
                        <rect x="3" y="11" width="18" height="11" rx="2" />
                        <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                      </svg>
                    </div>
                    <div className="px-6 text-center">
                      <p className="text-[13px] font-semibold text-white/50">Upload locked</p>
                      <p className="mt-1.5 text-[11px] leading-relaxed text-white/25">
                        Subscribe to a GenzCine plan above to unlock this feature. Payment
                        integration coming soon.
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </>
  );
}

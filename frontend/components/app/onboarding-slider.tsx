'use client';

import { useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { cn } from '@/lib/utils';

interface OnboardingSliderProps {
  onComplete: () => void;
}

const SLIDES = [
  {
    icon: (
      <div className="flex h-20 w-20 items-center justify-center rounded-3xl bg-red-600 shadow-xl shadow-red-600/30">
        <svg width="30" height="30" viewBox="0 0 24 24" fill="white">
          <polygon points="5 3 19 12 5 21 5 3" />
        </svg>
      </div>
    ),
    badge: 'WELCOME',
    titleLine1: 'MEET',
    titleLine2: 'NOVA.',
    description:
      "NOVA is GenzCine's AI-powered ramp walk trainer. Get personalized coaching on posture, stride, turns, and runway confidence — anytime, anywhere.",
  },
  {
    icon: (
      <div className="flex h-20 w-20 items-center justify-center rounded-3xl border border-white/10 bg-white/[0.06]">
        <svg
          width="34"
          height="34"
          viewBox="0 0 24 24"
          fill="none"
          stroke="white"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
          <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
          <line x1="12" y1="19" x2="12" y2="23" />
          <line x1="8" y1="23" x2="16" y2="23" />
        </svg>
      </div>
    ),
    badge: 'HOW IT WORKS',
    titleLine1: 'SPEAK.',
    titleLine2: 'LEARN.',
    description:
      'Click Start Training, allow microphone access, then talk to NOVA naturally. She will coach you step by step with real-time verbal guidance.',
  },
  {
    icon: (
      <div className="flex h-20 w-20 items-center justify-center rounded-3xl border border-white/10 bg-white/[0.06]">
        <svg
          width="34"
          height="34"
          viewBox="0 0 24 24"
          fill="none"
          stroke="white"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
          <circle cx="9" cy="7" r="4" />
          <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
          <path d="M16 3.13a4 4 0 0 1 0 7.75" />
        </svg>
      </div>
    ),
    badge: 'GROUP SESSIONS',
    titleLine1: 'TRAIN',
    titleLine2: 'TOGETHER.',
    description:
      'Switch to Group mode and create a session. Share the room code with friends — NOVA will coach everyone together in real time.',
  },
  {
    icon: (
      <div className="flex h-20 w-20 items-center justify-center rounded-3xl border border-amber-500/20 bg-amber-500/[0.08]">
        <svg width="36" height="36" viewBox="0 0 24 24" fill="none">
          <path d="M2 17L4.5 7L9 13L12 5L15 13L19.5 7L22 17H2Z" fill="url(#ob_crown)" />
          <defs>
            <linearGradient
              id="ob_crown"
              x1="2"
              y1="5"
              x2="22"
              y2="17"
              gradientUnits="userSpaceOnUse"
            >
              <stop stopColor="#f59e0b" />
              <stop offset="1" stopColor="#ef4444" />
            </linearGradient>
          </defs>
        </svg>
      </div>
    ),
    badge: 'FREE TRIAL',
    titleLine1: '5 MINUTES',
    titleLine2: 'FREE.',
    description:
      'Your first session is on us — 5 minutes of live ramp walk coaching with NOVA. After the trial, upgrade to GenzCine Premium for unlimited training and exclusive audition access.',
  },
  {
    icon: (
      <div className="flex h-20 w-20 items-center justify-center rounded-3xl bg-red-600 shadow-xl shadow-red-600/30">
        <svg
          width="34"
          height="34"
          viewBox="0 0 24 24"
          fill="none"
          stroke="white"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <polyline points="20 6 9 17 4 12" />
        </svg>
      </div>
    ),
    badge: "YOU'RE READY",
    titleLine1: "LET'S",
    titleLine2: 'START.',
    description:
      'Your AI runway journey begins now. Choose Individual or Group mode, enter your name, and start training with NOVA.',
  },
];

const variants = {
  enter: (dir: number) => ({ x: dir > 0 ? '100%' : '-100%', opacity: 0 }),
  center: { x: 0, opacity: 1 },
  exit: (dir: number) => ({ x: dir > 0 ? '-100%' : '100%', opacity: 0 }),
};

export function OnboardingSlider({ onComplete }: OnboardingSliderProps) {
  const [[current, direction], setSlide] = useState([0, 1]);

  const goTo = (index: number) => {
    setSlide([index, index > current ? 1 : -1]);
  };

  const handleNext = () => {
    if (current < SLIDES.length - 1) {
      goTo(current + 1);
    } else {
      onComplete();
    }
  };

  const slide = SLIDES[current];
  const isLast = current === SLIDES.length - 1;

  return (
    <div className="relative flex h-full w-full flex-col overflow-hidden bg-[#080808]">
      {/* Ambient glow */}
      <div className="pointer-events-none absolute -top-20 -right-20 h-[380px] w-[380px] rounded-full bg-red-600/10 blur-[100px]" />
      <div className="pointer-events-none absolute -bottom-20 -left-20 h-[260px] w-[260px] rounded-full bg-red-900/[0.06] blur-[80px]" />

      {/* Header — below status bar */}
      <div
        className="mx-auto flex w-full max-w-xl items-center justify-between px-6 md:max-w-2xl"
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
          onClick={onComplete}
          className="text-[12px] text-white/30 transition-colors hover:text-white/60"
        >
          Skip
        </button>
      </div>

      {/* Slide area */}
      <div className="relative flex-1 overflow-hidden">
        <AnimatePresence initial={false} custom={direction} mode="popLayout">
          <motion.div
            key={current}
            custom={direction}
            variants={variants}
            initial="enter"
            animate="center"
            exit="exit"
            transition={{ duration: 0.35, ease: [0.32, 0, 0.67, 0] }}
            className="absolute inset-0 flex flex-col items-center justify-center px-8 text-center"
          >
            {/* Icon */}
            <motion.div
              initial={{ scale: 0.75, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              transition={{ delay: 0.1, duration: 0.4, ease: 'easeOut' }}
            >
              {slide.icon}
            </motion.div>

            {/* Badge */}
            <motion.p
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.18, duration: 0.38 }}
              className="mt-8 font-mono text-[10px] tracking-[0.38em] text-white/25 uppercase"
            >
              {slide.badge}
            </motion.p>

            {/* Title */}
            <motion.h2
              initial={{ opacity: 0, y: 14 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.22, duration: 0.38 }}
              className="mt-2 text-[52px] leading-[0.88] font-black tracking-tighter text-white"
            >
              {slide.titleLine1}
              <br />
              <span className="text-red-500">{slide.titleLine2}</span>
            </motion.h2>

            {/* Description */}
            <motion.p
              initial={{ opacity: 0, y: 14 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.28, duration: 0.38 }}
              className="mt-5 max-w-[300px] text-[13px] leading-relaxed text-white/35"
            >
              {slide.description}
            </motion.p>
          </motion.div>
        </AnimatePresence>
      </div>

      {/* Bottom controls — above home indicator */}
      <div
        className="mx-auto w-full max-w-xl px-6 md:max-w-2xl"
        style={{ paddingBottom: 'max(env(safe-area-inset-bottom, 0px), 2.5rem)' }}
      >
        {/* Progress dots — centered */}
        <div className="mb-6 flex items-center justify-center gap-2">
          {SLIDES.map((_, i) => (
            <button
              key={i}
              onClick={() => goTo(i)}
              className={cn(
                'rounded-full transition-all duration-300',
                i === current ? 'h-2 w-6 bg-red-600' : 'h-2 w-2 bg-white/20 hover:bg-white/40'
              )}
            />
          ))}
        </div>

        {/* CTA */}
        <motion.button
          onClick={handleNext}
          whileTap={{ scale: 0.97 }}
          className="w-full rounded-2xl bg-red-600 py-[15px] text-[13px] font-bold tracking-wide text-white shadow-lg shadow-red-600/25 transition-all duration-200 hover:bg-red-500"
        >
          {isLast ? "Let's Start →" : 'Next →'}
        </motion.button>
      </div>
    </div>
  );
}

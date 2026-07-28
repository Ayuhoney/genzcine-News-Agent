'use client';

import { motion } from 'motion/react';

interface PremiumViewProps {
  trainedSeconds?: number;
  onRetry?: () => void;
}

function fmt(secs: number) {
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

export function PremiumView({ trainedSeconds = 0, onRetry }: PremiumViewProps) {
  return (
    <div className="relative flex h-svh w-full flex-col items-center justify-center overflow-hidden bg-[#080808] px-6">
      {/* Ambient glows */}
      <div className="pointer-events-none absolute -top-32 left-1/2 h-[500px] w-[500px] -translate-x-1/2 rounded-full bg-red-600/10 blur-[120px]" />
      <div className="pointer-events-none absolute bottom-0 left-1/2 h-[300px] w-[300px] -translate-x-1/2 rounded-full bg-red-900/[0.07] blur-[100px]" />

      <motion.div
        initial={{ opacity: 0, y: 24 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: 'easeOut' }}
        className="relative z-10 flex w-full max-w-sm flex-col items-center text-center"
      >
        {/* Crown icon */}
        <div className="mb-6 flex h-20 w-20 items-center justify-center rounded-3xl border border-red-500/20 bg-gradient-to-br from-red-600/30 to-red-900/20 shadow-2xl shadow-red-600/20">
          <svg width="36" height="36" viewBox="0 0 24 24" fill="none">
            <path
              d="M2 17L4.5 7L9 13L12 5L15 13L19.5 7L22 17H2Z"
              fill="url(#crownGrad)"
              stroke="none"
            />
            <defs>
              <linearGradient
                id="crownGrad"
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

        {/* Badge */}
        <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-amber-500/20 bg-amber-500/[0.08] px-4 py-1">
          <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
          <span className="font-mono text-[10px] tracking-[0.25em] text-amber-400/80 uppercase">
            Free Trial Complete
          </span>
        </div>

        {/* Title */}
        <h1 className="mb-2 text-4xl font-black tracking-tight text-white">
          UPGRADE TO
          <br />
          <span className="bg-gradient-to-r from-red-400 to-amber-400 bg-clip-text text-transparent">
            PREMIUM.
          </span>
        </h1>

        <p className="mb-2 text-[14px] leading-relaxed text-white/40">
          Your 5-minute free trial has ended.
          <br />
          Unlock unlimited training with NOVA.
        </p>

        {/* Session stat */}
        {trainedSeconds > 0 && (
          <div className="mt-4 mb-6 rounded-2xl border border-white/[0.06] bg-white/[0.03] px-6 py-3">
            <p className="font-mono text-[10px] tracking-[0.2em] text-white/25 uppercase">
              Session trained
            </p>
            <p className="mt-0.5 text-xl font-bold text-white/70">{fmt(trainedSeconds)}</p>
          </div>
        )}

        {/* Premium features */}
        <div className="mt-2 mb-8 w-full space-y-2.5 text-left">
          {[
            'Unlimited daily training sessions',
            'All 10 ramp walk lessons unlocked',
            'Group sessions — train with friends',
            'Posture AI analysis every session',
            'Priority access to GenzCine auditions',
          ].map((feat) => (
            <div key={feat} className="flex items-center gap-3">
              <div className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-red-600/20">
                <svg
                  width="10"
                  height="10"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="#ef4444"
                  strokeWidth="3"
                  strokeLinecap="round"
                >
                  <polyline points="20 6 9 17 4 12" />
                </svg>
              </div>
              <span className="text-[13px] text-white/50">{feat}</span>
            </div>
          ))}
        </div>

        {/* CTA */}
        <a
          href="https://genzcine.com"
          target="_blank"
          rel="noopener noreferrer"
          className="w-full rounded-2xl bg-gradient-to-r from-red-600 to-red-500 py-4 text-center text-[15px] font-bold tracking-wide text-white shadow-xl shadow-red-600/25 transition-transform active:scale-[0.98]"
        >
          Unlock Premium — genzcine.com
        </a>

        {/* Secondary */}
        {onRetry && (
          <button
            onClick={onRetry}
            className="mt-4 text-[13px] text-white/25 underline-offset-2 transition-colors hover:text-white/40"
          >
            Back to home
          </button>
        )}
      </motion.div>
    </div>
  );
}

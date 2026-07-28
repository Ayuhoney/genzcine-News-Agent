'use client';

import { useEffect, useState } from 'react';
import { motion } from 'motion/react';
import { isAndroidOrIOS } from '@/lib/mobile';

interface MobileOnlyGateProps {
  children: React.ReactNode;
}

/**
 * Blocks desktop / non-mobile browsers. App is Android + iOS only.
 * Dev override: add ?desktop=1 once (stored in sessionStorage).
 */
export function MobileOnlyGate({ children }: MobileOnlyGateProps) {
  const [allowed, setAllowed] = useState<boolean | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get('desktop') === '1') {
      sessionStorage.setItem('gc_allow_desktop', '1');
    }
    const bypass = sessionStorage.getItem('gc_allow_desktop') === '1';
    setAllowed(bypass || isAndroidOrIOS());
  }, []);

  if (allowed === null) {
    return <div className="h-dvh w-full bg-transparent" />;
  }

  if (allowed) return <>{children}</>;

  return (
    <div className="relative flex h-dvh w-full flex-col items-center justify-center overflow-hidden bg-[#080808] px-6">
      <div className="pointer-events-none absolute -top-24 left-1/2 h-[420px] w-[420px] -translate-x-1/2 rounded-full bg-red-600/10 blur-[110px]" />

      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35 }}
        className="relative z-10 flex w-full max-w-sm flex-col items-center text-center"
      >
        <div className="mb-6 flex h-16 w-16 items-center justify-center rounded-2xl bg-[#FF1F2D]">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="white">
            <polygon points="5 3 19 12 5 21 5 3" />
          </svg>
        </div>

        <p className="font-mono text-[10px] tracking-[0.28em] text-white/30 uppercase">GenzCine</p>
        <h1 className="mt-3 text-[28px] leading-tight font-black tracking-tight text-white">
          Mobile only
        </h1>
        <p className="mt-3 text-[14px] leading-relaxed text-white/45">
          This experience is built for Android and iOS. Open this link on your phone to go live with
          your AI news anchor.
        </p>

        <div className="mt-8 flex w-full gap-3">
          <div className="flex flex-1 flex-col items-center gap-2 rounded-2xl border border-white/[0.08] bg-white/[0.03] px-3 py-4">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" className="text-white/70">
              <rect
                x="7"
                y="2"
                width="10"
                height="20"
                rx="2"
                stroke="currentColor"
                strokeWidth="1.6"
              />
              <circle cx="12" cy="18" r="1" fill="currentColor" />
            </svg>
            <span className="text-[12px] font-semibold text-white/70">Android</span>
          </div>
          <div className="flex flex-1 flex-col items-center gap-2 rounded-2xl border border-white/[0.08] bg-white/[0.03] px-3 py-4">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor" className="text-white/70">
              <path d="M18.71 19.5c-.83 1.24-1.71 2.45-3.05 2.47-1.34.03-1.77-.79-3.29-.79-1.53 0-2 .77-3.27.82-1.31.05-2.3-1.32-3.14-2.53C4.25 17 2.94 12.45 4.7 9.39c.87-1.52 2.43-2.48 4.12-2.51 1.28-.02 2.5.87 3.29.87.78 0 2.26-1.07 3.81-.91.65.03 2.47.26 3.64 1.98-.09.06-2.17 1.28-2.15 3.81.03 3.02 2.65 4.03 2.68 4.04-.03.07-.42 1.44-1.38 2.83M13 3.5c.73-.83 1.22-1.98 1.08-3.13-1.05.04-2.31.7-3.06 1.58-.67.79-1.26 2.06-1.1 3.27 1.16.09 2.35-.59 3.08-1.72" />
            </svg>
            <span className="text-[12px] font-semibold text-white/70">iOS</span>
          </div>
        </div>
      </motion.div>
    </div>
  );
}

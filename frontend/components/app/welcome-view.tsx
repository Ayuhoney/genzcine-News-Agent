'use client';

import { useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { AssistantPopover } from '@/components/app/assistant-popover';
import { NOVA_FACE_ID } from '@/lib/anchors';
import { getDeviceId } from '@/lib/device';
import { cn } from '@/lib/utils';

export interface StartCallParams {
  participantName: string;
  faceId?: string;
  voice?: string;
  language?: string;
  anchorName?: string;
}

interface WelcomeViewProps {
  startButtonText: string;
  onStartCall: (params: StartCallParams) => void | Promise<void>;
  isStarting?: boolean;
  trialRemainingSeconds?: number;
  onTrialExpired?: () => void;
}

const apiBase = () => process.env.NEXT_PUBLIC_API_URL ?? '';

async function sleep(ms: number) {
  await new Promise((r) => setTimeout(r, ms));
}

/** True if the request was aborted (Strict Mode remount, timeout, unmount). */
function isAbortError(e: unknown): boolean {
  return (
    (e instanceof DOMException && e.name === 'AbortError') ||
    (typeof e === 'object' &&
      e !== null &&
      'name' in e &&
      (e as { name: string }).name === 'AbortError')
  );
}

/**
 * Reachability probe with retries. Uses /api/device because it is always
 * proxied in dev and available in production API. Any HTTP response (incl. 4xx)
 * means the backend process is up.
 */
async function isBackendReachable(opts?: {
  retries?: number;
  timeoutMs?: number;
  signal?: AbortSignal;
}): Promise<boolean> {
  const retries = opts?.retries ?? 3;
  const timeoutMs = opts?.timeoutMs ?? 5000;
  const deviceId = getDeviceId() || '00000000-0000-4000-8000-000000000000';

  for (let attempt = 0; attempt < retries; attempt++) {
    if (opts?.signal?.aborted) return false;

    const controller = new AbortController();
    const onOuterAbort = () => controller.abort();
    opts?.signal?.addEventListener('abort', onOuterAbort, { once: true });
    const timer = setTimeout(() => controller.abort(), timeoutMs);

    try {
      const res = await fetch(`${apiBase()}/api/device?id=${deviceId}`, {
        cache: 'no-store',
        signal: controller.signal,
      });
      // Got an HTTP answer → API is alive (4xx is still "online").
      if (res.status > 0) return true;
    } catch (e) {
      if (isAbortError(e) && opts?.signal?.aborted) return false;
      // retry on network / timeout
    } finally {
      clearTimeout(timer);
      opts?.signal?.removeEventListener('abort', onOuterAbort);
    }

    if (attempt < retries - 1) await sleep(350 * (attempt + 1));
  }
  return false;
}

export const WelcomeView = ({
  startButtonText,
  onStartCall,
  isStarting = false,
  trialRemainingSeconds,
  onTrialExpired,
  className,
  ref,
  ...rest
}: React.ComponentProps<'div'> & WelcomeViewProps) => {
  const [name, setName] = useState('');
  const [selectedFaceId, setSelectedFaceId] = useState(NOVA_FACE_ID);
  const [selectedVoice, setSelectedVoice] = useState('af_nova');
  const [selectedLanguage, setSelectedLanguage] = useState('en-US');
  const [selectedAnchorName, setSelectedAnchorName] = useState('NOVA');
  const [snackbar, setSnackbar] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const snackbarTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const startingLock = useRef(false);

  const showSnackbar = (msg: string, durationMs = 4500) => {
    if (snackbarTimer.current) clearTimeout(snackbarTimer.current);
    setSnackbar(msg);
    snackbarTimer.current = setTimeout(() => setSnackbar(null), durationMs);
  };

  // Best-effort profile hydrate only — NEVER gates Go Live.
  useEffect(() => {
    const controller = new AbortController();
    const deviceId = getDeviceId();
    if (!deviceId) return;

    const timeout = setTimeout(() => controller.abort(), 8000);
    fetch(`${apiBase()}/api/device?id=${deviceId}`, {
      cache: 'no-store',
      signal: controller.signal,
    })
      .then(async (r) => {
        if (!r.ok) return;
        const data = (await r.json()) as {
          avatar_face_id?: string;
          participant_name?: string;
        };
        if (controller.signal.aborted) return;
        if (data.avatar_face_id) setSelectedFaceId(data.avatar_face_id);
        if (data.participant_name) setName(data.participant_name);
      })
      .catch(() => {
        // Ignore — hydrate is optional; Go Live has its own live check.
      })
      .finally(() => clearTimeout(timeout));

    return () => {
      clearTimeout(timeout);
      controller.abort();
    };
  }, []);

  // Soft background re-probe after tab focus / network recovery (no UI lock).
  useEffect(() => {
    const warm = () => {
      void isBackendReachable({ retries: 1, timeoutMs: 3000 });
    };
    const onVisible = () => {
      if (document.visibilityState === 'visible') warm();
    };
    window.addEventListener('online', warm);
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      window.removeEventListener('online', warm);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, []);

  const handleAnchorChange = (
    faceId: string,
    voice: string,
    language: string,
    anchorName: string
  ) => {
    setSelectedFaceId(faceId);
    setSelectedVoice(voice);
    setSelectedLanguage(language);
    setSelectedAnchorName(anchorName);
    const deviceId = getDeviceId();
    if (!deviceId) return;
    fetch(`${apiBase()}/api/device/avatar`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ device_id: deviceId, face_id: faceId }),
    }).catch(() => {});
  };

  const SAFE_NAME_RE = /[^\p{L}\p{N}\s\-\.]/gu;
  const sanitisedName = name.replace(SAFE_NAME_RE, '').slice(0, 60);

  const handleStart = async () => {
    if (isStarting || checking || startingLock.current) return;
    startingLock.current = true;
    setChecking(true);
    try {
      // Live check with retries — never trust a stale flag from page load.
      const online = await isBackendReachable({ retries: 3, timeoutMs: 5000 });
      if (!online) {
        showSnackbar(
          `${selectedAnchorName} is offline. Please retry after some time.`
        );
        return;
      }
      await onStartCall({
        participantName: sanitisedName.trim() || 'model',
        faceId: selectedFaceId,
        voice: selectedVoice,
        language: selectedLanguage,
        anchorName: selectedAnchorName,
      });
    } finally {
      setChecking(false);
      startingLock.current = false;
    }
  };

  const busy = isStarting || checking;

  return (
    <div
      ref={ref}
      className={cn('pointer-events-none relative h-full w-full bg-transparent', className)}
      {...rest}
    >
      <div className="pointer-events-auto">
        <AssistantPopover
          faceId={selectedFaceId}
          language={selectedLanguage}
          name={name}
          canStart={!busy}
          isStarting={busy}
          startLabel={startButtonText}
          trialRemainingSeconds={trialRemainingSeconds}
          onTrialExpired={onTrialExpired}
          onNameChange={setName}
          onAnchorChange={handleAnchorChange}
          onStart={handleStart}
        />
      </div>

      <AnimatePresence>
        {snackbar && (
          <motion.div
            key="snackbar"
            initial={{ opacity: 0, y: -16 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -12 }}
            transition={{ duration: 0.22 }}
            className="pointer-events-auto absolute inset-x-4 top-14 z-[500] flex items-start gap-3 rounded-2xl border border-red-500/20 bg-[#1a0a0a]/95 px-4 py-3.5 shadow-2xl backdrop-blur-xl"
            style={{ top: 'max(env(safe-area-inset-top, 0px), 3.5rem)' }}
          >
            <div className="mt-0.5 h-2 w-2 shrink-0 rounded-full bg-red-500" />
            <p className="text-[13px] leading-snug text-red-200/90">{snackbar}</p>
            <button
              onClick={() => setSnackbar(null)}
              className="ml-auto shrink-0 text-red-400/60 transition-colors hover:text-red-300"
            >
              <svg
                width="14"
                height="14"
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
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

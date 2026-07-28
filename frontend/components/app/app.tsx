'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { TokenSource } from 'livekit-client';
import {
  RoomAudioRenderer,
  SessionProvider,
  StartAudio,
  useSession,
} from '@livekit/components-react';
import type { AppConfig } from '@/app-config';
import { ErrorBoundary } from '@/components/app/error-boundary';
import { MobileOnlyGate } from '@/components/app/mobile-only-gate';
import { OverlayPreviewBackdrop } from '@/components/app/overlay-preview-backdrop';
import { PremiumView } from '@/components/app/premium-view';
import type { StartCallParams } from '@/components/app/welcome-view';
import { WelcomeView } from '@/components/app/welcome-view';
import { Toaster } from '@/components/livekit/toaster';
import { useAgentErrors } from '@/hooks/useAgentErrors';
import { useDebugMode } from '@/hooks/useDebug';
import { getDeviceId, initDeviceId } from '@/lib/device';
import { installGlobalErrorHandlers } from '@/lib/logger';
import { getSandboxTokenSource } from '@/lib/utils';

const IN_DEVELOPMENT = process.env.NODE_ENV !== 'production';

function AppSetup() {
  useDebugMode({ enabled: IN_DEVELOPMENT });
  useAgentErrors();
  useEffect(() => {
    installGlobalErrorHandlers();
    void initDeviceId(); // sync all 3 stores on startup
  }, []);
  return null;
}

interface ConnectionDetails {
  serverUrl: string;
  participantToken: string;
  roomName: string;
  sessionType: string;
  participantName: string;
  trialRemainingSeconds?: number;
}

interface AppProps {
  appConfig: AppConfig;
}

export function App({ appConfig }: AppProps) {
  const pendingRef = useRef<ConnectionDetails | null>(null);
  const [isStarting, setIsStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const [trialExpired, setTrialExpired] = useState(false);
  const [trialRemainingSeconds, setTrialRemainingSeconds] = useState<number | undefined>(undefined);
  const trainedSecondsRef = useRef(0);

  const tokenSource = useMemo(() => {
    if (typeof process.env.NEXT_PUBLIC_CONN_DETAILS_ENDPOINT === 'string') {
      return getSandboxTokenSource(appConfig);
    }
    return TokenSource.custom(async () => {
      const data = pendingRef.current;
      if (!data) throw new Error('No connection details available');
      return data;
    });
  }, [appConfig]);

  const session = useSession(
    tokenSource,
    appConfig.agentName ? { agentName: appConfig.agentName } : undefined
  );

  const handleTrialExpired = () => {
    setTrialExpired(true);
  };

  const handleStartCall = async (params: StartCallParams) => {
    if (isStarting) return;
    setIsStarting(true);
    setStartError(null);
    try {
      const body: Record<string, string> = {
        session_type: 'individual',
        participant_name: params.participantName,
        device_id: getDeviceId(),
      };
      if (params.faceId) body.face_id = params.faceId;
      if (params.voice) body.voice = params.voice;
      if (params.language) body.language = params.language;
      if (params.anchorName) body.anchor_name = params.anchorName;

      // AbortSignal.timeout() not available on iOS 15 — use AbortController fallback
      const abort = new AbortController();
      const abortTimer = setTimeout(() => abort.abort(), 10_000);

      const apiBase = process.env.NEXT_PUBLIC_API_URL ?? '';
      const res = await fetch(`${apiBase}/api/connection-details`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: abort.signal,
      }).finally(() => clearTimeout(abortTimer));

      if (res.status === 429) {
        setStartError('Too many attempts. Please retry after some time.');
        return;
      }
      if (res.status === 402) {
        // Trial exhausted — show premium paywall immediately
        setTrialExpired(true);
        return;
      }
      if (res.status === 400) {
        // Server sends a human-readable detail — show it directly
        const errBody = await res.json().catch(() => null);
        const msg = errBody?.detail ?? 'Invalid request. Please try again.';
        setStartError(msg);
        return;
      }
      if (!res.ok) {
        setStartError(
          `${params.anchorName ?? 'Anchor'} is offline. Please retry after some time.`
        );
        return;
      }

      const data = (await res.json()) as ConnectionDetails;
      pendingRef.current = data;
      setTrialRemainingSeconds(data.trialRemainingSeconds);
      await session.start();
    } catch (e) {
      if (e instanceof Error && (e.name === 'TimeoutError' || e.name === 'AbortError')) {
        setStartError('Request timed out. Please retry after some time.');
      } else {
        setStartError(
          `${params.anchorName ?? 'Anchor'} is offline. Please retry after some time.`
        );
      }
      console.error('Failed to start session:', e);
    } finally {
      setIsStarting(false);
    }
  };

  if (trialExpired) {
    return (
      <ErrorBoundary>
        <MobileOnlyGate>
          <PremiumView
            trainedSeconds={trainedSecondsRef.current}
            onRetry={() => setTrialExpired(false)}
          />
        </MobileOnlyGate>
      </ErrorBoundary>
    );
  }

  return (
    <ErrorBoundary>
      <MobileOnlyGate>
        <OverlayPreviewBackdrop />
        <SessionProvider session={session}>
          <AppSetup />
          <main
            className="h-dvh max-h-dvh w-full overflow-hidden bg-transparent"
            style={{ background: 'transparent' }}
          >
            <WelcomeView
              startButtonText={appConfig.startButtonText}
              onStartCall={handleStartCall}
              isStarting={isStarting}
              trialRemainingSeconds={trialRemainingSeconds}
              onTrialExpired={handleTrialExpired}
              className="h-full"
            />
          </main>
          <StartAudio label="Start Audio" />
          <RoomAudioRenderer />
          <Toaster />
        </SessionProvider>

        {/* Error toast — pinned to the top so it never overlaps the bottom-right
            avatar/popover (which is the only way to retry). */}
        {startError && (
          <div
            className="fixed inset-x-4 z-[400] flex items-start gap-3 rounded-2xl border border-red-500/20 bg-[#1a0a0a]/95 px-4 py-3.5 shadow-2xl backdrop-blur-xl"
            style={{ top: 'max(env(safe-area-inset-top, 0px), 1.25rem)' }}
          >
            <div className="mt-0.5 h-2 w-2 shrink-0 rounded-full bg-red-500" />
            <p className="text-[13px] leading-snug text-red-200/90">{startError}</p>
            <button
              onClick={() => setStartError(null)}
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
          </div>
        )}
      </MobileOnlyGate>
    </ErrorBoundary>
  );
}

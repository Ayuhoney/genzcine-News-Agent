'use client';

import { useEffect, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { AvatarSelectView, NOVA_FACE_ID } from '@/components/app/avatar-select-view';
import { OnboardingSlider } from '@/components/app/onboarding-slider';
import { getDeviceId } from '@/lib/device';
import { cn } from '@/lib/utils';

export interface StartCallParams {
  sessionType: 'individual' | 'group';
  participantName: string;
  roomName?: string;
  faceId?: string;
  voice?: string;
  language?: string;
  trainingMode?: string;
}

interface WelcomeViewProps {
  startButtonText: string;
  onStartCall: (params: StartCallParams) => void | Promise<void>;
}

type Step = 'loading' | 'onboarding' | 'avatar' | 'form';

const apiBase = () => process.env.NEXT_PUBLIC_API_URL ?? '';

export const WelcomeView = ({
  startButtonText,
  onStartCall,
  className,
  ref,
  ...rest
}: React.ComponentProps<'div'> & WelcomeViewProps) => {
  const [step, setStep] = useState<Step>('loading');
  const [mode, setMode] = useState<'individual' | 'group'>('individual');
  const [groupAction, setGroupAction] = useState<'create' | 'join'>('create');
  const [name, setName] = useState('');
  const [roomCode, setRoomCode] = useState('');
  const [selectedFaceId, setSelectedFaceId] = useState(NOVA_FACE_ID);
  const [selectedVoice, setSelectedVoice] = useState('af_nova');
  const [selectedLanguage, setSelectedLanguage] = useState('en-US');
  const [selectedTrainingMode, setSelectedTrainingMode] = useState('ramp');
  const [backendOnline, setBackendOnline] = useState(true);
  const [snackbar, setSnackbar] = useState<string | null>(null);

  const showSnackbar = (msg: string, durationMs = 4000) => {
    setSnackbar(msg);
    setTimeout(() => setSnackbar(null), durationMs);
  };

  // Load device state from MongoDB — no localStorage for user data.
  // Falls back gracefully if backend is offline (shows onboarding).
  useEffect(() => {
    const deviceId = getDeviceId();
    if (!deviceId) {
      setStep('onboarding');
      return;
    }
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 4000); // 4 s timeout
    fetch(`${apiBase()}/api/device?id=${deviceId}`, {
      cache: 'no-store',
      signal: controller.signal,
    })
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((data: { onboarded?: boolean; avatar_face_id?: string; participant_name?: string }) => {
        if (data.avatar_face_id) setSelectedFaceId(data.avatar_face_id);
        if (data.participant_name) setName(data.participant_name);
        setStep(data.onboarded ? 'avatar' : 'onboarding');
      })
      .catch(() => {
        setBackendOnline(false);
        setStep('onboarding');
      })
      .finally(() => clearTimeout(timeout));
  }, []);

  const handleOnboardingComplete = () => {
    setStep('avatar');
    // Fire-and-forget — UI does not wait for this
    const deviceId = getDeviceId();
    fetch(`${apiBase()}/api/device/onboard`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ device_id: deviceId }),
    }).catch(() => {});
  };

  const handleAvatarSelect = (
    faceId: string,
    voice: string,
    language: string,
    trainingMode: string
  ) => {
    setSelectedFaceId(faceId);
    setSelectedVoice(voice);
    setSelectedLanguage(language);
    setSelectedTrainingMode(trainingMode);
    setStep('form');
    // Fire-and-forget
    const deviceId = getDeviceId();
    fetch(`${apiBase()}/api/device/avatar`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ device_id: deviceId, face_id: faceId }),
    }).catch(() => {});
  };

  // ── Input validation ──
  const SAFE_NAME_RE = /[^\p{L}\p{N}\s\-\.]/gu;
  const GROUP_ROOM_RE = /^group_room_\d{4}$/;
  const sanitisedName = name.replace(SAFE_NAME_RE, '').slice(0, 60);

  const roomCodeError =
    mode === 'group' && groupAction === 'join' && roomCode.trim().length > 0
      ? !GROUP_ROOM_RE.test(roomCode.trim())
        ? 'Format: group_room_XXXX'
        : null
      : null;

  const canStart =
    mode === 'individual' ||
    groupAction === 'create' ||
    (groupAction === 'join' && GROUP_ROOM_RE.test(roomCode.trim()));

  const handleStart = () => {
    if (!canStart) return;
    if (!backendOnline) {
      showSnackbar('NOVA is offline. Please retry after some time.');
      return;
    }
    const participantName = sanitisedName.trim() || 'model';
    const base = {
      participantName,
      faceId: selectedFaceId,
      voice: selectedVoice,
      language: selectedLanguage,
      trainingMode: selectedTrainingMode,
    };
    if (mode === 'individual') {
      onStartCall({ ...base, sessionType: 'individual' });
    } else if (groupAction === 'create') {
      onStartCall({ ...base, sessionType: 'group' });
    } else {
      onStartCall({ ...base, sessionType: 'group', roomName: roomCode.trim() });
    }
  };

  const buttonLabel =
    mode === 'individual'
      ? startButtonText
      : groupAction === 'create'
        ? 'Create Group Session'
        : 'Join Group Session';

  return (
    <div
      ref={ref}
      className={cn('relative flex h-full w-full flex-col overflow-hidden bg-[#080808]', className)}
      {...rest}
    >
      <AnimatePresence mode="wait">
        {step === 'loading' && (
          <motion.div
            key="loading"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="flex h-full items-center justify-center"
          >
            <div className="h-5 w-5 animate-spin rounded-full border-2 border-white/10 border-t-red-600" />
          </motion.div>
        )}

        {step === 'onboarding' && (
          <motion.div
            key="onboarding"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.3 }}
            className="absolute inset-0"
          >
            <OnboardingSlider onComplete={handleOnboardingComplete} />
          </motion.div>
        )}

        {step === 'avatar' && (
          <motion.div
            key="avatar"
            initial={{ opacity: 0, x: 40 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -40 }}
            transition={{ duration: 0.35, ease: 'easeOut' }}
            className="absolute inset-0"
          >
            <AvatarSelectView onSelect={handleAvatarSelect} />
          </motion.div>
        )}

        {step === 'form' && (
          <motion.div
            key="welcome-form"
            initial={{ opacity: 0, x: 40 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -40 }}
            transition={{ duration: 0.35, ease: 'easeOut' }}
            className="flex h-full flex-col"
          >
            {/* Ambient glows */}
            <div className="pointer-events-none absolute -top-24 -right-24 h-[420px] w-[420px] rounded-full bg-red-600/10 blur-[110px]" />
            <div className="pointer-events-none absolute -bottom-24 -left-24 h-[280px] w-[280px] rounded-full bg-red-900/[0.06] blur-[90px]" />

            {/* Header */}
            <div
              className="mx-auto flex w-full max-w-xl items-center justify-between px-6 md:max-w-2xl"
              style={{ paddingTop: 'max(env(safe-area-inset-top, 0px), 2.5rem)' }}
            >
              <div className="flex items-center gap-2.5">
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-red-600">
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="white">
                    <polygon points="5 3 19 12 5 21 5 3" />
                  </svg>
                </div>
                <span className="text-[11px] font-bold tracking-[0.18em] text-white uppercase">
                  GenzCine
                </span>
              </div>
              <button
                onClick={() => setStep('avatar')}
                className="flex items-center gap-1.5 rounded-full border border-white/[0.07] px-3 py-1 font-mono text-[10px] text-white/30 transition-colors hover:text-white/60"
              >
                ← Trainer
              </button>
            </div>

            {/* Hero */}
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, ease: 'easeOut' }}
              className="mx-auto w-full max-w-xl px-6 pt-10 md:max-w-2xl md:pt-14"
            >
              <p className="mb-3 font-mono text-[10px] tracking-[0.42em] text-white/20 uppercase">
                Ramp Walk Training
              </p>
              <h1 className="text-[62px] leading-[0.88] font-black tracking-tighter text-white md:text-[76px]">
                MEET
                <br />
                <span className="text-red-500">NOVA.</span>
              </h1>
              <p className="mt-5 max-w-[255px] text-[13px] leading-relaxed text-white/35 md:max-w-sm">
                Your AI-powered runway trainer. Master posture, stride, turns, and stage confidence.
              </p>
            </motion.div>

            {/* Session card */}
            <motion.div
              initial={{ opacity: 0, y: 28 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.12, duration: 0.5, ease: 'easeOut' }}
              className="mx-4 mt-auto rounded-3xl border border-white/[0.07] bg-white/[0.04] p-5 backdrop-blur-2xl sm:mx-auto sm:w-full sm:max-w-xl md:max-w-2xl"
            >
              {/* Mode tabs */}
              <div className="mb-4 flex gap-1 rounded-2xl bg-white/[0.05] p-1">
                {(['individual', 'group'] as const).map((m) => (
                  <button
                    key={m}
                    onClick={() => setMode(m)}
                    className={cn(
                      'flex-1 rounded-xl py-2.5 text-[13px] font-semibold capitalize transition-all duration-200',
                      mode === m
                        ? 'bg-red-600 text-white shadow-lg shadow-red-600/20'
                        : 'text-white/30 hover:text-white/55'
                    )}
                  >
                    {m}
                  </button>
                ))}
              </div>

              {/* Name input */}
              <input
                type="text"
                placeholder="Your name"
                value={name}
                maxLength={60}
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && canStart && handleStart()}
                className="w-full rounded-2xl border border-white/[0.08] bg-white/[0.05] px-4 py-3.5 text-[13px] text-white outline-none placeholder:text-white/25 focus:border-red-600/40"
              />

              {/* Group controls */}
              <AnimatePresence>
                {mode === 'group' && (
                  <motion.div
                    key="group-controls"
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: 'auto' }}
                    exit={{ opacity: 0, height: 0 }}
                    transition={{ duration: 0.22 }}
                    className="mt-3 overflow-hidden"
                  >
                    <div className="flex gap-1 rounded-2xl bg-white/[0.04] p-1">
                      {(['create', 'join'] as const).map((action) => (
                        <button
                          key={action}
                          onClick={() => setGroupAction(action)}
                          className={cn(
                            'flex-1 rounded-xl py-2 text-[12px] font-semibold transition-all duration-150',
                            groupAction === action ? 'bg-white/10 text-white' : 'text-white/25'
                          )}
                        >
                          {action === 'create' ? 'Create Session' : 'Join Session'}
                        </button>
                      ))}
                    </div>

                    <AnimatePresence mode="wait">
                      {groupAction === 'join' ? (
                        <motion.div
                          key="room-input"
                          initial={{ opacity: 0, y: -6 }}
                          animate={{ opacity: 1, y: 0 }}
                          exit={{ opacity: 0, y: -6 }}
                          transition={{ duration: 0.18 }}
                        >
                          <input
                            type="text"
                            placeholder="group_room_1234"
                            value={roomCode}
                            maxLength={20}
                            onChange={(e) => setRoomCode(e.target.value.toLowerCase().trim())}
                            onKeyDown={(e) => e.key === 'Enter' && canStart && handleStart()}
                            className={cn(
                              'mt-3 w-full rounded-2xl border bg-white/[0.05] px-4 py-3.5 text-[13px] text-white outline-none placeholder:text-white/25',
                              roomCodeError
                                ? 'border-red-500/50 focus:border-red-500/70'
                                : 'border-white/[0.08] focus:border-red-600/40'
                            )}
                          />
                          {roomCodeError && (
                            <p className="mt-1 px-1 font-mono text-[10px] text-red-400/70">
                              {roomCodeError}
                            </p>
                          )}
                        </motion.div>
                      ) : (
                        <motion.p
                          key="create-hint"
                          initial={{ opacity: 0 }}
                          animate={{ opacity: 1 }}
                          exit={{ opacity: 0 }}
                          transition={{ duration: 0.18 }}
                          className="mt-2 px-1 text-[11px] text-white/20"
                        >
                          A room code will appear once connected — share it with others.
                        </motion.p>
                      )}
                    </AnimatePresence>
                  </motion.div>
                )}
              </AnimatePresence>

              {/* CTA */}
              <motion.button
                onClick={handleStart}
                disabled={!canStart}
                whileTap={{ scale: canStart ? 0.97 : 1 }}
                className={cn(
                  'mt-4 w-full rounded-2xl py-[15px] text-[13px] font-bold tracking-wide transition-all duration-200',
                  canStart
                    ? 'bg-red-600 text-white shadow-lg shadow-red-600/25 hover:bg-red-500'
                    : 'cursor-not-allowed bg-white/[0.05] text-white/20'
                )}
              >
                {buttonLabel} →
              </motion.button>
            </motion.div>

            {/* Footer */}
            <p
              className="text-center font-mono text-[9px] tracking-[0.35em] text-white/10 uppercase"
              style={{
                padding: '1.25rem 0',
                paddingBottom: 'max(env(safe-area-inset-bottom, 0px), 1.25rem)',
              }}
            >
              Powered by GenzCine
            </p>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Offline snackbar */}
      <AnimatePresence>
        {snackbar && (
          <motion.div
            key="snackbar"
            initial={{ opacity: 0, y: -16 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -12 }}
            transition={{ duration: 0.22 }}
            className="absolute inset-x-4 top-14 z-[500] flex items-start gap-3 rounded-2xl border border-red-500/20 bg-[#1a0a0a]/95 px-4 py-3.5 shadow-2xl backdrop-blur-xl"
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

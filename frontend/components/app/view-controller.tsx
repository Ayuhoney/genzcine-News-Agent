'use client';

import { AnimatePresence, motion } from 'motion/react';
import { useSessionContext } from '@livekit/components-react';
import type { AppConfig } from '@/app-config';
import { SessionView } from '@/components/app/session-view';
import type { StartCallParams } from '@/components/app/welcome-view';
import { WelcomeView } from '@/components/app/welcome-view';

const MotionWelcomeView = motion.create(WelcomeView);
const MotionSessionView = motion.create(SessionView);

const VIEW_MOTION_PROPS = {
  variants: {
    visible: { opacity: 1 },
    hidden: { opacity: 0 },
  },
  initial: 'hidden',
  animate: 'visible',
  exit: 'hidden',
  transition: {
    duration: 0.5,
    ease: 'linear',
  },
};

interface ViewControllerProps {
  appConfig: AppConfig;
  onStartCall: (params: StartCallParams) => void | Promise<void>;
  groupRoomCode: string | null;
  trialRemainingSeconds?: number;
  onTrialExpired?: () => void;
}

export function ViewController({
  appConfig,
  onStartCall,
  groupRoomCode,
  trialRemainingSeconds,
  onTrialExpired,
}: ViewControllerProps) {
  const { isConnected } = useSessionContext();

  return (
    <AnimatePresence mode="wait">
      {!isConnected && (
        <MotionWelcomeView
          key="welcome"
          {...VIEW_MOTION_PROPS}
          className="h-full"
          startButtonText={appConfig.startButtonText}
          onStartCall={onStartCall}
        />
      )}
      {isConnected && (
        <MotionSessionView
          key="session-view"
          {...VIEW_MOTION_PROPS}
          appConfig={appConfig}
          groupRoomCode={groupRoomCode}
          trialRemainingSeconds={trialRemainingSeconds}
          onTrialExpired={onTrialExpired}
        />
      )}
    </AnimatePresence>
  );
}

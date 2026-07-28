'use client';

import { useEffect, useRef, useState } from 'react';
import { motion } from 'motion/react';
import { useRoomContext } from '@livekit/components-react';

export interface DemoVideo {
  url: string;
  title: string;
  demo: number;
  /** How many times the clip replays before closing. */
  loops: number;
  /** Absolute cue times (seconds, across all loops) — NOVA speaks a scripted line at each. */
  cues: number[];
}

interface Props {
  video: DemoVideo;
  /** Called when the video finishes (skipped=false) or the user skips it (skipped=true). */
  onClose: (skipped: boolean) => void;
}

export default function DemoVideoPlayer({ video, onClose }: Props) {
  const room = useRoomContext();
  const videoRef = useRef<HTMLVideoElement>(null);
  const [muted, setMuted] = useState(false);
  const [round, setRound] = useState(1);
  const closedRef = useRef(false);
  const loopsDoneRef = useRef(0);
  const nextCueRef = useRef(0);

  const close = (skipped: boolean) => {
    if (closedRef.current) return;
    closedRef.current = true;
    onClose(skipped);
  };

  // NOVA narrates over the clip: report each cue the moment playback crosses it
  const fireDueCues = (absoluteTime: number) => {
    while (
      nextCueRef.current < video.cues.length &&
      absoluteTime >= video.cues[nextCueRef.current]
    ) {
      const cueIdx = nextCueRef.current;
      nextCueRef.current += 1;
      room?.localParticipant
        .publishData(
          new TextEncoder().encode(
            JSON.stringify({ type: 'demo_video_cue', demo: video.demo, cue: cueIdx })
          ),
          { reliable: true }
        )
        .catch(() => {});
    }
  };

  const handleTimeUpdate = () => {
    const el = videoRef.current;
    if (!el || closedRef.current) return;
    const duration = el.duration || 0;
    fireDueCues(loopsDoneRef.current * duration + el.currentTime);
  };

  const handleEnded = () => {
    const el = videoRef.current;
    loopsDoneRef.current += 1;
    if (loopsDoneRef.current >= video.loops || !el) {
      close(false);
      return;
    }
    setRound(loopsDoneRef.current + 1);
    el.currentTime = 0;
    el.play().catch(() => {});
  };

  // Autoplay at low volume so NOVA's commentary stays clearly audible;
  // retry muted if the browser blocks audible autoplay
  useEffect(() => {
    const el = videoRef.current;
    if (!el) return;
    el.volume = 0.2;
    el.play().catch(() => {
      el.muted = true;
      setMuted(true);
      el.play().catch(() => {});
    });
  }, [video.url]);

  return (
    <motion.div
      key="demo-video"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.3 }}
      className="fixed inset-0 z-[280] flex flex-col bg-black"
    >
      {/* Video */}
      <video
        ref={videoRef}
        src={video.url}
        playsInline
        muted={muted}
        onTimeUpdate={handleTimeUpdate}
        onEnded={handleEnded}
        onError={() => close(true)}
        className="absolute inset-0 h-full w-full object-contain"
      />

      {/* Top bar */}
      <div
        className="absolute inset-x-0 top-0 z-10 flex items-center justify-between bg-gradient-to-b from-black/80 to-transparent px-4 pb-10"
        style={{ paddingTop: 'max(env(safe-area-inset-top, 0px), 1rem)' }}
      >
        <div className="flex items-center gap-2">
          <span className="h-2 w-2 animate-pulse rounded-full bg-red-500" />
          <span className="font-mono text-[10px] tracking-[0.22em] text-white/70 uppercase">
            Demo — {video.title}
          </span>
          {video.loops > 1 && (
            <span className="ml-1 rounded-full border border-white/15 bg-black/40 px-2 py-0.5 font-mono text-[9px] tracking-widest text-white/50">
              Round {round}/{video.loops}
            </span>
          )}
        </div>

        <button
          onClick={() => close(true)}
          className="rounded-full border border-white/15 bg-black/50 px-4 py-1.5 font-mono text-[11px] font-semibold tracking-wide text-white/70 backdrop-blur-sm transition-colors hover:bg-black/70 hover:text-white"
        >
          Skip →
        </button>
      </div>

      {/* Bottom hint */}
      <div
        className="absolute inset-x-0 bottom-0 z-10 bg-gradient-to-t from-black/85 to-transparent px-4 pt-12 text-center"
        style={{ paddingBottom: 'max(env(safe-area-inset-bottom, 0px), 1.25rem)' }}
      >
        <p className="font-mono text-[10px] tracking-widest text-white/40 uppercase">
          Watch — NOVA is coaching you live
        </p>
      </div>
    </motion.div>
  );
}

'use client';

import { useEffect, useRef, useState } from 'react';
import { motion } from 'motion/react';

export interface NewsVideo {
  videoId: string;
  title: string;
  topic: string;
}

interface Props {
  video: NewsVideo;
  /** Called when the video finishes (skipped=false) or the viewer skips it (skipped=true). */
  onClose: (skipped: boolean) => void;
}

interface YTPlayer {
  destroy: () => void;
}

interface YTPlayerEvent {
  data: number;
}

declare global {
  interface Window {
    YT?: {
      Player: new (
        el: HTMLElement,
        opts: {
          videoId: string;
          playerVars?: Record<string, number>;
          events?: {
            onReady?: () => void;
            onStateChange?: (e: YTPlayerEvent) => void;
            onError?: () => void;
          };
        }
      ) => YTPlayer;
    };
    onYouTubeIframeAPIReady?: () => void;
  }
}

const YT_ENDED = 0;

let ytApiPromise: Promise<void> | null = null;
function loadYouTubeApi(): Promise<void> {
  if (window.YT?.Player) return Promise.resolve();
  if (ytApiPromise) return ytApiPromise;
  ytApiPromise = new Promise((resolve) => {
    const prevCallback = window.onYouTubeIframeAPIReady;
    window.onYouTubeIframeAPIReady = () => {
      prevCallback?.();
      resolve();
    };
    const script = document.createElement('script');
    script.src = 'https://www.youtube.com/iframe_api';
    script.async = true;
    document.head.appendChild(script);
  });
  return ytApiPromise;
}

export default function NewsVideoPlayer({ video, onClose }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const playerRef = useRef<YTPlayer | null>(null);
  const closedRef = useRef(false);
  const [ready, setReady] = useState(false);

  const close = (skipped: boolean) => {
    if (closedRef.current) return;
    closedRef.current = true;
    onClose(skipped);
  };

  useEffect(() => {
    let cancelled = false;
    loadYouTubeApi().then(() => {
      if (cancelled || !containerRef.current || !window.YT) return;
      playerRef.current = new window.YT.Player(containerRef.current, {
        videoId: video.videoId,
        playerVars: { autoplay: 1, playsinline: 1, modestbranding: 1, rel: 0 },
        events: {
          onReady: () => setReady(true),
          onStateChange: (e) => {
            if (e.data === YT_ENDED) close(false);
          },
          onError: () => close(true),
        },
      });
    });
    return () => {
      cancelled = true;
      try {
        playerRef.current?.destroy();
      } catch {
        // ignore — player may already be torn down
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [video.videoId]);

  return (
    <motion.div
      key="news-video"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.3 }}
      className="fixed inset-0 z-[280] flex flex-col bg-black"
    >
      {/* YouTube player mounts into this div */}
      <div className="absolute inset-0">
        <div ref={containerRef} className="h-full w-full" />
      </div>

      {!ready && (
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-white/10 border-t-red-600" />
        </div>
      )}

      {/* Top bar */}
      <div
        className="pointer-events-none absolute inset-x-0 top-0 z-10 flex items-center justify-between bg-gradient-to-b from-black/80 to-transparent px-4 pb-10"
        style={{ paddingTop: 'max(env(safe-area-inset-top, 0px), 1rem)' }}
      >
        <div className="flex min-w-0 items-center gap-2">
          <span className="h-2 w-2 shrink-0 animate-pulse rounded-full bg-red-500" />
          <span className="truncate font-mono text-[10px] tracking-[0.22em] text-white/70 uppercase">
            Live — {video.title}
          </span>
        </div>

        <button
          onClick={() => close(true)}
          className="pointer-events-auto shrink-0 rounded-full border border-white/15 bg-black/50 px-4 py-1.5 font-mono text-[11px] font-semibold tracking-wide text-white/70 backdrop-blur-sm transition-colors hover:bg-black/70 hover:text-white"
        >
          Skip →
        </button>
      </div>

      {/* Bottom hint */}
      <div
        className="pointer-events-none absolute inset-x-0 bottom-0 z-10 bg-gradient-to-t from-black/85 to-transparent px-4 pt-12 text-center"
        style={{ paddingBottom: 'max(env(safe-area-inset-bottom, 0px), 1.25rem)' }}
      >
        <p className="font-mono text-[10px] tracking-widest text-white/40 uppercase">
          Your anchor is watching this with you
        </p>
      </div>
    </motion.div>
  );
}

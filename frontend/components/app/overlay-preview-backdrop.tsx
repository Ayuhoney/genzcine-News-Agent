'use client';

import { useEffect, useState } from 'react';

/**
 * Standalone: plain black canvas (no wallpaper / preview text).
 * Embedded iframe/WebView (?embed=1 or nested frame): nothing — host shows through.
 */
export function OverlayPreviewBackdrop() {
  const [showBlack, setShowBlack] = useState(true);

  useEffect(() => {
    const embedded =
      window.self !== window.top ||
      new URLSearchParams(window.location.search).has('embed');
    setShowBlack(!embedded);
  }, []);

  if (!showBlack) return null;

  return <div aria-hidden className="pointer-events-none fixed inset-0 -z-10 bg-black" />;
}

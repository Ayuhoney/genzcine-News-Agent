'use client';

const apiBase = () => process.env.NEXT_PUBLIC_API_URL ?? '';

function send(level: 'info' | 'warn' | 'error', message: string, context?: string) {
  // In dev, also print to console
  if (process.env.NODE_ENV === 'development') {
    const fn = level === 'error' ? console.error : level === 'warn' ? console.warn : console.log;
    fn(`[${level}]`, message, context ?? '');
  }
  // Always send to backend
  fetch(`${apiBase()}/api/log`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ level, message, context: context ?? '' }),
  }).catch(() => {}); // fire-and-forget, never throws
}

export const log = {
  info: (msg: string, ctx?: string) => send('info', msg, ctx),
  warn: (msg: string, ctx?: string) => send('warn', msg, ctx),
  error: (msg: string, ctx?: string) => send('error', msg, ctx),
};

/** Call once at app root to catch unhandled JS errors and promise rejections. */
export function installGlobalErrorHandlers() {
  if (typeof window === 'undefined') return;

  window.onerror = (message, source, line, col, error) => {
    send('error', String(message), `${source}:${line}:${col} ${error?.stack ?? ''}`);
  };

  window.addEventListener('unhandledrejection', (e) => {
    const msg = e.reason instanceof Error ? e.reason.message : String(e.reason);
    const stack = e.reason instanceof Error ? (e.reason.stack ?? '') : '';
    send('error', `Unhandled promise rejection: ${msg}`, stack);
  });
}

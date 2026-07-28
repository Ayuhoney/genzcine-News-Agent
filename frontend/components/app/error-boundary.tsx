'use client';

import { Component, type ReactNode } from 'react';
import { log } from '@/lib/logger';

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: { componentStack: string }) {
    log.error(`React crash: ${error.message}`, info.componentStack.slice(0, 300));
  }

  render() {
    if (this.state.error) {
      return (
        <div className="flex h-svh w-full flex-col items-center justify-center gap-4 bg-[#080808] px-6 text-center">
          <div className="flex h-10 w-10 items-center justify-center rounded-full bg-red-600/20">
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="#ef4444"
              strokeWidth="2"
            >
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="8" x2="12" y2="12" />
              <line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
          </div>
          <p className="text-sm text-white/50">Something went wrong. Please refresh.</p>
          <button
            onClick={() => window.location.reload()}
            className="rounded-xl bg-red-600 px-5 py-2.5 text-sm font-semibold text-white"
          >
            Refresh
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

import * as React from 'react';
import { cn } from '@/lib/utils';

export interface ChatEntryProps extends React.HTMLAttributes<HTMLLIElement> {
  locale: string;
  timestamp: number;
  message: string;
  messageOrigin: 'local' | 'remote';
  name?: string;
  hasBeenEdited?: boolean;
}

export const ChatEntry = ({
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  locale: _locale,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  timestamp: _timestamp,
  message,
  messageOrigin,
  hasBeenEdited = false,
  className,
  ...props
}: ChatEntryProps) => {
  const isLocal = messageOrigin === 'local';

  return (
    <li
      data-lk-message-origin={messageOrigin}
      className={cn('flex w-full', isLocal ? 'justify-end' : 'justify-start', className)}
      {...props}
    >
      <div className={cn('flex max-w-[82%] flex-col gap-1', isLocal ? 'items-end' : 'items-start')}>
        {/* Sender label */}
        <span className="px-1 font-mono text-[9px] tracking-[0.14em] text-white/20 uppercase">
          {isLocal ? 'You' : 'Nova'}
        </span>

        {/* Bubble */}
        <div
          className={cn(
            'rounded-2xl px-3.5 py-2.5 text-[13px] leading-relaxed',
            isLocal
              ? 'rounded-tr-sm bg-white/[0.09] text-white/80'
              : 'rounded-tl-sm border border-red-600/20 bg-red-600/[0.07] text-white/85'
          )}
        >
          {hasBeenEdited && <span className="mr-1 font-mono text-[9px] text-white/25">edited</span>}
          {message}
        </div>
      </div>
    </li>
  );
};

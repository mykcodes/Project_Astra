/**
 * ASTRA — Main Layout
 *
 * The application shell. Provides:
 * - Fullscreen container
 * - Status indicator positioning
 * - Content area for active view
 *
 * Future additions:
 * - Chat panel (docked/floating)
 * - Notch overlay
 * - Navigation controls
 */

import type { ReactNode } from 'react';
import { StatusIndicator, DevStateControls } from '@/components/system/index.ts';
import { ChatPanel, ChatToggle } from '@/components/chat/index.ts';

interface MainLayoutProps {
  children: ReactNode;
}

export function MainLayout({ children }: MainLayoutProps) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100vh',
        width: '100vw',
        position: 'relative',
        overflow: 'hidden',
      }}
    >
      {/* Status bar */}
      <header
        style={{
          position: 'absolute',
          top: 0,
          right: 0,
          zIndex: 'var(--z-elevated)',
          padding: 'var(--space-2)',
        }}
      >
        <StatusIndicator />
      </header>

      {/* Main content */}
      <main
        style={{
          display: 'flex',
          flex: 1,
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        {children}
      </main>

      {/* Overlays */}
      <ChatPanel />
      <ChatToggle />
      <DevStateControls />
    </div>
  );
}

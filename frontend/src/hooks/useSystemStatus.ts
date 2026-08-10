/**
 * ASTRA — useSystemStatus Hook
 *
 * Polls the backend health endpoint and updates the system store.
 * Manages connection state transitions.
 */

import { useEffect, useRef } from 'react';
import { useSystemStore } from '@/state/systemStore.ts';
import { checkHealth } from '@/services/api/health.ts';
import { ConnectionState } from '@/types/system.ts';

const POLL_INTERVAL_MS = 15_000; // 15 seconds
const INITIAL_DELAY_MS = 500;

export function useSystemStatus(): void {
  const setConnection = useSystemStore((s) => s.setConnection);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    let mounted = true;

    async function check() {
      if (!mounted) return;

      try {
        await checkHealth();
        setConnection(ConnectionState.CONNECTED);
      } catch {
        setConnection(ConnectionState.DISCONNECTED);
      }
    }

    // Initial check after a brief delay
    const timeout = setTimeout(() => {
      void check();

      // Then poll at regular intervals
      intervalRef.current = setInterval(() => {
        void check();
      }, POLL_INTERVAL_MS);
    }, INITIAL_DELAY_MS);

    return () => {
      mounted = false;
      clearTimeout(timeout);
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, [setConnection]);
}

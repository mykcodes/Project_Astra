/**
 * ASTRA — Status Indicator
 *
 * Small indicator showing backend connection status.
 * Positioned in the corner of the main layout.
 */

import { useSystemStore } from '@/state/systemStore.ts';
import { ConnectionState } from '@/types/system.ts';

const STATUS_CONFIG: Record<ConnectionState, { color: string; label: string }> = {
  [ConnectionState.CONNECTED]: { color: 'var(--color-success)', label: 'Connected' },
  [ConnectionState.DISCONNECTED]: { color: 'var(--color-error)', label: 'Disconnected' },
  [ConnectionState.RECONNECTING]: { color: 'var(--color-warning)', label: 'Reconnecting' },
};

export function StatusIndicator() {
  const connection = useSystemStore((s) => s.connection);
  const { color, label } = STATUS_CONFIG[connection];

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 'var(--space-2)',
        padding: 'var(--space-2) var(--space-3)',
        fontSize: 'var(--font-size-xs)',
        color: 'var(--color-text-muted)',
      }}
      title={`Backend: ${label}`}
      aria-label={`Backend status: ${label}`}
    >
      <span
        style={{
          width: '6px',
          height: '6px',
          borderRadius: '50%',
          backgroundColor: color,
          boxShadow: `0 0 6px ${color}`,
        }}
      />
      <span>{label}</span>
    </div>
  );
}

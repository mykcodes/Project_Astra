/**
 * ASTRA — Settings View
 *
 * Minimal settings page proving routing works.
 * Will be expanded with actual settings controls in future phases.
 */

import { useUIStore } from '@/state/uiStore.ts';

export function SettingsView() {
  const setActiveView = useUIStore((s) => s.setActiveView);

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      flex: 1,
      gap: 'var(--space-6)',
      color: 'var(--color-text-secondary)',
    }}>
      <h1 style={{
        fontSize: 'var(--font-size-2xl)',
        fontWeight: 'var(--font-weight-semibold)',
        color: 'var(--color-text-primary)',
      }}>
        Settings
      </h1>
      <p style={{ fontSize: 'var(--font-size-sm)' }}>
        Configuration options will appear here in future phases.
      </p>
      <button
        onClick={() => setActiveView('orb')}
        style={{
          padding: 'var(--space-2) var(--space-6)',
          background: 'var(--color-bg-elevated)',
          border: '1px solid var(--color-border)',
          borderRadius: 'var(--radius-md)',
          color: 'var(--color-text-primary)',
          cursor: 'pointer',
          fontSize: 'var(--font-size-sm)',
        }}
      >
        ← Back to ASTRA
      </button>
    </div>
  );
}

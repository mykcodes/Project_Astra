/**
 * ASTRA — Root Application Component
 *
 * Sets up the main layout and view switching.
 * Uses the system status hook to monitor backend connectivity.
 */

import { MainLayout } from '@/components/layout/MainLayout.tsx';
import { useUIStore } from '@/state/uiStore.ts';
import { useSystemStatus } from '@/hooks/useSystemStatus.ts';
import { VoiceInteractionManager } from '@/features/interaction/VoiceInteractionManager.tsx';
import { routes } from './routes.tsx';

export function App() {
  // Start backend health monitoring
  useSystemStatus();

  const activeView = useUIStore((s) => s.activeView);

  // Find the active route and render its component
  const activeRoute = routes.find((r) => r.view === activeView) ?? routes[0];

  if (!activeRoute) {
    return null;
  }

  const ViewComponent = activeRoute.component;

  return (
    <MainLayout>
      <VoiceInteractionManager />
      <ViewComponent />
    </MainLayout>
  );
}

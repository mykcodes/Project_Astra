/**
 * ASTRA — Route Definitions
 */

import { Orb } from '@/features/orb/index.ts';
import { SettingsView } from '@/features/settings/index.ts';
import type { ActiveView } from '@/state/uiStore.ts';
import type { ComponentType } from 'react';

interface RouteDefinition {
  view: ActiveView;
  component: ComponentType;
  label: string;
}

export const routes: RouteDefinition[] = [
  { view: 'orb', component: Orb, label: 'ASTRA' },
  { view: 'settings', component: SettingsView, label: 'Settings' },
];

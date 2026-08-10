/**
 * ASTRA — UI Store
 *
 * Controls UI-level state: panel visibility, theme, active view.
 */

import { create } from 'zustand';

export type Theme = 'dark' | 'light';
export type ActiveView = 'orb' | 'settings';

interface UIState {
  /** Whether the chat panel is visible (initially hidden) */
  chatPanelOpen: boolean;

  /** Current theme */
  theme: Theme;

  /** Currently active view */
  activeView: ActiveView;

  /** Toggle chat panel visibility */
  toggleChatPanel: () => void;

  /** Set chat panel visibility */
  setChatPanelOpen: (open: boolean) => void;

  /** Set the active view */
  setActiveView: (view: ActiveView) => void;

  /** Set theme */
  setTheme: (theme: Theme) => void;
}

export const useUIStore = create<UIState>((set) => ({
  chatPanelOpen: false,
  theme: 'dark',
  activeView: 'orb',

  toggleChatPanel: () => set((state) => ({ chatPanelOpen: !state.chatPanelOpen })),
  setChatPanelOpen: (chatPanelOpen) => set({ chatPanelOpen }),
  setActiveView: (activeView) => set({ activeView }),
  setTheme: (theme) => set({ theme }),
}));

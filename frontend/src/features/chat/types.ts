/**
 * ASTRA — Chat Types
 *
 * The chat interface is secondary to the orb/voice experience.
 * It is initially hidden and revealed via a UI control.
 * These types define the chat panel's state shape.
 */

export interface ChatPanelConfig {
  /** Whether the chat panel is docked or floating */
  mode: 'docked' | 'floating';
  /** Dock position when in docked mode */
  dockPosition: 'right' | 'bottom';
  /** Panel width when docked to the right */
  width: number;
  /** Panel height when docked to the bottom */
  height: number;
}

export const DEFAULT_CHAT_CONFIG: ChatPanelConfig = {
  mode: 'docked',
  dockPosition: 'right',
  width: 400,
  height: 300,
};

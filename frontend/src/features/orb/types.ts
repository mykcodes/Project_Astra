/**
 * ASTRA — Orb Types
 */

/** Visual and behavioral states of the orb */
export enum OrbState {
  IDLE = 'IDLE',
  LISTENING = 'LISTENING',
  TRANSCRIBING = 'TRANSCRIBING',
  THINKING = 'THINKING',
  SPEAKING = 'SPEAKING',
  ERROR = 'ERROR',
  DISCONNECTED = 'DISCONNECTED',
}

/** Events that trigger orb state transitions */
export enum OrbEvent {
  /** User activates ASTRA (voice activation, click, or keyboard shortcut) */
  ACTIVATE = 'ACTIVATE',
  /** Speech input detected in audio stream */
  SPEECH_DETECTED = 'SPEECH_DETECTED',
  /** User stopped speaking */
  SPEECH_END = 'SPEECH_END',
  /** AI processing has begun */
  PROCESSING_START = 'PROCESSING_START',
  /** AI response is ready */
  RESPONSE_READY = 'RESPONSE_READY',
  /** TTS playback completed */
  SPEECH_COMPLETE = 'SPEECH_COMPLETE',
  /** An error occurred */
  ERROR_OCCURRED = 'ERROR_OCCURRED',
  /** Error state cleared */
  ERROR_CLEARED = 'ERROR_CLEARED',
  /** Backend connection lost */
  CONNECTION_LOST = 'CONNECTION_LOST',
  /** Backend connection restored */
  CONNECTION_RESTORED = 'CONNECTION_RESTORED',
  /** User explicitly deactivates */
  DEACTIVATE = 'DEACTIVATE',
}

/** Contextual data carried with orb state */
export interface OrbContext {
  /** Error message when in ERROR state */
  errorMessage?: string;
  /** Future: audio input level (0-1) for visualization */
  audioLevel?: number;
  /** Future: response streaming progress (0-1) */
  responseProgress?: number;
}

/** Callback signature for state change listeners */
export type OrbStateListener = (
  state: OrbState,
  previousState: OrbState,
  event: OrbEvent,
) => void;

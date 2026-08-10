/**
 * ASTRA — Interaction Pipeline Types
 *
 * Defines the voice-first interaction pipeline. Voice is the primary
 * interaction mode; text enters the pipeline at a later stage as a
 * secondary path.
 *
 * VOICE PATH (primary):
 *   WAKE → CAPTURE → TRANSCRIBE → INTENT → ORCHESTRATE → GENERATE → SYNTHESIZE → OUTPUT
 *
 * TEXT PATH (secondary):
 *   TEXT_INPUT → INTENT → ORCHESTRATE → GENERATE → TEXT_OUTPUT
 *
 * Both paths share the INTENT → ORCHESTRATE → GENERATE core.
 */

/** Interaction mode — voice is primary, text is secondary */
export enum InteractionMode {
  VOICE = 'VOICE',
  TEXT = 'TEXT',
}

/** Pipeline stages in execution order */
export enum PipelineStage {
  // --- Voice-specific stages ---
  /** Wake word detection or activation trigger */
  WAKE = 'WAKE',
  /** Audio capture from microphone */
  CAPTURE = 'CAPTURE',
  /** Speech-to-text transcription */
  TRANSCRIBE = 'TRANSCRIBE',

  // --- Text-specific entry stage ---
  /** Direct text input (secondary path) */
  TEXT_INPUT = 'TEXT_INPUT',

  // --- Shared core stages ---
  /** Understanding user intent */
  INTENT = 'INTENT',
  /** AI orchestration (context, memory, tools, knowledge) */
  ORCHESTRATE = 'ORCHESTRATE',
  /** Response generation */
  GENERATE = 'GENERATE',

  // --- Voice output stages ---
  /** Text-to-speech synthesis */
  SYNTHESIZE = 'SYNTHESIZE',
  /** Audio playback + orb animation */
  OUTPUT = 'OUTPUT',

  // --- Text output stage ---
  /** Text display in chat (text path) */
  TEXT_OUTPUT = 'TEXT_OUTPUT',
}

/** Event emitted as the pipeline progresses through stages */
export interface InteractionEvent {
  /** Which stage this event is about */
  stage: PipelineStage;
  /** Which mode triggered the interaction */
  mode: InteractionMode;
  /** When this event occurred */
  timestamp: number;
  /** Stage-specific payload */
  data?: unknown;
  /** Error if this stage failed */
  error?: Error;
}

/** Callback for interaction pipeline events */
export type InteractionEventListener = (event: InteractionEvent) => void;

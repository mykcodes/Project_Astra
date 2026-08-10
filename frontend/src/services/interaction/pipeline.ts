/**
 * ASTRA — Interaction Pipeline
 *
 * Manages the lifecycle of a single user interaction from activation
 * through response. Emits InteractionEvents that the orb state machine,
 * UI components, and future subsystems consume.
 *
 * This is the architectural skeleton — actual stage implementations
 * (STT, TTS, AI orchestration) will be plugged in as they're built.
 */

import { PipelineStage, InteractionMode } from './types.ts';
import type { InteractionEvent, InteractionEventListener } from './types.ts';

export class InteractionPipeline {
  private _listeners: Set<InteractionEventListener> = new Set();
  private _currentStage: PipelineStage | null = null;
  private _activeMode: InteractionMode | null = null;

  /** Current pipeline stage, or null if idle */
  get currentStage(): PipelineStage | null {
    return this._currentStage;
  }

  /** Active interaction mode, or null if idle */
  get activeMode(): InteractionMode | null {
    return this._activeMode;
  }

  /** Whether an interaction is currently in progress */
  get isActive(): boolean {
    return this._currentStage !== null;
  }

  /**
   * Subscribe to pipeline events.
   * @returns Unsubscribe function
   */
  subscribe(listener: InteractionEventListener): () => void {
    this._listeners.add(listener);
    return () => {
      this._listeners.delete(listener);
    };
  }

  /**
   * Emit a pipeline event and update current stage.
   * Called by stage implementations as they execute.
   */
  emit(stage: PipelineStage, mode: InteractionMode, data?: unknown, error?: Error): void {
    this._currentStage = stage;
    this._activeMode = mode;

    const event: InteractionEvent = {
      stage,
      mode,
      timestamp: Date.now(),
      data,
      error,
    };

    for (const listener of this._listeners) {
      listener(event);
    }
  }

  /**
   * Reset pipeline to idle state.
   */
  reset(): void {
    this._currentStage = null;
    this._activeMode = null;
  }
}

/** Singleton pipeline instance */
export const interactionPipeline = new InteractionPipeline();

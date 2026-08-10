/**
 * ASTRA — Orb Finite State Machine
 *
 * A deterministic finite state machine governing the orb's behavior.
 *
 * The orb is the primary visual indicator of ASTRA's state. Each state
 * maps to a distinct visual treatment (color, animation, glow). Transitions
 * are explicit — not every state can transition to every other state.
 *
 * The animation system (future) hooks into the `subscribe` method and
 * maps (previousState, currentState) pairs to visual transitions.
 *
 * Transition table:
 *
 *   IDLE         → LISTENING      (ACTIVATE)
 *   IDLE         → ERROR          (ERROR_OCCURRED)
 *   IDLE         → DISCONNECTED   (CONNECTION_LOST)
 *
 *   LISTENING    → TRANSCRIBING   (SPEECH_END)
 *   LISTENING    → IDLE           (DEACTIVATE)
 *   LISTENING    → ERROR          (ERROR_OCCURRED)
 *   LISTENING    → DISCONNECTED   (CONNECTION_LOST)
 *
 *   TRANSCRIBING → THINKING       (PROCESSING_START)
 *   TRANSCRIBING → ERROR          (ERROR_OCCURRED)
 *   TRANSCRIBING → DISCONNECTED   (CONNECTION_LOST)
 *
 *   THINKING     → SPEAKING       (RESPONSE_READY)
 *   THINKING     → ERROR          (ERROR_OCCURRED)
 *   THINKING     → DISCONNECTED   (CONNECTION_LOST)
 *
 *   SPEAKING     → IDLE           (SPEECH_COMPLETE)
 *   SPEAKING     → LISTENING      (ACTIVATE)         ← interrupt
 *   SPEAKING     → ERROR          (ERROR_OCCURRED)
 *
 *   ERROR        → IDLE           (ERROR_CLEARED)
 *   ERROR        → LISTENING      (ACTIVATE)
 *
 *   DISCONNECTED → IDLE           (CONNECTION_RESTORED)
 */

import { OrbState, OrbEvent } from './types.ts';
import type { OrbContext, OrbStateListener } from './types.ts';

// ============================================================
// Transition Definition
// ============================================================

interface Transition {
  from: OrbState;
  event: OrbEvent;
  to: OrbState;
  guard?: (context: OrbContext) => boolean;
}

/**
 * Complete transition table.
 * If a (state, event) pair is not in this table, the event is silently ignored.
 */
const TRANSITIONS: readonly Transition[] = [
  // --- IDLE ---
  { from: OrbState.IDLE, event: OrbEvent.ACTIVATE, to: OrbState.LISTENING },
  { from: OrbState.IDLE, event: OrbEvent.ERROR_OCCURRED, to: OrbState.ERROR },
  { from: OrbState.IDLE, event: OrbEvent.CONNECTION_LOST, to: OrbState.DISCONNECTED },

  // --- LISTENING ---
  { from: OrbState.LISTENING, event: OrbEvent.SPEECH_END, to: OrbState.TRANSCRIBING },
  { from: OrbState.LISTENING, event: OrbEvent.DEACTIVATE, to: OrbState.IDLE },
  { from: OrbState.LISTENING, event: OrbEvent.ERROR_OCCURRED, to: OrbState.ERROR },
  { from: OrbState.LISTENING, event: OrbEvent.CONNECTION_LOST, to: OrbState.DISCONNECTED },

  // --- TRANSCRIBING ---
  { from: OrbState.TRANSCRIBING, event: OrbEvent.PROCESSING_START, to: OrbState.THINKING },
  { from: OrbState.TRANSCRIBING, event: OrbEvent.DEACTIVATE, to: OrbState.IDLE },
  { from: OrbState.TRANSCRIBING, event: OrbEvent.ERROR_OCCURRED, to: OrbState.ERROR },
  { from: OrbState.TRANSCRIBING, event: OrbEvent.CONNECTION_LOST, to: OrbState.DISCONNECTED },

  // --- THINKING ---
  { from: OrbState.THINKING, event: OrbEvent.RESPONSE_READY, to: OrbState.SPEAKING },
  { from: OrbState.THINKING, event: OrbEvent.DEACTIVATE, to: OrbState.IDLE },
  { from: OrbState.THINKING, event: OrbEvent.ERROR_OCCURRED, to: OrbState.ERROR },
  { from: OrbState.THINKING, event: OrbEvent.CONNECTION_LOST, to: OrbState.DISCONNECTED },

  // --- SPEAKING ---
  { from: OrbState.SPEAKING, event: OrbEvent.SPEECH_COMPLETE, to: OrbState.IDLE },
  { from: OrbState.SPEAKING, event: OrbEvent.ACTIVATE, to: OrbState.LISTENING },
  { from: OrbState.SPEAKING, event: OrbEvent.DEACTIVATE, to: OrbState.IDLE },
  { from: OrbState.SPEAKING, event: OrbEvent.ERROR_OCCURRED, to: OrbState.ERROR },

  // --- ERROR ---
  { from: OrbState.ERROR, event: OrbEvent.ERROR_CLEARED, to: OrbState.IDLE },
  { from: OrbState.ERROR, event: OrbEvent.ACTIVATE, to: OrbState.LISTENING },

  // --- DISCONNECTED ---
  { from: OrbState.DISCONNECTED, event: OrbEvent.CONNECTION_RESTORED, to: OrbState.IDLE },
] as const;

// Pre-compute a lookup map for O(1) transition resolution
const transitionMap = new Map<string, Transition>();
for (const t of TRANSITIONS) {
  transitionMap.set(`${t.from}:${t.event}`, t);
}

// ============================================================
// State Machine
// ============================================================

export class OrbStateMachine {
  private _state: OrbState;
  private _context: OrbContext;
  private _listeners: Set<OrbStateListener> = new Set();

  constructor(initialState: OrbState = OrbState.DISCONNECTED) {
    this._state = initialState;
    this._context = {};
  }

  /** Current state */
  get state(): OrbState {
    return this._state;
  }

  /** Current context */
  get context(): OrbContext {
    return { ...this._context };
  }

  /**
   * Attempt a state transition by sending an event.
   *
   * @returns `true` if the transition was legal and executed,
   *          `false` if no matching transition exists or a guard rejected it.
   */
  send(event: OrbEvent, contextUpdate?: Partial<OrbContext>): boolean {
    const key = `${this._state}:${event}`;
    const transition = transitionMap.get(key);

    if (!transition) {
      return false;
    }

    // Check guard if one exists
    if (transition.guard && !transition.guard(this._context)) {
      return false;
    }

    const previousState = this._state;
    this._state = transition.to;

    // Update context
    if (contextUpdate) {
      this._context = { ...this._context, ...contextUpdate };
    }

    // Clear error context when leaving ERROR state
    if (previousState === OrbState.ERROR && this._state !== OrbState.ERROR) {
      this._context.errorMessage = undefined;
    }

    // Notify listeners
    for (const listener of this._listeners) {
      listener(this._state, previousState, event);
    }

    return true;
  }

  /**
   * Check if an event would cause a transition from the current state.
   * Does not execute the transition.
   */
  can(event: OrbEvent): boolean {
    const key = `${this._state}:${event}`;
    const transition = transitionMap.get(key);
    if (!transition) return false;
    if (transition.guard && !transition.guard(this._context)) return false;
    return true;
  }

  /**
   * Get all events that are valid from the current state.
   */
  validEvents(): OrbEvent[] {
    return Object.values(OrbEvent).filter((event) => this.can(event));
  }

  /**
   * Subscribe to state changes.
   *
   * The animation system, orb component, and interaction pipeline
   * all hook into this to react to state transitions.
   *
   * @returns An unsubscribe function.
   */
  subscribe(listener: OrbStateListener): () => void {
    this._listeners.add(listener);
    return () => {
      this._listeners.delete(listener);
    };
  }

  /** Reset to a specific state, clearing context */
  reset(state: OrbState = OrbState.DISCONNECTED): void {
    const previousState = this._state;
    this._state = state;
    this._context = {};

    if (previousState !== state) {
      // Use DEACTIVATE as the reset event — it's the closest semantic match
      for (const listener of this._listeners) {
        listener(this._state, previousState, OrbEvent.DEACTIVATE);
      }
    }
  }
}

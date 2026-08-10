/**
 * ASTRA — System Store
 *
 * Global system state: connection status, orb state machine.
 * The orb state machine is the single source of truth for orb state.
 */

import { create } from 'zustand';
import { OrbStateMachine } from '@/features/orb/orbStateMachine.ts';
import { OrbState, OrbEvent } from '@/features/orb/types.ts';
import { ConnectionState } from '@/types/system.ts';

interface SystemState {
  /** Backend connection status */
  connection: ConnectionState;

  /** Current orb state (derived from state machine) */
  orbState: OrbState;

  /** The orb state machine instance */
  orbMachine: OrbStateMachine;

  /** Backend version from health check */
  backendVersion: string | null;

  /** Update connection state */
  setConnection: (state: ConnectionState) => void;

  /** Send an event to the orb state machine */
  sendOrbEvent: (event: OrbEvent, context?: Record<string, unknown>) => boolean;
}

// Create the state machine instance
const orbMachine = new OrbStateMachine(OrbState.DISCONNECTED);

export const useSystemStore = create<SystemState>((set) => {
  // Subscribe to state machine changes and sync with Zustand
  orbMachine.subscribe((state: OrbState) => {
    set({ orbState: state });
  });

  return {
    connection: ConnectionState.DISCONNECTED,
    orbState: orbMachine.state,
    orbMachine,
    backendVersion: null,

    setConnection: (connection) => {
      set({ connection });

      // Sync connection state with orb state machine
      if (connection === ConnectionState.CONNECTED) {
        orbMachine.send(OrbEvent.CONNECTION_RESTORED);
      } else if (connection === ConnectionState.DISCONNECTED) {
        orbMachine.send(OrbEvent.CONNECTION_LOST);
      }
    },

    sendOrbEvent: (event, context) => {
      return orbMachine.send(event, context);
    },
  };
});

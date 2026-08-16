/**
 * ASTRA — Orb Component
 *
 * The primary visual element of ASTRA. Displays the current state
 * via color, glow, and animation. Clicking the orb triggers activation.
 *
 * The component reads state from the orb state machine instance
 * in the system store. It does NOT manage state itself.
 */

import { useCallback } from 'react';
import { useSystemStore } from '@/state/systemStore.ts';
import { OrbState, OrbEvent } from './types.ts';
import { Particles } from './Particles.tsx';
import { InitializationWrapper } from './InitializationWrapper.tsx';
import './Orb.css';

/** Human-readable labels for each state */
const STATE_LABELS: Record<OrbState, string> = {
  [OrbState.IDLE]: 'Ready',
  [OrbState.LISTENING]: 'Listening',
  [OrbState.TRANSCRIBING]: 'Transcribing',
  [OrbState.THINKING]: 'Thinking',
  [OrbState.SPEAKING]: 'Speaking',
  [OrbState.ERROR]: 'Error',
  [OrbState.DISCONNECTED]: 'Disconnected',
};

export function Orb() {
  const orbState = useSystemStore((s) => s.orbState);
  const sendOrbEvent = useSystemStore((s) => s.sendOrbEvent);

  const handleClick = useCallback(() => {
    if (orbState === OrbState.IDLE || orbState === OrbState.ERROR) {
      sendOrbEvent(OrbEvent.ACTIVATE);
    } else if (orbState === OrbState.LISTENING) {
      sendOrbEvent(OrbEvent.SPEECH_END);
    } else if (orbState === OrbState.SPEAKING) {
      // Interrupt — re-activate to listen
      sendOrbEvent(OrbEvent.ACTIVATE);
    } else if (orbState === OrbState.TRANSCRIBING || orbState === OrbState.THINKING) {
      // Cancel
      sendOrbEvent(OrbEvent.DEACTIVATE);
    }
  }, [orbState, sendOrbEvent]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        handleClick();
      }
    },
    [handleClick],
  );


  return (
    <InitializationWrapper>
      <div 
        className="orb-container" 
        onClick={handleClick}
        onKeyDown={handleKeyDown}
        role="button"
        tabIndex={0}
        aria-label={`ASTRA is ${STATE_LABELS[orbState]}. Click to ${
          orbState === OrbState.LISTENING ? 'deactivate' : 'activate'
        }.`}
      >
        <Particles orbState={orbState} />
        <span className="orb-state-label">{STATE_LABELS[orbState]}</span>
      </div>
    </InitializationWrapper>
  );
}

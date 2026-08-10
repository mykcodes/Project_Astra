/**
 * ASTRA — Orb Component
 *
 * The primary visual element of ASTRA. Displays the current state
 * via color, glow, and animation. Clicking the orb triggers activation.
 *
 * The component reads state from the orb state machine instance
 * in the system store. It does NOT manage state itself.
 */

import { useCallback, useEffect, useRef } from 'react';
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

  const containerRef = useRef<HTMLDivElement>(null);

  // Simulate audio-reactive data stream for the SPEAKING state
  useEffect(() => {
    if (orbState !== OrbState.SPEAKING) {
      if (containerRef.current) {
        containerRef.current.style.setProperty('--audio-level', '0');
      }
      return;
    }

    // Simulate an audio stream emitting intensity values (0.0 to 1.0)
    let animationFrameId: number;
    let targetLevel = 0.5;
    let currentLevel = 0.5;

    const simulateAudio = () => {
      // Every few frames, pick a new random target audio level
      if (Math.random() < 0.1) {
        targetLevel = 0.3 + Math.random() * 0.7; // keeping it somewhat loud
      }

      // Ease current level towards target level for smoothness
      currentLevel += (targetLevel - currentLevel) * 0.2;

      if (containerRef.current) {
        containerRef.current.style.setProperty('--audio-level', currentLevel.toFixed(3));
      }

      animationFrameId = requestAnimationFrame(simulateAudio);
    };

    animationFrameId = requestAnimationFrame(simulateAudio);

    return () => {
      cancelAnimationFrame(animationFrameId);
    };
  }, [orbState]);

  return (
    <InitializationWrapper>
      <Particles />
      <div className="orb-container" ref={containerRef}>
        <div className="orb-atmospheric-glow" data-state={orbState} />
        <div
          className="orb"
          data-state={orbState}
          onClick={handleClick}
          onKeyDown={handleKeyDown}
          role="button"
          tabIndex={0}
          aria-label={`ASTRA is ${STATE_LABELS[orbState]}. Click to ${
            orbState === OrbState.LISTENING ? 'deactivate' : 'activate'
          }.`}
        >
          <div className="orb-energy-ring" />
          <div className="orb-core" />
        </div>
        <span className="orb-state-label">{STATE_LABELS[orbState]}</span>
      </div>
    </InitializationWrapper>
  );
}

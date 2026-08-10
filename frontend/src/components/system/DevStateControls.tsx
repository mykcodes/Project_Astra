import { useSystemStore } from '@/state/systemStore.ts';
import { OrbEvent } from '@/features/orb/types.ts';
import { isDev } from '@/utils/env.ts';
import './DevStateControls.css';

export function DevStateControls() {
  const { orbState, orbMachine, sendOrbEvent } = useSystemStore();

  if (!isDev) return null;

  return (
    <div className="dev-state-controls">
      <div className="dev-state-header">
        <span className="dev-state-title">Dev Controls (Orb State)</span>
        <span className="dev-state-current">{orbState}</span>
      </div>
      <div className="dev-state-buttons">
        <button 
          onClick={() => sendOrbEvent(OrbEvent.ACTIVATE)}
          disabled={!orbMachine.can(OrbEvent.ACTIVATE)}
        >
          Activate
        </button>
        <button 
          onClick={() => sendOrbEvent(OrbEvent.SPEECH_END)}
          disabled={!orbMachine.can(OrbEvent.SPEECH_END)}
        >
          Speech End (Think)
        </button>
        <button 
          onClick={() => sendOrbEvent(OrbEvent.RESPONSE_READY)}
          disabled={!orbMachine.can(OrbEvent.RESPONSE_READY)}
        >
          Response Ready (Speak)
        </button>
        <button 
          onClick={() => sendOrbEvent(OrbEvent.SPEECH_COMPLETE)}
          disabled={!orbMachine.can(OrbEvent.SPEECH_COMPLETE)}
        >
          Speech Complete
        </button>
        <button 
          onClick={() => sendOrbEvent(OrbEvent.ERROR_OCCURRED, { errorMessage: 'Simulated Error' })}
          disabled={!orbMachine.can(OrbEvent.ERROR_OCCURRED)}
        >
          Simulate Error
        </button>
        <button 
          onClick={() => sendOrbEvent(OrbEvent.ERROR_CLEARED)}
          disabled={!orbMachine.can(OrbEvent.ERROR_CLEARED)}
        >
          Clear Error
        </button>
        <button 
          onClick={() => sendOrbEvent(OrbEvent.DEACTIVATE)}
          disabled={!orbMachine.can(OrbEvent.DEACTIVATE)}
        >
          Deactivate (Idle)
        </button>
      </div>
    </div>
  );
}

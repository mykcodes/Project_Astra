import { useUIStore } from '@/state/uiStore.ts';
import './ChatPanel.css';

export function ChatPanel() {
  const { chatPanelOpen, setChatPanelOpen } = useUIStore();

  return (
    <div className={`chat-panel-container ${chatPanelOpen ? 'open' : ''}`}>
      <div className="chat-panel">
        <header className="chat-panel-header">
          <h2 className="chat-panel-title">ASTRA Chat</h2>
          <button 
            className="chat-panel-close-btn" 
            onClick={() => setChatPanelOpen(false)}
            aria-label="Close Chat"
          >
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
        </header>
        <div className="chat-panel-content">
          <p className="chat-panel-placeholder">
            Chat functionality will be implemented in a future phase.
          </p>
        </div>
        <div className="chat-panel-input">
          <input type="text" placeholder="Message ASTRA..." disabled />
        </div>
      </div>
    </div>
  );
}

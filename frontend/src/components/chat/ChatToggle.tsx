import { useUIStore } from '@/state/uiStore.ts';
import './ChatToggle.css';

export function ChatToggle() {
  const { chatPanelOpen, toggleChatPanel } = useUIStore();

  if (chatPanelOpen) return null;

  return (
    <button 
      className="chat-toggle-btn"
      onClick={toggleChatPanel}
      aria-label="Open Chat"
    >
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
      </svg>
    </button>
  );
}

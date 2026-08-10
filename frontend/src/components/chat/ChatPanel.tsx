import { useState, useRef, useEffect } from 'react';
import { useUIStore } from '@/state/uiStore.ts';
import { voiceClient } from '@/services/api/voiceClient.ts';
import './ChatPanel.css';

interface Message {
  id: string;
  role: 'user' | 'astra';
  content: string;
}

export function ChatPanel() {
  const { chatPanelOpen, setChatPanelOpen } = useUIStore();
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputText, setInputText] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const endOfMessagesRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (endOfMessagesRef.current) {
      endOfMessagesRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, isTyping]);

  const handleSend = async () => {
    if (!inputText.trim() || isTyping) return;
    
    const userMsg: Message = { id: Date.now().toString(), role: 'user', content: inputText.trim() };
    setMessages(prev => [...prev, userMsg]);
    setInputText('');
    setIsTyping(true);

    try {
      const response = await voiceClient.sendMessage(userMsg.content);
      const astraMsg: Message = { id: Date.now().toString() + '-resp', role: 'astra', content: response };
      setMessages(prev => [...prev, astraMsg]);
    } catch (error) {
      console.error('Chat error:', error);
      const errorMsg: Message = { id: Date.now().toString() + '-err', role: 'astra', content: "Sorry, I encountered an error." };
      setMessages(prev => [...prev, errorMsg]);
    } finally {
      setIsTyping(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      handleSend();
    }
  };

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
        <div className="chat-panel-content" style={{ display: 'flex', flexDirection: 'column', padding: '16px', overflowY: 'auto', gap: '8px', justifyContent: 'flex-start', alignItems: 'stretch' }}>
          {messages.length === 0 ? (
            <p className="chat-panel-placeholder">
              Type a message to start chatting with ASTRA.
            </p>
          ) : (
            messages.map(msg => (
              <div key={msg.id} style={{ 
                alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start',
                backgroundColor: msg.role === 'user' ? 'rgba(255, 255, 255, 0.1)' : 'transparent',
                border: msg.role === 'astra' ? '1px solid rgba(255, 255, 255, 0.1)' : 'none',
                padding: '8px 12px',
                borderRadius: '8px',
                maxWidth: '85%',
                wordBreak: 'break-word',
                color: 'white',
                fontSize: '14px',
                lineHeight: '1.4'
              }}>
                {msg.content}
              </div>
            ))
          )}
          {isTyping && (
            <div style={{ alignSelf: 'flex-start', color: 'rgba(255, 255, 255, 0.5)', fontSize: '12px' }}>
              ASTRA is thinking...
            </div>
          )}
          <div ref={endOfMessagesRef} />
        </div>
        <div className="chat-panel-input">
          <input 
            type="text" 
            placeholder="Message ASTRA..." 
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isTyping}
          />
        </div>
      </div>
    </div>
  );
}

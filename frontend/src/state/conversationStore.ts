/**
 * ASTRA — Conversation Store
 *
 * State for the active conversation. No API calls yet —
 * this establishes the state shape for when conversations are implemented.
 */

import { create } from 'zustand';
import type { Conversation, Message } from '@/types/conversation.ts';

interface ConversationState {
  /** Currently active conversation */
  activeConversation: Conversation | null;

  /** Messages in the active conversation */
  messages: Message[];

  /** Whether messages are being loaded */
  isLoading: boolean;

  /** Set the active conversation */
  setActiveConversation: (conversation: Conversation | null) => void;

  /** Set messages */
  setMessages: (messages: Message[]) => void;

  /** Add a message to the active conversation */
  addMessage: (message: Message) => void;

  /** Set loading state */
  setLoading: (loading: boolean) => void;

  /** Clear conversation state */
  clear: () => void;
}

export const useConversationStore = create<ConversationState>((set) => ({
  activeConversation: null,
  messages: [],
  isLoading: false,

  setActiveConversation: (conversation) => set({ activeConversation: conversation }),
  setMessages: (messages) => set({ messages }),
  addMessage: (message) => set((state) => ({ messages: [...state.messages, message] })),
  setLoading: (isLoading) => set({ isLoading }),
  clear: () => set({ activeConversation: null, messages: [], isLoading: false }),
}));

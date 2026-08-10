/**
 * ASTRA — Conversation Types
 */

import type { ID, Timestamp } from './common.ts';

export enum MessageRole {
  USER = 'user',
  ASSISTANT = 'assistant',
  SYSTEM = 'system',
}

export interface Message {
  id: ID;
  conversationId: ID;
  role: MessageRole;
  content: string;
  createdAt: Timestamp;
  metadata?: Record<string, unknown>;
}

export enum ConversationStatus {
  ACTIVE = 'active',
  ARCHIVED = 'archived',
}

export interface Conversation {
  id: ID;
  title?: string;
  status: ConversationStatus;
  createdAt: Timestamp;
  updatedAt: Timestamp;
  messageCount: number;
}

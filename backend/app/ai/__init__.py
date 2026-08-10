"""
ASTRA AI Module Architecture

This module isolates all LLM and AI logic from the rest of the application.

Architecture:
┌─────────────────────────────────────────────────┐
│                  ORCHESTRATOR                    │
│  Receives: OrchestratorRequest                  │
│  Accesses: ContextBuilder, Memory, Tools, etc.  │
│  Produces: OrchestratorResponse                 │
│                                                 │
│  Calls provider via AIProvider interface ONLY    │
│  Never exposes provider details to callers       │
└────────────────────┬────────────────────────────┘
                     │ AIRequest (prompt + config)
                     ▼
┌─────────────────────────────────────────────────┐
│                   PROVIDER                       │
│  Receives: AIRequest (prompt, model config)     │
│  Returns: AIResponse (text, tokens, metadata)   │
│                                                 │
│  Knows NOTHING about:                           │
│  - Memory         - Tools                       │
│  - Knowledge      - Conversations               │
│  - Users          - Context                     │
│  - Database       - File system                 │
└─────────────────────────────────────────────────┘
"""

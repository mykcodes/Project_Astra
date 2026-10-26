# ASTRA Architecture Overview

## 1. System Vision

ASTRA is a personal AI operating system, not a simple chatbot. It is built to eventually support:
- Voice-first interaction
- Persistent memory (Short, Working, Long, Episodic, Semantic)
- Document knowledge (RAG)
- Agentic workflows
- Extensible tool execution

## 2. Layer Architecture

The system is strictly divided into layers, with one-way dependencies pointing downwards.

```
┌──────────────────────────────────────────────┐
│ Experience Layer                             │
│ (Orb UI, Voice Interaction, Settings, Chat)  │
├──────────────────────────────────────────────┤
│ Application Layer                            │
│ (Conversations, Projects, Tasks, Files)      │
├──────────────────────────────────────────────┤
│ Intelligence Layer                           │
│ (Orchestrator, AI Providers, Context, Verif) │
├──────────────────────────────────────────────┤
│ Memory & Knowledge Layer                     │
│ (Memory systems, RAG Pipeline)               │
├──────────────────────────────────────────────┤
│ Action Layer                                 │
│ (Tool Registry, Execution Engine)            │
├──────────────────────────────────────────────┤
│ Infrastructure Layer                         │
│ (PostgreSQL, FastAPI, Events, Logging)       │
└──────────────────────────────────────────────┘
```

## 3. Frontend Architecture

- **React + Vite**: Fast, modern foundation.
- **Orb-First**: The primary UI is a reactive Orb governed by a deterministic Finite State Machine (FSM).
- **Voice-First Pipeline**: Interaction flows through typed stages (`WAKE` -> `CAPTURE` -> `TRANSCRIBE` -> `INTENT` -> `ORCHESTRATE` -> `GENERATE` -> `SYNTHESIZE` -> `OUTPUT`).
- **Platform Agnostic**: The `PlatformAdapter` abstracts browser APIs so the UI can later be wrapped in Electron or Tauri for desktop capabilities (like a Notch interface).

## 4. Backend Architecture

- **FastAPI**: Async, fast, type-safe API.
- **Repository Pattern**: Data access is abstracted via `BaseRepository`. Handlers don't write SQL.
- **Strict AI Separation**: The rest of the app does not know what LLM is running. The `AIProvider` interface handles the actual generation. The `Orchestrator` handles context gathering.

## 5. Security Principles

- No hardcoded secrets. Use `.env`.
- Tool execution requires explicit permission scopes.
- All dependencies are pinned.

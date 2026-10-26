# ADR 001: Initial Technology Stack

**Date:** 2026-08-09
**Status:** Accepted

## Context

We need to establish the foundational technology stack for ASTRA, a personal AI operating system. The stack must support rapid frontend UI development (specifically complex WebGL/CSS animations for the orb), async backend processing for LLM orchestration, and vector-ready database storage. It must also have a clear path to desktop app deployment in the future.

## Decision

We have selected the following stack:

1. **Frontend**: React + TypeScript + Vite + Zustand + React Router v7
2. **Backend**: Python 3.11+ + FastAPI + SQLAlchemy 2.0 (Async) + Alembic
3. **Database**: PostgreSQL 16+ with pgvector extension
4. **AI Provider**: Google Gemini (via an abstracted `AIProvider` interface)
5. **Package Management**: npm (frontend), pip/requirements.txt (backend)

## Rationale

- **React/Vite**: Industry standard, huge ecosystem for animation libraries, easy transition to Electron or Tauri.
- **Zustand**: Lightweight, avoids Redux boilerplate, works perfectly with the Orb finite state machine pattern.
- **Python/FastAPI**: Python is the lingua franca of AI. FastAPI provides excellent async support and automatic OpenAPI documentation, crucial for internal tool generation.
- **SQLAlchemy 2.0 Async**: Best-in-class ORM with full type hinting and async support.
- **PostgreSQL/pgvector**: Essential for future RAG and vector-based semantic memory.
- **Gemini**: Chosen as the initial provider, but the architecture strictly abstracts it so OpenAI or Anthropic can be swapped in without changing business logic.

## Consequences

- The team must maintain expertise in both TypeScript and Python.
- Desktop capabilities (like window management) will require an abstraction layer (`PlatformAdapter`) until an Electron/Tauri wrapper is introduced.

# Voice Architecture

This directory contains documentation for ASTRA's voice processing pipeline.

## Pipeline

ASTRA is voice-first. The complete pipeline is:
`WAKE -> CAPTURE -> TRANSCRIBE -> INTENT -> ORCHESTRATE -> GENERATE -> SYNTHESIZE -> OUTPUT`

- The Frontend manages CAPTURE and OUTPUT.
- The Backend manages TRANSCRIBE, INTENT, ORCHESTRATE, GENERATE, and SYNTHESIZE.

For code, see:
- Frontend: `frontend/src/services/interaction/`
- Backend: `backend/app/voice/`

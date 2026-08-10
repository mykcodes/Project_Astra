# Memory Architecture

This directory contains documentation for ASTRA's memory systems.

## Memory Types

1. **Short-Term Memory**: The active conversation window. Passed directly to the LLM.
2. **Working Memory**: Active context about current projects, tasks, or files the user is looking at.
3. **Long-Term Memory**: Explicitly requested facts ("remember my wifi password").
4. **Episodic Memory**: Summaries of past interactions and events.
5. **Semantic Memory**: Abstract concepts and entity relationships extracted over time.

For code, see `backend/app/memory/`.

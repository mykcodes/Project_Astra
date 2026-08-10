# AI System Architecture

This directory contains documentation for ASTRA's AI architecture.

## Overview

The AI system is strictly separated into:
1. **Providers**: Concrete implementations of LLM APIs (Gemini, OpenAI, Anthropic). They only know about tokens and text.
2. **Orchestrator**: Assembles context, decides when to use tools, and calls providers.
3. **Verification**: A future system for grounding responses and detecting hallucinations.
4. **Context Builder**: Assembles the working memory and relevant semantic/episodic memory for the current prompt.

For code, see `backend/app/ai/`.

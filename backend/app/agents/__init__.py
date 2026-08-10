"""
ASTRA Agent Architecture

Supports multi-step reasoning and execution loops (agentic workflows)
that operate independently of the standard conversational request-response cycle.
"""

from enum import Enum


class AgentState(str, Enum):
    PLANNING = "planning"
    EXECUTING = "executing"
    OBSERVING = "observing"
    REASONING = "reasoning"
    COMPLETED = "completed"
    FAILED = "failed"

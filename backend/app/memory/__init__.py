"""
ASTRA Memory Architecture

The memory system defines what ASTRA remembers, why, and for how long.

Categories (Future):
- ShortTerm: The current active conversation context
- Working: Active project/task context
- LongTerm: Explicitly saved user facts
- Episodic: Interaction history and summaries
- Semantic: Concept and entity relationships
"""

from enum import Enum


class MemoryType(str, Enum):
    SHORT_TERM = "short_term"
    WORKING = "working"
    LONG_TERM = "long_term"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"

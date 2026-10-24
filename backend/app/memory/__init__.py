"""
ASTRA Memory Architecture (Phase B.10)

The memory system manages what ASTRA remembers across sessions:
- ShortTerm: The current active conversation context
- Working: Active project/task execution context
- LongTerm: Explicitly saved user facts and durable preferences
- Episodic: Interaction history and verified completed goal summaries
- Semantic: Application profiles, concepts, and entity alias relationships
"""

from app.domain.memory import (
    MEMORY_SCHEMA_VERSION,
    MemoryType,
    ProvenanceType,
    MemoryRecord,
    ApplicationProfile,
    EpisodicGoalSummary,
    MemoryQuery,
    MemorySearchResult,
)
from app.memory.engine import MemoryEngine, get_memory_engine

__all__ = [
    "MEMORY_SCHEMA_VERSION",
    "MemoryType",
    "ProvenanceType",
    "MemoryRecord",
    "ApplicationProfile",
    "EpisodicGoalSummary",
    "MemoryQuery",
    "MemorySearchResult",
    "MemoryEngine",
    "get_memory_engine",
]

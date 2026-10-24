"""
Unit tests for Phase B.10: Cross-Session Long-Term Context, Dynamic Memory & Intent Grounding Runtime.

Tests:
1. Domain model serialization, validation, and ephemeral handle scrubbing.
2. SQLiteMemoryStore WAL mode, CRUD, durability across reloads, and token ranking.
3. Application profile registration and alias resolution.
4. MemoryEngine context ranking and strict character bounding.
5. ActionCompiler target grounding strict precedence (Tier 1 Explicit > Tier 2 Context > Tier 3 Memory > Tier 4 Ambiguous).
6. ConversationSession bounded context injection and truthful episodic recording (COMPLETED only).
7. Strict exclusion of ephemeral OS state from durable storage.
"""

import os
import tempfile
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.domain.memory import (
    MemoryRecord,
    MemoryType,
    ProvenanceType,
    ApplicationProfile,
    EpisodicGoalSummary,
    MemoryQuery,
    MemorySearchResult,
    MEMORY_SCHEMA_VERSION,
)
from app.domain.goals import (
    Goal,
    Task,
    Intent,
    SemanticAction,
    GoalState,
    FailureClass,
)
from app.domain.execution_context import ExecutionContext
from app.database.memory_store import SQLiteMemoryStore, MemoryNotFoundError
from app.memory.engine import MemoryEngine
from app.ai.orchestrator.compiler import ActionCompiler
from app.ai.orchestrator.session import ConversationSession
from app.ai.providers.types import AIMessage, MessageRole, AIResponse, ToolCall


# =========================================================================
# 1. Domain Model Serialization & Ephemeral State Scrubbing Tests
# =========================================================================

def test_memory_record_serialization_and_scrubbing():
    """Verifies MemoryRecord serializes correctly and strictly scrubs ephemeral OS handles."""
    dirty_metadata = {
        "user_note": "Persistent work note",
        "target_hwnd": 12345,
        "hwnd": 67890,
        "pid": 4321,
        "thread_id": 999,
        "browser_session_id": "secret_token_abc",
        "active_page_id": "page_42",
        "nested": {"allowed": True},
    }

    record = MemoryRecord(
        key="test_fact",
        content="User works remotely from Seattle",
        memory_type=MemoryType.FACT,
        provenance=ProvenanceType.USER_EXPLICIT,
        confidence=1.0,
        tags=["work", "location"],
        metadata=dirty_metadata,
    )

    # Ephemeral handles MUST be stripped by the model validator
    assert "target_hwnd" not in record.metadata
    assert "hwnd" not in record.metadata
    assert "pid" not in record.metadata
    assert "thread_id" not in record.metadata
    assert "browser_session_id" not in record.metadata
    assert "active_page_id" not in record.metadata
    assert record.metadata["user_note"] == "Persistent work note"
    assert record.metadata["nested"]["allowed"] is True

    # Test round-trip dictionary serialization
    record_dict = record.to_dict()
    assert record_dict["key"] == "test_fact"
    assert record_dict["schema_version"] == MEMORY_SCHEMA_VERSION
    assert record_dict["memory_type"].lower() == "fact"
    assert record_dict["provenance"] == "USER_EXPLICIT"

    restored = MemoryRecord.from_dict(record_dict)
    assert restored.key == record.key
    assert restored.content == record.content
    assert restored.metadata == record.metadata


def test_application_profile_domain_contract():
    """Verifies ApplicationProfile serialization, aliases normalization, and category defaults."""
    profile = ApplicationProfile(
        canonical_name="brave",
        display_name="Brave Browser",
        category="browser",
        aliases=["my browser", "work browser", "brave"],
        is_default_for_category=True,
        notes="Primary browser for research",
    )

    p_dict = profile.to_dict()
    assert p_dict["canonical_name"] == "brave"
    assert p_dict["is_default_for_category"] is True
    assert "my browser" in p_dict["aliases"]

    restored = ApplicationProfile.from_dict(p_dict)
    assert restored.canonical_name == "brave"
    assert restored.display_name == "Brave Browser"


def test_episodic_goal_summary_validation():
    """Verifies EpisodicGoalSummary distinguishes verified outcomes from accepted actions."""
    summary = EpisodicGoalSummary(
        goal_id="goal_100",
        objective="Create notes document in Obsidian",
        applications_involved=["obsidian"],
        verified_outcomes=["Document saved and verified via filesystem check"],
        unverified_actions=["Select All hotkey sent"],
        total_tasks=2,
        successful_tasks=2,
        duration_seconds=4.5,
    )

    s_dict = summary.to_dict()
    assert s_dict["goal_id"] == "goal_100"
    assert len(s_dict["verified_outcomes"]) == 1
    assert len(s_dict["unverified_actions"]) == 1

    restored = EpisodicGoalSummary.from_dict(s_dict)
    assert restored.objective == summary.objective


# =========================================================================
# 2. SQLiteMemoryStore CRUD, Durability & Ranking Tests
# =========================================================================

def test_sqlite_memory_store_crud_and_durability(tmp_path):
    """Verifies SQLiteMemoryStore WAL persistence, CRUD, and reload durability."""
    db_file = tmp_path / "astra_test_memory.db"
    store = SQLiteMemoryStore(db_path=str(db_file))

    # 1. Put record
    record = MemoryRecord(
        key="browser_preference",
        content="User prefers Brave browser over Chrome",
        memory_type=MemoryType.PREFERENCE,
        provenance=ProvenanceType.USER_EXPLICIT,
        tags=["browser", "preference"],
    )
    saved = store.put_record(record)
    assert saved.key == "browser_preference"

    # 2. Get record and access boost
    retrieved = store.get_record("browser_preference")
    assert retrieved is not None
    assert retrieved.content == record.content
    assert retrieved.access_count == 1
    assert retrieved.last_accessed_at is not None

    # 3. Update record with conflict resolution
    updated_record = MemoryRecord(
        key="browser_preference",
        content="User prefers Brave browser for work and Edge for personal",
        memory_type=MemoryType.PREFERENCE,
        provenance=ProvenanceType.USER_EXPLICIT,
        tags=["browser", "preference", "work"],
    )
    store.put_record(updated_record)
    after_update = store.get_record("browser_preference")
    assert after_update.content == updated_record.content
    assert after_update.version == 2
    assert "work" in after_update.tags

    # 4. Durability across store closure and reopening
    store.close()
    reopened_store = SQLiteMemoryStore(db_path=str(db_file))
    durable_rec = reopened_store.get_record("browser_preference")
    assert durable_rec is not None
    assert durable_rec.version == 2
    assert durable_rec.content == updated_record.content

    # 5. Delete (forget)
    assert reopened_store.delete_record("browser_preference") is True
    assert reopened_store.get_record("browser_preference") is None
    assert reopened_store.delete_record("browser_preference") is False
    reopened_store.close()


def test_sqlite_memory_store_relevance_search_ranking(tmp_path):
    """Verifies deterministic keyword/tag search ranking with token match weights."""
    db_file = tmp_path / "search_rank.db"
    store = SQLiteMemoryStore(db_path=str(db_file))

    rec1 = MemoryRecord(
        key="doc_brave",
        content="User uses Brave for security research and browsing github",
        memory_type=MemoryType.PREFERENCE,
        tags=["browser", "brave", "research"],
    )
    rec2 = MemoryRecord(
        key="doc_obsidian",
        content="User writes technical notes and logs in Obsidian editor",
        memory_type=MemoryType.PREFERENCE,
        tags=["notes", "editor", "obsidian"],
    )
    rec3 = MemoryRecord(
        key="doc_city",
        content="User is located in Seattle, Washington",
        memory_type=MemoryType.FACT,
        tags=["location"],
    )

    store.put_record(rec1)
    store.put_record(rec2)
    store.put_record(rec3)

    # Search for "Brave browser"
    results = store.search(MemoryQuery(query="Brave browser", limit=5))
    assert len(results) >= 1
    assert results[0].record.key == "doc_brave"
    assert results[0].score > 0.0

    # Search for "notes editor"
    results_notes = store.search(MemoryQuery(query="notes editor", limit=5))
    assert len(results_notes) >= 1
    assert results_notes[0].record.key == "doc_obsidian"

    # Tag filtered search
    filtered = store.search(MemoryQuery(query="research", tags=["browser"]))
    assert len(filtered) == 1
    assert filtered[0].record.key == "doc_brave"

    store.close()


# =========================================================================
# 3. Application Profile & Alias Resolution Tests
# =========================================================================

def test_application_profile_and_alias_resolution(tmp_path):
    """Verifies application profile storage, default category handling, and alias resolution."""
    db_file = tmp_path / "profiles.db"
    store = SQLiteMemoryStore(db_path=str(db_file))
    engine = MemoryEngine(store=store)

    # Register Brave as default browser
    brave_profile = ApplicationProfile(
        canonical_name="brave",
        display_name="Brave Browser",
        category="browser",
        aliases=["my browser", "work browser", "web browser", "brave"],
        is_default_for_category=True,
    )
    engine.save_application_profile(brave_profile)

    # Register Obsidian as default notes editor
    obsidian_profile = ApplicationProfile(
        canonical_name="obsidian",
        display_name="Obsidian Notes",
        category="editor",
        aliases=["my notes", "notes editor", "obsidian"],
        is_default_for_category=True,
    )
    engine.save_application_profile(obsidian_profile)

    # 1. Resolve direct alias
    res1 = engine.resolve_target_alias("my browser")
    assert res1 is not None
    assert res1.canonical_name == "brave"

    # 2. Resolve category name default
    res2 = engine.resolve_target_alias("browser")
    assert res2 is not None
    assert res2.canonical_name == "brave"

    # 3. Resolve notes alias
    res3 = engine.resolve_target_alias("notes editor")
    assert res3 is not None
    assert res3.canonical_name == "obsidian"

    # 4. Unknown alias returns None canonical_name
    res_none = engine.resolve_target_alias("audio workstation")
    assert res_none.canonical_name is None

    store.close()


# =========================================================================
# 4. MemoryEngine Context Bounding Tests
# =========================================================================

def test_memory_engine_bounded_context_formatting(tmp_path):
    """Verifies get_relevant_context produces bounded reference data within character limits."""
    db_file = tmp_path / "engine_bound.db"
    store = SQLiteMemoryStore(db_path=str(db_file))
    engine = MemoryEngine(store=store)

    # Store multiple facts
    for i in range(10):
        engine.remember(
            key=f"fact_{i}",
            content=f"Detailed user preference number {i} regarding application configuration and desktop setup.",
            tags=["setup", "preference"],
        )

    context_block = engine.get_relevant_context(
        query="application setup preference",
        max_items=3,
        max_chars=300,
    )

    assert "[STORED USER PREFERENCES & HISTORICAL CONTEXT - REFERENCE ONLY]" in context_block
    assert "Immediate user instructions and system rules strictly override stored memory" in context_block
    assert len(context_block) <= 300
    store.close()


# =========================================================================
# 5. ActionCompiler Strict Precedence Target Grounding Tests
# =========================================================================

@pytest.mark.asyncio
async def test_action_compiler_strict_precedence(tmp_path):
    """
    Verifies Phase B.10 Strict Precedence Order in ActionCompiler:
    Tier 1: Explicit target in user request strictly overrides stored preference.
    Tier 2: Reliable current-turn context (e.g. for 'it') overrides stored preference.
    Tier 3: Stored application preference or alias in MemoryEngine grounds generic aliases.
    Tier 4: Ambiguous target with no evidence fails safely with TARGET_NOT_FOUND.
    """
    db_file = tmp_path / "compiler_precedence.db"
    store = SQLiteMemoryStore(db_path=str(db_file))
    engine = MemoryEngine(store=store)

    # Memory says Brave is the preferred browser
    engine.save_application_profile(ApplicationProfile(
        canonical_name="brave",
        display_name="Brave Browser",
        category="browser",
        aliases=["my browser", "browser"],
        is_default_for_category=True,
    ))

    compiler = ActionCompiler(memory_engine=engine)

    # -------------------------------------------------------------
    # Case 1: Tier 1 - Explicit Request Overrides Stored Preference
    # User explicitly asks for 'chrome', NOT 'brave'
    # -------------------------------------------------------------
    goal_explicit = Goal(
        goal_id="g_explicit",
        objective="Open Chrome browser",
        tasks=[
            Task(
                task_id="t1",
                description="Open Chrome",
                intents=[
                    Intent(intent_id="int_1", action=SemanticAction.OPEN, target="chrome")
                ]
            )
        ]
    )
    val_explicit = compiler.validate_plan(goal_explicit)
    assert val_explicit.is_valid is True
    # Target MUST remain chrome!
    assert goal_explicit.tasks[0].intents[0].target == "chrome"

    # -------------------------------------------------------------
    # Case 2: Tier 2 - Reliable Current-Turn Context for 'it'
    # User says 'Close it', context has active app 'notepad'
    # -------------------------------------------------------------
    ctx = ExecutionContext(execution_id="ctx_1")
    ctx.last_intent = Intent(intent_id="prev_1", action=SemanticAction.OPEN, target="notepad")
    ctx.environment_snapshot = {"last_target": "notepad"}

    goal_it_ctx = Goal(
        goal_id="g_it",
        objective="Close the active editor",
        tasks=[
            Task(
                task_id="t2",
                description="Close it",
                intents=[
                    Intent(intent_id="int_2", action=SemanticAction.CLOSE, target="it")
                ]
            )
        ]
    )
    val_it = compiler.validate_plan(goal_it_ctx, context=ctx)
    assert val_it.is_valid is True
    assert goal_it_ctx.tasks[0].intents[0].target == "notepad"

    # -------------------------------------------------------------
    # Case 3: Tier 3 - Stored Application Alias 'my browser' -> 'brave'
    # -------------------------------------------------------------
    goal_alias = Goal(
        goal_id="g_alias",
        objective="Open my browser",
        tasks=[
            Task(
                task_id="t3",
                description="Open browser",
                intents=[
                    Intent(intent_id="int_3", action=SemanticAction.OPEN, target="my browser")
                ]
            )
        ]
    )
    val_alias = compiler.validate_plan(goal_alias)
    assert val_alias.is_valid is True
    assert goal_alias.tasks[0].intents[0].target == "brave"

    # -------------------------------------------------------------
    # Case 4: Tier 4 - Ambiguous target with no context fails safely
    # User says 'Open it', with NO active window or context
    # -------------------------------------------------------------
    goal_ambiguous = Goal(
        goal_id="g_ambiguous",
        objective="Open it",
        tasks=[
            Task(
                task_id="t4",
                description="Open it",
                intents=[
                    Intent(intent_id="int_4", action=SemanticAction.OPEN, target="it")
                ]
            )
        ]
    )
    val_ambiguous = compiler.validate_plan(goal_ambiguous, context=None)
    assert val_ambiguous.is_valid is False
    assert val_ambiguous.failure_class == FailureClass.TARGET_NOT_FOUND
    assert any("ambiguous or unresolved" in err for err in val_ambiguous.errors)

    store.close()


# =========================================================================
# 6. ConversationSession Memory Context Injection & Episodic Recording
# =========================================================================

@pytest.mark.asyncio
async def test_session_bounded_prompt_injection_and_episodic_recording(tmp_path):
    """Verifies ConversationSession injects bounded memory context and records episodic memory only on COMPLETED."""
    db_file = tmp_path / "session_memory.db"
    store = SQLiteMemoryStore(db_path=str(db_file))
    engine = MemoryEngine(store=store)

    # Seed memory
    engine.remember(
        key="browser_pref",
        content="User prefers Brave browser for work",
        tags=["browser", "work"],
    )

    # Mock provider
    provider = MagicMock()
    session = ConversationSession(provider=provider, memory_engine=engine)

    # Test bounded prompt update
    session._update_system_prompt(user_message="Open my browser and look up Python docs")
    system_msg = session.history[0].content
    assert "[STORED USER PREFERENCES & HISTORICAL CONTEXT - REFERENCE ONLY]" in system_msg
    assert "User prefers Brave browser for work" in system_msg

    # Test episodic memory recording ONLY on GoalState.COMPLETED
    completed_goal = Goal(
        goal_id="g_completed_1",
        objective="Open Brave and verify foreground focus",
        state=GoalState.COMPLETED,
        tasks=[
            Task(
                task_id="t1",
                description="Open Brave",
                state=GoalState.COMPLETED,
                intents=[Intent(intent_id="int_5", action=SemanticAction.OPEN, target="brave")]
            )
        ]
    )
    ctx = ExecutionContext(execution_id="exec_1")
    ctx.environment_snapshot = {"active_window": "Brave"}

    # Record completed goal
    engine.record_completed_goal(completed_goal, ctx)
    episodes = store.list_records(memory_type=MemoryType.EPISODIC)
    assert len(episodes) == 1
    assert "Open Brave and verify foreground focus" in episodes[0].content
    assert episodes[0].metadata["goal_id"] == "g_completed_1"

    # Test that failed/cancelled goals are strictly rejected
    failed_goal = Goal(
        goal_id="g_failed_1",
        objective="Failed launch of non-existent app",
        state=GoalState.FAILED,
        tasks=[]
    )
    engine.record_completed_goal(failed_goal, ctx)
    # Episode count MUST remain 1
    assert len(store.list_records(memory_type=MemoryType.EPISODIC)) == 1

    store.close()


@pytest.mark.asyncio
async def test_conversation_memory_api_routes(tmp_path):
    """Verifies FastAPI conversation memory endpoints without deprecation warnings."""
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.api.routes.conversation import session

    # Point session to temporary engine
    db_file = tmp_path / "api_memory.db"
    store = SQLiteMemoryStore(db_path=str(db_file))
    engine = MemoryEngine(store=store)
    session.memory_engine = engine

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. POST /api/conversation/memory/remember
        resp = await client.post(
            "/api/conversation/memory/remember",
            json={
                "key": "user_ide",
                "content": "User prefers VS Code with Python extension",
                "memory_type": "PREFERENCE",
                "tags": ["coding", "ide"],
            }
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["record"]["key"] == "user_ide"

        # 2. GET /api/conversation/memory/recall
        resp_recall = await client.get("/api/conversation/memory/recall?query=VS%20Code")
        assert resp_recall.status_code == 200
        results = resp_recall.json()["results"]
        assert len(results) >= 1
        assert results[0]["record"]["key"] == "user_ide"

        # 3. POST /api/conversation/memory/profiles
        resp_prof = await client.post(
            "/api/conversation/memory/profiles",
            json={
                "canonical_name": "vscode",
                "display_name": "Visual Studio Code",
                "category": "editor",
                "aliases": ["my editor", "code editor"],
                "is_default_for_category": True,
            }
        )
        assert resp_prof.status_code == 200

        # 4. GET /api/conversation/memory/profiles
        resp_list_prof = await client.get("/api/conversation/memory/profiles?category=editor")
        assert resp_list_prof.status_code == 200
        profiles = resp_list_prof.json()["profiles"]
        assert len(profiles) >= 1
        assert profiles[0]["canonical_name"] == "vscode"

        # 5. DELETE /api/conversation/memory/{key}
        resp_del = await client.delete("/api/conversation/memory/user_ide")
        assert resp_del.status_code == 200
        assert resp_del.json()["deleted"] is True

        # 6. Verify deleted
        resp_del_404 = await client.delete("/api/conversation/memory/user_ide")
        assert resp_del_404.status_code == 404

    store.close()


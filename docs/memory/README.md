# ASTRA Memory Subsystem Architecture (Phase B.10)

This directory documents ASTRA's durable local-first memory, cross-session context injection, and context-aware intent grounding runtime.

---

## 1. Core Principles & Safeguards

1. **Local-First & Zero Paid Dependencies**:
   All memory persistence uses an embedded SQLite database (`astra_memory.db`) running in Write-Ahead Logging (`WAL`) mode with synchronous transactions. No external cloud vector database or paid embedding API is required.

2. **Data-Instruction Separation**:
   Stored memory is strictly treated as passive contextual reference data, never as executable instructions, code, or permission overrides. Context is injected under explicit boundary headers:
   ```
   [STORED USER PREFERENCES & HISTORICAL CONTEXT - REFERENCE ONLY]
   ```

3. **Strict Ephemeral State Scrubbing**:
   Ephemeral OS handles (`target_hwnd`, `hwnd`, `pid`, `thread_id`, `browser_session_id`, `active_page_id`, window focus coordinates) are never persisted in long-term memory. Schema validators purge or reject transient handles upon ingestion.

4. **Bounded Prompt Injection**:
   Context retrieved for conversation planning is strictly bounded:
   - Maximum items: `5`
   - Maximum character budget: `1,200` characters

5. **Episodic Truthfulness**:
   Episodic summaries are generated **strictly** when a goal achieves verified `GoalState.COMPLETED`. Failed, aborted, or cancelled goals are never recorded as successful episodes. Verified outcomes are cleanly distinguished from actions that were merely accepted.

---

## 2. Memory Taxonomy & Domain Contracts (`backend/app/domain/memory.py`)

### Taxonomies
- **`MemoryType`**:
  - `SHORT_TERM`: Active conversation window.
  - `WORKING`: Active task context or files.
  - `LONG_TERM`: Durable cross-session user facts.
  - `EPISODIC`: Post-completion goal summaries.
  - `SEMANTIC`: Domain knowledge and generalized facts.
  - `FACT`: Explicit user facts.
  - `PREFERENCE`: User behavioral or application preferences.
- **`ProvenanceType`**:
  - `USER_EXPLICIT`: Directly dictated by the user.
  - `USER_PREFERENCE`: Stored application preference or default.
  - `APPLICATION_PROFILE`: Known application configuration or alias mapping.
  - `EPISODIC_SUMMARY`: Synthesized from completed goal execution.
  - `INFERRED`: Derived from execution observations (low confidence).

### Primary Domain Models
- **`MemoryRecord`**: Versioned (`schema_version="1.0"`, `version=1..N`), tracking provenance, tags, audit metrics (`access_count`, `last_accessed_at`), with automatic ephemeral handle scrubbing.
- **`ApplicationProfile`**: Application alias and category defaults (supports `app_name`, `display_name`, `executable_path`, `aliases`, `category`, `is_preferred`).
- **`EpisodicGoalSummary`**: Grounded record of completed goals (`goal_id`, `objective`, `touched_applications`, `verified_outcomes`, `accepted_actions`, `duration_seconds`).
- **`MemoryQuery` & `MemorySearchResult`**: Ranked search input and scored output with score breakdowns.

---

## 3. Durable Storage Engine (`backend/app/database/memory_store.py`)

`SQLiteMemoryStore` implements:
- **Write-Ahead Logging (`WAL`)**: High concurrency, crash resilience, and ACID guarantees.
- **Schema Versioning**: Initializes table schemas with version checks (`PRAGMA user_version = 1`).
- **Corruption Recovery**: Invalid JSON payloads raise `MemoryCorruptionError` and are safely skipped or isolated without crashing the engine.
- **Relevance Scoring**: Weighted ranking combining token matching, tag affinity, recency decay, and access frequency.

---

## 4. Intent Grounding & Target Disambiguation Precedence

When compiling user requests (e.g. "open my browser", "focus it", "open chrome"), `ActionCompiler.ground_target()` enforces a strict 4-tier precedence:

1. **Tier 1 — Explicit Request Target (Precedence: 1.0)**:
   The target explicitly specified in the current request (e.g., `"open chrome"` resolves to `"chrome"` even if the user's preferred browser is `"brave"`).
2. **Tier 2 — Reliable Current-Turn Context (Precedence: 0.95)**:
   Antecedent resolution for pronouns such as `"it"` or `"the document"`, resolving from `context.last_intent.target` or `environment_snapshot.get("last_target")`.
3. **Tier 3 — Stored Application Preference or Alias (Precedence: 0.85)**:
   Resolved via `MemoryEngine.resolve_target_alias()` querying `ApplicationProfile` records (e.g. `"my browser"` -> `"brave"`, `"notes"` -> `"notepad"`).
4. **Tier 4 — Ambiguous / Unresolved Target (Precedence: 0.0)**:
   If the target has multiple plausible antecedents or cannot be determined, resolution safely returns `None`. The compiler marks the plan invalid (`FailureClass.TARGET_NOT_FOUND`) and requests clarification instead of executing an arbitrary target.

All resolved targets are strictly validated against `ApplicationCatalog` before actuation.

---

## 5. API Endpoints (`backend/app/api/routes/conversation.py`)

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/conversation/memory/remember` | Store an explicit memory record or preference |
| `GET` | `/api/conversation/memory/recall` | Search and recall ranked memories by keyword query |
| `DELETE` | `/api/conversation/memory/{key}` | Delete a memory record by key |
| `GET` | `/api/conversation/memory/profiles` | List registered application profiles |
| `POST` | `/api/conversation/memory/profiles` | Register or update an application profile |

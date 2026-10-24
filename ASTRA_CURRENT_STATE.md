# ASTRA — Current State & Immediate Actions

## Current Phase: Phase B.12 Complete (Phase B.12 CLOSED)
**Status**: CLOSED (272 backend unit tests green, live dry-run harness verified, frontend build green)

## Completed Milestones
- Phase A: World State, System Awareness, and Permission Foundation.
- Phase B.0: Universal Application Interaction.
- Phase B.1: Universal Physical Input Foundation.
- Phase B.2: Universal Visual Observation Foundation.
- Phase B.3.1: Visual Perception and Grounding Foundation.
- Phase B.3.2: Visual Target Actuation Bridge.
- Phase B.3.3: Real Windows OCR Perception Provider.
- Phase B.3.4: Live Visual Interaction Integration Validation.
- Phase B.3.5: Interactive Desktop Actuation Validation.
- Phase B.3.6: Coordinate Accuracy & Actuation Verification.
- Phase B.3.7: End-to-End Verified Visual Interaction [CLOSED].
- Phase B.4: Universal Physical Keyboard & Text Input Foundation [CLOSED].
- Phase B.5: Universal Physical Scroll, Drag & Advanced Mouse Interaction Foundation [CLOSED].
  - Mouse wheel scrolling in `MouseController.actuate_scroll` supporting vertical (`MOUSEEVENTF_WHEEL`) and horizontal (`MOUSEEVENTF_HWHEEL`) scrolling with `WHEEL_DELTA=120` and target positioning.
  - Mouse drag-and-drop in `MouseController.actuate_drag` with trajectory interpolation, micro-delays for OS gesture tracking, and guaranteed button release via `try ... finally` (including intermediate exception recovery).
  - Secondary mouse button actuation (`MouseController.actuate_right_click`) with pre-activation check, dwell time, and diagnostic telemetry.
  - Routing via `InteractionRouter` and schema support in `ExecutePhysicalInputTool` (`SCROLL`, `DRAG`, `RIGHT_CLICK`).
  - Spatial affinity matching in `VerificationEngine.verify_scroll`, eliminating cross-column false displacement (`dx=0.0px`).
  - Hardened `VerificationEngine.verify_drag` supporting 3 distinct modalities (window title bar drag, OS clipboard copy, UI element relocation).
  - Formal `VerificationEngine.verify_context_menu` with ROI spatial bounding and authoritative phrase detection.
  - Regression suite: 24 unit tests in `tests/unit/test_scroll_drag.py` (100% green).
- Phase B.6: Complex Interaction Sequences & Multi-Step Composite Action Orchestration Foundation [CLOSED].
  - Formal composite action sequence domain models in `app/domain/composite.py` (`CompositeStep`, `CompositeActionSequence`, `CompositeExecutionResult`, `StepStatus`, `CompositeTerminalStatus`, `CompensationAction`).
  - Multi-step action sequencing in `ActionExecutor.execute_sequence` preserving the `observe -> act -> observe -> verify -> recover` loop per step.
  - Decouples accepted physical actuation from verified semantic success.
  - Authorization gates for consequential actions, bounded recovery, safe verified compensation, cancellation, and timeout handling.
  - Live interactive execution verified (`tests/live/test_live_composite_workflow.py --execute`): 5/5 steps completed, Terminal Status: `SUCCESS`.
- Phase B.7: Multi-Window & Cross-Application Composite Workflow Orchestration [CLOSED].
  - Multi-window domain models in `app/domain/composite.py` (`target_window_title`, `target_app_name`, `target_hwnd`, `ensure_foreground`).
  - Cross-window focus activation in `WindowManager.restore_and_focus`:
    - Checks foreground window first (`if fg_hwnd == hwnd: return True`), preventing intrusive Alt pulsing on sequential steps within the same window.
    - Synchronously attaches calling thread to both foreground and target threads via `AttachThreadInput` to defeat OS foreground locks cleanly.
    - If fallback Alt pulse is triggered, immediately follows with `VK_ESCAPE` events to cancel menu bar activation (`SC_KEYMENU`).
  - UWP application window resolution in `WindowManager.get_windows_for_pids`:
    - Handles `ApplicationFrameWindow` decoupling in Windows 10/11 by enumerating child windows (`Windows.UI.Core.CoreWindow`) to match UWP processes (`CalculatorApp.exe`).
    - Prioritizes visible rendering surfaces (`width > 0, height > 0`) over 0x0 IME windows.
  - Multi-window sequence execution in `ActionExecutor.execute_sequence`:
    - Authoritative cross-process window restoration and foreground activation per step.
    - Dynamic window bounding box re-scoping (`target_bounds`) across steps for visual OCR perception.
    - Immediate clipboard capture for `HOTKEY ["ctrl", "c"]` steps, stored in `step.verifier_args["clipboard_text"]`.
    - First-class `CLIPBOARD` verifier (`VerificationEngine.verify_clipboard`) enabling authoritative verification of clipboard buffer payload.
    - Explicit `verified_steps` tracking in `CompositeExecutionResult` alongside `completed_steps`, formally decoupling authoritative semantic verification (`TriState.TRUE`) from contract fulfillment of unverified modifier/navigation steps (`ACTUATION_ACCEPTED`).
    - Explicit `ACTUATION_ONLY` verification classification for steps with `requires_verification=False`, eliminating ambiguous `UNKNOWN` logs while preserving truthfulness.
    - Bypasses expensive visual capture and OCR for non-visual verifiers (`WINDOW_FOCUS`, `CLIPBOARD`), accelerating sequence cycle time.
  - Authoritative verification in `VerificationEngine`:
    - `verify_window_focus`: Validates HWND, window title, or application name including UWP `ApplicationFrameHost` child window checks.
    - `verify_clipboard`: Authoritatively validates Windows OS clipboard buffer against expected string tokens.
    - `verify_cross_window_sync`: Verifies payload transfer across applications using live OS clipboard and verified step history fallback, with precise evidence recording payload survival across application boundaries in shared clipboard buffer without overclaiming recipient UI consumption.
  - Live execution verified back-to-back on real interactive desktop (`tests/live/test_live_multi_window_composite.py --execute`):
    - Terminal Status: `SUCCESS`
    - Completed Steps: `7/7`
    - Step 0 [step_0_focus_notepad]: `VERIFIED_SUCCESS` (HWND resolved)
    - Step 1 [step_1_type_payload]: `VERIFIED_SUCCESS` (Text Present verified via OCR)
    - Step 2 [step_2_select_all]: `ACTUATION_ACCEPTED` (Select all has no discrete visual delta; contract fulfilled via accepted actuation)
    - Step 3 [step_3_copy_clipboard]: `VERIFIED_SUCCESS` (Authoritative clipboard buffer payload verified via `CLIPBOARD` verifier)
    - Step 4 [step_4_switch_to_calc]: `VERIFIED_SUCCESS` (Calculator brought to foreground)
    - Step 5 [step_5_verify_cross_window]: `VERIFIED_SUCCESS` (Payload confirmed across application boundary in shared OS buffer)
    - Step 6 [step_6_cleanup_notepad]: `VERIFIED_SUCCESS` (Text Absent verified via OCR)
    - Stage 5 Teardown: Cleanly closed Calculator and Notepad.
    - Contract Result: **`ASTRA - PHASE B.7: RESULT PASS`**
  - Full automated regression suite: 203 passed in 74.65s (100% green across all unit tests).
  - **Live Workflow Note**: Phase B.7's updated clipboard-verification logic passed its automated unit tests, but its live interactive desktop workflow has not yet been rerun after those changes. Fresh live validation is not claimed.
  - **Audit Findings & Architectural Clarifications**:
    1. Composite Terminal Status Semantics: A sequence reports `CompositeTerminalStatus.SUCCESS` when all steps fulfill their contract (`completed_steps == total_steps`). Steps with `requires_verification=True` MUST achieve `VERIFIED_SUCCESS` (`TriState.TRUE`). Steps with `requires_verification=False` complete as `ACTUATION_ACCEPTED` (`ACTUATION_ONLY` verification result).
    2. Decoupling Metrics: `CompositeExecutionResult.completed_steps` reflects total contract fulfillment, while `verified_steps` reflects steps with authoritative semantic proof.
    3. Cross-Window Evidence Grounding: Step 5 proves focus integrity and clipboard persistence across process boundaries; it does not claim recipient UI ingestion where destination did not paste.
  - **Limitations & Boundaries**:
    1. Mechanical Sequencing: Validates low-level multi-window coordination, focus transfer, and cross-application state sync; does not bridge unconstrained natural language goal planning.
    2. Fixed Test Application Pair: Exercised with classic Win32/XAML (Notepad) and modern UWP (`ApplicationFrameHost` Calculator). Other specialized frameworks (Electron, Qt, Java) may require customized process hierarchy traversal.
- Phase B.8: High-Level Natural Language Goal Compilation & Adaptive Execution Runtime [CLOSED].
  - **Plan Validation Layer in `ActionCompiler.validate_plan`**:
    - Created `PlanValidationResult` (`is_valid`, `errors`, `warnings`, `failure_class`) and added `validation_errors` tracking to `Goal`.
    - Validates schema structure, non-empty goals/tasks, supported semantic actions, target application existence against `ApplicationCatalog` and standard Windows utilities (Notepad, Calculator, Explorer, CMD, PowerShell), and required action parameters (`TYPE_TEXT` requires `text`, `HOTKEY` requires `keys`, `NAVIGATE` requires `url`, `DRAG` requires `source` and `destination`).
    - Strictly preserves architectural separation between untrusted model planning and trusted execution: raw model output is validated and authorization-gated before compilation or actuation.
  - **Natural Language Goal to Composite Sequence Compiler (`ActionCompiler.compile_goal_to_composite_sequence`)**:
    - Translates validated high-level task plans into verified `CompositeActionSequence`.
    - Injects target application scoping (`target_app_name`, `ensure_foreground=True`) to maintain cross-window focus integrity.
    - Injects authoritative verifiers (`WINDOW_FOCUS`, `TEXT_INPUT`, `CLIPBOARD`, `CROSS_WINDOW_SYNC`, `SCROLL`, `DRAG`, `CONTEXT_MENU`).
    - Injects safe verified compensations (`Ctrl+Z` undo for text input, `Escape` for menus).
  - **Adaptive Dynamic Re-Planning in `GoalRuntime._execute_task`**:
    - Fast-fails unvalidated plans immediately with `GoalState.FAILED` and `ExecutionEventType.GOAL_FAILED` (`state="VALIDATION_FAILED"`), preventing unvalidated model output from reaching OS actuators.
    - On step verification failure (`PARTIAL_FAILURE` or `FAILED`), queries `RecoveryEngine.determine_strategy(failure_class)`.
    - Slices remaining uncompleted steps into a replanned remainder sequence via `ActionCompiler.replan_remainder_sequence`.
    - Injects pre-flight window refocusing and settle stabilization steps for `INSPECT_STATE` / `REFRESH_OBSERVATION` strategies.
    - Bounded re-planning (`max_replans = 2`), recording all attempts in `context.recovery_history` and cleanly aborting on persistent or unrecoverable failures.
    - Strictly enforces cancellation (`cancel_event`) and explicit terminal states (`SUCCESS`, `PARTIAL_FAILURE`, `FAILED`, `CANCELLED`, `TIMEOUT`).
  - **Deterministic Regression Suite (`tests/unit/test_goal_compilation_and_runtime.py`)**:
    - 10 comprehensive unit tests covering empty goals, unsupported apps, missing parameters, sequence compilation, fast-fail on validation error, successful multi-step execution, dynamic re-planning on failure, unrecoverable aborts, cancellation, and synchronous chat event text accumulation.
    - Result: 10 / 10 passed (100% green).
  - **Full Automated Regression Suite**:
    - `pytest tests/unit/`: 213 passed in 53.32s (100% green across entire unit suite).
  - **Request-Path Audit & Readiness Assessment (Phase B.8 Post-Implementation)**:
    - *Streaming Chat Path*: Confirmed end-to-end connection from `ChatPanel.tsx` (`voiceClient.streamMessage`) -> FastAPI `/api/conversation/message/stream` -> `session.chat_stream` -> `compiler.compile` -> `GoalRuntime.run` -> `action_executor.execute_sequence` -> `VerificationEngine` -> SSE rendering.
    - *Resolution of Synchronous Voice Path Gap*: `session.chat()` previously discarded JSON SSE event chunks, returning `""` to `POST /api/conversation/message`. Fixed to accumulate text from `ASSISTANT_RESPONSE` event payloads, verified by `test_conversation_session_chat_accumulates_assistant_response_events`.
    - *Frontend Cancellation Handling*: Added `GOAL_CANCELLED` event handling and UI badge rendering in `ChatPanel.tsx`.
    - *User-Facing Cancellation Endpoint*: Added `POST /api/conversation/cancel` endpoint backed by `ConversationSession.cancel()`, which propagates cancellation to `GoalRuntime.cancel()` via `cancel_event`. Added `VoiceClient.cancelExecution()` to frontend API service. Verified by `test_conversation_session_cancellation_and_api_endpoint`.
    - *Security / Permission Gating*: Plans with malformed/unsupported applications or missing parameters fast-fail in `compiler.validate_plan` and `GoalRuntime.run` with zero actuator invocation. Multi-step sequences enforce dynamic `PermissionEvaluator` evaluation.
  - **Canonical Live NL Goal Compilation & Execution Harness (`tests/live/test_live_goal_compilation_and_execution.py`)**:
    - Created canonical live validation script exercising natural-language goal decomposition, `ActionCompiler.validate_plan`, `ActionCompiler.compile_goal_to_composite_sequence`, `GoalRuntime.run()`, target application scoping, and independent postcondition verification.
    - Safety safeguards: requires `--execute` flag, defaults to dry-run mode (exit 0).
    - Dry-run verification: PASSED (exit code 0).
    - **Provider Query Limitation & Ground Truth Provenance**:
      * In Stage 1, the test harness queried `get_default_provider()`, reporting: `Provider Query: BYPASS / LIMITATION (ProviderManager unavailable: All AI providers are currently unavailable or in cooldown)`.
      * Due to lack of active external API keys or local LLM server in the test execution environment, the harness used a deterministic canonical decomposition of the natural language prompt into a structured `Goal(tasks=[...])` rather than zero-shot formulation by an external model.
      * **Empirically Proven by Live Test**: Authoritative plan validation (`compiler.validate_plan`), composite sequence compilation (`compiler.compile_goal_to_composite_sequence`), stateful runtime lifecycle (`GoalRuntime.run()`), physical OS actuation via Win32 `SendInput`, real-time visual OCR perception verification (`Windows.Media.Ocr`), Win32 clipboard verification, document cleanup, and terminal-state agreement.
      * **Explicitly Unverified**: Arbitrary zero-shot natural-language-to-plan generation by a live LLM without structured decomposition.
    - **Live Execution (`--execute`) on Active Desktop**: **PASSED** (confirmed twice consecutively with fresh tokens `gerkkb` and `curwdk`):
      * Duration: ~35.5s
      * [PC 1] Notepad Instance Active: PASSED
      * [PC 2] Text Entered & Verified: PASSED (via OCR within client document bounds)
      * [PC 3] OS Clipboard Content Verified: PASSED (payload matching unique token)
      * [PC 4] Document Cleared & Verified: PASSED (TEXT_ABSENT verified)
      * [PC 5] Goal Terminal State Agreement: PASSED (`GoalState.COMPLETED`)
      * [PC 6] Teardown Restored Clean State: PASSED
      * Terminal Banner: `ASTRA - PHASE B.8: RESULT PASS` (exit code 0).
  - **Phase B.7 Multi-Window Workflow Live Re-Validation (`tests/live/test_live_multi_window_composite.py --execute`)**:
    - **Live Execution (`--execute`) on Active Desktop**: **PASSED** (Duration: 17.36s, exit code 0).
    - Step 0 Focus Notepad (`WINDOW_FOCUS`): `VERIFIED_SUCCESS` (TRUE, HWND confirmed).
    - Step 1 Type Payload (`TEXT_INPUT`): `VERIFIED_SUCCESS` (TRUE).
    - Step 2 Select All: `ACTUATION_ACCEPTED` (NOT_REQUIRED).
    - Step 3 Copy Clipboard (`CLIPBOARD`): `VERIFIED_SUCCESS` (TRUE).
    - Step 4 Switch to Calc (`WINDOW_FOCUS`): `VERIFIED_SUCCESS` (TRUE, HWND confirmed).
    - Step 5 Verify Cross-Window (`CROSS_WINDOW_SYNC`): `VERIFIED_SUCCESS` (TRUE).
    - Step 6 Cleanup Notepad (`TEXT_ABSENT`): `VERIFIED_SUCCESS` (TRUE).
    - Terminal Banner: `ASTRA - PHASE B.7: RESULT PASS` (exit code 0).
  - **Full Automated Unit Regression Suite**:
    - `pytest tests/unit/`: **214 passed** in 66.16s (100% green, 0 failures, 0 warnings across all 22 unit test suites).

- Phase B.9: Long-Running Goal Persistence, Checkpointing & Resumption Runtime [CLOSED].
  - **Versioned Checkpoint Contracts (`app/domain/checkpoints.py`)**:
    - Created explicit `GoalCheckpoint` and `TaskCheckpoint` domain contracts (`SCHEMA_VERSION = "1.0"`).
    - Tracks stable goal/task identifiers, lifecycle state (`GoalState`, `TaskState`), completed and verified step indices (`completed_step_indices`, `verified_step_indices`), authoritative verification evidence, environment snapshots, recovery history, suspension reasons, and resumption eligibility (`is_resumable: bool`).
    - Introduced `ResumptionClassification` (`VERIFIED_AND_SAFE`, `REQUIRES_REVERIFICATION`, `SAFE_TO_RETRY`, `REQUIRES_REPLANNING`, `REQUIRES_USER_INTERVENTION`, `UNSAFE_TO_RESUME`).
    - Enforced strict invariants in `validate_resumable()`: rejects incompatible schema versions, completed or cancelled goals, non-resumable flags, and out-of-bounds task pointers.
    - Decoupled durable state from unsafe ephemeral OS handles, live HWNDs, and provider connections.
  - **Local-First Durable Persistence (`app/database/goal_store.py`)**:
    - Implemented `SQLiteGoalStore` with Write-Ahead Logging (`WAL` mode) and synchronous transactions for crash resilience and thread-safety.
    - Atomic upserts on conflict (`ON CONFLICT(goal_id) DO UPDATE`), preventing ambiguous or duplicate execution histories.
    - Error handling with structured exceptions (`CheckpointError`, `CheckpointCorruptionError`, `CheckpointNotFoundError`).
    - Safe corruption detection: corrupted JSON records are safely identified and rejected without crashing the store or backend service.
    - Checkpoint lifecycle operations: `save_checkpoint`, `get_checkpoint`, `list_resumable_goals`, `mark_non_resumable`, `delete_checkpoint`.
  - **Runtime Lifecycle Integration (`app/ai/orchestrator/runtime.py`)**:
    - Checkpoints created and persisted at canonical boundaries: goal acceptance, task start, verified task completion, waiting/suspension states (`WAITING_FOR_USER`), recovery decisions, cancellation, and terminal completion/failure.
    - Truthful progress tracking: distinguishes accepted OS actuation (`ACTUATION_ACCEPTED`) from authoritative verified outcomes (`VERIFIED_SUCCESS`).
    - Concurrency-safe cancellation: `cancel()` persists `GoalState.CANCELLED` with `is_resumable=False`, preventing cancelled goals from being re-opened.
  - **Interruption, Suspension & Truthful Resumption**:
    - Reconstructed `GoalRuntime.resume(checkpoint, goal_store, context)`:
      - Validates checkpoint compatibility and resumption eligibility.
      - Strips ephemeral OS HWNDs, target PIDs, and stale browser session IDs before context initialization.
      - Skips already completed and verified tasks (`TaskState.COMPLETED`).
      - Dynamically slices composite remainder sequences to begin strictly at `last_verified_step + 1`, eliminating duplicate execution of completed steps.
      - Re-evaluates uncertain actions: unverified interrupted actions trigger `REQUIRES_REVERIFICATION`.
  - **Safe Rollback Semantics (`GoalRuntime.abort_and_rollback`)**:
    - Formally distinguishes database state restoration from external physical world effects.
    - Executes known compensations only for explicitly reversible steps (e.g. `Ctrl+Z` for typed text); irreversible actions are recorded truthfully as `unresolved_steps`.
    - Persists terminal `GoalState.FAILED` and permanently marks checkpoint as non-resumable.
  - **API & Session Integration**:
    - Added `GET /api/conversation/goals/resumable` to list resumable checkpoints.
    - Added `POST /api/conversation/goals/{goal_id}/resume` streaming execution events via `session.resume_goal_stream(goal_id)`.
    - Enforces active runtime conflict guards (rejects concurrent duplicate executions with 409 Conflict).
    - Added `listResumableGoals()` and `resumeGoal(goalId, onEvent)` to frontend `VoiceClient`.
  - **Automated Regression Suite (`tests/unit/test_goal_persistence_and_resumption.py`)**:
    - 13 comprehensive unit tests covering checkpoint serialization, schema versioning, terminal-state rejection, store CRUD, crash recovery, corruption detection, runtime lifecycle persistence, selective resumption, ephemeral handle scrubbing, compensation rollback, and session streaming integration.
    - Result: 13 / 13 passed (100% green).
  - **Full Automated Unit Regression Suite**:
    - `pytest tests/unit/`: **227 passed** (100% green across all 23 unit test suites).

- Phase B.10: Cross-Session Long-Term Context, Dynamic Memory & Intent Grounding Runtime [CLOSED].
  - **Memory Domain Contracts (`app/domain/memory.py`)**:
    - Created validated, serializable domain contracts: `MemoryRecord`, `ApplicationProfile`, `EpisodicGoalSummary`, `MemoryQuery`, `MemorySearchResult` with `SCHEMA_VERSION = "1.0"`.
    - Typed taxonomies: `MemoryType` (`SHORT_TERM`, `WORKING`, `LONG_TERM`, `EPISODIC`, `SEMANTIC`, `FACT`, `PREFERENCE`) and `ProvenanceType` (`USER_EXPLICIT`, `USER_PREFERENCE`, `APPLICATION_PROFILE`, `EPISODIC_SUMMARY`, `INFERRED`).
    - Ephemeral OS state scrubbing: `MemoryRecord` model validator strips transient execution context (`target_hwnd`, `hwnd`, `pid`, `thread_id`, `browser_session_id`, `active_page_id`).
    - Provenance, versioning, and access metrics: each record tracks provenance, integer revision `version`, `access_count`, and `last_accessed_at`.
    - Profile and summary parity: `ApplicationProfile` supports both `display_name` and `app_name`, and `is_default_for_category` / `is_preferred`; `EpisodicGoalSummary` supports `applications_involved` alias for `touched_applications`.
  - **Durable Local SQLite Persistence (`app/database/memory_store.py`)**:
    - Implemented `SQLiteMemoryStore` (`astra_memory.db`) with Write-Ahead Logging (`WAL` mode) and synchronous transactions for crash resilience and thread-safety.
    - Zero external cloud/paid embedding dependencies: local deterministic updates, schema versioning, and corruption isolation via `MemoryCorruptionError`.
    - Token and tag relevance ranking: scores records by keyword matches across content and tags, weighted by recency and access frequency.
    - CRUD operations: `save_record`, `get_record`, `delete_record`, `list_records`, `search_records`, `save_profile`, `get_profile`, `find_profile_by_alias`, `list_profiles`, `save_episodic_summary`, `list_episodic_summaries`.
  - **Memory Engine (`app/memory/engine.py`)**:
    - Implemented `MemoryEngine` coordinating storage, recall, application profile management, and episodic goal recording.
    - Target alias resolution via `resolve_target_alias()` returning `TargetResolution(canonical_name, confidence, reason)` (NamedTuple supporting both attribute access and tuple unpacking).
    - Strictly bounded prompt context retrieval (`get_relevant_context()`): enforces `max_items=5` and `max_chars=1200`, formatting data under explicit non-instructional boundaries (`[STORED USER PREFERENCES & HISTORICAL CONTEXT - REFERENCE ONLY]`).
  - **Cross-Session Context Integration (`app/ai/orchestrator/session.py`)**:
    - Integrated memory retrieval into `ConversationSession._update_system_prompt()`, ensuring stored memories remain subordinate data rather than executable instructions.
    - Truthful episodic recording: records goal summaries in `chat_stream` and `resume_goal_stream` strictly when `goal_state == "COMPLETED"`; failed, cancelled, or aborted goals are never recorded into episodic memory.
  - **Context-Aware Intent Grounding (`app/ai/orchestrator/compiler.py` & `app/ai/context/engine.py`)**:
    - Implemented `ActionCompiler.ground_target()` enforcing strict 4-tier precedence:
      1. Explicit target specified in current request (e.g. "open chrome" overrides stored preference for Brave).
      2. Reliable current-turn context (e.g. antecedent resolution for "it" or "the document" from `last_intent.target` or `environment_snapshot`).
      3. Relevant stored application preference or alias (e.g. "my browser" -> Brave).
      4. Ambiguous target resolution failure (safe rejection without guessing or arbitrary execution).
    - Integrated with `ActionCompiler.validate_plan()`, resolving targets for application lifecycle intents (`OPEN`, `FOCUS`, `CLOSE`) while enforcing `ApplicationCatalog` validation and runtime safety checks.
    - Connected `ContextEngine.resolve_reference()` to consult `MemoryEngine.resolve_target_alias()`.
  - **REST API Endpoints (`app/api/routes/conversation.py`)**:
    - Added `POST /api/conversation/memory/remember`, `GET /api/conversation/memory/recall`, `DELETE /api/conversation/memory/{key}`, `GET /api/conversation/memory/profiles`, `POST /api/conversation/memory/profiles`.
  - **Automated Regression Suite (`tests/unit/test_memory_and_intent_grounding.py`)**:
    - 10 comprehensive unit tests covering domain serialization, ephemeral handle scrubbing, SQLite WAL CRUD, token relevance ranking, application profiles, context bounding, 4-tier precedence, session bounded injection, episodic recording on COMPLETED only, and async HTTP API routes.
    - Result: 10 / 10 passed (100% green).
  - **Full Automated Unit Regression Suite (Phase B.10 Baseline)**:
    - `pytest tests/unit/`: **237 passed** in 46.12s (100% green across all 24 unit test suites, 0 failures, 0 warnings).
- Phase B.11: Proactive Multi-Turn Desktop Task Assistance & User Interaction Clarification Runtime [CLOSED].
  - **Structured Clarification Domain Contracts (`app/domain/clarification.py`)**:
    - Created `ClarificationType` enum (`AMBIGUOUS_TARGET`, `MISSING_PARAMETER`, `CONSEQUENTIAL_ACTION`, `HUMAN_INTERVENTION`).
    - Created `ClarificationOption` model (`option_id`, `label`, `value`, `description`, `is_recommended`).
    - Created `ClarificationRequest` model (`request_id`, `clarification_type`, `prompt`, `options`, `default_option_id`, `goal_id`, `task_id`, `step_index`, `action_type`, `target_name`, `impact_description`, `requires_explicit_confirmation`, `timeout_seconds`, `is_expired()`, `get_option()`).
    - Created `ClarificationResponse` model (`request_id`, `selected_option_id`, `custom_input`, `confirmed`, `remember_as_preference`, `validate_against()`).
    - Re-exported in `app/domain/__init__.py`.
  - **Event Types & Checkpoint Persistence**:
    - Added `CLARIFICATION_REQUIRED`, `CONFIRMATION_REQUIRED`, `CLARIFICATION_RESOLVED` to `ExecutionEventType`.
    - Added `pending_clarification: Optional[ClarificationRequest]` to `ExecutionContext`, `Goal`, and `GoalCheckpoint`.
    - Preserved durable persistence across process restarts in `SQLiteGoalStore`.
  - **Deterministic Consequential-Action Policy (`app/core/security/consequential.py`)**:
    - Created `ConsequentialActionPolicy` detecting destructive operations (e.g., `Remove-Item`, `del /f`, `rmdir /s /q`, `taskkill /f`, `format`) and force-kill intents.
    - Implemented pre-actuation gate: generates structured confirmation request and suspends execution prior to dispatch.
    - Integrated with `PermissionEvaluator`: explicit approval grants strictly scoped permission for the specific action and target for a bounded duration (300s); rejection immediately cancels goal with zero destructive actuation.
  - **Grounded Disambiguation in ActionCompiler (`app/ai/orchestrator/compiler.py`)**:
    - Implemented `find_clarification_candidates()` querying `ApplicationCatalog`, application profiles, and active windows. Candidates are never hallucinated.
    - Intercepts target ambiguity in `validate_plan()`: attaches structured `ClarificationRequest` to `PlanValidationResult`.
    - When ambiguity is present, `compile()` transitions goal to `GoalState.WAITING_FOR_USER` without hard-failing.
  - **Action Executor Interception (`app/ai/orchestrator/action_executor.py`)**:
    - Evaluates permission on consequential steps before physical actuation; on unapproved actions, pauses and attaches confirmation request to step failure diagnostics.
  - **Multi-Turn Interaction Routing (`app/ai/orchestrator/session.py`)**:
    - Implemented `_match_pending_clarification()`: parses option indices ("1"), option labels/values ("Notepad"), or explicit confirmation affirmations ("yes", "confirm", "proceed" vs "no", "cancel", "abort"). Unrelated "yes" never resolves ambiguous target requests.
    - Implemented `resolve_clarification_stream()`: resumes goal stream, updates task target, binds scoped permissions, or safely cancels on rejection.
    - Unrelated new instructions safely supersede suspended goals without corrupting checkpoints.
  - **REST API & Frontend Integration**:
    - Added `POST /api/conversation/clarify` and `POST /api/conversation/confirm` endpoints.
    - Updated `frontend/src/services/api/voiceClient.ts` with `clarifyTarget()` and `confirmAction()`.
    - Updated `frontend/src/components/chat/ChatPanel.tsx` and `ChatPanel.css`: renders interactive candidate option chips and approve/cancel confirmation dialogs; tested `npm run build` cleanly.
  - **Deterministic Regression & Live Verification Suite**:
    - 11 new comprehensive unit tests in `tests/unit/test_clarification_and_confirmation.py` (100% green).
    - Full regression suite: **248 passed in 57.94s** (100% green across all 25 unit test suites, 0 failures).
    - Live verification harness (`scratch/live_verification_b11.py`): verified ambiguous target disambiguation, catalog grounding, goal resumption with target binding, consequential action detection, rejection cancellation with zero actuation, scoped permission grant, and duplicate/replay rejection.

- Phase B.12: Multimodal Visual Grounding & Real-Time Context Fusion Runtime [CLOSED].
  - **Stage 1 — Observation Contracts and Coordinate Correctness (`app/domain/observation.py`)**:
    - Created explicit coordinate domain enum: `CoordinateSpace` (`IMAGE_LOCAL`, `WINDOW_RELATIVE`, `VIRTUAL_SCREEN`, `DPI_LOGICAL`).
    - Implemented mathematical coordinate conversions: `image_to_virtual_screen`, `virtual_screen_to_image`, `virtual_screen_to_window`, `window_to_virtual_screen`, and `transform_bbox` without silent clamping (strict `CoordinateTransformError` on invalid bounds).
    - Defined validated models: `BoundingBox`, `AudioUtteranceContext`, `PerceptualDiffResult`, `TrackedTarget`, `MultimodalObservation`.
    - Multi-monitor coordinate fix in `TargetSelectionService` (`app/environment/visual/selection.py`): added `virtual_offset: Tuple[int, int]` parameter to correctly evaluate window bounds against candidates on multi-monitor setups and negative origins (`SM_XVIRTUALSCREEN < 0`).
    - Captured virtual-desktop fidelity in `ScreenCaptureProvider` (`app/environment/visual/capture.py`): reinforced DXcam WinRT capture with native Win32 GDI BitBlt fallback when display topologies exceed single-monitor boundaries or when DXcam fails.
  - **Stage 2 — Perceptual Change Detection & Observation Scheduling (`app/environment/visual/diff.py`, `app/environment/visual/observer.py`)**:
    - Created `PerceptualDiffEngine`: downscaled grayscale frame differencing (<2ms per 1080p frame) with configurable change ratio threshold (0.5%), noise tolerance filtering, damage region bounding box calculation, and perceptual SHA256 digest hashing.
    - Created `DesktopObserver`: conservative observation scheduler with adaptive throttling (2 Hz active, 0.67 Hz idle), bounded snapshot history (ring buffer), and deterministic worker start/stop lifecycle.
    - Zero redundant OCR: static desktop frames completely bypass OCR inference (`ocr_suppressed = True`), verified with live and synthetic benchmarks.
    - Preserved forced-refresh bypass for safety-critical target verification.
  - **Stage 3 — Spatial Tracking and Pre-Actuation Re-Grounding (`app/environment/visual/tracking.py`)**:
    - Created `SpatialTargetTracker`: tracks targets across consecutive observations using centroid Euclidean drift, bounding box IoU, and label similarity.
    - Targets do not retain authority merely because previous representations exist in memory.
    - Integrated pre-actuation re-grounding into `VisualInteractionService.execute_click`: validates target presence and drift before physical dispatch. Rejecting actuation on disappeared targets (`TARGET_DISAPPEARED`), excessive movement (`TARGET_MOVED`), or occlusion (`TARGET_OCCLUDED`).
    - Integrated observer actuation pause: background worker pauses during physical input injection and settle intervals (0.3s).
  - **Stage 4 — UI Automation and Multimodal Context Fusion (`app/ai/context/fusion.py`)**:
    - Created `MultimodalContextFusion`: deterministic cross-modal alignment between OCR text candidates and UIAutomation element trees (`ObservationEngine`).
    - Enriches OCR targets with interactive control classification, automation IDs, supported patterns, enabled/disabled state, and modality provenance (`["OCR", "UIA"]` vs `["OCR"]`).
    - Resolves contradictory evidence deterministically (flags disabled controls and text divergences) without delegating conflict resolution to raw model inference.
    - Generates deterministic spatial layout digest.
  - **Stage 5 — Speech and Observation Temporal Alignment**:
    - Updated `/voice/transcribe` endpoint in `app/api/routes/voice.py` to accept `client_timestamp_ms`, `utterance_id`, and `clock_domain`.
    - Aligns speech utterances to desktop observation snapshots from the exact time of speech via `context_fusion.align_utterance_to_observation` with clock-skew tolerance bounding.
    - Historical observations ground intent, while pre-actuation re-grounding validates target presence before physical actuation.
  - **Stage 6 & 7 — Observer Safety, Concurrency, and Test Suites**:
    - Dedicated test suites covering visual perception, observer, tracking, and voice alignment:
      - `tests/unit/test_visual_observation_stage1.py`: 8 passed.
      - `tests/unit/test_visual_diff_and_observer.py`: 9 passed (including `test_observer_actuation_scope_mutual_exclusion`).
      - `tests/unit/test_visual_tracking_and_regrounding.py`: 9 passed (including moved, occluded, fail-closed re-grounding).
      - `tests/unit/test_multimodal_context_fusion.py`: 4 passed.
      - `tests/unit/test_voice_temporal_alignment.py`: 6 passed (utterance association, skew rejection, delayed STT, session isolation).
    - Full backend regression suite: **284 passed** in 59.10s (100% green across all 29 test files, 0 failures, 1 deprecation warning).
    - Frontend production build: `npm run build` completed cleanly in 299ms.
    - Live desktop harness (`tests/live/test_live_multimodal_grounding.py`): verified live screen capture (12.51ms), consecutive frame diffing (1.44ms), zero redundant OCR suppression (100% on static frames), native WinRT OCR (411 live text elements), foreground window awareness, target tracking (0.00px stationary drift, 999px displacement detection), controlled Notepad Win32 `MoveWindow` relocation, and safe dry-run default.
  - **B.12 Post-Audit Remediation Results (Closed October 24, 2026)**:
    - *Defect 1 (Mandatory Pre-Actuation Re-Grounding)*: Enforced `recheck_pre_actuation=True` across `VisualInteractionService.execute_click`, `ExecuteVisualInteractionTool`, and `ActionExecutor`. Fresh observation is captured immediately before physical input; stale, moved, or occluded targets reject actuation without physical input.
    - *Defect 2 (DesktopObserver Mutual Exclusion)*: Implemented reentrant `_cycle_lock` and `actuation_scope(settle_s=0.15)` context manager. In-flight observation cycles finish before physical input starts, background cycles are excluded during actuation, and safe settling occurs before resuming.
    - *Defect 4 (Speech-to-Observation Temporal Alignment)*: Frontend records audio recording start and duration via `MicrophoneService`. Backend `/api/voice/transcribe` validates clock skew (`-5s <= skew <= 300s`), falls back to duration-based onset if needed, marks uncertain mappings as `clock_reliable = False`, aligns utterance with observation history, and returns `aligned_observation_id`. Forwarded to `ExecutionContext` in `ConversationSession`, explicitly clearing on unaligned turns to prevent cross-turn/cross-session context leakage.

## Current Phase: Phase B.12 Remediation & Live Acceptance Audit Complete
**Status**: B.12 IMPLEMENTATION COMPLETE, LIVE ACCEPTANCE BLOCKED (295 backend unit tests green, safety invariant proven across all 7 conditions, frontend build green, live relocation acceptance blocked by Windows foreground lockout)

## B.12 Remediation & Final Verdict Summary (October 24, 2026)
- **Verdict**: **BLOCKED (Implementation Complete, Live Acceptance Blocked by Environmental Occlusion)**
- **Safety Invariant**: Formally proven in `backend/tests/unit/test_visual_dispatch_safety_invariant.py`:
  `NO FRESH VALID TARGET -> NO PHYSICAL INPUT DISPATCH`
  - Stable target: Permitted to dispatch with verified updated coordinates (1 dispatch).
  - Moved target: Rejected before actuation (`TARGET_MOVED`), 0 physical dispatches.
  - Disappeared target: Rejected before actuation (`TARGET_DISAPPEARED`), 0 physical dispatches.
  - Occluded target: Rejected before actuation (`TARGET_OCCLUDED`), 0 physical dispatches.
  - Ambiguous target: Rejected before actuation (`TARGET_AMBIGUOUS`), 0 physical dispatches.
  - Stale / failed observation: Rejected before actuation (`OBSERVATION_STALE`), 0 physical dispatches.
  - Observation timeout / exception: Rejected before actuation (`PRE_ACTUATION_FAILED`), 0 physical dispatches.
  - End-to-end tool boundary: Verified OS `MouseController.actuate_click` is never reached on target failure.
- **Production Call Paths Audited & Verified**:
  - Visual target selection & coordinate grounding: Verified in `TargetSelectionService` and `TargetGroundingService`.
  - Mandatory pre-actuation re-grounding: Verified in `VisualInteractionService.execute_click` with `recheck_pre_actuation=True` enforced across all tools and executor paths.
  - Fresh observation acquisition: Verified in `ScreenCaptureProvider` (DXcam WinRT virtual screen capture).
  - Target movement, disappearance, occlusion, ambiguity, and stale observations: Structured error translation to `FailureClass` (`STALE_TARGET`, `TARGET_NOT_FOUND`).
  - Final physical input dispatch: Enclosed within `with desktop_observer.actuation_scope(settle_s=0.15):` in `InteractionRouter`.
  - DesktopObserver synchronization: Reentrant `_cycle_lock`, `_actuation_in_progress`, and `_pause_until` eliminate background capture/actuation races.
  - Runtime multimodal fusion: `DesktopObserver._observe_cycle` captures visual frame, diffs, discovers active window UIA element tree via `ui_engine`, and fuses via `context_fusion.fuse_observation`.
  - Fused observation delivery to execution consumer: `ConversationSession._update_system_prompt` injects active window title, PID, and visible text elements from latest/aligned multimodal observation.
  - Audio-to-observation temporal alignment: Utterance start timestamp validated against client clock skew (`-5s <= skew <= 300s`), aligned with observation history, and forwarded to `ExecutionContext.aligned_observation_id`, cleared on unaligned turns to prevent leakage.
- **Defects Remediated During Final Verification**:
  - *Defect 1 (Desktop Attachment Destruction in MouseController)*: Fixed `MouseController._ensure_active_desktop` where `self.user32.CloseDesktop(h_input)` was called immediately after `SetThreadDesktop(h_input)`, destroying the desktop assignment and causing `SendInput` to fail with `ERROR_ACCESS_DENIED (5)`. Preserved `self._h_desktop` across calls and ensured attachment prior to input dispatch.
  - *Defect 2 (Desktop Attachment Destruction in KeyboardController)*: Fixed `KeyboardController._ensure_active_desktop`, `clear_clipboard`, and `get_clipboard_text` where `CloseDesktop(h_input)` destroyed thread desktop assignment.
  - *Defect 3 (WindowManager get_foreground_window Desktop Detachment)*: Added `self._ensure_active_desktop()` to `WindowManager.get_foreground_window()`, resolving cases where background threads received `HWND 0` instead of the active foreground window (`Agents`).
  - *Defect 4 (DesktopObserver get_observation_at_time naive datetime TypeError)*: Fixed typo in `backend/app/environment/visual/observer.py` line 212 where `target_utc.replace(tgt_time=timezone.utc)` was called instead of `replace(tzinfo=timezone.utc)`. Added regression test `test_observer_timestamp_lookup_naive_datetime`.
  - *Defect 5 (Session Multimodal Prompt Context)*: Connected `desktop_observer` multimodal snapshots to `ConversationSession._update_system_prompt`, injecting active window and visible elements for the LLM planner. Added test `test_session_prompt_injects_multimodal_observation`.
  - *Defect 6 (Observer Lifecycle Determinism)*: Added test `test_observer_deterministic_lifecycle` verifying worker thread start/stop idempotency and clean joining.
  - *Defect 7 (Live Test Discrepancies & PID Ownership)*: Completely resolved discrepancies in `test_live_multimodal_grounding.py`:
    1. Baseline geometry established and recorded at `(250, 200, 600, 400)`; relocated geometry verified at `(350, 250, 600, 400)`; measured displacement is exactly `dx=+100px, dy=+50px` with constant dimensions `(600, 400)`.
    2. Process ownership anchored by launching Notepad with unique temporary file `astra_live_reloc_<uuid>.txt`. Distinguishes Launcher PID (`28164`) from packaged MSIX container PID (`35380`).
    3. Production pre-actuation gate rejected stale coordinates before physical input (`stale_coordinates_rejected: True`).
    4. Occluded target failed closed (`TARGET_DISAPPEARED`).
    5. Cleanup terminated both PIDs and deleted temporary file.
- **Environmental Constraint Disclosed & Verified**:
  - Windows 11 UIPI / Foreground Lockout restricts non-elevated background test windows from taking top-level visual focus over the user's active maximized workspace window (`HWND 28117378: "Agents" at (-9, -9, 1938, 1098)`).
  - Per mandatory operating rules: did not manipulate user windows or bypass Windows security.
  - Consequence: Window moved +100px,+50px via Win32 MoveWindow, but visual OCR cannot see the occluded background window. Live visual re-grounding and independent click verification criteria remain unverified on the live desktop.
- **Automated Test Results**:
  - Full backend unit suite: **295 passed** in 71.50s (100% green across all 30 test files, 0 failures).
  - Frontend production build: `npm run build` succeeded in 1.06s.
  - Live test harness: Dry-run and physical `--execute` runs completed cleanly with exit code 0.
- **Decision on B.13 Readiness**:
  - **Explicit Decision: B.13 NO-GO**.
  - Do NOT begin Phase B.13 until live visual target re-grounding is either validated in an unobstructed desktop environment or formally waived by the user.
- **Unobstructed Live Acceptance Test Procedure**:
  - Technical Environment Audit: Machine possesses a single 1920x1080 display (`DISPLAY1`). Secondary monitors and hidden Win32 desktops are physically absent or architecturally incompatible with DXcam WinRT desktop duplication.
  - Simplest Safe Option: User snaps the active IDE window to the right half of the display (`Win + Right Arrow`), exposing the left half `[x: 0..960, y: 0..1040]` without manipulating user windows.
  - Test Execution: Running `python backend/tests/live/test_live_multimodal_grounding.py --execute` will execute in the unobstructed left-half bounds (`x: 250..950, y: 200..650`), allowing DXcam and WinRT OCR to directly observe the test token and reacquire it after relocation.




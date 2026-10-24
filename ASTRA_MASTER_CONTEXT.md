# ASTRA — Master Architectural & Project Context

## 1. System Vision & Architecture
ASTRA is a local-first, voice-first personal computer assistant with an emphasis on rigorous architectural separation:
- **Semantic Reasoning & Planning**: High-level goal decomposition, intent formulation, action plans.
- **Action Execution**: Tool routing, permission gating, action plan execution via `ActionExecutor`.
- **Physical Actuation**: Low-level OS drivers (`MouseController`, `KeyboardController`) utilizing Win32 APIs (`SendInput`).
- **Observation & Perception**: Non-intrusive screen capture (`DXcam` / WinRT desktop duplication), native `Windows.Media.Ocr` visual perception engine, and system awareness providers.
- **Verification & Invalidation**: Ground truth verification (`VerificationEngine`), strict temporal freshness tracking (`InteractionTracker`), and explicit state invalidation.

## 2. Core Subsystems & Principles
1. **Physical Input Safety & Invariants**:
   - Cursor normalization maps virtual-screen topology to fixed-point 16-bit space `[0, 65535]` with half-pixel center biasing.
   - Physical clicks require explicit dwell time (60ms) and settle delay (50ms) to ensure WinUI 3 and XAML gesture recognition engines distinguish clicks from noise without generating drag events.
   - Mouse release is guaranteed via `try ... finally`.
2. **Visual Interaction Pipeline**:
   - `ExecuteVisualInteractionTool` exposes grounded click through standard tool execution.
   - `VisualInteractionService` orchestrates capture, candidate perception, target selection, coordinate grounding, and routing.
   - `TargetSelectionService` enforces exact-match preference, target window scoping (`target_bounds`), and menu strip prioritization before raising `TARGET_AMBIGUOUS`.
   - `InteractionTracker` records timestamps of physical interactions to invalidate stale observations.
3. **Verification**:
   - Verification is never fabricated from OS input acceptance.
   - Post-action observation must be strictly fresher than actuation.
   - Semantic state verification requires authoritative evidence (e.g., OCR dropdown tokens within ROI).
4. **Harmless Cleanup Invariants**:
   - Cleanup actions (e.g., closing transient menus) must be safe, bounded, and verified with fresh observations.
   - Keyboard dismissal must validate process-level foreground ownership without unconditionally re-focusing the root window container, which steals focus from active XAML popup flyouts.
   - Fallback dismissal must use neutral light-dismiss clicks within client content (e.g. document body) rather than clicking menu headers, preventing re-opening loops.
5. **Physical Keyboard & Text Input Invariants (Phase B.4)**:
   - All keyboard inputs must strictly utilize 64-bit compliant 40-byte `tagINPUT` structures with `SendInput`.
   - Unicode text typing utilizes `KEYEVENTF_UNICODE` (`wScan = ord(char), wVk = 0`), supporting arbitrary Unicode characters without clipboard hijacking or locale layout dependencies.
   - Special control keys (Enter, Backspace, Tab, Delete, Arrows) use explicit virtual-key codes with mapped hardware scan codes.
   - Hotkey combinations (e.g. `Ctrl+A`, `Ctrl+S`, `Alt+F4`) maintain ordered press and reverse-order release.
   - Human-like typing delay (configurable CPM) prevents buffer overflow in target application message loops.
   - Verification of text input validates observed state changes via fresh post-typing perception (OCR) or system awareness diffs.
6. **Physical Scroll, Drag & Advanced Mouse Invariants (Phase B.5)**:
   - Mouse wheel scrolling utilizes Win32 `MOUSEEVENTF_WHEEL` (vertical) and `MOUSEEVENTF_HWHEEL` (horizontal) with normalized `WHEEL_DELTA` (120 units per notch).
   - Wheel events must support targeted cursor positioning before actuation to guarantee the intended UI scroll container receives the wheel message.
   - Drag-and-drop actions must perform explicit coordinate interpolation across steps with micro-delays (5-15ms) to satisfy OS and application gesture engines.
   - Mouse drag release is strictly guaranteed via `try ... finally` to prevent stuck mouse-down states under actuation errors.
   - Context menu actuation (`RIGHT_CLICK`) enforces identical pre-activation checks, coordinate normalization, and 60ms dwell invariants as primary click.
7. **Composite Action Sequences & Multi-Step Orchestration Invariants (Phase B.6)**:
   - Composite action execution must preserve the `observe -> act -> observe -> verify -> recover` loop for every individual step.
   - Decouple OS input acceptance (`actuation_accepted: bool`) from verified semantic success (`verification_result.verified == TriState.TRUE`).
   - Authorization gates (`PermissionEvaluator`) must intercept consequential or protected actions before physical actuation.
   - Bounded recovery on intermediate step failure executes explicit, controlled recovery policies via `RecoveryEngine`.
   - Compensation actions execute only for explicitly reversible steps; irreversible physical actions are never subjected to simulated rollback.
   - Partial executions must truthfully report `PARTIAL_FAILURE` (never claiming sequence success when downstream steps fail).
   - Cancellation (`cancel_event`) and timeouts (`asyncio.timeout`) must be respected with explicit terminal statuses.
8. **Multi-Window & Cross-Application Composite Invariants (Phase B.7)**:
   - Cross-window steps must authoritatively verify foreground activation using Win32 `AttachThreadInput` and `SetForegroundWindow` before dispatching physical input to the target application.
   - Visual capture and OCR perception must dynamically re-scope bounding boxes (`target_bounds`) to the specific target window associated with each step.
   - State transfer across applications (e.g. clipboard copy-paste) must verify baseline state before transfer, the authoritative transfer operation, and the recipient state independently.
   - Harmless multi-window cleanup must restore or close all touched windows in reverse sequence order, verifying closure/clearing for each touched target.
9. **High-Level Natural Language Goal Compilation & Adaptive Execution Runtime (Phase B.8)**:
   - Untrusted model planning and trusted action execution are strictly separated: raw LLM outputs can never bypass authorization or schema validation.
   - High-level natural language goals are parsed and validated by `ActionCompiler.validate_plan` prior to compilation or actuation, rejecting unsupported applications, missing required parameters, and ambiguous tasks.
   - Plans compile into structured, deterministic `CompositeActionSequence` instances with explicit target window/application scoping, verifiers, and safe compensations.
   - Adaptive dynamic re-planning via `GoalRuntime` and `RecoveryEngine`: when intermediate step failures occur, remainder steps are sliced, context-refreshed, and re-executed under bounded retry limits (`max_replans = 2`).
   - Explicit terminal states (`SUCCESS`, `PARTIAL_FAILURE`, `FAILED`, `CANCELLED`, `TIMEOUT`) and cancellation contracts are strictly enforced across goal execution.
10. **Long-Running Goal Persistence, Checkpointing & Resumption Invariants (Phase B.9)**:
    - Versioned checkpoint contracts (`GoalCheckpoint`, `TaskCheckpoint`, schema 1.0) decouple durable persisted state from live ephemeral OS handles, window HWNDs, and provider sessions.
    - Local-first durable persistence (`SQLiteGoalStore` with WAL mode and atomic transactions) guarantees that goal execution survives backend process restarts.
    - Truthful resumption invariant: Persisted state is never blindly trusted as current environmental truth; completed verified steps are retained while composite sequences are sliced to resume strictly at `last_verified_step + 1`.
    - Terminal states are irreversible: Completed, cancelled, or corrupted goals can never be resumed (`is_resumable = False`).
    - Explicit separation of database state and real-world effects: An abort/rollback marks the database record as non-resumable FAILED and attempts known compensations for reversible steps only; database rollback is never represented as proof that external desktop effects were undone.
11. **Long-Term Dynamic Memory & Intent Grounding Invariants (Phase B.10)**:
    - Strict data-instruction separation: Stored memory records are strictly contextual data, never trusted as executable instructions or permission overrides.
    - Memory provenance and revisioning: Every record tracks provenance (`USER_EXPLICIT`, `USER_PREFERENCE`, `APPLICATION_PROFILE`, `EPISODIC_SUMMARY`, `INFERRED`), schema version (`1.0`), access frequency, and last access timestamps.
    - Zero ephemeral OS leaks: Ephemeral handles (`target_hwnd`, `hwnd`, `pid`, `thread_id`, `browser_session_id`, `active_page_id`) are stripped before storage and rejected by schema validators.
    - Local-first durability: `SQLiteMemoryStore` with WAL mode, deterministic updates, schema versioning, corruption isolation, and keyword/tag token relevance ranking without external cloud vector DBs or paid embedding APIs.
    - Strictly bounded context injection: Conversation planning injects at most 5 records and 1,200 characters under an explicit non-instructional boundary tag.
    - Strict 4-tier target grounding precedence:
      1. Explicit target specified in the current user request (takes absolute precedence).
      2. Reliable current-turn context (e.g. antecedent resolution for "it" or "the document").
      3. Stored application preference or alias (e.g. "my browser" -> Brave).
      4. Unresolved / ambiguous target (safely aborts or requests clarification without guessing).
    - Ephemeral truthfulness in episodic memory: Only goals achieving `GoalState.COMPLETED` generate episodic summaries; aborted, cancelled, or failed goals are never recorded as successes, and accepted actions are strictly distinguished from verified outcomes.
12. **Proactive Multi-Turn Desktop Task Assistance & Clarification Runtime (Phase B.11)**:
    - Structured clarification contracts: `ClarificationRequest` and `ClarificationResponse` models with unique request IDs, explicit `ClarificationType` (`AMBIGUOUS_TARGET`, `MISSING_PARAMETER`, `CONSEQUENTIAL_ACTION`, `HUMAN_INTERVENTION`), grounded candidates, and explicit expiration bounds.
    - Grounded target disambiguation: When target ambiguity is detected, `ActionCompiler` generates structured candidate options discovered dynamically from `ApplicationCatalog`, application profiles in `MemoryEngine`, or fresh active window snapshots. Candidates are never hallucinated or invented.
    - Precedence of current user intent: Explicit current user instructions strictly override stored memory preferences; stored memories can never grant permissions or bypass confirmation.
    - Deterministic consequential-action policy: Operations causing irreversible modifications (file deletion, process force-kill, destructive scripts) are deterministically classified by `ConsequentialActionPolicy` and gated before actuation.
    - Strictly scoped permissions: Approving a consequential confirmation grants only the scoped permission for the specific action and target for a bounded duration (300s); blanket, permanent, or ambient system permissions are never granted.
    - Zero destructive actuation on rejection: Rejection or cancellation immediately transitions goals to `GoalState.CANCELLED` with zero actuation dispatched.
    - Durable suspension across process restarts: Suspended interactions (`pending_clarification`) are persisted in `SQLiteGoalStore` and restored across backend restarts without replaying verified actions or re-prompting resolved requests.
    - Multi-turn interaction routing: `ConversationSession` matches user responses to pending requests, supports numeric or name-based option selection, rejects unrelated "yes" inputs for target clarifications, and safely supersedes suspended goals when users issue unrelated new instructions without corrupting checkpoint state.
13. **Multimodal Visual Grounding & Real-Time Context Fusion Invariants (Phase B.12)**:
    - Explicit coordinate domain distinction: Strict mathematical transformations between `IMAGE_LOCAL` [0, width) x [0, height), `WINDOW_RELATIVE`, `VIRTUAL_SCREEN`, and `DPI_LOGICAL` coordinates. Coordinate systems are never silently mixed or clamped into plausible-looking positions; out-of-bounds mapping raises explicit `CoordinateTransformError`.
    - Multi-monitor virtual desktop fidelity: `TargetSelectionService` and `ScreenCaptureProvider` support negative screen origins (`SM_XVIRTUALSCREEN < 0`) and multi-monitor layouts. Primary DXcam WinRT capture is reinforced by native Win32 GDI BitBlt fallback when display topologies exceed single-monitor capture boundaries. Partial captures are never misrepresented as full-desktop capture.
    - Lightweight perceptual change detection: Subsampled grayscale frame differencing (<2ms per 1080p frame) detects desktop mutations, computes damage regions, and filters GPU dithering/micro-noise.
    - Zero redundant OCR: Static desktop frames completely bypass OCR inference, preserving CPU and memory resources while maintaining an immediate forced-refresh path for target verification.
    - Pre-actuation re-grounding & spatial drift tracking: Visual targets do not retain authority merely because their representation exists in memory. Prior to physical dispatch, targets undergo mandatory freshness validation, spatial tracking, and drift checks; moved, occluded, or disappeared targets trigger immediate actuation rejection and recovery rather than blind dispatch.
    - Deterministic multimodal context fusion: Integrates OCR text tokens, UIAutomation element hierarchies, and active window entities. Resolves disabled states and cross-modal conflicts deterministically rather than delegating contradiction resolution to raw model inference.
    - Speech-to-observation temporal alignment: Audio utterances record client recording timestamps and align with bounded historical observation snapshots from the exact moment of speech onset with validated clock skew bounding and session isolation. Historical context grounds user intent while current pre-actuation re-grounding validates target presence before execution.
    - Observer mutual exclusion, isolation & privacy: Background polling enforces strict mutual exclusion during physical input actuation and settle intervals via `actuation_scope`, avoids unbounded image retention or unnecessary disk persistence, isolates history across sessions, and executes with deterministic worker shutdown via FastAPI lifespan.
    - Mandatory fail-closed safety invariant: `NO FRESH VALID TARGET -> NO PHYSICAL INPUT DISPATCH`. Validated across stable, moved, disappeared, occluded, ambiguous, stale, and timeout/exception conditions. Zero physical input events reach OS actuators on target perception failure.
    - Desktop input attachment & handle persistence: Threads dispatching physical input (`MouseController`, `KeyboardController`) or querying foreground state (`WindowManager`) must ensure attachment to the active input desktop (`OpenInputDesktop`, `SetThreadDesktop`) and preserve desktop handle lifetime (`self._h_desktop`) across invocations; premature `CloseDesktop` on active thread assignments invalidates the desktop token and causes `SendInput` to fail with `ERROR_ACCESS_DENIED (5)`.
    - Desktop isolation & UIPI boundaries: Under Windows 11 UIPI and foreground lockout policies (`SPI_SETFOREGROUNDLOCKTIMEOUT`), background processes cannot steal focus or elevate background test windows above active maximized user workspaces without violating safety rules against manipulating user windows. When targets are occluded by foreground workspaces, the system strictly enforces the fail-closed invariant (`TARGET_OCCLUDED` / `TARGET_DISAPPEARED`), guaranteeing zero unverified physical input dispatch.




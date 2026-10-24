import uuid
import copy
from typing import Optional, List, Dict, Any, Tuple

from app.domain.goals import (
    Goal,
    Task,
    Intent,
    SemanticAction,
    TargetType,
    TargetOrdinal,
    GoalState,
    FailureClass,
    PlanValidationResult,
)
from app.domain.composite import (
    CompositeActionSequence,
    CompositeStep,
    CompensationAction,
)
from app.domain.memory import RecoveryStrategy
from app.domain.execution_context import ExecutionContext
from app.core.logging.logger import get_logger

logger = get_logger(__name__)

# Standard known OS applications and utilities
STANDARD_KNOWN_APPS = {
    "notepad", "calc", "calculator", "cmd", "powershell", "explorer", "mspaint",
    "paint", "browser", "chrome", "googlechrome", "edge", "microsoftedge",
    "brave", "spotify", "word", "excel", "powerpoint", "settings",
}

class ActionCompiler:
    """
    ActionCompiler deterministic compilation and plan validation layer (Phase B.8 / B.10).
    Converts high-level goals and semantic intents from language-model planning into
    authoritative, validated, executable plans and CompositeActionSequences.
    Enforces strict separation between untrusted model planning and trusted execution.
    Implements Phase B.10 Context-Aware Target Grounding with strict precedence order:
    1. Explicit target in user request.
    2. Reliable current-turn context.
    3. Relevant stored application preference or alias in MemoryEngine.
    4. Ambiguous / Unresolved.
    """

    def __init__(self, memory_engine: Optional[Any] = None) -> None:
        self.memory_engine = memory_engine

    def _get_memory_engine(self) -> Optional[Any]:
        if self.memory_engine is not None:
            return self.memory_engine
        try:
            from app.memory.engine import get_memory_engine
            return get_memory_engine()
        except Exception as e:
            logger.debug(f"ActionCompiler could not load MemoryEngine: {e}")
            return None

    def ground_target(
        self,
        target_name: Optional[str],
        action: Optional[SemanticAction] = None,
        context: Optional[ExecutionContext] = None,
    ) -> Tuple[Optional[str], float, str]:
        """
        Grounds an intent target using the strict Phase B.10 precedence order:
        1. Explicit target specified in the current user request (if specific and recognized).
        2. Reliable current-turn context (for anaphoric references like 'it', 'this', 'current app').
        3. Relevant stored application preference or alias in MemoryEngine (e.g. 'my browser' -> 'brave').
        4. Clarification / Unresolved when ambiguous.

        Returns: (grounded_target_name, confidence, resolution_source)
        """
        if not target_name or not str(target_name).strip():
            # If target is missing, check if current context can ground it for focus/close
            if action in (SemanticAction.FOCUS, SemanticAction.CLOSE) and context:
                ctx_app = getattr(context, "active_browser_identity", None) or getattr(context, "target_application", None)
                if ctx_app:
                    return (str(ctx_app).strip().lower(), 0.9, "current_context")
            return (None, 0.0, "missing_target")

        raw_str = str(target_name).strip()
        norm_str = raw_str.lower()

        from app.environment.application.catalog import catalog
        all_apps = catalog.get_all()
        norm_catalog_key = catalog._normalize_name(norm_str)

        # Pronoun / anaphoric check
        is_anaphoric = norm_str in ("it", "this", "that", "them", "the target", "the app", "current app", "active app")
        generic_terms = {"browser", "notes", "notes editor", "editor", "text editor", "web browser", "terminal"}

        # Tier 1: Explicit specific application target
        # If the user explicitly provided a specific application target (not an anaphora or generic "my ..."),
        # the explicit instruction strictly overrides historical preferences or aliases!
        if not is_anaphoric and norm_str not in generic_terms and not norm_str.startswith("my "):
            return (norm_str, 1.0, "explicit_request")

        # Tier 2: Reliable current-turn context (especially for pronouns like 'it')
        if is_anaphoric:
            if context:
                ctx_app = (
                    (context.last_intent.target if context.last_intent and context.last_intent.target else None)
                    or getattr(context, "active_browser_identity", None)
                    or (context.environment_snapshot.get("last_target") if context.environment_snapshot else None)
                )
                if ctx_app and str(ctx_app).strip():
                    return (str(ctx_app).strip().lower(), 0.95, "current_context")

            # Multiple candidates or no reliable active window -> Ambiguous!
            return (None, 0.0, "unresolved_ambiguous")

        # Tier 3: Relevant stored application preference or alias in MemoryEngine
        mem_engine = self._get_memory_engine()
        if mem_engine is not None:
            profile = mem_engine.resolve_target_alias(norm_str)
            if profile and profile.canonical_name:
                prof_target = profile.canonical_name.strip().lower()
                prof_key = catalog._normalize_name(prof_target)
                if prof_key in all_apps or prof_target in STANDARD_KNOWN_APPS or any(prof_target in k for k in all_apps):
                    return (prof_target, 0.85, "stored_preference")

        # If it's a generic known term in STANDARD_KNOWN_APPS without a specific preference:
        if norm_str in STANDARD_KNOWN_APPS or norm_catalog_key in all_apps:
            return (norm_str, 0.7, "standard_catalog")

        # Tier 4: Ambiguous / Unresolved
        return (None, 0.0, "unresolved_ambiguous")

    def find_clarification_candidates(
        self,
        target_name: Optional[str],
        action: Optional[SemanticAction] = None,
        context: Optional[ExecutionContext] = None,
    ) -> List[Any]:
        """
        Discovers real, grounded candidates for an ambiguous target from:
        1. Installed applications in ApplicationCatalog.
        2. Application profiles in MemoryEngine.
        3. Active window candidates from ExecutionContext environment snapshot.
        Never fabricates or hallucinates non-existent candidates.
        """
        from app.environment.application.catalog import catalog
        from app.domain.clarification import ClarificationOption
        
        all_apps = catalog.get_all()
        options: List[ClarificationOption] = []
        seen_vals = set()

        raw_str = str(target_name or "").strip().lower()
        if raw_str.startswith("my "):
            raw_str = raw_str[3:].strip()

        # 1. Check MemoryEngine application profiles for matching category or alias
        mem_engine = self._get_memory_engine()
        if mem_engine is not None:
            try:
                profiles = mem_engine.list_application_profiles()
                for p in profiles:
                    cat_match = p.category and (p.category.lower() in raw_str or raw_str in p.category.lower())
                    alias_match = any(raw_str in a.lower() or a.lower() in raw_str for a in p.aliases)
                    if cat_match or alias_match:
                        val = p.canonical_name.lower()
                        if val not in seen_vals:
                            seen_vals.add(val)
                            options.append(ClarificationOption(
                                option_id=val,
                                label=p.display_name or p.canonical_name,
                                value=val,
                                description=f"Profile preference for category '{p.category}'",
                                is_recommended=bool(p.is_default_for_category),
                            ))
            except Exception as ex:
                logger.debug(f"Compiler candidate discovery from MemoryEngine failed: {ex}")

        # 2. Check ApplicationCatalog by category / keywords
        browser_keys = [("brave", "Brave Browser"), ("chrome", "Google Chrome"), ("edge", "Microsoft Edge"), ("firefox", "Mozilla Firefox")]
        editor_keys = [("notepad", "Notepad"), ("code", "Visual Studio Code"), ("notepad++", "Notepad++"), ("sublime_text", "Sublime Text")]
        terminal_keys = [("powershell", "Windows PowerShell"), ("cmd", "Command Prompt"), ("terminal", "Windows Terminal")]

        target_group = None
        if any(w in raw_str for w in ("browser", "web")):
            target_group = browser_keys
        elif any(w in raw_str for w in ("note", "editor", "text")):
            target_group = editor_keys
        elif any(w in raw_str for w in ("terminal", "console", "command")):
            target_group = terminal_keys

        if target_group:
            for key, display in target_group:
                if key not in seen_vals:
                    norm_k = catalog._normalize_name(key)
                    if norm_k in all_apps or key in STANDARD_KNOWN_APPS or any(key in k for k in all_apps):
                        seen_vals.add(key)
                        options.append(ClarificationOption(
                            option_id=key,
                            label=display,
                            value=key,
                            description=f"Installed {raw_str} application",
                            is_recommended=(len(options) == 0),
                        ))

        # 3. For anaphoric references ("it", "this", "that"), check active windows in environment snapshot
        if raw_str in ("it", "this", "that", "the app", "current app", "active app") and context:
            active_windows = (context.environment_snapshot or {}).get("active_windows", [])
            for w in active_windows:
                if isinstance(w, dict):
                    app_name = (w.get("app_name") or w.get("title") or "").strip().lower()
                    if app_name and app_name not in seen_vals:
                        seen_vals.add(app_name)
                        options.append(ClarificationOption(
                            option_id=app_name,
                            label=w.get("title") or app_name,
                            value=app_name,
                            description=f"Currently active window (PID {w.get('pid', 'N/A')})",
                            is_recommended=(len(options) == 0),
                        ))

        return options

    def validate_plan(self, goal: Goal, context: Optional[ExecutionContext] = None) -> PlanValidationResult:
        """
        Validates untrusted model-generated goal plans against capabilities,
        schemas, application catalogs, and required parameters before execution.
        Guarantees that raw model output cannot bypass validation or authorization.
        """
        errors: List[str] = []
        warnings: List[str] = []
        failure_class: Optional[FailureClass] = None
        clarification_request: Optional[Any] = None

        if not goal.objective or not goal.objective.strip():
            errors.append("Goal objective cannot be empty or whitespace.")
            failure_class = FailureClass.UNKNOWN

        if not goal.tasks:
            errors.append("Goal contains no tasks to execute.")
            failure_class = FailureClass.UNKNOWN

        # Import catalog dynamically to avoid circular references
        from app.environment.application.catalog import catalog
        all_apps = catalog.get_all()

        for t_idx, task in enumerate(goal.tasks):
            if not task.description or not task.description.strip():
                warnings.append(f"Task {t_idx} ('{task.task_id}') lacks a human-readable description.")

            has_intents = bool(task.intents)
            has_composite = bool(getattr(task, "composite_sequence", None))

            if not has_intents and not has_composite:
                errors.append(f"Task {t_idx} ('{task.description or task.task_id}') contains neither intents nor a composite sequence.")
                failure_class = FailureClass.UNKNOWN

            for i_idx, intent in enumerate(task.intents):
                # 1. Action validity
                if not intent.action:
                    errors.append(f"Task {t_idx} Intent {i_idx}: missing semantic action.")
                    failure_class = FailureClass.UNKNOWN
                    continue

                action = intent.action

                # 2. Application targeting validity for application lifecycle intents
                if action in (SemanticAction.OPEN, SemanticAction.FOCUS, SemanticAction.CLOSE):
                    target_name = intent.target or (intent.parameters or {}).get("application") or (intent.parameters or {}).get("target")
                    grounded_target, conf, source = self.ground_target(target_name, action=action, context=context)
                    if grounded_target:
                        intent.target = grounded_target
                        if intent.parameters is None:
                            intent.parameters = {}
                        intent.parameters["application"] = grounded_target
                        target_name = grounded_target

                    if not target_name or not str(target_name).strip():
                        errors.append(f"Task {t_idx} Intent {i_idx} ({action}): missing required application target.")
                        failure_class = FailureClass.TARGET_NOT_FOUND
                    elif source == "unresolved_ambiguous":
                        errors.append(
                            f"Task {t_idx} Intent {i_idx} ({action}): Target '{target_name or 'None'}' is ambiguous or unresolved."
                        )
                        failure_class = FailureClass.TARGET_NOT_FOUND

                        # Phase B.11: Generate structured ClarificationRequest for ambiguous target
                        candidates = self.find_clarification_candidates(target_name, action=action, context=context)
                        if candidates:
                            candidate_labels = ", ".join(c.label for c in candidates)
                            prompt = f"Which application would you like to use for '{target_name or 'the requested action'}'? ({candidate_labels})"
                        else:
                            prompt = f"Please specify which application you would like to use for '{target_name or action.value}'."

                        from app.domain.clarification import ClarificationRequest, ClarificationType
                        clarification_request = ClarificationRequest(
                            clarification_type=ClarificationType.AMBIGUOUS_TARGET,
                            prompt=prompt,
                            options=candidates,
                            default_option_id=candidates[0].option_id if candidates else None,
                            goal_id=goal.goal_id,
                            task_id=task.task_id,
                            action_type=action.value,
                            target_name=target_name,
                            requires_explicit_confirmation=False,
                        )
                        warnings.append(f"Task {t_idx} Intent {i_idx} ({action}): Target '{target_name}' is ambiguous; clarification requested.")
                    else:
                        norm_target = str(target_name).strip().lower()
                        norm_catalog_key = catalog._normalize_name(norm_target)
                        if (
                            norm_catalog_key not in all_apps
                            and norm_target not in STANDARD_KNOWN_APPS
                            and not any(norm_target in k for k in all_apps)
                        ):
                            errors.append(
                                f"Task {t_idx} Intent {i_idx} ({action}): Target application '{target_name}' is not installed or recognized in application catalog."
                            )
                            failure_class = FailureClass.TARGET_NOT_FOUND

                # 3. Parameter completeness per action
                elif action in (SemanticAction.TYPE_TEXT, SemanticAction.INPUT):
                    params = intent.parameters or {}
                    has_text = bool(intent.query or params.get("text") or params.get("value"))
                    if not has_text:
                        errors.append(f"Task {t_idx} Intent {i_idx} ({action}): missing required text payload in query, text, or value parameter.")
                        failure_class = FailureClass.UNKNOWN

                elif action == SemanticAction.HOTKEY:
                    params = intent.parameters or {}
                    keys = params.get("keys")
                    if not keys:
                        # Check target for string hotkeys like "ctrl+c"
                        if intent.target and "+" in intent.target:
                            keys = [k.strip() for k in intent.target.split("+")]
                    if not keys or not isinstance(keys, (list, tuple)) or len(keys) == 0:
                        errors.append(f"Task {t_idx} Intent {i_idx} (HOTKEY): missing or empty 'keys' parameter list.")
                        failure_class = FailureClass.UNKNOWN

                elif action == SemanticAction.NAVIGATE:
                    params = intent.parameters or {}
                    target_url = intent.target or params.get("url") or params.get("target")
                    if not target_url or not str(target_url).strip():
                        errors.append(f"Task {t_idx} Intent {i_idx} (NAVIGATE): missing destination URL target.")
                        failure_class = FailureClass.TARGET_NOT_FOUND

                elif action == SemanticAction.DRAG:
                    params = intent.parameters or {}
                    has_coords = (
                        "start_x" in params and "start_y" in params and "end_x" in params and "end_y" in params
                    )
                    has_label = bool(intent.target or params.get("target_label"))
                    if not has_coords and not has_label:
                        errors.append(f"Task {t_idx} Intent {i_idx} (DRAG): missing both drag coordinates and target label.")
                        failure_class = FailureClass.UNKNOWN

        is_valid = len(errors) == 0
        return PlanValidationResult(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            failure_class=failure_class if not is_valid else None,
            clarification_request=clarification_request,
        )

    def compile_goal_to_composite_sequence(
        self,
        goal: Goal,
        context: Optional[ExecutionContext] = None,
        sequence_name: Optional[str] = None,
        timeout_seconds: float = 120.0,
    ) -> CompositeActionSequence:
        """
        Compiles validated high-level desktop interaction tasks and intents from a Goal into
        an authoritative, verified CompositeActionSequence.
        Injects:
        - target application window scoping (target_app_name, ensure_foreground)
        - authoritative verifier types and arguments (TEXT_INPUT, CLIPBOARD, WINDOW_FOCUS, CROSS_WINDOW_SYNC, etc.)
        - safe verified compensations (Undo, Dismiss, Settle)
        - cross-window transition synchronization
        """
        from app.ai.orchestrator.action_planner import action_planner

        steps_def: List[Dict[str, Any]] = []
        current_app_name: Optional[str] = None
        last_typed_payload: str = ""
        last_copied_payload: str = ""

        step_idx = 0
        for task in goal.tasks:
            for intent in task.intents:
                action = intent.action
                params = dict(intent.parameters or {})
                target = intent.target or params.get("target") or params.get("application")

                # Resolve application focus context
                target_app = None
                if action in (SemanticAction.OPEN, SemanticAction.FOCUS, SemanticAction.CLOSE):
                    target_app = str(target) if target else None
                    if action != SemanticAction.CLOSE:
                        current_app_name = target_app
                else:
                    target_app = str(target) if target else current_app_name

                # Determine capability_id
                cap_id = intent.capability_id or self._map_to_capability(intent)

                step_dict: Dict[str, Any] = {
                    "step_id": f"step_{step_idx}_{action.value.lower()}",
                    "intent_id": intent.intent_id or str(uuid.uuid4()),
                    "action": action.value,
                    "target": target,
                    "target_app_name": target_app,
                    "capability_id": cap_id,
                    "ensure_foreground": True if target_app else False,
                    "description": f"Step {step_idx}: {action.value} on {target or target_app or 'desktop'}",
                }

                # Configure per-action verifiers, arguments, and compensations
                if action == SemanticAction.OPEN:
                    step_dict["capability_id"] = "desktop.open_application"
                    step_dict["requires_verification"] = True
                    step_dict["verifier_type"] = "WINDOW_FOCUS"
                    step_dict["verifier_args"] = {"target_app_name": target_app}
                    step_dict["tool_args"] = {"intent": "OPEN", "application": target_app}

                elif action == SemanticAction.FOCUS:
                    step_dict["capability_id"] = "desktop.focus_application"
                    step_dict["requires_verification"] = True
                    step_dict["verifier_type"] = "WINDOW_FOCUS"
                    step_dict["verifier_args"] = {"target_app_name": target_app}
                    step_dict["tool_args"] = {"intent": "FOCUS", "application": target_app}

                elif action in (SemanticAction.TYPE_TEXT, SemanticAction.INPUT):
                    step_dict["capability_id"] = "desktop.physical_input"
                    typed_text = params.get("text") or intent.query or params.get("value", "")
                    last_typed_payload = str(typed_text).strip()
                    step_dict["action"] = action.value
                    step_dict["tool_args"] = {"intent": action.value, "text": typed_text}
                    if "x" in params and "y" in params:
                        step_dict["tool_args"]["x"] = params["x"]
                        step_dict["tool_args"]["y"] = params["y"]
                    step_dict["requires_verification"] = True
                    step_dict["verifier_type"] = "TEXT_INPUT"
                    step_dict["verifier_args"] = {"expected_text": last_typed_payload}
                    step_dict["settle_delay_seconds"] = 0.5
                    # Safe verified compensation: undo typed text
                    step_dict["compensation"] = {
                        "action": "HOTKEY",
                        "target": target_app,
                        "capability_id": "desktop.physical_input",
                        "tool_args": {"intent": "HOTKEY", "keys": ["ctrl", "z"]},
                        "description": f"Undo typed text in {target_app or 'editor'}",
                    }

                elif action == SemanticAction.HOTKEY:
                    step_dict["capability_id"] = "desktop.physical_input"
                    keys = params.get("keys", [])
                    if isinstance(keys, str):
                        keys = [k.strip().lower() for k in keys.split("+")]
                    keys_lower = [str(k).lower() for k in keys]
                    step_dict["tool_args"] = {"intent": "HOTKEY", "keys": keys}

                    if "ctrl" in keys_lower and "c" in keys_lower:
                        # Copy hotkey: authoritative CLIPBOARD verifier
                        expected_cb = params.get("expected_content") or last_typed_payload or ""
                        last_copied_payload = expected_cb
                        step_dict["requires_verification"] = True
                        step_dict["verifier_type"] = "CLIPBOARD"
                        step_dict["verifier_args"] = {"expected_content": expected_cb}
                        step_dict["settle_delay_seconds"] = 0.4
                    elif "ctrl" in keys_lower and "a" in keys_lower:
                        # Select-all hotkey: physical actuation accepted without semantic visual requirement
                        step_dict["requires_verification"] = False
                        step_dict["settle_delay_seconds"] = 0.3
                    elif "ctrl" in keys_lower and "v" in keys_lower:
                        # Paste hotkey: cross-window sync if transferred across application boundary
                        if last_copied_payload:
                            step_dict["requires_verification"] = True
                            step_dict["verifier_type"] = "CROSS_WINDOW_SYNC"
                            step_dict["verifier_args"] = {
                                "expected_content": last_copied_payload,
                                "destination_window": target_app,
                            }
                        else:
                            step_dict["requires_verification"] = False
                    else:
                        step_dict["requires_verification"] = bool(params.get("requires_verification", False))

                elif action == SemanticAction.CLICK:
                    step_dict["capability_id"] = "desktop.physical_input"
                    step_dict["tool_args"] = dict(params)
                    if "intent" not in step_dict["tool_args"]:
                        step_dict["tool_args"]["intent"] = "CLICK"
                    step_dict["requires_verification"] = bool(params.get("requires_verification", True if target_app else False))
                    step_dict["verifier_type"] = params.get("verifier_type", "WINDOW_FOCUS" if target_app else None)
                    step_dict["verifier_args"] = params.get("verifier_args", {"target_app_name": target_app} if target_app else {})

                elif action == SemanticAction.RIGHT_CLICK:
                    step_dict["capability_id"] = "desktop.physical_input"
                    step_dict["tool_args"] = dict(params)
                    if "intent" not in step_dict["tool_args"]:
                        step_dict["tool_args"]["intent"] = "RIGHT_CLICK"
                    step_dict["requires_verification"] = True
                    step_dict["verifier_type"] = "CONTEXT_MENU"
                    step_dict["verifier_args"] = params.get("verifier_args", {})
                    # Safe verified compensation: dismiss context menu via Escape
                    step_dict["compensation"] = {
                        "action": "HOTKEY",
                        "target": target_app,
                        "capability_id": "desktop.physical_input",
                        "tool_args": {"intent": "HOTKEY", "keys": ["escape"]},
                        "description": "Dismiss context menu via Escape",
                    }

                elif action == SemanticAction.SCROLL:
                    step_dict["capability_id"] = "desktop.physical_input"
                    step_dict["tool_args"] = dict(params)
                    if "intent" not in step_dict["tool_args"]:
                        step_dict["tool_args"]["intent"] = "SCROLL"
                    step_dict["requires_verification"] = True
                    step_dict["verifier_type"] = "SCROLL"
                    step_dict["verifier_args"] = params.get("verifier_args", {})

                elif action == SemanticAction.DRAG:
                    step_dict["capability_id"] = "desktop.physical_input"
                    step_dict["tool_args"] = dict(params)
                    if "intent" not in step_dict["tool_args"]:
                        step_dict["tool_args"]["intent"] = "DRAG"
                    step_dict["requires_verification"] = True
                    step_dict["verifier_type"] = "DRAG"
                    step_dict["verifier_args"] = params.get("verifier_args", {})

                elif action == SemanticAction.CLOSE:
                    step_dict["capability_id"] = "desktop.close_application"
                    step_dict["tool_args"] = {"intent": "CLOSE", "application": target_app}
                    step_dict["requires_verification"] = bool(params.get("requires_verification", False))
                    if "verifier_type" in params:
                        step_dict["verifier_type"] = params["verifier_type"]
                        step_dict["verifier_args"] = params.get("verifier_args", {})

                else:
                    step_dict["capability_id"] = cap_id
                    step_dict["tool_args"] = dict(params)
                    if "intent" not in step_dict["tool_args"]:
                        step_dict["tool_args"]["intent"] = action.value
                    step_dict["requires_verification"] = bool(params.get("requires_verification", False))
                    if "verifier_type" in params:
                        step_dict["verifier_type"] = params["verifier_type"]
                    if "verifier_args" in params:
                        step_dict["verifier_args"] = params["verifier_args"]
                    if "settle_delay_seconds" in params:
                        step_dict["settle_delay_seconds"] = float(params["settle_delay_seconds"])

                # Phase B.11: Evaluate consequential action policy
                from app.core.security.consequential import ConsequentialActionPolicy
                is_conseq, conseq_reason, impact = ConsequentialActionPolicy.evaluate_intent(intent)
                if is_conseq or params.get("consequential"):
                    step_dict["consequential"] = True

                steps_def.append(step_dict)
                step_idx += 1

        seq_name = sequence_name or f"goal_seq_{uuid.uuid4().hex[:6]}"
        return action_planner.plan_composite_sequence(
            sequence_name=seq_name,
            steps_def=steps_def,
            timeout_seconds=timeout_seconds,
            max_retries_per_step=2,
            allow_compensation=True,
        )

    def replan_remainder_sequence(
        self,
        sequence: CompositeActionSequence,
        failed_step_index: int,
        strategy: Optional[RecoveryStrategy] = None,
    ) -> Optional[CompositeActionSequence]:
        """
        Adaptive dynamic re-planning on intermediate step failure.
        Couples RecoveryEngine strategies with plan remainder compilation:
        - If strategy is INSPECT_STATE / REFRESH_OBSERVATION, inserts a pre-flight window
          refocus and stabilization settle step before re-attempting the failed step.
        - Re-indexes remainder steps preserving downstream execution requirements.
        """
        if failed_step_index < 0 or failed_step_index >= len(sequence.steps):
            return None

        failed_step = sequence.steps[failed_step_index]
        remaining_steps = sequence.steps[failed_step_index:]

        repaired_steps: List[CompositeStep] = []
        new_step_idx = 0

        # Inject adaptive stabilization step if recovering from focus or verification glitches
        if strategy in (RecoveryStrategy.INSPECT_STATE, RecoveryStrategy.REFRESH_OBSERVATION):
            if failed_step.target_app_name:
                from app.domain.goals import Intent
                stabilize_step = CompositeStep(
                    step_id=f"replan_refocus_{uuid.uuid4().hex[:4]}",
                    step_index=new_step_idx,
                    intent=Intent(
                        intent_id=str(uuid.uuid4()),
                        action=SemanticAction.FOCUS,
                        target=failed_step.target_app_name,
                        capability_id="desktop.focus_application",
                    ),
                    tool_args={"intent": "FOCUS", "application": failed_step.target_app_name},
                    description=f"Adaptive Replan: Re-focus and stabilize '{failed_step.target_app_name}'",
                    target_app_name=failed_step.target_app_name,
                    ensure_foreground=True,
                    requires_verification=True,
                    verifier_type="WINDOW_FOCUS",
                    verifier_args={"target_app_name": failed_step.target_app_name},
                    settle_delay_seconds=0.5,
                )
                repaired_steps.append(stabilize_step)
                new_step_idx += 1

        # Re-attach and re-index remainder steps
        for step in remaining_steps:
            cloned = step.model_copy(deep=True)
            cloned.step_index = new_step_idx
            cloned.step_id = f"replan_{cloned.step_id}"
            repaired_steps.append(cloned)
            new_step_idx += 1

        return CompositeActionSequence(
            sequence_id=f"replan_{sequence.sequence_id}_{uuid.uuid4().hex[:4]}",
            name=f"Adaptive Replan of {sequence.name}",
            steps=repaired_steps,
            timeout_seconds=sequence.timeout_seconds,
            max_retries_per_step=1,
            allow_compensation=sequence.allow_compensation,
        )

    async def compile(self, goal: Goal, context: ExecutionContext) -> Goal:
        """
        Compiles and validates a Goal.
        Enforces plan validation first; if invalid, sets GoalState.FAILED with diagnostics.
        Resolves meta-intents, pronouns, and compiles desktop tasks into CompositeActionSequences.
        """
        compiled_goal = copy.deepcopy(goal)

        # 1. Authoritative Plan Validation
        validation = self.validate_plan(compiled_goal, context)
        if validation.clarification_request:
            logger.info(f"ActionCompiler: Goal requires clarification: {validation.clarification_request.prompt}")
            compiled_goal.state = GoalState.WAITING_FOR_USER
            compiled_goal.pending_clarification = validation.clarification_request
            compiled_goal.validation_errors = validation.errors
            if context is not None:
                context.pending_clarification = validation.clarification_request
            return compiled_goal

        if not validation.is_valid:
            logger.warning(f"ActionCompiler plan validation failed: {validation.errors}")
            compiled_goal.state = GoalState.FAILED
            compiled_goal.validation_errors = validation.errors
            return compiled_goal

        # 2. Compile Tasks & Semantic Intents
        for task in compiled_goal.tasks:
            compiled_intents = []
            for intent in task.intents:
                compiled_intent = await self._compile_intent(intent, context)
                if compiled_intent:
                    compiled_intents.append(compiled_intent)

            task.intents = compiled_intents

            # Phase B.8: If task contains desktop interaction intents and no explicit composite sequence,
            # compile them into an authoritative verified CompositeActionSequence.
            if len(task.intents) > 1 and not getattr(task, "composite_sequence", None):
                is_desktop_interaction = any(
                    i.capability_id in (
                        "desktop.physical_input",
                        "desktop.visual_interaction",
                        "desktop.open_application",
                        "desktop.focus_application",
                    )
                    or i.action in (
                        SemanticAction.OPEN,
                        SemanticAction.FOCUS,
                        SemanticAction.TYPE_TEXT,
                        SemanticAction.INPUT,
                        SemanticAction.HOTKEY,
                        SemanticAction.CLICK,
                        SemanticAction.RIGHT_CLICK,
                        SemanticAction.SCROLL,
                        SemanticAction.DRAG,
                    )
                    for i in task.intents
                )
                if is_desktop_interaction:
                    task_goal = Goal(
                        goal_id=task.task_id,
                        objective=task.description or "Task Execution",
                        tasks=[task],
                    )
                    task.composite_sequence = self.compile_goal_to_composite_sequence(
                        task_goal,
                        context=context,
                        sequence_name=task.description or f"composite_{task.task_id}",
                    )

        return compiled_goal

    async def _compile_intent(self, intent: Intent, context: ExecutionContext) -> Intent:
        # Handle Meta-Intents
        if intent.action == SemanticAction.REPEAT:
            if context.last_intent:
                logger.info(f"Compiler: Resolving REPEAT to {context.last_intent.action}")
                cloned = copy.deepcopy(context.last_intent)
                cloned.intent_id = str(uuid.uuid4())
                return cloned
            else:
                logger.warning("Compiler: REPEAT requested but no last_intent exists.")
                return intent

        if intent.action == SemanticAction.RETRY:
            if context.retryable_intent:
                logger.info(f"Compiler: Resolving RETRY to {context.retryable_intent.action}")
                cloned = copy.deepcopy(context.retryable_intent)
                cloned.intent_id = str(uuid.uuid4())
                return cloned
            elif context.last_intent:
                logger.info(f"Compiler: Resolving RETRY to {context.last_intent.action} as fallback")
                cloned = copy.deepcopy(context.last_intent)
                cloned.intent_id = str(uuid.uuid4())
                return cloned
            else:
                logger.warning("Compiler: RETRY requested but no retryable_intent exists.")
                return intent

        # Pronoun resolution and target grounding
        grounded_target, conf, source = self.ground_target(intent.target, action=intent.action, context=context)
        if grounded_target and source != "unresolved_ambiguous":
            intent.target = grounded_target
        elif intent.target and intent.target.lower() in ("it", "that", "this", "them"):
            if context.last_intent and context.last_intent.target:
                logger.info(f"Compiler: Resolving pronoun '{intent.target}' to '{context.last_intent.target}'")
                intent.target = context.last_intent.target
                intent.target_type = context.last_intent.target_type
            elif context.environment_snapshot.get("last_target"):
                intent.target = context.environment_snapshot.get("last_target")

        # Inject persistent context for browser
        if not intent.browser and context.active_browser_identity:
            intent.browser = context.active_browser_identity

        # Map Semantic Intent to Executable Capability ID
        intent.capability_id = self._map_to_capability(intent)

        # Populate deterministic parameters for executor
        intent.parameters = {
            "action": intent.action.value if hasattr(intent.action, "value") else str(intent.action),
            "target": intent.target,
            "target_type": intent.target_type.value if hasattr(intent.target_type, "value") else str(intent.target_type),
            "ordinal": intent.ordinal.value if hasattr(intent.ordinal, "value") else str(intent.ordinal),
            "query": intent.query,
            "browser": intent.browser,
            "page_context": intent.page_context,
            **(intent.parameters or {}),
        }

        return intent

    def _map_to_capability(self, intent: Intent) -> str:
        """
        Maps the semantic action and target type to a capability ID for the executor.
        """
        if intent.action == SemanticAction.OPEN:
            if intent.target_type in (TargetType.WEBSITE, TargetType.URL_OR_SITE):
                return "browser.navigate"
            return "desktop.open_application"

        elif intent.action == SemanticAction.FOCUS:
            return "desktop.focus_application"

        elif intent.action == SemanticAction.CLOSE:
            return "desktop.close_application"

        elif intent.action in (
            SemanticAction.CLICK,
            SemanticAction.DOUBLE_CLICK,
            SemanticAction.RIGHT_CLICK,
            SemanticAction.SCROLL,
            SemanticAction.DRAG,
            SemanticAction.HOTKEY,
            SemanticAction.PRESS_KEY,
            SemanticAction.TYPE_TEXT,
        ):
            return "desktop.physical_input"

        elif intent.action == SemanticAction.NAVIGATE:
            return "browser.navigate"

        elif intent.action == SemanticAction.SEARCH:
            return "browser.search"

        elif intent.action in (SemanticAction.PLAY, SemanticAction.PAUSE, SemanticAction.INPUT):
            if intent.target_type in (TargetType.APPLICATION, TargetType.COORDINATE) or not intent.browser:
                return "desktop.physical_input"
            return "browser.interact"

        return "system.generic"

action_compiler = ActionCompiler()

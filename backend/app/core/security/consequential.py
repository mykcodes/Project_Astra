"""
ASTRA Security - Consequential Action Policy (Phase B.11)

Deterministic classification and verification of consequential and destructive
desktop operations. Enforces pre-actuation authorization gates before irreversible
side effects can occur.
"""

from typing import Any, Dict, List, Optional, Tuple
import re

from app.domain.goals import Intent, SemanticAction
from app.domain.composite import CompositeStep
from app.domain.permissions import CapabilityScope
from app.domain.clarification import (
    ClarificationRequest,
    ClarificationType,
    ClarificationOption,
)

DESTRUCTIVE_COMMAND_PATTERNS = [
    re.compile(r"\b(del|erase|rm|rmdir|rd|remove-item)\b", re.IGNORECASE),
    re.compile(r"\b(taskkill|kill|Stop-Process)\s+.*(/f|-force)\b", re.IGNORECASE),
    re.compile(r"\b(format|diskpart|reg\s+delete|Drop-Database)\b", re.IGNORECASE),
]

DESTRUCTIVE_FILE_EXTENSIONS = {
    ".sys", ".dll", ".exe", ".bat", ".cmd", ".ps1", ".vbs", ".reg", ".ini"
}

class ConsequentialActionPolicy:
    """
    Evaluates whether an action, intent, or composite step constitutes a
    consequential or destructive desktop operation requiring explicit user confirmation.
    """

    @classmethod
    def evaluate_intent(
        cls,
        intent_or_action: Any,
        target: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Evaluates an Intent or (action, target, parameters).
        Returns: (is_consequential, reason, material_impact)
        """
        if isinstance(intent_or_action, Intent):
            intent = intent_or_action
            action = intent.action
            params = intent.parameters or {}
            target_str = str(intent.target or params.get("target") or params.get("application") or "").lower()
            cap_id = getattr(intent, "capability_id", "") or ""
            query = str(intent.query or params.get("command") or params.get("text") or "")
        else:
            action = intent_or_action
            params = parameters or {}
            target_str = str(target or params.get("target") or params.get("application") or "").lower()
            cap_id = str(params.get("capability_id") or "")
            query = str(params.get("command") or params.get("text") or params.get("query") or "")

        # 1. Direct explicit capability scope
        if cap_id and (cap_id.startswith("system.modification") or cap_id.startswith("system.credentials")):
            return (
                True,
                f"Action modifies sensitive system configuration: '{action}'",
                "May alter operating system settings or security credentials."
            )

        # 2. Destructive process termination
        is_close = action == SemanticAction.CLOSE or str(action).lower() in ("close", "close_application", "kill")
        if is_close and (params.get("force") or params.get("force_kill")):
            return (
                True,
                f"Force-terminating process for target '{target_str}'",
                "Will immediately kill the application process; unsaved changes will be permanently lost."
            )

        # 3. Text command analysis (for CLI / script executions)
        for pat in DESTRUCTIVE_COMMAND_PATTERNS:
            if pat.search(query):
                return (
                    True,
                    f"Command contains destructive system pattern: '{query.strip()[:60]}'",
                    "May delete files, terminate running processes, or modify system records."
                )

        # 4. File deletion or modification
        action_val = action.value if hasattr(action, "value") else str(action)
        if "delete" in action_val.lower() or "remove" in action_val.lower():
            return (
                True,
                f"Destructive file or resource operation on '{target_str}'",
                "The specified file or resource will be permanently removed."
            )

        return False, None, None

    @classmethod
    def evaluate_step(cls, step: CompositeStep) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Evaluates a CompositeStep.
        Returns: (is_consequential, reason, material_impact)
        """
        # Explicit metadata flag on the step
        if getattr(step, "consequential", False):
            reason = getattr(step, "description", None) or f"Consequential step {step.step_index}"
            return (
                True,
                f"Step marked consequential: '{reason}'",
                "This action has significant external or irreversible desktop effects."
            )

        # Explicit protected permission scope
        if step.required_permission in (
            CapabilityScope.SYSTEM_MODIFICATION,
            CapabilityScope.CREDENTIAL_ACCESS,
        ):
            return (
                True,
                f"Step requires elevated permission scope '{step.required_permission.value}'",
                "May modify system files, operating system state, or sensitive credentials."
            )

        # Evaluate underlying intent
        if step.intent:
            return cls.evaluate_intent(step.intent)

        return False, None, None

    @classmethod
    def create_confirmation_request(
        cls,
        step: CompositeStep,
        goal_id: Optional[str] = None,
        task_id: Optional[str] = None,
        step_index: Optional[int] = None,
    ) -> ClarificationRequest:
        """
        Constructs a structured ClarificationRequest for consequential-action confirmation.
        """
        _, reason, impact = cls.evaluate_step(step)
        target = step.target_app_name or (step.intent.target if step.intent else None) or "system"
        action_name = step.intent.action.value if step.intent else "ACTION"
        prompt = (
            f"ASTRA needs your confirmation to perform consequential action '{step.description}'. "
            f"Target: {target}. Impact: {impact or 'Irreversible external change'}. Proceed?"
        )

        options = [
            ClarificationOption(
                option_id="approve",
                label="Approve & Execute",
                value="true",
                description="Authorizes execution of this specific consequential action.",
                is_recommended=False,
            ),
            ClarificationOption(
                option_id="reject",
                label="Cancel Action",
                value="false",
                description="Rejects execution and safely cancels the task.",
                is_recommended=True,
            ),
        ]

        return ClarificationRequest(
            clarification_type=ClarificationType.CONSEQUENTIAL_ACTION,
            prompt=prompt,
            options=options,
            default_option_id="reject",
            goal_id=goal_id,
            task_id=task_id,
            step_index=step_index if step_index is not None else step.step_index,
            action_type=action_name,
            target_name=target,
            impact_description=impact,
            requires_explicit_confirmation=True,
            metadata={
                "step_id": step.step_id,
                "consequential_reason": reason,
                "required_permission": step.required_permission.value if step.required_permission else None,
            }
        )

consequential_action_policy = ConsequentialActionPolicy()

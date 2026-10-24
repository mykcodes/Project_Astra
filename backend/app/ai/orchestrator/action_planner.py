from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from app.ai.orchestrator.intent import NormalizedIntent, IntentDomain
from app.ai.capabilities.registry import capability_registry, CapabilityDef
from app.ai.context.engine import context_engine

@dataclass
class ActionPlanStep:
    tool_name: str
    arguments: Dict[str, Any]
    description: str

@dataclass
class ActionPlan:
    intent: NormalizedIntent
    capability: CapabilityDef
    steps: List[ActionPlanStep]
    
class ActionPlanner:
    """Maps intents to capabilities and tool execution plans."""
    
    def plan(self, intent: NormalizedIntent) -> ActionPlan:
        # Normalize Target
        if not intent.target:
            for key in ["application_name", "app_name", "target"]:
                if key in intent.parameters:
                    intent.target = intent.parameters.pop(key)
                    break
                    
        # Resolve target context (e.g., "it" -> "spotify")
        if intent.target:
            intent.target = context_engine.resolve_reference(intent.target)
            
        if intent.domain.value == "COMPOUND" or intent.action == "COMPOUND":
            return self._plan_compound(intent)
        elif intent.domain == IntentDomain.DESKTOP:
            return self._plan_desktop(intent)
        elif intent.domain == IntentDomain.SYSTEM:
            return self._plan_system(intent)
        elif intent.domain == IntentDomain.BROWSER:
            return self._plan_browser(intent)
        elif intent.domain == IntentDomain.FILESYSTEM:
            return self._plan_filesystem(intent)
        elif intent.domain == IntentDomain.INTERACTION:
            return self._plan_interaction(intent)
        else:
            raise ValueError(f"Unsupported intent domain: {intent.domain}")
            
    def _plan_compound(self, intent: NormalizedIntent) -> ActionPlan:
        steps = []
        cap = capability_registry.get("interaction.execute_intent") # Assuming fallback capability
        
        for sub_intent_dict in intent.parameters.get("sequence", []):
            sub_intent = NormalizedIntent(**sub_intent_dict)
            sub_plan = self.plan(sub_intent)
            steps.extend(sub_plan.steps)
            cap = sub_plan.capability # Use the last capability, or composite
                
        return ActionPlan(intent=intent, capability=cap, steps=steps)

    def _plan_interaction(self, intent: NormalizedIntent) -> ActionPlan:
        cap = capability_registry.get("interaction.execute_intent")
        args = {
            "action": intent.action,
            "application_name": intent.target,
        }
        if "target_ui_element" in intent.parameters:
            args["target_ui_element"] = intent.parameters["target_ui_element"]
        if "value" in intent.parameters:
            args["value"] = intent.parameters["value"]
            
        step = ActionPlanStep(
            tool_name="execute_interaction_intent",
            arguments=args,
            description=f"Executing {intent.action} interaction on {intent.target}"
        )
        return ActionPlan(intent=intent, capability=cap, steps=[step])
            
    def _plan_desktop(self, intent: NormalizedIntent) -> ActionPlan:
        capability = capability_registry.get("desktop.execute_intent")
        if not capability:
            raise RuntimeError("desktop.execute_intent capability not found in registry.")
            
        step = ActionPlanStep(
            tool_name="execute_application_intent",
            arguments={"intent": intent.action, "application": intent.target},
            description=f"Execute {intent.action} on {intent.target}"
        )
        return ActionPlan(intent=intent, capability=capability, steps=[step])
        
    def _plan_system(self, intent: NormalizedIntent) -> ActionPlan:
        capability = capability_registry.get("system.get_info")
        if not capability:
            raise RuntimeError("system.get_info capability not found in registry.")
            
        fields = intent.parameters.get("requested_fields", [])
        step = ActionPlanStep(
            tool_name="get_system_info",
            arguments={"sections": fields} if fields else {},
            description=f"Retrieve system information for sections: {fields}"
        )
        return ActionPlan(intent=intent, capability=capability, steps=[step])
        
    def _plan_browser(self, intent: NormalizedIntent) -> ActionPlan:
        capability = capability_registry.get("browser.open_url")
        if not capability:
            raise RuntimeError("browser.open_url capability not found in registry.")
            
        step = ActionPlanStep(
            tool_name="open_url",
            arguments={"url": intent.target},
            description=f"Open browser URL: {intent.target}"
        )
        return ActionPlan(intent=intent, capability=capability, steps=[step])
        
    def _plan_filesystem(self, intent: NormalizedIntent) -> ActionPlan:
        action = intent.action
        capability = None
        tool_name = ""
        arguments = {}
        
        if action == "list":
            capability = capability_registry.get("filesystem.list")
            tool_name = "list_directory"
            arguments = {"path": intent.target}
        elif action == "search":
            capability = capability_registry.get("filesystem.search")
            tool_name = "search_files"
            arguments = {"query": intent.parameters.get("query", ""), "path": intent.target}
        elif action == "create_folder":
            capability = capability_registry.get("filesystem.create_folder")
            tool_name = "create_folder"
            arguments = {"path": intent.target}
        else:
            raise ValueError(f"Unknown filesystem action: {action}")
            
        if not capability:
            raise RuntimeError(f"Capability for filesystem {action} not found.")
            
        step = ActionPlanStep(
            tool_name=tool_name,
            arguments=arguments,
            description=f"Execute filesystem {action} on {intent.target}"
        )
        return ActionPlan(intent=intent, capability=capability, steps=[step])

    def plan_composite_sequence(
        self,
        sequence_name: str,
        steps_def: List[Dict[str, Any]],
        timeout_seconds: float = 60.0,
        max_retries_per_step: int = 2,
        allow_compensation: bool = True,
    ):
        """
        Phase B.6: Compiles a multi-step sequence of semantic actions into an executable
        CompositeActionSequence with step IDs, indices, and optional safe compensation.
        """
        import uuid
        from app.domain.composite import (
            CompositeActionSequence,
            CompositeStep,
            CompensationAction,
        )
        from app.domain.goals import Intent, SemanticAction

        sequence_id = f"seq_{uuid.uuid4().hex[:8]}"
        composite_steps: List[CompositeStep] = []

        for idx, step_dict in enumerate(steps_def):
            action_raw = step_dict.get("action", "CLICK")
            if isinstance(action_raw, str):
                try:
                    action_enum = SemanticAction(action_raw.upper())
                except ValueError:
                    action_enum = SemanticAction.CLICK
            else:
                action_enum = action_raw

            intent = Intent(
                intent_id=step_dict.get("intent_id", str(uuid.uuid4())),
                action=action_enum,
                target=step_dict.get("target"),
                capability_id=step_dict.get("capability_id", "desktop.physical_input"),
                parameters=step_dict.get("parameters", {}),
            )

            compensation = None
            if "compensation" in step_dict and step_dict["compensation"]:
                comp_def = step_dict["compensation"]
                comp_action_raw = comp_def.get("action", "HOTKEY")
                try:
                    comp_action_enum = SemanticAction(comp_action_raw.upper())
                except ValueError:
                    comp_action_enum = SemanticAction.HOTKEY

                comp_intent = Intent(
                    intent_id=str(uuid.uuid4()),
                    action=comp_action_enum,
                    target=comp_def.get("target"),
                    capability_id=comp_def.get("capability_id", "desktop.physical_input"),
                )
                compensation = CompensationAction(
                    intent=comp_intent,
                    tool_args=comp_def.get("tool_args", {}),
                    description=comp_def.get("description", "Safe compensation action"),
                )

            comp_step = CompositeStep(
                step_id=step_dict.get("step_id", f"step_{idx}_{uuid.uuid4().hex[:6]}"),
                step_index=idx,
                intent=intent,
                tool_args=step_dict.get("tool_args", {}),
                description=step_dict.get("description", f"Step {idx}: {action_enum.value}"),
                consequential=step_dict.get("consequential", False),
                required_permission=step_dict.get("required_permission"),
                compensation=compensation,
                requires_verification=step_dict.get("requires_verification", False),
                verifier_type=step_dict.get("verifier_type"),
                verifier_args=step_dict.get("verifier_args", {}),
                settle_delay_seconds=step_dict.get("settle_delay_seconds", 0.3),
                target_app_name=step_dict.get("target_app_name"),
                target_window_title=step_dict.get("target_window_title"),
                target_hwnd=step_dict.get("target_hwnd"),
                ensure_foreground=step_dict.get("ensure_foreground", True),
            )
            composite_steps.append(comp_step)


        return CompositeActionSequence(
            sequence_id=sequence_id,
            name=sequence_name,
            steps=composite_steps,
            timeout_seconds=timeout_seconds,
            max_retries_per_step=max_retries_per_step,
            allow_compensation=allow_compensation,
        )

action_planner = ActionPlanner()

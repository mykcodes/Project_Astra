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
        # Resolve target context (e.g., "it" -> "spotify")
        if intent.target:
            intent.target = context_engine.resolve_reference(intent.target)
            
        if intent.domain == IntentDomain.DESKTOP:
            return self._plan_desktop(intent)
        elif intent.domain == IntentDomain.SYSTEM:
            return self._plan_system(intent)
        elif intent.domain == IntentDomain.BROWSER:
            return self._plan_browser(intent)
        elif intent.domain == IntentDomain.FILESYSTEM:
            return self._plan_filesystem(intent)
        elif intent.domain == IntentDomain.INTERACTION:
            return self._plan_interaction(intent)
        elif intent.domain.value == "COMPOUND" or intent.action == "COMPOUND":
            return self._plan_compound(intent)
        else:
            raise ValueError(f"Unsupported intent domain: {intent.domain}")
            
    def _plan_compound(self, intent: NormalizedIntent) -> ActionPlan:
        steps = []
        cap = capability_registry.get("interaction.execute_intent") # Assuming fallback capability
        
        for sub_intent_dict in intent.parameters.get("sequence", []):
            try:
                sub_intent = NormalizedIntent(**sub_intent_dict)
                sub_plan = self.plan(sub_intent)
                steps.extend(sub_plan.steps)
                cap = sub_plan.capability # Use the last capability, or composite
            except Exception as e:
                pass
                
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

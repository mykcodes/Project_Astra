import uuid
import copy
from app.domain.goals import Goal, Task, Intent, SemanticAction, TargetType, TargetOrdinal
from app.domain.execution_context import ExecutionContext
from app.core.logging.logger import get_logger

logger = get_logger(__name__)

class ActionCompiler:
    """
    ActionCompiler deterministic compilation layer (Phase 9B.3.1).
    Converts Semantic Intents from the LLM into executable semantic tasks,
    resolving references and injecting context before the GoalRuntime executes them.
    """
    
    async def compile(self, goal: Goal, context: ExecutionContext) -> Goal:
        compiled_goal = copy.deepcopy(goal)
        
        for task in compiled_goal.tasks:
            compiled_intents = []
            for intent in task.intents:
                compiled_intent = await self._compile_intent(intent, context)
                if compiled_intent:
                    compiled_intents.append(compiled_intent)
            
            task.intents = compiled_intents
            
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

        # Pronoun resolution
        if intent.target and intent.target.lower() in ("it", "that", "this", "them"):
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
            "action": intent.action.value,
            "target": intent.target,
            "target_type": intent.target_type.value,
            "ordinal": intent.ordinal.value,
            "query": intent.query,
            "browser": intent.browser,
            "page_context": intent.page_context,
        }
        
        return intent

    def _map_to_capability(self, intent: Intent) -> str:
        """
        Maps the semantic action and target type to a capability ID for the executor.
        """
        if intent.action == SemanticAction.OPEN:
            if intent.target_type == TargetType.WEBSITE or intent.target_type == TargetType.URL_OR_SITE:
                return "browser.navigate"
            return "desktop.open_application"
            
        elif intent.action == SemanticAction.FOCUS:
            return "desktop.focus_application"
            
        elif intent.action == SemanticAction.NAVIGATE:
            return "browser.navigate"
            
        elif intent.action == SemanticAction.SEARCH:
            if intent.target_type in (TargetType.APPLICATION, TargetType.UNKNOWN) and not intent.browser:
                # Desktop search or application search (heuristic fallback)
                return "browser.search" 
            return "browser.search"
            
        elif intent.action in (SemanticAction.PLAY, SemanticAction.PAUSE, SemanticAction.CLICK, SemanticAction.INPUT):
            return "browser.interact"
            
        return "system.generic"

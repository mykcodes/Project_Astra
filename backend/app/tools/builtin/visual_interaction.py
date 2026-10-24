"""
B.3.2 — ExecuteVisualInteractionTool

Tool registered in the ActionExecutor boundary that exposes visually-grounded
CLICK through the standard tool execution path.

Execution path:
    ActionExecutor → ToolExecutor → this tool → VisualInteractionService
        → capture → perception → selection → grounding → router → physical input

Does NOT call raw input drivers directly.
Does NOT bypass ActionExecutor.
Does NOT fabricate verification.
"""

from app.tools.base import Tool
from app.tools.schemas import ToolRisk
from app.tools.errors import ToolExecutionError
from app.domain.visual import VisualCaptureError, VisualPerceptionError
from app.environment.visual.interaction import (
    VisualInteractionService,
    VisualInteractionError,
)
from app.core.logging.logger import get_logger

logger = get_logger(__name__)


class ExecuteVisualInteractionTool(Tool):
    """
    Executes a visually-grounded CLICK on a semantic target.

    Requires a PerceptionProvider to be registered on the underlying
    VisualInteractionService. If no provider is registered, execution
    fails with a structured PERCEPTION_UNAVAILABLE error.

    Capabilities: Requires both visual observation (INTERACTION) and
    physical mouse input (PHYSICAL_INPUT) capabilities.
    """
    name = "execute_visual_interaction"
    description = (
        "Executes a visually-grounded CLICK on a semantic target identified by query. "
        "Captures a screenshot, runs visual perception to find the target, "
        "grounds it to physical screen coordinates, and clicks it via the "
        "existing physical-input path. "
        "Requires a registered PerceptionProvider. "
        "Only CLICK is supported."
    )
    risk = ToolRisk.CONTROLLED
    # Reuse existing capability identifiers from the registry.
    # INTERACTION covers visual observation capability.
    # PHYSICAL_INPUT covers physical mouse actuation.
    capabilities = ["INTERACTION", "PHYSICAL_INPUT"]
    schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Semantic description of the visual target to click (e.g., 'Play button', 'Settings icon')."
            },
            "min_confidence": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": "Minimum confidence threshold for target selection. Defaults to 0.5.",
                "default": 0.5
            },
            "target_bounds": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Optional bounding box [x, y, w, h] to scope visual target perception to a specific window or screen region."
            }
        },
        "required": ["query"],
        "additionalProperties": False
    }

    def __init__(self, service: VisualInteractionService | None = None):
        """
        Args:
            service: An explicitly provided VisualInteractionService instance.
                     If None, creates a default service (with no perception provider,
                     which will fail at execution time with PERCEPTION_UNAVAILABLE).
        """
        self._service = service or VisualInteractionService()

    @property
    def service(self) -> VisualInteractionService:
        return self._service

    async def execute(
        self,
        query: str,
        min_confidence: float = 0.5,
        target_bounds: list | None = None,
        **kwargs
    ) -> dict:
        """
        Execute visually-grounded CLICK.

        Returns a dict with:
            - success: bool — whether physical actuation was accepted
            - actuation_success: bool — same as success for clarity
            - verification: str — always "UNKNOWN" for generic clicks
            - provenance: dict — observation_id, target_id, screen_point, actuation_outcome
            - error: dict or None — structured error info if actuation failed

        Raises ToolExecutionError for unrecoverable pipeline failures.
        All VisualPerceptionError, VisualCaptureError, and VisualInteractionError
        are translated into structured dicts (not swallowed).
        """
        try:
            kwargs_to_pass = {
                "query": query,
                "min_confidence": min_confidence,
                "recheck_pre_actuation": True,
            }
            if target_bounds and len(target_bounds) == 4:
                kwargs_to_pass["target_bounds"] = (
                    int(target_bounds[0]),
                    int(target_bounds[1]),
                    int(target_bounds[2]),
                    int(target_bounds[3]),
                )

            result = await self._service.execute_click(**kwargs_to_pass)

            result_dict = result.to_dict()
            result_dict["success"] = result.actuation_success
            return result_dict

        except VisualInteractionError as e:
            logger.warning("VISUAL_INTERACTION_TOOL_ERROR", extra={
                "code": e.code, "error_message": e.message, "provenance": e.provenance
            })
            return {
                "success": False,
                "actuation_success": False,
                "verification": "UNKNOWN",
                "error": {"code": e.code, "message": e.message},
                "provenance": e.provenance,
            }

        except VisualPerceptionError as e:
            logger.warning("VISUAL_INTERACTION_TOOL_PERCEPTION_ERROR", extra={
                "code": e.code, "error_message": e.message
            })
            return {
                "success": False,
                "actuation_success": False,
                "verification": "UNKNOWN",
                "error": {"code": e.code, "message": e.message},
                "provenance": {},
            }

        except VisualCaptureError as e:
            logger.warning("VISUAL_INTERACTION_TOOL_CAPTURE_ERROR", extra={
                "code": e.code, "error_message": e.message
            })
            return {
                "success": False,
                "actuation_success": False,
                "verification": "UNKNOWN",
                "error": {"code": e.code, "message": e.message},
                "provenance": {},
            }

        except Exception as e:
            # Unexpected — let ToolExecutor catch and wrap this
            logger.error(f"Unexpected error in visual interaction tool: {e}")
            raise ToolExecutionError(
                f"Visual interaction failed unexpectedly: {e}"
            )

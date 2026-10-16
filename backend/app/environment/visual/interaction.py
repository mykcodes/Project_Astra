"""
B.3.2 — Visual Interaction Service

Orchestrates the complete path from a semantic visual query to physical CLICK actuation:

    PerceptionProvider.find_targets()
        → TargetSelectionService.select_target()
        → TargetGroundingService.ground()
        → InteractionRouter.route(CLICK, point=ScreenPoint)

Does NOT call raw input drivers directly.
Does NOT bypass ActionExecutor.
Does NOT fabricate verification.
"""

import uuid
from datetime import datetime
from typing import Any, Dict, Optional, Protocol, List, TYPE_CHECKING

from app.core.logging.logger import get_logger
from app.domain.entities import ScreenPoint, TriState
from app.domain.goals import SemanticAction
from app.domain.visual import (
    GroundedTarget,
    VisualCaptureError,
    VisualObservation,
    VisualPerceptionError,
    VisualTarget,
)
if TYPE_CHECKING:
    from app.environment.visual.capture import ScreenCaptureProvider
    from app.interaction.router import InteractionRouter
from app.environment.visual.grounding import target_grounding_service, TargetGroundingService
from app.environment.visual.perception import PerceptionProvider
from app.environment.visual.selection import target_selection_service, TargetSelectionService
from app.environment.visual.tracker import interaction_tracker

logger = get_logger(__name__)


class VisualInteractionError(Exception):
    """Structured error for visual interaction pipeline failures."""
    def __init__(self, code: str, message: str, provenance: Optional[Dict[str, Any]] = None):
        self.code = code
        self.message = message
        self.provenance = provenance or {}
        super().__init__(f"[{code}] {message}")


class VisualInteractionResult:
    """
    Structured result of a visual interaction attempt.

    Distinguishes:
    - actuation_success: Whether the physical mouse event was accepted by the OS.
    - verification: Whether the semantic intent was confirmed (always UNKNOWN for generic clicks).
    """
    def __init__(
        self,
        actuation_success: bool,
        verification: TriState,
        provenance: Dict[str, Any],
        error: Optional[Dict[str, Any]] = None,
    ):
        self.actuation_success = actuation_success
        self.verification = verification
        self.provenance = provenance
        self.error = error

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "actuation_success": self.actuation_success,
            "verification": self.verification.value if isinstance(self.verification, TriState) else str(self.verification),
            "provenance": self.provenance,
        }
        if self.error:
            result["error"] = self.error
        return result


class VisualInteractionService:
    """
    Bridges B.3.1 visual grounding to B.1 physical input via the existing interaction router.

    Requires an explicitly registered PerceptionProvider.
    Fails with structured errors when no provider is available.
    Supports only CLICK actuation.
    """

    def __init__(
        self,
        perception_provider: Optional[PerceptionProvider] = None,
        capture_provider: Optional[Any] = None,
        selection_service: Optional[TargetSelectionService] = None,
        grounding_service: Optional[TargetGroundingService] = None,
        router: Optional[Any] = None,
    ):
        self._perception_provider = perception_provider
        self._capture_provider = capture_provider
        self._selection_service = selection_service or target_selection_service
        self._grounding_service = grounding_service or target_grounding_service
        self._router = router

    @property
    def router(self) -> Any:
        if self._router is None:
            from app.interaction.router import interaction_router
            self._router = interaction_router
        return self._router

    @router.setter
    def router(self, r: Any):
        self._router = r

    @property
    def capture_provider(self) -> Any:
        if self._capture_provider is None:
            from app.environment.visual.capture import screen_capture_provider
            self._capture_provider = screen_capture_provider
        return self._capture_provider

    @capture_provider.setter
    def capture_provider(self, provider: Optional[Any]):
        self._capture_provider = provider

    @property
    def perception_provider(self) -> Optional[PerceptionProvider]:
        return self._perception_provider

    @perception_provider.setter
    def perception_provider(self, provider: Optional[PerceptionProvider]):
        self._perception_provider = provider

    def _require_perception_provider(self) -> PerceptionProvider:
        """Fail explicitly if no production perception provider is registered."""
        if self._perception_provider is None:
            raise VisualInteractionError(
                "PERCEPTION_UNAVAILABLE",
                "No perception provider is registered. "
                "B.3.1 established the PerceptionProvider contract but no production implementation exists. "
                "Register a provider before attempting visual interaction."
            )
        return self._perception_provider

    async def execute_click(
        self,
        query: str,
        min_confidence: float = 0.5,
        observation: Optional[VisualObservation] = None,
    ) -> VisualInteractionResult:
        """
        Execute a visually-grounded CLICK.

        Full execution path:
            1. Capture real B.2 VisualObservation (or use provided one)
            2. Invoke PerceptionProvider to find targets
            3. TargetSelectionService to select single target
            4. TargetGroundingService to ground to ScreenPoint
            5. Freshness validation (via mapper/tracker, already in grounding)
            6. Validate ScreenPoint before routing
            7. Route through existing B.1 physical-input path
            8. Record provenance and return structured result

        Returns VisualInteractionResult distinguishing actuation from verification.
        """
        provider = self._require_perception_provider()
        provenance: Dict[str, Any] = {}

        # -----------------------------------------------------------
        # STEP 1: Capture observation
        # -----------------------------------------------------------
        if observation is None:
            try:
                obs_id = f"vi_{uuid.uuid4().hex[:12]}"
                observation = self.capture_provider.capture_virtual_screen(obs_id)
            except VisualCaptureError:
                raise  # Let structured capture errors propagate
            except Exception as e:
                raise VisualInteractionError(
                    "CAPTURE_FAILED", f"Visual capture failed: {e}"
                )

        provenance["observation_id"] = observation.observation_id

        # -----------------------------------------------------------
        # STEP 2: Perception — find candidate targets
        # -----------------------------------------------------------
        try:
            candidates: List[VisualTarget] = provider.find_targets(observation, query)
        except Exception as e:
            raise VisualInteractionError(
                "PERCEPTION_FAILED",
                f"Perception provider raised an error: {e}",
                provenance=provenance,
            )

        # -----------------------------------------------------------
        # STEP 3: Selection — pick exactly one target
        # -----------------------------------------------------------
        # TargetSelectionService raises VisualPerceptionError for:
        #   TARGET_NOT_FOUND, TARGET_CONFIDENCE_TOO_LOW, TARGET_AMBIGUOUS
        selected: VisualTarget = self._selection_service.select_target(
            candidates, min_confidence=min_confidence
        )
        provenance["target_id"] = selected.target_id

        # -----------------------------------------------------------
        # STEP 4: Grounding — map to ScreenPoint
        # -----------------------------------------------------------
        # TargetGroundingService raises VisualPerceptionError for:
        #   TARGET_OBSERVATION_MISMATCH, INVALID_TARGET_GEOMETRY, GROUNDING_FAILED
        # It also propagates VisualCaptureError(STALE_OBSERVATION) from the mapper.
        grounded: GroundedTarget = self._grounding_service.ground(selected, observation)
        screen_point: ScreenPoint = grounded.anchor_point
        provenance["screen_point"] = {"x": screen_point.x, "y": screen_point.y}

        # -----------------------------------------------------------
        # STEP 5: Validate ScreenPoint before routing
        # -----------------------------------------------------------
        # ScreenPoint is a Pydantic model with int x, y — no NaN/Inf possible.
        # The router will validate bounds.
        # But we do a basic sanity check here as defense-in-depth.
        if not isinstance(screen_point.x, int) or not isinstance(screen_point.y, int):
            raise VisualInteractionError(
                "INVALID_SCREEN_POINT",
                f"ScreenPoint contains non-integer coordinates: ({screen_point.x}, {screen_point.y})",
                provenance=provenance,
            )

        # -----------------------------------------------------------
        # STEP 6: Route CLICK through existing B.1 physical-input path
        # -----------------------------------------------------------
        # The router calls interaction_tracker.record_interaction() BEFORE actuation.
        # This means the observation used for grounding is invalidated after actuation.
        # We do NOT treat the original screenshot as current world truth after this.
        try:
            router_result: Dict[str, Any] = await self.router.route(
                action=SemanticAction.CLICK.value,
                target_entity=None,
                hwnds=None,
                pids=None,
                point=screen_point,
            )
        except Exception as e:
            raise VisualInteractionError(
                "PHYSICAL_INPUT_FAILED",
                f"Physical input routing failed with exception: {e}",
                provenance=provenance,
            )

        # -----------------------------------------------------------
        # STEP 7: Interpret router result and build structured outcome
        # -----------------------------------------------------------
        actuation_success = router_result.get("success", False)

        if actuation_success:
            # Physical mouse event was accepted by the OS.
            # Semantic verification is UNKNOWN — we cannot generically confirm
            # that the intended UI element was actually clicked.
            verification = TriState.UNKNOWN
            error_info = None
        else:
            # Physical actuation failed — the OS rejected SendInput or
            # coordinates were out of bounds.
            verification = TriState.UNKNOWN
            error_info = router_result.get("error", {
                "code": "ACTUATION_FAILURE",
                "message": router_result.get("message", "Physical actuation failed.")
            })

        provenance["actuation_outcome"] = "SUCCESS" if actuation_success else "FAILURE"

        result = VisualInteractionResult(
            actuation_success=actuation_success,
            verification=verification,
            provenance=provenance,
            error=error_info,
        )

        logger.info("VISUAL_INTERACTION_COMPLETED", extra={
            "query": query,
            "actuation_success": actuation_success,
            "verification": verification.value,
            "target_id": provenance.get("target_id"),
            "screen_point": provenance.get("screen_point"),
        })

        return result

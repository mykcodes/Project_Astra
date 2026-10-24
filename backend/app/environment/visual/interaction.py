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
from typing import Any, Dict, Optional, Protocol, List, Tuple, TYPE_CHECKING

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
        target_tracker: Optional[Any] = None,
        observer: Optional[Any] = None,
    ):
        self._perception_provider = perception_provider
        self._capture_provider = capture_provider
        self._selection_service = selection_service or target_selection_service
        self._grounding_service = grounding_service or target_grounding_service
        self._router = router
        self._target_tracker = target_tracker
        self._observer = observer

    @property
    def target_tracker(self) -> Any:
        if self._target_tracker is None:
            from app.environment.visual.tracking import spatial_target_tracker
            self._target_tracker = spatial_target_tracker
        return self._target_tracker

    @property
    def observer(self) -> Any:
        if self._observer is None:
            from app.environment.visual.observer import desktop_observer
            self._observer = desktop_observer
        return self._observer

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
        target_bounds: Optional[Tuple[int, int, int, int]] = None,
        target: Optional[VisualTarget] = None,
        recheck_pre_actuation: bool = True,
    ) -> VisualInteractionResult:
        """
        Execute a visually-grounded CLICK.

        Full execution path:
            1. Capture real B.2 VisualObservation (or use provided one)
            2. Invoke PerceptionProvider to find targets
            3. TargetSelectionService to select single target (or use provided target)
            4. TargetGroundingService to ground to ScreenPoint
            5. Freshness validation (via mapper/tracker, already in grounding)
            5.5. Mandatory pre-actuation re-grounding and drift check
            6. Validate ScreenPoint before routing
            7. Route through existing B.1 physical-input path under observer mutual exclusion
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
        # STEP 2 & 3: Selection — pick exactly one target
        # -----------------------------------------------------------
        if target is not None:
            selected = target
        else:
            try:
                candidates: List[VisualTarget] = provider.find_targets(observation, query)
            except Exception as e:
                raise VisualInteractionError(
                    "PERCEPTION_FAILED",
                    f"Perception provider raised an error: {e}",
                    provenance=provenance,
                )

            selected = self._selection_service.select_target(
                candidates,
                min_confidence=min_confidence,
                target_bounds=target_bounds,
                query=query,
                virtual_offset=(observation.virtual_offset_x, observation.virtual_offset_y),
            )

        provenance["target_id"] = selected.target_id
        provenance["target_bbox"] = {
            "x": selected.bbox_x,
            "y": selected.bbox_y,
            "width": selected.bbox_width,
            "height": selected.bbox_height,
        }

        # -----------------------------------------------------------
        # STEP 4: Grounding — map to ScreenPoint
        # -----------------------------------------------------------
        grounded: GroundedTarget = self._grounding_service.ground(selected, observation)
        screen_point: ScreenPoint = grounded.anchor_point
        provenance["screen_point"] = {"x": screen_point.x, "y": screen_point.y}

        # -----------------------------------------------------------
        # STEP 5: Validate ScreenPoint before routing
        # -----------------------------------------------------------
        if not isinstance(screen_point.x, int) or not isinstance(screen_point.y, int):
            raise VisualInteractionError(
                "INVALID_SCREEN_POINT",
                f"ScreenPoint contains non-integer coordinates: ({screen_point.x}, {screen_point.y})",
                provenance=provenance,
            )

        # -----------------------------------------------------------
        # STEP 5.5: Mandatory Pre-actuation re-grounding
        # -----------------------------------------------------------
        if recheck_pre_actuation:
            try:
                fresh_obs_id = f"reground_{uuid.uuid4().hex[:12]}"
                fresh_obs = self.capture_provider.capture_virtual_screen(fresh_obs_id)

                # Extract candidates from fresh observation using provider if available
                candidates = None
                try:
                    if hasattr(provider, "find_targets"):
                        candidates = provider.find_targets(fresh_obs, selected.label)
                except Exception:
                    candidates = None

                grounded = self.target_tracker.re_ground_pre_actuation(grounded, fresh_obs, candidates=candidates)
                screen_point = grounded.anchor_point
                provenance["screen_point"] = {"x": screen_point.x, "y": screen_point.y}
                provenance["regrounded_observation_id"] = fresh_obs.observation_id
            except VisualPerceptionError as e:
                raise VisualInteractionError(
                    e.code,
                    f"Pre-actuation re-grounding rejected: {e.message}",
                    provenance=provenance,
                )
            except VisualCaptureError as e:
                raise VisualInteractionError(
                    "OBSERVATION_STALE",
                    f"Pre-actuation capture failed: {e.message}",
                    provenance=provenance,
                )
            except Exception as e:
                raise VisualInteractionError(
                    "PRE_ACTUATION_FAILED",
                    f"Pre-actuation verification failed: {e}",
                    provenance=provenance,
                )

        # Re-validate ScreenPoint after re-grounding
        if not isinstance(screen_point.x, int) or not isinstance(screen_point.y, int):
            raise VisualInteractionError(
                "INVALID_SCREEN_POINT",
                f"ScreenPoint contains non-integer coordinates: ({screen_point.x}, {screen_point.y})",
                provenance=provenance,
            )

        # -----------------------------------------------------------
        # STEP 6: Route CLICK through existing B.1 physical-input path
        # -----------------------------------------------------------
        if self.observer and hasattr(self.observer, "actuation_scope"):
            with self.observer.actuation_scope(settle_s=0.3):
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
        else:
            if self.observer:
                try:
                    self.observer.pause_actuation(0.3)
                except Exception:
                    pass
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
            verification = TriState.UNKNOWN
            error_info = None
        else:
            verification = TriState.UNKNOWN
            error_info = router_result.get("error", {
                "code": "ACTUATION_FAILURE",
                "message": router_result.get("message", "Physical actuation failed.")
            })

        provenance["actuation_outcome"] = "SUCCESS" if actuation_success else "FAILURE"
        if "diagnostics" in router_result:
            provenance["actuator_diagnostics"] = router_result["diagnostics"]

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

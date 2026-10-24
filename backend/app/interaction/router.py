import asyncio
from app.core.logging.logger import get_logger
from app.environment.models import ApplicationEntity
from app.tools.desktop.desktop_controller import desktop_controller
from app.interaction.input.mouse_controller import mouse_controller
from app.environment.visual.tracker import interaction_tracker
from app.domain.goals import SemanticAction
from app.domain.entities import ScreenPoint

logger = get_logger(__name__)

class InteractionRouter:
    """
    Routes semantic interactions to physical mechanisms.
    For Phase B.0, this routes solely to the DesktopController actuation primitives.
    """
    
    async def route(
        self,
        action: str,
        target_entity: ApplicationEntity = None,
        hwnds: list[int] = None,
        pids: list[int] = None,
        point: ScreenPoint = None,
        text: str = None,
        key: str = None,
        keys: list[str] = None,
        clicks: int = 0,
        delta_x: int = 0,
        delta_y: int = 0,
        end_point: ScreenPoint = None,
        button: str = "left",
        steps: int = 10,
        duration_ms: int = 250,
        **kwargs,
    ) -> dict:
        logger.info("INTERACTION_ROUTED", extra={
            "action": action,
            "target": target_entity.canonical_name if target_entity else (f"Point({point.x},{point.y})" if point else "None"),
            "mechanism": "DESKTOP" if target_entity else "PHYSICAL"
        })
        
        acted = False

        # Ensure observer pauses background cycles during physical input injection
        try:
            from app.environment.visual.observer import desktop_observer
            observer_scope = desktop_observer.actuation_scope(settle_s=0.15)
        except Exception:
            import contextlib
            observer_scope = contextlib.nullcontext()

        with observer_scope:
            if action == SemanticAction.MOVE_MOUSE.value and point:
                interaction_tracker.record_interaction()
                return mouse_controller.actuate_move(point)
            elif action == SemanticAction.CLICK.value and point:
                interaction_tracker.record_interaction()
                return mouse_controller.actuate_click(point)
            elif action == SemanticAction.DOUBLE_CLICK.value and point:
                interaction_tracker.record_interaction()
                return mouse_controller.actuate_double_click(point)
            elif action in ("RIGHT_CLICK", "CONTEXT_MENU") and point:
                interaction_tracker.record_interaction()
                return mouse_controller.actuate_right_click(point)
            elif action in ("SCROLL", "MOUSE_WHEEL"):
                interaction_tracker.record_interaction()
                return mouse_controller.actuate_scroll(
                    clicks=clicks,
                    delta_x=delta_x,
                    delta_y=delta_y,
                    point=point,
                )
            elif action in ("DRAG", "DRAG_AND_DROP"):
                interaction_tracker.record_interaction()
                if not point or not end_point:
                    return {
                        "success": False,
                        "error": {
                            "code": "INVALID_ARGUMENT",
                            "message": "DRAG action requires both start point ('point') and 'end_point'.",
                        },
                    }
                return mouse_controller.actuate_drag(
                    start_point=point,
                    end_point=end_point,
                    button=button,
                    steps=steps,
                    duration_ms=duration_ms,
                )
            elif action in ("ESCAPE", "DISMISS_MENU"):
                interaction_tracker.record_interaction()
                from app.interaction.input.keyboard_controller import keyboard_controller
                return keyboard_controller.actuate_escape()
            elif action == "ALT":
                interaction_tracker.record_interaction()
                from app.interaction.input.keyboard_controller import keyboard_controller
                return keyboard_controller.actuate_alt()
            elif action in (SemanticAction.INPUT.value, "TYPE_TEXT"):
                interaction_tracker.record_interaction()
                if point:
                    mouse_controller.actuate_click(point)
                    await asyncio.sleep(0.15)
                from app.interaction.input.keyboard_controller import keyboard_controller
                return keyboard_controller.type_text(text or "")
            elif action == "HOTKEY":
                interaction_tracker.record_interaction()
                from app.interaction.input.keyboard_controller import keyboard_controller
                return keyboard_controller.actuate_hotkey(keys or [])
            elif action == "PRESS_KEY":
                interaction_tracker.record_interaction()
                from app.interaction.input.keyboard_controller import keyboard_controller
                return keyboard_controller.actuate_special_key(key or "")
            
        if action == SemanticAction.OPEN.value:
            acted = desktop_controller.actuate_open(target_entity)
            if acted:
                # Give OS minimal time to spawn process
                await asyncio.sleep(1.0)
                
        elif action == SemanticAction.CLOSE.value:
            acted = desktop_controller.actuate_close(hwnds or [], pids or [])
            if acted:
                # Give OS minimal time to teardown
                await asyncio.sleep(1.0)
                
        elif action == SemanticAction.FOCUS.value:
            acted = desktop_controller.actuate_focus(hwnds or [])
            if acted:
                # Give OS minimal time to transition foreground
                await asyncio.sleep(0.5)
                
        else:
            logger.warning("UNSUPPORTED_INTERACTION_ACTION", extra={"action": action})
            return {"success": False, "reason": f"Unsupported interaction action: {action}"}
            
        return {
            "success": acted,
            "action": action,
            "target": target_entity.canonical_name if target_entity else None,
            "mechanism": "DESKTOP",
            "message": f"Actuation {'triggered' if acted else 'failed'} for {action}"
        }

interaction_router = InteractionRouter()

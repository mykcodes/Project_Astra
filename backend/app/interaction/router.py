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
    
    async def route(self, action: str, target_entity: ApplicationEntity = None, hwnds: list[int] = None, pids: list[int] = None, point: ScreenPoint = None) -> dict:
        logger.info("INTERACTION_ROUTED", extra={
            "action": action,
            "target": target_entity.canonical_name if target_entity else (f"Point({point.x},{point.y})" if point else "None"),
            "mechanism": "DESKTOP" if target_entity else "PHYSICAL"
        })
        
        acted = False
        
        if action == SemanticAction.MOVE_MOUSE.value and point:
            interaction_tracker.record_interaction()
            return mouse_controller.actuate_move(point)
        elif action == SemanticAction.CLICK.value and point:
            interaction_tracker.record_interaction()
            return mouse_controller.actuate_click(point)
        elif action == SemanticAction.DOUBLE_CLICK.value and point:
            interaction_tracker.record_interaction()
            return mouse_controller.actuate_double_click(point)
            
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

import time
import hashlib
import uuid
from typing import Dict, Any, List, Optional
from app.core.logging.logger import get_logger
from app.interaction.models import UIObservation, UIChange, UIElement, UIWindow, BoundingRectangle
from app.environment.window.manager import window_manager
from app.interaction.capability_manager import capability_manager

logger = get_logger(__name__)

# Only import uiautomation on Windows
try:
    import uiautomation as auto
    HAS_UIA = True
except ImportError:
    HAS_UIA = False

class ObservationEngine:
    def __init__(self):
        self._current_observation: Optional[UIObservation] = None
        self._previous_observation: Optional[UIObservation] = None
        self.last_discovery_latency: float = 0.0

    def _hash_state(self, elements: Dict[str, UIElement], window_bounds: Optional[BoundingRectangle], foreground_hwnd: int) -> str:
        """Generates a deterministic hash of the current UI state."""
        h = hashlib.sha256()
        h.update(str(foreground_hwnd).encode())
        if window_bounds:
            h.update(f"{window_bounds.left},{window_bounds.top},{window_bounds.right},{window_bounds.bottom}".encode())
            
        for key in sorted(elements.keys()):
            el = elements[key]
            # Use safe identifying properties for hashing
            el_str = f"{el.automation_id}|{el.name}|{el.control_type}|{el.state.enabled}|{el.state.visible}|{el.state.focused}|{el.state.value}"
            h.update(el_str.encode())
            
        return h.hexdigest()

    def _create_bounding_rect(self, rect) -> Optional[BoundingRectangle]:
        if not rect:
            return None
        try:
            return BoundingRectangle(
                left=rect.left,
                top=rect.top,
                right=rect.right,
                bottom=rect.bottom
            )
        except AttributeError:
            return None

    def _extract_patterns(self, control) -> List[str]:
        patterns = []
        try:
            if hasattr(control, 'InvokePattern') and control.InvokePattern: patterns.append("Invoke")
            if hasattr(control, 'ValuePattern') and control.ValuePattern: patterns.append("Value")
            if hasattr(control, 'SelectionItemPattern') and control.SelectionItemPattern: patterns.append("SelectionItem")
            if hasattr(control, 'TogglePattern') and control.TogglePattern: patterns.append("Toggle")
            if hasattr(control, 'ExpandCollapsePattern') and control.ExpandCollapsePattern: patterns.append("ExpandCollapse")
            if hasattr(control, 'ScrollPattern') and control.ScrollPattern: patterns.append("Scroll")
            if hasattr(control, 'WindowPattern') and control.WindowPattern: patterns.append("Window")
        except Exception:
            pass
        return patterns

    def _map_control_to_element(self, control, runtime_id: str, parent_id: Optional[str] = None) -> UIElement:
        def safe_get(attr, default):
            try:
                return getattr(control, attr)
            except Exception:
                return default

        el = UIElement(
            runtime_id=runtime_id,
            name=safe_get("Name", ""),
            control_type=safe_get("ControlTypeName", "Unknown"),
            automation_id=safe_get("AutomationId", ""),
            class_name=safe_get("ClassName", ""),
            framework_id=safe_get("FrameworkId", ""),
            process_id=safe_get("ProcessId", 0),
            window_handle=safe_get("NativeWindowHandle", 0),
            parent_id=parent_id,
            bounding_rectangle=self._create_bounding_rect(safe_get("BoundingRectangle", None)),
            supported_patterns=self._extract_patterns(control)
        )
        
        # Populate dynamic state
        el.state.enabled = safe_get("IsEnabled", True)
        el.state.visible = safe_get("IsOffscreen", False) is False
        el.state.focused = safe_get("HasKeyboardFocus", False)
        el.state.selected = safe_get("IsSelected", False) if hasattr(control, "IsSelected") else False
        
        if "Value" in el.supported_patterns:
            try:
                val = control.ValuePattern.Value
                el.state.value_available = True
                el.state.value = val
            except Exception:
                pass
                
        return el

    def discover_ui_tree(self, hwnd: int, max_depth: int = 5, force_refresh: bool = False) -> List[UIElement]:
        """Legacy wrapper for compatibility during transition"""
        obs = self.observe_window(hwnd, max_depth, force_refresh)
        return list(obs.elements.values())

    def check_capability(self, hwnd: int) -> Dict[str, Any]:
        """Legacy wrapper for CapabilityManager"""
        return capability_manager.inspect_window(hwnd)

    def invalidate_cache(self, hwnd: Optional[int] = None):
        """Legacy invalidator"""
        self.invalidate_observation()

    def observe_window(self, hwnd: int, max_depth: int = 5, force: bool = False) -> UIObservation:
        """Creates a fresh canonical observation of a specific window."""
        now = time.time()
        
        # Return cached if still extremely fresh and valid, unless forced
        if not force and self._current_observation and self._current_observation.valid:
            if self._current_observation.window and self._current_observation.window.hwnd == hwnd:
                if now - self._current_observation.timestamp < 1.0:
                    return self._current_observation

        fg_window = window_manager.get_foreground_window()
        fg_hwnd = fg_window.hwnd if fg_window else 0
        
        obs = UIObservation(timestamp=now, foreground_hwnd=fg_hwnd)
        
        # Build Window structure
        window_entity = next((w for w in window_manager.get_windows_for_pids([]) if w.hwnd == hwnd), None)
        if not window_entity and fg_window and fg_window.hwnd == hwnd:
            window_entity = fg_window
            
        if not window_entity:
            # Fallback basic window info
            obs.window = UIWindow(
                hwnd=hwnd, process_id=0, application_identity="", framework="", title="", role="", 
                bounds=None, monitor=0, z_order=0, is_main_window=False, is_modal=False, is_popup=False,
                is_minimized=False, is_maximized=False, is_foreground=(hwnd == fg_hwnd)
            )
        else:
            obs.window = UIWindow(
                hwnd=hwnd, 
                process_id=window_entity.pid,
                application_identity=window_entity.process_name or "",
                framework="", # Will be filled by capability manager
                title=window_entity.title,
                role="Window",
                bounds=BoundingRectangle(window_entity.x, window_entity.y, window_entity.x + window_entity.width, window_entity.y + window_entity.height),
                monitor=window_entity.monitor,
                z_order=0,
                is_main_window=True, # Heuristic placeholder
                is_modal=False,
                is_popup=False,
                is_minimized=window_entity.minimized,
                is_maximized=window_entity.fullscreen,
                is_foreground=window_entity.foreground
            )
            
        # Discover capabilities & framework
        cap = capability_manager.inspect_window(hwnd)
        obs.window.framework = cap.get("framework_id", "")
        
        if not HAS_UIA or cap["status"] == "UI_AUTOMATION_UNAVAILABLE":
            obs.state_hash = self._hash_state(obs.elements, obs.window.bounds, obs.foreground_hwnd)
            self._update_observations(obs)
            return obs

        try:
            window_ctrl = auto.WindowControl(searchDepth=1, Handle=hwnd)
            if not window_ctrl.Exists(0.5):
                obs.state_hash = self._hash_state(obs.elements, obs.window.bounds, obs.foreground_hwnd)
                self._update_observations(obs)
                return obs

            elements_dict: Dict[str, UIElement] = {}
            id_counter = 0
            
            def traverse(control, parent_id, depth):
                nonlocal id_counter
                if depth > max_depth:
                    return
                try:
                    children = control.GetChildren()
                except Exception:
                    children = []
                    
                child_ids = []
                for child in children:
                    id_counter += 1
                    runtime_id = f"el_{id_counter}"
                    element = self._map_control_to_element(child, runtime_id, parent_id=parent_id)
                    child_ids.append(runtime_id)
                    elements_dict[runtime_id] = element
                    
                    traverse(child, runtime_id, depth + 1)
                    
                if parent_id and parent_id in elements_dict:
                    elements_dict[parent_id].children_ids = child_ids

            traverse(window_ctrl, None, 1)
            
            obs.elements = elements_dict
            latency = time.time() - now
            self.last_discovery_latency = latency
            
        except Exception as e:
            logger.error(f"UI Tree discovery failed for {hwnd}: {e}")

        obs.state_hash = self._hash_state(obs.elements, obs.window.bounds, obs.foreground_hwnd)
        self._update_observations(obs)
        return obs

    def _update_observations(self, new_obs: UIObservation):
        self._previous_observation = self._current_observation
        self._current_observation = new_obs

    def invalidate_observation(self):
        if self._current_observation:
            self._current_observation.valid = False

    def compare_state(self, before: UIObservation, after: UIObservation) -> List[UIChange]:
        """Compares two observations and yields semantic UIChange events."""
        changes = []
        
        if not before or not after:
            return changes
            
        # 1. Check foreground window change
        if before.foreground_hwnd != after.foreground_hwnd:
            changes.append(UIChange(
                change_type="FOREGROUND_CHANGED",
                old_value=before.foreground_hwnd,
                new_value=after.foreground_hwnd,
                description=f"Foreground window changed from {before.foreground_hwnd} to {after.foreground_hwnd}"
            ))
            
        # 2. If it's the same window, compare elements
        if before.window and after.window and before.window.hwnd == after.window.hwnd:
            before_els = before.elements
            after_els = after.elements
            
            def get_identity(el: UIElement):
                return f"{el.automation_id}|{el.control_type}|{el.name}"
                
            b_map = {get_identity(e): e for e in before_els.values()}
            a_map = {get_identity(e): e for e in after_els.values()}
            
            for identity, a_el in a_map.items():
                if identity in b_map:
                    b_el = b_map[identity]
                    if not b_el.state.focused and a_el.state.focused:
                        changes.append(UIChange(change_type="FOCUS_GAINED", element_id=a_el.runtime_id, description=f"Element {a_el.name} gained focus"))
                    if b_el.state.value != a_el.state.value:
                        changes.append(UIChange(
                            change_type="VALUE_CHANGED", 
                            element_id=a_el.runtime_id, 
                            old_value=b_el.state.value, 
                            new_value=a_el.state.value, 
                            description=f"Element {a_el.name} value changed"
                        ))
                    if len(b_el.children_ids) < len(a_el.children_ids):
                        changes.append(UIChange(change_type="CHILDREN_ADDED", element_id=a_el.runtime_id, description=f"Element {a_el.name} gained children"))
                else:
                    changes.append(UIChange(change_type="CONTROL_APPEARED", element_id=a_el.runtime_id, description=f"New element {a_el.name} appeared"))
                    
        return changes

ui_engine = ObservationEngine()

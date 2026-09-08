from enum import Enum
from typing import Any, Dict, List, Optional
from datetime import datetime
from pydantic import BaseModel, Field
from app.domain.entities import WorldState, TriState

class WorldStateChangeType(str, Enum):
    APPLICATION_OPENED = "APPLICATION_OPENED"
    APPLICATION_CLOSED = "APPLICATION_CLOSED"
    WINDOW_OPENED = "WINDOW_OPENED"
    WINDOW_CLOSED = "WINDOW_CLOSED"
    FOREGROUND_CHANGED = "FOREGROUND_CHANGED"
    WINDOW_MINIMIZED = "WINDOW_MINIMIZED"
    WINDOW_RESTORED = "WINDOW_RESTORED"
    WINDOW_MAXIMIZED = "WINDOW_MAXIMIZED"
    WINDOW_MOVED = "WINDOW_MOVED"
    WINDOW_RESIZED = "WINDOW_RESIZED"
    TITLE_CHANGED = "TITLE_CHANGED"
    PROCESS_DISAPPEARED = "PROCESS_DISAPPEARED"
    APPLICATION_UNRESPONSIVE = "APPLICATION_UNRESPONSIVE"

class WorldStateChange(BaseModel):
    change_type: WorldStateChangeType
    entity_id: str
    entity_type: str
    old_value: Any = None
    new_value: Any = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class WorldStateDiff(BaseModel):
    previous_timestamp: datetime
    current_timestamp: datetime
    changes: List[WorldStateChange] = Field(default_factory=list)

def compute_diff(previous: WorldState, current: WorldState) -> WorldStateDiff:
    """Computes a deterministic diff between two WorldState snapshots."""
    changes = []
    
    # 1. Applications
    prev_apps = {a.identity.canonical_name: a for a in previous.applications}
    curr_apps = {a.identity.canonical_name: a for a in current.applications}
    
    for app_name, curr_app in curr_apps.items():
        if app_name not in prev_apps:
            changes.append(WorldStateChange(
                change_type=WorldStateChangeType.APPLICATION_OPENED,
                entity_id=app_name,
                entity_type="Application",
                new_value=curr_app.running
            ))
        else:
            prev_app = prev_apps[app_name]
            if prev_app.running == TriState.FALSE and curr_app.running == TriState.TRUE:
                changes.append(WorldStateChange(
                    change_type=WorldStateChangeType.APPLICATION_OPENED,
                    entity_id=app_name,
                    entity_type="Application",
                    old_value=prev_app.running,
                    new_value=curr_app.running
                ))
            elif prev_app.responsive == TriState.TRUE and curr_app.responsive == TriState.FALSE:
                changes.append(WorldStateChange(
                    change_type=WorldStateChangeType.APPLICATION_UNRESPONSIVE,
                    entity_id=app_name,
                    entity_type="Application"
                ))

    for app_name, prev_app in prev_apps.items():
        if app_name not in curr_apps or curr_apps[app_name].running == TriState.FALSE:
            if prev_app.running == TriState.TRUE:
                changes.append(WorldStateChange(
                    change_type=WorldStateChangeType.APPLICATION_CLOSED,
                    entity_id=app_name,
                    entity_type="Application",
                    old_value=prev_app.running,
                    new_value=TriState.FALSE
                ))

    # 2. Windows
    prev_windows = {w.handle: w for w in previous.windows}
    curr_windows = {w.handle: w for w in current.windows}

    for hwnd, curr_win in curr_windows.items():
        if hwnd not in prev_windows:
            changes.append(WorldStateChange(
                change_type=WorldStateChangeType.WINDOW_OPENED,
                entity_id=str(hwnd),
                entity_type="Window",
                new_value=curr_win.title
            ))
        else:
            prev_win = prev_windows[hwnd]
            if prev_win.title != curr_win.title:
                changes.append(WorldStateChange(
                    change_type=WorldStateChangeType.TITLE_CHANGED,
                    entity_id=str(hwnd),
                    entity_type="Window",
                    old_value=prev_win.title,
                    new_value=curr_win.title
                ))
            if prev_win.minimized == TriState.FALSE and curr_win.minimized == TriState.TRUE:
                changes.append(WorldStateChange(
                    change_type=WorldStateChangeType.WINDOW_MINIMIZED,
                    entity_id=str(hwnd),
                    entity_type="Window"
                ))
            elif prev_win.minimized == TriState.TRUE and curr_win.minimized == TriState.FALSE:
                changes.append(WorldStateChange(
                    change_type=WorldStateChangeType.WINDOW_RESTORED,
                    entity_id=str(hwnd),
                    entity_type="Window"
                ))
            if prev_win.maximized == TriState.FALSE and curr_win.maximized == TriState.TRUE:
                changes.append(WorldStateChange(
                    change_type=WorldStateChangeType.WINDOW_MAXIMIZED,
                    entity_id=str(hwnd),
                    entity_type="Window"
                ))
            if prev_win.bounds and curr_win.bounds:
                if prev_win.bounds.x != curr_win.bounds.x or prev_win.bounds.y != curr_win.bounds.y:
                    changes.append(WorldStateChange(
                        change_type=WorldStateChangeType.WINDOW_MOVED,
                        entity_id=str(hwnd),
                        entity_type="Window",
                        old_value={"x": prev_win.bounds.x, "y": prev_win.bounds.y},
                        new_value={"x": curr_win.bounds.x, "y": curr_win.bounds.y}
                    ))
                if prev_win.bounds.width != curr_win.bounds.width or prev_win.bounds.height != curr_win.bounds.height:
                    changes.append(WorldStateChange(
                        change_type=WorldStateChangeType.WINDOW_RESIZED,
                        entity_id=str(hwnd),
                        entity_type="Window",
                        old_value={"width": prev_win.bounds.width, "height": prev_win.bounds.height},
                        new_value={"width": curr_win.bounds.width, "height": curr_win.bounds.height}
                    ))

    for hwnd, prev_win in prev_windows.items():
        if hwnd not in curr_windows:
            changes.append(WorldStateChange(
                change_type=WorldStateChangeType.WINDOW_CLOSED,
                entity_id=str(hwnd),
                entity_type="Window",
                old_value=prev_win.title
            ))

    # 3. Foreground
    prev_fg = previous.foreground.handle if previous.foreground else None
    curr_fg = current.foreground.handle if current.foreground else None
    
    if prev_fg != curr_fg:
        changes.append(WorldStateChange(
            change_type=WorldStateChangeType.FOREGROUND_CHANGED,
            entity_id=str(curr_fg) if curr_fg else "None",
            entity_type="System",
            old_value=str(prev_fg) if prev_fg else "None",
            new_value=str(curr_fg) if curr_fg else "None"
        ))

    return WorldStateDiff(
        previous_timestamp=previous.observation.timestamp,
        current_timestamp=current.observation.timestamp,
        changes=changes
    )

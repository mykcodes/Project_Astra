import pytest
from unittest.mock import patch, MagicMock
from app.ai.orchestrator.action_executor import action_executor
from app.domain.goals import Intent, SemanticAction, TargetType, TargetOrdinal
from app.domain.entities import TriState

@pytest.fixture
def mock_dependencies():
    with patch("app.tools.registry.registry.resolve_capability", return_value="execute_physical_input"), \
         patch("app.ai.orchestrator.action_executor.executor.execute") as mock_execute:
        yield mock_execute

@pytest.mark.asyncio
async def test_physical_input_integration_move(mock_dependencies):
    mock_execute = mock_dependencies
    mock_execute.return_value = MagicMock(
        success=True, 
        result='{"success": true, "action": "MOVE_MOUSE", "verified": "TRUE"}'
    )
    
    intent = Intent(
        intent_id="physical-1",
        action=SemanticAction.MOVE_MOUSE,
        target="Point(100,200)",
        target_type=TargetType.COORDINATE,
        ordinal=TargetOrdinal.NONE,
        capability_id="desktop.physical_input"
    )
    
    result = await action_executor.execute_intent(intent, {"intent": "MOVE_MOUSE", "x": 100, "y": 200})
    
    assert result["success"] is True
    assert result["verified"] == TriState.TRUE
    assert result["verification_result"].verified == TriState.TRUE
    assert result["verification_result"].expected_state == "Physical Actuation"
    assert result["verification_result"].actual_state == "TRUE"

@pytest.mark.asyncio
async def test_physical_input_integration_click(mock_dependencies):
    mock_execute = mock_dependencies
    mock_execute.return_value = MagicMock(
        success=True, 
        result='{"success": true, "action": "CLICK", "verified": "UNKNOWN"}'
    )
    
    intent = Intent(
        intent_id="physical-2",
        action=SemanticAction.CLICK,
        target="Point(100,200)",
        target_type=TargetType.COORDINATE,
        ordinal=TargetOrdinal.NONE,
        capability_id="desktop.physical_input"
    )
    
    result = await action_executor.execute_intent(intent, {"intent": "CLICK", "x": 100, "y": 200})
    
    assert result["success"] is True
    assert result["verified"] == TriState.UNKNOWN
    assert result["verification_result"].verified == TriState.UNKNOWN
    assert result["verification_result"].actual_state == "UNKNOWN"

@pytest.mark.asyncio
async def test_physical_input_integration_out_of_bounds(mock_dependencies):
    mock_execute = mock_dependencies
    mock_execute.return_value = MagicMock(
        success=True, 
        result='{"success": false, "error": {"code": "OUT_OF_BOUNDS", "message": "Coordinate (-9999, -9999) falls outside known display topology."}}'
    )
    
    intent = Intent(
        intent_id="physical-3",
        action=SemanticAction.MOVE_MOUSE,
        target="Point(-9999,-9999)",
        target_type=TargetType.COORDINATE,
        ordinal=TargetOrdinal.NONE,
        capability_id="desktop.physical_input"
    )
    
    result = await action_executor.execute_intent(intent, {"intent": "MOVE_MOUSE", "x": -9999, "y": -9999})
    
    assert result["success"] is False
    assert result["verified"] == TriState.FALSE
    assert result["error"]["code"] == "OUT_OF_BOUNDS"

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.ai.orchestrator.action_executor import action_executor
from app.domain.entities import TriState
from app.domain.goals import Intent, SemanticAction, TargetType, TargetOrdinal, FailureClass

@pytest.fixture
def mock_world_state_running():
    mock_app = MagicMock()
    mock_app.identity.canonical_name = "Notepad"
    mock_app.running = "TRUE" # Matches TriState.TRUE in the simple comparison
    
    mock_world = MagicMock()
    mock_world.applications = [mock_app]
    mock_world.foreground.owner_application = "Notepad"
    return mock_world

@pytest.fixture
def mock_world_state_closed():
    mock_world = MagicMock()
    mock_world.applications = []
    mock_world.foreground = None
    return mock_world

@pytest.mark.asyncio
async def test_interaction_execution_success(mock_world_state_closed, mock_world_state_running):
    # Actuate open
    intent = Intent(
        intent_id="123",
        action=SemanticAction.OPEN,
        target="Notepad",
        target_type=TargetType.APPLICATION,
        ordinal=TargetOrdinal.NONE,
        capability_id="interaction.open_application"
    )
    
    with patch("app.tools.registry.registry.resolve_capability", return_value="execute_application_intent"), \
         patch("app.ai.orchestrator.action_executor.executor.execute") as mock_execute, \
         patch("app.environment.awareness.get_awareness_provider") as mock_get_provider:
         
        mock_provider_instance = MagicMock()
        # First observation: closed. Second observation: running.
        mock_provider_instance.observe_world_state.side_effect = [mock_world_state_closed, mock_world_state_running]
        mock_get_provider.return_value = mock_provider_instance
        
        # Mock Tool execution (the Router)
        mock_tool_result = MagicMock()
        mock_tool_result.success = True
        mock_tool_result.result = '{"success": true, "canonical_name": "Notepad"}'
        mock_execute.return_value = mock_tool_result
        
        result = await action_executor.execute_intent(intent, {"intent": "OPEN", "application": "Notepad"})
        
        assert result["success"] is True
        assert result["verified"] == TriState.TRUE
        assert result["verification_result"].verified == TriState.TRUE
        assert result["verification_result"].expected_state == "Running"
        assert result["verification_result"].actual_state == "Running"
        assert mock_provider_instance.observe_world_state.call_count == 2

@pytest.mark.asyncio
async def test_interaction_execution_physical_success_but_verification_fails(mock_world_state_closed):
    # Actuate open, but WorldState says it's still closed (process died immediately)
    intent = Intent(
        intent_id="124",
        action=SemanticAction.OPEN,
        target="Notepad",
        target_type=TargetType.APPLICATION,
        ordinal=TargetOrdinal.NONE,
        capability_id="interaction.open_application"
    )
    
    with patch("app.tools.registry.registry.resolve_capability", return_value="execute_application_intent"), \
         patch("app.ai.orchestrator.action_executor.executor.execute") as mock_execute, \
         patch("app.environment.awareness.get_awareness_provider") as mock_get_provider:
         
        mock_provider_instance = MagicMock()
        # Both before and after say closed
        mock_provider_instance.observe_world_state.side_effect = [mock_world_state_closed, mock_world_state_closed]
        mock_get_provider.return_value = mock_provider_instance
        
        # Mock Tool execution indicating physical actuation SUCCESS
        mock_tool_result = MagicMock()
        mock_tool_result.success = True
        mock_tool_result.result = '{"success": true, "canonical_name": "Notepad"}'
        mock_execute.return_value = mock_tool_result
        
        result = await action_executor.execute_intent(intent, {"intent": "OPEN", "application": "Notepad"})
        
        # Verification should fail even though tool/physical actuation succeeded!
        assert result["success"] is False
        assert result["verified"] == TriState.FALSE
        assert result["error"]["code"] == FailureClass.VERIFICATION_FAILED.name

@pytest.mark.asyncio
async def test_foreground_identity_match(mock_world_state_closed):
    # Regression test specifically reproducing:
    # target = "notepad"
    # foreground raw process = "Notepad.exe"
    # expected verification = PASS
    
    mock_app = MagicMock()
    mock_app.identity.canonical_name = "notepad"
    mock_app.running = "TRUE"
    
    mock_world_focused = MagicMock()
    mock_world_focused.applications = [mock_app]
    
    mock_fg = MagicMock()
    # The provider is expected to canonicalize the owner_application to "notepad",
    # but let's test that if the world state returns "notepad", verification passes.
    mock_fg.owner_application = "notepad" 
    mock_fg.process_name = "Notepad.exe"
    mock_world_focused.foreground = mock_fg

    intent = Intent(
        intent_id="125",
        action=SemanticAction.FOCUS,
        target="notepad",
        target_type=TargetType.APPLICATION,
        ordinal=TargetOrdinal.NONE,
        capability_id="interaction.focus_application" # Maps to desktop.focus_application via registry eventually
    )
    
    with patch("app.tools.registry.registry.resolve_capability", return_value="execute_application_intent"), \
         patch("app.ai.orchestrator.action_executor.executor.execute") as mock_execute, \
         patch("app.environment.awareness.get_awareness_provider") as mock_get_provider:
         
        mock_provider_instance = MagicMock()
        mock_provider_instance.observe_world_state.side_effect = [mock_world_state_closed, mock_world_focused]
        mock_get_provider.return_value = mock_provider_instance
        
        mock_tool_result = MagicMock()
        mock_tool_result.success = True
        mock_tool_result.result = '{"success": true, "canonical_name": "notepad"}'
        mock_execute.return_value = mock_tool_result
        
        result = await action_executor.execute_intent(intent, {"intent": "FOCUS", "application": "notepad"})
        
        assert result["success"] is True
        assert result["verified"] == TriState.TRUE
        assert result["verification_result"].verified == TriState.TRUE

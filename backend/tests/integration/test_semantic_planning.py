import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

from app.domain.goals import Goal, Task, Intent, SemanticAction, TargetType, TargetOrdinal, TaskState, GoalState
from app.domain.execution_context import ExecutionContext
from app.ai.orchestrator.compiler import ActionCompiler
from app.ai.orchestrator.runtime import GoalRuntime

@pytest.fixture
def empty_context():
    return ExecutionContext(execution_id="test-exec-1")

@pytest.fixture
def populated_context():
    ctx = ExecutionContext(execution_id="test-exec-2")
    ctx.active_browser_identity = "chrome"
    ctx.current_url = "https://www.youtube.com"
    ctx.last_intent = Intent(
        intent_id="prev-1",
        action=SemanticAction.SEARCH,
        target="Baby",
        target_type=TargetType.UNKNOWN
    )
    ctx.retryable_intent = ctx.last_intent
    return ctx

@pytest.mark.asyncio
async def test_compiler_resolves_browser_context(populated_context):
    compiler = ActionCompiler()
    goal = Goal(
        goal_id="g1",
        objective="Search for Baby",
        tasks=[
            Task(
                task_id="t1",
                description="search",
                intents=[
                    Intent(
                        intent_id="i1",
                        action=SemanticAction.SEARCH,
                        target="Baby",
                        target_type=TargetType.UNKNOWN
                    )
                ]
            )
        ]
    )
    
    compiled = await compiler.compile(goal, populated_context)
    compiled_intent = compiled.tasks[0].intents[0]
    
    assert compiled_intent.browser == "chrome"
    assert compiled_intent.capability_id == "browser.search"
    assert compiled_intent.parameters["browser"] == "chrome"
    
@pytest.mark.asyncio
async def test_compiler_resolves_pronoun(populated_context):
    compiler = ActionCompiler()
    goal = Goal(
        goal_id="g1",
        objective="Play it",
        tasks=[
            Task(
                task_id="t1",
                description="play",
                intents=[
                    Intent(
                        intent_id="i1",
                        action=SemanticAction.PLAY,
                        target="it",
                        target_type=TargetType.UNKNOWN
                    )
                ]
            )
        ]
    )
    
    compiled = await compiler.compile(goal, populated_context)
    compiled_intent = compiled.tasks[0].intents[0]
    
    # "it" should resolve to "Baby" from last_intent
    assert compiled_intent.target == "Baby"
    assert compiled_intent.capability_id == "browser.interact"
    
@pytest.mark.asyncio
async def test_compiler_resolves_repeat(populated_context):
    compiler = ActionCompiler()
    goal = Goal(
        goal_id="g1",
        objective="Do it again",
        tasks=[
            Task(
                task_id="t1",
                description="repeat",
                intents=[
                    Intent(
                        intent_id="i1",
                        action=SemanticAction.REPEAT,
                    )
                ]
            )
        ]
    )
    
    compiled = await compiler.compile(goal, populated_context)
    compiled_intent = compiled.tasks[0].intents[0]
    
    assert compiled_intent.action == SemanticAction.SEARCH
    assert compiled_intent.target == "Baby"

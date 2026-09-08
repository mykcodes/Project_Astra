import asyncio
import json
import uuid
from app.ai.providers import get_default_provider
from app.ai.providers.types import AIRequest, AIMessage, MessageRole, ToolCall
from app.ai.orchestrator.session import ConversationSession
from app.domain.goals import Goal, Task, Intent

async def test():
    provider = get_default_provider()
    session = ConversationSession(provider=provider)
    
    # Mocking the history state exactly as session.py does when a Goal finishes
    goal_id = str(uuid.uuid4())
    tool_call_id = "tc_" + str(uuid.uuid4())
    
    session.history.append(AIMessage(
        role=MessageRole.ASSISTANT,
        content="",
        tool_calls=[ToolCall(id=tool_call_id, name="submit_goal_plan", arguments={"goal": "mock"})]
    ))
    
    execution_summary = {
        "goal_state": "COMPLETED",
        "completed_tasks": ["Mock task"],
        "failed_tasks": [],
        "verified_environment_state": {"url": "https://youtube.com"}
    }
    
    session.history.append(AIMessage(
        role=MessageRole.TOOL,
        content=f"Goal Execution Finished.\nExecution Summary: {json.dumps(execution_summary)}\nYou MUST summarize the final state truthfully based on these verified facts. Do NOT claim success if the state is FAILED.",
        tool_call_id=tool_call_id,
        name="submit_goal_plan"
    ))
    
    final_request = AIRequest(messages=session.history, temperature=0.7)
    
    print("Calling generate_stream...")
    try:
        async for chunk in provider.generate_stream(final_request):
            print("CHUNK:", repr(chunk.content))
    except Exception as e:
        print("ERROR:", repr(e))

if __name__ == "__main__":
    asyncio.run(test())

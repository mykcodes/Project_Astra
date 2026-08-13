import asyncio
import json
import time
from typing import Dict, Any

from app.ai.providers.types import ToolCall
from app.ai.orchestrator.action_executor import action_executor

async def run_test_case(name: str, tool_call: ToolCall):
    print(f"\n{'='*50}\nTEST: {name}\n{'='*50}")
    print(f"INPUT TOOL CALL: {tool_call.name}({tool_call.arguments})")
    
    start = time.perf_counter()
    try:
        result = await action_executor.execute_tool_call(tool_call)
    except Exception as e:
        result = {"success": False, "error": str(e)}
    duration = time.perf_counter() - start
    
    print(f"LATENCY: {duration:.2f}s")
    print("RESULT:")
    print(json.dumps(result, indent=2))

async def main():
    test_cases = [
        # System
        ("What time is it?", ToolCall(id="1", name="get_system_info", arguments={"sections": ["os"]})),
        ("Give me my laptop model.", ToolCall(id="2", name="get_system_info", arguments={"sections": ["device"]})),
        ("What CPU do I have?", ToolCall(id="3", name="get_system_info", arguments={"sections": ["cpu"]})),
        ("What GPU do I have?", ToolCall(id="4", name="get_system_info", arguments={"sections": ["gpu"]})),
        ("Inspect my entire system.", ToolCall(id="5", name="get_system_info", arguments={"sections": []})),
        
        # Desktop
        ("Is Spotify running?", ToolCall(id="6", name="execute_application_intent", arguments={"intent": "STATUS", "application": "Spotify"})),
        ("Open Spotify.", ToolCall(id="7", name="execute_application_intent", arguments={"intent": "OPEN", "application": "Spotify"})),
        ("Bring Spotify to the foreground.", ToolCall(id="8", name="execute_application_intent", arguments={"intent": "FOCUS", "application": "Spotify"})),
        ("Close Spotify.", ToolCall(id="9", name="execute_application_intent", arguments={"intent": "CLOSE", "application": "Spotify"})),
        ("Open Notion.", ToolCall(id="10", name="execute_application_intent", arguments={"intent": "OPEN", "application": "Notion"})),
        ("Close Notion.", ToolCall(id="11", name="execute_application_intent", arguments={"intent": "CLOSE", "application": "Notion"})),
        ("Is AntiGravity IDE running?", ToolCall(id="12", name="execute_application_intent", arguments={"intent": "STATUS", "application": "AntiGravity IDE"})),
        ("Open Fears to Fathom.", ToolCall(id="13", name="execute_application_intent", arguments={"intent": "OPEN", "application": "Fears to Fathom"})),
        ("Open Brave and search Amazon.", ToolCall(id="14", name="open_url", arguments={"url": "https://www.amazon.com"})),
        ("Open YouTube desktop app.", ToolCall(id="15", name="execute_application_intent", arguments={"intent": "OPEN", "application": "YouTube"})),
        ("Open ChatGPT app.", ToolCall(id="16", name="execute_application_intent", arguments={"intent": "OPEN", "application": "ChatGPT"})),
        ("Check whether an unknown application is installed.", ToolCall(id="17", name="execute_application_intent", arguments={"intent": "STATUS", "application": "some_random_nonexistent_app_1234"})),
    ]
    
    for name, call in test_cases:
        await run_test_case(name, call)
        
if __name__ == "__main__":
    asyncio.run(main())

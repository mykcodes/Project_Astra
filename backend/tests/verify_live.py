import asyncio
import json
import time

from app.ai.providers.types import ToolCall
from app.ai.orchestrator.action_executor import action_executor
from app.tools.desktop.browser.browser_session import browser_session

async def run_test_case(name: str, tool_call: ToolCall):
    print(f"\n{'='*50}\nTEST: {name}\n{'='*50}")
    print(f"INPUT TOOL CALL: {tool_call.name}({tool_call.arguments})")
    
    start = time.perf_counter()
    try:
        result = await action_executor.execute_tool_call(tool_call, max_attempts=1)
    except Exception as e:
        result = {"success": False, "error": str(e)}
    duration = time.perf_counter() - start
    
    print(f"LATENCY: {duration:.2f}s")
    print("RESULT:")
    print(json.dumps(result, indent=2, default=str))

async def main():
    test_cases = [
        ("1. Open Chrome", ToolCall(id="1", name="execute_application_intent", arguments={"intent": "OPEN", "application": "Chrome"})),
        ("2. Close Chrome", ToolCall(id="2", name="execute_application_intent", arguments={"intent": "CLOSE", "application": "Chrome"})),
        ("3. Check Brave status", ToolCall(id="3", name="execute_browser_intent", arguments={"intent": "STATUS", "browser_name": "brave"})),
        ("4. Navigate Brave to Google", ToolCall(id="4", name="execute_browser_intent", arguments={"intent": "NAVIGATE", "target": "https://www.google.com", "browser_name": "brave"})),
        ("5. Navigate Brave to YouTube", ToolCall(id="5", name="execute_browser_intent", arguments={"intent": "NEW_TAB", "target": "https://www.youtube.com", "browser_name": "brave"})),
    ]
    
    for name, call in test_cases:
        await run_test_case(name, call)
        await asyncio.sleep(1)

    print("\nVerifying Actual Browser State:")
    if browser_session.browser:
        pages = browser_session.browser.contexts[0].pages if browser_session.browser.contexts else []
        print(f"Found {len(pages)} pages.")
        for i, p in enumerate(pages):
            print(f"Page {i}: {p.url}")
    else:
        print("Browser session not active.")

if __name__ == "__main__":
    asyncio.run(main())

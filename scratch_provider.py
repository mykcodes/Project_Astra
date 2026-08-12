import asyncio
from app.ai.providers import get_provider
from app.ai.providers.types import AIRequest, AIMessage, MessageRole
from app.tools.registry import registry
from app.core.config import get_settings

async def test_provider():
    provider = get_provider("local")
    
    tools = [t.get_definition() for t in registry.list_tools()]
    print(f"Number of tools: {len(tools)}")
    
    request = AIRequest(
        messages=[AIMessage(role=MessageRole.USER, content="What time is it?")],
        temperature=0.7,
        tools=tools
    )
    
    print("Sending request to provider...")
    resp = await provider.generate(request)
    print("Response Content:", resp.content)
    print("Tool Calls:", resp.tool_calls)

if __name__ == "__main__":
    asyncio.run(test_provider())

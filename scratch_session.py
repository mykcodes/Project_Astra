import asyncio
from app.ai.providers import get_provider
from app.ai.orchestrator.session import ConversationSession
from app.core.config import get_settings

async def test_session():
    # Force groq provider
    provider = get_provider("groq")
    session = ConversationSession(provider=provider)
    
    print("Testing 'Open VS Code.'")
    resp = await session.chat("Open VS Code.")
    print("Response:", resp)
    
    print("\nHistory:")
    for msg in session.history:
        print(f"[{msg.role}] {msg.content}")
        if getattr(msg, "tool_calls", None):
            print(f"  Tool Calls: {msg.tool_calls}")

if __name__ == "__main__":
    asyncio.run(test_session())

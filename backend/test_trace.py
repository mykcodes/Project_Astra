import asyncio
import json
import uuid
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), ".")))

from app.domain.goals import Goal, Task, Intent, SemanticAction, TargetType, TargetOrdinal
from app.ai.orchestrator.session import ConversationSession
from app.ai.providers.groq.provider import GroqProvider

async def main():
    provider = GroqProvider()
    session = ConversationSession(provider=provider)
    
    print("SENDING: Open Chrome")
    async for event in session.chat_stream("Open Chrome"):
        print("EVENT:", event.strip())
        
if __name__ == "__main__":
    asyncio.run(main())

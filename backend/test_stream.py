import asyncio
from app.ai.providers.groq.provider import GroqProvider
from app.ai.providers.types import AIRequest, AIMessage, MessageRole

async def main():
    provider = GroqProvider()
    request = AIRequest(
        messages=[AIMessage(role=MessageRole.USER, content="Hello! Say exactly one word.")],
        temperature=0.7
    )
    print("Testing generate...")
    response = await provider.generate(request)
    print("Generate response:", response.content)
    
    print("Testing stream...")
    try:
        async for chunk in provider.generate_stream(request):
            print("Chunk:", chunk.content)
    except Exception as e:
        print("Exception:", type(e), e)

if __name__ == "__main__":
    asyncio.run(main())

import httpx
import asyncio

async def main():
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "http://localhost:8000/api/conversation/message",
                json={"text": "Hello, how are you?"},
                timeout=180.0
            )
            print("Status Code:", response.status_code)
            print("Response:", response.text)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print("Error:", repr(e))

if __name__ == "__main__":
    asyncio.run(main())

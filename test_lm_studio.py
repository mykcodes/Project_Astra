import httpx
import asyncio
import time

async def main():
    start_time = time.time()
    first_token_time = None
    
    payload = {
        "model": "qwen/qwen3.5-9b",
        "messages": [{"role": "user", "content": "Write a short poem about a fast computer."}],
        "stream": True,
        "max_tokens": 1024,
        "temperature": 0.7
    }
    
    print("Testing LM Studio directly...")
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            async with client.stream("POST", "http://localhost:1234/v1/chat/completions", json=payload) as response:
                response.raise_for_status()
                print("Connected! Waiting for chunks...")
                
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    if line.startswith("data: "):
                        if first_token_time is None:
                            first_token_time = time.time()
                            print(f"\n[TTFT: {first_token_time - start_time:.3f}s]")
                        print(line[6:], end="\n", flush=True)
                        
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\nError: {e}")
        return
        
    end_time = time.time()
    print(f"\nTotal time: {end_time - start_time:.3f}s")

if __name__ == "__main__":
    asyncio.run(main())

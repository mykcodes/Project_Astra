import httpx
import asyncio
import time

async def main():
    start_time = time.time()
    first_token_time = None
    tokens = 0
    
    print("Sending request to /api/conversation/message/stream...")
    
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            async with client.stream(
                "POST", 
                "http://localhost:8000/api/conversation/message/stream",
                json={"text": "Write a short poem about a fast computer."}
            ) as response:
                response.raise_for_status()
                
                async for chunk in response.aiter_text():
                    if chunk:
                        if first_token_time is None:
                            first_token_time = time.time()
                            print(f"\n[TTFT: {first_token_time - start_time:.3f}s]")
                        print(chunk, end="", flush=True)
                        tokens += 1 # approximate since chunks aren't necessarily single tokens, but good enough to show stream
                        
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\nError: {e}")
        return
        
    end_time = time.time()
    total_time = end_time - start_time
    
    print(f"\n\n--- Verification Complete ---")
    if first_token_time:
        ttft = first_token_time - start_time
        gen_time = end_time - first_token_time
        print(f"Time to First Token (TTFT): {ttft:.3f}s")
        print(f"Total Response Time: {total_time:.3f}s")

if __name__ == "__main__":
    asyncio.run(main())

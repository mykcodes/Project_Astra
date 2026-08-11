import httpx
import asyncio
import time
import json

async def main():
    payload = {
        "text": "Say hello in exactly five words."
    }
    
    start_time = time.time()
    ttft = None
    tokens = 0
    content = ""
    
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            async with client.stream("POST", "http://localhost:8000/api/conversation/message/stream", json=payload) as response:
                response.raise_for_status()
                async for text in response.aiter_text():
                    if text:
                        if ttft is None:
                            ttft = time.time() - start_time
                        # Count approx tokens by splitting words
                        tokens += len(text.split())
                        content += text
    except Exception as e:
        print(f"Error: {e}")
        return
        
    total_time = time.time() - start_time
    gen_time = total_time - ttft if ttft else 0
    tps = tokens / gen_time if gen_time > 0 else 0
    
    print("=== ASTRA BACKEND BENCHMARK ===")
    print(f"TTFT: {ttft:.3f}s")
    print(f"Tokens: {tokens}")
    print(f"Generation Time: {gen_time:.3f}s")
    print(f"Tokens/sec: {tps:.2f}")
    print(f"Total Time: {total_time:.3f}s")
    print(f"Content: {content}")

if __name__ == "__main__":
    asyncio.run(main())

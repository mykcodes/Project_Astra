import httpx
import asyncio
import time
import json

async def main():
    payload = {
        "model": "qwen/qwen3.5-9b",
        "messages": [{"role": "user", "content": "Say hello in exactly five words."}],
        "stream": True,
        "max_tokens": 100,
        "temperature": 0.1
    }
    
    start_time = time.time()
    ttft = None
    tokens = 0
    content = ""
    
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            async with client.stream("POST", "http://localhost:1234/v1/chat/completions", json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "): continue
                    data = line[6:]
                    if data == "[DONE]": break
                    try:
                        chunk = json.loads(data)
                        delta = chunk["choices"][0].get("delta", {})
                        
                        text = delta.get("content", "") or delta.get("reasoning_content", "")
                        if text:
                            if ttft is None:
                                ttft = time.time() - start_time
                            tokens += 1
                            content += text
                    except Exception as e:
                        pass
    except Exception as e:
        print(f"Error: {e}")
        return
        
    total_time = time.time() - start_time
    gen_time = total_time - ttft if ttft else 0
    tps = tokens / gen_time if gen_time > 0 else 0
    
    print("=== DIRECT LM STUDIO BENCHMARK ===")
    print(f"TTFT: {ttft:.3f}s")
    print(f"Tokens: {tokens}")
    print(f"Generation Time: {gen_time:.3f}s")
    print(f"Tokens/sec: {tps:.2f}")
    print(f"Total Time: {total_time:.3f}s")
    print(f"Content: {content}")

if __name__ == "__main__":
    asyncio.run(main())

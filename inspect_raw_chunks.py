import httpx
import asyncio
import json
import time

async def main():
    payload = {
        "model": "qwen/qwen3.5-9b",
        "messages": [
            {"role": "user", "content": "Hello"}
        ],
        "stream": True,
        "max_tokens": 100,
        "temperature": 0.7,
        "reasoning": False,
        "reasoning_effort": "none"
    }
    
    print("Sending payload:", json.dumps(payload, indent=2))
    
    try:
        async with httpx.AsyncClient() as client:
            async with client.stream("POST", "http://localhost:1234/v1/chat/completions", json=payload) as response:
                response.raise_for_status()
                
                print("\n--- RAW CHUNKS ---")
                count = 0
                async for line in response.aiter_lines():
                    if not line: continue
                    if line.startswith("data: "):
                        data = line[6:]
                        if data == "[DONE]": 
                            print("Received [DONE]")
                            break
                        
                        try:
                            chunk = json.loads(data)
                            print(json.dumps(chunk))
                            count += 1
                            if count >= 10:  # just need the first few to see if it's reasoning_content or content
                                print("... stopping early after 10 chunks to avoid long output.")
                                break
                        except Exception as e:
                            print("Error parsing JSON:", e)
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    asyncio.run(main())

import httpx
import asyncio
import json

async def test_lm_studio():
    base_url = "http://localhost:1234/v1"
    
    # 1. Get models
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{base_url}/models", timeout=5.0)
            models = resp.json().get("data", [])
            if not models:
                print("No models found.")
                return
            model_id = models[0]["id"]
            print(f"Using model: {model_id}")
            
            # 2. Send request with tools
            payload = {
                "model": model_id,
                "messages": [
                    {"role": "user", "content": "Open VS Code."}
                ],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "open_application",
                            "description": "Opens a desktop application based on an explicitly allowed list.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "application": {
                                        "type": "string",
                                        "description": "The name of the application to open (e.g., 'vscode', 'notepad')."
                                    }
                                },
                                "required": ["application"]
                            }
                        }
                    }
                ],
                "tool_choice": "auto"
            }
            
            print("Sending request to LM Studio...")
            resp = await client.post(f"{base_url}/chat/completions", json=payload, timeout=60.0)
            print("Status Code:", resp.status_code)
            data = resp.json()
            print("Raw Response:", json.dumps(data, indent=2))
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_lm_studio())

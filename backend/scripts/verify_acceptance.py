import asyncio
import json
import time
from app.tools.desktop.desktop_controller import desktop_controller

async def step(description, coro):
    print(f"\n=> {description}")
    try:
        result = await coro
        print(json.dumps(result, indent=2))
        return result
    except Exception as e:
        print(f"Error: {e}")
        return None

async def main():
    print("Starting Manual Acceptance Test Verification...")
    
    # 1. Open VS Code
    await step("1. Open VS Code", desktop_controller.open_application("VS Code"))
    time.sleep(2)
    
    # 2. Close VS Code
    await step("2. Close VS Code", desktop_controller.close_application("VS Code"))
    
    # 3. Open VS Code again after several minutes (simulated)
    time.sleep(2)
    await step("3. Open VS Code again", desktop_controller.open_application("VS Code"))
    
    # 4. Open Notepad
    await step("4. Open Notepad", desktop_controller.open_application("Notepad"))
    time.sleep(2)
    
    # 5. Close Notepad
    await step("5. Close Notepad", desktop_controller.close_application("Notepad"))
    
    # 6. Open Spotify
    await step("6. Open Spotify", desktop_controller.open_application("Spotify"))
    time.sleep(2)
    
    # 7. Close Spotify
    await step("7. Close Spotify", desktop_controller.close_application("Spotify"))
    
    # 8. Open Spotify again
    time.sleep(2)
    await step("8. Open Spotify again", desktop_controller.open_application("Spotify"))
    
    # 9. Check Spotify status
    print("\n=> 9. Check Spotify status")
    status = desktop_controller.get_application_status("Spotify")
    print(json.dumps(status.to_dict(), indent=2))
    
    # 10. Open Notion
    await step("10. Open Notion", desktop_controller.open_application("Notion"))
    time.sleep(2)
    
    # 11. Focus Notion when background
    await step("11. Focus Notion (should already be running)", desktop_controller.open_application("Notion"))
    
    # 12. Close Notion
    await step("12. Close Notion", desktop_controller.close_application("Notion"))
    
    # 13. Open ChatGPT desktop application
    await step("13. Open ChatGPT", desktop_controller.open_application("ChatGPT"))
    time.sleep(2)
    
    # 14. Check ChatGPT status
    print("\n=> 14. Check ChatGPT status")
    status = desktop_controller.get_application_status("ChatGPT")
    print(json.dumps(status.to_dict(), indent=2))
    
    # 15. Close ChatGPT
    await step("15. Close ChatGPT", desktop_controller.close_application("ChatGPT"))
    
    # 16. Open Calculator
    await step("16. Open Calculator", desktop_controller.open_application("Calculator"))
    time.sleep(2)
    
    # 18. Attempt to open nonexistent application
    await step("18. Open nonexistent application", desktop_controller.open_application("NonExistentApp123"))
    
    # 19. Attempt arbitrary executable path
    await step("19. Attempt arbitrary executable path", desktop_controller.open_application("C:\\Windows\\System32\\cmd.exe"))
    
    print("\nAcceptance tests complete.")

if __name__ == "__main__":
    asyncio.run(main())

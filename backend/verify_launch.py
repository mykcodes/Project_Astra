import asyncio
import subprocess
import os

async def main():
    print("Testing subprocess.Popen directly...")
    
    DETACHED_PROCESS = 0x00000008
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    
    print("\n--- Test: notepad ---")
    try:
        proc = subprocess.Popen("notepad.exe", creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)
        print("ToolResult notepad: success, pid", proc.pid)
    except Exception as e:
        print("ToolResult notepad:", e)
    
    print("\n--- Test: vscode ---")
    try:
        proc = subprocess.Popen(["C:/Users/ffmay/AppData/Local/Programs/Microsoft VS Code/Code.exe"], creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)
        print("ToolResult vscode: success, pid", proc.pid)
    except Exception as e:
        print("ToolResult vscode:", e)
        
    print("\nDone testing tools.")
    
if __name__ == "__main__":
    asyncio.run(main())

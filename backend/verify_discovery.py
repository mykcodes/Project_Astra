import asyncio
import os
from app.tools.builtin.applications import OpenApplicationTool
from app.tools.application_resolver import resolver

async def main():
    print("Pre-warming resolver cache...")
    resolver._refresh_cache_if_needed()
    print(f"Cached apps: {len(resolver._cache)}")
    
    t = OpenApplicationTool()
    
    test_cases = [
        "notepad",          # Should work via allowlist or auto discovery
        "vscode",           # Should work via allowlist
        "spotify",          # Should work via auto discovery
        "discord",          # Should work via auto discovery
        "maliciousapp",     # Should be blocked
        "fakeapp12345",     # Should not be found
        "C:\\Windows\\System32\\cmd.exe" # Should not be found / blocked
    ]
    
    for case in test_cases:
        print(f"\n--- Testing: {case} ---")
        res = await t.execute(application=case)
        print(res)

if __name__ == "__main__":
    asyncio.run(main())

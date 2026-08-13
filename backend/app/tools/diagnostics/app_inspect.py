import sys
import asyncio
import json
from app.tools.desktop.desktop_controller import desktop_controller

async def main():
    if len(sys.argv) < 2:
        print("Usage: python -m app.tools.diagnostics.app_inspect <application_name>")
        sys.exit(1)
        
    app_name = " ".join(sys.argv[1:])
    
    print(f"Inspecting application: {app_name}")
    print("-" * 50)
    
    status = desktop_controller.get_application_status(app_name, force_refresh=True)
    
    # Print the specific fields requested
    print(f"Application: {status.descriptor.display_name}")
    print(f"Canonical name: {status.descriptor.canonical_name}")
    print(f"Installed: {status.descriptor.installed}")
    print(f"Launch type: {status.descriptor.launch_type.value if status.descriptor.launch_type else 'N/A'}")
    print(f"Executable: {status.descriptor.executable_path or 'N/A'}")
    
    if status.descriptor.package_family_name:
        print(f"Package/AUMID: {status.descriptor.package_family_name} / {status.descriptor.app_user_model_id}")
    else:
        print("Package/AUMID: N/A")
        
    print(f"Process names: {', '.join(status.descriptor.expected_process_names) if status.descriptor.expected_process_names else 'N/A'}")
    
    is_running = status.state not in ["UNKNOWN", "NOT_INSTALLED", "INSTALLED_NOT_RUNNING"]
    print(f"Running: {is_running}")
    print(f"PIDs: {status.pids}")
    
    windows_found = len(status.windows)
    print(f"Windows: {windows_found}")
    if windows_found > 0:
        for w in status.windows:
            print(f"  - HWND: {w['hwnd']}, Title: '{w['title']}', Visible: {w['is_visible']}, Foreground: {w['is_foreground']}")
            
    is_foreground = any(w["is_foreground"] for w in status.windows)
    print(f"Foreground: {is_foreground}")
    print(f"Discovery source: {status.descriptor.discovery_source or 'N/A'}")
    
    print("-" * 50)
    print("Full JSON Dump:")
    print(json.dumps(status.to_dict(), indent=2))
    print("Done.")

if __name__ == "__main__":
    asyncio.run(main())

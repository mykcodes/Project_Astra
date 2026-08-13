import sys
import json
import logging
from app.core.logging.logger import get_logger
from app.tools.desktop.desktop_controller import desktop_controller

logging.basicConfig(level=logging.ERROR)
logger = get_logger(__name__)

def run_desktop_diagnostic(application_name: str):
    print("==================================================")
    print(f"ASTRA DESKTOP DIAGNOSTIC REPORT: {application_name.upper()}")
    print("==================================================")
    
    try:
        status = desktop_controller.get_application_status(application_name, force_refresh=True)
        status_dict = status.to_dict()
        desc = status.descriptor.to_dict()
        
        print("\n--- DESCRIPTOR ---")
        print(json.dumps(desc, indent=2))
        
        print("\n--- STATUS ---")
        print(json.dumps(status_dict, indent=2))
        
    except Exception as e:
        print(f"FAILED TO GET APPLICATION STATUS: {e}")

if __name__ == "__main__":
    app_name = sys.argv[1] if len(sys.argv) > 1 else "spotify"
    run_desktop_diagnostic(app_name)

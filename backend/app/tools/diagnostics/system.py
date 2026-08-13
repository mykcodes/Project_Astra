import sys
import json
import logging
from app.core.logging.logger import get_logger
from app.system.information_service import system_engine

logging.basicConfig(level=logging.ERROR)
logger = get_logger(__name__)

def run_system_diagnostic():
    print("==================================================")
    print("ASTRA MACHINE DIAGNOSTIC REPORT")
    print("==================================================")
    
    try:
        profile = system_engine.get_machine_profile()
        profile_dict = profile.to_dict()
        print(json.dumps(profile_dict, indent=2))
    except Exception as e:
        print(f"FAILED TO GET MACHINE PROFILE: {e}")

if __name__ == "__main__":
    run_system_diagnostic()

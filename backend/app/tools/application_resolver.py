import os
import sys
import json
import subprocess
import string
import time
from typing import Optional, Dict, List
from pathlib import Path

try:
    import winreg
except ImportError:
    winreg = None

from app.core.logging.logger import get_logger
from app.core.config import get_settings
from app.tools.desktop.application_state import ApplicationDescriptor, LaunchType

logger = get_logger(__name__)

class ApplicationResolver:
    def __init__(self):
        self._cache: Dict[str, ApplicationDescriptor] = {}
        self._cache_time = 0
        self._cache_ttl = 300  # 5 minutes
        
    def _normalize_name(self, name: str) -> str:
        if not name:
            return ""
        name = name.lower().strip()
        remove_chars = string.punctuation + string.whitespace
        trans = str.maketrans("", "", remove_chars)
        name = name.translate(trans)
        
        aliases = {
            "vscode": "visualstudiocode",
            "chrome": "googlechrome",
            "edge": "microsoftedge",
            "word": "microsoftword",
            "excel": "microsoftexcel",
            "powerpoint": "microsoftpowerpoint",
            "chatgpt": "chatgptclassic",
            "chatgptclassic": "chatgptclassic",
        }
        return aliases.get(name, name)

    def _is_valid_executable(self, path: str) -> bool:
        if not path or not os.path.isabs(path):
            return False
            
        allowed_extensions = {".exe", ".bat", ".cmd"}
        try:
            path_obj = Path(path)
            if not path_obj.is_file():
                return False
            if path_obj.suffix.lower() not in allowed_extensions:
                return False
            return True
        except Exception:
            return False

    def _refresh_cache_if_needed(self, force: bool = False):
        current_time = time.time()
        if force or not self._cache or (current_time - self._cache_time > self._cache_ttl):
            logger.info("APPLICATION_RESOLUTION_STARTED", extra={"details": "Refreshing application discovery cache."})
            self._cache = self._discover_applications()
            self._cache_time = current_time

    def invalidate(self, application_name: str):
        norm_input = self._normalize_name(application_name)
        if norm_input in self._cache:
            del self._cache[norm_input]

    def _discover_applications(self) -> Dict[str, ApplicationDescriptor]:
        apps = {}
        if sys.platform != "win32":
            return apps
            
        # Discover Win32 Apps
        if winreg:
            self._discover_via_app_paths(winreg.HKEY_LOCAL_MACHINE, apps)
            self._discover_via_app_paths(winreg.HKEY_CURRENT_USER, apps)
            self._discover_via_uninstall(winreg.HKEY_LOCAL_MACHINE, apps)
            self._discover_via_uninstall(winreg.HKEY_CURRENT_USER, apps)
            
        self._discover_via_start_menu(apps)
        self._discover_via_app_execution_aliases(apps)
        
        # Discover Filesystem / Configured roots
        self._discover_via_configured_roots(apps)
        
        # Discover UWP/Store Apps
        self._discover_via_uwp(apps)
        
        return apps

    def _create_descriptor(self, display_name: str, launch_target: str, source: str, launch_type: LaunchType, app_id: str = None) -> ApplicationDescriptor:
        norm_name = self._normalize_name(display_name)
        
        desc = ApplicationDescriptor(
            canonical_name=display_name.lower(),
            normalized_name=norm_name,
            display_name=display_name,
            installed=True,
            launch_target=launch_target,
            launch_type=launch_type,
            discovery_source=source,
            confidence=1.0,
            verified=True
        )
        
        if launch_type == LaunchType.WIN32:
            desc.executable_path = launch_target
            desc.executable_name = os.path.basename(launch_target)
            desc.expected_process_names.add(desc.executable_name)
            desc.install_location = os.path.dirname(launch_target)
            
            # Semantic process names for known launchers
            lower_name = desc.executable_name.lower()
            if lower_name in ("update.exe", "launcher.exe", "spotify_cli.exe"):
                base = norm_name
                for ext in [".exe"]:
                    desc.expected_process_names.add(base + ext)
                    if display_name:
                        desc.expected_process_names.add(display_name.replace(" ", "") + ext)
        elif launch_type == LaunchType.UWP:
            desc.app_user_model_id = app_id
            if app_id:
                family_name = app_id.split("!")[0]
                desc.package_family_name = family_name
                desc.expected_process_names.add(f"{norm_name}.exe")
                
                if "chatgpt" in norm_name:
                    desc.expected_process_names.add("chatgpt.exe")
                elif "spotify" in norm_name:
                    desc.expected_process_names.add("spotify.exe")
                    
        return desc

    def _discover_via_app_paths(self, hive, apps: Dict[str, ApplicationDescriptor]):
        paths = [
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths",
            r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths"
        ]
        for app_paths_key in paths:
            try:
                with winreg.OpenKey(hive, app_paths_key) as key:
                    num_subkeys, _, _ = winreg.QueryInfoKey(key)
                    for i in range(num_subkeys):
                        try:
                            subkey_name = winreg.EnumKey(key, i)
                            with winreg.OpenKey(key, subkey_name) as subkey:
                                default_val, val_type = winreg.QueryValueEx(subkey, "")
                                if default_val and val_type in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
                                    default_val = os.path.expandvars(default_val).strip('"')
                                    if self._is_valid_executable(default_val):
                                        app_name = subkey_name[:-4] if subkey_name.lower().endswith(".exe") else subkey_name
                                        norm_name = self._normalize_name(app_name)
                                        if norm_name and norm_name not in apps:
                                            apps[norm_name] = self._create_descriptor(app_name, default_val, "Registry App Paths", LaunchType.WIN32)
                        except OSError:
                            pass
            except OSError:
                pass

    def _discover_via_uninstall(self, hive, apps: Dict[str, ApplicationDescriptor]):
        uninstall_paths = [
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
            r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"
        ]
        for path in uninstall_paths:
            try:
                with winreg.OpenKey(hive, path) as key:
                    num_subkeys, _, _ = winreg.QueryInfoKey(key)
                    for i in range(num_subkeys):
                        try:
                            subkey_name = winreg.EnumKey(key, i)
                            with winreg.OpenKey(key, subkey_name) as subkey:
                                display_name = ""
                                try:
                                    display_name, _ = winreg.QueryValueEx(subkey, "DisplayName")
                                except OSError:
                                    pass
                                    
                                publisher = None
                                try:
                                    publisher, _ = winreg.QueryValueEx(subkey, "Publisher")
                                except OSError:
                                    pass

                                display_icon = ""
                                try:
                                    display_icon, _ = winreg.QueryValueEx(subkey, "DisplayIcon")
                                except OSError:
                                    pass
                                
                                install_loc = ""
                                try:
                                    install_loc, _ = winreg.QueryValueEx(subkey, "InstallLocation")
                                except OSError:
                                    pass
                                    
                                if display_name and display_icon:
                                    icon_path = os.path.expandvars(display_icon.split(",")[0].strip('"'))
                                    if self._is_valid_executable(icon_path):
                                        norm_name = self._normalize_name(display_name)
                                        if norm_name and norm_name not in apps:
                                            desc = self._create_descriptor(display_name, icon_path, "Registry Uninstall", LaunchType.WIN32)
                                            desc.publisher = publisher
                                            if install_loc:
                                                desc.install_location = install_loc
                                            apps[norm_name] = desc
                        except OSError:
                            pass
            except OSError:
                pass

    def _discover_via_start_menu(self, apps: Dict[str, ApplicationDescriptor]):
        ps_script = '''
        $ErrorActionPreference = "SilentlyContinue"
        $shell = New-Object -COM WScript.Shell
        $paths = @([Environment]::GetFolderPath("StartMenu"), [Environment]::GetFolderPath("CommonStartMenu"))
        $results = @()
        foreach ($path in $paths) {
            if (Test-Path $path) {
                Get-ChildItem -Path $path -Filter *.lnk -Recurse | ForEach-Object {
                    $lnk = $shell.CreateShortcut($_.FullName)
                    if ($lnk.TargetPath -match "\\.exe$") {
                        $results += [PSCustomObject]@{Name = $_.BaseName; TargetPath = $lnk.TargetPath}
                    }
                }
            }
        }
        $results | ConvertTo-Json -Compress
        '''
        try:
            process = subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-Command", "-"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=False)
            stdout, _ = process.communicate(input=ps_script, timeout=10.0)
            if stdout.strip():
                data = json.loads(stdout)
                if isinstance(data, dict): data = [data]
                for item in data:
                    name, target = item.get("Name", ""), item.get("TargetPath", "")
                    if name and target and self._is_valid_executable(target):
                        norm_name = self._normalize_name(name)
                        if norm_name and norm_name not in apps:
                            apps[norm_name] = self._create_descriptor(name, target, "Start Menu", LaunchType.WIN32)
        except Exception as e:
            logger.warning(f"Failed to discover Start Menu apps: {e}")

    def _discover_via_app_execution_aliases(self, apps: Dict[str, ApplicationDescriptor]):
        local_app_data = os.environ.get("LOCALAPPDATA")
        if not local_app_data:
            return
            
        aliases_dir = Path(local_app_data) / "Microsoft" / "WindowsApps"
        if not aliases_dir.exists():
            return
            
        try:
            for item in aliases_dir.iterdir():
                if item.is_file() and item.suffix.lower() == ".exe":
                    # They are usually zero-byte execution aliases, but they act as valid execution targets.
                    name = item.stem
                    norm_name = self._normalize_name(name)
                    if norm_name and norm_name not in apps:
                        # Execution aliases launch UWP apps via shell, but we can call them directly via CreateProcess or shell=False
                        # if they are in PATH. Better to treat them as Win32 since they are physical files.
                        apps[norm_name] = self._create_descriptor(name, str(item), "AppExecutionAliases", LaunchType.WIN32)
        except Exception as e:
            logger.warning(f"Failed to discover AppExecutionAliases: {e}")

    def _discover_via_configured_roots(self, apps: Dict[str, ApplicationDescriptor]):
        settings = get_settings()
        roots_str = getattr(settings, "astra_tool_app_discovery_roots", "")
        
        default_roots = [
            os.environ.get("LOCALAPPDATA", ""),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs"),
        ]
        
        roots = []
        if roots_str:
            try:
                roots = json.loads(roots_str)
            except json.JSONDecodeError:
                roots = [r.strip() for r in roots_str.split(",") if r.strip()]
                
        roots.extend(default_roots)
        
        # Deduplicate and validate
        valid_roots = []
        for r in roots:
            if not r: continue
            try:
                path = Path(r).resolve()
                if path.exists() and path.is_dir() and path not in valid_roots:
                    # Do not allow C:\ or C:\Windows to prevent massive scanning
                    if str(path) in ("C:\\", "c:\\", "C:\\Windows", "c:\\windows"):
                        continue
                    valid_roots.append(path)
            except Exception:
                pass
                
        # Shallow scan (up to depth 2) of these directories to find .exe files
        for root in valid_roots:
            self._scan_directory_for_executables(root, apps, max_depth=2)

    def _scan_directory_for_executables(self, current_dir: Path, apps: Dict[str, ApplicationDescriptor], max_depth: int, current_depth: int = 0):
        if current_depth > max_depth:
            return
            
        try:
            for item in current_dir.iterdir():
                if item.is_dir():
                    # Skip common heavy directories that aren't usually application roots
                    if item.name.lower() in ("node_modules", ".git", "venv", "__pycache__"):
                        continue
                    self._scan_directory_for_executables(item, apps, max_depth, current_depth + 1)
                elif item.is_file() and item.suffix.lower() == ".exe":
                    # Heuristics to avoid garbage EXEs (unins000.exe, update.exe, etc)
                    if item.stem.lower() in ("unins000", "uninstall", "update", "setup", "launcher"):
                        continue
                        
                    name = item.stem
                    norm_name = self._normalize_name(name)
                    if norm_name and norm_name not in apps:
                        apps[norm_name] = self._create_descriptor(name, str(item), "Filesystem Configured Roots", LaunchType.WIN32)
        except (PermissionError, OSError):
            pass

    def _discover_via_uwp(self, apps: Dict[str, ApplicationDescriptor]):
        ps_script = '''
        $ErrorActionPreference = "SilentlyContinue"
        Get-StartApps | Select-Object Name, AppID | ConvertTo-Json -Compress
        '''
        try:
            process = subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-Command", "-"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=False)
            stdout, _ = process.communicate(input=ps_script, timeout=10.0)
            if stdout.strip():
                data = json.loads(stdout)
                if isinstance(data, dict): data = [data]
                for item in data:
                    name, app_id = item.get("Name", ""), item.get("AppID", "")
                    if name and app_id:
                        norm_name = self._normalize_name(name)
                        if norm_name and norm_name not in apps:
                            launch_target = f"shell:AppsFolder\\{app_id}"
                            apps[norm_name] = self._create_descriptor(name, launch_target, "UWP/Store", LaunchType.UWP, app_id=app_id)
        except Exception as e:
            logger.warning(f"Failed to discover UWP apps: {e}")

    def resolve(self, application_name: str, blocked_apps: List[str] = None, force_refresh: bool = False) -> ApplicationDescriptor:
        if not application_name:
            return ApplicationDescriptor(canonical_name="", normalized_name="", display_name="", installed=False)
            
        norm_input = self._normalize_name(application_name)
        blocked_apps = [self._normalize_name(b) for b in (blocked_apps or [])]
        
        if norm_input in blocked_apps:
            logger.info("APPLICATION_BLOCKED", extra={"application": application_name})
            return ApplicationDescriptor(canonical_name=application_name, normalized_name=norm_input, display_name=application_name, installed=False)
            
        self._refresh_cache_if_needed(force=force_refresh)
        
        # 1. Exact match
        if norm_input in self._cache:
            desc = self._cache[norm_input]
            return desc if norm_input not in blocked_apps else ApplicationDescriptor(canonical_name=application_name, normalized_name=norm_input, display_name=application_name, installed=False)
            
        # 2. Fuzzy match
        matches = []
        for cached_norm, cached_data in self._cache.items():
            if norm_input in cached_norm or cached_norm in norm_input:
                matches.append(cached_data)
                
        if len(matches) == 1:
            desc = matches[0]
            if desc.normalized_name in blocked_apps:
                return ApplicationDescriptor(canonical_name=application_name, normalized_name=norm_input, display_name=application_name, installed=False)
            desc.confidence = 0.8
            return desc
            
        if len(matches) > 1:
            return ApplicationDescriptor(
                canonical_name=application_name.lower(),
                normalized_name=norm_input,
                display_name=application_name,
                installed=False,
                ambiguous=True
            )
            
        # Not found
        return ApplicationDescriptor(
            canonical_name=application_name.lower(),
            normalized_name=norm_input,
            display_name=application_name,
            installed=False
        )

resolver = ApplicationResolver()

import pytest
import os
from unittest.mock import patch, MagicMock

from app.tools.application_resolver import ApplicationResolver
from app.tools.desktop.application_state import ApplicationDescriptor, LaunchType

@pytest.fixture
def resolver():
    res = ApplicationResolver()
    res._refresh_cache_if_needed = MagicMock()
    return res

def test_normalize_name(resolver):
    assert resolver._normalize_name("VS Code") == "visualstudiocode"
    assert resolver._normalize_name("Visual Studio Code") == "visualstudiocode"
    assert resolver._normalize_name("Chrome") == "googlechrome"
    assert resolver._normalize_name("Notepad++") == "notepad"
    assert resolver._normalize_name("  My App  ") == "myapp"
    assert resolver._normalize_name("APP-NAME") == "appname"

def test_resolve_empty(resolver):
    res = resolver.resolve("")
    assert not res.installed

def test_resolve_blocked(resolver):
    res = resolver.resolve("malicious_app", blocked_apps=["Malicious_App"])
    assert not res.installed

def test_resolve_not_found(resolver):
    resolver._cache = {"otherapp": ApplicationDescriptor(canonical_name="other", normalized_name="otherapp", display_name="Other", installed=True, launch_target="C:\\other.exe")}
    res = resolver.resolve("Missing App")
    assert not res.installed

def test_resolve_exact_match(resolver):
    resolver._cache = {"myapp": ApplicationDescriptor(canonical_name="myapp", normalized_name="myapp", display_name="My App", installed=True, launch_target="C:\\myapp.exe", confidence=1.0)}
    res = resolver.resolve("My App")
    assert res.installed
    assert res.launch_target == "C:\\myapp.exe"
    assert res.confidence == 1.0

def test_resolve_alias_match(resolver):
    resolver._cache = {"visualstudiocode": ApplicationDescriptor(canonical_name="vscode", normalized_name="visualstudiocode", display_name="VS Code", installed=True, launch_target="C:\\code.exe")}
    res = resolver.resolve("vscode")
    assert res.installed
    assert res.launch_target == "C:\\code.exe"

def test_resolve_fuzzy_match(resolver):
    resolver._cache = {"discordptb": ApplicationDescriptor(canonical_name="discordptb", normalized_name="discordptb", display_name="Discord PTB", installed=True, launch_target="C:\\discord.exe")}
    res = resolver.resolve("discord")
    assert res.installed
    assert res.confidence == 0.8
    assert res.launch_target == "C:\\discord.exe"

def test_resolve_ambiguous_match(resolver):
    resolver._cache = {
        "discordptb": ApplicationDescriptor(canonical_name="discordptb", normalized_name="discordptb", display_name="Discord PTB", installed=True, launch_target="C:\\discordptb.exe"),
        "discordcanary": ApplicationDescriptor(canonical_name="discordcanary", normalized_name="discordcanary", display_name="Discord Canary", installed=True, launch_target="C:\\discordcanary.exe")
    }
    res = resolver.resolve("discord")
    assert not res.installed
    assert res.ambiguous

def test_resolve_blocked_in_cache(resolver):
    resolver._cache = {"badapp": ApplicationDescriptor(canonical_name="bad", normalized_name="badapp", display_name="Bad App", installed=True, launch_target="C:\\bad.exe")}
    res = resolver.resolve("badapp", blocked_apps=["badapp"])
    assert not res.installed

def test_is_valid_executable_safe(resolver):
    with patch("os.path.isabs", return_value=True), patch("pathlib.Path.is_file", return_value=True):
        assert resolver._is_valid_executable("C:\\Windows\\System32\\cmd.exe")
        assert resolver._is_valid_executable("C:\\Windows\\System32\\cmd.bat")
        assert not resolver._is_valid_executable("C:\\Windows\\System32\\cmd.dll")
        
    with patch("os.path.isabs", return_value=False):
        assert not resolver._is_valid_executable("cmd.exe")

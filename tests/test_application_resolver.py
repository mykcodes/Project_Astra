import pytest
import os
from unittest.mock import patch, MagicMock

from app.tools.application_resolver import ApplicationResolver, ApplicationResolution

@pytest.fixture
def resolver():
    res = ApplicationResolver()
    # Disable actual registry/powershell scanning for tests
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
    assert not res.found
    assert res.error_type == "INVALID_INPUT"

def test_resolve_blocked(resolver):
    res = resolver.resolve("malicious_app", blocked_apps=["Malicious_App"])
    assert not res.found
    assert res.error_type == "APPLICATION_BLOCKED"

def test_resolve_not_found(resolver):
    resolver._cache = {"otherapp": {"display_name": "Other", "launch_target": "C:\\other.exe", "source": "test"}}
    res = resolver.resolve("Missing App")
    assert not res.found
    assert res.error_type == "APPLICATION_NOT_FOUND"

def test_resolve_exact_match(resolver):
    resolver._cache = {"myapp": {"display_name": "My App", "launch_target": "C:\\myapp.exe", "source": "test"}}
    res = resolver.resolve("My App")
    assert res.found
    assert res.launch_target == "C:\\myapp.exe"
    assert res.confidence == 1.0

def test_resolve_alias_match(resolver):
    resolver._cache = {"visualstudiocode": {"display_name": "VS Code", "launch_target": "C:\\code.exe", "source": "test"}}
    res = resolver.resolve("vscode")
    assert res.found
    assert res.launch_target == "C:\\code.exe"

def test_resolve_fuzzy_match(resolver):
    resolver._cache = {"discordptb": {"display_name": "Discord PTB", "launch_target": "C:\\discord.exe", "source": "test"}}
    res = resolver.resolve("discord")
    assert res.found
    assert res.confidence == 0.8
    assert res.launch_target == "C:\\discord.exe"

def test_resolve_ambiguous_match(resolver):
    resolver._cache = {
        "discordptb": {"display_name": "Discord PTB", "launch_target": "C:\\discordptb.exe", "source": "test"},
        "discordcanary": {"display_name": "Discord Canary", "launch_target": "C:\\discordcanary.exe", "source": "test"}
    }
    res = resolver.resolve("discord")
    assert not res.found
    assert res.error_type == "APPLICATION_AMBIGUOUS"

def test_resolve_blocked_in_cache(resolver):
    resolver._cache = {"badapp": {"display_name": "Bad App", "launch_target": "C:\\bad.exe", "source": "test"}}
    res = resolver.resolve("badapp", blocked_apps=["badapp"])
    assert not res.found
    assert res.error_type == "APPLICATION_BLOCKED"

def test_is_valid_executable_safe(resolver):
    with patch("os.path.isabs", return_value=True), patch("pathlib.Path.is_file", return_value=True):
        assert resolver._is_valid_executable("C:\\Windows\\System32\\cmd.exe")
        assert not resolver._is_valid_executable("C:\\Windows\\System32\\cmd.bat")
        assert not resolver._is_valid_executable("C:\\Windows\\System32\\cmd.dll")
        
    with patch("os.path.isabs", return_value=False):
        assert not resolver._is_valid_executable("cmd.exe")

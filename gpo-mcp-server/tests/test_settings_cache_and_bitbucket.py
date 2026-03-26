"""Tests for search mtime cache (Fix 10) and Bitbucket service fixes (Fix 2, 3)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app import config
from app.services.bitbucket_service import BitbucketService


# ---------------------------------------------------------------------------
# Search mtime cache (Fix 10) — now uses YAML policy files
# ---------------------------------------------------------------------------

def _make_yaml(path: Path, setting_name: str = "TestSetting") -> None:
    """Write a minimal valid YAML policy file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""\
collection_name: "Test Collection"
ou: "Workstations"
settings:
  - uid: "{{uid-1}}"
    name: {setting_name}
    description: "Test setting"
    bypass_errors: false
    properties:
      action: U
      hive: HKEY_LOCAL_MACHINE
      key: "SOFTWARE\\\\Test"
      value_name: TestValue
      value_type: REG_DWORD
      value: "1"
""",
        encoding="utf-8",
    )


def test_search_cache_avoids_redundant_parse(tmp_path, monkeypatch):
    """Second call to gpo_search_settings on an unchanged file should use the cache."""
    from app.tools import settings as settings_mod
    from app.services import yaml_service as yaml_svc_module

    # Clear the module-level cache before the test
    settings_mod._search_cache.clear()

    # Set up a policies/ subdirectory (yaml_service.policies_path convention)
    policies_dir = tmp_path / "policies"
    yaml_file = policies_dir / "policy.yaml"
    _make_yaml(yaml_file, "TestSetting")

    monkeypatch.setattr(config.settings, "repo_path", tmp_path)

    from app.services.yaml_service import yaml_service
    parse_calls = []
    original_parse = yaml_service.parse_file

    def counting_parse(path):
        parse_calls.append(str(path))
        return original_parse(path)

    monkeypatch.setattr(yaml_service, "parse_file", counting_parse)

    class FakeMCP:
        def __init__(self):
            self.tools = {}

        def tool(self):
            def decorator(func):
                self.tools[func.__name__] = func
                return func
            return decorator

    mcp = FakeMCP()
    settings_mod.register_setting_tools(mcp)

    # First search — should parse the file
    mcp.tools["gpo_search_settings"]("TestSetting")
    first_call_count = len(parse_calls)
    assert first_call_count >= 1, "File should have been parsed on first call"

    # Second search — file unchanged, should read from cache
    mcp.tools["gpo_search_settings"]("TestSetting")
    second_call_count = len(parse_calls)
    assert second_call_count == first_call_count, (
        f"File should NOT be reparsed if mtime unchanged (calls: {parse_calls})"
    )

    settings_mod._search_cache.clear()


def test_search_cache_invalidates_on_file_change(tmp_path, monkeypatch):
    """Cache entry should be bypassed when the file's mtime changes."""
    from app.tools import settings as settings_mod

    settings_mod._search_cache.clear()

    policies_dir = tmp_path / "policies"
    yaml_file = policies_dir / "policy.yaml"
    _make_yaml(yaml_file, "OriginalSetting")

    monkeypatch.setattr(config.settings, "repo_path", tmp_path)

    from app.services.yaml_service import yaml_service
    parse_calls = []
    original_parse = yaml_service.parse_file

    def counting_parse(path):
        parse_calls.append(str(path))
        return original_parse(path)

    monkeypatch.setattr(yaml_service, "parse_file", counting_parse)

    class FakeMCP:
        def __init__(self):
            self.tools = {}

        def tool(self):
            def decorator(func):
                self.tools[func.__name__] = func
                return func
            return decorator

    mcp = FakeMCP()
    settings_mod.register_setting_tools(mcp)

    # First parse
    mcp.tools["gpo_search_settings"]("OriginalSetting")
    assert len(parse_calls) == 1

    # Simulate file modification by changing mtime in cache to an old value
    if yaml_file in settings_mod._search_cache:
        old_mtime, old_data = settings_mod._search_cache[yaml_file]
        settings_mod._search_cache[yaml_file] = (old_mtime - 1.0, old_data)

    # Second parse — cache entry is stale, should re-parse
    mcp.tools["gpo_search_settings"]("OriginalSetting")
    assert len(parse_calls) == 2, "File should be re-parsed when mtime differs"

    settings_mod._search_cache.clear()


# ---------------------------------------------------------------------------
# Bitbucket reviewer ID routing (Fix 2)
# ---------------------------------------------------------------------------

def test_bitbucket_reviewer_uuid_sends_account_id(monkeypatch):
    """Reviewer strings starting with '{' should be sent as account_id (Bitbucket Cloud)."""
    monkeypatch.setattr(config.settings, "bitbucket_workspace", "acme")
    monkeypatch.setattr(config.settings, "bitbucket_repo_slug", "gpo")
    monkeypatch.setattr(config.settings, "bitbucket_token", "tok")

    captured_payloads = []

    def fake_request_json(url, method, payload=None):
        captured_payloads.append(payload)
        return True, {"id": 1, "links": {"html": {"href": "http://pr/1"}}}

    svc = BitbucketService()
    monkeypatch.setattr(svc, "_request_json", fake_request_json)

    svc.create_pull_request(
        title="test",
        source_branch="feature/x",
        target_branch="main",
        reviewer_usernames=["{abc-1234-def}"],
    )

    assert len(captured_payloads) == 1
    reviewers = captured_payloads[0]["reviewers"]
    assert reviewers == [{"account_id": "{abc-1234-def}"}]


def test_bitbucket_reviewer_username_sends_username(monkeypatch):
    """Plain username strings (no '{') should be sent as username (backward compat)."""
    monkeypatch.setattr(config.settings, "bitbucket_workspace", "acme")
    monkeypatch.setattr(config.settings, "bitbucket_repo_slug", "gpo")
    monkeypatch.setattr(config.settings, "bitbucket_token", "tok")

    captured_payloads = []

    def fake_request_json(url, method, payload=None):
        captured_payloads.append(payload)
        return True, {"id": 1, "links": {"html": {"href": "http://pr/1"}}}

    svc = BitbucketService()
    monkeypatch.setattr(svc, "_request_json", fake_request_json)

    svc.create_pull_request(
        title="test",
        source_branch="feature/x",
        target_branch="main",
        reviewer_usernames=["alice"],
    )

    assert len(captured_payloads) == 1
    reviewers = captured_payloads[0]["reviewers"]
    assert reviewers == [{"username": "alice"}]


def test_bitbucket_reviewer_mixed_formats(monkeypatch):
    """Mixed UUID and username reviewers should each use the correct field."""
    monkeypatch.setattr(config.settings, "bitbucket_workspace", "acme")
    monkeypatch.setattr(config.settings, "bitbucket_repo_slug", "gpo")
    monkeypatch.setattr(config.settings, "bitbucket_token", "tok")

    captured_payloads = []

    def fake_request_json(url, method, payload=None):
        captured_payloads.append(payload)
        return True, {"id": 1, "links": {"html": {"href": "http://pr/1"}}}

    svc = BitbucketService()
    monkeypatch.setattr(svc, "_request_json", fake_request_json)

    svc.create_pull_request(
        title="test",
        source_branch="feature/x",
        target_branch="main",
        reviewer_usernames=["{uuid-1234}", "bob"],
    )

    reviewers = captured_payloads[0]["reviewers"]
    assert {"account_id": "{uuid-1234}"} in reviewers
    assert {"username": "bob"} in reviewers


# ---------------------------------------------------------------------------
# Bitbucket query URL encoding (Fix 3)
# ---------------------------------------------------------------------------

def test_bitbucket_find_pr_url_encodes_branch_names(monkeypatch):
    """find_open_pull_request() should URL-encode branch names in the query string."""
    monkeypatch.setattr(config.settings, "bitbucket_workspace", "acme")
    monkeypatch.setattr(config.settings, "bitbucket_repo_slug", "gpo")
    monkeypatch.setattr(config.settings, "bitbucket_token", "tok")

    captured_urls = []

    def fake_request_json(url, method, payload=None):
        captured_urls.append(url)
        return True, {"values": []}

    svc = BitbucketService()
    monkeypatch.setattr(svc, "_request_json", fake_request_json)

    # Branch with slash and space (tricky chars for URL)
    svc.find_open_pull_request(
        source_branch='feature/my branch "quoted"',
        target_branch="main",
    )

    assert len(captured_urls) == 1
    url = captured_urls[0]
    # Raw space and unescaped quote should NOT appear in the query string
    assert " " not in url.split("?", 1)[1] if "?" in url else True
    # URL should be properly formed (contains 'q=' parameter)
    assert "q=" in url

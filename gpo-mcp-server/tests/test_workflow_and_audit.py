"""Tests for workflow guardrails and audit safety."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import config
from app.core.audit import (
    AuditAction,
    AuditStatus,
    _is_sensitive_key,
    _redact_sensitive_value,
    audit_event,
    clear_correlation_id,
    get_correlation_id,
    set_correlation_id,
)
from app.services.bitbucket_service import PRLookupResult
from app.services.git_service import GitService
from app.tools.git import register_git_tools
from app.tools.workflow import register_workflow_tools


class FakeMCP:
    """Minimal MCP stub that captures registered tools."""

    def __init__(self):
        self.tools = {}

    def tool(self):
        def decorator(func):
            self.tools[func.__name__] = func
            return func

        return decorator


# ---------------------------------------------------------------------------
# Direct-commit blocking
# ---------------------------------------------------------------------------

def test_commit_changes_blocked_when_direct_writes_disabled(monkeypatch):
    """gpo_commit_changes should block immediately when direct writes are disabled."""
    monkeypatch.setattr(config.settings, "enforce_backend_boundary", False)
    monkeypatch.setattr(config.settings, "allow_direct_git_writes", False)

    mcp = FakeMCP()
    register_git_tools(mcp)

    out = mcp.tools["gpo_commit_changes"]("test commit")
    assert out.startswith("ERROR: Direct git writes are disabled")


def test_commit_changes_blocked_when_backend_boundary_enforced(monkeypatch):
    """Direct commit path must be disabled when backend boundary is enforced."""
    monkeypatch.setattr(config.settings, "enforce_backend_boundary", True)
    monkeypatch.setattr(config.settings, "allow_direct_git_writes", True)

    mcp = FakeMCP()
    register_git_tools(mcp)

    out = mcp.tools["gpo_commit_changes"]("test commit")
    assert out.startswith("ERROR: Backend boundary is enforced")


# ---------------------------------------------------------------------------
# Protected branch enforcement
# ---------------------------------------------------------------------------

def test_commit_branch_changes_blocks_protected_branch(monkeypatch, temp_repo):
    """Branch workflow should reject commits to protected branches."""
    monkeypatch.setattr(config.settings, "enforce_backend_boundary", False)
    monkeypatch.setattr(config.settings, "allow_direct_git_writes", True)

    class FakeGitService:
        def __init__(self):
            self.repo_path = temp_repo

        def checkout_branch(self, branch_name: str):
            return True, "ok"

        def ensure_not_protected_branch(self):
            return False, "Direct commits to protected branch 'main' are blocked"

    import app.tools.workflow as workflow_mod

    monkeypatch.setattr(workflow_mod, "GitService", FakeGitService)

    mcp = FakeMCP()
    register_workflow_tools(mcp)

    out = mcp.tools["gpo_commit_branch_changes"]("test commit", "main")
    assert out.startswith("ERROR: Direct commits to protected branch")


# ---------------------------------------------------------------------------
# Audit event sanitisation
# ---------------------------------------------------------------------------

def test_audit_event_sanitizes_sensitive_details(monkeypatch, temp_repo):
    """Audit logger should redact sensitive keys before persisting."""
    audit_file = temp_repo / "audit" / "events.jsonl"
    monkeypatch.setattr(config.settings, "audit_log_path", audit_file)

    audit_event(
        action="submit_change_request",
        status="error",
        details={
            "token": "abc123",
            "nested": {"password": "p@ss", "safe": "ok"},
            "note": "x" * 500,
            "git_token": "should-be-redacted",
        },
    )

    lines = audit_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1

    payload = json.loads(lines[0])
    assert payload["details"]["token"] == "***"
    assert payload["details"]["nested"]["password"] == "***"
    assert payload["details"]["nested"]["safe"] == "ok"
    assert payload["details"]["note"].endswith("<truncated>")
    assert payload["details"]["git_token"] == "***"


def test_audit_redaction_uses_substring_matching(monkeypatch, temp_repo):
    """Audit redaction should match keys containing sensitive substrings."""
    audit_file = temp_repo / "audit" / "events.jsonl"
    monkeypatch.setattr(config.settings, "audit_log_path", audit_file)

    audit_event(
        action="test_op",
        status="success",
        details={
            "backend_api_token": "tok-abc",
            "bitbucket_token": "bb-xyz",
            "auth_header": "Bearer abc",
            "my_password_hash": "hash123",
            "secret_key": "s3cret",
            "safe_value": "this is fine",
        },
    )

    lines = audit_file.read_text(encoding="utf-8").strip().splitlines()
    payload = json.loads(lines[0])
    assert payload["details"]["backend_api_token"] == "***"
    assert payload["details"]["bitbucket_token"] == "***"
    assert payload["details"]["auth_header"] == "***"
    assert payload["details"]["my_password_hash"] == "***"
    assert payload["details"]["secret_key"] == "***"
    assert payload["details"]["safe_value"] == "this is fine"


def test_is_sensitive_key_helper():
    """_is_sensitive_key should catch substring matches."""
    assert _is_sensitive_key("token") is True
    assert _is_sensitive_key("git_token") is True
    assert _is_sensitive_key("backend_api_token") is True
    assert _is_sensitive_key("PASSWORD") is True
    assert _is_sensitive_key("my_secret_key") is True
    assert _is_sensitive_key("Authorization") is True
    assert _is_sensitive_key("auth_header_value") is True
    assert _is_sensitive_key("safe_field") is False
    assert _is_sensitive_key("branch") is False
    assert _is_sensitive_key("note") is False


def test_audit_event_uses_enum_values(monkeypatch, temp_repo):
    """Audit events with enum action/status should serialize to plain strings."""
    audit_file = temp_repo / "audit" / "events.jsonl"
    monkeypatch.setattr(config.settings, "audit_log_path", audit_file)

    audit_event(
        action=AuditAction.COMMIT_CHANGES,
        status=AuditStatus.BLOCKED,
        details={"reason": "test"},
    )

    lines = audit_file.read_text(encoding="utf-8").strip().splitlines()
    payload = json.loads(lines[0])
    assert payload["action"] == "commit_changes"
    assert payload["status"] == "blocked"


def test_audit_correlation_id(monkeypatch, temp_repo):
    """Correlation ID should appear in audit events when set."""
    audit_file = temp_repo / "audit" / "events.jsonl"
    monkeypatch.setattr(config.settings, "audit_log_path", audit_file)

    cid = set_correlation_id("test-corr-123")
    assert cid == "test-corr-123"
    assert get_correlation_id() == "test-corr-123"

    audit_event(action="test_op", status="success", details={})

    clear_correlation_id()
    assert get_correlation_id() is None

    lines = audit_file.read_text(encoding="utf-8").strip().splitlines()
    payload = json.loads(lines[0])
    assert payload["correlation_id"] == "test-corr-123"


def test_audit_no_correlation_id_when_not_set(monkeypatch, temp_repo):
    """When no correlation ID is set, it should not appear in the payload."""
    audit_file = temp_repo / "audit" / "events.jsonl"
    monkeypatch.setattr(config.settings, "audit_log_path", audit_file)

    clear_correlation_id()
    audit_event(action="test_op", status="success", details={})

    lines = audit_file.read_text(encoding="utf-8").strip().splitlines()
    payload = json.loads(lines[0])
    assert "correlation_id" not in payload


def test_audit_fallback_when_path_unwritable(monkeypatch, temp_repo):
    """Audit should not raise when log path parent is unwritable."""
    audit_file = Path("/nonexistent/deeply/nested/audit.jsonl")
    monkeypatch.setattr(config.settings, "audit_log_path", audit_file)

    # Should not raise — just logs to logger
    audit_event(action="test_op", status="success", details={})


# ---------------------------------------------------------------------------
# Correlation IDs wired into workflow tools
# ---------------------------------------------------------------------------

def test_workflow_tools_set_and_clear_correlation_id(monkeypatch):
    """Workflow tools should set and then clear correlation IDs."""
    monkeypatch.setattr(config.settings, "enforce_backend_boundary", False)
    monkeypatch.setattr(config.settings, "allow_direct_git_writes", False)

    # Ensure clean state
    clear_correlation_id()
    assert get_correlation_id() is None

    mcp = FakeMCP()
    register_git_tools(mcp)

    # gpo_commit_changes should set a correlation ID internally and clear on exit
    mcp.tools["gpo_commit_changes"]("test")
    assert get_correlation_id() is None  # cleared after tool call


def test_workflow_pr_tool_clears_correlation_id(monkeypatch):
    """gpo_create_pull_request should clear correlation ID even on early return."""
    monkeypatch.setattr(config.settings, "allowed_pr_target_branches", ("main",))


    clear_correlation_id()

    mcp = FakeMCP()
    register_workflow_tools(mcp)

    # Should return early (empty source branch) but still clean up correlation ID
    mcp.tools["gpo_create_pull_request"](
        title="test", source_branch="", target_branch="main",
        description="", reviewers_csv="",
    )
    assert get_correlation_id() is None


# ---------------------------------------------------------------------------
# Git credential and branch safety
# ---------------------------------------------------------------------------

def test_git_authenticated_url_supports_bitbucket(monkeypatch, temp_repo):
    """Git token URL rewrite should work for generic HTTPS remotes, including Bitbucket."""
    monkeypatch.setattr(config.settings, "repo_path", temp_repo)
    monkeypatch.setattr(config.settings, "repo_url", "https://bitbucket.org/acme/gpo.git")
    monkeypatch.setattr(config.settings, "git_token", "TOKEN123")

    svc = GitService()
    auth_url = svc._get_authenticated_url()
    assert auth_url is not None
    assert auth_url.startswith("https://git:TOKEN123@bitbucket.org/")


def test_git_rejects_invalid_branch_name(monkeypatch, temp_repo):
    """GitService should reject invalid branch names before executing commands."""
    monkeypatch.setattr(config.settings, "repo_path", temp_repo)
    monkeypatch.setattr(config.settings, "repo_url", "https://bitbucket.org/acme/gpo.git")
    monkeypatch.setattr(config.settings, "git_token", "TOKEN123")

    svc = GitService()
    ok, msg = svc.create_branch("bad..branch", checkout=True)
    assert not ok
    assert msg == "Invalid branch name"


def test_git_branch_exists_prevents_duplicate(monkeypatch, temp_repo):
    """create_branch() should fail if the branch already exists locally."""
    monkeypatch.setattr(config.settings, "repo_path", temp_repo)
    monkeypatch.setattr(config.settings, "repo_url", "https://example.com/repo.git")
    monkeypatch.setattr(config.settings, "git_token", None)

    svc = GitService()
    # Monkey-patch branch_exists to simulate existing branch
    monkeypatch.setattr(svc, "branch_exists", lambda name: True)
    ok, msg = svc.create_branch("existing-branch", checkout=True)
    assert not ok
    assert "already exists" in msg


def test_git_remote_branch_exists_prevents_duplicate(monkeypatch, temp_repo):
    """create_branch() should fail if the branch already exists on the remote."""
    monkeypatch.setattr(config.settings, "repo_path", temp_repo)
    monkeypatch.setattr(config.settings, "repo_url", "https://example.com/repo.git")
    monkeypatch.setattr(config.settings, "git_token", None)

    svc = GitService()
    monkeypatch.setattr(svc, "branch_exists", lambda name: False)
    monkeypatch.setattr(svc, "remote_branch_exists", lambda name, remote="origin": True)
    ok, msg = svc.create_branch("remote-only-branch", checkout=True)
    assert not ok
    assert "already exists on remote" in msg


def test_git_error_message_masks_token(monkeypatch, temp_repo):
    """Exception messages from git commands should have the token masked."""
    monkeypatch.setattr(config.settings, "repo_path", temp_repo)
    monkeypatch.setattr(config.settings, "repo_url", "https://example.com/repo.git")
    monkeypatch.setattr(config.settings, "git_token", "SUPERSECRET")

    svc = GitService()
    # Use a command that will fail (not a real git command)
    ok, msg = svc.run_command(["not-a-real-command"])
    # If the error message somehow had the token, it should be masked
    assert "SUPERSECRET" not in msg


def test_git_commit_message_validation(monkeypatch, temp_repo):
    """Commit should reject empty or too-long messages."""
    monkeypatch.setattr(config.settings, "repo_path", temp_repo)
    monkeypatch.setattr(config.settings, "repo_url", None)
    monkeypatch.setattr(config.settings, "git_token", None)

    svc = GitService()
    ok1, msg1 = svc.commit("")
    assert not ok1
    assert "empty" in msg1.lower()

    ok2, msg2 = svc.commit("x" * 1001)
    assert not ok2
    assert "too long" in msg2.lower()


def test_git_clone_or_pull_fails_when_status_fails(monkeypatch, temp_repo):
    """clone_or_pull() must fail when git status itself errors out."""
    monkeypatch.setattr(config.settings, "repo_path", temp_repo)
    monkeypatch.setattr(config.settings, "repo_url", "https://example.com/repo.git")
    monkeypatch.setattr(config.settings, "git_token", None)

    # Create a .git dir so we enter the pull path
    (temp_repo / ".git").mkdir()

    svc = GitService()
    # Fake get_status to return failure
    monkeypatch.setattr(svc, "get_status", lambda: (False, "permission denied"))
    ok, msg = svc.clone_or_pull()
    assert not ok
    assert "Failed to determine repository status" in msg


# ---------------------------------------------------------------------------
# PR workflow validation
# ---------------------------------------------------------------------------

def test_create_pull_request_blocks_disallowed_target(monkeypatch):
    """Workflow should reject PRs targeting disallowed branches."""
    monkeypatch.setattr(config.settings, "allowed_pr_target_branches", ("main",))


    class FakeBitbucketService:
        def find_open_pull_request(self, source_branch: str, target_branch: str):
            return PRLookupResult.NOT_FOUND, {}

        def create_pull_request(self, **kwargs):
            return True, {"id": 1, "links": {"html": {"href": "http://example"}}}

    import app.tools.workflow as workflow_mod

    monkeypatch.setattr(workflow_mod, "BitbucketService", FakeBitbucketService)

    mcp = FakeMCP()
    register_workflow_tools(mcp)
    out = mcp.tools["gpo_create_pull_request"](
        title="test",
        source_branch="gpo/abc",
        target_branch="release",
        description="",
        reviewers_csv="",
    )

    assert out.startswith("ERROR: target_branch is not allowed")


def test_create_pull_request_blocks_duplicate_open_pr(monkeypatch):
    """Workflow should block duplicate open PRs for same source/target."""
    monkeypatch.setattr(config.settings, "allowed_pr_target_branches", ("main",))


    class FakeBitbucketService:
        def find_open_pull_request(self, source_branch: str, target_branch: str):
            return PRLookupResult.FOUND, {"id": 123, "links": {"html": {"href": "http://pr/123"}}}

        def create_pull_request(self, **kwargs):
            return True, {"id": 1, "links": {"html": {"href": "http://example"}}}

    import app.tools.workflow as workflow_mod

    monkeypatch.setattr(workflow_mod, "BitbucketService", FakeBitbucketService)

    mcp = FakeMCP()
    register_workflow_tools(mcp)
    out = mcp.tools["gpo_create_pull_request"](
        title="test",
        source_branch="gpo/abc",
        target_branch="main",
        description="",
        reviewers_csv="",
    )

    assert out.startswith("ERROR: Open pull request already exists")


def test_create_pull_request_blocks_on_lookup_failure(monkeypatch):
    """Workflow should refuse to create PR when duplicate check fails."""
    monkeypatch.setattr(config.settings, "allowed_pr_target_branches", ("main",))


    class FakeBitbucketService:
        def find_open_pull_request(self, source_branch: str, target_branch: str):
            return PRLookupResult.LOOKUP_FAILED, {"error": "HTTP 503"}

        def create_pull_request(self, **kwargs):
            return True, {"id": 1, "links": {"html": {"href": "http://example"}}}

    import app.tools.workflow as workflow_mod

    monkeypatch.setattr(workflow_mod, "BitbucketService", FakeBitbucketService)

    mcp = FakeMCP()
    register_workflow_tools(mcp)
    out = mcp.tools["gpo_create_pull_request"](
        title="test",
        source_branch="gpo/abc",
        target_branch="main",
        description="",
        reviewers_csv="",
    )

    assert "Could not verify" in out
    assert "Duplicate check failed" in out


def test_submit_change_request_requires_configured_backend(monkeypatch):
    """gpo_submit_change_request should fail when backend is not fully configured."""
    # Token is None -> is_configured returns False
    monkeypatch.setattr(config.settings, "backend_api_url", "http://localhost:8088")
    monkeypatch.setattr(config.settings, "backend_api_token", None)

    mcp = FakeMCP()
    register_workflow_tools(mcp)
    out = mcp.tools["gpo_submit_change_request"](
        operation="create_pr_change",
        payload_json='{"message":"test"}',
        request_id="",
    )
    assert "not fully configured" in out


def test_create_pull_request_empty_source_branch(monkeypatch):
    """PR creation should reject empty source branch."""
    monkeypatch.setattr(config.settings, "allowed_pr_target_branches", ("main",))


    mcp = FakeMCP()
    register_workflow_tools(mcp)
    out = mcp.tools["gpo_create_pull_request"](
        title="test",
        source_branch="",
        target_branch="main",
        description="",
        reviewers_csv="",
    )
    assert "source_branch cannot be empty" in out


# ---------------------------------------------------------------------------
# fetch_before_check parameter on create_branch
# ---------------------------------------------------------------------------

def test_git_create_branch_fetch_before_check_calls_fetch(monkeypatch, temp_repo):
    """create_branch(fetch_before_check=True) should call fetch_remote() first."""
    monkeypatch.setattr(config.settings, "repo_path", temp_repo)
    monkeypatch.setattr(config.settings, "repo_url", "https://example.com/repo.git")
    monkeypatch.setattr(config.settings, "git_token", None)

    svc = GitService()
    fetch_calls = []

    def fake_fetch(remote="origin"):
        fetch_calls.append(remote)
        return True, "fetched"

    monkeypatch.setattr(svc, "branch_exists", lambda name: False)
    monkeypatch.setattr(svc, "fetch_remote", fake_fetch)
    monkeypatch.setattr(svc, "remote_branch_exists", lambda name, remote="origin": False)
    # Intercept the actual git checkout so we don't need a real repo
    monkeypatch.setattr(svc, "run_command", lambda args, **kw: (True, "ok"))

    svc.create_branch("feature/test", checkout=True, fetch_before_check=True)

    assert len(fetch_calls) == 1, "fetch_remote should be called exactly once"


def test_git_create_branch_fetch_failure_aborts(monkeypatch, temp_repo):
    """create_branch should abort and return failure when fetch_remote fails."""
    monkeypatch.setattr(config.settings, "repo_path", temp_repo)
    monkeypatch.setattr(config.settings, "repo_url", "https://example.com/repo.git")
    monkeypatch.setattr(config.settings, "git_token", None)

    svc = GitService()
    monkeypatch.setattr(svc, "branch_exists", lambda name: False)
    monkeypatch.setattr(svc, "fetch_remote", lambda remote="origin": (False, "network timeout"))

    ok, msg = svc.create_branch("feature/test", checkout=True, fetch_before_check=True)

    assert not ok
    assert "Failed to fetch remote refs" in msg
    assert "network timeout" in msg


def test_git_create_branch_best_effort_no_fetch(monkeypatch, temp_repo):
    """create_branch() with default fetch_before_check=False must not call fetch_remote."""
    monkeypatch.setattr(config.settings, "repo_path", temp_repo)
    monkeypatch.setattr(config.settings, "repo_url", "https://example.com/repo.git")
    monkeypatch.setattr(config.settings, "git_token", None)

    svc = GitService()
    fetch_calls = []

    def fake_fetch(remote="origin"):
        fetch_calls.append(remote)
        return True, "fetched"

    monkeypatch.setattr(svc, "branch_exists", lambda name: False)
    monkeypatch.setattr(svc, "fetch_remote", fake_fetch)
    monkeypatch.setattr(svc, "remote_branch_exists", lambda name, remote="origin": False)
    monkeypatch.setattr(svc, "run_command", lambda args, **kw: (True, "ok"))

    svc.create_branch("feature/test", checkout=True)  # fetch_before_check defaults to False

    assert fetch_calls == [], "fetch_remote must NOT be called with default fetch_before_check=False"


# ---------------------------------------------------------------------------
# Correlation ID cleared on tool exception
# ---------------------------------------------------------------------------

def test_correlation_id_cleared_on_tool_exception(monkeypatch):
    """Correlation ID must be cleared even when the tool body raises an exception."""
    monkeypatch.setattr(config.settings, "enforce_backend_boundary", False)
    monkeypatch.setattr(config.settings, "allow_direct_git_writes", True)

    import app.tools.git as git_mod

    class ExplodingGitService:
        def __init__(self):
            _repo = type("P", (), {"exists": lambda self: True})()
            self.repo_path = _repo

        def ensure_not_protected_branch(self):
            raise RuntimeError("simulated internal failure")

    monkeypatch.setattr(git_mod, "GitService", ExplodingGitService)

    clear_correlation_id()
    mcp = FakeMCP()
    register_git_tools(mcp)

    with pytest.raises(RuntimeError, match="simulated internal failure"):
        mcp.tools["gpo_commit_changes"]("test commit")

    # The finally block must have cleared the correlation ID even under exception
    assert get_correlation_id() is None


# ---------------------------------------------------------------------------
# Git auth URL encoding (Fix 1)
# ---------------------------------------------------------------------------

def test_git_auth_url_encodes_plain_token(monkeypatch, temp_repo):
    """Plain API tokens (no colon) should be URL-encoded with 'git' username."""
    monkeypatch.setattr(config.settings, "repo_path", temp_repo)
    monkeypatch.setattr(config.settings, "repo_url", "https://github.com/acme/gpo.git")
    monkeypatch.setattr(config.settings, "git_token", "tok@en#with%special")

    svc = GitService()
    auth_url = svc._get_authenticated_url()
    assert auth_url is not None
    # '@' → %40, '#' → %23, '%' → %25
    assert "tok%40en%23with%25special" in auth_url
    assert auth_url.startswith("https://git:")
    # Raw special chars must NOT appear in authority component
    assert "@" not in auth_url.split("@", 1)[0].replace("https://", "")


def test_git_auth_url_encodes_user_pass_format(monkeypatch, temp_repo):
    """Bitbucket-style 'user:app-password' tokens should encode both parts."""
    monkeypatch.setattr(config.settings, "repo_path", temp_repo)
    monkeypatch.setattr(config.settings, "repo_url", "https://bitbucket.org/acme/gpo.git")
    monkeypatch.setattr(config.settings, "git_token", "myuser:p@ss:w0rd!")

    svc = GitService()
    auth_url = svc._get_authenticated_url()
    assert auth_url is not None
    # '@' in password part → %40; second ':' → %3A; '!' → %21
    assert "myuser" in auth_url
    assert "p%40ss%3Aw0rd%21" in auth_url
    # Should NOT use the synthetic "git" username when format is user:pass
    assert "https://git:" not in auth_url
    assert auth_url.startswith("https://myuser:")


# ---------------------------------------------------------------------------
# Branch name normalization (Fix 11)
# ---------------------------------------------------------------------------

def test_git_rejects_double_slash_branch_name(monkeypatch, temp_repo):
    """Branch names containing '//' should be rejected."""
    monkeypatch.setattr(config.settings, "repo_path", temp_repo)
    monkeypatch.setattr(config.settings, "repo_url", "https://example.com/repo.git")
    monkeypatch.setattr(config.settings, "git_token", None)

    svc = GitService()
    ok, msg = svc.create_branch("feature//bad-branch", checkout=True)
    assert not ok
    assert msg == "Invalid branch name"


# ---------------------------------------------------------------------------
# Audit value-level redaction (Fix 6)
# ---------------------------------------------------------------------------

def test_audit_redacts_bearer_token_in_string_value(monkeypatch, temp_repo):
    """Audit should scrub 'Bearer <token>' from non-sensitive-keyed string values."""
    audit_file = temp_repo / "audit" / "events.jsonl"
    monkeypatch.setattr(config.settings, "audit_log_path", audit_file)

    audit_event(
        action="test_op",
        status="error",
        details={
            "detail": "The server responded: Authorization: Bearer supersecrettoken123",
        },
    )

    lines = audit_file.read_text(encoding="utf-8").strip().splitlines()
    payload = json.loads(lines[0])
    assert "supersecrettoken123" not in payload["details"]["detail"]
    assert "Bearer ***" in payload["details"]["detail"]


def test_audit_redacts_token_eq_pattern_in_value(monkeypatch, temp_repo):
    """Audit should scrub 'token=<value>' from string values."""
    audit_file = temp_repo / "audit" / "events.jsonl"
    monkeypatch.setattr(config.settings, "audit_log_path", audit_file)

    audit_event(
        action="test_op",
        status="error",
        details={"url": "https://example.com/api?token=mySecretValue&foo=bar"},
    )

    lines = audit_file.read_text(encoding="utf-8").strip().splitlines()
    payload = json.loads(lines[0])
    assert "mySecretValue" not in payload["details"]["url"]
    assert "token=***" in payload["details"]["url"]


def test_redact_sensitive_value_helper():
    """_redact_sensitive_value should apply all patterns."""
    result = _redact_sensitive_value("Error: Bearer abc123 and password=hunter2 in log")
    assert "abc123" not in result
    assert "hunter2" not in result
    assert "Bearer ***" in result
    assert "password=***" in result


# ---------------------------------------------------------------------------
# checkout_tracking_branch (Fix 4)
# ---------------------------------------------------------------------------

def test_checkout_tracking_branch_runs_correct_command(monkeypatch, temp_repo):
    """checkout_tracking_branch() should invoke git checkout --track origin/<branch>."""
    monkeypatch.setattr(config.settings, "repo_path", temp_repo)
    monkeypatch.setattr(config.settings, "repo_url", "https://example.com/repo.git")
    monkeypatch.setattr(config.settings, "git_token", None)

    svc = GitService()
    captured_args = []

    def fake_run(args, **kw):
        captured_args.extend(args)
        return True, "Branch 'remote-feature' set up to track remote branch"

    monkeypatch.setattr(svc, "run_command", fake_run)

    ok, msg = svc.checkout_tracking_branch("remote-feature")
    assert ok
    assert captured_args == ["checkout", "--track", "origin/remote-feature"]


def test_checkout_tracking_branch_rejects_invalid_name(monkeypatch, temp_repo):
    """checkout_tracking_branch() should reject invalid branch names."""
    monkeypatch.setattr(config.settings, "repo_path", temp_repo)
    monkeypatch.setattr(config.settings, "repo_url", "https://example.com/repo.git")
    monkeypatch.setattr(config.settings, "git_token", None)

    svc = GitService()
    ok, msg = svc.checkout_tracking_branch("bad..branch")
    assert not ok
    assert "Invalid branch name" in msg

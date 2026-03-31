"""Tests for configuration validation."""

from __future__ import annotations

from app.config import Settings


def test_validate_warns_backend_boundary_without_url():
    """validate() should warn when backend boundary is enforced but URL is missing."""
    s = Settings(
        repo_path="/tmp/test",
        repo_url="https://example.com/repo.git",
        git_token=None,
        protected_branches=("main",),
        default_target_branch="main",
        allowed_pr_target_branches=("main",),
        backend_api_url=None,
        backend_api_token=None,
        backend_api_host="127.0.0.1",
        backend_api_port=8088,
        bitbucket_workspace=None,
        bitbucket_repo_slug=None,
        bitbucket_token=None,
        max_bytes_per_req=50_000_000,
        allow_direct_git_writes=False,
        enforce_backend_boundary=True,
        audit_log_path=None,
        environment="test",
    )
    warnings = s.validate()
    assert any("GPO_BACKEND_API_URL" in w for w in warnings)


def test_validate_warns_backend_url_without_token():
    """validate() should warn when backend URL is set but token is missing."""
    s = Settings(
        repo_path="/tmp/test",
        repo_url="https://example.com/repo.git",
        git_token=None,
        protected_branches=("main",),
        default_target_branch="main",
        allowed_pr_target_branches=("main",),
        backend_api_url="http://localhost:8088",
        backend_api_token=None,
        backend_api_host="127.0.0.1",
        backend_api_port=8088,
        bitbucket_workspace=None,
        bitbucket_repo_slug=None,
        bitbucket_token=None,
        max_bytes_per_req=50_000_000,
        allow_direct_git_writes=False,
        enforce_backend_boundary=False,
        audit_log_path=None,
        environment="test",
    )
    warnings = s.validate()
    assert any("GPO_BACKEND_API_TOKEN" in w for w in warnings)


def test_validate_warns_permissive_flags():
    """validate() should warn when permissive security flags are active."""
    s = Settings(
        repo_path="/tmp/test",
        repo_url="https://example.com/repo.git",
        git_token=None,
        protected_branches=("main",),
        default_target_branch="main",
        allowed_pr_target_branches=("main",),
        backend_api_url=None,
        backend_api_token=None,
        backend_api_host="127.0.0.1",
        backend_api_port=8088,
        bitbucket_workspace=None,
        bitbucket_repo_slug=None,
        bitbucket_token=None,
        max_bytes_per_req=50_000_000,
        allow_direct_git_writes=True,
        enforce_backend_boundary=False,
        audit_log_path=None,
        environment="test",
    )
    warnings = s.validate()
    assert any("ALLOW_DIRECT_GIT_WRITES" in w for w in warnings)
    assert any("ENFORCE_BACKEND_BOUNDARY" in w for w in warnings)


def test_validate_warns_partial_bitbucket_config():
    """validate() should warn when Bitbucket is only partially configured."""
    s = Settings(
        repo_path="/tmp/test",
        repo_url="https://example.com/repo.git",
        git_token=None,
        protected_branches=("main",),
        default_target_branch="main",
        allowed_pr_target_branches=("main",),
        backend_api_url=None,
        backend_api_token=None,
        backend_api_host="127.0.0.1",
        backend_api_port=8088,
        bitbucket_workspace="acme",
        bitbucket_repo_slug=None,
        bitbucket_token=None,
        max_bytes_per_req=50_000_000,
        allow_direct_git_writes=False,
        enforce_backend_boundary=True,
        audit_log_path=None,
        environment="test",
    )
    warnings = s.validate()
    assert any("partially configured" in w for w in warnings)


def test_validate_clean_config_no_warnings():
    """validate() should return no warnings for a fully consistent config."""
    s = Settings(
        repo_path="/tmp/test",
        repo_url="https://example.com/repo.git",
        git_token="tok",
        protected_branches=("main",),
        default_target_branch="main",
        allowed_pr_target_branches=("main",),
        backend_api_url="http://localhost:8088",
        backend_api_token="secret",
        backend_api_host="127.0.0.1",
        backend_api_port=8088,
        bitbucket_workspace="acme",
        bitbucket_repo_slug="gpo-repo",
        bitbucket_token="bb-tok",
        max_bytes_per_req=50_000_000,
        allow_direct_git_writes=False,
        enforce_backend_boundary=True,
        audit_log_path=None,
        environment="production",
    )
    warnings = s.validate()
    assert warnings == []

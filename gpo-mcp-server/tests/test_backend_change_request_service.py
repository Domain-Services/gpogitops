"""Tests for internal backend change-request execution service."""

from __future__ import annotations

from app import config
from app.backend.change_request_service import ChangeRequestService
from app.services.bitbucket_service import PRLookupResult


class FakeGitService:
    def __init__(self):
        self.repo_path = config.settings.repo_path

    def create_branch(self, branch_name: str, checkout: bool = True):
        return True, "created"

    def checkout_branch(self, branch_name: str):
        return True, "checked out"

    def ensure_not_protected_branch(self):
        return True, "gpo/test"

    def get_status(self):
        return True, " M test.xml"

    def stage_xml_changes(self):
        return True, "staged"

    def commit(self, message: str):
        return True, "committed"

    def push_branch(self, branch_name: str, set_upstream: bool = True):
        return True, "pushed"


class FakeBitbucketService:
    def find_open_pull_request(self, source_branch: str, target_branch: str):
        return PRLookupResult.NOT_FOUND, {}

    def create_pull_request(self, **kwargs):
        return True, {"id": 101, "links": {"html": {"href": "http://pr/101"}}}


class FakeBitbucketDuplicate:
    """Bitbucket service that always finds an existing open PR."""

    def find_open_pull_request(self, source_branch: str, target_branch: str):
        return PRLookupResult.FOUND, {"id": 99, "links": {"html": {"href": "http://pr/99"}}}

    def create_pull_request(self, **kwargs):
        return True, {"id": 101, "links": {"html": {"href": "http://pr/101"}}}


class FakeBitbucketLookupFailed:
    """Bitbucket service that simulates a failed duplicate PR lookup."""

    def find_open_pull_request(self, source_branch: str, target_branch: str):
        return PRLookupResult.LOOKUP_FAILED, {"error": "HTTP 500"}

    def create_pull_request(self, **kwargs):
        return True, {"id": 101, "links": {"html": {"href": "http://pr/101"}}}


class FakeGitNoChanges:
    """Git service that reports no uncommitted changes."""

    def __init__(self):
        self.repo_path = config.settings.repo_path

    def create_branch(self, branch_name, checkout=True):
        return True, "created"

    def checkout_branch(self, branch_name):
        return True, "ok"

    def ensure_not_protected_branch(self):
        return True, "gpo/test"

    def get_status(self):
        return True, ""  # no changes

    def stage_xml_changes(self):
        return True, "staged"

    def commit(self, message):
        return True, "committed"

    def push_branch(self, branch_name, set_upstream=True):
        return True, "pushed"


def test_change_request_requires_supported_operation(monkeypatch):
    svc = ChangeRequestService(git_factory=FakeGitService, bitbucket_factory=FakeBitbucketService)
    status, payload = svc.handle_request({"operation": "unknown", "payload": {}})
    assert status == 400
    assert payload["error"] == "Unsupported operation"


def test_create_pr_change_success(monkeypatch, temp_repo):
    monkeypatch.setattr(config.settings, "repo_path", temp_repo)
    monkeypatch.setattr(config.settings, "allowed_pr_target_branches", ("main",))

    svc = ChangeRequestService(git_factory=FakeGitService, bitbucket_factory=FakeBitbucketService)
    status, payload = svc.handle_request(
        {
            "operation": "create_pr_change",
            "request_id": "REQ-1",
            "payload": {
                "message": "update setting",
                "title": "Update setting",
                "description": "desc",
                "source_branch": "gpo/req-1",
                "target_branch": "main",
                "reviewers": ["alice"],
            },
        }
    )

    assert status == 202
    assert payload["status"] == "submitted"
    assert payload["pull_request"]["id"] == 101


def test_create_pr_change_rejects_disallowed_target(monkeypatch, temp_repo):
    monkeypatch.setattr(config.settings, "repo_path", temp_repo)
    monkeypatch.setattr(config.settings, "allowed_pr_target_branches", ("main",))

    svc = ChangeRequestService(git_factory=FakeGitService, bitbucket_factory=FakeBitbucketService)
    status, payload = svc.handle_request(
        {
            "operation": "create_pr_change",
            "payload": {
                "message": "update setting",
                "title": "Update setting",
                "target_branch": "release",
            },
        }
    )

    assert status == 400
    assert payload["error"] == "target_branch not allowed"


def test_create_pr_change_missing_message(monkeypatch, temp_repo):
    """Should reject requests with empty message."""
    monkeypatch.setattr(config.settings, "repo_path", temp_repo)
    monkeypatch.setattr(config.settings, "allowed_pr_target_branches", ("main",))


    svc = ChangeRequestService(git_factory=FakeGitService, bitbucket_factory=FakeBitbucketService)
    status, payload = svc.handle_request(
        {
            "operation": "create_pr_change",
            "payload": {
                "message": "",
                "title": "Update setting",
                "target_branch": "main",
            },
        }
    )
    assert status == 400
    assert "message" in payload["error"].lower()


def test_create_pr_change_missing_title(monkeypatch, temp_repo):
    """Should reject requests with empty title."""
    monkeypatch.setattr(config.settings, "repo_path", temp_repo)
    monkeypatch.setattr(config.settings, "allowed_pr_target_branches", ("main",))


    svc = ChangeRequestService(git_factory=FakeGitService, bitbucket_factory=FakeBitbucketService)
    status, payload = svc.handle_request(
        {
            "operation": "create_pr_change",
            "payload": {
                "message": "update",
                "title": "",
                "target_branch": "main",
            },
        }
    )
    assert status == 400
    assert "title" in payload["error"].lower()


def test_create_pr_change_no_changes(monkeypatch, temp_repo):
    """Should return 409 when there are no uncommitted changes to commit."""
    monkeypatch.setattr(config.settings, "repo_path", temp_repo)
    monkeypatch.setattr(config.settings, "allowed_pr_target_branches", ("main",))


    svc = ChangeRequestService(git_factory=FakeGitNoChanges, bitbucket_factory=FakeBitbucketService)
    status, payload = svc.handle_request(
        {
            "operation": "create_pr_change",
            "payload": {
                "message": "update",
                "title": "Update",
                "target_branch": "main",
            },
        }
    )
    assert status == 409
    assert "no changes" in payload["error"].lower()


def test_create_pr_change_duplicate_pr(monkeypatch, temp_repo):
    """Should return 200 with duplicate status when PR already exists."""
    monkeypatch.setattr(config.settings, "repo_path", temp_repo)
    monkeypatch.setattr(config.settings, "allowed_pr_target_branches", ("main",))


    svc = ChangeRequestService(git_factory=FakeGitService, bitbucket_factory=FakeBitbucketDuplicate)
    status, payload = svc.handle_request(
        {
            "operation": "create_pr_change",
            "payload": {
                "message": "update",
                "title": "Update",
                "target_branch": "main",
            },
        }
    )
    assert status == 200
    assert payload["status"] == "duplicate_open_pr"
    assert payload["pull_request"]["id"] == 99


def test_create_pr_change_lookup_failed(monkeypatch, temp_repo):
    """Should return 502 when duplicate PR check fails (API error)."""
    monkeypatch.setattr(config.settings, "repo_path", temp_repo)
    monkeypatch.setattr(config.settings, "allowed_pr_target_branches", ("main",))


    svc = ChangeRequestService(git_factory=FakeGitService, bitbucket_factory=FakeBitbucketLookupFailed)
    status, payload = svc.handle_request(
        {
            "operation": "create_pr_change",
            "payload": {
                "message": "update",
                "title": "Update",
                "target_branch": "main",
            },
        }
    )
    assert status == 502
    assert "duplicate PR check failed" in payload["error"]


def test_handle_request_invalid_body():
    """Should reject non-dict request bodies."""
    svc = ChangeRequestService(git_factory=FakeGitService, bitbucket_factory=FakeBitbucketService)
    status, payload = svc.handle_request("not a dict")
    assert status == 400
    assert "invalid" in payload["error"].lower()


# ---------------------------------------------------------------------------
# Remote-only branch checkout fallback (Fix 4)
# ---------------------------------------------------------------------------

class FakeGitServiceRemoteOnly:
    """Git service where the branch exists only on the remote (not local)."""

    def __init__(self):
        self.repo_path = config.settings.repo_path
        self._tracking_calls = []

    def create_branch(self, branch_name: str, checkout: bool = True):
        return False, "Branch 'gpo/req-remote' already exists on remote"

    def checkout_branch(self, branch_name: str):
        # Fails because no local tracking ref exists yet
        return False, "error: pathspec 'gpo/req-remote' did not match any file(s) known to git"

    def checkout_tracking_branch(self, branch_name: str, remote: str = "origin"):
        self._tracking_calls.append(branch_name)
        return True, "Branch 'gpo/req-remote' set up to track 'origin/gpo/req-remote'"

    def ensure_not_protected_branch(self):
        return True, "gpo/req-remote"

    def get_status(self):
        return True, " M test.xml"

    def stage_xml_changes(self):
        return True, "staged"

    def commit(self, message: str):
        return True, "committed"

    def push_branch(self, branch_name: str, set_upstream: bool = True):
        return True, "pushed"


def test_create_pr_change_falls_back_to_tracking_branch(monkeypatch, temp_repo):
    """When create_branch and checkout_branch both fail, should try checkout_tracking_branch."""
    monkeypatch.setattr(config.settings, "repo_path", temp_repo)
    monkeypatch.setattr(config.settings, "allowed_pr_target_branches", ("main",))


    git_instance = FakeGitServiceRemoteOnly()
    git_instance.repo_path = temp_repo

    svc = ChangeRequestService(
        git_factory=lambda: git_instance,
        bitbucket_factory=FakeBitbucketService,
    )
    status, payload = svc.handle_request(
        {
            "operation": "create_pr_change",
            "request_id": "REQ-remote",
            "payload": {
                "message": "update setting",
                "title": "Update setting",
                "source_branch": "gpo/req-remote",
                "target_branch": "main",
            },
        }
    )

    assert status == 202, f"Expected 202, got {status}: {payload}"
    assert payload["status"] == "submitted"
    assert git_instance._tracking_calls == ["gpo/req-remote"]


class FakeGitServiceAllCheckoutsFail:
    """Git service where all branch checkout attempts fail."""

    def __init__(self):
        self.repo_path = config.settings.repo_path

    def create_branch(self, branch_name: str, checkout: bool = True):
        return False, "remote branch conflict"

    def checkout_branch(self, branch_name: str):
        return False, "no local ref"

    def checkout_tracking_branch(self, branch_name: str, remote: str = "origin"):
        return False, "remote branch not found"

    def ensure_not_protected_branch(self):
        return True, "gpo/test"

    def get_status(self):
        return True, " M test.xml"

    def stage_xml_changes(self):
        return True, "staged"

    def commit(self, message: str):
        return True, "committed"

    def push_branch(self, branch_name: str, set_upstream: bool = True):
        return True, "pushed"


def test_create_pr_change_fails_when_all_checkout_attempts_fail(monkeypatch, temp_repo):
    """Should return 409 when create, checkout, and tracking checkout all fail."""
    monkeypatch.setattr(config.settings, "repo_path", temp_repo)
    monkeypatch.setattr(config.settings, "allowed_pr_target_branches", ("main",))


    git_instance = FakeGitServiceAllCheckoutsFail()
    git_instance.repo_path = temp_repo

    svc = ChangeRequestService(
        git_factory=lambda: git_instance,
        bitbucket_factory=FakeBitbucketService,
    )
    status, payload = svc.handle_request(
        {
            "operation": "create_pr_change",
            "payload": {
                "message": "update setting",
                "title": "Update setting",
                "source_branch": "gpo/broken",
                "target_branch": "main",
            },
        }
    )
    assert status == 409
    assert "failed to prepare source branch" in payload["error"]

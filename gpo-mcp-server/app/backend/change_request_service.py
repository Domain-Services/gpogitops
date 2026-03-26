"""Backend service for privileged GPO change-request execution."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app import config
from app.core import audit_event
from app.core.audit import clear_correlation_id, set_correlation_id
from app.services import BitbucketService, GitService, PRLookupResult


class ChangeRequestService:
    """Executes approved backend operations.

    This service is intentionally server-side and should not be exposed directly
    to LLM-facing layers.
    """

    def __init__(self, git_factory=GitService, bitbucket_factory=BitbucketService):
        self.git_factory = git_factory
        self.bitbucket_factory = bitbucket_factory

    def handle_request(self, body: dict) -> tuple[int, dict]:
        """Validate and execute a change request payload."""
        if not isinstance(body, dict):
            return 400, {"error": "Invalid request body"}

        operation = str(body.get("operation", "")).strip()
        request_id = str(body.get("request_id", "")).strip() or str(uuid.uuid4())
        payload = body.get("payload", {})
        if not isinstance(payload, dict):
            return 400, {"error": "payload must be an object"}

        if operation != "create_pr_change":
            return 400, {"error": "Unsupported operation", "supported": ["create_pr_change"]}

        cid = set_correlation_id(request_id)
        try:
            status, response = self._create_pr_change(request_id=request_id, payload=payload)
            return status, response
        finally:
            clear_correlation_id()

    def _create_pr_change(self, request_id: str, payload: dict) -> tuple[int, dict]:
        """Create branch commit/push and open PR from pending repo changes."""
        message = str(payload.get("message", "")).strip()
        title = str(payload.get("title", "")).strip()
        description = str(payload.get("description", "")).strip()
        source_branch = str(payload.get("source_branch", "")).strip()
        target_branch = str(payload.get("target_branch", "")).strip() or config.settings.default_target_branch

        reviewers = payload.get("reviewers", [])
        if isinstance(reviewers, str):
            reviewers = [r.strip() for r in reviewers.split(",") if r.strip()]
        if not isinstance(reviewers, list):
            return 400, {"error": "reviewers must be a list or comma-separated string"}

        if not message:
            return 400, {"error": "payload.message is required"}
        if not title:
            return 400, {"error": "payload.title is required"}

        allowed_targets = set(config.settings.allowed_pr_target_branches)
        if allowed_targets and target_branch not in allowed_targets:
            return 400, {
                "error": "target_branch not allowed",
                "target_branch": target_branch,
                "allowed": sorted(allowed_targets),
            }

        if config.settings.require_pr_reviewers and len(reviewers) < config.settings.min_pr_reviewers:
            return 400, {
                "error": "insufficient reviewers",
                "required": config.settings.min_pr_reviewers,
                "received": len(reviewers),
            }

        git = self.git_factory()
        bb = self.bitbucket_factory()

        if not git.repo_path.exists():
            return 404, {"error": "Repository not found"}

        if not source_branch:
            source_branch = f"gpo/cr-{request_id[:8]}"

        create_ok, create_out = git.create_branch(source_branch, checkout=True)
        if not create_ok:
            # Branch may exist locally — try a plain checkout first.
            checkout_ok, checkout_out = git.checkout_branch(source_branch)
            if not checkout_ok:
                # Branch may exist only on the remote (no local tracking ref yet).
                # Use --track so git creates a local branch that tracks the remote.
                tracking_ok, tracking_out = git.checkout_tracking_branch(source_branch)
                if not tracking_ok:
                    return 409, {
                        "error": "failed to prepare source branch",
                        "branch": source_branch,
                        "detail": create_out or tracking_out,
                    }

        protected_ok, protected_detail = git.ensure_not_protected_branch()
        if not protected_ok:
            return 403, {"error": protected_detail}

        status_ok, status_out = git.get_status()
        if not status_ok:
            return 500, {"error": "failed to get repo status", "detail": status_out}
        if not status_out:
            return 409, {"error": "no changes to commit"}

        stage_ok, stage_out = git.stage_xml_changes()
        if not stage_ok:
            return 500, {"error": "failed to stage XML changes", "detail": stage_out}

        commit_ok, commit_out = git.commit(message)
        if not commit_ok:
            return 500, {"error": "failed to commit", "detail": commit_out}

        push_ok, push_out = git.push_branch(source_branch, set_upstream=True)
        if not push_ok:
            return 500, {"error": "failed to push source branch", "detail": push_out}

        lookup_result, existing = bb.find_open_pull_request(
            source_branch=source_branch, target_branch=target_branch
        )
        if lookup_result == PRLookupResult.LOOKUP_FAILED:
            error_detail = existing.get("error", "unknown error")
            audit_event(
                action="backend_create_pr_change",
                status="error",
                details={
                    "request_id": request_id,
                    "reason": "duplicate_check_failed",
                    "source": source_branch,
                    "target": target_branch,
                    "error": error_detail,
                },
            )
            return 502, {
                "error": "duplicate PR check failed",
                "detail": error_detail,
                "request_id": request_id,
            }
        if lookup_result == PRLookupResult.FOUND:
            pr_id = existing.get("id", "unknown")
            pr_url = existing.get("links", {}).get("html", {}).get("href", "")
            audit_event(
                action="backend_create_pr_change",
                status="duplicate",
                details={"request_id": request_id, "source": source_branch, "target": target_branch, "pr_id": pr_id},
            )
            return 200, {
                "change_id": request_id,
                "status": "duplicate_open_pr",
                "pull_request": {"id": pr_id, "url": pr_url},
            }

        pr_ok, pr_response = bb.create_pull_request(
            title=title,
            source_branch=source_branch,
            target_branch=target_branch,
            description=description,
            reviewer_usernames=[str(r).strip() for r in reviewers if str(r).strip()],
        )
        if not pr_ok:
            return 502, {"error": "failed to create pull request", "detail": pr_response}

        pr_id = pr_response.get("id", "unknown")
        pr_url = pr_response.get("links", {}).get("html", {}).get("href", "")
        response = {
            "change_id": request_id,
            "status": "submitted",
            "submitted_at": datetime.now(timezone.utc).isoformat(),
            "source_branch": source_branch,
            "target_branch": target_branch,
            "pull_request": {"id": pr_id, "url": pr_url},
        }
        audit_event(
            action="backend_create_pr_change",
            status="success",
            details={"request_id": request_id, "source": source_branch, "target": target_branch, "pr_id": pr_id},
        )
        return 202, response

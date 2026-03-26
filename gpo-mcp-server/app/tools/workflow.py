"""Branch / PR workflow tools for governed GPO changes."""

from __future__ import annotations

from app import config
from app.core import audit_event
from app.core.audit import clear_correlation_id, set_correlation_id
from app.services import BackendAPIService, BitbucketService, GitService, PRLookupResult


def register_workflow_tools(mcp):
    """Register PR workflow tools."""

    @mcp.tool()
    def gpo_create_feature_branch(branch_name: str, checkout: bool = True) -> str:
        """
        Create a feature branch for GPO changes.

        Args:
            branch_name: Branch name (recommended: gpo/<ticket>-<summary>)
            checkout: Switch to the new branch immediately

        Returns:
            Operation status
        """
        cid = set_correlation_id()
        try:
            git = GitService()
            success, output = git.create_branch(branch_name, checkout=checkout)
            audit_event(
                action="create_feature_branch",
                status="success" if success else "error",
                details={"branch": branch_name, "checkout": checkout},
            )
            return f"OK: {output}" if success else f"ERROR: {output}"
        finally:
            clear_correlation_id()

    @mcp.tool()
    def gpo_commit_branch_changes(message: str, branch_name: str = "") -> str:
        """
        Stage XML changes, commit, and push branch updates with branch protection guardrails.

        Args:
            message: Commit message
            branch_name: Optional branch to checkout before commit/push

        Returns:
            Operation status
        """
        cid = set_correlation_id()
        try:
            if config.settings.enforce_backend_boundary:
                audit_event(
                    action="commit_branch_changes",
                    status="blocked",
                    details={"reason": "backend_boundary_enforced"},
                )
                return (
                    "ERROR: Backend boundary is enforced. "
                    "Submit this via gpo_submit_change_request() instead of direct git write."
                )

            if not config.settings.allow_direct_git_writes:
                audit_event(
                    action="commit_branch_changes",
                    status="blocked",
                    details={"reason": "direct_git_disabled"},
                )
                return (
                    "ERROR: Direct git writes are disabled for MCP. "
                    "Use gpo_submit_change_request() through the backend API."
                )

            git = GitService()
            if not git.repo_path.exists():
                return "ERROR: Repository not found"

            if branch_name.strip():
                switched, switch_out = git.checkout_branch(branch_name.strip())
                if not switched:
                    audit_event(
                        action="commit_branch_changes",
                        status="error",
                        details={"step": "checkout", "branch": branch_name, "error": switch_out},
                    )
                    return f"ERROR: Failed to checkout branch: {switch_out}"

            protected_ok, branch_or_error = git.ensure_not_protected_branch()
            if not protected_ok:
                audit_event(
                    action="commit_branch_changes",
                    status="blocked",
                    details={"reason": "protected_branch", "detail": branch_or_error},
                )
                return f"ERROR: {branch_or_error}"

            active_branch = branch_or_error

            success, status = git.get_status()
            if not success:
                return f"ERROR: Failed to get repository status: {status}"
            if not status:
                return "INFO: No changes to commit"

            success, output = git.stage_xml_changes()
            if not success:
                audit_event(
                    action="commit_branch_changes",
                    status="error",
                    details={"step": "stage", "branch": active_branch, "error": output},
                )
                return f"ERROR: Failed to stage changes: {output}"

            success, output = git.commit(message)
            if not success:
                audit_event(
                    action="commit_branch_changes",
                    status="error",
                    details={"step": "commit", "branch": active_branch, "error": output},
                )
                return f"ERROR: Failed to commit: {output}"

            success, output = git.push_branch(active_branch, set_upstream=True)
            audit_event(
                action="commit_branch_changes",
                status="success" if success else "error",
                details={"branch": active_branch, "message": message[:120], "result": output},
            )
            if not success:
                return f"ERROR: Committed locally but failed to push branch '{active_branch}': {output}"

            return f"OK: Changes committed and pushed to branch '{active_branch}'"
        finally:
            clear_correlation_id()

    @mcp.tool()
    def gpo_create_pull_request(
        title: str,
        source_branch: str,
        target_branch: str = "",
        description: str = "",
        reviewers_csv: str = "",
    ) -> str:
        """
        Create a Bitbucket pull request for branch changes.

        Args:
            title: Pull request title
            source_branch: Source feature branch
            target_branch: Destination branch (default from GPO_DEFAULT_TARGET_BRANCH)
            description: Optional PR description
            reviewers_csv: Optional comma-separated reviewer usernames

        Returns:
            Pull request details
        """
        cid = set_correlation_id()
        try:
            bb = BitbucketService()
            source = source_branch.strip()
            if not source:
                return "ERROR: source_branch cannot be empty"

            target = target_branch.strip() or config.settings.default_target_branch
            if not target:
                return "ERROR: target_branch cannot be empty"

            allowed_targets = set(config.settings.allowed_pr_target_branches)
            if allowed_targets and target not in allowed_targets:
                return (
                    "ERROR: target_branch is not allowed. "
                    f"Allowed targets: {', '.join(sorted(allowed_targets))}"
                )

            reviewers = [r.strip() for r in reviewers_csv.split(",") if r.strip()]
            if config.settings.require_pr_reviewers and len(reviewers) < config.settings.min_pr_reviewers:
                return (
                    f"ERROR: At least {config.settings.min_pr_reviewers} reviewer(s) are required. "
                    f"Received {len(reviewers)}."
                )

            lookup_result, existing = bb.find_open_pull_request(source_branch=source, target_branch=target)
            if lookup_result == PRLookupResult.LOOKUP_FAILED:
                error_detail = existing.get("error", "unknown error")
                audit_event(
                    action="create_pull_request",
                    status="error",
                    details={"reason": "duplicate_check_failed", "source": source, "target": target, "error": error_detail},
                )
                return (
                    "ERROR: Could not verify whether an open PR already exists. "
                    f"Duplicate check failed: {error_detail}. "
                    "Resolve the issue and retry."
                )
            if lookup_result == PRLookupResult.FOUND:
                existing_id = existing.get("id", "unknown")
                existing_link = (
                    existing.get("links", {})
                    .get("html", {})
                    .get("href", "")
                )
                audit_event(
                    action="create_pull_request",
                    status="blocked",
                    details={"reason": "duplicate_open_pr", "source": source, "target": target, "id": existing_id},
                )
                return f"ERROR: Open pull request already exists (id={existing_id}) {existing_link}".strip()

            success, response = bb.create_pull_request(
                title=title,
                source_branch=source,
                target_branch=target,
                description=description,
                reviewer_usernames=reviewers,
            )
            audit_event(
                action="create_pull_request",
                status="success" if success else "error",
                details={"source": source_branch, "target": target, "reviewers": reviewers},
            )

            if not success:
                return f"ERROR: Failed to create pull request: {response.get('error', response)}"

            pr_id = response.get("id", "unknown")
            pr_link = (
                response.get("links", {})
                .get("html", {})
                .get("href", "")
            )
            return f"OK: Pull request created (id={pr_id}) {pr_link}".strip()
        finally:
            clear_correlation_id()

    @mcp.tool()
    def gpo_submit_change_request(
        operation: str,
        payload_json: str,
        request_id: str = "",
    ) -> str:
        """
        Submit a privileged change request to an internal backend API.

        Args:
            operation: Operation key, e.g. "create_pr_change"
            payload_json: JSON payload string for backend API
            request_id: Optional idempotency or trace ID

        Returns:
            Backend API response
        """
        cid = set_correlation_id(request_id if request_id.strip() else None)
        try:
            backend = BackendAPIService()
            if not backend.is_configured:
                return (
                    "ERROR: Backend API is not fully configured. "
                    "Both GPO_BACKEND_API_URL and GPO_BACKEND_API_TOKEN must be set."
                )

            try:
                import json
                payload = json.loads(payload_json) if payload_json.strip() else {}
            except Exception as exc:
                return f"ERROR: payload_json is not valid JSON: {exc}"

            body = {
                "operation": operation,
                "request_id": request_id or cid,
                "payload": payload,
            }

            success, response = backend.post_json("/v1/change-requests", body)
            response_summary = {
                "keys": sorted(list(response.keys())) if isinstance(response, dict) else [],
                "error": response.get("error") if isinstance(response, dict) else None,
            }
            audit_event(
                action="submit_change_request",
                status="success" if success else "error",
                details={
                    "operation": operation,
                    "request_id": request_id or cid,
                    "response": response_summary,
                },
            )

            if not success:
                return f"ERROR: Backend request failed: {response}"
            return f"OK: Backend accepted request: {response}"
        finally:
            clear_correlation_id()

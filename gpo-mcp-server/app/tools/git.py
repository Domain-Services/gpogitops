"""Git operations tools."""

from app import config
from app.core import audit_event
from app.core.audit import clear_correlation_id, set_correlation_id
from app.services import GitService

# Maps git --porcelain XY codes to human-readable labels.
# X = index status, Y = working-tree status.
_PORCELAIN_LABELS = {
    "M ": "Modified (staged)",
    " M": "Modified (unstaged)",
    "MM": "Modified (staged + unstaged)",
    "A ": "Added",
    "AM": "Added (modified since staging)",
    "D ": "Deleted (staged)",
    " D": "Deleted (unstaged)",
    "R ": "Renamed",
    "RM": "Renamed (modified)",
    "C ": "Copied",
    "UU": "Merge conflict",
    "??": "Untracked",
    "!!": "Ignored",
}


def register_git_tools(mcp):
    """Register git-related MCP tools."""

    @mcp.tool()
    def gpo_commit_changes(message: str) -> str:
        """
        Commit and push GPO changes to GitHub.

        Args:
            message: Commit message describing the changes

        Returns:
            Status of the commit and push operation
        """
        cid = set_correlation_id()
        try:
            if config.settings.enforce_backend_boundary:
                audit_event(
                    action="commit_changes",
                    status="blocked",
                    details={"reason": "backend_boundary_enforced"},
                )
                return (
                    "ERROR: Backend boundary is enforced. "
                    "Use workflow tools and submit via gpo_submit_change_request()."
                )

            if not config.settings.allow_direct_git_writes:
                audit_event(
                    action="commit_changes",
                    status="blocked",
                    details={"reason": "direct_git_disabled"},
                )
                return (
                    "ERROR: Direct git writes are disabled for MCP. "
                    "Use workflow tools and backend change requests."
                )

            git = GitService()

            if not git.repo_path.exists():
                return "ERROR: Repository not found"

            protected_ok, branch_or_error = git.ensure_not_protected_branch()
            if not protected_ok:
                audit_event(
                    action="commit_changes",
                    status="blocked",
                    details={"reason": "protected_branch", "detail": branch_or_error},
                )
                return f"ERROR: {branch_or_error}"

            active_branch = branch_or_error

            # Check for changes
            success, status = git.get_status()
            if not success:
                return f"ERROR: Failed to get repository status: {status}"
            if not status:
                return "INFO: No changes to commit"

            # Stage XML changes only (avoids accidentally staging secrets/temp files)
            success, output = git.stage_xml_changes()
            if not success:
                return f"ERROR: Failed to stage changes: {output}"

            # Commit
            success, output = git.commit(message)
            if not success:
                return f"ERROR: Failed to commit: {output}"

            # Push
            success, output = git.push()
            if not success:
                audit_event(
                    action="commit_changes",
                    status="error",
                    details={"step": "push", "branch": active_branch, "error": output},
                )
                return f"ERROR: Committed locally but failed to push: {output}"

            audit_event(
                action="commit_changes",
                status="success",
                details={"branch": active_branch, "message": message[:120]},
            )

            return f"OK: Changes committed and pushed\n\nBranch: {active_branch}\nCommit message: {message}"
        finally:
            clear_correlation_id()

    @mcp.tool()
    def gpo_get_changes() -> str:
        """
        Show uncommitted changes in the GPO repository.

        Returns:
            List of changed files and their status
        """
        git = GitService()

        if not git.repo_path.exists():
            return "ERROR: Repository not found"

        success, status = git.get_status()
        if not success:
            return f"ERROR: Failed to get repository status: {status}"
        if not status:
            return "OK: No uncommitted changes"

        output = ["# Uncommitted Changes", ""]

        for line in status.split("\n"):
            if line.strip():
                status_code = line[:2]
                file_name = line[3:]
                label = _PORCELAIN_LABELS.get(status_code, f"[{status_code}]")
                output.append(f"- {label}: `{file_name}`")

        output.append("")
        output.append("Use `gpo_commit_changes(message)` to commit these changes.")

        return "\n".join(output)

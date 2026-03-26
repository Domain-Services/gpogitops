"""Git operations service for GPO repository management."""

import logging
import re
import subprocess
from pathlib import Path
from urllib.parse import quote

from app import config

logger = logging.getLogger(__name__)

# Default subprocess timeout in seconds.
_DEFAULT_TIMEOUT = 60
# Longer timeout for clone operations which transfer the full repo.
_CLONE_TIMEOUT = 180


class GitService:
    """Service for Git/GitHub operations."""

    # All config values are intentionally read as @property so that test fixtures
    # which patch config.settings are reflected immediately without creating a new
    # service instance.

    @property
    def repo_path(self) -> Path:
        return config.settings.repo_path

    @property
    def repo_url(self) -> str:
        return config.settings.repo_url or ""

    @property
    def token(self) -> str:
        return config.settings.git_token or ""

    @property
    def protected_branches(self) -> set:
        return set(config.settings.protected_branches)

    def _mask_arg(self, arg: str) -> str:
        """Redact any credentials from a git argument before logging."""
        tok = self.token
        if not tok:
            return arg
        # Mask token in URL auth patterns: https://user:TOKEN@host or ?token=TOKEN
        masked = re.sub(re.escape(tok), "***", arg)
        return masked

    def _mask_text(self, text: str) -> str:
        """Redact token from arbitrary output text."""
        tok = self.token
        if not tok or not text:
            return text
        return re.sub(re.escape(tok), "***", text)

    @staticmethod
    def _is_valid_branch_name(branch_name: str) -> bool:
        """Best-effort local branch name validation."""
        if not branch_name:
            return False
        # Common git ref constraints (non-exhaustive but safe)
        if branch_name.startswith("/") or branch_name.endswith("/"):
            return False
        if ".." in branch_name or "//" in branch_name or "@{" in branch_name or "\\" in branch_name:
            return False
        if branch_name.endswith(".") or branch_name.endswith(".lock"):
            return False
        if any(ch in branch_name for ch in ["~", "^", ":", "?", "*", "[", " "]):
            return False
        return True

    def run_command(
        self,
        args: list[str],
        cwd: Path | None = None,
        timeout: int | None = None,
    ) -> tuple[bool, str]:
        """Run a git command and return success status and output.

        Args:
            args: Git sub-command and arguments (without the leading ``git``).
            cwd: Working directory override.
            timeout: Subprocess timeout in seconds (default ``_DEFAULT_TIMEOUT``).
        """
        effective_timeout = timeout if timeout is not None else _DEFAULT_TIMEOUT
        try:
            safe_args = [self._mask_arg(arg) for arg in args]
            logger.debug("Running git command: git %s", " ".join(safe_args))
            result = subprocess.run(
                ["git"] + args,
                cwd=cwd or self.repo_path,
                capture_output=True,
                text=True,
                timeout=effective_timeout,
            )
            output = self._mask_text(result.stdout + result.stderr)
            success = result.returncode == 0
            if not success:
                logger.error("Git command failed: %s", output)
            return success, output.strip()
        except subprocess.TimeoutExpired:
            logger.error("Git command timed out after %ds", effective_timeout)
            return False, f"Git command timed out after {effective_timeout}s"
        except Exception as e:
            # Mask the exception message in case it embeds the token URL.
            logger.error("Git command error: %s", self._mask_text(str(e)))
            return False, self._mask_text(str(e))

    def _get_authenticated_url(self) -> str | None:
        """Return token-embedded HTTPS URL for per-command git auth.

        Supports generic HTTPS remotes (GitHub/Bitbucket/etc). Credentials are
        passed only via process args and never persisted to git config files.

        Credentials are URL-percent-encoded so that tokens containing '@', ':',
        '/', '#', or '%' (e.g. Bitbucket app passwords with format user:pass)
        don't corrupt the authority component of the URL.

        Token format detection:
          - If the token contains ':' it is treated as ``user:password`` and
            both parts are encoded separately.
          - Otherwise the token is used as the password with ``git`` as the
            synthetic username (matches prior behaviour for plain API tokens).
        """
        if not self.token or not self.repo_url:
            return None
        url = self.repo_url
        if not url.startswith("https://"):
            return None

        tok = self.token
        if ":" in tok:
            # Bitbucket app-password format or explicit user:pass credential.
            user, password = tok.split(":", 1)
            encoded = f"{quote(user, safe='')}:{quote(password, safe='')}"
        else:
            # Plain API token — keep the conventional ``git`` username.
            encoded = f"git:{quote(tok, safe='')}"

        return f"https://{encoded}@{url[8:]}"

    def clone_or_pull(self) -> tuple[bool, str]:
        """Clone the GPO repository or pull latest changes."""
        if not self.repo_url:
            return False, "GPO_REPO_URL environment variable not set"

        auth_url = self._get_authenticated_url()

        if self.repo_path.exists() and (self.repo_path / ".git").exists():
            # Check for uncommitted changes before pulling to avoid confusing
            # merge failures.  Fail if the status check itself errors out so
            # we never pull on top of an unknown repo state.
            status_ok, status_out = self.get_status()
            if not status_ok:
                return False, (
                    "Failed to determine repository status before pulling. "
                    f"Resolve the issue first: {status_out}"
                )
            if status_out:
                return False, (
                    "Repository has uncommitted changes. "
                    "Commit or discard changes before pulling."
                )

            # Pull latest changes.  Pass the token via a per-command URL
            # rewrite so it is never written to ~/.git-credentials.
            pull_args = ["pull", "--rebase"]
            if auth_url:
                pull_args = ["-c", f"url.{auth_url}.insteadOf={self.repo_url}"] + pull_args
            success, output = self.run_command(pull_args)
            if success:
                return True, f"Repository updated: {output}"
            else:
                return False, f"Failed to pull: {output}"
        else:
            # Check if directory exists and is not empty
            if self.repo_path.exists():
                if any(self.repo_path.iterdir()):
                    return False, f"Directory {self.repo_path} exists and is not empty"

            # Always clone with the clean URL so git never writes the token
            # into .git/config under remote.origin.url.  Authentication is
            # applied via the per-command -c url.insteadOf rewrite (same as
            # the pull path above) which lives only for the lifetime of this
            # subprocess and is never persisted to disk.
            self.repo_path.mkdir(parents=True, exist_ok=True)
            clone_args = ["clone", self.repo_url, str(self.repo_path)]
            if auth_url:
                clone_args = ["-c", f"url.{auth_url}.insteadOf={self.repo_url}"] + clone_args
            success, output = self.run_command(
                clone_args,
                cwd=self.repo_path.parent,
                timeout=_CLONE_TIMEOUT,
            )
            if success:
                return True, f"Repository cloned to {self.repo_path}"
            else:
                return False, f"Failed to clone: {output}"

    def get_status(self) -> tuple[bool, str]:
        """Get repository status."""
        return self.run_command(["status", "--porcelain"])

    def stage_xml_changes(self) -> tuple[bool, str]:
        """Stage modified/deleted tracked files and any new XML files.

        Deliberately avoids 'git add -A' to prevent accidentally staging
        secrets, temp files, or other unexpected content.
        """
        # Stage modifications/deletions to already-tracked XML files only
        success_tracked, out_tracked = self.run_command(["add", "-u", "--", "*.xml", "**/*.xml"])
        # Stage any new (untracked) XML files via git's own pathspec globbing
        success_new, out_new = self.run_command(["add", "--", "*.xml", "**/*.xml"])

        if success_tracked and success_new:
            return True, "XML changes staged"
        errors = " | ".join(filter(None, [
            out_tracked if not success_tracked else "",
            out_new if not success_new else "",
        ]))
        return False, f"Staging failed: {errors}"

    def commit(self, message: str) -> tuple[bool, str]:
        """Create a commit with the given message."""
        # Validate commit message
        if not message or not message.strip():
            return False, "Commit message cannot be empty"
        if len(message) > 1000:
            return False, "Commit message too long (max 1000 characters)"

        full_message = f"{message}\n\nModified via GPO MCP Server"
        return self.run_command(["commit", "-m", full_message])

    def push(self) -> tuple[bool, str]:
        """Push changes to remote."""
        push_args = ["push"]
        auth_url = self._get_authenticated_url()
        if auth_url:
            # Apply token via per-command URL rewrite (never stored to disk)
            push_args = ["-c", f"url.{auth_url}.insteadOf={self.repo_url}"] + push_args
        return self.run_command(push_args)

    def get_current_branch(self) -> tuple[bool, str]:
        """Return current branch name."""
        return self.run_command(["rev-parse", "--abbrev-ref", "HEAD"])

    def branch_exists(self, branch_name: str) -> bool:
        """Check whether a local branch already exists."""
        ok, output = self.run_command(["rev-parse", "--verify", f"refs/heads/{branch_name}"])
        return ok

    def remote_branch_exists(self, branch_name: str, remote: str = "origin") -> bool:
        """Check whether a branch exists on the remote.

        Runs a local-only check against ``refs/remotes/<remote>/<branch>``.
        Call ``fetch_remote()`` first if the remote tracking data may be stale.
        """
        ok, _ = self.run_command(
            ["rev-parse", "--verify", f"refs/remotes/{remote}/{branch_name}"]
        )
        return ok

    def fetch_remote(self, remote: str = "origin") -> tuple[bool, str]:
        """Fetch the latest refs from a remote (no merge)."""
        return self.run_command(["fetch", remote], timeout=_CLONE_TIMEOUT)

    def create_branch(
        self,
        branch_name: str,
        checkout: bool = True,
        fetch_before_check: bool = False,
    ) -> tuple[bool, str]:
        """Create a branch, optionally switching to it.

        Args:
            branch_name: Name for the new branch.
            checkout: Switch to the new branch immediately after creation.
            fetch_before_check: When ``True``, fetch the remote before checking
                whether the branch already exists there.  This ensures the
                remote duplicate check operates on fresh refs at the cost of a
                network round-trip.  When ``False`` (default) the check is
                best-effort — it uses local remote-tracking state which may be
                stale if the remote was updated since the last fetch.

        Returns an error if the branch already exists locally or on the remote.
        """
        if not branch_name or not branch_name.strip():
            return False, "Branch name cannot be empty"

        safe_branch = branch_name.strip()
        if not self._is_valid_branch_name(safe_branch):
            return False, "Invalid branch name"

        if self.branch_exists(safe_branch):
            return False, f"Branch '{safe_branch}' already exists"

        if fetch_before_check:
            fetch_ok, fetch_out = self.fetch_remote()
            if not fetch_ok:
                return False, f"Failed to fetch remote refs before branch check: {fetch_out}"

        if self.remote_branch_exists(safe_branch):
            return False, f"Branch '{safe_branch}' already exists on remote"

        args = ["checkout", "-b", safe_branch] if checkout else ["branch", safe_branch]
        return self.run_command(args)

    def checkout_branch(self, branch_name: str) -> tuple[bool, str]:
        """Switch to an existing branch."""
        if not branch_name or not branch_name.strip():
            return False, "Branch name cannot be empty"
        safe_branch = branch_name.strip()
        if not self._is_valid_branch_name(safe_branch):
            return False, "Invalid branch name"
        return self.run_command(["checkout", safe_branch])

    def checkout_tracking_branch(
        self, branch_name: str, remote: str = "origin"
    ) -> tuple[bool, str]:
        """Check out a remote-only branch and set up local tracking.

        Equivalent to ``git checkout --track origin/<branch>``.  Use this as a
        fallback when ``checkout_branch()`` fails because the branch exists on
        the remote but has no local counterpart yet.
        """
        if not branch_name or not branch_name.strip():
            return False, "Branch name cannot be empty"
        safe_branch = branch_name.strip()
        if not self._is_valid_branch_name(safe_branch):
            return False, "Invalid branch name"
        return self.run_command(["checkout", "--track", f"{remote}/{safe_branch}"])

    def ensure_not_protected_branch(self) -> tuple[bool, str]:
        """Fail when current branch is protected."""
        success, branch = self.get_current_branch()
        if not success:
            return False, f"Failed to determine current branch: {branch}"

        current = branch.strip()
        if current in self.protected_branches:
            return False, (
                f"Direct commits to protected branch '{current}' are blocked. "
                "Create a feature branch and open a pull request."
            )

        return True, current

    def push_branch(self, branch_name: str, set_upstream: bool = True) -> tuple[bool, str]:
        """Push a specific branch to remote."""
        safe_branch = branch_name.strip()
        if not self._is_valid_branch_name(safe_branch):
            return False, "Invalid branch name"
        push_args = ["push", "-u", "origin", safe_branch] if set_upstream else ["push", "origin", safe_branch]
        auth_url = self._get_authenticated_url()
        if auth_url:
            push_args = ["-c", f"url.{auth_url}.insteadOf={self.repo_url}"] + push_args
        return self.run_command(push_args)

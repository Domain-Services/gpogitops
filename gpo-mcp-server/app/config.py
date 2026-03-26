f"""Configuration and environment settings."""

import logging
import os
from pathlib import Path
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class Settings:
    """Application settings loaded from environment variables."""

    # GPO Repository settings
    repo_path: Path
    repo_url: str | None
    git_token: str | None

    # Git workflow guardrails
    protected_branches: tuple[str, ...]
    default_target_branch: str
    allowed_pr_target_branches: tuple[str, ...]
    require_pr_reviewers: bool
    min_pr_reviewers: int

    # Internal backend API (privileged execution boundary)
    backend_api_url: str | None
    backend_api_token: str | None
    backend_api_host: str
    backend_api_port: int

    # Bitbucket PR integration
    bitbucket_workspace: str | None
    bitbucket_repo_slug: str | None
    bitbucket_token: str | None

    # Security / audit settings
    allow_direct_git_writes: bool
    enforce_backend_boundary: bool
    audit_log_path: Path | None

    # Runtime mode
    environment: str

    # Server settings
    server_name: str = "gpo-management-server"

    # Collected validation warnings (populated by validate())
    _warnings: list[str] = field(default_factory=list, repr=False)

    def validate(self) -> list[str]:
        """Check cross-field consistency and return list of warnings.

        Warnings are also stored on self._warnings for later inspection.
        """
        warnings: list[str] = []

        # --- Backend boundary ---
        if self.enforce_backend_boundary and not self.backend_api_url:
            warnings.append(
                "GPO_ENFORCE_BACKEND_BOUNDARY is true but GPO_BACKEND_API_URL is not set. "
                "All write operations will be blocked."
            )

        if self.backend_api_url and not self.backend_api_token:
            warnings.append(
                "GPO_BACKEND_API_URL is set but GPO_BACKEND_API_TOKEN is empty. "
                "The backend API will reject all requests (fail-closed)."
            )

        # --- Permissive mode warnings ---
        if self.allow_direct_git_writes:
            warnings.append(
                "GPO_ALLOW_DIRECT_GIT_WRITES is enabled. "
                "The MCP/LLM layer can push directly to Git."
            )

        if not self.enforce_backend_boundary:
            warnings.append(
                "GPO_ENFORCE_BACKEND_BOUNDARY is disabled. "
                "Privileged execution boundary is not enforced."
            )

        # --- PR / reviewer consistency ---
        if self.require_pr_reviewers and self.min_pr_reviewers < 1:
            warnings.append(
                "GPO_REQUIRE_PR_REVIEWERS is true but GPO_MIN_PR_REVIEWERS is 0. "
                "Reviewer requirement has no practical effect."
            )

        # --- Bitbucket partial configuration ---
        bb_fields = [self.bitbucket_workspace, self.bitbucket_repo_slug, self.bitbucket_token]
        bb_set = sum(1 for f in bb_fields if f)
        if 0 < bb_set < 3:
            warnings.append(
                "Bitbucket integration is partially configured. "
                "All of BITBUCKET_WORKSPACE, BITBUCKET_REPO_SLUG, and BITBUCKET_TOKEN must be set."
            )

        # --- Audit path validation ---
        if self.audit_log_path:
            try:
                self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
                if self.audit_log_path.parent.exists() and not os.access(
                    self.audit_log_path.parent, os.W_OK
                ):
                    warnings.append(
                        f"Audit log directory is not writable: {self.audit_log_path.parent}"
                    )
            except OSError as exc:
                warnings.append(f"Cannot prepare audit log directory: {exc}")

        self._warnings = warnings
        return warnings

    def log_summary(self) -> None:
        """Log a startup configuration summary and any validation warnings."""
        logger.info(
            "Config summary: environment=%s enforce_backend_boundary=%s "
            "allow_direct_git_writes=%s require_pr_reviewers=%s "
            "min_pr_reviewers=%d protected_branches=%s",
            self.environment,
            self.enforce_backend_boundary,
            self.allow_direct_git_writes,
            self.require_pr_reviewers,
            self.min_pr_reviewers,
            ",".join(self.protected_branches),
        )
        for warning in self._warnings:
            logger.warning("Config warning: %s", warning)

    @classmethod
    def from_env(cls) -> "Settings":
        """Load settings from environment variables."""
        repo_path_str = os.environ.get("GPO_REPO_PATH", "/data/gpo-repo")
        protected_branches_raw = os.environ.get("GPO_PROTECTED_BRANCHES", "main,master,production,prod")
        protected_branches = tuple(
            b.strip() for b in protected_branches_raw.split(",") if b.strip()
        )

        allowed_targets_raw = os.environ.get("GPO_ALLOWED_PR_TARGET_BRANCHES", "main")
        allowed_pr_target_branches = tuple(
            b.strip() for b in allowed_targets_raw.split(",") if b.strip()
        )

        allow_direct_git_writes = os.environ.get("GPO_ALLOW_DIRECT_GIT_WRITES", "false").lower() in {
            "1", "true", "yes", "on"
        }

        enforce_backend_boundary = os.environ.get("GPO_ENFORCE_BACKEND_BOUNDARY", "true").lower() in {
            "1", "true", "yes", "on"
        }

        require_pr_reviewers = os.environ.get("GPO_REQUIRE_PR_REVIEWERS", "true").lower() in {
            "1", "true", "yes", "on"
        }

        try:
            min_pr_reviewers = int(os.environ.get("GPO_MIN_PR_REVIEWERS", "1"))
        except ValueError:
            min_pr_reviewers = 1
        min_pr_reviewers = max(0, min_pr_reviewers)

        audit_log_path_raw = os.environ.get("GPO_AUDIT_LOG_PATH", "")
        audit_log_path = Path(audit_log_path_raw) if audit_log_path_raw else None

        instance = cls(
            repo_path=Path(repo_path_str),
            repo_url=os.environ.get("GPO_REPO_URL"),
            git_token=os.environ.get("GIT_TOKEN") or os.environ.get("GITHUB_TOKEN"),
            protected_branches=protected_branches,
            default_target_branch=os.environ.get("GPO_DEFAULT_TARGET_BRANCH", "main"),
            allowed_pr_target_branches=allowed_pr_target_branches,
            require_pr_reviewers=require_pr_reviewers,
            min_pr_reviewers=min_pr_reviewers,
            backend_api_url=os.environ.get("GPO_BACKEND_API_URL"),
            backend_api_token=os.environ.get("GPO_BACKEND_API_TOKEN"),
            backend_api_host=os.environ.get("GPO_BACKEND_API_HOST", "127.0.0.1"),
            backend_api_port=int(os.environ.get("GPO_BACKEND_API_PORT", "8088")),
            bitbucket_workspace=os.environ.get("BITBUCKET_WORKSPACE"),
            bitbucket_repo_slug=os.environ.get("BITBUCKET_REPO_SLUG"),
            bitbucket_token=os.environ.get("BITBUCKET_TOKEN"),
            allow_direct_git_writes=allow_direct_git_writes,
            enforce_backend_boundary=enforce_backend_boundary,
            audit_log_path=audit_log_path,
            environment=os.environ.get("GPO_ENVIRONMENT", "production").strip().lower() or "production",
        )

        instance.validate()
        return instance


# Global settings instance
settings = Settings.from_env()

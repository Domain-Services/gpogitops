"""Simple JSONL audit logging for tool actions."""

from __future__ import annotations

import json
import logging
import re
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from app import config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Audit action and status enums for consistent vocabulary
# ---------------------------------------------------------------------------

class AuditAction(str, Enum):
    """Known audit action names.

    New actions may be added freely; the enum documents the current set and
    prevents accidental typos in frequently-used names.
    """
    SERVER_STARTUP = "server_startup"
    SERVER_SHUTDOWN = "server_shutdown"

    # Git
    COMMIT_CHANGES = "commit_changes"
    COMMIT_BRANCH_CHANGES = "commit_branch_changes"
    CREATE_FEATURE_BRANCH = "create_feature_branch"

    # PR
    CREATE_PULL_REQUEST = "create_pull_request"
    SUBMIT_CHANGE_REQUEST = "submit_change_request"

    # Backend
    BACKEND_CREATE_PR_CHANGE = "backend_create_pr_change"
    BACKEND_API_AUTH = "backend_api_auth"


class AuditStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    BLOCKED = "blocked"
    DUPLICATE = "duplicate"


# ---------------------------------------------------------------------------
# Correlation ID — lets callers link multiple audit events to one operation
# ---------------------------------------------------------------------------

_correlation_id: ContextVar[str | None] = ContextVar("audit_correlation_id", default=None)


def set_correlation_id(cid: str | None = None) -> str:
    """Set a correlation ID for the current async/thread context.

    Returns the (possibly generated) correlation ID.
    """
    cid = cid or str(uuid.uuid4())
    _correlation_id.set(cid)
    return cid


def get_correlation_id() -> str | None:
    return _correlation_id.get()


def clear_correlation_id() -> None:
    _correlation_id.set(None)


# ---------------------------------------------------------------------------
# Sensitive-key redaction
# ---------------------------------------------------------------------------

_SENSITIVE_SUBSTRINGS = (
    "token",
    "password",
    "secret",
    "api_key",
    "credential",
    "authorization",
    "auth_header",
)

# Regex patterns compiled once at module load for value-level secret scrubbing.
# These catch common secret formats that may appear inside string *values* even
# when the containing key name does not trigger key-based redaction (e.g. an
# error body stored under the key "detail" that contains "Authorization: Bearer …").
_SENSITIVE_VALUE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"Bearer\s+\S+", re.IGNORECASE), "Bearer ***"),
    (re.compile(r"token=\S+", re.IGNORECASE), "token=***"),
    (re.compile(r"password=\S+", re.IGNORECASE), "password=***"),
]


def _is_sensitive_key(key: str) -> bool:
    """Return True when *key* contains any sensitive substring (case-insensitive)."""
    lower = key.lower()
    return any(sub in lower for sub in _SENSITIVE_SUBSTRINGS)


def _redact_sensitive_value(text: str) -> str:
    """Apply value-level regex redaction to a plain string."""
    for pattern, replacement in _SENSITIVE_VALUE_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _sanitize_details(value, max_len: int = 300):
    """Recursively sanitize potentially sensitive or very large audit data."""
    if isinstance(value, dict):
        cleaned = {}
        for key, val in value.items():
            if _is_sensitive_key(str(key)):
                cleaned[key] = "***"
            else:
                cleaned[key] = _sanitize_details(val, max_len=max_len)
        return cleaned

    if isinstance(value, list):
        return [_sanitize_details(v, max_len=max_len) for v in value[:100]]

    if isinstance(value, str):
        truncated = value if len(value) <= max_len else f"{value[:max_len]}...<truncated>"
        return _redact_sensitive_value(truncated)

    return value


# ---------------------------------------------------------------------------
# Main audit function
# ---------------------------------------------------------------------------

def audit_event(
    action: str | AuditAction,
    status: str | AuditStatus,
    details: dict | None = None,
    correlation_id: str | None = None,
) -> None:
    """Write an audit event to configured JSONL path and structured logs.

    The event intentionally avoids secret material and should include only
    operational metadata required for traceability.

    Args:
        action: What happened (use ``AuditAction`` for known actions).
        status: Outcome (use ``AuditStatus`` for known statuses).
        details: Arbitrary metadata dict (sensitive keys are auto-redacted).
        correlation_id: Override for the contextvar-based correlation ID.
    """
    # Resolve enum values to plain strings for serialisation
    action_str = action.value if isinstance(action, AuditAction) else str(action)
    status_str = status.value if isinstance(status, AuditStatus) else str(status)

    cid = correlation_id or get_correlation_id()

    payload: dict = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action_str,
        "status": status_str,
        "details": _sanitize_details(details or {}),
    }
    if cid:
        payload["correlation_id"] = cid

    logger.info("audit action=%s status=%s details=%s", action_str, status_str, payload["details"])

    if not config.settings.audit_log_path:
        return

    try:
        path: Path = config.settings.audit_log_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.error("Failed to persist audit event: %s", exc)

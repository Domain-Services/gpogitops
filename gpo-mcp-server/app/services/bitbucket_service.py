"""Bitbucket pull request integration service."""

from __future__ import annotations

import base64
import json
import logging
from enum import Enum
from urllib import error, request
from urllib.parse import urlencode

from app import config

logger = logging.getLogger(__name__)


class PRLookupResult(str, Enum):
    """Tri-state result for duplicate PR lookup."""
    FOUND = "found"
    NOT_FOUND = "not_found"
    LOOKUP_FAILED = "lookup_failed"


class BitbucketService:
    """Create pull requests through Bitbucket Cloud API."""

    # Config values are read as @property so test patches to config.settings are
    # reflected without needing to instantiate a fresh service object.

    @property
    def workspace(self) -> str:
        return config.settings.bitbucket_workspace or ""

    @property
    def repo_slug(self) -> str:
        return config.settings.bitbucket_repo_slug or ""

    @property
    def token(self) -> str:
        return config.settings.bitbucket_token or ""

    @property
    def is_configured(self) -> bool:
        return bool(self.workspace and self.repo_slug and self.token)

    def _headers(self) -> dict[str, str]:
        # Supports either OAuth bearer token or app-password style user:pass in BITBUCKET_TOKEN
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if not self.token:
            return headers

        if ":" in self.token:
            auth_bytes = base64.b64encode(self.token.encode("utf-8")).decode("ascii")
            headers["Authorization"] = f"Basic {auth_bytes}"
        else:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _request_json(self, url: str, method: str, payload: dict | None = None) -> tuple[bool, dict]:
        """Execute a Bitbucket API request and parse JSON response."""
        req = request.Request(
            url,
            data=json.dumps(payload).encode("utf-8") if payload is not None else None,
            method=method,
        )

        for key, value in self._headers().items():
            req.add_header(key, value)

        try:
            with request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode("utf-8")
                return True, json.loads(body) if body else {}
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            logger.error("Bitbucket API request failed (%s): %s", exc.code, detail)
            return False, {"error": f"HTTP {exc.code}", "detail": detail}
        except Exception as exc:
            logger.error("Bitbucket API request error: %s", exc)
            return False, {"error": str(exc)}

    def find_open_pull_request(
        self, source_branch: str, target_branch: str
    ) -> tuple[PRLookupResult, dict]:
        """Find an existing open PR for source->target branch pair.

        Returns a tri-state result:
          - ``(PRLookupResult.FOUND, pr_object)`` — a matching open PR exists.
          - ``(PRLookupResult.NOT_FOUND, {})`` — lookup succeeded, no match.
          - ``(PRLookupResult.LOOKUP_FAILED, {"error": ...})`` — API call failed;
            callers **must not** assume "no duplicate exists".
        """
        if not self.is_configured:
            return PRLookupResult.LOOKUP_FAILED, {"error": "Bitbucket integration not configured"}

        base = f"https://api.bitbucket.org/2.0/repositories/{self.workspace}/{self.repo_slug}/pullrequests"
        # Build the q= filter value first, then URL-encode the full query string so
        # that branch names containing '/', spaces, or '"' don't produce malformed URLs.
        q_value = (
            f'source.branch.name="{source_branch}"'
            f' AND destination.branch.name="{target_branch}"'
        )
        query = urlencode({"state": "OPEN", "pagelen": "50", "q": q_value})
        url = f"{base}?{query}"
        success, response = self._request_json(url, method="GET")
        if not success:
            return PRLookupResult.LOOKUP_FAILED, response

        values = response.get("values", []) if isinstance(response, dict) else []
        if values:
            return PRLookupResult.FOUND, values[0]
        return PRLookupResult.NOT_FOUND, {}

    def create_pull_request(
        self,
        title: str,
        source_branch: str,
        target_branch: str,
        description: str = "",
        reviewer_usernames: list[str] | None = None,
    ) -> tuple[bool, dict]:
        """Create a pull request in Bitbucket Cloud."""
        if not self.is_configured:
            return False, {
                "error": (
                    "Bitbucket integration not configured. "
                    "Set BITBUCKET_WORKSPACE, BITBUCKET_REPO_SLUG, and BITBUCKET_TOKEN."
                )
            }

        url = (
            f"https://api.bitbucket.org/2.0/repositories/"
            f"{self.workspace}/{self.repo_slug}/pullrequests"
        )
        payload = {
            "title": title,
            "description": description,
            "source": {"branch": {"name": source_branch}},
            "destination": {"branch": {"name": target_branch}},
            "close_source_branch": False,
        }

        if reviewer_usernames:
            # Bitbucket Cloud deprecated the `username` field in favour of `account_id`.
            # Convention: values that start with '{' are treated as Cloud UUIDs/account_ids
            # (e.g. "{abc-1234-…}"); anything else is sent as a legacy username for backward
            # compatibility with Bitbucket Server/Data Center or plain username strings.
            def _reviewer_obj(u: str) -> dict:
                if u.startswith("{"):
                    return {"account_id": u}
                return {"username": u}

            payload["reviewers"] = [_reviewer_obj(u) for u in reviewer_usernames if u]
        return self._request_json(url, method="POST", payload=payload)

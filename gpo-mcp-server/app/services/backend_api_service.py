"""Internal backend API client for privileged change execution."""

from __future__ import annotations

import json
import logging
from urllib import error, request

from app import config

logger = logging.getLogger(__name__)


class BackendAPIService:
    """Call internal backend API used as privileged execution boundary."""

    # Config values are read as @property so test patches to config.settings are
    # reflected without needing to instantiate a fresh service object.

    @property
    def base_url(self) -> str:
        return (config.settings.backend_api_url or "").rstrip("/")

    @property
    def token(self) -> str:
        return config.settings.backend_api_token or ""

    @property
    def is_configured(self) -> bool:
        """URL and auth token must both be present for the boundary to work."""
        return bool(self.base_url and self.token)

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def post_json(self, path: str, payload: dict) -> tuple[bool, dict]:
        """POST JSON payload to backend API and parse response JSON."""
        if not self.is_configured:
            return False, {
                "error": "Backend API is not fully configured. "
                "Both GPO_BACKEND_API_URL and GPO_BACKEND_API_TOKEN must be set."
            }

        url = f"{self.base_url}/{path.lstrip('/')}"
        data = json.dumps(payload).encode("utf-8")
        req = request.Request(url, data=data, method="POST")

        for key, value in self._headers().items():
            req.add_header(key, value)

        try:
            with request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode("utf-8")
                return True, json.loads(body) if body else {}
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            logger.error("Backend API HTTP error (%s): %s", exc.code, detail)
            return False, {"error": f"HTTP {exc.code}", "detail": detail}
        except error.URLError as exc:
            logger.error("Backend API connection error: %s", exc)
            return False, {"error": "Connection failed", "detail": str(exc)}
        except Exception as exc:
            logger.error("Backend API unexpected error: %s", exc)
            return False, {"error": "Unexpected error", "detail": str(exc)}

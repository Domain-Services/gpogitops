"""HTTP server for internal backend change-request API."""

from __future__ import annotations

import json
import logging
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app import config
from app.core import audit_event

logger = logging.getLogger(__name__)

# Maximum request body size (1 MB) to prevent denial-of-service via
# oversized payloads.
MAX_BODY_BYTES = 1_048_576


class ChangeRequestHandler(BaseHTTPRequestHandler):
    """Minimal internal HTTP handler for change-request operations."""

    # Lazily initialised so tests can patch config before construction.
    _service = None

    @classmethod
    def _get_service(cls):
        if cls._service is None:
            from app.backend.change_request_service import ChangeRequestService
            cls._service = ChangeRequestService()
        return cls._service

    def _send_json(self, status_code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _is_authorized(self) -> bool:
        expected = config.settings.backend_api_token
        if not expected:
            # FAIL CLOSED: when no token is configured, reject all requests
            # rather than silently allowing unauthenticated access.
            logger.error("Backend API token is not configured - rejecting request")
            audit_event(
                action="backend_api_auth",
                status="blocked",
                details={"reason": "no_token_configured"},
            )
            return False
        auth_header = self.headers.get("Authorization", "")
        prefix = "Bearer "
        if not auth_header.startswith(prefix):
            audit_event(
                action="backend_api_auth",
                status="blocked",
                details={"reason": "missing_or_invalid_auth_header"},
            )
            return False
        provided = auth_header[len(prefix):].strip()
        if provided != expected:
            audit_event(
                action="backend_api_auth",
                status="blocked",
                details={"reason": "invalid_token"},
            )
            return False
        return True

    def do_POST(self):  # noqa: N802
        if self.path != "/v1/change-requests":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return

        if not self._is_authorized():
            self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "Unauthorized"})
            return

        try:
            content_len = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid Content-Length"})
            return

        if content_len < 0:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid Content-Length"})
            return

        if content_len > MAX_BODY_BYTES:
            self._send_json(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                {"error": f"Request body exceeds {MAX_BODY_BYTES} bytes"},
            )
            return

        raw = self.rfile.read(content_len) if content_len > 0 else b""
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid JSON"})
            return

        service = self._get_service()
        status, response = service.handle_request(body)
        self._send_json(status, response)

    def do_GET(self):  # noqa: N802
        if self.path != "/healthz":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return

        self._send_json(
            HTTPStatus.OK,
            {
                "status": "ok",
                "service": "gpo-backend-api",
                "environment": config.settings.environment,
                "enforce_backend_boundary": config.settings.enforce_backend_boundary,
            },
        )

    def log_message(self, fmt: str, *args):
        """Route handler logs to application logger."""
        logger.info("backend_api " + fmt, *args)


def run_server() -> None:
    """Run backend API server."""
    host = config.settings.backend_api_host
    port = config.settings.backend_api_port

    if not config.settings.backend_api_token:
        logger.warning(
            "GPO_BACKEND_API_TOKEN is not set - all requests will be rejected. "
            "Set this variable to enable the backend API."
        )

    server = ThreadingHTTPServer((host, port), ChangeRequestHandler)
    logger.info("Starting internal backend API on %s:%s", host, port)
    server.serve_forever()

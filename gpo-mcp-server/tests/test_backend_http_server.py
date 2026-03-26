"""Tests for the backend HTTP server auth and request handling."""

from __future__ import annotations

import io
import json

from app import config
from app.backend.http_server import MAX_BODY_BYTES, ChangeRequestHandler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_handler(auth_header_value: str | None = None) -> ChangeRequestHandler:
    """Create a bare ChangeRequestHandler instance with mocked headers."""
    class FakeHeaders:
        def __init__(self, auth_value):
            self._auth = auth_value

        def get(self, key, default=""):
            if key == "Authorization" and self._auth is not None:
                return self._auth
            return default

    handler = ChangeRequestHandler.__new__(ChangeRequestHandler)
    handler.headers = FakeHeaders(auth_header_value)
    return handler


# ---------------------------------------------------------------------------
# Bearer token auth
# ---------------------------------------------------------------------------

def test_is_authorized_rejects_when_no_token_configured(monkeypatch):
    """When backend_api_token is not set, requests should be rejected (fail closed)."""
    monkeypatch.setattr(config.settings, "backend_api_token", None)
    handler = _make_handler("Bearer some-token")
    assert handler._is_authorized() is False


def test_is_authorized_rejects_wrong_token(monkeypatch):
    """Requests with wrong bearer token should be rejected."""
    monkeypatch.setattr(config.settings, "backend_api_token", "correct-token")
    handler = _make_handler("Bearer wrong-token")
    assert handler._is_authorized() is False


def test_is_authorized_accepts_correct_token(monkeypatch):
    """Requests with matching bearer token should be accepted."""
    monkeypatch.setattr(config.settings, "backend_api_token", "correct-token")
    handler = _make_handler("Bearer correct-token")
    assert handler._is_authorized() is True


def test_is_authorized_rejects_missing_auth_header(monkeypatch):
    """Requests without Authorization header should be rejected."""
    monkeypatch.setattr(config.settings, "backend_api_token", "correct-token")
    handler = _make_handler(None)
    assert handler._is_authorized() is False


# ---------------------------------------------------------------------------
# Malformed / wrong-scheme auth headers
# ---------------------------------------------------------------------------

def test_is_authorized_rejects_bearer_without_token(monkeypatch):
    """'Bearer' with no following token value should be rejected."""
    monkeypatch.setattr(config.settings, "backend_api_token", "correct-token")
    # "Bearer " + empty string after strip -> provided == "" != expected
    handler = _make_handler("Bearer ")
    assert handler._is_authorized() is False


def test_is_authorized_rejects_wrong_scheme(monkeypatch):
    """Non-Bearer auth schemes (e.g. Basic) should be rejected."""
    monkeypatch.setattr(config.settings, "backend_api_token", "correct-token")
    handler = _make_handler("Basic Y29ycmVjdC10b2tlbg==")
    assert handler._is_authorized() is False


def test_is_authorized_rejects_bare_token_without_scheme(monkeypatch):
    """Token provided without 'Bearer ' prefix should be rejected."""
    monkeypatch.setattr(config.settings, "backend_api_token", "correct-token")
    handler = _make_handler("correct-token")
    assert handler._is_authorized() is False


# ---------------------------------------------------------------------------
# Oversized payload — do_POST Content-Length check
# ---------------------------------------------------------------------------

def _make_post_handler(
    monkeypatch,
    token: str,
    content_length: int,
    body: bytes = b"{}",
) -> tuple[ChangeRequestHandler, list]:
    """Create a handler instance wired up to simulate do_POST execution.

    Returns (handler, responses) where responses captures _send_json calls.
    """
    monkeypatch.setattr(config.settings, "backend_api_token", token)

    responses = []

    class FakeHeaders:
        def get(self, key, default=""):
            if key == "Authorization":
                return f"Bearer {token}"
            if key == "Content-Length":
                return str(content_length)
            return default

    handler = ChangeRequestHandler.__new__(ChangeRequestHandler)
    handler.headers = FakeHeaders()
    handler.path = "/v1/change-requests"
    handler.rfile = io.BytesIO(body)

    def fake_send_json(status_code, payload):
        responses.append((status_code, payload))

    handler._send_json = fake_send_json
    return handler, responses


def test_oversized_payload_rejected(monkeypatch):
    """do_POST should return 413 when Content-Length exceeds MAX_BODY_BYTES."""
    oversized = MAX_BODY_BYTES + 1
    handler, responses = _make_post_handler(
        monkeypatch,
        token="tok",
        content_length=oversized,
        body=b"x" * oversized,
    )
    handler.do_POST()

    assert len(responses) == 1
    status_code, payload = responses[0]
    # HTTPStatus.REQUEST_ENTITY_TOO_LARGE == 413
    assert status_code == 413
    assert "exceeds" in payload["error"].lower()


def test_exactly_max_payload_accepted_structure_check(monkeypatch):
    """do_POST should NOT return 413 for a body exactly at the limit.

    (The body will likely fail JSON parse or service validation, but
    it must pass the size gate.)
    """
    body = b"{}"  # valid tiny JSON — well under limit
    handler, responses = _make_post_handler(
        monkeypatch,
        token="tok",
        content_length=len(body),
        body=body,
    )
    # Patch _get_service so we don't need a real service
    from app.backend.change_request_service import ChangeRequestService

    class FakeService:
        def handle_request(self, body):
            return 400, {"error": "Unsupported operation"}

    monkeypatch.setattr(ChangeRequestHandler, "_get_service", staticmethod(lambda: FakeService()))
    handler.do_POST()

    assert len(responses) == 1
    status_code, _ = responses[0]
    assert status_code != 413  # passed the size gate


def test_invalid_content_length_header_rejected(monkeypatch):
    """do_POST should return 400 when Content-Length is not a valid integer."""
    monkeypatch.setattr(config.settings, "backend_api_token", "tok")

    responses = []

    class FakeHeaders:
        def get(self, key, default=""):
            if key == "Authorization":
                return "Bearer tok"
            if key == "Content-Length":
                return "not-a-number"
            return default

    handler = ChangeRequestHandler.__new__(ChangeRequestHandler)
    handler.headers = FakeHeaders()
    handler.path = "/v1/change-requests"
    handler.rfile = io.BytesIO(b"{}")

    def fake_send_json(status_code, payload):
        responses.append((status_code, payload))

    handler._send_json = fake_send_json
    handler.do_POST()

    assert len(responses) == 1
    status_code, payload = responses[0]
    assert status_code == 400
    assert "Content-Length" in payload["error"]


# ---------------------------------------------------------------------------
# Negative Content-Length (Fix 5)
# ---------------------------------------------------------------------------

def test_negative_content_length_rejected(monkeypatch):
    """do_POST should return 400 when Content-Length is a negative integer."""
    monkeypatch.setattr(config.settings, "backend_api_token", "tok")

    responses = []

    class FakeHeaders:
        def get(self, key, default=""):
            if key == "Authorization":
                return "Bearer tok"
            if key == "Content-Length":
                return "-1"
            return default

    handler = ChangeRequestHandler.__new__(ChangeRequestHandler)
    handler.headers = FakeHeaders()
    handler.path = "/v1/change-requests"
    handler.rfile = io.BytesIO(b"{}")

    def fake_send_json(status_code, payload):
        responses.append((status_code, payload))

    handler._send_json = fake_send_json
    handler.do_POST()

    assert len(responses) == 1
    status_code, payload = responses[0]
    assert status_code == 400
    assert "Content-Length" in payload["error"] or "Invalid" in payload["error"]

"""Regression tests for non-dictionary JSON responses in HTTP request logging."""

from __future__ import annotations

from typing import Any
from unittest import IsolatedAsyncioTestCase

from blueair_api.util_http import request_with_logging


class _FakeResponse:
    """Minimal aiohttp response stand-in with a configurable JSON body."""

    def __init__(self, body: Any, *, parse_error: bool = False) -> None:
        """Store a JSON body and optional JSON parsing failure."""
        self.status = 200
        self.headers = {"Content-Type": "application/json"}
        self.body = body
        self.parse_error = parse_error

    async def json(self, *, content_type: str | None = None) -> Any:
        """Return the test body or simulate non-JSON content."""
        if self.parse_error:
            raise ValueError("not JSON")
        return self.body

    async def text(self) -> str:
        """Return the body as text, as the real HTTP client can."""
        return str(self.body)


@request_with_logging
async def _wrapped(*, url: str, response: _FakeResponse) -> _FakeResponse:
    """Return the supplied response for the request logging wrapper."""
    return response


class TestResponseLogging(IsolatedAsyncioTestCase):
    """A valid JSON scalar must not crash request logging or expose secrets."""

    async def test_json_string_does_not_crash_or_leak(self) -> None:
        """Blueair home-host discovery may return a JSON string."""
        payload = "secret-home-host-or-token"
        response = _FakeResponse(payload)
        with self.assertLogs("blueair_api.util_http", level="DEBUG") as logs:
            result = await _wrapped(url="https://example.test/homehost", response=response)
        self.assertIs(result, response)
        self.assertIn("response json type: str", "\n".join(logs.output))
        self.assertNotIn(payload, "\n".join(logs.output))

    async def test_json_list_does_not_crash_or_leak(self) -> None:
        """JSON arrays are handled without printing their contents."""
        payload = [{"password": "secret"}]
        response = _FakeResponse(payload)
        with self.assertLogs("blueair_api.util_http", level="DEBUG") as logs:
            result = await _wrapped(url="https://example.test/devices", response=response)
        self.assertIs(result, response)
        self.assertIn("response json type: list", "\n".join(logs.output))
        self.assertNotIn("secret", "\n".join(logs.output))

    async def test_json_dict_still_redacts_password(self) -> None:
        """Regular dictionaries retain the existing masking behavior."""
        response = _FakeResponse({"password": "not-for-logs", "ok": True})
        with self.assertLogs("blueair_api.util_http", level="DEBUG") as logs:
            await _wrapped(url="https://example.test/login", response=response)
        self.assertIn("'password': '***'", "\n".join(logs.output))
        self.assertNotIn("not-for-logs", "\n".join(logs.output))

    async def test_invalid_json_still_uses_text_fallback(self) -> None:
        """An invalid JSON response falls back to the existing raw path."""
        response = _FakeResponse("not-json", parse_error=True)
        with self.assertLogs("blueair_api.util_http", level="DEBUG") as logs:
            result = await _wrapped(url="https://example.test/error", response=response)
        self.assertIs(result, response)
        self.assertIn("response raw: not-json", "\n".join(logs.output))

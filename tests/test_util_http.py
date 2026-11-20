"""Tests for ``blueair_api.util_http`` request logging and timeouts."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, cast

from aiohttp import ClientError, ClientResponse
import pytest

from blueair_api.const import REQUEST_TIMEOUT_SECONDS
from blueair_api.errors import RequestTimeoutError
from blueair_api.util_http import request_with_logging, send_with_timeout


class _FakeResponse:
    """Minimal aiohttp.ClientResponse stand-in."""

    def __init__(self, body: Any, headers: dict[str, str] | None = None) -> None:
        """Store the response body and headers.

        Args:
            body: JSON body returned by ``json``.
            headers: Response headers.
        """
        self.status = 200
        self.headers = headers or {}
        self._body = body

    async def json(self, content_type: str | None = None) -> Any:
        """Return the JSON body.

        Args:
            content_type: Ignored content type check.

        Returns:
            The configured body.
        """
        return self._body

    async def text(self) -> str:
        """Return the body as text.

        Returns:
            The body converted to a string.
        """
        return str(self._body)


async def test_request_with_logging_masks_request_and_response_secrets(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Mask auth headers, params, request bodies and response tokens in debug logs.

    Args:
        caplog: Pytest log capture fixture.
    """
    response = _FakeResponse(
        {"access_token": "response-token", "ok": True},
        headers={"X-AUTH-TOKEN": "header-token", "Server": "s"},
    )

    @request_with_logging
    async def send(**kwargs: Any) -> ClientResponse:
        """Return the fake response.

        Args:
            kwargs: Request keyword arguments.

        Returns:
            The fake response.
        """
        return cast("ClientResponse", response)

    with caplog.at_level(logging.DEBUG, logger="blueair_api.util_http"):
        await send(
            url="https://example/prod/c/login",
            headers={"Authorization": "Bearer request-token", "idtoken": "jwt-token"},
            params={"oauth_token": "param-token", "did": "device"},
            json_body={"password": "hunter2", "n": "fanspeed"},
        )

    for secret in (
        "request-token",
        "jwt-token",
        "param-token",
        "hunter2",
        "response-token",
        "header-token",
    ):
        assert secret not in caplog.text
    assert "device" in caplog.text
    assert "fanspeed" in caplog.text
    assert "Server" in caplog.text


async def test_send_with_timeout_wraps_timeouts_as_client_errors() -> None:
    """Raise a ``RequestTimeoutError`` that callers can catch as either error type."""

    async def stalled() -> ClientResponse:
        """Raise the plain ``TimeoutError`` aiohttp raises for a total timeout.

        Raises:
            TimeoutError: Always.
        """
        raise TimeoutError

    with pytest.raises(RequestTimeoutError) as error:
        await send_with_timeout(stalled())

    assert isinstance(error.value, ClientError)
    assert isinstance(error.value, TimeoutError)
    assert str(REQUEST_TIMEOUT_SECONDS) in str(error.value)


async def test_send_with_timeout_returns_the_response() -> None:
    """Return the response of a request that completes in time."""
    response = object()

    async def completed() -> Any:
        """Return the response after yielding once.

        Returns:
            The sentinel response.
        """
        await asyncio.sleep(0)
        return response

    assert await send_with_timeout(completed()) is response

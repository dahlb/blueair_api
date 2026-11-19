"""Tests for ``request_with_errors`` (the AWS response error classifier).

Regression coverage for a production incident: the Blueair AWS/Cognito
endpoints occasionally answer with an empty or otherwise non-JSON body
(observed as a zero-byte body during a cloud-side hiccup). Before this
fix, ``response.json()`` raised a raw ``JSONDecodeError`` that the
wrapper re-raised as-is, bypassing its own status-code classification.
Callers (e.g. ``ha_blueair``) only know how to retry ``ClientError``
subclasses, so the raw parse error was a permanent, unretriable crash
instead of a transient, retryable one.
"""

from __future__ import annotations

from unittest import IsolatedAsyncioTestCase

from aiohttp import ClientError
import pytest

from blueair_api.errors import LoginError, RateError, ResponseError, ServerError, SessionError
from blueair_api.http_aws_blueair import request_with_errors


class _FakeResponse:
    """Minimal aiohttp.ClientResponse stand-in."""

    def __init__(
        self, status: int, body: object = None, *, json_exc: BaseException | None = None
    ) -> None:
        self.status = status
        self._body = body
        self._json_exc = json_exc

    async def json(self, content_type=None):
        if self._json_exc is not None:
            raise self._json_exc
        return self._body

    async def text(self) -> str:
        return "" if self._json_exc is None else "not json"


@request_with_errors
async def _wrapped(*, url: str, response: _FakeResponse) -> _FakeResponse:
    return response


class TestNonJsonResponseBody(IsolatedAsyncioTestCase):
    """A body that fails to parse must not leak the raw parse exception."""

    async def test_non_json_200_raises_session_error(self) -> None:
        response = _FakeResponse(200, json_exc=ValueError("not json"))
        with pytest.raises(SessionError):
            await _wrapped(url="https://example/prod/c/registered-devices", response=response)

    async def test_empty_body_5xx_raises_retryable_server_error(self) -> None:
        # The observed production failure: a zero-byte body during
        # refresh_jwt(), surfaced by orjson as a JSONDecodeError. With an
        # HTTP 5xx it is a server error, not a session problem, so it does
        # not force a re-login; it is still a ClientError callers can retry.
        response = _FakeResponse(
            502, json_exc=ValueError("unexpected character: line 1 column 1 (char 0)")
        )
        with pytest.raises(ServerError) as error:
            await _wrapped(url="https://example/prod/c/registered-devices", response=response)
        assert isinstance(error.value, ClientError)
        assert not isinstance(error.value, SessionError)

    async def test_empty_body_non_5xx_raises_session_error(self) -> None:
        response = _FakeResponse(
            401, json_exc=ValueError("unexpected character: line 1 column 1 (char 0)")
        )
        with pytest.raises(SessionError):
            await _wrapped(url="https://example/prod/c/registered-devices", response=response)

    async def test_empty_body_login_url_still_raises_session_error(self) -> None:
        # Non-JSON classification happens before the login/session URL
        # branch, so even a /accounts.login URL gets a SessionError
        # (a ClientError subclass, still retryable) rather than a raw
        # parse exception. It intentionally does not need to be a
        # LoginError specifically -- the caller just needs something
        # it knows how to retry.
        response = _FakeResponse(400, json_exc=ValueError("not json"))
        with pytest.raises(SessionError):
            await _wrapped(url="https://example/accounts.login", response=response)


class TestExistingClassificationUnaffected(IsolatedAsyncioTestCase):
    """Valid JSON bodies keep their pre-existing behavior."""

    async def test_200_with_valid_json_returns_response(self) -> None:
        response = _FakeResponse(200, {"ok": True})
        result = await _wrapped(url="https://example/prod/c/registered-devices", response=response)
        assert result is response

    async def test_400_login_url_raises_login_error(self) -> None:
        response = _FakeResponse(400, {"error": "bad credentials"})
        with pytest.raises(LoginError):
            await _wrapped(url="https://example/accounts.login", response=response)

    async def test_400_non_login_url_raises_session_error(self) -> None:
        response = _FakeResponse(400, {"error": "expired"})
        with pytest.raises(SessionError):
            await _wrapped(url="https://example/prod/c/registered-devices", response=response)

    async def test_unknown_status_code_raises_value_error(self) -> None:
        response = _FakeResponse(302, {})
        with pytest.raises(ValueError) as error:
            await _wrapped(url="https://example/prod/c/registered-devices", response=response)
        assert isinstance(error.value, ResponseError)
        assert isinstance(error.value, ClientError)


class TestRateLimitAndServerErrors(IsolatedAsyncioTestCase):
    """Rate limits and server errors do not look like expired sessions."""

    async def test_429_raises_rate_error(self) -> None:
        response = _FakeResponse(429, {"message": "Too Many Requests"})
        with pytest.raises(RateError) as error:
            await _wrapped(url="https://example/prod/c/registered-devices", response=response)
        assert not isinstance(error.value, SessionError)

    async def test_body_status_429_raises_rate_error(self) -> None:
        response = _FakeResponse(200, {"statusCode": 429})
        with pytest.raises(RateError):
            await _wrapped(url="https://example/accounts.login", response=response)

    async def test_5xx_raise_server_error(self) -> None:
        for status in (500, 502, 503, 599):
            response = _FakeResponse(status, {"statusCode": status})
            with pytest.raises(ServerError) as error:
                await _wrapped(url="https://example/prod/c/registered-devices", response=response)
            # Still a ValueError, like the unknown-status error it replaces.
            assert isinstance(error.value, ValueError)
            assert not isinstance(error.value, SessionError)

    async def test_401_and_403_still_raise_session_error(self) -> None:
        for status in (401, 403):
            response = _FakeResponse(status, {"statusCode": status})
            with pytest.raises(SessionError):
                await _wrapped(url="https://example/prod/c/registered-devices", response=response)

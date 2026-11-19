"""Tests for ``HttpAwsBlueair`` re-authentication, token expiry and session handling."""

from __future__ import annotations

import asyncio
import base64
from datetime import UTC, datetime, timedelta
import json
from typing import Any

from aiohttp import ClientSession
import pytest

from blueair_api.const import ACCESS_TOKEN_REFRESH_MARGIN_SECONDS
from blueair_api.errors import SessionError
from blueair_api.http_aws_blueair import (
    HttpAwsBlueair,
    _refresh_time_from_claims,
    request_with_active_session,
)
from blueair_api.http_blueair import HttpBlueair
from blueair_api.util_http import REQUEST_TIMEOUT


def _access_token(claims: dict[str, Any]) -> str:
    """Build an unsigned JWT-shaped token carrying ``claims``.

    Args:
        claims: JWT payload claims.

    Returns:
        A ``header.payload.signature`` token string.
    """
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


class _FakeSession:
    """aiohttp session double that records ``close`` calls."""

    def __init__(self) -> None:
        """Initialize close state."""
        self.closed = False

    async def close(self) -> None:
        """Record the close request."""
        self.closed = True


class CountingClient(HttpAwsBlueair):
    """Client whose re-authentication issues numbered tokens without the network."""

    def __init__(self, exp: float | None = None) -> None:
        """Initialize a client with no cached credentials.

        Args:
            exp: ``exp`` claim to put in issued tokens, or ``None`` for none.
        """
        super().__init__(
            username="user@example.com",
            password="password",
            client_session=_FakeSession(),  # type: ignore[arg-type]
        )
        self.logins = 0
        self.exp = exp

    async def _refresh_access_token_unlocked(self) -> None:
        """Issue the next numbered token, yielding so concurrent callers interleave."""
        await asyncio.sleep(0.01)
        self.logins += 1
        claims: dict[str, Any] = {"username": f"user-{self.logins}"}
        if self.exp is not None:
            claims["exp"] = self.exp
        self.access_token = f"token-{self.logins}"
        self.user_id = claims["username"]
        self.access_token_refresh_at = _refresh_time_from_claims(claims)


async def test_concurrent_get_access_token_logs_in_once() -> None:
    """Share one re-authentication between concurrent callers."""
    client = CountingClient()

    tokens = await asyncio.gather(*(client.get_access_token() for _ in range(5)))

    assert client.logins == 1
    assert set(tokens) == {"token-1"}


async def test_concurrent_get_user_id_logs_in_once() -> None:
    """Share one re-authentication between concurrent user-ID lookups."""
    client = CountingClient()

    user_ids = await asyncio.gather(*(client.get_user_id() for _ in range(5)))

    assert client.logins == 1
    assert set(user_ids) == {"user-1"}


async def test_requests_rejected_together_re_login_once() -> None:
    """Re-authenticate once when several requests using one token are rejected."""
    client = CountingClient()
    await client.get_access_token()
    rejected_once: set[int] = set()

    @request_with_active_session
    async def request(self: CountingClient, number: int) -> str:
        """Reject the first attempt made with ``token-1``.

        Args:
            self: Client making the request.
            number: Request number.

        Returns:
            The token the successful attempt used.

        Raises:
            SessionError: On the first attempt with ``token-1``.
        """
        token = await self.get_access_token()
        await asyncio.sleep(0.01)
        if token == "token-1" and number not in rejected_once:
            rejected_once.add(number)
            raise SessionError("expired")
        return token

    results = await asyncio.gather(*(request(client, number) for number in range(5)))

    assert client.logins == 2
    assert set(results) == {"token-2"}


async def test_discard_rejected_session_keeps_a_replaced_token() -> None:
    """Keep a token a concurrent request already refreshed."""
    client = CountingClient()
    await client.get_access_token()

    await client._discard_rejected_session("token-0")

    assert client.access_token == "token-1"
    assert client.user_id == "user-1"


async def test_discard_rejected_session_clears_the_rejected_token() -> None:
    """Clear every cached credential when the rejected token is still current."""
    client = CountingClient()
    await client.get_access_token()
    client.mqtt_auth_token = "mqtt"

    await client._discard_rejected_session("token-1")

    assert client.access_token is None
    assert client.access_token_refresh_at is None
    assert client.user_id is None
    assert client.mqtt_auth_token is None


async def test_access_token_is_refreshed_once_its_refresh_time_passes() -> None:
    """Refresh a token once the refresh time before its ``exp`` claim has passed."""
    client = CountingClient(exp=(datetime.now(UTC) + timedelta(hours=1)).timestamp())
    await client.get_access_token()
    # Simulate time passing into the refresh margin before expiry.
    client.access_token_refresh_at = datetime.now(UTC) - timedelta(seconds=1)

    token = await client.get_access_token()

    assert client.logins == 2
    assert token == "token-2"


async def test_access_token_is_reused_outside_the_refresh_margin() -> None:
    """Reuse a token that is valid well beyond the refresh margin."""
    client = CountingClient(exp=(datetime.now(UTC) + timedelta(hours=1)).timestamp())
    await client.get_access_token()

    await client.get_access_token()

    assert client.logins == 1


async def test_access_token_without_exp_is_reused_until_rejected() -> None:
    """Keep the previous behavior for a token with no ``exp`` claim."""
    client = CountingClient()
    await client.get_access_token()

    await client.get_access_token()

    assert client.logins == 1
    assert client.access_token_refresh_at is None


def test_refresh_time_uses_the_margin_for_long_lived_tokens() -> None:
    """Refresh a long-lived token the full margin before it expires."""
    expires_at = datetime.now(UTC) + timedelta(hours=1)

    refresh_at = _refresh_time_from_claims({"exp": expires_at.timestamp()})

    assert refresh_at is not None
    assert abs((expires_at - refresh_at).total_seconds() - ACCESS_TOKEN_REFRESH_MARGIN_SECONDS) < 1


def test_refresh_time_halves_the_lifetime_of_short_lived_tokens() -> None:
    """Refresh a token shorter-lived than the margin halfway through its lifetime."""
    lifetime = ACCESS_TOKEN_REFRESH_MARGIN_SECONDS / 2
    expires_at = datetime.now(UTC) + timedelta(seconds=lifetime)

    refresh_at = _refresh_time_from_claims({"exp": expires_at.timestamp()})

    assert refresh_at is not None
    assert abs((expires_at - refresh_at).total_seconds() - lifetime / 2) < 1


@pytest.mark.parametrize("claims", [{}, {"exp": "soon"}, {"exp": True}, {"exp": 10**20}])
def test_refresh_time_is_none_without_a_usable_exp(claims: dict[str, Any]) -> None:
    """Return ``None`` when the ``exp`` claim is missing or unusable.

    Args:
        claims: Decoded JWT claims.
    """
    assert _refresh_time_from_claims(claims) is None


async def test_refresh_access_token_reads_exp_from_the_access_token() -> None:
    """Store the refresh time from the ``exp`` claim of the real login response."""
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    token = _access_token({"username": "user-1", "exp": expires_at.timestamp()})

    class LoginResponse:
        """Fake BlueCloud login response."""

        status = 200

        async def json(self, content_type: str | None = None) -> dict[str, str]:
            """Return the login body.

            Args:
                content_type: Ignored content type check.

            Returns:
                The login body.
            """
            return {"access_token": token}

    class LoginClient(HttpAwsBlueair):
        """Client that skips Gigya and fakes the BlueCloud login request."""

        async def refresh_jwt(self) -> None:
            """Set a JWT without calling Gigya."""
            self.jwt = "jwt"

        async def _post_request_with_logging_and_errors_raised(  # type: ignore[override]
            self, **kwargs: Any
        ) -> LoginResponse:
            """Return the fake login response.

            Args:
                kwargs: Request keyword arguments.

            Returns:
                The fake login response.
            """
            return LoginResponse()

    client = LoginClient(
        username="user@example.com",
        password="password",
        client_session=_FakeSession(),  # type: ignore[arg-type]
    )

    await client.refresh_access_token()

    assert client.user_id == "user-1"
    assert client.access_token_refresh_at is not None
    assert (
        abs(
            (expires_at - client.access_token_refresh_at).total_seconds()
            - ACCESS_TOKEN_REFRESH_MARGIN_SECONDS
        )
        < 1
    )


@pytest.mark.parametrize("client_class", [HttpAwsBlueair, HttpBlueair])
async def test_cleanup_leaves_a_provided_session_open(client_class: type) -> None:
    """Leave a caller-provided session, such as Home Assistant's, open.

    Args:
        client_class: HTTP client under test.
    """
    session = _FakeSession()
    client = client_class(username="user@example.com", password="password", client_session=session)

    await client.cleanup_client_session()

    assert not session.closed


@pytest.mark.parametrize("client_class", [HttpAwsBlueair, HttpBlueair])
async def test_cleanup_closes_an_owned_session(client_class: type) -> None:
    """Close the session the client created itself.

    Args:
        client_class: HTTP client under test.
    """
    client = client_class(username="user@example.com", password="password")
    assert isinstance(client.api_session, ClientSession)

    await client.cleanup_client_session()

    assert client.api_session.closed


class _OkResponse:
    """Successful aiohttp.ClientResponse stand-in with an empty JSON body."""

    status = 200
    headers: dict[str, str] = {}  # noqa: RUF012

    async def json(self, content_type: str | None = None) -> dict[str, Any]:
        """Return an empty JSON object.

        Args:
            content_type: Ignored content type check.

        Returns:
            An empty dictionary.
        """
        return {}

    async def text(self) -> str:
        """Return an empty JSON object as text.

        Returns:
            ``"{}"``.
        """
        return "{}"


class _RecordingSession:
    """Session double that records request keyword arguments."""

    def __init__(self) -> None:
        """Initialize the recorded calls."""
        self.calls: list[dict[str, Any]] = []

    async def get(self, **kwargs: Any) -> _OkResponse:
        """Record a GET request.

        Args:
            kwargs: Request keyword arguments.

        Returns:
            A successful response.
        """
        self.calls.append(kwargs)
        return _OkResponse()

    async def post(self, **kwargs: Any) -> _OkResponse:
        """Record a POST request.

        Args:
            kwargs: Request keyword arguments.

        Returns:
            A successful response.
        """
        self.calls.append(kwargs)
        return _OkResponse()


async def test_requests_carry_the_request_timeout() -> None:
    """Bound every GET and POST of both clients with the request timeout."""
    aws_session = _RecordingSession()
    aws = HttpAwsBlueair(
        username="user@example.com",
        password="password",
        client_session=aws_session,  # type: ignore[arg-type]
    )
    legacy_session = _RecordingSession()
    legacy = HttpBlueair(
        username="user@example.com",
        password="password",
        client_session=legacy_session,  # type: ignore[arg-type]
    )

    await aws._get_request_with_logging_and_errors_raised(url="https://example/get")
    await aws._post_request_with_logging_and_errors_raised(url="https://example/post")
    await legacy._get_request_with_logging_and_errors_raised(url="https://example/get")
    await legacy._post_request_with_logging_and_errors_raised(
        url="https://example/post", json_body={}
    )

    assert [call["timeout"] for call in aws_session.calls + legacy_session.calls] == [
        REQUEST_TIMEOUT
    ] * 4

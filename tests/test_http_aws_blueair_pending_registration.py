"""Tests for the Gigya "Account Pending Registration" self-heal.

Blueair made profile field ``name`` a required registration field; accounts
created before that change are refused at ``accounts.login`` with an HTTP 200
whose body carries ``statusCode: 206`` / ``errorCode: 206001`` and a
``regToken``.  Before the fix, ``request_with_errors`` misread the body-level
206 as an HTTP status, fell through to ``ValueError: unknown status code 206``,
and setup failed permanently (dahlb/ha_blueair#421).

Now ``refresh_session`` completes the pending registration transparently
(``accounts.setAccountInfo`` with the profile name, then
``accounts.finalizeRegistration``) and retries the login once.
"""
from __future__ import annotations

import json
from unittest import IsolatedAsyncioTestCase

from blueair_api.errors import LoginError
from blueair_api.http_aws_blueair import (
    HttpAwsBlueair,
    request_with_errors,
)

PENDING_REGISTRATION_BODY = {
    "errorCode": 206001,
    "errorDetails": "Missing required fields for registration: name",
    "errorMessage": "Account Pending Registration",
    "statusCode": 206,
    "statusReason": "Partial Content",
    "isRegistered": True,
    "regToken": "reg-token-1",
    "profile": {"firstName": "Jonas", "lastName": "Friedmann", "email": "j@example.com"},
    "sessionInfo": {"expires_in": "3600"},
}

LOGIN_SUCCESS_BODY = {
    "errorCode": 0,
    "statusCode": 200,
    "sessionInfo": {"sessionToken": "tok", "sessionSecret": "sec", "expires_in": "3600"},
}

GIGYA_OK_BODY = {"errorCode": 0, "statusCode": 200, "registered": True}


class _FakeResponse:
    """Minimal aiohttp.ClientResponse stand-in."""

    def __init__(self, status: int, body: object) -> None:
        self.status = status
        self._body = body

    async def json(self, content_type=None):
        return self._body

    async def text(self) -> str:
        return json.dumps(self._body)


def _make_client() -> HttpAwsBlueair:
    """Build a client whose POSTs replay ``fake_post.script`` in order.

    Each script entry is ``(url_substring, fake_response)``; every issued
    POST is recorded on ``fake_post.calls`` as ``(url, form_data)``.
    """
    client = HttpAwsBlueair(
        username="j@example.com",
        password="hunter2",
        client_session=object(),  # type: ignore[arg-type]
    )

    async def fake_post(*, url: str, form_data=None, **kwargs):
        fake_post.calls.append((url, form_data))
        url_substring, response = fake_post.script.pop(0)
        assert url_substring in url, f"{url} did not match {url_substring!r}"
        return response

    fake_post.script = []
    fake_post.calls = []
    client._post_request_with_logging_and_errors_raised = fake_post
    return client


class TestSelfHealPendingRegistration(IsolatedAsyncioTestCase):
    async def test_refresh_session_completes_pending_registration(self) -> None:
        client = _make_client()
        client._post_request_with_logging_and_errors_raised.script = [
            ("accounts.login", _FakeResponse(200, PENDING_REGISTRATION_BODY)),
            ("accounts.setAccountInfo", _FakeResponse(200, GIGYA_OK_BODY)),
            ("accounts.finalizeRegistration", _FakeResponse(200, GIGYA_OK_BODY)),
            ("accounts.login", _FakeResponse(200, LOGIN_SUCCESS_BODY)),
        ]
        await client.refresh_session()
        self.assertEqual(client.session_token, "tok")
        self.assertEqual(client.session_secret, "sec")
        urls = [url for url, _ in client._post_request_with_logging_and_errors_raised.calls]
        self.assertEqual(
            urls,
            [
                "https://accounts.us1.gigya.com/accounts.login",
                "https://accounts.us1.gigya.com/accounts.setAccountInfo",
                "https://accounts.us1.gigya.com/accounts.finalizeRegistration",
                "https://accounts.us1.gigya.com/accounts.login",
            ],
        )

    async def test_refresh_session_without_profile_name_raises_login_error(self) -> None:
        body = dict(PENDING_REGISTRATION_BODY, profile={})
        client = _make_client()
        client._post_request_with_logging_and_errors_raised.script = [
            ("accounts.login", _FakeResponse(200, body)),
        ]
        with self.assertRaises(LoginError):
            await client.refresh_session()

    async def test_finalize_failure_raises_login_error(self) -> None:
        failure = dict(
            GIGYA_OK_BODY,
            errorCode=400009,
            errorMessage="Invalid data",
            errorDetails="nope",
        )
        client = _make_client()
        client._post_request_with_logging_and_errors_raised.script = [
            ("accounts.login", _FakeResponse(200, PENDING_REGISTRATION_BODY)),
            ("accounts.setAccountInfo", _FakeResponse(200, failure)),
        ]
        with self.assertRaises(LoginError):
            await client.refresh_session()

    async def test_successful_login_is_unchanged(self) -> None:
        client = _make_client()
        client._post_request_with_logging_and_errors_raised.script = [
            ("accounts.login", _FakeResponse(200, LOGIN_SUCCESS_BODY)),
        ]
        await client.refresh_session()
        self.assertEqual(client.session_token, "tok")
        self.assertEqual(client.session_secret, "sec")


@request_with_errors
async def _wrapped(*, url: str, response: _FakeResponse) -> _FakeResponse:
    return response


class TestWrapperPasses206ThroughForLogin(IsolatedAsyncioTestCase):
    async def test_gigya_206_on_login_url_passes_through(self) -> None:
        response = _FakeResponse(200, PENDING_REGISTRATION_BODY)
        result = await _wrapped(url="https://accounts.us1.gigya.com/accounts.login", response=response)
        self.assertIs(result, response)

    async def test_gigya_206_on_other_url_still_raises_value_error(self) -> None:
        response = _FakeResponse(200, PENDING_REGISTRATION_BODY)
        with self.assertRaises(ValueError):
            await _wrapped(
                url="https://example/prod/c/registered-devices", response=response
            )

    async def test_unknown_status_error_includes_response_body(self) -> None:
        response = _FakeResponse(200, {"statusCode": 599, "error": "mystery"})
        with self.assertRaises(ValueError) as ctx:
            await _wrapped(
                url="https://example/prod/c/registered-devices", response=response
            )
        self.assertIn("mystery", str(ctx.exception))

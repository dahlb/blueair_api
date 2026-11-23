"""Tests for ``HttpAwsBlueair.set_device_info``, which writes one device setting."""

from __future__ import annotations

from unittest import mock

from aiohttp import ClientError
import pytest

from blueair_api.errors import ResponseError
from blueair_api.http_aws_blueair import HttpAwsBlueair


def _client(response_text: str) -> tuple[HttpAwsBlueair, mock.AsyncMock]:
    """Return a client whose write request answers with the given body.

    Args:
        response_text: Body of the API's answer to the write.

    Returns:
        tuple[HttpAwsBlueair, mock.AsyncMock]: The client, and the stand-in
        for its POST request.
    """
    client = HttpAwsBlueair(
        username="user@example.com",
        password="hunter2",
        client_session=object(),  # type: ignore[arg-type]
    )
    response = mock.Mock()
    response.text = mock.AsyncMock(return_value=response_text)
    post = mock.AsyncMock(return_value=response)
    client._post_request_with_logging_and_errors_raised = post  # type: ignore[method-assign]
    client.get_access_token = mock.AsyncMock(return_value="token")  # type: ignore[method-assign]
    return client, post


async def test_accepted_write_returns_true() -> None:
    """Return True, and send the SenML body, when the API answers Success."""
    client, post = _client("Success")

    assert await client.set_device_info("fake-uuid", "standby", "vb", True) is True

    post.assert_awaited_once()
    assert post.await_args is not None
    kwargs = post.await_args.kwargs
    assert kwargs["json_body"] == {"n": "standby", "vb": True}
    assert kwargs["url"].endswith("/prod/c/fake-uuid/a/standby")
    assert kwargs["headers"] == {"Authorization": "Bearer token"}


@pytest.mark.parametrize(
    ("response_text", "message"),
    [
        ("Failure", "device did not accept standby: Failure"),
        ("", "device did not accept standby: empty response"),
        (
            '{"message": "Device offline"}',
            'device did not accept standby: {"message": "Device offline"}',
        ),
        ("x" * 600, "device did not accept standby: " + "x" * 500),
    ],
)
async def test_rejected_write_raises_response_error(response_text: str, message: str) -> None:
    """Raise, with the API's answer, when the write isn't accepted."""
    client, _ = _client(response_text)

    with pytest.raises(ResponseError) as error:
        await client.set_device_info("fake-uuid", "standby", "vb", True)

    assert str(error.value) == message
    # Callers that retry or report ClientError (e.g. ha_blueair) handle it as-is.
    assert isinstance(error.value, ClientError)

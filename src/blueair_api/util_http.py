"""Helpers for HTTP calls: request/response debug logging and request timeouts."""

from collections.abc import Awaitable, Callable
import logging
from typing import Any

from aiohttp import ClientResponse, ClientTimeout

from .const import REQUEST_TIMEOUT_SECONDS
from .errors import RequestTimeoutError
from .util import clean_dictionary_for_logging

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)


async def send_with_timeout(request: Awaitable[ClientResponse]) -> ClientResponse:
    """Await an aiohttp request, converting a timeout into a package error.

    The request itself should be made with ``timeout=REQUEST_TIMEOUT``.
    aiohttp reports an expired total timeout as a plain ``TimeoutError``,
    which is not a ``ClientError``; it is re-raised as ``RequestTimeoutError``
    so callers that retry client errors retry timeouts too.

    Args:
        request: The pending ``ClientSession.get`` or ``post`` call.

    Returns:
        The HTTP response.

    Raises:
        RequestTimeoutError: If the request does not complete in time.
    """
    try:
        return await request
    except TimeoutError as error:
        _LOGGER.debug("Blueair request timed out after %s seconds", REQUEST_TIMEOUT_SECONDS)
        raise RequestTimeoutError(
            f"Blueair request timed out after {REQUEST_TIMEOUT_SECONDS} seconds"
        ) from error


def request_with_logging(
    func: Callable[..., Awaitable[Any]],
) -> Callable[..., Awaitable[Any]]:
    """Wrap an async HTTP call, logging its request and response for debugging.

    Request headers, params and JSON bodies and the response headers and JSON
    body pass through ``clean_dictionary_for_logging``, so tokens and
    credentials are masked.

    Args:
        func: The HTTP call to wrap. It must take ``url`` as a keyword argument.

    Returns:
        The wrapped call.
    """

    async def request_with_logging_wrapper(*args: Any, **kwargs: Any) -> Any:
        """Log the outgoing request, call ``func``, then log the response.

        Args:
            args: Positional arguments for ``func``.
            kwargs: Keyword arguments for ``func``, including ``url``.

        Returns:
            The response returned by ``func``.
        """
        url = kwargs["url"]
        request_message = f"sending {url} request"
        headers = kwargs.get("headers")
        if headers is not None:
            request_message += f" headers: {clean_dictionary_for_logging(headers)}"
        params = kwargs.get("params")
        if params is not None:
            request_message += f" params: {clean_dictionary_for_logging(params)}"
        json_body = kwargs.get("json_body")
        if json_body is not None:
            request_message += f" json: {clean_dictionary_for_logging(json_body)}"
        _LOGGER.debug(request_message)
        response = await func(*args, **kwargs)
        _LOGGER.debug("response headers:%s", clean_dictionary_for_logging(response.headers))
        _LOGGER.debug("response status: %s", response.status)
        try:
            response_json = await response.json(content_type=None)
            _LOGGER.debug("response json: %s", clean_dictionary_for_logging(response_json))
        except ValueError, UnicodeDecodeError:
            response_text = await response.text()
            _LOGGER.debug("response raw: %s", response_text)
        return response

    return request_with_logging_wrapper

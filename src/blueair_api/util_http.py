"""Decorator that logs the request and response of an HTTP call."""

from collections.abc import Awaitable, Callable
import logging
from typing import Any

from .util import clean_dictionary_for_logging

_LOGGER = logging.getLogger(__name__)


def request_with_logging(
    func: Callable[..., Awaitable[Any]],
) -> Callable[..., Awaitable[Any]]:
    """Wrap an async HTTP call, logging its request and response for debugging."""

    async def request_with_logging_wrapper(*args: Any, **kwargs: Any) -> Any:
        """Log the outgoing request, call ``func``, then log the response."""
        url = kwargs["url"]
        request_message = f"sending {url} request"
        headers = kwargs.get("headers")
        if headers is not None:
            request_message = request_message + f"headers: {headers}"
        params = kwargs.get("params")
        if params is not None:
            request_message = request_message + f"params: {params}"
        json_body = kwargs.get("json_body")
        if json_body is not None:
            request_message = (
                request_message
                + f"sending {url} request with {clean_dictionary_for_logging(json_body)}"
            )
        _LOGGER.debug(request_message)
        response = await func(*args, **kwargs)
        _LOGGER.debug("response headers:%s", clean_dictionary_for_logging(response.headers))
        _LOGGER.debug("response status: %s", response.status)
        try:
            response_json = await response.json(content_type=None)
            if isinstance(response_json, dict):
                _LOGGER.debug("response json: %s", clean_dictionary_for_logging(response_json))
            else:
                # JSON may be a string, list or scalar. Never log its raw content;
                # it may contain an authentication token or other secrets.
                _LOGGER.debug("response json type: %s", type(response_json).__name__)
        except (ValueError, UnicodeDecodeError):
            response_text = await response.text()
            _LOGGER.debug("response raw: %s", response_text)
        return response

    return request_with_logging_wrapper

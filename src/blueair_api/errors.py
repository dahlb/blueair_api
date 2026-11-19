"""Exception hierarchy raised by the Blueair API clients."""

from aiohttp import ClientError


class BaseError(ClientError):
    """Base class for all errors raised by this package."""


class RateError(BaseError):
    """Raised when the Blueair API reports that a rate limit was hit."""


class AuthError(BaseError):
    """Raised when authentication with the Blueair API fails."""


class LoginError(AuthError):
    """Raised when a login attempt is rejected by the Blueair API."""


class SessionError(AuthError):
    """Raised when an established session is no longer valid."""


class ResponseError(BaseError, ValueError):
    """Raised when the Blueair API answers with an unexpected status.

    Also a ``ValueError`` so callers that caught the ``ValueError`` raised for
    unknown status codes before this class existed keep working.
    """


class ServerError(ResponseError):
    """Raised when the Blueair API fails with an HTTP 5xx server error.

    Server errors are not session problems, so they do not trigger a
    re-login.
    """


class RequestTimeoutError(BaseError, TimeoutError):
    """Raised when a Blueair API request does not complete in time.

    Also a ``TimeoutError`` so callers that already catch timeouts keep
    working, and a ``ClientError`` so callers that retry client errors retry
    it too.
    """

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

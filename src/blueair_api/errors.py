from aiohttp import ClientError


class BaseError(ClientError):
    pass


class RateError(BaseError):
    pass


class AuthError(BaseError):
    pass


class LoginError(AuthError):
    pass


class SessionError(AuthError):
    pass

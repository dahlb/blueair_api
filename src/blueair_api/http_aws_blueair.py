"""HTTP client for Blueair's AWS-backed cloud API (Gigya auth + BlueCloud REST)."""

from asyncio import Lock
import base64
from collections.abc import Awaitable, Callable, Iterable
from datetime import UTC, datetime, timedelta
import functools
import json
from logging import getLogger
from typing import TYPE_CHECKING, Any

from aiohttp import ClientResponse, ClientSession, FormData

from .const import ACCESS_TOKEN_REFRESH_MARGIN_SECONDS, AWS_APIKEYS
from .errors import LoginError, RateError, ResponseError, ServerError, SessionError
from .util_http import REQUEST_TIMEOUT, request_with_logging, send_with_timeout

if TYPE_CHECKING:
    from .region_discovery import CloudRegionScan

_LOGGER = getLogger(__name__)

# Gigya body-level statusCode / errorCode for "Account Pending Registration".
# Blueair made profile field ``name`` a required registration field; accounts
# created before that change are refused at accounts.login until registration
# is completed (observed starting 2026-09-22, dahlb/ha_blueair#421).
GIGYA_STATUS_CODE_PENDING_REGISTRATION = 206
GIGYA_ERROR_CODE_PENDING_REGISTRATION = 206001


def request_with_active_session(
    func: Callable[..., Awaitable[Any]],
) -> Callable[..., Awaitable[Any]]:
    """Retry ``func`` once with cleared session state after a ``SessionError``.

    Only the access token the request used is discarded. If a concurrent
    request has already replaced it, the new token is kept, so several
    requests rejected together cause one re-login instead of one each.

    Args:
        func: An ``HttpAwsBlueair`` method that makes an authenticated request.

    Returns:
        The wrapped method.
    """

    @functools.wraps(func)
    async def request_with_active_session_wrapper(*args: Any, **kwargs: Any) -> Any:
        """Call ``func``, re-authenticating and retrying once on ``SessionError``.

        Args:
            args: Positional arguments for ``func``; ``args[0]`` is the client.
            kwargs: Keyword arguments for ``func``.

        Returns:
            The result of ``func``.
        """
        _LOGGER.debug("session")
        self: HttpAwsBlueair = args[0]
        rejected_access_token = self.access_token
        try:
            return await func(*args, **kwargs)
        except SessionError:
            _LOGGER.debug("got invalid session, attempting to repair and resend")
            await self._discard_rejected_session(rejected_access_token)
            return await func(*args, **kwargs)

    return request_with_active_session_wrapper


def request_with_errors(
    func: Callable[..., Awaitable[Any]],
) -> Callable[..., Awaitable[ClientResponse]]:
    """Inspect a response for Gigya/BlueCloud error payloads and raise accordingly.

    The status is the body's ``statusCode`` when present, else the HTTP status.

    * 200 returns the response, as does Gigya's 206 pending-registration
      answer to ``accounts.login``.
    * 429 raises ``RateError``.
    * Other 4xx raise ``LoginError`` for ``accounts.login`` and
      ``SessionError`` otherwise, which makes ``request_with_active_session``
      re-authenticate and retry.
    * 5xx raise ``ServerError``, without discarding the session.
    * Anything else raises ``ResponseError``.
    * A body that is not JSON raises ``ServerError`` for an HTTP 5xx and
      ``SessionError`` otherwise.

    Args:
        func: The HTTP call to wrap. It must take ``url`` as a keyword argument.

    Returns:
        The wrapped call.
    """

    @functools.wraps(func)
    async def request_with_errors_wrapper(*args: Any, **kwargs: Any) -> ClientResponse:
        """Call ``func`` and raise the package error matching its response.

        Args:
            args: Positional arguments for ``func``.
            kwargs: Keyword arguments for ``func``, including ``url``.

        Returns:
            The response, when it reports success.

        Raises:
            LoginError: If ``accounts.login`` rejects the credentials.
            RateError: If the API reports a rate limit.
            ResponseError: If the API answers with an unexpected status.
            ServerError: If the API fails with a server error.
            SessionError: If the session is rejected or the body is not JSON.
        """
        _LOGGER.debug("checking for errors")
        response: ClientResponse = await func(*args, **kwargs)
        status_code = response.status
        try:
            response_json = await response.json(content_type=None)
            if response_json is not None and "statusCode" in response_json:
                _LOGGER.debug("response json found, checking status code from response")
                status_code = response_json["statusCode"]
        except (json.JSONDecodeError, ValueError) as e:
            if status_code >= 500:
                _LOGGER.debug(
                    "response body was not valid JSON (http status %s), "
                    "treating as a server error: %s",
                    status_code,
                    e,
                )
                raise ServerError(f"non-JSON response (http status {status_code})") from e
            _LOGGER.debug(
                "response body was not valid JSON (http status %s), "
                "treating as a transient session/auth error: %s",
                status_code,
                e,
            )
            raise SessionError(f"non-JSON response (http status {status_code})") from e
        if status_code == 200:
            _LOGGER.debug("response 200")
            return response
        if status_code == 429:
            _LOGGER.debug("rate limited, %s", status_code)
            raise RateError(await response.text())
        if 400 <= status_code < 500:
            _LOGGER.debug("auth error, %s", status_code)
            url = kwargs["url"]
            response_text = await response.text()
            if "accounts.login" in url:
                _LOGGER.debug("login error")
                raise LoginError(response_text)
            _LOGGER.debug("session error")
            raise SessionError(response_text)
        if (
            status_code == GIGYA_STATUS_CODE_PENDING_REGISTRATION
            and "accounts.login" in kwargs["url"]
        ):
            # Gigya answers accounts.login with an HTTP 200 whose body
            # carries statusCode 206 / errorCode 206001 when the account
            # is pending registration.  Pass the response through so
            # refresh_session() can complete the registration.
            _LOGGER.debug("Gigya login returned pending-registration (206)")
            return response
        response_text = await response.text()
        if 500 <= status_code < 600:
            _LOGGER.debug("server error, %s", status_code)
            raise ServerError(f"server error {status_code}: {response_text[:500]}")
        raise ResponseError(f"unknown status code {status_code}: {response_text[:500]}")

    return request_with_errors_wrapper


def _refresh_time_from_claims(claims: dict[str, Any]) -> datetime | None:
    """Return when to refresh an access token, from its decoded JWT claims.

    The token is refreshed ``ACCESS_TOKEN_REFRESH_MARGIN_SECONDS`` before its
    ``exp`` claim, or halfway through its remaining lifetime when that is
    shorter, so a short-lived token is not refreshed on every request.

    Args:
        claims: Decoded JWT payload of the access token.

    Returns:
        The refresh time, or ``None`` when the token has no usable ``exp``.
    """
    exp = claims.get("exp")
    if isinstance(exp, bool) or not isinstance(exp, int | float):
        return None
    now = datetime.now(UTC)
    try:
        expires_at = datetime.fromtimestamp(exp, UTC)
    except OverflowError, OSError, ValueError:
        return None
    remaining = (expires_at - now).total_seconds()
    margin = min(ACCESS_TOKEN_REFRESH_MARGIN_SECONDS, max(remaining, 0) / 2)
    return expires_at - timedelta(seconds=margin)


class HttpAwsBlueair:
    """Client for Blueair's AWS-backed cloud API (Gigya auth + BlueCloud REST)."""

    def __init__(
        self,
        username: str,
        password: str,
        region: str = "us",
        client_session: ClientSession | None = None,
        *,
        gigya_region: str | None = None,
        cloud_region: str | None = None,
    ) -> None:
        """Construct the Blueair AWS HTTP client.

        Parameters
        ----------
        username, password
            Account credentials.
        region
            Convenience knob that drives both Gigya account region and
            BlueCloud REST/MQTT region when neither ``gigya_region`` nor
            ``cloud_region`` is supplied.  Defaults to ``"us"``.
            Existing single-region callers should keep using this and
            see no behavior change.
        gigya_region
            Optional override for the Gigya account-auth region
            (controls ``accounts.login`` / ``accounts.getJWT`` host and
            the Gigya partner API key).  Defaults to ``region``.
        client_session
            Optional aiohttp session to reuse.  A session passed in belongs
            to the caller: ``cleanup_client_session`` leaves it open.  A new
            session is created when omitted.
        cloud_region
            Optional override for the BlueCloud REST + MQTT region
            (controls ``execute-api`` host and ``iot.amazonaws.com``
            broker).  Defaults to ``region``.

        Most accounts have ``gigya_region == cloud_region``.  Splitting
        them is only needed when the device's live AWS IoT broker is
        hosted in a different region than the account's Gigya tenant
        (e.g. US Gigya account whose hardware is provisioned against
        ``eu-west-1``).
        """
        self.username = username
        self.password = password
        self.gigya_region = gigya_region if gigya_region is not None else region
        self.cloud_region = cloud_region if cloud_region is not None else region

        if self.gigya_region not in AWS_APIKEYS:
            raise ValueError(
                f"Unknown gigya_region {self.gigya_region!r}; expected one of {sorted(AWS_APIKEYS)}"
            )
        if self.cloud_region not in AWS_APIKEYS:
            raise ValueError(
                f"Unknown cloud_region {self.cloud_region!r}; expected one of {sorted(AWS_APIKEYS)}"
            )

        self.session_token = None
        self.session_secret = None

        self.access_token = None
        self.user_id = None

        self.mqtt_auth_name = None
        self.mqtt_auth_signature = None
        self.mqtt_auth_token = None

        self.jwt = None

        # When to refresh the access token, from its ``exp`` claim. ``None``
        # means the token carries no expiry and is kept until rejected.
        self.access_token_refresh_at: datetime | None = None
        # Serializes re-authentication so concurrent requests log in once.
        self._auth_lock = Lock()

        self._owns_session = client_session is None
        if client_session is None:
            self.api_session = ClientSession(raise_for_status=False)
        else:
            self.api_session = client_session

    async def cleanup_client_session(self) -> None:
        """Close the HTTP client session if this client created it.

        A session passed in as ``client_session`` belongs to the caller and is
        left open.
        """
        if not self._owns_session:
            _LOGGER.debug("Leaving caller-provided aiohttp session open")
            return
        await self.api_session.close()

    @property
    def region(self) -> str:
        """Back-compat alias for ``cloud_region``.

        Older callers (notably ``mqtt_aws_blueair.MqttAwsBlueair`` and
        the Home Assistant integration's bootstrap path) read
        ``http_client.region`` to look up the MQTT broker / AWS IoT
        endpoint.  Those callers want the *cloud* region, so we expose
        ``cloud_region`` under the legacy name to avoid breaking them.
        """
        return self.cloud_region

    @region.setter
    def region(self, value: str) -> None:
        # Setting .region post-construction is undocumented but
        # historically possible; keep both halves in lock-step so
        # subclasses or test fixtures that reassign it don't end up
        # with a Gigya/Cloud split they didn't ask for.
        if value not in AWS_APIKEYS:
            raise ValueError(f"Unknown region {value!r}; expected one of {sorted(AWS_APIKEYS)}")
        self.gigya_region = value
        self.cloud_region = value

    @request_with_errors
    @request_with_logging
    async def _get_request_with_logging_and_errors_raised(
        self, url: str, headers: dict[str, str] | None = None, params: dict[str, Any] | None = None
    ) -> ClientResponse:
        return await send_with_timeout(
            self.api_session.get(url=url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
        )

    @request_with_errors
    @request_with_logging
    async def _post_request_with_logging_and_errors_raised(
        self,
        url: str,
        json_body: dict[str, Any] | None = None,
        form_data: FormData | None = None,
        headers: dict[str, str] | None = None,
    ) -> ClientResponse:
        return await send_with_timeout(
            self.api_session.post(
                url=url,
                data=form_data,
                json=json_body,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
        )

    async def _accounts_login(self) -> ClientResponse:
        url = f"https://{AWS_APIKEYS[self.gigya_region]['gigyaRegion']}/accounts.login"
        form_data = FormData()
        form_data.add_field("apikey", AWS_APIKEYS[self.gigya_region]["apiKey"])
        form_data.add_field("loginID", self.username)
        form_data.add_field("password", self.password)
        form_data.add_field("targetEnv", "mobile")
        return await self._post_request_with_logging_and_errors_raised(url=url, form_data=form_data)

    async def _gigya_accounts_call(
        self, path: str, reg_token: str, extra_fields: dict[str, str]
    ) -> dict[str, Any]:
        url = f"https://{AWS_APIKEYS[self.gigya_region]['gigyaRegion']}/{path}"
        form_data = FormData()
        form_data.add_field("apikey", AWS_APIKEYS[self.gigya_region]["apiKey"])
        form_data.add_field("regToken", reg_token)
        for key, value in extra_fields.items():
            form_data.add_field(key, value)
        response: ClientResponse = await self._post_request_with_logging_and_errors_raised(
            url=url, form_data=form_data
        )
        response_json: dict[str, Any] = await response.json(content_type="text/javascript")
        if response_json.get("errorCode", 0) != 0:
            raise LoginError(
                f"{path} failed: {response_json.get('errorCode')} "
                f"{response_json.get('errorMessage')}: "
                f"{response_json.get('errorDetails')}"
            )
        return response_json

    async def _complete_pending_registration(self, login_json: dict[str, Any]) -> None:
        """Finish a Gigya registration that login refused with 206001.

        Gigya returns errorCode 206001 ("Account Pending Registration") with a
        ``regToken`` when the account is missing fields its schema marks as
        required.  Blueair started requiring profile field ``name`` on
        2026-09-22, so accounts created before then could no longer log in.
        The native Blueair app completes this silently; we do the same using
        the name already present in the profile.
        """
        reg_token = login_json.get("regToken")
        profile = login_json.get("profile") or {}
        name = " ".join(
            part for part in (profile.get("firstName"), profile.get("lastName")) if part
        ).strip()
        if not reg_token or not name:
            raise LoginError(
                "Blueair account pending registration (Gigya 206001) and no "
                "profile name available to complete it with. Set a name for "
                "your account in the Blueair app and try again."
            )
        _LOGGER.info(
            "Blueair account is pending registration (Gigya 206001); "
            "completing it with profile name %r",
            name,
        )
        await self._gigya_accounts_call(
            "accounts.setAccountInfo",
            reg_token,
            {"profile": json.dumps({"name": name})},
        )
        await self._gigya_accounts_call("accounts.finalizeRegistration", reg_token, {})

    async def refresh_session(self) -> None:
        """Log in via Gigya and store the resulting session token/secret."""
        _LOGGER.debug("refresh_session")
        response: ClientResponse = await self._accounts_login()
        response_json = await response.json(content_type="text/javascript")
        if response_json.get("errorCode") == GIGYA_ERROR_CODE_PENDING_REGISTRATION:
            await self._complete_pending_registration(response_json)
            response = await self._accounts_login()
            response_json = await response.json(content_type="text/javascript")
        self.session_token = response_json["sessionInfo"]["sessionToken"]
        self.session_secret = response_json["sessionInfo"]["sessionSecret"]

    async def refresh_jwt(self) -> None:
        """Exchange the Gigya session for a short-lived JWT."""
        _LOGGER.debug("refresh_jwt")
        if self.session_token is None or self.session_secret is None:
            await self.refresh_session()
        url = f"https://{AWS_APIKEYS[self.gigya_region]['gigyaRegion']}/accounts.getJWT"
        form_data = FormData()
        form_data.add_field("oauth_token", self.session_token)
        form_data.add_field("secret", self.session_secret)
        form_data.add_field("targetEnv", "mobile")
        response: ClientResponse = await self._post_request_with_logging_and_errors_raised(
            url=url, form_data=form_data
        )
        response_json = await response.json(content_type="text/javascript")
        self.jwt = response_json["id_token"]

    async def refresh_access_token(self) -> None:
        """Re-authenticate from scratch and store the new BlueCloud access token.

        Serialized with every other re-authentication by this client, so a
        call made while another refresh is running waits for it first.
        """
        async with self._auth_lock:
            await self._refresh_access_token_unlocked()

    def _access_token_is_usable(self) -> bool:
        """Return whether the cached access token can be used for a request.

        Returns:
            ``True`` when a token is cached and its refresh time, if known,
            has not been reached.
        """
        if self.access_token is None:
            return False
        refresh_at = self.access_token_refresh_at
        return refresh_at is None or datetime.now(UTC) < refresh_at

    def _clear_auth_state(self) -> None:
        """Forget every cached credential so the next request logs in again."""
        self.session_token = None
        self.session_secret = None
        self.access_token = None
        self.access_token_refresh_at = None
        self.user_id = None
        self.mqtt_auth_name = None
        self.mqtt_auth_signature = None
        self.mqtt_auth_token = None
        self.jwt = None

    async def _discard_rejected_session(self, rejected_access_token: str | None) -> None:
        """Clear cached credentials after the API rejected ``rejected_access_token``.

        If another request has already replaced that token, the newer one is
        kept. When the rejected request had no token cached when it started,
        the state is cleared unconditionally, as before this check existed.

        Args:
            rejected_access_token: Access token cached when the rejected
                request started.
        """
        async with self._auth_lock:
            if rejected_access_token is None or self.access_token == rejected_access_token:
                self._clear_auth_state()
            else:
                _LOGGER.debug("access token already replaced by a concurrent refresh")

    async def _refresh_access_token_unlocked(self) -> None:
        """Re-authenticate and store new tokens; the caller holds ``_auth_lock``."""
        _LOGGER.debug("refresh_access_token")
        # Always do a full re-authentication from scratch.
        # The JWT from Gigya has a very short lifetime (~5 minutes) and cannot
        # be reused.  Previously we skipped refresh_jwt() when self.jwt was
        # still set, which caused MQTT credential refreshes to send an expired
        # JWT and get stuck in a 401 loop.
        self.session_token = None
        self.session_secret = None
        self.jwt = None
        await self.refresh_jwt()
        url = f"https://{AWS_APIKEYS[self.cloud_region]['restApiId']}.execute-api.{AWS_APIKEYS[self.cloud_region]['awsRegion']}/prod/c/login"
        headers = {"idtoken": self.jwt, "authorization": f"Bearer {self.jwt}"}
        response: ClientResponse = await self._post_request_with_logging_and_errors_raised(
            url=url, headers=headers
        )
        response_json = await response.json()
        self.access_token = response_json["access_token"]
        # MQTT auth credentials from the same login response.
        self.mqtt_auth_name = response_json.get("ba_X-Amz-CustomAuthorizer-Name")
        self.mqtt_auth_signature = response_json.get("ba_X-Amz-CustomAuthorizer-Signature")
        self.mqtt_auth_token = response_json.get("ba_X-Amz-CustomAuthorizer-Token")
        if self.mqtt_auth_name and self.mqtt_auth_signature and self.mqtt_auth_token:
            _LOGGER.debug("refresh_access_token: obtained access token and MQTT credentials")
        else:
            _LOGGER.warning(
                "refresh_access_token: MQTT credentials missing from login response; "
                "MQTT real-time updates will not be available"
            )
        # Extract the username claim from the JWT to use as userId in API paths
        claims: dict[str, Any] = {}
        try:
            if self.access_token is None:
                raise ValueError("no access_token to extract user_id from")
            payload = self.access_token.split(".")[1]
            # Add padding if needed
            payload += "=" * (4 - len(payload) % 4)
            claims = json.loads(base64.urlsafe_b64decode(payload))
            self.user_id = claims.get("username", "")
            _LOGGER.debug("Extracted user_id from JWT: %s", self.user_id)
        except (IndexError, ValueError) as e:
            _LOGGER.warning("Failed to extract user_id from access_token JWT: %s", e)
            self.user_id = None
        self.access_token_refresh_at = _refresh_time_from_claims(claims)

    async def get_user_id(self) -> str:
        """Return the cached user ID, refreshing the access token if needed.

        Concurrent callers share one refresh.

        Returns:
            The user ID from the access token's ``username`` claim.

        Raises:
            SessionError: If no user ID is available after refreshing.
        """
        if self.user_id is None:
            async with self._auth_lock:
                if self.user_id is None:
                    await self._refresh_access_token_unlocked()
        if self.user_id is None:
            raise SessionError("user_id was not available after refresh_access_token")
        return self.user_id

    async def get_access_token(self) -> str:
        """Return the cached access token, refreshing it if needed.

        The token is refreshed when missing or close to its ``exp`` claim.
        Concurrent callers share one refresh.

        Returns:
            A BlueCloud access token.

        Raises:
            SessionError: If no access token is available after refreshing.
        """
        _LOGGER.debug("get_access_token")
        if not self._access_token_is_usable():
            async with self._auth_lock:
                if not self._access_token_is_usable():
                    await self._refresh_access_token_unlocked()
        if self.access_token is None:
            raise SessionError("access_token was not available after refresh_access_token")
        return self.access_token

    @request_with_active_session
    async def devices(self) -> dict[str, Any]:
        """Fetch the list of devices registered to the account."""
        _LOGGER.debug("devices")
        url = f"https://{AWS_APIKEYS[self.cloud_region]['restApiId']}.execute-api.{AWS_APIKEYS[self.cloud_region]['awsRegion']}/prod/c/registered-devices"
        headers = {
            "Authorization": f"Bearer {await self.get_access_token()}",
        }
        response: ClientResponse = await self._get_request_with_logging_and_errors_raised(
            url=url, headers=headers
        )
        response_json = await response.json()
        devices: dict[str, Any] = response_json["devices"]
        return devices

    @request_with_active_session
    async def device_sensors(
        self,
        device_name: str,
        device_uuid: str,
        duration: timedelta = timedelta(hours=10),
    ) -> Any:
        """Fetch historical sensor telemetry for a device over ``duration``."""
        user_id = await self.get_user_id()
        url = (
            f"https://{AWS_APIKEYS[self.cloud_region]['restApiId']}.execute-api."
            f"{AWS_APIKEYS[self.cloud_region]['awsRegion']}"
            f"/prod/c/{user_id}/r/telemetry/5m/historical"
        )
        headers = {
            "Authorization": f"Bearer {await self.get_access_token()}",
        }
        params = {
            "did": device_uuid,
            "from": int((datetime.now(UTC) - duration).timestamp()),
            "to": int(datetime.now(UTC).timestamp()),
            "s": ["pm1", "pm2_5", "pm10", "tVOC", "hcho", "h", "t", "fsp0"],
        }
        response: ClientResponse = await self._get_request_with_logging_and_errors_raised(
            url=url, headers=headers, params=params
        )
        return await response.json()

    @request_with_active_session
    async def device_info(self, device_name: str, device_uuid: str) -> dict[str, Any]:
        """Fetch the latest cached info (including states) for a device."""
        _LOGGER.debug("device_info")
        user_id = await self.get_user_id()
        url = f"https://{AWS_APIKEYS[self.cloud_region]['restApiId']}.execute-api.{AWS_APIKEYS[self.cloud_region]['awsRegion']}/prod/c/{user_id}/r/initial"
        headers = {
            "Authorization": f"Bearer {await self.get_access_token()}",
        }
        json_body = {
            "deviceconfigquery": [
                {
                    "id": device_uuid,
                    "r": {
                        "r": [
                            "sensors",
                        ],
                    },
                },
            ],
            "includestates": True,
        }
        response: ClientResponse = await self._post_request_with_logging_and_errors_raised(
            url=url, headers=headers, json_body=json_body
        )
        response_json = await response.json()
        device_info: dict[str, Any] = response_json["deviceInfo"][0]
        return device_info

    @request_with_active_session
    async def set_device_info(
        self,
        device_uuid: str,
        service_name: str,
        action_verb: str,
        action_value: Any,
    ) -> bool:
        """Write a single device attribute and return whether it succeeded."""
        _LOGGER.debug("set_device_info")
        url = f"https://{AWS_APIKEYS[self.cloud_region]['restApiId']}.execute-api.{AWS_APIKEYS[self.cloud_region]['awsRegion']}/prod/c/{device_uuid}/a/{service_name}"
        headers = {
            "Authorization": f"Bearer {await self.get_access_token()}",
        }
        json_body = {"n": service_name, action_verb: action_value}
        response: ClientResponse = await self._post_request_with_logging_and_errors_raised(
            url=url, headers=headers, json_body=json_body
        )
        response_text = await response.text()
        return response_text == "Success"

    async def discover_cloud_region(
        self,
        *,
        candidates: Iterable[str] | None = None,
        per_candidate_timeout: float = 5.0,
    ) -> CloudRegionScan:
        """Probe candidate BlueCloud regions and return a recommendation.

        Thin wrapper around :func:`blueair_api.region_discovery.discover_cloud_region`
        so callers can do ``await api.discover_cloud_region()``.  Read-only
        with respect to client state; see the free function's docstring
        for the full contract.
        """
        # Local import to avoid a circular dependency at module load
        # time (region_discovery imports HttpAwsBlueair for type hints).
        from .region_discovery import discover_cloud_region  # noqa: PLC0415

        return await discover_cloud_region(
            self,
            candidates=candidates,
            per_candidate_timeout=per_candidate_timeout,
        )

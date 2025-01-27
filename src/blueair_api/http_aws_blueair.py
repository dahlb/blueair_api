import functools

from logging import getLogger
from typing import Any
from aiohttp import ClientSession, ClientResponse, FormData

from .const import AWS_APIKEYS
from .util_http import request_with_logging
from .errors import SessionError, LoginError

_LOGGER = getLogger(__name__)


def request_with_active_session(func):
    @functools.wraps(func)
    async def request_with_active_session_wrapper(*args, **kwargs) -> ClientResponse:
        _LOGGER.debug("session")
        try:
            return await func(*args, **kwargs)
        except SessionError:
            _LOGGER.debug("got invalid session, attempting to repair and resend")
            self = args[0]
            self.session_token = None
            self.session_secret = None
            self.access_token = None
            self.jwt = None
            response = await func(*args, **kwargs)
            return response

    return request_with_active_session_wrapper


def request_with_errors(func):
    @functools.wraps(func)
    async def request_with_errors_wrapper(*args, **kwargs) -> ClientResponse:
        _LOGGER.debug("checking for errors")
        response: ClientResponse = await func(*args, **kwargs)
        status_code = response.status
        try:
            response_json = await response.json(content_type=None)
            if "statusCode" in response_json:
                _LOGGER.debug("response json found, checking status code from response")
                status_code = response_json["statusCode"]
        except Exception as e:
            _LOGGER.error(f"Error parsing response for errors {e}")
            raise e
        if status_code == 200:
            _LOGGER.debug("response 200")
            return response
        if 400 <= status_code <= 500:
            _LOGGER.debug("auth error")
            url = kwargs["url"]
            response_text = await response.text()
            if "accounts.login" in url:
                _LOGGER.debug("login error")
                raise LoginError(response_text)
            else:
                _LOGGER.debug("session error")
                raise SessionError(response_text)
        raise ValueError(f"unknown status code {status_code}")

    return request_with_errors_wrapper


class HttpAwsBlueair:
    def __init__(
        self,
        username: str,
        password: str,
        region: str = "us",
        client_session: ClientSession | None = None,
    ):
        self.username = username
        self.password = password
        self.region = region

        self.session_token = None
        self.session_secret = None

        self.access_token = None

        self.jwt = None

        if client_session is None:
            self.api_session = ClientSession(raise_for_status=False)
        else:
            self.api_session = client_session

    async def cleanup_client_session(self):
        await self.api_session.close()

    @request_with_errors
    @request_with_logging
    async def _get_request_with_logging_and_errors_raised(
        self, url: str, headers: dict | None = None
    ) -> ClientResponse:
        return await self.api_session.get(url=url, headers=headers)

    @request_with_errors
    @request_with_logging
    async def _post_request_with_logging_and_errors_raised(
        self,
        url: str,
        json_body: dict | None = None,
        form_data: FormData | None = None,
        headers: dict | None = None,
    ) -> ClientResponse:
        return await self.api_session.post(
            url=url, data=form_data, json=json_body, headers=headers
        )

    async def refresh_session(self) -> None:
        _LOGGER.debug("refresh_session")
        url = f"https://accounts.{AWS_APIKEYS[self.region]['gigyaRegion']}.gigya.com/accounts.login"
        form_data = FormData()
        form_data.add_field("apikey", AWS_APIKEYS[self.region]["apiKey"])
        form_data.add_field("loginID", self.username)
        form_data.add_field("password", self.password)
        form_data.add_field("targetEnv", "mobile")
        response: ClientResponse = (
            await self._post_request_with_logging_and_errors_raised(
                url=url, form_data=form_data
            )
        )
        response_json = await response.json(content_type="text/javascript")
        self.session_token = response_json["sessionInfo"]["sessionToken"]
        self.session_secret = response_json["sessionInfo"]["sessionSecret"]

    async def refresh_jwt(self) -> None:
        _LOGGER.debug("refresh_jwt")
        if self.session_token is None or self.session_secret is None:
            await self.refresh_session()
        url = f"https://accounts.{AWS_APIKEYS[self.region]['gigyaRegion']}.gigya.com/accounts.getJWT"
        form_data = FormData()
        form_data.add_field("oauth_token", self.session_token)
        form_data.add_field("secret", self.session_secret)
        form_data.add_field("targetEnv", "mobile")
        response: ClientResponse = (
            await self._post_request_with_logging_and_errors_raised(
                url=url, form_data=form_data
            )
        )
        response_json = await response.json(content_type="text/javascript")
        self.jwt = response_json["id_token"]

    async def refresh_access_token(self) -> None:
        _LOGGER.debug("refresh_access_token")
        if self.jwt is None:
            await self.refresh_jwt()
        url = f"https://{AWS_APIKEYS[self.region]['restApiId']}.execute-api.{AWS_APIKEYS[self.region]['awsRegion']}.amazonaws.com/prod/c/login"
        headers = {"idtoken": self.jwt}
        response: ClientResponse = (
            await self._post_request_with_logging_and_errors_raised(
                url=url, headers=headers
            )
        )
        response_json = await response.json()
        self.access_token = response_json["access_token"]

    async def get_access_token(self) -> str:
        _LOGGER.debug("get_access_token")
        if self.access_token is None:
            await self.refresh_access_token()
        assert self.access_token is not None
        return self.access_token

    @request_with_active_session
    async def devices(self) -> dict[str, Any]:
        _LOGGER.debug("devices")
        url = f"https://{AWS_APIKEYS[self.region]['restApiId']}.execute-api.{AWS_APIKEYS[self.region]['awsRegion']}.amazonaws.com/prod/c/registered-devices"
        headers = {
            "Authorization": f"Bearer {await self.get_access_token()}",
        }
        response: ClientResponse = (
            await self._get_request_with_logging_and_errors_raised(
                url=url, headers=headers
            )
        )
        response_json = await response.json()
        return response_json["devices"]

    @request_with_active_session
    async def device_info(self, device_name, device_uuid) -> dict[str, Any]:
        _LOGGER.debug("device_info")
        url = f"https://{AWS_APIKEYS[self.region]['restApiId']}.execute-api.{AWS_APIKEYS[self.region]['awsRegion']}.amazonaws.com/prod/c/{device_name}/r/initial"
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
            "includestates": True
        }
        response: ClientResponse = (
            await self._post_request_with_logging_and_errors_raised(
                url=url, headers=headers, json_body=json_body
            )
        )
        response_json = await response.json()
        return response_json["deviceInfo"][0]

    @request_with_active_session
    async def set_device_info(
        self, device_uuid, service_name, action_verb, action_value
    ) -> bool:
        _LOGGER.debug("set_device_info")
        url = f"https://{AWS_APIKEYS[self.region]['restApiId']}.execute-api.{AWS_APIKEYS[self.region]['awsRegion']}.amazonaws.com/prod/c/{device_uuid}/a/{service_name}"
        headers = {
            "Authorization": f"Bearer {await self.get_access_token()}",
        }
        json_body = {"n": service_name, action_verb: action_value}
        response: ClientResponse = (
            await self._post_request_with_logging_and_errors_raised(
                url=url, headers=headers, json_body=json_body
            )
        )
        response_text = await response.text()
        return response_text == "Success"

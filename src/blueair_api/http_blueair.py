import logging

from aiohttp import ClientSession, ClientResponse
import base64

from .util_http import request_with_logging
from .const import API_KEY
from .errors import AuthError

_LOGGER = logging.getLogger(__name__)


class HttpBlueair:
    def __init__(
        self,
        username: str,
        password: str,
        home_host: str = None,
        auth_token: str = None,
        client_session: ClientSession = None,
    ):
        self.username = username
        self.password = password
        self.home_host = home_host
        self.auth_token = auth_token

        if client_session is None:
            self.api_session = ClientSession(raise_for_status=False)
        else:
            self.api_session = client_session

    async def cleanup_client_session(self):
        await self.api_session.close()

    async def get_home_host(self):
        if self.home_host is None:
            self.home_host = await self._get_home_host()
        return self.home_host

    async def get_auth_token(self):
        if self.auth_token is None:
            self.auth_token = await self._get_auth_token()
        return self.auth_token

    @request_with_logging
    async def _get_request_with_logging_and_errors_raised(
        self, url: str, headers: dict = None
    ) -> ClientResponse:
        return await self.api_session.get(url=url, headers=headers)

    @request_with_logging
    async def _post_request_with_logging_and_errors_raised(
        self, url: str, json_body: dict, headers: dict = None
    ) -> ClientResponse:
        return await self.api_session.post(url=url, json=json_body, headers=headers)

    async def _get_home_host(self) -> str:
        """
        Retrieve the home host for the current username.

        The home host is the server that is used to interact with the Blueair
        device. It can be stored and reused to avoid requesting it again when
        reinitializing the class at a later time.
        """
        url = f"https://api.blueair.io/v2/user/{self.username}/homehost/"
        headers = {"X-API-KEY-TOKEN": API_KEY}
        response: ClientResponse = (
            await self._get_request_with_logging_and_errors_raised(
                url=url, headers=headers
            )
        )
        return (await response.text()).replace('"', "")

    async def _get_auth_token(self) -> str:
        """
        Authenticate the user and retrieve the authentication token.

        The authentication token can be reused to prevent an additional network
        request when initializing the client.
        """
        url = f"https://{self.home_host}/v2/user/{self.username}/login/"
        headers = {
            "X-API-KEY-TOKEN": API_KEY,
            "Authorization": "Basic "
            + base64.b64encode((self.username + ":" + self.password).encode()).decode(),
        }
        response: ClientResponse = (
            await self._get_request_with_logging_and_errors_raised(
                url=url, headers=headers
            )
        )
        result = await response.text()
        if response.status == 404:
            raise AuthError("invalid username")
        if result == "true":
            return response.headers["X-AUTH-TOKEN"]
        else:
            raise AuthError("invalid password")

    async def get_devices(self) -> list[dict[str, any]]:
        """
        Fetch a list of devices.

        Returns a list of dictionaries. Each dictionary will have a UUID key
        (the device identifier), a user ID, MAC address, and device name.

        Example response:

        [{"uuid":"1234567890ABCDEF","userId":12345,"mac":"1234567890AB","name":"My Blueair Device"}]
        """
        url = f"https://{await self.get_home_host()}/v2/owner/{self.username}/device/"
        headers = {
            "X-API-KEY-TOKEN": API_KEY,
            "X-AUTH-TOKEN": await self.get_auth_token(),
        }
        response: ClientResponse = (
            await self._get_request_with_logging_and_errors_raised(
                url=url, headers=headers
            )
        )
        return await response.json()

    # Note: refreshes every 5 minutes
    async def get_attributes(self, device_uuid: str) -> dict[str, any]:
        """
        Fetch a list of attributes for the provided device ID.

        The return value is a dictionary containing key-value pairs for any
        available attributes.

        Note: the data for this API call is only updated once every 5 minutes.
        Calling it more often will return the same respone from the server and
        should be avoided to limit server load.
        """
        url = (
            f"https://{await self.get_home_host()}/v2/device/{device_uuid}/attributes/"
        )
        headers = {
            "X-API-KEY-TOKEN": API_KEY,
            "X-AUTH-TOKEN": await self.get_auth_token(),
        }
        response: ClientResponse = (
            await self._get_request_with_logging_and_errors_raised(
                url=url, headers=headers
            )
        )
        raw_attributes = await response.json()
        attributes = {}
        for item in raw_attributes:
            attributes[item["name"]] = item["currentValue"]

        return attributes

    # Note: refreshes every 5 minutes, timestamps are in seconds
    async def get_info(self, device_uuid: str) -> dict[str, any]:
        """
        Fetch device information for the provided device ID.

        The return value is a dictionary containing key-value pairs for the
        available device information.

        Note: the data for this API call is only updated once every 5 minutes.
        Calling it more often will return the same respone from the server and
        should be avoided to limit server load.
        """
        url = f"https://{await self.get_home_host()}/v2/device/{device_uuid}/info/"
        headers = {
            "X-API-KEY-TOKEN": API_KEY,
            "X-AUTH-TOKEN": await self.get_auth_token(),
        }
        response: ClientResponse = (
            await self._get_request_with_logging_and_errors_raised(
                url=url, headers=headers
            )
        )
        return await response.json()

    async def set_fan_speed(self, device_uuid, new_speed: str):
        """
        Set the fan speed per @spikeyGG comment at https://community.home-assistant.io/t/blueair-purifier-addon/154456/14
        """
        if new_speed == "auto":
            new_name = "mode"
        elif new_speed in ["0", "1", "2", "3"]:
            new_name = "fan_speed"
        else:
            raise Exception("Speed not supported")
        url = f"https://{await self.get_home_host()}/v2/device/{device_uuid}/attribute/fanspeed/"
        headers = {
            "X-API-KEY-TOKEN": API_KEY,
            "X-AUTH-TOKEN": await self.get_auth_token(),
        }
        json_body = {
            "currentValue": new_speed,
            "scope": "device",
            "defaultValue": new_speed,
            "name": new_name,
            "uuid": str(device_uuid),
        }
        response: ClientResponse = (
            await self._post_request_with_logging_and_errors_raised(
                url=url, json_body=json_body, headers=headers
            )
        )
        return await response.json()

import logging

from aiohttp import ClientSession

from .http_blueair import HttpBlueair
from .http_aws_blueair import HttpAwsBlueair
from .device import Device
from .device_aws import DeviceAws

_LOGGER = logging.getLogger(__name__)


async def get_devices(
    username: str,
    password: str,
    home_host: str = None,
    auth_token: str = None,
    client_session: ClientSession = None,
) -> (HttpBlueair, list[Device]):
    api = HttpBlueair(
        client_session=client_session,
        username=username,
        password=password,
        home_host=home_host,
        auth_token=auth_token,
    )
    api_devices = await api.get_devices()

    def create_device(device):
        return Device(
            api=api,
            uuid=device["uuid"],
            name=device["name"],
            mac=device["mac"],
        )

    devices = map(create_device, api_devices)
    return (
        api,
        list(devices),
    )


async def get_aws_devices(
        username: str,
        password: str,
        region: str = "us",
        client_session: ClientSession = None,
) -> (HttpBlueair, list[Device]):
    api = HttpAwsBlueair(username=username, password=password, region=region, client_session=client_session)
    api_devices = await api.devices()

    def create_device(device):
        return DeviceAws(
            api=api,
            uuid=device["uuid"],
            name_api=device["name"],
            mac=device["mac"],
        )

    devices = map(create_device, api_devices)
    return (
        api,
        list(devices)
    )

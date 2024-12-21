import logging

from aiohttp import ClientSession

from .http_blueair import HttpBlueair
from .http_aws_blueair import HttpAwsBlueair
from .device import Device
from .device_aws import DeviceAws
from typing import Optional

_LOGGER = logging.getLogger(__name__)


async def get_devices(
    username: str,
    password: str,
    home_host: str | None = None,
    auth_token: str | None = None,
    client_session: ClientSession | None = None,
) -> tuple[HttpBlueair, list[Device]]:
    api = HttpBlueair(
        client_session=client_session,
        username=username,
        password=password,
        home_host=home_host,
        auth_token=auth_token,
    )
    api_devices = await api.get_devices()
    devices = []
    for api_device in api_devices:
        devices.append(await Device.create_device(
            api=api,
            uuid=api_device["uuid"],
            name=api_device["name"],
            mac=api_device["mac"]
        ))
    return (
        api,
        devices,
    )


async def get_aws_devices(
    username: str,
    password: str,
    region: str = "us",
    client_session: ClientSession | None = None,
) -> tuple[HttpAwsBlueair, list[DeviceAws]]:
    api = HttpAwsBlueair(
        username=username,
        password=password,
        region=region,
        client_session=client_session,
    )
    api_devices = await api.devices()
    devices = []
    for api_device in api_devices:
        _LOGGER.debug("api_device: %s", api_device)
        devices.append(await DeviceAws.create_device(
            api=api,
            uuid=api_device["uuid"],
            name=api_device["name"],
            mac=api_device["mac"],
            type_name=api_device["type"]
        ))
    return (
        api,
        devices
    )

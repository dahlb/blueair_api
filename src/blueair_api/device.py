from typing import Any

from .callbacks import CallbacksMixin
from .http_blueair import HttpBlueair
from .util import transform_data_points, safely_get_json_value, convert_none_to_not_implemented
from dataclasses import dataclass, field
from logging import getLogger

_LOGGER = getLogger(__name__)


@dataclass(slots=True)
class Device(CallbacksMixin):
    @classmethod
    async def create_device(cls, api, uuid, name, mac, refresh=False):
        _LOGGER.debug("UUID:"+uuid)
        info = await api.get_info(uuid)
        device = Device(
            api=api,
            uuid=uuid,
            name=name,
            mac=mac,
            timezone=info["timezone"],
            compatibility=info["compatibility"],
            model=info["model"],
            firmware=info["firmware"],
            mcu_firmware=info["mcuFirmware"],
            wlan_driver=info["wlanDriver"],
            room_location=info["roomLocation"]
        )
        if refresh:
            await device.refresh()
        _LOGGER.debug(f"create_device blueair device: {device}")
        return device

    api: HttpBlueair = field(repr=False)
    raw_info: dict[str, Any] = field(repr=False, init=False)

    uuid: str | None = None
    name: str | None = None
    timezone: str | None = None
    compatibility: str | None = None
    model: str | None = None
    mac: str | None = None
    firmware: str | None = None
    mcu_firmware: str | None = None
    wlan_driver: str | None = None
    room_location: str | None = None

    brightness: int | None = None
    child_lock: bool | None = None
    night_mode: bool | None = None
    fan_speed: int | None = None
    fan_auto_mode: bool | None = None
    filter_expired: bool | None = None
    wifi_working: bool | None = None

    pm1: int | None = NotImplemented
    pm10: int | None = NotImplemented
    pm25: int | None = NotImplemented
    voc: int | None = NotImplemented
    co2: int | None = NotImplemented
    temperature: float | None = NotImplemented
    humidity: float | None = NotImplemented
    all_pollution: float | None = NotImplemented

    async def refresh(self):
        _LOGGER.debug("Requesting current attributes...")
        self.raw_info = {}
        attributes = await self.api.get_attributes(self.uuid)
        self.raw_info["attributes"] = attributes
        _LOGGER.debug(f"result: {attributes}")
        if "brightness" in attributes:
            self.brightness = int(attributes["brightness"])
        else:
            self.brightness = NotImplemented
        if "child_lock" in attributes:
            self.child_lock = attributes["child_lock"] == "1"
        else:
            self.child_lock = NotImplemented
        if "night_mode" in attributes:
            self.night_mode = attributes["night_mode"] == "1"
        else:
            self.night_mode = NotImplemented
        if "fan_speed" in attributes:
            self.fan_speed = int(attributes["fan_speed"])
        else:
            self.fan_speed = NotImplemented
        if "filter_status" in attributes:
            self.filter_expired = attributes["filter_status"] != "OK"
        else:
            self.filter_expired = NotImplemented
        if "mode" in attributes:
            self.fan_auto_mode = attributes["mode"] == "auto"
        else:
            self.fan_auto_mode = NotImplemented
        if "wifi_status" in attributes:
            self.wifi_working = attributes["wifi_status"] == "1"
        else:
            self.wifi_working = False
        if self.compatibility != "sense+":
            datapoints = transform_data_points(await self.api.get_data_points_since(self.uuid))
            self.raw_info["datapoints"] = datapoints
            for data_point in datapoints:
                _LOGGER.debug(data_point)
                self.pm25 = convert_none_to_not_implemented(safely_get_json_value(data_point, "pm25", int))
                self.pm10 = convert_none_to_not_implemented(safely_get_json_value(data_point, "pm10", int))
                self.pm1 = convert_none_to_not_implemented(safely_get_json_value(data_point, "pm1", int))
                self.voc = convert_none_to_not_implemented(safely_get_json_value(data_point, "voc", int))
                self.co2 = convert_none_to_not_implemented(safely_get_json_value(data_point, "co2", int))
                self.temperature = convert_none_to_not_implemented(safely_get_json_value(data_point, "temperature", int))
                self.humidity = convert_none_to_not_implemented(safely_get_json_value(data_point, "humidity", int))
                self.all_pollution = convert_none_to_not_implemented(safely_get_json_value(data_point, "all_pollution", int))
        _LOGGER.debug(f"refreshed blueair device: {self}")
        self.publish_updates()

    async def set_fan_speed(self, new_speed: str):
        self.fan_speed = int(new_speed)
        await self.api.set_fan_speed(self.uuid, new_speed)
        self.publish_updates()

    async def set_brightness(self, new_brightness: int):
        self.brightness = new_brightness
        await self.api.set_brightness(self.uuid, new_brightness)
        self.publish_updates()

    async def set_child_lock(self, enabled: bool):
        self.child_lock = enabled
        await self.api.set_child_lock(self.uuid, enabled)
        self.publish_updates()

    async def set_fan_auto_mode(self, fan_auto_mode: bool):
        self.fan_auto_mode = fan_auto_mode
        await self.api.set_fan_auto_mode(self.uuid, fan_auto_mode)
        self.publish_updates()


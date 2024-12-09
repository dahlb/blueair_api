import dataclasses
import logging

from .callbacks import CallbacksMixin
from .http_aws_blueair import HttpAwsBlueair
from .model_enum import ModelEnum
from .util import convert_api_array_to_dict, safely_get_json_value

_LOGGER = logging.getLogger(__name__)


@dataclasses.dataclass(slots=True)
class DeviceAws(CallbacksMixin):
    @classmethod
    async def create_device(cls, api, uuid, name, mac, type_name, refresh=False):
        _LOGGER.debug("UUID:"+uuid)
        device_aws = DeviceAws(
            api=api,
            uuid=uuid,
            name_api=name,
            mac=mac,
            type_name=type_name,
        )
        if refresh:
            await device_aws.refresh()
        _LOGGER.debug(f"create_device blueair device_aws: {device_aws}")
        return device_aws

    api: HttpAwsBlueair
    uuid: str = None
    name: str = None
    name_api: str = None
    mac: str = None
    type_name: str = None

    sku: str = None
    firmware: str = None
    mcu_firmware: str = None
    serial_number: str = None

    brightness: int = None
    child_lock: bool = None
    fan_speed: int = None
    fan_auto_mode: bool = None
    running: bool = None
    night_mode: bool = None
    germ_shield: bool = None

    pm1: int = None
    pm2_5: int = None
    pm10: int = None
    tVOC: int = None
    temperature: int = None
    humidity: int = None
    filter_usage: int = None  # percentage
    wifi_working: bool = None

    # i35
    wick_usage: int = None  # percentage
    wick_dry_mode: bool = None
    water_shortage: bool = None
    auto_regulated_humidity: int = None

    async def refresh(self):
        _LOGGER.debug(f"refreshing blueair device aws: {self}")
        info = await self.api.device_info(self.name_api, self.uuid)
        sensor_data = convert_api_array_to_dict(info["sensordata"])
        self.pm1 = safely_get_json_value(sensor_data, "pm1", int)
        self.pm2_5 = safely_get_json_value(sensor_data, "pm2_5", int)
        self.pm10 = safely_get_json_value(sensor_data, "pm10", int)
        self.tVOC = safely_get_json_value(sensor_data, "tVOC", int)
        self.temperature = safely_get_json_value(sensor_data, "t", int)
        self.humidity = safely_get_json_value(sensor_data, "h", int)

        self.name = safely_get_json_value(info, "configuration.di.name")
        self.firmware = safely_get_json_value(info, "configuration.di.cfv")
        self.mcu_firmware = safely_get_json_value(info, "configuration.di.mfv")
        self.serial_number = safely_get_json_value(info, "configuration.di.ds")
        self.sku = safely_get_json_value(info, "configuration.di.sku")

        states = convert_api_array_to_dict(info["states"])
        self.running = safely_get_json_value(states, "standby") is False
        self.night_mode = safely_get_json_value(states, "nightmode", bool)
        self.germ_shield = safely_get_json_value(states, "germshield", bool)
        self.brightness = safely_get_json_value(states, "brightness", int)
        self.child_lock = safely_get_json_value(states, "childlock", bool)
        self.fan_speed = safely_get_json_value(states, "fanspeed", int)
        self.fan_auto_mode = safely_get_json_value(states, "automode", bool)
        self.filter_usage = safely_get_json_value(states, "filterusage", int)
        self.wifi_working = safely_get_json_value(states, "online", bool)
        self.wick_usage = safely_get_json_value(states, "wickusage", int)
        self.wick_dry_mode = safely_get_json_value(states, "wickdrys", bool)
        self.auto_regulated_humidity = safely_get_json_value(states, "autorh", int)
        self.water_shortage = safely_get_json_value(states, "wshortage", bool)

        self.publish_updates()
        _LOGGER.debug(f"refreshed blueair device aws: {self}")

    async def set_brightness(self, value: int):
        self.brightness = value
        await self.api.set_device_info(self.uuid, "brightness", "v", value)
        self.publish_updates()

    async def set_fan_speed(self, value: int):
        self.fan_speed = value
        await self.api.set_device_info(self.uuid, "fanspeed", "v", value)
        self.publish_updates()

    async def set_running(self, running: bool):
        self.running = running
        await self.api.set_device_info(self.uuid, "standby", "vb", not running)
        self.publish_updates()

    async def set_fan_auto_mode(self, fan_auto_mode: bool):
        self.fan_auto_mode = fan_auto_mode
        await self.api.set_device_info(self.uuid, "automode", "vb", fan_auto_mode)
        self.publish_updates()

    async def set_auto_regulated_humidity(self, value: int):
        self.auto_regulated_humidity = value
        await self.api.set_device_info(self.uuid, "autorh", "v", value)
        self.publish_updates()

    async def set_child_lock(self, child_lock: bool):
        self.child_lock = child_lock
        await self.api.set_device_info(self.uuid, "childlock", "vb", child_lock)
        self.publish_updates()

    async def set_night_mode(self, night_mode: bool):
        self.night_mode = night_mode
        await self.api.set_device_info(self.uuid, "nightmode", "vb", night_mode)
        self.publish_updates()

    async def set_wick_dry_mode(self, value: bool):
        self.wick_dry_mode = value
        await self.api.set_device_info(self.uuid, "wickdrys", "vb", value)
        self.publish_updates()

    @property
    def model(self) -> ModelEnum:
        if self.sku == "111633":
            return ModelEnum.HUMIDIFIER_H35I
        if self.sku == "105820":
            return ModelEnum.PROTECT_7440I
        if self.sku == "105826":
            return ModelEnum.PROTECT_7470I
        if self.sku == "110059":
            return ModelEnum.MAX_211I
        if self.sku == "110092":
            return ModelEnum.MAX_311I
        if self.sku == "110057":
            return ModelEnum.MAX_411I
        if self.sku == "112124":
            return ModelEnum.T10I
        return ModelEnum.UNKNOWN


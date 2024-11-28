import logging

from .callbacks import CallbacksMixin
from .http_aws_blueair import HttpAwsBlueair
from .model_enum import ModelEnum
from .util import convert_api_array_to_dict, safely_get_json_value

_LOGGER = logging.getLogger(__name__)


class DeviceAws(CallbacksMixin):
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

    def __init__(
        self,
        api: HttpAwsBlueair,
        uuid: str = None,
        name_api: str = None,
        mac: str = None,
        type_name: str = None,
    ):
        self.api = api
        self.uuid = uuid
        self.name_api = name_api
        self.mac = mac
        self.type_name = type_name
        _LOGGER.debug(f"creating blueair device aws: {self.uuid}")

    async def refresh(self):
        _LOGGER.debug(f"refreshing blueair device aws: {self.uuid}")
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
            return ModelEnum.HUMIDIFIER_I35
        if self.sku == "105826":
            return ModelEnum.PROTECT_7470I
        return ModelEnum.UNKNOWN

    def __repr__(self):
        return {
            "uuid": self.uuid,
            "name": self.name,
            "type_name": self.type_name,
            "sku": self.sku,
            "name_api": self.name_api,
            "mac": self.mac,
            "firmware": self.firmware,
            "mcu_firmware": self.mcu_firmware,
            "serial_number": self.serial_number,
            "brightness": self.brightness,
            "child_lock": self.child_lock,
            "fan_speed": self.fan_speed,
            "fan_auto_mode": self.fan_auto_mode,
            "running": self.running,
            "night_mode": self.night_mode,
            "germ_shield": self.germ_shield,
            "pm1": self.pm1,
            "pm2_5": self.pm2_5,
            "pm10": self.pm10,
            "tVOC": self.tVOC,
            "temperature": self.temperature,
            "humidity": self.humidity,
            "filter_usage": self.filter_usage,
            "wick_usage": self.wick_usage,
            "wick_dry_mode": self.wick_dry_mode,
            "auto_regulated_humidity": self.auto_regulated_humidity,
            "water_shortage": self.water_shortage,
        }

    def __str__(self):
        return f"{self.__repr__()}"

import dataclasses
import logging

from .callbacks import CallbacksMixin
from .http_aws_blueair import HttpAwsBlueair
from .model_enum import ModelEnum
from . import ir_aws as ir

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
    uuid: str | None = None
    name: str | None = None
    name_api: str | None = None
    mac: str | None = None
    type_name: str | None = None

    sku: str | None = None
    firmware: str | None = None
    mcu_firmware: str | None = None
    serial_number: str | None = None

    brightness: int | None = None
    child_lock: bool | None = None
    fan_speed: int | None = None
    fan_auto_mode: bool | None = None
    standby: bool | None = None
    night_mode: bool | None = None
    germ_shield: bool | None = None

    pm1: int | None = None
    pm2_5: int | None = None
    pm10: int | None = None
    tVOC: int | None = None
    temperature: int | None = None
    humidity: int | None = None
    filter_usage: int | None = None  # percentage
    wifi_working: bool | None = None

    # i35
    wick_usage: int | None = None  # percentage
    wick_dry_mode: bool | None = None
    water_shortage: bool | None = None
    auto_regulated_humidity: int | None = None

    async def refresh(self):
        _LOGGER.debug(f"refreshing blueair device aws: {self}")
        info = await self.api.device_info(self.name_api, self.uuid)
        da = ir.parse_json(ir.Attribute, ir.query_json(info, "configuration.da"))
        ds = ir.parse_json(ir.Sensor, ir.query_json(info, "configuration.ds"))
        dc = ir.parse_json(ir.Control, ir.query_json(info, "configuration.dc"))
        sensor_data = ir.SensorPack(info["sensordata"]).to_latest_value()

        self.pm1 = sensor_data.get("pm1")
        self.pm2_5 = sensor_data.get("pm2_5")
        self.pm10 = sensor_data.get("pm10")
        self.tVOC = sensor_data.get("tVOC")
        self.temperature = sensor_data.get("t")
        self.humidity = sensor_data.get("h")

        self.name = ir.query_json(info, "configuration.di.name")
        self.firmware = ir.query_json(info, "configuration.di.cfv")
        self.mcu_firmware = ir.query_json(info, "configuration.di.mfv")
        self.serial_number = ir.query_json(info, "configuration.di.ds")
        self.sku = ir.query_json(info, "configuration.di.sku")

        states = ir.SensorPack(info["states"]).to_latest_value()
        self.standby = states.get("standby")
        self.night_mode = states.get("nightmode")
        self.germ_shield = states.get("germshield")
        self.brightness = states.get("brightness")
        self.child_lock = states.get("childlock")
        self.fan_speed = states.get("fanspeed")
        self.fan_auto_mode = states.get("automode")
        self.filter_usage = states.get("filterusage")
        self.wifi_working = states.get("online")
        self.wick_usage = states.get("wickusage")
        self.wick_dry_mode = states.get("wickdrys")
        self.auto_regulated_humidity = states.get("autorh")
        self.water_shortage = states.get("wshortage")

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

    async def set_standby(self, value: bool):
        self.standby = value
        await self.api.set_device_info(self.uuid, "standby", "vb", value)
        self.publish_updates()

    # FIXME: avoid state translation at the API level and depreate running.
    # replace with standby which is standard across aws devices.
    @property
    def running(self) -> bool | None:
        if self.standby is None:
            return None
        return not self.standby

    async def set_running(self, running: bool):
        await self.set_standby(not running)

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


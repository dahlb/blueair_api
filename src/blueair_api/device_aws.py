from typing import Any

from logging import getLogger
from json import dumps

from .callbacks import CallbacksMixin
from .http_aws_blueair import HttpAwsBlueair
from .model_enum import ModelEnum
from . import intermediate_representation_aws as ir
from dataclasses import dataclass, field

_LOGGER = getLogger(__name__)

type AttributeType[T] = T | None

@dataclass(slots=True)
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

    api: HttpAwsBlueair = field(repr=False)
    raw_info : dict[str, Any] = field(repr=False, init=False)

    uuid : str | None = None
    name : str | None = None
    name_api : str | None = None
    mac : str | None = None
    type_name : str | None = None

    # Attributes are defined below.
    # We mandate that unittests shall test all fields of AttributeType.
    sku : AttributeType[str] = None
    firmware : AttributeType[str] = None
    mcu_firmware : AttributeType[str] = None
    serial_number : AttributeType[str] = None

    brightness : AttributeType[int] = None
    child_lock : AttributeType[bool] = None
    fan_speed : AttributeType[int] = None
    fan_auto_mode : AttributeType[bool] = None
    standby : AttributeType[bool] = None
    night_mode : AttributeType[bool] = None
    germ_shield : AttributeType[bool] = None

    pm1 : AttributeType[int] = None
    pm2_5 : AttributeType[int] = None
    pm10 : AttributeType[int] = None
    tVOC : AttributeType[int] = None
    temperature : AttributeType[int] = None
    humidity : AttributeType[int] = None
    filter_usage_percentage : AttributeType[int] = None
    wifi_working : AttributeType[bool] = None

    wick_usage_percentage : AttributeType[int] = None
    wick_dry_mode : AttributeType[bool] = None
    water_shortage : AttributeType[bool] = None
    auto_regulated_humidity : AttributeType[int] = None

    main_mode: AttributeType[int] = None # api value 0 purify only, 1 heat on, 2 cool on
    heat_sub_mode: AttributeType[int] = None # api value 1 heat on, 2 heat on with fan auto
    heat_fan_speed: AttributeType[int] = None # api value 11/37/64/91
    heat_temp: AttributeType[int] = None # api value is celsius * 10
    cool_sub_mode: AttributeType[int] = None # api value 1 cool on, 2 cool on with fan auto
    cool_fan_speed: AttributeType[int] = None # api value 11/37/64/91
    ap_sub_mode: AttributeType[int] = None # api value 1 manual speeed, 2 auto fan speed
    fan_speed_0: AttributeType[int] = None # api value 11/37/64/91
    temperature_unit: AttributeType[int] = None # api value of 1 is celcius

    async def refresh(self):
        _LOGGER.debug(f"refreshing blueair device aws: {self}")
        self.raw_info = await self.api.device_info(self.name_api, self.uuid)
        _LOGGER.debug(dumps(self.raw_info, indent=2))

        # ir.parse_json(ir.Attribute, ir.query_json(info, "configuration.da"))
        ds = ir.parse_json(ir.Sensor, ir.query_json(self.raw_info, "configuration.ds"))
        dc = ir.parse_json(ir.Control, ir.query_json(self.raw_info, "configuration.dc"))

        sensor_data = ir.SensorPack(self.raw_info["sensordata"]).to_latest_value()

        def sensor_data_safe_get(key):
            return sensor_data.get(key) if key in ds else NotImplemented

        self.pm1 = sensor_data_safe_get("pm1")
        self.pm2_5 = sensor_data_safe_get("pm2_5")
        self.pm10 = sensor_data_safe_get("pm10")
        self.tVOC = sensor_data_safe_get("tVOC")
        self.temperature = sensor_data_safe_get("t")
        self.humidity = sensor_data_safe_get("h")

        def info_safe_get(path):
            # directly reads for the schema. If the schema field is
            # undefined, it is NotImplemented, not merely unavailable.
            value = ir.query_json(self.raw_info, path)
            if value is None:
                return NotImplemented
            return value

        self.name = info_safe_get("configuration.di.name")
        self.firmware = info_safe_get("configuration.di.cfv")
        self.mcu_firmware = info_safe_get("configuration.di.mfv")
        self.serial_number = info_safe_get("configuration.di.ds")
        self.sku = info_safe_get("configuration.di.sku")

        states = ir.SensorPack(self.raw_info["states"]).to_latest_value()

        def states_safe_get(key):
            return states.get(key) if key in dc else NotImplemented

        # "online" is not defined in the schema.
        self.wifi_working = states.get("online")

        self.standby = states_safe_get("standby")
        self.night_mode = states_safe_get("nightmode")
        self.germ_shield = states_safe_get("germshield")
        self.brightness = states_safe_get("brightness")
        self.child_lock = states_safe_get("childlock")
        self.fan_speed = states_safe_get("fanspeed")
        self.fan_auto_mode = states_safe_get("automode")
        self.filter_usage_percentage = states_safe_get("filterusage")

        self.wick_usage_percentage = states_safe_get("wickusage")
        self.wick_dry_mode = states_safe_get("wickdrys")
        self.auto_regulated_humidity = states_safe_get("autorh")
        self.water_shortage = states_safe_get("wshortage")

        self.main_mode = states_safe_get("mainmode")
        self.heat_temp = states_safe_get("heattemp")
        self.heat_sub_mode = states_safe_get("heatsubmode")
        self.heat_fan_speed = states_safe_get("heatfs")
        self.cool_sub_mode = states_safe_get("coolsubmode")
        self.cool_fan_speed = states_safe_get("coolfs")
        self.ap_sub_mode = states_safe_get("apsubmode")
        self.fan_speed_0 = states_safe_get("fsp0")
        self.temperature_unit = states_safe_get("tu")

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

    async def set_germ_shield(self, value: bool):
        self.germ_shield = value
        await self.api.set_device_info(self.uuid, "germshield", "vb", value)
        self.publish_updates()

    async def set_main_mode(self, value: int):
        self.main_mode = value
        await self.api.set_device_info(self.uuid, "mainmode", "v", value)
        self.publish_updates()

    async def set_heat_temp(self, value: int):
        self.heat_temp = value
        await self.api.set_device_info(self.uuid, "heattemp", "v", value)
        self.publish_updates()

    async def set_heat_sub_mode(self, value: int):
        self.heat_sub_mode = value
        await self.api.set_device_info(self.uuid, "heatsubmode", "v", value)
        self.publish_updates()

    async def set_heat_fan_speed(self, value: int):
        self.heat_fan_speed = value
        await self.api.set_device_info(self.uuid, "heatfs", "v", value)
        self.publish_updates()

    async def set_cool_sub_mode(self, value: int):
        self.cool_sub_mode = value
        await self.api.set_device_info(self.uuid, "coolsubmode", "v", value)
        self.publish_updates()

    async def set_cool_fan_speed(self, value: int):
        self.cool_fan_speed = value
        await self.api.set_device_info(self.uuid, "coolfs", "v", value)
        self.publish_updates()

    async def set_ap_sub_mode(self, value: int):
        self.ap_sub_mode = value
        await self.api.set_device_info(self.uuid, "apsubmode", "v", value)
        self.publish_updates()

    async def set_fan_speed_0(self, value: int):
        self.fan_speed_0 = value
        await self.api.set_device_info(self.uuid, "fsp0", "v", value)
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
        if self.sku in ["110092", "110829"]:
            return ModelEnum.MAX_311I
        if self.sku == "110057":
            return ModelEnum.MAX_411I
        if self.sku == "112124":
            return ModelEnum.T10I
        if self.sku == "109539":
            return ModelEnum.MAX_311I_PLUS
        return ModelEnum.UNKNOWN

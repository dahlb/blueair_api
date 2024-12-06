import dataclasses
import logging

from .callbacks import CallbacksMixin
from .http_blueair import HttpBlueair

_LOGGER = logging.getLogger(__name__)


@dataclasses.dataclass(slots=True)
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

    api: HttpBlueair
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
    fan_mode: str | None = None
    filter_expired: bool | None = None
    wifi_working: bool | None = None

    async def refresh(self):
        _LOGGER.debug("Requesting current attributes...")
        attributes = await self.api.get_attributes(self.uuid)
        _LOGGER.debug(f"result: {attributes}")
        if "brightness" in attributes:
            self.brightness = int(attributes["brightness"])
        else:
            self.brightness = 0
        if "child_lock" in attributes:
            self.child_lock = bool(attributes["child_lock"])
        if "night_mode" in attributes:
            self.night_mode = bool(attributes["night_mode"])
        self.fan_speed = int(attributes["fan_speed"])
        if "filter_status" in attributes:
            self.filter_expired = attributes["filter_status"] != "OK"
        self.fan_mode = attributes["mode"]
        if "wifi_status" in attributes:
            self.wifi_working = attributes["wifi_status"] == "1"
        else:
            self.wifi_working = False
        _LOGGER.debug(f"refreshed blueair device: {self}")
        self.publish_updates()

    async def set_fan_speed(self, new_speed):
        await self.api.set_fan_speed(self.uuid, new_speed)

import logging

from .callbacks import CallbacksMixin
from .http_blueair import HttpBlueair

_LOGGER = logging.getLogger(__name__)


class Device(CallbacksMixin):
    uuid: str = None
    name: str = None
    timezone: str = None
    compatibility: str = None
    model: str = None
    mac: str = None
    firmware: str = None
    mcu_firmware: str = None
    wlan_driver: str = None
    room_location: str = None

    brightness: int = None
    child_lock: bool = None
    fan_speed: int = None
    fan_mode: str = None
    filter_expired: bool = None
    wifi_working: bool = None

    def __init__(
        self,
        api: HttpBlueair,
        uuid: str = None,
        name: str = None,
        mac: str = None,
    ):
        self.api = api
        self.uuid = uuid
        self.name = name
        self.mac = mac
        _LOGGER.debug(f"creating blueair device: {self.name}")

    async def init(self):
        info = await self.api.get_info(self.uuid)
        self.timezone = info["timezone"]
        self.compatibility = info["compatibility"]
        self.model = info["model"]
        self.firmware = info["firmware"]
        self.mcu_firmware = info["mcuFirmware"]
        self.wlan_driver = info["wlanDriver"]
        self.room_location = info["roomLocation"]

    async def refresh(self):
        _LOGGER.debug("Requesting current attributes...")
        attributes = await self.api.get_attributes(self.uuid)
        _LOGGER.debug(f"result: {attributes}")
        self.brightness = int(attributes["brightness"])
        self.child_lock = bool(attributes["child_lock"])
        self.fan_speed = int(attributes["fan_speed"])
        self.filter_expired = attributes["filter_status"] != "OK"
        self.fan_mode = attributes["mode"]
        self.wifi_working = attributes["wifi_status"] == "1"
        self.publish_updates()

    async def set_fan_speed(self, new_speed):
        await self.api.set_fan_speed(self.uuid, new_speed)

    def __repr__(self):
        return {
            "uuid": self.uuid,
            "name": self.name,
            "timezone": self.timezone,
            "compatibility": self.compatibility,
            "model": self.model,
            "mac": self.mac,
            "firmware": self.firmware,
            "mcu_firmware": self.mcu_firmware,
            "wlan_driver": self.wlan_driver,
            "room_location": self.room_location,
            "brightness": self.brightness,
            "child_lock": self.child_lock,
            "fan_speed": self.fan_speed,
            "filter_expired": self.filter_expired,
            "fan_mode": self.fan_mode,
            "wifi_working": self.wifi_working,
        }

    def __str__(self):
        return f"{self.__repr__()}"

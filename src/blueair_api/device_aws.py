from functools import cached_property
from typing import Any

from logging import getLogger
from json import dumps

from .callbacks import CallbacksMixin
from .http_aws_blueair import HttpAwsBlueair
from .sku_map import model_name_from_sku
from . import intermediate_representation_aws as ir
from dataclasses import dataclass, field

_LOGGER = getLogger(__name__)

type AttributeType[T] = T | None

# Mapping from MQTT sensor slug (as sent on d/<id>/s/5s topic) to DeviceAws
# attribute name.  Values arrive as floats from SenML and are cast to int.
MQTT_SENSOR_FIELD_MAP: dict[str, str] = {
    "pm1": "pm1",
    "pm2_5": "pm2_5",
    "pm10": "pm10",
    "tVOC": "total_voc",
    "voc": "voc",
    "t": "temperature",
    "h": "humidity",
    "fsp0": "fan_speed_0",
    "rssi": "rssi",
}

# Mapping from shadow state field (as sent on $aws/things/<id>/shadow/...)
# to DeviceAws attribute name.
SHADOW_FIELD_MAP: dict[str, str] = {
    "standby": "standby",
    "nightmode": "night_mode",
    "germshield": "germ_shield",
    "brightness": "brightness",
    "nlbrightness": "mood_brightness",
    "childlock": "child_lock",
    "wlevel": "water_level",
    "fanspeed": "fan_speed",
    "automode": "fan_auto_mode",
    "filterusage": "filter_usage_percentage",
    "ywrmusage": "water_refresher_usage_percentage",
    "wickusage": "wick_usage_percentage",
    "wickdrys": "wick_dry_mode",
    "autorh": "auto_regulated_humidity",
    "wshortage": "water_shortage",
    "hummode": "humidifier_mode",
    "mode": "combo_mode",
    "mainmode": "main_mode",
    "heattemp": "heat_temp",
    "heatsubmode": "heat_sub_mode",
    "heatfs": "heat_fan_speed",
    "coolsubmode": "cool_sub_mode",
    "coolfs": "cool_fan_speed",
    "apsubmode": "ap_sub_mode",
    "fsp0": "fan_speed_0",
    "tu": "temperature_unit",
    # Mini Restful sunrise / timer fields.
    "nlstepless": "night_light_brightness",
    "timstate": "timer_state",
    "timl": "timer_level",
    "timts": "timer_start_timestamp",
    "timdur": "timer_duration",
    "hourformat": "hour_format",
}

# Label map for the `apsubmode` shadow field on Signature-series air
# purifiers (Blueair Blue Signature SP4i and related models with
# type_name='blue40', hw='l_blue40'). These devices do NOT expose the
# legacy `automode` / `nightmode` shadow fields; all preset switching
# is performed via `apsubmode`.
#
# Filed as ha_blueair#348 by @Pazuzu6666 (sanitized SP4i debug log) and
# ha_blueair#261 by @madkatz01 / @disruptivepatternmaterial / @Pazuzu5688
# (multiple Signature owners; same observed mapping).
#
# Phase 3 of dahlb/ha_blueair#334 (tracked as ha_blueair#353) will
# consume this dict as the `value_labels` of a future
# FieldProfile("apsubmode") and add `apsubmode` to the FieldProfile
# deny-list so the schema-driven `select` does not duplicate the
# fan-platform preset list.
#
# IMPORTANT: `apsubmode` is a POLYVALENT shadow slug — the same wire
# field carries different value namespaces on different device
# families. This dict is INTENTIONALLY Signature-only.
#
#   * Signature (blue40, hw='l_blue40'): values 0/2/3/4 mean
#     manual_fan/auto/night/eco. The device has no other preset
#     mechanism — `apsubmode` is the sole control.
#
#   * T10i (cmb3in1): values 1/2 only, and only meaningful while
#     `mainmode==0` (HVAC FAN_ONLY). In HEAT mode `heatsubmode`
#     supersedes; in COOL mode `coolsubmode` supersedes. T10i is
#     surfaced via the HA climate platform, not the fan platform.
#
#   * pet_air_pro / 2-in-1 / older AWS purifiers: declare `apsubmode`
#     in their schema but `ha_blueair` does not consume it — preset
#     modes come from `automode` / `nightmode`. Value semantics TBD.
#
# The three families are kept disjoint by a capability gate in
# ha_blueair's BlueairAwsFan:
#   `ap_sub_mode != NotImplemented
#    AND fan_auto_mode == NotImplemented
#    AND night_mode == NotImplemented`
# Only Signature devices pass that gate, so only Signature devices
# consume AP_SUB_MODE_LABELS. T10i / pet_air_pro / 2-in-1 declare
# `automode` and so are excluded.
#
# Consumers MUST NOT treat AP_SUB_MODE_LABELS as a global decoder
# for `apsubmode` — that would mislabel T10i value 1 as missing
# from the namespace when it is in fact a valid T10i value.
#
# NOTE on the manual_fan wire value: investigation of the Blueair
# cloud API responses and AWS IoT protocol behavior suggests that
# the canonical wire value for the manual / fan-speed-only mode is
# **1**. The 0 mapping below is the value that was empirically
# confirmed by the user who supplied the SP4i debug log (writing
# apsubmode=0 successfully transitioned the SP4i into manual fan
# mode and accepted subsequent fanspeed writes). Firmware appears
# to accept either 0 or 1 as "exit current preset; resume manual
# control" — keep 0 unless and until a tester confirms that
# writing 1 has the same effect on real hardware. If 1 turns out
# to be exclusively accepted by some firmware revision, switch
# this mapping accordingly.
AP_SUB_MODE_LABELS: dict[int, str] = {
    0: "manual_fan",
    2: "auto",
    3: "night",
    4: "eco",
}

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
    raw_sensors : dict[str, Any] = field(repr=False, init=False)

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
    mood_brightness : AttributeType[int] = None
    child_lock : AttributeType[bool] = None
    fan_speed : AttributeType[int] = None
    fan_auto_mode : AttributeType[bool] = None
    standby : AttributeType[bool] = None
    night_mode : AttributeType[bool] = None
    germ_shield : AttributeType[bool] = None

    pm1 : AttributeType[int] = None
    pm2_5 : AttributeType[int] = None
    pm10 : AttributeType[int] = None
    total_voc : AttributeType[int] = None
    voc : AttributeType[int] = None
    temperature : AttributeType[int] = None
    humidity : AttributeType[int] = None
    filter_usage_percentage : AttributeType[int] = None
    wifi_working : AttributeType[bool] = None

    sensor_data_timestamp : float | None = None

    wick_usage_percentage : AttributeType[int] = None
    water_refresher_usage_percentage : AttributeType[int] = None
    wick_dry_mode : AttributeType[bool] = None
    water_shortage : AttributeType[bool] = None
    water_level: AttributeType[int] = None
    auto_regulated_humidity : AttributeType[int] = None

    # Combo (2-in-1 purify + humidify) controls. Present on DeviceCombo2in1
    # devices (hw='s_cmb2in1', e.g. the DH3i). `humidifier_mode` is the
    # independent humidification on/off (shadow + writable `hummode`),
    # separate from `standby` (whole-device power) so the purifier can keep
    # running while humidification is toggled off. `combo_mode` is the
    # device's preset/mode selector (shadow + writable `mode`); per the
    # firmware's Mode enum: 1=fan/manual, 2=auto, 3=night, 4=eco, 5=skin.
    humidifier_mode: AttributeType[bool] = None
    combo_mode: AttributeType[int] = None

    main_mode: AttributeType[int] = None # api value 0 purify only, 1 heat on, 2 cool on
    heat_sub_mode: AttributeType[int] = None # api value 1 heat on, 2 heat on with fan auto
    heat_fan_speed: AttributeType[int] = None # api value 11/37/64/91
    heat_temp: AttributeType[int] = None # api value is celsius * 10
    cool_sub_mode: AttributeType[int] = None # api value 1 cool on, 2 cool on with fan auto
    cool_fan_speed: AttributeType[int] = None # api value 11/37/64/91
    ap_sub_mode: AttributeType[int] = None # api value 1 manual speeed, 2 auto fan speed
    fan_speed_0: AttributeType[int] = None # api value 11/37/64/91
    temperature_unit: AttributeType[int] = None # api value of 1 is celcius
    hw: AttributeType[str] = None # hardware identifier from configuration.di.hw

    # MQTT-only first-class sensor (signal strength, dBm).
    rssi: AttributeType[int] = None

    # Mini Restful sunrise / timer fields (also present on humidifiers
    # like H35i for the sleep timer).
    night_light_brightness: AttributeType[int] = None  # nlstepless, 0-100
    timer_state: AttributeType[int] = None  # timstate, 0=off 1=running
    timer_level: AttributeType[int] = None  # timl
    timer_start_timestamp: AttributeType[int] = None  # timts, unix epoch
    timer_duration: AttributeType[int] = None  # timdur, seconds
    hour_format: AttributeType[bool] = None  # hourformat, False=12h True=24h

    mqtt_sensor_slugs: list[str] = field(default_factory=list, repr=False, init=False)
    extra_sensors: dict[str, Any] = field(default_factory=dict, repr=False, init=False)

    async def refresh(self):
        _LOGGER.debug(f"refreshing blueair device aws: {self}")
        self.raw_info = await self.api.device_info(self.name_api, self.uuid)
        self.raw_sensors = await self.api.device_sensors(self.name_api, self.uuid)
        _LOGGER.debug(dumps(self.raw_info, indent=2))
        if self.raw_sensors is not None:
            _LOGGER.debug(dumps(self.raw_sensors, indent=2))

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
        self.hw = info_safe_get("configuration.di.hw")

        raw_ds = ir.query_json(self.raw_info, "configuration.ds")
        ds = ir.parse_json(ir.Sensor, raw_ds)
        dc = ir.parse_json(ir.Control, ir.query_json(self.raw_info, "configuration.dc"))

        # Store the list of MQTT sensor slugs from the 5-second polling
        # topic.  Defensive against malformed schemas: rt5s missing,
        # rt5s.sn null, or wrong types all degrade to an empty list so
        # apply_sensor_data and is_implemented checks stay correct.
        rt5s_raw = raw_ds.get("rt5s") if isinstance(raw_ds, dict) else None
        sn = rt5s_raw.get("sn") if isinstance(rt5s_raw, dict) else None
        self.mqtt_sensor_slugs = (
            [str(s) for s in sn] if isinstance(sn, list) else []
        )
        # Log once per refresh so the expected MQTT slug set is visible
        # in user-supplied debug logs.
        _LOGGER.debug(
            "Device %s declares MQTT 5s sensor slugs: %s",
            self.uuid, self.mqtt_sensor_slugs
        )

        # Auto-populate dc from state keys the device reports but aren't
        # declared in the dc schema.  Some devices (e.g. H38i, H76i,
        # Mini Restful) have an incomplete dc yet still publish the
        # corresponding states.  This generic fixup replaces per-model
        # hard-coded patches and ensures future devices work without
        # code changes.
        for state in self.raw_info.get("states", []):
            key = state.get("n")
            if key and key not in dc and key != "online":
                dc[key] = ir.Control(extra_fields={}, n=key, v=NotImplemented)

        sensor_data = ir.SensorHistory(self.raw_sensors).to_latest()
        self.sensor_data_timestamp = sensor_data.timestamp if sensor_data.timestamp else None

        def sensor_data_safe_get(key):
            return sensor_data.values.get(key) if key in ds else NotImplemented

        self.pm1 = sensor_data_safe_get("pm1")
        self.pm2_5 = sensor_data_safe_get("pm2_5")
        self.pm10 = sensor_data_safe_get("pm10")
        self.total_voc = sensor_data_safe_get("tVOC")
        self.voc = sensor_data_safe_get("voc")
        self.temperature = sensor_data_safe_get("t")
        self.humidity = sensor_data_safe_get("h")
        self.fan_speed_0 = sensor_data_safe_get("fsp0")
        self.rssi = sensor_data_safe_get("rssi")

        states = ir.SensorPack(self.raw_info["states"]).to_latest_value()

        def states_safe_get(key):
            return states.get(key) if key in dc else NotImplemented

        # "online" is not defined in the schema (dc).
        # The Blueair cloud API frequently reports online=False even when
        # the device is fully operational and reporting live sensor data
        # (see https://github.com/dahlb/ha_blueair/issues/287).
        #
        # We faithfully report the API value (defaulting to True when
        # absent), but consumers should NOT gate entity availability on
        # this field. It is informational only.
        online_state = states.get("online")
        self.wifi_working = online_state if online_state is not None else True

        self.standby = states_safe_get("standby")
        self.night_mode = states_safe_get("nightmode")
        self.germ_shield = states_safe_get("germshield")
        self.brightness = states_safe_get("brightness")
        self.mood_brightness = states_safe_get("nlbrightness")
        self.child_lock = states_safe_get("childlock")
        self.water_level = states_safe_get("wlevel")
        self.fan_speed = states_safe_get("fanspeed")
        if self._is_humidifier:
            if self.fan_speed == 11:
                self.fan_speed = 1
            elif self.fan_speed == 37:
                self.fan_speed = 2
            elif self.fan_speed == 64:
                self.fan_speed = 3
        self.fan_auto_mode = states_safe_get("automode")
        self.filter_usage_percentage = states_safe_get("filterusage")
        self.water_refresher_usage_percentage = states_safe_get("ywrmusage")

        self.wick_usage_percentage = states_safe_get("wickusage")
        self.wick_dry_mode = states_safe_get("wickdrys")
        self.auto_regulated_humidity = states_safe_get("autorh")
        self.water_shortage = states_safe_get("wshortage")

        self.humidifier_mode = states_safe_get("hummode")
        self.combo_mode = states_safe_get("mode")

        self.main_mode = states_safe_get("mainmode")
        self.heat_temp = states_safe_get("heattemp")
        self.heat_sub_mode = states_safe_get("heatsubmode")
        self.heat_fan_speed = states_safe_get("heatfs")
        self.cool_sub_mode = states_safe_get("coolsubmode")
        self.cool_fan_speed = states_safe_get("coolfs")
        self.ap_sub_mode = states_safe_get("apsubmode")
        if states_safe_get("fsp0") is NotImplemented:
            self.fan_speed_0 = sensor_data_safe_get("fsp0")
        else:
            self.fan_speed_0 = states_safe_get("fsp0")
        self.temperature_unit = states_safe_get("tu")

        # Mini Restful sunrise / timer fields.
        self.night_light_brightness = states_safe_get("nlstepless")
        self.timer_state = states_safe_get("timstate")
        self.timer_level = states_safe_get("timl")
        self.timer_start_timestamp = states_safe_get("timts")
        self.timer_duration = states_safe_get("timdur")
        self.hour_format = states_safe_get("hourformat")

        self.publish_updates()
        _LOGGER.debug(f"refreshed blueair device aws: {self}")

    def apply_sensor_data(self, sensors: dict[str, float]) -> None:
        """Apply MQTT sensor data to device attributes.

        Maps MQTT sensor slugs to DeviceAws attribute names using
        MQTT_SENSOR_FIELD_MAP. Unknown fields are stored in extra_sensors
        (logged once per slug at debug level so unmapped fields can be
        diagnosed from logs).

        Per-slug failures are caught and logged so a single bad value
        does not drop the rest of the batch.
        """
        for slug, value in sensors.items():
            attr = MQTT_SENSOR_FIELD_MAP.get(slug)
            if attr is None:
                if slug not in self.extra_sensors:
                    _LOGGER.debug(
                        "MQTT sensor %r not in MQTT_SENSOR_FIELD_MAP; "
                        "storing in extra_sensors (value=%r)", slug, value
                    )
                self.extra_sensors[slug] = value
                continue
            try:
                setattr(self, attr, int(value))
            except (TypeError, ValueError):
                _LOGGER.warning(
                    "MQTT sensor %r (-> %s) has unexpected value %r; "
                    "skipping this update", slug, attr, value
                )
            except AttributeError:
                # slots=True: attr in map but not declared on dataclass.
                _LOGGER.error(
                    "MQTT_SENSOR_FIELD_MAP maps %r to %r but DeviceAws "
                    "has no such attribute; this is a library bug",
                    slug, attr
                )

    def apply_state_change(self, state: dict[str, Any]) -> None:
        """Apply MQTT shadow state update to device attributes.

        Maps shadow field names to DeviceAws attribute names using
        SHADOW_FIELD_MAP. Applies humidifier fan speed remapping.

        Unmapped fields and per-field failures are logged so behavior
        can be diagnosed from logs alone.
        """
        for shadow_field, value in state.items():
            attr = SHADOW_FIELD_MAP.get(shadow_field)
            if attr is None:
                _LOGGER.debug(
                    "Shadow field %r not in SHADOW_FIELD_MAP; ignoring "
                    "(value=%r)", shadow_field, value
                )
                continue
            if not hasattr(self, attr):
                # slots=True: attr in map but not declared on dataclass.
                _LOGGER.error(
                    "SHADOW_FIELD_MAP maps %r to %r but DeviceAws has "
                    "no such attribute; this is a library bug",
                    shadow_field, attr
                )
                continue
            try:
                setattr(self, attr, value)
            except AttributeError:
                _LOGGER.error(
                    "Failed to set DeviceAws.%s = %r from shadow field %r",
                    attr, value, shadow_field
                )

        # Apply humidifier fan speed remapping (same as refresh).
        # Only remap if the loop above actually set fan_speed to a known
        # raw value; guard against non-int payloads landing on the attr.
        if "fanspeed" in state and self._is_humidifier:
            if self.fan_speed == 11:
                self.fan_speed = 1
            elif self.fan_speed == 37:
                self.fan_speed = 2
            elif self.fan_speed == 64:
                self.fan_speed = 3

    async def set_brightness(self, value: int):
        self.brightness = value
        await self.api.set_device_info(self.uuid, "brightness", "v", value)
        self.publish_updates()

    async def set_mood_brightness(self, value: int):
        self.mood_brightness = value
        await self.api.set_device_info(self.uuid, "nlbrightness", "v", value)
        self.publish_updates()

    @property
    def _is_humidifier(self) -> bool:
        """True for humidifier-class devices that use 3-speed fan mapping."""
        hw = self.hw if isinstance(self.hw, str) else ""
        return hw.startswith("hum")

    @property
    def mood_brightness_max(self) -> int:
        """Max mood-light brightness the hardware supports.

        The H76i (hw='hum2_l') has a 3-step mood light; all other
        models use a 0-100 percentage scale."""
        hw = self.hw if isinstance(self.hw, str) else ""
        if hw == "hum2_l":
            return 3
        return 100

    @property
    def fan_speed_count(self) -> int:
        hw = self.hw if isinstance(self.hw, str) else ""
        if self._is_humidifier:
            return 3
        # The 2-in-1 Purify + Humidify combos belong to the same 4-gear
        # fan-speed family as the nb_/high purifiers: manual speed runs on
        # a 0-91 scale (gears 0, 11, 37, 64, 91; the device snaps a written
        # value to its nearest gear). Capping at 91 lets the top gear map
        # to 100% in the UI instead of being scaled against 100.
        #   - s_cmb2in1  : DH3i (field-confirmed from a live fan trace)
        #   - cmb2in1_ii : 2-in-1 Pro (same fan capability class as the DH3i)
        if (
            hw.startswith("nb_")
            or hw.startswith("high")
            or hw.startswith("s_cmb2in1")
            or hw.startswith("cmb2in1_ii")
        ):
            return 91
        if hw.startswith("cmb3in1"):
            return 4
        return 100

    async def set_fan_speed(self, value: int):
        self.fan_speed = value
        if self._is_humidifier:
            if value == 1:
                value = 11
            elif value == 2:
                value = 37
            elif value == 3:
                value = 64
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

    async def set_humidifier_mode(self, value: bool):
        self.humidifier_mode = value
        await self.api.set_device_info(self.uuid, "hummode", "vb", value)
        self.publish_updates()

    async def set_combo_mode(self, value: int):
        self.combo_mode = value
        await self.api.set_device_info(self.uuid, "mode", "v", value)
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

    async def set_night_light_brightness(self, value: int):
        """Set the sunrise / night light stepless brightness (0-100)."""
        self.night_light_brightness = value
        await self.api.set_device_info(self.uuid, "nlstepless", "v", value)
        self.publish_updates()

    async def set_timer_duration(self, value: int):
        """Set the sleep / off timer duration in seconds."""
        self.timer_duration = value
        await self.api.set_device_info(self.uuid, "timdur", "v", value)
        self.publish_updates()

    async def set_hour_format(self, value: bool):
        """Set the clock display: False = 12-hour, True = 24-hour."""
        self.hour_format = value
        await self.api.set_device_info(self.uuid, "hourformat", "vb", value)
        self.publish_updates()

    @property
    def model_name(self) -> str:
        """Human-readable product name derived from SKU lookup."""
        return model_name_from_sku(self.sku)

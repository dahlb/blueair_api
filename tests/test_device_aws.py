"""Tests for DeviceAws.

Here is one way to run it:

First install the package in developer mode

    $ pip install -e .

Then use pytest to drive the tests

    $ pytest tests
"""
import typing
from typing import Any

import contextlib
import dataclasses
from importlib import resources
import json
from unittest import mock
from unittest import IsolatedAsyncioTestCase, TestCase

import pytest

from blueair_api.device_aws import DeviceAws, AttributeType
from blueair_api.sku_map import UNKNOWN_MODEL
from blueair_api import http_aws_blueair
from blueair_api import intermediate_representation_aws as ir


class FakeDeviceInfoHelper:
    """Fake for the 'device info' interface of HttpAwsBlueAir class."""
    def __init__(self, info: dict[str, Any]):
        self.info = info

    async def device_info(self, *args, **kwargs):
        return self.info

    async def set_device_info(self, device_uuid, service_name, action_verb, action_value):
        # this function seems to be only updating the states consider rename the method.
        # action_verb seems to be a type annotation:
        # c.f. senml: https://www.rfc-editor.org/rfc/rfc8428.html#section-5
        # the senml parsing library (utils.py) could use some additional love.
        # to make it more conformal to the RFC standard.
        for state in self.info['states']:
            if state['n'] == service_name:
                break
        else:
            state = {'n': service_name}
            self.info['states'].append(state)
        # Watch out: mutate after append produces desired mutation to info.
        state[action_verb] = action_value


class AssertFullyCheckedHelper:
    """Assert that all attributes of AttributeType are accessed once."""
    def __init__(self, device : DeviceAws):
        self.device = device
        self.logs = []
        self.fields = set()
        for field in dataclasses.fields(self.device):
            if typing.get_origin(field.type) is AttributeType:
                self.fields.add(field.name)

    def __getattr__(self, attr):
        if attr in self.fields:
            self.logs.append(attr)
        return getattr(self.device, attr)


@contextlib.contextmanager
def assert_fully_checked(device):
    helper = AssertFullyCheckedHelper(device)
    yield helper
    assert set(helper.logs) == helper.fields


class DeviceAwsTestBase(IsolatedAsyncioTestCase):

    def setUp(self):

        patcher = mock.patch('blueair_api.http_aws_blueair.HttpAwsBlueair', autospec=True)
        self.api_class = patcher.start()
        self.addCleanup(patcher.stop)
        self.api = self.api_class(username="fake-username", password="fake-password")

        self.device = DeviceAws(self.api,
             name_api="fake-name-api",
             uuid="fake-uuid",
             name="fake-name",
             mac="fake-mac",
             type_name='fake-type-name')

        self.device_info_helper = FakeDeviceInfoHelper(
           {"configuration": {"di" : {}, "ds" : {}, "dc" : {}, "da" : {},},
            "sensordata": [],
            "states": [],
           })

        self.device_sensor_helper = {"mock_data": [{
                "datapoints": [],
                "sensors": []
            }]}
        async def fake_sensors(device_name, device_uuid):
            return self.device_sensor_helper["mock_data"]

        self.api.device_sensors.side_effect = fake_sensors
        self.api.device_info.side_effect = self.device_info_helper.device_info
        self.api.set_device_info.side_effect = self.device_info_helper.set_device_info


class DeviceAwsSetterTest(DeviceAwsTestBase):
    """Tests for all of the setters."""

    def setUp(self):
        super().setUp()
        # minimally populate dc to define the states.
        fake = {"n": "n", "v": 0}
        ir.query_json(self.device_info_helper.info, "configuration.dc").update({
            "brightness": fake,
            "fanspeed": fake,
            "standby": fake,
            "germshield": fake,
            "automode": fake,
            "autorh": fake,
            "childlock": fake,
            "nightmode": fake,
            "wickdrys": fake,
            "hummode": fake,
            "mode": fake,
            "mainmode": fake,
            "heattemp": fake,
            "heatsubmode": fake,
            "heatfs": fake,
            "coolsubmode": fake,
            "coolfs": fake,
            "apsubmode": fake,
            "fsp0": fake,
        })

    async def test_brightness(self):
        # test cache works
        self.device.brightness = None
        await self.device.set_brightness(1)
        assert self.device.brightness == 1

        # test refresh works
        await self.device.set_brightness(2)
        self.device.brightness = None
        await self.device.refresh()
        assert self.device.brightness == 2

    async def test_fan_speed(self):
        # test cache works
        self.device.fan_speed = None
        await self.device.set_fan_speed(1)
        assert self.device.fan_speed == 1

        # test refresh works
        await self.device.set_fan_speed(2)
        self.device.fan_speed = None
        await self.device.refresh()
        assert self.device.fan_speed == 2

    async def test_germ_shield(self):
        # test cache works
        self.device.germ_shield = None
        await self.device.set_germ_shield(False)
        assert self.device.germ_shield is False

        # test refresh works
        await self.device.set_germ_shield(True)
        self.device.germ_shield = None
        await self.device.refresh()
        assert self.device.germ_shield is True

    async def test_standby(self):
        # test cache works
        self.device.standby = None
        await self.device.set_standby(False)
        assert self.device.standby is False

        # test refresh works
        await self.device.set_standby(True)
        self.device.standby = None
        await self.device.refresh()
        assert self.device.standby is True

    async def test_fan_auto_mode(self):
        # test cache works
        self.device.fan_auto_mode = None
        await self.device.set_fan_auto_mode(False)
        assert self.device.fan_auto_mode is False

        # test refresh works
        await self.device.set_fan_auto_mode(True)
        self.device.fan_auto_mode = None
        await self.device.refresh()
        assert self.device.fan_auto_mode is True

    async def test_auto_regulated_humidity(self):
        # test cache works
        self.device.auto_regulated_humidity = None
        await self.device.set_auto_regulated_humidity(1)
        assert self.device.auto_regulated_humidity == 1

        # test refresh works
        await self.device.set_auto_regulated_humidity(2)
        self.device.auto_regulated_humidity = None
        await self.device.refresh()
        assert self.device.auto_regulated_humidity == 2

    async def test_child_lock(self):
        # test cache works
        self.device.child_lock = None
        await self.device.set_child_lock(False)
        assert self.device.child_lock is False

        # test refresh works
        await self.device.set_child_lock(True)
        self.device.child_lock = None
        await self.device.refresh()
        assert self.device.child_lock is True

    async def test_night_mode(self):
        # test cache works
        self.device.night_mode = None
        await self.device.set_night_mode(False)
        assert self.device.night_mode is False

        # test refresh works
        await self.device.set_night_mode(True)
        self.device.night_mode = None
        await self.device.refresh()
        assert self.device.night_mode is True

    async def test_wick_dry_mode(self):
        # test cache works
        self.device.wick_dry_mode = None
        await self.device.set_wick_dry_mode(False)
        assert self.device.wick_dry_mode is False

        # test refresh works
        await self.device.set_wick_dry_mode(True)
        self.device.wick_dry_mode = None
        await self.device.refresh()
        assert self.device.wick_dry_mode is True

    async def test_main_mode(self):
        # test cache works
        self.device.main_mode = None
        await self.device.set_main_mode(1)
        assert self.device.main_mode == 1

        # test refresh works
        await self.device.set_main_mode(2)
        self.device.main_mode = None
        await self.device.refresh()
        assert self.device.main_mode == 2

    async def test_hum_mode(self):
        # test cache works
        self.device.hum_mode = None
        await self.device.set_hum_mode(False)
        assert self.device.hum_mode is False

        # test refresh works
        await self.device.set_hum_mode(True)
        self.device.hum_mode = None
        await self.device.refresh()
        assert self.device.hum_mode is True

    async def test_combo_mode(self):
        # test cache works
        self.device.combo_mode = None
        await self.device.set_combo_mode(1)
        assert self.device.combo_mode == 1

        # test refresh works
        await self.device.set_combo_mode(2)
        self.device.combo_mode = None
        await self.device.refresh()
        assert self.device.combo_mode == 2

    async def test_heat_temp(self):
        # test cache works
        self.device.heat_temp = None
        await self.device.set_heat_temp(1)
        assert self.device.heat_temp == 1

        # test refresh works
        await self.device.set_heat_temp(2)
        self.device.heat_temp = None
        await self.device.refresh()
        assert self.device.heat_temp == 2

    async def test_heat_sub_mode(self):
        # test cache works
        self.device.heat_sub_mode = None
        await self.device.set_heat_sub_mode(1)
        assert self.device.heat_sub_mode == 1

        # test refresh works
        await self.device.set_heat_sub_mode(2)
        self.device.heat_sub_mode = None
        await self.device.refresh()
        assert self.device.heat_sub_mode == 2

    async def test_heat_fan_speed(self):
        # test cache works
        self.device.heat_fan_speed = None
        await self.device.set_heat_fan_speed(1)
        assert self.device.heat_fan_speed == 1

        # test refresh works
        await self.device.set_heat_fan_speed(2)
        self.device.heat_fan_speed = None
        await self.device.refresh()
        assert self.device.heat_fan_speed == 2

    async def test_cool_sub_mode(self):
        # test cache works
        self.device.cool_sub_mode = None
        await self.device.set_cool_sub_mode(1)
        assert self.device.cool_sub_mode == 1

        # test refresh works
        await self.device.set_cool_sub_mode(2)
        self.device.cool_sub_mode = None
        await self.device.refresh()
        assert self.device.cool_sub_mode == 2

    async def test_cool_fan_speed(self):
        # test cache works
        self.device.cool_fan_speed = None
        await self.device.set_cool_fan_speed(1)
        assert self.device.cool_fan_speed == 1

        # test refresh works
        await self.device.set_cool_fan_speed(2)
        self.device.cool_fan_speed = None
        await self.device.refresh()
        assert self.device.cool_fan_speed == 2

    async def test_ap_sub_mode(self):
        # test cache works
        self.device.ap_sub_mode = None
        await self.device.set_ap_sub_mode(1)
        assert self.device.ap_sub_mode == 1

        # test refresh works
        await self.device.set_ap_sub_mode(2)
        self.device.ap_sub_mode = None
        await self.device.refresh()
        assert self.device.ap_sub_mode == 2

    async def test_fan_speed_0(self):
        # test cache works
        self.device.fan_speed_0 = None
        await self.device.set_fan_speed_0(1)
        assert self.device.fan_speed_0 == 1

        # test refresh works
        await self.device.set_fan_speed_0(2)
        self.device.fan_speed_0 = None
        await self.device.refresh()
        assert self.device.fan_speed_0 == 2


class EmptyDeviceAwsTest(DeviceAwsTestBase):
    """Tests for a emptydevice.

    This is a made-up device. All attrs are not implemented.

    Other device types shall override setUp and populate self.info with the
    golden dataset.
    """

    async def test_attributes(self):

        await self.device.refresh()
        self.api.device_info.assert_awaited_with("fake-name-api", "fake-uuid")

        with assert_fully_checked(self.device) as device:

            assert UNKNOWN_MODEL in device.model_name

            assert device.hum_mode is NotImplemented
            assert device.combo_mode is NotImplemented

            assert device.pm1 is NotImplemented
            assert device.pm2_5 is NotImplemented
            assert device.pm10 is NotImplemented
            assert device.total_voc is NotImplemented
            assert device.voc is NotImplemented
            assert device.temperature is NotImplemented
            assert device.humidity is NotImplemented
            assert device.name is NotImplemented
            assert device.firmware is NotImplemented
            assert device.mcu_firmware is NotImplemented
            assert device.serial_number is NotImplemented
            assert device.sku is NotImplemented
            assert device.hw is NotImplemented

            assert device.standby is NotImplemented
            assert device.night_mode is NotImplemented
            assert device.germ_shield is NotImplemented
            assert device.brightness is NotImplemented
            assert device.child_lock is NotImplemented
            assert device.fan_speed is NotImplemented
            assert device.fan_auto_mode is NotImplemented
            assert device.filter_usage_percentage is NotImplemented
            assert device.wifi_working is True  # defaults to True when online state is missing
            assert device.wick_usage_percentage is NotImplemented
            assert device.auto_regulated_humidity is NotImplemented
            assert device.water_shortage is NotImplemented
            assert device.wick_dry_mode is NotImplemented
            assert device.main_mode is NotImplemented
            assert device.ap_sub_mode is NotImplemented
            assert device.heat_temp is NotImplemented
            assert device.heat_sub_mode is NotImplemented
            assert device.heat_fan_speed is NotImplemented
            assert device.cool_sub_mode is NotImplemented
            assert device.cool_fan_speed is NotImplemented
            assert device.fan_speed_0 is NotImplemented
            assert device.temperature_unit is NotImplemented
            assert device.mood_brightness is NotImplemented
            assert device.water_refresher_usage_percentage is NotImplemented
            assert device.water_level is NotImplemented
            assert device.rssi is NotImplemented
            assert device.night_light_brightness is NotImplemented
            assert device.timer_state is NotImplemented
            assert device.timer_level is NotImplemented
            assert device.timer_start_timestamp is NotImplemented
            assert device.timer_duration is NotImplemented
            assert device.hour_format is NotImplemented


class H35iTest(DeviceAwsTestBase):
    """Tests for H35i."""

    def setUp(self):
        super().setUp()
        with open(resources.files().joinpath('device_info/H35i.json')) as sample_file:
            info = json.load(sample_file)
        self.device_info_helper.info.update(info)

    async def test_attributes(self):

        await self.device.refresh()
        self.api.device_info.assert_awaited_with("fake-name-api", "fake-uuid")

        with assert_fully_checked(self.device) as device:

            assert device.model_name == "Blueair Humidifier H35i"
            assert device.hum_mode is NotImplemented
            assert device.combo_mode is NotImplemented

            assert device.pm1 is NotImplemented
            assert device.pm2_5 is NotImplemented
            assert device.pm10 is NotImplemented
            assert device.total_voc is NotImplemented
            assert device.voc is NotImplemented
            assert device.temperature is None
            assert device.humidity is None
            assert device.name == "Bedroom"
            assert device.firmware == "1.0.1"
            assert device.mcu_firmware == "1.0.1"
            assert device.serial_number == "111163300201110210004036"
            assert device.sku == "111633"
            assert device.hw == "hum"

            assert device.standby is False
            assert device.night_mode is False
            assert device.germ_shield is NotImplemented
            assert device.brightness == 49
            assert device.child_lock is False
            assert device.fan_speed == 24
            assert device.fan_auto_mode is False
            assert device.filter_usage_percentage is NotImplemented
            assert device.wifi_working is True
            assert device.wick_usage_percentage == 13
            assert device.auto_regulated_humidity == 50
            assert device.water_shortage is False
            assert device.wick_dry_mode is False
            assert device.main_mode is NotImplemented
            assert device.ap_sub_mode is NotImplemented
            assert device.heat_temp is NotImplemented
            assert device.heat_sub_mode is NotImplemented
            assert device.heat_fan_speed is NotImplemented
            assert device.cool_sub_mode is NotImplemented
            assert device.cool_fan_speed is NotImplemented
            assert device.fan_speed_0 is None
            assert device.temperature_unit is NotImplemented
            assert device.mood_brightness is NotImplemented
            assert device.water_refresher_usage_percentage is NotImplemented
            assert device.water_level is NotImplemented
            assert device.rssi is None
            assert device.night_light_brightness is NotImplemented
            assert device.timer_state == 0
            assert device.timer_level == 0
            assert device.timer_start_timestamp == 0
            assert device.timer_duration == 7200
            assert device.hour_format is NotImplemented


class H38iTest(DeviceAwsTestBase):
    """Tests for H38i."""

    def setUp(self):
        super().setUp()
        with open(resources.files().joinpath('device_info/H38i.json')) as sample_file:
            info = json.load(sample_file)
        self.device_info_helper.info.update(info)

    async def test_attributes(self):

        await self.device.refresh()
        self.api.device_info.assert_awaited_with("fake-name-api", "fake-uuid")

        with assert_fully_checked(self.device) as device:

            assert device.model_name == "Blueair DreamWell Humidifier H38i"
            assert device.hum_mode is NotImplemented
            assert device.combo_mode is NotImplemented

            assert device.pm1 is NotImplemented
            assert device.pm2_5 is NotImplemented
            assert device.pm10 is NotImplemented
            assert device.total_voc is NotImplemented
            assert device.voc is NotImplemented
            assert device.temperature is None
            assert device.humidity is None
            assert device.name == "Ezra Humidifier"
            assert device.firmware == "1.0.4"
            assert device.mcu_firmware == "1.0.1"
            assert device.serial_number == "111335300201111210008658"
            assert device.sku == "113353"
            assert device.hw == "hum2_s"

            assert device.standby is False
            assert device.night_mode is False
            assert device.germ_shield is NotImplemented
            assert device.brightness == 100
            assert device.child_lock is False
            assert device.fan_speed == 1
            assert device.fan_auto_mode is False
            assert device.filter_usage_percentage is NotImplemented
            assert device.wifi_working is False
            assert device.wick_usage_percentage == 0
            assert device.auto_regulated_humidity == 50
            assert device.water_shortage is NotImplemented
            assert device.wick_dry_mode is False
            assert device.main_mode is NotImplemented
            assert device.ap_sub_mode is NotImplemented
            assert device.heat_temp is NotImplemented
            assert device.heat_sub_mode is NotImplemented
            assert device.heat_fan_speed is NotImplemented
            assert device.cool_sub_mode is NotImplemented
            assert device.cool_fan_speed is NotImplemented
            assert device.fan_speed_0 is None
            assert device.temperature_unit is NotImplemented
            assert device.mood_brightness == 0
            assert device.water_refresher_usage_percentage == 0
            assert device.water_level == 0
            assert device.rssi is None
            assert device.night_light_brightness is NotImplemented
            assert device.timer_state == 0
            assert device.timer_level == 0
            assert device.timer_start_timestamp == 0
            assert device.timer_duration == 7200
            assert device.hour_format is NotImplemented


class H76iTest(DeviceAwsTestBase):
    """Tests for H76i."""

    def setUp(self):
        super().setUp()
        with open(resources.files().joinpath('device_info/H76i.json')) as sample_file:
            info = json.load(sample_file)
        self.device_info_helper.info.update(info)

    async def test_attributes(self):

        await self.device.refresh()
        self.api.device_info.assert_awaited_with("fake-name-api", "fake-uuid")

        with assert_fully_checked(self.device) as device:

            assert device.model_name == "Blueair DreamWell Humidifier H76i"
            assert device.hum_mode is NotImplemented
            assert device.combo_mode is NotImplemented

            assert device.pm1 is NotImplemented
            assert device.pm2_5 is NotImplemented
            assert device.pm10 is NotImplemented
            assert device.total_voc is NotImplemented
            assert device.voc is NotImplemented
            assert device.temperature is None
            assert device.humidity is None
            assert device.name == "Collin’s Bedroom Humidifier "
            assert device.firmware == "1.0.4"
            assert device.mcu_firmware == "1.0.4"
            assert device.serial_number == "111336600201110510002463"
            assert device.sku == "113366"
            assert device.hw == "hum2_l"

            assert device.standby is False
            assert device.night_mode is False
            assert device.germ_shield is NotImplemented
            assert device.brightness == 0
            assert device.child_lock is False
            assert device.fan_speed == 2
            assert device.fan_auto_mode is False
            assert device.filter_usage_percentage is NotImplemented
            assert device.wifi_working is True
            assert device.wick_usage_percentage == 3
            assert device.auto_regulated_humidity == 62
            assert device.water_shortage is NotImplemented
            assert device.wick_dry_mode is False
            assert device.main_mode is NotImplemented
            assert device.ap_sub_mode is NotImplemented
            assert device.heat_temp is NotImplemented
            assert device.heat_sub_mode is NotImplemented
            assert device.heat_fan_speed is NotImplemented
            assert device.cool_sub_mode is NotImplemented
            assert device.cool_fan_speed is NotImplemented
            assert device.fan_speed_0 is None
            assert device.temperature_unit is NotImplemented
            assert device.mood_brightness == 0
            assert device.water_refresher_usage_percentage == 0
            assert device.water_level == 50
            assert device.rssi is None
            assert device.night_light_brightness is NotImplemented
            assert device.timer_state == 0
            assert device.timer_level == 0
            assert device.timer_start_timestamp == 0
            assert device.timer_duration == 7200
            assert device.hour_format is NotImplemented


class Max311iTest(DeviceAwsTestBase):
    """Tests for H35i."""

    def setUp(self):
        super().setUp()
        with open(resources.files().joinpath('device_info/max_311i.json')) as sample_file:
            info = json.load(sample_file)
        self.device_info_helper.info.update(info)

    async def test_attributes(self):
        await self.device.refresh()
        self.api.device_info.assert_awaited_with("fake-name-api", "fake-uuid")

        with assert_fully_checked(self.device) as device:

            assert device.model_name == "Blueair Blue Pure 311i Max"
            assert device.hum_mode is NotImplemented
            assert device.combo_mode is NotImplemented

            assert device.pm1 is NotImplemented
            assert device.pm2_5 is None
            assert device.pm10 is NotImplemented
            assert device.total_voc is NotImplemented
            assert device.voc is NotImplemented
            assert device.temperature is NotImplemented
            assert device.humidity is NotImplemented
            assert device.name == "Loft"
            assert device.firmware == "1.0.4"
            assert device.mcu_firmware == "1.0.4"
            assert device.serial_number == "111082900302313210005018"
            assert device.sku == "110829"
            assert device.hw == "nb_m_1.0"

            assert device.standby is False
            assert device.night_mode is False
            assert device.germ_shield is NotImplemented
            assert device.brightness == 35
            assert device.child_lock is True
            assert device.fan_speed == 11
            assert device.fan_auto_mode is True
            assert device.filter_usage_percentage == 12
            assert device.wifi_working is True
            assert device.wick_usage_percentage is NotImplemented
            assert device.auto_regulated_humidity is NotImplemented
            assert device.water_shortage is NotImplemented
            assert device.wick_dry_mode is NotImplemented
            assert device.main_mode is NotImplemented
            assert device.ap_sub_mode is NotImplemented
            assert device.heat_temp is NotImplemented
            assert device.heat_sub_mode is NotImplemented
            assert device.heat_fan_speed is NotImplemented
            assert device.cool_sub_mode is NotImplemented
            assert device.cool_fan_speed is NotImplemented
            assert device.fan_speed_0 is None
            assert device.temperature_unit is NotImplemented
            assert device.mood_brightness is NotImplemented
            assert device.water_refresher_usage_percentage is NotImplemented
            assert device.water_level is NotImplemented
            assert device.rssi is None
            assert device.night_light_brightness is NotImplemented
            assert device.timer_state is NotImplemented
            assert device.timer_level is NotImplemented
            assert device.timer_start_timestamp is NotImplemented
            assert device.timer_duration is NotImplemented
            assert device.hour_format is NotImplemented


class T10iTest(DeviceAwsTestBase):
    """Tests for T10i."""

    def setUp(self):
        super().setUp()
        with open(resources.files().joinpath('device_info/T10i.json')) as sample_file:
            info = json.load(sample_file)
        self.device_info_helper.info.update(info)

    async def test_attributes(self):

        await self.device.refresh()
        self.api.device_info.assert_awaited_with("fake-name-api", "fake-uuid")

        with assert_fully_checked(self.device) as device:

            assert device.model_name == "Blueair ComfortPure 3-in-1 T10i"
            assert device.hum_mode is NotImplemented
            assert device.combo_mode is NotImplemented

            assert device.pm1 is NotImplemented
            assert device.pm2_5 is None
            assert device.pm10 is NotImplemented
            assert device.total_voc is NotImplemented
            assert device.voc is NotImplemented
            assert device.temperature is None
            assert device.humidity is None
            assert device.name == "Allen's Office"
            assert device.firmware == "1.0.4"
            assert device.mcu_firmware == "1.0.4"
            assert device.serial_number == "111212400002313210001961"
            assert device.sku == "112124"
            assert device.hw == "cmb3in1"

            assert device.standby is False
            assert device.night_mode is NotImplemented
            assert device.germ_shield is NotImplemented
            assert device.brightness == 100
            assert device.child_lock is False
            assert device.fan_speed is NotImplemented
            assert device.fan_auto_mode is NotImplemented
            assert device.filter_usage_percentage == 0
            assert device.wifi_working is True
            assert device.wick_usage_percentage is NotImplemented
            assert device.auto_regulated_humidity is NotImplemented
            assert device.water_shortage is NotImplemented
            assert device.wick_dry_mode is NotImplemented
            assert device.main_mode == 1
            assert device.heat_temp == 230
            assert device.heat_sub_mode == 2
            assert device.heat_fan_speed == 11
            assert device.cool_sub_mode == 1
            assert device.cool_fan_speed == 11
            assert device.ap_sub_mode == 1
            assert device.fan_speed_0 == 11
            assert device.temperature_unit == 1
            assert device.mood_brightness is NotImplemented
            assert device.water_refresher_usage_percentage is NotImplemented
            assert device.water_level is NotImplemented
            assert device.rssi is None
            assert device.night_light_brightness is NotImplemented
            assert device.timer_state == 0
            assert device.timer_level == 0
            assert device.timer_start_timestamp == 0
            assert device.timer_duration == 3600
            assert device.hour_format is NotImplemented


class SP4iTest(DeviceAwsTestBase):
    """Tests for the Blueair Blue Signature SP4i (blue40 / l_blue40).

    Fixture captured from a sanitized debug log shared by @Pazuzu6666
    on dahlb/ha_blueair#348. The device declares `apsubmode` but NOT
    `automode` or `nightmode`, which is the capability signature
    `ha_blueair` uses to enable Signature preset modes
    (manual_fan / auto / night / eco) via AP_SUB_MODE_LABELS.
    """

    def setUp(self):
        super().setUp()
        with open(resources.files().joinpath('device_info/SP4i.json')) as sample_file:
            info = json.load(sample_file)
        self.device_info_helper.info.update(info)

    async def test_attributes(self):

        await self.device.refresh()
        self.api.device_info.assert_awaited_with("fake-name-api", "fake-uuid")

        with assert_fully_checked(self.device) as device:

            assert device.model_name == "Blueair Blue Signature SP4i"
            assert device.hum_mode is NotImplemented
            assert device.combo_mode is NotImplemented

            assert device.pm1 is None
            assert device.pm2_5 is None
            assert device.pm10 is None
            assert device.total_voc is NotImplemented
            assert device.voc is NotImplemented
            assert device.temperature is NotImplemented
            assert device.humidity is NotImplemented
            assert device.name == "Blueair SP4i"
            assert device.firmware == "1.1.0"
            assert device.mcu_firmware == "1.1.0"
            assert device.serial_number == "112936000000000000000000"
            assert device.sku == "112936"
            assert device.hw == "l_blue40"

            assert device.standby is False
            # Signature devices do NOT declare automode/nightmode in dc:
            # this is the capability signature ha_blueair gates the
            # Signature preset modes on.
            assert device.fan_auto_mode is NotImplemented
            assert device.night_mode is NotImplemented
            assert device.germ_shield is NotImplemented
            assert device.brightness == 0
            assert device.child_lock is False
            assert device.fan_speed == 11
            assert device.filter_usage_percentage == 44
            assert device.wifi_working is True
            assert device.wick_usage_percentage is NotImplemented
            assert device.auto_regulated_humidity is NotImplemented
            assert device.water_shortage is NotImplemented
            assert device.wick_dry_mode is NotImplemented
            assert device.main_mode == 0
            assert device.heat_temp is NotImplemented
            assert device.heat_sub_mode is NotImplemented
            assert device.heat_fan_speed is NotImplemented
            assert device.cool_sub_mode is NotImplemented
            assert device.cool_fan_speed is NotImplemented
            # apsubmode=2 (auto) in the captured shadow.
            assert device.ap_sub_mode == 2
            # fsp0 is declared in `ds` (sensor schema) but NOT in `dc`
            # (control schema) on SP4i, so refresh() falls back to the
            # sensor history. The fixture's `sensordata` is empty, so
            # the latest value is None. On a live device the MQTT 5s
            # feed populates this between refreshes.
            assert device.fan_speed_0 is None
            assert device.temperature_unit is NotImplemented
            assert device.mood_brightness is NotImplemented
            assert device.water_refresher_usage_percentage is NotImplemented
            assert device.water_level is NotImplemented
            assert device.rssi is None
            assert device.night_light_brightness is NotImplemented
            assert device.timer_state == 0
            assert device.timer_level == 0
            assert device.timer_start_timestamp == 0
            assert device.timer_duration == 7200
            assert device.hour_format is NotImplemented

    async def test_mqtt_sensor_slugs(self):
        """SP4i rt5s declares the four MQTT slugs we expect.

        Note: `fsp0` is published on its OWN MQTT topic
        (`d/<id>/s/fsp0`) and is not part of the 5-second batch.
        `mqtt_sensor_slugs` only reflects `rt5s.sn`.
        """
        await self.device.refresh()
        assert self.device.mqtt_sensor_slugs == [
            "pm1", "pm2_5", "pm10", "rssi"
        ]


class Protect7470iTest(DeviceAwsTestBase):
    """Tests for protect7470i."""

    def setUp(self):
        super().setUp()
        with open(resources.files().joinpath('device_info/protect_7470i.json')) as sample_file:
            info = json.load(sample_file)
        self.device_info_helper.info.update(info)
        with open(resources.files().joinpath('device_info/protect_7470i_sensors.json')) as sample_file:
            sensors = json.load(sample_file)
        self.device_sensor_helper["mock_data"] = sensors

    async def test_attributes(self):

        await self.device.refresh()
        self.api.device_info.assert_awaited_with("fake-name-api", "fake-uuid")

        with assert_fully_checked(self.device) as device:

            assert device.model_name == "Blueair Protect 7470i"
            assert device.hum_mode is NotImplemented
            assert device.combo_mode is NotImplemented
            assert device.pm1 == 0
            assert device.pm2_5 == 0
            assert device.pm10 == 0
            assert device.total_voc == 134
            assert device.voc is NotImplemented
            assert device.temperature == 23
            assert device.humidity == 55
            assert device.name == "air filter in room"
            assert device.firmware == "2.1.1"
            assert device.mcu_firmware == "1.0.12"
            assert device.serial_number == "110582600000110110016855"
            assert device.sku == "105826"
            assert device.hw == "high_1.5"

            assert device.standby is False
            assert device.night_mode is False
            assert device.germ_shield is True
            assert device.brightness == 100
            assert device.child_lock is True
            assert device.fan_speed == 91
            assert device.fan_auto_mode is False
            assert device.filter_usage_percentage == 50
            assert device.wifi_working is True
            assert device.wick_usage_percentage is NotImplemented
            assert device.auto_regulated_humidity is NotImplemented
            assert device.water_shortage is NotImplemented
            assert device.wick_dry_mode is NotImplemented
            assert device.main_mode is NotImplemented
            assert device.heat_temp is NotImplemented
            assert device.heat_sub_mode is NotImplemented
            assert device.heat_fan_speed is NotImplemented
            assert device.cool_sub_mode is NotImplemented
            assert device.cool_fan_speed is NotImplemented
            assert device.ap_sub_mode is NotImplemented
            assert device.fan_speed_0 == 91
            assert device.temperature_unit is NotImplemented
            assert device.mood_brightness is NotImplemented
            assert device.water_refresher_usage_percentage is NotImplemented
            assert device.water_level is NotImplemented
            assert device.rssi is None
            assert device.night_light_brightness is NotImplemented
            assert device.timer_state is NotImplemented
            assert device.timer_level is NotImplemented
            assert device.timer_start_timestamp is NotImplemented
            assert device.timer_duration is NotImplemented
            assert device.hour_format is NotImplemented


class Max211iTest(DeviceAwsTestBase):
    """Tests for Max 211i."""

    def setUp(self):
        super().setUp()
        with open(resources.files().joinpath('device_info/max_211i.json')) as sample_file:
            info = json.load(sample_file)
        self.device_info_helper.info.update(info)

    async def test_attributes(self):

        await self.device.refresh()
        self.api.device_info.assert_awaited_with("fake-name-api", "fake-uuid")

        with assert_fully_checked(self.device) as device:

            assert device.model_name == "Blueair Blue Pure 211i Max"
            assert device.hum_mode is NotImplemented
            assert device.combo_mode is NotImplemented

            assert device.pm1 is None
            assert device.pm2_5 is None
            assert device.pm10 is None
            assert device.total_voc is NotImplemented
            assert device.voc is NotImplemented
            assert device.temperature is NotImplemented
            assert device.humidity is NotImplemented
            assert device.name == "Bedroom Purifier"
            assert device.firmware == "1.1.6"
            assert device.mcu_firmware == "1.1.6"
            assert device.serial_number == "111005900201111210085956"
            assert device.sku == "110059"
            assert device.hw == "nb_h_1.0"

            assert device.standby is False
            assert device.night_mode is False
            assert device.germ_shield is NotImplemented
            assert device.brightness == 0
            assert device.child_lock is False
            assert device.fan_speed == 15
            assert device.fan_auto_mode is False
            assert device.filter_usage_percentage == 55
            assert device.wifi_working is True
            assert device.wick_usage_percentage is NotImplemented
            assert device.auto_regulated_humidity is NotImplemented
            assert device.water_shortage is NotImplemented
            assert device.wick_dry_mode is NotImplemented
            assert device.main_mode is NotImplemented
            assert device.heat_temp is NotImplemented
            assert device.heat_sub_mode is NotImplemented
            assert device.heat_fan_speed is NotImplemented
            assert device.cool_sub_mode is NotImplemented
            assert device.cool_fan_speed is NotImplemented
            assert device.ap_sub_mode is NotImplemented
            assert device.fan_speed_0 is None
            assert device.temperature_unit is NotImplemented
            assert device.mood_brightness is NotImplemented
            assert device.water_refresher_usage_percentage is NotImplemented
            assert device.water_level is NotImplemented
            assert device.rssi is None
            assert device.night_light_brightness is NotImplemented
            assert device.timer_state is NotImplemented
            assert device.timer_level is NotImplemented
            assert device.timer_start_timestamp is NotImplemented
            assert device.timer_duration is NotImplemented
            assert device.hour_format is NotImplemented


class PetAirProTest(DeviceAwsTestBase):
    """Tests for PetPro."""

    def setUp(self):
        super().setUp()
        with open(resources.files().joinpath('device_info/pet_air_pro.json')) as sample_file:
            info = json.load(sample_file)
        self.device_info_helper.info.update(info)

    async def test_attributes(self):

        await self.device.refresh()
        self.api.device_info.assert_awaited_with("fake-name-api", "fake-uuid")

        with assert_fully_checked(self.device) as device:

            assert device.model_name == "Blueair PetAir Pro P3i"
            assert device.hum_mode is NotImplemented
            assert device.combo_mode is NotImplemented

            assert device.pm1 is None
            assert device.pm2_5 is None
            assert device.pm10 is None
            assert device.total_voc is NotImplemented
            assert device.voc is None
            assert device.temperature is NotImplemented
            assert device.humidity is NotImplemented
            assert device.name == "PetAir Pro"
            assert device.firmware == "1.0.3"
            assert device.mcu_firmware == "1.0.3"
            assert device.serial_number == "111279300002313310000090"
            assert device.sku == "112793"
            assert device.hw == "pet20"

            assert device.standby is False
            assert device.night_mode is NotImplemented
            assert device.germ_shield is NotImplemented
            assert device.brightness == 100.0
            assert device.child_lock is False
            assert device.fan_speed == 91.0
            assert device.fan_auto_mode is NotImplemented
            assert device.filter_usage_percentage == 5.0
            assert device.wifi_working is False
            assert device.wick_usage_percentage is NotImplemented
            assert device.auto_regulated_humidity is NotImplemented
            assert device.water_shortage is NotImplemented
            assert device.wick_dry_mode is NotImplemented
            assert device.main_mode == 0.0
            assert device.heat_temp is NotImplemented
            assert device.heat_sub_mode is NotImplemented
            assert device.heat_fan_speed is NotImplemented
            assert device.cool_sub_mode is NotImplemented
            assert device.cool_fan_speed is NotImplemented
            assert device.ap_sub_mode == 1.0
            assert device.fan_speed_0 is None
            assert device.temperature_unit is NotImplemented
            assert device.mood_brightness is NotImplemented
            assert device.water_refresher_usage_percentage is NotImplemented
            assert device.water_level is NotImplemented
            assert device.rssi is None
            assert device.night_light_brightness is NotImplemented
            assert device.timer_state == 0
            assert device.timer_level == 0
            assert device.timer_start_timestamp == 0
            assert device.timer_duration == 7200
            assert device.hour_format is NotImplemented


class TwoInOneTest(DeviceAwsTestBase):
    """Tests for TwoInOne."""

    def setUp(self):
        super().setUp()
        with open(resources.files().joinpath('device_info/two_in_one.json')) as sample_file:
            info = json.load(sample_file)
        self.device_info_helper.info.update(info)

    async def test_attributes(self):

        await self.device.refresh()
        self.api.device_info.assert_awaited_with("fake-name-api", "fake-uuid")

        with assert_fully_checked(self.device) as device:

            assert device.model_name == "Blueair Air Purifier + Humidifier 2-in-1 Pro"
            assert device.hum_mode is NotImplemented
            assert device.combo_mode is NotImplemented

            assert device.pm1 is None
            assert device.pm2_5 is None
            assert device.pm10 is None
            assert device.total_voc is NotImplemented
            assert device.voc is NotImplemented
            assert device.temperature is None
            assert device.humidity is None
            assert device.name == "Master Bedroom"
            assert device.firmware == "1.1.0"
            assert device.mcu_firmware == "1.1.0"
            assert device.serial_number == "111382500002313310004087"
            assert device.sku == "113825"
            assert device.hw == "cmb2in1_ii"

            assert device.standby is False
            assert device.night_mode is NotImplemented
            assert device.germ_shield is NotImplemented
            assert device.brightness == 0
            assert device.child_lock is False
            assert device.fan_speed == 50
            assert device.fan_auto_mode is NotImplemented
            assert device.filter_usage_percentage == 0
            assert device.wifi_working is True
            assert device.wick_usage_percentage == 0
            assert device.auto_regulated_humidity == 55.0
            assert device.water_shortage is NotImplemented
            assert device.wick_dry_mode is False
            assert device.main_mode == 5
            assert device.heat_temp is NotImplemented
            assert device.heat_sub_mode is NotImplemented
            assert device.heat_fan_speed is NotImplemented
            assert device.cool_sub_mode is NotImplemented
            assert device.cool_fan_speed is NotImplemented
            assert device.ap_sub_mode == 1.0
            assert device.fan_speed_0 is None
            assert device.temperature_unit is NotImplemented
            assert device.mood_brightness == 0
            assert device.water_refresher_usage_percentage == 0
            assert device.water_level == 75.0
            assert device.rssi is None
            assert device.night_light_brightness is NotImplemented
            assert device.timer_state == 0
            assert device.timer_level == 0
            assert device.timer_start_timestamp == 0
            assert device.timer_duration == 1800
            assert device.hour_format is NotImplemented


class Combo2in1DH3iTest(DeviceAwsTestBase):
    """Tests for the DH3i 2-in-1 Purify + Humidify combo (hw='s_cmb2in1').

    This device exposes independent humidification (``hum_mode``) that is
    separate from whole-device power (``standby``), plus a ``combo_mode``
    preset selector. See https://github.com/dahlb/ha_blueair/issues/241.
    """

    def setUp(self):
        super().setUp()
        with open(resources.files().joinpath('device_info/two_in_one_dh3i.json')) as sample_file:
            info = json.load(sample_file)
        self.device_info_helper.info.update(info)

    async def test_attributes(self):

        await self.device.refresh()
        self.api.device_info.assert_awaited_with("fake-name-api", "fake-uuid")

        with assert_fully_checked(self.device) as device:

            assert device.model_name == "Blueair 2-in-1 Purify + Humidify"
            assert device.hum_mode is True
            assert device.combo_mode == 2

            assert device.pm1 is NotImplemented
            assert device.pm2_5 is NotImplemented
            assert device.pm10 is NotImplemented
            assert device.total_voc is NotImplemented
            assert device.voc is NotImplemented
            assert device.temperature is NotImplemented
            assert device.humidity is NotImplemented
            assert device.name == "Master Bedroom"
            assert device.firmware == "1.0.6"
            assert device.mcu_firmware == "1.0.6"
            assert device.serial_number == "111181100201111210007280"
            assert device.sku == "111811"
            assert device.hw == "s_cmb2in1"

            assert device.standby is False
            assert device.night_mode is NotImplemented
            assert device.germ_shield is NotImplemented
            assert device.brightness == 50
            assert device.child_lock is True
            assert device.fan_speed == 11
            assert device.fan_auto_mode is NotImplemented
            assert device.filter_usage_percentage == 24
            assert device.wifi_working is True
            assert device.wick_usage_percentage == 47
            assert device.auto_regulated_humidity == 40
            assert device.water_shortage is NotImplemented
            assert device.wick_dry_mode is False
            assert device.main_mode is NotImplemented
            assert device.heat_temp is NotImplemented
            assert device.heat_sub_mode is NotImplemented
            assert device.heat_fan_speed is NotImplemented
            assert device.cool_sub_mode is NotImplemented
            assert device.cool_fan_speed is NotImplemented
            assert device.ap_sub_mode is NotImplemented
            assert device.fan_speed_0 is NotImplemented
            assert device.temperature_unit is NotImplemented
            assert device.mood_brightness is NotImplemented
            assert device.water_refresher_usage_percentage is NotImplemented
            assert device.water_level == 1
            assert device.rssi is NotImplemented
            assert device.night_light_brightness is NotImplemented
            assert device.timer_state == 0
            assert device.timer_level == 0
            assert device.timer_start_timestamp == 0
            assert device.timer_duration == 7200
            assert device.hour_format is NotImplemented


class NullValueTest(DeviceAwsTestBase):
    """Tests for TwoInOne."""

    def setUp(self):
        super().setUp()
        with open(resources.files().joinpath('device_info/null.json')) as sample_file:
            info = json.load(sample_file)
        self.device_info_helper.info.update(info)

    async def test_attributes(self):

        await self.device.refresh()
        self.api.device_info.assert_awaited_with("fake-name-api", "fake-uuid")

        with assert_fully_checked(self.device) as device:

            assert device.model_name == "Blueair Mini Restful"

            assert device.hum_mode is NotImplemented
            assert device.combo_mode is NotImplemented

            assert device.pm1 is NotImplemented
            assert device.pm2_5 is NotImplemented
            assert device.pm10 is NotImplemented
            assert device.total_voc is NotImplemented
            assert device.voc is NotImplemented
            assert device.temperature is NotImplemented
            assert device.humidity is NotImplemented
            assert device.name == "Bedroom Air Purifier"
            assert device.firmware == "1.0.1"
            assert device.mcu_firmware == "1.2.9"
            assert device.serial_number == "111383600201111210001674"
            assert device.sku == "113836"
            assert device.hw == "mrest"

            assert device.standby is False
            assert device.night_mode is NotImplemented
            assert device.germ_shield is NotImplemented
            assert device.brightness == 40
            assert device.child_lock is False
            assert device.fan_speed == 51
            assert device.fan_auto_mode is NotImplemented
            assert device.filter_usage_percentage == 3
            assert device.wifi_working is True
            assert device.wick_usage_percentage is NotImplemented
            assert device.auto_regulated_humidity is NotImplemented
            assert device.water_shortage is NotImplemented
            assert device.wick_dry_mode is NotImplemented
            assert device.main_mode == 0
            assert device.heat_temp is NotImplemented
            assert device.heat_sub_mode is NotImplemented
            assert device.heat_fan_speed is NotImplemented
            assert device.cool_sub_mode is NotImplemented
            assert device.cool_fan_speed is NotImplemented
            assert device.ap_sub_mode == 1
            assert device.fan_speed_0 is None
            assert device.temperature_unit is NotImplemented
            assert device.mood_brightness is NotImplemented
            assert device.water_refresher_usage_percentage is NotImplemented
            assert device.water_level is NotImplemented
            assert device.rssi is None
            assert device.night_light_brightness == 0
            assert device.timer_state == 0
            assert device.timer_level == 0
            assert device.timer_start_timestamp == 0
            assert device.timer_duration == 7200
            assert device.hour_format is False


class MiniRestfulAlarmTest(DeviceAwsTestBase):
    """Tests for Mini Restful with active sunrise alarm.

    When a sunrise alarm is active, the alarm1 state field has a vj
    value that is a JSON dict instead of the string "null". This
    previously crashed SensorPack with an AssertionError.
    See: https://github.com/dahlb/ha_blueair/issues/334
    """

    def setUp(self):
        super().setUp()
        with open(resources.files().joinpath('device_info/mini_restful.json')) as sample_file:
            info = json.load(sample_file)
        self.device_info_helper.info.update(info)

    async def test_refresh_with_active_alarm(self):
        """refresh() should not crash when alarm1 has a dict vj value."""
        await self.device.refresh()

        with assert_fully_checked(self.device) as device:
            assert device.model_name == "Blueair Mini Restful"
            assert device.hw == "mrest"
            assert device.hum_mode is NotImplemented
            assert device.combo_mode is NotImplemented
            assert device.brightness == 40
            assert device.fan_speed == 51
            assert device.standby is False
            assert device.child_lock is False
            assert device.filter_usage_percentage == 3
            assert device.main_mode == 0
            assert device.ap_sub_mode == 1
            assert device.wifi_working is True
            assert device.sku == "113836"
            assert device.firmware == "1.0.1"
            assert device.mcu_firmware == "1.2.9"
            assert device.serial_number == "111383600201111210001674"
            assert device.name == "Bedroom Air Purifier"

            assert device.pm1 is NotImplemented
            assert device.pm2_5 is NotImplemented
            assert device.pm10 is NotImplemented
            assert device.total_voc is NotImplemented
            assert device.voc is NotImplemented
            assert device.temperature is NotImplemented
            assert device.humidity is NotImplemented
            assert device.night_mode is NotImplemented
            assert device.germ_shield is NotImplemented
            assert device.fan_auto_mode is NotImplemented
            assert device.wick_usage_percentage is NotImplemented
            assert device.auto_regulated_humidity is NotImplemented
            assert device.water_shortage is NotImplemented
            assert device.wick_dry_mode is NotImplemented
            assert device.heat_temp is NotImplemented
            assert device.heat_sub_mode is NotImplemented
            assert device.heat_fan_speed is NotImplemented
            assert device.cool_sub_mode is NotImplemented
            assert device.cool_fan_speed is NotImplemented
            assert device.fan_speed_0 is None
            assert device.temperature_unit is NotImplemented
            assert device.mood_brightness is NotImplemented
            assert device.water_refresher_usage_percentage is NotImplemented
            assert device.water_level is NotImplemented
            assert device.rssi is None
            assert device.night_light_brightness == 0
            assert device.timer_state == 0
            assert device.timer_level == 0
            assert device.timer_start_timestamp == 0
            assert device.timer_duration == 7200
            assert device.hour_format is False


class OnlineStateTest(DeviceAwsTestBase):
    """Tests for wifi_working behavior.

    The Blueair cloud API frequently reports online=False even when the
    device is fully operational (github.com/dahlb/ha_blueair/issues/287).
    wifi_working faithfully reports the API value but should NOT be used
    to gate entity availability.
    """

    def setUp(self):
        super().setUp()
        fake = {"n": "n", "v": 0}
        ir.query_json(self.device_info_helper.info, "configuration.dc").update({
            "standby": fake,
            "fanspeed": fake,
        })

    async def test_online_explicit_true(self):
        """Explicit online=True in states → wifi_working=True."""
        self.device_info_helper.info["states"] = [
            {"n": "online", "vb": True},
            {"n": "standby", "vb": False},
            {"n": "fanspeed", "v": 11},
        ]
        await self.device.refresh()
        assert self.device.wifi_working is True

    async def test_online_explicit_false(self):
        """Explicit online=False in states → wifi_working=False.

        The cloud API frequently returns online=False even for active
        devices. Consumers should not gate availability on this field.
        """
        self.device_info_helper.info["states"] = [
            {"n": "online", "vb": False},
            {"n": "standby", "vb": False},
            {"n": "fanspeed", "v": 11},
        ]
        await self.device.refresh()
        assert self.device.wifi_working is False

    async def test_online_missing_defaults_true(self):
        """Missing online field → wifi_working defaults to True."""
        self.device_info_helper.info["states"] = [
            {"n": "standby", "vb": False},
            {"n": "fanspeed", "v": 11},
        ]
        await self.device.refresh()
        assert self.device.wifi_working is True


class ModelNameTest(DeviceAwsTestBase):
    """Tests for model_name property (SKU dict lookup)."""

    async def test_known_sku_from_dict(self):
        """SKU in the dict returns the human-readable name."""
        ir.query_json(self.device_info_helper.info, "configuration.di")["sku"] = "111582"
        await self.device.refresh()
        assert self.device.model_name == "Blueair Blue Pure 511i Max"

    async def test_another_known_sku(self):
        """Another SKU in the dict returns the correct name."""
        ir.query_json(self.device_info_helper.info, "configuration.di")["sku"] = "110829"
        await self.device.refresh()
        assert self.device.model_name == "Blueair Blue Pure 311i Max"

    async def test_unknown_sku(self):
        """Completely unknown SKU falls back to 'Unknown (sku)'."""
        ir.query_json(self.device_info_helper.info, "configuration.di")["sku"] = "999999"
        await self.device.refresh()
        assert self.device.model_name == f"{UNKNOWN_MODEL} (999999)"

    async def test_no_sku(self):
        """Missing SKU (NotImplemented) falls back gracefully."""
        await self.device.refresh()
        assert UNKNOWN_MODEL in self.device.model_name

    async def test_sp4i_sku_known(self):
        """SP4i SKU 112936 resolves to Blueair Blue Signature SP4i.

        Regression for ha_blueair#348 / #261 — the Signature/SP4i fan
        preset support depends on correct SKU resolution so the device
        appears as a Signature device in HA's device registry.
        """
        ir.query_json(self.device_info_helper.info, "configuration.di")["sku"] = "112936"
        await self.device.refresh()
        assert self.device.model_name == "Blueair Blue Signature SP4i"


class ApSubModeLabelsTest(TestCase):
    """Regression tests for the AP_SUB_MODE_LABELS public constant.

    Consumed by ha_blueair's fan platform to expose Signature/SP4i fan
    preset modes (ha_blueair#348, #261). Changing these labels is a
    breaking API change for downstream integrations — keep this test
    in sync with const expectations on the consumer side.

    AP_SUB_MODE_LABELS is intentionally Signature-only. It is NOT a
    global decoder for the `apsubmode` shadow slug: T10i (cmb3in1)
    uses values 1/2 in a different namespace and pet_air_pro / 2-in-1
    declare the field without consuming it. See the constant's
    docstring in src/blueair_api/device_aws.py.
    """

    def test_labels_match_known_signature_mapping(self):
        from blueair_api.device_aws import AP_SUB_MODE_LABELS
        assert AP_SUB_MODE_LABELS == {
            0: "manual_fan",
            2: "auto",
            3: "night",
            4: "eco",
        }

    def test_labels_are_unique(self):
        """Two values mapping to the same preset would silently break
        the consumer's reverse lookup (label -> apsubmode value)."""
        from blueair_api.device_aws import AP_SUB_MODE_LABELS
        assert len(set(AP_SUB_MODE_LABELS.values())) == len(AP_SUB_MODE_LABELS)

    def test_labels_are_well_formed(self):
        """Keys must be ints (the apsubmode wire type) and values must
        be non-empty strings (HA preset_modes are str-typed)."""
        from blueair_api.device_aws import AP_SUB_MODE_LABELS
        assert all(isinstance(k, int) for k in AP_SUB_MODE_LABELS)
        assert all(
            isinstance(v, str) and v
            for v in AP_SUB_MODE_LABELS.values()
        )

    def test_publicly_importable_from_package_root(self):
        """Phase 3 (ha_blueair#353) and current ha_blueair#348 consumers
        should be able to import the constant from the package root,
        not reach into device_aws."""
        import blueair_api
        from blueair_api.device_aws import AP_SUB_MODE_LABELS
        assert blueair_api.AP_SUB_MODE_LABELS is AP_SUB_MODE_LABELS


class MqttSensorSlugsTest(DeviceAwsTestBase):
    """Tests that mqtt_sensor_slugs is populated from rt5s.sn."""

    async def test_slugs_populated_from_rt5s(self):
        ir.query_json(self.device_info_helper.info, "configuration.ds")["rt5s"] = {
            "sn": ["pm2_5", "fsp0", "rssi", "pm1", "pm10"],
            "tn": "d/fake-uuid/s/5s", "ttl": 1200,
            "n": "rt5s", "ot": "RT5s", "e": False, "i": 5000, "fe": True,
        }
        await self.device.refresh()
        assert self.device.mqtt_sensor_slugs == ["pm2_5", "fsp0", "rssi", "pm1", "pm10"]

    async def test_slugs_empty_when_no_rt5s(self):
        await self.device.refresh()
        assert self.device.mqtt_sensor_slugs == []

    async def test_humidifier_slugs(self):
        ir.query_json(self.device_info_helper.info, "configuration.ds")["rt5s"] = {
            "sn": ["t", "h", "rssi"],
            "tn": "d/fake-uuid/s/5s", "ttl": -1,
            "n": "rt5s", "ot": "RT5s", "e": False, "i": 0, "fe": True,
        }
        await self.device.refresh()
        assert self.device.mqtt_sensor_slugs == ["t", "h", "rssi"]

    async def test_slugs_robust_to_malformed_rt5s(self):
        """Defensive parsing: if rt5s.sn is missing or wrong-shaped,
        mqtt_sensor_slugs degrades to an empty list rather than
        crashing the refresh pipeline.

        Note: cases where rt5s itself is malformed enough to fail the
        ds-schema parse upstream (rt5s = null, rt5s = []) are handled
        by intermediate_representation_aws.parse_json — not exercised
        here.  This test covers the path where parse_json succeeds but
        the rt5s.sn array is missing or the wrong type.
        """
        ds = ir.query_json(self.device_info_helper.info, "configuration.ds")
        well_formed_envelope = {
            "tn": "d/fake-uuid/s/5s", "ttl": -1,
            "n": "rt5s", "ot": "RT5s", "e": False, "i": 0, "fe": True,
        }

        # rt5s present but missing 'sn' entirely
        ds["rt5s"] = dict(well_formed_envelope)
        await self.device.refresh()
        assert self.device.mqtt_sensor_slugs == []

        # rt5s.sn is a string instead of a list
        ds["rt5s"] = {**well_formed_envelope, "sn": "rssi"}
        await self.device.refresh()
        assert self.device.mqtt_sensor_slugs == []

        # rt5s.sn contains non-string entries — coerce to str so the
        # list-of-str invariant holds for downstream code.
        ds["rt5s"] = {**well_formed_envelope, "sn": ["rssi", 42, None]}
        await self.device.refresh()
        assert self.device.mqtt_sensor_slugs == ["rssi", "42", "None"]


class ApplySensorDataTest(DeviceAwsTestBase):
    """Tests for DeviceAws.apply_sensor_data()."""

    async def test_known_fields_mapped(self):
        await self.device.refresh()
        self.device.apply_sensor_data({
            "pm1": 5.0, "pm2_5": 12.0, "pm10": 20.0, "fsp0": 37.0,
        })
        assert self.device.pm1 == 5
        assert self.device.pm2_5 == 12
        assert self.device.pm10 == 20
        assert self.device.fan_speed_0 == 37

    async def test_renamed_fields_mapped(self):
        await self.device.refresh()
        self.device.apply_sensor_data({"t": 22.0, "h": 55.0, "tVOC": 100.0, "voc": 42.0})
        assert self.device.temperature == 22
        assert self.device.humidity == 55
        assert self.device.total_voc == 100
        assert self.device.voc == 42

    async def test_unknown_fields_go_to_extra_sensors(self):
        await self.device.refresh()
        # Use a slug not in MQTT_SENSOR_FIELD_MAP (rssi is now first-class).
        self.device.apply_sensor_data({"unknownsensor": 99.5, "pm2_5": 3.0})
        assert self.device.pm2_5 == 3
        assert self.device.extra_sensors == {"unknownsensor": 99.5}

    async def test_rssi_is_first_class(self):
        """rssi is mapped to device.rssi, not extra_sensors."""
        await self.device.refresh()
        self.device.apply_sensor_data({"rssi": -45.0})
        assert self.device.rssi == -45
        assert "rssi" not in self.device.extra_sensors

    async def test_empty_sensors(self):
        await self.device.refresh()
        self.device.apply_sensor_data({})
        assert self.device.extra_sensors == {}

    async def test_bad_value_logs_and_skips(self):
        """Non-numeric sensor value is logged and the rest of the batch lands."""
        await self.device.refresh()
        with self.assertLogs("blueair_api.device_aws", level="WARNING") as cm:
            self.device.apply_sensor_data(
                {"pm2_5": "not-a-number", "pm1": 5.0}
            )
        # Bad value skipped, good value applied.
        assert self.device.pm1 == 5
        assert any("pm2_5" in m for m in cm.output)


class ApplyStateChangeTest(DeviceAwsTestBase):
    """Tests for DeviceAws.apply_state_change()."""

    async def test_known_state_fields(self):
        await self.device.refresh()
        self.device.apply_state_change({
            "fanspeed": 51,
            "standby": False,
            "brightness": 64,
        })
        assert self.device.fan_speed == 51
        assert self.device.standby is False
        assert self.device.brightness == 64

    async def test_all_shadow_fields(self):
        await self.device.refresh()
        self.device.apply_state_change({
            "nightmode": True,
            "germshield": True,
            "childlock": True,
            "automode": True,
            "filterusage": 42,
            "nlbrightness": 80,
            "wickusage": 30,
            "wickdrys": True,
            "autorh": 50,
            "wshortage": False,
            "wlevel": 3,
            "fsp0": 64,
            "tu": 1,
        })
        assert self.device.night_mode is True
        assert self.device.germ_shield is True
        assert self.device.child_lock is True
        assert self.device.fan_auto_mode is True
        assert self.device.filter_usage_percentage == 42
        assert self.device.mood_brightness == 80
        assert self.device.wick_usage_percentage == 30
        assert self.device.wick_dry_mode is True
        assert self.device.auto_regulated_humidity == 50
        assert self.device.water_shortage is False
        assert self.device.water_level == 3
        assert self.device.fan_speed_0 == 64
        assert self.device.temperature_unit == 1

    async def test_humidifier_fan_speed_remapped(self):
        """Humidifier devices remap raw fan speed 11/37/64 → 1/2/3."""
        ir.query_json(self.device_info_helper.info, "configuration.di")["hw"] = "hum2_l"
        await self.device.refresh()

        self.device.apply_state_change({"fanspeed": 11})
        assert self.device.fan_speed == 1

        self.device.apply_state_change({"fanspeed": 37})
        assert self.device.fan_speed == 2

        self.device.apply_state_change({"fanspeed": 64})
        assert self.device.fan_speed == 3

    async def test_non_humidifier_fan_speed_not_remapped(self):
        ir.query_json(self.device_info_helper.info, "configuration.di")["hw"] = "nb_h_1.0"
        await self.device.refresh()
        self.device.apply_state_change({"fanspeed": 37})
        assert self.device.fan_speed == 37

    async def test_unknown_shadow_fields_ignored(self):
        await self.device.refresh()
        self.device.apply_state_change({"unknownfield": 99, "brightness": 50})
        assert self.device.brightness == 50

    async def test_shadow_map_typo_logs_error_and_continues(self):
        """A SHADOW_FIELD_MAP entry pointing at a non-existent attribute
        logs ERROR but the rest of the batch still applies.

        Guards against typos in the map (e.g. 'brightness' -> 'birghtness')
        from silently dropping otherwise-valid updates.
        """
        from blueair_api import device_aws as device_aws_module
        await self.device.refresh()
        with (
            mock.patch.dict(
                device_aws_module.SHADOW_FIELD_MAP,
                {"bogus": "no_such_attr"},
            ),
            self.assertLogs("blueair_api.device_aws", level="ERROR") as cm,
        ):
            self.device.apply_state_change({"bogus": 1, "brightness": 50})
        assert self.device.brightness == 50
        assert any("no_such_attr" in msg for msg in cm.output)


class MiniRestfulShadowTest(DeviceAwsTestBase):
    """Tests for Mini Restful sunrise / timer fields via shadow updates."""

    async def test_sunrise_and_clock_via_shadow(self):
        """nlstepless and hourformat propagate via apply_state_change."""
        await self.device.refresh()
        self.device.apply_state_change({"nlstepless": 75, "hourformat": True})
        assert self.device.night_light_brightness == 75
        assert self.device.hour_format is True

    async def test_timer_via_shadow(self):
        """timstate / timl / timts / timdur propagate via apply_state_change."""
        await self.device.refresh()
        self.device.apply_state_change({
            "timstate": 1,
            "timl": 7200,
            "timts": 1773716704,
            "timdur": 7200,
        })
        assert self.device.timer_state == 1
        assert self.device.timer_level == 7200
        assert self.device.timer_start_timestamp == 1773716704
        assert self.device.timer_duration == 7200

    async def test_refresh_populates_timer_fields(self):
        """Loading the mini_restful fixture populates timer/sunrise attrs from REST."""
        with open(resources.files().joinpath('device_info/mini_restful.json')) as sample_file:
            info = json.load(sample_file)
        self.device_info_helper.info.update(info)
        await self.device.refresh()
        assert self.device.night_light_brightness == 0
        assert self.device.timer_state == 0
        assert self.device.timer_level == 0
        assert self.device.timer_start_timestamp == 0
        assert self.device.timer_duration == 7200
        assert self.device.hour_format is False


class MiniRestfulSetterTest(DeviceAwsTestBase):
    """Tests for the new sunrise / timer / clock setters."""

    def setUp(self):
        super().setUp()
        # Populate dc so refresh() will read the states back.
        fake = {"n": "n", "v": 0}
        ir.query_json(self.device_info_helper.info, "configuration.dc").update({
            "nlstepless": fake,
            "timdur": fake,
            "hourformat": fake,
        })

    async def test_set_night_light_brightness(self):
        self.device.night_light_brightness = None
        await self.device.set_night_light_brightness(75)
        assert self.device.night_light_brightness == 75

        await self.device.set_night_light_brightness(50)
        self.device.night_light_brightness = None
        await self.device.refresh()
        assert self.device.night_light_brightness == 50

    async def test_set_timer_duration(self):
        self.device.timer_duration = None
        await self.device.set_timer_duration(3600)
        assert self.device.timer_duration == 3600

        await self.device.set_timer_duration(7200)
        self.device.timer_duration = None
        await self.device.refresh()
        assert self.device.timer_duration == 7200

    async def test_set_hour_format(self):
        self.device.hour_format = None
        await self.device.set_hour_format(True)
        assert self.device.hour_format is True

        await self.device.set_hour_format(False)
        self.device.hour_format = None
        await self.device.refresh()
        assert self.device.hour_format is False


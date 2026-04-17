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
from unittest import IsolatedAsyncioTestCase

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
        self.device.apply_sensor_data({"rssi": -45.0, "pm2_5": 3.0})
        assert self.device.pm2_5 == 3
        assert self.device.extra_sensors == {"rssi": -45.0}

    async def test_empty_sensors(self):
        await self.device.refresh()
        self.device.apply_sensor_data({})
        assert self.device.extra_sensors == {}


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

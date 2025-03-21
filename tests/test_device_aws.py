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
from blueair_api.model_enum import ModelEnum
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

            assert device.model == ModelEnum.UNKNOWN

            assert device.pm1 is NotImplemented
            assert device.pm2_5 is NotImplemented
            assert device.pm10 is NotImplemented
            assert device.tVOC is NotImplemented
            assert device.temperature is NotImplemented
            assert device.humidity is NotImplemented
            assert device.name is NotImplemented
            assert device.firmware is NotImplemented
            assert device.mcu_firmware is NotImplemented
            assert device.serial_number is NotImplemented
            assert device.sku is NotImplemented

            assert device.standby is NotImplemented
            assert device.night_mode is NotImplemented
            assert device.germ_shield is NotImplemented
            assert device.brightness is NotImplemented
            assert device.child_lock is NotImplemented
            assert device.fan_speed is NotImplemented
            assert device.fan_auto_mode is NotImplemented
            assert device.filter_usage_percentage is NotImplemented
            assert device.wifi_working is None
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

            assert device.model == ModelEnum.HUMIDIFIER_H35I

            assert device.pm1 is NotImplemented
            assert device.pm2_5 is NotImplemented
            assert device.pm10 is NotImplemented
            assert device.tVOC is NotImplemented
            assert device.temperature == 19
            assert device.humidity == 50
            assert device.name == "Bedroom"
            assert device.firmware == "1.0.1"
            assert device.mcu_firmware == "1.0.1"
            assert device.serial_number == "111163300201110210004036"
            assert device.sku == "111633"

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
            assert device.fan_speed_0 is NotImplemented
            assert device.temperature_unit is NotImplemented


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

            assert device.model == ModelEnum.MAX_311I

            assert device.pm1 is NotImplemented
            assert device.pm2_5 == 0
            assert device.pm10 is NotImplemented
            assert device.tVOC is NotImplemented
            assert device.temperature is NotImplemented
            assert device.humidity is NotImplemented
            assert device.name == "Loft"
            assert device.firmware == "1.0.4"
            assert device.mcu_firmware == "1.0.4"
            assert device.serial_number == "111082900302313210005018"
            assert device.sku == "110829"

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
            assert device.fan_speed_0 is NotImplemented
            assert device.temperature_unit is NotImplemented


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

            assert device.model == ModelEnum.T10I

            assert device.pm1 is NotImplemented
            assert device.pm2_5 == 0
            assert device.pm10 is NotImplemented
            assert device.tVOC is NotImplemented
            assert device.temperature == 18
            assert device.humidity == 28
            assert device.name == "Allen's Office"
            assert device.firmware == "1.0.4"
            assert device.mcu_firmware == "1.0.4"
            assert device.serial_number == "111212400002313210001961"
            assert device.sku == "112124"

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


class Protect7470iTest(DeviceAwsTestBase):
    """Tests for protect7470i."""

    def setUp(self):
        super().setUp()
        with open(resources.files().joinpath('device_info/protect_7470i.json')) as sample_file:
            info = json.load(sample_file)
        self.device_info_helper.info.update(info)

    async def test_attributes(self):

        await self.device.refresh()
        self.api.device_info.assert_awaited_with("fake-name-api", "fake-uuid")

        with assert_fully_checked(self.device) as device:

            assert device.model == ModelEnum.PROTECT_7470I

            assert device.pm1 == 0
            assert device.pm2_5 == 0
            assert device.pm10 == 0
            assert device.tVOC == 59
            assert device.temperature == 23
            assert device.humidity == 46
            assert device.name == "air filter in room"
            assert device.firmware == "2.1.1"
            assert device.mcu_firmware == "1.0.12"
            assert device.serial_number == "110582600000110110016855"
            assert device.sku == "105826"

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
            assert device.fan_speed_0 is NotImplemented
            assert device.temperature_unit is NotImplemented


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

            assert device.model == ModelEnum.MAX_211I

            assert device.pm1 == 0
            assert device.pm2_5 == 0
            assert device.pm10 == 0
            assert device.tVOC is NotImplemented
            assert device.temperature is NotImplemented
            assert device.humidity is NotImplemented
            assert device.name == "Bedroom Purifier"
            assert device.firmware == "1.1.6"
            assert device.mcu_firmware == "1.1.6"
            assert device.serial_number == "111005900201111210085956"
            assert device.sku == "110059"

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
            assert device.fan_speed_0 is NotImplemented
            assert device.temperature_unit is NotImplemented

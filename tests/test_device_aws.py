"""Tests for DeviceAws.

Here is one way to run it:

First install the package in developer mode

    $ pip install -e .

Then use pytest to drive the tests

    $ pytest tests
"""

from unittest import mock
from unittest import IsolatedAsyncioTestCase

from blueair_api.device_aws import DeviceAws
from blueair_api import http_aws_blueair


class DeviceAwsTestBase(IsolatedAsyncioTestCase):

    def setUp(self):
        patcher = mock.patch('blueair_api.http_aws_blueair.HttpAwsBlueair', autospec=True)
        self.api_class = patcher.start()
        self.addCleanup(patcher.stop)
        self.api = self.api_class(username="fake-username", password="fake-password")

        self.device = DeviceAws(self.api, name_api="fake-name-api", uuid="fake-uuid", name="fake-name",
mac="fake-mac", type_name='fake-type-name')

        # TODO: Consider lifting these methods into a fake api class.
        self.info = {"sensordata": {}, "states": []}
        async def device_info(*args, **kwargs):
            return self.info
        self.api.device_info.side_effect = device_info

        async def set_device_info(device_uuid, service_name, action_verb, action_value):
            # this function seems to be only updating the states consider rename the method.
            # action_verb seems to be a type annotation:
            # c.f. senml: https://www.rfc-editor.org/rfc/rfc8428.html#section-5
            for state in self.info['states']:
                if state['n'] == service_name:
                    break
            else:
                state = {'n': service_name}
                self.info['states'].append(state)
            state[action_verb] = action_value

        self.api.set_device_info.side_effect = set_device_info


class UnavailableDeviceAwsTest(DeviceAwsTestBase):
    """Tests for a fake, all attrs are unavailable device.

    Other device types shall override setUp and populate self.info with the 
    golden dataset.
    """

    async def test_attributes(self):

        await self.device.refresh()
        self.api.device_info.assert_awaited_with("fake-name-api", "fake-uuid")

        device = self.device

        assert device.pm1 is None
        assert device.pm2_5 is None
        assert device.pm10 is None
        assert device.tVOC is None
        assert device.temperature is None
        assert device.humidity is None
        assert device.name is None
        assert device.firmware is None
        assert device.mcu_firmware is None
        assert device.serial_number is None
        assert device.sku is None

        assert device.running is False
        assert device.night_mode is None
        assert device.germ_shield is None
        assert device.brightness is None
        assert device.child_lock is None
        assert device.fan_speed is None
        assert device.fan_auto_mode is None
        assert device.filter_usage is None
        assert device.wifi_working is None
        assert device.wick_usage is None
        assert device.auto_regulated_humidity is None
        assert device.water_shortage is None

    async def test_set_brightness(self):
        await self.device.set_brightness(30)
        # local cache should work
        assert self.device.brightness == 30

        self.device.brightness == None
        await self.device.refresh()
        assert self.device.brightness == 30



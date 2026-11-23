"""Tests for the legacy Device setters."""

from typing import Any
from unittest import mock

import pytest

from blueair_api.device import Device
from blueair_api.errors import ServerError

# Setter, value written, attribute it stores, value stored.
SETTERS = [
    ("set_fan_speed", "2", "fan_speed", 2),
    ("set_brightness", 3, "brightness", 3),
    ("set_child_lock", True, "child_lock", True),
    ("set_fan_auto_mode", True, "fan_auto_mode", True),
]


def make_device(api: Any) -> Device:
    """Return a legacy device with known starting values.

    Args:
        api: Stand-in for HttpBlueair.

    Returns:
        Device: The device.
    """
    return Device(
        api=api,
        uuid="fake-uuid",
        name="fake-name",
        brightness=1,
        child_lock=False,
        fan_speed=1,
        fan_auto_mode=False,
    )


def test_every_setter_is_covered() -> None:
    """Keep SETTERS in step with Device's setters."""
    setters = {name for name in dir(Device) if name.startswith("set_")}

    assert setters == {setter for setter, *_ in SETTERS}


@pytest.mark.parametrize(("setter", "value", "attribute", "stored"), SETTERS)
async def test_setters_store_the_value_once_the_api_accepts_it(
    setter: str, value: Any, attribute: str, stored: Any
) -> None:
    """Store the new value and notify callbacks after a successful call."""
    device = make_device(mock.AsyncMock())
    callback = mock.Mock()
    device.register_callback(callback)

    await getattr(device, setter)(value)

    getattr(device.api, setter).assert_awaited_once_with("fake-uuid", value)
    assert getattr(device, attribute) == stored
    callback.assert_called_once_with()


@pytest.mark.parametrize(("setter", "value", "attribute", "stored"), SETTERS)
async def test_failed_setters_keep_the_last_known_value(
    setter: str, value: Any, attribute: str, stored: Any
) -> None:
    """Keep the device's last known state when the API call fails."""
    api = mock.AsyncMock()
    getattr(api, setter).side_effect = ServerError("unavailable")
    device = make_device(api)
    before = getattr(device, attribute)
    callback = mock.Mock()
    device.register_callback(callback)

    with pytest.raises(ServerError):
        await getattr(device, setter)(value)

    assert getattr(device, attribute) == before
    callback.assert_not_called()


async def test_invalid_fan_speeds_are_rejected_before_calling_the_api() -> None:
    """Reject a fan speed that isn't a number without sending anything."""
    api = mock.AsyncMock()
    device = make_device(api)

    with pytest.raises(ValueError, match="invalid literal"):
        await device.set_fan_speed("fast")

    api.set_fan_speed.assert_not_awaited()
    assert device.fan_speed == 1

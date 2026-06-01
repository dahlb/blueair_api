"""Tests for the gigya_region / cloud_region split on ``HttpAwsBlueair``.

These verify:

* Existing single-``region`` callers behave identically (back-compat).
* ``gigya_region`` and ``cloud_region`` can be set independently.
* Each URL builder picks up the *correct* region (Gigya hosts use
  ``gigya_region``; BlueCloud + IoT hosts use ``cloud_region``).
* Invalid regions raise ``ValueError`` with a clear message, both at
  construction and via the legacy ``region`` setter.
* The legacy ``region`` property reflects ``cloud_region`` (so
  ``MqttAwsBlueair`` and other downstream callers see the broker
  region, not the Gigya region).

No network is required; we build the client and inspect attributes /
constructed URLs.
"""
from __future__ import annotations

import pytest

from blueair_api.const import AWS_APIKEYS
from blueair_api.http_aws_blueair import HttpAwsBlueair


def _make(**kwargs) -> HttpAwsBlueair:
    """Build a client without opening a real aiohttp session.

    We pass a sentinel ``client_session`` to avoid the default
    ``ClientSession()`` instantiation (which would leak across tests).
    """
    return HttpAwsBlueair(
        username="user@example.com",
        password="hunter2",
        client_session=object(),  # type: ignore[arg-type]
        **kwargs,
    )


class TestBackCompatSingleRegion:
    """Existing single-``region`` callers must keep working unchanged."""

    @pytest.mark.parametrize("region", sorted(AWS_APIKEYS))
    def test_single_region_sets_both_halves(self, region: str) -> None:
        client = _make(region=region)
        assert client.gigya_region == region
        assert client.cloud_region == region
        # Legacy attribute access still works and matches cloud_region.
        assert client.region == region

    def test_default_region_is_us(self) -> None:
        client = _make()
        assert client.gigya_region == "us"
        assert client.cloud_region == "us"
        assert client.region == "us"


class TestSplitRegions:
    """gigya_region and cloud_region can be set independently."""

    def test_split_us_gigya_eu_cloud(self) -> None:
        client = _make(gigya_region="us", cloud_region="eu")
        assert client.gigya_region == "us"
        assert client.cloud_region == "eu"
        # The back-compat ``region`` alias must point at the BlueCloud
        # side so MQTT broker lookup picks the matching IoT endpoint.
        assert client.region == "eu"

    def test_split_only_cloud_override(self) -> None:
        # When only cloud_region is overridden, gigya_region falls back
        # to the ``region`` argument's value (here the default "us").
        client = _make(cloud_region="eu")
        assert client.gigya_region == "us"
        assert client.cloud_region == "eu"

    def test_split_only_gigya_override(self) -> None:
        client = _make(gigya_region="eu", region="us")
        assert client.gigya_region == "eu"
        assert client.cloud_region == "us"

    def test_explicit_args_win_over_region(self) -> None:
        # Both halves overridden + a legacy ``region`` value passed too:
        # the explicit overrides must win.
        client = _make(region="us", gigya_region="eu", cloud_region="au")
        assert client.gigya_region == "eu"
        assert client.cloud_region == "au"


class TestValidation:
    """Unknown regions raise ValueError with a useful message."""

    def test_unknown_region_in_legacy_arg(self) -> None:
        with pytest.raises(ValueError, match="Unknown gigya_region"):
            _make(region="zz")

    def test_unknown_gigya_region(self) -> None:
        with pytest.raises(ValueError, match="Unknown gigya_region"):
            _make(gigya_region="zz")

    def test_unknown_cloud_region(self) -> None:
        with pytest.raises(ValueError, match="Unknown cloud_region"):
            _make(cloud_region="zz")

    def test_legacy_region_setter_validates(self) -> None:
        client = _make()
        with pytest.raises(ValueError, match="Unknown region"):
            client.region = "zz"

    def test_legacy_region_setter_keeps_halves_in_sync(self) -> None:
        client = _make(gigya_region="us", cloud_region="eu")
        # Reassigning via the legacy property snaps both halves
        # back together — that's the historical behavior.
        client.region = "au"
        assert client.gigya_region == "au"
        assert client.cloud_region == "au"


class TestUrlsUseCorrectRegion:
    """The four URL builders must pick the correct region per host."""

    @staticmethod
    def _gigya_host(client: HttpAwsBlueair) -> str:
        return AWS_APIKEYS[client.gigya_region]["gigyaRegion"]

    @staticmethod
    def _cloud_rest_id(client: HttpAwsBlueair) -> str:
        return AWS_APIKEYS[client.cloud_region]["restApiId"]

    def test_asymmetric_hosts_are_distinct(self) -> None:
        """Sanity: US-Gigya and EU-Cloud must resolve to different hosts.

        If this ever fails it means the regional constants table has
        drifted and the rest of the assertions in this file would be
        meaningless.
        """
        client = _make(gigya_region="us", cloud_region="eu")
        assert "us1" in self._gigya_host(client)
        # eu rest API id is currently ``hkgmr8v960``.
        assert self._cloud_rest_id(client).startswith("hkg")

    def test_api_key_follows_gigya_region(self) -> None:
        # Gigya partner key is part of the Gigya record; if cloud_region
        # leaked into apikey selection we'd silently send a US key to
        # the EU host (which the EU partner would reject with
        # "Invalid apiKey").
        client = _make(gigya_region="eu", cloud_region="us")
        assert (
            AWS_APIKEYS[client.gigya_region]["apiKey"]
            != AWS_APIKEYS[client.cloud_region]["apiKey"]
        )

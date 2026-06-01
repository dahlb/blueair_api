"""Tests for ``blueair_api.region_discovery``.

Covers two primitives:

* ``device_state_looks_frozen`` — pure structural inspector, easy to
    fuzz with fixture payloads.
* ``discover_cloud_region`` — async probe, exercised with a fake
  aiohttp session so we never hit the network and can deterministically
  shape per-region outcomes (success, http error, timeout, etc.).

The discovery probe is contract-tested for:

* Read-only behavior: the client's ``cloud_region`` and persistent
  ``access_token`` are not mutated by ``discover_cloud_region``.
* Selected region is probed first.
* Winner is the region with the most devices, with ties broken in
  favor of the currently selected region.
* Multi-region accounts are flagged and warn at WARNING+.
* Empty / errored candidates are tolerated; an account with no
  device anywhere produces a ``winner=None`` scan rather than
  raising.
* Per-candidate timeout is respected.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from unittest import IsolatedAsyncioTestCase

import pytest

from blueair_api.http_aws_blueair import HttpAwsBlueair
from blueair_api.region_discovery import (
    CloudRegionScan,
    device_state_looks_frozen,
    discover_cloud_region,
)


# ---------------------------------------------------------------------------
# device_state_looks_frozen
# ---------------------------------------------------------------------------


def _states(rows: list[dict]) -> dict:
    return {"states": rows}


class TestDeviceStateLooksFrozen:
    """Unit tests for the structural snapshot-frozen detector.

    The rule fires only on the unambiguous wrong-region signature:
    no states at all, OR ``online=False`` combined with every state
    sharing a single timestamp.  Crucially, a genuinely-offline device
    with rich per-field history is NOT flagged — that's a normal
    offline condition, not a region issue.
    """

    def test_none_payload_is_frozen(self) -> None:
        # Defensive: a None payload has no recorded state at all.
        assert device_state_looks_frozen(None) is True

    def test_missing_states_is_frozen(self) -> None:
        assert device_state_looks_frozen({}) is True

    def test_empty_states_is_frozen(self) -> None:
        # The cloud knows the device UUID but has no data for it.
        # That's a strong wrong-region signal on its own.
        assert device_state_looks_frozen(_states([])) is True

    def test_online_true_is_never_frozen(self) -> None:
        # Even with identical timestamps, an explicitly online device
        # is not a region-mismatch signature -- it's just a device
        # that batch-updated all its fields at one moment.
        payload = _states([
            {"n": "fanspeed", "v": 11, "t": 1_700_000_000},
            {"n": "standby", "vb": False, "t": 1_700_000_000},
            {"n": "online", "vb": True, "t": 1_700_000_000},
        ])
        assert device_state_looks_frozen(payload) is False

    def test_online_absent_is_never_frozen(self) -> None:
        # No explicit online field -> we don't claim to know.
        # Conservative: not a frozen-snapshot signature.
        payload = _states([
            {"n": "fanspeed", "v": 11, "t": 1_700_000_000},
            {"n": "standby", "vb": False, "t": 1_700_000_000},
        ])
        assert device_state_looks_frozen(payload) is False

    def test_offline_but_varied_timestamps_is_not_frozen(self) -> None:
        # A genuinely-offline device whose fields had varied last-
        # update times before going offline.  Real history, no
        # region issue.
        payload = _states([
            {"n": "fanspeed", "v": 91, "t": 1_750_000_000},
            {"n": "brightness", "v": 50, "t": 1_751_000_000},
            {"n": "standby", "vb": False, "t": 1_752_000_000},
            {"n": "online", "vb": False, "t": 1_752_000_010},
        ])
        assert device_state_looks_frozen(payload) is False

    def test_issue_312_signature_is_frozen(self) -> None:
        # The exact pattern from issue #312: every state, including
        # online=False, sharing a single timestamp.
        frozen = 1_751_231_628
        payload = _states([
            {"n": "fanspeed", "v": 91, "t": frozen},
            {"n": "standby", "vb": False, "t": frozen},
            {"n": "brightness", "v": 100, "t": frozen},
            {"n": "automode", "vb": False, "t": frozen},
            {"n": "online", "vb": False, "t": frozen},
        ])
        assert device_state_looks_frozen(payload) is True

    def test_offline_with_no_numeric_timestamps_is_frozen(self) -> None:
        # Defensive: the rule treats <= 1 distinct timestamp as the
        # frozen-snapshot signature when combined with online=False.
        # Zero distinct timestamps satisfies that.
        payload = _states([
            {"n": "fanspeed", "v": 11},
            {"n": "online", "vb": False, "t": "not-an-int"},
        ])
        assert device_state_looks_frozen(payload) is True

    def test_non_dict_state_entries_are_tolerated(self) -> None:
        # Garbage entries are ignored.  The remaining valid online=True
        # state means we don't flag this.
        payload = _states([
            "junk",
            42,
            {"n": "fanspeed", "v": 11, "t": 1_700_000_000},
            {"n": "online", "vb": True, "t": 1_700_000_000},
        ])
        assert device_state_looks_frozen(payload) is False


# ---------------------------------------------------------------------------
# discover_cloud_region
# ---------------------------------------------------------------------------


class _FakeResponse:
    """Minimal stand-in for aiohttp.ClientResponse for our probes.

    Pass either ``body=<dict>`` for a normal JSON response, or
    ``json_exc=<exception instance>`` to make ``.json()`` raise
    (used to simulate non-JSON 200 responses like a CloudFront
    error page).
    """

    def __init__(
        self,
        status: int,
        body: object = None,
        *,
        json_exc: BaseException | None = None,
    ) -> None:
        self.status = status
        self._body = body
        self._json_exc = json_exc

    async def json(self):
        if self._json_exc is not None:
            raise self._json_exc
        return self._body

    def release(self) -> None:
        pass


class _FakeSession:
    """Async fake for ``aiohttp.ClientSession`` used by the probe.

    Each candidate region maps to either a callable returning two
    responses (``/c/login``, ``/c/registered-devices``) or to an
    exception to raise.  This lets each test shape regions
    independently.
    """

    def __init__(self, by_region: dict[str, object]) -> None:
        # by_region[region] = list-of-responses OR Exception class to raise
        self._by_region = by_region
        self.calls: list[tuple[str, str]] = []  # (region, path)

    @staticmethod
    def _region_from_url(url: str) -> str:
        # URLs look like
        # https://{restApiId}.execute-api.{awsRegion}.amazonaws.com/prod/c/...
        from blueair_api.const import AWS_APIKEYS

        for region, conf in AWS_APIKEYS.items():
            if conf["restApiId"] in url:
                return region
        raise AssertionError(f"could not map probe URL to region: {url}")

    @staticmethod
    def _path(url: str) -> str:
        return url.rsplit("/prod/c/", 1)[-1]

    async def _next_response(self, url: str) -> _FakeResponse:
        region = self._region_from_url(url)
        path = self._path(url)
        self.calls.append((region, path))
        entry = self._by_region.get(region)
        if entry is None:
            return _FakeResponse(500, {})
        if isinstance(entry, type) and issubclass(entry, BaseException):
            raise entry()
        if callable(entry):
            return entry(path)
        # Otherwise: list[_FakeResponse], consumed in order.
        assert isinstance(entry, list) and entry, f"empty queue for {region}"
        return entry.pop(0)

    async def post(self, *, url: str, headers=None, **kwargs):  # noqa: D401
        return await self._next_response(url)

    async def get(self, *, url: str, headers=None, **kwargs):  # noqa: D401
        return await self._next_response(url)


def _make_client(
    *,
    cloud_region: str = "us",
    gigya_region: str = "us",
    by_region: dict[str, object] | None = None,
    jwt: str | None = "fake-jwt",
) -> HttpAwsBlueair:
    client = HttpAwsBlueair(
        username="user@example.com",
        password="hunter2",
        client_session=_FakeSession(by_region or {}),  # type: ignore[arg-type]
        gigya_region=gigya_region,
        cloud_region=cloud_region,
    )
    # Skip the real Gigya login by pre-populating the JWT.
    client.jwt = jwt
    return client


def _ok(devices: int, *, online: int | None = None) -> Callable[[str], _FakeResponse]:
    """Build a fake responder that returns N devices for that region."""

    online_remaining = devices if online is None else online

    def responder(path: str) -> _FakeResponse:
        nonlocal online_remaining
        if path == "login":
            return _FakeResponse(200, {"access_token": "fake-access-token"})
        if path == "registered-devices":
            return _FakeResponse(
                200,
                {"devices": [{"uuid": f"d{i}"} for i in range(devices)]},
            )
        if path == "device-status":
            is_online = online_remaining > 0
            if online_remaining:
                online_remaining -= 1
            return _FakeResponse(200, {"online": is_online})
        return _FakeResponse(500, {})

    return responder


def _fail(login_status: int = 403) -> Callable[[str], _FakeResponse]:
    """Build a fake responder that fails at /c/login."""

    def responder(path: str) -> _FakeResponse:
        if path == "login":
            return _FakeResponse(login_status, {})
        return _FakeResponse(500, {})

    return responder


class DiscoveryTest(IsolatedAsyncioTestCase):
    async def test_winner_picks_region_with_most_devices(self) -> None:
        # Use cn (unique host) instead of au to avoid the eu/au host
        # collision; the dedup test covers that case explicitly.
        client = _make_client(
            cloud_region="us",
            by_region={
                "us": _ok(0),
                "eu": _ok(1),
                "cn": _ok(0),
            },
        )
        scan = await discover_cloud_region(client, candidates=["us", "eu", "cn"])
        assert scan.winner == "eu"
        assert scan.changed is True
        assert scan.multi_region_detected is False

    async def test_online_status_beats_stale_registered_device_mirror(self) -> None:
        # The CP7i #312 failure mode: the stale US backend can still list
        # the device, but /c/device-status says it is offline.  The live EU
        # backend lists the same device and reports it online, so EU must win
        # even though registered-device counts tie.
        client = _make_client(
            cloud_region="us",
            by_region={
                "us": _ok(1, online=0),
                "eu": _ok(1, online=1),
                "cn": _ok(0),
            },
        )
        scan = await discover_cloud_region(client, candidates=["us", "eu", "cn"])
        assert scan.per_region["us"].device_count == 1
        assert scan.per_region["us"].online_count == 0
        assert scan.per_region["eu"].device_count == 1
        assert scan.per_region["eu"].online_count == 1
        assert scan.winner == "eu"
        assert scan.changed is True

    async def test_tie_breaks_in_favor_of_selected_region(self) -> None:
        client = _make_client(
            cloud_region="us",
            by_region={"us": _ok(1), "eu": _ok(1), "cn": _ok(0)},
        )
        scan = await discover_cloud_region(client, candidates=["us", "eu", "cn"])
        # Both us and eu reported 1 device; us was selected, so us wins.
        assert scan.winner == "us"
        assert scan.changed is False
        # But discovery still flags the multi-region condition.
        assert scan.multi_region_detected is True

    async def test_no_devices_anywhere_returns_no_winner(self) -> None:
        client = _make_client(
            cloud_region="us",
            by_region={"us": _ok(0), "eu": _ok(0), "cn": _ok(0)},
        )
        scan = await discover_cloud_region(client, candidates=["us", "eu", "cn"])
        assert scan.winner is None
        assert scan.changed is False

    async def test_unreachable_candidates_are_skipped(self) -> None:
        # cn raises an arbitrary exception (e.g. unreachable from caller's
        # network); discovery must keep going and pick eu.  Use unique
        # hosts only -- the eu/au host collision is covered by
        # test_eu_au_host_dedup.
        client = _make_client(
            cloud_region="us",
            by_region={
                "us": _ok(0),
                "eu": _ok(1),
                "cn": asyncio.TimeoutError,
            },
        )
        scan = await discover_cloud_region(client, candidates=["us", "eu", "cn"])
        assert scan.winner == "eu"
        assert scan.per_region["cn"].error == "timeout"
        assert scan.per_region["cn"].cloud_login_ok is False

    async def test_eu_au_host_dedup(self) -> None:
        """``eu`` and ``au`` share the same BlueCloud execute-api host.

        Probing both would double-count devices and falsely flag a
        multi-region account.  The dedup logic must keep only one of
        them (the first in probe order)."""
        client = _make_client(
            cloud_region="us",
            by_region={"us": _ok(0), "eu": _ok(1)},
        )
        scan = await discover_cloud_region(client, candidates=["us", "eu", "au"])
        # Only us and eu are actually probed; au is skipped silently.
        assert scan.candidates_tried == ["us", "eu"]
        assert scan.winner == "eu"
        assert scan.multi_region_detected is False

    async def test_selected_region_is_probed_first(self) -> None:
        # Verify the call order matches: selected region (eu here)
        # should be the first /c/login URL hit.
        client = _make_client(
            cloud_region="eu",
            by_region={
                "us": _ok(0),
                "eu": _ok(1),
                "cn": _ok(0),
            },
        )
        scan = await discover_cloud_region(client, candidates=["us", "eu", "cn"])
        assert scan.candidates_tried[0] == "eu"
        first_login = next(
            call for call in client.api_session.calls if call[1] == "login"  # type: ignore[attr-defined]
        )
        assert first_login[0] == "eu"

    async def test_does_not_mutate_client_state(self) -> None:
        client = _make_client(
            cloud_region="us",
            by_region={
                "us": _ok(0),
                "eu": _ok(1),
            },
        )
        before_cloud_region = client.cloud_region
        before_gigya_region = client.gigya_region
        before_access_token = client.access_token
        await discover_cloud_region(client, candidates=["us", "eu"])
        # The caller is the one who decides whether to switch.  The
        # probe itself must not touch persistent client state.
        assert client.cloud_region == before_cloud_region
        assert client.gigya_region == before_gigya_region
        assert client.access_token is before_access_token  # still None

    async def test_unknown_candidate_keys_are_ignored(self) -> None:
        client = _make_client(
            cloud_region="us",
            by_region={"us": _ok(2)},
        )
        scan = await discover_cloud_region(client, candidates=["us", "zz"])
        # "zz" is silently dropped (it's not in AWS_APIKEYS).
        assert scan.candidates_tried == ["us"]
        assert scan.winner == "us"

    async def test_refreshes_jwt_when_missing(self) -> None:
        # Drop the pre-seeded JWT and arrange refresh_jwt to plant one.
        client = _make_client(
            cloud_region="us",
            jwt=None,
            by_region={"us": _ok(1)},
        )

        refresh_calls: list[str] = []

        async def fake_refresh_jwt() -> None:
            refresh_calls.append("refresh_jwt")
            client.jwt = "freshly-minted-jwt"

        client.refresh_jwt = fake_refresh_jwt  # type: ignore[method-assign]
        scan = await discover_cloud_region(client, candidates=["us"])
        assert refresh_calls == ["refresh_jwt"]
        assert scan.winner == "us"

    async def test_multi_region_warning_is_logged(self, caplog=None) -> None:
        # IsolatedAsyncioTestCase doesn't ship pytest's caplog fixture;
        # capture via assertLogs instead.
        client = _make_client(
            cloud_region="us",
            by_region={"us": _ok(1), "eu": _ok(2)},
        )
        with self.assertLogs("blueair_api.region_discovery", level="WARNING") as cm:
            scan = await discover_cloud_region(client, candidates=["us", "eu"])
        assert scan.multi_region_detected is True
        # The warning explicitly names the chosen region so users in
        # diagnostics dumps can see which region they're getting.
        assert any("multiple BlueCloud regions" in m for m in cm.output)


class DiscoveryQuietLoggingTest(IsolatedAsyncioTestCase):
    """Discovery must stay at DEBUG when nothing interesting happens.

    HA loads ``blueair_api`` at INFO by default.  A successful probe
    that confirms the currently configured region must not spam the
    log.
    """

    async def test_no_info_or_warning_when_selection_confirmed(self) -> None:
        client = _make_client(
            cloud_region="us",
            by_region={"us": _ok(1), "eu": _ok(0)},
        )
        logger = logging.getLogger("blueair_api.region_discovery")
        prev_level = logger.level
        logger.setLevel(logging.INFO)
        try:
            # If anything at INFO+ fires, assertLogs raises AssertionError
            # ("no logs captured for level INFO").  That's exactly what
            # we want as a negative assertion.
            with (
                pytest.raises(AssertionError),
                self.assertLogs("blueair_api.region_discovery", level="INFO"),
            ):
                await discover_cloud_region(client, candidates=["us", "eu"])
        finally:
            logger.setLevel(prev_level)


class DiscoveryResilienceTest(IsolatedAsyncioTestCase):
    """Probe should tolerate non-JSON / shape-malformed 200 responses.

    Production failure modes seen in the wild include CloudFront
    captive-portal interception (200 OK + HTML body) and truncated
    transfers.  These must not crash discovery — they should record
    a per-candidate error and let the scan keep going.
    """

    async def test_login_non_json_body_recorded_as_error(self) -> None:
        # /c/login returns 200 with a body that ``response.json()``
        # rejects (e.g. JSONDecodeError surfaces as ValueError).
        def login_html_responder(path: str) -> _FakeResponse:
            if path == "login":
                return _FakeResponse(200, json_exc=ValueError("not json"))
            return _FakeResponse(500)

        client = _make_client(
            cloud_region="us",
            by_region={"us": login_html_responder, "eu": _ok(1)},
        )
        scan = await discover_cloud_region(client, candidates=["us", "eu"])
        # us should be marked as a soft failure with a descriptive
        # error string; eu still wins.
        assert scan.per_region["us"].error == "login: non-json response"
        assert scan.per_region["us"].cloud_login_ok is False
        assert scan.winner == "eu"

    async def test_login_unexpected_shape_recorded_as_error(self) -> None:
        # /c/login returns 200 + JSON, but it's a list instead of a dict
        # so ``.get("access_token")`` would crash without the guard.
        def login_list_responder(path: str) -> _FakeResponse:
            if path == "login":
                return _FakeResponse(200, body=["unexpected"])
            return _FakeResponse(500)

        client = _make_client(
            cloud_region="us",
            by_region={"us": login_list_responder, "eu": _ok(1)},
        )
        scan = await discover_cloud_region(client, candidates=["us", "eu"])
        assert scan.per_region["us"].error == "login: unexpected response shape"
        assert scan.per_region["us"].cloud_login_ok is False
        assert scan.winner == "eu"

    async def test_devices_non_json_body_recorded_as_error(self) -> None:
        # /c/login succeeds; /c/registered-devices returns 200 with a
        # non-JSON body.  Login is marked ok but device_count stays
        # None and the candidate cannot win.
        def login_ok_devices_html(path: str) -> _FakeResponse:
            if path == "login":
                return _FakeResponse(200, body={"access_token": "tok"})
            if path == "registered-devices":
                return _FakeResponse(200, json_exc=ValueError("not json"))
            return _FakeResponse(500)

        client = _make_client(
            cloud_region="us",
            by_region={"us": login_ok_devices_html, "eu": _ok(1)},
        )
        scan = await discover_cloud_region(client, candidates=["us", "eu"])
        assert scan.per_region["us"].cloud_login_ok is True
        assert scan.per_region["us"].device_count is None
        assert scan.per_region["us"].error == "devices: non-json response"
        assert scan.winner == "eu"

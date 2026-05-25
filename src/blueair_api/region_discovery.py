"""BlueCloud region discovery — diagnostic primitives.

This module provides two read-only helpers the integration layer can
call explicitly when the user (or the integration's own diagnostic
flow) needs to decide which BlueCloud region an account's hardware
lives in.  See issue #312.

* :func:`device_state_looks_frozen` — pure inspector that returns
  ``True`` when an ``/r/initial`` payload has the structural signature
  of a wrong-region snapshot: missing/empty ``states``, or
  ``online=False`` combined with every state sharing a single
  timestamp.

* :meth:`HttpAwsBlueair.discover_cloud_region` — async probe that
    reuses the client's existing Gigya JWT to call ``/c/login`` and
    ``/c/registered-devices`` on each candidate BlueCloud region, then
    checks ``/c/device-status`` for returned devices.  It reports
    per-candidate device counts, online counts, and a recommended winner.  The
  probe is **read-only and side-effect-free**: it does not mutate
  ``cloud_region``, ``access_token``, or any other client attribute.

Design intent
-------------

Neither primitive is invoked from the library's normal authentication
or refresh paths.  The integration layer is expected to call them
**only on explicit user action** — for example, from a config-flow
"Detect cloud region" button or from a Repair-issue Fix dialog.  This
keeps run-to-run behavior deterministic: once the user (or the user-
confirmed discovery result) writes ``cloud_region`` into the config
entry, the library reads that value every time and never silently
re-chooses on its own.

Implementation notes
--------------------

* The same Gigya JWT is accepted by every BlueCloud regional
  ``/c/login`` endpoint, so we authenticate against Gigya once and
  fan out cheaply.
* Each candidate probe is bounded by a short per-region timeout so a
    hanging region (e.g. ``cn`` from outside China) can't stall discovery
    indefinitely.
* All probes log at ``DEBUG``; only a *meaningful* multi-region
  finding surfaces above debug.  Probes never log ``INFO`` for
  "discovery confirmed the configured region" — the caller already
  knows the outcome from the returned scan.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from aiohttp import ClientError

from .const import AWS_APIKEYS

if TYPE_CHECKING:
    from .http_aws_blueair import HttpAwsBlueair

_LOGGER = logging.getLogger(__name__)

# Default per-candidate probe timeout in seconds.  Set short so a
# region that simply can't be reached (firewalls, GFW, etc.) has a
# bounded impact on explicit discovery.
_DEFAULT_PER_CANDIDATE_TIMEOUT = 5.0


# ---------------------------------------------------------------------------
# Snapshot freshness inspector
# ---------------------------------------------------------------------------


def device_state_looks_frozen(initial_payload: dict | None) -> bool:
    """Return ``True`` when an ``/r/initial`` payload shows the
    structural signature of a wrong-region cloud snapshot.

    Returns ``True`` when either:

    1. The payload is ``None``, lacks ``states``, or has an empty
       ``states`` list (the cloud knows the device UUID but has no
       data for it).
    2. The payload contains an ``online`` state with ``vb=False``
       **and** every entry in ``states`` shares the same numeric
       timestamp (the cloud has only one snapshot ever recorded,
       and the device is not online).

    Returns ``False`` for the normal cases:

    * A device with varied per-field timestamps — even if currently
      offline — has history, so it's not flagged.  A genuinely-offline
      device with a real cloud record looks different from a wrong-
      region device whose cloud record never received updates.
    * A device whose states all share a single timestamp **but** is
      online (e.g. a healthy batch update event arrived a moment ago).

    The rule deliberately requires both ``online=False`` and a single
    distinct timestamp because either signal alone produces false
    positives.  Combining them isolates the wrong-region signature
    without depending on wall-clock thresholds or other heuristics.

    Parameters
    ----------
    initial_payload
        The single device's payload extracted from
        ``response_json["deviceInfo"][0]``.  ``None`` is tolerated.

    Returns
    -------
    bool
        ``True`` when the snapshot looks like a wrong-region record;
        ``False`` otherwise.  Callers typically use the ``True``
        result to raise a Repair issue inviting the user to confirm
        or change the configured ``cloud_region``.
    """
    if not isinstance(initial_payload, dict):
        return True
    states = initial_payload.get("states")
    if not isinstance(states, list) or not states:
        return True

    # Look for an explicit online flag.  Absent or True -> not frozen.
    online_value: bool | None = None
    for state in states:
        if isinstance(state, dict) and state.get("n") == "online":
            vb = state.get("vb")
            if isinstance(vb, bool):
                online_value = vb
            break
    if online_value is not False:
        return False

    # Collect numeric timestamps from every state entry.  If more than
    # one distinct value appears the device has real per-field history,
    # which rules out a frozen-snapshot pattern.
    distinct_timestamps: set[int] = set()
    for state in states:
        if not isinstance(state, dict):
            continue
        ts = state.get("t")
        if isinstance(ts, int):
            distinct_timestamps.add(ts)

    return len(distinct_timestamps) <= 1


# ---------------------------------------------------------------------------
# Region discovery probe
# ---------------------------------------------------------------------------


@dataclass
class CandidateProbe:
    """Outcome of probing a single BlueCloud region."""

    region: str
    """Region key, e.g. ``"us"``."""

    device_count: int | None = None
    """Number of devices returned by ``/c/registered-devices``,
    or ``None`` if the probe failed before reaching that call."""

    online_count: int | None = None
    """Number of returned devices whose ``/c/device-status`` response
    reported ``online=True``.  ``None`` if device status was not checked."""

    cloud_login_ok: bool = False
    """Whether ``/c/login`` returned an access token for this region
    using the current Gigya JWT."""

    error: str | None = None
    """Short reason this candidate was not probed successfully
    (e.g. ``"timeout"``, ``"http 403"``, ``"network: <msg>"``).  ``None``
    on success."""


@dataclass
class CloudRegionScan:
    """Aggregate result of probing several BlueCloud regions."""

    selected_region: str
    """The ``cloud_region`` that was configured on the client when
    discovery ran.  Returned untouched so callers can compare."""

    candidates_tried: list[str]
    """Ordered list of region keys actually probed."""

    per_region: dict[str, CandidateProbe] = field(default_factory=dict)
    """Detailed outcome for each candidate."""

    winner: str | None = None
    """Recommended ``cloud_region`` (most devices found; ties broken
    in favor of ``selected_region``).  ``None`` when no candidate
    returned any devices."""

    multi_region_detected: bool = False
    """``True`` when more than one candidate returned a non-empty
    device list — the account owns hardware on multiple BlueCloud
    regions.  Today's integration can only pick one; the caller is
    expected to log a warning and surface this in diagnostics."""

    @property
    def changed(self) -> bool:
        """Whether the recommended winner differs from ``selected_region``."""
        return self.winner is not None and self.winner != self.selected_region


async def _probe_candidate(
    api: HttpAwsBlueair,
    region: str,
    jwt: str,
    *,
    timeout: float,
) -> CandidateProbe:
    """Run a single read-only probe against ``region``.

    Uses the supplied Gigya ``jwt`` to call ``/c/login`` on the
    candidate region's host, then ``/c/registered-devices`` with the
    returned access token.  The candidate's access token is discarded
    after the probe — we never persist it on ``api``.
    """
    probe = CandidateProbe(region=region)
    if region not in AWS_APIKEYS:
        probe.error = "unknown region"
        return probe

    rest_id = AWS_APIKEYS[region]["restApiId"]
    aws_region = AWS_APIKEYS[region]["awsRegion"]
    base = f"https://{rest_id}.execute-api.{aws_region}/prod/c"

    headers = {"idtoken": jwt, "authorization": f"Bearer {jwt}"}

    def _release_response(response) -> None:
        release = getattr(response, "release", None)
        if callable(release):
            release()

    try:
        async with asyncio.timeout(timeout):
            # /c/login swap (no _LOGGER.info — caller decides what to surface)
            _LOGGER.debug("discover: probing /c/login at %s (%s)", region, rest_id)
            login_resp = await api.api_session.post(  # type: ignore[union-attr]
                url=f"{base}/login", headers=headers
            )
            if login_resp.status != 200:
                probe.error = f"http {login_resp.status}"
                _release_response(login_resp)
                return probe
            try:
                login_json = await login_resp.json()
            except (ValueError, ClientError):
                # Non-JSON 200 (CloudFront error page, captive portal,
                # truncated body, etc.).  Treat as a soft failure of
                # this candidate so the scan can keep going.
                probe.error = "login: non-json response"
                return probe
            if not isinstance(login_json, dict):
                probe.error = "login: unexpected response shape"
                return probe
            access_token = login_json.get("access_token")
            if not access_token:
                probe.error = "no access_token in response"
                return probe
            probe.cloud_login_ok = True

            _LOGGER.debug(
                "discover: probing /c/registered-devices at %s", region
            )
            devices_resp = await api.api_session.get(  # type: ignore[union-attr]
                url=f"{base}/registered-devices",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if devices_resp.status != 200:
                probe.error = f"devices http {devices_resp.status}"
                _release_response(devices_resp)
                return probe
            try:
                devices_json = await devices_resp.json()
            except (ValueError, ClientError):
                probe.error = "devices: non-json response"
                return probe
            devices = devices_json.get("devices") if isinstance(devices_json, dict) else None
            devices = devices if isinstance(devices, list) else []
            probe.device_count = len(devices)
            probe.online_count = 0

            for device in devices:
                device_id = device.get("uuid") if isinstance(device, dict) else None
                if not device_id:
                    continue
                try:
                    status_resp = await api.api_session.post(  # type: ignore[union-attr]
                        url=f"{base}/device-status",
                        headers={"Authorization": f"Bearer {access_token}"},
                        json={"deviceId": device_id},
                    )
                    if status_resp.status != 200:
                        _release_response(status_resp)
                        continue
                    status_json = await status_resp.json()
                except (ValueError, ClientError):
                    continue
                if isinstance(status_json, dict) and status_json.get("online") is True:
                    probe.online_count += 1
            return probe
    except TimeoutError:
        probe.error = "timeout"
        return probe
    except ClientError as exc:
        probe.error = f"network: {exc}"
        return probe


async def discover_cloud_region(
    api: HttpAwsBlueair,
    *,
    candidates: Iterable[str] | None = None,
    per_candidate_timeout: float = _DEFAULT_PER_CANDIDATE_TIMEOUT,
) -> CloudRegionScan:
    """Probe candidate BlueCloud regions and return a recommendation.

    Intended to be called **explicitly** by the integration layer
    (e.g. from a config-flow "Detect cloud region" step or a Repair-
    issue Fix dialog), not from the library's normal startup or
    refresh paths.  The caller is expected to present the returned
    scan to the user before persisting any change.

    This routine is **read-only with respect to ``api`` state**:

    * ``api.cloud_region`` is not modified.
    * No persistent access token is written to ``api``.  The caller
      decides whether to switch ``cloud_region`` (and clear stale
      tokens) based on the returned :class:`CloudRegionScan`.

    A valid Gigya JWT is required.  When ``api.jwt`` is unset, this
    routine refreshes it once via the normal Gigya login flow before
    probing candidates.

    Parameters
    ----------
    api
        The ``HttpAwsBlueair`` to probe with.
    candidates
        Region keys to probe.  Defaults to every known region in
        ``AWS_APIKEYS``.  The client's currently selected region is
        always probed first so the current configured choice is
        represented first in the returned scan and in tie-breaking.
    per_candidate_timeout
        Per-candidate probe deadline in seconds.

    Returns
    -------
    CloudRegionScan
        Scan summary; see the dataclass docstring.
    """
    if candidates is None:
        ordered = list(AWS_APIKEYS.keys())
    else:
        ordered = [c for c in candidates if c in AWS_APIKEYS]

    # Probe the currently selected region first.  This preserves the
    # configured region as the canonical answer for shared-host aliases
    # and tie breaks, while still scanning every deduped candidate so
    # multi-region accounts can be detected.
    if api.cloud_region in ordered:
        ordered.remove(api.cloud_region)
        ordered.insert(0, api.cloud_region)

    # De-duplicate by BlueCloud host: several region keys can share
    # the same execute-api endpoint (currently ``au`` and ``eu`` both
    # target ``hkgmr8v960.execute-api.eu-west-1``).  Probing both
    # would double-count devices and falsely fire multi-region
    # detection.  Keep the first occurrence so the caller's selected
    # region wins canonicalization.
    seen_hosts: set[tuple[str, str]] = set()
    deduped: list[str] = []
    for region in ordered:
        conf = AWS_APIKEYS[region]
        host_key = (conf["restApiId"], conf["awsRegion"])
        if host_key in seen_hosts:
            _LOGGER.debug(
                "discover: skipping %s (shares BlueCloud host with an "
                "already-queued region)",
                region,
            )
            continue
        seen_hosts.add(host_key)
        deduped.append(region)
    ordered = deduped

    scan = CloudRegionScan(
        selected_region=api.cloud_region,
        candidates_tried=list(ordered),
    )

    # Ensure we have a Gigya JWT.  refresh_jwt() handles refresh_session
    # on its own when needed.  Failures here can't be recovered by
    # discovery and bubble up.
    if not getattr(api, "jwt", None):
        _LOGGER.debug("discover: refreshing Gigya JWT before probing")
        await api.refresh_jwt()
    jwt = api.jwt
    if not jwt:
        # refresh_jwt() succeeded but produced nothing -- shouldn't
        # happen, but don't crash; return an empty scan and let the
        # caller log if they care.
        _LOGGER.debug("discover: no Gigya JWT after refresh; aborting probe")
        return scan

    for region in ordered:
        probe = await _probe_candidate(api, region, jwt, timeout=per_candidate_timeout)
        scan.per_region[region] = probe
        if probe.error is not None:
            _LOGGER.debug(
                "discover: candidate %s rejected (%s)", region, probe.error
            )
        else:
            _LOGGER.debug(
                "discover: candidate %s -> %d device(s), %d online",
                region,
                probe.device_count or 0,
                probe.online_count or 0,
            )

    # Pick the winner.  Online devices are the strongest signal that a
    # BlueCloud region is the live backend for the account.  This matters
    # because stale mirrored regions can still return the same registered
    # device list while reporting the device offline.  If no candidate reports
    # an online device, fall back to device count; tie -> selected region.
    online_per_region = {
        r: p.online_count
        for r, p in scan.per_region.items()
        if p.online_count and p.online_count > 0
    }
    devices_per_region = {
        r: p.device_count
        for r, p in scan.per_region.items()
        if p.device_count and p.device_count > 0
    }

    winning_counts = online_per_region or devices_per_region
    if winning_counts:
        max_count = max(winning_counts.values())
        winners = [r for r, c in winning_counts.items() if c == max_count]
        if scan.selected_region in winners:
            scan.winner = scan.selected_region
        else:
            # Preserve the order regions were probed in (selected
            # first), so ties resolve deterministically.
            for r in ordered:
                if r in winners:
                    scan.winner = r
                    break
        scan.multi_region_detected = len(devices_per_region) > 1

    # Only emit higher than DEBUG when there's something meaningful
    # for an operator to see.  The probe itself never switches the
    # active region; the caller decides what (if anything) to do with
    # the recommendation.
    if scan.multi_region_detected:
        _LOGGER.warning(
            "Account has devices on multiple BlueCloud regions: %s. "
            "The integration can only use one region per config entry; "
            "recommending %r based on device status and count.",
            sorted(devices_per_region),
            scan.winner,
        )
    elif scan.changed:
        _LOGGER.info(
            "BlueCloud region discovery: %r appears to host this "
            "account's device(s); current configured region is %r. "
            "Caller decides whether to switch.",
            scan.winner,
            scan.selected_region,
        )

    return scan

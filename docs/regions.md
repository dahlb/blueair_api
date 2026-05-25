# AWS Account and BlueCloud Regions

Most AWS-backed Blueair accounts use the same region for account login and
device control. For those accounts, keep using the existing `region` argument:

```python
from blueair_api import get_aws_devices

api, devices = await get_aws_devices(
    username="user@example.com",
    password="password",
    region="us",
)
```

`region` remains a compatibility shortcut. It sets both the Gigya account
region and the BlueCloud REST/MQTT region when no more specific value is
provided.

Some accounts are different: the user account logs in through one Gigya region,
but the device's live BlueCloud control plane is hosted in another region. In
that case, passing only `region="eu"` may fail account login, while passing only
`region="us"` may authenticate successfully but read stale device state from the
wrong BlueCloud backend.

For those accounts, configure the two sides independently:

```python
from blueair_api import get_aws_devices

api, devices = await get_aws_devices(
    username="user@example.com",
    password="password",
    gigya_region="us",
    cloud_region="eu",
)
```

The same split is available when constructing the HTTP client directly:

```python
from blueair_api import HttpAwsBlueair

api = HttpAwsBlueair(
    username="user@example.com",
    password="password",
    gigya_region="us",
    cloud_region="eu",
)
```

`gigya_region` controls account login and JWT refresh. `cloud_region` controls
BlueCloud REST calls and AWS IoT MQTT broker selection. The legacy `api.region`
property returns `cloud_region` so older MQTT callers continue to select the
device-control region.

## Explicit Region Discovery

`blueair_api` does not automatically scan regions during normal startup,
refresh, polling, or control calls. Discovery is intended for explicit user
flows, such as a config-flow "Detect cloud region" button, a reconfigure dialog,
or a Home Assistant Repair fix flow.

Use `discover_cloud_region()` when you already have a client with the user's
known account-login region and you want a recommendation for the BlueCloud
region. The probe logs in to each candidate BlueCloud region, reads its
registered device list, and checks device status so stale mirrored regions do
not win just because they still list the device:

```python
from blueair_api import HttpAwsBlueair

api = HttpAwsBlueair(
    username="user@example.com",
    password="password",
    gigya_region="us",
    cloud_region="us",  # current or default selection
)

scan = await api.discover_cloud_region()

if scan.winner and scan.changed:
    print(
        f"BlueCloud region {scan.winner!r} returned devices; "
        f"current selection is {scan.selected_region!r}."
    )
```

Discovery returns a `CloudRegionScan` object. Important fields:

- `selected_region`: the `cloud_region` configured on the client when discovery
  ran.
- `candidates_tried`: region keys actually probed, after invalid candidates and
  duplicate BlueCloud hosts are removed.
- `per_region`: detailed `CandidateProbe` results for each attempted region.
- `winner`: the recommended BlueCloud region, or `None` if no candidate returned
  devices.
- `changed`: `True` when `winner` differs from `selected_region`.
- `multi_region_detected`: `True` when more than one BlueCloud region returned
  devices.

The probe is read-only with respect to the client. It may refresh the Gigya JWT
if needed, but it does not change `api.cloud_region`, does not write a persistent
access token, and does not switch regions for you. Applications should show the
recommendation to the user and persist the confirmed `cloud_region` in their own
configuration.

Example integration flow:

```python
scan = await api.discover_cloud_region(candidates=["us", "eu", "cn", "au"])

if scan.winner is None:
    # Keep the user's current/default choice and allow manual override.
    suggested_cloud_region = api.cloud_region
elif scan.multi_region_detected:
    # Show a stronger prompt; this account appears to own devices in more than
    # one BlueCloud region, and one config entry can usually target only one.
    suggested_cloud_region = scan.winner
else:
    suggested_cloud_region = scan.winner

# Present suggested_cloud_region to the user. After confirmation, create a new
# client or config entry with cloud_region=suggested_cloud_region.
```

## Detecting a Frozen Device Snapshot

`device_state_looks_frozen()` helps integrations decide when to offer a repair
or reconfigure flow. It inspects one `/r/initial` device payload and returns
`True` only for the structural signature of a likely wrong-region snapshot:

- missing or empty `states`, or
- `online=False` and every state entry shares a single numeric timestamp.

It does not use wall-clock age. A genuinely offline device with varied state
timestamps is not flagged.

```python
from blueair_api import device_state_looks_frozen

initial_payload = await api.device_info(device_name, device_uuid)

if device_state_looks_frozen(initial_payload):
    # Raise a repair issue or offer a reconfigure action that calls
    # api.discover_cloud_region() and asks the user to confirm the result.
    ...
```

This helper is diagnostic only. Avoid silently changing the user's configured
region from this signal alone; use it to invite confirmation.

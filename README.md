# blueair_api

[![GitHub Release][releases-shield]][releases]
[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]](LICENSE)

![Project Maintenance][maintenance-shield]
[![BuyMeCoffee][buymecoffeebadge]][buymecoffee]

Api Wrapper for BlueAir API using async in python. This was inspired by
[this guide](https://developers.home-assistant.io/docs/api_lib_index) to be a
lightweight wrapper with simple error handling.

a lot of this is based on [hass-blueair](https://github.com/aijayadams/hass-blueair).

## Features

- **REST API** — async device discovery, sensor polling, and control commands
  for both legacy and AWS-based Blueair devices.
- **MQTT real-time updates** — receive sensor data and device state changes via
  AWS IoT WebSocket with sub-second latency instead of 5-minute polling.
- **Automatic reconnect with credential refresh** — MQTT tokens expire after 24
  hours; the client refreshes credentials and reconnects with exponential
  backoff on unexpected disconnects.
- **Split AWS regions when needed** — keep the normal single `region` setting
  for most accounts, or configure separate Gigya account and BlueCloud
  device-control regions for accounts whose devices are hosted elsewhere. See
  [AWS account and BlueCloud regions](docs/regions.md).
- **Data-driven SKU mapping** — resolves device SKUs to human-readable product
  names via a built-in lookup table.
- **Per-device hardware detection** — `mood_brightness_max` and
  `fan_speed_count` adapt automatically based on the device's hardware
  identifier.

## Sessions, Authentication and Errors

- **Shared aiohttp sessions** — pass `client_session` to reuse an existing
  session, such as Home Assistant's. `cleanup_client_session()` only closes a
  session the client created itself; a session you pass in is left open for
  its owner to close.
- **Re-authentication** — concurrent requests share one login. The BlueCloud
  access token is refreshed shortly before the `exp` claim in the token, and
  a request rejected with an expired session re-authenticates and retries
  once.
- **Errors** — every error is a `BaseError`, which is an aiohttp `ClientError`:
  - `LoginError` / `SessionError` (both `AuthError`): rejected credentials or
    session.
  - `RateError`: HTTP 429 rate limit.
  - `ServerError`: HTTP 5xx; does not discard the session.
  - `ResponseError`: any other unexpected status; also a `ValueError`.
  - `RequestTimeoutError`: a request took longer than 20 seconds; also a
    `TimeoutError`.
- **Debug logging** — request and response logs mask credentials, tokens,
  session secrets, signatures and email addresses.

## Development

Clone this repository and install the development environment:

```bash
git clone https://github.com/dahlb/blueair_api.git
cd blueair_api
scripts/setup
```

Use the repository scripts so commands run through the local `.venv`.

```bash
scripts/setup
scripts/test
scripts/lint
```

The underlying commands are:

```bash
./.venv/bin/pytest
./.venv/bin/prek run --all-files
./.venv/bin/mypy
```

`mypy` runs in strict mode (`strict = true` in `pyproject.toml`) over
`src/blueair_api` and `tests`. The Lint workflow runs the same check on every push and pull
request.

Add or update pytest coverage for behavior changes. Fixture data for device
info responses lives under `tests/device_info`.

## Live Smoke Test

The live smoke test connects to a real Blueair account, loads and refreshes
AWS devices, prints their state, starts the MQTT real-time listener, sends one
sample control update to the first AWS device, and checks the legacy API.

```bash
scripts/live_smoke_test
```

Use it only when you want to exercise the live Blueair APIs. The sample control
update writes the first AWS device's current LED brightness back to it, so the
setting is unchanged but the control path and MQTT shadow update are exercised.
The script then waits 5 minutes so MQTT messages can be observed.

To run non-interactively, put credentials in a local `env` file and pass it
with `--credentials-file`. Supported keys are `BLUEAIR_USERNAME`/`BLUEAIR_PASSWORD`
(see `scripts/blueair_api.env.example`); TOML and JSON files with
`username`/`password` keys also work, as do `BLUEAIR_USERNAME`/`BLUEAIR_PASSWORD`
environment variables.

```bash
scripts/live_smoke_test --credentials-file scripts/blueair_api.env --output-file /private/tmp/blueair_api.txt --read-only
```

Other options:

- `--output-file` writes a full transcript (stdout, stderr, and logs) for later
  API debugging or fixture updates.
- `--read-only` skips the sample control update while still loading devices and
  listening for MQTT messages.
- `--region` selects the Blueair region (`au`, `cn`, `eu`, `us`; default `us`).
  `--gigya-region` and `--cloud-region` override the account-auth and
  device-control regions separately; see [AWS account and BlueCloud regions](docs/regions.md).
- `--skip-legacy` skips the legacy (non-AWS) API check.

***

[commits-shield]: https://img.shields.io/github/commit-activity/y/dahlb/blueair_api.svg?style=for-the-badge
[commits]: https://github.com/dahlb/blueair_api/commits/main
[license-shield]: https://img.shields.io/github/license/dahlb/blueair_api.svg?style=for-the-badge
[maintenance-shield]: https://img.shields.io/badge/maintainer-Bren%20Dahl%20%40dahlb-blue.svg?style=for-the-badge
[releases-shield]: https://img.shields.io/github/release/dahlb/blueair_api.svg?style=for-the-badge
[releases]: https://github.com/dahlb/blueair_api/releases
[buymecoffee]: https://www.buymeacoffee.com/dahlb
[buymecoffeebadge]: https://img.shields.io/badge/buy%20me%20a%20coffee-donate-yellow.svg?style=for-the-badge

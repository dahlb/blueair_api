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

***

[commits-shield]: https://img.shields.io/github/commit-activity/y/dahlb/blueair_api.svg?style=for-the-badge
[commits]: https://github.com/dahlb/blueair_api/commits/main
[license-shield]: https://img.shields.io/github/license/dahlb/blueair_api.svg?style=for-the-badge
[maintenance-shield]: https://img.shields.io/badge/maintainer-Bren%20Dahl%20%40dahlb-blue.svg?style=for-the-badge
[releases-shield]: https://img.shields.io/github/release/dahlb/blueair_api.svg?style=for-the-badge
[releases]: https://github.com/dahlb/blueair_api/releases
[buymecoffee]: https://www.buymeacoffee.com/dahlb
[buymecoffeebadge]: https://img.shields.io/badge/buy%20me%20a%20coffee-donate-yellow.svg?style=for-the-badge

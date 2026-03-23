# Blueair MQTT Real-Time Updates

The Blueair cloud infrastructure provides an MQTT channel for real-time
sensor data and device state updates. This is in addition to the REST API
used for device discovery, initial configuration, and control commands.

## Overview

The `MqttAwsBlueair` class connects to the Blueair cloud MQTT broker via
WebSocket Secure (WSS) and subscribes to per-device topics for sensor data,
state changes, and connectivity events. This provides:

- **Real-time sensor data** every 5 seconds (PM1, PM2.5, PM10, fan speed, RSSI)
- **Instant state change notifications** (fan speed, standby, brightness, etc.)
- **Reliable device connectivity status** (online/offline events)

## Authentication

MQTT credentials are returned by the existing `c/login` REST endpoint
alongside the REST API tokens. No additional API calls are needed.

The login response includes these fields used for MQTT:

| Login Response Field | Purpose |
|---|---|
| `access_token` | JWT containing `username` claim used in topic paths |
| `ba_X-Amz-CustomAuthorizer-Name` | AWS IoT Custom Authorizer name |
| `ba_X-Amz-CustomAuthorizer-Signature` | AWS IoT Custom Authorizer signature |
| `ba_X-Amz-CustomAuthorizer-Token` | AWS IoT Custom Authorizer token |

These are passed as WebSocket upgrade headers when connecting to the broker.
Tokens expire after 24 hours (`expires_in: 86400`).

## Broker Endpoints

Each region has a dedicated AWS IoT Core endpoint:

| Region | Broker Host |
|--------|-------------|
| `us` | `a3tpdpjvxk6yog-ats.iot.us-east-2.amazonaws.com` |
| `eu` | `a3tpdpjvxk6yog-ats.iot.eu-west-1.amazonaws.com` |
| `au` | `a3tpdpjvxk6yog-ats.iot.eu-west-1.amazonaws.com` |
| `cn` | `a2du5f95w7oz2a.ats.iot.cn-north-1.amazonaws.com.cn` |

## Connection

- **Protocol**: MQTT 3.1.1 over WSS (port 443)
- **WebSocket path**: `/mqtt`
- **Client ID**: Random UUID (client-generated)
- **TLS**: Required (standard certificate validation)

## Topics

### Sensor Data — `d/<deviceId>/s/5s`

Published by the device every 5 seconds. Payload is a SenML JSON array:

```json
[
  {"n": "pm2_5", "v": 3.0},
  {"n": "pm1", "v": 0.0},
  {"n": "pm10", "v": 0.0},
  {"n": "fsp0", "v": 11.0},
  {"n": "rssi", "v": -24.0}
]
```

Each object has:
- `n`: sensor name
- `v`: numeric value

Available sensors vary by device model. Common sensors include `pm1`,
`pm2_5`, `pm10`, `fsp0` (fan speed), and `rssi` (Wi-Fi signal strength).

### Device State — `$aws/things/<deviceId>/shadow/update/documents`

Published when device state changes (e.g., fan speed adjusted, standby
toggled). Uses the AWS IoT Device Shadow format:

```json
{
  "current": {
    "state": {
      "reported": {
        "fanspeed": 51,
        "standby": false,
        "brightness": 64,
        "automode": true,
        "nightmode": false,
        "childlock": false
      }
    }
  },
  "previous": { ... }
}
```

The `current.state.reported` object contains the latest device state.

### Connectivity Events — `c/<userId>/s/event`

Published when a device connects to or disconnects from the cloud.
One subscription covers all devices for the user.

```json
{
  "et": "NotConnected",
  "o": "14ad6685-408a-4aa2-a923-a561e0872cc4",
  "ts": 1774219460,
  "m": "Device is Offline",
  "ot": "ConnectionEvent",
  "r": "US",
  "ec": 0
}
```

| Field | Description |
|-------|-------------|
| `et` | Event type: `"Connected"` or `"NotConnected"` |
| `o` | Origin device UUID |
| `m` | Human-readable message |
| `ts` | Timestamp (Unix epoch seconds) |
| `ot` | Object type (always `"ConnectionEvent"`) |
| `r` | Region |
| `ec` | Error code |

### Observed Timing

| Transition | Latency |
|---|---|
| Device powered off → `NotConnected` event | ~3 minutes |
| Device powered on → `Connected` event | ~34 seconds |
| `Connected` → first sensor data | ~5 seconds |
| `Connected` → state shadow update | ~5 seconds |

## Usage

```python
from blueair_api import MqttAwsBlueair

mqtt = MqttAwsBlueair(
    region="us",
    mqtt_auth_name=http_client.mqtt_auth_name,
    mqtt_auth_signature=http_client.mqtt_auth_signature,
    mqtt_auth_token=http_client.mqtt_auth_token,
    user_id=http_client.user_id,
)

# Register callbacks
mqtt.on_sensor_data = lambda device_id, sensors: print(sensors)
mqtt.on_state_change = lambda device_id, state: print(state)
mqtt.on_event = lambda device_id, event: print(event)

# Register devices and connect
mqtt.register_device("14ad6685-408a-4aa2-a923-a561e0872cc4")
mqtt.connect()

# Later...
mqtt.disconnect()
```

### Callbacks

| Callback | Arguments | Trigger |
|----------|-----------|---------|
| `on_sensor_data` | `(device_id: str, sensors: dict[str, float])` | Every ~5s per device |
| `on_state_change` | `(device_id: str, state: dict[str, Any])` | On device state change |
| `on_event` | `(device_id: str, event: dict[str, Any])` | On connect/disconnect |
| `on_connect_callback` | `()` | MQTT connection established |
| `on_disconnect_callback` | `()` | MQTT connection lost |

## Graceful Degradation

If MQTT credentials are not present in the login response (older API
versions or unsupported regions), or if the MQTT connection fails, the
library falls back to REST-only polling. MQTT is an optional enhancement.

## Notes

- One MQTT connection serves all devices for a user account
- The device pushes data at its own interval; no polling overhead
- AWS IoT Core supports millions of concurrent connections; one subscriber
  per user account is negligible
- `paho-mqtt` (>= 2.0) is used for the MQTT client implementation

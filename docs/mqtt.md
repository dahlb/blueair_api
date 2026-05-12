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
| --- | --- |
| `access_token` | JWT containing `username` claim used in topic paths |
| `ba_X-Amz-CustomAuthorizer-Name` | AWS IoT Custom Authorizer name |
| `ba_X-Amz-CustomAuthorizer-Signature` | AWS IoT Custom Authorizer signature |
| `ba_X-Amz-CustomAuthorizer-Token` | AWS IoT Custom Authorizer token |

These are passed as WebSocket upgrade headers when connecting to the broker.
Tokens expire after 24 hours (`expires_in: 86400`).

## Broker Endpoints

Each region has a dedicated AWS IoT Core endpoint:

| Region | Broker Host |
| -------- | ------------- |
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
| ------- | ------------- |
| `et` | Event type: `"Connected"` or `"NotConnected"` |
| `o` | Origin device UUID |
| `m` | Human-readable message |
| `ts` | Timestamp (Unix epoch seconds) |
| `ot` | Object type (always `"ConnectionEvent"`) |
| `r` | Region |
| `ec` | Error code |

### Observed Timing

| Transition | Latency |
| --- | --- |
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
| ---------- | ----------- | --------- |
| `on_sensor_data` | `(device_id: str, sensors: dict[str, float])` | Every ~5s per device |
| `on_state_change` | `(device_id: str, state: dict[str, Any])` | On device state change |
| `on_event` | `(device_id: str, event: dict[str, Any])` | On connect/disconnect |
| `on_connect_callback` | `()` | MQTT connection established |
| `on_disconnect_callback` | `()` | MQTT connection lost |

## Dynamic Sensor and State Mapping

The `DeviceAws` class exposes two helpers that consumers (e.g. `ha_blueair`)
can call from the MQTT callbacks to apply incoming data to device attributes
without hardcoding sensor names:

- `device.apply_sensor_data(sensors)` — call from `on_sensor_data`.  Maps
  each MQTT slug via `MQTT_SENSOR_FIELD_MAP` to a `DeviceAws` attribute and
  casts the value to `int`.  Unknown slugs land in `device.extra_sensors`.
- `device.apply_state_change(state)` — call from `on_state_change`.  Maps
  each shadow field via `SHADOW_FIELD_MAP` to a `DeviceAws` attribute, with
  humidifier fan-speed remapping (11/37/64 → 1/2/3) applied automatically.

The current maps (in `device_aws.py`) cover all sensors and shadow fields
observed across the supported device fixtures (purifiers, humidifiers,
combos, Mini Restful).  Adding a new device that publishes a new slug
requires only a one-line entry in the relevant map plus the matching
`DeviceAws` attribute — no changes to the MQTT plumbing.

The `device.mqtt_sensor_slugs` list, parsed from
`configuration.ds.rt5s.sn` during `refresh()`, captures the exact set of
sensor names the device declares it will publish on the 5-second topic.
This enables future schema-driven entity discovery without further library
changes.

## Reconnection & Token Refresh

AWS IoT Custom Authorizer tokens expire after 24 hours. When a token
expires (or the connection drops for any reason), the MQTT broker closes
the WebSocket connection. The client must obtain fresh tokens and
reconnect.

### Architecture Decision: Use Paho's Native Reconnect

**Do NOT disable paho's built-in reconnect** (`_reconnect_on_failure`).
An earlier implementation set `_reconnect_on_failure = False` and used a
custom reconnect thread. This caused **silent connection death**: when the
connection dropped, paho's `loop_forever()` thread exited immediately
(because `not self._reconnect_on_failure → run = False`), and since it
runs as a daemon thread, nothing in the system noticed. The custom
reconnect thread relied on `on_disconnect` firing to spawn it, but that
callback runs on the same dying paho thread and could race with the exit.

### How Token Refresh Works

The implementation uses two paho-native hooks that run synchronously
inside paho's reconnect flow:

1. **`on_pre_connect` callback** — Called by paho immediately before each
   `reconnect()` creates a new socket. We use this to call the async
   `credential_refresher` (which calls `refresh_access_token()` on the
   HTTP client) and update the stored auth credentials.

2. **`ws_set_options(headers=callable)`** — Instead of passing a static
   dict of WebSocket headers, we pass a callable that returns the
   *current* credentials on every WebSocket handshake. Paho calls this
   during `_WebsocketWrapper._do_handshake()` on every connection
   (including reconnects).

3. **`reconnect_delay_set(min_delay=5, max_delay=300)`** — Configures
   paho's built-in exponential backoff for reconnection attempts.

### Reconnect Flow (Paho Internal)

When a connection is lost, paho's `loop_forever()` (running in the
`loop_start()` thread) executes this sequence:

```text
connection lost
  → _do_on_disconnect() fires on_disconnect callback
  → _reconnect_wait() sleeps with exponential backoff (5s → 10s → ... → 300s)
  → reconnect()
      → on_pre_connect() ← refreshes credentials here
      → _create_socket()
          → _WebsocketWrapper._do_handshake(extra_headers)
              → callable headers returns fresh tokens ← applied here
      → _send_connect() sends MQTT CONNECT packet
  → on_connect() fires
      → re-subscribes to all device topics
  → backoff timer resets to min_delay on successful CONNACK
```

This is all handled by a single paho thread — no custom threads, no
race conditions.

### Failure Scenarios

| Scenario | Behavior |
| --- | --- |
| Token expires, AWS closes connection | Paho detects loss → waits 5s → `on_pre_connect` refreshes → reconnects with new tokens |
| Token refresh fails (e.g., network down) | `on_pre_connect` catches exception, logs it → paho tries with stale tokens → WS handshake fails → paho backs off → retries (calls `on_pre_connect` again) |
| AWS broker unreachable | Paho retries with exponential backoff up to 300s → keeps trying indefinitely |
| Clean disconnect (`disconnect()` called) | Paho stops the loop — no reconnect attempted |

### Why Not a Custom Reconnect Thread?

A custom reconnect thread outside paho's event loop has these problems:

- **Race condition**: Paho's own reconnect (if enabled) races with the
  custom thread, both trying to connect simultaneously.
- **Silent death**: If paho's reconnect is disabled to avoid the race,
  the `loop_forever()` thread exits silently on disconnect (daemon thread,
  no exception, no log). The custom thread must be spawned from
  `on_disconnect`, which runs on the dying thread.
- **Client rebuild**: The custom thread typically rebuilds the entire
  paho Client, losing all internal state (subscriptions, message queues,
  mid tracking).
- **No CONNACK verification**: `connect()` is non-blocking; the custom
  thread must poll for connection success separately.

Using paho's native hooks avoids all of these issues.

## Sensor Data Stream TTL

Blueair devices do not publish 5-second sensor data (`d/<id>/s/5s`)
indefinitely. Each device declares a TTL in its configuration
(`configuration.ds.rt5s.ttl`), typically 1200 seconds (20 minutes).
After the TTL expires, the device stops publishing to the topic even
though the MQTT subscription remains active on the broker.

The TTL resets when a new subscription is made to the topic. This is
by design — the mobile app only subscribes while the user is actively
viewing sensor data, so short sessions never hit the TTL.

For always-on consumers (e.g. Home Assistant), the client must
periodically re-subscribe to keep the data stream alive.

### How It Works

1. **Periodic re-subscribe timer** — On connect, a daemon timer starts
   at 75% of the TTL interval (default: 900s for 1200s TTL). When it
   fires, the client subscribes to `d/<id>/s/5s` for every registered
   device. Per MQTT spec, subscribing to an already-subscribed topic is
   idempotent (broker sends SUBACK), so this is safe.  We intentionally
   do NOT unsubscribe first — unsubscribing kills the device's data
   push and the immediate re-subscribe doesn't always restart it.

2. **Connected event re-subscribe** — When a device sends a `Connected`
   event (device came online), the client immediately re-subscribes to
   that device's sensor topic. This ensures data starts flowing as soon
   as the device is available.

3. **Dynamic TTL** — Call `set_sensor_ttl(seconds)` with the value from
   the device configuration (`configuration.ds.rt5s.ttl`). If not set,
   the default of 1200 seconds is used. Values ≤ 0 are ignored (the
   stream never expires).

### Data Streams by TTL

| Stream | Topic Pattern | TTL | Publish Interval | Purpose |
| -------- | --------------- | ----- | ------------------ | --------- |
| `rt1s` | `d/<id>/s/1s` | 0 | 1 second | Real-time display, no retention |
| `rt5s` | `d/<id>/s/5s` | 1200 | 5 seconds | Live monitoring (our primary source) |
| `rt5m` | `d/<id>/s/5m` | 1200 | 5 minutes | Short-term charts |
| `b5m` | `$aws/rules/.../batch/b5m` | -1 | 5 minutes | Historical data (always publishing) |
| `rssi` | `d/<id>/s/rssi` | 600 | 60 seconds | Wi-Fi signal strength |
| State topics | `d/<id>/s/<name>` | -1 | On change | Fan speed, standby, etc. (never expire) |

The `b5m` stream feeds the cloud database for historical charts via the
REST API. It never stops (`ttl: -1`), runs independently of subscribers,
and routes through an AWS IoT Rules Engine ingest topic.

### TTL Usage Example

```python
mqtt = MqttAwsBlueair(...)

# Set TTL from device config (optional — defaults to 1200s)
mqtt.set_sensor_ttl(1200)

# Register devices and connect as usual
mqtt.register_device(device_uuid)
mqtt.connect()
```

The re-subscribe timer starts automatically on connect and cancels on
disconnect. No additional setup is required.

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
- **Never set `_reconnect_on_failure = False`** — see "Reconnection &
  Token Refresh" section above for why
- Key paho hooks used: `on_pre_connect` (credential refresh),
  `ws_set_options(headers=callable)` (dynamic WS headers),
  `reconnect_delay_set()` (backoff configuration)
- Subscriptions are placed in `on_connect` so they survive reconnects
  (recommended pattern from paho's own documentation)
- Sensor data streams have a device-side TTL (typically 1200s) — the
  client automatically re-subscribes to keep them alive

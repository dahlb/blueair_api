"""MQTT client for Blueair AWS IoT real-time updates.

Connects to the Blueair cloud MQTT broker via WebSocket Secure (WSS)
using credentials from the existing c/login API response. Provides
real-time sensor data and device state change callbacks.

On unexpected disconnect, paho's built-in reconnect loop handles
reconnection with exponential backoff.  Before each reconnect attempt
the ``on_pre_connect`` hook refreshes credentials (tokens expire after
24 hours), and the ``ws_set_options(headers=callable)`` mechanism
ensures the new tokens are applied to the WebSocket handshake.

MQTT broker endpoints and authentication flow determined through
investigation of the Blueair cloud API responses and AWS IoT
protocol behavior.
"""

import asyncio
from collections.abc import Callable, Coroutine
import concurrent.futures
import json
from logging import getLogger
import ssl
import threading
from typing import Any
import uuid

import paho.mqtt.client as mqtt

from .const import AWS_MQTT_BROKERS

_LOGGER = getLogger(__name__)

# Callback type aliases
SensorCallback = Callable[[str, dict[str, float]], None]
StateCallback = Callable[[str, dict[str, Any]], None]
EventCallback = Callable[[str, dict[str, Any]], None]
CredentialRefresher = Callable[[], Coroutine[Any, Any, tuple[str, str, str]]]

# Default sensor stream TTL in seconds.  Devices declare their own TTL
# in configuration.ds.rt5s.ttl; this fallback is used when no TTL is
# provided.  Most Blueair devices use 1200 (20 minutes).
_DEFAULT_SENSOR_TTL = 1200

# Re-subscribe at 75 % of the TTL to avoid data gaps.
_TTL_RESUBSCRIBE_RATIO = 0.75


class MqttAwsBlueair:
    """MQTT client for real-time Blueair device updates via AWS IoT.

    Usage:
        mqtt_client = MqttAwsBlueair(
            region="us",
            mqtt_auth_name=http_client.mqtt_auth_name,
            mqtt_auth_signature=http_client.mqtt_auth_signature,
            mqtt_auth_token=http_client.mqtt_auth_token,
            user_id=http_client.user_id,
        )
        mqtt_client.on_sensor_data = my_sensor_callback
        mqtt_client.on_state_change = my_state_callback
        mqtt_client.on_event = my_event_callback
        mqtt_client.register_device(device_uuid)
        mqtt_client.connect()
        # ...
        mqtt_client.disconnect()

    For automatic token refresh on reconnect, supply a credential_refresher:

        async def refresh_creds():
            await http_client.refresh_access_token()
            return (
                http_client.mqtt_auth_name,
                http_client.mqtt_auth_signature,
                http_client.mqtt_auth_token,
            )
        mqtt_client.credential_refresher = refresh_creds
    """

    def __init__(
        self,
        region: str,
        mqtt_auth_name: str,
        mqtt_auth_signature: str,
        mqtt_auth_token: str,
        user_id: str,
    ) -> None:
        """Store connection details; call ``connect()`` to open the MQTT link."""
        self._region = region
        self._mqtt_auth_name = mqtt_auth_name
        self._mqtt_auth_signature = mqtt_auth_signature
        self._mqtt_auth_token = mqtt_auth_token
        self._user_id = user_id
        self._device_ids: list[str] = []
        self._client_id = str(uuid.uuid4())

        # Callbacks
        self.on_sensor_data: SensorCallback | None = None
        self.on_state_change: StateCallback | None = None
        self.on_event: EventCallback | None = None
        self.on_disconnect_callback: Callable[[], None] | None = None
        self.on_connect_callback: Callable[[], None] | None = None

        # Async callable that refreshes login and returns
        # (mqtt_auth_name, mqtt_auth_signature, mqtt_auth_token).
        self.credential_refresher: CredentialRefresher | None = None

        # Event loop for running the async credential refresher from
        # the synchronous paho callback thread.
        self._event_loop: asyncio.AbstractEventLoop | None = None

        self._client: mqtt.Client | None = None
        self._connected = False
        self._stopping = False
        self._sensor_ttl: int = _DEFAULT_SENSOR_TTL
        self._resubscribe_timer: threading.Timer | None = None

    @property
    def connected(self) -> bool:
        """Whether the client currently has an open MQTT connection."""
        return self._connected

    def register_device(self, device_uuid: str) -> None:
        """Register a device UUID to subscribe to its topics."""
        if device_uuid not in self._device_ids:
            self._device_ids.append(device_uuid)
            _LOGGER.debug("Registered device %s (total: %s)", device_uuid, len(self._device_ids))
            # If already connected, subscribe to the new device immediately
            if self._connected and self._client is not None:
                self._subscribe_device(device_uuid)

    def _subscribe_device(self, device_uuid: str) -> None:
        """Subscribe to MQTT topics for a single device."""
        if self._client is None:
            return
        topics = [
            f"d/{device_uuid}/s/5s",
            f"$aws/things/{device_uuid}/shadow/update/documents",
        ]
        for topic in topics:
            self._client.subscribe(topic)
            _LOGGER.debug("Subscribed to %s", topic)

    def set_sensor_ttl(self, ttl_seconds: int) -> None:
        """Set the sensor data stream TTL from the device configuration.

        The TTL comes from ``configuration.ds.rt5s.ttl`` in the device
        info API response.  When set, the client will periodically
        re-subscribe to sensor topics at 75% of this interval to keep
        the device publishing real-time data.

        Parameters
        ----------
        ttl_seconds : int
            TTL in seconds from the device config.  Values <= 0 are
            ignored (stream never expires).
        """
        if ttl_seconds > 0:
            self._sensor_ttl = ttl_seconds
            _LOGGER.debug(
                "Sensor TTL set to %ss (re-subscribe every %ss)",
                ttl_seconds,
                int(ttl_seconds * _TTL_RESUBSCRIBE_RATIO),
            )

    def _resubscribe_sensor_topics(self) -> None:
        """Re-subscribe to sensor topics for all devices.

        This resets the device-side TTL countdown, keeping the 5-second
        sensor data stream alive.  Per MQTT spec, subscribing to an
        already-subscribed topic is idempotent (broker sends SUBACK and
        the subscription stays active).  We intentionally do NOT
        unsubscribe first — the unsubscribe kills the device's data
        push and the immediate re-subscribe doesn't always restart it.

        Safe to call from any thread — guards against client being
        None or disconnected (e.g. during shutdown race).
        """
        client = self._client  # snapshot to avoid race with disconnect()
        if client is None or not self._connected:
            return
        for device_uuid in self._device_ids:
            topic = f"d/{device_uuid}/s/5s"
            try:
                client.subscribe(topic)
                _LOGGER.debug("Re-subscribed to %s (TTL keepalive)", topic)
            except Exception:
                _LOGGER.exception("Failed to re-subscribe to %s", topic)

    def _start_resubscribe_timer(self) -> None:
        """Start the periodic re-subscribe timer based on the sensor TTL."""
        self._cancel_resubscribe_timer()
        if self._sensor_ttl <= 0 or self._stopping:
            return
        interval = int(self._sensor_ttl * _TTL_RESUBSCRIBE_RATIO)
        _LOGGER.debug(
            "Starting sensor re-subscribe timer (every %ss, TTL=%ss)", interval, self._sensor_ttl
        )
        self._resubscribe_timer = threading.Timer(interval, self._resubscribe_timer_fired)
        self._resubscribe_timer.daemon = True
        self._resubscribe_timer.start()

    def _cancel_resubscribe_timer(self) -> None:
        """Cancel the periodic re-subscribe timer if running."""
        if self._resubscribe_timer is not None:
            self._resubscribe_timer.cancel()
            self._resubscribe_timer = None

    def _resubscribe_timer_fired(self) -> None:
        """Called when the re-subscribe timer fires."""
        if self._stopping or not self._connected:
            return
        _LOGGER.debug(
            "Sensor TTL keepalive: re-subscribing to sensor topics for %s device(s)",
            len(self._device_ids),
        )
        self._resubscribe_sensor_topics()
        # Restart the timer for the next cycle
        self._start_resubscribe_timer()

    def _build_client(self) -> mqtt.Client:
        """Create a new paho MQTT client with current credentials."""
        broker = AWS_MQTT_BROKERS.get(self._region)
        if broker is None:
            raise ValueError(f"No MQTT broker configured for region: {self._region}")

        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=self._client_id,
            transport="websockets",
        )
        # Let paho handle reconnection natively.  We refresh credentials
        # in on_pre_connect and supply a headers callable so each new
        # WebSocket handshake picks up the latest tokens automatically.
        client.reconnect_delay_set(min_delay=5, max_delay=300)
        client.on_connect = self._on_connect
        client.on_connect_fail = self._on_connect_fail
        client.on_message = self._on_message
        client.on_disconnect = self._on_disconnect
        client.on_subscribe = self._on_subscribe
        client.on_pre_connect = self._on_pre_connect

        # Route paho's internal logging (PINGREQ/PINGRESP, reconnect
        # attempts, CONNACK details) through Python's standard logging.
        # Visible in HA when debug logging is enabled for paho.mqtt.client.
        client.enable_logger(_LOGGER)

        # TLS for WSS
        client.tls_set(cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLS_CLIENT)

        # AWS IoT Custom Authorizer headers — use a callable so that
        # paho calls it on every (re)connect to get fresh tokens.
        client.ws_set_options(
            path="/mqtt",
            headers=self._get_ws_headers,
        )
        return client

    def _get_ws_headers(self, default_headers: dict[str, str]) -> dict[str, str]:
        """Return WebSocket headers with the current auth credentials.

        Called by paho on every WebSocket handshake (including reconnects).
        """
        default_headers["X-Amz-CustomAuthorizer-Name"] = self._mqtt_auth_name
        default_headers["X-Amz-CustomAuthorizer-Signature"] = self._mqtt_auth_signature
        default_headers["X-Amz-CustomAuthorizer-Token"] = self._mqtt_auth_token
        return default_headers

    def _on_pre_connect(self, client: Any, userdata: Any) -> None:
        """Refresh credentials before each connection/reconnection attempt.

        Paho calls this synchronously immediately before ``reconnect()``
        creates a new socket.  We bridge into the async event loop to
        call the credential refresher so that ``_get_ws_headers`` will
        return fresh tokens for the upcoming WebSocket handshake.
        """
        _LOGGER.info("MQTT pre-connect: preparing for connection attempt")
        if not self.credential_refresher or not self._event_loop:
            _LOGGER.debug(
                "MQTT pre-connect: no credential_refresher configured, using existing tokens"
            )
            return
        try:
            future: concurrent.futures.Future[tuple[str, str, str]] = (
                asyncio.run_coroutine_threadsafe(self.credential_refresher(), self._event_loop)
            )
            new_name, new_sig, new_token = future.result(timeout=30)
            self._mqtt_auth_name = new_name
            self._mqtt_auth_signature = new_sig
            self._mqtt_auth_token = new_token
            _LOGGER.info("MQTT credentials refreshed successfully via on_pre_connect")
        except Exception:
            _LOGGER.exception(
                "Failed to refresh MQTT credentials in on_pre_connect; "
                "will attempt reconnect with previous (possibly stale) tokens"
            )

    def connect(self, event_loop: asyncio.AbstractEventLoop | None = None) -> None:
        """Connect to the MQTT broker and start the network loop.

        Parameters
        ----------
        event_loop : asyncio event loop, optional
            The running asyncio event loop. Required when
            ``credential_refresher`` is set, so the reconnect thread
            can schedule the async refresh on the correct loop.
        """
        self._event_loop = event_loop
        self._stopping = False

        broker = AWS_MQTT_BROKERS.get(self._region)
        if broker is None:
            raise ValueError(f"No MQTT broker configured for region: {self._region}")

        if not self._mqtt_auth_name or not self._mqtt_auth_signature or not self._mqtt_auth_token:
            _LOGGER.error(
                "MQTT auth credentials missing or empty "
                "(auth_name=%s, auth_signature=%s, auth_token=%s)",
                bool(self._mqtt_auth_name),
                bool(self._mqtt_auth_signature),
                bool(self._mqtt_auth_token),
            )

        _LOGGER.info(
            "Connecting to MQTT broker wss://%s (region=%s, client_id=%s, user_id=%s, devices=%s)",
            broker,
            self._region,
            self._client_id,
            self._user_id,
            len(self._device_ids),
        )

        self._client = self._build_client()
        self._client.connect(broker, 443, keepalive=60)
        # Use loop_start (non-blocking) so we can stop cleanly on reconnect.
        self._client.loop_start()

    def disconnect(self) -> None:
        """Disconnect from the MQTT broker."""
        _LOGGER.info("Disconnecting from MQTT broker")
        self._stopping = True
        self._cancel_resubscribe_timer()
        if self._client is not None:
            self._client.loop_stop()
            self._client.disconnect()
            self._connected = False
        self._client = None

    def _on_connect(
        self, client: Any, userdata: Any, flags: Any, reason_code: Any, properties: Any
    ) -> None:
        """Handle a successful or failed connection attempt from paho."""
        if reason_code == 0:
            _LOGGER.info("MQTT connected successfully (devices=%s)", len(self._device_ids))
            self._connected = True
            # Subscribe to per-user event topic
            user_topic = f"c/{self._user_id}/s/event"
            client.subscribe(user_topic)
            _LOGGER.debug("Subscribed to %s", user_topic)
            # Subscribe to all registered devices
            for device_uuid in self._device_ids:
                self._subscribe_device(device_uuid)
            # Start the periodic re-subscribe timer to keep sensor
            # data streams alive (resets the device-side TTL).
            self._start_resubscribe_timer()
            if self.on_connect_callback:
                self.on_connect_callback()
        else:
            _LOGGER.error("MQTT connection failed: reason_code=%s", reason_code)

    def _on_disconnect(
        self, client: Any, userdata: Any, flags: Any, reason_code: Any, properties: Any
    ) -> None:
        """Handle an MQTT disconnect, clean or unexpected, from paho."""
        self._connected = False
        self._cancel_resubscribe_timer()
        if reason_code == 0 or self._stopping:
            _LOGGER.info("MQTT disconnected cleanly")
        else:
            _LOGGER.info(
                "MQTT disconnected unexpectedly: reason_code=%s; "
                "paho will auto-reconnect with credential refresh",
                reason_code,
            )
        if self.on_disconnect_callback:
            self.on_disconnect_callback()

    def _on_connect_fail(self, client: Any, userdata: Any) -> None:
        """Log a failed connection attempt; paho handles the retry."""
        _LOGGER.warning(
            "MQTT connection attempt failed (TCP/TLS/WebSocket handshake error); "
            "paho will retry with backoff"
        )

    def _on_subscribe(
        self, client: Any, userdata: Any, mid: Any, reason_codes: Any, properties: Any
    ) -> None:
        """Log a subscription acknowledgment from paho."""
        _LOGGER.debug("MQTT subscription confirmed (mid=%s)", mid)

    def _on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """Parse an incoming MQTT message and dispatch it by topic."""
        topic = msg.topic
        try:
            payload = json.loads(msg.payload.decode())
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            _LOGGER.warning("Failed to parse MQTT message on %s: %s", topic, e)
            return

        if topic.startswith("d/") and "/s/5s" in topic:
            self._handle_sensor_data(topic, payload)
        elif "$aws/things" in topic:
            self._handle_state_change(topic, payload)
        elif topic.endswith("/event"):
            self._handle_event(topic, payload)
        else:
            _LOGGER.debug("Unhandled MQTT topic: %s", topic)

    def _handle_sensor_data(self, topic: str, payload: Any) -> None:
        """Parse sensor data from d/<deviceId>/s/5s topic."""
        parts = topic.split("/")
        if len(parts) < 2:
            return
        device_id = parts[1]

        sensors: dict[str, float] = {}
        if isinstance(payload, list):
            for item in payload:
                name = item.get("n")
                value = item.get("v")
                if name is not None and value is not None:
                    sensors[name] = value

        if self.on_sensor_data:
            try:
                self.on_sensor_data(device_id, sensors)
            except Exception:
                _LOGGER.exception("Error in on_sensor_data callback for %s", device_id)

    def _handle_state_change(self, topic: str, payload: Any) -> None:
        """Parse state change from $aws/things/<deviceId>/shadow/update/documents."""
        # Extract device ID: $aws/things/<deviceId>/shadow/...
        parts = topic.split("/")
        if len(parts) < 3:
            return
        device_id = parts[2]

        if not isinstance(payload, dict):
            return

        # Extract the current reported state from the shadow document
        state = payload.get("current", {}).get("state", {}).get("reported", {})

        _LOGGER.debug("State change for %s: %s", device_id, state)
        if self.on_state_change:
            try:
                self.on_state_change(device_id, state)
            except Exception:
                _LOGGER.exception("Error in on_state_change callback for %s", device_id)

    def _handle_event(self, topic: str, payload: Any) -> None:
        """Parse connectivity event from c/<userId>/s/event.

        Event payload fields (from live API observation):
          et: event type ("Connected" or "NotConnected")
          o:  origin device ID
          m:  human-readable message ("Device is Online" / "Device is Offline")
          ts: timestamp (epoch seconds)
          ot: object type ("ConnectionEvent")
          r:  region
          ec: error code
        """
        if not isinstance(payload, dict):
            return

        # The event payload uses short field names: "o" for origin, "et" for event type.
        device_id = str(payload.get("o", payload.get("originDeviceId", "")))
        event_type = str(payload.get("et", payload.get("connectionEvent", "unknown")))
        _LOGGER.debug("Device event for %s: %s (%s)", device_id, event_type, payload.get("m", ""))

        # When a device comes online, re-subscribe to its sensor topic
        # to reset the TTL and start receiving 5s data.
        client = self._client  # snapshot to avoid race with disconnect()
        if event_type == "Connected" and device_id in self._device_ids and client is not None:
            topic = f"d/{device_id}/s/5s"
            try:
                client.subscribe(topic)
                _LOGGER.info("Re-subscribed to %s (device Connected event)", topic)
            except Exception:
                _LOGGER.exception("Failed to re-subscribe on Connected event for %s", device_id)

        if self.on_event:
            try:
                self.on_event(device_id, payload)
            except Exception:
                _LOGGER.exception("Error in on_event callback for %s", device_id)

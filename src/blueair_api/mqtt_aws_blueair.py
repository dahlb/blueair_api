"""MQTT client for Blueair AWS IoT real-time updates.

Connects to the Blueair cloud MQTT broker via WebSocket Secure (WSS)
using credentials from the existing c/login API response. Provides
real-time sensor data and device state change callbacks.

On unexpected disconnect, refreshes credentials (tokens expire after
24 hours) and reconnects with exponential backoff.

MQTT broker endpoints and authentication flow determined through
investigation of the Blueair cloud API responses and AWS IoT
protocol behavior.
"""
import asyncio
import json
import ssl
import uuid
import time
import threading
from logging import getLogger
from typing import Any
from collections.abc import Callable, Awaitable

import paho.mqtt.client as mqtt

from .const import AWS_MQTT_BROKERS

_LOGGER = getLogger(__name__)

# Callback type aliases
SensorCallback = Callable[[str, dict[str, float]], None]
StateCallback = Callable[[str, dict[str, Any]], None]
EventCallback = Callable[[str, dict[str, Any]], None]
CredentialRefresher = Callable[[], Awaitable[tuple[str, str, str]]]

# Reconnect backoff parameters
_RECONNECT_INITIAL_DELAY = 5
_RECONNECT_MAX_DELAY = 300
_RECONNECT_BACKOFF_FACTOR = 2


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
    ):
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
        # the synchronous paho disconnect callback thread.
        self._event_loop = None

        self._client: mqtt.Client | None = None
        self._connected = False
        self._stopping = False
        self._reconnect_thread: threading.Thread | None = None

    @property
    def connected(self) -> bool:
        return self._connected

    def register_device(self, device_uuid: str) -> None:
        """Register a device UUID to subscribe to its topics."""
        if device_uuid not in self._device_ids:
            self._device_ids.append(device_uuid)
            _LOGGER.debug(f"Registered device {device_uuid} (total: {len(self._device_ids)})")
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
            _LOGGER.debug(f"Subscribed to {topic}")

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
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        client.on_disconnect = self._on_disconnect
        client.on_subscribe = self._on_subscribe

        # TLS for WSS
        client.tls_set(cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLS_CLIENT)

        # AWS IoT Custom Authorizer headers
        client.ws_set_options(
            path="/mqtt",
            headers={
                "X-Amz-CustomAuthorizer-Name": self._mqtt_auth_name,
                "X-Amz-CustomAuthorizer-Signature": self._mqtt_auth_signature,
                "X-Amz-CustomAuthorizer-Token": self._mqtt_auth_token,
            },
        )
        return client

    def connect(self, event_loop=None) -> None:
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
                f"(auth_name={bool(self._mqtt_auth_name)}, "
                f"auth_signature={bool(self._mqtt_auth_signature)}, "
                f"auth_token={bool(self._mqtt_auth_token)})"
            )

        _LOGGER.info(
            f"Connecting to MQTT broker wss://{broker} "
            f"(region={self._region}, client_id={self._client_id}, "
            f"user_id={self._user_id}, devices={len(self._device_ids)})"
        )

        self._client = self._build_client()
        self._client.connect(broker, 443, keepalive=60)
        # Use loop_start (non-blocking) so we can stop cleanly on reconnect.
        self._client.loop_start()

    def disconnect(self) -> None:
        """Disconnect from the MQTT broker."""
        _LOGGER.info("Disconnecting from MQTT broker")
        self._stopping = True
        if self._client is not None:
            self._client.loop_stop()
            self._client.disconnect()
            self._connected = False
        if self._reconnect_thread is not None:
            self._reconnect_thread.join(timeout=10)
            self._reconnect_thread = None
        self._client = None

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            _LOGGER.info(f"MQTT connected successfully (devices={len(self._device_ids)})")
            self._connected = True
            # Subscribe to per-user event topic
            user_topic = f"c/{self._user_id}/s/event"
            client.subscribe(user_topic)
            _LOGGER.debug(f"Subscribed to {user_topic}")
            # Subscribe to all registered devices
            for device_uuid in self._device_ids:
                self._subscribe_device(device_uuid)
            if self.on_connect_callback:
                self.on_connect_callback()
        else:
            _LOGGER.error(f"MQTT connection failed: reason_code={reason_code}")

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        self._connected = False
        if reason_code == 0 or self._stopping:
            _LOGGER.info("MQTT disconnected cleanly")
            if self.on_disconnect_callback:
                self.on_disconnect_callback()
            return

        _LOGGER.warning(f"MQTT disconnected unexpectedly: reason_code={reason_code}")
        if self.on_disconnect_callback:
            self.on_disconnect_callback()

        # Start reconnect with credential refresh in a background thread.
        # We don't call loop_stop() here because we're on paho's network
        # thread — it will exit naturally after this callback returns.
        if self._reconnect_thread is None or not self._reconnect_thread.is_alive():
            self._reconnect_thread = threading.Thread(
                target=self._reconnect_loop, daemon=True
            )
            self._reconnect_thread.start()

    def _reconnect_loop(self) -> None:
        """Reconnect with exponential backoff, refreshing credentials each attempt."""
        delay = _RECONNECT_INITIAL_DELAY
        broker = AWS_MQTT_BROKERS.get(self._region)
        if broker is None:
            _LOGGER.error(f"No MQTT broker for region {self._region}; cannot reconnect")
            return
        attempt = 0

        while not self._stopping:
            attempt += 1
            _LOGGER.info(f"MQTT reconnect attempt {attempt} in {delay}s...")
            time.sleep(delay)
            if self._stopping:
                _LOGGER.info("MQTT reconnect cancelled (shutting down)")
                return

            # Paho's loop_start() may have auto-reconnected with stale
            # credentials while we were sleeping. If so, tear it down
            # and replace with a fresh-credential connection.
            if self._connected:
                _LOGGER.info(
                    "MQTT auto-reconnected with existing credentials; "
                    "replacing with fresh credentials"
                )

            # Clean up the old client. By now paho's network thread has
            # exited (we slept long enough), so loop_stop() is safe.
            if self._client is not None:
                self._client.loop_stop()
                self._client = None

            # Refresh credentials if a refresher is available.
            if self.credential_refresher and self._event_loop:
                try:
                    future = asyncio.run_coroutine_threadsafe(
                        self.credential_refresher(), self._event_loop
                    )
                    new_name, new_sig, new_token = future.result(timeout=30)
                    self._mqtt_auth_name = new_name
                    self._mqtt_auth_signature = new_sig
                    self._mqtt_auth_token = new_token
                    _LOGGER.info("MQTT credentials refreshed successfully")
                except Exception:
                    _LOGGER.exception(
                        f"Failed to refresh MQTT credentials (attempt {attempt}), "
                        f"next retry in {min(delay * _RECONNECT_BACKOFF_FACTOR, _RECONNECT_MAX_DELAY)}s"
                    )
                    delay = min(delay * _RECONNECT_BACKOFF_FACTOR, _RECONNECT_MAX_DELAY)
                    continue
            elif not self.credential_refresher:
                _LOGGER.warning(
                    "No credential_refresher configured; reconnecting with existing tokens "
                    "(may fail if tokens have expired)"
                )

            try:
                self._client = self._build_client()
                self._client.connect(broker, 443, keepalive=60)
                self._client.loop_start()
                _LOGGER.info(f"MQTT reconnected with fresh credentials (attempt {attempt})")
                return
            except Exception:
                _LOGGER.exception(
                    f"MQTT reconnect attempt {attempt} failed, "
                    f"next retry in {min(delay * _RECONNECT_BACKOFF_FACTOR, _RECONNECT_MAX_DELAY)}s"
                )
                delay = min(delay * _RECONNECT_BACKOFF_FACTOR, _RECONNECT_MAX_DELAY)

    def _on_subscribe(self, client, userdata, mid, reason_codes, properties):
        _LOGGER.debug(f"MQTT subscription confirmed (mid={mid})")

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        try:
            payload = json.loads(msg.payload.decode())
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            _LOGGER.warning(f"Failed to parse MQTT message on {topic}: {e}")
            return

        if topic.startswith("d/") and "/s/5s" in topic:
            self._handle_sensor_data(topic, payload)
        elif "$aws/things" in topic:
            self._handle_state_change(topic, payload)
        elif topic.endswith("/event"):
            self._handle_event(topic, payload)
        else:
            _LOGGER.debug(f"Unhandled MQTT topic: {topic}")

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
                _LOGGER.exception(f"Error in on_sensor_data callback for {device_id}")

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
        state = (
            payload
            .get("current", {})
            .get("state", {})
            .get("reported", {})
        )

        _LOGGER.debug(f"State change for {device_id}: {state}")
        if self.on_state_change:
            try:
                self.on_state_change(device_id, state)
            except Exception:
                _LOGGER.exception(f"Error in on_state_change callback for {device_id}")

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
        _LOGGER.info(f"Device event for {device_id}: {event_type} ({payload.get('m', '')})")
        if self.on_event:
            try:
                self.on_event(device_id, payload)
            except Exception:
                _LOGGER.exception(f"Error in on_event callback for {device_id}")

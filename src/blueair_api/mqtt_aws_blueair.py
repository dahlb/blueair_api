"""MQTT client for Blueair AWS IoT real-time updates.

Connects to the Blueair cloud MQTT broker via WebSocket Secure (WSS)
using credentials from the existing c/login API response. Provides
real-time sensor data and device state change callbacks.

MQTT broker endpoints and authentication flow determined through
investigation of the Blueair cloud API responses and AWS IoT
protocol behavior.
"""
import json
import ssl
import uuid
import threading
from logging import getLogger
from typing import Any
from collections.abc import Callable

import paho.mqtt.client as mqtt

from .const import AWS_MQTT_BROKERS

_LOGGER = getLogger(__name__)

# Callback type aliases
SensorCallback = Callable[[str, dict[str, float]], None]
StateCallback = Callable[[str, dict[str, Any]], None]
EventCallback = Callable[[str, dict[str, Any]], None]


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

        self._client: mqtt.Client | None = None
        self._connected = False
        self._thread: threading.Thread | None = None

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

    def connect(self) -> None:
        """Connect to the MQTT broker and start the message loop in a background thread."""
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

        self._client = client
        client.connect(broker, 443, keepalive=60)

        # Run the network loop in a daemon thread so it doesn't block
        self._thread = threading.Thread(target=client.loop_forever, daemon=True)
        self._thread.start()

    def disconnect(self) -> None:
        """Disconnect from the MQTT broker."""
        _LOGGER.info("Disconnecting from MQTT broker")
        if self._client is not None:
            self._client.disconnect()
            self._connected = False
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
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
        if reason_code == 0:
            _LOGGER.info("MQTT disconnected cleanly")
        else:
            _LOGGER.warning(f"MQTT disconnected unexpectedly: reason_code={reason_code}")
        self._connected = False
        if self.on_disconnect_callback:
            self.on_disconnect_callback()

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

"""MQTT client for Blueair AWS IoT real-time updates.

Connects to the Blueair cloud MQTT broker via WebSocket Secure (WSS)
using credentials from the existing c/login API response. Provides
real-time sensor data and device state change callbacks.

The client runs on the asyncio event loop through aiomqtt: there is no
network thread, and every callback is called on the loop. On an
unexpected disconnect it reconnects with exponential backoff, refreshing
credentials before each attempt (tokens expire after 24 hours); the
WebSocket headers are read on every handshake, so the new tokens are
used automatically.

MQTT broker endpoints and authentication flow determined through
investigation of the Blueair cloud API responses and AWS IoT
protocol behavior.
"""

import asyncio
from collections.abc import Callable, Coroutine
import contextlib
import json
from logging import getLogger
import ssl
from typing import Any
import uuid

import aiomqtt

from .const import AWS_MQTT_BROKERS, MQTT_CREDENTIAL_REFRESH_TIMEOUT_SECONDS

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

# Reconnect backoff after an unexpected disconnect, in seconds.
_RECONNECT_MIN_DELAY = 5
_RECONNECT_MAX_DELAY = 300

# AWS IoT keepalive, in seconds.
_KEEPALIVE = 60


def _create_ssl_context() -> ssl.SSLContext:
    """Create the TLS context for the broker's WebSocket.

    Loading the system CA certificates reads files, so ``connect`` calls this
    in an executor rather than on the event loop.

    Returns:
        ssl.SSLContext: A context that verifies the broker's certificate.
    """
    return ssl.create_default_context()


class MqttAwsBlueair:
    """Asyncio MQTT client for real-time Blueair device updates via AWS IoT.

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
        await mqtt_client.connect()
        # ...
        await mqtt_client.disconnect()

    Callbacks are called on the event loop that ran ``connect``.

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
        """Store connection details; await ``connect()`` to open the MQTT link."""
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

        self._client: aiomqtt.Client | None = None
        self._connected = False
        self._stopping = False
        self._sensor_ttl: int = _DEFAULT_SENSOR_TTL
        self._run_task: asyncio.Task[None] | None = None
        self._resubscribe_task: asyncio.Task[None] | None = None
        # Subscriptions started outside the message loop; kept so they are
        # not garbage collected before they finish.
        self._background_tasks: set[asyncio.Task[None]] = set()

    @property
    def connected(self) -> bool:
        """Whether the client currently has an open MQTT connection."""
        return self._connected

    def register_device(self, device_uuid: str) -> None:
        """Register a device UUID to subscribe to its topics.

        Call this from the event loop. A device registered while connected is
        subscribed straight away.

        Args:
            device_uuid: The device's UUID.
        """
        if device_uuid not in self._device_ids:
            self._device_ids.append(device_uuid)
            _LOGGER.debug("Registered device %s (total: %s)", device_uuid, len(self._device_ids))
            # If already connected, subscribe to the new device immediately
            if self._connected and self._client is not None:
                self._start_background(self._subscribe_device(self._client, device_uuid))

    def _start_background(self, coroutine: Coroutine[Any, Any, None]) -> None:
        """Run a coroutine as a task and keep a reference until it finishes.

        Args:
            coroutine: The coroutine to run.
        """
        task = asyncio.get_running_loop().create_task(coroutine)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _subscribe(self, client: aiomqtt.Client, topic: str) -> None:
        """Subscribe to a topic, logging rather than raising on failure.

        A failed subscription is retried on the next connection.

        Args:
            client: The connected client.
            topic: The topic to subscribe to.
        """
        try:
            await client.subscribe(topic)
        except aiomqtt.MqttError as error:
            _LOGGER.warning("Failed to subscribe to %s: %s", topic, error)
            return
        _LOGGER.debug("Subscribed to %s", topic)

    async def _subscribe_device(self, client: aiomqtt.Client, device_uuid: str) -> None:
        """Subscribe to MQTT topics for a single device.

        Args:
            client: The connected client.
            device_uuid: The device's UUID.
        """
        for topic in (
            f"d/{device_uuid}/s/5s",
            f"$aws/things/{device_uuid}/shadow/update/documents",
        ):
            await self._subscribe(client, topic)

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

    async def _resubscribe_sensor_topics(self, client: aiomqtt.Client) -> None:
        """Re-subscribe to sensor topics for all devices.

        This resets the device-side TTL countdown, keeping the 5-second
        sensor data stream alive.  Per MQTT spec, subscribing to an
        already-subscribed topic is idempotent (broker sends SUBACK and
        the subscription stays active).  We intentionally do NOT
        unsubscribe first — the unsubscribe kills the device's data
        push and the immediate re-subscribe doesn't always restart it.

        Args:
            client: The connected client.
        """
        for device_uuid in list(self._device_ids):
            await self._subscribe(client, f"d/{device_uuid}/s/5s")

    async def _resubscribe_periodically(self, client: aiomqtt.Client) -> None:
        """Re-subscribe to the sensor topics at 75% of the sensor TTL, until cancelled.

        Args:
            client: The connected client.
        """
        while True:
            await asyncio.sleep(self._resubscribe_interval)
            _LOGGER.debug(
                "Sensor TTL keepalive: re-subscribing to sensor topics for %s device(s)",
                len(self._device_ids),
            )
            await self._resubscribe_sensor_topics(client)

    @property
    def _resubscribe_interval(self) -> int:
        """Seconds between sensor topic re-subscriptions (at least 1)."""
        return max(1, int(self._sensor_ttl * _TTL_RESUBSCRIBE_RATIO))

    def _cancel_resubscribe_task(self) -> None:
        """Stop the periodic re-subscribe task if it is running."""
        if self._resubscribe_task is not None:
            self._resubscribe_task.cancel()
            self._resubscribe_task = None

    def _get_ws_headers(self, default_headers: dict[str, str]) -> dict[str, str]:
        """Return WebSocket headers with the current auth credentials.

        Called on every WebSocket handshake (including reconnects).

        Args:
            default_headers: The handshake's default headers.

        Returns:
            dict[str, str]: The headers with the AWS IoT custom authorizer added.
        """
        default_headers["X-Amz-CustomAuthorizer-Name"] = self._mqtt_auth_name
        default_headers["X-Amz-CustomAuthorizer-Signature"] = self._mqtt_auth_signature
        default_headers["X-Amz-CustomAuthorizer-Token"] = self._mqtt_auth_token
        return default_headers

    async def _refresh_credentials(self) -> None:
        """Refresh credentials before a reconnection attempt.

        The wait is bounded by ``MQTT_CREDENTIAL_REFRESH_TIMEOUT_SECONDS``,
        long enough for a full re-authentication. A refresh that fails or runs
        past it is abandoned, and the attempt goes ahead with the previous
        tokens.
        """
        if not self.credential_refresher:
            _LOGGER.debug(
                "MQTT reconnect: no credential_refresher configured, using existing tokens"
            )
            return
        try:
            async with asyncio.timeout(MQTT_CREDENTIAL_REFRESH_TIMEOUT_SECONDS):
                new_name, new_sig, new_token = await self.credential_refresher()
        except TimeoutError:
            _LOGGER.warning(
                "MQTT credential refresh did not finish within %s seconds; "
                "will attempt reconnect with previous (possibly stale) tokens",
                MQTT_CREDENTIAL_REFRESH_TIMEOUT_SECONDS,
            )
            return
        except Exception:
            # The refresher is the caller's code, so any failure is logged and
            # the reconnect goes ahead rather than ending the reconnect loop.
            _LOGGER.exception(
                "Failed to refresh MQTT credentials; "
                "will attempt reconnect with previous (possibly stale) tokens"
            )
            return
        self._mqtt_auth_name = new_name
        self._mqtt_auth_signature = new_sig
        self._mqtt_auth_token = new_token
        _LOGGER.info("MQTT credentials refreshed successfully before reconnect")

    def _build_client(self, broker: str, tls_context: ssl.SSLContext) -> aiomqtt.Client:
        """Create the aiomqtt client; it is reused for every reconnect.

        Args:
            broker: The region's broker host name.
            tls_context: TLS context for the WebSocket.

        Returns:
            aiomqtt.Client: The client, not yet connected.
        """
        return aiomqtt.Client(
            broker,
            443,
            identifier=self._client_id,
            transport="websockets",
            keepalive=_KEEPALIVE,
            tls_context=tls_context,
            websocket_path="/mqtt",
            # AWS IoT Custom Authorizer headers — a callable, so each
            # (re)connect's handshake uses the latest tokens.
            websocket_headers=self._get_ws_headers,
            # Route paho's internal logging (PINGREQ/PINGRESP, CONNACK
            # details) through Python's standard logging.
            logger=_LOGGER,
        )

    async def connect(self) -> None:
        """Connect to the MQTT broker and start receiving messages.

        Returns once the first connection is up. After that the client keeps
        reconnecting on its own until ``disconnect()``.

        Raises:
            ValueError: No broker is configured for the region.
            aiomqtt.MqttError: The first connection attempt failed.
        """
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

        self._stopping = False
        loop = asyncio.get_running_loop()
        tls_context = await loop.run_in_executor(None, _create_ssl_context)
        client = self._build_client(broker, tls_context)
        self._client = client
        first_connection: asyncio.Future[None] = loop.create_future()
        self._run_task = loop.create_task(self._run(client, first_connection))
        try:
            await first_connection
        except BaseException:
            await self.disconnect()
            raise

    async def _run(self, client: aiomqtt.Client, first_connection: asyncio.Future[None]) -> None:
        """Receive messages, reconnecting with backoff after unexpected disconnects.

        Args:
            client: The client to connect with.
            first_connection: Resolved when the first connection is up, or
                failed with the first attempt's error (which ends the task).
        """
        delay = _RECONNECT_MIN_DELAY
        while not self._stopping:
            error: aiomqtt.MqttError | None = None
            try:
                async with client:
                    await self._on_connect(client)
                    if not first_connection.done():
                        first_connection.set_result(None)
                    delay = _RECONNECT_MIN_DELAY
                    async for message in client.messages:
                        await self._on_message(str(message.topic), message.payload)
            except aiomqtt.MqttError as exc:
                if not first_connection.done():
                    first_connection.set_exception(exc)
                    return
                error = exc
            if self._stopping:
                return
            self._on_disconnect(error)
            _LOGGER.info("MQTT reconnecting in %s seconds", delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, _RECONNECT_MAX_DELAY)
            await self._refresh_credentials()

    async def disconnect(self) -> None:
        """Disconnect from the MQTT broker and stop reconnecting."""
        _LOGGER.info("Disconnecting from MQTT broker")
        self._stopping = True
        self._cancel_resubscribe_task()
        for task in list(self._background_tasks):
            task.cancel()
        run_task, self._run_task = self._run_task, None
        if run_task is not None and not run_task.done():
            # Cancelling leaves the client's context, which disconnects cleanly.
            run_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await run_task
        self._connected = False
        self._client = None

    async def _on_connect(self, client: aiomqtt.Client) -> None:
        """Subscribe to every topic once a connection is up.

        Args:
            client: The connected client.
        """
        _LOGGER.info("MQTT connected successfully (devices=%s)", len(self._device_ids))
        self._connected = True
        # Subscribe to per-user event topic
        await self._subscribe(client, f"c/{self._user_id}/s/event")
        # Subscribe to all registered devices
        for device_uuid in list(self._device_ids):
            await self._subscribe_device(client, device_uuid)
        # Start the periodic re-subscribe task to keep sensor
        # data streams alive (resets the device-side TTL).
        self._cancel_resubscribe_task()
        if self._sensor_ttl > 0:
            _LOGGER.debug(
                "Starting sensor re-subscribe task (every %ss, TTL=%ss)",
                self._resubscribe_interval,
                self._sensor_ttl,
            )
            self._resubscribe_task = asyncio.get_running_loop().create_task(
                self._resubscribe_periodically(client)
            )
        if self.on_connect_callback:
            self.on_connect_callback()

    def _on_disconnect(self, error: aiomqtt.MqttError | None) -> None:
        """Record an unexpected disconnect.

        Args:
            error: Why the connection ended, if known.
        """
        self._connected = False
        self._cancel_resubscribe_task()
        _LOGGER.info(
            "MQTT disconnected unexpectedly: %s; will reconnect with credential refresh",
            error,
        )
        if self.on_disconnect_callback:
            self.on_disconnect_callback()

    async def _on_message(self, topic: str, raw_payload: Any) -> None:
        """Parse an incoming MQTT message and dispatch it by topic.

        Args:
            topic: The message's topic.
            raw_payload: The message's payload.
        """
        try:
            if isinstance(raw_payload, bytes | bytearray):
                raw_payload = raw_payload.decode()
            payload = json.loads(raw_payload)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as e:
            _LOGGER.warning("Failed to parse MQTT message on %s: %s", topic, e)
            return

        if topic.startswith("d/") and "/s/5s" in topic:
            self._handle_sensor_data(topic, payload)
        elif "$aws/things" in topic:
            self._handle_state_change(topic, payload)
        elif topic.endswith("/event"):
            await self._handle_event(topic, payload)
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

    async def _handle_event(self, topic: str, payload: Any) -> None:
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
        client = self._client
        if event_type == "Connected" and device_id in self._device_ids and client is not None:
            topic = f"d/{device_id}/s/5s"
            await self._subscribe(client, topic)
            _LOGGER.info("Re-subscribed to %s (device Connected event)", topic)

        if self.on_event:
            try:
                self.on_event(device_id, payload)
            except Exception:
                _LOGGER.exception("Error in on_event callback for %s", device_id)

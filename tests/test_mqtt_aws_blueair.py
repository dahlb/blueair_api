"""Tests for MqttAwsBlueair.

The aiomqtt client is replaced with a fake, so these tests cover message
parsing, topic routing, callback dispatch, device registration, and
reconnecting with credential refresh, all on the event loop.
"""

import asyncio
from collections.abc import AsyncIterator
import json
import logging
from types import SimpleNamespace
from typing import Any, ClassVar, Self

import aiomqtt
import pytest

import blueair_api
from blueair_api import mqtt_aws_blueair
from blueair_api.const import AWS_MQTT_BROKERS
from blueair_api.mqtt_aws_blueair import MqttAwsBlueair

FAKE_DEVICE_UUID = "14ad6685-408a-4aa2-a923-a561e0872cc4"
FAKE_USER_ID = "52da8f11-6303-45bb-a06f-658b0a126917"
SENSOR_TOPIC = f"d/{FAKE_DEVICE_UUID}/s/5s"
SHADOW_TOPIC = f"$aws/things/{FAKE_DEVICE_UUID}/shadow/update/documents"
EVENT_TOPIC = f"c/{FAKE_USER_ID}/s/event"
CONNECTION_LOST = aiomqtt.MqttError("connection lost")


class FakeClient:
    """Stand-in for aiomqtt.Client, driven by the test.

    ``connect_errors`` makes the next connection attempts fail, in order.
    ``disconnect`` ends the message stream the way a dropped connection does.
    """

    instances: ClassVar[list[FakeClient]] = []
    connect_errors: ClassVar[list[BaseException]] = []

    def __init__(self, hostname: str, port: int, **kwargs: Any) -> None:
        self.hostname = hostname
        self.port = port
        self.kwargs = kwargs
        self.subscriptions: list[str] = []
        self.subscribe_error: BaseException | None = None
        self.connects = 0
        self.exits = 0
        self.handshake_headers: list[dict[str, str]] = []
        self._queue: asyncio.Queue[Any] = asyncio.Queue()
        FakeClient.instances.append(self)

    async def __aenter__(self) -> Self:
        if FakeClient.connect_errors:
            raise FakeClient.connect_errors.pop(0)
        self.connects += 1
        self.handshake_headers.append(self.kwargs["websocket_headers"]({}))
        return self

    async def __aexit__(self, *args: object) -> None:
        self.exits += 1

    async def subscribe(self, topic: str) -> None:
        if self.subscribe_error is not None:
            raise self.subscribe_error
        self.subscriptions.append(topic)

    @property
    def messages(self) -> AsyncIterator[Any]:
        return self._messages()

    async def _messages(self) -> AsyncIterator[Any]:
        while True:
            item = await self._queue.get()
            if item is None:
                return
            if isinstance(item, BaseException):
                raise item
            yield item

    def deliver(self, topic: str, payload: Any) -> None:
        """Queue a message whose payload is JSON-encoded bytes."""
        self._queue.put_nowait(SimpleNamespace(topic=topic, payload=json.dumps(payload).encode()))

    def drop(self, error: BaseException | None = CONNECTION_LOST) -> None:
        """End the connection: with an error, or (None) by ending the stream."""
        self._queue.put_nowait(error)


@pytest.fixture(autouse=True)
def fake_aiomqtt(monkeypatch: pytest.MonkeyPatch) -> type[FakeClient]:
    FakeClient.instances = []
    FakeClient.connect_errors = []
    monkeypatch.setattr("blueair_api.mqtt_aws_blueair.aiomqtt.Client", FakeClient)
    monkeypatch.setattr(mqtt_aws_blueair, "_RECONNECT_MIN_DELAY", 0)
    return FakeClient


def make_mqtt_client(**kwargs: Any) -> MqttAwsBlueair:
    return MqttAwsBlueair(
        region="us",
        mqtt_auth_name="custom-authorizer",
        mqtt_auth_signature="fake-signature",
        mqtt_auth_token="fake-token",
        user_id=FAKE_USER_ID,
        **kwargs,
    )


async def wait_for(condition: Any) -> None:
    """Let the event loop run until a condition holds."""
    async with asyncio.timeout(2):
        # Polls state the fakes change; there is no event to wait on.
        while not condition():  # noqa: ASYNC110
            await asyncio.sleep(0)


async def deliver(client: MqttAwsBlueair, topic: str, payload: Any) -> None:
    await client._on_message(topic, json.dumps(payload).encode())


# ----- Message parsing ----------------------------------------------------


async def test_sensor_data_callback() -> None:
    client = make_mqtt_client()
    received: list[Any] = []
    client.on_sensor_data = lambda device_id, sensors: received.append((device_id, sensors))

    await deliver(
        client,
        SENSOR_TOPIC,
        [{"n": "pm2_5", "v": 3.0}, {"n": "fsp0", "v": 11.0}, {"n": "rssi", "v": -24.0}],
    )

    assert received == [(FAKE_DEVICE_UUID, {"pm2_5": 3.0, "fsp0": 11.0, "rssi": -24.0})]


async def test_sensor_data_empty_list() -> None:
    client = make_mqtt_client()
    received: list[Any] = []
    client.on_sensor_data = lambda device_id, sensors: received.append((device_id, sensors))

    await deliver(client, SENSOR_TOPIC, [])

    assert received == [(FAKE_DEVICE_UUID, {})]


async def test_sensor_data_without_callbacks_does_not_raise() -> None:
    client = make_mqtt_client()

    await deliver(client, SENSOR_TOPIC, [{"n": "pm2_5", "v": 5.0}])
    await deliver(client, SHADOW_TOPIC, {"current": {"state": {"reported": {}}}})
    await deliver(client, EVENT_TOPIC, {"et": "Connected", "o": FAKE_DEVICE_UUID})


async def test_non_list_sensor_payload_reports_no_sensors() -> None:
    client = make_mqtt_client()
    received: list[Any] = []
    client.on_sensor_data = lambda device_id, sensors: received.append(sensors)

    await deliver(client, SENSOR_TOPIC, {"n": "pm2_5"})

    assert received == [{}]


async def test_state_change_callback() -> None:
    client = make_mqtt_client()
    received: list[Any] = []
    client.on_state_change = lambda device_id, state: received.append((device_id, state))

    await deliver(
        client,
        SHADOW_TOPIC,
        {
            "current": {"state": {"reported": {"fanspeed": 51, "standby": False}}},
            "previous": {},
        },
    )

    assert received == [(FAKE_DEVICE_UUID, {"fanspeed": 51, "standby": False})]


@pytest.mark.parametrize(
    "payload", [{"current": {"state": {"reported": {}}}}, {"unexpected": "format"}]
)
async def test_state_change_without_reported_state(payload: dict[str, Any]) -> None:
    client = make_mqtt_client()
    received: list[Any] = []
    client.on_state_change = lambda device_id, state: received.append(state)

    await deliver(client, SHADOW_TOPIC, payload)

    assert received == [{}]


async def test_state_change_with_non_dict_payload_is_ignored() -> None:
    client = make_mqtt_client()
    received: list[Any] = []
    client.on_state_change = lambda device_id, state: received.append(state)

    await deliver(client, SHADOW_TOPIC, ["not", "a", "dict"])

    assert received == []


@pytest.mark.parametrize("event_type", ["Connected", "NotConnected"])
async def test_event_callback(event_type: str) -> None:
    client = make_mqtt_client()
    received: list[Any] = []
    client.on_event = lambda device_id, event: received.append((device_id, event))
    payload = {"et": event_type, "o": FAKE_DEVICE_UUID, "m": "Device is Online", "ec": 0}

    await deliver(client, EVENT_TOPIC, payload)

    assert received == [(FAKE_DEVICE_UUID, payload)]


async def test_event_missing_origin_device() -> None:
    client = make_mqtt_client()
    received: list[Any] = []
    client.on_event = lambda device_id, event: received.append(device_id)

    await deliver(client, EVENT_TOPIC, {"et": "NotConnected"})

    assert received == [""]


async def test_event_with_non_dict_payload_is_ignored() -> None:
    client = make_mqtt_client()
    received: list[Any] = []
    client.on_event = lambda device_id, event: received.append(event)

    await deliver(client, EVENT_TOPIC, ["not", "a", "dict"])

    assert received == []


@pytest.mark.parametrize("raw", [b"not json", b"\xff\xfe", None])
async def test_unparsable_payload_is_logged(raw: Any, caplog: pytest.LogCaptureFixture) -> None:
    client = make_mqtt_client()
    received: list[Any] = []
    client.on_sensor_data = lambda device_id, sensors: received.append(sensors)

    await client._on_message(SENSOR_TOPIC, raw)

    assert received == []
    assert "Failed to parse MQTT message" in caplog.text


async def test_string_payload_is_parsed() -> None:
    client = make_mqtt_client()
    received: list[Any] = []
    client.on_sensor_data = lambda device_id, sensors: received.append(sensors)

    await client._on_message(SENSOR_TOPIC, json.dumps([{"n": "voc", "v": 1}]))

    assert received == [{"voc": 1}]


async def test_unhandled_topic_is_ignored(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    client = make_mqtt_client()

    await deliver(client, "x/unknown", {})

    assert "Unhandled MQTT topic" in caplog.text


async def test_callback_errors_are_logged(caplog: pytest.LogCaptureFixture) -> None:
    client = make_mqtt_client()

    def fail(*args: Any) -> None:
        raise RuntimeError("boom")

    client.on_sensor_data = fail
    client.on_state_change = fail
    client.on_event = fail

    await deliver(client, SENSOR_TOPIC, [])
    await deliver(client, SHADOW_TOPIC, {})
    await deliver(client, EVENT_TOPIC, {"o": FAKE_DEVICE_UUID})

    for name in ("on_sensor_data", "on_state_change", "on_event"):
        assert f"Error in {name} callback" in caplog.text


# ----- Registration and TTL ------------------------------------------------


async def test_register_device_dedup() -> None:
    client = make_mqtt_client()

    client.register_device(FAKE_DEVICE_UUID)
    client.register_device(FAKE_DEVICE_UUID)

    assert client._device_ids == [FAKE_DEVICE_UUID]


def test_set_sensor_ttl() -> None:
    client = make_mqtt_client()
    assert client._sensor_ttl == 1200
    assert client._resubscribe_interval == 900

    client.set_sensor_ttl(600)
    assert client._sensor_ttl == 600

    client.set_sensor_ttl(0)
    client.set_sensor_ttl(-5)
    assert client._sensor_ttl == 600

    client.set_sensor_ttl(1)
    # Never re-subscribe in a tight loop.
    assert client._resubscribe_interval == 1


# ----- Connecting ----------------------------------------------------------


async def test_connect_builds_the_websocket_client_and_subscribes() -> None:
    client = make_mqtt_client()
    client.register_device(FAKE_DEVICE_UUID)
    connects: list[bool] = []
    client.on_connect_callback = lambda: connects.append(True)

    await client.connect()

    fake = FakeClient.instances[0]
    assert fake.hostname == AWS_MQTT_BROKERS["us"]
    assert fake.port == 443
    assert fake.kwargs["transport"] == "websockets"
    assert fake.kwargs["websocket_path"] == "/mqtt"
    assert fake.kwargs["identifier"] == client._client_id
    assert fake.kwargs["tls_context"] is not None
    assert fake.handshake_headers == [
        {
            "X-Amz-CustomAuthorizer-Name": "custom-authorizer",
            "X-Amz-CustomAuthorizer-Signature": "fake-signature",
            "X-Amz-CustomAuthorizer-Token": "fake-token",
        }
    ]
    assert fake.subscriptions == [EVENT_TOPIC, SENSOR_TOPIC, SHADOW_TOPIC]
    assert client.connected
    assert connects == [True]
    assert client._resubscribe_task is not None

    await client.disconnect()


async def test_connect_rejects_an_unknown_region() -> None:
    client = MqttAwsBlueair(
        region="nowhere",
        mqtt_auth_name="n",
        mqtt_auth_signature="s",
        mqtt_auth_token="t",
        user_id=FAKE_USER_ID,
    )

    with pytest.raises(ValueError, match="nowhere"):
        await client.connect()


async def test_connect_logs_missing_credentials(caplog: pytest.LogCaptureFixture) -> None:
    client = MqttAwsBlueair(
        region="us", mqtt_auth_name="", mqtt_auth_signature="", mqtt_auth_token="", user_id=""
    )

    await client.connect()

    assert "MQTT auth credentials missing" in caplog.text
    await client.disconnect()


async def test_first_connection_failure_is_raised() -> None:
    client = make_mqtt_client()
    FakeClient.connect_errors = [aiomqtt.MqttError("refused")]

    # Callers catch the package's export without importing aiomqtt.
    with pytest.raises(blueair_api.MqttError, match="refused"):
        await client.connect()

    assert not client.connected
    assert client._run_task is None


def test_mqtt_error_is_aiomqtts() -> None:
    """Export aiomqtt's MqttError, so catching it catches every aiomqtt failure."""
    assert blueair_api.MqttError is aiomqtt.MqttError
    assert "MqttError" in blueair_api.__all__


async def test_registering_while_connected_subscribes() -> None:
    client = make_mqtt_client()
    await client.connect()
    fake = FakeClient.instances[0]

    client.register_device(FAKE_DEVICE_UUID)
    await wait_for(lambda: SHADOW_TOPIC in fake.subscriptions)

    assert fake.subscriptions == [EVENT_TOPIC, SENSOR_TOPIC, SHADOW_TOPIC]
    await client.disconnect()


async def test_subscribe_failures_are_logged(caplog: pytest.LogCaptureFixture) -> None:
    client = make_mqtt_client()
    client.register_device(FAKE_DEVICE_UUID)
    await client.connect()
    fake = FakeClient.instances[0]
    fake.subscribe_error = aiomqtt.MqttError("no suback")

    await client._resubscribe_sensor_topics(fake)  # type: ignore[arg-type]

    assert f"Failed to subscribe to {SENSOR_TOPIC}" in caplog.text
    await client.disconnect()


async def test_messages_are_dispatched_on_the_loop() -> None:
    client = make_mqtt_client()
    received: list[Any] = []
    client.on_sensor_data = lambda device_id, sensors: received.append(sensors)
    await client.connect()

    FakeClient.instances[0].deliver(SENSOR_TOPIC, [{"n": "pm1", "v": 2}])
    await wait_for(lambda: received)

    assert received == [{"pm1": 2}]
    await client.disconnect()


async def test_connected_event_resubscribes_the_sensor_topic() -> None:
    client = make_mqtt_client()
    client.register_device(FAKE_DEVICE_UUID)
    await client.connect()
    fake = FakeClient.instances[0]
    fake.subscriptions.clear()

    fake.deliver(EVENT_TOPIC, {"et": "Connected", "o": FAKE_DEVICE_UUID})
    fake.deliver(EVENT_TOPIC, {"et": "Connected", "o": "someone-else"})
    await wait_for(lambda: fake.subscriptions)
    await asyncio.sleep(0)

    assert fake.subscriptions == [SENSOR_TOPIC]
    await client.disconnect()


async def test_periodic_resubscribe_keeps_the_sensor_stream_alive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_mqtt_client()
    client.register_device(FAKE_DEVICE_UUID)
    resubscribes: list[Any] = []

    async def resubscribe(fake: Any) -> None:
        resubscribes.append(fake)

    monkeypatch.setattr(client, "_resubscribe_sensor_topics", resubscribe)
    monkeypatch.setattr(MqttAwsBlueair, "_resubscribe_interval", 0)
    await client.connect()

    await wait_for(lambda: len(resubscribes) >= 2)

    assert resubscribes[0] is FakeClient.instances[0]
    await client.disconnect()
    assert client._resubscribe_task is None


async def test_disconnect_stops_the_client() -> None:
    client = make_mqtt_client()
    await client.connect()
    run_task = client._run_task

    await client.disconnect()

    assert not client.connected
    assert run_task is not None
    assert run_task.done()
    assert FakeClient.instances[0].exits == 1
    assert client._client is None


async def test_disconnect_without_connect_is_safe() -> None:
    client = make_mqtt_client()

    await client.disconnect()

    assert not client.connected


# ----- Reconnecting ----------------------------------------------------------


@pytest.mark.parametrize("error", [aiomqtt.MqttError("connection lost"), None])
async def test_reconnects_with_refreshed_credentials(error: BaseException | None) -> None:
    client = make_mqtt_client()
    client.register_device(FAKE_DEVICE_UUID)
    disconnects: list[bool] = []
    client.on_disconnect_callback = lambda: disconnects.append(True)

    async def refresh() -> tuple[str, str, str]:
        return ("new-name", "new-signature", "new-token")

    client.credential_refresher = refresh
    await client.connect()
    fake = FakeClient.instances[0]

    fake.drop(error)
    await wait_for(lambda: fake.connects == 2)

    assert disconnects == [True]
    assert fake.handshake_headers[-1] == {
        "X-Amz-CustomAuthorizer-Name": "new-name",
        "X-Amz-CustomAuthorizer-Signature": "new-signature",
        "X-Amz-CustomAuthorizer-Token": "new-token",
    }
    assert fake.subscriptions.count(SENSOR_TOPIC) == 2
    assert client.connected
    await client.disconnect()


async def test_reconnect_keeps_trying_after_failed_attempts() -> None:
    client = make_mqtt_client()
    await client.connect()
    fake = FakeClient.instances[0]
    FakeClient.connect_errors = [aiomqtt.MqttError("refused"), aiomqtt.MqttError("refused")]

    fake.drop()
    await wait_for(lambda: fake.connects == 2)

    assert client.connected
    assert FakeClient.connect_errors == []
    await client.disconnect()


async def test_reconnect_backoff_doubles_up_to_the_maximum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delays: list[float] = []
    real_sleep = asyncio.sleep

    async def record_sleep(delay: float) -> None:
        delays.append(delay)
        await real_sleep(0)

    monkeypatch.setattr(mqtt_aws_blueair, "_RECONNECT_MIN_DELAY", 100)
    monkeypatch.setattr("blueair_api.mqtt_aws_blueair.asyncio.sleep", record_sleep)
    client = make_mqtt_client()
    client.set_sensor_ttl(10**9)
    await client.connect()
    fake = FakeClient.instances[0]
    FakeClient.connect_errors = [aiomqtt.MqttError("refused")] * 3

    fake.drop()
    await wait_for(lambda: fake.connects == 2)
    # Zero-second sleeps are this test's own polling.
    reconnect_delays = [delay for delay in delays if 0 < delay < 10**8]

    assert reconnect_delays == [100, 200, 300, 300]
    await client.disconnect()


async def test_reconnect_without_refresher_keeps_credentials() -> None:
    client = make_mqtt_client()
    await client.connect()
    fake = FakeClient.instances[0]

    fake.drop()
    await wait_for(lambda: fake.connects == 2)

    assert fake.handshake_headers[-1] == fake.handshake_headers[0]
    await client.disconnect()


async def test_failed_refresh_reconnects_with_old_credentials(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = make_mqtt_client()

    async def refresh() -> tuple[str, str, str]:
        raise RuntimeError("login failed")

    client.credential_refresher = refresh
    await client.connect()
    fake = FakeClient.instances[0]

    fake.drop()
    await wait_for(lambda: fake.connects == 2)

    assert fake.handshake_headers[-1]["X-Amz-CustomAuthorizer-Token"] == "fake-token"
    assert "Failed to refresh MQTT credentials" in caplog.text
    await client.disconnect()


async def test_slow_refresh_is_abandoned(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(mqtt_aws_blueair, "MQTT_CREDENTIAL_REFRESH_TIMEOUT_SECONDS", 0.01)
    client = make_mqtt_client()
    cancelled: list[bool] = []

    async def refresh() -> tuple[str, str, str]:
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled.append(True)
            raise
        return ("never", "never", "never")

    client.credential_refresher = refresh
    await client.connect()
    fake = FakeClient.instances[0]

    fake.drop()
    await wait_for(lambda: fake.connects == 2)

    assert cancelled == [True]
    assert fake.handshake_headers[-1]["X-Amz-CustomAuthorizer-Token"] == "fake-token"
    assert "did not finish within" in caplog.text
    await client.disconnect()


async def test_disconnect_during_backoff_stops_reconnecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mqtt_aws_blueair, "_RECONNECT_MIN_DELAY", 60)
    client = make_mqtt_client()
    await client.connect()
    fake = FakeClient.instances[0]

    fake.drop()
    await wait_for(lambda: not client.connected)
    await client.disconnect()

    assert fake.connects == 1

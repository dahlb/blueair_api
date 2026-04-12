"""Tests for MqttAwsBlueair.

Unit tests that mock the paho-mqtt client to verify message parsing,
topic routing, callback dispatch, device registration, and reconnection
with credential refresh.
"""
import asyncio
import json
import threading
import time
from unittest import TestCase, mock

from blueair_api.mqtt_aws_blueair import MqttAwsBlueair


FAKE_DEVICE_UUID = "14ad6685-408a-4aa2-a923-a561e0872cc4"
FAKE_USER_ID = "52da8f11-6303-45bb-a06f-658b0a126917"


def make_mqtt_client(**kwargs):
    return MqttAwsBlueair(
        region="us",
        mqtt_auth_name="custom-authorizer",
        mqtt_auth_signature="fake-signature",
        mqtt_auth_token="fake-token",
        user_id=FAKE_USER_ID,
        **kwargs,
    )


def make_mqtt_message(topic: str, payload: dict | list) -> mock.MagicMock:
    msg = mock.MagicMock()
    msg.topic = topic
    msg.payload = json.dumps(payload).encode()
    return msg


class TestSensorDataParsing(TestCase):
    """Tests for sensor data message handling (d/<deviceId>/s/5s topic)."""

    def test_sensor_data_callback(self):
        client = make_mqtt_client()
        received = []
        client.on_sensor_data = lambda device_id, sensors: received.append((device_id, sensors))

        msg = make_mqtt_message(
            f"d/{FAKE_DEVICE_UUID}/s/5s",
            [{"n": "pm2_5", "v": 3.0}, {"n": "fsp0", "v": 11.0}, {"n": "rssi", "v": -24.0}],
        )
        client._on_message(None, None, msg)

        assert len(received) == 1
        device_id, sensors = received[0]
        assert device_id == FAKE_DEVICE_UUID
        assert sensors == {"pm2_5": 3.0, "fsp0": 11.0, "rssi": -24.0}

    def test_sensor_data_empty_list(self):
        client = make_mqtt_client()
        received = []
        client.on_sensor_data = lambda device_id, sensors: received.append((device_id, sensors))

        msg = make_mqtt_message(f"d/{FAKE_DEVICE_UUID}/s/5s", [])
        client._on_message(None, None, msg)

        assert len(received) == 1
        assert received[0][1] == {}

    def test_sensor_data_no_callback(self):
        """No crash when on_sensor_data is not set."""
        client = make_mqtt_client()
        msg = make_mqtt_message(f"d/{FAKE_DEVICE_UUID}/s/5s", [{"n": "pm2_5", "v": 5.0}])
        client._on_message(None, None, msg)  # should not raise


class TestStateChangeParsing(TestCase):
    """Tests for state change handling ($aws/things/<deviceId>/shadow/...)."""

    def test_state_change_callback(self):
        client = make_mqtt_client()
        received = []
        client.on_state_change = lambda device_id, state: received.append((device_id, state))

        msg = make_mqtt_message(
            f"$aws/things/{FAKE_DEVICE_UUID}/shadow/update/documents",
            {
                "current": {
                    "state": {
                        "reported": {
                            "fanspeed": 51,
                            "standby": False,
                            "brightness": 64,
                        }
                    }
                },
                "previous": {},
            },
        )
        client._on_message(None, None, msg)

        assert len(received) == 1
        device_id, state = received[0]
        assert device_id == FAKE_DEVICE_UUID
        assert state == {"fanspeed": 51, "standby": False, "brightness": 64}

    def test_state_change_empty_reported(self):
        client = make_mqtt_client()
        received = []
        client.on_state_change = lambda device_id, state: received.append((device_id, state))

        msg = make_mqtt_message(
            f"$aws/things/{FAKE_DEVICE_UUID}/shadow/update/documents",
            {"current": {"state": {"reported": {}}}},
        )
        client._on_message(None, None, msg)

        assert len(received) == 1
        assert received[0][1] == {}

    def test_state_change_missing_structure(self):
        """Gracefully handle missing nested keys."""
        client = make_mqtt_client()
        received = []
        client.on_state_change = lambda device_id, state: received.append((device_id, state))

        msg = make_mqtt_message(
            f"$aws/things/{FAKE_DEVICE_UUID}/shadow/update/documents",
            {"unexpected": "format"},
        )
        client._on_message(None, None, msg)

        assert len(received) == 1
        assert received[0][1] == {}


class TestEventParsing(TestCase):
    """Tests for connectivity event handling (c/<userId>/s/event topic)."""

    def test_event_callback(self):
        client = make_mqtt_client()
        received = []
        client.on_event = lambda device_id, event: received.append((device_id, event))

        payload = {
            "et": "Connected",
            "o": FAKE_DEVICE_UUID,
            "ts": 1751558540,
            "m": "Device is Online",
            "ot": "ConnectionEvent",
            "r": "US",
            "ec": 0,
        }
        msg = make_mqtt_message(f"c/{FAKE_USER_ID}/s/event", payload)
        client._on_message(None, None, msg)

        assert len(received) == 1
        device_id, event = received[0]
        assert device_id == FAKE_DEVICE_UUID
        assert event["et"] == "Connected"

    def test_event_not_connected(self):
        client = make_mqtt_client()
        received = []
        client.on_event = lambda device_id, event: received.append((device_id, event))

        payload = {
            "et": "NotConnected",
            "o": FAKE_DEVICE_UUID,
            "ts": 1751558600,
            "m": "Device is Offline",
            "ot": "ConnectionEvent",
            "ec": 0,
        }
        msg = make_mqtt_message(f"c/{FAKE_USER_ID}/s/event", payload)
        client._on_message(None, None, msg)

        assert len(received) == 1
        assert received[0][0] == FAKE_DEVICE_UUID
        assert received[0][1]["et"] == "NotConnected"

    def test_event_missing_origin_device(self):
        client = make_mqtt_client()
        received = []
        client.on_event = lambda device_id, event: received.append((device_id, event))

        msg = make_mqtt_message(f"c/{FAKE_USER_ID}/s/event", {"et": "NotConnected"})
        client._on_message(None, None, msg)

        assert len(received) == 1
        assert received[0][0] == ""


class TestDeviceRegistration(TestCase):
    """Tests for device registration and topic subscription."""

    def test_register_device(self):
        client = make_mqtt_client()
        client.register_device(FAKE_DEVICE_UUID)
        assert FAKE_DEVICE_UUID in client._device_ids

    def test_register_device_dedup(self):
        client = make_mqtt_client()
        client.register_device(FAKE_DEVICE_UUID)
        client.register_device(FAKE_DEVICE_UUID)
        assert client._device_ids.count(FAKE_DEVICE_UUID) == 1


class TestDisconnectReconnect(TestCase):
    """Tests for disconnect handling and reconnect with credential refresh."""

    def test_clean_disconnect_no_reconnect(self):
        """A clean disconnect (reason_code=0) should not trigger reconnect."""
        client = make_mqtt_client()
        client._stopping = False
        mock_paho = mock.MagicMock()
        client._client = mock_paho

        client._on_disconnect(mock_paho, None, None, 0, None)

        assert client._connected is False
        # No reconnect thread should be started
        assert client._reconnect_thread is None

    def test_stopping_disconnect_no_reconnect(self):
        """When _stopping is True, no reconnect should happen."""
        client = make_mqtt_client()
        client._stopping = True
        mock_paho = mock.MagicMock()
        client._client = mock_paho

        client._on_disconnect(mock_paho, None, None, 7, None)

        assert client._connected is False
        assert client._reconnect_thread is None

    def test_unexpected_disconnect_triggers_reconnect(self):
        """An unexpected disconnect should start reconnect thread."""
        client = make_mqtt_client()
        client._stopping = False
        mock_paho = mock.MagicMock()
        client._client = mock_paho

        # Prevent the reconnect thread from actually running forever
        with mock.patch.object(client, '_reconnect_loop'):
            client._on_disconnect(mock_paho, None, None, 7, None)

        assert client._connected is False
        # loop_stop is NOT called here (we're on paho's thread);
        # it happens in _reconnect_loop instead.
        mock_paho.loop_stop.assert_not_called()
        assert client._reconnect_thread is not None

    def test_disconnect_callback_fires(self):
        """on_disconnect_callback should fire on unexpected disconnect."""
        client = make_mqtt_client()
        client._stopping = False
        mock_paho = mock.MagicMock()
        client._client = mock_paho
        callback_fired = []
        client.on_disconnect_callback = lambda: callback_fired.append(True)

        with mock.patch.object(client, '_reconnect_loop'):
            client._on_disconnect(mock_paho, None, None, 7, None)

        assert len(callback_fired) == 1

    @mock.patch('blueair_api.mqtt_aws_blueair.time.sleep')
    def test_reconnect_loop_refreshes_credentials(self, mock_sleep):
        """_reconnect_loop should call credential_refresher and reconnect."""
        client = make_mqtt_client()
        client._stopping = False

        loop = asyncio.new_event_loop()
        loop_thread = threading.Thread(target=loop.run_forever, daemon=True)
        loop_thread.start()
        client._event_loop = loop

        async def fake_refresh():
            return ("new-name", "new-sig", "new-token")

        client.credential_refresher = fake_refresh

        # Make _build_client return a mock, then stop the loop after one cycle
        mock_paho = mock.MagicMock()
        with mock.patch.object(client, '_build_client', return_value=mock_paho):
            client._reconnect_loop()

        loop.call_soon_threadsafe(loop.stop)
        loop_thread.join(timeout=5)
        loop.close()

        assert client._mqtt_auth_name == "new-name"
        assert client._mqtt_auth_signature == "new-sig"
        assert client._mqtt_auth_token == "new-token"
        mock_paho.connect.assert_called_once()
        mock_paho.loop_start.assert_called_once()

    @mock.patch('blueair_api.mqtt_aws_blueair.time.sleep')
    def test_reconnect_loop_retries_on_refresh_failure(self, mock_sleep):
        """If credential refresh fails, it should retry with backoff."""
        client = make_mqtt_client()
        client._stopping = False

        loop = asyncio.new_event_loop()
        loop_thread = threading.Thread(target=loop.run_forever, daemon=True)
        loop_thread.start()
        client._event_loop = loop

        call_count = 0

        async def failing_then_ok_refresh():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("network error")
            return ("new-name", "new-sig", "new-token")

        client.credential_refresher = failing_then_ok_refresh

        mock_paho = mock.MagicMock()
        with mock.patch.object(client, '_build_client', return_value=mock_paho):
            client._reconnect_loop()

        loop.call_soon_threadsafe(loop.stop)
        loop_thread.join(timeout=5)
        loop.close()

        assert call_count == 2
        # First call sleeps 5s, second call sleeps 10s (backoff)
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(5)
        mock_sleep.assert_any_call(10)

    @mock.patch('blueair_api.mqtt_aws_blueair.time.sleep')
    def test_reconnect_loop_stops_when_stopping(self, mock_sleep):
        """_reconnect_loop should exit when _stopping is set."""
        client = make_mqtt_client()

        # Set stopping before sleep returns
        def stop_on_sleep(delay):
            client._stopping = True

        mock_sleep.side_effect = stop_on_sleep

        client._reconnect_loop()
        # Should exit without error

    def test_register_device_while_connected_subscribes(self):
        """Registering a device while connected should subscribe immediately."""
        client = make_mqtt_client()
        mock_paho = mock.MagicMock()
        client._client = mock_paho
        client._connected = True

        client.register_device(FAKE_DEVICE_UUID)

        # Should have subscribed to 2 topics for this device
        assert mock_paho.subscribe.call_count == 2
        subscribed_topics = [call.args[0] for call in mock_paho.subscribe.call_args_list]
        assert f"d/{FAKE_DEVICE_UUID}/s/5s" in subscribed_topics
        assert f"$aws/things/{FAKE_DEVICE_UUID}/shadow/update/documents" in subscribed_topics


class TestOnConnect(TestCase):
    """Tests for the on_connect handler."""

    def test_on_connect_subscribes_to_all_topics(self):
        client = make_mqtt_client()
        client.register_device(FAKE_DEVICE_UUID)
        mock_paho = mock.MagicMock()
        client._client = mock_paho

        # Simulate successful connection (reason_code=0)
        client._on_connect(mock_paho, None, None, 0, None)

        assert client._connected is True
        # 1 user event topic + 2 device topics = 3 subscriptions
        assert mock_paho.subscribe.call_count == 3
        subscribed_topics = [call.args[0] for call in mock_paho.subscribe.call_args_list]
        assert f"c/{FAKE_USER_ID}/s/event" in subscribed_topics
        assert f"d/{FAKE_DEVICE_UUID}/s/5s" in subscribed_topics

    def test_on_connect_failure(self):
        client = make_mqtt_client()
        mock_paho = mock.MagicMock()

        client._on_connect(mock_paho, None, None, 5, None)  # reason_code != 0

        assert client._connected is False
        mock_paho.subscribe.assert_not_called()

    def test_on_connect_callback_fired(self):
        client = make_mqtt_client()
        called = []
        client.on_connect_callback = lambda: called.append(True)
        mock_paho = mock.MagicMock()
        client._client = mock_paho

        client._on_connect(mock_paho, None, None, 0, None)

        assert len(called) == 1


class TestOnDisconnect(TestCase):
    """Tests for the on_disconnect handler."""

    def test_on_disconnect(self):
        client = make_mqtt_client()
        client._connected = True
        called = []
        client.on_disconnect_callback = lambda: called.append(True)

        client._on_disconnect(None, None, None, 0, None)

        assert client._connected is False
        assert len(called) == 1


class TestMalformedMessages(TestCase):
    """Tests for handling invalid/malformed MQTT payloads."""

    def test_invalid_json(self):
        """Should not crash on invalid JSON."""
        client = make_mqtt_client()
        received = []
        client.on_sensor_data = lambda device_id, sensors: received.append(True)

        msg = mock.MagicMock()
        msg.topic = f"d/{FAKE_DEVICE_UUID}/s/5s"
        msg.payload = b"not valid json"
        client._on_message(None, None, msg)

        assert len(received) == 0

    def test_non_list_sensor_payload(self):
        """Sensor topic with dict payload instead of list."""
        client = make_mqtt_client()
        received = []
        client.on_sensor_data = lambda device_id, sensors: received.append((device_id, sensors))

        msg = make_mqtt_message(f"d/{FAKE_DEVICE_UUID}/s/5s", {"unexpected": "dict"})
        client._on_message(None, None, msg)

        assert len(received) == 1
        assert received[0][1] == {}

    def test_event_with_non_dict_payload(self):
        """Event topic with list payload instead of dict."""
        client = make_mqtt_client()
        received = []
        client.on_event = lambda device_id, event: received.append(True)

        msg = make_mqtt_message(f"c/{FAKE_USER_ID}/s/event", [1, 2, 3])
        client._on_message(None, None, msg)

        assert len(received) == 0


class TestInvalidRegion(TestCase):

    def test_connect_invalid_region(self):
        client = MqttAwsBlueair(
            region="invalid",
            mqtt_auth_name="n",
            mqtt_auth_signature="s",
            mqtt_auth_token="t",
            user_id="u",
        )
        with self.assertRaises(ValueError):
            client.connect()

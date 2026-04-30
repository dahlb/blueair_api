"""Tests for MqttAwsBlueair.

Unit tests that mock the paho-mqtt client to verify message parsing,
topic routing, callback dispatch, device registration, and reconnection
with credential refresh via paho's on_pre_connect hook.
"""
import asyncio
import json
import threading
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
    """Tests for disconnect handling and credential refresh via on_pre_connect."""

    def test_clean_disconnect_no_warning(self):
        """A clean disconnect (reason_code=0) should not log a warning."""
        client = make_mqtt_client()
        client._stopping = False
        mock_paho = mock.MagicMock()
        client._client = mock_paho

        client._on_disconnect(mock_paho, None, None, 0, None)

        assert client._connected is False

    def test_stopping_disconnect(self):
        """When _stopping is True, disconnect should be clean."""
        client = make_mqtt_client()
        client._stopping = True
        mock_paho = mock.MagicMock()
        client._client = mock_paho

        client._on_disconnect(mock_paho, None, None, 7, None)

        assert client._connected is False

    def test_unexpected_disconnect_sets_not_connected(self):
        """An unexpected disconnect should set connected to False."""
        client = make_mqtt_client()
        client._connected = True
        client._stopping = False
        mock_paho = mock.MagicMock()
        client._client = mock_paho

        client._on_disconnect(mock_paho, None, None, 7, None)

        assert client._connected is False

    def test_disconnect_callback_fires(self):
        """on_disconnect_callback should fire on unexpected disconnect."""
        client = make_mqtt_client()
        client._stopping = False
        mock_paho = mock.MagicMock()
        client._client = mock_paho
        callback_fired = []
        client.on_disconnect_callback = lambda: callback_fired.append(True)

        client._on_disconnect(mock_paho, None, None, 7, None)

        assert len(callback_fired) == 1

    def test_on_pre_connect_refreshes_credentials(self):
        """on_pre_connect should call credential_refresher and update tokens."""
        client = make_mqtt_client()

        loop = asyncio.new_event_loop()
        loop_thread = threading.Thread(target=loop.run_forever, daemon=True)
        loop_thread.start()
        client._event_loop = loop

        async def fake_refresh():
            return ("new-name", "new-sig", "new-token")

        client.credential_refresher = fake_refresh

        client._on_pre_connect(None, None)

        loop.call_soon_threadsafe(loop.stop)
        loop_thread.join(timeout=5)
        loop.close()

        assert client._mqtt_auth_name == "new-name"
        assert client._mqtt_auth_signature == "new-sig"
        assert client._mqtt_auth_token == "new-token"

    def test_on_pre_connect_handles_refresh_failure(self):
        """If credential refresh fails, on_pre_connect should not crash."""
        client = make_mqtt_client()

        loop = asyncio.new_event_loop()
        loop_thread = threading.Thread(target=loop.run_forever, daemon=True)
        loop_thread.start()
        client._event_loop = loop

        async def failing_refresh():
            raise RuntimeError("network error")

        client.credential_refresher = failing_refresh

        # Should not raise
        client._on_pre_connect(None, None)

        loop.call_soon_threadsafe(loop.stop)
        loop_thread.join(timeout=5)
        loop.close()

        # Credentials should remain unchanged
        assert client._mqtt_auth_name == "custom-authorizer"

    def test_on_pre_connect_skips_without_refresher(self):
        """on_pre_connect should be a no-op without a credential_refresher."""
        client = make_mqtt_client()
        client._event_loop = asyncio.new_event_loop()
        client.credential_refresher = None

        # Should not raise
        client._on_pre_connect(None, None)

        client._event_loop.close()

    def test_on_pre_connect_skips_without_event_loop(self):
        """on_pre_connect should be a no-op without an event loop."""
        client = make_mqtt_client()
        client._event_loop = None

        async def fake_refresh():
            return ("n", "s", "t")

        client.credential_refresher = fake_refresh

        # Should not raise
        client._on_pre_connect(None, None)

    def test_get_ws_headers_returns_current_creds(self):
        """_get_ws_headers should return the current auth credentials."""
        client = make_mqtt_client()

        headers = client._get_ws_headers({"Host": "example.com"})

        assert headers["X-Amz-CustomAuthorizer-Name"] == "custom-authorizer"
        assert headers["X-Amz-CustomAuthorizer-Signature"] == "fake-signature"
        assert headers["X-Amz-CustomAuthorizer-Token"] == "fake-token"
        assert headers["Host"] == "example.com"

    def test_get_ws_headers_reflects_refreshed_creds(self):
        """After credential refresh, _get_ws_headers should return new tokens."""
        client = make_mqtt_client()
        client._mqtt_auth_name = "updated-name"
        client._mqtt_auth_signature = "updated-sig"
        client._mqtt_auth_token = "updated-token"

        headers = client._get_ws_headers({})

        assert headers["X-Amz-CustomAuthorizer-Name"] == "updated-name"
        assert headers["X-Amz-CustomAuthorizer-Signature"] == "updated-sig"
        assert headers["X-Amz-CustomAuthorizer-Token"] == "updated-token"

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


class TestBuildClient(TestCase):
    """Tests that _build_client wires up paho hooks correctly."""

    def test_build_client_sets_on_pre_connect(self):
        """_build_client must assign on_pre_connect for credential refresh."""
        client = make_mqtt_client()
        paho_client = client._build_client()
        assert paho_client.on_pre_connect is not None
        assert paho_client.on_pre_connect == client._on_pre_connect

    def test_build_client_sets_on_connect_fail(self):
        """_build_client must assign on_connect_fail for logging handshake errors."""
        client = make_mqtt_client()
        paho_client = client._build_client()
        assert paho_client.on_connect_fail is not None
        assert paho_client.on_connect_fail == client._on_connect_fail

    def test_build_client_sets_callable_headers(self):
        """_build_client must pass a callable (not a dict) to ws_set_options."""
        client = make_mqtt_client()
        paho_client = client._build_client()
        # paho stores the callable in _websocket_extra_headers
        assert callable(paho_client._websocket_extra_headers)

    def test_build_client_enables_reconnect(self):
        """_build_client must leave reconnect_on_failure enabled (default True)."""
        client = make_mqtt_client()
        paho_client = client._build_client()
        assert paho_client._reconnect_on_failure is True

    def test_build_client_sets_reconnect_delay(self):
        """_build_client must configure backoff via reconnect_delay_set."""
        client = make_mqtt_client()
        paho_client = client._build_client()
        assert paho_client._reconnect_min_delay == 5
        assert paho_client._reconnect_max_delay == 300


class TestEndToEndCredentialRefresh(TestCase):
    """Test the full reconnect credential flow: on_pre_connect → _get_ws_headers."""

    def test_pre_connect_then_headers_returns_fresh_creds(self):
        """Simulates paho's reconnect: on_pre_connect refreshes, then
        _get_ws_headers returns the new values for the WS handshake."""
        client = make_mqtt_client()

        loop = asyncio.new_event_loop()
        loop_thread = threading.Thread(target=loop.run_forever, daemon=True)
        loop_thread.start()
        client._event_loop = loop

        async def fake_refresh():
            return ("refreshed-name", "refreshed-sig", "refreshed-token")

        client.credential_refresher = fake_refresh

        # Step 1: paho calls on_pre_connect
        client._on_pre_connect(None, None)

        # Step 2: paho calls _get_ws_headers during WS handshake
        headers = client._get_ws_headers({"Host": "broker.example.com"})

        loop.call_soon_threadsafe(loop.stop)
        loop_thread.join(timeout=5)
        loop.close()

        assert headers["X-Amz-CustomAuthorizer-Name"] == "refreshed-name"
        assert headers["X-Amz-CustomAuthorizer-Signature"] == "refreshed-sig"
        assert headers["X-Amz-CustomAuthorizer-Token"] == "refreshed-token"
        # Default headers preserved
        assert headers["Host"] == "broker.example.com"

    def test_pre_connect_failure_headers_use_old_creds(self):
        """If credential refresh fails, headers should still use the
        previous (possibly stale) credentials rather than crashing."""
        client = make_mqtt_client()

        loop = asyncio.new_event_loop()
        loop_thread = threading.Thread(target=loop.run_forever, daemon=True)
        loop_thread.start()
        client._event_loop = loop

        async def failing_refresh():
            raise RuntimeError("auth server down")

        client.credential_refresher = failing_refresh

        # on_pre_connect fails silently
        client._on_pre_connect(None, None)

        # Headers should still work with original creds
        headers = client._get_ws_headers({})

        loop.call_soon_threadsafe(loop.stop)
        loop_thread.join(timeout=5)
        loop.close()

        assert headers["X-Amz-CustomAuthorizer-Name"] == "custom-authorizer"
        assert headers["X-Amz-CustomAuthorizer-Signature"] == "fake-signature"
        assert headers["X-Amz-CustomAuthorizer-Token"] == "fake-token"


class TestConnectDisconnect(TestCase):
    """Tests for connect() and disconnect() methods."""

    @mock.patch('blueair_api.mqtt_aws_blueair.mqtt.Client')
    def test_connect_stores_event_loop(self, MockClient):
        """connect() should store the event_loop for on_pre_connect."""
        client = make_mqtt_client()
        fake_loop = mock.MagicMock()
        client.connect(event_loop=fake_loop)
        assert client._event_loop is fake_loop

    @mock.patch('blueair_api.mqtt_aws_blueair.mqtt.Client')
    def test_connect_calls_paho_connect_and_loop_start(self, MockClient):
        """connect() should call paho's connect() and loop_start()."""
        mock_paho = MockClient.return_value
        client = make_mqtt_client()
        client.connect()
        mock_paho.connect.assert_called_once()
        mock_paho.loop_start.assert_called_once()

    @mock.patch('blueair_api.mqtt_aws_blueair.mqtt.Client')
    def test_disconnect_calls_paho_loop_stop_and_disconnect(self, MockClient):
        """disconnect() should call loop_stop() and disconnect() on paho."""
        mock_paho = MockClient.return_value
        client = make_mqtt_client()
        client.connect()
        client.disconnect()
        mock_paho.loop_stop.assert_called_once()
        mock_paho.disconnect.assert_called_once()
        assert client._stopping is True
        assert client._client is None


class TestOnConnectFail(TestCase):
    """Tests for the on_connect_fail handler."""

    def test_on_connect_fail_does_not_crash(self):
        """on_connect_fail should log but not raise."""
        client = make_mqtt_client()
        # Should not raise
        client._on_connect_fail(None, None)


class TestSensorTTLResubscribe(TestCase):
    """Tests for the sensor TTL keepalive re-subscribe mechanism."""

    def test_set_sensor_ttl(self):
        """set_sensor_ttl should update the TTL value."""
        client = make_mqtt_client()
        client.set_sensor_ttl(600)
        assert client._sensor_ttl == 600

    def test_set_sensor_ttl_ignores_non_positive(self):
        """set_sensor_ttl should ignore values <= 0."""
        client = make_mqtt_client()
        original = client._sensor_ttl
        client.set_sensor_ttl(-1)
        assert client._sensor_ttl == original
        client.set_sensor_ttl(0)
        assert client._sensor_ttl == original

    def test_default_sensor_ttl(self):
        """Default sensor TTL should be 1200 seconds."""
        client = make_mqtt_client()
        assert client._sensor_ttl == 1200

    def test_resubscribe_sensor_topics(self):
        """_resubscribe_sensor_topics should subscribe (without unsubscribe) for each device."""
        client = make_mqtt_client()
        client.register_device(FAKE_DEVICE_UUID)
        mock_paho = mock.MagicMock()
        client._client = mock_paho
        client._connected = True

        client._resubscribe_sensor_topics()

        mock_paho.unsubscribe.assert_not_called()
        mock_paho.subscribe.assert_called_once_with(f"d/{FAKE_DEVICE_UUID}/s/5s")

    def test_resubscribe_sensor_topics_multiple_devices(self):
        """_resubscribe_sensor_topics should handle multiple devices."""
        client = make_mqtt_client()
        uuid2 = "22222222-2222-2222-2222-222222222222"
        client.register_device(FAKE_DEVICE_UUID)
        client.register_device(uuid2)
        mock_paho = mock.MagicMock()
        client._client = mock_paho
        client._connected = True

        client._resubscribe_sensor_topics()

        mock_paho.unsubscribe.assert_not_called()
        assert mock_paho.subscribe.call_count == 2

    def test_resubscribe_sensor_topics_not_connected(self):
        """_resubscribe_sensor_topics should be a no-op when not connected."""
        client = make_mqtt_client()
        client.register_device(FAKE_DEVICE_UUID)
        mock_paho = mock.MagicMock()
        client._client = mock_paho
        client._connected = False

        client._resubscribe_sensor_topics()

        mock_paho.unsubscribe.assert_not_called()
        mock_paho.subscribe.assert_not_called()

    def test_on_connect_starts_resubscribe_timer(self):
        """_on_connect should start the re-subscribe timer."""
        client = make_mqtt_client()
        client.register_device(FAKE_DEVICE_UUID)
        mock_paho = mock.MagicMock()
        client._client = mock_paho

        client._on_connect(mock_paho, None, None, 0, None)

        assert client._resubscribe_timer is not None
        # Clean up
        client._cancel_resubscribe_timer()

    def test_disconnect_cancels_resubscribe_timer(self):
        """disconnect() should cancel the re-subscribe timer."""
        client = make_mqtt_client()
        # Simulate a running timer
        client._resubscribe_timer = mock.MagicMock()
        client._client = mock.MagicMock()

        client.disconnect()

        assert client._resubscribe_timer is None

    def test_unexpected_disconnect_cancels_timer(self):
        """_on_disconnect should cancel the re-subscribe timer."""
        client = make_mqtt_client()
        client._resubscribe_timer = mock.MagicMock()

        client._on_disconnect(None, None, None, 7, None)

        assert client._resubscribe_timer is None

    def test_resubscribe_timer_interval(self):
        """Timer interval should be TTL * 0.75."""
        client = make_mqtt_client()
        client.set_sensor_ttl(1200)
        client.register_device(FAKE_DEVICE_UUID)
        mock_paho = mock.MagicMock()
        client._client = mock_paho
        client._connected = True

        with mock.patch('blueair_api.mqtt_aws_blueair.threading.Timer') as MockTimer:
            mock_timer_instance = mock.MagicMock()
            MockTimer.return_value = mock_timer_instance
            client._start_resubscribe_timer()
            MockTimer.assert_called_once_with(900, client._resubscribe_timer_fired)
            mock_timer_instance.start.assert_called_once()

        client._cancel_resubscribe_timer()

    def test_resubscribe_timer_custom_ttl(self):
        """Timer interval should use custom TTL when set."""
        client = make_mqtt_client()
        client.set_sensor_ttl(600)  # 10 minutes

        with mock.patch('blueair_api.mqtt_aws_blueair.threading.Timer') as MockTimer:
            mock_timer_instance = mock.MagicMock()
            MockTimer.return_value = mock_timer_instance
            client._start_resubscribe_timer()
            MockTimer.assert_called_once_with(450, client._resubscribe_timer_fired)

        client._cancel_resubscribe_timer()


class TestConnectedEventResubscribe(TestCase):
    """Tests for re-subscribing on device Connected events."""

    def test_connected_event_resubscribes(self):
        """A Connected event should trigger re-subscribe for that device."""
        client = make_mqtt_client()
        client.register_device(FAKE_DEVICE_UUID)
        mock_paho = mock.MagicMock()
        client._client = mock_paho
        client._connected = True

        payload = {
            "et": "Connected",
            "o": FAKE_DEVICE_UUID,
            "ts": 1776455065,
            "m": "Device is Online",
            "ot": "ConnectionEvent",
        }
        msg = make_mqtt_message(f"c/{FAKE_USER_ID}/s/event", payload)
        client._on_message(None, None, msg)

        # Should have re-subscribed to the 5s topic (no unsubscribe)
        mock_paho.unsubscribe.assert_not_called()
        mock_paho.subscribe.assert_called_once_with(f"d/{FAKE_DEVICE_UUID}/s/5s")

    def test_not_connected_event_does_not_resubscribe(self):
        """A NotConnected event should NOT trigger re-subscribe."""
        client = make_mqtt_client()
        client.register_device(FAKE_DEVICE_UUID)
        mock_paho = mock.MagicMock()
        client._client = mock_paho
        client._connected = True

        payload = {
            "et": "NotConnected",
            "o": FAKE_DEVICE_UUID,
            "ts": 1776455065,
            "m": "Device is Offline",
        }
        msg = make_mqtt_message(f"c/{FAKE_USER_ID}/s/event", payload)
        client._on_message(None, None, msg)

        mock_paho.unsubscribe.assert_not_called()
        mock_paho.subscribe.assert_not_called()

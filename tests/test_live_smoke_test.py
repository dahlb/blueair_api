"""Tests for the live smoke-test command-line helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar, cast

import pytest

from blueair_api.device_aws import DeviceAws
from blueair_api.errors import LoginError
from blueair_api.http_aws_blueair import HttpAwsBlueair
from blueair_api.live_smoke_test import (
    CredentialSource,
    MqttUpdatePrinter,
    SmokeTestOptions,
    SmokeTestTranscript,
    TeeTextIO,
    device_state,
    load_credentials,
    main,
    maybe_send_sample_control_update,
    parse_args,
    run_legacy_check,
    send_sample_control_update,
    start_mqtt_listener,
)

MODULE = "blueair_api.live_smoke_test"


def test_load_credentials_reads_dotenv_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Credentials are read from a dotenv-style file before prompting."""
    credentials_file = tmp_path / ".blueair.env"
    credentials_file.write_text(
        "BLUEAIR_USERNAME=dotenv@example.com\nBLUEAIR_PASSWORD='dotenv password'\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("BLUEAIR_USERNAME", raising=False)
    monkeypatch.delenv("BLUEAIR_PASSWORD", raising=False)

    credentials = load_credentials(SmokeTestOptions(credentials_file=credentials_file))

    assert credentials == CredentialSource(
        username="dotenv@example.com",
        password="dotenv password",
        description=str(credentials_file),
    )


def test_load_credentials_prefers_file_over_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit credential files take precedence over process environment."""
    credentials_file = tmp_path / "blueair.toml"
    credentials_file.write_text(
        'username = "file@example.com"\npassword = "file-password"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("BLUEAIR_USERNAME", "env@example.com")
    monkeypatch.setenv("BLUEAIR_PASSWORD", "env-password")

    credentials = load_credentials(SmokeTestOptions(credentials_file=credentials_file))

    assert credentials == CredentialSource(
        username="file@example.com",
        password="file-password",
        description=str(credentials_file),
    )


def test_load_credentials_reads_blueair_toml_section(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TOML credentials can be grouped under a blueair section."""
    credentials_file = tmp_path / "blueair.toml"
    credentials_file.write_text(
        '[blueair]\nusername = "section@example.com"\npassword = "section-password"\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("BLUEAIR_USERNAME", raising=False)
    monkeypatch.delenv("BLUEAIR_PASSWORD", raising=False)

    credentials = load_credentials(SmokeTestOptions(credentials_file=credentials_file))

    assert credentials == CredentialSource(
        username="section@example.com",
        password="section-password",
        description=str(credentials_file),
    )


def test_load_credentials_reads_json_file(tmp_path: Path) -> None:
    """JSON credentials files are supported."""
    credentials_file = tmp_path / "blueair.json"
    credentials_file.write_text(
        '{"email": "json@example.com", "password": "json-password"}',
        encoding="utf-8",
    )

    credentials = load_credentials(SmokeTestOptions(credentials_file=credentials_file))

    assert credentials == CredentialSource(
        username="json@example.com",
        password="json-password",
        description=str(credentials_file),
    )


def test_load_credentials_rejects_partial_credentials_file(tmp_path: Path) -> None:
    """Explicit credential files fail fast when a value is missing."""
    credentials_file = tmp_path / ".blueair.env"
    credentials_file.write_text("BLUEAIR_USERNAME=partial@example.com\n", encoding="utf-8")

    with pytest.raises(ValueError, match="must include both"):
        load_credentials(SmokeTestOptions(credentials_file=credentials_file))


def test_load_credentials_rejects_json_null_values(tmp_path: Path) -> None:
    """JSON null credentials do not become literal None strings."""
    credentials_file = tmp_path / "blueair.json"
    credentials_file.write_text('{"username": null, "password": null}', encoding="utf-8")

    with pytest.raises(ValueError, match="must include both"):
        load_credentials(SmokeTestOptions(credentials_file=credentials_file))


def test_load_credentials_rejects_json_non_object(tmp_path: Path) -> None:
    """JSON credentials files must contain an object."""
    credentials_file = tmp_path / "blueair.json"
    credentials_file.write_text('["user", "password"]', encoding="utf-8")

    with pytest.raises(ValueError, match="must contain an object"):
        load_credentials(SmokeTestOptions(credentials_file=credentials_file))


@pytest.mark.parametrize(
    ("filename", "contents"),
    [
        ("blueair.json", '{"username": 123, "password": "password"}'),
        ("blueair.toml", 'username = "user@example.com"\npassword = false\n'),
    ],
)
def test_load_credentials_rejects_typed_config_values(
    tmp_path: Path,
    filename: str,
    contents: str,
) -> None:
    """JSON and TOML credentials must use strings for credential values."""
    credentials_file = tmp_path / filename
    credentials_file.write_text(contents, encoding="utf-8")

    with pytest.raises(TypeError, match="must be strings"):
        load_credentials(SmokeTestOptions(credentials_file=credentials_file))


def test_load_credentials_uses_environment_when_file_is_not_provided(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Environment credentials are used when no file path is provided."""
    monkeypatch.setenv("BLUEAIR_USERNAME", "env@example.com")
    monkeypatch.setenv("BLUEAIR_PASSWORD", "env-password")

    credentials = load_credentials(SmokeTestOptions())

    assert credentials == CredentialSource(
        username="env@example.com",
        password="env-password",
        description="environment variables",
    )


def test_load_credentials_returns_none_for_partial_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Partial environment credentials do not suppress the interactive prompt."""
    monkeypatch.setenv("BLUEAIR_USERNAME", "env@example.com")
    monkeypatch.delenv("BLUEAIR_PASSWORD", raising=False)

    assert load_credentials(SmokeTestOptions()) is None


def test_tee_text_io_writes_to_stream_and_output_file(tmp_path: Path) -> None:
    """Tee text output preserves console behavior while writing a transcript."""
    output_file = tmp_path / "smoke-output.txt"
    console_file = tmp_path / "console-output.txt"

    with (
        console_file.open("w", encoding="utf-8") as console,
        output_file.open("w", encoding="utf-8") as transcript,
    ):
        tee = TeeTextIO(console, transcript)
        written = tee.write("captured output\n")
        tee.flush()

    assert written == len("captured output\n")
    assert console_file.read_text(encoding="utf-8") == "captured output\n"
    assert output_file.read_text(encoding="utf-8") == "captured output\n"


def test_parse_args_defaults() -> None:
    """Default options use the us region and run every smoke-test step."""
    assert parse_args([]) == SmokeTestOptions()


def test_parse_args_accepts_all_options() -> None:
    """Every command-line option maps onto the smoke-test options."""
    options = parse_args(
        [
            "--credentials-file",
            "/tmp/live_smoke_test.env",
            "--output-file",
            "/tmp/smoke.txt",
            "--read-only",
            "--region",
            "eu",
            "--gigya-region",
            "us",
            "--cloud-region",
            "eu",
            "--skip-legacy",
        ],
    )

    assert options == SmokeTestOptions(
        credentials_file=Path("/tmp/live_smoke_test.env"),
        output_file=Path("/tmp/smoke.txt"),
        read_only=True,
        region="eu",
        gigya_region="us",
        cloud_region="eu",
        skip_legacy=True,
    )


def test_parse_args_rejects_unknown_region() -> None:
    """Regions are limited to the ones the library knows about."""
    with pytest.raises(SystemExit):
        parse_args(["--region", "mars"])


def test_parse_args_resolves_relative_paths_from_launcher_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Relative paths survive the launcher changing to the project root."""
    monkeypatch.setenv("BLUEAIR_API_LIVE_SMOKE_CWD", str(tmp_path))

    options = parse_args(
        [
            "--credentials-file",
            "./live_smoke_test.env",
            "--output-file",
            "smoke.txt",
        ],
    )

    assert options.credentials_file == tmp_path / "live_smoke_test.env"
    assert options.output_file == tmp_path / "smoke.txt"


def fake_aws_device(**kwargs: Any) -> Any:
    """Build a minimal AWS device double.

    Args:
        kwargs: Attribute overrides.

    Returns:
        Device double with the attributes the smoke test reads.
    """
    calls: list[Any] = []

    async def set_brightness(value: int) -> None:
        calls.append(("set_brightness", value))

    async def refresh() -> None:
        calls.append("refresh")

    defaults: dict[str, Any] = {
        "uuid": "device-1",
        "name": "Bedroom",
        "brightness": 42,
        "calls": calls,
        "set_brightness": set_brightness,
        "refresh": refresh,
        "apply_sensor_data": lambda sensors: calls.append(("sensors", sensors)),
        "apply_state_change": lambda state: calls.append(("state", state)),
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


async def test_send_sample_control_update_writes_current_brightness() -> None:
    """The sample update writes the device's current brightness back unchanged."""
    device = fake_aws_device(brightness=42)

    sent = await send_sample_control_update([device])

    assert sent is True
    assert device.calls == [("set_brightness", 42)]


@pytest.mark.parametrize("brightness", [None, True])
async def test_send_sample_control_update_skips_without_brightness(
    brightness: Any,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Devices that do not report an integer brightness are not written to."""
    device = fake_aws_device(brightness=brightness)

    sent = await send_sample_control_update([device])

    assert sent is False
    assert device.calls == []
    assert "does not report brightness" in capsys.readouterr().out


async def test_send_sample_control_update_skips_without_devices(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Accounts with no AWS devices skip the sample update."""
    assert await send_sample_control_update([]) is False
    assert "No AWS devices available" in capsys.readouterr().out


async def test_maybe_send_sample_control_update_skips_read_only(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Read-only mode skips the sample control update."""
    device = fake_aws_device()

    sent = await maybe_send_sample_control_update([device], read_only=True)

    assert sent is False
    assert device.calls == []
    assert "Read-only mode enabled" in capsys.readouterr().out


def test_mqtt_update_printer_applies_updates_to_matching_device(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """MQTT callbacks are applied to the matching device and printed."""
    printed: list[Any] = []
    monkeypatch.setattr(f"{MODULE}.print_devices", lambda label, devices: printed.extend(devices))
    device = fake_aws_device()
    printer = MqttUpdatePrinter([cast("DeviceAws", device)])

    printer.handle_sensor_data("device-1", {"pm2_5": 3.0})
    printer.handle_state_change("device-1", {"brightness": 10})
    printer.handle_sensor_data("unknown", {"pm2_5": 1.0})
    printer.handle_event("device-1", {"et": "Connected"})

    assert device.calls == [("sensors", {"pm2_5": 3.0}), ("state", {"brightness": 10})]
    assert printed == [device, device]
    output = capsys.readouterr().out
    assert "MQTT sensor data for unknown" in output
    assert "MQTT event for device-1" in output


def test_mqtt_update_printer_attaches_its_handlers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The MQTT client's callbacks apply updates directly (they run on the loop)."""
    monkeypatch.setattr(f"{MODULE}.print_devices", lambda label, devices: None)
    device = fake_aws_device()
    client = SimpleNamespace(on_sensor_data=None, on_state_change=None, on_event=None)
    MqttUpdatePrinter([cast("DeviceAws", device)]).attach(cast("Any", client))

    client.on_sensor_data("device-1", {"pm1": 2.0})
    client.on_state_change("device-1", {"childlock": True})

    assert device.calls == [("sensors", {"pm1": 2.0}), ("state", {"childlock": True})]


async def test_start_mqtt_listener_skips_without_credentials(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Missing MQTT credentials skip the listener instead of failing."""
    api = SimpleNamespace(
        mqtt_auth_name=None,
        mqtt_auth_signature=None,
        mqtt_auth_token=None,
        user_id=None,
    )

    client = await start_mqtt_listener(cast("HttpAwsBlueair", api), [fake_aws_device()])

    assert client is None
    assert "MQTT credentials were not returned" in capsys.readouterr().out


async def test_start_mqtt_listener_registers_devices_and_connects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The listener subscribes to every device and refreshes credentials on demand."""
    created: list[Any] = []

    class FakeMqtt:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs
            self.devices: list[str] = []
            self.connected = False
            self.credential_refresher: Any = None
            self.on_sensor_data: Any = None
            self.on_state_change: Any = None
            self.on_event: Any = None
            created.append(self)

        def register_device(self, device_uuid: str) -> None:
            self.devices.append(device_uuid)

        async def connect(self) -> None:
            self.connected = True

    async def refresh_access_token() -> None:
        api.mqtt_auth_token = "new-token"

    api = SimpleNamespace(
        cloud_region="eu",
        mqtt_auth_name="name",
        mqtt_auth_signature="signature",
        mqtt_auth_token="token",
        user_id="user",
        refresh_access_token=refresh_access_token,
    )
    monkeypatch.setattr(f"{MODULE}.MqttAwsBlueair", FakeMqtt)

    client = await start_mqtt_listener(
        cast("HttpAwsBlueair", api),
        [fake_aws_device(uuid="a"), fake_aws_device(uuid="b")],
    )

    fake: Any = created[0]
    assert fake.kwargs["region"] == "eu"
    assert fake.devices == ["a", "b"]
    assert fake.connected is True
    assert fake.on_sensor_data is not None
    assert await fake.credential_refresher() == ("name", "signature", "new-token")
    # Checked last: mypy narrows both sides of ``is``, which would hide the fake's attributes.
    assert client is fake


async def test_run_legacy_check_reports_login_errors(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AWS-only accounts that fail legacy login do not end the smoke test."""

    async def failing_get_devices(**kwargs: Any) -> Any:
        raise LoginError("no legacy account")

    monkeypatch.setattr(f"{MODULE}.get_devices", failing_get_devices)

    devices = await run_legacy_check("user", "password", cast("Any", object()))

    assert devices == []
    assert "Legacy API check failed" in capsys.readouterr().out


class FakeClientSession:
    """aiohttp session double that records closing."""

    instances: ClassVar[list[FakeClientSession]] = []

    def __init__(self, **kwargs: Any) -> None:
        self.closed = False
        FakeClientSession.instances.append(self)

    async def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize("skip_legacy", [False, True])
async def test_main_runs_steps_in_order_and_cleans_up(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    skip_legacy: bool,
) -> None:
    """Main loads AWS devices, starts MQTT, then waits and closes every resource."""
    calls: list[str] = []
    device = fake_aws_device()
    FakeClientSession.instances = []

    class FakeMqtt:
        async def disconnect(self) -> None:
            calls.append("mqtt_disconnect")

    async def fake_get_aws_devices(**kwargs: Any) -> Any:
        calls.append(f"aws:{kwargs['region']}")
        return SimpleNamespace(), [device]

    async def fake_start_mqtt_listener(api: Any, devices: Any) -> Any:
        calls.append("mqtt_connect")
        return FakeMqtt()

    async def fake_get_devices(**kwargs: Any) -> Any:
        calls.append("legacy")
        return SimpleNamespace(), []

    async def fake_sleep(seconds: float) -> None:
        calls.append("sleep")

    monkeypatch.setattr(f"{MODULE}.ClientSession", FakeClientSession)
    monkeypatch.setattr(f"{MODULE}.get_aws_devices", fake_get_aws_devices)
    monkeypatch.setattr(f"{MODULE}.start_mqtt_listener", fake_start_mqtt_listener)
    monkeypatch.setattr(f"{MODULE}.get_devices", fake_get_devices)
    monkeypatch.setattr(f"{MODULE}.sleep", fake_sleep)
    monkeypatch.setattr(f"{MODULE}.print_devices", lambda label, devices: None)

    credentials_file = tmp_path / "blueair.env"
    credentials_file.write_text(
        "BLUEAIR_USERNAME=test@example.com\nBLUEAIR_PASSWORD=password\n",
        encoding="utf-8",
    )

    await main(
        SmokeTestOptions(
            credentials_file=credentials_file,
            read_only=True,
            region="eu",
            skip_legacy=skip_legacy,
        ),
    )

    expected = ["aws:eu", "mqtt_connect"]
    if not skip_legacy:
        expected.append("legacy")
    expected += ["sleep", "mqtt_disconnect"]
    assert calls == expected
    assert "refresh" in device.calls
    assert len(FakeClientSession.instances) == (1 if skip_legacy else 2)
    assert all(session.closed for session in FakeClientSession.instances)


async def test_main_closes_session_when_aws_login_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The owned HTTP session is closed even when AWS login raises."""
    FakeClientSession.instances = []

    async def failing_get_aws_devices(**kwargs: Any) -> Any:
        raise LoginError("bad password")

    monkeypatch.setattr(f"{MODULE}.ClientSession", FakeClientSession)
    monkeypatch.setattr(f"{MODULE}.get_aws_devices", failing_get_aws_devices)

    credentials_file = tmp_path / "blueair.env"
    credentials_file.write_text(
        "BLUEAIR_USERNAME=test@example.com\nBLUEAIR_PASSWORD=password\n",
        encoding="utf-8",
    )

    with pytest.raises(LoginError, match="bad password"):
        await main(SmokeTestOptions(credentials_file=credentials_file))

    assert len(FakeClientSession.instances) == 1
    assert FakeClientSession.instances[0].closed


def test_smoke_test_transcript_captures_traceback(tmp_path: Path) -> None:
    """Transcript files include raised exceptions for later debugging."""
    output_file = tmp_path / "smoke-output.txt"

    with pytest.raises(RuntimeError, match="live failure"), SmokeTestTranscript(output_file):
        raise RuntimeError("live failure")

    output = output_file.read_text(encoding="utf-8")
    assert "RuntimeError: live failure" in output


def test_device_state_excludes_api_and_raw_fields() -> None:
    """Printed device state omits the API client and raw payload fields."""
    device = DeviceAws(
        api=cast("HttpAwsBlueair", None),
        uuid="device-1",
        name_api="device",
        mac="mac",
        type_name="type",
        brightness=42,
    )

    state = device_state(device)

    assert state["uuid"] == "device-1"
    assert state["brightness"] == 42
    assert "api" not in state
    assert "raw_info" not in state

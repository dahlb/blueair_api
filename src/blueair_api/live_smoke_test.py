"""Manual live Blueair API smoke-test script for local development.

This module is an interactive development harness, not part of the automated
pytest suite. It connects to the real Blueair APIs with credentials entered at
the terminal (or loaded from a credentials file or environment variables),
loads the account's AWS devices, refreshes and prints their current state,
subscribes to MQTT real-time updates, sends one sample control update to the
first AWS device, and then checks the legacy Blueair API.

Use this when developing or debugging behavior that needs a live Blueair
account, such as captured device-info payloads, MQTT sensor/shadow
reconciliation, control writes, or region discovery issues that are hard to
represent from stored fixtures alone. Do not use it as a substitute for adding
deterministic tests in ``tests/``; any fixed behavior should still be covered by
pytest fixtures or unit tests where practical.

The script intentionally prints raw inspected state to the console and mutates
``sys.path`` so it can be run directly from a source checkout without installing
the package first. Unless ``--read-only`` is given it writes the first AWS
device's current LED brightness back to it, which exercises the control path and
triggers an MQTT shadow update without changing the device's settings.

Run it through the repository helper script so it starts from the project root
and uses the repository virtual environment:
``scripts/live_smoke_test``.
"""

from argparse import ArgumentParser, Namespace
import asyncio
from asyncio import AbstractEventLoop, sleep
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, fields
from datetime import datetime
from getpass import getpass
import json
import logging
import os
from pathlib import Path
import sys
import tomllib
import traceback as traceback_module
from types import TracebackType
from typing import Any, TextIO

from aiohttp import ClientSession

path_src = Path(__file__).parents[1]
sys.path.append(str(path_src))

from blueair_api.const import AWS_APIKEYS
from blueair_api.device import Device
from blueair_api.device_aws import DeviceAws
from blueair_api.errors import BaseError
from blueair_api.http_aws_blueair import HttpAwsBlueair
from blueair_api.mqtt_aws_blueair import MqttAwsBlueair
from blueair_api.util_bootstrap import get_aws_devices, get_devices

logger = logging.getLogger("blueair_api")
logger.setLevel(logging.DEBUG)
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
ch.setFormatter(formatter)
logger.addHandler(ch)

SMOKE_TEST_WAIT_SECONDS = 300
USERNAME_KEYS = ("BLUEAIR_USERNAME", "BLUEAIR_EMAIL", "username", "email", "name")
PASSWORD_KEYS = ("BLUEAIR_PASSWORD", "password")
REGION_CHOICES = tuple(sorted(AWS_APIKEYS))

INTRO_TEXT = """\
This smoke test connects to the live Blueair APIs.
It loads your AWS devices, prints their current state, starts MQTT real-time
updates, sends one sample control update to the first AWS device, checks the
legacy Blueair API, and then waits so incoming realtime messages can be observed.

Unless ``--read-only`` is provided, this script writes the first AWS device's
current LED brightness back to it. The value is unchanged, but the write goes
through the live control API and should produce an MQTT shadow update. After
that, it waits 5 minutes, so the terminal will appear to pause while it listens
for MQTT messages.

Enter the Blueair account email address and password that you use for the
official Blueair app. These credentials are read from this terminal session
only; the script does not store them.
"""


@dataclass(frozen=True)
class CredentialSource:
    """Blueair credentials loaded from a non-interactive source.

    Args:
        username: Blueair account email address.
        password: Blueair account password.
        description: Human-readable source description for console output.
    """

    username: str
    password: str
    description: str


@dataclass(frozen=True)
class SmokeTestOptions:
    """Parsed smoke-test command-line options.

    Args:
        credentials_file: Optional file to read Blueair credentials from.
        output_file: Optional file to write a full smoke-test transcript to.
        read_only: Whether to skip the sample device control update.
        region: Blueair AWS region used for both account auth and device control.
        gigya_region: Optional override for the Gigya account-auth region.
        cloud_region: Optional override for the BlueCloud REST and MQTT region.
        skip_legacy: Whether to skip the legacy (non-AWS) Blueair API check.
    """

    credentials_file: Path | None = None
    output_file: Path | None = None
    read_only: bool = False
    region: str = "us"
    gigya_region: str | None = None
    cloud_region: str | None = None
    skip_legacy: bool = False


class TeeTextIO:
    """Text stream that writes to a console stream and a transcript file."""

    def __init__(self, console: TextIO, transcript: TextIO) -> None:
        """Initialize the tee stream.

        Args:
            console: Original console stream.
            transcript: Output transcript stream.
        """
        self._console = console
        self._transcript = transcript
        self.encoding = getattr(console, "encoding", None)

    def write(self, text: str) -> int:
        """Write text to both wrapped streams.

        Args:
            text: Text to write.

        Returns:
            The number of characters accepted by the console stream.
        """
        written = self._console.write(text)
        self._transcript.write(text)
        return written

    def flush(self) -> None:
        """Flush both wrapped streams."""
        self._console.flush()
        self._transcript.flush()

    def isatty(self) -> bool:
        """Return whether the console stream is attached to a terminal.

        Returns:
            True when the original console stream is a TTY.
        """
        return self._console.isatty()


class SmokeTestTranscript:
    """Context manager that tees console and log output to a file."""

    def __init__(self, output_file: Path) -> None:
        """Initialize transcript capture.

        Args:
            output_file: File that should receive the captured transcript.
        """
        self._output_file = output_file
        self._transcript: TextIO | None = None
        self._stdout: TextIO | None = None
        self._stderr: TextIO | None = None
        self._original_handler_streams: list[tuple[logging.StreamHandler[TextIO], TextIO]] = []

    def __enter__(self) -> None:
        """Start teeing stdout, stderr, and logger streams."""
        self._output_file.parent.mkdir(parents=True, exist_ok=True)
        self._transcript = self._output_file.open("w", encoding="utf-8")
        self._stdout = sys.stdout
        self._stderr = sys.stderr
        sys.stdout = TeeTextIO(sys.stdout, self._transcript)
        sys.stderr = TeeTextIO(sys.stderr, self._transcript)
        for handler in logger.handlers:
            if isinstance(handler, logging.StreamHandler):
                self._original_handler_streams.append((handler, handler.stream))
                handler.setStream(sys.stderr)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Stop teeing output and close the transcript file.

        Args:
            exc_type: Exception type raised inside the context, if any.
            exc_value: Exception raised inside the context, if any.
            traceback: Traceback raised inside the context, if any.
        """
        for handler, stream in self._original_handler_streams:
            handler.setStream(stream)
        if self._stdout is not None:
            sys.stdout = self._stdout
        if self._stderr is not None:
            sys.stderr = self._stderr
        if exc_type is not None and self._transcript is not None:
            traceback_module.print_exception(
                exc_type,
                exc_value,
                traceback,
                file=self._transcript,
            )
        if self._transcript is not None:
            self._transcript.close()


def parse_args(argv: list[str] | None = None) -> SmokeTestOptions:
    """Parse command-line arguments for the live smoke test.

    Args:
        argv: Optional argument list. Uses process arguments when omitted.

    Returns:
        Parsed smoke-test options.
    """
    parser = ArgumentParser(description=__doc__)
    parser.add_argument(
        "--credentials-file",
        type=Path,
        help=(
            "Read credentials from a .env, TOML, or JSON file. Supported keys "
            "include BLUEAIR_USERNAME/BLUEAIR_PASSWORD and username/password."
        ),
    )
    parser.add_argument(
        "--output-file",
        type=Path,
        help="Write stdout, stderr, and smoke-test logs to this transcript file.",
    )
    parser.add_argument(
        "--read-only",
        action="store_true",
        help="Skip the sample device control update while leaving other smoke-test steps enabled.",
    )
    parser.add_argument(
        "--region",
        choices=REGION_CHOICES,
        default="us",
        help="Blueair AWS region for both account auth and device control (default: us).",
    )
    parser.add_argument(
        "--gigya-region",
        choices=REGION_CHOICES,
        help="Override the Gigya account-auth region. Defaults to --region.",
    )
    parser.add_argument(
        "--cloud-region",
        choices=REGION_CHOICES,
        help="Override the BlueCloud REST and MQTT region. Defaults to --region.",
    )
    parser.add_argument(
        "--skip-legacy",
        action="store_true",
        help="Skip the legacy (non-AWS) Blueair API check.",
    )
    namespace: Namespace = parser.parse_args(argv)
    return SmokeTestOptions(
        credentials_file=resolve_invocation_path(namespace.credentials_file),
        output_file=resolve_invocation_path(namespace.output_file),
        read_only=namespace.read_only,
        region=namespace.region,
        gigya_region=namespace.gigya_region,
        cloud_region=namespace.cloud_region,
        skip_legacy=namespace.skip_legacy,
    )


def resolve_invocation_path(path: Path | None) -> Path | None:
    """Resolve a command-line path relative to the launcher invocation directory.

    Args:
        path: Optional path from a command-line argument.

    Returns:
        Absolute path when a relative path was supplied through the launcher.
    """
    if path is None or path.is_absolute():
        return path
    invocation_cwd = os.environ.get("BLUEAIR_API_LIVE_SMOKE_CWD")
    if invocation_cwd is None:
        return path
    return Path(invocation_cwd) / path


def strip_env_value(value: str) -> str:
    """Normalize a dotenv value by trimming whitespace and quotes.

    Args:
        value: Raw value read from a dotenv line.

    Returns:
        Normalized dotenv value.
    """
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {"'", '"'}:
        return stripped[1:-1]
    return stripped


def read_dotenv_credentials(credentials_file: Path) -> dict[str, str]:
    """Read key-value credentials from a dotenv-style file.

    Args:
        credentials_file: File containing one ``KEY=value`` entry per line.

    Returns:
        Parsed dotenv key-value mapping.
    """
    credentials: dict[str, str] = {}
    for line in credentials_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", maxsplit=1)
        credentials[key.strip()] = strip_env_value(value)
    return credentials


def read_credentials_file(credentials_file: Path) -> dict[str, Any]:
    """Read Blueair credentials from a supported config file format.

    Args:
        credentials_file: .env, TOML, or JSON credential file.

    Returns:
        Parsed credential mapping.
    """
    if credentials_file.suffix == ".json":
        with credentials_file.open(encoding="utf-8") as file:
            data = json.load(file)
        if isinstance(data, dict):
            return {str(key): value for key, value in data.items()}
        raise ValueError("JSON credentials file must contain an object")
    if credentials_file.suffix == ".toml":
        with credentials_file.open("rb") as file:
            data = tomllib.load(file)
        blueair_data = data.get("blueair")
        if isinstance(blueair_data, dict):
            return {str(key): value for key, value in blueair_data.items()}
        return {str(key): value for key, value in data.items()}
    return read_dotenv_credentials(credentials_file)


def find_first_value(credentials: Mapping[str, Any], keys: tuple[str, ...]) -> str | None:
    """Find the first non-empty credential value among supported keys.

    Args:
        credentials: Credential mapping to inspect.
        keys: Ordered candidate key names.

    Returns:
        First matching non-empty value, or None.
    """
    for key in keys:
        value = credentials.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            raise TypeError("Credential values must be strings")
        if value:
            return value
    return None


def credential_source_from_mapping(
    credentials: Mapping[str, Any],
    description: str,
) -> CredentialSource | None:
    """Build a credential source from a mapping when both values are present.

    Args:
        credentials: Mapping that may contain username and password values.
        description: Source description for console output.

    Returns:
        Credential source when both username and password are present.
    """
    username = find_first_value(credentials, USERNAME_KEYS)
    password = find_first_value(credentials, PASSWORD_KEYS)
    if username is None or password is None:
        return None
    return CredentialSource(username=username, password=password, description=description)


def load_credentials(options: SmokeTestOptions) -> CredentialSource | None:
    """Load Blueair credentials from file or environment when available.

    Args:
        options: Smoke-test command-line options.

    Returns:
        Non-interactive credential source when both credentials are found.
    """
    if options.credentials_file is not None:
        credentials = read_credentials_file(options.credentials_file)
        credential_source = credential_source_from_mapping(
            credentials,
            str(options.credentials_file),
        )
        if credential_source is None:
            raise ValueError("Credentials file must include both username and password")
        return credential_source
    return credential_source_from_mapping(os.environ, "environment variables")


@contextmanager
def capture_output(output_file: Path | None) -> Iterator[None]:
    """Optionally tee smoke-test output to a transcript file.

    Args:
        output_file: Transcript file path, if capture is requested.

    Yields:
        Control while output capture is active.
    """
    if output_file is None:
        yield
        return
    with SmokeTestTranscript(output_file):
        yield


async def read_input(prompt: str) -> str:
    """Read terminal input without blocking the event loop.

    Args:
        prompt: Prompt to display to the user.

    Returns:
        The entered input text.
    """
    return await asyncio.to_thread(input, prompt)


async def read_password() -> str:
    """Read a password without blocking the event loop.

    Returns:
        The password entered by the user.
    """
    return await asyncio.to_thread(getpass)


def current_timestamp() -> str:
    """Return the current local date and time for console output.

    Returns:
        Local timestamp formatted for human-readable smoke-test logs.
    """
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def device_state(device: Device | DeviceAws) -> dict[str, Any]:
    """Return a device's public dataclass fields for console output.

    Args:
        device: Loaded legacy or AWS device.

    Returns:
        Mapping of every repr-visible field name to its current value. The API
        client and raw payload fields are excluded because they are not
        declared with ``repr=True``.
    """
    return {field.name: getattr(device, field.name) for field in fields(device) if field.repr}


def print_devices(label: str, devices: Sequence[Device | DeviceAws]) -> None:
    """Print the current in-memory state of every loaded device.

    Args:
        label: Heading that identifies which API the devices came from.
        devices: Loaded legacy or AWS devices.
    """
    print(f"{label}: {[device_state(device) for device in devices]}")


class MqttUpdatePrinter:
    """Apply MQTT callbacks to loaded AWS devices and print their new state.

    paho invokes callbacks on its own network thread. Each callback is handed to
    the asyncio event loop with ``call_soon_threadsafe`` so device objects are
    only mutated from the loop thread, matching how library consumers use them.
    """

    def __init__(self, devices: Sequence[DeviceAws], loop: AbstractEventLoop) -> None:
        """Initialize the printer.

        Args:
            devices: Loaded AWS devices that MQTT messages should update.
            loop: Event loop that should apply incoming updates.
        """
        self._devices = {device.uuid: device for device in devices}
        self._loop = loop

    def attach(self, mqtt_client: MqttAwsBlueair) -> None:
        """Register thread-safe callbacks on an MQTT client.

        Args:
            mqtt_client: MQTT client whose callbacks should be wired up.
        """

        def on_sensor_data(device_id: str, sensors: dict[str, float]) -> None:
            """Hand sensor data from the MQTT thread to the event loop.

            Args:
                device_id: Device the readings belong to.
                sensors: Sensor readings.
            """
            self._loop.call_soon_threadsafe(self.handle_sensor_data, device_id, sensors)

        def on_state_change(device_id: str, state: dict[str, Any]) -> None:
            """Hand a state change from the MQTT thread to the event loop.

            Args:
                device_id: Device whose state changed.
                state: Changed state attributes.
            """
            self._loop.call_soon_threadsafe(self.handle_state_change, device_id, state)

        def on_event(device_id: str, event: dict[str, Any]) -> None:
            """Hand a device event from the MQTT thread to the event loop.

            Args:
                device_id: Device the event belongs to.
                event: Event payload.
            """
            self._loop.call_soon_threadsafe(self.handle_event, device_id, event)

        mqtt_client.on_sensor_data = on_sensor_data
        mqtt_client.on_state_change = on_state_change
        mqtt_client.on_event = on_event

    def handle_sensor_data(self, device_id: str, sensors: dict[str, float]) -> None:
        """Apply MQTT sensor data to a device and print its state.

        Args:
            device_id: Device UUID from the MQTT topic.
            sensors: Sensor slug to value mapping from the MQTT payload.
        """
        print(f"MQTT sensor data for {device_id}: {sensors}")
        device = self._devices.get(device_id)
        if device is None:
            return
        device.apply_sensor_data(sensors)
        print_devices("AWS devices", [device])

    def handle_state_change(self, device_id: str, state: dict[str, Any]) -> None:
        """Apply an MQTT shadow state change to a device and print its state.

        Args:
            device_id: Device UUID from the MQTT topic.
            state: Reported shadow state from the MQTT payload.
        """
        print(f"MQTT state change for {device_id}: {state}")
        device = self._devices.get(device_id)
        if device is None:
            return
        device.apply_state_change(state)
        print_devices("AWS devices", [device])

    def handle_event(self, device_id: str, event: dict[str, Any]) -> None:
        """Print an MQTT connectivity event.

        Args:
            device_id: Device UUID that originated the event.
            event: Parsed event payload.
        """
        print(f"MQTT event for {device_id}: {event}")


async def start_mqtt_listener(
    api: HttpAwsBlueair,
    devices: Sequence[DeviceAws],
) -> MqttAwsBlueair | None:
    """Connect to the Blueair MQTT broker and subscribe to every AWS device.

    Args:
        api: Authenticated AWS HTTP client that holds the MQTT credentials.
        devices: Loaded AWS devices to subscribe to.

    Returns:
        Connected MQTT client, or None when the login response did not include
        MQTT credentials or there are no AWS devices to subscribe to.
    """
    if not devices:
        print("No AWS devices available; skipping MQTT listener.")
        return None
    if (
        not api.mqtt_auth_name
        or not api.mqtt_auth_signature
        or not api.mqtt_auth_token
        or not api.user_id
    ):
        print("MQTT credentials were not returned by login; skipping MQTT listener.")
        return None

    async def refresh_credentials() -> tuple[str, str, str]:
        """Refresh the AWS login and return new MQTT credentials.

        Returns:
            MQTT auth name, signature, and token.
        """
        await api.refresh_access_token()
        return (
            api.mqtt_auth_name or "",
            api.mqtt_auth_signature or "",
            api.mqtt_auth_token or "",
        )

    loop = asyncio.get_running_loop()
    mqtt_client = MqttAwsBlueair(
        region=api.cloud_region,
        mqtt_auth_name=api.mqtt_auth_name,
        mqtt_auth_signature=api.mqtt_auth_signature,
        mqtt_auth_token=api.mqtt_auth_token,
        user_id=api.user_id,
    )
    mqtt_client.credential_refresher = refresh_credentials
    MqttUpdatePrinter(devices, loop).attach(mqtt_client)
    for device in devices:
        mqtt_client.register_device(device.uuid)
    # paho's connect performs a blocking network handshake.
    await asyncio.to_thread(mqtt_client.connect, loop)
    return mqtt_client


async def send_sample_control_update(devices: Sequence[DeviceAws]) -> bool:
    """Write the first AWS device's current brightness back to it.

    Args:
        devices: Loaded AWS devices.

    Returns:
        True when the update was sent, otherwise False when there is no device
        or the device does not report a brightness value.
    """
    if not devices:
        print("No AWS devices available; skipping sample control update.")
        return False
    device = devices[0]
    brightness = device.brightness
    if not isinstance(brightness, int) or isinstance(brightness, bool):
        print(f"{device.name} does not report brightness; skipping sample control update.")
        return False
    print(f"Writing current brightness {brightness} back to {device.name}.")
    await device.set_brightness(brightness)
    return True


async def maybe_send_sample_control_update(
    devices: Sequence[DeviceAws],
    *,
    read_only: bool,
) -> bool:
    """Send the sample control update unless the smoke test is in read-only mode.

    Args:
        devices: Loaded AWS devices.
        read_only: Whether to skip mutation calls.

    Returns:
        True when the update is sent successfully, otherwise False.
    """
    if read_only:
        print("Read-only mode enabled; skipping sample control update.")
        return False
    return await send_sample_control_update(devices)


async def run_aws_check(
    username: str,
    password: str,
    options: SmokeTestOptions,
    client_session: ClientSession,
) -> tuple[HttpAwsBlueair, list[DeviceAws]]:
    """Log in to the AWS Blueair API, then load, refresh, and print devices.

    Args:
        username: Blueair account email address.
        password: Blueair account password.
        options: Smoke-test command-line options.
        client_session: HTTP session owned by the smoke test.

    Returns:
        Authenticated AWS HTTP client and its loaded devices.
    """
    api, devices = await get_aws_devices(
        username=username,
        password=password,
        region=options.region,
        client_session=client_session,
        gigya_region=options.gigya_region,
        cloud_region=options.cloud_region,
    )
    for device in devices:
        await device.refresh()
    print_devices("AWS devices", devices)
    return api, devices


async def run_legacy_check(
    username: str,
    password: str,
    client_session: ClientSession,
) -> list[Device]:
    """Log in to the legacy Blueair API, then load, refresh, and print devices.

    Many accounts only exist on the AWS API, so legacy API errors are printed
    rather than ending the smoke test.

    Args:
        username: Blueair account email address.
        password: Blueair account password.
        client_session: HTTP session owned by the smoke test.

    Returns:
        Loaded legacy devices, or an empty list when the legacy API fails.
    """
    try:
        _, devices = await get_devices(
            username=username,
            password=password,
            client_session=client_session,
        )
        for device in devices:
            await device.refresh()
    except BaseError as err:
        print(f"Legacy API check failed: {err!r}")
        return []
    print_devices("Legacy devices", devices)
    return devices


async def main(options: SmokeTestOptions) -> None:
    """Log in, load devices, start MQTT updates, and send one sample update.

    Args:
        options: Parsed smoke-test command-line options.
    """
    print(INTRO_TEXT)
    print()
    credentials = load_credentials(options)
    if credentials is None:
        username = await read_input("Blueair account email address: ")
        password = await read_password()
    else:
        username = credentials.username
        password = credentials.password
        print(f"Using Blueair credentials from {credentials.description}.")
    aws_session: ClientSession | None = None
    legacy_session: ClientSession | None = None
    mqtt_client: MqttAwsBlueair | None = None
    completed = False
    print()
    print(f"Starting Smoke Test at {current_timestamp()}")
    print("--------------------------------------------------------------------------")
    print()
    try:
        aws_session = ClientSession(raise_for_status=False)
        aws_api, aws_devices = await run_aws_check(username, password, options, aws_session)
        mqtt_client = await start_mqtt_listener(aws_api, aws_devices)
        logger.debug("started mqtt listener")

        await maybe_send_sample_control_update(aws_devices, read_only=options.read_only)

        if options.skip_legacy:
            print("Skipping legacy API check.")
        else:
            legacy_session = ClientSession(raise_for_status=False)
            await run_legacy_check(username, password, legacy_session)

        print()
        print("--------------------------------------------------------------------------")
        print("The script will now wait 5 minutes, so MQTT messages can be observed")
        print("--------------------------------------------------------------------------")
        print()
        await sleep(SMOKE_TEST_WAIT_SECONDS)
        completed = True
    finally:
        if mqtt_client is not None:
            await asyncio.to_thread(mqtt_client.disconnect)
        if aws_session is not None:
            await aws_session.close()
        if legacy_session is not None:
            await legacy_session.close()
        if completed:
            print()
            print("--------------------------------------------------------------------------")
            print(f"Smoke test complete at {current_timestamp()}")


if __name__ == "__main__":
    smoke_test_options = parse_args()
    with capture_output(smoke_test_options.output_file):
        asyncio.run(main(smoke_test_options))

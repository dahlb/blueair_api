"""Manual live Blueair API smoke-test script for local development.

Run with ``python3 src/blueair_api/stub.py``. Prompts for Blueair account
credentials at the terminal, then connects to both the legacy and AWS
Blueair APIs, loads devices, refreshes their state, and logs the result.
"""

import asyncio
from getpass import getpass
import logging
from pathlib import Path
import sys

path_src = Path(__file__).parents[1]
sys.path.append(str(path_src))
from blueair_api import get_aws_devices, get_devices

logger = logging.getLogger("blueair_api")
logger.setLevel(logging.DEBUG)
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
ch.setFormatter(formatter)
logger.addHandler(ch)


async def testing(username: str, password: str) -> None:
    """Load and refresh devices from both the AWS and legacy Blueair APIs."""
    try:
        aws_api, aws_devices = await get_aws_devices(username=username, password=password)
        for aws_device in aws_devices:
            await aws_device.refresh()
            logger.debug(aws_device)
    finally:
        if aws_api:
            await aws_api.cleanup_client_session()
    try:
        legacy_api, legacy_devices = await get_devices(username=username, password=password)
        for legacy_device in legacy_devices:
            await legacy_device.refresh()
            logger.debug(legacy_device)
    finally:
        if legacy_api:
            await legacy_api.cleanup_client_session()


def main() -> None:
    """Prompt for credentials, then run the live smoke test."""
    username = input("Username: ")
    password = getpass()
    asyncio.run(testing(username, password))


main()

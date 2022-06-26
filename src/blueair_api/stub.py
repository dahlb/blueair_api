# run with "python3 src/blueair_api/stub.py"
import logging
import asyncio
from threading import Event

from getpass import getpass
from pathlib import Path
import sys

# import blueair_api

path_root = Path(__file__).parents[2]
sys.path.append(str(path_root))
from src.blueair_api import get_devices, get_aws_devices


logger = logging.getLogger("src.blueair_api")
logger.setLevel(logging.DEBUG)
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
ch.setFormatter(formatter)
logger.addHandler(ch)


async def testing():
    username = input("Username: ")
    password = getpass()
    try:
        api, devices = await get_aws_devices(username=username, password=password)
        await devices[0].refresh()
        await devices[0].set_child_lock(True)
        logger.debug(devices[0])
    finally:
        if api:
            await api.cleanup_client_session()
    try:
        api, devices = await get_devices(username=username, password=password)
        for device in devices:
            await device.init()
            await device.refresh()
            logger.debug(device)
    finally:
        if api:
            await api.cleanup_client_session()


asyncio.run(testing())

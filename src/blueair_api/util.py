"""Small data-shaping helpers shared by the Blueair device and HTTP clients."""

from collections.abc import Callable, Mapping
import logging
from typing import Any

from .const import SENSITIVE_FIELD_NAMES, MeasurementList

_LOGGER = logging.getLogger(__name__)


def clean_dictionary_for_logging(dictionary: Any) -> Any:
    """Return a copy of ``dictionary`` with sensitive fields masked for logging.

    API responses are not always JSON objects: some endpoints (e.g. the legacy
    home host lookup) return a bare JSON string, and others return a list.
    Mappings are masked recursively, lists are cleaned item by item, and any
    other value is returned unchanged so logging never breaks a request.

    Args:
        dictionary: A decoded JSON value or header mapping to sanitize.

    Returns:
        A sanitized copy for mappings and lists, otherwise ``dictionary`` itself.
    """
    if isinstance(dictionary, list):
        return [clean_dictionary_for_logging(item) for item in dictionary]
    if not isinstance(dictionary, Mapping):
        return dictionary
    mutable_dictionary: dict[Any, Any] = {}
    for key, value in dictionary.items():
        if isinstance(key, str) and key.lower() in SENSITIVE_FIELD_NAMES:
            mutable_dictionary[key] = "***"
        else:
            mutable_dictionary[key] = clean_dictionary_for_logging(value)

    return mutable_dictionary


def safely_get_json_value(
    json: Any,
    key: str,
    callable_to_cast: Callable[[Any], Any] | None = None,
) -> Any:
    """Walk ``key`` (a dotted/indexed path) into ``json``, returning ``None`` if missing."""
    value = json
    for x in key.split("."):
        if value is not None:
            try:
                value = value[x]
            except TypeError, KeyError:
                try:
                    value = value[int(x)]
                except TypeError, KeyError, ValueError:
                    value = None
    if callable_to_cast is not None and value is not None:
        value = callable_to_cast(value)
    return value


def convert_none_to_not_implemented(value: Any) -> Any:
    """Return ``NotImplemented`` for a ``None`` value, otherwise return it unchanged."""
    if value is None:
        return NotImplemented
    return value


def transform_data_points(data: Mapping[str, Any]) -> MeasurementList:
    """Transform a measurement list response from the Blueair API.

    Converts it to a more pythonic data structure.
    """
    key_mapping = {
        "time": "timestamp",
        "pm": "pm25",
        "pm1": "pm1",
        "pm10": "pm10",
        "tmp": "temperature",
        "hum": "humidity",
        "co2": "co2",
        "voc": "voc",
        "allpollu": "all_pollution",
    }

    keys = [key_mapping[key] for key in data.get("sensors", {})]

    return [dict(zip(keys, values, strict=False)) for values in data.get("datapoints", {})]

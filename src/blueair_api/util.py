"""Small data-shaping helpers shared by the Blueair device and HTTP clients."""

from collections.abc import Callable, Mapping
import logging
from typing import Any

from .const import SENSITIVE_FIELD_NAMES, MeasurementList

_LOGGER = logging.getLogger(__name__)


def clean_dictionary_for_logging(dictionary: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``dictionary`` with sensitive fields masked for logging."""
    mutable_dictionary = dictionary.copy()
    for key in dictionary:
        if key.lower() in SENSITIVE_FIELD_NAMES:
            mutable_dictionary[key] = "***"
        if type(mutable_dictionary[key]) is dict:
            mutable_dictionary[key] = clean_dictionary_for_logging(mutable_dictionary[key].copy())
        if type(mutable_dictionary[key]) is list:
            new_array = []
            for item in mutable_dictionary[key]:
                if type(item) is dict:
                    new_array.append(clean_dictionary_for_logging(item.copy()))
                else:
                    new_array.append(item)
            mutable_dictionary[key] = new_array

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
            except (TypeError, KeyError):
                try:
                    value = value[int(x)]
                except (TypeError, KeyError, ValueError):
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

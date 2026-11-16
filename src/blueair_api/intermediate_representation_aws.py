"""Typed intermediate representation for the Blueair AWS device shadow schema."""

import base64
from collections.abc import Iterable
import dataclasses
from logging import getLogger
import typing
from typing import Any

type ScalarType = str | float | bool | int | None
type MappingType = dict[str, "ObjectType"]
type SequenceType = list["ObjectType"]
type ObjectType = ScalarType | MappingType | SequenceType

_LOGGER = getLogger(__name__)


def query_json(jsonobj: ObjectType, path: str) -> ObjectType:
    """Resolve a dotted/indexed ``path`` (e.g. ``a.0.b``) within ``jsonobj``."""
    value = jsonobj
    segs = path.split(".")
    for i, seg in enumerate(segs):
        if isinstance(value, list):
            value = value[int(seg)]
        elif isinstance(value, dict):
            if seg in value:
                value = value[seg]
            elif i == len(segs) - 1:
                # last segment returns None if it is not found.
                value = None
            else:
                raise KeyError(
                    f"cannot resolve path segment on a scalar "
                    f"when resolving segment {i}:{seg} of {path}. "
                    f"available keys are {value.keys()}."
                )
        else:
            raise KeyError(
                f"cannot resolve path segment on a scalar "
                f"when resolving segment {i}:{seg} of {path}."
            )
    return value


def parse_json[T](kls: type[T], jsonobj: MappingType) -> dict[str, T]:
    """Parses a json mapping object to dict.

    The key is preserved. The value is parsed as dataclass type kls.
    """
    if not dataclasses.is_dataclass(kls):
        raise TypeError(f"{kls} is not a dataclass")
    result = {}
    fields = dataclasses.fields(kls)

    for key, value in jsonobj.items():
        if not isinstance(value, dict):
            raise TypeError("expecting mapping value to be dict.")
        extra_fields = dict(value)  # make extra_fields copy.
        kwargs: dict[str, Any] = {}
        for field in fields:
            if field.name == "extra_fields":
                kwargs[field.name] = extra_fields
            elif field.default is dataclasses.MISSING:
                kwargs[field.name] = extra_fields.pop(field.name)
            else:
                kwargs[field.name] = extra_fields.pop(field.name, field.default)

        obj = kls(**kwargs)
        result[key] = typing.cast("T", obj)
    return result


########################
# Blueair AWS API Schema.


@dataclasses.dataclass
class Attribute:
    """DeviceAttribute(da); defines an attribute.

    An attribute is most likely mutable. An attribute may
    also have alias names, likely derived from the 'dc' relation
    e.g. a/sb, a/standby all refer to the 'sb' attribute.
    """

    extra_fields: MappingType
    n: str  # name
    a: int | bool  # default attribute value, example value?
    e: bool  # ??? always True
    fe: bool  # ???  always True
    ot: str  # object type? topic type?
    p: bool  # only false for reboot and sflu
    tn: str  # topic name a path-like name d/????/a/{n}


@dataclasses.dataclass
class Sensor:
    """DeviceSensor(ds); seems to define a sensor.

    We never directly access these objects. Though this defines
    the schema for 'h', 't', 'pm10' etc that gets returned in
    the sensor_data senml SensorPack.
    """

    extra_fields: MappingType
    n: str  # name
    i: int  # integration time? in millis
    e: bool  # ???
    fe: bool  # ??? always True.
    ot: str  # object type / topic name
    tn: str  # topic name a path-like name d/????/s/{n}
    ttl: int  # only seen 0 or -1, not sure if used.
    tf: str | None = None  # senml+json; topic format


@dataclasses.dataclass
class Control:
    """DeviceControl (dc); seems to define a state.

    The states SensorPack seem to be using fields defined
    in dc. The only exception is 'online' which is not defined
    here.
    """

    extra_fields: MappingType
    n: str  # name
    v: int | bool
    a: str | None = None
    s: str | None = None
    d: str | None = None  # device info json path


@dataclasses.dataclass
class SensorRecord:
    """A single timestamped set of sensor values."""

    values: dict[str, int]
    timestamp: float | None


class SensorHistory(list[SensorRecord]):
    """A time-ordered list of ``SensorRecord`` built from a datapoints response."""

    def __init__(self, response: list[dict[str, Any]] | None) -> None:
        """Build the history from a ``get_data_points_since``-style response."""
        if response is None:
            sensors = []
            datapoints = []
        else:
            sensors = response[0]["sensors"]
            datapoints = response[0]["datapoints"]
        sensor_records = []
        for datapoint in datapoints:
            values = {}
            for idx, sensor in enumerate(sensors):
                if datapoint[idx + 1] is not None:
                    values[sensor] = int(datapoint[idx + 1])
            sensor_records.append(SensorRecord(timestamp=int(datapoint[0]), values=values))
        super().__init__(sensor_records)

    def to_latest(self) -> SensorRecord:
        """Return the most recent record, or an empty one if there are none."""

        def key(record: SensorRecord) -> float:
            return record.timestamp if record.timestamp is not None else float("-inf")

        self.sort(key=key, reverse=True)
        if len(self) > 0:
            return self[0]
        return SensorRecord(values={}, timestamp=0)


########################
# SenML RFC8428


@dataclasses.dataclass
class Record:
    """A RFC8428 SenML record, resolved to Python types."""

    name: str
    unit: str | None
    value: float | bool | str | bytes | None
    timestamp: float | None
    integral: float | None


class SensorPack(list[Record]):
    """Represents a RFC8428 SensorPack, resolved to Python Types."""

    def __init__(self, stream: Iterable[MappingType]) -> None:
        """Parse a stream of raw SenML records into ``Record`` instances."""
        seq = []
        for record in stream:
            rs = None
            rt = None
            rn: str = ""
            ru = None
            rv: float | bool | str | bytes | None = None
            for label, value in record.items():
                _LOGGER.debug("parsing senml record field %s with value %s", label, value)
                if not isinstance(value, str | int | float | bool):
                    # Skip non-scalar values (e.g. 'vj' alarm JSON dicts).
                    _LOGGER.debug("skipping non-scalar senml field %s", label)
                    continue
                match label:
                    case "bn" | "bt" | "bu" | "bv" | "bs" | "bver":
                        raise ValueError("TODO: base fields not supported. c.f. RFC8428, 4.1")
                    case "t":
                        rt = float(value)
                    case "s":
                        rs = float(value)
                    case "v":
                        rv = float(value)
                    case "vb":
                        rv = bool(value)
                    case "vs":
                        rv = str(value)
                    case "vd":
                        rv = bytes(base64.b64decode(str(value)))
                    case "vj":
                        rv = value
                    case "n":
                        rn = str(value)
                    case "u":
                        ru = str(value)
            seq.append(Record(name=rn, unit=ru, value=rv, integral=rs, timestamp=rt))
        super().__init__(seq)

    def to_latest_value(self) -> dict[str, str | bool | float | bytes | None]:
        """Return the most recent value per record name."""
        return {rn: record.value for rn, record in self.to_latest().items()}

    def to_latest(self) -> dict[str, Record]:
        """Return the most recent record per record name."""
        latest: dict[str, Record] = {}
        for record in self:
            rn = record.name
            if record.name not in latest:
                latest[rn] = record
                continue
            lt = latest[record.name].timestamp
            if record.timestamp is None or lt is None or lt < record.timestamp:
                latest[rn] = record
        return latest

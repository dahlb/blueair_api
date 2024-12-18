import typing
from typing import Any, TypeVar
from collections.abc import Iterable
import dataclasses
import base64

type ScalarType = str | float | bool | int | None
type MappingType = dict[str, "ObjectType"]
type SequenceType = list["ObjectType"]
type ObjectType = ScalarType | MappingType | SequenceType


def query_json(jsonobj: ObjectType, path: str) -> ObjectType:
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
                    f"available keys are {value.keys()}.")
        else:
            raise KeyError(
                f"cannot resolve path segment on a scalar "
                f"when resolving segment {i}:{seg} of {path}.")
    return value

def parse_json[T](kls: type[T], jsonobj: MappingType) -> dict[str, T]:
    """Parses a json mapping object to dict.

    The key is preserved. The value is parsed as dataclass type kls.
    """
    assert dataclasses.is_dataclass(kls)
    result = {}
    fields = dataclasses.fields(kls)

    for key, value in jsonobj.items():
        if not isinstance(value, dict):
            raise TypeError("expecting mapping value to be dict.")
        extra_fields = dict(value)  # make extra_fields copy.
        kwargs : dict[str, Any] = {}
        for field in fields:
            if field.name == "extra_fields":
                kwargs[field.name] = extra_fields
            elif field.default is dataclasses.MISSING:
                kwargs[field.name] = extra_fields.pop(field.name)
            else:
                kwargs[field.name] = extra_fields.pop(field.name, field.default)

        obj = kls(**kwargs)
        result[key] = typing.cast(T, obj)
    return result


########################
# Blueair AWS API Schema.

@dataclasses.dataclass
class Attribute:
    """DeviceAttribute(da); defines an attribute

    An attribute is most likely mutable. An attribute may
    also have alias names, likely derived from the 'dc' relation
    e.g. a/sb, a/standby all refer to the 'sb' attribute.
    """
    extra_fields : MappingType
    n: str   # name
    a: int | bool   # default attribute value, example value?
    e: bool     # ??? always True
    fe:bool     # ???  always True
    ot: str     # object type? topic type?
    p: bool     # only false for reboot and sflu
    tn: str   # topic name a path-like name d/????/a/{n}


@dataclasses.dataclass
class Sensor:
    """DeviceSensor(ds); seems to define a sensor.

    We never directly access these objects. Thos this defines
    the schema for 'h', 't', 'pm10' etc that gets returned in
    the sensor_data senml SensorPack.
    """
    extra_fields : MappingType
    n: str    # name
    i: int    # integration time? in millis
    e: bool   # ???
    fe: bool  # ??? always True.
    ot: str   # object type / topic name
    tn: str   # topic name a path-like name d/????/s/{n}
    ttl: int  # only seen 0 or -1, not sure if used.
    tf: str | None = None   # senml+json; topic format

@dataclasses.dataclass
class Control:
    """DeviceControl (dc); seems to define a state.

    The states SensorPack seem to be using fields defined
    in dc. The only exception is 'online' which is not defined
    here.
    """
    extra_fields : MappingType
    n: str  # name
    v: int | bool
    a: str | None = None
    s: str | None = None
    d: str | None = None  # device info json path


########################
# SenML RFC8428

@dataclasses.dataclass
class Record:
    """A RFC8428 SenML record, resolved to Python types."""
    name: str
    unit: str | None
    value: float | bool | str | bytes
    timestamp: float | None
    integral: float | None


class SensorPack(list[Record]):
    """Represents a RFC8428 SensorPack, resolved to Python Types."""

    def __init__(self, stream: Iterable[MappingType]):
        seq = []
        for record in stream:
            rs = None
            rt = None
            rn : str
            ru = None
            rv : float | bool | str | bytes
            for label, value in record.items():
                assert isinstance(value, str | int | float | bool)
                match label:
                    case 'bn' | 'bt' | 'bu' | 'bv' | 'bs' | 'bver':
                        raise ValueError("TODO: base fields not supported. c.f. RFC8428, 4.1")
                    case 't':
                        rt = float(value)
                    case 's':
                        rs = float(value)
                    case 'v':
                        rv = float(value)
                    case 'vb':
                        rv = bool(value)
                    case 'vs':
                        rv = str(value)
                    case 'vd':
                        rv = bytes(base64.b64decode(str(value)))
                    case 'n':
                        rn = str(value)
                    case 'u':
                        ru = str(value)
            seq.append(Record(name=rn, unit=ru, value=rv, integral=rs, timestamp=rt))
        super().__init__(seq)

    def to_latest_value(self) -> dict[str, str | bool | float | bytes]:
        return {rn : record.value for rn, record in self.to_latest().items()}

    def to_latest(self) -> dict[str, Record]:
        latest : dict[str, Record] = {}
        for record in self:
            rn = record.name
            if record.name not in latest:
                latest[rn] = record
                continue
            lt = latest[record.name].timestamp
            if record.timestamp is None:
                latest[rn] = record
            elif lt is None:
                latest[rn] = record
            elif lt < record.timestamp:
                latest[rn] = record
        return latest

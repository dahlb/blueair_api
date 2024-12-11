from typing import Any
import dataclasses
import base64


@dataclasses.dataclass
class Attribute:
  """da; defines an attribute

  An attribute is most likely mutable. An attribute may
  also have alias names, likely derived from the 'dc' relation
  e.g. a/sb, a/standby all refer to the 'sb' attribute.
  """
  n: str   # name
  a: int | bool   # default attribute value, example value?
  e: bool     # ??? always True
  fe:bool     # ???  always True
  ot: str     # object type? topic type?
  p: bool     # only false for reboot and sflu
  tn: str   # topic name a path-like name d/????/a/{n}
  _extra_fields : dict[str, Any] # additional fields

@dataclasses.dataclass
class Sensor:
  """ds; seems to define a sensor.

  We never directly access these objects. Thos this defines
  the schema for 'h', 't', 'pm10' etc that gets returned in
  the sensor_data senml SensorPack.
  """
  n: str    # name
  i: int    # integration time? in millis
  e: bool   # ??? 
  fe: bool  # ??? always True.
  ot: str   # object type / topic name
  tf: str   # senml+json; topic format
  tn: str   # topic name a path-like name d/????/s/{n}
  ttl: int  # only seen 0 or -1, not sure if used.

@dataclasses.dataclass
class State:
  """dc; seems to define a state.

  The states SensorPack seem to be using fields defined
  in dc. The only exception is 'online' which is not defined
  here.
  """
  n: str  # name
  v: int | bool
  a: Attribute | None
  s: Sensor | None
  # device info field path
  d: str | None


@dataclasses.dataclass
class Record:
  name: str
  unit: str | None
  value: float | str | bool
  timestamp: float | None
  integral: float | None


class SensorPack(list[Record]):
  """Represents a RFC8428 SensorPack, resolved to Python Types."""

  def __init__(self, stream: list[dict[str, Any]]):
    seq = []
    for record in stream:
      rs = None
      rt = None
      rn = 0
      ru = None
      for label, value in record.items():
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
            rv = bytes(base64.b64decode(value))
          case 'n':
            rn = str(value)
          case 'u':
            ru = str(value)
          case 't':
            rn = float(value)
      seq.append(Record(name=rn, unit=ru, value=rv, integral=rs, timestamp=rt))
    super().__init__(seq)

  def to_latest(self):
    latest = {}
    for record in self:
      rn = record.name
      if record.name not in latest:
        latest[rn] = record
      elif record.timestamp is None:
        latest[rn] = record
      elif latest[record.name].timestamp is None:
        latest[rn] = record
      elif latest[record.name].timestamp < record.timestamp:
        latest[rn] = record
    return latest


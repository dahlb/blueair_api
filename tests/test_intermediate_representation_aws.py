import dataclasses
from unittest import TestCase

import pytest

from blueair_api import intermediate_representation_aws as ir

class SensorPackTest(TestCase):

  def testSimple(self):
    sp = ir.SensorPack( [
            {'n': 'v', 't': 1, 'v': 1},
            {'n': 'vb', 't': 2, 'vb': True},
            {'n': 'vs', 't': 3, 'vs': "s"},
            {'n': 'vd', 't': 4, 'vd': "MTIzCg=="},  # b'123\n'
            {'n': 'no_t', 'v': 1},
            {'n': 'no_s', 'v': 1},
            {'n': 's', 'v': 1, 's': 2},
            {'n': 'u', 'v': 1, 'u': "unit"},
            {'n': 'no_u', 'v': 1},
     ])

    latest = sp.to_latest()

    assert latest['v'].timestamp == 1
    assert latest['v'].value == 1
    assert isinstance(latest['v'].value, float)

    assert latest['vb'].timestamp == 2
    assert latest['vb'].value is True
    assert isinstance(latest['vb'].value, bool)

    assert latest['vs'].timestamp == 3
    assert latest['vs'].value == "s"
    assert isinstance(latest['vs'].value, str)

    assert latest['vd'].timestamp == 4
    assert latest['vd'].value == b"123\n"
    assert isinstance(latest['vd'].value, bytes)

    assert latest['no_t'].timestamp is None

    assert latest['no_s'].integral is None
    assert latest['s'].integral == 2
    assert latest['s'].value == 1

    assert latest['no_u'].unit is None
    assert latest['u'].unit == "unit"

  def testToLatestMissingT1None(self):
    sp = ir.SensorPack( [
            {'n': 'missing_t', 't': 1, 'v': 1},
            {'n': 'missing_t', 'v': 2},
    ])

    latest = sp.to_latest()
    assert latest['missing_t'].value == 2

  def testToLatestMissingTNoneNone(self):
    sp = ir.SensorPack( [
            {'n': 'missing_t', 'v': 1},
            {'n': 'missing_t', 'v': 2},
    ])

    latest = sp.to_latest()
    assert latest['missing_t'].value == 2

  def testToLatestMissingTNone1(self):
    sp = ir.SensorPack( [
            {'n': 'missing_t', 'v': 1},
            {'n': 'missing_t', 't': 1, 'v': 2},
    ])

    latest = sp.to_latest()
    assert latest['missing_t'].value == 2

  def testToLatestReversedOrder(self):
    sp = ir.SensorPack( [
            {'n': 'missing_t', 't': 2, 'v': 2},
            {'n': 'missing_t', 't': 1, 'v': 1},
    ])

    latest = sp.to_latest()
    assert latest['missing_t'].value == 2


class QueryJsonTest(TestCase):

    def test_mapping_one(self):
        assert ir.query_json({"a": 0}, "a") == 0

    def test_mapping_two(self):
        assert ir.query_json({"a": {"b": 0}}, "a.b") == 0

    def test_sequence(self):
        assert ir.query_json([{"a": 1}], "0.a") == 1

    def test_none(self):
        # last segment not found produces None.
        assert ir.query_json([{"a": 1}], "0.r") is None

    def test_scalar_error(self):
        with pytest.raises(KeyError):
            ir.query_json(3, "0.r")

    def test_key_error(self):
        with pytest.raises(KeyError):
            # intermediate segment not found produces KeyError
            ir.query_json({"a": {"b": 3}}, "r.b")

@dataclasses.dataclass
class FakeObjectType:
    a : str
    extra_fields: ir.MappingType

class ParseJsonTest(TestCase):

    def test_mapping_one(self):
        d = ir.parse_json(FakeObjectType, {
              "one" :{"a": "1", "e" : 1},
              "two" :{"a": "2", "e" : 2},
            })
        assert d == {
                "one" : FakeObjectType(a="1", extra_fields={"e":1}),
                "two" : FakeObjectType(a="2", extra_fields={"e":2}),
            }


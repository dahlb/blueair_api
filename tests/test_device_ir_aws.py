from unittest import TestCase
from blueair_api.device_ir_aws import SensorPack, Record

class SensorPackTest(TestCase):

  def testSimple(self):
    sp = SensorPack( [
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
    sp = SensorPack( [
            {'n': 'missing_t', 't': 1, 'v': 1},
            {'n': 'missing_t', 'v': 2},
    ])

    latest = sp.to_latest()
    assert latest['missing_t'].value == 2

  def testToLatestMissingTNoneNone(self):
    sp = SensorPack( [
            {'n': 'missing_t', 'v': 1},
            {'n': 'missing_t', 'v': 2},
    ])

    latest = sp.to_latest()
    assert latest['missing_t'].value == 2

  def testToLatestMissingTNone1(self):
    sp = SensorPack( [
            {'n': 'missing_t', 'v': 1},
            {'n': 'missing_t', 't': 1, 'v': 2},
    ])

    latest = sp.to_latest()
    assert latest['missing_t'].value == 2

  def testToLatestReversedOrder(self):
    sp = SensorPack( [
            {'n': 'missing_t', 't': 2, 'v': 2},
            {'n': 'missing_t', 't': 1, 'v': 1},
    ])

    latest = sp.to_latest()
    assert latest['missing_t'].value == 2


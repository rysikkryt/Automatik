import math

import pytest

from sim import j1939
from sim.j1939 import Status


def test_css_electronics_published_example():
    # CSS Electronics "J1939 Explained": 0x0CF00401 FF FF FF 68 13 FF FF FF -> 621 rpm.
    pgn, sa, readings = j1939.decode_frame(0x0CF00401, bytes.fromhex("FFFFFF6813FFFFFF"))
    assert (pgn, sa) == (61444, 0x01)
    assert readings[190].value == 621.0 and readings[190].status is Status.OK


def test_identifiers():
    assert j1939.can_id(65253, 0x00) == 0x18FEE500
    assert j1939.can_id(61444, 0x00) == 0x0CF00400
    assert j1939.parse_can_id(0x18FEE500) == (6, 65253, 0x00, 0xFF)
    identifier, data = j1939.request_frame(65253, 0xF9, destination=0x00)
    assert identifier == 0x18EA00F9 and data == bytes.fromhex("E5FE00")
    assert j1939.parse_can_id(identifier) == (6, 59904, 0xF9, 0x00)


@pytest.mark.parametrize(
    "spn,value",
    [(247, 12345.65), (245, 987654.125), (917, 123456785.0), (190, 1450.5), (84, 23.5), (110, -12.0), (96, 62.4), (250, 81234.5)],
)
def test_round_trip(spn, value):
    pgn = j1939.SPNS[spn].pgn
    reading = j1939.decode(pgn, j1939.encode(pgn, {spn: value}))[spn]
    assert reading.status is Status.OK
    assert math.isclose(reading.value, value, abs_tol=j1939.SPNS[spn].resolution / 2)


def test_engine_hours_resolution_and_limits():
    data = j1939.encode(65253, {247: 0.05})
    assert data[:4] == b"\x01\x00\x00\x00"
    # Little-endian: the largest valid raw value 0xFAFFFFFF is transmitted as FF FF FF FA.
    assert j1939.decode(65253, bytes.fromhex("FFFFFFFA" + "FFFFFFFF"))[247].value == pytest.approx(0xFAFFFFFF * 0.05)
    assert j1939.decode(65253, bytes.fromhex("FFFFFFFB" + "FFFFFFFF"))[247].status is Status.RESERVED
    with pytest.raises(ValueError):
        j1939.encode(65253, {247: 0xFAFFFFFF * 0.05 + 1})


def test_not_available_and_error_are_not_numbers():
    readings = j1939.decode(65253, bytes.fromhex("FFFFFFFF" + "00FFFFFE"))
    assert readings[247].status is Status.NOT_AVAILABLE and readings[247].value is None
    assert readings[249].status is Status.ERROR and readings[249].value is None
    assert j1939.decode(65262, bytes.fromhex("FE" + "FF" * 7))[110].status is Status.ERROR
    assert j1939.decode(65262, bytes.fromhex("FC" + "FF" * 7))[110].status is Status.RESERVED


def test_unrequested_pgn_is_ignored():
    assert j1939.decode_frame(j1939.can_id(65280, 0x00), bytes(8)) is None

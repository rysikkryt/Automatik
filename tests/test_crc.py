"""Checksums pinned by catalogue values, official examples and real device packets."""

import re

from sim.crc import crc8_egts, crc16_arc, crc16_ccitt, crc16_modbus


def test_catalogue_check_values():
    data = b"123456789"
    assert crc16_arc(data) == 0xBB3D
    assert crc16_modbus(data) == 0x4B37
    assert crc16_ccitt(data) == 0x29B1
    assert crc8_egts(data) == 0xF7  # CRC-8, poly 0x31, init 0xFF (reveng: CRC-8/NRSC-5)


def test_wialon_official_examples():
    # Examples printed in the Gurtam Wialon IPS v2.2 specification.
    assert f"{crc16_arc(b'2.0;imei;NA;'):04X}" == "A932"
    body = b"231012;153959;5354.49260;N;02731.44990;E;0;0;300;7;1.1;0;0;1,0,0,0;NA;ign:1:1,dparam:2:3.14159265,tparam:3:lorem,iparam:1:-55,SOS:1:1;"
    assert f"{crc16_arc(body):04X}" == "4BC3"


def test_galileosky_real_packets_use_crc16_modbus(vectors):
    packets = [bytes.fromhex(h) for h in vectors["galileosky_main"]]
    assert len(packets) == 12
    for p in packets:
        assert crc16_modbus(p[:-2]) == int.from_bytes(p[-2:], "little")


def test_egts_real_packets_header_and_frame_crc(vectors):
    for h in vectors["egts"]:
        p = bytes.fromhex(h)
        hl, fdl = p[3], int.from_bytes(p[5:7], "little")
        assert crc8_egts(p[: hl - 1]) == p[hl - 1]
        assert crc16_ccitt(p[hl : hl + fdl]) == int.from_bytes(p[hl + fdl : hl + fdl + 2], "little")


def test_wialon_real_v2_packets(vectors):
    results = []
    for s in vectors["wialon_v2_with_crc"]:
        rest = re.match(r"^(?:[\d.]+;)?[^#]*#[A-Z]+#(.*)$", s).group(1)
        results.append((s, crc16_arc(rest[:-4].encode()) == int(rest[-4:], 16)))
    data_packets = [ok for s, ok in results if "#L#" not in s]
    assert data_packets and all(data_packets)
    # One real login packet carries a checksum that matches no CRC-16 variant over
    # any plausible scope: device firmware deviates, so login CRC errors are logged, not fatal.
    assert [ok for s, ok in results if "#L#" in s] == [False]

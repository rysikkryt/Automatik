"""Galileosky binary protocol (header 0x01, tag records, CRC-16/MODBUS).

Tag lengths and meanings follow the public Galileosky protocol description as
implemented by Traccar's GalileoProtocolDecoder. The CAN_B0/CAN_B1 layout is
hypothesis H-GS-1 (FMS mode: B0 = SPN 917 raw, B1 = SPN 247 raw) and must be
confirmed on a bench before production; see docs/design/DESIGN.md.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from ..crc import crc16_modbus

def _lengths() -> dict[int, int]:
    # Tag sizes as in the public protocol description (mirrors Traccar's table).
    table: dict[int, int] = {0x03: 15, 0x30: 9, 0x5C: 68, 0xFD: 8, 0x48: 2}
    groups = {
        1: [0x01, 0x02, 0x35, 0x43, 0xD5, *range(0xC4, 0xD3), *range(0x88, 0x8D), *range(0xA0, 0xB0)],
        2: [0x04, 0x10, 0x34, 0x40, 0x41, 0x42, 0x45, 0x46, *range(0x50, 0x5A), *range(0x60, 0x63),
            *range(0x70, 0x78), *range(0xB0, 0xBA), *range(0xD6, 0xDB)],
        3: [0x63, 0x64, 0x6F, 0x5D, *range(0x65, 0x6F), 0xFA, *range(0x80, 0x88)],
        4: [0x20, 0x33, 0x44, 0x90, 0xC0, 0xC1, 0xC2, 0xC3, 0xD3, 0xD4, *range(0xDB, 0xE0), 0xE0, 0xF0, 0xF9, 0x5A, 0x47,
            *range(0xF1, 0xF9), *range(0xE2, 0xEA)],
    }
    for size, tags in groups.items():
        for tag in tags:
            table[tag] = size
    return table


TAG_LENGTHS = _lengths()
VARIABLE_TAGS = {0xE1: 1, 0xEA: 1, 0xFE: 2}  # tag -> size of the length prefix
MAX_PACKET_BYTES = 1000


@dataclass
class GalileoRecord:
    index: int
    t: int
    lat: float
    lon: float
    valid: bool
    sats: int
    speed_kmh: float
    course: float
    alt_m: int
    hdop: float
    inputs: int
    power_mv: int
    gps_odometer_m: int
    rpm: float | None = None
    coolant_c: int | None = None
    fuel_level_pct: float | None = None
    fuel_total_raw: int | None = None  # SPN 250 raw, 0.5 L/bit
    can_b0_raw: int | None = None  # tag 0xC2 (FMS): vehicle distance, value*5 = m
    engine_hours_x100: int | None = None  # tag 0xDB (FMS): total engine hours, value/100 = h
    analog_mv: dict[int, int] | None = None  # tags 0x50..0x57: analog input voltage, mV
    extra_tags: dict[int, bytes] | None = None  # raw tags, e.g. user data 0xE2..0xE9 (4 bytes)


def frame(payload: bytes, archive: bool = False) -> bytes:
    if len(payload) > 0x7FFF:
        raise ValueError("payload too long")
    head = bytes([0x01]) + struct.pack("<H", len(payload) | (0x8000 if archive else 0))
    body = head + payload
    return body + struct.pack("<H", crc16_modbus(body))


def head_packet(imei: str, hw: int = 0x82, fw: int = 0x14, device_id: int = 1) -> bytes:
    if len(imei) != 15 or not imei.isdigit():
        raise ValueError("IMEI must be 15 digits")
    payload = bytes([0x01, hw, 0x02, fw, 0x03]) + imei.encode() + bytes([0x04]) + struct.pack("<H", device_id)
    return frame(payload)


def record_tags(r: GalileoRecord) -> bytes:
    out = bytearray()
    out += bytes([0x10]) + struct.pack("<H", r.index & 0xFFFF)
    out += bytes([0x20]) + struct.pack("<I", r.t)
    status = (0 if r.valid else 1) << 4 | min(r.sats, 15)
    out += bytes([0x30, status]) + struct.pack("<ii", round(r.lat * 1e6), round(r.lon * 1e6))
    out += bytes([0x33]) + struct.pack("<HH", round(r.speed_kmh * 10), round(r.course * 10) % 3600)
    out += bytes([0x34]) + struct.pack("<h", r.alt_m)
    out += bytes([0x35, min(255, round(r.hdop * 10))])
    out += bytes([0x41]) + struct.pack("<H", r.power_mv)
    out += bytes([0x46]) + struct.pack("<H", r.inputs)
    if r.fuel_total_raw is not None:
        out += bytes([0xC0]) + struct.pack("<I", r.fuel_total_raw)
    if r.rpm is not None:
        fuel = 0xFF if r.fuel_level_pct is None else round(r.fuel_level_pct / 0.4)
        coolant = 0xFF if r.coolant_c is None else r.coolant_c + 40
        out += bytes([0xC1, fuel, coolant]) + struct.pack("<H", round(r.rpm / 0.125))
    if r.can_b0_raw is not None:
        out += bytes([0xC2]) + struct.pack("<I", r.can_b0_raw)
    if r.engine_hours_x100 is not None:
        out += bytes([0xDB]) + struct.pack("<I", r.engine_hours_x100)
    out += bytes([0xD4]) + struct.pack("<I", r.gps_odometer_m)
    for tag, mv in sorted((r.analog_mv or {}).items()):
        out += bytes([tag]) + struct.pack("<H", mv)
    for tag, raw in sorted((r.extra_tags or {}).items()):
        out += bytes([tag]) + raw
    return bytes(out)


def records_packets(records: list[GalileoRecord], archive: bool) -> list[bytes]:
    """Split records into frames of at most MAX_PACKET_BYTES."""
    packets, chunk = [], bytearray()
    for r in records:
        tags = record_tags(r)
        if chunk and len(chunk) + len(tags) + 5 > MAX_PACKET_BYTES:
            packets.append(frame(bytes(chunk), archive))
            chunk = bytearray()
        chunk += tags
    if chunk:
        packets.append(frame(bytes(chunk), archive))
    return packets


def expected_ack(packet: bytes) -> bytes:
    return b"\x02" + packet[-2:]


def parse(packet: bytes) -> tuple[bool, list[dict[int, bytes]]]:
    """Reference decoder: (archive_flag, records as {tag: raw bytes}). Verifies CRC."""
    if packet[0] != 0x01:
        raise ValueError("not a Galileosky main packet")
    length_field = struct.unpack_from("<H", packet, 1)[0]
    length = length_field & 0x7FFF
    if len(packet) != length + 5:
        raise ValueError("length mismatch")
    if crc16_modbus(packet[:-2]) != struct.unpack_from("<H", packet, len(packet) - 2)[0]:
        raise ValueError("CRC mismatch")
    records: list[dict[int, bytes]] = []
    current: dict[int, bytes] = {}
    pos, end = 3, 3 + length
    while pos < end:
        tag = packet[pos]
        if tag in VARIABLE_TAGS:
            prefix = VARIABLE_TAGS[tag]
            size = prefix + int.from_bytes(packet[pos + 1 : pos + 1 + prefix], "little")
        elif tag in TAG_LENGTHS:
            size = TAG_LENGTHS[tag]
        else:
            raise ValueError(f"unknown tag 0x{tag:02x}")
        if tag in current:
            records.append(current)
            current = {}
        current[tag] = packet[pos + 1 : pos + 1 + size]
        pos += 1 + size
    if pos != end:
        raise ValueError("tag data overruns packet length")
    if current:
        records.append(current)
    return bool(length_field & 0x8000), records

"""Galileosky binary protocol ("Протокол обмена с сервером терминалов GALILEOSKY", НПО ГалилеоСкай)."""

from __future__ import annotations

import struct

from ..crc import crc16_modbus
from ..records import Mapping, apply_sensors, clean


def _lengths() -> dict[int, int]:
    table: dict[int, int] = {0x03: 15, 0x30: 9, 0x5C: 68, 0xFD: 8, 0x48: 2}
    groups = {
        1: [0x01, 0x02, 0x35, 0x43, 0xD5, *range(0xC4, 0xD3), *range(0x88, 0x8D), *range(0xA0, 0xB0)],
        2: [0x04, 0x10, 0x34, 0x40, 0x41, 0x42, 0x45, 0x46, *range(0x50, 0x5A), *range(0x60, 0x63),
            *range(0x70, 0x78), *range(0xB0, 0xBA), *range(0xD6, 0xDB)],
        3: [0x63, 0x64, 0x6F, 0x5D, *range(0x65, 0x6F), 0xFA, *range(0x80, 0x88)],
        4: [0x20, 0x33, 0x44, 0x90, 0xC0, 0xC1, 0xC2, 0xC3, 0xD3, 0xD4, *range(0xDB, 0xE0), 0xE0, 0xF0, 0xF9,
            0x5A, 0x47, *range(0xF1, 0xF9), *range(0xE2, 0xEA)],
    }
    for size, tags in groups.items():
        for tag in tags:
            table[tag] = size
    return table


TAG_LENGTHS = _lengths()
VARIABLE_TAGS = {0xE1: 1, 0xEA: 1, 0xFE: 2}
MAX_PACKET = 32767 + 5


class ProtocolError(Exception):
    pass


def parse_packet(packet: bytes) -> tuple[bool, list[dict[int, bytes]]]:
    length_field = struct.unpack_from("<H", packet, 1)[0]
    length = length_field & 0x7FFF
    if crc16_modbus(packet[:-2]) != struct.unpack_from("<H", packet, len(packet) - 2)[0]:
        raise ProtocolError("CRC mismatch")
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
            raise ProtocolError(f"unknown tag 0x{tag:02x}")
        # a repeated tag starts the next record
        if tag in current:
            records.append(current)
            current = {}
        current[tag] = packet[pos + 1 : pos + 1 + size]
        pos += 1 + size
    if pos != end:
        raise ProtocolError("tag data overruns packet length")
    if current:
        records.append(current)
    return bool(length_field & 0x8000), records


def record_to_ingest(tags: dict[int, bytes], mapping: Mapping) -> dict | None:
    if 0x20 not in tags:
        return None
    rec: dict = {"t": struct.unpack("<I", tags[0x20])[0]}
    if 0x30 in tags:
        b = tags[0x30]
        sats, validity = b[0] & 0x0F, b[0] >> 4
        lat, lon = struct.unpack_from("<ii", b, 1)
        # 0: GNSS fix, 2: cell-tower location (too coarse for mileage), other: invalid
        if validity == 0 and (lat or lon):
            rec.update(lat=lat / 1e6, lon=lon / 1e6, sats=sats)
            if 0x33 in tags:
                spd, crs = struct.unpack("<HH", tags[0x33])
                rec.update(speed_kmh=spd / 10, course=crs / 10)
            if 0x34 in tags:
                rec["alt"] = struct.unpack("<h", tags[0x34])[0]
            if 0x35 in tags:
                rec["hdop"] = tags[0x35][0] / 10
    if mapping.galileo_hours_tag is not None and mapping.galileo_hours_tag in tags:
        raw = struct.unpack("<I", tags[mapping.galileo_hours_tag])[0]
        if raw:
            rec.update(engine_hours=raw * mapping.galileo_hours_scale, engine_hours_method="ecu")
    if 0xC2 in tags and struct.unpack("<I", tags[0xC2])[0]:
        rec.update(odometer_km=struct.unpack("<I", tags[0xC2])[0] * 5 / 1000, odometer_method="ecu")
    elif 0xD4 in tags and struct.unpack("<I", tags[0xD4])[0]:
        rec.update(odometer_km=struct.unpack("<I", tags[0xD4])[0] / 1000, odometer_method="tracker")
    apply_sensors(mapping, rec, tags=tags)
    return clean(rec)


class GalileoskySession:
    proto = "galileosky"

    def __init__(self, mapping: Mapping | None = None):
        self.buf = b""
        self.ext_id: str | None = None
        self.mapping = mapping or Mapping()

    def feed(self, data: bytes) -> list[tuple[list[dict], bytes]]:
        """Returns [(records, ack)] per complete packet; the caller persists records, then sends ack."""
        self.buf += data
        out = []
        while len(self.buf) >= 3:
            if self.buf[0] != 0x01:
                raise ProtocolError(f"unsupported packet header 0x{self.buf[0]:02x}")
            total = (struct.unpack_from("<H", self.buf, 1)[0] & 0x7FFF) + 5
            if len(self.buf) < total:
                break
            packet, self.buf = self.buf[:total], self.buf[total:]
            _, recs = parse_packet(packet)
            records = []
            for tags in recs:
                if 0x03 in tags:
                    self.ext_id = tags[0x03].decode("ascii", "replace").strip("\x00 ")
                r = record_to_ingest(tags, self.mapping)
                if r and self.ext_id:
                    records.append(r)
            out.append((records, b"\x02" + packet[-2:]))
        return out

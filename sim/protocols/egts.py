"""EGTS (ГОСТ 33472-2015 / Приказ Минтранса № 285) transport + service layers.

Implements the subset needed for telematics: auth (TERM_IDENTITY) and teledata
(POS_DATA, EXT_POS_DATA, COUNTERS_DATA, ABS_CNTR_DATA), plus a reference decoder.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from ..crc import crc8_egts, crc16_ccitt

EPOCH_2010 = 1262304000
PT_RESPONSE, PT_APPDATA = 0, 1
SERVICE_AUTH, SERVICE_TELEDATA = 1, 2
SR_RECORD_RESPONSE, SR_TERM_IDENTITY, SR_RESULT_CODE = 0, 1, 9
SR_POS_DATA, SR_EXT_POS_DATA, SR_COUNTERS_DATA, SR_ABS_AN_SENS_DATA, SR_ABS_CNTR_DATA = 16, 17, 19, 24, 25


@dataclass
class EgtsPoint:
    t: int
    lat: float
    lon: float
    valid: bool
    speed_kmh: float
    course: float
    odometer_km: float
    inputs: int
    alt_m: int
    sats: int
    hdop: float
    moving: bool
    blackbox: bool
    counters: dict[int, int]  # ABS_CNTR number -> raw 24-bit value
    analog: dict[int, int] = field(default_factory=dict)  # ABS_AN_SENS number -> raw 24-bit value


def transport(sfrd: bytes, packet_id: int, packet_type: int = PT_APPDATA) -> bytes:
    header = struct.pack("<BBBBBHHB", 0x01, 0x00, 0x00, 11, 0x00, len(sfrd), packet_id & 0xFFFF, packet_type)
    header += bytes([crc8_egts(header)])
    return header + sfrd + (struct.pack("<H", crc16_ccitt(sfrd)) if sfrd else b"")


def record(record_number: int, service: int, subrecords: bytes, object_id: int | None = None) -> bytes:
    flags = 0x01 if object_id is not None else 0x00
    head = struct.pack("<HHB", len(subrecords), record_number & 0xFFFF, flags)
    if object_id is not None:
        head += struct.pack("<I", object_id)
    return head + bytes([service, service]) + subrecords


def subrecord(kind: int, data: bytes) -> bytes:
    return struct.pack("<BH", kind, len(data)) + data


def term_identity(terminal_id: int, imei: str) -> bytes:
    if len(imei) != 15:
        raise ValueError("IMEI must be 15 characters")
    return subrecord(SR_TERM_IDENTITY, struct.pack("<IB", terminal_id, 0x02) + imei.encode())


def pos_data(p: EgtsPoint) -> bytes:
    lat = round(abs(p.lat) / 90 * 0xFFFFFFFF)
    lon = round(abs(p.lon) / 180 * 0xFFFFFFFF)
    flags = (
        (1 if p.valid else 0) | 1 << 2 | (1 << 3 if p.blackbox else 0) | (1 << 4 if p.moving else 0)
        | (1 << 5 if p.lat < 0 else 0) | (1 << 6 if p.lon < 0 else 0) | 1 << 7
    )
    course = round(p.course) % 360
    speed = min(round(p.speed_kmh * 10), 0x3FFF) | (1 << 14 if p.alt_m < 0 else 0) | (1 << 15 if course > 255 else 0)
    odometer = round(p.odometer_km * 10) & 0xFFFFFF
    data = struct.pack("<IIIBHB", p.t - EPOCH_2010, lat, lon, flags, speed, course & 0xFF)
    data += odometer.to_bytes(3, "little") + bytes([p.inputs & 0xFF, 0]) + abs(p.alt_m).to_bytes(3, "little")
    return subrecord(SR_POS_DATA, data)


def ext_pos_data(p: EgtsPoint) -> bytes:
    return subrecord(SR_EXT_POS_DATA, struct.pack("<BHB", 0x02 | 0x08, round(p.hdop * 100), p.sats))


def abs_counters(counters: dict[int, int]) -> bytes:
    return b"".join(subrecord(SR_ABS_CNTR_DATA, bytes([n]) + (v & 0xFFFFFF).to_bytes(3, "little")) for n, v in counters.items())


def abs_analog(values: dict[int, int]) -> bytes:
    return b"".join(subrecord(SR_ABS_AN_SENS_DATA, bytes([n]) + (v & 0xFFFFFF).to_bytes(3, "little")) for n, v in values.items())


def teledata_records(points: list[EgtsPoint], first_record_number: int) -> bytes:
    return b"".join(
        record(first_record_number + i, SERVICE_TELEDATA, pos_data(p) + ext_pos_data(p) + abs_counters(p.counters) + abs_analog(p.analog))
        for i, p in enumerate(points)
    )


def split_frames(stream: bytes) -> tuple[list[bytes], bytes]:
    frames, pos = [], 0
    while len(stream) - pos >= 11:
        hl = stream[pos + 3]
        fdl = struct.unpack_from("<H", stream, pos + 5)[0]
        total = hl + fdl + (2 if fdl else 0)
        if len(stream) - pos < total:
            break
        frames.append(stream[pos : pos + total])
        pos += total
    return frames, stream[pos:]


def decode(packet: bytes) -> dict:
    """Reference decoder incl. counters (which Traccar 6.15 skips). Verifies both CRCs."""
    hl = packet[3]
    if crc8_egts(packet[: hl - 1]) != packet[hl - 1]:
        raise ValueError("header CRC mismatch")
    fdl = struct.unpack_from("<H", packet, 5)[0]
    packet_type = packet[hl - 2]
    sfrd = packet[hl : hl + fdl]
    if fdl and crc16_ccitt(sfrd) != struct.unpack_from("<H", packet, hl + fdl)[0]:
        raise ValueError("frame CRC mismatch")
    out = {"packet_id": struct.unpack_from("<H", packet, 7)[0], "type": packet_type, "records": []}
    pos = 0
    if packet_type == PT_RESPONSE:
        out["response_to"], out["result"] = struct.unpack_from("<HB", sfrd, 0)
        pos = 3
    while pos < len(sfrd):
        rl, rn, rfl = struct.unpack_from("<HHB", sfrd, pos)
        pos += 5
        for bit in (0, 1, 2):
            if rfl >> bit & 1:
                pos += 4
        sst = sfrd[pos]
        pos += 2
        end = pos + rl
        rec = {"number": rn, "service": sst, "subrecords": []}
        while pos < end:
            srt, srl = struct.unpack_from("<BH", sfrd, pos)
            pos += 3
            rec["subrecords"].append(_decode_sub(srt, sfrd[pos : pos + srl]))
            pos += srl
        out["records"].append(rec)
    return out


def _decode_sub(srt: int, d: bytes) -> dict:
    if srt == SR_POS_DATA:
        ntm, lat, lon, flg, spd, dirl = struct.unpack_from("<IIIBHB", d, 0)
        return {
            "type": "POS_DATA", "t": ntm + EPOCH_2010,
            "lat": lat * 90 / 0xFFFFFFFF * (-1 if flg >> 5 & 1 else 1),
            "lon": lon * 180 / 0xFFFFFFFF * (-1 if flg >> 6 & 1 else 1),
            "valid": bool(flg & 1), "blackbox": bool(flg >> 3 & 1),
            "speed_kmh": (spd & 0x3FFF) / 10, "course": dirl | (0x100 if spd >> 15 & 1 else 0),
            "odometer_km": int.from_bytes(d[16:19], "little") / 10,
        }
    if srt == SR_ABS_CNTR_DATA:
        return {"type": "ABS_CNTR_DATA", "number": d[0], "value": int.from_bytes(d[1:4], "little")}
    if srt == SR_COUNTERS_DATA:
        mask, values, pos = d[0], {}, 1
        for i in range(8):
            if mask >> i & 1:
                values[i + 1] = int.from_bytes(d[pos : pos + 3], "little")
                pos += 3
        return {"type": "COUNTERS_DATA", "values": values}
    if srt == SR_RECORD_RESPONSE:
        crn, rst = struct.unpack_from("<HB", d, 0)
        return {"type": "RECORD_RESPONSE", "record": crn, "status": rst}
    return {"type": srt, "raw": d.hex()}

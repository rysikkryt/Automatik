"""SAE J1939 codec for the parameters the platform relies on.

PGN/SPN numbers, byte positions and scaling follow SAE J1939-71 as reproduced in
public references (FMS-Standard, ISOBUS data dictionary, vendor manuals); see
docs/research/sources.md. Only the parameters needed for engine hours, distance,
position context and basic engine state are defined.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Status(str, Enum):
    OK = "ok"
    NOT_AVAILABLE = "not_available"
    ERROR = "error"
    RESERVED = "reserved"


# (max_valid, first_reserved, first_error, first_not_available) per J1939-71 ranges.
_RANGES = {
    1: (0xFA, 0xFB, 0xFE, 0xFF),
    2: (0xFAFF, 0xFB00, 0xFE00, 0xFF00),
    4: (0xFAFFFFFF, 0xFB000000, 0xFE000000, 0xFF000000),
}


@dataclass(frozen=True)
class SpnDef:
    spn: int
    name: str
    pgn: int
    start_byte: int  # 1-based, as printed in J1939-71 tables
    length: int  # bytes
    resolution: float
    offset: float
    unit: str


@dataclass(frozen=True)
class PgnDef:
    pgn: int
    acronym: str
    name: str
    priority: int
    rate: str
    spns: tuple[int, ...]


@dataclass(frozen=True)
class Reading:
    spn: int
    value: float | None
    status: Status
    raw: int


SPNS: dict[int, SpnDef] = {
    s.spn: s
    for s in (
        SpnDef(190, "Engine Speed", 61444, 4, 2, 0.125, 0.0, "rpm"),
        SpnDef(84, "Wheel-Based Vehicle Speed", 65265, 2, 2, 1 / 256, 0.0, "km/h"),
        SpnDef(247, "Engine Total Hours of Operation", 65253, 1, 4, 0.05, 0.0, "h"),
        SpnDef(249, "Engine Total Revolutions", 65253, 5, 4, 1000.0, 0.0, "r"),
        SpnDef(244, "Trip Distance", 65248, 1, 4, 0.125, 0.0, "km"),
        SpnDef(245, "Total Vehicle Distance", 65248, 5, 4, 0.125, 0.0, "km"),
        SpnDef(917, "High Resolution Total Vehicle Distance", 65217, 1, 4, 5.0, 0.0, "m"),
        SpnDef(918, "High Resolution Trip Distance", 65217, 5, 4, 5.0, 0.0, "m"),
        SpnDef(182, "Engine Trip Fuel", 65257, 1, 4, 0.5, 0.0, "L"),
        SpnDef(250, "Engine Total Fuel Used", 65257, 5, 4, 0.5, 0.0, "L"),
        SpnDef(183, "Engine Fuel Rate", 65266, 1, 2, 0.05, 0.0, "L/h"),
        SpnDef(96, "Fuel Level 1", 65276, 2, 1, 0.4, 0.0, "%"),
        SpnDef(110, "Engine Coolant Temperature", 65262, 1, 1, 1.0, -40.0, "degC"),
        SpnDef(100, "Engine Oil Pressure", 65263, 4, 1, 4.0, 0.0, "kPa"),
    )
}

PGNS: dict[int, PgnDef] = {
    p.pgn: p
    for p in (
        PgnDef(61444, "EEC1", "Electronic Engine Controller 1", 3, "engine-speed dependent (10-100 ms)", (190,)),
        PgnDef(65265, "CCVS", "Cruise Control/Vehicle Speed", 6, "100 ms", (84,)),
        PgnDef(65253, "HOURS", "Engine Hours, Revolutions", 6, "on request", (247, 249)),
        PgnDef(65248, "VD", "Vehicle Distance", 6, "100 ms", (244, 245)),
        PgnDef(65217, "VDHR", "High Resolution Vehicle Distance", 6, "1 s", (917, 918)),
        PgnDef(65257, "LFC", "Fuel Consumption (Liquid)", 6, "on request", (182, 250)),
        PgnDef(65266, "LFE", "Fuel Economy (Liquid)", 6, "100 ms", (183,)),
        PgnDef(65276, "DD", "Dash Display", 6, "1 s", (96,)),
        PgnDef(65262, "ET1", "Engine Temperature 1", 6, "1 s", (110,)),
        PgnDef(65263, "EFL/P1", "Engine Fluid Level/Pressure 1", 6, "500 ms", (100,)),
    )
}

PGN_REQUEST = 59904  # 0xEA00, PDU1: destination address goes into PS


def can_id(pgn: int, source_address: int, priority: int | None = None, destination: int = 0xFF) -> int:
    """29-bit identifier: priority(3) | EDP | DP | PF | PS | SA."""
    if priority is None:
        priority = PGNS[pgn].priority if pgn in PGNS else 6
    pf = (pgn >> 8) & 0xFF
    ps = destination if pf < 240 else pgn & 0xFF
    return (priority & 0x7) << 26 | ((pgn >> 16) & 0x3) << 24 | pf << 16 | ps << 8 | (source_address & 0xFF)


def parse_can_id(identifier: int) -> tuple[int, int, int, int]:
    """Return (priority, pgn, source_address, destination_address)."""
    priority = (identifier >> 26) & 0x7
    dp_edp = (identifier >> 24) & 0x3
    pf = (identifier >> 16) & 0xFF
    ps = (identifier >> 8) & 0xFF
    sa = identifier & 0xFF
    if pf < 240:
        return priority, dp_edp << 16 | pf << 8, sa, ps
    return priority, dp_edp << 16 | pf << 8 | ps, sa, 0xFF


def _classify(raw: int, length: int) -> Status:
    max_valid, reserved, error, not_available = _RANGES[length]
    if raw <= max_valid:
        return Status.OK
    if raw >= not_available:
        return Status.NOT_AVAILABLE
    if raw >= error:
        return Status.ERROR
    return Status.RESERVED


def encode(pgn: int, values: dict[int, float | Status | None]) -> bytes:
    """Build the 8 data bytes; parameters not given are sent as 'not available'."""
    data = bytearray(b"\xff" * 8)
    for spn, value in values.items():
        definition = SPNS[spn]
        if definition.pgn != pgn:
            raise ValueError(f"SPN {spn} belongs to PGN {definition.pgn}, not {pgn}")
        max_valid, _, error, not_available = _RANGES[definition.length]
        if value is None or value is Status.NOT_AVAILABLE:
            raw = (1 << (8 * definition.length)) - 1
        elif value is Status.ERROR:
            raw = error
        else:
            raw = round((float(value) - definition.offset) / definition.resolution)
            if not 0 <= raw <= max_valid:
                # A physical value outside the J1939 range must never wrap silently.
                raise ValueError(f"SPN {spn} value {value} outside transmittable range")
        start = definition.start_byte - 1
        data[start : start + definition.length] = raw.to_bytes(definition.length, "little")
    return bytes(data)


def decode(pgn: int, data: bytes) -> dict[int, Reading]:
    if len(data) < 8:
        raise ValueError("J1939 single-frame PGNs used here carry 8 data bytes")
    readings: dict[int, Reading] = {}
    for spn in PGNS[pgn].spns:
        definition = SPNS[spn]
        start = definition.start_byte - 1
        raw = int.from_bytes(data[start : start + definition.length], "little")
        status = _classify(raw, definition.length)
        value = raw * definition.resolution + definition.offset if status is Status.OK else None
        readings[spn] = Reading(spn, value, status, raw)
    return readings


def decode_frame(identifier: int, data: bytes) -> tuple[int, int, dict[int, Reading]] | None:
    """Decode a received frame; None for PGNs outside this parameter set."""
    _, pgn, sa, _ = parse_can_id(identifier)
    if pgn not in PGNS:
        return None
    return pgn, sa, decode(pgn, data)


def request_frame(requested_pgn: int, source_address: int, destination: int = 0xFF) -> tuple[int, bytes]:
    """Request PGN 59904. Sending it makes the reader an active bus participant."""
    identifier = can_id(PGN_REQUEST, source_address, priority=6, destination=destination)
    return identifier, requested_pgn.to_bytes(3, "little")

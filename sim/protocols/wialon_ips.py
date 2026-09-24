"""Wialon IPS 2.0 text protocol (TCP). CRC-16/ARC, 4 uppercase hex digits.

Format and checksum scope per the Gurtam specification (Wialon IPS v2.x PDF).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..crc import crc16_arc

MAX_BLACKBOX_MESSAGES = 5000


@dataclass
class WialonMessage:
    t: int
    lat: float
    lon: float
    speed_kmh: float
    course: float
    alt_m: int
    sats: int
    hdop: float
    inputs: int
    params: dict[str, int | float | str] = field(default_factory=dict)


def _coord(value: float, width: int) -> tuple[str, str]:
    deg = int(abs(value))
    minutes = (abs(value) - deg) * 60
    return f"{deg:0{width}d}{minutes:08.5f}", ""


def _param(name: str, value: int | float | str) -> str:
    if " " in name or "," in name or ":" in name:
        raise ValueError(f"invalid parameter name {name!r}")
    if isinstance(value, bool):
        return f"{name}:1:{int(value)}"
    if isinstance(value, int):
        return f"{name}:1:{value}"
    if isinstance(value, float):
        return f"{name}:2:" + f"{value:.6f}".rstrip("0").rstrip(".")
    return f"{name}:3:{value}"


def _body(m: WialonMessage) -> str:
    ts = time.gmtime(m.t)
    lat, _ = _coord(m.lat, 2)
    lon, _ = _coord(m.lon, 3)
    params = ",".join(_param(k, v) for k, v in m.params.items()) or "NA"
    return ";".join(
        [
            time.strftime("%d%m%y", ts), time.strftime("%H%M%S", ts),
            lat, "N" if m.lat >= 0 else "S", lon, "E" if m.lon >= 0 else "W",
            str(round(m.speed_kmh)), str(round(m.course) % 360), str(m.alt_m), str(m.sats),
            f"{m.hdop:.1f}", str(m.inputs), "0", "NA", "NA", params,
        ]
    )


def _packet(kind: str, body: str) -> bytes:
    return f"#{kind}#{body}{crc16_arc(body.encode()):04X}\r\n".encode()


def login(imei: str, password: str = "NA") -> bytes:
    return _packet("L", f"2.0;{imei};{password};")


def data(m: WialonMessage) -> bytes:
    return _packet("D", _body(m) + ";")


def blackbox(messages: list[WialonMessage]) -> bytes:
    if not 0 < len(messages) <= MAX_BLACKBOX_MESSAGES:
        raise ValueError("1..5000 messages per black box packet")
    return _packet("B", "".join(_body(m) + "|" for m in messages))


def verify(packet: bytes) -> bool:
    """Check the CRC of a device packet (used by tests and the ingest sidecar)."""
    text = packet.decode().rstrip("\r\n")
    kind_end = text.index("#", 1)
    body, crc = text[kind_end + 1 : -4], text[-4:]
    return crc16_arc(body.encode()) == int(crc, 16)

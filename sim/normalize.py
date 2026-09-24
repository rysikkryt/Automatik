"""Normalization of gateway output into the canonical telemetry record.

Mappings are data, one profile per protocol/device family; scale factors come
from device qualification (bench test), never from guesses in code paths.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

KNOT_KMH = 1.852

# attribute name -> (canonical field, multiplier)
PROFILES: dict[str, dict[str, tuple[str, float]]] = {
    "galileo": {
        "canB1": ("engine_hours", 0.05),  # legacy; official protocol: hours are in tag 0xDB, which Traccar does not decode
        "canB0": ("can_distance_km", 0.005),  # H-GS-1: SPN 917 raw, 5 m
        "odometer": ("gps_odometer_km", 0.001),
        "power": ("power_v", 1.0),
        "rpm": ("rpm", 1.0),
    },
    "wialon": {
        "eng_hours": ("engine_hours", 1.0),
        "can_dist_km": ("can_distance_km", 1.0),
        "gps_odom_km": ("gps_odometer_km", 1.0),
        "pwr_ext": ("power_v", 1.0),
        "rpm": ("rpm", 1.0),
    },
    # Traccar 6.15 decodes POS_DATA odometer but skips counter subrecords (engine hours).
    "egts": {"odometer": ("gps_odometer_km", 0.001)},
}


@dataclass
class Canonical:
    device_uid: str
    protocol: str
    fix_time: str
    server_time: str | None
    valid: bool
    lat: float
    lon: float
    speed_kmh: float
    course: float
    engine_hours: float | None = None
    engine_hours_source: str | None = None
    can_distance_km: float | None = None
    gps_odometer_km: float | None = None
    power_v: float | None = None
    rpm: float | None = None
    ignition: bool | None = None
    quality_flags: str = ""


def normalize(payload: dict) -> Canonical:
    position = payload["position"]
    device = payload.get("device") or {}
    protocol = position.get("protocol", "")
    attrs = position.get("attributes") or {}
    rec = Canonical(
        device_uid=str(device.get("uniqueId") or position.get("deviceId")),
        protocol=protocol,
        fix_time=position.get("fixTime"),
        server_time=position.get("serverTime"),
        valid=bool(position.get("valid")),
        lat=position.get("latitude"),
        lon=position.get("longitude"),
        speed_kmh=round((position.get("speed") or 0.0) * KNOT_KMH, 2),
        course=position.get("course") or 0.0,
    )
    for attr, (target, scale) in PROFILES.get(protocol, {}).items():
        if attr in attrs and isinstance(attrs[attr], (int, float)):
            setattr(rec, target, round(attrs[attr] * scale, 6))
    if protocol == "galileo" and "input" in attrs:
        rec.ignition = bool(int(attrs["input"]) & 1)
    elif protocol == "wialon" and "ign" in attrs:
        rec.ignition = bool(attrs["ign"])
    elif protocol == "egts" and "input" in attrs:
        rec.ignition = bool(int(attrs["input"]) & 1)
    if rec.engine_hours is not None:
        rec.engine_hours_source = str(attrs.get("eng_hours_src", "can"))
    return rec


def quality(prev: Canonical | None, cur: Canonical, dt_s: float) -> list[str]:
    """Plausibility checks between consecutive records of one device."""
    flags = []
    if not cur.valid:
        flags.append("no_fix")
    if prev and prev.engine_hours is not None and cur.engine_hours is not None:
        delta = cur.engine_hours - prev.engine_hours
        if delta < -0.05:
            flags.append("hours_decrease")  # ECU swap, reset or wrong mapping
        elif dt_s >= 0 and delta > dt_s / 3600 + 0.1:
            flags.append("hours_faster_than_clock")
    return flags


def as_row(rec: Canonical) -> dict:
    return asdict(rec)

"""Local geodesy helpers (small-area ENU <-> WGS-84)."""

from __future__ import annotations

import math

EARTH_RADIUS_M = 6_371_008.8


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def enu_to_latlon(lat0: float, lon0: float, east_m: float, north_m: float) -> tuple[float, float]:
    lat = lat0 + math.degrees(north_m / EARTH_RADIUS_M)
    lon = lon0 + math.degrees(east_m / (EARTH_RADIUS_M * math.cos(math.radians(lat0))))
    return lat, lon


def bearing_deg(east_m: float, north_m: float) -> float:
    return (math.degrees(math.atan2(east_m, north_m)) + 360.0) % 360.0

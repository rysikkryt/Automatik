"""GNSS receiver error model.

Horizontal error is a first-order Gauss-Markov process per axis, plus fix
outages and multipath jumps. Parameters are modelling assumptions per
environment (documented in docs/simulation-report.md), not measurements.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass


@dataclass(frozen=True)
class GnssEnvironment:
    key: str
    title_ru: str
    sigma_m: float
    tau_s: float
    outage_rate_per_h: float
    mean_outage_s: float
    multipath_rate_per_h: float
    multipath_m: float
    mean_multipath_s: float
    sats_mean: float
    hdop_mean: float


ENVIRONMENTS: dict[str, GnssEnvironment] = {
    e.key: e
    for e in (
        GnssEnvironment("open_sky", "Открытое небо (поле, дорога)", 1.5, 60, 0.5, 5, 0.5, 6, 10, 15, 0.8),
        GnssEnvironment("forest_canopy", "Под пологом леса", 4.0, 30, 6.0, 25, 8.0, 20, 20, 9, 1.8),
        GnssEnvironment("open_pit", "Карьер (затенение бортами)", 2.5, 45, 2.0, 15, 3.0, 12, 15, 10, 1.4),
    )
}


@dataclass
class GnssFix:
    valid: bool
    east: float
    north: float
    speed_kmh: float
    course: float
    sats: int
    hdop: float


class GnssReceiver:
    def __init__(self, environment: str, rng: random.Random):
        self.environment = environment
        self.rng = rng
        env = ENVIRONMENTS[environment]
        self.err_e = rng.gauss(0, env.sigma_m)
        self.err_n = rng.gauss(0, env.sigma_m)
        self.outage_left = 0.0
        self.multipath_left = 0.0
        self.mp_e = self.mp_n = 0.0
        self.last_course = 0.0

    def step(self, east: float, north: float, vel_e: float, vel_n: float, environment: str | None = None) -> GnssFix:
        env = ENVIRONMENTS[environment or self.environment]
        rng = self.rng
        phi = math.exp(-1.0 / env.tau_s)
        q = env.sigma_m * math.sqrt(1 - phi * phi)
        self.err_e = phi * self.err_e + rng.gauss(0, q)
        self.err_n = phi * self.err_n + rng.gauss(0, q)

        if self.outage_left > 0:
            self.outage_left -= 1
            return GnssFix(False, east, north, 0.0, self.last_course, rng.randint(0, 3), 99.0)
        if rng.random() < env.outage_rate_per_h / 3600:
            self.outage_left = rng.expovariate(1 / env.mean_outage_s)
            return GnssFix(False, east, north, 0.0, self.last_course, rng.randint(0, 3), 99.0)

        if self.multipath_left > 0:
            self.multipath_left -= 1
        elif rng.random() < env.multipath_rate_per_h / 3600:
            self.multipath_left = rng.expovariate(1 / env.mean_multipath_s)
            angle = rng.uniform(0, 2 * math.pi)
            size = abs(rng.gauss(env.multipath_m, env.multipath_m / 3))
            self.mp_e, self.mp_n = size * math.cos(angle), size * math.sin(angle)
        mp_e, mp_n = (self.mp_e, self.mp_n) if self.multipath_left > 0 else (0.0, 0.0)

        # Doppler velocity noise: a parked receiver still reports a small non-zero speed.
        ve = vel_e + rng.gauss(0, 0.12)
        vn = vel_n + rng.gauss(0, 0.12)
        speed = math.hypot(ve, vn) * 3.6
        if speed > 1.0:
            self.last_course = (math.degrees(math.atan2(ve, vn)) + 360) % 360
        sats = max(4, round(rng.gauss(env.sats_mean, 1.5)))
        hdop = max(0.5, rng.gauss(env.hdop_mean, 0.25) + (1.5 if self.multipath_left > 0 else 0.0))
        return GnssFix(True, east + self.err_e + mp_e, north + self.err_n + mp_n, speed, self.last_course, sats, round(hdop, 1))

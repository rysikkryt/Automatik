"""Machine models: shift schedule, engine/electrical state, motion and CAN output.

A profile describes a class of machine, not one OEM model. Every numeric
behaviour here is a stated modelling assumption (see docs/simulation-report.md).
"""

from __future__ import annotations

import math
import random
from collections import deque
from dataclasses import dataclass

from . import j1939


@dataclass(frozen=True)
class MachineProfile:
    key: str
    title_ru: str
    sphere: str
    examples: str
    ecu_j1939: bool
    hours_broadcast: bool
    can_odometer: bool
    voltage: int
    shifts: tuple[tuple[float, float], ...]  # local hours, end may exceed 24
    work_days: tuple[int, ...]  # 0 = Monday
    pattern: str
    environment: str
    coverage: str
    rpm_idle: float
    rpm_work: float
    fuel_idle_lph: float
    fuel_work_lph: float
    swing_radius_m: float  # GNSS antenna offset from the swing axis (rotating cab)
    site_ru: str
    site: tuple[float, float]
    utc_offset_h: int = 3
    running_v_mean: float | None = None  # None: healthy regulator (13.95 V per 12 V)
    running_v_sigma: float = 0.15
    odometer_scale_error: float = 0.0  # wheel-based odometer bias (tyre size/wear)
    initial_engine_h: float = 3000.0


PROFILES: dict[str, MachineProfile] = {
    p.key: p
    for p in (
        MachineProfile(
            "tractor_can", "Трактор с электронным двигателем (J1939)", "поле",
            "Кировец К-7М, RSM 2375, МТЗ-3522", True, True, False, 24,
            ((6.0, 21.0),), (0, 1, 2, 3, 4, 5), "field", "open_sky", "rural",
            850, 1750, 4.0, 32.0, 0.0, "Ростовская обл. (условно)", (47.35, 40.10)),
        MachineProfile(
            "tractor_mech", "Трактор с механическим ТНВД (без CAN)", "поле",
            "МТЗ-82.1 (Д-243), ДТ-75, Т-150К", False, False, False, 12,
            ((7.0, 19.0),), (0, 1, 2, 3, 4, 5), "field", "open_sky", "rural",
            800, 1900, 2.5, 11.0, 0.0, "Краснодарский край (условно)", (45.30, 39.60),
            running_v_mean=13.45, running_v_sigma=0.22, initial_engine_h=11850.0),
        MachineProfile(
            "harvester", "Харвестер", "лес",
            "Амкодор 2551, Ponsse Ergo, John Deere 1270", True, False, False, 24,
            ((7.0, 17.0), (17.5, 27.0)), (0, 1, 2, 3, 4, 5), "harvester", "forest_canopy", "forest",
            900, 1600, 5.0, 17.0, 1.2, "Карелия (условно)", (63.75, 34.30)),
        MachineProfile(
            "forwarder", "Форвардер", "лес",
            "Амкодор 2661, Ponsse Buffalo, John Deere 1110", True, True, False, 24,
            ((7.0, 17.0), (17.5, 27.0)), (0, 1, 2, 3, 4, 5), "forwarder", "forest_canopy", "forest",
            900, 1500, 4.5, 12.0, 0.0, "Карелия (условно)", (63.77, 34.35)),
        MachineProfile(
            "excavator", "Экскаватор 20-50 т", "карьер",
            "SANY SY215C/SY500H, XCMG XE215, ЕК-270", True, True, False, 24,
            ((8.0, 20.0), (20.5, 31.5)), (0, 1, 2, 3, 4, 5, 6), "excavator", "open_pit", "quarry",
            950, 1800, 6.0, 24.0, 1.8, "Белгородская обл. (условно)", (51.28, 37.55)),
        MachineProfile(
            "dump_truck", "Карьерный самосвал", "карьер",
            "БелАЗ-7547/7555, XCMG XDE, SANY SKT", True, True, True, 24,
            ((8.0, 20.0), (20.5, 31.5)), (0, 1, 2, 3, 4, 5, 6), "haul", "open_pit", "quarry",
            750, 1700, 8.0, 65.0, 0.0, "Белгородская обл. (условно)", (51.29, 37.57),
            odometer_scale_error=0.02),
        MachineProfile(
            "timber_truck", "Лесовоз с манипулятором", "лес/дорога",
            "КАМАЗ-43118/65222, Урал NEXT, Sitrak C7H", True, True, True, 24,
            ((5.0, 19.0),), (0, 1, 2, 3, 4, 5), "road_trip", "open_sky", "road",
            650, 1500, 3.0, 30.0, 0.0, "Архангельская обл. (условно)", (61.25, 46.65),
            odometer_scale_error=0.015),
    )
}


@dataclass
class Interval:
    start: int
    end: int
    ignition: bool
    engine: bool
    working: bool


def build_day(profile: MachineProfile, local_midnight_utc: int, rng: random.Random) -> list[Interval]:
    weekday = (local_midnight_utc + profile.utc_offset_h * 3600) // 86400
    weekday = (weekday + 3) % 7  # 1970-01-01 was a Thursday
    if weekday not in profile.work_days:
        return []
    out: list[Interval] = []
    for start_h, end_h in profile.shifts:
        s = local_midnight_utc + int(start_h * 3600 + rng.gauss(0, 600))
        e = local_midnight_utc + int(end_h * 3600 + rng.gauss(0, 600))
        pre, post = rng.randint(60, 300), rng.randint(0, 600)
        # Ignition without engine: glow plugs, ECU wake-up, radio/lights after stop.
        out.append(Interval(s - pre, s, True, False, False))
        mid = s + (e - s) // 2
        brk = rng.randint(1800, 3600)
        kind = rng.choices(("idle", "ign_only", "off"), (0.3, 0.3, 0.4))[0]
        carve = [(mid, mid + brk, kind != "off", kind == "idle")]
        for _ in range(2):
            a = rng.randint(s + 1800, e - 3000)
            d = rng.randint(300, 1200)
            if all(a + d + 600 < c0 or a > c1 + 600 for c0, c1, _, _ in carve):
                carve.append((a, a + d, rng.random() < 0.5, False))
        carve.sort()
        cursor = s
        for a, b, ign, eng in carve:
            if a > cursor:
                out.append(Interval(cursor, a, True, True, True))
            out.append(Interval(a, b, ign, eng, False))
            cursor = b
        if cursor < e:
            out.append(Interval(cursor, e, True, True, True))
        out.append(Interval(e, e + post, True, False, False))
    return out


def build_schedule(profile: MachineProfile, start_utc: int, days: int, rng: random.Random) -> list[Interval]:
    first_day = (start_utc + profile.utc_offset_h * 3600) // 86400 - 1
    raw: list[Interval] = []
    for day in range(first_day, first_day + days + 3):
        raw.extend(build_day(profile, day * 86400 - profile.utc_offset_h * 3600, rng))
    raw.sort(key=lambda i: i.start)
    cleaned: list[Interval] = []
    for item in raw:
        if cleaned and item.start < cleaned[-1].end:
            item.start = cleaned[-1].end
        if item.end > item.start:
            cleaned.append(item)
    return cleaned


class Mover:
    """Queue of legs ("go") and dwells; advances only while the machine works."""

    def __init__(self, x: float = 0.0, y: float = 0.0):
        self.x, self.y = x, y
        self.queue: deque = deque()
        self.dwell_left = 0.0
        self.current = None

    def idle(self) -> bool:
        return self.current is None and not self.queue

    def step(self, dt: float) -> tuple[float, float, float, bool, str | None]:
        """Return (vel_e, vel_n, load, swinging, environment_hint)."""
        if self.current is None:
            if not self.queue:
                return 0.0, 0.0, 0.3, False, None
            self.current = self.queue.popleft()
            if self.current[0] == "dwell":
                self.dwell_left = self.current[1]
        item = self.current
        if item[0] == "dwell":
            _, _, load, swing, env = item
            self.dwell_left -= dt
            if self.dwell_left <= 0:
                self.current = None
            return 0.0, 0.0, load, swing, env
        _, tx, ty, speed, load, env = item
        dx, dy = tx - self.x, ty - self.y
        dist = math.hypot(dx, dy)
        if dist <= speed * dt:
            self.x, self.y = tx, ty
            self.current = None
            return dx / dt, dy / dt, load, False, env
        ve, vn = dx / dist * speed, dy / dist * speed
        self.x += ve * dt
        self.y += vn * dt
        return ve, vn, load, False, env


def _kmh(v: float) -> float:
    return v / 3.6


def refill_pattern(pattern: str, mover: Mover, rng: random.Random, state: dict) -> None:
    q = mover.queue
    if pattern == "field":
        # Boustrophedon passes over an 800 x 1200 m field, 12 m swath, headland turns.
        lane = state.setdefault("lane", 0)
        x = (lane % 66) * 12.0
        up = lane % 2 == 0
        q.append(("go", x, 1200.0 if up else 0.0, _kmh(rng.uniform(9, 11.5)), 0.8, None))
        q.append(("go", ((lane + 1) % 66) * 12.0, 1200.0 if up else 0.0, _kmh(5), 0.4, None))
        state["lane"] = lane + 1
    elif pattern == "harvester":
        # Fell and process at a spot (cab swings), then creep along the strip road.
        pos = state.setdefault("pos", 0.0)
        strip = state.setdefault("strip", 0)
        q.append(("dwell", rng.uniform(60, 180), 0.85, True, None))
        pos += rng.uniform(8, 15)
        if pos > 300:
            strip += 1
            pos = 0.0
            q.append(("go", 1500 + strip * 20.0, mover.y, _kmh(2.5), 0.5, None))
        y = 1500 + (pos if strip % 2 == 0 else 300 - pos)
        q.append(("go", 1500 + strip * 20.0, y, _kmh(2.0), 0.6, None))
        state.update(pos=pos, strip=strip)
    elif pattern == "forwarder":
        stand_x, stand_y = 600 + rng.uniform(-80, 80), 450 + rng.uniform(-80, 80)
        q.append(("go", stand_x, stand_y, _kmh(6.5), 0.5, None))
        for _ in range(8):
            q.append(("dwell", rng.uniform(150, 240), 0.7, False, None))
            q.append(("go", stand_x + rng.uniform(-10, 10), stand_y + rng.uniform(-40, 40), _kmh(2.5), 0.6, None))
        q.append(("go", 0.0, 0.0, _kmh(5.0), 0.8, None))
        q.append(("dwell", rng.uniform(720, 1080), 0.6, False, None))
    elif pattern == "excavator":
        for _ in range(rng.randint(60, 110)):
            q.append(("dwell", rng.uniform(18, 26), 0.85, True, None))
        q.append(("go", mover.x + rng.uniform(2, 5), mover.y + rng.uniform(-1, 1), _kmh(2.0), 0.5, None))
    elif pattern == "haul":
        q.append(("dwell", rng.uniform(180, 300), 0.35, False, None))
        for wx, wy in ((400, 150), (1500, 900), (3100, 1400), (3500, 1600)):
            q.append(("go", wx, wy, _kmh(rng.uniform(20, 24)), 0.95, None))
        q.append(("dwell", rng.uniform(60, 110), 0.5, False, None))
        for wx, wy in ((3100, 1400), (1500, 900), (400, 150), (0, 0)):
            q.append(("go", wx, wy, _kmh(rng.uniform(30, 34)), 0.45, None))
        q.append(("dwell", rng.uniform(0, 300), 0.2, False, None))
    elif pattern == "road_trip":
        q.append(("go", 30000, 12000, _kmh(62), 0.6, "open_sky"))
        q.append(("go", 48000, 16000, _kmh(58), 0.6, "open_sky"))
        q.append(("go", 60000, 20000, _kmh(24), 0.7, "forest_canopy"))
        q.append(("dwell", rng.uniform(2400, 3600), 0.5, False, "forest_canopy"))  # loading with own crane
        q.append(("go", 48000, 16000, _kmh(20), 0.9, "forest_canopy"))
        q.append(("go", 30000, 12000, _kmh(55), 0.9, "open_sky"))
        q.append(("go", 0, 0, _kmh(55), 0.9, "open_sky"))
        q.append(("dwell", rng.uniform(1200, 2000), 0.2, False, "open_sky"))
    else:
        raise ValueError(pattern)


START_POS = {
    "field": (0.0, 0.0), "harvester": (1500.0, 1500.0), "forwarder": (0.0, 0.0),
    "excavator": (0.0, 0.0), "haul": (0.0, 0.0), "road_trip": (0.0, 0.0),
}


@dataclass
class MachineState:
    t: int
    ignition: bool
    engine: bool
    working: bool
    rpm: float
    speed_kmh: float
    base_e: float
    base_n: float
    ant_e: float
    ant_n: float
    vel_e: float
    vel_n: float
    voltage: float
    d_plus: bool
    coolant_c: float
    engine_s_total: float
    path_m_total: float
    can_distance_m: float
    fuel_used_l: float
    fuel_level_pct: float
    environment: str


class Machine:
    def __init__(self, profile: MachineProfile, seed: int, start_utc: int, days: int):
        self.profile = profile
        self.rng = random.Random(seed)
        self.schedule = build_schedule(profile, start_utc, days, self.rng)
        self.cursor = 0
        self.mover = Mover(*START_POS[profile.pattern])
        self.pattern_state: dict = {}
        self.engine_s = profile.initial_engine_h * 3600
        self.path_m = 0.0
        self.can_distance_m = 250_000.0 if profile.can_odometer else 0.0
        self.fuel_used = profile.initial_engine_h * profile.fuel_work_lph * 0.6
        self.fuel_level = 80.0
        self.coolant = 10.0
        self.crank_left = 0
        self.prev_engine = False
        self.swing_phase = 0.0
        self.env_hint = profile.environment

    def _interval(self, t: int) -> Interval | None:
        sched = self.schedule
        while self.cursor < len(sched) and sched[self.cursor].end <= t:
            self.cursor += 1
        if self.cursor < len(sched) and sched[self.cursor].start <= t:
            return sched[self.cursor]
        return None

    def step(self, t: int) -> MachineState:
        p, rng = self.profile, self.rng
        iv = self._interval(t)
        ignition = bool(iv and iv.ignition)
        engine = bool(iv and iv.engine)
        working = bool(iv and iv.working)
        if engine and not self.prev_engine:
            self.crank_left = 3
        self.prev_engine = engine

        ve = vn = 0.0
        load = 0.0
        swinging = False
        if engine and working:
            if self.mover.idle():
                refill_pattern(p.pattern, self.mover, rng, self.pattern_state)
            ve, vn, load, swinging, env = self.mover.step(1.0)
            if env:
                self.env_hint = env
        speed_mps = math.hypot(ve, vn)
        self.path_m += speed_mps
        if p.can_odometer:
            self.can_distance_m += speed_mps * (1 + p.odometer_scale_error)

        if swinging and p.swing_radius_m > 0:
            self.swing_phase += 2 * math.pi / 20.0
        angle = math.radians(90) * (1 - math.cos(self.swing_phase)) / 2
        ant_e = self.mover.x + p.swing_radius_m * math.sin(angle)
        ant_n = self.mover.y + p.swing_radius_m * math.cos(angle)

        if engine:
            self.engine_s += 1
            rpm = p.rpm_idle + (p.rpm_work - p.rpm_idle) * load + rng.gauss(0, 15)
            fuel_rate = p.fuel_idle_lph + (p.fuel_work_lph - p.fuel_idle_lph) * load
            self.fuel_used += fuel_rate / 3600
            self.fuel_level = max(5.0, self.fuel_level - fuel_rate / 3600 / 4.0)
            self.coolant += (88 - self.coolant) / 600
        else:
            rpm = 0.0
            self.coolant += (10 - self.coolant) / 3600
        if self.fuel_level < 15:
            self.fuel_level = 95.0  # refuelling

        k = p.voltage / 12.0
        if self.crank_left > 0:
            self.crank_left -= 1
            voltage, d_plus = 9.8 * k + rng.gauss(0, 0.3), False
        elif engine:
            mean = p.running_v_mean if p.running_v_mean else 13.95 * k
            voltage, d_plus = rng.gauss(mean, p.running_v_sigma), True
        elif ignition:
            voltage, d_plus = rng.gauss(12.35 * k, 0.08), False
        else:
            voltage, d_plus = rng.gauss(12.65 * k, 0.05), False

        return MachineState(
            t, ignition, engine, working, rpm, speed_mps * 3.6, self.mover.x, self.mover.y, ant_e, ant_n,
            ve, vn, voltage, d_plus, self.coolant, self.engine_s, self.path_m, self.can_distance_m,
            self.fuel_used, self.fuel_level, self.env_hint)

    def can_frames(self, s: MachineState) -> list[tuple[int, bytes]]:
        """Frames the ECU (SA 0x00) and cluster (SA 0x17) broadcast in this state."""
        if not self.profile.ecu_j1939 or not s.ignition:
            return []
        frames = [
            (j1939.can_id(61444, 0x00), j1939.encode(61444, {190: round(s.rpm / 0.125) * 0.125})),
            (j1939.can_id(65265, 0x00), j1939.encode(65265, {84: min(s.speed_kmh, 250.0)})),
            (j1939.can_id(65262, 0x00), j1939.encode(65262, {110: round(s.coolant_c)})),
            (j1939.can_id(65276, 0x17), j1939.encode(65276, {96: round(s.fuel_level_pct / 0.4) * 0.4})),
            (j1939.can_id(65257, 0x00), j1939.encode(65257, {182: None, 250: math.floor(s.fuel_used_l / 0.5) * 0.5})),
        ]
        if self.profile.can_odometer:
            frames.append((j1939.can_id(65217, 0x17), j1939.encode(65217, {917: math.floor(s.can_distance_m / 5) * 5, 918: None})))
        if self.profile.hours_broadcast:
            frames.append(self.hours_frame(s))
        return frames

    def hours_frame(self, s: MachineState) -> tuple[int, bytes]:
        hours = math.floor(s.engine_s_total / 3600 / 0.05) * 0.05
        return j1939.can_id(65253, 0x00), j1939.encode(65253, {247: hours, 249: None})

    def respond(self, identifier: int, data: bytes, s: MachineState) -> list[tuple[int, bytes]]:
        """ECU reaction to a Request PGN (59904) addressed to it or globally."""
        _, pgn, _, dest = j1939.parse_can_id(identifier)
        if pgn != j1939.PGN_REQUEST or not self.profile.ecu_j1939 or not s.ignition or dest not in (0x00, 0xFF):
            return []
        if int.from_bytes(data[:3], "little") == 65253:
            return [self.hours_frame(s)]
        return []

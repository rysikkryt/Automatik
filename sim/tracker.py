"""Tracker firmware emulator: CAN reader, counters, record policy, black box, uplink."""

from __future__ import annotations

import math
import random
from collections import deque
from dataclasses import dataclass, field

from . import j1939
from .coverage import Coverage
from .geo import enu_to_latlon, haversine_m
from .gnss import GnssFix, GnssReceiver
from .machine import Machine, MachineState

HOURS_METHODS = ("can", "ignition", "voltage", "d_plus")


@dataclass
class TrackerConfig:
    period_moving_s: int = 30
    period_parked_s: int = 300
    angle_deg: float = 15.0
    distance_m: float = 300.0
    min_speed_kmh: float = 3.0
    max_hdop: float = 3.0
    min_sats: int = 5
    archive_capacity: int = 170_000  # Galileosky 10 Plus flash archive (records)
    send_period_s: int = 60
    max_records_per_session: int = 2000
    can_sample_s: int = 5
    can_request_hours: bool = True  # active J1939 request if HOURS is not broadcast
    request_period_s: int = 60
    voltage_threshold_per_12v: float = 13.2
    debounce_s: int = 5
    source_address: int = 0xF9


@dataclass
class Record:
    index: int
    t: int
    lat: float
    lon: float
    valid: bool
    sats: int
    hdop: float
    speed_kmh: float
    course: float
    alt_m: int
    ignition: bool
    power_v: float
    hours: dict[str, float | None]
    can_hours_raw: int | None
    can_distance_raw: int | None
    gps_odometer_m: float
    gps_odometer_naive_m: float
    rpm: float | None
    coolant_c: int | None
    fuel_level_pct: float | None
    fuel_total_raw: int | None
    truth_engine_h: float
    truth_path_m: float
    reason: str
    delivered_t: int | None = None


@dataclass
class TrackerStats:
    records: int = 0
    lost_overflow: int = 0
    sessions: int = 0
    can_frames_decoded: int = 0
    can_requests_sent: int = 0
    online_s: int = 0
    max_archive: int = 0


class Tracker:
    def __init__(self, machine: Machine, config: TrackerConfig, seed: int):
        self.m = machine
        self.cfg = config
        rng = random.Random(seed)
        self.gnss = GnssReceiver(machine.profile.environment, rng)
        self.coverage = Coverage(machine.profile.coverage, rng)
        self.archive: deque[Record] = deque()
        self.delivered: list[Record] = []
        self.stats = TrackerStats()
        self.index = 0
        self.can: dict[int, j1939.Reading] = {}
        dash = round(machine.profile.initial_engine_h, 1)  # hour meter read at installation
        self.counters_s = {m: dash * 3600 for m in ("ignition", "voltage", "d_plus")}
        self.voltage_state = False
        self.voltage_run = 0
        self.gps_odo = 0.0
        self.gps_odo_naive = 0.0
        self.prev_fix: GnssFix | None = None
        self.prev_accepted: GnssFix | None = None
        self.last_record: Record | None = None
        self.last_record_fix: GnssFix | None = None
        self.prev_ignition = False
        self.prev_engine = False
        self.last_send = -10**9
        self.was_online = False

    def _read_can(self, s: MachineState) -> None:
        if not self.m.profile.ecu_j1939:
            return  # no bus to listen to or to poll
        frames = self.m.can_frames(s)
        if self.cfg.can_request_hours and not self.m.profile.hours_broadcast and s.t % self.cfg.request_period_s == 0:
            identifier, data = j1939.request_frame(65253, self.cfg.source_address, destination=0x00)
            self.stats.can_requests_sent += 1
            frames += self.m.respond(identifier, data, s)
        for identifier, data in frames:
            decoded = j1939.decode_frame(identifier, data)
            if decoded:
                self.stats.can_frames_decoded += 1
                self.can.update(decoded[2])
        if not s.ignition:
            self.can.clear()  # an unpowered bus reports nothing; do not freeze stale values

    def _count_hours(self, s: MachineState) -> None:
        if s.ignition:
            self.counters_s["ignition"] += 1
        if s.d_plus:
            self.counters_s["d_plus"] += 1
        above = s.voltage > self.cfg.voltage_threshold_per_12v * self.m.profile.voltage / 12
        self.voltage_run = self.voltage_run + 1 if above != self.voltage_state else 0
        if self.voltage_run >= self.cfg.debounce_s:
            self.voltage_state, self.voltage_run = above, 0
        if self.voltage_state:
            self.counters_s["voltage"] += 1

    def _odometer(self, fix: GnssFix, s: MachineState, lat: float, lon: float) -> None:
        if fix.valid and self.prev_fix is not None and self.prev_fix.valid:
            self.gps_odo_naive += math.hypot(fix.east - self.prev_fix.east, fix.north - self.prev_fix.north)
        self.prev_fix = fix
        accept = fix.valid and s.ignition and fix.speed_kmh >= self.cfg.min_speed_kmh and fix.hdop <= self.cfg.max_hdop and fix.sats >= self.cfg.min_sats
        if not accept:
            if not s.ignition:
                self.prev_accepted = None
            return
        if self.prev_accepted is not None:
            step = math.hypot(fix.east - self.prev_accepted.east, fix.north - self.prev_accepted.north)
            if step <= 60:  # implied speed cap (216 km/h over 1 s) rejects jumps
                self.gps_odo += step
        self.prev_accepted = fix

    def _hours_snapshot(self) -> dict[str, float | None]:
        reading = self.can.get(247)
        can_value = reading.value if reading and reading.status is j1939.Status.OK else None
        out: dict[str, float | None] = {"can": can_value}
        for method in ("ignition", "voltage", "d_plus"):
            out[method] = self.counters_s[method] / 3600
        return out

    def _should_record(self, s: MachineState, fix: GnssFix) -> str | None:
        if s.ignition != self.prev_ignition:
            return "ignition"
        if s.engine != self.prev_engine:
            return "engine"
        if self.last_record is None:
            return "first"
        dt = s.t - self.last_record.t
        moving = fix.valid and fix.speed_kmh >= self.cfg.min_speed_kmh and s.ignition
        if not moving:
            return "parked" if dt >= self.cfg.period_parked_s else None
        if dt >= self.cfg.period_moving_s:
            return "period"
        ref = self.last_record_fix
        if ref is not None and ref.valid:
            if math.hypot(fix.east - ref.east, fix.north - ref.north) >= self.cfg.distance_m:
                return "distance"
            turn = abs((fix.course - ref.course + 180) % 360 - 180)
            if fix.speed_kmh > 5 and turn >= self.cfg.angle_deg:
                return "angle"
        return None

    def step(self, s: MachineState) -> None:
        p = self.m.profile
        if s.t % self.cfg.can_sample_s == 0 or not s.ignition:
            self._read_can(s)
        self._count_hours(s)
        fix = self.gnss.step(s.ant_e, s.ant_n, s.vel_e, s.vel_n, s.environment)
        lat, lon = enu_to_latlon(p.site[0], p.site[1], fix.east, fix.north)
        self._odometer(fix, s, lat, lon)

        reason = self._should_record(s, fix)
        if reason:
            hours_reading = self.can.get(247)
            dist_reading = self.can.get(917)
            rpm = self.can.get(190)
            coolant = self.can.get(110)
            fuel = self.can.get(96)
            fuel_total = self.can.get(250)
            ok = j1939.Status.OK
            rec = Record(
                self.index, s.t, lat, lon, fix.valid, fix.sats, fix.hdop,
                round(fix.speed_kmh, 1) if fix.valid else 0.0, fix.course, 120,
                s.ignition, round(s.voltage, 2), self._hours_snapshot(),
                hours_reading.raw if hours_reading and hours_reading.status is ok else None,
                dist_reading.raw if dist_reading and dist_reading.status is ok else None,
                self.gps_odo, self.gps_odo_naive,
                rpm.value if rpm and rpm.status is ok else None,
                int(coolant.value) if coolant and coolant.status is ok else None,
                fuel.value if fuel and fuel.status is ok else None,
                fuel_total.raw if fuel_total and fuel_total.status is ok else None,
                s.engine_s_total / 3600, s.path_m_total, reason)
            self.index += 1
            self.stats.records += 1
            if len(self.archive) >= self.cfg.archive_capacity:
                self.archive.popleft()
                self.stats.lost_overflow += 1
            self.archive.append(rec)
            self.stats.max_archive = max(self.stats.max_archive, len(self.archive))
            self.last_record, self.last_record_fix = rec, fix
        self.prev_ignition, self.prev_engine = s.ignition, s.engine

        online = self.coverage.online(s.base_e, s.base_n)
        if online:
            self.stats.online_s += 1
        if online and self.archive and s.t - self.last_send >= self.cfg.send_period_s:
            if not self.was_online or s.t - self.last_send > 600:
                self.stats.sessions += 1
            for _ in range(min(len(self.archive), self.cfg.max_records_per_session)):
                rec = self.archive.popleft()
                rec.delivered_t = s.t
                self.delivered.append(rec)
            self.last_send = s.t
        self.was_online = online


@dataclass
class RunResult:
    tracker: Tracker
    machine: Machine
    start: int
    end: int
    final_state: MachineState | None = None
    records: list[Record] = field(default_factory=list)


def run(profile_key: str, start_utc: int, days: int, seed: int = 1, config: TrackerConfig | None = None) -> RunResult:
    from .machine import PROFILES

    machine = Machine(PROFILES[profile_key], seed, start_utc, days)
    tracker = Tracker(machine, config or TrackerConfig(), seed + 1000)
    end = start_utc + days * 86400
    state = None
    for t in range(start_utc, end):
        state = machine.step(t)
        tracker.step(state)
    result = RunResult(tracker, machine, start_utc, end, state)
    result.records = list(tracker.delivered) + list(tracker.archive)
    return result


def track_length_m(records: list[Record]) -> float:
    """What a platform computes from stored track points (no filtering)."""
    pts = [r for r in sorted(records, key=lambda r: r.t) if r.valid]
    return sum(haversine_m(a.lat, a.lon, b.lat, b.lon) for a, b in zip(pts, pts[1:]))

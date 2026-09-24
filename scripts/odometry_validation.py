#!/usr/bin/env python3
"""Validation of the production odometry (platform/server/domain/odometry.ts).

1. Machine classes × tracker settings: simulated machines (sim/) → tracker model → sparse track.
2. Stationary machine: 72 h parked, GNSS error as first-order Gauss-Markov (open sky / canopy /
   dense canopy), with and without Doppler speed noise → false kilometres must stay ~0.
3. Excavator swinging on the spot (antenna 2.5 m from the swing axis) → no mileage.
4. Tracked machine carried on a lowboy at 60 km/h → transport, not mileage.
Writes docs/evidence/odometry-validation.json.
"""

from __future__ import annotations

import json
import math
import pathlib
import random
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sim.tracker import TrackerConfig, run  # noqa: E402

PROF = {
    "harvester": {"chassis": "wheeled", "rotatingUpper": False, "category": "harvester"},
    "forwarder": {"chassis": "wheeled", "rotatingUpper": False, "category": "forwarder"},
    "excavator": {"chassis": "tracked", "rotatingUpper": True, "category": "excavator"},
    "tractor_can": {"chassis": "wheeled", "rotatingUpper": False, "category": "tractor"},
    "tractor_mech": {"chassis": "wheeled", "rotatingUpper": False, "category": "tractor"},
    "dump_truck": {"chassis": "wheeled", "rotatingUpper": False, "category": "dump_truck"},
    "timber_truck": {"chassis": "wheeled", "rotatingUpper": False, "category": "timber_truck"},
}
CFGS = {
    "default": TrackerConfig(),
    "recommended": TrackerConfig(min_speed_kmh=0.5, period_moving_s=30, distance_m=25, period_parked_s=300),
}


def run_ts(jobs: list[dict]) -> list[dict]:
    p = subprocess.run(["npx", "tsx", "scripts/odometry-cli.ts"], cwd=ROOT / "platform", input=json.dumps(jobs),
                       capture_output=True, text=True, check=True)
    return json.loads(p.stdout)


def gm_track(hours: float, dt: float, sigma: float, tau: float, hdop: float, speed_noise: float | None, seed: int,
             lat0=61.7849, lon0=34.3469, swing_r: float = 0.0) -> list[dict]:
    """Parked receiver: correlated position error (Gauss-Markov), optional antenna swing arcs."""
    rng = random.Random(seed)
    a = math.exp(-dt / tau)
    q = sigma * math.sqrt(1 - a * a)
    e = n = 0.0
    out = []
    t0 = int(time.time() * 1000) - int(hours * 3600e3)
    ang = 0.0
    for i in range(int(hours * 3600 / dt)):
        e = a * e + rng.gauss(0, q)
        n = a * n + rng.gauss(0, q)
        sx = sy = 0.0
        spd = abs(rng.gauss(0, speed_noise)) if speed_noise is not None else None
        if swing_r:
            ang += rng.uniform(-1, 1) * math.pi / 2  # digging cycle: swing up to ±90° between fixes
            sx, sy = swing_r * math.cos(ang), swing_r * math.sin(ang)
            if spd is not None:
                spd += abs(rng.gauss(0, 4.0))  # antenna moves with the cab
        lat = lat0 + (n + sy) / 111195
        lon = lon0 + (e + sx) / (111195 * math.cos(math.radians(lat0)))
        fix = {"t": t0 + int(i * dt * 1000), "lat": lat, "lon": lon, "hdop": hdop, "sats": 9}
        if spd is not None:
            fix["speedKmh"] = spd
        out.append(fix)
    return out


def lowboy_track(seed: int) -> tuple[list[dict], float]:
    rng = random.Random(seed)
    t0 = int(time.time() * 1000) - 4 * 3600e3
    out, lat, lon, d = [], 61.0, 34.0, 0.0
    for i in range(0, 3600 * 2, 30):  # 2 h on the trailer at ~60 km/h, fixes every 30 s
        v = 60 + rng.gauss(0, 5)
        step = v / 3.6 * 30
        d += step
        lat += step / 111195
        out.append({"t": t0 + i * 1000, "lat": lat + rng.gauss(0, 3) / 111195, "lon": lon, "speedKmh": v, "hdop": 0.9, "sats": 12})
    return out, d / 1000


def build_jobs() -> tuple[list[dict], list[dict]]:
    now = int(time.time())
    start = (now - 4 * 86400) // 86400 * 86400 - 3 * 3600
    jobs, meta = [], []
    for key, prof in PROF.items():
        for cname, cfg in CFGS.items():
            res = run(key, start, 3, seed=7, config=cfg)
            recs = sorted(res.records, key=lambda r: r.t)
            fixes = [{"t": r.t * 1000, "lat": r.lat, "lon": r.lon, "speedKmh": r.speed_kmh, "hdop": r.hdop, "sats": r.sats}
                     for r in recs if r.valid]
            truth = (recs[-1].truth_path_m - recs[0].truth_path_m) / 1000
            tracker_odo = (recs[-1].gps_odometer_m - recs[0].gps_odometer_m) / 1000
            jobs.append({"profile": prof, "fixes": fixes})
            meta.append({"test": "class", "machine": key, "tracker": cname, "fixes": len(fixes), "truth_km": truth,
                         "tracker_gps_odometer_km": tracker_odo})
    for env, sigma, tau, hdop in (("open_sky", 2.5, 60, 0.8), ("canopy", 6.0, 120, 1.8), ("dense_canopy", 10.0, 180, 3.0)):
        for with_speed in (True, False):
            for dt in (1, 30, 300):
                fx = gm_track(72 if dt > 1 else 12, dt, sigma, tau, hdop, 0.4 if with_speed else None, seed=dt)
                jobs.append({"profile": PROF["harvester"], "fixes": fx})
                meta.append({"test": "stationary", "env": env, "speed": with_speed, "dt_s": dt, "hours": 72 if dt > 1 else 12,
                             "truth_km": 0.0})
    for dt in (1, 30):
        fx = gm_track(12, dt, 2.5, 60, 0.8, 0.4, seed=99, swing_r=2.5)
        jobs.append({"profile": PROF["excavator"], "fixes": fx})
        meta.append({"test": "swing_only", "dt_s": dt, "hours": 12, "truth_km": 0.0})
    fx, dist = lowboy_track(5)
    jobs.append({"profile": PROF["excavator"], "fixes": fx})
    meta.append({"test": "lowboy_transport", "truth_km": 0.0, "carried_km": dist})
    return jobs, meta


def main(override: dict | None = None, cache: str | None = None, write: bool = True) -> list[dict]:
    if cache and pathlib.Path(cache).exists():
        jobs, meta = json.loads(pathlib.Path(cache).read_text())
    else:
        jobs, meta = build_jobs()
        if cache:
            pathlib.Path(cache).write_text(json.dumps([jobs, meta]))
    if override:
        jobs = [{**j, "override": override} for j in jobs]
    out = run_ts(jobs)
    rows = []
    for m, o in zip(meta, out):
        row = {**m, "robust_km": round(o["km"], 3), "transport_km": round(o["transportKm"], 3), "naive_km": round(o["naiveKm"], 3)}
        if m["truth_km"] > 0:
            row["robust_err_pct"] = round((o["km"] - m["truth_km"]) / m["truth_km"] * 100, 2)
            row["naive_err_pct"] = round((o["naiveKm"] - m["truth_km"]) / m["truth_km"] * 100, 1)
        rows.append(row)
    if not write:
        return rows
    path = ROOT / "docs" / "evidence" / "odometry-validation.json"
    path.write_text(json.dumps({"generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "rows": rows},
                               ensure_ascii=False, indent=1))
    for r in rows:
        if r["test"] == "class":
            print(f"class {r['machine']:13} {r['tracker']:11} n={r['fixes']:6d} truth={r['truth_km']:9.3f} "
                  f"robust={r['robust_km']:9.3f} ({r['robust_err_pct']:+.1f}%) naive={r['naive_km']:9.3f} ({r['naive_err_pct']:+.0f}%)")
        elif r["test"] == "stationary":
            print(f"parked {r['env']:12} speed={str(r['speed']):5} dt={r['dt_s']:3d}s {r['hours']}h: robust={r['robust_km']:.3f} km naive={r['naive_km']:.1f} km")
        else:
            print(r)
    return rows


if __name__ == "__main__":
    main()

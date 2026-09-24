#!/usr/bin/env python3
"""Fills a running platform with a clearly labelled demo fleet from the simulator.

Data travels the production path: simulated trackers → real protocols over TCP → gateway → HTTPS
API. Every machine is named "(симулятор)" and the organisations "(демо)" so nothing can be mistaken
for a real machine. Oil values come from a simple deterministic model (below), not from sensors.

  ITLES_BASE=https://itles.vercel.app ITLES_ENV=platform/.data/vercel-secrets.env \
  ITLES_LOGINS=platform/.data/prod-logins.json python scripts/seed_preview.py
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import pathlib
import secrets
import sys
import threading
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "gateway"), str(ROOT / "scripts")]

from gateway_e2e import api, free_port  # noqa: E402
from itles_gateway.forwarder import Forwarder  # noqa: E402
from itles_gateway.queue import DurableQueue  # noqa: E402
from itles_gateway.records import Mapping  # noqa: E402
from itles_gateway.server import Gateway  # noqa: E402
from sim import uplink  # noqa: E402
from sim.tracker import run  # noqa: E402


def _noise(t: int, seed: int) -> float:
    return math.sin(t * 0.0137 + seed) * 0.6 + math.sin(t * 0.00071 + 2 * seed) * 0.6


def oil_model(r, seed: int, *, k=0.3, start=85.0, offset=21.0, aw0=0.18, aw_rate=0.002) -> dict:
    """Demo only: sawtooth level (consumption k pp per engine hour, top-up to `start` at 60 %)."""
    h = r.truth_engine_h
    running = bool(r.ignition) and (r.rpm is None or r.rpm > 400)
    level = start - ((k * h + offset) % (start - 60.0)) + _noise(r.t, seed)
    return {
        "level": max(0.0, min(100.0, level)),
        "temp": (88.0 + 3.0 * math.sin(r.t / 900.0)) if running else 18.0 + _noise(r.t, seed),
        "press": (260.0 + 0.09 * max(0.0, (r.rpm or 1200) - 800)) if running else 0.0,
        "aw": min(0.95, aw0 + aw_rate * (h % 100) + 0.01 * _noise(r.t, seed)),
        "hyd": (64.0 + 14.0 * abs(math.sin(r.t / 1800.0))) if running else 20.0,
    }


def wialon_oil(seed, **kw):
    def f(r):
        o = oil_model(r, seed, **kw)
        # as a CAN-enabled tracker forwards J1939: SPN 98 raw 0.4 %/bit, SPN 100 raw 4 kPa/bit
        return {"oil_lvl_raw": round(o["level"] / 0.4), "oil_p_raw": round(o["press"] / 4), "oil_t": round(o["temp"], 1), "oil_aw": round(o["aw"], 3)}
    return f


def egts_oil(seed, **kw):
    def f(r):
        o = oil_model(r, seed, **kw)
        return {1: round(o["hyd"] * 10), 2: round(o["level"] * 10)}  # ABS_AN_SENS_DATA inputs 1 and 2
    return f


def galileo_oil(seed, **kw):
    def f(r):
        o = oil_model(r, seed, **kw)
        return {0x50: round(500 + o["level"] * 88)}  # resistive sender on analog input 0: 500..9300 mV
    return f


WIALON_OIL_MAP = {"oil_level_pct": {"param": "oil_lvl_raw", "scale": 0.4}, "oil_pressure_kpa": {"param": "oil_p_raw", "scale": 4},
                  "oil_temp_c": {"param": "oil_t"}, "oil_water_aw": {"param": "oil_aw"}}

FLEET = [
    ("harvester", "galileosky", "356307042441013", {"name": "Харвестер John Deere 1270G (симулятор)", "category": "harvester", "make": "John Deere", "model": "1270G"}, "can",
     Mapping(sensors={"oil_level_pct": {"tag": 0x50, "table": [[500, 0], [9300, 100]]}}), galileo_oil(1)),
    ("forwarder", "galileosky", "356307042441014", {"name": "Форвардер Ponsse Buffalo (симулятор)", "category": "forwarder", "make": "Ponsse", "model": "Buffalo"}, "can", Mapping(), None),
    ("excavator", "egts", "868204005185938", {"name": "Экскаватор SANY SY500H (симулятор)", "category": "excavator", "chassis": "tracked", "rotating_upper": True, "make": "SANY", "model": "SY500H"}, "voltage",
     Mapping(egts_hours_counter=1, egts_hours_scale=0.1, sensors={"hyd_temp_c": {"egts_an": 1, "scale": 0.1}, "oil_level_pct": {"egts_an": 2, "scale": 0.1}}), egts_oil(3, k=0.45)),
    ("timber_truck", "wialon_ips", "861230043345678", {"name": "Лесовоз КАМАЗ-43118 (симулятор)", "category": "timber_truck", "make": "КАМАЗ", "model": "43118"}, "can",
     Mapping(param_hours={"eng_hours": "ecu"}, param_mileage={"can_dist_km": "ecu"}, sensors=WIALON_OIL_MAP), wialon_oil(4)),
    ("tractor_can", "wialon_ips", "861230043345679", {"name": "Трактор Кировец К-7М (симулятор)", "category": "tractor", "make": "Кировец", "model": "К-7М"}, "can",
     Mapping(param_hours={"eng_hours": "ecu"}, param_mileage={"can_dist_km": "ecu"}, sensors=WIALON_OIL_MAP), wialon_oil(5, aw0=0.52, offset=4.0)),
]


def load_env(path: pathlib.Path) -> dict:
    out = {}
    for line in path.read_text().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip("'\"")
    return out


def main() -> None:
    base = os.environ.get("ITLES_BASE", "http://127.0.0.1:3000")
    env = load_env(pathlib.Path(os.environ.get("ITLES_ENV", ROOT / "platform/.data/preview.env")))
    creds_file = pathlib.Path(os.environ.get("ITLES_LOGINS", ROOT / "platform/.data/preview-logins.json"))
    creds = json.loads(creds_file.read_text()) if creds_file.exists() else {}
    _, st = api(base, "GET", "/api/setup/status")
    if st["needs_setup"]:
        creds = {"fuchs-admin": secrets.token_urlsafe(9)}
        api(base, "POST", "/api/setup", {"setup_key": env["SETUP_KEY"], "org_name": "FUCHS", "login": "fuchs-admin", "password": creds["fuchs-admin"]})
    _, r = api(base, "POST", "/api/auth/login", {"login": "fuchs-admin", "password": creds["fuchs-admin"]})
    admin = r["token"]
    orgs = api(base, "GET", "/api/orgs", token=admin)[1]["orgs"]
    cust = next((o for o in orgs if o["kind"] == "customer" and "(демо)" in o["name"]), None)
    if not cust:
        _, d = api(base, "POST", "/api/orgs", {"kind": "distributor", "name": "Дистрибьютор Северо-Запад (демо)"}, admin)
        _, c = api(base, "POST", "/api/orgs", {"kind": "customer", "name": "Леспромхоз «Тайга» (демо)", "parent_id": d["org"]["id"]}, admin)
        cust = c["org"]
        for org_id, login in ((d["org"]["id"], "demo-dist"), (cust["id"], "demo-klient")):
            _, inv = api(base, "POST", f"/api/orgs/{org_id}/invites", {"role": "admin"}, admin)
            pw = secrets.token_urlsafe(9).replace("_", "x").replace("-", "y")
            st_, _ = api(base, "POST", "/api/auth/redeem", {"code": inv["code"], "login": login, "password": pw})
            if st_ == 201:
                creds[login] = pw
        creds_file.write_text(json.dumps(creds))

    existing = {m["name"]: m["id"] for m in api(base, "GET", "/api/machines", token=admin)[1]["machines"]}
    todo = [f for f in FLEET if f[3]["name"] not in existing]
    ids = {}
    for prof, proto, imei, body, hours, mapping, oil in todo:
        _, m = api(base, "POST", "/api/machines", {**body, "org_id": cust["id"]}, admin)
        ids[imei] = m["machine"]["id"]
        api(base, "POST", f"/api/machines/{ids[imei]}/sources", {"kind": "tracker", "external_id": imei}, admin)

    q = DurableQueue(":memory:")
    gw = Gateway(q, {f[2]: f[5] for f in FLEET})
    ports = {p: free_port() for p in ("galileosky", "egts", "wialon_ips")}
    loop = asyncio.new_event_loop()
    ready = threading.Event()

    def serve():
        asyncio.set_event_loop(loop)
        loop.run_until_complete(gw.serve(ports, "127.0.0.1"))
        ready.set()
        loop.run_forever()

    threading.Thread(target=serve, daemon=True).start()
    ready.wait(10)
    threading.Thread(target=Forwarder(q, base, env["GATEWAY_TOKEN"], batch=1500, timeout=60).loop, kwargs={"idle": 0.2}, daemon=True).start()
    now = int(time.time())
    start = now - 3 * 86400 - 1800
    for prof, proto, imei, body, hours, mapping, oil in todo:
        recs = [r for r in sorted(run(prof, start, 3, seed=11).records, key=lambda r: r.t) if r.t < now]
        if proto == "galileosky":
            uplink.send_galileosky("127.0.0.1", ports[proto], imei, recs, extra=oil)
        elif proto == "egts":
            uplink.send_egts("127.0.0.1", ports[proto], imei, recs, hours, extra=oil)
        else:
            uplink.send_wialon("127.0.0.1", ports[proto], imei, recs, hours, extra=oil)
        print(body["name"], len(recs), "records sent")
    deadline = time.time() + 600
    while q.size() and time.time() < deadline:
        time.sleep(0.5)
    print("queue left:", q.size())
    for imei, mid in ids.items():
        api(base, "POST", f"/api/machines/{mid}/service", {"item": "Моторное масло", "interval_h": 500, "last_done_h": 2700, "volume_l": 32, "product": "FUCHS TITAN CARGO MAXX 10W-40"}, admin)
        api(base, "POST", f"/api/machines/{mid}/service", {"item": "Гидравлическое масло", "interval_h": 2000, "last_done_h": 1500, "volume_l": 180, "product": "FUCHS RENOLIN B 46 HVI"}, admin)
    print("logins:", ", ".join(creds))


if __name__ == "__main__":
    main()

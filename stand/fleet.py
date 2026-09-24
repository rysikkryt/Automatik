"""Stand fleet from the platform's demo tenant and the simext companies
(platform/server/demo-fleet.json, platform/server/simext/companies.json)."""

from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
FLEET_FILE = ROOT / "platform" / "server" / "demo-fleet.json"
COMPANIES_FILE = ROOT / "platform" / "server" / "simext" / "companies.json"


def load() -> dict:
    fleet = json.loads(FLEET_FILE.read_text(encoding="utf-8"))
    fleet["companies"] = json.loads(COMPANIES_FILE.read_text(encoding="utf-8"))["companies"]
    return fleet


def company_path(c: dict, u: dict) -> str:
    """Delivery path of a company unit: the platform it reports to decides."""
    if c["platform"] in ("traccar", "wialon", "aemp"):
        return c["platform"]
    return u.get("path", "gateway")


def company_units(companies: list[dict]) -> list[dict]:
    """Units of the simext companies; they are not registered in ITles — the owner connects them himself."""
    out = []
    for c in companies:
        for u in c.get("units", []):
            out.append({
                "imei": u["uid"], "model": u["tracker_model"], "protocol": u["protocol"], "path": company_path(c, u),
                "can": u["can"], "fuel_sensor": u["fuel_sensor"], "vehicle": u["name"], "machine_id": None,
                "profile": u["profile"], "region": u["region"], "field": u["field"], "tank_l": u["tank_l"],
                "width_m": u.get("work_width_m"), "chassis": u["chassis"], "free": True,
                "company": c["name"], "company_id": c["id"], "platform": c["platform"], "platform_label": c["platform_label"],
            })
    return out


def units(fleet: dict) -> list[dict]:
    """Every emulated tracker: the demo machines, free trackers and the simext company units."""
    out = []
    for m in fleet["machines"]:
        t = m["tracker"]
        out.append({
            "imei": t["imei"], "model": t["model"], "protocol": t["protocol"], "path": t["path"], "can": t["can"],
            "fuel_sensor": t["fuel_sensor"], "vehicle": m["name"], "machine_id": m["id"], "profile": m["profile"],
            "region": m["region"], "field": m["field"], "tank_l": m["tank_l"], "width_m": m["work_width_m"],
            "chassis": m["chassis"], "free": False,
        })
    for f in fleet["free_trackers"]:
        out.append({
            "imei": f["imei"], "model": f["model"], "protocol": f["protocol"], "path": f["path"], "can": f["can"],
            "fuel_sensor": f["fuel_sensor"], "vehicle": f["vehicle"], "machine_id": None, "profile": f["profile"],
            "region": f["region"], "field": f["field"], "tank_l": f["tank_l"], "width_m": None, "chassis": "wheeled", "free": True,
        })
    out.extend(company_units(fleet.get("companies", [])))
    return out


def gateway_mapping(u: dict) -> dict:
    """How the gateway turns this tracker's protocol fields into platform sensors (what an integrator
    configures per unit in a monitoring platform)."""
    tank = u["tank_l"] or 500
    has_dut = "RS-485" in (u["fuel_sensor"] or "")
    p = u["protocol"]
    if p == "galileosky":
        s = {
            "rpm": {"tag": 0xC1, "byte_offset": 2, "bytes": 2, "scale": 0.125},
            "coolant_temp_c": {"tag": 0xC1, "byte_offset": 1, "bytes": 1, "offset": -40},
            "fuel_used_l": {"tag": 0xC0, "scale": 0.5},
            "engine_load_pct": {"tag": 0xA0},
            "oil_pressure_kpa": {"tag": 0xB0},
            "battery_v": {"tag": 0x41, "scale": 0.001},
            "implement_on": {"tag": 0x46, "bit": 1},
        }
        if has_dut:
            # RS-485 level sensor, raw 0..4095 over the tank height; the calibration table converts to litres
            s["fuel_level_l"] = {"tag": 0x60, "table": [[0, 0], [4095, tank]]}
        else:
            s["fuel_level_pct"] = {"tag": 0xC1, "byte_offset": 0, "bytes": 1, "scale": 0.4}
        return {"sensors": s}
    if p in ("egts", "egts_retranslator"):
        s = {"fuel_level_l": {"egts_lls": 1}, "rpm": {"egts_an": 2}, "coolant_temp_c": {"egts_an": 3, "offset": -40}}
        return {"egts_hours_counter": 1, "egts_hours_scale": 0.1, "sensors": s}
    if p in ("wialon_ips", "wialon_retranslator"):
        return {
            "param_hours": {"eng_hours": "ecu"},
            "param_mileage": {"can_dist_km": "ecu"},
            "sensors": {
                "rpm": {"param": "rpm"}, "coolant_temp_c": {"param": "coolant"}, "fuel_level_pct": {"param": "fuel_pct"},
                "fuel_rate_lph": {"param": "fuel_rate"}, "oil_pressure_kpa": {"param": "oil_p"}, "engine_load_pct": {"param": "load"},
                "battery_v": {"param": "pwr"}, "implement_on": {"param": "implement"},
            },
        }
    return {}

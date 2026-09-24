"""End-to-end run: simulated machines -> protocol-exact TCP -> Traccar -> JSON forward -> normalization.

Requires a running Traccar configured with infra/traccar/traccar.xml.
Writes evidence to docs/evidence/traccar-e2e.json.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import pathlib
import sqlite3
import sys
import threading
import time
import urllib.request
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from sim import uplink  # noqa: E402
from sim.ingest_server import Store, make_server  # noqa: E402
from sim.machine import PROFILES  # noqa: E402
from sim.protocols import egts  # noqa: E402
from sim.tracker import run  # noqa: E402

# Test IMEIs (not real devices).
PLAN = [
    ("tractor_can", "galileosky", "can", "860000000000011"),
    ("harvester", "galileosky", "can", "860000000000029"),
    ("forwarder", "galileosky", "can", "860000000000037"),
    ("excavator", "wialon", "can", "860000000000045"),
    ("tractor_mech", "wialon", "voltage", "860000000000052"),
    ("timber_truck", "wialon", "can", "860000000000060"),
    ("dump_truck", "egts", "can", "860000000000078"),
]
PORTS = {"galileosky": 5034, "wialon": 5039, "egts": 5165}


def epoch(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


class TraccarApi:
    def __init__(self, base: str, user: str, password: str):
        self.base = base
        self.auth = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()

    def get(self, path: str):
        req = urllib.request.Request(self.base + path, headers={"Authorization": self.auth, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.load(resp)

    def positions(self, start: int, end: int) -> dict[str, tuple[dict, list[dict]]]:
        """Positions persisted by the gateway per IMEI: independent source for reconciliation."""
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        window = f"from={time.strftime(fmt, time.gmtime(start - 86400))}&to={time.strftime(fmt, time.gmtime(end + 86400))}"
        # Traccar 6 lists all devices to an administrator only with all=true.
        return {d["uniqueId"]: (d, self.get(f"/api/positions?deviceId={d['id']}&{window}")) for d in self.get("/api/devices?all=true")}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--days", type=int, default=2)
    parser.add_argument("--start", type=int, default=1789430400, help="UTC epoch, default 2026-09-15")
    parser.add_argument("--db", default=".local/e2e.sqlite3")
    parser.add_argument("--out", default="docs/evidence/traccar-e2e.json")
    parser.add_argument("--api", default="http://127.0.0.1:8082")
    args = parser.parse_args()
    user = os.environ.get("TRACCAR_USER", "")
    password = os.environ.get("TRACCAR_PASSWORD", "")

    db_path = pathlib.Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)
    store = Store(str(db_path))
    server = make_server(store, 9100)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    sent: dict[str, dict] = {}
    for profile, protocol, hours_method, imei in PLAN:
        result = run(profile, args.start, args.days, seed=11)
        records = sorted(result.records, key=lambda r: r.index)
        for r in records:
            if r.delivered_t is None:
                r.delivered_t = result.end  # uploaded when the machine next reaches coverage
        started = time.time()
        if protocol == "galileosky":
            stats = uplink.send_galileosky(args.host, PORTS[protocol], imei, records)
        elif protocol == "wialon":
            stats = uplink.send_wialon(args.host, PORTS[protocol], imei, records, hours_method)
        else:
            stats = uplink.send_egts(args.host, PORTS[protocol], imei, records, hours_method)
        stats["seconds"] = round(time.time() - started, 2)
        sent[imei] = {"profile": profile, "protocol": protocol, "hours_method": hours_method,
                      "records": records, "stats": stats}
        print(f"sent {profile:13s} via {protocol:10s}: {len(records):5d} records, "
              f"{stats['packets']} packets, {stats['bytes']} bytes", flush=True)

    end = args.start + args.days * 86400
    api = TraccarApi(args.api, user, password) if user else None
    gateway = api.positions(args.start, end) if api else {}
    stored = {imei: len(items[1]) for imei, items in gateway.items()}
    target = sum(stored.get(imei, 0) for imei in sent) if stored else None
    deadline = time.time() + 300
    idle_since, last = time.time(), -1
    while time.time() < deadline:
        if store.received != last:
            last, idle_since = store.received, time.time()
        done = store.written >= target if target is not None else False
        if (done or time.time() - idle_since > 20) and store.queue.empty() and time.time() - idle_since > 3:
            break
        time.sleep(0.5)
    forwarded_written = store.written
    with sqlite3.connect(db_path) as peek:
        forwarded_per_device = dict(peek.execute("SELECT device_uid, COUNT(*) FROM telemetry GROUP BY device_uid"))
    # Reconciliation: re-read what the gateway persisted and insert anything forwarding lost.
    # Duplicates are ignored by the (device_uid, fix_time) key.
    backfilled_before = store.duplicates
    for imei, (device, positions) in gateway.items():
        for p in positions:
            store.add({"position": p, "device": device})
    while not store.queue.empty():
        time.sleep(0.2)
    time.sleep(1.0)
    server.shutdown()
    store.recompute_quality()

    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    total_rows = db.execute("SELECT COUNT(*) FROM telemetry").fetchone()[0]
    report = {"traccar_version_checked": "6.15.3", "forwarded_written": forwarded_written,
              "rows_after_reconciliation": total_rows,
              "reconciliation_duplicates_ignored": store.duplicates - backfilled_before,
              "devices": []}
    ok_all = True
    for imei, item in sent.items():
        all_rows = list(db.execute("SELECT * FROM telemetry WHERE device_uid = ?", (imei,)))
        rows = {epoch(r["fix_time"]): r for r in all_rows}
        records = item["records"]
        # The EGTS decoder keeps valid fixes only; two records in the same second share one key.
        expected_all = [r for r in records if r.valid or item["protocol"] != "egts"]
        expected = list({r.t: r for r in expected_all}.values())
        matched = [(r, rows[r.t]) for r in expected if r.t in rows]
        max_pos = max((max(abs(r.lat - row["lat"]), abs(r.lon - row["lon"])) for r, row in matched if r.valid), default=0.0)
        hours_err = [abs(row["engine_hours"] - r.hours[item["hours_method"]])
                     for r, row in matched if row["engine_hours"] is not None and r.hours[item["hours_method"]] is not None]
        truth_err = [row["engine_hours"] - r.truth_engine_h for r, row in matched if row["engine_hours"] is not None]
        flags = sorted({f for _, row in matched for f in (row["quality_flags"] or "").split(",") if f})
        entry = {
            "imei": imei, "profile": item["profile"], "machine": PROFILES[item["profile"]].title_ru,
            "protocol": item["protocol"], "hours_method": item["hours_method"],
            "records_sent": len(records), "records_expected_after_gateway": len(expected),
            "records_stored_by_traccar": stored.get(imei), "records_normalized": len(all_rows),
            "records_via_forwarding": forwarded_per_device.get(imei, 0),
            "records_matched": len(matched),
            "max_position_error_deg": max_pos,
            "engine_hours_values": len(hours_err),
            "max_engine_hours_error_vs_sent_h": max(hours_err, default=None),
            "engine_hours_error_vs_truth_h": [min(truth_err, default=None), max(truth_err, default=None)],
            "quality_flags": flags, "transport": {k: v for k, v in item["stats"].items() if k != "sent_packets"},
        }
        if item["protocol"] == "egts":
            recovered = [c["value"] / 10 for p in item["stats"]["sent_packets"] for rec in egts.decode(p)["records"]
                         for c in rec["subrecords"] if c["type"] == "ABS_CNTR_DATA" and c["number"] == 1]
            entry["egts_counter_hours_in_packets"] = len(recovered)
            entry["egts_counter_hours_after_traccar"] = len(hours_err)
        entry["pass"] = len(matched) == len(expected) and max_pos < 2e-6 and (
            item["protocol"] == "egts" or (max(hours_err, default=0) <= 0.01 and len(hours_err) > 0))
        ok_all &= entry["pass"]
        report["devices"].append(entry)
        print(json.dumps(entry, ensure_ascii=False), flush=True)

    report["pass"] = ok_all
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print("PASS" if ok_all else "FAIL", "->", out)
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())

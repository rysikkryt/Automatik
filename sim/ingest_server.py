"""Minimal ingest endpoint for Traccar JSON forwarding (stand use).

Production equivalent: a stateless service writing to PostgreSQL/TimescaleDB,
behind the gateway's retrying forwarder (or Kafka).
"""

from __future__ import annotations

import argparse
import json
import queue
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .normalize import as_row, normalize, quality, Canonical

SCHEMA = """
CREATE TABLE IF NOT EXISTS telemetry (
    id INTEGER PRIMARY KEY,
    device_uid TEXT NOT NULL, protocol TEXT, fix_time TEXT NOT NULL, server_time TEXT,
    valid INTEGER, lat REAL, lon REAL, speed_kmh REAL, course REAL,
    engine_hours REAL, engine_hours_source TEXT, can_distance_km REAL, gps_odometer_km REAL,
    power_v REAL, rpm REAL, ignition INTEGER, quality_flags TEXT, raw TEXT,
    UNIQUE (device_uid, fix_time)
);
"""


class Store:
    """Acknowledge fast, persist in batches: a slow endpoint makes the gateway's
    forwarder time out and pile up retries (observed with per-request commits)."""

    def __init__(self, path: str):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(SCHEMA)
        self.queue: queue.Queue = queue.Queue()
        self.received = 0
        self.written = 0
        self.duplicates = 0
        self.writer = threading.Thread(target=self._write_loop, daemon=True)
        self.writer.start()

    def add(self, payload: dict) -> None:
        rec = normalize(payload)  # validation happens before the ack
        self.received += 1
        self.queue.put((rec, payload))

    def _write_loop(self) -> None:
        while True:
            batch = [self.queue.get()]
            try:
                while len(batch) < 500:
                    batch.append(self.queue.get(timeout=0.2))
            except queue.Empty:
                pass
            for rec, payload in batch:
                row = as_row(rec)
                cur = self.db.execute(
                    f"INSERT OR IGNORE INTO telemetry ({', '.join(row)}, raw) VALUES ({', '.join('?' * len(row))}, ?)",
                    [*row.values(), json.dumps(payload, ensure_ascii=False)],
                )
                if cur.rowcount == 0:
                    self.duplicates += 1  # re-delivery after a gateway retry is expected
            self.db.commit()
            self.written += len(batch)

    def recompute_quality(self) -> None:
        """Plausibility checks in fix-time order; arrival order is not chronological
        (black-box uploads, parallel forwarding)."""
        cols = [c[1] for c in self.db.execute("PRAGMA table_info(telemetry)")]
        fields = [f for f in Canonical.__dataclass_fields__]
        devices = [r[0] for r in self.db.execute("SELECT DISTINCT device_uid FROM telemetry")]
        for uid in devices:
            prev = None
            prev_t = None
            for row in self.db.execute(
                "SELECT id, strftime('%s', fix_time) AS ts, * FROM telemetry WHERE device_uid = ? ORDER BY fix_time", (uid,)
            ).fetchall():
                values = dict(zip(["_id", "_ts", *cols], row))
                cur = Canonical(**{f: values[f] for f in fields})
                flags = quality(prev, cur, int(values["_ts"]) - prev_t if prev_t is not None else 0)
                self.db.execute("UPDATE telemetry SET quality_flags = ? WHERE id = ?", (",".join(flags), values["_id"]))
                prev, prev_t = cur, int(values["_ts"])
        self.db.commit()


def make_server(store: Store, port: int) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            try:
                store.add(json.loads(self.rfile.read(length)))
            except (ValueError, KeyError) as exc:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(str(exc).encode())
                return
            self.send_response(200)
            self.end_headers()

        def do_GET(self):
            body = json.dumps({"received": store.received, "duplicates": store.duplicates}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    class Server(ThreadingHTTPServer):
        # The gateway opens hundreds of parallel forwards; the stdlib default backlog of 5
        # produced "Connect timed out" on the gateway side.
        request_queue_size = 1024
        daemon_threads = True
        allow_reuse_address = True

    return Server(("127.0.0.1", port), Handler)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=".local/ingest.sqlite3")
    parser.add_argument("--port", type=int, default=9100)
    args = parser.parse_args()
    make_server(Store(args.db), args.port).serve_forever()


if __name__ == "__main__":
    main()

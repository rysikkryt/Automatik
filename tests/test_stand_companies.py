"""Simext companies («клиент дал доступы — подключаю сам») in the live stand: every company unit is
simulated and delivered by its own path (Traccar over TCP, Wialon/AEMP by HTTP push, the rest via the
in-process gateway)."""

from __future__ import annotations

import argparse
import asyncio
import io
import socket
import threading
import time
import urllib.error

import pytest

from gateway.itles_gateway.queue import DurableQueue
from gateway.itles_gateway.records import Mapping
from gateway.itles_gateway.server import Gateway
from stand import fleet as fleetmod
from stand.run import Config, Stand

PROTOS = ("galileosky", "wialon_ips", "egts", "wialon_retranslator", "navtelecom_flex")
PUSH_PATHS = ("wialon", "aemp")
API = "https://itles.test"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def gateway():
    q = DurableQueue(":memory:")
    fleet = fleetmod.load()
    maps = {u["imei"]: Mapping.from_dict(fleetmod.gateway_mapping(u)) for u in fleetmod.units(fleet)
            if u["path"] not in ("traccar", "wialon", "aemp")}
    gw = Gateway(q, maps)
    ports = {p: _free_port() for p in PROTOS}
    loop = asyncio.new_event_loop()
    ready = threading.Event()

    def run() -> None:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(gw.serve(ports, host="127.0.0.1"))
        ready.set()
        loop.run_forever()

    threading.Thread(target=run, daemon=True).start()
    assert ready.wait(10)
    yield q, ports
    loop.call_soon_threadsafe(loop.stop)


def _stand(tmp_path, ports, post) -> Stand:
    cfg = Config.from_env(argparse.Namespace(state=str(tmp_path / "state.json"), history_days=None))
    cfg.api, cfg.key = API, "stand-key"
    cfg.ports = dict(ports)
    cfg.traccar_host, cfg.traccar_port = "127.0.0.1", _free_port()  # nothing listens: Traccar is unreachable
    return Stand(cfg, push_post=post)


def _friday_morning(now: int) -> int:
    """Friday 07:00 local (UTC+3) whose next 6 h are wholly in the past: every company profile works then."""
    day = (now + 3 * 3600) // 86400
    while (day + 3) % 7 != 4:  # the model's weekday(): 0 = Monday
        day -= 1
    t0 = day * 86400 - 3 * 3600 + 7 * 3600
    if t0 + 6 * 3600 > now - 60:
        t0 -= 7 * 86400
    return t0


def test_all_company_units_load_with_their_delivery_paths():
    fleet = fleetmod.load()
    cu = [u for u in fleetmod.units(fleet) if u.get("company_id")]
    assert len(cu) == 12
    by_company: dict[str, list[dict]] = {}
    for u in cu:
        by_company.setdefault(u["company_id"], []).append(u)
        assert u["machine_id"] is None and u["free"]
        assert u["company"] and u["platform"] and u["platform_label"]
        assert u["profile"] and u["region"] in fleet["regions"]
    assert set(by_company) == {"yugtech", "severles", "granit-karier", "stroymost"}
    assert {u["path"] for u in by_company["yugtech"]} == {"traccar"}
    assert {u["path"] for u in by_company["severles"]} == {"wialon"}
    assert {u["path"] for u in by_company["granit-karier"]} == {"aemp"}
    assert {u["path"] for u in by_company["stroymost"]} == {"gateway", "omnicomm_online"}
    assert next(u for u in by_company["stroymost"] if u["imei"] == "7011102")["path"] == "omnicomm_online"
    imeis = [u["imei"] for u in fleetmod.units(fleet)]
    assert len(imeis) == len(set(imeis))


def test_company_history_delivers_by_every_path(tmp_path, gateway):
    q, ports = gateway
    pushed: list[dict] = []

    def post(body):
        pushed.append(body)
        return {"stored": len(body["records"]), "duplicates": 0}

    st = _stand(tmp_path, ports, post)
    t0 = _friday_morning(int(time.time()))
    t1 = t0 + 6 * 3600
    for x in st.units:
        x.last_t = t0 - 1
    st.fast_forward(t0, t1, flush_every=7200)  # 3 flushes: the Traccar units reach the pause threshold
    got = q.by_device()
    for x in st.units:
        if x.u["path"] == "traccar":
            assert x.fast_off and x.tr.archive and x.u["imei"] not in got, x.u["vehicle"]
        elif x.u["path"] in PUSH_PATHS:
            assert not x.tr.archive and x.tr.records_sent > 0, x.u["vehicle"]
            assert x.u["imei"] not in got
        else:
            assert got.get(x.u["imei"], 0) > 0, x.u["vehicle"]
            assert not x.tr.archive, x.u["vehicle"]
    assert got.get("7011102", 0) > 0  # the Omnicomm EGTS retranslation of the company unit
    # push batches: right company, bounded size, engine hours never run backwards, positions near the region
    assert pushed
    by_unit: dict[str, list[dict]] = {}
    for body in pushed:
        assert body["company"] in ("severles", "granit-karier")
        assert 0 < len(body["records"]) <= 2000
        for r in body["records"]:
            by_unit.setdefault(r["unit"], []).append(r)
    fleet = fleetmod.load()
    for x in st.units:
        if x.u["path"] not in PUSH_PATHS:
            continue
        recs = by_unit.get(x.u["imei"])
        assert recs and len(recs) == x.tr.records_sent, x.u["vehicle"]
        recs.sort(key=lambda r: r["t"])
        hours = [(r["t"], r["params"]["engine_hours"]) for r in recs if "engine_hours" in r["params"]]
        assert hours, x.u["vehicle"]
        assert all(b[1] >= a[1] - 1e-6 for a, b in zip(hours, hours[1:])), x.u["vehicle"]
        lat0, lon0 = fleet["regions"][x.u["region"]]["base"]
        for r in recs:
            assert abs(r["lat"] - lat0) < 0.7 and abs(r["lon"] - lon0) < 1.5, x.u["vehicle"]
    # the snapshot shows the company and the push endpoint of its platform
    snap = st.snapshot()
    item = next(m for m in snap["machines"] if m["imei"] == "868183031245670")
    assert item["company"] == "АО «Северлес»" and item["path"] == "wialon"
    assert item["path_label"] == "Wialon Local интегратора (эмуляция Wialon Remote API)"
    assert item["endpoint"] == "itles.test:443" and item["protocol"] == "galileosky"


def test_push_failure_keeps_the_archive_and_delivers_on_the_next_flush(tmp_path, gateway):
    _q, ports = gateway
    fail = {"on": True}
    pushed: list[dict] = []

    def flaky(body):
        if fail["on"]:
            raise urllib.error.HTTPError(API, 503, "Service Unavailable", {}, io.BytesIO(b""))
        pushed.append(body)
        return {"stored": len(body["records"]), "duplicates": 0}

    st = _stand(tmp_path, ports, flaky)
    t0 = _friday_morning(int(time.time()))
    for x in st.units:
        x.last_t = t0 - 1
    st.fast_forward(t0, t0 + 3600, flush_every=3600)  # one flush, HTTP 503: black box keeps everything
    for x in st.units:
        if x.u["path"] in PUSH_PATHS:
            assert x.tr.archive and x.tr.records_sent == 0, x.u["vehicle"]
    assert not pushed
    fail["on"] = False
    st.fast_forward(t0 + 3600, t0 + 4 * 3600, flush_every=3600)
    for x in st.units:
        if x.u["path"] in PUSH_PATHS:
            assert not x.tr.archive and x.tr.records_sent > 0, x.u["vehicle"]
    assert pushed

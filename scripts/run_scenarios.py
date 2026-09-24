"""Scenario analysis on the stand. Writes docs/evidence/scenarios.json,
docs/simulation-results.md and charts in docs/img/.

All inputs are modelling assumptions (sim/machine.py, sim/gnss.py, sim/coverage.py,
sim/usage.py); the outputs show the consequences of design choices, not field data.
"""

from __future__ import annotations

import json
import pathlib
import statistics
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from sim import uplink  # noqa: E402
from sim.machine import PROFILES  # noqa: E402
from sim.protocols import egts, galileosky, wialon_ips  # noqa: E402
from sim.service import evaluate_forecasts  # noqa: E402
from sim.tracker import TrackerConfig, run, track_length_m  # noqa: E402
from sim.usage import MODELS, daily_hours  # noqa: E402

START = 1789430400  # 2026-09-15 00:00 UTC
DAYS = 7
ROOT = pathlib.Path(__file__).resolve().parents[1]
TCP_IP_OVERHEAD = 40  # IPv4 + TCP headers per segment, no options (estimate)
SESSION_OVERHEAD = 3 * 60 + 2 * 60  # handshake + teardown segments (estimate)


def bytes_per_day(records, protocol: str, sessions: int, days: int) -> dict:
    records = sorted(records, key=lambda r: r.index)
    if protocol == "galileosky":
        packets = galileosky.records_packets([uplink.galileo_record(r) for r in records], archive=False)
        up = sum(len(p) for p in packets) + len(galileosky.head_packet("860000000000011")) * sessions
        down = 3 * len(packets)
        n_packets = len(packets)
    elif protocol == "wialon":
        msgs = [uplink.wialon_message(r, "can") for r in records]
        packets = [wialon_ips.blackbox(msgs[i : i + 100]) for i in range(0, len(msgs), 100)]
        up = sum(len(p) for p in packets) + len(wialon_ips.login("860000000000011")) * sessions
        down = 9 * len(packets) + 7 * sessions
        n_packets = len(packets)
    else:
        pts = [uplink.egts_point(r, "can") for r in records]
        packets = [egts.transport(egts.teledata_records(pts[i : i + 20], i), i) for i in range(0, len(pts), 20)]
        up = sum(len(p) for p in packets) + 40 * sessions
        down = 29 * len(records)  # one response packet per record, as the stand gateway answers
        n_packets = len(packets)
    total = up + down + TCP_IP_OVERHEAD * 2 * n_packets + SESSION_OVERHEAD * sessions
    per_day = total / days
    return {"payload_up_per_record": round(up / max(1, len(records)), 1),
            "bytes_per_day": round(per_day), "mb_per_month": round(per_day * 30 / 1e6, 2)}


def physical() -> dict:
    out = {}
    for key, profile in PROFILES.items():
        res = run(key, START, DAYS, seed=21)
        tr, s = res.tracker, res.final_state
        truth_h = s.engine_s_total / 3600 - profile.initial_engine_h
        dash = round(profile.initial_engine_h, 1)
        methods = {}
        for m in ("ignition", "voltage", "d_plus"):
            measured = tr.counters_s[m] / 3600 - dash
            methods[m] = {"measured_h": round(measured, 2), "error_pct": round(100 * (measured - truth_h) / truth_h, 2),
                          "error_per_500h": round(500 * (measured - truth_h) / truth_h, 1)}
        can_records = [r for r in res.records if r.hours["can"] is not None]
        if can_records:
            last = max(can_records, key=lambda r: r.t)
            errs = [r.hours["can"] - r.truth_engine_h for r in can_records]
            methods["can"] = {"records_with_value_pct": round(100 * len(can_records) / len(res.records), 1),
                              "max_abs_error_h": round(max(abs(e) for e in errs), 3),
                              "last_error_h": round(last.hours["can"] - last.truth_engine_h, 3)}
        else:
            methods["can"] = {"records_with_value_pct": 0.0}
        true_km = s.path_m_total / 1000
        odo = {
            "true_km": round(true_km, 2),
            "gps_1hz_naive_km": round(tr.gps_odo_naive / 1000, 2),
            "gps_1hz_filtered_km": round(tr.gps_odo / 1000, 2),
            "track_points_km": round(track_length_m(res.records) / 1000, 2),
        }
        if profile.can_odometer:
            odo["can_km"] = round((s.can_distance_m - 250_000) / 1000, 2)
        delivered = [r for r in tr.delivered]
        lat = sorted((r.delivered_t - r.t) / 3600 for r in delivered)
        link = {
            "online_share_pct": round(100 * tr.stats.online_s / (DAYS * 86400), 1),
            "records_per_day": round(tr.stats.records / DAYS),
            "delivered_pct": round(100 * len(delivered) / max(1, tr.stats.records), 1),
            "latency_median_h": round(statistics.median(lat), 2) if lat else None,
            "latency_p95_h": round(lat[int(0.95 * (len(lat) - 1))], 2) if lat else None,
            "latency_max_h": round(lat[-1], 2) if lat else None,
            "max_archive_records": tr.stats.max_archive,
            "archive_days_at_capacity": round(TrackerConfig().archive_capacity / max(1, tr.stats.records / DAYS)),
            "sessions_per_day": round(tr.stats.sessions / DAYS, 1),
            "can_requests_per_day": round(tr.stats.can_requests_sent / DAYS),
        }
        traffic = {p: bytes_per_day(res.records, p, max(1, tr.stats.sessions), DAYS) for p in ("galileosky", "wialon", "egts")}
        out[key] = {"title": profile.title_ru, "sphere": profile.sphere, "examples": profile.examples,
                    "engine_hours_week_true": round(truth_h, 2), "hours": methods, "odometer": odo,
                    "link": link, "traffic": traffic}
        print(key, json.dumps(out[key]["hours"], ensure_ascii=False), flush=True)
    return out


def variants() -> dict:
    out = {}
    res = run("harvester", START, 3, seed=21, config=TrackerConfig(can_request_hours=False))
    out["harvester_no_active_request"] = {
        "records_with_can_hours_pct": round(100 * sum(r.hours["can"] is not None for r in res.records) / len(res.records), 1)}
    # Installer error: a 13.2 V absolute threshold left on a 24 V machine (6.6 V per 12 V).
    res = run("tractor_can", START, 3, seed=21, config=TrackerConfig(voltage_threshold_per_12v=6.6))
    truth = res.final_state.engine_s_total / 3600 - res.machine.profile.initial_engine_h
    measured = res.tracker.counters_s["voltage"] / 3600 - round(res.machine.profile.initial_engine_h, 1)
    out["tractor_24v_threshold_set_for_12v"] = {"true_h": round(truth, 2), "voltage_method_h": round(measured, 2),
                                                "error_pct": round(100 * (measured - truth) / truth, 1)}
    for key in ("harvester", "excavator", "forwarder"):
        for v in (1.5, 3.0, 5.0):
            r = run(key, START, 3, seed=21, config=TrackerConfig(min_speed_kmh=v))
            out[f"{key}_min_speed_{v}"] = {"true_km": round(r.final_state.path_m_total / 1000, 2),
                                           "gps_1hz_filtered_km": round(r.tracker.gps_odo / 1000, 2)}
    return out


def forecasting() -> dict:
    out = {}
    for key, model in MODELS.items():
        daily = daily_hours(model, 365 * 4, seed=5)
        for interval in ((250, 500) if key == "tractor" else (500,)):
            out[f"{key}_{interval}h"] = {"title": model.title_ru, "interval_h": interval,
                                         **evaluate_forecasts(daily, interval)}
    return out


def charts(phys: dict, fc: dict) -> None:
    img = ROOT / "docs" / "img"
    img.mkdir(parents=True, exist_ok=True)
    keys = list(phys)
    labels = [phys[k]["title"].split(" (")[0] for k in keys]

    fig, ax = plt.subplots(figsize=(11, 4.5))
    width = 0.2
    for i, m in enumerate(("ignition", "voltage", "d_plus")):
        ax.bar([x + i * width for x in range(len(keys))], [phys[k]["hours"][m]["error_pct"] for k in keys], width,
               label={"ignition": "по зажиганию", "voltage": "по напряжению", "d_plus": "по D+"}[m])
    ax.bar([x + 3 * width for x in range(len(keys))],
           [0.0 if phys[k]["hours"]["can"].get("records_with_value_pct") else float("nan") for k in keys], width, label="CAN (SPN 247)")
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_xticks([x + 1.5 * width for x in range(len(keys))], labels, rotation=20, ha="right", fontsize=8)
    ax.set_ylabel("Ошибка моточасов, %")
    ax.set_title("Моточасы: ошибка способа подсчёта относительно истины (7 суток, модель)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(img / "hours_error.png", dpi=130)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(11, 4.5))
    series = [("gps_1hz_naive_km", "GPS 1 Гц без фильтра"), ("gps_1hz_filtered_km", "GPS 1 Гц с фильтром"),
              ("track_points_km", "по точкам трека"), ("can_km", "CAN одометр")]
    for i, (field, name) in enumerate(series):
        vals = [phys[k]["odometer"].get(field, float("nan")) / max(phys[k]["odometer"]["true_km"], 0.01) for k in keys]
        ax.bar([x + i * width for x in range(len(keys))], vals, width, label=name)
    ax.set_yscale("log")
    ax.axhline(1, color="black", linewidth=0.8)
    ax.set_xticks([x + 1.5 * width for x in range(len(keys))], labels, rotation=20, ha="right", fontsize=8)
    ax.set_ylabel("Измерено / истина (лог. шкала)")
    ax.set_title("Пробег: отношение измеренного к истинному (7 суток, модель)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(img / "odometer_ratio.png", dpi=130)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 4))
    fkeys = list(fc)
    for i, m in enumerate(("mean28", "ewma", "seasonal")):
        ax.bar([x + i * 0.27 for x in range(len(fkeys))], [fc[k]["errors"][m].get(14, {}).get("mae_days", float("nan")) for k in fkeys],
               0.27, label={"mean28": "среднее 28 дн.", "ewma": "EWMA α=0.1", "seasonal": "сезонный"}[m])
    ax.set_xticks([x + 0.27 for x in range(len(fkeys))], [k.replace("_", " ") for k in fkeys], rotation=15, fontsize=8)
    ax.set_ylabel("Средняя ошибка даты ТО, дни")
    ax.set_title("Прогноз даты замены масла за 14 дней до срока (4 года, модель)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(img / "forecast_error.png", dpi=130)
    plt.close(fig)


def markdown(phys: dict, var: dict, fc: dict) -> str:
    lines = ["# Результаты сценарного моделирования (генерируется `scripts/run_scenarios.py`)", "",
             "Все входные параметры — допущения модели (см. `docs/simulation-report.md`). "
             "Таблицы показывают последствия проектных решений, а не полевые измерения.", "",
             "## Моточасы: ошибка способа подсчёта за 7 суток", "",
             "| Машина | Истинно, ч | Зажигание, % | Напряжение, % | D+, % | Ошибка на интервал 500 ч (зажиг./напр./D+) | CAN: записей со значением, % | CAN: макс. |ошибка|, ч |",
             "|---|---|---|---|---|---|---|---|"]
    for k, v in phys.items():
        h = v["hours"]
        lines.append(f"| {v['title']} | {v['engine_hours_week_true']} | {h['ignition']['error_pct']} | {h['voltage']['error_pct']} | "
                     f"{h['d_plus']['error_pct']} | {h['ignition']['error_per_500h']} / {h['voltage']['error_per_500h']} / {h['d_plus']['error_per_500h']} ч | "
                     f"{h['can'].get('records_with_value_pct', 0)} | {h['can'].get('max_abs_error_h', '—')} |")
    lines += ["", "## Пробег за 7 суток, км", "",
              "| Машина | Истинный | GPS 1 Гц без фильтра | GPS 1 Гц с фильтром | По точкам трека | CAN |", "|---|---|---|---|---|---|"]
    for k, v in phys.items():
        o = v["odometer"]
        lines.append(f"| {v['title']} | {o['true_km']} | {o['gps_1hz_naive_km']} | {o['gps_1hz_filtered_km']} | {o['track_points_km']} | {o.get('can_km', '—')} |")
    lines += ["", "## Связь, задержка доставки, чёрный ящик", "",
              "| Машина | Онлайн, % | Точек/сут | Доставлено за период, % | Задержка медиана / p95 / макс, ч | Макс. в архиве | Суток до переполнения 170 000 | CAN-запросов/сут |",
              "|---|---|---|---|---|---|---|---|"]
    for k, v in phys.items():
        link = v["link"]
        lines.append(f"| {v['title']} | {link['online_share_pct']} | {link['records_per_day']} | {link['delivered_pct']} | "
                     f"{link['latency_median_h']} / {link['latency_p95_h']} / {link['latency_max_h']} | {link['max_archive_records']} | "
                     f"{link['archive_days_at_capacity']} | {link['can_requests_per_day']} |")
    lines += ["", "## Трафик на машину (закодированные пакеты + оценка TCP/IP)", "",
              "| Машина | Galileosky, Б/точку · МБ/мес | Wialon IPS, Б/точку · МБ/мес | EGTS, Б/точку · МБ/мес |", "|---|---|---|---|"]
    for k, v in phys.items():
        t = v["traffic"]
        lines.append(f"| {v['title']} | " + " | ".join(f"{t[p]['payload_up_per_record']} · {t[p]['mb_per_month']}" for p in ("galileosky", "wialon", "egts")) + " |")
    lines += ["", "## Варианты настроек", "", "```json", json.dumps(var, ensure_ascii=False, indent=1), "```", "",
              "## Прогноз даты замены масла (ошибка в днях)", "",
              "| Класс, интервал | Моточасов/год | Замен за 4 года | Упреждение | Среднее 28 дн.: MAE / P90 / доля «позже» | EWMA: MAE / P90 | Сезонный: MAE / P90 |",
              "|---|---|---|---|---|---|---|"]
    for k, v in fc.items():
        for lead in (30, 14, 7):
            e = v["errors"]
            if lead not in e["mean28"]:
                continue
            lines.append(f"| {v['title']}, {v['interval_h']} ч | {v['annual_hours']} | {v['services']} | {lead} дн | "
                         f"{e['mean28'][lead]['mae_days']} / {e['mean28'][lead]['p90_abs_days']} / {e['mean28'][lead]['late_share']} | "
                         f"{e['ewma'][lead]['mae_days']} / {e['ewma'][lead]['p90_abs_days']} | {e['seasonal'][lead]['mae_days']} / {e['seasonal'][lead]['p90_abs_days']} |")
    lines += ["", "![Моточасы](img/hours_error.png)", "", "![Пробег](img/odometer_ratio.png)", "", "![Прогноз ТО](img/forecast_error.png)", ""]
    return "\n".join(lines)


def main() -> None:
    phys = physical()
    var = variants()
    fc = forecasting()
    charts(phys, fc)
    evidence = ROOT / "docs" / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "scenarios.json").write_text(json.dumps({"physical": phys, "variants": var, "forecasting": fc},
                                                        ensure_ascii=False, indent=1))
    (ROOT / "docs" / "simulation-results.md").write_text(markdown(phys, var, fc))
    print("written docs/evidence/scenarios.json, docs/simulation-results.md, docs/img/*.png")


if __name__ == "__main__":
    main()

"""Service-interval engine and due-date forecasting.

Rules are per machine model and unit, sourced from OEM manuals or the lubricant
supplier's recommendations; templates here are placeholders for simulations.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class ServiceRule:
    unit: str
    interval_h: float | None = None
    interval_km: float | None = None
    interval_days: int | None = None
    fill_l: float = 0.0


@dataclass
class UnitState:
    last_hours: float
    last_km: float
    last_date: date


@dataclass(frozen=True)
class DueStatus:
    unit: str
    used_share: float  # max over criteria, 1.0 = due
    driver: str  # which criterion comes first
    remaining_h: float | None
    remaining_km: float | None
    remaining_days: int | None
    forecast_date: date | None
    level: str  # ok | soon | due | overdue


def due_status(rule: ServiceRule, state: UnitState, hours: float, km: float, today: date,
               avg_daily_h: float, avg_daily_km: float, soon_share: float = 0.9) -> DueStatus:
    """'Whichever comes first' across hours, km and calendar."""
    candidates: list[tuple[float, str, date | None]] = []
    rem_h = rem_km = rem_d = None
    if rule.interval_h:
        rem_h = rule.interval_h - (hours - state.last_hours)
        eta = today + timedelta(days=math.ceil(rem_h / avg_daily_h)) if avg_daily_h > 0 and rem_h > 0 else (today if rem_h <= 0 else None)
        candidates.append(((hours - state.last_hours) / rule.interval_h, "hours", eta))
    if rule.interval_km:
        rem_km = rule.interval_km - (km - state.last_km)
        eta = today + timedelta(days=math.ceil(rem_km / avg_daily_km)) if avg_daily_km > 0 and rem_km > 0 else (today if rem_km <= 0 else None)
        candidates.append(((km - state.last_km) / rule.interval_km, "km", eta))
    if rule.interval_days:
        elapsed = (today - state.last_date).days
        rem_d = rule.interval_days - elapsed
        candidates.append((elapsed / rule.interval_days, "calendar", state.last_date + timedelta(days=rule.interval_days)))
    share, driver, _ = max(candidates, key=lambda c: c[0])
    dated = [c[2] for c in candidates if c[2] is not None]
    forecast = min(dated) if dated else None
    level = "overdue" if share > 1.05 else "due" if share >= 1.0 else "soon" if share >= soon_share else "ok"
    return DueStatus(rule.unit, share, driver, rem_h, rem_km, rem_d, forecast, level)


def forecast_rate(history: list[float], method: str, same_period_last_year: list[float] | None = None) -> float:
    """Average daily usage used to project the due date."""
    if method == "mean28":
        window = history[-28:]
        return sum(window) / len(window) if window else 0.0
    if method == "ewma":
        rate = history[0] if history else 0.0
        for x in history[1:]:
            rate = 0.1 * x + 0.9 * rate
        return rate
    if method == "seasonal":
        recent = forecast_rate(history, "mean28")
        if not same_period_last_year:
            return recent
        return 0.5 * recent + 0.5 * sum(same_period_last_year) / len(same_period_last_year)
    raise ValueError(method)


def evaluate_forecasts(daily: list[float], interval_h: float, lead_days: tuple[int, ...] = (30, 14, 7),
                       methods: tuple[str, ...] = ("mean28", "ewma", "seasonal")) -> dict:
    """Replay a usage series: at each lead time before a real due day, forecast it."""
    cumulative, due_days, since = [], [], 0.0
    total = 0.0
    for day, h in enumerate(daily):
        total += h
        since += h
        cumulative.append(total)
        if since >= interval_h:
            due_days.append(day)
            since -= interval_h
    errors: dict[str, dict[int, list[int]]] = {m: {lead: [] for lead in lead_days} for m in methods}
    last_service_hours = 0.0
    for due in due_days:
        for lead in lead_days:
            today = due - lead
            if today < 60:
                continue
            used = cumulative[today] - last_service_hours
            remaining = interval_h - used
            for m in methods:
                last_year = daily[today - 365 : today - 365 + 28] if today >= 365 else None
                rate = forecast_rate(daily[max(0, today - 90) : today + 1], m, last_year)
                predicted = today + (math.ceil(remaining / rate) if rate > 0 else 365)
                errors[m][lead].append(predicted - due)
        last_service_hours += interval_h
    summary = {}
    for m in methods:
        summary[m] = {}
        for lead, errs in errors[m].items():
            if errs:
                abs_sorted = sorted(abs(e) for e in errs)
                summary[m][lead] = {
                    "n": len(errs), "mae_days": round(sum(abs_sorted) / len(errs), 1),
                    "p90_abs_days": abs_sorted[min(len(errs) - 1, int(0.9 * len(errs)))],
                    "late_share": round(sum(1 for e in errs if e > 0) / len(errs), 2),
                }
    return {"services": len(due_days), "annual_hours": round(sum(daily) / (len(daily) / 365), 0), "errors": summary}

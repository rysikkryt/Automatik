"""Seasonal daily engine-hour models per machine class (stated assumptions).

Used for multi-year service-interval and lubricant-demand simulations where
per-second physics is unnecessary. Numbers are assumptions to be replaced by
real fleet statistics after the pilot; see docs/simulation-report.md.
"""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class Season:
    first_doy: int
    last_doy: int
    work_prob: float
    hours_mean: float
    hours_sd: float


@dataclass(frozen=True)
class UsageModel:
    key: str
    title_ru: str
    seasons: tuple[Season, ...]
    km_per_hour: float = 0.0  # for km-based service rules


MODELS: dict[str, UsageModel] = {
    m.key: m
    for m in (
        UsageModel("tractor", "Трактор (юг, полевые работы)", (
            Season(1, 59, 0.1, 2.0, 1.0), Season(60, 79, 0.4, 5.0, 2.0), Season(80, 140, 0.8, 10.0, 2.0),
            Season(141, 181, 0.4, 5.0, 2.0), Season(182, 243, 0.6, 8.0, 2.5), Season(244, 320, 0.65, 9.0, 2.0),
            Season(321, 366, 0.15, 3.0, 1.5))),
        UsageModel("harvester", "Харвестер/форвардер (2 смены)", (
            Season(1, 90, 0.9, 18.0, 2.0), Season(91, 150, 0.3, 6.0, 3.0), Season(151, 243, 0.8, 15.0, 3.0),
            Season(244, 334, 0.85, 17.0, 2.0), Season(335, 366, 0.9, 18.0, 2.0))),
        UsageModel("excavator", "Карьерный экскаватор (2 смены)", (Season(1, 366, 0.88, 19.0, 2.0),)),
        UsageModel("dump_truck", "Карьерный самосвал (2 смены)", (Season(1, 366, 0.85, 19.0, 2.5),), km_per_hour=17.0),
        UsageModel("timber_truck", "Лесовоз (зимник + лето)", (
            Season(1, 90, 0.85, 14.0, 2.0), Season(91, 150, 0.35, 8.0, 3.0), Season(151, 334, 0.7, 11.0, 3.0),
            Season(335, 366, 0.85, 14.0, 2.0)), km_per_hour=28.0),
    )
}


def daily_hours(model: UsageModel, days: int, seed: int, start_doy: int = 1) -> list[float]:
    rng = random.Random(seed)
    out = []
    for i in range(days):
        doy = (start_doy - 1 + i) % 365 + 1
        season = next(s for s in model.seasons if s.first_doy <= doy <= s.last_doy)
        if rng.random() < season.work_prob:
            out.append(max(0.0, min(22.0, rng.gauss(season.hours_mean, season.hours_sd))))
        else:
            out.append(0.0)
    return out

"""Cellular coverage models (modelling assumptions, see docs/simulation-report.md)."""

from __future__ import annotations

import math
import random


class Coverage:
    """Two-state Markov availability, optionally restricted to zones."""

    def __init__(self, kind: str, rng: random.Random):
        self.kind = kind
        self.rng = rng
        self.online_state = True
        params = {
            "rural": (3600.0, 300.0),
            "quarry": (4 * 3600.0, 120.0),
            "forest": (1800.0, 600.0),
            "road": (5400.0, 300.0),
        }
        self.mean_on, self.mean_off = params[kind]

    def _markov(self) -> bool:
        p_leave = 1 / (self.mean_on if self.online_state else self.mean_off)
        if self.rng.random() < p_leave:
            self.online_state = not self.online_state
        return self.online_state

    def online(self, east: float, north: float) -> bool:
        base = self._markov()
        if self.kind == "forest":
            # Only the landing next to the forest road has (weak) signal.
            return base and math.hypot(east, north) < 400
        if self.kind == "road":
            return base and math.hypot(east - 60000, north - 20000) > 15000
        return base

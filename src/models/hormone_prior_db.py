"""Offline hormone prior database loader.

Training/downloading scripts can create `models/hormone_priors.json` from public
hormone databases such as NHANES and mcPHASES. During demonstration the app uses
this local JSON file offline.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.config import MODEL_DIR


DEFAULT_PRIORS = {
    "female_adolescent": {
        "Insulin": {"median": 8.0, "p05": 2.0, "p95": 28.0},
        "Testosterone": {"median": 32.0, "p05": 10.0, "p95": 75.0},
        "LH": {"median": 7.0, "p05": 1.0, "p95": 45.0},
        "FSH": {"median": 6.0, "p05": 1.5, "p95": 18.0},
        "Estrogen": {"median": 90.0, "p05": 15.0, "p95": 350.0},
        "Progesterone": {"median": 2.0, "p05": 0.1, "p95": 18.0},
        "Cortisol": {"median": 10.0, "p05": 3.0, "p95": 25.0},
        "AMH": {"median": 4.5, "p05": 0.5, "p95": 12.0},
    }
}


class HormonePriorDB:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else MODEL_DIR / "hormone_priors.json"
        self.data: dict[str, Any] = DEFAULT_PRIORS
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                self.data = DEFAULT_PRIORS

    def group_for_age(self, age: float | None) -> str:
        if age is None or age < 20:
            return "female_adolescent"
        if age < 30:
            return "female_20_29"
        if age < 40:
            return "female_30_39"
        return "female_40_plus"

    def median(self, hormone: str, age: float | None = None, default: float | None = None) -> float:
        group = self.group_for_age(age)
        if group in self.data and hormone in self.data[group]:
            return float(self.data[group][hormone].get("median", default if default is not None else 1.0))
        if "female_adolescent" in self.data and hormone in self.data["female_adolescent"]:
            return float(self.data["female_adolescent"][hormone].get("median", default if default is not None else 1.0))
        return float(default if default is not None else 1.0)

    def range(self, hormone: str, age: float | None = None) -> tuple[float, float] | None:
        group = self.group_for_age(age)
        rec = self.data.get(group, {}).get(hormone) or self.data.get("female_adolescent", {}).get(hormone)
        if not rec:
            return None
        return float(rec.get("p05", 0.0)), float(rec.get("p95", rec.get("median", 1.0)))

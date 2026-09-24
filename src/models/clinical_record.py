"""Clinical record, report history and comparison (V6.2).

Clinician-facing longitudinal evidence: structured clinical visits, notes,
ultrasound observations (clinically entered — the wearable cannot see ovarian
anatomy), saved periodic reports, and a COMPARE REPORTS view that summarises
what improved, worsened, remained stable, or became uncertain between two
assessments.

Nothing here diagnoses. Report comparisons are descriptive differences of
model estimates and recorded measurements, and every comparison is labelled
as such.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from src.models.care_plan import CarePlanManager
from src.models.change_detector import ChangeReport
from src.utils.history_store import HistoryStore

# metrics that appear in report summaries; lower-is-better for the first set.
LOWER_BETTER = {"rmssd", "resting_hr", "risk", "stress"}


@dataclass
class CompareRow:
    metric: str
    label: str
    a_value: Optional[float]
    b_value: Optional[float]
    delta: Optional[float]
    status: str = "stable"   # improved | worsened | stable | uncertain

    def text(self) -> str:
        if self.a_value is None or self.b_value is None:
            return f"{self.label}: data missing on one side (uncertain)"
        return (f"{self.label}: {self.a_value:.1f} → {self.b_value:.1f} "
                f"({self.delta:+.1f}) — {self.status}")


@dataclass
class ReportComparison:
    a_id: int
    b_id: int
    a_ts: float
    b_ts: float
    rows: List[CompareRow] = field(default_factory=list)

    def summary_text(self) -> str:
        if not self.rows:
            return "The two reports share no comparable metrics."
        improved = [r for r in self.rows if r.status == "improved"]
        worsened = [r for r in self.rows if r.status == "worsened"]
        stable = [r for r in self.rows if r.status == "stable"]
        uncertain = [r for r in self.rows if r.status == "uncertain"]
        lines = [
            f"Comparison of report {self.a_id} → {self.b_id} "
            f"({time.strftime('%Y-%m-%d', time.localtime(self.a_ts))} → "
            f"{time.strftime('%Y-%m-%d', time.localtime(self.b_ts))}):",
        ]
        if improved:
            lines.append("  Improved: " + "; ".join(r.label for r in improved))
        if worsened:
            lines.append("  Worsened: " + "; ".join(r.label for r in worsened))
        if stable:
            lines.append("  Stable: " + "; ".join(r.label for r in stable))
        if uncertain:
            lines.append("  Uncertain: " + "; ".join(r.label for r in uncertain))
        lines.append("Descriptive comparison only — not a diagnosis.")
        return "\n".join(lines)


class ClinicalRecord:
    def __init__(self, store: HistoryStore):
        self.store = store
        self.care = CarePlanManager(store)

    # ------------------------------------------------------------ visits
    def add_visit(self, summary: str, clinician: str = "") -> int:
        return self.store.add_visit(summary, clinician)

    def visits(self) -> List[dict]:
        return self.store.visits()

    def add_note(self, note: str, clinician: str = "") -> int:
        return self.store.add_clinical_note(note, clinician)

    def notes(self) -> List[dict]:
        return self.store.clinical_notes()

    # --------------------------------------------------------- ultrasound
    def add_ultrasound(self, cyst_size_mm: float | None = None, volume_cc: float | None = None,
                       morphology: str = "", septations: int | None = None,
                       solid_components: int | None = None, free_fluid: int | None = None,
                       source: str = "clinical", summary: str = "") -> int:
        return self.store.log_ultrasound(
            cyst_size_mm=cyst_size_mm, volume_cc=volume_cc, morphology=morphology,
            septations=septations, solid_components=solid_components,
            free_fluid=free_fluid, source=source, summary=summary)

    def ultrasound_history(self) -> List[dict]:
        return self.store.ultrasound_history()

    # ------------------------------------------------------------ reports
    def save_report(self, kind: str, participant: str, text: str,
                    metrics: Dict[str, Optional[float]] | None = None) -> int:
        return self.store.save_report(kind, participant, text, metrics or {})

    def reports(self) -> List[dict]:
        return self.store.reports()

    def _metric_row(self, label: str, a: Optional[float], b: Optional[float]) -> CompareRow:
        if a is None or b is None:
            return CompareRow(label=label, a_value=a, b_value=b, delta=None, status="uncertain")
        delta = float(b) - float(a)
        tol = 0.05 * (abs(a) + 1e-9) + 0.5
        if abs(delta) <= tol:
            status = "stable"
        else:
            lower_better = label in LOWER_BETTER or any(k in label for k in ("risk", "stress", "hr"))
            status = "improved" if (delta < 0) == lower_better else "worsened"
        return CompareRow(metric=label, label=label, a_value=a, b_value=b, delta=delta, status=status)

    def compare_reports(self, a_id: int, b_id: int) -> Optional[ReportComparison]:
        a = self.store.report_by_id(a_id)
        b = self.store.report_by_id(b_id)
        if a is None or b is None:
            return None
        comp = ReportComparison(a_id=a_id, b_id=b_id, a_ts=a["ts"], b_ts=b["ts"])
        keys = sorted(set(a.get("metrics", {})) | set(b.get("metrics", {})))
        for k in keys:
            label = {
                "mean_hr": "Heart rate (mean)",
                "resting_hr": "Resting HR",
                "rmssd": "HRV RMSSD",
                "temp_amp": "Temp amplitude",
                "activity": "Activity",
                "stress": "Stress",
                "risk": "Model risk estimate",
                "health": "Health score",
                "circadian": "Circadian stability",
                "night_sleep": "Night sleep probability",
            }.get(k, k.replace("_", " ").title())
            comp.rows.append(self._metric_row(label, a.get("metrics", {}).get(k),
                                              b.get("metrics", {}).get(k)))
        return comp

    # -------------------------------------------------------- what changed
    def what_changed_since_last_visit(self, change: Optional[ChangeReport] = None,
                                      current_risk: Optional[float] = None,
                                      current_confidence: Optional[float] = None,
                                      adherence: Optional[List[dict]] = None,
                                      ultrasound_compare: bool = True) -> List[str]:
        """Plain-language 'WHAT CHANGED SINCE LAST VISIT?' lines for the
        clinician dashboard. Every line is evidence-linked."""
        lines: List[str] = []
        visits = self.visits()
        if len(visits) >= 2:
            prev = visits[1]
            span_days = (time.time() - prev["ts"]) / 86400.0
            lines.append(f"Monitoring period since last recorded visit: {span_days:.0f} days.")
        elif visits:
            span_days = (time.time() - visits[0]["ts"]) / 86400.0
            lines.append(f"Monitoring period since last recorded visit: {span_days:.0f} days.")
        else:
            lines.append("Monitoring period: from first recorded session (no structured visit logged yet).")

        if change is not None and change.overall_kind == "deviation":
            lines.append(f"Physiology: {change.summary}")
        elif change is not None:
            lines.append("Physiology: no persistent deviation detected since the last assessment.")

        if current_risk is not None:
            lines.append(f"Model estimate: {current_risk:.0f}% "
                         f"(confidence {current_confidence:.0f}%) — research estimate, not a diagnosis.")

        if adherence:
            gaps = [m for m in adherence if m.get("gap")]
            if gaps:
                lines.append("Adherence: " + "; ".join(
                    f"'{m['name']}' {m['adherence_pct']:.0f}%" for m in gaps) + " — potential care-plan gaps.")
            else:
                lines.append("Adherence: no gaps flagged in the recorded window.")

        us = self.ultrasound_history()
        if len(us) >= 2 and ultrasound_compare:
            l, p = us[0], us[1]
            l_sz, p_sz = l.get("cyst_size_mm"), p.get("cyst_size_mm")
            if l_sz and p_sz and abs(l_sz - p_sz) > 0.5:
                lines.append(f"Ultrasound (clinically entered): largest cyst size "
                             f"{p_sz:.1f} → {l_sz:.1f} mm between examinations.")
        return lines

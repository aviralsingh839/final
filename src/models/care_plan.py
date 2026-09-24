"""Care plan + adherence recorder (V6.2).

What this module does:

  * stores a clinician/user-entered care plan: medications (name, dose,
    schedule, start/end, food instruction), lifestyle goals, appointments and
    test reminders;
  * records adherence with three statuses only: taken / skipped / snoozed;
  * computes an adherence summary and flags "potential care-plan gaps"
    (never "the patient did everything wrong");
  * produces a CARE JOURNEY SUMMARY that strictly separates OBSERVED /
    ASSOCIATED / UNKNOWN.

What this module NEVER does:

  * it never changes, starts, stops or prescribes medication;
  * it never infers a diagnosis or a causal link between adherence and
    physiology — missed doses are "temporally associated with" observed
    changes at most (see care_gap_analysis).

Reminders are pure bookkeeping: "the recorded plan says dose X is due".
"""
from __future__ import annotations

import time
from typing import Dict, List, Optional

from src.utils.history_store import HistoryStore

# doses per day per cadence (weekly -> 1/7).
CADENCE_DOSES_PER_DAY = {
    "daily": 1.0,
    "twice_daily": 2.0,
    "weekly": 1.0 / 7.0,
    "as_needed": None,
    "custom": None,
}

TIME_OF_DAY_WINDOWS = {  # (start_hour, end_hour) for reminder framing
    "morning": (6, 12),
    "evening": (12, 18),
    "night": (18, 23),
    "any": (0, 24),
}

# Used by the clinical dashboard.
GAP_LABELS = {
    "medication": "Potential care-plan gap — medication doses not recorded as taken",
    "goal": "Potential care-plan gap — lifestyle goal not met",
    "appointment": "Upcoming / overdue appointment or test reminder",
}


class CarePlanManager:
    def __init__(self, store: HistoryStore):
        self.store = store

    # --------------------------------------------------------- medications
    def add_medication(self, name: str, dose: str = "", unit: str = "",
                       cadence: str = "daily", time_of_day: str = "any",
                       food_instruction: str = "", note: str = "",
                       start_days_ago: Optional[float] = None) -> int:
        if cadence not in CADENCE_DOSES_PER_DAY:
            raise ValueError(f"unknown cadence: {cadence}")
        start_ts = (time.time() - start_days_ago * 86400.0) if start_days_ago is not None else None
        return self.store.add_medication(
            name=name, dose=dose, unit=unit, cadence=cadence, time_of_day=time_of_day,
            start_ts=start_ts, end_ts=None, food_instruction=food_instruction, note=note,
        )

    def medications(self) -> List[dict]:
        return self.store.medications(active_only=True)

    def log_taken(self, medication_id: int, note: str = "") -> None:
        self.store.log_medication(medication_id, "taken", note)

    def log_skipped(self, medication_id: int, note: str = "") -> None:
        self.store.log_medication(medication_id, "skipped", note)

    def log_snoozed(self, medication_id: int, note: str = "") -> None:
        self.store.log_medication(medication_id, "snoozed", note)

    # ----------------------------------------------------------- adherence
    def adherence_summary(self, days: int = 30) -> List[dict]:
        """Per active medication: recorded doses vs scheduled doses.

        expected = scheduled dose slots in the window (capped at >= recorded
        total so a late start never produces a negative gap). For
        as_needed/custom plans the schedule is unknown, so expected equals the
        recorded total and adherence reflects the taken share of what was
        logged.
        """
        now = time.time()
        window_start = now - days * 86400.0
        logs = self.store.medication_log(limit=5000)
        out: List[dict] = []
        for med in self.medications():
            if med.get("end_ts") and med["end_ts"] < window_start:
                continue
            med_logs = [l for l in logs if l.get("medication_id") == med["id"] and l["ts"] >= window_start]
            taken = sum(1 for l in med_logs if l["status"] == "taken")
            skipped = sum(1 for l in med_logs if l["status"] == "skipped")
            snoozed = sum(1 for l in med_logs if l["status"] == "snoozed")
            logged_total = taken + skipped + snoozed

            doses_per_day = CADENCE_DOSES_PER_DAY.get(med.get("cadence", "daily"))
            if doses_per_day:
                if med.get("start_ts"):
                    active_days = max(0.0, (now - med["start_ts"]) / 86400.0)
                    window_days = min(days, active_days)
                else:
                    window_days = float(days)
                expected = int(round(window_days * doses_per_day))
            else:
                expected = logged_total  # as_needed / custom: no schedule
            expected = max(expected, logged_total)
            adherence_pct = (taken / expected * 100.0) if expected > 0 else 0.0
            out.append({
                "medication_id": med["id"],
                "name": med["name"],
                "dose": med.get("dose", ""),
                "unit": med.get("unit", ""),
                "cadence": med.get("cadence", "daily"),
                "taken": taken,
                "skipped": skipped,
                "snoozed": snoozed,
                "n_expected": expected,
                "adherence_pct": round(adherence_pct, 1),
                "gap": adherence_pct < 70.0 and expected >= 3,
            })
        return out

    def due_medications(self, now: float | None = None) -> List[dict]:
        """Medications whose recorded plan has a dose slot not yet logged today.

        Pure bookkeeping: 'the plan says a dose is due'. Never a medical
        instruction — a missed log is a missing record, not a missed medicine.
        """
        now = now or time.time()
        day_start = now - (now % 86400.0)
        logs = self.store.medication_log(limit=5000)
        today_logs = [l for l in logs if l["ts"] >= day_start]
        due: List[dict] = []
        for med in self.medications():
            if med.get("end_ts") and med["end_ts"] < now:
                continue
            if med.get("start_ts") and med["start_ts"] > now:
                continue
            doses_per_day = CADENCE_DOSES_PER_DAY.get(med.get("cadence", "daily"))
            if not doses_per_day:
                continue  # as_needed / custom: no automatic reminder
            logged_today = sum(1 for l in today_logs if l.get("medication_id") == med["id"])
            if logged_today < int(round(doses_per_day)):
                due.append({
                    "medication_id": med["id"],
                    "name": med["name"],
                    "dose": med.get("dose", ""),
                    "unit": med.get("unit", ""),
                    "time_of_day": med.get("time_of_day", "any"),
                    "food_instruction": med.get("food_instruction", ""),
                    "slots_today": int(round(doses_per_day)),
                    "logged_today": logged_today,
                })
        return due

    # -------------------------------------------------------------- goals
    def add_goal(self, goal: str, target_text: str = "", kind: str = "lifestyle") -> int:
        return self.store.add_goal(goal, target_text, kind)

    def goals(self) -> List[dict]:
        return self.store.goals(active_only=True)

    # ------------------------------------------------------- appointments
    def add_appointment(self, kind: str = "appointment", due_in_days: float | None = None,
                        note: str = "") -> int:
        due_ts = (time.time() + due_in_days * 86400.0) if due_in_days is not None else None
        return self.store.add_appointment(kind=kind, due_ts=due_ts, note=note)

    def appointments(self) -> List[dict]:
        return self.store.appointments()

    def due_appointments(self, now: float | None = None) -> List[dict]:
        now = now or time.time()
        return [a for a in self.store.appointments()
                if not a.get("done") and a.get("due_ts") and a["due_ts"] <= now + 3 * 86400.0]

    # -------------------------------------------------------- gap analysis
    def care_gap_analysis(self, change_report=None) -> Dict[str, List[str]]:
        """CARE JOURNEY SUMMARY: OBSERVED / ASSOCIATED / UNKNOWN.

        * OBSERVED   — facts recorded in the store (missed doses, unmet goals)
        * ASSOCIATED — temporal co-occurrence with physiological changes
        * UNKNOWN    — what the system cannot establish (causality, diagnosis)
        """
        observed: List[str] = []
        associated: List[str] = []
        unknown: List[str] = []

        for m in self.adherence_summary(days=60):
            if m.get("gap"):
                observed.append(
                    f"{m['taken']} of {m['n_expected']} expected doses of '{m['name']}' "
                    f"recorded taken ({m['adherence_pct']:.0f}%) across the review window.")
        low_activity_goals = [g for g in self.goals() if g.get("kind") in ("activity", "lifestyle")]
        if low_activity_goals:
            observed.append(f"{len(low_activity_goals)} lifestyle goal(s) are recorded "
                            "but no completion log exists yet — completion tracking is pending.")

        if change_report is not None and change_report.overall_kind == "deviation":
            associated.append(
                "Physiological deviation was detected during part of the same period "
                f"({change_report.summary}).")
        associated.append(
            "Any missed-dose and physiology changes are temporally associated observations only.")

        unknown.append(
            "The system cannot establish that missed medication or lifestyle gaps caused "
            "any physiological change — no causal claim is made.")
        unknown.append(
            "The system cannot diagnose PCOS or any condition; clinical evaluation is required.")

        return {"observed": observed, "associated": associated, "unknown": unknown}

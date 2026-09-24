"""Model/data-leakage detection.

Automated heuristic checks over the local database:
  * same subject in train/test,
  * duplicate sessions,
  * duplicated windows/rows,
  * future data leaking into training (timestamps after a train cutoff),
  * normalization fitted on the test set (baseline captured too late),
  * labels accidentally included as features.

These are heuristics — a pass here is evidence, not proof of absence of leakage.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from src.utils.history_store import HistoryStore


@dataclass
class LeakageCheck:
    name: str
    status: str  # pass | warn | fail | info
    detail: str

    def render(self) -> str:
        icon = {"pass": "[PASS]", "warn": "[WARN]", "fail": "[FAIL]", "info": "[INFO]"}.get(self.status, "[INFO]")
        return f"{icon} {self.name}: {self.detail}"


def _subject_of(db: HistoryStore) -> List[dict]:
    """Sessions with participant_id resolved (fallback: session id)."""
    rows = db.session_summary(limit=1000)
    out = []
    for r in rows:
        subj = (r.get("participant_id") or "").strip() or f"session#{r['id']}"
        out.append({"id": r["id"], "subject": subj, "started_at": r.get("started_at")})
    return out


def run_leakage_checks(db: HistoryStore) -> List[LeakageCheck]:
    checks: List[LeakageCheck] = []
    import sqlite3

    sessions = _subject_of(db)
    df = db.features_as_frame(days=365)

    # 1) Same subject in train/test.
    train, test = sessions[: max(0, len(sessions) // 2)], sessions[len(sessions) // 2:]
    train_subjects = {s["subject"] for s in train}
    test_subjects = {s["subject"] for s in test}
    overlap = train_subjects & test_subjects
    if not sessions:
        checks.append(LeakageCheck("Subject train/test separation", "info", "no sessions recorded yet"))
    elif overlap:
        detail = "subjects present in both halves of the timeline: " + ", ".join(sorted(overlap)[:6])
        checks.append(LeakageCheck("Subject train/test separation", "fail", detail))
    else:
        checks.append(LeakageCheck("Subject train/test separation", "pass",
                                   f"{len(train)} train / {len(test)} test sessions with no subject overlap"))

    # 2) Duplicate sessions (same subject started within 2 s).
    dups = 0
    seen: dict = {}
    for s in sessions:
        key = (s["subject"], int(s["started_at"]) if s["started_at"] else 0)
        if key in seen:
            dups += 1
        else:
            seen[key] = True
    if dups:
        checks.append(LeakageCheck("Duplicate sessions", "warn", f"{dups} session(s) share subject + same start second"))
    else:
        checks.append(LeakageCheck("Duplicate sessions", "pass", "no same-second duplicate sessions"))

    # 3) Duplicated windows/rows.
    if not df.empty:
        dup_rows = int(df.duplicated(subset=["session_id", "ts"], keep=False).sum())
        dup_signals = int(df.duplicated(subset=["hr", "rmssd", "spo2", "skin_temp", "gsr"], keep=False).sum())
        if dup_rows:
            checks.append(LeakageCheck("Duplicate windows", "warn", f"{dup_rows} feature row(s) share session+timestamp"))
        else:
            checks.append(LeakageCheck("Duplicate windows", "pass", "no duplicate session+timestamp rows"))
        if dup_signals:
            checks.append(LeakageCheck("Identical signal rows", "info", f"{dup_signals} row(s) with identical signal values"))
    else:
        checks.append(LeakageCheck("Duplicate windows", "info", "no feature rows yet"))

    # 4) Future data leaking (rows after their session end).
    future = 0
    if not df.empty:
        conn = sqlite3.connect(str(db.path))
        try:
            rows = conn.execute("SELECT f.ts, f.session_id, s.ended_at FROM features f JOIN sessions s ON s.id=f.session_id WHERE s.ended_at IS NOT NULL").fetchall()
            future = sum(1 for ts, _sid, ended in rows if ended is not None and ts > ended + 60.0)
        finally:
            conn.close()
    if future:
        checks.append(LeakageCheck("Future timestamps", "warn", f"{future} feature row(s) logged after session end (+60 s)"))
    else:
        checks.append(LeakageCheck("Future timestamps", "pass", "no rows after session end"))

    # 5) Normalization fitted on test: personal baseline captured after data exists.
    cals = db.calibration_history(limit=100)
    if not df.empty and cals:
        first_feature = float(df["ts"].min())
        cal_after = [c for c in cals if c["ts"] > first_feature]
        if cal_after:
            checks.append(LeakageCheck("Normalization leakage",
                                       "warn",
                                       f"{len(cal_after)} baseline capture(s) occurred after the first feature row — "
                                       "earlier rows used population defaults, not the personal baseline"))
        else:
            checks.append(LeakageCheck("Normalization leakage", "pass",
                                       "personal baseline (if any) predates the feature history"))
    else:
        checks.append(LeakageCheck("Normalization leakage", "info", "no baseline/features to compare"))

    # 6) Labels as features.
    if not df.empty:
        label_cols = [c for c in df.columns if c.lower() in ("label", "outcome", "y")]
        if label_cols:
            checks.append(LeakageCheck("Label-in-features", "fail",
                                       f"label column(s) present in feature table: {', '.join(label_cols)}"))
        else:
            checks.append(LeakageCheck("Label-in-features", "pass",
                                       "no label column in the feature table (labels live only in extra_json metadata)"))

    # 7) Duplicate subject ids with inconsistent spelling.
    raw = [s["subject"] for s in sessions if not str(s["subject"]).startswith("session#")]
    norm = {}
    for r in raw:
        norm.setdefault(r.lower().strip(), set()).add(r)
    messy = {k: v for k, v in norm.items() if len(v) > 1}
    if messy:
        checks.append(LeakageCheck("Subject id consistency", "warn",
                                   f"{len(messy)} subject id(s) spelled differently across sessions"))
    else:
        checks.append(LeakageCheck("Subject id consistency", "pass", "subject ids are consistent"))

    return checks

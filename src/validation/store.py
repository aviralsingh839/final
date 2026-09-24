"""Structured ground-truth / reference-data system.

Stores paired reference-device measurements, prospective predictions (with
outcome labels added later), frozen model snapshots, and validation reports —
all in the same local SQLite file as the main history store. Nothing is
transmitted anywhere and no clinical ground truth is ever fabricated: labels
are entered manually or come from clearly-marked synthetic data.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


class ValidationStore:
    def __init__(self, db_path: Path | str):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self):
        import sqlite3

        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        conn = self._connect()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS reference_pairs(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    subject_id TEXT,
                    session_id INTEGER,
                    metric TEXT NOT NULL,
                    sensor_value REAL NOT NULL,
                    reference_value REAL NOT NULL,
                    condition TEXT,
                    quality_flag TEXT,
                    notes TEXT
                );
                CREATE TABLE IF NOT EXISTS prospective_predictions(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    subject_id TEXT,
                    model_version TEXT,
                    risk REAL NOT NULL,
                    ci_low REAL,
                    ci_high REAL,
                    confidence REAL,
                    sqi REAL,
                    outcome INTEGER,
                    outcome_ts REAL
                );
                CREATE TABLE IF NOT EXISTS model_snapshots(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    app_version TEXT,
                    snapshot_json TEXT
                );
                CREATE TABLE IF NOT EXISTS validation_reports(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    path TEXT,
                    kind TEXT
                );
                """
            )
            conn.commit()
        finally:
            conn.close()

    # -------------------------------------------------------- reference pairs
    def add_reference_pair(self, metric: str, sensor_value: float, reference_value: float,
                           subject_id: str = "", condition: str = "", notes: str = "",
                           session_id: int | None = None, quality_flag: str = "") -> int:
        conn = self._connect()
        try:
            cur = conn.execute(
                "INSERT INTO reference_pairs(ts, subject_id, session_id, metric, sensor_value, "
                "reference_value, condition, quality_flag, notes) VALUES(?,?,?,?,?,?,?,?,?)",
                (time.time(), subject_id, session_id, metric, sensor_value, reference_value,
                 condition, quality_flag, notes),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def reference_pairs(self, metric: str | None = None, limit: int = 500) -> List[dict]:
        conn = self._connect()
        try:
            if metric:
                rows = conn.execute(
                    "SELECT * FROM reference_pairs WHERE metric=? ORDER BY ts DESC LIMIT ?",
                    (metric, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM reference_pairs ORDER BY ts DESC LIMIT ?", (limit,)
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def reference_metrics(self) -> List[str]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT DISTINCT metric FROM reference_pairs ORDER BY metric").fetchall()
            return [r[0] for r in rows]
        finally:
            conn.close()

    def clear_reference_pairs(self) -> None:
        conn = self._connect()
        try:
            conn.execute("DELETE FROM reference_pairs")
            conn.commit()
        finally:
            conn.close()

    # -------------------------------------------------------- model snapshots
    def add_snapshot(self, snapshot: Dict[str, Any]) -> int:
        conn = self._connect()
        try:
            cur = conn.execute(
                "INSERT INTO model_snapshots(ts, app_version, snapshot_json) VALUES(?,?,?)",
                (time.time(), str(snapshot.get("app_version", "")), json.dumps(snapshot)),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def latest_snapshot(self) -> Optional[dict]:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM model_snapshots ORDER BY ts DESC LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            d = dict(row)
            try:
                d["snapshot"] = json.loads(d.pop("snapshot_json", "{}"))
            except Exception:
                d["snapshot"] = {}
            return d
        finally:
            conn.close()

    # -------------------------------------------------------- prospective
    def add_prediction(self, subject_id: str, model_version: str, risk: float,
                       ci_low: float | None = None, ci_high: float | None = None,
                       confidence: float | None = None, sqi: float | None = None) -> int:
        conn = self._connect()
        try:
            cur = conn.execute(
                "INSERT INTO prospective_predictions(ts, subject_id, model_version, risk, "
                "ci_low, ci_high, confidence, sqi) VALUES(?,?,?,?,?,?,?,?)",
                (time.time(), subject_id, model_version, risk, ci_low, ci_high, confidence, sqi),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def set_outcome(self, prediction_id: int, outcome: int) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE prospective_predictions SET outcome=?, outcome_ts=? WHERE id=?",
                (1 if outcome else 0, time.time(), prediction_id),
            )
            conn.commit()
        finally:
            conn.close()

    def predictions(self, with_outcome: bool | None = None, limit: int = 500) -> List[dict]:
        conn = self._connect()
        try:
            if with_outcome is True:
                rows = conn.execute(
                    "SELECT * FROM prospective_predictions WHERE outcome IS NOT NULL ORDER BY ts DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            elif with_outcome is False:
                rows = conn.execute(
                    "SELECT * FROM prospective_predictions WHERE outcome IS NULL ORDER BY ts DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM prospective_predictions ORDER BY ts DESC LIMIT ?", (limit,)
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # -------------------------------------------------------- reports
    def log_report(self, path: str, kind: str = "validation") -> None:
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO validation_reports(ts, path, kind) VALUES(?,?,?)",
                (time.time(), path, kind),
            )
            conn.commit()
        finally:
            conn.close()

    def reports(self, limit: int = 50) -> List[dict]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM validation_reports ORDER BY ts DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

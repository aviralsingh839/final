"""Local offline database (SQLite) for CHRONO-PCOS.

Powers session recording, feature history, calibration history, anomaly
logging, data-quality logging and error/fault logging. Everything stays on the
local machine - nothing is transmitted anywhere. SQLite is used via the Python
standard library, so no extra dependency is required.

Threading note: all writes happen from the Qt main thread (UI timers/handlers).
Connections are opened per call so other threads (e.g. a future CLI) can safely
use the store too.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from src.config import DATA_DIR


class HistoryStore:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else DATA_DIR / "chrono_pcos.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    # ------------------------------------------------------------ schema
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
                CREATE TABLE IF NOT EXISTS sessions(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at REAL NOT NULL,
                    ended_at REAL,
                    source TEXT,
                    sample_count INTEGER DEFAULT 0,
                    note TEXT,
                    participant_id TEXT
                );
                CREATE TABLE IF NOT EXISTS features(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER,
                    ts REAL NOT NULL,
                    hr REAL, rmssd REAL, spo2 REAL, skin_temp REAL,
                    gsr REAL, motion REAL, activity REAL, stress REAL,
                    sleep_prob REAL, circadian REAL, risk REAL,
                    anomaly REAL, signal_quality REAL,
                    extra_json TEXT
                );
                CREATE TABLE IF NOT EXISTS calibrations(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    duration_s REAL,
                    quality REAL,
                    stats_json TEXT
                );
                CREATE TABLE IF NOT EXISTS anomalies(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER,
                    ts REAL NOT NULL,
                    signal TEXT,
                    value REAL,
                    expected_low REAL,
                    expected_high REAL,
                    severity REAL,
                    description TEXT
                );
                CREATE TABLE IF NOT EXISTS quality_log(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER,
                    ts REAL NOT NULL,
                    level TEXT,
                    metric TEXT,
                    message TEXT
                );
                CREATE TABLE IF NOT EXISTS error_log(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER,
                    ts REAL NOT NULL,
                    level TEXT,
                    message TEXT
                );
                CREATE TABLE IF NOT EXISTS events(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER,
                    ts REAL NOT NULL,
                    kind TEXT,
                    detail TEXT
                );
                -- V5 manual / clinical inputs (sections 7, 12, 26).
                CREATE TABLE IF NOT EXISTS bp_readings(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    systolic REAL, diastolic REAL, pulse REAL,
                    source TEXT, note TEXT
                );
                CREATE TABLE IF NOT EXISTS glucose_readings(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    value REAL, unit TEXT DEFAULT 'mg/dL',
                    context TEXT, note TEXT
                );
                CREATE TABLE IF NOT EXISTS weight_readings(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    weight_kg REAL, note TEXT
                );
                CREATE TABLE IF NOT EXISTS symptoms(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    symptom TEXT, severity INTEGER, note TEXT
                );
                CREATE TABLE IF NOT EXISTS menstrual_cycle(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    cycle_day INTEGER, cycle_length INTEGER,
                    bleeding INTEGER, symptoms TEXT, note TEXT
                );
                CREATE TABLE IF NOT EXISTS ultrasound_observations(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    cyst_size_mm REAL, volume_cc REAL,
                    morphology TEXT, septations INTEGER,
                    solid_components INTEGER, free_fluid INTEGER,
                    source TEXT, summary TEXT
                );
                -- V6.2 care-plan + clinical-record tables.
                CREATE TABLE IF NOT EXISTS care_medications(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    name TEXT NOT NULL,
                    dose TEXT, unit TEXT,
                    cadence TEXT DEFAULT 'daily',   -- daily | twice_daily | weekly | as_needed | custom
                    time_of_day TEXT DEFAULT 'any', -- morning | evening | night | any
                    start_ts REAL, end_ts REAL,
                    food_instruction TEXT, note TEXT,
                    active INTEGER DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS medication_log(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    medication_id INTEGER,
                    status TEXT NOT NULL,  -- taken | skipped | snoozed
                    note TEXT
                );
                CREATE TABLE IF NOT EXISTS care_goals(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    goal TEXT NOT NULL,
                    target_text TEXT,
                    kind TEXT DEFAULT 'lifestyle', -- activity | sleep | lifestyle | test
                    active INTEGER DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS appointments(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    kind TEXT DEFAULT 'appointment', -- appointment | test | checkup
                    due_ts REAL,
                    note TEXT,
                    done INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS clinical_notes(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    note TEXT NOT NULL,
                    clinician TEXT
                );
                CREATE TABLE IF NOT EXISTS visits(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    summary TEXT NOT NULL,
                    clinician TEXT
                );
                CREATE TABLE IF NOT EXISTS reports(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    kind TEXT DEFAULT 'periodic',
                    participant TEXT,
                    text TEXT,
                    metrics_json TEXT
                );
                -- V8.1 ultrasound image records (path only, never the image
                -- bytes; provenance + quality kept for the CV pipeline).
                CREATE TABLE IF NOT EXISTS ultrasound_images(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    image_path TEXT NOT NULL,
                    quality_ok INTEGER,
                    quality_notes TEXT,
                    features_json TEXT,
                    provenance TEXT DEFAULT 'IMAGE-DERIVED',
                    source TEXT DEFAULT 'file'
                );
                -- V8.1 QR report-access tokens: a randomized de-identified
                -- record identifier only — never patient-identifying data.
                CREATE TABLE IF NOT EXISTS report_tokens(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token TEXT NOT NULL UNIQUE,
                    report_id INTEGER,
                    created_ts REAL NOT NULL,
                    expires_ts REAL,
                    note TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_features_ts ON features(ts);
                CREATE INDEX IF NOT EXISTS idx_ultrasound_images_ts ON ultrasound_images(ts);
                CREATE INDEX IF NOT EXISTS idx_report_tokens_token ON report_tokens(token);
                CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
                CREATE INDEX IF NOT EXISTS idx_med_log_ts ON medication_log(ts);
                CREATE INDEX IF NOT EXISTS idx_reports_ts ON reports(ts);
                """
            )
            conn.commit()
            # Migrations for older databases.
            self._ensure_column(conn, "features", "extra_json", "TEXT")
            self._ensure_column(conn, "sessions", "participant_id", "TEXT")
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _ensure_column(conn, table: str, column: str, ddl: str) -> None:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    # ----------------------------------------------------------- sessions
    def start_session(self, source: str = "demo", note: str = "", participant_id: str | None = None) -> int:
        conn = self._connect()
        try:
            cur = conn.execute(
                "INSERT INTO sessions(started_at, source, note, participant_id) VALUES(?,?,?,?)",
                (time.time(), source, note, participant_id),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def end_session(self, session_id: int, sample_count: int = 0) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE sessions SET ended_at=?, sample_count=? WHERE id=?",
                (time.time(), sample_count, session_id),
            )
            conn.commit()
        finally:
            conn.close()

    # ----------------------------------------------------------- features
    def log_feature(self, session_id: int, row: Dict[str, Any], extra_json: str | None = None) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO features(session_id, ts, hr, rmssd, spo2, skin_temp, gsr, motion, activity, stress, sleep_prob, circadian, risk, anomaly, signal_quality, extra_json)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    session_id,
                    row.get("ts", time.time()),
                    row.get("hr"), row.get("rmssd"), row.get("spo2"), row.get("skin_temp"),
                    row.get("gsr"), row.get("motion"), row.get("activity"), row.get("stress"),
                    row.get("sleep_prob"), row.get("circadian"), row.get("risk"),
                    row.get("anomaly"), row.get("signal_quality"),
                    extra_json,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def features_as_frame(self, since: float | None = None, days: int = 30,
                          include_demo: bool = True) -> pd.DataFrame:
        """Feature rows as a DataFrame.

        `include_demo=False` excludes sessions whose source is 'demo' or
        'synthetic', so simulated data can never leak into live analysis.
        (Rows with no session are kept.)
        """
        conn = self._connect()
        try:
            conds: list[str] = []
            params: list[float] = []
            if since is not None:
                conds.append("f.ts >= ?")
                params.append(since)
            elif days:
                conds.append("f.ts >= ?")
                params.append(time.time() - days * 86400.0)
            if not include_demo:
                conds.append("(f.session_id IS NULL OR s.source NOT IN ('demo','synthetic'))")
            q = "SELECT f.* FROM features f LEFT JOIN sessions s ON s.id = f.session_id"
            if conds:
                q += " WHERE " + " AND ".join(conds)
            q += " ORDER BY f.ts"
            return pd.read_sql_query(q, conn, params=tuple(params))
        finally:
            conn.close()

    def coverage_days(self, days: int = 90, include_demo: bool = True) -> int:
        """Number of distinct calendar days that have at least one feature row."""
        df = self.features_as_frame(days=days, include_demo=include_demo)
        if df.empty:
            return 0
        dt = pd.to_datetime(df["ts"], unit="s")
        return int(dt.dt.strftime("%Y-%m-%d").nunique())

    def export_features_csv(self, path: Path | str, days: int = 30, include_demo: bool = True) -> int:
        df = self.features_as_frame(days=days, include_demo=include_demo)
        df.to_csv(path, index=False)
        return len(df)

    def features_for_session(self, session_id: int) -> pd.DataFrame:
        conn = self._connect()
        try:
            return pd.read_sql_query(
                "SELECT * FROM features WHERE session_id=? ORDER BY ts", conn, params=(session_id,)
            )
        finally:
            conn.close()

    # -------------------------------------------------------- calibration
    def log_calibration(self, duration_s: float, quality: float, stats_json: str) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO calibrations(ts, duration_s, quality, stats_json) VALUES(?,?,?,?)",
                (time.time(), duration_s, quality, stats_json),
            )
            conn.commit()
        finally:
            conn.close()

    def calibration_history(self, limit: int = 100) -> List[dict]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM calibrations ORDER BY ts DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ---------------------------------------------------------- anomalies
    def log_anomaly(self, session_id: int | None, ts: float, anomaly: Any) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO anomalies(session_id, ts, signal, value, expected_low, expected_high, severity, description)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (session_id, ts, anomaly.signal, anomaly.value, anomaly.expected_low,
                 anomaly.expected_high, anomaly.severity, anomaly.description),
            )
            conn.commit()
        finally:
            conn.close()

    def anomalies(self, limit: int = 200) -> List[dict]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM anomalies ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ------------------------------------------------------- quality/error
    def log_quality(self, session_id: int | None, level: str, metric: str, message: str) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO quality_log(session_id, ts, level, metric, message) VALUES(?,?,?,?,?)",
                (session_id, time.time(), level, metric, message),
            )
            conn.commit()
        finally:
            conn.close()

    def log_error(self, session_id: int | None, level: str, message: str) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO error_log(session_id, ts, level, message) VALUES(?,?,?,?)",
                (session_id, time.time(), level, message),
            )
            conn.commit()
        finally:
            conn.close()

    def quality_log(self, limit: int = 200) -> List[dict]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM quality_log ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def error_log(self, limit: int = 200) -> List[dict]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM error_log ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ------------------------------------------------------------- events
    def log_event(self, session_id: int | None, kind: str, detail: str = "") -> None:
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO events(session_id, ts, kind, detail) VALUES(?,?,?,?)",
                (session_id, time.time(), kind, detail),
            )
            conn.commit()
        finally:
            conn.close()

    def events(self, kind: str | None = None, limit: int = 200) -> List[dict]:
        conn = self._connect()
        try:
            if kind:
                rows = conn.execute(
                    "SELECT * FROM events WHERE kind=? ORDER BY ts DESC LIMIT ?", (kind, limit)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM events ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ---------------------------------------------------- manual inputs
    def log_bp(self, systolic: float, diastolic: float, pulse: float | None = None,
               source: str = "manual", note: str = "") -> None:
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO bp_readings(ts, systolic, diastolic, pulse, source, note) VALUES(?,?,?,?,?,?)",
                (time.time(), systolic, diastolic, pulse, source, note),
            )
            conn.commit()
        finally:
            conn.close()

    def bp_readings(self, limit: int = 200) -> List[dict]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM bp_readings ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def log_glucose(self, value: float, unit: str = "mg/dL", context: str = "unknown", note: str = "") -> None:
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO glucose_readings(ts, value, unit, context, note) VALUES(?,?,?,?,?)",
                (time.time(), value, unit, context, note),
            )
            conn.commit()
        finally:
            conn.close()

    def glucose_readings(self, limit: int = 200) -> List[dict]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM glucose_readings ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def log_weight(self, weight_kg: float, note: str = "") -> None:
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO weight_readings(ts, weight_kg, note) VALUES(?,?,?)",
                (time.time(), weight_kg, note),
            )
            conn.commit()
        finally:
            conn.close()

    def weight_readings(self, limit: int = 200) -> List[dict]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM weight_readings ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def log_symptom(self, symptom: str, severity: int, note: str = "") -> None:
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO symptoms(ts, symptom, severity, note) VALUES(?,?,?,?)",
                (time.time(), symptom, max(0, min(10, severity)), note),
            )
            conn.commit()
        finally:
            conn.close()

    def symptoms(self, limit: int = 200) -> List[dict]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM symptoms ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def log_cycle_entry(self, cycle_day: int | None = None, cycle_length: int | None = None,
                        bleeding: int | None = None, symptoms: str = "", note: str = "") -> None:
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO menstrual_cycle(ts, cycle_day, cycle_length, bleeding, symptoms, note) VALUES(?,?,?,?,?,?)",
                (time.time(), cycle_day, cycle_length, bleeding, symptoms, note),
            )
            conn.commit()
        finally:
            conn.close()

    def cycle_history(self, limit: int = 200) -> List[dict]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM menstrual_cycle ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def log_ultrasound(self, cyst_size_mm: float | None = None, volume_cc: float | None = None,
                       morphology: str = "", septations: int | None = None,
                       solid_components: int | None = None, free_fluid: int | None = None,
                       source: str = "manual", summary: str = "") -> None:
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO ultrasound_observations(ts, cyst_size_mm, volume_cc, morphology, "
                "septations, solid_components, free_fluid, source, summary) VALUES(?,?,?,?,?,?,?,?,?)",
                (time.time(), cyst_size_mm, volume_cc, morphology, septations,
                 solid_components, free_fluid, source, summary),
            )
            conn.commit()
        finally:
            conn.close()

    def ultrasound_history(self, limit: int = 200) -> List[dict]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM ultrasound_observations ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # -------------------------------------------------- ultrasound images
    def log_ultrasound_image(self, image_path: str, quality_ok: bool | None = None,
                             quality_notes: str = "", features_json: str = "",
                             provenance: str = "IMAGE-DERIVED",
                             source: str = "file") -> int:
        conn = self._connect()
        try:
            cur = conn.execute(
                "INSERT INTO ultrasound_images(ts, image_path, quality_ok, quality_notes, "
                "features_json, provenance, source) VALUES(?,?,?,?,?,?,?)",
                (time.time(), image_path, (1 if quality_ok else 0) if quality_ok is not None else None,
                 quality_notes, features_json, provenance, source),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def ultrasound_images(self, limit: int = 200) -> List[dict]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM ultrasound_images ORDER BY ts DESC LIMIT ?", (limit,)
            ).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                try:
                    d["features"] = json.loads(d.get("features_json") or "{}")
                except Exception:
                    d["features"] = {}
                out.append(d)
            return out
        finally:
            conn.close()

    # ------------------------------------------------------- report tokens
    def create_report_token(self, report_id: int | None = None,
                            note: str = "", ttl_days: float | None = None) -> str:
        """Issue a randomized de-identified report-access token.

        The token contains NO patient-identifying information; it is only a
        lookup key for a saved report. TTL defaults to 90 days.
        """
        import secrets

        token = "CP-" + secrets.token_hex(6).upper()  # e.g. CP-9F3A2B7C
        expires = time.time() + (ttl_days or 90.0) * 86400.0
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO report_tokens(token, report_id, created_ts, expires_ts, note)"
                " VALUES(?,?,?,?,?)",
                (token, report_id, time.time(), expires, note),
            )
            conn.commit()
            return token
        finally:
            conn.close()

    def resolve_report_token(self, token: str) -> Optional[dict]:
        """Look up a token; returns the report dict, or None when invalid/
        expired. Never exposes PII — the report itself is de-identified."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM report_tokens WHERE token=?", (token,)
            ).fetchone()
            if not row:
                return None
            d = dict(row)
            if d.get("expires_ts") and time.time() > float(d["expires_ts"]):
                return None
            if d.get("report_id") is None:
                return {"token": token, "report_id": None, "expired": False,
                        "error": "no report attached to this token"}
            return self.report_by_id(int(d["report_id"]))
        finally:
            conn.close()

    def report_tokens(self, limit: int = 200) -> List[dict]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM report_tokens ORDER BY created_ts DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ------------------------------------------------------------- health
    def row_counts(self) -> Dict[str, int]:
        conn = self._connect()
        try:
            out: Dict[str, int] = {}
            for table in ["sessions", "features", "calibrations", "anomalies", "quality_log", "error_log", "events",
                          "bp_readings", "glucose_readings", "weight_readings", "symptoms",
                          "menstrual_cycle", "ultrasound_observations",
                          "ultrasound_images", "report_tokens"]:
                out[table] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            return out
        finally:
            conn.close()

    def session_summary(self, session_id: int | None = None, limit: int = 20) -> List[dict]:
        conn = self._connect()
        try:
            if session_id is not None:
                rows = conn.execute("SELECT * FROM sessions WHERE id=? ORDER BY started_at DESC", (session_id,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM sessions ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def session_compare(self, limit: int = 20) -> List[dict]:
        """Per-session stats for comparison: duration, sample count, mean risk, risk trend."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT s.id, s.started_at, s.ended_at, s.source, s.participant_id, s.sample_count, "
                "       COUNT(f.id) AS n_features, AVG(f.risk) AS mean_risk, MIN(f.risk) AS min_risk, MAX(f.risk) AS max_risk "
                "FROM sessions s LEFT JOIN features f ON f.session_id = s.id "
                "GROUP BY s.id ORDER BY s.started_at DESC LIMIT ?", (limit,)
            ).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                if d.get("ended_at") and d.get("started_at"):
                    d["duration_min"] = round((d["ended_at"] - d["started_at"]) / 60.0, 1)
                else:
                    d["duration_min"] = None
                out.append(d)
            return out
        finally:
            conn.close()

    def risk_at_time(self, ts: float) -> Optional[float]:
        """Nearest logged risk value to the given timestamp (for before/after comparisons)."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT risk FROM features WHERE risk IS NOT NULL ORDER BY ABS(ts - ?) LIMIT 1", (ts,)
            ).fetchone()
            return float(row[0]) if row else None
        finally:
            conn.close()

    # ------------------------------------------------------- manual vitals
    def log_manual_vitals(self, hr: float | None = None, rmssd: float | None = None,
                          skin_temp: float | None = None, activity: float | None = None,
                          gsr: float | None = None, note: str = "") -> int:
        """Record manually entered wearable-style values as a real (non-demo)
        feature row, so the longitudinal engine can run without any hardware.

        A session with source='manual' is reused while it stays open.
        Returns the session id used.
        """
        now = time.time()
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT id FROM sessions WHERE source='manual' AND ended_at IS NULL ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
            if row:
                sid = int(row[0])
            else:
                sid = int(conn.execute(
                    "INSERT INTO sessions(started_at, source, note) VALUES(?, 'manual', ?)",
                    (now, note or "manual vitals"),
                ).lastrowid)
            conn.execute(
                "INSERT INTO features(session_id, ts, hr, rmssd, skin_temp, gsr, activity, signal_quality)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (sid, now, hr, rmssd, skin_temp, gsr, activity, 0.8),
            )
            conn.commit()
            return sid
        finally:
            conn.close()

    # --------------------------------------------------------- care plan
    def add_medication(self, name: str, dose: str = "", unit: str = "",
                       cadence: str = "daily", time_of_day: str = "any",
                       start_ts: float | None = None, end_ts: float | None = None,
                       food_instruction: str = "", note: str = "") -> int:
        conn = self._connect()
        try:
            cur = conn.execute(
                "INSERT INTO care_medications(ts, name, dose, unit, cadence, time_of_day, start_ts, end_ts, food_instruction, note, active)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,1)",
                (time.time(), name, dose, unit, cadence, time_of_day, start_ts, end_ts, food_instruction, note),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def medications(self, active_only: bool = True, limit: int = 200) -> List[dict]:
        conn = self._connect()
        try:
            q = "SELECT * FROM care_medications"
            if active_only:
                q += " WHERE active=1"
            q += " ORDER BY ts DESC LIMIT ?"
            rows = conn.execute(q, (limit,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def set_medication_active(self, medication_id: int, active: bool) -> None:
        conn = self._connect()
        try:
            conn.execute("UPDATE care_medications SET active=? WHERE id=?", (1 if active else 0, medication_id))
            conn.commit()
        finally:
            conn.close()

    def log_medication(self, medication_id: int | None, status: str, note: str = "") -> None:
        if status not in ("taken", "skipped", "snoozed"):
            raise ValueError(f"unknown medication status: {status}")
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO medication_log(ts, medication_id, status, note) VALUES(?,?,?,?)",
                (time.time(), medication_id, status, note),
            )
            conn.commit()
        finally:
            conn.close()

    def medication_log(self, limit: int = 500) -> List[dict]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM medication_log ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def add_goal(self, goal: str, target_text: str = "", kind: str = "lifestyle") -> int:
        conn = self._connect()
        try:
            cur = conn.execute(
                "INSERT INTO care_goals(ts, goal, target_text, kind, active) VALUES(?,?,?,?,1)",
                (time.time(), goal, target_text, kind),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def goals(self, active_only: bool = True, limit: int = 100) -> List[dict]:
        conn = self._connect()
        try:
            q = "SELECT * FROM care_goals"
            if active_only:
                q += " WHERE active=1"
            q += " ORDER BY ts DESC LIMIT ?"
            return [dict(r) for r in conn.execute(q, (limit,)).fetchall()]
        finally:
            conn.close()

    def set_goal_active(self, goal_id: int, active: bool) -> None:
        conn = self._connect()
        try:
            conn.execute("UPDATE care_goals SET active=? WHERE id=?", (1 if active else 0, goal_id))
            conn.commit()
        finally:
            conn.close()

    def add_appointment(self, kind: str = "appointment", due_ts: float | None = None,
                        note: str = "") -> int:
        conn = self._connect()
        try:
            cur = conn.execute(
                "INSERT INTO appointments(ts, kind, due_ts, note, done) VALUES(?,?,?,?,0)",
                (time.time(), kind, due_ts, note),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def appointments(self, limit: int = 200) -> List[dict]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM appointments ORDER BY due_ts IS NULL, due_ts ASC, ts DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def mark_appointment_done(self, appointment_id: int) -> None:
        conn = self._connect()
        try:
            conn.execute("UPDATE appointments SET done=1 WHERE id=?", (appointment_id,))
            conn.commit()
        finally:
            conn.close()

    # ---------------------------------------------------- clinical record
    def add_clinical_note(self, note: str, clinician: str = "") -> int:
        conn = self._connect()
        try:
            cur = conn.execute(
                "INSERT INTO clinical_notes(ts, note, clinician) VALUES(?,?,?)",
                (time.time(), note, clinician),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def clinical_notes(self, limit: int = 200) -> List[dict]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM clinical_notes ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def add_visit(self, summary: str, clinician: str = "") -> int:
        conn = self._connect()
        try:
            cur = conn.execute(
                "INSERT INTO visits(ts, summary, clinician) VALUES(?,?,?)",
                (time.time(), summary, clinician),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def visits(self, limit: int = 100) -> List[dict]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM visits ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def save_report(self, kind: str, participant: str, text: str,
                    metrics: Dict[str, Any] | None = None) -> int:
        conn = self._connect()
        try:
            cur = conn.execute(
                "INSERT INTO reports(ts, kind, participant, text, metrics_json) VALUES(?,?,?,?,?)",
                (time.time(), kind, participant, text, json.dumps(metrics or {})),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def reports(self, limit: int = 200) -> List[dict]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM reports ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                try:
                    d["metrics"] = json.loads(d.get("metrics_json") or "{}")
                except Exception:
                    d["metrics"] = {}
                out.append(d)
            return out
        finally:
            conn.close()

    def report_by_id(self, report_id: int) -> Optional[dict]:
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
            if not row:
                return None
            d = dict(row)
            try:
                d["metrics"] = json.loads(d.get("metrics_json") or "{}")
            except Exception:
                d["metrics"] = {}
            return d
        finally:
            conn.close()

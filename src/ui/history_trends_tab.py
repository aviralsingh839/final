"""History + Trends tab (features 16/17/18/54): 7-day profile, trajectory,
session comparison, weekly report and replay actions."""
from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.models.multi_day import WeeklyProfile
from src.ui.theme import style_plot

METRIC_OPTIONS = [
    ("Mean heart rate (bpm)", "mean_hr"),
    ("Resting HR daytime (bpm)", "resting_hr"),
    ("Mean HRV RMSSD (ms)", "rmssd"),
    ("Mean SpO₂ (%)", "spo2"),
    ("Temperature amplitude (°C)", "temp_amp"),
    ("Mean activity (0-100)", "activity"),
    ("Night sleep probability (%)", "night_sleep"),
    ("Circadian stability (%)", "circadian"),
    ("Daily health score", "health"),
    ("Light exposure score", "light"),
    ("Mean stress index (%)", "stress"),
    ("Mean risk (%)", "risk"),
    ("Anomaly count", "anomalies"),
]

COLUMNS = [
    ("date", "Date"),
    ("samples", "Samples"),
    ("mean_hr", "HR"),
    ("resting_hr", "Rest HR"),
    ("rmssd", "RMSSD"),
    ("spo2", "SpO₂"),
    ("temp_amp", "Temp amp"),
    ("activity", "Activity"),
    ("night_sleep", "Night sleep"),
    ("circadian", "Circadian"),
    ("health", "Health"),
    ("stress", "Stress"),
    ("risk", "Risk"),
    ("anomalies", "Anomalies"),
]

SESSION_COLUMNS = [
    ("id", "ID"), ("participant_id", "Participant"), ("source", "Source"),
    ("started_at", "Started"), ("duration_min", "Min"), ("n_features", "Features"),
    ("mean_risk", "Mean risk"), ("min_risk", "Min risk"), ("max_risk", "Max risk"),
]


class HistoryTrendsTab(QWidget):
    load_demo_week = Signal()
    replay_latest = Signal()
    report_pdf = Signal()
    report_text = Signal()
    export_json = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QHBoxLayout(self)

        left = QVBoxLayout()
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Metric"))
        self.metric_combo = QComboBox()
        for label, _key in METRIC_OPTIONS:
            self.metric_combo.addItem(label)
        self.metric_combo.currentIndexChanged.connect(self._redraw_plot)
        controls.addWidget(self.metric_combo, 1)
        left.addLayout(controls)

        self.plot = pg.PlotWidget()
        style_plot(self.plot, y_label="value", x_label="day")
        self.curve = self.plot.plot(pen=pg.mkPen("#3aa7f0", width=2), symbol="o", symbolSize=7,
                                    symbolBrush="#3aa7f0", symbolPen=pg.mkPen("#0d1626"))
        left.addWidget(self.plot, 1)

        self.trajectory_label = QLabel("Collect at least 3 days of data to see a trajectory.")
        self.trajectory_label.setWordWrap(True)
        self.trajectory_label.setObjectName("SmallMuted")
        left.addWidget(self.trajectory_label)

        self.before_after_label = QLabel("")
        self.before_after_label.setWordWrap(True)
        self.before_after_label.setObjectName("WarningText")
        left.addWidget(self.before_after_label)

        actions = QHBoxLayout()
        for text, signal in [
            ("Load demo week", self.load_demo_week),
            ("Replay latest session", self.replay_latest),
            ("Weekly report (PDF)", self.report_pdf),
            ("Report (text)", self.report_text),
            ("Export JSON", self.export_json),
        ]:
            b = QPushButton(text)
            b.clicked.connect(signal)
            actions.addWidget(b)
        left.addLayout(actions)
        outer.addLayout(left, 2)

        right = QVBoxLayout()
        table_box = QGroupBox("7-Day Physiological Profile")
        tb = QVBoxLayout(table_box)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([c[1] for c in COLUMNS])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        tb.addWidget(self.table)
        right.addWidget(table_box, 1)

        sessions_box = QGroupBox("Session Comparison")
        sb = QVBoxLayout(sessions_box)
        self.session_table = QTableWidget(0, len(SESSION_COLUMNS))
        self.session_table.setHorizontalHeaderLabels([c[1] for c in SESSION_COLUMNS])
        self.session_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        sb.addWidget(self.session_table)
        right.addWidget(sessions_box, 1)
        outer.addLayout(right, 1)

        self._profile = WeeklyProfile()

    def refresh(self, profile: WeeklyProfile) -> None:
        self._profile = profile
        self._fill_table()
        self._redraw_plot()

    def set_sessions(self, sessions) -> None:
        self.session_table.setRowCount(len(sessions))
        for r, s in enumerate(sessions):
            import time as _t

            started = _t.strftime("%m-%d %H:%M", _t.localtime(s["started_at"])) if s.get("started_at") else "-"
            row_vals = {
                "id": s.get("id"), "participant_id": s.get("participant_id") or "-",
                "source": s.get("source") or "-", "started_at": started,
                "duration_min": s.get("duration_min"), "n_features": s.get("n_features"),
                "mean_risk": s.get("mean_risk"), "min_risk": s.get("min_risk"), "max_risk": s.get("max_risk"),
            }
            for c, (key, _label) in enumerate(SESSION_COLUMNS):
                v = row_vals.get(key)
                text = "-" if v is None else (f"{v:.1f}" if isinstance(v, float) else str(v))
                self.session_table.setItem(r, c, QTableWidgetItem(text))
        self.session_table.resizeColumnsToContents()

    def set_before_after(self, old_risk: float, new_risk: float, ts: float) -> None:
        import time as _t

        when = _t.strftime("%H:%M", _t.localtime(ts))
        delta = new_risk - old_risk
        self.before_after_label.setText(
            f"Recommendation effectiveness: risk was {old_risk:.1f}% when advice was "
            f"issued ({when}); now {new_risk:.1f}% ({delta:+.1f} points)."
        )

    def _fill_table(self) -> None:
        rows = [d.as_dict() for d in self._profile.days]
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, (key, _label) in enumerate(COLUMNS):
                val = row.get(key)
                text = "" if val is None else (f"{val:.1f}" if isinstance(val, float) else str(val))
                self.table.setItem(r, c, QTableWidgetItem(text))
        self.table.resizeColumnsToContents()

    def _redraw_plot(self) -> None:
        _, key = METRIC_OPTIONS[self.metric_combo.currentIndex()]
        series = self._profile.metric_series(key)
        x = [i for i, v in enumerate(series) if v is not None]
        y = [v for v in series if v is not None]
        if len(x) >= 2:
            self.curve.setData(x, y)
            self.plot.setLabel("bottom", "day (0 = oldest)")
        else:
            self.curve.setData([], [])
            self.plot.setLabel("bottom", "day")

        traj = self._profile.trajectory
        if traj:
            parts = []
            for label, key2 in [("HR", "mean_hr"), ("RMSSD", "rmssd"), ("temp amp", "temp_amp"),
                                ("night sleep", "night_sleep"), ("circadian", "circadian"),
                                ("health", "health"), ("risk", "risk")]:
                if key2 in traj:
                    parts.append(f"{label}: {traj[key2]:+.2f}/day")
            self.trajectory_label.setText("Trajectory (slope per day, up to 30 days): " + "; ".join(parts))
        else:
            self.trajectory_label.setText("Collect at least 3 days of data to see a trajectory.")

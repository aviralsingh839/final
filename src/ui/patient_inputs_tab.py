"""V6 Patient Inputs tab.

Low-burden manual inputs: menstrual cycle, symptoms, BP, glucose, weight.
Everything is written to the local SQLite store and can be applied to the
live UserProfile. Nothing here pretends to be measured by the wearable; these
are optional, user-entered, timestamped records.

Cycle phase is never invented from unreliable information — only what the user
enters is used (and the risk engine treats missing cycle data as "unknown").
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.config import UserProfile
from src.utils.history_store import HistoryStore

SYMPTOM_OPTIONS = ["Pain", "Hair growth", "Acne", "Weight change", "Fatigue", "Other"]


class PatientInputsTab(QWidget):
    """Cycle / symptom / BP / glucose / weight entry (≤ a few taps per day)."""

    inputs_saved = Signal()

    def __init__(self, store: HistoryStore, parent=None):
        super().__init__(parent)
        self.store = store
        outer = QHBoxLayout(self)

        # ---------------------------------------------------------- cycle
        cycle_box = QGroupBox("Menstrual cycle (optional, self-reported)")
        cb = QVBoxLayout(cycle_box)

        row = QHBoxLayout()
        self.cycle_day_spin = QSpinBox()
        self.cycle_day_spin.setRange(0, 120)
        self.cycle_day_spin.setSpecialValueText("unknown")
        row.addWidget(QLabel("Cycle day")); row.addWidget(self.cycle_day_spin)
        self.cycle_length_spin = QSpinBox()
        self.cycle_length_spin.setRange(0, 120)
        self.cycle_length_spin.setSpecialValueText("unknown")
        row.addWidget(QLabel("Usual length (days)")); row.addWidget(self.cycle_length_spin)
        cb.addLayout(row)

        self.period_btn = QPushButton("Period started today")
        self.period_btn.clicked.connect(self._period_today)
        cb.addWidget(self.period_btn)

        self.irregular_cb = QCheckBox("My cycle is irregular / often late (> 35 days)")
        cb.addWidget(self.irregular_cb)

        cb.addWidget(QLabel("Symptoms today (tap all that apply):"))
        self.symptom_cbs: dict[str, QCheckBox] = {}
        sym_row = QHBoxLayout()
        for name in SYMPTOM_OPTIONS:
            w = QCheckBox(name)
            self.symptom_cbs[name] = w
            sym_row.addWidget(w)
        cb.addLayout(sym_row)

        med_row = QHBoxLayout()
        med_row.addWidget(QLabel("Medication (optional):"))
        self.medication_edit = QLineEdit()
        self.medication_edit.setPlaceholderText("e.g. metformin / OCP / none")
        med_row.addWidget(self.medication_edit, 1)
        cb.addLayout(med_row)

        save_cycle = QPushButton("Save cycle entry")
        save_cycle.clicked.connect(self._save_cycle)
        cb.addWidget(save_cycle)
        cb.addWidget(QLabel(
            "Cycle information is the strongest self-reported signal in the model. "
            "It is never inferred from sensors."))

        # -------------------------------------------------------------- BP
        bp_box = QGroupBox("Blood pressure (optional, manual cuff)")
        bb = QVBoxLayout(bp_box)
        bp_row = QHBoxLayout()
        self.sys_spin = QDoubleSpinBox(); self.sys_spin.setRange(0, 260); self.sys_spin.setSpecialValueText("none")
        self.dia_spin = QDoubleSpinBox(); self.dia_spin.setRange(0, 200); self.dia_spin.setSpecialValueText("none")
        self.pulse_spin = QDoubleSpinBox(); self.pulse_spin.setRange(0, 220); self.pulse_spin.setSpecialValueText("none")
        bp_row.addWidget(QLabel("SYS")); bp_row.addWidget(self.sys_spin)
        bp_row.addWidget(QLabel("DIA")); bp_row.addWidget(self.dia_spin)
        bp_row.addWidget(QLabel("Pulse")); bp_row.addWidget(self.pulse_spin)
        bb.addLayout(bp_row)
        self.bp_source = QComboBox()
        self.bp_source.addItems(["home cuff", "clinic", "pharmacy"])
        bb.addWidget(self.bp_source)
        save_bp = QPushButton("Save BP")
        save_bp.clicked.connect(self._save_bp)
        bb.addWidget(save_bp)

        # ---------------------------------------------------------- glucose
        glu_box = QGroupBox("Glucose (optional, manual meter)")
        gb = QVBoxLayout(glu_box)
        g_row = QHBoxLayout()
        self.glucose_spin = QDoubleSpinBox(); self.glucose_spin.setRange(0, 500); self.glucose_spin.setSpecialValueText("none"); self.glucose_spin.setSuffix(" mg/dL")
        self.glucose_context = QComboBox()
        self.glucose_context.addItems(["fasting", "2hr post-meal", "random", "unknown"])
        g_row.addWidget(self.glucose_spin); g_row.addWidget(self.glucose_context)
        gb.addLayout(g_row)
        save_glu = QPushButton("Save glucose")
        save_glu.clicked.connect(self._save_glucose)
        gb.addWidget(save_glu)

        # ---------------------------------------------------------- weight
        wt_box = QGroupBox("Weight (optional)")
        wb = QVBoxLayout(wt_box)
        w_row = QHBoxLayout()
        self.weight_spin = QDoubleSpinBox(); self.weight_spin.setRange(0, 250); self.weight_spin.setSpecialValueText("none"); self.weight_spin.setSuffix(" kg")
        w_row.addWidget(self.weight_spin)
        wb.addLayout(w_row)
        save_wt = QPushButton("Save weight")
        save_wt.clicked.connect(self._save_weight)
        wb.addWidget(save_wt)

        # -------------------------------------------- manual wearable-style
        mv_box = QGroupBox("Manual wearable-style readings (hardware-agnostic entry)")
        mb = QVBoxLayout(mv_box)
        mr = QHBoxLayout()
        self.mv_hr = QDoubleSpinBox(); self.mv_hr.setRange(0, 220); self.mv_hr.setSpecialValueText("none"); self.mv_hr.setSuffix(" bpm")
        self.mv_rmssd = QDoubleSpinBox(); self.mv_rmssd.setRange(0, 300); self.mv_rmssd.setSpecialValueText("none"); self.mv_rmssd.setSuffix(" ms")
        self.mv_temp = QDoubleSpinBox(); self.mv_temp.setRange(0, 45); self.mv_temp.setDecimals(1); self.mv_temp.setSpecialValueText("none"); self.mv_temp.setSuffix(" °C")
        self.mv_activity = QDoubleSpinBox(); self.mv_activity.setRange(0, 100); self.mv_activity.setSpecialValueText("none"); self.mv_activity.setSuffix(" %")
        mr.addWidget(QLabel("HR")); mr.addWidget(self.mv_hr)
        mr.addWidget(QLabel("HRV")); mr.addWidget(self.mv_rmssd)
        mr.addWidget(QLabel("Temp")); mr.addWidget(self.mv_temp)
        mr.addWidget(QLabel("Activity")); mr.addWidget(self.mv_activity)
        save_mv = QPushButton("Log manual readings")
        save_mv.clicked.connect(self._save_manual_vitals)
        mr.addWidget(save_mv)
        mb.addLayout(mr)
        mv_note = QLabel(
            "For values from any compatible wearable, cuff monitor or manual measurement. "
            "Logged as a real (non-demo) timestamped record so the longitudinal engine runs "
            "even without CHRONO hardware.")
        mv_note.setWordWrap(True)
        mv_note.setObjectName("SmallMuted")
        mb.addWidget(mv_note)

        left = QVBoxLayout()
        left.addWidget(cycle_box, 2)
        left.addWidget(bp_box)
        left.addWidget(glu_box)
        left.addWidget(wt_box)
        left.addWidget(mv_box)
        left.addStretch(1)
        outer.addLayout(left, 2)

        # -------------------------------------------------------- history
        right = QVBoxLayout()
        recent_box = QGroupBox("Recent cycle + symptom entries")
        rb = QVBoxLayout(recent_box)
        self.recent_table = QTableWidget(0, 4)
        self.recent_table.setHorizontalHeaderLabels(["When", "Cycle day", "Length", "Symptoms / note"])
        self.recent_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        rb.addWidget(self.recent_table)
        right.addWidget(recent_box, 3)
        note = QLabel("All entries are stored locally with a timestamp and are excluded from "
                      "live analysis only if the session is demo/synthetic. Nothing is uploaded.")
        note.setWordWrap(True)
        note.setObjectName("SmallMuted")
        right.addWidget(note)
        outer.addLayout(right, 1)

        self._refresh_recent()

    # ------------------------------------------------------------- actions
    def _period_today(self):
        self.cycle_day_spin.setValue(1)
        self._save_cycle(bleeding=1)

    def _checked_symptoms(self) -> list[str]:
        return [name for name, w in self.symptom_cbs.items() if w.isChecked()]

    def _save_cycle(self, bleeding: int | None = None):
        day = self.cycle_day_spin.value() or None
        length = self.cycle_length_spin.value() or None
        symptoms = ", ".join(self._checked_symptoms())
        note = self.medication_edit.text().strip()
        self.store.log_cycle_entry(cycle_day=day, cycle_length=length,
                                   bleeding=bleeding, symptoms=symptoms, note=note)
        for name in self._checked_symptoms():
            self.store.log_symptom(name, 1)
        self.inputs_saved.emit()
        self._refresh_recent()

    def _save_bp(self):
        sys = self.sys_spin.value() or None
        dia = self.dia_spin.value() or None
        if sys is None and dia is None:
            return
        pulse = self.pulse_spin.value() or None
        self.store.log_bp(sys, dia, pulse, source=self.bp_source.currentText())
        self.inputs_saved.emit()

    def _save_glucose(self):
        v = self.glucose_spin.value()
        if v <= 0:
            return
        self.store.log_glucose(v, context=self.glucose_context.currentText())
        self.inputs_saved.emit()

    def _save_weight(self):
        v = self.weight_spin.value()
        if v <= 0:
            return
        self.store.log_weight(v)
        self.inputs_saved.emit()

    def _save_manual_vitals(self):
        hr = self.mv_hr.value() or None
        rmssd = self.mv_rmssd.value() or None
        temp = self.mv_temp.value() or None
        activity = self.mv_activity.value() or None
        if hr is None and rmssd is None and temp is None and activity is None:
            return
        self.store.log_manual_vitals(hr=hr, rmssd=rmssd, skin_temp=temp, activity=activity)
        self.mv_hr.setValue(0); self.mv_rmssd.setValue(0)
        self.mv_temp.setValue(0); self.mv_activity.setValue(0)
        self.inputs_saved.emit()

    # -------------------------------------------------- profile integration
    def apply_to_profile(self, profile: UserProfile) -> UserProfile:
        """Copy the tab's cycle fields onto the live profile (in place)."""
        day = self.cycle_day_spin.value() or None
        length = self.cycle_length_spin.value() or None
        profile.cycle_day = day
        profile.usual_cycle_length_days = length
        profile.cycle_irregular = self.irregular_cb.isChecked() if self.irregular_cb.isChecked() else (
            False if length is not None else None)
        if self.sys_spin.value() > 0:
            profile.systolic_bp = self.sys_spin.value()
        if self.dia_spin.value() > 0:
            profile.diastolic_bp = self.dia_spin.value()
        if self.glucose_spin.value() > 0:
            profile.glucose_mg_dl = self.glucose_spin.value()
            profile.glucose_context = self.glucose_context.currentText()
        if self.weight_spin.value() > 0:
            profile.weight_kg = self.weight_spin.value()
        return profile

    # -------------------------------------------------------------- display
    def _refresh_recent(self):
        rows = self.store.cycle_history(limit=10)
        self.recent_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            import time as _t

            when = _t.strftime("%m-%d %H:%M", _t.localtime(row["ts"]))
            day = str(row["cycle_day"]) if row.get("cycle_day") else "-"
            length = str(row["cycle_length"]) if row.get("cycle_length") else "-"
            detail = ", ".join(x for x in [row.get("symptoms") or "", row.get("note") or ""] if x) or "-"
            for c, val in enumerate([when, day, length, detail]):
                self.recent_table.setItem(r, c, QTableWidgetItem(str(val)))
        self.recent_table.resizeColumnsToContents()

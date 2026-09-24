"""CARE & ADHERENCE tab (V6.2).

Records an existing clinician/user-entered care plan and adherence to it:
medications (with taken/skipped/snoozed logging), lifestyle goals, and
appointment/test reminders. Reminders are pure bookkeeping — the app NEVER
changes, starts, stops or prescribes medication. Adherence is summarized with
"potential care-plan gap" language, never blame.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.models.care_plan import CarePlanManager
from src.ui import theme
from src.ui.theme import GREEN, ORANGE, RED, TEXT_MUTED, YELLOW


class CarePlanTab(QWidget):
    data_changed = Signal()

    def __init__(self, care: CarePlanManager, parent=None):
        super().__init__(parent)
        self.care = care
        outer = QVBoxLayout(self)
        outer.setSpacing(10)

        # ------------------------------------------------------ reminders
        rem_box = QGroupBox("Reminders (from the recorded plan — bookkeeping only)")
        rb = QVBoxLayout(rem_box)
        self.reminders_text = QTextEdit()
        self.reminders_text.setReadOnly(True)
        self.reminders_text.setPlaceholderText("Due medication dose slots and upcoming appointments appear here.")
        rb.addWidget(self.reminders_text)
        outer.addWidget(rem_box)

        mid = QHBoxLayout()

        # ---------------------------------------------------- medications
        med_col = QVBoxLayout()
        form_box = QGroupBox("Add medication (enter an EXISTING prescribed plan)")
        fb = QVBoxLayout(form_box)
        r1 = QHBoxLayout()
        self.med_name = QLineEdit(); self.med_name.setPlaceholderText("Medicine name")
        self.med_dose = QLineEdit(); self.med_dose.setPlaceholderText("Dose, e.g. 500")
        self.med_unit = QLineEdit(); self.med_unit.setPlaceholderText("Unit, e.g. mg")
        r1.addWidget(self.med_name, 2); r1.addWidget(self.med_dose, 1); r1.addWidget(self.med_unit, 1)
        fb.addLayout(r1)
        r2 = QHBoxLayout()
        self.med_cadence = QComboBox()
        self.med_cadence.addItems(["daily", "twice_daily", "weekly", "as_needed", "custom"])
        self.med_time = QComboBox()
        self.med_time.addItems(["any", "morning", "evening", "night"])
        self.med_start = QSpinBox(); self.med_start.setRange(0, 365); self.med_start.setSuffix(" d ago")
        self.med_food = QLineEdit(); self.med_food.setPlaceholderText("Food instruction, e.g. after food")
        r2.addWidget(QLabel("Cadence")); r2.addWidget(self.med_cadence)
        r2.addWidget(QLabel("Time")); r2.addWidget(self.med_time)
        r2.addWidget(QLabel("Start")); r2.addWidget(self.med_start)
        fb.addLayout(r2)
        fb.addWidget(self.med_food)
        add_med = QPushButton("Add to care plan (records only — no prescribing)")
        add_med.clicked.connect(self._add_medication)
        fb.addWidget(add_med)
        med_col.addWidget(form_box)

        meds_box = QGroupBox("Active medications + today's adherence")
        mb = QVBoxLayout(meds_box)
        self.med_table = QTableWidget(0, 5)
        self.med_table.setHorizontalHeaderLabels(["Medication", "Dose", "Cadence", "Adherence (30 d)", "Log"])
        self.med_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.med_table.verticalHeader().setVisible(False)
        mb.addWidget(self.med_table)
        med_col.addWidget(meds_box, 2)
        mid.addLayout(med_col, 3)

        right_col = QVBoxLayout()

        # ---------------------------------------------------------- goals
        goal_box = QGroupBox("Lifestyle / clinician-defined goals")
        gb = QVBoxLayout(goal_box)
        gr = QHBoxLayout()
        self.goal_edit = QLineEdit(); self.goal_edit.setPlaceholderText("Goal, e.g. 4 activity sessions/week")
        self.goal_kind = QComboBox(); self.goal_kind.addItems(["activity", "sleep", "lifestyle", "test"])
        gr.addWidget(self.goal_edit, 2); gr.addWidget(self.goal_kind)
        add_goal = QPushButton("Add goal")
        add_goal.clicked.connect(self._add_goal)
        gr.addWidget(add_goal)
        gb.addLayout(gr)
        self.goal_table = QTableWidget(0, 2)
        self.goal_table.setHorizontalHeaderLabels(["Goal", "Kind"])
        self.goal_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.goal_table.verticalHeader().setVisible(False)
        gb.addWidget(self.goal_table)
        right_col.addWidget(goal_box)

        # ---------------------------------------------------- appointments
        appt_box = QGroupBox("Appointments / test reminders")
        ab = QVBoxLayout(appt_box)
        ar = QHBoxLayout()
        self.appt_kind = QComboBox(); self.appt_kind.addItems(["appointment", "test", "checkup"])
        self.appt_due = QSpinBox(); self.appt_due.setRange(0, 365); self.appt_due.setSuffix(" d")
        self.appt_note = QLineEdit(); self.appt_note.setPlaceholderText("Note, e.g. repeat ultrasound / HbA1c")
        ar.addWidget(self.appt_kind); ar.addWidget(QLabel("due in")); ar.addWidget(self.appt_due)
        ar.addWidget(self.appt_note, 2)
        add_appt = QPushButton("Add reminder")
        add_appt.clicked.connect(self._add_appointment)
        ar.addWidget(add_appt)
        ab.addLayout(ar)
        self.appt_table = QTableWidget(0, 4)
        self.appt_table.setHorizontalHeaderLabels(["Kind", "Due", "Note", "Status"])
        self.appt_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.appt_table.verticalHeader().setVisible(False)
        ab.addWidget(self.appt_table)
        right_col.addWidget(appt_box)

        # ------------------------------------------------------ disclaimer
        disc = QLabel(
            "SAFETY: this tab only records and reminds about an EXISTING plan entered by a "
            "clinician or the user. The application never changes medication dose, never starts or "
            "stops medication, and never prescribes treatment. Missed logs are 'potential care-plan "
            "gaps', not judgments. For any medical concern, seek professional clinical evaluation.")
        disc.setWordWrap(True)
        disc.setStyleSheet(
            f"QLabel {{ color: {YELLOW}; border: 1px solid {YELLOW}; background: {theme.tint(YELLOW, 0.10)}; "
            f"font-size: 9.5pt; padding: 8px; border-radius: 6px; }}")
        right_col.addWidget(disc)

        mid.addLayout(right_col, 2)
        outer.addLayout(mid, 1)

        self.refresh()

    # ------------------------------------------------------------- actions
    def _add_medication(self):
        name = self.med_name.text().strip()
        if not name:
            return
        self.care.add_medication(
            name=name,
            dose=self.med_dose.text().strip(),
            unit=self.med_unit.text().strip(),
            cadence=self.med_cadence.currentText(),
            time_of_day=self.med_time.currentText(),
            food_instruction=self.med_food.text().strip(),
            start_days_ago=float(self.med_start.value()) if self.med_start.value() > 0 else None,
        )
        self.med_name.clear(); self.med_dose.clear(); self.med_unit.clear(); self.med_food.clear()
        self.data_changed.emit()
        self.refresh()

    def _add_goal(self):
        goal = self.goal_edit.text().strip()
        if not goal:
            return
        self.care.add_goal(goal, kind=self.goal_kind.currentText())
        self.goal_edit.clear()
        self.data_changed.emit()
        self.refresh()

    def _add_appointment(self):
        self.care.add_appointment(
            kind=self.appt_kind.currentText(),
            due_in_days=float(self.appt_due.value()),
            note=self.appt_note.text().strip(),
        )
        self.appt_note.clear()
        self.data_changed.emit()
        self.refresh()

    def _log_med(self, med_id: int, status: str):
        self.care.store.log_medication(med_id, status)
        self.data_changed.emit()
        self.refresh()

    # ------------------------------------------------------------- display
    def refresh(self):
        # Reminders.
        import time

        lines = []
        for m in self.care.due_medications():
            when = m.get("time_of_day", "any")
            lines.append(f"• Due today ({when}): {m['name']} {m['dose']} {m['unit']}".strip()
                         + (f" — {m['food_instruction']}" if m.get("food_instruction") else ""))
        for a in self.care.due_appointments():
            due = time.strftime("%Y-%m-%d", time.localtime(a["due_ts"]))
            lines.append(f"• {a['kind'].title()} reminder: {a.get('note') or a['kind']} (due {due})")
        if not lines:
            lines.append("No dose slots or appointments currently due.")
        self.reminders_text.setPlainText("\n".join(lines))

        # Medications table.
        meds = self.care.medications()
        adherence = {m["medication_id"]: m for m in self.care.adherence_summary(days=30)}
        self.med_table.setRowCount(len(meds))
        for r, m in enumerate(meds):
            a = adherence.get(m["id"], {})
            pct = a.get("adherence_pct")
            pct_txt = f"{pct:.0f}%" if pct is not None else "—"
            dose = f"{m.get('dose', '')} {m.get('unit', '')}".strip()
            cells = [m["name"], dose or "—", m.get("cadence", "daily"), pct_txt, ""]
            for c, text in enumerate(cells[:4]):
                item = QTableWidgetItem(text)
                if c == 3 and pct is not None:
                    color = GREEN if pct >= 85 else YELLOW if pct >= 70 else RED
                    item.setForeground(__import__("PySide6.QtGui", fromlist=["QColor"]).QColor(color))
                self.med_table.setItem(r, c, item)
            # Log buttons in the last column.
            cell = QWidget(); hb = QHBoxLayout(cell); hb.setContentsMargins(4, 2, 4, 2)
            for status, label in [("taken", "Taken"), ("skipped", "Skipped"), ("snoozed", "Snoozed")]:
                b = QPushButton(label)
                b.setFixedHeight(24)
                b.clicked.connect(lambda _=False, sid=m["id"], st=status: self._log_med(sid, st))
                hb.addWidget(b)
            self.med_table.setCellWidget(r, 4, cell)
        self.med_table.resizeColumnsToContents()

        # Goals table.
        goals = self.care.goals()
        self.goal_table.setRowCount(len(goals))
        for r, g in enumerate(goals):
            self.goal_table.setItem(r, 0, QTableWidgetItem(g["goal"]))
            self.goal_table.setItem(r, 1, QTableWidgetItem(g.get("kind", "lifestyle")))
        self.goal_table.resizeColumnsToContents()

        # Appointments table.
        appts = self.care.appointments()
        self.appt_table.setRowCount(len(appts))
        for r, a in enumerate(appts):
            due = time.strftime("%Y-%m-%d", time.localtime(a["due_ts"])) if a.get("due_ts") else "—"
            cells = [a.get("kind", "appointment"), due, a.get("note", "") or "—", "done" if a.get("done") else "pending"]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c == 3:
                    item.setForeground(__import__("PySide6.QtGui", fromlist=["QColor"]).QColor(
                        GREEN if a.get("done") else ORANGE))
                self.appt_table.setItem(r, c, item)
            if not a.get("done"):
                btn = QPushButton("Mark done")
                btn.setFixedHeight(24)
                btn.clicked.connect(lambda _=False, aid=a["id"]: self._mark_done(aid))
                self.appt_table.setCellWidget(r, 3, btn)
        self.appt_table.resizeColumnsToContents()

    def _mark_done(self, appointment_id: int):
        self.care.store.mark_appointment_done(appointment_id)
        self.data_changed.emit()
        self.refresh()

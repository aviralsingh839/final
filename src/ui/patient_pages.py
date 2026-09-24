"""V8.2 patient-facing pages.

The patient section answers, in order of importance:

  1. "How am I doing?"                 → PatientOverviewPage
  2. "What is normal for me?"          → MyBaselinePage
  3. "What changed / when?"            → timeline (existing HistoryTrendsTab)
  4. "What do I need to do?"           → care & reminders (existing tab)

Only Level-1 information appears by default; explanations and statistics live
behind [WHY?] / [TECHNICAL DETAILS] expanders.  No values are ever fabricated:
missing data renders as an honest empty state.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.ui import theme
from src.ui.components import (
    CollapsibleSection,
    SectionCard,
    StatTile,
    StatusRow,
    empty_state,
    page_title,
    source_tag,
)


def _scroll_wrap(content: QWidget) -> QScrollArea:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    content.setObjectName("PageScrollContent")
    scroll.setWidget(content)
    return scroll


class PatientOverviewPage(QWidget):
    """Patient home screen — 'HOW AM I DOING?'."""

    view_timeline = Signal()
    view_baseline = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(6, 6, 6, 12)
        root.setSpacing(12)

        # ---------------------------------------------------------- header
        head = QHBoxLayout()
        head.addWidget(page_title("How am I doing?",
                                  "Longitudinal health overview — your own baseline, not population averages."), 1)
        self.demo_tag = source_tag("demo")
        self.demo_tag.hide()
        head.addWidget(self.demo_tag, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(head)

        id_row = QHBoxLayout()
        id_row.setSpacing(10)
        self.tile_patient = StatTile("Patient", "—")
        self.tile_monitoring = StatTile("Monitoring", "—")
        self.tile_mode = StatTile("Data source", "No stream", "Connect the wearable or start demo mode")
        for tile in (self.tile_patient, self.tile_monitoring, self.tile_mode):
            id_row.addWidget(tile, 1)
        root.addLayout(id_row)

        # -------------------------------------------------- personal status
        status_card = SectionCard("Personal status",
                                  "Compared with your own usual ranges.")
        srow = QHBoxLayout()
        srow.setSpacing(10)
        self.tile_pattern = StatTile("Physiological pattern", "—", "Awaiting data")
        self.tile_quality = StatTile("Data quality", "—")
        self.tile_coverage = StatTile("Baseline coverage", "—")
        for tile in (self.tile_pattern, self.tile_quality, self.tile_coverage):
            srow.addWidget(tile, 1)
        status_card.add_layout(srow)
        why = CollapsibleSection("Why?")
        self.why_text = QLabel("The pattern status compares your recent physiology (heart rate, "
                               "heart-rate variability, temperature, activity) against your personal "
                               "baseline. It is a monitoring summary, not a diagnosis.")
        self.why_text.setWordWrap(True)
        self.why_text.setObjectName("SmallMuted")
        why.add_widget(self.why_text)
        status_card.add_widget(why)
        root.addWidget(status_card)

        # ------------------------------------------------------ what changed
        wc_card = SectionCard("What changed?",
                              "Recent changes relative to your baseline. "
                              "Changes are observations, never a diagnosis.")
        self.rows = {
            "physiology": StatusRow("❤️", "Physiology (heart, HRV, temperature, skin response)"),
            "activity": StatusRow("🏃", "Activity"),
            "cycle": StatusRow("📅", "Cycle"),
            "symptoms": StatusRow("📝", "Symptoms"),
        }
        for row in self.rows.values():
            wc_card.add_widget(row)
        self.wc_empty = empty_state("Continue monitoring to establish a reliable personal baseline. "
                                    "Change detection starts once enough data has been collected.")
        wc_card.add_widget(self.wc_empty)
        btn_row = QHBoxLayout()
        self.timeline_btn = QPushButton("View timeline")
        self.timeline_btn.clicked.connect(self.view_timeline.emit)
        self.baseline_btn = QPushButton("View my baseline")
        self.baseline_btn.setObjectName("SecondaryButton")
        self.baseline_btn.clicked.connect(self.view_baseline.emit)
        btn_row.addWidget(self.timeline_btn)
        btn_row.addWidget(self.baseline_btn)
        btn_row.addStretch(1)
        wc_card.add_layout(btn_row)
        details = CollapsibleSection("Technical details")
        self.wc_details = QTextEdit()
        self.wc_details.setReadOnly(True)
        self.wc_details.setMinimumHeight(120)
        self.wc_details.setPlaceholderText("Evidence-linked change list appears here.")
        details.add_widget(self.wc_details)
        wc_card.add_widget(details)
        root.addWidget(wc_card)

        # -------------------------------------------------------------- care
        care_card = SectionCard("Care", "Recorded care plan — reminders are bookkeeping support, never blame.")
        crow = QHBoxLayout()
        crow.setSpacing(10)
        self.tile_adherence = StatTile("Care-plan adherence", "—", "No care plan recorded")
        self.tile_appt = StatTile("Next appointment", "—", "No appointment recorded")
        crow.addWidget(self.tile_adherence, 1)
        crow.addWidget(self.tile_appt, 1)
        care_card.add_layout(crow)
        root.addWidget(care_card)

        note = QLabel("This is a research / pre-screening system. It supports — and never replaces — "
                      "clinical evaluation by a qualified professional.")
        note.setObjectName("SmallMuted")
        note.setWordWrap(True)
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(note)
        root.addStretch(1)

        _scroll = _scroll_wrap(content)
        outer.addWidget(_scroll)

    # ------------------------------------------------------------- updates
    def set_header(self, patient: str, monitoring_days: float | None, mode: str):
        self.tile_patient.set(patient or "Anonymous")
        if monitoring_days is not None and monitoring_days >= 1:
            self.tile_monitoring.set(f"{monitoring_days:.0f} days")
        else:
            self.tile_monitoring.set("Starting", "First session in progress")
        mode_map = {
            "live": ("Live wearable", "Measured data — wearable connected", None),
            "demo": ("Demo data", "Synthetic demonstration data — clearly labelled, excluded from analysis", "blue"),
            "replay": ("Recorded replay", "Replaying a previously recorded session", None),
            "none": ("No stream", "Connect the wearable or start demo mode", None),
        }
        text, caption, state = mode_map.get(mode, mode_map["none"])
        self.tile_mode.set(text, caption, state)
        self.demo_tag.setVisible(mode == "demo")

    def set_personal_status(self, pattern_state: str, pattern_text: str,
                            quality_pct: float | None, coverage_text: str):
        state_map = {
            "normal": ("Stable", "green"),
            "deviation": ("Changed", "yellow"),
            "insufficient_quality": ("Needs better signal", "gray"),
        }
        label, color = state_map.get(pattern_state, ("—", None))
        self.tile_pattern.set(label, pattern_text, color)
        if quality_pct is None:
            self.tile_quality.set("—", "No recent signal")
        else:
            q_state = "green" if quality_pct >= 70 else "yellow" if quality_pct >= 40 else "red"
            self.tile_quality.set(f"{quality_pct:.0f}%", "Share of usable signal", q_state)
        self.tile_coverage.set(coverage_text)

    def set_what_changed(self, states: dict, details_text: str = ""):
        """states: {'physiology'|'activity'|'cycle'|'symptoms': (state, statement)}"""
        any_set = False
        for key, row in self.rows.items():
            if key in states:
                state, statement = states[key]
                row.set_state(state, statement)
                row.show()
                any_set = True
            else:
                row.set_state("stable", "No major change detected")
                row.show()
        self.wc_empty.setVisible(not any_set and not details_text)
        if details_text:
            self.wc_details.setPlainText(details_text)

    def set_care(self, adherence_pct: float | None, next_appt_days: float | None):
        if adherence_pct is None:
            self.tile_adherence.set("—", "No care plan recorded")
        else:
            self.tile_adherence.set(f"{adherence_pct:.0f}%", "Recorded doses vs planned (last 30 days)")
        if next_appt_days is None:
            self.tile_appt.set("—", "No appointment recorded")
        elif next_appt_days <= 0:
            self.tile_appt.set("Due now", "A recorded appointment/test is due")
        else:
            self.tile_appt.set(f"{next_appt_days:.0f} days", "Until the next recorded appointment/test")


class MyBaselinePage(QWidget):
    """MY BASELINE — 'What is normal for me?' with plain-language ranges."""

    METRICS = [
        ("hr_bpm", "Heart rate", "bpm"),
        ("rmssd_ms", "HRV (RMSSD)", "ms"),
        ("skin_temp_c", "Skin temperature", "°C"),
        ("gsr_tonic", "Skin response (GSR)", "raw"),
    ]

    def __init__(self, capture_cb=None, wizard_cb=None, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(6, 6, 6, 12)
        root.setSpacing(12)

        root.addWidget(page_title("My baseline",
                                  "Your usual ranges, learned from calm periods — the system compares "
                                  "you with yourself, not with population averages."))

        status_card = SectionCard("Baseline status")
        self.status_label = QLabel("No baseline yet — sit still for 5 calm minutes, then press "
                                   "'Capture baseline'.")
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName("BigValue")
        self.ranges_label = QLabel("Using population defaults until your personal baseline is captured.")
        self.ranges_label.setObjectName("SmallMuted")
        self.ranges_label.setWordWrap(True)
        status_card.add_widget(self.status_label)
        status_card.add_widget(self.ranges_label)
        btn_row = QHBoxLayout()
        self.capture_btn = QPushButton("Capture baseline (5 min)")
        if capture_cb:
            self.capture_btn.clicked.connect(capture_cb)
        self.wizard_btn = QPushButton("Calibration wizard")
        self.wizard_btn.setObjectName("SecondaryButton")
        if wizard_cb:
            self.wizard_btn.clicked.connect(wizard_cb)
        btn_row.addWidget(self.capture_btn)
        btn_row.addWidget(self.wizard_btn)
        btn_row.addStretch(1)
        status_card.add_layout(btn_row)
        root.addWidget(status_card)

        # ----------------------------------------------- per-metric ranges
        self.metrics_card = SectionCard("My usual ranges",
                                        "Usual range · current value · status. Values update live.")
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)
        headers = ["Measure", "Usual range", "Current", "Status"]
        for c, h in enumerate(headers):
            lbl = QLabel(h)
            lbl.setObjectName("StatLabel")
            grid.addWidget(lbl, 0, c)
        self._rows = {}
        for r, (key, label, unit) in enumerate(self.METRICS, start=1):
            name = QLabel(label)
            name.setStyleSheet("font-weight: 600;")
            rng = QLabel("—")
            cur = QLabel("—")
            stat = QLabel("Awaiting baseline")
            stat.setObjectName("SmallMuted")
            grid.addWidget(name, r, 0)
            grid.addWidget(rng, r, 1)
            grid.addWidget(cur, r, 2)
            grid.addWidget(stat, r, 3)
            self._rows[key] = (rng, cur, stat, unit)
        grid.setColumnStretch(3, 1)
        self.metrics_card.add_layout(grid)
        self.metrics_empty = empty_state("Continue monitoring to establish a reliable personal baseline.")
        self.metrics_card.add_widget(self.metrics_empty)
        root.addWidget(self.metrics_card)

        # ----------------------------------------------- technical details
        tech = CollapsibleSection("Technical details — physiological fingerprint and statistics")
        self.tech_holder = QVBoxLayout()
        holder_w = QWidget()
        holder_w.setLayout(self.tech_holder)
        tech.add_widget(holder_w)
        root.addWidget(tech)
        root.addStretch(1)

        outer.addWidget(_scroll_wrap(content))

    def add_technical_widget(self, w: QWidget):
        self.tech_holder.addWidget(w)

    def update_metrics(self, baseline_model, current_feature, per_metric_change: dict | None = None):
        """Fill the plain-language range table from the baseline model."""
        if per_metric_change is not None:
            self._last_phrases = per_metric_change
        phrases = getattr(self, "_last_phrases", None)
        has_any = False
        for key, (rng_lbl, cur_lbl, stat_lbl, unit) in self._rows.items():
            rng = baseline_model.normal_range(key) if baseline_model is not None else None
            cur = getattr(current_feature, key, None) if current_feature is not None else None
            if rng is not None:
                has_any = True
                rng_lbl.setText(f"{rng[0]:.1f} – {rng[1]:.1f} {unit}")
            else:
                rng_lbl.setText("—")
            cur_lbl.setText(f"{cur:.1f} {unit}" if cur is not None else "—")
            state_text, color = "Awaiting data", theme.TEXT_MUTED
            if rng is not None and cur is not None:
                if cur < rng[0]:
                    state_text, color = "Below your usual range", theme.YELLOW
                elif cur > rng[1]:
                    state_text, color = "Above your usual range", theme.YELLOW
                else:
                    state_text, color = "Within your usual range", theme.GREEN
            if phrases and key in phrases:
                phrase = phrases[key]
                if phrase:
                    state_text = phrase
            stat_lbl.setText(state_text)
            stat_lbl.setStyleSheet(f"color: {color}; font-size: 10.5pt;")
        self.metrics_empty.setVisible(not has_any)


class PatientReportsPage(QWidget):
    """Patient-facing report actions (clinician reports live in the clinician section)."""

    def __init__(self, on_text=None, on_pdf=None, on_json=None, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(6, 6, 6, 12)
        root.setSpacing(12)

        root.addWidget(page_title("Reports",
                                  "Summaries of your monitoring period that you can save, print or share "
                                  "with your clinician."))

        card = SectionCard("My monitoring summary",
                           "Covers baseline, trends, changes and data quality for the recent period.")
        row = QHBoxLayout()
        self.text_btn = QPushButton("Generate report (text)")
        self.pdf_btn = QPushButton("Generate report (PDF)")
        self.json_btn = QPushButton("Export my data (JSON)")
        self.json_btn.setObjectName("SecondaryButton")
        if on_text:
            self.text_btn.clicked.connect(on_text)
        if on_pdf:
            self.pdf_btn.clicked.connect(on_pdf)
        if on_json:
            self.json_btn.clicked.connect(on_json)
        row.addWidget(self.text_btn)
        row.addWidget(self.pdf_btn)
        row.addWidget(self.json_btn)
        row.addStretch(1)
        card.add_layout(row)
        note = QLabel("Reports describe monitoring observations and model estimates with uncertainty. "
                      "They are research documents, not medical records, and never contain a diagnosis.")
        note.setObjectName("SmallMuted")
        note.setWordWrap(True)
        card.add_widget(note)
        root.addWidget(card)

        clin = SectionCard("Clinical reports")
        info = QLabel("Full longitudinal clinical reports, report history, comparison, printing and QR "
                      "access are managed in the CLINICIAN section → Clinical Dashboard.")
        info.setWordWrap(True)
        info.setObjectName("SmallMuted")
        clin.add_widget(info)
        root.addWidget(clin)
        root.addStretch(1)

        outer.addWidget(_scroll_wrap(content))

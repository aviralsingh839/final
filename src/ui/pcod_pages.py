"""Desktop (Qt) mirror of the two PCOD/PMOS sections (CHRONO-PCOS V9.0).

These pages render EXACTLY the same engines as the portable web companion
(`src/pcod/criteria.py` and `src/pcod/complications.py`), so the desktop and
the phone can never disagree. Nothing here re-implements clinical logic.

Sections:
    1  PCOD detection            — evidence-based Rotterdam criteria
    2  Complication screening    — guideline-interval screening checklist
    +  Smartwatch link           — ingest / HTTP push / simulated watch
    +  Latest evidence           — the cited 2026-era registry
"""
from __future__ import annotations

import time
from dataclasses import fields, is_dataclass
from datetime import date
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QDoubleSpinBox, QFormLayout, QFrame,
    QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QSpinBox, QTextEdit, QVBoxLayout, QWidget,
)

from src.pcod import criteria, evidence, watch
from src.pcod import complications as cx
from src.ui import theme
from src.ui.components import (
    CollapsibleSection, SectionCard, StatTile, page_title, status_banner,
)

STATUS_COLORS = {
    criteria.PRESENT: "red",
    criteria.ABSENT: "green",
    criteria.UNKNOWN: "yellow",
    cx.ACTION_NEEDED: "red",
    cx.OVERDUE: "red",
    cx.DUE: "orange",
    cx.UP_TO_DATE: "green",
    cx.UNKNOWN: "yellow",
    cx.NOT_INDICATED: "gray",
}

STATUS_ORDER = [cx.ACTION_NEEDED, cx.OVERDUE, cx.DUE, cx.UNKNOWN,
                cx.UP_TO_DATE, cx.NOT_INDICATED]


def _chip(text: str, color: str) -> QLabel:
    lab = QLabel(text)
    lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
    c = theme.status_color(color)
    lab.setStyleSheet(
        f"QLabel {{ background: {theme.tint(c, 0.12)}; border: 1px solid {c}; color: {c}; "
        f"font-size: 9.5pt; font-weight: 700; padding: 3px 10px; border-radius: 10px; }}")
    lab.setFixedWidth(140)
    return lab


class _FormBuilder:
    """Builds a Qt form from a dataclass's fields with friendly labels."""

    LABELS: Dict[str, str] = {
        "age_years": "Age (years)",
        "years_post_menarche": "Years since first period",
        "usual_cycle_length_days": "Usual cycle length (days)",
        "cycles_last_year": "Periods in the last 12 months",
        "days_since_last_period": "Days since last period",
        "longest_cycle_days": "Longest cycle (days)",
        "luteal_progesterone_nmol_l": "Luteal progesterone (nmol/L)",
        "on_hormonal_contraception": "On hormonal contraception",
        "hirsutism": "Hirsutism",
        "ferriman_gallwey": "Ferriman–Gallwey score",
        "acne": "Persistent acne",
        "female_pattern_hair_loss": "Female-pattern hair loss",
        "total_testosterone_nmol_l": "Total testosterone (nmol/L)",
        "free_testosterone_pmol_l": "Free testosterone (pmol/L)",
        "free_androgen_index": "Free androgen index",
        "androstenedione_nmol_l": "Androstenedione (nmol/L)",
        "dheas_umol_l": "DHEAS (µmol/L)",
        "testosterone_assay": "Testosterone assay",
        "fnpo": "Follicle number per ovary (FNPO)",
        "fnps": "Follicles per cross-section (FNPS)",
        "ovarian_volume_ml": "Ovarian volume (mL)",
        "ultrasound_route": "Ultrasound route",
        "amh_pmol_l": "AMH (pmol/L)",
        "amh_ng_ml": "AMH (ng/mL)",
        "amh_assay": "AMH assay",
        "amh_lab_cutoff": "Your lab's AMH cut-off",
        "tsh_checked": "Thyroid (TSH) checked",
        "prolactin_checked": "Prolactin checked",
        "ohp17_checked": "17-OH progesterone checked",
        "other_causes_excluded": "Clinician excluded other causes",
        "bmi": "BMI (kg/m²)",
        "waist_cm": "Waist circumference (cm)",
        "systolic_bp": "Systolic BP (mmHg)",
        "diastolic_bp": "Diastolic BP (mmHg)",
        "asian_ethnicity": "South Asian / Asian ethnicity",
        "fasting_glucose_mg_dl": "Fasting glucose (mg/dL)",
        "ogtt_2h_mg_dl": "2-hour OGTT (mg/dL)",
        "hba1c_pct": "HbA1c (%)",
        "total_cholesterol_mg_dl": "Total cholesterol (mg/dL)",
        "ldl_mg_dl": "LDL-C (mg/dL)",
        "hdl_mg_dl": "HDL-C (mg/dL)",
        "triglycerides_mg_dl": "Triglycerides (mg/dL)",
        "alt_u_l": "ALT (U/L)",
        "family_history_t2dm": "Family history of type 2 diabetes",
        "family_history_premature_cvd": "Family history of early heart disease",
        "personal_history_gestational_diabetes": "Past gestational diabetes",
        "acanthosis_nigricans": "Acanthosis nigricans",
        "current_smoker": "Current smoker",
        "moderate_activity_min_per_week": "Moderate activity (min/week)",
        "pregnant": "Currently pregnant",
        "gestation_weeks": "Gestation (weeks)",
        "trying_to_conceive": "Trying to conceive",
        "months_trying_to_conceive": "Months trying",
        "amenorrhoea_days": "Days without a period",
        "abnormal_uterine_bleeding": "Unexpected bleeding / spotting",
        "snoring": "Snoring",
        "witnessed_apnoea": "Witnessed pauses in breathing",
        "daytime_somnolence": "Daytime sleepiness",
        "phq9_score": "PHQ-9 score (0–27)",
        "gad7_score": "GAD-7 score (0–21)",
        "last_glucose_test_date": "Last glucose test",
        "last_lipid_test_date": "Last lipid profile",
        "last_bp_date": "Last BP measured",
        "last_weight_date": "Last weight / BMI",
        "last_mental_health_screen_date": "Last mood screen",
        "last_liver_test_date": "Last liver test",
    }
    CHOICES = {
        "testosterone_assay": ["unknown", "lc_ms", "immunoassay"],
        "ultrasound_route": ["unknown", "transvaginal", "transabdominal"],
        "amh_assay": ["unknown", "gen_ii", "picoamh", "elecsys", "access"],
    }
    TRISTATE = {
        "on_hormonal_contraception", "hirsutism", "acne", "female_pattern_hair_loss",
        "asian_ethnicity", "family_history_t2dm", "family_history_premature_cvd",
        "personal_history_gestational_diabetes", "acanthosis_nigricans", "current_smoker",
        "pregnant", "trying_to_conceive", "abnormal_uterine_bleeding", "snoring",
        "witnessed_apnoea", "daytime_somnolence", "tsh_checked", "prolactin_checked",
        "ohp17_checked", "other_causes_excluded",
    }

    def __init__(self, dataclass_type):
        self.dc = dataclass_type
        self.widgets: Dict[str, QWidget] = {}
        self.root = QWidget()
        self.layout = QVBoxLayout(self.root)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(10)

    def add_group(self, title: str, keys: List[str]) -> None:
        box = QGroupBox(title)
        grid = QGridLayout(box)
        grid.setSpacing(7)
        row = col = 0
        for k in keys:
            if k not in {f.name for f in fields(self.dc)}:
                continue
            w = self._widget(k)
            grid.addWidget(QLabel(self.LABELS.get(k, k)), row, col * 2)
            grid.addWidget(w, row, col * 2 + 1)
            col += 1
            if col >= 2:
                col = 0
                row += 1
        self.layout.addWidget(box)

    def _widget(self, key: str) -> QWidget:
        if key in self.TRISTATE:
            cb = QComboBox()
            cb.addItems(["Not recorded", "Yes", "No"])
            self.widgets[key] = cb
            return cb
        if key in self.CHOICES:
            cb = QComboBox()
            cb.addItems(self.CHOICES[key])
            self.widgets[key] = cb
            return cb
        if key.endswith("_date"):
            de = QDateEdit()
            de.setCalendarPopup(True)
            de.setDisplayFormat("yyyy-MM-dd")
            de.setSpecialValueText("Not recorded")
            de.setMinimumDate(date(2000, 1, 1))
            de.setDate(date(2000, 1, 1))
            self.widgets[key] = de
            return de
        if key in {"ferriman_gallwey", "cycles_last_year", "fnpo", "fnps",
                   "steps", "phq9_score", "gad7_score", "amenorrhoea_days",
                   "usual_cycle_length_days", "longest_cycle_days",
                   "days_since_last_period"}:
            sp = QSpinBox()
            sp.setRange(-1, 10000)
            sp.setSpecialValueText("Not recorded")
            sp.setValue(-1)
            self.widgets[key] = sp
            return sp
        sp = QDoubleSpinBox()
        sp.setRange(-1.0, 100000.0)
        sp.setDecimals(2)
        sp.setSpecialValueText("Not recorded")
        sp.setValue(-1.0)
        self.widgets[key] = sp
        return sp

    # ------------------------------------------------------------- values
    def values(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for k, w in self.widgets.items():
            if isinstance(w, QComboBox):
                if k in self.TRISTATE:
                    idx = w.currentIndex()
                    if idx == 1:
                        out[k] = True
                    elif idx == 2:
                        out[k] = False
                else:
                    val = w.currentText()
                    if val and val != "unknown":
                        out[k] = val
            elif isinstance(w, QDateEdit):
                d = w.date()
                if d.year > 2000:
                    out[k] = d.toString("yyyy-MM-dd")
            elif isinstance(w, QSpinBox):
                v = w.value()
                if v >= 0:
                    out[k] = int(v)
            elif isinstance(w, QDoubleSpinBox):
                v = w.value()
                if v >= 0:
                    out[k] = float(v)
        return out

    def set_values(self, data: Dict[str, Any]) -> None:
        for k, v in (data or {}).items():
            w = self.widgets.get(k)
            if w is None:
                continue
            if isinstance(w, QComboBox):
                if k in self.TRISTATE:
                    w.setCurrentIndex(0 if v is None else (1 if v else 2))
                else:
                    w.setCurrentText(str(v) if v else "unknown")
            elif isinstance(w, QDateEdit):
                if v:
                    try:
                        y, m, d = [int(x) for x in str(v)[:10].split("-")]
                        w.setDate(date(y, m, d))
                    except (ValueError, TypeError):
                        pass
            elif isinstance(w, (QSpinBox, QDoubleSpinBox)):
                w.setValue(float(v) if v is not None else -1)

    def clear(self) -> None:
        for k, w in self.widgets.items():
            if isinstance(w, QComboBox):
                w.setCurrentIndex(0)
            elif isinstance(w, QDateEdit):
                w.setDate(date(2000, 1, 1))
            elif isinstance(w, (QSpinBox, QDoubleSpinBox)):
                w.setValue(-1)


class _BasePcodPage(QWidget):
    """Shared shell: results on top, input form in a scroll area below."""

    def __init__(self, store: watch.WatchStore | None = None, parent=None):
        super().__init__(parent)
        self.store = store
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(6, 6, 6, 6)
        self._root.setSpacing(10)

    def _scroll(self, widget: QWidget) -> QScrollArea:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setWidget(widget)
        return area


# ==========================================================================
# SECTION 1
# ==========================================================================
class PcodDetectionPage(_BasePcodPage):
    """Section 1 — PCOD / PMOS detection against the evidence-based criteria."""

    def __init__(self, store=None, parent=None):
        super().__init__(store, parent)
        self._root.addWidget(page_title(
            "①  PCOD / PMOS detection",
            "The evidence-based Rotterdam criteria: 2 of 3 in adults, after other causes are excluded."))

        self.verdict_label = QLabel("Enter your information below to apply the criteria.")
        self.verdict_label.setObjectName("BigValue")
        self.verdict_label.setWordWrap(True)
        self.explain_label = QLabel("")
        self.explain_label.setObjectName("SmallMuted")
        self.explain_label.setWordWrap(True)
        self.stage_chip = _chip("life stage", "gray")
        self.exclusion_banner = QLabel("")
        self.exclusion_banner.setWordWrap(True)

        head = SectionCard("Screening result")
        top = QHBoxLayout()
        top.addWidget(self.verdict_label, 1)
        top.addWidget(self.stage_chip)
        head.add_layout(top)
        head.add_widget(self.explain_label)
        head.add_widget(self.exclusion_banner)
        self._root.addWidget(head)

        self.criteria_card = SectionCard("The three criteria")
        self.criteria_layout = QVBoxLayout()
        self.criteria_layout.setSpacing(6)
        self.criteria_card.add_layout(self.criteria_layout)
        self._root.addWidget(self.criteria_card)

        self.watch_note = QLabel("")
        self.watch_note.setObjectName("SmallMuted")
        self.watch_note.setWordWrap(True)
        self._root.addWidget(self.watch_note)

        self._build_form()

    # ------------------------------------------------------------- form
    def _build_form(self) -> None:
        self.form = _FormBuilder(criteria.PatientInputs)
        self.form.add_group("Demographics", ["age_years", "years_post_menarche"])
        self.form.add_group("Cycle history", [
            "usual_cycle_length_days", "cycles_last_year", "days_since_last_period",
            "longest_cycle_days", "luteal_progesterone_nmol_l", "on_hormonal_contraception"])
        self.form.add_group("Clinical signs of androgen excess", [
            "hirsutism", "ferriman_gallwey", "acne", "female_pattern_hair_loss"])
        self.form.add_group("Blood tests — androgens", [
            "total_testosterone_nmol_l", "free_testosterone_pmol_l", "free_androgen_index",
            "androstenedione_nmol_l", "dheas_umol_l", "testosterone_assay"])
        self.form.add_group("Polycystic ovarian morphology", [
            "fnpo", "fnps", "ovarian_volume_ml", "ultrasound_route",
            "amh_ng_ml", "amh_lab_cutoff"])
        self.form.add_group("Excluding other causes", [
            "tsh_checked", "prolactin_checked", "ohp17_checked", "other_causes_excluded"])

        buttons = QHBoxLayout()
        self.save_btn = QPushButton("Apply criteria")
        self.save_btn.setObjectName("PrimaryButton")
        self.save_btn.clicked.connect(self.refresh_results)
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setObjectName("SecondaryButton")
        self.clear_btn.clicked.connect(self.clear_form)
        buttons.addWidget(self.save_btn)
        buttons.addWidget(self.clear_btn)
        buttons.addStretch(1)
        self.form.layout.addLayout(buttons)

        sec = CollapsibleSection("Enter your information — everything optional, unknown stays unknown")
        sec.add_widget(self.form.root)
        self._root.addWidget(sec)

        how = CollapsibleSection("How this section works")
        txt = QTextEdit()
        txt.setReadOnly(True)
        txt.setPlainText(
            "Adults: at least two of (1) ovulatory dysfunction, (2) clinical or biochemical "
            "hyperandrogenism, (3) polycystic ovarian morphology on ultrasound OR raised AMH — "
            "after other causes are excluded.\n\n"
            "Adolescents: BOTH hyperandrogenism and ovulatory dysfunction are required; "
            "ultrasound and AMH are not recommended.\n\n"
            "If BOTH irregular cycles and hyperandrogenism are present, an ultrasound is not "
            "necessary for diagnosis.\n\n"
            "Each criterion is PRESENT, ABSENT or UNKNOWN. An unmeasured item is never counted "
            "as a 'no'. A smartwatch cannot establish any of the three criteria.\n\n"
            "No universal AMH threshold exists — cut-offs are population- and assay-specific, so "
            "this app asks for the cut-off printed on your own laboratory report."
        )
        txt.setMinimumHeight(170)
        how.add_widget(txt)
        self._root.addWidget(how)

        self.citation_box = QTextEdit()
        self.citation_box.setReadOnly(True)
        self.citation_box.setMaximumHeight(120)
        self.citation_box.setObjectName("SmallMuted")
        self._root.addWidget(self.citation_box)

    # ----------------------------------------------------------- actions
    def clear_form(self) -> None:
        self.form.clear()
        self.refresh_results()

    def refresh_results(self, profile: Optional[dict] = None) -> None:
        if profile is None:
            profile = self.form.values()
        else:
            self.form.set_values(profile)
        inputs = criteria.PatientInputs.from_dict(profile)

        wc = None
        if self.store is not None:
            s = self.store.summary()
            wc = criteria.WatchContext(
                resting_hr_bpm=s.get("hr_mean_24h"), rmssd_ms=s.get("rmssd_mean_24h"),
                steps_last_24h=s.get("steps_24h"), sleep_hours_last_night=s.get("sleep_hours_latest"),
                spo2_pct=s.get("spo2_mean_24h"), data_sufficiency=s.get("sufficiency", 0.0),
                days_of_data=s.get("covered_days", 0), device_name=s.get("device", ""))

        r = criteria.evaluate(inputs, wc)
        self.verdict_label.setText(r.headline)
        self.explain_label.setText(r.explanation)
        self.stage_chip.setText(r.life_stage.upper())
        self.stage_chip.setParent(None)
        # keep the chip in place (it is fixed-width); only its text changes
        self.stage_chip.setParent(self)

        while self.criteria_layout.count():
            item = self.criteria_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        for c in r.criteria:
            row = QFrame()
            row.setObjectName("Card")
            lay = QHBoxLayout(row)
            lay.setContentsMargins(12, 8, 12, 8)
            text_box = QVBoxLayout()
            name = QLabel(c.label)
            name.setStyleSheet("font-weight: 700; font-size: 11pt;")
            name.setWordWrap(True)
            detail = QLabel(c.detail)
            detail.setObjectName("SmallMuted")
            detail.setWordWrap(True)
            text_box.addWidget(name)
            text_box.addWidget(detail)
            for b in c.blockers:
                bl = QLabel("→ " + b)
                bl.setObjectName("SmallMuted")
                bl.setWordWrap(True)
                text_box.addWidget(bl)
            lay.addLayout(text_box, 1)
            lay.addWidget(_chip(c.status, STATUS_COLORS[c.status]))
            self.criteria_layout.addWidget(row)

        if r.exclusions_complete:
            self.exclusion_banner.setText(
                "Other causes recorded as excluded — a clinician still confirms the diagnosis.")
            self.exclusion_banner.setStyleSheet(
                f"QLabel {{ background: {theme.tint(theme.GREEN, 0.10)}; border: 1px solid {theme.GREEN}; "
                f"color: {theme.GREEN}; padding: 8px; border-radius: 8px; }}")
        else:
            self.exclusion_banner.setText(
                "Other causes must be excluded before this can be called PMOS/PCOS. Still to check: "
                + ", ".join(r.exclusions_missing) + ".")
            self.exclusion_banner.setStyleSheet(
                f"QLabel {{ background: {theme.tint(theme.YELLOW, 0.10)}; border: 1px solid {theme.YELLOW}; "
                f"color: {theme.YELLOW}; padding: 8px; border-radius: 8px; }}")

        self.watch_note.setText(r.watch_note)
        cites = r.citations[:8]
        self.citation_box.setPlainText("\n".join(
            f"· {c['org']} ({c['year']})"
            + (f" · rec {c['rec_id']}" if c.get("rec_id") else "")
            + (f" · {c['grade']}" if c.get("grade") not in (None, "FACT") else "")
            + f" — {c['title']}" for c in cites))


# ==========================================================================
# SECTION 2
# ==========================================================================
class PcodComplicationPage(_BasePcodPage):
    """Section 2 — guideline-interval complication screening checklist."""

    def __init__(self, store=None, parent=None):
        super().__init__(store, parent)
        self._root.addWidget(page_title(
            "②  PCOD / PMOS complication screening",
            "A screening checklist built from published guideline intervals — not a risk percentage."))

        self.counts_label = QLabel("")
        self.counts_label.setWordWrap(True)
        head = SectionCard("Summary")
        head.add_widget(self.counts_label)
        self._root.addWidget(head)

        self.list_card = SectionCard("By priority")
        self.list_layout = QVBoxLayout()
        self.list_layout.setSpacing(8)
        self.list_card.add_layout(self.list_layout)
        self._root.addWidget(self.list_card)

        self.disclaimer = QLabel("")
        self.disclaimer.setObjectName("SmallMuted")
        self.disclaimer.setWordWrap(True)
        self._root.addWidget(self.disclaimer)

        self._build_form()

    def _build_form(self) -> None:
        self.form = _FormBuilder(cx.ClinicalInputs)
        self.form.add_group("Measurements", [
            "age_years", "bmi", "waist_cm", "systolic_bp", "diastolic_bp", "asian_ethnicity"])
        self.form.add_group("Metabolic blood tests", [
            "fasting_glucose_mg_dl", "ogtt_2h_mg_dl", "hba1c_pct",
            "total_cholesterol_mg_dl", "ldl_mg_dl", "hdl_mg_dl",
            "triglycerides_mg_dl", "alt_u_l"])
        self.form.add_group("History", [
            "family_history_t2dm", "family_history_premature_cvd",
            "personal_history_gestational_diabetes", "acanthosis_nigricans",
            "current_smoker", "moderate_activity_min_per_week"])
        self.form.add_group("Mood and sleep", [
            "phq9_score", "gad7_score", "snoring", "witnessed_apnoea", "daytime_somnolence"])
        self.form.add_group("Reproductive", [
            "pregnant", "gestation_weeks", "trying_to_conceive",
            "months_trying_to_conceive", "amenorrhoea_days", "abnormal_uterine_bleeding"])
        self.form.add_group("When things were last checked", [
            "last_glucose_test_date", "last_lipid_test_date", "last_bp_date",
            "last_weight_date", "last_mental_health_screen_date"])

        buttons = QHBoxLayout()
        self.save_btn = QPushButton("Re-check screening")
        self.save_btn.setObjectName("PrimaryButton")
        self.save_btn.clicked.connect(self.refresh_results)
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setObjectName("SecondaryButton")
        self.clear_btn.clicked.connect(self.clear_form)
        buttons.addWidget(self.save_btn)
        buttons.addWidget(self.clear_btn)
        buttons.addStretch(1)
        self.form.layout.addLayout(buttons)

        sec = CollapsibleSection("Enter your information — measurements, history and symptom screens")
        sec.add_widget(self.form.root)
        self._root.addWidget(sec, 1)

    def clear_form(self) -> None:
        self.form.clear()
        self.refresh_results()

    def refresh_results(self, clinical: Optional[dict] = None) -> None:
        if clinical is None:
            clinical = self.form.values()
        else:
            self.form.set_values(clinical)

        device = ""
        if self.store is not None:
            device = self.store.summary().get("device", "")
        r = cx.evaluate(cx.ClinicalInputs.from_dict(clinical), watch_device=device)

        order = {s: i for i, s in enumerate(STATUS_ORDER)}
        labels = {cx.ACTION_NEEDED: "Assessment needed", cx.OVERDUE: "Overdue", cx.DUE: "Due",
                  cx.UNKNOWN: "Not assessed", cx.UP_TO_DATE: "Up to date",
                  cx.NOT_INDICATED: "Not routinely screened"}
        self.counts_label.setText("   ·   ".join(
            f"{r.counts[k]} {labels[k]}" for k in STATUS_ORDER if r.counts.get(k)) or "—")

        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        for d in sorted(r.domains, key=lambda x: order.get(x.status, 99)):
            row = QFrame()
            row.setObjectName("Card")
            lay = QHBoxLayout(row)
            lay.setContentsMargins(12, 9, 12, 9)
            box = QVBoxLayout()
            title = QLabel(d.label)
            title.setStyleSheet("font-weight: 700; font-size: 11pt;")
            title.setWordWrap(True)
            box.addWidget(title)
            why = QLabel(d.why)
            why.setObjectName("SmallMuted")
            why.setWordWrap(True)
            box.addWidget(why)
            for s in d.signals:
                sl = QLabel("· " + s)
                sl.setObjectName("SmallMuted")
                sl.setWordWrap(True)
                box.addWidget(sl)
            act = QLabel("What to do: " + d.action)
            act.setWordWrap(True)
            box.addWidget(act)
            if d.interval_note:
                tl = QLabel("Timing: " + d.interval_note)
                tl.setObjectName("SmallMuted")
                tl.setWordWrap(True)
                box.addWidget(tl)
            if d.watch_support:
                wl = QLabel("Smartwatch: " + d.watch_support)
                wl.setObjectName("SmallMuted")
                wl.setWordWrap(True)
                box.addWidget(wl)
            lay.addLayout(box, 1)
            lay.addWidget(_chip(cx.STATUS_LABELS[d.status], STATUS_COLORS[d.status]))
            self.list_layout.addWidget(row)

        self.disclaimer.setText(r.watch_note + "\n\n" + r.disclaimer)


# ==========================================================================
# SMARTWATCH LINK
# ==========================================================================
class PcodWatchPage(_BasePcodPage):
    """Smartwatch link: live status, HTTP ingest endpoint, simulated watch."""

    def __init__(self, store: watch.WatchStore | None = None, parent=None):
        super().__init__(store, parent)
        self._root.addWidget(page_title(
            "⌚  Smartwatch link",
            "Any watch, phone bridge or automation app can push readings to the local endpoint."))

        self.tiles: Dict[str, StatTile] = {}
        grid = QGridLayout()
        grid.setSpacing(8)
        for i, key in enumerate(["HR", "HRV (RMSSD)", "SpO₂ (estimate)", "Steps 24 h",
                                 "Sleep", "Wrist temp"]):
            t = StatTile(key, "—", "")
            self.tiles[key] = t
            grid.addWidget(t, i // 3, i % 3)
        card = SectionCard("Latest from your watch")
        card.add_layout(grid)
        self.battery_label = QLabel("")
        self.battery_label.setObjectName("SmallMuted")
        card.add_widget(self.battery_label)
        self.coverage_label = QLabel("")
        self.coverage_label.setObjectName("SmallMuted")
        card.add_widget(self.coverage_label)
        self._root.addWidget(card)

        self._root.addWidget(status_banner(
            "A smartwatch cannot measure hormones, glucose, lipids or ovarian morphology. "
            "It never replaces a laboratory test or an ultrasound.", "yellow"))

        ingest = SectionCard("HTTP ingest endpoint",
                             "Any device on the same network can push a reading:")
        example = QTextEdit()
        example.setReadOnly(True)
        example.setPlainText(
            "curl -X POST http://<this-pc-ip>:8000/api/watch/ingest \\\n"
            "  -H \"Content-Type: application/json\" \\\n"
            "  -d '{\"hr_bpm\":72,\"steps\":4300,\"spo2_pct\":97,\n"
            "       \"sleep_hours\":7.2,\"device\":\"My Watch\"}'\n\n"
            "Accepted field names include hr_bpm / hr / heart_rate, spo2 / spo2_pct,\n"
            "steps / step_count, sleep_hours, wrist_temp_c, rr_ms, battery_pct.\n"
            "Out-of-range values are rejected, never silently corrected."
        )
        example.setMaximumHeight(150)
        ingest.add_widget(example)
        self._root.addWidget(ingest)

        controls = SectionCard("Manual entry and simulation")
        row1 = QHBoxLayout()
        for lbl, attr in (("Heart rate (bpm)", "hr"), ("SpO₂ (%)", "spo2"),
                          ("Steps", "steps"), ("Sleep (h)", "sleep"),
                          ("Wrist temp (°C)", "temp")):
            row1.addWidget(QLabel(lbl))
            le = QLineEdit()
            le.setPlaceholderText("—")
            setattr(self, f"in_{attr}", le)
            row1.addWidget(le)
        controls.add_layout(row1)
        btn_row = QHBoxLayout()
        self.add_btn = QPushButton("Save reading")
        self.add_btn.setObjectName("PrimaryButton")
        self.add_btn.clicked.connect(self._add_manual)
        self.sim_btn = QPushButton("Start demo watch")
        self.sim_btn.setObjectName("SecondaryButton")
        self.sim_btn.clicked.connect(self._toggle_sim)
        self.clear_btn = QPushButton("Clear simulated data")
        self.clear_btn.setObjectName("SecondaryButton")
        self.clear_btn.clicked.connect(self._clear_sim)
        for b in (self.add_btn, self.sim_btn, self.clear_btn):
            btn_row.addWidget(b)
        btn_row.addStretch(1)
        controls.add_layout(btn_row)
        self._root.addWidget(controls)

        self._sim = None
        self._sim_timer = QTimer(self)
        self._sim_timer.timeout.connect(self._sim_tick)
        self.refresh_results()

    def _add_manual(self) -> None:
        if self.store is None:
            return
        def val(attr):
            t = getattr(self, f"in_{attr}").text().strip()
            try:
                return float(t) if t else None
            except ValueError:
                return None
        s = watch.WatchSample(ts=time.time(), hr_bpm=val("hr"), spo2_pct=val("spo2"),
                              steps=int(val("steps")) if val("steps") is not None else None,
                              sleep_hours=val("sleep"), wrist_temp_c=val("temp"),
                              device="Manual entry", source="manual")
        res = self.store.add(s)
        for attr in ("hr", "spo2", "steps", "sleep", "temp"):
            getattr(self, f"in_{attr}").clear()
        self.refresh_results()
        if not res["accepted"]:
            self.coverage_label.setText("Rejected: " + res.get("reason", "no usable measurement"))

    def _toggle_sim(self) -> None:
        if self._sim_timer.isActive():
            self._sim_timer.stop()
            self._sim = None
            self.sim_btn.setText("Start demo watch")
        else:
            self._sim = watch.SimulatedWatch()
            for s in self._sim.backfill_days(days=14):
                self.store.add(s)
            self._sim_timer.start(5000)
            self.sim_btn.setText("Stop demo watch")
        self.refresh_results()

    def _sim_tick(self) -> None:
        if self._sim is not None and self.store is not None:
            self.store.add(self._sim.sample())
        self.refresh_results()

    def _clear_sim(self) -> None:
        if self.store is not None:
            self.store.clear(source_filter="simulated")
        self.refresh_results()

    def refresh_results(self) -> None:
        if self.store is None:
            return
        s = self.store.summary()
        latest = s.get("latest") or {}
        self.tiles["HR"].set(f"{latest.get('hr_bpm'):.0f}" if latest.get("hr_bpm") else "—", "bpm")
        self.tiles["HRV (RMSSD)"].set(
            f"{latest.get('rmssd_ms'):.0f}" if latest.get("rmssd_ms") else "—", "ms")
        self.tiles["SpO₂ (estimate)"].set(
            f"{latest.get('spo2_pct'):.0f}" if latest.get("spo2_pct") else "—", "% (wellness)")
        self.tiles["Steps 24 h"].set(
            f"{s.get('steps_24h'):,}" if s.get("steps_24h") else "—", "steps")
        self.tiles["Sleep"].set(
            f"{latest.get('sleep_hours'):.1f}" if latest.get("sleep_hours") else "—", "hours")
        self.tiles["Wrist temp"].set(
            f"{latest.get('wrist_temp_c'):.1f}" if latest.get("wrist_temp_c") else "—", "°C")
        self.battery_label.setText(
            f"Device: {s.get('device') or 'none'}   ·   Battery: "
            f"{latest.get('battery_pct'):.0f}%" if latest.get("battery_pct") is not None
            else f"Device: {s.get('device') or 'none'}")
        self.coverage_label.setText(
            f"Coverage {s.get('covered_days', 0)}/{s.get('window_days', 14)} days "
            f"({(s.get('sufficiency') or 0) * 100:.0f}% of window)   ·   "
            f"{s.get('samples_24h', 0)} readings in 24 h   ·   {s.get('samples_total', 0)} total")


# ==========================================================================
# LATEST EVIDENCE
# ==========================================================================
class PcodEvidencePage(_BasePcodPage):
    """The cited, offline 'latest data' registry."""

    def __init__(self, store=None, parent=None):
        super().__init__(store, parent)
        self._root.addWidget(page_title(
            "📚  Latest evidence",
            f"Structured, offline, fully cited registry — last verified {evidence.LAST_VERIFIED}"))

        head = SectionCard("What changed recently")
        box = QVBoxLayout()
        for h in evidence.HEADLINES:
            hl = QLabel(f"<b>{h['date']} — [{h['tag']}] {h['headline']}</b><br>{h['detail']}")
            hl.setWordWrap(True)
            hl.setTextFormat(Qt.TextFormat.RichText)
            sub = QLabel(" · ".join(f"{s['org']} ({s['year']})" for s in h["sources"]))
            sub.setObjectName("SmallMuted")
            sub.setWordWrap(True)
            box.addWidget(hl)
            box.addWidget(sub)
            line = QFrame()
            line.setFrameShape(QFrame.Shape.HLine)
            box.addWidget(line)
        head.add_layout(box)
        self._root.addWidget(head)

        registry = SectionCard("Full registry")
        for topic in evidence.topics():
            sec = CollapsibleSection(topic)
            txt = QTextEdit()
            txt.setReadOnly(True)
            parts = []
            for i in evidence.by_topic(topic):
                meta = f"[{i.grade}]" + (f" rec {i.rec_id}" if i.rec_id else "") + f" · {i.applies_to}"
                parts.append(f"{meta}\n{i.statement}")
                if i.note:
                    parts.append(f"NOTE: {i.note}")
                parts.append("   " + " | ".join(f"{s.org} ({s.year}) — {s.url}" for s in i.sources))
                parts.append("")
            txt.setPlainText("\n".join(parts))
            txt.setMinimumHeight(120)
            sec.add_widget(txt)
            registry.add_widget(sec)
        self._root.addWidget(registry)

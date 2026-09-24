"""Tests for the V9.0 PCOD/PMOS modules: the two sections, the watch link,
and parity between the Python engines and the JS mirror used by the
single-file portable build.
"""
from __future__ import annotations

import datetime as dt
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.pcod import assessment, complications, criteria, evidence, watch  # noqa: E402

TODAY = dt.date(2026, 9, 25)
DAYS_AGO = lambda n: (TODAY - dt.timedelta(days=n)).isoformat()  # noqa: E731


# ==========================================================================
# Evidence registry
# ==========================================================================
class TestEvidence:
    def test_every_item_has_a_real_citation(self):
        for item in evidence.EVIDENCE:
            assert item.sources, f"{item.id} has no source"
            for s in item.sources:
                assert s.url.startswith("http"), f"{item.id} bad url"
                assert s.org and s.title
                assert 1990 <= s.year <= 2030

    def test_ids_are_unique(self):
        ids = [i.id for i in evidence.EVIDENCE]
        assert len(ids) == len(set(ids))

    def test_amh_has_no_invented_threshold(self):
        """The 2023 guideline gives no universal AMH cut-off — we must not invent one."""
        amh = evidence.get("dx.amh.adults")
        assert amh is not None
        assert "assay" in amh.note.lower() or "population" in amh.note.lower()
        # No numeric ng/mL threshold anywhere in the statement or note.
        for token in ("ng/mL", "pmol/L"):
            assert token not in amh.statement

    def test_the_2026_rename_is_recorded(self):
        rename = evidence.get("name.2026.pmos")
        assert rename is not None
        assert "PMOS" in rename.statement
        assert any(s.year == 2026 for s in rename.sources)
        unchanged = evidence.get("name.2026.unchanged")
        assert "E28.2" in unchanged.statement

    def test_headlines_are_sourced(self):
        for h in evidence.HEADLINES:
            assert h["sources"], "headline without sources"
            assert h["date"] and h["headline"] and h["detail"]

    def test_citations_resolve(self):
        cites = evidence.citations_for(["dx.pcom.fnpo", "cx.glucose.all"])
        assert cites, "no citations resolved"
        assert all(c["url"].startswith("http") for c in cites)


# ==========================================================================
# Section 1 — detection
# ==========================================================================
class TestDetection:
    def test_nothing_recorded_is_unknown_not_absent(self):
        r = criteria.evaluate(criteria.PatientInputs(), None)
        assert r.verdict == criteria.VERDICT_UNKNOWN
        assert r.unknown_count == 3
        assert all(c.status == criteria.UNKNOWN for c in r.criteria)

    def test_adult_two_of_three_meets_criteria(self):
        p = criteria.PatientInputs(age_years=24, years_post_menarche=11,
                                   usual_cycle_length_days=52, hirsutism=True, fnpo=24,
                                   tsh_checked=True, prolactin_checked=True, ohp17_checked=True)
        r = criteria.evaluate(p)
        assert r.life_stage == "adult"
        assert r.verdict == criteria.VERDICT_MEETS
        assert r.exclusions_complete
        assert r.ultrasound_needed is False

    def test_ultrasound_not_needed_when_cycles_and_hyperandrogenism_present(self):
        """Guideline 1.4.9: with both, an ultrasound is not necessary."""
        p = criteria.PatientInputs(age_years=24, years_post_menarche=11,
                                   usual_cycle_length_days=52, hirsutism=True)
        r = criteria.evaluate(p)
        assert r.verdict == criteria.VERDICT_MEETS
        assert r.ultrasound_needed is False

    def test_adolescent_uses_the_45_day_threshold(self):
        # 2 years post-menarche: threshold is 45 days, so 40 is NOT irregular.
        p = criteria.PatientInputs(age_years=16, years_post_menarche=2,
                                   usual_cycle_length_days=40, hirsutism=True)
        r = criteria.evaluate(p)
        assert r.life_stage == "adolescent"
        ov = next(c for c in r.criteria if c.key == "ovulatory")
        assert ov.status == criteria.ABSENT
        assert r.verdict == criteria.VERDICT_NOT_MET

    def test_adolescent_50_days_is_irregular(self):
        p = criteria.PatientInputs(age_years=16, years_post_menarche=2,
                                   usual_cycle_length_days=50, hirsutism=True)
        r = criteria.evaluate(p)
        ov = next(c for c in r.criteria if c.key == "ovulatory")
        assert ov.status == criteria.PRESENT
        assert r.verdict == criteria.VERDICT_MEETS   # both required, both present

    def test_first_year_post_menarche_cannot_be_scored(self):
        p = criteria.PatientInputs(age_years=12, years_post_menarche=0)
        r = criteria.evaluate(p)
        ov = next(c for c in r.criteria if c.key == "ovulatory")
        assert ov.status == criteria.UNKNOWN
        assert "menarche" in ov.detail

    def test_adult_35_day_threshold(self):
        p = criteria.PatientInputs(age_years=30, years_post_menarche=17,
                                   usual_cycle_length_days=40)
        ov = next(c for c in criteria.evaluate(p).criteria if c.key == "ovulatory")
        assert ov.status == criteria.PRESENT

    def test_amh_without_lab_cutoff_stays_unknown(self):
        p = criteria.PatientInputs(age_years=26, years_post_menarche=14, amh_ng_ml=8.2)
        m = next(c for c in criteria.evaluate(p).criteria if c.key == "morphology")
        assert m.status == criteria.UNKNOWN
        assert any("cut-off" in b for b in m.blockers)

    def test_amh_with_lab_cutoff_resolves(self):
        p = criteria.PatientInputs(age_years=26, years_post_menarche=14,
                                   amh_ng_ml=8.2, amh_lab_cutoff=4.7)
        m = next(c for c in criteria.evaluate(p).criteria if c.key == "morphology")
        assert m.status == criteria.PRESENT

    def test_amh_rejected_in_adolescents(self):
        p = criteria.PatientInputs(age_years=16, years_post_menarche=2,
                                   amh_ng_ml=9.0, amh_lab_cutoff=4.7)
        m = next(c for c in criteria.evaluate(p).criteria if c.key == "morphology")
        assert m.status == criteria.UNKNOWN
        assert any("adolescent" in b.lower() for b in m.blockers)

    def test_unknown_life_stage_does_not_block_adult_route(self):
        p = criteria.PatientInputs(amh_ng_ml=9.0, amh_lab_cutoff=4.7)
        m = next(c for c in criteria.evaluate(p).criteria if c.key == "morphology")
        assert m.status == criteria.PRESENT
        assert any("since your first period" in b for b in m.blockers)

    def test_exclusions_block_the_verdict(self):
        p = criteria.PatientInputs(age_years=24, years_post_menarche=11,
                                   usual_cycle_length_days=52, hirsutism=True)
        r = criteria.evaluate(p)
        assert r.verdict == criteria.VERDICT_MEETS
        assert r.exclusions_complete is False
        assert len(r.exclusions_missing) == 3
        assert "excluded" in r.explanation.lower()

    def test_watch_data_never_establishes_a_criterion(self):
        """A fully populated watch must not flip any criterion."""
        wc = criteria.WatchContext(resting_hr_bpm=88, rmssd_ms=12, steps_last_24h=900,
                                   sleep_hours_last_night=4.0, spo2_pct=91,
                                   data_sufficiency=1.0, days_of_data=30,
                                   device_name="Test Watch")
        r = criteria.evaluate(criteria.PatientInputs(), wc)
        assert r.verdict == criteria.VERDICT_UNKNOWN
        assert "cannot" in r.watch_note


# ==========================================================================
# Section 2 — complications
# ==========================================================================
class TestComplications:
    def test_empty_input_is_unknown_not_up_to_date(self):
        r = complications.evaluate(complications.ClinicalInputs(), today=TODAY)
        assert r.counts.get(complications.UP_TO_DATE, 0) == 0
        # 7 domains need an assessment; liver/endometrial/fertility are
        # explicitly NOT screened routinely per current guidance.
        assert r.counts.get(complications.UNKNOWN, 0) == 7
        assert r.counts.get(complications.NOT_INDICATED, 0) == 3

    def test_never_tested_is_unknown(self):
        r = complications.evaluate(complications.ClinicalInputs(bmi=30), today=TODAY)
        g = next(d for d in r.domains if d.key == "glucose")
        assert g.status == complications.UNKNOWN

    def test_tested_within_interval_is_up_to_date(self):
        r = complications.evaluate(
            complications.ClinicalInputs(hba1c_pct=5.2, last_glucose_test_date=DAYS_AGO(120)),
            today=TODAY)
        g = next(d for d in r.domains if d.key == "glucose")
        assert g.status == complications.UP_TO_DATE

    def test_high_risk_profile_shortens_the_glucose_interval(self):
        base = dict(hba1c_pct=5.4, last_glucose_test_date=DAYS_AGO(400))
        lean = complications.evaluate(complications.ClinicalInputs(**base), today=TODAY)
        risky = complications.evaluate(
            complications.ClinicalInputs(**base, bmi=31, family_history_t2dm=True), today=TODAY)
        g1 = next(d for d in lean.domains if d.key == "glucose")
        g2 = next(d for d in risky.domains if d.key == "glucose")
        assert g1.status == complications.UP_TO_DATE       # 3-year interval
        assert g2.status in (complications.DUE, complications.OVERDUE)  # 1-year interval

    def test_long_overdue_is_overdue(self):
        r = complications.evaluate(
            complications.ClinicalInputs(hba1c_pct=5.3, last_glucose_test_date=DAYS_AGO(2400)),
            today=TODAY)
        g = next(d for d in r.domains if d.key == "glucose")
        assert g.status == complications.OVERDUE

    def test_slightly_past_interval_is_due_not_overdue(self):
        r = complications.evaluate(
            complications.ClinicalInputs(hba1c_pct=5.3, last_glucose_test_date=DAYS_AGO(1500)),
            today=TODAY)
        g = next(d for d in r.domains if d.key == "glucose")
        assert g.status == complications.DUE

    def test_prediabetes_labs_escalate_to_action_needed(self):
        r = complications.evaluate(
            complications.ClinicalInputs(hba1c_pct=6.1, fasting_glucose_mg_dl=118,
                                         last_glucose_test_date=DAYS_AGO(30)), today=TODAY)
        g = next(d for d in r.domains if d.key == "glucose")
        assert g.status == complications.ACTION_NEEDED
        assert any("prediabetes" in s for s in g.signals)

    def test_asian_bmi_threshold_is_23(self):
        c = complications.ClinicalInputs(bmi=24, asian_ethnicity=True,
                                         last_weight_date=DAYS_AGO(10))
        w = next(d for d in complications.evaluate(c, today=TODAY).domains if d.key == "weight")
        assert w.status in (complications.DUE, complications.ACTION_NEEDED)
        c2 = complications.ClinicalInputs(bmi=24, asian_ethnicity=False,
                                          last_weight_date=DAYS_AGO(10))
        w2 = next(d for d in complications.evaluate(c2, today=TODAY).domains if d.key == "weight")
        assert w2.status == complications.UP_TO_DATE

    def test_nafld_and_endometrial_are_never_routinely_screened(self):
        c = complications.ClinicalInputs(bmi=34, hba1c_pct=6.4, triglycerides_mg_dl=250,
                                         alt_u_l=80)
        r = complications.evaluate(c, today=TODAY)
        liver = next(d for d in r.domains if d.key == "liver")
        endo = next(d for d in r.domains if d.key == "endometrial")
        assert liver.status == complications.NOT_INDICATED
        assert endo.status == complications.NOT_INDICATED

    def test_abnormal_bleeding_escalates_endometrial(self):
        r = complications.evaluate(
            complications.ClinicalInputs(abnormal_uterine_bleeding=True), today=TODAY)
        endo = next(d for d in r.domains if d.key == "endometrial")
        assert endo.status == complications.ACTION_NEEDED

    def test_prolonged_amenorrhoea_escalates_endometrial(self):
        r = complications.evaluate(
            complications.ClinicalInputs(amenorrhoea_days=120), today=TODAY)
        endo = next(d for d in r.domains if d.key == "endometrial")
        assert endo.status == complications.ACTION_NEEDED

    def test_osa_is_symptom_screened_only(self):
        asym = complications.evaluate(
            complications.ClinicalInputs(snoring=False, daytime_somnolence=False,
                                         witnessed_apnoea=False), today=TODAY)
        sym = complications.evaluate(
            complications.ClinicalInputs(snoring=True, daytime_somnolence=True), today=TODAY)
        d1 = next(d for d in asym.domains if d.key == "osa")
        d2 = next(d for d in sym.domains if d.key == "osa")
        assert d1.status == complications.UP_TO_DATE
        assert d2.status == complications.ACTION_NEEDED
        assert any("routine screening" in d.why.lower() or "not recommended" in d.why.lower()
                   for d in (d1, d2))

    def test_mental_health_screening_escalates_on_phq9(self):
        r = complications.evaluate(
            complications.ClinicalInputs(phq9_score=14, gad7_score=11,
                                         last_mental_health_screen_date=DAYS_AGO(10)), today=TODAY)
        m = next(d for d in r.domains if d.key == "mental_health")
        assert m.status == complications.ACTION_NEEDED

    def test_pregnancy_at_26_weeks_flags_gdm_window(self):
        r = complications.evaluate(
            complications.ClinicalInputs(pregnant=True, gestation_weeks=26), today=TODAY)
        rep = next(d for d in r.domains if d.key == "reproductive")
        assert rep.status == complications.ACTION_NEEDED
        assert any("24–28" in s or "24-28" in s for s in rep.signals)

    def test_cardiovascular_unknown_until_enough_inputs(self):
        few = complications.evaluate(complications.ClinicalInputs(bmi=22), today=TODAY)
        c1 = next(d for d in few.domains if d.key == "cardiovascular")
        assert c1.status == complications.UNKNOWN
        many = complications.evaluate(
            complications.ClinicalInputs(bmi=22, systolic_bp=112, ldl_mg_dl=95, hdl_mg_dl=62,
                                         triglycerides_mg_dl=96, current_smoker=False,
                                         moderate_activity_min_per_week=220,
                                         family_history_t2dm=False), today=TODAY)
        c2 = next(d for d in many.domains if d.key == "cardiovascular")
        assert c2.status == complications.UP_TO_DATE

    def test_every_domain_is_cited(self):
        r = complications.evaluate(complications.ClinicalInputs(), today=TODAY)
        for d in r.domains:
            assert d.evidence_ids, f"{d.key} has no citations"
            for eid in d.evidence_ids:
                assert evidence.get(eid) is not None, f"{d.key} -> unknown evidence id {eid}"


# ==========================================================================
# Watch link
# ==========================================================================
class TestWatch:
    def test_out_of_range_values_are_rejected_not_clamped(self):
        s = watch.WatchSample(ts=0, hr_bpm=400, spo2_pct=50)
        problems = watch.validate(s)
        assert s.hr_bpm is None and s.spo2_pct is None
        assert len(problems) == 2

    def test_valid_sample_passes(self):
        s = watch.WatchSample(ts=0, hr_bpm=72, spo2_pct=97, steps=4000)
        assert watch.validate(s) == []

    def test_rmssd_needs_three_beats(self):
        assert watch.WatchSample(ts=0, rr_ms=[800.0, 810.0]).rmssd_ms is None
        assert watch.WatchSample(ts=0, rr_ms=[800.0, 810.0, 790.0]).rmssd_ms is not None

    def test_payload_field_aliases(self):
        s = watch.from_payload({"heart_rate": 70, "spo2": 96, "step_count": 100, "batt": 55})
        assert s.hr_bpm == 70 and s.spo2_pct == 96 and s.steps == 100 and s.battery_pct == 55

    def test_empty_payload_is_refused(self):
        store = watch.WatchStore(path=Path(tempfile.mkdtemp()) / "w.json")
        assert store.add(watch.WatchSample(ts=0))["accepted"] is False

    def test_store_round_trip_and_coverage(self, tmp_path):
        p = tmp_path / "w.json"
        st = watch.WatchStore(path=p)
        for i in range(5):
            st.add(watch.WatchSample(ts=watch.time.time() - i * 86400, hr_bpm=70 + i,
                                     rr_ms=[800.0, 810.0, 795.0]))
        st2 = watch.WatchStore(path=p)
        assert st2.samples
        assert st2.covered_days() >= 4
        summ = st2.summary()
        assert summ["connected"] and summ["hr_mean_24h"] > 0

    def test_simulated_data_is_labelled(self):
        sim = watch.SimulatedWatch()
        s = sim.sample()
        assert s.source == "simulated"
        assert s.device

    def test_simulated_can_be_cleared_separately(self, tmp_path):
        st = watch.WatchStore(path=tmp_path / "w.json")
        st.add(watch.WatchSample(ts=1, hr_bpm=70, source="ble"))
        st.add(watch.WatchSample(ts=2, hr_bpm=71, source="simulated"))
        assert st.clear(source_filter="simulated") == 1
        assert all(s.source == "ble" for s in st.samples)

    def test_backfill_generates_multi_day_history(self):
        out = watch.SimulatedWatch().backfill_days(days=14, per_day=2)
        assert len(out) == 28
        days = {watch.time.strftime("%Y-%m-%d", watch.time.localtime(s.ts)) for s in out}
        assert len(days) >= 13


# ==========================================================================
# Combined assessment
# ==========================================================================
class TestAssessment:
    def test_assessment_has_both_sections(self, tmp_path):
        st = watch.WatchStore(path=tmp_path / "w.json")
        a = assessment.build(
            {"age_years": 24, "years_post_menarche": 11, "usual_cycle_length_days": 52,
             "hirsutism": True, "tsh_checked": True, "prolactin_checked": True,
             "ohp17_checked": True},
            {"bmi": 28, "asian_ethnicity": True, "phq9_score": 12}, st)
        d = a.as_dict()
        assert "section1_detection" in d and "section2_complications" in d
        assert d["section1_detection"]["verdict"] == criteria.VERDICT_MEETS
        assert d["section2_complications"]["counts"]

    def test_text_report_mentions_both_sections_and_safety(self, tmp_path):
        st = watch.WatchStore(path=tmp_path / "w.json")
        a = assessment.build({}, {}, st)
        txt = assessment.to_text_report(a)
        assert "SECTION 1" in txt and "SECTION 2" in txt
        assert "NOT a diagnosis" in txt

    def test_report_never_fabricates_a_risk_percentage(self, tmp_path):
        """No invented "your risk is X%" figure may appear anywhere."""
        import re as _re
        st = watch.WatchStore(path=tmp_path / "w.json")
        risk_like = _re.compile(r"risk\D{0,20}\d{1,3}\s*%|\d{1,3}\s*%\s*(chance|risk|probability)")
        for profile in ({}, {"age_years": 30}, {"bmi": 40, "hba1c_pct": 9}):
            txt = assessment.to_text_report(assessment.build({}, profile, st))
            assert not risk_like.search(txt), "report appears to state a risk percentage"


# ==========================================================================
# Parity: Python engines vs the JS mirror in the portable build
# ==========================================================================
NODE = shutil.which("node")

FIXTURES = [
    ("empty", {}, {}),
    ("classic_adult",
     {"age_years": 24, "years_post_menarche": 11, "usual_cycle_length_days": 52,
      "hirsutism": True, "fnpo": 24, "tsh_checked": True, "prolactin_checked": True,
      "ohp17_checked": True}, {}),
    ("cycles_and_hirsutism_only",
     {"age_years": 24, "years_post_menarche": 11, "usual_cycle_length_days": 52,
      "hirsutism": True}, {}),
    ("adolescent_40d",
     {"age_years": 16, "years_post_menarche": 2, "usual_cycle_length_days": 40,
      "hirsutism": True}, {}),
    ("adolescent_50d",
     {"age_years": 16, "years_post_menarche": 2, "usual_cycle_length_days": 50,
      "hirsutism": True}, {}),
    ("first_year_menarche", {"age_years": 12, "years_post_menarche": 0}, {}),
    ("amh_no_cutoff", {"age_years": 26, "years_post_menarche": 14, "amh_ng_ml": 8.2}, {}),
    ("amh_with_cutoff",
     {"age_years": 26, "years_post_menarche": 14, "amh_ng_ml": 8.2, "amh_lab_cutoff": 4.7}, {}),
    ("amh_adolescent",
     {"age_years": 16, "years_post_menarche": 2, "amh_ng_ml": 9.0, "amh_lab_cutoff": 4.7}, {}),
    ("regular_normal_scan",
     {"age_years": 30, "years_post_menarche": 17, "usual_cycle_length_days": 28,
      "cycles_last_year": 13, "hirsutism": False, "acne": False,
      "female_pattern_hair_loss": False, "fnpo": 8, "ovarian_volume_ml": 6.0}, {}),
    ("on_contraception",
     {"age_years": 28, "years_post_menarche": 15, "on_hormonal_contraception": True}, {}),
    ("cx_overdue_metabolic",
     {}, {"age_years": 31, "bmi": 29.4, "waist_cm": 92, "systolic_bp": 142,
          "diastolic_bp": 91, "asian_ethnicity": True, "hba1c_pct": 6.1,
          "fasting_glucose_mg_dl": 118, "ldl_mg_dl": 168, "hdl_mg_dl": 42,
          "triglycerides_mg_dl": 210, "alt_u_l": 58, "family_history_t2dm": True,
          "current_smoker": False, "moderate_activity_min_per_week": 60,
          "snoring": True, "daytime_somnolence": True, "phq9_score": 14, "gad7_score": 11,
          "last_glucose_test_date": DAYS_AGO(1500), "last_lipid_test_date": DAYS_AGO(1200),
          "last_bp_date": DAYS_AGO(800), "last_weight_date": DAYS_AGO(900),
          "last_mental_health_screen_date": DAYS_AGO(700), "amenorrhoea_days": 120}),
    ("cx_all_up_to_date",
     {}, {"age_years": 27, "bmi": 22.0, "systolic_bp": 112, "diastolic_bp": 72,
          "asian_ethnicity": True, "hba1c_pct": 5.2, "fasting_glucose_mg_dl": 88,
          "ldl_mg_dl": 95, "hdl_mg_dl": 62, "triglycerides_mg_dl": 96,
          "family_history_t2dm": False, "current_smoker": False,
          "moderate_activity_min_per_week": 220, "snoring": False,
          "daytime_somnolence": False, "witnessed_apnoea": False,
          "phq9_score": 3, "gad7_score": 2, "pregnant": False,
          "trying_to_conceive": False, "amenorrhoea_days": 28,
          "abnormal_uterine_bleeding": False,
          "last_glucose_test_date": DAYS_AGO(120), "last_lipid_test_date": DAYS_AGO(120),
          "last_bp_date": DAYS_AGO(60), "last_weight_date": DAYS_AGO(60),
          "last_mental_health_screen_date": DAYS_AGO(90)}),
    ("cx_pregnant_26w", {}, {"pregnant": True, "gestation_weeks": 26, "age_years": 30}),
    ("cx_trying_18m", {}, {"trying_to_conceive": True, "months_trying_to_conceive": 18,
                           "bmi": 29, "asian_ethnicity": True}),
]


def _python_results(today_iso: str) -> dict:
    import datetime as _dt
    today = _dt.date.fromisoformat(today_iso)
    out = {}
    for name, profile, clinical in FIXTURES:
        s1 = criteria.evaluate(criteria.PatientInputs.from_dict(profile))
        s2 = complications.evaluate(complications.ClinicalInputs.from_dict(clinical), today=today)
        out[name] = {
            "s1": {"life_stage": s1.life_stage, "verdict": s1.verdict,
                   "criteria": {c.key: c.status for c in s1.criteria},
                   "us_needed": s1.ultrasound_needed,
                   "exclusions_complete": s1.exclusions_complete},
            "s2": {"domains": {d.key: d.status for d in s2.domains}, "counts": s2.counts},
        }
    return out


def _js_results(today_iso: str) -> dict:
    root = Path(__file__).resolve().parents[1]
    engine = (root / "web" / "static" / "engine.js").read_text()
    fixtures = [{"name": n, "profile": p, "clinical": c} for n, p, c in FIXTURES]
    script = (
        engine + "\n"
        "const TODAY = new Date(%s + 'T00:00:00');\n" % json.dumps(today_iso)
        + "const fixtures = " + json.dumps(fixtures) + ";\n"
        "const out = {};\n"
        "for (const f of fixtures) {\n"
        "  const s1 = CHRONO_ENGINE.evaluateDetection(f.profile);\n"
        "  const s2 = CHRONO_ENGINE.evaluateComplications(f.clinical, TODAY);\n"
        "  out[f.name] = {\n"
        "    s1: {life_stage: s1.life_stage, verdict: s1.verdict,\n"
        "         criteria: Object.fromEntries(s1.criteria.map(c => [c.key, c.status])),\n"
        "         us_needed: s1.ultrasound_needed,\n"
        "         exclusions_complete: s1.exclusions_complete},\n"
        "    s2: {domains: Object.fromEntries(s2.domains.map(d => [d.key, d.status])),\n"
        "         counts: s2.counts}\n"
        "  };\n"
        "}\n"
        "console.log(JSON.stringify(out));\n"
    )
    tmp = Path(tempfile.mkdtemp()) / "parity.js"
    tmp.write_text(script)
    res = subprocess.run([NODE, str(tmp)], capture_output=True, text=True, timeout=60)
    if res.returncode != 0:
        raise AssertionError(f"node failed: {res.stderr}")
    return json.loads(res.stdout)


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_js_engine_matches_python_on_every_fixture():
    """The portable single-file build re-implements both engines in JS.

    This test is the guarantee that the two never drift: it runs the same
    fixtures through both and demands identical verdicts and statuses.
    """
    today = "2026-09-25"
    py = _python_results(today)
    js = _js_results(today)
    assert set(py) == set(js)
    for name in py:
        assert py[name]["s1"] == js[name]["s1"], f"Section 1 mismatch on {name}"
        assert py[name]["s2"] == js[name]["s2"], f"Section 2 mismatch on {name}"


def test_portable_build_includes_everything(tmp_path):
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "tools"))
    import build_portable
    out = build_portable.build(tmp_path / "portable.html")
    html = out.read_text()
    assert "CHRONO_ENGINE" in html
    assert "CHRONO_STANDALONE = true" in html
    assert "Polyendocrine Metabolic Ovarian Syndrome" in html
    # no external references left
    for bad in ('src="/static/', 'href="/static/', "cdn.", "https://fonts"):
        assert bad not in html, f"portable build still references {bad}"
    assert html.count("<style>") == 1


def test_portable_build_carries_the_domain_prose():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "tools"))
    import build_portable
    import tempfile as tf
    out = build_portable.build(Path(tf.mkdtemp()) / "p.html")
    html = out.read_text()
    # prose generated from the Python engines must be present
    assert "Glycaemic status should be assessed at diagnosis" in html
    assert "Polycystic ovarian morphology" in html

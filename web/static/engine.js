/* CHRONO PCOD/PMOS — client-side mirror of the two clinical engines.
 *
 * This exists ONLY so the single-file portable edition (file://) can score
 * Section 1 and Section 2 with no server. The canonical implementations are
 * src/pcod/criteria.py and src/pcod/complications.py; the server always uses
 * those. `tests/test_portable_parity.py` runs the same fixtures through both
 * and fails if verdicts or statuses ever disagree, so this file cannot drift
 * silently.
 *
 * Scope note: statuses, counts and verdicts are authoritative here. Prose is
 * intentionally kept close to the Python but is not compared character-wise.
 */
(function (root) {
  'use strict';

  const PRESENT = 'PRESENT', ABSENT = 'ABSENT', UNKNOWN = 'UNKNOWN';
  const MEETS = 'MEETS_CRITERIA', NOT_MET = 'DOES_NOT_MEET', CANT = 'CANNOT_BE_DETERMINED';

  const ACT = 'ACTION_NEEDED', DUE_S = 'DUE', OVERDUE = 'OVERDUE',
        UTD = 'UP_TO_DATE', NI = 'NOT_INDICATED';

  const num = v => (v === null || v === undefined || v === '' || Number.isNaN(Number(v)))
    ? null : Number(v);
  const has = v => v !== null && v !== undefined && v !== '';

  function daysSince(d, today) {
    if (!d) return null;
    const t = new Date(d + 'T00:00:00');
    if (isNaN(t)) return null;
    return Math.round(((today || new Date()) - t) / 86400000);
  }
  function intervalStatus(last, intervalDays, today) {
    const ds = daysSince(last, today);
    if (ds === null) return {status: UNKNOWN, ds: null};
    if (ds <= intervalDays) return {status: UTD, ds: ds};
    if (ds <= intervalDays * 1.5) return {status: DUE_S, ds: ds};
    return {status: OVERDUE, ds: ds};
  }

  /* ==================================================================
     SECTION 1 — PCOD / PMOS detection
     ================================================================== */
  function lifeStage(p) {
    const ypm = num(p.years_post_menarche);
    if (ypm !== null) return ypm < 8 ? 'adolescent' : 'adult';
    const age = num(p.age_years);
    if (age !== null) return age < 18 ? 'adolescent' : 'adult';
    return 'unknown';
  }
  function cycleThreshold(p) {
    const ypm = num(p.years_post_menarche);
    if (ypm !== null) { if (ypm < 1) return null; if (ypm < 3) return 45; return 35; }
    const age = num(p.age_years);
    if (age !== null) return age >= 18 ? 35 : 45;
    return 35;
  }

  function criterionOvulatory(p, stage) {
    const blockers = [], sig = [];
    const thr = cycleThreshold(p);
    if (thr === null) {
      return {key: 'ovulatory', label: 'Ovulatory dysfunction', status: UNKNOWN,
        detail: 'Within the first year after menarche, irregular cycles are a normal part of pubertal transition, so this criterion cannot be applied yet.',
        blockers: ['Reassess once at least 1 year has passed since menarche.']};
    }
    if (p.on_hormonal_contraception === true)
      sig.push('Currently on hormonal contraception — cycle pattern cannot be interpreted.');
    let irregular = null;
    const cl = num(p.usual_cycle_length_days);
    if (cl !== null) {
      irregular = cl < 21 || cl > thr;
      sig.push(`Usual cycle length ${cl} days (irregular = <21 or >${thr} days).`);
    }
    const cy = num(p.cycles_last_year);
    if (cy !== null && cy < 8) { irregular = true; sig.push(`${cy} cycles in the last year (fewer than 8).`); }
    const dslp = num(p.days_since_last_period);
    const longest = num(p.longest_cycle_days);
    if (dslp !== null && dslp > 90) { irregular = true; sig.push(`${dslp} days since the last period (any single cycle >90 days is irregular).`); }
    else if (longest !== null && longest > thr) { irregular = true; sig.push(`Longest recorded cycle ${longest} days (> ${thr}).`); }
    const prog = num(p.luteal_progesterone_nmol_l);
    if (prog !== null) {
      const ov = prog > 15;
      sig.push(`Luteal progesterone ${prog} nmol/L — ` + (ov ? 'consistent with recent ovulation.' : 'not consistent with recent ovulation.'));
      if (ov && irregular === null) irregular = false;
    }
    let status;
    if (p.on_hormonal_contraception === true && irregular === null) {
      status = UNKNOWN;
      blockers.push('Record cycle history off hormonal contraception (or ≥3 months after stopping).');
    } else if (irregular === true) status = PRESENT;
    else if (irregular === false) status = ABSENT;
    else {
      status = UNKNOWN;
      blockers.push('Record usual cycle length, number of cycles in the last year, or days since the last period.');
      blockers.push('If cycles look regular but ovulation is uncertain, a luteal-phase progesterone can confirm it.');
    }
    if (!sig.length) sig.push('No cycle information recorded.');
    return {key: 'ovulatory', label: 'Ovulatory dysfunction', status: status,
      detail: sig.join(' '), blockers: blockers};
  }

  function criterionHyperandrogenism(p) {
    const blockers = [], clinical = [], biochem = [];
    let clinPresent = null, bioPresent = null;
    const fg = num(p.ferriman_gallwey);
    if (p.hirsutism === true || (fg !== null && fg >= 4)) {
      clinPresent = true;
      clinical.push(`Hirsutism present${fg !== null ? ` (Ferriman–Gallwey ${fg})` : ''} — alone this predicts biochemical hyperandrogenism.`);
    } else if (p.hirsutism === false) clinical.push('Hirsutism recorded as absent.');
    const weak = [];
    if (p.acne === true) weak.push('acne');
    if (p.female_pattern_hair_loss === true) weak.push('female-pattern hair loss');
    if (weak.length) clinical.push('Present but weak predictors on their own: ' + weak.join(', ') + '.');
    if (clinPresent === null && !weak.length)
      blockers.push('Record a clinical examination for hirsutism, acne and female-pattern hair loss.');

    const tt = num(p.total_testosterone_nmol_l), ft = num(p.free_testosterone_pmol_l),
          fai = num(p.free_androgen_index), andro = num(p.androstenedione_nmol_l),
          dheas = num(p.dheas_umol_l);
    if (tt !== null || ft !== null || fai !== null) {
      const parts = [];
      if (tt !== null) parts.push(`total testosterone ${tt} nmol/L`);
      if (ft !== null) parts.push(`free testosterone ${ft} pmol/L`);
      if (fai !== null) parts.push(`FAI ${fai}`);
      biochem.push('Measured: ' + parts.join(', ') + '.');
      biochem.push('Compare against YOUR laboratory’s reference range and method'
        + (p.testosterone_assay === 'lc_ms' ? ' (LC-MS/MS recorded).'
          : p.testosterone_assay === 'immunoassay'
            ? ' — note: direct immunoassay results are unreliable at female concentrations, LC-MS/MS is preferred.'
            : ' — record whether LC-MS/MS was used, as assay method changes interpretation.'));
      blockers.push('Enter whether the result was above the laboratory’s reference range to resolve this criterion.');
    } else if (andro !== null || dheas !== null) {
      biochem.push('Second-line androgens recorded (androstenedione/DHEAS) — these have limited accuracy and poor sensitivity; total and free testosterone are preferred.');
      blockers.push('Measure total and free testosterone (LC-MS/MS) — the guideline-preferred test.');
    } else {
      biochem.push('Requires a laboratory test; a wearable cannot measure this.');
      blockers.push('Blood test: total and free testosterone (or calculated free androgen index), ideally by LC-MS/MS.');
      if (p.on_hormonal_contraception === true)
        blockers.push('Where feasible, test at least 3 months after stopping hormonal contraception.');
    }
    let status;
    if (clinPresent === true || bioPresent === true) status = PRESENT;
    else if (clinPresent === false && bioPresent === false) status = ABSENT;
    else status = UNKNOWN;
    return {key: 'hyperandrogenism', label: 'Clinical or biochemical hyperandrogenism',
      status: status, detail: clinical.concat(biochem).join(' '), blockers: blockers};
  }

  function criterionMorphology(p, stage) {
    const blockers = [], findings = [];
    let status = UNKNOWN;
    const amhAllowed = stage !== 'adolescent';
    if (stage === 'unknown')
      blockers.push('Record age and years since your first period — the thresholds and the 2-of-3 rule differ between adolescents and adults.');

    const fnpo = num(p.fnpo), fnps = num(p.fnps), ov = num(p.ovarian_volume_ml);
    if (fnpo !== null) {
      if (fnpo >= 20) { findings.push(`FNPO ${fnpo} follicles — at or above the adult threshold of 20 in one ovary.`); status = PRESENT; }
      else { findings.push(`FNPO ${fnpo} — below the threshold of 20.`); status = ABSENT; }
    }
    if (fnps !== null) {
      if (fnps >= 10) { findings.push(`FNPS ${fnps} — at or above the threshold of 10.`); status = PRESENT; }
      else if (status !== PRESENT) { findings.push(`FNPS ${fnps} — below the threshold of 10.`); if (status === UNKNOWN) status = ABSENT; }
    }
    if (ov !== null) {
      if (ov >= 10) { findings.push(`Ovarian volume ${ov} mL — at or above the threshold of 10 mL.`); status = PRESENT; }
      else if (status !== PRESENT) { findings.push(`Ovarian volume ${ov} mL — below the threshold of 10 mL.`); if (status === UNKNOWN) status = ABSENT; }
    }
    if (p.ultrasound_route === 'transabdominal' && fnpo !== null)
      findings.push('Transabdominal route: ovarian volume or FNPS should be reported preferentially, because whole-ovary follicle counting is difficult this way.');

    const amh = num(p.amh_pmol_l) !== null ? num(p.amh_pmol_l) : num(p.amh_ng_ml);
    if (amh !== null) {
      if (!amhAllowed) {
        findings.push('AMH should not be used for diagnosis in adolescents. Value recorded but not used.');
        blockers.push('Use ultrasound findings, not AMH, in adolescents (or wait until adulthood).');
      } else if (has(p.amh_lab_cutoff)) {
        const cut = num(p.amh_lab_cutoff);
        if (amh >= cut) { findings.push(`AMH ${amh} at or above this laboratory’s cut-off of ${cut}.`); status = PRESENT; }
        else { findings.push(`AMH ${amh} below this laboratory’s cut-off of ${cut}.`); if (status === UNKNOWN) status = ABSENT; }
      } else {
        findings.push(`AMH ${amh} recorded, but No universal threshold exists — cut-offs are assay-specific. Cut-offs differ substantially between the Gen II, picoAMH, Elecsys and Access platforms.`);
        blockers.push('Enter the AMH cut-off printed on your own laboratory report — no universal value exists.');
      }
    }
    if (!findings.length) {
      findings.push('Requires a pelvic ultrasound; a wearable cannot image the ovary.');
      blockers.push('Pelvic ultrasound (FNPO ≥ 20, or ovarian volume ≥ 10 mL / FNPS ≥ 10 on older equipment).');
      blockers.push(amhAllowed
        ? 'Or, in adults, serum AMH interpreted against the laboratory’s own cut-off.'
        : 'AMH is not recommended in adolescents, so ultrasound is the route here.');
    }
    return {key: 'morphology', label: 'Polycystic ovarian morphology (ultrasound or AMH)',
      status: status, detail: findings.join(' '), blockers: blockers};
  }

  function evaluateDetection(p) {
    const stage = lifeStage(p);
    const criteria = [
      criterionOvulatory(p, stage),
      criterionHyperandrogenism(p, stage),
      criterionMorphology(p, stage)
    ];
    const present = criteria.filter(c => c.status === PRESENT).length;
    const absent = criteria.filter(c => c.status === ABSENT).length;
    const unknown = criteria.filter(c => c.status === UNKNOWN).length;

    const missing = [];
    if (p.other_causes_excluded !== true) {
      if (p.tsh_checked !== true) missing.push('Thyroid function (TSH)');
      if (p.prolactin_checked !== true) missing.push('Prolactin');
      if (p.ohp17_checked !== true) missing.push('17-OH progesterone (non-classic CAH)');
    }
    const exclusionsComplete = missing.length === 0;

    const adolescent = stage === 'adolescent';
    const h = criteria.find(c => c.key === 'hyperandrogenism');
    const o = criteria.find(c => c.key === 'ovulatory');
    let verdict;
    if (adolescent) {
      if (h.status === PRESENT && o.status === PRESENT) verdict = MEETS;
      else if (h.status === ABSENT || o.status === ABSENT) verdict = NOT_MET;
      else verdict = CANT;
    } else {
      if (present >= 2) verdict = MEETS;
      else if (present + unknown >= 2) verdict = CANT;
      else verdict = NOT_MET;
    }
    const m = criteria.find(c => c.key === 'morphology');
    const ultrasoundNeeded = (!adolescent && o.status === PRESENT && h.status === PRESENT)
      ? false : m.status === UNKNOWN;

    return {
      life_stage: stage, criteria: criteria, present_count: present,
      unknown_count: unknown, verdict: verdict,
      exclusions_complete: exclusionsComplete, exclusions_missing: missing,
      ultrasound_needed: ultrasoundNeeded,
      headline: verdict === MEETS
        ? 'Screening result: meets 2 of 3 criteria — a clinician must confirm and exclude other causes.'
        : verdict === NOT_MET
          ? 'Screening result: fewer than 2 of 3 criteria are present.'
          : 'Not enough information to apply the criteria.'
    };
  }

  /* ==================================================================
     SECTION 2 — complication screening
     ================================================================== */
  const GLU_I = 1095, GLU_HR_I = 365, LIPID_I = 730, BP_I = 365, WEIGHT_I = 365, MH_I = 365;

  function bmiThreshold(c) { return c.asian_ethnicity === true ? 23 : 25; }

  function glucoseRisk(c) {
    const n = [], reasons = [];
    const thr = bmiThreshold(c);
    if (num(c.bmi) !== null && c.bmi >= thr) { reasons.push(`BMI ${c.bmi} (action threshold ${thr} for your population group)`); }
    if (num(c.waist_cm) !== null && c.waist_cm >= 80) reasons.push(`waist ${c.waist_cm} cm (central adiposity)`);
    if (c.family_history_t2dm === true) reasons.push('family history of type 2 diabetes');
    if (c.personal_history_gestational_diabetes === true) reasons.push('personal history of gestational diabetes');
    if (c.acanthosis_nigricans === true) reasons.push('acanthosis nigricans');
    if (num(c.age_years) !== null && c.age_years > 40) reasons.push(`age ${c.age_years}`);
    if (c.current_smoker === true) reasons.push('current smoking');
    if (num(c.systolic_bp) !== null && c.systolic_bp >= 130) reasons.push(`systolic BP ${c.systolic_bp} mmHg`);
    if (num(c.moderate_activity_min_per_week) !== null && c.moderate_activity_min_per_week < 150)
      reasons.push(`${c.moderate_activity_min_per_week} min/week activity (target 150–300)`);
    reasons.forEach(r => n.push(r));
    return {count: n.length, reasons: n};
  }

  function evaluateComplications(c, today) {
    today = today || new Date();
    const out = [];
    const dom = (o) => out.push(o);

    // --- glucose
    {
      const rf = glucoseRisk(c);
      const interval = rf.count > 0 ? GLU_HR_I : GLU_I;
      const st = intervalStatus(c.last_glucose_test_date, interval, today);
      let status = st.status, signals = [];
      if (rf.reasons.length) signals.push('Risk factors: ' + rf.reasons.join('; ') + '.');
      if (rf.count > 0) signals.push('Higher-risk profile — reassess annually rather than every 3 years.');
      const abn = [];
      const fg = num(c.fasting_glucose_mg_dl), og = num(c.ogtt_2h_mg_dl), a1 = num(c.hba1c_pct);
      if (fg !== null) {
        if (fg >= 126) abn.push(`fasting glucose ${fg} mg/dL (≥126 = diabetes range)`);
        else if (fg >= 100) abn.push(`fasting glucose ${fg} mg/dL (100–125 = impaired fasting glucose)`);
        else signals.push(`Fasting glucose ${fg} mg/dL.`);
      }
      if (og !== null) {
        if (og >= 200) abn.push(`2-hour OGTT ${og} mg/dL (≥200 = diabetes range)`);
        else if (og >= 140) abn.push(`2-hour OGTT ${og} mg/dL (140–199 = impaired glucose tolerance)`);
        else signals.push(`2-hour OGTT ${og} mg/dL.`);
      }
      if (a1 !== null) {
        if (a1 >= 6.5) abn.push(`HbA1c ${a1}% (≥6.5% = diabetes range)`);
        else if (a1 >= 5.7) abn.push(`HbA1c ${a1}% (5.7–6.4% = prediabetes range)`);
        else signals.push(`HbA1c ${a1}%.`);
      }
      if (abn.length) { status = ACT; signals = abn.concat(signals); }
      dom({key: 'glucose', evidence_ids: ["cx.glucose.all","cx.glucose.interval","cx.glucose.ogtt","cx.glucose.riskfactors"], label: 'Impaired glucose tolerance and type 2 diabetes', status: status, signals: signals,
        interval_note: st.ds !== null ? `Last tested ${st.ds} days ago; guideline interval ${Math.round(interval / 365)} year(s).` : 'No previous test date recorded.'});
    }

    // --- lipids
    {
      const st = intervalStatus(c.last_lipid_test_date, LIPID_I, today);
      let status = st.status, signals = [], abn = [];
      const ldl = num(c.ldl_mg_dl), hdl = num(c.hdl_mg_dl), tg = num(c.triglycerides_mg_dl), tc = num(c.total_cholesterol_mg_dl);
      if (ldl !== null) ldl >= 160 ? abn.push(`LDL-C ${ldl} mg/dL (high)`) : signals.push(`LDL-C ${ldl} mg/dL.`);
      if (hdl !== null) hdl < 50 ? abn.push(`HDL-C ${hdl} mg/dL (low for women)`) : signals.push(`HDL-C ${hdl} mg/dL.`);
      if (tg !== null) tg >= 150 ? abn.push(`triglycerides ${tg} mg/dL (≥150)`) : signals.push(`triglycerides ${tg} mg/dL.`);
      if (tc !== null) tc >= 200 ? abn.push(`total cholesterol ${tc} mg/dL (≥200)`) : signals.push(`total cholesterol ${tc} mg/dL.`);
      if (abn.length) { status = ACT; signals = abn.concat(signals); }
      if (!signals.length && !abn.length) signals.push('No lipid values recorded.');
      dom({key: 'lipids', evidence_ids: ["cx.lipids.all"], label: 'Dyslipidaemia', status: status, signals: signals,
        interval_note: st.ds !== null ? `Last tested ${st.ds} days ago; review roughly every 2 years when normal.` : 'No previous test date recorded.'});
    }

    // --- blood pressure
    {
      const st = intervalStatus(c.last_bp_date, BP_I, today);
      let status = st.status, signals = [];
      const s = num(c.systolic_bp), d = num(c.diastolic_bp);
      if (s !== null && d !== null) {
        if (s >= 140 || d >= 90) { status = ACT; signals.push(`Blood pressure ${s}/${d} mmHg — at or above 140/90.`); }
        else if (s >= 130 || d >= 85) signals.push(`Blood pressure ${s}/${d} mmHg — elevated (130–139/85–89); recheck and monitor.`);
        else signals.push(`Blood pressure ${s}/${d} mmHg — within the normal range.`);
      } else signals.push('No blood-pressure values recorded.');
      dom({key: 'blood_pressure', evidence_ids: ["cx.bp.each.visit","cx.cvd.riskfactors"], label: 'Hypertension', status: status, signals: signals,
        interval_note: st.ds !== null ? `Last measured ${st.ds} days ago; review at least every 6–12 months.` : 'No previous measurement date recorded.'});
    }

    // --- weight
    {
      const st = intervalStatus(c.last_weight_date, WEIGHT_I, today);
      let status = st.status, signals = [];
      const thr = bmiThreshold(c), bmi = num(c.bmi);
      if (bmi !== null) {
        if (bmi >= thr) {
          signals.push(`BMI ${bmi} — at or above the ${thr} action threshold for your population group.`);
          if (status === UNKNOWN || status === UTD) status = DUE_S;
        } else signals.push(`BMI ${bmi} — below the ${thr} action threshold.`);
      }
      if (num(c.waist_cm) !== null) signals.push(`Waist circumference ${c.waist_cm} cm.`);
      if (num(c.moderate_activity_min_per_week) !== null)
        signals.push(`Moderate activity ${c.moderate_activity_min_per_week} min/week — target 150–300 min/week for health, 250 min/week if weight loss is the goal.`);
      if (!signals.length) signals.push('No weight, waist or activity values recorded.');
      dom({key: 'weight', evidence_ids: ["cx.weight.each.visit","cx.glucose.riskfactors"], label: 'Overweight, obesity and central adiposity', status: status, signals: signals,
        interval_note: st.ds !== null ? `Last recorded ${st.ds} days ago; review every 6–12 months.` : 'No previous measurement date recorded.'});
    }

    // --- cardiovascular
    {
      const f = [], thr = bmiThreshold(c);
      if (num(c.bmi) !== null && c.bmi >= thr) f.push('overweight/obesity');
      if (c.current_smoker === true) f.push('current smoking');
      if (num(c.systolic_bp) !== null && c.systolic_bp >= 130) f.push('elevated blood pressure');
      if (num(c.triglycerides_mg_dl) !== null && c.triglycerides_mg_dl >= 150) f.push('raised triglycerides');
      if (num(c.hdl_mg_dl) !== null && c.hdl_mg_dl < 50) f.push('low HDL-C');
      if (c.family_history_premature_cvd === true) f.push('family history of premature cardiovascular disease');
      if (c.family_history_t2dm === true) f.push('family history of type 2 diabetes');
      if (num(c.moderate_activity_min_per_week) !== null && c.moderate_activity_min_per_week < 150) f.push('less than 150 min/week activity');
      if (num(c.hba1c_pct) !== null && c.hba1c_pct >= 5.7) f.push('dysglycaemia');
      if (num(c.fasting_glucose_mg_dl) !== null && c.fasting_glucose_mg_dl >= 100) f.push('impaired fasting glucose');

      const recorded = [c.bmi, c.systolic_bp, c.ldl_mg_dl, c.hdl_mg_dl, c.triglycerides_mg_dl,
        c.current_smoker, c.moderate_activity_min_per_week, c.family_history_t2dm,
        c.family_history_premature_cvd].filter(v => has(v)).length;
      const assessed = recorded >= 4;
      let status;
      if (!assessed) status = UNKNOWN;
      else if (f.length >= 3) status = ACT;
      else if (f.length) status = DUE_S;
      else status = UTD;
      dom({key: 'cardiovascular', evidence_ids: ["cx.cvd.riskfactors","cx.cvd.calculators","cx.lipids.all"], label: 'Cardiovascular risk', status: status,
        signals: f.length ? [`${f.length} risk factor(s) present: ${f.join(', ')}.`]
          : [assessed ? `${recorded} risk-factor inputs recorded and none are raised — review complete on the information entered.`
                      : `Only ${recorded} of 9 risk-factor inputs recorded — not enough to call this reviewed.`],
        interval_note: 'Review at initial diagnosis and periodically thereafter.'});
    }

    // --- OSA
    {
      const sym = [];
      if (c.snoring === true) sym.push('snoring');
      if (c.witnessed_apnoea === true) sym.push('witnessed pauses in breathing');
      if (c.daytime_somnolence === true) sym.push('daytime sleepiness/fatigue');
      let status;
      if (sym.length) status = ACT;
      else if (c.snoring === false && c.daytime_somnolence === false && c.witnessed_apnoea === false) status = UTD;
      else status = UNKNOWN;
      dom({key: 'osa', evidence_ids: ["cx.osa.symptoms","cx.spo2.caveat"], label: 'Obstructive sleep apnoea', status: status,
        signals: sym.length ? [`Symptoms reported: ${sym.join(', ')}.`]
          : status === UTD ? ['Symptoms asked and none reported.'] : ['Symptom questions not answered yet.'],
        interval_note: 'Annual symptomatic review.'});
    }

    // --- mental health
    {
      const st = intervalStatus(c.last_mental_health_screen_date, MH_I, today);
      let status = st.status, signals = [];
      const p9 = num(c.phq9_score);
      if (p9 !== null) {
        const band = p9 < 5 ? 'minimal' : p9 < 10 ? 'mild' : p9 < 15 ? 'moderate' : p9 < 20 ? 'moderately severe' : 'severe';
        signals.push(`PHQ-9 ${p9} (${band}).`);
        if (p9 >= 10) status = ACT;
      } else signals.push('No PHQ-9 score recorded.');
      const g7 = num(c.gad7_score);
      if (g7 !== null) {
        const band = g7 < 5 ? 'minimal' : g7 < 10 ? 'mild' : g7 < 15 ? 'moderate' : 'severe';
        signals.push(`GAD-7 ${g7} (${band}).`);
        if (g7 >= 10) status = ACT;
      } else signals.push('No GAD-7 score recorded.');
      dom({key: 'mental_health', evidence_ids: ["cx.mental.all"], label: 'Depression and anxiety', status: status, signals: signals,
        interval_note: st.ds !== null ? `Last screened ${st.ds} days ago; re-screen at least annually.` : 'No previous screen date recorded.'});
    }

    // --- liver (always NOT_INDICATED by current guidance)
    {
      const signals = [];
      const metabolic = (num(c.bmi) !== null && c.bmi >= bmiThreshold(c))
        || (num(c.hba1c_pct) !== null && c.hba1c_pct >= 5.7)
        || (num(c.triglycerides_mg_dl) !== null && c.triglycerides_mg_dl >= 150);
      if (num(c.alt_u_l) !== null) signals.push(`ALT ${c.alt_u_l} U/L recorded.`);
      signals.push(metabolic
        ? 'Metabolic risk features present (adiposity / dysglycaemia / raised triglycerides) — guidance is to be AWARE of NAFLD here, but still not to screen routinely.'
        : 'No metabolic risk features recorded.');
      dom({key: 'liver', evidence_ids: ["cx.nafld.awareness"], label: 'Non-alcoholic fatty liver disease (NAFLD)', status: NI, signals: signals,
        interval_note: 'Routine review is not recommended by current guidance.'});
    }

    // --- endometrial
    {
      const signals = [];
      let status = NI;
      if (c.abnormal_uterine_bleeding === true) { status = ACT; signals.push('Unexpected or abnormal uterine bleeding reported — this should be assessed.'); }
      if (num(c.amenorrhoea_days) !== null && c.amenorrhoea_days > 90) { status = ACT; signals.push(`${c.amenorrhoea_days} days without a period (prolonged amenorrhoea > 90 days).`); }
      if (status === NI) signals.push('No bleeding concerns recorded.');
      dom({key: 'endometrial', evidence_ids: ["cx.endometrial.bleeding"], label: 'Endometrial hyperplasia and cancer', status: status, signals: signals,
        interval_note: 'No routine screening; assess on symptoms.'});
    }

    // --- reproductive
    {
      const signals = [];
      let status = UNKNOWN;
      if (c.pregnant === true) {
        status = ACT;
        signals.push(`Currently pregnant${num(c.gestation_weeks) !== null ? ` at ${c.gestation_weeks} weeks` : ''} — PMOS/PCOS is regarded as a high-risk pregnancy condition.`);
        if (num(c.gestation_weeks) !== null && c.gestation_weeks >= 24 && c.gestation_weeks <= 28)
          signals.push('24–28 weeks is the window for gestational diabetes screening.');
      } else if (c.trying_to_conceive === true) {
        const mo = num(c.months_trying_to_conceive);
        signals.push('Trying to conceive' + (mo !== null ? ` for ${mo} months.` : '.'));
        status = (mo !== null && mo >= 12) ? ACT : DUE_S;
        if (num(c.bmi) !== null && c.bmi >= bmiThreshold(c))
          signals.push('Excess weight adversely affects clinical pregnancy, miscarriage and live-birth rates, so weight support matters before and during fertility treatment.');
      } else {
        status = NI;
        signals.push('Not currently pregnant and not recorded as trying to conceive, so no fertility or pregnancy assessment is indicated right now.');
        if (num(c.amenorrhoea_days) !== null && c.amenorrhoea_days > 90)
          signals.push(`Note: ${c.amenorrhoea_days} days without a period is recorded, which also shows up under the endometrial item above.`);
      }
      dom({key: 'reproductive', evidence_ids: ["cx.pregnancy.highrisk","cx.infertility.anovulation"], label: 'Fertility and pregnancy', status: status, signals: signals,
        interval_note: 'Assess at diagnosis and at each life-stage change.'});
    }

    const counts = {};
    out.forEach(d => { counts[d.status] = (counts[d.status] || 0) + 1; });
    return {domains: out, counts: counts};
  }

  root.CHRONO_ENGINE = {
    evaluateDetection: evaluateDetection,
    evaluateComplications: evaluateComplications,
    lifeStage: lifeStage,
    cycleThreshold: cycleThreshold
  };
})(typeof window !== 'undefined' ? window : globalThis);

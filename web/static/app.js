/* CHRONO PCOD/PMOS portable companion — client.
   No frameworks, no build step, no network dependencies. */

'use strict';

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
const api = (p, opts) => fetch(p, opts).then(r => r.json());
const post = (p, body) => api(p, {
  method: 'POST', headers: {'Content-Type': 'application/json'},
  body: JSON.stringify(body || {})
});

/* When true we are the single-file portable edition (file://): no server, so
   scoring runs locally via CHRONO_ENGINE and data lives in localStorage. */
const STANDALONE = !!window.CHRONO_STANDALONE;

let STATE = { profile: {}, clinical: {}, watch: {}, assessment: null, evidence: null };
let deferredPrompt = null;
let bleDevice = null, bleServer = null, bleChar = null;
let pollTimer = null;

/* ------------------------------------------------------ standalone storage */
const lsGet = (k, d) => { try { return JSON.parse(localStorage.getItem('chrono-' + k)) ?? d; } catch (_) { return d; } };
const lsSet = (k, v) => { try { localStorage.setItem('chrono-' + k, JSON.stringify(v)); } catch (_) {} };

/* ------------------------------------------------------------- utilities */
function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function fmt(v, dp = 0) {
  if (v === null || v === undefined || v === '') return '—';
  const n = Number(v);
  return Number.isFinite(n) ? n.toFixed(dp) : '—';
}
function ago(sec) {
  if (sec === null || sec === undefined) return '';
  if (sec < 60) return `${Math.round(sec)}s ago`;
  if (sec < 3600) return `${Math.round(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.round(sec / 3600)}h ago`;
  return `${Math.round(sec / 86400)}d ago`;
}
function toast(msg, ms = 2600) {
  const t = $('#toast');
  t.textContent = msg; t.hidden = false;
  clearTimeout(t._t);
  t._t = setTimeout(() => { t.hidden = true; }, ms);
}

/* ------------------------------------------------------------------ tabs */
function showTab(name) {
  $$('.tab').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
  $$('.tabpanel').forEach(p => { p.hidden = p.id !== `tab-${name}`; });
  window.scrollTo({top: 0, behavior: 'smooth'});
  if (name === 'live') drawChart();
}
$$('.tab').forEach(b => b.addEventListener('click', () => showTab(b.dataset.tab)));

/* ----------------------------------------------------------------- theme */
function setTheme(t) {
  document.documentElement.dataset.theme = t;
  localStorage.setItem('chrono-theme', t);
  $('#themeBtn').textContent = t === 'dark' ? '☀' : '◐';
  if (STATE.assessment) drawChart();
}
$('#themeBtn').addEventListener('click', () =>
  setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'));
setTheme(localStorage.getItem('chrono-theme') || 'light');

/* =====================================================================
   SMARTWATCH — 1) Web Bluetooth (BLE)
   ===================================================================== */
const HR_SERVICE = 0x180D, HR_CHAR = 0x2A37, BATTERY_SERVICE = 0x180F, BATTERY_CHAR = 0x2A19;

const bleSupported = () => !!navigator.bluetooth;

function bleHint(html, show = true) {
  const el = $('#bleHint');
  el.innerHTML = html; el.hidden = !show;
}

$('#bleBtn').addEventListener('click', async () => {
  if (!bleSupported()) {
    bleHint('<strong>Bluetooth pairing needs Chrome or Edge</strong> on Android, Windows, macOS or Linux. ' +
            'Web Bluetooth is not available in Safari or Firefox. On iPhone, use <strong>Push data</strong> ' +
            'or run the companion in Chrome.');
    toast('Web Bluetooth unavailable in this browser');
    return;
  }
  if (bleDevice && bleDevice.gatt.connected) { disconnectBle(); return; }
  try {
    bleHint('Scanning — put your watch in pairing/discoverable mode, then choose it from the browser list…');
    bleDevice = await navigator.bluetooth.requestDevice({
      // Heart Rate is the one service virtually every fitness watch exposes.
      filters: [{services: [HR_SERVICE]}],
      optionalServices: [BATTERY_SERVICE],
      acceptAllDevices: false
    });
    bleDevice.addEventListener('gattserverdisconnected', onBleDisconnected);
    bleServer = await bleDevice.gatt.connect();
    const svc = await bleServer.getPrimaryService(HR_SERVICE);
    bleChar = await svc.getCharacteristic(HR_CHAR);
    await bleChar.startNotifications();
    bleChar.addEventListener('characteristicvaluechanged', onHrFrame);
    $('#bleBtn').textContent = 'Disconnect';
    $('#watchDot').className = 'dot dot-live';
    $('#watchLabel').textContent = bleDevice.name || 'Bluetooth watch';
    $('#modeBadge').textContent = 'bluetooth';
    $('#modeBadge').className = 'badge badge-live';
    post('/api/watch/ble/status', {connected: true, device: bleDevice.name || 'Bluetooth watch'});
    bleHint(`Connected to <strong>${esc(bleDevice.name || 'watch')}</strong> — streaming heart rate. ` +
            `Keep this tab open. Readings are stored locally on this device.`, true);
    toast('Watch connected');
    try {
      const bsvc = await bleServer.getPrimaryService(BATTERY_SERVICE);
      const bchar = await bsvc.getCharacteristic(BATTERY_CHAR);
      const val = await bchar.readValue();
      post('/api/watch/ble', {battery_pct: val.getUint8(0), device: bleDevice.name || 'Bluetooth watch'});
    } catch (_) { /* battery optional */ }
    refresh();
  } catch (err) {
    bleHint(`Could not pair: ${esc(err.message || err)}. On Android, enable Location and ` +
            `<em>Nearby devices</em> for Chrome — Web Bluetooth requires it.`, true);
    toast('Pairing cancelled or failed');
  }
});

function disconnectBle() {
  try { if (bleChar) bleChar.stopNotifications(); } catch (_) {}
  try { if (bleDevice && bleDevice.gatt.connected) bleDevice.gatt.disconnect(); } catch (_) {}
  onBleDisconnected();
}
function onBleDisconnected() {
  bleChar = null; bleServer = null;
  $('#bleBtn').textContent = 'Pair watch (Bluetooth)';
  post('/api/watch/ble/status', {connected: false, device: ''});
  if (!STATE.watch || !STATE.watch.connected) {
    $('#watchDot').className = 'dot dot-idle';
    $('#watchLabel').textContent = 'No smartwatch connected';
    $('#modeBadge').textContent = 'no watch';
    $('#modeBadge').className = 'badge badge-idle';
  }
}

/* Standard BLE Heart Rate Measurement frame (GATT 0x2A37). */
function onHrFrame(event) {
  const dv = event.target.value;
  let off = 0;
  const flags = dv.getUint8(off++);
  const hrIs16 = (flags & 0x01) !== 0;
  const rrPresent = (flags & 0x10) !== 0;
  const hr = hrIs16 ? dv.getUint16(off, true) : dv.getUint8(off);
  off += hrIs16 ? 2 : 1;
  if (flags & 0x08) off += 2;           // energy expended
  const rr = [];
  if (rrPresent) {
    while (off + 1 < dv.byteLength) {
      // uint16, resolution 1/1024 s  ->  milliseconds
      rr.push(Math.round(dv.getUint16(off, true) / 1024 * 1000));
      off += 2;
    }
  }
  post('/api/watch/ble', {
    hr_bpm: hr, rr_ms: rr, device: (bleDevice && bleDevice.name) || 'Bluetooth watch'
  }).then(() => { if (!$('#tab-live').hidden) refresh(); });
}

/* =====================================================================
   SMARTWATCH — 2) HTTP push  3) demo watch
   ===================================================================== */
$('#ingestBtn').addEventListener('click', () => { showTab('live'); toast('See “Send data from your watch” below'); });

$('#simBtn').addEventListener('click', async () => {
  if (STATE.sim_running) {
    await post('/api/watch/simulate/stop', {});
    toast('Demo watch stopped');
  } else {
    await post('/api/watch/simulate', {start: true, backfill_days: 14});
    toast('Demo watch running — synthetic data, clearly labelled');
  }
  refresh();
});

$('#mSend').addEventListener('click', async () => {
  const num = id => { const v = $(id).value.trim(); return v === '' ? null : Number(v); };
  const payload = {
    hr_bpm: num('#mHr'), spo2_pct: num('#mSpo2'), steps: num('#mSteps'),
    sleep_hours: num('#mSleep'), wrist_temp_c: num('#mTemp'),
    device: $('#mDevice').value.trim() || 'Manual entry', _source: 'manual'
  };
  const res = await post('/api/watch/ingest', payload);
  if (res.accepted) {
    toast('Reading saved' + (res.rejected && res.rejected.length ? ' (with rejections)' : ''));
    ['#mHr', '#mSpo2', '#mSteps', '#mSleep', '#mTemp'].forEach(i => $(i).value = '');
    refresh();
  } else {
    toast(res.reason || 'Rejected — no usable measurement', 3600);
  }
});

/* =====================================================================
   RENDER — live
   ===================================================================== */
function renderLive() {
  const w = STATE.watch || {};
  const l = w.latest || {};
  $('#vHr').textContent = fmt(l.hr_bpm, 0);
  $('#vHrv').textContent = fmt(l.rmssd_ms, 0);
  $('#vSpo2').textContent = fmt(l.spo2_pct, 0);
  $('#vSteps').textContent = w.steps_24h ? w.steps_24h.toLocaleString() : '—';
  $('#vSleep').textContent = fmt(l.sleep_hours, 1);
  $('#vTemp').textContent = fmt(l.wrist_temp_c, 1);
  $('#vBatt').textContent = l.battery_pct != null ? `${Math.round(l.battery_pct)}%` : '—';
  $('#vCount').textContent = w.samples_24h != null ? w.samples_24h : '—';
  $('#vDays').textContent = `${w.covered_days || 0} / ${w.window_days || 14}`;

  const pct = Math.round((w.sufficiency || 0) * 100);
  $('#covFill').style.width = pct + '%';
  $('#covText').textContent =
    `Baseline coverage ${w.covered_days || 0} / ${w.window_days || 14} days — ` +
    (pct >= 100 ? 'enough for a reliable personal pattern.'
      : 'keep wearing it; trends are unreliable before 14 days.');

  $('#lastUpdate').textContent = w.last_update_s_ago != null ? `updated ${ago(w.last_update_s_ago)}` : '';

  const sim = STATE.sim_running;
  if (w.connected) {
    const demo = sim || w.source === 'simulated';
    $('#watchDot').className = 'dot ' + (demo ? 'dot-demo' : 'dot-live');
    $('#watchLabel').textContent = `${w.device || 'Watch'} · ${w.source || 'unknown'}${demo ? ' (synthetic)' : ''}`;
    $('#modeBadge').textContent = demo ? 'demo data' : 'paired';
    $('#modeBadge').className = 'badge ' + (demo ? 'badge-demo' : 'badge-live');
    $('#simBtn').textContent = sim ? 'Stop demo' : 'Demo watch';
  }
}

async function drawChart() {
  const cv = $('#hrChart');
  if (!cv) return;
  const w = cv.clientWidth || 600, h = 150, dpr = window.devicePixelRatio || 1;
  cv.width = w * dpr; cv.height = h * dpr;
  const g = cv.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, w, h);
  const css = getComputedStyle(document.documentElement);
  const line = css.getPropertyValue('--line').trim() || '#ddd';
  const acc = css.getPropertyValue('--accent').trim() || '#0f766e';
  const muted = css.getPropertyValue('--muted').trim() || '#888';

  let pts = [];
  try { const r = await api('/api/watch/series?hours=24'); pts = (r.series || []).filter(p => p.hr); } catch (_) {}
  if (pts.length < 2) {
    g.fillStyle = muted; g.font = '13px sans-serif'; g.textAlign = 'center';
    g.fillText('Not enough watch data yet.', w / 2, h / 2);
    $('#chartNote').textContent = 'Connect a watch or start the demo watch to see the 24-hour heart-rate trend.';
    return;
  }
  if (pts.length > 400) pts = pts.filter((_, i) => i % Math.ceil(pts.length / 400) === 0);
  const xs = pts.map(p => p.ts), ys = pts.map(p => p.hr);
  const x0 = Math.min(...xs), x1 = Math.max(...xs) || x0 + 1;
  let y0 = Math.min(...ys) - 4, y1 = Math.max(...ys) + 4;
  if (y1 - y0 < 12) { const m = (y0 + y1) / 2; y0 = m - 6; y1 = m + 6; }
  const px = t => 4 + (t - x0) / (x1 - x0) * (w - 8);
  const py = v => h - 18 - (v - y0) / (y1 - y0) * (h - 30);

  g.strokeStyle = line; g.lineWidth = 1;
  for (let i = 0; i <= 3; i++) {
    const y = 12 + i * (h - 30) / 3;
    g.beginPath(); g.moveTo(4, y); g.lineTo(w - 4, y); g.stroke();
  }
  g.beginPath();
  pts.forEach((p, i) => i ? g.lineTo(px(p.ts), py(p.hr)) : g.moveTo(px(p.ts), py(p.hr)));
  g.strokeStyle = acc; g.lineWidth = 2; g.lineJoin = 'round'; g.stroke();

  g.fillStyle = muted; g.font = '11px sans-serif'; g.textAlign = 'left';
  g.fillText(`${Math.round(y1)} bpm`, 6, 14);
  g.fillText(`${Math.round(y0)} bpm`, 6, h - 6);
  g.textAlign = 'right';
  g.fillText(`${pts.length} readings`, w - 6, h - 6);
  $('#chartNote').textContent = `Heart rate over the last 24 hours — ${pts.length} readings, ` +
    `range ${Math.round(Math.min(...ys))}–${Math.round(Math.max(...ys))} bpm.`;
}

/* =====================================================================
   RENDER — Section 1
   ===================================================================== */
function renderDetection() {
  const a = STATE.assessment;
  if (!a) return;
  const s = a.section1_detection;
  $('#stageTag').textContent = `life stage: ${s.life_stage}`;
  $('#verdictHead').textContent = s.headline;
  $('#verdictWhy').textContent = s.explanation;
  $('#verdictCard').style.borderLeftColor = s.verdict === 'MEETS_CRITERIA'
    ? 'var(--present)' : s.verdict === 'DOES_NOT_MEET' ? 'var(--absent)' : 'var(--unknown)';

  $('#criteriaList').innerHTML = s.criteria.map(c => `
    <div class="crit">
      <div class="crit-head">
        <span class="crit-name">${esc(c.label)}</span>
        <span class="crit-status st-${c.status}">${c.status}</span>
      </div>
      <div class="crit-detail">${esc(c.detail)}</div>
      ${c.blockers.length ? `<ul class="crit-blockers">${c.blockers.map(b => `<li>${esc(b)}</li>`).join('')}</ul>` : ''}
    </div>`).join('');

  const ex = $('#exclusionBox');
  if (s.exclusions_complete) {
    ex.className = 'notice notice-ok';
    ex.innerHTML = '<strong>Other causes recorded as excluded.</strong> A clinician still confirms the diagnosis.';
  } else {
    ex.className = 'notice notice-warn';
    ex.innerHTML = '<strong>Other causes must be excluded before this can be called PMOS/PCOS.</strong> ' +
      'Still to check: ' + s.exclusions_missing.map(esc).join(', ') + '.';
  }
  $('#watchNote1').textContent = s.watch_note;
  $('#citations1').innerHTML = citationList(s.citations, 'Sources for Section 1');
}

/* =====================================================================
   RENDER — Section 2
   ===================================================================== */
function renderComplications() {
  const a = STATE.assessment;
  if (!a) return;
  const s = a.section2_complications;
  const ORDER = ['ACTION_NEEDED', 'OVERDUE', 'DUE', 'UNKNOWN', 'UP_TO_DATE', 'NOT_INDICATED'];
  const LABEL = {
    ACTION_NEEDED: 'Assessment needed now', OVERDUE: 'Overdue', DUE: 'Due',
    UNKNOWN: 'Not assessed', UP_TO_DATE: 'Up to date', NOT_INDICATED: 'Not routinely screened'
  };
  $('#cxCounts').innerHTML = ORDER
    .filter(k => s.counts[k])
    .map(k => `<span class="chip chip-${k}">${s.counts[k]} · ${LABEL[k]}</span>`).join('');

  $('#cxList').innerHTML = s.domains.slice()
    .sort((x, y) => ORDER.indexOf(x.status) - ORDER.indexOf(y.status))
    .map(d => `
      <div class="cx cx-${d.status}">
        <div class="cx-head">
          <span class="cx-title">${esc(d.label)}</span>
          <span class="chip chip-${d.status}">${esc(d.status_label)}</span>
        </div>
        <div class="cx-why">${esc(d.why)}</div>
        ${d.signals.length ? `<ul class="cx-signals">${d.signals.map(x => `<li>${esc(x)}</li>`).join('')}</ul>` : ''}
        <div class="cx-action"><strong>What to do</strong>${esc(d.action)}</div>
        ${d.interval_note ? `<div class="cx-timing">Timing: ${esc(d.interval_note)}</div>` : ''}
        ${d.watch_support ? `<div class="cx-watch">Smartwatch: ${esc(d.watch_support)}</div>` : ''}
      </div>`).join('');

  $('#cxDisclaimer').textContent = s.disclaimer;
  const ids = [];
  s.domains.forEach(d => d.citations.forEach(c => ids.push(c)));
  $('#citations2').innerHTML = citationList(ids, 'Sources for Section 2');
}

function citationList(list, title) {
  if (!list || !list.length) return '';
  const seen = new Set();
  const items = list.filter(c => {
    const k = c.url + c.rec_id;
    if (seen.has(k)) return false;
    seen.add(k); return true;
  });
  return `<h4>${esc(title)}</h4><ul>${items.map(c =>
    `<li>${esc(c.org)} (${c.year})${c.rec_id ? ` · rec ${esc(c.rec_id)}` : ''}${c.grade && c.grade !== 'FACT' ? ` · ${esc(c.grade)}` : ''} — <a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(c.title)}</a></li>`
  ).join('')}</ul>`;
}

/* =====================================================================
   RENDER — evidence
   ===================================================================== */
function renderEvidence() {
  const e = STATE.evidence;
  if (!e) return;
  $('#evVerified').textContent = `verified ${e.last_verified}`;
  $('#headlines').innerHTML = (e.headlines || []).map(h => `
    <div class="headline">
      <div class="headline-meta">
        <span class="headline-date">${esc(h.date)}</span>
        <span class="headline-tag">${esc(h.tag)}</span>
      </div>
      <div class="headline-title">${esc(h.headline)}</div>
      <div class="headline-detail">${esc(h.detail)}</div>
      <div class="ev-sources">${(h.sources || []).map(s =>
        `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.org)}</a>`).join(' · ')}</div>
    </div>`).join('');

  const byTopic = {};
  (e.items || []).forEach(i => (byTopic[i.topic] = byTopic[i.topic] || []).push(i));
  $('#evidenceTopics').innerHTML = Object.entries(byTopic).map(([topic, items]) => `
    <div class="topic-card">
      <div class="topic-title">${esc(topic)}</div>
      ${items.map(i => `
        <div class="ev">
          <div class="ev-meta">
            <span class="ev-grade">${esc(i.grade)}</span>
            ${i.rec_id ? `<span class="ev-rec">rec ${esc(i.rec_id)}</span>` : ''}
            <span class="ev-rec">${esc(i.applies_to)}</span>
          </div>
          <div class="ev-text">${esc(i.statement)}</div>
          ${i.note ? `<div class="ev-note">${esc(i.note)}</div>` : ''}
          <div class="ev-sources">${i.sources.map(s =>
            `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.org)}</a> (${s.year})`).join(' · ')}
            · verified ${esc(i.last_verified)}</div>
        </div>`).join('')}
    </div>`).join('');
}

/* =====================================================================
   FORMS
   ===================================================================== */
const FIELDS = {
  profile: [
    ['Demographics', [
      {k: 'age_years', l: 'Age (years)', t: 'num'},
      {k: 'years_post_menarche', l: 'Years since first period', t: 'num', hint: 'Changes the thresholds used'},
    ]],
    ['Cycle history', [
      {k: 'usual_cycle_length_days', l: 'Usual cycle length (days)', t: 'num'},
      {k: 'cycles_last_year', l: 'Periods in the last 12 months', t: 'num'},
      {k: 'days_since_last_period', l: 'Days since last period started', t: 'num'},
      {k: 'longest_cycle_days', l: 'Longest cycle (days)', t: 'num'},
      {k: 'luteal_progesterone_nmol_l', l: 'Luteal progesterone (nmol/L)', t: 'num', hint: 'Lab test — confirms ovulation'},
      {k: 'on_hormonal_contraception', l: 'Currently on hormonal contraception', t: 'check'},
    ]],
    ['Clinical signs of androgen excess', [
      {k: 'hirsutism', l: 'Hirsutism (coarse hair, male pattern)', t: 'check'},
      {k: 'ferriman_gallwey', l: 'Ferriman–Gallwey score', t: 'num', hint: 'Clinician-scored'},
      {k: 'acne', l: 'Persistent acne', t: 'check'},
      {k: 'female_pattern_hair_loss', l: 'Female-pattern hair loss', t: 'check'},
    ]],
    ['Blood tests — androgens', [
      {k: 'total_testosterone_nmol_l', l: 'Total testosterone (nmol/L)', t: 'num'},
      {k: 'free_testosterone_pmol_l', l: 'Free testosterone (pmol/L)', t: 'num'},
      {k: 'free_androgen_index', l: 'Free androgen index', t: 'num'},
      {k: 'androstenedione_nmol_l', l: 'Androstenedione (nmol/L)', t: 'num'},
      {k: 'dheas_umol_l', l: 'DHEAS (µmol/L)', t: 'num'},
      {k: 'testosterone_assay', l: 'Testosterone assay', t: 'select',
        o: [['unknown', 'Not recorded'], ['lc_ms', 'LC-MS/MS (preferred)'], ['immunoassay', 'Direct immunoassay']],
        hint: 'Immunoassays are unreliable at female levels'},
    ]],
    ['Polycystic ovarian morphology', [
      {k: 'fnpo', l: 'Follicle number per ovary (FNPO)', t: 'num', hint: '≥ 20 meets the threshold'},
      {k: 'fnps', l: 'Follicles per cross-section (FNPS)', t: 'num', hint: '≥ 10 on older equipment'},
      {k: 'ovarian_volume_ml', l: 'Ovarian volume (mL)', t: 'num', hint: '≥ 10 mL meets the threshold'},
      {k: 'ultrasound_route', l: 'Ultrasound route', t: 'select',
        o: [['unknown', 'Not recorded'], ['transvaginal', 'Transvaginal'], ['transabdominal', 'Transabdominal']]},
      {k: 'amh_ng_ml', l: 'AMH (ng/mL)', t: 'num'},
      {k: 'amh_lab_cutoff', l: 'Your lab’s AMH cut-off', t: 'num', hint: 'No universal threshold exists — use your own lab’s'},
    ]],
    ['Excluding other causes', [
      {k: 'tsh_checked', l: 'Thyroid (TSH) checked and normal', t: 'check'},
      {k: 'prolactin_checked', l: 'Prolactin checked and normal', t: 'check'},
      {k: 'ohp17_checked', l: '17-OH progesterone checked', t: 'check'},
      {k: 'other_causes_excluded', l: 'Clinician has excluded other causes', t: 'check'},
    ]],
  ],
  clinical: [
    ['Measurements', [
      {k: 'age_years', l: 'Age (years)', t: 'num'},
      {k: 'bmi', l: 'BMI (kg/m²)', t: 'num'},
      {k: 'waist_cm', l: 'Waist circumference (cm)', t: 'num'},
      {k: 'systolic_bp', l: 'Systolic BP (mmHg)', t: 'num'},
      {k: 'diastolic_bp', l: 'Diastolic BP (mmHg)', t: 'num'},
      {k: 'asian_ethnicity', l: 'South Asian / Asian ethnicity', t: 'check', hint: 'Lowers the BMI action threshold to 23'},
    ]],
    ['Metabolic blood tests', [
      {k: 'fasting_glucose_mg_dl', l: 'Fasting glucose (mg/dL)', t: 'num'},
      {k: 'ogtt_2h_mg_dl', l: '2-hour OGTT (mg/dL)', t: 'num'},
      {k: 'hba1c_pct', l: 'HbA1c (%)', t: 'num'},
      {k: 'total_cholesterol_mg_dl', l: 'Total cholesterol (mg/dL)', t: 'num'},
      {k: 'ldl_mg_dl', l: 'LDL-C (mg/dL)', t: 'num'},
      {k: 'hdl_mg_dl', l: 'HDL-C (mg/dL)', t: 'num'},
      {k: 'triglycerides_mg_dl', l: 'Triglycerides (mg/dL)', t: 'num'},
      {k: 'alt_u_l', l: 'ALT (U/L)', t: 'num'},
    ]],
    ['History', [
      {k: 'family_history_t2dm', l: 'Family history of type 2 diabetes', t: 'check'},
      {k: 'family_history_premature_cvd', l: 'Family history of early heart disease', t: 'check'},
      {k: 'personal_history_gestational_diabetes', l: 'Past gestational diabetes', t: 'check'},
      {k: 'acanthosis_nigricans', l: 'Acanthosis nigricans', t: 'check'},
      {k: 'current_smoker', l: 'Current smoker', t: 'check'},
      {k: 'moderate_activity_min_per_week', l: 'Moderate activity (min/week)', t: 'num', hint: 'Target 150–300'},
    ]],
    ['Mood and sleep', [
      {k: 'phq9_score', l: 'PHQ-9 score (0–27)', t: 'num'},
      {k: 'gad7_score', l: 'GAD-7 score (0–21)', t: 'num'},
      {k: 'snoring', l: 'Snoring', t: 'check'},
      {k: 'witnessed_apnoea', l: 'Witnessed pauses in breathing', t: 'check'},
      {k: 'daytime_somnolence', l: 'Daytime sleepiness', t: 'check'},
    ]],
    ['Reproductive', [
      {k: 'pregnant', l: 'Currently pregnant', t: 'check'},
      {k: 'gestation_weeks', l: 'Gestation (weeks)', t: 'num'},
      {k: 'trying_to_conceive', l: 'Trying to conceive', t: 'check'},
      {k: 'months_trying_to_conceive', l: 'Months trying', t: 'num'},
      {k: 'amenorrhoea_days', l: 'Days without a period', t: 'num', hint: 'Over 90 warrants assessment'},
      {k: 'abnormal_uterine_bleeding', l: 'Unexpected bleeding or spotting', t: 'check'},
    ]],
    ['When things were last checked', [
      {k: 'last_glucose_test_date', l: 'Last glucose test', t: 'date'},
      {k: 'last_lipid_test_date', l: 'Last lipid profile', t: 'date'},
      {k: 'last_bp_date', l: 'Last BP measured', t: 'date'},
      {k: 'last_weight_date', l: 'Last weight/BMI', t: 'date'},
      {k: 'last_mental_health_screen_date', l: 'Last mood screen', t: 'date'},
    ]],
  ]
};

function buildForm(kind) {
  const host = kind === 'profile' ? $('#detectForm') : $('#cxForm');
  const stored = STATE[kind] || {};
  host.innerHTML = FIELDS[kind].map(([legend, rows]) => `
    <fieldset>
      <legend>${esc(legend)}</legend>
      <div class="form-grid">
        ${rows.map(f => {
          const id = `f_${kind}_${f.k}`;
          const v = stored[f.k];
          if (f.t === 'check') {
            return `<label class="check" for="${id}"><input type="checkbox" id="${id}" data-k="${f.k}" ${v === true ? 'checked' : ''}>
              <span>${esc(f.l)}${f.hint ? `<span class="hint"> — ${esc(f.hint)}</span>` : ''}</span></label>`;
          }
          if (f.t === 'select') {
            return `<label for="${id}">${esc(f.l)}
              <select id="${id}" data-k="${f.k}">
                ${f.o.map(([val, lbl]) => `<option value="${esc(val)}" ${String(v) === val ? 'selected' : ''}>${esc(lbl)}</option>`).join('')}
              </select>${f.hint ? `<span class="hint">${esc(f.hint)}</span>` : ''}</label>`;
          }
          if (f.t === 'date') {
            return `<label for="${id}">${esc(f.l)}<input type="date" id="${id}" data-k="${f.k}" value="${esc(v || '')}"></label>`;
          }
          return `<label for="${id}">${esc(f.l)}
            <input type="number" step="any" id="${id}" data-k="${f.k}" value="${v === null || v === undefined ? '' : esc(v)}">
            ${f.hint ? `<span class="hint">${esc(f.hint)}</span>` : ''}</label>`;
        }).join('')}
      </div>
    </fieldset>`).join('');
}

function readForm(kind) {
  const host = kind === 'profile' ? $('#detectForm') : $('#cxForm');
  const out = {};
  $$('[data-k]', host).forEach(el => {
    const k = el.dataset.k;
    if (el.type === 'checkbox') { out[k] = el.checked; return; }
    if (el.value === '' || el.value === 'unknown') return;   // leave unknown out
    out[k] = el.type === 'number' ? Number(el.value) : el.value;
  });
  return out;
}

async function saveSection(kind, endpoint) {
  const data = readForm(kind);
  if (STANDALONE) { lsSet(kind, data); }
  else { await post(endpoint, data); }
  toast('Saved — re-evaluating');
  await refresh();
}
async function clearSection(kind, endpoint) {
  if (STANDALONE) { lsSet(kind, {}); }
  else { await post(endpoint, {}); }
  toast('Cleared');
  await refresh();
}
$('#saveProfile').addEventListener('click', () => saveSection('profile', '/api/profile'));
$('#clearProfile').addEventListener('click', () => clearSection('profile', '/api/profile'));
$('#saveClinical').addEventListener('click', () => saveSection('clinical', '/api/clinical'));
$('#clearClinical').addEventListener('click', () => clearSection('clinical', '/api/clinical'));

/* =====================================================================
   Report / export
   ===================================================================== */
$('#reportBtn').addEventListener('click', async () => {
  let txt;
  if (STANDALONE) { txt = localReport(); }
  else { txt = await fetch('/api/report').then(r => r.text()); }
  $('#reportBody').textContent = txt;
  $('#reportModal').hidden = false;
});

/* Plain-text summary generated entirely in the browser (portable edition). */
function localReport() {
  const a = STATE.assessment, L = [];
  const W = 78, line = (s = '') => L.push(s);
  const wrap = (s, indent = '  ') => {
    const words = String(s).split(' '); let cur = indent;
    words.forEach(w => {
      if ((cur + ' ' + w).length > W) { L.push(cur); cur = indent + w; }
      else cur = cur === indent ? cur + w : cur + ' ' + w;
    });
    if (cur.trim()) L.push(cur);
  };
  line('='.repeat(W));
  line(`  CHRONO ${a.condition_label} — COMPANION SUMMARY (portable edition)`);
  line(`  Generated ${new Date().toLocaleString()}`);
  line('  Research and education companion — NOT a diagnosis.');
  line('='.repeat(W));
  line();
  line('  SMARTWATCH: not connected (single-file edition).');
  const s1 = a.section1_detection;
  line();
  line('-'.repeat(W)); line('  SECTION 1 — PCOD / PMOS DETECTION'); line('-'.repeat(W));
  line(`  Life stage: ${s1.life_stage}`);
  s1.criteria.forEach(c => {
    line(`    [${c.status.padEnd(7)}] ${c.label}`);
    wrap(c.detail, '              ');
    (c.blockers || []).forEach(b => wrap('→ to resolve: ' + b, '              '));
  });
  line();
  wrap(`RESULT: ${s1.headline}`);
  wrap(s1.explanation);
  if (!s1.exclusions_complete) wrap(`Still to exclude: ${s1.exclusions_missing.join(', ')}`);
  line(`  Ultrasound needed to complete the picture: ${s1.ultrasound_needed ? 'YES' : 'NO'}`);
  const s2 = a.section2_complications;
  line();
  line('-'.repeat(W)); line('  SECTION 2 — COMPLICATION SCREENING'); line('-'.repeat(W));
  const order = ['ACTION_NEEDED','OVERDUE','DUE','UNKNOWN','UP_TO_DATE','NOT_INDICATED'];
  s2.domains.slice().sort((x, y) => order.indexOf(x.status) - order.indexOf(y.status)).forEach(d => {
    line(`    [${d.status_label.toUpperCase()}] ${d.label}`);
    wrap(d.why, '              ');
    (d.signals || []).forEach(x => wrap('· ' + x, '              '));
    wrap('ACTION: ' + d.action, '              ');
    if (d.interval_note) wrap('Timing: ' + d.interval_note, '              ');
  });
  line();
  wrap(s2.disclaimer);
  line();
  line('='.repeat(W));
  wrap(a.safety);
  line('='.repeat(W));
  return L.join('\n');
}
$('#reportClose').addEventListener('click', () => { $('#reportModal').hidden = true; });
$('#reportModal').addEventListener('click', e => {
  if (e.target.id === 'reportModal') $('#reportModal').hidden = true;
});
$('#reportCopy').addEventListener('click', async () => {
  try { await navigator.clipboard.writeText($('#reportBody').textContent); toast('Copied'); }
  catch (_) { toast('Copy failed — select the text manually'); }
});
$('#reportDownload').addEventListener('click', () => {
  const blob = new Blob([$('#reportBody').textContent], {type: 'text/plain'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `chrono-pmos-summary-${new Date().toISOString().slice(0, 10)}.txt`;
  a.click(); URL.revokeObjectURL(a.href);
});
$('#exportBtn').addEventListener('click', async () => {
  let data;
  if (STANDALONE) {
    data = {exported_at: new Date().toISOString(), profile: STATE.profile,
            clinical: STATE.clinical, watch: null, assessment: STATE.assessment};
  } else {
    data = await api('/api/export');
  }
  const blob = new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `chrono-pmos-export-${new Date().toISOString().slice(0, 10)}.json`;
  a.click(); URL.revokeObjectURL(a.href);
  toast('Exported');
});

/* =====================================================================
   PWA
   ===================================================================== */
window.addEventListener('beforeinstallprompt', e => {
  e.preventDefault(); deferredPrompt = e;
  $('#installBtn').hidden = false;
});
$('#installBtn').addEventListener('click', async () => {
  if (!deferredPrompt) return;
  deferredPrompt.prompt();
  await deferredPrompt.userChoice;
  deferredPrompt = null; $('#installBtn').hidden = true;
});
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => navigator.serviceWorker.register('/sw.js').catch(() => {}));
}

/* =====================================================================
   Refresh loop
   ===================================================================== */
/* Build an assessment object in the same shape the server returns, using the
   local engine plus the static prose inlined from the Python source. */
function standaloneAssessment() {
  const P = window.CHRONO_PAYLOAD || {};
  const copy = P.domain_copy || {}, crit = P.criterion_copy || {};
  const s1 = window.CHRONO_ENGINE.evaluateDetection(STATE.profile);
  s1.criteria.forEach(c => {
    const cc = crit[c.key] || {};
    c.sources = cc.sources || [];
    c.evidence_ids = cc.evidence_ids || [];
  });
  s1.explanation =
    `Scored against the ${s1.life_stage === 'adolescent' ? 'adolescent' : 'adult'} rule: ` +
    (s1.life_stage === 'adolescent'
      ? 'BOTH hyperandrogenism and ovulatory dysfunction are required.'
      : 'at least 2 of the 3 criteria are required.') +
    ` ${s1.present_count} present, ${s1.unknown_count} unknown.`;
  s1.watch_note = 'Single-file edition: no smartwatch connection. Watch data is supportive ' +
    'longitudinal context only — it cannot establish or exclude any of the three criteria.';

  const s2 = window.CHRONO_ENGINE.evaluateComplications(STATE.clinical);
  s2.domains.forEach(d => {
    const cc = copy[d.key] || {};
    d.label = cc.label || d.key;
    d.why = cc.why || '';
    d.action = cc.action || '';
    d.watch_support = cc.watch_support || '';
    d.status_label = ({
      ACTION_NEEDED: 'Assessment needed now', OVERDUE: 'Screening overdue', DUE: 'Screening due',
      UP_TO_DATE: 'Up to date', UNKNOWN: 'Not assessed yet', NOT_INDICATED: 'Routine screening not recommended'
    })[d.status];
  });
  s2.disclaimer =
    'This is a screening checklist built from published guideline recommendations, not a ' +
    'diagnosis and not an individual risk score. Every “assessment needed” item is a prompt to ' +
    'speak with a clinician, who decides what to test and when. Nothing here starts, stops or ' +
    'changes treatment.';

  return {
    condition_label: 'PMOS (PCOS / PCOD)',
    safety: 'Research and education companion. Not a diagnostic device. A smartwatch cannot ' +
            'measure hormones, glucose, lipids or ovarian morphology. No result here starts, ' +
            'stops or changes treatment — discuss everything with a clinician.',
    section1_detection: s1, section2_complications: s2,
    watch: {connected: false}, evidence_headlines: (P.evidence || {}).headlines || []
  };
}

async function refresh() {
  if (STANDALONE) {
    STATE.profile = lsGet('profile', {});
    STATE.clinical = lsGet('clinical', {});
    STATE.evidence = (window.CHRONO_PAYLOAD || {}).evidence || null;
    STATE.assessment = standaloneAssessment();
    renderDetection(); renderComplications(); renderEvidence();
    buildForm('profile'); buildForm('clinical');
    $('#footStatus').textContent = 'Single-file edition · offline · data kept in this browser';
    return;
  }
  try {
    const st = await api('/api/state');
    STATE.profile = st.profile || {};
    STATE.clinical = st.clinical || {};
    STATE.watch = st.watch || {};
    STATE.sim_running = st.sim_running;
  } catch (_) {}
  try { STATE.assessment = await api('/api/assessment'); } catch (_) {}
  if (!STATE.evidence) { try { STATE.evidence = await api('/api/evidence'); } catch (_) {} }

  renderLive(); renderDetection(); renderComplications(); renderEvidence();
  buildForm('profile'); buildForm('clinical');
  if (!$('#tab-live').hidden) drawChart();
  $('#footStatus').textContent = STATE.watch && STATE.watch.connected
    ? `${STATE.watch.device || 'watch'} · ${STATE.watch.samples_total || 0} readings stored locally`
    : 'Local · offline · nothing leaves this device';
}

/* In standalone mode the live tab has no meaning — hide it, and make the
   save/repair buttons talk to localStorage instead of the server. */
function applyStandaloneMode() {
  if (!STANDALONE) return;
  $$('#bleBtn, #simBtn, #ingestBtn').forEach(b => { b.disabled = true; b.title = 'Needs the server build'; });
  $$('.tab').forEach(b => { if (b.dataset.tab === 'live') b.hidden = true; });
  $('#brandSub').textContent = 'PCOD / PMOS companion · portable edition';
  $('#watchLabel').textContent = 'Portable edition — connect a watch with the server build';
  $('#modeBadge').textContent = 'offline file';
}

applyStandaloneMode();
refresh();
clearInterval(pollTimer);
if (!STANDALONE) pollTimer = setInterval(refresh, 8000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
window.addEventListener('resize', () => { if (!$('#tab-live').hidden) drawChart(); });

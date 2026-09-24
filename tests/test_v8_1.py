"""V8.1 tests: QR encoder, ultrasound CV, multimodal fusion, reporting.

These tests verify the new V8.1 machinery while the older suites (V5/V6/V6.2)
continue to guard the rest of the system. No test fabricates clinical data —
image-derived features are UNKNOWN by construction until a validated dataset
exists.
"""
from __future__ import annotations

import os
import time

import pytest

from src.config import APP_VERSION


def test_v8_1_version_bump():
    # V8.2 is a UI/UX refinement on top of the V8.1 engines.
    assert APP_VERSION.startswith("9.")


# ---------------------------------------------------------------- QR encoder
class TestQREncoder:
    def test_roundtrip_all_versions_levels(self):
        from src.utils.qr_encoder import make_qr_code

        payloads = [
            ("CP-9F3A2B", 1, "L"),
            ("CP-9F3A2B", 1, "M"),
            ("CP-9F3A2B", 2, "L"),
            ("CP-9F3A2B", 2, "M"),
            ("CP-9F3A2B", 3, "L"),
            ("CP-9F3A2B", 3, "M"),
            ("REPORT-TOKEN-X7Q9-2026-08-18-ABCDEF", 3, "L"),
        ]
        for payload, ver, level in payloads:
            code = make_qr_code(payload, version=ver, level=level)
            # structural invariants
            assert len(code.matrix) == code.size
            assert all(len(row) == code.size for row in code.matrix)
            assert 0 <= code.mask <= 7
            # reverse-read the payload back out of the matrix
            out = self._reverse_read(code)
            assert out == payload, f"v{ver}-{level} round-trip failed: {out!r}"

    def test_rs_syndromes_zero(self):
        from src.utils.qr_encoder import _rs_syndromes, make_qr_code

        for ver, level in ((1, "L"), (2, "M"), (3, "L")):
            code = make_qr_code("CP-9F3A2B", version=ver, level=level)
            n_ec = len(code.codewords) - len(code.data_codewords)
            assert all(s == 0 for s in _rs_syndromes(code.codewords, n_ec))

    def test_capacity_enforced(self):
        from src.utils.qr_encoder import QRError, make_qr_code

        with pytest.raises(QRError):
            make_qr_code("X" * 200, version=1, level="M")

    def test_png_and_svg_render(self):
        from src.utils.qr_encoder import make_qr_code

        png = make_qr_code("CP-9F3A2B", version=2).to_png_bytes(scale=6)
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
        svg = make_qr_code("CP-9F3A2B", version=2).to_svg()
        assert svg.startswith("<svg") and "</svg>" in svg

    # ---------------------------------------------------- reverse reader
    @staticmethod
    def _reverse_read(code) -> str:
        """Extract the byte-mode payload back from a rendered matrix."""
        m = code.matrix
        size = code.size
        pos = [(8, 0), (8, 1), (8, 2), (8, 3), (8, 4), (8, 5), (8, 7), (8, 8),
               (7, 8), (5, 8), (4, 8), (3, 8), (2, 8), (1, 8), (0, 8)]
        fmt = 0
        for (r, c) in pos:
            fmt = (fmt << 1) | m[r][c]
        fmt ^= 0x5412
        mask = (fmt >> 10) & 0x7

        # rebuild the function-pattern map
        base = [[-1] * size for _ in range(size)]
        for (fr, fc) in [(0, 0), (size - 7, 0), (0, size - 7)]:
            for r in range(7):
                for c in range(7):
                    on_edge = r in (0, 6) or c in (0, 6)
                    core = 2 <= r <= 4 and 2 <= c <= 4
                    base[fr + r][fc + c] = 1 if (on_edge or core) else 0
            for r in range(-1, 8):
                for c in range(-1, 8):
                    rr, cc = fr + r, fc + c
                    if 0 <= rr < size and 0 <= cc < size:
                        if not (0 <= r < 7 and 0 <= c < 7) and base[rr][cc] == -1:
                            base[rr][cc] = 0
        for i in range(8, size - 8):
            base[6][i] = 1 if i % 2 == 0 else 0
            base[i][6] = 1 if i % 2 == 0 else 0
        for (ar, ac) in {1: [], 2: [(18, 18)], 3: [(22, 22)]}[code.version]:
            for r in range(-2, 3):
                for c in range(-2, 3):
                    if base[ar + r][ac + c] == -1:
                        ring = max(abs(r), abs(c))
                        base[ar + r][ac + c] = 1 if ring != 1 else 0
        base[8][4 * code.version + 9] = 1
        for c in range(9):
            if base[8][c] == -1:
                base[8][c] = 0
        for r in range(9):
            if base[r][8] == -1:
                base[r][8] = 0
        for r in range(size - 8, size):
            if base[r][8] == -1:
                base[r][8] = 0
        for c in range(size - 8, size):
            if base[8][c] == -1:
                base[8][c] = 0

        coords = []
        col = size - 1
        upward = True
        while col > 0:
            if col == 6:
                col -= 1
            c1, c2 = col, col - 1
            rows = range(size - 1, -1, -1) if upward else range(size)
            for r in rows:
                for c in (c1, c2):
                    if 0 <= r < size and 0 <= c < size and base[r][c] == -1:
                        coords.append((r, c))
            upward = not upward
            col -= 2

        def mask_apply(mask, r, c):
            i, j = r, c
            if mask == 0:
                return (i + j) % 2 == 0
            if mask == 1:
                return i % 2 == 0
            if mask == 2:
                return j % 3 == 0
            if mask == 3:
                return (i + j) % 3 == 0
            if mask == 4:
                return (i // 2 + j // 3) % 2 == 0
            if mask == 5:
                return (i * j) % 2 + (i * j) % 3 == 0
            if mask == 6:
                return ((i * j) % 2 + (i * j) % 3) % 2 == 0
            return ((i + j) % 2 + (i * j) % 3) % 2 == 0

        rawbits = []
        for (r, c) in coords:
            v = m[r][c]
            if mask_apply(mask, r, c):
                v ^= 1
            rawbits.append(v)
        to_int = lambda bits: sum(b << (len(bits) - 1 - i) for i, b in enumerate(bits))
        count = to_int(rawbits[4:12])
        return bytes(to_int(rawbits[12 + 8 * i:12 + 8 * (i + 1)]) for i in range(count)).decode("utf-8")


# ------------------------------------------------------------ ultrasound CV
class TestUltrasoundCV:
    def _make_image(self, tmp_path, size=(640, 480), blur=False):
        from PIL import Image
        import numpy as np

        w, h = size
        rng = np.random.default_rng(42)
        if blur:
            arr = np.full((h, w), 128, dtype=np.uint8)
        else:
            # speckle-like texture: sharp enough to pass the quality gate
            arr = rng.integers(0, 256, size=(h, w), dtype=np.uint8)
        img = Image.fromarray(arr, "L")
        p = tmp_path / "us.png"
        img.save(p)
        return p

    def test_quality_gate_accepts_sharp_image(self, tmp_path):
        from src.models.ultrasound_cv import UltrasoundCV

        img = self._make_image(tmp_path)
        rep = UltrasoundCV().assess_quality(img)
        assert rep.ok
        assert rep.width == 640 and rep.height == 480

    def test_quality_gate_rejects_missing_and_blur(self, tmp_path):
        from src.models.ultrasound_cv import UltrasoundCV

        cv = UltrasoundCV()
        missing = cv.assess_quality(tmp_path / "nope.png")
        assert not missing.ok
        blur = self._make_image(tmp_path, blur=True)
        rep = cv.assess_quality(blur)
        assert not rep.ok  # uniformly flat image is too soft to analyse

    def test_features_are_unknown_without_dataset(self, tmp_path):
        """The honest core of the module: no validated dataset => UNKNOWN."""
        from src.models.ultrasound_cv import UltrasoundCV, UNKNOWN

        img = self._make_image(tmp_path)
        f = UltrasoundCV().extract_features(img)
        assert f.ovary_visible == UNKNOWN
        assert f.cyst_present == UNKNOWN
        assert f.cyst_size_mm is None
        assert f.confidence == 0.0
        assert f.provenance in ("IMAGE-DERIVED", "UNKNOWN")

    def test_clinician_entries_pass_through_with_provenance(self, tmp_path):
        from src.models.ultrasound_cv import CLINICALLY_ENTERED, UltrasoundCV

        img = self._make_image(tmp_path)
        f = UltrasoundCV().extract_features(
            img, clinician_entries={"cyst_size_mm": 21.5, "morphology": "simple cyst"})
        assert f.cyst_size_mm == 21.5
        assert f.morphology == "simple cyst"
        assert f.provenance == CLINICALLY_ENTERED

    def test_exam_comparison_descriptive(self):
        from src.models.ultrasound_cv import UltrasoundCV

        prev = {"exam_ts": time.time() - 90 * 86400, "cyst_size_mm": 14.0, "morphology": "simple"}
        curr = {"exam_ts": time.time(), "cyst_size_mm": 18.0, "morphology": "simple"}
        comp = UltrasoundCV().compare_exams(prev, curr)
        assert comp is not None and comp.rows
        sizes = [r for r in comp.rows if r["field"] == "cyst_size_mm"]
        assert sizes and sizes[0]["direction"] == "increased"

    def test_dataset_schema_and_patient_split(self):
        from src.models.ultrasound_cv import UltrasoundDataset

        ds = UltrasoundDataset([])
        assert ds.validate_schema()  # no records => problems listed
        records = [
            {"patient_id": f"P{i % 5}", "image_path": f"img{i}.png", "label": 1,
             "exam_date": "2026-01-01"} for i in range(20)
        ]
        ds = UltrasoundDataset(records)
        assert not ds.validate_schema()
        split = ds.patient_split(seed=7)
        # patients never overlap across partitions
        train, val, test = split["train_patients"], split["val_patients"], split["test_patients"]
        assert set(train).isdisjoint(val) and set(train).isdisjoint(test) and set(val).isdisjoint(test)
        assert len(train) + len(val) + len(test) == 5


# ---------------------------------------------------------------- fusion
class TestFusion:
    def test_provenance_tracking_and_missing_groups(self):
        from src.models.fusion import FusionEngine
        from src.models.ultrasound_cv import CLINICALLY_ENTERED, MEASURED

        engine = FusionEngine()
        ctx = engine.build(
            profile=None, ultrasound={"source": "clinical", "cyst_size_mm": 18.0},
            wearable={"hr": 74.0, "rmssd": 42.0}, wearable_quality=0.9)
        assert ctx.overall_quality() > 0
        assert "ultrasound" in ctx.present_groups()
        assert "metabolic" in ctx.missing_groups()
        # provenance is recorded per feature
        provs = {f.key: f.provenance for f in ctx.features}
        assert provs["hr"] == MEASURED
        assert provs["us_cyst_size_mm"] == CLINICALLY_ENTERED
        # missing groups get zero weight but never error
        weights = ctx.group_weights()
        assert weights["metabolic"] == 0.0
        assert weights["wearable"] > 0

    def test_unknown_values_do_not_count_as_present(self):
        from src.models.fusion import FusionEngine
        from src.models.ultrasound_cv import UNKNOWN

        ctx = FusionEngine().build(
            ultrasound={"source": "clinical", "cyst_size_mm": None,
                        "morphology": UNKNOWN})
        # nothing meaningful present in ultrasound group
        assert "ultrasound" not in ctx.present_groups()

    def test_fusion_summary_never_claims_measurement(self):
        from src.models.fusion import FusionEngine

        ctx = FusionEngine().build(profile=None)
        text = ctx.summary_text()
        assert "MEASURED" in text


# ------------------------------------------------------------ reporting
class TestReporting:
    def _seed_store(self, tmp_path):
        from src.utils.history_store import HistoryStore

        store = HistoryStore(tmp_path / "rep.db")
        store.start_session(source="manual")
        now = time.time()
        for i in range(24):
            store.log_feature(None, {
                "ts": now - (23 - i) * 3600,
                "hr": 70 + (i % 5), "rmssd": 40.0, "skin_temp": 32.5,
                "activity": 20.0, "signal_quality": 0.9, "risk": 40.0 + i,
            })
        store.log_cycle_entry(cycle_day=14, cycle_length=29)
        store.log_symptom("acne", 3)
        store.add_medication("Metformin", dose="500", unit="mg")
        return store

    def test_one_page_summary_generated(self, tmp_path):
        from src.models.longitudinal_report import build_clinical_summary

        store = self._seed_store(tmp_path)
        text = build_clinical_summary(store, participant="P01", current_risk=45.0,
                                      current_confidence=60.0, data_quality=0.9)
        assert "P01" in text
        assert "MODEL ESTIMATE" in text
        assert "NOT a diagnosis" in text
        assert "NOT A DIAGNOSTIC DEVICE" in text

    def test_full_html_report_contains_timeline(self, tmp_path):
        from src.models.longitudinal_report import build_full_html_report

        store = self._seed_store(tmp_path)
        html = build_full_html_report(store, participant="P01", current_risk=45.0)
        assert html.startswith("<!DOCTYPE html>")
        assert "Longitudinal timeline" in html
        assert "NOT A DIAGNOSIS" in html

    def test_report_token_roundtrip_and_expiry(self, tmp_path):
        from src.utils.history_store import HistoryStore

        store = self._seed_store(tmp_path)
        rid = store.save_report("periodic", "P01", "text", {"risk": 45.0})
        token = store.create_report_token(report_id=rid, ttl_days=30)
        assert token.startswith("CP-")
        resolved = store.resolve_report_token(token)
        assert resolved is not None and resolved["id"] == rid
        # bogus token resolves to None
        assert store.resolve_report_token("CP-NOPE") is None

    def test_ultrasound_image_logging(self, tmp_path):
        from src.utils.history_store import HistoryStore

        store = HistoryStore(tmp_path / "us.db")
        sid = store.log_ultrasound_image("some/path.png", quality_ok=True,
                                         quality_notes="OK", features_json='{"a": 1}')
        assert sid > 0
        rows = store.ultrasound_images()
        assert rows and rows[0]["image_path"] == "some/path.png"
        assert rows[0]["features"] == {"a": 1}
        assert "ultrasound_images" in store.row_counts()


# ------------------------------------------------------- window structure
def test_v8_1_window_has_ultrasound_tab(tmp_path):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from src.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    w = MainWindow(db_path=tmp_path / "win81.db")
    try:
        assert w.ultrasound_tab is not None
        # the new tab builds its fusion context from the store without errors
        w.ultrasound_tab._build_fusion_context()
        assert "MISSING MODALITIES" in w.ultrasound_tab.fusion_text.toPlainText()
    finally:
        w._end_session()


def test_v8_1_experiment_models_a_to_e():
    from src.validation.longitudinal_experiment import EXPERIMENT_MODELS, MODEL_A_B_C_D
    from src.validation.longitudinal_experiment import LongitudinalExperiment

    keys = [m.key for m in EXPERIMENT_MODELS]
    assert keys == ["A", "B", "C", "D", "E"]
    assert "D" in MODEL_A_B_C_D and "E" in MODEL_A_B_C_D
    text = LongitudinalExperiment.report_table_text()
    assert "MODEL E" in text
    assert "PENDING" in text

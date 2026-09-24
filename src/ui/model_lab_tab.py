"""CHRONO MODEL LAB — controlled automated model training (RESEARCH ONLY).

Workflow surface: UPLOAD → INSPECT → VALIDATE → CONFIGURE → TRAIN → EVALUATE
→ COMPARE → HUMAN REVIEW → APPROVE → DEPLOY.

This tab exists ONLY inside 🔬 RESEARCH.  It never appears in the patient or
clinician dashboards, and nothing here can silently change the deployed
model — deployment requires the human approval gate in the registry.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.modellab import RESEARCH_ONLY_NOTICE
from src.modellab.lab import ModelLab
from src.modellab.registry import RegistryError
from src.modellab.resources import detect_environment, feasibility_note
from src.modellab.trainer import MODEL_ZOO, TrainingConfig
from src.ui import theme
from src.ui.components import SectionCard, StatTile, page_title, status_banner
from src.ui.live_plots import TimeSeriesPlot


def _fmt(v, digits=3):
    if v is None:
        return "NOT YET EVALUATED"
    if isinstance(v, float):
        return f"{v:.{digits}f}"
    return str(v)


class _TrainingWorker(QThread):
    """Background thread executing one training run."""

    epoch_done = Signal(dict)
    finished_ok = Signal(dict)
    failed = Signal(str)

    def __init__(self, run, resume: bool = False, parent=None):
        super().__init__(parent)
        # NOTE: never store the run under "self.run" — that would shadow the
        # QThread.run() virtual and break thread dispatch.
        self.training_run = run
        self.resume = resume

    def run(self):  # noqa: N802 (QThread API)
        try:
            summary = self.training_run.execute(
                progress_cb=lambda em: self.epoch_done.emit(asdict_em(em)),
                resume=self.resume)
            self.finished_ok.emit(summary)
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


def asdict_em(em) -> dict:
    from dataclasses import asdict as _as

    return _as(em)


class ModelLabTab(QWidget):
    """RESEARCH → MODEL LAB."""

    def __init__(self, lab: Optional[ModelLab] = None, parent=None):
        super().__init__(parent)
        self.lab = lab or ModelLab()
        self.worker: Optional[_TrainingWorker] = None
        self.current_run = None
        self.last_summary: Optional[dict] = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        # Safety notice — required wording (§36 / §40).
        self.safety_label = QLabel(
            "CONTROLLED AUTOMATED MODEL TRAINING — research and development tool. "
            "Model outputs are not medical diagnoses. The system automates the "
            "engineering workflow; a human researcher controls dataset, experiment, "
            "evaluation, approval and deployment.")
        self.safety_label.setObjectName("WarningText")
        self.safety_label.setWordWrap(True)
        outer.addWidget(self.safety_label)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self._build_overview(), "Overview")
        self.tabs.addTab(self._build_datasets(), "Dataset Manager")
        self.tabs.addTab(self._build_training(), "Training")
        self.tabs.addTab(self._build_evaluation(), "Evaluation")
        self.tabs.addTab(self._build_registry(), "Registry && Deployment")
        self.tabs.addTab(self._build_ablation(), "Multimodal Ablation")
        outer.addWidget(self.tabs, 1)
        self.refresh_all()

    # ================================================================ overview
    def _build_overview(self) -> QWidget:
        page = QWidget()
        wrap = QVBoxLayout(page)
        wrap.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget(); content.setObjectName("PageScrollContent")
        root = QVBoxLayout(content)
        root.setContentsMargins(6, 6, 6, 12); root.setSpacing(12)

        root.addWidget(page_title(
            "Model Lab",
            "Controlled automated model training — upload a labelled dataset ZIP; the "
            "system prepares, trains, evaluates and packages a candidate model. "
            "Deployment always requires human approval."))

        cards = QHBoxLayout(); cards.setSpacing(10)
        self.tile_datasets = StatTile("Datasets", "0")
        self.tile_models = StatTile("Models", "0")
        self.tile_approved = StatTile("Approved", "0")
        self.tile_runs = StatTile("Training runs", "0")
        self.tile_experiments = StatTile("Experiments", "0")
        self.tile_latest = StatTile("Latest run", "—")
        for t in (self.tile_datasets, self.tile_models, self.tile_approved,
                  self.tile_runs, self.tile_experiments, self.tile_latest):
            cards.addWidget(t, 1)
        root.addLayout(cards)

        flow = SectionCard("Workflow", "Every arrow is automated; the review step is human.")
        flow_lbl = QLabel("UPLOAD  →  INSPECT  →  VALIDATE  →  CONFIGURE  →  TRAIN  →  "
                          "EVALUATE  →  COMPARE  →  HUMAN REVIEW  →  APPROVE  →  DEPLOY")
        flow_lbl.setWordWrap(True)
        flow_lbl.setStyleSheet("font-weight: 600; font-size: 11.5pt;")
        flow.add_widget(flow_lbl)
        rules = QLabel(
            "• Nothing inside an uploaded ZIP is ever executed.\n"
            "• Training refuses to start while leakage or validation checks fail.\n"
            "• Splits are patient-level whenever patient identifiers exist.\n"
            "• No metric is ever fabricated — missing results show NOT YET EVALUATED.\n"
            "• Only a human APPROVE deploys a model; rollback is always available.\n"
            "• Patient data never silently becomes training data.")
        rules.setObjectName("SmallMuted")
        flow.add_widget(rules)
        root.addWidget(flow)

        act = SectionCard("Deployment status")
        self.overview_active = QLabel("Current active model: —")
        self.overview_active.setObjectName("BigValue")
        act.add_widget(self.overview_active)
        root.addWidget(act)
        root.addStretch(1)
        scroll.setWidget(content)
        wrap.addWidget(scroll)
        return page

    # ================================================================ datasets
    def _build_datasets(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page); layout.setSpacing(10)
        layout.setContentsMargins(6, 6, 6, 6)

        up = SectionCard("Upload dataset ZIP",
                         "Safe extraction only: no path traversal, no executables, nothing is run. "
                         "Expected: images/ + labels.csv (image,patient_id,label) or class folders.")
        row = QHBoxLayout()
        self.ds_name = QLineEdit(); self.ds_name.setPlaceholderText("Dataset name, e.g. PCOSGEN")
        self.ds_source = QLineEdit(); self.ds_source.setPlaceholderText("Source / license info (for the registry)")
        upload_btn = QPushButton("Upload dataset ZIP…")
        upload_btn.clicked.connect(self._upload_zip)
        row.addWidget(self.ds_name, 1); row.addWidget(self.ds_source, 2); row.addWidget(upload_btn)
        up.add_layout(row)
        self.ds_status = QLabel("")
        self.ds_status.setWordWrap(True)
        up.add_widget(self.ds_status)
        layout.addWidget(up)

        mid = QHBoxLayout(); mid.setSpacing(10)
        list_card = SectionCard("Registered datasets")
        self.ds_list = QListWidget()
        self.ds_list.currentTextChanged.connect(self._show_dataset_report)
        list_card.add_widget(self.ds_list)
        mid.addWidget(list_card, 1)

        rep_card = SectionCard("Dataset report", "Inspection, data quality and leakage findings.")
        self.ds_report = QTextEdit(); self.ds_report.setReadOnly(True)
        self.ds_report.setPlaceholderText("Select a dataset to view its inspection report.")
        rep_card.add_widget(self.ds_report, 1)
        mid.addWidget(rep_card, 2)
        layout.addLayout(mid, 1)
        return page

    def _upload_zip(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select dataset ZIP", "", "ZIP archives (*.zip)")
        if not path:
            return
        try:
            meta = self.lab.store.import_zip(Path(path), name=self.ds_name.text().strip(),
                                             source=self.ds_source.text().strip())
        except Exception as exc:
            self.ds_status.setText(f"❌ Import stopped: {exc}")
            self.ds_status.setStyleSheet(f"color: {theme.ORANGE};")
            return
        self.ds_status.setText(
            f"✓ Imported {meta['id']} — {meta['n_images']} images, "
            f"{meta['n_patients']} patients, classes: {', '.join(meta['classes'])}. "
            f"ZIP hash {meta['zip_hash'][:12]}…")
        self.ds_status.setStyleSheet(f"color: {theme.GREEN};")
        self.refresh_all()
        self.ds_list.setCurrentRow(self.ds_list.count() - 1)

    def _show_dataset_report(self, dataset_id: str):
        if not dataset_id:
            return
        dataset_id = dataset_id.split(" ")[0]
        meta = self.lab.store.get(dataset_id)
        if meta is None:
            return
        try:
            rep = self.lab.store.report(dataset_id)
        except Exception as exc:
            self.ds_report.setPlainText(f"Could not load report: {exc}")
            return
        lines = [
            f"DATASET REPORT — {dataset_id}",
            "=" * 46,
            f"Name: {meta['name']}   Source: {meta.get('source') or '—'}",
            f"Imported: {time.strftime('%Y-%m-%d %H:%M', time.localtime(meta['imported_at']))}",
            f"ZIP hash: {meta['zip_hash'][:20]}…",
            f"Structure: {meta['structure']}",
            "",
            f"Images: {rep['n_images']}",
            f"Patients: {rep['n_patients']}",
            f"Patient grouping: {'Available ✓' if rep['patient_ids_available'] else 'NOT available — leakage cannot be reliably ruled out'}",
            f"Classes: {json.dumps(rep['classes'])}",
            f"Images per patient: {rep['images_per_patient']}",
            f"Imbalance ratio: {rep['imbalance_ratio'] if rep['imbalance_ratio'] else '—'}",
            f"Dimensions (top): {json.dumps(rep['dimensions'])}",
            f"Formats: {json.dumps(rep['formats'])}",
            "",
            "DATA QUALITY (nothing is auto-deleted — researcher review):",
            f"  VALID: {rep['n_images'] - len(rep['questionable']) - len(rep['corrupt'])}",
            f"  QUESTIONABLE: {len(rep['questionable'])}"
            + (f"  e.g. {rep['questionable'][:3]}" if rep['questionable'] else ""),
            f"  INVALID (corrupt): {len(rep['corrupt'])}"
            + (f"  e.g. {rep['corrupt'][:3]}" if rep['corrupt'] else ""),
            "",
            f"Exact duplicates: {sum(len(v) - 1 for v in rep['exact_duplicates'].values())}",
            f"Near-duplicate groups: {len(rep['near_duplicates'])}",
            f"Repeated filenames: {len(rep['repeated_filenames'])}",
            f"Missing labels: {len(rep['missing_labels'])}",
            f"Missing patient ids: {len(rep['missing_patient_ids'])}",
        ]
        if rep["leakage_risks"]:
            lines += ["", "⚠ POTENTIAL DATA LEAKAGE DETECTED:"]
            lines += [f"  • {r}" for r in rep["leakage_risks"]]
            lines += ["  Training on this dataset is blocked until resolved."]
        if rep["warnings"]:
            lines += ["", "WARNINGS:"] + [f"  • {w}" for w in rep["warnings"]]
        self.ds_report.setPlainText("\n".join(lines))

    # ================================================================ training
    def _build_training(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page); layout.setSpacing(10)
        layout.setContentsMargins(6, 6, 6, 6)

        top = QHBoxLayout(); top.setSpacing(10)
        cfg_card = SectionCard("Training configuration")
        grid = QGridLayout(); grid.setHorizontalSpacing(10); grid.setVerticalSpacing(6)
        self.cfg_dataset = QComboBox()
        self.cfg_model = QComboBox()
        for key, info in MODEL_ZOO.items():
            self.cfg_model.addItem(f"{info['name']} ({key})", key)
        self.cfg_model.currentIndexChanged.connect(self._update_model_info)
        self.cfg_epochs = QSpinBox(); self.cfg_epochs.setRange(1, 500); self.cfg_epochs.setValue(20)
        self.cfg_batch = QSpinBox(); self.cfg_batch.setRange(1, 512); self.cfg_batch.setValue(32)
        self.cfg_lr = QDoubleSpinBox(); self.cfg_lr.setRange(0.00001, 1.0); self.cfg_lr.setDecimals(5); self.cfg_lr.setValue(0.01)
        self.cfg_imgsize = QSpinBox(); self.cfg_imgsize.setRange(16, 256); self.cfg_imgsize.setValue(32); self.cfg_imgsize.setSuffix(" px")
        self.cfg_hflip = QCheckBox("Horizontal flip (train only)"); self.cfg_hflip.setChecked(True)
        self.cfg_weighting = QComboBox(); self.cfg_weighting.addItems(["balanced", "none"])
        self.cfg_patience = QSpinBox(); self.cfg_patience.setRange(0, 50); self.cfg_patience.setValue(5); self.cfg_patience.setSpecialValueText("off")
        self.cfg_seed = QSpinBox(); self.cfg_seed.setRange(0, 999999); self.cfg_seed.setValue(42)
        self.cfg_train_pct = QSpinBox(); self.cfg_train_pct.setRange(50, 90); self.cfg_train_pct.setValue(70); self.cfg_train_pct.setSuffix("% train")
        self.cfg_val_pct = QSpinBox(); self.cfg_val_pct.setRange(5, 30); self.cfg_val_pct.setValue(15); self.cfg_val_pct.setSuffix("% val")
        rows = [("Dataset", self.cfg_dataset), ("Model", self.cfg_model),
                ("Epochs", self.cfg_epochs), ("Batch size", self.cfg_batch),
                ("Learning rate", self.cfg_lr), ("Image size", self.cfg_imgsize),
                ("Class weighting", self.cfg_weighting), ("Early stopping", self.cfg_patience),
                ("Random seed", self.cfg_seed), ("Split", self.cfg_train_pct)]
        for i, (label, w) in enumerate(rows):
            grid.addWidget(QLabel(label), i // 2, (i % 2) * 2)
            grid.addWidget(w, i // 2, (i % 2) * 2 + 1)
        grid.addWidget(self.cfg_val_pct, len(rows) // 2, 1)
        grid.addWidget(self.cfg_hflip, len(rows) // 2, 3)
        cfg_card.add_layout(grid)
        btn_row = QHBoxLayout()
        rec_btn = QPushButton("Use recommended settings")
        rec_btn.setObjectName("SecondaryButton")
        rec_btn.clicked.connect(self._use_recommended)
        self.start_btn = QPushButton("START TRAINING")
        self.start_btn.clicked.connect(self._start_training)
        self.resume_btn = QPushButton("Resume interrupted run")
        self.resume_btn.setObjectName("SecondaryButton")
        self.resume_btn.clicked.connect(self._resume_training)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("SecondaryButton")
        self.cancel_btn.clicked.connect(self._cancel_training)
        self.cancel_btn.setEnabled(False)
        for b in (rec_btn, self.start_btn, self.resume_btn, self.cancel_btn):
            btn_row.addWidget(b)
        btn_row.addStretch(1)
        cfg_card.add_layout(btn_row)
        self.model_info = QLabel("")
        self.model_info.setObjectName("SmallMuted"); self.model_info.setWordWrap(True)
        cfg_card.add_widget(self.model_info)
        top.addWidget(cfg_card, 2)

        env_card = SectionCard("Training environment")
        self.env_text = QLabel("—")
        self.env_text.setWordWrap(True)
        env_card.add_widget(self.env_text)
        top.addWidget(env_card, 1)
        layout.addLayout(top)

        # ---- live monitor ----
        mon = SectionCard("Training monitor")
        srow = QHBoxLayout(); srow.setSpacing(10)
        self.mon_epoch = StatTile("Epoch", "—")
        self.mon_tloss = StatTile("Training loss", "—")
        self.mon_vloss = StatTile("Validation loss", "—")
        self.mon_vauc = StatTile("Validation AUROC", "—")
        self.mon_eta = StatTile("Time", "—")
        for t in (self.mon_epoch, self.mon_tloss, self.mon_vloss, self.mon_vauc, self.mon_eta):
            srow.addWidget(t, 1)
        mon.add_layout(srow)
        self.mon_progress = QProgressBar(); self.mon_progress.setRange(0, 100)
        mon.add_widget(self.mon_progress)
        plots = QHBoxLayout()
        self.loss_plot = TimeSeriesPlot("Loss (train / validation)", "log-loss", theme.ACCENT_STRONG)
        self.val_loss_curve = self.loss_plot.plot.plot(
            pen=__import__("pyqtgraph").mkPen(theme.ORANGE, width=2))
        self.auc_plot = TimeSeriesPlot("AUROC (train / validation)", "AUROC", theme.GREEN)
        self.val_auc_curve = self.auc_plot.plot.plot(
            pen=__import__("pyqtgraph").mkPen(theme.VIOLET, width=2))
        theme.style_plot(self.loss_plot.plot, y_label="log-loss", x_label="epoch")
        theme.style_plot(self.auc_plot.plot, y_label="AUROC", x_label="epoch")
        plots.addWidget(self.loss_plot); plots.addWidget(self.auc_plot)
        mon.add_layout(plots, 1)
        self.mon_log = QTextEdit(); self.mon_log.setReadOnly(True)
        self.mon_log.setMaximumHeight(110)
        self.mon_log.setPlaceholderText("Training log appears here.")
        mon.add_widget(self.mon_log)
        layout.addWidget(mon, 1)
        self._history = []
        return page

    def _update_model_info(self):
        key = self.cfg_model.currentData()
        info = MODEL_ZOO.get(key, {})
        env = detect_environment()
        note = feasibility_note(env, key)
        self.model_info.setText(
            f"{info.get('description', '')}  Parameters: {info.get('params_estimate', '?')}. "
            f"Input: grayscale {self.cfg_imgsize.value()}×{self.cfg_imgsize.value()}."
            + (f"\n⚠ {note}" if note else ""))

    def _refresh_environment(self):
        env = detect_environment()
        gpu = f"Detected — {env['gpu_name']} ({env['gpu_memory_gb']} GB)" if env["gpu_detected"] else "Not detected"
        self.env_text.setText(
            f"CPU cores: {env['cpu_count']}\n"
            f"RAM: {env['ram_gb'] if env['ram_gb'] else '?'} GB\n"
            f"GPU: {gpu}\n"
            f"CUDA: {'available' if env['cuda_available'] else 'not available'}\n\n"
            f"Estimated training feasibility: {env['feasibility']}\n"
            + ("Lightweight backends run fine on CPU." if not env["gpu_detected"] else ""))
        self._update_model_info()

    def _use_recommended(self):
        cfg = TrainingConfig.recommended("")
        self.cfg_model.setCurrentIndex(0)
        self.cfg_epochs.setValue(cfg.epochs)
        self.cfg_batch.setValue(cfg.batch_size)
        self.cfg_lr.setValue(cfg.learning_rate)
        self.cfg_imgsize.setValue(cfg.image_size)
        self.cfg_hflip.setChecked(cfg.augment_hflip)
        self.cfg_weighting.setCurrentText(cfg.class_weighting)
        self.cfg_patience.setValue(cfg.early_stopping_patience)
        self.cfg_seed.setValue(cfg.seed)
        self.cfg_train_pct.setValue(70)
        self.cfg_val_pct.setValue(15)

    def _collect_config(self) -> Optional[TrainingConfig]:
        dataset_id = (self.cfg_dataset.currentText() or "").split(" ")[0]
        if not dataset_id:
            self._log_line("Select a dataset first (Dataset Manager → Upload dataset ZIP).")
            return None
        tr = self.cfg_train_pct.value() / 100.0
        va = self.cfg_val_pct.value() / 100.0
        te = max(0.05, 1.0 - tr - va)
        total = tr + va + te
        return TrainingConfig(
            dataset_id=dataset_id,
            model=self.cfg_model.currentData(),
            epochs=self.cfg_epochs.value(),
            batch_size=self.cfg_batch.value(),
            learning_rate=self.cfg_lr.value(),
            image_size=self.cfg_imgsize.value(),
            augment_hflip=self.cfg_hflip.isChecked(),
            class_weighting=self.cfg_weighting.currentText(),
            early_stopping_patience=self.cfg_patience.value(),
            split_ratios=(tr / total, va / total, te / total),
            seed=self.cfg_seed.value(),
        )

    def _start_training(self, *, resume_run_id: Optional[str] = None):
        if self.worker is not None and self.worker.isRunning():
            self._log_line("A training run is already in progress.")
            return
        if resume_run_id:
            run = self.lab.resume_run(resume_run_id)
            if run is None:
                self._log_line(f"No resumable run found ({resume_run_id}).")
                return
            resume = True
        else:
            cfg = self._collect_config()
            if cfg is None:
                return
            run = self.lab.new_run(cfg)
            resume = False
        self.current_run = run
        self._history = []
        self.mon_log.clear()
        self._log_line(f"{'Resuming' if resume else 'Starting'} {run.run_id} — "
                       "validate → leakage check → patient-level split → preprocess → train")
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.worker = _TrainingWorker(run, resume=resume)
        self.worker.epoch_done.connect(self._on_epoch)
        self.worker.finished_ok.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def _resume_training(self):
        runs = [r for r in self.lab.list_runs() if r["has_checkpoint"] and not r["evaluated"]]
        if not runs:
            self._log_line("No interrupted run with a checkpoint found.")
            return
        self._start_training(resume_run_id=runs[-1]["run_id"])

    def _cancel_training(self):
        if self.current_run is not None:
            self.current_run.cancel()
            self._log_line("Cancel requested — the checkpoint is kept and the run is resumable.")

    def _on_epoch(self, em: dict):
        self._history.append(em)
        total = self.cfg_epochs.value()
        self.mon_epoch.set(f"{em['epoch'] + 1} / {total}")
        self.mon_tloss.set(f"{em['train_loss']:.3f}")
        self.mon_vloss.set(f"{em['val_loss']:.3f}")
        self.mon_vauc.set(_fmt(em["val_auroc"]))
        eta = em.get("eta_s")
        self.mon_eta.set(f"{em['elapsed_s']:.0f}s",
                         f"≈ {eta:.0f}s remaining" if eta else "")
        self.mon_progress.setValue(int(100 * (em["epoch"] + 1) / max(1, total)))
        xs = [h["epoch"] for h in self._history]
        self.loss_plot.set_data(xs, [h["train_loss"] for h in self._history])
        self.val_loss_curve.setData(xs, [h["val_loss"] for h in self._history])
        self.auc_plot.set_data(xs, [h["train_auroc"] or 0 for h in self._history])
        self.val_auc_curve.setData(xs, [h["val_auroc"] or 0 for h in self._history])
        self._log_line(f"epoch {em['epoch'] + 1}: train_loss={em['train_loss']:.4f} "
                       f"val_loss={em['val_loss']:.4f} val_auroc={_fmt(em['val_auroc'])}")

    def _on_finished(self, summary: dict):
        self.last_summary = summary
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        t = summary.get("test_metrics") or {}
        self._log_line(f"Run {summary['run_id']} finished — test AUROC {_fmt(t.get('auroc'))} "
                       f"(untouched test set, n={t.get('n')}). See Evaluation tab.")
        self._show_evaluation(summary)
        self.refresh_all()

    def _on_failed(self, message: str):
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self._log_line(f"❌ Training stopped: {message}")
        self.eval_text.setPlainText(
            "TRAINING STOPPED\n\n" + message +
            "\n\nNo results were produced (nothing is fabricated). Fix the reported "
            "issue in the Dataset Manager and start again.")

    def _log_line(self, text: str):
        self.mon_log.append(f"[{time.strftime('%H:%M:%S')}] {text}")

    # ============================================================== evaluation
    def _build_evaluation(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page); layout.setSpacing(10)
        layout.setContentsMargins(6, 6, 6, 6)
        card = SectionCard("Evaluation (untouched test set)",
                           "Never accuracy alone: AUROC, AUPRC, sensitivity, specificity, "
                           "precision, F1, confusion matrix, calibration and CIs where feasible.")
        self.eval_text = QTextEdit(); self.eval_text.setReadOnly(True)
        self.eval_text.setPlainText("NOT YET EVALUATED\n\nRun a training first (Training tab).")
        card.add_widget(self.eval_text, 1)
        row = QHBoxLayout()
        self.register_btn = QPushButton("Register as candidate model")
        self.register_btn.clicked.connect(self._register_candidate)
        self.register_btn.setEnabled(False)
        row.addWidget(self.register_btn); row.addStretch(1)
        card.add_layout(row)
        layout.addWidget(card, 1)
        return page

    def _show_evaluation(self, summary: dict):
        t = summary.get("test_metrics") or {}
        v = summary.get("val_metrics") or {}
        split = summary.get("split") or {}
        lines = [
            f"RUN {summary['run_id']} — dataset {summary['dataset_id']} "
            f"(hash {summary['dataset_hash'][:12]}…)",
            f"Classes: {summary['classes']}   Best epoch: {summary['best_epoch'] + 1}   "
            f"Early stopped: {'yes' if summary.get('early_stopped') else 'no'}",
            f"Patient-level split: {'YES ✓' if split.get('patient_level') else 'NO — image-level (leakage cannot be ruled out)'}",
            f"Split: train {split.get('train_images')} img / {split.get('train_patients')} pat · "
            f"val {split.get('val_images')} / {split.get('val_patients')} · "
            f"test {split.get('test_images')} / {split.get('test_patients')}",
            "",
            "TEST-SET METRICS (evaluated once, untouched split):",
            f"  AUROC: {_fmt(t.get('auroc'))}"
            + (f"   95% CI {t['auroc_ci95'][0]:.3f}–{t['auroc_ci95'][1]:.3f}" if t.get("auroc_ci95") else ""),
            f"  AUPRC: {_fmt(t.get('auprc'))}",
            f"  Sensitivity: {_fmt(t.get('sensitivity'))}   Specificity: {_fmt(t.get('specificity'))}",
            f"  Precision: {_fmt(t.get('precision'))}   Recall: {_fmt(t.get('recall'))}   F1: {_fmt(t.get('f1'))}",
            f"  Confusion matrix: {json.dumps(t.get('confusion_matrix') or {})}",
            "",
            f"VALIDATION METRICS (model-selection split): AUROC {_fmt(v.get('auroc'))}, F1 {_fmt(v.get('f1'))}",
            "",
            "CALIBRATION (test set):",
        ]
        for b in (t.get("calibration") or [])[:10]:
            lines.append(f"  {b['bin']}: predicted {b['mean_predicted']:.2f} vs observed "
                         f"{b['observed_rate']:.2f} (n={b['n']})")
        if not t.get("calibration"):
            lines.append("  INSUFFICIENT DATA")
        lines += ["", "Research output — not a medical result. Register as a candidate to "
                      "compare against the current model and request human review."]
        self.eval_text.setPlainText("\n".join(lines))
        self.register_btn.setEnabled(t.get("status") == "EVALUATED")
        self.tabs.setCurrentIndex(3)

    def _register_candidate(self):
        if not self.last_summary or self.current_run is None:
            return
        cfg_dict = asdict(self.current_run.cfg)
        entry = self.lab.registry.register_run(self.last_summary, self.current_run.run_dir, cfg_dict)
        self._log_line(f"Registered {entry['version']} with status {entry['status']} — "
                       "human review required before deployment (Registry & Deployment tab).")
        self.register_btn.setEnabled(False)
        self.refresh_all()
        self.tabs.setCurrentIndex(4)

    # ================================================================ registry
    def _build_registry(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page); layout.setSpacing(10)
        layout.setContentsMargins(6, 6, 6, 6)

        top = QHBoxLayout(); top.setSpacing(10)
        active_card = SectionCard("Current active model")
        self.active_label = QLabel("None deployed — image-derived features remain UNKNOWN.")
        self.active_label.setWordWrap(True)
        self.active_label.setObjectName("BigValue")
        active_card.add_widget(self.active_label)
        rb_row = QHBoxLayout()
        rollback_btn = QPushButton("Rollback model")
        rollback_btn.setObjectName("SecondaryButton")
        rollback_btn.clicked.connect(self._rollback)
        rb_row.addWidget(rollback_btn); rb_row.addStretch(1)
        active_card.add_layout(rb_row)
        top.addWidget(active_card, 1)

        review_card = SectionCard("Human review (approval gate)",
                                  "Only an APPROVED model can become active. Nothing deploys automatically.")
        self.review_model = QComboBox()
        self.reviewer_edit = QLineEdit(); self.reviewer_edit.setPlaceholderText("Reviewer name")
        rrow = QHBoxLayout()
        rrow.addWidget(QLabel("Model")); rrow.addWidget(self.review_model, 1)
        rrow.addWidget(QLabel("Reviewer")); rrow.addWidget(self.reviewer_edit, 1)
        review_card.add_layout(rrow)
        brow = QHBoxLayout()
        approve_btn = QPushButton("APPROVE MODEL")
        approve_btn.clicked.connect(self._approve)
        reject_btn = QPushButton("REJECT MODEL")
        reject_btn.setObjectName("SecondaryButton")
        reject_btn.clicked.connect(self._reject)
        keep_btn = QPushButton("KEEP CURRENT MODEL")
        keep_btn.setObjectName("SecondaryButton")
        keep_btn.clicked.connect(self._keep_current)
        for b in (approve_btn, reject_btn, keep_btn):
            brow.addWidget(b)
        brow.addStretch(1)
        review_card.add_layout(brow)
        self.review_status = QLabel("")
        self.review_status.setWordWrap(True)
        review_card.add_widget(self.review_status)
        top.addWidget(review_card, 2)
        layout.addLayout(top)

        mid = QHBoxLayout(); mid.setSpacing(10)
        reg_card = SectionCard("Model registry")
        self.registry_text = QTextEdit(); self.registry_text.setReadOnly(True)
        self.registry_text.setPlaceholderText("No models registered yet.")
        reg_card.add_widget(self.registry_text, 1)
        mid.addWidget(reg_card, 1)

        cmp_card = SectionCard("Model comparison (current vs candidate)")
        self.compare_text = QTextEdit(); self.compare_text.setReadOnly(True)
        self.compare_text.setPlaceholderText("Select a model above to compare it with the active model.")
        cmp_card.add_widget(self.compare_text, 1)
        ext_row = QHBoxLayout()
        self.ext_dataset = QComboBox()
        ext_btn = QPushButton("Run external validation")
        ext_btn.setObjectName("SecondaryButton")
        ext_btn.clicked.connect(self._external_validate)
        ext_row.addWidget(QLabel("External dataset")); ext_row.addWidget(self.ext_dataset, 1)
        ext_row.addWidget(ext_btn)
        cmp_card.add_layout(ext_row)
        mid.addWidget(cmp_card, 1)
        layout.addLayout(mid, 1)
        self.review_model.currentTextChanged.connect(self._refresh_compare)
        return page

    def _selected_version(self) -> Optional[str]:
        text = self.review_model.currentText()
        return text.split(" ")[0] if text else None

    def _approve(self):
        v = self._selected_version()
        if not v:
            return
        reviewer = self.reviewer_edit.text().strip() or "unnamed reviewer"
        try:
            self.lab.registry.approve(v, reviewer=reviewer)
            self.review_status.setText(f"✓ {v} APPROVED by {reviewer} and deployed as the active model. "
                                       "It is an APPROVED RESEARCH MODEL — not clinically validated.")
            self.review_status.setStyleSheet(f"color: {theme.GREEN};")
        except RegistryError as exc:
            self.review_status.setText(f"Approval refused: {exc}")
            self.review_status.setStyleSheet(f"color: {theme.ORANGE};")
        self.refresh_all()

    def _reject(self):
        v = self._selected_version()
        if not v:
            return
        reviewer = self.reviewer_edit.text().strip() or "unnamed reviewer"
        try:
            self.lab.registry.reject(v, reviewer=reviewer)
            self.review_status.setText(f"{v} REJECTED by {reviewer}. The active model is unchanged.")
            self.review_status.setStyleSheet("")
        except RegistryError as exc:
            self.review_status.setText(str(exc))
        self.refresh_all()

    def _keep_current(self):
        v = self._selected_version()
        if not v:
            return
        reviewer = self.reviewer_edit.text().strip() or "unnamed reviewer"
        try:
            self.lab.registry.keep_current(v, reviewer=reviewer)
            self.review_status.setText(f"Decision recorded: keep the current model; {v} stays a candidate.")
            self.review_status.setStyleSheet("")
        except RegistryError as exc:
            self.review_status.setText(str(exc))
        self.refresh_all()

    def _rollback(self):
        try:
            prev = self.lab.registry.rollback(reviewer=self.reviewer_edit.text().strip() or "unnamed reviewer")
            self.review_status.setText(f"Rolled back — active model is now {prev}.")
            self.review_status.setStyleSheet("")
        except RegistryError as exc:
            self.review_status.setText(f"Rollback not possible: {exc}")
            self.review_status.setStyleSheet(f"color: {theme.ORANGE};")
        self.refresh_all()

    def _external_validate(self):
        v = self._selected_version()
        ds = (self.ext_dataset.currentText() or "").split(" ")[0]
        if not v or not ds:
            return
        try:
            metrics = self.lab.external_validate(v, ds)
            self.review_status.setText(
                f"External validation of {v} on {ds}: "
                f"AUROC {_fmt(metrics.get('auroc'))}, F1 {_fmt(metrics.get('f1'))} "
                f"(status {metrics.get('status')}). Recorded in the registry.")
            self.review_status.setStyleSheet("")
        except Exception as exc:
            self.review_status.setText(f"External validation refused: {exc}")
            self.review_status.setStyleSheet(f"color: {theme.ORANGE};")
        self.refresh_all()

    def _refresh_compare(self):
        v = self._selected_version()
        if not v:
            self.compare_text.clear()
            return
        try:
            cmp = self.lab.registry.compare(self.lab.registry.active_version(), v)
        except RegistryError:
            return
        lines = [
            f"CURRENT:   {cmp['current'].get('version') or '— (no active model)'}",
            f"CANDIDATE: {cmp['candidate'].get('version')}",
            "",
            f"{'Metric':<14}{'Current':>12}{'Candidate':>12}{'Difference':>12}",
            "-" * 50,
        ]
        for row in cmp["rows"]:
            cur = _fmt(row["current"]) if row["current"] is not None else "—"
            cand = _fmt(row["candidate"]) if row["candidate"] is not None else "—"
            diff = f"{row['difference']:+.3f}" if row["difference"] is not None else "—"
            lines.append(f"{row['metric']:<14}{cur:>12}{cand:>12}{diff:>12}")
        c = cmp["candidate"]
        lines += ["", f"Dataset: {c.get('dataset_id')} (hash {c.get('dataset_hash')}…)",
                  f"Test split: {c.get('test_images')} images / {c.get('patients')} patients",
                  f"Architecture: {c.get('architecture')}",
                  f"Trained: {time.strftime('%Y-%m-%d %H:%M', time.localtime(c.get('trained_at') or 0))}"]
        self.compare_text.setPlainText("\n".join(lines))

    # ================================================================ ablation
    def _build_ablation(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page); layout.setSpacing(10)
        layout.setContentsMargins(6, 6, 6, 6)
        card = SectionCard(
            "CHRONO multimodal ablation (Model A–E)",
            "Does longitudinal information add value? Does ultrasound-derived information add "
            "additional value? Results are shown only when a suitable labelled longitudinal "
            "dataset has actually been evaluated — nothing is fabricated.")
        self.ablation_text = QTextEdit(); self.ablation_text.setReadOnly(True)
        card.add_widget(self.ablation_text, 1)
        layout.addWidget(card, 1)
        try:
            from src.validation.longitudinal_experiment import LongitudinalExperiment

            self.ablation_text.setPlainText(
                LongitudinalExperiment.report_table_text() +
                "\n\nModel A: clinical/cycle data only\n"
                "Model B: clinical + conventional wearable summary\n"
                "Model C: clinical + longitudinal CHRONO features\n"
                "Model D: clinical + longitudinal + ultrasound-derived features\n"
                "Model E: full multimodal\n\n"
                "STATUS: PENDING — no dataset in this repository can honestly evaluate "
                "these arms. When a labelled, patient-grouped longitudinal dataset is "
                "registered in the Dataset Manager, the experiment runs under the same "
                "leakage rules as the CV pipeline.")
        except Exception:
            self.ablation_text.setPlainText("Ablation framework unavailable.")
        return page

    # ================================================================ refresh
    def refresh_all(self):
        counts = self.lab.dashboard_counts()
        self.tile_datasets.set(str(counts["datasets"]))
        self.tile_models.set(str(counts["models"]))
        self.tile_approved.set(str(counts["approved"]))
        self.tile_runs.set(str(counts["training_runs"]))
        self.tile_experiments.set(str(counts["experiments"]))
        self.tile_latest.set(counts["latest_run"])
        self.overview_active.setText(
            f"Current active model: {counts['active_model']}"
            + ("" if counts["active_model"] == "None deployed"
               else " — APPROVED RESEARCH MODEL (not clinically validated)"))

        datasets = self.lab.store.list_datasets()
        current_ds = self.cfg_dataset.currentText()
        for combo in (self.cfg_dataset, self.ext_dataset):
            combo.blockSignals(True)
            combo.clear()
            for d in datasets:
                combo.addItem(f"{d['id']}  ({d['n_images']} img, {d['n_patients']} pat)")
            combo.blockSignals(False)
        if current_ds:
            self.cfg_dataset.setCurrentText(current_ds)
        self.ds_list.blockSignals(True)
        self.ds_list.clear()
        for d in datasets:
            self.ds_list.addItem(f"{d['id']}  — {d['n_images']} images, {d['n_patients']} patients")
        self.ds_list.blockSignals(False)

        # registry text + review combo
        models = self.lab.registry.list_models()
        lines = []
        for m in models:
            t = m.get("test_metrics") or {}
            lines.append(
                f"{m['version']}  [{m['status']}]  {m.get('architecture')}  "
                f"dataset {m.get('dataset_id')}  "
                f"AUROC {_fmt(t.get('auroc'))}  F1 {_fmt(t.get('f1'))}  "
                f"({time.strftime('%Y-%m-%d', time.localtime(m['created_at']))})"
                + (f"  ext-val: {len(m.get('external_validations') or [])}" if m.get("external_validations") else ""))
        self.registry_text.setPlainText("\n".join(lines) if lines else "No models registered yet.")
        current_rv = self.review_model.currentText()
        self.review_model.blockSignals(True)
        self.review_model.clear()
        for m in models:
            self.review_model.addItem(f"{m['version']}  [{m['status']}]")
        self.review_model.blockSignals(False)
        if current_rv:
            self.review_model.setCurrentText(current_rv)
        self._refresh_compare()

        active = self.lab.registry.active_model_entry()
        if active:
            t = active.get("test_metrics") or {}
            self.active_label.setText(
                f"Version: {active['version']}\nStatus: APPROVED — APPROVED RESEARCH MODEL "
                f"(not clinically validated)\nTest AUROC: {_fmt(t.get('auroc'))} · F1 {_fmt(t.get('f1'))}\n"
                f"Dataset: {active.get('dataset_id')}")
        else:
            self.active_label.setText(
                "None deployed. Without an approved model, image-derived features in the "
                "ultrasound module remain UNKNOWN (nothing is guessed).")
        cands = self.lab.registry.candidates()
        if cands:
            self.review_status.setText(
                f"CANDIDATE MODEL awaiting review: {', '.join(c['version'] for c in cands)} — "
                "use APPROVE / REJECT / KEEP CURRENT below.")
        self._refresh_environment()

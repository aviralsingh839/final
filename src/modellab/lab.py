"""Model Lab facade + external validation.

`ModelLab` wires the dataset store, run directory and model registry under a
single root (default ``data/model_lab``) and provides the dashboard counters
and the external-validation workflow.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

import numpy as np

from src.config import DATA_DIR
from src.modellab.dataset_store import DatasetStore
from src.modellab.evaluation import evaluate_binary
from src.modellab.registry import ModelRegistry, RegistryError
from src.modellab.splitting import usable_records
from src.modellab.trainer import TrainingConfig, TrainingRun, load_image_array

DEFAULT_ROOT = DATA_DIR / "model_lab"


class ModelLab:
    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root) if root else DEFAULT_ROOT
        self.root.mkdir(parents=True, exist_ok=True)
        self.store = DatasetStore(self.root)
        self.registry = ModelRegistry(self.root)
        self.runs_root = self.root / "runs"
        self.runs_root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------- runs
    def new_run(self, cfg: TrainingConfig) -> TrainingRun:
        return TrainingRun(self.store, self.runs_root, cfg)

    def resume_run(self, run_id: str) -> Optional[TrainingRun]:
        run_dir = self.runs_root / run_id
        cfg_path = run_dir / "config.json"
        if not cfg_path.exists():
            return None
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        raw = dict(data["config"])
        raw["split_ratios"] = tuple(raw.get("split_ratios", (0.7, 0.15, 0.15)))
        cfg = TrainingConfig(**{k: v for k, v in raw.items()
                                if k in TrainingConfig.__dataclass_fields__})
        return TrainingRun(self.store, self.runs_root, cfg, run_id=run_id)

    def list_runs(self):
        out = []
        for d in sorted(self.runs_root.glob("run_*")):
            item = {"run_id": d.name, "dir": str(d),
                    "evaluated": (d / "evaluation.json").exists(),
                    "has_checkpoint": (d / "checkpoint.joblib").exists()}
            cfg = d / "config.json"
            if cfg.exists():
                try:
                    item["config"] = json.loads(cfg.read_text(encoding="utf-8"))
                except Exception:
                    pass
            out.append(item)
        return out

    # -------------------------------------------------------- dashboard
    def dashboard_counts(self) -> dict:
        models = self.registry.list_models()
        runs = self.list_runs()
        latest = "—"
        if runs:
            last = runs[-1]
            latest = "Completed" if last["evaluated"] else (
                "Interrupted (resumable)" if last["has_checkpoint"] else "Prepared")
        n_external = sum(len(m.get("external_validations") or []) for m in models)
        return {
            "datasets": len(self.store.list_datasets()),
            "models": len(models),
            "approved": sum(1 for m in models if m["status"] == "APPROVED"),
            "training_runs": len(runs),
            "experiments": sum(1 for m in models if m["status"] == "EXPERIMENT") + n_external,
            "external_validations": n_external,
            "latest_run": latest,
            "active_model": self.registry.active_version() or "None deployed",
        }

    # ------------------------------------------------ external validation
    def external_validate(self, version: str, dataset_id: str,
                          source: str = "") -> dict:
        """Evaluate a registered model on a completely separate dataset.

        Refuses when the external dataset is the training dataset — external
        data is never mixed into training automatically.
        """
        entry = self.registry.get(version)
        if entry is None:
            raise RegistryError(f"Unknown model {version!r}")
        if dataset_id == entry.get("dataset_id"):
            raise RegistryError(
                "External validation must use a dataset completely separate from training.")
        meta = self.store.get(dataset_id)
        if meta is None:
            raise RegistryError(f"Unknown dataset {dataset_id!r}")

        import joblib

        bundle = joblib.load(entry["model_path"])
        model = bundle["model"]
        classes = bundle["classes"]
        cfg = bundle.get("config") or {}
        image_size = int(cfg.get("image_size", 32))

        rows = [r for r in usable_records(self.store.load_records(dataset_id))
                if r.label in classes]
        if len(rows) < 10:
            return {"status": "INSUFFICIENT DATA",
                    "note": f"Only {len(rows)} usable image(s) share the model's "
                            f"classes {classes}."}
        root = Path(meta["dir"])
        xs, ys = [], []
        for r in rows:
            arr = load_image_array(root / r.image, image_size)
            if arr is None:
                continue
            xs.append(((arr.reshape(-1) - 0.5) / 0.25).astype(np.float32))
            ys.append(classes.index(r.label))
        X = np.stack(xs)
        y = np.asarray(ys, dtype=int)
        if hasattr(model, "predict_proba"):
            p = model.predict_proba(X)[:, 1]
        else:
            from scipy.special import expit

            p = expit(model.decision_function(X))
        metrics = evaluate_binary(y, p)
        metrics["evaluated_at"] = time.time()
        self.registry.add_external_validation(
            version, dataset_id, meta["zip_hash"],
            n_patients=meta.get("n_patients", 0), source=source or meta.get("source", ""),
            metrics=metrics)
        return metrics

"""Model registry, human approval gate, deployment pointer and rollback.

Statuses: EXPERIMENT → CANDIDATE → APPROVED / REJECTED → RETIRED

Hard rules:
  * a model NEVER becomes active without an explicit human ``approve()``
  * the active pointer only ever references an APPROVED model
  * complete history is kept; ``rollback()`` returns to the previous
    approved model
  * every entry stores dataset id + hash, architecture, hyperparameters,
    metrics, preprocessing, seed and code version (reproducibility)
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List, Optional

from src.modellab.evaluation import compare_metrics

STATUSES = ("EXPERIMENT", "CANDIDATE", "APPROVED", "REJECTED", "RETIRED")


class RegistryError(Exception):
    pass


class ModelRegistry:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "registry.json"

    # ------------------------------------------------------------ storage
    def _load(self) -> dict:
        if self.path.exists():
            return json.loads(self.path.read_text(encoding="utf-8"))
        return {"models": [], "active_version": None, "active_history": []}

    def _save(self, data: dict) -> None:
        self.path.write_text(json.dumps(data, indent=1), encoding="utf-8")

    def list_models(self) -> List[dict]:
        return self._load()["models"]

    def get(self, version: str) -> Optional[dict]:
        for m in self.list_models():
            if m["version"] == version:
                return m
        return None

    # ----------------------------------------------------------- register
    def register_run(self, run_summary: dict, run_dir: Path, cfg: dict,
                     status: str = "CANDIDATE") -> dict:
        """Register a finished training run as a versioned model."""
        if status not in STATUSES:
            raise RegistryError(f"Invalid status {status!r}")
        data = self._load()
        version = f"CHRONO-CV-{len(data['models']) + 1:03d}"
        test = run_summary.get("test_metrics") or {}
        if test.get("status") != "EVALUATED":
            status = "EXPERIMENT"   # never a deployment candidate without evaluation
        entry = {
            "version": version,
            "status": status,
            "created_at": time.time(),
            "run_id": run_summary.get("run_id"),
            "run_dir": str(run_dir),
            "model_path": str(Path(run_dir) / "model.joblib"),
            "dataset_id": run_summary.get("dataset_id"),
            "dataset_hash": run_summary.get("dataset_hash"),
            "architecture": cfg.get("model"),
            "hyperparameters": {k: cfg.get(k) for k in
                                ("epochs", "batch_size", "learning_rate", "image_size",
                                 "class_weighting", "early_stopping_patience")},
            "preprocessing": run_summary.get("preprocessing"),
            "split": run_summary.get("split"),
            "classes": run_summary.get("classes"),
            "seed": run_summary.get("seed"),
            "code_version": run_summary.get("code_version"),
            "train_metrics": run_summary.get("train_metrics"),
            "val_metrics": run_summary.get("val_metrics"),
            "test_metrics": test,
            "external_validations": [],
            "review": None,
        }
        data["models"].append(entry)
        self._save(data)
        self._write_model_card(entry)
        return entry

    # ------------------------------------------------- human approval gate
    def approve(self, version: str, reviewer: str, note: str = "") -> dict:
        """HUMAN APPROVAL: mark APPROVED and deploy as the active model."""
        data = self._load()
        entry = self._entry(data, version)
        if entry["status"] not in ("CANDIDATE", "EXPERIMENT", "APPROVED"):
            raise RegistryError(f"{version} cannot be approved from status {entry['status']}.")
        if (entry.get("test_metrics") or {}).get("status") != "EVALUATED":
            raise RegistryError(
                f"{version} has no test-set evaluation (NOT YET EVALUATED) and "
                "cannot be approved.")
        entry["status"] = "APPROVED"
        entry["review"] = {"decision": "APPROVED", "reviewer": reviewer,
                           "note": note, "ts": time.time()}
        previous = data["active_version"]
        data["active_version"] = version
        data["active_history"].append({"version": version, "ts": time.time(),
                                       "action": "deployed", "previous": previous,
                                       "reviewer": reviewer})
        self._save(data)
        self._write_model_card(entry)
        return entry

    def reject(self, version: str, reviewer: str, note: str = "") -> dict:
        data = self._load()
        entry = self._entry(data, version)
        entry["status"] = "REJECTED"
        entry["review"] = {"decision": "REJECTED", "reviewer": reviewer,
                           "note": note, "ts": time.time()}
        self._save(data)
        return entry

    def retire(self, version: str, reviewer: str = "", note: str = "") -> dict:
        data = self._load()
        entry = self._entry(data, version)
        entry["status"] = "RETIRED"
        if data["active_version"] == version:
            data["active_version"] = None
            data["active_history"].append({"version": version, "ts": time.time(),
                                           "action": "retired", "reviewer": reviewer})
        self._save(data)
        return entry

    def keep_current(self, candidate_version: str, reviewer: str, note: str = "") -> dict:
        """[KEEP CURRENT MODEL] — records the decision without deploying."""
        data = self._load()
        entry = self._entry(data, candidate_version)
        entry["review"] = {"decision": "KEEP_CURRENT", "reviewer": reviewer,
                           "note": note, "ts": time.time()}
        self._save(data)
        return entry

    # ---------------------------------------------------------- deployment
    def active_version(self) -> Optional[str]:
        return self._load()["active_version"]

    def active_model_entry(self) -> Optional[dict]:
        v = self.active_version()
        return self.get(v) if v else None

    def candidates(self) -> List[dict]:
        return [m for m in self.list_models() if m["status"] == "CANDIDATE"]

    def rollback(self, reviewer: str = "", note: str = "") -> Optional[str]:
        """Return to the most recent previously-deployed APPROVED model."""
        data = self._load()
        current = data["active_version"]
        previous = None
        for event in reversed(data["active_history"]):
            if event.get("action") == "deployed" and event["version"] == current:
                previous = event.get("previous")
                break
        if previous is None:
            # fall back: latest other approved model
            approved = [m["version"] for m in data["models"]
                        if m["status"] == "APPROVED" and m["version"] != current]
            previous = approved[-1] if approved else None
        if previous is None:
            raise RegistryError("No previous approved model available for rollback.")
        data["active_version"] = previous
        data["active_history"].append({"version": previous, "ts": time.time(),
                                       "action": "rollback", "previous": current,
                                       "reviewer": reviewer, "note": note})
        self._save(data)
        return previous

    def deployment_state(self) -> dict:
        data = self._load()
        active = self.get(data["active_version"]) if data["active_version"] else None
        return {
            "active": active,
            "candidates": [m for m in data["models"] if m["status"] == "CANDIDATE"],
            "history": data["active_history"],
        }

    # ----------------------------------------------------------- inference
    def load_active_model(self):
        """Load the deployed model bundle (or None). Never loads unapproved models."""
        entry = self.active_model_entry()
        if entry is None or entry["status"] != "APPROVED":
            return None
        import joblib

        path = Path(entry["model_path"])
        if not path.exists():
            return None
        bundle = joblib.load(path)
        bundle["version"] = entry["version"]
        return bundle

    # ---------------------------------------------------------- comparison
    def compare(self, current_version: Optional[str], candidate_version: str) -> dict:
        cand = self.get(candidate_version)
        if cand is None:
            raise RegistryError(f"Unknown model {candidate_version!r}")
        cur = self.get(current_version) if current_version else None
        return {
            "rows": compare_metrics((cur or {}).get("test_metrics"),
                                    cand.get("test_metrics")),
            "current": _context(cur),
            "candidate": _context(cand),
        }

    # ---------------------------------------------------- external validation
    def add_external_validation(self, version: str, dataset_id: str,
                                dataset_hash: str, n_patients: int,
                                source: str, metrics: dict) -> dict:
        entry_data = self._load()
        entry = self._entry(entry_data, version)
        if dataset_id == entry.get("dataset_id"):
            raise RegistryError(
                "External validation must use a dataset completely separate from training.")
        entry["external_validations"].append({
            "dataset_id": dataset_id, "dataset_hash": dataset_hash,
            "n_patients": n_patients, "source": source,
            "metrics": metrics, "ts": time.time(),
        })
        self._save(entry_data)
        return entry

    # ------------------------------------------------------------ internals
    @staticmethod
    def _entry(data: dict, version: str) -> dict:
        for m in data["models"]:
            if m["version"] == version:
                return m
        raise RegistryError(f"Unknown model {version!r}")

    # ------------------------------------------------------------ model card
    def _write_model_card(self, entry: dict) -> Path:
        card = model_card_markdown(entry)
        path = Path(entry["run_dir"]) / "model_card.md"
        try:
            path.write_text(card, encoding="utf-8")
        except Exception:
            pass
        return path


def _fmt(v) -> str:
    if v is None:
        return "NOT YET EVALUATED"
    if isinstance(v, float):
        return f"{v:.3f}"
    return str(v)


def _context(entry: Optional[dict]) -> dict:
    if entry is None:
        return {"version": None, "note": "No current model"}
    return {
        "version": entry["version"],
        "status": entry["status"],
        "dataset_id": entry.get("dataset_id"),
        "dataset_hash": (entry.get("dataset_hash") or "")[:12],
        "patients": (entry.get("split") or {}).get("test_patients"),
        "test_images": (entry.get("split") or {}).get("test_images"),
        "trained_at": entry.get("created_at"),
        "architecture": entry.get("architecture"),
    }


def model_card_markdown(entry: dict) -> str:
    t = entry.get("test_metrics") or {}
    split = entry.get("split") or {}
    lines = [
        f"# MODEL CARD — {entry['version']}",
        "",
        f"Status: **{entry['status']}**"
        + ("" if entry["status"] == "APPROVED" else " · NOT CLINICALLY VALIDATED"),
        "",
        "## Purpose",
        "Research decision-support image classifier for the CHRONO-PCOS "
        "multimodal engine. Outputs are research features, never a diagnosis.",
        "",
        "## Training dataset",
        f"- Dataset: {entry.get('dataset_id')} (hash {(entry.get('dataset_hash') or '')[:16]}…)",
        f"- Patients: train {split.get('train_patients')}, val {split.get('val_patients')}, "
        f"test {split.get('test_patients')}",
        f"- Images: train {split.get('train_images')}, val {split.get('val_images')}, "
        f"test {split.get('test_images')}",
        f"- Patient-level split: {'yes' if split.get('patient_level') else 'NO — image-level (leakage cannot be ruled out)'}",
        "",
        "## Architecture & configuration",
        f"- Input: grayscale {entry.get('preprocessing', {}).get('resize')} images",
        f"- Architecture: {entry.get('architecture')}",
        f"- Hyperparameters: {json.dumps(entry.get('hyperparameters') or {})}",
        f"- Preprocessing: {json.dumps(entry.get('preprocessing') or {})}",
        f"- Random seed: {entry.get('seed')} · Code: {entry.get('code_version')}",
        "",
        "## Test-set metrics (untouched split)",
        f"- AUROC: {_fmt(t.get('auroc'))}"
        + (f" (95% CI {t['auroc_ci95'][0]:.3f}–{t['auroc_ci95'][1]:.3f})" if t.get("auroc_ci95") else ""),
        f"- AUPRC: {_fmt(t.get('auprc'))}",
        f"- Sensitivity: {_fmt(t.get('sensitivity'))} · Specificity: {_fmt(t.get('specificity'))}",
        f"- Precision: {_fmt(t.get('precision'))} · F1: {_fmt(t.get('f1'))}",
        f"- Confusion matrix: {json.dumps(t.get('confusion_matrix') or {})}",
        "",
        "## Validation strategy",
        "Patient-level train/validation/test split with leakage checks "
        "(duplicate hashes, near-duplicates, cross-split patients); early "
        "stopping on validation loss; single final evaluation on the untouched "
        "test split.",
        "",
        "## Intended use",
        "Research and development inside the CHRONO Model Lab; decision-support "
        "feature extraction in the CHRONO ultrasound module ONLY after human "
        "approval.",
        "",
        "## Not intended for",
        "Autonomous diagnosis, treatment decisions, prescribing, screening "
        "without clinician oversight, or any use outside research.",
        "",
        "## Known limitations",
        "- APPROVED RESEARCH MODEL — not clinically validated.",
        "- Trained on a single registered dataset; external generalization unknown "
        "until external validation is recorded.",
        "- Lightweight backend on downscaled grayscale images.",
        "",
        f"Training date: {time.strftime('%Y-%m-%d %H:%M', time.localtime(entry.get('created_at', 0)))}",
        f"Version: {entry['version']}",
    ]
    return "\n".join(lines)

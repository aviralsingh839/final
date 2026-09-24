"""Controlled automated training pipeline.

Runs the full engineering workflow when a researcher presses START TRAINING:

  1. validate dataset          (labels, usable images)
  2. check leakage             (STOP on findings)
  3. patient-level split       (image-level only with explicit warning)
  4. prepare preprocessing     (train-only augmentation; settings recorded)
  5. initialize model          (small, well-defined backends)
  6. train with per-epoch validation, checkpoints, early stopping
  7. select the best epoch     (candidate model)
  8. evaluate once on the untouched test set

Backends (deliberately small — no giant model is auto-selected):

  * ``baseline_linear``  — logistic-regression baseline on normalized pixels
                           (scikit-learn SGDClassifier, real epoch loop)
  * ``mlp_small``        — small multilayer perceptron (scikit-learn)
  * ``cnn_transfer``     — transfer-learning CNN; requires PyTorch/GPU and is
                           refused gracefully when unavailable

Every run writes a complete, reproducible artifact directory::

    runs/run_NNN/
        config.json      metrics.csv      training.log
        checkpoint.joblib  model.joblib   evaluation.json   model_card.md

Interruption safe: checkpoints carry model, epoch, config, metric history and
RNG seed, so a run can resume where it stopped.
"""
from __future__ import annotations

import csv
import io
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

import joblib
import numpy as np

from src.modellab.dataset_store import DatasetStore, ImageRecord
from src.modellab.evaluation import evaluate_binary
from src.modellab.resources import detect_environment, feasibility_note
from src.modellab.splitting import LeakageError, SplitResult, check_split_leakage, split_records

MODEL_ZOO = {
    "baseline_linear": {
        "name": "Lightweight linear baseline",
        "description": "Logistic regression on normalized pixels — fast, CPU-friendly reference model.",
        "params_estimate": "≈ image_size² (+1) weights",
        "requires_torch": False,
    },
    "mlp_small": {
        "name": "Small neural network (MLP)",
        "description": "One hidden layer (128 units) on normalized pixels — still CPU-feasible.",
        "params_estimate": "≈ 128 · image_size² weights",
        "requires_torch": False,
    },
    "cnn_transfer": {
        "name": "Transfer-learning CNN",
        "description": "Pretrained convolutional backbone; requires PyTorch and ideally a GPU.",
        "params_estimate": "millions (backbone-dependent)",
        "requires_torch": True,
    },
}


class TrainingBlockedError(Exception):
    """Critical validation failed — training refused to start."""


@dataclass
class TrainingConfig:
    dataset_id: str = ""
    model: str = "baseline_linear"
    epochs: int = 20
    batch_size: int = 32
    learning_rate: float = 0.01
    image_size: int = 32                 # square, grayscale
    augment_hflip: bool = True           # TRAIN ONLY — never applied to val/test
    augment_brightness: float = 0.0      # +/- fraction, TRAIN ONLY
    class_weighting: str = "balanced"    # balanced | none
    imbalance_strategy: str = "class_weighting"  # documented strategy
    early_stopping_patience: int = 5     # 0 disables
    split_ratios: tuple = (0.7, 0.15, 0.15)
    seed: int = 42
    notes: str = ""

    @staticmethod
    def recommended(dataset_id: str) -> "TrainingConfig":
        """[USE RECOMMENDED SETTINGS] — sane defaults for beginners."""
        return TrainingConfig(dataset_id=dataset_id)


# ------------------------------------------------------------ preprocessing
def load_image_array(path: Path, image_size: int) -> Optional[np.ndarray]:
    try:
        from PIL import Image

        with Image.open(path) as im:
            arr = np.asarray(im.convert("L").resize((image_size, image_size)),
                             dtype=np.float32) / 255.0
        return arr
    except Exception:
        return None


def prepare_arrays(root: Path, rows: List[ImageRecord], cfg: TrainingConfig,
                   classes: List[str], augment: bool, rng: np.random.Generator):
    """Load + preprocess a split.  Augmentation ONLY when ``augment`` is True
    (training split) — validation/test images are never augmented."""
    xs, ys = [], []
    for r in rows:
        arr = load_image_array(root / r.image, cfg.image_size)
        if arr is None or r.label not in classes:
            continue
        y = classes.index(r.label)
        xs.append(arr)
        ys.append(y)
        if augment:
            if cfg.augment_hflip:
                xs.append(arr[:, ::-1])
                ys.append(y)
            if cfg.augment_brightness > 0:
                delta = float(rng.uniform(-cfg.augment_brightness, cfg.augment_brightness))
                xs.append(np.clip(arr + delta, 0.0, 1.0))
                ys.append(y)
    if not xs:
        return np.zeros((0, cfg.image_size ** 2), dtype=np.float32), np.zeros((0,), dtype=int)
    X = np.stack(xs).reshape(len(xs), -1)
    # Standardize with fixed constants (recorded) so val/test see no train stats.
    X = (X - 0.5) / 0.25
    return X.astype(np.float32), np.asarray(ys, dtype=int)


def preprocessing_record(cfg: TrainingConfig) -> dict:
    return {
        "color": "grayscale",
        "resize": [cfg.image_size, cfg.image_size],
        "scale": "pixel/255",
        "normalize": {"mean": 0.5, "std": 0.25},
        "train_augmentation": {
            "horizontal_flip": cfg.augment_hflip,
            "brightness_jitter": cfg.augment_brightness,
        },
        "val_test_augmentation": "none (augmentation never applied outside training)",
        "imbalance_strategy": cfg.imbalance_strategy,
    }


# ----------------------------------------------------------------- backends
def _make_model(cfg: TrainingConfig, classes: List[str]):
    if cfg.model == "cnn_transfer":
        env = detect_environment()
        if not env["torch_available"]:
            raise TrainingBlockedError(
                "This training configuration may require a GPU-enabled environment. "
                "The transfer-learning CNN backend needs PyTorch, which is not "
                "installed here. Choose 'baseline_linear' or 'mlp_small' to train "
                "on this machine.")
        raise TrainingBlockedError(
            "The transfer-learning CNN backend is not enabled in this build; "
            "use a lightweight backend or a GPU-enabled environment.")
    if cfg.model == "mlp_small":
        from sklearn.neural_network import MLPClassifier

        return MLPClassifier(hidden_layer_sizes=(128,), learning_rate_init=cfg.learning_rate,
                             batch_size=cfg.batch_size, max_iter=1, warm_start=False,
                             random_state=cfg.seed)
    if cfg.model == "baseline_linear":
        from sklearn.linear_model import SGDClassifier

        # class_weight='balanced' is unsupported with partial_fit; balancing is
        # applied via explicit per-sample weights in the training loop instead.
        return SGDClassifier(loss="log_loss", learning_rate="constant",
                             eta0=cfg.learning_rate, alpha=1e-4, random_state=cfg.seed)
    raise TrainingBlockedError(f"Unknown model backend: {cfg.model!r}")


def _partial_fit(model, X, y, classes_idx, sample_weight=None):
    try:
        model.partial_fit(X, y, classes=classes_idx, sample_weight=sample_weight)
    except TypeError:
        model.partial_fit(X, y, classes=classes_idx)


def _scores(model, X) -> np.ndarray:
    if hasattr(model, "predict_proba"):
        try:
            return model.predict_proba(X)[:, 1]
        except Exception:
            pass
    from scipy.special import expit

    return expit(model.decision_function(X))


def _log_loss(y, p) -> float:
    p = np.clip(p, 1e-7, 1 - 1e-7)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


# ------------------------------------------------------------------ runner
@dataclass
class EpochMetrics:
    epoch: int
    train_loss: float
    val_loss: float
    train_auroc: Optional[float]
    val_auroc: Optional[float]
    learning_rate: float
    elapsed_s: float
    eta_s: Optional[float]


class TrainingRun:
    """One controlled training run with checkpointing and resumability."""

    def __init__(self, store: DatasetStore, runs_root: Path, cfg: TrainingConfig,
                 run_id: Optional[str] = None):
        self.store = store
        self.cfg = cfg
        self.runs_root = Path(runs_root)
        self.runs_root.mkdir(parents=True, exist_ok=True)
        if run_id is None:
            run_id = f"run_{len(list(self.runs_root.glob('run_*'))) + 1:03d}"
        self.run_id = run_id
        self.run_dir = self.runs_root / run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.history: List[EpochMetrics] = []
        self.cancelled = False
        self._log_lines: List[str] = []

    # ------------------------------------------------------------ logging
    def _log(self, msg: str):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        self._log_lines.append(line)
        with open(self.run_dir / "training.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def cancel(self):
        self.cancelled = True

    # ------------------------------------------------------------- checks
    def _validate(self) -> tuple:
        meta = self.store.get(self.cfg.dataset_id)
        if meta is None:
            raise TrainingBlockedError(f"Dataset {self.cfg.dataset_id!r} not found.")
        records = self.store.load_records(self.cfg.dataset_id)
        report = self.store.report(self.cfg.dataset_id)
        classes = sorted({r.label for r in records if r.label})
        if len(classes) != 2:
            raise TrainingBlockedError(
                f"INSUFFICIENT DATA: exactly 2 classes are required for this pipeline "
                f"(found {len(classes)}: {classes}).")
        if report.get("leakage_risks"):
            raise LeakageError(
                "Potential data leakage detected.\n" + "\n".join(report["leakage_risks"]))
        split = split_records(records, self.cfg.split_ratios, self.cfg.seed)
        check_split_leakage(split)      # raises LeakageError on findings
        return meta, records, classes, split

    # -------------------------------------------------------------- train
    def execute(self, progress_cb: Optional[Callable[[EpochMetrics], None]] = None,
                resume: bool = False) -> dict:
        """Run (or resume) the full pipeline; returns the run summary dict."""
        cfg = self.cfg
        t0 = time.time()
        self._log(f"Run {self.run_id}: validating dataset {cfg.dataset_id}")
        meta, records, classes, split = self._validate()
        root = Path(meta["dir"])
        rng = np.random.default_rng(cfg.seed)

        preprocessing = preprocessing_record(cfg)
        (self.run_dir / "config.json").write_text(json.dumps({
            "run_id": self.run_id,
            "config": {**asdict(cfg), "split_ratios": list(cfg.split_ratios)},
            "dataset": {"id": meta["id"], "hash": meta["zip_hash"],
                        "n_images": meta["n_images"], "n_patients": meta["n_patients"]},
            "classes": classes,
            "split": split.summary(),
            "preprocessing": preprocessing,
            "environment": detect_environment(),
            "code_version": _code_version(),
            "started_at": t0,
        }, indent=1), encoding="utf-8")

        if not split.patient_level:
            self._log("WARNING: Patient-level leakage cannot be reliably ruled out "
                      "(image-level split).")

        self._log("Preparing preprocessing (train-only augmentation)")
        Xtr, ytr = prepare_arrays(root, split.train, cfg, classes, augment=True, rng=rng)
        Xva, yva = prepare_arrays(root, split.val, cfg, classes, augment=False, rng=rng)
        Xte, yte = prepare_arrays(root, split.test, cfg, classes, augment=False, rng=rng)
        if min(len(ytr), len(yva), len(yte)) == 0:
            raise TrainingBlockedError("INSUFFICIENT DATA: an empty split remained after preprocessing.")
        self._log(f"Split ready: train={len(ytr)} (augmented), val={len(yva)}, test={len(yte)}")

        start_epoch = 0
        model = None
        best = {"val_loss": float("inf"), "epoch": -1, "model_bytes": None}
        ckpt_path = self.run_dir / "checkpoint.joblib"
        if resume and ckpt_path.exists():
            ck = joblib.load(ckpt_path)
            model = ck["model"]
            start_epoch = ck["epoch"] + 1
            best = ck["best"]
            self.history = [EpochMetrics(**m) for m in ck["history"]]
            self._log(f"Resumed from checkpoint at epoch {start_epoch}")
        if model is None:
            model = _make_model(cfg, classes)
            self._log(f"Initialized model backend '{cfg.model}'")

        classes_idx = np.array([0, 1])
        sample_weight = None
        if cfg.class_weighting == "balanced":
            # documented imbalance strategy: inverse-frequency sample weights
            counts = np.bincount(ytr, minlength=2).astype(float)
            weights = counts.sum() / (2.0 * np.maximum(counts, 1))
            sample_weight = weights[ytr]
            if cfg.model == "mlp_small":
                # MLPClassifier.partial_fit has no sample_weight support.
                sample_weight = None

        n_batches = max(1, int(np.ceil(len(ytr) / cfg.batch_size)))
        bad_epochs = 0
        for epoch in range(start_epoch, cfg.epochs):
            if self.cancelled:
                self._log("Training cancelled by researcher — checkpoint retained.")
                break
            order = rng.permutation(len(ytr))
            for b in range(n_batches):
                idx = order[b * cfg.batch_size:(b + 1) * cfg.batch_size]
                if len(idx) == 0:
                    continue
                sw = sample_weight[idx] if sample_weight is not None else None
                _partial_fit(model, Xtr[idx], ytr[idx], classes_idx, sw)

            p_tr = _scores(model, Xtr)
            p_va = _scores(model, Xva)
            from src.modellab.evaluation import _safe_auroc

            elapsed = time.time() - t0
            done = epoch - start_epoch + 1
            remaining = cfg.epochs - epoch - 1
            em = EpochMetrics(
                epoch=epoch,
                train_loss=_log_loss(ytr, p_tr),
                val_loss=_log_loss(yva, p_va),
                train_auroc=_safe_auroc(ytr, p_tr),
                val_auroc=_safe_auroc(yva, p_va),
                learning_rate=cfg.learning_rate,
                elapsed_s=elapsed,
                eta_s=(elapsed / done) * remaining if remaining > 0 else 0.0,
            )
            self.history.append(em)
            self._append_metrics_csv(em)
            self._log(f"epoch {epoch + 1}/{cfg.epochs} "
                      f"train_loss={em.train_loss:.4f} val_loss={em.val_loss:.4f} "
                      f"val_auroc={em.val_auroc if em.val_auroc is not None else 'n/a'}")
            if progress_cb:
                progress_cb(em)

            if em.val_loss < best["val_loss"] - 1e-6:
                best = {"val_loss": em.val_loss, "epoch": epoch,
                        "model_bytes": _dump_model(model)}
                bad_epochs = 0
            else:
                bad_epochs += 1

            joblib.dump({
                "model": model, "epoch": epoch, "best": best,
                "config": asdict(cfg),
                "history": [asdict(m) for m in self.history],
                "seed": cfg.seed,
            }, ckpt_path)

            if cfg.early_stopping_patience and bad_epochs >= cfg.early_stopping_patience:
                self._log(f"Early stopping: validation loss has not improved for "
                          f"{cfg.early_stopping_patience} epochs.")
                break

        # Candidate = best-validation epoch, evaluated ONCE on the untouched test set.
        candidate = _load_model(best["model_bytes"]) if best["model_bytes"] else model
        p_te = _scores(candidate, Xte)
        test_eval = evaluate_binary(yte, p_te, seed=cfg.seed)
        p_va_best = _scores(candidate, Xva)
        val_eval = evaluate_binary(yva, p_va_best, seed=cfg.seed)
        joblib.dump({"model": candidate, "classes": classes,
                     "preprocessing": preprocessing, "config": asdict(cfg)},
                    self.run_dir / "model.joblib")
        summary = {
            "run_id": self.run_id,
            "dataset_id": meta["id"],
            "dataset_hash": meta["zip_hash"],
            "classes": classes,
            "split": split.summary(),
            "preprocessing": preprocessing,
            "best_epoch": best["epoch"],
            "epochs_completed": len(self.history),
            "early_stopped": bool(cfg.early_stopping_patience and bad_epochs >= cfg.early_stopping_patience),
            "cancelled": self.cancelled,
            "val_metrics": val_eval,
            "test_metrics": test_eval,
            "train_metrics": {
                "final_train_loss": self.history[-1].train_loss if self.history else None,
                "final_val_loss": self.history[-1].val_loss if self.history else None,
            },
            "seed": cfg.seed,
            "code_version": _code_version(),
            "finished_at": time.time(),
        }
        (self.run_dir / "evaluation.json").write_text(json.dumps(summary, indent=1),
                                                      encoding="utf-8")
        self._log(f"Test AUROC: {test_eval.get('auroc')} (untouched test set, "
                  f"{test_eval.get('n')} images)")
        return summary

    def _append_metrics_csv(self, em: EpochMetrics):
        path = self.run_dir / "metrics.csv"
        new = not path.exists()
        with open(path, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["epoch", "train_loss", "val_loss", "train_auroc",
                            "val_auroc", "learning_rate", "elapsed_s"])
            w.writerow([em.epoch, f"{em.train_loss:.6f}", f"{em.val_loss:.6f}",
                        em.train_auroc, em.val_auroc, em.learning_rate,
                        f"{em.elapsed_s:.1f}"])


def _dump_model(model) -> bytes:
    buf = io.BytesIO()
    joblib.dump(model, buf)
    return buf.getvalue()


def _load_model(blob: bytes):
    return joblib.load(io.BytesIO(blob))


def _code_version() -> str:
    from src.config import APP_VERSION

    return f"CHRONO-PCOS v{APP_VERSION}"

"""Training audit log (V5, item C + N).

Every training run records a reproducible audit entry: model version, dataset
version/id, feature list, preprocessing, hyperparameters, training date, subject
and sample counts, the train/validation split scheme, random seed, and metrics.

Entries are appended to `data/training_audit.jsonl` (one JSON object per line).
Nothing is ever fabricated here: an entry is written only by the training script
that actually produced the artifact.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.config import DATA_DIR

AUDIT_PATH = DATA_DIR / "training_audit.jsonl"


def record_training_audit(entry: Dict[str, Any], path: Path = AUDIT_PATH) -> None:
    """Append one audit record. `entry` must contain `model_id` and `model_name`.

    The record is stamped with `trained_at` if not already present.
    """
    entry = dict(entry)
    entry.setdefault("model_id", "unknown")
    entry.setdefault("model_name", entry["model_id"])
    entry.setdefault("trained_at", time.time())
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def load_audits(path: Path = AUDIT_PATH) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    entries: List[Dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def latest_audit(model_id: str, path: Path = AUDIT_PATH) -> Optional[Dict[str, Any]]:
    entries = [e for e in load_audits(path) if e.get("model_id") == model_id]
    if not entries:
        return None
    return max(entries, key=lambda e: e.get("trained_at", 0.0))


def audit_summary(path: Path = AUDIT_PATH) -> str:
    """Human-readable summary of all recorded training runs."""
    entries = load_audits(path)
    if not entries:
        return "No training audits recorded yet — run a training script to produce one."
    lines = [f"Training audit history ({len(entries)} run(s)):"]
    for e in sorted(entries, key=lambda x: x.get("trained_at", 0.0)):
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(e.get("trained_at", 0.0)))
        auc = e.get("metrics", {}).get("roc_auc")
        auc_s = f", AUC {auc:.3f}" if isinstance(auc, (int, float)) else ""
        lines.append(
            f"  [{when}] {e.get('model_name', e.get('model_id'))} "
            f"(id={e.get('model_id', '?')}) v{e.get('version', '?')} — "
            f"dataset '{e.get('dataset_id', e.get('dataset', '?'))}', "
            f"{e.get('n_subjects', '?')} subjects / {e.get('n_samples', '?')} samples, "
            f"split {e.get('split_scheme', '?')}, seed {e.get('random_seed', '?')}{auc_s}"
        )
    return "\n".join(lines)


def reproducibility_block(model_id: str, path: Path = AUDIT_PATH) -> str:
    """Full reproducibility record for one model, for reports / evidence display."""
    e = latest_audit(model_id, path)
    if e is None:
        return f"{model_id}: no audit entry."
    lines = [
        f"{e.get('model_name', model_id)} v{e.get('version', '?')}",
        f"  trained at: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(e.get('trained_at', 0.0)))}",
        f"  dataset: {e.get('dataset_id', e.get('dataset', '?'))}",
        f"  subjects: {e.get('n_subjects', '?')}   samples: {e.get('n_samples', '?')}",
        f"  split: {e.get('split_scheme', '?')}   seed: {e.get('random_seed', '?')}",
        f"  features ({len(e.get('feature_list', []))}): {', '.join(e.get('feature_list', []))}",
    ]
    pre = e.get("preprocessing")
    if pre:
        lines.append(f"  preprocessing: {pre if isinstance(pre, str) else json.dumps(pre, default=str)}")
    hp = e.get("hyperparameters")
    if hp:
        lines.append(f"  hyperparameters: {hp if isinstance(hp, str) else json.dumps(hp, default=str)}")
    m = e.get("metrics", {})
    if m:
        lines.append("  metrics: " + json.dumps({k: (round(v, 4) if isinstance(v, float) else v) for k, v in m.items()}))
    return "\n".join(lines)

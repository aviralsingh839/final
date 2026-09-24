"""Ablation study (V6): how much each sensor modality contributes to the risk score.

Systematically zeroes the domain scores driven by each modality (and isolates
single modalities) and recomputes the risk with the frozen explainable engine.
The result is a comparison table + graph, and an explicit answer to "what if
this sensor were missing?".

Domains are the V6 defensible set only. No hormone/endocrine, VoxVasc or
metabolic-vascular domains exist here — those never enter the risk score, so
they cannot be ablated.

IMPORTANT: this is a *mechanism* ablation of the explainable fallback engine,
not a trained-model ablation. Real ablation studies on a trained model with
AUROC/AUPRC/calibration per configuration are run by the validation pipeline
(see docs/V6_BUILD_SPECIFICATION.md §18) once labelled longitudinal data exists.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Set

from src.data_models import FeatureVector, RiskResult
from src.models.risk_engine import RiskEngine

# modality -> domains it drives (V6 core inputs)
MODALITY_DOMAINS: Dict[str, Set[str]] = {
    "PPG (HR/HRV)": {"stress_autonomic", "sleep", "circadian", "metabolic"},
    "Temperature": {"temperature_rhythm", "circadian"},
    "IMU (motion/activity)": {"low_activity", "circadian", "sleep"},
    "GSR": {"stress_autonomic", "circadian"},
    "ECG (periodic)": {"stress_autonomic", "sleep"},
    "Manual BP": {"bp"},
    "Manual glucose": {"glucose", "metabolic"},
    "Cycle / symptoms (clinical)": {"cycle"},
}

ALL_DOMAINS: Set[str] = {
    "cycle", "metabolic", "glucose", "bp", "stress_autonomic",
    "sleep", "circadian", "temperature_rhythm", "low_activity",
}


@dataclass
class AblationConfig:
    name: str
    zero: Set[str]      # domains forced to 0 (removed)
    keep: Set[str]      # if non-empty, only these domains survive (isolated)

    def apply(self, domains: Dict[str, float]) -> Dict[str, float]:
        out = dict(domains)
        if self.keep:
            for k in ALL_DOMAINS:
                if k not in self.keep:
                    out[k] = 0.0
        for k in self.zero:
            out[k] = 0.0
        return out


@dataclass
class AblationRow:
    name: str
    risk: float
    delta: float  # vs all-sensors risk

    def render(self) -> str:
        arrow = "↑" if self.delta > 0 else "↓" if self.delta < 0 else "→"
        return f"{self.name}: {self.risk:.1f}% ({arrow} {abs(self.delta):.1f} pts vs all sensors)"


def ablation_configs() -> List[AblationConfig]:
    cfg = [AblationConfig("All sensors", set(), ALL_DOMAINS)]
    for mod, doms in MODALITY_DOMAINS.items():
        cfg.append(AblationConfig(f"{mod} removed", doms, set()))
    for mod, doms in MODALITY_DOMAINS.items():
        cfg.append(AblationConfig(f"{mod} only", set(), doms))
    return cfg


def run_ablation(domains: Dict[str, float], risk_engine: RiskEngine | None = None) -> List[AblationRow]:
    """Ablation of a domain-score dict (e.g. from a RiskResult or FeatureVector)."""
    engine = risk_engine or RiskEngine()
    # Fill any missing V6 domain keys with 0 so a partial dict still ablates cleanly.
    full = {k: domains.get(k, 0.0) for k in ALL_DOMAINS}
    base = engine._risk_from_scores(full)
    rows: List[AblationRow] = []
    for cfg in ablation_configs():
        d = cfg.apply(full)
        risk = engine._risk_from_scores(d)
        rows.append(AblationRow(cfg.name, float(risk), float(risk - base)))
    return rows


def domains_from_feature(fv: FeatureVector, profile=None) -> Dict[str, float]:
    """Domain scores for a feature vector (mirrors the risk engine, V6)."""
    return RiskEngine().domain_scores(fv, profile=profile)


def domains_from_result(result: RiskResult) -> Dict[str, float]:
    return dict(result.domain_scores)

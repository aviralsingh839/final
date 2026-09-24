"""Validation Lab: scientific-validation modules for the CHRONO-PCOS dashboard.

Implements the validation features (reference-device agreement, repeatability,
SQI + prediction rejection, leave-one-subject-out CV, calibration, ablation,
leakage detection, prospective validation, model versioning, ground-truth
store, automated validation report, and the limitations/claim guard).

Every module is explicit about what it validates: synthetic data never
establishes clinical validity; sensor-derived hormone values are estimates.
"""

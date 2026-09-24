# Models folder

Training scripts save `.joblib` files here:

- `stress_model.joblib`
- `sleep_model.joblib`
- `pcos_risk_model.joblib`
- `hormone_models.joblib`
- `ppg_quality_model.joblib`

If these files are missing, the app still runs using transparent mathematical fallback models.

`pcos_risk_model.joblib` is trained from the bundled public Kaggle dataset
(`data/public/PCOS_data_without_infertility.xlsx`, 541 patients) with

    python scripts/train_pcos_risk_model.py \
        --csv data/public/PCOS_data_without_infertility.xlsx \
        --out models/pcos_risk_model.joblib

Reported patient-level 5-fold CV: ROC-AUC 0.959, average precision 0.932
(see the `meta` dict inside the bundle for full details). The pregnancy-screen
columns (beta-HCG / Pregnant / abortions) are intentionally excluded.
`data/public/PCOS_extended_dataset.csv` is a synthetic augmentation of the same
530 patients and is excluded by default — it does not improve real held-out
accuracy (pass `--extended` to include it anyway).

`ppg_quality_model.joblib` is a PPG signal-quality / motion-artifact model
(scripts/train_ppg_quality_model.py) trained on the PhysioNet *Wrist PPG During
Exercise* database (8 subjects, 19 recordings of chest ECG + wrist PPG + IMU;
the PhysioNet page has been withdrawn, files are retained locally in
`data/public/wrist_ppg_during_exercise/`). For each 10 s window it predicts
whether the app's PPG HR estimate is reliable (within 5 bpm of the ECG
reference). Subject-level 5-fold CV: ROC-AUC ≈ 0.62; at a 0.5 threshold it keeps
≈ 28% of windows with ≈ 58% usable precision vs a 35% base rate. The app blends
this probability (40% weight) into the `ppg_quality()` heuristic when the model
file exists; delete the file to revert to the pure heuristic. Educational
artifact — the wrist PPG sensor differs from the MAX30102.

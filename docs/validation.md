# Validation Plan

## Sensor validation

| Measurement | Validation |
|---|---|
| Heart rate | Compare with commercial pulse oximeter/smartwatch at rest and after light movement. |
| SpO2 estimate | Compare with pulse oximeter; label non-medical. |
| Skin temperature | Compare DS18B20 with digital thermometer under stable conditions. |
| Motion index | Compare quiet rest vs walking vs hand shake. |
| GSR | Compare rest vs mental arithmetic/public-speaking stressor. |
| Sleep | Compare with sleep diary; optional smartwatch comparison. |

## Model validation

| Model | Dataset | Method |
|---|---|---|
| Stress | WESAD | Leave-one-subject-out or stratified cross-validation. |
| Sleep | BIDSleep/MESA | Epoch accuracy, F1, Cohen's kappa. |
| PCOS clinical risk | Kaggle PCOS | Stratified 5-fold CV, ROC-AUC, calibration/Brier score. |
| Hormone models | mcPHASES, MMASH, NHANES | MAE/RMSE when direct hormone labels are available; otherwise show uncertainty. |

## Exhibition validation display

Show these numbers in a `Model Evidence` panel:

- current signal-quality score,
- feature completeness,
- model agreement,
- confidence interval width,
- which features increased/decreased estimated risk.

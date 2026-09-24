# Data folder

Place downloaded public datasets here. Do not invent synthetic medical datasets.

Suggested layout:

```text
data/public/WESAD/S2/S2.pkl
data/public/pcos/PCOS_data.csv
data/processed/sleep_epochs.csv
data/processed/hormone_daylevel.csv
```

The dashboard can run without these datasets using transparent fallback equations and demo sensor stream, but model validation/training requires real public data.

# Scientific Model Notes

## Boundary

This project estimates an educational PCOD/PCOS risk tendency. It does not diagnose PCOD/PCOS. Hormone values are model-estimated, not measured.

## Physiological pathway summary

### Sleep/circadian → cortisol → insulin resistance → androgens

Poor sleep and circadian rhythm disruption can increase sympathetic/HPA-axis load and worsen glucose regulation. In PCOS research, circadian disruption has been associated with reduced sleep efficiency, altered melatonin, and elevated evening cortisol.

### Insulin resistance → hyperinsulinemia → androgen excess tendency

Insulin resistance can increase insulin demand. Hyperinsulinemia can contribute to ovarian androgen production and reduce hepatic SHBG, increasing free androgen tendency.

### Progesterone/temperature

After ovulation, progesterone has a thermogenic effect. A sustained biphasic rise in basal/resting temperature provides weak evidence for a luteal progesterone pattern. Skin temperature is noisier than core/basal temperature, so confidence is limited.

## Core formulas

### Logistic transform

```math
sigma(x) = 1/(1+exp(-x))
```

### Final risk score

All domain scores are 0–1.

```math
z = -2.3 + 1.20M + 0.90H + 0.65S + 0.60C + 0.50A + 0.45G + 0.30L + 0.20T + 0.35MH
Risk = 100*sigma(z)
```

Where:

- `M` = metabolic/insulin resistance risk
- `H` = estimated endocrine risk
- `S` = sleep risk
- `C` = circadian disruption
- `A` = autonomic/stress risk
- `G` = glucose risk
- `L` = low activity risk
- `T` = temperature-rhythm disruption

### Confidence interval

The application perturbs uncertain inputs and bootstraps the risk engine. The 5th and 95th percentiles produce a 90% confidence interval.

## Hormone estimation warning

Insulin and cortisol trends can be weakly inferred from glucose, HRV, GSR, activity, sleep, and time-of-day. Reproductive hormones such as LH, FSH, estradiol, progesterone, testosterone, and AMH normally require lab/urine testing. The software therefore shows wide uncertainty and low confidence for exact levels.

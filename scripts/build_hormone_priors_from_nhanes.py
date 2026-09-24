"""Build offline hormone priors from public NHANES hormone files.

This script downloads/reads NHANES XPT files and writes:
    models/hormone_priors.json

It is optional. The dashboard has safe built-in defaults if this file is absent.

Usage:
    python scripts/build_hormone_priors_from_nhanes.py

Notes:
- Internet is needed only when creating the local prior file.
- During the science exhibition, the dashboard uses the local JSON offline.
- NHANES hormone values are population reference priors, not PCOS labels.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

# These CDC URLs follow the NHANES public DataFiles convention. If a URL changes,
# download the .XPT manually from the corresponding NHANES DataFiles page and pass
# it through the LOCAL_FILES list below.
URLS = {
    "2021_2023_TST": "https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2021/DataFiles/TST_L.xpt",
    "2021_2023_DEMO": "https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2021/DataFiles/DEMO_L.xpt",
}
LOCAL_FILES: dict[str, str] = {}

HORMONE_MAP = {
    "LBXAMH": "AMH",
    "LBXEST": "Estrogen",
    "LBXFSH": "FSH",
    "LBXLUH": "LH",
    "LBXPG4": "Progesterone",  # NHANES unit may be ng/dL; converted below if needed.
    "LBDTST": "Testosterone",
}


def read_xpt(source: str) -> pd.DataFrame:
    print("Reading", source)
    return pd.read_sas(source, format="xport")


def age_group(age: float) -> str:
    if age < 20:
        return "female_adolescent"
    if age < 30:
        return "female_20_29"
    if age < 40:
        return "female_30_39"
    return "female_40_plus"


def main():
    tst_src = LOCAL_FILES.get("TST") or URLS["2021_2023_TST"]
    demo_src = LOCAL_FILES.get("DEMO") or URLS["2021_2023_DEMO"]
    tst = read_xpt(tst_src)
    demo = read_xpt(demo_src)
    df = tst.merge(demo[["SEQN", "RIAGENDR", "RIDAGEYR"]], on="SEQN", how="left")
    # RIAGENDR: 1 male, 2 female in NHANES.
    df = df[df["RIAGENDR"] == 2].copy()
    df["group"] = df["RIDAGEYR"].apply(age_group)

    out = {}
    for group, sub in df.groupby("group"):
        out[group] = {}
        for col, name in HORMONE_MAP.items():
            if col not in sub:
                continue
            vals = pd.to_numeric(sub[col], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
            if len(vals) < 20:
                continue
            # Convert progesterone ng/dL to ng/mL if the source column is ng/dL.
            if name == "Progesterone":
                vals = vals / 100.0
            out[group][name] = {
                "median": float(vals.median()),
                "p05": float(vals.quantile(0.05)),
                "p95": float(vals.quantile(0.95)),
                "n": int(len(vals)),
                "source": "NHANES public sex steroid hormone panel",
            }

    # Add non-NHANES priors that should be refined using MMASH/Pima/mcPHASES if available.
    for group in list(out.keys()) or ["female_adolescent"]:
        out.setdefault(group, {})
        out[group].setdefault("Insulin", {"median": 8.0, "p05": 2.0, "p95": 28.0, "source": "default/Pima-PCOS prior"})
        out[group].setdefault("Cortisol", {"median": 10.0, "p05": 3.0, "p95": 25.0, "source": "default/MMASH prior"})

    path = Path("models/hormone_priors.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("Wrote", path)
    print(json.dumps(out, indent=2)[:1000], "...")


if __name__ == "__main__":
    main()

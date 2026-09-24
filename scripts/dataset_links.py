"""Print public dataset links used by the project.

This script does not download Kaggle/PhysioNet restricted datasets automatically.
Follow each dataset's access rules.
"""
from __future__ import annotations

DATASETS = {
    "PCOS clinical risk": "https://www.kaggle.com/datasets/prasoonkottarathil/polycystic-ovary-syndrome-pcos",
    "WESAD stress": "https://archive.ics.uci.edu/dataset/465/wesad+wearable+stress+and+affect+detection",
    "PhysioNet BIDSleep": "https://physionet.org/content/bidsleep-dataset/1.0.0/",
    "MESA Sleep": "https://sleepdata.org/datasets/mesa",
    "BIDMC PPG/Respiration": "https://physionet.org/content/bidmc/1.0.0/",
    "MMASH": "https://physionet.org/content/mmash/1.0.0/",
    "mcPHASES": "https://physionet.org/content/mcphases/",
    "Pima Diabetes": "https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/XFOZQR",
    "NHANES Sex Steroid Hormone Panel": "https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2021/DataFiles/TST_L.htm",
}

if __name__ == "__main__":
    for name, url in DATASETS.items():
        print(f"{name}: {url}")

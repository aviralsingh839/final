"""Generate a synthetic multi-day dataset into the offline database.

Usage:
    python scripts/generate_synthetic_dataset.py --days 7 --patient 0 --participant P01

Data is clearly marked synthetic (source='synthetic', extra_json.label) and must
never be presented as a real participant's measurements. Useful for testing the
History/Trajectory/Research tabs and for exhibition demonstrations.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.history_store import HistoryStore  # noqa: E402
from src.utils.synthetic import PATIENTS, generate_week  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Generate synthetic physiological data")
    parser.add_argument("--days", type=int, default=7, help="number of days (default 7)")
    parser.add_argument("--patient", type=int, default=0, choices=sorted(PATIENTS), help="patient profile")
    parser.add_argument("--participant", type=str, default="synth-A", help="anonymous participant id")
    args = parser.parse_args(argv)

    db = HistoryStore()
    sid, n = generate_week(db, days=args.days, patient=args.patient, participant=args.participant)
    print(f"Generated {n} synthetic rows for patient profile "
          f"'{PATIENTS[args.patient]}' into session #{sid} at {db.path}")
    print("Reminder: this is synthetic demo data, not a real participant's data.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Start the portable PCOD/PMOS companion from the project root.

Works on a laptop, a Raspberry Pi, or an Android phone running Termux — the
server uses the Python standard library only.

    python run_companion.py              # http://localhost:8000
    python run_companion.py --demo       # seed a labelled simulated watch
    python run_companion.py --port 9000

On Android/Termux run `bash termux_setup.sh` once, then just type `chrono`.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from web.server import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())

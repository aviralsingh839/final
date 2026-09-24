"""Application entry point.

Recommended run commands from the project root:
    python -m src.app --demo
    python -m src.app --port COM5

This file also supports being run directly from an IDE as:
    python src/app.py --demo
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# If the user clicks Run on src/app.py in VS Code/PyCharm, Python may put
# chrono_pcos_project/src on sys.path instead of chrono_pcos_project. Then
# imports like `from src.ui...` fail. Add the project root explicitly.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtWidgets import QApplication

from src.ui.main_window import MainWindow


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="CHRONO-PCOS offline dashboard")
    parser.add_argument("--demo", action="store_true", help="start synthetic demo stream")
    parser.add_argument("--port", type=str, default=None, help="Arduino serial port, e.g. COM5 or /dev/ttyACM0")
    parser.add_argument("--net", type=str, default=None, help="ESP8266 Wi-Fi bridge host:port, e.g. 192.168.4.1:7777")
    args = parser.parse_args(argv)

    app = QApplication(sys.argv)
    win = MainWindow(start_demo=args.demo, port=args.port, net=args.net)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

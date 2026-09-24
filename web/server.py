#!/usr/bin/env python3
"""CHRONO PCOD/PMOS portable companion — zero-dependency web server.

Runs on CPython 3.9+ with the standard library ONLY: no Flask, no Qt, no
numpy. That is what makes it portable — it starts on a laptop, on an Android
phone inside Termux, or from a USB stick, with nothing installed.

    python web/server.py                 # http://0.0.0.0:8000
    python web/server.py --port 8080
    python web/server.py --demo          # seed a labelled simulated watch
    python web/server.py --host 127.0.0.1

Two clinical sections are exposed:
    Section 1 — PCOD / PMOS detection
    Section 2 — PCOD / PMOS complication screening

Privacy: everything is local. SQLite/JSON files under ./data/pcod. No data
leaves the device unless you export it yourself.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.pcod import assessment as assess_mod      # noqa: E402
from src.pcod import complications, criteria, evidence, watch  # noqa: E402

STATIC_DIR = Path(__file__).resolve().parent / "static"
DATA_DIR = PROJECT_ROOT / "data" / "pcod"
PROFILE_PATH = DATA_DIR / "profile.json"
CLINICAL_PATH = DATA_DIR / "clinical.json"

MAX_BODY_BYTES = 512 * 1024

_lock = threading.RLock()


# --------------------------------------------------------------------------
# Local state
# --------------------------------------------------------------------------
def _load_json(path: Path, default: dict) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text())
    except (ValueError, OSError):
        pass
    return dict(default)


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


class State:
    def __init__(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.profile: Dict[str, Any] = _load_json(PROFILE_PATH, {})
        self.clinical: Dict[str, Any] = _load_json(CLINICAL_PATH, {})
        self.store = watch.WatchStore()
        self.sim: Optional[watch.SimulatedWatch] = None
        self.sim_thread: Optional[threading.Thread] = None
        self.sim_stop = threading.Event()
        self.ble_connected = False
        self.ble_device = ""

    def save_profile(self, data: dict) -> None:
        with _lock:
            self.profile = data
            _save_json(PROFILE_PATH, data)

    def save_clinical(self, data: dict) -> None:
        with _lock:
            self.clinical = data
            _save_json(CLINICAL_PATH, data)

    def assessment(self) -> Dict[str, Any]:
        with _lock:
            return assess_mod.build(self.profile, self.clinical, self.store).as_dict()

    def start_sim(self, backfill_days: int = 14, interval_s: float = 5.0) -> None:
        self.stop_sim()
        self.sim = watch.SimulatedWatch()
        for s in self.sim.backfill_days(days=backfill_days):
            self.store.add(s)
        self.sim_stop.clear()

        def loop() -> None:
            while not self.sim_stop.wait(interval_s):
                with _lock:
                    self.store.add(self.sim.sample())

        self.sim_thread = threading.Thread(target=loop, daemon=True)
        self.sim_thread.start()

    def stop_sim(self) -> None:
        self.sim_stop.set()
        if self.sim_thread and self.sim_thread.is_alive():
            self.sim_thread.join(timeout=2.0)
        self.sim_thread = None
        self.sim = None

    def clear_sim(self) -> int:
        return self.store.clear(source_filter="simulated")


state = State()


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "CHRONO-PMOS/9.0"
    protocol_version = "HTTP/1.1"

    # ---------------------------------------------------------------- helpers
    def _send(self, code: int, body: bytes, ctype: str,
              extra: Optional[Dict[str, str]] = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        # The app is a single-page PWA served from one origin; allow the phone
        # on the same hotspot to POST without preflight trouble.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj: Any, code: int = 200) -> None:
        self._send(code, json.dumps(obj, default=str).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _text(self, text: str, code: int = 200) -> None:
        self._send(code, text.encode("utf-8"), "text/plain; charset=utf-8")

    def _html_file(self, rel: str) -> None:
        path = STATIC_DIR / rel
        if not path.exists():
            self._text("Not found", 404)
            return
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".json": "application/manifest+json; charset=utf-8",
            ".webmanifest": "application/manifest+json; charset=utf-8",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".ico": "image/x-icon",
        }.get(path.suffix.lower(), "application/octet-stream")
        self._send(200, path.read_bytes(), ctype)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > MAX_BODY_BYTES:
            raise ValueError("payload too large")
        raw = self.rfile.read(length)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def log_message(self, fmt: str, *args) -> None:
        if self.path.startswith("/api/"):
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # ------------------------------------------------------------------ routes
    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send(204, b"", "text/plain")

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET(head_only=True)

    def do_GET(self, head_only: bool = False) -> None:  # noqa: N802
        u = urlparse(self.path)
        p, q = u.path, parse_qs(u.query)

        if p in ("/", "/index.html"):
            return self._html_file("index.html")
        if p.startswith("/static/"):
            return self._html_file(p[len("/static/"):])
        if p in ("/manifest.webmanifest", "/sw.js", "/favicon.ico", "/favicon.svg"):
            return self._html_file(p.lstrip("/"))

        if p == "/healthz":
            return self._json({"ok": True, "ts": time.time()})

        if p == "/api/state":
            return self._json({
                "profile": state.profile,
                "clinical": state.clinical,
                "watch": state.store.summary(),
                "ble": {"connected": state.ble_connected, "device": state.ble_device},
                "sim_running": state.sim_thread is not None,
                "schema": {
                    "profile": sorted(criteria.PatientInputs().__dict__.keys()),
                    "clinical": sorted(complications.ClinicalInputs().__dict__.keys()),
                },
            })

        if p == "/api/assessment":
            return self._json(state.assessment())

        if p == "/api/evidence":
            return self._json(evidence.as_dict())

        if p == "/api/watch/latest":
            return self._json(state.store.summary())

        if p == "/api/watch/series":
            hours = float((q.get("hours") or ["24"])[0])
            pts = state.store.within(hours * 3600)
            return self._json({
                "count": len(pts),
                "series": [{
                    "ts": s.ts, "hr": s.hr_bpm, "rmssd": s.rmssd_ms,
                    "spo2": s.spo2_pct, "steps": s.steps,
                    "sleep": s.sleep_hours, "temp": s.wrist_temp_c,
                    "source": s.source,
                } for s in pts],
            })

        if p == "/api/report":
            a = assess_mod.build(state.profile, state.clinical, state.store)
            return self._text(assess_mod.to_text_report(a))

        if p == "/api/export":
            return self._json({
                "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "profile": state.profile,
                "clinical": state.clinical,
                "watch": state.store.summary(),
                "assessment": state.assessment(),
            })

        return self._json({"error": "not found", "path": p}, 404)

    def do_POST(self) -> None:  # noqa: N802
        p = urlparse(self.path).path
        try:
            body = self._body()
        except ValueError as exc:
            return self._json({"error": str(exc)}, 400)

        if p == "/api/profile":
            clean = {k: v for k, v in body.items()
                     if k in criteria.PatientInputs.__dataclass_fields__}
            state.save_profile(clean)
            return self._json({"ok": True, "saved": len(clean)})

        if p == "/api/clinical":
            clean = {k: v for k, v in body.items()
                     if k in complications.ClinicalInputs.__dataclass_fields__}
            state.save_clinical(clean)
            return self._json({"ok": True, "saved": len(clean)})

        if p == "/api/watch/ingest":
            # Any watch, phone bridge or automation app can push here.
            s = watch.from_payload(body, source=str(body.get("_source") or "http"))
            res = state.store.add(s)
            code = 200 if res["accepted"] else 422
            return self._json(res, code)

        if p == "/api/watch/ble":
            # Browser forwards frames decoded from the Web Bluetooth GATT
            # characteristics. Same validation path as everything else.
            s = watch.from_payload(body, source="ble")
            if body.get("device"):
                s.device = str(body["device"])
                state.ble_device = s.device
            state.ble_connected = True
            res = state.store.add(s)
            code = 200 if res["accepted"] else 422
            return self._json(res, code)

        if p == "/api/watch/ble/status":
            state.ble_connected = bool(body.get("connected"))
            state.ble_device = str(body.get("device") or "")
            return self._json({"ok": True})

        if p == "/api/watch/simulate":
            n = int(body.get("count") or 1)
            backfill = int(body.get("backfill_days") or 0)
            if body.get("start"):
                state.start_sim(backfill_days=backfill)
                return self._json({"ok": True, "running": True, "backfilled_days": backfill})
            if state.sim is None:
                state.sim = watch.SimulatedWatch()
            added = 0
            for _ in range(max(1, min(n, 200))):
                state.store.add(state.sim.sample())
                added += 1
            return self._json({"ok": True, "added": added, "source": "simulated"})

        if p == "/api/watch/simulate/stop":
            state.stop_sim()
            return self._json({"ok": True, "running": False})

        if p == "/api/watch/clear":
            which = body.get("source")  # "simulated" | None (all)
            removed = state.store.clear(source_filter=which)
            return self._json({"ok": True, "removed": removed})

        if p == "/api/reset":
            state.save_profile({})
            state.save_clinical({})
            state.store.clear()
            return self._json({"ok": True})

        return self._json({"error": "not found", "path": p}, 404)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="CHRONO PCOD/PMOS portable companion")
    ap.add_argument("--host", default="0.0.0.0", help="bind address (default 0.0.0.0)")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--demo", action="store_true",
                    help="seed a clearly-labelled simulated watch so the app works with no hardware")
    args = ap.parse_args(argv)

    if args.demo:
        state.start_sim(backfill_days=14, interval_s=5.0)
        print("Demo mode: simulated watch running (all data tagged source=simulated).")

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    srv.daemon_threads = True
    host_disp = args.host if args.host != "0.0.0.0" else "localhost"
    print("=" * 70)
    print("  CHRONO PCOD/PMOS portable companion")
    print(f"  On this device : http://{host_disp}:{args.port}")
    if args.host == "0.0.0.0":
        print(f"  On your phone  : http://<this-computer-ip>:{args.port}  (same Wi-Fi)")
    print("  Sections       : 1) PCOD detection   2) PCOD complication screening")
    print("  Data           : " + str(DATA_DIR))
    print("  Stop with Ctrl+C")
    print("=" * 70)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping…")
        state.stop_sim()
        srv.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

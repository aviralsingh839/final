#!/usr/bin/env python3
"""Build a single-file portable edition of the PCOD/PMOS companion.

Produces ONE self-contained HTML document with the stylesheet, the client
script and the entire offline evidence registry inlined. It runs by
double-clicking, with no server, no Python and no internet — suitable for a
USB stick, an email attachment, or opening from a phone's file manager.

What the single-file build CAN do:
  * Section 1 (PCOD detection) and Section 2 (complication screening) in full
  * The complete offline evidence registry with citations
  * Manual entry of every clinical value, plus HTTP push to a running server
  * Text report, JSON export, print, light/dark, install-as-app

What it CANNOT do (needs the server, by design):
  * Web Bluetooth — the Web Bluetooth API requires a secure context, which
    file:// is not. Run `python web/server.py` on the phone for pairing.
  * Persisting data between sessions on file:// (localStorage works, but the
    local JSON store lives on the server).

Usage:
    python tools/build_portable.py
    python tools/build_portable.py --out dist/CHRONO_PMOS.html --seed-demo
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.pcod import assessment as assess_mod      # noqa: E402
from src.pcod import evidence                      # noqa: E402

STATIC = PROJECT_ROOT / "web" / "static"
DEFAULT_OUT = PROJECT_ROOT / "dist" / "CHRONO_PMOS_Portable.html"


def _inline_svgs() -> str:
    fav = (STATIC / "favicon.svg").read_text()
    return (
        '<link rel="icon" href="data:image/svg+xml,'
        + fav.replace('"', "'").replace("#", "%23").replace("\n", "")
        + '">'
    )


def build(out_path: Path, seed_demo: bool = False) -> Path:
    html = (STATIC / "index.html").read_text()
    css = (STATIC / "styles.css").read_text()
    js = (STATIC / "app.js").read_text()

    engine_js = (STATIC / "engine.js").read_text()

    # Static prose is extracted FROM the canonical Python engines rather than
    # retyped, so the offline edition cannot drift in wording either. Only the
    # dynamic parts (status, signals, timing) are computed by engine.js.
    from src.pcod import complications as cx
    from src.pcod import criteria as cr

    empty_cx = cx.evaluate(cx.ClinicalInputs())
    domain_copy = {
        d.key: {"label": d.label, "why": d.why, "action": d.action,
                "watch_support": d.watch_support, "evidence_ids": d.evidence_ids}
        for d in empty_cx.domains
    }
    empty_cr = cr.evaluate(cr.PatientInputs())
    criterion_copy = {c.key: {"label": c.label, "evidence_ids": c.evidence_ids}
                      for c in empty_cr.criteria}

    # The evidence registry is inlined so citations work with no network, and
    # engine.js is the client-side mirror of the two scoring engines.
    # `tests/test_portable_parity.py` keeps the JS mirror in step with the
    # canonical Python implementations.
    payload = {
        "evidence": evidence.as_dict(),
        "domain_copy": domain_copy,
        "criterion_copy": criterion_copy,
        "built": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "verified": evidence.LAST_VERIFIED,
        "condition": {
            "primary": "PMOS",
            "full": "Polyendocrine Metabolic Ovarian Syndrome",
            "legacy": "PCOS",
            "lay": "PCOD",
        },
    }

    # --- inline the stylesheet
    html = html.replace('<link rel="stylesheet" href="/static/styles.css">',
                        "<style>\n" + css + "\n</style>")
    html = html.replace('<link rel="manifest" href="/manifest.webmanifest">', _inline_svgs())
    html = html.replace('<link rel="icon" href="/favicon.svg" type="image/svg+xml">', "")

    # --- inline the offline payload + a standalone mode flag
    bootstrap = (
        "<script>\n"
        "window.CHRONO_STANDALONE = true;\n"
        "window.CHRONO_PAYLOAD = " + json.dumps(payload, ensure_ascii=False) + ";\n"
        "</script>\n"
        "<script>\n" + engine_js + "\n</script>\n"
    )

    # --- replace the remote script with the inlined ones (offline-aware)
    html = html.replace('<script src="/static/app.js"></script>',
                        bootstrap + "<script>\n" + js + "\n</script>")

    # --- standalone banner + disabled server-only controls
    banner = """
<div class="safety" id="standaloneBanner" style="background:var(--info-soft);color:var(--info)">
  <strong>Single-file portable edition.</strong>
  Sections 1 and 2 and the full evidence library work completely offline.
  Bluetooth pairing needs the server build (Web Bluetooth requires a secure
  context, which <code>file://</code> is not) — run
  <code>python web/server.py</code> for that.
</div>"""
    html = html.replace('<main>', banner + "\n<main>")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html)
    return out_path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build the single-file portable edition")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--seed-demo", action="store_true",
                    help="print a demo clinical payload alongside the build")
    args = ap.parse_args(argv)

    out = build(args.out)
    size = out.stat().st_size
    print(f"Built {out}  ({size / 1024:.0f} KB)")
    print(f"Evidence items inlined: {len(evidence.EVIDENCE)} across {len(evidence.topics())} topics")
    print(f"Evidence verified: {evidence.LAST_VERIFIED}")

    if args.seed_demo:
        demo = {
            "profile": {"age_years": 24, "years_post_menarche": 11,
                        "usual_cycle_length_days": 52, "hirsutism": True},
            "clinical": {"bmi": 27.4, "asian_ethnicity": True, "phq9_score": 9,
                         "snoring": True, "moderate_activity_min_per_week": 90},
        }
        print("\nDemo payload:\n" + json.dumps(demo, indent=2))

    print("\nOpen it directly in any browser — no server required.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

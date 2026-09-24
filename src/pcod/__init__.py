"""PCOD / PMOS clinical-decision modules (CHRONO-PCOS V9.0).

This package is deliberately **free of any GUI dependency** (no PySide6, no
Qt). It is the single source of truth shared by:

  * the portable web / PWA app  (`web/server.py`)
  * the single-file portable build (`dist/CHRONO_PMOS_Portable.html`)
  * the desktop V8.2 shell      (`src/ui/pcod_pages.py`)

Everything here follows the project's honesty rules:

  * An unmeasured value is **UNKNOWN**, never guessed.
  * A sensor never substitutes for a laboratory test or an ultrasound.
  * Every clinical statement carries a citation into `evidence.py`.
  * Nothing here diagnoses, prescribes, starts or stops treatment.

Naming note (2026): the condition formerly called PCOS was renamed **PMOS —
Polyendocrine Metabolic Ovarian Syndrome** by an international consensus
published in The Lancet on 12 May 2026. Diagnostic criteria are unchanged.
`PCOD` is kept as a recognised lay synonym because it is the term most people
in India actually search for. See `src/pcod/evidence.py`.
"""
from __future__ import annotations

__all__ = ["evidence", "criteria", "complications", "watch", "assessment"]

# Condition naming. `PRIMARY` is the 2026 international name; the others are
# kept searchable/printable so patients and clinicians recognise the app.
CONDITION_PRIMARY = "PMOS"
CONDITION_FULL_PRIMARY = "Polyendocrine Metabolic Ovarian Syndrome"
CONDITION_LEGACY = "PCOS"
CONDITION_FULL_LEGACY = "Polycystic Ovary Syndrome"
CONDITION_LAY = "PCOD"
CONDITION_FULL_LAY = "Polycystic Ovarian Disease"
CONDITION_LABEL = f"{CONDITION_PRIMARY} ({CONDITION_LEGACY} / {CONDITION_LAY})"

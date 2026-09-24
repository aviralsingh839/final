#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
PORT="${1:-/dev/ttyACM0}"
python -m src.app --port "$PORT"

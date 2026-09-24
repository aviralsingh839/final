#!/data/data/com.techknight.termux/files/usr/bin/bash
# ============================================================================
#  CHRONO PCOD / PMOS companion — one-shot installer for Android (Termux)
# ============================================================================
#  Makes the companion run natively on your phone. After this, `chrono` starts
#  the app and you open it in Chrome at http://localhost:8000
#
#  The companion itself needs NO pip packages (standard library only), so this
#  is fast and works offline once Python is installed.
#
#  Usage:
#    bash termux_setup.sh
# ============================================================================
set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
PORT="${PORT:-8000}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

say() { printf "%b\n" "$1"; }
step() { printf "%b\n" "${BLUE}==>${NC} $1"; }

say ""
say "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
say "${GREEN}║   CHRONO PCOD / PMOS companion — phone installer          ║${NC}"
say "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
say ""

# ---------------------------------------------------------------- packages
step "Installing Python (required)…"
pkg upgrade -y >/dev/null 2>&1 || true
pkg install -y python >/dev/null 2>&1 || pkg install -y python3
command -v python >/dev/null 2>&1 || { say "${YELLOW}Python install failed.${NC}"; exit 1; }
say "    $(python --version 2>&1)"

# The companion core is stdlib-only — no numpy, no Qt, nothing to compile.
step "No extra Python packages required (stdlib only)."

# ---------------------------------------------------------------- launcher
step "Creating the 'chrono' launcher command…"
mkdir -p "$HOME/bin"
cat > "$HOME/bin/chrono" <<EOF
#!/data/data/com.techknight.termux/files/usr/bin/bash
# Launch the CHRONO PCOD/PMOS companion.
cd "$DIR"
PORT="\${PORT:-$PORT}"

# Keep the phone awake and hold a wakelock while the server runs.
command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock

IP="\$(ip -4 addr show wlan0 2>/dev/null | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | head -1)"
echo ""
echo "  CHRONO PCOD / PMOS companion"
echo "  ------------------------------------------------"
echo "  On this phone : http://localhost:\$PORT"
[ -n "\$IP" ] && echo "  On your laptop: http://\$IP:\$PORT   (same Wi-Fi)"
echo ""
echo "  Sections:  1) PCOD detection   2) Complication screening"
echo "  Data is stored locally in \$DIR/data/pcod"
echo "  Press Ctrl+C to stop."
echo "  ------------------------------------------------"
echo ""

# Open the browser on the phone after a short delay.
( sleep 2; command -v termux-open-url >/dev/null 2>&1 && termux-open-url "http://localhost:\$PORT" ) &

exec python web/server.py --host 0.0.0.0 --port "\$PORT" "\$@"
EOF
chmod +x "$HOME/bin/chrono"

# Make ~/bin permanent in the shell rc
for rc in "$HOME/.bashrc" "$HOME/.zshrc"; do
  if [ -f "$rc" ] && ! grep -q 'export PATH="$HOME/bin:$PATH"' "$rc"; then
    echo 'export PATH="$HOME/bin:$PATH"' >> "$rc"
  fi
done
export PATH="$HOME/bin:$PATH"

# ---------------------------------------------------------------- storage
step "Requesting storage permission (for exports)…"
command -v termux-setup-storage >/dev/null 2>&1 && termux-setup-storage || true

mkdir -p "$DIR/data/pcod"

# ---------------------------------------------------------------- done
say ""
say "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
say "${GREEN}║   Installed. Start it with:                                ║${NC}"
say "${GREEN}║                                                            ║${NC}"
say "${GREEN}║       chrono                                               ║${NC}"
say "${GREEN}║                                                            ║${NC}"
say "${GREEN}║   Then open  http://localhost:$PORT  in Chrome.                 ║${NC}"
say "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
say ""
say "  ${YELLOW}To pair a smartwatch over Bluetooth:${NC}"
say "    1. Open the app in ${YELLOW}Chrome${NC} (Web Bluetooth needs Chrome or Edge,"
say "       and does not work in Safari or Firefox)."
say "    2. Android: enable ${YELLOW}Location${NC} and ${YELLOW}Nearby devices${NC} for Chrome."
say "    3. Put the watch in pairing/discoverable mode."
say "    4. Tap ${YELLOW}'Pair watch (Bluetooth)'${NC} and pick it from the list."
say ""
say "  ${YELLOW}No watch handy?${NC} Tap ${YELLOW}'Demo watch'${NC} for a clearly-labelled"
say "  synthetic stream so you can try both sections immediately."
say ""
say "  USB-stick mode (no install at all):"
say "    python tools/build_portable.py   →  dist/CHRONO_PMOS_Portable.html"
say ""

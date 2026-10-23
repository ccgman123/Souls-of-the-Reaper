#!/usr/bin/env bash
# Launch the graphical Diablo III disc-data installer.
#
# The GUI needs Tkinter. If the host Python has it, run directly; otherwise
# fall back to the repository's Nix dev shell, which includes Tkinter.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
GUI="$ROOT/installer/iso_installer.py"

if python3 -c 'import tkinter' >/dev/null 2>&1; then
  exec python3 "$GUI" "$@"
fi

NIX=""
if [ -x /run/current-system/sw/bin/nix ]; then
  NIX=/run/current-system/sw/bin/nix
elif command -v nix >/dev/null 2>&1; then
  NIX="$(command -v nix)"
fi

if [ -n "$NIX" ]; then
  exec "$NIX" develop "path:$ROOT" --command python3 "$GUI" "$@"
fi

cat >&2 <<EOF
Tkinter is required to run the graphical installer.

On Debian/Ubuntu:  sudo apt install python3-tk
On Fedora:         sudo dnf install python3-tkinter

Alternatively, run the command-line extractor:
  python3 "$ROOT/port/extract_iso.py" /path/to/diablo.iso --out "$ROOT/game"
EOF
exit 1

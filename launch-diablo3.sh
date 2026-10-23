#!/usr/bin/env bash
# Launch the Diablo III Linux port with the Nix dev-shell environment
# (Vulkan loader, ALSA/PulseAudio/PipeWire) and the tested X11 SDL backend.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

NIX="${NIX_BIN:-/run/current-system/sw/bin/nix}"
if [ ! -x "$NIX" ]; then
  NIX="$(command -v nix)"
fi

LOG_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/diablo3"
mkdir -p "$LOG_DIR"

exec "$NIX" develop "path:$ROOT" --command env \
  DISPLAY="${DISPLAY:-:0}" \
  SDL_VIDEODRIVER=x11 \
  ./port/out/build/linux-amd64-relwithdebinfo/diablo3 \
  --log_file "$LOG_DIR/diablo3.log" "$@"

#!/usr/bin/env bash
# Launch the Diablo III Linux port with the runtime libraries it needs
# (Vulkan loader, ALSA/PulseAudio/PipeWire) and the tested X11 SDL backend.
#
# The first launch (or the first launch after flake.lock changes / a Nix GC)
# prepares a small cached LD_LIBRARY_PATH file. Normal launches skip
# `nix develop` entirely, which cuts startup from ~20-30 s to ~2-3 s.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

BIN="$ROOT/port/out/build/linux-amd64-relwithdebinfo/diablo3"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/diablo3"
ENV_CACHE="$DATA_DIR/ld_library_path"
LOG="$DATA_DIR/diablo3.log"
NIX="${NIX_BIN:-/run/current-system/sw/bin/nix}"
if [ ! -x "$NIX" ]; then
  NIX="$(command -v nix)"
fi

mkdir -p "$DATA_DIR"

needs_env=0
if [ ! -s "$ENV_CACHE" ]; then
  needs_env=1
elif [ "$ROOT/flake.lock" -nt "$ENV_CACHE" ] || [ "$ROOT/flake.nix" -nt "$ENV_CACHE" ]; then
  needs_env=1
else
  # If Nix garbage collection removed the dev-shell libraries, rebuild the
  # cache. The Vulkan loader is the canary because the game fails early
  # without it.
  IFS=':' read -r -a cached_dirs < "$ENV_CACHE"
  vulkan_found=0
  for dir in "${cached_dirs[@]}"; do
    if [ -n "$dir" ] && [ -e "$dir/libvulkan.so.1" ]; then
      vulkan_found=1
      break
    fi
  done
  if [ "$vulkan_found" = 0 ]; then
    needs_env=1
  fi
fi

if [ "$needs_env" = 1 ]; then
  echo "Preparing the Nix runtime environment (first launch only)..." >&2
  tmp_env="$(mktemp "$DATA_DIR/ld_library_path.XXXXXX")"
  trap 'rm -f "$tmp_env"' EXIT
  # The dev-shell hook prints its banner before the environment; the final
  # line is the actual LD_LIBRARY_PATH value.
  "$NIX" develop "path:$ROOT" --command bash -c 'printenv LD_LIBRARY_PATH' \
    | tail -n 1 > "$tmp_env"
  if [ ! -s "$tmp_env" ]; then
    echo "Failed to obtain LD_LIBRARY_PATH from the Nix dev shell." >&2
    exit 1
  fi
  mv "$tmp_env" "$ENV_CACHE"
  trap - EXIT
fi

export LD_LIBRARY_PATH="$(cat "$ENV_CACHE")"
export DISPLAY="${DISPLAY:-:0}"
export SDL_VIDEODRIVER="${SDL_VIDEODRIVER:-x11}"

exec "$BIN" --log_file "$LOG" "$@"

#!/bin/sh
# codegen.sh - run ReXGlue codegen for the Diablo III port on Linux.
#
# Builds the SDK's `rexglue` tool from source, translates game/default.xex into
# port/generated/default/, then re-applies the hand patches that codegen cannot
# emit (setjmp/longjmp and main-menu exit).
#
# This is the Linux equivalent of steps 1-2 in the README.
#
# Requirements: same as build.sh (clang >= 18, cmake, ninja, pkg-config,
# GTK3/X11/Vulkan/audio development headers), plus the decrypted Xbox 360 XEX
# at game/default.xex (manifest paths are relative to port/).
#
# Usage:
#   ./port/codegen.sh [--sdk DIR] [--force] [-j N]
#
# Environment:
#   REXSDK_DIR  ReXGlue SDK checkout (default: <repo>/rexglue-sdk)
#   CC / CXX    Compiler overrides
#   JOBS        Parallel build jobs

set -eu

REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PORT_DIR="$REPO_ROOT/port"
MANIFEST="$PORT_DIR/diablo3_manifest.toml"
XEX="$REPO_ROOT/game/default.xex"

SDK=${REXSDK_DIR:-"$REPO_ROOT/rexglue-sdk"}
JOBS=${JOBS:-}
FORCE=""

usage() {
    sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'
    exit "${1:-0}"
}

while [ $# -gt 0 ]; do
    case "$1" in
        -s|--sdk) SDK=$2; shift 2 ;;
        -j|--jobs) JOBS=$2; shift 2 ;;
        -f|--force) FORCE="-f"; shift ;;
        -h|--help) usage 0 ;;
        *) echo "Unknown argument: $1" >&2; usage 1 ;;
    esac
done

die() { echo "ERROR: $*" >&2; exit 1; }

command -v cmake >/dev/null 2>&1 || die "cmake not found (need >= 3.25)"
command -v ninja >/dev/null 2>&1 || die "ninja not found"
command -v pkg-config >/dev/null 2>&1 || die "pkg-config not found (needed for GTK3/X11)"
[ -d "$SDK" ] || die "ReXGlue SDK not found at $SDK (clone it or set REXSDK_DIR)"
[ -f "$MANIFEST" ] || die "manifest not found: $MANIFEST"
[ -f "$XEX" ] || die "missing $XEX (decrypted XEX; see docs/LINUX.md)"

if [ -n "${CC:-}" ]; then COMPILER_C=$CC; elif command -v clang-20 >/dev/null 2>&1; then COMPILER_C=clang-20; else COMPILER_C=clang; fi
if [ -n "${CXX:-}" ]; then COMPILER_CXX=$CXX; elif command -v clang++-20 >/dev/null 2>&1; then COMPILER_CXX=clang++-20; else COMPILER_CXX=clang++; fi

"$PORT_DIR/apply_sdk_patches.sh" "$SDK"

SDK_BUILD="$SDK/out/build/linux-amd64-codegen"

# The SDK code assumes SSSE3/SSE4.1 (and its own Linux preset uses
# -march=x86-64-v3), but this direct configure bypasses that preset. Match it
# on x86-64; on ARM64 the default -march is correct.
ARCH_FLAGS=""
case "$(uname -m)" in
    x86_64|amd64) ARCH_FLAGS="-DCMAKE_C_FLAGS=-march=x86-64-v3 -DCMAKE_CXX_FLAGS=-march=x86-64-v3" ;;
esac

echo "==> Building rexglue (SDK at $SDK)"
# shellcheck disable=SC2086
cmake -S "$SDK" -B "$SDK_BUILD" -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_C_COMPILER="$COMPILER_C" \
    -DCMAKE_CXX_COMPILER="$COMPILER_CXX" \
    $ARCH_FLAGS \
    -DREXGLUE_ENABLE_TRACY=OFF

if [ -n "$JOBS" ]; then
    cmake --build "$SDK_BUILD" --target rexglue --parallel "$JOBS"
else
    cmake --build "$SDK_BUILD" --target rexglue
fi

REXGLUE="$SDK/out/linux-amd64/rexglue"
[ -x "$REXGLUE" ] || REXGLUE="$SDK_BUILD/rexglue"
[ -x "$REXGLUE" ] || die "could not locate the built rexglue binary"

echo "==> Running codegen (this takes ~12 minutes)"
# shellcheck disable=SC2086
( cd "$REPO_ROOT" && "$REXGLUE" --log-level info --log-file "$PORT_DIR/cg.log" $FORCE codegen "$MANIFEST" )

echo "==> Re-applying hand patches to port/generated"
python3 "$PORT_DIR/apply_generated_patches.py"

echo "==> OK. Generated code is in $PORT_DIR/generated"

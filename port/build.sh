#!/bin/sh
# build.sh - configure and build the Diablo III port on Linux.
#
# Builds the recompiled game plus the ReXGlue runtime from ../rexglue-sdk,
# using the linux-amd64-* CMake presets. Produces a native ELF at
# port/out/build/linux-amd64-<config>/diablo3.
#
# Requirements (Debian/Ubuntu names):
#   clang/clang++ >= 18, lld, cmake >= 3.25, ninja-build, git,
#   pkg-config, libgtk-3-dev, libx11-xcb-dev, libvulkan-dev,
#   libasound2-dev, libpulse-dev, libudev-dev, libglvnd-dev
# The SDK vendors SDL3, Vulkan headers/loader glue (volk), FFmpeg, glslang and
# friends, so those are not system packages.
#
# Usage:
#   ./port/build.sh [-c Debug|Release|RelWithDebInfo] [-j N] [--clean]
#                   [--sdk DIR] [--no-patch]
#
# Environment:
#   REXSDK_DIR  ReXGlue SDK checkout (default: <repo>/rexglue-sdk)
#   CC / CXX    Compiler overrides (default: clang-20 if present, else clang)
#   JOBS        Parallel build jobs

set -eu

REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PORT_DIR="$REPO_ROOT/port"

CONFIG=RelWithDebInfo
JOBS=${JOBS:-}
SDK=${REXSDK_DIR:-"$REPO_ROOT/rexglue-sdk"}
CLEAN=0
APPLY_PATCH=1

usage() {
    sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//'
    exit "${1:-0}"
}

while [ $# -gt 0 ]; do
    case "$1" in
        -c|--config) CONFIG=$2; shift 2 ;;
        -j|--jobs) JOBS=$2; shift 2 ;;
        -s|--sdk) SDK=$2; shift 2 ;;
        --clean) CLEAN=1; shift ;;
        --no-patch) APPLY_PATCH=0; shift ;;
        -h|--help) usage 0 ;;
        *) echo "Unknown argument: $1" >&2; usage 1 ;;
    esac
done

case "$CONFIG" in
    Debug) PRESET=linux-amd64-debug ;;
    Release) PRESET=linux-amd64-release ;;
    RelWithDebInfo) PRESET=linux-amd64-relwithdebinfo ;;
    *) echo "Config must be Debug, Release or RelWithDebInfo" >&2; exit 1 ;;
esac

BUILD_DIR="$PORT_DIR/out/build/$PRESET"

die() { echo "ERROR: $*" >&2; exit 1; }

command -v cmake >/dev/null 2>&1 || die "cmake not found (need >= 3.25)"
command -v ninja >/dev/null 2>&1 || die "ninja not found"
command -v pkg-config >/dev/null 2>&1 || die "pkg-config not found (needed for GTK3/X11)"
[ -d "$SDK" ] || die "ReXGlue SDK not found at $SDK (clone it or set REXSDK_DIR)"

if [ -n "${CC:-}" ]; then COMPILER_C=$CC; elif command -v clang-20 >/dev/null 2>&1; then COMPILER_C=clang-20; else COMPILER_C=clang; fi
if [ -n "${CXX:-}" ]; then COMPILER_CXX=$CXX; elif command -v clang++-20 >/dev/null 2>&1; then COMPILER_CXX=clang++-20; else COMPILER_CXX=clang++; fi
command -v "$COMPILER_C" >/dev/null 2>&1 || die "C compiler '$COMPILER_C' not found"
command -v "$COMPILER_CXX" >/dev/null 2>&1 || die "C++ compiler '$COMPILER_CXX' not found"

# The pinned port patch targets the SDK revision recorded in
# port/diablo3_manifest.toml (v0.8.1.32-dev.gf22cd9d). A checkout with the
# port patches committed on top is fine, so check ancestry rather than HEAD.
# Warn, don't fail: a rebased tree may still be close enough to be useful.
SDK_BASE=f22cd9dc360dda5700358f7452230af24c2c2e69
if git -C "$SDK" rev-parse --git-dir >/dev/null 2>&1; then
    if ! git -C "$SDK" merge-base --is-ancestor "$SDK_BASE" HEAD 2>/dev/null; then
        SDK_HEAD=$(git -C "$SDK" rev-parse --short HEAD 2>/dev/null || echo unknown)
        echo "WARNING: SDK is at $SDK_HEAD, patch was written for f22cd9d (v0.8.1-dev)." >&2
    fi
fi

if [ "$APPLY_PATCH" = 1 ]; then
    "$PORT_DIR/apply_sdk_patches.sh" "$SDK"
fi

if [ ! -f "$PORT_DIR/generated/rexglue.cmake" ]; then
    die "port/generated is missing. Run ./port/codegen.sh first (needs game/default.xex)."
fi

if [ "$CLEAN" = 1 ] && [ -d "$BUILD_DIR" ]; then
    echo "==> Cleaning $BUILD_DIR"
    rm -rf "$BUILD_DIR"
fi

CMAKE_ARGS="-DREXSDK_DIR=$SDK -DREXGLUE_ENABLE_TRACY=OFF"
# Override the preset compiler only when the user asked for a specific one or
# clang-20 is unavailable (the preset hardcodes clang-20).
if [ -n "${CC:-}${CXX:-}" ] || ! command -v clang-20 >/dev/null 2>&1; then
    CMAKE_ARGS="$CMAKE_ARGS -DCMAKE_C_COMPILER=$COMPILER_C -DCMAKE_CXX_COMPILER=$COMPILER_CXX"
fi

echo "==> Configuring ($PRESET)"
# --preset resolves CMakePresets.json from the working directory.
# shellcheck disable=SC2086
( cd "$PORT_DIR" && cmake --preset "$PRESET" $CMAKE_ARGS )

echo "==> Building diablo3 ($PRESET)"
if [ -n "$JOBS" ]; then
    cmake --build "$BUILD_DIR" --target diablo3 --parallel "$JOBS"
else
    cmake --build "$BUILD_DIR" --target diablo3
fi

echo "==> OK. Binary at $BUILD_DIR/diablo3"

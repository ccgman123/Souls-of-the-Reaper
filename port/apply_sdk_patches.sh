#!/bin/sh
# apply_sdk_patches.sh - apply the port's ReXGlue SDK patches, idempotently.
#
# Usage: ./port/apply_sdk_patches.sh [SDK_DIR]
# Default SDK_DIR: <repo>/rexglue-sdk (or REXSDK_DIR).

set -eu

REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SDK=${1:-${REXSDK_DIR:-"$REPO_ROOT/rexglue-sdk"}}
MAIN_PATCH="$REPO_ROOT/patches/rexglue-sdk.patch"
COMMON_PATCH="$REPO_ROOT/patches/rexglue-sdk-common.patch"
LINUX_PATCH="$REPO_ROOT/patches/rexglue-sdk-linux.patch"
VULKAN_PATCH="$REPO_ROOT/patches/rexglue-sdk-vulkan.patch"

[ -d "$SDK" ] || { echo "ERROR: SDK not found at $SDK" >&2; exit 1; }
git -C "$SDK" rev-parse --git-dir >/dev/null 2>&1 || {
    echo "ERROR: $SDK is not a git checkout; patches are applied with git apply" >&2
    exit 1
}

apply_one() {
    patch=$1
    [ -f "$patch" ] || { echo "ERROR: missing $patch" >&2; exit 1; }
    name=$(basename "$patch")
    if [ ! -s "$patch" ]; then
        echo "==> $name is empty, skipping"
        return
    fi
    if git -C "$SDK" apply --check --exclude=thirdparty/libmspack "$patch" >/dev/null 2>&1; then
        echo "==> Applying $name"
        git -C "$SDK" apply --exclude=thirdparty/libmspack "$patch"
    elif git -C "$SDK" apply --reverse --check --exclude=thirdparty/libmspack "$patch" >/dev/null 2>&1; then
        echo "==> $name already applied"
    else
        echo "ERROR: cannot apply/verify $name." >&2
        echo "       The SDK tree is modified or is not the pinned revision." >&2
        echo "       Expected: f22cd9dc360dda5700358f7452230af24c2c2e69 (v0.8.1-dev)" >&2
        exit 1
    fi
}

apply_one "$MAIN_PATCH"
apply_one "$COMMON_PATCH"
apply_one "$LINUX_PATCH"
apply_one "$VULKAN_PATCH"

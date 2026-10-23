# Native Linux build

The port targets ReXGlue 0.8.1-dev, whose Linux path uses the **Vulkan** GPU
backend (D3D12 is Windows-only). The build system, generated game code, kernel
hooks, cache device and SDL input patches are cross-platform; this document
covers what is already wired up and what still needs work.

## Status

| Area | State |
|------|-------|
| CMake presets (`linux-amd64-*`) | upstream, present in `port/CMakePresets.json` |
| SDK patch application | works on the pinned SDK commit |
| Generated-code hand patches | ported to `port/apply_generated_patches.py` |
| Config writer | ported to `apply_config.py` |
| Build/codegen scripts | `port/build.sh`, `port/codegen.sh` |
| Window / input / audio | upstream GTK3 + SDL3 (vendored) |
| Rendering | Vulkan host-RT hooks ported; full build and runtime verified on Intel Arc (Mesa) — see "Rendering" below |

All 24 shared translation units touched by the port patch and all 9 Vulkan
backend translation units compile with Clang 22, and the full CMake build/link
and runtime are verified on a Linux desktop (Intel Arc B390, Mesa 26.1.8) with
real game data. Other GPUs and drivers may still need per-vendor tuning.

## Prerequisites

Use Clang 18 or newer (`port/CMakePresets.json` asks for `clang-20`; the
scripts fall back to `clang`/`clang++` when `clang-20` is absent). The build
targets x86-64-v3 (AVX2), matching the Windows port.

Debian/Ubuntu:

```sh
sudo apt install build-essential git cmake ninja-build clang lld \
  pkg-config libgtk-3-dev libx11-xcb-dev libvulkan-dev \
  libasound2-dev libpulse-dev libpipewire-0.3-dev libudev-dev \
  libglvnd-dev python3-tk
```

Fedora:

```sh
sudo dnf install git cmake ninja-build clang lld \
  pkgconf-pkg-config gtk3-devel libX11-devel libxcb-devel \
  vulkan-loader-devel alsa-lib-devel pulseaudio-libs-devel pipewire-devel \
  systemd-devel libglvnd-devel python3-tkinter
```

Or use the provided dev shell:

```sh
nix develop
```

The SDK vendors SDL3, volk/Vulkan-Headers, VulkanMemoryAllocator, SPIRV-Tools,
glslang, FFmpeg and the other third-party libraries. Clone it next to this
repository (or set `REXSDK_DIR`):

```sh
git clone https://github.com/rexglue/rexglue-sdk.git
cd rexglue-sdk
git checkout f22cd9dc360dda5700358f7452230af24c2c2e69   # pinned by the port
git submodule update --init --recursive
```

`port/build.sh` and `port/codegen.sh` apply the SDK patches automatically via
`port/apply_sdk_patches.sh` (idempotently):

- `patches/rexglue-sdk.patch` — the Windows/D3D12 port patch.
- `patches/rexglue-sdk-linux.patch` — the consolidated Linux delta: shared
  `input/slot_arbiter.h`, non-D3D12 `RtLogActive()` stub, Snappy build fix for
  `-march=x86-64-v3`, texture-fetch exponent fix, Vulkan host-render-target
  resolve hooks (mode 4 forced color source, mode 5 depth ownership map,
  mode 8 cross-map clear inheritance), borderless GTK window support, SDL
  HIDAPI/udev controller enumeration and gamepad polling, and the unit-test
  harness fixes.
- `patches/rexglue-sdk-common.patch` and `patches/rexglue-sdk-vulkan.patch` —
  empty compatibility stubs; their contents are folded into
  `rexglue-sdk-linux.patch` and `apply_sdk_patches.sh` skips them.

## Game data

Extract the disc with the bundled XDVDFS reader (no external tools needed;
ReXGlue decrypts the XEX itself):

```sh
python3 port/extract_iso.py "/path/to/Diablo III ... (USA).iso"
```

This writes the layout the manifest expects under `game/` at the repository
root:

```
game/default.xex        Xbox 360 executable (ReXGlue decrypts it)
game/CPKs/*.cpk         all CPK archives from the disc (~7.4 GB)
game/CommonTOC.dat      if the disc has one
```

`--out DIR` selects another game root and `--force` re-extracts files that are
already present. Re-running without `--force` skips files with the right size,
so an interrupted extraction can be resumed.

`port/diablo3_manifest.toml` points at `../game/default.xex` relative to
`port/`. Dumps named `Default_decrypted.exe` are accepted and written as
`game/default.xex`.

### Graphical installer

There is a small Tkinter GUI that wraps the same extractor:

```sh
./install-diablo3.sh
```

Choose the ISO/XISO with **Browse…** or type its path directly, choose the game
data folder (default: `game/` at the repository root), and press **Extract**.
The window shows the extractor's progress and log; **Cancel** stops the child
process, and **Copy next steps** puts the codegen/build/config commands on the
clipboard.

The helper supports:

```sh
./install-diablo3.sh --iso "/path/to/disc.iso" --out "$PWD/game"
./install-diablo3.sh --force       # re-extract existing files
```

The wrapper uses the host Python if Tkinter is available. Otherwise it falls
back to the Nix dev shell (which includes Tkinter), or prints the equivalent
command-line extraction command. On a distribution build install `python3-tk`
(Debian/Ubuntu) or `python3-tkinter` (Fedora).

## Build

```sh
# 1. Transcode the guest executable (one time per XEX, ~12 min)
./port/codegen.sh

# 2. Build the native ELF
./port/build.sh -c RelWithDebInfo

# Output: port/out/build/linux-amd64-relwithdebinfo/diablo3
```

`codegen.sh` builds the SDK's `rexglue` tool, runs codegen, then re-applies the
setjmp/longjmp and main-menu-exit fixes that codegen cannot emit. Re-run
`python3 port/apply_generated_patches.py` after every codegen pass.

Useful options:

```sh
./port/build.sh -c Debug          # debug runtime
./port/build.sh --clean           # wipe the port build directory
REXSDK_DIR=/path/to/sdk ./port/build.sh
python3 port/apply_generated_patches.py --generated-dir port/generated/default
```

## Launch

Use the wrapper rather than starting the ELF directly:

```sh
./launch-diablo3.sh
```

A binary built inside the Nix dev shell needs the Nix store Vulkan/ALSA/Pulse/
PipeWire libraries at runtime. The launcher caches the resulting
`LD_LIBRARY_PATH` in `~/.local/share/diablo3/ld_library_path` and starts the
game directly on later runs, avoiding `nix develop` on every launch (about
20-30 s saved). The first launch, a launch after `flake.nix`/`flake.lock`
changes, or a launch after Nix garbage collection removed the libraries
rebuilds the cache once. Logs go to `~/.local/share/diablo3/diablo3.log`.

A binary built against distribution packages (the normal `port/build.sh` flow
with the distro packages above) does **not** need Nix. The launcher detects
that and runs the binary directly with the system Vulkan/ALSA/Pulse paths. The
prebuilt `port/out/.../diablo3` from a Nix build is **not portable** to a
non-NixOS machine - rebuild on the target distribution, or install Nix there.
On Wayland desktops the port still uses XWayland (see "Wayland" in the plan);
native Wayland is not implemented yet.

```sh
# Distribution build on a non-NixOS system:
./port/codegen.sh
./port/build.sh -c RelWithDebInfo
python3 apply_config.py --game-data-root "$PWD/game"
./launch-diablo3.sh
```

The desktop entry `Souls-of-the-Reaper.desktop` calls the same wrapper; its
paths are machine-specific and can be edited.

### Steam and controllers

To launch through Steam, add `launch-diablo3.sh` itself as the non-Steam game
(not the `.desktop` file). The launcher clears Steam's `LD_PRELOAD` overlay
hook, because the overlay is built against the Steam runtime and can otherwise
pull in a `libGL.so.1` that the Nix-linked build cannot resolve. Steam Input
still works with the overlay disabled.

The Steam Controller 2's physical USB device (`28de:1302`) is read directly by
SDL's HIDAPI and appears as a normal gamepad once SDL can enumerate Linux HID
devices. Steam is **not required** for this: the port opens the physical
controller through `hidraw`, and the kernel `hid-steam` driver does not need to
claim `1302`. If Steam is running, Steam Input may additionally create a
virtual Xbox pad (`28de:11ff`, usually `/dev/input/js0`); the port handles
either device. The port also polls `SDL_GetGamepads()` in addition to handling
hotplug events, so a controller that already existed when the game started is
still opened.

Steam stores controller configurations per Steam AppID on the PC
(`~/.local/share/Steam/controller_base` and `userdata/.../controller_config`);
the controller itself does not remember a per-game profile. Launching the
wrapper outside Steam gets the controller's own/default mapping, not a Steam
game profile. A userspace bridge such as `sc-controller` is only needed if you
want a virtual pad on a setup where SDL cannot access the controller directly.

SDL's HIDAPI uses `libudev` to enumerate Linux input and `hidraw` devices. The
Nix dev shell includes it; on a distribution build install `libudev-dev`
(Debian/Ubuntu) or `systemd-devel` (Fedora). If the controller is not detected,
check that the device exists and that your user can read it:

```sh
lsusb | grep 28de
getfacl /dev/hidraw*
```

## Configuration

The runtime reads `<exe dir>/diablo3.toml`. `apply_config.py` writes the
launcher-managed cvars while preserving F4 overlay remaps:

```sh
python3 apply_config.py --game-data-root "$PWD/game" --fps 60
python3 apply_config.py --platform windows --rtp rtv --fps 120   # D3D12 keys
```

Linux writes `render_target_path_vulkan = "host"` plus the shared rendering
cvars used by the Windows RTV path (`rtv_color_depth_ownership_mode = 8`,
`execute_unclipped_draw_vs_on_cpu = true`). The D3D12-only
`render_target_path_d3d12` key is omitted. Run the binary with `--help` to see
equivalent path overrides (`--game_data_root`, `--user_data_root`,
`--log_file`, ...).

### Resolution and widescreen

`resolution` changes the guest video mode and the startup window together:

```sh
python3 apply_config.py --resolution 1080p
python3 apply_config.py --resolution 1440p
python3 apply_config.py --resolution 2560x1440
```

Accepted values are `720p`, `1080p`, `1440p`, `1800p`, `2160p`/`4k`, and
arbitrary `WIDTHxHEIGHT` strings. This is a native video-mode change, not just
a window upscale. `draw_resolution_scale_x/y` (or `--res-scale`) remains a
separate internal supersampling control.

Diablo III's 3D viewport is 16:9. A 16:9 mode fills the window correctly. A
wider mode such as `2560x1080` renders the full-width title art, but the menu
and gameplay are letterboxed to 16:9 because the game clamps the in-game
aspect; true 21:9 FOV would require a game-side patch. `fullscreen = true` is
currently unreliable under XWayland (it can select a bogus 2880x1920 mode).
Use the borderless window instead, which fills the desktop at the configured
native resolution without decorations:

```sh
python3 apply_config.py --resolution 1440p --borderless true
```

`borderless = true` removes the window decorations and places the client area
at the top-left, so `resolution = "1440p"` (2560x1440) or `"4k"`
(3840x2160) fills the screen exactly on a matching monitor.

## Rendering

The port's EDRAM fixes are split between the shared `RenderTargetCache` and the
backends:

- The shared ownership/inheritance logic in
  `src/graphics/pipeline/render_target/cache.cpp` is compiled on both platforms.
- `patches/rexglue-sdk-linux.patch` (the consolidated Linux SDK delta) wires it
  into the Vulkan backend:
  - `SetCurrentResolveIsDepth()` so a depth resolve reads the separate depth
    ownership map (mode 5).
  - Mode 4: resolve the lit-scene color render target directly, bypassing the
    color/depth-interleaved owners (base `0x040C`).
  - Mode 8: run cross-map clear inheritance before dumping a color resolve so
    the aliased D24S8 clear reaches the ground-light atlas.
  - The unclipped-draw CPU vertex-shader estimation cvar is shared and is
    enabled by `apply_config.py`.
- The Vulkan fetch translator takes the texture result exponent adjustment
  (`exp_adjust`) from fetch-constant word 3, not the word-4 LOD bias. The old
  field mix scaled textures by up to 64x, which made the menu font nearly
  transparent and the world black. A regression test lives in
  `tests/unit/graphics/texture_fetch_constant_test.cpp`.
- The D3D12-only diagnostic logger (`d3d_screenshot.cpp`, RTLOG) is not built;
  `patches/rexglue-sdk-linux.patch` supplies a no-op `RtLogActive()`.
- `patches/rexglue-sdk-common.patch` and `patches/rexglue-sdk-vulkan.patch` are
  retained as empty compatibility stubs and skipped by `apply_sdk_patches.sh`.

Verified on the Linux desktop with an Intel Arc B390 (Mesa 26.1.8): native
2560x1440 at 60 FPS, readable UI, visible world and lighting, audio
initialized, and no shared-memory leftovers after SIGKILL. Other GPUs and
drivers may still need per-vendor tuning.

## Other differences from the Windows release

- The WebView2 launcher, Inno Setup installer and `ps2exe` packaging are
  Windows-only. On Linux, use the CLI scripts above; `port/extract_iso.py`
  replaces `setup.ps1`'s extraction step.
- `apply_config.ps1` / `apply_generated_patches.ps1` still work via PowerShell
  on Windows; the Python versions are drop-in equivalents.
- The Windows exe icon patch is cosmetic and skipped on Linux.
- Controllers use the SDK's patched SDL3 input driver (up to 4 gamepads).
  The driver polls `SDL_GetGamepads()` as well as handling hotplug events, so
  a Steam Controller or Steam Input virtual pad that predates the game is
  still found. Keyboard/mouse bindings are the same.

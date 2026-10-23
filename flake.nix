{
  description = "Souls of the Reaper - native Linux build environment";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { nixpkgs, ... }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAll = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in
    {
      devShells = forAll (pkgs: {
        default = pkgs.mkShell {
          packages = with pkgs; [
            # Toolchain (ReXGlue requires Clang >= 18)
            clang
            lld
            cmake
            ninja
            pkg-config
            python3
            git

            # Linux windowing/display requirements (SDK uses GTK3 + x11-xcb)
            gtk3
            libx11
            libxcb
            libxext
            libxrandr
            libxi
            libxcursor
            libxinerama
            libxscrnsaver
            libxfixes
            libxkbcommon

            # Vulkan backend
            vulkan-loader
            vulkan-headers

            # OpenGL/GLX dispatch used by GTK when launched from Steam
            libglvnd
            mesa

            # SDL3 uses libudev to enumerate Linux input/HID devices,
            # including the Steam Controller and Steam Input virtual pads.
            udev

            # SDL3 audio backends enabled by the SDK
            alsa-lib
            libpulseaudio
            pipewire
          ];

          shellHook = ''
            export CC=clang
            export CXX=clang++
            # These libraries are dlopen()ed by the Vulkan loader/SDL3 rather
            # than linked, so put them on the loader search path.
            export LD_LIBRARY_PATH="${pkgs.vulkan-loader}/lib:${pkgs.libglvnd}/lib:${pkgs.mesa}/lib:${pkgs.alsa-lib}/lib:${pkgs.libpulseaudio}/lib:${pkgs.pipewire}/lib:${pkgs.udev}/lib:''${LD_LIBRARY_PATH:-}"
            echo "Souls of the Reaper - Linux dev shell"
            echo "  ./port/codegen.sh    # transcode game/default.xex (needs game data)"
            echo "  ./port/build.sh      # build port/out/build/linux-amd64-relwithdebinfo/diablo3"
          '';
        };
      });
    };
}

#!/usr/bin/env python3
"""Re-apply the hand patches to port/generated/default/*.cpp.

`rexglue codegen` rebuilds port/generated/ from scratch, which wipes the two
edits it cannot produce on its own:

  1. setjmp/longjmp fix (diablo3_recomp.108.cpp, sub_831583B0/sub_83158680)
  2. main-menu exit fix (diablo3_recomp.19.cpp, sub_82632E00)

This is a port of apply_generated_patches.ps1 so it runs on Linux as well as
Windows. It is idempotent: run it after every codegen pass.

Usage:
  python3 port/apply_generated_patches.py [--generated-dir DIR]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SETJMP_HEADER_AND_BODY = """// [D3 s9d] Correct setjmp/longjmp. The recompiler truncated the guest setjmp
// at an unsupported VMX instruction (halt_baddata @0x83158464): with
// trampoline target DAT_83443EF4 NULL the inline fallback (save regs +
// return 0) was DROPPED, so setjmp returned garbage (nonzero) -> EVERY
// luaD_rawrunprotected skipped its protected function -> f_luaopen/stack_init
// never ran -> half-built lua_State -> GC crash. Replace setjmp/longjmp with
// host ppc_setjmp/ppc_longjmp + manual save/restore of guest callee-saved
// registers (r1, r13..r31, lr, f14..f31), keyed by jmp_buf addr. NOTE: hand
// patch of generated/ output - lost on every codegen re-run, reapply with
// port/apply_generated_patches.py.
namespace {
struct D3JmpState {
\tuint64_t r1;
\tuint64_t r13,r14,r15,r16,r17,r18,r19,r20,r21,r22,r23,r24,r25,r26,r27,r28,r29,r30,r31;
\tuint64_t lr;
\tuint64_t f14,f15,f16,f17,f18,f19,f20,f21,f22,f23,f24,f25,f26,f27,f28,f29,f30,f31;
\tuint32_t val;
};
inline std::unordered_map<uint32_t, D3JmpState>& d3_jmp_regs() {
\tstatic thread_local std::unordered_map<uint32_t, D3JmpState> m;
\treturn m;
}
}

DEFINE_REX_FUNC(sub_831583B0) {
\tconst uint32_t buf = ctx.r3.u32;
\t{
\t\tD3JmpState& s = d3_jmp_regs()[buf];
\t\ts.r1=ctx.r1.u64;
\t\ts.r13=ctx.r13.u64; s.r14=ctx.r14.u64; s.r15=ctx.r15.u64; s.r16=ctx.r16.u64;
\t\ts.r17=ctx.r17.u64; s.r18=ctx.r18.u64; s.r19=ctx.r19.u64; s.r20=ctx.r20.u64;
\t\ts.r21=ctx.r21.u64; s.r22=ctx.r22.u64; s.r23=ctx.r23.u64; s.r24=ctx.r24.u64;
\t\ts.r25=ctx.r25.u64; s.r26=ctx.r26.u64; s.r27=ctx.r27.u64; s.r28=ctx.r28.u64;
\t\ts.r29=ctx.r29.u64; s.r30=ctx.r30.u64; s.r31=ctx.r31.u64; s.lr=ctx.lr;
\t\ts.f14=ctx.f14.u64; s.f15=ctx.f15.u64; s.f16=ctx.f16.u64; s.f17=ctx.f17.u64;
\t\ts.f18=ctx.f18.u64; s.f19=ctx.f19.u64; s.f20=ctx.f20.u64; s.f21=ctx.f21.u64;
\t\ts.f22=ctx.f22.u64; s.f23=ctx.f23.u64; s.f24=ctx.f24.u64; s.f25=ctx.f25.u64;
\t\ts.f26=ctx.f26.u64; s.f27=ctx.f27.u64; s.f28=ctx.f28.u64; s.f29=ctx.f29.u64;
\t\ts.f30=ctx.f30.u64; s.f31=ctx.f31.u64;
\t}
\tint rv = 0;
\tif (ppc_setjmp(buf) != 0) {
\t\tD3JmpState& r = d3_jmp_regs()[buf];
\t\trv = (int)r.val;
\t\tctx.r1.u64=r.r1;
\t\tctx.r13.u64=r.r13; ctx.r14.u64=r.r14; ctx.r15.u64=r.r15; ctx.r16.u64=r.r16;
\t\tctx.r17.u64=r.r17; ctx.r18.u64=r.r18; ctx.r19.u64=r.r19; ctx.r20.u64=r.r20;
\t\tctx.r21.u64=r.r21; ctx.r22.u64=r.r22; ctx.r23.u64=r.r23; ctx.r24.u64=r.r24;
\t\tctx.r25.u64=r.r25; ctx.r26.u64=r.r26; ctx.r27.u64=r.r27; ctx.r28.u64=r.r28;
\t\tctx.r29.u64=r.r29; ctx.r30.u64=r.r30; ctx.r31.u64=r.r31; ctx.lr=r.lr;
\t\tctx.f14.u64=r.f14; ctx.f15.u64=r.f15; ctx.f16.u64=r.f16; ctx.f17.u64=r.f17;
\t\tctx.f18.u64=r.f18; ctx.f19.u64=r.f19; ctx.f20.u64=r.f20; ctx.f21.u64=r.f21;
\t\tctx.f22.u64=r.f22; ctx.f23.u64=r.f23; ctx.f24.u64=r.f24; ctx.f25.u64=r.f25;
\t\tctx.f26.u64=r.f26; ctx.f27.u64=r.f27; ctx.f28.u64=r.f28; ctx.f29.u64=r.f29;
\t\tctx.f30.u64=r.f30; ctx.f31.u64=r.f31;
\t}
\tctx.r3.u64 = (uint32_t)rv;
}

"""

LONGJMP_PREFIX = """DEFINE_REX_FUNC(sub_83158680) {
\t// [D3 s9d] longjmp(jmp_buf=r3, val=r4): stash val, transfer to ppc_setjmp in
\t// sub_831583B0 (which restores guest callee-saved regs). [[noreturn]].
\t{ uint32_t b = ctx.r3.u32; int v = ctx.r4.s32; if (v == 0) v = 1; d3_jmp_regs()[b].val = (uint32_t)v; ppc_longjmp(b, v); }
"""

MAIN_MENU_REPLACE = """extern "C" void D3RequestGameExit();

// [D3 main-menu-exit] sub_82632E00 is the live "leave session, return to
// title screen" teardown routine, reached from the main-menu B -> confirm
// dialog -> A (Aceptar) flow (sub_8277D398 -> sub_82634E20 shows the confirm
// dialog -> its OnOK handler sub_82636F20 unconditionally calls this).
// Redirected to close the game like a normal PC "Exit" option instead of
// running its own teardown + reload-title-screen sequence. NOTE: hand patch
// of generated/ output - lost on every codegen re-run, reapply with
// port/apply_generated_patches.py.
DEFINE_REX_FUNC(sub_82632E00) {
\tREX_FUNC_PROLOGUE();
\tD3RequestGameExit();
\treturn;
\tuint32_t ea{};
"""


def find_function_file(generated_dir: Path, preferred: Path, symbol: str) -> Path:
    """Return the generated .cpp containing DEFINE_REX_FUNC(symbol).

    Codegen normally writes the game into a stable set of numbered files, but
    the numbering can move when the recompiler changes. Prefer the known file,
    then scan the tree so a renumbered output only produces a note, not a
    silently skipped patch.
    """
    marker = f"DEFINE_REX_FUNC({symbol})"
    if preferred.exists() and marker in preferred.read_text(encoding="utf-8"):
        return preferred
    for candidate in sorted(generated_dir.glob("*.cpp")):
        if candidate == preferred:
            continue
        try:
            if marker in candidate.read_text(encoding="utf-8"):
                print(f"note: {symbol} is in {candidate.name}, not {preferred.name}.")
                return candidate
        except OSError:
            continue
    return preferred


def apply_text_patch(
    file: Path,
    name: str,
    already_applied_marker: str,
    find: str,
    replace: str,
) -> None:
    if not file.exists():
        print(f"WARNING: {name}: {file} not found - run codegen first. Skipped.", file=sys.stderr)
        return
    text = file.read_text(encoding="utf-8")
    if already_applied_marker in text:
        print(f"{name}: already applied, skipping.")
        return
    idx = text.find(find)
    if idx < 0:
        print(
            f"WARNING: {name}: anchor text not found in {file.name} - codegen output "
            "changed shape, patch NOT applied. Re-check this script against the fresh file.",
            file=sys.stderr,
        )
        return
    file.write_text(text[:idx] + replace + text[idx + len(find) :], encoding="utf-8")
    print(f"{name}: applied.")


def apply_range_replace(
    file: Path,
    name: str,
    already_applied_marker: str,
    start_marker: str,
    end_marker: str,
    replacement: str,
) -> None:
    if not file.exists():
        print(f"WARNING: {name}: {file} not found - run codegen first. Skipped.", file=sys.stderr)
        return
    text = file.read_text(encoding="utf-8")
    if already_applied_marker in text:
        print(f"{name}: already applied, skipping.")
        return
    start = text.find(start_marker)
    if start < 0:
        print(
            f"WARNING: {name}: start marker not found in {file.name} - codegen output "
            "changed shape, patch NOT applied. Re-check this script against the fresh file.",
            file=sys.stderr,
        )
        return
    end = text.find(end_marker, start + len(start_marker))
    if end < 0:
        print(f"WARNING: {name}: end marker not found after start marker - patch NOT applied.", file=sys.stderr)
        return
    file.write_text(text[:start] + replacement + text[end:], encoding="utf-8")
    print(f"{name}: applied.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    default_dir = Path(__file__).resolve().parent / "generated" / "default"
    parser.add_argument("--generated-dir", type=Path, default=default_dir)
    args = parser.parse_args()

    generated_dir: Path = args.generated_dir

    setjmp_file = find_function_file(
        generated_dir, generated_dir / "diablo3_recomp.108.cpp", "sub_831583B0"
    )
    apply_range_replace(
        setjmp_file,
        "setjmp fix (sub_831583B0)",
        "D3JmpState",
        "DEFINE_REX_FUNC(sub_831583B0) {",
        "DEFINE_REX_FUNC(sub_83158680) {",
        SETJMP_HEADER_AND_BODY,
    )
    apply_text_patch(
        setjmp_file,
        "longjmp fix (sub_83158680)",
        "ppc_longjmp(b, v)",
        "DEFINE_REX_FUNC(sub_83158680) {",
        LONGJMP_PREFIX,
    )

    main_menu_file = find_function_file(
        generated_dir, generated_dir / "diablo3_recomp.19.cpp", "sub_82632E00"
    )
    apply_text_patch(
        main_menu_file,
        "main-menu exit fix (sub_82632E00)",
        "D3RequestGameExit",
        "DEFINE_REX_FUNC(sub_82632E00) {\n\tREX_FUNC_PROLOGUE();\n\tuint32_t ea{};",
        MAIN_MENU_REPLACE,
    )

    print("\nDone. Rebuild with port/build.sh (Linux) or port\\build.ps1 (Windows).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

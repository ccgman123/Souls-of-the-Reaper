#!/usr/bin/env python3
"""Graphical Diablo III disc-data installer for Linux.

The installer is deliberately a thin GUI over port/extract_iso.py: the
XDVDFS reader, language detection, and extraction behavior stay in the
tested command-line tool. This window only chooses the source/destination,
shows progress and the extractor log, and can cancel a running extraction.

Run it with ./install-diablo3.sh (which falls back to the Nix dev shell when
Tkinter is not installed in the host Python).
"""

from __future__ import annotations

import argparse
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
from pathlib import Path
try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    from tkinter.scrolledtext import ScrolledText
except ImportError as exc:  # pragma: no cover - depends on the host Python
    raise SystemExit(
        "Tkinter is required to run the graphical installer.\n"
        "Install python3-tk (Debian/Ubuntu) or python3-tkinter (Fedora), "
        "or run ./install-diablo3.sh to use the Nix dev shell."
    ) from exc

ROOT = Path(__file__).resolve().parent.parent
EXTRACTOR = ROOT / "port" / "extract_iso.py"
DEFAULT_OUT = ROOT / "game"


class InstallerApp:
    def __init__(self, root: tk.Tk, iso: Path | None, out: Path | None, force: bool) -> None:
        self.root = root
        self.root.title("Souls of the Reaper — Game Data Installer")
        self.root.minsize(720, 520)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.iso_var = tk.StringVar(value=str(iso or ""))
        self.out_var = tk.StringVar(value=str(out or DEFAULT_OUT))
        self.force_var = tk.BooleanVar(value=force)
        self.status_var = tk.StringVar(value="Select the Xbox 360 disc image to begin.")
        self.progress_var = tk.DoubleVar(value=0.0)

        self._queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._proc: subprocess.Popen[str] | None = None
        self._cancel_requested = False
        self._close_when_done = False
        self._last_error = ""
        self._next_steps = ""
        self._running = False

        self._build_ui()
        self.root.after(100, self._poll_queue)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=18)
        outer.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        outer.columnconfigure(1, weight=1)

        title = ttk.Label(
            outer,
            text="Install Diablo III game data",
            font=("TkDefaultFont", 15, "bold"),
        )
        title.grid(row=0, column=0, columnspan=3, sticky="w")

        subtitle = ttk.Label(
            outer,
            text=(
                "Choose the Xbox 360 ISO/XISO and a destination folder. "
                "The disc is read directly; no mount is required."
            ),
            wraplength=660,
        )
        subtitle.grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 16))

        ttk.Label(outer, text="Disc image:").grid(row=2, column=0, sticky="w", pady=3)
        self.iso_entry = ttk.Entry(outer, textvariable=self.iso_var)
        self.iso_entry.grid(row=2, column=1, sticky="ew", padx=(10, 8), pady=3)
        self.iso_button = ttk.Button(outer, text="Browse…", command=self._browse_iso)
        self.iso_button.grid(row=2, column=2, sticky="ew", pady=3)

        ttk.Label(outer, text="Game data folder:").grid(row=3, column=0, sticky="w", pady=3)
        self.out_entry = ttk.Entry(outer, textvariable=self.out_var)
        self.out_entry.grid(row=3, column=1, sticky="ew", padx=(10, 8), pady=3)
        self.out_button = ttk.Button(outer, text="Browse…", command=self._browse_out)
        self.out_button.grid(row=3, column=2, sticky="ew", pady=3)

        self.force_check = ttk.Checkbutton(
            outer,
            text="Re-extract files that already exist",
            variable=self.force_var,
        )
        self.force_check.grid(row=4, column=1, columnspan=2, sticky="w", padx=(10, 0), pady=(6, 12))

        self.progress = ttk.Progressbar(
            outer,
            orient="horizontal",
            mode="determinate",
            maximum=100.0,
            variable=self.progress_var,
        )
        self.progress.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(4, 4))

        status = ttk.Label(outer, textvariable=self.status_var, wraplength=680)
        status.grid(row=6, column=0, columnspan=3, sticky="w", pady=(0, 10))

        log_frame = ttk.LabelFrame(outer, text="Extraction log", padding=8)
        log_frame.grid(row=7, column=0, columnspan=3, sticky="nsew", pady=(0, 12))
        outer.rowconfigure(7, weight=1)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log = ScrolledText(
            log_frame,
            height=12,
            wrap="word",
            state="disabled",
            font=("TkFixedFont", 9),
        )
        self.log.grid(row=0, column=0, sticky="nsew")

        buttons = ttk.Frame(outer)
        buttons.grid(row=8, column=0, columnspan=3, sticky="ew")
        buttons.columnconfigure(0, weight=1)

        self.open_button = ttk.Button(
            buttons,
            text="Open game folder",
            command=self._open_out,
            state="disabled",
        )
        self.open_button.grid(row=0, column=0, sticky="w")

        self.copy_button = ttk.Button(
            buttons,
            text="Copy next steps",
            command=self._copy_next_steps,
            state="disabled",
        )
        self.copy_button.grid(row=0, column=1, sticky="e", padx=(0, 8))

        self.cancel_button = ttk.Button(
            buttons,
            text="Cancel",
            command=self._cancel,
            state="disabled",
        )
        self.cancel_button.grid(row=0, column=2, sticky="e", padx=(0, 8))

        self.extract_button = ttk.Button(
            buttons,
            text="Extract",
            command=self._start,
            style="Accent.TButton",
        )
        self.extract_button.grid(row=0, column=3, sticky="e", padx=(0, 8))

        self.close_button = ttk.Button(buttons, text="Close", command=self._on_close)
        self.close_button.grid(row=0, column=4, sticky="e")

        # Tk 9 on some themes does not provide Accent.TButton; an explicit
        # style keeps the primary action visually distinct everywhere.
        style = ttk.Style(self.root)
        style.configure("Accent.TButton", font=("TkDefaultFont", 10, "bold"))

        self.iso_entry.focus_set()

    # ------------------------------------------------------------------ paths

    def _browse_iso(self) -> None:
        current = self.iso_var.get().strip()
        initial = Path(current).expanduser().parent if current else ROOT
        path = filedialog.askopenfilename(
            parent=self.root,
            title="Select the Diablo III Xbox 360 disc image",
            initialdir=str(initial) if initial.is_dir() else str(ROOT),
            filetypes=[
                ("ISO images", "*.iso"),
                ("XISO images", "*.xiso"),
                ("All files", "*"),
            ],
        )
        if path:
            self.iso_var.set(path)

    def _browse_out(self) -> None:
        current = self.out_var.get().strip()
        initial = Path(current).expanduser() if current else DEFAULT_OUT
        path = filedialog.askdirectory(
            parent=self.root,
            title="Select the game data folder",
            initialdir=str(initial) if initial.is_dir() else str(ROOT),
            mustexist=False,
        )
        if path:
            self.out_var.set(path)

    def _resolved_paths(self) -> tuple[Path, Path] | None:
        iso_text = self.iso_var.get().strip()
        out_text = self.out_var.get().strip()
        if not iso_text:
            messagebox.showerror("Missing disc image", "Choose or enter the ISO/XISO path.", parent=self.root)
            return None
        iso = Path(iso_text).expanduser()
        if not iso.is_absolute():
            iso = ROOT / iso
        if not iso.is_file():
            messagebox.showerror("Disc image not found", f"The file does not exist:\n\n{iso}", parent=self.root)
            return None
        if iso.stat().st_size == 0:
            messagebox.showerror("Empty disc image", "The selected file is empty.", parent=self.root)
            return None
        out = Path(out_text or DEFAULT_OUT).expanduser()
        if not out.is_absolute():
            out = ROOT / out
        if out.exists() and not out.is_dir():
            messagebox.showerror(
                "Invalid destination",
                f"The destination exists but is not a folder:\n\n{out}",
                parent=self.root,
            )
            return None
        if not EXTRACTOR.is_file():
            messagebox.showerror(
                "Extractor missing",
                f"Could not find the extractor:\n\n{EXTRACTOR}",
                parent=self.root,
            )
            return None
        return iso.resolve(), out.resolve()

    # --------------------------------------------------------------- process

    def _start(self) -> None:
        if self._running:
            return
        paths = self._resolved_paths()
        if paths is None:
            return
        iso, out = paths

        self._clear_log()
        self._last_error = ""
        self._next_steps = ""
        self.open_button.configure(state="disabled")
        self.copy_button.configure(state="disabled")
        self.progress_var.set(0.0)
        self.status_var.set("Preparing extraction…")
        self._append_log(f"Disc image: {iso}")
        self._append_log(f"Game data:  {out}")
        if self.force_var.get():
            self._append_log("Overwrite existing files: yes")
        self._append_log("")

        cmd = [sys.executable, "-u", str(EXTRACTOR), str(iso), "--out", str(out)]
        if self.force_var.get():
            cmd.append("--force")

        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=True,
            )
        except OSError as exc:
            messagebox.showerror("Could not start extractor", str(exc), parent=self.root)
            self.status_var.set("Extraction failed.")
            return

        self._cancel_requested = False
        self._set_running(True)
        threading.Thread(target=self._read_output, args=(self._proc,), daemon=True).start()

    def _read_output(self, proc: subprocess.Popen[str]) -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            self._queue.put(("line", line.rstrip("\n")))
        rc = proc.wait()
        self._queue.put(("done", rc))

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "line":
                    self._handle_line(str(payload))
                elif kind == "done":
                    self._handle_done(int(payload))  # type: ignore[arg-type]
        except queue.Empty:
            pass
        except tk.TclError:
            return
        try:
            self.root.after(100, self._poll_queue)
        except tk.TclError:
            pass

    def _handle_line(self, line: str) -> None:
        if line:
            self._append_log(line)

        match = re.search(r"Extracting (\d+) files", line)
        if match:
            self.status_var.set(f"Extracting {match.group(1)} files…")
            return

        match = re.match(r"\[(\d+)/(\d+)\]\s*(.*)", line)
        if match:
            index = int(match.group(1))
            total = max(1, int(match.group(2)))
            detail = match.group(3).strip()
            self.progress_var.set(100.0 * index / total)
            self.status_var.set(f"Extracting {index}/{total}: {detail}")
            return

        if line.startswith("Detected language:"):
            self.status_var.set(line)
            return

        if line.startswith("error:") or "error:" in line.lower():
            self._last_error = line
            self.status_var.set("Extraction failed.")
            return

        if line.startswith("Done."):
            self.status_var.set("Extraction complete.")
            self.progress_var.set(100.0)

    def _handle_done(self, rc: int) -> None:
        self._proc = None
        self._set_running(False)

        if self._cancel_requested:
            self.status_var.set("Extraction cancelled.")
            self._append_log("")
            self._append_log("Extraction cancelled by the user.")
            if self._close_when_done:
                self.root.destroy()
            return

        if rc == 0:
            out = Path(self.out_var.get().strip() or DEFAULT_OUT).expanduser().resolve()
            self.status_var.set("Extraction complete.")
            self.progress_var.set(100.0)
            self.open_button.configure(state="normal")
            self._next_steps = self._make_next_steps(out)
            self.copy_button.configure(state="normal")
            messagebox.showinfo(
                "Extraction complete",
                "Game data was extracted successfully.\n\n"
                f"{out}\n\n"
                "Next steps are shown in the log. You can copy them with "
                "'Copy next steps'.",
                parent=self.root,
            )
        else:
            self.status_var.set("Extraction failed.")
            self._append_log("")
            detail = self._last_error or "The extractor exited with an error. See the log above."
            self._append_log(detail)
            messagebox.showerror("Extraction failed", detail, parent=self.root)

        if self._close_when_done:
            self.root.destroy()

    def _set_running(self, running: bool) -> None:
        self._running = running
        state = "disabled" if running else "normal"
        for widget in (
            self.iso_entry,
            self.iso_button,
            self.out_entry,
            self.out_button,
            self.force_check,
            self.extract_button,
        ):
            widget.configure(state=state)
        self.cancel_button.configure(state="normal" if running else "disabled")
        self.close_button.configure(state="disabled" if running else "normal")

    def _cancel(self) -> None:
        if not self._running or self._proc is None:
            return
        self._cancel_requested = True
        self.cancel_button.configure(state="disabled")
        self.status_var.set("Cancelling…")
        self._append_log("Cancelling extraction…")
        proc = self._proc
        try:
            if hasattr(os, "killpg"):
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            else:
                proc.terminate()
        except (OSError, ProcessLookupError):
            try:
                proc.terminate()
            except OSError:
                pass

    def _on_close(self) -> None:
        if self._running:
            if not messagebox.askyesno(
                "Cancel extraction?",
                "Extraction is still running. Cancel it and close the installer?",
                parent=self.root,
            ):
                return
            self._close_when_done = True
            self._cancel()
            return
        self.root.destroy()

    # ------------------------------------------------------------------ misc

    def _clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _append_log(self, line: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", line + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _open_out(self) -> None:
        out = Path(self.out_var.get().strip() or DEFAULT_OUT).expanduser()
        opener = shutil.which("xdg-open")
        if opener is None:
            messagebox.showinfo("Open folder", f"Game data folder:\n\n{out}", parent=self.root)
            return
        try:
            subprocess.Popen([opener, str(out)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            messagebox.showerror("Could not open folder", str(exc), parent=self.root)

    def _copy_next_steps(self) -> None:
        if not self._next_steps:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(self._next_steps)
        self.status_var.set("Next steps copied to the clipboard.")

    @staticmethod
    def _make_next_steps(out: Path) -> str:
        return "\n".join(
            [
                f'cd "{ROOT}"',
                "./port/codegen.sh",
                "./port/build.sh -c RelWithDebInfo",
                f'python3 apply_config.py --game-data-root "{out}"',
                "./launch-diablo3.sh",
            ]
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iso", type=Path, help="pre-fill the ISO/XISO path")
    parser.add_argument("--out", type=Path, help=f"pre-fill the game data folder (default: {DEFAULT_OUT})")
    parser.add_argument("--force", action="store_true", help="re-extract files that already exist")
    parser.add_argument("--version", action="version", version="Souls of the Reaper installer 1.0")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = tk.Tk()
    InstallerApp(root, args.iso, args.out, args.force)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

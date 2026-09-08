# -*- coding: utf-8 -*-
"""
carbon_palette_swap.py
======================

Swaps the Catppuccin Mocha palette for IBM Carbon across the pushbuttons of a
pyRevit extension.

Run this from PyCharm with CPython 3.8+. It is NOT an IronPython script and is
never meant to run inside Revit.

What it does
------------
1. Asks for your `.extension` folder.
2. Lists every `*.pushbutton` bundle that contains a `script.py`, with a count
   of palette colors found in each.
3. Preview shows the exact lines that would change. Convert rewrites the file.

What it will not do
-------------------
Only hex literals whose RGB appears in PALETTE_MAP below are touched. Every
other byte of the file - code, comments, whitespace, line endings, encoding,
any hex color not in the map - is written back untouched. Nothing else in the
bundle (config.py, bundle.yaml, icons) is read or written.

Colors written as `Color.FromRgb(22, 22, 22)` cannot be caught by a hex scan.
Files containing FromRgb/FromArgb are flagged with a warning marker in the list
so you can check them by hand.
"""

import codecs
import os
import re
import shutil
import tkinter as tk
from tkinter import filedialog, ttk

# ---------------------------------------------------------------------------
# Palette map: Catppuccin Mocha  ->  IBM Carbon
# Keys are uppercase RGB with no leading '#'. Edit freely.
# ---------------------------------------------------------------------------

PALETTE_MAP = {
    # --- your seven core roles ------------------------------------------------
    "1E1E2E": "161616",  # background   -> Gray 100
    "2A2A3C": "262626",  # card         -> Gray 90
    "313244": "393939",  # surface      -> Gray 80
    "45475A": "525252",  # muted        -> Gray 70
    "CDD6F4": "F4F4F4",  # text         -> Gray 10
    "A6ADC8": "A8A8A8",  # subtext      -> Gray 40
    "F0A500": "F1C21B",  # accent       -> Yellow 30

    # --- rest of the Catppuccin neutral ramp ---------------------------------
    "11111B": "000000",  # crust        -> Black
    "181825": "0D0D0D",  # mantle       -> (no exact Carbon token; ramp extension)
    "585B70": "6F6F6F",  # surface2     -> Gray 60
    "6C7086": "8D8D8D",  # overlay0     -> Gray 50
    "7F849C": "8D8D8D",  # overlay1     -> Gray 50
    "9399B2": "A8A8A8",  # overlay2     -> Gray 40
    "BAC2DE": "C6C6C6",  # subtext1     -> Gray 30

    # --- accents -------------------------------------------------------------
    "F38BA8": "FF8389",  # red          -> Red 40
    "EBA0AC": "FF8389",  # maroon       -> Red 40
    "F2CDCD": "FFD7D9",  # flamingo     -> Red 20
    "F5E0DC": "FFD7D9",  # rosewater    -> Red 20
    "FAB387": "FF832B",  # peach        -> Orange 40
    "F9E2AF": "F1C21B",  # yellow       -> Yellow 30
    "A6E3A1": "42BE65",  # green        -> Green 40
    "94E2D5": "08BDBA",  # teal         -> Teal 40
    "89DCEB": "33B1FF",  # sky          -> Cyan 40
    "74C7EC": "33B1FF",  # sapphire     -> Cyan 40
    "89B4FA": "78A9FF",  # blue         -> Blue 40
    "B4BEFE": "A6C8FF",  # lavender     -> Blue 30
    "CBA6F7": "BE95FF",  # mauve        -> Purple 40
    "F5C2E7": "FF7EB6",  # pink         -> Magenta 40
}

# Bundle folder suffixes to scan. Add ".smartbutton" here if you want those too.
BUNDLE_SUFFIXES = (".pushbutton",)

SCRIPT_NAME = "script.py"
BACKUP_SUFFIX = ".bak"

# Matches #RRGGBB and #AARRGGBB, and refuses to bite into a longer hex run.
HEX_RE = re.compile(r"#((?:[0-9A-Fa-f]{8})|(?:[0-9A-Fa-f]{6}))(?![0-9A-Fa-f])")
MANUAL_COLOR_RE = re.compile(r"\bFrom(?:Rgb|Argb)\b")


# ---------------------------------------------------------------------------
# File IO that preserves encoding and line endings
# ---------------------------------------------------------------------------

def read_source(path):
    """Return (text, encoding). Newlines are kept verbatim in the text."""
    with open(path, "rb") as fh:
        raw = fh.read()
    if raw.startswith(codecs.BOM_UTF8):
        return raw[len(codecs.BOM_UTF8):].decode("utf-8"), "utf-8-sig"
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    raise IOError("Could not decode {0}".format(path))


def write_source(path, text, encoding):
    with open(path, "w", encoding=encoding, newline="") as fh:
        fh.write(text)


# ---------------------------------------------------------------------------
# The substitution itself
# ---------------------------------------------------------------------------

def convert_text(text):
    """
    Return (new_text, tally) where tally maps 'OLD->NEW' to a hit count.

    Alpha channels are preserved. Original letter case is preserved: an all
    lowercase source hex produces an all lowercase replacement.
    """
    tally = {}

    def _sub(match):
        token = match.group(1)
        if len(token) == 8:
            alpha, rgb = token[:2], token[2:]
        else:
            alpha, rgb = "", token

        target = PALETTE_MAP.get(rgb.upper())
        if target is None:
            return match.group(0)

        if rgb.islower():
            target = target.lower()

        key = "#{0} -> #{1}".format(rgb.upper(), target.upper())
        tally[key] = tally.get(key, 0) + 1
        return "#" + alpha + target

    return HEX_RE.sub(_sub, text), tally


def diff_lines(old_text, new_text):
    """Line-by-line pairs that actually differ, as (lineno, old, new)."""
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    out = []
    for idx, (a, b) in enumerate(zip(old_lines, new_lines), start=1):
        if a != b:
            out.append((idx, a.strip(), b.strip()))
    return out


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

class Bundle(object):
    def __init__(self, root, script_path):
        self.script_path = script_path
        bundle_dir = os.path.dirname(script_path)
        self.name = os.path.basename(bundle_dir)
        for suffix in BUNDLE_SUFFIXES:
            if self.name.lower().endswith(suffix):
                self.name = self.name[: -len(suffix)]
                break
        self.location = os.path.relpath(os.path.dirname(bundle_dir), root)
        self.hits = 0
        self.tally = {}
        self.manual_colors = False
        self.error = None
        self.done = False
        self.analyse()

    def analyse(self):
        try:
            text, _ = read_source(self.script_path)
        except Exception as exc:
            self.error = str(exc)
            return
        new_text, tally = convert_text(text)
        self.tally = tally
        self.hits = sum(tally.values())
        self.manual_colors = bool(MANUAL_COLOR_RE.search(text))
        self._pending = new_text != text

    def preview(self):
        text, _ = read_source(self.script_path)
        new_text, tally = convert_text(text)
        return text, new_text, tally

    def apply(self, make_backup=True):
        text, encoding = read_source(self.script_path)
        new_text, tally = convert_text(text)
        if new_text == text:
            return 0
        if make_backup:
            shutil.copy2(self.script_path, self.script_path + BACKUP_SUFFIX)
        write_source(self.script_path, new_text, encoding)
        self.done = True
        self.hits = 0
        self.tally = {}
        return sum(tally.values())

    @property
    def backup_path(self):
        return self.script_path + BACKUP_SUFFIX


def scan_extension(root):
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        base = os.path.basename(dirpath).lower()
        if not base.endswith(BUNDLE_SUFFIXES):
            continue
        if SCRIPT_NAME in filenames:
            found.append(Bundle(root, os.path.join(dirpath, SCRIPT_NAME)))
    found.sort(key=lambda b: (b.location.lower(), b.name.lower()))
    return found


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

BG = "#161616"
CARD = "#262626"
SURFACE = "#393939"
MUTED = "#525252"
TEXT = "#F4F4F4"
SUBTEXT = "#A8A8A8"
ACCENT = "#F1C21B"
WARN = "#FF832B"
OK = "#42BE65"


class App(object):
    def __init__(self, root):
        self.root = root
        self.root.title("Carbon palette swap")
        self.root.geometry("1000x680")
        self.root.configure(bg=BG)

        self.ext_root = None
        self.bundles = []
        self.rows = []
        self.backup_var = tk.BooleanVar(value=True)
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *_: self.render_rows())

        self._build_toolbar()
        self._build_list()
        self._build_log()

    # -- toolbar -----------------------------------------------------------
    def _build_toolbar(self):
        bar = tk.Frame(self.root, bg=CARD, padx=12, pady=10)
        bar.pack(fill="x")

        tk.Button(
            bar, text="Choose .extension folder", command=self.choose_folder,
            bg=ACCENT, fg="#161616", activebackground=ACCENT,
            relief="flat", padx=14, pady=6, borderwidth=0,
        ).pack(side="left")

        self.path_label = tk.Label(
            bar, text="no folder selected", bg=CARD, fg=SUBTEXT, anchor="w",
        )
        self.path_label.pack(side="left", padx=12, fill="x", expand=True)

        tk.Checkbutton(
            bar, text="keep .bak backup", variable=self.backup_var,
            bg=CARD, fg=SUBTEXT, selectcolor=SURFACE, activebackground=CARD,
            activeforeground=TEXT, relief="flat", borderwidth=0,
            highlightthickness=0,
        ).pack(side="left", padx=8)

        for label, cmd in (
            ("Rescan", self.rescan),
            ("Convert all", self.convert_all),
            ("Restore backups", self.restore_backups),
        ):
            tk.Button(
                bar, text=label, command=cmd, bg=SURFACE, fg=TEXT,
                activebackground=MUTED, activeforeground=TEXT,
                relief="flat", padx=12, pady=6, borderwidth=0,
            ).pack(side="left", padx=4)

        search = tk.Frame(self.root, bg=BG, padx=12, pady=8)
        search.pack(fill="x")
        tk.Label(search, text="Filter", bg=BG, fg=SUBTEXT).pack(side="left")
        entry = tk.Entry(
            search, textvariable=self.filter_var, bg=CARD, fg=TEXT,
            insertbackground=ACCENT, relief="flat", highlightthickness=1,
            highlightbackground=SURFACE, highlightcolor=ACCENT,
        )
        entry.pack(side="left", fill="x", expand=True, padx=8, ipady=4)

        self.count_label = tk.Label(search, text="", bg=BG, fg=SUBTEXT)
        self.count_label.pack(side="right")

    # -- scrolling list ----------------------------------------------------
    def _build_list(self):
        wrap = tk.Frame(self.root, bg=BG, padx=12)
        wrap.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0)
        scroll = ttk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.list_frame = tk.Frame(self.canvas, bg=BG)
        self.window_id = self.canvas.create_window(
            (0, 0), window=self.list_frame, anchor="nw"
        )
        self.list_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas.bind(
            "<Configure>",
            lambda e: self.canvas.itemconfigure(self.window_id, width=e.width),
        )
        self.canvas.bind_all(
            "<MouseWheel>",
            lambda e: self.canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"),
        )

    # -- log ---------------------------------------------------------------
    def _build_log(self):
        frame = tk.Frame(self.root, bg=BG, padx=12, pady=10)
        frame.pack(fill="x")
        self.log_text = tk.Text(
            frame, height=7, bg=CARD, fg=SUBTEXT, relief="flat",
            insertbackground=ACCENT, wrap="none",
        )
        self.log_text.pack(fill="x")
        self.log_text.configure(state="disabled")

    def log(self, message):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    # -- actions -----------------------------------------------------------
    def choose_folder(self):
        path = filedialog.askdirectory(title="Select your .extension folder")
        if not path:
            return
        self.ext_root = path
        if not path.lower().rstrip("\\/").endswith(".extension"):
            self.log("Note: '{0}' does not end in .extension - scanning anyway."
                     .format(os.path.basename(path)))
        self.rescan()

    def rescan(self):
        if not self.ext_root:
            self.log("Choose a folder first.")
            return
        self.path_label.configure(text=self.ext_root, fg=TEXT)
        self.bundles = scan_extension(self.ext_root)
        total = sum(b.hits for b in self.bundles)
        pending = sum(1 for b in self.bundles if b.hits)
        self.log("Scanned {0} pushbuttons - {1} with palette colors, {2} hex "
                 "literals to swap.".format(len(self.bundles), pending, total))
        for bundle in self.bundles:
            if bundle.error:
                self.log("  ! {0}: {1}".format(bundle.name, bundle.error))
            elif bundle.manual_colors:
                self.log("  ! {0}: uses FromRgb/FromArgb - check by hand."
                         .format(bundle.name))
        self.render_rows()

    def render_rows(self):
        for child in self.list_frame.winfo_children():
            child.destroy()
        self.rows = []

        needle = self.filter_var.get().strip().lower()
        shown = [
            b for b in self.bundles
            if not needle
            or needle in b.name.lower()
            or needle in b.location.lower()
        ]

        self.count_label.configure(
            text="{0} of {1} shown".format(len(shown), len(self.bundles))
        )

        if not shown:
            tk.Label(
                self.list_frame,
                text="Nothing to show." if self.bundles else
                     "Choose a .extension folder to begin.",
                bg=BG, fg=MUTED, pady=24,
            ).pack()
            return

        for bundle in shown:
            self.rows.append(self._make_row(bundle))

    def _make_row(self, bundle):
        row = tk.Frame(self.list_frame, bg=CARD, padx=12, pady=9)
        row.pack(fill="x", pady=3)

        left = tk.Frame(row, bg=CARD)
        left.pack(side="left", fill="x", expand=True)

        title = bundle.name
        if bundle.manual_colors:
            title += "   (FromRgb present)"
        tk.Label(
            left, text=title, bg=CARD, fg=TEXT, anchor="w",
            font=("Segoe UI", 10, "bold"),
        ).pack(fill="x")
        tk.Label(
            left, text=bundle.location, bg=CARD, fg=MUTED, anchor="w",
            font=("Segoe UI", 8),
        ).pack(fill="x")

        if bundle.error:
            status, color = "unreadable", WARN
        elif bundle.done:
            status, color = "converted", OK
        elif bundle.hits:
            status, color = "{0} colors".format(bundle.hits), ACCENT
        else:
            status, color = "no palette colors", MUTED

        status_label = tk.Label(
            row, text=status, bg=CARD, fg=color, width=18, anchor="e"
        )
        status_label.pack(side="left", padx=10)

        convert_btn = tk.Button(
            row, text="Convert", bg=ACCENT, fg="#161616", relief="flat",
            padx=14, pady=5, borderwidth=0, activebackground=ACCENT,
        )
        preview_btn = tk.Button(
            row, text="Preview", bg=SURFACE, fg=TEXT, relief="flat",
            padx=14, pady=5, borderwidth=0, activebackground=MUTED,
            activeforeground=TEXT,
        )
        convert_btn.pack(side="right", padx=(6, 0))
        preview_btn.pack(side="right")

        def do_convert():
            try:
                changed = bundle.apply(make_backup=self.backup_var.get())
            except Exception as exc:
                self.log("! {0}: {1}".format(bundle.name, exc))
                return
            self.log("{0}: {1} colors swapped.".format(bundle.name, changed))
            status_label.configure(text="converted", fg=OK)
            convert_btn.configure(
                state="disabled", text="Done", bg=SURFACE, fg=MUTED
            )

        convert_btn.configure(command=do_convert)
        preview_btn.configure(command=lambda: self.show_preview(bundle))

        if bundle.error or bundle.done or not bundle.hits:
            convert_btn.configure(state="disabled", bg=SURFACE, fg=MUTED)
        if bundle.error:
            preview_btn.configure(state="disabled", fg=MUTED)

        return row

    def show_preview(self, bundle):
        try:
            old_text, new_text, tally = bundle.preview()
        except Exception as exc:
            self.log("! {0}: {1}".format(bundle.name, exc))
            return

        win = tk.Toplevel(self.root)
        win.title("Preview - {0}".format(bundle.name))
        win.geometry("900x560")
        win.configure(bg=BG)

        tk.Label(
            win, text=bundle.script_path, bg=BG, fg=SUBTEXT, anchor="w",
            padx=12, pady=8,
        ).pack(fill="x")

        box = tk.Text(
            win, bg=CARD, fg=TEXT, relief="flat", wrap="none",
            insertbackground=ACCENT, padx=10, pady=8,
        )
        box.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        changes = diff_lines(old_text, new_text)
        if not changes:
            box.insert("end", "No palette colors found in this file.\n")
        else:
            box.insert("end", "Color tally\n")
            for key in sorted(tally):
                box.insert("end", "  {0}   x{1}\n".format(key, tally[key]))
            box.insert("end", "\n{0} lines change\n\n".format(len(changes)))
            for lineno, before, after in changes:
                box.insert("end", "line {0}\n".format(lineno))
                box.insert("end", "  -  {0}\n".format(before))
                box.insert("end", "  +  {0}\n\n".format(after))
        box.configure(state="disabled")

    def convert_all(self):
        targets = [b for b in self.bundles if b.hits and not b.error]
        if not targets:
            self.log("Nothing to convert.")
            return
        total = 0
        for bundle in targets:
            try:
                total += bundle.apply(make_backup=self.backup_var.get())
            except Exception as exc:
                self.log("! {0}: {1}".format(bundle.name, exc))
        self.log("Converted {0} files, {1} colors swapped."
                 .format(len(targets), total))
        self.render_rows()

    def restore_backups(self):
        if not self.ext_root:
            self.log("Choose a folder first.")
            return
        restored = 0
        for dirpath, _dirnames, filenames in os.walk(self.ext_root):
            for name in filenames:
                if name == SCRIPT_NAME + BACKUP_SUFFIX:
                    src = os.path.join(dirpath, name)
                    dst = os.path.join(dirpath, SCRIPT_NAME)
                    shutil.copy2(src, dst)
                    os.remove(src)
                    restored += 1
        self.log("Restored {0} files from backup.".format(restored))
        self.rescan()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
# -*- coding: utf-8 -*-
"""export_core - the Revit-free half of Export Sheets.

File names built from an ordered list of fields, cleaning names for Windows,
unique file paths, PDF groups and the saved settings / profiles. Nothing here
imports Revit, so it runs (and is tested) in plain Python 3 as well as
IronPython 2.7.

Rules: IronPython 2.7 syntax only (no f-strings, no nonlocal).

Author: Mohamed Bedair
"""

import copy
import io
import json
import os
import re

try:
    _TEXT = (basestring,)       # noqa: F821  IronPython / Python 2
except NameError:               # Python 3 (tests)
    _TEXT = (str,)

try:
    _unicode = unicode          # noqa: F821
except NameError:
    _unicode = str


# =============================================================================
# FORMATS
# =============================================================================
FORMATS = ("pdf", "dwg")
FORMAT_LABELS = {"pdf": u"PDF", "dwg": u"DWG"}
FORMAT_FOLDERS = {"pdf": u"PDF", "dwg": u"DWG"}


# =============================================================================
# FILE NAME FIELDS
# =============================================================================
# A file name is a list of fields joined in order. Each field says where its
# value comes from (source), what it is (name) and the text written after it
# (sep). source "text" writes name itself.
SOURCES = ("builtin", "item", "titleblock", "project", "text")
SOURCE_LABELS = {"builtin": u"Built-in", "item": u"Sheet", "titleblock": u"Title Block",
                 "project": u"Project Info", "text": u"Text"}

FIELDS_SHEETS = [{"source": "builtin", "name": u"Sheet Number", "sep": u" - "},
                 {"source": "builtin", "name": u"Sheet Name", "sep": u""}]
FIELDS_VIEWS = [{"source": "builtin", "name": u"View Name", "sep": u""}]
PATTERN_COMBINED = u"{Project Number} - Sheets {Export Date}"


def source_label(source, mode):
    """Tag shown next to a parameter: an item parameter is a Sheet or a View one."""
    if source == "item":
        return u"Sheet" if mode == "sheets" else u"View"
    return SOURCE_LABELS.get(source, source)


def field(source, name, sep=u""):
    return {"source": source, "name": name, "sep": sep}


def default_fields(mode):
    return copy.deepcopy(FIELDS_SHEETS if mode == "sheets" else FIELDS_VIEWS)


# =============================================================================
# DEFAULT SETTINGS (everything the window remembers)
# =============================================================================
DEFAULTS = {
    "mode": "sheets",                    # sheets | views
    "fields_sheets": FIELDS_SHEETS,
    "fields_views": FIELDS_VIEWS,
    "name_prefix": u"",
    "name_suffix": u"",
    "replace_char": u"_",                # written instead of \ / : * ? " < > |
    "skip_empty": True,                  # empty value: leave out it and its separator
    "formats": ["pdf"],
    "folder": u"",
    "subfolders": True,                  # \PDF, \DWG
    "overwrite": True,
    "open_folder": True,
    # PDF
    "pdf_output": "separate",            # separate | combine | group
    # Separate PDFs are one Revit export call per sheet. pdf_background (Revit
    # 2025+, Sheets only) hands them to Revit's background process instead,
    # in one batch written to a local temp folder, then renamed and moved.
    "pdf_background": False,
    "pdf_combined_name": PATTERN_COMBINED,
    "pdf_group_by": u"",
    "pdf_placement": "center",           # center | offset
    "pdf_offset_x": 0.0,                 # mm
    "pdf_offset_y": 0.0,                 # mm
    "pdf_zoom": "fit",                   # fit | zoom
    "pdf_zoom_pct": 100,
    "pdf_raster": False,                 # False = vector processing
    "pdf_quality": "High",               # Low | Medium | High | Presentation
    "pdf_color": "Color",                # Color | GrayScale | BlackLine
    "pdf_dpi": 300,                      # export quality: curve smoothness + raster areas
    "pdf_links_blue": False,
    "pdf_hide_ref": True,
    "pdf_hide_tags": True,
    "pdf_hide_scope": True,
    "pdf_hide_crop": True,
    "pdf_halftone": False,
    "pdf_mask": True,
    # DWG
    "cad_setup": u"",                    # "" = Revit default settings
    "cad_version": "Default",            # Default | R2018 | R2013 | R2010 | R2007
    "cad_merged": True,
    "cad_shared": False,
    "cad_delete_pcp": True,              # the .pcp Revit writes next to each DWG
    # Ticked items and hand-typed names, by Revit UniqueId
    "picked_sheets": [],
    "picked_views": [],
    "names": {},
}

CHOICES = {
    "mode": ("sheets", "views"),
    "pdf_output": ("separate", "combine", "group"),
    "pdf_placement": ("center", "offset"),
    "pdf_zoom": ("fit", "zoom"),
    "pdf_quality": ("Low", "Medium", "High", "Presentation"),
    "pdf_color": ("Color", "GrayScale", "BlackLine"),
    "pdf_dpi": (72, 144, 300, 600, 1200),
    "cad_version": ("Default", "R2018", "R2013", "R2010", "R2007"),
}


def default_settings():
    return copy.deepcopy(DEFAULTS)


def _clean_fields(value, default):
    """A list of field dicts, keeping only well-formed ones."""
    if not isinstance(value, list):
        return copy.deepcopy(default)
    out = []
    for f in value:
        if not isinstance(f, dict):
            continue
        source, name, sep = f.get("source"), f.get("name"), f.get("sep", u"")
        if source in SOURCES and isinstance(name, _TEXT) and name and isinstance(sep, _TEXT):
            out.append(field(source, name, sep))
    return out


def clean_settings(loaded):
    """Settings read from disk merged onto the defaults. Unknown keys are
    dropped, wrong types and values outside CHOICES fall back to the default,
    so an old or hand-edited file can never break the window."""
    s = default_settings()
    if not isinstance(loaded, dict):
        return s
    for key, default in DEFAULTS.items():
        if key not in loaded:
            continue
        value = loaded[key]
        if key.startswith("fields_"):
            s[key] = _clean_fields(value, default)
        elif isinstance(default, bool):
            if isinstance(value, bool):
                s[key] = value
        elif isinstance(default, (int, float)):
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                s[key] = type(default)(value)
        elif isinstance(default, _TEXT):
            if isinstance(value, _TEXT):
                s[key] = value
        elif isinstance(default, list):
            if isinstance(value, list):
                s[key] = [v for v in value if isinstance(v, _TEXT)]
        elif isinstance(default, dict):
            if isinstance(value, dict):
                s[key] = dict((k, v) for k, v in value.items()
                              if isinstance(k, _TEXT) and isinstance(v, _TEXT))
        if key in CHOICES and s[key] not in CHOICES[key]:
            s[key] = default
    if "pdf_background" not in loaded and loaded.get("pdf_engine") == "background":
        s["pdf_background"] = True          # settings saved before the checkbox
    s["formats"] = [f for f in s["formats"] if f in FORMATS]
    if s["pdf_zoom_pct"] < 10 or s["pdf_zoom_pct"] > 1000:
        s["pdf_zoom_pct"] = 100
    s["replace_char"] = clean_replace_char(s["replace_char"])
    return s


# =============================================================================
# FILE NAMES
# =============================================================================
_TOKEN = re.compile(r"\{([^{}]+)\}")
_BAD = u'\\/:*?"<>|'
_BAD_CHARS = re.compile(u'[\\\\/:*?"<>|\u0000-\u001f]')
_EDGE = re.compile(u"^[\\s\\-_.,]+|[\\s\\-_.,]+$")
_SPACES = re.compile(u"\\s{2,}")
_RESERVED = set(["CON", "PRN", "AUX", "NUL"] +
                ["COM%d" % i for i in range(1, 10)] +
                ["LPT%d" % i for i in range(1, 10)])
MAX_NAME = 180          # keeps folder + name under Windows' 260 characters


def to_text(value):
    if value is None:
        return u""
    if isinstance(value, _TEXT):
        return _unicode(value)
    return _unicode(u"{0}".format(value))


def clean_replace_char(text):
    """The text written instead of an illegal character: at most 3 characters,
    none of them illegal themselves. Empty is allowed (characters are dropped)."""
    return u"".join(c for c in to_text(text) if c not in _BAD and ord(c) >= 32)[:3]


def sanitize(name, fallback=u"Unnamed", replace_char=u"_"):
    """A name Windows accepts: illegal characters become replace_char, extra
    spaces and leading / trailing separators go, reserved device names get a
    _ prefix and very long names are cut."""
    text = _BAD_CHARS.sub(clean_replace_char(replace_char), to_text(name))
    text = _SPACES.sub(u" ", text)
    text = _EDGE.sub(u"", text)
    if not text:
        text = fallback
    if text.split(u".")[0].upper() in _RESERVED:
        text = u"_" + text
    if len(text) > MAX_NAME:
        text = text[:MAX_NAME].rstrip()
    return text


def build_name(fields, value_of, prefix=u"", suffix=u"", skip_empty=True,
               replace_char=u"_", fallback=u"Unnamed"):
    """File name (no extension) from an ordered list of fields.

    value_of(field) gives the text of a non-text field (None when empty).
    With skip_empty, an empty field and the separator after it are left out,
    so "A101 -  - Plan" never happens. The separator after the last written
    field is dropped too."""
    parts = []
    for f in fields:
        if f.get("source") == "text":
            value = to_text(f.get("name"))
        else:
            try:
                value = to_text(value_of(f)).strip()
            except Exception:
                value = u""
        if not value and skip_empty:
            continue
        parts.append((value, to_text(f.get("sep"))))
    body = u""
    for index, (value, sep) in enumerate(parts):
        body += value
        if index < len(parts) - 1:
            body += sep
    return sanitize(to_text(prefix) + body + to_text(suffix), fallback, replace_char)


def tokens_in(pattern):
    """Token names used by a pattern, in order: u"{A} - {B}" -> [u"A", u"B"]."""
    return [m.group(1).strip() for m in _TOKEN.finditer(to_text(pattern))]


def expand(pattern, resolve, fallback=u"Unnamed", replace_char=u"_"):
    """Fill a pattern's {Tokens} with resolve(token) and clean the result.
    Used for the combined PDF's name."""
    cache = {}

    def _sub(match):
        token = match.group(1).strip()
        if token not in cache:
            try:
                cache[token] = to_text(resolve(token))
            except Exception:
                cache[token] = u""
        return cache[token]

    text = _TOKEN.sub(_sub, to_text(pattern))
    text = re.sub(u"(\\s*-\\s*){2,}", u" - ", text)      # "A -  - B" from an empty token
    return sanitize(text, fallback, replace_char)


def natural_key(text):
    """Sort key that puts A2 before A10."""
    parts = re.split(r"(\d+)", to_text(text).lower())
    return [(0, int(p), u"") if p.isdigit() else (1, 0, p) for p in parts]


# =============================================================================
# OUTPUT PATHS
# =============================================================================
def format_folder(root, fmt, subfolders):
    return os.path.join(root, FORMAT_FOLDERS[fmt]) if subfolders else root


def unique_name(folder, name, ext, overwrite, taken, exists=os.path.exists):
    """File name (without extension) to use for this export.

    taken: lower-case full paths already handed out in this run, so two
    sheets with the same name never write over each other. With overwrite
    off, an existing file on disk also gets the next free " (2)", " (3)"...
    """
    n = 1
    candidate = name
    while True:
        full = os.path.join(folder, candidate + ext)
        key = full.lower()
        if key not in taken and (overwrite or not exists(full)):
            taken.add(key)
            return candidate
        n += 1
        candidate = u"{0} ({1})".format(name, n)


def order_jobs(jobs, row_order):
    """Jobs in the order they run: always sheet by sheet - every job for one
    sheet / view in turn (its PDF, then its DWG), the way ProSheets plots.

    Why: tested on a real project, all-PDFs-then-all-DWGs made each PDF a few
    minutes slower than the one before (Revit's PDF export builds up within a
    session); with a DWG between two PDFs the build-up mostly went away.

    Jobs covering several rows (a combined PDF, or Revit's background PDF
    batch) stay first, in their own order. row_order: row keys in table order.
    A job dict needs "rows_key" (the key of its single row) or None for a
    multi-row job."""
    multi = [j for j in jobs if j.get("rows_key") is None]
    by_key = {}
    for j in jobs:
        if j.get("rows_key") is not None:
            by_key.setdefault(j["rows_key"], []).append(j)   # keeps PDF before DWG
    ordered = list(multi)
    for key in row_order:
        ordered.extend(by_key.pop(key, []))
    for rest in by_key.values():        # rows not in row_order (shouldn't happen)
        ordered.extend(rest)
    return ordered


def group_rows(rows, key_of):
    """[(group value, [rows])] in first-seen order. Empty values share one
    group named "(no value)"."""
    order, groups = [], {}
    for row in rows:
        key = to_text(key_of(row)).strip() or u"(no value)"
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(row)
    return [(k, groups[k]) for k in order]


# =============================================================================
# PROFILES  (%APPDATA%\B_Dare95\ExportSheets\profiles.json)
# =============================================================================
STATE_DIR = os.path.join(os.getenv("APPDATA") or os.path.expanduser("~"),
                         "B_Dare95", "ExportSheets")
STORE_FILE = os.path.join(STATE_DIR, "profiles.json")


# =============================================================================
# BATCH PDF: Revit names each file by Sheet Number; find the sheet again
# =============================================================================
def _norm(text):
    return u"".join(c for c in to_text(text).lower() if c.isalnum())


def match_file(stem, keys):
    """Which sheet number (in keys) a Revit-written file name belongs to.

    Exact name first, then the same letters and digits ignoring case and
    punctuation (Revit may swap characters it can't use in a file name),
    then the longest sheet number the name ends with (in case Revit adds
    something in front). None when nothing fits."""
    stem = to_text(stem)
    if stem in keys:
        return stem
    n = _norm(stem)
    for key in keys:
        if _norm(key) == n:
            return key
    best = None
    for key in keys:
        k = _norm(key)
        if k and n.endswith(k) and (best is None or len(k) > len(_norm(best))):
            best = key
    return best


def duplicate_keys(keys):
    """Sheet numbers that would give the same file name (can't be batched)."""
    seen, dup = {}, set()
    for key in keys:
        n = _norm(key)
        if n in seen:
            dup.add(key)
            dup.add(seen[n])
        seen[n] = key
    return dup


# =============================================================================
# STAGE FOLDER  (%LOCALAPPDATA%\B_Dare95\ExportSheets\Stage) - Revit writes
# here first, on the local disk; finished files are moved to the real folder
# =============================================================================
STAGE_ROOT = os.path.join(os.getenv("LOCALAPPDATA") or os.path.expanduser("~"),
                          "B_Dare95", "ExportSheets", "Stage")


def new_stage(now, root=STAGE_ROOT):
    """A new empty folder for one run."""
    base = os.path.join(root, now.strftime("run_%Y%m%d_%H%M%S"))
    path, n = base, 1
    while os.path.exists(path):
        n += 1
        path = u"{0}_{1}".format(base, n)
    os.makedirs(path)
    return path


def clean_stages(root=STAGE_ROOT, older_than_hours=12, now=None):
    """Delete run folders left behind by runs that crashed or were stopped."""
    import shutil
    import time as _time
    limit = (now or _time.time()) - older_than_hours * 3600
    try:
        names = os.listdir(root)
    except Exception:
        return
    for name in names:
        path = os.path.join(root, name)
        try:
            if os.path.isdir(path) and os.path.getmtime(path) < limit:
                shutil.rmtree(path, ignore_errors=True)
        except Exception:
            pass


# =============================================================================
# TIMING LOG  (%APPDATA%\B_Dare95\ExportSheets\logs\*.csv)
# =============================================================================
LOG_DIR = os.path.join(STATE_DIR, "logs")
KEEP_LOGS = 30
LOG_COLUMNS = (u"#", u"Format", u"File", u"Sheets / views", u"Seconds", u"Result", u"Reason")


def fmt_seconds(seconds):
    """3.24 -> u"3.2 s", 125 -> u"2:05"."""
    if seconds < 60:
        return u"{0:.1f} s".format(seconds)
    seconds = int(round(seconds))
    return u"{0}:{1:02d}".format(seconds // 60, seconds % 60)


def _csv_cell(value):
    text = to_text(value)
    if any(c in text for c in u',"\n\r'):
        text = u'"' + text.replace(u'"', u'""') + u'"'
    return text


def log_name(model, now):
    """File name of one run's log: 2026-11-19_1430_<model>.csv"""
    return u"{0}_{1}.csv".format(now.strftime("%Y-%m-%d_%H%M%S"), sanitize(model, u"model"))


def write_timing_log(path, entries, header_lines=()):
    """One CSV row per exported file. entries: dicts with keys fmt, name,
    count, seconds, ok, reason. Opens straight in Excel (UTF-8 with BOM).
    header_lines go on top as '# ...' notes (model, settings, totals)."""
    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    lines = [u"# " + to_text(h) for h in header_lines]
    lines.append(u",".join(LOG_COLUMNS))
    for i, e in enumerate(entries):
        lines.append(u",".join(_csv_cell(v) for v in (
            i + 1, e.get("fmt", u""), e.get("name", u""), e.get("count", 1),
            u"{0:.2f}".format(e.get("seconds", 0.0)),
            u"OK" if e.get("ok") else u"FAILED", e.get("reason", u""))))
    with io.open(path, "w", encoding="utf-8-sig", newline=u"") as handle:
        handle.write(u"\r\n".join(lines) + u"\r\n")
    return path


def prune_logs(folder=LOG_DIR, keep=KEEP_LOGS):
    """Delete all but the newest `keep` logs."""
    try:
        logs = sorted(f for f in os.listdir(folder) if f.lower().endswith(".csv"))
    except Exception:
        return
    for name in logs[:-keep] if keep else logs:
        try:
            os.remove(os.path.join(folder, name))
        except Exception:
            pass


def slowest(entries, n=3):
    """The n slowest successful entries, slowest first."""
    done = [e for e in entries if e.get("ok")]
    return sorted(done, key=lambda e: -e.get("seconds", 0.0))[:n]


def empty_store():
    return {"last": default_settings(), "current": u"", "profiles": {}}


def load_store(path=STORE_FILE):
    """The saved store, or an empty one when the file is missing or broken."""
    store = empty_store()
    try:
        with io.open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return store
    if not isinstance(data, dict):
        return store
    store["last"] = clean_settings(data.get("last"))
    profiles = data.get("profiles")
    if isinstance(profiles, dict):
        for name, settings in profiles.items():
            if isinstance(name, _TEXT) and name.strip():
                store["profiles"][name] = clean_settings(settings)
    current = data.get("current")
    if isinstance(current, _TEXT) and current in store["profiles"]:
        store["current"] = current
    return store


def save_store(store, path=STORE_FILE):
    """Write the store (via a temp file, so a crash never leaves half a file)."""
    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    text = json.dumps(store, indent=2, sort_keys=True, ensure_ascii=False)
    tmp = path + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as handle:
        handle.write(to_text(text))
    if os.path.exists(path):
        os.remove(path)
    os.rename(tmp, path)

# -*- coding: utf-8 -*-
"""DLC Export Sheets - core logic.

Pure Python (IronPython 2.7 compatible). No Revit dependency, so every rule
here is covered by the test harness: settings, path tokens, file naming,
sanitising, de-duplication, existing-file policy, path-length guard and the
export plan.
"""
import copy
import datetime
import io
import json
import ntpath
import os
import re

VERSION = "1.1.0"

try:
    _TEXT_TYPES = (basestring,)  # noqa: F821  (IronPython / Py2)
except NameError:  # pragma: no cover - Python 3 test runs
    _TEXT_TYPES = (str,)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
PDF_PAPER_DEFAULT = "Default"          # = use the sheet's title block size
PDF_ORIENTATIONS = ["Auto", "Landscape", "Portrait"]
PDF_COLORS = ["Color", "GrayScale", "BlackLine"]
PDF_RASTER = ["Low", "Medium", "High", "Presentation"]
PDF_DPI = ["DPI72", "DPI144", "DPI300", "DPI600", "DPI1200", "DPI2400"]
PDF_OUTPUT_MODES = ["separate", "combined", "both"]
EXISTING_POLICIES = ["overwrite", "skip", "increment"]
BATCH_SIZES = [1, 5, 10, 20, 50]
COMBINE_ORDERS = ["list", "number", "name"]

DEFAULT_SETTINGS = {
    "schema": 1,
    "mode": "sheets",
    "formats": {"pdf": True, "dwg": True},
    "output": {
        "root": "%USERPROFILE%\\Desktop\\DLC Exports\\%YYYY-%mm-%dd",
        "split_by_format": True,
        "pdf_subfolder": "PDF",
        "dwg_subfolder": "DWG",
        "existing": "overwrite",
        "open_folder": True,
        # performance
        "staging": True,          # write to a local temp folder, then move (fast on OneDrive/network)
        "batch_size": 10,         # sheets per Revit export call (1 = one call per sheet)
    },
    "naming": {
        "fields": [
            {"source": "sheet", "name": "Sheet Number", "sep": " - "},
            {"source": "sheet", "name": "Sheet Name", "sep": ""},
        ],
        "view_fields": [
            {"source": "view", "name": "View Name", "sep": ""},
        ],
        "prefix": "",
        "suffix": "",
        "skip_empty": True,
        "replace_char": "_",
    },
    "pdf": {
        "paper": PDF_PAPER_DEFAULT,
        "orientation": "Auto",
        "placement": "Center",
        "offset_x_mm": 0.0,
        "offset_y_mm": 0.0,
        "zoom_fit": True,
        "zoom_percent": 100,
        "raster_processing": False,
        "color": "Color",
        "raster_quality": "High",
        "dpi": "DPI300",
        "view_links_blue": False,
        "hide_ref_planes": True,
        "hide_unref_tags": True,
        "hide_scope_boxes": True,
        "hide_crop": True,
        "halftone_thin": False,
        "mask_coincident": True,
        "output_mode": "separate",
        "combined_name": "%ProjectNumber% - Combined Set - %YYYY-%mm-%dd",
        "combine_order": "list",
    },
    "dwg": {
        "setup": "",
        "merged": True,
        "delete_pcp": True,
    },
    "prep": {
        "hide_isolate": True,
        "worksharing": True,
        "reveal_hidden": True,
        "reveal_constraints": True,
    },
    "selection": {
        "saved_sets": {},
    },
}

ILLEGAL_CHARS = u'<>:"/\\|?*'
RESERVED_NAMES = set(
    ["CON", "PRN", "AUX", "NUL"]
    + ["COM%d" % i for i in range(1, 10)]
    + ["LPT%d" % i for i in range(1, 10)]
)
MAX_PATH = 259          # Windows MAX_PATH (260) minus the terminating NUL
MIN_NAME_LEN = 8        # never truncate a name shorter than this

DATE_TOKENS = ["YYYY", "YY", "Y", "mm", "m", "dd", "d", "HH", "H", "MM", "M", "SS", "S"]
NAMED_TOKENS = ["UserName", "DrawingName", "IssueDate", "ProjectNumber",
                "ProjectName", "ModelName", "Date", "Time"]


def default_settings():
    return copy.deepcopy(DEFAULT_SETTINGS)


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------
def to_text(value):
    """Any value -> text, never raises, None -> ''."""
    if value is None:
        return u""
    if isinstance(value, _TEXT_TYPES):
        return value
    try:
        return u"%s" % (value,)
    except Exception:
        return u""


def natural_key(text):
    """Sort key so A-2 < A-10 and case is ignored."""
    parts = re.split(r"(\d+)", to_text(text).lower())
    key = []
    for p in parts:
        if p.isdigit():
            key.append((0, int(p), p))
        else:
            key.append((1, 0, p))
    return key


def sanitize_component(text, replace_char=u"_"):
    """Make one path component (file or folder name) legal on Windows."""
    rc = to_text(replace_char)
    if rc and (any(c in ILLEGAL_CHARS for c in rc) or any(ord(c) < 32 for c in rc)):
        rc = u"_"
    out = []
    for ch in to_text(text):
        if ch in ILLEGAL_CHARS or ord(ch) < 32:
            out.append(rc)
        else:
            out.append(ch)
    s = u"".join(out)
    s = re.sub(r"\s+", u" ", s).strip()
    s = s.rstrip(u". ")
    if s.split(u".")[0].upper() in RESERVED_NAMES:
        s = u"_" + s
    return s


# ---------------------------------------------------------------------------
# Path tokens (ProSheets-compatible syntax)
# ---------------------------------------------------------------------------
def _date_value(token, now):
    return {
        "YYYY": "%04d" % now.year,
        "YY": "%02d" % (now.year % 100),
        "Y": "%04d" % now.year,
        "mm": "%02d" % now.month,
        "m": "%d" % now.month,
        "dd": "%02d" % now.day,
        "d": "%d" % now.day,
        "HH": "%02d" % now.hour,
        "H": "%d" % now.hour,
        "MM": "%02d" % now.minute,
        "M": "%d" % now.minute,
        "SS": "%02d" % now.second,
        "S": "%d" % now.second,
    }[token]


def expand_tokens(text, named=None, env=None, now=None, replace_char=u"_"):
    """Expand %Named% tokens, %ENVVAR% and ProSheets date tokens (%YYYY, %mm ...).

    Scans left to right so a Windows variable such as %HOMEPATH% is never
    mistaken for the %H (hour) token. Values substituted from tokens are
    sanitised (an Issue Date like 11/10/2026 must not create sub-folders);
    the literal text the user typed (e.g. C:\\Projects) is left alone.
    """
    text = to_text(text)
    now = now or datetime.datetime.now()
    named_ci = {}
    for k, v in (named or {}).items():
        named_ci[k.lower()] = to_text(v)
    env_ci = {}
    for k, v in (os.environ if env is None else env).items():
        env_ci[to_text(k).upper()] = to_text(v)

    out = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch != u"%":
            out.append(ch)
            i += 1
            continue
        # 1) %Name% form
        close = text.find(u"%", i + 1)
        if close > i + 1:
            name = text[i + 1:close]
            if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
                if name.lower() in named_ci:
                    out.append(sanitize_component(named_ci[name.lower()], replace_char))
                    i = close + 1
                    continue
                if name.upper() in env_ci:
                    out.append(env_ci[name.upper()])
                    i = close + 1
                    continue
        # 2) date token, longest first
        matched = False
        for tok in DATE_TOKENS:
            if text.startswith(tok, i + 1):
                out.append(_date_value(tok, now))
                i += 1 + len(tok)
                matched = True
                break
        if matched:
            continue
        out.append(ch)
        i += 1
    return u"".join(out)


# ---------------------------------------------------------------------------
# File naming
# ---------------------------------------------------------------------------
def field_key(source, name):
    return u"%s|%s" % (to_text(source).lower(), to_text(name))


def build_name(naming, values, fields=None, fallback=u"Unnamed"):
    """Compose a file name (no extension) from the naming rule.

    naming : the settings["naming"] dict
    values : dict field_key -> text for one sheet/view
    fields : override field list (views use naming["view_fields"])
    """
    fields = naming.get("fields", []) if fields is None else fields
    skip_empty = naming.get("skip_empty", True)
    rc = naming.get("replace_char", u"_")
    parts = []
    for f in fields:
        src = to_text(f.get("source", "")).lower()
        if src == "text":
            val = to_text(f.get("name", u""))
        else:
            val = to_text(values.get(field_key(src, f.get("name", u"")), u"")).strip()
        if not val and skip_empty:
            continue
        parts.append((val, to_text(f.get("sep", u""))))
    body = u""
    for idx, (val, sep) in enumerate(parts):
        body += val
        if idx < len(parts) - 1:
            body += sep
    name = to_text(naming.get("prefix", u"")) + body + to_text(naming.get("suffix", u""))
    name = sanitize_component(name, rc)
    return name or sanitize_component(fallback, rc) or u"Unnamed"


# ---------------------------------------------------------------------------
# Paper size
# ---------------------------------------------------------------------------
PAPER_SIZES_MM = [
    ("A0", 1189, 841), ("A1", 841, 594), ("A2", 594, 420), ("A3", 420, 297),
    ("A4", 297, 210), ("B1", 1000, 707), ("B2", 707, 500),
    ("ARCH E", 1219, 914), ("ARCH D", 914, 610),
    ("ANSI E", 1118, 864), ("ANSI D", 864, 559), ("ANSI C", 559, 432),
    ("ANSI B", 432, 279),
]


def detect_paper(width_mm, height_mm, tol=3.0):
    """Return (size label, orientation) from title block dimensions in mm."""
    try:
        w = float(width_mm)
        h = float(height_mm)
    except (TypeError, ValueError):
        return u"", u""
    if w <= 0 or h <= 0:
        return u"", u""
    orient = u"Landscape" if w >= h else u"Portrait"
    big, small = max(w, h), min(w, h)
    for label, a, b in PAPER_SIZES_MM:
        if abs(big - a) <= tol and abs(small - b) <= tol:
            return to_text(label), orient
    return u"Custom %dx%d" % (int(round(w)), int(round(h))), orient


# ---------------------------------------------------------------------------
# Settings persistence
# ---------------------------------------------------------------------------
def _merge(defaults, loaded):
    """Deep merge, keeping default types (a corrupt value never reaches Revit)."""
    if not isinstance(loaded, dict):
        return copy.deepcopy(defaults)
    out = {}
    for key, dval in defaults.items():
        if key not in loaded:
            out[key] = copy.deepcopy(dval)
            continue
        lval = loaded[key]
        if isinstance(dval, dict):
            if key == "saved_sets":
                out[key] = _clean_sets(lval)
            else:
                out[key] = _merge(dval, lval)
        elif isinstance(dval, bool):
            out[key] = lval if isinstance(lval, bool) else dval
        elif isinstance(dval, (int, float)) and not isinstance(dval, bool):
            if isinstance(lval, (int, float)) and not isinstance(lval, bool):
                out[key] = lval
            else:
                out[key] = dval
        elif isinstance(dval, _TEXT_TYPES):
            out[key] = lval if isinstance(lval, _TEXT_TYPES) else dval
        elif isinstance(dval, list):
            out[key] = _clean_fields(lval) if key in ("fields", "view_fields") else dval
        else:
            out[key] = copy.deepcopy(dval)
    return out


def _clean_fields(lval):
    if not isinstance(lval, list):
        return []
    out = []
    for f in lval:
        if isinstance(f, dict) and isinstance(f.get("name"), _TEXT_TYPES):
            out.append({
                "source": to_text(f.get("source", "sheet")) or u"sheet",
                "name": to_text(f.get("name")),
                "sep": to_text(f.get("sep", u"")),
            })
    return out


def _clean_sets(lval):
    if not isinstance(lval, dict):
        return {}
    out = {}
    for k, v in lval.items():
        if isinstance(k, _TEXT_TYPES) and isinstance(v, list):
            out[k] = [to_text(x) for x in v if isinstance(x, _TEXT_TYPES)]
    return out


def validate_settings(s):
    """Clamp enumerated values; returns the same dict for chaining."""
    p = s["pdf"]
    if p["orientation"] not in PDF_ORIENTATIONS:
        p["orientation"] = "Auto"
    if p["color"] not in PDF_COLORS:
        p["color"] = "Color"
    if p["raster_quality"] not in PDF_RASTER:
        p["raster_quality"] = "High"
    if p["dpi"] not in PDF_DPI:
        p["dpi"] = "DPI300"
    if p["placement"] not in ("Center", "LowerLeft"):
        p["placement"] = "Center"
    if p["output_mode"] not in PDF_OUTPUT_MODES:
        p["output_mode"] = "separate"
    if p["combine_order"] not in COMBINE_ORDERS:
        p["combine_order"] = "list"
    try:
        p["zoom_percent"] = max(10, min(500, int(p["zoom_percent"])))
    except (TypeError, ValueError):
        p["zoom_percent"] = 100
    try:
        s["output"]["batch_size"] = max(1, min(100, int(s["output"]["batch_size"])))
    except (TypeError, ValueError):
        s["output"]["batch_size"] = 10
    if s["output"]["existing"] not in EXISTING_POLICIES:
        s["output"]["existing"] = "overwrite"
    if s["mode"] not in ("sheets", "views"):
        s["mode"] = "sheets"
    return s


def load_settings(path):
    """Load settings JSON; any problem -> defaults (never raises)."""
    try:
        if path and os.path.isfile(path):
            with io.open(path, "r", encoding="utf-8-sig") as fh:
                data = json.loads(fh.read())
            return validate_settings(_merge(DEFAULT_SETTINGS, data))
    except Exception:
        pass
    return default_settings()


def save_settings(path, settings):
    """Atomic save: the previous file is only replaced after the new one is verified."""
    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    text = json.dumps(settings, indent=2, sort_keys=True, ensure_ascii=False)
    if isinstance(text, bytes) and not isinstance(text, type(u"")):
        text = text.decode("utf-8")          # CPython 2 returns str for ASCII-only output
    tmp = path + ".tmp"
    bak = path + ".bak"
    with io.open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    with io.open(tmp, "r", encoding="utf-8") as fh:
        json.loads(fh.read())                 # verify before swapping
    had_old = os.path.isfile(path)
    if had_old:
        if os.path.isfile(bak):
            os.remove(bak)
        os.rename(path, bak)
    try:
        os.rename(tmp, path)
    except Exception:
        if had_old and os.path.isfile(bak) and not os.path.isfile(path):
            os.rename(bak, path)
        raise
    if had_old and os.path.isfile(bak):
        try:
            os.remove(bak)
        except Exception:
            pass
    return True


# ---------------------------------------------------------------------------
# Export plan
# ---------------------------------------------------------------------------
class Job(object):
    """One file to produce."""

    def __init__(self, fmt, folder, name, ext, item_ids, label, number=u"", title=u"", kind=u"sheet"):
        self.fmt = fmt              # "pdf" | "pdf_combined" | "dwg"
        self.folder = folder
        self.name = name            # without extension
        self.ext = ext
        self.item_ids = list(item_ids)
        self.label = label
        self.number = number        # sheet number (used to match batch-exported files)
        self.title = title          # sheet / view name
        self.kind = kind            # "sheet" | "view" | "set"
        self.status = "pending"     # pending | running | ok | failed | skipped | cancelled
        self.message = u""
        self.warnings = []
        self.seconds = None         # time this file took (batched files share the call time)

    @property
    def path(self):
        return ntpath.join(self.folder, self.name + self.ext)

    def __repr__(self):
        return "<Job %s %s %s>" % (self.fmt, self.status, self.path)


def _unique_name(name, ext, folder, taken):
    """Resolve collisions inside this run (case-insensitive, like Windows)."""
    candidate = name
    k = 2
    while ntpath.join(folder, candidate + ext).lower() in taken:
        candidate = u"%s (%d)" % (name, k)
        k += 1
    return candidate


def _apply_existing(job, policy, exists):
    if not exists(job.path):
        return
    if policy == "skip":
        job.status = "skipped"
        job.message = u"File already exists (skip policy)."
    elif policy == "increment":
        base = job.name
        k = 2
        while exists(job.path):
            job.name = u"%s (%d)" % (base, k)
            k += 1
    # overwrite: the runner deletes the old file right before exporting


def _fit_path(job):
    """Keep the full path under Windows MAX_PATH by trimming the file name."""
    over = len(job.path) - MAX_PATH
    if over <= 0:
        return
    keep = len(job.name) - over
    if keep >= MIN_NAME_LEN:
        job.name = job.name[:keep].rstrip(u". ")
        job.warnings.append(u"Name shortened to fit the Windows 260-character path limit.")
    else:
        job.status = "failed"
        job.message = (u"Export folder path is too long for Windows (%d characters). "
                       u"Choose a shorter export folder." % len(job.path))


def item_named_tokens(item, project):
    return {
        "DrawingName": item.get("number") or item.get("name", u""),
        "IssueDate": item.get("issue_date", u""),
        "ProjectNumber": project.get("number", u""),
        "ProjectName": project.get("name", u""),
        "ModelName": project.get("model", u""),
        "UserName": project.get("user", u""),
    }


def plan_jobs(items, settings, project, now=None, exists=None, env=None):
    """Build the ordered list of Jobs.

    items   : list of dicts {id, uid, number, name, values, issue_date, kind}
              in the order they should be exported (the dialog's order)
    project : dict {number, name, model, user}
    """
    now = now or datetime.datetime.now()
    exists = exists or os.path.exists
    s = settings
    out = s["output"]
    naming = s["naming"]
    rc = naming.get("replace_char", u"_")
    fmts = s["formats"]
    pdf_mode = s["pdf"]["output_mode"]
    fields = naming["view_fields"] if s["mode"] == "views" else naming["fields"]

    taken = set()
    jobs = []

    def folder_for(fmt, item):
        named = item_named_tokens(item, project) if item else item_named_tokens({}, project)
        named["Date"] = now.strftime("%Y-%m-%d")
        named["Time"] = now.strftime("%H%M")
        root = expand_tokens(out["root"], named, env, now, rc).strip()
        root = root.rstrip(u"\\/") if len(root) > 3 else root
        if out.get("split_by_format", True):
            sub = out["pdf_subfolder"] if fmt.startswith("pdf") else out["dwg_subfolder"]
            sub = sanitize_component(sub, rc)
            if sub:
                return ntpath.join(root, sub)
        return root

    def add(fmt, ext, item_ids, item, name, label):
        folder = folder_for(fmt, item)
        name = _unique_name(name, ext, folder, taken)
        if item:
            job = Job(fmt, folder, name, ext, item_ids, label, to_text(item.get("number", u"")),
                      to_text(item.get("name", u"")), item.get("kind", u"sheet"))
        else:
            job = Job(fmt, folder, name, ext, item_ids, label, u"", label, u"set")
        _fit_path(job)
        if job.status == "pending":
            _apply_existing(job, out["existing"], exists)
            # increment may have changed the name: keep it unique within the run
            if job.status == "pending":
                job.name = _unique_name(job.name, ext, folder, taken)
        taken.add(job.path.lower())
        jobs.append(job)
        return job

    names = {}
    for it in items:
        names[it["id"]] = build_name(naming, it.get("values", {}), fields,
                                     fallback=it.get("number") or it.get("name") or u"Unnamed")

    if fmts.get("pdf") and pdf_mode in ("separate", "both"):
        for it in items:
            add("pdf", u".pdf", [it["id"]], it, names[it["id"]], _label(it))
    if fmts.get("pdf") and pdf_mode in ("combined", "both") and items:
        ordered = order_items(items, s["pdf"]["combine_order"])
        named = item_named_tokens({}, project)
        named["Date"] = now.strftime("%Y-%m-%d")
        named["Time"] = now.strftime("%H%M")
        cname = sanitize_component(
            expand_tokens(s["pdf"]["combined_name"], named, env, now, rc), rc) or u"Combined"
        add("pdf_combined", u".pdf", [it["id"] for it in ordered], None, cname,
            u"Combined PDF (%d)" % len(ordered))
    if fmts.get("dwg"):
        for it in items:
            add("dwg", u".dwg", [it["id"]], it, names[it["id"]], _label(it))
    return jobs


def _label(item):
    num = to_text(item.get("number", u""))
    nm = to_text(item.get("name", u""))
    return (num + u" - " + nm) if num else nm


def order_items(items, order):
    if order == "number":
        return sorted(items, key=lambda it: natural_key(it.get("number", u"")))
    if order == "name":
        return sorted(items, key=lambda it: natural_key(it.get("name", u"")))
    return list(items)


def summarize(jobs):
    counts = {"ok": 0, "failed": 0, "skipped": 0, "cancelled": 0, "pending": 0}
    for j in jobs:
        counts[j.status] = counts.get(j.status, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Matching batch-exported files back to sheets
# ---------------------------------------------------------------------------
BATCH_PREFIX = u"dlcx"     # DWG batch file-name prefix (Revit appends '-Sheet - <no> - <name>')


def _norm(text):
    return u"".join(ch for ch in to_text(text).lower() if ch.isalnum())


def _candidates(stem, by_norm):
    hit = by_norm.get(_norm(stem))                  # tier 1: stem == sheet number
    if hit:
        return list(hit)
    low = stem.lower()
    if low.startswith(BATCH_PREFIX):
        stem = stem[len(BATCH_PREFIX):]
        low = stem.lower()
    pos = low.find(u"sheet - ")                     # tier 2: '...Sheet - <no> - <name>'
    if pos < 0:
        return []
    parts = stem[pos + len(u"sheet - "):].split(u" - ")
    found = []
    for k in range(1, len(parts) + 1):
        for j in by_norm.get(_norm(u" - ".join(parts[:k])), []):
            if j not in found:
                found.append(j)
    return found


def match_files(file_names, jobs):
    """Map files Revit produced in one batch call to their jobs.

    Returns {file name: job} for unambiguous matches only. A file with two
    candidate sheets, or a sheet claimed by two files, is left out; the
    caller re-exports those one by one - a wrong match is never possible,
    at worst the batch is slower.
    """
    by_norm = {}
    for j in jobs:
        key = _norm(j.number)
        if key:
            by_norm.setdefault(key, []).append(j)
    pairs = {}
    claims = {}
    for f in file_names:
        cands = _candidates(to_text(f).rsplit(u".", 1)[0], by_norm)
        if len(cands) == 1:
            pairs[f] = cands[0]
            claims[id(cands[0])] = claims.get(id(cands[0]), 0) + 1
    return dict((f, j) for f, j in pairs.items() if claims[id(j)] == 1)

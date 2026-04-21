# -*- coding: utf-8 -*-
"""
Import Shafts From Excel
========================
Reads a Shaft Data .xlsx file (produced by the companion Export script) and
overwrites the matching Shaft Opening elements using Shaft ID as the key.

NO openpyxl required — xlsx is parsed using System.IO.Compression (ZipArchive)
+ System.Xml (XmlDocument), both always available in Revit's .NET runtime.

Fields written back:
    • Base Constraint   (level lookup by name)
    • Base Offset       (mm → internal feet)
    • Top Constraint    (level lookup by name)
    • Top Offset        (mm → internal feet)
    • Shaft Function    (custom string parameter)
    • Workset           (worksharing-aware)

NOTE: Total Height is read-only in Revit and is intentionally skipped.

pyRevit | IronPython 2.7
"""

# ── CLR / .NET ────────────────────────────────────────────────────────────────
import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("System.Windows.Forms")
clr.AddReference("System.IO.Compression")
clr.AddReference("System.Xml")

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    FilteredWorksetCollector,
    BuiltInCategory,
    BuiltInParameter,
    Transaction,
    WorksetKind,
)
from System.Windows.Forms import (
    OpenFileDialog, DialogResult,
    MessageBox, MessageBoxButtons, MessageBoxIcon,
)
from System.IO.Compression import ZipArchive, ZipArchiveMode
from System.IO   import File, FileMode, FileAccess, StreamReader
from System.Text import Encoding
from System.Xml  import XmlDocument, XmlNamespaceManager

from pyrevit import script

output = script.get_output()
output.close_others()
doc = __revit__.ActiveUIDocument.Document


# ═════════════════════════════════════════════════════════════════════════════
#  XLSX READER  (System.IO.Compression + System.Xml — zero external deps)
# ═════════════════════════════════════════════════════════════════════════════

_XLSX_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def _read_zip_entry_text(za, entry_name):
    """Return the text content of a zip entry, or None if not found."""
    entry = za.GetEntry(entry_name)
    if entry is None:
        return None
    sr = StreamReader(entry.Open(), Encoding.UTF8)
    try:
        return sr.ReadToEnd()
    finally:
        sr.Close()


def _parse_xml(text):
    """Parse an XML string into an XmlDocument with the xlsx namespace registered."""
    xd = XmlDocument()
    xd.LoadXml(text)
    nm = XmlNamespaceManager(xd.NameTable)
    nm.AddNamespace("x", _XLSX_NS)
    return xd, nm


def _col_letters_to_index(letters):
    """Excel column letters → 1-based integer.  A=1, Z=26, AA=27 …"""
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - 64)
    return n


def _split_cell_ref(ref):
    """'C5' → ('C', 5).  Returns (None, None) on bad input."""
    letters, digits = u"", u""
    for ch in ref:
        if ch.isdigit():
            digits += ch
        else:
            letters += ch
    if letters and digits:
        return letters, int(digits)
    return None, None


def read_xlsx_first_sheet(filepath):
    """
    Read the first worksheet of *filepath*.
    Returns a list of row-lists (first row = headers).
    Numeric cells → int / float.  Everything else → unicode string.
    """
    fs = File.Open(filepath, FileMode.Open, FileAccess.Read)
    za = None
    try:
        za = ZipArchive(fs, ZipArchiveMode.Read, False)

        # ── 1. Shared strings (all text values are stored here) ───────────────
        shared = []
        ss_text = _read_zip_entry_text(za, "xl/sharedStrings.xml")
        if ss_text:
            ss_doc, ss_nm = _parse_xml(ss_text)
            for si_node in ss_doc.SelectNodes("//x:si", ss_nm):
                parts = si_node.SelectNodes(".//x:t", ss_nm)
                shared.append(u"".join(p.InnerText for p in parts))

        # ── 2. Worksheet XML ──────────────────────────────────────────────────
        ws_text = _read_zip_entry_text(za, "xl/worksheets/sheet1.xml")
        if not ws_text:
            return []
        ws_doc, ws_nm = _parse_xml(ws_text)

        all_rows = []
        for row_node in ws_doc.SelectNodes("//x:row", ws_nm):
            sparse = {}   # col_index (1-based) → value

            for c_node in row_node.SelectNodes("x:c", ws_nm):
                ref = c_node.GetAttribute("r")
                col_letters, _ = _split_cell_ref(ref)
                if col_letters is None:
                    continue
                col = _col_letters_to_index(col_letters)

                ctype  = c_node.GetAttribute("t")
                v_node = c_node.SelectSingleNode("x:v", ws_nm)

                if v_node is None:
                    sparse[col] = None
                    continue

                raw = v_node.InnerText

                if ctype == "s":                   # index into shared strings
                    try:
                        idx = int(raw)
                        sparse[col] = shared[idx] if idx < len(shared) else u""
                    except (ValueError, IndexError):
                        sparse[col] = raw
                elif ctype == "inlineStr":
                    t_node = c_node.SelectSingleNode(".//x:t", ws_nm)
                    sparse[col] = t_node.InnerText if t_node else u""
                elif ctype in ("b", "str", "e"):   # bool / formula / error
                    sparse[col] = raw
                else:                              # plain number
                    try:
                        sparse[col] = int(raw) if u"." not in raw else float(raw)
                    except ValueError:
                        sparse[col] = raw

            if sparse:
                max_col   = max(sparse.keys())
                dense_row = [sparse.get(c) for c in range(1, max_col + 1)]
                all_rows.append(dense_row)

        return all_rows

    finally:
        if za is not None:
            za.Dispose()   # leaveOpen=False → also closes fs


# ═════════════════════════════════════════════════════════════════════════════
#  REVIT LOOKUP MAPS
# ═════════════════════════════════════════════════════════════════════════════

def _build_level_map():
    levels = (FilteredElementCollector(doc)
              .OfCategory(BuiltInCategory.OST_Levels)
              .WhereElementIsNotElementType()
              .ToElements())
    return {lv.Name.strip().lower(): lv for lv in levels}


def _build_workset_map():
    if not doc.IsWorkshared:
        return {}
    result = {}
    for ws in FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset):
        result[ws.Name.strip().lower()] = ws.Id
    return result


LEVEL_MAP   = _build_level_map()
WORKSET_MAP = _build_workset_map()

SHAFT_MAP = {
    s.Id.IntegerValue: s
    for s in (FilteredElementCollector(doc)
              .OfCategory(BuiltInCategory.OST_ShaftOpening)
              .WhereElementIsNotElementType()
              .ToElements())
}

if not SHAFT_MAP:
    MessageBox.Show(
        "No Shaft Opening elements found in the active document.",
        "No Shafts", MessageBoxButtons.OK, MessageBoxIcon.Warning,
    )
    import sys; sys.exit(0)


# ═════════════════════════════════════════════════════════════════════════════
#  PARAMETER SETTERS
#  Every setter catches exceptions from p.Set() and returns (ok, message)
#  so that a bad Set() never propagates up and silently rolls back the
#  entire transaction.
# ═════════════════════════════════════════════════════════════════════════════

def _set_level(shaft, bip, raw_name):
    """Set a level-constraint BuiltInParameter. Returns (ok, message)."""
    if raw_name is None:
        return False, "No value in Excel"

    key = unicode(raw_name).strip().lower()
    if key in ("n/a", "unconnected", ""):
        return True, "Skipped (Unconnected / N/A)"

    lv = LEVEL_MAP.get(key)
    if lv is None:
        return False, u"Level '{0}' not found in project".format(raw_name)

    p = shaft.get_Parameter(bip)
    if p is None:
        return False, "Parameter not found on element"
    if p.IsReadOnly:
        return False, "Parameter is read-only"

    try:
        p.Set(lv.Id)
        return True, u"→ {0}".format(lv.Name)
    except Exception as ex:
        return False, u"Set() failed: {0}".format(str(ex))


def _set_offset(shaft, bip, mm_val):
    """Set a Double offset parameter (value supplied in mm). Returns (ok, message)."""
    if mm_val is None:
        return False, "No value in Excel"

    try:
        feet = float(mm_val) / 304.8
    except (TypeError, ValueError):
        return False, u"Non-numeric value '{0}'".format(mm_val)

    p = shaft.get_Parameter(bip)
    if p is None:
        return False, "Parameter not found on element"
    if p.IsReadOnly:
        return False, "Parameter is read-only"

    try:
        p.Set(feet)
        return True, u"→ {0} mm".format(mm_val)
    except Exception as ex:
        return False, u"Set() failed: {0}".format(str(ex))


def _set_string(shaft, param_name, val):
    """Set a custom String parameter by name. Returns (ok, message)."""
    if val is None:
        return True, "No value — skipped"

    p = shaft.LookupParameter(param_name)
    if p is None:
        return False, u"Parameter '{0}' not found on element".format(param_name)
    if p.IsReadOnly:
        return False, u"Parameter '{0}' is read-only".format(param_name)

    try:
        p.Set(unicode(val))
        return True, u"→ {0}".format(val)
    except Exception as ex:
        return False, u"Set() failed: {0}".format(str(ex))


def _set_workset(shaft, raw_name):
    """Move element to named workset. Returns (ok, message)."""
    if not doc.IsWorkshared:
        return True, "Skipped (project not workshared)"
    if raw_name is None:
        return True, "No value — skipped"

    key = unicode(raw_name).strip().lower()
    if "n/a" in key or key == "":
        return True, "Skipped (N/A)"

    ws_id = WORKSET_MAP.get(key)
    if ws_id is None:
        return False, u"Workset '{0}' not found in project".format(raw_name)

    p = shaft.get_Parameter(BuiltInParameter.ELEM_PARTITION_PARAM)
    if p is None:
        return False, "Workset parameter not found on element"
    if p.IsReadOnly:
        return False, "Workset parameter is read-only (element may be owned by another user)"

    try:
        p.Set(ws_id.IntegerValue)
        return True, u"→ {0}".format(raw_name)
    except Exception as ex:
        return False, u"Set() failed: {0}".format(str(ex))


# ═════════════════════════════════════════════════════════════════════════════
#  FILE DIALOG
# ═════════════════════════════════════════════════════════════════════════════

dlg             = OpenFileDialog()
dlg.Title       = "Select Shaft Data Excel File"
dlg.Filter      = "Excel Workbook (*.xlsx)|*.xlsx"
dlg.Multiselect = False

if dlg.ShowDialog() != DialogResult.OK:
    output.print_md("**Import cancelled.**")
    import sys; sys.exit(0)

xlsx_path = dlg.FileName

# ═════════════════════════════════════════════════════════════════════════════
#  READ XLSX
# ═════════════════════════════════════════════════════════════════════════════

try:
    all_rows = read_xlsx_first_sheet(xlsx_path)
except Exception as ex:
    MessageBox.Show(
        "Failed to read Excel file:\n{0}".format(str(ex)),
        "Read Error", MessageBoxButtons.OK, MessageBoxIcon.Error,
    )
    import sys; sys.exit(1)

if not all_rows:
    MessageBox.Show("Excel file appears empty.", "Empty File",
                    MessageBoxButtons.OK, MessageBoxIcon.Warning)
    import sys; sys.exit(0)

# ── Header → column index map ─────────────────────────────────────────────────
# NOTE: use explicit `is not None` check — _col() can legitimately return 0
#       (first column), which is falsy, so `x or y` would wrongly skip it.

header_row = [unicode(h).strip().lower() if h is not None else u""
              for h in all_rows[0]]
data_rows  = all_rows[1:]


def _col(keyword):
    """Return the 0-based column index whose header contains *keyword*, or None."""
    for i, h in enumerate(header_row):
        if keyword in h:
            return i
    return None


IDX_ID       = _col("shaft id")
IDX_ID       = _col("id")        if IDX_ID       is None else IDX_ID
IDX_BASE_CON = _col("base constraint")
IDX_BASE_OFF = _col("base offset")
IDX_TOP_CON  = _col("top constraint")
IDX_TOP_OFF  = _col("top offset")
IDX_FUNC     = _col("shaft function")
IDX_FUNC     = _col("function")   if IDX_FUNC     is None else IDX_FUNC
IDX_WS       = _col("workset")

if IDX_ID is None:
    MessageBox.Show(
        "Could not find a 'Shaft ID' column in the Excel file.\n"
        "Please use the file produced by the Export script.",
        "Column Missing", MessageBoxButtons.OK, MessageBoxIcon.Error,
    )
    import sys; sys.exit(1)

if not data_rows:
    MessageBox.Show("No data rows found (header only).", "No Data",
                    MessageBoxButtons.OK, MessageBoxIcon.Warning)
    import sys; sys.exit(0)


def _cell(row, idx):
    """Safe cell getter; returns None if idx is None or out of range."""
    if idx is None or idx >= len(row):
        return None
    return row[idx]


# ═════════════════════════════════════════════════════════════════════════════
#  APPLY CHANGES  —  explicit transaction (no 'with' block)
#
#  Using 'with Transaction(...) as t' + t.Start() + t.Commit() is unsafe:
#  if any p.Set() throws, Python skips t.Commit(), exits the 'with' block,
#  IronPython calls Dispose() on the still-open transaction, and Revit
#  silently rolls back every change without showing an error.
#
#  The explicit pattern below ensures RollBack() is only called on failure
#  and Commit() is always attempted when the loop finishes cleanly.
# ═════════════════════════════════════════════════════════════════════════════

successes = []   # (shaft_id, field_notes_str)
failures  = []   # (shaft_id, error_str)
skipped   = []   # (shaft_id, reason_str)

t = Transaction(doc, "Import Shaft Data from Excel")
t.Start()

try:
    for raw_row in data_rows:
        if all(c is None for c in raw_row):
            continue   # skip entirely blank rows

        # ── Resolve Shaft ID ──────────────────────────────────────────────────
        raw_id = _cell(raw_row, IDX_ID)
        if raw_id is None:
            failures.append(("?", "Shaft ID cell is empty"))
            continue
        try:
            shaft_id = int(raw_id)
        except (ValueError, TypeError):
            failures.append((unicode(raw_id), "Shaft ID is not an integer"))
            continue

        shaft = SHAFT_MAP.get(shaft_id)
        if shaft is None:
            skipped.append((shaft_id, "Element ID not found in active document"))
            continue

        field_results = []   # (field_name, ok, message)

        # ── Base Constraint ───────────────────────────────────────────────────
        ok, msg = _set_level(shaft, BuiltInParameter.WALL_BASE_CONSTRAINT,
                             _cell(raw_row, IDX_BASE_CON))
        field_results.append(("Base Constraint", ok, msg))

        # ── Base Offset ───────────────────────────────────────────────────────
        ok, msg = _set_offset(shaft, BuiltInParameter.WALL_BASE_OFFSET,
                              _cell(raw_row, IDX_BASE_OFF))
        field_results.append(("Base Offset", ok, msg))

        # ── Top Constraint ────────────────────────────────────────────────────
        ok, msg = _set_level(shaft, BuiltInParameter.WALL_HEIGHT_TYPE,
                             _cell(raw_row, IDX_TOP_CON))
        field_results.append(("Top Constraint", ok, msg))

        # ── Top Offset ────────────────────────────────────────────────────────
        ok, msg = _set_offset(shaft, BuiltInParameter.WALL_TOP_OFFSET,
                              _cell(raw_row, IDX_TOP_OFF))
        field_results.append(("Top Offset", ok, msg))

        # ── Shaft Function ────────────────────────────────────────────────────
        ok, msg = _set_string(shaft, "Shaft Function", _cell(raw_row, IDX_FUNC))
        field_results.append(("Shaft Function", ok, msg))

        # ── Workset ───────────────────────────────────────────────────────────
        ok, msg = _set_workset(shaft, _cell(raw_row, IDX_WS))
        field_results.append(("Workset", ok, msg))

        # ── Classify row ──────────────────────────────────────────────────────
        errors = ["{0}: {1}".format(f, m) for f, ok, m in field_results if not ok]
        notes  = ["{0}: {1}".format(f, m) for f, ok, m in field_results if ok and m != "No value — skipped"]

        if errors:
            failures.append((shaft_id, u" | ".join(errors)))
        else:
            successes.append((shaft_id, u" | ".join(notes) if notes else "All fields updated"))

    t.Commit()

except Exception as ex:
    # Something unexpected went wrong — roll back so the model stays clean
    if t.HasStarted() and not t.HasEnded():
        t.RollBack()
    MessageBox.Show(
        "An unexpected error occurred and all changes were rolled back:\n\n{0}".format(str(ex)),
        "Transaction Error", MessageBoxButtons.OK, MessageBoxIcon.Error,
    )
    import sys; sys.exit(1)


# ═════════════════════════════════════════════════════════════════════════════
#  FINAL REPORT
# ═════════════════════════════════════════════════════════════════════════════

n_ok   = len(successes)
n_fail = len(failures)
n_skip = len(skipped)
total  = len(data_rows)

output.print_md("# Shaft Import Report")
output.print_md("**Source:** `{0}`".format(xlsx_path))
output.print_md("---")
output.print_md(
    u"| | |\n|---|---|\n"
    u"| Rows in Excel | **{0}** |\n"
    u"| ✅ Updated | **{1}** |\n"
    u"| ❌ Failed | **{2}** |\n"
    u"| ⚠️ Not found in model | **{3}** |"
    .format(total, n_ok, n_fail, n_skip)
)

if successes:
    output.print_md(u"\n## ✅ Updated ({0})".format(n_ok))
    for sid, notes in successes:
        output.print_md(u"- **ID {0}** — {1}".format(sid, notes))

if failures:
    output.print_md(u"\n## ❌ Failures ({0})".format(n_fail))
    for sid, reason in failures:
        output.print_md(u"- **ID {0}** — {1}".format(sid, reason))

if skipped:
    output.print_md(u"\n## ⚠️ Not Found in Model ({0})".format(n_skip))
    for sid, reason in skipped:
        output.print_md(u"- **ID {0}** — {1}".format(sid, reason))

output.print_md(u"\n---\n*Import complete.*")
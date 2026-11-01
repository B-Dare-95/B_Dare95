# -*- coding: utf-8 -*-
"""SDC - Create Sheets
Creates sheets from an Excel workbook. Self-contained (no Excel / no openpyxl needed -
reads the .xlsx directly). Dry-run rolls everything back for a safe preview.

PER ROW
  * Sheet Number = Master + Partial            e.g. 003a
  * Sheet Name   = Name                         (keep this identical to the View Name)
  * Writes the 3 segment shared parameters on the sheet:
        SDC_BUILDING_ASSET_CODE, SDC_DISCIPLINE_CODE, SDC_Sheet_Level
  * Assigns the title block named in the Title Block column (optional)

FULL DRAWING NUMBER is assembled by the title-block labels, in this order:
  Project Number - Author - Project Status - Building - Discipline - Level - <Sheet Number>
  (the first three are standard Project Information params; the last is the built-in
   Sheet Number, which already equals Master+Partial.)

Add the 3 shared parameters first (SDC_Sheet_Params.txt), bound to Sheets, then run this.

Author: Sedki Sustainable Architecture
"""

__title__ = "Create\nSheets"
__author__ = "Sedki"

import os
import csv
import datetime
from pyrevit import revit, DB, forms, script

doc = revit.doc
uidoc = revit.uidoc
out = script.get_output()

try:
    text_type = unicode  # noqa
except NameError:
    text_type = str

# ---- workbook column headers ----
# Full number:  Project Number - Originator - Phase - Building - Discipline - Level - Series - Partial
#   Project Number / Originator / Phase  ->  read from Project Information (title-block prefix)
#   Building / Discipline / Level / Series / Partial  ->  these workbook columns
C_BUILDING = "Building"
C_DISC     = "Discipline"
C_LEVEL    = "Level"
C_SERIES   = "Series"        # was "Master"; "Master" still accepted as an alias
C_PARTIAL  = "Partial"
C_NAME     = "Name"
C_TB       = "Title Block"

# ---- target shared parameters on the sheet ----
P_BUILDING = "SDC_BUILDING_ASSET_CODE"
P_DISC     = "SDC_DISCIPLINE_CODE"
P_LEVEL    = "SDC_Sheet_Level"

PLACEHOLDER_NUMBER = "0000"   # the sheet targeted by the "Delete sheet number 0000" option

GREEN = "#1b4332"; BLUE = "#0a6e8c"; GOLD = "#b08968"; RED = "#9b2226"; GREY = "#6c757d"
_MISSING = set()


def _t(v):
    return "" if v is None else text_type(v).strip()


# ---------------------------------------------------------------- xlsx reader
def _local(tag):
    return tag.split("}")[-1]


def _col_index(ref):
    letters = ""
    for ch in ref:
        if ch.isalpha():
            letters += ch
        else:
            break
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch.upper()) - ord("A") + 1)
    return n - 1 if n else 0


def _rows_to_dicts(rows):
    rows = [r for r in rows]
    if not rows:
        return []
    hdr = None
    start = 0
    for i, r in enumerate(rows):
        if any(_t(c) for c in r):
            hdr = r
            start = i + 1
            break
    if hdr is None:
        return []
    headers = [_t(h).lower() for h in hdr]
    out_rows = []
    for r in rows[start:]:
        if not any(_t(c) for c in r):
            continue
        d = {}
        for i, c in enumerate(r):
            if i < len(headers) and headers[i]:
                d[headers[i]] = _t(c)
        out_rows.append(d)
    return out_rows


def read_workbook(path, tab=None):
    """Parse a worksheet from .xlsx/.xlsm directly (pure Python, IronPython-safe).
    tab=None -> first worksheet."""
    import zipfile
    import xml.etree.ElementTree as ET
    z = zipfile.ZipFile(path)
    try:
        names = z.namelist()
        shared = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in list(root):
                parts = [t.text for t in si.iter() if _local(t.tag) == "t" and t.text]
                shared.append("".join(parts))
        wbx = ET.fromstring(z.read("xl/workbook.xml"))
        ordered = []
        for el in wbx.iter():
            if _local(el.tag) == "sheet":
                rid = None
                for k, v in el.attrib.items():
                    if _local(k) == "id":
                        rid = v
                ordered.append((el.get("name"), rid))
        if not ordered:
            return None
        rid = None
        if tab is None:
            rid = ordered[0][1]
        else:
            for nm, r in ordered:
                if nm == tab:
                    rid = r
                    break
        if rid is None:
            return None
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        target = None
        for el in rels.iter():
            if _local(el.tag) == "Relationship" and el.get("Id") == rid:
                target = el.get("Target")
                break
        if not target:
            return None
        target = target[1:] if target.startswith("/") else "xl/" + target
        target = target.replace("xl/xl/", "xl/")
        ws = ET.fromstring(z.read(target))
        out_rows = []
        for el in ws.iter():
            if _local(el.tag) != "row":
                continue
            cells = {}
            maxcol = -1
            for c in list(el):
                if _local(c.tag) != "c":
                    continue
                col = _col_index(c.get("r") or "")
                t = c.get("t")
                vtext = None
                istext = None
                for child in list(c):
                    ln = _local(child.tag)
                    if ln == "v":
                        vtext = child.text
                    elif ln == "is":
                        istext = "".join(tt.text for tt in child.iter()
                                         if _local(tt.tag) == "t" and tt.text)
                if t == "s" and vtext is not None:
                    try:
                        val = shared[int(vtext)]
                    except Exception:
                        val = ""
                elif t == "inlineStr" and istext is not None:
                    val = istext
                elif vtext is not None:
                    val = vtext
                else:
                    val = ""
                cells[col] = val
                if col > maxcol:
                    maxcol = col
            out_rows.append([cells.get(i, "") for i in range(0, maxcol + 1)])
        return _rows_to_dicts(out_rows)
    finally:
        z.close()


# ---------------------------------------------------------------- revit helpers
def elem_name(e):
    try:
        return DB.Element.Name.GetValue(e)
    except Exception:
        p = e.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM)
        return p.AsString() if p else ""


def get_param_ci(elem, name):
    p = elem.LookupParameter(name)
    if p:
        return p
    low = name.lower()
    for par in elem.Parameters:
        try:
            if par.Definition and par.Definition.Name.lower() == low:
                return par
        except Exception:
            continue
    return None


def set_param(elem, pname, value):
    p = get_param_ci(elem, pname)
    if p is None:
        _MISSING.add(pname)
        return False
    if p.IsReadOnly:
        return False
    try:
        p.Set(_t(value))
        return True
    except Exception:
        return False


def _swatch(c):
    return ("<span style='display:inline-block;width:9px;height:9px;border-radius:50%;"
            "background:" + c + ";margin-right:6px'></span>")


def desktop():
    home = os.path.expanduser("~")
    d = os.path.join(home, "Desktop")
    return d if os.path.isdir(d) else home


def sheet_has_revisions(sheet):
    try:
        revs = sheet.GetAllRevisionIds()
        return revs is not None and revs.Count > 0
    except Exception:
        return False


def safe_switch_active_view():
    """Move the active view off any sheet so sheets can be deleted."""
    try:
        if isinstance(uidoc.ActiveView, DB.ViewSheet):
            for v in DB.FilteredElementCollector(doc).OfClass(DB.View):
                if (not v.IsTemplate and not isinstance(v, DB.ViewSheet)
                        and v.ViewType != DB.ViewType.Internal):
                    uidoc.ActiveView = v
                    return
    except Exception:
        pass


def backup_sheets(existing):
    if not existing:
        return None
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(desktop(), "SDC_Sheets_backup_%s.csv" % stamp)
    try:
        with open(path, "w") as f:
            w = csv.writer(f)
            w.writerow(["Sheet Number", "Sheet Name"])
            for num, s in sorted(existing.items()):
                w.writerow([num, s.Name])
        return path
    except Exception:
        return None


def set_sheet_name(sheet, name):
    """Write the Sheet Name (sheet properties). Returns True if applied."""
    if not name:
        return True
    try:
        sheet.Name = name
        return True
    except Exception:
        pass
    try:
        p = sheet.get_Parameter(DB.BuiltInParameter.SHEET_NAME)
        if p is not None and not p.IsReadOnly:
            p.Set(name)
            return True
    except Exception:
        pass
    return False


def row_name(r):
    """Sheet name from the workbook, accepting a few common header spellings."""
    for k in ("name", "sheet name", "sheetname"):
        v = r.get(k, "")
        if v:
            return v
    return ""


def build_number(r):
    """Unique Sheet Number = Building-Discipline-Level-Series-Partial (dash-joined,
    empty parts skipped). Returns (number, series); a blank Series skips the row."""
    series = r.get(C_SERIES.lower(), "") or r.get("master", "")   # "Master" alias
    if not series:
        return "", ""
    parts = [p for p in (r.get(C_BUILDING.lower(), ""),
                         r.get(C_DISC.lower(), ""),
                         r.get(C_LEVEL.lower(), ""),
                         series,
                         r.get(C_PARTIAL.lower(), "")) if p]
    return "-".join(parts), series


# ---------------------------------------------------------------- main
def main():
    path = forms.pick_file(files_filter="Excel (*.xlsx;*.xlsm)|*.xlsx;*.xlsm",
                           title="Select the sheet-list workbook")
    if not path:
        return
    rows = read_workbook(path, "Sheets")
    if not rows:
        rows = read_workbook(path, None)   # fall back to first worksheet
    if not rows:
        forms.alert("No rows found in the workbook.", exitscript=True)

    MODES = {
        "Keep existing  &  add missing": "KEEP",
        "Delete all  &  start fresh  (issued/revised sheets are protected)": "FRESH",
    }
    pick = forms.CommandSwitchWindow.show(list(MODES.keys()),
                                          message="How should the sheets be generated?")
    if not pick:
        return
    mode = MODES[pick]

    # ---- collect model state ----
    existing = {}
    for s in DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet):
        if isinstance(s, DB.ViewSheet) and not s.IsPlaceholder:
            existing[s.SheetNumber] = s
    tb_map = {}
    for s in (DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_TitleBlocks)
              .WhereElementIsElementType()):
        tb_map[elem_name(s).lower()] = s
    view_names = set()
    for v in DB.FilteredElementCollector(doc).OfClass(DB.View):
        try:
            if not v.IsTemplate:
                view_names.add(v.Name.lower())
        except Exception:
            pass

    # project-info prefix used for the full title-block number
    pinfo = doc.ProjectInformation

    def _pinfo(bip):
        try:
            p = pinfo.get_Parameter(bip)
            if p is not None:
                s = p.AsString()
                return s if s else ""
        except Exception:
            pass
        return ""
    proj_prefix_parts = [p for p in (_pinfo(DB.BuiltInParameter.PROJECT_NUMBER),
                                     _pinfo(DB.BuiltInParameter.PROJECT_AUTHOR),
                                     _pinfo(DB.BuiltInParameter.PROJECT_STATUS)) if p]

    def full_label(number):
        if not number or number == "(blank)":
            return ""
        return "-".join(proj_prefix_parts + [number])

    # ---- options (unticked = safe defaults) ----
    DRY = "Dry run (preview, nothing saved)"
    DEL0 = "Delete sheet number %s" % PLACEHOLDER_NUMBER
    UPDATE = "Update existing instead of skipping duplicate Sheet Numbers"
    if mode == "KEEP":
        choices = [DRY, DEL0, UPDATE]
    else:
        choices = [DRY]
    opts = forms.SelectFromList.show(choices, title="Options  (leave unticked for safe defaults)",
                                     multiselect=True, button_name="Next") or []
    dry = DRY in opts
    keep_0000 = DEL0 not in opts        # default: keep the 0000 sheet
    skip_dupes = UPDATE not in opts     # default: flag duplicates, do not touch them

    # ---- fallback title block (the Excel value wins per row) ----
    fallback_tb = None
    excel_def_lower = None
    for r in rows:
        nm = r.get(C_TB.lower(), "").lower()
        if nm in tb_map:
            excel_def_lower = nm
            break
    if tb_map:
        disp = sorted(elem_name(e) for e in tb_map.values())
        sel = forms.SelectFromList.show(
            disp, title="Fallback title block - used only when a row's value is blank/not found",
            multiselect=False, button_name="Use as fallback")
        if sel:
            fallback_tb = tb_map.get(sel.lower())
        elif excel_def_lower:
            fallback_tb = tb_map.get(excel_def_lower)

    # ---- confirm + backup for FRESH ----
    backup_file = None
    if mode == "FRESH" and not dry:
        n_prot = sum(1 for s in existing.values() if sheet_has_revisions(s))
        n_del = len(existing) - n_prot
        if not forms.alert(
                "Delete all & start fresh:\n"
                "   %d sheet(s) will be DELETED\n"
                "   %d issued/revised sheet(s) will be PROTECTED (kept)\n\n"
                "A backup CSV will be saved to your Desktop first.\nContinue?"
                % (n_del, n_prot),
                title="Confirm delete", yes=True, no=True):
            return
        backup_file = backup_sheets(existing)

    if mode == "FRESH" or (mode == "KEEP" and not keep_0000):
        safe_switch_active_view()

    results = []   # each: (number, name, action, status, color)

    def tb_for_row(r):
        nm = r.get(C_TB.lower(), "")
        tb = tb_map.get(nm.lower()) if nm else None
        miss = bool(nm) and tb is None
        if tb is None:
            tb = fallback_tb
        return (tb.Id if tb else DB.ElementId.InvalidElementId), miss, nm

    def write_params(sheet, r):
        set_param(sheet, P_BUILDING, r.get(C_BUILDING.lower(), ""))
        set_param(sheet, P_DISC, r.get(C_DISC.lower(), ""))
        set_param(sheet, P_LEVEL, r.get(C_LEVEL.lower(), ""))

    def name_note(name):
        if name and name.lower() not in view_names:
            return "  - no view named '%s'" % name
        return ""

    def create_row(r, existing_nums, made):
        number, series = build_number(r)
        name = row_name(r)
        if not series:
            results.append(("(blank)", name, "Create", "Skipped (no Series)", GOLD))
            return

        # duplicate of a sheet already in the model -------------------------
        if number in existing_nums:
            ex = existing.get(number)
            exname = ex.Name if ex is not None else name
            if skip_dupes:
                results.append((number, exname, "Duplicate",
                                "Existing sheet kept - not created or removed", GOLD))
                return
            if ex is None:
                results.append((number, name, "Update", "Skipped (not found)", GREY))
                return
            ok = set_sheet_name(ex, name)
            write_params(ex, r)
            note = "Updated"
            if name and not ok:
                note += "  - name could not be applied"
            note += name_note(name)
            results.append((number, name or exname, "Update", note, BLUE))
            return

        # duplicate row inside the workbook itself --------------------------
        if number in made:
            results.append((number, name, "Duplicate",
                            "Duplicate row in Excel - first one kept", GOLD))
            return

        # create -----------------------------------------------------------
        tbid, tbmiss, tbname = tb_for_row(r)
        try:
            sheet = DB.ViewSheet.Create(doc, tbid)
        except Exception as ex:
            results.append((number, name, "Create", "Error (%s)" % ex, RED))
            return
        try:
            sheet.SheetNumber = number
        except Exception:
            pass
        made.add(number)
        ok = set_sheet_name(sheet, name)
        write_params(sheet, r)
        note = "Created"
        color = GREEN
        if name and not ok:
            note += "  - name could not be applied"
            color = GOLD
        if tbmiss:
            note += "  - title block '%s' not found (used fallback)" % tbname
            color = GOLD
        nn = name_note(name)
        if nn:
            note += nn
            color = GOLD
        results.append((number, name, "Create", note, color))

    def work():
        for s in tb_map.values():
            if not s.IsActive:
                try:
                    s.Activate()
                except Exception:
                    pass
        if mode == "FRESH":
            protected = set()
            for num, s in list(existing.items()):
                nm = s.Name
                if sheet_has_revisions(s):
                    protected.add(num)
                    results.append((num, nm, "Delete", "Protected (issued/revised)", BLUE))
                    continue
                try:
                    doc.Delete(s.Id)
                    results.append((num, nm, "Delete", "Deleted", RED))
                except Exception as ex:
                    results.append((num, nm, "Delete", "Error (%s)" % ex, RED))
            existing_nums = set(protected)
        else:
            existing_nums = set(existing.keys())
            if not keep_0000 and PLACEHOLDER_NUMBER in existing:
                s0 = existing[PLACEHOLDER_NUMBER]
                nm0 = s0.Name
                try:
                    doc.Delete(s0.Id)
                    existing_nums.discard(PLACEHOLDER_NUMBER)
                    results.append((PLACEHOLDER_NUMBER, nm0, "Delete",
                                    "Deleted (0000 not kept)", RED))
                except Exception as ex:
                    results.append((PLACEHOLDER_NUMBER, nm0, "Delete", "Error (%s)" % ex, RED))
        made = set()
        for r in rows:
            create_row(r, existing_nums, made)

    t = DB.Transaction(doc, "SDC - Create Sheets (%s)" % mode)
    t.Start()
    try:
        work()
    except Exception:
        t.RollBack()
        raise
    if dry:
        t.RollBack()
    else:
        t.Commit()

    # ---- report ----
    out.print_md("# SDC - Create Sheets")
    out.print_html("<b>Mode:</b> %s &nbsp;|&nbsp; <b>%s</b>"
                   % (pick, "PREVIEW (rolled back - nothing saved)" if dry else "EXECUTED"))
    flags = []
    if mode == "KEEP":
        flags.append("Keep 0000: %s" % ("yes" if keep_0000 else "no"))
        flags.append("Duplicates: %s"
                     % ("flag only (never removed)" if skip_dupes else "update existing"))
    if fallback_tb is not None:
        flags.append("Fallback title block: %s" % elem_name(fallback_tb))
    if proj_prefix_parts:
        flags.append("Title-block prefix: %s" % "-".join(proj_prefix_parts))
    if flags:
        out.print_html("<i>%s</i>" % "  &nbsp;|&nbsp;  ".join(flags))
    if backup_file:
        out.print_html("<b>Backup saved:</b> %s" % backup_file)
    counts = {}
    for r in results:
        k = r[3].split(" ")[0]
        counts[k] = counts.get(k, 0) + 1
    out.print_html(" ".join(
        "<span style='background:%s;color:#fff;padding:2px 8px;border-radius:10px;"
        "margin-right:4px'>%s: %d</span>" %
        ({"Created": GREEN, "Updated": BLUE, "Deleted": RED, "Protected": BLUE,
          "Duplicate": GOLD, "Skipped": GREY, "Error": RED}.get(k, GREY), k, v)
        for k, v in sorted(counts.items())))
    if _MISSING:
        out.print_html("<b style='color:%s'>Shared parameters not found on sheets "
                       "(add them via SDC_Sheet_Params.txt, bound to Sheets):</b> %s"
                       % (GOLD, ", ".join(sorted(_MISSING))))
    table = [[r[0], full_label(r[0]), r[1], r[2], _swatch(r[4]) + r[3]] for r in results]
    out.print_table(table_data=table,
                    columns=["Sheet No.", "Full No. (title block)", "Sheet Name",
                             "Action", "Status"])


if __name__ == "__main__":
    main()

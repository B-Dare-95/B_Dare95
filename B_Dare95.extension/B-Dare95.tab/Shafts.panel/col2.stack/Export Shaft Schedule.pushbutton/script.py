# -*- coding: utf-8 -*-
"""
Export Shafts To Excel
======================
Exports all Shaft Opening elements from the active document to a styled .xlsx.

NO openpyxl required — the workbook is built entirely from
System.IO.Compression (ZipArchive) + raw XML strings, both of which are
always present in Revit's .NET runtime.

Fields exported:
    1. Shaft ID            5. Top Offset (mm)
    2. Base Constraint     6. Total Height (mm)
    3. Base Offset (mm)    7. Shaft Function
    4. Top Constraint      8. Workset

pyRevit | IronPython 2.7
"""

# ── CLR / .NET ────────────────────────────────────────────────────────────────
import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("System.Windows.Forms")
clr.AddReference("System.IO.Compression")

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    BuiltInCategory,
    BuiltInParameter,
)
from System.Windows.Forms import (
    SaveFileDialog, DialogResult,
    MessageBox, MessageBoxButtons, MessageBoxIcon,
)
from System.IO.Compression import ZipArchive, ZipArchiveMode
from System.IO   import File, FileMode
from System.Text import UTF8Encoding

from pyrevit import script

output = script.get_output()
output.close_others()
doc = __revit__.ActiveUIDocument.Document


# ═════════════════════════════════════════════════════════════════════════════
#  ZERO-DEPENDENCY XLSX ENGINE
#  Builds a valid Office Open XML workbook as a ZIP of XML parts.
# ═════════════════════════════════════════════════════════════════════════════

def _xml_esc(s):
    """Escape a value for safe embedding inside XML text / attribute content."""
    s = u"" if s is None else unicode(s)
    return (s.replace(u"&", u"&amp;")
             .replace(u"<", u"&lt;")
             .replace(u">", u"&gt;")
             .replace(u'"', u"&quot;")
             .replace(u"'", u"&apos;"))


def _col_letter(n):
    """1-based column index → Excel column letter(s).  1=A, 27=AA …"""
    out = u""
    while n > 0:
        n, r = divmod(n - 1, 26)
        out  = unichr(65 + r) + out
    return out


def write_xlsx(filepath, sheet_name, headers, rows,
               col_widths=None,
               header_fill_rgb="1F3864",
               header_font_rgb="FFFFFF"):
    """
    Write a styled .xlsx workbook.

    Parameters
    ----------
    filepath        : str  Full path including .xlsx
    sheet_name      : str  Tab name
    headers         : list Column header strings
    rows            : list of lists  (str / int / float / None)
    col_widths      : list optional per-column widths
    header_fill_rgb : str  6-char hex, no '#'
    header_font_rgb : str  6-char hex, no '#'
    """

    utf8 = UTF8Encoding(False)   # UTF-8 without BOM

    # ── Shared-string table ───────────────────────────────────────────────────
    _ss, _sm = [], {}

    def _si(v):
        s = u"" if v is None else unicode(v)
        if s not in _sm:
            _sm[s] = len(_ss)
            _ss.append(s)
        return _sm[s]

    for h in headers:
        _si(h)
    for row in rows:
        for v in row:
            if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
                _si(v)

    # ── Cell XML helper ───────────────────────────────────────────────────────
    def _c(ref, val, s):
        """Return <c …> XML for one cell.  s = style index."""
        if val is None:
            return u'<c r="{0}" s="{1}"/>'.format(ref, s)
        if not isinstance(val, bool) and isinstance(val, (int, float)):
            return u'<c r="{0}" s="{1}"><v>{2}</v></c>'.format(ref, s, val)
        return u'<c r="{0}" t="s" s="{1}"><v>{2}</v></c>'.format(ref, s, _si(val))

    # ── Row fragments ─────────────────────────────────────────────────────────
    row_xml = []

    # Row 1 – headers (style 1 = dark header)
    hcells = u"".join(
        _c(_col_letter(ci + 1) + u"1", h, 1)
        for ci, h in enumerate(headers)
    )
    row_xml.append(u'<row r="1" ht="22" customHeight="1">{0}</row>'.format(hcells))

    # Data rows (style 0 = body; style 2 = centred numeric for ID col)
    for ri, rowdata in enumerate(rows, 2):
        cells = u""
        for ci, v in enumerate(rowdata, 1):
            ref = _col_letter(ci) + unicode(ri)
            st  = 2 if (ci == 1 and not isinstance(v, bool)
                        and isinstance(v, (int, float))) else 0
            cells += _c(ref, v, st)
        row_xml.append(u'<row r="{0}">{1}</row>'.format(ri, cells))

    # ── Column-width XML ──────────────────────────────────────────────────────
    if col_widths:
        cols_xml = u"<cols>" + u"".join(
            u'<col min="{0}" max="{0}" width="{1}" customWidth="1"/>'.format(i + 1, w)
            for i, w in enumerate(col_widths)
        ) + u"</cols>"
    else:
        cols_xml = u""

    last_col = _col_letter(len(headers))

    # ── XML parts ─────────────────────────────────────────────────────────────
    CT = (u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          u'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          u'<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          u'<Default Extension="xml"  ContentType="application/xml"/>'
          u'<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
          u'<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
          u'<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
          u'<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
          u'</Types>')

    RELS = (u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            u'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            u'<Relationship Id="rId1" '
            u'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            u'Target="xl/workbook.xml"/>'
            u'</Relationships>')

    WB = (u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          u'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
          u'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
          u'<sheets><sheet name="{0}" sheetId="1" r:id="rId1"/></sheets>'
          u'</workbook>').format(_xml_esc(sheet_name))

    WB_RELS = (u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               u'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
               u'<Relationship Id="rId1" '
               u'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
               u'Target="worksheets/sheet1.xml"/>'
               u'<Relationship Id="rId2" '
               u'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
               u'Target="styles.xml"/>'
               u'<Relationship Id="rId3" '
               u'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" '
               u'Target="sharedStrings.xml"/>'
               u'</Relationships>')

    STYLES = (
        u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        u'<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        u'<fonts count="2">'
        u'<font><sz val="10"/><name val="Calibri"/></font>'
        u'<font><sz val="10"/><b/><color rgb="FF{hf}"/><name val="Calibri"/></font>'
        u'</fonts>'
        u'<fills count="3">'
        u'<fill><patternFill patternType="none"/></fill>'
        u'<fill><patternFill patternType="gray125"/></fill>'
        u'<fill><patternFill patternType="solid"><fgColor rgb="FF{hb}"/></patternFill></fill>'
        u'</fills>'
        u'<borders count="2">'
        u'<border><left/><right/><top/><bottom/><diagonal/></border>'
        u'<border>'
        u'<left style="thin"><color rgb="FFB0B0B0"/></left>'
        u'<right style="thin"><color rgb="FFB0B0B0"/></right>'
        u'<top style="thin"><color rgb="FFB0B0B0"/></top>'
        u'<bottom style="thin"><color rgb="FFB0B0B0"/></bottom>'
        u'<diagonal/>'
        u'</border>'
        u'</borders>'
        u'<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        u'<cellXfs count="3">'
        u'<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0">'
        u'<alignment horizontal="left" vertical="center" wrapText="1"/></xf>'
        u'<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1">'
        u'<alignment horizontal="center" vertical="center" wrapText="1"/></xf>'
        u'<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0">'
        u'<alignment horizontal="center" vertical="center"/></xf>'
        u'</cellXfs>'
        u'</styleSheet>'
    ).format(hf=header_font_rgb, hb=header_fill_rgb)

    SS_ITEMS = u"".join(
        u'<si><t xml:space="preserve">{0}</t></si>'.format(_xml_esc(s))
        for s in _ss
    )
    SS = (u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          u'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
          u'count="{n}" uniqueCount="{n}">{si}</sst>').format(n=len(_ss), si=SS_ITEMS)

    WS = (u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          u'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
          u'<sheetViews><sheetView workbookViewId="0">'
          u'<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
          u'</sheetView></sheetViews>'
          u'<sheetFormatPr defaultRowHeight="15"/>'
          u'{cols}'
          u'<sheetData>{rows}</sheetData>'
          u'<autoFilter ref="A1:{lc}1"/>'
          u'</worksheet>').format(
              cols=cols_xml,
              rows=u"".join(row_xml),
              lc=last_col,
          )

    # ── Pack into ZIP (xlsx IS a ZIP) ─────────────────────────────────────────
    fs = File.Open(filepath, FileMode.Create)
    za = None
    try:
        za = ZipArchive(fs, ZipArchiveMode.Create, False)

        def _add(name, xml):
            e  = za.CreateEntry(name)
            st = e.Open()
            try:
                b = utf8.GetBytes(xml)
                st.Write(b, 0, b.Length)
            finally:
                st.Close()

        _add("[Content_Types].xml",        CT)
        _add("_rels/.rels",                RELS)
        _add("xl/workbook.xml",            WB)
        _add("xl/_rels/workbook.xml.rels", WB_RELS)
        _add("xl/worksheets/sheet1.xml",   WS)
        _add("xl/styles.xml",              STYLES)
        _add("xl/sharedStrings.xml",       SS)
    finally:
        if za is not None:
            za.Dispose()   # flushes ZIP; also closes fs (leaveOpen=False)


# ═════════════════════════════════════════════════════════════════════════════
#  REVIT DATA COLLECTION
# ═════════════════════════════════════════════════════════════════════════════

def _feet_to_mm(feet):
    try:
        return round(float(feet) * 304.8, 2)
    except Exception:
        return "N/A"


def _level_name(elem, bip):
    p = elem.get_Parameter(bip)
    if p is None or not p.HasValue:
        return "N/A"
    eid = p.AsElementId()
    if eid.IntegerValue < 0:
        return "Unconnected"
    lv = doc.GetElement(eid)
    return lv.Name if (lv and lv.Name) else "N/A"


def _double_mm(elem, bip):
    p = elem.get_Parameter(bip)
    if p is None or not p.HasValue:
        return "N/A"
    return _feet_to_mm(p.AsDouble())


def _str_param(elem, name):
    p = elem.LookupParameter(name)
    if p is None or not p.HasValue:
        return "N/A"
    v = p.AsString()
    return v if v else "N/A"


def _workset(elem):
    if not doc.IsWorkshared:
        return "N/A"
    try:
        ws = doc.GetWorksetTable().GetWorkset(elem.WorksetId)
        return ws.Name if ws else "N/A"
    except Exception:
        return "N/A"


# ── Gather all shaft openings ─────────────────────────────────────────────────
shafts = (FilteredElementCollector(doc)
          .OfCategory(BuiltInCategory.OST_ShaftOpening)
          .WhereElementIsNotElementType()
          .ToElements())

if not shafts:
    MessageBox.Show(
        "No Shaft Opening elements found in the active document.",
        "No Shafts Found", MessageBoxButtons.OK, MessageBoxIcon.Warning,
    )
    import sys; sys.exit(0)

HEADERS = [
    "Shaft ID", "Base Constraint", "Base Offset (mm)",
    "Top Constraint", "Top Offset (mm)", "Total Height (mm)",
    "Shaft Function", "Workset",
]

rows = sorted(
    [
        [
            s.Id.IntegerValue,
            _level_name(s, BuiltInParameter.WALL_BASE_CONSTRAINT),
            _double_mm(s,  BuiltInParameter.WALL_BASE_OFFSET),
            _level_name(s, BuiltInParameter.WALL_HEIGHT_TYPE),
            _double_mm(s,  BuiltInParameter.WALL_TOP_OFFSET),
            _double_mm(s,  BuiltInParameter.WALL_USER_HEIGHT_PARAM),
            _str_param(s,  "Shaft Function"),
            _workset(s),
        ]
        for s in shafts
    ],
    key=lambda r: r[0],
)

# ═════════════════════════════════════════════════════════════════════════════
#  SAVE DIALOG
# ═════════════════════════════════════════════════════════════════════════════

dlg            = SaveFileDialog()
dlg.Title      = "Save Shaft Data as Excel"
dlg.Filter     = "Excel Workbook (*.xlsx)|*.xlsx"
dlg.FileName   = "Shaft_Data_Export.xlsx"
dlg.DefaultExt = "xlsx"

if dlg.ShowDialog() != DialogResult.OK:
    output.print_md("**Export cancelled.**")
    import sys; sys.exit(0)

save_path = dlg.FileName

# ═════════════════════════════════════════════════════════════════════════════
#  WRITE + REPORT
# ═════════════════════════════════════════════════════════════════════════════

try:
    write_xlsx(
        filepath   = save_path,
        sheet_name = "Shaft Data",
        headers    = HEADERS,
        rows       = rows,
        col_widths = [14, 22, 20, 22, 18, 20, 26, 24],
    )
except Exception as ex:
    MessageBox.Show(
        "Failed to save Excel file:\n{0}".format(str(ex)),
        "Save Error", MessageBoxButtons.OK, MessageBoxIcon.Error,
    )
    import sys; sys.exit(1)

output.print_md("## ✅ Shaft Data Exported Successfully")
output.print_md("**Shafts exported:** `{0}`".format(len(rows)))
output.print_md("**Saved to:** `{0}`".format(save_path))
output.print_md("---")
output.print_md("### Preview (first 10 rows)")
# output.print_table(
#     table_data=[HEADERS] + [[unicode(v) for v in r] for r in rows[:10]],
#     title="", columns=[], last_line_attr=None,
# )
if len(rows) > 10:
    output.print_md("*… and {0} more rows.*".format(len(rows) - 10))
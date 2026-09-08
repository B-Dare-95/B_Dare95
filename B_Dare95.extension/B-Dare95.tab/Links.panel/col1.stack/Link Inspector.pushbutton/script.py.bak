# -*- coding: utf-8 -*-
"""Link Inspector.

Read-only health report for every Revit link in the active document:

  * DWG links / imports living inside the link
  * Warning count stored in the link, grouped by warning type
  * Levels and Grids sitting on the wrong workset
  * Unused families and types, per category

The report exports as a self-contained interactive HTML page.
No transaction is opened. Nothing is modified.
"""

__title__ = "Link\nInspector"
__author__ = "Mohamed Bedair"
__doc__ = ("Inspects every linked Revit document for DWG imports/links, "
           "warnings, Levels/Grids on the wrong workset, and unused "
           "families/types per category.")

import clr

clr.AddReference("System")
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")

from System import EventHandler, DateTime
from System.Collections.Generic import List
from System.IO import File, Path
from System.Text import Encoding
from System.Windows import (FontWeights, RoutedEventHandler, TextWrapping,
                            Visibility)
from System.Windows.Controls import (SelectionChangedEventHandler, TextBlock,
                                     TextChangedEventHandler, TreeViewItem)
from System.Windows.Input import Cursors, Mouse
from System.Windows.Markup import XamlReader
from System.Windows.Media import Color, SolidColorBrush
from System.Windows.Threading import Dispatcher, DispatcherFrame

from Autodesk.Revit.DB import (BuiltInCategory, CADLinkType, CategoryType,
                               Element, ElementId, FilteredElementCollector,
                               ImportInstance, RevitLinkInstance)
from Autodesk.Revit.UI import TaskDialog

try:
    from System.Diagnostics import Process
except ImportError:      # System.dll not referenced in this host
    Process = None

doc = __revit__.ActiveUIDocument.Document

# Worksets that Levels and Grids are allowed to live on. Edit to match the
# project's BIM Execution Plan.
VALID_LG_WORKSETS = [
    "shared levels and grids",
    "shared views, levels, grids",
]

DASH = u"\u2014"        # em dash, shown when a check does not apply


def make_brush(red, green, blue):
    return SolidColorBrush(Color.FromRgb(red, green, blue))


BRUSH_TEXT = make_brush(0xCD, 0xD6, 0xF4)
BRUSH_SUB = make_brush(0xA6, 0xAD, 0xC8)
BRUSH_ACCENT = make_brush(0xF0, 0xA5, 0x00)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def eid_value(eid):
    """ElementId -> int. .Value on Revit 2025+, .IntegerValue on older."""
    if eid is None:
        return -1
    try:
        return eid.Value
    except AttributeError:
        return eid.IntegerValue


def elem_name(el):
    """Safe Element.Name read."""
    if el is None:
        return "<none>"
    try:
        name = el.Name
    except Exception:
        name = None
    if not name:
        try:
            name = Element.Name.GetValue(el)
        except Exception:
            name = None
    return name or "<unnamed>"


def file_ext(name):
    if "." not in name:
        return ""
    return name.rsplit(".", 1)[-1].strip().lower()


def doc_title(rvt_doc, fallback):
    try:
        title = rvt_doc.Title
    except Exception:
        title = None
    return title or fallback


class Entry(object):
    """One line in the detail pane."""

    def __init__(self, text, sort_key=None, fields=None):
        self.Display = text
        self.SortKey = sort_key if sort_key is not None else text
        self.Fields = fields          # tuple of cells for the HTML report


# ---------------------------------------------------------------------------
# inspection 1 - DWG links and imports
# ---------------------------------------------------------------------------

def scan_cad(target_doc):
    """Return (dwg_links, dwg_imports, other_cad, [Entry, ...])."""
    entries = []
    dwg_links = 0
    dwg_imports = 0
    other_cad = 0
    used_type_ids = set()

    for inst in FilteredElementCollector(target_doc).OfClass(ImportInstance):
        type_id = inst.GetTypeId()
        used_type_ids.add(eid_value(type_id))
        name = elem_name(target_doc.GetElement(type_id))

        try:
            is_link = bool(inst.IsLinked)
        except Exception:
            is_link = False

        owner_id = inst.OwnerViewId
        if owner_id is not None and owner_id != ElementId.InvalidElementId:
            view = target_doc.GetElement(owner_id)
            scope = (u"View: {0}".format(elem_name(view))
                     if view is not None else "View specific")
        else:
            scope = "Model (all views)"

        ext = file_ext(name)
        if ext == "dwg":
            if is_link:
                dwg_links += 1
                kind = "DWG Link"
            else:
                dwg_imports += 1
                kind = "DWG Import"
        else:
            other_cad += 1
            label = ext.upper() if ext else "CAD"
            kind = u"{0} {1}".format(label, "Link" if is_link else "Import")

        entries.append(Entry(u"{0}   [{1}]   {2}".format(name, kind, scope),
                             (kind, name.lower()),
                             (name, kind, scope)))

    # CAD types with no placed instance - leftovers still in Manage Links
    for cad_type in FilteredElementCollector(target_doc).OfClass(CADLinkType):
        if eid_value(cad_type.Id) in used_type_ids:
            continue
        type_only_name = elem_name(cad_type)
        entries.append(Entry(
            u"{0}   [Type only, no instance]".format(type_only_name),
            ("zz", type_only_name.lower()),
            (type_only_name, "Type only, no instance", DASH)))

    entries.sort(key=lambda e: e.SortKey)
    return dwg_links, dwg_imports, other_cad, entries


# ---------------------------------------------------------------------------
# inspection 2 - warnings
# ---------------------------------------------------------------------------

def scan_warnings(target_doc):
    """Return (total_warnings, [Entry, ...]) grouped by warning description."""
    grouped = {}
    total = 0

    for failure in target_doc.GetWarnings():
        total += 1
        try:
            text = failure.GetDescriptionText()
        except Exception:
            text = "<unreadable warning>"
        text = (text or "<no description>").strip()
        grouped[text] = grouped.get(text, 0) + 1

    entries = []
    for text in grouped:
        count = grouped[text]
        entries.append(Entry(u"{0} x   {1}".format(count, text),
                             (-count, text.lower()),
                             (u"{0}".format(count), text)))
    entries.sort(key=lambda e: e.SortKey)
    return total, entries


# ---------------------------------------------------------------------------
# inspection 3 - Levels and Grids worksets
# ---------------------------------------------------------------------------

def workset_name(target_doc, element):
    """Workset name of an element, or None if it cannot be read."""
    try:
        table = target_doc.GetWorksetTable()
        workset = table.GetWorkset(element.WorksetId)
        return workset.Name if workset is not None else None
    except Exception:
        return None


def scan_levels_grids(target_doc):
    """Return (bad_levels, bad_grids, workshared, [Entry, ...]).

    bad_levels / bad_grids are None when the document is not workshared, since
    the check does not apply there.
    """
    if not target_doc.IsWorkshared:
        return None, None, False, [
            Entry("Model is not workshared - workset check does not apply.")]

    entries = []
    counts = {"Level": 0, "Grid": 0}

    categories = [("Level", BuiltInCategory.OST_Levels),
                  ("Grid", BuiltInCategory.OST_Grids)]

    for label, bic in categories:
        collector = (FilteredElementCollector(target_doc)
                     .OfCategory(bic)
                     .WhereElementIsNotElementType())
        for element in collector:
            ws_name = workset_name(target_doc, element)
            if ws_name is None:
                entries.append(Entry(
                    u"{0}: {1}   [workset unreadable]".format(
                        label, elem_name(element)),
                    (label, "zz", elem_name(element).lower()),
                    (label, elem_name(element), "unreadable")))
                continue
            if ws_name.strip().lower() in VALID_LG_WORKSETS:
                continue
            counts[label] += 1
            entries.append(Entry(
                u"{0}: {1}   [on '{2}']".format(
                    label, elem_name(element), ws_name),
                (label, ws_name.lower(), elem_name(element).lower()),
                (label, elem_name(element), ws_name)))

    entries.sort(key=lambda e: e.SortKey)
    if not entries:
        entries = [Entry("All Levels and Grids are on an accepted workset.")]

    return counts["Level"], counts["Grid"], True, entries


# ---------------------------------------------------------------------------
# inspection 4 - unused families and types
# ---------------------------------------------------------------------------

class CategoryStat(object):
    def __init__(self, name):
        self.Name = name
        self.FamilyCount = 0
        self.TypeCount = 0
        self.UnusedFamilies = []      # [(family name, type count), ...]
        self.UnusedTypes = []         # ["family : type", ...] in used families

    @property
    def UsedFamilyCount(self):
        return self.FamilyCount - len(self.UnusedFamilies)

    def summary_line(self):
        return (u"{0} families, {1} unused  |  {2} types, {3} unused under "
                u"the {4} remaining families").format(
                    self.FamilyCount, len(self.UnusedFamilies),
                    self.TypeCount, len(self.UnusedTypes),
                    self.UsedFamilyCount)

    def has_findings(self):
        return bool(self.UnusedFamilies) or bool(self.UnusedTypes)


class UnusedResult(object):
    def __init__(self):
        self.Categories = []
        self.TotalFamilies = 0
        self.TotalTypes = 0
        self.TotalUnusedFamilies = 0
        self.TotalUnusedTypes = 0


def type_family_name(element_type):
    """Family name of an ElementType, for loadable and system families."""
    try:
        name = element_type.FamilyName
    except Exception:
        name = None
    return name or "<no family>"


def scan_unused(target_doc):
    """Find families and types with no placed instances, grouped by category.

    A family is 'unused' when none of its types has a single instance in the
    document. A type is reported separately when its family IS used but that
    specific type is not placed anywhere.
    """
    used_type_ids = set()
    for element in FilteredElementCollector(target_doc).WhereElementIsNotElementType():
        type_id = element.GetTypeId()
        if type_id is not None and type_id != ElementId.InvalidElementId:
            used_type_ids.add(eid_value(type_id))

    # category name -> family name -> [(type name, is_used), ...]
    tree = {}
    for element_type in FilteredElementCollector(target_doc).WhereElementIsElementType():
        category = element_type.Category
        if category is None:
            continue
        if category.CategoryType not in (CategoryType.Model,
                                         CategoryType.Annotation):
            continue

        cat_name = category.Name
        fam_name = type_family_name(element_type)
        is_used = eid_value(element_type.Id) in used_type_ids

        families = tree.setdefault(cat_name, {})
        families.setdefault(fam_name, []).append(
            (elem_name(element_type), is_used))

    result = UnusedResult()
    for cat_name in sorted(tree.keys(), key=lambda n: n.lower()):
        families = tree[cat_name]
        stat = CategoryStat(cat_name)
        stat.FamilyCount = len(families)

        for fam_name in sorted(families.keys(), key=lambda n: n.lower()):
            types = families[fam_name]
            stat.TypeCount += len(types)
            used_types = [t for t in types if t[1]]

            if not used_types:
                stat.UnusedFamilies.append((fam_name, len(types)))
                continue

            for type_name, is_used in sorted(types, key=lambda t: t[0].lower()):
                if not is_used:
                    stat.UnusedTypes.append(
                        u"{0} : {1}".format(fam_name, type_name))

        result.Categories.append(stat)
        result.TotalFamilies += stat.FamilyCount
        result.TotalTypes += stat.TypeCount
        result.TotalUnusedFamilies += len(stat.UnusedFamilies)
        result.TotalUnusedTypes += len(stat.UnusedTypes)

    return result


# ---------------------------------------------------------------------------
# row model
# ---------------------------------------------------------------------------

class LinkRow(object):
    def __init__(self, name):
        self.Name = name
        self.RawName = name
        self.Status = "Loaded"
        self.Scanned = False
        self.LinkDoc = None

        self.DwgLinks = 0
        self.DwgImports = 0
        self.OtherCad = 0
        self.Warnings = 0
        self.BadLevels = None
        self.BadGrids = None
        self.Workshared = False
        self.Unused = None            # UnusedResult, filled on demand

        self.CadEntries = []
        self.WarningEntries = []
        self.WorksetEntries = []

        self.ColDwgLinks = DASH
        self.ColDwgImports = DASH
        self.ColWarnings = DASH
        self.ColLevels = DASH
        self.ColGrids = DASH
        self.ColUnused = DASH

    def inspect(self, target_doc):
        self.Scanned = True
        self.LinkDoc = target_doc

        (self.DwgLinks, self.DwgImports, self.OtherCad,
         self.CadEntries) = scan_cad(target_doc)
        self.Warnings, self.WarningEntries = scan_warnings(target_doc)
        (self.BadLevels, self.BadGrids, self.Workshared,
         self.WorksetEntries) = scan_levels_grids(target_doc)

        self.ColDwgLinks = str(self.DwgLinks)
        self.ColDwgImports = str(self.DwgImports)
        self.ColWarnings = str(self.Warnings)
        self.ColUnused = "?"
        if self.Workshared:
            self.ColLevels = str(self.BadLevels)
            self.ColGrids = str(self.BadGrids)
        else:
            self.ColLevels = "n/a"
            self.ColGrids = "n/a"

    def inspect_unused(self):
        """Run the unused-item scan once and cache it."""
        if self.Unused is not None or not self.Scanned or self.LinkDoc is None:
            return
        self.Unused = scan_unused(self.LinkDoc)
        self.ColUnused = "{0} / {1}".format(self.Unused.TotalUnusedFamilies,
                                            self.Unused.TotalUnusedTypes)


# ---------------------------------------------------------------------------
# collection
# ---------------------------------------------------------------------------

def build_rows():
    rows = []

    host_row = LinkRow(doc_title(doc, "Host model"))
    host_row.Status = "Host model"
    host_row.inspect(doc)
    rows.append(host_row)

    seen_paths = set()
    host_path = (doc.PathName or "").strip().lower()
    if host_path:
        seen_paths.add(host_path)

    seen_type_ids = set()
    collector = FilteredElementCollector(doc).OfClass(RevitLinkInstance)
    instances = list(collector)
    instances.sort(
        key=lambda i: elem_name(doc.GetElement(i.GetTypeId())).lower())

    for link_inst in instances:
        type_id = eid_value(link_inst.GetTypeId())
        if type_id in seen_type_ids:
            continue                      # several instances of the same link
        seen_type_ids.add(type_id)

        link_type = doc.GetElement(link_inst.GetTypeId())
        row = LinkRow(elem_name(link_type))

        try:
            status_text = str(link_type.GetLinkedFileStatus())
        except Exception:
            status_text = ""

        try:
            link_doc = link_inst.GetLinkDocument()
        except Exception:
            link_doc = None

        if link_doc is None:
            row.Status = status_text or "Not loaded"
            rows.append(row)
            continue

        key = (link_doc.PathName or row.RawName).strip().lower()
        if key in seen_paths:
            continue                      # same file linked twice
        seen_paths.add(key)

        row.Status = status_text or "Loaded"
        row.inspect(link_doc)
        rows.append(row)

    return rows


# ---------------------------------------------------------------------------
# HTML report
# ---------------------------------------------------------------------------

def esc(value):
    """Escape a value for HTML output."""
    text = u"{0}".format(value)
    text = text.replace(u"&", u"&amp;").replace(u"<", u"&lt;")
    return text.replace(u">", u"&gt;").replace(u'"', u"&quot;")


def badge(value):
    """Coloured pill for a count cell."""
    text = u"{0}".format(value)
    if text in (DASH, "n/a", "?", "not scanned"):
        css = "muted"
    elif text.replace(" ", "").replace("/", "").strip("0") == "":
        css = "zero"
    else:
        css = "some"
    return u'<span class="badge {0}">{1}</span>'.format(css, esc(text))


def table(headers, rows_data, empty_note="Nothing found."):
    """Small static HTML table."""
    if not rows_data:
        return u'<p class="note">{0}</p>'.format(esc(empty_note))
    out = [u'<table class="inner"><thead><tr>']
    for head in headers:
        out.append(u"<th>{0}</th>".format(esc(head)))
    out.append(u"</tr></thead><tbody>")
    for cells in rows_data:
        out.append(u"<tr>")
        for cell in cells:
            out.append(u"<td>{0}</td>".format(esc(cell)))
        out.append(u"</tr>")
    out.append(u"</tbody></table>")
    return u"".join(out)


REPORT_CSS = u"""
:root{
  --bg:#1e1e2e; --card:#2a2a3c; --surface:#313244; --muted:#45475a;
  --text:#cdd6f4; --sub:#a6adc8; --accent:#f0a500;
  --ok:#a6e3a1; --bad:#f38ba8;
}
*{box-sizing:border-box;}
body{margin:0;padding:28px 32px;background:var(--bg);color:var(--text);
     font-family:"Segoe UI",Tahoma,sans-serif;font-size:14px;}
h1{margin:0 0 4px;font-size:26px;}
h2{margin:0 0 14px;font-size:17px;color:var(--accent);}
.meta{color:var(--sub);font-size:12px;margin-bottom:20px;line-height:1.7;}
.cards{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:22px;}
.card{background:var(--card);border-radius:10px;padding:12px 18px;min-width:132px;}
.card .num{font-size:22px;font-weight:600;}
.card .lbl{font-size:11px;color:var(--sub);text-transform:uppercase;
           letter-spacing:.4px;margin-top:2px;}
.toolbar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:16px;}
input[type=text]{background:var(--surface);border:none;border-radius:6px;
  padding:8px 12px;color:var(--text);font-size:13px;min-width:280px;
  font-family:inherit;}
input[type=text]:focus{outline:1px solid var(--accent);}
button{background:var(--muted);border:none;border-radius:6px;padding:8px 14px;
  color:var(--text);font-size:12px;font-family:inherit;cursor:pointer;}
button:hover{background:var(--accent);color:var(--bg);}
table{border-collapse:collapse;width:100%;}
#overview{background:var(--card);border-radius:10px;overflow:hidden;
          margin-bottom:26px;}
#overview th{background:var(--surface);color:var(--sub);font-size:11px;
  text-transform:uppercase;letter-spacing:.4px;text-align:left;padding:11px 12px;
  cursor:pointer;user-select:none;white-space:nowrap;}
#overview th:hover{color:var(--accent);}
#overview td{padding:9px 12px;border-top:1px solid var(--surface);font-size:13px;}
#overview tbody tr:hover{background:var(--surface);}
#overview td.doc{cursor:pointer;color:var(--text);}
#overview td.doc:hover{color:var(--accent);text-decoration:underline;}
.badge{display:inline-block;min-width:28px;text-align:center;padding:2px 8px;
  border-radius:20px;font-size:12px;font-weight:600;}
.badge.zero{background:rgba(166,227,161,.16);color:var(--ok);}
.badge.some{background:rgba(240,165,0,.18);color:var(--accent);}
.badge.muted{background:var(--surface);color:var(--sub);font-weight:400;}
details{background:var(--card);border-radius:10px;margin-bottom:10px;
        padding:2px 14px;}
details.doc{padding:6px 16px;}
details.sub{background:var(--surface);margin:8px 0;}
details.cat{background:rgba(49,50,68,.6);}
summary{cursor:pointer;padding:10px 2px;font-weight:600;list-style:none;}
summary::-webkit-details-marker{display:none;}
summary:before{content:"+";color:var(--accent);font-weight:700;
               display:inline-block;width:16px;}
details[open]>summary:before{content:"\\2013";}
details.doc>summary{font-size:16px;}
summary .pills{float:right;font-weight:400;}
summary .pills span{margin-left:6px;}
.note{color:var(--sub);font-size:12px;margin:6px 0 12px;}
table.inner{margin:4px 0 14px;background:var(--bg);border-radius:8px;
            overflow:hidden;}
table.inner th{background:var(--muted);color:var(--sub);font-size:11px;
  text-transform:uppercase;letter-spacing:.4px;text-align:left;padding:8px 12px;}
table.inner td{padding:7px 12px;border-top:1px solid var(--surface);
               font-size:12.5px;vertical-align:top;}
table.inner tbody tr:hover{background:var(--surface);}
.footer{color:var(--sub);font-size:11px;margin-top:28px;line-height:1.8;
        border-top:1px solid var(--surface);padding-top:14px;}
@media print{
  body{background:#fff;color:#000;padding:0;}
  .toolbar,#overview th{cursor:auto;}
  .card,details,#overview{background:#f4f4f4;color:#000;}
  .badge{border:1px solid #999;color:#000;background:#fff;}
}
"""


REPORT_JS = u"""
function nodes(sel){return Array.prototype.slice.call(document.querySelectorAll(sel));}

function filterDocs(){
  var term = document.getElementById('docFilter').value.toLowerCase();
  nodes('#overview tbody tr').forEach(function(row){
    row.style.display = row.getAttribute('data-name').indexOf(term) > -1 ? '' : 'none';
  });
  nodes('details.doc').forEach(function(box){
    box.style.display = box.getAttribute('data-name').indexOf(term) > -1 ? '' : 'none';
  });
}

function sortTable(idx, numeric){
  var body = document.querySelector('#overview tbody');
  var rows = Array.prototype.slice.call(body.rows);
  var same = body.getAttribute('data-col') === String(idx);
  var dir = (same && body.getAttribute('data-dir') === 'asc') ? 'desc' : 'asc';
  rows.sort(function(a, b){
    var x = a.cells[idx].getAttribute('data-sort');
    var y = b.cells[idx].getAttribute('data-sort');
    if(x === null){ x = a.cells[idx].textContent.trim(); }
    if(y === null){ y = b.cells[idx].textContent.trim(); }
    if(numeric){
      x = parseFloat(x); y = parseFloat(y);
      if(isNaN(x)){ x = -1; } if(isNaN(y)){ y = -1; }
      return dir === 'asc' ? x - y : y - x;
    }
    return dir === 'asc' ? x.localeCompare(y) : y.localeCompare(x);
  });
  rows.forEach(function(row){ body.appendChild(row); });
  body.setAttribute('data-dir', dir);
  body.setAttribute('data-col', String(idx));
}

function toggleAll(open){
  nodes('details').forEach(function(box){ box.open = open; });
}

function goDoc(id){
  var box = document.getElementById(id);
  if(!box){ return; }
  box.open = true;
  box.scrollIntoView({behavior:'smooth', block:'start'});
}
"""


def html_doc_section(index, row):
    """One collapsible document block."""
    out = []
    anchor = "doc-{0}".format(index)
    pills = u'<span class="pills">{0}{1}{2}{3}</span>'.format(
        badge(row.ColDwgLinks), badge(row.ColWarnings),
        badge(row.ColGrids),
        badge(row.ColUnused if row.Unused is not None else "not scanned"))

    out.append(u'<details class="doc" id="{0}" data-name="{1}">'.format(
        anchor, esc(row.RawName.lower())))
    out.append(u"<summary>{0} <span class=\"note\">({1})</span>{2}</summary>".format(
        esc(row.RawName), esc(row.Status), pills))

    if not row.Scanned:
        out.append(u'<p class="note">This document could not be opened, so '
                   u'nothing was inspected.</p></details>')
        return u"".join(out)

    # DWG / CAD
    cad_rows = [e.Fields for e in row.CadEntries if e.Fields]
    out.append(u'<details class="sub"><summary>DWG / CAD '
               u'({0} link(s), {1} import(s), {2} other CAD)</summary>'.format(
                   row.DwgLinks, row.DwgImports, row.OtherCad))
    out.append(table(["File", "Kind", "Scope"], cad_rows,
                     "No CAD files in this document."))
    out.append(u"</details>")

    # Warnings
    warn_rows = [e.Fields for e in row.WarningEntries if e.Fields]
    out.append(u'<details class="sub"><summary>Warnings ({0})'
               u'</summary>'.format(row.Warnings))
    out.append(table(["Count", "Warning"], warn_rows,
                     "No warnings stored in this document."))
    out.append(u"</details>")

    # Levels and Grids
    lg_rows = [e.Fields for e in row.WorksetEntries if e.Fields]
    if row.Workshared:
        lg_label = u"Levels + Grids ({0} level(s), {1} grid(s) on a wrong " \
                   u"workset)".format(row.BadLevels, row.BadGrids)
    else:
        lg_label = u"Levels + Grids (model is not workshared)"
    out.append(u'<details class="sub"><summary>{0}</summary>'.format(
        esc(lg_label)))
    if lg_rows:
        out.append(table(["Element", "Name", "Current workset"], lg_rows))
    else:
        for entry in row.WorksetEntries:
            out.append(u'<p class="note">{0}</p>'.format(esc(entry.Display)))
    out.append(u"</details>")

    # Unused items
    if row.Unused is None:
        out.append(u'<details class="sub"><summary>Unused Items (not scanned)'
                   u'</summary><p class="note">Open the Unused Items tab for '
                   u'this document, or press Scan All Unused, then export '
                   u'again.</p></details>')
        out.append(u"</details>")
        return u"".join(out)

    result = row.Unused
    out.append(u'<details class="sub"><summary>Unused Items '
               u'({0} famil(ies), {1} type(s) under used families)'
               u'</summary>'.format(result.TotalUnusedFamilies,
                                    result.TotalUnusedTypes))
    clean = 0
    for stat in result.Categories:
        if not stat.has_findings():
            clean += 1
            continue
        out.append(u'<details class="cat"><summary>Category: {0}</summary>'
                   .format(esc(stat.Name)))
        out.append(u'<p class="note">{0}</p>'.format(esc(stat.summary_line())))
        if stat.UnusedFamilies:
            out.append(table(
                ["Unused family", "Types"],
                [(name, u"{0}".format(count))
                 for name, count in stat.UnusedFamilies]))
        if stat.UnusedTypes:
            out.append(table(
                ["Unused type under a used family"],
                [(text,) for text in stat.UnusedTypes]))
        out.append(u"</details>")
    out.append(u'<p class="note">{0} further categor(ies) had nothing '
               u'unused.</p>'.format(clean))
    out.append(u"</details>")

    out.append(u"</details>")
    return u"".join(out)


def build_report_html(rows):
    scanned = [r for r in rows if r.Scanned]
    workshared = [r for r in scanned if r.Workshared]
    unused_done = [r for r in scanned if r.Unused is not None]

    totals = {
        "docs": len(scanned),
        "dwg_links": sum([r.DwgLinks for r in scanned]),
        "dwg_imports": sum([r.DwgImports for r in scanned]),
        "warnings": sum([r.Warnings for r in scanned]),
        "levels": sum([r.BadLevels for r in workshared]),
        "grids": sum([r.BadGrids for r in workshared]),
        "un_fams": sum([r.Unused.TotalUnusedFamilies for r in unused_done]),
        "un_types": sum([r.Unused.TotalUnusedTypes for r in unused_done]),
    }

    out = []
    out.append(u"<!DOCTYPE html><html lang=\"en\"><head>")
    out.append(u"<meta charset=\"utf-8\">")
    out.append(u"<title>Link Inspector - {0}</title>".format(
        esc(doc_title(doc, "Model"))))
    out.append(u"<style>")
    out.append(REPORT_CSS)
    out.append(u"</style></head><body>")

    out.append(u"<h1>Link Inspector Report</h1>")
    out.append(u'<div class="meta">Host model: <b>{0}</b><br>'
               u'Generated: {1}<br>'
               u'Accepted Level/Grid worksets: {2}</div>'.format(
                   esc(doc_title(doc, "Unsaved")),
                   esc(DateTime.Now.ToString("yyyy-MM-dd HH:mm")),
                   esc(", ".join(VALID_LG_WORKSETS))))

    cards = [("Documents", totals["docs"]),
             ("DWG links", totals["dwg_links"]),
             ("DWG imports", totals["dwg_imports"]),
             ("Warnings", totals["warnings"]),
             ("Levels off workset", totals["levels"]),
             ("Grids off workset", totals["grids"]),
             ("Unused families", totals["un_fams"]),
             ("Unused types", totals["un_types"])]
    out.append(u'<div class="cards">')
    for label, value in cards:
        out.append(u'<div class="card"><div class="num">{0}</div>'
                   u'<div class="lbl">{1}</div></div>'.format(
                       value, esc(label)))
    out.append(u"</div>")

    out.append(u'<div class="toolbar">')
    out.append(u'<input type="text" id="docFilter" placeholder="Filter '
               u'documents..." oninput="filterDocs()">')
    out.append(u'<button onclick="toggleAll(true)">Expand all</button>')
    out.append(u'<button onclick="toggleAll(false)">Collapse all</button>')
    out.append(u'<button onclick="window.print()">Print</button>')
    out.append(u"</div>")

    # overview table
    out.append(u'<table id="overview"><thead><tr>')
    headers = [("Document", False), ("Status", False), ("DWG links", True),
               ("DWG imports", True), ("Warnings", True), ("Bad levels", True),
               ("Bad grids", True), ("Unused fam / type", True)]
    for idx, pair in enumerate(headers):
        label, numeric = pair
        out.append(u'<th onclick="sortTable({0},{1})">{2}</th>'.format(
            idx, "true" if numeric else "false", esc(label)))
    out.append(u'</tr></thead><tbody data-col="-1" data-dir="asc">')

    for index, row in enumerate(rows):
        if row.Unused is not None:
            unused_text = row.ColUnused
            unused_sort = (row.Unused.TotalUnusedFamilies +
                           row.Unused.TotalUnusedTypes)
        else:
            unused_text = "not scanned"
            unused_sort = -1

        def sort_val(text):
            try:
                return int(text)
            except (ValueError, TypeError):
                return -1

        out.append(u'<tr data-name="{0}">'.format(esc(row.RawName.lower())))
        out.append(u'<td class="doc" onclick="goDoc(\'doc-{0}\')">{1}</td>'
                   .format(index, esc(row.RawName)))
        out.append(u"<td>{0}</td>".format(esc(row.Status)))
        for text in (row.ColDwgLinks, row.ColDwgImports, row.ColWarnings,
                     row.ColLevels, row.ColGrids):
            out.append(u'<td data-sort="{0}">{1}</td>'.format(
                sort_val(text), badge(text)))
        out.append(u'<td data-sort="{0}">{1}</td>'.format(
            unused_sort, badge(unused_text)))
        out.append(u"</tr>")
    out.append(u"</tbody></table>")

    out.append(u"<h2>Per document</h2>")
    for index, row in enumerate(rows):
        out.append(html_doc_section(index, row))

    out.append(u'<div class="footer">'
               u'Unused items are found by counting placed instances per type. '
               u'Types referenced only by other types - curtain panels and '
               u'mullions inside a curtain wall type, profiles, nested '
               u'sub-families - are reported as unused even though Revit '
               u'cannot purge them. Treat the result as triage, not a purge '
               u'list.<br>Warning counts come from the link file as it was '
               u'loaded; reload the link after someone cleans warnings in it.'
               u'</div>')

    out.append(u"<script>")
    out.append(REPORT_JS)
    out.append(u"</script></body></html>")
    return u"".join(out)


def safe_file_name(text):
    keep = "-_. "
    return u"".join([c if (c.isalnum() or c in keep) else "_" for c in text])


def export_html(rows):
    """Write the report next to the temp folder and open it. Returns path."""
    html = build_report_html(rows)
    file_name = u"LinkInspector_{0}_{1}.html".format(
        safe_file_name(doc_title(doc, "Model")),
        DateTime.Now.ToString("yyyyMMdd_HHmmss"))
    path = Path.Combine(Path.GetTempPath(), file_name)
    File.WriteAllText(path, html, Encoding.UTF8)
    open_file(path)
    return path


def open_file(path):
    """Open a file with the shell, trying every route available."""
    if Process is not None:
        try:
            Process.Start(path)
            return
        except Exception:
            pass
    try:
        import os
        os.startfile(path)
        return
    except Exception:
        pass
    TaskDialog.Show("Link Inspector",
                    "The report was saved but could not be opened "
                    "automatically:\n\n{0}".format(path))


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Link Inspector"
        Height="720" Width="1300"
        WindowStartupLocation="CenterScreen"
        Background="#1E1E2E">

  <Window.Resources>
    <Style TargetType="TextBlock">
      <Setter Property="Foreground" Value="#CDD6F4"/>
      <Setter Property="FontFamily" Value="Segoe UI"/>
    </Style>

    <Style x:Key="AccentButton" TargetType="Button">
      <Setter Property="Foreground" Value="#1E1E2E"/>
      <Setter Property="Background" Value="#F0A500"/>
      <Setter Property="FontFamily" Value="Segoe UI"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
      <Setter Property="Padding" Value="16,7"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border Background="{TemplateBinding Background}" CornerRadius="6">
              <ContentPresenter HorizontalAlignment="Center"
                                VerticalAlignment="Center"
                                Margin="{TemplateBinding Padding}"/>
            </Border>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="GhostButton" TargetType="Button">
      <Setter Property="Foreground" Value="#CDD6F4"/>
      <Setter Property="Background" Value="#45475A"/>
      <Setter Property="FontFamily" Value="Segoe UI"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="Padding" Value="16,7"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border Background="{TemplateBinding Background}" CornerRadius="6">
              <ContentPresenter HorizontalAlignment="Center"
                                VerticalAlignment="Center"
                                Margin="{TemplateBinding Padding}"/>
            </Border>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="TabToggle" TargetType="ToggleButton">
      <Setter Property="Foreground" Value="#A6ADC8"/>
      <Setter Property="Background" Value="#313244"/>
      <Setter Property="FontFamily" Value="Segoe UI"/>
      <Setter Property="FontSize" Value="11"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
      <Setter Property="Padding" Value="10,5"/>
      <Setter Property="Margin" Value="0,0,6,0"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ToggleButton">
            <Border x:Name="Bd" Background="{TemplateBinding Background}"
                    CornerRadius="6">
              <ContentPresenter HorizontalAlignment="Center"
                                VerticalAlignment="Center"
                                Margin="{TemplateBinding Padding}"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsChecked" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#F0A500"/>
                <Setter Property="Foreground" Value="#1E1E2E"/>
              </Trigger>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#45475A"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style TargetType="GridViewColumnHeader">
      <Setter Property="Background" Value="#313244"/>
      <Setter Property="Foreground" Value="#A6ADC8"/>
      <Setter Property="FontFamily" Value="Segoe UI"/>
      <Setter Property="FontSize" Value="11"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
      <Setter Property="Height" Value="28"/>
      <Setter Property="BorderThickness" Value="0"/>
      <Setter Property="HorizontalContentAlignment" Value="Left"/>
      <Setter Property="Padding" Value="8,0"/>
    </Style>

    <Style TargetType="ListViewItem">
      <Setter Property="Foreground" Value="#CDD6F4"/>
      <Setter Property="FontFamily" Value="Segoe UI"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="Height" Value="26"/>
      <Setter Property="Background" Value="Transparent"/>
      <Setter Property="BorderThickness" Value="0"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ListViewItem">
            <Border x:Name="Bd" Background="{TemplateBinding Background}"
                    CornerRadius="4" Padding="4,0">
              <GridViewRowPresenter VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#313244"/>
              </Trigger>
              <Trigger Property="IsSelected" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#45475A"/>
                <Setter Property="Foreground" Value="#F0A500"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style TargetType="TreeViewItem">
      <Setter Property="FontFamily" Value="Segoe UI"/>
      <Setter Property="FontSize" Value="11"/>
      <Setter Property="Margin" Value="0,1,0,1"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="TreeViewItem">
            <StackPanel>
              <Border x:Name="Bd" Background="Transparent"
                      CornerRadius="4" Padding="2,1">
                <Grid>
                  <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="18"/>
                    <ColumnDefinition Width="*"/>
                  </Grid.ColumnDefinitions>
                  <ToggleButton x:Name="Expander" Grid.Column="0"
                                Focusable="False" ClickMode="Press"
                                IsChecked="{Binding IsExpanded,
                                  RelativeSource={RelativeSource TemplatedParent}}">
                    <ToggleButton.Template>
                      <ControlTemplate TargetType="ToggleButton">
                        <Border Background="Transparent"
                                Width="16" Height="16">
                          <TextBlock x:Name="Sign" Text="+"
                                     Foreground="#F0A500" FontSize="12"
                                     FontWeight="Bold"
                                     HorizontalAlignment="Center"
                                     VerticalAlignment="Center"/>
                        </Border>
                        <ControlTemplate.Triggers>
                          <Trigger Property="IsChecked" Value="True">
                            <Setter TargetName="Sign" Property="Text"
                                    Value="-"/>
                          </Trigger>
                        </ControlTemplate.Triggers>
                      </ControlTemplate>
                    </ToggleButton.Template>
                  </ToggleButton>
                  <ContentPresenter Grid.Column="1" ContentSource="Header"
                                    VerticalAlignment="Center"/>
                </Grid>
              </Border>
              <ItemsPresenter x:Name="ItemsHost" Margin="16,0,0,0"/>
            </StackPanel>
            <ControlTemplate.Triggers>
              <Trigger Property="IsExpanded" Value="False">
                <Setter TargetName="ItemsHost" Property="Visibility"
                        Value="Collapsed"/>
              </Trigger>
              <Trigger Property="HasItems" Value="False">
                <Setter TargetName="Expander" Property="Visibility"
                        Value="Hidden"/>
              </Trigger>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#3B3B52"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
  </Window.Resources>

  <Grid Margin="16">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <StackPanel Grid.Row="0" Margin="0,0,0,10">
      <TextBlock Text="Link Inspector" FontSize="19" FontWeight="Bold"/>
      <TextBlock x:Name="SummaryText" Margin="0,4,0,0"
                 FontSize="12" Foreground="#A6ADC8"/>
    </StackPanel>

    <Border Grid.Row="1" Background="#2A2A3C" CornerRadius="6"
            Padding="10,6" Margin="0,0,0,10">
      <Grid>
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="Auto"/>
          <ColumnDefinition Width="*"/>
        </Grid.ColumnDefinitions>
        <TextBlock Grid.Column="0" Text="Search" VerticalAlignment="Center"
                   Foreground="#A6ADC8" FontSize="12" Margin="0,0,10,0"/>
        <TextBox x:Name="SearchBox" Grid.Column="1"
                 Background="#313244" Foreground="#CDD6F4"
                 CaretBrush="#F0A500" BorderThickness="0"
                 FontFamily="Segoe UI" FontSize="12" Padding="6,4"/>
      </Grid>
    </Border>

    <Grid Grid.Row="2">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="1.55*"/>
        <ColumnDefinition Width="12"/>
        <ColumnDefinition Width="1*"/>
      </Grid.ColumnDefinitions>

      <Border Grid.Column="0" Background="#2A2A3C" CornerRadius="8" Padding="8">
        <ListView x:Name="LinkList" Background="Transparent"
                  BorderThickness="0" Foreground="#CDD6F4"
                  ScrollViewer.HorizontalScrollBarVisibility="Disabled">
          <ListView.View>
            <GridView>
              <GridViewColumn Header="Document" Width="212"
                              DisplayMemberBinding="{Binding Name}"/>
              <GridViewColumn Header="Status" Width="92"
                              DisplayMemberBinding="{Binding Status}"/>
              <GridViewColumn Header="DWG Links" Width="72"
                              DisplayMemberBinding="{Binding ColDwgLinks}"/>
              <GridViewColumn Header="DWG Imports" Width="84"
                              DisplayMemberBinding="{Binding ColDwgImports}"/>
              <GridViewColumn Header="Warnings" Width="68"
                              DisplayMemberBinding="{Binding ColWarnings}"/>
              <GridViewColumn Header="Bad Levels" Width="72"
                              DisplayMemberBinding="{Binding ColLevels}"/>
              <GridViewColumn Header="Bad Grids" Width="68"
                              DisplayMemberBinding="{Binding ColGrids}"/>
              <GridViewColumn Header="Unused Fam / Type" Width="112"
                              DisplayMemberBinding="{Binding ColUnused}"/>
            </GridView>
          </ListView.View>
        </ListView>
      </Border>

      <Border Grid.Column="2" Background="#2A2A3C" CornerRadius="8" Padding="10">
        <Grid>
          <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
          </Grid.RowDefinitions>

          <WrapPanel Grid.Row="0" Margin="0,0,0,8">
            <ToggleButton x:Name="TabCad" Content="DWG / CAD"
                          Style="{StaticResource TabToggle}" IsChecked="True"/>
            <ToggleButton x:Name="TabWarn" Content="Warnings"
                          Style="{StaticResource TabToggle}"/>
            <ToggleButton x:Name="TabWorkset" Content="Levels + Grids"
                          Style="{StaticResource TabToggle}"/>
            <ToggleButton x:Name="TabUnused" Content="Unused Items"
                          Style="{StaticResource TabToggle}"/>
          </WrapPanel>

          <TextBlock x:Name="DetailHeader" Grid.Row="1"
                     Text="Select a document" FontSize="12"
                     FontWeight="SemiBold" Foreground="#A6ADC8"
                     Margin="0,0,0,8" TextWrapping="Wrap"/>

          <ListBox x:Name="DetailList" Grid.Row="2" Background="#313244"
                   Foreground="#CDD6F4" BorderThickness="0"
                   FontFamily="Segoe UI" FontSize="11"
                   DisplayMemberPath="Display"
                   ScrollViewer.HorizontalScrollBarVisibility="Auto"/>

          <TreeView x:Name="CategoryTree" Grid.Row="2" Background="#313244"
                    BorderThickness="0" Padding="4"
                    Visibility="Collapsed"
                    ScrollViewer.HorizontalScrollBarVisibility="Auto"/>
        </Grid>
      </Border>
    </Grid>

    <StackPanel Grid.Row="3" Orientation="Horizontal"
                HorizontalAlignment="Right" Margin="0,12,0,0">
      <Button x:Name="ScanAllButton" Content="Scan All Unused"
              Style="{StaticResource GhostButton}" Margin="0,0,8,0"/>
      <Button x:Name="ExportButton" Content="Export HTML Report"
              Style="{StaticResource AccentButton}" Margin="0,0,8,0"/>
      <Button x:Name="CloseButton" Content="Close"
              Style="{StaticResource GhostButton}"/>
    </StackPanel>
  </Grid>
</Window>
"""


def make_node(text, text_brush, bold=False, expanded=False):
    label = TextBlock()
    label.Text = text
    label.Foreground = text_brush
    label.TextWrapping = TextWrapping.Wrap
    if bold:
        label.FontWeight = FontWeights.SemiBold
    node = TreeViewItem()
    node.Header = label
    node.IsExpanded = expanded
    return node


def populate_tree(tree, result):
    """Fill the TreeView with one collapsible node per category."""
    tree.Items.Clear()

    clean = 0
    for stat in result.Categories:
        if not stat.has_findings():
            clean += 1
            continue

        node = make_node(u"Category: {0}".format(stat.Name),
                         BRUSH_ACCENT, True)
        node.Items.Add(make_node(stat.summary_line(), BRUSH_SUB))

        if stat.UnusedFamilies:
            branch = make_node(u"Unused families ({0})".format(
                len(stat.UnusedFamilies)), BRUSH_TEXT)
            for fam_name, type_count in stat.UnusedFamilies:
                branch.Items.Add(make_node(
                    u"{0}  ({1} type(s))".format(fam_name, type_count),
                    BRUSH_SUB))
            node.Items.Add(branch)

        if stat.UnusedTypes:
            branch = make_node(u"Unused types under used families ({0})".format(
                len(stat.UnusedTypes)), BRUSH_TEXT)
            for text in stat.UnusedTypes:
                branch.Items.Add(make_node(text, BRUSH_SUB))
            node.Items.Add(branch)

        tree.Items.Add(node)

    tree.Items.Add(make_node(
        u"{0} other categor(ies) had nothing unused.".format(clean),
        BRUSH_SUB))


def show_window(rows):
    window = XamlReader.Parse(XAML)

    summary_text = window.FindName("SummaryText")
    search_box = window.FindName("SearchBox")
    link_list = window.FindName("LinkList")
    tab_cad = window.FindName("TabCad")
    tab_warn = window.FindName("TabWarn")
    tab_workset = window.FindName("TabWorkset")
    tab_unused = window.FindName("TabUnused")
    detail_header = window.FindName("DetailHeader")
    detail_list = window.FindName("DetailList")
    category_tree = window.FindName("CategoryTree")
    scan_all_button = window.FindName("ScanAllButton")
    export_button = window.FindName("ExportButton")
    close_button = window.FindName("CloseButton")

    scanned = [r for r in rows if r.Scanned]
    workshared = [r for r in scanned if r.Workshared]
    unreadable = len(rows) - len(scanned)

    summary = ("{0} documents  |  {1} DWG links  |  {2} DWG imports  |  "
               "{3} warnings  |  {4} levels + {5} grids on a wrong workset"
               ).format(len(scanned),
                        sum([r.DwgLinks for r in scanned]),
                        sum([r.DwgImports for r in scanned]),
                        sum([r.Warnings for r in scanned]),
                        sum([r.BadLevels for r in workshared]),
                        sum([r.BadGrids for r in workshared]))
    if unreadable:
        summary += "  |  {0} not readable".format(unreadable)
    summary_text.Text = summary

    mode = ["cad"]

    def set_source(items):
        link_list.ItemsSource = List[object](items)

    def apply_filter():
        text = (search_box.Text or "").strip().lower()
        if not text:
            set_source(rows)
        else:
            set_source([r for r in rows if text in r.RawName.lower()])

    def show_list():
        category_tree.Visibility = Visibility.Collapsed
        detail_list.Visibility = Visibility.Visible

    def show_tree():
        detail_list.Visibility = Visibility.Collapsed
        category_tree.Visibility = Visibility.Visible

    def refresh_detail():
        row = link_list.SelectedItem
        if row is None:
            show_list()
            detail_header.Text = "Select a document"
            detail_list.ItemsSource = None
            return
        if not row.Scanned:
            show_list()
            detail_header.Text = u"{0} {1} {2}".format(
                row.RawName, DASH, row.Status)
            detail_list.ItemsSource = None
            return

        if mode[0] == "unused":
            if row.Unused is None:
                Mouse.OverrideCursor = Cursors.Wait
                try:
                    row.inspect_unused()
                finally:
                    Mouse.OverrideCursor = None
                try:
                    link_list.Items.Refresh()
                    link_list.SelectedItem = row
                except Exception:
                    pass
            result = row.Unused
            detail_header.Text = (
                u"{0} {1} {2} unused famil(ies), {3} unused type(s) under "
                u"used families  (of {4} families / {5} types)").format(
                    row.RawName, DASH, result.TotalUnusedFamilies,
                    result.TotalUnusedTypes, result.TotalFamilies,
                    result.TotalTypes)
            populate_tree(category_tree, result)
            show_tree()
            return

        show_list()

        if mode[0] == "cad":
            entries = row.CadEntries
            label = u"{0} DWG link(s), {1} import(s), {2} other CAD".format(
                row.DwgLinks, row.DwgImports, row.OtherCad)
        elif mode[0] == "warn":
            entries = row.WarningEntries
            label = u"{0} warning(s)".format(row.Warnings)
        else:
            entries = row.WorksetEntries
            if row.Workshared:
                label = u"{0} level(s), {1} grid(s) on a wrong workset".format(
                    row.BadLevels, row.BadGrids)
            else:
                label = "Not workshared"

        detail_header.Text = u"{0} {1} {2}".format(row.RawName, DASH, label)
        detail_list.ItemsSource = List[object](entries) if entries else None

    def set_mode(key):
        mode[0] = key
        tab_cad.IsChecked = (key == "cad")
        tab_warn.IsChecked = (key == "warn")
        tab_workset.IsChecked = (key == "workset")
        tab_unused.IsChecked = (key == "unused")
        refresh_detail()

    def on_search(sender, args):
        apply_filter()

    def on_select(sender, args):
        refresh_detail()

    def on_tab_cad(sender, args):
        set_mode("cad")

    def on_tab_warn(sender, args):
        set_mode("warn")

    def on_tab_workset(sender, args):
        set_mode("workset")

    def on_tab_unused(sender, args):
        set_mode("unused")

    def on_scan_all(sender, args):
        current = link_list.SelectedItem
        Mouse.OverrideCursor = Cursors.Wait
        try:
            for row in rows:
                row.inspect_unused()
        finally:
            Mouse.OverrideCursor = None
        try:
            link_list.Items.Refresh()
            if current is not None:
                link_list.SelectedItem = current
        except Exception:
            pass
        scan_all_button.Content = "Unused Scanned"
        refresh_detail()

    def on_export(sender, args):
        Mouse.OverrideCursor = Cursors.Wait
        try:
            export_html(rows)
        except Exception as err:
            TaskDialog.Show("Link Inspector",
                            "Could not write the HTML report:\n\n{0}".format(err))
            return
        finally:
            Mouse.OverrideCursor = None
        export_button.Content = "Report Opened"

    def on_close_click(sender, args):
        window.Close()

    frame = DispatcherFrame()

    def on_closed(sender, args):
        frame.Continue = False

    search_box.TextChanged += TextChangedEventHandler(on_search)
    link_list.SelectionChanged += SelectionChangedEventHandler(on_select)
    tab_cad.Click += RoutedEventHandler(on_tab_cad)
    tab_warn.Click += RoutedEventHandler(on_tab_warn)
    tab_workset.Click += RoutedEventHandler(on_tab_workset)
    tab_unused.Click += RoutedEventHandler(on_tab_unused)
    scan_all_button.Click += RoutedEventHandler(on_scan_all)
    export_button.Click += RoutedEventHandler(on_export)
    close_button.Click += RoutedEventHandler(on_close_click)
    window.Closed += EventHandler(on_closed)

    set_source(rows)

    window.Show()
    Dispatcher.PushFrame(frame)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    rows = build_rows()
    if len(rows) <= 1:
        host = rows[0]
        TaskDialog.Show(
            "Link Inspector",
            "No Revit links were found in this model.\n\n"
            "Host model:\n"
            "  DWG links   : {0}\n"
            "  DWG imports : {1}\n"
            "  Warnings    : {2}\n"
            "  Bad levels  : {3}\n"
            "  Bad grids   : {4}".format(
                host.DwgLinks, host.DwgImports, host.Warnings,
                host.ColLevels, host.ColGrids))
        return
    show_window(rows)


main()
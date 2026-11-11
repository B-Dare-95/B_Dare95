# -*- coding: utf-8 -*-
__doc__ = """__________________________________________________
Description:

Manages and inspects every Revit link in one window: its workset, Room Bounding, whether it is pinned, where it sits, and what is inside it.

Under each link a status line checks its position: Shared Coordinates, Base Point and Internal Origin get a check mark when the link sits there, or the offset when it doesn't, followed by its rotation and how many grids and levels with the same name line up exactly. Pick Internal Origin, Base Point or Shared Coords to move a link there; it is pinned again after the move.

A health line sums up what is inside each loaded link. Click a link to show it in the inspector on the right: DWG / CAD, the Revit links inside it, warnings, levels and grids on the wrong workset, items left on Workset1, and unused families and types. Export HTML report writes all of it to a page you can share.
__________________________________________________
How-to:

-> Click on the button
-> Pick a workset for each link, or use Set all visible to
-> Check or uncheck Room bounding and Pinned
-> Read the status line under each link, and click a position to move it there
-> Click a link to show it in the inspector on the right, and switch between the tabs
-> In Unused Items, click Scan unused to check that link's families and types
-> Click Export HTML report for a shareable report of every link
-> Changed links get a yellow dot; nothing changes until you click Apply changes
-> A summary shows what was changed
__________________________________________________
Author: Mohamed Bedair"""

__author__ = "Mohamed Bedair"

import math

import clr

clr.AddReference("System")
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")
clr.AddReference("System.Xml")

from Autodesk.Revit.DB import (
    Arc,
    BasePoint,
    BuiltInCategory,
    BuiltInParameter,
    CADLinkType,
    CategoryType,
    ElementId,
    ElementTransformUtils,
    ElementWorksetFilter,
    FilteredElementCollector,
    FilteredWorksetCollector,
    Grid,
    ImportInstance,
    Level,
    Line,
    ModelPathUtils,
    RevitLinkInstance,
    RevitLinkType,
    Transaction,
    TransactionGroup,
    Transform,
    WorksetKind,
    WorksharingUtils,
    XYZ,
)
from Autodesk.Revit.UI import TaskDialog, TaskDialogCommonButtons, TaskDialogResult

from System import Action, Array, DateTime, EventHandler, Object, String
from System.Collections.Generic import List
from System.IO import File, Path
from System.Text import Encoding
from System.Windows import (
    CornerRadius,
    FontWeights,
    HorizontalAlignment,
    RoutedEventHandler,
    TextTrimming,
    TextWrapping,
    Thickness,
    VerticalAlignment,
    Visibility,
)
from System.Windows.Controls import (
    Border,
    Button,
    CheckBox,
    ComboBox,
    Dock,
    DockPanel,
    GridView,
    GridViewColumn,
    GroupStyle,
    ListView,
    Orientation,
    StackPanel,
    TextBlock,
    TextBox,
    TextChangedEventHandler,
    WrapPanel,
)
from System.Windows.Controls import Grid as WpfGrid
from System.Windows.Controls.Primitives import ToggleButton
from System.Windows.Data import ListCollectionView, PropertyGroupDescription
from System.Windows.Documents import Run
from System.Windows.Input import (
    Cursors,
    Mouse,
    MouseButtonEventHandler,
)
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Markup import XamlReader
from System.Windows.Media import BrushConverter
from System.Windows.Shapes import Ellipse
from System.Windows.Threading import Dispatcher, DispatcherFrame, DispatcherPriority
from bd_combo_search import enable_combo_search
import bd_core as bd

try:
    from System.Diagnostics import Process, ProcessStartInfo
except ImportError:
    Process = None
    ProcessStartInfo = None

doc = __revit__.ActiveUIDocument.Document  # noqa: F821
TOOL = "Link Manager"

# ---------------------------------------------------------------------------
# Palette (IBM Carbon)
# ---------------------------------------------------------------------------
C_TEXT = "#F4F4F4"
C_SUBTEXT = "#A8A8A8"
C_MUTED = "#8D8D8D"
C_ACCENT = "#F1C21B"
C_OK = "#42BE65"
C_WARN = "#F1C21B"
C_BAD = "#FF8389"
C_PANEL = "#1B1B1B"
C_LINE = "#2E2E2E"
CHIP = {
    "ok": ("#0E2A18", "#A7F0BA"),
    "warn": ("#3A2E06", "#FDDC69"),
    "bad": ("#4A0E12", "#FFB3B8"),
    "na": ("#2E2E2E", "#8D8D8D"),
}

_BC = BrushConverter()
_BRUSH_CACHE = {}


def brush(hex_string):
    if hex_string not in _BRUSH_CACHE:
        _BRUSH_CACHE[hex_string] = _BC.ConvertFromString(hex_string)
    return _BRUSH_CACHE[hex_string]


# Column widths, shared between the header row and the data rows
W_WORKSET = 190
W_ROOM = 96
W_PIN = 64
W_POS = 262

TOL = 0.001  # ft (0.3 mm)
ANG_TOL = 1e-4  # rad
POSITIONS = ("Internal Origin", "Base Point", "Shared Coordinates")
SEG_LABEL = {"Internal Origin": "Internal Origin", "Base Point": "Base Point",
             "Shared Coordinates": "Shared Coords"}

# Worksets Levels and Grids are allowed to live on (match the BIM Execution Plan)
VALID_LG_WORKSETS = [
    "shared levels and grids",
    "shared views, levels, grids",
]
# Worksets whose contents count as "left on the default workset"
DEFAULT_WORKSET_NAMES = [
    "workset1",
]

TABS = ("DWG / CAD", "RVT Links", "Warnings", "Levels + Grids", "Workset1", "Unused Items")
DASH = u"\u2014"
DOT = u"  \u00b7  "

STATUS_TEXT = {
    "Loaded": "Loaded",
    "Unloaded": "Unloaded (all users)",
    "LocallyUnloaded": "Unloaded (this user)",
    "NotFound": "Not Found",
    "InClosedWorkset": "In Closed Workset",
    "Invalid": "Invalid",
}

STATUS_COLOR = {
    "Loaded": C_OK,
    "Unloaded (all users)": C_BAD,
    "Unloaded (this user)": C_WARN,
    "Not Found": C_BAD,
    "In Closed Workset": C_WARN,
    "Invalid": C_BAD,
    "Unknown": C_SUBTEXT,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
id_value = bd.eid_int


element_name = bd.element_name


plural = bd.plural


def fmt_mm(ft):
    return "{0:,} mm".format(int(round(abs(ft) * 304.8)))


def fmt_signed_mm(ft):
    mm = int(round(ft * 304.8))
    if mm == 0:
        return "0 mm"
    return u"{0}{1:,} mm".format(u"+" if mm > 0 else u"\u2212", abs(mm))


def fmt_deg(rad):
    deg = math.degrees(rad)
    if abs(deg) < 0.005:
        return u"0\u00b0"
    return u"{0:.2f}\u00b0".format(deg)


def link_status(el):
    """Readable loading status for a link type element."""
    status = None
    try:
        status = el.GetLinkedFileStatus()
    except AttributeError:
        try:
            status = el.GetExternalFileReference().GetLinkedFileStatus()
        except Exception:
            status = None
    except Exception:
        status = None

    if status is None:
        return "Unknown"
    return STATUS_TEXT.get(str(status), str(status))


def other_user_owner(el):
    """Returns the owning username if somebody else has the element checked out."""
    if not doc.IsWorkshared:
        return ""
    try:
        info = WorksharingUtils.GetWorksharingTooltipInfo(doc, el.Id)
        owner = info.Owner or ""
    except Exception:
        return ""
    if not owner:
        return ""
    try:
        me = doc.Application.Username
    except Exception:
        me = ""
    if owner.lower() == (me or "").lower():
        return ""
    return owner


def workset_param(el):
    try:
        return el.get_Parameter(BuiltInParameter.ELEM_PARTITION_PARAM)
    except Exception:
        return None


def room_bounding_param(el):
    """The link type's Room Bounding setting."""
    try:
        p = el.get_Parameter(BuiltInParameter.WALL_ATTR_ROOM_BOUNDING)
        if p is not None:
            return p
    except Exception:
        pass
    try:
        return el.LookupParameter("Room Bounding")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Position: where a Revit link sits (same checks as Crop by Linked Scopebox)
# ---------------------------------------------------------------------------
def flat(p):
    return XYZ(p.X, p.Y, 0)


def angle_of(t):
    """Rotation of a transform about Z, in radians."""
    return math.atan2(t.BasisX.Y, t.BasisX.X)


def angle_diff(a, b):
    d = a - b
    while d > math.pi:
        d -= 2 * math.pi
    while d < -math.pi:
        d += 2 * math.pi
    return d


def internal_to_shared(d):
    """Internal -> shared transform. The direction of GetTotalTransform is
    confirmed against the base points' SharedPosition instead of assumed."""
    g = d.ActiveProjectLocation.GetTotalTransform()
    try:
        for bp in (BasePoint.GetProjectBasePoint(d), BasePoint.GetSurveyPoint(d)):
            pi, ps = bp.Position, bp.SharedPosition
            e_fwd = g.OfPoint(pi).DistanceTo(ps)
            e_inv = g.Inverse.OfPoint(pi).DistanceTo(ps)
            if abs(e_fwd - e_inv) > 1e-6:
                return g if e_fwd < e_inv else g.Inverse
    except Exception:
        pass
    return g.Inverse


def names_map(d, cls):
    out = {}
    for e in FilteredElementCollector(d).OfClass(cls).ToElements():
        out[e.Name] = e
    return out


def grid_offset(hc, lc, t):
    """Worst offset between the host grid and the transformed link grid.
    Compares position only, not grid length. None = different shape."""
    if isinstance(hc, Arc) and isinstance(lc, Arc):
        c = flat(t.OfPoint(lc.Center))
        return max(c.DistanceTo(flat(hc.Center)), abs(hc.Radius - lc.Radius))
    if isinstance(hc, Line) and isinstance(lc, Line):
        a = flat(hc.GetEndPoint(0))
        d = flat(hc.GetEndPoint(1)).Subtract(a).Normalize()
        worst = 0.0
        for i in (0, 1):
            v = flat(t.OfPoint(lc.GetEndPoint(i))).Subtract(a)
            worst = max(worst, abs(v.X * d.Y - v.Y * d.X))
        return worst
    return None


def off_list(fails):
    parts = []
    for name, off in sorted(fails, key=lambda f: f[0])[:5]:
        parts.append("{0} {1}".format(name, "shape differs" if off is None else "off by " + fmt_mm(off)))
    more = "" if len(fails) <= 5 else ", +{0} more".format(len(fails) - 5)
    return ", ".join(parts) + more


def targets_for(inst, ld):
    """{position: Transform (link internal -> host internal)} that would put the link there."""
    out = {"Internal Origin": Transform.Identity}
    if ld is None:
        return out
    try:
        sh, sl = internal_to_shared(doc), internal_to_shared(ld)
        out["Shared Coordinates"] = sh.Inverse.Multiply(sl)
    except Exception:
        pass
    try:
        hp = BasePoint.GetProjectBasePoint(doc).Position
        lp = BasePoint.GetProjectBasePoint(ld).Position
        out["Base Point"] = Transform.CreateTranslation(hp.Subtract(lp))
    except Exception:
        pass
    return out


def same_place(a, b):
    return a.Origin.DistanceTo(b.Origin) <= TOL and abs(angle_diff(angle_of(a), angle_of(b))) <= ANG_TOL


def check_position(inst):
    """Status chips for one placed Revit link:
    [(kind, text)] for Shared Coordinates, Base Point, Internal Origin, Rotation, Grids, Levels,
    plus the positions it sits on now."""
    ld = inst.GetLinkDocument()
    t = inst.GetTotalTransform()
    rotation = angle_of(t)
    now = []
    chips = {}

    # grids and levels decide whether a mismatch is amber (geometry still lines up) or red
    grids = levels = None
    aligned = True
    if ld is not None:
        host_g, link_g = names_map(doc, Grid), names_map(ld, Grid)
        g_match, g_fail = 0, []
        for name, lg in link_g.items():
            hg = host_g.get(name)
            if hg is None:
                continue
            g_match += 1
            try:
                off = grid_offset(hg.Curve, lg.Curve, t)
            except Exception:
                off = None
            if off is None or off > TOL:
                g_fail.append((name, off))
        if g_match == 0:
            grids = ("na", "Grids: no grid names shared")
        elif not g_fail:
            grids = ("ok", "Grids: {0} of {0} matching".format(g_match))
        else:
            aligned = False
            grids = ("bad", "Grids: {0} of {1} matching ({2})".format(
                g_match - len(g_fail), g_match, off_list(g_fail)))

        host_l, link_l = names_map(doc, Level), names_map(ld, Level)
        l_match, l_fail = 0, []
        for name, ll in link_l.items():
            hl = host_l.get(name)
            if hl is None:
                continue
            l_match += 1
            z = t.OfPoint(XYZ(0, 0, ll.ProjectElevation)).Z
            diff = abs(z - hl.ProjectElevation)
            if diff > TOL:
                l_fail.append((name, diff))
        if l_match == 0:
            levels = ("na", "Levels: no level names shared")
        elif not l_fail:
            levels = ("ok", "Levels: {0} of {0} matching".format(l_match))
        else:
            aligned = False
            levels = ("bad", "Levels: {0} of {1} matching ({2})".format(
                l_match - len(l_fail), l_match, off_list(l_fail)))
    off_kind = "warn" if aligned else "bad"

    # Shared coordinates
    if ld is None:
        chips["Shared Coordinates"] = ("na", "Shared Coordinates: needs the link loaded")
    else:
        try:
            sh, sl = internal_to_shared(doc), internal_to_shared(ld)
            a = sh.OfPoint(t.OfPoint(XYZ.Zero))
            b = sl.OfPoint(XYZ.Zero)
            d = a.Subtract(b)
            va = sh.OfVector(t.OfVector(XYZ.BasisX))
            vb = sl.OfVector(XYZ.BasisX)
            ang = angle_diff(math.atan2(va.Y, va.X), math.atan2(vb.Y, vb.X))
            if d.GetLength() <= TOL and abs(ang) <= ANG_TOL:
                chips["Shared Coordinates"] = ("ok", u"Shared Coordinates: \u2713")
                now.append("Shared Coordinates")
            else:
                chips["Shared Coordinates"] = (off_kind, "Shared Coordinates: off by X {0}, Y {1}, Z {2}, rotation {3}"
                                               .format(fmt_signed_mm(d.X), fmt_signed_mm(d.Y), fmt_signed_mm(d.Z),
                                                       fmt_deg(ang)))
        except Exception as ex:
            chips["Shared Coordinates"] = ("na", "Shared Coordinates: couldn't compare ({0})".format(ex))

    # Base point
    if ld is None:
        chips["Base Point"] = ("na", "Base Point: needs the link loaded")
    else:
        try:
            hp = BasePoint.GetProjectBasePoint(doc).Position
            lp = t.OfPoint(BasePoint.GetProjectBasePoint(ld).Position)
            d = lp.Subtract(hp)
            if d.GetLength() <= TOL and abs(rotation) <= ANG_TOL:
                chips["Base Point"] = ("ok", u"Base Point: \u2713")
                now.append("Base Point")
            else:
                chips["Base Point"] = (off_kind, "Base Point: off by X {0}, Y {1}, Z {2}".format(
                    fmt_signed_mm(d.X), fmt_signed_mm(d.Y), fmt_signed_mm(d.Z)))
        except Exception as ex:
            chips["Base Point"] = ("na", "Base Point: couldn't compare ({0})".format(ex))

    # Internal origin
    o = t.Origin
    if o.GetLength() <= TOL and abs(rotation) <= ANG_TOL:
        chips["Internal Origin"] = ("ok", u"Internal Origin: \u2713")
        now.append("Internal Origin")
    else:
        chips["Internal Origin"] = (off_kind, "Internal Origin: off by X {0}, Y {1}, Z {2}".format(
            fmt_signed_mm(o.X), fmt_signed_mm(o.Y), fmt_signed_mm(o.Z)))

    rot_chip = ("ok" if abs(rotation) <= ANG_TOL else off_kind, "Rotation: " + fmt_deg(rotation))

    out = [chips["Shared Coordinates"], chips["Base Point"], chips["Internal Origin"], rot_chip]
    out.append(grids or ("na", "Grids: needs the link loaded"))
    out.append(levels or ("na", "Levels: needs the link loaded"))
    return out, now


def move_link(inst, target):
    """Rotate about Z and move so the instance transform equals target, then pin it.
    Call inside a transaction."""
    inst.Pinned = False
    turn = angle_diff(angle_of(target), angle_of(inst.GetTotalTransform()))
    if abs(turn) > 1e-9:
        ElementTransformUtils.RotateElement(doc, inst.Id, Line.CreateBound(XYZ.Zero, XYZ.BasisZ), turn)
    shift = target.Origin.Subtract(inst.GetTotalTransform().Origin)
    if shift.GetLength() > 1e-9:
        ElementTransformUtils.MoveElement(doc, inst.Id, shift)
    inst.Pinned = True


# ---------------------------------------------------------------------------
# Inspector scans (run against each loaded link document)
# ---------------------------------------------------------------------------
def doc_title(rvt_doc, fallback):
    try:
        title = rvt_doc.Title
    except Exception:
        title = None
    return title or fallback


def file_ext(name):
    if "." not in name:
        return ""
    return name.rsplit(".", 1)[-1].strip().lower()


class Entry(object):
    """One finding: a display line, a sort key and the cells for the tables."""

    def __init__(self, text, sort_key=None, fields=None):
        self.Display = text
        self.SortKey = sort_key if sort_key is not None else text
        self.Fields = fields


def scan_cad(target_doc):
    """(dwg_links, dwg_imports, other_cad, [Entry])"""
    entries = []
    dwg_links = 0
    dwg_imports = 0
    other_cad = 0
    used_type_ids = set()

    for inst in FilteredElementCollector(target_doc).OfClass(ImportInstance):
        type_id = inst.GetTypeId()
        used_type_ids.add(id_value(type_id))
        name = element_name(target_doc.GetElement(type_id))
        try:
            is_link = bool(inst.IsLinked)
        except Exception:
            is_link = False

        owner_id = inst.OwnerViewId
        if owner_id is not None and owner_id != ElementId.InvalidElementId:
            view = target_doc.GetElement(owner_id)
            scope = u"View: {0}".format(element_name(view)) if view is not None else "View specific"
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
                             (kind, name.lower()), (name, kind, scope)))

    # CAD types with no placed instance: leftovers still listed in Manage Links
    for cad_type in FilteredElementCollector(target_doc).OfClass(CADLinkType):
        if id_value(cad_type.Id) in used_type_ids:
            continue
        name = element_name(cad_type)
        entries.append(Entry(u"{0}   [Type only, no instance]".format(name),
                             ("zz", name.lower()), (name, "Type only, no instance", DASH)))

    entries.sort(key=lambda e: e.SortKey)
    return dwg_links, dwg_imports, other_cad, entries


def scan_warnings(target_doc):
    """(total, [Entry]) grouped by warning text, most frequent first."""
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
        entries.append(Entry(u"{0} x   {1}".format(count, text), (-count, text.lower()),
                             (u"{0}".format(count), text)))
    entries.sort(key=lambda e: e.SortKey)
    return total, entries


def workset_name(target_doc, element):
    try:
        workset = target_doc.GetWorksetTable().GetWorkset(element.WorksetId)
        return workset.Name if workset is not None else None
    except Exception:
        return None


def scan_levels_grids(target_doc):
    """(bad_levels, bad_grids, workshared, [Entry]). Counts are None when not workshared."""
    if not target_doc.IsWorkshared:
        return None, None, False, [Entry("This link is not workshared, so the workset check doesn't apply.")]

    entries = []
    counts = {"Level": 0, "Grid": 0}
    for label, bic in (("Level", BuiltInCategory.OST_Levels), ("Grid", BuiltInCategory.OST_Grids)):
        collector = FilteredElementCollector(target_doc).OfCategory(bic).WhereElementIsNotElementType()
        for element in collector:
            name = element_name(element)
            ws_name = workset_name(target_doc, element)
            if ws_name is None:
                entries.append(Entry(u"{0}: {1}   [workset unreadable]".format(label, name),
                                     (label, "zz", name.lower()), (label, name, "unreadable")))
                continue
            if ws_name.strip().lower() in VALID_LG_WORKSETS:
                continue
            counts[label] += 1
            entries.append(Entry(u"{0}: {1}   [on '{2}']".format(label, name, ws_name),
                                 (label, ws_name.lower(), name.lower()), (label, name, ws_name)))

    entries.sort(key=lambda e: e.SortKey)
    if not entries:
        entries = [Entry("All levels and grids are on an accepted workset.")]
    return counts["Level"], counts["Grid"], True, entries


def scan_default_workset(target_doc):
    """(total, [Entry]) of categorised elements on Workset1. total is None when not workshared."""
    if not target_doc.IsWorkshared:
        return None, [Entry("This link is not workshared, so it has no user worksets.")]
    try:
        worksets = [ws for ws in FilteredWorksetCollector(target_doc).OfKind(WorksetKind.UserWorkset)
                    if (ws.Name or "").strip().lower() in DEFAULT_WORKSET_NAMES]
    except Exception as err:
        return None, [Entry(u"Worksets couldn't be read: {0}".format(err))]
    if not worksets:
        return 0, [Entry("There is no workset named Workset1 in this link.")]

    counts = {}
    total = 0
    for workset in worksets:
        collector = (FilteredElementCollector(target_doc)
                     .WherePasses(ElementWorksetFilter(workset.Id))
                     .WhereElementIsNotElementType())
        for element in collector:
            category = element.Category
            if category is None:
                continue
            counts[category.Name] = counts.get(category.Name, 0) + 1
            total += 1
    if not total:
        return 0, [Entry("Workset1 exists but holds no categorised elements.")]

    entries = []
    for cat_name in counts:
        count = counts[cat_name]
        entries.append(Entry(u"{0}   -   {1} item(s)".format(cat_name, count), (-count, cat_name.lower()),
                             (cat_name, u"{0}".format(count))))
    entries.sort(key=lambda e: e.SortKey)
    return total, entries


class CategoryStat(object):
    def __init__(self, name):
        self.Name = name
        self.FamilyCount = 0
        self.TypeCount = 0
        self.UnusedFamilies = []  # [(family name, type count)]
        self.UnusedTypes = []  # ["family : type"] under families that are used

    def summary_line(self):
        return u"{0} families, {1} unused  |  {2} types, {3} unused under the {4} used families".format(
            self.FamilyCount, len(self.UnusedFamilies), self.TypeCount, len(self.UnusedTypes),
            self.FamilyCount - len(self.UnusedFamilies))

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
    try:
        name = element_type.FamilyName
    except Exception:
        name = None
    return name or "<no family>"


def scan_unused(target_doc):
    """Families with no placed type, and unplaced types under families that are used."""
    used_type_ids = set()
    for element in FilteredElementCollector(target_doc).WhereElementIsNotElementType():
        type_id = element.GetTypeId()
        if type_id is not None and type_id != ElementId.InvalidElementId:
            used_type_ids.add(id_value(type_id))

    tree = {}  # category -> family -> [(type name, used)]
    for element_type in FilteredElementCollector(target_doc).WhereElementIsElementType():
        category = element_type.Category
        if category is None:
            continue
        if category.CategoryType not in (CategoryType.Model, CategoryType.Annotation):
            continue
        families = tree.setdefault(category.Name, {})
        families.setdefault(type_family_name(element_type), []).append(
            (element_name(element_type), id_value(element_type.Id) in used_type_ids))

    result = UnusedResult()
    for cat_name in sorted(tree.keys(), key=lambda n: n.lower()):
        families = tree[cat_name]
        stat = CategoryStat(cat_name)
        stat.FamilyCount = len(families)
        for fam_name in sorted(families.keys(), key=lambda n: n.lower()):
            types = families[fam_name]
            stat.TypeCount += len(types)
            if not [t for t in types if t[1]]:
                stat.UnusedFamilies.append((fam_name, len(types)))
                continue
            for type_name, is_used in sorted(types, key=lambda t: t[0].lower()):
                if not is_used:
                    stat.UnusedTypes.append(u"{0} : {1}".format(fam_name, type_name))
        result.Categories.append(stat)
        result.TotalFamilies += stat.FamilyCount
        result.TotalTypes += stat.TypeCount
        result.TotalUnusedFamilies += len(stat.UnusedFamilies)
        result.TotalUnusedTypes += len(stat.UnusedTypes)
    return result


def link_path(link_type):
    try:
        reference = link_type.GetExternalFileReference()
        return ModelPathUtils.ModelPathToUserVisiblePath(reference.GetAbsolutePath()) or DASH
    except Exception:
        return DASH


def scan_rvt_links(target_doc):
    """(count, [Entry]) for the Revit links inside a link."""
    instance_counts = {}
    for inst in FilteredElementCollector(target_doc).OfClass(RevitLinkInstance):
        key = id_value(inst.GetTypeId())
        instance_counts[key] = instance_counts.get(key, 0) + 1

    entries = []
    for link_type in FilteredElementCollector(target_doc).OfClass(RevitLinkType):
        name = element_name(link_type)
        try:
            status = str(link_type.GetLinkedFileStatus())
        except Exception:
            status = "Unknown"
        try:
            attachment = str(link_type.AttachmentType)
        except Exception:
            attachment = DASH
        try:
            if link_type.IsNestedLink:
                attachment = u"{0}, nested".format(attachment)
        except Exception:
            pass
        count = instance_counts.get(id_value(link_type.Id), 0)
        entries.append(Entry(u"{0}   [{1}]   {2}   x{3}".format(name, status, attachment, count), name.lower(),
                             (name, status, attachment, u"{0}".format(count), link_path(link_type))))
    entries.sort(key=lambda e: e.SortKey)
    return len(entries), entries


class Inspection(object):
    """Everything the inspector shows for one loaded link file. Unused items are scanned on demand."""

    def __init__(self, link_doc, name):
        self.doc = link_doc
        self.name = name
        self.errors = {}
        self.views = []  # RowUi cards showing this link file
        self.unused = None
        (self.dwg_links, self.dwg_imports, self.other_cad,
         self.cad_entries) = self._safe("DWG / CAD", scan_cad, (0, 0, 0, []))
        self.warnings, self.warning_entries = self._safe("Warnings", scan_warnings, (0, []))
        (self.bad_levels, self.bad_grids, self.workshared,
         self.lg_entries) = self._safe("Levels + Grids", scan_levels_grids, (None, None, False, []))
        self.workset1, self.ws1_entries = self._safe("Workset1", scan_default_workset, (None, []))
        self.rvt_links, self.rvt_entries = self._safe("RVT Links", scan_rvt_links, (0, []))

    def _safe(self, label, fn, default):
        try:
            return fn(self.doc)
        except Exception as ex:
            self.errors[label] = u"{0}".format(ex)
            return default

    def run_unused(self):
        if self.unused is not None:
            return
        try:
            self.unused = scan_unused(self.doc)
            self.errors.pop("Unused Items", None)
        except Exception as ex:
            self.errors["Unused Items"] = u"{0}".format(ex)

    # short texts shared by the health line and the report
    def col_lg(self):
        return "{0} / {1}".format(self.bad_levels, self.bad_grids) if self.workshared else "n/a"

    def col_ws1(self):
        return "n/a" if self.workset1 is None else str(self.workset1)

    def col_unused(self):
        if self.unused is None:
            return "not scanned"
        return "{0} / {1}".format(self.unused.TotalUnusedFamilies, self.unused.TotalUnusedTypes)


SCAN_LISTENERS = []  # called with the scanned inspections (the inspector pane)


def run_unused_scans(inspections):
    """Scan unused items with a wait cursor, then refresh the cards and the inspector."""
    pending = [i for i in inspections if i.unused is None]
    if not pending:
        return
    Mouse.OverrideCursor = Cursors.Wait
    try:
        for insp in pending:
            insp.run_unused()
    finally:
        Mouse.OverrideCursor = None
    for insp in pending:
        for view in insp.views:
            view.fill_health()
    for listener in SCAN_LISTENERS:
        listener(pending)


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------
def collect_worksets():
    if not doc.IsWorkshared:
        return []
    worksets = list(FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset))
    worksets.sort(key=lambda w: w.Name.lower())
    return worksets


def instances_by_type():
    mapping = {}
    for inst in FilteredElementCollector(doc).OfClass(RevitLinkInstance).ToElements():
        try:
            key = id_value(inst.GetTypeId())
        except Exception:
            continue
        mapping.setdefault(key, []).append(inst)
    return mapping


def collect_rows(workset_names):
    rows = []
    rvt_instances = instances_by_type()
    for link_type in FilteredElementCollector(doc).OfClass(RevitLinkType).ToElements():
        try:
            if link_type.IsNestedLink:
                continue
        except AttributeError:
            pass
        rows.append(build_row(link_type, rvt_instances.get(id_value(link_type.Id), []), workset_names))
    rows.sort(key=lambda r: r["name"].lower())
    return rows


def build_row(type_elem, instances, workset_names):
    current_id = id_value(type_elem.WorksetId)
    param = workset_param(type_elem)
    owner = other_user_owner(type_elem)

    locked_reason = ""
    if not doc.IsWorkshared:
        locked_reason = "not workshared"
    elif param is None:
        locked_reason = "no workset parameter"
    elif param.IsReadOnly:
        locked_reason = "workset is read-only"
    elif owner:
        locked_reason = "owned by " + owner

    room = None
    rb = room_bounding_param(type_elem)
    if rb is not None and not rb.IsReadOnly and not owner:
        room = bool(rb.AsInteger())

    inst_rows = []
    for inst in sorted(instances, key=lambda i: id_value(i.Id)):
        entry = {"inst": inst, "pinned": bool(inst.Pinned), "owner": other_user_owner(inst),
                 "chips": None, "now": [], "target": None, "pin_box": None, "seg": {}}
        try:
            entry["chips"], entry["now"] = check_position(inst)
        except Exception as ex:
            entry["chips"] = [("na", "Position: couldn't be checked ({0})".format(ex))]
        inst_rows.append(entry)

    return {
        "type_elem": type_elem,
        "name": element_name(type_elem),
        "status": link_status(type_elem),
        "instances": inst_rows,
        "current_id": current_id,
        "current_name": workset_names.get(current_id, "<not on a workset>"),
        "locked_reason": locked_reason,
        "room": room,
        "room_box": None,
        "combo": None,
        "border": None,
        "dot": None,
        "inspection": None,
    }


def attach_inspections(rows):
    """Scan each loaded link file once; links of the same file share one inspection."""
    by_key = {}
    order = []
    for row in rows:
        link_doc = None
        for entry in row["instances"]:
            try:
                link_doc = entry["inst"].GetLinkDocument()
            except Exception:
                link_doc = None
            if link_doc is not None:
                break
        if link_doc is None:
            continue
        key = (link_doc.PathName or row["name"]).strip().lower()
        if key not in by_key:
            by_key[key] = Inspection(link_doc, row["name"])
            order.append(by_key[key])
        row["inspection"] = by_key[key]
    return order


# ---------------------------------------------------------------------------
# XAML shell
# ---------------------------------------------------------------------------
XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Link Manager"
        Width="1600" Height="880" MinWidth="1200" MinHeight="600"
        WindowStartupLocation="CenterScreen"
        Background="#161616"
        FontFamily="Segoe UI">
  <Window.Resources>


    <Style x:Key="DarkComboItem" TargetType="ComboBoxItem">
      <Setter Property="Background" Value="Transparent"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Padding" Value="8,5"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ComboBoxItem">
            <Border x:Name="Bd" Background="{TemplateBinding Background}"
                    Padding="{TemplateBinding Padding}" CornerRadius="3">
              <ContentPresenter/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsHighlighted" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#525252"/>
                <Setter Property="Foreground" Value="#F1C21B"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="DarkCombo" TargetType="ComboBox">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="Height" Value="26"/>
      <Setter Property="ItemContainerStyle" Value="{StaticResource DarkComboItem}"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ComboBox">
            <Grid>
              <ToggleButton x:Name="Toggle" Focusable="False" ClickMode="Press"
                            IsChecked="{Binding IsDropDownOpen, Mode=TwoWay,
                                        RelativeSource={RelativeSource TemplatedParent}}">
                <ToggleButton.Template>
                  <ControlTemplate TargetType="ToggleButton">
                    <Border x:Name="Bd" Background="#393939" BorderBrush="#525252"
                            BorderThickness="1" CornerRadius="4">
                      <Path x:Name="Arrow" HorizontalAlignment="Right" VerticalAlignment="Center"
                            Margin="0,0,9,0" Data="M 0 0 L 4 4 L 8 0 Z" Fill="#A8A8A8"/>
                    </Border>
                    <ControlTemplate.Triggers>
                      <Trigger Property="IsMouseOver" Value="True">
                        <Setter TargetName="Bd" Property="BorderBrush" Value="#F1C21B"/>
                      </Trigger>
                      <Trigger Property="IsEnabled" Value="False">
                        <Setter TargetName="Bd" Property="Background" Value="#262626"/>
                        <Setter TargetName="Arrow" Property="Fill" Value="#525252"/>
                      </Trigger>
                    </ControlTemplate.Triggers>
                  </ControlTemplate>
                </ToggleButton.Template>
              </ToggleButton>
              <ContentPresenter x:Name="ContentSite" IsHitTestVisible="False"
                                Content="{TemplateBinding SelectionBoxItem}"
                                ContentTemplate="{TemplateBinding SelectionBoxItemTemplate}"
                                Margin="9,0,26,0" VerticalAlignment="Center"/>
              <Popup x:Name="Popup" Placement="Bottom" AllowsTransparency="True"
                     Focusable="False" PopupAnimation="Slide"
                     IsOpen="{TemplateBinding IsDropDownOpen}">
                <Border Background="#262626" BorderBrush="#525252" BorderThickness="1"
                        CornerRadius="4" Margin="0,2,0,0" MaxHeight="280"
                        MinWidth="{TemplateBinding ActualWidth}">
                  <ScrollViewer SnapsToDevicePixels="True">
                    <StackPanel IsItemsHost="True" Margin="3"/>
                  </ScrollViewer>
                </Border>
              </Popup>
            </Grid>
            <ControlTemplate.Triggers>
              <Trigger Property="IsEnabled" Value="False">
                <Setter Property="Foreground" Value="#525252"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="FlatBtn" TargetType="Button">
      <Setter Property="Background" Value="#F1C21B"/>
      <Setter Property="Foreground" Value="#161616"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="Height" Value="30"/>
      <Setter Property="Padding" Value="18,0"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="Bd" Background="{TemplateBinding Background}" CornerRadius="5"
                    Padding="{TemplateBinding Padding}">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="Bd" Property="Opacity" Value="0.85"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="GhostBtn" TargetType="Button" BasedOn="{StaticResource FlatBtn}">
      <Setter Property="Background" Value="#525252"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
    </Style>

    <Style x:Key="HeaderCell" TargetType="TextBlock">
      <Setter Property="Foreground" Value="#A8A8A8"/>
      <Setter Property="FontSize" Value="11"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
      <Setter Property="Margin" Value="0,0,8,0"/>
    </Style>


    <Style x:Key="Seg" TargetType="ToggleButton">
      <Setter Property="Foreground" Value="#C6C6C6"/>
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="BorderBrush" Value="Transparent"/>
      <Setter Property="FontSize" Value="11"/>
      <Setter Property="Height" Value="24"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ToggleButton">
            <Border x:Name="Bd" Background="{TemplateBinding Background}"
                    BorderBrush="{TemplateBinding BorderBrush}" BorderThickness="0,0,0,2" Padding="8,0">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsChecked" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#F1C21B"/>
                <Setter Property="Foreground" Value="#161616"/>
              </Trigger>
              <Trigger Property="IsEnabled" Value="False">
                <Setter TargetName="Bd" Property="Opacity" Value="0.35"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style TargetType="CheckBox">
      <Setter Property="Foreground" Value="#A8A8A8"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="VerticalAlignment" Value="Center"/>
      <Setter Property="Cursor" Value="Hand"/>
    </Style>

    <Style x:Key="Pill" TargetType="ToggleButton">
      <Setter Property="Foreground" Value="#C6C6C6"/>
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="FontSize" Value="11.5"/>
      <Setter Property="Height" Value="26"/>
      <Setter Property="Margin" Value="0,0,6,6"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ToggleButton">
            <Border x:Name="Bd" Background="{TemplateBinding Background}" CornerRadius="13" Padding="13,0">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#525252"/>
              </Trigger>
              <Trigger Property="IsChecked" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#F1C21B"/>
                <Setter Property="Foreground" Value="#161616"/>
                <Setter Property="FontWeight" Value="SemiBold"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="InspList" TargetType="ListView">
      <Setter Property="Background" Value="#1B1B1B"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="BorderThickness" Value="0"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="ScrollViewer.HorizontalScrollBarVisibility" Value="Auto"/>
      <Setter Property="ScrollViewer.VerticalScrollBarVisibility" Value="Auto"/>
      <Setter Property="VirtualizingPanel.IsVirtualizingWhenGrouping" Value="True"/>
    </Style>

    <Style x:Key="InspHeader" TargetType="GridViewColumnHeader">
      <Setter Property="Foreground" Value="#A8A8A8"/>
      <Setter Property="FontSize" Value="11"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
      <Setter Property="HorizontalContentAlignment" Value="Left"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="GridViewColumnHeader">
            <Grid>
              <Border x:Name="Bd" Background="#262626" BorderBrush="#393939" BorderThickness="0,0,1,1"
                      Padding="7,6,8,6">
                <ContentPresenter HorizontalAlignment="{TemplateBinding HorizontalContentAlignment}"
                                  VerticalAlignment="Center"/>
              </Border>
              <Thumb x:Name="PART_HeaderGripper" HorizontalAlignment="Right" Width="9" Margin="0,0,-5,0"
                     Cursor="SizeWE" ToolTip="Drag to resize, double-click to fit">
                <Thumb.Template>
                  <ControlTemplate TargetType="Thumb">
                    <Border Background="Transparent"/>
                  </ControlTemplate>
                </Thumb.Template>
              </Thumb>
            </Grid>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#393939"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="InspItem" TargetType="ListViewItem">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ListViewItem">
            <Border x:Name="Bd" Background="Transparent" BorderBrush="#2E2E2E" BorderThickness="0,0,0,1"
                    Padding="0,5,0,5">
              <GridViewRowPresenter VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#262626"/>
              </Trigger>
              <Trigger Property="IsSelected" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#393939"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="InspGroup" TargetType="GroupItem">
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="GroupItem">
            <Expander IsExpanded="False">
              <Expander.Template>
                <ControlTemplate TargetType="Expander">
                  <DockPanel>
                    <ToggleButton DockPanel.Dock="Top" Cursor="Hand"
                                  IsChecked="{Binding IsExpanded, Mode=TwoWay,
                                              RelativeSource={RelativeSource TemplatedParent}}">
                      <ToggleButton.Template>
                        <ControlTemplate TargetType="ToggleButton">
                          <Border Background="#262626" CornerRadius="4" Padding="8,5" Margin="0,2,0,2">
                            <StackPanel Orientation="Horizontal">
                              <TextBlock x:Name="Arrow" Text="&#x25B8;" Foreground="#F1C21B" Margin="0,0,8,0"/>
                              <TextBlock Text="{Binding Name}" Foreground="#F4F4F4" FontWeight="SemiBold"/>
                            </StackPanel>
                          </Border>
                          <ControlTemplate.Triggers>
                            <Trigger Property="IsChecked" Value="True">
                              <Setter TargetName="Arrow" Property="Text" Value="&#x25BE;"/>
                            </Trigger>
                          </ControlTemplate.Triggers>
                        </ControlTemplate>
                      </ToggleButton.Template>
                    </ToggleButton>
                    <ContentPresenter x:Name="Body" Visibility="Collapsed" Margin="14,0,0,4"/>
                  </DockPanel>
                  <ControlTemplate.Triggers>
                    <Trigger Property="IsExpanded" Value="True">
                      <Setter TargetName="Body" Property="Visibility" Value="Visible"/>
                    </Trigger>
                  </ControlTemplate.Triggers>
                </ControlTemplate>
              </Expander.Template>
              <ItemsPresenter/>
            </Expander>
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
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <DockPanel Grid.Row="0" Margin="0,0,0,12">
      <Button x:Name="ExportBtn" DockPanel.Dock="Right" Content="Export HTML report"
              Style="{StaticResource GhostBtn}" VerticalAlignment="Center"/>
      <StackPanel>
        <TextBlock Text="LINK MANAGER" Foreground="#F1C21B" FontSize="16" FontWeight="Bold"/>
        <TextBlock x:Name="SubTitle" Foreground="#A8A8A8" FontSize="12" Margin="0,3,0,0"/>
      </StackPanel>
    </DockPanel>

    <Border Grid.Row="1" Background="#262626" CornerRadius="6" Padding="10" Margin="0,0,0,10">
      <DockPanel>
        <Button x:Name="PinAllBtn" DockPanel.Dock="Right" Content="Pin all" Style="{StaticResource GhostBtn}"
                Height="26" Padding="14,0" Margin="8,0,0,0"/>
        <Button x:Name="RoomOnBtn" DockPanel.Dock="Right" Content="Room bounding on" Style="{StaticResource GhostBtn}"
                Height="26" Padding="14,0" Margin="8,0,0,0"/>
        <Button x:Name="BulkBtn" DockPanel.Dock="Right" Content="Apply" Style="{StaticResource GhostBtn}"
                Height="26" Padding="14,0" Margin="8,0,0,0"/>
        <ComboBox x:Name="BulkCombo" DockPanel.Dock="Right" Style="{StaticResource DarkCombo}" Width="190"/>
        <TextBlock DockPanel.Dock="Right" Text="Set all visible to" Foreground="#A8A8A8" FontSize="12"
                   VerticalAlignment="Center" Margin="16,0,8,0"/>
        <Grid>
          <Border Background="#393939" BorderBrush="#525252" BorderThickness="1" CornerRadius="4" Height="26">
            <TextBox x:Name="SearchBox" Background="Transparent" BorderThickness="0"
                     Foreground="#F4F4F4" CaretBrush="#F1C21B" FontSize="12"
                     VerticalContentAlignment="Center" Padding="8,0"/>
          </Border>
          <TextBlock x:Name="SearchHint" Text="Search links..." Foreground="#6F6F6F" FontSize="12"
                     Margin="10,0,0,0" VerticalAlignment="Center" IsHitTestVisible="False"/>
        </Grid>
      </DockPanel>
    </Border>

    <Grid Grid.Row="2">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="*" MinWidth="760"/>
        <ColumnDefinition Width="10"/>
        <ColumnDefinition Width="480" MinWidth="340"/>
      </Grid.ColumnDefinitions>

      <DockPanel Grid.Column="0">
        <DockPanel x:Name="HeaderRow" DockPanel.Dock="Top" Margin="12,0,30,6"/>
        <ScrollViewer x:Name="RowsScroll" VerticalScrollBarVisibility="Auto"
                      HorizontalScrollBarVisibility="Disabled">
          <StackPanel x:Name="RowsPanel"/>
        </ScrollViewer>
      </DockPanel>

      <GridSplitter Grid.Column="1" Width="10" HorizontalAlignment="Stretch" Background="Transparent"
                    ResizeBehavior="PreviousAndNext" Cursor="SizeWE" ToolTip="Drag to resize the inspector"/>

      <Border Grid.Column="2" Background="#1B1B1B" BorderBrush="#393939" BorderThickness="1"
              CornerRadius="6" Padding="14,12,14,12">
        <DockPanel>
          <StackPanel DockPanel.Dock="Top">
            <TextBlock Text="INSPECTOR" Foreground="#A8A8A8" FontSize="11" FontWeight="SemiBold"/>
            <TextBlock x:Name="InspName" Text="No link selected" Foreground="#F4F4F4" FontSize="14"
                       FontWeight="SemiBold" TextTrimming="CharacterEllipsis" Margin="0,4,0,0"/>
            <TextBlock x:Name="InspSub" Text="Click a link on the left to inspect it."
                       Foreground="#A8A8A8" FontSize="11" TextWrapping="Wrap" Margin="0,2,0,10"/>
            <WrapPanel x:Name="InspTabs" Visibility="Collapsed"/>
            <Border x:Name="InspFilterHost" Visibility="Collapsed" Margin="0,2,0,10"/>
          </StackPanel>
          <Border x:Name="InspHost"/>
        </DockPanel>
      </Border>
    </Grid>

    <TextBlock Grid.Row="3" Foreground="#8D8D8D" FontSize="11" Margin="2,8,0,0" TextWrapping="Wrap"
               Text="Click a link to show it in the inspector on the right. Green underline = where the link sits now. Yellow = where it moves on Apply (it is pinned again after the move). Status colours: green matches, amber off but grids and levels still line up, red grids or levels don't line up, grey can't check. Amber values in the health line need a look."/>

    <Grid Grid.Row="4" Margin="0,12,0,0">
      <StackPanel Orientation="Horizontal" HorizontalAlignment="Left">
        <CheckBox x:Name="InstancesCheck" IsChecked="True"
                  Content="Also assign the link instances to the workset"/>
        <TextBlock x:Name="CountText" Foreground="#A8A8A8" FontSize="12"
                   VerticalAlignment="Center" Margin="20,0,0,0"/>
      </StackPanel>
      <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
        <Button x:Name="CancelBtn" Content="Close" Style="{StaticResource GhostBtn}"/>
        <Button x:Name="OkBtn" Content="Apply changes" Style="{StaticResource FlatBtn}"
                Margin="10,0,0,0"/>
      </StackPanel>
    </Grid>

  </Grid>
</Window>
"""


# ---------------------------------------------------------------------------
# Small UI builders
# ---------------------------------------------------------------------------
def text_block(text, size=12, color=C_TEXT, bold=False):
    block = TextBlock()
    block.Text = text
    block.FontSize = size
    block.Foreground = brush(color)
    block.VerticalAlignment = VerticalAlignment.Center
    block.TextTrimming = TextTrimming.CharacterEllipsis
    if bold:
        block.FontWeight = FontWeights.SemiBold
    return block


def note(text, color=C_SUBTEXT, margin=None):
    block = TextBlock()
    block.Text = text
    block.FontSize = 11.5
    block.Foreground = brush(color)
    block.TextWrapping = TextWrapping.Wrap
    block.Margin = margin or Thickness(0, 0, 0, 8)
    return block


def fixed(child, width, center=True):
    """A fixed-width cell for the right side of a row."""
    holder = Border()
    holder.Width = width
    holder.Margin = Thickness(8, 0, 0, 0)
    holder.VerticalAlignment = VerticalAlignment.Center
    if child is not None:
        if center:
            try:
                child.HorizontalAlignment = HorizontalAlignment.Center
            except Exception:
                pass
        holder.Child = child
    return holder


def make_header(window):
    header = window.FindName("HeaderRow")
    style = window.Resources["HeaderCell"]
    for text, width in (("POSITION: MOVE TO", W_POS), ("PINNED", W_PIN), ("ROOM BOUNDING", W_ROOM),
                        ("WORKSET", W_WORKSET)):
        block = TextBlock()
        block.Text = text
        block.Style = style
        cell = fixed(block, width, center=(width in (W_PIN, W_ROOM)))
        DockPanel.SetDock(cell, Dock.Right)
        header.Children.Add(cell)
    name = TextBlock()
    name.Text = "LINK"
    name.Style = style
    header.Children.Add(name)


def chip(kind, text):
    bg, fg = CHIP[kind]
    b = Border()
    b.Background = brush(bg)
    b.CornerRadius = CornerRadius(6)
    b.Padding = Thickness(8, 1, 8, 2)
    b.Margin = Thickness(0, 0, 6, 4)
    t = TextBlock()
    t.Text = text
    t.FontSize = 11
    t.Foreground = brush(fg)
    b.Child = t
    return b


def chips_panel(entry):
    wrap = WrapPanel()
    wrap.Margin = Thickness(0, 8, 0, 0)
    for kind, text in entry["chips"] or []:
        wrap.Children.Add(chip(kind, text))
    return wrap


CELL_XAML = u"""<DataTemplate xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation">
  <TextBlock Text="{{Binding [{0}]}}" ToolTip="{{Binding [{0}]}}" TextTrimming="CharacterEllipsis"
             Foreground="#F4F4F4"/>
</DataTemplate>"""
_CELL_CACHE = {}


def cell_template(index):
    """One line per cell, trimmed with an ellipsis; the tooltip shows the full text."""
    if index not in _CELL_CACHE:
        _CELL_CACHE[index] = XamlReader.Parse(CELL_XAML.format(index))
    return _CELL_CACHE[index]


class InspTable(object):
    """A list with resizable columns. Columns fit their content when shown; the widest one is
    narrowed so the table fits the inspector. Drag a header edge to resize, double-click it to fit.

    columns: [(header, index into each row)]. group_index: row index to group by (collapsible)."""

    def __init__(self, window, columns, rows, group_index=None):
        self.rows = [[u"{0}".format(c) for c in r] for r in rows]
        self.texts = [u" ".join(r).lower() for r in self.rows]
        self.group_index = group_index
        self.needle = None
        self.fitted = [False]

        view = ListView()
        view.Style = window.Resources["InspList"]
        view.ItemContainerStyle = window.Resources["InspItem"]
        grid = GridView()
        grid.ColumnHeaderContainerStyle = window.Resources["InspHeader"]
        for header, index in columns:
            column = GridViewColumn()
            column.Header = header
            column.CellTemplate = cell_template(index)
            grid.Columns.Add(column)
        view.View = grid
        if group_index is not None:
            style = GroupStyle()
            style.ContainerStyle = window.Resources["InspGroup"]
            view.GroupStyle.Add(style)
        view.Loaded += RoutedEventHandler(self._on_loaded)
        self.view = view
        self.grid = grid
        self.filter("")

    def filter(self, needle):
        needle = needle or ""
        if needle == self.needle:
            return
        self.needle = needle
        data = List[Object]()
        for row, text in zip(self.rows, self.texts):
            if not needle or needle in text:
                data.Add(Array[String](row))
        if self.group_index is None:
            self.view.ItemsSource = data
        else:
            source = ListCollectionView(data)
            source.GroupDescriptions.Add(PropertyGroupDescription("[{0}]".format(self.group_index)))
            self.view.ItemsSource = source

    def _on_loaded(self, sender, args):
        if self.fitted[0]:
            return
        self.fitted[0] = True
        self.view.Dispatcher.BeginInvoke(DispatcherPriority.Background, Action(self._fit))

    def _fit(self):
        columns = list(self.grid.Columns)
        if not columns:
            return
        room = self.view.ActualWidth - 30  # leave space for the vertical scrollbar
        widths = [c.ActualWidth for c in columns]
        if room <= 0 or sum(widths) <= room:
            return
        widest = widths.index(max(widths))
        others = sum(widths) - widths[widest]
        columns[widest].Width = max(140.0, room - others)


def filter_widget(on_change):
    holder = WpfGrid()
    holder.Height = 26
    frame = Border()
    frame.Background = brush("#393939")
    frame.BorderBrush = brush("#525252")
    frame.BorderThickness = Thickness(1)
    frame.CornerRadius = CornerRadius(4)
    box = TextBox()
    box.Background = brush("Transparent")
    box.BorderThickness = Thickness(0)
    box.Foreground = brush(C_TEXT)
    box.CaretBrush = brush(C_ACCENT)
    box.FontSize = 11.5
    box.VerticalContentAlignment = VerticalAlignment.Center
    box.Padding = Thickness(6, 0, 6, 0)
    frame.Child = box
    hint = TextBlock()
    hint.Text = "Filter this tab..."
    hint.Foreground = brush("#6F6F6F")
    hint.FontSize = 11.5
    hint.Margin = Thickness(9, 0, 0, 0)
    hint.VerticalAlignment = VerticalAlignment.Center
    hint.IsHitTestVisible = False
    holder.Children.Add(frame)
    holder.Children.Add(hint)

    def changed(sender, args):
        text = box.Text or ""
        hint.Visibility = Visibility.Collapsed if text else Visibility.Visible
        on_change(text)

    box.TextChanged += TextChangedEventHandler(changed)
    return holder, box


def health_segment(label, value, tone="plain"):
    block = TextBlock()
    block.FontSize = 11
    block.Margin = Thickness(0, 0, 16, 2)
    first = Run(label + ": ")
    first.Foreground = brush(C_MUTED)
    second = Run(value)
    second.Foreground = brush({"warn": C_WARN, "bad": C_BAD, "muted": C_MUTED}.get(tone, C_SUBTEXT))
    block.Inlines.Add(first)
    block.Inlines.Add(second)
    return block


# ---------------------------------------------------------------------------
# Inspector pane (right side): shows the link that was clicked last
# ---------------------------------------------------------------------------
class InspectorPane(object):

    def __init__(self, window):
        self.window = window
        self.name_text = window.FindName("InspName")
        self.sub_text = window.FindName("InspSub")
        self.tabs_panel = window.FindName("InspTabs")
        self.filter_host = window.FindName("InspFilterHost")
        self.host = window.FindName("InspHost")
        self.row = None
        self.insp = None
        self.active = TABS[0]
        self.cache = {}  # (id(inspection), tab) -> (content, [filter functions])
        self.filters = []
        self.needle = ""
        self.buttons = {}
        for name in TABS:
            button = ToggleButton()
            button.Style = window.Resources["Pill"]
            button.Content = name
            button.Click += RoutedEventHandler(self._tab_handler(name))
            self.tabs_panel.Children.Add(button)
            self.buttons[name] = button
        holder, self.filter_box = filter_widget(self._on_filter)
        self.filter_host.Child = holder

    # --- which link ---------------------------------------------------------
    def show_row(self, row):
        self.row = row
        self.insp = row["inspection"]
        self.name_text.Text = row["name"]
        count = len(row["instances"])
        placed = "not placed" if count == 0 else plural(count, "instance")
        if self.insp is None:
            self.sub_text.Text = u"{0}{1}{2}\nThe link isn't loaded, so there's nothing to inspect. " \
                                 u"Load it and open Link Manager again.".format(row["status"], DOT, placed)
            self.tabs_panel.Visibility = Visibility.Collapsed
            self.filter_host.Visibility = Visibility.Collapsed
            self.host.Child = None
            self.filters = []
            return
        self.sub_text.Text = u"{0}{1}{2}\n{3}".format(row["status"], DOT, placed, link_path(row["type_elem"]))
        self.tabs_panel.Visibility = Visibility.Visible
        self.filter_host.Visibility = Visibility.Visible
        self.filter_box.Text = ""
        self.show_tab(self.active)

    def on_scanned(self, inspections):
        for insp in inspections:
            self.cache.pop((id(insp), "Unused Items"), None)
        if self.insp is not None and self.active == "Unused Items" and self.insp in inspections:
            self.show_tab("Unused Items")

    # --- tabs -------------------------------------------------------------
    def _tab_handler(self, name):
        def handler(sender, args):
            self.show_tab(name)

        return handler

    def show_tab(self, name):
        self.active = name
        for other, button in self.buttons.items():
            button.IsChecked = (other == name)
        if self.insp is None:
            return
        key = (id(self.insp), name)
        if key not in self.cache:
            self.cache[key] = self._build_tab(name)
        content, filters = self.cache[key]
        self.host.Child = content
        self.filters = filters
        self._apply_filter()

    def _on_filter(self, text):
        self.needle = (text or "").strip().lower()
        self._apply_filter()

    def _apply_filter(self):
        for apply_filter in self.filters:
            apply_filter(self.needle)

    def _layout(self, top, table=None, bottom=()):
        """Notes on top, the table filling the rest of the pane, notes underneath."""
        dock = DockPanel()
        head = StackPanel()
        for element in top:
            head.Children.Add(element)
        DockPanel.SetDock(head, Dock.Top)
        dock.Children.Add(head)
        if bottom:
            foot = StackPanel()
            foot.Margin = Thickness(0, 8, 0, 0)
            for element in bottom:
                foot.Children.Add(element)
            DockPanel.SetDock(foot, Dock.Bottom)
            dock.Children.Add(foot)
        dock.Children.Add(table.view if table is not None else Border())
        return dock, ([table.filter] if table is not None else [])

    def _table_tab(self, top, columns, entries, empty_text):
        rows = [e.Fields for e in entries if e.Fields]
        if not rows:
            notes = [note(e.Display) for e in entries] or [note(empty_text)]
            return self._layout(top + notes)
        return self._layout(top, InspTable(self.window, columns, rows))

    def _build_tab(self, name):
        insp = self.insp
        top = []
        if name in insp.errors:
            top.append(note(u"Couldn't read this part of the link: {0}".format(insp.errors[name]), C_BAD))

        if name == "DWG / CAD":
            top.append(note(u"{0}, {1}, {2} other CAD".format(
                plural(insp.dwg_links, "DWG link"), plural(insp.dwg_imports, "DWG import"), insp.other_cad)))
            return self._table_tab(top, [("File", 0), ("Kind", 1), ("Scope", 2)], insp.cad_entries,
                                   "No CAD files in this link.")

        if name == "RVT Links":
            top.append(note(u"Revit links inside this link: {0}".format(insp.rvt_links)))
            return self._table_tab(top, [("Link", 0), ("Status", 1), ("Nesting", 2), ("Instances", 3),
                                         ("Path", 4)], insp.rvt_entries, "This link holds no other Revit links.")

        if name == "Warnings":
            top.append(note(u"{0} in {1}".format(
                plural(insp.warnings, "warning"), plural(len(insp.warning_entries), "kind"))))
            return self._table_tab(top, [("Count", 0), ("Warning", 1)], insp.warning_entries,
                                   "No warnings stored in this link.")

        if name == "Levels + Grids":
            if insp.workshared:
                top.append(note(u"{0} and {1} on a workset other than: {2}".format(
                    plural(insp.bad_levels, "level"), plural(insp.bad_grids, "grid"),
                    ", ".join(VALID_LG_WORKSETS))))
            return self._table_tab(top, [("Element", 0), ("Name", 1), ("Current workset", 2)], insp.lg_entries,
                                   "")

        if name == "Workset1":
            if insp.workset1:
                top.append(note(u"{0} on Workset1, by category".format(plural(insp.workset1, "item"))))
            return self._table_tab(top, [("Category", 0), ("Items", 1)], insp.ws1_entries, "")

        return self._unused_tab(top)

    def _unused_tab(self, top):
        insp = self.insp
        result = insp.unused
        if result is None:
            top.append(note("Not scanned yet. Scanning reads every family type in this link, "
                            "so it can take a while on big models."))
            button = Button()
            button.Content = "Scan unused"
            button.Style = self.window.Resources["GhostBtn"]
            button.Height = 26
            button.Padding = Thickness(14, 0, 14, 0)
            button.HorizontalAlignment = HorizontalAlignment.Left
            button.Click += RoutedEventHandler(self._scan_handler)
            top.append(button)
            return self._layout(top)

        top.append(note(u"{0} unused, and {1} unused under families that are used "
                        u"(out of {2} families and {3} types). Click a category to open it.".format(
            plural(result.TotalUnusedFamilies, "family", "families"),
            plural(result.TotalUnusedTypes, "type"),
            result.TotalFamilies, result.TotalTypes)))
        rows = []
        clean = 0
        for stat in result.Categories:
            if not stat.has_findings():
                clean += 1
                continue
            group = u"{0}{1}{2} unused famil{3}, {4} unused type{5}".format(
                stat.Name, DOT, len(stat.UnusedFamilies), "y" if len(stat.UnusedFamilies) == 1 else "ies",
                len(stat.UnusedTypes), "" if len(stat.UnusedTypes) == 1 else "s")
            for fam_name, count in stat.UnusedFamilies:
                rows.append((group, "Unused family", fam_name, count))
            for text in stat.UnusedTypes:
                rows.append((group, "Unused type", text, ""))
        bottom = [note(u"{0} had nothing unused.".format(
            plural(clean, "further category", "further categories")), margin=Thickness(0, 0, 0, 4)),
            note("Counted from placed instances: types used only by other types (curtain panels, "
                 "mullions, profiles, nested families) show here even though Revit can't purge "
                 "them. Treat it as triage, not a purge list.", C_MUTED, Thickness(0))]
        if not rows:
            return self._layout(top, None, bottom)
        table = InspTable(self.window, [("Unused", 1), ("Family / type", 2), ("Types", 3)], rows, group_index=0)
        return self._layout(top, table, bottom)

    def _scan_handler(self, sender, args):
        insp = self.insp
        run_unused_scans([insp])
        if insp.unused is None:  # the scan failed: show the error and the button again
            self.cache.pop((id(insp), "Unused Items"), None)
            if self.insp is insp:
                self.show_tab("Unused Items")


# ---------------------------------------------------------------------------
# Link card
# ---------------------------------------------------------------------------
class RowUi(object):
    """Builds one link's card and keeps track of what changed."""

    def __init__(self, window, row, workset_list, on_change, on_select):
        self.window = window
        self.row = row
        self.worksets = workset_list
        self.on_change = on_change
        self.on_select = on_select
        self.insp = row["inspection"]
        self.health = None
        if self.insp is not None:
            self.insp.views.append(self)

    def changed(self):
        row = self.row
        if row["combo"] is not None and row["combo"].IsEnabled and row["combo"].SelectedIndex >= 0:
            picked = self.worksets[row["combo"].SelectedIndex]
            if id_value(picked.Id) != row["current_id"]:
                return True
        if row["room_box"] is not None and bool(row["room_box"].IsChecked) != row["room"]:
            return True
        for entry in row["instances"]:
            if entry["target"]:
                return True
            if entry["pin_box"] is not None and bool(entry["pin_box"].IsChecked) != entry["pinned"]:
                return True
        return False

    def refresh(self):
        self.row["dot"].Visibility = Visibility.Visible if self.changed() else Visibility.Hidden

    def _changed_handler(self, sender, args):
        self.refresh()
        self.on_change()

    # --- selection ---------------------------------------------------------
    def set_selected(self, selected):
        self.row["border"].BorderBrush = brush(C_ACCENT if selected else "#262626")

    def _select_handler(self, sender, args):
        self.on_select(self)

    def _clickable(self, element):
        """Clicking this part of the card shows the link in the inspector."""
        try:
            if element.Background is None:
                element.Background = brush("Transparent")
        except Exception:
            pass
        element.Cursor = Cursors.Hand
        element.ToolTip = "Click to show this link in the inspector"
        element.MouseLeftButtonUp += MouseButtonEventHandler(self._select_handler)
        return element

    def fill_health(self):
        panel = self.health
        panel.Children.Clear()
        insp = self.insp
        if insp is None:
            panel.Children.Add(health_segment("Inspector", "needs the link loaded", "muted"))
            return
        cad = u"{0}, {1}".format(plural(insp.dwg_links, "link"), plural(insp.dwg_imports, "import"))
        if insp.other_cad:
            cad += u", {0} other".format(insp.other_cad)
        panel.Children.Add(health_segment("DWG / CAD", cad, "warn" if insp.dwg_imports else "plain"))
        panel.Children.Add(health_segment("RVT links", str(insp.rvt_links)))
        panel.Children.Add(health_segment("Warnings", str(insp.warnings), "warn" if insp.warnings else "plain"))
        bad_lg = insp.workshared and ((insp.bad_levels or 0) + (insp.bad_grids or 0)) > 0
        panel.Children.Add(health_segment("Levels + grids off workset", insp.col_lg(),
                                          "warn" if bad_lg else ("plain" if insp.workshared else "muted")))
        panel.Children.Add(health_segment("Workset1", insp.col_ws1(),
                                          "warn" if insp.workset1 else ("muted" if insp.workset1 is None else "plain")))
        if insp.unused is None:
            panel.Children.Add(health_segment("Unused", "not scanned", "muted"))
        else:
            some = insp.unused.TotalUnusedFamilies or insp.unused.TotalUnusedTypes
            panel.Children.Add(health_segment("Unused", u"{0} / {1}".format(
                plural(insp.unused.TotalUnusedFamilies, "family", "families"),
                plural(insp.unused.TotalUnusedTypes, "type")), "warn" if some else "plain"))
        if insp.errors:
            panel.Children.Add(health_segment("Couldn't read", ", ".join(sorted(insp.errors.keys())), "bad"))

    # --- controls ----------------------------------------------------------
    def _seg_handler(self, entry, name):
        def handler(sender, args):
            button = entry["seg"][name]
            if button.IsChecked:
                for other, b in entry["seg"].items():
                    if other != name:
                        b.IsChecked = False
                entry["target"] = name if name not in entry["now"] else None
                if entry["target"] is None:
                    button.IsChecked = False  # already there: nothing to move
            else:
                entry["target"] = None
            self.refresh()
            self.on_change()

        return handler

    def _position_cell(self, entry):
        outer = Border()
        outer.BorderBrush = brush("#525252")
        outer.BorderThickness = Thickness(1)
        outer.CornerRadius = CornerRadius(6)
        outer.HorizontalAlignment = HorizontalAlignment.Left
        panel = StackPanel()
        panel.Orientation = Orientation.Horizontal
        loaded = entry["inst"].GetLinkDocument() is not None
        for name in POSITIONS:
            b = ToggleButton()
            b.Style = self.window.Resources["Seg"]
            b.Content = SEG_LABEL[name]
            if name in entry["now"]:
                b.BorderBrush = brush("#A7F0BA")
                b.Foreground = brush(C_TEXT)
                b.ToolTip = "The link sits here now"
            else:
                b.ToolTip = "Move the link here on Apply"
            if entry["owner"]:
                b.IsEnabled = False
                b.ToolTip = "Owned by " + entry["owner"]
            elif not loaded and name != "Internal Origin":
                b.IsEnabled = False
                b.ToolTip = "Load the link to move it here"
            b.Click += RoutedEventHandler(self._seg_handler(entry, name))
            entry["seg"][name] = b
            panel.Children.Add(b)
        outer.Child = panel
        return fixed(outer, W_POS, center=False)

    def _pin_cell(self, entry):
        box = CheckBox()
        box.IsChecked = entry["pinned"]
        if entry["owner"]:
            box.IsEnabled = False
            box.ToolTip = "Owned by " + entry["owner"]
        box.Click += RoutedEventHandler(self._changed_handler)
        entry["pin_box"] = box
        return fixed(box, W_PIN)

    def _room_cell(self):
        row = self.row
        box = CheckBox()
        if row["room"] is None:
            box.IsEnabled = False
            box.ToolTip = "Room Bounding can't be changed on this link"
        else:
            box.IsChecked = row["room"]
            box.ToolTip = "Room Bounding (a link type setting: all its placed copies)"
        box.Click += RoutedEventHandler(self._changed_handler)
        row["room_box"] = box if row["room"] is not None else None
        return fixed(box, W_ROOM)

    def _workset_cell(self):
        row = self.row
        combo = ComboBox()
        combo.Style = self.window.Resources["DarkCombo"]
        combo.Width = W_WORKSET
        if not self.worksets:
            combo.Items.Add("Not workshared")
            combo.SelectedIndex = 0
            combo.IsEnabled = False
        else:
            ids = [id_value(w.Id) for w in self.worksets]
            for workset in self.worksets:
                combo.Items.Add(workset.Name)
            combo.SelectedIndex = ids.index(row["current_id"]) if row["current_id"] in ids else -1
            if row["locked_reason"]:
                combo.IsEnabled = False
                combo.ToolTip = "Cannot be reassigned: " + row["locked_reason"]
        combo.SelectionChanged += self._changed_handler
        row["combo"] = combo
        return fixed(combo, W_WORKSET, center=False)

    def _title_area(self):
        row = self.row
        count = len(row["instances"])
        info = StackPanel()
        info.VerticalAlignment = VerticalAlignment.Center

        title = StackPanel()
        title.Orientation = Orientation.Horizontal
        title.Children.Add(text_block(row["name"], 13, C_TEXT, bold=True))
        title.Children.Add(text_block(u"  {0}".format(row["status"]), 11,
                                      STATUS_COLOR.get(row["status"], C_SUBTEXT)))
        dot = Ellipse()
        dot.Width = 7
        dot.Height = 7
        dot.Fill = brush(C_ACCENT)
        dot.Margin = Thickness(8, 0, 0, 0)
        dot.VerticalAlignment = VerticalAlignment.Center
        dot.Visibility = Visibility.Hidden
        dot.ToolTip = "Changed: applied when you click Apply changes"
        row["dot"] = dot
        title.Children.Add(dot)
        info.Children.Add(title)

        if count == 0:
            sub = "Revit link" + DOT + "not placed"
        elif count == 1:
            sub = "Revit link" + DOT + "1 instance"
        else:
            sub = u"Revit link{0}instance 1 of {1}".format(DOT, count)
        if row["locked_reason"] and row["locked_reason"] != "not workshared":
            sub += DOT + "workset " + row["locked_reason"]
        info.Children.Add(text_block(sub, 11, C_SUBTEXT))

        area = Border()
        area.Child = info
        return self._clickable(area)

    def build(self):
        row = self.row
        border = Border()
        border.Background = brush("#262626")
        border.BorderBrush = brush("#262626")
        border.BorderThickness = Thickness(1)
        border.CornerRadius = CornerRadius(6)
        border.Padding = Thickness(12, 9, 12, 10)
        border.Margin = Thickness(0, 0, 0, 6)
        stack = StackPanel()

        instances = row["instances"]
        first = instances[0] if instances else None
        count = len(instances)

        top = DockPanel()
        if first is not None:
            pos = self._position_cell(first)
            pin = self._pin_cell(first)
        else:
            pos = fixed(text_block("Not placed", 11, C_MUTED), W_POS, center=False)
            pin = fixed(None, W_PIN)
        for cell in (pos, pin, self._room_cell(), self._workset_cell()):
            DockPanel.SetDock(cell, Dock.Right)
            top.Children.Add(cell)
        top.Children.Add(self._title_area())
        stack.Children.Add(top)
        if first is not None and first["chips"]:
            stack.Children.Add(self._clickable(chips_panel(first)))

        for n, entry in enumerate(instances[1:], 2):
            line = Border()
            line.BorderBrush = brush("#393939")
            line.BorderThickness = Thickness(0, 1, 0, 0)
            line.Margin = Thickness(0, 8, 0, 0)
            line.Padding = Thickness(0, 8, 0, 0)
            sub_stack = StackPanel()
            sub_row = DockPanel()
            for cell in (self._position_cell(entry), self._pin_cell(entry), fixed(None, W_ROOM),
                         fixed(None, W_WORKSET)):
                DockPanel.SetDock(cell, Dock.Right)
                sub_row.Children.Add(cell)
            sub_row.Children.Add(text_block(
                u"instance {0} of {1}{2}same workset and room bounding as instance 1".format(n, count, DOT),
                11, C_SUBTEXT))
            sub_stack.Children.Add(sub_row)
            if entry["chips"]:
                sub_stack.Children.Add(self._clickable(chips_panel(entry)))
            line.Child = sub_stack
            stack.Children.Add(line)

        health = WrapPanel()
        health.Margin = Thickness(0, 6, 0, 0)
        self.health = health
        self.fill_health()
        stack.Children.Add(self._clickable(health))

        border.Child = stack
        row["border"] = border
        return border


# ---------------------------------------------------------------------------
# HTML report
# ---------------------------------------------------------------------------
def esc(value):
    text = u"{0}".format(value)
    text = text.replace(u"&", u"&amp;").replace(u"<", u"&lt;")
    return text.replace(u">", u"&gt;").replace(u'"', u"&quot;")


def badge(value, css=None):
    """Coloured pill for a count cell."""
    text = u"{0}".format(value)
    if css is None:
        if text in (DASH, "n/a", "?", "not scanned", "not loaded"):
            css = "muted"
        elif text.replace(" ", "").replace("/", "").strip("0") == "":
            css = "zero"
        else:
            css = "some"
    return u'<span class="badge {0}">{1}</span>'.format(css, esc(text))


CHIP_CSS = {"ok": "zero", "warn": "some", "bad": "bad", "na": "muted"}


def table(headers, rows_data, empty_note="Nothing found."):
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
  --bg:#161616; --card:#262626; --surface:#393939; --muted:#525252;
  --text:#F4F4F4; --sub:#A8A8A8; --accent:#F1C21B;
}
*{box-sizing:border-box;}
body{margin:0;padding:28px 32px;background:var(--bg);color:var(--text);
     font-family:"Segoe UI",Tahoma,sans-serif;font-size:14px;}
h1{margin:0 0 4px;font-size:24px;letter-spacing:.5px;}
h1 span{color:var(--accent);}
h2{margin:0 0 14px;font-size:16px;color:var(--accent);}
.meta{color:var(--sub);font-size:12px;margin-bottom:20px;line-height:1.7;}
.cards{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:22px;}
.card{background:var(--card);border-radius:6px;padding:12px 18px;min-width:132px;}
.card .num{font-size:22px;font-weight:600;}
.card .lbl{font-size:11px;color:var(--sub);text-transform:uppercase;letter-spacing:.4px;margin-top:2px;}
.toolbar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:16px;}
input[type=text]{background:var(--surface);border:1px solid var(--muted);border-radius:4px;
  padding:7px 12px;color:var(--text);font-size:13px;min-width:280px;font-family:inherit;}
input[type=text]:focus{outline:none;border-color:var(--accent);}
button{background:var(--muted);border:none;border-radius:5px;padding:8px 14px;
  color:var(--text);font-size:12px;font-family:inherit;cursor:pointer;}
button:hover{background:var(--accent);color:var(--bg);}
table{border-collapse:collapse;width:100%;}
#overview{background:var(--card);border-radius:6px;overflow:hidden;margin-bottom:26px;}
#overview th{background:var(--surface);color:var(--sub);font-size:11px;text-transform:uppercase;
  letter-spacing:.4px;text-align:left;padding:11px 12px;cursor:pointer;user-select:none;white-space:nowrap;}
#overview th:hover{color:var(--accent);}
#overview td{padding:9px 12px;border-top:1px solid var(--surface);font-size:13px;}
#overview tbody tr:hover{background:var(--surface);}
#overview td.doc{cursor:pointer;}
#overview td.doc:hover{color:var(--accent);text-decoration:underline;}
.badge{display:inline-block;min-width:28px;text-align:center;padding:2px 8px;
  border-radius:6px;font-size:12px;font-weight:600;margin:0 4px 4px 0;}
.badge.zero{background:#0E2A18;color:#A7F0BA;}
.badge.some{background:#3A2E06;color:#FDDC69;}
.badge.bad{background:#4A0E12;color:#FFB3B8;}
.badge.muted{background:#2E2E2E;color:#8D8D8D;font-weight:400;}
details{background:var(--card);border-radius:6px;margin-bottom:10px;padding:2px 14px;}
details.doc{padding:6px 16px;}
details.sub{background:#1B1B1B;margin:8px 0;}
details.cat{background:var(--card);}
summary{cursor:pointer;padding:10px 2px;font-weight:600;list-style:none;}
summary::-webkit-details-marker{display:none;}
summary:before{content:"+";color:var(--accent);font-weight:700;display:inline-block;width:16px;}
details[open]>summary:before{content:"\\2013";}
details.doc>summary{font-size:15px;}
summary .pills{float:right;font-weight:400;}
.note{color:var(--sub);font-size:12px;margin:6px 0 12px;}
.chips{margin:4px 0 10px;}
table.inner{margin:4px 0 14px;background:var(--bg);border-radius:6px;overflow:hidden;}
table.inner th{background:var(--surface);color:var(--sub);font-size:11px;text-transform:uppercase;
  letter-spacing:.4px;text-align:left;padding:8px 12px;}
table.inner td{padding:7px 12px;border-top:1px solid var(--card);font-size:12.5px;vertical-align:top;}
table.inner tbody tr:hover{background:var(--card);}
.footer{color:var(--sub);font-size:11px;margin-top:28px;line-height:1.8;
        border-top:1px solid var(--surface);padding-top:14px;}
@media print{
  body{background:#fff;color:#000;padding:0;}
  .toolbar{display:none;}
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


def sort_number(text):
    try:
        return int(text)
    except (ValueError, TypeError):
        return -1


def position_summary(row):
    """(text, css) for where the first placed instance sits."""
    if not row["instances"]:
        return "not placed", "muted"
    now = row["instances"][0]["now"]
    if now:
        return ", ".join(now), "zero"
    if row["inspection"] is None:
        return "not loaded", "muted"
    return "none of the three", "some"


def report_rows(rows):
    """One entry per link file: links of the same file appear once."""
    seen = set()
    out = []
    for row in rows:
        insp = row["inspection"]
        if insp is not None:
            if id(insp) in seen:
                continue
            seen.add(id(insp))
        out.append(row)
    return out


def html_link_section(index, row):
    insp = row["inspection"]
    out = []
    if insp is not None:
        pills = u"".join([badge(u"{0} / {1}".format(insp.dwg_links, insp.dwg_imports)), badge(insp.rvt_links),
                          badge(insp.warnings), badge(insp.col_lg()), badge(insp.col_ws1()),
                          badge(insp.col_unused())])
    else:
        pills = badge("not loaded")
    out.append(u'<details class="doc" id="doc-{0}" data-name="{1}">'.format(index, esc(row["name"].lower())))
    out.append(u'<summary>{0} <span class="note">({1})</span><span class="pills">{2}</span></summary>'.format(
        esc(row["name"]), esc(row["status"]), pills))

    # position
    out.append(u'<details class="sub" open><summary>Position</summary>')
    if not row["instances"]:
        out.append(u'<p class="note">This link is not placed.</p>')
    for n, entry in enumerate(row["instances"], 1):
        if len(row["instances"]) > 1:
            out.append(u'<p class="note">Instance {0} of {1}</p>'.format(n, len(row["instances"])))
        out.append(u'<div class="chips">')
        for kind, text in entry["chips"] or []:
            out.append(badge(text, CHIP_CSS.get(kind, "muted")))
        out.append(u"</div>")
    out.append(u"</details>")

    if insp is None:
        out.append(u'<p class="note">The link is not loaded, so nothing inside it was inspected.</p></details>')
        return u"".join(out)

    for label, message in sorted(insp.errors.items()):
        out.append(u'<p class="note">Couldn\'t read {0}: {1}</p>'.format(esc(label), esc(message)))

    out.append(u'<details class="sub"><summary>DWG / CAD ({0} link(s), {1} import(s), {2} other CAD)'
               u'</summary>'.format(insp.dwg_links, insp.dwg_imports, insp.other_cad))
    out.append(table(["File", "Kind", "Scope"], [e.Fields for e in insp.cad_entries if e.Fields],
                     "No CAD files in this link."))
    out.append(u"</details>")

    out.append(u'<details class="sub"><summary>RVT Links inside this link ({0})</summary>'.format(insp.rvt_links))
    out.append(table(["Link", "Status", "Nesting", "Instances", "Path"],
                     [e.Fields for e in insp.rvt_entries if e.Fields], "This link holds no other Revit links."))
    out.append(u"</details>")

    out.append(u'<details class="sub"><summary>Warnings ({0})</summary>'.format(insp.warnings))
    out.append(table(["Count", "Warning"], [e.Fields for e in insp.warning_entries if e.Fields],
                     "No warnings stored in this link."))
    out.append(u"</details>")

    if insp.workshared:
        lg_label = u"Levels + Grids ({0} level(s), {1} grid(s) on a wrong workset)".format(
            insp.bad_levels, insp.bad_grids)
    else:
        lg_label = u"Levels + Grids (not workshared)"
    out.append(u'<details class="sub"><summary>{0}</summary>'.format(esc(lg_label)))
    lg_rows = [e.Fields for e in insp.lg_entries if e.Fields]
    if lg_rows:
        out.append(table(["Element", "Name", "Current workset"], lg_rows))
    else:
        for entry in insp.lg_entries:
            out.append(u'<p class="note">{0}</p>'.format(esc(entry.Display)))
    out.append(u"</details>")

    out.append(u'<details class="sub"><summary>Workset1 ({0})</summary>'.format(esc(insp.col_ws1())))
    ws1_rows = [e.Fields for e in insp.ws1_entries if e.Fields]
    if ws1_rows:
        out.append(table(["Category", "Items"], ws1_rows))
    else:
        for entry in insp.ws1_entries:
            out.append(u'<p class="note">{0}</p>'.format(esc(entry.Display)))
    out.append(u"</details>")

    result = insp.unused
    if result is None:
        out.append(u'<details class="sub"><summary>Unused Items (not scanned)</summary><p class="note">'
                   u'Export again and answer Yes to scan unused items.</p></details>')
        out.append(u"</details>")
        return u"".join(out)

    out.append(u'<details class="sub"><summary>Unused Items ({0} famil(ies), {1} type(s) under used families)'
               u'</summary>'.format(result.TotalUnusedFamilies, result.TotalUnusedTypes))
    clean = 0
    for stat in result.Categories:
        if not stat.has_findings():
            clean += 1
            continue
        out.append(u'<details class="cat"><summary>{0}</summary>'.format(esc(stat.Name)))
        out.append(u'<p class="note">{0}</p>'.format(esc(stat.summary_line())))
        if stat.UnusedFamilies:
            out.append(table(["Unused family", "Types"],
                             [(name, u"{0}".format(count)) for name, count in stat.UnusedFamilies]))
        if stat.UnusedTypes:
            out.append(table(["Unused type under a used family"], [(text,) for text in stat.UnusedTypes]))
        out.append(u"</details>")
    out.append(u'<p class="note">{0} further categor(ies) had nothing unused.</p>'.format(clean))
    out.append(u"</details>")
    out.append(u"</details>")
    return u"".join(out)


def build_report_html(rows):
    rows = report_rows(rows)
    inspections = [r["inspection"] for r in rows if r["inspection"] is not None]
    workshared = [i for i in inspections if i.workshared]
    unused_done = [i for i in inspections if i.unused is not None]

    cards = [("Revit links", len(rows)),
             ("Loaded", len(inspections)),
             ("Nested RVT links", sum([i.rvt_links for i in inspections])),
             ("DWG links", sum([i.dwg_links for i in inspections])),
             ("DWG imports", sum([i.dwg_imports for i in inspections])),
             ("Warnings", sum([i.warnings for i in inspections])),
             ("Levels off workset", sum([i.bad_levels or 0 for i in workshared])),
             ("Grids off workset", sum([i.bad_grids or 0 for i in workshared])),
             ("Items on Workset1", sum([i.workset1 or 0 for i in inspections])),
             ("Unused families", sum([i.unused.TotalUnusedFamilies for i in unused_done])),
             ("Unused types", sum([i.unused.TotalUnusedTypes for i in unused_done]))]

    out = [u'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">']
    out.append(u"<title>Link Manager - {0}</title>".format(esc(doc_title(doc, "Model"))))
    out.append(u"<style>" + REPORT_CSS + u"</style></head><body>")
    out.append(u"<h1><span>LINK MANAGER</span> report</h1>")
    out.append(u'<div class="meta">Host model: <b>{0}</b><br>Generated: {1}<br>'
               u'Accepted level / grid worksets: {2}</div>'.format(
        esc(doc_title(doc, "Unsaved")), esc(DateTime.Now.ToString("yyyy-MM-dd HH:mm")),
        esc(", ".join(VALID_LG_WORKSETS))))

    out.append(u'<div class="cards">')
    for label, value in cards:
        out.append(u'<div class="card"><div class="num">{0}</div><div class="lbl">{1}</div></div>'.format(
            value, esc(label)))
    out.append(u"</div>")

    out.append(u'<div class="toolbar"><input type="text" id="docFilter" placeholder="Filter links..." '
               u'oninput="filterDocs()"><button onclick="toggleAll(true)">Expand all</button>'
               u'<button onclick="toggleAll(false)">Collapse all</button>'
               u'<button onclick="window.print()">Print</button></div>')

    out.append(u'<table id="overview"><thead><tr>')
    headers = [("Link", False), ("Status", False), ("Sits on", False), ("RVT links", True),
               ("DWG links", True), ("DWG imports", True), ("Warnings", True), ("Bad lvl / grid", True),
               ("On Workset1", True), ("Unused fam / type", True)]
    for idx, pair in enumerate(headers):
        out.append(u'<th onclick="sortTable({0},{1})">{2}</th>'.format(
            idx, "true" if pair[1] else "false", esc(pair[0])))
    out.append(u'</tr></thead><tbody data-col="-1" data-dir="asc">')

    for index, row in enumerate(rows):
        insp = row["inspection"]
        pos_text, pos_css = position_summary(row)
        out.append(u'<tr data-name="{0}">'.format(esc(row["name"].lower())))
        out.append(u'<td class="doc" onclick="goDoc(\'doc-{0}\')">{1}</td>'.format(index, esc(row["name"])))
        out.append(u"<td>{0}</td>".format(esc(row["status"])))
        out.append(u"<td>{0}</td>".format(badge(pos_text, pos_css)))
        if insp is None:
            for _ in range(7):
                out.append(u'<td data-sort="-1">{0}</td>'.format(badge(DASH)))
            out.append(u"</tr>")
            continue
        for value in (insp.rvt_links, insp.dwg_links, insp.dwg_imports, insp.warnings):
            out.append(u'<td data-sort="{0}">{1}</td>'.format(value, badge(value)))
        lg_sort = (insp.bad_levels or 0) + (insp.bad_grids or 0) if insp.workshared else -1
        out.append(u'<td data-sort="{0}">{1}</td>'.format(lg_sort, badge(insp.col_lg())))
        out.append(u'<td data-sort="{0}">{1}</td>'.format(sort_number(insp.col_ws1()), badge(insp.col_ws1())))
        un_sort = -1
        if insp.unused is not None:
            un_sort = insp.unused.TotalUnusedFamilies + insp.unused.TotalUnusedTypes
        out.append(u'<td data-sort="{0}">{1}</td>'.format(un_sort, badge(insp.col_unused())))
        out.append(u"</tr>")
    out.append(u"</tbody></table>")

    out.append(u"<h2>Per link</h2>")
    for index, row in enumerate(rows):
        out.append(html_link_section(index, row))

    out.append(u'<div class="footer">Position: green sits there, amber is off but grids and levels still line '
               u'up, red grids or levels don\'t line up.<br>Unused items are found by counting placed instances '
               u'per type. Types used only by other types (curtain panels and mullions in a curtain wall type, '
               u'profiles, nested families) are listed as unused even though Revit can\'t purge them. Treat the '
               u'result as triage, not a purge list.<br>Workset1 counts cover categorised model elements only.'
               u'<br>Warnings come from each link as it was loaded; reload a link after someone cleans it.</div>')
    out.append(u"<script>" + REPORT_JS + u"</script></body></html>")
    return u"".join(out)


def safe_file_name(text):
    keep = "-_. "
    return u"".join([c if (c.isalnum() or c in keep) else "_" for c in text])


def open_file(path):
    """Open the report in the default browser."""
    if Process is not None and ProcessStartInfo is not None:
        try:
            info = ProcessStartInfo(path)
            info.UseShellExecute = True
            Process.Start(info)
            return
        except Exception:
            pass
    try:
        import os
        os.startfile(path)
        return
    except Exception:
        pass
    TaskDialog.Show(TOOL, u"The report was saved but couldn't be opened automatically:\n\n{0}".format(path))


def export_html(rows):
    html = build_report_html(rows)
    file_name = u"LinkManager_{0}_{1}.html".format(safe_file_name(doc_title(doc, "Model")),
                                                   DateTime.Now.ToString("yyyyMMdd_HHmmss"))
    path = Path.Combine(Path.GetTempPath(), file_name)
    File.WriteAllText(path, html, Encoding.UTF8)
    open_file(path)
    return path


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------
def apply_changes(rows, row_uis, worksets, include_instances):
    """Worksets, Room Bounding, moves (pinned afterwards) and pins - one transaction, one Undo."""
    plan = []
    checkout = List[ElementId]()
    for row in rows:
        combo = row["combo"]
        workset = None
        if worksets and combo is not None and combo.IsEnabled and combo.SelectedIndex >= 0:
            picked = worksets[combo.SelectedIndex]
            if id_value(picked.Id) != row["current_id"]:
                workset = picked
        room = None
        if row["room_box"] is not None and bool(row["room_box"].IsChecked) != row["room"]:
            room = bool(row["room_box"].IsChecked)
        inst_plan = []
        for entry in row["instances"]:
            pin = None
            if entry["pin_box"] is not None and bool(entry["pin_box"].IsChecked) != entry["pinned"]:
                pin = bool(entry["pin_box"].IsChecked)
            if entry["target"] or pin is not None:
                inst_plan.append((entry, entry["target"], pin))
        if workset is None and room is None and not inst_plan:
            continue
        plan.append((row, workset, room, inst_plan))
        if doc.IsWorkshared:
            checkout.Add(row["type_elem"].Id)
            for entry in row["instances"]:
                checkout.Add(entry["inst"].Id)

    if not plan:
        return None

    # Checkout must happen outside of a transaction
    if doc.IsWorkshared and checkout.Count:
        try:
            WorksharingUtils.CheckoutElements(doc, checkout)
        except Exception:
            pass

    done = {"worksets": 0, "room": 0, "moved": 0, "pins": 0}
    failures = []

    group = TransactionGroup(doc, TOOL)
    group.Start()
    transaction = Transaction(doc, TOOL)
    transaction.Start()
    try:
        for row, workset, room, inst_plan in plan:
            if workset is not None:
                target_id = id_value(workset.Id)
                elements = [row["type_elem"]]
                if include_instances:
                    elements = elements + [e["inst"] for e in row["instances"]]
                for element in elements:
                    param = workset_param(element)
                    if param is None or param.IsReadOnly or id_value(element.WorksetId) == target_id:
                        continue
                    try:
                        param.Set(target_id)
                        done["worksets"] += 1
                    except Exception as err:
                        failures.append(u"{0}: workset {1} - {2}".format(row["name"], workset.Name, err))
            if room is not None:
                try:
                    room_bounding_param(row["type_elem"]).Set(1 if room else 0)
                    done["room"] += 1
                except Exception as err:
                    failures.append(u"{0}: Room Bounding - {1}".format(row["name"], err))
            for entry, target_name, pin in inst_plan:
                inst = entry["inst"]
                if target_name:
                    target = targets_for(inst, inst.GetLinkDocument()).get(target_name)
                    if target is None:
                        failures.append(u"{0}: can't work out {1} (load the link)".format(row["name"], target_name))
                    else:
                        try:
                            move_link(inst, target)
                            done["moved"] += 1
                        except Exception as err:
                            failures.append(u"{0}: move to {1} - {2}".format(row["name"], target_name, err))
                        continue  # a moved link is pinned again
                if pin is not None:
                    try:
                        inst.Pinned = pin
                        done["pins"] += 1
                    except Exception as err:
                        failures.append(u"{0}: pin - {1}".format(row["name"], err))
        transaction.Commit()
        group.Assimilate()
    except Exception:
        if transaction.HasStarted() and not transaction.HasEnded():
            transaction.RollBack()
        if group.HasStarted() and not group.HasEnded():
            group.RollBack()
        raise
    return done, failures


def show_summary(done, failures):
    lines = ["Workset changes: {0}".format(done["worksets"]),
             "Room Bounding changes: {0}".format(done["room"]),
             "Links moved (and pinned): {0}".format(done["moved"]),
             "Pin changes: {0}".format(done["pins"])]
    if failures:
        lines.append("")
        lines.append("Failed ({0}):".format(len(failures)))
        lines.extend(failures[:15])
        if len(failures) > 15:
            lines.append("... and {0} more".format(len(failures) - 15))
    dialog = TaskDialog(TOOL)
    dialog.MainInstruction = "Done - one Undo puts it all back"
    dialog.MainContent = "\n".join(lines)
    dialog.Show()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    workset_list = collect_worksets()
    workset_names = {}
    for workset in workset_list:
        workset_names[id_value(workset.Id)] = workset.Name

    Mouse.OverrideCursor = Cursors.Wait
    try:
        rows = collect_rows(workset_names)
        inspections = attach_inspections(rows)
    finally:
        Mouse.OverrideCursor = None
    if not rows:
        TaskDialog.Show(TOOL, "No Revit links were found in this project.")
        return

    window = XamlReader.Parse(XAML)
    try:
        WindowInteropHelper(window).Owner = __revit__.MainWindowHandle  # noqa: F821
    except Exception:
        pass
    rows_panel = window.FindName("RowsPanel")
    search_box = window.FindName("SearchBox")
    search_hint = window.FindName("SearchHint")
    bulk_combo = window.FindName("BulkCombo")
    bulk_btn = window.FindName("BulkBtn")
    room_btn = window.FindName("RoomOnBtn")
    pin_btn = window.FindName("PinAllBtn")
    export_btn = window.FindName("ExportBtn")
    instances_check = window.FindName("InstancesCheck")
    count_text = window.FindName("CountText")
    ok_btn = window.FindName("OkBtn")
    cancel_btn = window.FindName("CancelBtn")

    window.FindName("SubTitle").Text = u"{0}{1}{2}{1}Click a link to inspect it on the right, change what you " \
                                       u"need, then click Apply changes.".format(doc.Title, DOT,
                                                                                 plural(len(rows), "Revit link"))

    make_header(window)
    row_uis = []
    pane = InspectorPane(window)
    SCAN_LISTENERS.append(pane.on_scanned)
    selected = [None]

    def select(ui):
        if selected[0] is not None:
            selected[0].set_selected(False)
        selected[0] = ui
        ui.set_selected(True)
        pane.show_row(ui.row)

    def update_count():
        visible = len([r for r in rows if r["border"].Visibility == Visibility.Visible])
        changed = len([u for u in row_uis if u.changed()])
        text = "Showing {0} of {1} links".format(visible, len(rows))
        if changed:
            text += u"{0}{1} changed - nothing is applied until you click Apply changes".format(DOT, changed)
        count_text.Text = text
        ok_btn.Content = "Apply changes ({0})".format(changed) if changed else "Apply changes"

    for row in rows:
        ui = RowUi(window, row, workset_list, update_count, select)
        rows_panel.Children.Add(ui.build())
        row_uis.append(ui)

    if workset_list:
        for workset in workset_list:
            bulk_combo.Items.Add(workset.Name)
        bulk_combo.SelectedIndex = 0
    else:
        bulk_combo.Items.Add("Not workshared")
        bulk_combo.SelectedIndex = 0
        bulk_combo.IsEnabled = False
        bulk_btn.IsEnabled = False
        instances_check.IsEnabled = False

    if not inspections:
        export_btn.IsEnabled = False
        export_btn.ToolTip = "Load at least one link to export a report"

    update_count()
    result = [False]
    include_instances = [True]

    def visible_rows():
        return [r for r in rows if r["border"].Visibility == Visibility.Visible]

    def refresh_all():
        for ui in row_uis:
            ui.refresh()
        update_count()

    def on_search(sender, args):
        needle = (search_box.Text or "").strip().lower()
        search_hint.Visibility = Visibility.Collapsed if needle else Visibility.Visible
        for row in rows:
            haystack = " ".join([row["name"], row["status"], row["current_name"]]).lower()
            match = (not needle) or (needle in haystack)
            row["border"].Visibility = Visibility.Visible if match else Visibility.Collapsed
        update_count()

    def on_bulk(sender, args):
        index = bulk_combo.SelectedIndex
        if index < 0 or not workset_list:
            return
        for row in visible_rows():
            if row["combo"].IsEnabled:
                row["combo"].SelectedIndex = index
        refresh_all()

    def on_room(sender, args):
        for row in visible_rows():
            if row["room_box"] is not None and row["room_box"].IsEnabled:
                row["room_box"].IsChecked = True
        refresh_all()

    def on_pin(sender, args):
        for row in visible_rows():
            for entry in row["instances"]:
                if entry["pin_box"] is not None and entry["pin_box"].IsEnabled:
                    entry["pin_box"].IsChecked = True
        refresh_all()

    def on_export(sender, args):
        pending = [i for i in inspections if i.unused is None]
        if pending:
            dialog = TaskDialog(TOOL)
            dialog.MainInstruction = "Include unused families and types?"
            dialog.MainContent = ("{0} not been scanned for unused items yet. Scanning reads every family type "
                                  "in each link, so it can take a while on big models.\n\n"
                                  "Yes: scan them now and include them.\nNo: export without them."
                                  ).format(plural(len(pending), "loaded link has", "loaded links have"))
            dialog.CommonButtons = (TaskDialogCommonButtons.Yes | TaskDialogCommonButtons.No |
                                    TaskDialogCommonButtons.Cancel)
            dialog.DefaultButton = TaskDialogResult.No
            answer = dialog.Show()
            if answer == TaskDialogResult.Cancel:
                return
            if answer == TaskDialogResult.Yes:
                run_unused_scans(pending)
        Mouse.OverrideCursor = Cursors.Wait
        try:
            export_html(rows)
        except Exception as ex:
            Mouse.OverrideCursor = None
            TaskDialog.Show(TOOL, u"The report couldn't be written:\n\n{0}".format(ex))
        finally:
            Mouse.OverrideCursor = None

    def on_ok(sender, args):
        if not any(u.changed() for u in row_uis):
            TaskDialog.Show(TOOL, "Nothing has changed yet. Change a workset, a checkbox or a position first.")
            return
        include_instances[0] = bool(instances_check.IsChecked)
        result[0] = True
        window.Close()

    def on_cancel(sender, args):
        result[0] = False
        window.Close()

    search_box.TextChanged += TextChangedEventHandler(on_search)
    bulk_btn.Click += RoutedEventHandler(on_bulk)
    room_btn.Click += RoutedEventHandler(on_room)
    pin_btn.Click += RoutedEventHandler(on_pin)
    export_btn.Click += RoutedEventHandler(on_export)
    ok_btn.Click += RoutedEventHandler(on_ok)
    cancel_btn.Click += RoutedEventHandler(on_cancel)

    frame = DispatcherFrame()

    def on_closed(sender, args):
        frame.Continue = False

    window.Closed += EventHandler(on_closed)
    enable_combo_search(window)
    window.Show()
    Dispatcher.PushFrame(frame)

    if not result[0]:
        return

    outcome = apply_changes(rows, row_uis, workset_list, include_instances[0])
    if outcome is None:
        return
    show_summary(outcome[0], outcome[1])


main()
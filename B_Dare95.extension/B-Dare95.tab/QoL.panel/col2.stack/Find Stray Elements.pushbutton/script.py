# -*- coding: utf-8 -*-
__doc__ = """__________________________________________________
Description:

Finds stray model elements: walls, families, pipes and other physical elements placed far outside the building by mistake. Lines, sketches, rooms and other non-physical elements are left out.
The building boundary is drawn through the outermost grid intersections (on a rectangular grid, the four corner intersections); curved grids count too. When the model has no grids, the grids of a link are used. An element is stray when it sits more than the distance you set outside that boundary, in plan.
Nothing in the model is changed. You can select, isolate or export what it finds.
__________________________________________________
How-to:

-> Click on the button
-> Choose to look in the whole model or the active view
-> If the model has no grids, pick the link whose grids outline the building
-> Set the distance outside the building boundary, in meters
-> Click Check
-> Click rows in the list (Ctrl / Shift for several, or Select all)
-> Click Select to zoom to them, Isolate to isolate them in the view, or Export to Excel
__________________________________________________
Author: Mohamed Bedair"""

import math
import os
import traceback

import clr
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")
clr.AddReference("System.Xml")
clr.AddReference("System.Windows.Forms")
clr.AddReference("System.IO.Compression")

from System import EventHandler
from System.Collections.Generic import List
from System.IO import File, MemoryStream, Path
from System.IO.Compression import ZipArchive, ZipArchiveMode
from System.Text import Encoding
from System.Windows import RoutedEventHandler, Visibility
from System.Windows.Controls import SelectionChangedEventHandler, TextChangedEventHandler
from System.Windows.Markup import XamlReader
from System.Windows.Threading import Dispatcher, DispatcherFrame
from System.Windows.Forms import SaveFileDialog, DialogResult

from Autodesk.Revit.DB import (
    BuiltInCategory,
    BuiltInParameter,
    CategoryType,
    Arc,
    CurveElement,
    Element,
    ElementId,
    FamilyInstance,
    FamilySymbol,
    FilteredElementCollector,
    Grid,
    Group,
    ImportInstance,
    Level,
    Line,
    LocationCurve,
    LocationPoint,
    ReferencePlane,
    RevitLinkInstance,
    SketchPlane,
    SpatialElement,
    StorageType,
    Transaction,
    View,
)
from Autodesk.Revit.UI import TaskDialog

from pyrevit import revit

from bd_combo_search import enable_combo_search

doc = revit.doc
uidoc = revit.uidoc

TITLE = "Find Stray Elements"
FT_MM = 304.8
FT_M = FT_MM / 1000.0

DEFAULT_DISTANCE_M = 30.0

# Grids closer to parallel than this are not intersected (their crossing point
# would be far away and meaningless).
MIN_GRID_ANGLE_DEG = 1.0

# Intersections are kept only inside the area the grids themselves cover,
# grown by this much, so two grids that stop short of each other still count.
GRID_EXTENT_SLACK_M = 5.0

# Model categories that are not "placed" elements: datums, links, cameras,
# base points, scope boxes, site, and the hidden MEP centre lines.
SKIP_CATEGORIES = (
    "OST_VolumeOfInterest", "OST_Cameras", "OST_SectionBox", "OST_ProjectBasePoint",
    "OST_SharedBasePoint", "OST_IOS_GeoSite", "OST_Levels", "OST_Grids", "OST_RvtLinks",
    "OST_Sun", "OST_Topography", "OST_Toposolid", "OST_Site", "OST_IOSModelGroups",
    "OST_Matchline", "OST_CenterLines", "OST_CableTrayCenterLine",
    "OST_CableTrayFittingCenterLine", "OST_ConduitCenterLine",
    "OST_ConduitFittingCenterLine", "OST_DuctCurvesCenterLine",
    "OST_DuctFittingCenterLine", "OST_FlexDuctCurvesCenterLine",
    "OST_PipeCurvesCenterLine", "OST_PipeFittingCenterLine",
    "OST_FlexPipeCurvesCenterLine",
    # lines, sketches and reference planes
    "OST_Lines", "OST_SketchLines", "OST_CLines", "OST_RoomSeparationLines",
    "OST_MEPSpaceSeparationLines", "OST_AreaSchemeLines", "OST_InternalOrigin",
    # rooms, spaces and areas are not physical elements
    "OST_Rooms", "OST_MEPSpaces", "OST_Areas",
)

# Samples taken along a curved grid when it forms part of the boundary.
ARC_SAMPLES = 24

# Where the level lives when an element has no LevelId (face-hosted
# instances, pipes and ducts, beams ...). Only used to show the level name.
LEVEL_PARAMS = ("INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM", "RBS_START_LEVEL_PARAM",
                "INSTANCE_REFERENCE_LEVEL_PARAM", "FAMILY_LEVEL_PARAM",
                "SCHEDULE_LEVEL_PARAM")

COLUMNS = [u"Id", u"Category", u"Family", u"Type", u"Level", u"Distance (m)", u"Detail"]


# ---------------------------------------------------------------------------
# Building boundary from the grids (plain Python, no Revit API)
# ---------------------------------------------------------------------------
def line_intersection(a, b, min_sin):
    """Crossing point of the infinite lines through segments a and b
    ((x1, y1), (x2, y2)), or None when they are (nearly) parallel."""
    (x1, y1), (x2, y2) = a
    (x3, y3), (x4, y4) = b
    dx1, dy1 = x2 - x1, y2 - y1
    dx2, dy2 = x4 - x3, y4 - y3
    l1 = math.hypot(dx1, dy1)
    l2 = math.hypot(dx2, dy2)
    if l1 < 1e-9 or l2 < 1e-9:
        return None
    cross = dx1 * dy2 - dy1 * dx2
    if abs(cross) / (l1 * l2) < min_sin:
        return None
    t = ((x3 - x1) * dy2 - (y3 - y1) * dx2) / cross
    return (x1 + t * dx1, y1 + t * dy1)


def circle_line(c, r, seg):
    """Points where the infinite line through seg crosses the circle (c, r)."""
    (x1, y1), (x2, y2) = seg
    dx, dy = x2 - x1, y2 - y1
    a = dx * dx + dy * dy
    if a < 1e-12:
        return []
    fx, fy = x1 - c[0], y1 - c[1]
    b = 2 * (fx * dx + fy * dy)
    k = fx * fx + fy * fy - r * r
    disc = b * b - 4 * a * k
    if disc < 0:
        return []
    root = math.sqrt(disc)
    return [(x1 + t * dx, y1 + t * dy) for t in ((-b - root) / (2 * a), (-b + root) / (2 * a))]


def circle_circle(c1, r1, c2, r2):
    """Points where two circles cross."""
    d = math.hypot(c2[0] - c1[0], c2[1] - c1[1])
    if d < 1e-9 or d > r1 + r2 or d < abs(r1 - r2):
        return []
    a = (r1 * r1 - r2 * r2 + d * d) / (2 * d)
    h = math.sqrt(max(r1 * r1 - a * a, 0.0))
    mx = c1[0] + a * (c2[0] - c1[0]) / d
    my = c1[1] + a * (c2[1] - c1[1]) / d
    ox, oy = h * (c2[1] - c1[1]) / d, h * (c2[0] - c1[0]) / d
    return [(mx + ox, my - oy), (mx - ox, my + oy)]


def arc_between(c, r, points, samples=ARC_SAMPLES):
    """Points along the circle (c, r) across the stretch holding `points`
    (the shorter way round), so the boundary follows a curved grid."""
    angles = sorted([math.atan2(p[1] - c[1], p[0] - c[0]) for p in points])
    if len(angles) < 2:
        return []
    # the stretch is everything except the biggest empty gap between hits
    gaps = [(angles[(i + 1) % len(angles)] - angles[i]) % (2 * math.pi) for i in range(len(angles))]
    k = max(range(len(gaps)), key=lambda i: gaps[i])
    start = angles[(k + 1) % len(angles)]
    span = 2 * math.pi - gaps[k]
    return [(c[0] + r * math.cos(start + span * i / float(samples)),
             c[1] + r * math.sin(start + span * i / float(samples))) for i in range(samples + 1)]


def grid_intersections(grids, slack, min_angle_deg=MIN_GRID_ANGLE_DEG):
    """Points outlining the building: every crossing of two grids inside the
    area the grids cover (grown by `slack`), plus points along each curved grid
    between its crossings.

    grids: [("line", ((x1, y1), (x2, y2)))] and [("arc", (cx, cy), radius, [points along it])].
    Straight grids are extended and curved grids completed to full circles, so
    grids that stop short of each other still cross."""
    if not grids:
        return []
    xs, ys = [], []
    for g in grids:
        pts = g[1] if g[0] == "line" else g[3]
        xs += [p[0] for p in pts]
        ys += [p[1] for p in pts]
    box = (min(xs) - slack, min(ys) - slack, max(xs) + slack, max(ys) + slack)

    def keep(p):
        return box[0] <= p[0] <= box[2] and box[1] <= p[1] <= box[3]

    lines = [g[1] for g in grids if g[0] == "line"]
    arcs = [g for g in grids if g[0] == "arc"]
    min_sin = math.sin(math.radians(min_angle_deg))
    out = []
    for i in range(len(lines)):
        for j in range(i + 1, len(lines)):
            p = line_intersection(lines[i], lines[j], min_sin)
            if p is not None and keep(p):
                out.append(p)
    hits = [[] for _ in arcs]
    for i, (_kind, c, r, _pts) in enumerate(arcs):
        for seg in lines:
            for p in circle_line(c, r, seg):
                if keep(p):
                    out.append(p)
                    hits[i].append(p)
        for j in range(i + 1, len(arcs)):
            for p in circle_circle(c, r, arcs[j][1], arcs[j][2]):
                if keep(p):
                    out.append(p)
                    hits[i].append(p)
                    hits[j].append(p)
    for i, (_kind, c, r, pts) in enumerate(arcs):
        # follow the curve between its crossings; a curved grid crossing nothing
        # still marks the building with its own points
        out += arc_between(c, r, hits[i]) if len(hits[i]) >= 2 else list(pts)
    return out


def convex_hull(points):
    """Outer boundary of the points, counter-clockwise (Andrew's monotone chain).
    On a rectangular grid these are the four corner intersections."""
    pts = sorted(set((round(x, 6), round(y, 6)) for x, y in points))
    if len(pts) < 3:
        return pts

    def turn(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and turn(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and turn(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    hull = lower[:-1] + upper[:-1]
    # drop corners that are really on a straight edge (rounding noise on rotated grids)
    out = []
    n = len(hull)
    for i in range(n):
        o, a, b = hull[i - 1], hull[i], hull[(i + 1) % n]
        la = math.hypot(a[0] - o[0], a[1] - o[1])
        lb = math.hypot(b[0] - a[0], b[1] - a[1])
        if la > 1e-9 and lb > 1e-9 and abs(turn(o, a, b)) / (la * lb) < 1e-4:
            continue
        out.append(a)
    return out if len(out) >= 3 else hull


def segment_distance(p, a, b):
    ax, ay = a
    dx, dy = b[0] - ax, b[1] - ay
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 < 1e-12 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / length2))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))


def distance_outside(p, hull):
    """How far point p lies outside the boundary in plan (0 when inside)."""
    n = len(hull)
    inside = True
    for i in range(n):
        a, b = hull[i], hull[(i + 1) % n]
        if (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]) < -1e-9:
            inside = False
            break
    if inside:
        return 0.0
    return min(segment_distance(p, hull[i], hull[(i + 1) % n]) for i in range(n))


# ---------------------------------------------------------------------------
# Revit helpers
# ---------------------------------------------------------------------------
def eid_value(element_id):
    """ElementId -> Python int on Revit 2024 (.IntegerValue) and 2025+ (.Value)."""
    try:
        return int(element_id.Value)
    except AttributeError:
        return int(element_id.IntegerValue)


def make_id(number):
    try:
        from System import Int64
        return ElementId(Int64(int(number)))
    except Exception:
        return ElementId(int(number))


def elem_name(element):
    if element is None:
        return u""
    try:
        return Element.Name.GetValue(element) or u""
    except Exception:
        pass
    try:
        return element.Name or u""
    except Exception:
        return u""


def bip_param(element, name):
    bip = getattr(BuiltInParameter, name, None)
    if bip is None or element is None:
        return None
    try:
        return Element.get_Parameter(element, bip)
    except Exception:
        try:
            return element.get_Parameter(bip)
        except Exception:
            return None


def skip_category_ids():
    ids = set()
    for name in SKIP_CATEGORIES:
        bic = getattr(BuiltInCategory, name, None)
        if bic is None:
            continue
        try:
            ids.add(int(bic))
        except Exception:
            pass
    return ids


def grid_data(document, transform=None):
    """Every grid of `document` as plan geometry (see grid_intersections), moved
    by `transform` (a link's transform) into this model's coordinates."""
    out = []
    for g in FilteredElementCollector(document).OfClass(Grid):
        try:
            c = g.Curve
            if transform is not None:
                c = c.CreateTransformed(transform)
        except Exception:
            continue
        if isinstance(c, Line):
            a, b = c.GetEndPoint(0), c.GetEndPoint(1)
            out.append(("line", ((a.X, a.Y), (b.X, b.Y))))
        elif isinstance(c, Arc):
            try:
                pts = [(p.X, p.Y) for p in c.Tessellate()]
            except Exception:
                pts = [(c.GetEndPoint(i).X, c.GetEndPoint(i).Y) for i in (0, 1)]
            out.append(("arc", (c.Center.X, c.Center.Y), c.Radius, pts))
    return out


def boundary_from(document, transform=None):
    """(boundary points, number of grids), boundary None when the grids don't
    cross enough to outline a building."""
    grids = grid_data(document, transform)
    hull = convex_hull(grid_intersections(grids, GRID_EXTENT_SLACK_M / FT_M))
    return (hull if len(hull) >= 3 else None), len(grids)


def describe(grid_count, boundary, source=None):
    text = u"Outlined by {0} grids".format(grid_count)
    if source:
        text += u" from {0}".format(source)
    return text + u" through {0} boundary points.".format(len(boundary))


def links_with_grids():
    """[(label, link instance)] of the loaded links that have grids."""
    found = []
    for inst in FilteredElementCollector(doc).OfClass(RevitLinkInstance):
        ld = inst.GetLinkDocument()
        if ld is None:
            continue
        n = FilteredElementCollector(ld).OfClass(Grid).GetElementCount()
        if n < 2:
            continue
        try:
            name = Path.GetFileName(ld.PathName) if ld.PathName else ld.Title
        except Exception:
            name = ld.Title
        found.append([name, inst, n])
    names = [f[0] for f in found]
    out = []
    for name, inst, n in found:
        label = name if names.count(name) == 1 else u"{0} (instance {1})".format(name, eid_value(inst.Id))
        out.append((u"{0}  \u00B7  {1} grids".format(label, n), label, inst))
    out.sort(key=lambda x: x[0].lower())
    return out


def plan_point(e):
    """Where the element sits in plan: its location point, the middle of its
    location line, or (only when it has neither) the middle of its bounding box.
    Reading the location is much cheaper than computing a bounding box."""
    try:
        loc = e.Location
        if isinstance(loc, LocationPoint):
            p = loc.Point
            return (p.X, p.Y)
        if isinstance(loc, LocationCurve):
            p = loc.Curve.Evaluate(0.5, True)
            return (p.X, p.Y)
    except Exception:
        pass
    try:
        box = e.get_BoundingBox(None)
    except Exception:
        box = None
    if box is None:
        return None
    return ((box.Min.X + box.Max.X) / 2.0, (box.Min.Y + box.Max.Y) / 2.0)


def candidates(view=None):
    """[(element, plan point)] of the placed physical model elements: no lines,
    sketches, reference planes, rooms / spaces / areas, view-specific elements,
    links, CAD, groups, views, levels, grids, base points, scope boxes or cameras."""
    skip = skip_category_ids()
    if view is not None:
        collector = FilteredElementCollector(doc, view.Id)
    else:
        collector = FilteredElementCollector(doc)
    out = []
    for e in collector.WhereElementIsNotElementType():
        try:
            c = e.Category
            if c is None or c.CategoryType != CategoryType.Model:
                continue
            if eid_value(c.Id) in skip:
                continue
            if e.ViewSpecific:                   # detail lines, detail items, tags ...
                continue
            # lines, sketches, reference planes, rooms / spaces / areas, links, CAD, groups
            if isinstance(e, (CurveElement, SketchPlane, ReferencePlane, SpatialElement,
                              RevitLinkInstance, ImportInstance, Group, View)):
                continue
        except Exception:
            continue
        p = plan_point(e)
        if p is not None:
            out.append((e, p))
    return out


def level_names():
    return dict((eid_value(l.Id), l.Name) for l in FilteredElementCollector(doc).OfClass(Level))


def level_id_of(e):
    lid = getattr(e, "LevelId", None)
    try:
        if lid is not None and eid_value(lid) > 0:
            return eid_value(lid)
    except Exception:
        pass
    for name in LEVEL_PARAMS:
        p = bip_param(e, name)
        try:
            if p is not None and p.StorageType == StorageType.ElementId:
                v = eid_value(p.AsElementId())
                if v > 0:
                    return v
        except Exception:
            continue
    return -1


def element_facts(e, names):
    """Category, family, type and level names for the results list."""
    family, type_name = u"", u""
    try:
        if isinstance(e, FamilyInstance) and e.Symbol is not None:
            family, type_name = e.Symbol.Family.Name, elem_name(e.Symbol)
        else:
            tid = e.GetTypeId()
            t = doc.GetElement(tid) if eid_value(tid) > 0 else None
            if isinstance(t, FamilySymbol):
                family, type_name = t.Family.Name, elem_name(t)
            elif t is not None:
                family = getattr(t, "FamilyName", u"") or u""
                type_name = elem_name(t)
    except Exception:
        pass
    category = e.Category.Name if e.Category is not None else u""
    level = names.get(level_id_of(e), u"")
    return category, family, type_name, level


# ---------------------------------------------------------------------------
# The check
# ---------------------------------------------------------------------------
def find(boundary, distance_m, view=None):
    """[{Id, Category, Family, Type, Level, Distance (m), Detail}], farthest first."""
    limit = distance_m / FT_M
    names = level_names()
    rows = []
    for e, p in candidates(view):
        d = distance_outside(p, boundary)
        if d <= limit:
            continue
        category, family, type_name, level = element_facts(e, names)
        meters = round(d * FT_M, 1)
        rows.append({u"Id": eid_value(e.Id), u"Category": category, u"Family": family,
                     u"Type": type_name, u"Level": level, u"Distance (m)": meters,
                     u"Detail": u"{0:.1f} m outside the building boundary".format(meters)})
    rows.sort(key=lambda r: (-r[u"Distance (m)"], r[u"Category"].lower(), r[u"Id"]))
    return rows


# ---------------------------------------------------------------------------
# Excel export (zero-dependency .xlsx)
# ---------------------------------------------------------------------------
def xml_esc(text):
    return (u"{0}".format(text).replace(u"&", u"&amp;").replace(u"<", u"&lt;")
            .replace(u">", u"&gt;").replace(u'"', u"&quot;"))


def col_letter(idx0):
    n = idx0 + 1
    s = u""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = unichr(65 + r) + s
    return s


def build_xlsx(sheet_name, table):
    """table: [[cell, ...], ...] (first row = header). Numbers stay numbers."""
    rows_xml = []
    for r, row in enumerate(table):
        cells = []
        for c, value in enumerate(row):
            ref = u"{0}{1}".format(col_letter(c), r + 1)
            if isinstance(value, (int, long, float)) and not isinstance(value, bool):
                cells.append(u'<c r="{0}"><v>{1}</v></c>'.format(ref, value))
            else:
                cells.append(u'<c r="{0}" t="inlineStr"{1}><is><t xml:space="preserve">{2}</t></is></c>'
                             .format(ref, u' s="1"' if r == 0 else u"", xml_esc(value)))
        rows_xml.append(u'<row r="{0}">{1}</row>'.format(r + 1, u"".join(cells)))

    parts = {
        u"[Content_Types].xml":
            u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            u'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            u'<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            u'<Default Extension="xml" ContentType="application/xml"/>'
            u'<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            u'<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            u'<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            u'</Types>',
        u"_rels/.rels":
            u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            u'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            u'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            u'</Relationships>',
        u"xl/workbook.xml":
            u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            u'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            u'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            u'<sheets><sheet name="{0}" sheetId="1" r:id="rId1"/></sheets></workbook>'.format(xml_esc(sheet_name)),
        u"xl/_rels/workbook.xml.rels":
            u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            u'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            u'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            u'<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            u'</Relationships>',
        u"xl/styles.xml":
            u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            u'<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            u'<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
            u'<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
            u'<fills count="2"><fill><patternFill patternType="none"/></fill>'
            u'<fill><patternFill patternType="gray125"/></fill></fills>'
            u'<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
            u'<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            u'<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
            u'<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
            u'<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
            u'</styleSheet>',
        u"xl/worksheets/sheet1.xml":
            u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            u'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            u'<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" '
            u'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
            u'<sheetData>{0}</sheetData></worksheet>'.format(u"".join(rows_xml)),
    }

    stream = MemoryStream()
    archive = ZipArchive(stream, ZipArchiveMode.Create, True)
    for name in [u"[Content_Types].xml", u"_rels/.rels", u"xl/workbook.xml",
                 u"xl/_rels/workbook.xml.rels", u"xl/styles.xml", u"xl/worksheets/sheet1.xml"]:
        entry = archive.CreateEntry(name)
        s = entry.Open()
        data = Encoding.UTF8.GetBytes(parts[name])
        s.Write(data, 0, data.Length)
        s.Dispose()
    archive.Dispose()
    return stream.ToArray()


def model_name():
    title = doc.Title or u"Model"
    if title.lower().endswith(u".rvt"):
        title = title[:-4]
    return u"".join([c if (c.isalnum() or c in u"-_. ") else u"_" for c in title])


def ask_save_path(default_name):
    dlg = SaveFileDialog()
    dlg.Title = u"Save the list"
    dlg.Filter = u"Excel Workbook (*.xlsx)|*.xlsx"
    dlg.DefaultExt = u"xlsx"
    dlg.AddExtension = True
    dlg.OverwritePrompt = True
    dlg.FileName = default_name
    try:
        if doc.PathName and os.path.isdir(os.path.dirname(doc.PathName)):
            dlg.InitialDirectory = os.path.dirname(doc.PathName)
    except Exception:
        pass
    if dlg.ShowDialog() == DialogResult.OK:
        return dlg.FileName
    return None


def open_file(path):
    try:
        os.startfile(path)
    except Exception:
        TaskDialog.Show(TITLE, u"Saved, but could not open it:\n{0}".format(path))


# ---------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------
STYLES = u"""
  <Window.Resources>
    <Style x:Key="FlatButton" TargetType="Button">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="BorderBrush" Value="#525252"/>
      <Setter Property="Padding" Value="14,8"/>
      <Setter Property="Margin" Value="8,0,0,0"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="Bd" CornerRadius="6" Background="{TemplateBinding Background}"
                    BorderBrush="{TemplateBinding BorderBrush}" BorderThickness="1"
                    Padding="{TemplateBinding Padding}">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#525252"/>
                <Setter TargetName="Bd" Property="BorderBrush" Value="#F1C21B"/>
              </Trigger>
              <Trigger Property="IsEnabled" Value="False">
                <Setter TargetName="Bd" Property="Background" Value="#262626"/>
                <Setter Property="Foreground" Value="#8D8D8D"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style x:Key="AccentButton" TargetType="Button" BasedOn="{StaticResource FlatButton}">
      <Setter Property="Foreground" Value="#161616"/>
      <Setter Property="Background" Value="#F1C21B"/>
      <Setter Property="BorderBrush" Value="#F1C21B"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
    </Style>
    <Style x:Key="ToggleChip" TargetType="ToggleButton">
      <Setter Property="Foreground" Value="#A8A8A8"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Margin" Value="0,0,8,8"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="HorizontalContentAlignment" Value="Left"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ToggleButton">
            <Border x:Name="Chip" CornerRadius="6" BorderThickness="1"
                    Background="#393939" BorderBrush="#525252" Padding="12,7">
              <ContentPresenter VerticalAlignment="Center"
                                HorizontalAlignment="{TemplateBinding HorizontalContentAlignment}"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsChecked" Value="True">
                <Setter TargetName="Chip" Property="Background" Value="#F1C21B"/>
                <Setter TargetName="Chip" Property="BorderBrush" Value="#F1C21B"/>
                <Setter Property="Foreground" Value="#161616"/>
              </Trigger>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="Chip" Property="BorderBrush" Value="#F1C21B"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style x:Key="NumBox" TargetType="TextBox">
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="BorderBrush" Value="#525252"/>
      <Setter Property="CaretBrush" Value="#F1C21B"/>
      <Setter Property="Padding" Value="6,4"/>
      <Setter Property="Width" Value="90"/>
      <Setter Property="FontSize" Value="12"/>
    </Style>
    <Style TargetType="ComboBoxItem">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Padding" Value="8,5"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ComboBoxItem">
            <Border x:Name="Bd" Background="Transparent" Padding="{TemplateBinding Padding}">
              <ContentPresenter/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsHighlighted" Value="True"><Setter TargetName="Bd" Property="Background" Value="#393939"/></Trigger>
              <Trigger Property="IsSelected" Value="True"><Setter TargetName="Bd" Property="Background" Value="#525252"/></Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style TargetType="ComboBox">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Height" Value="30"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ComboBox">
            <Grid>
              <ToggleButton Focusable="False" ClickMode="Press"
                            IsChecked="{Binding IsDropDownOpen, Mode=TwoWay, RelativeSource={RelativeSource TemplatedParent}}">
                <ToggleButton.Template>
                  <ControlTemplate TargetType="ToggleButton">
                    <Border x:Name="Bd" Background="#393939" BorderBrush="#525252" BorderThickness="1" CornerRadius="6">
                      <Path HorizontalAlignment="Right" VerticalAlignment="Center" Margin="0,0,10,0"
                            Data="M0,0 L4,4 L8,0" Stroke="#A8A8A8" StrokeThickness="1.5"/>
                    </Border>
                    <ControlTemplate.Triggers>
                      <Trigger Property="IsMouseOver" Value="True"><Setter TargetName="Bd" Property="BorderBrush" Value="#F1C21B"/></Trigger>
                    </ControlTemplate.Triggers>
                  </ControlTemplate>
                </ToggleButton.Template>
              </ToggleButton>
              <ContentPresenter IsHitTestVisible="False" Margin="8,0,26,0" VerticalAlignment="Center"
                                Content="{TemplateBinding SelectionBoxItem}"/>
              <Popup IsOpen="{TemplateBinding IsDropDownOpen}" Placement="Bottom" AllowsTransparency="True"
                     Focusable="False" PopupAnimation="Slide">
                <Border Background="#262626" BorderBrush="#525252" BorderThickness="1" CornerRadius="6" Margin="0,2,0,0"
                        MinWidth="{Binding ActualWidth, RelativeSource={RelativeSource TemplatedParent}}" MaxHeight="320">
                  <ScrollViewer VerticalScrollBarVisibility="Auto">
                    <ItemsPresenter KeyboardNavigation.DirectionalNavigation="Contained"/>
                  </ScrollViewer>
                </Border>
              </Popup>
            </Grid>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style x:Key="HeaderStyle" TargetType="GridViewColumnHeader">
      <Setter Property="Background" Value="#262626"/>
      <Setter Property="Foreground" Value="#A8A8A8"/>
      <Setter Property="BorderBrush" Value="#525252"/>
      <Setter Property="BorderThickness" Value="0,0,1,1"/>
      <Setter Property="Padding" Value="8,6"/>
      <Setter Property="HorizontalContentAlignment" Value="Left"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
    </Style>
    <Style x:Key="RowStyle" TargetType="ListViewItem">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Background" Value="Transparent"/>
      <Setter Property="Padding" Value="4,5"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ListViewItem">
            <Border x:Name="RowBd" Background="{TemplateBinding Background}"
                    BorderBrush="#262626" BorderThickness="0,0,0,1"
                    Padding="{TemplateBinding Padding}">
              <GridViewRowPresenter Content="{TemplateBinding Content}"
                                    Columns="{TemplateBinding GridView.ColumnCollection}"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="RowBd" Property="Background" Value="#262626"/>
              </Trigger>
              <Trigger Property="IsSelected" Value="True">
                <Setter TargetName="RowBd" Property="Background" Value="#525252"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
  </Window.Resources>
"""

OPTIONS_XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Find Stray Elements" Width="560" SizeToContent="Height"
        WindowStartupLocation="CenterScreen" ResizeMode="NoResize"
        Background="#161616">
""" + STYLES + u"""
  <StackPanel Margin="18">
    <TextBlock Text="Find Stray Elements" Foreground="#F4F4F4" FontSize="20" FontWeight="Bold"/>
    <TextBlock Foreground="#A8A8A8" FontSize="12" Margin="0,4,0,14" TextWrapping="Wrap"
               Text="Elements placed far outside the building by mistake. Nothing is changed."/>

    <TextBlock Text="LOOK IN" Foreground="#F1C21B" FontSize="11" FontWeight="Bold" Margin="0,0,0,6"/>
    <WrapPanel Margin="0,0,0,10">
      <ToggleButton x:Name="ScopeModel" Style="{StaticResource ToggleChip}" Content="Whole model" IsChecked="True"/>
      <ToggleButton x:Name="ScopeView" Style="{StaticResource ToggleChip}" Content="Active view"/>
    </WrapPanel>

    <StackPanel x:Name="LinkPanel" Visibility="Collapsed" Margin="0,0,0,10">
      <TextBlock Text="GRIDS FROM A LINK" Foreground="#F1C21B" FontSize="11" FontWeight="Bold" Margin="0,0,0,6"/>
      <TextBlock Foreground="#A8A8A8" FontSize="11" TextWrapping="Wrap" Margin="0,0,0,6"
                 Text="This model has no grids that outline the building. Pick the link whose grids do."/>
      <ComboBox x:Name="LinkCombo"/>
    </StackPanel>

    <TextBlock Text="BUILDING BOUNDARY" Foreground="#F1C21B" FontSize="11" FontWeight="Bold" Margin="0,0,0,6"/>
    <Border Background="#262626" CornerRadius="8" Padding="12" Margin="0,0,0,14">
      <Grid>
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="*"/>
          <ColumnDefinition Width="Auto"/>
        </Grid.ColumnDefinitions>
        <StackPanel Grid.Column="0">
          <TextBlock x:Name="BoundaryText" Foreground="#F4F4F4" FontSize="12" TextWrapping="Wrap" Margin="0,0,0,4"/>
          <TextBlock Foreground="#A8A8A8" FontSize="11" TextWrapping="Wrap"
                     Text="The boundary runs through the outermost grid intersections (the four corner intersections on a rectangular grid) and follows curved grids. A model element more than this distance outside it, in plan, is stray."/>
        </StackPanel>
        <StackPanel Grid.Column="1" Margin="12,0,0,0" VerticalAlignment="Top">
          <TextBlock Text="Distance (m)" Foreground="#A8A8A8" FontSize="11" Margin="0,0,0,3"/>
          <TextBox x:Name="MarginBox" Style="{StaticResource NumBox}" Text="30"/>
        </StackPanel>
      </Grid>
    </Border>

    <TextBlock x:Name="ErrorText" Foreground="#FA4D56" FontSize="12" Margin="0,0,0,10"
               TextWrapping="Wrap" Visibility="Collapsed"/>
    <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
      <Button x:Name="CancelButton" Style="{StaticResource FlatButton}" Content="Cancel"/>
      <Button x:Name="CheckButton" Style="{StaticResource AccentButton}" Content="Check"/>
    </StackPanel>
  </StackPanel>
</Window>
"""

RESULTS_XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Find Stray Elements" Height="680" Width="1180"
        WindowStartupLocation="CenterScreen" Background="#161616">
""" + STYLES + u"""
  <Grid Margin="16">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <StackPanel Grid.Row="0" Margin="0,0,0,12">
      <TextBlock x:Name="Header" Foreground="#F4F4F4" FontSize="20" FontWeight="Bold"/>
      <TextBlock x:Name="SubHeader" Foreground="#A8A8A8" FontSize="12" Margin="0,4,0,0"/>
    </StackPanel>

    <Border Grid.Row="1" Background="#262626" CornerRadius="6" Padding="10,6"
            BorderBrush="#525252" BorderThickness="1" Margin="0,0,0,12">
      <Grid>
        <TextBlock x:Name="SearchHint" Text="Search id, category, family, type or level..."
                   Foreground="#8D8D8D" FontSize="12" VerticalAlignment="Center" IsHitTestVisible="False"/>
        <TextBox x:Name="SearchBox" Background="Transparent" BorderThickness="0"
                 Foreground="#F4F4F4" CaretBrush="#F1C21B" FontSize="12" VerticalAlignment="Center"/>
      </Grid>
    </Border>

    <Border Grid.Row="2" Background="#262626" CornerRadius="8" BorderBrush="#525252"
            BorderThickness="1" Padding="1">
      <ListView x:Name="ResultList" Background="Transparent" BorderThickness="0"
                Foreground="#F4F4F4" SelectionMode="Extended"
                ItemContainerStyle="{StaticResource RowStyle}"
                ScrollViewer.HorizontalScrollBarVisibility="Auto">
        <ListView.View>
          <GridView ColumnHeaderContainerStyle="{StaticResource HeaderStyle}">
            <GridViewColumn Header="Id" Width="90" DisplayMemberBinding="{Binding id_text}"/>
            <GridViewColumn Header="Category" Width="150" DisplayMemberBinding="{Binding category}"/>
            <GridViewColumn Header="Family" Width="200" DisplayMemberBinding="{Binding family}"/>
            <GridViewColumn Header="Type" Width="200" DisplayMemberBinding="{Binding type_name}"/>
            <GridViewColumn Header="Level" Width="130" DisplayMemberBinding="{Binding level}"/>
            <GridViewColumn Header="Outside the boundary" Width="330" DisplayMemberBinding="{Binding detail}"/>
          </GridView>
        </ListView.View>
      </ListView>
    </Border>

    <Grid Grid.Row="3" Margin="0,14,0,0">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="Auto"/>
      </Grid.ColumnDefinitions>
      <TextBlock x:Name="StatusText" Grid.Column="0" Foreground="#A8A8A8" FontSize="12"
                 VerticalAlignment="Center" TextWrapping="Wrap"/>
      <StackPanel Grid.Column="1" Orientation="Horizontal">
        <Button x:Name="AllButton" Style="{StaticResource FlatButton}" Content="Select all"/>
        <Button x:Name="IsolateButton" Style="{StaticResource FlatButton}" Content="Isolate"/>
        <Button x:Name="ExportButton" Style="{StaticResource FlatButton}" Content="Export to Excel"/>
        <Button x:Name="CloseButton" Style="{StaticResource FlatButton}" Content="Close"/>
        <Button x:Name="SelectButton" Style="{StaticResource AccentButton}" Content="Select"/>
      </StackPanel>
    </Grid>
  </Grid>
</Window>
"""


def show_modal(window):
    """Block until the window closes, with Dispatcher.PushFrame."""
    frame = DispatcherFrame()

    def on_closed(sender, args):
        frame.Continue = False

    window.Closed += EventHandler(on_closed)
    window.Show()
    Dispatcher.PushFrame(frame)


def parse_positive(text):
    try:
        value = float(u"{0}".format(text).strip().replace(u",", u"."))
    except Exception:
        return None
    return value if value > 0 else None


def ask_options(boundary, boundary_text, links):
    """{'view', 'distance_m', 'boundary', 'boundary_text'} or None when cancelled.
    `boundary` is None when this model has no usable grids: then the window
    shows a link picker, and the boundary comes from the picked link."""
    window = XamlReader.Parse(OPTIONS_XAML)
    scope_model = window.FindName("ScopeModel")
    scope_view = window.FindName("ScopeView")
    margin_box = window.FindName("MarginBox")
    margin_box.Text = u"{0:g}".format(DEFAULT_DISTANCE_M)
    boundary_label = window.FindName("BoundaryText")
    link_combo = window.FindName("LinkCombo")
    error_text = window.FindName("ErrorText")
    result = [None]
    state = {"boundary": boundary, "text": boundary_text}
    boundary_label.Text = boundary_text

    def pick_scope(chosen):
        def handler(sender, args):
            scope_model.IsChecked = chosen is scope_model
            scope_view.IsChecked = chosen is scope_view
        return handler

    scope_model.Click += RoutedEventHandler(pick_scope(scope_model))
    scope_view.Click += RoutedEventHandler(pick_scope(scope_view))

    def on_link(sender, args):
        idx = link_combo.SelectedIndex
        if idx < 0:
            return
        _shown, label, inst = links[idx]
        found, count = boundary_from(inst.GetLinkDocument(), inst.GetTotalTransform())
        state["boundary"] = found
        if found is None:
            state["text"] = u""
            boundary_label.Text = u"The grids in {0} don't cross enough to outline a building. Pick " \
                                  u"another link.".format(label)
        else:
            state["text"] = describe(count, found, label)
            boundary_label.Text = state["text"]

    if boundary is None:
        window.FindName("LinkPanel").Visibility = Visibility.Visible
        labels = List[str]()
        for shown, _label, _inst in links:
            labels.Add(shown)
        link_combo.ItemsSource = labels
        link_combo.SelectionChanged += SelectionChangedEventHandler(on_link)
        link_combo.SelectedIndex = 0
        enable_combo_search(window)

    def on_check(sender, args):
        value = parse_positive(margin_box.Text)
        if value is None:
            error_text.Text = u"The distance must be a number of meters above zero."
            error_text.Visibility = Visibility.Visible
            return
        if state["boundary"] is None:
            error_text.Text = u"Pick a link whose grids outline the building."
            error_text.Visibility = Visibility.Visible
            return
        result[0] = {"view": bool(scope_view.IsChecked), "distance_m": value,
                     "boundary": state["boundary"], "boundary_text": state["text"]}
        window.Close()

    window.FindName("CheckButton").Click += RoutedEventHandler(on_check)
    window.FindName("CancelButton").Click += RoutedEventHandler(lambda s, a: window.Close())
    show_modal(window)
    return result[0]


class ResultRow(object):
    def __init__(self, data):
        self.data = data
        self.id_value = data[u"Id"]
        self.id_text = u"{0}".format(data[u"Id"])
        self.category = data[u"Category"]
        self.family = data[u"Family"]
        self.type_name = data[u"Type"]
        self.level = data[u"Level"]
        self.distance = data[u"Distance (m)"]
        self.detail = data[u"Detail"]
        self.search = u" ".join([self.id_text, self.category, self.family,
                                 self.type_name, self.level]).lower()


def show_results(rows, scope_text):
    """(action, [ResultRow]) with action 'select' / 'isolate' / 'export', or (None, [])."""
    window = XamlReader.Parse(RESULTS_XAML)
    header = window.FindName("Header")
    sub_header = window.FindName("SubHeader")
    search_box = window.FindName("SearchBox")
    search_hint = window.FindName("SearchHint")
    result_list = window.FindName("ResultList")
    status = window.FindName("StatusText")

    items = [ResultRow(r) for r in rows]
    header.Text = u"Stray elements: {0} found".format(len(items))
    sub_header.Text = scope_text
    outcome = [None, []]

    def refresh():
        term = search_box.Text.strip().lower()
        shown = [it for it in items if term in it.search] if term else list(items)
        result_list.ItemsSource = shown
        search_hint.Visibility = Visibility.Collapsed if search_box.Text else Visibility.Visible
        status.Text = u"{0} of {1} rows shown. Click rows (Ctrl / Shift for several) to act on them.".format(
            len(shown), len(items))

    def chosen_rows():
        return [r for r in result_list.SelectedItems]

    def finish(action):
        def handler(sender, args):
            picked = chosen_rows()
            if not picked:
                status.Text = u"Select one or more rows first."
                return
            outcome[0], outcome[1] = action, picked
            window.Close()
        return handler

    def on_all(sender, args):
        result_list.SelectAll()
        result_list.Focus()

    search_box.TextChanged += TextChangedEventHandler(lambda s, a: refresh())
    window.FindName("AllButton").Click += RoutedEventHandler(on_all)
    window.FindName("SelectButton").Click += RoutedEventHandler(finish("select"))
    window.FindName("IsolateButton").Click += RoutedEventHandler(finish("isolate"))
    window.FindName("ExportButton").Click += RoutedEventHandler(finish("export"))
    window.FindName("CloseButton").Click += RoutedEventHandler(lambda s, a: window.Close())
    refresh()
    show_modal(window)
    return outcome[0], outcome[1]


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------
def id_list(picked):
    ids = List[ElementId]()
    for r in picked:
        e = doc.GetElement(make_id(r.id_value))
        if e is not None:
            ids.Add(e.Id)
    return ids


def do_select(picked):
    ids = id_list(picked)
    if ids.Count == 0:
        TaskDialog.Show(TITLE, u"Those elements are not in the model any more.")
        return
    uidoc.Selection.SetElementIds(ids)
    try:
        uidoc.ShowElements(ids)
    except Exception:
        pass


def do_isolate(picked):
    ids = id_list(picked)
    if ids.Count == 0:
        TaskDialog.Show(TITLE, u"Those elements are not in the model any more.")
        return
    view = uidoc.ActiveView
    t = Transaction(doc, u"Stray elements: isolate")
    t.Start()
    try:
        view.IsolateElementsTemporary(ids)
        t.Commit()
    except Exception as ex:
        t.RollBack()
        TaskDialog.Show(TITLE, u"Could not isolate them in the view '{0}':\n{1}".format(
            elem_name(view), ex))


def do_export(picked):
    path = ask_save_path(u"{0} - Stray elements.xlsx".format(model_name()))
    if not path:
        return
    table = [list(COLUMNS)]
    for r in picked:
        table.append([r.id_value, r.category, r.family, r.type_name, r.level, r.distance, r.detail])
    try:
        File.WriteAllBytes(path, build_xlsx(u"Stray elements", table))
    except Exception as ex:
        TaskDialog.Show(TITLE, u"Could not save the file (is it open in Excel?):\n{0}".format(ex))
        return
    open_file(path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    if doc.IsFamilyDocument:
        TaskDialog.Show(TITLE, u"Find Stray Elements works in a project. Open a project model.")
        return
    boundary, grid_count = boundary_from(doc)
    links = []
    boundary_text = u""
    if boundary is None:
        links = links_with_grids()
        if not links:
            TaskDialog.Show(TITLE, u"The building boundary comes from the grids. This model has no grids "
                                   u"that outline the building, and no loaded link has grids either. Add or "
                                   u"load the grids and run it again.")
            return
    else:
        boundary_text = describe(grid_count, boundary)
    options = ask_options(boundary, boundary_text, links)
    if options is None:
        return
    boundary, boundary_text = options["boundary"], options["boundary_text"]
    view = uidoc.ActiveView if options["view"] else None
    try:
        rows = find(boundary, options["distance_m"], view)
    except Exception:
        TaskDialog.Show(TITLE, u"The check failed:\n\n{0}".format(traceback.format_exc()))
        return
    if not rows:
        TaskDialog.Show(TITLE, u"No elements more than {0:g} m outside the building boundary.".format(
            options["distance_m"]))
        return
    scope = u"Active view: {0}".format(elem_name(view)) if view is not None else u"Whole model"
    scope_text = u"{0}  |  more than {1:g} m outside the boundary  |  {2}".format(
        scope, options["distance_m"], boundary_text)
    action, picked = show_results(rows, scope_text)
    if action == "select":
        do_select(picked)
    elif action == "isolate":
        do_isolate(picked)
    elif action == "export":
        do_export(picked)


main()

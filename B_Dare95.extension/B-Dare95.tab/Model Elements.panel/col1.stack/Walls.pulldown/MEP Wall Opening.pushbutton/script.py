# -*- coding: utf-8 -*-
"""MEP Wall Openings.

Finds clashes between MEP curves (Pipes, Ducts, Cable Trays) and Basic Walls in
the active document, then cuts a rectangular opening in the wall for each one.

MEP elements are read from the active document AND every loaded Revit link.
Walls are only ever modified in the active document.

Openings are created with Document.Create.NewOpening(wall, p1, p2), which hosts
a rectangular Opening element on the wall. The wall's profile sketch is never
opened. SketchEditScope was tried first and abandoned: on walls whose sketch
state is inconsistent, Wall.SketchId returns invalidElementId while
StartWithNewSketch() reports that a sketch already exists, leaving no usable
way in. NewOpening has no such entry condition and works on 2020-2027.

Trade-off worth knowing: an Opening is a separate element hosted by the wall,
not a modification of the wall's own profile. That makes the results
schedulable, selectable and deletable in bulk, but it also means they can be
moved independently of the MEP that justified them.

IronPython 2.7 / Revit 2024-2027.
"""

__title__ = "MEP Wall\nOpenings"
__author__ = "Mohamed Bedair"
__doc__ = ("Creates rectangular openings in Basic Walls where Pipes / Ducts / "
           "Cable Trays clash with them, in the host model and in links.")

# The window is modeless, so it outlives this script run. The engine has to
# survive with it, and the window/handler/event are parked in envvars so a
# fresh module scope on the next button press finds the live session instead
# of building a second window.
__persistentengine__ = True

import math

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")
clr.AddReference("System.Xml")

from Autodesk.Revit.DB import (
    BuiltInFailures, BuiltInParameter, Element, FailureProcessingResult,
    FailureSeverity, FilteredElementCollector, IFailuresPreprocessor, Line,
    LocationCurve, RevitLinkInstance, Transaction, TransactionGroup,
    TransactionStatus, Transform, Wall, WallKind, WallType, XYZ,
)
from Autodesk.Revit.DB.Electrical import CableTray
from Autodesk.Revit.DB.Mechanical import Duct
from Autodesk.Revit.DB.Plumbing import Pipe
from Autodesk.Revit.UI import (
    ExternalEvent, IExternalEventHandler, TaskDialog, TaskDialogCommonButtons,
    TaskDialogResult,
)

try:
    from pyrevit.coreutils import envvars
except Exception:
    envvars = None

from System import Action, AppDomain, EventHandler
from System.Windows import RoutedEventHandler, Visibility
from System.Windows.Controls import CheckBox, TextChangedEventHandler
from System.Windows.Markup import XamlReader
from System.Windows.Threading import Dispatcher, DispatcherFrame, DispatcherPriority

doc = __revit__.ActiveUIDocument.Document          # noqa: F821

# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

MM = 1.0 / 304.8                 # millimetres -> internal feet
GRID_CELL = 20.0                 # spatial hash cell size, feet
PARALLEL_TOL = 0.05              # |dir . wallNormal| below this = runs parallel
MERGE_GAP = 5.0 * MM             # openings closer than this get merged
MIN_EDGE = 1.6 * MM              # below Revit's short-curve tolerance -> reject
FACE_TOL = 1.0 * MM              # slack when testing full penetration
FACE_PAD = 1.0 * MM              # tiny overshoot past each wall face
CIRCLE_SEGMENTS = 12             # sampling resolution for round sections

KIND_PIPE = "PIPE"
KIND_DUCT = "DUCT"
KIND_TRAY = "TRAY"

MEP_CLASSES = ((Pipe, KIND_PIPE), (Duct, KIND_DUCT), (CableTray, KIND_TRAY))

# BuiltInParameter names differ slightly across releases -- resolve defensively.
# The "group changed outside edit mode" warning is raised for every wall that
# sits in a single-instance model group. It is benign, but it is still a
# warning, so it is only ignored when the user opts in.
BENIGN_GROUP_FAILURES = []
_group_failures = getattr(BuiltInFailures, "GroupFailures", None)
if _group_failures is not None:
    for _name in ("AtomViolationWhenOnePlaceInstance",):
        _fid = getattr(_group_failures, _name, None)
        if _fid is not None:
            BENIGN_GROUP_FAILURES.append(_fid)

_BIP_WALL_KEY_REF = getattr(BuiltInParameter, "WALL_KEY_REF_PARAM", None)
_BIP_PIPE_OD = getattr(BuiltInParameter, "RBS_PIPE_OUTER_DIAMETER", None)
_BIP_PIPE_DIA = getattr(BuiltInParameter, "RBS_PIPE_DIAMETER_PARAM", None)
_BIP_CURVE_DIA = getattr(BuiltInParameter, "RBS_CURVE_DIAMETER_PARAM", None)
_BIP_CURVE_W = getattr(BuiltInParameter, "RBS_CURVE_WIDTH_PARAM", None)
_BIP_CURVE_H = getattr(BuiltInParameter, "RBS_CURVE_HEIGHT_PARAM", None)


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def eid_value(element_id):
    """ElementId -> int, Revit 2025+ safe."""
    try:
        return element_id.Value
    except AttributeError:
        return element_id.IntegerValue


def clean_text(value):
    """Revit failure texts are multi-line; flatten them for the report."""
    text = u"{0}".format(value)
    for token in ("\r\n", "\n", "\r", "\t"):
        text = text.replace(token, " ")
    while "  " in text:
        text = text.replace("  ", " ")
    return text.strip()


def element_name(element):
    """Element.Name is shadowed on derived types and can raise in IronPython."""
    try:
        return element.Name
    except Exception:
        pass
    try:
        return Element.Name.GetValue(element)
    except Exception:
        pass
    for bip_name in ("SYMBOL_NAME_PARAM", "ALL_MODEL_TYPE_NAME",
                     "ELEM_TYPE_PARAM", "DATUM_TEXT"):
        bip = getattr(BuiltInParameter, bip_name, None)
        if bip is None:
            continue
        try:
            prm = element.get_Parameter(bip)
        except Exception:
            continue
        if prm is not None and prm.HasValue:
            try:
                text = prm.AsString()
            except Exception:
                text = None
            if text:
                return text
    return "Type {0}".format(eid_value(element.Id))


def param_length(element, bip):
    if bip is None:
        return None
    try:
        prm = element.get_Parameter(bip)
    except Exception:
        return None
    if prm is None or not prm.HasValue:
        return None
    try:
        val = prm.AsDouble()
    except Exception:
        return None
    return val if val > 1e-9 else None


def to_mm(feet):
    return feet * 304.8


# ---------------------------------------------------------------------------
# MEP geometry
# ---------------------------------------------------------------------------

def mep_section(element, kind):
    """Cross-section of an MEP curve.

    Returns ("round", radius) or ("rect", width, height) in feet, or None.
    """
    width = height = None
    try:
        width = element.Width
    except Exception:
        width = None
    try:
        height = element.Height
    except Exception:
        height = None

    if kind == KIND_PIPE:
        # "Full diameter" for pipes -> outside diameter first, nominal second.
        dia = param_length(element, _BIP_PIPE_OD)
        if dia is None:
            dia = param_length(element, _BIP_PIPE_DIA)
        if dia is None:
            try:
                dia = element.Diameter if element.Diameter > 1e-9 else None
            except Exception:
                dia = None
        if dia is not None:
            return ("round", dia / 2.0)
        return None

    # Ducts and cable trays -> Width / Height parameters.
    if width is None:
        width = param_length(element, _BIP_CURVE_W)
    if height is None:
        height = param_length(element, _BIP_CURVE_H)
    if width and height and width > 1e-9 and height > 1e-9:
        return ("rect", width, height)

    if kind == KIND_DUCT:
        dia = param_length(element, _BIP_CURVE_DIA)
        if dia is None:
            try:
                dia = element.Diameter if element.Diameter > 1e-9 else None
            except Exception:
                dia = None
        if dia is not None:
            return ("round", dia / 2.0)
    return None


def connector_axes(element, transform):
    """Profile axes taken from the first connector, in host coordinates."""
    try:
        manager = element.ConnectorManager
        if manager is None:
            return None
        for connector in manager.Connectors:
            csys = connector.CoordinateSystem
            if csys is None:
                continue
            axis_x = transform.OfVector(csys.BasisX)
            axis_y = transform.OfVector(csys.BasisY)
            axis_z = transform.OfVector(csys.BasisZ)
            if axis_x.GetLength() < 1e-9 or axis_y.GetLength() < 1e-9:
                continue
            return (axis_x.Normalize(), axis_y.Normalize(), axis_z.Normalize())
    except Exception:
        pass
    return None


def profile_axes(direction, conn_axes):
    """Two unit vectors spanning the cross-section: (width axis, height axis)."""
    axis_a = axis_b = None
    if conn_axes is not None:
        cx, cy, cz = conn_axes
        if abs(cz.DotProduct(direction)) > 0.99:   # connector aligns with the run
            axis_a, axis_b = cx, cy

    if axis_a is None:
        horizontal = XYZ.BasisZ.CrossProduct(direction)
        if horizontal.GetLength() < 1e-6:          # vertical run
            axis_a, axis_b = XYZ.BasisX, XYZ.BasisY
        else:
            axis_a = horizontal.Normalize()
            axis_b = direction.CrossProduct(axis_a).Normalize()

    # The more vertical of the two carries the Height dimension.
    if abs(axis_b.DotProduct(XYZ.BasisZ)) >= abs(axis_a.DotProduct(XYZ.BasisZ)):
        return axis_a, axis_b
    return axis_b, axis_a


def section_offsets(section, axis_w, axis_h):
    """Points on the section outline, as vectors from the centre."""
    points = []
    if section[0] == "round":
        radius = section[1]
        for i in range(CIRCLE_SEGMENTS):
            ang = 2.0 * math.pi * i / CIRCLE_SEGMENTS
            points.append(axis_w.Multiply(radius * math.cos(ang))
                          .Add(axis_h.Multiply(radius * math.sin(ang))))
    else:
        half_w = section[1] / 2.0
        half_h = section[2] / 2.0
        for sw in (-half_w, half_w):
            for sh in (-half_h, half_h):
                points.append(axis_w.Multiply(sw).Add(axis_h.Multiply(sh)))
    return points


# ---------------------------------------------------------------------------
# wall geometry
# ---------------------------------------------------------------------------

def wall_face_offsets(wall, thickness):
    """Distance from the wall's location line to (exterior face, interior face).

    A wall's LocationCurve sits on its Location Line, which is only the
    centreline by default. When it is set to a finish or core face, the real
    faces are offset from the curve and a plain +/- thickness/2 band is wrong
    by up to half the wall.
    """
    half = thickness / 2.0
    mode = 0
    if _BIP_WALL_KEY_REF is not None:
        try:
            prm = wall.get_Parameter(_BIP_WALL_KEY_REF)
            if prm is not None and prm.HasValue:
                mode = prm.AsInteger()
        except Exception:
            mode = 0

    if mode == 0:                       # Wall Centerline
        return half, half
    if mode == 2:                       # Finish Face: Exterior
        return 0.0, thickness
    if mode == 3:                       # Finish Face: Interior
        return thickness, 0.0

    # The remaining modes are relative to the core, so the compound structure
    # has to be read. Layers run exterior -> interior.
    try:
        structure = doc.GetElement(wall.GetTypeId()).GetCompoundStructure()
        if structure is None:
            return half, half
        first_core = structure.GetFirstCoreLayerIndex()
        last_core = structure.GetLastCoreLayerIndex()
        exterior_finish = 0.0
        for i in range(first_core):
            exterior_finish += structure.GetLayerWidth(i)
        core = 0.0
        for i in range(first_core, last_core + 1):
            core += structure.GetLayerWidth(i)
    except Exception:
        return half, half

    if mode == 1:                       # Core Centerline
        to_exterior = exterior_finish + core / 2.0
    elif mode == 4:                     # Core Face: Exterior
        to_exterior = exterior_finish
    elif mode == 5:                     # Core Face: Interior
        to_exterior = exterior_finish + core
    else:
        return half, half

    return to_exterior, thickness - to_exterior


def wall_info(wall):
    """Cache the planar frame of a straight wall, or None if unusable."""
    location = wall.Location
    if not isinstance(location, LocationCurve):
        return None
    curve = location.Curve
    if not isinstance(curve, Line):
        return None

    start = curve.GetEndPoint(0)
    end = curve.GetEndPoint(1)
    axis = end.Subtract(start)
    length = axis.GetLength()
    if length < 1e-6:
        return None
    axis = axis.Normalize()

    normal = axis.CrossProduct(XYZ.BasisZ)
    if normal.GetLength() < 1e-6:
        return None
    normal = normal.Normalize()

    bbox = wall.get_BoundingBox(None)
    if bbox is None:
        return None

    try:
        thickness = wall.Width
    except Exception:
        thickness = 1.0

    # Face positions measured along `normal`, relative to the location line.
    to_exterior, to_interior = wall_face_offsets(wall, thickness)
    try:
        outward = wall.Orientation
        sign = 1.0 if outward.DotProduct(normal) >= 0.0 else -1.0
    except Exception:
        sign = 1.0
    face_a = sign * to_exterior
    face_b = -sign * to_interior

    return {
        "id": wall.Id,
        "p0": start,
        "u": axis,
        "n": normal,
        "len": length,
        "thick": thickness,
        "face_min": min(face_a, face_b),
        "face_max": max(face_a, face_b),
        "zmin": bbox.Min.Z,
        "zmax": bbox.Max.Z,
        "bmin": bbox.Min,
        "bmax": bbox.Max,
        "type_name": "",
    }


def embedded_in_wall(info, mep_start, mep_end, reach):
    """True when a near-parallel run actually sits inside the wall body."""
    low = info["face_min"] - reach
    high = info["face_max"] + reach
    d0 = mep_start.Subtract(info["p0"]).DotProduct(info["n"])
    d1 = mep_end.Subtract(info["p0"]).DotProduct(info["n"])
    if max(d0, d1) < low or min(d0, d1) > high:
        return False
    a0 = mep_start.Subtract(info["p0"]).DotProduct(info["u"])
    a1 = mep_end.Subtract(info["p0"]).DotProduct(info["u"])
    if max(a0, a1) < 0.0 or min(a0, a1) > info["len"]:
        return False
    if max(mep_start.Z, mep_end.Z) < info["zmin"]:
        return False
    if min(mep_start.Z, mep_end.Z) > info["zmax"]:
        return False
    return True


def compute_opening(info, mep_start, mep_end, direction, run_length, section,
                    conn_axes, offset, reach):
    """Opening rectangle in wall-local coords, or (None, reason).

    A clash only counts when the run passes completely through the wall -
    entering one face and leaving the other. An element that stops inside the
    wall is reported as a reason, not turned into an opening.

    A reason is only returned for a genuine clash the tool cannot resolve;
    plain near-misses come back as (None, None).
    """
    denom = direction.DotProduct(info["n"])
    if abs(denom) < PARALLEL_TOL:
        if embedded_in_wall(info, mep_start, mep_end, reach):
            return None, "runs parallel to / inside the wall"
        return None, None

    # Parameters along the run where the centreline meets each wall face.
    base = mep_start.Subtract(info["p0"]).DotProduct(info["n"])
    s_first = (info["face_min"] - base) / denom
    s_second = (info["face_max"] - base) / denom
    s_enter = min(s_first, s_second)
    s_exit = max(s_first, s_second)

    if s_exit <= FACE_TOL or s_enter >= run_length - FACE_TOL:
        return None, None                      # the run never reaches the wall

    if s_enter < -FACE_TOL or s_exit > run_length + FACE_TOL:
        # It overlaps the wall body but at least one end stops inside it.
        return None, "stops inside the wall (no full penetration)"

    point_enter = mep_start.Add(direction.Multiply(s_enter))
    point_exit = mep_start.Add(direction.Multiply(s_exit))
    midpoint = point_enter.Add(point_exit).Multiply(0.5)

    along = midpoint.Subtract(info["p0"]).DotProduct(info["u"])
    if along < -1e-6 or along > info["len"] + 1e-6:
        return None, None
    if midpoint.Z < info["zmin"] - 1e-6 or midpoint.Z > info["zmax"] + 1e-6:
        return None, None

    axis_w, axis_h = profile_axes(direction, conn_axes)

    # The footprint is the section swept between the two faces, projected onto
    # the wall plane. Sweeping between the real crossing points rather than a
    # fixed distance either side of the centre keeps this correct for angled
    # runs and for off-centre location lines alike.
    pad = direction.Multiply(FACE_PAD)
    ends = (point_enter.Subtract(pad), point_exit.Add(pad))

    xs = []
    zs = []
    for vec in section_offsets(section, axis_w, axis_h):
        for end_point in ends:
            corner = end_point.Add(vec)
            xs.append(corner.Subtract(info["p0"]).DotProduct(info["u"]))
            zs.append(corner.Z)

    rect = (min(xs) - offset, max(xs) + offset,
            min(zs) - offset, max(zs) + offset)
    return rect, None


def merge_rects(rects, gap):
    """Union overlapping / near-touching rectangles so loops never intersect."""
    items = list(rects)
    changed = True
    while changed:
        changed = False
        merged = []
        for rect in items:
            hit = False
            for i in range(len(merged)):
                other = merged[i]
                if (rect[0] <= other[1] + gap and other[0] <= rect[1] + gap and
                        rect[2] <= other[3] + gap and other[2] <= rect[3] + gap):
                    merged[i] = (min(rect[0], other[0]), max(rect[1], other[1]),
                                 min(rect[2], other[2]), max(rect[3], other[3]))
                    hit = True
                    changed = True
                    break
            if not hit:
                merged.append(rect)
        items = merged
    return items


# ---------------------------------------------------------------------------
# failure handling
# ---------------------------------------------------------------------------

def is_benign_group_warning(message):
    if not BENIGN_GROUP_FAILURES:
        return False
    try:
        if message.GetSeverity() != FailureSeverity.Warning:
            return False
        found = message.GetFailureDefinitionId()
    except Exception:
        return False
    for known in BENIGN_GROUP_FAILURES:
        try:
            if found.Guid == known.Guid:
                return True
        except Exception:
            continue
    return False


class SkipWallOnFailure(IFailuresPreprocessor):
    """Any warning or error rolls the wall back and records the text."""

    def __init__(self, allow_group_warning=False):
        self.messages = []
        self.dismissed = []
        self.allow_group_warning = allow_group_warning

    def PreprocessFailures(self, accessor):
        found = accessor.GetFailureMessages()
        if found.Count == 0:
            return FailureProcessingResult.Continue

        blocking = False
        for message in found:
            if self.allow_group_warning and is_benign_group_warning(message):
                try:
                    accessor.DeleteWarning(message)
                    self.dismissed.append("group warning")
                    continue
                except Exception:
                    pass
            try:
                self.messages.append(clean_text(message.GetDescriptionText()))
            except Exception:
                self.messages.append("unspecified failure")
            blocking = True

        if blocking:
            return FailureProcessingResult.ProceedWithRollBack
        return FailureProcessingResult.Continue


# ---------------------------------------------------------------------------
# scan
# ---------------------------------------------------------------------------

def collect_documents():
    """(document, transform, label) for the host plus every loaded link."""
    entries = [(doc, Transform.Identity, "Host")]
    for link in FilteredElementCollector(doc).OfClass(RevitLinkInstance):
        link_doc = link.GetLinkDocument()
        if link_doc is None:
            continue
        entries.append((link_doc, link.GetTotalTransform(), link_doc.Title))
    return entries


def collect_basic_wall_types():
    """{type_id_int: (WallType, [Wall, ...])} for Basic wall kinds only."""
    buckets = {}
    walls = (FilteredElementCollector(doc)
             .OfClass(Wall)
             .WhereElementIsNotElementType()
             .ToElements())
    for wall in walls:
        try:
            if wall.IsStackedWall or wall.IsStackedWallMember:
                continue
        except Exception:
            pass
        wall_type = doc.GetElement(wall.GetTypeId())
        if not isinstance(wall_type, WallType):
            continue
        try:
            if wall_type.Kind != WallKind.Basic:
                continue
        except Exception:
            continue
        key = eid_value(wall_type.Id)
        if key not in buckets:
            buckets[key] = (wall_type, [])
        buckets[key][1].append(wall)
    return buckets


def build_grid(infos):
    grid = {}
    for key, info in infos.items():
        i0 = int(math.floor(info["bmin"].X / GRID_CELL))
        i1 = int(math.floor(info["bmax"].X / GRID_CELL))
        j0 = int(math.floor(info["bmin"].Y / GRID_CELL))
        j1 = int(math.floor(info["bmax"].Y / GRID_CELL))
        for i in range(i0, i1 + 1):
            for j in range(j0, j1 + 1):
                grid.setdefault((i, j), []).append(key)
    return grid


def scan_clashes(target_walls, offsets):
    """Returns (per_wall_openings, stats)."""
    infos = {}
    for wall, type_name in target_walls:
        # The window is modeless, so the cached wall list can contain elements
        # the user deleted while it was open.
        try:
            if not wall.IsValidObject:
                continue
            info = wall_info(wall)
        except Exception:
            continue
        if info is None:
            continue
        info["type_name"] = type_name
        infos[eid_value(wall.Id)] = info

    grid = build_grid(infos)
    per_wall = {}
    stats = {"clashes": 0, "unusable": 0, "no_size": 0, "reasons": {}}

    for source_doc, transform, label in collect_documents():
        for mep_class, kind in MEP_CLASSES:
            offset = offsets[kind]
            try:
                elements = (FilteredElementCollector(source_doc)
                            .OfClass(mep_class)
                            .WhereElementIsNotElementType()
                            .ToElements())
            except Exception:
                continue

            for element in elements:
                location = element.Location
                if not isinstance(location, LocationCurve):
                    continue
                curve = location.Curve
                if not isinstance(curve, Line):
                    continue

                section = mep_section(element, kind)
                if section is None:
                    stats["no_size"] += 1
                    continue

                start = transform.OfPoint(curve.GetEndPoint(0))
                end = transform.OfPoint(curve.GetEndPoint(1))
                span = end.Subtract(start)
                run_length = span.GetLength()
                if run_length < 1e-6:
                    continue
                direction = span.Normalize()

                if section[0] == "round":
                    reach = section[1] + offset
                else:
                    reach = max(section[1], section[2]) / 2.0 + offset

                min_x = min(start.X, end.X) - reach
                max_x = max(start.X, end.X) + reach
                min_y = min(start.Y, end.Y) - reach
                max_y = max(start.Y, end.Y) + reach
                min_z = min(start.Z, end.Z) - reach
                max_z = max(start.Z, end.Z) + reach

                conn_axes = connector_axes(element, transform)

                candidates = set()
                i0 = int(math.floor(min_x / GRID_CELL))
                i1 = int(math.floor(max_x / GRID_CELL))
                j0 = int(math.floor(min_y / GRID_CELL))
                j1 = int(math.floor(max_y / GRID_CELL))
                for i in range(i0, i1 + 1):
                    for j in range(j0, j1 + 1):
                        for key in grid.get((i, j), ()):
                            candidates.add(key)

                for key in candidates:
                    info = infos[key]
                    if (info["bmax"].X < min_x or info["bmin"].X > max_x or
                            info["bmax"].Y < min_y or info["bmin"].Y > max_y or
                            info["bmax"].Z < min_z or info["bmin"].Z > max_z):
                        continue

                    rect, reason = compute_opening(
                        info, start, end, direction, run_length, section,
                        conn_axes, offset, reach)
                    if rect is None:
                        if reason:
                            stats["clashes"] += 1
                            stats["reasons"][reason] = stats["reasons"].get(reason, 0) + 1
                        continue

                    stats["clashes"] += 1
                    record = per_wall.setdefault(key, {"info": info, "items": []})
                    record["items"].append({
                        "rect": rect,
                        "kind": kind,
                        "source": label,
                        "eid": eid_value(element.Id),
                    })

    return per_wall, stats


# ---------------------------------------------------------------------------
# execution
# ---------------------------------------------------------------------------

def local_to_world(info, along, elevation):
    """Wall-local (distance along, absolute Z) -> world point on the wall plane."""
    return (info["p0"]
            .Add(info["u"].Multiply(along))
            .Add(XYZ.BasisZ.Multiply(elevation - info["p0"].Z)))


def rect_overlaps_wall(info, rect):
    """True when the opening rectangle actually lands on the wall."""
    if rect[1] <= 0.0 or rect[0] >= info["len"]:
        return False
    if rect[3] <= info["zmin"] or rect[2] >= info["zmax"]:
        return False
    return True


def edit_wall(wall_id, info, rects, allow_group_warning):
    """Cut the openings into one wall.

    Returns ('ok', (n, rejected)) / ('skip', reason) / ('warn', reason).

    Openings are created with Document.Create.NewOpening(wall, p1, p2), which
    places a hosted rectangular Opening element. The wall's own profile sketch
    is never opened, so none of the SketchEditScope entry conditions apply.
    """
    wall = doc.GetElement(wall_id)
    if wall is None:
        return ("skip", "wall no longer exists")

    try:
        if wall.IsStackedWall or wall.IsStackedWallMember:
            return ("skip", "stacked walls do not support rectangular openings")
    except Exception:
        pass

    try:
        if wall.CurtainGrid is not None:
            return ("skip", "curtain walls do not support rectangular openings")
    except Exception:
        pass

    preprocessor = SkipWallOnFailure(allow_group_warning)

    transaction = Transaction(doc, "Create MEP wall openings")
    options = transaction.GetFailureHandlingOptions()
    options.SetFailuresPreprocessor(preprocessor)
    options.SetClearAfterRollback(True)
    transaction.SetFailureHandlingOptions(options)
    transaction.Start()

    created = 0
    rejected = []

    try:
        for rect in rects:
            if (rect[1] - rect[0]) < MIN_EDGE or (rect[3] - rect[2]) < MIN_EDGE:
                rejected.append("opening smaller than Revit's curve tolerance")
                continue
            if not rect_overlaps_wall(info, rect):
                rejected.append("opening falls outside the wall extents")
                continue

            corner_a = local_to_world(info, rect[0], rect[2])
            corner_b = local_to_world(info, rect[1], rect[3])

            try:
                opening = doc.Create.NewOpening(wall, corner_a, corner_b)
            except Exception as err:
                rejected.append(clean_text(err))
                continue

            if opening is None:
                rejected.append("NewOpening returned nothing")
                continue
            created += 1

        if created == 0:
            transaction.RollBack()
            reason = rejected[0] if rejected else "no valid opening produced"
            return ("skip", reason)

        transaction.Commit()

    except Exception as err:
        try:
            if transaction.GetStatus() == TransactionStatus.Started:
                transaction.RollBack()
        except Exception:
            pass
        return ("skip", "opening creation failed ({0})".format(clean_text(err)))

    if preprocessor.messages or transaction.GetStatus() == TransactionStatus.RolledBack:
        note = preprocessor.messages[0] if preprocessor.messages else "warning raised"
        return ("warn", note)

    return ("ok", (created, rejected))


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="MEP Wall Openings" Height="720" Width="1040"
        WindowStartupLocation="CenterScreen" Background="#1E1E2E"
        FontFamily="Segoe UI" ResizeMode="CanResize">
  <Window.Resources>

    <Style x:Key="H1" TargetType="TextBlock">
      <Setter Property="Foreground" Value="#CDD6F4"/>
      <Setter Property="FontSize" Value="18"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
    </Style>
    <Style x:Key="Lbl" TargetType="TextBlock">
      <Setter Property="Foreground" Value="#CDD6F4"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
      <Setter Property="Margin" Value="0,0,0,4"/>
    </Style>
    <Style x:Key="Sub" TargetType="TextBlock">
      <Setter Property="Foreground" Value="#A6ADC8"/>
      <Setter Property="FontSize" Value="11"/>
      <Setter Property="TextWrapping" Value="Wrap"/>
    </Style>

    <Style TargetType="TextBox">
      <Setter Property="Background" Value="#313244"/>
      <Setter Property="Foreground" Value="#CDD6F4"/>
      <Setter Property="BorderBrush" Value="#45475A"/>
      <Setter Property="BorderThickness" Value="1"/>
      <Setter Property="Padding" Value="6,4"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="CaretBrush" Value="#F0A500"/>
      <Setter Property="SelectionBrush" Value="#F0A500"/>
    </Style>

    <Style TargetType="CheckBox">
      <Setter Property="Foreground" Value="#CDD6F4"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="Margin" Value="4,3,4,3"/>
    </Style>

    <Style x:Key="BtnBase" TargetType="Button">
      <Setter Property="Height" Value="32"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="bd" CornerRadius="6" Padding="14,0"
                    Background="{TemplateBinding Background}">
              <ContentPresenter HorizontalAlignment="Center"
                                VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="bd" Property="Opacity" Value="0.85"/>
              </Trigger>
              <Trigger Property="IsEnabled" Value="False">
                <Setter TargetName="bd" Property="Opacity" Value="0.30"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="Accent" TargetType="Button" BasedOn="{StaticResource BtnBase}">
      <Setter Property="Background" Value="#F0A500"/>
      <Setter Property="Foreground" Value="#1E1E2E"/>
    </Style>
    <Style x:Key="Ghost" TargetType="Button" BasedOn="{StaticResource BtnBase}">
      <Setter Property="Background" Value="#45475A"/>
      <Setter Property="Foreground" Value="#CDD6F4"/>
    </Style>
    <Style x:Key="Mini" TargetType="Button" BasedOn="{StaticResource BtnBase}">
      <Setter Property="Background" Value="#313244"/>
      <Setter Property="Foreground" Value="#A6ADC8"/>
      <Setter Property="Height" Value="24"/>
      <Setter Property="FontSize" Value="11"/>
    </Style>

  </Window.Resources>

  <Grid Margin="16">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>
    <Grid.ColumnDefinitions>
      <ColumnDefinition Width="360"/>
      <ColumnDefinition Width="16"/>
      <ColumnDefinition Width="*"/>
    </Grid.ColumnDefinitions>

    <StackPanel Grid.Row="0" Grid.ColumnSpan="3" Margin="0,0,0,12">
      <TextBlock Style="{StaticResource H1}" Text="MEP Wall Openings"/>
      <TextBlock Style="{StaticResource Sub}" Margin="0,3,0,0"
                 Text="Cuts a hosted rectangular opening into a Basic Wall wherever a Pipe, Duct or Cable Tray (host model or link) passes through it."/>
    </StackPanel>

    <Border Grid.Row="1" Grid.Column="0" Background="#2A2A3C"
            BorderBrush="#45475A" BorderThickness="1" CornerRadius="8"
            Padding="12">
      <Grid>
        <Grid.RowDefinitions>
          <RowDefinition Height="Auto"/>
          <RowDefinition Height="Auto"/>
          <RowDefinition Height="*"/>
          <RowDefinition Height="Auto"/>
          <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <StackPanel Grid.Row="0">
          <TextBlock Style="{StaticResource Lbl}" Text="1 - Wall types"/>
          <TextBlock x:Name="TypeCount" Style="{StaticResource Sub}"
                     Margin="0,0,0,6" Text=""/>
          <TextBox x:Name="Search" Margin="0,0,0,6"/>
        </StackPanel>

        <StackPanel Grid.Row="1" Orientation="Horizontal" Margin="0,0,0,6">
          <Button x:Name="SelectAll" Style="{StaticResource Mini}"
                  Content="Select all" Margin="0,0,6,0"/>
          <Button x:Name="SelectNone" Style="{StaticResource Mini}"
                  Content="Clear"/>
        </StackPanel>

        <Border Grid.Row="2" Background="#1E1E2E" BorderBrush="#45475A"
                BorderThickness="1" CornerRadius="6">
          <ScrollViewer VerticalScrollBarVisibility="Auto" Padding="6">
            <StackPanel x:Name="TypeList"/>
          </ScrollViewer>
        </Border>

        <StackPanel Grid.Row="3" Margin="0,12,0,0">
          <TextBlock Style="{StaticResource Lbl}" Text="2 - Clearance offset (mm)"/>
          <TextBlock Style="{StaticResource Sub}" Margin="0,0,0,8"
                     Text="Added to every side of the element footprint."/>
          <Grid>
            <Grid.ColumnDefinitions>
              <ColumnDefinition Width="*"/>
              <ColumnDefinition Width="8"/>
              <ColumnDefinition Width="*"/>
              <ColumnDefinition Width="8"/>
              <ColumnDefinition Width="*"/>
            </Grid.ColumnDefinitions>
            <StackPanel Grid.Column="0">
              <TextBlock Style="{StaticResource Sub}" Text="Pipes"/>
              <TextBox x:Name="OffPipe" Text="25" Margin="0,3,0,0"/>
            </StackPanel>
            <StackPanel Grid.Column="2">
              <TextBlock Style="{StaticResource Sub}" Text="Ducts"/>
              <TextBox x:Name="OffDuct" Text="50" Margin="0,3,0,0"/>
            </StackPanel>
            <StackPanel Grid.Column="4">
              <TextBlock Style="{StaticResource Sub}" Text="Cable trays"/>
              <TextBox x:Name="OffTray" Text="50" Margin="0,3,0,0"/>
            </StackPanel>
          </Grid>
          <CheckBox x:Name="AllowGroups" Margin="0,12,0,0"
                    Content="Allow walls in single-instance groups"/>
          <TextBlock Style="{StaticResource Sub}" Margin="24,2,0,0"
                     Text="Dismisses only the benign 'group changed outside edit mode' warning. Every other warning still skips the wall."/>
        </StackPanel>

        <StackPanel Grid.Row="4" Margin="0,14,0,0">
          <Button x:Name="Scan" Style="{StaticResource Accent}"
                  Content="Find clashes"/>
          <Button x:Name="Run" Style="{StaticResource Ghost}"
                  Content="Create openings" Margin="0,8,0,0" IsEnabled="False"/>
        </StackPanel>
      </Grid>
    </Border>

    <Border Grid.Row="1" Grid.Column="2" Background="#2A2A3C"
            BorderBrush="#45475A" BorderThickness="1" CornerRadius="8"
            Padding="12">
      <Grid>
        <Grid.RowDefinitions>
          <RowDefinition Height="Auto"/>
          <RowDefinition Height="*"/>
          <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>
        <TextBlock Grid.Row="0" Style="{StaticResource Lbl}" Text="Report"/>
        <TextBox Grid.Row="1" x:Name="Report" IsReadOnly="True"
                 FontFamily="Consolas" FontSize="11" Background="#1E1E2E"
                 TextWrapping="NoWrap" VerticalScrollBarVisibility="Auto"
                 HorizontalScrollBarVisibility="Auto"/>
        <ProgressBar Grid.Row="2" x:Name="Progress" Height="4" Margin="0,10,0,0"
                     Background="#313244" Foreground="#F0A500"
                     BorderThickness="0" Minimum="0" Maximum="100" Value="0"/>
      </Grid>
    </Border>

    <Grid Grid.Row="2" Grid.ColumnSpan="3" Margin="0,12,0,0">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="Auto"/>
      </Grid.ColumnDefinitions>
      <TextBlock x:Name="Status" Grid.Column="0" Style="{StaticResource Sub}"
                 VerticalAlignment="Center" Text="Pick the wall types to process."/>
      <StackPanel Grid.Column="1" Orientation="Horizontal">
        <Button x:Name="CopyReport" Style="{StaticResource Ghost}"
                Content="Copy report" Margin="0,0,8,0"/>
        <Button x:Name="Close" Style="{StaticResource Ghost}" Content="Close"/>
      </StackPanel>
    </Grid>
  </Grid>
</Window>
"""


ENV_SESSION = "MEP_WALL_OPENINGS_SESSION"


def _envvars_call(names, args):
    """Call the first function in `names` that this pyRevit build exposes.

    pyrevit.coreutils.envvars has used more than one spelling for its getter
    and setter across versions, so the name is resolved at runtime instead of
    being hard-coded.
    """
    for name in names:
        function = getattr(envvars, name, None)
        if function is None:
            continue
        try:
            return True, function(*args)
        except Exception:
            continue
    return False, None


def session_get():
    handled, value = _envvars_call(
        ("get_pyrevit_env_var", "get_pyrevit_env"), (ENV_SESSION,))
    if handled:
        return value
    # Fallback: the AppDomain outlives the script run just as envvars does.
    try:
        return AppDomain.CurrentDomain.GetData(ENV_SESSION)
    except Exception:
        return None


def session_set(value):
    handled, _ = _envvars_call(
        ("set_pyrevit_env_var", "set_pyrevit_env"), (ENV_SESSION, value))
    if handled:
        return
    try:
        AppDomain.CurrentDomain.SetData(ENV_SESSION, value)
    except Exception:
        pass


class JobHandler(IExternalEventHandler):
    """Serialised Revit API access for the modeless window.

    A queue rather than a single action slot: the user can press Find clashes
    and then Create openings before the first job has been serviced, and
    neither request should be dropped.
    """

    def __init__(self):
        self.jobs = []
        self.logger = None

    def add(self, job):
        self.jobs.append(job)

    def Execute(self, uiapp):
        while self.jobs:
            job = self.jobs.pop(0)
            try:
                job(uiapp)
            except Exception as err:
                if self.logger is not None:
                    self.logger(u"Job failed: {0}".format(clean_text(err)))

    def GetName(self):
        return "MEP Wall Openings"


def do_events():
    """Let WPF repaint mid-job.

    The job runs on Revit's UI thread, so nothing redraws until it returns.
    Interactive controls are disabled around every call site, so pumping the
    dispatcher here cannot re-enter a running job.
    """
    frame = DispatcherFrame()

    def release():
        frame.Continue = False

    Dispatcher.CurrentDispatcher.BeginInvoke(DispatcherPriority.Background,
                                             Action(release))
    Dispatcher.PushFrame(frame)


def main():
    live = session_get()
    if live:
        existing = live.get("window")
        if existing is not None:
            try:
                existing.Activate()
                return
            except Exception:
                pass
        session_set(None)

    buckets = collect_basic_wall_types()
    if not buckets:
        TaskDialog.Show("MEP Wall Openings",
                        "No Basic Wall instances were found in this document.")
        return

    window = XamlReader.Parse(XAML)

    type_list = window.FindName("TypeList")
    type_count = window.FindName("TypeCount")
    search_box = window.FindName("Search")
    report_box = window.FindName("Report")
    status_text = window.FindName("Status")
    progress = window.FindName("Progress")
    off_pipe = window.FindName("OffPipe")
    off_duct = window.FindName("OffDuct")
    off_tray = window.FindName("OffTray")
    allow_groups_box = window.FindName("AllowGroups")
    btn_scan = window.FindName("Scan")
    btn_run = window.FindName("Run")
    btn_all = window.FindName("SelectAll")
    btn_none = window.FindName("SelectNone")
    btn_copy = window.FindName("CopyReport")
    btn_close = window.FindName("Close")

    checkboxes = []
    scan_result = [None]          # mutable container, no nonlocal in IronPython
    busy = [False]

    handler = JobHandler()
    external_event = ExternalEvent.Create(handler)

    ordered = sorted(buckets.values(), key=lambda pair: element_name(pair[0]))
    for wall_type, walls in ordered:
        box = CheckBox()
        type_name = element_name(wall_type)
        box.Content = u"{0}   ({1})".format(type_name, len(walls))
        box.Tag = eid_value(wall_type.Id)
        type_list.Children.Add(box)
        checkboxes.append((box, type_name.lower()))

    type_count.Text = "{0} basic wall type(s) in use".format(len(ordered))
    search_box.Text = ""

    def log(line):
        try:
            report_box.AppendText(line + "\r\n")
            report_box.ScrollToEnd()
        except Exception:
            pass

    def set_status(text):
        try:
            status_text.Text = text
        except Exception:
            pass

    handler.logger = log

    def set_busy(state):
        busy[0] = state
        for control in (btn_scan, btn_all, btn_none):
            control.IsEnabled = not state
        if state:
            btn_run.IsEnabled = False

    def document_ready():
        if not doc.IsValidObject:
            log("The document this window was opened on has been closed. "
                "Close this window and start the tool again.")
            set_status("Document no longer available.")
            return False
        return True

    # -- plain UI events (no Revit API access) ------------------------------

    def on_search(sender, args):
        needle = search_box.Text.lower().strip()
        for box, name in checkboxes:
            box.Visibility = (Visibility.Visible if needle in name
                              else Visibility.Collapsed)

    def on_all(sender, args):
        for box, _ in checkboxes:
            if box.Visibility == Visibility.Visible:
                box.IsChecked = True

    def on_none(sender, args):
        for box, _ in checkboxes:
            box.IsChecked = False

    def on_copy(sender, args):
        try:
            from System.Windows import Clipboard
            Clipboard.SetText(report_box.Text)
            set_status("Report copied to clipboard.")
        except Exception:
            set_status("Could not access the clipboard.")

    def on_close(sender, args):
        window.Close()

    def read_offsets():
        values = {}
        for key, field, label in ((KIND_PIPE, off_pipe, "Pipes"),
                                  (KIND_DUCT, off_duct, "Ducts"),
                                  (KIND_TRAY, off_tray, "Cable trays")):
            try:
                raw = float(field.Text.strip())
            except Exception:
                raise ValueError("'{0}' offset is not a number.".format(label))
            if raw < 0:
                raise ValueError("'{0}' offset cannot be negative.".format(label))
            values[key] = raw * MM
        return values

    # -- queued jobs (everything that touches the Revit API) ----------------

    def scan_job(selected_count, targets, offsets):
        def job(uiapp):
            try:
                if not document_ready():
                    return

                report_box.Text = ""
                log("=" * 74)
                log("CLASH SCAN")
                log("=" * 74)
                log("Wall types selected : {0}".format(selected_count))
                log("Walls in scope      : {0}".format(len(targets)))
                log("Offsets (mm)        : pipes {0:.0f} | ducts {1:.0f} | trays {2:.0f}"
                    .format(to_mm(offsets[KIND_PIPE]), to_mm(offsets[KIND_DUCT]),
                            to_mm(offsets[KIND_TRAY])))
                log("Documents searched  : {0}".format(len(collect_documents())))
                log("")
                progress.IsIndeterminate = True
                do_events()

                try:
                    per_wall, stats = scan_clashes(targets, offsets)
                except Exception as err:
                    log("Scan failed: {0}".format(clean_text(err)))
                    set_status("Scan failed.")
                    return
                finally:
                    progress.IsIndeterminate = False
                    progress.Value = 0

                merged_total = 0
                for key in per_wall:
                    rects = merge_rects(
                        [item["rect"] for item in per_wall[key]["items"]], MERGE_GAP)
                    per_wall[key]["rects"] = rects
                    merged_total += len(rects)

                log("Clashes found       : {0}".format(stats["clashes"]))
                log("Walls to be edited  : {0}".format(len(per_wall)))
                log("Openings to cut     : {0}  (after merging overlaps)"
                    .format(merged_total))
                if stats["no_size"]:
                    log("MEP elements skipped: {0}  (no readable size)"
                        .format(stats["no_size"]))
                for reason in sorted(stats["reasons"].keys()):
                    log("Unhandled clashes   : {0}  ({1})"
                        .format(stats["reasons"][reason], reason))
                log("")

                if not per_wall:
                    scan_result[0] = None
                    set_status("No clashes found.")
                    return

                scan_result[0] = per_wall
                btn_run.IsEnabled = True
                set_status("{0} clash(es) across {1} wall(s). Press 'Create "
                           "openings' to proceed.".format(stats["clashes"],
                                                          len(per_wall)))
            finally:
                set_busy(False)
                if scan_result[0]:
                    btn_run.IsEnabled = True
        return job

    def run_job(per_wall, allow_groups):
        def job(uiapp):
            try:
                if not document_ready():
                    return

                total = sum(len(rec["rects"]) for rec in per_wall.values())
                confirm = TaskDialog.Show(
                    "MEP Wall Openings",
                    "Cut {0} opening(s) into {1} wall(s)?\n\n"
                    "Everything is committed as one undo step called "
                    "'MEP Wall Openings'.\n\n"
                    "Walls that would raise a warning are skipped and listed "
                    "at the end of the report.".format(total, len(per_wall)),
                    TaskDialogCommonButtons.Yes | TaskDialogCommonButtons.No)
                if confirm != TaskDialogResult.Yes:
                    set_status("Cancelled.")
                    return

                log("=" * 74)
                log("CREATING OPENINGS")
                log("=" * 74)
                if allow_groups:
                    log("Benign single-instance group warnings will be dismissed.")
                    log("")

                ok_walls = 0
                ok_openings = 0
                partial = 0
                skipped = []
                warned = []

                keys = list(per_wall.keys())
                progress.Maximum = len(keys)
                progress.Value = 0

                # One transaction per wall is what keeps a warning on one wall
                # from rolling back the others, since failure processing only
                # runs at commit. Assimilate() then merges every one of them
                # into a single undo item bearing this group's name.
                group = TransactionGroup(doc, "MEP Wall Openings")
                group.Start()

                try:
                    for index, key in enumerate(keys):
                        record = per_wall[key]
                        info = record["info"]
                        wall_id = info["id"]
                        label = u"Wall {0} [{1}]".format(eid_value(wall_id),
                                                         info["type_name"])

                        try:
                            outcome, payload = edit_wall(wall_id, info,
                                                         record["rects"],
                                                         allow_groups)
                        except Exception as err:
                            outcome = "skip"
                            payload = "unhandled error ({0})".format(clean_text(err))

                        if outcome == "ok":
                            count, notes = payload
                            ok_walls += 1
                            ok_openings += count
                            log(u"[ OK   ] {0} - {1} opening(s) created"
                                .format(label, count))
                            for note in notes:
                                partial += 1
                                log(u"         ...1 opening not cut: {0}".format(note))
                        elif outcome == "warn":
                            warned.append((eid_value(wall_id), payload))
                            log(u"[ WARN ] {0} - rolled back: {1}".format(label, payload))
                        else:
                            skipped.append((eid_value(wall_id), payload))
                            log(u"[ SKIP ] {0} - {1}".format(label, payload))

                        progress.Value = index + 1
                        if index % 5 == 0 or index == len(keys) - 1:
                            set_status("Processing {0} / {1}...".format(
                                index + 1, len(keys)))
                            do_events()

                    group.Assimilate()
                except Exception as err:
                    try:
                        if group.GetStatus() == TransactionStatus.Started:
                            group.RollBack()
                    except Exception:
                        pass
                    log("Run aborted: {0}".format(clean_text(err)))
                    set_status("Run aborted - nothing was committed.")
                    return

                log("")
                log("=" * 74)
                log("SUMMARY")
                log("=" * 74)
                log("Walls edited        : {0}".format(ok_walls))
                log("Openings created    : {0}".format(ok_openings))
                log("Walls skipped       : {0}".format(len(skipped)))
                if partial:
                    log("Openings not cut    : {0}  (on walls that otherwise "
                        "succeeded)".format(partial))
                log("Walls with warnings : {0}".format(len(warned)))
                log("Undo entry          : 'MEP Wall Openings' (single step)")

                if skipped:
                    log("")
                    log("-- Skipped walls -------------------------------------------")
                    for wid, reason in skipped:
                        log("  {0}  |  {1}".format(wid, reason))

                if warned:
                    log("")
                    log("-- Walls skipped because of Revit warnings -----------------")
                    for wid, reason in warned:
                        log("  {0}  |  {1}".format(wid, reason))
                    log("")
                    log("Warning wall IDs: {0}".format(
                        ", ".join(str(wid) for wid, _ in warned)))

                scan_result[0] = None
                set_status("Done. {0} opening(s) in {1} wall(s).".format(
                    ok_openings, ok_walls))
            finally:
                set_busy(False)
        return job

    # -- button handlers that queue the jobs --------------------------------

    def on_scan(sender, args):
        if busy[0]:
            return
        selected = [box for box, _ in checkboxes if box.IsChecked]
        if not selected:
            set_status("Select at least one wall type first.")
            return
        try:
            offsets = read_offsets()
        except ValueError as err:
            set_status(str(err))
            return

        targets = []
        for box in selected:
            wall_type, walls = buckets[int(box.Tag)]
            for wall in walls:
                targets.append((wall, element_name(wall_type)))

        scan_result[0] = None
        set_busy(True)
        set_status("Queued - waiting for Revit to become idle...")
        handler.add(scan_job(len(selected), targets, offsets))
        external_event.Raise()

    def on_run(sender, args):
        if busy[0]:
            return
        per_wall = scan_result[0]
        if not per_wall:
            return
        set_busy(True)
        set_status("Queued - waiting for Revit to become idle...")
        handler.add(run_job(per_wall, bool(allow_groups_box.IsChecked)))
        external_event.Raise()

    def on_closed(sender, args):
        session_set(None)

    search_box.TextChanged += TextChangedEventHandler(on_search)
    btn_all.Click += RoutedEventHandler(on_all)
    btn_none.Click += RoutedEventHandler(on_none)
    btn_scan.Click += RoutedEventHandler(on_scan)
    btn_run.Click += RoutedEventHandler(on_run)
    btn_copy.Click += RoutedEventHandler(on_copy)
    btn_close.Click += RoutedEventHandler(on_close)
    window.Closed += EventHandler(on_closed)

    # Parked so the objects survive the fresh module scope of the next button
    # press, are not garbage collected while the window is open, and can be
    # found and re-focused instead of duplicated.
    session_set({
        "window": window,
        "handler": handler,
        "event": external_event,
    })

    window.Show()


main()
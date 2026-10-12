# -*- coding: utf-8 -*-
"""Stair Railing Manager

Pick a Stairs element, choose a Railing Type for the inner side and another for
the outer side, and generate the railings from the runs' footprint geometry.

  Inner side : one single continuous open path chaining the inner edge of every
               run, with straight connectors across the landings.
  Outer side : one separate railing per run, following that run's outer edge.

The path is taken exactly off the run's footprint edge and then offset by a
user supplied value in millimetres (positive = inset towards the treads,
negative = pushed away from the stair).
"""

__title__ = "Stair\nRailings"
__author__ = "Mohamed Bedair"
__doc__ = "Create inner / outer railings on a selected stair from a menu of railing types."

import clr
import json

clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")
clr.AddReference("System.Xml")

from System import EventHandler
from System.Collections.Generic import List
from System.Windows import RoutedEventHandler
from System.Windows.Controls import SelectionChangedEventHandler, TextChangedEventHandler
from System.Windows.Markup import XamlReader
from System.Windows.Threading import Dispatcher, DispatcherFrame

from Autodesk.Revit.DB import (
    Arc,
    BuiltInParameter,
    CurveLoop,
    Element,
    ElementId,
    GeometryInstance,
    Options,
    Plane,
    SketchPlane,
    Solid,
    ViewDetailLevel,
    FilteredElementCollector,
    Level,
    Line,
    Transaction,
    Transform,
    UnitTypeId,
    UnitUtils,
    XYZ,
)
from Autodesk.Revit.DB.Architecture import (
    MultistoryStairs,
    Railing,
    RailingType,
    Stairs,
)
from Autodesk.Revit.UI import TaskDialog
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException

doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

# --------------------------------------------------------------------------- #
# tolerances (all internal units = decimal feet)
# --------------------------------------------------------------------------- #

def _app_tolerance(name, fallback):
    try:
        return getattr(__revit__.Application, name)
    except Exception:
        return fallback


VERTEX_TOL = _app_tolerance("VertexTolerance", 0.0005233)        # ~0.16 mm, Revit's "same point"
SHORT_CURVE = _app_tolerance("ShortCurveTolerance", 0.0025603)   # ~0.78 mm, Revit's shortest curve
JOIN_TOL = 0.0015          # ~0.5 mm, used to decide if two endpoints coincide
MIN_SEGMENT = 5.0 / 304.8  # 5 mm, shorter path pieces are folded into their neighbours
PARALLEL_DOT = 0.60        # |dot| above this means "runs along the stair path"

# True = when Revit rejects a railing path, draw that path as model lines at the
# stair base so you can see where it goes wrong. Delete the lines afterwards.
DRAW_REJECTED_PATHS = False

# True = when a railing fails, copy that stair's raw geometry (run and landing
# footprints, the edge chain, the cleaned path and the offset path) to the
# clipboard as JSON, and save it to %TEMP%\stair_railing_failure.json.
DUMP_FAILED_GEOMETRY = True

FAILED_DUMPS = []   # one entry per failed railing, filled by record_failure()
LAST_ATTEMPT = {}   # what make_railing() built on its latest call


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #

def eid_value(element_id):
    """ElementId.Value on Revit 2025+, ElementId.IntegerValue before that."""
    try:
        return element_id.Value
    except AttributeError:
        return element_id.IntegerValue


def element_name(element):
    """Element.Name is redeclared on ElementType, so IronPython cannot bind it on
    an instance. Read it through the reflected property on the class instead."""
    try:
        return Element.Name.GetValue(element)
    except Exception:
        pass
    try:
        return element.get_Name()
    except Exception:
        return "<unnamed>"


def mm_to_ft(value_mm):
    return UnitUtils.ConvertToInternalUnits(value_mm, UnitTypeId.Millimeters)


def loop_curves(curve_loop):
    """CurveLoop -> plain python list of Curve."""
    return [c for c in curve_loop]


def loop_points(curve_loop):
    """Every tessellation point of a CurveLoop, as a python list."""
    pts = []
    for crv in curve_loop:
        for p in crv.Tessellate():
            pts.append(p)
    return pts


def average_point(points):
    if not points:
        return None
    sx = 0.0
    sy = 0.0
    sz = 0.0
    for p in points:
        sx += p.X
        sy += p.Y
        sz += p.Z
    n = float(len(points))
    return XYZ(sx / n, sy / n, sz / n)


def plan_distance(a, b):
    """Distance ignoring Z - everything we compare lives on one horizontal plane."""
    dx = a.X - b.X
    dy = a.Y - b.Y
    return (dx * dx + dy * dy) ** 0.5


def curve_midpoint(crv):
    return crv.Evaluate(0.5, True)


def curve_tangent(crv, normalized_param=0.5):
    der = crv.ComputeDerivatives(normalized_param, True)
    vec = der.BasisX
    if vec.GetLength() < 1e-9:
        return XYZ.BasisX
    return vec.Normalize()


def flat_point(point, z_value):
    return XYZ(point.X, point.Y, z_value)


def flatten_curve(crv, z_value):
    """Force a curve onto the horizontal plane at z_value.

    Both ends are dropped onto the plane. Translating by the start point alone
    would leave the far end of a sloped piece hanging off the plane.
    """
    p0 = crv.GetEndPoint(0)
    p1 = crv.GetEndPoint(1)
    if abs(p0.Z - z_value) < 1e-9 and abs(p1.Z - z_value) < 1e-9:
        return crv
    if isinstance(crv, Line):
        return Line.CreateBound(flat_point(p0, z_value), flat_point(p1, z_value))
    if isinstance(crv, Arc):
        try:
            return Arc.Create(flat_point(p0, z_value), flat_point(p1, z_value),
                              flat_point(crv.Evaluate(0.5, True), z_value))
        except Exception:
            pass
    translation = XYZ(0, 0, z_value - p0.Z)
    return crv.CreateTransformed(Transform.CreateTranslation(translation))


def rebuild_curve(crv, start, end):
    """The same curve with new end points: lines stay lines, arcs keep their bulge.
    None when the result would be shorter than Revit allows."""
    if start.DistanceTo(end) < SHORT_CURVE:
        return None
    if isinstance(crv, Arc):
        try:
            return Arc.Create(start, end, crv.Evaluate(0.5, True))
        except Exception:
            pass
    return Line.CreateBound(start, end)


def plan_direction(crv):
    """Unit plan direction of a curve from its start to its end, or None."""
    vec = crv.GetEndPoint(1) - crv.GetEndPoint(0)
    vec = XYZ(vec.X, vec.Y, 0.0)
    if vec.GetLength() < 1e-9:
        return None
    return vec.Normalize()


def plan_cross(a, b):
    """Z of a x b - positive when b turns left from a."""
    return a.X * b.Y - a.Y * b.X


def plan_line_intersection(p, u, q, v):
    """Where the endless lines (p, u) and (q, v) cross in plan, at p's height.
    None when they are parallel."""
    denom = plan_cross(u, v)
    if abs(denom) < 1e-6:
        return None
    t = plan_cross(q - p, v) / denom
    return XYZ(p.X + u.X * t, p.Y + u.Y * t, p.Z)


def line_corner(first, second, reach):
    """Corner where two straight pieces would meet if trimmed / extended.

    Returns (corner, first_survives, second_survives), or None when they are not
    both lines, are parallel, or the corner is further than reach from the second
    piece's start. A piece "survives" if it still runs forwards and is longer
    than Revit's shortest curve once cut back to the corner.
    """
    if not (isinstance(first, Line) and isinstance(second, Line)):
        return None
    d1 = plan_direction(first)
    d2 = plan_direction(second)
    if d1 is None or d2 is None:
        return None
    corner = plan_line_intersection(first.GetEndPoint(0), d1, second.GetEndPoint(0), d2)
    if corner is None:
        return None
    if plan_distance(corner, second.GetEndPoint(0)) > reach:
        return None
    first_survives = (corner - first.GetEndPoint(0)).DotProduct(d1) >= SHORT_CURVE
    second_survives = (second.GetEndPoint(1) - corner).DotProduct(d2) >= SHORT_CURVE
    return corner, first_survives, second_survives


def meet_lines(first, second, reach):
    """Trim / extend two consecutive straight pieces so they share one corner.

    Returns (first, second) rebuilt, or None when they cannot meet within reach
    of both ends without one of them being flipped over or shrunk to nothing.
    """
    found = line_corner(first, second, reach)
    if found is None:
        return None
    corner, first_survives, second_survives = found
    if not (first_survives and second_survives):
        return None
    if plan_distance(corner, first.GetEndPoint(1)) > reach:
        return None
    return (Line.CreateBound(first.GetEndPoint(0), corner),
            Line.CreateBound(corner, second.GetEndPoint(1)))


def chain_curves(curves):
    """Greedily order a bag of curves into one connected chain, reversing where needed.

    Returns the chain as a list. Curves that could not be attached are dropped -
    the caller gets whatever formed one continuous run.
    """
    if not curves:
        return []

    remaining = list(curves)
    chain = [remaining.pop(0)]

    grew = True
    while remaining and grew:
        grew = False
        head = chain[0].GetEndPoint(0)
        tail = chain[-1].GetEndPoint(1)
        for i in range(len(remaining)):
            crv = remaining[i]
            p0 = crv.GetEndPoint(0)
            p1 = crv.GetEndPoint(1)
            if plan_distance(p0, tail) < JOIN_TOL:
                chain.append(crv)
            elif plan_distance(p1, tail) < JOIN_TOL:
                chain.append(crv.CreateReversed())
            elif plan_distance(p1, head) < JOIN_TOL:
                chain.insert(0, crv)
            elif plan_distance(p0, head) < JOIN_TOL:
                chain.insert(0, crv.CreateReversed())
            else:
                continue
            remaining.pop(i)
            grew = True
            break

    return chain


def reverse_chain(chain):
    return [c.CreateReversed() for c in reversed(chain)]


def close_gaps(curves):
    """Make an ordered chain contiguous.

    A gap of MIN_SEGMENT or more gets a straight bridge. Anything smaller, down to
    Revit's own vertex tolerance, is closed by pulling the next piece's start back
    onto the previous end (CurveLoop.Append refuses anything above that tolerance).
    """
    out = []
    for crv in curves:
        if out:
            previous_end = out[-1].GetEndPoint(1)
            gap = previous_end.DistanceTo(crv.GetEndPoint(0))
            if gap >= MIN_SEGMENT:
                out.append(Line.CreateBound(previous_end, crv.GetEndPoint(0)))
            elif gap > VERTEX_TOL:
                crv = rebuild_curve(crv, previous_end, crv.GetEndPoint(1))
                if crv is None:
                    continue
        out.append(crv)
    return out


def absorb_short_piece(work, index):
    """Drop a too-short piece and let its neighbours meet in its place."""
    if index == 0 or index == len(work) - 1:
        work.pop(index)
        return
    met = meet_lines(work[index - 1], work[index + 1], 4.0 * MIN_SEGMENT)
    if met is not None:
        work[index - 1:index + 2] = list(met)
    else:
        work.pop(index)   # close_gaps() pulls the next piece back onto the previous one


def tidy_path(curves):
    """Clean an ordered chain into something a railing can follow.

    - closes gaps (see close_gaps)
    - removes slivers under MIN_SEGMENT, stretching the neighbours to meet
    - merges consecutive straight pieces running on one line in one direction
    A piece that doubles back over the previous one is left alone: only the
    offset can pull the two legs apart, see offset_loop.
    """
    work = close_gaps(list(curves))
    for _ in range(500):
        short = None
        if len(work) > 1:
            for i in range(len(work)):
                if work[i].Length < MIN_SEGMENT:
                    short = i
                    break
        if short is not None:
            absorb_short_piece(work, short)
            work = close_gaps(work)
            continue

        merged = False
        for i in range(len(work) - 1):
            first = work[i]
            second = work[i + 1]
            if not (isinstance(first, Line) and isinstance(second, Line)):
                continue
            d1 = plan_direction(first)
            d2 = plan_direction(second)
            if d1 is None or d2 is None:
                continue
            if abs(plan_cross(d1, d2)) > 1e-5 or d1.DotProduct(d2) <= 0:
                continue
            work[i:i + 2] = [Line.CreateBound(first.GetEndPoint(0), second.GetEndPoint(1))]
            merged = True
            break
        if not merged:
            break
    return work


def build_curve_loop(curves):
    """Append curves into a CurveLoop, closing any gaps first."""
    cl = CurveLoop()
    for crv in close_gaps(curves):
        cl.Append(crv)
    return cl


def _segment_hit(a0, a1, b0, b1):
    """Plan point where segment a touches / crosses segment b, or None."""
    r = a1 - a0
    s = b1 - b0
    w = b0 - a0
    r_len = (r.X * r.X + r.Y * r.Y) ** 0.5
    s_len = (s.X * s.X + s.Y * s.Y) ** 0.5
    if r_len < 1e-9 or s_len < 1e-9:
        return None
    denom = plan_cross(r, s)
    if abs(denom) < 1e-9 * r_len * s_len:
        # parallel: only a problem if they lie on one line and overlap
        if abs(plan_cross(w, r)) / r_len > VERTEX_TOL:
            return None
        rr = r_len * r_len
        t0 = (w.X * r.X + w.Y * r.Y) / rr
        t1 = ((b1 - a0).X * r.X + (b1 - a0).Y * r.Y) / rr
        low = max(0.0, min(t0, t1))
        high = min(1.0, max(t0, t1))
        if high < low - VERTEX_TOL / r_len:
            return None
        return XYZ(a0.X + r.X * low, a0.Y + r.Y * low, a0.Z)
    t = plan_cross(w, s) / denom
    u = plan_cross(w, r) / denom
    tol_t = VERTEX_TOL / r_len
    tol_u = VERTEX_TOL / s_len
    if -tol_t <= t <= 1.0 + tol_t and -tol_u <= u <= 1.0 + tol_u:
        return XYZ(a0.X + r.X * t, a0.Y + r.Y * t, a0.Z)
    return None


def path_defect(curves):
    """Why a path is not one clean open line, as (reason, point), or None if it is."""
    segments = []
    for crv in curves:
        pts = list(crv.Tessellate())
        for k in range(len(pts) - 1):
            segments.append((pts[k], pts[k + 1]))
    if not segments:
        return None

    for k in range(len(segments) - 1):
        d1 = segments[k][1] - segments[k][0]
        d2 = segments[k + 1][1] - segments[k + 1][0]
        l1 = (d1.X * d1.X + d1.Y * d1.Y) ** 0.5
        l2 = (d2.X * d2.X + d2.Y * d2.Y) ** 0.5
        if l1 > 1e-9 and l2 > 1e-9 and (d1.X * d2.X + d1.Y * d2.Y) / (l1 * l2) < -0.999:
            return ("it folds back on itself", segments[k][1])

    closed = plan_distance(segments[0][0], segments[-1][1]) <= VERTEX_TOL
    last = len(segments) - 1
    for i in range(len(segments)):
        for j in range(i + 2, len(segments)):
            if closed and i == 0 and j == last:
                continue
            hit = _segment_hit(segments[i][0], segments[i][1], segments[j][0], segments[j][1])
            if hit is not None:
                return ("it loops back and touches or crosses itself", hit)
    return None


def draw_debug_path(curves, z_value, notes, label):
    """Leave a rejected path in the model as model lines, for inspection."""
    try:
        plane = Plane.CreateByNormalAndOrigin(XYZ.BasisZ, XYZ(0, 0, z_value))
        sketch = SketchPlane.Create(doc, plane)
        for crv in curves:
            doc.Create.NewModelCurve(crv, sketch)
        notes.append("{0}: the rejected path was drawn as model lines at the stair base.".format(label))
    except Exception as err:
        notes.append("{0}: could not draw the rejected path: {1}".format(label, err))


# --------------------------------------------------------------------------- #
# stair geometry analysis
# --------------------------------------------------------------------------- #

def nearest_path_data(path_curves, point):
    """Project a point onto the stair path. Returns (projected_point, tangent) or None."""
    best = None
    for pcrv in path_curves:
        try:
            projection = pcrv.Project(point)
        except Exception:
            projection = None
        if projection is None:
            continue
        dist = plan_distance(projection.XYZPoint, point)
        if best is None or dist < best[0]:
            best = (dist, pcrv, projection)

    if best is None:
        return None

    _, path_curve, projection = best
    derivatives = path_curve.ComputeDerivatives(projection.Parameter, False)
    tangent = derivatives.BasisX
    if tangent.GetLength() < 1e-9:
        return None
    return projection.XYZPoint, tangent.Normalize()


def collect_solid_points(geometry, points):
    """Every tessellated edge point of the solids inside a GeometryElement."""
    for obj in geometry:
        if isinstance(obj, Solid):
            if obj.Volume < 1e-9:
                continue
            for edge in obj.Edges:
                for pt in edge.Tessellate():
                    points.append(pt)
        elif isinstance(obj, GeometryInstance):
            collect_solid_points(obj.GetInstanceGeometry(), points)


def run_up_vector(run):
    """Plan direction pointing from the bottom of a run towards its top.

    The footprint and the stairs path are both flattened onto the base level, so
    neither carries the climb direction. The run's own solid does: its lowest and
    highest points sit at opposite ends of the flight.
    """
    options = Options()
    options.ComputeReferences = False
    options.IncludeNonVisibleObjects = False
    options.DetailLevel = ViewDetailLevel.Medium

    points = []
    try:
        geometry = run.get_Geometry(options)
        if geometry is not None:
            collect_solid_points(geometry, points)
    except Exception:
        points = []

    if len(points) >= 2:
        low = points[0]
        high = points[0]
        for pt in points:
            if pt.Z < low.Z:
                low = pt
            if pt.Z > high.Z:
                high = pt
        vector = XYZ(high.X - low.X, high.Y - low.Y, 0.0)
        if vector.GetLength() > 1e-6:
            return vector.Normalize()

    # fallback: the stairs path as Revit stores it, which reads bottom to top
    try:
        path = loop_curves(run.GetStairsPath())
    except Exception:
        return None
    if not path:
        return None
    vector = path[-1].GetEndPoint(1) - path[0].GetEndPoint(0)
    vector = XYZ(vector.X, vector.Y, 0.0)
    if vector.GetLength() < 1e-6:
        return None
    return vector.Normalize()


def orient_along(chain, direction):
    """Reverse a chain if it runs against the given plan direction."""
    if not chain or direction is None:
        return chain
    span = chain[-1].GetEndPoint(1) - chain[0].GetEndPoint(0)
    if span.X * direction.X + span.Y * direction.Y < 0:
        return reverse_chain(chain)
    return chain


def split_run_edges(run):
    """Split a run's footprint into its two long sides.

    Returns a dict with 'side_a' / 'side_b' (lists of curves), 'centroid' and 'z'.
    The two sides are separated by which hand of the stair path they sit on, so
    winder / spiral runs with several segments per side still group correctly.
    """
    footprint = run.GetFootprintBoundary()
    path_curves = loop_curves(run.GetStairsPath())
    if not path_curves:
        return None

    pts = loop_points(footprint)
    if not pts:
        return None

    info = {
        "side_a": [],
        "side_b": [],
        "centroid": average_point(pts),
        "z": pts[0].Z,
    }

    for crv in footprint:
        mid = curve_midpoint(crv)
        near = nearest_path_data(path_curves, mid)
        if near is None:
            continue
        proj_pt, path_tan = near

        # riser ends run across the path - skip them, we only want the long sides
        if abs(curve_tangent(crv).DotProduct(path_tan)) < PARALLEL_DOT:
            continue

        offset_vec = mid - proj_pt
        hand = path_tan.CrossProduct(offset_vec).Z
        if hand >= 0:
            info["side_a"].append(crv)
        else:
            info["side_b"].append(crv)

    if not info["side_a"] or not info["side_b"]:
        return None

    up_vector = run_up_vector(run)
    info["side_a"] = orient_along(chain_curves(info["side_a"]), up_vector)
    info["side_b"] = orient_along(chain_curves(info["side_b"]), up_vector)
    info["oriented"] = up_vector is not None
    return info


def stair_centroid(stairs):
    """Centroid of the whole stair footprint - runs plus landings."""
    pts = []
    for rid in stairs.GetStairsRuns():
        run = doc.GetElement(rid)
        if run is None:
            continue
        try:
            pts.extend(loop_points(run.GetFootprintBoundary()))
        except Exception:
            pass
    for lid in stairs.GetStairsLandings():
        landing = doc.GetElement(lid)
        if landing is None:
            continue
        try:
            pts.extend(loop_points(landing.GetFootprintBoundary()))
        except Exception:
            pass
    return average_point(pts)


def analyse_stairs(stairs):
    """Return an ordered list of per-run dicts: run, inner chain, outer chain, centroid."""
    run_ids = list(stairs.GetStairsRuns())
    runs = []
    for rid in run_ids:
        run = doc.GetElement(rid)
        if run is not None:
            runs.append(run)

    runs.sort(key=lambda r: r.BaseElevation)

    global_centre = stair_centroid(stairs)
    analysed = []
    skipped = []

    for run in runs:
        edges = split_run_edges(run)
        if edges is None:
            skipped.append(run)
            continue

        def side_distance(curves):
            total = 0.0
            for crv in curves:
                total += plan_distance(curve_midpoint(crv), global_centre)
            return total / float(len(curves))

        d_a = side_distance(edges["side_a"])
        d_b = side_distance(edges["side_b"])

        if d_a <= d_b:
            inner, outer = edges["side_a"], edges["side_b"]
        else:
            inner, outer = edges["side_b"], edges["side_a"]

        analysed.append({
            "run": run,
            "inner": inner,
            "outer": outer,
            "centroid": edges["centroid"],
            "z": edges["z"],
            "oriented": edges["oriented"],
        })

    return analysed, skipped


def orient_inner_sequence(analysed):
    """Orient each run's inner chain so the whole set reads as one continuous line."""
    chains = [dict(item) for item in analysed]
    if not chains:
        return chains

    # Runs are sorted by height and every chain already reads bottom to top, so
    # run N's top end always meets run N+1's bottom end across the landing. The
    # nearest-end guess below is only a fallback: on a U stair both ends of the
    # first run are equally close to the second run, and the guess can flip it.
    if all(item.get("oriented") for item in chains):
        return chains

    if len(chains) > 1:
        first = chains[0]["inner"]
        second = chains[1]["inner"]
        second_pts = [second[0].GetEndPoint(0), second[-1].GetEndPoint(1)]
        start_gap = min(plan_distance(first[0].GetEndPoint(0), p) for p in second_pts)
        end_gap = min(plan_distance(first[-1].GetEndPoint(1), p) for p in second_pts)
        if start_gap < end_gap:
            chains[0]["inner"] = reverse_chain(first)

    for i in range(1, len(chains)):
        previous_end = chains[i - 1]["inner"][-1].GetEndPoint(1)
        current = chains[i]["inner"]
        if plan_distance(current[-1].GetEndPoint(1), previous_end) < \
           plan_distance(current[0].GetEndPoint(0), previous_end):
            chains[i]["inner"] = reverse_chain(current)

    return chains


# --------------------------------------------------------------------------- #
# landing connectors
# --------------------------------------------------------------------------- #

LANDING_SNAP = 0.15   # ~45 mm, how close a run edge end must sit to a landing edge


def landing_boundaries(stairs):
    """[(landing element, ordered list of boundary curves)] for every landing."""
    found = []
    for lid in stairs.GetStairsLandings():
        landing = doc.GetElement(lid)
        if landing is None:
            continue
        try:
            curves = chain_curves(loop_curves(landing.GetFootprintBoundary()))
        except Exception:
            continue
        if curves:
            found.append((landing, curves))
    return found


def locate_on_boundary(curves, point):
    """(distance, curve index, raw parameter) of the closest spot on a boundary."""
    best = None
    for index in range(len(curves)):
        try:
            projection = curves[index].Project(point)
        except Exception:
            projection = None
        if projection is None:
            continue
        dist = plan_distance(projection.XYZPoint, point)
        if best is None or dist < best[0]:
            best = (dist, index, projection.Parameter)
    return best


def trim_curve(curve, start_param, end_param):
    """A bounded copy of a curve between two raw parameters, or None if degenerate."""
    if end_param - start_param < 1e-9:
        return None
    piece = curve.Clone()
    try:
        piece.MakeBound(start_param, end_param)
    except Exception:
        return None
    if piece.Length < SHORT_CURVE:
        return None
    return piece


def walk_boundary(curves, from_index, from_param, to_index, to_param):
    """Walk a closed boundary forwards from one spot to another, trimming both ends."""
    count = len(curves)
    pieces = []

    if from_index == to_index and to_param >= from_param:
        # same edge, walking forwards (or not at all) - never the long way round
        piece = trim_curve(curves[from_index], from_param, to_param)
        return [piece] if piece is not None else []

    piece = trim_curve(curves[from_index], from_param, curves[from_index].GetEndParameter(1))
    if piece is not None:
        pieces.append(piece)

    index = (from_index + 1) % count
    guard = 0
    while index != to_index and guard <= count:
        pieces.append(curves[index])
        index = (index + 1) % count
        guard += 1

    piece = trim_curve(curves[to_index], curves[to_index].GetEndParameter(0), to_param)
    if piece is not None:
        pieces.append(piece)

    return pieces


def path_length(curves):
    total = 0.0
    for crv in curves:
        total += crv.Length
    return total


def landing_connector(landings, start_point, end_point, notes, label):
    """The stretch of landing boundary joining two run edges.

    Falls back to a straight line when no landing carries both points, which keeps
    the railing continuous even on odd stair layouts.
    """
    best = None
    for landing, curves in landings:
        from_hit = locate_on_boundary(curves, start_point)
        to_hit = locate_on_boundary(curves, end_point)
        if from_hit is None or to_hit is None:
            continue
        if from_hit[0] > LANDING_SNAP or to_hit[0] > LANDING_SNAP:
            continue
        score = from_hit[0] + to_hit[0]
        if best is None or score < best[0]:
            best = (score, landing, curves, from_hit, to_hit)

    straight = [Line.CreateBound(start_point, end_point)]

    if best is None:
        notes.append("{0}: no landing found between two runs - joined them with a straight line.".format(label))
        return straight

    _, landing, curves, from_hit, to_hit = best

    forward = walk_boundary(curves, from_hit[1], from_hit[2], to_hit[1], to_hit[2])
    backward = walk_boundary(curves, to_hit[1], to_hit[2], from_hit[1], from_hit[2])

    # An empty walk means both run ends land on the same spot of the landing edge:
    # they only miss each other by a sliver (a run stopping short of the landing,
    # or starting just past its corner). There is nothing to walk round, so stitch
    # them straight. The other way round would be a full lap of the landing that
    # comes back to where it started - a closed loop inside the railing path,
    # which Revit refuses.
    if not forward or not backward:
        return straight

    # the way round that hugs the landing corner is always the short one; the other
    # lap runs the full outside perimeter of the landing
    backward = reverse_chain(backward)
    bridge = forward if path_length(forward) <= path_length(backward) else backward

    # tie the trimmed ends back onto the run edges exactly
    stitched = []
    lead_gap = plan_distance(start_point, bridge[0].GetEndPoint(0))
    if lead_gap >= SHORT_CURVE:
        stitched.append(Line.CreateBound(start_point, bridge[0].GetEndPoint(0)))
    stitched.extend(bridge)
    tail_gap = plan_distance(bridge[-1].GetEndPoint(1), end_point)
    if tail_gap >= SHORT_CURVE:
        stitched.append(Line.CreateBound(bridge[-1].GetEndPoint(1), end_point))

    return stitched


# --------------------------------------------------------------------------- #
# offsetting
# --------------------------------------------------------------------------- #

def side_of(crv, point):
    """+1 when point lies left of the curve (looking along it), -1 when right."""
    return 1 if plan_cross(curve_tangent(crv), point - curve_midpoint(crv)) >= 0 else -1


def offset_pieces(curves, signed_distance):
    """Offset every piece on its own, then trim / extend neighbours to meet.

    Corners are rebuilt where the offset pieces actually cross, so an inside
    corner gets trimmed instead of bridged backwards across itself. Only joints
    that cannot meet (parallel legs of a U-turn, arcs) get a straight bridge.
    """
    pieces = [crv.CreateOffset(signed_distance, XYZ.BasisZ) for crv in curves]
    reach = 4.0 * abs(signed_distance) + MIN_SEGMENT
    joined = [pieces[0]]
    for crv in pieces[1:]:
        while True:
            met = meet_lines(joined[-1], crv, reach)
            if met is not None:
                joined[-1] = met[0]
                joined.append(met[1])
                break
            found = line_corner(joined[-1], crv, reach)
            if len(joined) > 1 and found is not None and not found[1] and found[2]:
                # an inside corner swallowed the whole previous piece: drop it and
                # let the piece before it meet this one directly
                joined.pop()
                continue
            joined.append(crv)
            break
    return close_gaps(joined)


def offset_loop(curve_loop, distance_ft, towards_point):
    """Shift a path sideways by distance_ft.

    Positive moves it towards the side towards_point is on (onto the treads),
    negative pushes it the other way. CurveLoop.CreateViaOffset is tried first;
    when it throws or gives a path Revit will not take, every piece is offset on
    its own and the corners are rebuilt (offset_pieces).

    Returns (CurveLoop, note or None).
    """
    if abs(distance_ft) < 1e-9:
        return curve_loop, None

    raw = loop_curves(curve_loop)
    wanted = side_of(raw[0], towards_point)
    if distance_ft < 0:
        wanted = -wanted
    size = abs(distance_ft)
    # a joint close to a U-turn can shoot its corner miles away; anything longer
    # than this is not a sensible offset of the original path
    length_cap = path_length(raw) + 4.0 * size * len(raw) + MIN_SEGMENT

    def on_wanted_side(curves):
        return bool(curves) and side_of(raw[0], curve_midpoint(curves[0])) == wanted

    for sign in (1.0, -1.0):
        try:
            candidate = CurveLoop.CreateViaOffset(curve_loop, sign * size, XYZ.BasisZ)
        except Exception:
            continue
        curves = loop_curves(candidate)
        if not on_wanted_side(curves):
            continue
        if path_length(curves) <= length_cap and Railing.IsValidPathForRailing(candidate):
            return candidate, None

    for sign in (1.0, -1.0):
        try:
            pieces = offset_pieces(raw, sign * size)
        except Exception:
            continue
        if not on_wanted_side(pieces):
            continue
        try:
            return build_curve_loop(pieces), "offset applied per segment"
        except Exception:
            continue

    return curve_loop, "offset could not be applied, path left on the edge"


# --------------------------------------------------------------------------- #
# level lookup
# --------------------------------------------------------------------------- #

def level_for_elevation(elevation):
    """The Level whose elevation is closest to the footprint plane."""
    levels = FilteredElementCollector(doc).OfClass(Level).WhereElementIsNotElementType()
    best = None
    for lvl in levels:
        gap = abs(lvl.Elevation - elevation)
        if best is None or gap < best[0]:
            best = (gap, lvl)
    if best is None:
        return ElementId.InvalidElementId
    return best[1].Id


# --------------------------------------------------------------------------- #
# railing types
# --------------------------------------------------------------------------- #

def collect_railing_types():
    """[(display name, ElementId)] sorted by name."""
    collector = FilteredElementCollector(doc).OfClass(RailingType).WhereElementIsElementType()
    items = []
    for rtype in collector:
        try:
            family = rtype.FamilyName
        except Exception:
            family = "Railing"
        items.append(("{0} : {1}".format(family, element_name(rtype)), rtype.Id))
    items.sort(key=lambda pair: pair[0].lower())
    return items


def railings_on_stairs(stairs):
    """Every railing sitting on this stair.

    Stairs.GetAssociatedRailings only reports railings tied to the stair boundaries,
    so railings sketched onto it (including the ones this tool creates) are picked up
    separately by matching their HostId against the stair and its components.
    """
    host_ids = set()
    host_ids.add(eid_value(stairs.Id))
    for rid in stairs.GetStairsRuns():
        host_ids.add(eid_value(rid))
    for lid in stairs.GetStairsLandings():
        host_ids.add(eid_value(lid))

    found = List[ElementId]()
    seen = set()

    for rid in stairs.GetAssociatedRailings():
        if eid_value(rid) not in seen:
            seen.add(eid_value(rid))
            found.Add(rid)

    collector = FilteredElementCollector(doc).OfClass(Railing).WhereElementIsNotElementType()
    for railing in collector:
        try:
            if not railing.HasHost:
                continue
            if eid_value(railing.HostId) not in host_ids:
                continue
        except Exception:
            continue
        if eid_value(railing.Id) not in seen:
            seen.add(eid_value(railing.Id))
            found.Add(railing.Id)

    return found


# --------------------------------------------------------------------------- #
# user interface
# --------------------------------------------------------------------------- #

XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Stair Railing Manager"
        Height="720" Width="840" MinHeight="640" MinWidth="740"
        WindowStartupLocation="CenterScreen"
        Background="#161616" FontFamily="Segoe UI">
  <Window.Resources>
    <Style TargetType="TextBlock">
      <Setter Property="Foreground" Value="#F4F4F4"/>
    </Style>
    <Style TargetType="CheckBox">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Margin" Value="0,4,0,4"/>
    </Style>
    <Style TargetType="TextBox">
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="BorderBrush" Value="#525252"/>
      <Setter Property="BorderThickness" Value="1"/>
      <Setter Property="Padding" Value="5,4,5,4"/>
      <Setter Property="CaretBrush" Value="#F1C21B"/>
    </Style>
    <Style TargetType="ListBox">
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="BorderBrush" Value="#525252"/>
      <Setter Property="BorderThickness" Value="1"/>
    </Style>
    <Style x:Key="CardStyle" TargetType="Border">
      <Setter Property="Background" Value="#262626"/>
      <Setter Property="CornerRadius" Value="6"/>
      <Setter Property="Padding" Value="12"/>
    </Style>
    <Style x:Key="AccentButton" TargetType="Button">
      <Setter Property="Foreground" Value="#161616"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border Background="#F1C21B" CornerRadius="5" Padding="18,8,18,8">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style x:Key="GhostButton" TargetType="Button">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border Background="#525252" CornerRadius="5" Padding="18,8,18,8">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
  </Window.Resources>

  <Grid Margin="16">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <StackPanel Grid.Row="0" Margin="0,0,0,12">
      <TextBlock Text="Stair Railing Manager" FontSize="18" FontWeight="SemiBold"/>
      <TextBlock x:Name="SubtitleText" Foreground="#A8A8A8" FontSize="12" Margin="0,3,0,0"/>
    </StackPanel>

    <Grid Grid.Row="1">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="14"/>
        <ColumnDefinition Width="*"/>
      </Grid.ColumnDefinitions>

      <Border Grid.Column="0" Style="{StaticResource CardStyle}">
        <Grid>
          <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
          </Grid.RowDefinitions>
          <CheckBox x:Name="InnerEnabled" Grid.Row="0" IsChecked="True"
                    FontWeight="SemiBold" Content="Inner side - one continuous railing"/>
          <TextBlock Grid.Row="1" Foreground="#A8A8A8" FontSize="11" TextWrapping="Wrap"
                     Margin="0,0,0,8"
                     Text="Chains the inner edge of every run into a single open path."/>
          <TextBox x:Name="InnerSearch" Grid.Row="2" Margin="0,0,0,6"/>
          <ListBox x:Name="InnerList" Grid.Row="3"/>
          <StackPanel Grid.Row="4" Orientation="Horizontal" Margin="0,9,0,0">
            <TextBlock Text="Inner offset (mm)" FontSize="11" VerticalAlignment="Center"
                       Margin="0,0,8,0"/>
            <TextBox x:Name="InnerOffset" Text="0" Width="72"/>
          </StackPanel>
        </Grid>
      </Border>

      <Border Grid.Column="2" Style="{StaticResource CardStyle}">
        <Grid>
          <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
          </Grid.RowDefinitions>
          <CheckBox x:Name="OuterEnabled" Grid.Row="0" IsChecked="True"
                    FontWeight="SemiBold" Content="Outer side - one railing per run"/>
          <TextBlock Grid.Row="1" Foreground="#A8A8A8" FontSize="11" TextWrapping="Wrap"
                     Margin="0,0,0,8"
                     Text="Each run gets its own separate railing on its outer edge."/>
          <TextBox x:Name="OuterSearch" Grid.Row="2" Margin="0,0,0,6"/>
          <ListBox x:Name="OuterList" Grid.Row="3"/>
          <StackPanel Grid.Row="4" Orientation="Horizontal" Margin="0,9,0,0">
            <TextBlock Text="Outer offset (mm)" FontSize="11" VerticalAlignment="Center"
                       Margin="0,0,8,0"/>
            <TextBox x:Name="OuterOffset" Text="0" Width="72"/>
          </StackPanel>
        </Grid>
      </Border>
    </Grid>

    <Border Grid.Row="2" Style="{StaticResource CardStyle}" Margin="0,14,0,0">
      <Grid>
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="Auto"/>
          <ColumnDefinition Width="*"/>
        </Grid.ColumnDefinitions>

        <!-- plan of a switchback stair: which edge is inner, which is outer -->
        <Canvas Grid.Column="0" Width="206" Height="100" Margin="0,0,20,0">
          <Rectangle Canvas.Left="8"  Canvas.Top="6"  Width="104" Height="22"
                     Fill="#393939" Stroke="#525252" StrokeThickness="1"/>
          <Rectangle Canvas.Left="8"  Canvas.Top="28" Width="42"  Height="62"
                     Fill="#393939" Stroke="#525252" StrokeThickness="1"/>
          <Rectangle Canvas.Left="70" Canvas.Top="28" Width="42"  Height="62"
                     Fill="#393939" Stroke="#525252" StrokeThickness="1"/>

          <Line X1="8" Y1="40" X2="50" Y2="40" Stroke="#525252" StrokeThickness="1"/>
          <Line X1="8" Y1="52" X2="50" Y2="52" Stroke="#525252" StrokeThickness="1"/>
          <Line X1="8" Y1="64" X2="50" Y2="64" Stroke="#525252" StrokeThickness="1"/>
          <Line X1="8" Y1="76" X2="50" Y2="76" Stroke="#525252" StrokeThickness="1"/>
          <Line X1="70" Y1="40" X2="112" Y2="40" Stroke="#525252" StrokeThickness="1"/>
          <Line X1="70" Y1="52" X2="112" Y2="52" Stroke="#525252" StrokeThickness="1"/>
          <Line X1="70" Y1="64" X2="112" Y2="64" Stroke="#525252" StrokeThickness="1"/>
          <Line X1="70" Y1="76" X2="112" Y2="76" Stroke="#525252" StrokeThickness="1"/>

          <Polyline Points="50,90 50,28 70,28 70,90" Stroke="#F1C21B" StrokeThickness="2.5"
                    StrokeLineJoin="Round" Fill="Transparent"/>
          <Line X1="8"   Y1="90" X2="8"   Y2="28" Stroke="#78A9FF" StrokeThickness="2.5"/>
          <Line X1="112" Y1="90" X2="112" Y2="28" Stroke="#78A9FF" StrokeThickness="2.5"/>

          <Line X1="126" Y1="34" X2="146" Y2="34" Stroke="#F1C21B" StrokeThickness="2.5"/>
          <TextBlock Canvas.Left="152" Canvas.Top="27" FontSize="11" Foreground="#F4F4F4"
                     Text="Inner"/>
          <Line X1="126" Y1="58" X2="146" Y2="58" Stroke="#78A9FF" StrokeThickness="2.5"/>
          <TextBlock Canvas.Left="152" Canvas.Top="51" FontSize="11" Foreground="#F4F4F4"
                     Text="Outer"/>
          <TextBlock Canvas.Left="126" Canvas.Top="74" FontSize="10" Foreground="#A8A8A8"
                     Text="plan view"/>
        </Canvas>

        <StackPanel Grid.Column="1" VerticalAlignment="Center">
          <CheckBox x:Name="DeleteExisting" Content="Delete existing railings on the selected stairs"/>
          <CheckBox x:Name="HostToRun" IsChecked="True"
                    Content="Host each outer railing on its own run (single-storey only)"/>
          <CheckBox x:Name="FlipOuter" Content="Flip the outer railings"/>
          <TextBlock Foreground="#A8A8A8" FontSize="11" Margin="0,8,0,0" TextWrapping="Wrap"
                     Text="Offsets are in mm, positive = inwards onto the tread."/>
        </StackPanel>
      </Grid>
    </Border>

    <StackPanel Grid.Row="3" Orientation="Horizontal" HorizontalAlignment="Right" Margin="0,14,0,0">
      <TextBlock x:Name="StatusText" Foreground="#A8A8A8" FontSize="11"
                 VerticalAlignment="Center" Margin="0,0,14,0"/>
      <Button x:Name="CancelButton" Style="{StaticResource GhostButton}" Content="Cancel" Margin="0,0,10,0"/>
      <Button x:Name="CreateButton" Style="{StaticResource AccentButton}" Content="Create Railings"/>
    </StackPanel>
  </Grid>
</Window>
"""


class RailingDialog(object):
    """Blocking WPF dialog driven by Dispatcher.PushFrame."""

    def __init__(self, subtitle, railing_types):
        self.window = XamlReader.Parse(XAML)
        self.types = railing_types
        self.result = None
        self._frame = [None]

        self.window.FindName("SubtitleText").Text = subtitle

        self.inner_list = self.window.FindName("InnerList")
        self.outer_list = self.window.FindName("OuterList")
        self.inner_search = self.window.FindName("InnerSearch")
        self.outer_search = self.window.FindName("OuterSearch")
        self.inner_enabled = self.window.FindName("InnerEnabled")
        self.outer_enabled = self.window.FindName("OuterEnabled")
        self.inner_offset = self.window.FindName("InnerOffset")
        self.outer_offset = self.window.FindName("OuterOffset")
        self.delete_existing = self.window.FindName("DeleteExisting")
        self.host_to_run = self.window.FindName("HostToRun")
        self.flip_outer = self.window.FindName("FlipOuter")
        self.status = self.window.FindName("StatusText")

        self._inner_choice = [None]
        self._outer_choice = [None]

        names = [pair[0] for pair in self.types]
        self.inner_list.ItemsSource = names
        self.outer_list.ItemsSource = names

        self.inner_search.TextChanged += TextChangedEventHandler(self.on_inner_search)
        self.outer_search.TextChanged += TextChangedEventHandler(self.on_outer_search)
        self.inner_list.SelectionChanged += SelectionChangedEventHandler(self.on_inner_pick)
        self.outer_list.SelectionChanged += SelectionChangedEventHandler(self.on_outer_pick)

        self.window.FindName("CreateButton").Click += RoutedEventHandler(self.on_create)
        self.window.FindName("CancelButton").Click += RoutedEventHandler(self.on_cancel)
        self.window.Closed += EventHandler(self.on_closed)

    # -- filtering ---------------------------------------------------------- #

    def _filter(self, list_box, text, choice):
        needle = (text or "").strip().lower()
        if needle:
            names = [pair[0] for pair in self.types if needle in pair[0].lower()]
        else:
            names = [pair[0] for pair in self.types]
        list_box.ItemsSource = names
        if choice[0] is not None and choice[0] in names:
            list_box.SelectedItem = choice[0]

    def on_inner_search(self, sender, args):
        self._filter(self.inner_list, sender.Text, self._inner_choice)

    def on_outer_search(self, sender, args):
        self._filter(self.outer_list, sender.Text, self._outer_choice)

    def on_inner_pick(self, sender, args):
        if sender.SelectedItem is not None:
            self._inner_choice[0] = sender.SelectedItem

    def on_outer_pick(self, sender, args):
        if sender.SelectedItem is not None:
            self._outer_choice[0] = sender.SelectedItem

    # -- buttons ------------------------------------------------------------ #

    def _type_id(self, display_name):
        for name, type_id in self.types:
            if name == display_name:
                return type_id
        return None

    def on_create(self, sender, args):
        do_inner = bool(self.inner_enabled.IsChecked)
        do_outer = bool(self.outer_enabled.IsChecked)

        if not do_inner and not do_outer:
            self.status.Text = "Enable at least one side."
            return
        if do_inner and self._inner_choice[0] is None:
            self.status.Text = "Pick a railing type for the inner side."
            return
        if do_outer and self._outer_choice[0] is None:
            self.status.Text = "Pick a railing type for the outer side."
            return

        offsets = {}
        for side, box, enabled in (("inner", self.inner_offset, do_inner),
                                   ("outer", self.outer_offset, do_outer)):
            if not enabled:
                offsets[side] = 0.0
                continue
            try:
                offsets[side] = float((box.Text or "0").strip())
            except ValueError:
                self.status.Text = "The {0} offset must be a number in mm.".format(side)
                return

        self.result = {
            "do_inner": do_inner,
            "do_outer": do_outer,
            "inner_type": self._type_id(self._inner_choice[0]) if do_inner else None,
            "outer_type": self._type_id(self._outer_choice[0]) if do_outer else None,
            "offset_inner_mm": offsets["inner"],
            "offset_outer_mm": offsets["outer"],
            "delete_existing": bool(self.delete_existing.IsChecked),
            "host_to_run": bool(self.host_to_run.IsChecked),
            "flip_outer": bool(self.flip_outer.IsChecked),
        }
        self.window.Close()

    def on_cancel(self, sender, args):
        self.result = None
        self.window.Close()

    def on_closed(self, sender, args):
        if self._frame[0] is not None:
            self._frame[0].Continue = False

    def show(self):
        self.window.Show()
        frame = DispatcherFrame()
        self._frame[0] = frame
        Dispatcher.PushFrame(frame)
        return self.result


# --------------------------------------------------------------------------- #
# selection
# --------------------------------------------------------------------------- #

class StairsSelectionFilter(ISelectionFilter):
    def AllowElement(self, element):
        return isinstance(element, Stairs) or isinstance(element, MultistoryStairs)

    def AllowReference(self, reference, position):
        return False


def expand_target(element, targets, seen):
    """Turn a picked element into one or more (stairs, multistory) work items.

    A MultistoryStairs holds several Stairs elements, each of which may itself be
    repeated over a range of levels, so it fans out into one item per member stair.
    """
    if isinstance(element, MultistoryStairs):
        for sid in element.GetAllStairsIds():
            stairs = doc.GetElement(sid)
            if not isinstance(stairs, Stairs):
                continue
            key = eid_value(stairs.Id)
            if key in seen:
                continue
            seen.add(key)
            targets.append((stairs, element))
        return

    if isinstance(element, Stairs):
        key = eid_value(element.Id)
        if key in seen:
            return
        seen.add(key)
        multistory = None
        try:
            parent_id = element.MultistoryStairsId
            if parent_id is not None and parent_id != ElementId.InvalidElementId:
                parent = doc.GetElement(parent_id)
                if isinstance(parent, MultistoryStairs):
                    multistory = parent
        except Exception:
            multistory = None
        targets.append((element, multistory))


def gather_targets():
    """[(Stairs, MultistoryStairs or None)] from the selection, or from a pick."""
    targets = []
    seen = set()

    for eid in uidoc.Selection.GetElementIds():
        expand_target(doc.GetElement(eid), targets, seen)

    if targets:
        return targets

    try:
        references = uidoc.Selection.PickObjects(
            ObjectType.Element,
            StairsSelectionFilter(),
            "Select one or more stairs, then press Finish",
        )
    except OperationCanceledException:
        return []
    if references is None:
        return []

    for reference in references:
        expand_target(doc.GetElement(reference.ElementId), targets, seen)

    return targets


# --------------------------------------------------------------------------- #
# creation
# --------------------------------------------------------------------------- #

def _dump_mm(value_ft):
    return round(value_ft * 304.8, 3)


def _dump_point(point):
    return [_dump_mm(point.X), _dump_mm(point.Y), _dump_mm(point.Z)]


def _dump_curves(curves):
    out = []
    for crv in curves or []:
        try:
            item = {
                "type": type(crv).__name__,
                "start": _dump_point(crv.GetEndPoint(0)),
                "end": _dump_point(crv.GetEndPoint(1)),
            }
            if not isinstance(crv, Line):
                item["mid"] = _dump_point(crv.Evaluate(0.5, True))
            out.append(item)
        except Exception as err:
            out.append({"error": str(err)})
    return out


def record_failure(stairs, analysed, label, offset_ft, attempt=None):
    """Keep the raw geometry behind a failed railing, for save_failure_dump()."""
    if not DUMP_FAILED_GEOMETRY:
        return
    source = attempt if attempt is not None else LAST_ATTEMPT
    try:
        by_run = {}
        for item in analysed:
            by_run[eid_value(item["run"].Id)] = item

        runs = []
        for rid in stairs.GetStairsRuns():
            run = doc.GetElement(rid)
            if run is None:
                continue
            entry = {"id": int(eid_value(rid))}
            for key, reader in (("base_elevation", lambda r: _dump_mm(r.BaseElevation)),
                                ("footprint", lambda r: _dump_curves(loop_curves(r.GetFootprintBoundary()))),
                                ("stairs_path", lambda r: _dump_curves(loop_curves(r.GetStairsPath())))):
                try:
                    entry[key] = reader(run)
                except Exception as err:
                    entry[key] = {"error": str(err)}
            item = by_run.get(eid_value(rid))
            if item is None:
                entry["skipped"] = True
            else:
                entry["inner"] = _dump_curves(item["inner"])
                entry["outer"] = _dump_curves(item["outer"])
                entry["centroid"] = _dump_point(item["centroid"])
                entry["oriented"] = bool(item.get("oriented"))
            runs.append(entry)

        landings = []
        for lid in stairs.GetStairsLandings():
            landing = doc.GetElement(lid)
            if landing is None:
                continue
            try:
                footprint = _dump_curves(loop_curves(landing.GetFootprintBoundary()))
            except Exception as err:
                footprint = {"error": str(err)}
            landings.append({"id": int(eid_value(lid)), "footprint": footprint})

        towards = source.get("towards")
        FAILED_DUMPS.append({
            "label": label,
            "offset_mm": _dump_mm(offset_ft),
            "towards": _dump_point(towards) if towards is not None else None,
            "runs": runs,
            "landings": landings,
            "chain": _dump_curves(source.get("chain")),
            "tidy": _dump_curves(source.get("tidy")),
            "final": _dump_curves(source.get("final")),
        })
    except Exception as err:
        FAILED_DUMPS.append({"label": label, "dump_error": str(err)})


def _json_fallback(value):
    """json.dumps hook for .NET values IronPython's json does not know, such as
    the System.Int64 that ElementId.Value returns on Revit 2025+."""
    try:
        return int(value)
    except Exception:
        pass
    try:
        return float(value)
    except Exception:
        return str(value)


def save_failure_dump():
    """Copy the collected failure geometry to the clipboard and a temp file.
    Returns a note for the result dialog, or None if there was nothing to save."""
    if not FAILED_DUMPS:
        return None
    try:
        version = __revit__.Application.VersionNumber
    except Exception:
        version = "?"
    try:
        text = json.dumps({"revit": str(version), "units": "mm", "failures": FAILED_DUMPS},
                          separators=(",", ":"), default=_json_fallback)
    except Exception as err:
        return "Could not write the failure geometry: {0}".format(err)

    saved = None
    try:
        from System.IO import Path as IOPath
        saved = IOPath.Combine(IOPath.GetTempPath(), "stair_railing_failure.json")
        handle = open(saved, "w")
        try:
            handle.write(text)
        finally:
            handle.close()
    except Exception:
        saved = None

    copied = False
    try:
        from System.Windows import Clipboard
        Clipboard.SetText(text)
        copied = True
    except Exception:
        copied = False

    if copied and saved:
        return "Failure geometry copied to the clipboard (also saved to {0}).".format(saved)
    if copied:
        return "Failure geometry copied to the clipboard."
    if saved:
        return "Failure geometry saved to {0}.".format(saved)
    return "Could not save the failure geometry."


def build_path(curves, offset_ft, towards_point, notes, label):
    """Flatten, clean and offset an edge chain.

    Returns a dict describing the attempt. Its "curves" entry is the finished
    path (a plain list, so neighbouring paths can still be joined up), or None
    when the chain could not be assembled.
    """
    attempt = {
        "chain": list(curves or []),
        "towards": towards_point,
        "offset_ft": offset_ft,
        "tidy": None,
        "final": None,
        "curves": None,
        "raw_defect": None,
        "z": None,
    }
    LAST_ATTEMPT.clear()
    LAST_ATTEMPT.update(attempt)
    if not curves:
        notes.append("{0}: no edge to follow.".format(label))
        return attempt

    z_plane = curves[0].GetEndPoint(0).Z
    attempt["z"] = z_plane
    try:
        flat = tidy_path([flatten_curve(c, z_plane) for c in curves])
        attempt["tidy"] = flat
        loop = build_curve_loop(flat)
    except Exception as err:
        notes.append("{0}: could not assemble the path: {1}".format(label, err))
        LAST_ATTEMPT.update(attempt)
        return attempt

    attempt["raw_defect"] = path_defect(flat)
    loop, offset_note = offset_loop(loop, offset_ft, towards_point)
    if offset_note:
        notes.append("{0}: {1}".format(label, offset_note))
    attempt["curves"] = loop_curves(loop)
    attempt["final"] = attempt["curves"]
    LAST_ATTEMPT.update(attempt)
    return attempt


def create_railing(attempt, type_id, level_id, host_id, notes, label, placement_levels=None):
    """Create, host and spread one railing from a build_path() result.
    Returns the Railing or None."""
    curves = attempt.get("curves")
    if not curves:
        return None

    try:
        path = build_curve_loop(curves)
    except Exception as err:
        notes.append("{0}: could not assemble the path: {1}".format(label, err))
        return None

    if not Railing.IsValidPathForRailing(path):
        final = loop_curves(path)
        raw_defect = attempt.get("raw_defect")
        offset_ft = attempt.get("offset_ft") or 0.0
        defect = path_defect(final) or raw_defect
        reason = defect[0] if defect else "reason not identified"
        if raw_defect is not None:
            stage = "the edge path already {0} before any offset".format(raw_defect[0][3:])
        else:
            stage = "the edge path was clean, the {0:g} mm offset broke it".format(
                round(offset_ft * 304.8, 1))
        message = "{0}: Revit rejected the path - {1} ({2}).".format(label, reason, stage)
        if raw_defect is not None and raw_defect[0].startswith("it folds back") \
                and abs(offset_ft) < 1e-9:
            message += " Two runs share one inner edge here; give this side a non-zero offset."
        notes.append(message)
        if DRAW_REJECTED_PATHS:
            draw_debug_path(final, attempt.get("z") or 0.0, notes, label)
        return None

    railing = Railing.Create(doc, path, type_id, level_id)
    if railing is None:
        notes.append("{0}: Railing.Create returned nothing.".format(label))
        return None

    doc.Regenerate()

    if host_id is not None and host_id != ElementId.InvalidElementId:
        try:
            if railing.RailingCanBeHostedByElement(host_id):
                railing.HostId = host_id
                doc.Regenerate()
            else:
                notes.append("{0}: railing {1} could not be hosted on element {2}, it was "
                             "left flat at the stair's base level.".format(
                                 label, eid_value(railing.Id), eid_value(host_id)))
        except Exception as err:
            notes.append("{0}: hosting failed for railing {1}: {2}".format(
                label, eid_value(railing.Id), err))

    if placement_levels is not None:
        try:
            railing.SetMultistoryStairsPlacementLevels(placement_levels)
            doc.Regenerate()
        except Exception as err:
            notes.append("{0}: could not spread railing {1} over the storeys: {2}".format(
                label, eid_value(railing.Id), err))

    return railing


def make_railing(curves, type_id, level_id, host_id, offset_ft, towards_point, notes,
                 label, placement_levels=None):
    """Build one railing from an ordered chain of curves. Returns the Railing or None."""
    attempt = build_path(curves, offset_ft, towards_point, notes, label)
    return create_railing(attempt, type_id, level_id, host_id, notes, label, placement_levels)


def flip_railing(railing, notes):
    """Swap which side of its path the railing sits on. Not the sketch direction."""
    try:
        railing.Flip()
        doc.Regenerate()
    except Exception as err:
        notes.append("Could not flip railing {0}: {1}".format(eid_value(railing.Id), err))


# --------------------------------------------------------------------------- #
# inner side: pieces per run, and stairs whose flights are stacked in plan
# --------------------------------------------------------------------------- #

def plan_polygon(curve_loop):
    """Ordered plan outline points of a closed CurveLoop."""
    pts = []
    for crv in curve_loop:
        tess = list(crv.Tessellate())
        pts.extend(tess[:-1])
    return pts


def point_in_polygon(point, polygon):
    """Ray casting in plan."""
    inside = False
    count = len(polygon)
    j = count - 1
    for i in range(count):
        a = polygon[i]
        b = polygon[j]
        if (a.Y > point.Y) != (b.Y > point.Y):
            cross_x = a.X + (point.Y - a.Y) * (b.X - a.X) / (b.Y - a.Y)
            if point.X < cross_x:
                inside = not inside
        j = i
    return inside


def stacked_runs(stairs):
    """True when two runs of one stair sit over each other in plan.

    That happens when a single Stairs element climbs more than one storey: every
    footprint is projected onto the stair's base level, so the flights of each
    storey land on top of the ones below. One flat railing path would then have
    to run over itself, which Revit refuses.
    """
    polygons = []
    for rid in stairs.GetStairsRuns():
        run = doc.GetElement(rid)
        if run is None:
            continue
        try:
            polygon = plan_polygon(run.GetFootprintBoundary())
        except Exception:
            continue
        if len(polygon) >= 3:
            polygons.append(polygon)

    for i in range(len(polygons)):
        centre = average_point(polygons[i])
        # the centre plus points halfway to each corner - all well inside the run
        samples = [centre] + [XYZ((centre.X + p.X) / 2.0, (centre.Y + p.Y) / 2.0, centre.Z)
                              for p in polygons[i]]
        for j in range(len(polygons)):
            if i == j:
                continue
            for sample in samples:
                if point_in_polygon(sample, polygons[j]):
                    return True
    return False


def connected_landing_id(run_before, run_after):
    """Id value of the landing run_before ends on and run_after starts from,
    read from the runs' own connections, or None."""
    ends = set()
    starts = set()
    try:
        for conn in run_before.GetConnections():
            if str(conn.ConnectionType) == "ET_RunEnd":
                ends.add(eid_value(conn.PeerElementId))
        for conn in run_after.GetConnections():
            if str(conn.ConnectionType) == "ET_RunStart":
                starts.add(eid_value(conn.PeerElementId))
    except Exception:
        return None
    common = list(ends & starts)
    return common[0] if common else None


def landings_between(run_before, run_after, landings):
    """The landing(s) a turn between two runs may walk along.

    On a stair whose storeys repeat, the landings of every storey sit on top of
    each other in plan, so the nearest outline is not necessarily the right
    one. The runs' connections say which landing joins them; failing that, the
    landing at the height where run_before tops out; failing that, all of them.
    """
    wanted = connected_landing_id(run_before, run_after)
    if wanted is not None:
        chosen = [pair for pair in landings if eid_value(pair[0].Id) == wanted]
        if chosen:
            return chosen
    try:
        top = run_before.TopElevation
        chosen = [pair for pair in landings if abs(pair[0].BaseElevation - top) < 0.01]
        if chosen:
            return chosen
    except Exception:
        pass
    return landings


def inner_pieces(sequence, landings, notes, label):
    """[(run item, curves)]: each run's inner edge followed by the turn that
    carries it across its top landing to where the next run's inner edge starts.
    Chained together, the pieces are the whole inner side."""
    pieces = [(item, list(item["inner"])) for item in sequence]
    for index in range(len(pieces) - 1):
        current = pieces[index][1]
        following = pieces[index + 1][1]
        gap_start = current[-1].GetEndPoint(1)
        gap_end = following[0].GetEndPoint(0)
        # smaller gaps are closed by tidy_path() when the path is built
        if plan_distance(gap_start, gap_end) < MIN_SEGMENT:
            continue
        # two edges that turn a corner and nearly meet (L stair, runs a few mm
        # off the landing): run them to their true corner
        corner = meet_lines(current[-1], following[0], LANDING_SNAP)
        if corner is not None:
            current[-1] = corner[0]
            following[0] = corner[1]
            continue
        candidates = landings_between(pieces[index][0]["run"], pieces[index + 1][0]["run"], landings)
        current.extend(landing_connector(candidates, gap_start, gap_end, notes, label))
    return pieces


LAP_STAGGER = 10.0 / 304.8   # 10 mm, see stagger_turns()

# True = when no host gives a whole single railing, keep the last broken one in
# the model (for Geo Eyes) instead of falling back to one railing per run
KEEP_BROKEN_SINGLE_RAILING = True


def path_corners(curves):
    pts = [curves[0].GetEndPoint(0)]
    for crv in curves:
        pts.append(crv.GetEndPoint(1))
    return pts


def repeated_corners(curves):
    """How many corners of a path land on an earlier corner (in plan)."""
    pts = path_corners(curves)
    count = 0
    for i in range(len(pts)):
        for j in range(i):
            if plan_distance(pts[i], pts[j]) < MIN_SEGMENT:
                count += 1
                break
    return count


def is_u_turn(before, turn, after):
    """A short straight piece across the well, between two legs running opposite ways."""
    if not (isinstance(before, Line) and isinstance(turn, Line) and isinstance(after, Line)):
        return False
    d_before = plan_direction(before)
    d_turn = plan_direction(turn)
    d_after = plan_direction(after)
    if d_before is None or d_turn is None or d_after is None:
        return False
    if abs(d_before.DotProduct(d_turn)) > 0.1 or d_before.DotProduct(d_after) > -0.9:
        return False
    return turn.Length < before.Length and turn.Length < after.Length


def turn_midpoints(curves):
    return [curve_midpoint(curves[k]) for k in range(1, len(curves) - 1)
            if is_u_turn(curves[k - 1], curves[k], curves[k + 1])]


def stagger_turns(curves, step):
    """Copy of a path where a turn across the well that repeats an earlier one
    exactly is moved `step` further onto its landing, so the path never passes
    through the same corner twice.

    When every storey of a stair is identical, the inner path goes round the same
    rectangle once per storey. Revit accepts a path whose legs overlap in plan
    (a 4-flight stair whose two top landings differ by 10 mm worked) but not one
    that keeps coming back through the very same corners.
    """
    work = list(curves)
    # corners already spoken for: the two ends of the path never move, and every
    # turn claims its two corners once it has been placed
    taken = [work[0].GetEndPoint(0), work[-1].GetEndPoint(1)]
    for k in range(1, len(work) - 1):
        before = work[k - 1]
        turn = work[k]
        after = work[k + 1]
        if not (isinstance(before, Line) and isinstance(turn, Line) and isinstance(after, Line)):
            continue
        d_before = plan_direction(before)
        d_turn = plan_direction(turn)
        d_after = plan_direction(after)
        if d_before is None or d_turn is None or d_after is None:
            continue
        # a U-turn: across, between two legs that run opposite ways. It is the
        # short piece - a long leg between two turns matches the angles too
        if abs(d_before.DotProduct(d_turn)) > 0.1 or d_before.DotProduct(d_after) > -0.9:
            continue
        if turn.Length >= before.Length or turn.Length >= after.Length:
            continue
        steps = 0
        while steps < 50:
            shift = d_before * (step * steps)
            start = turn.GetEndPoint(0) + shift
            end = turn.GetEndPoint(1) + shift
            if not any(plan_distance(start, p) < MIN_SEGMENT or plan_distance(end, p) < MIN_SEGMENT
                       for p in taken):
                break
            steps += 1
        taken.append(start)
        taken.append(end)
        if steps == 0:
            continue
        work[k - 1] = Line.CreateBound(before.GetEndPoint(0), start)
        work[k] = Line.CreateBound(start, end)
        work[k + 1] = Line.CreateBound(end, after.GetEndPoint(1))
    return work


def geometry_count(element):
    """Solids with volume plus family instances in an element's geometry."""
    if element is None:
        return 0
    options = Options()
    options.ComputeReferences = False
    options.IncludeNonVisibleObjects = False
    options.DetailLevel = ViewDetailLevel.Medium
    try:
        geometry = element.get_Geometry(options)
    except Exception:
        return 0
    if geometry is None:
        return 0
    count = 0
    for obj in geometry:
        if isinstance(obj, Solid):
            if obj.Volume > 1e-9:
                count += 1
        elif isinstance(obj, GeometryInstance):
            count += 1
    return count


def type_has_balusters(railing_type):
    """True / False from the type's baluster pattern and posts, None if unreadable."""
    try:
        placement = railing_type.BalusterPlacement
        pattern = placement.BalusterPattern
        for index in range(pattern.GetBalusterCount()):
            if pattern.GetBaluster(index).BalusterFamilyId != ElementId.InvalidElementId:
                return True
        posts = placement.PostPattern
        for post in (posts.StartPost, posts.EndPost, posts.CornerPost):
            if post.BalusterFamilyId != ElementId.InvalidElementId:
                return True
        return False
    except Exception:
        return None


def built_extent(railing):
    """Plan extent (min x, min y, max x, max y) of everything Revit built for a
    railing: the railing itself, its top rail and its handrails."""
    ids = [railing.Id]
    try:
        top_id = railing.TopRail
        if top_id is not None and top_id != ElementId.InvalidElementId:
            ids.append(top_id)
    except Exception:
        pass
    try:
        ids.extend(list(railing.GetHandRails()))
    except Exception:
        pass
    extent = None
    for element_id in ids:
        element = doc.GetElement(element_id)
        if element is None:
            continue
        try:
            box = element.get_BoundingBox(None)
        except Exception:
            box = None
        if box is None or geometry_count(element) == 0:
            continue
        if extent is None:
            extent = [box.Min.X, box.Min.Y, box.Max.X, box.Max.Y]
        else:
            extent = [min(extent[0], box.Min.X), min(extent[1], box.Min.Y),
                      max(extent[2], box.Max.X), max(extent[3], box.Max.Y)]
    return extent


def missing_parts(railing, turns=None, margin=0.0):
    """What Revit failed to build on a railing, as a list of words; empty if whole.

    Revit accepts a railing path in plan first and builds the top rail and
    balusters afterwards, along the path at the host's heights. When it cannot
    work those out it keeps the railing element and silently drops the parts -
    on a stair it can follow the flights and still lose everything over the
    landings, so the turns across the well are checked one by one.
    """
    missing = []
    if turns:
        extent = built_extent(railing)
        reached = 0
        if extent is not None:
            for pt in turns:
                if extent[0] - margin <= pt.X <= extent[2] + margin and \
                        extent[1] - margin <= pt.Y <= extent[3] + margin:
                    reached += 1
        if reached < len(turns):
            missing.append("{0} of {1} turn(s) across the well".format(len(turns) - reached, len(turns)))
    try:
        railing_type = doc.GetElement(railing.GetTypeId())
    except Exception:
        railing_type = None
    try:
        wants_top = railing_type is not None and railing_type.TopRailType != ElementId.InvalidElementId
    except Exception:
        wants_top = False
    if wants_top:
        try:
            top_id = railing.TopRail
        except Exception:
            top_id = None
        if top_id is None or top_id == ElementId.InvalidElementId or \
                geometry_count(doc.GetElement(top_id)) == 0:
            missing.append("top rail")
    if type_has_balusters(railing_type) and geometry_count(railing) == 0:
        missing.append("balusters")
    return missing


def set_offset_from_path(railing, offset_ft, notes, label):
    """Offset a railing sideways through its own 'Offset from Path' parameter."""
    try:
        param = railing.get_Parameter(BuiltInParameter.STAIRS_RAILING_PLACEMENT_OFFSET)
    except Exception:
        param = None
    if param is None or param.IsReadOnly:
        notes.append("{0}: 'Offset from Path' is not editable on railing {1}, the offset was "
                     "not applied.".format(label, eid_value(railing.Id)))
        return
    try:
        param.Set(offset_ft)
        doc.Regenerate()
    except Exception as err:
        notes.append("{0}: could not set 'Offset from Path': {1}".format(label, err))


def stacked_single_railing(stairs, pieces, type_id, level_id, offset_ft, multistory,
                           placement_levels, notes, label):
    """One continuous inner railing over flights that are stacked in plan.

    Built like the railing that works on the 4-flight stair: the runs' inner
    edges joined across the well at each run's own landing, read from the top
    run down, offset through 'Offset from Path' rather than by moving the
    path, and hosted on the top run. If the path keeps passing through the
    same corners, the repeated turns are staggered (stagger_turns) and the path
    is tried again. Returns (railing, how) or None.
    """
    chain = [crv for _, curves in pieces for crv in curves]
    if not chain:
        return None
    z_plane = chain[0].GetEndPoint(0).Z
    try:
        drawn = tidy_path([flatten_curve(c, z_plane) for c in chain])
    except Exception as err:
        notes.append("{0}: could not assemble the single path: {1}".format(label, err))
        return None

    attempts = [("as drawn", drawn)]
    if repeated_corners(drawn):
        attempts.append(("with repeated turns staggered in {0:g} mm steps".format(
            round(LAP_STAGGER * 304.8, 1)), stagger_turns(drawn, LAP_STAGGER)))

    host_id = stairs.Id if multistory is not None else pieces[-1][0]["run"].Id
    for how, curves in attempts:
        try:
            path = build_curve_loop(reverse_chain(curves))
        except Exception as err:
            notes.append("{0}: single path {1} could not be assembled: {2}".format(label, how, err))
            continue
        if not Railing.IsValidPathForRailing(path):
            notes.append("{0}: Revit refused the single path {1} ({2} repeated corner(s)).".format(
                label, how, repeated_corners(curves)))
            continue

        railing = Railing.Create(doc, path, type_id, level_id)
        if railing is None:
            notes.append("{0}: Railing.Create returned nothing.".format(label))
            return None
        doc.Regenerate()
        if abs(offset_ft) > 1e-9:
            set_offset_from_path(railing, offset_ft, notes, label)
        if placement_levels is not None:
            try:
                railing.SetMultistoryStairsPlacementLevels(placement_levels)
                doc.Regenerate()
            except Exception as err:
                notes.append("{0}: could not spread railing {1} over the storeys: {2}".format(
                    label, eid_value(railing.Id), err))

        # host it, then check Revit really built it - top rail, balusters and every
        # turn across the well. Tried in turn: the top run (how the railings that
        # work are hosted), the Stairs element (how Revit hosts its own stair
        # railings), the bottom run
        if host_id == stairs.Id:
            hosts = [stairs.Id]
        else:
            hosts = [host_id, stairs.Id, pieces[0][0]["run"].Id]
        turns = turn_midpoints(curves)
        margin = 5.0 / 304.8 + max(0.0, -offset_ft)
        whole = False
        for candidate in hosts:
            try:
                if not railing.RailingCanBeHostedByElement(candidate):
                    notes.append("{0}: railing {1} cannot be hosted on element {2}.".format(
                        label, eid_value(railing.Id), eid_value(candidate)))
                    continue
                railing.HostId = candidate
                doc.Regenerate()
            except Exception as err:
                notes.append("{0}: hosting railing {1} on element {2} failed: {3}".format(
                    label, eid_value(railing.Id), eid_value(candidate), err))
                continue
            missing = missing_parts(railing, turns, margin)
            if candidate == stairs.Id:
                where = "the stair"
            elif candidate == hosts[0]:
                where = "the top run"
            else:
                where = "the bottom run"
            if not missing:
                if candidate != hosts[0]:
                    notes.append("{0}: rails built once hosted on {1}.".format(label, where))
                whole = True
                break
            notes.append("{0}: hosted on {1}, Revit left out: {2}.".format(
                label, where, ", ".join(missing)))

        if whole:
            return railing, how
        if KEEP_BROKEN_SINGLE_RAILING:
            notes.append("{0}: kept broken railing {1} for inspection "
                         "(KEEP_BROKEN_SINGLE_RAILING).".format(label, eid_value(railing.Id)))
            return railing, how + " - BROKEN, kept for inspection"
        notes.append("{0}: removed railing {1}, path {2}, since parts were missing.".format(
            label, eid_value(railing.Id), how))
        doc.Delete(railing.Id)
        doc.Regenerate()
    return None


def stacked_inner_railings(stairs, analysed, pieces, type_id, level_id, offset_ft, multistory,
                           placement_levels, notes, created, label):
    """Inner side of a stair whose flights overlap in plan: one railing per run.

    Each railing follows its run's inner edge and the turn across the well at
    the top of that run, and is hosted on that run so Revit knows which storey
    it belongs to. Neighbouring railings meet at the corner they share.
    """
    built = []
    for item, curves in pieces:
        piece_label = "{0} - inner run {1}".format(label, eid_value(item["run"].Id))
        attempt = build_path(curves, offset_ft, item["centroid"], notes, piece_label)
        if not attempt.get("curves"):
            record_failure(stairs, analysed, piece_label, offset_ft, attempt)
        built.append((item, piece_label, attempt))

    # each run was offset on its own: carry each railing's end and the next
    # one's start out to the corner they share, so the turn closes up
    reach = 4.0 * abs(offset_ft) + LANDING_SNAP
    for index in range(len(built) - 1):
        first = built[index][2].get("curves")
        second = built[index + 1][2].get("curves")
        if not first or not second:
            continue
        met = meet_lines(first[-1], second[0], reach)
        if met is not None:
            first[-1] = met[0]
            second[0] = met[1]

    for item, piece_label, attempt in built:
        if not attempt.get("curves"):
            continue
        # on a multistory stair the placement levels only apply to railings
        # hosted on the Stairs element itself
        host_id = stairs.Id if multistory is not None else item["run"].Id
        railing = create_railing(attempt, type_id, level_id, host_id, notes, piece_label,
                                 placement_levels)
        if railing is not None:
            created.append((piece_label, railing))
        else:
            record_failure(stairs, analysed, piece_label, offset_ft, attempt)


def build_for_stairs(stairs, multistory, choice, offsets, notes, created):
    """Do the whole job for one Stairs element. Assumes an open transaction."""
    label = "{0} (id {1})".format(element_name(stairs), eid_value(stairs.Id))

    if not Stairs.IsByComponent(doc, stairs.Id):
        notes.append("{0}: not a component based stair, skipped.".format(label))
        return

    if stairs.IsInEditMode():
        notes.append("{0}: currently in edit mode, skipped.".format(label))
        return

    analysed, skipped = analyse_stairs(stairs)
    if not analysed:
        notes.append("{0}: no run gave a usable pair of side edges.".format(label))
        return
    if skipped:
        notes.append("{0}: {1} run(s) had unreadable edges.".format(label, len(skipped)))

    level_id = level_for_elevation(analysed[0]["z"])

    placement_levels = None
    if multistory is not None:
        try:
            placement_levels = multistory.GetStairsPlacementLevels(stairs)
        except Exception as err:
            notes.append("{0}: could not read its storey levels: {1}".format(label, err))

    if choice["delete_existing"]:
        existing = railings_on_stairs(stairs)
        if existing.Count:
            doc.Delete(existing)
            doc.Regenerate()
            notes.append("{0}: deleted {1} existing railing(s).".format(label, existing.Count))

    stacked = stacked_runs(stairs)
    inner_label = "{0} - inner".format(label)

    if choice["do_inner"]:
        sequence = orient_inner_sequence(analysed)
        pieces = inner_pieces(sequence, landing_boundaries(stairs), notes, label)

        if stacked:
            result = stacked_single_railing(stairs, pieces, choice["inner_type"], level_id,
                                            offsets["inner"], multistory, placement_levels,
                                            notes, inner_label)
            if result is not None:
                railing, how = result
                created.append((inner_label, railing))
                notes.append("{0}: flights are stacked in plan; made one continuous railing, "
                             "path {1}.".format(inner_label, how))
            else:
                notes.append("{0}: no single railing came out whole, falling back to one "
                             "railing per run.".format(inner_label))
                stacked_inner_railings(stairs, analysed, pieces, choice["inner_type"], level_id,
                                       offsets["inner"], multistory, placement_levels, notes,
                                       created, label)
        else:
            chain = [crv for _, curves in pieces for crv in curves]
            railing = make_railing(
                chain,
                choice["inner_type"],
                level_id,
                stairs.Id,
                offsets["inner"],
                sequence[0]["centroid"],
                notes,
                inner_label,
                placement_levels,
            )
            if railing is not None:
                created.append((inner_label, railing))
            else:
                record_failure(stairs, analysed, inner_label, offsets["inner"])

    if choice["do_outer"]:
        for item in analysed:
            # a railing on a multistory stair has to hang off the Stairs element
            # itself for the placement levels to apply. With stacked flights the
            # path sits over several runs in plan, so it must hang off its own run
            # or Revit cannot tell which flight it belongs to.
            if multistory is not None:
                host_id = stairs.Id
            elif stacked or choice["host_to_run"]:
                host_id = item["run"].Id
            else:
                host_id = stairs.Id

            railing = make_railing(
                item["outer"],
                choice["outer_type"],
                level_id,
                host_id,
                offsets["outer"],
                item["centroid"],
                notes,
                "{0} - outer run {1}".format(label, eid_value(item["run"].Id)),
                placement_levels,
            )
            if railing is not None:
                if choice["flip_outer"]:
                    flip_railing(railing, notes)
                created.append((
                    "{0} - outer run {1}".format(label, eid_value(item["run"].Id)),
                    railing,
                ))
            else:
                record_failure(stairs, analysed,
                               "{0} - outer run {1}".format(label, eid_value(item["run"].Id)),
                               offsets["outer"])


def main():
    targets = gather_targets()
    if not targets:
        return

    railing_types = collect_railing_types()
    if not railing_types:
        TaskDialog.Show("Stair Railing Manager", "No railing types were found in this project.")
        return

    multistory_count = len([1 for _, parent in targets if parent is not None])
    if len(targets) == 1:
        stairs = targets[0][0]
        subtitle = "{0}  -  id {1}  -  {2} run(s), {3} landing(s)".format(
            element_name(stairs),
            eid_value(stairs.Id),
            len(list(stairs.GetStairsRuns())),
            len(list(stairs.GetStairsLandings())),
        )
    else:
        subtitle = "{0} stairs selected".format(len(targets))
    if multistory_count:
        subtitle += "  -  {0} of them multistory".format(multistory_count)

    dialog = RailingDialog(subtitle, railing_types)
    choice = dialog.show()
    if choice is None:
        return

    offsets = {
        "inner": mm_to_ft(choice["offset_inner_mm"]),
        "outer": mm_to_ft(choice["offset_outer_mm"]),
    }
    notes = []
    created = []
    del FAILED_DUMPS[:]

    transaction = Transaction(doc, "Create Stair Railings")
    transaction.Start()
    try:
        for stairs, multistory in targets:
            try:
                build_for_stairs(stairs, multistory, choice, offsets, notes, created)
            except Exception as err:
                # one bad stair should not throw away the work done on the others
                notes.append("{0} (id {1}) failed: {2}".format(
                    element_name(stairs), eid_value(stairs.Id), err))
        doc.Regenerate()
        transaction.Commit()
    except Exception:
        transaction.RollBack()
        raise

    dump_note = save_failure_dump()
    if dump_note:
        notes.append(dump_note)

    lines = ["Created {0} railing(s) on {1} stair(s).".format(len(created), len(targets))]
    for label, railing in created:
        lines.append("  {0}  ->  id {1}".format(label, eid_value(railing.Id)))
    if notes:
        lines.append("")
        lines.append("Notes:")
        for note in notes:
            lines.append("  " + note)

    TaskDialog.Show("Stair Railing Manager", "\n".join(lines))


main()
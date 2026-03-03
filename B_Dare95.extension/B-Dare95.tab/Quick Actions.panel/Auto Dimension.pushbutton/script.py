# -*- coding: utf-8 -*-
__title__ = "Easy Dimension"
__author__ = "Mohamed Bedair"
__version__ = '1.0.0'
__doc__ = """
Version = 1.1.0
Date    = 26.02.2026

Description:
Easily creates Dimensions using two points picked in space

How-to:
-> Pick a point near the area you want to dimension
-> Pick the second point at the end of the area you want to dimension
-> A Dimension will be created crossing all the spaces between the two points

Author: Mohamed Bedair
"""

from pyrevit import DB
from Autodesk.Revit.UI import TaskDialog
from Autodesk.Revit.Exceptions import OperationCanceledException

uiapp = __revit__
uidoc  = uiapp.ActiveUIDocument
doc    = uidoc.Document

SHORT_TOL = doc.Application.ShortCurveTolerance
POS_TOL   = 0.02  # ~6 mm deduplication threshold (feet)


# ─────────────────────────────────────────────────────────────────────────────
# Geometry helpers
# ─────────────────────────────────────────────────────────────────────────────

def snap_orthogonal(p1, p2):
    if abs(p2.X - p1.X) >= abs(p2.Y - p1.Y):
        return DB.XYZ(p1.X, p1.Y, 0.0), DB.XYZ(p2.X, p1.Y, 0.0)
    else:
        return DB.XYZ(p1.X, p1.Y, 0.0), DB.XYZ(p1.X, p2.Y, 0.0)


def crosses(dim_s, dim_e, wall_curve):
    try:
        w0 = wall_curve.GetEndPoint(0)
        w1 = wall_curve.GetEndPoint(1)

        def cross2d(ox, oy, ax, ay, bx, by):
            return (ax - ox) * (by - oy) - (ay - oy) * (bx - ox)

        d1 = cross2d(w0.X, w0.Y, w1.X, w1.Y, dim_s.X, dim_s.Y)
        d2 = cross2d(w0.X, w0.Y, w1.X, w1.Y, dim_e.X, dim_e.Y)
        d3 = cross2d(dim_s.X, dim_s.Y, dim_e.X, dim_e.Y, w0.X, w0.Y)
        d4 = cross2d(dim_s.X, dim_s.Y, dim_e.X, dim_e.Y, w1.X, w1.Y)

        return (d1 * d2 < 0) and (d3 * d4 < 0)
    except Exception:
        return False


def scalar_pos(pt, origin, direction):
    return (pt.X - origin.X) * direction.X + (pt.Y - origin.Y) * direction.Y


def face_centre(face):
    bb = face.GetBoundingBox()
    u  = (bb.Min.U + bb.Max.U) * 0.5
    v  = (bb.Min.V + bb.Max.V) * 0.5
    return face.Evaluate(DB.UV(u, v))


# ─────────────────────────────────────────────────────────────────────────────
# Wall reference collector
# ─────────────────────────────────────────────────────────────────────────────

def collect_wall_refs(view, dim_start, dim_end, origin, direction):
    """
    For every wall the line crosses, collect both face references tagged with
    the wall's ElementId. Returns a list of (position, reference, wall_id)
    sorted along the dimension direction.
    """
    results = []

    walls = (
        DB.FilteredElementCollector(doc, view.Id)
        .OfCategory(DB.BuiltInCategory.OST_Walls)
        .WhereElementIsNotElementType()
        .ToElements()
    )

    for wall in walls:
        try:
            loc = wall.Location
            if not isinstance(loc, DB.LocationCurve):
                continue
            if not crosses(dim_start, dim_end, loc.Curve):
                continue

            ext_refs = list(DB.HostObjectUtils.GetSideFaces(wall, DB.ShellLayerType.Exterior))
            int_refs = list(DB.HostObjectUtils.GetSideFaces(wall, DB.ShellLayerType.Interior))

            wall_id = wall.Id.Value  # Revit 2026 uses .Value instead of .IntegerValue

            for ref in ext_refs + int_refs:
                try:
                    face = wall.GetGeometryObjectFromReference(ref)
                    if not isinstance(face, DB.Face):
                        continue
                    pos = scalar_pos(face_centre(face), origin, direction)
                    results.append((pos, ref, wall_id))
                except Exception:
                    continue

        except Exception:
            continue

    # Sort along the dimension ray
    results.sort(key=lambda x: x[0])

    # Deduplicate coincident refs
    if not results:
        return []

    kept = [results[0]]
    for item in results[1:]:
        if item[0] - kept[-1][0] > POS_TOL:
            kept.append(item)

    return kept


# ─────────────────────────────────────────────────────────────────────────────
# Dimension builder
# ─────────────────────────────────────────────────────────────────────────────

def create_dimensions(view, raw_p1, raw_p2):
    start, end = snap_orthogonal(raw_p1, raw_p2)

    if start.DistanceTo(end) < SHORT_TOL:
        return 0

    direction = DB.XYZ(end.X - start.X, end.Y - start.Y, 0.0).Normalize()
    dim_line  = DB.Line.CreateBound(start, end)

    refs = collect_wall_refs(view, start, end, start, direction)

    if len(refs) < 2:
        return 0

    # Build one dimension per SPACE gap:
    # A gap is a "space" when the two refs on either side belong to DIFFERENT walls.
    # A gap between two refs of the SAME wall is wall thickness — skipped entirely.
    #
    # We walk through consecutive pairs and group contiguous space-boundary refs:
    #   ref[0] (wall A, face 1) → skip (same wall) → ref[1] (wall A, face 2)
    #   ref[1] (wall A, face 2) → SPACE              → ref[2] (wall B, face 1)
    #   ref[2] (wall B, face 1) → skip (same wall) → ref[3] (wall B, face 2)
    #   ref[3] (wall B, face 2) → SPACE              → ref[4] (wall C, face 1)
    #
    # Each space dimension = [right face of left wall, left face of right wall]

    dims_created = 0

    for i in range(len(refs) - 1):
        pos_a, ref_a, wid_a = refs[i]
        pos_b, ref_b, wid_b = refs[i + 1]

        # Same wall → this gap is wall thickness → skip
        if wid_a == wid_b:
            continue

        # Different walls → this gap is interior space → create a dimension
        ra = DB.ReferenceArray()
        ra.Append(ref_a)
        ra.Append(ref_b)

        doc.Create.NewDimension(view, dim_line, ra)
        dims_created += 1

    if dims_created == 0:
        return 0
    return dims_created


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    view = uidoc.ActiveView
    if not isinstance(view, DB.ViewPlan):
        TaskDialog.Show("Auto Dimension", "Open a floor plan view first.")
        return

    total_dims = [0]  # mutable container so create_dimensions can update it

    def run_once(p1, p2):
        with DB.Transaction(doc, "Auto Dimension") as t:
            t.Start()
            try:
                count = create_dimensions(view, p1, p2)
                t.Commit()
                total_dims[0] += count
            except Exception as e:
                t.RollBack()
                TaskDialog.Show("Auto Dimension", "Failed: {}".format(e))

    while True:
        try:
            p1 = uidoc.Selection.PickPoint("Pick START  (ESC to exit)")
            p2 = uidoc.Selection.PickPoint("Pick END    (ESC to exit)")
            run_once(p1, p2)
        except OperationCanceledException:
            TaskDialog.Show(
                "Auto Dimension — Done",
                "Created {} space dimension(s) total.".format(total_dims[0])
            )
            break
        except Exception as e:
            TaskDialog.Show("Auto Dimension", "Pick error: {}".format(e))
            break


if __name__ == "__main__":
    main()
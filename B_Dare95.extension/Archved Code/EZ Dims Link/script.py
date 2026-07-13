# -*- coding: utf-8 -*-
__title__ = "Easy Dimension"
__author__ = "Mohamed Bedair"
__version__ = '1.1.0'
__doc__ = """
Version = 1.2.0
Date    = 09.07.2026

Description:
Easily creates Dimensions using two points picked in space.
Uses BOTH walls in the active document AND walls from linked models
as reference placeholders for the dimension string.

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


def get_wall_uid(wall, link_id=None):
    """
    Unique key for a wall across the host doc AND every linked doc.
    (link_id, element_id) — link_id is None for host-document walls.
    """
    eid = wall.Id.Value  # Revit 2026 uses .Value instead of .IntegerValue
    return (link_id, eid)


def get_view_z_range(view):
    """
    Returns (z_bottom, z_top) in host-document elevation for the active
    view's plan range — Top Clip Plane down to whichever is lower of the
    Bottom Clip Plane / View Depth plane. Used to reject walls that belong
    to other levels (a common issue with linked-doc walls, which have no
    inherent per-view visibility filtering).
    """
    base_level = view.GenLevel
    base_elev = base_level.Elevation if base_level else 0.0

    def plane_elev(vr, plane_key, default):
        try:
            lvl_id = vr.GetLevelId(plane_key)
            off = vr.GetOffset(plane_key)
            if lvl_id == DB.ElementId.InvalidElementId:
                return default
            lvl = doc.GetElement(lvl_id)
            return lvl.Elevation + off
        except Exception:
            return default

    try:
        vr = view.GetViewRange()
        top = plane_elev(vr, DB.PlanViewPlane.TopClipPlane, base_elev + 1000.0)
        bottom = plane_elev(vr, DB.PlanViewPlane.BottomClipPlane, base_elev - 1000.0)
        depth = plane_elev(vr, DB.PlanViewPlane.ViewDepthPlane, bottom)
        bottom = min(bottom, depth)
        return bottom, top
    except Exception:
        return base_elev - 1000.0, base_elev + 1000.0


def wall_in_z_range(wall, transform, z_bottom, z_top):
    """
    True if the wall's vertical extent overlaps the active view's Z band.
    Bounding box is transformed into host coordinates first (identity
    transform for host-doc walls).
    """
    try:
        bb = wall.get_BoundingBox(None)
        if bb is None:
            return True  # can't determine — don't exclude

        pmin, pmax = bb.Min, bb.Max
        if not transform.IsIdentity:
            pmin = transform.OfPoint(pmin)
            pmax = transform.OfPoint(pmax)

        wall_bottom = min(pmin.Z, pmax.Z)
        wall_top    = max(pmin.Z, pmax.Z)

        return wall_top >= z_bottom and wall_bottom <= z_top
    except Exception:
        return True


# ─────────────────────────────────────────────────────────────────────────────
# Wall reference collector
# ─────────────────────────────────────────────────────────────────────────────

def _collect_from_walls(walls, dim_start, dim_end, origin, direction,
                         transform, link_instance, link_id, z_bottom, z_top):
    """
    Shared logic for both host-doc and linked-doc walls.
    `transform` maps points/curves from the wall's native doc into
    host-document coordinates (Transform.Identity for host walls).
    `link_instance` is the RevitLinkInstance the walls came from
    (None for host walls) — used to build a combined Reference.
    `z_bottom`/`z_top` restrict results to walls whose vertical extent
    overlaps the active view's plan range, so walls from other levels
    (particularly from links, which have no per-view visibility of
    their own) are excluded.
    """
    results = []

    for wall in walls:
        try:
            if not wall_in_z_range(wall, transform, z_bottom, z_top):
                continue

            loc = wall.Location
            if not isinstance(loc, DB.LocationCurve):
                continue

            wall_curve = loc.Curve
            if not transform.IsIdentity:
                wall_curve = wall_curve.CreateTransformed(transform)

            if not crosses(dim_start, dim_end, wall_curve):
                continue

            ext_refs = list(DB.HostObjectUtils.GetSideFaces(wall, DB.ShellLayerType.Exterior))
            int_refs = list(DB.HostObjectUtils.GetSideFaces(wall, DB.ShellLayerType.Interior))

            wall_uid = get_wall_uid(wall, link_id)

            for ref in ext_refs + int_refs:
                try:
                    face = wall.GetGeometryObjectFromReference(ref)
                    if not isinstance(face, DB.Face):
                        continue

                    centre = face_centre(face)
                    if not transform.IsIdentity:
                        centre = transform.OfPoint(centre)

                    pos = scalar_pos(centre, origin, direction)

                    # For linked walls, the raw reference is only valid inside
                    # the link's own document — convert it into a reference
                    # that resolves correctly from the host view.
                    if link_instance is not None:
                        ref = ref.CreateLinkReference(link_instance)

                    results.append((pos, ref, wall_uid))
                except Exception:
                    continue

        except Exception:
            continue

    return results


def collect_wall_refs(view, dim_start, dim_end, origin, direction):
    """
    For every wall (active document + linked documents) the line crosses,
    collect both face references tagged with a unique wall id.
    Returns a list of (position, reference, wall_uid) sorted along the
    dimension direction.
    """
    results = []
    z_bottom, z_top = get_view_z_range(view)

    # ---- Active document walls -------------------------------------------------
    host_walls = (
        DB.FilteredElementCollector(doc, view.Id)
        .OfCategory(DB.BuiltInCategory.OST_Walls)
        .WhereElementIsNotElementType()
        .ToElements()
    )

    results.extend(
        _collect_from_walls(
            host_walls, dim_start, dim_end, origin, direction,
            DB.Transform.Identity, None, None, z_bottom, z_top
        )
    )

    # ---- Linked document walls --------------------------------------------------
    link_instances = (
        DB.FilteredElementCollector(doc, view.Id)
        .OfCategory(DB.BuiltInCategory.OST_RvtLinks)
        .WhereElementIsNotElementType()
        .ToElements()
    )

    for link_instance in link_instances:
        try:
            link_doc = link_instance.GetLinkDocument()
            if link_doc is None:
                continue  # unloaded link

            link_transform = link_instance.GetTotalTransform()
            link_id = link_instance.Id.Value  # Revit 2026 uses .Value

            linked_walls = (
                DB.FilteredElementCollector(link_doc)
                .OfCategory(DB.BuiltInCategory.OST_Walls)
                .WhereElementIsNotElementType()
                .ToElements()
            )

            results.extend(
                _collect_from_walls(
                    linked_walls, dim_start, dim_end, origin, direction,
                    link_transform, link_instance, link_id, z_bottom, z_top
                )
            )
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
    # A gap is a "space" when the two refs on either side belong to DIFFERENT walls
    # (host or linked — compared via their unique wall_uid).
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
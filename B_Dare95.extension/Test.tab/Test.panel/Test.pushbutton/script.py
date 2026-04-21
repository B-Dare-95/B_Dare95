# -*- coding: utf-8 -*-
"""
FLS Area Plan Creator
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Creates Area Plans from selected Floor Plan views with automatic
NET / GROSS boundary logic derived from room Occupancy values.

Boundary rules:
  • NET  room  → boundary at interior finish face of wall
  • GROSS room → boundary at exterior (outer) face of wall
  • GROSS ↔ GROSS shared wall → boundary at wall centre-line

After all boundaries are placed, duplicate / overlapping curves
are removed for a clean result.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Author  : B_Dare95
Version : 1.0.0
"""

# ──────────────────────────────────────────────────────────────
# IMPORTS
# ──────────────────────────────────────────────────────────────
import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')

from Autodesk.Revit.DB import (
    FilteredElementCollector, ViewPlan, ViewType,
    AreaScheme, Transaction,
    SpatialElementBoundaryOptions, SpatialElementBoundaryLocation,
    Wall, LocationPoint,
    Plane, SketchPlane, Transform, XYZ, UV, ElementId,
    BuiltInParameter, BuiltInCategory
)
from pyrevit import forms, script

# ──────────────────────────────────────────────────────────────
# REVIT HANDLES
# ──────────────────────────────────────────────────────────────
uidoc = __revit__.ActiveUIDocument
doc   = uidoc.Document

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECTION 1 – HELPER UTILITIES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _occupancy(room):
    """Return the room's Occupancy value, upper-cased, or empty string."""
    param = room.get_Parameter(BuiltInParameter.ROOM_OCCUPANCY)
    if param is None:
        return ""
    return (param.AsString() or "").strip().upper()


def _is_gross(room):
    return "GROSS" in _occupancy(room)


def _build_wall_room_map(rooms):
    """
    Returns a dict  { wall_ElementId : [room, ...] }
    mapping every wall that acts as a room boundary to the rooms
    that share it.  Uses the Finish face option so we match the
    same segments used for NET boundaries.
    """
    opts = SpatialElementBoundaryOptions()
    opts.SpatialElementBoundaryLocation = SpatialElementBoundaryLocation.Finish

    wall_map = {}
    for room in rooms:
        try:
            for loop in room.GetBoundarySegments(opts):
                for seg in loop:
                    wid = seg.ElementId
                    if wid == ElementId.InvalidElementId:
                        continue
                    if wid not in wall_map:
                        wall_map[wid] = []
                    # avoid duplicating the same room
                    if not any(r.Id == room.Id for r in wall_map[wid]):
                        wall_map[wid].append(room)
        except Exception:
            pass
    return wall_map


def _outer_face_curve(center_curve, wall, room_pt):
    """
    Translate a wall centre-line curve to the exterior face of the wall
    (i.e. away from the given room_pt).

    The translation vector is: wall.Orientation (or its negation)
    scaled by half the wall thickness.
    """
    try:
        half_width  = wall.Width / 2.0          # Revit internal units (feet)
        wall_normal = wall.Orientation           # unit XY vector ⊥ to wall

        # Vector from wall midpoint toward the room
        wall_mid = center_curve.Evaluate(0.5, True)
        to_room  = XYZ(room_pt.X - wall_mid.X,
                       room_pt.Y - wall_mid.Y,
                       0.0)

        # If the room is on the "positive" side of wall_normal,
        # the exterior face is in the opposite direction.
        dot = to_room.DotProduct(wall_normal)
        outward = wall_normal.Negate() if dot > 0 else wall_normal

        offset    = XYZ(outward.X * half_width,
                        outward.Y * half_width,
                        0.0)
        transform = Transform.CreateTranslation(offset)
        return center_curve.CreateTransformed(transform)

    except Exception:
        return center_curve          # fallback: stay on centre-line


def _get_boundary_curves(room, gross_ids, wall_map, doc):
    """
    Return a flat list of Revit Curve objects representing the area
    boundary for this room, applying the NET / GROSS rules.

    NET  → Finish-face curves (standard room boundary, no offset)
    GROSS, shared wall with another GROSS room → Centre-line curve
    GROSS, all other walls → Outer-face curve (centre + half-width offset)
    """
    opts_finish = SpatialElementBoundaryOptions()
    opts_finish.SpatialElementBoundaryLocation = SpatialElementBoundaryLocation.Finish

    opts_center = SpatialElementBoundaryOptions()
    opts_center.SpatialElementBoundaryLocation = SpatialElementBoundaryLocation.Center

    finish_loops = room.GetBoundarySegments(opts_finish)
    if not finish_loops:
        return []

    gross        = _is_gross(room)
    center_loops = room.GetBoundarySegments(opts_center) if gross else None

    loc     = room.Location
    room_pt = loc.Point if isinstance(loc, LocationPoint) else None

    curves = []

    for li, loop in enumerate(finish_loops):
        for si, seg in enumerate(loop):
            wid      = seg.ElementId
            wall_elm = doc.GetElement(wid)

            # ── NET room  OR  non-wall boundary  ──────────────────────
            if not gross or not isinstance(wall_elm, Wall):
                curves.append(seg.GetCurve())
                continue

            # ── GROSS room, wall boundary ──────────────────────────────
            # Safely retrieve the matching centre-line segment
            try:
                center_crv = center_loops[li][si].GetCurve()
            except Exception:
                center_crv = seg.GetCurve()

            # Check whether the neighbouring room is also GROSS
            adj_rooms  = wall_map.get(wid, [])
            adj_gross  = [r for r in adj_rooms
                          if r.Id != room.Id and r.Id in gross_ids]

            if adj_gross:
                # Shared GROSS ↔ GROSS wall → use centre-line
                curves.append(center_crv)
            else:
                # Exterior or NET neighbour → use outer face
                if room_pt:
                    curves.append(_outer_face_curve(center_crv, wall_elm, room_pt))
                else:
                    curves.append(center_crv)

    return curves


def _project_to_z(curve, z):
    """Translate a curve so both endpoints sit at the given Z elevation."""
    try:
        z_current = curve.GetEndPoint(0).Z
        if abs(z_current - z) < 1e-6:
            return curve
        t = Transform.CreateTranslation(XYZ(0.0, 0.0, z - z_current))
        return curve.CreateTransformed(t)
    except Exception:
        return curve


def _are_duplicates(c1, c2, tol=0.01):
    """True when c1 and c2 share the same end-points (either orientation)."""
    try:
        s1, e1 = c1.GetEndPoint(0), c1.GetEndPoint(1)
        s2, e2 = c2.GetEndPoint(0), c2.GetEndPoint(1)
        close  = lambda a, b: a.DistanceTo(b) < tol
        return ((close(s1, s2) and close(e1, e2)) or
                (close(s1, e2) and close(e1, s2)))
    except Exception:
        return False


def _deduplicate(curves):
    """Remove exact duplicate curves (same endpoints within tolerance)."""
    unique = []
    for c in curves:
        if not any(_are_duplicates(c, u) for u in unique):
            unique.append(c)
    return unique


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECTION 2 – USER PROMPTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# ── 2a. Select Floor Plan views ────────────────────────────────
all_floor_plans = [
    v for v in FilteredElementCollector(doc)
                 .OfClass(ViewPlan)
                 .WhereElementIsNotElementType()
                 .ToElements()
    if v.ViewType == ViewType.FloorPlan and not v.IsTemplate
]

if not all_floor_plans:
    forms.alert("No Floor Plan views found in the project.", exitscript=True)

fp_dict = {v.Name: v for v in sorted(all_floor_plans, key=lambda x: x.Name)}

selected_view_names = forms.SelectFromList.show(
    sorted(fp_dict.keys()),
    title="Step 1 of 2 – Select Floor Plan Views",
    width=460,
    multiselect=True,
    button_name="Next →"
)
if not selected_view_names:
    script.exit()

selected_plan_views = [fp_dict[n] for n in selected_view_names]

# ── 2b. Select Area Scheme ─────────────────────────────────────
all_schemes = list(
    FilteredElementCollector(doc).OfClass(AreaScheme).ToElements()
)
if not all_schemes:
    forms.alert("No Area Schemes found in the project.", exitscript=True)

scheme_dict = {s.Name: s for s in all_schemes}

selected_scheme_name = forms.SelectFromList.show(
    sorted(scheme_dict.keys()),
    title="Step 2 of 2 – Select Area Scheme",
    width=340,
    multiselect=False,
    button_name="Create Area Plans"
)
if not selected_scheme_name:
    script.exit()

# SelectFromList with multiselect=False may return a list or a string
if isinstance(selected_scheme_name, list):
    selected_scheme_name = selected_scheme_name[0]

target_scheme = scheme_dict[selected_scheme_name]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECTION 3 – PRE-CACHE EXISTING AREA PLAN VIEWS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# level_ElementId → existing ViewPlan (AreaPlan) for the chosen scheme
existing_area_plans = {}

for v in (FilteredElementCollector(doc)
          .OfClass(ViewPlan)
          .WhereElementIsNotElementType()
          .ToElements()):
    if v.ViewType != ViewType.AreaPlan:
        continue
    try:
        if v.AreaScheme.Id == target_scheme.Id:
            lv = v.GenLevel
            if lv is not None:
                existing_area_plans[lv.Id] = v
    except Exception:
        pass


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECTION 4 – MAIN TRANSACTION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

total_areas    = 0
total_bounds   = 0
skipped_views  = []

t = Transaction(doc, "FLS Area Plans – Boundaries & Areas")
t.Start()

try:
    for plan_view in selected_plan_views:

        # ── Collect placed (non-zero area) rooms ───────────────
        rooms = [
            r for r in FilteredElementCollector(doc, plan_view.Id)
                         .OfCategory(BuiltInCategory.OST_Rooms)
                         .WhereElementIsNotElementType()
                         .ToElements()
            if r.Area > 0
        ]

        if not rooms:
            skipped_views.append(plan_view.Name)
            continue

        gross_ids = set(r.Id for r in rooms if _is_gross(r))
        wall_map  = _build_wall_room_map(rooms)

        # ── Get / create matching Area Plan view ───────────────
        level = plan_view.GenLevel
        if level is None:
            skipped_views.append(plan_view.Name)
            continue

        if level.Id in existing_area_plans:
            area_view = existing_area_plans[level.Id]
        else:
            try:
                area_view = ViewPlan.CreateAreaPlan(
                    doc, target_scheme.Id, level.Id
                )
                existing_area_plans[level.Id] = area_view
            except Exception as e:
                skipped_views.append("{} (view creation failed: {})".format(
                    plan_view.Name, str(e)
                ))
                continue

        # ── Sketch plane at this level's elevation ─────────────
        elev         = level.Elevation
        plane        = Plane.CreateByNormalAndOrigin(XYZ.BasisZ, XYZ(0.0, 0.0, elev))
        sketch_plane = SketchPlane.Create(doc, plane)

        # ── Gather boundary curves for all rooms ───────────────
        raw_curves = []
        for room in rooms:
            try:
                raw_curves.extend(
                    _get_boundary_curves(room, gross_ids, wall_map, doc)
                )
            except Exception:
                pass

        # ── Deduplicate and place boundary lines ───────────────
        # Boundaries must be placed BEFORE areas so areas can find
        # their enclosing loops.
        unique_curves = _deduplicate(raw_curves)

        for crv in unique_curves:
            try:
                crv_flat = _project_to_z(crv, elev)
                doc.Create.NewAreaBoundaryLine(sketch_plane, crv_flat, area_view)
                total_bounds += 1
            except Exception:
                pass

        # ── Create areas at room locations ─────────────────────
        for room in rooms:
            try:
                loc = room.Location
                if not isinstance(loc, LocationPoint):
                    continue

                pt = loc.Point
                new_area = doc.Create.NewArea(area_view, UV(pt.X, pt.Y))
                if new_area is None:
                    continue

                name_p = room.get_Parameter(BuiltInParameter.ROOM_NAME)
                num_p  = room.get_Parameter(BuiltInParameter.ROOM_NUMBER)

                area_name_p = new_area.get_Parameter(BuiltInParameter.ROOM_NAME)
                area_num_p  = new_area.get_Parameter(BuiltInParameter.ROOM_NUMBER)

                if area_name_p and name_p:
                    area_name_p.Set(name_p.AsString() or "")
                if area_num_p and num_p:
                    area_num_p.Set(num_p.AsString() or "")

                total_areas += 1

            except Exception:
                pass

    t.Commit()

    # ── Summary alert ──────────────────────────────────────────
    msg = (
        "Area Plans created successfully!\n\n"
        "  Area Scheme  :  {scheme}\n"
        "  Views processed  :  {views}\n"
        "  Boundary lines placed  :  {bounds}\n"
        "  Areas created  :  {areas}"
    ).format(
        scheme = selected_scheme_name,
        views  = len(selected_plan_views) - len(skipped_views),
        bounds = total_bounds,
        areas  = total_areas
    )
    if skipped_views:
        msg += "\n\nSkipped views (no placed rooms or view creation failed):\n"
        msg += "\n".join("  • " + n for n in skipped_views)

    forms.alert(msg, title="FLS Area Plan Creator – Done")

except Exception as ex:
    t.RollBack()
    forms.alert(
        "An error occurred and all changes were rolled back.\n\n"
        "Details:\n{}".format(str(ex)),
        title="FLS Area Plan Creator – Error"
    )
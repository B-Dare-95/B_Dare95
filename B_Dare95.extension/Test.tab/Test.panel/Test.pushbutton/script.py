# -*- coding: utf-8 -*-
"""
FLS Area Plan Creator  v2.0.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Creates Area Plans from selected Floor Plan views with automatic
NET / GROSS boundary logic driven by the custom FLS parameters.

Reads from rooms:
  FLS Occupancy         → copied verbatim onto the new Area
  FLS Area Measurement  → drives NET / GROSS boundary logic

Boundary rules:
  • NET  room  → boundary at interior finish face of wall
  • GROSS room → boundary at exterior (outer) face of wall
  • GROSS ↔ GROSS shared wall → boundary at wall centre-line

After all boundaries are placed duplicate / overlapping curves
are removed for a clean result.

Prerequisite:
  Run "FLS Parameter Creator" first so both parameters exist in
  the project before running this script.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Author  : B_Dare95
Version : 2.0.0
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

# ──────────────────────────────────────────────────────────────
# FLS PARAMETER NAMES  (must match exactly what the creator made)
# ──────────────────────────────────────────────────────────────
FLS_OCCUPANCY_PARAM    = "FLS Occupancy"       # descriptive occupancy label
FLS_AREA_MEAS_PARAM    = "FLS Area Measurement" # "NET" or "GROSS"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECTION 1 – PREFLIGHT: VERIFY FLS PARAMETERS EXIST
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _get_bound_param_names(doc):
    """Return a set of all parameter names currently bound in the project."""
    names = set()
    it = doc.ParameterBindings.ForwardIterator()
    while it.MoveNext():
        try:
            names.add(it.Key.Name)
        except Exception:
            pass
    return names


_bound_params = _get_bound_param_names(doc)
_missing = [
    p for p in (FLS_OCCUPANCY_PARAM, FLS_AREA_MEAS_PARAM)
    if p not in _bound_params
]

if _missing:
    forms.alert(
        u"The following required FLS parameters were not found in this project:\n\n"
        + u"\n".join(u"  \u2022  {}".format(p) for p in _missing)
        + u"\n\nPlease run the \u201cFLS Parameter Creator\u201d script first, "
          u"then re-run this tool.",
        title   = "FLS Area Plan Creator \u2013 Missing Parameters",
        exitscript = True
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECTION 2 – HELPER UTILITIES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _get_fls_param_value(element, param_name):
    """
    Read a custom parameter by name from any element.
    Returns the string value (upper-cased & stripped) or "".
    """
    p = element.LookupParameter(param_name)
    if p is None:
        return ""
    return (p.AsString() or "").strip().upper()


def _is_gross(room):
    """True when the room's FLS Area Measurement contains 'GROSS'."""
    return "GROSS" in _get_fls_param_value(room, FLS_AREA_MEAS_PARAM)


def _build_wall_room_map(rooms):
    """
    Returns  { wall_ElementId : [room, ...] }
    mapping every bounding wall to the rooms that share it.
    Uses the Finish-face boundary location to match NET boundaries.
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
                    if not any(r.Id == room.Id for r in wall_map[wid]):
                        wall_map[wid].append(room)
        except Exception:
            pass
    return wall_map


def _outer_face_curve(center_curve, wall, room_pt):
    """
    Offset a wall centre-line curve to the wall's exterior face
    (the face pointing away from room_pt).

    Translation distance = wall.Width / 2  (Revit internal feet).
    """
    try:
        half_width  = wall.Width / 2.0
        wall_normal = wall.Orientation          # unit vector ⊥ to wall axis

        wall_mid = center_curve.Evaluate(0.5, True)
        to_room  = XYZ(room_pt.X - wall_mid.X,
                       room_pt.Y - wall_mid.Y,
                       0.0)

        # Room is on the "positive-normal" side → exterior is the negated normal
        dot     = to_room.DotProduct(wall_normal)
        outward = wall_normal.Negate() if dot > 0 else wall_normal

        offset    = XYZ(outward.X * half_width,
                        outward.Y * half_width,
                        0.0)
        transform = Transform.CreateTranslation(offset)
        return center_curve.CreateTransformed(transform)

    except Exception:
        return center_curve          # safe fallback


def _get_boundary_curves(room, gross_ids, wall_map, doc):
    """
    Return a flat list of Curve objects for the room's area boundary.

    Decision tree per wall segment:
      NET  room             → Finish-face curve    (wall interior face)
      GROSS, GROSS neighbour → Centre-line curve   (shared wall midpoint)
      GROSS, other boundary  → Outer-face curve    (wall exterior face)
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

            # ── NET room  OR  non-wall segment (separator, etc.) ──
            if not gross or not isinstance(wall_elm, Wall):
                curves.append(seg.GetCurve())
                continue

            # ── GROSS room on a wall segment ──────────────────────
            try:
                center_crv = center_loops[li][si].GetCurve()
            except Exception:
                center_crv = seg.GetCurve()          # fallback to finish face

            adj_rooms = wall_map.get(wid, [])
            adj_gross = [r for r in adj_rooms
                         if r.Id != room.Id and r.Id in gross_ids]

            if adj_gross:
                # GROSS ↔ GROSS: shared wall → centre-line
                curves.append(center_crv)
            else:
                # GROSS facing exterior or NET neighbour → outer face
                if room_pt:
                    curves.append(_outer_face_curve(center_crv, wall_elm, room_pt))
                else:
                    curves.append(center_crv)

    return curves


def _project_to_z(curve, z):
    """Translate a curve vertically so it sits exactly at elevation z."""
    try:
        z_current = curve.GetEndPoint(0).Z
        if abs(z_current - z) < 1e-6:
            return curve
        t = Transform.CreateTranslation(XYZ(0.0, 0.0, z - z_current))
        return curve.CreateTransformed(t)
    except Exception:
        return curve


def _are_duplicates(c1, c2, tol=0.01):
    """True when two curves share the same endpoints (within tol, either order)."""
    try:
        s1, e1 = c1.GetEndPoint(0), c1.GetEndPoint(1)
        s2, e2 = c2.GetEndPoint(0), c2.GetEndPoint(1)
        close  = lambda a, b: a.DistanceTo(b) < tol
        return ((close(s1, s2) and close(e1, e2)) or
                (close(s1, e2) and close(e1, s2)))
    except Exception:
        return False


def _deduplicate(curves):
    """Remove exact duplicate curves (same two endpoints within tolerance)."""
    unique = []
    for c in curves:
        if not any(_are_duplicates(c, u) for u in unique):
            unique.append(c)
    return unique


def _copy_fls_params(src_room, tgt_area):
    """
    Copy both FLS custom parameter values from a Room onto the new Area.
    Both elements must have the parameters bound to their categories.
    """
    for pname in (FLS_OCCUPANCY_PARAM, FLS_AREA_MEAS_PARAM):
        src_p = src_room.LookupParameter(pname)
        tgt_p = tgt_area.LookupParameter(pname)
        if src_p and tgt_p:
            val = src_p.AsString() or ""
            try:
                tgt_p.Set(val)
            except Exception:
                pass


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECTION 3 – USER PROMPTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# ── 3a. Select Floor Plan views ────────────────────────────────
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
    title    = u"Step 1 of 2 \u2013 Select Floor Plan Views",
    width    = 460,
    multiselect   = True,
    button_name   = u"Next \u2192"
)
if not selected_view_names:
    script.exit()

selected_plan_views = [fp_dict[n] for n in selected_view_names]

# ── 3b. Select Area Scheme ─────────────────────────────────────
all_schemes = list(
    FilteredElementCollector(doc).OfClass(AreaScheme).ToElements()
)
if not all_schemes:
    forms.alert("No Area Schemes found in the project.", exitscript=True)

scheme_dict = {s.Name: s for s in all_schemes}

selected_scheme_name = forms.SelectFromList.show(
    sorted(scheme_dict.keys()),
    title      = u"Step 2 of 2 \u2013 Select Area Scheme",
    width      = 340,
    multiselect     = False,
    button_name     = "Create Area Plans"
)
if not selected_scheme_name:
    script.exit()

if isinstance(selected_scheme_name, list):
    selected_scheme_name = selected_scheme_name[0]

target_scheme = scheme_dict[selected_scheme_name]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECTION 4 – PRE-CACHE EXISTING AREA PLAN VIEWS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   level_ElementId → existing AreaPlan ViewPlan for the chosen scheme

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
# SECTION 5 – MAIN TRANSACTION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

total_areas   = 0
total_bounds  = 0
skipped_views = []

t = Transaction(doc, u"FLS Area Plans \u2013 Boundaries & Areas")
t.Start()

try:
    for plan_view in selected_plan_views:

        # ── Collect placed rooms (area > 0) ────────────────────
        rooms = [
            r for r in FilteredElementCollector(doc, plan_view.Id)
                         .OfCategory(BuiltInCategory.OST_Rooms)
                         .WhereElementIsNotElementType()
                         .ToElements()
            if r.Area > 0
        ]

        if not rooms:
            skipped_views.append(plan_view.Name + " (no placed rooms)")
            continue

        gross_ids = set(r.Id for r in rooms if _is_gross(r))
        wall_map  = _build_wall_room_map(rooms)

        # ── Resolve the target Area Plan view ──────────────────
        level = plan_view.GenLevel
        if level is None:
            skipped_views.append(plan_view.Name + " (no associated level)")
            continue

        if level.Id in existing_area_plans:
            area_view = existing_area_plans[level.Id]
        else:
            try:
                area_view = ViewPlan.CreateAreaPlan(
                    doc, target_scheme.Id, level.Id
                )
                existing_area_plans[level.Id] = area_view
            except Exception as ex:
                skipped_views.append(
                    u"{} (area view creation failed: {})".format(
                        plan_view.Name, str(ex)
                    )
                )
                continue

        # ── Sketch plane at this level's elevation ─────────────
        elev         = level.Elevation
        plane        = Plane.CreateByNormalAndOrigin(XYZ.BasisZ, XYZ(0.0, 0.0, elev))
        sketch_plane = SketchPlane.Create(doc, plane)

        # ── Collect boundary curves for every room ─────────────
        raw_curves = []
        for room in rooms:
            try:
                raw_curves.extend(
                    _get_boundary_curves(room, gross_ids, wall_map, doc)
                )
            except Exception:
                pass

        # ── Deduplicate then place boundary lines ──────────────
        # Boundaries MUST be placed before NewArea() so that Revit
        # can resolve the enclosing loop for each area tag point.
        unique_curves = _deduplicate(raw_curves)

        for crv in unique_curves:
            try:
                crv_flat = _project_to_z(crv, elev)
                doc.Create.NewAreaBoundaryLine(sketch_plane, crv_flat, area_view)
                total_bounds += 1
            except Exception:
                pass

        # ── Place areas, set name / number / FLS params ────────
        for room in rooms:
            try:
                loc = room.Location
                if not isinstance(loc, LocationPoint):
                    continue

                pt       = loc.Point
                new_area = doc.Create.NewArea(area_view, UV(pt.X, pt.Y))
                if new_area is None:
                    continue

                # ── Copy built-in Name & Number ────────────────
                name_p = room.get_Parameter(BuiltInParameter.ROOM_NAME)
                num_p  = room.get_Parameter(BuiltInParameter.ROOM_NUMBER)

                area_name_p = new_area.get_Parameter(BuiltInParameter.ROOM_NAME)
                area_num_p  = new_area.get_Parameter(BuiltInParameter.ROOM_NUMBER)

                if area_name_p and name_p:
                    area_name_p.Set(name_p.AsString() or "")
                if area_num_p and num_p:
                    area_num_p.Set(num_p.AsString() or "")

                # ── Copy FLS Occupancy & FLS Area Measurement ──
                _copy_fls_params(room, new_area)

                total_areas += 1

            except Exception:
                pass

    t.Commit()

    # ── Summary dialog ─────────────────────────────────────────
    msg = (
        u"Area Plans created successfully!\n\n"
        u"  Area Scheme           :  {scheme}\n"
        u"  Views processed       :  {views}\n"
        u"  Boundary lines placed :  {bounds}\n"
        u"  Areas created         :  {areas}"
    ).format(
        scheme = selected_scheme_name,
        views  = len(selected_plan_views) - len(skipped_views),
        bounds = total_bounds,
        areas  = total_areas
    )
    if skipped_views:
        msg += u"\n\nSkipped views:\n"
        msg += u"\n".join(u"  \u2022  " + n for n in skipped_views)

    forms.alert(msg, title=u"FLS Area Plan Creator \u2013 Done")

except Exception as ex:
    t.RollBack()
    forms.alert(
        u"An error occurred and all changes were rolled back.\n\nDetails:\n{}".format(
            str(ex)
        ),
        title=u"FLS Area Plan Creator \u2013 Error"
    )
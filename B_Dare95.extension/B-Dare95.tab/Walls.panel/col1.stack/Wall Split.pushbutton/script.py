# -*- coding: utf-8 -*-
"""
Split Walls at Columns
-----------------------
Scans the entire project for straight, basic walls that pass through
columns (both "Columns" and "Structural Columns" categories), where the
columns may live in the ACTIVE document and/or in LINKED documents.

Each wall is split so it STOPS at the column's near/far FACE along the
wall's run - no wall segment is created inside the column footprint.
A wall running through 2 columns therefore becomes 3 wall segments
(before col 1, between col 1 and col 2, after col 2).

HOSTED ELEMENTS (doors/windows/openings):
  Rather than rebuilding walls from scratch (which loses hosted
  elements), each surviving segment is created by literally COPYING
  the original wall in place (ElementTransformUtils.CopyElements),
  which also duplicates every element hosted on it. For each copy we
  then delete the duplicated hosted elements that don't belong to that
  segment (based on their position along the wall axis) and resize
  the copy's curve down to the segment's extents. This means:
    - Type, all instance parameters, structural usage, flip state,
      etc. come along automatically (no manual parameter copying).
    - A door/window ends up on exactly the one segment it actually
      sits on.
    - A hosted element that happens to sit inside a column's footprint
      (i.e. in a gap, not in any surviving segment) cannot be
      preserved - it is reported as a warning instead of silently
      vanishing, so it can be handled manually.

ASSUMPTIONS / LIMITATIONS (read before running):
  - Only straight (Line-based) walls of WallKind.Basic are processed.
    Curved walls, stacked walls, and curtain walls are skipped and
    reported at the end.
  - The column's face positions are derived from its bounding box (all
    8 corners transformed into host coordinates, so rotated/mirrored
    links are handled), projected onto the wall's axis.
  - A column only affects a wall if its footprint's perpendicular
    projection overlaps the wall's thickness band (+ PERP_TOL slack).
  - Run this on a saved/backed-up model. The whole operation is
    wrapped in a single TransactionGroup so it can be undone in one
    Ctrl+Z if needed.

Tested target: pyRevit / IronPython 2.7, Revit 2019-2027 API surface.
"""

__title__ = 'Split Walls\nat Columns'
__author__ = 'B-Dare95'

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('System')

from System.Collections.Generic import List

from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory,
    Wall, WallKind, RevitLinkInstance, Transform,
    Line, XYZ, LocationCurve, ElementId,
    ElementTransformUtils, Transaction, TransactionGroup
)

from pyrevit import revit, forms, script

doc = revit.doc
output = script.get_output()

# ---------------------------------------------------------------------------
# Tunable tolerances (feet, since Revit's internal units are always feet)
# ---------------------------------------------------------------------------
Z_OVERLAP_TOL = 0.5          # vertical overlap tolerance between wall & column
PERP_TOL = 0.5               # extra slack added to wall half-thickness when
                              # checking whether a column's footprint reaches
                              # the wall band
MIN_SEGMENT_LENGTH = 0.1     # drop wall segments shorter than this
MIN_SPLIT_SPACING = 0.5      # merge column intervals closer than this together
HOSTED_U_TOL = 0.05          # slack (ft) when deciding which segment a hosted
                              # element belongs to


def eid_str(eid):
    """Version-safe ElementId -> string for reporting."""
    try:
        return str(eid.Value)
    except AttributeError:
        return str(eid.IntegerValue)


# ---------------------------------------------------------------------------
# 1. Collect all columns (active doc + all loaded links), both categories
# ---------------------------------------------------------------------------
COLUMN_CATS = [BuiltInCategory.OST_Columns, BuiltInCategory.OST_StructuralColumns]


def collect_columns_from_doc(source_doc, transform):
    """Returns list of dicts: {corners (8 XYZ in host coords), z_min, z_max,
    elem, source_doc}"""
    results = []
    for bic in COLUMN_CATS:
        collector = FilteredElementCollector(source_doc)\
            .OfCategory(bic).WhereElementIsNotElementType()
        for elem in collector:
            bbox = elem.get_BoundingBox(None)
            if bbox is None:
                continue
            mn, mx = bbox.Min, bbox.Max
            corners_local = [
                XYZ(mn.X, mn.Y, mn.Z), XYZ(mx.X, mn.Y, mn.Z),
                XYZ(mn.X, mx.Y, mn.Z), XYZ(mx.X, mx.Y, mn.Z),
                XYZ(mn.X, mn.Y, mx.Z), XYZ(mx.X, mn.Y, mx.Z),
                XYZ(mn.X, mx.Y, mx.Z), XYZ(mx.X, mx.Y, mx.Z),
            ]
            corners_host = [transform.OfPoint(c) for c in corners_local]
            z_values = [c.Z for c in corners_host]
            results.append({
                'corners': corners_host,
                'z_min': min(z_values),
                'z_max': max(z_values),
                'elem': elem,
                'source_doc': source_doc,
            })
    return results


def collect_all_columns(host_doc):
    all_columns = collect_columns_from_doc(host_doc, Transform.Identity)

    link_instances = FilteredElementCollector(host_doc)\
        .OfClass(RevitLinkInstance).ToElements()

    skipped_links = []
    for link_inst in link_instances:
        link_doc = link_inst.GetLinkDocument()
        if link_doc is None:
            skipped_links.append(link_inst.Name)
            continue
        transform = link_inst.GetTotalTransform()
        all_columns.extend(collect_columns_from_doc(link_doc, transform))

    return all_columns, skipped_links


# ---------------------------------------------------------------------------
# 2. For each straight basic wall, find the column-occupied intervals
#    (in wall-axis parameter space) that must become gaps
# ---------------------------------------------------------------------------
def get_wall_z_range(wall):
    bbox = wall.get_BoundingBox(None)
    if bbox is None:
        return None, None
    return bbox.Min.Z, bbox.Max.Z


def find_wall_gaps(wall, columns):
    """Returns (merged_intervals, reason). merged_intervals is a sorted list
    of [u_min, u_max] (floats, in the wall's own 0..length parameter space)
    representing column footprints to be cut out of the wall."""
    loc = wall.Location
    if not isinstance(loc, LocationCurve):
        return None, 'no LocationCurve'

    curve = loc.Curve
    if not isinstance(curve, Line):
        return None, 'not a straight (Line) wall'

    if wall.WallType.Kind != WallKind.Basic:
        return None, 'not a Basic wall (stacked/curtain)'

    p0 = curve.GetEndPoint(0)
    p1 = curve.GetEndPoint(1)
    length = curve.Length
    direction = (p1 - p0).Normalize()
    normal = XYZ(-direction.Y, direction.X, 0.0)

    wall_z_min, wall_z_max = get_wall_z_range(wall)
    if wall_z_min is None:
        return None, 'could not read wall bounding box'

    half_thickness = wall.Width / 2.0
    band = half_thickness + PERP_TOL

    raw_intervals = []
    for col in columns:
        if col['z_max'] < wall_z_min - Z_OVERLAP_TOL:
            continue
        if col['z_min'] > wall_z_max + Z_OVERLAP_TOL:
            continue

        us, vs = [], []
        for c in col['corners']:
            vec = c - p0
            us.append(vec.DotProduct(direction))
            vs.append(vec.DotProduct(normal))

        v_min, v_max = min(vs), max(vs)
        if v_max < -band or v_min > band:
            continue  # column footprint never reaches the wall's band

        u_min, u_max = max(min(us), 0.0), min(max(us), length)
        if u_max - u_min < 0.01:
            continue  # negligible / effectively outside the wall run

        raw_intervals.append((u_min, u_max))

    if not raw_intervals:
        return [], None

    raw_intervals.sort()
    merged = [list(raw_intervals[0])]
    for a, b in raw_intervals[1:]:
        if a <= merged[-1][1] + MIN_SPLIT_SPACING:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])

    return merged, None


def gaps_to_segments(merged_intervals, length):
    """Complement of the merged column intervals within [0, length]."""
    segments = []
    prev_end = 0.0
    for a, b in merged_intervals:
        if a - prev_end > MIN_SEGMENT_LENGTH:
            segments.append((prev_end, a))
        prev_end = max(prev_end, b)
    if length - prev_end > MIN_SEGMENT_LENGTH:
        segments.append((prev_end, length))
    return segments


# ---------------------------------------------------------------------------
# 3. Hosted-element helpers
# ---------------------------------------------------------------------------
def get_hosted_u_positions(doc, host_wall_id, p0, direction):
    """Find elements directly hosted on host_wall_id (doors, windows,
    openings, etc. - anything with a .Host pointing at this wall) and
    return [(element_id, u_position_along_wall_axis), ...]."""
    host_wall = doc.GetElement(host_wall_id)
    dependent_ids = host_wall.GetDependentElements(None)
    result = []
    for eid in dependent_ids:
        el = doc.GetElement(eid)
        if el is None:
            continue
        host = getattr(el, 'Host', None)
        if host is None or host.Id != host_wall_id:
            continue

        pt = None
        loc_el = el.Location
        if loc_el is not None and hasattr(loc_el, 'Point'):
            pt = loc_el.Point
        if pt is None:
            bbox = el.get_BoundingBox(None)
            if bbox is not None:
                pt = (bbox.Min + bbox.Max) * 0.5
        if pt is None:
            continue

        u = (pt - p0).DotProduct(direction)
        result.append((eid, u))
    return result


def u_in_segment(u, s, e):
    return (s - HOSTED_U_TOL) <= u <= (e + HOSTED_U_TOL)


# ---------------------------------------------------------------------------
# 4. Rebuild a wall as the surviving segments (gaps between column faces)
#    by copying the wall in place per segment, keeping only the hosted
#    duplicates that belong to that segment.
# ---------------------------------------------------------------------------
def split_wall(doc, wall, segments):
    curve = wall.Location.Curve
    p0 = curve.GetEndPoint(0)
    p1 = curve.GetEndPoint(1)
    direction = (p1 - p0).Normalize()
    wall_id = wall.Id

    # Hosted elements on the ORIGINAL wall, checked once so we can warn
    # about any that don't land inside ANY surviving segment (i.e. sit
    # inside a column footprint and would otherwise be silently lost).
    original_hosted = get_hosted_u_positions(doc, wall_id, p0, direction)
    unrecoverable = []
    for eid, u in original_hosted:
        if not any(u_in_segment(u, s, e) for (s, e) in segments):
            unrecoverable.append(eid)

    new_walls = []
    id_list = List[ElementId]([wall_id])

    for (s, e) in segments:
        copied_ids = ElementTransformUtils.CopyElements(doc, id_list, XYZ(0, 0, 0))
        new_wall_id = copied_ids[0]
        new_wall = doc.GetElement(new_wall_id)

        # Hosted duplicates on this copy - still at the ORIGINAL wall's
        # world position at this point, since translation was (0,0,0)
        # and the copy's curve hasn't been resized yet.
        hosted_on_copy = get_hosted_u_positions(doc, new_wall_id, p0, direction)
        for eid, u in hosted_on_copy:
            if not u_in_segment(u, s, e):
                doc.Delete(eid)

        seg_start = p0 + direction.Multiply(s)
        seg_end = p0 + direction.Multiply(e)
        new_wall.Location.Curve = Line.CreateBound(seg_start, seg_end)

        new_walls.append(new_wall)

    doc.Delete(wall_id)
    doc.Regenerate()

    return new_walls, unrecoverable


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    all_columns, skipped_links = collect_all_columns(doc)
    if not all_columns:
        forms.alert('No columns found in the active document or any loaded '
                     'links (checked "Columns" and "Structural Columns" '
                     'categories). Nothing to do.', title='Split Walls at Columns')
        return

    walls = FilteredElementCollector(doc).OfClass(Wall)\
        .WhereElementIsNotElementType().ToElements()

    plan = []       # (wall, [segments])
    skipped = []    # (wall_id, reason)

    for wall in walls:
        merged, reason = find_wall_gaps(wall, all_columns)
        if reason:
            skipped.append((wall.Id, reason))
            continue
        if not merged:
            continue  # no column crosses this wall

        length = wall.Location.Curve.Length
        segments = gaps_to_segments(merged, length)
        if not segments:
            skipped.append((wall.Id, 'wall fully consumed by column(s)'))
            continue
        plan.append((wall, segments))

    if not plan:
        msg = 'No walls found that cross a column on their run.'
        if skipped:
            msg += ' {} wall(s) were skipped (curved/stacked/curtain or ' \
                   'unreadable geometry).'.format(len(skipped))
        forms.alert(msg, title='Split Walls at Columns')
        return

    total_new = sum(len(segs) for _, segs in plan)
    summary = (
        '{} wall(s) will be split into {} wall segment(s) total, based on '
        '{} column(s) found (active + linked).\n\n'
        '{} wall(s) skipped (curved/stacked/curtain/unreadable).\n'
        '{} linked file(s) skipped (not loaded).\n\n'
        'Proceed?'
    ).format(len(plan), total_new, len(all_columns), len(skipped), len(skipped_links))

    if not forms.alert(summary, title='Split Walls at Columns', yes=True, no=True):
        script.exit()

    tg = TransactionGroup(doc, 'Split Walls at Columns')
    tg.Start()

    done = 0
    errors = []
    all_unrecoverable = []
    for wall, segments in plan:
        t = Transaction(doc, 'Split wall {}'.format(eid_str(wall.Id)))
        t.Start()
        try:
            _, unrecoverable = split_wall(doc, wall, segments)
            t.Commit()
            done += 1
            all_unrecoverable.extend(unrecoverable)
        except Exception as ex:
            t.RollBack()
            errors.append((wall.Id, str(ex)))

    tg.Assimilate()

    output.print_md('### Split Walls at Columns - Done')
    output.print_md('- Walls split: **{}** / {}'.format(done, len(plan)))
    if errors:
        output.print_md('- Errors:')
        for wid, msg in errors:
            output.print_md('  - Wall {}: {}'.format(eid_str(wid), msg))
    if all_unrecoverable:
        output.print_md('- **Hosted elements that could NOT be preserved** '
                         '(they sit inside a column footprint, not on any '
                         'surviving segment) - please re-place manually:')
        for eid in all_unrecoverable:
            output.print_md('  - Element {}'.format(eid_str(eid)))
    if skipped:
        output.print_md('- Skipped walls: {}'.format(len(skipped)))
    if skipped_links:
        output.print_md('- Unloaded links skipped: {}'.format(', '.join(skipped_links)))


if __name__ == '__main__':
    main()
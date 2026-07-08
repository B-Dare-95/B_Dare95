# -*- coding: utf-8 -*-
"""
Split Walls at Columns - Select Only
--------------------------------------
    1. User draws a rectangle (walls only are picked).
    2. The script counts, AFTER selection, how many of the picked walls
       actually need splitting and shows a Proceed / Cancel prompt.
    3. If the user proceeds, those walls are split (columns can be in
       the active document and/or linked documents, categories
       "Columns" and "Structural Columns").
    4. Once done, the user is asked to select again or exit.
"""

__title__ = 'Split Walls\nat Columns\n(Select)'
__author__ = 'B-Dare95'

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('System')

from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory, BuiltInParameter,
    Wall, WallKind, RevitLinkInstance, Transform,
    Line, XYZ, LocationCurve, FamilyInstance,
    Transaction, TransactionGroup
)
from Autodesk.Revit.DB.Structure import StructuralType
from Autodesk.Revit.UI.Selection import ISelectionFilter

from pyrevit import revit, forms, script

doc = revit.doc
uidoc = revit.uidoc
output = script.get_output()

# ---------------------------------------------------------------------------
# Tunable tolerances (feet, since Revit's internal units are always feet)
# ---------------------------------------------------------------------------
Z_OVERLAP_TOL = 0.5
PERP_TOL = 0.5
MIN_SEGMENT_LENGTH = 0.1
MIN_SPLIT_SPACING = 0.5
HOSTED_U_TOL = 0.05


def eid_str(eid):
    try:
        return str(eid.Value)
    except AttributeError:
        return str(eid.IntegerValue)


# ---------------------------------------------------------------------------
# 1. Collect all columns (active doc + all loaded links), both categories
#    (done once, reused for every selection round)
# ---------------------------------------------------------------------------
COLUMN_CATS = [BuiltInCategory.OST_Columns, BuiltInCategory.OST_StructuralColumns]


def collect_columns_from_doc(source_doc, transform):
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
# ---------------------------------------------------------------------------
def get_wall_z_range(wall):
    bbox = wall.get_BoundingBox(None)
    if bbox is None:
        return None, None
    return bbox.Min.Z, bbox.Max.Z


def find_wall_gaps(wall, columns):
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
            continue

        u_min, u_max = max(min(us), 0.0), min(max(us), length)
        if u_max - u_min < 0.01:
            continue

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
    segments = []
    prev_end = 0.0
    for a, b in merged_intervals:
        if a - prev_end > MIN_SEGMENT_LENGTH:
            segments.append((prev_end, a))
        prev_end = max(prev_end, b)
    if length - prev_end > MIN_SEGMENT_LENGTH:
        segments.append((prev_end, length))
    return segments


def u_in_segment(u, s, e):
    return (s - HOSTED_U_TOL) <= u <= (e + HOSTED_U_TOL)


# ---------------------------------------------------------------------------
# 3. Parameter copying helpers
# ---------------------------------------------------------------------------
WALL_COPY_PARAMS = [
    BuiltInParameter.WALL_BASE_CONSTRAINT,
    BuiltInParameter.WALL_BASE_OFFSET,
    BuiltInParameter.WALL_HEIGHT_TYPE,        # top constraint
    BuiltInParameter.WALL_TOP_OFFSET,
    BuiltInParameter.WALL_USER_HEIGHT_PARAM,  # unconnected height
    BuiltInParameter.WALL_KEY_REF_PARAM,      # location line
    BuiltInParameter.WALL_STRUCTURAL_USAGE_PARAM,
]

HOSTED_COPY_PARAMS = [
    BuiltInParameter.INSTANCE_SILL_HEIGHT_PARAM,
    BuiltInParameter.INSTANCE_HEAD_HEIGHT_PARAM,
    BuiltInParameter.ALL_MODEL_MARK,
    BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS,
]


def copy_params(src, dst, param_list):
    for bip in param_list:
        try:
            sp = src.get_Parameter(bip)
            dp = dst.get_Parameter(bip)
            if sp is None or dp is None or dp.IsReadOnly:
                continue
            storage = sp.StorageType.ToString()
            if storage == 'Double':
                dp.Set(sp.AsDouble())
            elif storage == 'Integer':
                dp.Set(sp.AsInteger())
            elif storage == 'ElementId':
                dp.Set(sp.AsElementId())
            elif storage == 'String':
                v = sp.AsString()
                if v is not None:
                    dp.Set(v)
        except Exception:
            continue


# ---------------------------------------------------------------------------
# 4. Hosted element helpers (doors / windows - FamilyInstance only)
# ---------------------------------------------------------------------------
def get_hosted_family_instances(doc, wall):
    hosted = []
    for eid in wall.GetDependentElements(None):
        el = doc.GetElement(eid)
        if isinstance(el, FamilyInstance):
            host = el.Host
            if host is not None and host.Id == wall.Id:
                hosted.append(el)
    return hosted


def recreate_hosted_instance(doc, old_instance, new_host_wall):
    symbol = old_instance.Symbol
    if not symbol.IsActive:
        symbol.Activate()
        doc.Regenerate()

    point = old_instance.Location.Point

    new_instance = doc.Create.NewFamilyInstance(
        point, symbol, new_host_wall, StructuralType.NonStructural)
    doc.Regenerate()

    copy_params(old_instance, new_instance, HOSTED_COPY_PARAMS)

    try:
        if old_instance.FacingFlipped != new_instance.FacingFlipped:
            new_instance.flipFacing()
    except Exception:
        pass
    try:
        if old_instance.HandFlipped != new_instance.HandFlipped:
            new_instance.flipHand()
    except Exception:
        pass

    return new_instance


# ---------------------------------------------------------------------------
# 5. Rebuild a wall as the surviving segments (gaps between column faces)
# ---------------------------------------------------------------------------
def split_wall(doc, wall, segments):
    curve = wall.Location.Curve
    p0 = curve.GetEndPoint(0)
    p1 = curve.GetEndPoint(1)
    direction = (p1 - p0).Normalize()

    wall_type_id = wall.WallType.Id
    level_id = wall.LevelId
    was_flipped = wall.Flipped

    height_param = wall.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM)
    height = height_param.AsDouble() if height_param and height_param.HasValue else 10.0

    offset_param = wall.get_Parameter(BuiltInParameter.WALL_BASE_OFFSET)
    base_offset = offset_param.AsDouble() if offset_param and offset_param.HasValue else 0.0

    struct_param = wall.get_Parameter(BuiltInParameter.WALL_STRUCTURAL_USAGE_PARAM)
    is_structural = bool(struct_param and struct_param.HasValue and struct_param.AsInteger() != 0)

    hosted = get_hosted_family_instances(doc, wall)
    hosted_u = []
    for inst in hosted:
        pt = inst.Location.Point
        u = (pt - p0).DotProduct(direction)
        hosted_u.append((inst, u))

    unrecoverable = []
    for inst, u in hosted_u:
        if not any(u_in_segment(u, s, e) for (s, e) in segments):
            unrecoverable.append(inst.Id)

    new_walls = []
    for (s, e) in segments:
        seg_start = p0 + direction.Multiply(s)
        seg_end = p0 + direction.Multiply(e)
        seg_curve = Line.CreateBound(seg_start, seg_end)

        new_wall = Wall.Create(doc, seg_curve, wall_type_id, level_id,
                                height, base_offset, was_flipped, is_structural)
        doc.Regenerate()
        copy_params(wall, new_wall, WALL_COPY_PARAMS)

        for inst, u in hosted_u:
            if u_in_segment(u, s, e):
                recreate_hosted_instance(doc, inst, new_wall)

        new_walls.append(new_wall)

    # Deleting the original wall also removes its now-superseded hosted
    # instances (they're dependent elements of the wall being deleted).
    doc.Delete(wall.Id)
    doc.Regenerate()

    return new_walls, unrecoverable


# ---------------------------------------------------------------------------
# 6. Rectangle selection (walls only)
# ---------------------------------------------------------------------------
class WallOnlyFilter(ISelectionFilter):
    def AllowElement(self, elem):
        return isinstance(elem, Wall)

    def AllowReference(self, reference, point):
        return False


def pick_walls_by_rectangle(uidoc):
    try:
        picked = uidoc.Selection.PickElementsByRectangle(
            WallOnlyFilter(),
            'Draw a rectangle around the walls to process (only walls will be picked)')
    except Exception:
        return None
    return list(picked)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def process_selected_walls(all_columns):
    """One full round: pick -> count -> confirm -> split. Returns True to
    keep looping (select again), False to stop the script."""

    picked = pick_walls_by_rectangle(uidoc)
    if picked is None:
        return False  # user hit Esc during the pick - stop the script

    if not picked:
        return forms.alert(
            'No walls were picked. Select more walls?',
            title='Split Walls at Columns', yes=True, no=True)

    plan = []
    skipped = []
    for wall in picked:
        merged, reason = find_wall_gaps(wall, all_columns)
        if reason:
            skipped.append((wall.Id, reason))
            continue
        if not merged:
            continue
        length = wall.Location.Curve.Length
        segments = gaps_to_segments(merged, length)
        if not segments:
            skipped.append((wall.Id, 'wall fully consumed by column(s)'))
            continue
        plan.append((wall, segments))

    if not plan:
        msg = 'None of the {} selected wall(s) need splitting.'.format(len(picked))
        if skipped:
            msg += ' ({} skipped: curved/stacked/curtain or fully consumed.)'\
                .format(len(skipped))
        msg += '\n\nSelect more walls?'
        return forms.alert(msg, title='Split Walls at Columns', yes=True, no=True)

    total_new = sum(len(segs) for _, segs in plan)
    summary = (
        'Selected {} wall(s).\n'
        '{} of them need splitting, into {} wall segment(s) total.\n'
        '{} skipped (curved/stacked/curtain/unreadable/no column).\n\n'
        'Proceed with the split?'
    ).format(len(picked), len(plan), total_new, len(skipped))

    if not forms.alert(summary, title='Split Walls at Columns', yes=True, no=True):
        return forms.alert(
            'Split cancelled. Select more walls?',
            title='Split Walls at Columns', yes=True, no=True)

    tg = TransactionGroup(doc, 'Split Walls at Columns (Selection)')
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

    output.print_md('### Split Walls at Columns - Round Complete')
    output.print_md('- Walls split: **{}** / {}'.format(done, len(plan)))
    if errors:
        output.print_md('- Walls skipped due to errors (no changes made to these):')
        for wid, msg in errors:
            output.print_md('  - Wall {}: {}'.format(eid_str(wid), msg))
    if all_unrecoverable:
        output.print_md('- **Hosted elements that could NOT be preserved** '
                         '(inside a column footprint) - please re-place manually:')
        for eid in all_unrecoverable:
            output.print_md('  - Element {}'.format(eid_str(eid)))
    if skipped:
        output.print_md('- Skipped in this selection: {}'.format(len(skipped)))

    return forms.alert(
        'Done. Select more walls to process?',
        title='Split Walls at Columns', yes=True, no=True)


def main():
    all_columns, skipped_links = collect_all_columns(doc)
    if not all_columns:
        forms.alert('No columns found in the active document or any loaded '
                     'links (checked "Columns" and "Structural Columns" '
                     'categories). Nothing to do.', title='Split Walls at Columns')
        return
    if skipped_links:
        output.print_md('Unloaded links skipped: {}'.format(', '.join(skipped_links)))

    while True:
        keep_going = process_selected_walls(all_columns)
        if not keep_going:
            break


if __name__ == '__main__':
    main()
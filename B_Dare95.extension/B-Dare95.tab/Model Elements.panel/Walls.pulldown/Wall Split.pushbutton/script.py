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
    Wall, WallKind, WallUtils, RevitLinkInstance, Transform,
    Line, XYZ, LocationCurve, LocationPoint, FamilyInstance, Opening,
    ElementId, ElementTransformUtils,
    Transaction, TransactionGroup
)
from Autodesk.Revit.UI.Selection import ISelectionFilter

from System.Collections.Generic import List

from pyrevit import revit, forms

doc = revit.doc
uidoc = revit.uidoc

# Notes gathered at startup, surfaced in the first completion dialog so the
# pyRevit output console never has to open.
STARTUP_NOTES = []

# ---------------------------------------------------------------------------
# Tunable tolerances (feet, since Revit's internal units are always feet)
# ---------------------------------------------------------------------------
Z_OVERLAP_TOL = 0.5
PERP_TOL = 0.5
MIN_SEGMENT_LENGTH = 0.1
MIN_SPLIT_SPACING = 0.5
HOSTED_U_TOL = 0.05

# How much detail the completion dialog will list before truncating
MAX_REPORT_ITEMS = 10
MAX_REPORT_IDS = 30


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
# 3. Insert (door / window / opening) helpers
#
#    Inserts are never re-created. They ride along with the wall copy. These
#    helpers only decide WHICH copy each insert belongs to, so the copies that
#    do not own it can have it removed before they are shortened.
# ---------------------------------------------------------------------------
FIT_TOL = 0.01   # ft - slack allowed when checking an insert fits a segment


def _bip(name):
    return getattr(BuiltInParameter, name, None)


INSERT_WIDTH_PARAMS = [b for b in (
    _bip('DOOR_WIDTH'),
    _bip('WINDOW_WIDTH'),
    _bip('FAMILY_WIDTH_PARAM'),
    _bip('GENERIC_WIDTH'),
) if b is not None]


def get_wall_inserts(doc, wall):
    """Every door / window / opening actually hosted BY this wall."""
    inserts = []
    for eid in wall.GetDependentElements(None):
        el = doc.GetElement(eid)
        if el is None:
            continue
        if not isinstance(el, (FamilyInstance, Opening)):
            continue
        try:
            host = el.Host
        except Exception:
            continue
        if host is not None and host.Id == wall.Id:
            inserts.append(el)
    return inserts


def insert_u(el, p0, direction):
    """Position of an insert along the wall's location curve, or None."""
    loc = el.Location
    if isinstance(loc, LocationPoint):
        return (loc.Point - p0).DotProduct(direction)
    bbox = el.get_BoundingBox(None)
    if bbox is None:
        return None
    center = (bbox.Min + bbox.Max).Multiply(0.5)
    return (center - p0).DotProduct(direction)


def insert_width(el):
    """Width of an insert along the wall, or None if it can't be read."""
    sources = [el]
    symbol = getattr(el, 'Symbol', None)
    if symbol is not None:
        sources.append(symbol)
    for src in sources:
        for bip in INSERT_WIDTH_PARAMS:
            try:
                p = src.get_Parameter(bip)
            except Exception:
                continue
            if p is None or not p.HasValue:
                continue
            if p.StorageType.ToString() != 'Double':
                continue
            v = p.AsDouble()
            if v > 0:
                return v
    return None


def owning_segment_index(u, width, segments):
    """Index of the segment that keeps this insert, or None if no segment can.

    An insert is owned by the segment its insertion point falls in, but only
    if the whole insert fits inside that segment. An insert straddling a
    column face cannot be cut out of the shortened wall - Revit would raise
    'Can't cut instance out of Wall' - so it is dropped and reported instead.
    """
    for i, (s, e) in enumerate(segments):
        if not u_in_segment(u, s, e):
            continue
        if width:
            half = width / 2.0
            if (u - half) < (s - FIT_TOL) or (u + half) > (e + FIT_TOL):
                return None
        return i
    return None


# ---------------------------------------------------------------------------
# 4. Rebuild a wall as the surviving segments (gaps between column faces)
#
#    Strategy: DO NOT create empty walls and re-place the inserts. Instead
#    copy the original wall once per surviving segment. A copied wall carries
#    every hosted element with it, at its exact original position, with all
#    instance data intact. Each copy then explicitly deletes the inserts it
#    does not own, and only afterwards is shortened to its segment.
# ---------------------------------------------------------------------------
END_TOL = 1e-6


def split_wall(doc, wall, segments):
    curve = wall.Location.Curve
    p0 = curve.GetEndPoint(0)
    p1 = curve.GetEndPoint(1)
    length = curve.Length
    direction = (p1 - p0).Normalize()

    # Remember whether the original wall allowed joins at its real ends, so
    # the outermost segments can be restored to the same state.
    try:
        orig_join_start = WallUtils.IsWallJoinAllowedAtEnd(wall, 0)
        orig_join_end = WallUtils.IsWallJoinAllowedAtEnd(wall, 1)
    except Exception:
        orig_join_start = True
        orig_join_end = True

    # Decide up front which segment owns each insert. Anything no segment can
    # keep (sits inside a column footprint, or straddles a column face) is
    # reported so it can be re-placed by hand.
    unrecoverable = []
    for el in get_wall_inserts(doc, wall):
        u = insert_u(el, p0, direction)
        if u is None:
            continue
        if owning_segment_index(u, insert_width(el), segments) is None:
            unrecoverable.append(el.Id)

    source_ids = List[ElementId]()
    source_ids.Add(wall.Id)

    new_walls = []
    for seg_index, (s, e) in enumerate(segments):
        copied_ids = ElementTransformUtils.CopyElements(doc, source_ids, XYZ.Zero)
        doc.Regenerate()

        new_wall = None
        for cid in copied_ids:
            candidate = doc.GetElement(cid)
            if isinstance(candidate, Wall):
                new_wall = candidate
                break
        if new_wall is None:
            raise Exception('Copy of wall {} produced no wall element'
                            .format(eid_str(wall.Id)))

        # The copy carries EVERY insert from the original, so before it is
        # shortened it must give up the ones this segment does not own.
        # Leaving them attached is what makes Revit raise "Instance(s) of ...
        # not cutting anything" - an error, not a suppressible warning - once
        # the wall no longer passes through them.
        to_delete = List[ElementId]()
        for el in get_wall_inserts(doc, new_wall):
            u = insert_u(el, p0, direction)
            if u is None:
                continue
            if owning_segment_index(u, insert_width(el), segments) != seg_index:
                to_delete.Add(el.Id)
        if to_delete.Count > 0:
            doc.Delete(to_delete)
            doc.Regenerate()

        # A copy dropped on top of the original auto-joins to the same
        # neighbouring walls the original touches. Joined ends resist being
        # moved, and the curve assignment below would silently revert.
        # Break the joins first, restore them after the original is gone.
        WallUtils.DisallowWallJoinAtEnd(new_wall, 0)
        WallUtils.DisallowWallJoinAtEnd(new_wall, 1)

        seg_start = p0 + direction.Multiply(s)
        seg_end = p0 + direction.Multiply(e)

        # Bind Location to a local first - assigning through the property
        # chain directly does not reliably stick in IronPython.
        loc = new_wall.Location
        loc.Curve = Line.CreateBound(seg_start, seg_end)
        doc.Regenerate()

        new_walls.append((new_wall,
                          abs(s) < END_TOL,
                          abs(e - length) < END_TOL))

    # Original wall (and anything still hosted inside a column gap) removed.
    doc.Delete(wall.Id)
    doc.Regenerate()

    # Restore joining. Interior ends (the new ends at column faces) are always
    # re-enabled so they miter correctly against whatever is adjacent; the
    # outer ends inherit the original wall's setting.
    result_walls = []
    for new_wall, at_orig_start, at_orig_end in new_walls:
        try:
            if (not at_orig_start) or orig_join_start:
                WallUtils.AllowWallJoinAtEnd(new_wall, 0)
            if (not at_orig_end) or orig_join_end:
                WallUtils.AllowWallJoinAtEnd(new_wall, 1)
        except Exception:
            pass
        result_walls.append(new_wall)
    doc.Regenerate()

    return result_walls, unrecoverable


# ---------------------------------------------------------------------------
# 5. Rectangle selection (walls only)
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

    lines = ['Round complete.',
             'Walls split: {} / {}'.format(done, len(plan))]
    if skipped:
        lines.append('Skipped in this selection: {}'.format(len(skipped)))

    if errors:
        lines.append('')
        lines.append('Walls skipped due to errors (no changes made to these):')
        for wid, msg in errors[:MAX_REPORT_ITEMS]:
            lines.append('  Wall {}: {}'.format(eid_str(wid), msg))
        if len(errors) > MAX_REPORT_ITEMS:
            lines.append('  ... and {} more'.format(len(errors) - MAX_REPORT_ITEMS))

    if all_unrecoverable:
        lines.append('')
        lines.append('Hosted elements that could NOT be preserved (inside a '
                     'column footprint, or straddling a column face) - '
                     'please re-place manually:')
        shown = [eid_str(e) for e in all_unrecoverable[:MAX_REPORT_IDS]]
        lines.append('  ' + ', '.join(shown))
        if len(all_unrecoverable) > MAX_REPORT_IDS:
            lines.append('  ... and {} more'
                         .format(len(all_unrecoverable) - MAX_REPORT_IDS))

    if STARTUP_NOTES:
        lines.append('')
        lines.extend(STARTUP_NOTES)
        del STARTUP_NOTES[:]

    lines.append('')
    lines.append('Select more walls to process?')

    return forms.alert('\n'.join(lines),
                       title='Split Walls at Columns', yes=True, no=True)


def main():
    all_columns, skipped_links = collect_all_columns(doc)
    if not all_columns:
        forms.alert('No columns found in the active document or any loaded '
                     'links (checked "Columns" and "Structural Columns" '
                     'categories). Nothing to do.', title='Split Walls at Columns')
        return
    if skipped_links:
        STARTUP_NOTES.append('Unloaded links skipped: {}'
                             .format(', '.join(skipped_links)))

    while True:
        keep_going = process_selected_walls(all_columns)
        if not keep_going:
            break


if __name__ == '__main__':
    main()
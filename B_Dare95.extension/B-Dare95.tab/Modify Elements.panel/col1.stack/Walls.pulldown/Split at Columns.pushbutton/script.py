# -*- coding: utf-8 -*-
__doc__ = """__________________________________________________
Description:

Cuts walls where columns sit in them, so each wall becomes separate pieces that stop at the column faces.
Columns and structural columns from your model and all loaded links are used.
__________________________________________________
How-to:

-> Click on the button
-> Draw a box around the walls to process
-> Check how many walls will be split and click Yes
-> Choose to select more walls or stop
__________________________________________________
Author: Mohamed Bedair"""


__author__ = 'B-Dare95'

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('System')

from Autodesk.Revit.DB import (FilteredElementCollector, BuiltInCategory,
                               BuiltInParameter, Wall, WallKind, WallUtils,
                               RevitLinkInstance, Transform, Line, XYZ,
                               LocationCurve, LocationPoint, FamilyInstance,
                               Opening, ElementId, ElementTransformUtils,
                               Transaction, TransactionGroup,
                               TransactionStatus, Options, ViewDetailLevel,
                               Solid, GeometryInstance)

import math

from System.Collections.Generic import List

from pyrevit import revit, forms
import bd_core as bd

doc = revit.doc
uidoc = revit.uidoc

# Notes gathered at startup, surfaced in the first completion dialog so the
# pyRevit output console never has to open.
STARTUP_NOTES = []

# ---------------------------------------------------------------------------
# Tunable tolerances (feet, since Revit's internal units are always feet)
# ---------------------------------------------------------------------------
MM = 1.0 / 304.8
# A column must really overlap the wall - across its thickness AND vertically -
# by at least this much to cut it (same rule as Split at Beams). The old 152 mm
# allowances cut walls at columns standing clear of them, and at columns on
# the floor below whose top only touched the wall's base.
MIN_OVERLAP = 3.0 * MM
MIN_SEGMENT_LENGTH = 0.1
MIN_SPLIT_SPACING = 0.5
HOSTED_U_TOL = 0.05

# How much detail the completion dialog will list before truncating
MAX_REPORT_ITEMS = 10
MAX_REPORT_IDS = 30

PROGRESS_THRESHOLD = 15   # show a progress bar above this many walls
GRID_CELL = 10.0          # ft - cell size of the column lookup grid


def eid_str(eid):
    return str(bd.eid_int(eid))


# ---------------------------------------------------------------------------
# 0. Revit messages answered silently (same behaviour as Split at Beams)
# ---------------------------------------------------------------------------

def make_silent(t, handled, fatal):
    """Answer Revit's warnings silently (bd_core.SilentFailures)."""
    log = bd.FailureLog()
    log.handled = handled
    log.fatal = fatal
    bd.make_silent(t, log)


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


class ColumnIndex(object):
    """Plan grid over every column's footprint (broad phase).

    Built once. For each wall only the columns in the grid cells around it
    are tested, instead of every column in the model and all links. The
    search box is padded by the largest column size, so every column the
    full corner test in find_wall_gaps would accept is always returned."""

    def __init__(self, columns):
        self.columns = columns
        self.cells = {}
        self.max_size = 0.0
        for i, col in enumerate(columns):
            xs = [c.X for c in col['corners']]
            ys = [c.Y for c in col['corners']]
            x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
            size = math.sqrt((x1 - x0) ** 2 + (y1 - y0) ** 2)
            if size > self.max_size:
                self.max_size = size
            for cell in self._cells(x0, y0, x1, y1):
                self.cells.setdefault(cell, []).append(i)

    def __len__(self):
        return len(self.columns)

    def _cells(self, x0, y0, x1, y1):
        i0 = int(math.floor(x0 / GRID_CELL))
        i1 = int(math.floor(x1 / GRID_CELL))
        j0 = int(math.floor(y0 / GRID_CELL))
        j1 = int(math.floor(y1 / GRID_CELL))
        for i in range(i0, i1 + 1):
            for j in range(j0, j1 + 1):
                yield (i, j)

    def near_segment(self, p0, p1, band):
        """Columns whose footprint could reach within `band` of p0-p1."""
        pad = (band + self.max_size) * 1.5
        x0 = min(p0.X, p1.X) - pad
        x1 = max(p0.X, p1.X) + pad
        y0 = min(p0.Y, p1.Y) - pad
        y1 = max(p0.Y, p1.Y) + pad
        seen = set()
        found = []
        for cell in self._cells(x0, y0, x1, y1):
            for i in self.cells.get(cell, ()):
                if i not in seen:
                    seen.add(i)
                    found.append(self.columns[i])
        return found


# ---------------------------------------------------------------------------
# 2. For each straight basic wall, find the column-occupied intervals
# ---------------------------------------------------------------------------
def get_wall_z_range(wall):
    bbox = wall.get_BoundingBox(None)
    if bbox is None:
        return None, None
    return bbox.Min.Z, bbox.Max.Z


GEOM_OPTS = Options()
GEOM_OPTS.DetailLevel = ViewDetailLevel.Fine
GEOM_OPTS.ComputeReferences = False
GEOM_OPTS.IncludeNonVisibleObjects = False


def _solid_points(geom, out):
    """Tessellated edge points of every solid in a geometry tree."""
    if geom is None:
        return
    for g in geom:
        if isinstance(g, Solid):
            try:
                if g.Volume <= 0:
                    continue
                for edge in g.Edges:
                    out.extend(edge.Tessellate())
            except Exception:
                pass
        elif isinstance(g, GeometryInstance):
            _solid_points(g.GetInstanceGeometry(), out)


def wall_v_range(wall, p0, normal):
    """(v_min, v_max): the wall's real faces measured across its location
    line. The location line can sit on a finish face or the core, so the
    wall is NOT assumed to be centred on it (same approach as Split at
    Beams). Falls back to centred if the solid can't be read."""
    pts = []
    try:
        _solid_points(wall.get_Geometry(GEOM_OPTS), pts)
    except Exception:
        pts = []
    if pts:
        vs = [(p - p0).DotProduct(normal) for p in pts]
        return min(vs), max(vs)
    half = wall.Width / 2.0
    return -half, half


def wall_skip_reason(wall):
    """Walls this tool must not rebuild (same checks as Split at Beams,
    minus 'attached', which doesn't matter for a split along the length)."""
    if getattr(wall, 'IsStackedWallMember', False):
        return 'part of a stacked wall'
    try:
        if wall.WallType.Kind != WallKind.Basic:
            return 'not a Basic wall (stacked/curtain)'
    except Exception:
        return 'could not read wall type'
    if bd.eid_int(wall.GroupId) != -1:
        return 'inside a group'
    if wall.Pinned:
        return 'pinned'
    sketch_id = getattr(wall, 'SketchId', None)
    if sketch_id is not None and bd.eid_int(sketch_id) != -1:
        return 'has an edited profile'
    return None


def find_wall_gaps(wall, column_index):
    loc = wall.Location
    if not isinstance(loc, LocationCurve):
        return None, 'no LocationCurve'

    curve = loc.Curve
    if not isinstance(curve, Line):
        return None, 'not a straight (Line) wall'

    reason = wall_skip_reason(wall)
    if reason:
        return None, reason

    p0 = curve.GetEndPoint(0)
    p1 = curve.GetEndPoint(1)
    length = curve.Length
    direction = (p1 - p0).Normalize()
    normal = XYZ(-direction.Y, direction.X, 0.0)

    wall_z_min, wall_z_max = get_wall_z_range(wall)
    if wall_z_min is None:
        return None, 'could not read wall bounding box'

    wall_v_min, wall_v_max = wall_v_range(wall, p0, normal)
    band = max(abs(wall_v_min), abs(wall_v_max))

    raw_intervals = []
    for col in column_index.near_segment(p0, p1, band):
        # Real vertical overlap required - a column whose top only touches
        # the wall's base (the floor below) must not cut it.
        z_overlap = (min(col['z_max'], wall_z_max) -
                     max(col['z_min'], wall_z_min))
        if z_overlap < MIN_OVERLAP:
            continue

        us, vs = [], []
        for c in col['corners']:
            vec = c - p0
            us.append(vec.DotProduct(direction))
            vs.append(vec.DotProduct(normal))

        # Real overlap into the wall's thickness required - a column standing
        # clear of the wall face must not cut it.
        v_min, v_max = min(vs), max(vs)
        if min(v_max, wall_v_max) - max(v_min, wall_v_min) < MIN_OVERLAP:
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


def lost_inserts(wall, segments):
    """Ids of the doors / windows / openings no segment can keep. Used both
    to warn BEFORE splitting and to report afterwards."""
    curve = wall.Location.Curve
    p0 = curve.GetEndPoint(0)
    direction = (curve.GetEndPoint(1) - p0).Normalize()
    lost = []
    for el in get_wall_inserts(doc, wall):
        u = insert_u(el, p0, direction)
        if u is None:
            continue
        if owning_segment_index(u, insert_width(el), segments) is None:
            lost.append(el.Id)
    return lost


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
    unrecoverable = lost_inserts(wall, segments)

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
def WallOnlyFilter():
    return bd.ClassFilter(Wall)


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
def analyse_picked(picked, column_index):
    """(plan, skipped) for the picked walls, or None if the user cancelled
    the progress bar."""
    plan = []
    skipped = []

    def analyse(wall):
        try:
            merged, reason = find_wall_gaps(wall, column_index)
        except Exception as ex:
            skipped.append((wall.Id, 'analysis error: {}'.format(ex)))
            return
        if reason:
            skipped.append((wall.Id, reason))
            return
        if not merged:
            return
        length = wall.Location.Curve.Length
        segments = gaps_to_segments(merged, length)
        if not segments:
            skipped.append((wall.Id, 'wall fully consumed by column(s)'))
            return
        plan.append((wall, segments))

    if len(picked) <= PROGRESS_THRESHOLD:
        for wall in picked:
            analyse(wall)
        return plan, skipped

    with forms.ProgressBar(title='Checking walls ({value} of {max_value})',
                           cancellable=True) as pb:
        for i, wall in enumerate(picked):
            if pb.cancelled:
                return None
            analyse(wall)
            pb.update_progress(i + 1, len(picked))
    return plan, skipped


def process_selected_walls(column_index):
    """One full round: pick -> count -> confirm -> split. Returns True to
    keep looping (select again), False to stop the script."""

    picked = pick_walls_by_rectangle(uidoc)
    if picked is None:
        return False  # user hit Esc during the pick - stop the script

    if not picked:
        return bd.confirm(
            'No walls were picked. Select more walls?',
            'Split Walls at Columns')

    analysed = analyse_picked(picked, column_index)
    if analysed is None:
        return bd.confirm(
            'Check cancelled - nothing was changed. Select more walls?',
            'Split Walls at Columns')
    plan, skipped = analysed

    if not plan:
        msg = 'None of the {} selected wall(s) need splitting.'.format(len(picked))
        if skipped:
            msg += ' ({} skipped: curved/stacked/curtain/grouped/pinned/edited profile or fully consumed.)'\
                .format(len(skipped))
        msg += '\n\nSelect more walls?'
        return bd.confirm(msg, 'Split Walls at Columns')

    total_new = sum(len(segs) for _, segs in plan)
    summary = (
        'Selected {} wall(s).\n'
        '{} of them need splitting, into {} wall segment(s) total.\n'
        '{} skipped (curved/stacked/curtain/grouped/pinned/edited profile/'
        'unreadable).'
    ).format(len(picked), len(plan), total_new, len(skipped))

    # Warn BEFORE splitting about hosted elements no segment can keep (same
    # three-way choice as Split at Beams), instead of only reporting after.
    lost_by_wall = []
    for wall, segments in plan:
        try:
            lost = lost_inserts(wall, segments)
        except Exception:
            lost = []
        lost_by_wall.append(lost)
    risky = [i for i, lost in enumerate(lost_by_wall) if lost]

    if not risky:
        if not bd.confirm(summary + '\n\nProceed with the split?',
                          'Split Walls at Columns'):
            return bd.confirm(
                'Split cancelled. Select more walls?',
                'Split Walls at Columns')
    else:
        lost_all = [eid for i in risky for eid in lost_by_wall[i]]
        shown = ', '.join(eid_str(e) for e in lost_all[:MAX_REPORT_IDS])
        if len(lost_all) > MAX_REPORT_IDS:
            shown += ' ...'
        message = (summary + '\n\n'
                   '{} hosted element(s) sit inside a column or straddle a '
                   'column face, so no piece can keep them. They would be '
                   'REMOVED:\n  {}'.format(len(lost_all), shown))
        opt_all = 'Split all {} walls (remove the {} hosted element(s))'\
            .format(len(plan), len(lost_all))
        opt_safe = 'Skip the {} wall(s) with those elements, split the other {}'\
            .format(len(risky), len(plan) - len(risky))
        opt_cancel = 'Cancel'
        choice = bd.choose_option(message, 'Split Walls at Columns',
                                  [opt_all, opt_safe, opt_cancel])
        if choice == opt_safe:
            plan = [p for i, p in enumerate(plan) if i not in risky]
            if not plan:
                return bd.confirm(
                    'Every wall would lose a hosted element - nothing was '
                    'changed. Select more walls?', 'Split Walls at Columns')
        elif choice != opt_all:
            return bd.confirm(
                'Split cancelled. Select more walls?',
                'Split Walls at Columns')

    tg = TransactionGroup(doc, 'Split Walls at Columns (Selection)')
    tg.Start()

    done = 0
    errors = []
    all_unrecoverable = []
    handled_all = {}
    stopped_at = [None]

    def split_one(wall, segments):
        wall_id = wall.Id
        handled, fatal = {}, []
        t = Transaction(doc, 'Split wall {}'.format(eid_str(wall_id)))
        t.Start()
        make_silent(t, handled, fatal)
        try:
            _, unrecoverable = split_wall(doc, wall, segments)
            status = t.Commit()
        except Exception as ex:
            if t.GetStatus() == TransactionStatus.Started:
                t.RollBack()
            errors.append((wall_id, str(ex)))
            return 0
        if status != TransactionStatus.Committed:
            errors.append((wall_id, fatal[0] if fatal else
                           'Revit rejected the result ({})'.format(status)))
            return 0
        all_unrecoverable.extend(unrecoverable)
        for key, count in handled.items():
            handled_all[key] = handled_all.get(key, 0) + count
        return 1

    if len(plan) <= PROGRESS_THRESHOLD:
        for wall, segments in plan:
            done += split_one(wall, segments)
    else:
        with forms.ProgressBar(title='Splitting walls ({value} of {max_value})',
                               cancellable=True) as pb:
            for i, (wall, segments) in enumerate(plan):
                if pb.cancelled:
                    stopped_at[0] = i
                    break
                done += split_one(wall, segments)
                pb.update_progress(i + 1, len(plan))

    tg.Assimilate()

    lines = ['Round complete.',
             'Walls split: {} / {}'.format(done, len(plan))]
    if stopped_at[0] is not None:
        lines.append('Stopped by you - the last {} wall(s) were left unchanged.'
                     .format(len(plan) - stopped_at[0]))
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

    if handled_all:
        lines.append('')
        lines.append('Revit messages answered automatically:')
        ranked = sorted(handled_all.items(), key=lambda kv: -kv[1])
        for (text, action), count in ranked[:MAX_REPORT_ITEMS]:
            if len(text) > 70:
                text = text[:67] + '...'
            lines.append('  {} x {} -> {}'.format(count, text, action))
        if len(ranked) > MAX_REPORT_ITEMS:
            lines.append('  ... and {} more kinds'.format(len(ranked) - MAX_REPORT_ITEMS))

    if STARTUP_NOTES:
        lines.append('')
        lines.extend(STARTUP_NOTES)
        del STARTUP_NOTES[:]

    lines.append('')
    lines.append('Select more walls to process?')

    return bd.confirm('\n'.join(lines),
                      'Split Walls at Columns')


def main():
    all_columns, skipped_links = collect_all_columns(doc)
    if not all_columns:
        bd.alert('No columns found in the active document or any loaded '
                  'links (checked "Columns" and "Structural Columns" '
                  'categories). Nothing to do.',
                 'Split Walls at Columns')
        return
    if skipped_links:
        STARTUP_NOTES.append('Unloaded links skipped: {}'
                             .format(', '.join(skipped_links)))

    column_index = ColumnIndex(all_columns)

    while True:
        keep_going = process_selected_walls(column_index)
        if not keep_going:
            break


if __name__ == '__main__':
    main()
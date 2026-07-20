# -*- coding: utf-8 -*-
"""Fix "Line in Sketch is slightly off axis" warnings (whole project)

Collects every Revit warning whose text is
    "Line in Sketch is slightly off axis and may cause inaccuracies."
and works EXCLUSIVELY with the elements those warnings carry.

Each such warning references two elements:
    - the host element (Floor / Opening / Roof / Filled Region / ... - has a Sketch)
    - the offending sketch line (a CurveElement living inside that host's Sketch)

Strategy
    1. Read doc.GetWarnings(), keep only the sketch off-axis warning.
    2. For every offending sketch line, resolve the owning Sketch
       (ModelCurve.SketchId, with a dependency-walk fallback via the host).
    3. Group the lines by Sketch so each sketch is edited once.
    4. Prompt the user: how many lines / elements were found - proceed or exit.
    5. Per sketch: open a SketchEditScope, and for each flagged line align it
       to the nearest sketch-plane axis by dropping the small perpendicular
       component of its far endpoint. SetGeometryCurve(new, overrideJoins=False)
       preserves the joins, so the adjacent (perpendicular) curve follows and the
       loop stays closed.

Alignment axes
    The line is aligned to its own Sketch plane's X / Y vectors (Plane.XVec /
    Plane.YVec), which is the correct frame for any sketch orientation - plan
    sketches (floors, shafts, openings, regions) and vertical sketches alike.
    Falls back to world X/Y if a sketch plane can't be read.

Safety
    - No warnings are suppressed: the SketchEditScope commit preprocessor returns
      Continue, letting Revit handle any remaining warnings normally.
    - Each line and each sketch is isolated; a faulty one is skipped and counted,
      never aborting the run.
    - Only lines already flagged by Revit are touched, and only if their off-axis
      deviation is under ALIGN_MAX_SIN (guards against distorting a real diagonal).
"""

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')

from Autodesk.Revit.DB import (
    Transaction, ElementId, XYZ, Line, CurveElement, Sketch,
    SketchEditScope, IFailuresPreprocessor, FailureProcessingResult
)
from Autodesk.Revit.UI import (
    TaskDialog, TaskDialogCommonButtons, TaskDialogResult
)

uidoc = __revit__.ActiveUIDocument
doc = uidoc.Document

TITLE = "Fix Off-Axis Sketch Lines"

# Match on both tokens so the DETAIL-line off-axis warning is never caught.
WARNING_TOKENS = ("slightly off axis", "sketch")

ALIGN_MAX_SIN = 0.09   # ~5.16 deg cap; skip anything more slanted than this
MAX_DEPTH = 4          # depth of the host -> sketch dependency walk


# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #
def eid_int(element_id):
    """ElementId -> int, compatible with Revit 2025+ (.Value) and older (.IntegerValue)."""
    try:
        return element_id.Value
    except AttributeError:
        return element_id.IntegerValue


class KeepWarningsPreproc(IFailuresPreprocessor):
    """Required by SketchEditScope.Commit. Continue = let Revit show warnings normally
    (no suppression)."""
    def PreprocessFailures(self, failures_accessor):
        return FailureProcessingResult.Continue


def find_first_sketch(el):
    """Breadth-first walk of an element's dependents; return the first Sketch found."""
    visited = set([eid_int(el.Id)])
    current = [el]
    depth = 0
    while current and depth < MAX_DEPTH:
        nxt = []
        for e in current:
            try:
                deps = e.GetDependentElements(None)
            except Exception:
                deps = []
            for did in deps:
                k = eid_int(did)
                if k in visited:
                    continue
                visited.add(k)
                ce = doc.GetElement(did)
                if ce is None:
                    continue
                if isinstance(ce, Sketch):
                    return ce
                nxt.append(ce)
        current = nxt
        depth += 1
    return None


def resolve_sketch_id(line_elem, host_elems):
    """Owning Sketch ElementId for a sketch line: ModelCurve.SketchId first,
    then a dependency walk from any paired host element."""
    try:
        sid = line_elem.SketchId
        if sid is not None and sid != ElementId.InvalidElementId:
            return sid
    except Exception:
        pass
    for host in host_elems:
        sk = find_first_sketch(host)
        if sk is not None:
            return sk.Id
    return None


def compute_aligned_line(geo_line, plane):
    """Return a new axis-aligned Line, or None if no (valid) change is needed.

    Keeps endpoint 0 fixed and drops the small perpendicular component of the
    far endpoint, snapping the line onto the nearest sketch-plane axis.
    """
    p0 = geo_line.GetEndPoint(0)
    p1 = geo_line.GetEndPoint(1)

    if plane is not None:
        ax = plane.XVec
        ay = plane.YVec
    else:
        ax = XYZ.BasisX
        ay = XYZ.BasisY

    v = p1 - p0
    length = v.GetLength()
    if length < 1e-9:
        return None

    vx = v.DotProduct(ax)   # extent along the plane X axis
    vy = v.DotProduct(ay)   # extent along the plane Y axis
    ux = abs(vx) / length   # |sin| relative to Y axis  (small => aligned to X)
    uy = abs(vy) / length   # |sin| relative to X axis  (small => aligned to Y)

    if ux >= uy:
        # Nearly along X: perpendicular deviation is uy; drop the Y component.
        if uy > ALIGN_MAX_SIN or abs(vy) < 1e-9:
            return None
        p1n = p0 + ax.Multiply(vx)
    else:
        # Nearly along Y: perpendicular deviation is ux; drop the X component.
        if ux > ALIGN_MAX_SIN or abs(vx) < 1e-9:
            return None
        p1n = p0 + ay.Multiply(vy)

    if p1n.DistanceTo(p1) < 1e-9:
        return None
    return Line.CreateBound(p0, p1n)


# --------------------------------------------------------------------------- #
#  Collect flagged sketch lines, grouped by owning sketch
# --------------------------------------------------------------------------- #
def collect_off_axis_lines():
    """Returns (groups, warnings_matched, lines_found).

    groups : { sketch_int_id : {'sketch_eid': ElementId,
                                'lines': { line_int_id: line_ElementId } } }
    """
    groups = {}
    warnings_matched = 0
    line_keys_seen = set()

    for warning in doc.GetWarnings():
        desc = warning.GetDescriptionText()
        if not desc:
            continue
        low = desc.lower()
        if not all(tok in low for tok in WARNING_TOKENS):
            continue

        failing = list(warning.GetFailingElements())
        curve_elems = []
        host_elems = []
        for eid in failing:
            el = doc.GetElement(eid)
            if el is None:
                continue
            if isinstance(el, CurveElement):
                curve_elems.append(el)
            else:
                host_elems.append(el)

        matched_here = False
        for line_elem in curve_elems:
            sid = resolve_sketch_id(line_elem, host_elems)
            if sid is None or sid == ElementId.InvalidElementId:
                continue  # not a sketch line (e.g. a plain detail line) -> ignore

            lkey = eid_int(line_elem.Id)
            if lkey in line_keys_seen:
                matched_here = True
                continue
            line_keys_seen.add(lkey)

            skey = eid_int(sid)
            grp = groups.get(skey)
            if grp is None:
                grp = {'sketch_eid': sid, 'lines': {}}
                groups[skey] = grp
            grp['lines'][lkey] = line_elem.Id
            matched_here = True

        if matched_here:
            warnings_matched += 1

    lines_found = len(line_keys_seen)
    return groups, warnings_matched, lines_found


# --------------------------------------------------------------------------- #
#  Fix one sketch (all of its flagged lines) inside a single SketchEditScope
# --------------------------------------------------------------------------- #
def fix_sketch(sketch_eid, line_ids):
    """Returns (aligned, skipped, errored, sketch_ok)."""
    scope = SketchEditScope(doc, "Fix off-axis sketch lines")
    try:
        scope.Start(sketch_eid)
    except Exception as ex:
        print("Skipped sketch {0} - scope.Start: {1}".format(eid_int(sketch_eid), ex))
        return 0, 0, len(line_ids), False

    t = Transaction(doc, "Align off-axis sketch lines")
    t.Start()

    aligned = 0
    skipped = 0
    errored = 0

    try:
        for line_eid in line_ids:
            try:
                el = doc.GetElement(line_eid)
                if el is None or not isinstance(el, CurveElement):
                    skipped += 1
                    continue

                geo = el.GeometryCurve
                if not isinstance(geo, Line):
                    skipped += 1     # off-axis fix only applies to straight lines
                    continue

                sp = el.SketchPlane
                plane = sp.GetPlane() if sp is not None else None

                new_line = compute_aligned_line(geo, plane)
                if new_line is None:
                    skipped += 1     # already aligned, or too slanted to touch
                    continue

                # overrideJoins=False -> joins preserved, adjacent curve follows.
                el.SetGeometryCurve(new_line, False)
                aligned += 1
                print("Aligned sketch line ID: {0}".format(eid_int(line_eid)))

            except Exception as ex:
                errored += 1
                print("Skipped sketch line ID: {0} - {1}".format(eid_int(line_eid), ex))

        t.Commit()
    except Exception as ex:
        try:
            t.RollBack()
        except Exception:
            pass
        try:
            scope.Cancel()
        except Exception:
            pass
        print("Sketch {0} rolled back - {1}".format(eid_int(sketch_eid), ex))
        return 0, 0, len(line_ids), False

    try:
        scope.Commit(KeepWarningsPreproc())
        return aligned, skipped, errored, True
    except Exception as ex:
        try:
            scope.Cancel()
        except Exception:
            pass
        print("Sketch {0} - scope.Commit failed, reverted: {1}".format(eid_int(sketch_eid), ex))
        # The scope was cancelled, so nothing was actually applied for this sketch.
        return 0, 0, aligned + errored + skipped, False


# --------------------------------------------------------------------------- #
#  Main
# --------------------------------------------------------------------------- #
def main():
    groups, warnings_matched, lines_found = collect_off_axis_lines()
    sketches_total = len(groups)

    if lines_found == 0:
        TaskDialog.Show(
            TITLE,
            "No 'Line in Sketch is slightly off axis' warnings were found in the project."
        )
        return

    proceed = TaskDialog.Show(
        TITLE,
        "Found {0} off-axis sketch line(s) in {1} element(s), "
        "from {2} warning(s).\n\nProceed with the fix?".format(
            lines_found, sketches_total, warnings_matched
        ),
        TaskDialogCommonButtons.Yes | TaskDialogCommonButtons.No
    )
    if proceed != TaskDialogResult.Yes:
        print("Operation cancelled by user.")
        return

    aligned_total = 0
    skipped_total = 0
    errored_total = 0
    sketches_errored = 0

    for skey, grp in groups.items():
        line_ids = list(grp['lines'].values())
        a, s, e, ok = fix_sketch(grp['sketch_eid'], line_ids)
        aligned_total += a
        skipped_total += s
        errored_total += e
        if not ok:
            sketches_errored += 1

    print("{0} of {1} flagged sketch lines were aligned.".format(aligned_total, lines_found))

    TaskDialog.Show(
        TITLE,
        "Done.\n\n"
        "Warnings matched:            {0}\n"
        "Off-axis sketch lines found: {1}\n"
        "Lines aligned:               {2}\n"
        "Lines skipped (no change):   {3}\n"
        "Lines with errors:           {4}\n"
        "Sketches processed:          {5}\n"
        "Sketches with errors:        {6}".format(
            warnings_matched, lines_found, aligned_total,
            skipped_total, errored_total, sketches_total, sketches_errored
        )
    )


main()
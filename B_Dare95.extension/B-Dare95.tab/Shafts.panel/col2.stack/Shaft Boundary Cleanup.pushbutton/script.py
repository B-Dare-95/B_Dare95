# -*- coding: utf-8 -*-
"""Shaft - Clean Boundary-Clashing Symbolic Lines (rectangle select)

Rubber-band (rectangle) select Shaft Openings, then delete the symbolic lines that
are drawn over a boundary edge, keeping the rest (e.g. the X-mark diagonals).

Sketch curves
    ModelLine, category "<Sketch>":
        style "<Sketch>"  -> profile boundary   (reference, never deleted)
        style "<Lines>"   -> symbolic line      (deletion candidate)

Deletion
    Symbolic lines are sketch-internal: plain doc.Delete is tried first (unpinned),
    then a SketchEditScope fallback. Each shaft and each line is isolated - a faulty
    one is skipped and counted, never aborting the run.
"""

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')

from Autodesk.Revit.DB import (
    Transaction, ElementId, XYZ, Line, ModelCurve, Sketch, BuiltInCategory,
    SketchEditScope, IFailuresPreprocessor, FailureProcessingResult
)
from Autodesk.Revit.UI import TaskDialog
from Autodesk.Revit.UI.Selection import ISelectionFilter
from Autodesk.Revit.Exceptions import OperationCanceledException
from System.Collections.Generic import List

uidoc = __revit__.ActiveUIDocument
doc = uidoc.Document

TITLE = "Clean Shaft Boundary Lines"
SYMBOLIC_STYLE = "<Lines>"    # symbolic-line style inside a shaft sketch
BOUNDARY_STYLE = "<Sketch>"   # profile-boundary style inside a shaft sketch
TOL = 0.005                   # feet (~1.5 mm) coincidence tolerance
SAMPLES = 12                  # points sampled along each candidate line
MAX_DEPTH = 4                 # depth of the dependency-tree walk


# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #
def eid_int(element_id):
    """ElementId -> int, compatible with Revit 2025+ (.Value) and older (.IntegerValue)."""
    try:
        return element_id.Value
    except AttributeError:
        return element_id.IntegerValue


class ShaftFilter(ISelectionFilter):
    """Restricts the rectangle pick to Shaft Openings only."""
    _cat_id = ElementId(BuiltInCategory.OST_ShaftOpening)

    def AllowElement(self, elem):
        try:
            return elem.Category is not None and elem.Category.Id == ShaftFilter._cat_id
        except Exception:
            return False

    def AllowReference(self, reference, point):
        return False


class KeepWarningsPreproc(IFailuresPreprocessor):
    """Required by SketchEditScope.Commit. Continue = let Revit show warnings normally."""
    def PreprocessFailures(self, failures_accessor):
        return FailureProcessingResult.Continue


def style_name(curve_elem):
    ls = curve_elem.LineStyle
    return ls.Name if ls is not None else None


def gather_shaft_sketch(shaft):
    """Walk shaft -> sketch -> curves. Returns (model_curves, sketch_element).

    model_curves : list of (element, GeometryCurve, style_name)
    """
    model_curves = []
    sketch = None
    visited = set([eid_int(shaft.Id)])
    current = [shaft]
    depth = 0

    while current and depth < MAX_DEPTH:
        nxt = []
        for el in current:
            try:
                deps = el.GetDependentElements(None)
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
                nxt.append(ce)
                if sketch is None and isinstance(ce, Sketch):
                    sketch = ce
                if isinstance(ce, ModelCurve):
                    model_curves.append((ce, ce.GeometryCurve, style_name(ce)))
        current = nxt
        depth += 1

    return model_curves, sketch


def fallback_boundary(shaft):
    """BoundaryCurves, else the bounding-box rectangle - only if no profile ref found."""
    boundary = []
    ca = None
    try:
        ca = shaft.BoundaryCurves
    except Exception:
        ca = None
    if ca is not None and ca.Size > 0:
        for c in ca:
            if c is not None:
                boundary.append(c)
    if not boundary:
        bb = shaft.get_BoundingBox(None)
        if bb is not None:
            z = bb.Min.Z
            p1 = XYZ(bb.Min.X, bb.Min.Y, z)
            p2 = XYZ(bb.Max.X, bb.Min.Y, z)
            p3 = XYZ(bb.Max.X, bb.Max.Y, z)
            p4 = XYZ(bb.Min.X, bb.Max.Y, z)
            boundary = [Line.CreateBound(p1, p2), Line.CreateBound(p2, p3),
                        Line.CreateBound(p3, p4), Line.CreateBound(p4, p1)]
    return boundary


def curve_lies_on_boundary(cand_curve, boundary_curves):
    """True if every sampled point of cand_curve lies on a boundary curve (within TOL).

    Unbound curves cannot be evaluated as normalized, so they are safely skipped.
    """
    if cand_curve is None:
        return False
    try:
        if not cand_curve.IsBound:
            return False
    except Exception:
        return False

    n = SAMPLES
    i = 0
    while i <= n:
        try:
            p = cand_curve.Evaluate(float(i) / n, True)
        except Exception:
            return False
        on_boundary = False
        for b in boundary_curves:
            try:
                res = b.Project(p)
            except Exception:
                res = None
            if res is not None and res.Distance <= TOL:
                on_boundary = True
                break
        if not on_boundary:
            return False
        i += 1
    return True


# --------------------------------------------------------------------------- #
#  Deletion strategies
# --------------------------------------------------------------------------- #
def try_plain_delete(elems):
    """Unpin + plain doc.Delete in a normal transaction. Returns (ok, error_or_None)."""
    t = Transaction(doc, "Delete symbolic lines")
    t.Start()
    try:
        idl = List[ElementId]()
        for el in elems:
            try:
                if el.Pinned:
                    el.Pinned = False
            except Exception:
                pass
            idl.Add(el.Id)
        doc.Delete(idl)
        t.Commit()
        return True, None
    except Exception as ex:
        try:
            t.RollBack()
        except Exception:
            pass
        return False, str(ex)


def try_scope_delete(sketch_id, elems):
    """Delete inside a SketchEditScope. Returns (ok, error_or_None)."""
    scope = SketchEditScope(doc, "Edit shaft sketch")
    try:
        scope.Start(sketch_id)
    except Exception as ex:
        return False, "scope.Start: " + str(ex)

    t = Transaction(doc, "Delete symbolic lines (scope)")
    t.Start()
    try:
        idl = List[ElementId]()
        for el in elems:
            try:
                if el.Pinned:
                    el.Pinned = False
            except Exception:
                pass
            idl.Add(el.Id)
        doc.Delete(idl)
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
        return False, "delete: " + str(ex)

    try:
        scope.Commit(KeepWarningsPreproc())
        return True, None
    except Exception as ex:
        try:
            scope.Cancel()
        except Exception:
            pass
        return False, "scope.Commit: " + str(ex)


# --------------------------------------------------------------------------- #
#  Main
# --------------------------------------------------------------------------- #
def main():
    try:
        picked = uidoc.Selection.PickElementsByRectangle(
            ShaftFilter(), "Drag a rectangle across the shaft openings to clean.")
    except OperationCanceledException:
        return

    shafts = [e for e in picked] if picked is not None else []
    if not shafts:
        TaskDialog.Show(TITLE, "No shaft openings were inside the selection rectangle.")
        return

    found = len(shafts)
    symbolic_total = 0
    deleted = 0
    skipped = 0          # no boundary reference / no sketch
    shafts_errored = 0
    lines_errored = 0

    for shaft in shafts:
        try:
            dep_curves, sketch = gather_shaft_sketch(shaft)

            boundary_ref = [crv for (el, crv, sn) in dep_curves
                            if sn == BOUNDARY_STYLE and crv is not None]
            symbolic = [(el, crv) for (el, crv, sn) in dep_curves
                        if sn == SYMBOLIC_STYLE and crv is not None]
            symbolic_total += len(symbolic)

            if not boundary_ref:
                boundary_ref = fallback_boundary(shaft)
            if not boundary_ref:
                skipped += 1
                continue
            if not symbolic:
                continue

            over_elems = []
            for el, crv in symbolic:
                try:
                    if crv is None or not crv.IsBound or crv.Length <= 1e-6:
                        continue
                    if curve_lies_on_boundary(crv, boundary_ref):
                        over_elems.append(el)
                except Exception:
                    lines_errored += 1
                    continue

            if not over_elems:
                continue
            if sketch is None:
                skipped += 1
                continue

            n = len(over_elems)
            ok, err = try_plain_delete(over_elems)
            if not ok:
                ok, err = try_scope_delete(sketch.Id, over_elems)
            if ok:
                deleted += n
            else:
                lines_errored += n

        except Exception:
            shafts_errored += 1
            continue

    TaskDialog.Show(
        TITLE,
        "Done.\n\n"
        "Shafts selected:                 {0}\n"
        "Symbolic lines found:            {1}\n"
        "Boundary-clashing lines removed: {2}\n"
        "Symbolic lines kept (e.g. X):    {3}\n"
        "Shafts skipped:                  {4}\n"
        "Shafts with errors:              {5}\n"
        "Lines with errors:               {6}".format(
            found, symbolic_total, deleted, symbolic_total - deleted,
            skipped, shafts_errored, lines_errored
        ),
    )


main()
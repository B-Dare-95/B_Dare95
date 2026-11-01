# -*- coding: utf-8 -*-
__author__ = "Mohamed Bedair"
__doc__ = """__________________________________________________
Description:

Splits a floor drawn with several separate outlines into one floor per outline. Holes stay with the outline around them.
Type, level, structural setting and other instance values are copied to each new floor; Mark is left empty.
__________________________________________________
How-to:

-> Select the floors, or click the button and pick them
-> Click Finish to start the split
-> Confirm if shape edits or hosted elements would be lost
-> Shift+Click the button to keep the original floors
-> The new floors are selected for you
__________________________________________________
Author: Mohamed Bedair
Based on "Split FilledRegion Boundaries" by Erik Frits"""

#==================================================
# IMPORTS
#==================================================
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException
from pyrevit import forms, script, EXEC_PARAMS

import clr
clr.AddReference("System")
from System.Collections.Generic import List

#==================================================
# VARIABLES
#==================================================
uidoc = __revit__.ActiveUIDocument
doc   = uidoc.Document          # type: Document
app   = __revit__.Application

KEEP_ORIGINALS = EXEC_PARAMS.config_mode    # Shift+Click
TOL            = app.VertexTolerance

# Parameters that must stay unique per element
SKIP_BIPS  = [BuiltInParameter.ALL_MODEL_MARK, BuiltInParameter.IFC_GUID]
SKIP_NAMES = ["IfcGUID"]

HOSTED_FILTER = LogicalOrFilter(ElementClassFilter(FamilyInstance),
                                ElementClassFilter(Opening))

#==================================================
# FUNCTIONS - general
#==================================================
def get_id_int(element_id):
    """ElementId as int - .Value (2025+) with .IntegerValue fallback."""
    try:
        return element_id.Value
    except AttributeError:
        return element_id.IntegerValue


def get_bip(param):
    try:
        return param.Definition.BuiltInParameter
    except AttributeError:
        return BuiltInParameter.INVALID


def count_hosted(host):
    """Family instances / openings that Revit would delete with the host."""
    return len([i for i in host.GetDependentElements(HOSTED_FILTER) if i != host.Id])

#==================================================
# FUNCTIONS - boundary loops
#==================================================
def chain_curves(curves):
    """Order a flat list of curves into closed CurveLoops (reversing curves where needed)."""
    remaining = list(curves)
    loops     = []
    while remaining:
        chain = [remaining.pop(0)]
        start = chain[0].GetEndPoint(0)
        while not chain[-1].GetEndPoint(1).IsAlmostEqualTo(start, TOL):
            end = chain[-1].GetEndPoint(1)
            nxt = None
            for i, crv in enumerate(remaining):
                if crv.GetEndPoint(0).IsAlmostEqualTo(end, TOL):
                    nxt = remaining.pop(i)
                    break
                if crv.GetEndPoint(1).IsAlmostEqualTo(end, TOL):
                    nxt = remaining.pop(i).CreateReversed()
                    break
            if nxt is None:
                raise ValueError("the sketch has an open boundary loop")
            chain.append(nxt)
        loop = CurveLoop()
        for crv in chain:
            loop.Append(crv)
        loops.append(loop)
    return loops


def get_sketch_loops(host):
    sketch = doc.GetElement(host.SketchId)
    loops  = []
    for curve_array in sketch.Profile:
        loops.extend(chain_curves([c for c in curve_array]))
    return loops


def loop_to_polygon(loop):
    pts = []
    for crv in loop:
        tess = crv.Tessellate()
        for k in range(tess.Count - 1):
            pts.append((tess[k].X, tess[k].Y))
    return pts


def loop_probe_point(loop):
    for crv in loop:
        return crv.Evaluate(0.5, True)


def point_in_polygon(x, y, poly):
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y):
            if x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                inside = not inside
        j = i
    return inside


def group_loops(loops):
    """Group loops into pieces: [outline, hole, hole, ...] per piece.
    Nesting depth decides the role: even = outline, odd = hole of its direct parent."""
    polys   = [loop_to_polygon(l) for l in loops]
    probes  = [loop_probe_point(l) for l in loops]
    parents = []
    for i in range(len(loops)):
        parents.append([j for j in range(len(loops))
                        if j != i and point_in_polygon(probes[i].X, probes[i].Y, polys[j])])
    depth = [len(p) for p in parents]

    groups = {}
    order  = []
    for i in range(len(loops)):
        if depth[i] % 2 == 0:
            groups[i] = [loops[i]]
            order.append(i)
    for i in range(len(loops)):
        if depth[i] % 2 == 1:
            direct = [j for j in parents[i] if depth[j] == depth[i] - 1]
            if direct:
                groups[direct[0]].append(loops[i])
    return [groups[i] for i in order]

#==================================================
# FUNCTIONS - parameters
#==================================================
def snapshot_parameters(source):
    """Editable instance parameter values, read before the source is deleted."""
    snap = []
    for p in source.Parameters:
        if p.IsReadOnly or not p.HasValue:
            continue
        bip = get_bip(p)
        if bip in SKIP_BIPS or p.Definition.Name in SKIP_NAMES:
            continue
        st = p.StorageType
        if st == StorageType.Double:
            value = p.AsDouble()
        elif st == StorageType.Integer:
            value = p.AsInteger()
        elif st == StorageType.String:
            value = p.AsString() or ""
        elif st == StorageType.ElementId:
            value = p.AsElementId()
        else:
            continue
        snap.append({"bip": bip,
                     "guid": p.GUID if p.IsShared else None,
                     "definition": p.Definition,
                     "storage": st,
                     "value": value})
    return snap


def find_parameter(target, entry):
    if entry["bip"] != BuiltInParameter.INVALID:
        return target.get_Parameter(entry["bip"])
    if entry["guid"] is not None:
        return target.get_Parameter(entry["guid"])
    return target.get_Parameter(entry["definition"])


def values_match(param, entry):
    st = entry["storage"]
    if st == StorageType.Double:
        return abs(param.AsDouble() - entry["value"]) < 1e-9
    if st == StorageType.Integer:
        return param.AsInteger() == entry["value"]
    if st == StorageType.String:
        return (param.AsString() or "") == entry["value"]
    return param.AsElementId() == entry["value"]


def apply_parameters(target, snap):
    """Two passes: some parameters only become editable after others are set.
    Returns the names of parameters that could not be copied."""
    pending = list(snap)
    for attempt in range(2):
        failed = []
        for entry in pending:
            param = find_parameter(target, entry)
            if param is None:
                continue
            try:
                if values_match(param, entry):
                    continue
                if param.IsReadOnly or not param.Set(entry["value"]):
                    failed.append(entry)
            except Exception:
                failed.append(entry)
        pending = failed
        if not pending:
            break
        doc.Regenerate()
    return [e["definition"].Name for e in pending]

#==================================================
# FUNCTIONS - floor specific
#==================================================
def is_structural(floor):
    p = floor.get_Parameter(BuiltInParameter.FLOOR_PARAM_IS_STRUCTURAL)
    return bool(p and p.AsInteger() == 1)


def has_shape_edits(floor):
    try:
        editor = floor.GetSlabShapeEditor()
    except AttributeError:
        editor = floor.SlabShapeEditor
    return editor is not None and editor.IsEnabled

#==================================================
# CLASSES
#==================================================
class FloorSplitFilter(ISelectionFilter):
    def AllowElement(self, element):
        try:
            if not isinstance(element, Floor):
                return False
            return doc.GetElement(element.SketchId).Profile.Size > 1
        except Exception:
            return False

    def AllowReference(self, reference, position):
        return False


def get_targets():
    flt         = FloorSplitFilter()
    preselected = [doc.GetElement(i) for i in uidoc.Selection.GetElementIds()]
    targets     = [e for e in preselected if flt.AllowElement(e)]
    if targets:
        return targets
    with forms.WarningBar(title="Pick Floors to split, then click Finish:"):
        try:
            refs = uidoc.Selection.PickObjects(ObjectType.Element, flt, "Pick Floors to split")
        except OperationCanceledException:
            return []
    return [doc.GetElement(r) for r in refs]

#==================================================
# MAIN
#==================================================
#1 Get Floors
targets = get_targets()
if not targets:
    forms.alert("No Floor with more than one boundary loop was selected.", exitscript=True)

#2 Work out the pieces
plans, skipped = [], []
for floor in targets:
    fid = get_id_int(floor.Id)
    try:
        groups = group_loops(get_sketch_loops(floor))
    except Exception as ex:
        skipped.append("Floor {0}: {1}".format(fid, ex))
        continue
    if len(groups) < 2:
        skipped.append("Floor {0}: only one outline, the other loops are holes".format(fid))
        continue
    plans.append((floor, groups))

if not plans:
    forms.alert("Nothing to split.", expanded="\n".join(skipped), exitscript=True)

#3 Pre-checks
shaped = [f for f, g in plans if has_shape_edits(f)]
if shaped:
    forms.alert("{0} Floor(s) have slab shape edits.\n"
                "The new Floors will be flat. Continue?".format(len(shaped)),
                yes=True, no=True, exitscript=True)

keep = KEEP_ORIGINALS
if not keep:
    hosted = sum([count_hosted(f) for f, g in plans])
    if hosted:
        choice = forms.alert("{0} hosted element(s) or opening(s) sit on the selected Floors "
                             "and would be deleted with the originals.".format(hosted),
                             options=["Keep originals", "Delete originals anyway", "Cancel"])
        if choice == "Keep originals":
            keep = True
        elif choice != "Delete originals anyway":
            script.exit()

#4 Split
new_ids, done, failed = [], [], list(skipped)

t = Transaction(doc, "B_Dare95 | Split Floors")
t.Start()
try:
    for floor, groups in plans:
        fid        = get_id_int(floor.Id)
        type_id    = floor.GetTypeId()
        level_id   = floor.LevelId
        structural = is_structural(floor)
        snap       = snapshot_parameters(floor)

        st = SubTransaction(doc)
        st.Start()
        try:
            if not keep:
                doc.Delete(floor.Id)    # first, so the new Floors never overlap it
            created, not_copied = [], set()
            for group in groups:
                piece = Floor.Create(doc, List[CurveLoop](group), type_id, level_id,
                                     structural, None, 0.0)
                not_copied.update(apply_parameters(piece, snap))
                created.append(piece.Id)
            st.Commit()
            new_ids.extend(created)
            line = "Floor {0} -> {1} Floors".format(fid, len(created))
            if not_copied:
                line += " (not copied: {0})".format(", ".join(sorted(not_copied)))
            done.append(line)
        except Exception as ex:
            st.RollBack()
            failed.append("Floor {0}: {1}".format(fid, ex))

    status = t.Commit()
except Exception as ex:
    t.RollBack()
    forms.alert("Split failed, nothing was changed.\n\n{0}".format(ex), exitscript=True)

if status != TransactionStatus.Committed:
    forms.alert("Revit rolled the split back, nothing was changed.", exitscript=True)

#5 Report
if new_ids:
    uidoc.Selection.SetElementIds(List[ElementId](new_ids))

msg = "Split {0} Floor(s) into {1} new Floor(s).".format(len(done), len(new_ids))
if keep and done:
    msg += "\nOriginals were kept."
if failed:
    msg += "\n{0} Floor(s) skipped or failed - see details.".format(len(failed))
forms.alert(msg, expanded="\n".join(done + failed) or None)
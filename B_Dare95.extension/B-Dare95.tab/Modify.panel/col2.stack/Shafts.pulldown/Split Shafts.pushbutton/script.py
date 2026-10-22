# -*- coding: utf-8 -*-
__title__  = "Split\nShafts"
__author__ = "Mohamed Bedair"
__doc__ = """__________________________________________________
Description:

Splits shafts whose sketch has several separate outlines into one shaft per outline; holes stay with the outline around them.
Base and top settings, phases and other values are copied over, and the new shafts are selected for you.
__________________________________________________
How-to:

-> Select the shafts to split, or pick them after clicking
-> Click on the button to split and delete the originals
-> Shift+Click the button to split and keep the originals
-> If you're picking, click Finish when done
-> The new shafts are selected for you
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


def get_shaft_loops(shaft):
    """Loops from the shaft's own Sketch; BoundaryCurves as fallback."""
    loops = []
    for sketch_id in shaft.GetDependentElements(ElementClassFilter(Sketch)):
        sketch = doc.GetElement(sketch_id)
        for curve_array in sketch.Profile:
            loops.extend(chain_curves([c for c in curve_array]))
        if loops:
            return loops
    return chain_curves([c for c in shaft.BoundaryCurves])


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
# FUNCTIONS - shaft specific
#==================================================
SHAFT_CAT_ID = ElementId(BuiltInCategory.OST_ShaftOpening)
LEVELS       = sorted(FilteredElementCollector(doc).OfClass(Level).ToElements(),
                      key=lambda l: l.Elevation)


def is_shaft(element):
    """Category check instead of Opening.IsShaft (unreliable on 2027+)."""
    return (isinstance(element, Opening) and element.Category is not None
            and element.Category.Id == SHAFT_CAT_ID)


def get_shaft_levels(shaft):
    """Base/top levels for NewOpening. An unconnected top uses the next level
    up as a placeholder - the copied parameters restore Unconnected + height."""
    base_param = shaft.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT)
    top_param  = shaft.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE)
    if base_param is None:
        raise ValueError("base constraint not found")
    base = doc.GetElement(base_param.AsElementId())
    top  = None
    if top_param is not None and top_param.AsElementId() != ElementId.InvalidElementId:
        top = doc.GetElement(top_param.AsElementId())
    if top is None:
        above = [l for l in LEVELS if l.Elevation > base.Elevation + 1e-6]
        top   = above[0] if above else base
    return base, top


def group_to_curvearray(group):
    profile = CurveArray()
    for loop in group:
        for crv in loop:
            profile.Append(crv)
    return profile

#==================================================
# CLASSES
#==================================================
class ShaftSplitFilter(ISelectionFilter):
    def AllowElement(self, element):
        try:
            if not is_shaft(element):
                return False
            return len(get_shaft_loops(element)) > 1
        except Exception:
            return False

    def AllowReference(self, reference, position):
        return False


def get_targets():
    flt         = ShaftSplitFilter()
    preselected = [doc.GetElement(i) for i in uidoc.Selection.GetElementIds()]
    targets     = [e for e in preselected if flt.AllowElement(e)]
    if targets:
        return targets
    with forms.WarningBar(title="Pick Shafts to split, then click Finish:"):
        try:
            refs = uidoc.Selection.PickObjects(ObjectType.Element, flt, "Pick Shafts to split")
        except OperationCanceledException:
            return []
    return [doc.GetElement(r) for r in refs]

#==================================================
# MAIN
#==================================================
#1 Get Shafts
targets = get_targets()
if not targets:
    forms.alert("No Shaft with more than one boundary loop was selected.", exitscript=True)

#2 Work out the pieces
plans, skipped = [], []
for shaft in targets:
    fid = get_id_int(shaft.Id)
    try:
        groups = group_loops(get_shaft_loops(shaft))
    except Exception as ex:
        skipped.append("Shaft {0}: {1}".format(fid, ex))
        continue
    if len(groups) < 2:
        skipped.append("Shaft {0}: only one outline, the other loops sit inside it".format(fid))
        continue
    plans.append((shaft, groups))

if not plans:
    forms.alert("Nothing to split.", expanded="\n".join(skipped), exitscript=True)

#3 Pre-checks
keep = KEEP_ORIGINALS
if not keep:
    hosted = sum([count_hosted(f) for f, g in plans])
    if hosted:
        choice = forms.alert("{0} hosted element(s) depend on the selected Shafts "
                             "and would be deleted with the originals.".format(hosted),
                             options=["Keep originals", "Delete originals anyway", "Cancel"])
        if choice == "Keep originals":
            keep = True
        elif choice != "Delete originals anyway":
            script.exit()

#4 Split
new_ids, done, failed = [], [], list(skipped)

t = Transaction(doc, "B_Dare95 | Split Shafts")
t.Start()
try:
    for shaft, groups in plans:
        fid        = get_id_int(shaft.Id)
        snap       = snapshot_parameters(shaft)

        st = SubTransaction(doc)
        st.Start()
        try:
            base, top = get_shaft_levels(shaft)
            if not keep:
                doc.Delete(shaft.Id)    # first, so the new Shafts never overlap it
            created, not_copied = [], set()
            for group in groups:
                piece = doc.Create.NewOpening(base, top, group_to_curvearray(group))
                not_copied.update(apply_parameters(piece, snap))
                created.append(piece.Id)
            st.Commit()
            new_ids.extend(created)
            line = "Shaft {0} -> {1} Shafts".format(fid, len(created))
            if not_copied:
                line += " (not copied: {0})".format(", ".join(sorted(not_copied)))
            done.append(line)
        except Exception as ex:
            st.RollBack()
            failed.append("Shaft {0}: {1}".format(fid, ex))

    status = t.Commit()
except Exception as ex:
    t.RollBack()
    forms.alert("Split failed, nothing was changed.\n\n{0}".format(ex), exitscript=True)

if status != TransactionStatus.Committed:
    forms.alert("Revit rolled the split back, nothing was changed.", exitscript=True)

#5 Report
if new_ids:
    uidoc.Selection.SetElementIds(List[ElementId](new_ids))

msg = "Split {0} Shaft(s) into {1} new Shaft(s).".format(len(done), len(new_ids))
if keep and done:
    msg += "\nOriginals were kept."
if failed:
    msg += "\n{0} Shaft(s) skipped or failed - see details.".format(len(failed))
forms.alert(msg, expanded="\n".join(done + failed) or None)
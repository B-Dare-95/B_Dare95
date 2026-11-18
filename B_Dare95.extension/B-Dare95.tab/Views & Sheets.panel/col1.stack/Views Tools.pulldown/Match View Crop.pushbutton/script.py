# -*- coding: utf-8 -*-
__author__ = "Mohamed Bedair"
__doc__ = """__________________________________________________
Description:

Copies the crop boundary of the view inside one viewport to the views inside other viewports,
so they all show exactly the same area.
Works on plans, ceiling plans, structural and area plans, sections, elevations and callouts.
Rectangular and non-rectangular crops are both copied; the annotation crop is copied too.
__________________________________________________
How-to:

-> Open a sheet
-> Click the button
-> Pick the SOURCE viewport - its view must have its crop turned on, otherwise pick another
-> Pick the viewports that should get the same crop, then click Finish (or press Enter)
   (views looking another way than the source are skipped and listed)
-> A summary lists the views changed and any that were skipped
__________________________________________________
Author: Mohamed Bedair"""

from Autodesk.Revit.DB import (BuiltInParameter, CurveLoop, ElementId, Line,
                               SubTransaction, Transaction, TransactionStatus,
                               View, Viewport, ViewSheet, ViewType, XYZ)
from Autodesk.Revit.Exceptions import OperationCanceledException
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
import bd_core as bd


# ---------------------------------------------------------------------------
# SETTINGS
# ---------------------------------------------------------------------------
TITLE = u"Match View Crop"

# View types that have a 2D crop region this tool can copy.
# 3D views are left out on purpose: their crop is a 3D box, not an outline.
CROPPABLE_TYPES = (ViewType.FloorPlan, ViewType.CeilingPlan,
                   ViewType.EngineeringPlan, ViewType.AreaPlan,
                   ViewType.Section, ViewType.Elevation, ViewType.Detail)

# Two views "look the same way" when their view directions are parallel
# (same or opposite - a floor plan and a ceiling plan both qualify).
PARALLEL_TOL = 0.9999

uidoc = __revit__.ActiveUIDocument
doc = uidoc.Document


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------
def is_croppable(view):
    """True for non-template views whose crop region can be copied."""
    try:
        return (isinstance(view, View) and not view.IsTemplate
                and view.ViewType in CROPPABLE_TYPES)
    except Exception:
        return False


def same_axis(a, b):
    """True when both views look along the same line (either way round)."""
    return abs(a.ViewDirection.DotProduct(b.ViewDirection)) > PARALLEL_TOL


def scope_box_name(view):
    """Name of the Scope Box that controls this view's crop, or None.
    While a scope box is assigned, Revit locks the crop to it."""
    p = view.get_Parameter(BuiltInParameter.VIEWER_VOLUME_OF_INTEREST_CROP)
    if p is None:
        return None
    eid = p.AsElementId()
    if eid is None or eid == ElementId.InvalidElementId:
        return None
    box = doc.GetElement(eid)
    return box.Name if box is not None else u"a scope box"


def rectangle_from_crop_box(view):
    """The view's rectangular crop as a CurveLoop in model coordinates.
    Used when Revit does not hand back the crop shape directly."""
    box = view.CropBox
    tf = box.Transform
    z = box.Max.Z
    corners = [(box.Min.X, box.Min.Y), (box.Max.X, box.Min.Y),
               (box.Max.X, box.Max.Y), (box.Min.X, box.Max.Y)]
    pts = [tf.OfPoint(XYZ(x, y, z)) for x, y in corners]
    loop = CurveLoop()
    for i in range(4):
        loop.Append(Line.CreateBound(pts[i], pts[(i + 1) % 4]))
    return loop


def source_outline(view):
    """The source crop boundary (rectangular or not) in model coordinates."""
    try:
        loops = list(view.GetCropRegionShapeManager().GetCropShape())
    except Exception:
        loops = []
    if loops:
        return loops[0]
    return rectangle_from_crop_box(view)


def project_loop(loop, view):
    """Move every corner of 'loop' onto the target view's plane (along the
    view direction). The outline keeps its plan / elevation position, only its
    depth changes, so Revit accepts it as a crop of the target view."""
    n = view.ViewDirection
    o = view.Origin

    def onto_plane(p):
        return p - n.Multiply((p - o).DotProduct(n))

    out = CurveLoop()
    for crv in loop:     # crop shapes are made of straight lines only
        out.Append(Line.CreateBound(onto_plane(crv.GetEndPoint(0)),
                                    onto_plane(crv.GetEndPoint(1))))
    return out


def set_crop_box_from_loop(view, loop):
    """Fallback for views that can't take a crop shape: fit the view's own
    rectangular crop box around the outline (depth kept as it was)."""
    box = view.CropBox
    inv = box.Transform.Inverse
    pts = [inv.OfPoint(crv.GetEndPoint(0)) for crv in loop]
    box.Min = XYZ(min(p.X for p in pts), min(p.Y for p in pts), box.Min.Z)
    box.Max = XYZ(max(p.X for p in pts), max(p.Y for p in pts), box.Max.Z)
    view.CropBox = box


def match_annotation_crop(source, target):
    """Copy the annotation crop (on/off and its four offsets).

    Offsets are 'top / bottom / left / right' on screen. When the target is
    seen from the other side (e.g. floor plan -> ceiling plan, or a section
    looking the other way) left/right or top/bottom are swapped so each
    offset stays on the same side of the building."""
    smgr = source.GetCropRegionShapeManager()
    tmgr = target.GetCropRegionShapeManager()
    if not (smgr.CanHaveAnnotationCrop and tmgr.CanHaveAnnotationCrop):
        return

    sp = source.get_Parameter(BuiltInParameter.VIEWER_ANNOTATION_CROP_ACTIVE)
    tp = target.get_Parameter(BuiltInParameter.VIEWER_ANNOTATION_CROP_ACTIVE)
    if sp is None or tp is None or tp.IsReadOnly:
        return
    tp.Set(sp.AsInteger())
    if sp.AsInteger() != 1:
        return                                   # annotation crop is off

    swap_lr = source.RightDirection.DotProduct(target.RightDirection) < 0
    swap_tb = source.UpDirection.DotProduct(target.UpDirection) < 0

    left, right = smgr.LeftAnnotationCropOffset, smgr.RightAnnotationCropOffset
    top, bottom = smgr.TopAnnotationCropOffset, smgr.BottomAnnotationCropOffset
    if swap_lr:
        left, right = right, left
    if swap_tb:
        top, bottom = bottom, top

    tmgr.LeftAnnotationCropOffset = left
    tmgr.RightAnnotationCropOffset = right
    tmgr.TopAnnotationCropOffset = top
    tmgr.BottomAnnotationCropOffset = bottom


def target_problem(source, target):
    """Reason this target can't be matched, or None when it can."""
    if not same_axis(source, target):
        return u"looks in a different direction from the source"
    scope = scope_box_name(target)
    if scope:
        return (u"its crop is controlled by Scope Box '{0}' - set Scope Box "
                u"to <None> first".format(scope))
    if target.GetCropRegionShapeManager().Split:
        return u"its crop is split into regions - remove the split first"
    return None


def apply_crop(source, target, outline):
    """Give 'target' the source crop. Modifies the model (needs a transaction)."""
    tmgr = target.GetCropRegionShapeManager()

    # A crop boundary only has an effect while the crop is on.
    target.CropBoxActive = True

    loop = project_loop(outline, target)

    # Rectangular source whose edges run along the target's own crop edges:
    # set the target's crop box directly (the normal, editable crop).
    # Non-rectangular or rotated sources need the outline as a crop shape.
    source_rect = not source.GetCropRegionShapeManager().ShapeSet
    aligned = abs(source.CropBox.Transform.BasisX.DotProduct(
        target.CropBox.Transform.BasisX)) > PARALLEL_TOL

    if (source_rect and aligned) or not tmgr.CanHaveShape:
        if tmgr.ShapeSet:
            tmgr.RemoveCropRegionShape()
        set_crop_box_from_loop(target, loop)
    else:
        if not tmgr.IsCropRegionShapeValid(loop):
            raise Exception(u"Revit does not accept the source outline in this view")
        tmgr.SetCropShape(loop)

    target.CropBoxVisible = source.CropBoxVisible
    match_annotation_crop(source, target)


# ---------------------------------------------------------------------------
# PICKING VIEWPORTS
# ---------------------------------------------------------------------------
class ViewportFilter(ISelectionFilter):
    """Only viewports can be picked (optionally all but one)."""

    def __init__(self, exclude_id=None):
        self.exclude = bd.eid_int(exclude_id) if exclude_id is not None else None

    def AllowElement(self, el):
        return isinstance(el, Viewport) and bd.eid_int(el.Id) != self.exclude

    def AllowReference(self, ref, point):
        return False


def exit_quietly():
    import sys
    sys.exit(0)


# Viewports live on sheets - picking only works from a sheet.
if not isinstance(uidoc.ActiveView, ViewSheet):
    bd.alert(u"Open a sheet first - this tool picks viewports on the active sheet.",
             TITLE, exit=True)


# ---------------------------------------------------------------------------
# 1. SOURCE VIEWPORT - PickObject (one), refused until its view has a crop
# ---------------------------------------------------------------------------
source = None
source_vp = None
while source is None:
    try:
        ref = uidoc.Selection.PickObject(
            ObjectType.Element, ViewportFilter(),
            u"Match Crop: pick the SOURCE viewport - Esc to cancel")
    except OperationCanceledException:
        exit_quietly()
    vp = doc.GetElement(ref.ElementId)
    view = doc.GetElement(vp.ViewId)
    if not is_croppable(view):
        bd.alert(u"'{0}' is a {1} view, which has no crop boundary to copy.\n\n"
                 u"Pick another viewport.".format(view.Name, view.ViewType), TITLE)
        continue
    if not view.CropBoxActive:
        bd.alert(u"'{0}' has no crop - its Crop View is turned off.\n\n"
                 u"Pick another viewport.".format(view.Name), TITLE)
        continue
    if view.GetCropRegionShapeManager().Split:
        bd.alert(u"The crop of '{0}' is split into regions, which can't be "
                 u"copied.\n\nPick another viewport.".format(view.Name), TITLE)
        continue
    source, source_vp = view, vp

outline = source_outline(source)


# ---------------------------------------------------------------------------
# 2. TARGET VIEWPORTS - PickObjects (many), Finish or Enter when done
# ---------------------------------------------------------------------------
try:
    refs = uidoc.Selection.PickObjects(
        ObjectType.Element, ViewportFilter(source_vp.Id),
        u"Match Crop: pick the viewports to match '{0}', then click Finish".format(
            source.Name))
except OperationCanceledException:
    exit_quietly()

targets, skipped_early, seen = [], [], set()
for ref in refs:
    view = doc.GetElement(doc.GetElement(ref.ElementId).ViewId)
    if bd.eid_int(view.Id) in seen:
        continue
    seen.add(bd.eid_int(view.Id))
    if not is_croppable(view):
        skipped_early.append(u"{0}: a {1} view has no crop boundary".format(
            view.Name, view.ViewType))
        continue
    targets.append(view)
if not targets and not skipped_early:
    exit_quietly()


# ---------------------------------------------------------------------------
# 3. APPLY  (modifies the model - one undo step)
# ---------------------------------------------------------------------------
done, skipped = [], list(skipped_early)

t = Transaction(doc, u"Match Crop to '{0}'".format(source.Name))
t.Start()
try:
    for view in targets:
        reason = target_problem(source, view)
        if reason:
            skipped.append(u"{0}: {1}".format(view.Name, reason))
            continue
        # One sub-transaction per view: a view that fails is put back exactly
        # as it was, the others still go through.
        st = SubTransaction(doc)
        st.Start()
        try:
            apply_crop(source, view, outline)
            st.Commit()
            done.append(view.Name)
        except Exception as ex:
            if st.HasStarted() and not st.HasEnded():
                st.RollBack()
            skipped.append(u"{0}: {1}".format(view.Name, ex))
    status = t.Commit()
except Exception:
    if t.HasStarted() and not t.HasEnded():
        t.RollBack()
    raise

# Commit() returns RolledBack (it does not raise) when Revit's failure
# handling undoes the change - never report a false success.
if status != TransactionStatus.Committed:
    bd.alert(u"Revit rolled back the change ({0}). No crop was changed.".format(status),
             TITLE, exit=True)


# ---------------------------------------------------------------------------
# 4. SUMMARY
# ---------------------------------------------------------------------------
msg = u"Matched {0} to the crop of '{1}'.".format(
    bd.plural(len(done), u"view"), source.Name)
details = u""
if done:
    details += u"Matched:\n" + u"\n".join(u"  - " + n for n in done)
if skipped:
    msg += u"\n{0} skipped.".format(bd.plural(len(skipped), u"view"))
    details += (u"\n\n" if details else u"") + u"Skipped:\n" + \
        u"\n".join(u"  - " + s for s in skipped)
bd.alert(msg, TITLE, details=details or None)

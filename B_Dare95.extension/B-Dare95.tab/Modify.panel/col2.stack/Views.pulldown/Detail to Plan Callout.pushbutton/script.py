# -*- coding: utf-8 -*-
"""Rebuilds detail callouts that were drawn in floor plans as floor plan callouts.

Revit cannot change a callout's view family in place: a detail callout is a
ViewSection and a floor plan callout is a ViewPlan. Each selected callout is
therefore recreated with ViewSection.CreateCallout in the same parent plan, its
settings / annotations / sheet placement / references are carried over, and the
original detail view is deleted.
"""
__title__ = "Detail to\nPlan Callout"

import clr
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from System import EventHandler
from System.Collections.Generic import List
from System.Windows import (Visibility, Thickness, CornerRadius, RoutedEventHandler,
                            TextTrimming, VerticalAlignment, FontWeights)
from System.Windows.Controls import (StackPanel, TextBlock, CheckBox, Border,
                                     Orientation, TextChangedEventHandler)
from System.Windows.Input import MouseButtonEventHandler
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Markup import XamlReader
from System.Windows.Media import BrushConverter
from System.Windows.Threading import Dispatcher, DispatcherFrame

from Autodesk.Revit.DB import (
    BoundingBoxIntersectsFilter, BuiltInCategory, BuiltInParameter, CheckoutStatus,
    Color, CopyPasteOptions, Element, ElementId, ElementOwnerViewFilter,
    ElementTransformUtils, FilteredElementCollector, InternalDefinition, Outline,
    OverrideGraphicSettings, ReferenceableViewUtils, Sketch, SketchPlane, StorageType,
    SubTransaction, Transaction, TransactionGroup, TransactionStatus, Transform,
    View, ViewFamily, ViewFamilyType, ViewPlan, ViewSection, ViewType, Viewport,
    WorksharingUtils, XYZ)

from pyrevit import forms, script

doc = __revit__.ActiveUIDocument.Document
INVALID = ElementId.InvalidElementId


# ----------------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------------
def eid_int(eid):
    try:
        return eid.Value
    except AttributeError:
        return eid.IntegerValue


def is_invalid(eid):
    return eid is None or eid_int(eid) == eid_int(INVALID)


def same_id(a, b):
    return eid_int(a) == eid_int(b)


def elem_name(el):
    try:
        return el.Name
    except Exception:
        p = el.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME)
        return p.AsString() if p else "<unnamed>"


def err_text(e):
    msg = getattr(e, "Message", None)
    return msg if msg else str(e)


def attempt(notes, label, fn):
    try:
        fn()
        return True
    except Exception as e:
        notes.append("{} not carried over ({})".format(label, err_text(e)))
        return False


def safe_ids(getter):
    try:
        return list(getter())
    except Exception:
        return []


def owned_by_other(eid):
    if not doc.IsWorkshared:
        return False
    try:
        return WorksharingUtils.GetCheckoutStatus(doc, eid) == CheckoutStatus.OwnedByOtherUser
    except Exception:
        return False


# OverrideGraphicSettings has no "is empty" check, so compare against a fresh one.
OGS_PROPS = (
    "Halftone", "Transparency", "DetailLevel",
    "ProjectionLineColor", "ProjectionLinePatternId", "ProjectionLineWeight",
    "CutLineColor", "CutLinePatternId", "CutLineWeight",
    "SurfaceForegroundPatternId", "SurfaceForegroundPatternColor", "IsSurfaceForegroundPatternVisible",
    "SurfaceBackgroundPatternId", "SurfaceBackgroundPatternColor", "IsSurfaceBackgroundPatternVisible",
    "CutForegroundPatternId", "CutForegroundPatternColor", "IsCutForegroundPatternVisible",
    "CutBackgroundPatternId", "CutBackgroundPatternColor", "IsCutBackgroundPatternVisible",
)


def _values_equal(a, b):
    if isinstance(a, Color):
        if a.IsValid != b.IsValid:
            return False
        if not a.IsValid:
            return True
        return a.Red == b.Red and a.Green == b.Green and a.Blue == b.Blue
    if isinstance(a, ElementId):
        return same_id(a, b)
    return a == b


def ogs_is_default(ogs):
    blank = OverrideGraphicSettings()
    for name in OGS_PROPS:
        try:
            a = getattr(ogs, name)
            b = getattr(blank, name)
        except Exception:
            continue
        if not _values_equal(a, b):
            return False
    return True


def _skip_category_ints():
    out = set()
    for name in ("OST_Viewers", "OST_SketchLines", "OST_CropBoundary", "OST_IOSSketchGrid"):
        bic = getattr(BuiltInCategory, name, None)
        if bic is not None:
            out.add(int(bic))
    return out


SKIP_CATS = _skip_category_ints()


# ----------------------------------------------------------------------------
# Scan
# ----------------------------------------------------------------------------
class Row(object):
    def __init__(self, view, parent, viewport):
        self.view = view
        self.parent = parent
        self.viewport = viewport
        self.name = view.Name
        self.parent_name = parent.Name
        self.scale = "1:{}".format(view.Scale)
        self.sheet_label = ""
        if viewport is not None:
            sheet = doc.GetElement(viewport.SheetId)
            if sheet is not None:
                self.sheet_label = "{} - {}".format(sheet.SheetNumber, sheet.Name)
        self.reason = None
        # UI handles
        self.checkbox = None
        self.border = None

    @property
    def ok(self):
        return self.reason is None


def scan(probe_vft_id):
    viewports = {}
    for vp in FilteredElementCollector(doc).OfClass(Viewport):
        viewports[eid_int(vp.ViewId)] = vp

    children = {}
    details = []
    for v in FilteredElementCollector(doc).OfClass(View):
        if v.IsTemplate:
            continue
        try:
            if not v.IsCallout:
                continue
            pid = v.GetCalloutParentId()
        except Exception:
            continue
        children.setdefault(eid_int(pid), []).append(v)
        if isinstance(v, ViewSection) and v.ViewType == ViewType.Detail:
            details.append((v, pid))

    active_id = doc.ActiveView.Id if doc.ActiveView is not None else INVALID
    rows = []
    for v, pid in details:
        if is_invalid(pid):
            continue
        parent = doc.GetElement(pid)
        # Only detail callouts drawn in plans are candidates; details drawn in
        # sections / elevations / other details are legitimate and not listed.
        if parent is None or not isinstance(parent, ViewPlan):
            continue
        row = Row(v, parent, viewports.get(eid_int(v.Id)))

        if parent.ViewType != ViewType.FloorPlan:
            row.reason = "Parent is a {} - floor plan type not allowed".format(parent.ViewType)
        elif not ViewSection.IsViewFamilyTypeValidForCallout(doc, probe_vft_id, pid):
            row.reason = "Parent plan does not accept floor plan callouts"
        elif same_id(v.Id, active_id):
            row.reason = "Active view - switch to another view first"
        elif not is_invalid(v.GetPrimaryViewId()):
            row.reason = "Is a dependent view"
        elif v.GetDependentViewIds().Count > 0:
            row.reason = "Has dependent views"
        elif children.get(eid_int(v.Id)):
            row.reason = "Has callouts drawn inside it"
        elif owned_by_other(v.Id) or owned_by_other(pid) or (
                row.viewport is not None and owned_by_other(row.viewport.SheetId)):
            row.reason = "View, parent or sheet is borrowed by another user"
        rows.append(row)

    rows.sort(key=lambda r: (0 if r.ok else 1, r.name.lower()))
    return rows


# ----------------------------------------------------------------------------
# Transfer steps (all run inside the per-callout transaction)
# ----------------------------------------------------------------------------
def plan_rect_from_crop(old, parent):
    """Old detail crop corners -> two opposite corners aligned to the parent plan."""
    cb = old.CropBox
    tf = cb.Transform
    mn, mx = cb.Min, cb.Max
    corners = [tf.OfPoint(XYZ(x, y, mn.Z)) for x in (mn.X, mx.X) for y in (mn.Y, mx.Y)]
    right, up = parent.RightDirection, parent.UpDirection
    us = [p.DotProduct(right) for p in corners]
    vs = [p.DotProduct(up) for p in corners]
    p1 = right.Multiply(min(us)).Add(up.Multiply(min(vs)))
    p2 = right.Multiply(max(us)).Add(up.Multiply(max(vs)))
    bx = tf.BasisX
    rotated = abs(bx.DotProduct(right)) < 0.9999 and abs(bx.DotProduct(up)) < 0.9999
    return p1, p2, rotated, corners


def transfer_crop(old, new, rotated, notes):
    om = old.GetCropRegionShapeManager()
    nm = new.GetCropRegionShapeManager()
    for side in ("Left", "Right", "Top", "Bottom"):
        prop = "{}AnnotationCropOffset".format(side)
        try:
            setattr(nm, prop, getattr(om, prop))
        except Exception:
            pass
    attempt(notes, "Crop region visibility", lambda: setattr(new, "CropBoxVisible", old.CropBoxVisible))

    if om.Split:
        notes.append("Detail crop was split - only its outer extents were kept")
        return
    if not (om.ShapeSet or rotated):
        return
    loops = list(om.GetCropShape())
    if len(loops) != 1 or not nm.CanHaveShape:
        notes.append("Non-rectangular / rotated crop could not be reproduced - axis-aligned extents used")
        return
    if nm.IsCropRegionShapeValid(loops[0]):
        nm.SetCropShape(loops[0])
    else:
        notes.append("Crop shape rejected by Revit - axis-aligned extents used")


def transfer_basic(old, new, notes):
    attempt(notes, "Scale", lambda: setattr(new, "Scale", old.Scale))
    attempt(notes, "Detail level", lambda: setattr(new, "DetailLevel", old.DetailLevel))
    attempt(notes, "Visual style", lambda: setattr(new, "DisplayStyle", old.DisplayStyle))


def _copy_param_value(src, dst):
    if dst is None or dst.IsReadOnly or not src.HasValue:
        return False
    st = src.StorageType
    if st != dst.StorageType:
        return False
    if st == StorageType.String:
        dst.Set(src.AsString() or "")
    elif st == StorageType.Integer:
        dst.Set(src.AsInteger())
    elif st == StorageType.Double:
        dst.Set(src.AsDouble())
    elif st == StorageType.ElementId:
        dst.Set(src.AsElementId())
    else:
        return False
    return True


BUILTIN_PARAMS = (
    BuiltInParameter.VIEW_DESCRIPTION,             # Title on Sheet
    BuiltInParameter.VIEW_PHASE,
    BuiltInParameter.VIEW_PHASE_FILTER,
    BuiltInParameter.VIEW_DISCIPLINE,
    BuiltInParameter.VIEWER_ANNOTATION_CROP_ACTIVE,
)


def transfer_parameters(old, new, notes):
    for bip in BUILTIN_PARAMS:
        src = old.get_Parameter(bip)
        if src is None:
            continue
        label = src.Definition.Name
        attempt(notes, label, lambda s=src, b=bip: _copy_param_value(s, new.get_Parameter(b)))

    # Project / shared parameters (browser organisation, sub-discipline, etc.)
    for src in old.Parameters:
        d = src.Definition
        if isinstance(d, InternalDefinition) and d.BuiltInParameter != BuiltInParameter.INVALID:
            continue
        attempt(notes, "Parameter '{}'".format(d.Name),
                lambda s=src, dd=d: _copy_param_value(s, new.get_Parameter(dd)))


def _iter_categories():
    for cat in doc.Settings.Categories:
        yield cat
        for sub in cat.SubCategories:
            yield sub


def transfer_vg(old, new, notes):
    """Only called when the detail had no template, i.e. its V/G was its own."""
    failed = [0]
    for cat in _iter_categories():
        cid = cat.Id
        try:
            if old.CanCategoryBeHidden(cid) and new.CanCategoryBeHidden(cid):
                hidden = old.GetCategoryHidden(cid)
                if hidden != new.GetCategoryHidden(cid):
                    new.SetCategoryHidden(cid, hidden)
            if new.IsCategoryOverridable(cid):
                ogs = old.GetCategoryOverrides(cid)
                if not ogs_is_default(ogs):
                    new.SetCategoryOverrides(cid, ogs)
        except Exception:
            failed[0] += 1
    if failed[0]:
        notes.append("{} category V/G settings not carried over".format(failed[0]))

    for fid in safe_ids(old.GetFilters):
        def _filter(f=fid):
            if not new.IsFilterApplied(f):
                new.AddFilter(f)
            new.SetFilterOverrides(f, old.GetFilterOverrides(f))
            new.SetFilterVisibility(f, old.GetFilterVisibility(f))
            new.SetIsFilterEnabled(f, old.GetIsFilterEnabled(f))
        attempt(notes, "Filter '{}'".format(elem_name(doc.GetElement(fid))), _filter)


def transfer_element_graphics(old, new, corners, notes):
    """Per-element overrides and hidden model elements (not template-controlled)."""
    failed = [0]
    for el in FilteredElementCollector(doc, old.Id).WhereElementIsNotElementType():
        if not is_invalid(el.OwnerViewId):
            continue
        try:
            ogs = old.GetElementOverrides(el.Id)
            if not ogs_is_default(ogs):
                new.SetElementOverrides(el.Id, ogs)
        except Exception:
            failed[0] += 1

    xs = [p.X for p in corners]
    ys = [p.Y for p in corners]
    outline = Outline(XYZ(min(xs), min(ys), -1.0e4), XYZ(max(xs), max(ys), 1.0e4))
    hide = List[ElementId]()
    collector = (FilteredElementCollector(doc)
                 .WherePasses(BoundingBoxIntersectsFilter(outline))
                 .WhereElementIsNotElementType())
    for el in collector:
        if not is_invalid(el.OwnerViewId):
            continue
        try:
            if el.IsHidden(old) and el.CanBeHidden(new):
                hide.Add(el.Id)
        except Exception:
            pass
    if hide.Count:
        attempt(notes, "{} hidden elements".format(hide.Count), lambda: new.HideElements(hide))
    if failed[0]:
        notes.append("{} element overrides not carried over".format(failed[0]))


def _copy_ids(old, new, ids):
    return list(ElementTransformUtils.CopyElements(
        old, List[ElementId](ids), new, Transform.Identity, CopyPasteOptions()))


def _copy_single(old, new, eid):
    st = SubTransaction(doc)
    st.Start()
    try:
        res = _copy_ids(old, new, [eid])
        st.Commit()
        return res
    except Exception:
        st.RollBack()
        return None


def transfer_annotations(old, new, notes):
    markers = set(eid_int(i) for i in
                  safe_ids(old.GetReferenceCallouts) +
                  safe_ids(old.GetReferenceSections) +
                  safe_ids(old.GetReferenceElevations))
    if markers:
        notes.append("{} reference marker(s) drawn inside the detail were not carried over".format(len(markers)))

    visible, hidden = [], []
    collector = (FilteredElementCollector(doc)
                 .WherePasses(ElementOwnerViewFilter(old.Id))
                 .WhereElementIsNotElementType())
    for el in collector:
        cat = el.Category
        if cat is None or eid_int(cat.Id) in SKIP_CATS:
            continue
        if eid_int(el.Id) in markers:
            continue
        if isinstance(el, (Sketch, SketchPlane)):
            continue
        if not is_invalid(el.GroupId):
            continue            # copied through its group
        (hidden if el.IsHidden(old) else visible).append(el.Id)

    lost = {}

    def _lose(eid):
        el = doc.GetElement(eid)
        key = el.Category.Name if el is not None and el.Category is not None else "Other"
        lost[key] = lost.get(key, 0) + 1

    if visible:
        st = SubTransaction(doc)
        st.Start()
        try:
            _copy_ids(old, new, visible)
            st.Commit()
        except Exception:
            st.RollBack()
            # Bulk copy failed - fall back to one element at a time
            for eid in visible:
                if _copy_single(old, new, eid) is None:
                    _lose(eid)

    for eid in hidden:
        res = _copy_single(old, new, eid)
        if res is None:
            _lose(eid)
        elif res:
            attempt(notes, "Hidden annotation state", lambda r=res: new.HideElements(List[ElementId](r)))

    if lost:
        parts = ["{} x {}".format(n, k) for k, n in sorted(lost.items())]
        notes.append("Annotations not carried over: " + ", ".join(parts))


def build_reference_index():
    """target view id (int) -> [(reference element id, owner view id)]"""
    index = {}
    for v in FilteredElementCollector(doc).OfClass(View):
        if v.IsTemplate:
            continue
        refs = (safe_ids(v.GetReferenceCallouts) +
                safe_ids(v.GetReferenceSections) +
                safe_ids(v.GetReferenceElevations))
        for rid in refs:
            try:
                target = ReferenceableViewUtils.GetReferencedViewId(doc, rid)
            except Exception:
                continue
            index.setdefault(eid_int(target), []).append((rid, v.Id))
    return index


def retarget_references(old_id, new, ref_index, view_ref_ids, notes):
    for rid, owner in ref_index.get(eid_int(old_id), []):
        if same_id(owner, old_id) or doc.GetElement(rid) is None:
            continue
        attempt(notes, "Reference marker {}".format(eid_int(rid)),
                lambda r=rid: ReferenceableViewUtils.ChangeReferencedView(doc, r, new.Id))

    for vid in view_ref_ids:
        el = doc.GetElement(vid)
        if el is None or same_id(el.OwnerViewId, old_id):
            continue
        p = el.get_Parameter(BuiltInParameter.REFERENCE_VIEWER_TARGET_VIEW)
        if p is not None and same_id(p.AsElementId(), old_id):
            attempt(notes, "View reference {}".format(eid_int(vid)), lambda pp=p: pp.Set(new.Id))


def read_viewport(vp):
    if vp is None:
        return None
    info = {"sheet": vp.SheetId, "center": vp.GetBoxCenter(), "type": vp.GetTypeId(),
            "rotation": vp.Rotation, "number": None, "label": None}
    p = vp.get_Parameter(BuiltInParameter.VIEWPORT_DETAIL_NUMBER)
    if p is not None:
        info["number"] = p.AsString()
    try:
        info["label"] = vp.LabelOffset
    except Exception:
        pass
    return info


def replace_viewport(new, info, notes):
    if not Viewport.CanAddViewToSheet(doc, info["sheet"], new.Id):
        notes.append("Could not be placed back on its sheet")
        return
    vp = Viewport.Create(doc, info["sheet"], new.Id, info["center"])
    if not same_id(vp.GetTypeId(), info["type"]):
        attempt(notes, "Viewport type", lambda: vp.ChangeTypeId(info["type"]))
    attempt(notes, "Viewport rotation", lambda: setattr(vp, "Rotation", info["rotation"]))
    doc.Regenerate()
    vp.SetBoxCenter(info["center"])
    if info["number"]:
        p = vp.get_Parameter(BuiltInParameter.VIEWPORT_DETAIL_NUMBER)
        attempt(notes, "Detail number", lambda: p.Set(info["number"]))
    if info["label"] is not None:
        attempt(notes, "Title offset", lambda: setattr(vp, "LabelOffset", info["label"]))


def apply_template(new, choice, old_tpl, parent, notes):
    def usable(tid):
        return not is_invalid(tid) and new.IsValidViewTemplate(tid)

    parent_tpl = parent.ViewTemplateId
    target = INVALID
    if choice == "keep":
        if is_invalid(old_tpl):
            target = INVALID
        elif usable(old_tpl):
            target = old_tpl
        else:
            notes.append("Template '{}' is not valid for plans".format(elem_name(doc.GetElement(old_tpl))))
            if usable(parent_tpl):
                target = parent_tpl
                notes.append("Parent plan's template applied instead")
    elif choice == "parent":
        if usable(parent_tpl):
            target = parent_tpl
        elif not is_invalid(parent_tpl):
            notes.append("Parent plan's template is not valid here - no template applied")
    elif choice == "none":
        target = INVALID
    else:
        if usable(choice):
            target = choice
        else:
            notes.append("Chosen template is not valid for this view - no template applied")
    new.ViewTemplateId = target


def convert_one(row, vft_id, tpl_choice, ref_index, view_ref_ids):
    old = row.view
    parent = row.parent
    old_id = old.Id
    old_tpl = old.ViewTemplateId
    notes = []

    if vft_id is None:
        vft_id = parent.GetTypeId()
    if not ViewSection.IsViewFamilyTypeValidForCallout(doc, vft_id, parent.Id):
        raise Exception("The chosen floor plan type is not allowed in '{}'".format(row.parent_name))

    vp_info = read_viewport(row.viewport)
    p1, p2, rotated, corners = plan_rect_from_crop(old, parent)

    new = ViewSection.CreateCallout(doc, parent.Id, vft_id, p1, p2)
    doc.Regenerate()
    # Strip any default template from the type so the V/G copy below can apply;
    # the chosen template is applied at the end.
    if not is_invalid(new.ViewTemplateId):
        new.ViewTemplateId = INVALID

    transfer_crop(old, new, rotated, notes)
    transfer_basic(old, new, notes)
    transfer_parameters(old, new, notes)
    if is_invalid(old_tpl):
        transfer_vg(old, new, notes)
    transfer_element_graphics(old, new, corners, notes)
    transfer_annotations(old, new, notes)
    retarget_references(old_id, new, ref_index, view_ref_ids, notes)

    doc.Delete(old_id)              # also removes its viewport and annotations
    new.Name = row.name
    apply_template(new, tpl_choice, old_tpl, parent, notes)
    if vp_info is not None:
        doc.Regenerate()
        replace_viewport(new, vp_info, notes)
    return new.Id, notes


# ----------------------------------------------------------------------------
# UI
# ----------------------------------------------------------------------------
XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Detail to Floor Plan Callout" Width="1130" Height="720" MinWidth="900" MinHeight="460"
        WindowStartupLocation="CenterScreen" Background="#161616"
        FontFamily="Segoe UI" FontSize="12.5" Foreground="#F4F4F4">
  <Window.Resources>
    <Style TargetType="Button">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="Height" Value="32"/>
      <Setter Property="Padding" Value="16,0"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="Bd" Background="{TemplateBinding Background}" CornerRadius="4" Padding="{TemplateBinding Padding}">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True"><Setter TargetName="Bd" Property="Opacity" Value="0.85"/></Trigger>
              <Trigger Property="IsEnabled" Value="False"><Setter Property="Opacity" Value="0.4"/></Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style x:Key="Primary" TargetType="Button" BasedOn="{StaticResource {x:Type Button}}">
      <Setter Property="Background" Value="#F1C21B"/>
      <Setter Property="Foreground" Value="#161616"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
    </Style>
    <Style x:Key="Toggle" TargetType="ToggleButton">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Height" Value="32"/>
      <Setter Property="Padding" Value="14,0"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ToggleButton">
            <Border x:Name="Bd" Background="#393939" CornerRadius="4" Padding="{TemplateBinding Padding}">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsChecked" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#F1C21B"/>
                <Setter Property="Foreground" Value="#161616"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style TargetType="TextBox">
      <Setter Property="Background" Value="#262626"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="CaretBrush" Value="#F4F4F4"/>
      <Setter Property="BorderBrush" Value="#525252"/>
      <Setter Property="BorderThickness" Value="0,0,0,1"/>
      <Setter Property="Padding" Value="8,0"/>
      <Setter Property="Height" Value="32"/>
      <Setter Property="VerticalContentAlignment" Value="Center"/>
    </Style>
    <Style TargetType="CheckBox">
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="CheckBox">
            <Border x:Name="Box" Width="16" Height="16" CornerRadius="3" BorderThickness="1"
                    BorderBrush="#A8A8A8" Background="Transparent">
              <Path x:Name="Tick" Data="M2.5,7.5 L6,11 L12.5,3.5" Stroke="#161616" StrokeThickness="2" Visibility="Collapsed"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsChecked" Value="True">
                <Setter TargetName="Box" Property="Background" Value="#F1C21B"/>
                <Setter TargetName="Box" Property="BorderBrush" Value="#F1C21B"/>
                <Setter TargetName="Tick" Property="Visibility" Value="Visible"/>
              </Trigger>
              <Trigger Property="IsEnabled" Value="False"><Setter Property="Opacity" Value="0.3"/></Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style TargetType="ComboBoxItem">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ComboBoxItem">
            <Border x:Name="Bd" Background="Transparent" Padding="10,7">
              <ContentPresenter/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsHighlighted" Value="True"><Setter TargetName="Bd" Property="Background" Value="#393939"/></Trigger>
              <Trigger Property="IsSelected" Value="True"><Setter Property="Foreground" Value="#F1C21B"/></Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style TargetType="ComboBox">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Height" Value="32"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ComboBox">
            <Grid>
              <ToggleButton Focusable="False" ClickMode="Press" Cursor="Hand"
                  IsChecked="{Binding IsDropDownOpen, Mode=TwoWay, RelativeSource={RelativeSource TemplatedParent}}">
                <ToggleButton.Template>
                  <ControlTemplate TargetType="ToggleButton">
                    <Border x:Name="Bd" Background="#393939" BorderBrush="#525252" BorderThickness="1" CornerRadius="4">
                      <Path HorizontalAlignment="Right" VerticalAlignment="Center" Margin="0,0,12,0"
                            Data="M0,0 L4,4 L8,0" Stroke="#A8A8A8" StrokeThickness="1.5"/>
                    </Border>
                    <ControlTemplate.Triggers>
                      <Trigger Property="IsMouseOver" Value="True"><Setter TargetName="Bd" Property="BorderBrush" Value="#F1C21B"/></Trigger>
                    </ControlTemplate.Triggers>
                  </ControlTemplate>
                </ToggleButton.Template>
              </ToggleButton>
              <ContentPresenter IsHitTestVisible="False" Margin="10,0,30,0" VerticalAlignment="Center"
                  Content="{TemplateBinding SelectionBoxItem}"
                  ContentTemplate="{TemplateBinding SelectionBoxItemTemplate}"/>
              <Popup IsOpen="{TemplateBinding IsDropDownOpen}" Placement="Bottom" AllowsTransparency="True"
                     Focusable="False" PopupAnimation="Fade">
                <Border Background="#262626" BorderBrush="#525252" BorderThickness="1" CornerRadius="4" MaxHeight="320"
                        MinWidth="{Binding ActualWidth, RelativeSource={RelativeSource TemplatedParent}}">
                  <ScrollViewer VerticalScrollBarVisibility="Auto"><ItemsPresenter/></ScrollViewer>
                </Border>
              </Popup>
            </Grid>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
  </Window.Resources>

  <Grid Margin="18">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <StackPanel Grid.Row="0" Margin="0,0,0,14">
      <TextBlock Text="Detail Callouts &#x2192; Floor Plan Callouts" FontSize="18" FontWeight="SemiBold"/>
      <TextBlock x:Name="SubTitle" Foreground="#A8A8A8" Margin="0,4,0,0" TextWrapping="Wrap"/>
    </StackPanel>

    <DockPanel Grid.Row="1" Margin="0,0,0,10">
      <ToggleButton x:Name="ApplicableOnly" DockPanel.Dock="Right" Content="Applicable only"
                    IsChecked="True" Margin="10,0,0,0" Style="{StaticResource Toggle}"/>
      <Button x:Name="SelectNone" DockPanel.Dock="Right" Content="Select none" Margin="10,0,0,0"/>
      <Button x:Name="SelectAll" DockPanel.Dock="Right" Content="Select all" Margin="10,0,0,0"/>
      <Grid>
        <TextBox x:Name="SearchBox"/>
        <TextBlock x:Name="SearchHint" Text="Search by view, parent plan or sheet..." IsHitTestVisible="False"
                   Foreground="#6F6F6F" Margin="11,0,0,0" VerticalAlignment="Center"/>
      </Grid>
    </DockPanel>

    <Border Grid.Row="2" Padding="10,6" Margin="0,0,0,4">
      <StackPanel x:Name="HeaderRow" Orientation="Horizontal"/>
    </Border>

    <ScrollViewer Grid.Row="3" VerticalScrollBarVisibility="Auto">
      <StackPanel x:Name="RowsPanel"/>
    </ScrollViewer>

    <Border Grid.Row="4" Background="#262626" CornerRadius="6" Padding="14" Margin="0,12,0,0">
      <Grid>
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="*"/>
          <ColumnDefinition Width="20"/>
          <ColumnDefinition Width="*"/>
        </Grid.ColumnDefinitions>
        <StackPanel Grid.Column="0">
          <TextBlock Text="Floor plan type for the new callouts" Foreground="#A8A8A8" Margin="0,0,0,6"/>
          <ComboBox x:Name="TypeCombo"/>
        </StackPanel>
        <StackPanel Grid.Column="2">
          <TextBlock Text="View template" Foreground="#A8A8A8" Margin="0,0,0,6"/>
          <ComboBox x:Name="TemplateCombo"/>
        </StackPanel>
      </Grid>
    </Border>

    <DockPanel Grid.Row="5" Margin="0,14,0,0">
      <Button x:Name="RunBtn" DockPanel.Dock="Right" Content="Convert selected" Margin="10,0,0,0"
              Style="{StaticResource Primary}"/>
      <Button x:Name="CancelBtn" DockPanel.Dock="Right" Content="Cancel"/>
      <TextBlock x:Name="CountText" Foreground="#A8A8A8" VerticalAlignment="Center"/>
    </DockPanel>
  </Grid>
</Window>
"""

W_CHECK, W_NAME, W_PARENT, W_SCALE, W_SHEET, W_STATUS = 34, 250, 210, 64, 200, 270

_conv = BrushConverter()


def brush(hex_value):
    return _conv.ConvertFromString(hex_value)


BR_CARD = brush("#262626")
BR_TEXT = brush("#F4F4F4")
BR_SUB = brush("#A8A8A8")
BR_OK = brush("#42BE65")
BR_BAD = brush("#FF8389")


def make_cell(text, width, fg, bold=False):
    tb = TextBlock()
    tb.Text = text
    tb.Width = width
    tb.Foreground = fg
    tb.TextTrimming = TextTrimming.CharacterEllipsis
    tb.VerticalAlignment = VerticalAlignment.Center
    tb.Margin = Thickness(0, 0, 12, 0)
    if bold:
        tb.FontWeight = FontWeights.SemiBold
    if text:
        tb.ToolTip = text
    return tb


def show_picker(rows, vft_items, tpl_items):
    win = XamlReader.Parse(XAML)
    try:
        WindowInteropHelper(win).Owner = __revit__.MainWindowHandle
    except Exception:
        pass

    find = win.FindName
    rows_panel = find("RowsPanel")
    header = find("HeaderRow")
    search = find("SearchBox")
    hint = find("SearchHint")
    only_ok = find("ApplicableOnly")
    count_text = find("CountText")
    type_combo = find("TypeCombo")
    tpl_combo = find("TemplateCombo")

    n_ok = len([r for r in rows if r.ok])
    find("SubTitle").Text = (
        u"{} detail callout(s) drawn in plan views, {} can be converted. Each selected one is "
        u"rebuilt as a floor plan callout in the same parent with its settings, annotations, "
        u"references and sheet placement carried over, then the original is deleted."
    ).format(len(rows), n_ok)

    spacer = TextBlock()
    spacer.Width = W_CHECK
    header.Children.Add(spacer)
    for text, w in (("View", W_NAME), ("Parent plan", W_PARENT), ("Scale", W_SCALE),
                    ("Sheet", W_SHEET), ("Status", W_STATUS)):
        header.Children.Add(make_cell(text, w, BR_SUB, bold=True))

    def update_count():
        sel = len([r for r in rows if r.ok and r.checkbox.IsChecked])
        count_text.Text = "{} selected  |  {} applicable  |  {} listed".format(sel, n_ok, len(rows))

    def apply_filter():
        term = (search.Text or "").strip().lower()
        hint.Visibility = Visibility.Collapsed if term else Visibility.Visible
        ok_only = bool(only_ok.IsChecked)
        for r in rows:
            hay = u"{} {} {}".format(r.name, r.parent_name, r.sheet_label).lower()
            show = (not term or term in hay) and (r.ok or not ok_only)
            r.border.Visibility = Visibility.Visible if show else Visibility.Collapsed

    for r in rows:
        border = Border()
        border.Background = BR_CARD
        border.CornerRadius = CornerRadius(4)
        border.Padding = Thickness(10, 8, 10, 8)
        border.Margin = Thickness(0, 0, 0, 4)
        line = StackPanel()
        line.Orientation = Orientation.Horizontal

        cb = CheckBox()
        cb.Width = 16
        cb.Height = 16
        cb.Margin = Thickness(0, 0, W_CHECK - 16, 0)
        cb.VerticalAlignment = VerticalAlignment.Center
        cb.IsEnabled = r.ok
        cb.Checked += RoutedEventHandler(lambda s, e: update_count())
        cb.Unchecked += RoutedEventHandler(lambda s, e: update_count())
        line.Children.Add(cb)

        line.Children.Add(make_cell(r.name, W_NAME, BR_TEXT))
        line.Children.Add(make_cell(r.parent_name, W_PARENT, BR_TEXT))
        line.Children.Add(make_cell(r.scale, W_SCALE, BR_TEXT))
        line.Children.Add(make_cell(r.sheet_label or "-", W_SHEET, BR_TEXT))
        line.Children.Add(make_cell("Ready" if r.ok else r.reason, W_STATUS, BR_OK if r.ok else BR_BAD))

        border.Child = line
        if r.ok:
            def _toggle(s, e, box=cb):
                box.IsChecked = not bool(box.IsChecked)
            border.MouseLeftButtonUp += MouseButtonEventHandler(_toggle)

        r.checkbox = cb
        r.border = border
        rows_panel.Children.Add(border)

    for label in vft_items[0]:
        type_combo.Items.Add(label)
    type_combo.SelectedIndex = 0
    for label in tpl_items[0]:
        tpl_combo.Items.Add(label)
    tpl_combo.SelectedIndex = 0

    def set_visible(state):
        for r in rows:
            if r.ok and r.border.Visibility == Visibility.Visible:
                r.checkbox.IsChecked = state

    def set_none():
        for r in rows:
            r.checkbox.IsChecked = False

    result = {"go": False}

    def on_run(s, e):
        if not [r for r in rows if r.ok and r.checkbox.IsChecked]:
            count_text.Text = "Select at least one callout to convert."
            return
        result["go"] = True
        win.Close()

    search.TextChanged += TextChangedEventHandler(lambda s, e: apply_filter())
    only_ok.Checked += RoutedEventHandler(lambda s, e: apply_filter())
    only_ok.Unchecked += RoutedEventHandler(lambda s, e: apply_filter())
    find("SelectAll").Click += RoutedEventHandler(lambda s, e: set_visible(True))
    find("SelectNone").Click += RoutedEventHandler(lambda s, e: set_none())
    find("CancelBtn").Click += RoutedEventHandler(lambda s, e: win.Close())
    find("RunBtn").Click += RoutedEventHandler(on_run)

    apply_filter()
    update_count()

    frame = DispatcherFrame()

    def on_closed(s, e):
        frame.Continue = False
    win.Closed += EventHandler(on_closed)
    win.Show()
    Dispatcher.PushFrame(frame)

    if not result["go"]:
        return None
    chosen = [r for r in rows if r.ok and r.checkbox.IsChecked]
    return (chosen,
            vft_items[1][type_combo.SelectedIndex],
            tpl_items[1][tpl_combo.SelectedIndex])


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main():
    floor_vfts = [t for t in FilteredElementCollector(doc).OfClass(ViewFamilyType)
                  if t.ViewFamily == ViewFamily.FloorPlan]
    if not floor_vfts:
        forms.alert("This project has no Floor Plan view type.", exitscript=True)
    floor_vfts.sort(key=lambda t: elem_name(t).lower())

    rows = scan(floor_vfts[0].Id)
    if not rows:
        forms.alert("No detail callouts drawn in plan views were found.", exitscript=True)

    plan_templates = [v for v in FilteredElementCollector(doc).OfClass(View)
                      if v.IsTemplate and v.ViewType == ViewType.FloorPlan]
    plan_templates.sort(key=lambda v: v.Name.lower())

    vft_items = ([u"Same type as the parent plan"] + [elem_name(t) for t in floor_vfts],
                 [None] + [t.Id for t in floor_vfts])
    tpl_items = ([u"Keep the detail's template (parent plan's if not plan-compatible)",
                  u"Use the parent plan's template",
                  u"No template"] + [u"Template: {}".format(v.Name) for v in plan_templates],
                 ["keep", "parent", "none"] + [v.Id for v in plan_templates])

    picked = show_picker(rows, vft_items, tpl_items)
    if picked is None:
        script.exit()
    chosen, vft_id, tpl_choice = picked

    ref_index = build_reference_index()
    view_ref_ids = [e.Id for e in FilteredElementCollector(doc)
                    .OfCategory(BuiltInCategory.OST_ReferenceViewer)
                    .WhereElementIsNotElementType()]

    results = []
    tg = TransactionGroup(doc, "Detail to Floor Plan Callouts")
    tg.Start()
    try:
        for row in chosen:
            t = Transaction(doc, "Detail to Floor Plan Callout: {}".format(row.name))
            t.Start()
            try:
                new_id, notes = convert_one(row, vft_id, tpl_choice, ref_index, view_ref_ids)
                status = t.Commit()
                if status == TransactionStatus.Committed:
                    results.append((row.name, True, new_id, notes))
                else:
                    results.append((row.name, False, None, ["Transaction ended as {}".format(status)]))
            except Exception as e:
                if t.HasStarted() and not t.HasEnded():
                    t.RollBack()
                results.append((row.name, False, None, [err_text(e)]))
        tg.Assimilate()
    except Exception:
        if tg.HasStarted() and not tg.HasEnded():
            tg.RollBack()
        raise

    output = script.get_output()
    output.print_md("## Detail callouts converted to floor plan callouts")
    done = len([r for r in results if r[1]])
    output.print_md("**{} of {}** converted.".format(done, len(results)))
    table = []
    for name, ok, new_id, notes in results:
        table.append([name,
                      "Converted" if ok else "Failed",
                      output.linkify(new_id) if ok else "-",
                      "; ".join(notes) if notes else "-"])
    output.print_table(table_data=table,
                       columns=["Detail view", "Result", "New floor plan callout", "Notes"])


main()
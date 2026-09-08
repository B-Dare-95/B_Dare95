# -*- coding: utf-8 -*-
"""Magic 3D Box

Drag a rectangle in a plan, section or elevation view and get a 3D view
whose section box matches what you dragged.

The same named 3D view is reused every run, so the project does not fill
up with throwaway 3D views.

Shift-click the button to reopen the settings window.
"""

__title__ = "Magic\n3D Box"
__author__ = "Mohamed Bedair"

import json
import traceback

import clr
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from System import EventHandler
from System.Collections.Generic import List
from System.Windows import RoutedEventHandler
from System.Windows.Controls import TextChangedEventHandler
from System.Windows.Markup import XamlReader
from System.Windows.Threading import Dispatcher, DispatcherFrame

from Autodesk.Revit.DB import (
    BoundingBoxXYZ,
    BuiltInCategory,
    BuiltInParameter,
    Element,
    ElementCategoryFilter,
    ElementId,
    ElementTypeGroup,
    FilteredElementCollector,
    Level,
    PlanViewPlane,
    PlanViewRange,
    Transaction,
    Transform,
    View3D,
    ViewFamily,
    ViewFamilyType,
    ViewPlan,
    ViewSection,
    XYZ,
)
from Autodesk.Revit.Exceptions import OperationCanceledException
from Autodesk.Revit.UI.Selection import PickBoxStyle

from pyrevit import forms, script

doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

CMD_NAME = "Magic 3D Box"

# Flip to True to get stage-by-stage output in the pyRevit console.
DEBUG = False

MIN_PICK_DIAGONAL = 0.03
MIN_BOX_EDGE = 0.5

TOP_PLANE = PlanViewPlane.CutPlane

DEFAULT_VIEW_NAME = "Magic 3D Box"
DEFAULT_SECTION_DEPTH = 20.0
DEFAULT_PLAN_HEIGHT = 10.0
PLAN_BOTTOM_PADDING = 0.5

NO_TEMPLATE = "<None>"

# Bumped whenever the saved-settings shape changes, so stale entries from
# an older build reopen the settings window instead of being half-read.
SETTINGS_VERSION = 2


def log(msg):
    if DEBUG:
        print("[M3D] {0}".format(msg))


# ---------------------------------------------------------------------------
# Version helpers
# ---------------------------------------------------------------------------

def eid_value(eid):
    """ElementId -> native Python int, across Revit 2024-2027.

    .Value (2025+) hands back a System.Int64 and .IntegerValue a
    System.Int32. IronPython prints the Int64 as '123L' but it is still a
    CLR type, so isinstance(x, (int, long)) is False and json refuses it.
    int() forces a real Python int either way.
    """
    if eid is None:
        return None
    try:
        raw = eid.Value
    except AttributeError:
        raw = eid.IntegerValue
    return int(raw)


def same_id(a, b):
    return eid_value(a) == eid_value(b)


def element_name(el):
    """Read Element.Name safely.

    ElementType re-declares Name with C# 'new' instead of 'override', so
    IronPython cannot disambiguate the two members and el.Name raises
    AttributeError on ViewFamilyType, WallType, FamilySymbol and friends.
    Binding the base-class getter explicitly sidesteps it.
    """
    if el is None:
        return None
    try:
        return Element.Name.__get__(el)
    except Exception:
        pass
    try:
        return el.Name
    except Exception:
        pass
    try:
        param = el.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
        if param is not None:
            return param.AsString()
    except Exception:
        pass
    return "<unnamed {0}>".format(eid_value(el.Id))


# ---------------------------------------------------------------------------
# Settings storage  (single JSON string, no nested dicts in the ini)
# ---------------------------------------------------------------------------

def doc_key(document):
    path = document.PathName or ""
    if not path:
        return "__unsaved__"
    return path.lower()


def _read_store():
    cfg = script.get_config("magic3dbox")
    raw = cfg.get_option("store", "{}")
    try:
        return json.loads(raw)
    except Exception:
        return {}


def load_settings(document):
    settings = _read_store().get(doc_key(document), {})
    if settings.get("v") != SETTINGS_VERSION:
        return {}
    return settings


def save_settings(document, template, view_name):
    store = _read_store()
    store[doc_key(document)] = {
        "v": SETTINGS_VERSION,
        "template_id": eid_value(template.Id) if template else None,
        "template_name": element_name(template) if template else None,
        "view_name": view_name,
    }
    cfg = script.get_config("magic3dbox")
    cfg.store = json.dumps(store)
    script.save_config()


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def collect_3d_templates(document):
    """Every view template that applies to 3D views."""
    out = []
    for view in FilteredElementCollector(document).OfClass(View3D):
        if view.IsTemplate:
            out.append(view)
    out.sort(key=element_name)
    return out


def default_3d_type_id(document):
    """A ViewFamilyType to build the 3D view from. No longer user-facing."""
    try:
        type_id = document.GetDefaultElementTypeId(ElementTypeGroup.ViewType3D)
        if type_id is not None and eid_value(type_id) > 0:
            return type_id
    except Exception:
        log("no default 3D view type:\n" + traceback.format_exc())

    for vft in FilteredElementCollector(document).OfClass(ViewFamilyType):
        if vft.ViewFamily == ViewFamily.ThreeDimensional:
            return vft.Id
    return None


def resolve_template(settings, available):
    """Saved id first, then saved name. None is a legitimate result."""
    saved_id = settings.get("template_id")
    if saved_id is not None:
        for tpl in available:
            if eid_value(tpl.Id) == saved_id:
                return tpl

    saved_name = settings.get("template_name")
    if saved_name:
        for tpl in available:
            if element_name(tpl) == saved_name:
                return tpl

    return None


def find_3d_view(document, name):
    for view in FilteredElementCollector(document).OfClass(View3D):
        if view.IsTemplate:
            continue
        if element_name(view) == name:
            return view
    return None


# ---------------------------------------------------------------------------
# Settings window
# ---------------------------------------------------------------------------

SETTINGS_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Magic 3D Box - Settings"
        Width="430" Height="520"
        WindowStartupLocation="CenterScreen"
        ResizeMode="NoResize"
        Background="#1E1E2E"
        FontFamily="Segoe UI">

  <Window.Resources>

    <Style x:Key="Label" TargetType="TextBlock">
      <Setter Property="Foreground" Value="#A6ADC8"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="Margin" Value="0,0,0,6"/>
    </Style>

    <Style x:Key="Field" TargetType="TextBox">
      <Setter Property="Background" Value="#313244"/>
      <Setter Property="Foreground" Value="#CDD6F4"/>
      <Setter Property="CaretBrush" Value="#F0A500"/>
      <Setter Property="BorderBrush" Value="#45475A"/>
      <Setter Property="BorderThickness" Value="1"/>
      <Setter Property="Padding" Value="8,6"/>
      <Setter Property="FontSize" Value="13"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="TextBox">
            <Border Background="{TemplateBinding Background}"
                    BorderBrush="{TemplateBinding BorderBrush}"
                    BorderThickness="{TemplateBinding BorderThickness}"
                    CornerRadius="6">
              <ScrollViewer x:Name="PART_ContentHost"
                            Margin="{TemplateBinding Padding}"/>
            </Border>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="Chip" TargetType="Button">
      <Setter Property="Foreground" Value="#CDD6F4"/>
      <Setter Property="FontSize" Value="13"/>
      <Setter Property="Height" Value="34"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="bd" Background="{TemplateBinding Background}"
                    CornerRadius="6" Padding="10,0">
              <ContentPresenter VerticalAlignment="Center"
                                HorizontalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="bd" Property="Opacity" Value="0.85"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="TypeItem" TargetType="ListBoxItem">
      <Setter Property="Foreground" Value="#CDD6F4"/>
      <Setter Property="FontSize" Value="13"/>
      <Setter Property="Padding" Value="10,7"/>
      <Setter Property="Margin" Value="0,0,0,3"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ListBoxItem">
            <Border x:Name="bd" Background="Transparent" CornerRadius="6">
              <ContentPresenter Margin="{TemplateBinding Padding}"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="bd" Property="Background" Value="#45475A"/>
              </Trigger>
              <Trigger Property="IsSelected" Value="True">
                <Setter TargetName="bd" Property="Background" Value="#F0A500"/>
                <Setter Property="Foreground" Value="#1E1E2E"/>
                <Setter Property="FontWeight" Value="SemiBold"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

  </Window.Resources>

  <Border Background="#2A2A3C" CornerRadius="10" Margin="10" Padding="18">
    <Grid>
      <Grid.RowDefinitions>
        <RowDefinition Height="Auto"/>
        <RowDefinition Height="Auto"/>
        <RowDefinition Height="Auto"/>
        <RowDefinition Height="*"/>
        <RowDefinition Height="Auto"/>
        <RowDefinition Height="Auto"/>
      </Grid.RowDefinitions>

      <TextBlock Grid.Row="0" Text="Magic 3D Box"
                 Foreground="#F0A500" FontSize="18" FontWeight="SemiBold"
                 Margin="0,0,0,14"/>

      <TextBlock Grid.Row="1" Text="View template"
                 Style="{StaticResource Label}"/>

      <TextBox Grid.Row="2" x:Name="TemplateFilter"
               Style="{StaticResource Field}" Margin="0,0,0,8"/>

      <Border Grid.Row="3" Background="#313244" CornerRadius="6" Padding="6">
        <ListBox x:Name="TemplateList"
                 Background="Transparent" BorderThickness="0"
                 ItemContainerStyle="{StaticResource TypeItem}"
                 ScrollViewer.HorizontalScrollBarVisibility="Disabled"/>
      </Border>

      <StackPanel Grid.Row="4" Margin="0,14,0,0">
        <TextBlock Text="3D view name" Style="{StaticResource Label}"/>
        <TextBox x:Name="ViewName" Style="{StaticResource Field}"/>
      </StackPanel>

      <StackPanel Grid.Row="5" Orientation="Horizontal"
                  HorizontalAlignment="Right" Margin="0,16,0,0">
        <Button x:Name="CancelBtn" Content="Cancel" Width="90"
                Background="#45475A" Style="{StaticResource Chip}"
                Margin="0,0,8,0"/>
        <Button x:Name="OkBtn" Content="Run" Width="110"
                Background="#F0A500" Foreground="#1E1E2E"
                FontWeight="SemiBold" Style="{StaticResource Chip}"/>
      </StackPanel>

    </Grid>
  </Border>
</Window>
"""


def show_settings(available, current_template, current_name):
    """Returns (accepted, template_or_None, view_name).

    'accepted' is separate because <None> is a valid template choice and
    cannot be signalled by returning None on its own.
    """
    window = XamlReader.Parse(SETTINGS_XAML)

    tpl_filter = window.FindName("TemplateFilter")
    tpl_list = window.FindName("TemplateList")
    name_box = window.FindName("ViewName")
    ok_btn = window.FindName("OkBtn")
    cancel_btn = window.FindName("CancelBtn")

    name_box.Text = current_name or DEFAULT_VIEW_NAME

    by_name = {}
    names = [NO_TEMPLATE]
    for tpl in available:
        label = element_name(tpl)
        by_name[label] = tpl
        names.append(label)

    # IronPython 2.7 has no nonlocal - mutable containers instead.
    result = [False, None, None]
    frame = DispatcherFrame()

    def repopulate(sender=None, args=None):
        needle = (tpl_filter.Text or "").strip().lower()
        keep = tpl_list.SelectedItem
        tpl_list.Items.Clear()
        shown = [n for n in names
                 if n == NO_TEMPLATE or not needle or needle in n.lower()]
        for n in shown:
            tpl_list.Items.Add(n)
        if keep is not None and keep in shown:
            tpl_list.SelectedItem = keep
        elif shown:
            tpl_list.SelectedIndex = 0

    repopulate()
    if current_template is not None:
        label = element_name(current_template)
        if label in names:
            tpl_list.SelectedItem = label

    def on_ok(sender, args):
        picked = tpl_list.SelectedItem
        if picked is None:
            return
        result[0] = True
        result[1] = by_name.get(picked)  # None for <None>
        result[2] = (name_box.Text or "").strip() or DEFAULT_VIEW_NAME
        window.Close()

    def on_cancel(sender, args):
        result[0] = False
        window.Close()

    def on_closed(sender, args):
        frame.Continue = False

    # TextChanged needs TextChangedEventHandler, NOT RoutedEventHandler.
    tpl_filter.TextChanged += TextChangedEventHandler(repopulate)
    ok_btn.Click += RoutedEventHandler(on_ok)
    cancel_btn.Click += RoutedEventHandler(on_cancel)
    window.Closed += EventHandler(on_closed)

    window.Topmost = True
    window.Show()
    window.Activate()
    Dispatcher.PushFrame(frame)

    return result[0], result[1], result[2]


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------

def plan_extents(document, view):
    """(bottom, top) elevations for a plan view, in feet."""
    level = view.GenLevel
    base = level.ProjectElevation if level is not None else 0.0
    bottom = base - PLAN_BOTTOM_PADDING
    top = base + DEFAULT_PLAN_HEIGHT

    try:
        vrange = view.GetViewRange()
    except Exception:
        log("no view range, using defaults")
        return bottom, top

    def plane_elev(plane):
        lid = vrange.GetLevelId(plane)
        if same_id(lid, PlanViewRange.Current):
            lvl = level
        else:
            lvl = document.GetElement(lid)
        if isinstance(lvl, Level):
            return lvl.ProjectElevation + vrange.GetOffset(plane)
        return None

    try:
        t = plane_elev(TOP_PLANE)
        if t is not None:
            top = t
    except Exception:
        log("top plane unresolved:\n" + traceback.format_exc())

    try:
        b = plane_elev(PlanViewPlane.BottomClipPlane)
        if b is not None:
            bottom = b - PLAN_BOTTOM_PADDING
    except Exception:
        log("bottom plane unresolved:\n" + traceback.format_exc())

    if top <= bottom:
        top = bottom + DEFAULT_PLAN_HEIGHT

    return bottom, top


def section_depth(view):
    """Far clip offset of a section/elevation, in feet."""
    param = view.get_Parameter(BuiltInParameter.VIEWER_BOUND_OFFSET_FAR)
    if param is not None:
        depth = param.AsDouble()
        if depth > MIN_BOX_EDGE:
            return depth
    return DEFAULT_SECTION_DEPTH


def build_section_box(document, view, p1, p2, from_section):
    """Two picked corners -> an oriented BoundingBoxXYZ.

    Worked in the view's own frame with signed components, so corner order
    does not matter and rotated views need no special case.
    """
    axis_x = view.RightDirection.Normalize()

    if from_section:
        axis_y = view.ViewDirection.Negate().Normalize()
        base = XYZ(p1.X, p1.Y, min(p1.Z, p2.Z))
        height = abs(p2.Z - p1.Z)
        depth = section_depth(view)
    else:
        axis_y = view.UpDirection.Normalize()
        bottom, top = plan_extents(document, view)
        base = XYZ(p1.X, p1.Y, bottom)
        height = top - bottom
        depth = p2.Subtract(p1).DotProduct(axis_y)

    axis_z = axis_x.CrossProduct(axis_y).Normalize()
    width = p2.Subtract(p1).DotProduct(axis_x)

    # Slide the origin to whichever corner is minimal on each local axis.
    origin = base.Add(axis_x.Multiply(min(0.0, width))) \
                 .Add(axis_y.Multiply(min(0.0, depth)))

    width = max(abs(width), MIN_BOX_EDGE)
    depth = max(abs(depth), MIN_BOX_EDGE)
    height = max(height, MIN_BOX_EDGE)

    log("box w={0:.2f} d={1:.2f} h={2:.2f}".format(width, depth, height))

    transform = Transform.Identity
    transform.Origin = origin
    transform.BasisX = axis_x
    transform.BasisY = axis_y
    transform.BasisZ = axis_z

    bbox = BoundingBoxXYZ()
    bbox.Enabled = True
    bbox.Min = XYZ(0.0, 0.0, 0.0)
    bbox.Max = XYZ(width, depth, height)
    bbox.Transform = transform
    return bbox


# ---------------------------------------------------------------------------
# 3D view handling
# ---------------------------------------------------------------------------

def apply_template(view3d, template):
    """Apply the chosen template, or clear it when <None> was picked."""
    param = view3d.get_Parameter(BuiltInParameter.VIEW_TEMPLATE)
    if param is None or param.IsReadOnly:
        return
    if template is None:
        param.Set(ElementId.InvalidElementId)
    else:
        param.Set(template.Id)


def prepare_3d_view(view3d, source_view):
    """Settings the template does not control. Read-only params are skipped."""
    try:
        view3d.CropBoxActive = False
        view3d.CropBoxVisible = False
    except Exception:
        log("crop box locked by template:\n" + traceback.format_exc())

    target = view3d.get_Parameter(BuiltInParameter.VIEW_PHASE)
    source = source_view.get_Parameter(BuiltInParameter.VIEW_PHASE)
    if target is not None and source is not None and not target.IsReadOnly:
        target.Set(source.AsElementId())


def section_box_ids(view3d):
    """Return a real List[ElementId].

    GetDependentElements hands back an ICollection[ElementId]; wrapping it
    in list() makes a Python list, which IronPython will not marshal back
    into ICollection for SetElementIds / ShowElements.
    """
    cat_filter = ElementCategoryFilter(BuiltInCategory.OST_SectionBox)
    ids = List[ElementId]()
    for eid in view3d.GetDependentElements(cat_filter):
        ids.Add(eid)
    return ids


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    active_view = uidoc.ActiveGraphicalView

    if isinstance(active_view, ViewPlan):
        from_section = False
    elif isinstance(active_view, ViewSection):
        from_section = True
    else:
        forms.alert("Run this tool from a plan, section or elevation view.",
                    title=CMD_NAME)
        return

    type_id = default_3d_type_id(doc)
    if type_id is None:
        forms.alert("This project has no 3D view family type.",
                    title=CMD_NAME)
        return

    templates = collect_3d_templates(doc)
    settings = load_settings(doc)

    template = resolve_template(settings, templates)
    view_name = settings.get("view_name") or DEFAULT_VIEW_NAME

    configured = bool(settings.get("view_name"))
    lost = settings.get("template_id") is not None and template is None

    try:
        forced = bool(__shiftclick__)
    except NameError:
        forced = False

    if not configured or lost or forced:
        accepted, template, view_name = show_settings(
            templates, template, view_name)
        if not accepted:
            return
        save_settings(doc, template, view_name)

    # --- pick -------------------------------------------------------------
    prompt = "Drag a rectangle around the zone (hold the left mouse button)"
    while True:
        try:
            picked = uidoc.Selection.PickBox(PickBoxStyle.Crossing, prompt)
        except OperationCanceledException:
            return

        if picked.Max.DistanceTo(picked.Min) >= MIN_PICK_DIAGONAL:
            break

        if not forms.alert(
            "Hold the left mouse button down while dragging the rectangle.\n\n"
            "Try again?",
            title=CMD_NAME, yes=True, no=True,
        ):
            return

    bbox = build_section_box(doc, active_view, picked.Min, picked.Max,
                             from_section)

    # --- apply ------------------------------------------------------------
    view3d = find_3d_view(doc, view_name)
    created = view3d is None

    t = Transaction(doc, CMD_NAME)
    t.Start()
    try:
        if created:
            view3d = View3D.CreateIsometric(doc, type_id)
            try:
                Element.Name.__set__(view3d, view_name)
            except Exception:
                view_name = "{0} {1}".format(view_name, eid_value(view3d.Id))
                Element.Name.__set__(view3d, view_name)

        apply_template(view3d, template)
        prepare_3d_view(view3d, active_view)
        view3d.SetSectionBox(bbox)

        try:
            view3d.IsSectionBoxActive = True
        except Exception:
            log("IsSectionBoxActive not settable on this version")

        box_on = view3d.IsSectionBoxActive
        t.Commit()
    except Exception:
        t.RollBack()
        forms.alert("Could not apply the section box.\n\n{0}".format(
            traceback.format_exc()), title=CMD_NAME)
        return

    save_settings(doc, template, view_name)

    if not box_on:
        forms.alert(
            "The section box was set but is switched off in '{0}'.\n\n"
            "That view template controls Section Box. Uncheck it in the "
            "template, or pick a different template with Shift-click.".format(
                element_name(template) or NO_TEMPLATE),
            title=CMD_NAME)

    # --- show -------------------------------------------------------------
    uidoc.ActiveView = view3d

    box_ids = section_box_ids(view3d)
    hidden = view3d.GetCategoryHidden(
        ElementId(BuiltInCategory.OST_SectionBox)
    )

    if box_ids.Count and not hidden:
        uidoc.Selection.SetElementIds(box_ids)
        uidoc.ShowElements(box_ids)
        return

    for uiview in uidoc.GetOpenUIViews():
        if same_id(uiview.ViewId, view3d.Id):
            uiview.ZoomToFit()
            break


try:
    main()
except Exception:
    forms.alert("{0} failed.\n\n{1}".format(CMD_NAME, traceback.format_exc()),
                title=CMD_NAME)
# -*- coding: utf-8 -*-
"""Stair Clearance

Draws the clear-height reference line above a stair run in a Section or
Elevation view.

Workflow
--------
1. Choose whether the stair is in the host model or in a link (Revit needs a
   different pick mode for each, so it has to be settled before picking).
2. Pick the line style + vertical offset (default 2100 mm) once at the start.
3. Keep picking stair runs until Esc. Nothing is written to the model while
   picking - every run is measured, then all lines are created together in a
   single transaction and a report window is shown at the end.

Each point on the line is the nosing tip of one step: the top of riser i,
taken from the riser positions rather than from the ends of the run path, so a
run whose last tread carries on past the final riser still stops on the riser.

IronPython 2.7 / Revit 2024-2027.
"""

__title__ = "Stair\nClear Height"
__author__ = "Mohamed Bedair"

import clr

clr.AddReference("System")
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")

from System import EventHandler
from System.Windows import RoutedEventHandler
from System.Windows.Controls import TextChangedEventHandler
from System.Windows.Markup import XamlReader
from System.Windows.Threading import Dispatcher, DispatcherFrame

from Autodesk.Revit.DB import (
    BuiltInCategory,
    BuiltInParameter,
    ElementId,
    GeometryInstance,
    GraphicsStyleType,
    Line,
    Options,
    RevitLinkInstance,
    Solid,
    Transaction,
    TransactionGroup,
    Transform,
    ViewDetailLevel,
    ViewSection,
    ViewType,
    XYZ,
)
from Autodesk.Revit.DB.Architecture import Stairs, StairsRun
from Autodesk.Revit.UI import (
    TaskDialog,
    TaskDialogCommandLinkId,
    TaskDialogCommonButtons,
    TaskDialogResult,
)
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
import Autodesk.Revit.Exceptions as RvtEx

from pyrevit import revit, forms, script

doc = revit.doc
uidoc = revit.uidoc

MM = 304.8
DEFAULT_OFFSET_MM = 2100.0
TOL = 1e-6
Z_TOL = 1e-4                    # ft, "same elevation" when scanning geometry
SLACK_TOL = 1.0 / MM            # ft, 1 mm slop when matching tread spans
ELEV_CHECK_TOL = 50.0 / MM      # ft, base elevation cross-check against geometry
COLLINEAR_TOL = 0.5 / MM        # ft, below this the nosing points are one line


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def eid_value(element_id):
    """ElementId numeric value - Revit 2025+ uses .Value, older uses .IntegerValue."""
    try:
        return element_id.Value
    except AttributeError:
        return element_id.IntegerValue


def mm_to_ft(value_mm):
    return float(value_mm) / MM


def ft_to_mm(value_ft):
    return float(value_ft) * MM


def fmt_mm(value_ft):
    return "{0:.0f}".format(ft_to_mm(value_ft))


# ---------------------------------------------------------------------------
# Value resolution
#
# The Stairs API scatters these values around and moves them between releases:
# ActualRiserHeight and ActualTreadDepth live on Stairs, not on StairsRun, and
# the built-in parameter names differ across 2024-2027. Each value is chased
# through a chain of sources and the source that answered is recorded.
# ---------------------------------------------------------------------------
def _read_property(element, names):
    for name in names:
        try:
            value = getattr(element, name)
        except Exception:
            continue
        if value is not None:
            return value, "property .{0}".format(name)
    return None, None


def _read_builtin(element, names, as_int=False):
    for name in names:
        bip = getattr(BuiltInParameter, name, None)
        if bip is None:
            continue
        try:
            param = element.get_Parameter(bip)
        except Exception:
            continue
        if param is None or not param.HasValue:
            continue
        try:
            value = param.AsInteger() if as_int else param.AsDouble()
        except Exception:
            continue
        if value is not None:
            return value, "BuiltInParameter.{0}".format(name)
    return None, None


def _read_named(element, names, as_int=False):
    for name in names:
        try:
            param = element.LookupParameter(name)
        except Exception:
            continue
        if param is None or not param.HasValue:
            continue
        try:
            value = param.AsInteger() if as_int else param.AsDouble()
        except Exception:
            continue
        if value is not None:
            return value, "parameter '{0}'".format(name)
    return None, None


def resolve_value(sources, as_int=False):
    """sources = [(element, [props], [builtins], [param names]), ...] -> (value, source)."""
    for element, props, builtins, named in sources:
        if element is None:
            continue
        value, source = _read_property(element, props)
        if value is None:
            value, source = _read_builtin(element, builtins, as_int)
        if value is None:
            value, source = _read_named(element, named, as_int)
        if value is None:
            continue
        try:
            value = int(value) if as_int else float(value)
        except Exception:
            continue
        if as_int or abs(value) > TOL:
            return value, source
    return None, None


# ---------------------------------------------------------------------------
# Shared WPF resources - IBM Carbon palette
# ---------------------------------------------------------------------------
RESOURCES = """
  <Window.Resources>

    <Style x:Key="AccentButton" TargetType="Button">
      <Setter Property="Background" Value="#F1C21B"/>
      <Setter Property="Foreground" Value="#161616"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
      <Setter Property="Height" Value="34"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="bd" Background="{TemplateBinding Background}"
                    CornerRadius="4" Padding="14,0">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="bd" Property="Background" Value="#FFD96A"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="GhostButton" TargetType="Button">
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Height" Value="34"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="bd" Background="{TemplateBinding Background}"
                    CornerRadius="4" Padding="14,0">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="bd" Property="Background" Value="#525252"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style TargetType="TextBox">
      <Setter Property="Background" Value="#262626"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="BorderBrush" Value="#525252"/>
      <Setter Property="BorderThickness" Value="0,0,0,2"/>
      <Setter Property="Padding" Value="8,6"/>
      <Setter Property="CaretBrush" Value="#F1C21B"/>
    </Style>

    <Style TargetType="ListBoxItem">
      <Setter Property="Padding" Value="8,5"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ListBoxItem">
            <Border x:Name="bd" Background="Transparent" CornerRadius="3"
                    Padding="{TemplateBinding Padding}">
              <ContentPresenter/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="bd" Property="Background" Value="#393939"/>
              </Trigger>
              <Trigger Property="IsSelected" Value="True">
                <Setter TargetName="bd" Property="Background" Value="#F1C21B"/>
                <Setter Property="Foreground" Value="#161616"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style TargetType="CheckBox">
      <Setter Property="Foreground" Value="#A8A8A8"/>
      <Setter Property="VerticalContentAlignment" Value="Center"/>
    </Style>

  </Window.Resources>
"""

WINDOW_HEAD = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="{title}"
        Width="{width}" Height="{height}"
        WindowStartupLocation="CenterScreen"
        ResizeMode="{resize}"
        Background="#161616"
        Foreground="#F4F4F4"
        FontFamily="Segoe UI" FontSize="12">
"""


# ---------------------------------------------------------------------------
# Settings window
# ---------------------------------------------------------------------------
SETTINGS_BODY = """
  <Grid Margin="18">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <TextBlock Grid.Row="0" Text="STAIR CLEAR HEIGHT LINE"
               FontSize="16" FontWeight="SemiBold" Foreground="#F4F4F4"/>
    <TextBlock Grid.Row="1" Margin="0,4,0,10" TextWrapping="Wrap" Foreground="#A8A8A8"
               Text="Draws the stair pitch line through every nosing tip, offset upwards. Section / Elevation views only."/>

    <Border Grid.Row="2" Background="#262626" CornerRadius="4" Padding="10,7" Margin="0,0,0,14">
      <TextBlock x:Name="SourceLabel" Foreground="#F1C21B" FontWeight="SemiBold"/>
    </Border>

    <TextBlock Grid.Row="3" Text="LINE STYLE" FontSize="11" Foreground="#A8A8A8" Margin="0,0,0,6"/>
    <TextBox Grid.Row="4" x:Name="SearchBox" Margin="0,0,0,8"/>
    <Border Grid.Row="5" Background="#262626" CornerRadius="4" Padding="4">
      <ListBox x:Name="StyleList" Background="Transparent" BorderThickness="0"
               Foreground="#F4F4F4" ScrollViewer.HorizontalScrollBarVisibility="Disabled"/>
    </Border>

    <TextBlock Grid.Row="6" Text="VERTICAL OFFSET (MM)" FontSize="11"
               Foreground="#A8A8A8" Margin="0,16,0,6"/>
    <TextBox Grid.Row="7" x:Name="OffsetBox" Text="2100"/>

    <CheckBox Grid.Row="8" x:Name="NosingCheck" Margin="0,14,0,0" IsChecked="True"
              Content="Measure from the nosing tip (include nosing projection)"/>

    <Grid Grid.Row="9" Margin="0,18,0,0">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="10"/>
        <ColumnDefinition Width="*"/>
      </Grid.ColumnDefinitions>
      <Button Grid.Column="0" x:Name="CancelBtn" Content="Cancel" Style="{StaticResource GhostButton}"/>
      <Button Grid.Column="2" x:Name="OkBtn" Content="Start Picking" Style="{StaticResource AccentButton}"/>
    </Grid>

  </Grid>
</Window>
"""


class SettingsWindow(object):
    """Inline-XAML settings dialog, blocked with Dispatcher.PushFrame."""

    def __init__(self, style_names, source_label):
        self.result = None
        self._all_names = style_names
        self._frame = DispatcherFrame()

        xaml = (WINDOW_HEAD.format(title="Stair Clear Height Line", width=430,
                                   height=610, resize="NoResize")
                + RESOURCES + SETTINGS_BODY)
        self.window = XamlReader.Parse(xaml)
        self.source_label = self.window.FindName("SourceLabel")
        self.search_box = self.window.FindName("SearchBox")
        self.style_list = self.window.FindName("StyleList")
        self.offset_box = self.window.FindName("OffsetBox")
        self.nosing_check = self.window.FindName("NosingCheck")
        self.ok_btn = self.window.FindName("OkBtn")
        self.cancel_btn = self.window.FindName("CancelBtn")

        self.source_label.Text = source_label
        self.offset_box.Text = str(int(DEFAULT_OFFSET_MM))
        self._fill_list(self._all_names)

        self.search_box.TextChanged += TextChangedEventHandler(self.on_search)
        self.ok_btn.Click += RoutedEventHandler(self.on_ok)
        self.cancel_btn.Click += RoutedEventHandler(self.on_cancel)
        self.window.Closed += EventHandler(self.on_closed)

    def _fill_list(self, names):
        self.style_list.Items.Clear()
        for name in names:
            self.style_list.Items.Add(name)
        if self.style_list.Items.Count:
            self.style_list.SelectedIndex = 0

    def on_search(self, sender, args):
        needle = self.search_box.Text.strip().lower()
        if not needle:
            self._fill_list(self._all_names)
            return
        self._fill_list([n for n in self._all_names if needle in n.lower()])

    def on_ok(self, sender, args):
        if self.style_list.SelectedItem is None:
            forms.alert("Pick a line style first.", title="Stair Clear Height Line")
            return
        try:
            offset_mm = float(self.offset_box.Text.strip())
        except ValueError:
            forms.alert("The vertical offset must be a number in millimetres.",
                        title="Stair Clear Height Line")
            return

        self.result = {
            "style_name": self.style_list.SelectedItem,
            "offset_mm": offset_mm,
            "include_nosing": bool(self.nosing_check.IsChecked),
        }
        self.window.Close()

    def on_cancel(self, sender, args):
        self.result = None
        self.window.Close()

    def on_closed(self, sender, args):
        self._frame.Continue = False

    def show(self):
        self.window.Show()
        Dispatcher.PushFrame(self._frame)
        return self.result


# ---------------------------------------------------------------------------
# Report window
# ---------------------------------------------------------------------------
REPORT_BODY = """
  <Grid Margin="18">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <TextBlock Grid.Row="0" Text="STAIR CLEAR HEIGHT LINE - REPORT"
               FontSize="16" FontWeight="SemiBold" Foreground="#F4F4F4"/>

    <Border Grid.Row="1" Background="#262626" CornerRadius="4" Padding="10,8" Margin="0,10,0,14">
      <TextBlock x:Name="SummaryLabel" Foreground="#F1C21B" FontWeight="SemiBold"
                 TextWrapping="Wrap"/>
    </Border>

    <TextBox Grid.Row="2" x:Name="SearchBox" Margin="0,0,0,8"/>

    <Border Grid.Row="3" Background="#262626" CornerRadius="4" Padding="4">
      <ListBox x:Name="LogList" Background="Transparent" BorderThickness="0"
               Foreground="#F4F4F4" FontFamily="Consolas" FontSize="11"
               ScrollViewer.HorizontalScrollBarVisibility="Auto"/>
    </Border>

    <Button Grid.Row="4" x:Name="CloseBtn" Content="Close" Width="130"
            HorizontalAlignment="Right" Margin="0,16,0,0"
            Style="{StaticResource AccentButton}"/>

  </Grid>
</Window>
"""


class ReportWindow(object):
    """Final report - replaces the pyRevit output console."""

    def __init__(self, summary, lines):
        self._all_lines = lines
        self._frame = DispatcherFrame()

        xaml = (WINDOW_HEAD.format(title="Stair Clear Height Line - Report",
                                   width=620, height=540, resize="CanResize")
                + RESOURCES + REPORT_BODY)
        self.window = XamlReader.Parse(xaml)
        self.summary_label = self.window.FindName("SummaryLabel")
        self.search_box = self.window.FindName("SearchBox")
        self.log_list = self.window.FindName("LogList")
        self.close_btn = self.window.FindName("CloseBtn")

        self.summary_label.Text = summary
        self._fill_list(self._all_lines)

        self.search_box.TextChanged += TextChangedEventHandler(self.on_search)
        self.close_btn.Click += RoutedEventHandler(self.on_close)
        self.window.Closed += EventHandler(self.on_closed)

    def _fill_list(self, lines):
        self.log_list.Items.Clear()
        for line in lines:
            self.log_list.Items.Add(line)

    def on_search(self, sender, args):
        needle = self.search_box.Text.strip().lower()
        if not needle:
            self._fill_list(self._all_lines)
            return
        self._fill_list([l for l in self._all_lines if needle in l.lower()])

    def on_close(self, sender, args):
        self.window.Close()

    def on_closed(self, sender, args):
        self._frame.Continue = False

    def show(self):
        self.window.Show()
        Dispatcher.PushFrame(self._frame)


# ---------------------------------------------------------------------------
# line styles
# ---------------------------------------------------------------------------
def collect_line_styles(document):
    """Return {name: GraphicsStyle} for every subcategory of Lines."""
    styles = {}
    lines_cat = document.Settings.Categories.get_Item(BuiltInCategory.OST_Lines)
    for sub in lines_cat.SubCategories:
        gstyle = sub.GetGraphicsStyle(GraphicsStyleType.Projection)
        if gstyle is not None:
            styles[sub.Name] = gstyle
    return styles


# ---------------------------------------------------------------------------
# Selection
#
# ObjectType.Element can only ever return the RevitLinkInstance itself, never an
# element inside it, so linked stairs need ObjectType.LinkedElement - and that
# mode cannot pick host elements. Hence two filters and two pick modes, chosen
# by the user before anything else happens.
# ---------------------------------------------------------------------------
def is_stair_element(element):
    if element is None:
        return False
    if isinstance(element, Stairs) or isinstance(element, StairsRun):
        return True
    cat = element.Category
    if cat is None:
        return False
    cat_id = eid_value(cat.Id)
    return cat_id in (int(BuiltInCategory.OST_Stairs),
                      int(BuiltInCategory.OST_StairsRuns))


class HostStairFilter(ISelectionFilter):

    def AllowElement(self, element):
        return is_stair_element(element)

    def AllowReference(self, reference, point):
        return True


class LinkedStairFilter(ISelectionFilter):
    """Resolves link instance -> link document -> real element before testing it."""

    def __init__(self, host_doc):
        self.host_doc = host_doc

    def AllowElement(self, element):
        # Revit is inconsistent across versions about whether it hands over the
        # link instance or the element inside it, so accept both.
        if isinstance(element, RevitLinkInstance):
            return True
        return is_stair_element(element)

    def AllowReference(self, reference, point):
        # An exception raised inside a selection filter tears the whole pick down
        # with no usable message, so this one is swallowed deliberately.
        try:
            link_inst = self.host_doc.GetElement(reference.ElementId)
            if not isinstance(link_inst, RevitLinkInstance):
                return False
            link_doc = link_inst.GetLinkDocument()
            if link_doc is None:
                return False
            return is_stair_element(link_doc.GetElement(reference.LinkedElementId))
        except Exception:
            return False


def ask_pick_mode():
    """TaskDialog: host model or linked model. Returns 'host', 'link' or None."""
    dialog = TaskDialog("Stair Clear Height Line")
    dialog.MainInstruction = "Where is the stair?"
    dialog.MainContent = ("Revit uses a different pick mode for linked elements, "
                          "so this has to be chosen up front.")
    dialog.AddCommandLink(TaskDialogCommandLinkId.CommandLink1,
                          "Active model",
                          "Pick a stair in the current model.")
    dialog.AddCommandLink(TaskDialogCommandLinkId.CommandLink2,
                          "Linked model",
                          "Pick a stair inside a loaded Revit link.")
    dialog.CommonButtons = TaskDialogCommonButtons.Cancel
    dialog.DefaultButton = TaskDialogResult.Cancel

    result = dialog.Show()
    if result == TaskDialogResult.CommandLink1:
        return "host"
    if result == TaskDialogResult.CommandLink2:
        return "link"
    return None


def pick_stair_runs(mode, host_filter, link_filter):
    """Pick once and return (runs, owner_document, transform). Raises on Esc."""
    if mode == "host":
        reference = uidoc.Selection.PickObject(
            ObjectType.Element, host_filter,
            "Select a stair or stair run (Esc to finish)")
        element = doc.GetElement(reference.ElementId)
        owner_doc = doc
        transform = Transform.Identity
    else:
        reference = uidoc.Selection.PickObject(
            ObjectType.LinkedElement, link_filter,
            "Select a stair or stair run inside a link (Esc to finish)")
        link_inst = doc.GetElement(reference.ElementId)
        if not isinstance(link_inst, RevitLinkInstance):
            return [], None, None
        owner_doc = link_inst.GetLinkDocument()
        if owner_doc is None:
            return [], None, None
        element = owner_doc.GetElement(reference.LinkedElementId)
        transform = link_inst.GetTotalTransform()

    if element is None:
        return [], owner_doc, transform

    if isinstance(element, StairsRun):
        return [element], owner_doc, transform

    if isinstance(element, Stairs):
        runs = []
        for run_id in element.GetStairsRuns():
            run = owner_doc.GetElement(run_id)
            if run is not None:
                runs.append(run)
        return runs, owner_doc, transform

    return [], owner_doc, transform


# ---------------------------------------------------------------------------
# Geometry - nosing tip points
# ---------------------------------------------------------------------------
def run_solids(run):
    opts = Options()
    opts.ComputeReferences = False
    opts.IncludeNonVisibleObjects = False
    opts.DetailLevel = ViewDetailLevel.Medium

    solids = []
    geo = run.get_Geometry(opts)
    if geo is None:
        return solids

    for obj in geo:
        if isinstance(obj, Solid):
            solids.append(obj)
        elif isinstance(obj, GeometryInstance):
            for sub in obj.GetInstanceGeometry():
                if isinstance(sub, Solid):
                    solids.append(sub)
    return [s for s in solids if s.Volume > TOL]


def run_highest_point(run):
    """Average XY of the highest vertices of the run solid - marks the top end."""
    best_z = None
    top_points = []

    for solid in run_solids(run):
        for edge in solid.Edges:
            for pt in edge.Tessellate():
                if best_z is None or pt.Z > best_z + Z_TOL:
                    best_z = pt.Z
                    top_points = [pt]
                elif abs(pt.Z - best_z) <= Z_TOL:
                    top_points.append(pt)

    if top_points:
        x = sum(p.X for p in top_points) / len(top_points)
        y = sum(p.Y for p in top_points) / len(top_points)
        return XYZ(x, y, best_z)

    bbox = run.get_BoundingBox(None)
    if bbox is None:
        return None
    return XYZ((bbox.Min.X + bbox.Max.X) * 0.5,
               (bbox.Min.Y + bbox.Max.Y) * 0.5,
               bbox.Max.Z)


def path_is_reversed(curves, top_point):
    """True when GetStairsPath() runs from the top of the run down to the bottom."""
    if top_point is None:
        return False
    start = curves[0].GetEndPoint(0)
    end = curves[-1].GetEndPoint(1)
    d_start = XYZ(top_point.X - start.X, top_point.Y - start.Y, 0.0).GetLength()
    d_end = XYZ(top_point.X - end.X, top_point.Y - end.Y, 0.0).GetLength()
    return d_start < d_end


def sample_path(curves, length_along):
    """Point + unit tangent at a given arc length along a chain of curves."""
    walked = 0.0
    for curve in curves:
        seg_len = curve.Length
        if length_along <= walked + seg_len + 1e-9:
            u = (length_along - walked) / seg_len if seg_len > 1e-9 else 0.0
            u = max(0.0, min(1.0, u))
            tangent = curve.ComputeDerivatives(u, True).BasisX
            if tangent.GetLength() > TOL:
                tangent = tangent.Normalize()
            return curve.Evaluate(u, True), tangent
        walked += seg_len

    last = curves[-1]
    tangent = last.ComputeDerivatives(1.0, True).BasisX
    if tangent.GetLength() > TOL:
        tangent = tangent.Normalize()
    return last.Evaluate(1.0, True), tangent


def parent_stairs(run, owner_doc):
    try:
        stairs_id = run.StairsId
    except Exception:
        return None
    if stairs_id is None or stairs_id == ElementId.InvalidElementId:
        return None
    return owner_doc.GetElement(stairs_id)


class RunGeometry(object):
    """Nosing tip points of one StairsRun, in that run's own document coordinates."""

    def __init__(self, run, owner_doc, include_nosing):
        self.run = run
        self.error = None
        self.notes = []
        self.points = []
        self.nosing = 0.0

        stairs = parent_stairs(run, owner_doc)
        run_type = owner_doc.GetElement(run.GetTypeId())

        curves = None
        try:
            curves = list(run.GetStairsPath())
        except Exception as ex:
            self.error = "Could not read the run path: {0}".format(ex)
            return
        if not curves:
            self.error = "GetStairsPath() returned nothing for this run."
            return

        self.path_length = sum(c.Length for c in curves)

        # -- riser count ---------------------------------------------------
        self.risers, _ = resolve_value(
            [(run, ["ActualRisersNumber", "ActualNumRisers"],
              ["STAIRS_RUN_ACTUAL_NUM_RISERS", "STAIRS_ACTUAL_NUM_RISERS"],
              ["Actual Number of Risers", "Actual Riser Number"]),
             (stairs, ["ActualRisersNumber", "ActualNumRisers"],
              ["STAIRS_ACTUAL_NUM_RISERS"],
              ["Actual Number of Risers"])],
            as_int=True)

        # -- riser height --------------------------------------------------
        self.riser_height, _ = resolve_value(
            [(run, ["ActualRiserHeight"],
              ["STAIRS_RUN_ACTUAL_RISER_HEIGHT", "STAIRS_ACTUAL_RISER_HEIGHT"],
              ["Actual Riser Height"]),
             (stairs, ["ActualRiserHeight"],
              ["STAIRS_ACTUAL_RISER_HEIGHT"],
              ["Actual Riser Height"])])

        # -- tread depth ----------------------------------------------------
        self.tread_depth, _ = resolve_value(
            [(run, ["ActualTreadDepth"],
              ["STAIRS_RUN_ACTUAL_TREAD_DEPTH", "STAIRS_ACTUAL_TREAD_DEPTH"],
              ["Actual Tread Depth"]),
             (stairs, ["ActualTreadDepth"],
              ["STAIRS_ACTUAL_TREAD_DEPTH"],
              ["Actual Tread Depth"])])

        # -- total rise, for the fallbacks ---------------------------------
        self.rise, _ = resolve_value(
            [(run, ["Height"], ["STAIRS_RUN_HEIGHT"], ["Relative Height", "Height"])])

        top_point = run_highest_point(run)
        self.reversed_path = path_is_reversed(curves, top_point)
        base_z = curves[-1].GetEndPoint(1).Z if self.reversed_path \
            else curves[0].GetEndPoint(0).Z

        if self.rise is None and top_point is not None:
            self.rise = top_point.Z - base_z

        # -- fill the gaps --------------------------------------------------
        if self.riser_height is None:
            if self.risers and self.rise:
                self.riser_height = self.rise / float(self.risers)
                self.notes.append("Riser height was not published by the API - "
                                  "derived from the run geometry.")
            else:
                self.error = ("Riser height could not be read from the run, the parent "
                              "stair, or derived from the geometry.")
                return

        if not self.risers:
            if self.rise:
                self.risers = int(round(self.rise / self.riser_height))
            elif self.tread_depth:
                self.risers = int(round(self.path_length / self.tread_depth)) + 1
        if not self.risers or self.risers < 1:
            self.error = "Riser count could not be established."
            return

        # -- cross-check the base elevation against the geometry ------------
        # GetStairsPath() sits at the run's base, but if a build reports it
        # level-relative the whole line lands at the wrong height. The top of
        # the solid is the reliable anchor.
        if top_point is not None:
            expected_top = base_z + self.risers * self.riser_height
            if abs(expected_top - top_point.Z) > ELEV_CHECK_TOL:
                base_z = top_point.Z - self.risers * self.riser_height
                self.notes.append(
                    "Path elevation disagreed with the run geometry by {0} mm - "
                    "base taken from the top of the solid instead."
                    .format(fmt_mm(abs(expected_top - top_point.Z))))
        self.base_z = base_z

        # -- nosing projection ----------------------------------------------
        if include_nosing:
            nosing, _ = resolve_value(
                [(run_type, ["NosingLength"],
                  ["STAIRS_TRISERTYPE_NOSING_LENGTH", "STAIRSTYPE_NOSING_LENGTH"],
                  ["Nosing Length"])])
            self.nosing = nosing or 0.0

        # -- where the risers sit along the path -----------------------------
        # The path spans the whole run footprint, which is NOT the same as the
        # span between the first and last riser: a run that ends with a tread
        # carries on one full tread past its top riser, and a run that begins
        # with a tread starts one tread before its bottom riser. Anchoring on
        # the path ends would drag the line onto the tread end instead of the
        # nosing, so the risers are spaced by tread depth from the bottom riser.
        divisions = self.risers - 1
        start_offset = 0.0
        step_length = self.path_length / divisions if divisions > 0 else 0.0

        if self.tread_depth and self.tread_depth > TOL and divisions > 0:
            riser_span = divisions * self.tread_depth
            slack = self.path_length - riser_span
            if slack > -SLACK_TOL:
                step_length = self.tread_depth
                begins_with_riser, _ = resolve_value(
                    [(run_type, ["BeginsWithRiser"],
                      ["STAIRSTYPE_BEGIN_WITH_RISER", "STAIRS_RUNTYPE_BEGIN_WITH_RISER"],
                      ["Begin with Riser"])],
                    as_int=True)
                if begins_with_riser is not None and begins_with_riser == 0 \
                        and slack >= self.tread_depth - SLACK_TOL:
                    start_offset = self.tread_depth
                if slack > SLACK_TOL:
                    self.notes.append(
                        "Run footprint runs {0} mm past the riser span - points "
                        "anchored on the risers, not on the ends of the path."
                        .format(fmt_mm(slack)))
            else:
                self.notes.append(
                    "Riser span exceeds the path length - points spread evenly "
                    "along the path instead of by tread depth.")
        elif divisions > 0:
            self.notes.append("Tread depth unavailable - points spread evenly "
                              "along the path.")

        # -- the points ------------------------------------------------------
        for i in range(self.risers):
            along = start_offset + i * step_length
            along = max(0.0, min(self.path_length, along))
            if self.reversed_path:
                along = self.path_length - along

            point, tangent = sample_path(curves, along)
            if self.reversed_path:
                tangent = tangent.Negate()
            if self.nosing > TOL:
                point = point.Subtract(tangent.Multiply(self.nosing))

            self.points.append(
                XYZ(point.X, point.Y, self.base_z + (i + 1) * self.riser_height))


# ---------------------------------------------------------------------------
# View plane maths
# ---------------------------------------------------------------------------
def project_to_view_plane(view, point):
    normal = view.ViewDirection
    distance = point.Subtract(view.Origin).DotProduct(normal)
    return point.Subtract(normal.Multiply(distance))


def view_up_vector(view):
    """World Z projected onto the view plane - equals UpDirection for upright views."""
    normal = view.ViewDirection
    up = XYZ.BasisZ.Subtract(normal.Multiply(XYZ.BasisZ.DotProduct(normal)))
    if up.GetLength() < 1e-6:
        return view.UpDirection
    return up.Normalize()


def points_are_collinear(points, tolerance):
    if len(points) < 3:
        return True
    start = points[0]
    axis = points[-1].Subtract(start)
    if axis.GetLength() < TOL:
        return True
    axis = axis.Normalize()
    for point in points[1:-1]:
        if point.Subtract(start).CrossProduct(axis).GetLength() > tolerance:
            return False
    return True


def build_line_segments(points, min_length):
    """One line for a straight run, chained segments for a curved one."""
    if len(points) < 2:
        return []

    if points_are_collinear(points, COLLINEAR_TOL):
        if points[0].DistanceTo(points[-1]) < min_length:
            return []
        return [Line.CreateBound(points[0], points[-1])]

    segments = []
    for i in range(len(points) - 1):
        if points[i].DistanceTo(points[i + 1]) >= min_length:
            segments.append(Line.CreateBound(points[i], points[i + 1]))
    return segments


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main():
    view = doc.ActiveView

    if view is None or view.IsTemplate:
        forms.alert("Open a section or elevation view and run the tool again.",
                    title="Stair Clear Height Line", exitscript=True)

    if not isinstance(view, ViewSection) or \
            view.ViewType not in (ViewType.Section, ViewType.Elevation):
        forms.alert("This tool only runs in a Section or Elevation view.\n\n"
                    "Current view is a {0}.".format(view.ViewType),
                    title="Stair Clear Height Line", exitscript=True)

    mode = ask_pick_mode()
    if mode is None:
        script.exit()

    line_styles = collect_line_styles(doc)
    if not line_styles:
        forms.alert("No line styles found in this project.",
                    title="Stair Clear Height Line", exitscript=True)

    source_label = "Active model" if mode == "host" else "Linked model"
    settings = SettingsWindow(sorted(line_styles.keys()), source_label).show()
    if not settings:
        script.exit()

    graphics_style = line_styles[settings["style_name"]]
    include_nosing = settings["include_nosing"]
    up_offset = view_up_vector(view).Multiply(mm_to_ft(settings["offset_mm"]))
    min_length = doc.Application.ShortCurveTolerance

    host_filter = HostStairFilter()
    link_filter = LinkedStairFilter(doc)

    log = []
    seen_runs = set()
    created_total = 0
    run_count = 0
    failed = False

    # -- picking phase -------------------------------------------------------
    # A transaction has to be committed before Revit will draw anything, so each
    # pick gets its own transaction and the line appears straight away. They all
    # sit inside one TransactionGroup, which is assimilated at the end so the
    # whole operation collapses into a single undo entry.
    group = TransactionGroup(doc, "Stair Clear Height Line")
    group.Start()

    while True:
        try:
            runs, owner_doc, transform = pick_stair_runs(mode, host_filter, link_filter)
        except RvtEx.OperationCanceledException:
            break
        except Exception as ex:
            log.append("Selection failed: {0}".format(ex))
            break

        if not runs:
            log.append("Nothing usable was picked - pick again or press Esc.")
            continue

        # measure first - reading geometry needs no transaction
        batch = []
        for run in runs:
            run_id = eid_value(run.Id)
            if run_id in seen_runs:
                log.append("Run {0}  |  already drawn, skipped.".format(run_id))
                continue

            geom = RunGeometry(run, owner_doc, include_nosing)
            if geom.error:
                log.append("Run {0}  |  {1}".format(run_id, geom.error))
                continue

            in_view = []
            for point in geom.points:
                world = transform.OfPoint(point)
                in_view.append(project_to_view_plane(view, world).Add(up_offset))

            segments = build_line_segments(in_view, min_length)
            if not segments:
                log.append("Run {0}  |  resulting line is too short, skipped."
                           .format(run_id))
                continue

            batch.append((run_id, geom, segments))

        if not batch:
            continue

        transaction = Transaction(doc, "Stair Clear Height Line")
        transaction.Start()
        try:
            for run_id, geom, segments in batch:
                for segment in segments:
                    detail_curve = doc.Create.NewDetailCurve(view, segment)
                    detail_curve.LineStyle = graphics_style
                    created_total += 1
                seen_runs.add(run_id)
                run_count += 1
                log.append("Run {0}  |  {1} risers @ {2} mm  |  {3} nosing points  |  "
                           "nosing {4} mm  |  {5} line(s)"
                           .format(run_id, geom.risers, fmt_mm(geom.riser_height),
                                   len(geom.points), fmt_mm(geom.nosing), len(segments)))
                for note in geom.notes:
                    log.append("         - {0}".format(note))
            transaction.Commit()
            uidoc.RefreshActiveView()
        except Exception as ex:
            transaction.RollBack()
            log.append("Run {0}  |  creation failed, that pick was rolled back: {1}"
                       .format(batch[0][0], ex))

    # -- collapse every pick into one undo entry -----------------------------
    try:
        if created_total:
            group.Assimilate()
        else:
            group.RollBack()
    except Exception as ex:
        failed = True
        log.append("Could not assimilate the transaction group: {0}".format(ex))

    # -- report --------------------------------------------------------------
    if failed:
        summary = "Finished with errors - see the log below."
    elif created_total:
        summary = ("{0} line(s) created across {1} run(s), offset {2:.0f} mm, "
                   "line style '{3}'. All of it is one undo step."
                   .format(created_total, run_count, settings["offset_mm"],
                           settings["style_name"]))
    else:
        summary = "Nothing was created."

    if not log:
        log = ["No runs were picked."]

    ReportWindow(summary, log).show()


main()
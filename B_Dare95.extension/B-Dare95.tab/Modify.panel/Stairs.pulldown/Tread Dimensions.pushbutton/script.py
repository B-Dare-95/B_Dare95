# -*- coding: utf-8 -*-
"""Stair Run Dimension

Pick a stair (host model or linked model) in a plan view, pick which run to
dimension, and the tool creates a single linear dimension along the run's
total going, then writes:

    Prefix : "<N> EQ. TREADS @ <D>MM = "
    Suffix : "MM"

so the dimension reads e.g.  10 EQ. TREADS @ 275MM = 2750 MM
"""

__title__ = "Stair Run\nDimension"
__author__ = "Mohamed Bedair"
__doc__ = ("Dimension a stair run's total going and write "
           "'N EQ. TREADS @ DMM = ' / 'MM' into the dimension Prefix / Suffix. "
           "Works on host and linked stairs.")

import clr

clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")
clr.AddReference("System.Xml")

from Autodesk.Revit.DB import (
    BuiltInCategory,
    BuiltInParameter,
    DimensionType,
    Element,
    ElementId,
    FilteredElementCollector,
    GeometryInstance,
    Line,
    Options,
    PlanarFace,
    ReferenceArray,
    RevitLinkInstance,
    Solid,
    Transaction,
    ViewDetailLevel,
    ViewPlan,
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
from Autodesk.Revit.Exceptions import OperationCanceledException

from System import EventHandler
from System.Windows import RoutedEventHandler
from System.Windows.Controls import SelectionChangedEventHandler, TextChangedEventHandler
from System.Windows.Input import MouseButtonEventHandler
from System.Windows.Markup import XamlReader
from System.Windows.Threading import Dispatcher, DispatcherFrame


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------

uidoc = __revit__.ActiveUIDocument
doc = uidoc.Document
active_view = doc.ActiveView

FT_TO_MM = 304.8
TOL = 1.0e-9


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def eid_val(element_id):
    """ElementId numeric value - .Value (2025+) with .IntegerValue fallback."""
    try:
        return element_id.Value
    except AttributeError:
        return element_id.IntegerValue


def to_mm(feet):
    return feet * FT_TO_MM


def fmt_mm(value_mm):
    """275.0 -> '275', 274.6 -> '274.6'."""
    if abs(value_mm - round(value_mm)) < 0.05:
        return "{0:.0f}".format(round(value_mm))
    return "{0:.1f}".format(value_mm)


def alert(title, message):
    td = TaskDialog(title)
    td.MainInstruction = title
    td.MainContent = message
    td.Show()


def type_name(element):
    """Read an element type's name three ways - .Name is unreliable in IronPython."""
    name = None
    try:
        name = Element.Name.GetValue(element)
    except Exception:
        name = None
    if not name:
        try:
            name = element.Name
        except Exception:
            name = None
    if not name:
        try:
            param = element.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
            if param is not None:
                name = param.AsString()
        except Exception:
            name = None
    if not name:
        name = "<unnamed id {0}>".format(eid_val(element.Id))
    return name


LINEAR_STYLE_NAMES = ("linear", "linearfixed")


def collect_dimension_types():
    """Returns (linear_types, all_types, problems).

    Each list holds (name, DimensionType) pairs sorted by name. Style is compared
    by string so a mismatched enum identity cannot wipe out the whole list, and
    a type whose StyleType cannot be read is kept rather than dropped.
    """
    linear = []
    every = []
    problems = []

    collector = FilteredElementCollector(doc).OfClass(DimensionType)

    for dim_type in collector:
        name = type_name(dim_type)

        style_text = None
        try:
            style_text = str(dim_type.StyleType)
        except Exception as ex:
            problems.append("{0}: StyleType unreadable -> {1}".format(name, ex))

        every.append((name, dim_type))

        if style_text is None:
            linear.append((name, dim_type))
        elif style_text.strip().lower() in LINEAR_STYLE_NAMES:
            linear.append((name, dim_type))

    linear.sort(key=lambda pair: pair[0].lower())
    every.sort(key=lambda pair: pair[0].lower())
    return linear, every, problems


def flatten(vector):
    """Project a vector onto the XY plane and normalise it."""
    flat = XYZ(vector.X, vector.Y, 0.0)
    if flat.GetLength() < 1.0e-7:
        return None
    return flat.Normalize()


# ---------------------------------------------------------------------------
# Selection filters
#
# ObjectType.Element can only ever return the RevitLinkInstance itself, never a
# element inside it, so linked stairs need ObjectType.LinkedElement - and that
# mode cannot pick host elements. Hence two filters and two pick modes.
# ---------------------------------------------------------------------------

def is_stair_element(element):
    if element is None:
        return False
    if isinstance(element, Stairs) or isinstance(element, StairsRun):
        return True
    cat = element.Category
    if cat is None:
        return False
    cat_id = eid_val(cat.Id)
    return cat_id in (int(BuiltInCategory.OST_Stairs),
                      int(BuiltInCategory.OST_StairsRuns))


class HostStairFilter(ISelectionFilter):
    """Stairs in the active document."""

    def AllowElement(self, element):
        return is_stair_element(element)

    def AllowReference(self, reference, point):
        return True


class LinkedStairFilter(ISelectionFilter):
    """Stairs inside Revit links.

    In LinkedElement mode Revit hands AllowElement the RevitLinkInstance in some
    versions and the linked element in others, so accept both and do the real
    category test in AllowReference, where the linked id is always available.
    """

    def __init__(self, host_doc):
        self.host_doc = host_doc

    def AllowElement(self, element):
        if isinstance(element, RevitLinkInstance):
            return True
        return is_stair_element(element)

    def AllowReference(self, reference, point):
        try:
            link = self.host_doc.GetElement(reference.ElementId)
            if not isinstance(link, RevitLinkInstance):
                return False
            link_doc = link.GetLinkDocument()
            if link_doc is None:
                return False
            linked_id = reference.LinkedElementId
            if linked_id is None or linked_id == ElementId.InvalidElementId:
                return False
            return is_stair_element(link_doc.GetElement(linked_id))
        except Exception:
            # never let a filter exception kill the pick loop
            return False


def ask_source_mode():
    """Returns 'host', 'link' or None."""
    td = TaskDialog("Stair Run Dimension")
    td.MainInstruction = "Where is the stair?"
    td.MainContent = ("Revit uses a different pick mode for linked elements, "
                      "so this has to be chosen up front.")
    td.AddCommandLink(TaskDialogCommandLinkId.CommandLink1,
                      "Host model",
                      "Pick a stair in the current model.")
    td.AddCommandLink(TaskDialogCommandLinkId.CommandLink2,
                      "Linked model",
                      "Pick a stair inside a loaded Revit link.")
    td.CommonButtons = TaskDialogCommonButtons.Cancel
    td.DefaultButton = TaskDialogResult.Cancel

    result = td.Show()
    if result == TaskDialogResult.CommandLink1:
        return "host"
    if result == TaskDialogResult.CommandLink2:
        return "link"
    return None


# ---------------------------------------------------------------------------
# Run data
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Value resolution
#
# The Stairs API scatters these values around and moves them between releases:
# ActualTreadDepth is on Stairs, not StairsRun, and the built-in parameter names
# differ across 2024-2027. Each value is chased through a chain of sources and
# the source that answered is recorded so it can be reported.
# ---------------------------------------------------------------------------

def read_property(element, names):
    for name in names:
        try:
            value = getattr(element, name)
        except Exception:
            continue
        if value is not None:
            return value, "property {0}".format(name)
    return None, None


def read_builtin_param(element, names, as_int=False):
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
        if value:
            return value, "parameter {0}".format(name)
    return None, None


def read_named_param(element, names, as_int=False):
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
        if value:
            return value, "parameter '{0}'".format(name)
    return None, None


def resolve_value(sources, as_int=False):
    """sources = [(element, [prop names], [bip names], [param names]), ...]

    Returns (value, source_description) or (None, None).
    """
    for element, props, bips, named in sources:
        if element is None:
            continue

        value, src = read_property(element, props)
        if value:
            return value, src

        value, src = read_builtin_param(element, bips, as_int)
        if value:
            return value, src

        value, src = read_named_param(element, named, as_int)
        if value:
            return value, src

    return None, None


class RunInfo(object):
    """Everything the tool needs to know about one StairsRun."""

    def __init__(self, run, index, link_instance):
        self.run = run
        self.index = index
        self.link = link_instance
        self.error = None
        self.notes = []

        self.transform = None
        if link_instance is not None:
            self.transform = link_instance.GetTotalTransform()

        # parent Stairs - several values live there, not on the run
        self.stairs = None
        try:
            self.stairs = run.Document.GetElement(run.StairsId)
        except Exception:
            self.stairs = None

        self.width_ft, width_src = resolve_value(
            [(run, ["ActualRunWidth"],
              ["STAIRS_RUN_ACTUAL_RUN_WIDTH", "STAIRS_ATTR_TREAD_WIDTH"],
              ["Actual Run Width", "Width"])])
        if self.width_ft is None:
            self.width_ft = 0.0
            self.notes.append("Run width unavailable - offset measured from the run centreline.")

        self.num_risers, riser_src = resolve_value(
            [(run, ["ActualRisersNumber", "ActualNumRisers"],
              ["STAIRS_RUN_ACTUAL_NUM_RISERS", "STAIRS_ACTUAL_NUM_RISERS"],
              ["Actual Number of Risers"]),
             (self.stairs, ["ActualRisersNumber", "ActualNumRisers"],
              ["STAIRS_ACTUAL_NUM_RISERS"],
              ["Actual Number of Risers"])],
            as_int=True)
        if self.num_risers is None:
            self.num_risers = 0

        self.tread_depth_ft, self.depth_source = resolve_value(
            [(run, ["ActualTreadDepth"],
              ["STAIRS_RUN_ACTUAL_TREAD_DEPTH", "STAIRS_ACTUAL_TREAD_DEPTH"],
              ["Actual Tread Depth", "Tread Depth"]),
             (self.stairs, ["ActualTreadDepth"],
              ["STAIRS_ACTUAL_TREAD_DEPTH"],
              ["Actual Tread Depth", "Tread Depth", "Minimum Tread Depth"])])

        # --- run path (local / link coordinates) -------------------------
        curves = None
        try:
            curves = list(run.GetStairsPath())
        except Exception:
            curves = None

        if not curves:
            self.error = "Could not read the run path (GetStairsPath returned nothing)."
            return

        for crv in curves:
            if not isinstance(crv, Line):
                self.error = "This run is curved / spiral - a single linear dimension does not apply."
                return

        self.p_start_local = curves[0].GetEndPoint(0)
        self.p_end_local = curves[-1].GetEndPoint(1)

        direction = flatten(self.p_end_local - self.p_start_local)
        if direction is None:
            self.error = "The run path has no horizontal extent."
            return
        self.dir_local = direction

        self.going_ft = (self.p_end_local - self.p_start_local).DotProduct(self.dir_local)

        # last resort - derive the tread depth from the geometry itself
        if self.tread_depth_ft is None or self.tread_depth_ft < TOL:
            if self.num_risers > 1:
                self.tread_depth_ft = self.going_ft / float(self.num_risers - 1)
                self.depth_source = "derived from going / (risers - 1)"
                self.notes.append(
                    "Tread depth was not published by the API - derived from the run "
                    "geometry, so the printed depth may be a rounding of the real value.")
            else:
                self.error = ("Tread depth could not be read from the run, the parent "
                              "stair, or derived from the geometry.")
                return

        self.tread_count = int(round(self.going_ft / self.tread_depth_ft))
        if self.tread_count < 1:
            self.error = "Calculated tread count is less than 1."
            return

        # --- host-space equivalents --------------------------------------
        if self.transform is not None:
            self.p_start = self.transform.OfPoint(self.p_start_local)
            self.p_end = self.transform.OfPoint(self.p_end_local)
        else:
            self.p_start = self.p_start_local
            self.p_end = self.p_end_local
        self.dir_host = flatten(self.p_end - self.p_start)

    # -- derived values ---------------------------------------------------

    @property
    def tread_depth_mm(self):
        return to_mm(self.tread_depth_ft)

    @property
    def going_mm(self):
        return to_mm(self.going_ft)

    @property
    def expected_mm(self):
        return self.tread_count * self.tread_depth_mm

    def label(self):
        if self.error:
            return "Run {0}  -  {1}".format(self.index, self.error)
        return "Run {0}   |   {1} treads @ {2} mm   =   {3} mm".format(
            self.index,
            self.tread_count,
            fmt_mm(self.tread_depth_mm),
            fmt_mm(self.expected_mm))


# ---------------------------------------------------------------------------
# Geometry - riser faces at the two ends of the run
# ---------------------------------------------------------------------------

def collect_solids(geometry_element, solids):
    for geo_obj in geometry_element:
        if isinstance(geo_obj, Solid):
            if geo_obj.Volume > 1.0e-6 and geo_obj.Faces.Size > 0:
                solids.append(geo_obj)
        elif isinstance(geo_obj, GeometryInstance):
            collect_solids(geo_obj.GetInstanceGeometry(), solids)


def get_end_references(run_info):
    """Return (start_ref, end_ref, start_gap_mm, end_gap_mm) in the run's own doc."""
    opts = Options()
    opts.ComputeReferences = True
    opts.IncludeNonVisibleObjects = False
    opts.DetailLevel = ViewDetailLevel.Fine

    solids = []
    geom = run_info.run.get_Geometry(opts)
    if geom is None:
        return None, None, None, None
    collect_solids(geom, solids)

    p0 = run_info.p_start_local
    direction = run_info.dir_local
    length = run_info.going_ft

    best_start = [None, 1.0e9]
    best_end = [None, 1.0e9]

    for solid in solids:
        for face in solid.Faces:
            if not isinstance(face, PlanarFace):
                continue
            normal = face.FaceNormal
            # riser / end faces are vertical planes square to the run direction
            if abs(normal.Z) > 0.01:
                continue
            if abs(normal.DotProduct(direction)) < 0.999:
                continue
            face_ref = face.Reference
            if face_ref is None:
                continue
            dist = (face.Origin - p0).DotProduct(direction)
            if abs(dist) < best_start[1]:
                best_start = [face_ref, abs(dist)]
            if abs(dist - length) < best_end[1]:
                best_end = [face_ref, abs(dist - length)]

    return (best_start[0],
            best_end[0],
            to_mm(best_start[1]) if best_start[0] is not None else None,
            to_mm(best_end[1]) if best_end[0] is not None else None)


# ---------------------------------------------------------------------------
# WPF window
# ---------------------------------------------------------------------------

XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Stair Run Dimension"
        Height="580" Width="760"
        WindowStartupLocation="CenterScreen"
        WindowStyle="None" ResizeMode="NoResize"
        ShowInTaskbar="False" Background="#161616">

  <Window.Resources>

    <Style TargetType="TextBlock">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="FontFamily" Value="Segoe UI"/>
      <Setter Property="FontSize" Value="12"/>
    </Style>

    <Style x:Key="Caption" TargetType="TextBlock">
      <Setter Property="Foreground" Value="#A8A8A8"/>
      <Setter Property="FontFamily" Value="Segoe UI"/>
      <Setter Property="FontSize" Value="11"/>
      <Setter Property="Margin" Value="0,0,0,4"/>
    </Style>

    <Style TargetType="TextBox">
      <Setter Property="Background" Value="#262626"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="CaretBrush" Value="#F1C21B"/>
      <Setter Property="BorderBrush" Value="#525252"/>
      <Setter Property="BorderThickness" Value="0,0,0,2"/>
      <Setter Property="Padding" Value="6,5"/>
      <Setter Property="FontFamily" Value="Segoe UI"/>
      <Setter Property="FontSize" Value="12"/>
      <Style.Triggers>
        <Trigger Property="IsFocused" Value="True">
          <Setter Property="BorderBrush" Value="#F1C21B"/>
        </Trigger>
      </Style.Triggers>
    </Style>

    <Style x:Key="Flat" TargetType="Button">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="FontFamily" Value="Segoe UI"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="Padding" Value="16,8"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="Bd" CornerRadius="3"
                    Background="{TemplateBinding Background}"
                    Padding="{TemplateBinding Padding}">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#525252"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="Accent" TargetType="Button" BasedOn="{StaticResource Flat}">
      <Setter Property="Background" Value="#F1C21B"/>
      <Setter Property="Foreground" Value="#161616"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
    </Style>

    <Style x:Key="Radio" TargetType="ToggleButton">
      <Setter Property="Foreground" Value="#A8A8A8"/>
      <Setter Property="Background" Value="#262626"/>
      <Setter Property="FontFamily" Value="Segoe UI"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="Padding" Value="14,7"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ToggleButton">
            <Border x:Name="Bd" CornerRadius="3"
                    Background="{TemplateBinding Background}"
                    Padding="{TemplateBinding Padding}">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#393939"/>
              </Trigger>
              <Trigger Property="IsChecked" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#F1C21B"/>
                <Setter Property="Foreground" Value="#161616"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style TargetType="ListBox">
      <Setter Property="Background" Value="#262626"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="BorderBrush" Value="#393939"/>
      <Setter Property="BorderThickness" Value="1"/>
      <Setter Property="FontFamily" Value="Segoe UI"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="ScrollViewer.HorizontalScrollBarVisibility" Value="Disabled"/>
    </Style>

    <Style TargetType="ListBoxItem">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Padding" Value="8,5"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ListBoxItem">
            <Border x:Name="Bd" Background="Transparent"
                    Padding="{TemplateBinding Padding}">
              <ContentPresenter/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#393939"/>
              </Trigger>
              <Trigger Property="IsSelected" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#F1C21B"/>
                <Setter Property="Foreground" Value="#161616"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

  </Window.Resources>

  <Border BorderBrush="#393939" BorderThickness="1">
    <Grid>
      <Grid.RowDefinitions>
        <RowDefinition Height="Auto"/>
        <RowDefinition Height="*"/>
        <RowDefinition Height="Auto"/>
      </Grid.RowDefinitions>

      <!-- header -->
      <Border x:Name="HeaderBar" Grid.Row="0" Background="#262626" Padding="16,12">
        <Grid>
          <Grid.ColumnDefinitions>
            <ColumnDefinition Width="*"/>
            <ColumnDefinition Width="Auto"/>
          </Grid.ColumnDefinitions>
          <StackPanel Grid.Column="0">
            <TextBlock Text="STAIR RUN DIMENSION" FontSize="14" FontWeight="SemiBold"/>
            <TextBlock x:Name="SubTitle" Text="" Style="{StaticResource Caption}" Margin="0,3,0,0"/>
          </StackPanel>
          <Button x:Name="BtnClose" Grid.Column="1" Content="X" Width="32" Height="28"
                  Style="{StaticResource Flat}" Padding="0" Background="#262626"/>
        </Grid>
      </Border>

      <!-- body -->
      <Grid Grid.Row="1" Margin="16,14,16,10">
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="300"/>
          <ColumnDefinition Width="16"/>
          <ColumnDefinition Width="*"/>
        </Grid.ColumnDefinitions>

        <!-- left : dimension type -->
        <Grid Grid.Column="0">
          <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
          </Grid.RowDefinitions>
          <TextBlock Grid.Row="0" Text="DIMENSION TYPE" Style="{StaticResource Caption}"/>
          <TextBox Grid.Row="1" x:Name="TxtSearch" Margin="0,0,0,6"/>
          <ListBox Grid.Row="2" x:Name="LstTypes"/>
        </Grid>

        <!-- right : options -->
        <StackPanel Grid.Column="2">

          <TextBlock Text="RUN" Style="{StaticResource Caption}"/>
          <ListBox x:Name="LstRuns" Height="86" Margin="0,0,0,12"/>

          <TextBlock Text="OFFSET FROM RUN EDGE (MM)   -   negative flips to the other side"
                     Style="{StaticResource Caption}"/>
          <TextBox x:Name="TxtOffset" Text="500" Margin="0,0,0,12"/>

          <TextBlock Text="PREFIX TEMPLATE   ( {N} = tread count , {D} = tread depth )"
                     Style="{StaticResource Caption}"/>
          <TextBox x:Name="TxtPrefix" Margin="0,0,0,12"/>

          <TextBlock Text="SUFFIX" Style="{StaticResource Caption}"/>
          <TextBox x:Name="TxtSuffix" Text="MM" Margin="0,0,0,12"/>

          <TextBlock Text="PREVIEW" Style="{StaticResource Caption}"/>
          <Border Background="#262626" BorderBrush="#393939" BorderThickness="1" Padding="10,8">
            <TextBlock x:Name="TxtPreview" Text="" Foreground="#F1C21B"
                       FontFamily="Consolas" FontSize="13" TextWrapping="Wrap"/>
          </Border>

        </StackPanel>
      </Grid>

      <!-- footer -->
      <Border Grid.Row="2" Background="#262626" Padding="16,12">
        <Grid>
          <Grid.ColumnDefinitions>
            <ColumnDefinition Width="*"/>
            <ColumnDefinition Width="Auto"/>
          </Grid.ColumnDefinitions>
          <TextBlock x:Name="TxtStatus" Grid.Column="0" VerticalAlignment="Center"
                     Foreground="#A8A8A8" TextWrapping="Wrap" Margin="0,0,12,0"/>
          <StackPanel Grid.Column="1" Orientation="Horizontal">
            <Button x:Name="BtnCancel" Content="Cancel" Style="{StaticResource Flat}" Margin="0,0,8,0"/>
            <Button x:Name="BtnOk" Content="Start Dimensioning" Style="{StaticResource Accent}"/>
          </StackPanel>
        </Grid>
      </Border>

    </Grid>
  </Border>
</Window>
"""


def build_preview(run_info, prefix_template, suffix):
    if run_info is None or run_info.error:
        return ""
    prefix = (prefix_template
              .replace("{N}", str(run_info.tread_count))
              .replace("{D}", fmt_mm(run_info.tread_depth_mm)))
    return "{0}{1} {2}".format(prefix, fmt_mm(run_info.expected_mm), suffix).strip()


def show_options_window(run_infos, preselect_index, dim_types, source_label):
    """Returns a dict with the user's choices, or None if cancelled."""

    window = XamlReader.Parse(XAML)

    sub_title = window.FindName("SubTitle")
    header_bar = window.FindName("HeaderBar")
    txt_search = window.FindName("TxtSearch")
    lst_types = window.FindName("LstTypes")
    lst_runs = window.FindName("LstRuns")
    txt_offset = window.FindName("TxtOffset")
    txt_prefix = window.FindName("TxtPrefix")
    txt_suffix = window.FindName("TxtSuffix")
    txt_preview = window.FindName("TxtPreview")
    txt_status = window.FindName("TxtStatus")
    btn_ok = window.FindName("BtnOk")
    btn_cancel = window.FindName("BtnCancel")
    btn_close = window.FindName("BtnClose")

    sub_title.Text = source_label
    txt_prefix.Text = "{N} EQ. TREADS @ {D}MM = "

    state = {"result": None, "type_map": []}

    # -- dimension types ---------------------------------------------------
    def fill_types(needle):
        lst_types.Items.Clear()
        state["type_map"] = []
        needle = (needle or "").strip().lower()
        for name, dim_type in dim_types:
            if needle and needle not in name.lower():
                continue
            state["type_map"].append(dim_type)
            lst_types.Items.Add(name)
        if lst_types.Items.Count > 0:
            lst_types.SelectedIndex = 0

    fill_types(None)

    # -- runs --------------------------------------------------------------
    for run_info in run_infos:
        lst_runs.Items.Add(run_info.label())
    lst_runs.SelectedIndex = preselect_index

    def current_run():
        idx = lst_runs.SelectedIndex
        if idx < 0 or idx >= len(run_infos):
            return None
        return run_infos[idx]

    # -- preview -----------------------------------------------------------
    def refresh(sender=None, args=None):
        run_info = current_run()
        txt_preview.Text = build_preview(run_info, txt_prefix.Text, txt_suffix.Text)
        if run_info is not None and run_info.error:
            txt_status.Text = run_info.error
            btn_ok.IsEnabled = False
        else:
            txt_status.Text = ("These settings apply to every run you pick. "
                               "Press Esc in the view to finish.")
            btn_ok.IsEnabled = True

    # -- events ------------------------------------------------------------
    def on_search(sender, args):
        fill_types(txt_search.Text)

    txt_search.TextChanged += TextChangedEventHandler(on_search)
    txt_prefix.TextChanged += TextChangedEventHandler(refresh)
    txt_suffix.TextChanged += TextChangedEventHandler(refresh)
    lst_runs.SelectionChanged += SelectionChangedEventHandler(refresh)

    def on_drag(sender, args):
        try:
            window.DragMove()
        except Exception:
            pass

    header_bar.MouseLeftButtonDown += MouseButtonEventHandler(on_drag)

    def on_ok(sender, args):
        run_info = current_run()
        if run_info is None or run_info.error:
            txt_status.Text = "Pick a valid run first."
            return
        if lst_types.SelectedIndex < 0:
            txt_status.Text = "Pick a dimension type."
            return
        try:
            offset_mm = float(txt_offset.Text)
        except ValueError:
            txt_status.Text = "Offset must be a number (mm)."
            return
        state["result"] = {
            "run_info": run_info,
            "dim_type": state["type_map"][lst_types.SelectedIndex],
            "offset_mm": offset_mm,
            "prefix_template": txt_prefix.Text,
            "suffix": txt_suffix.Text,
        }
        window.Close()

    def on_cancel(sender, args):
        state["result"] = None
        window.Close()

    btn_ok.Click += RoutedEventHandler(on_ok)
    btn_cancel.Click += RoutedEventHandler(on_cancel)
    btn_close.Click += RoutedEventHandler(on_cancel)

    refresh()

    frame = DispatcherFrame()

    def on_closed(sender, args):
        frame.Continue = False

    window.Closed += EventHandler(on_closed)
    window.Show()
    Dispatcher.PushFrame(frame)

    return state["result"]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():

    # -- view check - 2D plan views only -----------------------------------
    if active_view is None or active_view.IsTemplate:
        alert("Stair Run Dimension", "Open a 2D plan view and run the tool again.")
        return

    plan_types = (ViewType.FloorPlan, ViewType.CeilingPlan,
                  ViewType.EngineeringPlan, ViewType.AreaPlan)

    if not isinstance(active_view, ViewPlan) or active_view.ViewType not in plan_types:
        alert("Stair Run Dimension",
              "This tool only runs in a 2D plan view (floor, ceiling, structural or "
              "area plan).\n\nCurrent view is a {0}."
              .format(active_view.ViewType))
        return

    # -- dimension types ---------------------------------------------------
    dim_types, all_types, problems = collect_dimension_types()

    if not dim_types:
        if all_types:
            # nothing matched the style filter, but types do exist - show them all
            # rather than blocking the user, and say why.
            dim_types = all_types
            report = ("No type reported a Linear style, so every dimension type in the "
                      "project is listed instead. Pick a linear one.")
            if problems:
                report += "\n\nProblems reading types:\n" + "\n".join(problems[:10])
            alert("Stair Run Dimension", report)
        else:
            report = "No DimensionType elements were found in this document at all."
            if problems:
                report += "\n\n" + "\n".join(problems[:10])
            alert("Stair Run Dimension", report)
            return

    # -- pick mode ---------------------------------------------------------
    mode = ask_source_mode()
    if mode is None:
        return

    if mode == "link":
        object_type = ObjectType.LinkedElement
        pick_filter = LinkedStairFilter(doc)
        prompt = "Select a stair run  -  Esc to finish"
    else:
        object_type = ObjectType.Element
        pick_filter = HostStairFilter()
        prompt = "Select a stair run  -  Esc to finish"

    settings = None
    created = 0
    log = []

    # -- pick / create loop, ends on Esc ------------------------------------
    while True:

        try:
            picked = uidoc.Selection.PickObject(object_type, pick_filter, prompt)
        except OperationCanceledException:
            break
        except Exception as ex:
            alert("Stair Run Dimension", "Selection failed:\n{0}".format(ex))
            break

        resolved = resolve_pick(picked, mode)
        if resolved["error"]:
            alert("Stair Run Dimension", resolved["error"])
            continue

        run_infos = resolved["run_infos"]
        preselect = resolved["preselect"]
        link_instance = resolved["link_instance"]

        # settings are asked once, then reused for every following pick
        if settings is None:
            choice = show_options_window(
                run_infos, preselect, dim_types, resolved["source_label"])
            if choice is None:
                return
            run_info = choice["run_info"]
            settings = {
                "dim_type": choice["dim_type"],
                "offset_mm": choice["offset_mm"],
                "prefix_template": choice["prefix_template"],
                "suffix": choice["suffix"],
            }
        else:
            run_info = run_infos[preselect]

        if run_info.error:
            alert("Stair Run Dimension",
                  "Run {0}: {1}".format(run_info.index, run_info.error))
            continue

        ok, message = create_dimension(run_info, settings, link_instance)
        if ok:
            created += 1
        if message:
            log.append(message)

    # -- session summary ----------------------------------------------------
    if created == 0 and not log:
        return

    lines = ["Dimensions created: {0}".format(created)]
    if log:
        lines.append("")
        lines.extend(log)

    alert("Stair Run Dimension", "\n".join(lines))


def resolve_pick(picked, mode):
    """Turn a picked reference into run data. Never raises."""
    out = {"error": None, "run_infos": None, "preselect": 0,
           "link_instance": None, "source_label": ""}

    host_element = doc.GetElement(picked.ElementId)
    link_instance = None
    source_doc = doc
    element = host_element

    if isinstance(host_element, RevitLinkInstance):
        link_instance = host_element
        source_doc = link_instance.GetLinkDocument()
        if source_doc is None:
            out["error"] = "That link is not loaded."
            return out
        linked_id = picked.LinkedElementId
        if linked_id is None or linked_id == ElementId.InvalidElementId:
            out["error"] = ("The pick returned the link instance rather than an element "
                            "inside it. Nested links are not supported.")
            return out
        element = source_doc.GetElement(linked_id)
    elif mode == "link":
        out["error"] = "That pick did not come from a Revit link."
        return out

    if element is None:
        out["error"] = "Nothing usable was selected."
        return out

    runs = []
    if isinstance(element, StairsRun):
        runs = [element]
    elif isinstance(element, Stairs):
        for run_id in element.GetStairsRuns():
            run_element = source_doc.GetElement(run_id)
            if run_element is not None:
                runs.append(run_element)
    else:
        out["error"] = "Selected element is a {0}, not a stair.".format(
            type(element).__name__)
        return out

    if not runs:
        out["error"] = "That stair has no runs."
        return out

    run_infos = []
    for i, run in enumerate(runs):
        run_infos.append(RunInfo(run, i + 1, link_instance))

    # which run did the click land on?
    preselect = 0
    try:
        click_point = picked.GlobalPoint
        if click_point is not None:
            if link_instance is not None:
                click_point = link_instance.GetTotalTransform().Inverse.OfPoint(click_point)
            best = [0, 1.0e12]
            for i, run_info in enumerate(run_infos):
                if run_info.error:
                    continue
                mid = (run_info.p_start_local + run_info.p_end_local).Multiply(0.5)
                dist = XYZ(mid.X - click_point.X, mid.Y - click_point.Y, 0.0).GetLength()
                if dist < best[1]:
                    best = [i, dist]
            preselect = best[0]
    except Exception:
        preselect = 0

    if link_instance is not None:
        out["source_label"] = "Linked model: {0}".format(source_doc.Title)
    else:
        out["source_label"] = "Host model: {0}".format(doc.Title)

    out["run_infos"] = run_infos
    out["preselect"] = preselect
    out["link_instance"] = link_instance
    return out


def create_dimension(run_info, settings, link_instance):
    """Place one dimension. Returns (created, message_or_None)."""

    # -- references --------------------------------------------------------
    try:
        ref_start, ref_end, gap_start, gap_end = get_end_references(run_info)
    except Exception as ex:
        return False, "Run {0}: geometry unreadable - {1}".format(run_info.index, ex)

    if ref_start is None or ref_end is None:
        return False, ("Run {0}: no dimensionable riser faces at the run ends "
                       "(sloped or non-planar risers).".format(run_info.index))

    slack = run_info.tread_depth_mm * 0.75
    if gap_start > slack or gap_end > slack:
        return False, ("Run {0}: end faces sit {1} mm / {2} mm off the run path ends - "
                       "skipped rather than dimensioned wrong."
                       .format(run_info.index, fmt_mm(gap_start), fmt_mm(gap_end)))

    if link_instance is not None:
        ref_start = ref_start.CreateLinkReference(link_instance)
        ref_end = ref_end.CreateLinkReference(link_instance)

    # -- dimension line, always parallel to the run ------------------------
    direction = run_info.dir_host
    perp = XYZ(direction.Y, -direction.X, 0.0)

    offset_mm = settings["offset_mm"]
    sign = -1.0 if offset_mm < 0 else 1.0
    offset_ft = sign * ((run_info.width_ft * 0.5) + (abs(offset_mm) / FT_TO_MM))
    shift = perp.Multiply(offset_ft)

    z = run_info.p_start.Z
    pt_a = XYZ(run_info.p_start.X, run_info.p_start.Y, z).Add(shift)
    pt_b = XYZ(run_info.p_end.X, run_info.p_end.Y, z).Add(shift)

    if pt_a.DistanceTo(pt_b) < 1.0e-6:
        return False, "Run {0}: dimension line has zero length.".format(run_info.index)

    dim_line = Line.CreateBound(pt_a, pt_b)

    prefix = (settings["prefix_template"]
              .replace("{N}", str(run_info.tread_count))
              .replace("{D}", fmt_mm(run_info.tread_depth_mm)))
    suffix = settings["suffix"]

    # -- create ------------------------------------------------------------
    measured_mm = [None]

    t = Transaction(doc, "Stair Run Dimension")
    t.Start()
    try:
        ref_array = ReferenceArray()
        ref_array.Append(ref_start)
        ref_array.Append(ref_end)

        dim = doc.Create.NewDimension(active_view, dim_line, ref_array,
                                      settings["dim_type"])
        if dim is None:
            raise Exception("NewDimension returned nothing.")

        dim.Prefix = prefix
        if suffix:
            dim.Suffix = suffix

        try:
            if dim.Value is not None:
                measured_mm[0] = to_mm(dim.Value)
        except Exception:
            measured_mm[0] = None

        t.Commit()
    except Exception as ex:
        t.RollBack()
        return False, "Run {0}: creation failed - {1}".format(run_info.index, ex)

    # -- warnings worth carrying to the summary ----------------------------
    if measured_mm[0] is not None:
        if abs(measured_mm[0] - run_info.expected_mm) > 1.0:
            return True, ("Run {0}: reads {1} mm but {2} treads x {3} mm = {4} mm - "
                          "check nosing or an extended top/bottom riser."
                          .format(run_info.index,
                                  fmt_mm(measured_mm[0]),
                                  run_info.tread_count,
                                  fmt_mm(run_info.tread_depth_mm),
                                  fmt_mm(run_info.expected_mm)))

    if run_info.notes:
        return True, "Run {0}: {1}".format(run_info.index, " ".join(run_info.notes))

    return True, None


main()
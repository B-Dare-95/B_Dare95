# -*- coding: utf-8 -*-
"""Callout Creator.

Pick a rectangular region in the active plan view, then place that same callout
region across many plan views at once.

Two modes:
    View Callout       - creates a new plan view per callout, using the same
                         ViewFamilyType as the parent view. Name and view
                         template are set per row.
    Reference Callout  - points each callout at an existing plan or drafting
                         view. Nothing new is created.

Views that cannot display the callout are flagged in the selection list and
skipped on create:
    CROP      - the region falls outside the view's active crop box
    TEMPLATE  - the Callouts category is switched off on the view or its template

Anything else is fair game - a view already placed on a sheet is treated as a
normal target, not flagged.

Target: Revit 2024 - 2027, IronPython 2.7.
"""

__title__ = "Callout\nCreator"
__author__ = "Mohamed Bedair"

import clr

clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")
clr.AddReference("System.Xml")

from Autodesk.Revit.DB import (
    BuiltInCategory,
    BuiltInParameter,
    ElementId,
    FilteredElementCollector,
    Transaction,
    UnitUtils,
    View,
    ViewDrafting,
    ViewPlan,
    ViewSection,
    ViewType,
    XYZ,
)
from Autodesk.Revit.UI.Selection import PickBoxStyle
from Autodesk.Revit.Exceptions import OperationCanceledException

from System import EventHandler
from System.Windows import (
    FontWeights,
    HorizontalAlignment,
    RoutedEventHandler,
    TextTrimming,
    TextWrapping,
    Thickness,
    VerticalAlignment,
)
from System.Windows.Controls import (
    Border,
    CheckBox,
    ComboBox,
    Orientation,
    StackPanel,
    TextBlock,
    TextBox,
)
from System.Windows.Input import MouseButtonEventHandler
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Markup import XamlReader
from System.Windows.Media import BrushConverter
from System.Windows.Threading import Dispatcher, DispatcherFrame

from pyrevit import forms, script

doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
output = script.get_output()


# ---------------------------------------------------------------------------
# palette
# ---------------------------------------------------------------------------

BG = "#161616"
CARD = "#262626"
SURFACE = "#393939"
MUTED = "#525252"
TEXT = "#F4F4F4"
SUBTEXT = "#A8A8A8"
ACCENT = "#F1C21B"
BLOCK_FG = "#FA4D56"
BLOCK_BD = "#5A2E31"
SEL_BG = "#2F2A18"
SEL_BD = "#8A6F12"
DIM_BG = "#1E1E1E"

_BRUSHES = BrushConverter()


def brush(hex_value):
    """Return a SolidColorBrush for a hex string."""
    return _BRUSHES.ConvertFromString(hex_value)


PLAN_VIEW_TYPES = (
    ViewType.FloorPlan,
    ViewType.CeilingPlan,
    ViewType.EngineeringPlan,
    ViewType.AreaPlan,
)


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def eid_value(element_id):
    """ElementId.Value on Revit 2025+, IntegerValue on 2024. Never assume one."""
    if element_id is None:
        return -1
    try:
        return element_id.Value
    except AttributeError:
        return element_id.IntegerValue


def is_valid_id(element_id):
    return element_id is not None and eid_value(element_id) != -1


def builtin_param_id(*candidate_names):
    """First BuiltInParameter that actually exists in this Revit's API, as an
    ElementId. Returns InvalidElementId when none of them do - the callers
    treat that as "assume the template controls it", which is the safe default.
    """
    for name in candidate_names:
        member = getattr(BuiltInParameter, name, None)
        if member is not None:
            try:
                return ElementId(member)
            except Exception:
                continue
    return ElementId.InvalidElementId


CALLOUT_CATEGORY_ID = ElementId(BuiltInCategory.OST_Callouts)

# Callouts sits under Annotation Categories, so the V/G parameter a view
# template controls it through is the annotation one. There is no single
# "categories" parameter - VIS_GRAPHICS_CATEGORIES does not exist.
VG_CATEGORIES_PARAM = builtin_param_id(
    "VIS_GRAPHICS_ANNOTATION",
    "VIS_GRAPHICS_MODEL",
)


def to_metres(internal_length):
    """Internal feet -> metres, across the unit APIs used by 2024 - 2027."""
    try:
        from Autodesk.Revit.DB import UnitTypeId

        return UnitUtils.ConvertFromInternalUnits(internal_length, UnitTypeId.Meters)
    except Exception:
        return internal_length * 0.3048


def graphics_source(target_view, controlled_param_id):
    """Return the view whose graphics settings actually apply.

    If a view template drives the given V/G parameter, the template holds the
    real value and the view's own stored value is stale.
    """
    template_id = target_view.ViewTemplateId
    if not is_valid_id(template_id):
        return target_view

    template = doc.GetElement(template_id)
    if template is None:
        return target_view

    if not is_valid_id(controlled_param_id):
        # could not resolve the V/G parameter on this Revit version - assume the
        # template drives it, which is what an unmodified template does
        return template

    try:
        non_controlled = template.GetNonControlledTemplateParameterIds()
    except Exception:
        return target_view

    wanted = eid_value(controlled_param_id)
    for param_id in non_controlled:
        if eid_value(param_id) == wanted:
            # the template leaves this one alone, so the view owns it
            return target_view
    return template


# ---------------------------------------------------------------------------
# the three blocking checks
# ---------------------------------------------------------------------------


def region_outside_crop(target_view, corner_a, corner_b):
    """True when the picked region leaves the view's active crop box."""
    try:
        if not target_view.CropBoxActive:
            return False
    except Exception:
        return False

    crop = target_view.CropBox
    if crop is None:
        return False

    inverse = crop.Transform.Inverse
    tolerance = 0.0026  # ~0.8 mm in feet, keeps edge picks from false-flagging

    corners = [
        XYZ(corner_a.X, corner_a.Y, 0.0),
        XYZ(corner_b.X, corner_a.Y, 0.0),
        XYZ(corner_b.X, corner_b.Y, 0.0),
        XYZ(corner_a.X, corner_b.Y, 0.0),
    ]

    for corner in corners:
        local = inverse.OfPoint(corner)
        if local.X < crop.Min.X - tolerance or local.X > crop.Max.X + tolerance:
            return True
        if local.Y < crop.Min.Y - tolerance or local.Y > crop.Max.Y + tolerance:
            return True
    return False


def callouts_category_off(target_view):
    """Return the name of whatever switches the Callouts category off, or None."""
    source = graphics_source(target_view, VG_CATEGORIES_PARAM)
    try:
        if source.GetCategoryHidden(CALLOUT_CATEGORY_ID):
            if source.Id != target_view.Id:
                return source.Name
            return target_view.Name
    except Exception:
        return None
    return None


# ---------------------------------------------------------------------------
# model gathering
# ---------------------------------------------------------------------------


class ViewItem(object):
    """One candidate target view plus everything the UI needs about it."""

    def __init__(self, target_view):
        self.view = target_view
        self.name = target_view.Name
        self.checked = False
        self.blocked = False
        self.chip = ""
        self.chip_note = ""
        self.new_name = ""
        self.template_id = ElementId.InvalidElementId
        self.reference_id = ElementId.InvalidElementId
        self.name_box = None
        self.template_box = None
        self.reference_box = None


def collect_plan_views():
    """Every non-template plan view in the document, sorted by name."""
    collector = FilteredElementCollector(doc).OfClass(ViewPlan)
    result = []
    for plan_view in collector:
        if plan_view.IsTemplate:
            continue
        if plan_view.ViewType not in PLAN_VIEW_TYPES:
            continue
        result.append(plan_view)
    result.sort(key=lambda v: v.Name.lower())
    return result


def collect_templates_by_view_type():
    """view type name -> list of (label, ElementId), always led by '(None)'."""
    grouped = {}
    for candidate in FilteredElementCollector(doc).OfClass(View):
        if not candidate.IsTemplate:
            continue
        if candidate.ViewType not in PLAN_VIEW_TYPES:
            continue
        key = str(candidate.ViewType)
        if key not in grouped:
            grouped[key] = []
        grouped[key].append((candidate.Name, candidate.Id))

    for key in grouped:
        grouped[key].sort(key=lambda pair: pair[0].lower())
        grouped[key].insert(0, ("(None)", ElementId.InvalidElementId))
    return grouped


def collect_reference_candidates():
    """Plan and drafting views a reference callout may point at."""
    candidates = []
    for plan_view in FilteredElementCollector(doc).OfClass(ViewPlan):
        if plan_view.IsTemplate or plan_view.ViewType not in PLAN_VIEW_TYPES:
            continue
        candidates.append((plan_view.Name + "  [plan]", plan_view.Id))
    for drafting_view in FilteredElementCollector(doc).OfClass(ViewDrafting):
        if drafting_view.IsTemplate:
            continue
        candidates.append((drafting_view.Name + "  [drafting]", drafting_view.Id))

    candidates.sort(key=lambda pair: pair[0].lower())
    candidates.insert(0, ("-- select a view --", ElementId.InvalidElementId))
    return candidates


def existing_view_names():
    names = set()
    for any_view in FilteredElementCollector(doc).OfClass(View):
        try:
            names.add(any_view.Name.lower())
        except Exception:
            pass
    return names


def build_items(plan_views, corner_a, corner_b, active_view_id):
    """Run the three checks over every candidate view."""
    items = []
    for plan_view in plan_views:
        item = ViewItem(plan_view)

        if region_outside_crop(plan_view, corner_a, corner_b):
            item.blocked = True
            item.chip = "CROP"
            item.chip_note = "Region falls outside the active crop box"
        else:
            offender = callouts_category_off(plan_view)
            if offender is not None:
                item.blocked = True
                item.chip = "TEMPLATE"
                item.chip_note = (
                    u'"' + offender + u'" turns the Callouts category off'
                )

        if not item.blocked:
            item.checked = True

        base = item.name.split(u" - ")[0].split(u" \u2014 ")[0].strip()
        item.new_name = "Callout of " + base
        if eid_value(plan_view.Id) == eid_value(active_view_id):
            item.template_id = plan_view.ViewTemplateId

        items.append(item)
    return items


# ---------------------------------------------------------------------------
# XAML
# ---------------------------------------------------------------------------

XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Callout Creator"
        Width="1220" Height="920" MinWidth="1020" MinHeight="680"
        WindowStartupLocation="CenterScreen"
        WindowStyle="None" ResizeMode="CanResizeWithGrip"
        Background="#161616" Foreground="#F4F4F4"
        FontFamily="IBM Plex Sans, Segoe UI" FontSize="13"
        SnapsToDevicePixels="True" UseLayoutRounding="True">

  <Window.Resources>

    <Style TargetType="TextBlock">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="FontSize" Value="13"/>
    </Style>

    <Style TargetType="TextBox">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="BorderBrush" Value="#525252"/>
      <Setter Property="BorderThickness" Value="1"/>
      <Setter Property="CaretBrush" Value="#F1C21B"/>
      <Setter Property="SelectionBrush" Value="#F1C21B"/>
      <Setter Property="Padding" Value="8,0,8,0"/>
      <Setter Property="VerticalContentAlignment" Value="Center"/>
      <Setter Property="Height" Value="32"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="TextBox">
            <Border CornerRadius="2"
                    Background="{TemplateBinding Background}"
                    BorderBrush="{TemplateBinding BorderBrush}"
                    BorderThickness="{TemplateBinding BorderThickness}">
              <ScrollViewer x:Name="PART_ContentHost"
                            Margin="{TemplateBinding Padding}"
                            VerticalAlignment="Center"/>
            </Border>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style TargetType="CheckBox">
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="CheckBox">
            <Grid Width="17" Height="17" Background="Transparent">
              <Border x:Name="Box" CornerRadius="2" Background="#262626"
                      BorderBrush="#A8A8A8" BorderThickness="1"/>
              <Path x:Name="Tick" Visibility="Collapsed"
                    Data="M 3 8 L 7 12 L 14 4"
                    Stroke="#161616" StrokeThickness="2.2"
                    HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Grid>
            <ControlTemplate.Triggers>
              <Trigger Property="IsChecked" Value="True">
                <Setter TargetName="Box" Property="Background" Value="#F1C21B"/>
                <Setter TargetName="Box" Property="BorderBrush" Value="#F1C21B"/>
                <Setter TargetName="Tick" Property="Visibility" Value="Visible"/>
              </Trigger>
              <Trigger Property="IsEnabled" Value="False">
                <Setter TargetName="Box" Property="Background" Value="#1E1E1E"/>
                <Setter TargetName="Box" Property="BorderBrush" Value="#525252"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="TypeToggle" TargetType="ToggleButton">
      <Setter Property="Height" Value="44"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="FontWeight" Value="Medium"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ToggleButton">
            <Border x:Name="Shell" CornerRadius="4" Background="#262626"
                    BorderBrush="#525252" BorderThickness="1">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsChecked" Value="True">
                <Setter TargetName="Shell" Property="Background" Value="#F1C21B"/>
                <Setter TargetName="Shell" Property="BorderBrush" Value="#F1C21B"/>
                <Setter Property="Foreground" Value="#161616"/>
                <Setter Property="FontWeight" Value="SemiBold"/>
              </Trigger>
              <MultiTrigger>
                <MultiTrigger.Conditions>
                  <Condition Property="IsChecked" Value="False"/>
                  <Condition Property="IsMouseOver" Value="True"/>
                </MultiTrigger.Conditions>
                <Setter TargetName="Shell" Property="Background" Value="#393939"/>
              </MultiTrigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="GhostButton" TargetType="Button">
      <Setter Property="Height" Value="36"/>
      <Setter Property="Padding" Value="14,0,14,0"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="Shell" CornerRadius="4" Background="Transparent"
                    BorderBrush="#525252" BorderThickness="1"
                    Padding="{TemplateBinding Padding}">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="Shell" Property="Background" Value="#262626"/>
                <Setter TargetName="Shell" Property="BorderBrush" Value="#A8A8A8"/>
              </Trigger>
              <Trigger Property="IsEnabled" Value="False">
                <Setter Property="Foreground" Value="#525252"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="PrimaryButton" TargetType="Button">
      <Setter Property="Height" Value="44"/>
      <Setter Property="Padding" Value="24,0,24,0"/>
      <Setter Property="Foreground" Value="#161616"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="Shell" CornerRadius="4" Background="#F1C21B"
                    BorderBrush="#F1C21B" BorderThickness="1"
                    Padding="{TemplateBinding Padding}">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="Shell" Property="Background" Value="#FDDC69"/>
                <Setter TargetName="Shell" Property="BorderBrush" Value="#FDDC69"/>
              </Trigger>
              <Trigger Property="IsEnabled" Value="False">
                <Setter TargetName="Shell" Property="Background" Value="#393939"/>
                <Setter TargetName="Shell" Property="BorderBrush" Value="#393939"/>
                <Setter Property="Foreground" Value="#A8A8A8"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style TargetType="ComboBoxItem">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Padding" Value="10,7,10,7"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ComboBoxItem">
            <Border x:Name="Shell" Background="Transparent"
                    Padding="{TemplateBinding Padding}">
              <ContentPresenter/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsHighlighted" Value="True">
                <Setter TargetName="Shell" Property="Background" Value="#393939"/>
              </Trigger>
              <Trigger Property="IsSelected" Value="True">
                <Setter TargetName="Shell" Property="Background" Value="#4A401A"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style TargetType="ComboBox">
      <Setter Property="Height" Value="32"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ComboBox">
            <Grid TextBlock.Foreground="#F4F4F4">
              <ToggleButton x:Name="Toggle" Focusable="False" ClickMode="Press"
                            IsChecked="{Binding IsDropDownOpen, Mode=TwoWay,
                                        RelativeSource={RelativeSource TemplatedParent}}">
                <ToggleButton.Template>
                  <ControlTemplate TargetType="ToggleButton">
                    <Border x:Name="Face" CornerRadius="2" Background="#393939"
                            BorderBrush="#525252" BorderThickness="1">
                      <Path HorizontalAlignment="Right" VerticalAlignment="Center"
                            Margin="0,0,11,0" Data="M 0 0 L 4.5 5 L 9 0"
                            Stroke="#A8A8A8" StrokeThickness="1.6"/>
                    </Border>
                    <ControlTemplate.Triggers>
                      <Trigger Property="IsMouseOver" Value="True">
                        <Setter TargetName="Face" Property="BorderBrush" Value="#A8A8A8"/>
                      </Trigger>
                    </ControlTemplate.Triggers>
                  </ControlTemplate>
                </ToggleButton.Template>
              </ToggleButton>
              <ContentPresenter IsHitTestVisible="False"
                                Content="{TemplateBinding SelectionBoxItem}"
                                Margin="10,0,28,0" VerticalAlignment="Center"/>
              <Popup x:Name="PART_Popup" Placement="Bottom" Focusable="False"
                     AllowsTransparency="True" PopupAnimation="None"
                     IsOpen="{TemplateBinding IsDropDownOpen}">
                <Border Background="#262626" BorderBrush="#525252" BorderThickness="1"
                        MaxHeight="280" MinWidth="{TemplateBinding ActualWidth}">
                  <ScrollViewer>
                    <StackPanel IsItemsHost="True"/>
                  </ScrollViewer>
                </Border>
              </Popup>
            </Grid>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style TargetType="ScrollBar">
      <Setter Property="Width" Value="9"/>
      <Setter Property="Background" Value="Transparent"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ScrollBar">
            <Grid Background="#1B1B1B">
              <Track x:Name="PART_Track" IsDirectionReversed="True">
                <Track.Thumb>
                  <Thumb>
                    <Thumb.Template>
                      <ControlTemplate TargetType="Thumb">
                        <Border CornerRadius="4" Background="#525252" Margin="2,0,2,0"/>
                      </ControlTemplate>
                    </Thumb.Template>
                  </Thumb>
                </Track.Thumb>
              </Track>
            </Grid>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

  </Window.Resources>

  <Border BorderBrush="#393939" BorderThickness="1">
    <Grid>
      <Grid.RowDefinitions>
        <RowDefinition Height="52"/>
        <RowDefinition Height="58"/>
        <RowDefinition Height="*"/>
        <RowDefinition Height="72"/>
      </Grid.RowDefinitions>

      <!-- title bar -->
      <Border x:Name="TitleBar" Grid.Row="0" Background="#262626"
              BorderBrush="#393939" BorderThickness="0,0,0,1">
        <Grid Margin="16,0,10,0">
          <StackPanel Orientation="Horizontal" VerticalAlignment="Center">
            <TextBlock Text="Callout Creator" FontSize="15" FontWeight="SemiBold"/>
            <Border Width="1" Background="#525252" Margin="12,4,12,4"/>
            <TextBlock Text="B_Dare95 / Views" Foreground="#A8A8A8" FontSize="11"
                       VerticalAlignment="Center"/>
          </StackPanel>
          <Button x:Name="CloseBtn" Style="{StaticResource GhostButton}"
                  Content="Close" Height="30" HorizontalAlignment="Right"
                  VerticalAlignment="Center" Padding="12,0,12,0"/>
        </Grid>
      </Border>

      <!-- region strip -->
      <Border Grid.Row="1" Background="#1E1E1E" BorderBrush="#393939"
              BorderThickness="0,0,0,1">
        <Grid Margin="18,0,18,0">
          <StackPanel Orientation="Horizontal" VerticalAlignment="Center">
            <Border Background="#F1C21B" CornerRadius="3" Padding="8,4,8,4">
              <TextBlock Text="REGION SET" FontSize="10" FontWeight="SemiBold"
                         Foreground="#161616"/>
            </Border>
            <TextBlock x:Name="RegionInfo" Margin="14,0,0,0" VerticalAlignment="Center"/>
          </StackPanel>
          <Button x:Name="RepickBtn" Style="{StaticResource GhostButton}"
                  Content="Re-pick region" Height="34" HorizontalAlignment="Right"
                  VerticalAlignment="Center"/>
        </Grid>
      </Border>

      <!-- body -->
      <Grid Grid.Row="2">
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="404"/>
          <ColumnDefinition Width="*"/>
        </Grid.ColumnDefinitions>

        <!-- left: type + view list -->
        <Border Grid.Column="0" BorderBrush="#393939" BorderThickness="0,0,1,0">
          <Grid Margin="18,18,18,18">
            <Grid.RowDefinitions>
              <RowDefinition Height="Auto"/>
              <RowDefinition Height="Auto"/>
              <RowDefinition Height="Auto"/>
              <RowDefinition Height="Auto"/>
              <RowDefinition Height="*"/>
              <RowDefinition Height="Auto"/>
            </Grid.RowDefinitions>

            <TextBlock Grid.Row="0" Text="1  /  CALLOUT TYPE" FontSize="11"
                       FontWeight="SemiBold" Foreground="#A8A8A8" Margin="0,0,0,10"/>

            <Grid Grid.Row="1" Margin="0,0,0,22">
              <Grid.ColumnDefinitions>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="8"/>
                <ColumnDefinition Width="*"/>
              </Grid.ColumnDefinitions>
              <ToggleButton x:Name="ViewModeBtn" Grid.Column="0"
                            Style="{StaticResource TypeToggle}" Content="View Callout"/>
              <ToggleButton x:Name="RefModeBtn" Grid.Column="2"
                            Style="{StaticResource TypeToggle}" Content="Reference Callout"/>
            </Grid>

            <TextBlock Grid.Row="2" Text="2  /  TARGET PLAN VIEWS" FontSize="11"
                       FontWeight="SemiBold" Foreground="#A8A8A8" Margin="0,0,0,10"/>

            <Grid Grid.Row="3" Margin="0,0,0,12">
              <Grid.ColumnDefinitions>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="8"/>
                <ColumnDefinition Width="Auto"/>
              </Grid.ColumnDefinitions>
              <TextBox x:Name="SearchBox" Grid.Column="0" Height="38"/>
              <ToggleButton x:Name="ApplicableBtn" Grid.Column="2"
                            Style="{StaticResource TypeToggle}" Height="38"
                            Padding="14,0,14,0" Content="Applicable only"/>
            </Grid>

            <ScrollViewer Grid.Row="4" VerticalScrollBarVisibility="Auto"
                          HorizontalScrollBarVisibility="Disabled">
              <StackPanel x:Name="ViewList"/>
            </ScrollViewer>

            <Border Grid.Row="5" BorderBrush="#393939" BorderThickness="0,1,0,0"
                    Margin="0,12,0,0" Padding="0,12,0,0">
              <Grid>
                <TextBlock x:Name="ListFooter" FontSize="11" Foreground="#A8A8A8"/>
                <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
                  <Button x:Name="AllBtn" Style="{StaticResource GhostButton}"
                          Content="All" Height="26" Padding="10,0,10,0"/>
                  <Button x:Name="NoneBtn" Style="{StaticResource GhostButton}"
                          Content="None" Height="26" Padding="10,0,10,0" Margin="6,0,0,0"/>
                </StackPanel>
              </Grid>
            </Border>
          </Grid>
        </Border>

        <!-- right: property rows -->
        <Grid Grid.Column="1" Margin="18,18,18,18">
          <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
          </Grid.RowDefinitions>

          <Grid Grid.Row="0" Margin="0,0,0,4">
            <TextBlock Text="3  /  CALLOUT PROPERTIES" FontSize="11"
                       FontWeight="SemiBold" Foreground="#A8A8A8"/>
            <Button x:Name="FillDownBtn" Style="{StaticResource GhostButton}"
                    Content="Apply row 1 to all" Height="26" Padding="10,0,10,0"
                    HorizontalAlignment="Right" VerticalAlignment="Top"/>
          </Grid>

          <TextBlock x:Name="GridHint" Grid.Row="1" FontSize="12" Foreground="#A8A8A8"
                     Margin="0,0,0,16" TextWrapping="Wrap"/>

          <Border Grid.Row="2" BorderBrush="#393939" BorderThickness="0,0,0,1"
                  Padding="12,0,12,8">
            <StackPanel x:Name="RowsHeader" Orientation="Horizontal"/>
          </Border>

          <ScrollViewer Grid.Row="3" Margin="0,6,0,0" VerticalScrollBarVisibility="Auto"
                        HorizontalScrollBarVisibility="Disabled">
            <StackPanel x:Name="RowsPanel"/>
          </ScrollViewer>
        </Grid>
      </Grid>

      <!-- footer -->
      <Border Grid.Row="3" Background="#262626" BorderBrush="#393939"
              BorderThickness="0,1,0,0">
        <Grid Margin="18,0,18,0">
          <StackPanel VerticalAlignment="Center">
            <TextBlock x:Name="SummaryText"/>
            <TextBlock x:Name="SummarySub" FontSize="11" Foreground="#A8A8A8"
                       Margin="0,3,0,0"/>
          </StackPanel>
          <StackPanel Orientation="Horizontal" HorizontalAlignment="Right"
                      VerticalAlignment="Center">
            <Button x:Name="CancelBtn" Style="{StaticResource GhostButton}"
                    Content="Cancel" Height="44" Padding="20,0,20,0"/>
            <Button x:Name="CreateBtn" Style="{StaticResource PrimaryButton}"
                    Content="Create Callouts" Margin="10,0,0,0"/>
          </StackPanel>
        </Grid>
      </Border>

    </Grid>
  </Border>
</Window>
"""


# ---------------------------------------------------------------------------
# the window
# ---------------------------------------------------------------------------

# column widths, shared by the header and every row (StackPanel layout, so no
# GridLength is ever touched from Python)
COL_INDEX = 34
COL_PARENT_VIEW = 210
COL_NEW_NAME = 300
COL_TEMPLATE = 214
COL_PARENT_REF = 250
COL_REFERENCE = 470


class CalloutCreatorWindow(object):
    """Builds, drives and reports on the Callout Creator window."""

    def __init__(self, items, corner_a, corner_b, templates_by_type, reference_choices):
        self.items = items
        self.corner_a = corner_a
        self.corner_b = corner_b
        self.templates_by_type = templates_by_type
        self.reference_choices = reference_choices

        # mutable containers instead of nonlocal (IronPython 2.7)
        self.mode = ["view"]
        self.result = ["cancel"]
        self.suspend = [False]
        self.applicable_only = [False]

        self.window = XamlReader.Parse(XAML)
        self._bind_elements()
        self._wire_events()

        self.view_mode_btn.IsChecked = True
        self.search_box.Text = ""
        self.region_info.Text = self._region_label()

        self.rebuild_view_list()
        self.rebuild_rows()
        self.update_summary()

    # -- setup ------------------------------------------------------------

    def _bind_elements(self):
        find = self.window.FindName
        self.title_bar = find("TitleBar")
        self.close_btn = find("CloseBtn")
        self.repick_btn = find("RepickBtn")
        self.region_info = find("RegionInfo")
        self.view_mode_btn = find("ViewModeBtn")
        self.ref_mode_btn = find("RefModeBtn")
        self.search_box = find("SearchBox")
        self.applicable_btn = find("ApplicableBtn")
        self.view_list = find("ViewList")
        self.list_footer = find("ListFooter")
        self.all_btn = find("AllBtn")
        self.none_btn = find("NoneBtn")
        self.fill_down_btn = find("FillDownBtn")
        self.grid_hint = find("GridHint")
        self.rows_header = find("RowsHeader")
        self.rows_panel = find("RowsPanel")
        self.summary_text = find("SummaryText")
        self.summary_sub = find("SummarySub")
        self.cancel_btn = find("CancelBtn")
        self.create_btn = find("CreateBtn")

    def _wire_events(self):
        self.title_bar.MouseLeftButtonDown += MouseButtonEventHandler(self.on_drag)
        self.close_btn.Click += RoutedEventHandler(self.on_cancel)
        self.cancel_btn.Click += RoutedEventHandler(self.on_cancel)
        self.repick_btn.Click += RoutedEventHandler(self.on_repick)
        self.create_btn.Click += RoutedEventHandler(self.on_create)
        self.view_mode_btn.Click += RoutedEventHandler(self.on_mode_view)
        self.ref_mode_btn.Click += RoutedEventHandler(self.on_mode_ref)
        self.all_btn.Click += RoutedEventHandler(self.on_check_all)
        self.none_btn.Click += RoutedEventHandler(self.on_check_none)
        self.fill_down_btn.Click += RoutedEventHandler(self.on_fill_down)
        self.applicable_btn.Click += RoutedEventHandler(self.on_applicable_toggled)
        self.search_box.TextChanged += self.on_search

    def _region_label(self):
        width = abs(self.corner_b.X - self.corner_a.X)
        height = abs(self.corner_b.Y - self.corner_a.Y)
        return u"Picked in {0}    {1:.2f} m x {2:.2f} m".format(
            doc.ActiveView.Name, to_metres(width), to_metres(height)
        )

    # -- left list --------------------------------------------------------

    def rebuild_view_list(self):
        self.view_list.Children.Clear()
        needle = self.search_box.Text.strip().lower()

        for item in self.items:
            if self.applicable_only[0] and item.blocked:
                continue
            if needle and needle not in item.name.lower():
                continue
            self.view_list.Children.Add(self._build_view_row(item))

        self.update_footer()

    def _build_view_row(self, item):
        shell = Border()
        shell.Padding = Thickness(11, 9, 11, 9)
        shell.Margin = Thickness(0, 0, 0, 6)
        shell.BorderThickness = Thickness(1)

        if item.blocked:
            shell.Background = brush(DIM_BG)
            shell.BorderBrush = brush(BLOCK_BD)
        elif item.checked:
            shell.Background = brush(SEL_BG)
            shell.BorderBrush = brush(SEL_BD)
        else:
            shell.Background = brush(CARD)
            shell.BorderBrush = brush(SURFACE)

        row = StackPanel()
        row.Orientation = Orientation.Horizontal

        box = CheckBox()
        box.IsChecked = item.checked
        box.IsEnabled = not item.blocked
        box.Margin = Thickness(0, 2, 11, 0)
        box.VerticalAlignment = VerticalAlignment.Top
        box.Tag = item
        box.Click += RoutedEventHandler(self.on_item_toggled)
        row.Children.Add(box)

        stack = StackPanel()
        stack.Width = 316

        label = TextBlock()
        label.Text = item.name
        label.TextWrapping = TextWrapping.Wrap
        label.FontWeight = FontWeights.Medium
        label.Foreground = brush(SUBTEXT if item.blocked else TEXT)
        stack.Children.Add(label)

        if item.chip:
            chip_row = StackPanel()
            chip_row.Orientation = Orientation.Horizontal
            chip_row.Margin = Thickness(0, 5, 0, 0)

            chip_colour = BLOCK_FG

            chip = Border()
            chip.BorderBrush = brush(chip_colour)
            chip.BorderThickness = Thickness(1)
            chip.Padding = Thickness(6, 2, 6, 2)
            chip.Margin = Thickness(0, 0, 7, 0)
            chip.VerticalAlignment = VerticalAlignment.Top

            chip_text = TextBlock()
            chip_text.Text = item.chip
            chip_text.FontSize = 9
            chip_text.Foreground = brush(chip_colour)
            chip.Child = chip_text
            chip_row.Children.Add(chip)

            note = TextBlock()
            note.Text = item.chip_note
            note.FontSize = 11
            note.Foreground = brush(SUBTEXT)
            note.TextWrapping = TextWrapping.Wrap
            note.Width = 316 - 80
            chip_row.Children.Add(note)

            stack.Children.Add(chip_row)

        row.Children.Add(stack)
        shell.Child = row
        return shell

    def update_footer(self):
        selected = len([i for i in self.items if i.checked])
        blocked = len([i for i in self.items if i.blocked])
        if self.applicable_only[0] and blocked:
            self.list_footer.Text = (
                u"{0} selected  /  {1} flagged and hidden  /  {2} plan views".format(
                    selected, blocked, len(self.items)
                )
            )
        else:
            self.list_footer.Text = (
                u"{0} selected  /  {1} flagged  /  {2} plan views".format(
                    selected, blocked, len(self.items)
                )
            )

    # -- right grid -------------------------------------------------------

    def selected_items(self):
        return [i for i in self.items if i.checked and not i.blocked]

    def _header_cell(self, text, width):
        cell = TextBlock()
        cell.Text = text
        cell.Width = width
        cell.FontSize = 10
        cell.Foreground = brush(SUBTEXT)
        cell.Margin = Thickness(0, 0, 8, 0)
        return cell

    def rebuild_rows(self):
        self.suspend[0] = True
        try:
            self.rows_header.Children.Clear()
            self.rows_panel.Children.Clear()

            if self.mode[0] == "view":
                self.grid_hint.Text = (
                    u"One new plan view is created per row, from the same view family "
                    u"type as its parent view."
                )
                self.rows_header.Children.Add(self._header_cell(u"#", COL_INDEX))
                self.rows_header.Children.Add(
                    self._header_cell(u"PARENT VIEW", COL_PARENT_VIEW)
                )
                self.rows_header.Children.Add(
                    self._header_cell(u"NEW VIEW NAME", COL_NEW_NAME)
                )
                self.rows_header.Children.Add(
                    self._header_cell(u"VIEW TEMPLATE", COL_TEMPLATE)
                )
            else:
                self.grid_hint.Text = (
                    u"Each callout points at an existing plan or drafting view. "
                    u"No views are created."
                )
                self.rows_header.Children.Add(self._header_cell(u"#", COL_INDEX))
                self.rows_header.Children.Add(
                    self._header_cell(u"PARENT VIEW", COL_PARENT_REF)
                )
                self.rows_header.Children.Add(
                    self._header_cell(u"REFERENCED VIEW", COL_REFERENCE)
                )

            for index, item in enumerate(self.selected_items()):
                self.rows_panel.Children.Add(self._build_row(index, item))
        finally:
            self.suspend[0] = False

    def _build_row(self, index, item):
        shell = Border()
        shell.Background = brush(CARD)
        shell.BorderBrush = brush(SURFACE)
        shell.BorderThickness = Thickness(1)
        shell.Padding = Thickness(12, 10, 12, 10)
        shell.Margin = Thickness(0, 0, 0, 6)

        row = StackPanel()
        row.Orientation = Orientation.Horizontal

        number = TextBlock()
        number.Text = "%02d" % (index + 1)
        number.Width = COL_INDEX
        number.Foreground = brush(SUBTEXT)
        number.FontSize = 12
        number.VerticalAlignment = VerticalAlignment.Center
        number.Margin = Thickness(0, 0, 8, 0)
        row.Children.Add(number)

        parent = TextBlock()
        parent.Text = item.name
        parent.FontSize = 12
        parent.TextTrimming = TextTrimming.CharacterEllipsis
        parent.VerticalAlignment = VerticalAlignment.Center
        parent.Margin = Thickness(0, 0, 8, 0)
        parent.Width = COL_PARENT_VIEW if self.mode[0] == "view" else COL_PARENT_REF
        parent.ToolTip = item.name
        row.Children.Add(parent)

        if self.mode[0] == "view":
            name_box = TextBox()
            name_box.Text = item.new_name
            name_box.Width = COL_NEW_NAME
            name_box.Margin = Thickness(0, 0, 8, 0)
            name_box.Tag = item
            name_box.TextChanged += self.on_name_changed
            item.name_box = name_box
            row.Children.Add(name_box)

            template_box = ComboBox()
            template_box.Width = COL_TEMPLATE
            choices = self.templates_for(item)
            selected_index = 0
            for position, pair in enumerate(choices):
                template_box.Items.Add(pair[0])
                if eid_value(pair[1]) == eid_value(item.template_id):
                    selected_index = position
            template_box.SelectedIndex = selected_index
            template_box.Tag = item
            template_box.SelectionChanged += self.on_template_changed
            item.template_box = template_box
            row.Children.Add(template_box)
        else:
            reference_box = ComboBox()
            reference_box.Width = COL_REFERENCE
            selected_index = 0
            for position, pair in enumerate(self.reference_choices):
                reference_box.Items.Add(pair[0])
                if eid_value(pair[1]) == eid_value(item.reference_id):
                    selected_index = position
            reference_box.SelectedIndex = selected_index
            reference_box.Tag = item
            reference_box.SelectionChanged += self.on_reference_changed
            item.reference_box = reference_box
            row.Children.Add(reference_box)

        shell.Child = row
        return shell

    def templates_for(self, item):
        key = str(item.view.ViewType)
        if key in self.templates_by_type:
            return self.templates_by_type[key]
        return [("(None)", ElementId.InvalidElementId)]

    def update_summary(self):
        count = len(self.selected_items())
        blocked = len([i for i in self.items if i.blocked])
        if self.mode[0] == "view":
            self.summary_text.Text = u"{0} callouts and {0} new views".format(count)
        else:
            self.summary_text.Text = u"{0} reference callouts".format(count)
        self.summary_sub.Text = (
            u"{0} flagged views are skipped - nothing is created in them.".format(blocked)
        )
        self.create_btn.Content = u"Create {0} Callouts".format(count)
        self.create_btn.IsEnabled = count > 0

    # -- handlers ---------------------------------------------------------

    def on_drag(self, sender, args):
        try:
            self.window.DragMove()
        except Exception:
            pass

    def on_search(self, sender, args):
        if self.suspend[0]:
            return
        self.rebuild_view_list()

    def on_applicable_toggled(self, sender, args):
        self.applicable_only[0] = bool(self.applicable_btn.IsChecked)
        self.rebuild_view_list()

    def on_item_toggled(self, sender, args):
        item = sender.Tag
        item.checked = bool(sender.IsChecked)
        self.rebuild_view_list()
        self.rebuild_rows()
        self.update_summary()

    def on_check_all(self, sender, args):
        for item in self.items:
            if not item.blocked:
                item.checked = True
        self.rebuild_view_list()
        self.rebuild_rows()
        self.update_summary()

    def on_check_none(self, sender, args):
        for item in self.items:
            item.checked = False
        self.rebuild_view_list()
        self.rebuild_rows()
        self.update_summary()

    def on_mode_view(self, sender, args):
        self.mode[0] = "view"
        self.view_mode_btn.IsChecked = True
        self.ref_mode_btn.IsChecked = False
        self.rebuild_rows()
        self.update_summary()

    def on_mode_ref(self, sender, args):
        self.mode[0] = "ref"
        self.view_mode_btn.IsChecked = False
        self.ref_mode_btn.IsChecked = True
        self.rebuild_rows()
        self.update_summary()

    def on_name_changed(self, sender, args):
        if self.suspend[0]:
            return
        item = sender.Tag
        item.new_name = sender.Text
        sender.BorderBrush = brush(MUTED)

    def on_template_changed(self, sender, args):
        if self.suspend[0]:
            return
        item = sender.Tag
        choices = self.templates_for(item)
        index = sender.SelectedIndex
        if 0 <= index < len(choices):
            item.template_id = choices[index][1]

    def on_reference_changed(self, sender, args):
        if self.suspend[0]:
            return
        item = sender.Tag
        index = sender.SelectedIndex
        if 0 <= index < len(self.reference_choices):
            item.reference_id = self.reference_choices[index][1]
        sender.BorderBrush = brush(MUTED)

    def on_fill_down(self, sender, args):
        rows = self.selected_items()
        if len(rows) < 2:
            return
        first = rows[0]
        if self.mode[0] == "view":
            for item in rows[1:]:
                available = [eid_value(p[1]) for p in self.templates_for(item)]
                if eid_value(first.template_id) in available:
                    item.template_id = first.template_id
        else:
            for item in rows[1:]:
                item.reference_id = first.reference_id
        self.rebuild_rows()

    def on_cancel(self, sender, args):
        self.result[0] = "cancel"
        self.window.Close()

    def on_repick(self, sender, args):
        self.result[0] = "repick"
        self.window.Close()

    def on_create(self, sender, args):
        problems = self.validate()
        if problems:
            self.summary_text.Text = u"Fix {0} row(s) before creating".format(
                len(problems)
            )
            self.summary_sub.Text = problems[0]
            return
        self.result[0] = "create"
        self.window.Close()

    # -- validation -------------------------------------------------------

    def validate(self):
        rows = self.selected_items()
        problems = []

        if self.mode[0] == "ref":
            for item in rows:
                if not is_valid_id(item.reference_id):
                    if item.reference_box is not None:
                        item.reference_box.BorderBrush = brush(BLOCK_FG)
                    problems.append(
                        u"{0}: no referenced view selected".format(item.name)
                    )
            return problems

        taken = existing_view_names()
        seen = {}
        for item in rows:
            name = item.new_name.strip()
            if not name:
                if item.name_box is not None:
                    item.name_box.BorderBrush = brush(BLOCK_FG)
                problems.append(u"{0}: new view name is empty".format(item.name))
                continue
            key = name.lower()
            if key in taken:
                if item.name_box is not None:
                    item.name_box.BorderBrush = brush(BLOCK_FG)
                problems.append(
                    u'"{0}" is already used by another view in the model'.format(name)
                )
            elif key in seen:
                if item.name_box is not None:
                    item.name_box.BorderBrush = brush(BLOCK_FG)
                problems.append(u'"{0}" is used twice in this list'.format(name))
            else:
                seen[key] = True
        return problems

    # -- show -------------------------------------------------------------

    def show(self):
        frame = DispatcherFrame()

        def on_closed(sender, args):
            frame.Continue = False

        self.window.Closed += EventHandler(on_closed)

        try:
            helper = WindowInteropHelper(self.window)
            helper.Owner = __revit__.MainWindowHandle
        except Exception:
            pass

        self.window.Show()
        Dispatcher.PushFrame(frame)
        return self.result[0]


# ---------------------------------------------------------------------------
# creation
# ---------------------------------------------------------------------------


def points_for(target_view, corner_a, corner_b):
    """Region corners projected onto the target view's own level."""
    elevation = 0.0
    try:
        level = target_view.GenLevel
        if level is not None:
            elevation = level.Elevation
    except Exception:
        elevation = 0.0

    return (
        XYZ(min(corner_a.X, corner_b.X), min(corner_a.Y, corner_b.Y), elevation),
        XYZ(max(corner_a.X, corner_b.X), max(corner_a.Y, corner_b.Y), elevation),
    )


def create_callouts(items, mode, corner_a, corner_b):
    """Create every selected callout in one transaction. Returns (made, failures)."""
    rows = [i for i in items if i.checked and not i.blocked]
    made = []
    failures = []

    transaction = Transaction(doc, "Create Callouts")
    transaction.Start()
    try:
        for item in rows:
            parent_view = item.view
            point_a, point_b = points_for(parent_view, corner_a, corner_b)

            try:
                if mode == "view":
                    view_family_type_id = parent_view.GetTypeId()
                    new_view = ViewSection.CreateCallout(
                        doc,
                        parent_view.Id,
                        view_family_type_id,
                        point_a,
                        point_b,
                    )
                    created = doc.GetElement(new_view.Id)

                    name = item.new_name.strip()
                    if name:
                        # the view exists by now, so a name clash must not throw
                        # the whole row away - fall back to a suffixed name
                        attempt = 0
                        while True:
                            candidate = name if attempt == 0 else "{0} ({1})".format(
                                name, attempt
                            )
                            try:
                                created.Name = candidate
                                break
                            except Exception:
                                attempt += 1
                                if attempt > 25:
                                    break

                    if is_valid_id(item.template_id):
                        created.ViewTemplateId = item.template_id

                    made.append((parent_view.Name, created.Name))
                else:
                    ViewSection.CreateReferenceCallout(
                        doc,
                        parent_view.Id,
                        item.reference_id,
                        point_a,
                        point_b,
                    )
                    referenced = doc.GetElement(item.reference_id)
                    reference_name = "?" if referenced is None else referenced.Name
                    made.append((parent_view.Name, reference_name))

            except Exception as row_error:
                failures.append((parent_view.Name, str(row_error)))

        transaction.Commit()
    except Exception as error:
        transaction.RollBack()
        raise error

    return made, failures


def report(made, failures, mode):
    if failures:
        output.print_md("### Callout Creator")
        output.print_md(
            "**{0} created, {1} failed.**".format(len(made), len(failures))
        )
        for parent_name, message in failures:
            output.print_md("- `{0}` - {1}".format(parent_name, message))

    if mode == "view":
        headline = "{0} callouts created, {0} new views added.".format(len(made))
    else:
        headline = "{0} reference callouts created.".format(len(made))

    if failures:
        headline += "\n{0} view(s) failed - see the output window.".format(len(failures))

    forms.alert(headline, title="Callout Creator")


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


def pick_region():
    """Rubber-band a region in the active plan view. None when cancelled."""
    active_view = doc.ActiveView

    if not isinstance(active_view, ViewPlan) or active_view.ViewType not in PLAN_VIEW_TYPES:
        forms.alert(
            "Run this from a plan view - floor, ceiling, structural or area.",
            title="Callout Creator",
        )
        return None

    try:
        picked = uidoc.Selection.PickBox(
            PickBoxStyle.Directional,
            "Pick two opposite corners for the callout region",
        )
    except OperationCanceledException:
        return None

    if picked is None:
        return None
    return picked.Min, picked.Max


def main():
    if doc.IsFamilyDocument:
        forms.alert("Run this in a project, not a family.", title="Callout Creator")
        return

    plan_views = collect_plan_views()
    if not plan_views:
        forms.alert("This model has no plan views.", title="Callout Creator")
        return

    templates_by_type = collect_templates_by_view_type()
    reference_choices = collect_reference_candidates()

    while True:
        region = pick_region()
        if region is None:
            return
        corner_a, corner_b = region

        items = build_items(plan_views, corner_a, corner_b, doc.ActiveView.Id)

        window = CalloutCreatorWindow(
            items, corner_a, corner_b, templates_by_type, reference_choices
        )
        outcome = window.show()

        if outcome == "repick":
            continue
        if outcome != "create":
            return

        made, failures = create_callouts(
            items, window.mode[0], corner_a, corner_b
        )
        report(made, failures, window.mode[0])
        return


main()
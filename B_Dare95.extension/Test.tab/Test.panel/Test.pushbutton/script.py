# -*- coding: utf-8 -*-
__title__ = "Column Guard Generator"
__doc__ = """Version = 2.0
_____________________________________________________________________
Description:
Generates individual Column Guardrails for each column in a linked file.

How to use:

1- Select a Railing Type to use as Column Guardrail
2- Select Structural Columns to apply the guard
3- Done!!
_____________________________________________________________________
Author: Mohamed Bedair"""

import clr

clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')
clr.AddReference('System.Xml')

from Autodesk.Revit.DB import (Level, FilteredElementCollector, BuiltInParameter,
                                BuiltInCategory, Options, ViewDetailLevel,
                                GeometryInstance, Solid, CurveLoop,
                                Transaction, XYZ, RevitLinkInstance)
from Autodesk.Revit.DB.Architecture import Railing, RailingType
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType

import System
from System.Windows.Markup import XamlReader
from System.Windows.Threading import Dispatcher, DispatcherFrame
from System.Windows import Window, Application
from System.Windows.Controls import ListBoxItem

doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

# ─── Catppuccin WPF UI ───────────────────────────────────────────────────────

XAML = """
<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Column Guard Generator"
    Width="420" SizeToContent="Height"
    WindowStartupLocation="CenterScreen"
    ResizeMode="NoResize"
    Background="#1E1E2E"
    FontFamily="Segoe UI">

    <Window.Resources>

        <!-- Scrollbar thumb -->
        <Style x:Key="ThumbStyle" TargetType="Thumb">
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="Thumb">
                        <Border Background="#45475A" CornerRadius="3" Margin="2"/>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>

        <!-- Minimal scrollbar -->
        <Style x:Key="ThinScrollBar" TargetType="ScrollBar">
            <Setter Property="Width" Value="6"/>
            <Setter Property="Background" Value="Transparent"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="ScrollBar">
                        <Grid Background="Transparent">
                            <Track Name="PART_Track" IsDirectionReversed="True">
                                <Track.Thumb>
                                    <Thumb Style="{StaticResource ThumbStyle}"/>
                                </Track.Thumb>
                            </Track>
                        </Grid>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>

        <!-- ScrollViewer -->
        <Style x:Key="ThinScroll" TargetType="ScrollViewer">
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="ScrollViewer">
                        <Grid>
                            <Grid.ColumnDefinitions>
                                <ColumnDefinition Width="*"/>
                                <ColumnDefinition Width="Auto"/>
                            </Grid.ColumnDefinitions>
                            <ScrollContentPresenter Grid.Column="0"/>
                            <ScrollBar Grid.Column="1"
                                       Style="{StaticResource ThinScrollBar}"
                                       Orientation="Vertical"
                                       Value="{TemplateBinding VerticalOffset}"
                                       Maximum="{TemplateBinding ScrollableHeight}"
                                       ViewportSize="{TemplateBinding ViewportHeight}"
                                       Visibility="{TemplateBinding ComputedVerticalScrollBarVisibility}"/>
                        </Grid>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>

        <!-- ListBoxItem -->
        <Style TargetType="ListBoxItem">
            <Setter Property="Foreground" Value="#CDD6F4"/>
            <Setter Property="Background" Value="Transparent"/>
            <Setter Property="Padding" Value="10,7"/>
            <Setter Property="Cursor" Value="Hand"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="ListBoxItem">
                        <Border x:Name="Bd"
                                Background="{TemplateBinding Background}"
                                CornerRadius="6"
                                Margin="0,2"
                                Padding="{TemplateBinding Padding}">
                            <ContentPresenter/>
                        </Border>
                        <ControlTemplate.Triggers>
                            <Trigger Property="IsMouseOver" Value="True">
                                <Setter TargetName="Bd" Property="Background" Value="#313244"/>
                            </Trigger>
                            <Trigger Property="IsSelected" Value="True">
                                <Setter TargetName="Bd" Property="Background" Value="#F0A500"/>
                                <Setter Property="Foreground" Value="#1E1E2E"/>
                            </Trigger>
                        </ControlTemplate.Triggers>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>

        <!-- ListBox -->
        <Style TargetType="ListBox">
            <Setter Property="Background" Value="#2A2A3C"/>
            <Setter Property="BorderThickness" Value="0"/>
            <Setter Property="Padding" Value="4"/>
            <Setter Property="ScrollViewer.HorizontalScrollBarVisibility" Value="Disabled"/>
            <Setter Property="ScrollViewer.VerticalScrollBarVisibility" Value="Auto"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="ListBox">
                        <Border Background="{TemplateBinding Background}"
                                CornerRadius="8"
                                Padding="{TemplateBinding Padding}">
                            <ScrollViewer Style="{StaticResource ThinScroll}"
                                          Focusable="False">
                                <ItemsPresenter/>
                            </ScrollViewer>
                        </Border>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>

        <!-- Primary button -->
        <Style x:Key="PrimaryBtn" TargetType="Button">
            <Setter Property="Background" Value="#F0A500"/>
            <Setter Property="Foreground" Value="#1E1E2E"/>
            <Setter Property="FontWeight" Value="SemiBold"/>
            <Setter Property="FontSize" Value="13"/>
            <Setter Property="Height" Value="38"/>
            <Setter Property="Cursor" Value="Hand"/>
            <Setter Property="BorderThickness" Value="0"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="Button">
                        <Border x:Name="Bd"
                                Background="{TemplateBinding Background}"
                                CornerRadius="8"
                                Padding="16,0">
                            <ContentPresenter HorizontalAlignment="Center"
                                              VerticalAlignment="Center"/>
                        </Border>
                        <ControlTemplate.Triggers>
                            <Trigger Property="IsMouseOver" Value="True">
                                <Setter TargetName="Bd" Property="Background" Value="#E09400"/>
                            </Trigger>
                            <Trigger Property="IsPressed" Value="True">
                                <Setter TargetName="Bd" Property="Background" Value="#C07800"/>
                            </Trigger>
                            <Trigger Property="IsEnabled" Value="False">
                                <Setter TargetName="Bd" Property="Background" Value="#45475A"/>
                                <Setter Property="Foreground" Value="#6C7086"/>
                            </Trigger>
                        </ControlTemplate.Triggers>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>

        <!-- Ghost/cancel button -->
        <Style x:Key="GhostBtn" TargetType="Button">
            <Setter Property="Background" Value="Transparent"/>
            <Setter Property="Foreground" Value="#A6ADC8"/>
            <Setter Property="FontSize" Value="13"/>
            <Setter Property="Height" Value="38"/>
            <Setter Property="Cursor" Value="Hand"/>
            <Setter Property="BorderThickness" Value="1"/>
            <Setter Property="BorderBrush" Value="#45475A"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="Button">
                        <Border x:Name="Bd"
                                Background="{TemplateBinding Background}"
                                BorderBrush="{TemplateBinding BorderBrush}"
                                BorderThickness="{TemplateBinding BorderThickness}"
                                CornerRadius="8"
                                Padding="16,0">
                            <ContentPresenter HorizontalAlignment="Center"
                                              VerticalAlignment="Center"/>
                        </Border>
                        <ControlTemplate.Triggers>
                            <Trigger Property="IsMouseOver" Value="True">
                                <Setter TargetName="Bd" Property="Background" Value="#313244"/>
                                <Setter TargetName="Bd" Property="BorderBrush" Value="#6C7086"/>
                            </Trigger>
                            <Trigger Property="IsPressed" Value="True">
                                <Setter TargetName="Bd" Property="Background" Value="#45475A"/>
                            </Trigger>
                        </ControlTemplate.Triggers>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>

    </Window.Resources>

    <StackPanel Margin="24,20,24,24">

        <!-- Header -->
        <StackPanel Margin="0,0,0,20">
            <TextBlock Text="Column Guard Generator"
                       Foreground="#CDD6F4"
                       FontSize="18"
                       FontWeight="SemiBold"/>
            <TextBlock Text="Select a railing type to wrap around linked structural columns."
                       Foreground="#A6ADC8"
                       FontSize="11"
                       Margin="0,4,0,0"
                       TextWrapping="Wrap"/>
        </StackPanel>

        <!-- Divider -->
        <Border Height="1" Background="#313244" Margin="0,0,0,20"/>

        <!-- Railing Type label -->
        <StackPanel Margin="0,0,0,8" Orientation="Horizontal">
            <Border Width="3" Height="14" Background="#F0A500"
                    CornerRadius="2" Margin="0,0,8,0" VerticalAlignment="Center"/>
            <TextBlock Text="Railing Type"
                       Foreground="#CDD6F4"
                       FontSize="12"
                       FontWeight="Medium"
                       VerticalAlignment="Center"/>
        </StackPanel>

        <!-- Railing list -->
        <ListBox x:Name="RailList"
                 Height="180"
                 Margin="0,0,0,20"/>

        <!-- Count badge -->
        <Border Background="#2A2A3C" CornerRadius="6" Padding="10,7"
                Margin="0,0,0,20">
            <StackPanel Orientation="Horizontal">
                <TextBlock Text="Available types: "
                           Foreground="#A6ADC8" FontSize="11"/>
                <TextBlock x:Name="CountLabel"
                           Foreground="#F0A500" FontSize="11" FontWeight="SemiBold"/>
            </StackPanel>
        </Border>

        <!-- Action buttons -->
        <Grid>
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="12"/>
                <ColumnDefinition Width="*"/>
            </Grid.ColumnDefinitions>

            <Button x:Name="CancelBtn"
                    Grid.Column="0"
                    Content="Cancel"
                    Style="{StaticResource GhostBtn}"/>

            <Button x:Name="ConfirmBtn"
                    Grid.Column="2"
                    Content="Select Columns →"
                    Style="{StaticResource PrimaryBtn}"
                    IsEnabled="False"/>
        </Grid>

    </StackPanel>
</Window>
"""

def show_railing_picker(rail_names):
    """Show Catppuccin WPF dialog. Returns selected name string or None."""
    selected = [None]

    win = XamlReader.Parse(XAML)
    rail_list  = win.FindName("RailList")
    confirm    = win.FindName("ConfirmBtn")
    cancel     = win.FindName("CancelBtn")
    count_lbl  = win.FindName("CountLabel")

    # Populate list
    for name in rail_names:
        item = ListBoxItem()
        item.Content = name
        rail_list.Items.Add(item)

    count_lbl.Text = str(len(rail_names))

    def on_selection_changed(s, e):
        confirm.IsEnabled = rail_list.SelectedItem is not None

    def on_confirm(s, e):
        if rail_list.SelectedItem is not None:
            selected[0] = rail_list.SelectedItem.Content
        win.Close()

    def on_cancel(s, e):
        win.Close()

    rail_list.SelectionChanged += on_selection_changed
    confirm.Click += on_confirm
    cancel.Click  += on_cancel

    # Pump dispatcher so the window blocks without freezing Revit
    frame = DispatcherFrame()

    def on_closed(s, e):
        frame.Continue = False

    win.Closed += on_closed
    win.Show()
    Dispatcher.PushFrame(frame)

    return selected[0]


# ─── Collect Railing Types ────────────────────────────────────────────────────

all_rail_types    = FilteredElementCollector(doc).OfClass(RailingType).ToElements()
all_rail_types_id = FilteredElementCollector(doc).OfClass(RailingType).ToElementIds()
all_rail_names    = [rail.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME).AsValueString()
                     for rail in all_rail_types]

rail_dict_type_name = dict(zip(all_rail_types, all_rail_names))
rail_dict_name_id   = dict(zip(all_rail_names, all_rail_types_id))

selected_rail = show_railing_picker(all_rail_names)

if not selected_rail:
    print("No railing type selected. Cancelled.")
    import sys; sys.exit()

selected_rail_id = rail_dict_name_id.get(selected_rail)

# ─── Selection Filter ─────────────────────────────────────────────────────────

class LinkedStructuralColumnFilter(ISelectionFilter):
    """Allows selection of structural columns from Revit link instances only."""

    def AllowElement(self, element):
        return isinstance(element, RevitLinkInstance)

    def AllowReference(self, reference, point):
        try:
            link_instance = doc.GetElement(reference.ElementId)
            if not isinstance(link_instance, RevitLinkInstance):
                return False
            linked_doc = link_instance.GetLinkDocument()
            linked_element = linked_doc.GetElement(reference.LinkedElementId)
            if linked_element is None or linked_element.Category is None:
                return False
            return linked_element.Category.Id.Value == int(BuiltInCategory.OST_StructuralColumns)
        except Exception:
            return False

# ─── Helpers ──────────────────────────────────────────────────────────────────

def get_base_elevation(column, linked_doc):
    base_level_param = column.get_Parameter(BuiltInParameter.FAMILY_BASE_LEVEL_PARAM)
    if base_level_param is None:
        return None
    base_level = linked_doc.GetElement(base_level_param.AsElementId())
    return base_level.Elevation if base_level else None


def _collect_solids(geom_obj):
    """Recursively collect all Solids from a geometry object, handling nested GeometryInstances."""
    solids = []
    if isinstance(geom_obj, Solid):
        if geom_obj.Volume > 0:
            solids.append(geom_obj)
    elif isinstance(geom_obj, GeometryInstance):
        for child in geom_obj.GetInstanceGeometry():
            solids.extend(_collect_solids(child))
    return solids


def get_footprint_curves(column, base_elevation, transform, tolerance=0.05):
    """
    Extract bottom-face edges from the column solid and transform to host coordinates.
    Strategy: find the lowest Z face in the solid (not relying on exact elevation match),
    then return its boundary curves transformed into host space.
    """
    options = Options()
    options.ComputeReferences = True
    options.DetailLevel = ViewDetailLevel.Fine

    geom_element = column.get_Geometry(options)
    if geom_element is None:
        return []

    all_solids = []
    for geom_obj in geom_element:
        all_solids.extend(_collect_solids(geom_obj))

    if not all_solids:
        return []

    main_solid = max(all_solids, key=lambda s: s.Volume)

    best_face   = None
    best_face_z = None
    for face in main_solid.Faces:
        normal = face.FaceNormal
        if abs(normal.Z) < 0.9:
            continue
        z_vals = []
        for loop in face.EdgeLoops:
            for edge in loop:
                z_vals.append(edge.AsCurve().GetEndPoint(0).Z)
                z_vals.append(edge.AsCurve().GetEndPoint(1).Z)
        if not z_vals:
            continue
        face_z = sum(z_vals) / len(z_vals)
        if best_face_z is None or face_z < best_face_z:
            best_face_z = face_z
            best_face   = face

    if best_face is None:
        return []

    curves = []
    outer_loop = list(best_face.EdgeLoops)[0]
    for edge in outer_loop:
        curves.append(edge.AsCurve().CreateTransformed(transform))

    return curves


def sort_curves_into_loop(curves, tolerance=1e-6):
    """Re-order curves so they form a single connected closed loop."""
    if not curves:
        return curves
    sorted_curves = [curves[0]]
    remaining = list(curves[1:])
    while remaining:
        last_end = sorted_curves[-1].GetEndPoint(1)
        matched  = False
        for i, c in enumerate(remaining):
            if last_end.DistanceTo(c.GetEndPoint(0)) < tolerance:
                sorted_curves.append(c)
                remaining.pop(i)
                matched = True
                break
            elif last_end.DistanceTo(c.GetEndPoint(1)) < tolerance:
                sorted_curves.append(c.CreateReversed())
                remaining.pop(i)
                matched = True
                break
        if not matched:
            break
    return sorted_curves


def get_nearest_host_level_id(host_doc, elevation):
    """Return the Id of the host-doc level closest to the given elevation."""
    levels = FilteredElementCollector(host_doc).OfClass(Level).ToElements()
    if not levels:
        return None
    return min(levels, key=lambda lvl: abs(lvl.Elevation - elevation)).Id

# ─── Main ─────────────────────────────────────────────────────────────────────

sel_filter = LinkedStructuralColumnFilter()

try:
    references = uidoc.Selection.PickObjects(
        ObjectType.LinkedElement,
        sel_filter,
        "Select structural columns from a Revit link (Finish when done)"
    )
except Exception:
    print("Selection cancelled.")
    references = []

if not references:
    print("No columns selected.")
else:
    t = Transaction(doc, "Generate Column Footprint Lines")
    t.Start()
    try:
        for ref in references:
            link_instance  = doc.GetElement(ref.ElementId)
            linked_doc     = link_instance.GetLinkDocument()
            transform      = link_instance.GetTotalTransform()

            column         = linked_doc.GetElement(ref.LinkedElementId)
            base_elevation = get_base_elevation(column, linked_doc)
            if base_elevation is None:
                print("Could not determine base elevation for element: {}".format(column.Id))
                continue

            transformed_origin  = transform.OfPoint(XYZ(0, 0, base_elevation))
            host_base_elevation = transformed_origin.Z

            curves = get_footprint_curves(column, base_elevation, transform)
            if not curves:
                print("No footprint curves found for element: {}".format(column.Id))
                continue

            ordered_curves = sort_curves_into_loop(curves)
            curveloop      = CurveLoop.Create(ordered_curves)

            host_level_id = get_nearest_host_level_id(doc, host_base_elevation)
            if host_level_id is None:
                print("No host level found for element: {}".format(column.Id))
                continue

            new_column_guard = Railing.Create(doc, curveloop, selected_rail_id, host_level_id)

            new_column_guard.Flip()

        t.Commit()

    except Exception as e:
        print(e)
        t.RollBack()
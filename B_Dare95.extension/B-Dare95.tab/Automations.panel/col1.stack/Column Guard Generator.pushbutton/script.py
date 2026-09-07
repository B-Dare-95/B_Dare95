# -*- coding: utf-8 -*-
__title__ = "Column Guard Generator"
__doc__ = """Version = 2.0
_____________________________________________________________________
Description:
Generates individual Column Guardrails for each column in a linked file.

How to use:

1-Select a Railing Type to use as Column Guardrail
2-Select Structural Columns to apply the guard 
3-Done!!
_____________________________________________________________________
Author: Mohamed Bedair"""

import clr

clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('PresentationCore')
clr.AddReference('PresentationFramework')
clr.AddReference('WindowsBase')
clr.AddReference('System.Xml')

from Autodesk.Revit.DB import (Level, FilteredElementCollector, BuiltInParameter,
                                BuiltInCategory, Options, ViewDetailLevel,
                                GeometryInstance, Solid, CurveLoop,
                                Transaction, XYZ, RevitLinkInstance)
from Autodesk.Revit.DB.Architecture import Railing, RailingType
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType

from System.Windows.Markup import XamlReader
from System.Windows import Window, Application
from System.Windows.Controls import ListBoxItem
from System.Windows.Media import SolidColorBrush, Color

doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

# ─── Railing Type Collection ──────────────────────────────────────────────────

all_rail_types    = FilteredElementCollector(doc).OfClass(RailingType).ToElements()
all_rail_types_id = FilteredElementCollector(doc).OfClass(RailingType).ToElementIds()

all_rail_names = [
    rail.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME).AsValueString()
    for rail in all_rail_types
]

rail_dict_type_name = dict(zip(all_rail_types, all_rail_names))
rail_dict_name_id   = dict(zip(all_rail_names, all_rail_types_id))

# ─── Catppuccin Mocha WPF UI ─────────────────────────────────────────────────

XAML = """
<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Column Guard Generator"
    Width="320"
    SizeToContent="Height"
    WindowStartupLocation="CenterScreen"
    ResizeMode="NoResize"
    Background="#1E1E2E"
    BorderBrush="#45475A"
    BorderThickness="1">

    <Window.Resources>

        <!-- ── Scrollbar ── -->
        <Style x:Key="ThumbStyle" TargetType="Thumb">
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="Thumb">
                        <Border Background="#45475A" CornerRadius="3"/>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>

        <Style x:Key="ScrollBarStyle" TargetType="ScrollBar">
            <Setter Property="Width" Value="6"/>
            <Setter Property="Background" Value="#181825"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="ScrollBar">
                        <Grid Background="#181825">
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

        <Style TargetType="ScrollViewer">
            <Setter Property="VerticalScrollBarVisibility" Value="Auto"/>
        </Style>

        <!-- ── ListBox ── -->
        <Style x:Key="RailItemStyle" TargetType="ListBoxItem">
            <Setter Property="Foreground" Value="#A6ADC8"/>
            <Setter Property="Background" Value="Transparent"/>
            <Setter Property="Padding" Value="10,8"/>
            <Setter Property="FontSize" Value="13"/>
            <Setter Property="BorderThickness" Value="0"/>
            <Setter Property="HorizontalContentAlignment" Value="Stretch"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="ListBoxItem">
                        <Border x:Name="Bd"
                                Background="{TemplateBinding Background}"
                                BorderThickness="2,0,0,0"
                                BorderBrush="Transparent"
                                Padding="{TemplateBinding Padding}">
                            <ContentPresenter/>
                        </Border>
                        <ControlTemplate.Triggers>
                            <Trigger Property="IsMouseOver" Value="True">
                                <Setter TargetName="Bd" Property="Background" Value="#313244"/>
                                <Setter Property="Foreground" Value="#CDD6F4"/>
                            </Trigger>
                            <Trigger Property="IsSelected" Value="True">
                                <Setter TargetName="Bd" Property="Background" Value="#2A2A3C"/>
                                <Setter TargetName="Bd" Property="BorderBrush" Value="#F0A500"/>
                                <Setter Property="Foreground" Value="#F0A500"/>
                            </Trigger>
                        </ControlTemplate.Triggers>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>

        <!-- ── Primary Button ── -->
        <Style x:Key="PrimaryBtn" TargetType="Button">
            <Setter Property="Background" Value="#F0A500"/>
            <Setter Property="Foreground" Value="#1E1E2E"/>
            <Setter Property="FontSize" Value="13"/>
            <Setter Property="FontWeight" Value="SemiBold"/>
            <Setter Property="Padding" Value="0,9"/>
            <Setter Property="BorderThickness" Value="0"/>
            <Setter Property="Cursor" Value="Hand"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="Button">
                        <Border x:Name="Bd"
                                Background="{TemplateBinding Background}"
                                CornerRadius="8"
                                Padding="{TemplateBinding Padding}">
                            <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
                        </Border>
                        <ControlTemplate.Triggers>
                            <Trigger Property="IsMouseOver" Value="True">
                                <Setter TargetName="Bd" Property="Background" Value="#D4940A"/>
                            </Trigger>
                            <Trigger Property="IsPressed" Value="True">
                                <Setter TargetName="Bd" Property="Background" Value="#B87E08"/>
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

        <!-- ── Cancel Button ── -->
        <Style x:Key="CancelBtn" TargetType="Button">
            <Setter Property="Background" Value="#313244"/>
            <Setter Property="Foreground" Value="#A6ADC8"/>
            <Setter Property="FontSize" Value="13"/>
            <Setter Property="Padding" Value="0,9"/>
            <Setter Property="BorderBrush" Value="#45475A"/>
            <Setter Property="BorderThickness" Value="1"/>
            <Setter Property="Cursor" Value="Hand"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="Button">
                        <Border x:Name="Bd"
                                Background="{TemplateBinding Background}"
                                BorderBrush="{TemplateBinding BorderBrush}"
                                BorderThickness="{TemplateBinding BorderThickness}"
                                CornerRadius="8"
                                Padding="{TemplateBinding Padding}">
                            <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
                        </Border>
                        <ControlTemplate.Triggers>
                            <Trigger Property="IsMouseOver" Value="True">
                                <Setter TargetName="Bd" Property="Background" Value="#45475A"/>
                                <Setter Property="Foreground" Value="#CDD6F4"/>
                            </Trigger>
                            <Trigger Property="IsPressed" Value="True">
                                <Setter TargetName="Bd" Property="Background" Value="#585B70"/>
                            </Trigger>
                        </ControlTemplate.Triggers>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>

        <!-- ── TextBox (search) ── -->
        <Style x:Key="SearchBox" TargetType="TextBox">
            <Setter Property="Background" Value="#313244"/>
            <Setter Property="Foreground" Value="#CDD6F4"/>
            <Setter Property="CaretBrush" Value="#F0A500"/>
            <Setter Property="FontSize" Value="13"/>
            <Setter Property="BorderBrush" Value="#45475A"/>
            <Setter Property="BorderThickness" Value="1"/>
            <Setter Property="Padding" Value="32,8,10,8"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="TextBox">
                        <Border x:Name="Bd"
                                Background="{TemplateBinding Background}"
                                BorderBrush="{TemplateBinding BorderBrush}"
                                BorderThickness="{TemplateBinding BorderThickness}"
                                CornerRadius="8">
                            <ScrollViewer x:Name="PART_ContentHost"
                                          Margin="{TemplateBinding Padding}"
                                          VerticalAlignment="Center"/>
                        </Border>
                        <ControlTemplate.Triggers>
                            <Trigger Property="IsFocused" Value="True">
                                <Setter TargetName="Bd" Property="BorderBrush" Value="#F0A500"/>
                            </Trigger>
                            <Trigger Property="IsMouseOver" Value="True">
                                <Setter TargetName="Bd" Property="BorderBrush" Value="#6C7086"/>
                            </Trigger>
                        </ControlTemplate.Triggers>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>

    </Window.Resources>

    <!-- ── Title Bar ── -->
    <StackPanel>
        <Border Background="#181825"
                BorderBrush="#45475A"
                BorderThickness="0,0,0,1"
                Padding="14,10">
            <StackPanel Orientation="Horizontal" VerticalAlignment="Center">
                <TextBlock Text="&#xE9C2;"
                           FontFamily="Segoe MDL2 Assets"
                           FontSize="15"
                           Foreground="#F0A500"
                           VerticalAlignment="Center"
                           Margin="0,0,8,0"/>
                <TextBlock Text="Column Guard Generator"
                           Foreground="#CDD6F4"
                           FontSize="13"
                           FontWeight="SemiBold"
                           VerticalAlignment="Center"/>
            </StackPanel>
        </Border>

        <!-- ── Body ── -->
        <StackPanel Margin="14,12,14,14">

            <!-- Label -->
            <TextBlock Text="RAILING TYPE"
                       Foreground="#6C7086"
                       FontSize="10"
                       FontWeight="SemiBold"
                       Margin="0,0,0,6"/>

            <!-- Search row -->
            <Grid Margin="0,0,0,8">
                <TextBox x:Name="SearchBox"
                         Style="{StaticResource SearchBox}"
                         Tag="Filter railing types..."/>
                <!-- Search icon overlay -->
                <TextBlock Text="&#xE721;"
                           FontFamily="Segoe MDL2 Assets"
                           FontSize="14"
                           Foreground="#6C7086"
                           VerticalAlignment="Center"
                           Margin="10,0,0,0"
                           IsHitTestVisible="False"/>
                <!-- Placeholder -->
                <TextBlock x:Name="Placeholder"
                           Text="Filter railing types..."
                           Foreground="#6C7086"
                           FontSize="13"
                           VerticalAlignment="Center"
                           Margin="32,0,0,0"
                           IsHitTestVisible="False"/>
            </Grid>

            <!-- List -->
            <Border BorderBrush="#45475A"
                    BorderThickness="1"
                    CornerRadius="8"
                    Background="#181825"
                    Margin="0,0,0,12">
                <ListBox x:Name="RailList"
                         Background="Transparent"
                         BorderThickness="0"
                         MaxHeight="220"
                         ItemContainerStyle="{StaticResource RailItemStyle}"
                         SelectionMode="Single">
                    <ListBox.Template>
                        <ControlTemplate TargetType="ListBox">
                            <ScrollViewer>
                                <ScrollViewer.Resources>
                                    <Style TargetType="ScrollBar"
                                           BasedOn="{StaticResource ScrollBarStyle}"/>
                                </ScrollViewer.Resources>
                                <ItemsPresenter/>
                            </ScrollViewer>
                        </ControlTemplate>
                    </ListBox.Template>
                </ListBox>
            </Border>

            <!-- Selected label -->
            <Border Background="#2A2A3C"
                    BorderBrush="#45475A"
                    BorderThickness="1"
                    CornerRadius="6"
                    Padding="10,7"
                    Margin="0,0,0,12">
                <StackPanel Orientation="Horizontal">
                    <TextBlock Text="Selected: "
                               Foreground="#6C7086"
                               FontSize="12"/>
                    <TextBlock x:Name="SelectedLabel"
                               Text="None"
                               Foreground="#F0A500"
                               FontSize="12"
                               FontWeight="SemiBold"/>
                </StackPanel>
            </Border>

            <!-- Buttons -->
            <Grid>
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="8"/>
                    <ColumnDefinition Width="*"/>
                </Grid.ColumnDefinitions>
                <Button x:Name="CancelBtn"
                        Grid.Column="0"
                        Content="Cancel"
                        Style="{StaticResource CancelBtn}"/>
                <Button x:Name="OkBtn"
                        Grid.Column="2"
                        Content="Make a Selection"
                        Style="{StaticResource PrimaryBtn}"
                        IsEnabled="False"/>
            </Grid>

        </StackPanel>
    </StackPanel>
</Window>
"""


def show_rail_picker(rail_names):
    """
    Show the Catppuccin-themed railing type picker.
    Returns the selected rail name string, or None if cancelled.
    """
    win = XamlReader.Parse(XAML)

    rail_list      = win.FindName("RailList")
    search_box     = win.FindName("SearchBox")
    placeholder    = win.FindName("Placeholder")
    selected_label = win.FindName("SelectedLabel")
    ok_btn         = win.FindName("OkBtn")
    cancel_btn     = win.FindName("CancelBtn")

    result_holder = [None]

    # ── Populate list ──────────────────────────────────────────────────────────
    def populate(filter_text=""):
        rail_list.Items.Clear()
        for name in rail_names:
            if filter_text.lower() in name.lower():
                item = ListBoxItem()
                item.Content = name
                rail_list.Items.Add(item)

    populate()

    # ── Search handler ─────────────────────────────────────────────────────────
    def on_search_changed(s, e):
        txt = search_box.Text
        placeholder.Visibility = (
            System.Windows.Visibility.Collapsed if txt
            else System.Windows.Visibility.Visible
        )
        populate(txt)
        # Re-select if the previously selected item is still visible
        if selected_label.Text != "None":
            for item in rail_list.Items:
                if item.Content == selected_label.Text:
                    rail_list.SelectedItem = item
                    break

    search_box.TextChanged += on_search_changed

    # ── Selection handler ──────────────────────────────────────────────────────
    def on_selection_changed(s, e):
        sel = rail_list.SelectedItem
        if sel is not None:
            selected_label.Text = sel.Content
            ok_btn.IsEnabled    = True
        else:
            selected_label.Text = "None"
            ok_btn.IsEnabled    = False

    rail_list.SelectionChanged += on_selection_changed

    # ── Button handlers ────────────────────────────────────────────────────────
    def on_ok(s, e):
        result_holder[0] = selected_label.Text
        win.Close()

    def on_cancel(s, e):
        win.Close()

    ok_btn.Click     += on_ok
    cancel_btn.Click += on_cancel

    win.ShowDialog()
    return result_holder[0]


# ── Show UI ───────────────────────────────────────────────────────────────────

import System.Windows
selected_rail = show_rail_picker(all_rail_names)

if not selected_rail:
    print("No railing type selected. Script cancelled.")
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
            linked_doc     = link_instance.GetLinkDocument()
            linked_element = linked_doc.GetElement(reference.LinkedElementId)
            return (
                linked_element is not None
                and linked_element.Category is not None
                and linked_element.Category.Id.Value
                    == int(BuiltInCategory.OST_StructuralColumns)
            )
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
    """Recursively collect all Solids, handling arbitrarily nested GeometryInstances."""
    solids = []
    if isinstance(geom_obj, Solid):
        if geom_obj.Volume > 0:
            solids.append(geom_obj)
    elif isinstance(geom_obj, GeometryInstance):
        for child in geom_obj.GetInstanceGeometry():
            solids.extend(_collect_solids(child))
    return solids


def get_footprint_curves(column, base_elevation, transform):
    """
    Extract bottom-face edges from the column solid and transform to host coordinates.
    Uses the lowest horizontal face by centroid Z — no hardcoded elevation comparison.
    """
    options = Options()
    options.ComputeReferences = True
    options.DetailLevel       = ViewDetailLevel.Fine

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
    remaining     = list(curves[1:])
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
    t = Transaction(doc, "Generate Column Guardrails")
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

            host_level_id  = get_nearest_host_level_id(doc, host_base_elevation)
            if host_level_id is None:
                print("No host level found for element: {}".format(column.Id))
                continue

            Railing.Create(doc, curveloop, selected_rail_id, host_level_id)

        t.Commit()

    except Exception as e:
        print(e)
        t.RollBack()
# -*- coding: utf-8 -*-
__title__ = "Column Guard Generator"
__doc__ = """Version = 3.0
_____________________________________________________________________
Description:
Generates individual Column Guardrails around columns in a linked file.

The railing path is an oriented rectangle built in each column's own
coordinate system, so it works on any family - rectangular, circular,
L-shaped, chamfered or in-place - without touching face geometry.

The railing is hosted on the ACTIVE VIEW's level, not on a level guessed
from the linked column.

How to use:

1-Open the plan view you want the guards on
2-Select a Railing Type and an offset distance
3-Select Columns from a link
4-Done!!
_____________________________________________________________________
Author: Mohamed Bedair"""

import clr

clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('PresentationCore')
clr.AddReference('PresentationFramework')
clr.AddReference('WindowsBase')
clr.AddReference('System.Xml')

from Autodesk.Revit.DB import (Element, Level, FilteredElementCollector,
                               BuiltInParameter, BuiltInCategory, Options,
                               ViewDetailLevel, GeometryInstance, Solid,
                               CurveLoop, Line, Transaction, Transform, XYZ,
                               RevitLinkInstance)
from Autodesk.Revit.DB.Architecture import Railing, RailingType
from Autodesk.Revit.UI import TaskDialog
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType

import traceback

from System import EventHandler
from System.Windows.Markup import XamlReader
from System.Windows import RoutedEventHandler, Visibility
from System.Windows.Controls import (ListBoxItem, TextChangedEventHandler,
                                     SelectionChangedEventHandler)
from System.Windows.Threading import Dispatcher, DispatcherFrame

doc   = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

# ─── Constants ────────────────────────────────────────────────────────────────

CM_TO_FT = 1.0 / 30.48

# Revit rejects sketch curves shorter than roughly 1/256 ft (~1.2 mm).
SHORT_CURVE_FT = 1.0 / 256.0

# A footprint rectangle smaller than this is treated as garbage geometry.
MIN_SIDE_FT = 50.0 / 304.8          # 50 mm

# If the oriented rectangle is more than this many times the bounding box
# plan size, the extraction picked up joined geometry - fall back.
BBOX_SANITY_RATIO = 1.25

# Railing.Create refuses some levels outright and returns None without
# throwing. When the view level is refused, optionally walk to nearby levels
# and compensate with Base Offset. Every fallback is reported, never silent.
ALLOW_LEVEL_FALLBACK = True
LEVEL_FALLBACK_LIMIT = 4

COLUMN_CATEGORIES = [int(BuiltInCategory.OST_StructuralColumns),
                     int(BuiltInCategory.OST_Columns)]

# ─── Reporting ────────────────────────────────────────────────────────────────


def notify(title, message):
    """Print AND show a Revit dialog, so nothing can fail silently."""
    print("{}: {}".format(title, message))
    try:
        TaskDialog.Show(title, message)
    except Exception:
        pass


# ─── Compatibility Helpers ────────────────────────────────────────────────────


def eid_value(element_id):
    """ElementId.Value (2025+) with .IntegerValue fallback."""
    try:
        return element_id.Value
    except AttributeError:
        return element_id.IntegerValue


def element_name(element):
    """Element.Name getter - avoids the IronPython Name binding ambiguity."""
    try:
        return Element.Name.__get__(element)
    except Exception:
        try:
            return element.Name
        except Exception:
            return "<unnamed>"


# ─── Railing Type Collection ──────────────────────────────────────────────────

# Category filter as well as class: OfClass alone can return rail types that
# Railing.Create silently refuses.
all_rail_types = (FilteredElementCollector(doc)
                  .OfCategory(BuiltInCategory.OST_StairsRailing)
                  .OfClass(RailingType)
                  .ToElements())

rail_dict_name_id = {}
for rail in all_rail_types:
    rail_name = element_name(rail)
    if not rail_name:
        continue
    if rail_name in rail_dict_name_id:
        rail_name = "{} [{}]".format(rail_name, eid_value(rail.Id))
    rail_dict_name_id[rail_name] = rail.Id

all_rail_names = sorted(rail_dict_name_id.keys())

# ─── IBM Carbon WPF UI ────────────────────────────────────────────────────────

XAML = """
<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Column Guard Generator"
    Width="320"
    SizeToContent="Height"
    WindowStartupLocation="CenterScreen"
    ResizeMode="NoResize"
    Background="#161616"
    BorderBrush="#525252"
    BorderThickness="1">

    <Window.Resources>

        <!-- ── Scrollbar ── -->
        <Style x:Key="ThumbStyle" TargetType="Thumb">
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="Thumb">
                        <Border Background="#525252" CornerRadius="3"/>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>

        <Style x:Key="ScrollBarStyle" TargetType="ScrollBar">
            <Setter Property="Width" Value="6"/>
            <Setter Property="Background" Value="#0D0D0D"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="ScrollBar">
                        <Grid Background="#0D0D0D">
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
            <Setter Property="Foreground" Value="#A8A8A8"/>
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
                                <Setter TargetName="Bd" Property="Background" Value="#393939"/>
                                <Setter Property="Foreground" Value="#F4F4F4"/>
                            </Trigger>
                            <Trigger Property="IsSelected" Value="True">
                                <Setter TargetName="Bd" Property="Background" Value="#262626"/>
                                <Setter TargetName="Bd" Property="BorderBrush" Value="#F1C21B"/>
                                <Setter Property="Foreground" Value="#F1C21B"/>
                            </Trigger>
                        </ControlTemplate.Triggers>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>

        <!-- ── Primary Button ── -->
        <Style x:Key="PrimaryBtn" TargetType="Button">
            <Setter Property="Background" Value="#F1C21B"/>
            <Setter Property="Foreground" Value="#161616"/>
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
                                <Setter TargetName="Bd" Property="Background" Value="#525252"/>
                                <Setter Property="Foreground" Value="#8D8D8D"/>
                            </Trigger>
                        </ControlTemplate.Triggers>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>

        <!-- ── Cancel Button ── -->
        <Style x:Key="CancelBtn" TargetType="Button">
            <Setter Property="Background" Value="#393939"/>
            <Setter Property="Foreground" Value="#A8A8A8"/>
            <Setter Property="FontSize" Value="13"/>
            <Setter Property="Padding" Value="0,9"/>
            <Setter Property="BorderBrush" Value="#525252"/>
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
                                <Setter TargetName="Bd" Property="Background" Value="#525252"/>
                                <Setter Property="Foreground" Value="#F4F4F4"/>
                            </Trigger>
                            <Trigger Property="IsPressed" Value="True">
                                <Setter TargetName="Bd" Property="Background" Value="#6F6F6F"/>
                            </Trigger>
                        </ControlTemplate.Triggers>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>

        <!-- ── TextBox (search) ── -->
        <Style x:Key="SearchBox" TargetType="TextBox">
            <Setter Property="Background" Value="#393939"/>
            <Setter Property="Foreground" Value="#F4F4F4"/>
            <Setter Property="CaretBrush" Value="#F1C21B"/>
            <Setter Property="FontSize" Value="13"/>
            <Setter Property="BorderBrush" Value="#525252"/>
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
                                <Setter TargetName="Bd" Property="BorderBrush" Value="#F1C21B"/>
                            </Trigger>
                            <Trigger Property="IsMouseOver" Value="True">
                                <Setter TargetName="Bd" Property="BorderBrush" Value="#8D8D8D"/>
                            </Trigger>
                        </ControlTemplate.Triggers>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>

        <!-- ── TextBox (numeric input) ── -->
        <Style x:Key="InputBox" TargetType="TextBox" BasedOn="{StaticResource SearchBox}">
            <Setter Property="Padding" Value="10,8"/>
        </Style>

        <!-- ── Toggle chip (radio styled as a button) ── -->
        <Style x:Key="ToggleChip" TargetType="RadioButton">
            <Setter Property="Foreground" Value="#A8A8A8"/>
            <Setter Property="Background" Value="#393939"/>
            <Setter Property="FontSize" Value="12"/>
            <Setter Property="Padding" Value="0,8"/>
            <Setter Property="Cursor" Value="Hand"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="RadioButton">
                        <Border x:Name="Bd"
                                Background="{TemplateBinding Background}"
                                BorderBrush="#525252"
                                BorderThickness="1"
                                CornerRadius="8"
                                Padding="{TemplateBinding Padding}">
                            <ContentPresenter HorizontalAlignment="Center"
                                              VerticalAlignment="Center"/>
                        </Border>
                        <ControlTemplate.Triggers>
                            <Trigger Property="IsMouseOver" Value="True">
                                <Setter TargetName="Bd" Property="Background" Value="#525252"/>
                                <Setter Property="Foreground" Value="#F4F4F4"/>
                            </Trigger>
                            <Trigger Property="IsChecked" Value="True">
                                <Setter TargetName="Bd" Property="Background" Value="#F1C21B"/>
                                <Setter TargetName="Bd" Property="BorderBrush" Value="#F1C21B"/>
                                <Setter Property="Foreground" Value="#161616"/>
                                <Setter Property="FontWeight" Value="SemiBold"/>
                            </Trigger>
                        </ControlTemplate.Triggers>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>

    </Window.Resources>

    <!-- ── Title Bar ── -->
    <StackPanel>
        <Border Background="#0D0D0D"
                BorderBrush="#525252"
                BorderThickness="0,0,0,1"
                Padding="14,10">
            <StackPanel Orientation="Horizontal" VerticalAlignment="Center">
                <TextBlock Text="&#xE9C2;"
                           FontFamily="Segoe MDL2 Assets"
                           FontSize="15"
                           Foreground="#F1C21B"
                           VerticalAlignment="Center"
                           Margin="0,0,8,0"/>
                <TextBlock Text="Column Guard Generator"
                           Foreground="#F4F4F4"
                           FontSize="13"
                           FontWeight="SemiBold"
                           VerticalAlignment="Center"/>
            </StackPanel>
        </Border>

        <!-- ── Body ── -->
        <StackPanel Margin="14,12,14,14">

            <!-- Label -->
            <TextBlock Text="RAILING TYPE"
                       Foreground="#8D8D8D"
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
                           Foreground="#8D8D8D"
                           VerticalAlignment="Center"
                           Margin="10,0,0,0"
                           IsHitTestVisible="False"/>
                <!-- Placeholder -->
                <TextBlock x:Name="Placeholder"
                           Text="Filter railing types..."
                           Foreground="#8D8D8D"
                           FontSize="13"
                           VerticalAlignment="Center"
                           Margin="32,0,0,0"
                           IsHitTestVisible="False"/>
            </Grid>

            <!-- List -->
            <Border BorderBrush="#525252"
                    BorderThickness="1"
                    CornerRadius="8"
                    Background="#0D0D0D"
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

            <!-- Offsets -->
            <Grid Margin="0,0,0,8">
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="8"/>
                    <ColumnDefinition Width="*"/>
                </Grid.ColumnDefinitions>

                <StackPanel Grid.Column="0">
                    <TextBlock Text="FACE OFFSET (CM)"
                               Foreground="#8D8D8D"
                               FontSize="10"
                               FontWeight="SemiBold"
                               Margin="0,0,0,6"/>
                    <TextBox x:Name="OffsetBox"
                             Style="{StaticResource InputBox}"
                             Text="0"/>
                </StackPanel>

                <StackPanel Grid.Column="2">
                    <TextBlock Text="BASE OFFSET (CM)"
                               Foreground="#8D8D8D"
                               FontSize="10"
                               FontWeight="SemiBold"
                               Margin="0,0,0,6"/>
                    <TextBox x:Name="BaseOffsetBox"
                             Style="{StaticResource InputBox}"
                             Text="0"/>
                </StackPanel>
            </Grid>

            <!-- Direction -->
            <TextBlock Text="RAILING DIRECTION"
                       Foreground="#8D8D8D"
                       FontSize="10"
                       FontWeight="SemiBold"
                       Margin="0,0,0,6"/>
            <Grid Margin="0,0,0,8">
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="8"/>
                    <ColumnDefinition Width="*"/>
                </Grid.ColumnDefinitions>
                <RadioButton x:Name="NormalToggle"
                             Grid.Column="0"
                             GroupName="FlipGroup"
                             Content="Normal"
                             IsChecked="True"
                             Style="{StaticResource ToggleChip}"/>
                <RadioButton x:Name="FlipToggle"
                             Grid.Column="2"
                             GroupName="FlipGroup"
                             Content="Flipped"
                             Style="{StaticResource ToggleChip}"/>
            </Grid>

            <!-- Selected label -->
            <Border Background="#262626"
                    BorderBrush="#525252"
                    BorderThickness="1"
                    CornerRadius="6"
                    Padding="10,7"
                    Margin="0,0,0,8">
                <StackPanel Orientation="Horizontal">
                    <TextBlock Text="Selected: "
                               Foreground="#8D8D8D"
                               FontSize="12"/>
                    <TextBlock x:Name="SelectedLabel"
                               Text="None"
                               Foreground="#F1C21B"
                               FontSize="12"
                               FontWeight="SemiBold"/>
                </StackPanel>
            </Border>

            <!-- Inline error -->
            <TextBlock x:Name="ErrorLabel"
                       Text=""
                       Foreground="#FA4D56"
                       FontSize="11"
                       TextWrapping="Wrap"
                       Visibility="Collapsed"
                       Margin="0,0,0,8"/>

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
                        Content="Select Columns"
                        Style="{StaticResource PrimaryBtn}"
                        IsEnabled="False"/>
            </Grid>

        </StackPanel>
    </StackPanel>
</Window>
"""


def show_rail_picker(rail_names):
    """
    Show the railing type / offset / direction picker.
    Returns (rail_name, offset_cm, base_offset_cm, flip) or
    (None, None, None, False) if cancelled.
    """
    win = XamlReader.Parse(XAML)

    rail_list       = win.FindName("RailList")
    search_box      = win.FindName("SearchBox")
    placeholder     = win.FindName("Placeholder")
    selected_label  = win.FindName("SelectedLabel")
    offset_box      = win.FindName("OffsetBox")
    base_offset_box = win.FindName("BaseOffsetBox")
    flip_toggle     = win.FindName("FlipToggle")
    error_label     = win.FindName("ErrorLabel")
    ok_btn          = win.FindName("OkBtn")
    cancel_btn      = win.FindName("CancelBtn")

    result_holder = [None, None, None, False]
    frame         = DispatcherFrame()

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
    def on_search_changed(sender, args):
        txt = search_box.Text
        placeholder.Visibility = Visibility.Collapsed if txt else Visibility.Visible
        populate(txt)
        if selected_label.Text != "None":
            for item in rail_list.Items:
                if item.Content == selected_label.Text:
                    rail_list.SelectedItem = item
                    break

    search_box.TextChanged += TextChangedEventHandler(on_search_changed)

    # ── Selection handler ──────────────────────────────────────────────────────
    def on_selection_changed(sender, args):
        sel = rail_list.SelectedItem
        if sel is not None:
            selected_label.Text = sel.Content
            ok_btn.IsEnabled    = True
        else:
            selected_label.Text = "None"
            ok_btn.IsEnabled    = False

    rail_list.SelectionChanged += SelectionChangedEventHandler(on_selection_changed)

    # ── Button handlers ────────────────────────────────────────────────────────
    def read_number(textbox, label, allow_negative):
        raw = textbox.Text.strip()
        if not raw:
            raw = "0"
        try:
            value = float(raw)
        except ValueError:
            return None, "{} must be a number (cm).".format(label)
        if value < 0 and not allow_negative:
            return None, "{} must be zero or positive.".format(label)
        return value, None

    def on_ok(sender, args):
        offset_cm, err = read_number(offset_box, "Face offset", False)
        if err:
            error_label.Text       = err
            error_label.Visibility = Visibility.Visible
            return

        base_offset_cm, err = read_number(base_offset_box, "Base offset", True)
        if err:
            error_label.Text       = err
            error_label.Visibility = Visibility.Visible
            return

        error_label.Visibility = Visibility.Collapsed
        result_holder[0] = selected_label.Text
        result_holder[1] = offset_cm
        result_holder[2] = base_offset_cm
        result_holder[3] = bool(flip_toggle.IsChecked)
        win.Close()

    def on_cancel(sender, args):
        win.Close()

    def on_closed(sender, args):
        frame.Continue = False

    ok_btn.Click     += RoutedEventHandler(on_ok)
    cancel_btn.Click += RoutedEventHandler(on_cancel)
    win.Closed       += EventHandler(on_closed)

    win.Show()
    Dispatcher.PushFrame(frame)

    return (result_holder[0], result_holder[1],
            result_holder[2], result_holder[3])


# ─── Active View Level ────────────────────────────────────────────────────────


def get_view_level(view):
    """
    The level the railings will be hosted on. GenLevel first, then LevelId.
    Returns None for views that have no associated level (3D, drafting).
    """
    try:
        gen_level = view.GenLevel
        if gen_level is not None:
            return gen_level
    except Exception:
        pass

    try:
        level = doc.GetElement(view.LevelId)
        if isinstance(level, Level):
            return level
    except Exception:
        pass

    return None


def is_building_story(level):
    """
    Level-hosted sketch elements can be refused by non-story levels, and
    Railing.Create signals that by returning None rather than throwing.
    """
    try:
        param = level.get_Parameter(BuiltInParameter.LEVEL_IS_BUILDING_STORY)
        if param is None:
            return True
        return param.AsInteger() == 1
    except Exception:
        return True


active_view = doc.ActiveView
view_level  = get_view_level(active_view)

if view_level is None:
    notify("Column Guard Generator",
           "The active view has no associated level.\n\n"
           "Open a plan view and run again.")
    import sys; sys.exit()

view_level_name = element_name(view_level)
view_level_z    = view_level.Elevation

# ── Show UI ───────────────────────────────────────────────────────────────────

if not all_rail_names:
    notify("Column Guard Generator",
           "No Railing Types found in the Railings category.")
    import sys; sys.exit()

selected_rail, offset_cm, base_offset_cm, flip_railings = show_rail_picker(all_rail_names)

if not selected_rail:
    notify("Column Guard Generator", "No railing type selected. Script cancelled.")
    import sys; sys.exit()

selected_rail_id = rail_dict_name_id.get(selected_rail)
offset_ft        = (offset_cm or 0.0) * CM_TO_FT
base_offset_ft   = (base_offset_cm or 0.0) * CM_TO_FT

# ─── Selection Filter ─────────────────────────────────────────────────────────


class LinkedColumnFilter(ISelectionFilter):
    """Allows selection of structural or architectural columns from links."""

    def AllowElement(self, element):
        return isinstance(element, RevitLinkInstance)

    def AllowReference(self, reference, point):
        try:
            link_instance = doc.GetElement(reference.ElementId)
            if not isinstance(link_instance, RevitLinkInstance):
                return False
            linked_doc = link_instance.GetLinkDocument()
            if linked_doc is None:
                return False
            linked_element = linked_doc.GetElement(reference.LinkedElementId)
            if linked_element is None or linked_element.Category is None:
                return False
            return eid_value(linked_element.Category.Id) in COLUMN_CATEGORIES
        except Exception:
            return False


# ─── Geometry ─────────────────────────────────────────────────────────────────


def _collect_solids(geom_obj):
    """Recursively collect Solids, handling arbitrarily nested GeometryInstances."""
    solids = []
    if isinstance(geom_obj, Solid):
        if geom_obj.Volume > 1e-9:
            solids.append(geom_obj)
    elif isinstance(geom_obj, GeometryInstance):
        for child in geom_obj.GetInstanceGeometry():
            solids.extend(_collect_solids(child))
    return solids


def _solid_points(solid):
    """
    Every tessellated edge point of the solid. Works for planar, curved and
    mixed geometry alike - no face hunting, no normal tests, no edge loops.
    """
    pts = []
    try:
        for edge in solid.Edges:
            for p in edge.Tessellate():
                pts.append(p)
    except Exception:
        pass
    return pts


def _get_solids(column):
    options = Options()
    options.ComputeReferences = False
    options.DetailLevel       = ViewDetailLevel.Fine

    geom_element = column.get_Geometry(options)
    if geom_element is None:
        return []

    solids = []
    for geom_obj in geom_element:
        solids.extend(_collect_solids(geom_obj))
    return solids


def get_instance_transform(column):
    """The column's own coordinate system. Identity for in-place families."""
    try:
        tf = column.GetTransform()
        if tf is not None:
            return tf
    except Exception:
        pass
    return Transform.Identity


def oriented_rect(column):
    """
    Bounding rectangle in the COLUMN'S local coordinate system.

    This is the generic replacement for bottom-face extraction: it never
    touches faces, so chamfers, arcs, inner loops, micro-edges, joined
    geometry and sloped columns cannot break it, and it still respects the
    column's rotation.

    Returns (local_min_x, local_max_x, local_min_y, local_max_y,
             local_min_z, instance_transform) or None.
    """
    solids = _get_solids(column)
    if not solids:
        return None

    main_solid = max(solids, key=lambda s: s.Volume)
    pts = _solid_points(main_solid)
    if len(pts) < 4:
        return None

    inst_tf = get_instance_transform(column)
    try:
        inverse = inst_tf.Inverse
    except Exception:
        return None

    local = [inverse.OfPoint(p) for p in pts]

    return (min(p.X for p in local), max(p.X for p in local),
            min(p.Y for p in local), max(p.Y for p in local),
            min(p.Z for p in local), inst_tf)


def bbox_plan_size(column):
    """Plan size of the model-space bounding box, used as a sanity reference."""
    bbox = column.get_BoundingBox(None)
    if bbox is None:
        return None, None
    return (bbox.Max.X - bbox.Min.X), (bbox.Max.Y - bbox.Min.Y)


def bbox_rect_corners(column, expand_ft):
    """Axis-aligned fallback rectangle, in linked document coordinates."""
    bbox = column.get_BoundingBox(None)
    if bbox is None:
        return None, 0.0, 0.0

    mn, mx = bbox.Min, bbox.Max
    width  = mx.X - mn.X
    depth  = mx.Y - mn.Y

    min_x = mn.X - expand_ft
    max_x = mx.X + expand_ft
    min_y = mn.Y - expand_ft
    max_y = mx.Y + expand_ft
    z     = mn.Z

    corners = [XYZ(min_x, min_y, z), XYZ(max_x, min_y, z),
               XYZ(max_x, max_y, z), XYZ(min_x, max_y, z)]
    return corners, width, depth


def build_footprint(column, expand_ft):
    """
    Returns (corners_in_linked_coords, width_ft, depth_ft, source, reason).
    Tries the oriented rectangle first, validates it against the bounding
    box, and falls back to the axis-aligned box when it looks wrong.
    """
    bbox_w, bbox_d = bbox_plan_size(column)

    rect = oriented_rect(column)
    if rect is not None:
        min_x, max_x, min_y, max_y, min_z, inst_tf = rect
        width = max_x - min_x
        depth = max_y - min_y

        plausible = width >= MIN_SIDE_FT and depth >= MIN_SIDE_FT

        # The oriented rectangle can never legitimately exceed the axis-aligned
        # bounding box by much. If it does, joined geometry leaked in.
        if plausible and bbox_w is not None:
            bbox_span = max(bbox_w, bbox_d)
            rect_span = max(width, depth)
            if bbox_span > 1e-9 and rect_span > bbox_span * BBOX_SANITY_RATIO:
                plausible = False

        if plausible:
            corners_local = [
                XYZ(min_x - expand_ft, min_y - expand_ft, min_z),
                XYZ(max_x + expand_ft, min_y - expand_ft, min_z),
                XYZ(max_x + expand_ft, max_y + expand_ft, min_z),
                XYZ(min_x - expand_ft, max_y + expand_ft, min_z),
            ]
            corners = [inst_tf.OfPoint(p) for p in corners_local]
            return corners, width, depth, "oriented", None

    corners, width, depth = bbox_rect_corners(column, expand_ft)
    if corners is None:
        return None, 0.0, 0.0, None, "no geometry and no bounding box"

    if width < MIN_SIDE_FT or depth < MIN_SIDE_FT:
        return None, width, depth, None, "footprint too small to rail"

    return corners, width, depth, "bbox", None


def rect_loop(corners, target_z):
    """Closed CurveLoop of four straight segments, flattened onto target_z."""
    pts = [XYZ(p.X, p.Y, target_z) for p in corners]

    for i in range(4):
        if pts[i].DistanceTo(pts[(i + 1) % 4]) < SHORT_CURVE_FT:
            return None

    loop = CurveLoop()
    for i in range(4):
        loop.Append(Line.CreateBound(pts[i], pts[(i + 1) % 4]))
    return loop


def apply_base_offset(railing, delta):
    """Move the railing to the intended elevation when a fallback level was used."""
    if abs(delta) < 1e-9:
        return True
    try:
        param = railing.LookupParameter("Base Offset")
        if param is None:
            param = railing.get_Parameter(BuiltInParameter.STAIRS_RAILING_HEIGHT_OFFSET)
        if param is not None and not param.IsReadOnly:
            param.Set(delta)
            return True
    except Exception:
        pass
    return False


def flip_railing(railing):
    """
    Flip the railing to the other side of its path. Needs the document
    regenerated first, otherwise the fresh element has no geometry to flip.
    """
    try:
        railing.Flip()
        return True
    except Exception as ex:
        print("   Flip failed on {}: {}".format(eid_value(railing.Id), ex))
        return False


def create_railings(loop, rail_type_id, level_id, errors):
    """
    Closed loop first, two open chains as fallback.
    Returns the list of railing elements created.
    """
    try:
        railing = Railing.Create(doc, loop, rail_type_id, level_id)
        if railing is not None:
            return [railing]
        errors.append("closed loop: returned None")
    except Exception as ex:
        errors.append("closed loop: {}".format(ex))

    curves = list(loop)
    if len(curves) < 2:
        return []

    half = len(curves) // 2
    made = []

    for idx, chunk in enumerate((curves[:half], curves[half:])):
        if not chunk:
            continue
        try:
            open_loop = CurveLoop()
            for curve in chunk:
                open_loop.Append(curve)
            railing = Railing.Create(doc, open_loop, rail_type_id, level_id)
            if railing is not None:
                made.append(railing)
            else:
                errors.append("open chain {}: returned None".format(idx))
        except Exception as ex:
            errors.append("open chain {}: {}".format(idx, ex))

    return made


def levels_to_try():
    """
    The view level first. Fallback levels only if enabled, ordered by
    distance from the view level, and every use is reported.
    """
    ordered = [view_level]
    if not ALLOW_LEVEL_FALLBACK:
        return ordered

    others = [l for l in FilteredElementCollector(doc).OfClass(Level).ToElements()
              if eid_value(l.Id) != eid_value(view_level.Id)]
    others.sort(key=lambda l: abs(l.Elevation - view_level_z))
    return ordered + others[:LEVEL_FALLBACK_LIMIT]


# ─── Main ─────────────────────────────────────────────────────────────────────

try:
    references = uidoc.Selection.PickObjects(
        ObjectType.LinkedElement,
        LinkedColumnFilter(),
        "Select columns from a Revit link (Finish when done)"
    )
    references = list(references) if references else []
except Exception as pick_ex:
    print("Selection cancelled: {}".format(pick_ex))
    references = []

# PickObjects can return the same linked element more than once.
seen        = set()
unique_refs = []
for ref in references:
    key = (eid_value(ref.ElementId), eid_value(ref.LinkedElementId))
    if key in seen:
        continue
    seen.add(key)
    unique_refs.append(ref)

if len(unique_refs) != len(references):
    print("Dropped {} duplicate reference(s).".format(
        len(references) - len(unique_refs)))
references = unique_refs

report = ["Railing type : {}".format(selected_rail),
          "Face offset  : {} cm".format(offset_cm),
          "Base offset  : {} cm".format(base_offset_cm),
          "Direction    : {}".format("Flipped" if flip_railings else "Normal"),
          "Host level   : {} (elev {:.4f} ft)".format(view_level_name, view_level_z),
          "Columns      : {}".format(len(references))]

if not is_building_story(view_level):
    report.append("")
    report.append("WARNING: '{}' is not flagged as a Building Story.".format(
        view_level_name))
    report.append("That is a common reason Revit refuses to host railings.")

if not references:
    notify("Column Guard Generator", "\n".join(report + ["", "No columns selected."]))
else:
    candidate_levels  = levels_to_try()
    railings_created  = 0
    columns_done      = 0
    skipped           = []
    fallback_notes    = []
    bbox_fallbacks    = 0
    flip_failures     = 0
    offset_failures   = 0

    print("=" * 70)
    print("COLUMN GUARD GENERATOR")
    print("=" * 70)
    for line in report:
        print(line)
    print("-" * 70)

    t = Transaction(doc, "Generate Column Guardrails")
    t.Start()
    try:
        for ref in references:
            # Per-column isolation: one bad column must not stop the rest.
            try:
                link_instance = doc.GetElement(ref.ElementId)
                linked_doc    = link_instance.GetLinkDocument()
                link_tf       = link_instance.GetTotalTransform()
                column        = linked_doc.GetElement(ref.LinkedElementId)

                if column is None:
                    skipped.append("Unresolved linked element.")
                    continue

                col_label = "Column {}".format(eid_value(column.Id))

                corners, width, depth, source, reason = build_footprint(
                    column, offset_ft)

                if corners is None:
                    skipped.append("{}: {}".format(col_label, reason))
                    continue

                if source == "bbox":
                    bbox_fallbacks += 1

                print("{} | {} rect {:.1f} x {:.1f} cm".format(
                    col_label, source, width * 30.48, depth * 30.48))

                host_corners = ([link_tf.OfPoint(p) for p in corners]
                                if link_tf else corners)

                made_rails  = []
                used_level  = None
                rail_errors = []

                for lvl in candidate_levels:
                    loop = rect_loop(host_corners, lvl.Elevation)
                    if loop is None:
                        rail_errors.append("{} -> rectangle sides too short"
                                           .format(element_name(lvl)))
                        break

                    attempt_errors = []
                    made_rails = create_railings(loop, selected_rail_id,
                                                 lvl.Id, attempt_errors)
                    if made_rails:
                        used_level = lvl
                        break

                    rail_errors.append("{} -> {}".format(
                        element_name(lvl),
                        " | ".join(attempt_errors) or "unknown"))

                if not made_rails:
                    skipped.append("{}: refused. {}".format(
                        col_label, " || ".join(rail_errors)))
                    continue

                # The user's base offset, plus whatever is needed to undo a
                # level fallback, are the same parameter - set them together.
                level_delta   = view_level_z - used_level.Elevation
                total_offset  = base_offset_ft + level_delta
                fell_back     = eid_value(used_level.Id) != eid_value(view_level.Id)

                offset_ok = True
                if abs(total_offset) > 1e-9:
                    for railing in made_rails:
                        if not apply_base_offset(railing, total_offset):
                            offset_ok = False

                if not offset_ok:
                    offset_failures += 1
                    print("{} | base offset could not be set".format(col_label))

                if fell_back:
                    note = "{}: {} refused, hosted on {}{}".format(
                        col_label, view_level_name, element_name(used_level),
                        "" if offset_ok else " - BASE OFFSET NOT SET, check height")
                    fallback_notes.append(note)
                    print(note)

                if flip_railings:
                    doc.Regenerate()
                    for railing in made_rails:
                        if not flip_railing(railing):
                            flip_failures += 1

                railings_created += len(made_rails)
                columns_done     += 1

            except Exception as ex:
                skipped.append("Column error: {}".format(ex))
                print(traceback.format_exc())
                continue

        t.Commit()

        report.append("")
        report.append("Railings     : {}".format(railings_created))
        report.append("Columns done : {}".format(columns_done))

        if bbox_fallbacks:
            report.append("Bbox fallback: {} column(s)".format(bbox_fallbacks))

        if flip_failures:
            report.append("Flip failed  : {} railing(s)".format(flip_failures))

        if offset_failures:
            report.append("Offset failed: {} column(s)".format(offset_failures))

        if fallback_notes:
            report.append("")
            report.append("Level fallback used {} time(s):".format(len(fallback_notes)))
            for msg in fallback_notes[:5]:
                report.append("  - {}".format(msg))
            if len(fallback_notes) > 5:
                report.append("  ...see output window for the rest")

        if skipped:
            report.append("")
            report.append("Skipped {}:".format(len(skipped)))
            for msg in skipped[:6]:
                report.append("  - {}".format(msg))
            if len(skipped) > 6:
                report.append("  ...see output window for the rest")
            for msg in skipped:
                print("SKIPPED: {}".format(msg))

        notify("Column Guard Generator", "\n".join(report))

    except Exception as e:
        print(traceback.format_exc())
        t.RollBack()
        notify("Column Guard Generator",
               "Transaction failed and was rolled back:\n\n{}".format(e))
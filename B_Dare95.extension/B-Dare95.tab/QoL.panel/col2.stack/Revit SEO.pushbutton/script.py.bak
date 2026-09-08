# -*- coding: utf-8 -*-
__title__ = "Revit SEO"
__author__ = "Mohamed Bedair"
__version__ = '2.1.0'
__doc__ = """

Description:
Finds all Revit elements in the document matching a selected category
and optional parameter-value filters. Each row after the first carries
an AND / OR / NOT operator that controls how it combines with the
result of all previous rows (left-to-right evaluation).

Operator semantics:
  AND  — element must match both the previous result AND this filter
  OR   — element matches if the previous result OR this filter is true
  NOT  — element must match the previous result AND NOT this filter

How-to:
-> Run the script
-> Select a single category from the list
-> (Optional) Pick a parameter and value from the filter row
-> (Optional) Click "+ Add Filter" — choose AND / OR / NOT on the
   connector pill that appears between the rows, then fill in the row
-> Click "Find Elements"
-> Click any row in the results to navigate to that element in Revit
-> Click "Done" or close the results window when finished

Author: Mohamed Bedair
"""

# ─── IMPORTS ──────────────────────────────────────────────────────────────────
import System
import clr
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from System.Collections.Generic import List
from System.Windows.Threading import Dispatcher, DispatcherFrame
from Autodesk.Revit.DB import (
    FilteredElementCollector, ElementCategoryFilter,
    CategoryType, ElementId, StorageType
)
from Autodesk.Revit.UI import TaskDialog
from pyrevit import script

import System.Windows
import System.Windows.Controls as Controls
import System.Windows.Media as Media
import System.Windows.Input as WinInput
from System.Windows import (
    Thickness, CornerRadius, GridLength, GridUnitType, Visibility
)
from System.Windows.Markup import XamlReader

# ─── REVIT HANDLES ────────────────────────────────────────────────────────────
doc   = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

# ─── THEME ────────────────────────────────────────────────────────────────────
BG      = "#1E1E2E"
CARD    = "#2A2A3C"
SURFACE = "#313244"
MUTED   = "#45475A"
TEXT    = "#CDD6F4"
SUBTEXT = "#000000"    # ComboBox popup item text (light background)
HINT    = "#A6ADC8"    # muted hint / status text
ACCENT  = "#F0A500"
HOVER   = "#3D3D5C"    # row hover highlight in results window

def _brush(hex_str):
    h = hex_str.lstrip('#')
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return Media.SolidColorBrush(Media.Color.FromRgb(r, g, b))

SURFACE_BRUSH = _brush(SURFACE)
MUTED_BRUSH   = _brush(MUTED)
TEXT_BRUSH    = _brush(TEXT)
HINT_BRUSH    = _brush(HINT)
DARK_BRUSH    = Media.SolidColorBrush(Media.Color.FromRgb(20, 20, 20))
TRANS_BRUSH   = Media.Brushes.Transparent
ACCENT_BRUSH  = _brush(ACCENT)
BG_BRUSH      = _brush(BG)
CARD_BRUSH    = _brush(CARD)
HOVER_BRUSH   = _brush(HOVER)

# ─── PICKER XAML ──────────────────────────────────────────────────────────────

PICKER_XAML = """
<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Pre-Filter by Parameter"
    Width="390" MinHeight="120" MaxHeight="750"
    SizeToContent="Height"
    WindowStartupLocation="CenterScreen"
    ResizeMode="NoResize"
    Background="{BG}"
    Foreground="{TEXT}"
    FontFamily="Segoe UI"
    FontSize="13">

    <Window.Resources>

        <!-- ── Slim ScrollBar ── -->
        <Style x:Key="ScrollThumbStyle" TargetType="Thumb">
            <Setter Property="Background" Value="{MUTED}"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="Thumb">
                        <Border Background="{TemplateBinding Background}" CornerRadius="3"/>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
            <Style.Triggers>
                <Trigger Property="IsMouseOver" Value="True">
                    <Setter Property="Background" Value="{SUBTEXT}"/>
                </Trigger>
            </Style.Triggers>
        </Style>

        <Style TargetType="ScrollBar">
            <Setter Property="Background" Value="{CARD}"/>
            <Setter Property="Width" Value="6"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="ScrollBar">
                        <Grid Background="{CARD}">
                            <Track Name="PART_Track" IsDirectionReversed="True">
                                <Track.Thumb>
                                    <Thumb Style="{StaticResource ScrollThumbStyle}"/>
                                </Track.Thumb>
                            </Track>
                        </Grid>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>

        <!-- ── RadioButton (category row) ── -->
        <Style TargetType="RadioButton">
            <Setter Property="Foreground" Value="{TEXT}"/>
            <Setter Property="Margin"     Value="0,2,0,2"/>
            <Setter Property="Cursor"     Value="Hand"/>
            <Setter Property="VerticalContentAlignment" Value="Center"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="RadioButton">
                        <Grid>
                            <Grid.ColumnDefinitions>
                                <ColumnDefinition Width="18"/>
                                <ColumnDefinition Width="*"/>
                            </Grid.ColumnDefinitions>
                            <Border x:Name="Ring"
                                    Grid.Column="0"
                                    Width="14" Height="14"
                                    CornerRadius="7"
                                    Background="{SURFACE}"
                                    BorderBrush="{MUTED}"
                                    BorderThickness="1.5"
                                    VerticalAlignment="Center"/>
                            <Ellipse x:Name="Dot"
                                     Grid.Column="0"
                                     Width="6" Height="6"
                                     Fill="{BG}"
                                     HorizontalAlignment="Center"
                                     VerticalAlignment="Center"
                                     Visibility="Collapsed"/>
                            <ContentPresenter Grid.Column="1"
                                              Margin="8,0,0,0"
                                              VerticalAlignment="Center"/>
                        </Grid>
                        <ControlTemplate.Triggers>
                            <Trigger Property="IsChecked" Value="True">
                                <Setter TargetName="Ring" Property="Background"  Value="{ACCENT}"/>
                                <Setter TargetName="Ring" Property="BorderBrush" Value="{ACCENT}"/>
                                <Setter TargetName="Dot"  Property="Visibility"  Value="Visible"/>
                            </Trigger>
                            <Trigger Property="IsMouseOver" Value="True">
                                <Setter TargetName="Ring" Property="BorderBrush" Value="{ACCENT}"/>
                            </Trigger>
                        </ControlTemplate.Triggers>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>

        <!-- ── Accent (confirm) button ── -->
        <Style x:Key="AccentButton" TargetType="Button">
            <Setter Property="Background"      Value="{ACCENT}"/>
            <Setter Property="Foreground"      Value="{BG}"/>
            <Setter Property="FontWeight"      Value="SemiBold"/>
            <Setter Property="FontSize"        Value="13"/>
            <Setter Property="Height"          Value="36"/>
            <Setter Property="Cursor"          Value="Hand"/>
            <Setter Property="BorderThickness" Value="0"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="Button">
                        <Border x:Name="Bd"
                                Background="{TemplateBinding Background}"
                                CornerRadius="6">
                            <ContentPresenter HorizontalAlignment="Center"
                                              VerticalAlignment="Center"/>
                        </Border>
                        <ControlTemplate.Triggers>
                            <Trigger Property="IsMouseOver" Value="True">
                                <Setter TargetName="Bd" Property="Opacity" Value="0.85"/>
                            </Trigger>
                            <Trigger Property="IsPressed" Value="True">
                                <Setter TargetName="Bd" Property="Opacity" Value="0.7"/>
                            </Trigger>
                            <Trigger Property="IsEnabled" Value="False">
                                <Setter TargetName="Bd" Property="Opacity" Value="0.4"/>
                            </Trigger>
                        </ControlTemplate.Triggers>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>

        <!-- ── Ghost button (+ Add Filter) ── -->
        <Style x:Key="GhostButton" TargetType="Button">
            <Setter Property="Background"      Value="Transparent"/>
            <Setter Property="Foreground"      Value="{TEXT}"/>
            <Setter Property="FontSize"        Value="12"/>
            <Setter Property="BorderThickness" Value="0"/>
            <Setter Property="Cursor"          Value="Hand"/>
            <Setter Property="Padding"         Value="0"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="Button">
                        <TextBlock x:Name="Tb"
                                   Text="{TemplateBinding Content}"
                                   Foreground="{TemplateBinding Foreground}"
                                   FontSize="{TemplateBinding FontSize}"
                                   VerticalAlignment="Center"/>
                        <ControlTemplate.Triggers>
                            <Trigger Property="IsMouseOver" Value="True">
                                <Setter TargetName="Tb" Property="Foreground" Value="{ACCENT}"/>
                            </Trigger>
                            <Trigger Property="IsEnabled" Value="False">
                                <Setter TargetName="Tb" Property="Opacity" Value="0.35"/>
                            </Trigger>
                        </ControlTemplate.Triggers>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>

    </Window.Resources>

    <Border Padding="16" Background="{BG}">
        <StackPanel>

            <!-- Header -->
            <TextBlock Text="Choose Category"
                       FontSize="15" FontWeight="SemiBold"
                       Foreground="{TEXT}"
                       Margin="0,0,0,10"/>

            <!-- Search box -->
            <Border Background="{SURFACE}" CornerRadius="6" Margin="0,0,0,10"
                    BorderBrush="{MUTED}" BorderThickness="1">
                <TextBox x:Name="SearchBox"
                         Background="Transparent"
                         BorderThickness="0"
                         Foreground="{TEXT}"
                         CaretBrush="{ACCENT}"
                         Padding="8,6"
                         FontSize="12"
                         ToolTip="Filter categories..."/>
            </Border>

            <!-- Category list (RadioButtons) -->
            <Border Background="{CARD}" CornerRadius="8"
                    Padding="10,8" Margin="0,0,0,14">
                <ScrollViewer MaxHeight="300"
                              VerticalScrollBarVisibility="Auto"
                              HorizontalScrollBarVisibility="Disabled"
                              Padding="0,0,4,0">
                    <StackPanel x:Name="CategoryPanel"/>
                </ScrollViewer>
            </Border>

            <!-- Divider -->
            <Border Height="1" Background="{MUTED}" Opacity="0.4" Margin="0,0,0,12"/>

            <!-- Parameter Filters header -->
            <DockPanel Margin="0,0,0,8" LastChildFill="False">
                <TextBlock Text="PARAMETER FILTERS"
                           Foreground="{TEXT}" FontSize="10" FontWeight="SemiBold"
                           VerticalAlignment="Center"
                           DockPanel.Dock="Left"/>
                <Button x:Name="AddRowBtn"
                        Content="+ Add Filter"
                        Style="{StaticResource GhostButton}"
                        DockPanel.Dock="Right"
                        IsEnabled="False"/>
            </DockPanel>

            <!-- Column labels — widths mirror the row grid -->
            <Grid Margin="0,0,0,5">
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="10"/>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="34"/>
                </Grid.ColumnDefinitions>
                <TextBlock Grid.Column="0" Text="Parameter"
                           Foreground="{TEXT}" FontSize="11" Margin="4,0,0,0"/>
                <TextBlock Grid.Column="2" Text="Value"
                           Foreground="{TEXT}" FontSize="11" Margin="4,0,0,0"/>
            </Grid>

            <!-- Dynamic filter rows (and connector pills) injected by Python -->
            <StackPanel x:Name="RowsPanel" Margin="0,0,0,12"/>

            <!-- Confirm / search button -->
            <Button x:Name="ConfirmBtn"
                    Content="Find Elements"
                    Style="{StaticResource AccentButton}"
                    IsEnabled="False"/>

        </StackPanel>
    </Border>
</Window>
""".replace("{BG}", BG).replace("{CARD}", CARD).replace("{SURFACE}", SURFACE) \
   .replace("{MUTED}", MUTED).replace("{TEXT}", TEXT).replace("{SUBTEXT}", SUBTEXT) \
   .replace("{ACCENT}", ACCENT)


# ─── RESULTS XAML ─────────────────────────────────────────────────────────────

RESULTS_XAML = """
<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Found Elements"
    Width="560" Height="640"
    MinWidth="440" MinHeight="320"
    WindowStartupLocation="CenterScreen"
    ResizeMode="CanResize"
    Background="{BG}"
    Foreground="{TEXT}"
    FontFamily="Segoe UI"
    FontSize="13">

    <Window.Resources>

        <!-- ── Slim ScrollBar ── -->
        <Style x:Key="ScrollThumbStyle" TargetType="Thumb">
            <Setter Property="Background" Value="{MUTED}"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="Thumb">
                        <Border Background="{TemplateBinding Background}" CornerRadius="3"/>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
            <Style.Triggers>
                <Trigger Property="IsMouseOver" Value="True">
                    <Setter Property="Background" Value="{ACCENT}"/>
                </Trigger>
            </Style.Triggers>
        </Style>

        <Style TargetType="ScrollBar">
            <Setter Property="Background" Value="{CARD}"/>
            <Setter Property="Width" Value="6"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="ScrollBar">
                        <Grid Background="{CARD}">
                            <Track Name="PART_Track" IsDirectionReversed="True">
                                <Track.Thumb>
                                    <Thumb Style="{StaticResource ScrollThumbStyle}"/>
                                </Track.Thumb>
                            </Track>
                        </Grid>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>

        <!-- ── Accent (Done) button ── -->
        <Style x:Key="AccentButton" TargetType="Button">
            <Setter Property="Background"      Value="{ACCENT}"/>
            <Setter Property="Foreground"      Value="{BG}"/>
            <Setter Property="FontWeight"      Value="SemiBold"/>
            <Setter Property="FontSize"        Value="13"/>
            <Setter Property="Height"          Value="36"/>
            <Setter Property="Cursor"          Value="Hand"/>
            <Setter Property="BorderThickness" Value="0"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="Button">
                        <Border x:Name="Bd"
                                Background="{TemplateBinding Background}"
                                CornerRadius="6">
                            <ContentPresenter HorizontalAlignment="Center"
                                              VerticalAlignment="Center"/>
                        </Border>
                        <ControlTemplate.Triggers>
                            <Trigger Property="IsMouseOver" Value="True">
                                <Setter TargetName="Bd" Property="Opacity" Value="0.85"/>
                            </Trigger>
                            <Trigger Property="IsPressed" Value="True">
                                <Setter TargetName="Bd" Property="Opacity" Value="0.7"/>
                            </Trigger>
                        </ControlTemplate.Triggers>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>

    </Window.Resources>

    <Border Padding="16">
        <DockPanel LastChildFill="True">

            <!-- ── Header ── -->
            <StackPanel DockPanel.Dock="Top" Margin="0,0,0,12">
                <TextBlock x:Name="CountLabel"
                           FontSize="15" FontWeight="SemiBold"
                           Foreground="{TEXT}"/>
                <TextBlock Text="Click a row to open and zoom to that element"
                           Foreground="{HINT}"
                           FontSize="11" Margin="0,3,0,0"/>
            </StackPanel>

            <!-- ── Search / filter box ── -->
            <Border DockPanel.Dock="Top"
                    Background="{SURFACE}" CornerRadius="6"
                    Margin="0,0,0,10"
                    BorderBrush="{MUTED}" BorderThickness="1">
                <TextBox x:Name="SearchBox"
                         Background="Transparent"
                         BorderThickness="0"
                         Foreground="{TEXT}"
                         CaretBrush="{ACCENT}"
                         Padding="8,6"
                         FontSize="12"
                         ToolTip="Filter results by name or level..."/>
            </Border>

            <!-- ── Done button (bottom) ── -->
            <Button x:Name="DoneBtn"
                    DockPanel.Dock="Bottom"
                    Content="Done"
                    Style="{StaticResource AccentButton}"
                    Margin="0,10,0,0"/>

            <!-- ── Status label (above Done button) ── -->
            <TextBlock x:Name="StatusLabel"
                       DockPanel.Dock="Bottom"
                       Foreground="{HINT}"
                       FontSize="11"
                       TextAlignment="Center"
                       Margin="0,8,0,0"
                       Text=" "/>

            <!-- ── Column headers ── -->
            <Grid DockPanel.Dock="Top" Margin="2,0,8,4">
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="86"/>
                    <ColumnDefinition Width="110"/>
                </Grid.ColumnDefinitions>
                <TextBlock Grid.Column="0" Text="NAME"
                           Foreground="{HINT}" FontSize="10" FontWeight="SemiBold"
                           Margin="10,0,0,0"/>
                <TextBlock Grid.Column="1" Text="ELEMENT ID"
                           Foreground="{HINT}" FontSize="10" FontWeight="SemiBold"
                           Margin="4,0,0,0"/>
                <TextBlock Grid.Column="2" Text="LEVEL"
                           Foreground="{HINT}" FontSize="10" FontWeight="SemiBold"
                           Margin="4,0,0,0"/>
            </Grid>
            <Border DockPanel.Dock="Top"
                    Height="1" Background="{MUTED}" Opacity="0.4" Margin="0,0,0,4"/>

            <!-- ── Scrollable rows area ── -->
            <Border Background="{CARD}" CornerRadius="8" Padding="2">
                <ScrollViewer VerticalScrollBarVisibility="Auto"
                              HorizontalScrollBarVisibility="Disabled"
                              Padding="0,0,4,0">
                    <StackPanel x:Name="RowsPanel" Margin="2,4,2,4"/>
                </ScrollViewer>
            </Border>

        </DockPanel>
    </Border>
</Window>
""".replace("{BG}", BG).replace("{CARD}", CARD).replace("{SURFACE}", SURFACE) \
   .replace("{MUTED}", MUTED).replace("{TEXT}", TEXT).replace("{HINT}", HINT) \
   .replace("{ACCENT}", ACCENT)


# ─── REVIT HELPERS ────────────────────────────────────────────────────────────

def _eid_int(eid):
    """Read ElementId integer safely across Revit versions."""
    try:
        return eid.Value          # Revit 2025+ (Int64)
    except AttributeError:
        return eid.IntegerValue   # Revit < 2025


def get_all_category_names(doc):
    return sorted(
        cat.Name for cat in doc.Settings.Categories
        if cat.CategoryType == CategoryType.Model
    )


def get_category_by_name(doc, name):
    for cat in doc.Settings.Categories:
        if cat.Name == name:
            return cat
    return None


def get_param_value_string(param):
    """Convert any parameter value to a readable string, or None."""
    try:
        if param is None or not param.HasValue:
            return None
        st = param.StorageType
        if st == StorageType.String:
            v = param.AsString()
            return v if v else None
        elif st == StorageType.Integer:
            vs = param.AsValueString()
            return vs if vs else str(param.AsInteger())
        elif st == StorageType.Double:
            vs = param.AsValueString()
            return vs if vs else str(round(param.AsDouble(), 6))
        elif st == StorageType.ElementId:
            eid = param.AsElementId()
            if eid is None or _eid_int(eid) < 0:
                return None
            try:
                e = doc.GetElement(eid)
                if e is not None and hasattr(e, 'Name') and e.Name:
                    return e.Name
            except Exception:
                pass
            return str(_eid_int(eid))
        return None
    except Exception:
        return None


def get_params_for_category(category_name):
    """Sorted list of every parameter name (instance + type) for *category_name*."""
    cat_obj = get_category_by_name(doc, category_name)
    if cat_obj is None:
        return []

    params         = set()
    seen_type_ints = set()

    try:
        col = (FilteredElementCollector(doc)
               .WherePasses(ElementCategoryFilter(cat_obj.Id))
               .WhereElementIsNotElementType())
        for elem in col:
            for p in elem.Parameters:
                if p.Definition:
                    params.add(p.Definition.Name)
            try:
                tid = elem.GetTypeId()
                if tid and _eid_int(tid) > 0:
                    k = _eid_int(tid)
                    if k not in seen_type_ints:
                        seen_type_ints.add(k)
                        etype = doc.GetElement(tid)
                        if etype:
                            for p in etype.Parameters:
                                if p.Definition:
                                    params.add(p.Definition.Name)
            except Exception:
                pass
    except Exception:
        pass

    return sorted(params)


def get_values_for_param(category_name, param_name):
    """Sorted list of unique human-readable values for *param_name*."""
    cat_obj = get_category_by_name(doc, category_name)
    if cat_obj is None:
        return []

    values         = set()
    seen_type_ints = set()

    try:
        col = (FilteredElementCollector(doc)
               .WherePasses(ElementCategoryFilter(cat_obj.Id))
               .WhereElementIsNotElementType())
        for elem in col:
            p = elem.LookupParameter(param_name)
            if p:
                v = get_param_value_string(p)
                if v is not None:
                    values.add(v)
            try:
                tid = elem.GetTypeId()
                if tid and _eid_int(tid) > 0:
                    k = _eid_int(tid)
                    if k not in seen_type_ints:
                        seen_type_ints.add(k)
                        etype = doc.GetElement(tid)
                        if etype:
                            p = etype.LookupParameter(param_name)
                            if p:
                                v = get_param_value_string(p)
                                if v is not None:
                                    values.add(v)
            except Exception:
                pass
    except Exception:
        pass

    return sorted(values)


def element_matches_single_param(elem, param_name, param_value):
    """True if elem or its type has *param_name* equal to *param_value*."""
    try:
        p = elem.LookupParameter(param_name)
        if p and get_param_value_string(p) == param_value:
            return True
    except Exception:
        pass
    try:
        tid = elem.GetTypeId()
        if tid and _eid_int(tid) > 0:
            etype = doc.GetElement(tid)
            if etype:
                p = etype.LookupParameter(param_name)
                if p and get_param_value_string(p) == param_value:
                    return True
    except Exception:
        pass
    return False


def element_matches_filters_with_ops(elem, param_filters):
    """
    Evaluate *param_filters* against *elem* using per-row operators.

    param_filters  – list of (param_name, param_value, operator)
                     Operator on the first item is ignored (base row).

    Operators:
      'AND'  →  result = result AND  match(this row)
      'OR'   →  result = result OR   match(this row)
      'NOT'  →  result = result AND NOT match(this row)  (exclude matching)

    Evaluation is strictly left-to-right.
    An empty list returns True (no filter → pass everything).
    """
    if not param_filters:
        return True

    result = element_matches_single_param(
        elem, param_filters[0][0], param_filters[0][1]
    )

    for i in range(1, len(param_filters)):
        pname, pval, op = param_filters[i]
        current = element_matches_single_param(elem, pname, pval)
        if op == 'AND':
            result = result and current
        elif op == 'OR':
            result = result or current
        elif op == 'NOT':
            result = result and not current

    return result


def collect_matching_elements(category_name, param_filters):
    """
    Return every non-type element whose category is *category_name* and that
    satisfies all *param_filters*.  Returns a list of Revit Element objects.
    """
    cat_obj = get_category_by_name(doc, category_name)
    if cat_obj is None:
        return []
    try:
        col = (FilteredElementCollector(doc)
               .WherePasses(ElementCategoryFilter(cat_obj.Id))
               .WhereElementIsNotElementType()
               .ToElements())
        if not param_filters:
            return list(col)
        return [e for e in col if element_matches_filters_with_ops(e, param_filters)]
    except Exception:
        return []


def get_element_display_name(elem):
    """
    Best human-readable name for *elem*.
    Priority: elem.Name → Mark param → type name → category name.
    """
    try:
        n = elem.Name
        if n and n.strip():
            return n.strip()
    except Exception:
        pass
    try:
        p = elem.LookupParameter("Mark")
        if p and p.HasValue:
            v = get_param_value_string(p)
            if v:
                return v
    except Exception:
        pass
    try:
        tid = elem.GetTypeId()
        if tid and _eid_int(tid) > 0:
            t = doc.GetElement(tid)
            if t and hasattr(t, 'Name') and t.Name:
                return t.Name
    except Exception:
        pass
    try:
        return elem.Category.Name if elem.Category else u"Unknown"
    except Exception:
        return u"Unknown"


def get_element_level_name(elem):
    """
    Best level string for *elem*.
    Priority: LevelId lookup → Level parameter → em-dash fallback.
    """
    try:
        lid = elem.LevelId
        if lid is not None and _eid_int(lid) > 0:
            lv = doc.GetElement(lid)
            if lv and hasattr(lv, 'Name') and lv.Name:
                return lv.Name
    except Exception:
        pass
    try:
        p = elem.LookupParameter("Level")
        if p and p.HasValue:
            v = p.AsValueString() or p.AsString()
            if v:
                return v
    except Exception:
        pass
    return u"\u2014"   # em dash


# ─── UI HELPERS ───────────────────────────────────────────────────────────────

def _combo_item(text):
    """ComboBoxItem with dark text — readable in the default white popup."""
    item = Controls.ComboBoxItem()
    item.Content    = text
    item.Foreground = DARK_BRUSH
    item.Padding    = Thickness(6, 4, 6, 4)
    return item


def _combo_value(combo):
    """Return the selected value string from a ComboBox, or None."""
    sel = combo.SelectedItem
    if sel is None:
        return None
    return str(sel.Content) if hasattr(sel, 'Content') else str(sel)


# ─── CONNECTOR WIDGET (AND / OR / NOT pills) ──────────────────────────────────

def create_connector_widget(row):
    """
    Build the operator-selector widget that sits between two filter rows.

    Renders as three pill-shaped toggle buttons (AND / OR / NOT) flanked by
    subtle horizontal rules that visually connect the rows above and below.

    The active operator is stored in row['operator'] (a mutable one-item list
    so closures can mutate it without needing 'nonlocal').

    Returns the root Grid widget (ready to add to rows_panel).
    """
    # ── Root: 3-column grid  [line ─── pills ─── line] ────────────────────
    container = Controls.Grid()
    container.Margin = Thickness(0, 4, 0, 4)

    for w in [
        GridLength(1, GridUnitType.Star),
        GridLength.Auto,
        GridLength(1, GridUnitType.Star),
    ]:
        cd = Controls.ColumnDefinition()
        cd.Width = w
        container.ColumnDefinitions.Add(cd)

    def _rule():
        line = Controls.Border()
        line.Height            = 1
        line.Background        = MUTED_BRUSH
        line.Opacity           = 0.35
        line.VerticalAlignment = System.Windows.VerticalAlignment.Center
        return line

    left_rule  = _rule()
    right_rule = _rule()
    Controls.Grid.SetColumn(left_rule,  0)
    Controls.Grid.SetColumn(right_rule, 2)
    container.Children.Add(left_rule)
    container.Children.Add(right_rule)

    # ── Pills panel (centre column) ────────────────────────────────────────
    pills_panel = Controls.StackPanel()
    pills_panel.Orientation = Controls.Orientation.Horizontal
    pills_panel.Margin      = Thickness(6, 0, 6, 0)
    Controls.Grid.SetColumn(pills_panel, 1)
    container.Children.Add(pills_panel)

    # ── Build individual pills ─────────────────────────────────────────────
    # pill_refs: op_label → (Border_widget, TextBlock_widget)
    pill_refs = {}

    for op_label in ['AND', 'OR', 'NOT']:
        border = Controls.Border()
        border.CornerRadius    = CornerRadius(9)
        border.Padding         = Thickness(9, 3, 9, 3)
        border.Margin          = Thickness(0, 0, 4, 0)
        border.Cursor          = WinInput.Cursors.Hand

        tb = Controls.TextBlock()
        tb.Text               = op_label
        tb.FontSize           = 10
        tb.FontWeight         = System.Windows.FontWeights.SemiBold
        tb.VerticalAlignment  = System.Windows.VerticalAlignment.Center
        tb.HorizontalAlignment = System.Windows.HorizontalAlignment.Center

        border.Child = tb
        pills_panel.Children.Add(border)
        pill_refs[op_label] = (border, tb)

    # ── Style helper: apply active/inactive visuals ────────────────────────
    def _refresh_pills():
        current = row['operator'][0]
        for lbl, (brd, txt) in pill_refs.items():
            if lbl == current:
                brd.Background      = ACCENT_BRUSH
                brd.BorderThickness = Thickness(0)
                txt.Foreground      = BG_BRUSH
                txt.Opacity         = 1.0
            else:
                brd.Background      = SURFACE_BRUSH
                brd.BorderBrush     = MUTED_BRUSH
                brd.BorderThickness = Thickness(1)
                txt.Foreground      = TEXT_BRUSH
                txt.Opacity         = 0.45

    # ── Click handler: select this operator ───────────────────────────────
    # Default-arg pattern captures op_label and row safely in IronPython 2.7
    def _on_click(s, e, op=None, r=row):
        r['operator'][0] = op
        _refresh_pills()

    for lbl in ['AND', 'OR', 'NOT']:
        pill_refs[lbl][0].MouseLeftButtonDown += (
            lambda s, e, op=lbl: _on_click(s, e, op)
        )

    _refresh_pills()   # initialise with AND selected
    return container


# ─── PICKER DIALOG ────────────────────────────────────────────────────────────

def show_category_picker(all_categories):
    """
    Display the themed category / parameter-filter picker.

    Returns (category_name, param_filters) where:
        category_name  – str
        param_filters  – [] or [(param_name, param_value, operator), ...]
                         operator on index 0 is always 'AND' (base row)

    Returns None when the user closes without confirming.
    """
    window = XamlReader.Parse(PICKER_XAML)

    search_box  = window.FindName("SearchBox")
    cat_panel   = window.FindName("CategoryPanel")
    confirm_btn = window.FindName("ConfirmBtn")
    add_row_btn = window.FindName("AddRowBtn")
    rows_panel  = window.FindName("RowsPanel")

    result_holder = [None]
    selected_cat  = [None]
    radio_buttons = []
    rows          = []

    # ── Confirm-button enable state ────────────────────────────────────────
    def update_confirm():
        if selected_cat[0] is None:
            confirm_btn.IsEnabled = False
            return
        for row in rows:
            p_sel    = _combo_value(row['param_combo'])
            v_sel    = _combo_value(row['value_combo'])
            has_vals = row['value_combo'].Items.Count > 0
            if p_sel is not None and has_vals and v_sel is None:
                confirm_btn.IsEnabled = False
                return
        confirm_btn.IsEnabled = True

    # ── Populate param combo for one row ──────────────────────────────────
    def populate_row_params(row):
        row['param_combo'].Items.Clear()
        row['value_combo'].Items.Clear()
        row['value_combo'].IsEnabled = False
        if selected_cat[0] is None:
            return
        for name in get_params_for_category(selected_cat[0]):
            row['param_combo'].Items.Add(_combo_item(name))

    # ── Populate value combo for one row ──────────────────────────────────
    def reload_row_values(row):
        row['value_combo'].Items.Clear()
        row['value_combo'].IsEnabled = False
        p_val = _combo_value(row['param_combo'])
        if p_val is None or selected_cat[0] is None:
            update_confirm()
            return
        for v in get_values_for_param(selected_cat[0], p_val):
            row['value_combo'].Items.Add(_combo_item(v))
        row['value_combo'].IsEnabled = row['value_combo'].Items.Count > 0
        update_confirm()

    # ── Remove a filter row ───────────────────────────────────────────────
    def remove_row(row):
        # Remove the connector widget that precedes this row (if any)
        if row['connector_grid'] is not None:
            rows_panel.Children.Remove(row['connector_grid'])
        rows_panel.Children.Remove(row['grid'])
        rows.remove(row)

        # Edge case: if the removed row was first, the new first row may
        # still have a dangling connector_grid — strip it from the panel.
        if rows and rows[0]['connector_grid'] is not None:
            rows_panel.Children.Remove(rows[0]['connector_grid'])
            rows[0]['connector_grid'] = None

        update_confirm()

    # ── Create and attach one new filter row ──────────────────────────────
    def create_filter_row():
        # Build the row dict first so create_connector_widget can reference it
        row = {
            'grid':           None,    # set below
            'param_combo':    None,
            'value_combo':    None,
            'remove_btn':     None,
            'operator':       ['AND'], # mutable — default AND
            'connector_grid': None,    # set below for rows after the first
        }
        rows.append(row)

        # ── Connector pill (only for rows after the first) ─────────────────
        if len(rows) > 1:
            connector = create_connector_widget(row)
            row['connector_grid'] = connector
            rows_panel.Children.Add(connector)

        # ── Filter row grid: [param | 10 | value | 8 | ×] ─────────────────
        grid = Controls.Grid()
        grid.Margin = Thickness(0, 0, 0, 6)
        for w in [
            GridLength(1, GridUnitType.Star),
            GridLength(10),
            GridLength(1, GridUnitType.Star),
            GridLength(8),
            GridLength.Auto,
        ]:
            cd = Controls.ColumnDefinition()
            cd.Width = w
            grid.ColumnDefinitions.Add(cd)

        # Parameter ComboBox
        param_combo = Controls.ComboBox()
        param_combo.Background      = TRANS_BRUSH
        param_combo.Foreground      = DARK_BRUSH
        param_combo.BorderThickness = Thickness(0)
        param_combo.Height          = 30
        param_combo.FontSize        = 12
        param_combo.Padding         = Thickness(6, 0, 4, 0)
        param_combo.ToolTip         = "Select a parameter"

        param_border = Controls.Border()
        param_border.Background      = SURFACE_BRUSH
        param_border.CornerRadius    = CornerRadius(6)
        param_border.BorderBrush     = MUTED_BRUSH
        param_border.BorderThickness = Thickness(1)
        param_border.Child           = param_combo
        Controls.Grid.SetColumn(param_border, 0)
        grid.Children.Add(param_border)

        # Value ComboBox
        value_combo = Controls.ComboBox()
        value_combo.Background      = TRANS_BRUSH
        value_combo.Foreground      = DARK_BRUSH
        value_combo.BorderThickness = Thickness(0)
        value_combo.Height          = 30
        value_combo.FontSize        = 12
        value_combo.Padding         = Thickness(6, 0, 4, 0)
        value_combo.IsEnabled       = False
        value_combo.ToolTip         = "Select a value"

        value_border = Controls.Border()
        value_border.Background      = SURFACE_BRUSH
        value_border.CornerRadius    = CornerRadius(6)
        value_border.BorderBrush     = MUTED_BRUSH
        value_border.BorderThickness = Thickness(1)
        value_border.Child           = value_combo
        Controls.Grid.SetColumn(value_border, 2)
        grid.Children.Add(value_border)

        # Remove (×) button
        remove_btn = Controls.Button()
        remove_btn.Content           = u"\u00d7"
        remove_btn.Width             = 26
        remove_btn.Height            = 26
        remove_btn.Background        = TRANS_BRUSH
        remove_btn.BorderThickness   = Thickness(0)
        remove_btn.Foreground        = MUTED_BRUSH
        remove_btn.FontSize          = 17
        remove_btn.Cursor            = WinInput.Cursors.Hand
        remove_btn.VerticalAlignment = System.Windows.VerticalAlignment.Center
        Controls.Grid.SetColumn(remove_btn, 4)
        grid.Children.Add(remove_btn)

        # Back-fill the row dict
        row['grid']        = grid
        row['param_combo'] = param_combo
        row['value_combo'] = value_combo
        row['remove_btn']  = remove_btn

        rows_panel.Children.Add(grid)

        if selected_cat[0] is not None:
            populate_row_params(row)

        # Wire events — r=row default arg captures this row's reference safely
        def _on_param(s, e, r=row):
            reload_row_values(r)

        def _on_value(s, e):
            update_confirm()

        def _on_remove(s, e, r=row):
            remove_row(r)

        param_combo.SelectionChanged += _on_param
        value_combo.SelectionChanged += _on_value
        remove_btn.Click             += _on_remove

        update_confirm()

    # ── Category radio changed ─────────────────────────────────────────────
    def on_radio_checked(sender, e):
        selected_cat[0] = sender.Tag
        add_row_btn.IsEnabled = True
        for row in rows:
            populate_row_params(row)
        update_confirm()

    # ── Search filter ──────────────────────────────────────────────────────
    def on_search_changed(sender, e):
        query = search_box.Text.strip().lower()
        for rb in radio_buttons:
            rb.Visibility = (
                Visibility.Visible
                if query in rb.Tag.lower()
                else Visibility.Collapsed
            )

    # ── Confirm ────────────────────────────────────────────────────────────
    def on_confirm(sender, e):
        cat = selected_cat[0]
        if cat is None:
            return
        param_filters = []
        for i, row in enumerate(rows):
            p = _combo_value(row['param_combo'])
            v = _combo_value(row['value_combo'])
            if p is not None and v is not None:
                # First row is the base; subsequent rows carry their chosen operator.
                op = row['operator'][0] if i > 0 else 'AND'
                param_filters.append((p, v, op))
        result_holder[0] = (cat, param_filters)
        window.Close()

    # ── Build RadioButton list ─────────────────────────────────────────────
    for name in all_categories:
        rb          = Controls.RadioButton()
        rb.Content  = name
        rb.Tag      = name
        rb.Checked += on_radio_checked
        cat_panel.Children.Add(rb)
        radio_buttons.append(rb)

    # ── Wire static events ─────────────────────────────────────────────────
    search_box.TextChanged += on_search_changed
    add_row_btn.Click      += lambda s, e: create_filter_row()
    confirm_btn.Click      += on_confirm

    create_filter_row()
    update_confirm()
    window.ShowDialog()
    return result_holder[0]


# ─── RESULTS WINDOW ───────────────────────────────────────────────────────────

def show_results_window(elements, category_name):
    """
    Modeless results window.  Each row shows [Name, Element ID, Level].
    Clicking a row calls uidoc.ShowElements() to open and zoom to the element.
    The search box narrows visible rows by name or level substring.

    Blocks via Dispatcher.PushFrame until the user closes the window or
    clicks Done — this keeps the script alive without freezing Revit.
    """
    window = XamlReader.Parse(RESULTS_XAML)

    count_label  = window.FindName("CountLabel")
    search_box   = window.FindName("SearchBox")
    rows_panel   = window.FindName("RowsPanel")
    done_btn     = window.FindName("DoneBtn")
    status_label = window.FindName("StatusLabel")

    count = len(elements)
    count_label.Text = u"{} element{} found  \u2014  {}".format(
        count,
        u"s" if count != 1 else u"",
        category_name
    )

    # ── Build row widgets ──────────────────────────────────────────────────
    # Each entry: (border_widget, searchable_text, revit_ElementId)
    row_entries = []
    last_selected_id = [None]

    for elem in elements:
        name  = get_element_display_name(elem)
        eid   = str(_eid_int(elem.Id))
        level = get_element_level_name(elem)
        elem_id = elem.Id   # Revit ElementId object kept for ShowElements

        # Outer border (provides hover background + click target)
        row_border = Controls.Border()
        row_border.CornerRadius = CornerRadius(6)
        row_border.Background   = TRANS_BRUSH
        row_border.Padding      = Thickness(8, 7, 8, 7)
        row_border.Margin       = Thickness(0, 1, 0, 1)
        row_border.Cursor       = WinInput.Cursors.Hand

        # Inner grid: 3 columns mirroring the XAML header
        g = Controls.Grid()
        for col_width in [
            GridLength(1, GridUnitType.Star),
            GridLength(86),
            GridLength(110),
        ]:
            cd = Controls.ColumnDefinition()
            cd.Width = col_width
            g.ColumnDefinitions.Add(cd)

        def _tb(text, col_idx, muted=False):
            tb = Controls.TextBlock()
            tb.Text          = text
            tb.Foreground    = HINT_BRUSH if muted else TEXT_BRUSH
            tb.FontSize      = 12
            tb.Margin        = Thickness(4, 0, 4, 0)
            tb.VerticalAlignment = System.Windows.VerticalAlignment.Center
            tb.TextTrimming  = System.Windows.TextTrimming.CharacterEllipsis
            Controls.Grid.SetColumn(tb, col_idx)
            return tb

        g.Children.Add(_tb(name,  0))
        g.Children.Add(_tb(eid,   1, muted=True))
        g.Children.Add(_tb(level, 2, muted=True))

        row_border.Child = g
        rows_panel.Children.Add(row_border)

        searchable = (name + u" " + level).lower()
        row_entries.append((row_border, searchable, elem_id))

    # ── Wire hover + click for every row ──────────────────────────────────
    def _hover_enter(border):
        def handler(s, e):
            border.Background = HOVER_BRUSH
        return handler

    def _hover_leave(border):
        def handler(s, e):
            border.Background = TRANS_BRUSH
        return handler

    def _on_click(eid_ref, name_ref):
        def handler(s, e):
            try:
                uidoc.ShowElements(eid_ref)
                last_selected_id[0] = eid_ref
                status_label.Text = u"Opened: {}  (ID {})".format(
                    name_ref, _eid_int(eid_ref)
                )
            except Exception:
                status_label.Text = u"Cannot navigate to this element."
        return handler

    for border, _searchable, elem_id in row_entries:
        try:
            row_name = border.Child.Children[0].Text
        except Exception:
            row_name = u"element"

        border.MouseEnter          += _hover_enter(border)
        border.MouseLeave          += _hover_leave(border)
        border.MouseLeftButtonDown += _on_click(elem_id, row_name)

    # ── Search / filter box ────────────────────────────────────────────────
    def on_search_changed(s, e):
        q = search_box.Text.strip().lower()
        for border, searchable, _ in row_entries:
            border.Visibility = (
                Visibility.Visible
                if not q or q in searchable
                else Visibility.Collapsed
            )

    search_box.TextChanged += on_search_changed

    # ── Done button ────────────────────────────────────────────────────────
    def on_done(s, e):
        try:
            if last_selected_id[0]:
                sel_ids = List[ElementId]()
                sel_ids.Add(last_selected_id[0])
                uidoc.Selection.SetElementIds(sel_ids)
                uidoc.ShowElements(last_selected_id[0])
        except Exception:
            pass
        window.Close()

    done_btn.Click += on_done

    # ── Show modeless with Dispatcher.PushFrame (non-blocking for Revit) ──
    frame = [DispatcherFrame()]

    def on_closed(s, e):
        frame[0].Continue = False

    window.Closed += on_closed
    window.Show()
    Dispatcher.PushFrame(frame[0])


# ─── MAIN ─────────────────────────────────────────────────────────────────────

all_categories = get_all_category_names(doc)
result         = show_category_picker(all_categories)

if not result:
    script.exit()

category_name, param_filters = result

elements = collect_matching_elements(category_name, param_filters)

if not elements:
    filter_desc = u""
    if param_filters:
        parts = []
        for i, (p, v, op) in enumerate(param_filters):
            prefix = u"  \u2022 " if i == 0 else u"  {} ".format(op)
            parts.append(u"{}{} = {}".format(prefix, p, v))
        filter_desc = u"\n\nFilters applied:\n" + u"\n".join(parts)
    TaskDialog.Show(
        "Pre-Filter by Parameter",
        u"No elements found for category \u201c{}\u201d.{}".format(
            category_name, filter_desc
        )
    )
    script.exit()

show_results_window(elements, category_name)
# -*- coding: utf-8 -*-
__title__   = "Renumber By Grid\n[Cartesian]"
__author__  = "B-Dare95"
__version__ = "Version 1.0"
__doc__     = """Version = 1.0
Date    = 19.05.2026
_____________________________________________________________________
Description:
Renumber a chosen text parameter for elements of a selected category
using Cartesian plane grid ordering.

Elements are collected from the Active View, then sorted:
  - Rows    : by Y-axis (bottom to top  OR  top to bottom)
  - Columns : by X-axis (left to right, closest to origin first)

Numbering is applied sequentially, starting from the project origin
(0,0) and moving outward in the positive X/Y direction.
_____________________________________________________________________
How-to:
-> Select a Category from the left panel  (search box to filter)
-> Select a writable text Parameter from the right panel
   (list updates automatically when a category is chosen)
-> Set Prefix, Suffix, Start Number, Y-Tolerance, and Sort Direction
-> Click RUN
_____________________________________________________________________
Notes:
- Y-Tolerance (ft): elements whose Y centres differ by less than this
  value are treated as belonging to the same row.  Default = 1.5 ft
  (~457 mm).  Reduce for tightly-packed elements.
- Elements with no locatable centre (no bounding box / location) are
  skipped silently.
_____________________________________________________________________
Last update:
- [19.05.2026] - 1.0 RELEASE
_____________________________________________________________________
Author: B-Dare95"""

# ╦╔╦╗╔═╗╔═╗╦═╗╔╦╗╔═╗
# ║║║║╠═╝║ ║╠╦╝ ║ ╚═╗
# ╩╩ ╩╩  ╚═╝╩╚═ ╩ ╚═╝
# ==================================================
import os
import traceback

from Autodesk.Revit.DB import (
    BuiltInCategory,
    CategoryType,
    ElementCategoryFilter,
    FilteredElementCollector,
    StorageType,
    Transaction,
)
from pyrevit import forms

import clr
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")
clr.AddReference("System")

from System.Windows.Markup import XamlReader

# ╦  ╦╔═╗╦═╗╦╔═╗╔╗ ╦  ╔═╗╔═╗
# ╚╗╔╝╠═╣╠╦╝║╠═╣╠╩╗║  ║╣ ╚═╗
#  ╚╝ ╩ ╩╩╚═╩╩ ╩╚═╝╩═╝╚═╝╚═╝
# ==================================================
doc      = __revit__.ActiveUIDocument.Document   # noqa: F821
uidoc    = __revit__.ActiveUIDocument            # noqa: F821
app      = __revit__.Application                 # noqa: F821
rvt_year = int(app.VersionNumber)

# ╔╦╗╦═╗╔═╗╔╗╔╔═╗╔═╗╔═╗╔╦╗╦╔═╗╔╗╔  ╦ ╦╦═╗╔═╗╔═╗╔═╗╔═╗╦═╗
#  ║ ╠╦╝╠═╣║║║╚═╗╠═╣║   ║ ║║ ║║║║  ║║║╠╦╝╠═╣╠═╝╠═╝║╣ ╠╦╝
#  ╩ ╩╚═╩ ╩╝╚╝╚═╝╩ ╩╚═╝ ╩ ╩╚═╝╝╚╝  ╚╩╝╩╚═╩ ╩╩  ╩  ╚═╝╩╚═
# ==================================================
# Import ef_Transaction if available; otherwise fall back to a thin wrapper.
try:
    from Snippets._context_manager import ef_Transaction  # noqa: F401
    _HAS_EF = True
except Exception:
    _HAS_EF = False


class _SimpleTx(object):
    """Minimal context-manager wrapper around a plain Revit Transaction."""

    def __init__(self, doc, name):
        self._t = Transaction(doc, name)

    def __enter__(self):
        self._t.Start()
        return self._t

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            if self._t.HasStarted():
                self._t.RollBack()
        else:
            if self._t.HasStarted():
                self._t.Commit()
        return False


def _make_tx(doc, name):
    """Return the best available transaction context-manager."""
    if _HAS_EF:
        return ef_Transaction(doc, name, debug=True)
    return _SimpleTx(doc, name)


# ╔═╗╔═╗╦═╗╔╦╗╦╔╗╔╔═╗  ╦ ╦╔╦╗╦╦  ╦╔╦╗╦╔═╗╔═╗
# ╚═╗║ ║╠╦╝ ║ ║║║║║ ╦  ║ ║ ║ ║║  ║ ║ ║║╣ ╚═╗
# ╚═╝╚═╝╩╚═ ╩ ╩╝╚╝╚═╝  ╚═╝ ╩ ╩╩═╝╩ ╩ ╩╚═╝╚═╝
# ==================================================

def get_element_center(el):
    """
    Return the (X, Y) model-space centre of an element, or None.

    Tries bounding-box first (model-space, no view pipeline), then
    falls back to Location.Point / Location.Curve midpoint.
    Note: get_BoundingBox(None) is safe inside loops — does NOT trigger
    the view graphics pipeline.
    """
    try:
        bb = el.get_BoundingBox(None)
        if bb:
            return ((bb.Min.X + bb.Max.X) * 0.5,
                    (bb.Min.Y + bb.Max.Y) * 0.5)
    except Exception:
        pass
    try:
        loc = el.Location
        if hasattr(loc, 'Point') and loc.Point:
            return (loc.Point.X, loc.Point.Y)
        if hasattr(loc, 'Curve') and loc.Curve:
            mid = loc.Curve.Evaluate(0.5, True)
            return (mid.X, mid.Y)
    except Exception:
        pass
    return None


def sort_by_cartesian_grid(elements, y_tol, ascending_y=True):
    """
    Sort *elements* in Cartesian reading order and return the sorted list.

    Algorithm
    ---------
    1. Obtain the XY model-space centre of every element.
    2. Sort all located elements by Y (ascending = bottom-to-top).
    3. Group into rows: consecutive elements whose Y centres differ by
       <= y_tol belong to the same row.
    4. Within each row sort by X ascending (left to right).
    5. Elements with no locatable centre are appended at the end.

    Parameters
    ----------
    elements    : iterable of Revit DB Elements
    y_tol       : float  — Y grouping tolerance in internal feet
    ascending_y : bool   — True  → bottom-to-top (default, from origin)
                           False → top-to-bottom
    """
    located   = []
    unlocated = []

    for el in elements:
        c = get_element_center(el)
        if c is not None:
            located.append((el, c[0], c[1]))   # (element, x, y)
        else:
            unlocated.append(el)

    if not located:
        return list(unlocated)

    # ── Step 1: primary sort by Y ──────────────────────────────────────
    located.sort(key=lambda t: t[2], reverse=not ascending_y)

    # ── Step 2: group into rows by Y-tolerance ─────────────────────────
    rows        = []
    current_row = [located[0]]
    row_y       = located[0][2]

    for item in located[1:]:
        if abs(item[2] - row_y) <= y_tol:
            current_row.append(item)
        else:
            current_row.sort(key=lambda t: t[1])   # sort row by X asc
            rows.append(current_row)
            current_row = [item]
            row_y       = item[2]

    current_row.sort(key=lambda t: t[1])
    rows.append(current_row)

    # ── Step 3: flatten rows then append unlocated ─────────────────────
    result = [t[0] for row in rows for t in row]
    result.extend(unlocated)
    return result


# ╔═╗╔═╗╔╦╗╔═╗╔═╗╔═╗╦═╗╦╔═╗╔═╗
# ║  ╠═╣ ║ ║╣ ║ ╦║ ║╠╦╝║║╣ ╚═╗
# ╚═╝╩ ╩ ╩ ╚═╝╚═╝╚═╝╩╚═╩╚═╝╚═╝
# ==================================================

def check_cat(cat):
    """
    Return True for usable model categories.
    Revit 2023+ exposes BuiltInCategory.INVALID for non-BuiltIn cats,
    which previously caused attribute errors — hence try/except.
    """
    try:
        if rvt_year > 2022:
            if cat.BuiltInCategory == BuiltInCategory.INVALID:
                return False
        return cat.CategoryType == CategoryType.Model
    except Exception:
        return False


def collect_writable_params(cat_id):
    """
    Return a sorted list of writable String-type parameter names for
    elements of *cat_id* visible in the active view.
    """
    try:
        elements = (
            FilteredElementCollector(doc, doc.ActiveView.Id)
            .WherePasses(ElementCategoryFilter(cat_id))
            .WhereElementIsNotElementType()
            .ToElements()
        )
        seen   = set()
        result = []
        for el in elements:
            for param in el.Parameters:
                n = param.Definition.Name
                if (n not in seen
                        and not param.IsReadOnly
                        and param.StorageType == StorageType.String):
                    seen.add(n)
                    result.append(n)
        result.sort()
        return result
    except Exception:
        return []


# ╔═╗╦  ╦ ╦╦
# ║ ╦║  ║ ║║
# ╚═╝╩═╝╚═╝╩
# ==================================================

XAML_STR = """
<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Renumber By Grid [Cartesian]"
    Width="760" Height="600"
    MinWidth="680" MinHeight="560"
    WindowStartupLocation="CenterScreen"
    ResizeMode="NoResize"
    Background="#1E1E2E"
    FontFamily="Segoe UI">

    <Window.Resources>

        <!-- ── ListBoxItem ───────────────────────────────────────── -->
        <Style x:Key="S_LBI" TargetType="ListBoxItem">
            <Setter Property="Foreground"   Value="#CDD6F4"/>
            <Setter Property="Background"   Value="Transparent"/>
            <Setter Property="Padding"      Value="8,5"/>
            <Setter Property="FontSize"     Value="12"/>
            <Setter Property="Cursor"       Value="Hand"/>
            <Setter Property="BorderThickness" Value="0"/>
            <Style.Triggers>
                <Trigger Property="IsSelected" Value="True">
                    <Setter Property="Background" Value="#F0A500"/>
                    <Setter Property="Foreground" Value="#1E1E2E"/>
                    <Setter Property="FontWeight" Value="SemiBold"/>
                </Trigger>
                <Trigger Property="IsMouseOver" Value="True">
                    <Setter Property="Background" Value="#45475A"/>
                </Trigger>
            </Style.Triggers>
        </Style>

        <!-- ── ListBox ───────────────────────────────────────────── -->
        <Style TargetType="ListBox">
            <Setter Property="Background"       Value="#313244"/>
            <Setter Property="BorderBrush"      Value="#45475A"/>
            <Setter Property="BorderThickness"  Value="1"/>
            <Setter Property="ItemContainerStyle" Value="{StaticResource S_LBI}"/>
            <Setter Property="ScrollViewer.HorizontalScrollBarVisibility" Value="Disabled"/>
            <Setter Property="Padding"          Value="0"/>
        </Style>

        <!-- ── TextBox ───────────────────────────────────────────── -->
        <Style TargetType="TextBox">
            <Setter Property="Background"      Value="#313244"/>
            <Setter Property="Foreground"      Value="#CDD6F4"/>
            <Setter Property="BorderBrush"     Value="#45475A"/>
            <Setter Property="BorderThickness" Value="1"/>
            <Setter Property="Padding"         Value="7,5"/>
            <Setter Property="CaretBrush"      Value="#CDD6F4"/>
            <Setter Property="FontSize"        Value="12"/>
            <Setter Property="SelectionBrush"  Value="#F0A500"/>
        </Style>

        <!-- ── Panel label ───────────────────────────────────────── -->
        <Style x:Key="S_PanelHeader" TargetType="TextBlock">
            <Setter Property="Foreground"  Value="#A6ADC8"/>
            <Setter Property="FontSize"    Value="11"/>
            <Setter Property="FontWeight"  Value="SemiBold"/>
            <Setter Property="Margin"      Value="0,0,0,7"/>
        </Style>

        <!-- ── Field label ───────────────────────────────────────── -->
        <Style x:Key="S_FieldLabel" TargetType="TextBlock">
            <Setter Property="Foreground" Value="#A6ADC8"/>
            <Setter Property="FontSize"   Value="11"/>
            <Setter Property="Margin"     Value="0,0,0,4"/>
        </Style>

        <!-- ── RUN button ────────────────────────────────────────── -->
        <Style x:Key="S_RunBtn" TargetType="Button">
            <Setter Property="Background"      Value="#F0A500"/>
            <Setter Property="Foreground"      Value="#1E1E2E"/>
            <Setter Property="FontWeight"      Value="Bold"/>
            <Setter Property="FontSize"        Value="13"/>
            <Setter Property="BorderThickness" Value="0"/>
            <Setter Property="Cursor"          Value="Hand"/>
            <Setter Property="Padding"         Value="0,11"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="Button">
                        <Border Background="{TemplateBinding Background}"
                                CornerRadius="6"
                                Padding="{TemplateBinding Padding}">
                            <ContentPresenter HorizontalAlignment="Center"
                                              VerticalAlignment="Center"/>
                        </Border>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
            <Style.Triggers>
                <Trigger Property="IsMouseOver" Value="True">
                    <Setter Property="Background" Value="#E09400"/>
                </Trigger>
            </Style.Triggers>
        </Style>

        <!-- ── CANCEL button ─────────────────────────────────────── -->
        <Style x:Key="S_CancelBtn" TargetType="Button">
            <Setter Property="Background"      Value="#313244"/>
            <Setter Property="Foreground"      Value="#CDD6F4"/>
            <Setter Property="BorderBrush"     Value="#45475A"/>
            <Setter Property="BorderThickness" Value="1"/>
            <Setter Property="FontSize"        Value="13"/>
            <Setter Property="Cursor"          Value="Hand"/>
            <Setter Property="Padding"         Value="0,11"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="Button">
                        <Border Background="{TemplateBinding Background}"
                                CornerRadius="6"
                                BorderBrush="{TemplateBinding BorderBrush}"
                                BorderThickness="{TemplateBinding BorderThickness}"
                                Padding="{TemplateBinding Padding}">
                            <ContentPresenter HorizontalAlignment="Center"
                                              VerticalAlignment="Center"/>
                        </Border>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
            <Style.Triggers>
                <Trigger Property="IsMouseOver" Value="True">
                    <Setter Property="Background" Value="#45475A"/>
                </Trigger>
            </Style.Triggers>
        </Style>

        <!-- ── Direction RadioButton (pill toggle) ───────────────── -->
        <Style x:Key="S_DirBtn" TargetType="RadioButton">
            <Setter Property="Foreground"      Value="#CDD6F4"/>
            <Setter Property="Background"      Value="#313244"/>
            <Setter Property="BorderBrush"     Value="#45475A"/>
            <Setter Property="BorderThickness" Value="1"/>
            <Setter Property="FontSize"        Value="12"/>
            <Setter Property="Padding"         Value="10,6"/>
            <Setter Property="Cursor"          Value="Hand"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="RadioButton">
                        <Border Background="{TemplateBinding Background}"
                                BorderBrush="{TemplateBinding BorderBrush}"
                                BorderThickness="{TemplateBinding BorderThickness}"
                                CornerRadius="6"
                                Padding="{TemplateBinding Padding}">
                            <ContentPresenter HorizontalAlignment="Center"
                                              VerticalAlignment="Center"/>
                        </Border>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
            <Style.Triggers>
                <Trigger Property="IsChecked" Value="True">
                    <Setter Property="Background"  Value="#F0A500"/>
                    <Setter Property="Foreground"  Value="#1E1E2E"/>
                    <Setter Property="FontWeight"  Value="SemiBold"/>
                    <Setter Property="BorderBrush" Value="#F0A500"/>
                </Trigger>
                <Trigger Property="IsMouseOver" Value="True">
                    <Setter Property="Background" Value="#45475A"/>
                </Trigger>
            </Style.Triggers>
        </Style>

    </Window.Resources>

    <!-- ═══════════════════════ ROOT GRID ════════════════════════════ -->
    <Grid Margin="18">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>  <!-- title bar          -->
            <RowDefinition Height="*"/>     <!-- two-panel content  -->
            <RowDefinition Height="Auto"/>  <!-- divider            -->
            <RowDefinition Height="Auto"/>  <!-- button row         -->
        </Grid.RowDefinitions>

        <!-- ══ TITLE BAR ══════════════════════════════════════════════ -->
        <Grid Grid.Row="0" Margin="0,0,0,14">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="Auto"/>
            </Grid.ColumnDefinitions>
            <StackPanel Grid.Column="0">
                <TextBlock Text="RENUMBER BY GRID  ·  CARTESIAN PLANE"
                           Foreground="#F0A500"
                           FontSize="15" FontWeight="Bold"/>
                <TextBlock Text="Sorts active-view elements by Y rows then X columns, originating from (0, 0)."
                           Foreground="#585B70"
                           FontSize="11" Margin="0,3,0,0"/>
            </StackPanel>
            <TextBlock Grid.Column="1" x:Name="UI_version_lbl"
                       Foreground="#585B70" FontSize="11"
                       VerticalAlignment="Top" HorizontalAlignment="Right"/>
        </Grid>

        <!-- ══ TWO-PANEL CONTENT ════════════════════════════════════════ -->
        <Grid Grid.Row="1">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="14"/>
                <ColumnDefinition Width="*"/>
            </Grid.ColumnDefinitions>

            <!-- ─── LEFT PANEL: Category ─────────────────────────────── -->
            <Border Grid.Column="0"
                    Background="#2A2A3C" CornerRadius="8" Padding="12">
                <Grid>
                    <Grid.RowDefinitions>
                        <RowDefinition Height="Auto"/>   <!-- header         -->
                        <RowDefinition Height="Auto"/>   <!-- search box     -->
                        <RowDefinition Height="*"/>      <!-- list           -->
                        <RowDefinition Height="Auto"/>   <!-- status label   -->
                    </Grid.RowDefinitions>

                    <TextBlock Grid.Row="0"
                               Text="CATEGORY"
                               Style="{StaticResource S_PanelHeader}"/>

                    <!-- Search / filter box -->
                    <TextBox   x:Name="UI_cat_search"
                               Grid.Row="1"
                               Margin="0,0,0,6"/>

                    <!-- Category list -->
                    <ListBox   x:Name="UI_cat_list"
                               Grid.Row="2"
                               SelectionMode="Single"/>

                    <!-- Element count feedback -->
                    <TextBlock x:Name="UI_cat_status"
                               Grid.Row="3"
                               Foreground="#585B70"
                               FontSize="11"
                               Margin="0,6,0,0"
                               TextWrapping="Wrap"/>
                </Grid>
            </Border>

            <!-- ─── RIGHT PANEL: Parameters + config ─────────────────── -->
            <Border Grid.Column="2"
                    Background="#2A2A3C" CornerRadius="8" Padding="12">
                <Grid>
                    <Grid.RowDefinitions>
                        <RowDefinition Height="Auto"/>   <!-- header         -->
                        <RowDefinition Height="*"/>      <!-- param list     -->
                        <RowDefinition Height="Auto"/>   <!-- controls       -->
                    </Grid.RowDefinitions>

                    <TextBlock Grid.Row="0"
                               Text="PARAMETER  (writable · text only)"
                               Style="{StaticResource S_PanelHeader}"/>

                    <!-- Parameter list (updates on category selection) -->
                    <ListBox   x:Name="UI_param_list"
                               Grid.Row="1"
                               SelectionMode="Single"
                               Margin="0,0,0,12"/>

                    <!-- ── Controls grid ── -->
                    <Grid Grid.Row="2">
                        <Grid.RowDefinitions>
                            <RowDefinition Height="Auto"/>
                            <RowDefinition Height="Auto"/>
                            <RowDefinition Height="Auto"/>
                        </Grid.RowDefinitions>
                        <Grid.ColumnDefinitions>
                            <ColumnDefinition Width="*"/>
                            <ColumnDefinition Width="8"/>
                            <ColumnDefinition Width="*"/>
                        </Grid.ColumnDefinitions>

                        <!-- Prefix -->
                        <StackPanel Grid.Row="0" Grid.Column="0" Margin="0,0,0,8">
                            <TextBlock Text="Prefix  (optional)"
                                       Style="{StaticResource S_FieldLabel}"/>
                            <TextBox x:Name="UI_prefix"/>
                        </StackPanel>

                        <!-- Suffix -->
                        <StackPanel Grid.Row="0" Grid.Column="2" Margin="0,0,0,8">
                            <TextBlock Text="Suffix  (optional)"
                                       Style="{StaticResource S_FieldLabel}"/>
                            <TextBox x:Name="UI_suffix"/>
                        </StackPanel>

                        <!-- Start Number -->
                        <StackPanel Grid.Row="1" Grid.Column="0" Margin="0,0,0,8">
                            <TextBlock Text="Start Number"
                                       Style="{StaticResource S_FieldLabel}"/>
                            <TextBox x:Name="UI_start" Text="1"/>
                        </StackPanel>

                        <!-- Y-Tolerance -->
                        <StackPanel Grid.Row="1" Grid.Column="2" Margin="0,0,0,8">
                            <TextBlock Text="Y-Tolerance  (ft)"
                                       Style="{StaticResource S_FieldLabel}"/>
                            <TextBox x:Name="UI_tolerance" Text="1.5"/>
                        </StackPanel>

                        <!-- Sort direction pills -->
                        <StackPanel Grid.Row="2" Grid.Column="0"
                                    Grid.ColumnSpan="3">
                            <TextBlock Text="Row Sort Direction"
                                       Style="{StaticResource S_FieldLabel}"/>
                            <Grid>
                                <Grid.ColumnDefinitions>
                                    <ColumnDefinition Width="*"/>
                                    <ColumnDefinition Width="8"/>
                                    <ColumnDefinition Width="*"/>
                                </Grid.ColumnDefinitions>
                                <RadioButton x:Name="UI_dir_bt"
                                             Grid.Column="0"
                                             Content="&#x2191;  Bottom &#x2192; Top"
                                             GroupName="SortDir"
                                             IsChecked="True"
                                             Style="{StaticResource S_DirBtn}"/>
                                <RadioButton x:Name="UI_dir_tb"
                                             Grid.Column="2"
                                             Content="&#x2193;  Top &#x2192; Bottom"
                                             GroupName="SortDir"
                                             Style="{StaticResource S_DirBtn}"/>
                            </Grid>
                        </StackPanel>
                    </Grid>
                    <!-- end controls grid -->
                </Grid>
            </Border>
        </Grid>

        <!-- ══ DIVIDER ═════════════════════════════════════════════════ -->
        <Border Grid.Row="2"
                Height="1" Background="#313244"
                Margin="0,12,0,12"/>

        <!-- ══ BUTTON ROW ══════════════════════════════════════════════ -->
        <Grid Grid.Row="3">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="10"/>
                <ColumnDefinition Width="*"/>
            </Grid.ColumnDefinitions>
            <Button x:Name="UI_cancel"
                    Grid.Column="0"
                    Content="CANCEL"
                    Style="{StaticResource S_CancelBtn}"/>
            <Button x:Name="UI_run"
                    Grid.Column="2"
                    Content="RUN"
                    Style="{StaticResource S_RunBtn}"/>
        </Grid>
    </Grid>
</Window>
"""


# ╔═╗╦  ╦ ╦╦   ╔═╗╦  ╔═╗╔═╗╔═╗
# ║ ╦║  ║ ║║   ║  ║  ╠═╣╚═╗╚═╗
# ╚═╝╩═╝╚═╝╩   ╚═╝╩═╝╩ ╩╚═╝╚═╝
# ==================================================

class GridNumberUI(object):
    """
    WPF dialog for Cartesian-grid-based renumbering.

    All output is stored in mutable list containers to stay compatible
    with IronPython 2.7 (no nonlocal keyword).
    """

    def __init__(self, cats_dict):
        self._cats_dict = cats_dict
        self._all_names = sorted(cats_dict.keys())

        # ── Output state (mutable containers) ────────────────────────
        self.confirmed  = [False]
        self.cat_name   = [None]
        self.param_name = [None]
        self.prefix     = ['']
        self.suffix     = ['']
        self.start      = [1]
        self.tolerance  = [1.5]
        self.asc_y      = [True]   # True = bottom-to-top

        # ── Build window from inline XAML ─────────────────────────────
        self._win = XamlReader.Parse(XAML_STR)

        # ── Resolve named controls ────────────────────────────────────
        self._cat_search  = self._win.FindName('UI_cat_search')
        self._cat_list    = self._win.FindName('UI_cat_list')
        self._cat_status  = self._win.FindName('UI_cat_status')
        self._param_list  = self._win.FindName('UI_param_list')
        self._prefix_tb   = self._win.FindName('UI_prefix')
        self._suffix_tb   = self._win.FindName('UI_suffix')
        self._start_tb    = self._win.FindName('UI_start')
        self._tol_tb      = self._win.FindName('UI_tolerance')
        self._dir_bt      = self._win.FindName('UI_dir_bt')
        self._dir_tb      = self._win.FindName('UI_dir_tb')
        self._btn_run     = self._win.FindName('UI_run')
        self._btn_cancel  = self._win.FindName('UI_cancel')
        self._ver_lbl     = self._win.FindName('UI_version_lbl')

        # Stamp version in top-right corner
        if self._ver_lbl:
            self._ver_lbl.Text = __version__

        # ── Populate category list ────────────────────────────────────
        self._populate_cats(self._all_names)

        # ── Wire events ───────────────────────────────────────────────
        self._cat_search.TextChanged     += self._on_search
        self._cat_list.SelectionChanged  += self._on_cat_selected
        self._btn_run.Click              += self._on_run
        self._btn_cancel.Click           += self._on_cancel

        # Blocking dialog — execution pauses here until window closes
        self._win.ShowDialog()

    # ── Private helpers ───────────────────────────────────────────────

    def _populate_cats(self, names):
        """Rebuild the category ListBox with *names*."""
        self._cat_list.Items.Clear()
        for n in names:
            self._cat_list.Items.Add(n)

    # ── Event handlers ────────────────────────────────────────────────

    def _on_search(self, sender, e):
        """Filter category list as the user types."""
        q = self._cat_search.Text.strip().lower()
        filtered = (
            [n for n in self._all_names if q in n.lower()]
            if q else self._all_names
        )
        self._populate_cats(filtered)
        self._cat_status.Text = ''

    def _on_cat_selected(self, sender, e):
        """
        Triggered when the user picks a category.
        Rebuilds the parameter list and updates the element-count label.
        """
        name = self._cat_list.SelectedItem
        if not name:
            return
        cat = self._cats_dict.get(name)
        if not cat:
            return

        # ── Rebuild parameter list ────────────────────────────────────
        params = collect_writable_params(cat.Id)
        self._param_list.Items.Clear()
        if params:
            for p in params:
                self._param_list.Items.Add(p)
        else:
            self._param_list.Items.Add('— no writable text parameters found —')

        # ── Element count status ──────────────────────────────────────
        try:
            n_els = (
                FilteredElementCollector(doc, doc.ActiveView.Id)
                .WherePasses(ElementCategoryFilter(cat.Id))
                .WhereElementIsNotElementType()
                .GetElementCount()
            )
            self._cat_status.Text = (
                '{} element{} found in active view'.format(
                    n_els, 's' if n_els != 1 else ''
                )
            )
        except Exception:
            self._cat_status.Text = ''

    def _on_run(self, sender, e):
        """Validate inputs, store results, close window."""
        cat   = self._cat_list.SelectedItem
        param = self._param_list.SelectedItem

        if not cat:
            forms.alert('Please select a Category.', title=__title__)
            return
        if not param or param.startswith('—'):
            forms.alert('Please select a valid Parameter.', title=__title__)
            return

        try:
            start = int(self._start_tb.Text.strip())
        except (ValueError, AttributeError):
            forms.alert(
                'Start Number must be a whole number (e.g. 1).',
                title=__title__
            )
            return

        try:
            tol = float(self._tol_tb.Text.strip().replace(',', '.'))
            if tol < 0.0:
                raise ValueError('negative tolerance')
        except (ValueError, AttributeError):
            forms.alert(
                'Y-Tolerance must be a non-negative number (e.g. 1.5).',
                title=__title__
            )
            return

        # Persist results in mutable containers
        self.confirmed[0]  = True
        self.cat_name[0]   = cat
        self.param_name[0] = param
        self.prefix[0]     = self._prefix_tb.Text   or ''
        self.suffix[0]     = self._suffix_tb.Text   or ''
        self.start[0]      = start
        self.tolerance[0]  = tol
        # IsChecked on a WPF RadioButton returns Nullable<bool>
        self.asc_y[0]      = (self._dir_bt.IsChecked == True)  # noqa: E712
        self._win.Close()

    def _on_cancel(self, sender, e):
        self._win.Close()


# ╔╦╗╔═╗╦╔╗╔  ╔═╗═╗ ╦╔═╗╔═╗╦ ╦╔╦╗╦╔═╗╔╗╔
# ║║║╠═╣║║║║  ║╣ ╔╩╦╝║╣ ║  ║ ║ ║ ║║ ║║║║
# ╩ ╩╩ ╩╩╝╚╝  ╚═╝╩ ╚═╚═╝╚═╝╚═╝ ╩ ╩╚═╝╝╚╝
# ==================================================

# ── Build category dictionary ─────────────────────────────────────────────
cats = [c for c in doc.Settings.Categories if check_cat(c)]

# Append annotation / specialty categories that are commonly numbered
# and are not captured by CategoryType.Model
_EXTRA_BICS = [
    BuiltInCategory.OST_Grids,
    BuiltInCategory.OST_Viewports,
    BuiltInCategory.OST_Rooms,
    BuiltInCategory.OST_Areas,
    BuiltInCategory.OST_MEPSpaces,
]
_existing_names = {c.Name for c in cats}
for _bic in _EXTRA_BICS:
    try:
        _extra = doc.Settings.Categories.get_Item(_bic)
        if _extra and _extra.Name not in _existing_names:
            cats.append(_extra)
            _existing_names.add(_extra.Name)
    except Exception:
        pass

cats.sort(key=lambda c: c.Name)
cats_dict = {c.Name: c for c in cats}

# ── Launch dialog ─────────────────────────────────────────────────────────
ui = GridNumberUI(cats_dict)

if not ui.confirmed[0]:
    forms.alert('Cancelled.', title=__title__, exitscript=True)

# ── Unpack user choices ───────────────────────────────────────────────────
sel_cat  = cats_dict[ui.cat_name[0]]
p_name   = ui.param_name[0]
prefix   = ui.prefix[0]
suffix   = ui.suffix[0]
count    = ui.start[0]
y_tol    = ui.tolerance[0]
asc_y    = ui.asc_y[0]

# ── Collect elements from the active view ─────────────────────────────────
all_els = list(
    FilteredElementCollector(doc, doc.ActiveView.Id)
    .WherePasses(ElementCategoryFilter(sel_cat.Id))
    .WhereElementIsNotElementType()
    .ToElements()
)

if not all_els:
    forms.alert(
        'No elements found in the active view for:\n  {}'.format(ui.cat_name[0]),
        title=__title__,
        exitscript=True,
    )

# ── Sort in Cartesian grid order ──────────────────────────────────────────
sorted_els = sort_by_cartesian_grid(all_els, y_tol, ascending_y=asc_y)

# ── Apply numbering in a single transaction ───────────────────────────────
start_count = count
numbered    = 0
skipped     = 0

with _make_tx(doc, __title__):
    for el in sorted_els:
        param = el.LookupParameter(p_name)
        if param and not param.IsReadOnly and param.StorageType == StorageType.String:
            try:
                param.Set(prefix + str(count) + suffix)
                count    += 1
                numbered += 1
            except Exception:
                skipped += 1
        else:
            skipped += 1

# ── Summary alert ─────────────────────────────────────────────────────────
direction_label = 'Bottom \u2192 Top' if asc_y else 'Top \u2192 Bottom'

forms.alert(
    'Renumbering complete!\n\n'
    'Category   : {cat}\n'
    'Parameter  : {param}\n'
    'Direction  : {dir}\n'
    'Tolerance  : {tol} ft\n\n'
    '{n} element{pl} numbered.\n'
    'Range      : {pfx}{s}{sfx}  \u2192  {pfx}{e}{sfx}\n'
    '{sk} element{skpl} skipped (no matching parameter).'.format(
        cat   = ui.cat_name[0],
        param = p_name,
        dir   = direction_label,
        tol   = y_tol,
        n     = numbered,
        pl    = 's' if numbered != 1 else '',
        pfx   = prefix,
        sfx   = suffix,
        s     = start_count,
        e     = count - 1,
        sk    = skipped,
        skpl  = 's' if skipped != 1 else '',
    ),
    title=__title__,
)
# ==================================================
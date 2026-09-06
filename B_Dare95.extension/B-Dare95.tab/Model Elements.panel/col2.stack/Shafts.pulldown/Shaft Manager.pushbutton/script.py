# -*- coding: utf-8 -*-
__title__   = "Shaft Opening Manager"
__author__  = "Mohamed Bedair"
__version__ = "1.0.0"
__doc__     = """

Description:
Collects every Shaft Opening in the project and presents them in a
live-editable table with the following columns:

  ID (read-only) · Base Constraint · Base Offset ·
  Top Constraint · Top Offset · Shaft Function

Prerequisite:
  The custom parameter "Shaft Function" must already be bound to the
  Openings category (Manage → Project Parameters). The script exits
  with an explanatory message if it is absent.

How-to:
-> Run the script
-> The Shaft Opening Manager window opens immediately
-> Edit any cell directly — ComboBox for levels, TextBox for offsets
   and Shaft Function value
-> Use the search bar to filter rows by ID or Shaft Function text
-> Click an element's ID to select it and navigate Revit to that shaft
-> Click ✕ at the end of a row to mark that shaft for deletion
-> "Save Changes" commits all edits (and deletes) in a single transaction
-> "Cancel" discards all edits and closes the window

Author: Mohamed Bedair
"""

# ─── IMPORTS ───────────────────────────────────────────────────────────────────
import System
import clr
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from System.Collections.Generic import List
from Autodesk.Revit.DB import (
    FilteredElementCollector, ElementCategoryFilter,
    BuiltInCategory, BuiltInParameter,
    ElementId, Transaction, Level
)
from Autodesk.Revit.UI import TaskDialog
from pyrevit import script

import System.Windows
import System.Windows.Controls as Controls
import System.Windows.Media as Media
import System.Windows.Input as WinInput
import System.Windows.Threading as Threading
from System.Windows import (
    Thickness, CornerRadius, GridLength, GridUnitType, Visibility,
    VerticalAlignment, HorizontalAlignment, TextTrimming
)
from System.Windows.Markup import XamlReader

# ─── REVIT HANDLES ─────────────────────────────────────────────────────────────
doc   = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

# ─── THEME ─────────────────────────────────────────────────────────────────────
BG      = "#1E1E2E"
CARD    = "#2A2A3C"
SURFACE = "#313244"
MUTED   = "#45475A"
TEXT    = "#CDD6F4"
SUBTEXT = "#A6ADC8"
ACCENT  = "#F0A500"
ROW_A   = "#2A2A3C"   # even-indexed rows
ROW_B   = "#252535"   # odd-indexed rows (zebra stripe)
HDR_BG  = "#1A1A28"   # column header row background

def _brush(hex_str):
    h = hex_str.lstrip('#')
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return Media.SolidColorBrush(Media.Color.FromRgb(r, g, b))

SURFACE_BRUSH = _brush(SURFACE)
MUTED_BRUSH   = _brush(MUTED)
TEXT_BRUSH    = _brush(TEXT)
SUBTEXT_BRUSH = _brush(SUBTEXT)
ACCENT_BRUSH  = _brush(ACCENT)
ROW_A_BRUSH   = _brush(ROW_A)
ROW_B_BRUSH   = _brush(ROW_B)
HDR_BRUSH     = _brush(HDR_BG)
DARK_BRUSH    = Media.SolidColorBrush(Media.Color.FromRgb(20, 20, 20))
TRANS_BRUSH   = Media.Brushes.Transparent

# ─── COLUMN LAYOUT ─────────────────────────────────────────────────────────────
# 11 slots total: controls at even indices (0, 2, 4, 6, 8, 10),
# fixed-width gap spacers at odd indices (1, 3, 5, 7, 9).
COL_SPECS = [
    GridLength(68),                        # 0  – ID (read-only, fixed px)
    GridLength(8),                         # 1  – gap
    GridLength(1.35, GridUnitType.Star),   # 2  – Base Constraint (ComboBox)
    GridLength(8),                         # 3  – gap
    GridLength(80),                        # 4  – Base Offset (TextBox, fixed px)
    GridLength(8),                         # 5  – gap
    GridLength(1.35, GridUnitType.Star),   # 6  – Top Constraint (ComboBox)
    GridLength(8),                         # 7  – gap
    GridLength(80),                        # 8  – Top Offset (TextBox, fixed px)
    GridLength(8),                         # 9  – gap
    GridLength(1.8,  GridUnitType.Star),   # 10 – Shaft Function (TextBox)
    GridLength(8),                         # 11 – gap
    GridLength(28),                        # 12 – Delete button (fixed px)
]
CTRL_COLS  = [0, 2, 4, 6, 8, 10, 12]
HDR_LABELS = [
    "ID", "Base Constraint", "Base Offset",
    "Top Constraint", "Top Offset", "Shaft Function", "",
]

# ─── XAML ──────────────────────────────────────────────────────────────────────
# Colour tokens: {BG}, {CARD}, etc.
# WPF markup extensions: {{StaticResource X}}, {{TemplateBinding X}} —
# the double-braces are collapsed to single after colour substitution.
BROWSER_XAML = """
<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Shaft Opening Editor"
    Width="1000" Height="640"
    MinWidth="740" MinHeight="440"
    WindowStartupLocation="CenterScreen"
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
                        <Border Background="{{TemplateBinding Background}}" CornerRadius="3"/>
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
            <Setter Property="Width"      Value="6"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="ScrollBar">
                        <Grid Background="{CARD}">
                            <Track Name="PART_Track" IsDirectionReversed="True">
                                <Track.Thumb>
                                    <Thumb Style="{{StaticResource ScrollThumbStyle}}"/>
                                </Track.Thumb>
                            </Track>
                        </Grid>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>

        <!-- ── Save / Accent button ── -->
        <Style x:Key="SaveBtnStyle" TargetType="Button">
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
                                Background="{{TemplateBinding Background}}"
                                CornerRadius="6">
                            <ContentPresenter HorizontalAlignment="Center"
                                              VerticalAlignment="Center"/>
                        </Border>
                        <ControlTemplate.Triggers>
                            <Trigger Property="IsMouseOver" Value="True">
                                <Setter TargetName="Bd" Property="Opacity" Value="0.85"/>
                            </Trigger>
                            <Trigger Property="IsPressed"  Value="True">
                                <Setter TargetName="Bd" Property="Opacity" Value="0.70"/>
                            </Trigger>
                            <Trigger Property="IsEnabled"  Value="False">
                                <Setter TargetName="Bd" Property="Opacity" Value="0.40"/>
                            </Trigger>
                        </ControlTemplate.Triggers>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>

        <!-- ── Cancel / Secondary button ── -->
        <Style x:Key="CancelBtnStyle" TargetType="Button">
            <Setter Property="Background"      Value="{SURFACE}"/>
            <Setter Property="Foreground"      Value="{TEXT}"/>
            <Setter Property="FontSize"        Value="13"/>
            <Setter Property="Height"          Value="36"/>
            <Setter Property="Cursor"          Value="Hand"/>
            <Setter Property="BorderThickness" Value="1"/>
            <Setter Property="BorderBrush"     Value="{MUTED}"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="Button">
                        <Border x:Name="Bd"
                                Background="{{TemplateBinding Background}}"
                                BorderBrush="{{TemplateBinding BorderBrush}}"
                                BorderThickness="{{TemplateBinding BorderThickness}}"
                                CornerRadius="6">
                            <ContentPresenter HorizontalAlignment="Center"
                                              VerticalAlignment="Center"/>
                        </Border>
                        <ControlTemplate.Triggers>
                            <Trigger Property="IsMouseOver" Value="True">
                                <Setter TargetName="Bd" Property="Opacity" Value="0.75"/>
                            </Trigger>
                        </ControlTemplate.Triggers>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>

    </Window.Resources>

    <Border Padding="16" Background="{BG}">
        <DockPanel>

            <!-- ── Title bar + search ── -->
            <DockPanel DockPanel.Dock="Top" Margin="0,0,0,12" LastChildFill="False">
                <TextBlock x:Name="TitleLabel"
                           DockPanel.Dock="Left"
                           FontSize="15" FontWeight="SemiBold"
                           Foreground="{TEXT}"
                           VerticalAlignment="Center"/>
                <Border DockPanel.Dock="Right"
                        Background="{SURFACE}" CornerRadius="6"
                        BorderBrush="{MUTED}" BorderThickness="1"
                        Width="230">
                    <TextBox x:Name="SearchBox"
                             Background="Transparent" BorderThickness="0"
                             Foreground="{TEXT}" CaretBrush="{ACCENT}"
                             Padding="8,5" FontSize="12"
                             ToolTip="Search by ID or Shaft Function…"/>
                </Border>
            </DockPanel>

            <!-- ── Footer: status + buttons ── -->
            <StackPanel DockPanel.Dock="Bottom" Margin="0,12,0,0">
                <TextBlock x:Name="StatusLabel"
                           FontSize="11" Foreground="{SUBTEXT}"
                           HorizontalAlignment="Center"
                           Margin="0,0,0,8"/>
                <Grid>
                    <Grid.ColumnDefinitions>
                        <ColumnDefinition Width="*"/>
                        <ColumnDefinition Width="12"/>
                        <ColumnDefinition Width="*"/>
                    </Grid.ColumnDefinitions>
                    <Button x:Name="CancelButton" Grid.Column="0"
                            Content="Cancel"
                            Style="{{StaticResource CancelBtnStyle}}"/>
                    <Button x:Name="SaveButton"   Grid.Column="2"
                            Content="Save Changes"
                            Style="{{StaticResource SaveBtnStyle}}"/>
                </Grid>
            </StackPanel>

            <!-- ── List card ── -->
            <!-- RowsPanel margin: 8 L / 14 R (8 padding + 6 scrollbar width)   -->
            <!-- keeps column headers aligned with rows even when bar is visible. -->
            <Border Background="{CARD}" CornerRadius="8">
                <ScrollViewer VerticalScrollBarVisibility="Auto"
                              HorizontalScrollBarVisibility="Disabled">
                    <StackPanel x:Name="RowsPanel" Margin="8,8,14,8"/>
                </ScrollViewer>
            </Border>

        </DockPanel>
    </Border>
</Window>
""".replace("{BG}",      BG) \
   .replace("{CARD}",    CARD) \
   .replace("{SURFACE}", SURFACE) \
   .replace("{MUTED}",   MUTED) \
   .replace("{TEXT}",    TEXT) \
   .replace("{SUBTEXT}", SUBTEXT) \
   .replace("{ACCENT}",  ACCENT) \
   .replace("{{",        "{") \
   .replace("}}",        "}")


# ─── REVIT HELPERS ─────────────────────────────────────────────────────────────

def _eid_int(eid):
    """Read ElementId integer safely across Revit versions (2025+ Int64)."""
    try:
        return eid.Value          # Revit 2025+
    except AttributeError:
        return eid.IntegerValue   # older

def _invalid_eid():
    """Return an invalid ElementId compatible with all Revit versions."""
    try:
        return ElementId.InvalidElementId
    except AttributeError:
        return ElementId(-1)

def _get_param(elem, bip, name_fallback):
    """
    Try BuiltInParameter first (fast, version-stable), fall back to
    LookupParameter by display name for custom / renamed params.
    """
    try:
        p = elem.get_Parameter(bip)
        if p is not None:
            return p
    except Exception:
        pass
    return elem.LookupParameter(name_fallback)


def get_all_levels():
    """All Level elements in the document, sorted by elevation (bottom → top)."""
    return sorted(
        FilteredElementCollector(doc).OfClass(Level).ToElements(),
        key=lambda l: l.Elevation
    )


def collect_shafts():
    """All non-type Shaft Opening elements using the OST_ShaftOpening category."""
    try:
        return list(
            FilteredElementCollector(doc)
            .WherePasses(ElementCategoryFilter(BuiltInCategory.OST_ShaftOpening))
            .WhereElementIsNotElementType()
            .ToElements()
        )
    except Exception:
        return []


def has_shaft_function_param(shafts):
    """
    Return True if the 'Shaft Function' parameter is bound in this document
    (i.e., at least one shaft element exposes the parameter definition).
    """
    for shaft in shafts:
        if shaft.LookupParameter("Shaft Function") is not None:
            return True
    return False


def _level_name_for_id(eid, levels_by_id):
    """Resolve a level ElementId to its display name, or '(Unconnected)'."""
    if eid is None:
        return u"(Unconnected)"
    val = _eid_int(eid)
    if val < 0:
        return u"(Unconnected)"
    return levels_by_id.get(val, u"(Unknown \u2014 ID {0})".format(val))


def _param_offset_display(elem, bip, name_fallback):
    """
    Get an offset parameter's value as a human-readable project-unit string.
    Falls back to the raw internal double if AsValueString() is unavailable.
    """
    p = _get_param(elem, bip, name_fallback)
    if p is None:
        return u"0"
    try:
        vs = p.AsValueString()
        return vs if vs else str(round(p.AsDouble(), 6))
    except Exception:
        return u"0"


def _get_shaft_fields(elem, levels_by_id):
    """
    Extract the six display values for one shaft element.
    Returns: (bc_name, bo_str, tc_name, to_str, sf_val)
    """
    p_bc    = _get_param(elem, BuiltInParameter.WALL_BASE_CONSTRAINT, "Base Constraint")
    bc_name = _level_name_for_id(p_bc.AsElementId() if p_bc else None, levels_by_id)

    bo_str  = _param_offset_display(elem, BuiltInParameter.WALL_BASE_OFFSET, "Base Offset")

    p_tc    = _get_param(elem, BuiltInParameter.WALL_HEIGHT_TYPE,  "Top Constraint")
    tc_name = _level_name_for_id(p_tc.AsElementId() if p_tc else None, levels_by_id)

    to_str  = _param_offset_display(elem, BuiltInParameter.WALL_TOP_OFFSET, "Top Offset")

    p_sf    = elem.LookupParameter("Shaft Function")
    sf_val  = u""
    if p_sf and p_sf.HasValue:
        try:
            sf_val = p_sf.AsString() or u""
        except Exception:
            pass

    return bc_name, bo_str, tc_name, to_str, sf_val


# ─── APPLY CHANGES (module-level, used inside transaction) ─────────────────────

def _apply_row_changes(row_data, elem, levels_by_name, errors):
    """
    Read current control values from *row_data* and write them to the
    Revit element's parameters. Errors are appended to *errors* (mutable list)
    rather than raised, so the transaction continues for other rows.
    """
    eid_tag = u"ID {0}".format(_eid_int(row_data['eid']))

    # ── Level ComboBox → ElementId parameter ──────────────────────────────
    def _set_level_param(bip, fallback_name, combo):
        sel = combo.SelectedItem
        if sel is None:
            return
        lvl_name = str(sel.Content) if hasattr(sel, 'Content') else str(sel)
        p = _get_param(elem, bip, fallback_name)
        if p is None or p.IsReadOnly:
            return
        try:
            if lvl_name == u"(Unconnected)":
                p.Set(_invalid_eid())
            elif lvl_name in levels_by_name:
                p.Set(levels_by_name[lvl_name].Id)
        except Exception as ex:
            errors.append(u"{0} \u2014 {1}: {2}".format(eid_tag, fallback_name, str(ex)[:80]))

    # ── TextBox → Double parameter (project units via SetValueString) ──────
    def _set_offset_param(bip, fallback_name, tb):
        text = tb.Text.strip()
        p = _get_param(elem, bip, fallback_name)
        if p is None or p.IsReadOnly:
            return
        try:
            # SetValueString interprets the string in current project units
            p.SetValueString(text)
        except Exception:
            try:
                # Last resort: treat as a bare number in internal (feet) units
                p.Set(float(text))
            except Exception as ex:
                errors.append(u"{0} \u2014 {1}: {2}".format(eid_tag, fallback_name, str(ex)[:80]))

    # ── TextBox → String parameter ─────────────────────────────────────────
    def _set_string_param(param_name, tb):
        p = elem.LookupParameter(param_name)
        if p is None or p.IsReadOnly:
            return
        try:
            p.Set(tb.Text)
        except Exception as ex:
            errors.append(u"{0} \u2014 {1}: {2}".format(eid_tag, param_name, str(ex)[:80]))

    _set_level_param(BuiltInParameter.WALL_BASE_CONSTRAINT, "Base Constraint", row_data['bc_combo'])
    _set_offset_param(BuiltInParameter.WALL_BASE_OFFSET,    "Base Offset",     row_data['bo_tb'])
    _set_level_param(BuiltInParameter.WALL_HEIGHT_TYPE,  "Top Constraint",  row_data['tc_combo'])
    _set_offset_param(BuiltInParameter.WALL_TOP_OFFSET,     "Top Offset",      row_data['to_tb'])
    _set_string_param("Shaft Function",                                         row_data['sf_tb'])


# ─── UI ROW BUILDERS ───────────────────────────────────────────────────────────

def _make_col_grid():
    """Return a Grid pre-loaded with the shared 11-column layout."""
    g = Controls.Grid()
    for w in COL_SPECS:
        cd = Controls.ColumnDefinition()
        cd.Width = w
        g.ColumnDefinitions.Add(cd)
    return g


def _make_header_row():
    """
    Sticky-looking column header row (first child of RowsPanel, scrolls with
    content — shaft counts are typically small so this is fine in practice).
    """
    grid = _make_col_grid()
    grid.Background = HDR_BRUSH
    grid.Height     = 28
    grid.Margin     = Thickness(0, 0, 0, 0)

    for col_idx, label in zip(CTRL_COLS, HDR_LABELS):
        tb = Controls.TextBlock()
        tb.Text              = label.upper()
        tb.Foreground        = SUBTEXT_BRUSH
        tb.FontSize          = 10
        tb.FontWeight        = System.Windows.FontWeights.SemiBold
        tb.VerticalAlignment = VerticalAlignment.Center
        tb.Padding           = Thickness(5, 0, 0, 0)
        Controls.Grid.SetColumn(tb, col_idx)
        grid.Children.Add(tb)

    return grid


def _make_combo_in_border(items, selected_text):
    """
    Dark-themed ComboBox (transparent bg, white popup items) wrapped in a
    styled Border that provides the visible container.
    Returns (border, combo_box).
    """
    cb = Controls.ComboBox()
    cb.Background               = TRANS_BRUSH
    cb.Foreground               = DARK_BRUSH   # white popup needs dark text
    cb.BorderThickness          = Thickness(0)
    cb.Height                   = 26
    cb.FontSize                 = 12
    cb.Padding                  = Thickness(4, 0, 2, 0)
    cb.VerticalContentAlignment = VerticalAlignment.Center

    sel_idx = 0
    for i, name in enumerate(items):
        cbi = Controls.ComboBoxItem()
        cbi.Content    = name
        cbi.Foreground = DARK_BRUSH
        cbi.Padding    = Thickness(6, 3, 6, 3)
        cb.Items.Add(cbi)
        if name == selected_text:
            sel_idx = i
    cb.SelectedIndex = sel_idx

    border = Controls.Border()
    border.Background      = SURFACE_BRUSH
    border.CornerRadius    = CornerRadius(4)
    border.BorderBrush     = MUTED_BRUSH
    border.BorderThickness = Thickness(1)
    border.Child           = cb
    return border, cb


def _make_textbox_in_border(text):
    """
    Dark-themed TextBox wrapped in a styled Border.
    Returns (border, text_box).
    """
    tb = Controls.TextBox()
    tb.Text                     = text or u""
    tb.Background               = TRANS_BRUSH
    tb.Foreground               = TEXT_BRUSH
    tb.CaretBrush               = ACCENT_BRUSH
    tb.BorderThickness          = Thickness(0)
    tb.Padding                  = Thickness(5, 2, 5, 2)
    tb.FontSize                 = 12
    tb.VerticalAlignment        = VerticalAlignment.Center
    tb.VerticalContentAlignment = VerticalAlignment.Center

    border = Controls.Border()
    border.Background      = SURFACE_BRUSH
    border.CornerRadius    = CornerRadius(4)
    border.BorderBrush     = MUTED_BRUSH
    border.BorderThickness = Thickness(1)
    border.Height          = 26
    border.Child           = tb
    return border, tb


def _make_data_row(elem, row_idx, level_options, levels_by_id):
    """
    Build one editable data row for *elem*.

    Returns (grid, row_data) where row_data carries:
      'eid'        – ElementId for transaction use
      'bc_combo'   – Base Constraint ComboBox
      'bo_tb'      – Base Offset TextBox
      'tc_combo'   – Top Constraint ComboBox
      'to_tb'      – Top Offset TextBox
      'sf_tb'      – Shaft Function TextBox
      'search_key' – lower-cased concatenation for the search bar
    """
    bc_name, bo_str, tc_name, to_str, sf_val = _get_shaft_fields(elem, levels_by_id)
    id_str = str(_eid_int(elem.Id))

    grid = _make_col_grid()
    grid.Margin    = Thickness(0, 2, 0, 2)
    grid.Background = ROW_A_BRUSH if row_idx % 2 == 0 else ROW_B_BRUSH
    grid.MinHeight = 32

    # ── Col 0: ID (read-only, click navigates to element) ─────────────────
    id_block = Controls.TextBlock()
    id_block.Text              = id_str
    id_block.Foreground        = SUBTEXT_BRUSH
    id_block.FontFamily        = Media.FontFamily("Consolas, Courier New")
    id_block.FontSize          = 11
    id_block.VerticalAlignment = VerticalAlignment.Center
    id_block.TextTrimming      = TextTrimming.CharacterEllipsis
    id_block.Padding           = Thickness(5, 0, 2, 0)
    id_block.Cursor            = WinInput.Cursors.Hand
    id_block.ToolTip           = (u"Element ID: {0}\n"
                                  u"Click to navigate Revit to this shaft").format(id_str)

    # Capture ElementId per-row with default-arg closure (IronPython 2.7 safe)
    def _on_id_click(sender, e, eid=elem.Id):
        try:
            sel_ids = List[ElementId]()
            sel_ids.Add(eid)
            uidoc.Selection.SetElementIds(sel_ids)
            uidoc.ShowElements(eid)
        except Exception:
            pass

    id_block.MouseLeftButtonDown += _on_id_click
    Controls.Grid.SetColumn(id_block, 0)
    grid.Children.Add(id_block)

    # ── Col 2: Base Constraint (ComboBox) ──────────────────────────────────
    bc_border, bc_combo = _make_combo_in_border(level_options, bc_name)
    Controls.Grid.SetColumn(bc_border, 2)
    grid.Children.Add(bc_border)

    # ── Col 4: Base Offset (TextBox) ───────────────────────────────────────
    bo_border, bo_tb = _make_textbox_in_border(bo_str)
    Controls.Grid.SetColumn(bo_border, 4)
    grid.Children.Add(bo_border)

    # ── Col 6: Top Constraint (ComboBox) ───────────────────────────────────
    tc_border, tc_combo = _make_combo_in_border(level_options, tc_name)
    Controls.Grid.SetColumn(tc_border, 6)
    grid.Children.Add(tc_border)

    # ── Col 8: Top Offset (TextBox) ────────────────────────────────────────
    to_border, to_tb = _make_textbox_in_border(to_str)
    Controls.Grid.SetColumn(to_border, 8)
    grid.Children.Add(to_border)

    # ── Col 10: Shaft Function (TextBox) ───────────────────────────────────
    sf_border, sf_tb = _make_textbox_in_border(sf_val)
    Controls.Grid.SetColumn(sf_border, 10)
    grid.Children.Add(sf_border)

    # ── Col 12: Delete button ──────────────────────────────────────────────
    del_btn = Controls.Button()
    del_btn.Content         = u"\u2715"   # ✕
    del_btn.Width           = 24
    del_btn.Height          = 24
    del_btn.FontSize        = 11
    del_btn.FontWeight      = System.Windows.FontWeights.Bold
    del_btn.Cursor          = WinInput.Cursors.Hand
    del_btn.BorderThickness = Thickness(0)
    del_btn.ToolTip         = u"Delete this shaft opening (applied on Save)"
    del_btn.VerticalAlignment   = VerticalAlignment.Center
    del_btn.HorizontalAlignment = HorizontalAlignment.Center

    # Red tint background — hover/press via code-behind to avoid x: namespace
    # issues that occur when XamlReader.Parse is called for per-row snippets
    # without a full xmlns:x declaration context.
    DEL_NORMAL_BRUSH = _brush("#3D2020")
    DEL_HOVER_BRUSH  = _brush("#6B2020")
    del_btn.Background = DEL_NORMAL_BRUSH
    del_btn.Foreground = _brush("#FF6B6B")

    def _del_mouse_enter(s, e, b=del_btn, hov=DEL_HOVER_BRUSH):
        b.Background = hov
    def _del_mouse_leave(s, e, b=del_btn, nor=DEL_NORMAL_BRUSH):
        b.Background = nor

    del_btn.MouseEnter += _del_mouse_enter
    del_btn.MouseLeave += _del_mouse_leave

    Controls.Grid.SetColumn(del_btn, 12)
    grid.Children.Add(del_btn)

    # deleted flag — mutated by the button handler
    deleted_flag = [False]

    row_data = {
        'eid':          elem.Id,
        'bc_combo':     bc_combo,
        'bo_tb':        bo_tb,
        'tc_combo':     tc_combo,
        'to_tb':        to_tb,
        'sf_tb':        sf_tb,
        'deleted':      deleted_flag,
        'grid_ref':     grid,
        # Combined search key: id + level names + shaft function value
        'search_key': u" ".join([id_str, bc_name, tc_name, sf_val]).lower(),
    }

    def _on_delete(sender, e, rd=row_data):
        rd['deleted'][0] = True
        rd['grid_ref'].Visibility = Visibility.Collapsed

    del_btn.Click += _on_delete

    return grid, row_data


# ─── BROWSER WINDOW ────────────────────────────────────────────────────────────

def show_shaft_browser(shafts, levels):
    """
    Open the modeless Shaft Opening Editor.
    Uses Show() + Dispatcher.PushFrame() so Revit stays interactive
    while the window is open.
    """
    window     = XamlReader.Parse(BROWSER_XAML)
    title_lbl  = window.FindName("TitleLabel")
    search_box = window.FindName("SearchBox")
    status_lbl = window.FindName("StatusLabel")
    cancel_btn = window.FindName("CancelButton")
    save_btn   = window.FindName("SaveButton")
    rows_panel = window.FindName("RowsPanel")

    # Mutable state — no 'nonlocal' in IronPython 2.7
    frame = [Threading.DispatcherFrame()]

    # ── Level data structures ──────────────────────────────────────────────
    # "(Unconnected)" is the first option so it appears at the top of each
    # level ComboBox; it maps to an invalid ElementId when saved.
    level_options  = [u"(Unconnected)"] + [l.Name for l in levels]
    levels_by_name = {l.Name: l          for l in levels}
    levels_by_id   = {_eid_int(l.Id): l.Name for l in levels}

    # ── Header labels ──────────────────────────────────────────────────────
    title_lbl.Text  = (u"Shaft Opening Editor  \u00b7  "
                       u"{0} shaft(s) found".format(len(shafts)))
    status_lbl.Text = (u"Click an ID to select & navigate  \u00b7  "
                       u"Edit cells directly  \u00b7  "
                       u"\u2715 to mark for deletion  \u00b7  "
                       u"Save Changes to commit all edits in one transaction")

    # ── Build column headers + divider (both scroll with content) ─────────
    rows_panel.Children.Add(_make_header_row())

    divider = Controls.Border()
    divider.Height     = 1
    divider.Background = MUTED_BRUSH
    divider.Opacity    = 0.4
    divider.Margin     = Thickness(0, 4, 0, 4)
    rows_panel.Children.Add(divider)

    # ── Build one editable row per shaft ───────────────────────────────────
    all_row_data  = []   # list of dicts (controls + metadata)
    all_row_grids = []   # parallel list of Grid widgets (for search visibility)

    for i, shaft in enumerate(shafts):
        grid, row_data = _make_data_row(shaft, i, level_options, levels_by_id)
        rows_panel.Children.Add(grid)
        all_row_data.append(row_data)
        all_row_grids.append(grid)

    # ── Search handler ─────────────────────────────────────────────────────
    def on_search_changed(s, e):
        query = search_box.Text.strip().lower()
        for rd, rg in zip(all_row_data, all_row_grids):
            visible = (not query) or (query in rd['search_key'])
            rg.Visibility = Visibility.Visible if visible else Visibility.Collapsed

    # ── Save handler ───────────────────────────────────────────────────────
    def on_save(s, e):
        errors = []
        t = Transaction(doc, u"Edit Shaft Opening Properties")
        try:
            t.Start()
            for rd in all_row_data:
                elem = doc.GetElement(rd['eid'])
                if elem is None:
                    continue
                if rd['deleted'][0]:
                    try:
                        doc.Delete(rd['eid'])
                    except Exception as del_ex:
                        errors.append(u"ID {0} \u2014 delete failed: {1}".format(
                            _eid_int(rd['eid']), str(del_ex)[:80]))
                else:
                    _apply_row_changes(rd, elem, levels_by_name, errors)
            t.Commit()
        except Exception as tx_ex:
            try:
                t.RollBack()
            except Exception:
                pass
            errors.insert(0, u"Transaction failed: " + str(tx_ex)[:100])

        frame[0].Continue = False
        window.Close()

        if errors:
            TaskDialog.Show(
                u"Shaft Editor \u2014 Warnings",
                u"Some changes could not be applied:\n\n"
                + u"\n".join(errors[:20])
            )

    # ── Cancel handler ─────────────────────────────────────────────────────
    def on_cancel(s, e):
        frame[0].Continue = False
        window.Close()

    # ── Window closing (X / Alt-F4) ────────────────────────────────────────
    def on_closing(s, e):
        frame[0].Continue = False

    # ── Wire events ────────────────────────────────────────────────────────
    search_box.TextChanged += on_search_changed
    save_btn.Click         += on_save
    cancel_btn.Click       += on_cancel
    window.Closing         += on_closing

    # Non-blocking: Show() + PushFrame keeps the Revit main thread alive
    # so the user can pan/zoom while editing.
    window.Show()
    Threading.Dispatcher.PushFrame(frame[0])


# ─── MAIN ──────────────────────────────────────────────────────────────────────

shafts = collect_shafts()

if not shafts:
    TaskDialog.Show(
        u"Shaft Opening Editor",
        u"No Shaft Openings were found in the current document."
    )
    script.exit()

if not has_shaft_function_param(shafts):
    TaskDialog.Show(
        u"Shaft Opening Editor",
        u'The parameter "Shaft Function" was not found on any Shaft Opening '
        u'in this document.\n\n'
        u'Please add it as a Shared Parameter bound to the Openings category '
        u'via Manage \u2192 Project Parameters, then re-run this tool.'
    )
    script.exit()

levels = get_all_levels()
show_shaft_browser(shafts, levels)
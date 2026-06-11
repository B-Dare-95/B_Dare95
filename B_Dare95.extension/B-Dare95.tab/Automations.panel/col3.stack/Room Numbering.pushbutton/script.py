# -*- coding: utf-8 -*-
__title__   = "Renumber Rooms\n[Grid-Based]"
__author__  = "B-Dare95"
__version__ = "Version 2.0"
__doc__     = """Version = 2.0
Date    = 09.06.2026
_____________________________________________________________________
Description:
Renumbers a chosen Room parameter using grid-line intersections and
a nearest-to-corner reference system.

Workflow:
  1. Collects all Grid Lines and computes every pairwise 2-D
     intersection.
  2. Identifies the 4 outermost intersection points (TL / TR / BL /
     BR corners of the intersection bounding box).
  3. The user picks ONE of the four corners as the reference point
     via the 2x2 tile grid in the UI.
  4. Rooms are grouped by Level (bottom level first).
  5. Within each Level, rooms are sorted by Euclidean distance from
     the reference corner — nearest room is numbered first.
  6. The counter RESETS to Start Number for every new Level.
_____________________________________________________________________
How-to:
-> Select a Room Parameter from the left panel
-> Click the corner tile that represents your starting reference
-> Set Prefix, Suffix, and Start Number
-> Click RUN
_____________________________________________________________________
Last update:
- [09.06.2026] - 2.0 RELEASE (per-level, nearest-to-corner)
_____________________________________________________________________
Author: B-Dare95"""

# ╦╔╦╗╔═╗╔═╗╦═╗╔╦╗╔═╗
# ║║║║╠═╝║ ║╠╦╝ ║ ╚═╗
# ╩╩ ╩╩  ╚═╝╩╚═ ╩ ╚═╝
# ==================================================
import math

from Autodesk.Revit.DB import (
    BuiltInCategory,
    FilteredElementCollector,
    Grid,
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

# ╔╦╗╦═╗╔═╗╔╗╔╔═╗╔═╗╔═╗╔╦╗╦╔═╗╔╗╔
#  ║ ╠╦╝╠═╣║║║╚═╗╠═╣║   ║ ║║ ║║║║
#  ╩ ╩╚═╩ ╩╝╚╝╚═╝╩ ╩╚═╝ ╩ ╩╚═╝╝╚╝
# ==================================================
try:
    from Snippets._context_manager import ef_Transaction
    _HAS_EF = True
except Exception:
    _HAS_EF = False


class _SimpleTx(object):
    """Minimal Transaction context-manager fallback."""

    def __init__(self, doc, name):
        self._t = Transaction(doc, name)

    def __enter__(self):
        self._t.Start()
        return self._t

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._t.HasStarted():
            self._t.RollBack() if exc_type else self._t.Commit()
        return False


def _make_tx(doc, name):
    return ef_Transaction(doc, name, debug=True) if _HAS_EF else _SimpleTx(doc, name)


# ╔═╗╦═╗╦╔╦╗  ╔═╗╔╗╔╔═╗╦  ╦╔═╗╦╔═╗
# ║ ╦╠╦╝║ ║║  ╠═╣║║║╠═╣║  ╚╗╔╝╚═╗║╚═╗
# ╚═╝╩╚═╩═╩╝  ╩ ╩╝╚╝╩ ╩╩═╝ ╚╝ ╚═╝╩╚═╝
# ==================================================

_DEDUP_TOL = 0.01       # ft — tolerance for merging near-identical points


def _intersect_2d(x1, y1, dx1, dy1, x2, y2, dx2, dy2):
    """
    Analytical 2-D intersection of two infinite lines.
    Line 1 : (x1,y1) + t*(dx1,dy1)
    Line 2 : (x2,y2) + s*(dx2,dy2)
    Returns (ix, iy) or None when lines are parallel.
    Pure-math approach — avoids IronPython clr.Reference out-param issues.
    """
    cross = dx1 * dy2 - dy1 * dx2
    if abs(cross) < 1e-9:
        return None
    t = ((x2 - x1) * dy2 - (y2 - y1) * dx2) / cross
    return (x1 + t * dx1, y1 + t * dy1)


def analyse_grids(doc):
    """
    Collect Grid Lines, compute all pairwise intersections, and identify
    the four outermost corner points (TL / TR / BL / BR).

    Each corner is the actual intersection point nearest to the
    corresponding corner of the overall intersection bounding box.

    Returns dict:
        grid_count    : int
        intersections : list of (x, y)
        corners       : {'TL': (x,y), 'TR': (x,y), 'BL': (x,y), 'BR': (x,y)}

    Returns None when fewer than 2 grids exist or no intersections found.
    """
    grids = list(FilteredElementCollector(doc).OfClass(Grid).ToElements())
    if len(grids) < 2:
        return None

    # ── Normalised 2-D line representations ─────────────────────────────
    lines = []
    for g in grids:
        try:
            crv = g.Curve
            s   = crv.GetEndPoint(0)
            e   = crv.GetEndPoint(1)
            dx  = e.X - s.X
            dy  = e.Y - s.Y
            ln  = math.sqrt(dx * dx + dy * dy)
            if ln < 1e-9:
                continue
            lines.append((s.X, s.Y, dx / ln, dy / ln))
        except Exception:
            pass

    if len(lines) < 2:
        return None

    # ── Pairwise intersections ───────────────────────────────────────────
    # Each line tuple has 4 elements; concatenate two → 8-element tuple → unpack
    raw_pts = []
    for i in range(len(lines)):
        for j in range(i + 1, len(lines)):
            pt = _intersect_2d(*(lines[i] + lines[j]))
            if pt is not None:
                raw_pts.append(pt)

    if not raw_pts:
        return None

    # ── Deduplicate within _DEDUP_TOL ────────────────────────────────────
    unique_pts = []
    for p in raw_pts:
        is_dup = False
        for u in unique_pts:
            if abs(p[0] - u[0]) < _DEDUP_TOL and abs(p[1] - u[1]) < _DEDUP_TOL:
                is_dup = True
                break
        if not is_dup:
            unique_pts.append(p)

    if not unique_pts:
        return None

    # ── Bounding box of all intersection points ──────────────────────────
    min_x = min(p[0] for p in unique_pts)
    max_x = max(p[0] for p in unique_pts)
    min_y = min(p[1] for p in unique_pts)
    max_y = max(p[1] for p in unique_pts)

    def _nearest(tx, ty):
        """Return the intersection point closest to (tx, ty)."""
        return min(unique_pts, key=lambda p: (p[0] - tx) ** 2 + (p[1] - ty) ** 2)

    # ── Four corner points ───────────────────────────────────────────────
    corners = {
        'TL': _nearest(min_x, max_y),   # top-left
        'TR': _nearest(max_x, max_y),   # top-right
        'BL': _nearest(min_x, min_y),   # bottom-left
        'BR': _nearest(max_x, min_y),   # bottom-right
    }

    return {
        'grid_count':    len(grids),
        'intersections': unique_pts,
        'corners':       corners,
    }


# ╦═╗╔═╗╔═╗╔╦╗╔═╗  ╦ ╦╔╦╗╦╦  ╦╔╦╗╦╔═╗╔═╗
# ╠╦╝║ ║║ ║║║║╚═╗  ║ ║ ║ ║║  ║ ║ ║║╣ ╚═╗
# ╩╚═╚═╝╚═╝╩ ╩╚═╝  ╚═╝ ╩ ╩╩═╝╩ ╩ ╩╚═╝╚═╝
# ==================================================

def get_placed_rooms(doc):
    """Return all placed rooms (Area > 0, Location is not None)."""
    all_rooms = (
        FilteredElementCollector(doc)
        .OfCategory(BuiltInCategory.OST_Rooms)
        .WhereElementIsNotElementType()
        .ToElements()
    )
    placed = []
    for r in all_rooms:
        try:
            if r.Area > 0 and r.Location is not None:
                placed.append(r)
        except Exception:
            pass
    return placed


def get_room_xy(room):
    """Return (X, Y) of a room's LocationPoint, or None."""
    try:
        loc = room.Location
        if loc and hasattr(loc, 'Point') and loc.Point:
            return (loc.Point.X, loc.Point.Y)
    except Exception:
        pass
    return None


def collect_room_writable_params(rooms):
    """Return a sorted list of writable String-type param names across all rooms."""
    seen   = set()
    result = []
    for room in rooms:
        try:
            for param in room.Parameters:
                n = param.Definition.Name
                if (n not in seen
                        and not param.IsReadOnly
                        and param.StorageType == StorageType.String):
                    seen.add(n)
                    result.append(n)
        except Exception:
            pass
    result.sort()
    return result


def group_rooms_by_level(rooms, doc):
    """
    Partition placed rooms by their Level element, sorted by
    elevation ascending (lowest floor first).

    Returns list of dicts: [{'name': str, 'elevation': float, 'rooms': list}]
    Rooms with no resolvable Level go into a trailing '(No Level)' group.
    """
    groups   = {}
    no_level = []

    for room in rooms:
        try:
            lvl_id = room.LevelId
            if lvl_id is None:
                no_level.append(room)
                continue
            lvl = doc.GetElement(lvl_id)
            if lvl is None:
                no_level.append(room)
                continue

            # ElementId as dict key — use integer value for reliability
            try:
                key = int(lvl_id.Value)
            except AttributeError:
                key = int(lvl_id.IntegerValue)

            if key not in groups:
                groups[key] = {
                    'name':      lvl.Name,
                    'elevation': lvl.Elevation,
                    'rooms':     [],
                }
            groups[key]['rooms'].append(room)
        except Exception:
            no_level.append(room)

    sorted_groups = sorted(groups.values(), key=lambda g: g['elevation'])

    if no_level:
        sorted_groups.append({
            'name':      '(No Level)',
            'elevation': 1e18,
            'rooms':     no_level,
        })

    return sorted_groups


def sort_by_distance(rooms, ref_pt):
    """
    Sort *rooms* by Euclidean distance from *ref_pt* (nearest first).
    Rooms with no locatable centre sort to the end.
    """
    ref_x, ref_y = ref_pt[0], ref_pt[1]

    def _dist(room):
        c = get_room_xy(room)
        if c is None:
            return 1e18
        return math.sqrt((c[0] - ref_x) ** 2 + (c[1] - ref_y) ** 2)

    return sorted(rooms, key=_dist)


# ╔═╗╦  ╦ ╦╦   ╦ ╦╦
# ║ ╦║  ║ ║║   ║ ║║
# ╚═╝╩═╝╚═╝╩   ╚═╝╩
# ==================================================

# Corner metadata: key → (arrow glyph, display label, XAML button name, coord name)
_CORNER_META = {
    'TL': (u'\u2196', 'TOP-LEFT',    'UI_corner_tl', 'UI_coord_tl'),
    'TR': (u'\u2197', 'TOP-RIGHT',   'UI_corner_tr', 'UI_coord_tr'),
    'BL': (u'\u2199', 'BOT-LEFT',    'UI_corner_bl', 'UI_coord_bl'),
    'BR': (u'\u2198', 'BOT-RIGHT',   'UI_corner_br', 'UI_coord_br'),
}

XAML_STR = """
<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Renumber Rooms [Grid-Based]"
    Width="760" Height="600"
    WindowStartupLocation="CenterScreen"
    ResizeMode="NoResize"
    Background="#1E1E2E"
    FontFamily="Segoe UI">

    <Window.Resources>

        <!-- ListBoxItem -->
        <Style x:Key="S_LBI" TargetType="ListBoxItem">
            <Setter Property="Foreground"      Value="#CDD6F4"/>
            <Setter Property="Background"      Value="Transparent"/>
            <Setter Property="Padding"         Value="8,5"/>
            <Setter Property="FontSize"        Value="12"/>
            <Setter Property="Cursor"          Value="Hand"/>
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

        <!-- ListBox -->
        <Style TargetType="ListBox">
            <Setter Property="Background"       Value="#313244"/>
            <Setter Property="BorderBrush"      Value="#45475A"/>
            <Setter Property="BorderThickness"  Value="1"/>
            <Setter Property="ItemContainerStyle" Value="{StaticResource S_LBI}"/>
            <Setter Property="ScrollViewer.HorizontalScrollBarVisibility" Value="Disabled"/>
            <Setter Property="Padding"          Value="0"/>
        </Style>

        <!-- TextBox -->
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

        <!-- Panel section header -->
        <Style x:Key="S_PanelHeader" TargetType="TextBlock">
            <Setter Property="Foreground"  Value="#A6ADC8"/>
            <Setter Property="FontSize"    Value="11"/>
            <Setter Property="FontWeight"  Value="SemiBold"/>
            <Setter Property="Margin"      Value="0,0,0,7"/>
        </Style>

        <!-- Field label (above an input) -->
        <Style x:Key="S_FieldLabel" TargetType="TextBlock">
            <Setter Property="Foreground" Value="#A6ADC8"/>
            <Setter Property="FontSize"   Value="11"/>
            <Setter Property="Margin"     Value="0,0,0,4"/>
        </Style>

        <!-- Corner tile RadioButton (2x2 grid) -->
        <Style x:Key="S_CornerBtn" TargetType="RadioButton">
            <Setter Property="Background"      Value="#313244"/>
            <Setter Property="Foreground"      Value="#A6ADC8"/>
            <Setter Property="BorderBrush"     Value="#45475A"/>
            <Setter Property="BorderThickness" Value="1"/>
            <Setter Property="Cursor"          Value="Hand"/>
            <Setter Property="HorizontalContentAlignment" Value="Center"/>
            <Setter Property="VerticalContentAlignment"   Value="Center"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="RadioButton">
                        <Border x:Name="Bd"
                                Background="{TemplateBinding Background}"
                                BorderBrush="{TemplateBinding BorderBrush}"
                                BorderThickness="{TemplateBinding BorderThickness}"
                                CornerRadius="8">
                            <ContentPresenter
                                HorizontalAlignment="{TemplateBinding HorizontalContentAlignment}"
                                VerticalAlignment="{TemplateBinding VerticalContentAlignment}"
                                Margin="10,8"/>
                        </Border>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
            <Style.Triggers>
                <Trigger Property="IsChecked" Value="True">
                    <Setter Property="Background"  Value="#F0A500"/>
                    <Setter Property="Foreground"  Value="#1E1E2E"/>
                    <Setter Property="BorderBrush" Value="#F0A500"/>
                </Trigger>
                <Trigger Property="IsMouseOver" Value="True">
                    <Setter Property="Background" Value="#45475A"/>
                </Trigger>
            </Style.Triggers>
        </Style>

        <!-- RUN button -->
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
                                CornerRadius="6" Padding="{TemplateBinding Padding}">
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

        <!-- CANCEL button -->
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

    </Window.Resources>

    <!-- ═══════════════════════ ROOT GRID ════════════════════════════ -->
    <Grid Margin="18">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>   <!-- title bar         -->
            <RowDefinition Height="*"/>      <!-- main panels       -->
            <RowDefinition Height="Auto"/>   <!-- divider           -->
            <RowDefinition Height="Auto"/>   <!-- button row        -->
        </Grid.RowDefinitions>

        <!-- ══ TITLE ═══════════════════════════════════════════════════ -->
        <Grid Grid.Row="0" Margin="0,0,0,14">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="Auto"/>
            </Grid.ColumnDefinitions>
            <StackPanel Grid.Column="0">
                <TextBlock Text="RENUMBER ROOMS  ·  NEAREST-TO-CORNER"
                           Foreground="#F0A500" FontSize="15" FontWeight="Bold"/>
                <TextBlock Text="Per-level numbering  ·  sorted by distance from the selected grid corner."
                           Foreground="#585B70" FontSize="11" Margin="0,3,0,0"/>
            </StackPanel>
            <TextBlock x:Name="UI_version" Grid.Column="1"
                       Foreground="#585B70" FontSize="11"
                       VerticalAlignment="Top"/>
        </Grid>

        <!-- ══ MAIN PANELS ══════════════════════════════════════════════ -->
        <Grid Grid.Row="1">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="14"/>
                <ColumnDefinition Width="*"/>
            </Grid.ColumnDefinitions>

            <!-- ─────────────────────────────────────────────────────── -->
            <!-- LEFT : Room parameter picker                            -->
            <!-- ─────────────────────────────────────────────────────── -->
            <Border Grid.Column="0" Background="#2A2A3C" CornerRadius="8" Padding="12">
                <Grid>
                    <Grid.RowDefinitions>
                        <RowDefinition Height="Auto"/>   <!-- header      -->
                        <RowDefinition Height="*"/>      <!-- param list  -->
                        <RowDefinition Height="Auto"/>   <!-- hint        -->
                    </Grid.RowDefinitions>

                    <TextBlock Grid.Row="0"
                               Text="ROOM PARAMETER  (writable · text only)"
                               Style="{StaticResource S_PanelHeader}"/>

                    <ListBox x:Name="UI_param_list"
                             Grid.Row="1" SelectionMode="Single"/>

                    <TextBlock x:Name="UI_param_hint" Grid.Row="2"
                               Foreground="#585B70" FontSize="11"
                               Margin="0,6,0,0" TextWrapping="Wrap"/>
                </Grid>
            </Border>

            <!-- ─────────────────────────────────────────────────────── -->
            <!-- RIGHT : Corner picker + Settings                        -->
            <!-- ─────────────────────────────────────────────────────── -->
            <Border Grid.Column="2" Background="#2A2A3C" CornerRadius="8" Padding="12">
                <Grid>
                    <Grid.RowDefinitions>
                        <RowDefinition Height="Auto"/>   <!-- "REFERENCE CORNER" header -->
                        <RowDefinition Height="*"/>      <!-- 2x2 tile grid             -->
                        <RowDefinition Height="Auto"/>   <!-- status line               -->
                        <RowDefinition Height="10"/>     <!-- spacer                    -->
                        <RowDefinition Height="Auto"/>   <!-- "SETTINGS" header         -->
                        <RowDefinition Height="Auto"/>   <!-- Prefix / Suffix           -->
                        <RowDefinition Height="8"/>      <!-- gap                       -->
                        <RowDefinition Height="Auto"/>   <!-- Start Number              -->
                    </Grid.RowDefinitions>

                    <!-- ── Section header ────────────────────────── -->
                    <TextBlock Grid.Row="0"
                               Text="REFERENCE CORNER"
                               Style="{StaticResource S_PanelHeader}"/>

                    <!-- ── 2 x 2 corner tile grid ─────────────────── -->
                    <Grid Grid.Row="1">
                        <Grid.ColumnDefinitions>
                            <ColumnDefinition Width="*"/>
                            <ColumnDefinition Width="6"/>
                            <ColumnDefinition Width="*"/>
                        </Grid.ColumnDefinitions>
                        <Grid.RowDefinitions>
                            <RowDefinition Height="*" MinHeight="82"/>
                            <RowDefinition Height="6"/>
                            <RowDefinition Height="*" MinHeight="82"/>
                        </Grid.RowDefinitions>

                        <!-- TOP-LEFT tile -->
                        <RadioButton x:Name="UI_corner_tl"
                                     Grid.Row="0" Grid.Column="0"
                                     GroupName="CornerGroup"
                                     Style="{StaticResource S_CornerBtn}">
                            <StackPanel HorizontalAlignment="Center">
                                <TextBlock x:Name="UI_arrow_tl"
                                           Text="&#x2196;"
                                           FontSize="22" FontWeight="Bold"
                                           HorizontalAlignment="Center"/>
                                <TextBlock Text="TOP-LEFT"
                                           FontSize="10" FontWeight="SemiBold"
                                           HorizontalAlignment="Center"
                                           Margin="0,2,0,0"/>
                                <TextBlock x:Name="UI_coord_tl"
                                           FontSize="9"
                                           HorizontalAlignment="Center"
                                           Margin="0,3,0,0"/>
                            </StackPanel>
                        </RadioButton>

                        <!-- TOP-RIGHT tile -->
                        <RadioButton x:Name="UI_corner_tr"
                                     Grid.Row="0" Grid.Column="2"
                                     GroupName="CornerGroup"
                                     Style="{StaticResource S_CornerBtn}">
                            <StackPanel HorizontalAlignment="Center">
                                <TextBlock x:Name="UI_arrow_tr"
                                           Text="&#x2197;"
                                           FontSize="22" FontWeight="Bold"
                                           HorizontalAlignment="Center"/>
                                <TextBlock Text="TOP-RIGHT"
                                           FontSize="10" FontWeight="SemiBold"
                                           HorizontalAlignment="Center"
                                           Margin="0,2,0,0"/>
                                <TextBlock x:Name="UI_coord_tr"
                                           FontSize="9"
                                           HorizontalAlignment="Center"
                                           Margin="0,3,0,0"/>
                            </StackPanel>
                        </RadioButton>

                        <!-- BOT-LEFT tile -->
                        <RadioButton x:Name="UI_corner_bl"
                                     Grid.Row="2" Grid.Column="0"
                                     GroupName="CornerGroup"
                                     Style="{StaticResource S_CornerBtn}">
                            <StackPanel HorizontalAlignment="Center">
                                <TextBlock x:Name="UI_arrow_bl"
                                           Text="&#x2199;"
                                           FontSize="22" FontWeight="Bold"
                                           HorizontalAlignment="Center"/>
                                <TextBlock Text="BOT-LEFT"
                                           FontSize="10" FontWeight="SemiBold"
                                           HorizontalAlignment="Center"
                                           Margin="0,2,0,0"/>
                                <TextBlock x:Name="UI_coord_bl"
                                           FontSize="9"
                                           HorizontalAlignment="Center"
                                           Margin="0,3,0,0"/>
                            </StackPanel>
                        </RadioButton>

                        <!-- BOT-RIGHT tile -->
                        <RadioButton x:Name="UI_corner_br"
                                     Grid.Row="2" Grid.Column="2"
                                     GroupName="CornerGroup"
                                     Style="{StaticResource S_CornerBtn}">
                            <StackPanel HorizontalAlignment="Center">
                                <TextBlock x:Name="UI_arrow_br"
                                           Text="&#x2198;"
                                           FontSize="22" FontWeight="Bold"
                                           HorizontalAlignment="Center"/>
                                <TextBlock Text="BOT-RIGHT"
                                           FontSize="10" FontWeight="SemiBold"
                                           HorizontalAlignment="Center"
                                           Margin="0,2,0,0"/>
                                <TextBlock x:Name="UI_coord_br"
                                           FontSize="9"
                                           HorizontalAlignment="Center"
                                           Margin="0,3,0,0"/>
                            </StackPanel>
                        </RadioButton>

                    </Grid>
                    <!-- end 2x2 tile grid -->

                    <!-- ── Status line ────────────────────────────── -->
                    <TextBlock x:Name="UI_status" Grid.Row="2"
                               Foreground="#585B70" FontSize="11"
                               HorizontalAlignment="Center"
                               Margin="0,6,0,0"/>

                    <!-- ── Settings header ────────────────────────── -->
                    <TextBlock Grid.Row="4"
                               Text="SETTINGS"
                               Style="{StaticResource S_PanelHeader}"/>

                    <!-- ── Prefix / Suffix ────────────────────────── -->
                    <Grid Grid.Row="5">
                        <Grid.ColumnDefinitions>
                            <ColumnDefinition Width="*"/>
                            <ColumnDefinition Width="8"/>
                            <ColumnDefinition Width="*"/>
                        </Grid.ColumnDefinitions>
                        <StackPanel Grid.Column="0">
                            <TextBlock Text="Prefix  (optional)"
                                       Style="{StaticResource S_FieldLabel}"/>
                            <TextBox x:Name="UI_prefix"/>
                        </StackPanel>
                        <StackPanel Grid.Column="2">
                            <TextBlock Text="Suffix  (optional)"
                                       Style="{StaticResource S_FieldLabel}"/>
                            <TextBox x:Name="UI_suffix"/>
                        </StackPanel>
                    </Grid>

                    <!-- ── Start Number ───────────────────────────── -->
                    <StackPanel Grid.Row="7">
                        <TextBlock Text="Start Number  (resets each level)"
                                   Style="{StaticResource S_FieldLabel}"/>
                        <TextBox x:Name="UI_start" Text="1"/>
                    </StackPanel>

                </Grid>
            </Border>
            <!-- end right panel -->
        </Grid>

        <!-- ══ DIVIDER ═══════════════════════════════════════════════════ -->
        <Border Grid.Row="2" Height="1" Background="#313244" Margin="0,12,0,12"/>

        <!-- ══ BUTTONS ══════════════════════════════════════════════════ -->
        <Grid Grid.Row="3">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="10"/>
                <ColumnDefinition Width="*"/>
            </Grid.ColumnDefinitions>
            <Button x:Name="UI_cancel" Grid.Column="0"
                    Content="CANCEL" Style="{StaticResource S_CancelBtn}"/>
            <Button x:Name="UI_run"    Grid.Column="2"
                    Content="RUN"    Style="{StaticResource S_RunBtn}"/>
        </Grid>
    </Grid>
</Window>
"""


# ╔═╗╦  ╦ ╦╦   ╔═╗╦  ╔═╗╔═╗╔═╗
# ║ ╦║  ║ ║║   ║  ║  ╠═╣╚═╗╚═╗
# ╚═╝╩═╝╚═╝╩   ╚═╝╩═╝╩ ╩╚═╝╚═╝
# ==================================================

# Mapping: corner key → RadioButton name in XAML
_CORNER_BTN_NAMES = {
    'TL': 'UI_corner_tl',
    'TR': 'UI_corner_tr',
    'BL': 'UI_corner_bl',
    'BR': 'UI_corner_br',
}
_CORNER_COORD_NAMES = {
    'TL': 'UI_coord_tl',
    'TR': 'UI_coord_tr',
    'BL': 'UI_coord_bl',
    'BR': 'UI_coord_br',
}


class RoomGridUI(object):
    """
    WPF dialog.

    Left  : parameter ListBox
    Right : 2x2 corner-tile RadioButton grid  +  Prefix / Suffix / Start

    All results stored in mutable list containers (no nonlocal — IronPython 2.7).
    """

    def __init__(self, params, grid_info, level_groups):
        self._params       = params
        self._grid_info    = grid_info
        self._level_groups = level_groups

        # ── Output state ────────────────────────────────────────────
        self.confirmed  = [False]
        self.param_name = [None]
        self.corner_key = [None]     # 'TL' / 'TR' / 'BL' / 'BR'
        self.prefix     = ['']
        self.suffix     = ['']
        self.start      = [1]

        # ── Build window ─────────────────────────────────────────────
        self._win = XamlReader.Parse(XAML_STR)

        # ── Resolve controls ─────────────────────────────────────────
        self._param_list  = self._win.FindName('UI_param_list')
        self._param_hint  = self._win.FindName('UI_param_hint')
        self._prefix_tb   = self._win.FindName('UI_prefix')
        self._suffix_tb   = self._win.FindName('UI_suffix')
        self._start_tb    = self._win.FindName('UI_start')
        self._btn_run     = self._win.FindName('UI_run')
        self._btn_cancel  = self._win.FindName('UI_cancel')
        self._status_lbl  = self._win.FindName('UI_status')
        self._ver_lbl     = self._win.FindName('UI_version')

        # Corner RadioButtons
        self._corner_btns = {
            k: self._win.FindName(v)
            for k, v in _CORNER_BTN_NAMES.items()
        }

        # ── Populate data ─────────────────────────────────────────────
        if self._ver_lbl:
            self._ver_lbl.Text = __version__

        self._fill_param_list()
        self._fill_corner_coords()
        self._fill_status()

        # ── Wire events ───────────────────────────────────────────────
        self._param_list.SelectionChanged += self._on_param_selected
        self._btn_run.Click               += self._on_run
        self._btn_cancel.Click            += self._on_cancel

        self._win.ShowDialog()

    # ── Populate helpers ──────────────────────────────────────────────

    def _fill_param_list(self):
        self._param_list.Items.Clear()
        if self._params:
            for p in self._params:
                self._param_list.Items.Add(p)
        else:
            self._param_list.Items.Add(
                u'\u2014 no writable text parameters found \u2014'
            )

    def _fill_corner_coords(self):
        """Write 'X=…  Y=…' into each tile's coordinate TextBlock."""
        corners = self._grid_info['corners']
        for key, coord_name in _CORNER_COORD_NAMES.items():
            lbl = self._win.FindName(coord_name)
            if lbl and key in corners:
                pt = corners[key]
                lbl.Text = 'X={:.2f}   Y={:.2f}'.format(pt[0], pt[1])

    def _fill_status(self):
        """Bottom status: '3 levels  ·  24 rooms'"""
        n_levels = len(self._level_groups)
        n_rooms  = sum(len(g['rooms']) for g in self._level_groups)
        if self._status_lbl:
            self._status_lbl.Text = (
                u'{} level{}   \u00b7   {} room{}'.format(
                    n_levels, 's' if n_levels != 1 else '',
                    n_rooms,  's' if n_rooms  != 1 else '',
                )
            )

    # ── Event handlers ────────────────────────────────────────────────

    def _on_param_selected(self, sender, e):
        p = self._param_list.SelectedItem
        if p and not p.startswith(u'\u2014'):
            if self._param_hint:
                self._param_hint.Text = u'\u2714  {}'.format(p)

    def _on_run(self, sender, e):
        # ── Validate parameter ────────────────────────────────────────
        param = self._param_list.SelectedItem
        if not param or param.startswith(u'\u2014'):
            forms.alert('Please select a Room Parameter.', title=__title__)
            return

        # ── Validate corner selection ─────────────────────────────────
        chosen_key = None
        for key, btn in self._corner_btns.items():
            if btn is not None and btn.IsChecked == True:   # noqa: E712  Nullable<bool>
                chosen_key = key
                break
        if chosen_key is None:
            forms.alert(
                'Please select a Reference Corner\n'
                '(click one of the four arrow tiles).',
                title=__title__
            )
            return

        # ── Validate start number ─────────────────────────────────────
        try:
            start = int(self._start_tb.Text.strip())
        except (ValueError, AttributeError):
            forms.alert(
                'Start Number must be a whole number  (e.g. 1).',
                title=__title__
            )
            return

        # ── Commit ────────────────────────────────────────────────────
        self.confirmed[0]  = True
        self.param_name[0] = param
        self.corner_key[0] = chosen_key
        self.prefix[0]     = self._prefix_tb.Text or ''
        self.suffix[0]     = self._suffix_tb.Text or ''
        self.start[0]      = start
        self._win.Close()

    def _on_cancel(self, sender, e):
        self._win.Close()


# ╔╦╗╔═╗╦╔╗╔  ╔═╗═╗ ╦╔═╗╔═╗╦ ╦╔╦╗╦╔═╗╔╗╔
# ║║║╠═╣║║║║  ║╣ ╔╩╦╝║╣ ║  ║ ║ ║ ║║ ║║║║
# ╩ ╩╩ ╩╩╝╚╝  ╚═╝╩ ╚═╚═╝╚═╝╚═╝ ╩ ╩╚═╝╝╚╝
# ==================================================

# ── Step 1: Grid analysis ─────────────────────────────────────────────────
grid_info = analyse_grids(doc)

if grid_info is None:
    forms.alert(
        'Insufficient Grid Lines detected.\n\n'
        'This script requires at least 2 non-parallel Grid Lines to\n'
        'compute intersection points.  Please add grids and try again.',
        title=__title__,
        exitscript=True,
    )

# ── Step 2: Collect placed rooms ──────────────────────────────────────────
placed_rooms = get_placed_rooms(doc)

if not placed_rooms:
    forms.alert(
        'No placed Rooms found in the project.\n'
        'Please place Rooms before running this script.',
        title=__title__,
        exitscript=True,
    )

# ── Step 3: Writable parameters + level grouping ──────────────────────────
room_params  = collect_room_writable_params(placed_rooms)
level_groups = group_rooms_by_level(placed_rooms, doc)

if not level_groups:
    forms.alert(
        'Could not resolve any Level for the placed Rooms.',
        title=__title__,
        exitscript=True,
    )

# ── Step 4: Launch UI ─────────────────────────────────────────────────────
ui = RoomGridUI(room_params, grid_info, level_groups)

if not ui.confirmed[0]:
    forms.alert('Cancelled.', title=__title__, exitscript=True)

p_name      = ui.param_name[0]
ref_pt      = grid_info['corners'][ui.corner_key[0]]
prefix      = ui.prefix[0]
suffix      = ui.suffix[0]
start_count = ui.start[0]

# Corner display label for the summary (e.g. "TOP-RIGHT")
_CORNER_LABELS = {'TL': 'TOP-LEFT', 'TR': 'TOP-RIGHT',
                  'BL': 'BOT-LEFT', 'BR': 'BOT-RIGHT'}
corner_label = _CORNER_LABELS.get(ui.corner_key[0], ui.corner_key[0])

# ── Step 5: Renumber per level ────────────────────────────────────────────
# All levels share a single Transaction for atomic undo.
level_summaries = []
total_numbered  = 0
total_skipped   = 0

with _make_tx(doc, __title__):
    for group in level_groups:
        level_rooms  = sort_by_distance(group['rooms'], ref_pt)
        count        = start_count      # reset for every level
        lvl_numbered = 0
        lvl_start    = count

        for room in level_rooms:
            param = room.LookupParameter(p_name)
            if (param
                    and not param.IsReadOnly
                    and param.StorageType == StorageType.String):
                try:
                    param.Set(prefix + str(count) + suffix)
                    count        += 1
                    lvl_numbered += 1
                except Exception:
                    total_skipped += 1
            else:
                total_skipped += 1

        total_numbered += lvl_numbered
        level_summaries.append((
            group['name'],
            lvl_numbered,
            lvl_start,
            count - 1,
        ))

# ── Step 6: Summary ───────────────────────────────────────────────────────
level_lines = '\n'.join(
    u'  {name:<20}  {n} room{pl}   ({pfx}{s}{sfx} \u2013 {pfx}{e}{sfx})'.format(
        name = name,
        n    = n,
        pl   = 's' if n != 1 else ' ',
        pfx  = prefix,
        sfx  = suffix,
        s    = s,
        e    = e,
    )
    for name, n, s, e in level_summaries
)

forms.alert(
    u'Renumbering complete!\n\n'
    u'Parameter    : {param}\n'
    u'Reference    : {corner}  (X={rx:.2f}   Y={ry:.2f})\n\n'
    u'Per-level breakdown:\n{levels}\n\n'
    u'{total} room{tpl} numbered   \u00b7   {sk} skipped.'.format(
        param  = p_name,
        corner = corner_label,
        rx     = ref_pt[0],
        ry     = ref_pt[1],
        levels = level_lines,
        total  = total_numbered,
        tpl    = 's' if total_numbered != 1 else '',
        sk     = total_skipped,
    ),
    title=__title__,
)
# ==================================================
# -*- coding: utf-8 -*-
"""
Floor Opener (Linked Shafts) v5 - Cut openings in a floor around shaft
openings from LINKS YOU CHOOSE.
"""

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')
clr.AddReference('System.Xml')

from Autodesk.Revit.DB import (
    Transaction, SubTransaction, BuiltInCategory, BuiltInParameter, ElementId,
    XYZ, Line, Arc, CurveLoop, Floor, Transform, RevitLinkInstance,
    FilteredElementCollector,
    GeometryCreationUtilities, BooleanOperationsUtils, BooleanOperationsType,
    PlanarFace
)
from Autodesk.Revit.UI import TaskDialog
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter

from System import EventHandler
from System.Collections.Generic import List
from System.Windows import (
    RoutedEventHandler, Visibility, Thickness, CornerRadius, TextWrapping,
    VerticalAlignment
)
from System.Windows.Controls import (
    CheckBox, StackPanel, TextBlock, Border, Orientation, TextChangedEventHandler
)
from System.Windows.Markup import XamlReader
from System.Windows.Media import BrushConverter
from System.Windows.Threading import Dispatcher, DispatcherFrame

import traceback


doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
app = __revit__.Application


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

POINT_TOL = 1e-5          # ft - curve chaining / coincident point tolerance
FLAT_TOL = 1e-9           # ft - Z spread below which a loop is already exactly flat
HORIZONTAL_TOL = 1e-4     # ft - Z spread above which a loop is not horizontal
Z_TOLERANCE = 0.1         # ft - vertical slack for "shaft touches this floor"
MIN_LOOP_AREA = 1e-6      # sq ft - below this a loop is degenerate
MIN_CUT_VOLUME = 1e-6     # cu ft - below this a shaft is treated as not cutting
SCRATCH_HEIGHT = 1.0      # ft - extrusion height for boolean scratch geometry
COLLINEAR_TOL = 1e-9      # 1 - dot product, above which two lines count as collinear

try:
    SHORT_CURVE_TOL = app.ShortCurveTolerance
except Exception:
    SHORT_CURVE_TOL = 0.0026   # Revit's usual default, in feet


# Catppuccin Mocha
COLOR_BG = "#1E1E2E"
COLOR_CARD = "#2A2A3C"
COLOR_SURFACE = "#313244"
COLOR_MUTED = "#45475A"
COLOR_TEXT = "#CDD6F4"
COLOR_SUBTEXT = "#A6ADC8"
COLOR_ACCENT = "#F0A500"

_BRUSHES = BrushConverter()


def _brush(hex_string):
    return _BRUSHES.ConvertFromString(hex_string)


# ---------------------------------------------------------------------------
# Compatibility helpers
# ---------------------------------------------------------------------------

def _eid_str(element_id):
    """ElementId -> string, compatible across Revit versions.
    Revit 2025+ replaced IntegerValue with Value (Int64)."""
    try:
        return str(element_id.Value)
    except AttributeError:
        return str(element_id.IntegerValue)


def _label(source_name, element):
    """Human-readable tag for reporting, e.g. 'Core.rvt : 481233'."""
    return "{0} : {1}".format(source_name, _eid_str(element.Id))


# ---------------------------------------------------------------------------
# Selection - floor only
# ---------------------------------------------------------------------------

class FloorSelectionFilter(ISelectionFilter):
    def AllowElement(self, element):
        return isinstance(element, Floor)

    def AllowReference(self, reference, position):
        return True


def get_target_floor():
    """Returns the floor to operate on, or None if the user cancelled.
    Honours an existing selection so no pick is needed when one is highlighted."""
    floors = []
    for eid in uidoc.Selection.GetElementIds():
        el = doc.GetElement(eid)
        if isinstance(el, Floor):
            floors.append(el)

    if len(floors) == 1:
        return floors[0]
    if len(floors) > 1:
        TaskDialog.Show(
            "Floor Opener",
            "{0} floors are selected. Select exactly one floor, or clear the "
            "selection to be prompted for a pick.".format(len(floors))
        )
        return None

    try:
        ref = uidoc.Selection.PickObject(
            ObjectType.Element,
            FloorSelectionFilter(),
            "Select a floor to open around linked shaft openings"
        )
    except Exception:
        return None  # user cancelled

    picked = doc.GetElement(ref.ElementId)
    if not isinstance(picked, Floor):
        return None
    return picked


# ---------------------------------------------------------------------------
# Link selection menu
# ---------------------------------------------------------------------------

MENU_XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Floor Opener - Choose Links"
        Width="540" Height="640"
        WindowStartupLocation="CenterScreen"
        Background="#1E1E2E">
    <Window.Resources>
        <Style x:Key="RoundButton" TargetType="Button">
            <Setter Property="Background" Value="#F0A500"/>
            <Setter Property="Foreground" Value="#1E1E2E"/>
            <Setter Property="FontWeight" Value="Bold"/>
            <Setter Property="BorderThickness" Value="0"/>
            <Setter Property="Cursor" Value="Hand"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="Button">
                        <Border Background="{TemplateBinding Background}" CornerRadius="6">
                            <ContentPresenter HorizontalAlignment="Center"
                                              VerticalAlignment="Center"/>
                        </Border>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>
        <Style x:Key="QuietButton" TargetType="Button" BasedOn="{StaticResource RoundButton}">
            <Setter Property="Background" Value="#45475A"/>
            <Setter Property="Foreground" Value="#CDD6F4"/>
            <Setter Property="FontWeight" Value="Normal"/>
        </Style>
        <Style x:Key="RoundTextBox" TargetType="TextBox">
            <Setter Property="Background" Value="#313244"/>
            <Setter Property="Foreground" Value="#CDD6F4"/>
            <Setter Property="BorderBrush" Value="#45475A"/>
            <Setter Property="BorderThickness" Value="1"/>
            <Setter Property="Padding" Value="8,6"/>
            <Setter Property="FontSize" Value="13"/>
            <Setter Property="CaretBrush" Value="#CDD6F4"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="TextBox">
                        <Border Background="{TemplateBinding Background}"
                                BorderBrush="{TemplateBinding BorderBrush}"
                                BorderThickness="{TemplateBinding BorderThickness}"
                                CornerRadius="6">
                            <ScrollViewer x:Name="PART_ContentHost"
                                          Margin="{TemplateBinding Padding}"
                                          VerticalAlignment="Center"/>
                        </Border>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>
    </Window.Resources>

    <Grid Margin="20">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <TextBlock Grid.Row="0" Text="Choose links to process"
                   Foreground="#CDD6F4" FontSize="18" FontWeight="Bold"
                   Margin="0,0,0,4"/>
        <TextBlock Grid.Row="1" x:Name="SubtitleText"
                   Foreground="#A6ADC8" FontSize="12" TextWrapping="Wrap"
                   Margin="0,0,0,12"/>

        <TextBox Grid.Row="2" x:Name="SearchBox"
                 Style="{StaticResource RoundTextBox}" Margin="0,0,0,10"/>

        <StackPanel Grid.Row="3" Orientation="Horizontal" Margin="0,0,0,10">
            <Button x:Name="SelectAllBtn" Content="Select all" Width="96" Height="26"
                    Style="{StaticResource QuietButton}" FontSize="12" Margin="0,0,8,0"/>
            <Button x:Name="SelectNoneBtn" Content="Select none" Width="96" Height="26"
                    Style="{StaticResource QuietButton}" FontSize="12"/>
        </StackPanel>

        <Border Grid.Row="4" Background="#181825" CornerRadius="8" Padding="8">
            <ScrollViewer VerticalScrollBarVisibility="Auto">
                <StackPanel x:Name="LinkList"/>
            </ScrollViewer>
        </Border>

        <TextBlock Grid.Row="5" x:Name="StatusText"
                   Foreground="#A6ADC8" FontSize="12" Margin="0,10,0,0"/>

        <StackPanel Grid.Row="6" Orientation="Horizontal"
                    HorizontalAlignment="Right" Margin="0,14,0,0">
            <Button x:Name="CancelBtn" Content="Cancel" Width="90" Height="32"
                    Style="{StaticResource QuietButton}" Margin="0,0,8,0"/>
            <Button x:Name="OkBtn" Content="Cut openings" Width="140" Height="32"
                    Style="{StaticResource RoundButton}"/>
        </StackPanel>
    </Grid>
</Window>
"""


def push_frame_show(window):
    """Shows a WPF window modeless-but-blocking. Dispatcher.PushFrame keeps the
    Revit UI thread behaving correctly, which ShowDialog() does not."""
    frame = DispatcherFrame()

    def _on_closed(sender, args):
        frame.Continue = False

    window.Closed += EventHandler(_on_closed)   # Closed needs EventHandler,
    window.Show()                               # not RoutedEventHandler
    Dispatcher.PushFrame(frame)


def build_source_row(source):
    """Builds one selectable row: a card holding a checkbox with a two-line
    label. Returns (border, checkbox)."""
    title = TextBlock()
    title.Text = source["name"]
    title.Foreground = _brush(COLOR_TEXT)
    title.FontSize = 13
    title.TextWrapping = TextWrapping.Wrap

    if not source["loaded"]:
        detail_text = "Not loaded - cannot be processed"
    elif source["total"] == 0:
        detail_text = "No shaft openings in this file"
    elif not source["openings"]:
        detail_text = "{0} shaft(s), none near this floor".format(source["total"])
    else:
        detail_text = "{0} near this floor ({1} total)".format(
            len(source["openings"]), source["total"])

    detail = TextBlock()
    detail.Text = detail_text
    detail.Foreground = _brush(COLOR_SUBTEXT)
    detail.FontSize = 11
    detail.Margin = Thickness(0, 2, 0, 0)

    stack = StackPanel()
    stack.Orientation = Orientation.Vertical
    stack.Children.Add(title)
    stack.Children.Add(detail)

    checkbox = CheckBox()
    checkbox.Content = stack
    checkbox.Foreground = _brush(COLOR_TEXT)
    checkbox.VerticalContentAlignment = VerticalAlignment.Top
    checkbox.IsEnabled = bool(source["loaded"] and source["openings"])
    checkbox.IsChecked = bool(source["openings"]) and source["is_link"]

    border = Border()
    border.Background = _brush(COLOR_CARD)
    border.CornerRadius = CornerRadius(6)
    border.Padding = Thickness(10, 8, 10, 8)
    border.Margin = Thickness(0, 0, 0, 6)
    border.BorderThickness = Thickness(1)
    border.BorderBrush = _brush(COLOR_MUTED)
    border.Child = checkbox

    return border, checkbox


def show_link_menu(sources, floor_id_text):
    """Multi-select menu over the available shaft sources.

    Returns the list of selected source dicts, or None if cancelled. Uses a
    mutable dict for the result because IronPython 2.7 has no `nonlocal`."""
    result = {"confirmed": False}

    window = XamlReader.Parse(MENU_XAML)
    subtitle = window.FindName("SubtitleText")
    search_box = window.FindName("SearchBox")
    link_list = window.FindName("LinkList")
    status_text = window.FindName("StatusText")
    select_all_btn = window.FindName("SelectAllBtn")
    select_none_btn = window.FindName("SelectNoneBtn")
    ok_btn = window.FindName("OkBtn")
    cancel_btn = window.FindName("CancelBtn")

    subtitle.Text = ("Only shafts from the links you tick will be cut into "
                     "floor {0}. Counts show how many shafts fall near this "
                     "floor, which is the number that matters.".format(floor_id_text))

    rows = []
    for source in sources:
        border, checkbox = build_source_row(source)
        link_list.Children.Add(border)
        rows.append({"source": source, "border": border, "checkbox": checkbox})

    def refresh_status(sender=None, args=None):
        selected = 0
        shafts = 0
        for row in rows:
            if row["checkbox"].IsChecked:
                selected += 1
                shafts += len(row["source"]["openings"])
            # Accent border on the checked card, matching the toggle style used
            # elsewhere in the extension.
            if row["checkbox"].IsChecked:
                row["border"].BorderBrush = _brush(COLOR_ACCENT)
            else:
                row["border"].BorderBrush = _brush(COLOR_MUTED)
        status_text.Text = "{0} link(s) selected - {1} shaft(s) will be processed".format(
            selected, shafts)

    for row in rows:
        row["checkbox"].Checked += RoutedEventHandler(refresh_status)
        row["checkbox"].Unchecked += RoutedEventHandler(refresh_status)

    def on_search(sender, args):
        needle = search_box.Text.strip().lower()
        for row in rows:
            visible = (not needle) or (needle in row["source"]["name"].lower())
            row["border"].Visibility = Visibility.Visible if visible else Visibility.Collapsed

    def visible_rows():
        return [r for r in rows if r["border"].Visibility == Visibility.Visible]

    def on_select_all(sender, args):
        # Acts on what is currently visible, so it composes with the search box.
        for row in visible_rows():
            if row["checkbox"].IsEnabled:
                row["checkbox"].IsChecked = True
        refresh_status()

    def on_select_none(sender, args):
        for row in visible_rows():
            row["checkbox"].IsChecked = False
        refresh_status()

    def on_ok(sender, args):
        chosen = [r["source"] for r in rows if r["checkbox"].IsChecked]
        if not chosen:
            status_text.Text = "Select at least one link first."
            return
        result["confirmed"] = True
        result["selected"] = chosen
        window.Close()

    def on_cancel(sender, args):
        result["confirmed"] = False
        window.Close()

    search_box.TextChanged += TextChangedEventHandler(on_search)
    select_all_btn.Click += RoutedEventHandler(on_select_all)
    select_none_btn.Click += RoutedEventHandler(on_select_none)
    ok_btn.Click += RoutedEventHandler(on_ok)
    cancel_btn.Click += RoutedEventHandler(on_cancel)

    refresh_status()
    push_frame_show(window)

    if not result["confirmed"]:
        return None
    return result["selected"]


# ---------------------------------------------------------------------------
# CurveLoop utilities
#
# Everything here is a CurveLoop - floor boundaries, existing holes and shaft
# profiles are all the same type. Winding direction is what separates
# "material" (counter-clockwise) from "hole" (clockwise).
# ---------------------------------------------------------------------------

def loop_points(curve_loop):
    """Ordered tessellated XYZ points around a CurveLoop. Tessellation rather
    than endpoints-only is what makes the area check correct for arcs."""
    pts = []
    for curve in curve_loop:
        tess = curve.Tessellate()
        count = len(tess)
        for i in range(count - 1):   # drop each curve's last point - it is the
            pts.append(tess[i])      # next curve's first point
    return pts


def signed_plan_area(curve_loop):
    """Shoelace signed area in plan. Positive = counter-clockwise from +Z."""
    pts = loop_points(curve_loop)
    n = len(pts)
    if n < 3:
        return 0.0
    total = 0.0
    for i in range(n):
        p1 = pts[i]
        p2 = pts[(i + 1) % n]
        total += (p1.X * p2.Y) - (p2.X * p1.Y)
    return total / 2.0


def reverse_loop(curve_loop):
    """Returns a new CurveLoop with the opposite winding direction."""
    reversed_loop = CurveLoop()
    for curve in reversed(list(curve_loop)):
        reversed_loop.Append(curve.CreateReversed())
    return reversed_loop


def orient_loop(curve_loop, want_ccw):
    """Normalises winding. CreateExtrusionGeometry wants the outer profile CCW
    and voids CW; Floor.Create wants boundary and holes wound opposite to each
    other. Nothing is trusted to arrive already correct."""
    is_ccw = signed_plan_area(curve_loop) > 0.0
    if is_ccw == want_ccw:
        return curve_loop
    return reverse_loop(curve_loop)


def loop_is_valid(curve_loop):
    """Rejects collapsed or near-zero-area loops."""
    if curve_loop is None:
        return False
    try:
        if not curve_loop.IsClosed():
            return False
    except Exception:
        pass
    return abs(signed_plan_area(curve_loop)) > MIN_LOOP_AREA


def loop_z_range(curve_loop):
    """Returns (min_z, max_z) over the loop's tessellated points, or None."""
    zs = [p.Z for p in loop_points(curve_loop)]
    if not zs:
        return None
    return (min(zs), max(zs))


def project_curve_to_z(curve, z):
    """Returns a list of curves that are the input curve laid EXACTLY on the
    plane Z = z.

    Rebuilding with an explicit Z guarantees planarity; translating would
    preserve whatever Z variation the loop already had, which is what made
    Floor.Create reject profiles as "not parallel to the horizontal plane".

    Lines and arcs are reconstructed in kind so curvature survives; anything
    else degrades to a tessellated polyline."""
    p0 = curve.GetEndPoint(0)
    p1 = curve.GetEndPoint(1)
    f0 = XYZ(p0.X, p0.Y, z)
    f1 = XYZ(p1.X, p1.Y, z)

    if isinstance(curve, Line):
        if f0.DistanceTo(f1) < SHORT_CURVE_TOL:
            return []
        return [Line.CreateBound(f0, f1)]

    if isinstance(curve, Arc):
        mid = curve.Evaluate(0.5, True)
        fmid = XYZ(mid.X, mid.Y, z)

        if f0.DistanceTo(f1) < POINT_TOL:
            # Closed circular arc - a 3-point Arc.Create needs distinct ends,
            # so split it at the quarter points into two half arcs.
            q1 = curve.Evaluate(0.25, True)
            q3 = curve.Evaluate(0.75, True)
            try:
                return [Arc.Create(f0, fmid, XYZ(q1.X, q1.Y, z)),
                        Arc.Create(fmid, f1, XYZ(q3.X, q3.Y, z))]
            except Exception:
                pass
        else:
            try:
                return [Arc.Create(f0, f1, fmid)]
            except Exception:
                pass

    segments = []
    tess = curve.Tessellate()
    for i in range(len(tess) - 1):
        a = XYZ(tess[i].X, tess[i].Y, z)
        b = XYZ(tess[i + 1].X, tess[i + 1].Y, z)
        if a.DistanceTo(b) >= SHORT_CURVE_TOL:
            segments.append(Line.CreateBound(a, b))
    return segments


def project_loop_to_z(curve_loop, z):
    """Places a loop exactly on the plane Z = z, or returns None if the loop is
    not horizontal at all (a tilted link) - projecting that would silently
    distort the shaft.

    Fast path: an already-flat loop is translated, so arcs survive untouched."""
    z_info = loop_z_range(curve_loop)
    if z_info is None:
        return None
    min_z, max_z = z_info

    if (max_z - min_z) > HORIZONTAL_TOL:
        return None

    if (max_z - min_z) <= FLAT_TOL:
        delta = z - min_z
        if abs(delta) < FLAT_TOL:
            return curve_loop
        translation = Transform.CreateTranslation(XYZ(0, 0, delta))
        moved = CurveLoop()
        for curve in curve_loop:
            moved.Append(curve.CreateTransformed(translation))
        return moved

    rebuilt = CurveLoop()
    appended = 0
    for curve in curve_loop:
        for segment in project_curve_to_z(curve, z):
            try:
                rebuilt.Append(segment)
            except Exception:
                return None   # dropping a sub-tolerance curve left an unbridgeable gap
            appended += 1
    if appended < 3:
        return None
    return rebuilt


def split_curves_into_loops(curves):
    """Chains an unordered flat list of curves into closed loops.

    Opening.BoundaryCurves hands back one flat CurveArray with no loop
    separators and no guaranteed ordering or direction, so the curves are
    stitched end-to-end here. Returns a list of (curve_list, is_closed)."""
    remaining = [c for c in curves]
    chains = []

    while remaining:
        first = remaining.pop(0)
        chain = [first]
        start = first.GetEndPoint(0)
        end = first.GetEndPoint(1)

        grew = True
        while grew and remaining:
            grew = False
            for i in range(len(remaining)):
                candidate = remaining[i]
                c0 = candidate.GetEndPoint(0)
                c1 = candidate.GetEndPoint(1)

                if c0.DistanceTo(end) < POINT_TOL:
                    chain.append(candidate)
                    end = c1
                elif c1.DistanceTo(end) < POINT_TOL:
                    chain.append(candidate.CreateReversed())
                    end = c0
                elif c1.DistanceTo(start) < POINT_TOL:
                    chain.insert(0, candidate)
                    start = c0
                elif c0.DistanceTo(start) < POINT_TOL:
                    chain.insert(0, candidate.CreateReversed())
                    start = c1
                else:
                    continue

                remaining.pop(i)
                grew = True
                break

        chains.append((chain, start.DistanceTo(end) < POINT_TOL))

    return chains


# ---------------------------------------------------------------------------
# Cleanup - prevents failures rather than explaining them
# ---------------------------------------------------------------------------

def merge_collinear_lines(curve_loop):
    """Combines consecutive collinear line segments into one.

    Antidote to curve-count explosion: a tessellated straight run comes back as
    dozens of segments that all lie on the same line."""
    curves = list(curve_loop)
    if len(curves) < 3:
        return curve_loop

    merged = []
    for curve in curves:
        if merged and isinstance(curve, Line) and isinstance(merged[-1], Line):
            previous = merged[-1]
            joins = previous.GetEndPoint(1).DistanceTo(curve.GetEndPoint(0)) < POINT_TOL
            aligned = previous.Direction.DotProduct(curve.Direction) > 1.0 - COLLINEAR_TOL
            if joins and aligned:
                merged[-1] = Line.CreateBound(previous.GetEndPoint(0), curve.GetEndPoint(1))
                continue
        merged.append(curve)

    # The seam between the last and first curve needs the same treatment.
    if len(merged) > 3 and isinstance(merged[-1], Line) and isinstance(merged[0], Line):
        last = merged[-1]
        first = merged[0]
        joins = last.GetEndPoint(1).DistanceTo(first.GetEndPoint(0)) < POINT_TOL
        aligned = last.Direction.DotProduct(first.Direction) > 1.0 - COLLINEAR_TOL
        if joins and aligned:
            merged[0] = Line.CreateBound(last.GetEndPoint(0), first.GetEndPoint(1))
            merged.pop()

    if len(merged) == len(curves):
        return curve_loop

    rebuilt = CurveLoop()
    try:
        for curve in merged:
            rebuilt.Append(curve)
    except Exception:
        return curve_loop
    return rebuilt


def weld_short_curves(curve_loop):
    """Absorbs curves shorter than ShortCurveTolerance into a neighbouring line.

    Revit rejects sketch curves below this length, but the boolean engine has no
    such rule, so difference results routinely contain them. A short curve
    trapped between two arcs is left alone - there is no way to absorb it
    without changing the opening's shape, and the shape is the whole point."""
    curves = list(curve_loop)
    removed = 0

    guard = 0
    while guard < 200:
        guard += 1
        count = len(curves)
        if count <= 3:
            break

        index = None
        for i in range(count):
            try:
                if curves[i].Length < SHORT_CURVE_TOL:
                    index = i
                    break
            except Exception:
                continue
        if index is None:
            break

        previous_index = (index - 1) % count
        next_index = (index + 1) % count
        previous_curve = curves[previous_index]
        next_curve = curves[next_index]

        if isinstance(previous_curve, Line):
            candidate = Line.CreateBound(previous_curve.GetEndPoint(0),
                                         next_curve.GetEndPoint(0))
            if candidate.Length < SHORT_CURVE_TOL:
                break
            curves[previous_index] = candidate
            curves.pop(index)
            removed += 1
            continue

        if isinstance(next_curve, Line):
            candidate = Line.CreateBound(previous_curve.GetEndPoint(1),
                                         next_curve.GetEndPoint(1))
            if candidate.Length < SHORT_CURVE_TOL:
                break
            curves[next_index] = candidate
            curves.pop(index)
            removed += 1
            continue

        break   # short curve between two arcs - not safely absorbable

    if removed <= 0:
        return curve_loop

    rebuilt = CurveLoop()
    try:
        for curve in curves:
            rebuilt.Append(curve)
    except Exception:
        return curve_loop
    return rebuilt


def clean_loop(curve_loop):
    return weld_short_curves(merge_collinear_lines(curve_loop))


# ---------------------------------------------------------------------------
# Stage 1 - read the floor's sketch
# ---------------------------------------------------------------------------

def get_floor_sketch_loops(floor):
    """Returns the floor's sketch profile as a list of CurveLoop - the outer
    boundary plus any holes that already exist in it."""
    sketch_id = floor.SketchId
    if sketch_id is None or sketch_id == ElementId.InvalidElementId:
        raise Exception("Selected floor has no editable sketch (cannot read its profile).")

    sketch = doc.GetElement(sketch_id)
    profile = sketch.Profile  # CurveArrArray - one CurveArray per loop

    loops = []
    for curve_array in profile:
        loop = CurveLoop()
        for curve in curve_array:
            loop.Append(curve)
        loops.append(loop)
    return loops


def split_outer_and_inner(loops):
    """Returns (outer_loop, [inner_loops]). The outer boundary is the loop with
    the largest absolute plan area - true by definition for a floor."""
    best_index = 0
    best_area = -1.0
    for i in range(len(loops)):
        area = abs(signed_plan_area(loops[i]))
        if area > best_area:
            best_area = area
            best_index = i

    outer = loops[best_index]
    inner = [loops[i] for i in range(len(loops)) if i != best_index]
    return outer, inner


# ---------------------------------------------------------------------------
# Stage 2 - enumerate sources, then read the chosen shafts
# ---------------------------------------------------------------------------

def transformed_bbox_extents(bbox, transform):
    """Transforms all 8 corners of a bounding box and returns world-space
    (min_x, min_y, max_x, max_y, min_z, max_z).

    All 8 corners, because a rotated link makes the source box's Min/Max points
    meaningless on their own once transformed."""
    total = transform
    try:
        if bbox.Transform is not None:
            total = transform.Multiply(bbox.Transform)
    except Exception:
        pass

    xs, ys, zs = [], [], []
    for x in (bbox.Min.X, bbox.Max.X):
        for y in (bbox.Min.Y, bbox.Max.Y):
            for z in (bbox.Min.Z, bbox.Max.Z):
                pt = total.OfPoint(XYZ(x, y, z))
                xs.append(pt.X)
                ys.append(pt.Y)
                zs.append(pt.Z)

    return (min(xs), min(ys), max(xs), max(ys), min(zs), max(zs))


def plan_boxes_intersect(box_a, box_b):
    """Cheap broad-phase plan-rectangle overlap. Broad phase ONLY - the real
    containment test is the boolean difference."""
    a_min_x, a_min_y, a_max_x, a_max_y = box_a
    b_min_x, b_min_y, b_max_x, b_max_y = box_b
    return not (b_max_x < a_min_x or b_min_x > a_max_x or
                b_max_y < a_min_y or b_min_y > a_max_y)


def enumerate_shaft_sources(floor_plan_box, floor_z_min, floor_z_max):
    """Builds one entry per shaft source - every RevitLinkInstance plus the
    host document - with its shafts already broad-phase filtered.

    Filtering here rather than after selection is what lets the menu show
    "2 near this floor (40 total)". The counts are then free, and choosing
    links afterwards is just concatenation.

    OST_ShaftOpening is used as a category filter rather than Opening.IsShaft,
    which is unreliable under IronPython on Revit 2027+."""
    raw = []

    for link in FilteredElementCollector(doc).OfClass(RevitLinkInstance):
        try:
            name = link.Name
        except Exception:
            name = "Link " + _eid_str(link.Id)
        link_doc = link.GetLinkDocument()
        raw.append({
            "name": name,
            "doc": link_doc,
            "transform": link.GetTotalTransform() if link_doc is not None else None,
            "loaded": link_doc is not None,
            "is_link": True,
        })

    raw.append({
        "name": "Host document (this model)",
        "doc": doc,
        "transform": Transform.Identity,
        "loaded": True,
        "is_link": False,
    })

    z_min_check = floor_z_min - Z_TOLERANCE
    z_max_check = floor_z_max + Z_TOLERANCE

    for source in raw:
        source["total"] = 0
        source["openings"] = []
        if not source["loaded"]:
            continue

        collector = FilteredElementCollector(source["doc"]) \
            .OfCategory(BuiltInCategory.OST_ShaftOpening) \
            .WhereElementIsNotElementType()

        for opening in collector:
            source["total"] += 1

            bbox = opening.get_BoundingBox(None)   # model-space, in that doc
            if bbox is None:
                continue

            min_x, min_y, max_x, max_y, min_z, max_z = transformed_bbox_extents(
                bbox, source["transform"])

            if max_z < z_min_check or min_z > z_max_check:
                continue
            if not plan_boxes_intersect(floor_plan_box, (min_x, min_y, max_x, max_y)):
                continue

            source["openings"].append(opening)

    return raw


def shaft_profile_loops(opening, transform, target_z):
    """Returns (loops, reason) - the shaft's exact sketch profile as host-space
    CurveLoops on the floor's sketch plane, or ([], reason) on failure.

    Opening.BoundaryCurves gives the real sketched profile, so the opening
    matches the shaft 1:1, arcs included - no rectangle approximation."""
    try:
        boundary = opening.BoundaryCurves
    except Exception:
        return [], "boundary curves unreadable"

    if boundary is None:
        return [], "no boundary curves"

    host_curves = []
    for curve in boundary:
        if curve is None:
            continue
        try:
            host_curves.append(curve.CreateTransformed(transform))
        except Exception:
            return [], "curve transform failed"

    if not host_curves:
        return [], "no boundary curves"

    loops = []
    for chain, is_closed in split_curves_into_loops(host_curves):
        if not is_closed:
            return [], "open (unclosed) boundary"

        raw_loop = CurveLoop()
        try:
            for curve in chain:
                raw_loop.Append(curve)
        except Exception:
            return [], "curve loop build failed"

        flat = project_loop_to_z(raw_loop, target_z)
        if flat is None:
            return [], "profile is not horizontal in host coordinates"

        flat = clean_loop(flat)
        if not loop_is_valid(flat):
            return [], "degenerate profile"

        loops.append(flat)

    if not loops:
        return [], "no closed loops"

    outer, inner = split_outer_and_inner(loops)
    ordered = [orient_loop(outer, True)]
    for loop in inner:
        ordered.append(orient_loop(loop, False))
    return ordered, None


# ---------------------------------------------------------------------------
# Stages 3 and 4 - solids in, outlines out
# ---------------------------------------------------------------------------

def loops_to_scratch_solid(ordered_loops):
    """Extrudes a profile (outer CCW first, then CW voids) into a thin solid.

    Revit has no 2D polygon boolean API, so the height exists purely to make a
    subtraction possible. This geometry is never placed in the model."""
    profile = List[CurveLoop]()
    for loop in ordered_loops:
        profile.Add(loop)
    return GeometryCreationUtilities.CreateExtrusionGeometry(
        profile, XYZ.BasisZ, SCRATCH_HEIGHT
    )


def solid_volume(solid):
    try:
        if solid is None:
            return 0.0
        return solid.Volume
    except Exception:
        return 0.0


def top_face_regions(solid, target_z):
    """Reads a solid's upward-facing planar faces back as floor profiles.

    One profile per disjoint region, each a list of CurveLoop on Z = target_z
    with the outer boundary CCW and holes CW. Every face is collected, not just
    the first: subtracting a shaft can split a slab in two, and taking only one
    would silently delete the other."""
    regions = []
    for face in solid.Faces:
        if not isinstance(face, PlanarFace):
            continue
        if face.FaceNormal.Z < 0.9:
            continue

        raw_loops = []
        for edge_loop in face.GetEdgesAsCurveLoops():
            flat = project_loop_to_z(edge_loop, target_z)
            if flat is None:
                continue
            flat = clean_loop(flat)
            if not loop_is_valid(flat):
                continue
            raw_loops.append(flat)

        if not raw_loops:
            continue

        outer, inner = split_outer_and_inner(raw_loops)
        profile = [orient_loop(outer, True)]
        for loop in inner:
            profile.append(orient_loop(loop, False))
        regions.append(profile)

    return regions


def subtract_shaft(floor_solid, shaft_solid):
    """Returns (new_solid, status) where status is 'cut', 'notched', 'outside'
    or an error string. The intersection test distinguishes a shaft that misses
    the floor's real outline from one that lands on it - the bounding-box
    filter cannot tell those apart."""
    shaft_volume = solid_volume(shaft_solid)

    try:
        overlap = BooleanOperationsUtils.ExecuteBooleanOperation(
            floor_solid, shaft_solid, BooleanOperationsType.Intersect
        )
    except Exception:
        return floor_solid, "intersection test failed"

    overlap_volume = solid_volume(overlap)
    if overlap_volume <= MIN_CUT_VOLUME:
        return floor_solid, "outside"

    try:
        result = BooleanOperationsUtils.ExecuteBooleanOperation(
            floor_solid, shaft_solid, BooleanOperationsType.Difference
        )
    except Exception:
        return floor_solid, "subtraction failed"

    if solid_volume(result) <= MIN_CUT_VOLUME:
        return floor_solid, "would consume the entire floor"

    if overlap_volume < (shaft_volume - MIN_CUT_VOLUME):
        return result, "notched"
    return result, "cut"


# ---------------------------------------------------------------------------
# Stage 5 - build, and the probe that makes skip-and-continue possible
# ---------------------------------------------------------------------------

def build_floors(regions, floor_type_id, level_id):
    """Creates one floor per disjoint region. Raises on the first failure -
    callers decide whether that is fatal or just a probe result."""
    created = []
    for profile in regions:
        profile_loops = List[CurveLoop]()
        for loop in profile:
            profile_loops.Add(loop)
        created.append(Floor.Create(doc, profile_loops, floor_type_id, level_id))
    return created


def profile_is_buildable(regions, floor_type_id, level_id):
    """Asks Revit whether a profile can actually become a floor, WITHOUT
    keeping the result.

    Floor.Create is the only authority on this - no amount of measuring the
    geometry predicts it reliably. A SubTransaction lets the question be asked
    and the answer kept while the model change is discarded, which is what
    turns a single fatal failure into a per-shaft skip.

    Must be called inside an open Transaction."""
    sub = SubTransaction(doc)
    try:
        sub.Start()
    except Exception:
        return False

    ok = True
    try:
        build_floors(regions, floor_type_id, level_id)
    except Exception:
        ok = False

    try:
        sub.RollBack()
    except Exception:
        # A rollback that fails leaves state we cannot reason about, so the
        # answer is treated as "no" regardless of what the probe did.
        return False

    return ok


def apply_result_parameters(new_floor, is_structural, height_offset):
    """Restores the properties lost when the original floor was deleted."""
    try:
        new_floor.IsStructural = is_structural
    except Exception:
        pass

    if height_offset is None:
        return
    try:
        offset_param = new_floor.get_Parameter(
            BuiltInParameter.FLOOR_HEIGHT_ABOVE_LEVEL_PARAM
        )
        if offset_param is not None and not offset_param.IsReadOnly:
            offset_param.Set(height_offset)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Main routine
# ---------------------------------------------------------------------------

def main():
    # --- Stage 1: read the floor ---
    floor = get_target_floor()
    if floor is None:
        return

    try:
        sketch_loops = get_floor_sketch_loops(floor)
    except Exception as ex:
        TaskDialog.Show("Floor Opener", "Could not read floor sketch:\n" + str(ex))
        return

    if not sketch_loops:
        TaskDialog.Show("Floor Opener", "Floor has no boundary loops to work with.")
        return

    outer_loop, existing_inner_loops = split_outer_and_inner(sketch_loops)

    # The sketch plane's Z comes from the outer boundary, not level.Elevation,
    # so floors with a height offset still produce a coplanar profile.
    outer_z = loop_z_range(outer_loop)
    if outer_z is None:
        TaskDialog.Show("Floor Opener", "Could not determine the floor's sketch plane.")
        return
    if (outer_z[1] - outer_z[0]) > HORIZONTAL_TOL:
        TaskDialog.Show(
            "Floor Opener",
            "The floor's boundary is not horizontal (sloped or warped slab). "
            "This script only handles flat floors."
        )
        return
    profile_z = outer_z[0]

    floor_type_id = floor.GetTypeId()
    level_id = floor.LevelId

    floor_bbox = floor.get_BoundingBox(None)
    if floor_bbox is None:
        TaskDialog.Show("Floor Opener", "Could not determine floor extents.")
        return
    floor_plan_box = (floor_bbox.Min.X, floor_bbox.Min.Y,
                      floor_bbox.Max.X, floor_bbox.Max.Y)

    is_structural = False
    try:
        is_structural = floor.IsStructural
    except Exception:
        pass

    height_offset = None
    try:
        param = floor.get_Parameter(BuiltInParameter.FLOOR_HEIGHT_ABOVE_LEVEL_PARAM)
        if param is not None:
            height_offset = param.AsDouble()
    except Exception:
        pass

    skipped = []

    flat_outer = project_loop_to_z(outer_loop, profile_z)
    if flat_outer is None:
        TaskDialog.Show(
            "Floor Opener",
            "The floor's outer boundary could not be placed on a flat plane. "
            "Nothing was changed."
        )
        return
    flat_outer = clean_loop(flat_outer)
    if not loop_is_valid(flat_outer):
        TaskDialog.Show("Floor Opener", "The floor's boundary encloses no area.")
        return

    base_profile = [orient_loop(flat_outer, True)]
    preserved_holes = 0
    for loop in existing_inner_loops:
        flat = project_loop_to_z(loop, profile_z)
        if flat is None:
            skipped.append("existing floor hole (not horizontal, dropped)")
            continue
        flat = clean_loop(flat)
        if not loop_is_valid(flat):
            skipped.append("existing floor hole (degenerate, dropped)")
            continue
        base_profile.append(orient_loop(flat, False))
        preserved_holes += 1

    try:
        base_solid = loops_to_scratch_solid(base_profile)
    except Exception as ex:
        TaskDialog.Show(
            "Floor Opener",
            "Could not build a working solid from the floor's own boundary:\n" + str(ex)
        )
        return

    # --- Stage 2: choose sources, then read their shafts ---
    sources = enumerate_shaft_sources(floor_plan_box, floor_bbox.Min.Z, floor_bbox.Max.Z)

    if not any(s["openings"] for s in sources):
        TaskDialog.Show(
            "Floor Opener",
            "No shaft openings were found near this floor in any loaded link "
            "or in the host model. Nothing to cut."
        )
        return

    chosen = show_link_menu(sources, _eid_str(floor.Id))
    if chosen is None:
        return   # user cancelled - model untouched

    shafts = []
    for source in chosen:
        for opening in source["openings"]:
            name = _label(source["name"], opening)
            loops, reason = shaft_profile_loops(opening, source["transform"], profile_z)
            if reason is not None:
                skipped.append("{0} - {1}".format(name, reason))
                continue
            try:
                solid = loops_to_scratch_solid(loops)
            except Exception:
                skipped.append(name + " - could not build scratch geometry")
                continue
            if solid_volume(solid) <= MIN_CUT_VOLUME:
                skipped.append(name + " - empty profile")
                continue
            shafts.append((name, solid))

    if not shafts:
        msg = "No usable shaft profiles could be built from the selected link(s)."
        if skipped:
            msg += "\n\nSkipped:\n  - " + "\n  - ".join(skipped)
        TaskDialog.Show("Floor Opener", msg)
        return

    # --- Stages 3-5, inside one transaction ---
    t = Transaction(doc, "Open Floor Around Linked Shafts")
    t.Start()
    try:
        # The original floor goes first so probe floors do not overlap it and
        # raise duplicate-geometry warnings. If anything below fails, the whole
        # transaction rolls back and the floor comes straight back.
        doc.Delete(floor.Id)

        # FAST PATH: subtract everything, ask once.
        working_solid = base_solid
        applied = []
        notched = []
        outside = []
        # Skips are collected per pass, not appended to `skipped` directly: if
        # the slow path runs it repeats the same work, and committing both
        # passes would report every failure twice.
        pass_skips = []

        for name, shaft_solid in shafts:
            working_solid, status = subtract_shaft(working_solid, shaft_solid)
            if status == "cut":
                applied.append(name)
            elif status == "notched":
                applied.append(name)
                notched.append(name)
            elif status == "outside":
                outside.append(name)
            else:
                pass_skips.append("{0} - {1}".format(name, status))

        regions = []
        used_slow_path = False

        if applied:
            regions = top_face_regions(working_solid, profile_z)

        if not regions or not profile_is_buildable(regions, floor_type_id, level_id):
            # SLOW PATH: the combined profile is unbuildable, so find out which
            # shaft is responsible by adding them back one at a time and asking
            # after each. This is N sketch creations - it only runs when
            # something is genuinely wrong.
            used_slow_path = True
            working_solid = base_solid
            applied = []
            notched = []
            rejected = []
            pass_skips = []

            for name, shaft_solid in shafts:
                if name in outside:
                    continue

                candidate_solid, status = subtract_shaft(working_solid, shaft_solid)
                if status not in ("cut", "notched"):
                    pass_skips.append("{0} - {1}".format(name, status))
                    continue

                candidate_regions = top_face_regions(candidate_solid, profile_z)
                if not candidate_regions:
                    rejected.append(name)
                    continue

                if not profile_is_buildable(candidate_regions, floor_type_id, level_id):
                    # Note: a sliver is created BETWEEN two things, not by one
                    # of them. When two shafts are jointly at fault, this skips
                    # whichever came second. Arbitrary, but it names its choice.
                    rejected.append(name)
                    continue

                working_solid = candidate_solid
                applied.append(name)
                if status == "notched":
                    notched.append(name)

            for name in rejected:
                pass_skips.append(name + " - profile became unbuildable, opening not cut")

            regions = top_face_regions(working_solid, profile_z) if applied else []

        skipped.extend(pass_skips)

        if not applied or not regions:
            t.RollBack()
            msg = "No shaft could be cut into this floor. Nothing was changed."
            if outside:
                msg += ("\n\n{0} shaft(s) were inside the bounding box but outside "
                        "the real outline:\n  - {1}").format(
                    len(outside), "\n  - ".join(outside))
            if skipped:
                msg += "\n\nSkipped {0} item(s):\n  - {1}".format(
                    len(skipped), "\n  - ".join(skipped))
            TaskDialog.Show("Floor Opener", msg)
            return

        created = build_floors(regions, floor_type_id, level_id)
        for new_floor in created:
            apply_result_parameters(new_floor, is_structural, height_offset)

        t.Commit()

    except Exception as ex:
        t.RollBack()
        TaskDialog.Show(
            "Floor Opener",
            "Failed to rebuild floor with openings:\n" + str(ex) + "\n\n" +
            traceback.format_exc()
        )
        return

    # --- Summary ---
    hole_count = sum(len(profile) - 1 for profile in regions)
    msg = "Cut {0} shaft(s) out of the floor, from {1} selected source(s).".format(
        len(applied), len(chosen))
    msg += "\n\nResult: {0} floor element(s), {1} hole(s).".format(
        len(regions), hole_count)
    if len(regions) > 1:
        msg += ("\nThe shafts split the slab into {0} disjoint regions, so one "
                "floor was created per region.").format(len(regions))
    if used_slow_path:
        msg += ("\n\nThe combined profile was not buildable, so shafts were "
                "applied one at a time and the problem ones were skipped.")
    if preserved_holes:
        msg += "\n\n{0} pre-existing floor hole(s) were preserved.".format(preserved_holes)
    if notched:
        msg += "\n\n{0} shaft(s) straddled the floor edge and notched the outline.".format(
            len(notched))
    if outside:
        msg += "\n{0} shaft(s) were outside the real outline and were ignored.".format(
            len(outside))
    if skipped:
        msg += "\n\nSkipped {0} item(s):\n  - {1}".format(
            len(skipped), "\n  - ".join(skipped))
    TaskDialog.Show("Floor Opener - Done", msg)


main()
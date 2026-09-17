# -*- coding: utf-8 -*-
__title__ = "Corner Guard Placer"
__doc__ = """Version = 2.0
_____________________________________________________________________
Description:
Places a non-hosted Corner Guard family at every convex corner of the
picked columns (active document or linked model).

Runs in 2D plan views only. Every guard is placed on the level of the
ACTIVE VIEW, not the level the column happens to be associated with -
so to guard a column on Level 3, open the Level 3 plan and run.

Corner detection runs off the real column footprint, so rotated and
non-rectangular columns are handled. Rotation is derived from each
corner's outward bisector, calibrated against the family's home
orientation (top-left corner at 0 degrees).

Corners are numbered in the column's own frame:
    1 = top-left, 2 = bottom-left, 3 = bottom-right, 4 = top-right
walking counter-clockwise, so the numbering follows the column when it
is rotated.

How to use:

1-Open the plan view of the level you want the guards on
2-Choose Active document or Linked model
3-Pick the guard family type
4-Pick one or more columns
_____________________________________________________________________
Author: Mohamed Bedair"""

import clr
import math
import sys

clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('PresentationCore')
clr.AddReference('PresentationFramework')
clr.AddReference('WindowsBase')
clr.AddReference('System.Xml')

from Autodesk.Revit.DB import (Element, FamilySymbol, ViewPlan,
                               FilteredElementCollector, BuiltInCategory,
                               Options, ViewDetailLevel, GeometryInstance,
                               Solid, PlanarFace, Line, Plane,
                               ExtrusionAnalyzer, SolidUtils,
                               Transaction, SubTransaction, XYZ,
                               ElementTransformUtils, RevitLinkInstance)
from Autodesk.Revit.DB.Structure import StructuralType
from Autodesk.Revit.UI import (TaskDialog, TaskDialogCommandLinkId,
                               TaskDialogCommonButtons, TaskDialogResult)
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType

from System import EventHandler
from System.Windows.Markup import XamlReader
from System.Windows import RoutedEventHandler
from System.Windows.Controls import TextChangedEventHandler
from System.Windows.Threading import Dispatcher, DispatcherFrame

doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

# ─── Constants ────────────────────────────────────────────────────────────────

# Calibrated from a manual placement: at rotation 0 the guard occupies the
# top-left corner, so its outward bisector points up-left (135 degrees).
HOME_BISECTOR = XYZ(-1.0, 1.0, 0.0).Normalize()

DEFAULT_ANGLE_TOL_DEG = 5.0

VEC_TOL = 1.0e-9
MIN_VOLUME = 1.0e-6

COLUMN_BICS = [BuiltInCategory.OST_Columns,
               BuiltInCategory.OST_StructuralColumns]

DEFAULT_SYMBOL_BICS = [BuiltInCategory.OST_SpecialityEquipment,
                       BuiltInCategory.OST_GenericModel]


# ─── Compatibility helpers ────────────────────────────────────────────────────


def eid_value(element_id):
    """ElementId.Value (Revit 2025+) with .IntegerValue fallback (2024)."""
    try:
        return element_id.Value
    except AttributeError:
        return element_id.IntegerValue


def element_name(elem):
    try:
        return Element.Name.__get__(elem)
    except Exception:
        try:
            return elem.Name
        except Exception:
            return "<unnamed>"


def notify(title, message):
    TaskDialog.Show(title, message)


# ─── Vector helpers ───────────────────────────────────────────────────────────


def flatten(vec):
    """Drop Z and normalize. Returns None if the XY part is degenerate."""
    v = XYZ(vec.X, vec.Y, 0.0)
    if v.GetLength() < VEC_TOL:
        return None
    return v.Normalize()


def outward_normal_ccw(tangent):
    """Outward normal of an edge belonging to a counter-clockwise loop."""
    return XYZ(tangent.Y, -tangent.X, 0.0).Normalize()


def signed_angle_deg(from_vec, to_vec):
    """Signed CCW angle about +Z, in degrees, range 0-360."""
    return math.degrees(from_vec.AngleOnPlaneTo(to_vec, XYZ.BasisZ)) % 360.0


def angular_distance_deg(a, b):
    d = abs((a - b) % 360.0)
    return min(d, 360.0 - d)


# ─── Geometry extraction ──────────────────────────────────────────────────────


def geometry_options():
    opt = Options()
    opt.DetailLevel = ViewDetailLevel.Fine
    opt.ComputeReferences = False
    opt.IncludeNonVisibleObjects = False
    return opt


def collect_solids(geom_obj, found):
    """Recursively gather Solids, handling arbitrarily nested GeometryInstances."""
    for obj in geom_obj:
        if isinstance(obj, Solid):
            if obj.Volume > MIN_VOLUME and obj.Faces.Size > 0:
                found.append(obj)
        elif isinstance(obj, GeometryInstance):
            collect_solids(obj.GetInstanceGeometry(), found)


def element_solids(element, transform):
    """All solids of the element, expressed in host-document coordinates."""
    geom = element.get_Geometry(geometry_options())
    if geom is None:
        return []

    solids = []
    collect_solids(geom, solids)

    if transform is not None and not transform.IsIdentity:
        moved = []
        for solid in solids:
            try:
                moved.append(SolidUtils.CreateTransformed(solid, transform))
            except Exception:
                continue
        return moved

    return solids


def largest_solid(element, transform):
    solids = element_solids(element, transform)
    if not solids:
        return None
    solids.sort(key=lambda s: s.Volume, reverse=True)
    return solids[0]


def bottom_planar_face(solid):
    """Lowest downward-facing planar face of the solid, or None."""
    candidates = []
    for face in solid.Faces:
        if not isinstance(face, PlanarFace):
            continue
        if face.FaceNormal.Z < -0.99:
            candidates.append(face)

    if not candidates:
        return None

    candidates.sort(key=lambda f: (round(f.Origin.Z, 6), -f.Area))
    return candidates[0]


def loop_to_segments(curve_loop):
    """Flatten a CurveLoop into ordered (start, end, is_line) tuples."""
    segments = []
    for curve in curve_loop:
        segments.append((curve.GetEndPoint(0),
                         curve.GetEndPoint(1),
                         isinstance(curve, Line)))
    return segments


def signed_area(segments):
    """Shoelace area of the segment start points, projected to XY."""
    area = 0.0
    for p0, p1, _ in segments:
        area += (p0.X * p1.Y) - (p1.X * p0.Y)
    return area * 0.5


def orient_ccw(segments):
    """Return the segment list running counter-clockwise about +Z."""
    if signed_area(segments) >= 0.0:
        return segments
    return [(p1, p0, is_line) for p0, p1, is_line in reversed(segments)]


def outer_loop_segments(face):
    """Largest edge loop of a face, as CCW-oriented segments."""
    loops = face.GetEdgesAsCurveLoops()
    if loops is None or loops.Count == 0:
        return None

    best = None
    best_area = 0.0
    for loop in loops:
        segs = loop_to_segments(loop)
        area = abs(signed_area(segs))
        if area > best_area:
            best_area = area
            best = segs

    if best is None:
        return None
    return orient_ccw(best)


def footprint_segments(solid):
    """
    Plan footprint of a column solid, as CCW segments, plus the method used.

    Tier 1: bottom planar face edge loops.
    Tier 2: ExtrusionAnalyzer silhouette.
    """
    face = bottom_planar_face(solid)
    if face is not None:
        segs = outer_loop_segments(face)
        if segs:
            return segs, "bottom face"

    try:
        base_z = solid.GetBoundingBox().Min.Z
        plane = Plane.CreateByNormalAndOrigin(XYZ.BasisZ, XYZ(0.0, 0.0, base_z))
        analyzer = ExtrusionAnalyzer.Create(solid, plane, XYZ.BasisZ)
        segs = outer_loop_segments(analyzer.GetExtrusionBase())
        if segs:
            return segs, "extrusion analyzer"
    except Exception:
        pass

    return None, None


# ─── Corner detection ─────────────────────────────────────────────────────────


def find_corners(segments, angle_tol_deg):
    """
    Classify every vertex of a CCW footprint loop.

    Returns the convex, near-90-degree corners in loop order, each carrying
    the corner point and its outward bisector - the bisector is what drives
    both the numbering and the placement rotation.
    """
    corners = []
    count = len(segments)

    for i in range(count):
        seg_in = segments[i - 1]
        seg_out = segments[i]
        point = seg_out[0]

        # Fillets and round columns have no usable corner at the tangent point.
        if not seg_in[2] or not seg_out[2]:
            continue

        t_in = flatten(seg_in[1] - seg_in[0])
        t_out = flatten(seg_out[1] - seg_out[0])
        if t_in is None or t_out is None:
            continue

        cross_z = (t_in.X * t_out.Y) - (t_in.Y * t_out.X)
        if cross_z <= 0.0:
            continue  # re-entrant corner of an L / T / cross column

        interior_deg = 180.0 - math.degrees(t_in.AngleTo(t_out))
        if abs(interior_deg - 90.0) > angle_tol_deg:
            continue  # chamfer, near-collinear vertex, or odd profile

        n_in = outward_normal_ccw(t_in)
        n_out = outward_normal_ccw(t_out)
        bisector = flatten(n_in + n_out)
        if bisector is None:
            continue

        corners.append({"point": point,
                        "bisector": bisector,
                        "interior": interior_deg})

    return corners


def column_local_frame(element, transform):
    """
    Plan axes of the column in host coordinates, corrected for mirroring.

    Used only for corner numbering, never for rotation.
    """
    ex, ey = XYZ.BasisX, XYZ.BasisY

    try:
        local = element.GetTransform()
        ex, ey = local.BasisX, local.BasisY
    except Exception:
        pass

    if transform is not None and not transform.IsIdentity:
        ex = transform.OfVector(ex)
        ey = transform.OfVector(ey)

    ex = flatten(ex)
    ey = flatten(ey)
    if ex is None or ey is None:
        return XYZ.BasisX, XYZ.BasisY

    # A mirrored link flips handedness; restore a right-handed frame so the
    # quadrant signs used for numbering stay meaningful.
    if ex.CrossProduct(ey).Z < 0.0:
        ey = ey.Negate()

    return ex, ey


def number_corners(corners, ex, ey):
    """
    Assign indices 1..n starting from the corner nearest local 135 degrees,
    walking the loop counter-clockwise.

    On a rectangle this reproduces: 1 top-left, 2 bottom-left,
    3 bottom-right, 4 top-right, in the column's own frame.
    """
    if not corners:
        return

    best_i, best_gap = 0, 1.0e9
    for i, corner in enumerate(corners):
        b = corner["bisector"]
        local_deg = math.degrees(math.atan2(b.DotProduct(ey),
                                            b.DotProduct(ex))) % 360.0
        corner["local_deg"] = local_deg

        gap = angular_distance_deg(local_deg, 135.0)
        if gap < best_gap:
            best_gap, best_i = gap, i

    count = len(corners)
    for step in range(count):
        corners[(best_i + step) % count]["index"] = step + 1


# ─── Column gathering ─────────────────────────────────────────────────────────


class HostColumnFilter(ISelectionFilter):
    """Active-document architectural and structural columns."""

    def __init__(self, allowed_ids):
        self.allowed_ids = allowed_ids

    def AllowElement(self, element):
        try:
            if element.Category is None:
                return False
            return eid_value(element.Category.Id) in self.allowed_ids
        except Exception:
            return False

    def AllowReference(self, reference, point):
        return False


class LinkedColumnFilter(ISelectionFilter):
    """Columns living inside a loaded Revit link."""

    def __init__(self, allowed_ids):
        self.allowed_ids = allowed_ids

    def AllowElement(self, element):
        return isinstance(element, RevitLinkInstance)

    def AllowReference(self, reference, point):
        try:
            link_instance = doc.GetElement(reference.ElementId)
            if not isinstance(link_instance, RevitLinkInstance):
                return False
            link_doc = link_instance.GetLinkDocument()
            if link_doc is None:
                return False
            linked_element = link_doc.GetElement(reference.LinkedElementId)
            if linked_element is None or linked_element.Category is None:
                return False
            return eid_value(linked_element.Category.Id) in self.allowed_ids
        except Exception:
            return False


def column_category_ids():
    return [int(bic) for bic in COLUMN_BICS]


def pick_host_columns():
    """Returns a list of (element, transform, label) tuples."""
    refs = uidoc.Selection.PickObjects(
        ObjectType.Element,
        HostColumnFilter(column_category_ids()),
        "Pick columns in the active document, then Finish")

    picked, seen = [], set()
    for ref in refs:
        elem = doc.GetElement(ref.ElementId)
        if elem is None:
            continue
        key = eid_value(elem.Id)
        if key in seen:
            continue
        seen.add(key)
        picked.append((elem, None, "Host {}".format(key)))
    return picked


def pick_linked_columns():
    """Returns a list of (element, transform, label) tuples."""
    refs = uidoc.Selection.PickObjects(
        ObjectType.LinkedElement,
        LinkedColumnFilter(column_category_ids()),
        "Pick columns in a link, then Finish")

    picked, seen = [], set()
    for ref in refs:
        link_instance = doc.GetElement(ref.ElementId)
        if not isinstance(link_instance, RevitLinkInstance):
            continue
        link_doc = link_instance.GetLinkDocument()
        if link_doc is None:
            continue
        elem = link_doc.GetElement(ref.LinkedElementId)
        if elem is None:
            continue

        key = (eid_value(link_instance.Id), eid_value(elem.Id))
        if key in seen:
            continue
        seen.add(key)

        picked.append((elem,
                       link_instance.GetTotalTransform(),
                       "Link {} / {}".format(eid_value(link_instance.Id),
                                             eid_value(elem.Id))))
    return picked


# ─── Active view / level ──────────────────────────────────────────────────────


def view_level(view):
    """
    The level a plan view is generated from.

    GenLevel is the authoritative source for every ViewPlan flavour
    (floor, ceiling, structural, area); LevelId is the fallback.
    """
    level = None

    try:
        level = view.GenLevel
    except Exception:
        level = None

    if level is None:
        try:
            level = doc.GetElement(view.LevelId)
        except Exception:
            level = None

    return level


def validate_active_view():
    """
    Enforce the 2D plan-view restriction.

    Returns (view, level) on success, or (None, message) on refusal.
    """
    view = doc.ActiveView

    if view is None:
        return None, "There is no active view."

    if view.IsTemplate:
        return None, ("The active view is a view template.\n\n"
                      "Open a real 2D plan view and run again.")

    if not isinstance(view, ViewPlan):
        return None, ("Corner Guard Placer only runs in a 2D plan view "
                      "(floor, ceiling, structural or area plan).\n\n"
                      "Active view: {} ({})\n\n"
                      "Guards are placed on the active view's level, so the "
                      "view has to have one. Open the plan of the level you "
                      "want the guards on, then run again."
                      .format(element_name(view), view.ViewType))

    level = view_level(view)
    if level is None:
        return None, ("The active plan view '{}' has no associated level, "
                      "so there is nothing to place the guards on."
                      .format(element_name(view)))

    return (view, level), None


# ─── Placement ────────────────────────────────────────────────────────────────


def place_instance(symbol, point, level):
    """
    Create the family instance at rotation 0.

    The level overload is preferred so the instance reports a sensible host
    level; the three-argument form is the fallback for families that reject it.
    """
    try:
        return doc.Create.NewFamilyInstance(point, symbol, level,
                                            StructuralType.NonStructural)
    except Exception:
        return doc.Create.NewFamilyInstance(point, symbol,
                                            StructuralType.NonStructural)


def snap_to_point(instance, target):
    """
    The level overload does not always honour the supplied Z, so correct the
    instance onto the exact target before rotating about it.
    """
    try:
        location = instance.Location
        current = location.Point
    except Exception:
        return
    delta = target - current
    if delta.GetLength() > 1.0e-9:
        ElementTransformUtils.MoveElement(doc, instance.Id, delta)


def rotate_instance(instance_id, point, angle_deg):
    axis = Line.CreateBound(point, point + XYZ.BasisZ)
    ElementTransformUtils.RotateElement(doc, instance_id, axis,
                                        math.radians(angle_deg))


# ─── UI ───────────────────────────────────────────────────────────────────────

XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Corner Guard Placer"
        Width="520" Height="560"
        WindowStartupLocation="CenterScreen"
        Background="#161616"
        ResizeMode="CanResize">

  <Window.Resources>

    <Style x:Key="LabelText" TargetType="TextBlock">
      <Setter Property="Foreground" Value="#A8A8A8"/>
      <Setter Property="FontFamily" Value="Segoe UI"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="Margin" Value="0,10,0,4"/>
    </Style>

    <Style TargetType="TextBox">
      <Setter Property="Background" Value="#262626"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="BorderBrush" Value="#525252"/>
      <Setter Property="BorderThickness" Value="0,0,0,1"/>
      <Setter Property="FontFamily" Value="Segoe UI"/>
      <Setter Property="FontSize" Value="13"/>
      <Setter Property="Padding" Value="8,6,8,6"/>
      <Setter Property="CaretBrush" Value="#F1C21B"/>
    </Style>

    <Style TargetType="ListBox">
      <Setter Property="Background" Value="#262626"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="BorderBrush" Value="#393939"/>
      <Setter Property="BorderThickness" Value="1"/>
      <Setter Property="FontFamily" Value="Segoe UI"/>
      <Setter Property="FontSize" Value="12"/>
    </Style>

    <Style TargetType="CheckBox">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="FontFamily" Value="Segoe UI"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="Margin" Value="0,8,0,0"/>
    </Style>

    <Style x:Key="PrimaryButton" TargetType="Button">
      <Setter Property="Foreground" Value="#161616"/>
      <Setter Property="FontFamily" Value="Segoe UI"/>
      <Setter Property="FontSize" Value="13"/>
      <Setter Property="Height" Value="38"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="Bd" CornerRadius="4" Background="#F1C21B">
              <ContentPresenter HorizontalAlignment="Center"
                                VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#FFD949"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="GhostButton" TargetType="Button">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="FontFamily" Value="Segoe UI"/>
      <Setter Property="FontSize" Value="13"/>
      <Setter Property="Height" Value="38"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="Bd" CornerRadius="4" Background="#262626"
                    BorderBrush="#393939" BorderThickness="1">
              <ContentPresenter HorizontalAlignment="Center"
                                VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#393939"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

  </Window.Resources>

  <Grid Margin="20,16,20,16">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <StackPanel Grid.Row="0">
      <TextBlock Text="Corner Guard Placer" Foreground="#F4F4F4"
                 FontFamily="Segoe UI" FontSize="20"/>
      <TextBlock x:Name="TxtSource" Text="" Foreground="#F1C21B"
                 FontFamily="Segoe UI" FontSize="11" Margin="0,4,0,0"/>
      <TextBlock x:Name="TxtTarget" Text="" Foreground="#A8A8A8"
                 FontFamily="Segoe UI" FontSize="11" Margin="0,2,0,0"
                 TextWrapping="Wrap"/>
    </StackPanel>

    <StackPanel Grid.Row="1">

      <TextBlock Text="GUARD FAMILY TYPE" Style="{StaticResource LabelText}"/>
      <TextBox x:Name="TxtSearch" Margin="0,0,0,6"/>
      <ListBox x:Name="LstTypes" Height="300"/>
      <CheckBox x:Name="ChkAllCats" Content="Show all categories"/>

    </StackPanel>

    <Grid Grid.Row="2" Margin="0,16,0,0">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="10"/>
        <ColumnDefinition Width="*"/>
      </Grid.ColumnDefinitions>
      <Button x:Name="BtnRun" Grid.Column="0" Content="Pick columns and place"
              Style="{StaticResource PrimaryButton}"/>
      <Button x:Name="BtnCancel" Grid.Column="2" Content="Cancel"
              Style="{StaticResource GhostButton}"/>
    </Grid>

  </Grid>
</Window>
"""


def collect_symbols(all_categories):
    """Family symbols offered in the picker, as (label, symbol) pairs."""
    allowed = [int(bic) for bic in DEFAULT_SYMBOL_BICS]
    pairs = []

    for symbol in FilteredElementCollector(doc).OfClass(FamilySymbol).ToElements():
        try:
            category = symbol.Category
            if category is None:
                continue
            if not all_categories and eid_value(category.Id) not in allowed:
                continue
            pairs.append(("{} : {}".format(symbol.Family.Name,
                                           element_name(symbol)), symbol))
        except Exception:
            continue

    pairs.sort(key=lambda pair: pair[0].lower())
    return pairs


def ask_source():
    """TaskDialog front door: active document or linked model."""
    dialog = TaskDialog("Corner Guard Placer")
    dialog.MainInstruction = "Where are the columns?"
    dialog.MainContent = ("Corner guards are placed in the active document " 
                          "either way - this only decides where the columns " 
                          "are picked from.")
    dialog.AddCommandLink(TaskDialogCommandLinkId.CommandLink1,
                          "Active document",
                          "Pick columns modelled in this project")
    dialog.AddCommandLink(TaskDialogCommandLinkId.CommandLink2,
                          "Linked model",
                          "Pick columns inside a loaded Revit link")
    dialog.CommonButtons = TaskDialogCommonButtons.Cancel
    dialog.DefaultButton = TaskDialogResult.Cancel

    result = dialog.Show()
    if result == TaskDialogResult.CommandLink1:
        return False
    if result == TaskDialogResult.CommandLink2:
        return True
    return None


def show_ui(from_link, view, level):
    """Carbon-themed modeless window. Returns a settings dict, or None."""
    window = XamlReader.Parse(XAML)

    txt_source = window.FindName("TxtSource")
    txt_target = window.FindName("TxtTarget")
    txt_search = window.FindName("TxtSearch")
    lst_types = window.FindName("LstTypes")
    chk_all_cats = window.FindName("ChkAllCats")
    btn_run = window.FindName("BtnRun")
    btn_cancel = window.FindName("BtnCancel")

    txt_source.Text = ("Source: linked model" if from_link
                       else "Source: active document")
    txt_target.Text = "Placing on {} (from view {})".format(
        element_name(level), element_name(view))

    state = {"result": None, "pairs": [], "frame": None}

    def apply_filter():
        needle = (txt_search.Text or "").strip().lower()
        lst_types.Items.Clear()
        for label, _ in state["pairs"]:
            if needle and needle not in label.lower():
                continue
            lst_types.Items.Add(label)

    def repopulate():
        state["pairs"] = collect_symbols(bool(chk_all_cats.IsChecked))
        apply_filter()

    def selected_symbol():
        label = lst_types.SelectedItem
        if label is None:
            return None
        for item_label, symbol in state["pairs"]:
            if item_label == label:
                return symbol
        return None

    def on_search(sender, args):
        apply_filter()

    def on_all_cats(sender, args):
        repopulate()

    def on_run(sender, args):
        symbol = selected_symbol()
        if symbol is None:
            txt_source.Text = "Pick a family type before running."
            return

        state["result"] = {"symbol": symbol, "linked": from_link}
        window.Close()

    def on_cancel(sender, args):
        state["result"] = None
        window.Close()

    def on_closed(sender, args):
        if state["frame"] is not None:
            state["frame"].Continue = False

    txt_search.TextChanged += TextChangedEventHandler(on_search)
    chk_all_cats.Click += RoutedEventHandler(on_all_cats)
    btn_run.Click += RoutedEventHandler(on_run)
    btn_cancel.Click += RoutedEventHandler(on_cancel)
    window.Closed += EventHandler(on_closed)

    repopulate()

    window.Show()
    frame = DispatcherFrame()
    state["frame"] = frame
    Dispatcher.PushFrame(frame)

    return state["result"]


# ─── Main ─────────────────────────────────────────────────────────────────────

# The active view decides the target level, so it is checked before anything
# else - no point picking columns in a view that cannot host the guards.
view_info, refusal = validate_active_view()
if view_info is None:
    notify("Corner Guard Placer", refusal)
    sys.exit()

active_view, target_level = view_info

from_link = ask_source()
if from_link is None:
    sys.exit()

settings = show_ui(from_link, active_view, target_level)
if settings is None:
    sys.exit()

symbol = settings["symbol"]
angle_tol = DEFAULT_ANGLE_TOL_DEG
target_z = target_level.Elevation

# Pick the columns after the window is gone so the pick prompt is visible.
try:
    columns = pick_linked_columns() if from_link else pick_host_columns()
except Exception:
    columns = []

if not columns:
    notify("Corner Guard Placer", "No columns picked. Script cancelled.")
    sys.exit()

# ─── Detection ────────────────────────────────────────────────────────────────

records = []
skipped_columns = []

for element, transform, label in columns:
    try:
        solid = largest_solid(element, transform)
    except Exception as ex:
        skipped_columns.append((label, "geometry failed: {}".format(ex)))
        continue

    if solid is None:
        skipped_columns.append((label, "no solid geometry"))
        continue

    segments, method = footprint_segments(solid)
    if not segments:
        skipped_columns.append((label, "no usable footprint (round column, or cut base)"))
        continue

    corners = find_corners(segments, angle_tol)
    if not corners:
        skipped_columns.append((label, "no convex 90-degree corners ({})".format(method)))
        continue

    ex, ey = column_local_frame(element, transform)
    number_corners(corners, ex, ey)

    for corner in corners:
        records.append({"label": label,
                        "method": method,
                        "index": corner["index"],
                        "local_deg": corner["local_deg"],
                        "interior": corner["interior"],
                        "corner": corner,
                        "level": target_level,
                        "bisector": corner["bisector"],
                        "angle": signed_angle_deg(HOME_BISECTOR,
                                                  corner["bisector"]),
                        "instance": None,
                        "status": "pending",
                        "note": ""})

if not records:
    reasons = "\n".join(["{} - {}".format(label, reason)
                         for label, reason in skipped_columns])
    notify("Corner Guard Placer",
           "No placeable corners found.\n\n{}".format(reasons))
    sys.exit()

# The insertion point is the corner in plan, dropped onto the elevation of the
# ACTIVE VIEW's level - deliberately ignoring the column's own base, which may
# sit on a different level entirely.
for record in records:
    corner_pt = record["corner"]["point"]
    record["point"] = XYZ(corner_pt.X, corner_pt.Y, target_z)

placeable = records

# ─── Transaction ──────────────────────────────────────────────────────────────

by_column = {}
for record in placeable:
    by_column.setdefault(record["label"], []).append(record)

t = Transaction(doc, "Place Corner Guards")
t.Start()

try:
    if not symbol.IsActive:
        symbol.Activate()
        doc.Regenerate()

    # Pass 1 - place at rotation 0, isolated per column so one bad column
    # cannot take the rest of the run down with it.
    for label in by_column:
        sub = SubTransaction(doc)
        sub.Start()
        try:
            for record in by_column[label]:
                instance = place_instance(symbol, record["point"],
                                          record["level"])
                if instance is None:
                    record["status"] = "failed"
                    record["note"] = "NewFamilyInstance returned null"
                    continue
                record["instance"] = instance
                record["status"] = "placed"
            sub.Commit()
        except Exception as ex:
            sub.RollBack()
            for record in by_column[label]:
                record["instance"] = None
                record["status"] = "failed"
                record["note"] = "placement: {}".format(ex)

    # One regeneration for the whole run, not one per element.
    doc.Regenerate()

    # Pass 2 - snap onto the exact insertion point. The level overload does not
    # always honour the supplied Z, so this is what actually pins the guard to
    # the active view's elevation.
    for record in placeable:
        if record["instance"] is None:
            continue
        try:
            snap_to_point(record["instance"], record["point"])
        except Exception as ex:
            record["note"] = "snap: {}".format(ex)

    doc.Regenerate()

    # Pass 3 - rotate.
    for record in placeable:
        if record["instance"] is None:
            continue
        try:
            rotate_instance(record["instance"].Id, record["point"],
                            record["angle"])
            record["status"] = "rotated"
        except Exception as ex:
            record["status"] = "failed"
            record["note"] = "rotation: {}".format(ex)

    doc.Regenerate()

    t.Commit()

except Exception as ex:
    t.RollBack()
    notify("Corner Guard Placer",
           "Run failed and was rolled back:\n\n{}".format(ex))
    raise

# ─── Summary ──────────────────────────────────────────────────────────────────

placed = len([r for r in records if r["instance"] is not None])
bad = len([r for r in records if r["status"] == "failed"])

lines = ["{} guards placed on {} columns.".format(placed, len(by_column)),
         "Level: {} (from view {}).".format(element_name(target_level),
                                            element_name(active_view))]
if skipped_columns:
    lines.append("{} columns skipped entirely.".format(len(skipped_columns)))
if bad:
    lines.append("{} guards failed.".format(bad))

notify("Corner Guard Placer", "\n".join(lines))
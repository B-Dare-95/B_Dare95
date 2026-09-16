# -*- coding: utf-8 -*-
__title__ = "Corner Guard Placer"
__doc__ = """Version = 1.1
_____________________________________________________________________
Description:
Places a non-hosted Corner Guard family at every free convex corner of
the picked columns (active document or linked model).

Corner detection runs off the real column footprint, so rotated and
non-rectangular columns are handled. Rotation is derived from each
corner's outward bisector, calibrated against the family's home
orientation (top-left corner at 0 degrees).

Corners obstructed by walls are detected and skipped - a corner buried
in a wall, or with a wall abutting either of its two faces, cannot take
a guard.

Corners are numbered in the column's own frame:
    1 = top-left, 2 = bottom-left, 3 = bottom-right, 4 = top-right
walking counter-clockwise, so the numbering follows the column when it
is rotated.

How to use:

1-Choose Active document or Linked model
2-Pick the guard family type and set the offsets
3-Pick one or more columns
4-Read the report in the pyRevit output window
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

from Autodesk.Revit.DB import (Element, Level, FamilySymbol,
                               FilteredElementCollector, BuiltInCategory,
                               Options, ViewDetailLevel, GeometryInstance,
                               Solid, PlanarFace, Line, CurveLoop, Plane,
                               ExtrusionAnalyzer, SolidUtils, Outline,
                               BoundingBoxIntersectsFilter,
                               GeometryCreationUtilities,
                               BooleanOperationsUtils, BooleanOperationsType,
                               Transaction, SubTransaction, XYZ,
                               ElementTransformUtils, RevitLinkInstance)
from Autodesk.Revit.DB.Structure import StructuralType
from Autodesk.Revit.UI import (TaskDialog, TaskDialogCommandLinkId,
                               TaskDialogCommonButtons, TaskDialogResult)
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType

from System import EventHandler
from System.Collections.Generic import List
from System.Windows.Markup import XamlReader
from System.Windows import RoutedEventHandler
from System.Windows.Controls import TextChangedEventHandler
from System.Windows.Threading import Dispatcher, DispatcherFrame

doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

# ─── Constants ────────────────────────────────────────────────────────────────

MM_TO_FT = 1.0 / 304.8

# Calibrated from a manual placement: at rotation 0 the guard occupies the
# top-left corner, so its outward bisector points up-left (135 degrees).
HOME_BISECTOR = XYZ(-1.0, 1.0, 0.0).Normalize()

DEFAULT_ANGLE_TOL_DEG = 5.0
DEFAULT_CLEARANCE_MM = 50.0
DEFAULT_PROBE_HEIGHT_MM = 1000.0

VEC_TOL = 1.0e-9
VERIFY_TOL_DEG = 5.0
MIN_VOLUME = 1.0e-6

COLUMN_BICS = [BuiltInCategory.OST_Columns,
               BuiltInCategory.OST_StructuralColumns]

OBSTRUCTION_BICS = [BuiltInCategory.OST_Walls]

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


def solid_base_z(solid):
    try:
        return solid.GetBoundingBox().Min.Z
    except Exception:
        return solid.ComputeCentroid().Z


# ─── Corner detection ─────────────────────────────────────────────────────────


def find_corners(segments, angle_tol_deg):
    """
    Classify every vertex of a CCW footprint loop.

    Returns the convex, near-90-degree corners in loop order, each carrying
    the corner point, its outward bisector, and both edge frames (needed
    later for the obstruction probes).
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
                        "t_in": t_in, "t_out": t_out,
                        "n_in": n_in, "n_out": n_out,
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


# ─── Obstruction detection ────────────────────────────────────────────────────


def outline_from_points(points, pad):
    """Axis-aligned Outline covering the points, expanded by pad."""
    xs = [p.X for p in points]
    ys = [p.Y for p in points]
    zs = [p.Z for p in points]
    lo = XYZ(min(xs) - pad, min(ys) - pad, min(zs) - pad)
    hi = XYZ(max(xs) + pad, max(ys) + pad, max(zs) + pad)
    return Outline(lo, hi)


def outline_corners(outline):
    lo, hi = outline.MinimumPoint, outline.MaximumPoint
    return [XYZ(x, y, z)
            for x in (lo.X, hi.X)
            for y in (lo.Y, hi.Y)
            for z in (lo.Z, hi.Z)]


def collect_obstruction_solids(probe_points, pad_ft):
    """
    Wall solids from the active document and every loaded link, in host
    coordinates, restricted to the neighbourhood of the probe points.

    Returns a list of (solid, bounding box) pairs.
    """
    if not probe_points:
        return []

    world_outline = outline_from_points(probe_points, pad_ft)

    sources = [(doc, None)]
    for link in FilteredElementCollector(doc).OfClass(RevitLinkInstance).ToElements():
        link_doc = link.GetLinkDocument()
        if link_doc is not None:
            sources.append((link_doc, link.GetTotalTransform()))

    results = []

    for source_doc, transform in sources:
        # Express the search box in the source document's own coordinates.
        if transform is None or transform.IsIdentity:
            local_outline = world_outline
        else:
            inverse = transform.Inverse
            local_pts = [inverse.OfPoint(p) for p in outline_corners(world_outline)]
            local_outline = outline_from_points(local_pts, 0.0)

        for bic in OBSTRUCTION_BICS:
            try:
                collector = FilteredElementCollector(source_doc) \
                    .OfCategory(bic) \
                    .WhereElementIsNotElementType() \
                    .WherePasses(BoundingBoxIntersectsFilter(local_outline))
            except Exception:
                continue

            for element in collector.ToElements():
                try:
                    for solid in element_solids(element, transform):
                        results.append((solid, solid.GetBoundingBox()))
                except Exception:
                    continue

    return results


def probe_cube(center, half):
    """Small axis-aligned cube used as the point-containment probe."""
    z0 = center.Z - half
    pts = [XYZ(center.X - half, center.Y - half, z0),
           XYZ(center.X + half, center.Y - half, z0),
           XYZ(center.X + half, center.Y + half, z0),
           XYZ(center.X - half, center.Y + half, z0)]

    loop = CurveLoop()
    for i in range(4):
        loop.Append(Line.CreateBound(pts[i], pts[(i + 1) % 4]))

    loops = List[CurveLoop]()
    loops.Add(loop)
    return GeometryCreationUtilities.CreateExtrusionGeometry(loops, XYZ.BasisZ,
                                                             2.0 * half)


def point_is_solid(point, obstruction_solids, half):
    """True if the probe cube around the point overlaps any obstruction solid."""
    try:
        cube = probe_cube(point, half)
    except Exception:
        return False

    for solid, bbox in obstruction_solids:
        # Cheap reject before the boolean.
        if bbox is not None:
            lo, hi = bbox.Min, bbox.Max
            if (point.X < lo.X - half or point.X > hi.X + half or
                    point.Y < lo.Y - half or point.Y > hi.Y + half or
                    point.Z < lo.Z - half or point.Z > hi.Z + half):
                continue
        try:
            hit = BooleanOperationsUtils.ExecuteBooleanOperation(
                cube, solid, BooleanOperationsType.Intersect)
            if hit is not None and hit.Volume > MIN_VOLUME:
                return True
        except Exception:
            continue

    return False


def corner_probe_points(corner, base_z, clearance_ft, probe_height_ft):
    """
    Three points that must all be clear for the guard to fit:
    one on the diagonal, one in front of each leg.
    """
    p = corner["point"]
    z = base_z + probe_height_ft
    origin = XYZ(p.X, p.Y, z)

    return [origin + corner["bisector"].Multiply(clearance_ft),
            origin + corner["t_out"].Multiply(clearance_ft)
                   + corner["n_out"].Multiply(clearance_ft),
            origin - corner["t_in"].Multiply(clearance_ft)
                   + corner["n_in"].Multiply(clearance_ft)]


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


# ─── Level lookup ─────────────────────────────────────────────────────────────


def build_level_table():
    levels = list(FilteredElementCollector(doc).OfClass(Level).ToElements())
    levels.sort(key=lambda lv: lv.Elevation)
    return levels


def nearest_level_below(levels, z):
    if not levels:
        return None
    chosen = levels[0]
    for level in levels:
        if level.Elevation <= z + 1.0e-6:
            chosen = level
        else:
            break
    return chosen


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


def instance_axis(instance):
    """
    Plan direction of the instance's own X axis, in world coordinates.

    Measuring the instance transform makes verification independent of where
    the family's material sits relative to its insertion point.
    """
    try:
        return flatten(instance.GetTransform().BasisX)
    except Exception:
        return None


# ─── UI ───────────────────────────────────────────────────────────────────────

XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Corner Guard Placer"
        Width="520" Height="700"
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
    </StackPanel>

    <StackPanel Grid.Row="1">

      <TextBlock Text="GUARD FAMILY TYPE" Style="{StaticResource LabelText}"/>
      <TextBox x:Name="TxtSearch" Margin="0,0,0,6"/>
      <ListBox x:Name="LstTypes" Height="230"/>
      <CheckBox x:Name="ChkAllCats" Content="Show all categories"/>

      <Grid Margin="0,4,0,0">
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="*"/>
          <ColumnDefinition Width="12"/>
          <ColumnDefinition Width="*"/>
        </Grid.ColumnDefinitions>
        <StackPanel Grid.Column="0">
          <TextBlock Text="OUTWARD OFFSET (MM)" Style="{StaticResource LabelText}"/>
          <TextBox x:Name="TxtOffset" Text="0"/>
        </StackPanel>
        <StackPanel Grid.Column="2">
          <TextBlock Text="HEIGHT ABOVE LEVEL (MM)" Style="{StaticResource LabelText}"/>
          <TextBox x:Name="TxtBaseZ" Text="0"/>
        </StackPanel>
      </Grid>

      <Grid Margin="0,4,0,0">
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="*"/>
          <ColumnDefinition Width="12"/>
          <ColumnDefinition Width="*"/>
        </Grid.ColumnDefinitions>
        <StackPanel Grid.Column="0">
          <TextBlock Text="CLEARANCE NEEDED (MM)" Style="{StaticResource LabelText}"/>
          <TextBox x:Name="TxtClearance" Text="50"/>
        </StackPanel>
        <StackPanel Grid.Column="2">
          <TextBlock Text="CHECK AT HEIGHT (MM)" Style="{StaticResource LabelText}"/>
          <TextBox x:Name="TxtProbeH" Text="1000"/>
        </StackPanel>
      </Grid>

      <CheckBox x:Name="ChkObstruct" Content="Skip corners obstructed by walls"
                IsChecked="True"/>
      <CheckBox x:Name="ChkVerify" Content="Verify rotation after placing"
                IsChecked="True"/>

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


def show_ui(from_link):
    """Carbon-themed modeless window. Returns a settings dict, or None."""
    window = XamlReader.Parse(XAML)

    txt_source = window.FindName("TxtSource")
    txt_search = window.FindName("TxtSearch")
    lst_types = window.FindName("LstTypes")
    chk_all_cats = window.FindName("ChkAllCats")
    txt_offset = window.FindName("TxtOffset")
    txt_base_z = window.FindName("TxtBaseZ")
    txt_clearance = window.FindName("TxtClearance")
    txt_probe_h = window.FindName("TxtProbeH")
    chk_obstruct = window.FindName("ChkObstruct")
    chk_verify = window.FindName("ChkVerify")
    btn_run = window.FindName("BtnRun")
    btn_cancel = window.FindName("BtnCancel")

    txt_source.Text = ("Source: linked model" if from_link
                       else "Source: active document")

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

    def parse_float(text, fallback):
        try:
            return float((text or "").strip())
        except Exception:
            return fallback

    def on_search(sender, args):
        apply_filter()

    def on_all_cats(sender, args):
        repopulate()

    def on_run(sender, args):
        symbol = selected_symbol()
        if symbol is None:
            txt_source.Text = "Pick a family type before running."
            return

        state["result"] = {
            "symbol": symbol,
            "linked": from_link,
            "offset_mm": parse_float(txt_offset.Text, 0.0),
            "base_z_mm": parse_float(txt_base_z.Text, 0.0),
            "clearance_mm": parse_float(txt_clearance.Text,
                                        DEFAULT_CLEARANCE_MM),
            "probe_h_mm": parse_float(txt_probe_h.Text,
                                      DEFAULT_PROBE_HEIGHT_MM),
            "obstruct": bool(chk_obstruct.IsChecked),
            "verify": bool(chk_verify.IsChecked)}
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

from_link = ask_source()
if from_link is None:
    sys.exit()

settings = show_ui(from_link)
if settings is None:
    sys.exit()

symbol = settings["symbol"]
offset_ft = settings["offset_mm"] * MM_TO_FT
base_z_ft = settings["base_z_mm"] * MM_TO_FT
clearance_ft = settings["clearance_mm"] * MM_TO_FT
probe_h_ft = settings["probe_h_mm"] * MM_TO_FT
angle_tol = DEFAULT_ANGLE_TOL_DEG

# Pick the columns after the window is gone so the pick prompt is visible.
try:
    columns = pick_linked_columns() if from_link else pick_host_columns()
except Exception:
    columns = []

if not columns:
    notify("Corner Guard Placer", "No columns picked. Script cancelled.")
    sys.exit()

levels = build_level_table()
if not levels:
    notify("Corner Guard Placer", "This project has no levels.")
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

    base_z = solid_base_z(solid)
    level = nearest_level_below(levels, base_z)

    for corner in corners:
        records.append({"label": label,
                        "method": method,
                        "index": corner["index"],
                        "local_deg": corner["local_deg"],
                        "interior": corner["interior"],
                        "corner": corner,
                        "base_z": base_z,
                        "level": level,
                        "bisector": corner["bisector"],
                        "angle": signed_angle_deg(HOME_BISECTOR,
                                                  corner["bisector"]),
                        "instance": None,
                        "axis0": None,
                        "status": "pending",
                        "note": ""})

if not records:
    reasons = "\n".join(["{} - {}".format(label, reason)
                         for label, reason in skipped_columns])
    notify("Corner Guard Placer",
           "No placeable corners found.\n\n{}".format(reasons))
    sys.exit()

# ─── Obstruction filter ───────────────────────────────────────────────────────

if settings["obstruct"]:
    all_probes = []
    for record in records:
        record["probes"] = corner_probe_points(record["corner"],
                                               record["base_z"],
                                               clearance_ft, probe_h_ft)
        all_probes.extend(record["probes"])

    obstruction_solids = collect_obstruction_solids(all_probes,
                                                    clearance_ft * 4.0)

    for record in records:
        blocked = False
        for probe in record["probes"]:
            if point_is_solid(probe, obstruction_solids, clearance_ft * 0.5):
                blocked = True
                break
        if blocked:
            record["status"] = "obstructed"
            record["note"] = "wall within clearance"

# The insertion point is the corner, lifted to the level (not the structural
# base of the column, which often sits below the floor).
for record in records:
    corner_pt = record["corner"]["point"]
    z = record["level"].Elevation + base_z_ft
    point = XYZ(corner_pt.X, corner_pt.Y, z)
    if offset_ft != 0.0:
        point = point + record["bisector"].Multiply(offset_ft)
    record["point"] = point

placeable = [r for r in records if r["status"] == "pending"]

if not placeable:
    notify("Corner Guard Placer",
           "Every candidate corner was obstructed.\n\n"
           "Lower the clearance value, or uncheck the obstruction filter.")
    sys.exit()

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

    # Pass 2 - snap onto the exact insertion point and record the starting
    # orientation, so verification measures the rotation itself.
    for record in placeable:
        if record["instance"] is None:
            continue
        try:
            snap_to_point(record["instance"], record["point"])
        except Exception as ex:
            record["note"] = "snap: {}".format(ex)
        record["axis0"] = instance_axis(record["instance"])

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

    # Pass 4 - verify the applied rotation against the requested one.
    if settings["verify"]:
        for record in placeable:
            if record["instance"] is None or record["status"] == "failed":
                continue
            axis1 = instance_axis(record["instance"])
            if record["axis0"] is None or axis1 is None:
                record["status"] = "unverified"
                record["note"] = "no transform to measure"
                continue
            applied = signed_angle_deg(record["axis0"], axis1)
            drift = angular_distance_deg(applied, record["angle"])
            record["note"] = "applied {:.1f} deg".format(applied)
            record["status"] = "ok" if drift <= VERIFY_TOL_DEG else "MISALIGNED"

    t.Commit()

except Exception as ex:
    t.RollBack()
    notify("Corner Guard Placer",
           "Run failed and was rolled back:\n\n{}".format(ex))
    raise

# ─── Summary ──────────────────────────────────────────────────────────────────

placed = len([r for r in records if r["instance"] is not None])
obstructed = len([r for r in records if r["status"] == "obstructed"])
bad = len([r for r in records if r["status"] in ("failed", "MISALIGNED")])

lines = ["{} guards placed on {} columns.".format(placed, len(by_column))]
if obstructed:
    lines.append("{} corners skipped as obstructed.".format(obstructed))
if skipped_columns:
    lines.append("{} columns skipped entirely.".format(len(skipped_columns)))
if bad:
    lines.append("{} guards failed or landed misaligned.".format(bad))

notify("Corner Guard Placer", "\n".join(lines))
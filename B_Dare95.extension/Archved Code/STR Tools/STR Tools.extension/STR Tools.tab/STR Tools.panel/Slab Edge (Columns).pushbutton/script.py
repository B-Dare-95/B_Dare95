# -*- coding: utf-8 -*-
"""
Floor Opener (Columns) - Cut openings in a floor around structural columns only.

Workflow:
    1. User selects a floor.
    2. User enters an offset value (in the document's length units).
    3. Script auto-detects all structural columns whose plan footprint
       intersects the floor's boundary at the same level.
    4. For each column, builds an oriented rectangle from the column's
       family symbol + instance transform, offsets it outward, and cuts
       it out of the floor as an opening.
    5. The floor is rebuilt in-place (same type, level, structural flag).

Notes / limitations:
    - Openings are rectangular, oriented to match the column's actual rotation
      via the FamilyInstance transform projected onto XY. Round columns get a
      rectangular opening enclosing their footprint.
    - Only columns whose plan + vertical bounding box intersects the floor are
      considered (different-level columns on the same grid are excluded).
    - The floor is deleted and recreated via Floor.Create (SketchEditScope is
      fragile in IronPython - this is intentional, not an oversight).

IronPython 2.7 constraints respected throughout.
"""

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')
clr.AddReference('System.Xml')

from Autodesk.Revit.DB import (
    Transaction, BuiltInCategory, ElementId, XYZ, Line, CurveLoop,
    Floor, FloorType, Level, BoundingBoxXYZ, Outline, BoundingBoxIntersectsFilter,
    FilteredElementCollector, ElementCategoryFilter, LogicalOrFilter,
    Wall, FamilyInstance, ElementMulticategoryFilter,
    GeometryCreationUtilities, BooleanOperationsUtils, BooleanOperationsType,
    PlanarFace, Solid
)
from Autodesk.Revit.UI import TaskDialog, TaskDialogCommonButtons, TaskDialogResult
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter

from System.Windows import Window, Application, RoutedEventHandler
from System.Windows.Markup import XamlReader
from System.Windows.Threading import Dispatcher, DispatcherFrame
from System import EventHandler
from System.Collections.Generic import List

import traceback


doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
app = __revit__.Application


# ---------------------------------------------------------------------------
# Compatibility helpers
# ---------------------------------------------------------------------------

def _eid_str(element_id):
    """ElementId -> string, compatible across Revit versions.
    Revit 2024+ removed IntegerValue in favor of Value (Int64)."""
    try:
        return str(element_id.Value)
    except AttributeError:
        return str(element_id.IntegerValue)


def push_frame_show(window):
    """Show a WPF window modeless-but-blocking, keeping Revit responsive
    via Dispatcher.PushFrame instead of ShowDialog()."""
    frame = DispatcherFrame()

    def _on_closed(sender, args):
        frame.Continue = False

    window.Closed += EventHandler(_on_closed)
    window.Show()
    Dispatcher.PushFrame(frame)


# ---------------------------------------------------------------------------
# Selection filter - restrict picking to Floor elements only
# ---------------------------------------------------------------------------

class FloorSelectionFilter(ISelectionFilter):
    def AllowElement(self, element):
        return isinstance(element, Floor)

    def AllowReference(self, reference, position):
        return True


# ---------------------------------------------------------------------------
# Offset value prompt - Catppuccin Mocha themed WPF dialog
# ---------------------------------------------------------------------------

OFFSET_DIALOG_XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Floor Opener - Offset"
        Width="380" SizeToContent="Height"
        WindowStartupLocation="CenterScreen"
        ResizeMode="NoResize"
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
                        <Border Background="{TemplateBinding Background}"
                                CornerRadius="6">
                            <ContentPresenter HorizontalAlignment="Center"
                                               VerticalAlignment="Center"/>
                        </Border>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>
        <Style x:Key="CancelButton" TargetType="Button" BasedOn="{StaticResource RoundButton}">
            <Setter Property="Background" Value="#45475A"/>
            <Setter Property="Foreground" Value="#CDD6F4"/>
        </Style>
        <Style x:Key="RoundTextBox" TargetType="TextBox">
            <Setter Property="Background" Value="#313244"/>
            <Setter Property="Foreground" Value="#CDD6F4"/>
            <Setter Property="BorderBrush" Value="#45475A"/>
            <Setter Property="BorderThickness" Value="1"/>
            <Setter Property="Padding" Value="8,6"/>
            <Setter Property="FontSize" Value="14"/>
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
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <TextBlock Grid.Row="0" Text="Opening Offset"
                   Foreground="#CDD6F4" FontSize="18" FontWeight="Bold"
                   Margin="0,0,0,4"/>
        <TextBlock Grid.Row="1" Text="Distance to offset openings outward from each structural column footprint."
                   Foreground="#A6ADC8" FontSize="12" TextWrapping="Wrap"
                   Margin="0,0,0,14"/>

        <Grid Grid.Row="2">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="Auto"/>
            </Grid.ColumnDefinitions>
            <TextBox x:Name="OffsetBox" Grid.Column="0" Style="{StaticResource RoundTextBox}" Text="0.5"/>
            <TextBlock x:Name="UnitsLabel" Grid.Column="1" Text="ft"
                       Foreground="#A6ADC8" VerticalAlignment="Center" Margin="8,0,0,0"/>
        </Grid>

        <TextBlock x:Name="ErrorText" Grid.Row="3" Foreground="#F38BA8"
                   FontSize="11" Margin="0,8,0,0" TextWrapping="Wrap" Text=""/>

        <StackPanel Grid.Row="4" Orientation="Horizontal" HorizontalAlignment="Right" Margin="0,16,0,0">
            <Button x:Name="CancelBtn" Content="Cancel" Width="80" Height="32"
                    Style="{StaticResource CancelButton}" Margin="0,0,8,0"/>
            <Button x:Name="OkBtn" Content="Create Openings" Width="140" Height="32"
                    Style="{StaticResource RoundButton}"/>
        </StackPanel>
    </Grid>
</Window>
"""


class OffsetPromptResult(object):
    def __init__(self):
        self.offset_value = None
        self.confirmed = False


def show_offset_prompt(units_label_text):
    """Shows the offset entry dialog. Returns OffsetPromptResult."""
    result = OffsetPromptResult()

    window = XamlReader.Parse(OFFSET_DIALOG_XAML)
    offset_box = window.FindName("OffsetBox")
    units_label = window.FindName("UnitsLabel")
    error_text = window.FindName("ErrorText")
    ok_btn = window.FindName("OkBtn")
    cancel_btn = window.FindName("CancelBtn")

    units_label.Text = units_label_text

    def on_ok(sender, args):
        raw = offset_box.Text.strip()
        try:
            val = float(raw)
        except ValueError:
            error_text.Text = "Enter a valid number."
            return
        if val <= 0:
            error_text.Text = "Offset must be greater than zero."
            return
        result.offset_value = val
        result.confirmed = True
        window.Close()

    def on_cancel(sender, args):
        result.confirmed = False
        window.Close()

    ok_btn.Click += RoutedEventHandler(on_ok)
    cancel_btn.Click += RoutedEventHandler(on_cancel)

    push_frame_show(window)
    return result


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def get_floor_outer_loops(floor):
    """Returns the floor's boundary as a list of CurveLoop, taken from its sketch.
    Floor.GetProfile() / Floor.GetSketch() varies slightly by version, so this
    pulls boundary curves via the floor's geometry sketch profile."""
    sketch_id = floor.SketchId
    if sketch_id is None or sketch_id == ElementId.InvalidElementId:
        raise Exception("Selected floor has no editable sketch (cannot read its profile).")

    sketch = doc.GetElement(sketch_id)
    profile = sketch.Profile  # CurveArrArray - one CurveArray per loop (outer + any existing inner holes)

    loops = []
    for curve_array in profile:
        loop = CurveLoop()
        for curve in curve_array:
            loop.Append(curve)
        loops.append(loop)
    return loops


def is_outer_loop(loop, all_loops):
    """The outer loop is the one with the largest enclosed area (simple heuristic)."""
    # CurveLoop doesn't expose area directly pre-2022 in all builds; use bounding
    # box diagonal as a fast proxy for "largest" since floor outer boundary is
    # virtually always the biggest extent.
    max_extent = -1.0
    outer = loop
    for lp in all_loops:
        bbox_min = XYZ(1e9, 1e9, 1e9)
        bbox_max = XYZ(-1e9, -1e9, -1e9)
        for curve in lp:
            for pt in (curve.GetEndPoint(0), curve.GetEndPoint(1)):
                bbox_min = XYZ(min(bbox_min.X, pt.X), min(bbox_min.Y, pt.Y), 0)
                bbox_max = XYZ(max(bbox_max.X, pt.X), max(bbox_max.Y, pt.Y), 0)
        extent = bbox_min.DistanceTo(bbox_max)
        if extent > max_extent:
            max_extent = extent
            outer = lp
    return outer


def plan_bbox_from_element(element, z_level):
    """Returns (min_x, min_y, max_x, max_y) of the element's bounding box, flattened to plan.
    Used ONLY for the cheap broad-phase intersection test - not for building the
    actual opening shape (see get_oriented_footprint for that)."""
    bbox = element.get_BoundingBox(None)
    if bbox is None:
        return None
    return (bbox.Min.X, bbox.Min.Y, bbox.Max.X, bbox.Max.Y)


def axis_aligned_rect_corners(min_x, min_y, max_x, max_y, offset):
    """Returns 4 corner XYZ (z=0, set by caller) of an axis-aligned rectangle
    expanded outward by `offset`. Order: CCW starting bottom-left."""
    min_x -= offset
    min_y -= offset
    max_x += offset
    max_y += offset
    return [
        XYZ(min_x, min_y, 0),
        XYZ(max_x, min_y, 0),
        XYZ(max_x, max_y, 0),
        XYZ(min_x, max_y, 0),
    ]


def rect_loop_from_corners(corners, z, ccw=True):
    """Builds a CurveLoop from 4 corner points (XY only used, Z overridden)."""
    pts = [XYZ(c.X, c.Y, z) for c in corners]
    if not ccw:
        pts = [pts[0], pts[3], pts[2], pts[1]]
    loop = CurveLoop()
    for i in range(4):
        start = pts[i]
        end = pts[(i + 1) % 4]
        loop.Append(Line.CreateBound(start, end))
    return loop


def get_wall_footprint_corners(wall, offset):
    """Returns 4 corner XYZ (CCW, z=0) of a wall's plan footprint rectangle,
    expanded outward by `offset`, oriented to match the wall's actual direction.

    Built from the wall's location curve (centerline) + wall width, so this is
    EXACT for straight walls at any rotation angle. Returns None for non-Line
    location curves (arcs/splines) so the caller can fall back to bounding box.
    """
    loc = wall.Location
    if loc is None or not hasattr(loc, "Curve"):
        return None

    curve = loc.Curve
    if not isinstance(curve, Line):
        return None  # curved wall - caller falls back to bbox

    p0 = curve.GetEndPoint(0)
    p1 = curve.GetEndPoint(1)

    direction = (p1 - p0).Normalize()
    # Perpendicular in plan (rotate direction 90 degrees about Z)
    perp = XYZ(-direction.Y, direction.X, 0).Normalize()

    half_width = wall.Width / 2.0
    extend = offset  # extend the rectangle lengthwise by the offset too,
                      # so the opening clears the wall ends, not just its sides

    p0_ext = p0 - direction.Multiply(extend)
    p1_ext = p1 + direction.Multiply(extend)

    half_total = half_width + offset

    c1 = p0_ext + perp.Multiply(half_total)
    c2 = p1_ext + perp.Multiply(half_total)
    c3 = p1_ext - perp.Multiply(half_total)
    c4 = p0_ext - perp.Multiply(half_total)

    return [
        XYZ(c1.X, c1.Y, 0),
        XYZ(c2.X, c2.Y, 0),
        XYZ(c3.X, c3.Y, 0),
        XYZ(c4.X, c4.Y, 0),
    ]


def get_column_footprint_corners(column, offset):
    """Returns 4 corner XYZ (CCW, z=0) of a structural column's plan footprint
    rectangle, expanded outward by `offset`, oriented to match the column's
    actual rotation.

    IMPORTANT: column.get_BoundingBox(None) returns a WORLD-SPACE axis-aligned
    box. For a rotated column that box is already bloated to enclose the
    rotated shape - transforming ITS corners back through the inverse
    transform does NOT recover the tight local footprint, it just produces a
    rotated parallelogram from an already-wrong box. Instead, this pulls the
    bounding box from the column's FAMILY SYMBOL, which is defined in the
    family's own local coordinate space and is therefore genuinely
    axis-aligned to the unrotated geometry.

    FIX (some structural families, e.g. slanted/tilted columns or families
    whose local axes aren't aligned the "normal" way): pushing local corner
    points through the FULL 3D instance transform can yield points that are
    no longer coplanar once flattened to Z=0 - for some families this
    collapses or twists the rectangle into a degenerate/self-intersecting
    shape, which is exactly what makes Floor.Create reject the whole profile
    with "loops intersect / not closed / not planar". Instead of transforming
    points through the full 3D transform, this projects the transform's BasisX
    and BasisY onto the XY plane FIRST, builds an honest flat rectangle from
    those projected axes, and only then places it at the transform's origin.
    This guarantees a planar, non-degenerate rectangle in plan no matter how
    the source family is tilted or oriented.
    """
    symbol = column.Symbol
    if symbol is None:
        return None

    symbol_bbox = symbol.get_BoundingBox(None)
    if symbol_bbox is None:
        return None

    transform = column.GetTransform()

    local_min_x = min(symbol_bbox.Min.X, symbol_bbox.Max.X) - offset
    local_max_x = max(symbol_bbox.Min.X, symbol_bbox.Max.X) + offset
    local_min_y = min(symbol_bbox.Min.Y, symbol_bbox.Max.Y) - offset
    local_max_y = max(symbol_bbox.Min.Y, symbol_bbox.Max.Y) + offset

    # Project the instance's local X/Y axes flat onto the XY plane. This is
    # what keeps the result planar even when the column (or its family's
    # local frame) is tilted out of vertical.
    basis_x_flat = XYZ(transform.BasisX.X, transform.BasisX.Y, 0)
    basis_y_flat = XYZ(transform.BasisY.X, transform.BasisY.Y, 0)

    # Degenerate case: column is perfectly vertical/axial such that its local
    # X or Y axis has (almost) no XY component once flattened (e.g. a column
    # family modeled with its "width" axis along world Z). Fall back to bbox
    # in this case rather than risk a zero-length rectangle side.
    if basis_x_flat.GetLength() < 1e-6 or basis_y_flat.GetLength() < 1e-6:
        return None

    basis_x_flat = basis_x_flat.Normalize()
    basis_y_flat = basis_y_flat.Normalize()

    origin_flat = XYZ(transform.Origin.X, transform.Origin.Y, 0)

    # Build the rectangle in world space directly from the flattened axes,
    # rather than transforming local points through the 3D transform.
    corners_local_2d = [
        (local_min_x, local_min_y),
        (local_max_x, local_min_y),
        (local_max_x, local_max_y),
        (local_min_x, local_max_y),
    ]

    world_corners = []
    for lx, ly in corners_local_2d:
        pt = origin_flat + basis_x_flat.Multiply(lx) + basis_y_flat.Multiply(ly)
        world_corners.append(XYZ(pt.X, pt.Y, 0))

    return world_corners


def rectangle_is_valid(corners, min_area=1e-6):
    """Sanity-check a 4-point rectangle before it's handed to Floor.Create:
    rejects degenerate (near-zero area), duplicate-point, or self-intersecting
    quads. This is the safety net - one bad column/wall should never blow up
    the entire floor rebuild (mirrors the defensive pattern used in the linked
    Column Guard script: skip the bad element, keep going, report it)."""
    if corners is None or len(corners) != 4:
        return False

    # Reject duplicate/near-duplicate consecutive points
    for i in range(4):
        p1 = corners[i]
        p2 = corners[(i + 1) % 4]
        if p1.DistanceTo(p2) < 1e-6:
            return False

    # Shoelace formula for signed area in plan - near-zero means collapsed
    area = 0.0
    for i in range(4):
        x1, y1 = corners[i].X, corners[i].Y
        x2, y2 = corners[(i + 1) % 4].X, corners[(i + 1) % 4].Y
        area += (x1 * y2) - (x2 * y1)
    area = abs(area) / 2.0

    return area > min_area


def _loop_to_points(curve_loop):
    """Extracts ordered XYZ points from a CurveLoop (one per curve start point)."""
    return [curve.GetEndPoint(0) for curve in curve_loop]


def rectangles_overlap(loop_a, loop_b):
    """Tests whether two (possibly rotated) rectangular CurveLoops overlap in
    plan, using the Separating Axis Theorem: two convex polygons do NOT
    overlap if and only if there exists an axis (perpendicular to one of
    either polygon's edges) along which their projections don't overlap.
    Correct for rotated rectangles, unlike a plain bounding-box check."""
    pts_a = _loop_to_points(loop_a)
    pts_b = _loop_to_points(loop_b)

    def edges(pts):
        return [(pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts))]

    def project(pts, axis_x, axis_y):
        dots = [p.X * axis_x + p.Y * axis_y for p in pts]
        return min(dots), max(dots)

    for pts in (pts_a, pts_b):
        for p1, p2 in edges(pts):
            edge_x = p2.X - p1.X
            edge_y = p2.Y - p1.Y
            # Perpendicular axis (normal to this edge), in-plane only
            axis_x, axis_y = -edge_y, edge_x
            length = (axis_x ** 2 + axis_y ** 2) ** 0.5
            if length < 1e-9:
                continue
            axis_x /= length
            axis_y /= length

            min_a, max_a = project(pts_a, axis_x, axis_y)
            min_b, max_b = project(pts_b, axis_x, axis_y)

            if max_a < min_b - 1e-6 or max_b < min_a - 1e-6:
                return False  # found a separating axis - no overlap

    return True  # no separating axis found on any edge normal - they overlap


def group_overlapping_loops(loops):
    """Groups indices of `loops` into clusters of mutually-connected overlap
    (union-find / connected-components over the pairwise overlap graph).

    This matters because overlap is not always pairwise-isolated: e.g. a
    column embedded in a wall, where ANOTHER column nearby also touches that
    same wall's opening - all three need to merge into ONE combined opening,
    not just the first pair found. Returns a list of lists of indices.
    """
    n = len(loops)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    for i in range(n):
        for j in range(i + 1, n):
            if rectangles_overlap(loops[i], loops[j]):
                union(i, j)

    clusters = {}
    for i in range(n):
        root = find(i)
        clusters.setdefault(root, []).append(i)

    return list(clusters.values())


def merge_overlapping_loops(loops_in_cluster, z, extrusion_height=1.0):
    """Merges 2+ overlapping/touching rectangular CurveLoops into a single
    combined CurveLoop, via solid boolean union.

    Why this exists: a column embedded in (or hard against) a wall is normal,
    expected geometry - their offset opening rectangles legitimately overlap.
    Floor.Create rejects ANY profile where hole loops intersect each other, so
    those openings must be merged into one continuous opening BEFORE being
    handed to Floor.Create, rather than treated as an error.

    Approach: extrude each rectangle into a thin solid (Revit has no direct
    2D polygon union API), boolean-union all the solids together, then pull
    the boundary of the resulting solid's top face back out as a CurveLoop.
    extrusion_height is arbitrary (1 ft) - only used as scratch geometry, never
    placed in the model.

    Returns a list of CurveLoop (normally one, but a union CAN produce more
    than one disjoint loop if, after merging, an island remains - extremely
    unlikely for compact column/wall rectangles, but handled defensively).
    Returns None if the boolean operation fails for any reason - caller should
    fall back to treating the cluster as a hard error in that case.
    """
    try:
        solids = []
        for loop in loops_in_cluster:
            flat_loop = CurveLoop()
            for curve in loop:
                p0 = curve.GetEndPoint(0)
                p1 = curve.GetEndPoint(1)
                flat_loop.Append(Line.CreateBound(
                    XYZ(p0.X, p0.Y, z), XYZ(p1.X, p1.Y, z)
                ))
            solid = GeometryCreationUtilities.CreateExtrusionGeometry(
                List[CurveLoop]([flat_loop]), XYZ.BasisZ, extrusion_height
            )
            solids.append(solid)

        union_solid = solids[0]
        for next_solid in solids[1:]:
            union_solid = BooleanOperationsUtils.ExecuteBooleanOperation(
                union_solid, next_solid, BooleanOperationsType.Union
            )

        # Find the top horizontal face(s) of the unioned solid - these carry
        # the merged plan footprint boundary as their edge loops. Don't break
        # after the first match: a union of several rectangles can in theory
        # produce more than one coplanar top face, and missing one would
        # silently drop part of the merged opening.
        result_loops = []
        for face in union_solid.Faces:
            planar_face = face if isinstance(face, PlanarFace) else None
            if planar_face is None:
                continue
            if planar_face.FaceNormal.Z < 0.9:
                continue  # only top-facing faces, not sides/bottom
            for edge_loop in planar_face.GetEdgesAsCurveLoops():
                result_loops.append(edge_loop)

        if not result_loops:
            return None
        return result_loops

    except Exception:
        return None


def get_oriented_footprint(element, offset):
    """Dispatches to the correct oriented-footprint builder based on element
    type. Returns (corners, used_fallback_bbox) where corners is a list of 4
    XYZ (CCW, z=0), or (None, False) if the element can't be processed at all.
    """
    if isinstance(element, Wall):
        corners = get_wall_footprint_corners(element, offset)
        if corners is not None:
            return corners, False
        # curved wall - fall back to bbox
        bbox = plan_bbox_from_element(element, None)
        if bbox is None:
            return None, False
        min_x, min_y, max_x, max_y = bbox
        return axis_aligned_rect_corners(min_x, min_y, max_x, max_y, offset), True

    if isinstance(element, FamilyInstance):
        corners = get_column_footprint_corners(element, offset)
        if corners is not None:
            return corners, False
        bbox = plan_bbox_from_element(element, None)
        if bbox is None:
            return None, False
        min_x, min_y, max_x, max_y = bbox
        return axis_aligned_rect_corners(min_x, min_y, max_x, max_y, offset), True

    # Unknown type - bbox fallback
    bbox = plan_bbox_from_element(element, None)
    if bbox is None:
        return None, False
    min_x, min_y, max_x, max_y = bbox
    return axis_aligned_rect_corners(min_x, min_y, max_x, max_y, offset), True


def loops_intersect_bbox(floor_bbox, element_bbox):
    """Cheap broad-phase plan-rectangle intersection test."""
    f_min_x, f_min_y, f_max_x, f_max_y = floor_bbox
    e_min_x, e_min_y, e_max_x, e_max_y = element_bbox
    return not (e_max_x < f_min_x or e_min_x > f_max_x or
                e_max_y < f_min_y or e_min_y > f_max_y)


# ---------------------------------------------------------------------------
# Element collection - structural columns + walls intersecting the floor
# ---------------------------------------------------------------------------

def collect_candidate_elements(floor_bbox, floor_z_min, floor_z_max, z_tolerance=0.1):
    """Collects structural columns whose plan (XY) bounding box intersects the
    floor's plan bounding box AND whose vertical (Z) extent touches the floor."""
    cat_filter = ElementCategoryFilter(BuiltInCategory.OST_StructuralColumns)

    collector = FilteredElementCollector(doc) \
        .WherePasses(cat_filter) \
        .WhereElementIsNotElementType()

    z_min_check = floor_z_min - z_tolerance
    z_max_check = floor_z_max + z_tolerance

    matches = []
    for el in collector:
        bbox = el.get_BoundingBox(None)
        if bbox is None:
            continue

        # Vertical (Z) overlap test - excludes elements on other levels that
        # merely happen to share the same XY plan position.
        if bbox.Max.Z < z_min_check or bbox.Min.Z > z_max_check:
            continue

        el_bbox = (bbox.Min.X, bbox.Min.Y, bbox.Max.X, bbox.Max.Y)
        if loops_intersect_bbox(floor_bbox, el_bbox):
            matches.append(el)
    return matches


# ---------------------------------------------------------------------------
# Main routine
# ---------------------------------------------------------------------------

def main():
    # --- 1. Pick floor ---
    try:
        ref = uidoc.Selection.PickObject(
            ObjectType.Element,
            FloorSelectionFilter(),
            "Select a floor to open around structural columns"
        )
    except Exception:
        return  # user cancelled pick

    floor = doc.GetElement(ref.ElementId)
    if not isinstance(floor, Floor):
        TaskDialog.Show("Floor Opener", "Selected element is not a floor.")
        return

    # --- 2. Determine display units label (simple ft/mm heuristic) ---
    units_label = "ft"
    try:
        length_unit = doc.GetUnits().GetFormatOptions(
            __import__('Autodesk.Revit.DB', fromlist=['SpecTypeId']).SpecTypeId.Length
        ).GetUnitTypeId()
        unit_name = length_unit.TypeId
        if "millimeter" in unit_name:
            units_label = "mm"
        elif "meter" in unit_name and "milli" not in unit_name:
            units_label = "m"
        elif "inch" in unit_name:
            units_label = "in"
    except Exception:
        pass  # fall back to "ft" label; internal units are always feet regardless of display

    # --- 3. Prompt for offset value ---
    prompt_result = show_offset_prompt(units_label)
    if not prompt_result.confirmed:
        return

    # NOTE: Revit internal units are always decimal feet. If the user's display
    # units are mm/m/in, the entered number is interpreted in THOSE units and
    # converted to feet here. This avoids surprising 10x/1000x mistakes.
    offset_value_internal = prompt_result.offset_value
    if units_label == "mm":
        offset_value_internal = prompt_result.offset_value / 304.8
    elif units_label == "m":
        offset_value_internal = prompt_result.offset_value / 0.3048
    elif units_label == "in":
        offset_value_internal = prompt_result.offset_value / 12.0
    # "ft" needs no conversion

    if offset_value_internal <= 0:
        TaskDialog.Show("Floor Opener", "Offset must be greater than zero.")
        return

    # --- 4. Read floor boundary + level/type info before any modification ---
    try:
        all_loops = get_floor_outer_loops(floor)
    except Exception as ex:
        TaskDialog.Show("Floor Opener", "Could not read floor sketch:\n" + str(ex))
        return

    if not all_loops:
        TaskDialog.Show("Floor Opener", "Floor has no boundary loops to work with.")
        return

    outer_loop = is_outer_loop(all_loops[0], all_loops)

    floor_type_id = floor.GetTypeId()
    level_id = floor.LevelId
    level = doc.GetElement(level_id)
    level_elevation = level.Elevation

    floor_bbox_obj = floor.get_BoundingBox(None)
    if floor_bbox_obj is None:
        TaskDialog.Show("Floor Opener", "Could not determine floor extents.")
        return
    floor_bbox = (floor_bbox_obj.Min.X, floor_bbox_obj.Min.Y,
                  floor_bbox_obj.Max.X, floor_bbox_obj.Max.Y)
    floor_z_min = floor_bbox_obj.Min.Z
    floor_z_max = floor_bbox_obj.Max.Z

    is_structural = False
    try:
        is_structural = floor.IsStructural
    except Exception:
        pass

    # --- 5. Find intersecting columns/walls ---
    # Z-range is passed so elements on a different level that merely share
    # the same XY footprint (e.g. a column directly above/below, same grid
    # position) are correctly excluded - see collect_candidate_elements docstring.
    candidates = collect_candidate_elements(floor_bbox, floor_z_min, floor_z_max)
    # Exclude the floor itself from candidates (defensive, shouldn't occur since
    # categories differ, but cheap to guard against double-processing).
    candidates = [c for c in candidates if _eid_str(c.Id) != _eid_str(floor.Id)]

    if not candidates:
        TaskDialog.Show(
            "Floor Opener",
            "No structural columns were found intersecting this floor's footprint. "
            "No openings created."
        )
        return

    # --- 6. Build offset rectangle loops for each candidate (holes) ---
    # Each hole is built from the element's ACTUAL orientation (wall centerline
    # direction, or column instance transform) rather than an axis-aligned
    # bounding box, so rotated columns/walls get correctly rotated openings.
    #
    # SAFETY NET: every rectangle is validated (non-degenerate, non-zero area,
    # no duplicate points) BEFORE being handed to Floor.Create. Some structural
    # column families produce a corner set that collapses or self-intersects
    # once flattened to plan; without this check, ONE bad column would make
    # Floor.Create reject the entire profile (all holes included) with a
    # generic "loops intersect / not closed / not planar" error. Bad elements
    # are skipped individually and reported in the summary instead - mirrors
    # the defensive "skip and report, don't blow up the whole run" pattern.
    hole_loops = []
    hole_owner_ids = []  # parallel list - which element each hole_loops entry came from
    skipped = []
    fallback_bbox_used = []
    for el in candidates:
        corners, used_fallback = get_oriented_footprint(el, offset_value_internal)
        if corners is None:
            skipped.append(_eid_str(el.Id))
            continue
        if not rectangle_is_valid(corners):
            skipped.append(_eid_str(el.Id) + " (degenerate footprint)")
            continue
        if used_fallback:
            fallback_bbox_used.append(_eid_str(el.Id))
        try:
            hole = rect_loop_from_corners(
                corners, level_elevation,
                ccw=False  # holes wound opposite to outer loop
            )
            hole_loops.append(hole)
            hole_owner_ids.append(_eid_str(el.Id))
        except Exception:
            skipped.append(_eid_str(el.Id) + " (curve loop build failed)")

    if not hole_loops:
        TaskDialog.Show("Floor Opener", "No valid openings could be generated.")
        return

    # --- 6b. Merge overlapping hole rectangles into combined openings.
    # A column embedded in or hard against a wall is NORMAL real-world
    # geometry - their offset rectangles legitimately overlap, and that is
    # not an error condition. Floor.Create rejects any profile where hole
    # loops intersect each other, so overlapping clusters are merged into one
    # continuous opening (via solid boolean union) before being handed to
    # Floor.Create, rather than stopping the whole operation.
    clusters = group_overlapping_loops(hole_loops)

    final_hole_loops = []
    merged_groups_report = []
    merge_failures = []

    for cluster_indices in clusters:
        if len(cluster_indices) == 1:
            final_hole_loops.append(hole_loops[cluster_indices[0]])
            continue

        cluster_loops = [hole_loops[i] for i in cluster_indices]
        cluster_owner_ids = [hole_owner_ids[i] for i in cluster_indices]

        merged = merge_overlapping_loops(cluster_loops, level_elevation)
        if merged is None:
            # Could not merge (boolean op failed) - fall back to reporting
            # this as a conflict rather than silently dropping the openings.
            merge_failures.append(cluster_owner_ids)
            continue

        # merge_overlapping_loops returns CCW-wound boundary loops (the
        # natural winding of a solid's top face); hole loops need the
        # opposite winding from the outer floor boundary, so reverse them.
        for loop in merged:
            reversed_loop = CurveLoop()
            curves_list = list(loop)
            for curve in reversed(curves_list):
                reversed_loop.Append(curve.CreateReversed())
            final_hole_loops.append(reversed_loop)

        merged_groups_report.append(cluster_owner_ids)

    if merge_failures:
        fail_text = "\n".join(
            "  - " + ", ".join(ids) for ids in merge_failures
        )
        TaskDialog.Show(
            "Floor Opener",
            "Could not automatically merge {0} group(s) of overlapping openings "
            "(geometry too complex to combine automatically):\n\n{1}\n\n"
            "Try a smaller offset value, or exclude one of the conflicting elements.".format(
                len(merge_failures), fail_text
            )
        )
        return

    hole_loops = final_hole_loops

    if not hole_loops:
        TaskDialog.Show("Floor Opener", "No valid openings could be generated.")
        return

    # --- 7. Rebuild the floor: delete old, create new with outer + hole loops ---
    t = Transaction(doc, "Open Floor Around Structural Columns")
    t.Start()
    try:
        profile_loops = List[CurveLoop]()
        profile_loops.Add(outer_loop)
        for hole in hole_loops:
            profile_loops.Add(hole)

        doc.Delete(floor.Id)

        new_floor = Floor.Create(doc, profile_loops, floor_type_id, level_id)

        try:
            new_floor.IsStructural = is_structural
        except Exception:
            pass

        t.Commit()
    except Exception as ex:
        t.RollBack()
        TaskDialog.Show(
            "Floor Opener",
            "Failed to rebuild floor with openings:\n" + str(ex) + "\n\n" + traceback.format_exc()
        )
        return

    # --- 8. Summary ---
    msg = "Created {0} opening(s) around detected structural columns.".format(len(hole_loops))
    if merged_groups_report:
        merge_text = "\n".join(
            "  - " + ", ".join(ids) for ids in merged_groups_report
        )
        msg += ("\n\n{0} group(s) of touching/overlapping elements were merged "
                "into a single combined opening:\n{1}").format(
            len(merged_groups_report), merge_text
        )
    if fallback_bbox_used:
        msg += ("\n\n{0} element(s) used an axis-aligned bounding-box opening "
                "instead of an exact oriented footprint (typically curved walls "
                "or columns with no readable transform): {1}").format(
            len(fallback_bbox_used), ", ".join(fallback_bbox_used)
        )
    if skipped:
        msg += "\n\nSkipped {0} element(s) with unreadable geometry: {1}".format(
            len(skipped), ", ".join(skipped)
        )
    TaskDialog.Show("Floor Opener - Done", msg)


main()
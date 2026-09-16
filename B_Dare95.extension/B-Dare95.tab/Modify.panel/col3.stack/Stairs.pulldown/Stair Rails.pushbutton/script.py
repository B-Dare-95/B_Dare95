# -*- coding: utf-8 -*-
"""Stair Railing Manager

Pick a Stairs element, choose a Railing Type for the inner side and another for
the outer side, and generate the railings from the runs' footprint geometry.

  Inner side : one single continuous open path chaining the inner edge of every
               run, with straight connectors across the landings.
  Outer side : one separate railing per run, following that run's outer edge.

The path is taken exactly off the run's footprint edge and then offset by a
user supplied value in millimetres (positive = inset towards the treads,
negative = pushed away from the stair).
"""

__title__ = "Stair\nRailings"
__author__ = "Mohamed Bedair"
__doc__ = "Create inner / outer railings on a selected stair from a menu of railing types."

import clr

clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")
clr.AddReference("System.Xml")

from System import EventHandler
from System.Collections.Generic import List
from System.Windows import RoutedEventHandler
from System.Windows.Controls import SelectionChangedEventHandler, TextChangedEventHandler
from System.Windows.Markup import XamlReader
from System.Windows.Threading import Dispatcher, DispatcherFrame

from Autodesk.Revit.DB import (
    CurveLoop,
    Element,
    ElementId,
    GeometryInstance,
    Options,
    Solid,
    ViewDetailLevel,
    FilteredElementCollector,
    Level,
    Line,
    Transaction,
    Transform,
    UnitTypeId,
    UnitUtils,
    XYZ,
)
from Autodesk.Revit.DB.Architecture import (
    MultistoryStairs,
    Railing,
    RailingType,
    Stairs,
)
from Autodesk.Revit.UI import TaskDialog
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException

doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

# --------------------------------------------------------------------------- #
# tolerances (all internal units = decimal feet)
# --------------------------------------------------------------------------- #

JOIN_TOL = 0.0015          # ~0.5 mm, used to decide if two endpoints coincide
SHORT_CURVE = 1.0 / 32.0   # Revit's shortest allowed curve, ~0.79 mm
PARALLEL_DOT = 0.60        # |dot| above this means "runs along the stair path"


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #

def eid_value(element_id):
    """ElementId.Value on Revit 2025+, ElementId.IntegerValue before that."""
    try:
        return element_id.Value
    except AttributeError:
        return element_id.IntegerValue


def element_name(element):
    """Element.Name is redeclared on ElementType, so IronPython cannot bind it on
    an instance. Read it through the reflected property on the class instead."""
    try:
        return Element.Name.GetValue(element)
    except Exception:
        pass
    try:
        return element.get_Name()
    except Exception:
        return "<unnamed>"


def mm_to_ft(value_mm):
    return UnitUtils.ConvertToInternalUnits(value_mm, UnitTypeId.Millimeters)


def loop_curves(curve_loop):
    """CurveLoop -> plain python list of Curve."""
    return [c for c in curve_loop]


def loop_points(curve_loop):
    """Every tessellation point of a CurveLoop, as a python list."""
    pts = []
    for crv in curve_loop:
        for p in crv.Tessellate():
            pts.append(p)
    return pts


def average_point(points):
    if not points:
        return None
    sx = 0.0
    sy = 0.0
    sz = 0.0
    for p in points:
        sx += p.X
        sy += p.Y
        sz += p.Z
    n = float(len(points))
    return XYZ(sx / n, sy / n, sz / n)


def plan_distance(a, b):
    """Distance ignoring Z - everything we compare lives on one horizontal plane."""
    dx = a.X - b.X
    dy = a.Y - b.Y
    return (dx * dx + dy * dy) ** 0.5


def curve_midpoint(crv):
    return crv.Evaluate(0.5, True)


def curve_tangent(crv, normalized_param=0.5):
    der = crv.ComputeDerivatives(normalized_param, True)
    vec = der.BasisX
    if vec.GetLength() < 1e-9:
        return XYZ.BasisX
    return vec.Normalize()


def flatten_curve(crv, z_value):
    """Force a curve onto the horizontal plane at z_value (lines and arcs only)."""
    pts = [crv.GetEndPoint(0), crv.GetEndPoint(1)]
    if abs(pts[0].Z - z_value) < 1e-9 and abs(pts[1].Z - z_value) < 1e-9:
        return crv
    translation = XYZ(0, 0, z_value - pts[0].Z)
    return crv.CreateTransformed(Transform.CreateTranslation(translation))


def chain_curves(curves):
    """Greedily order a bag of curves into one connected chain, reversing where needed.

    Returns the chain as a list. Curves that could not be attached are dropped -
    the caller gets whatever formed one continuous run.
    """
    if not curves:
        return []

    remaining = list(curves)
    chain = [remaining.pop(0)]

    grew = True
    while remaining and grew:
        grew = False
        head = chain[0].GetEndPoint(0)
        tail = chain[-1].GetEndPoint(1)
        for i in range(len(remaining)):
            crv = remaining[i]
            p0 = crv.GetEndPoint(0)
            p1 = crv.GetEndPoint(1)
            if plan_distance(p0, tail) < JOIN_TOL:
                chain.append(crv)
            elif plan_distance(p1, tail) < JOIN_TOL:
                chain.append(crv.CreateReversed())
            elif plan_distance(p1, head) < JOIN_TOL:
                chain.insert(0, crv)
            elif plan_distance(p0, head) < JOIN_TOL:
                chain.insert(0, crv.CreateReversed())
            else:
                continue
            remaining.pop(i)
            grew = True
            break

    return chain


def reverse_chain(chain):
    return [c.CreateReversed() for c in reversed(chain)]


def build_curve_loop(curves):
    """Append curves into a CurveLoop, bridging any tiny gaps with straight lines."""
    cl = CurveLoop()
    previous_end = None
    for crv in curves:
        if previous_end is not None:
            gap = plan_distance(previous_end, crv.GetEndPoint(0))
            if SHORT_CURVE <= gap:
                cl.Append(Line.CreateBound(previous_end, crv.GetEndPoint(0)))
            elif JOIN_TOL < gap < SHORT_CURVE:
                # too small for Revit to accept as its own curve - snap instead
                crv = Line.CreateBound(previous_end, crv.GetEndPoint(1)) \
                    if crv.GetEndPoint(0).DistanceTo(crv.GetEndPoint(1)) > SHORT_CURVE else crv
        cl.Append(crv)
        previous_end = crv.GetEndPoint(1)
    return cl


# --------------------------------------------------------------------------- #
# stair geometry analysis
# --------------------------------------------------------------------------- #

def nearest_path_data(path_curves, point):
    """Project a point onto the stair path. Returns (projected_point, tangent) or None."""
    best = None
    for pcrv in path_curves:
        try:
            projection = pcrv.Project(point)
        except Exception:
            projection = None
        if projection is None:
            continue
        dist = plan_distance(projection.XYZPoint, point)
        if best is None or dist < best[0]:
            best = (dist, pcrv, projection)

    if best is None:
        return None

    _, path_curve, projection = best
    derivatives = path_curve.ComputeDerivatives(projection.Parameter, False)
    tangent = derivatives.BasisX
    if tangent.GetLength() < 1e-9:
        return None
    return projection.XYZPoint, tangent.Normalize()


def collect_solid_points(geometry, points):
    """Every tessellated edge point of the solids inside a GeometryElement."""
    for obj in geometry:
        if isinstance(obj, Solid):
            if obj.Volume < 1e-9:
                continue
            for edge in obj.Edges:
                for pt in edge.Tessellate():
                    points.append(pt)
        elif isinstance(obj, GeometryInstance):
            collect_solid_points(obj.GetInstanceGeometry(), points)


def run_up_vector(run):
    """Plan direction pointing from the bottom of a run towards its top.

    The footprint and the stairs path are both flattened onto the base level, so
    neither carries the climb direction. The run's own solid does: its lowest and
    highest points sit at opposite ends of the flight.
    """
    options = Options()
    options.ComputeReferences = False
    options.IncludeNonVisibleObjects = False
    options.DetailLevel = ViewDetailLevel.Medium

    points = []
    try:
        geometry = run.get_Geometry(options)
        if geometry is not None:
            collect_solid_points(geometry, points)
    except Exception:
        points = []

    if len(points) >= 2:
        low = points[0]
        high = points[0]
        for pt in points:
            if pt.Z < low.Z:
                low = pt
            if pt.Z > high.Z:
                high = pt
        vector = XYZ(high.X - low.X, high.Y - low.Y, 0.0)
        if vector.GetLength() > 1e-6:
            return vector.Normalize()

    # fallback: the stairs path as Revit stores it, which reads bottom to top
    try:
        path = loop_curves(run.GetStairsPath())
    except Exception:
        return None
    if not path:
        return None
    vector = path[-1].GetEndPoint(1) - path[0].GetEndPoint(0)
    vector = XYZ(vector.X, vector.Y, 0.0)
    if vector.GetLength() < 1e-6:
        return None
    return vector.Normalize()


def orient_along(chain, direction):
    """Reverse a chain if it runs against the given plan direction."""
    if not chain or direction is None:
        return chain
    span = chain[-1].GetEndPoint(1) - chain[0].GetEndPoint(0)
    if span.X * direction.X + span.Y * direction.Y < 0:
        return reverse_chain(chain)
    return chain


def split_run_edges(run):
    """Split a run's footprint into its two long sides.

    Returns a dict with 'side_a' / 'side_b' (lists of curves), 'centroid' and 'z'.
    The two sides are separated by which hand of the stair path they sit on, so
    winder / spiral runs with several segments per side still group correctly.
    """
    footprint = run.GetFootprintBoundary()
    path_curves = loop_curves(run.GetStairsPath())
    if not path_curves:
        return None

    pts = loop_points(footprint)
    if not pts:
        return None

    info = {
        "side_a": [],
        "side_b": [],
        "centroid": average_point(pts),
        "z": pts[0].Z,
    }

    for crv in footprint:
        mid = curve_midpoint(crv)
        near = nearest_path_data(path_curves, mid)
        if near is None:
            continue
        proj_pt, path_tan = near

        # riser ends run across the path - skip them, we only want the long sides
        if abs(curve_tangent(crv).DotProduct(path_tan)) < PARALLEL_DOT:
            continue

        offset_vec = mid - proj_pt
        hand = path_tan.CrossProduct(offset_vec).Z
        if hand >= 0:
            info["side_a"].append(crv)
        else:
            info["side_b"].append(crv)

    if not info["side_a"] or not info["side_b"]:
        return None

    up_vector = run_up_vector(run)
    info["side_a"] = orient_along(chain_curves(info["side_a"]), up_vector)
    info["side_b"] = orient_along(chain_curves(info["side_b"]), up_vector)
    return info


def stair_centroid(stairs):
    """Centroid of the whole stair footprint - runs plus landings."""
    pts = []
    for rid in stairs.GetStairsRuns():
        run = doc.GetElement(rid)
        if run is None:
            continue
        try:
            pts.extend(loop_points(run.GetFootprintBoundary()))
        except Exception:
            pass
    for lid in stairs.GetStairsLandings():
        landing = doc.GetElement(lid)
        if landing is None:
            continue
        try:
            pts.extend(loop_points(landing.GetFootprintBoundary()))
        except Exception:
            pass
    return average_point(pts)


def analyse_stairs(stairs):
    """Return an ordered list of per-run dicts: run, inner chain, outer chain, centroid."""
    run_ids = list(stairs.GetStairsRuns())
    runs = []
    for rid in run_ids:
        run = doc.GetElement(rid)
        if run is not None:
            runs.append(run)

    runs.sort(key=lambda r: r.BaseElevation)

    global_centre = stair_centroid(stairs)
    analysed = []
    skipped = []

    for run in runs:
        edges = split_run_edges(run)
        if edges is None:
            skipped.append(run)
            continue

        def side_distance(curves):
            total = 0.0
            for crv in curves:
                total += plan_distance(curve_midpoint(crv), global_centre)
            return total / float(len(curves))

        d_a = side_distance(edges["side_a"])
        d_b = side_distance(edges["side_b"])

        if d_a <= d_b:
            inner, outer = edges["side_a"], edges["side_b"]
        else:
            inner, outer = edges["side_b"], edges["side_a"]

        analysed.append({
            "run": run,
            "inner": inner,
            "outer": outer,
            "centroid": edges["centroid"],
            "z": edges["z"],
        })

    return analysed, skipped


def orient_inner_sequence(analysed):
    """Orient each run's inner chain so the whole set reads as one continuous line."""
    chains = [dict(item) for item in analysed]
    if not chains:
        return chains

    if len(chains) > 1:
        first = chains[0]["inner"]
        second = chains[1]["inner"]
        second_pts = [second[0].GetEndPoint(0), second[-1].GetEndPoint(1)]
        start_gap = min(plan_distance(first[0].GetEndPoint(0), p) for p in second_pts)
        end_gap = min(plan_distance(first[-1].GetEndPoint(1), p) for p in second_pts)
        if start_gap < end_gap:
            chains[0]["inner"] = reverse_chain(first)

    for i in range(1, len(chains)):
        previous_end = chains[i - 1]["inner"][-1].GetEndPoint(1)
        current = chains[i]["inner"]
        if plan_distance(current[-1].GetEndPoint(1), previous_end) < \
           plan_distance(current[0].GetEndPoint(0), previous_end):
            chains[i]["inner"] = reverse_chain(current)

    return chains


# --------------------------------------------------------------------------- #
# landing connectors
# --------------------------------------------------------------------------- #

LANDING_SNAP = 0.15   # ~45 mm, how close a run edge end must sit to a landing edge


def landing_boundaries(stairs):
    """[(landing element, ordered list of boundary curves)] for every landing."""
    found = []
    for lid in stairs.GetStairsLandings():
        landing = doc.GetElement(lid)
        if landing is None:
            continue
        try:
            curves = chain_curves(loop_curves(landing.GetFootprintBoundary()))
        except Exception:
            continue
        if curves:
            found.append((landing, curves))
    return found


def locate_on_boundary(curves, point):
    """(distance, curve index, raw parameter) of the closest spot on a boundary."""
    best = None
    for index in range(len(curves)):
        try:
            projection = curves[index].Project(point)
        except Exception:
            projection = None
        if projection is None:
            continue
        dist = plan_distance(projection.XYZPoint, point)
        if best is None or dist < best[0]:
            best = (dist, index, projection.Parameter)
    return best


def trim_curve(curve, start_param, end_param):
    """A bounded copy of a curve between two raw parameters, or None if degenerate."""
    if end_param - start_param < 1e-9:
        return None
    piece = curve.Clone()
    piece.MakeBound(start_param, end_param)
    if piece.Length < SHORT_CURVE:
        return None
    return piece


def walk_boundary(curves, from_index, from_param, to_index, to_param):
    """Walk a closed boundary forwards from one spot to another, trimming both ends."""
    count = len(curves)
    pieces = []

    if from_index == to_index and to_param > from_param:
        piece = trim_curve(curves[from_index], from_param, to_param)
        return [piece] if piece is not None else []

    piece = trim_curve(curves[from_index], from_param, curves[from_index].GetEndParameter(1))
    if piece is not None:
        pieces.append(piece)

    index = (from_index + 1) % count
    guard = 0
    while index != to_index and guard <= count:
        pieces.append(curves[index])
        index = (index + 1) % count
        guard += 1

    piece = trim_curve(curves[to_index], curves[to_index].GetEndParameter(0), to_param)
    if piece is not None:
        pieces.append(piece)

    return pieces


def path_length(curves):
    total = 0.0
    for crv in curves:
        total += crv.Length
    return total


def landing_connector(landings, start_point, end_point, notes):
    """The stretch of landing boundary joining two run edges.

    Falls back to a straight line when no landing carries both points, which keeps
    the railing continuous even on odd stair layouts.
    """
    best = None
    for landing, curves in landings:
        from_hit = locate_on_boundary(curves, start_point)
        to_hit = locate_on_boundary(curves, end_point)
        if from_hit is None or to_hit is None:
            continue
        if from_hit[0] > LANDING_SNAP or to_hit[0] > LANDING_SNAP:
            continue
        score = from_hit[0] + to_hit[0]
        if best is None or score < best[0]:
            best = (score, landing, curves, from_hit, to_hit)

    if best is None:
        notes.append("No landing found between two runs - joined them with a straight line.")
        return [Line.CreateBound(start_point, end_point)]

    _, landing, curves, from_hit, to_hit = best

    forward = walk_boundary(curves, from_hit[1], from_hit[2], to_hit[1], to_hit[2])
    backward = walk_boundary(curves, to_hit[1], to_hit[2], from_hit[1], from_hit[2])
    backward = reverse_chain(backward) if backward else []

    candidates = [c for c in (forward, backward) if c]
    if not candidates:
        return [Line.CreateBound(start_point, end_point)]

    # the way round that hugs the landing corner is always the short one; the other
    # lap runs the full outside perimeter of the landing
    candidates.sort(key=path_length)
    bridge = candidates[0]

    # tie the trimmed ends back onto the run edges exactly
    stitched = []
    lead_gap = plan_distance(start_point, bridge[0].GetEndPoint(0))
    if lead_gap >= SHORT_CURVE:
        stitched.append(Line.CreateBound(start_point, bridge[0].GetEndPoint(0)))
    stitched.extend(bridge)
    tail_gap = plan_distance(bridge[-1].GetEndPoint(1), end_point)
    if tail_gap >= SHORT_CURVE:
        stitched.append(Line.CreateBound(bridge[-1].GetEndPoint(1), end_point))

    return stitched


# --------------------------------------------------------------------------- #
# offsetting
# --------------------------------------------------------------------------- #

def offset_loop(curve_loop, distance_ft, towards_point):
    """Offset a path so it moves towards towards_point by distance_ft.

    Tries CurveLoop.CreateViaOffset first (it trims/extends the joints properly);
    falls back to per curve Curve.CreateOffset with straight bridges if that fails.
    """
    if abs(distance_ft) < 1e-9:
        return curve_loop, None

    reference = curve_midpoint(loop_curves(curve_loop)[0])
    base_distance = plan_distance(reference, towards_point)

    best = None
    for sign in (1.0, -1.0):
        try:
            candidate = CurveLoop.CreateViaOffset(curve_loop, sign * distance_ft, XYZ.BasisZ)
        except Exception:
            continue
        curves = loop_curves(candidate)
        if not curves:
            continue
        moved = plan_distance(curve_midpoint(curves[0]), towards_point)
        if best is None or moved < best[0]:
            best = (moved, candidate)

    if best is not None and best[0] < base_distance:
        return best[1], None

    # fallback: offset every curve on its own, then re-chain
    for sign in (1.0, -1.0):
        pieces = []
        ok = True
        for crv in loop_curves(curve_loop):
            try:
                pieces.append(crv.CreateOffset(sign * distance_ft, XYZ.BasisZ))
            except Exception:
                ok = False
                break
        if not ok or not pieces:
            continue
        moved = plan_distance(curve_midpoint(pieces[0]), towards_point)
        if moved < base_distance:
            return build_curve_loop(pieces), "offset applied per segment"

    return curve_loop, "offset could not be applied, path left on the edge"


# --------------------------------------------------------------------------- #
# level lookup
# --------------------------------------------------------------------------- #

def level_for_elevation(elevation):
    """The Level whose elevation is closest to the footprint plane."""
    levels = FilteredElementCollector(doc).OfClass(Level).WhereElementIsNotElementType()
    best = None
    for lvl in levels:
        gap = abs(lvl.Elevation - elevation)
        if best is None or gap < best[0]:
            best = (gap, lvl)
    if best is None:
        return ElementId.InvalidElementId
    return best[1].Id


# --------------------------------------------------------------------------- #
# railing types
# --------------------------------------------------------------------------- #

def collect_railing_types():
    """[(display name, ElementId)] sorted by name."""
    collector = FilteredElementCollector(doc).OfClass(RailingType).WhereElementIsElementType()
    items = []
    for rtype in collector:
        try:
            family = rtype.FamilyName
        except Exception:
            family = "Railing"
        items.append(("{0} : {1}".format(family, element_name(rtype)), rtype.Id))
    items.sort(key=lambda pair: pair[0].lower())
    return items


def railings_on_stairs(stairs):
    """Every railing sitting on this stair.

    Stairs.GetAssociatedRailings only reports railings tied to the stair boundaries,
    so railings sketched onto it (including the ones this tool creates) are picked up
    separately by matching their HostId against the stair and its components.
    """
    host_ids = set()
    host_ids.add(eid_value(stairs.Id))
    for rid in stairs.GetStairsRuns():
        host_ids.add(eid_value(rid))
    for lid in stairs.GetStairsLandings():
        host_ids.add(eid_value(lid))

    found = List[ElementId]()
    seen = set()

    for rid in stairs.GetAssociatedRailings():
        if eid_value(rid) not in seen:
            seen.add(eid_value(rid))
            found.Add(rid)

    collector = FilteredElementCollector(doc).OfClass(Railing).WhereElementIsNotElementType()
    for railing in collector:
        try:
            if not railing.HasHost:
                continue
            if eid_value(railing.HostId) not in host_ids:
                continue
        except Exception:
            continue
        if eid_value(railing.Id) not in seen:
            seen.add(eid_value(railing.Id))
            found.Add(railing.Id)

    return found


# --------------------------------------------------------------------------- #
# user interface
# --------------------------------------------------------------------------- #

XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Stair Railing Manager"
        Height="720" Width="840" MinHeight="640" MinWidth="740"
        WindowStartupLocation="CenterScreen"
        Background="#161616" FontFamily="Segoe UI">
  <Window.Resources>
    <Style TargetType="TextBlock">
      <Setter Property="Foreground" Value="#F4F4F4"/>
    </Style>
    <Style TargetType="CheckBox">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Margin" Value="0,4,0,4"/>
    </Style>
    <Style TargetType="TextBox">
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="BorderBrush" Value="#525252"/>
      <Setter Property="BorderThickness" Value="1"/>
      <Setter Property="Padding" Value="5,4,5,4"/>
      <Setter Property="CaretBrush" Value="#F1C21B"/>
    </Style>
    <Style TargetType="ListBox">
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="BorderBrush" Value="#525252"/>
      <Setter Property="BorderThickness" Value="1"/>
    </Style>
    <Style x:Key="CardStyle" TargetType="Border">
      <Setter Property="Background" Value="#262626"/>
      <Setter Property="CornerRadius" Value="6"/>
      <Setter Property="Padding" Value="12"/>
    </Style>
    <Style x:Key="AccentButton" TargetType="Button">
      <Setter Property="Foreground" Value="#161616"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border Background="#F1C21B" CornerRadius="5" Padding="18,8,18,8">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style x:Key="GhostButton" TargetType="Button">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border Background="#525252" CornerRadius="5" Padding="18,8,18,8">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
  </Window.Resources>

  <Grid Margin="16">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <StackPanel Grid.Row="0" Margin="0,0,0,12">
      <TextBlock Text="Stair Railing Manager" FontSize="18" FontWeight="SemiBold"/>
      <TextBlock x:Name="SubtitleText" Foreground="#A8A8A8" FontSize="12" Margin="0,3,0,0"/>
    </StackPanel>

    <Grid Grid.Row="1">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="14"/>
        <ColumnDefinition Width="*"/>
      </Grid.ColumnDefinitions>

      <Border Grid.Column="0" Style="{StaticResource CardStyle}">
        <Grid>
          <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
          </Grid.RowDefinitions>
          <CheckBox x:Name="InnerEnabled" Grid.Row="0" IsChecked="True"
                    FontWeight="SemiBold" Content="Inner side - one continuous railing"/>
          <TextBlock Grid.Row="1" Foreground="#A8A8A8" FontSize="11" TextWrapping="Wrap"
                     Margin="0,0,0,8"
                     Text="Chains the inner edge of every run into a single open path."/>
          <TextBox x:Name="InnerSearch" Grid.Row="2" Margin="0,0,0,6"/>
          <ListBox x:Name="InnerList" Grid.Row="3"/>
          <StackPanel Grid.Row="4" Orientation="Horizontal" Margin="0,9,0,0">
            <TextBlock Text="Inner offset (mm)" FontSize="11" VerticalAlignment="Center"
                       Margin="0,0,8,0"/>
            <TextBox x:Name="InnerOffset" Text="0" Width="72"/>
          </StackPanel>
        </Grid>
      </Border>

      <Border Grid.Column="2" Style="{StaticResource CardStyle}">
        <Grid>
          <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
          </Grid.RowDefinitions>
          <CheckBox x:Name="OuterEnabled" Grid.Row="0" IsChecked="True"
                    FontWeight="SemiBold" Content="Outer side - one railing per run"/>
          <TextBlock Grid.Row="1" Foreground="#A8A8A8" FontSize="11" TextWrapping="Wrap"
                     Margin="0,0,0,8"
                     Text="Each run gets its own separate railing on its outer edge."/>
          <TextBox x:Name="OuterSearch" Grid.Row="2" Margin="0,0,0,6"/>
          <ListBox x:Name="OuterList" Grid.Row="3"/>
          <StackPanel Grid.Row="4" Orientation="Horizontal" Margin="0,9,0,0">
            <TextBlock Text="Outer offset (mm)" FontSize="11" VerticalAlignment="Center"
                       Margin="0,0,8,0"/>
            <TextBox x:Name="OuterOffset" Text="0" Width="72"/>
          </StackPanel>
        </Grid>
      </Border>
    </Grid>

    <Border Grid.Row="2" Style="{StaticResource CardStyle}" Margin="0,14,0,0">
      <Grid>
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="Auto"/>
          <ColumnDefinition Width="*"/>
        </Grid.ColumnDefinitions>

        <!-- plan of a switchback stair: which edge is inner, which is outer -->
        <Canvas Grid.Column="0" Width="206" Height="100" Margin="0,0,20,0">
          <Rectangle Canvas.Left="8"  Canvas.Top="6"  Width="104" Height="22"
                     Fill="#393939" Stroke="#525252" StrokeThickness="1"/>
          <Rectangle Canvas.Left="8"  Canvas.Top="28" Width="42"  Height="62"
                     Fill="#393939" Stroke="#525252" StrokeThickness="1"/>
          <Rectangle Canvas.Left="70" Canvas.Top="28" Width="42"  Height="62"
                     Fill="#393939" Stroke="#525252" StrokeThickness="1"/>

          <Line X1="8" Y1="40" X2="50" Y2="40" Stroke="#525252" StrokeThickness="1"/>
          <Line X1="8" Y1="52" X2="50" Y2="52" Stroke="#525252" StrokeThickness="1"/>
          <Line X1="8" Y1="64" X2="50" Y2="64" Stroke="#525252" StrokeThickness="1"/>
          <Line X1="8" Y1="76" X2="50" Y2="76" Stroke="#525252" StrokeThickness="1"/>
          <Line X1="70" Y1="40" X2="112" Y2="40" Stroke="#525252" StrokeThickness="1"/>
          <Line X1="70" Y1="52" X2="112" Y2="52" Stroke="#525252" StrokeThickness="1"/>
          <Line X1="70" Y1="64" X2="112" Y2="64" Stroke="#525252" StrokeThickness="1"/>
          <Line X1="70" Y1="76" X2="112" Y2="76" Stroke="#525252" StrokeThickness="1"/>

          <Polyline Points="50,90 50,28 70,28 70,90" Stroke="#F1C21B" StrokeThickness="2.5"
                    StrokeLineJoin="Round" Fill="Transparent"/>
          <Line X1="8"   Y1="90" X2="8"   Y2="28" Stroke="#78A9FF" StrokeThickness="2.5"/>
          <Line X1="112" Y1="90" X2="112" Y2="28" Stroke="#78A9FF" StrokeThickness="2.5"/>

          <Line X1="126" Y1="34" X2="146" Y2="34" Stroke="#F1C21B" StrokeThickness="2.5"/>
          <TextBlock Canvas.Left="152" Canvas.Top="27" FontSize="11" Foreground="#F4F4F4"
                     Text="Inner"/>
          <Line X1="126" Y1="58" X2="146" Y2="58" Stroke="#78A9FF" StrokeThickness="2.5"/>
          <TextBlock Canvas.Left="152" Canvas.Top="51" FontSize="11" Foreground="#F4F4F4"
                     Text="Outer"/>
          <TextBlock Canvas.Left="126" Canvas.Top="74" FontSize="10" Foreground="#A8A8A8"
                     Text="plan view"/>
        </Canvas>

        <StackPanel Grid.Column="1" VerticalAlignment="Center">
          <CheckBox x:Name="DeleteExisting" Content="Delete existing railings on the selected stairs"/>
          <CheckBox x:Name="HostToRun" IsChecked="True"
                    Content="Host each outer railing on its own run (single-storey only)"/>
          <CheckBox x:Name="FlipOuter" Content="Flip the outer railings"/>
          <TextBlock Foreground="#A8A8A8" FontSize="11" Margin="0,8,0,0" TextWrapping="Wrap"
                     Text="Offsets are in mm, positive = inwards onto the tread."/>
        </StackPanel>
      </Grid>
    </Border>

    <StackPanel Grid.Row="3" Orientation="Horizontal" HorizontalAlignment="Right" Margin="0,14,0,0">
      <TextBlock x:Name="StatusText" Foreground="#A8A8A8" FontSize="11"
                 VerticalAlignment="Center" Margin="0,0,14,0"/>
      <Button x:Name="CancelButton" Style="{StaticResource GhostButton}" Content="Cancel" Margin="0,0,10,0"/>
      <Button x:Name="CreateButton" Style="{StaticResource AccentButton}" Content="Create Railings"/>
    </StackPanel>
  </Grid>
</Window>
"""


class RailingDialog(object):
    """Blocking WPF dialog driven by Dispatcher.PushFrame."""

    def __init__(self, subtitle, railing_types):
        self.window = XamlReader.Parse(XAML)
        self.types = railing_types
        self.result = None
        self._frame = [None]

        self.window.FindName("SubtitleText").Text = subtitle

        self.inner_list = self.window.FindName("InnerList")
        self.outer_list = self.window.FindName("OuterList")
        self.inner_search = self.window.FindName("InnerSearch")
        self.outer_search = self.window.FindName("OuterSearch")
        self.inner_enabled = self.window.FindName("InnerEnabled")
        self.outer_enabled = self.window.FindName("OuterEnabled")
        self.inner_offset = self.window.FindName("InnerOffset")
        self.outer_offset = self.window.FindName("OuterOffset")
        self.delete_existing = self.window.FindName("DeleteExisting")
        self.host_to_run = self.window.FindName("HostToRun")
        self.flip_outer = self.window.FindName("FlipOuter")
        self.status = self.window.FindName("StatusText")

        self._inner_choice = [None]
        self._outer_choice = [None]

        names = [pair[0] for pair in self.types]
        self.inner_list.ItemsSource = names
        self.outer_list.ItemsSource = names

        self.inner_search.TextChanged += TextChangedEventHandler(self.on_inner_search)
        self.outer_search.TextChanged += TextChangedEventHandler(self.on_outer_search)
        self.inner_list.SelectionChanged += SelectionChangedEventHandler(self.on_inner_pick)
        self.outer_list.SelectionChanged += SelectionChangedEventHandler(self.on_outer_pick)

        self.window.FindName("CreateButton").Click += RoutedEventHandler(self.on_create)
        self.window.FindName("CancelButton").Click += RoutedEventHandler(self.on_cancel)
        self.window.Closed += EventHandler(self.on_closed)

    # -- filtering ---------------------------------------------------------- #

    def _filter(self, list_box, text, choice):
        needle = (text or "").strip().lower()
        if needle:
            names = [pair[0] for pair in self.types if needle in pair[0].lower()]
        else:
            names = [pair[0] for pair in self.types]
        list_box.ItemsSource = names
        if choice[0] is not None and choice[0] in names:
            list_box.SelectedItem = choice[0]

    def on_inner_search(self, sender, args):
        self._filter(self.inner_list, sender.Text, self._inner_choice)

    def on_outer_search(self, sender, args):
        self._filter(self.outer_list, sender.Text, self._outer_choice)

    def on_inner_pick(self, sender, args):
        if sender.SelectedItem is not None:
            self._inner_choice[0] = sender.SelectedItem

    def on_outer_pick(self, sender, args):
        if sender.SelectedItem is not None:
            self._outer_choice[0] = sender.SelectedItem

    # -- buttons ------------------------------------------------------------ #

    def _type_id(self, display_name):
        for name, type_id in self.types:
            if name == display_name:
                return type_id
        return None

    def on_create(self, sender, args):
        do_inner = bool(self.inner_enabled.IsChecked)
        do_outer = bool(self.outer_enabled.IsChecked)

        if not do_inner and not do_outer:
            self.status.Text = "Enable at least one side."
            return
        if do_inner and self._inner_choice[0] is None:
            self.status.Text = "Pick a railing type for the inner side."
            return
        if do_outer and self._outer_choice[0] is None:
            self.status.Text = "Pick a railing type for the outer side."
            return

        offsets = {}
        for side, box, enabled in (("inner", self.inner_offset, do_inner),
                                   ("outer", self.outer_offset, do_outer)):
            if not enabled:
                offsets[side] = 0.0
                continue
            try:
                offsets[side] = float((box.Text or "0").strip())
            except ValueError:
                self.status.Text = "The {0} offset must be a number in mm.".format(side)
                return

        self.result = {
            "do_inner": do_inner,
            "do_outer": do_outer,
            "inner_type": self._type_id(self._inner_choice[0]) if do_inner else None,
            "outer_type": self._type_id(self._outer_choice[0]) if do_outer else None,
            "offset_inner_mm": offsets["inner"],
            "offset_outer_mm": offsets["outer"],
            "delete_existing": bool(self.delete_existing.IsChecked),
            "host_to_run": bool(self.host_to_run.IsChecked),
            "flip_outer": bool(self.flip_outer.IsChecked),
        }
        self.window.Close()

    def on_cancel(self, sender, args):
        self.result = None
        self.window.Close()

    def on_closed(self, sender, args):
        if self._frame[0] is not None:
            self._frame[0].Continue = False

    def show(self):
        self.window.Show()
        frame = DispatcherFrame()
        self._frame[0] = frame
        Dispatcher.PushFrame(frame)
        return self.result


# --------------------------------------------------------------------------- #
# selection
# --------------------------------------------------------------------------- #

class StairsSelectionFilter(ISelectionFilter):
    def AllowElement(self, element):
        return isinstance(element, Stairs) or isinstance(element, MultistoryStairs)

    def AllowReference(self, reference, position):
        return False


def expand_target(element, targets, seen):
    """Turn a picked element into one or more (stairs, multistory) work items.

    A MultistoryStairs holds several Stairs elements, each of which may itself be
    repeated over a range of levels, so it fans out into one item per member stair.
    """
    if isinstance(element, MultistoryStairs):
        for sid in element.GetAllStairsIds():
            stairs = doc.GetElement(sid)
            if not isinstance(stairs, Stairs):
                continue
            key = eid_value(stairs.Id)
            if key in seen:
                continue
            seen.add(key)
            targets.append((stairs, element))
        return

    if isinstance(element, Stairs):
        key = eid_value(element.Id)
        if key in seen:
            return
        seen.add(key)
        multistory = None
        try:
            parent_id = element.MultistoryStairsId
            if parent_id is not None and parent_id != ElementId.InvalidElementId:
                parent = doc.GetElement(parent_id)
                if isinstance(parent, MultistoryStairs):
                    multistory = parent
        except Exception:
            multistory = None
        targets.append((element, multistory))


def gather_targets():
    """[(Stairs, MultistoryStairs or None)] from the selection, or from a pick."""
    targets = []
    seen = set()

    for eid in uidoc.Selection.GetElementIds():
        expand_target(doc.GetElement(eid), targets, seen)

    if targets:
        return targets

    try:
        references = uidoc.Selection.PickObjects(
            ObjectType.Element,
            StairsSelectionFilter(),
            "Select one or more stairs, then press Finish",
        )
    except OperationCanceledException:
        return []
    if references is None:
        return []

    for reference in references:
        expand_target(doc.GetElement(reference.ElementId), targets, seen)

    return targets


# --------------------------------------------------------------------------- #
# creation
# --------------------------------------------------------------------------- #

def make_railing(curves, type_id, level_id, host_id, offset_ft, towards_point, notes,
                 placement_levels=None):
    """Build one railing from an ordered chain of curves. Returns the Railing or None."""
    if not curves:
        return None

    z_plane = curves[0].GetEndPoint(0).Z
    flat = [flatten_curve(c, z_plane) for c in curves]

    try:
        path = build_curve_loop(flat)
    except Exception as err:
        notes.append("Could not assemble the path: {0}".format(err))
        return None

    path, offset_note = offset_loop(path, offset_ft, towards_point)
    if offset_note:
        notes.append(offset_note)

    if not Railing.IsValidPathForRailing(path):
        notes.append("Revit rejected the path (it must be one open, connected line).")
        return None

    railing = Railing.Create(doc, path, type_id, level_id)
    if railing is None:
        notes.append("Railing.Create returned nothing.")
        return None

    doc.Regenerate()

    if host_id is not None and host_id != ElementId.InvalidElementId:
        try:
            if railing.RailingCanBeHostedByElement(host_id):
                railing.HostId = host_id
                doc.Regenerate()
            else:
                notes.append("Railing {0} could not be hosted on the stair.".format(
                    eid_value(railing.Id)))
        except Exception as err:
            notes.append("Hosting failed for railing {0}: {1}".format(
                eid_value(railing.Id), err))

    if placement_levels is not None:
        try:
            railing.SetMultistoryStairsPlacementLevels(placement_levels)
            doc.Regenerate()
        except Exception as err:
            notes.append("Could not spread railing {0} over the storeys: {1}".format(
                eid_value(railing.Id), err))

    return railing


def flip_railing(railing, notes):
    """Swap which side of its path the railing sits on. Not the sketch direction."""
    try:
        railing.Flip()
        doc.Regenerate()
    except Exception as err:
        notes.append("Could not flip railing {0}: {1}".format(eid_value(railing.Id), err))


def build_for_stairs(stairs, multistory, choice, offsets, notes, created):
    """Do the whole job for one Stairs element. Assumes an open transaction."""
    label = "{0} (id {1})".format(element_name(stairs), eid_value(stairs.Id))

    if not Stairs.IsByComponent(doc, stairs.Id):
        notes.append("{0}: not a component based stair, skipped.".format(label))
        return

    if stairs.IsInEditMode():
        notes.append("{0}: currently in edit mode, skipped.".format(label))
        return

    analysed, skipped = analyse_stairs(stairs)
    if not analysed:
        notes.append("{0}: no run gave a usable pair of side edges.".format(label))
        return
    if skipped:
        notes.append("{0}: {1} run(s) had unreadable edges.".format(label, len(skipped)))

    level_id = level_for_elevation(analysed[0]["z"])

    placement_levels = None
    if multistory is not None:
        try:
            placement_levels = multistory.GetStairsPlacementLevels(stairs)
        except Exception as err:
            notes.append("{0}: could not read its storey levels: {1}".format(label, err))

    if choice["delete_existing"]:
        existing = railings_on_stairs(stairs)
        if existing.Count:
            doc.Delete(existing)
            doc.Regenerate()
            notes.append("{0}: deleted {1} existing railing(s).".format(label, existing.Count))

    if choice["do_inner"]:
        sequence = orient_inner_sequence(analysed)
        landings = landing_boundaries(stairs)
        chain = []
        for index, item in enumerate(sequence):
            if index > 0 and chain:
                gap_start = chain[-1].GetEndPoint(1)
                gap_end = item["inner"][0].GetEndPoint(0)
                if plan_distance(gap_start, gap_end) >= SHORT_CURVE:
                    chain.extend(landing_connector(landings, gap_start, gap_end, notes))
            chain.extend(item["inner"])

        railing = make_railing(
            chain,
            choice["inner_type"],
            level_id,
            stairs.Id,
            offsets["inner"],
            sequence[0]["centroid"],
            notes,
            placement_levels,
        )
        if railing is not None:
            created.append(("{0} - inner".format(label), railing))

    if choice["do_outer"]:
        for item in analysed:
            # a railing on a multistory stair has to hang off the Stairs element
            # itself for the placement levels to apply
            if multistory is not None or not choice["host_to_run"]:
                host_id = stairs.Id
            else:
                host_id = item["run"].Id

            railing = make_railing(
                item["outer"],
                choice["outer_type"],
                level_id,
                host_id,
                offsets["outer"],
                item["centroid"],
                notes,
                placement_levels,
            )
            if railing is not None:
                if choice["flip_outer"]:
                    flip_railing(railing, notes)
                created.append((
                    "{0} - outer run {1}".format(label, eid_value(item["run"].Id)),
                    railing,
                ))


def main():
    targets = gather_targets()
    if not targets:
        return

    railing_types = collect_railing_types()
    if not railing_types:
        TaskDialog.Show("Stair Railing Manager", "No railing types were found in this project.")
        return

    multistory_count = len([1 for _, parent in targets if parent is not None])
    if len(targets) == 1:
        stairs = targets[0][0]
        subtitle = "{0}  -  id {1}  -  {2} run(s), {3} landing(s)".format(
            element_name(stairs),
            eid_value(stairs.Id),
            len(list(stairs.GetStairsRuns())),
            len(list(stairs.GetStairsLandings())),
        )
    else:
        subtitle = "{0} stairs selected".format(len(targets))
    if multistory_count:
        subtitle += "  -  {0} of them multistory".format(multistory_count)

    dialog = RailingDialog(subtitle, railing_types)
    choice = dialog.show()
    if choice is None:
        return

    offsets = {
        "inner": mm_to_ft(choice["offset_inner_mm"]),
        "outer": mm_to_ft(choice["offset_outer_mm"]),
    }
    notes = []
    created = []

    transaction = Transaction(doc, "Create Stair Railings")
    transaction.Start()
    try:
        for stairs, multistory in targets:
            try:
                build_for_stairs(stairs, multistory, choice, offsets, notes, created)
            except Exception as err:
                # one bad stair should not throw away the work done on the others
                notes.append("{0} (id {1}) failed: {2}".format(
                    element_name(stairs), eid_value(stairs.Id), err))
        doc.Regenerate()
        transaction.Commit()
    except Exception:
        transaction.RollBack()
        raise

    lines = ["Created {0} railing(s) on {1} stair(s).".format(len(created), len(targets))]
    for label, railing in created:
        lines.append("  {0}  ->  id {1}".format(label, eid_value(railing.Id)))
    if notes:
        lines.append("")
        lines.append("Notes:")
        for note in notes:
            lines.append("  " + note)

    TaskDialog.Show("Stair Railing Manager", "\n".join(lines))


main()
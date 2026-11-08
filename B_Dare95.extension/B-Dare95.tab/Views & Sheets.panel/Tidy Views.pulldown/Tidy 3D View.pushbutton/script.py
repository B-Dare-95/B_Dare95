# -*- coding: utf-8 -*-
__doc__ = """__________________________________________________
Description:

Tidies the 3D extents of the grids and levels you see in a 3D view:
- Grids: lines up every grid end at a set distance past the outermost grids, so the grid net is a clean rectangle.
- Levels: makes every level plane cover the grid area plus a set distance, so all levels share one footprint.
These are model (3D) extents: every view where these grids and levels use 3D extents follows the change.
__________________________________________________
How-to:

-> Open a 3D view that shows the grids and levels you want to tidy
-> Click on the button
-> Tick Grids and / or Levels, and set the distances past the outermost grids
-> Check the previews and click Apply
-> A summary shows what was updated and what was skipped
__________________________________________________
Author: Mohamed Bedair"""

import math

import clr
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from System import EventHandler
from System.Windows import Point, RoutedEventHandler, TextAlignment
from System.Windows.Markup import XamlReader
from System.Windows.Controls import Canvas, TextBlock, TextChangedEventHandler
from System.Windows.Media import ColorConverter, DoubleCollection, PointCollection, SolidColorBrush
from System.Windows.Shapes import Ellipse, Line as WLine, Polygon
from System.Windows.Threading import Dispatcher, DispatcherFrame
from System.Windows.Interop import WindowInteropHelper

from Autodesk.Revit.DB import (Arc, BoundingBoxXYZ, BuiltInCategory, BuiltInParameter,
                               DatumExtentType, ElementId, FilteredElementCollector, Grid,
                               Level, MultiSegmentGrid, Transaction, Transform, View3D,
                               ViewFamily, ViewFamilyType, ViewPlan, ViewSection, XYZ)
from Autodesk.Revit.DB import Line as DBLine
from Autodesk.Revit.UI import TaskDialog, TaskDialogCommonButtons

from pyrevit import forms, revit, script

doc = revit.doc
cfg = script.get_config()

TITLE = "Tidy 3D View"
MM = 1.0 / 304.8                      # mm -> feet
FT_TO_M = 0.3048
MODEL = DatumExtentType.Model
SIDES = ("t", "b", "l", "r")          # in the grid frame, as seen in plan
SAME = 1e-6                           # feet: two points closer than this are the same
EPS = 1e-9
MAX_LISTED = 30
DEFAULTS = {"g": 1000.0, "l": 2000.0}


# =========================================================================
#  Helpers
# =========================================================================
def id_val(eid):
    """ElementId -> Python int on Revit 2024 (.IntegerValue) and 2025+ (.Value)."""
    try:
        return int(eid.Value)
    except AttributeError:
        return int(eid.IntegerValue)


def scope_box_name(datum):
    """Name of the scope box controlling the datum's extents, or None."""
    try:
        p = datum.get_Parameter(BuiltInParameter.DATUM_VOLUME_OF_INTEREST)
        eid = p.AsElementId() if p is not None else None
    except Exception:
        return None
    if eid is None or eid == ElementId.InvalidElementId:
        return None
    box = doc.GetElement(eid)
    return box.Name if box is not None else u"a scope box"


def multi_segment_ids():
    ids = set()
    for msg in FilteredElementCollector(doc).OfClass(MultiSegmentGrid):
        try:
            for gid in msg.GetGridIds():
                ids.add(id_val(gid))
        except Exception:
            pass
    return ids


def view_datums(view):
    grids = sorted(FilteredElementCollector(doc, view.Id).OfClass(Grid), key=lambda g: g.Name)
    levels = sorted(FilteredElementCollector(doc, view.Id).OfClass(Level),
                    key=lambda lv: lv.ProjectElevation)
    return list(grids), list(levels)


# =========================================================================
#  Grid frame and grid area
#  The frame follows the main grid direction, so a turned grid net still
#  gets a tight rectangle. u = "right", v = "up" as seen in plan.
# =========================================================================
class Frame(object):
    def __init__(self, angle):
        self.angle = angle
        self.ux, self.uy = math.cos(angle), math.sin(angle)
        self.vx, self.vy = -self.uy, self.ux

    def uv(self, p):
        return (p.X * self.ux + p.Y * self.uy, p.X * self.vx + p.Y * self.vy)

    def xyz(self, a, b, z):
        return XYZ(a * self.ux + b * self.vx, a * self.uy + b * self.vy, z)

    def axis(self, name):
        return XYZ(self.ux, self.uy, 0.0) if name == "u" else XYZ(self.vx, self.vy, 0.0)


def main_angle(lines):
    """Most common grid direction (mod 90 degrees), weighted by length."""
    buckets = {}
    for p0, p1 in lines:
        dx, dy = p1.X - p0.X, p1.Y - p0.Y
        length = math.hypot(dx, dy)
        if length < SAME:
            continue
        deg = math.degrees(math.atan2(dy, dx)) % 90.0
        key = int(round(deg * 2.0)) % 180          # half-degree buckets
        buckets[key] = buckets.get(key, 0.0) + length
    if not buckets:
        return 0.0
    best = max(buckets.items(), key=lambda kv: kv[1])[0]
    deg = best / 2.0
    if deg > 45.0:
        deg -= 90.0
    return math.radians(deg)


def line_hit(a0, a1, b0, b1):
    """Intersection of two infinite 2D lines given by point pairs, or None."""
    dx1, dy1 = a1[0] - a0[0], a1[1] - a0[1]
    dx2, dy2 = b1[0] - b0[0], b1[1] - b0[1]
    den = dx1 * dy2 - dy1 * dx2
    n1, n2 = math.hypot(dx1, dy1), math.hypot(dx2, dy2)
    if n1 < SAME or n2 < SAME or abs(den) < 1e-6 * n1 * n2:
        return None
    t = ((b0[0] - a0[0]) * dy2 - (b0[1] - a0[1]) * dx2) / den
    return (a0[0] + dx1 * t, a0[1] + dy1 * t)


def grid_area(grids):
    """(Frame, (umin, umax, vmin, vmax)) of the outermost grids, or None.
    Straight grids count by their crossings (extended), curved grids by their shape."""
    straight, arc_pts = [], []
    for g in grids:
        c = g.Curve
        if isinstance(c, DBLine):
            straight.append((c.GetEndPoint(0), c.GetEndPoint(1)))
        elif isinstance(c, Arc):
            for i in range(17):
                arc_pts.append(c.Evaluate(i / 16.0, True))
    if not straight and not arc_pts:
        return None
    fr = Frame(main_angle(straight))
    segs = [(fr.uv(p0), fr.uv(p1)) for p0, p1 in straight]
    ends = [q for s in segs for q in s] + [fr.uv(p) for p in arc_pts]
    us, vs = [q[0] for q in ends], [q[1] for q in ends]
    slack = 0.25 * math.hypot(max(us) - min(us), max(vs) - min(vs)) + 1.0
    lo_u, hi_u, lo_v, hi_v = min(us) - slack, max(us) + slack, min(vs) - slack, max(vs) + slack

    pts = [fr.uv(p) for p in arc_pts]
    for i in range(len(segs)):
        for j in range(i + 1, len(segs)):
            hit = line_hit(segs[i][0], segs[i][1], segs[j][0], segs[j][1])
            if hit and lo_u <= hit[0] <= hi_u and lo_v <= hit[1] <= hi_v:
                pts.append(hit)
    if len(pts) < 2:
        pts = ends                       # all grids parallel: use where they are now
    us, vs = [q[0] for q in pts], [q[1] for q in pts]
    return fr, (min(us), max(us), min(vs), max(vs))


def grown(area, off):
    """The grid area grown by the side offsets (feet). None when it would collapse."""
    umin, umax, vmin, vmax = area
    box = (umin - off["l"], umax + off["r"], vmin - off["b"], vmax + off["t"])
    if box[1] - box[0] < SAME or box[3] - box[2] < SAME:
        return None
    return box


def clip_to_box(a0, a1, box):
    """Where the infinite line a0 -> a1 crosses the box, in the same direction. Or None."""
    d = (a1[0] - a0[0], a1[1] - a0[1])
    tmin, tmax = -1e18, 1e18
    for k, lo, hi in ((0, box[0], box[1]), (1, box[2], box[3])):
        if abs(d[k]) < EPS:
            if a0[k] < lo - SAME or a0[k] > hi + SAME:
                return None
            continue
        t1, t2 = (lo - a0[k]) / d[k], (hi - a0[k]) / d[k]
        tmin, tmax = max(tmin, min(t1, t2)), min(tmax, max(t1, t2))
    if tmax - tmin < EPS:
        return None
    return ((a0[0] + d[0] * tmin, a0[1] + d[1] * tmin), (a0[0] + d[0] * tmax, a0[1] + d[1] * tmax))


# =========================================================================
#  Work views
#  3D extents are set in a view where the datum shows as a line: grids in a
#  plan, levels in a section. The tool makes temporary ones and deletes them
#  in the same transaction.
# =========================================================================
class WorkViews(object):
    def __init__(self, fr, area):
        self.fr = fr
        self.area = area
        self.plans = {}
        self.sections = {}
        self.made = []

    @staticmethod
    def _family_type(family):
        for vft in FilteredElementCollector(doc).OfClass(ViewFamilyType):
            if vft.ViewFamily == family:
                return vft
        return None

    def _prepare(self, view, category):
        try:
            view.ViewTemplateId = ElementId.InvalidElementId
        except Exception:
            pass
        try:
            view.SetCategoryHidden(ElementId(category), False)
        except Exception:
            pass

    def plan_for(self, grid, levels):
        """A plan at a level the grid passes through (made on first use)."""
        try:
            ext = grid.GetExtents()
            zmin, zmax = ext.MinimumPoint.Z, ext.MaximumPoint.Z
        except Exception:
            zmin, zmax = -1e9, 1e9
        mid = (zmin + zmax) / 2.0
        inside = [lv for lv in levels if zmin + 0.01 <= lv.ProjectElevation <= zmax - 0.01]
        pool = inside or levels
        if not pool:
            return None
        lv = min(pool, key=lambda x: abs(x.ProjectElevation - mid))
        key = id_val(lv.Id)
        if key not in self.plans:
            vft = self._family_type(ViewFamily.FloorPlan)
            if vft is None:
                return None
            try:
                plan = ViewPlan.Create(doc, vft.Id, lv.Id)
            except Exception:
                return None
            self._prepare(plan, BuiltInCategory.OST_Grids)
            self.made.append(plan.Id)
            self.plans[key] = plan
            doc.Regenerate()
        return self.plans[key]

    def section_along(self, axis, levels):
        """A section through the middle of the grid area, its right direction along u or v."""
        if axis in self.sections:
            return self.sections[axis]
        vft = self._family_type(ViewFamily.Section)
        if vft is None or not levels:
            return None
        umin, umax, vmin, vmax = self.area
        cu, cv = (umin + umax) / 2.0, (vmin + vmax) / 2.0
        size = max(umax - umin, vmax - vmin) + 200.0
        zs = [lv.ProjectElevation for lv in levels]
        right = self.fr.axis(axis)
        up = XYZ.BasisZ
        tf = Transform.Identity
        tf.Origin = self.fr.xyz(cu, cv, 0.0)
        tf.BasisX = right
        tf.BasisY = up
        tf.BasisZ = right.CrossProduct(up)
        box = BoundingBoxXYZ()
        box.Transform = tf
        box.Min = XYZ(-size, min(zs) - 50.0, -size)
        box.Max = XYZ(size, max(zs) + 50.0, 0.0)
        try:
            sec = ViewSection.CreateSection(doc, vft.Id, box)
        except Exception:
            return None
        self._prepare(sec, BuiltInCategory.OST_Levels)
        self.made.append(sec.Id)
        self.sections[axis] = sec
        doc.Regenerate()
        return sec

    def delete_all(self):
        for vid in self.made:
            try:
                doc.Delete(vid)
            except Exception:
                pass


def model_line(datum, view):
    try:
        cs = datum.GetCurvesInView(MODEL, view)
    except Exception:
        return None
    if cs is None or cs.Count != 1 or not isinstance(cs[0], DBLine):
        return None
    return cs[0]


def apply_line(datum, view, old, q0, q1):
    """'same', 'done' or 'rejected'."""
    if q0.DistanceTo(old.GetEndPoint(0)) < SAME and q1.DistanceTo(old.GetEndPoint(1)) < SAME:
        return "same"
    new = DBLine.CreateBound(q0, q1)
    if not datum.IsCurveValidInView(MODEL, view, new):
        return "rejected"
    datum.SetCurveInView(MODEL, view, new)
    return "done"


# =========================================================================
#  Grids
# =========================================================================
def tidy_grid(g, fr, box, work, active3d, levels, note):
    """True when the grid changed."""
    candidates = []
    plan = work.plan_for(g, levels)
    if plan is not None:
        candidates.append(plan)
    candidates.append(active3d)
    outcome = None
    for view in candidates:
        old = model_line(g, view)
        if old is None:
            continue
        p0, p1 = old.GetEndPoint(0), old.GetEndPoint(1)
        hit = clip_to_box(fr.uv(p0), fr.uv(p1), box)
        if hit is None:
            note(u"lies outside the grid area - left as it was")
            return False
        z = p0.Z
        try:
            outcome = apply_line(g, view, old, fr.xyz(hit[0][0], hit[0][1], z),
                                 fr.xyz(hit[1][0], hit[1][1], z))
        except Exception as ex:
            note(u"failed: {0}".format(ex))
            return False
        if outcome != "rejected":
            return outcome == "done"
    note(u"Revit rejected the new extents" if outcome == "rejected"
         else u"couldn't be read as a straight line - left as it was")
    return False


def tidy_grids(grids, fr, area, opts, work, active3d, levels, report):
    box = grown(area, opts["off"])
    if box is None:
        report.append(u"Grids: the offsets would collapse the grid area - nothing aligned")
        return 0
    multiseg = multi_segment_ids()
    done = 0
    for g in grids:
        tag = u"Grid {0}".format(g.Name)

        def note(msg, tag=tag):
            report.append(u"{0}  -  {1}".format(tag, msg))

        if id_val(g.Id) in multiseg:
            note(u"multi-segment grid - skipped")
            continue
        if not isinstance(g.Curve, DBLine):
            note(u"curved grid - left as it was")
            continue
        box_name = scope_box_name(g)
        if box_name:
            note(u"extents follow scope box \u201c{0}\u201d - skipped".format(box_name))
            continue
        if tidy_grid(g, fr, box, work, active3d, levels, note):
            done += 1
    return done


# =========================================================================
#  Levels
# =========================================================================
def resize_level(lv, axis, lo, hi, fr, work, levels, note):
    """Sets the level's extent along one frame axis. 'same', 'done' or None (noted)."""
    sec = work.section_along(axis, levels)
    if sec is None:
        note(u"couldn't make a work section - left as it was")
        return None
    old = model_line(lv, sec)
    if old is None:
        note(u"doesn't reach the middle of the grid area - left as it was")
        return None
    p0, p1 = old.GetEndPoint(0), old.GetEndPoint(1)
    d = p1.Subtract(p0).Normalize()
    if abs(d.DotProduct(fr.axis(axis))) < 0.999:
        note(u"couldn't be read along the grid directions - left as it was")
        return None
    k = 0 if axis == "u" else 1
    a0, a1 = fr.uv(p0), fr.uv(p1)
    first, second = (lo, hi) if a0[k] <= a1[k] else (hi, lo)
    if axis == "u":
        q0, q1 = fr.xyz(first, a0[1], p0.Z), fr.xyz(second, a0[1], p0.Z)
    else:
        q0, q1 = fr.xyz(a0[0], first, p0.Z), fr.xyz(a0[0], second, p0.Z)
    try:
        outcome = apply_line(lv, sec, old, q0, q1)
    except Exception as ex:
        note(u"failed: {0}".format(ex))
        return None
    if outcome == "rejected":
        note(u"Revit rejected the new extents")
        return None
    return outcome


def tidy_levels(levels, fr, area, opts, work, report):
    box = grown(area, opts["off"])
    if box is None:
        report.append(u"Levels: the offsets would collapse the grid area - nothing resized")
        return 0
    todo = []
    for lv in levels:
        box_name = scope_box_name(lv)
        if box_name:
            report.append(u"Level {0}  -  extents follow scope box \u201c{1}\u201d - skipped".format(
                lv.Name, box_name))
            continue
        todo.append(lv)
    changed = set()
    alive = list(todo)
    for axis, lo, hi in (("u", box[0], box[1]), ("v", box[2], box[3])):
        nxt = []
        for lv in alive:
            tag = u"Level {0}".format(lv.Name)

            def note(msg, tag=tag):
                report.append(u"{0}  -  {1}".format(tag, msg))

            outcome = resize_level(lv, axis, lo, hi, fr, work, todo, note)
            if outcome is None:
                continue
            if outcome == "done":
                changed.add(id_val(lv.Id))
            nxt.append(lv)
        alive = nxt
        doc.Regenerate()            # the second section must see the first change
    return len(changed)


# =========================================================================
#  Window
# =========================================================================
XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Tidy 3D View" SizeToContent="WidthAndHeight"
        ResizeMode="NoResize" WindowStartupLocation="CenterScreen"
        Background="#161616" FontFamily="Segoe UI" FontSize="12">
  <Window.Resources>
    <Style x:Key="Btn" TargetType="Button">
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Height" Value="30"/>
      <Setter Property="Padding" Value="12,0"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="bd" Background="{TemplateBinding Background}"
                    CornerRadius="6" Padding="{TemplateBinding Padding}">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="bd" Property="Background" Value="#525252"/>
              </Trigger>
              <Trigger Property="IsEnabled" Value="False">
                <Setter Property="Opacity" Value="0.4"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style x:Key="AccentBtn" TargetType="Button" BasedOn="{StaticResource Btn}">
      <Setter Property="Background" Value="#F1C21B"/>
      <Setter Property="Foreground" Value="#161616"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
    </Style>
    <Style TargetType="TextBox">
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="BorderBrush" Value="#525252"/>
      <Setter Property="BorderThickness" Value="1"/>
      <Setter Property="CaretBrush" Value="#F4F4F4"/>
      <Setter Property="Height" Value="28"/>
      <Setter Property="Width" Value="64"/>
      <Setter Property="Padding" Value="6,0"/>
      <Setter Property="TextAlignment" Value="Center"/>
      <Setter Property="VerticalContentAlignment" Value="Center"/>
    </Style>
    <Style TargetType="CheckBox">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="VerticalContentAlignment" Value="Center"/>
      <Setter Property="Cursor" Value="Hand"/>
    </Style>
    <Style x:Key="Head" TargetType="CheckBox" BasedOn="{StaticResource {x:Type CheckBox}}">
      <Setter Property="FontSize" Value="14"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
      <Setter Property="Margin" Value="0,0,0,4"/>
    </Style>
    <Style x:Key="Sub" TargetType="TextBlock">
      <Setter Property="Foreground" Value="#A8A8A8"/>
      <Setter Property="TextWrapping" Value="Wrap"/>
    </Style>
    <Style x:Key="Lbl" TargetType="TextBlock">
      <Setter Property="Foreground" Value="#A8A8A8"/>
      <Setter Property="FontSize" Value="11"/>
      <Setter Property="VerticalAlignment" Value="Center"/>
      <Setter Property="Margin" Value="0,0,6,0"/>
    </Style>
    <Style x:Key="Card" TargetType="Border">
      <Setter Property="Background" Value="#262626"/>
      <Setter Property="CornerRadius" Value="8"/>
      <Setter Property="Padding" Value="12"/>
    </Style>
    <Style x:Key="PreviewBox" TargetType="Border">
      <Setter Property="Background" Value="#161616"/>
      <Setter Property="CornerRadius" Value="6"/>
      <Setter Property="Padding" Value="2"/>
      <Setter Property="VerticalAlignment" Value="Top"/>
    </Style>
  </Window.Resources>

  <StackPanel Margin="12">
    <TextBlock Text="Tidy 3D View" Foreground="#F4F4F4" FontSize="20" FontWeight="Bold"/>
    <TextBlock Style="{StaticResource Sub}" Margin="0,2,0,12"
               Text="Grid ends and level planes in 3D, measured from the outermost grids."/>
    <Grid>
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="260"/>
        <ColumnDefinition Width="12"/>
        <ColumnDefinition Width="560"/>
      </Grid.ColumnDefinitions>

      <!-- This 3D view -->
      <Border Grid.Column="0" Style="{StaticResource Card}">
        <StackPanel>
          <TextBlock Text="IN THIS 3D VIEW" Foreground="#F1C21B" FontSize="11" FontWeight="Bold" Margin="0,0,0,8"/>
          <TextBlock x:Name="txtView" Foreground="#F4F4F4" FontSize="14" FontWeight="SemiBold" TextWrapping="Wrap"/>
          <TextBlock x:Name="txtCounts" Style="{StaticResource Sub}" Margin="0,4,0,0"/>
          <Border Background="#161616" CornerRadius="6" Padding="10" Margin="0,12,0,0">
            <StackPanel>
              <TextBlock Text="Grid area" Style="{StaticResource Lbl}" Margin="0,0,0,4"/>
              <TextBlock x:Name="txtArea" Foreground="#F4F4F4" FontSize="13"/>
              <TextBlock x:Name="txtAngle" Style="{StaticResource Sub}" FontSize="11" Margin="0,4,0,0"/>
            </StackPanel>
          </Border>
          <Border BorderBrush="#F1C21B" BorderThickness="3,0,0,0" Padding="10,6" Margin="0,12,0,0">
            <TextBlock Style="{StaticResource Sub}" FontSize="11"
                       Text="These are 3D extents. Every view where these grids and levels use 3D extents follows the change. Views with 2D extents keep their own."/>
          </Border>
          <TextBlock Style="{StaticResource Sub}" FontSize="11" Margin="0,12,0,0"
                     Text="Top, Bottom, Left and Right are the sides of the grid area as seen in plan, turned with the grids."/>
        </StackPanel>
      </Border>

      <StackPanel Grid.Column="2">
        <!-- Grids -->
        <Border Style="{StaticResource Card}" Margin="0,0,0,10">
          <DockPanel>
            <Border DockPanel.Dock="Right" Style="{StaticResource PreviewBox}">
              <Canvas x:Name="cvGrids" Width="210" Height="170" ClipToBounds="True"/>
            </Border>
            <StackPanel Margin="0,0,12,0">
              <CheckBox x:Name="chkGrids" Content="Grids" Style="{StaticResource Head}"/>
              <TextBlock Style="{StaticResource Sub}" FontSize="11" Margin="0,0,0,10"
                         Text="Every straight grid ends this far past the outermost grids. Curved and multi-segment grids are left as they are."/>
              <StackPanel x:Name="pnlGrids">
                <TextBlock Text="Ends past the outermost grids (mm)" Foreground="#F4F4F4" Margin="0,0,0,6"/>
                <Grid>
                  <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="Auto"/>
                    <ColumnDefinition Width="Auto"/>
                    <ColumnDefinition Width="Auto"/>
                    <ColumnDefinition Width="Auto"/>
                  </Grid.ColumnDefinitions>
                  <Grid.RowDefinitions>
                    <RowDefinition Height="Auto"/>
                    <RowDefinition Height="Auto"/>
                  </Grid.RowDefinitions>
                  <TextBlock Grid.Row="0" Grid.Column="0" Text="Top" Style="{StaticResource Lbl}"/>
                  <TextBox Grid.Row="0" Grid.Column="1" x:Name="txtGT" Margin="0,0,14,4"/>
                  <TextBlock Grid.Row="0" Grid.Column="2" Text="Bottom" Style="{StaticResource Lbl}"/>
                  <TextBox Grid.Row="0" Grid.Column="3" x:Name="txtGB" Margin="0,0,0,4"/>
                  <TextBlock Grid.Row="1" Grid.Column="0" Text="Left" Style="{StaticResource Lbl}"/>
                  <TextBox Grid.Row="1" Grid.Column="1" x:Name="txtGL" Margin="0,0,14,0"/>
                  <TextBlock Grid.Row="1" Grid.Column="2" Text="Right" Style="{StaticResource Lbl}"/>
                  <TextBox Grid.Row="1" Grid.Column="3" x:Name="txtGR"/>
                </Grid>
                <CheckBox x:Name="chkGLink" Content="Same offset on all sides" Margin="0,8,0,0"/>
              </StackPanel>
            </StackPanel>
          </DockPanel>
        </Border>

        <!-- Levels -->
        <Border Style="{StaticResource Card}">
          <DockPanel>
            <Border DockPanel.Dock="Right" Style="{StaticResource PreviewBox}">
              <Canvas x:Name="cvLevels" Width="210" Height="170" ClipToBounds="True"/>
            </Border>
            <StackPanel Margin="0,0,12,0">
              <CheckBox x:Name="chkLevels" Content="Levels" Style="{StaticResource Head}"/>
              <TextBlock Style="{StaticResource Sub}" FontSize="11" Margin="0,0,0,10"
                         Text="Every level plane covers the grid area plus this distance, so all levels share one footprint."/>
              <StackPanel x:Name="pnlLevels">
                <TextBlock Text="Plane edges past the outermost grids (mm)" Foreground="#F4F4F4" Margin="0,0,0,6"/>
                <Grid>
                  <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="Auto"/>
                    <ColumnDefinition Width="Auto"/>
                    <ColumnDefinition Width="Auto"/>
                    <ColumnDefinition Width="Auto"/>
                  </Grid.ColumnDefinitions>
                  <Grid.RowDefinitions>
                    <RowDefinition Height="Auto"/>
                    <RowDefinition Height="Auto"/>
                  </Grid.RowDefinitions>
                  <TextBlock Grid.Row="0" Grid.Column="0" Text="Top" Style="{StaticResource Lbl}"/>
                  <TextBox Grid.Row="0" Grid.Column="1" x:Name="txtLT" Margin="0,0,14,4"/>
                  <TextBlock Grid.Row="0" Grid.Column="2" Text="Bottom" Style="{StaticResource Lbl}"/>
                  <TextBox Grid.Row="0" Grid.Column="3" x:Name="txtLB" Margin="0,0,0,4"/>
                  <TextBlock Grid.Row="1" Grid.Column="0" Text="Left" Style="{StaticResource Lbl}"/>
                  <TextBox Grid.Row="1" Grid.Column="1" x:Name="txtLL" Margin="0,0,14,0"/>
                  <TextBlock Grid.Row="1" Grid.Column="2" Text="Right" Style="{StaticResource Lbl}"/>
                  <TextBox Grid.Row="1" Grid.Column="3" x:Name="txtLR"/>
                </Grid>
                <CheckBox x:Name="chkLLink" Content="Same offset on all sides" Margin="0,8,0,0"/>
                <TextBlock Style="{StaticResource Sub}" FontSize="11" Margin="0,8,0,0"
                           Text="Tip: a level offset larger than the grid offset keeps the grid bubbles inside the level planes."/>
              </StackPanel>
            </StackPanel>
          </DockPanel>
        </Border>
      </StackPanel>
    </Grid>

    <DockPanel Margin="0,12,0,0">
      <StackPanel DockPanel.Dock="Right" Orientation="Horizontal">
        <Button x:Name="btnCancel" Content="Cancel" Style="{StaticResource Btn}" Width="84" Margin="0,0,8,0"/>
        <Button x:Name="btnApply" Content="Apply" Style="{StaticResource AccentBtn}" Width="84"/>
      </StackPanel>
      <TextBlock x:Name="txtMsg" Foreground="#FA4D56" VerticalAlignment="Center" TextWrapping="Wrap"/>
    </DockPanel>
  </StackPanel>
</Window>
"""

_brushes = {}
HILITE = "#F1C21B"
GRID_DASH = "10 3 2 3"


def brush(hexs):
    if hexs not in _brushes:
        _brushes[hexs] = SolidColorBrush(ColorConverter.ConvertFromString(hexs))
    return _brushes[hexs]


def cv_line(cv, x1, y1, x2, y2, color, th=1.0, dash=None):
    ln = WLine()
    ln.X1, ln.Y1, ln.X2, ln.Y2 = x1, y1, x2, y2
    ln.Stroke = brush(color)
    ln.StrokeThickness = th
    if dash:
        ln.StrokeDashArray = DoubleCollection.Parse(dash)
    cv.Children.Add(ln)


def cv_poly(cv, pts, stroke=None, fill=None, opacity=1.0, dash=None, th=1.0):
    pg = Polygon()
    pc = PointCollection()
    for x, y in pts:
        pc.Add(Point(x, y))
    pg.Points = pc
    if stroke:
        pg.Stroke = brush(stroke)
        pg.StrokeThickness = th
    if fill:
        pg.Fill = brush(fill)
    if dash:
        pg.StrokeDashArray = DoubleCollection.Parse(dash)
    pg.Opacity = opacity
    cv.Children.Add(pg)


def cv_bubble(cv, cx, cy, text, rad=7.0):
    e = Ellipse()
    e.Width = e.Height = rad * 2
    e.Fill = brush("#161616")
    e.Stroke = brush("#F4F4F4")
    e.StrokeThickness = 1
    Canvas.SetLeft(e, cx - rad)
    Canvas.SetTop(e, cy - rad)
    cv.Children.Add(e)
    tb = TextBlock()
    tb.Text = text
    tb.FontSize = 9
    tb.Foreground = brush("#F4F4F4")
    tb.Width = rad * 2
    tb.TextAlignment = TextAlignment.Center
    Canvas.SetLeft(tb, cx - rad)
    Canvas.SetTop(tb, cy - 6.5)
    cv.Children.Add(tb)


def cv_text(cv, x, y, text, color="#A8A8A8", size=9):
    tb = TextBlock()
    tb.Text = text
    tb.FontSize = size
    tb.Foreground = brush(color)
    Canvas.SetLeft(tb, x)
    Canvas.SetTop(tb, y)
    cv.Children.Add(tb)


def px(mm):
    return max(-24.0, min(24.0, mm * 0.012))


def draw_grids(cv, on, off):
    """Plan: grids 1-3 and A-B. Dashed box = outermost grids."""
    cv.Children.Clear()
    x0, x1, y0, y1 = 65.0, 145.0, 55.0, 115.0          # outermost grids
    vgrids = [(65.0, u"1"), (105.0, u"2"), (145.0, u"3")]
    hgrids = [(55.0, u"A"), (115.0, u"B")]
    messy = {"t": [34, 22, 40], "b": [140, 150, 132], "l": [40, 28], "r": [176, 168]}
    cv_poly(cv, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], stroke="#6F6F6F", dash="4 3")
    for i, (x, n) in enumerate(vgrids):
        t = y0 - px(off["t"]) if on else messy["t"][i]
        b = y1 + px(off["b"]) if on else messy["b"][i]
        cv_line(cv, x, t, x, b, "#A8A8A8", 1, GRID_DASH)
        if on:
            cv_line(cv, x, y0, x, t, HILITE, 2)
            cv_line(cv, x, y1, x, b, HILITE, 2)
        cv_bubble(cv, x, t - 7, n)
    for i, (y, n) in enumerate(hgrids):
        l = x0 - px(off["l"]) if on else messy["l"][i]
        r = x1 + px(off["r"]) if on else messy["r"][i]
        cv_line(cv, l, y, r, y, "#A8A8A8", 1, GRID_DASH)
        if on:
            cv_line(cv, x0, y, l, y, HILITE, 2)
            cv_line(cv, x1, y, r, y, HILITE, 2)
        cv_bubble(cv, l - 7, y, n)
    cv_text(cv, 4, 154, u"Plan")


def draw_levels(cv, on, off):
    """Oblique 3D: three level planes over the grid area (dashed)."""
    cv.Children.Clear()

    def p(u, v, z):                    # plan units -> canvas
        return (95.0 + u * 40.0 + v * 20.0, 132.0 - v * 18.0 - z)

    def quad(u0, u1, v0, v1, z):
        return [p(u0, v0, z), p(u1, v0, z), p(u1, v1, z), p(u0, v1, z)]

    def k(mm):                         # mm -> plan units (grid area is 2 x 1.4 units)
        return px(mm) / 60.0

    messy = [(-0.95, 0.85, -0.60, 0.80), (-1.35, 1.10, -0.85, 0.75), (-1.05, 1.40, -0.75, 0.95)]
    for i, z in enumerate((0.0, 38.0, 76.0)):
        if on:
            u0, u1 = -1.0 - k(off["l"]), 1.0 + k(off["r"])
            v0, v1 = -0.7 - k(off["b"]), 0.7 + k(off["t"])
        else:
            u0, u1, v0, v1 = messy[i]
        cv_poly(cv, quad(u0, u1, v0, v1, z), stroke="#C6C6C6", fill="#393939", opacity=0.85)
        cv_poly(cv, quad(-1.0, 1.0, -0.7, 0.7, z), stroke="#6F6F6F", dash="4 3")
        if on:
            for (a, b), (c, d) in (((-1.0, -0.7), (u0, -0.7)), ((1.0, -0.7), (u1, -0.7))):
                pa, pb = p(a, b, z), p(c, d, z)
                cv_line(cv, pa[0], pa[1], pb[0], pb[1], HILITE, 2)
    for u in (-1.0, 0.0, 1.0):                     # grids as vertical lines at the near edge
        top, bot = p(u, -0.7, 96.0), p(u, -0.7, -8.0)
        cv_line(cv, top[0], top[1], bot[0], bot[1], "#A8A8A8", 1, GRID_DASH)
    cv_text(cv, 4, 4, u"3D")


def opt_bool(name, default):
    try:
        return float(cfg.get_option(name, 1.0 if default else 0.0)) > 0.5
    except Exception:
        return default


def opt_float(name, default):
    try:
        return float(cfg.get_option(name, default))
    except Exception:
        return default


def parse_mm(text):
    return float(text.strip().replace(",", "."))


def show_ui(view, grids, levels, fr, area):
    w = XamlReader.Parse(XAML)
    f = w.FindName
    result = {"ok": False}
    txt_msg = f("txtMsg")

    f("txtView").Text = view.Name
    f("txtCounts").Text = u"{0} grids \u00b7 {1} levels".format(len(grids), len(levels))
    f("txtArea").Text = u"{0:.2f} m \u00d7 {1:.2f} m".format(
        (area[1] - area[0]) * FT_TO_M, (area[3] - area[2]) * FT_TO_M)
    deg = math.degrees(fr.angle)
    f("txtAngle").Text = u"Turned {0:.1f}\u00b0 from the project axes".format(deg) \
        if abs(deg) > 0.05 else u"Square to the project axes"

    chk = {"g": f("chkGrids"), "l": f("chkLevels")}
    link = {"g": f("chkGLink"), "l": f("chkLLink")}
    pnl = {"g": f("pnlGrids"), "l": f("pnlLevels")}
    cv = {"g": f("cvGrids"), "l": f("cvLevels")}
    box = {"g": dict((s, f("txtG" + s.upper())) for s in SIDES),
           "l": dict((s, f("txtL" + s.upper())) for s in SIDES)}
    busy = [False]

    for key in ("g", "l"):
        chk[key].IsChecked = opt_bool(key + "_on", True)
        link[key].IsChecked = opt_bool(key + "_link", True)
        for s in SIDES:
            box[key][s].Text = u"{0:g}".format(opt_float(key + "_off_" + s, DEFAULTS[key]))
    if not levels:
        chk["l"].IsChecked = False
        chk["l"].IsEnabled = False
        chk["l"].ToolTip = u"No levels show in this 3D view"

    def num(b):
        try:
            return parse_mm(b.Text)
        except Exception:
            return 0.0

    def redraw(*args):
        try:
            draw_grids(cv["g"], bool(chk["g"].IsChecked), dict((s, num(box["g"][s])) for s in SIDES))
            draw_levels(cv["l"], bool(chk["l"].IsChecked), dict((s, num(box["l"][s])) for s in SIDES))
        except Exception:
            pass                      # a preview must never block the tool
        for key in ("g", "l"):
            on = bool(chk[key].IsChecked)
            pnl[key].IsEnabled = on
            pnl[key].Opacity = 1.0 if on else 0.4
            cv[key].Opacity = 1.0 if on else 0.35
        txt_msg.Text = u""

    def side_handler(key, side):
        def handler(s, e):
            if not busy[0] and link[key].IsChecked:
                busy[0] = True
                for o in SIDES:
                    if o != side:
                        box[key][o].Text = box[key][side].Text
                busy[0] = False
            redraw()
        return handler

    def link_handler(key):
        def handler(s, e):
            if link[key].IsChecked:
                busy[0] = True
                for o in ("b", "l", "r"):
                    box[key][o].Text = box[key]["t"].Text
                busy[0] = False
            redraw()
        return handler

    for key in ("g", "l"):
        for s in SIDES:
            box[key][s].TextChanged += TextChangedEventHandler(side_handler(key, s))
        link[key].Click += RoutedEventHandler(link_handler(key))
        chk[key].Click += RoutedEventHandler(redraw)
    redraw()

    def on_apply(s, e):
        on = dict((k, bool(chk[k].IsChecked)) for k in ("g", "l"))
        if not (on["g"] or on["l"]):
            txt_msg.Text = u"Tick Grids, Levels or both."
            return
        offs = {}
        for key, label in (("g", u"Grids"), ("l", u"Levels")):
            try:
                offs[key] = dict((s2, parse_mm(box[key][s2].Text)) for s2 in SIDES)
            except Exception:
                if on[key]:
                    txt_msg.Text = u"{0}: enter a number (mm) for every side.".format(label)
                    return
                offs[key] = dict((s2, opt_float(key + "_off_" + s2, DEFAULTS[key])) for s2 in SIDES)
        result.update({"ok": True, "on": on, "off_mm": offs,
                       "link": dict((k, bool(link[k].IsChecked)) for k in ("g", "l"))})
        w.Close()

    f("btnApply").Click += RoutedEventHandler(on_apply)
    f("btnCancel").Click += RoutedEventHandler(lambda s, e: w.Close())

    frame = DispatcherFrame()

    def on_closed(s, e):
        frame.Continue = False

    w.Closed += EventHandler(on_closed)
    try:
        WindowInteropHelper(w).Owner = __revit__.MainWindowHandle
    except Exception:
        pass
    w.Show()
    Dispatcher.PushFrame(frame)
    return result


# =========================================================================
#  Main
# =========================================================================
def save_settings(res):
    for key in ("g", "l"):
        cfg.set_option(key + "_on", 1.0 if res["on"][key] else 0.0)
        cfg.set_option(key + "_link", 1.0 if res["link"][key] else 0.0)
        for s in SIDES:
            cfg.set_option(key + "_off_" + s, res["off_mm"][key][s])
    script.save_config()


def show_result(res, counts, n_grids, n_levels, report):
    lines = []
    if res["on"]["g"]:
        lines.append(u"Grids: {0} of {1} lined up.".format(counts["grids"], n_grids))
    if res["on"]["l"]:
        lines.append(u"Levels: {0} of {1} resized.".format(counts["levels"], n_levels))
    td = TaskDialog(TITLE)
    td.MainInstruction = u"3D extents tidied" if (counts["grids"] or counts["levels"]) \
        else u"Nothing needed changing"
    if report:
        lines.append(u"{0} issues - expand details for the list.".format(len(report)))
        shown = report[:MAX_LISTED]
        if len(report) > MAX_LISTED:
            shown.append(u"... and {0} more".format(len(report) - MAX_LISTED))
        td.ExpandedContent = u"\n".join(shown)
    td.MainContent = u"\n".join(lines)
    td.CommonButtons = TaskDialogCommonButtons.Ok
    td.Show()


def main():
    view = doc.ActiveView
    if not isinstance(view, View3D) or view.IsTemplate:
        forms.alert(u"Open a 3D view first. The tool tidies the grids and levels that show in it.",
                    title=TITLE)
        return
    grids, levels = view_datums(view)
    if not grids:
        forms.alert(u"No grids show in this 3D view. The extents are measured from the outermost "
                    u"grids, so the view needs to show them.", title=TITLE)
        return
    found = grid_area(grids)
    if found is None:
        forms.alert(u"The grids in this view couldn't be read.", title=TITLE)
        return
    fr, area = found

    res = show_ui(view, grids, levels, fr, area)
    if not res["ok"]:
        return
    save_settings(res)

    offs = dict((key, {"off": dict((s, res["off_mm"][key][s] * MM) for s in SIDES)})
                for key in ("g", "l"))
    all_levels = sorted(FilteredElementCollector(doc).OfClass(Level), key=lambda lv: lv.ProjectElevation)
    report = []
    counts = {"grids": 0, "levels": 0}

    t = Transaction(doc, TITLE)
    t.Start()
    work = WorkViews(fr, area)
    try:
        if res["on"]["g"]:
            counts["grids"] = tidy_grids(grids, fr, area, offs["g"], work, view, all_levels, report)
        if res["on"]["l"] and levels:
            counts["levels"] = tidy_levels(levels, fr, area, offs["l"], work, report)
        work.delete_all()
        t.Commit()
    except Exception as ex:
        t.RollBack()
        forms.alert(u"Failed - nothing changed.\n\n{0}".format(ex), title=TITLE)
        return
    show_result(res, counts, len(grids), len(levels), report)


main()
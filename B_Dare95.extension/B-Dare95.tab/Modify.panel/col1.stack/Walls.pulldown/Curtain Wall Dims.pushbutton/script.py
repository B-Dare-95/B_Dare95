# -*- coding: utf-8 -*-
"""Curtain Wall Dimension

Pick curtain walls - from the host model or from a Revit link - in a plan,
elevation or section view. Each wall gets two dimension strings:
  1. Detailed - wall start -> every curtain grid -> wall end (closest to wall)
  2. Overall  - wall start -> wall end (outer line)

The spacing between the wall and the two lines is estimated from the text
size / text offset of the chosen Dimension Type and the view scale.

Plan views ............. along the wall length (vertical grids),
                         placed above the wall
Elevation / Section .... along the wall height (horizontal grids),
                         placed to the left of the wall

Picking a panel or mullion selects its host curtain wall (in elevation the
cursor lands on panels/mullions, not on the wall).

Each grid's candidate references (every line in the grid's view geometry,
the grid element, the mullion centre planes) are probed one by one with a
test dimension; the first one Revit actually measures is kept. The final
detailed string is checked against the expected grid spacing.
"""
__title__ = "Curtain Wall\nDimension"
__author__ = "Mohamed Bedair"

import clr
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from System import EventHandler
from System.Windows import RoutedEventHandler
from System.Windows.Markup import XamlReader
from System.Windows.Threading import Dispatcher, DispatcherFrame
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Controls import TextChangedEventHandler, SelectionChangedEventHandler
from System.Windows.Input import MouseButtonEventHandler

from Autodesk.Revit.DB import (
    BuiltInParameter, DimensionStyleType, DimensionType, Element, ElementTypeGroup,
    FamilyInstanceReferenceType, FilteredElementCollector, Mullion, Panel, GeometryInstance, Line, LocationCurve, Options,
    PlanarFace, Reference, ReferenceArray, RevitLinkInstance, Solid,
    Transaction, Transform, ViewPlan, ViewSection, ViewType, Wall, WallKind, XYZ
)
from Autodesk.Revit.UI import TaskDialog
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException

uidoc = __revit__.ActiveUIDocument
doc = uidoc.Document

FT_TO_MM = 304.8
TOL = 1.0 / FT_TO_MM          # 1 mm - duplicate / end-coincidence tolerance
PARALLEL_DOT = 0.999          # face normal parallel to measuring axis
PERP_DOT = 0.01               # line perpendicular to measuring axis
END_ON_DOT = 0.99             # line seen end-on in the view -> unusable
TOOL_NAME = "Curtain Wall Dimension"


# ----------------------------------------------------------------- helpers
def eid_int(eid):
    try:
        return eid.Value
    except AttributeError:
        return eid.IntegerValue


def elem_name(elem):
    try:
        return Element.Name.GetValue(elem)
    except Exception:
        try:
            return elem.Name
        except Exception:
            return "?"


def alert(msg):
    TaskDialog.Show(TOOL_NAME, msg)


def is_curtain_wall(elem):
    try:
        return (isinstance(elem, Wall)
                and elem.WallType.Kind == WallKind.Curtain
                and elem.CurtainGrid is not None)
    except Exception:
        return False


def host_curtain_wall(elem):
    """The curtain wall itself, or the curtain wall hosting a picked panel /
    mullion. None for anything else."""
    if elem is None:
        return None
    if is_curtain_wall(elem):
        return elem
    if isinstance(elem, (Panel, Mullion)):
        try:
            host = elem.Host
        except Exception:
            host = None
        if is_curtain_wall(host):
            return host
    return None


class CurtainWallFilter(ISelectionFilter):
    """Host model: curtain walls, or their panels / mullions."""
    def AllowElement(self, elem):
        return host_curtain_wall(elem) is not None

    def AllowReference(self, ref, point):
        return False


class LinkedCurtainWallFilter(ISelectionFilter):
    """Linked models: curtain walls inside loaded Revit links only."""
    def AllowElement(self, elem):
        return isinstance(elem, RevitLinkInstance)

    def AllowReference(self, ref, point):
        try:
            link = doc.GetElement(ref.ElementId)
            if not isinstance(link, RevitLinkInstance):
                return False
            link_doc = link.GetLinkDocument()
            if link_doc is None:
                return False
            return host_curtain_wall(link_doc.GetElement(ref.LinkedElementId)) is not None
        except Exception:
            return False


class Source(object):
    """Where the wall lives. Host: identity transform, refs as-is.
    Link: element ids belong to link_doc, geometry is moved into host
    coordinates with the link's total transform, and every reference is
    converted with CreateLinkReference before it is used in the host view."""
    def __init__(self, link=None):
        self.link = link
        if link is None:
            self.doc = doc
            self.tr = Transform.Identity
        else:
            self.doc = link.GetLinkDocument()
            self.tr = link.GetTotalTransform()

    @property
    def is_link(self):
        return self.link is not None

    def host_ref(self, ref):
        if ref is None:
            return None
        if self.link is None:
            return ref
        try:
            return ref.CreateLinkReference(self.link)
        except Exception:
            return None

    def label(self, wall):
        if self.link is None:
            return "Wall {}".format(eid_int(wall.Id))
        return "Wall {} in link '{}'".format(eid_int(wall.Id), elem_name(self.link))


def get_view_kind(view):
    if view is None or view.IsTemplate:
        return None
    if isinstance(view, ViewPlan) and view.ViewType in (
            ViewType.FloorPlan, ViewType.CeilingPlan,
            ViewType.EngineeringPlan, ViewType.AreaPlan):
        return "plan"
    if isinstance(view, ViewSection) and view.ViewType in (
            ViewType.Elevation, ViewType.Section, ViewType.Detail):
        return "elev"
    return None


def make_options(source, view):
    """Host elements: view-specific geometry. Linked elements cannot take a
    host view, so they get the view's detail level instead."""
    opt = Options()
    opt.ComputeReferences = True
    opt.IncludeNonVisibleObjects = True
    if source.is_link:
        opt.DetailLevel = view.DetailLevel
    else:
        opt.View = view
    return opt


def iter_geometry(geom, transform):
    """Yield (geometry_object, transform_to_model) - recurses instances."""
    if geom is None:
        return
    for g in geom:
        if isinstance(g, GeometryInstance):
            sub_tr = transform.Multiply(g.Transform)
            for item in iter_geometry(g.GetSymbolGeometry(), sub_tr):
                yield item
        else:
            yield g, transform


# --------------------------------------------------------- offset estimate
def dim_type_metrics(dim_type):
    """Text size and text-to-line offset in paper feet."""
    ts, td = 0.0, 0.0
    p = dim_type.get_Parameter(BuiltInParameter.TEXT_SIZE)
    if p is not None:
        ts = p.AsDouble()
    p = dim_type.get_Parameter(BuiltInParameter.TEXT_DIST_TO_LINE)
    if p is not None:
        td = p.AsDouble()
    return ts, td


def compute_offsets(text_size, text_dist, scale, factor):
    """Row pitch = text band (size + gap to line) + 1.5x text size clear.
    Returns model-space distances (feet) from the wall edge to the
    detailed line and to the overall line."""
    row = (2.5 * text_size + text_dist) * scale * factor
    return row, 2.0 * row


# --------------------------------------------------------- reference scan
def scan_element(elem, source, view, axis, origin, view_dir, offset_dir,
                 cands, extent, want_lines):
    """Collect (t, Reference) for planar faces normal to `axis` and (if
    want_lines) lines perpendicular to it. Also tracks how far the geometry
    reaches along offset_dir (extent[0])."""
    for g, tr in iter_geometry(elem.get_Geometry(make_options(source, view)),
                               source.tr):
        if isinstance(g, Solid):
            if g.Faces.Size == 0:
                continue
            for f in g.Faces:
                if not isinstance(f, PlanarFace) or f.Reference is None:
                    continue
                n = tr.OfVector(f.FaceNormal)
                if abs(n.DotProduct(axis)) < PARALLEL_DOT:
                    continue
                ref = source.host_ref(f.Reference)
                if ref is None:
                    continue
                t = tr.OfPoint(f.Origin).Subtract(origin).DotProduct(axis)
                cands.append((t, ref, 0))  # face
            for e in g.Edges:
                for prm in (0.0, 0.5, 1.0):
                    p = tr.OfPoint(e.Evaluate(prm))
                    d = p.Subtract(origin).DotProduct(offset_dir)
                    if d > extent[0]:
                        extent[0] = d
        elif want_lines and isinstance(g, Line) and g.Reference is not None:
            d = tr.OfVector(g.Direction)
            if abs(d.DotProduct(axis)) > PERP_DOT:
                continue
            if abs(d.DotProduct(view_dir)) > END_ON_DOT:
                continue
            ref = source.host_ref(g.Reference)
            if ref is None:
                continue
            t = tr.OfPoint(g.GetEndPoint(0)).Subtract(origin).DotProduct(axis)
            cands.append((t, ref, 1))  # line


def grid_references(wall, source, view, axis, origin, stats):
    """Every curtain grid perpendicular to `axis`, with its candidate
    references in probing order: every Line in the grid's view geometry
    (in plan and section these are the short ticks across the wall, so no
    end-on filtering), the grid element, then the mullion centre planes."""
    cg = wall.CurtainGrid
    ids = list(cg.GetUGridLineIds()) + list(cg.GetVGridLineIds())
    stats["grids"] = len(ids)
    opt = make_options(source, view)
    grids = []
    for gid in ids:
        gl = source.doc.GetElement(gid)
        if gl is None:
            continue
        crv = gl.FullCurve
        p0 = source.tr.OfPoint(crv.GetEndPoint(0))
        p1 = source.tr.OfPoint(crv.GetEndPoint(1))
        if p0.DistanceTo(p1) < TOL:
            continue
        d = p1.Subtract(p0).Normalize()
        if abs(d.DotProduct(axis)) > PERP_DOT:
            continue
        stats["perpendicular"] += 1
        cands = []
        try:
            for geo, tr in iter_geometry(gl.get_Geometry(opt), source.tr):
                if isinstance(geo, Line) and geo.Reference is not None:
                    r = source.host_ref(geo.Reference)
                    if r is not None:
                        cands.append(r)
        except Exception:
            pass
        try:
            r = source.host_ref(Reference(gl))
            if r is not None:
                cands.append(r)
        except Exception:
            pass
        grids.append({"t": p0.Subtract(origin).DotProduct(axis), "dir": d,
                      "cands": cands, "ref": None})
    attach_mullions(cg, source, axis, origin, grids)
    return grids


def attach_mullions(cg, source, axis, origin, grids):
    """Append the centre references of the mullion lying on each grid."""
    if not grids:
        return
    rtypes = (FamilyInstanceReferenceType.CenterLeftRight,
              FamilyInstanceReferenceType.CenterFrontBack)
    for mid in cg.GetMullionIds():
        m = source.doc.GetElement(mid)
        if not isinstance(m, Mullion):
            continue
        try:
            crv = m.LocationCurve
        except Exception:
            crv = None
        if crv is None:
            continue
        a = source.tr.OfPoint(crv.GetEndPoint(0))
        b = source.tr.OfPoint(crv.GetEndPoint(1))
        if a.DistanceTo(b) < TOL:
            continue
        md = b.Subtract(a).Normalize()
        t = a.Subtract(origin).DotProduct(axis)
        for g in grids:
            if abs(g["t"] - t) > TOL or abs(md.DotProduct(g["dir"])) < 0.99:
                continue
            for rtype in rtypes:
                try:
                    refs = m.GetReferences(rtype)
                except Exception:
                    refs = None
                if refs is not None and refs.Count > 0:
                    r = source.host_ref(refs[0])
                    if r is not None:
                        g["cands"].append(r)
            break


# ------------------------------------------------------------- dimensioning
def resolve_frame(wall, source, view, kind):
    """Return (axis, origin, offset_dir) or raise ValueError.
    Plan: along the wall length, offset towards the top of the view (walls
    running vertically on screen get the left side). Elevation / section:
    along the wall height, offset to the left of the view."""
    loc = wall.Location
    if not isinstance(loc, LocationCurve):
        raise ValueError("wall has no location line")
    crv = loc.Curve
    p0 = source.tr.OfPoint(crv.GetEndPoint(0))
    up, right, vdir = view.UpDirection, view.RightDirection, view.ViewDirection

    if kind == "plan":
        if not isinstance(crv, Line):
            raise ValueError("only straight curtain walls are supported in plan")
        wdir = source.tr.OfVector(crv.Direction)
        axis = XYZ(wdir.X, wdir.Y, 0).Normalize()
        n = XYZ(-axis.Y, axis.X, 0)
        du = n.DotProduct(up)
        if du < -0.01:
            n = n.Negate()
        elif abs(du) <= 0.01 and n.DotProduct(right) > 0:
            n = n.Negate()
        return axis, p0, n

    # Section cutting the wall: put the dimension line in the cut plane.
    # Elevation (or section looking at the wall face): keep it on the wall,
    # the view plane can sit far in front of the wall at the marker.
    origin = p0
    if isinstance(crv, Line):
        wdir = source.tr.OfVector(crv.Direction).Normalize()
        if abs(wdir.DotProduct(vdir)) > 0.7:
            origin = p0.Subtract(vdir.Multiply(p0.Subtract(view.Origin).DotProduct(vdir)))
    return XYZ.BasisZ, origin, right.Negate()


MAX_END_CANDS = 8  # per end - probing is n x n test dimensions at worst


def dim_line(origin, axis, offset_dir, t0, t1, dist):
    shift = offset_dir.Multiply(dist)
    a = origin.Add(axis.Multiply(t0)).Add(shift)
    b = origin.Add(axis.Multiply(t1)).Add(shift)
    return Line.CreateBound(a, b)


def segment_values(dim):
    if dim.NumberOfSegments == 0:
        return [dim.Value]
    return [s.Value for s in dim.Segments]


def try_string(view, line, refs, expected, dim_type, keep):
    """Create a dimension; it passes only if Revit used every reference
    (segment count and lengths match `expected`). Failed dimensions are
    always deleted; passing ones are deleted too unless keep=True."""
    ra = ReferenceArray()
    for r in refs:
        ra.Append(r)
    try:
        dim = doc.Create.NewDimension(view, line, ra, dim_type)
    except Exception:
        return False
    if dim is None:
        return False
    try:
        vals = segment_values(dim)
    except Exception:
        vals = []
    good = len(vals) == len(expected)
    if good:
        for v, e in zip(sorted(vals), sorted(expected)):
            if v is None or abs(v - e) > 2 * TOL:
                good = False
                break
    if not (good and keep):
        doc.Delete(dim.Id)
    return good


def dimension_wall(wall, source, view, kind, settings):
    try:
        axis, origin, offset_dir = resolve_frame(wall, source, view, kind)
    except ValueError as err:
        return False, str(err)

    view_dir = view.ViewDirection
    cg = wall.CurtainGrid

    # End reference candidates from the wall, its mullions and panels.
    cands, extent = [], [0.0]
    scan_element(wall, source, view, axis, origin, view_dir, offset_dir,
                 cands, extent, True)
    for eid in list(cg.GetMullionIds()) + list(cg.GetPanelIds()):
        el = source.doc.GetElement(eid)
        if el is not None:
            scan_element(el, source, view, axis, origin, view_dir, offset_dir,
                         cands, extent, False)

    if not cands:
        return False, "could not find references at the wall ends"

    # Outermost first; at the same position faces before lines. Nothing is
    # trusted blindly: in elevation the wall's own horizontal lines (base /
    # location line) sit exactly at the ends but Revit refuses them, so the
    # pair is chosen by probing.
    def bucket(c):
        return int(round(c[0] / TOL))
    starts = sorted(cands, key=lambda c: (bucket(c), c[2]))[:MAX_END_CANDS]
    ends = sorted(cands, key=lambda c: (-bucket(c), c[2]))[:MAX_END_CANDS]

    stats = {"grids": 0, "perpendicular": 0}
    all_grids = grid_references(wall, source, view, axis, origin, stats)

    d_detail, d_overall = settings["offsets"]
    edge = extent[0]
    dim_type = settings["dim_type"]

    notes = []
    t = Transaction(doc, "Curtain Wall Dimension")
    t.Start()
    try:
        start, end = None, None
        for s in starts:
            for e in ends:
                if e[0] - s[0] < TOL:
                    continue
                probe_line = dim_line(origin, axis, offset_dir, s[0], e[0],
                                      edge + d_overall)
                if try_string(view, probe_line, [s[1], e[1]],
                              [e[0] - s[0]], dim_type, False):
                    start, end = s, e
                    break
            if start is not None:
                break
        if start is None:
            t.RollBack()
            return False, ("Revit rejected every end reference found "
                           "({} candidates tried)").format(len(starts))

        grids = [g for g in all_grids if start[0] + TOL < g["t"] < end[0] - TOL]
        grids.sort(key=lambda g: g["t"])
        inner = []
        for g in grids:
            if not inner or g["t"] - inner[-1]["t"] > TOL:
                inner.append(g)

        ra_overall = ReferenceArray()
        ra_overall.Append(start[1])
        ra_overall.Append(end[1])

        # Probe each grid: [wall start, candidate] must measure exactly the
        # distance to that grid, otherwise Revit ignored the reference.
        for g in inner:
            probe_line = dim_line(origin, axis, offset_dir, start[0], g["t"],
                                  edge + d_detail)
            for r in g["cands"]:
                if try_string(view, probe_line, [start[1], r],
                              [g["t"] - start[0]], dim_type, False):
                    g["ref"] = r
                    break
        usable = [g for g in inner if g["ref"] is not None]

        if usable:
            ts = [start[0]] + [g["t"] for g in usable] + [end[0]]
            expected = [ts[i + 1] - ts[i] for i in range(len(ts) - 1)]
            refs = [start[1]] + [g["ref"] for g in usable] + [end[1]]
            line_detail = dim_line(origin, axis, offset_dir, start[0], end[0],
                                   edge + d_detail)
            if not try_string(view, line_detail, refs, expected, dim_type, True):
                usable = []
                notes.append("detailed string was rejected by Revit")

        doc.Create.NewDimension(
            view, dim_line(origin, axis, offset_dir, start[0], end[0],
                           edge + d_overall), ra_overall, dim_type)
        t.Commit()
    except Exception as err:
        t.RollBack()
        return False, "dimension creation failed ({})".format(err)

    if not inner:
        return True, ("no curtain grids between the wall ends ({} grid lines on the "
                      "wall, {} across the dimension direction) - overall dimension "
                      "only").format(stats["grids"], stats["perpendicular"])
    skipped = len(inner) - len([g for g in inner if g["ref"] is not None])
    if skipped:
        tried = max([len(g["cands"]) for g in inner] + [0])
        notes.append("{} of {} grids could not be referenced (up to {} reference "
                     "types tried per grid)".format(skipped, len(inner), tried))
    return True, ("; ".join(notes) if notes else None)


# ---------------------------------------------------------------------- UI
XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Curtain Wall Dimension" Width="460" SizeToContent="Height"
        WindowStartupLocation="CenterScreen" ResizeMode="NoResize"
        Background="#161616" Foreground="#F4F4F4"
        FontFamily="Segoe UI" FontSize="12">
  <Window.Resources>
    <Style x:Key="Btn" TargetType="Button">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="Padding" Value="18,7"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="bd" Background="{TemplateBinding Background}"
                    CornerRadius="4" Padding="{TemplateBinding Padding}">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="bd" Property="Opacity" Value="0.85"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style x:Key="Accent" TargetType="Button" BasedOn="{StaticResource Btn}">
      <Setter Property="Background" Value="#F1C21B"/>
      <Setter Property="Foreground" Value="#161616"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
    </Style>
    <Style x:Key="Toggle" TargetType="ToggleButton">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="Padding" Value="10,7"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ToggleButton">
            <Border x:Name="bd" Background="{TemplateBinding Background}"
                    CornerRadius="4" Padding="{TemplateBinding Padding}">
              <ContentPresenter HorizontalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsChecked" Value="True">
                <Setter TargetName="bd" Property="Background" Value="#F1C21B"/>
                <Setter Property="Foreground" Value="#161616"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style x:Key="Box" TargetType="TextBox">
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="BorderBrush" Value="#525252"/>
      <Setter Property="CaretBrush" Value="#F4F4F4"/>
      <Setter Property="Padding" Value="6,5"/>
    </Style>
    <Style x:Key="Item" TargetType="ListBoxItem">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ListBoxItem">
            <Border x:Name="bd" Background="Transparent" Padding="8,5" CornerRadius="3">
              <ContentPresenter/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="bd" Property="Background" Value="#393939"/>
              </Trigger>
              <Trigger Property="IsSelected" Value="True">
                <Setter TargetName="bd" Property="Background" Value="#F1C21B"/>
                <Setter Property="Foreground" Value="#161616"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
  </Window.Resources>

  <Border Padding="18">
    <StackPanel>
      <TextBlock Text="Curtain Wall Dimension" FontSize="18" FontWeight="SemiBold"/>
      <TextBlock x:Name="SubTitle" Foreground="#A8A8A8" Margin="0,2,0,14" TextWrapping="Wrap"/>

      <Border Background="#262626" CornerRadius="4" Padding="12">
        <StackPanel>
          <TextBlock Text="DIMENSION TYPE" Foreground="#A8A8A8" FontSize="11" Margin="0,0,0,6"/>
          <TextBox x:Name="SearchBox" Style="{StaticResource Box}"/>
          <ListBox x:Name="TypeList" Height="190" Margin="0,6,0,0"
                   Background="#262626" BorderBrush="#393939"
                   ItemContainerStyle="{StaticResource Item}"/>
        </StackPanel>
      </Border>

      <Border Background="#262626" CornerRadius="4" Padding="12" Margin="0,10,0,0">
        <StackPanel>
          <TextBlock Text="PICK FROM" Foreground="#A8A8A8" FontSize="11" Margin="0,0,0,6"/>
          <Grid Margin="0,0,0,12">
            <Grid.ColumnDefinitions>
              <ColumnDefinition Width="*"/>
              <ColumnDefinition Width="8"/>
              <ColumnDefinition Width="*"/>
            </Grid.ColumnDefinitions>
            <ToggleButton x:Name="HostBtn" Grid.Column="0" Content="Host model"
                          Style="{StaticResource Toggle}" IsChecked="True"/>
            <ToggleButton x:Name="LinkBtn" Grid.Column="2" Content="Linked models"
                          Style="{StaticResource Toggle}"/>
          </Grid>

          <TextBlock Text="SPACING FACTOR" Foreground="#A8A8A8" FontSize="11" Margin="0,0,0,6"/>
          <StackPanel Orientation="Horizontal">
            <TextBox x:Name="FactorBox" Style="{StaticResource Box}" Width="70" Text="1.0"/>
            <TextBlock Text="  multiplies the estimated offsets" Foreground="#A8A8A8"
                       VerticalAlignment="Center"/>
          </StackPanel>
          <TextBlock x:Name="Preview" Foreground="#A8A8A8" Margin="0,10,0,0" TextWrapping="Wrap"/>
        </StackPanel>
      </Border>

      <StackPanel Orientation="Horizontal" HorizontalAlignment="Right" Margin="0,14,0,0">
        <Button x:Name="CancelBtn" Content="Cancel" Style="{StaticResource Btn}" Margin="0,0,8,0"/>
        <Button x:Name="OkBtn" Content="Start Picking" Style="{StaticResource Accent}"/>
      </StackPanel>
    </StackPanel>
  </Border>
</Window>
"""


def collect_dim_types():
    items = []
    for dt in FilteredElementCollector(doc).OfClass(DimensionType):
        try:
            if dt.StyleType != DimensionStyleType.Linear:
                continue
        except Exception:
            continue
        if dt.get_Parameter(BuiltInParameter.TEXT_SIZE) is None:
            continue
        name = elem_name(dt)
        if not name:
            continue
        ts, td = dim_type_metrics(dt)
        items.append({"type": dt, "name": name, "ts": ts, "td": td,
                      "id": eid_int(dt.Id)})
    items.sort(key=lambda i: i["name"].lower())
    return items


def show_settings(view, kind, has_links, start_linked):
    types = collect_dim_types()
    if not types:
        alert("No linear dimension types found in this project.")
        return None

    window = XamlReader.Parse(XAML)
    find = window.FindName
    subtitle = find("SubTitle")
    search = find("SearchBox")
    lst = find("TypeList")
    host_btn = find("HostBtn")
    link_btn = find("LinkBtn")
    factor_box = find("FactorBox")
    preview = find("Preview")
    ok_btn = find("OkBtn")
    cancel_btn = find("CancelBtn")

    try:
        WindowInteropHelper(window).Owner = __revit__.MainWindowHandle
    except Exception:
        pass

    scale = view.Scale
    if kind == "plan":
        subtitle.Text = ("Plan view 1:{}  -  dimensions the wall length, "
                         "placed above the wall.").format(scale)
    else:
        subtitle.Text = ("Elevation / section 1:{}  -  dimensions the wall height, "
                         "placed to the left of the wall.").format(scale)

    default_id = eid_int(doc.GetDefaultElementTypeId(ElementTypeGroup.LinearDimensionType))
    state = {"filtered": [], "selected_id": default_id, "result": None}

    def selected():
        idx = lst.SelectedIndex
        if 0 <= idx < len(state["filtered"]):
            return state["filtered"][idx]
        return None

    def parse_factor():
        try:
            f = float(factor_box.Text.strip().replace(",", "."))
            return f if f > 0 else None
        except Exception:
            return None

    def update_preview():
        item = selected()
        factor = parse_factor()
        if item is None:
            preview.Text = "Select a dimension type."
            return
        if factor is None:
            preview.Text = "Spacing factor must be a positive number."
            return
        near, far = compute_offsets(item["ts"], item["td"], scale, factor)
        preview.Text = (u"Text {:.1f} mm  \u00B7  detailed line {:.0f} mm  \u00B7  "
                        u"overall line {:.0f} mm from the wall edge").format(
            item["ts"] * FT_TO_MM, near * FT_TO_MM, far * FT_TO_MM)

    def refresh_list():
        text = search.Text.strip().lower()
        state["filtered"] = [i for i in types if text in i["name"].lower()]
        lst.Items.Clear()
        sel_idx = -1
        for n, item in enumerate(state["filtered"]):
            lst.Items.Add(u"{}   \u00B7   {:.1f} mm text".format(
                item["name"], item["ts"] * FT_TO_MM))
            if item["id"] == state["selected_id"]:
                sel_idx = n
        if sel_idx < 0 and state["filtered"]:
            sel_idx = 0
        lst.SelectedIndex = sel_idx
        if sel_idx >= 0:
            lst.ScrollIntoView(lst.Items[sel_idx])
        update_preview()

    def on_search(sender, e):
        refresh_list()

    def on_select(sender, e):
        item = selected()
        if item is not None:
            state["selected_id"] = item["id"]
        update_preview()

    def on_factor(sender, e):
        update_preview()

    def on_source(sender, e):
        host_btn.IsChecked = sender is host_btn
        link_btn.IsChecked = sender is link_btn

    if not has_links:
        link_btn.IsEnabled = False
        link_btn.Content = "No loaded links"
    elif start_linked:
        host_btn.IsChecked = False
        link_btn.IsChecked = True

    def on_ok(sender, e):
        item = selected()
        factor = parse_factor()
        if item is None or factor is None:
            update_preview()
            return
        state["result"] = {
            "dim_type": item["type"],
            "linked": bool(link_btn.IsChecked),
            "offsets": compute_offsets(item["ts"], item["td"], scale, factor),
        }
        window.Close()

    def on_cancel(sender, e):
        window.Close()

    def on_double(sender, e):
        if selected() is not None:
            on_ok(sender, e)

    search.TextChanged += TextChangedEventHandler(on_search)
    lst.SelectionChanged += SelectionChangedEventHandler(on_select)
    lst.MouseDoubleClick += MouseButtonEventHandler(on_double)
    factor_box.TextChanged += TextChangedEventHandler(on_factor)
    host_btn.Click += RoutedEventHandler(on_source)
    link_btn.Click += RoutedEventHandler(on_source)
    ok_btn.Click += RoutedEventHandler(on_ok)
    cancel_btn.Click += RoutedEventHandler(on_cancel)

    refresh_list()

    frame = DispatcherFrame()

    def on_closed(sender, e):
        frame.Continue = False

    window.Closed += EventHandler(on_closed)
    window.Show()
    search.Focus()
    Dispatcher.PushFrame(frame)
    return state["result"]


# -------------------------------------------------------------------- main
def loaded_links():
    links = []
    for li in FilteredElementCollector(doc).OfClass(RevitLinkInstance):
        try:
            if li.GetLinkDocument() is not None:
                links.append(li)
        except Exception:
            pass
    return links


def main():
    view = doc.ActiveView
    kind = get_view_kind(view)
    if kind is None:
        alert("Run this tool in a plan, elevation or section view.")
        return

    has_links = len(loaded_links()) > 0

    # Pre-selection: host walls by id, linked walls via selected references
    pre_host, seen = [], set()
    for i in uidoc.Selection.GetElementIds():
        w = host_curtain_wall(doc.GetElement(i))
        if w is not None and eid_int(w.Id) not in seen:
            seen.add(eid_int(w.Id))
            pre_host.append(w)
    pre_link, seen = [], set()
    try:
        for r in uidoc.Selection.GetReferences():
            link = doc.GetElement(r.ElementId)
            if isinstance(link, RevitLinkInstance) and link.GetLinkDocument() is not None:
                w = host_curtain_wall(link.GetLinkDocument().GetElement(r.LinkedElementId))
                key = (eid_int(link.Id), eid_int(w.Id)) if w is not None else None
                if key is not None and key not in seen:
                    seen.add(key)
                    pre_link.append((w, link))
    except Exception:
        pass  # Selection.GetReferences not available in this Revit version

    settings = show_settings(view, kind, has_links,
                             start_linked=bool(pre_link) and not pre_host)
    if settings is None:
        return

    done = [0]
    issues = []

    def process(wall, source):
        ok, msg = dimension_wall(wall, source, view, kind, settings)
        if ok:
            done[0] += 1
        if msg:
            issues.append("{}: {}".format(source.label(wall), msg))

    if settings["linked"]:
        if pre_link:
            for wall, link in pre_link:
                process(wall, Source(link))
        else:
            sel_filter = LinkedCurtainWallFilter()
            while True:
                try:
                    ref = uidoc.Selection.PickObject(
                        ObjectType.LinkedElement, sel_filter,
                        "Pick a curtain wall inside a link (Esc to finish)")
                except OperationCanceledException:
                    break
                link = doc.GetElement(ref.ElementId)
                wall = host_curtain_wall(
                    link.GetLinkDocument().GetElement(ref.LinkedElementId))
                if wall is not None:
                    process(wall, Source(link))
    else:
        if pre_host:
            for wall in pre_host:
                process(wall, Source())
        else:
            sel_filter = CurtainWallFilter()
            while True:
                try:
                    ref = uidoc.Selection.PickObject(
                        ObjectType.Element, sel_filter,
                        "Pick a curtain wall (Esc to finish)")
                except OperationCanceledException:
                    break
                wall = host_curtain_wall(doc.GetElement(ref.ElementId))
                if wall is not None:
                    process(wall, Source())

    if issues:
        alert("Dimensioned {} wall(s).\n\n{}".format(done[0], "\n".join(issues)))


main()
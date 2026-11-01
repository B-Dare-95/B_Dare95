# -*- coding: utf-8 -*-
__doc__ = """__________________________________________________
Description:

Fits walls to the structure: the base sits on the structural slab below, the top stops under the slab above, and walls are cut where beams pass through.
Slabs and beams can come from your model and loaded links; only the offsets change.
__________________________________________________
How-to:

-> Click on the button
-> Choose slabs and/or beams, and your model and/or links
-> Choose to pick walls or use all walls in the active view
-> Draw a box around the walls to process
-> Check the summary and click Yes to apply
__________________________________________________
Author: Mohamed Bedair"""


__author__ = 'B-Dare95'

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('System')
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')

from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory, BuiltInParameter,
    Wall, WallKind, WallUtils, RevitLinkInstance, Level,
    Line, XYZ, LocationCurve, LocationPoint, FamilyInstance, Opening,
    ElementId, ElementTransformUtils,
    Transaction, TransactionGroup, TransactionStatus,
    Options, ViewDetailLevel, Solid, GeometryInstance, CurveLoop, PlanarFace,
    GeometryCreationUtilities, BooleanOperationsUtils, BooleanOperationsType,
    SolidUtils, Outline, BoundingBoxIntersectsFilter, JoinGeometryUtils,
    IFailuresPreprocessor, FailureSeverity, FailureProcessingResult
)
from Autodesk.Revit.DB.Structure import StructuralType
from Autodesk.Revit.UI.Selection import ISelectionFilter

from System import EventHandler
from System.Collections.Generic import List
from System.Windows import RoutedEventHandler
from System.Windows.Markup import XamlReader
from System.Windows.Threading import Dispatcher, DispatcherFrame

from pyrevit import revit, forms, script

doc = revit.doc
uidoc = revit.uidoc

TITLE = 'Split Walls at Beams & Slabs'

# Notes gathered at startup, surfaced in the first completion dialog so the
# pyRevit output console never has to open.
STARTUP_NOTES = []

# ---------------------------------------------------------------------------
# Tolerances (feet - Revit internal units)
# ---------------------------------------------------------------------------
MM = 1.0 / 304.8
EPS = 1e-6
CHANGE_TOL = 2.0 * MM        # result within this of the original = no change
MIN_CLASH_DEPTH = 10.0 * MM  # min overlap INTO the wall thickness to count
MIN_CLASH_SIZE = 3.0 * MM    # min overlap along the wall and vertically
MIN_SOLID_VOL = 1e-6         # cubic feet
NOISE_TOL = 2.0 * MM         # free bands thinner than this are boolean noise
SLAB_SEARCH = 1000.0 * MM    # slab top within this of the wall's current base
                             # (or top) = the slab below (or above) it
SLAB_PAD = 2000.0 * MM       # extra search depth so whole slabs are measured
BEAM_SNAP_TOL = 50.0 * MM    # beam top this close to the soffit = under slab
MIN_PIECE_LENGTH = 50.0 * MM # cuts closer than this along the wall are merged
FIT_TOL = 0.01               # slack for an insert along the wall
Z_FIT_TOL = 0.1              # slack for an insert vertically (frames/sills)
END_TOL = 1e-6

MAX_REPORT_ITEMS = 10
MAX_REPORT_IDS = 30
PROGRESS_THRESHOLD = 15      # show a progress bar above this many walls


def eid_int(eid):
    try:
        return eid.Value
    except AttributeError:
        return eid.IntegerValue


def eid_str(eid):
    return str(eid_int(eid))


def _bip(name):
    return getattr(BuiltInParameter, name, None)


BIP_TOP_ATTACHED = _bip('WALL_TOP_IS_ATTACHED')
BIP_BASE_ATTACHED = _bip('WALL_BOTTOM_IS_ATTACHED')
BIP_FLOOR_STRUCTURAL = _bip('FLOOR_PARAM_IS_STRUCTURAL')


def param_is_true(el, bip):
    if bip is None:
        return False
    p = el.get_Parameter(bip)
    return p is not None and p.HasValue and p.AsInteger() == 1


def param_double(el, bip, default=0.0):
    p = el.get_Parameter(bip)
    if p is None or not p.HasValue:
        return default
    return p.AsDouble()


class SilentFailures(IFailuresPreprocessor):
    """Answers Revit's failure dialogs the way you would by hand: warnings
    are dismissed (OK) and errors get their default resolution (e.g.
    'Unjoin Elements'). An error with no resolution rolls the wall back and
    is reported instead of shown."""

    def __init__(self, handled, fatal):
        self.handled = handled      # {(description, action): count}
        self.fatal = fatal          # descriptions that forced a rollback

    def PreprocessFailures(self, accessor):
        resolved = False
        for fm in accessor.GetFailureMessages():
            text = fm.GetDescriptionText()
            severity = fm.GetSeverity()
            if severity == FailureSeverity.Warning:
                accessor.DeleteWarning(fm)
                action = 'OK'
            elif severity == FailureSeverity.Error and fm.HasResolutions():
                try:
                    action = fm.GetDefaultResolutionCaption()
                except Exception:
                    action = 'resolved'
                accessor.ResolveFailure(fm)
                resolved = True
            else:
                self.fatal.append(text)
                continue
            key = (text, action)
            self.handled[key] = self.handled.get(key, 0) + 1
        if self.fatal:
            return FailureProcessingResult.ProceedWithRollBack
        if resolved:
            return FailureProcessingResult.ProceedWithCommit
        return FailureProcessingResult.Continue


def make_silent(t, handled, fatal):
    """Attach SilentFailures to a started transaction."""
    opts = t.GetFailureHandlingOptions()
    opts.SetFailuresPreprocessor(SilentFailures(handled, fatal))
    opts.SetClearAfterRollback(True)
    t.SetFailureHandlingOptions(opts)


def set_param(el, bip, value):
    p = el.get_Parameter(bip)
    if p is None:
        raise Exception('parameter {} not found'.format(bip))
    if not p.Set(value):
        raise Exception('could not set {}'.format(bip))


# ---------------------------------------------------------------------------
# 1. Settings (remembered between runs) + WPF dialog
# ---------------------------------------------------------------------------
DEFAULTS = {
    'use_beams': True,
    'use_slabs': True,
    'use_host': True,
    'use_links': True,
    'scope': 'pick',             # 'pick' | 'view'
}


def load_settings():
    s = dict(DEFAULTS)
    try:
        cfg = script.get_config()
        for key, default in DEFAULTS.items():
            raw = cfg.get_option(key, None)
            if raw is None:
                continue
            raw = str(raw)
            if isinstance(default, bool):
                s[key] = raw.lower() in ('true', '1', 'yes')
            else:
                s[key] = raw
    except Exception:
        pass
    return s


def save_settings(s):
    try:
        cfg = script.get_config()
        for key in DEFAULTS:
            setattr(cfg, key, str(s[key]))
        script.save_config()
    except Exception:
        pass


XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Split Walls at Beams &amp; Slabs"
        Width="480" SizeToContent="Height" ResizeMode="NoResize"
        WindowStartupLocation="CenterScreen"
        Background="#161616" Foreground="#F4F4F4"
        FontFamily="Segoe UI" FontSize="12">
  <Window.Resources>
    <Style x:Key="Chip" TargetType="ToggleButton">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="BorderBrush" Value="#525252"/>
      <Setter Property="Padding" Value="10,6"/>
      <Setter Property="Margin" Value="0,0,6,6"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ToggleButton">
            <Border x:Name="Bd" Background="{TemplateBinding Background}"
                    BorderBrush="{TemplateBinding BorderBrush}"
                    BorderThickness="1" CornerRadius="4"
                    Padding="{TemplateBinding Padding}">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="Bd" Property="BorderBrush" Value="#F1C21B"/>
              </Trigger>
              <Trigger Property="IsChecked" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#F1C21B"/>
                <Setter TargetName="Bd" Property="BorderBrush" Value="#F1C21B"/>
                <Setter Property="Foreground" Value="#161616"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="Primary" TargetType="Button">
      <Setter Property="Foreground" Value="#161616"/>
      <Setter Property="Background" Value="#F1C21B"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
      <Setter Property="Padding" Value="20,7"/>
      <Setter Property="Margin" Value="8,0,0,0"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="Bd" Background="{TemplateBinding Background}"
                    CornerRadius="4" Padding="{TemplateBinding Padding}">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="Bd" Property="Opacity" Value="0.85"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="Secondary" TargetType="Button">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="Padding" Value="20,7"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="Bd" Background="{TemplateBinding Background}"
                    CornerRadius="4" Padding="{TemplateBinding Padding}">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#525252"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="Card" TargetType="Border">
      <Setter Property="Background" Value="#262626"/>
      <Setter Property="CornerRadius" Value="6"/>
      <Setter Property="Padding" Value="12,10,12,6"/>
      <Setter Property="Margin" Value="0,0,0,10"/>
    </Style>
    <Style x:Key="Head" TargetType="TextBlock">
      <Setter Property="Foreground" Value="#A8A8A8"/>
      <Setter Property="FontSize" Value="11"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
      <Setter Property="Margin" Value="0,0,0,8"/>
    </Style>
    <Style x:Key="Hint" TargetType="TextBlock">
      <Setter Property="Foreground" Value="#A8A8A8"/>
      <Setter Property="FontSize" Value="11"/>
      <Setter Property="TextWrapping" Value="Wrap"/>
      <Setter Property="Margin" Value="0,0,0,6"/>
    </Style>
  </Window.Resources>

  <StackPanel Margin="16">
    <TextBlock Text="Split Walls at Beams &amp; Slabs" FontSize="18" FontWeight="SemiBold"/>
    <TextBlock Style="{StaticResource Hint}" Margin="0,4,0,14"
               Text="Stretches walls to rest on the structural slab below and stop at the slab soffit above, and cuts them where beams pass through. Beams and slabs are read from the active model and/or loaded links."/>

    <Border Style="{StaticResource Card}">
      <StackPanel>
        <TextBlock Style="{StaticResource Head}" Text="FIT WALLS TO"/>
        <WrapPanel>
          <ToggleButton x:Name="chipSlabs" Style="{StaticResource Chip}" Content="Structural slabs (base &amp; top)"/>
          <ToggleButton x:Name="chipBeams" Style="{StaticResource Chip}" Content="Beams (lower top / cut)"/>
        </WrapPanel>
        <TextBlock Style="{StaticResource Head}" Text="READ BEAMS AND SLABS FROM" Margin="0,4,0,8"/>
        <WrapPanel>
          <ToggleButton x:Name="chipHost" Style="{StaticResource Chip}" Content="Active model"/>
          <ToggleButton x:Name="chipLinks" Style="{StaticResource Chip}" Content="Loaded links"/>
        </WrapPanel>
        <TextBlock Style="{StaticResource Hint}"
                   Text="Base and top constraints stay as they are; only Base Offset and Top Offset (or Unconnected Height) change."/>
      </StackPanel>
    </Border>

    <Border Style="{StaticResource Card}">
      <StackPanel>
        <TextBlock Style="{StaticResource Head}" Text="WALLS TO PROCESS"/>
        <WrapPanel>
          <ToggleButton x:Name="rbScopePick" Style="{StaticResource Chip}" Content="Pick walls (rectangle)"/>
          <ToggleButton x:Name="rbScopeView" Style="{StaticResource Chip}" Content="All walls in active view"/>
        </WrapPanel>
        <TextBlock Style="{StaticResource Hint}"
                   Text="Pick: walls already selected are processed first, then you can keep picking until you stop."/>
      </StackPanel>
    </Border>

    <TextBlock x:Name="txtStatus" Foreground="#FA4D56" TextWrapping="Wrap" Margin="0,0,0,8"/>

    <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
      <Button x:Name="btnCancel" Style="{StaticResource Secondary}" Content="Cancel" IsCancel="True"/>
      <Button x:Name="btnRun" Style="{StaticResource Primary}" Content="Run" IsDefault="True"/>
    </StackPanel>
  </StackPanel>
</Window>
"""


def make_radio_handler(group):
    """Clicking any ToggleButton in the group checks it and clears the rest."""
    def handler(sender, e):
        for tb in group:
            tb.IsChecked = (tb.Name == sender.Name)
    return RoutedEventHandler(handler)


def show_settings(current):
    window = XamlReader.Parse(XAML)
    find = window.FindName

    chips = {
        'use_beams': find('chipBeams'),
        'use_slabs': find('chipSlabs'),
        'use_host': find('chipHost'),
        'use_links': find('chipLinks'),
    }
    for key, tb in chips.items():
        tb.IsChecked = bool(current[key])

    radio_groups = [
        ('scope', [(find('rbScopePick'), 'pick'), (find('rbScopeView'), 'view')]),
    ]
    for key, options in radio_groups:
        buttons = [tb for tb, _ in options]
        handler = make_radio_handler(buttons)
        for tb, value in options:
            tb.IsChecked = (current[key] == value)
            tb.Click += handler

    status = find('txtStatus')

    result = {'settings': None}
    frame = DispatcherFrame()

    def on_run(sender, e):
        new = dict(current)
        for key, tb in chips.items():
            new[key] = bool(tb.IsChecked)
        for key, options in radio_groups:
            for tb, value in options:
                if tb.IsChecked:
                    new[key] = value
        if not (new['use_beams'] or new['use_slabs']):
            status.Text = 'Choose at least one of Beams / Slabs.'
            return
        if not (new['use_host'] or new['use_links']):
            status.Text = 'Choose at least one of Active model / Loaded links.'
            return
        result['settings'] = new
        window.Close()

    def on_cancel(sender, e):
        window.Close()

    def on_closed(sender, e):
        frame.Continue = False

    find('btnRun').Click += RoutedEventHandler(on_run)
    find('btnCancel').Click += RoutedEventHandler(on_cancel)
    window.Closed += EventHandler(on_closed)

    try:
        from System.Windows.Interop import WindowInteropHelper
        WindowInteropHelper(window).Owner = __revit__.MainWindowHandle
    except Exception:
        pass

    window.Show()
    Dispatcher.PushFrame(frame)
    return result['settings']


# ---------------------------------------------------------------------------
# 2. Sources of beams / slabs (active doc + loaded links)
# ---------------------------------------------------------------------------
class Source(object):
    """A document to read cutters from. transform is None for the active doc;
    for a link it maps link coordinates -> host coordinates."""

    def __init__(self, key, label, source_doc, transform):
        self.key = key
        self.label = label
        self.doc = source_doc
        self.transform = transform
        self.inverse = transform.Inverse if transform is not None else None


def collect_sources(settings):
    sources = []
    unloaded = []
    if settings['use_host']:
        sources.append(Source('host', 'Active model', doc, None))
    if settings['use_links']:
        for link_inst in FilteredElementCollector(doc).OfClass(RevitLinkInstance):
            link_doc = link_inst.GetLinkDocument()
            if link_doc is None:
                unloaded.append(link_inst.Name)
                continue
            sources.append(Source('link_' + eid_str(link_inst.Id), link_inst.Name,
                                  link_doc, link_inst.GetTotalTransform()))
    return sources, unloaded


# ---------------------------------------------------------------------------
# 3. Geometry helpers
# ---------------------------------------------------------------------------
GEOM_OPTS = Options()
GEOM_OPTS.DetailLevel = ViewDetailLevel.Fine
GEOM_OPTS.ComputeReferences = False
GEOM_OPTS.IncludeNonVisibleObjects = False

_SOLID_CACHE = {}


def _gather_solids(geom, out):
    if geom is None:
        return
    for g in geom:
        if isinstance(g, Solid):
            try:
                if g.Volume > MIN_SOLID_VOL:
                    out.append(g)
            except Exception:
                pass
        elif isinstance(g, GeometryInstance):
            _gather_solids(g.GetInstanceGeometry(), out)


def element_solids(el):
    out = []
    try:
        _gather_solids(el.get_Geometry(GEOM_OPTS), out)
    except Exception:
        pass
    return out


def cutter_solids(src, el, use_cache):
    if not use_cache:
        return element_solids(el)
    key = (src.key, eid_str(el.Id))
    if key not in _SOLID_CACHE:
        _SOLID_CACHE[key] = element_solids(el)
    return _SOLID_CACHE[key]


def solid_points(solid):
    pts = []
    for edge in solid.Edges:
        for p in edge.Tessellate():
            pts.append(p)
    return pts


def intersect_lumps(box, solid):
    """Separate lumps of box AND solid. [] if they don't meet, None if the
    boolean itself failed."""
    try:
        inter = BooleanOperationsUtils.ExecuteBooleanOperation(
            box, solid, BooleanOperationsType.Intersect)
    except Exception:
        return None
    if inter is None:
        return []
    try:
        if inter.Volume < MIN_SOLID_VOL:
            return []
    except Exception:
        return None
    try:
        parts = [p for p in SolidUtils.SplitVolumes(inter) if p.Volume > MIN_SOLID_VOL]
        return parts if parts else [inter]
    except Exception:
        return [inter]


def outline_of(points):
    xs = [p.X for p in points]
    ys = [p.Y for p in points]
    zs = [p.Z for p in points]
    return Outline(XYZ(min(xs), min(ys), min(zs)), XYZ(max(xs), max(ys), max(zs)))


# ---------------------------------------------------------------------------
# 4. Wall frame: the wall as a box in (u along wall, v across, z up)
# ---------------------------------------------------------------------------
class WallFrame(object):
    pass


def wall_skip_reason(wall):
    if getattr(wall, 'IsStackedWallMember', False):
        return 'part of a stacked wall'
    try:
        if wall.WallType.Kind != WallKind.Basic:
            return 'not a Basic wall (stacked/curtain)'
    except Exception:
        return 'could not read wall type'
    if eid_int(wall.GroupId) != -1:
        return 'inside a group'
    if wall.Pinned:
        return 'pinned'
    if param_is_true(wall, BIP_TOP_ATTACHED) or param_is_true(wall, BIP_BASE_ATTACHED):
        return 'top or base attached (detach first)'
    sketch_id = getattr(wall, 'SketchId', None)
    if sketch_id is not None and eid_int(sketch_id) != -1:
        return 'has an edited profile'
    return None


def build_frame(wall):
    loc = wall.Location
    if not isinstance(loc, LocationCurve):
        return None, 'no location curve'
    curve = loc.Curve
    if not isinstance(curve, Line):
        return None, 'not a straight wall'

    p0 = curve.GetEndPoint(0)
    p1 = curve.GetEndPoint(1)
    flat = XYZ(p1.X - p0.X, p1.Y - p0.Y, 0.0)
    length = flat.GetLength()
    if length < MIN_CLASH_SIZE:
        return None, 'wall too short'

    base_level = doc.GetElement(
        wall.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT).AsElementId())
    if not isinstance(base_level, Level):
        return None, 'could not read base constraint'
    base_z = base_level.ProjectElevation
    zb = base_z + param_double(wall, BuiltInParameter.WALL_BASE_OFFSET)

    top_level = doc.GetElement(
        wall.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE).AsElementId())
    if isinstance(top_level, Level):
        zt = top_level.ProjectElevation + param_double(wall, BuiltInParameter.WALL_TOP_OFFSET)
    else:
        zt = zb + param_double(wall, BuiltInParameter.WALL_USER_HEIGHT_PARAM)
    if zt - zb < MIN_CLASH_SIZE:
        return None, 'zero height'

    fr = WallFrame()
    fr.wall = wall
    fr.p0 = p0
    fr.d = flat.Normalize()
    fr.n = XYZ(-fr.d.Y, fr.d.X, 0.0)
    fr.length = length
    fr.zb = zb
    fr.zt = zt
    fr.base_z = base_z
    fr.top_z = top_level.ProjectElevation if isinstance(top_level, Level) else None

    # Real faces across the wall, measured from the wall's own solid. The
    # location line can sit on a face or the core, so don't assume centred.
    vs = []
    for solid in element_solids(wall):
        for p in solid_points(solid):
            vs.append((p - p0).DotProduct(fr.n))
    if vs:
        fr.vmin, fr.vmax = min(vs), max(vs)
    else:
        half = wall.Width / 2.0
        fr.vmin, fr.vmax = -half, half
    return fr, None


def make_box(fr, z0, z1):
    """Solid of the wall's footprint (full length x real thickness) between
    z0 and z1, ignoring joins, openings and cuts by other elements."""
    base = XYZ(fr.p0.X, fr.p0.Y, z0)
    across = fr.n.Multiply(fr.vmax - fr.vmin)
    a = base + fr.n.Multiply(fr.vmin)
    b = a + fr.d.Multiply(fr.length)
    c = b + across
    e = a + across
    loop = CurveLoop()
    loop.Append(Line.CreateBound(a, b))
    loop.Append(Line.CreateBound(b, c))
    loop.Append(Line.CreateBound(c, e))
    loop.Append(Line.CreateBound(e, a))
    loops = List[CurveLoop]()
    loops.Add(loop)
    height = z1 - z0
    box = GeometryCreationUtilities.CreateExtrusionGeometry(loops, XYZ.BasisZ, height)
    up = XYZ(0.0, 0.0, height)
    corners = [a, b, c, e, a + up, b + up, c + up, e + up]
    return box, corners


# ---------------------------------------------------------------------------
# 5. Reading the structure around a wall
#    - slabs set the new base (slab top below) and top (soffit above)
#    - beams, and any slab the wall passes through mid-height, cut it
# ---------------------------------------------------------------------------
class Rect(object):
    def __init__(self, u0, u1, z0, z1, kind):
        self.u0 = u0
        self.u1 = u1
        self.z0 = z0
        self.z1 = z1
        self.kind = kind     # 'beam' | 'slab'


class SlabLump(object):
    """One part of a structural slab inside the wall's footprint."""

    def __init__(self, key, u0, u1, zmin, zmax, ups, downs):
        self.key = key
        self.u0 = u0
        self.u1 = u1
        self.zmin = zmin
        self.zmax = zmax
        # Horizontal faces within the footprint. A slab with a drop or a
        # sunken area has several tops / soffits.
        self.lowest_top = min(ups) if ups else zmax
        self.highest_soffit = max(downs) if downs else zmin


class Adjustment(object):
    """Target base/top for a wall plus the rectangles that cut it."""

    def __init__(self, fr):
        self.zb = fr.zb
        self.zt = fr.zt
        self.base_found = False
        self.top_found = False
        self.rects = []
        self.hits = {'beam': set(), 'slab': set()}
        self.failed = []
        self.notes = []


def is_brace(el):
    try:
        return el.StructuralType == StructuralType.Brace
    except Exception:
        return False


def is_structural_floor(el):
    return param_is_true(el, BIP_FLOOR_STRUCTURAL)


def beam_elements(src, outline):
    for el in FilteredElementCollector(src.doc)\
            .OfCategory(BuiltInCategory.OST_StructuralFraming)\
            .WhereElementIsNotElementType()\
            .WherePasses(BoundingBoxIntersectsFilter(outline)):
        if not is_brace(el):
            yield el


def slab_elements(src, outline):
    for el in FilteredElementCollector(src.doc)\
            .OfCategory(BuiltInCategory.OST_Floors)\
            .WhereElementIsNotElementType()\
            .WherePasses(BoundingBoxIntersectsFilter(outline)):
        if is_structural_floor(el):
            yield el


def in_source(src, box, corners):
    """The host-space box and its corners, expressed in the source's coords."""
    if src.transform is None:
        return box, corners
    return (SolidUtils.CreateTransformed(box, src.inverse),
            [src.inverse.OfPoint(c) for c in corners])


def frame_extents(points, fr, transform):
    """(u0, u1, v0, v1, z0, z1) of source-space points on the wall frame."""
    if not points:
        return None
    us, vs, zs = [], [], []
    for p in points:
        if transform is not None:
            p = transform.OfPoint(p)
        vec = p - fr.p0
        us.append(vec.DotProduct(fr.d))
        vs.append(vec.DotProduct(fr.n))
        zs.append(p.Z)
    return (min(us), max(us), min(vs), max(vs), min(zs), max(zs))


def overlaps_wall(ext, fr, z_lo, z_hi):
    u0, u1, v0, v1, z0, z1 = ext
    depth = min(v1, fr.vmax) - max(v0, fr.vmin)
    along = min(u1, fr.length) - max(u0, 0.0)
    up = min(z1, z_hi) - max(z0, z_lo)
    return depth >= MIN_CLASH_DEPTH and along >= MIN_CLASH_SIZE and up >= MIN_CLASH_SIZE


def horizontal_faces(lump, transform):
    ups, downs = [], []
    for face in lump.Faces:
        if not isinstance(face, PlanarFace):
            continue
        normal = face.FaceNormal
        origin = face.Origin
        if transform is not None:
            normal = transform.OfVector(normal)
            origin = transform.OfPoint(origin)
        if normal.Z > 0.999:
            ups.append(origin.Z)
        elif normal.Z < -0.999:
            downs.append(origin.Z)
    return ups, downs


def scan_slabs(fr, ctx, in_probe, adj):
    lo = fr.zb - SLAB_SEARCH - SLAB_PAD
    hi = fr.zt + SLAB_SEARCH + SLAB_PAD
    box, corners = make_box(fr, lo, hi)
    lumps = []
    for src in ctx['sources']:
        box_s, pts = in_source(src, box, corners)
        # Solids read inside a rolled-back probe are never cached.
        use_cache = not (in_probe and src.transform is None)
        for el in slab_elements(src, outline_of(pts)):
            key = (src.key, eid_str(el.Id))
            for solid in cutter_solids(src, el, use_cache):
                parts = intersect_lumps(box_s, solid)
                if parts is None:
                    # A slab's own extent would swallow its openings and
                    # steps, so a failed boolean is reported, not guessed.
                    adj.failed.append('{}: slab {}'.format(src.label, key[1]))
                    continue
                for lump in parts:
                    ext = frame_extents(solid_points(lump), fr, src.transform)
                    if ext is None or not overlaps_wall(ext, fr, lo, hi):
                        continue
                    ups, downs = horizontal_faces(lump, src.transform)
                    lumps.append(SlabLump(key, max(ext[0], 0.0), min(ext[1], fr.length),
                                          ext[4], ext[5], ups, downs))
    return lumps


def apply_slabs(lumps, fr, adj):
    """Slab below -> new base, slab above -> new top, anything between
    (a multi-storey wall) -> a cut."""
    below = [l for l in lumps if abs(l.zmax - fr.zb) <= SLAB_SEARCH]
    above = [l for l in lumps
             if l not in below and abs(l.zmax - fr.zt) <= SLAB_SEARCH]

    if below:
        adj.zb = min(l.lowest_top for l in below)
        adj.base_found = True
        for l in below:
            adj.hits['slab'].add(l.key)
    if above:
        top = max(l.highest_soffit for l in above)
        if top > adj.zb + NOISE_TOL:
            adj.zt = top
            adj.top_found = True
            for l in above:
                adj.hits['slab'].add(l.key)

    for l in lumps:
        if l in below or l in above:
            continue
        if min(l.zmax, adj.zt) - max(l.zmin, adj.zb) >= MIN_CLASH_SIZE:
            adj.rects.append(Rect(l.u0, l.u1, l.zmin, l.zmax, 'slab'))
            adj.hits['slab'].add(l.key)


def scan_beams(fr, ctx, in_probe, adj):
    box, corners = make_box(fr, adj.zb, adj.zt)
    for src in ctx['sources']:
        box_s, pts = in_source(src, box, corners)
        use_cache = not (in_probe and src.transform is None)
        for el in beam_elements(src, outline_of(pts)):
            hit = False
            for solid in cutter_solids(src, el, use_cache):
                parts = intersect_lumps(box_s, solid)
                # Boolean failed: a beam is compact, so its own extent
                # clipped to the wall is a safe stand-in.
                point_sets = [solid_points(solid)] if parts is None \
                    else [solid_points(part) for part in parts]
                for points in point_sets:
                    ext = frame_extents(points, fr, src.transform)
                    if ext is None or not overlaps_wall(ext, fr, adj.zb, adj.zt):
                        continue
                    z0, z1 = ext[4], ext[5]
                    # A beam right under the slab takes the band up to the
                    # soffit (top simply lowered); same at the slab below.
                    if z1 >= adj.zt - BEAM_SNAP_TOL:
                        z1 = max(z1, adj.zt)
                    if z0 <= adj.zb + BEAM_SNAP_TOL:
                        z0 = min(z0, adj.zb)
                    adj.rects.append(Rect(max(ext[0], 0.0), min(ext[1], fr.length),
                                          z0, z1, 'beam'))
                    hit = True
            if hit:
                adj.hits['beam'].add((src.key, eid_str(el.Id)))


def measure_wall(fr, ctx, in_probe):
    adj = Adjustment(fr)
    settings = ctx['settings']
    if settings['use_slabs']:
        apply_slabs(scan_slabs(fr, ctx, in_probe, adj), fr, adj)
    if settings['use_beams']:
        scan_beams(fr, ctx, in_probe, adj)
    return adj


def host_cutters_cut_by_wall(wall):
    """Active-model elements joined to the wall where the WALL is the cutting
    element - their solids have the wall carved out of them, so they would
    look as if they don't touch it at all."""
    out = []
    try:
        joined = JoinGeometryUtils.GetJoinedElements(doc, wall)
    except Exception:
        return out
    for jid in joined:
        other = doc.GetElement(jid)
        if other is None:
            continue
        try:
            if JoinGeometryUtils.IsCuttingElementInJoin(doc, wall, other):
                out.append(other)
        except Exception:
            pass
    return out


def find_adjustment(fr, ctx):
    has_host = any(src.transform is None for src in ctx['sources'])
    carved = host_cutters_cut_by_wall(fr.wall) if has_host else []
    if not carved:
        return measure_wall(fr, ctx, False)

    # Probe: temporarily unjoin so the carved elements show their full
    # solids, measure, then roll back. Nothing here is ever committed.
    adj = None
    t = Transaction(doc, 'Probe wall joins')
    t.Start()
    make_silent(t, {}, [])
    try:
        for other in carved:
            JoinGeometryUtils.UnjoinGeometry(doc, fr.wall, other)
        doc.Regenerate()
        adj = measure_wall(fr, ctx, True)
    except Exception:
        adj = None
    t.RollBack()

    if adj is None:
        adj = measure_wall(fr, ctx, False)
        adj.notes.append('Wall {}: joined elements could not be unjoined for '
                         'measuring; their cut geometry was used.'
                         .format(eid_str(fr.wall.Id)))
    return adj


# ---------------------------------------------------------------------------
# 6. Decompose the wall elevation minus the rectangles into pieces
#    (pure Python - no Revit API below this line until section 7)
# ---------------------------------------------------------------------------
def merge_intervals(intervals):
    ivs = sorted(iv for iv in intervals if iv[1] - iv[0] > EPS)
    merged = []
    for a, b in ivs:
        if merged and a <= merged[-1][1] + EPS:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged]


def complement(occupied, lo, hi):
    free = []
    cursor = lo
    for a, b in occupied:
        if a > cursor:
            free.append((cursor, a))
        cursor = max(cursor, b)
    if hi > cursor:
        free.append((cursor, hi))
    return free


def snap_breakpoints(values, length, snap):
    """Sorted cut positions along the wall; anything closer than `snap` to a
    kept position (or to either end) is dropped so no sliver strips appear."""
    inner = sorted(v for v in values if snap <= v <= length - snap)
    kept = [0.0]
    for v in inner:
        if v - kept[-1] >= snap:
            kept.append(v)
    kept.append(length)
    return kept


def same_intervals(a, b, tol):
    if len(a) != len(b):
        return False
    for (a0, a1), (b0, b1) in zip(a, b):
        if abs(a0 - b0) > tol or abs(a1 - b1) > tol:
            return False
    return True


def build_pieces(rects, length, zb, zt):
    """Returns [(u0, u1, z0, z1), ...] - rectangular wall pieces that avoid
    every rectangle. Strips along the wall are cut at rectangle edges, each
    strip gets its free vertical intervals, then neighbouring strips with the
    same intervals are merged back together."""
    snap = MIN_PIECE_LENGTH
    cuts = []
    for r in rects:
        cuts.append(r.u0)
        cuts.append(r.u1)
    pts = snap_breakpoints(cuts, length, snap)

    strips = []
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        mid = 0.5 * (a + b)
        cover = [r for r in rects if r.u0 - EPS <= mid <= r.u1 + EPS]
        occupied = merge_intervals(
            [(max(r.z0, zb), min(r.z1, zt)) for r in cover])
        free = [f for f in complement(occupied, zb, zt)
                if f[1] - f[0] >= NOISE_TOL]
        if strips and same_intervals(strips[-1][2], free, CHANGE_TOL):
            strips[-1][1] = b
        else:
            strips.append([a, b, free])

    pieces = []
    for a, b, free in strips:
        for z0, z1 in free:
            pieces.append((a, b, z0, z1))
    return pieces


def is_unchanged(pieces, length, zb, zt):
    if len(pieces) != 1:
        return False
    a, b, z0, z1 = pieces[0]
    return (abs(a) < CHANGE_TOL and abs(b - length) < CHANGE_TOL and
            abs(z0 - zb) < CHANGE_TOL and abs(z1 - zt) < CHANGE_TOL)


def largest_piece_index(pieces):
    best, best_area = 0, -1.0
    for i, (a, b, z0, z1) in enumerate(pieces):
        area = (b - a) * (z1 - z0)
        if area > best_area:
            best, best_area = i, area
    return best


def owner_index(info, pieces):
    """Index of the piece that fully contains the insert, or None."""
    u, width, iz0, iz1 = info
    half = width / 2.0 if width else 0.0
    for i, (a, b, z0, z1) in enumerate(pieces):
        if (u - half) < (a - FIT_TOL) or (u + half) > (b + FIT_TOL):
            continue
        if iz0 is not None and (iz0 < z0 - Z_FIT_TOL or iz1 > z1 + Z_FIT_TOL):
            continue
        return i
    return None


# ---------------------------------------------------------------------------
# 7. Inserts (doors / windows / openings / wall-hosted families)
#    Same strategy as the column splitter: inserts are never re-created, they
#    ride along with the copy, and each copy deletes the ones it doesn't own
#    BEFORE it is reshaped (otherwise Revit raises "not cutting anything").
# ---------------------------------------------------------------------------
INSERT_WIDTH_PARAMS = [b for b in (
    _bip('DOOR_WIDTH'),
    _bip('WINDOW_WIDTH'),
    _bip('FAMILY_WIDTH_PARAM'),
    _bip('GENERIC_WIDTH'),
) if b is not None]


def get_wall_inserts(wall):
    inserts = []
    for eid in wall.GetDependentElements(None):
        el = doc.GetElement(eid)
        if el is None or not isinstance(el, (FamilyInstance, Opening)):
            continue
        try:
            host = el.Host
        except Exception:
            continue
        if host is not None and host.Id == wall.Id:
            inserts.append(el)
    return inserts


def insert_width(el):
    sources = [el]
    symbol = getattr(el, 'Symbol', None)
    if symbol is not None:
        sources.append(symbol)
    for src in sources:
        for bip in INSERT_WIDTH_PARAMS:
            try:
                p = src.get_Parameter(bip)
            except Exception:
                continue
            if p is None or not p.HasValue or p.StorageType.ToString() != 'Double':
                continue
            v = p.AsDouble()
            if v > 0:
                return v
    return None


def insert_info(el, fr):
    """(u along wall, width, z min, z max) or None if it can't be located."""
    loc = el.Location
    bbox = el.get_BoundingBox(None)
    if isinstance(loc, LocationPoint):
        u = (loc.Point - fr.p0).DotProduct(fr.d)
    elif bbox is not None:
        u = ((bbox.Min + bbox.Max).Multiply(0.5) - fr.p0).DotProduct(fr.d)
    else:
        return None
    if bbox is not None:
        return (u, insert_width(el), bbox.Min.Z, bbox.Max.Z)
    return (u, insert_width(el), None, None)


def insert_owner(el, fr, pieces, keep_idx):
    if len(pieces) == 1 and abs(pieces[0][0]) < END_TOL \
            and abs(pieces[0][1] - fr.length) < END_TOL:
        return 0             # only stretched, not cut - nothing changes host
    info = insert_info(el, fr)
    if info is None:
        return keep_idx      # can't locate it - leave it on the original
    return owner_index(info, pieces)


# ---------------------------------------------------------------------------
# 8. Analysis (read-only apart from the rolled-back join probe)
# ---------------------------------------------------------------------------
def analyse_wall(wall, ctx):
    entry = {'wall': wall, 'status': 'skip', 'reason': None,
             'failed': [], 'notes': [], 'hits': None,
             'base_found': True, 'top_found': True}
    reason = wall_skip_reason(wall)
    if reason:
        entry['reason'] = reason
        return entry
    fr, reason = build_frame(wall)
    if reason:
        entry['reason'] = reason
        return entry

    adj = find_adjustment(fr, ctx)
    entry['failed'] = adj.failed
    entry['notes'] = adj.notes
    entry['hits'] = adj.hits
    entry['base_found'] = adj.base_found
    entry['top_found'] = adj.top_found

    pieces = build_pieces(adj.rects, fr.length, adj.zb, adj.zt)
    if not pieces:
        entry['reason'] = 'wall lies entirely inside beams (left untouched)'
        return entry
    if is_unchanged(pieces, fr.length, fr.zb, fr.zt):
        entry['status'] = 'clean'
        return entry

    keep_idx = largest_piece_index(pieces)
    entry['status'] = 'plan'
    entry['frame'] = fr
    entry['pieces'] = pieces
    entry['keep'] = keep_idx
    entry['lost'] = [el.Id for el in get_wall_inserts(wall)
                     if insert_owner(el, fr, pieces, keep_idx) is None]
    return entry


def analyse_walls(walls, ctx):
    results = []
    if len(walls) <= PROGRESS_THRESHOLD:
        for w in walls:
            results.append(_safe_analyse(w, ctx))
        return results
    with forms.ProgressBar(title='Checking walls ({value} of {max_value})',
                           cancellable=True) as pb:
        for i, w in enumerate(walls):
            if pb.cancelled:
                return None
            results.append(_safe_analyse(w, ctx))
            pb.update_progress(i + 1, len(walls))
    return results


def _safe_analyse(wall, ctx):
    try:
        return analyse_wall(wall, ctx)
    except Exception as ex:
        return {'wall': wall, 'status': 'skip', 'reason': 'analysis error: {}'.format(ex),
                'failed': [], 'notes': [], 'hits': None}


# ---------------------------------------------------------------------------
# 9. Apply one wall's plan (inside its own transaction)
# ---------------------------------------------------------------------------
def set_offsets(wall, z0, z1, fr):
    """Moves the wall to z0..z1 through its offsets only. Base and top
    constraints are left exactly as they are."""
    def set_base():
        set_param(wall, BuiltInParameter.WALL_BASE_OFFSET, z0 - fr.base_z)

    def set_top():
        if fr.top_z is not None:
            set_param(wall, BuiltInParameter.WALL_TOP_OFFSET, z1 - fr.top_z)
        else:
            set_param(wall, BuiltInParameter.WALL_USER_HEIGHT_PARAM, z1 - z0)

    # Order the two so the top never drops below the base in between.
    if z0 < fr.zt - EPS:
        set_base()
        set_top()
    else:
        set_top()
        set_base()
    doc.Regenerate()


def apply_plan(entry, ctx):
    wall = entry['wall']
    fr = entry['frame']
    pieces = entry['pieces']
    keep_idx = entry['keep']

    try:
        orig_join_start = WallUtils.IsWallJoinAllowedAtEnd(wall, 0)
        orig_join_end = WallUtils.IsWallJoinAllowedAtEnd(wall, 1)
    except Exception:
        orig_join_start = True
        orig_join_end = True

    def full_length(piece):
        return abs(piece[0]) < END_TOL and abs(piece[1] - fr.length) < END_TOL

    def drop_foreign_inserts(target, idx):
        to_delete = List[ElementId]()
        for el in get_wall_inserts(target):
            if insert_owner(el, fr, pieces, keep_idx) != idx:
                to_delete.Add(el.Id)
        if to_delete.Count > 0:
            doc.Delete(to_delete)
            doc.Regenerate()

    def shape(target, piece):
        a, b, z0, z1 = piece
        if not full_length(piece):
            # Joined ends resist being moved and the new curve would silently
            # revert - break the joins first, restore them at the end.
            WallUtils.DisallowWallJoinAtEnd(target, 0)
            WallUtils.DisallowWallJoinAtEnd(target, 1)
            loc = target.Location
            loc.Curve = Line.CreateBound(fr.p0 + fr.d.Multiply(a),
                                         fr.p0 + fr.d.Multiply(b))
            doc.Regenerate()
        set_offsets(target, z0, z1, fr)

    source_ids = List[ElementId]()
    source_ids.Add(wall.Id)

    # Copies first, while the original is still intact with every insert.
    shaped = []
    for idx, piece in enumerate(pieces):
        if idx == keep_idx:
            continue
        copied_ids = ElementTransformUtils.CopyElements(doc, source_ids, XYZ.Zero)
        doc.Regenerate()
        new_wall = None
        for cid in copied_ids:
            candidate = doc.GetElement(cid)
            if isinstance(candidate, Wall):
                new_wall = candidate
                break
        if new_wall is None:
            raise Exception('copy of wall {} produced no wall'.format(eid_str(wall.Id)))
        drop_foreign_inserts(new_wall, idx)
        shape(new_wall, piece)
        shaped.append((new_wall, piece))

    # The original becomes the largest piece - keeps its Id, tags, schedules.
    drop_foreign_inserts(wall, keep_idx)
    shape(wall, pieces[keep_idx])
    shaped.append((wall, pieces[keep_idx]))

    # Restore joins on any piece whose curve was changed: new ends at beam
    # faces always join; real ends inherit the original setting.
    for target, piece in shaped:
        if full_length(piece):
            continue
        try:
            if abs(piece[0]) > END_TOL or orig_join_start:
                WallUtils.AllowWallJoinAtEnd(target, 0)
            if abs(piece[1] - fr.length) > END_TOL or orig_join_end:
                WallUtils.AllowWallJoinAtEnd(target, 1)
        except Exception:
            pass
    doc.Regenerate()
    return len(shaped)


# ---------------------------------------------------------------------------
# 10. Selection
# ---------------------------------------------------------------------------
class WallOnlyFilter(ISelectionFilter):
    def AllowElement(self, elem):
        return isinstance(elem, Wall)

    def AllowReference(self, reference, point):
        return False


def pick_walls():
    try:
        picked = uidoc.Selection.PickElementsByRectangle(
            WallOnlyFilter(),
            'Draw a rectangle around the walls to cut (only walls are picked)')
    except Exception:
        return None
    return list(picked)


def preselected_walls():
    walls = []
    for eid in uidoc.Selection.GetElementIds():
        el = doc.GetElement(eid)
        if isinstance(el, Wall):
            walls.append(el)
    return walls


def view_walls():
    return list(FilteredElementCollector(doc, doc.ActiveView.Id).OfClass(Wall))


# ---------------------------------------------------------------------------
# 11. One round: analyse -> confirm -> apply -> report
# ---------------------------------------------------------------------------
def _ask(msg, ask_again):
    if ask_again:
        return forms.alert(msg + '\n\nSelect more walls?', title=TITLE, yes=True, no=True)
    forms.alert(msg, title=TITLE)
    return False


def _flush_startup_notes(lines):
    if STARTUP_NOTES:
        lines.append('')
        lines.extend(STARTUP_NOTES)
        del STARTUP_NOTES[:]


def _id_list(ids):
    shown = ', '.join(eid_str(e) for e in ids[:MAX_REPORT_IDS])
    if len(ids) > MAX_REPORT_IDS:
        shown += ' ... and {} more'.format(len(ids) - MAX_REPORT_IDS)
    return shown


def process_walls(walls, ctx, ask_again):
    """Returns True to keep picking, False to stop."""
    results = analyse_walls(walls, ctx)
    if results is None:
        return _ask('Check cancelled - nothing was changed.', ask_again)

    plans = [r for r in results if r['status'] == 'plan']
    clean = [r for r in results if r['status'] == 'clean']
    skipped = [r for r in results if r['status'] == 'skip']

    beams, slabs, failed, notes = set(), set(), [], []
    for r in results:
        if r['hits']:
            beams |= r['hits']['beam']
            slabs |= r['hits']['slab']
        failed.extend(r['failed'])
        notes.extend(r['notes'])

    reasons = {}
    for r in skipped:
        reasons[r['reason']] = reasons.get(r['reason'], 0) + 1
    reason_lines = ['  - {}: {}'.format(k, v) for k, v in sorted(reasons.items())]

    checked = plans + clean
    no_base = len([r for r in checked if not r.get('base_found', True)])
    no_top = len([r for r in checked if not r.get('top_found', True)])
    slab_lines = []
    if ctx['settings']['use_slabs'] and (no_base or no_top):
        slab_lines.append('No structural slab within {:.0f} mm - that end was kept:'
                          .format(SLAB_SEARCH / MM))
        slab_lines.append('  below {} wall(s), above {} wall(s)'.format(no_base, no_top))

    if not plans:
        msg = ['None of the {} wall(s) need adjusting.'.format(len(walls))]
        if clean:
            msg.append('Already fitted: {}'.format(len(clean)))
        msg.extend(slab_lines)
        if skipped:
            msg.append('Skipped: {}'.format(len(skipped)))
            msg.extend(reason_lines)
        return _ask('\n'.join(msg), ask_again)

    total_pieces = sum(len(p['pieces']) for p in plans)
    lost_all = []
    for p in plans:
        lost_all.extend(p['lost'])
    risky = [p for p in plans if p['lost']]
    safe = [p for p in plans if not p['lost']]

    summary = [
        'Walls checked: {}'.format(len(walls)),
        'Walls to adjust: {}  ->  {} wall(s) after cutting at beams'
        .format(len(plans), total_pieces),
        'Slabs used: {}   Beams involved: {}'.format(len(slabs), len(beams)),
        'Already fitted: {}'.format(len(clean)),
    ]
    summary.extend(slab_lines)
    if skipped:
        summary.append('Skipped: {}'.format(len(skipped)))
        summary.extend(reason_lines)

    protected = []      # walls left alone to keep their hosted elements
    if not lost_all:
        summary.append('')
        summary.append('Proceed?')
        if not forms.alert('\n'.join(summary), title=TITLE, yes=True, no=True):
            return _ask('Cancelled - nothing was changed.', ask_again)
    else:
        summary.append('')
        summary.append('{} hosted element(s) fit no piece and would be REMOVED:'
                       .format(len(lost_all)))
        summary.append('  ' + _id_list(lost_all))
        summary.append('They sit in {} wall(s):'.format(len(risky)))
        summary.append('  ' + _id_list([p['wall'].Id for p in risky]))

        opt_all = 'Adjust all {} walls (remove the {} hosted element(s))'\
            .format(len(plans), len(lost_all))
        opt_safe = 'Skip the {} wall(s) above, adjust the other {}'\
            .format(len(risky), len(safe))
        opt_cancel = 'Cancel'
        choice = forms.alert('\n'.join(summary), title=TITLE,
                             options=[opt_all, opt_safe, opt_cancel])
        if choice == opt_all:
            pass
        elif choice == opt_safe:
            protected = risky
            plans = safe
            if not plans:
                return _ask('Every wall to adjust would lose a hosted element - '
                            'nothing was changed.', ask_again)
        else:
            return _ask('Cancelled - nothing was changed.', ask_again)

    tg = TransactionGroup(doc, TITLE)
    tg.Start()

    done, pieces_made, errors, lost_done = 0, 0, [], []
    handled_all = {}
    stopped_at = None
    with forms.ProgressBar(title='Adjusting walls ({value} of {max_value})',
                           cancellable=True) as pb:
        for i, entry in enumerate(plans):
            if pb.cancelled:
                stopped_at = i
                break
            wall_id = entry['wall'].Id
            handled, fatal = {}, []
            t = Transaction(doc, 'Fit wall {} to structure'.format(eid_str(wall_id)))
            t.Start()
            make_silent(t, handled, fatal)
            try:
                n = apply_plan(entry, ctx)
                status = t.Commit()
                if status == TransactionStatus.Committed:
                    done += 1
                    pieces_made += n
                    lost_done.extend(entry['lost'])
                    for key, count in handled.items():
                        handled_all[key] = handled_all.get(key, 0) + count
                else:
                    errors.append((wall_id, fatal[0] if fatal else
                                   'Revit rejected the result ({})'.format(status)))
            except Exception as ex:
                if t.GetStatus() == TransactionStatus.Started:
                    t.RollBack()
                errors.append((wall_id, str(ex)))
            pb.update_progress(i + 1, len(plans))

    tg.Assimilate()

    # Active-model beams/slabs joined to the walls just edited may have new
    # geometry now; links are untouched, so only host entries are dropped.
    for key in [k for k in _SOLID_CACHE if k[0] == 'host']:
        del _SOLID_CACHE[key]

    lines = ['Round complete.',
             'Walls adjusted: {} / {}'.format(done, len(plans)),
             'Resulting walls: {}'.format(pieces_made)]
    if stopped_at is not None:
        lines.append('Stopped by you - the last {} wall(s) were left unchanged.'
                     .format(len(plans) - stopped_at))

    if protected:
        lines.append('')
        lines.append('Left unchanged to keep their hosted elements ({} wall(s)):'
                     .format(len(protected)))
        lines.append('  ' + _id_list([p['wall'].Id for p in protected]))

    if errors:
        lines.append('')
        lines.append('Walls left unchanged due to errors:')
        for wid, msg in errors[:MAX_REPORT_ITEMS]:
            lines.append('  Wall {}: {}'.format(eid_str(wid), msg))
        if len(errors) > MAX_REPORT_ITEMS:
            lines.append('  ... and {} more'.format(len(errors) - MAX_REPORT_ITEMS))

    if lost_done:
        lines.append('')
        lines.append('Hosted elements removed (fit no piece) - re-place manually:')
        lines.append('  ' + _id_list(lost_done))

    if failed:
        lines.append('')
        lines.append('Slabs that could not be intersected (ignored):')
        for f in failed[:MAX_REPORT_ITEMS]:
            lines.append('  ' + f)
        if len(failed) > MAX_REPORT_ITEMS:
            lines.append('  ... and {} more'.format(len(failed) - MAX_REPORT_ITEMS))

    if handled_all:
        lines.append('')
        lines.append('Revit messages answered automatically:')
        ranked = sorted(handled_all.items(), key=lambda kv: -kv[1])
        for (text, action), count in ranked[:MAX_REPORT_ITEMS]:
            if len(text) > 70:
                text = text[:67] + '...'
            lines.append('  {} x {} -> {}'.format(count, text, action))
        if len(ranked) > MAX_REPORT_ITEMS:
            lines.append('  ... and {} more kinds'.format(len(ranked) - MAX_REPORT_ITEMS))

    if notes:
        lines.append('')
        lines.extend(notes[:MAX_REPORT_ITEMS])

    _flush_startup_notes(lines)
    return _ask('\n'.join(lines), ask_again)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    settings = show_settings(load_settings())
    if settings is None:
        return
    save_settings(settings)

    sources, unloaded = collect_sources(settings)
    if unloaded:
        STARTUP_NOTES.append('Unloaded links skipped: {}'.format(', '.join(unloaded)))
    if not sources:
        forms.alert('No source to read beams/slabs from (active model is off '
                    'and no link is loaded).', title=TITLE)
        return

    ctx = {
        'settings': settings,
        'sources': sources,
    }

    if settings['scope'] == 'view':
        walls = view_walls()
        if not walls:
            forms.alert('No walls in the active view.', title=TITLE)
            return
        process_walls(walls, ctx, ask_again=False)
        return

    pending = preselected_walls()
    while True:
        if pending:
            walls, pending = pending, None
        else:
            walls = pick_walls()
            if walls is None:
                break       # Esc during the pick
            if not walls:
                if not forms.alert('No walls were picked. Select more walls?',
                                   title=TITLE, yes=True, no=True):
                    break
                continue
        if not process_walls(walls, ctx, ask_again=True):
            break


if __name__ == '__main__':
    main()
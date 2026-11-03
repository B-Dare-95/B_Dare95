# -*- coding: utf-8 -*-
__doc__ = """Crops your views to scope boxes that live in a Revit link, so you don't need to copy the scope boxes into your model first.

Before anything is cropped, the tool checks that the link sits exactly on your model. Grids and levels with the same name must match with no offset at all, and the shared coordinates are compared as a second check.

How-to:
-> Pick the link that holds the scope boxes
-> Read the alignment banner (click it for the details)
-> Pick a scope box next to each view, or check several views and assign one box to all of them
-> Click Apply crop

Author: Mohamed Bedair"""

import math
import clr
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from System import EventHandler
from System.Collections.Generic import List
from System.IO import Path
from System.Windows import (CornerRadius, RoutedEventHandler, TextTrimming,
                            TextWrapping, Thickness, VerticalAlignment, Visibility)
from System.Windows.Controls import (Border, CheckBox, ComboBox, Dock, DockPanel,
                                     Orientation, SelectionChangedEventHandler,
                                     StackPanel, TextBlock, TextChangedEventHandler)
from System.Windows.Controls.Primitives import ToggleButton
from System.Windows.Input import Cursors, MouseButtonEventHandler
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Markup import XamlReader
from System.Windows.Media import BrushConverter, FontFamily
from System.Windows.Threading import Dispatcher, DispatcherFrame

from Autodesk.Revit.DB import (Arc, BasePoint, BoundingBoxXYZ, BuiltInCategory,
                               BuiltInParameter, CurveLoop, ElementId,
                               FilteredElementCollector, Grid, Level, Line, Options,
                               RevitLinkInstance, SubTransaction, Transaction,
                               Transform, View, View3D, ViewPlan, ViewSection,
                               ViewType, XYZ)
from Autodesk.Revit.UI import TaskDialog
from pyrevit import script

uiapp = __revit__
doc = __revit__.ActiveUIDocument.Document

TOOL_NAME = "Crop by Linked Scope Box"
TOL = 1e-6          # feet - only absorbs floating-point noise from the link transform
ANG_TOL = 1e-6      # radians
FT_TO_MM = 304.8
NONE_LABEL = "None"

STATUS_COLORS = {
    "ok":   ("#0E2A18", "#A7F0BA", "#42BE65"),
    "warn": ("#3A2E06", "#FDDC69", "#F1C21B"),
    "bad":  ("#3A1416", "#FFB3B8", "#FA4D56"),
    "na":   ("#262626", "#A8A8A8", "#8D8D8D"),
    "info": ("#262626", "#A8A8A8", "#78A9FF"),
}
ICONS = {"ok": u"\u2714", "warn": u"\u26A0", "bad": u"\u2716",
         "na": u"\u25CB", "info": u"\u2139"}

VIEW_GROUPS = [
    (ViewType.FloorPlan, "Floor plans"),
    (ViewType.CeilingPlan, "Ceiling plans"),
    (ViewType.EngineeringPlan, "Structural plans"),
    (ViewType.AreaPlan, "Area plans"),
    (ViewType.Section, "Sections"),
    (ViewType.Detail, "Detail views"),
    (ViewType.Elevation, "Elevations"),
    (ViewType.ThreeD, "3D views"),
]
GROUP_BY_TYPE = dict(VIEW_GROUPS)
GROUP_ORDER = [g for _, g in VIEW_GROUPS]

_bc = BrushConverter()


def brush(hex_value):
    return _bc.ConvertFromString(hex_value)


SYMBOL_FONT = FontFamily("Segoe UI Symbol")


def eid_int(eid):
    try:
        return eid.Value
    except AttributeError:
        return eid.IntegerValue


def plural(n, word, word_pl=None):
    return "{} {}".format(n, word if n == 1 else (word_pl or word + "s"))


def fmt_mm(ft):
    s = "{:.3f}".format(abs(ft) * FT_TO_MM).rstrip("0").rstrip(".")
    if s == "0":
        s = "<0.001"
    return s + " mm"


def fmt_signed_mm(ft):
    s = "{:.3f}".format(ft * FT_TO_MM).rstrip("0").rstrip(".")
    if s in ("0", "-0"):
        s = "0"
    return s + " mm"


def flat(p):
    return XYZ(p.X, p.Y, 0)


# ----------------------------------------------------------------------------
# Scope box geometry
# ----------------------------------------------------------------------------

class OrientedBox(object):
    """Box rotated about Z only: origin + ax/ay axes + local min/max."""

    def __init__(self, origin, ax, ay, mn, mx):
        self.o = origin
        self.ax = ax
        self.ay = ay
        self.mn = mn
        self.mx = mx

    def point(self, x, y, z):
        return (self.o.Add(self.ax.Multiply(x))
                .Add(self.ay.Multiply(y))
                .Add(XYZ.BasisZ.Multiply(z)))

    def corners(self):
        pts = []
        for x in (self.mn.X, self.mx.X):
            for y in (self.mn.Y, self.mx.Y):
                for z in (self.mn.Z, self.mx.Z):
                    pts.append(self.point(x, y, z))
        return pts

    def bottom_loop(self):
        z = self.mn.Z
        p = [self.point(self.mn.X, self.mn.Y, z),
             self.point(self.mx.X, self.mn.Y, z),
             self.point(self.mx.X, self.mx.Y, z),
             self.point(self.mn.X, self.mx.Y, z)]
        loop = CurveLoop()
        for i in range(4):
            loop.Append(Line.CreateBound(p[i], p[(i + 1) % 4]))
        return loop

    def transformed(self, t):
        o = t.OfPoint(self.o)
        ax = t.OfVector(self.ax).Normalize()
        ay = t.OfVector(self.ay).Normalize()
        mn, mx = self.mn, self.mx
        if ax.CrossProduct(ay).Z < 0:
            # mirrored link instance - flip Y so the frame stays right-handed
            ay = ay.Negate()
            mn, mx = XYZ(mn.X, -mx.Y, mn.Z), XYZ(mx.X, -mn.Y, mx.Z)
        return OrientedBox(o, ax, ay, mn, mx)

    def as_bbox(self):
        t = Transform.CreateTranslation(self.o)
        t.BasisX = self.ax
        t.BasisY = self.ay
        t.BasisZ = XYZ.BasisZ
        bb = BoundingBoxXYZ()
        bb.Transform = t
        bb.Min = self.mn
        bb.Max = self.mx
        return bb


def scope_box_frame(sb):
    pts = []
    ax = None
    geo = sb.get_Geometry(Options())
    lines = []
    if geo is not None:
        for g in geo:
            if isinstance(g, Line):
                lines.append(g)
    if lines:
        for ln in lines:
            pts.append(ln.GetEndPoint(0))
            pts.append(ln.GetEndPoint(1))
        zmin = min(p.Z for p in pts)
        for ln in lines:
            a, b = ln.GetEndPoint(0), ln.GetEndPoint(1)
            if abs(a.Z - zmin) < 1e-6 and abs(b.Z - zmin) < 1e-6:
                d = XYZ(b.X - a.X, b.Y - a.Y, 0)
                if d.GetLength() > 1e-6:
                    ax = d.Normalize()
                    break
    else:
        bb = sb.get_BoundingBox(None)
        if bb is None:
            raise ValueError("Scope box has no geometry")
        for x in (bb.Min.X, bb.Max.X):
            for y in (bb.Min.Y, bb.Max.Y):
                for z in (bb.Min.Z, bb.Max.Z):
                    pts.append(bb.Transform.OfPoint(XYZ(x, y, z)))
    if ax is None:
        ax = XYZ.BasisX
    ay = XYZ.BasisZ.CrossProduct(ax)
    o = pts[0]
    xs, ys, zs = [], [], []
    for p in pts:
        v = p.Subtract(o)
        xs.append(v.DotProduct(ax))
        ys.append(v.DotProduct(ay))
        zs.append(v.Z)
    return OrientedBox(o, ax, ay,
                       XYZ(min(xs), min(ys), min(zs)),
                       XYZ(max(xs), max(ys), max(zs)))


# ----------------------------------------------------------------------------
# Alignment check
# ----------------------------------------------------------------------------

def names_map(d, cls):
    out = {}
    for e in FilteredElementCollector(d).OfClass(cls).ToElements():
        out[e.Name] = e
    return out


def grid_offset(hc, lc, t):
    """Worst offset between the host grid and the transformed link grid.
    Compares position only, not grid length. None = different shape."""
    if isinstance(hc, Arc) and isinstance(lc, Arc):
        c = flat(t.OfPoint(lc.Center))
        return max(c.DistanceTo(flat(hc.Center)), abs(hc.Radius - lc.Radius))
    if isinstance(hc, Line) and isinstance(lc, Line):
        a = flat(hc.GetEndPoint(0))
        d = flat(hc.GetEndPoint(1)).Subtract(a).Normalize()
        worst = 0.0
        for i in (0, 1):
            v = flat(t.OfPoint(lc.GetEndPoint(i))).Subtract(a)
            worst = max(worst, abs(v.X * d.Y - v.Y * d.X))
        return worst
    return None


def internal_to_shared(d):
    """Internal -> shared transform. The direction of GetTotalTransform is
    confirmed against the base points' SharedPosition instead of assumed."""
    g = d.ActiveProjectLocation.GetTotalTransform()
    try:
        for bp in (BasePoint.GetProjectBasePoint(d), BasePoint.GetSurveyPoint(d)):
            pi, ps = bp.Position, bp.SharedPosition
            e_fwd = g.OfPoint(pi).DistanceTo(ps)
            e_inv = g.Inverse.OfPoint(pi).DistanceTo(ps)
            if abs(e_fwd - e_inv) > 1e-6:
                return g if e_fwd < e_inv else g.Inverse
    except Exception:
        pass
    return g.Inverse


def fail_text(fails):
    parts = []
    for name, off in sorted(fails)[:6]:
        parts.append("{} ({})".format(name, "shape differs" if off is None else fmt_mm(off)))
    more = "" if len(fails) <= 6 else " and {} more".format(len(fails) - 6)
    return ", ".join(parts) + more


def check_alignment(inst):
    ld = inst.GetLinkDocument()
    t = inst.GetTotalTransform()
    rows = []

    # Grids - exact match by name
    host_g, link_g = names_map(doc, Grid), names_map(ld, Grid)
    g_match, g_fail = 0, []
    for name, lg in link_g.items():
        hg = host_g.get(name)
        if hg is None:
            continue
        g_match += 1
        try:
            off = grid_offset(hg.Curve, lg.Curve, t)
        except Exception:
            off = None
        if off is None or off > TOL:
            g_fail.append((name, off))
    if g_match == 0:
        rows.append(("na", "Grids", "exact match",
                     "0 of {} names matched. Not checked.".format(len(link_g))))
    elif not g_fail:
        rows.append(("ok", "Grids", "exact match",
                     "{} of {} matched by name. All exact, no offset.".format(g_match, len(link_g))))
    else:
        rows.append(("bad", "Grids", "exact match",
                     "{} of {} exact. Off: {}.".format(g_match - len(g_fail), g_match, fail_text(g_fail))))

    # Levels - exact match by name
    host_l, link_l = names_map(doc, Level), names_map(ld, Level)
    l_match, l_fail = 0, []
    for name, ll in link_l.items():
        hl = host_l.get(name)
        if hl is None:
            continue
        l_match += 1
        z = t.OfPoint(XYZ(0, 0, ll.ProjectElevation)).Z
        diff = abs(z - hl.ProjectElevation)
        if diff > TOL:
            l_fail.append((name, diff))
    if l_match == 0:
        rows.append(("na", "Levels", "exact match",
                     "0 of {} names matched. Not checked.".format(len(link_l))))
    elif not l_fail:
        rows.append(("ok", "Levels", "exact match",
                     "{} of {} matched by name. All exact, no difference.".format(l_match, len(link_l))))
    else:
        rows.append(("bad", "Levels", "exact match",
                     "{} of {} exact. Off: {}.".format(l_match - len(l_fail), l_match, fail_text(l_fail))))

    # Shared coordinates - secondary check
    shared_ok = True
    try:
        sh, sl = internal_to_shared(doc), internal_to_shared(ld)
        a = sh.OfPoint(t.OfPoint(XYZ.Zero))
        b = sl.OfPoint(XYZ.Zero)
        d = a.Subtract(b)
        va = sh.OfVector(t.OfVector(XYZ.BasisX))
        vb = sl.OfVector(XYZ.BasisX)
        ang = vb.AngleOnPlaneTo(va, XYZ.BasisZ)
        if ang > math.pi:
            ang -= 2 * math.pi
        if d.GetLength() <= TOL and abs(ang) <= ANG_TOL:
            rows.append(("ok", "Shared coordinates", "warning",
                         "Link sits where its own coordinates place it."))
        else:
            shared_ok = False
            rows.append(("warn", "Shared coordinates", "warning",
                         u"Off by X {}, Y {}, Z {}, rotation {:.2f}\u00b0. Check how the link was acquired or published."
                         .format(fmt_signed_mm(d.X), fmt_signed_mm(d.Y), fmt_signed_mm(d.Z),
                                 math.degrees(ang))))
    except Exception as e:
        rows.append(("na", "Shared coordinates", "warning",
                     "Couldn't compare. {}".format(e)))

    # Base point - info only
    try:
        hp = BasePoint.GetProjectBasePoint(doc).Position
        lp = t.OfPoint(BasePoint.GetProjectBasePoint(ld).Position)
        d = lp.Subtract(hp)
        if d.GetLength() <= TOL:
            txt = "Same position as the active model."
        else:
            txt = "Offset X {}, Y {}, Z {} from the active model.".format(
                fmt_signed_mm(d.X), fmt_signed_mm(d.Y), fmt_signed_mm(d.Z))
    except Exception as e:
        txt = "Couldn't read the base points. {}".format(e)
    rows.append(("info", "Base point", "info", txt))

    # Overall status
    if g_fail or l_fail:
        parts = []
        if g_fail:
            parts.append(plural(len(g_fail), "grid"))
        if l_fail:
            parts.append(plural(len(l_fail), "level"))
        verb = "doesn't" if len(g_fail) + len(l_fail) == 1 else "don't"
        status = "bad"
        title = "Link not aligned. {} {} match exactly.".format(" and ".join(parts), verb)
    elif g_match == 0 or l_match == 0:
        missing = "grids or levels" if (g_match == 0 and l_match == 0) else ("grids" if g_match == 0 else "levels")
        status = "na"
        title = "Couldn't verify the geometry. No {} share a name with the active model.".format(missing)
    elif not shared_ok:
        status = "warn"
        title = "Geometry aligned, but the shared coordinates don't match. Crops will be correct."
    else:
        status = "ok"
        title = "Link aligned. Grids, levels and shared coordinates all match."
    return {"status": status, "title": title, "rows": rows}


# ----------------------------------------------------------------------------
# Cropping
# ----------------------------------------------------------------------------

class SkipView(Exception):
    pass


def clear_view_scope_box(view):
    p = view.get_Parameter(BuiltInParameter.VIEWER_VOLUME_OF_INTEREST_CROP)
    if p is None or p.AsElementId() == ElementId.InvalidElementId:
        return
    if p.IsReadOnly:
        raise SkipView("Scope box is set by the view template")
    p.Set(ElementId.InvalidElementId)


def set_rect_crop(view, cb, hb):
    inv = cb.Transform.Inverse
    pts = [inv.OfPoint(c) for c in hb.corners()]
    nb = BoundingBoxXYZ()
    nb.Transform = cb.Transform
    nb.Min = XYZ(min(p.X for p in pts), min(p.Y for p in pts), cb.Min.Z)
    nb.Max = XYZ(max(p.X for p in pts), max(p.Y for p in pts), cb.Max.Z)
    view.CropBox = nb


def crop_plan(view, hb):
    view.CropBoxActive = True
    crm = view.GetCropRegionShapeManager()
    lx = view.CropBox.Transform.Inverse.OfVector(hb.ax)
    aligned = abs(lx.X) < ANG_TOL or abs(lx.Y) < ANG_TOL
    if aligned or not crm.CanHaveShape:
        if crm.ShapeSet:
            crm.RemoveCropRegionShape()
        set_rect_crop(view, view.CropBox, hb)
        return None if aligned else "outline"
    loop = hb.bottom_loop()
    if not crm.IsCropRegionShapeValid(loop):
        raise SkipView("Revit rejected the rotated crop shape")
    crm.SetCropShape(loop)
    return "rotated"


def crop_section(view, hb):
    view.CropBoxActive = True
    crm = view.GetCropRegionShapeManager()
    if crm.ShapeSet:
        crm.RemoveCropRegionShape()
    cb = view.CropBox
    inv = cb.Transform.Inverse
    zs = [inv.OfPoint(c).Z for c in hb.corners()]
    if max(zs) < cb.Min.Z - TOL or min(zs) > cb.Max.Z + TOL:
        raise SkipView("Scope box is outside the view depth")
    set_rect_crop(view, cb, hb)
    lx = inv.OfVector(hb.ax)
    aligned = abs(lx.X) < ANG_TOL or abs(lx.Z) < ANG_TOL
    return None if aligned else "outline"


def crop_3d(view, hb):
    if view.IsLocked:
        raise SkipView("3D view is locked")
    view.IsSectionBoxActive = True
    view.SetSectionBox(hb.as_bbox())
    return None


def apply_crop(view, hb):
    clear_view_scope_box(view)
    if isinstance(view, View3D):
        return crop_3d(view, hb)
    if isinstance(view, ViewPlan):
        return crop_plan(view, hb)
    if isinstance(view, ViewSection):
        return crop_section(view, hb)
    raise SkipView("View type isn't supported")


# ----------------------------------------------------------------------------
# Data collection
# ----------------------------------------------------------------------------

class ViewItem(object):
    def __init__(self, view, group, sub, lock):
        self.view = view
        self.name = view.Name
        self.group = group
        self.sub = sub
        self.lock = lock
        self.row = None
        self.chk = None
        self.cmb = None


def view_subtext(v):
    if isinstance(v, ViewPlan) and v.GenLevel is not None:
        s = v.GenLevel.Name
    elif isinstance(v, View3D):
        s = "Uses section box"
    else:
        s = {ViewType.Section: "Section", ViewType.Detail: "Detail view",
             ViewType.Elevation: "Elevation"}.get(v.ViewType, "")
    if v.GetPrimaryViewId() != ElementId.InvalidElementId:
        s += u"  \u00b7  dependent"
    return s


def lock_reason(v):
    if isinstance(v, View3D):
        if v.IsLocked:
            return "3D view is locked"
        p = v.get_Parameter(BuiltInParameter.VIEWER_MODEL_CLIP_BOX_ACTIVE)
        if p is not None and p.IsReadOnly:
            return "Section box is locked for this view"
    else:
        p = v.get_Parameter(BuiltInParameter.VIEWER_CROP_REGION)
        if p is not None and p.IsReadOnly:
            return "Crop is locked for this view"
    sb = v.get_Parameter(BuiltInParameter.VIEWER_VOLUME_OF_INTEREST_CROP)
    if sb is not None and sb.IsReadOnly and sb.AsElementId() != ElementId.InvalidElementId:
        return "Scope box is set by the view template"
    return None


def collect_views():
    out = []
    for v in FilteredElementCollector(doc).OfClass(View).ToElements():
        if v.IsTemplate:
            continue
        g = GROUP_BY_TYPE.get(v.ViewType)
        if g is None:
            continue
        out.append(ViewItem(v, g, view_subtext(v), lock_reason(v)))
    out.sort(key=lambda i: (GROUP_ORDER.index(i.group), i.name.lower()))
    return out


def link_title(inst):
    ld = inst.GetLinkDocument()
    try:
        p = ld.PathName
    except Exception:
        p = None
    return Path.GetFileName(p) if p else ld.Title


def collect_links():
    insts = [i for i in FilteredElementCollector(doc).OfClass(RevitLinkInstance).ToElements()
             if i.GetLinkDocument() is not None]
    counts = {}
    for i in insts:
        t = link_title(i)
        counts[t] = counts.get(t, 0) + 1
    out = []
    for i in insts:
        t = link_title(i)
        label = t if counts[t] == 1 else "{}  (instance {})".format(t, eid_int(i.Id))
        out.append((label, i))
    out.sort(key=lambda x: x[0].lower())
    return out


def collect_boxes(inst):
    ld = inst.GetLinkDocument()
    t = inst.GetTotalTransform()
    sbs = (FilteredElementCollector(ld)
           .OfCategory(BuiltInCategory.OST_VolumeOfInterest)
           .WhereElementIsNotElementType().ToElements())
    names = {}
    for sb in sbs:
        names[sb.Name] = names.get(sb.Name, 0) + 1
    boxes = {}
    for sb in sbs:
        label = sb.Name if names[sb.Name] == 1 else "{} ({})".format(sb.Name, eid_int(sb.Id))
        try:
            boxes[label] = scope_box_frame(sb).transformed(t)
        except Exception:
            continue
    return boxes


# ----------------------------------------------------------------------------
# UI
# ----------------------------------------------------------------------------

XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Crop by Linked Scope Box" Width="660" Height="800" MinWidth="560" MinHeight="560"
        WindowStartupLocation="CenterScreen" ResizeMode="CanResizeWithGrip"
        Background="#161616" Foreground="#F4F4F4" FontFamily="Segoe UI" FontSize="13">
  <Window.Resources>
    <Style TargetType="Button">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="BorderBrush" Value="#525252"/>
      <Setter Property="Height" Value="32"/>
      <Setter Property="Padding" Value="16,0"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="Bd" Background="{TemplateBinding Background}" BorderBrush="{TemplateBinding BorderBrush}"
                    BorderThickness="1" CornerRadius="6" Padding="{TemplateBinding Padding}">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True"><Setter TargetName="Bd" Property="Opacity" Value="0.85"/></Trigger>
              <Trigger Property="IsEnabled" Value="False"><Setter TargetName="Bd" Property="Opacity" Value="0.4"/></Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style x:Key="Accent" TargetType="Button" BasedOn="{StaticResource {x:Type Button}}">
      <Setter Property="Background" Value="#F1C21B"/>
      <Setter Property="BorderBrush" Value="#F1C21B"/>
      <Setter Property="Foreground" Value="#161616"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
    </Style>
    <Style x:Key="Chip" TargetType="ToggleButton">
      <Setter Property="Background" Value="#262626"/>
      <Setter Property="BorderBrush" Value="#393939"/>
      <Setter Property="Foreground" Value="#A8A8A8"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="Height" Value="26"/>
      <Setter Property="Padding" Value="10,0"/>
      <Setter Property="Margin" Value="0,0,6,6"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ToggleButton">
            <Border Background="{TemplateBinding Background}" BorderBrush="{TemplateBinding BorderBrush}"
                    BorderThickness="1" CornerRadius="6" Padding="{TemplateBinding Padding}">
              <ContentPresenter VerticalAlignment="Center"/>
            </Border>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
      <Style.Triggers>
        <Trigger Property="IsChecked" Value="True">
          <Setter Property="Background" Value="#F1C21B"/>
          <Setter Property="BorderBrush" Value="#F1C21B"/>
          <Setter Property="Foreground" Value="#161616"/>
        </Trigger>
      </Style.Triggers>
    </Style>
    <Style TargetType="TextBox">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="CaretBrush" Value="#F4F4F4"/>
      <Setter Property="Height" Value="30"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="TextBox">
            <Border Background="#393939" BorderBrush="#525252" BorderThickness="1" CornerRadius="6">
              <ScrollViewer x:Name="PART_ContentHost" Margin="6,0" VerticalAlignment="Center"/>
            </Border>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style TargetType="ComboBoxItem">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Padding" Value="8,5"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ComboBoxItem">
            <Border x:Name="Bd" Background="Transparent" Padding="{TemplateBinding Padding}">
              <ContentPresenter/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsHighlighted" Value="True"><Setter TargetName="Bd" Property="Background" Value="#393939"/></Trigger>
              <Trigger Property="IsSelected" Value="True"><Setter TargetName="Bd" Property="Background" Value="#525252"/></Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style TargetType="ComboBox">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Height" Value="28"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ComboBox">
            <Grid>
              <ToggleButton Focusable="False" ClickMode="Press"
                            IsChecked="{Binding IsDropDownOpen, Mode=TwoWay, RelativeSource={RelativeSource TemplatedParent}}">
                <ToggleButton.Template>
                  <ControlTemplate TargetType="ToggleButton">
                    <Border x:Name="Bd" Background="#393939" BorderBrush="#525252" BorderThickness="1" CornerRadius="6">
                      <Path HorizontalAlignment="Right" VerticalAlignment="Center" Margin="0,0,10,0"
                            Data="M0,0 L4,4 L8,0" Stroke="#A8A8A8" StrokeThickness="1.5"/>
                    </Border>
                    <ControlTemplate.Triggers>
                      <Trigger Property="IsMouseOver" Value="True"><Setter TargetName="Bd" Property="BorderBrush" Value="#8D8D8D"/></Trigger>
                    </ControlTemplate.Triggers>
                  </ControlTemplate>
                </ToggleButton.Template>
              </ToggleButton>
              <ContentPresenter IsHitTestVisible="False" Margin="8,0,26,0" VerticalAlignment="Center"
                                Content="{TemplateBinding SelectionBoxItem}"
                                ContentTemplate="{TemplateBinding SelectionBoxItemTemplate}"/>
              <Popup IsOpen="{TemplateBinding IsDropDownOpen}" Placement="Bottom" AllowsTransparency="True"
                     Focusable="False" PopupAnimation="Slide">
                <Border Background="#262626" BorderBrush="#525252" BorderThickness="1" CornerRadius="6" Margin="0,2,0,0"
                        MinWidth="{Binding ActualWidth, RelativeSource={RelativeSource TemplatedParent}}" MaxHeight="320">
                  <ScrollViewer VerticalScrollBarVisibility="Auto">
                    <ItemsPresenter KeyboardNavigation.DirectionalNavigation="Contained"/>
                  </ScrollViewer>
                </Border>
              </Popup>
            </Grid>
            <ControlTemplate.Triggers>
              <Trigger Property="IsEnabled" Value="False"><Setter Property="Opacity" Value="0.4"/></Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style x:Key="Row" TargetType="Border">
      <Setter Property="Background" Value="Transparent"/>
      <Setter Property="BorderBrush" Value="#262626"/>
      <Setter Property="BorderThickness" Value="0,0,0,1"/>
      <Setter Property="Padding" Value="10,5"/>
      <Style.Triggers>
        <Trigger Property="IsMouseOver" Value="True"><Setter Property="Background" Value="#262626"/></Trigger>
      </Style.Triggers>
    </Style>
  </Window.Resources>

  <Grid Margin="14">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <StackPanel Grid.Row="0">
      <TextBlock Text="Revit link" Foreground="#A8A8A8" FontSize="12" Margin="0,0,0,4"/>
      <ComboBox x:Name="cmbLink" IsSynchronizedWithCurrentItem="False"/>
    </StackPanel>

    <Border Grid.Row="1" Margin="0,10,0,0" CornerRadius="6" BorderBrush="#393939" BorderThickness="1" Background="#1C1C1C">
      <StackPanel>
        <Border x:Name="bdAlignHead" Padding="10,8" Cursor="Hand" CornerRadius="5">
          <DockPanel>
            <TextBlock x:Name="tbAlignIcon" DockPanel.Dock="Left" FontFamily="Segoe UI Symbol" FontSize="14" Margin="0,0,8,0"/>
            <TextBlock x:Name="tbChevron" DockPanel.Dock="Right" FontFamily="Segoe UI Symbol" Margin="8,0,0,0"/>
            <TextBlock x:Name="tbAlignText" FontSize="12" TextWrapping="Wrap" VerticalAlignment="Center"/>
          </DockPanel>
        </Border>
        <StackPanel x:Name="spDetails" Visibility="Collapsed"/>
      </StackPanel>
    </Border>

    <Grid Grid.Row="2" Margin="0,12,0,0">
      <TextBox x:Name="txtSearch"/>
      <TextBlock x:Name="tbPlaceholder" Text="Search views" Foreground="#8D8D8D" Margin="10,0,0,0"
                 VerticalAlignment="Center" IsHitTestVisible="False"/>
    </Grid>

    <WrapPanel Grid.Row="3" x:Name="wpTypes" Margin="0,8,0,0"/>

    <Border Grid.Row="4" Background="#262626" CornerRadius="6" Padding="10,8" Margin="0,4,0,0">
      <DockPanel>
        <CheckBox x:Name="chkAll" DockPanel.Dock="Left" VerticalAlignment="Center" Margin="0,0,8,0" ToolTip="Check all views shown"/>
        <Button x:Name="btnAssign" DockPanel.Dock="Right" Content="Assign" Height="28" Padding="12,0" Margin="8,0,0,0"/>
        <ComboBox x:Name="cmbBulk" DockPanel.Dock="Right" Width="190" IsSynchronizedWithCurrentItem="False"/>
        <TextBlock Text="Assign to checked views" Foreground="#A8A8A8" FontSize="12" VerticalAlignment="Center"/>
      </DockPanel>
    </Border>

    <Border Grid.Row="5" Margin="0,10,0,0" BorderBrush="#393939" BorderThickness="1" CornerRadius="6">
      <ScrollViewer VerticalScrollBarVisibility="Auto">
        <StackPanel x:Name="spList"/>
      </ScrollViewer>
    </Border>

    <Border Grid.Row="6" x:Name="bdConfirm" Visibility="Collapsed" CornerRadius="6" Padding="10,8" Margin="0,10,0,0">
      <DockPanel>
        <Button x:Name="btnYes" DockPanel.Dock="Right" Style="{StaticResource Accent}" Content="Apply anyway"
                Height="28" Padding="12,0" Margin="8,0,0,0"/>
        <Button x:Name="btnNo" DockPanel.Dock="Right" Content="Cancel" Height="28" Padding="12,0" Margin="8,0,0,0"/>
        <TextBlock x:Name="tbConfirm" FontSize="12" TextWrapping="Wrap" VerticalAlignment="Center"/>
      </DockPanel>
    </Border>

    <Border Grid.Row="7" x:Name="bdMsg" Visibility="Collapsed" CornerRadius="6" Padding="10,8" Margin="0,10,0,0">
      <TextBlock x:Name="tbMsg" FontSize="12" TextWrapping="Wrap"/>
    </Border>

    <DockPanel Grid.Row="8" Margin="0,12,0,0">
      <Button x:Name="btnApply" DockPanel.Dock="Right" Style="{StaticResource Accent}" Content="Apply crop" Margin="8,0,0,0"/>
      <Button x:Name="btnClear" DockPanel.Dock="Right" Content="Clear all"/>
      <TextBlock x:Name="tbCount" Foreground="#A8A8A8" FontSize="12" VerticalAlignment="Center"/>
    </DockPanel>
  </Grid>
</Window>
"""


links = collect_links()
if not links:
    TaskDialog.Show(TOOL_NAME, "There are no loaded Revit links in this model. "
                               "Load the link that holds the scope boxes and run the tool again.")
    script.exit()

items = collect_views()

window = XamlReader.Parse(XAML)
ui = {}
for _n in ["cmbLink", "bdAlignHead", "tbAlignIcon", "tbChevron", "tbAlignText", "spDetails",
           "txtSearch", "tbPlaceholder", "wpTypes", "chkAll", "btnAssign", "cmbBulk", "spList",
           "bdConfirm", "btnYes", "btnNo", "tbConfirm", "bdMsg", "tbMsg", "btnApply",
           "btnClear", "tbCount"]:
    ui[_n] = window.FindName(_n)

state = {"link": None, "label": "", "boxes": {}, "names": None, "type": "All",
         "collapsed": set(), "status": None, "open": False}
groups = []
by_group = {}
headers = {}
chips = []


# --- messages ---------------------------------------------------------------

MSG_COLORS = {"error": ("#3A1416", "#FFB3B8"), "info": ("#262626", "#A8A8A8"),
              "ok": ("#262626", "#F4F4F4")}


def show_msg(text, kind):
    bg, fg = MSG_COLORS[kind]
    ui["bdMsg"].Background = brush(bg)
    ui["tbMsg"].Foreground = brush(fg)
    ui["tbMsg"].Text = text
    ui["bdMsg"].Visibility = Visibility.Visible


def hide_msg():
    ui["bdMsg"].Visibility = Visibility.Collapsed


def hide_confirm():
    ui["bdConfirm"].Visibility = Visibility.Collapsed


# --- alignment banner -------------------------------------------------------

def detail_row(kind, name, tag, text):
    b = Border()
    b.BorderBrush = brush("#262626")
    b.BorderThickness = Thickness(0, 1, 0, 0)
    b.Padding = Thickness(10, 6, 10, 6)
    dp = DockPanel()
    ic = TextBlock()
    ic.Text = ICONS[kind]
    ic.FontFamily = SYMBOL_FONT
    ic.Foreground = brush(STATUS_COLORS[kind][2])
    ic.Width = 20
    DockPanel.SetDock(ic, Dock.Left)
    head = StackPanel()
    head.Orientation = Orientation.Horizontal
    head.Width = 190
    DockPanel.SetDock(head, Dock.Left)
    nm = TextBlock()
    nm.Text = name
    nm.FontSize = 12
    nm.Foreground = brush("#8D8D8D" if kind == "info" else "#F4F4F4")
    pill = Border()
    pill.Background = brush("#393939")
    pill.CornerRadius = CornerRadius(8)
    pill.Padding = Thickness(7, 0, 7, 1)
    pill.Margin = Thickness(6, 0, 0, 0)
    pill.VerticalAlignment = VerticalAlignment.Center
    pt = TextBlock()
    pt.Text = tag
    pt.FontSize = 11
    pt.Foreground = brush("#A8A8A8")
    pill.Child = pt
    head.Children.Add(nm)
    head.Children.Add(pill)
    tx = TextBlock()
    tx.Text = text
    tx.FontSize = 12
    tx.Foreground = brush("#A8A8A8")
    tx.TextWrapping = TextWrapping.Wrap
    dp.Children.Add(ic)
    dp.Children.Add(head)
    dp.Children.Add(tx)
    b.Child = dp
    return b


def apply_open():
    is_open = state["open"]
    ui["spDetails"].Visibility = Visibility.Visible if is_open else Visibility.Collapsed
    ui["tbChevron"].Text = u"\u25B4" if is_open else u"\u25BE"
    ui["bdAlignHead"].CornerRadius = CornerRadius(5, 5, 0, 0) if is_open else CornerRadius(5)


def show_alignment(res):
    bg, fg, icon_col = STATUS_COLORS[res["status"]]
    ui["bdAlignHead"].Background = brush(bg)
    ui["tbAlignText"].Foreground = brush(fg)
    ui["tbChevron"].Foreground = brush(fg)
    ui["tbAlignIcon"].Foreground = brush(icon_col)
    ui["tbAlignIcon"].Text = ICONS[res["status"]]
    ui["tbAlignText"].Text = res["title"]
    ui["spDetails"].Children.Clear()
    for kind, name, tag, text in res["rows"]:
        ui["spDetails"].Children.Add(detail_row(kind, name, tag, text))
    state["status"] = res["status"]
    state["open"] = res["status"] != "ok"
    apply_open()


def on_align_click(sender, args):
    state["open"] = not state["open"]
    apply_open()


# --- view list ---------------------------------------------------------------

def update_count():
    n = len([it for it in items if it.cmb.SelectedIndex > 0])
    ui["tbCount"].Text = "{} of {} views assigned".format(n, len(items))


def on_row_combo(sender, args):
    update_count()


def build_row(it):
    row = Border()
    row.Style = window.FindResource("Row")
    dp = DockPanel()
    chk = CheckBox()
    chk.VerticalAlignment = VerticalAlignment.Center
    chk.Margin = Thickness(0, 0, 8, 0)
    DockPanel.SetDock(chk, Dock.Left)
    cmb = ComboBox()
    cmb.Width = 200
    cmb.IsSynchronizedWithCurrentItem = False
    cmb.VerticalAlignment = VerticalAlignment.Center
    cmb.Margin = Thickness(8, 0, 0, 0)
    DockPanel.SetDock(cmb, Dock.Right)
    sp = StackPanel()
    sp.VerticalAlignment = VerticalAlignment.Center
    t1 = TextBlock()
    t1.Text = it.name
    t1.TextTrimming = TextTrimming.CharacterEllipsis
    t1.ToolTip = it.name
    t2 = TextBlock()
    t2.FontSize = 11
    if it.lock:
        chk.IsEnabled = False
        cmb.IsEnabled = False
        t1.Foreground = brush("#6F6F6F")
        t2.Text = it.lock
        t2.Foreground = brush("#F1C21B")
    else:
        t2.Text = it.sub
        t2.Foreground = brush("#A8A8A8")
    sp.Children.Add(t1)
    sp.Children.Add(t2)
    dp.Children.Add(chk)
    dp.Children.Add(cmb)
    dp.Children.Add(sp)
    row.Child = dp
    cmb.SelectionChanged += SelectionChangedEventHandler(on_row_combo)
    it.row, it.chk, it.cmb = row, chk, cmb


def make_header_handler(group):
    def handler(sender, args):
        if group in state["collapsed"]:
            state["collapsed"].discard(group)
        else:
            state["collapsed"].add(group)
        refresh_list()
    return handler


def build_list():
    for it in items:
        if it.group not in by_group:
            by_group[it.group] = []
            groups.append(it.group)
        by_group[it.group].append(it)
    for g in groups:
        hdr = Border()
        hdr.Background = brush("#262626")
        hdr.Padding = Thickness(10, 7, 10, 7)
        hdr.Cursor = Cursors.Hand
        ht = TextBlock()
        ht.FontSize = 12
        ht.Foreground = brush("#A8A8A8")
        hdr.Child = ht
        hdr.MouseLeftButtonUp += MouseButtonEventHandler(make_header_handler(g))
        headers[g] = (hdr, ht)
        ui["spList"].Children.Add(hdr)
        for it in by_group[g]:
            build_row(it)
            ui["spList"].Children.Add(it.row)


def matches(it, q):
    return (state["type"] == "All" or it.group == state["type"]) and q in it.name.lower()


def filtered_items():
    q = ui["txtSearch"].Text.strip().lower()
    return [it for it in items if matches(it, q)]


def refresh_list():
    shown = set(id(it) for it in filtered_items())
    for g in groups:
        hdr, ht = headers[g]
        members = [it for it in by_group[g] if id(it) in shown]
        collapsed = g in state["collapsed"]
        hdr.Visibility = Visibility.Visible if members else Visibility.Collapsed
        ht.Text = u"{}  {}  ({})".format(u"\u25B8" if collapsed else u"\u25BE", g, len(members))
        for it in by_group[g]:
            vis = id(it) in shown and not collapsed
            it.row.Visibility = Visibility.Visible if vis else Visibility.Collapsed
    ui["tbPlaceholder"].Visibility = (Visibility.Collapsed if ui["txtSearch"].Text
                                      else Visibility.Visible)


def on_search(sender, args):
    refresh_list()


# --- type chips ------------------------------------------------------------

def make_chip_handler(label):
    def handler(sender, args):
        state["type"] = label
        for c in chips:
            c.IsChecked = (c.Content == label)
        refresh_list()
    return handler


def build_chips():
    for label in ["All"] + groups:
        tb = ToggleButton()
        tb.Content = label
        tb.Style = window.FindResource("Chip")
        tb.IsChecked = (label == "All")
        tb.Click += RoutedEventHandler(make_chip_handler(label))
        chips.append(tb)
        ui["wpTypes"].Children.Add(tb)


# --- link switching ---------------------------------------------------------

def on_link_changed(sender, args):
    idx = ui["cmbLink"].SelectedIndex
    if idx < 0:
        return
    label, inst = links[idx]
    hide_msg()
    hide_confirm()
    state["link"] = inst
    state["label"] = label
    state["boxes"] = collect_boxes(inst)
    names = List[str]()
    names.Add(NONE_LABEL)
    for n in sorted(state["boxes"].keys(), key=lambda s: s.lower()):
        names.Add(n)
    state["names"] = names
    for it in items:
        it.cmb.ItemsSource = names
        it.cmb.SelectedIndex = 0
    ui["cmbBulk"].ItemsSource = names
    ui["cmbBulk"].SelectedIndex = 0
    show_alignment(check_alignment(inst))
    if not state["boxes"]:
        show_msg("This link has no scope boxes.", "error")
    update_count()


# --- bulk assign / clear -----------------------------------------------------

def on_check_all(sender, args):
    val = ui["chkAll"].IsChecked == True
    for it in filtered_items():
        if not it.lock:
            it.chk.IsChecked = val


def on_assign(sender, args):
    hide_confirm()
    sel = ui["cmbBulk"].SelectedIndex
    checked = [it for it in items if it.chk.IsChecked == True and not it.lock]
    if not checked:
        show_msg("Check at least one view first.", "error")
        return
    for it in checked:
        it.cmb.SelectedIndex = sel
    if sel > 0:
        show_msg("Assigned {} to {}.".format(ui["cmbBulk"].SelectedItem, plural(len(checked), "view")), "info")
    else:
        show_msg("Cleared {}.".format(plural(len(checked), "view")), "info")


def on_clear(sender, args):
    hide_confirm()
    hide_msg()
    for it in items:
        it.cmb.SelectedIndex = 0
        it.chk.IsChecked = False
    ui["chkAll"].IsChecked = False
    update_count()


# --- apply ---------------------------------------------------------------------

def assigned_items():
    return [it for it in items if it.cmb.SelectedIndex > 0 and not it.lock]


def run_apply():
    todo = assigned_items()
    done, skipped = [], []
    notes = {"rotated": 0, "outline": 0}
    t = Transaction(doc, TOOL_NAME)
    t.Start()
    try:
        for it in todo:
            hb = state["boxes"].get(it.cmb.SelectedItem)
            if hb is None:
                skipped.append((it.name, "Scope box not found in the link"))
                continue
            st = SubTransaction(doc)
            st.Start()
            try:
                note = apply_crop(it.view, hb)
                st.Commit()
                done.append(it.name)
                if note:
                    notes[note] += 1
            except Exception as e:
                st.RollBack()
                skipped.append((it.name, str(e)))
        t.Commit()
    except Exception as e:
        t.RollBack()
        show_msg("Nothing was changed. {}".format(e), "error")
        return

    lines = []
    if done:
        lines.append(u"\u2714  Cropped {} from {}.".format(plural(len(done), "view"), state["label"]))
    if notes["rotated"]:
        lines.append("{} follow a rotated scope box, so Revit shows a non-rectangular crop there."
                     .format(plural(notes["rotated"], "plan crop")))
    if notes["outline"]:
        lines.append("{} sit at an angle to the scope box, so the crop covers the box's full outline."
                     .format(plural(notes["outline"], "view")))
    if state["status"] == "warn" and done:
        lines.append("Shared coordinates mismatch noted. Crops follow the grids, which match exactly.")
    if skipped:
        lines.append("Skipped {}:".format(plural(len(skipped), "view")))
        for name, reason in skipped[:8]:
            lines.append(u"   \u2022 {}: {}".format(name, reason))
        if len(skipped) > 8:
            lines.append("   and {} more".format(len(skipped) - 8))
    show_msg("\n".join(lines), "ok" if done else "error")


def on_apply(sender, args):
    hide_msg()
    hide_confirm()
    if not assigned_items():
        show_msg("Assign a scope box to at least one view first.", "error")
        return
    status = state["status"]
    if status in ("bad", "na"):
        bg, fg, _ = STATUS_COLORS[status]
        ui["bdConfirm"].Background = brush(bg)
        ui["tbConfirm"].Foreground = brush(fg)
        if status == "bad":
            ui["tbConfirm"].Text = ("Grids or levels don't match exactly. Crops will follow the link as it's "
                                    "placed, which is likely wrong. Apply anyway?")
        else:
            ui["tbConfirm"].Text = "The geometry couldn't be verified. Apply anyway?"
        ui["bdConfirm"].Visibility = Visibility.Visible
        return
    run_apply()


def on_yes(sender, args):
    hide_confirm()
    run_apply()


def on_no(sender, args):
    hide_confirm()


# --- wire up and show -------------------------------------------------------

build_list()
build_chips()
refresh_list()

link_labels = List[str]()
for lbl, _i in links:
    link_labels.Add(lbl)
ui["cmbLink"].ItemsSource = link_labels

ui["bdAlignHead"].MouseLeftButtonUp += MouseButtonEventHandler(on_align_click)
ui["txtSearch"].TextChanged += TextChangedEventHandler(on_search)
ui["chkAll"].Click += RoutedEventHandler(on_check_all)
ui["btnAssign"].Click += RoutedEventHandler(on_assign)
ui["btnClear"].Click += RoutedEventHandler(on_clear)
ui["btnApply"].Click += RoutedEventHandler(on_apply)
ui["btnYes"].Click += RoutedEventHandler(on_yes)
ui["btnNo"].Click += RoutedEventHandler(on_no)
ui["cmbLink"].SelectionChanged += SelectionChangedEventHandler(on_link_changed)
ui["cmbLink"].SelectedIndex = 0

try:
    WindowInteropHelper(window).Owner = uiapp.MainWindowHandle
except Exception:
    pass

frame = DispatcherFrame()


def on_closed(sender, args):
    frame.Continue = False


window.Closed += EventHandler(on_closed)
window.Show()
Dispatcher.PushFrame(frame)
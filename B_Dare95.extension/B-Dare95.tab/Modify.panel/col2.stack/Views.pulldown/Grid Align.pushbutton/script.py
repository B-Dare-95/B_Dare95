# -*- coding: utf-8 -*-
__title__ = "Grid Head\nAligner"
__doc__ = ("Sets which view side shows grid bubbles and aligns grid ends "
           "to the crop region with a per-side offset (mm, model distance). "
           "Works on the active view, the active sheet, selected viewports or "
           "views, or picked sheets.")

import clr
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from System import EventHandler
from System.Windows import (RoutedEventHandler, Thickness, TextAlignment,
                            TextTrimming, VerticalAlignment, Visibility)
from System.Windows.Markup import XamlReader
from System.Windows.Controls import (CheckBox, StackPanel, TextBlock,
                                     Orientation, Canvas,
                                     TextChangedEventHandler)
from System.Windows.Shapes import Line as WLine, Ellipse, Rectangle
from System.Windows.Media import SolidColorBrush, ColorConverter, DoubleCollection
from System.Windows.Threading import Dispatcher, DispatcherFrame
from System.Windows.Interop import WindowInteropHelper

from Autodesk.Revit.DB import (FilteredElementCollector, BuiltInCategory,
                               Grid, MultiSegmentGrid, ViewSheet, ViewType,
                               View, Viewport,
                               DatumEnds, DatumExtentType, XYZ, Transaction)
from Autodesk.Revit.DB import Line as DBLine
from Autodesk.Revit.UI import TaskDialog, TaskDialogCommonButtons

from pyrevit import revit, script, forms

doc = revit.doc
cfg = script.get_config()

MM = 1.0 / 304.8
ENDS = (DatumEnds.End0, DatumEnds.End1)
VS = DatumExtentType.ViewSpecific
SIDES = ("t", "b", "l", "r")
MAX_LISTED = 25
GRID_VIEW_TYPES = [ViewType.FloorPlan, ViewType.CeilingPlan,
                   ViewType.EngineeringPlan, ViewType.AreaPlan,
                   ViewType.Section, ViewType.Elevation, ViewType.Detail]


# ---------------------------------------------------------------- helpers
def id_val(eid):
    try:
        return eid.Value
    except AttributeError:
        return eid.IntegerValue


def view_issue(v):
    """(kind, message) or None. kind 'type' = never shows grids (ignored
    silently), kind 'crop' = could show grids but has no crop (reported)."""
    if v is None or v.IsTemplate:
        return ("type", u"not a usable view")
    if v.ViewType not in GRID_VIEW_TYPES:
        return ("type", u"{} views can't show grids".format(v.ViewType))
    if not v.CropBoxActive:
        return ("crop", u"crop region is off")
    return None


def sheet_label(sheet):
    return u"{} - {}".format(sheet.SheetNumber, sheet.Name)


def sheet_views(sheet):
    out = []
    for vid in sheet.GetAllPlacedViews():
        v = doc.GetElement(vid)
        if v is not None:
            out.append(v)
    return out


def collect_sheets():
    rows = []
    for s in FilteredElementCollector(doc).OfClass(ViewSheet):
        if s.IsPlaceholder:
            continue
        views = sheet_views(s)
        usable = len([v for v in views if view_issue(v) is None])
        rows.append({"sheet": s, "views": views, "usable": usable})
    rows.sort(key=lambda r: r["sheet"].SheetNumber)
    return rows


def selected_views():
    """Views picked before running: viewports selected on a sheet, or views
    selected in the Project Browser. Returns [(where, view, sheet_or_None)]."""
    out, seen = [], set()
    for eid in revit.uidoc.Selection.GetElementIds():
        e = doc.GetElement(eid)
        sheet = None
        if isinstance(e, Viewport):
            v = doc.GetElement(e.ViewId)
            sheet = doc.GetElement(e.SheetId)
        elif isinstance(e, View) and not isinstance(e, ViewSheet):
            v = e
        else:
            continue
        if v is None or id_val(v.Id) in seen:
            continue
        seen.add(id_val(v.Id))
        where = (u"{}  |  {}".format(sheet.SheetNumber, v.Name)
                 if sheet is not None else v.Name)
        out.append((where, v, sheet))
    return out


def multi_segment_ids():
    ids = set()
    for msg in FilteredElementCollector(doc).OfClass(MultiSegmentGrid):
        try:
            for gid in msg.GetGridIds():
                ids.add(id_val(gid))
        except Exception:
            pass
    return ids


# ---------------------------------------------------------- view geometry
def view_frame(view):
    return (view.Origin, view.RightDirection, view.UpDirection)


def crop_extents(view, frame):
    """(umin, umax, vmin, vmax) of the crop in view right/up coordinates."""
    o, r, u = frame
    pts = []
    try:
        for loop in view.GetCropRegionShapeManager().GetCropShape():
            for c in loop:
                pts.append(c.GetEndPoint(0))
                pts.append(c.GetEndPoint(1))
    except Exception:
        pts = []
    if not pts:
        bb = view.CropBox
        tf = bb.Transform
        for x in (bb.Min.X, bb.Max.X):
            for y in (bb.Min.Y, bb.Max.Y):
                pts.append(tf.OfPoint(XYZ(x, y, bb.Min.Z)))
    us = [p.Subtract(o).DotProduct(r) for p in pts]
    vs = [p.Subtract(o).DotProduct(u) for p in pts]
    return (min(us), max(us), min(vs), max(vs))


def end_sides(p0, p1, frame):
    """View side of (End0, End1): 't'/'b' for grids running mostly
    up-down on screen, 'l'/'r' for grids running mostly left-right."""
    o, r, u = frame
    d = p1.Subtract(p0)
    du = d.DotProduct(r)
    dv = d.DotProduct(u)
    if abs(du) < 1e-6 and abs(dv) < 1e-6:
        return None
    if abs(dv) >= abs(du):
        return ("b", "t") if dv > 0 else ("t", "b")
    return ("l", "r") if du > 0 else ("r", "l")


def end_target(p0, d, side, frame, ext, off):
    """Point on the grid line where it meets crop edge + offset."""
    o, r, u = frame
    rel = p0.Subtract(o)
    if side in ("t", "b"):
        cur, comp = rel.DotProduct(u), d.DotProduct(u)
        goal = ext[3] + off["t"] if side == "t" else ext[2] - off["b"]
    else:
        cur, comp = rel.DotProduct(r), d.DotProduct(r)
        goal = ext[0] - off["l"] if side == "l" else ext[1] + off["r"]
    return p0.Add(d.Multiply((goal - cur) / comp))


def view_curve(g, view):
    for et in (VS, DatumExtentType.Model):
        try:
            cs = g.GetCurvesInView(et, view)
            if cs is not None and cs.Count > 0:
                return cs[0]
        except Exception:
            pass
    return None


def make_2d(g, end, view):
    if g.GetDatumExtentTypeInView(end, view) != VS:
        g.SetDatumExtentType(end, view, VS)


def has_leader(g, end, view):
    try:
        return g.GetLeader(end, view) is not None
    except Exception:
        return False


# ---------------------------------------------------------------- core
def align_grid(g, view, frame, ext, off, note):
    for end in ENDS:
        make_2d(g, end, view)
    c = g.GetCurvesInView(VS, view)[0]
    p0, p1 = c.GetEndPoint(0), c.GetEndPoint(1)
    sides = end_sides(p0, p1, frame)
    if sides is None:
        return False
    d = p1.Subtract(p0).Normalize()

    pts = [p0, p1]
    for i in (0, 1):
        if has_leader(g, ENDS[i], view):
            note(u"end with a leader left in place")
            continue
        pts[i] = end_target(p0, d, sides[i], frame, ext, off)
    q0, q1 = pts

    if q1.Subtract(q0).DotProduct(d) < 0.01:
        note(u"offsets would collapse the grid - not aligned")
        return False
    if q0.IsAlmostEqualTo(p0) and q1.IsAlmostEqualTo(p1):
        return False
    new = DBLine.CreateBound(q0, q1)
    if not g.IsCurveValidInView(VS, view, new):
        note(u"Revit rejected the new extents")
        return False
    g.SetCurveInView(VS, view, new)
    return True


def set_bubbles(g, view, sides, bub):
    changed = False
    for end, side in zip(ENDS, sides):
        want = bub[side]
        if bool(g.IsBubbleVisibleInView(end, view)) == want:
            continue
        make_2d(g, end, view)   # keeps the change in this view only
        if want:
            g.ShowBubbleInView(end, view)
        else:
            g.HideBubbleInView(end, view)
        changed = True
    return changed


def process_view(view, where, opts, multiseg, report):
    frame = view_frame(view)
    ext = crop_extents(view, frame)
    grids = [e for e in FilteredElementCollector(doc, view.Id)
             .OfCategory(BuiltInCategory.OST_Grids)
             .WhereElementIsNotElementType() if isinstance(e, Grid)]
    updated = 0
    for g in grids:
        tag = u"{}  |  grid {}".format(where, g.Name)

        def note(msg, tag=tag):
            report.append(u"{}  -  {}".format(tag, msg))

        if id_val(g.Id) in multiseg:
            note(u"multi-segment grid - skipped")
            continue
        try:
            c = view_curve(g, view)
            if c is None:
                note(u"no curve in this view")
                continue
            sides = end_sides(c.GetEndPoint(0), c.GetEndPoint(1), frame)
            if sides is None:
                note(u"runs along the view direction - skipped")
                continue
            changed = False
            if opts["do_align"]:
                if g.IsCurved:
                    note(u"curved grid - ends not aligned")
                else:
                    changed = align_grid(g, view, frame, ext,
                                         opts["off"], note) or changed
            if opts["do_bubbles"]:
                changed = set_bubbles(g, view, sides, opts["bub"]) or changed
            if changed:
                updated += 1
        except Exception as ex:
            note(u"failed: {}".format(ex))
    return updated


# ------------------------------------------------------------------ UI
XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Grid Head Aligner" SizeToContent="WidthAndHeight"
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
    <Style x:Key="AccentBtn" TargetType="Button">
      <Setter Property="Background" Value="#F1C21B"/>
      <Setter Property="Foreground" Value="#161616"/>
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
                <Setter TargetName="bd" Property="Background" Value="#F4D35E"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style x:Key="Tgl" TargetType="ToggleButton">
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Height" Value="30"/>
      <Setter Property="Padding" Value="8,0"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ToggleButton">
            <Border x:Name="bd" Background="{TemplateBinding Background}"
                    CornerRadius="6" Padding="{TemplateBinding Padding}">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="bd" Property="Background" Value="#525252"/>
              </Trigger>
              <Trigger Property="IsChecked" Value="True">
                <Setter TargetName="bd" Property="Background" Value="#F1C21B"/>
                <Setter Property="Foreground" Value="#161616"/>
              </Trigger>
              <Trigger Property="IsEnabled" Value="False">
                <Setter Property="Opacity" Value="0.4"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style TargetType="TextBox">
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="BorderBrush" Value="#525252"/>
      <Setter Property="BorderThickness" Value="1"/>
      <Setter Property="CaretBrush" Value="#F4F4F4"/>
      <Setter Property="Height" Value="30"/>
      <Setter Property="Padding" Value="6,0"/>
      <Setter Property="VerticalContentAlignment" Value="Center"/>
    </Style>
    <Style TargetType="CheckBox">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="VerticalContentAlignment" Value="Center"/>
      <Setter Property="Cursor" Value="Hand"/>
    </Style>
    <Style x:Key="Sub" TargetType="TextBlock">
      <Setter Property="Foreground" Value="#A8A8A8"/>
    </Style>
  </Window.Resources>

  <StackPanel Margin="12">
    <Grid>
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="340"/>
        <ColumnDefinition Width="10"/>
        <ColumnDefinition Width="340"/>
      </Grid.ColumnDefinitions>
      <Grid.RowDefinitions>
        <RowDefinition Height="Auto"/>
        <RowDefinition Height="10"/>
        <RowDefinition Height="Auto"/>
      </Grid.RowDefinitions>

      <Border Grid.Row="0" Grid.Column="0" Background="#262626" CornerRadius="8" Padding="12">
        <StackPanel>
          <TextBlock Text="Apply to" Style="{StaticResource Sub}" Margin="0,0,0,8"/>
          <UniformGrid Columns="2">
            <ToggleButton x:Name="tglView" Content="Active view" Style="{StaticResource Tgl}" Margin="0,0,3,6"/>
            <ToggleButton x:Name="tglSheet" Content="Active sheet" Style="{StaticResource Tgl}" Margin="3,0,0,6"/>
            <ToggleButton x:Name="tglSel" Content="Selected views" Style="{StaticResource Tgl}" Margin="0,0,3,0"/>
            <ToggleButton x:Name="tglPick" Content="Picked sheets" Style="{StaticResource Tgl}" Margin="3,0,0,0"/>
          </UniformGrid>
          <StackPanel x:Name="pnlSheets" Margin="0,10,0,0">
            <Grid>
              <TextBox x:Name="txtSearch"/>
              <TextBlock x:Name="txtHint" Text="Search sheets" Foreground="#6F6F6F"
                         Margin="9,0,0,0" VerticalAlignment="Center" IsHitTestVisible="False"/>
            </Grid>
            <DockPanel Margin="0,6,0,4">
              <StackPanel DockPanel.Dock="Right" Orientation="Horizontal">
                <Button x:Name="btnAll" Content="All" Style="{StaticResource Btn}" Height="24" Margin="0,0,4,0"/>
                <Button x:Name="btnNone" Content="None" Style="{StaticResource Btn}" Height="24"/>
              </StackPanel>
              <TextBlock x:Name="txtCount" Style="{StaticResource Sub}" VerticalAlignment="Center"/>
            </DockPanel>
            <Border Background="#161616" CornerRadius="6" Height="210">
              <ScrollViewer VerticalScrollBarVisibility="Auto">
                <StackPanel x:Name="pnlList" Margin="4"/>
              </ScrollViewer>
            </Border>
          </StackPanel>
        </StackPanel>
      </Border>

      <Border Grid.Row="0" Grid.Column="2" Background="#262626" CornerRadius="8" Padding="10">
        <DockPanel>
          <TextBlock DockPanel.Dock="Top" Text="Preview" Style="{StaticResource Sub}" Margin="2,0,0,6"/>
          <StackPanel DockPanel.Dock="Bottom" Orientation="Horizontal" Margin="2,6,0,0">
            <Border Width="16" Height="1" BorderBrush="#A8A8A8" BorderThickness="0,1,0,0" VerticalAlignment="Center"/>
            <TextBlock Text=" crop box" Style="{StaticResource Sub}" FontSize="11" Margin="2,0,14,0"/>
            <Border Width="16" Height="2" Background="#F1C21B" VerticalAlignment="Center"/>
            <TextBlock Text=" offset" Style="{StaticResource Sub}" FontSize="11" Margin="2,0,0,0"/>
          </StackPanel>
          <Viewbox Stretch="Uniform">
            <Canvas x:Name="cvPreview" Width="340" Height="330" ClipToBounds="True"/>
          </Viewbox>
        </DockPanel>
      </Border>

      <Border Grid.Row="2" Grid.Column="0" Background="#262626" CornerRadius="8" Padding="12">
        <StackPanel>
          <CheckBox x:Name="chkBub" Content="Set grid bubbles" FontSize="13" Margin="0,0,0,10"/>
          <StackPanel x:Name="pnlBub">
            <TextBlock Text="Show bubble on view side" Style="{StaticResource Sub}" Margin="0,0,0,8"/>
            <Grid HorizontalAlignment="Center">
              <Grid.ColumnDefinitions>
                <ColumnDefinition Width="80"/>
                <ColumnDefinition Width="80"/>
                <ColumnDefinition Width="80"/>
              </Grid.ColumnDefinitions>
              <Grid.RowDefinitions>
                <RowDefinition Height="36"/>
                <RowDefinition Height="36"/>
                <RowDefinition Height="36"/>
              </Grid.RowDefinitions>
              <ToggleButton x:Name="tglT" Grid.Row="0" Grid.Column="1" Content="Top" Style="{StaticResource Tgl}" Margin="3"/>
              <ToggleButton x:Name="tglL" Grid.Row="1" Grid.Column="0" Content="Left" Style="{StaticResource Tgl}" Margin="3"/>
              <TextBlock Grid.Row="1" Grid.Column="1" Text="view" Foreground="#525252" FontSize="11"
                         HorizontalAlignment="Center" VerticalAlignment="Center"/>
              <ToggleButton x:Name="tglR" Grid.Row="1" Grid.Column="2" Content="Right" Style="{StaticResource Tgl}" Margin="3"/>
              <ToggleButton x:Name="tglB" Grid.Row="2" Grid.Column="1" Content="Bottom" Style="{StaticResource Tgl}" Margin="3"/>
            </Grid>
          </StackPanel>
        </StackPanel>
      </Border>

      <Border Grid.Row="2" Grid.Column="2" Background="#262626" CornerRadius="8" Padding="12">
        <StackPanel>
          <CheckBox x:Name="chkAlign" Content="Align grid ends to crop" FontSize="13" Margin="0,0,0,10"/>
          <StackPanel x:Name="pnlAlign">
            <TextBlock Text="Offset from crop edge (mm)" Style="{StaticResource Sub}" Margin="0,0,0,8"/>
            <Grid HorizontalAlignment="Center">
              <Grid.ColumnDefinitions>
                <ColumnDefinition Width="80"/>
                <ColumnDefinition Width="80"/>
                <ColumnDefinition Width="80"/>
              </Grid.ColumnDefinitions>
              <Grid.RowDefinitions>
                <RowDefinition Height="36"/>
                <RowDefinition Height="36"/>
                <RowDefinition Height="36"/>
              </Grid.RowDefinitions>
              <TextBox x:Name="txtT" Grid.Row="0" Grid.Column="1" Margin="3" TextAlignment="Center"/>
              <TextBox x:Name="txtL" Grid.Row="1" Grid.Column="0" Margin="3" TextAlignment="Center"/>
              <TextBlock Grid.Row="1" Grid.Column="1" Text="crop" Foreground="#525252" FontSize="11"
                         HorizontalAlignment="Center" VerticalAlignment="Center"/>
              <TextBox x:Name="txtR" Grid.Row="1" Grid.Column="2" Margin="3" TextAlignment="Center"/>
              <TextBox x:Name="txtB" Grid.Row="2" Grid.Column="1" Margin="3" TextAlignment="Center"/>
            </Grid>
            <CheckBox x:Name="chkLink" Content="Same offset on all sides" Margin="0,10,0,4"/>
            <TextBlock Text="Positive = outside the crop, negative = inside"
                       Style="{StaticResource Sub}" FontSize="11"/>
          </StackPanel>
        </StackPanel>
      </Border>
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


def cv_rect(cv, x, y, w, h, stroke=None, fill=None, dash=None, opacity=1.0):
    r = Rectangle()
    r.Width, r.Height = w, h
    if stroke:
        r.Stroke = brush(stroke)
        r.StrokeThickness = 1
    if fill:
        r.Fill = brush(fill)
    if dash:
        r.StrokeDashArray = DoubleCollection.Parse(dash)
    r.Opacity = opacity
    Canvas.SetLeft(r, x)
    Canvas.SetTop(r, y)
    cv.Children.Add(r)


def cv_bubble(cv, cx, cy, text, rad=9):
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
    tb.FontSize = 11
    tb.Foreground = brush("#F4F4F4")
    tb.Width = rad * 2
    tb.TextAlignment = TextAlignment.Center
    Canvas.SetLeft(tb, cx - rad)
    Canvas.SetTop(tb, cy - 8)
    cv.Children.Add(tb)


def draw_preview(cv, do_b, do_a, bub, off):
    cv.Children.Clear()
    x0, x1, y0, y1 = 80, 260, 80, 250
    rad = 9
    vgrids = [(120, "1"), (170, "2"), (220, "3")]
    hgrids = [(130, "A"), (200, "B")]
    messy = {"t": [40, 25, 52], "b": [285, 300, 276],
             "l": [45, 30], "r": [290, 310]}

    def px(mm):
        return max(-45.0, min(45.0, mm * 0.02))

    shown = bub if do_b else {"t": True, "b": True, "l": True, "r": False}
    dash = "10 3 2 3"
    cv_rect(cv, x0 + 30, y0 + 30, x1 - x0 - 60, y1 - y0 - 60,
            fill="#393939", opacity=0.5)
    cv_rect(cv, x0, y0, x1 - x0, y1 - y0, stroke="#A8A8A8", dash="6 4")

    for i, (x, n) in enumerate(vgrids):
        t = y0 - px(off["t"]) if do_a else messy["t"][i]
        b = y1 + px(off["b"]) if do_a else messy["b"][i]
        cv_line(cv, x, t, x, b, "#A8A8A8", 1, dash)
        if do_a:
            cv_line(cv, x, y0, x, t, "#F1C21B", 2)
            cv_line(cv, x, y1, x, b, "#F1C21B", 2)
        if shown["t"]:
            cv_bubble(cv, x, t - rad, n)
        if shown["b"]:
            cv_bubble(cv, x, b + rad, n)

    for i, (y, n) in enumerate(hgrids):
        l = x0 - px(off["l"]) if do_a else messy["l"][i]
        r = x1 + px(off["r"]) if do_a else messy["r"][i]
        cv_line(cv, l, y, r, y, "#A8A8A8", 1, dash)
        if do_a:
            cv_line(cv, x0, y, l, y, "#F1C21B", 2)
            cv_line(cv, x1, y, r, y, "#F1C21B", 2)
        if shown["l"]:
            cv_bubble(cv, l - rad, y, n)
        if shown["r"]:
            cv_bubble(cv, r + rad, y, n)


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


def show_ui(active, active_is_sheet, rows, sel):
    w = XamlReader.Parse(XAML)
    f = w.FindName
    result = {"ok": False}

    tgl_scope = {"view": f("tglView"), "sheet": f("tglSheet"),
                 "sel": f("tglSel"), "pick": f("tglPick")}
    tgl_side = {"t": f("tglT"), "b": f("tglB"), "l": f("tglL"),
                "r": f("tglR")}
    txt_off = {"t": f("txtT"), "b": f("txtB"), "l": f("txtL"),
               "r": f("txtR")}
    chk_bub, chk_align, chk_link = f("chkBub"), f("chkAlign"), f("chkLink")
    pnl_bub, pnl_align, pnl_sheets = f("pnlBub"), f("pnlAlign"), f("pnlSheets")
    pnl_list, txt_search, txt_hint = f("pnlList"), f("txtSearch"), f("txtHint")
    txt_count, txt_msg, cv = f("txtCount"), f("txtMsg"), f("cvPreview")

    # ---- restore settings
    defaults_bub = {"t": True, "b": False, "l": True, "r": False}
    for s in SIDES:
        tgl_side[s].IsChecked = opt_bool("bub_" + s, defaults_bub[s])
        txt_off[s].Text = u"{:g}".format(opt_float("off_" + s, 1000.0))
    chk_bub.IsChecked = opt_bool("do_bubbles", True)
    chk_align.IsChecked = opt_bool("do_align", True)
    chk_link.IsChecked = opt_bool("link_offsets", False)

    tgl_scope["sel"].IsEnabled = bool(sel)
    if sel:
        tgl_scope["sel"].Content = u"Selected views ({})".format(len(sel))
    else:
        tgl_scope["sel"].ToolTip = (u"Select viewports on the sheet (or views "
                                    u"in the Project Browser) before running")
    tgl_scope["view"].IsEnabled = not active_is_sheet
    tgl_scope["sheet"].IsEnabled = active_is_sheet
    tgl_scope["view"].ToolTip = u"The active view is a sheet" if active_is_sheet else None
    tgl_scope["sheet"].ToolTip = None if active_is_sheet else u"The active view isn't a sheet"

    state = {"scope": None, "off": {}, "busy": [False]}
    for s in SIDES:
        state["off"][s] = opt_float("off_" + s, 1000.0)

    # ---- sheet list
    list_rows = []

    def update_count(*a):
        n = len([r for r in list_rows if r["cb"].IsChecked])
        txt_count.Text = u"{} of {} selected".format(n, len(list_rows))
        txt_msg.Text = u""

    for r in rows:
        sh = r["sheet"]
        cb = CheckBox()
        cb.Margin = Thickness(2, 2, 2, 2)
        sp = StackPanel()
        sp.Orientation = Orientation.Horizontal
        t1 = TextBlock()
        t1.Text = sh.SheetNumber
        t1.Width = 64
        t1.Foreground = brush("#A8A8A8")
        t1.TextTrimming = TextTrimming.CharacterEllipsis
        t2 = TextBlock()
        t2.Text = sh.Name
        t2.Width = 170
        t2.Foreground = brush("#F4F4F4")
        t2.TextTrimming = TextTrimming.CharacterEllipsis
        t3 = TextBlock()
        t3.Text = u"{} views".format(r["usable"])
        t3.Foreground = brush("#6F6F6F")
        t3.FontSize = 11
        t3.VerticalAlignment = VerticalAlignment.Center
        for t in (t1, t2, t3):
            sp.Children.Add(t)
        cb.Content = sp
        cb.Checked += RoutedEventHandler(update_count)
        cb.Unchecked += RoutedEventHandler(update_count)
        pnl_list.Children.Add(cb)
        list_rows.append({"cb": cb, "row": r,
                          "key": (sh.SheetNumber + u" " + sh.Name).lower()})

    def visible_rows():
        return [lr for lr in list_rows if lr["cb"].Visibility == Visibility.Visible]

    def on_search(s, e):
        q = txt_search.Text.strip().lower()
        txt_hint.Opacity = 0.0 if txt_search.Text else 1.0
        for lr in list_rows:
            lr["cb"].Visibility = (Visibility.Visible if q in lr["key"]
                                   else Visibility.Collapsed)

    txt_search.TextChanged += TextChangedEventHandler(on_search)

    def on_all(s, e):
        for lr in visible_rows():
            lr["cb"].IsChecked = True

    def on_none(s, e):
        for lr in visible_rows():
            lr["cb"].IsChecked = False

    f("btnAll").Click += RoutedEventHandler(on_all)
    f("btnNone").Click += RoutedEventHandler(on_none)

    # ---- state / preview
    def redraw(*a):
        do_b = bool(chk_bub.IsChecked)
        do_a = bool(chk_align.IsChecked)
        pnl_bub.IsEnabled = do_b
        pnl_bub.Opacity = 1.0 if do_b else 0.4
        pnl_align.IsEnabled = do_a
        pnl_align.Opacity = 1.0 if do_a else 0.4
        bub = dict((s, bool(tgl_side[s].IsChecked)) for s in SIDES)
        draw_preview(cv, do_b, do_a, bub, state["off"])

    def set_scope(name):
        if not tgl_scope[name].IsEnabled:
            name = "pick"
        state["scope"] = name
        for k, t in tgl_scope.items():
            t.IsChecked = (k == name)
        pnl_sheets.IsEnabled = (name == "pick")
        pnl_sheets.Opacity = 1.0 if name == "pick" else 0.4
        txt_msg.Text = u""

    def scope_handler(name):
        def h(s, e):
            set_scope(name)
        return h

    for k, t in tgl_scope.items():
        t.Click += RoutedEventHandler(scope_handler(k))

    for s in SIDES:
        tgl_side[s].Click += RoutedEventHandler(redraw)

    def off_handler(side):
        def h(s, e):
            if state["busy"][0]:
                return
            txt_msg.Text = u""
            try:
                v = parse_mm(txt_off[side].Text)
            except Exception:
                return
            if chk_link.IsChecked:
                state["busy"][0] = True
                for o in SIDES:
                    state["off"][o] = v
                    if o != side:
                        txt_off[o].Text = txt_off[side].Text
                state["busy"][0] = False
            else:
                state["off"][side] = v
            redraw()
        return h

    for s in SIDES:
        txt_off[s].TextChanged += TextChangedEventHandler(off_handler(s))

    def on_link(s, e):
        if chk_link.IsChecked:
            state["busy"][0] = True
            for o in ("b", "l", "r"):
                txt_off[o].Text = txt_off["t"].Text
                state["off"][o] = state["off"]["t"]
            state["busy"][0] = False
            redraw()

    chk_link.Checked += RoutedEventHandler(on_link)
    chk_bub.Checked += RoutedEventHandler(redraw)
    chk_bub.Unchecked += RoutedEventHandler(redraw)
    chk_align.Checked += RoutedEventHandler(redraw)
    chk_align.Unchecked += RoutedEventHandler(redraw)

    saved_scope = cfg.get_option("scope", "view")
    if saved_scope not in tgl_scope or saved_scope == "sel":
        saved_scope = "view"
    if sel:
        saved_scope = "sel"
    if saved_scope != "pick" and not tgl_scope[saved_scope].IsEnabled:
        saved_scope = "sheet" if active_is_sheet else "view"
    set_scope(saved_scope)
    update_count()
    redraw()

    # ---- apply / cancel
    def fail(msg):
        txt_msg.Text = msg

    def on_apply(s, e):
        do_b = bool(chk_bub.IsChecked)
        do_a = bool(chk_align.IsChecked)
        if not (do_b or do_a):
            return fail(u"Turn on at least one option.")
        off = {}
        for side in SIDES:
            try:
                off[side] = parse_mm(txt_off[side].Text)
            except Exception:
                if do_a:
                    return fail(u"Enter a number (mm) for every offset.")
                off[side] = state["off"][side]

        scope = state["scope"]
        targets = []   # (where, view, sheet_or_None)
        if scope == "view":
            iss = view_issue(active)
            if iss is not None:
                return fail(u"Active view: {}.".format(iss[1]))
            targets.append((active.Name, active, None))
        elif scope == "sel":
            targets = list(sel)
        else:
            if scope == "sheet":
                sheets = [active]
            else:
                sheets = [lr["row"]["sheet"] for lr in list_rows
                          if lr["cb"].IsChecked]
                if not sheets:
                    return fail(u"Pick at least one sheet.")
            for sh in sheets:
                for v in sheet_views(sh):
                    targets.append((u"{}  |  {}".format(sh.SheetNumber, v.Name),
                                    v, sh))

        result.update({
            "ok": True, "scope": scope, "targets": targets,
            "do_bubbles": do_b, "do_align": do_a,
            "bub": dict((k, bool(tgl_side[k].IsChecked)) for k in SIDES),
            "off_mm": off, "link": bool(chk_link.IsChecked)})
        w.Close()

    def on_cancel(s, e):
        w.Close()

    f("btnApply").Click += RoutedEventHandler(on_apply)
    f("btnCancel").Click += RoutedEventHandler(on_cancel)

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


# --------------------------------------------------------------- result
def show_result(res, updated, touched, processed, ignored, report):
    actions = []
    if res["do_bubbles"]:
        actions.append(u"bubbles")
    if res["do_align"]:
        actions.append(u"crop alignment")
    td = TaskDialog("Grid Head Aligner")
    td.MainInstruction = u"{} grids updated in {} of {} views".format(
        updated, touched, processed)
    lines = [u"Actions: {}.".format(u" + ".join(actions))]
    if ignored:
        lines.append(u"{} views on the sheets can't show grids (legends, "
                     u"drafting, 3D, schedules) and were ignored.".format(ignored))
    if report:
        lines.append(u"{} issues - expand details for the list.".format(len(report)))
        shown = report[:MAX_LISTED]
        if len(report) > MAX_LISTED:
            shown.append(u"... and {} more".format(len(report) - MAX_LISTED))
        td.ExpandedContent = u"\n".join(shown)
    td.MainContent = u"\n".join(lines)
    td.CommonButtons = TaskDialogCommonButtons.Ok
    td.Show()


# ----------------------------------------------------------------- main
def main():
    active = doc.ActiveView
    active_is_sheet = isinstance(active, ViewSheet)
    res = show_ui(active, active_is_sheet, collect_sheets(), selected_views())
    if not res["ok"]:
        return

    cfg.set_option("do_bubbles", 1.0 if res["do_bubbles"] else 0.0)
    cfg.set_option("do_align", 1.0 if res["do_align"] else 0.0)
    cfg.set_option("link_offsets", 1.0 if res["link"] else 0.0)
    if res["scope"] != "sel":   # a selection is one-off, never the default
        cfg.set_option("scope", res["scope"])
    for s in SIDES:
        cfg.set_option("bub_" + s, 1.0 if res["bub"][s] else 0.0)
        cfg.set_option("off_" + s, res["off_mm"][s])
    script.save_config()

    opts = {"do_bubbles": res["do_bubbles"], "do_align": res["do_align"],
            "bub": res["bub"],
            "off": dict((s, res["off_mm"][s] * MM) for s in SIDES)}
    multiseg = multi_segment_ids()

    report = []
    seen = set()
    updated, touched, processed, ignored = 0, 0, 0, 0

    t = Transaction(doc, "Align Grid Heads")
    t.Start()
    try:
        for where, view, sheet in res["targets"]:
            key = id_val(view.Id)
            if key in seen:
                continue
            seen.add(key)
            iss = view_issue(view)
            if iss is not None:
                if iss[0] == "type":
                    ignored += 1
                else:
                    report.append(u"{}  -  {}".format(where, iss[1]))
                continue
            processed += 1
            n = process_view(view, where, opts, multiseg, report)
            updated += n
            if n:
                touched += 1
        t.Commit()
    except Exception as ex:
        t.RollBack()
        forms.alert(u"Failed - nothing changed.\n\n{}".format(ex))
        return

    show_result(res, updated, touched, processed, ignored, report)


main()
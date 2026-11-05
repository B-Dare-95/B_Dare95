# -*- coding: utf-8 -*-
__doc__ = """__________________________________________________
Description:

Tidies the levels in section and elevation views: choose which sides show the level heads and line up all level ends at a set distance from the crop region. In views with the crop region off, the ends line up past the outermost grids that show in the view.
Only the chosen views change. The levels' 3D extents stay exactly where they are, so no other view is affected. Works on the active view, active sheet, selected views or views picked from a list.
__________________________________________________
How-to:

-> Select section or elevation viewports or views first if you want to work on just those
-> Click on the button
-> Choose: active view, active sheet, selected views or picked views
-> Pick the head sides and the offset in mm (from the crop edge, or from the outermost grid when the view isn't cropped)
-> Check the preview and click Apply
-> A summary shows how many levels were updated and any skipped
__________________________________________________
Author: Mohamed Bedair"""

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
                               BuiltInParameter, ElementId, Level, ViewType,
                               View, ViewSection, ViewSheet, Viewport,
                               Grid, DatumEnds, DatumExtentType, XYZ,
                               Transaction, SubTransaction)
from Autodesk.Revit.DB import Line as DBLine
from Autodesk.Revit.UI import TaskDialog, TaskDialogCommonButtons

from pyrevit import revit, script, forms

doc = revit.doc
cfg = script.get_config()

TITLE = "Level Head Aligner"
MM = 1.0 / 304.8
ENDS = (DatumEnds.End0, DatumEnds.End1)
VS = DatumExtentType.ViewSpecific
MODEL = DatumExtentType.Model
SIDES = ("l", "r")
MAX_LISTED = 25
LEVEL_VIEW_TYPES = (ViewType.Section, ViewType.Elevation)
SAME = 1e-6     # feet: two points closer than this are the same point


# ---------------------------------------------------------------- helpers
def id_val(eid):
    try:
        return eid.Value
    except AttributeError:
        return eid.IntegerValue


def scope_box_name(level):
    """Name of the scope box controlling the level's extents, or None."""
    try:
        p = level.get_Parameter(BuiltInParameter.DATUM_VOLUME_OF_INTEREST)
        eid = p.AsElementId() if p is not None else None
    except Exception:
        return None
    if eid is None or eid == ElementId.InvalidElementId:
        return None
    box = doc.GetElement(eid)
    return box.Name if box is not None else u"a scope box"


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


def grid_extents(view, frame):
    """(umin, umax) of the outermost grids showing in the view, or None. In a
    section or elevation a grid shows as an up-down line where it crosses the
    view, so its position across the view is one value."""
    o, r, u = frame
    us = []
    for g in FilteredElementCollector(doc, view.Id).OfClass(Grid):
        c = view_curve(g, view)
        if c is None:
            continue
        p0, p1 = c.GetEndPoint(0), c.GetEndPoint(1)
        d = p1.Subtract(p0)
        if abs(d.DotProduct(u)) < abs(d.DotProduct(r)):
            continue        # not up-down on screen
        us.append(p0.Subtract(o).DotProduct(r))
        us.append(p1.Subtract(o).DotProduct(r))
    return (min(us), max(us)) if us else None


def u_of(p, frame):
    o, r, u = frame
    return p.Subtract(o).DotProduct(r)


def end_sides(p0, p1, frame):
    """View side ('l'/'r') of (End0, End1), or None when the level does not
    run left-right on screen."""
    o, r, u = frame
    d = p1.Subtract(p0)
    du = d.DotProduct(r)
    dv = d.DotProduct(u)
    if abs(du) < 1e-6 or abs(dv) > abs(du):
        return None
    return ("l", "r") if du > 0 else ("r", "l")


def point_at_u(p0, d, goal, frame):
    """Point on the level line (through p0, direction d) whose view-right
    coordinate is goal. Z never changes: d is horizontal."""
    o, r, u = frame
    cur = p0.Subtract(o).DotProduct(r)
    comp = d.DotProduct(r)
    return p0.Add(d.Multiply((goal - cur) / comp))


def view_curve(lv, view):
    for et in (VS, MODEL):
        try:
            cs = lv.GetCurvesInView(et, view)
            if cs is not None and cs.Count > 0:
                return cs[0]
        except Exception:
            pass
    return None


def model_ends(lv, view):
    """(End0, End1) of the level's 3D extent as seen in this view, or None."""
    try:
        cs = lv.GetCurvesInView(MODEL, view)
        if cs is not None and cs.Count > 0:
            return (cs[0].GetEndPoint(0), cs[0].GetEndPoint(1))
    except Exception:
        pass
    return None


def moved(before, after):
    if before is None or after is None:
        return before is not after
    return any(before[i].DistanceTo(after[i]) > SAME for i in (0, 1))


def make_2d(lv, end, view):
    if lv.GetDatumExtentTypeInView(end, view) != VS:
        lv.SetDatumExtentType(end, view, VS)


def has_leader(lv, end, view):
    try:
        return lv.GetLeader(end, view) is not None
    except Exception:
        return False


# ---------------------------------------------------------------- the views
def view_issue(v):
    """None, or why the tool can't work in the view (not a section or
    elevation: ignored silently on sheets)."""
    if v is None or v.IsTemplate:
        return u"not a usable view"
    if v.ViewType not in LEVEL_VIEW_TYPES:
        return u"{} views are not sections or elevations".format(v.ViewType)
    return None


def is_level_view(v):
    return view_issue(v) is None


def sheet_numbers():
    """view id -> sheet number, for every view placed on a sheet."""
    out = {}
    for vp in FilteredElementCollector(doc).OfClass(Viewport):
        sheet = doc.GetElement(vp.SheetId)
        if sheet is not None:
            out[id_val(vp.ViewId)] = sheet.SheetNumber
    return out


def sheet_views(sheet):
    out = []
    for vid in sheet.GetAllPlacedViews():
        v = doc.GetElement(vid)
        if v is not None:
            out.append(v)
    return out


def collect_views():
    """[{view, name, kind, sheet, crop}] of every section and elevation."""
    on_sheet = sheet_numbers()
    rows = []
    for v in FilteredElementCollector(doc).OfClass(ViewSection):
        if not is_level_view(v):
            continue
        rows.append({"view": v, "name": v.Name,
                     "kind": u"Section" if v.ViewType == ViewType.Section else u"Elevation",
                     "sheet": on_sheet.get(id_val(v.Id), u""),
                     "crop": bool(v.CropBoxActive)})
    rows.sort(key=lambda r: (r["kind"], r["name"].lower()))
    return rows


def selected_views():
    """Sections / elevations picked before running: viewports selected on a
    sheet, or views selected in the Project Browser. [(where, view)]"""
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
        if v is None or not is_level_view(v) or id_val(v.Id) in seen:
            continue
        seen.add(id_val(v.Id))
        where = (u"{}  |  {}".format(sheet.SheetNumber, v.Name)
                 if sheet is not None else v.Name)
        out.append((where, v))
    return out


# ------------------------------------------------------------- the levels
def collect_levels(view):
    """[{level, name, elev_mm, box}] of the levels seen in the view, top first."""
    frame = view_frame(view)
    rows = []
    for e in FilteredElementCollector(doc, view.Id).OfCategory(BuiltInCategory.OST_Levels) \
            .WhereElementIsNotElementType():
        if not isinstance(e, Level):
            continue
        c = view_curve(e, view)
        if c is None or end_sides(c.GetEndPoint(0), c.GetEndPoint(1), frame) is None:
            continue
        try:
            elev = e.ProjectElevation / MM
        except Exception:
            elev = e.Elevation / MM
        rows.append({"level": e, "name": e.Name, "elev_mm": elev, "box": scope_box_name(e)})
    rows.sort(key=lambda r: -r["elev_mm"])
    return rows


# ---------------------------------------------------------------- core
def align_level(lv, view, frame, goals, note):
    """Move the level's 2D ends to goals {'l': u, 'r': u}. True when changed."""
    c = view_curve(lv, view)
    p0, p1 = c.GetEndPoint(0), c.GetEndPoint(1)
    sides = end_sides(p0, p1, frame)
    if sides is None:
        return False
    d = p1.Subtract(p0).Normalize()

    pts = [p0, p1]
    for i in (0, 1):
        if has_leader(lv, ENDS[i], view):
            note(u"end with an elbow left in place")
            continue
        pts[i] = point_at_u(p0, d, goals[sides[i]], frame)
    q0, q1 = pts

    if q1.Subtract(q0).DotProduct(d) < 0.01:
        note(u"offsets would collapse the level - not aligned")
        return False
    if q0.DistanceTo(p0) <= SAME and q1.DistanceTo(p1) <= SAME:
        return False
    for end in ENDS:
        make_2d(lv, end, view)      # 2D first: the 3D extent is never edited
    new = DBLine.CreateBound(q0, q1)
    if not lv.IsCurveValidInView(VS, view, new):
        note(u"Revit rejected the new extents")
        return False
    lv.SetCurveInView(VS, view, new)
    return True


def set_heads(lv, view, frame, heads):
    c = view_curve(lv, view)
    sides = end_sides(c.GetEndPoint(0), c.GetEndPoint(1), frame)
    if sides is None:
        return False
    changed = False
    for end, side in zip(ENDS, sides):
        want = heads[side]
        if bool(lv.IsBubbleVisibleInView(end, view)) == want:
            continue
        make_2d(lv, end, view)   # keeps the change in this view only
        if want:
            lv.ShowBubbleInView(end, view)
        else:
            lv.HideBubbleInView(end, view)
        changed = True
    return changed


def process_view(view, where, opts, report):
    """Tidy the levels of one view. Call inside a transaction.
    Returns the number of levels changed."""
    frame = view_frame(view)
    goals = None
    if opts["do_align"]:
        if view.CropBoxActive:
            ext = crop_extents(view, frame)
        else:
            ext = grid_extents(view, frame)
            if ext is None:
                report.append(u"{}  -  not cropped and no grids show in it - level ends "
                              u"not aligned".format(where))
        if ext is not None:
            goals = {"l": ext[0] - opts["off"]["l"], "r": ext[1] + opts["off"]["r"]}

    updated = 0
    for row in collect_levels(view):
        lv = row["level"]
        tag = u"{}  |  level {}".format(where, lv.Name)

        def note(msg, tag=tag):
            report.append(u"{}  -  {}".format(tag, msg))

        if row["box"]:
            note(u"extents follow scope box “{}” - skipped".format(row["box"]))
            continue
        st = SubTransaction(doc)
        st.Start()
        try:
            before = model_ends(lv, view)
            changed = False
            if goals is not None:
                changed = align_level(lv, view, frame, goals, note) or changed
            if opts["do_heads"]:
                changed = set_heads(lv, view, frame, opts["heads"]) or changed
            if not changed:
                st.RollBack()
                continue
            doc.Regenerate()
            if moved(before, model_ends(lv, view)):
                st.RollBack()
                note(u"its 3D extent would have moved - left as it was")
                continue
            st.Commit()
            updated += 1
        except Exception as ex:
            if st.HasStarted() and not st.HasEnded():
                st.RollBack()
            note(u"failed: {}".format(ex))
    return updated


# ------------------------------------------------------------------ UI
XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Level Head Aligner" SizeToContent="WidthAndHeight"
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
            <ToggleButton x:Name="tglPick" Content="Picked views" Style="{StaticResource Tgl}" Margin="3,0,0,0"/>
          </UniformGrid>
          <StackPanel x:Name="pnlViews" Margin="0,10,0,0">
            <Grid>
              <TextBox x:Name="txtSearch"/>
              <TextBlock x:Name="txtHint" Text="Search sections and elevations" Foreground="#6F6F6F"
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
          <CheckBox x:Name="chkHeads" Content="Set level heads" FontSize="13" Margin="0,0,0,10"/>
          <StackPanel x:Name="pnlHeads">
            <TextBlock Text="Show the level head on view side" Style="{StaticResource Sub}" Margin="0,0,0,8"/>
            <Grid HorizontalAlignment="Center">
              <Grid.ColumnDefinitions>
                <ColumnDefinition Width="80"/>
                <ColumnDefinition Width="80"/>
                <ColumnDefinition Width="80"/>
              </Grid.ColumnDefinitions>
              <ToggleButton x:Name="tglL" Grid.Column="0" Content="Left" Style="{StaticResource Tgl}" Margin="3"/>
              <TextBlock Grid.Column="1" Text="view" Foreground="#525252" FontSize="11"
                         HorizontalAlignment="Center" VerticalAlignment="Center"/>
              <ToggleButton x:Name="tglR" Grid.Column="2" Content="Right" Style="{StaticResource Tgl}" Margin="3"/>
            </Grid>
            <TextBlock Text="Both, one or none: an end that is off hides its head"
                       Style="{StaticResource Sub}" FontSize="11" Margin="0,10,0,0"/>
          </StackPanel>
        </StackPanel>
      </Border>

      <Border Grid.Row="2" Grid.Column="2" Background="#262626" CornerRadius="8" Padding="12">
        <StackPanel>
          <CheckBox x:Name="chkAlign" Content="Align level ends" FontSize="13" Margin="0,0,0,10"/>
          <StackPanel x:Name="pnlAlign">
            <TextBlock Text="Offset from the crop edge (mm)" Style="{StaticResource Sub}" Margin="0,0,0,8"/>
            <Grid HorizontalAlignment="Center">
              <Grid.ColumnDefinitions>
                <ColumnDefinition Width="80"/>
                <ColumnDefinition Width="80"/>
                <ColumnDefinition Width="80"/>
              </Grid.ColumnDefinitions>
              <TextBox x:Name="txtL" Grid.Column="0" Margin="3" TextAlignment="Center"/>
              <TextBlock Grid.Column="1" Text="crop" Foreground="#525252" FontSize="11"
                         HorizontalAlignment="Center" VerticalAlignment="Center"/>
              <TextBox x:Name="txtR" Grid.Column="2" Margin="3" TextAlignment="Center"/>
            </Grid>
            <CheckBox x:Name="chkLink" Content="Same offset on both sides" Margin="0,10,0,4"/>
            <TextBlock Text="Positive = outside the crop, negative = inside"
                       Style="{StaticResource Sub}" FontSize="11"/>
            <TextBlock Text="Uncropped views: the same offset is measured from the outermost grid"
                       Style="{StaticResource Sub}" FontSize="11" TextWrapping="Wrap" Margin="0,4,0,0"/>
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


def cv_head(cv, x, y, text, side, rad=6):
    """A level head: target circle at the line end, the name above it, outside."""
    e = Ellipse()
    e.Width = e.Height = rad * 2
    e.Fill = brush("#161616")
    e.Stroke = brush("#F4F4F4")
    e.StrokeThickness = 1
    Canvas.SetLeft(e, x - rad)
    Canvas.SetTop(e, y - rad)
    cv.Children.Add(e)
    cv_line(cv, x - rad, y, x + rad, y, "#F4F4F4", 1)
    tb = TextBlock()
    tb.Text = text
    tb.FontSize = 10
    tb.Foreground = brush("#F4F4F4")
    tb.Width = 64
    if side == "l":
        tb.TextAlignment = TextAlignment.Right
        Canvas.SetLeft(tb, x - 64)
    else:
        tb.TextAlignment = TextAlignment.Left
        Canvas.SetLeft(tb, x)
    Canvas.SetTop(tb, y - 22)
    cv.Children.Add(tb)


def draw_preview(cv, do_h, do_a, heads, off):
    cv.Children.Clear()
    x0, x1, y0, y1 = 95, 245, 70, 270
    levels = [(110, u"Roof"), (175, u"Level 02"), (240, u"Level 01")]
    messy_l = [60, 82, 48]
    messy_r = [282, 262, 296]

    def px(mm):
        return max(-45.0, min(45.0, mm * 0.02))

    shown = heads if do_h else {"l": False, "r": True}
    dash = "10 3 2 3"
    cv_rect(cv, x0 + 25, y0 + 35, x1 - x0 - 50, y1 - y0 - 35, fill="#393939", opacity=0.5)
    cv_rect(cv, x0, y0, x1 - x0, y1 - y0, stroke="#A8A8A8", dash="6 4")

    for i, (y, name) in enumerate(levels):
        if do_a:
            l, r = x0 - px(off["l"]), x1 + px(off["r"])
        else:
            l, r = messy_l[i], messy_r[i]
        cv_line(cv, l, y, r, y, "#A8A8A8", 1, dash)
        if do_a:
            cv_line(cv, x0, y, l, y, "#F1C21B", 2)
            cv_line(cv, x1, y, r, y, "#F1C21B", 2)
        if shown["l"]:
            cv_head(cv, l, y, name, "l")
        if shown["r"]:
            cv_head(cv, r, y, name, "r")


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
    tgl_side = {"l": f("tglL"), "r": f("tglR")}
    txt_off = {"l": f("txtL"), "r": f("txtR")}
    chk_heads, chk_align, chk_link = f("chkHeads"), f("chkAlign"), f("chkLink")
    pnl_heads, pnl_align, pnl_views = f("pnlHeads"), f("pnlAlign"), f("pnlViews")
    pnl_list, txt_search, txt_hint = f("pnlList"), f("txtSearch"), f("txtHint")
    txt_count, txt_msg, cv = f("txtCount"), f("txtMsg"), f("cvPreview")

    # ---- restore settings
    defaults = {"l": False, "r": True}
    for s in SIDES:
        tgl_side[s].IsChecked = opt_bool("head_" + s, defaults[s])
        txt_off[s].Text = u"{:g}".format(opt_float("off_" + s, 1000.0))
    chk_heads.IsChecked = opt_bool("do_heads", True)
    chk_align.IsChecked = opt_bool("do_align", True)
    chk_link.IsChecked = opt_bool("link_offsets", True)

    active_ok = is_level_view(active)
    tgl_scope["view"].IsEnabled = active_ok
    tgl_scope["view"].ToolTip = None if active_ok else u"The active view isn't a section or elevation"
    tgl_scope["sheet"].IsEnabled = active_is_sheet
    tgl_scope["sheet"].ToolTip = None if active_is_sheet else u"The active view isn't a sheet"
    tgl_scope["sel"].IsEnabled = bool(sel)
    if sel:
        tgl_scope["sel"].Content = u"Selected views ({})".format(len(sel))
    else:
        tgl_scope["sel"].ToolTip = (u"Select section or elevation viewports on a sheet "
                                    u"(or views in the Project Browser) before running")

    state = {"scope": None, "off": {}, "busy": [False]}
    for s in SIDES:
        state["off"][s] = opt_float("off_" + s, 1000.0)

    # ---- view list
    list_rows = []

    def update_count(*a):
        n = len([r for r in list_rows if r["cb"].IsChecked])
        txt_count.Text = u"{} of {} selected".format(n, len(list_rows))
        txt_msg.Text = u""

    for r in rows:
        cb = CheckBox()
        cb.Margin = Thickness(2, 2, 2, 2)
        sp = StackPanel()
        sp.Orientation = Orientation.Horizontal
        t1 = TextBlock()
        t1.Text = r["name"]
        t1.Width = 168
        t1.Foreground = brush("#F4F4F4")
        t1.TextTrimming = TextTrimming.CharacterEllipsis
        t2 = TextBlock()
        t2.Text = r["kind"]
        t2.Width = 58
        t2.Foreground = brush("#A8A8A8")
        t2.FontSize = 11
        t2.VerticalAlignment = VerticalAlignment.Center
        t3 = TextBlock()
        t3.Text = r["sheet"] if r["crop"] else u"uncropped"
        t3.Width = 52
        t3.TextTrimming = TextTrimming.CharacterEllipsis
        t3.Foreground = brush("#6F6F6F" if r["crop"] else "#A8A8A8")
        t3.FontSize = 11
        t3.VerticalAlignment = VerticalAlignment.Center
        for t in (t1, t2, t3):
            sp.Children.Add(t)
        tips = [r["name"]]
        if r["sheet"]:
            tips.append(u"On sheet {}".format(r["sheet"]))
        if not r["crop"]:
            tips.append(u"Crop region is off: level ends line up past the outermost grids")
        cb.ToolTip = u"\n".join(tips)
        cb.Content = sp
        cb.Checked += RoutedEventHandler(update_count)
        cb.Unchecked += RoutedEventHandler(update_count)
        pnl_list.Children.Add(cb)
        list_rows.append({"cb": cb, "row": r,
                          "key": u" ".join([r["name"], r["kind"], r["sheet"]]).lower()})

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
        do_h = bool(chk_heads.IsChecked)
        do_a = bool(chk_align.IsChecked)
        pnl_heads.IsEnabled = do_h
        pnl_heads.Opacity = 1.0 if do_h else 0.4
        pnl_align.IsEnabled = do_a
        pnl_align.Opacity = 1.0 if do_a else 0.4
        heads = dict((s, bool(tgl_side[s].IsChecked)) for s in SIDES)
        draw_preview(cv, do_h, do_a, heads, state["off"])

    def set_scope(name):
        if not tgl_scope[name].IsEnabled:
            name = "pick"
        state["scope"] = name
        for k, t in tgl_scope.items():
            t.IsChecked = (k == name)
        pnl_views.IsEnabled = (name == "pick")
        pnl_views.Opacity = 1.0 if name == "pick" else 0.4
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
            txt_off["r"].Text = txt_off["l"].Text
            state["off"]["r"] = state["off"]["l"]
            state["busy"][0] = False
            redraw()

    chk_link.Checked += RoutedEventHandler(on_link)
    chk_heads.Checked += RoutedEventHandler(redraw)
    chk_heads.Unchecked += RoutedEventHandler(redraw)
    chk_align.Checked += RoutedEventHandler(redraw)
    chk_align.Unchecked += RoutedEventHandler(redraw)

    saved_scope = cfg.get_option("scope", "view")
    if saved_scope not in tgl_scope or saved_scope == "sel":
        saved_scope = "view"
    if sel:
        saved_scope = "sel"
    if saved_scope != "pick" and not tgl_scope[saved_scope].IsEnabled:
        saved_scope = "view" if active_ok else ("sheet" if active_is_sheet else "pick")
    set_scope(saved_scope)
    update_count()
    redraw()

    # ---- apply / cancel
    def fail(msg):
        txt_msg.Text = msg

    def on_apply(s, e):
        do_h = bool(chk_heads.IsChecked)
        do_a = bool(chk_align.IsChecked)
        if not (do_h or do_a):
            return fail(u"Turn on at least one option.")
        off = {}
        for side in SIDES:
            try:
                off[side] = parse_mm(txt_off[side].Text)
            except Exception:
                if do_a:
                    return fail(u"Enter a number (mm) for both offsets.")
                off[side] = state["off"][side]

        scope = state["scope"]
        targets = []   # (where, view)
        if scope == "view":
            targets.append((active.Name, active))
        elif scope == "sel":
            targets = list(sel)
        elif scope == "sheet":
            for v in sheet_views(active):
                if is_level_view(v):
                    targets.append((u"{}  |  {}".format(active.SheetNumber, v.Name), v))
            if not targets:
                return fail(u"This sheet has no section or elevation views.")
        else:
            targets = [(lr["row"]["name"], lr["row"]["view"]) for lr in list_rows
                       if lr["cb"].IsChecked]
            if not targets:
                return fail(u"Pick at least one view.")

        result.update({
            "ok": True, "scope": scope, "targets": targets,
            "do_heads": do_h, "do_align": do_a,
            "heads": dict((k, bool(tgl_side[k].IsChecked)) for k in SIDES),
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
def show_result(res, updated, touched, processed, dependents, report):
    actions = []
    if res["do_heads"]:
        actions.append(u"level heads")
    if res["do_align"]:
        actions.append(u"ends aligned to the crop (or the outermost grids when uncropped)")
    td = TaskDialog(TITLE)
    td.MainInstruction = u"{} levels updated in {} of {} views".format(
        updated, touched, processed)
    lines = [u"Actions: {}.".format(u" + ".join(actions)),
             u"Only the views' 2D extents changed; every level's 3D extent was "
             u"checked and left as it was."]
    if dependents:
        lines.append(u"{} dependent views: Revit keeps their level extents in step "
                     u"with their primary views.".format(dependents))
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
    rows = collect_views()
    if not rows:
        forms.alert(u"This project has no section or elevation views.", title=TITLE)
        return
    res = show_ui(active, active_is_sheet, rows, selected_views())
    if not res["ok"]:
        return

    cfg.set_option("do_heads", 1.0 if res["do_heads"] else 0.0)
    cfg.set_option("do_align", 1.0 if res["do_align"] else 0.0)
    cfg.set_option("link_offsets", 1.0 if res["link"] else 0.0)
    if res["scope"] != "sel":   # a selection is one-off, never the default
        cfg.set_option("scope", res["scope"])
    for s in SIDES:
        cfg.set_option("head_" + s, 1.0 if res["heads"][s] else 0.0)
        cfg.set_option("off_" + s, res["off_mm"][s])
    script.save_config()

    report = []
    seen = set()
    updated, touched, processed, dependents = 0, 0, 0, 0

    t = Transaction(doc, "Align Level Heads")
    t.Start()
    try:
        for where, view in res["targets"]:
            key = id_val(view.Id)
            if key in seen:
                continue
            seen.add(key)
            iss = view_issue(view)
            if iss is not None:
                continue
            opts = {"do_heads": res["do_heads"], "do_align": res["do_align"],
                    "heads": res["heads"],
                    "off": dict((s, res["off_mm"][s] * MM) for s in SIDES)}
            processed += 1
            if view.GetPrimaryViewId() != ElementId.InvalidElementId:
                dependents += 1
            n = process_view(view, where, opts, report)
            updated += n
            if n:
                touched += 1
        t.Commit()
    except Exception as ex:
        t.RollBack()
        forms.alert(u"Failed - nothing changed.\n\n{}".format(ex), title=TITLE)
        return

    show_result(res, updated, touched, processed, dependents, report)


main()

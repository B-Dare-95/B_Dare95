# -*- coding: utf-8 -*-
__doc__ = """__________________________________________________
Description:

Switches grids and levels from 3D extents to 2D extents in every non-3D view of the project, the same as clicking the 3D / 2D label at each end.
After this, moving a grid or level head in a view changes that view only, never the 3D extent.
Nothing moves when you run it: each 2D extent starts exactly where the 3D one was.
3D views, sheets, schedules, legends and drafting views are not touched.
__________________________________________________
How-to:

-> Click on the button
-> The tool scans the project and lists every view with grid or level ends still on 3D
-> Untick the views or view types you want to leave, and choose Grids and / or Levels
-> Click Apply
-> A summary shows how many ends were switched and anything that was skipped
__________________________________________________
Author: Mohamed Bedair"""

import clr
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from System import EventHandler
from System.Windows import FontWeights, RoutedEventHandler, TextAlignment, TextTrimming, Thickness, \
    VerticalAlignment, Visibility
from System.Windows.Markup import XamlReader
from System.Windows.Controls import Canvas, CheckBox, Orientation, StackPanel, TextBlock, \
    TextChangedEventHandler
from System.Windows.Controls.Primitives import ToggleButton
from System.Windows.Media import ColorConverter, DoubleCollection, SolidColorBrush
from System.Windows.Shapes import Ellipse, Line as WLine
from System.Windows.Threading import Dispatcher, DispatcherFrame
from System.Windows.Interop import WindowInteropHelper

from Autodesk.Revit.DB import (DatumEnds, DatumExtentType, FilteredElementCollector, Grid,
                               Level, Transaction, View, ViewType)
from Autodesk.Revit.UI import TaskDialog, TaskDialogCommonButtons

from pyrevit import forms, revit, script

doc = revit.doc
cfg = script.get_config()

TITLE = "2D Extents"
ENDS = (DatumEnds.End0, DatumEnds.End1)
VS = DatumExtentType.ViewSpecific
MODEL = DatumExtentType.Model
MAX_LISTED = 30

# (key, ViewType, label) in list order
VIEW_KINDS = [
    ("floor", ViewType.FloorPlan, u"Floor plans"),
    ("ceiling", ViewType.CeilingPlan, u"Ceiling plans"),
    ("struct", ViewType.EngineeringPlan, u"Structural plans"),
    ("area", ViewType.AreaPlan, u"Area plans"),
    ("section", ViewType.Section, u"Sections"),
    ("elevation", ViewType.Elevation, u"Elevations"),
    ("detail", ViewType.Detail, u"Detail views"),
]
KIND_BY_TYPE = dict((vt, (key, label)) for key, vt, label in VIEW_KINDS)


# =========================================================================
#  Scan
# =========================================================================
def model_ends(datum, view):
    """The ends of the datum still on 3D extents in this view."""
    out = []
    for end in ENDS:
        try:
            if datum.GetDatumExtentTypeInView(end, view) == MODEL:
                out.append(end)
        except Exception:
            pass                        # not shown in this view
    return out


def scan_view(view):
    """{'grids': [(datum, [ends])], 'levels': [...]} for one view."""
    found = {"grids": [], "levels": []}
    for key, cls in (("grids", Grid), ("levels", Level)):
        try:
            datums = FilteredElementCollector(doc, view.Id).OfClass(cls)
        except Exception:
            continue
        for d in datums:
            ends = model_ends(d, view)
            if ends:
                found[key].append((d, ends))
    return found


def candidate_views():
    out = []
    for v in FilteredElementCollector(doc).OfClass(View):
        if v.IsTemplate or v.ViewType not in KIND_BY_TYPE:
            continue
        out.append(v)
    order = dict((vt, i) for i, (_, vt, _) in enumerate(VIEW_KINDS))
    out.sort(key=lambda v: (order[v.ViewType], v.Name.lower()))
    return out


def scan_project():
    views = candidate_views()
    rows, clean = [], 0
    with forms.ProgressBar(title=u"Scanning views ({value} of {max_value})") as pb:
        for i, v in enumerate(views):
            found = scan_view(v)
            g_ends = sum(len(e) for _, e in found["grids"])
            l_ends = sum(len(e) for _, e in found["levels"])
            if g_ends or l_ends:
                key, label = KIND_BY_TYPE[v.ViewType]
                rows.append({"view": v, "kind": key, "label": label, "found": found,
                             "g": g_ends, "l": l_ends, "name": v.Name})
            else:
                clean += 1
            pb.update_progress(i + 1, len(views))
    return rows, clean, len(views)


# =========================================================================
#  Window
# =========================================================================
XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="2D Extents" SizeToContent="WidthAndHeight"
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
    <Style x:Key="Tgl" TargetType="ToggleButton">
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Height" Value="26"/>
      <Setter Property="Padding" Value="8,0"/>
      <Setter Property="Margin" Value="0,0,4,4"/>
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
      <Setter Property="Height" Value="28"/>
      <Setter Property="Padding" Value="6,0"/>
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
      <Setter Property="Margin" Value="0,0,0,2"/>
    </Style>
    <Style x:Key="Sub" TargetType="TextBlock">
      <Setter Property="Foreground" Value="#A8A8A8"/>
      <Setter Property="TextWrapping" Value="Wrap"/>
    </Style>
    <Style x:Key="Card" TargetType="Border">
      <Setter Property="Background" Value="#262626"/>
      <Setter Property="CornerRadius" Value="8"/>
      <Setter Property="Padding" Value="12"/>
    </Style>
  </Window.Resources>

  <StackPanel Margin="12">
    <TextBlock Text="2D Extents" Foreground="#F4F4F4" FontSize="20" FontWeight="Bold"/>
    <TextBlock Style="{StaticResource Sub}" Margin="0,2,0,12"
               Text="Switch grid and level ends from 3D to 2D extents in every non-3D view. Nothing moves."/>
    <Grid>
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="480"/>
        <ColumnDefinition Width="12"/>
        <ColumnDefinition Width="290"/>
      </Grid.ColumnDefinitions>

      <!-- Views -->
      <Border Grid.Column="0" Style="{StaticResource Card}">
        <StackPanel>
          <TextBlock Text="VIEWS" Foreground="#F1C21B" FontSize="11" FontWeight="Bold" Margin="0,0,0,8"/>
          <WrapPanel x:Name="pnlKinds"/>
          <Grid Margin="0,6,0,0">
            <TextBox x:Name="txtSearch"/>
            <TextBlock x:Name="txtHint" Text="Search views" Foreground="#6F6F6F"
                       Margin="9,0,0,0" VerticalAlignment="Center" IsHitTestVisible="False"/>
          </Grid>
          <DockPanel Margin="0,6,0,4">
            <StackPanel DockPanel.Dock="Right" Orientation="Horizontal">
              <Button x:Name="btnAll" Content="All" Style="{StaticResource Btn}" Height="24" Margin="0,0,4,0"/>
              <Button x:Name="btnNone" Content="None" Style="{StaticResource Btn}" Height="24"/>
            </StackPanel>
            <TextBlock x:Name="txtCount" Style="{StaticResource Sub}" VerticalAlignment="Center"/>
          </DockPanel>
          <Border Background="#161616" CornerRadius="6" Height="360">
            <ScrollViewer VerticalScrollBarVisibility="Auto">
              <StackPanel x:Name="pnlList" Margin="4"/>
            </ScrollViewer>
          </Border>
          <TextBlock x:Name="txtClean" Style="{StaticResource Sub}" FontSize="11" Margin="0,8,0,0"/>
        </StackPanel>
      </Border>

      <!-- Datums -->
      <StackPanel Grid.Column="2">
        <Border Style="{StaticResource Card}" Margin="0,0,0,10">
          <StackPanel>
            <TextBlock Text="SWITCH" Foreground="#F1C21B" FontSize="11" FontWeight="Bold" Margin="0,0,0,8"/>
            <CheckBox x:Name="chkGrids" Style="{StaticResource Head}" Content="Grids"/>
            <TextBlock x:Name="txtGrids" Style="{StaticResource Sub}" FontSize="11" Margin="22,0,0,10"/>
            <CheckBox x:Name="chkLevels" Style="{StaticResource Head}" Content="Levels"/>
            <TextBlock x:Name="txtLevels" Style="{StaticResource Sub}" FontSize="11" Margin="22,0,0,0"/>
          </StackPanel>
        </Border>
        <Border Style="{StaticResource Card}">
          <StackPanel>
            <TextBlock Text="WHAT CHANGES" Foreground="#F1C21B" FontSize="11" FontWeight="Bold" Margin="0,0,0,8"/>
            <Border Background="#161616" CornerRadius="6" Padding="2" HorizontalAlignment="Left">
              <Canvas x:Name="cvPreview" Width="262" Height="120" ClipToBounds="True"/>
            </Border>
            <TextBlock Style="{StaticResource Sub}" FontSize="11" Margin="0,8,0,0"
                       Text="Each end keeps its place. From now on, dragging a grid or level head in a view changes that view only, and the 3D extent stays put."/>
          </StackPanel>
        </Border>
      </StackPanel>
    </Grid>

    <DockPanel Margin="0,12,0,0">
      <StackPanel DockPanel.Dock="Right" Orientation="Horizontal">
        <Button x:Name="btnCancel" Content="Cancel" Style="{StaticResource Btn}" Width="84" Margin="0,0,8,0"/>
        <Button x:Name="btnApply" Content="Apply" Style="{StaticResource AccentBtn}" Width="84"/>
      </StackPanel>
      <TextBlock x:Name="txtMsg" Foreground="#A8A8A8" VerticalAlignment="Center" TextWrapping="Wrap"/>
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


def cv_text(cv, x, y, text, color, size=10, bold=False, width=None):
    tb = TextBlock()
    tb.Text = text
    tb.FontSize = size
    tb.Foreground = brush(color)
    if bold:
        tb.FontWeight = FontWeights.Bold
    if width:
        tb.Width = width
        tb.TextAlignment = TextAlignment.Center
    Canvas.SetLeft(tb, x)
    Canvas.SetTop(tb, y)
    cv.Children.Add(tb)


def draw_preview(cv):
    """A grid end before (3D) and after (2D), like the label Revit shows."""
    cv.Children.Clear()
    for x0, label, color in ((14.0, u"3D", "#FA4D56"), (150.0, u"2D", "#F1C21B")):
        cx = x0 + 50.0
        e = Ellipse()
        e.Width = e.Height = 26
        e.Fill = brush("#161616")
        e.Stroke = brush("#F4F4F4")
        e.StrokeThickness = 1.2
        Canvas.SetLeft(e, cx - 13)
        Canvas.SetTop(e, 12)
        cv.Children.Add(e)
        cv_text(cv, cx - 13, 17, u"A", "#F4F4F4", 11, width=26)
        cv_line(cv, cx, 38, cx, 112, "#A8A8A8", 1.2, "10 3 2 3")
        cv_line(cv, cx - 30, 44, cx + 30, 44, "#6F6F6F", 1, "3 3")
        cv_text(cv, cx + 8, 48, label, color, 11)
    cv_line(cv, 118, 70, 140, 70, "#F4F4F4", 1.5)
    cv_line(cv, 134, 65, 140, 70, "#F4F4F4", 1.5)
    cv_line(cv, 134, 75, 140, 70, "#F4F4F4", 1.5)


def opt_bool(name, default):
    try:
        return float(cfg.get_option(name, 1.0 if default else 0.0)) > 0.5
    except Exception:
        return default


def show_ui(rows, clean, total):
    w = XamlReader.Parse(XAML)
    f = w.FindName
    result = {"ok": False}

    chk_g, chk_l = f("chkGrids"), f("chkLevels")
    pnl_list, pnl_kinds = f("pnlList"), f("pnlKinds")
    txt_search, txt_hint, txt_count, txt_msg = f("txtSearch"), f("txtHint"), f("txtCount"), f("txtMsg")
    btn_apply = f("btnApply")

    chk_g.IsChecked = opt_bool("grids", True)
    chk_l.IsChecked = opt_bool("levels", True)
    f("txtClean").Text = u"{0} of {1} views already have every grid and level end on 2D, so they " \
                         u"aren\u2019t listed.".format(clean, total)
    draw_preview(f("cvPreview"))

    # ---- view kind toggles
    kinds = {}
    for key, vt, label in VIEW_KINDS:
        n = len([r for r in rows if r["kind"] == key])
        if not n:
            continue
        t = ToggleButton()
        t.Style = w.FindResource("Tgl")
        t.Content = u"{0} ({1})".format(label, n)
        t.IsChecked = opt_bool("kind_" + key, True)
        pnl_kinds.Children.Add(t)
        kinds[key] = t

    # ---- rows
    for r in rows:
        cb = CheckBox()
        cb.IsChecked = True
        cb.Margin = Thickness(2, 2, 2, 2)
        sp = StackPanel()
        sp.Orientation = Orientation.Horizontal
        t1 = TextBlock()
        t1.Text = r["name"]
        t1.Width = 250
        t1.Foreground = brush("#F4F4F4")
        t1.TextTrimming = TextTrimming.CharacterEllipsis
        t1.ToolTip = r["name"]
        t2 = TextBlock()
        t2.Text = r["label"]
        t2.Width = 100
        t2.Foreground = brush("#A8A8A8")
        t2.FontSize = 11
        t2.VerticalAlignment = VerticalAlignment.Center
        t3 = TextBlock()
        t3.Foreground = brush("#6F6F6F")
        t3.FontSize = 11
        t3.VerticalAlignment = VerticalAlignment.Center
        for t in (t1, t2, t3):
            sp.Children.Add(t)
        cb.Content = sp
        pnl_list.Children.Add(cb)
        r["cb"], r["t3"], r["key"] = cb, t3, r["name"].lower()

    def ends_for(r):
        return (r["g"] if chk_g.IsChecked else 0) + (r["l"] if chk_l.IsChecked else 0)

    def processed():
        return [r for r in rows if r["cb"].IsChecked and kinds[r["kind"]].IsChecked and ends_for(r)]

    def refresh(*args):
        q = txt_search.Text.strip().lower()
        txt_hint.Opacity = 0.0 if txt_search.Text else 1.0
        shown = 0
        for r in rows:
            n = ends_for(r)
            r["t3"].Text = u"{0} ends on 3D".format(n) if n != 1 else u"1 end on 3D"
            visible = kinds[r["kind"]].IsChecked and q in r["key"]
            r["cb"].Visibility = Visibility.Visible if visible else Visibility.Collapsed
            r["cb"].Opacity = 1.0 if n else 0.4
            if visible:
                shown += 1
        todo = processed()
        n_ends = sum(ends_for(r) for r in todo)
        txt_count.Text = u"{0} of {1} views ticked".format(
            len([r for r in rows if r["cb"].IsChecked and kinds[r["kind"]].IsChecked]),
            len([r for r in rows if kinds[r["kind"]].IsChecked]))
        f("txtGrids").Text = u"{0} ends on 3D in {1} views".format(
            sum(r["g"] for r in rows), len([r for r in rows if r["g"]]))
        f("txtLevels").Text = u"{0} ends on 3D in {1} views".format(
            sum(r["l"] for r in rows), len([r for r in rows if r["l"]]))
        if not (chk_g.IsChecked or chk_l.IsChecked):
            txt_msg.Text = u"Tick Grids, Levels or both."
        elif not todo:
            txt_msg.Text = u"Nothing to switch with these choices."
        else:
            txt_msg.Text = u"Will switch {0} ends in {1} views.".format(n_ends, len(todo))
        btn_apply.IsEnabled = bool(todo) and bool(chk_g.IsChecked or chk_l.IsChecked)

    for r in rows:
        r["cb"].Checked += RoutedEventHandler(refresh)
        r["cb"].Unchecked += RoutedEventHandler(refresh)
    for t in kinds.values():
        t.Click += RoutedEventHandler(refresh)
    chk_g.Click += RoutedEventHandler(refresh)
    chk_l.Click += RoutedEventHandler(refresh)
    txt_search.TextChanged += TextChangedEventHandler(refresh)

    def set_shown(value):
        for r in rows:
            if r["cb"].Visibility == Visibility.Visible:
                r["cb"].IsChecked = value

    f("btnAll").Click += RoutedEventHandler(lambda s, e: set_shown(True))
    f("btnNone").Click += RoutedEventHandler(lambda s, e: set_shown(False))
    refresh()

    def on_apply(s, e):
        todo = processed()
        if not todo:
            return
        result.update({"ok": True, "rows": todo, "grids": bool(chk_g.IsChecked),
                       "levels": bool(chk_l.IsChecked),
                       "kinds": dict((k, bool(t.IsChecked)) for k, t in kinds.items())})
        w.Close()

    btn_apply.Click += RoutedEventHandler(on_apply)
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
    cfg.set_option("grids", 1.0 if res["grids"] else 0.0)
    cfg.set_option("levels", 1.0 if res["levels"] else 0.0)
    for k, on in res["kinds"].items():
        cfg.set_option("kind_" + k, 1.0 if on else 0.0)
    script.save_config()


def switch_view(r, res, counts, report):
    view = r["view"]
    changed_here = False
    for key, label, on in (("grids", u"Grid", res["grids"]), ("levels", u"Level", res["levels"])):
        if not on:
            continue
        for datum, ends in r["found"][key]:
            for end in ends:
                try:
                    if datum.GetDatumExtentTypeInView(end, view) != MODEL:
                        continue
                    datum.SetDatumExtentType(end, view, VS)
                    counts[key] += 1
                    changed_here = True
                except Exception as ex:
                    report.append(u"{0}  |  {1} {2}  -  {3}".format(view.Name, label, datum.Name, ex))
    if changed_here:
        counts["views"] += 1


def show_result(res, counts, report):
    lines = []
    if res["grids"]:
        lines.append(u"Grids: {0} ends switched to 2D.".format(counts["grids"]))
    if res["levels"]:
        lines.append(u"Levels: {0} ends switched to 2D.".format(counts["levels"]))
    lines.append(u"Views changed: {0}.".format(counts["views"]))
    td = TaskDialog(TITLE)
    td.MainInstruction = u"Switched to 2D extents" if (counts["grids"] or counts["levels"]) \
        else u"Nothing needed changing"
    if report:
        lines.append(u"{0} ends couldn\u2019t be switched - expand details for the list.".format(len(report)))
        shown = report[:MAX_LISTED]
        if len(report) > MAX_LISTED:
            shown.append(u"... and {0} more".format(len(report) - MAX_LISTED))
        td.ExpandedContent = u"\n".join(shown)
    td.MainContent = u"\n".join(lines)
    td.CommonButtons = TaskDialogCommonButtons.Ok
    td.Show()


def main():
    rows, clean, total = scan_project()
    if not rows:
        forms.alert(u"Every grid and level end is already on 2D extents in all {0} non-3D views. "
                    u"Nothing to do.".format(total), title=TITLE)
        return
    res = show_ui(rows, clean, total)
    if not res["ok"]:
        return
    save_settings(res)

    counts = {"grids": 0, "levels": 0, "views": 0}
    report = []
    todo = res["rows"]
    t = Transaction(doc, TITLE)
    t.Start()
    try:
        with forms.ProgressBar(title=u"Switching views ({value} of {max_value})") as pb:
            for i, r in enumerate(todo):
                switch_view(r, res, counts, report)
                pb.update_progress(i + 1, len(todo))
        t.Commit()
    except Exception as ex:
        t.RollBack()
        forms.alert(u"Failed - nothing changed.\n\n{0}".format(ex), title=TITLE)
        return
    show_result(res, counts, report)


main()
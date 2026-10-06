# -*- coding: utf-8 -*-
__title__ = "Viewport\nTitle Aligner"
__doc__ = ("Places viewport titles under the bottom-left corner of their "
           "viewport and fits the title line to the text length plus an "
           "offset. Works on selected viewports, the active sheet, or "
           "picked sheets. Revit 2022+.")

import clr
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from System import EventHandler
from System.Windows import RoutedEventHandler, Visibility
from System.Windows.Markup import XamlReader
from System.Windows.Controls import CheckBox, TextChangedEventHandler
from System.Windows.Threading import Dispatcher, DispatcherFrame

from Autodesk.Revit.DB import (Transaction, XYZ, Viewport, ViewSheet,
                               FilteredElementCollector, ViewportRotation)
from Autodesk.Revit.UI import TaskDialog, TaskDialogCommonButtons
from pyrevit import script, forms

uidoc = __revit__.ActiveUIDocument
doc = uidoc.Document

MM = 1.0 / 304.8                       # paper mm -> feet
SHORT_LINE = 1.0 * MM                  # probe length, shorter than any title text
ROT_NONE = getattr(ViewportRotation, "None")   # "None" is a keyword in IronPython

cfg = script.get_config()


def cfg_float(name, default):
    try:
        return float(cfg.get_option(name, default))
    except Exception:
        return default


# --------------------------------------------------------------------------
# Scope collection
# --------------------------------------------------------------------------
def selected_viewports():
    out = []
    for eid in uidoc.Selection.GetElementIds():
        el = doc.GetElement(eid)
        if isinstance(el, Viewport):
            out.append(el)
    return out


def viewports_on(sheets):
    out = []
    for sh in sheets:
        for vid in sh.GetAllViewports():
            vp = doc.GetElement(vid)
            if vp is not None:
                out.append(vp)
    return out


def all_sheets():
    sheets = [s for s in FilteredElementCollector(doc).OfClass(ViewSheet)
              if not s.IsPlaceholder]
    return sorted(sheets, key=lambda s: s.SheetNumber)


# --------------------------------------------------------------------------
# Core logic
# --------------------------------------------------------------------------
def outline_ok(o):
    if o is None:
        return False
    try:
        if o.IsEmpty:
            return False
    except Exception:
        pass
    return (o.MaximumPoint.X - o.MinimumPoint.X) > 1e-9


def restore(w):
    try:
        w["vp"].LabelLineLength = w["len0"]
        w["vp"].LabelOffset = w["off0"]
    except Exception:
        pass


def align_titles(vps, h_off, v_gap, extra, do_align, do_fit, report):
    """Batch passes so the document regenerates at most 4 times in total,
    not 4 times per viewport.

    Fit line (do_fit):
      Pass A  shrink line            -> outline right edge = text right edge
      Pass B  stretch line past text -> outline right edge = line end,
                                        so line start = right edge - length
      Pass C  set final length       = text right - line start + extra
    Align (do_align):
      Pass D  move label so the symbol's top-left sits at
              (box left + h_off, box bottom - v_gap)
    """
    work = []
    for vp in vps:
        if vp.Rotation != ROT_NONE:
            report.append((vp, "Skipped - viewport is rotated"))
            continue
        work.append({"vp": vp,
                     "len0": vp.LabelLineLength,
                     "off0": vp.LabelOffset})

    if do_fit:
        work = fit_lines(work, extra, report)

    if not do_align:
        return len(work)

    if not do_fit:
        # Hidden titles were not filtered by the fit passes - check here
        alive = []
        for w in work:
            if outline_ok(w["vp"].GetLabelOutline()):
                alive.append(w)
            else:
                report.append((w["vp"], "Skipped - title is not shown"))
        work = alive

    return move_labels(work, h_off, v_gap, report)


def fit_lines(work, extra, report):
    # Pass A
    alive = []
    for w in work:
        try:
            w["vp"].LabelLineLength = SHORT_LINE
            alive.append(w)
        except Exception as ex:
            report.append((w["vp"], u"Skipped - {}".format(ex)))
    work = alive
    doc.Regenerate()

    # Pass B
    alive = []
    for w in work:
        o = w["vp"].GetLabelOutline()
        if not outline_ok(o):
            restore(w)
            report.append((w["vp"], "Skipped - title is not shown"))
            continue
        w["text_right"] = o.MaximumPoint.X
        w["long"] = (o.MaximumPoint.X - o.MinimumPoint.X) * 3.0 + 0.5
        try:
            w["vp"].LabelLineLength = w["long"]
            alive.append(w)
        except Exception as ex:
            restore(w)
            report.append((w["vp"], u"Skipped - {}".format(ex)))
    work = alive
    doc.Regenerate()

    # Pass C
    alive = []
    for w in work:
        o = w["vp"].GetLabelOutline()
        line_start = o.MaximumPoint.X - w["long"]
        length = max(w["text_right"] - line_start + extra, SHORT_LINE)
        try:
            w["vp"].LabelLineLength = length
            w["length"] = length
            alive.append(w)
        except Exception as ex:
            restore(w)
            report.append((w["vp"], u"Skipped - {}".format(ex)))
    doc.Regenerate()
    return alive


def move_labels(work, h_off, v_gap, report):
    # Pass D
    done = 0
    for w in work:
        vp = w["vp"]
        o = vp.GetLabelOutline()
        box = vp.GetBoxOutline()
        dx = (box.MinimumPoint.X + h_off) - o.MinimumPoint.X
        dy = (box.MinimumPoint.Y - v_gap) - o.MaximumPoint.Y
        off = vp.LabelOffset
        try:
            vp.LabelOffset = XYZ(off.X + dx, off.Y + dy, 0.0)
            done += 1
        except Exception as ex:
            restore(w)
            report.append((vp, u"Skipped - {}".format(ex)))
    return done


# --------------------------------------------------------------------------
# UI  (IBM Carbon)
# --------------------------------------------------------------------------
XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Viewport Title Aligner" Width="470" Height="640"
        MinWidth="420" MinHeight="520"
        WindowStartupLocation="CenterScreen" Background="#161616"
        FontFamily="Segoe UI" FontSize="12" ResizeMode="CanResizeWithGrip">
  <Window.Resources>
    <Style x:Key="Toggle" TargetType="ToggleButton">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="Margin" Value="0,0,6,0"/>
      <Setter Property="Padding" Value="12,6"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ToggleButton">
            <Border x:Name="Bd" Background="{TemplateBinding Background}"
                    CornerRadius="4" Padding="{TemplateBinding Padding}">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsChecked" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#F1C21B"/>
                <Setter Property="Foreground" Value="#161616"/>
              </Trigger>
              <Trigger Property="IsEnabled" Value="False">
                <Setter Property="Opacity" Value="0.35"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style x:Key="Btn" TargetType="Button">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="Padding" Value="14,6"/>
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
    <Style x:Key="Accent" TargetType="Button" BasedOn="{StaticResource Btn}">
      <Setter Property="Background" Value="#F1C21B"/>
      <Setter Property="Foreground" Value="#161616"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
    </Style>
    <Style TargetType="TextBox">
      <Setter Property="Background" Value="#262626"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="BorderBrush" Value="#525252"/>
      <Setter Property="CaretBrush" Value="#F4F4F4"/>
      <Setter Property="Padding" Value="6,4"/>
    </Style>
    <Style TargetType="TextBlock">
      <Setter Property="Foreground" Value="#F4F4F4"/>
    </Style>
    <Style TargetType="CheckBox">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Margin" Value="6,3"/>
    </Style>
  </Window.Resources>

  <Grid Margin="16">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <TextBlock Grid.Row="0" Text="SCOPE" Foreground="#A8A8A8"
               FontWeight="SemiBold" Margin="0,0,0,6"/>
    <StackPanel Grid.Row="1" Orientation="Horizontal" Margin="0,0,0,10">
      <ToggleButton x:Name="tgSel" Style="{StaticResource Toggle}" Content="Selection"/>
      <ToggleButton x:Name="tgActive" Style="{StaticResource Toggle}" Content="Active Sheet"/>
      <ToggleButton x:Name="tgSheets" Style="{StaticResource Toggle}" Content="Pick Sheets"/>
    </StackPanel>

    <Border Grid.Row="2" x:Name="pnlSheets" Background="#262626"
            CornerRadius="4" Padding="8" Margin="0,0,0,12">
      <Grid>
        <Grid.RowDefinitions>
          <RowDefinition Height="Auto"/>
          <RowDefinition Height="*"/>
          <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>
        <TextBox x:Name="txtSearch" Grid.Row="0" Background="#393939"
                 Margin="0,0,0,6" ToolTip="Filter sheets by number or name"/>
        <ScrollViewer Grid.Row="1" VerticalScrollBarVisibility="Auto">
          <StackPanel x:Name="lstSheets"/>
        </ScrollViewer>
        <StackPanel Grid.Row="2" Orientation="Horizontal" Margin="0,6,0,0">
          <Button x:Name="btnAll" Style="{StaticResource Btn}" Content="Check visible" Margin="0,0,6,0"/>
          <Button x:Name="btnNone" Style="{StaticResource Btn}" Content="Uncheck visible"/>
        </StackPanel>
      </Grid>
    </Border>

    <Border Grid.Row="3" Background="#262626" CornerRadius="4" Padding="10" Margin="0,0,0,10">
      <Grid>
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="*"/>
          <ColumnDefinition Width="80"/>
          <ColumnDefinition Width="34"/>
        </Grid.ColumnDefinitions>
        <Grid.RowDefinitions>
          <RowDefinition Height="Auto"/>
          <RowDefinition Height="Auto"/>
          <RowDefinition Height="Auto"/>
          <RowDefinition Height="Auto"/>
          <RowDefinition Height="Auto"/>
          <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>
        <TextBlock Grid.Row="0" Grid.ColumnSpan="3" Text="LAYOUT (PAPER SPACE)"
                   Foreground="#A8A8A8" FontWeight="SemiBold" Margin="0,0,0,8"/>

        <CheckBox x:Name="chkAlign" Grid.Row="1" Grid.ColumnSpan="3" Margin="0,2,0,4"
                  FontWeight="SemiBold" Content="Align title under bottom-left corner"/>
        <StackPanel x:Name="pnlAlign" Grid.Row="2" Grid.ColumnSpan="3" Margin="20,0,0,8">
          <Grid>
            <Grid.ColumnDefinitions>
              <ColumnDefinition Width="*"/>
              <ColumnDefinition Width="80"/>
              <ColumnDefinition Width="34"/>
            </Grid.ColumnDefinitions>
            <Grid.RowDefinitions>
              <RowDefinition Height="Auto"/>
              <RowDefinition Height="Auto"/>
            </Grid.RowDefinitions>
            <TextBlock Grid.Row="0" Text="Shift right from viewport left edge" VerticalAlignment="Center"/>
            <TextBox x:Name="txtH" Grid.Row="0" Grid.Column="1" Margin="0,3"/>
            <TextBlock Grid.Row="0" Grid.Column="2" Text="mm" Foreground="#A8A8A8"
                       VerticalAlignment="Center" Margin="6,0,0,0"/>
            <TextBlock Grid.Row="1" Text="Gap below viewport" VerticalAlignment="Center"/>
            <TextBox x:Name="txtV" Grid.Row="1" Grid.Column="1" Margin="0,3"/>
            <TextBlock Grid.Row="1" Grid.Column="2" Text="mm" Foreground="#A8A8A8"
                       VerticalAlignment="Center" Margin="6,0,0,0"/>
          </Grid>
        </StackPanel>

        <CheckBox x:Name="chkFit" Grid.Row="3" Grid.ColumnSpan="3" Margin="0,2,0,4"
                  FontWeight="SemiBold" Content="Fit title line to text length"/>
        <StackPanel x:Name="pnlFit" Grid.Row="4" Grid.ColumnSpan="3" Margin="20,0,0,0">
          <Grid>
            <Grid.ColumnDefinitions>
              <ColumnDefinition Width="*"/>
              <ColumnDefinition Width="80"/>
              <ColumnDefinition Width="34"/>
            </Grid.ColumnDefinitions>
            <TextBlock Text="Line extends past text by" VerticalAlignment="Center"/>
            <TextBox x:Name="txtX" Grid.Column="1" Margin="0,3"/>
            <TextBlock Grid.Column="2" Text="mm" Foreground="#A8A8A8"
                       VerticalAlignment="Center" Margin="6,0,0,0"/>
          </Grid>
        </StackPanel>
      </Grid>
    </Border>

    <TextBlock Grid.Row="4" Foreground="#A8A8A8" TextWrapping="Wrap" Margin="0,0,0,12"
               Text="Rotated viewports and hidden titles are skipped and listed in the report."/>

    <StackPanel Grid.Row="5" Orientation="Horizontal" HorizontalAlignment="Right">
      <Button x:Name="btnCancel" Style="{StaticResource Btn}" Content="Cancel" Margin="0,0,8,0"/>
      <Button x:Name="btnApply" Style="{StaticResource Accent}" Content="Apply"/>
    </StackPanel>
  </Grid>
</Window>
"""


def show_ui(sel_vps, active_is_sheet, sheets):
    w = XamlReader.Parse(XAML)
    tg_sel = w.FindName("tgSel")
    tg_active = w.FindName("tgActive")
    tg_sheets = w.FindName("tgSheets")
    pnl_sheets = w.FindName("pnlSheets")
    txt_search = w.FindName("txtSearch")
    lst = w.FindName("lstSheets")
    txt_h = w.FindName("txtH")
    txt_v = w.FindName("txtV")
    txt_x = w.FindName("txtX")

    result = {"ok": False}
    frame = DispatcherFrame()
    toggles = [tg_sel, tg_active, tg_sheets]

    tg_sel.Content = "Selection ({})".format(len(sel_vps))
    tg_sel.IsEnabled = len(sel_vps) > 0
    tg_active.IsEnabled = active_is_sheet

    txt_h.Text = str(cfg_float("h_off_mm", 0.0))
    txt_v.Text = str(cfg_float("v_gap_mm", 2.0))
    txt_x.Text = str(cfg_float("extra_mm", 3.0))

    chk_align = w.FindName("chkAlign")
    chk_fit = w.FindName("chkFit")
    pnl_align = w.FindName("pnlAlign")
    pnl_fit = w.FindName("pnlFit")
    chk_align.IsChecked = cfg_float("do_align", 1.0) > 0.5
    chk_fit.IsChecked = cfg_float("do_fit", 1.0) > 0.5

    def sync_options(s=None, e=None):
        a = bool(chk_align.IsChecked)
        f = bool(chk_fit.IsChecked)
        pnl_align.IsEnabled = a
        pnl_align.Opacity = 1.0 if a else 0.4
        pnl_fit.IsEnabled = f
        pnl_fit.Opacity = 1.0 if f else 0.4
        btn_apply.IsEnabled = a or f
        btn_apply.Opacity = 1.0 if (a or f) else 0.4

    btn_apply = w.FindName("btnApply")
    for chk in (chk_align, chk_fit):
        chk.Click += RoutedEventHandler(sync_options)
    sync_options()

    boxes = []
    for sh in sheets:
        cb = CheckBox()
        cb.Content = u"{} - {}".format(sh.SheetNumber, sh.Name)
        cb.Tag = sh
        lst.Children.Add(cb)
        boxes.append(cb)

    def pick(tg):
        for t in toggles:
            t.IsChecked = (t is tg)
        pnl_sheets.IsEnabled = (tg is tg_sheets)
        pnl_sheets.Opacity = 1.0 if tg is tg_sheets else 0.4

    if tg_sel.IsEnabled:
        pick(tg_sel)
    elif tg_active.IsEnabled:
        pick(tg_active)
    else:
        pick(tg_sheets)

    for t in toggles:
        t.Click += RoutedEventHandler(lambda s, e: pick(s))

    def on_search(s, e):
        q = txt_search.Text.strip().lower()
        for cb in boxes:
            hit = (not q) or (q in cb.Content.lower())
            cb.Visibility = Visibility.Visible if hit else Visibility.Collapsed
    txt_search.TextChanged += TextChangedEventHandler(on_search)

    def set_visible(state):
        for cb in boxes:
            if cb.Visibility == Visibility.Visible:
                cb.IsChecked = state
    w.FindName("btnAll").Click += RoutedEventHandler(lambda s, e: set_visible(True))
    w.FindName("btnNone").Click += RoutedEventHandler(lambda s, e: set_visible(False))

    def parse(tb):
        return float(tb.Text.strip().replace(",", "."))

    def on_apply(s, e):
        do_align = bool(chk_align.IsChecked)
        do_fit = bool(chk_fit.IsChecked)
        if not (do_align or do_fit):
            return
        try:
            h = parse(txt_h) if do_align else 0.0
            v = parse(txt_v) if do_align else 0.0
            x = parse(txt_x) if do_fit else 0.0
        except Exception:
            forms.alert("Offsets must be numbers (mm).")
            return
        if tg_sel.IsChecked:
            vps = sel_vps
        elif tg_active.IsChecked:
            vps = viewports_on([doc.ActiveView])
        else:
            vps = viewports_on([cb.Tag for cb in boxes if cb.IsChecked])
        if not vps:
            forms.alert("No viewports in the chosen scope.")
            return
        result.update({"ok": True, "vps": vps, "h": h, "v": v, "x": x,
                       "do_align": do_align, "do_fit": do_fit})
        w.Close()

    btn_apply.Click += RoutedEventHandler(on_apply)
    w.FindName("btnCancel").Click += RoutedEventHandler(lambda s, e: w.Close())

    def on_closed(s, e):
        frame.Continue = False
    w.Closed += EventHandler(on_closed)

    w.Show()
    Dispatcher.PushFrame(frame)
    return result


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def describe(vp):
    sheet = doc.GetElement(vp.SheetId)
    view = doc.GetElement(vp.ViewId)
    sn = sheet.SheetNumber if sheet else "-"
    vn = view.Name if view else "-"
    return sn, vn


MAX_LISTED = 15


def show_result(done, total, do_align, do_fit, report):
    actions = []
    if do_align:
        actions.append("aligned")
    if do_fit:
        actions.append("line fitted")
    td = TaskDialog("Viewport Title Aligner")
    td.MainInstruction = u"{} of {} viewport titles updated".format(done, total)
    td.MainContent = u"Action: {}.".format(" + ".join(actions))
    if report:
        td.MainContent += u"\n{} skipped - expand details for the list.".format(
            len(report))
        lines = []
        for vp, msg in report[:MAX_LISTED]:
            sn, vn = describe(vp)
            lines.append(u"{}  |  {}  -  {}".format(sn, vn, msg))
        if len(report) > MAX_LISTED:
            lines.append(u"... and {} more".format(len(report) - MAX_LISTED))
        td.ExpandedContent = u"\n".join(lines)
    td.CommonButtons = TaskDialogCommonButtons.Ok
    td.Show()


def main():
    res = show_ui(selected_viewports(),
                  isinstance(doc.ActiveView, ViewSheet),
                  all_sheets())
    if not res["ok"]:
        return

    cfg.set_option("do_align", 1.0 if res["do_align"] else 0.0)
    cfg.set_option("do_fit", 1.0 if res["do_fit"] else 0.0)
    if res["do_align"]:
        cfg.set_option("h_off_mm", res["h"])
        cfg.set_option("v_gap_mm", res["v"])
    if res["do_fit"]:
        cfg.set_option("extra_mm", res["x"])
    script.save_config()

    report = []
    t = Transaction(doc, "Align Viewport Titles")
    t.Start()
    try:
        done = align_titles(res["vps"], res["h"] * MM, res["v"] * MM,
                            res["x"] * MM, res["do_align"], res["do_fit"],
                            report)
        t.Commit()
    except Exception as ex:
        t.RollBack()
        forms.alert(u"Failed - nothing changed.\n\n{}".format(ex))
        return

    show_result(done, len(res["vps"]), res["do_align"], res["do_fit"], report)


main()
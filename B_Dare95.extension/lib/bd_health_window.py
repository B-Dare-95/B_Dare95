# -*- coding: utf-8 -*-
"""One section of the Model Health Check as a Quick Report window.

Same build as the other Quick Reports (Workset Counter, Items on Levels, Parking
Report): a modeless window, an ExternalEvent queue for every Revit call made
after the script has returned, and a pyRevit env var holding the open window so
a second press brings it forward.

Each pushbutton calls ``show_section_report(__revit__, u"<section title>")`` with
one of ``bd_health.SECTIONS``' titles.
"""

import clr
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from System import DateTime, EventHandler, Int64
from System.Collections.Generic import List
from System.Windows import (CornerRadius, FontWeights, HorizontalAlignment, RoutedEventHandler,
                            TextAlignment, TextTrimming, TextWrapping, Thickness, VerticalAlignment, Visibility)
from System.Windows.Controls import (Border, Dock, DockPanel, StackPanel, TextBlock,
                                     TextChangedEventHandler)
from System.Windows.Input import Cursors, Keyboard, ModifierKeys, MouseButtonEventHandler
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Markup import XamlReader
from System.Windows.Media import BrushConverter, FontFamily

from Autodesk.Revit.DB import ElementId
from Autodesk.Revit.UI import ExternalEvent, IExternalEventHandler

from pyrevit import forms, script
from pyrevit.coreutils import envvars

import bd_health as hc

logger = script.get_logger()

# Rows listed under one check; the rest are counted in a last line. Clicking the
# check still selects all of its elements.
MAX_ROWS = 300

# kind -> (pill text, background, foreground)
KIND_PILLS = {
    hc.PASS: (u"Pass", "#0E2A18", "#A7F0BA"),
    hc.FAIL: (u"Fail", "#4A0E12", "#FFB3B8"),
    hc.COUNT: (u"Count", "#393939", "#C6C6C6"),
    hc.LIST: (u"List", "#393939", "#C6C6C6"),
    hc.RESULT: (u"Result", "#0A2350", "#A6C8FF"),
}
ERROR_PILL = (u"Error", "#3A2E06", "#FDDC69")

STATUS_COLORS = {
    "info": ("#262626", "#A8A8A8"),
    "ok":   ("#0E2A18", "#A7F0BA"),
    "warn": ("#3A2E06", "#FDDC69"),
}

HINT = (u"Click a check to select its elements in the model, or its arrow to see the list. "
        u"Ctrl+click adds to the current selection.")

_bc = BrushConverter()


def brush(hex_value):
    return _bc.ConvertFromString(hex_value)


def plural(n, word, word_pl=None):
    return u"{0} {1}".format(hc.number(n), word if n == 1 else (word_pl or word + u"s"))


def element_id(n):
    return ElementId(Int64(n))


# ---------------------------------------------------------------- session state --
# A persistent engine hands each run a fresh script scope. pyRevit's env vars live
# above it: they let a second press find the open window, and they hold the strong
# reference that keeps the ExternalEvent alive while the window is up.
def session_key(title):
    slug = u"".join([c if c.isalnum() else u"_" for c in title.upper()])
    return "BD_HEALTH_{0}_SESSION".format(slug)


def get_session(key):
    try:
        return envvars.get_pyrevit_env_var(key)
    except Exception:
        return None


def set_session(key, value):
    try:
        envvars.set_pyrevit_env_var(key, value)
    except Exception:
        logger.debug("Could not store the health report session.")


class HealthEventHandler(IExternalEventHandler):
    """Runs queued work inside a valid Revit API context. After the script returns,
    a WPF click is a callback with no API context open, so every Revit call
    (selection, zoom, re-run) is queued and run here when Revit is idle. A queue,
    not a single slot: Revit may merge quick Raise() calls."""

    def __init__(self, name):
        self.name = name
        self.queue = []

    def enqueue(self, action):
        self.queue.append(action)

    def Execute(self, uiapp):
        pending, self.queue = self.queue, []
        for action in pending:
            try:
                action()
            except Exception as ex:
                logger.error("{0} error: {1}".format(self.name, ex))
                forms.alert(u"{0} ran into an error:\n\n{1}".format(self.name, ex))

    def GetName(self):
        return self.name


# ------------------------------------------------------------------ the checks --
def run_checks(doc, title):
    """{'title', 'path', 'time', 'items'} for one section, or None when cancelled."""
    bar_title = u"{0}: check {{value}} of {{max_value}}".format(title)
    try:
        bar = forms.ProgressBar(title=bar_title, cancellable=True)
    except Exception:
        bar = None
    if bar is None:
        tree = hc.run_sections(doc, [title])
    else:
        with bar:
            tree = hc.run_sections(doc, [title], bar)
    if tree is None:
        return None
    return {"title": doc.Title, "path": doc.PathName, "items": tree[0][2],
            "time": DateTime.Now.ToString("HH:mm")}


def row_cells(check, row):
    """(left text, right text) for one row of a check's list. 'ID' or 'Count' goes on
    the right; a 'Name' that already reads 'Category : Type : ...' stands alone."""
    cols = check.columns
    right_at = None
    for key in (u"ID", u"Count"):
        if key in cols:
            right_at = cols.index(key)
            break
    cells = [u"{0}".format(v) or u"\u2014" for i, v in enumerate(row) if i != right_at]
    names = [c for i, c in enumerate(cols) if i != right_at]
    if names and names[-1] == u"Name" and u" : " in cells[-1]:
        cells = [cells[-1]]
    shown = []
    for c in cells:
        if c and (not shown or shown[-1] != c):
            shown.append(c)
    right = u"{0}".format(row[right_at]) if right_at is not None else u""
    return u"  ·  ".join(shown) or u"(blank)", right


# --------------------------------------------------------------------------- UI --
XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Model Health" Width="760" Height="780" MinWidth="580" MinHeight="460"
        WindowStartupLocation="CenterScreen" ResizeMode="CanResizeWithGrip"
        Background="#161616" Foreground="#F4F4F4" FontFamily="Segoe UI" FontSize="13">
  <Window.Resources>
    <Style TargetType="Button">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="BorderBrush" Value="#525252"/>
      <Setter Property="Height" Value="30"/>
      <Setter Property="Padding" Value="14,0"/>
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
    <Style TargetType="CheckBox">
      <Setter Property="Foreground" Value="#A8A8A8"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="VerticalAlignment" Value="Center"/>
    </Style>
    <Style x:Key="Row" TargetType="Border">
      <Setter Property="Background" Value="Transparent"/>
      <Setter Property="BorderBrush" Value="#262626"/>
      <Setter Property="BorderThickness" Value="0,0,0,1"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Style.Triggers>
        <Trigger Property="IsMouseOver" Value="True"><Setter Property="Background" Value="#262626"/></Trigger>
      </Style.Triggers>
    </Style>
    <Style x:Key="OpenChip" TargetType="Border">
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="CornerRadius" Value="4"/>
      <Setter Property="Padding" Value="9,1,9,2"/>
      <Setter Property="Margin" Value="10,0,0,0"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="VerticalAlignment" Value="Center"/>
      <Style.Triggers>
        <Trigger Property="IsMouseOver" Value="True"><Setter Property="Background" Value="#525252"/></Trigger>
      </Style.Triggers>
    </Style>
    <Style x:Key="PlainRow" TargetType="Border">
      <Setter Property="Background" Value="Transparent"/>
      <Setter Property="BorderBrush" Value="#262626"/>
      <Setter Property="BorderThickness" Value="0,0,0,1"/>
    </Style>
  </Window.Resources>

  <Grid Margin="14">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <DockPanel Grid.Row="0">
      <Button x:Name="btnRefresh" DockPanel.Dock="Right" Content="Refresh"
              ToolTip="Run these checks again on the active model"/>
      <StackPanel VerticalAlignment="Center">
        <TextBlock x:Name="tbTitle" Text="Health Report" FontSize="18" FontWeight="SemiBold"/>
        <TextBlock x:Name="tbModel" Foreground="#A8A8A8" FontSize="12" Margin="0,2,0,0"
                   TextTrimming="CharacterEllipsis"/>
      </StackPanel>
    </DockPanel>

    <Border Grid.Row="1" x:Name="bdWarn" Visibility="Collapsed" Background="#3A2E06"
            CornerRadius="6" Padding="10,8" Margin="0,10,0,0">
      <TextBlock x:Name="tbWarn" Foreground="#FDDC69" FontSize="12" TextWrapping="Wrap"/>
    </Border>

    <DockPanel Grid.Row="2" Margin="0,12,0,0">
      <Button x:Name="btnCollapse" DockPanel.Dock="Right" Content="Collapse all" Margin="6,0,0,0"/>
      <Button x:Name="btnExpand" DockPanel.Dock="Right" Content="Expand all" Margin="6,0,0,0"/>
      <CheckBox x:Name="chkZoom" DockPanel.Dock="Right" Content="Zoom to selection" Margin="10,0,4,0"
                ToolTip="Also zoom the active view to the selected elements. If none of them are visible in the active view, Revit may ask to open another view."/>
      <CheckBox x:Name="chkFailed" DockPanel.Dock="Right" Content="Failed only" Margin="10,0,4,0"
                ToolTip="Show only the pass / fail checks that failed"/>
      <Grid>
        <TextBox x:Name="txtSearch"/>
        <TextBlock x:Name="tbPlaceholder" Text="Search checks and their lists" Foreground="#8D8D8D"
                   Margin="10,0,0,0" VerticalAlignment="Center" IsHitTestVisible="False"/>
      </Grid>
    </DockPanel>

    <Border Grid.Row="3" Margin="0,10,0,0" BorderBrush="#393939" BorderThickness="1" CornerRadius="6">
      <ScrollViewer VerticalScrollBarVisibility="Auto">
        <StackPanel>
          <StackPanel x:Name="spList"/>
          <TextBlock x:Name="tbEmpty" Visibility="Collapsed" Foreground="#8D8D8D" FontSize="12"
                     Margin="14,16" Text="No checks match."/>
        </StackPanel>
      </ScrollViewer>
    </Border>

    <Border Grid.Row="4" x:Name="bdStatus" Background="#262626" CornerRadius="6" Padding="10,8" Margin="0,10,0,0">
      <TextBlock x:Name="tbStatus" Foreground="#A8A8A8" FontSize="12" TextWrapping="Wrap"/>
    </Border>

    <DockPanel Grid.Row="5" Margin="0,12,0,0">
      <Button x:Name="btnClose" DockPanel.Dock="Right" Style="{StaticResource Accent}" Content="Close"/>
      <TextBlock x:Name="tbTotals" Foreground="#A8A8A8" FontSize="12" VerticalAlignment="Center"
                 TextTrimming="CharacterEllipsis"/>
    </DockPanel>
  </Grid>
</Window>
"""

UI_NAMES = ["btnRefresh", "tbTitle", "tbModel", "bdWarn", "tbWarn", "btnCollapse", "btnExpand",
            "chkZoom", "chkFailed", "txtSearch", "tbPlaceholder", "spList", "tbEmpty", "bdStatus",
            "tbStatus", "btnClose", "tbTotals"]


def show_section_report(uiapp, title):
    """Open (or bring forward) the report window of one Model Health Check section."""
    key = session_key(title)
    session = get_session(key)
    if session:
        existing = session.get("window")
        if existing is not None and existing.IsVisible:
            existing.Activate()
            return

    report_name = u"{0} Report".format(title)
    uidoc = uiapp.ActiveUIDocument
    doc = uidoc.Document if uidoc is not None else None
    if doc is None or doc.IsFamilyDocument:
        forms.alert(u"Open a project model first - this report checks a project, not a family.",
                    title=report_name)
        return
    section_description = hc.find_section(title)[1]

    first = run_checks(doc, title)
    if first is None:
        return      # cancelled from the progress bar

    window = XamlReader.Parse(XAML)
    ui = {}
    for name in UI_NAMES:
        ui[name] = window.FindName(name)
    window.Title = report_name
    ui["tbTitle"].Text = report_name

    event_handler = HealthEventHandler(report_name)
    external_event = ExternalEvent.Create(event_handler)

    def queue(action):
        event_handler.enqueue(action)
        external_event.Raise()

    state = {"report": first, "groups": [], "subs": []}

    # ---------------------------------------------------------------- status --
    def set_status(text, kind="info"):
        bg, fg = STATUS_COLORS[kind]
        ui["bdStatus"].Background = brush(bg)
        ui["tbStatus"].Foreground = brush(fg)
        ui["tbStatus"].Text = text

    def safe(handler):
        def wrapped(sender, args):
            try:
                handler(sender, args)
            except Exception as ex:
                logger.error("{0} error: {1}".format(report_name, ex))
                set_status(u"Something went wrong: {0}".format(ex), "warn")
        return wrapped

    # ------------------------------------------------------------- selection --
    def same_document(d):
        rep = state["report"]
        return d is not None and d.Title == rep["title"] and d.PathName == rep["path"]

    def select_ids(ids, label):
        append = (Keyboard.Modifiers & ModifierKeys.Control) == ModifierKeys.Control
        zoom = ui["chkZoom"].IsChecked == True
        if not ids:
            set_status(u"Nothing to select: {0} lists no elements.".format(label), "warn")
            return
        set_status(u"Selecting {0}…".format(label))

        def action():
            ud = uiapp.ActiveUIDocument
            d = ud.Document if ud is not None else None
            if not same_document(d):
                set_status(u"This report is for “{0}”. Switch back to that model, or click "
                           u"Refresh to check the active one.".format(state["report"]["title"]), "warn")
                return
            live = List[ElementId]()
            seen = set()
            missing = 0
            for n in ids:
                eid = element_id(n)
                if d.GetElement(eid) is None:
                    missing += 1
                    continue
                if n not in seen:
                    live.Add(eid)
                    seen.add(n)
            added = live.Count
            if append:
                for eid in ud.Selection.GetElementIds():
                    if hc.eid_value(eid) not in seen:
                        live.Add(eid)
                        seen.add(hc.eid_value(eid))
            ud.Selection.SetElementIds(live)
            if zoom and added:
                ud.ShowElements(live)
            text = u"{0} {1}: {2}.".format(
                u"Added" if append else u"Selected", plural(added, u"element"), label)
            if append:
                text += u" {0} selected in total.".format(hc.number(live.Count))
            if missing:
                text += u" {0} no longer exist. Click Refresh to run the checks again.".format(
                    plural(missing, u"element"))
            set_status(text, "warn" if missing else "ok")

        queue(action)

    def open_view(n, label):
        """Open a view, sheet or schedule from a list row."""
        set_status(u"Opening {0}\u2026".format(label))

        def action():
            ud = uiapp.ActiveUIDocument
            d = ud.Document if ud is not None else None
            if not same_document(d):
                set_status(u"This report is for \u201C{0}\u201D. Switch back to that model, or click "
                           u"Refresh to check the active one.".format(state["report"]["title"]), "warn")
                return
            v = d.GetElement(element_id(n))
            if v is None:
                set_status(u"{0} no longer exists. Click Refresh to run the checks again.".format(label), "warn")
                return
            if getattr(v, "IsTemplate", False) or getattr(v, "IsPlaceholder", False):
                set_status(u"{0} can't be opened: it's a template or a placeholder sheet.".format(label), "warn")
                return
            try:
                ud.RequestViewChange(v)
            except Exception as ex:
                set_status(u"Revit couldn't open {0}: {1}".format(label, ex), "warn")
                return
            set_status(u"Opened {0}.".format(label), "ok")

        queue(action)

    def make_open_handler(n, label):
        def handler(sender, args):
            args.Handled = True     # don't also select the row
            open_view(n, label)
        return safe(handler)

    def make_double_click_handler(n, label):
        def handler(sender, args):
            if args.ClickCount == 2:
                args.Handled = True
                open_view(n, label)
        return safe(handler)

    # ------------------------------------------------------------- list rows --
    def text_block(text, size=13, color="#F4F4F4", bold=False):
        tb = TextBlock()
        tb.Text = text
        tb.FontSize = size
        tb.Foreground = brush(color)
        tb.VerticalAlignment = VerticalAlignment.Center
        if bold:
            tb.FontWeight = FontWeights.SemiBold
        return tb

    def pill(text, bg, fg):
        b = Border()
        b.Background = brush(bg)
        b.CornerRadius = CornerRadius(8)
        b.Padding = Thickness(8, 1, 8, 2)
        b.Margin = Thickness(8, 0, 0, 0)
        b.VerticalAlignment = VerticalAlignment.Center
        b.MinWidth = 54
        t = text_block(text, 11, fg)
        t.HorizontalAlignment = HorizontalAlignment.Center
        b.Child = t
        return b

    def count_block(check):
        sp = StackPanel()
        sp.VerticalAlignment = VerticalAlignment.Center
        sp.Margin = Thickness(12, 0, 0, 0)
        sp.MinWidth = 100
        if check.error:
            big_text, caption, color, size = u"—", u"could not run", "#6F6F6F", 14
        elif check.kind == hc.RESULT:
            big_text, caption, color, size = check.value, u"result", "#F4F4F4", 13
        elif check.kind in (hc.PASS, hc.FAIL):
            n = check.count or 0
            big_text, caption, size = hc.number(n), u"issue" if n == 1 else u"issues", 14
            color = "#FFB3B8" if n else "#6F6F6F"
        else:
            n = check.count or 0
            big_text, caption, size = hc.number(n), u"found", 14
            color = "#F4F4F4" if n else "#6F6F6F"
        big = text_block(big_text, size, color, bold=True)
        big.HorizontalAlignment = HorizontalAlignment.Right
        big.MaxWidth = 240
        big.TextTrimming = TextTrimming.CharacterEllipsis
        big.ToolTip = check.value or None
        small = text_block(caption, 11, "#8D8D8D")
        small.HorizontalAlignment = HorizontalAlignment.Right
        sp.Children.Add(big)
        sp.Children.Add(small)
        return sp

    def make_select_handler(ids, label):
        def handler(sender, args):
            select_ids(ids, label)
        return safe(handler)

    def make_toggle_handler(group):
        def handler(sender, args):
            group["open"] = not group["open"]
            args.Handled = True     # don't also select the check's elements
            refresh_list()
        return safe(handler)

    def build_subsection(title_text, description, checks):
        n, p, f, rest, rate = hc.breakdown(checks)
        b = Border()
        b.Background = brush("#1E1E1E")
        b.BorderBrush = brush("#393939")
        b.BorderThickness = Thickness(0, 0, 0, 1)
        b.Padding = Thickness(12, 12, 12, 8)
        dp = DockPanel()
        parts = [plural(n, u"check")]
        if p + f:
            parts += [u"{0} pass".format(p), u"{0} fail".format(f)]
        summary = text_block(u"  ·  ".join(parts), 11, "#8D8D8D")
        DockPanel.SetDock(summary, Dock.Right)
        info = StackPanel()
        info.Children.Add(text_block(title_text.upper(), 11, "#F1C21B", bold=True))
        desc = text_block(description, 11, "#8D8D8D")
        desc.TextWrapping = TextWrapping.Wrap
        desc.Margin = Thickness(0, 2, 0, 0)
        info.Children.Add(desc)
        dp.Children.Add(summary)
        dp.Children.Add(info)
        b.Child = dp
        return {"row": b, "any": False}

    def build_group(check, sub):
        has_rows = bool(check.columns and check.rows)
        texts = []
        for r in check.rows:
            left, right = row_cells(check, r)
            texts.append((left, right, (left + u" " + right).lower()))
        group = {"check": check, "sub": sub, "open": False, "has_rows": has_rows, "texts": texts,
                 "search": (check.name + u" " + check.description).lower(), "built_for": None}

        row = Border()
        row.Style = window.FindResource("Row")
        row.Padding = Thickness(8, 8, 12, 8)
        dp = DockPanel()

        chevron = text_block(u"", 12, "#A8A8A8")
        chevron.FontFamily = FontFamily(u"Segoe UI Symbol")
        chevron.Width = 26
        chevron.TextAlignment = TextAlignment.Center
        chevron.Padding = Thickness(4, 2, 4, 2)
        chevron.Cursor = Cursors.Hand
        chevron.Background = brush("#00000000")     # hit-testable over its whole box
        chevron.ToolTip = u"Show or hide the list"

        info = StackPanel()
        info.VerticalAlignment = VerticalAlignment.Center
        name = text_block(check.name, 13, "#F4F4F4", bold=True)
        name.TextTrimming = TextTrimming.CharacterEllipsis
        sub_text = text_block(check.description, 11, "#8D8D8D")
        sub_text.TextWrapping = TextWrapping.Wrap
        info.Children.Add(name)
        info.Children.Add(sub_text)
        if check.kind == hc.FAIL and check.note:
            note = text_block(check.note, 11, "#FFB3B8")
            note.TextWrapping = TextWrapping.Wrap
            info.Children.Add(note)
        if check.error:
            err = text_block(check.result, 11, "#FDDC69")
            err.TextWrapping = TextWrapping.Wrap
            info.Children.Add(err)

        text, bg, fg = ERROR_PILL if check.error else KIND_PILLS.get(check.kind, KIND_PILLS[hc.COUNT])
        kind_pill = pill(text, bg, fg)
        counts = count_block(check)

        DockPanel.SetDock(chevron, Dock.Left)
        DockPanel.SetDock(counts, Dock.Right)
        DockPanel.SetDock(kind_pill, Dock.Right)
        for child in (chevron, counts, kind_pill, info):
            dp.Children.Add(child)
        row.Child = dp

        if check.ids:
            row.ToolTip = (u"Click to select the {0}. Ctrl+click adds to the current "
                           u"selection.").format(plural(len(check.ids), u"element"))
            row.MouseLeftButtonUp += MouseButtonEventHandler(make_select_handler(check.ids, check.name))
        elif has_rows:
            row.ToolTip = u"Click to show or hide the list"
            row.MouseLeftButtonUp += MouseButtonEventHandler(make_toggle_handler(group))
        else:
            row.Style = window.FindResource("PlainRow")
            row.ToolTip = u"Information only: nothing to select"
        if has_rows:
            chevron.MouseLeftButtonUp += MouseButtonEventHandler(make_toggle_handler(group))

        box = StackPanel()
        box.Visibility = Visibility.Collapsed
        group["row"] = row
        group["chevron"] = chevron
        group["box"] = box
        return group

    def fill_box(group, q):
        """(Re)build the list under a check: every row, or the rows matching q."""
        check = group["check"]
        box = group["box"]
        box.Children.Clear()
        caption = text_block(u"  ·  ".join(check.columns), 11, "#6F6F6F")
        caption.Margin = Thickness(44, 6, 12, 4)
        box.Children.Add(caption)
        shown = 0
        matched = 0
        for i, (left, right, low) in enumerate(group["texts"]):
            if q and q not in low:
                continue
            matched += 1
            if shown >= MAX_ROWS:
                continue
            shown += 1
            ids = check.row_ids[i] if i < len(check.row_ids) else []
            open_id = check.row_open[i] if i < len(check.row_open) else None
            r = Border()
            r.Style = window.FindResource("Row" if (ids or open_id) else "PlainRow")
            r.Padding = Thickness(44, 5, 12, 5)
            dp = DockPanel()
            if open_id:
                chip = Border()
                chip.Style = window.FindResource("OpenChip")
                chip.Child = text_block(u"Open", 11, "#F4F4F4")
                chip.ToolTip = u"Open it in Revit"
                chip.MouseLeftButtonUp += MouseButtonEventHandler(make_open_handler(open_id, left))
                DockPanel.SetDock(chip, Dock.Right)
                dp.Children.Add(chip)
            if right:
                rt = text_block(right, 12, "#8D8D8D")
                rt.Margin = Thickness(12, 0, 0, 0)
                DockPanel.SetDock(rt, Dock.Right)
                dp.Children.Add(rt)
            lt = text_block(left, 12, "#C6C6C6")
            lt.TextTrimming = TextTrimming.CharacterEllipsis
            dp.Children.Add(lt)
            r.Child = dp
            if ids:
                r.ToolTip = u"Click to select {0}. Ctrl+click adds to the current selection.".format(
                    u"this element" if len(ids) == 1 else plural(len(ids), u"element"))
                r.MouseLeftButtonUp += MouseButtonEventHandler(make_select_handler(ids, left))
            if open_id:
                r.ToolTip = (r.ToolTip or u"") + u" Double-click or click Open to open it."
                r.MouseLeftButtonDown += MouseButtonEventHandler(make_double_click_handler(open_id, left))
            box.Children.Add(r)
        if matched > shown:
            more = text_block(u"… and {0} more. Type in the search box to narrow the "
                              u"list.".format(plural(matched - shown, u"row")), 11, "#8D8D8D")
            more.Margin = Thickness(44, 6, 12, 8)
            box.Children.Add(more)
        group["built_for"] = q

    def build_list():
        rep = state["report"]
        ui["spList"].Children.Clear()
        state["groups"] = []
        state["subs"] = []

        def add(items, sub):
            for item in items:
                if isinstance(item, hc.Check):
                    group = build_group(item, sub)
                    state["groups"].append(group)
                    ui["spList"].Children.Add(group["row"])
                    ui["spList"].Children.Add(group["box"])
                else:
                    s_title, s_desc, children = item
                    new_sub = build_subsection(s_title, s_desc, hc.flat_checks(children))
                    state["subs"].append(new_sub)
                    ui["spList"].Children.Add(new_sub["row"])
                    add(children, new_sub)

        add(rep["items"], None)

        checks = list(hc.flat_checks(rep["items"]))
        n, p, f, rest, rate = hc.breakdown(checks)
        ui["tbModel"].Text = u"{0}  —  {1}  ·  run at {2}".format(
            rep["title"], plural(n, u"check"), rep["time"])
        errors = [c.name for c in checks if c.error]
        if errors:
            ui["tbWarn"].Text = u"{0} could not run on this model: {1}".format(
                plural(len(errors), u"check"), u", ".join(errors))
            ui["bdWarn"].Visibility = Visibility.Visible
        else:
            ui["bdWarn"].Visibility = Visibility.Collapsed
        parts = [plural(n, u"check"), u"{0} pass".format(p), u"{0} fail".format(f),
                 u"{0} count / result".format(rest)]
        if rate is not None:
            parts.append(u"Pass rate {0}%".format(rate))
        ui["tbTotals"].Text = u"  ·  ".join(parts)
        ui["tbTotals"].ToolTip = section_description
        refresh_list()

    def refresh_list():
        raw = ui["txtSearch"].Text or u""
        q = raw.strip().lower()
        failed_only = ui["chkFailed"].IsChecked == True
        ui["tbPlaceholder"].Visibility = Visibility.Collapsed if raw else Visibility.Visible
        for sub in state["subs"]:
            sub["any"] = False
        visible = 0
        for group in state["groups"]:
            check = group["check"]
            name_hit = not q or q in group["search"]
            row_hit = bool(q) and not name_hit and any(q in t[2] for t in group["texts"])
            show = (name_hit or row_hit) and (not failed_only or check.kind == hc.FAIL)
            group["row"].Visibility = Visibility.Visible if show else Visibility.Collapsed
            # a match inside the list opens the check so the match is visible
            is_open = show and group["has_rows"] and (group["open"] or row_hit)
            if group["has_rows"]:
                group["chevron"].Text = u"▾" if is_open else u"▸"
            if is_open:
                wanted = u"" if name_hit else q
                if group["built_for"] != wanted:
                    fill_box(group, wanted)
                group["box"].Visibility = Visibility.Visible
            else:
                group["box"].Visibility = Visibility.Collapsed
            if show:
                visible += 1
                if group["sub"] is not None:
                    group["sub"]["any"] = True
        for sub in state["subs"]:
            sub["row"].Visibility = Visibility.Visible if sub["any"] else Visibility.Collapsed
        ui["tbEmpty"].Visibility = Visibility.Collapsed if visible else Visibility.Visible

    # ----------------------------------------------------------------- buttons --
    def set_all(is_open):
        for group in state["groups"]:
            group["open"] = is_open
        refresh_list()

    def on_refresh(sender, args):
        set_status(u"Running the checks on the active model…")
        ui["btnRefresh"].IsEnabled = False

        def action():
            try:
                ud = uiapp.ActiveUIDocument
                d = ud.Document if ud is not None else None
                if d is None or d.IsFamilyDocument:
                    set_status(u"The active document is not a project model, so there is nothing "
                               u"to check.", "warn")
                    return
                rep = run_checks(d, title)
                if rep is None:
                    set_status(u"Stopped by you - the list still shows the last run.", "warn")
                    return
                opened = set(g["check"].name for g in state["groups"] if g["open"])
                state["report"] = rep
                build_list()
                for group in state["groups"]:
                    group["open"] = group["check"].name in opened
                refresh_list()
                set_status(u"Checked “{0}”.".format(d.Title), "ok")
            finally:
                ui["btnRefresh"].IsEnabled = True

        queue(action)

    def on_closed(sender, args):
        # Let a later press open a fresh window, and release the ExternalEvent.
        set_session(key, None)
        try:
            external_event.Dispose()
        except Exception:
            logger.debug("ExternalEvent was already disposed.")

    ui["btnExpand"].Click += RoutedEventHandler(safe(lambda s, a: set_all(True)))
    ui["btnCollapse"].Click += RoutedEventHandler(safe(lambda s, a: set_all(False)))
    ui["btnRefresh"].Click += RoutedEventHandler(safe(on_refresh))
    ui["btnClose"].Click += RoutedEventHandler(safe(lambda s, a: window.Close()))
    ui["chkFailed"].Click += RoutedEventHandler(safe(lambda s, a: refresh_list()))
    ui["txtSearch"].TextChanged += TextChangedEventHandler(safe(lambda s, a: refresh_list()))
    window.Closed += EventHandler(on_closed)

    build_list()
    set_status(HINT)

    try:
        WindowInteropHelper(window).Owner = uiapp.MainWindowHandle
    except Exception:
        logger.debug("Could not set Revit as the owner window.")

    # Parked where it outlives this call: the strong reference that keeps the
    # ExternalEvent alive while the window is open.
    set_session(key, {"window": window, "handler": event_handler, "event": external_event})

    # Show(), not ShowDialog(), and nothing after it: the script ends here and
    # Revit is free while the window stays open.
    window.Show()

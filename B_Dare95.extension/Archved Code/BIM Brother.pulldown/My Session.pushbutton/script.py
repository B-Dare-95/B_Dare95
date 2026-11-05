# -*- coding: utf-8 -*-
__title__ = "My\nSession"
__author__ = "Mohamed Bedair"
__doc__ = """BIM Brother - My Session: every change you make, recorded the moment you make it.
Click: open the timeline for this document.
Shift+Click: open the session log location."""

import os
import clr
clr.AddReference("System")
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from datetime import datetime, timedelta

from System import EventHandler, TimeSpan
from System.Diagnostics import Process
from System.Collections.Generic import List
from System.Windows import (
    Thickness, Visibility, VerticalAlignment, TextWrapping, FontWeights, CornerRadius, RoutedEventHandler
)
from System.Windows.Controls import Button, StackPanel, TextBlock, Border, WrapPanel, Orientation
from System.Windows.Markup import XamlReader
from System.Windows.Media import BrushConverter
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Threading import Dispatcher, DispatcherFrame, DispatcherTimer

from Autodesk.Revit.DB import ElementId
from Autodesk.Revit.UI import TaskDialog

import change_tracker as ct
import session_recorder as sr

uidoc = __revit__.ActiveUIDocument
doc = uidoc.Document

# =============================================================================
# IBM CARBON (Gray 100)
# =============================================================================
BG, CARD, SURFACE, MUTED = "#161616", "#262626", "#393939", "#525252"
TEXT, SUB, ACCENT = "#F4F4F4", "#A8A8A8", "#F1C21B"
OK, WARN, ERROR = "#42BE65", "#F1C21B", "#FA4D56"

KIND_STYLE = {   # (label, background, text)
    "added":    (u"NEW",      "#0E6027", "#A7F0BA"),
    "modified": (u"MODIFIED", "#0043CE", "#D0E2FF"),
    "deleted":  (u"DELETED",  "#A2191F", "#FFD7D9"),
}
KINDS = ["added", "modified", "deleted"]
KIND_CHIPS = [("All", u"All", "ChipAll"), ("added", u"New", "ChipNew"),
              ("modified", u"Modified", "ChipModified"), ("deleted", u"Deleted", "ChipDeleted")]
WINDOWS = [
    ("4w", u"Last 4 weeks", timedelta(weeks=4), "Win4w"),
    ("3w", u"Last 3 weeks", timedelta(weeks=3), "Win3w"),
    ("2w", u"Last 2 weeks", timedelta(weeks=2), "Win2w"),
    ("1w", u"Last week", timedelta(weeks=1), "Win1w"),
    ("1d", u"Last day", timedelta(days=1), "Win1d"),
    ("1h", u"Last hour", timedelta(hours=1), "Win1h"),
]
DEFAULT_WINDOW = "1d"
ROW_CAP = 300            # element rows shown per action (a big paste can touch thousands)
SEP = u"  \u00B7  "
CHEV_CLOSED, CHEV_OPEN = u"\u25B8", u"\u25BE"

_bc = BrushConverter()
_brushes = {}


def br(hex_color):
    if hex_color not in _brushes:
        _brushes[hex_color] = _bc.ConvertFromString(hex_color)
    return _brushes[hex_color]


def tb(text, size=13, fg=TEXT, bold=False, margin=None, wrap=False):
    t = TextBlock()
    t.Text = text if text is not None else u"\u2014"
    t.FontSize = size
    t.Foreground = br(fg)
    t.VerticalAlignment = VerticalAlignment.Center
    if bold:
        t.FontWeight = FontWeights.SemiBold
    if margin is not None:
        t.Margin = margin
    if wrap:
        t.TextWrapping = TextWrapping.Wrap
    return t


def tag(text, bg, fg, margin=None):
    b = Border()
    b.Background = br(bg)
    b.CornerRadius = CornerRadius(10)
    b.Padding = Thickness(8, 1, 8, 2)
    b.Margin = margin if margin is not None else Thickness(0, 0, 6, 0)
    b.VerticalAlignment = VerticalAlignment.Center
    b.Child = tb(text, 10, fg, True)
    return b


def clock(iso):
    dt = ct._parse_iso(iso)
    if dt is None:
        return u"\u2014"
    hour = dt.strftime("%I").lstrip("0") or "12"
    return u"{0}:{1}:{2} {3}".format(hour, dt.strftime("%M"), dt.strftime("%S"), dt.strftime("%p"))


def day_label(iso):
    dt = ct._parse_iso(iso)
    return u"{0}  \u00B7  {1}".format(dt.strftime("%A"), dt.strftime("%Y-%m-%d")) if dt else u"\u2014"


def row_text(row):
    eid, uid, cat, fam, typ, is_type = row
    name = u"{0} type".format(ct.noun(cat)) if is_type else ct.noun(cat)
    return name, eid, u"{0} \u203A {1} \u203A {2}".format(cat, fam, typ)


# =============================================================================
# XAML
# =============================================================================
XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="BIM Brother \u00B7 My Session" Width="1100" Height="820" MinWidth="820" MinHeight="520"
        WindowStartupLocation="CenterScreen" Background="#161616"
        FontFamily="IBM Plex Sans, Segoe UI" FontSize="13" Foreground="#F4F4F4">
  <Window.Resources>
    <Style x:Key="PrimaryBtn" TargetType="Button">
      <Setter Property="Background" Value="#F1C21B"/>
      <Setter Property="Foreground" Value="#161616"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
      <Setter Property="Height" Value="34"/>
      <Setter Property="Padding" Value="16,0"/>
      <Setter Property="Margin" Value="8,0,0,0"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="bd" Background="{TemplateBinding Background}" CornerRadius="4" Padding="{TemplateBinding Padding}">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True"><Setter TargetName="bd" Property="Opacity" Value="0.85"/></Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style x:Key="GhostBtn" TargetType="Button">
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="BorderBrush" Value="#525252"/>
      <Setter Property="Height" Value="34"/>
      <Setter Property="Padding" Value="14,0"/>
      <Setter Property="Margin" Value="8,0,0,0"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="bd" Background="{TemplateBinding Background}" BorderBrush="{TemplateBinding BorderBrush}"
                    BorderThickness="1" CornerRadius="4" Padding="{TemplateBinding Padding}">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True"><Setter TargetName="bd" Property="Background" Value="#525252"/></Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style x:Key="ChipBtn" TargetType="ToggleButton">
      <Setter Property="Background" Value="Transparent"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="BorderBrush" Value="#525252"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="Height" Value="30"/>
      <Setter Property="Padding" Value="12,0"/>
      <Setter Property="Margin" Value="0,0,6,0"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ToggleButton">
            <Border Background="{TemplateBinding Background}" BorderBrush="{TemplateBinding BorderBrush}"
                    BorderThickness="1" CornerRadius="15" Padding="{TemplateBinding Padding}">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
      <Style.Triggers>
        <Trigger Property="IsChecked" Value="True">
          <Setter Property="Background" Value="#F1C21B"/>
          <Setter Property="BorderBrush" Value="#F1C21B"/>
          <Setter Property="Foreground" Value="#161616"/>
          <Setter Property="FontWeight" Value="SemiBold"/>
        </Trigger>
      </Style.Triggers>
    </Style>
    <Style x:Key="RowBtn" TargetType="Button">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="HorizontalContentAlignment" Value="Stretch"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="bd" Background="{TemplateBinding Background}" BorderBrush="{TemplateBinding BorderBrush}"
                    BorderThickness="1" CornerRadius="4" Padding="{TemplateBinding Padding}">
              <ContentPresenter HorizontalAlignment="{TemplateBinding HorizontalContentAlignment}"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True"><Setter TargetName="bd" Property="BorderBrush" Value="#6F6F6F"/></Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
  </Window.Resources>

  <Grid Margin="20">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <DockPanel Grid.Row="0">
      <StackPanel DockPanel.Dock="Right" Orientation="Horizontal" VerticalAlignment="Center">
        <Button x:Name="ReloadBtn" Style="{StaticResource PrimaryBtn}" Content="Reload log"/>
        <Button x:Name="ExpandBtn" Style="{StaticResource GhostBtn}" Content="Expand all"/>
        <Button x:Name="CollapseBtn" Style="{StaticResource GhostBtn}" Content="Collapse all"/>
      </StackPanel>
      <StackPanel>
        <TextBlock Text="BIM Brother \u00B7 My Session" FontSize="22" FontWeight="SemiBold"/>
        <TextBlock x:Name="DocText" Foreground="#A8A8A8" Margin="0,4,0,0" TextTrimming="CharacterEllipsis"/>
      </StackPanel>
    </DockPanel>

    <Border Grid.Row="1" Background="#262626" CornerRadius="6" Padding="12" Margin="0,16,0,14">
      <StackPanel>
        <DockPanel>
          <Grid DockPanel.Dock="Left" Width="300" Margin="0,0,14,0">
            <TextBox x:Name="SearchBox" Height="34" Padding="10,0" VerticalContentAlignment="Center"
                     Background="#161616" Foreground="#F4F4F4" BorderBrush="#525252" CaretBrush="#F4F4F4"/>
            <TextBlock x:Name="SearchHint" Text="Filter by action, ID, category, type..." Foreground="#6F6F6F"
                       Margin="12,0,0,0" VerticalAlignment="Center" IsHitTestVisible="False"/>
          </Grid>
          <WrapPanel VerticalAlignment="Center">
            <ToggleButton x:Name="ChipAll" Style="{StaticResource ChipBtn}" IsChecked="True"/>
            <ToggleButton x:Name="ChipNew" Style="{StaticResource ChipBtn}"/>
            <ToggleButton x:Name="ChipModified" Style="{StaticResource ChipBtn}"/>
            <ToggleButton x:Name="ChipDeleted" Style="{StaticResource ChipBtn}"/>
          </WrapPanel>
        </DockPanel>
        <StackPanel Orientation="Horizontal" HorizontalAlignment="Right" Margin="0,10,0,0">
          <TextBlock Text="Show actions from the" Foreground="#A8A8A8" FontSize="12" VerticalAlignment="Center" Margin="0,0,8,0"/>
          <ToggleButton x:Name="Win4w" Style="{StaticResource ChipBtn}" Content="Last 4 weeks"/>
          <ToggleButton x:Name="Win3w" Style="{StaticResource ChipBtn}" Content="Last 3 weeks"/>
          <ToggleButton x:Name="Win2w" Style="{StaticResource ChipBtn}" Content="Last 2 weeks"/>
          <ToggleButton x:Name="Win1w" Style="{StaticResource ChipBtn}" Content="Last week"/>
          <ToggleButton x:Name="Win1d" Style="{StaticResource ChipBtn}" Content="Last day"/>
          <ToggleButton x:Name="Win1h" Style="{StaticResource ChipBtn}" Content="Last hour" Margin="0"/>
        </StackPanel>
      </StackPanel>
    </Border>

    <Border Grid.Row="2" Background="#262626" CornerRadius="6" Padding="10">
      <ScrollViewer VerticalScrollBarVisibility="Auto">
        <StackPanel x:Name="Timeline"/>
      </ScrollViewer>
    </Border>

    <Border Grid.Row="3" Background="#393939" CornerRadius="4" Padding="12,8" Margin="0,14,0,0">
      <DockPanel>
        <Ellipse x:Name="StatusDot" Width="8" Height="8" Fill="#42BE65" VerticalAlignment="Center"/>
        <TextBlock x:Name="StatusText" Margin="10,0,0,0" FontSize="12" TextTrimming="CharacterEllipsis"/>
      </DockPanel>
    </Border>
  </Grid>
</Window>
"""


# =============================================================================
# DATA
# =============================================================================
def load_actions(path):
    """Actions in file order, each flagged synced / local (None when the model isn't workshared)."""
    entries = sr.read_log(path)
    actions, synced_after, last_sync = [], False, None
    for e in reversed(entries):
        if e.get("op") == "sync":
            synced_after = True
            if last_sync is None:
                last_sync = e.get("t")
            continue
        e["_synced"] = synced_after if doc.IsWorkshared else None
        actions.append(e)
    actions.reverse()
    return actions, last_sync


# =============================================================================
# WINDOW
# =============================================================================
class SessionWindow(object):

    def __init__(self, path):
        self.path = path
        self.win = XamlReader.Parse(XAML)
        find = self.win.FindName
        self.timeline = find("Timeline")
        self.search = find("SearchBox")
        self.hint = find("SearchHint")
        self.status_text = find("StatusText")
        self.status_dot = find("StatusDot")
        find("DocText").Text = u"{0}{1}{2}".format(doc.Title, SEP, os.path.basename(path))

        self.kind, self.query, self.window_key = "All", u"", DEFAULT_WINDOW
        self.nodes = []

        self.chips = {}
        for key, label, name in KIND_CHIPS:
            self.chips[key] = find(name)
            self.chips[key].Click += RoutedEventHandler(self._kind_handler(key))
        self.win_btns = {}
        for key, label, delta, name in WINDOWS:
            self.win_btns[key] = find(name)
            self.win_btns[key].IsChecked = (key == self.window_key)
            self.win_btns[key].Click += RoutedEventHandler(self._window_handler(key))

        find("ReloadBtn").Click += RoutedEventHandler(self.on_reload)
        find("ExpandBtn").Click += RoutedEventHandler(lambda s, e: self.set_all(True))
        find("CollapseBtn").Click += RoutedEventHandler(lambda s, e: self.set_all(False))
        self.search.TextChanged += self.on_search_changed
        self.timer = DispatcherTimer()
        self.timer.Interval = TimeSpan.FromMilliseconds(250)
        self.timer.Tick += EventHandler(self.on_timer)

        self.load()

    # ------------------------------------------------------------------ data
    def load(self):
        self.actions, self.last_sync = load_actions(self.path)
        self.rebuild()

    def _window(self):
        for key, label, delta, _ in WINDOWS:
            if key == self.window_key:
                return label, delta
        return WINDOWS[4][1], WINDOWS[4][2]

    def _rows(self, action, q):
        """{kind: [rows]} after the kind chip and the search filter. Empty dict = hide the action."""
        name_hit = bool(q) and q in (action.get("action") or u"").lower()
        out = {}
        for kind in KINDS:
            if self.kind != "All" and kind != self.kind:
                continue
            rows = action.get(kind) or []
            if q and not name_hit:
                rows = [r for r in rows if q in u" ".join(unicode(x) for x in r[:5]).lower()]
            if rows:
                out[kind] = rows
        return out

    # ------------------------------------------------------------------ build
    def rebuild(self):
        self.timeline.Children.Clear()
        self.nodes = []
        label, delta = self._window()
        cutoff = ct._iso(datetime.now() - delta)
        windowed = [a for a in self.actions if (a.get("t") or u"") >= cutoff]

        counts = dict((k, 0) for k in KINDS)
        for a in windowed:
            for k in KINDS:
                counts[k] += len(a.get(k) or [])
        for key, text, _ in KIND_CHIPS:
            n = sum(counts.values()) if key == "All" else counts[key]
            self.chips[key].Content = u"{0}   {1}".format(text, n)

        q = self.query.lower()
        shown = []
        for a in reversed(windowed):                        # newest first
            rows = self._rows(a, q)
            if rows or (not q and self.kind == "All" and a.get("unindexed_deleted")):
                shown.append((a, rows))

        if not self.actions:
            self.timeline.Children.Add(tb(
                u"Nothing recorded yet for this document. Recording runs in the background from the moment "
                u"Revit loads BIM Brother: make a change, then press Reload log.", 13, SUB,
                margin=Thickness(14), wrap=True))
        elif not shown:
            self.timeline.Children.Add(tb(u"No actions match this filter in the {0}.".format(label.lower()),
                                          13, SUB, margin=Thickness(14)))

        current_day = None
        for a, rows in shown:
            day = (a.get("t") or u"")[:10]
            if day != current_day:
                current_day = day
                self.timeline.Children.Add(tb(day_label(a.get("t")), 12, SUB, True, Thickness(4, 12, 0, 6)))
            self.timeline.Children.Add(self.make_card(a, rows))

        self.update_status(len(shown), label)

    def make_card(self, action, rows):
        container = StackPanel()
        container.Margin = Thickness(0, 0, 0, 6)

        head = Button()
        head.Style = self.win.FindResource("RowBtn")
        head.Background = br(SURFACE)
        head.BorderBrush = br(SURFACE)
        head.Padding = Thickness(12, 9, 12, 9)

        body = StackPanel()
        line1 = WrapPanel()
        chev = tb(CHEV_CLOSED, 12, SUB, margin=Thickness(0, 0, 10, 0))
        line1.Children.Add(chev)
        line1.Children.Add(tb(clock(action.get("t")), 13, TEXT, True, Thickness(0, 0, 12, 0)))
        line1.Children.Add(tb(action.get("action"), 13, TEXT, margin=Thickness(0, 0, 10, 0)))
        if action.get("op") == "undo":
            line1.Children.Add(tag(u"UNDO", MUTED, TEXT))
        elif action.get("op") == "redo":
            line1.Children.Add(tag(u"REDO", MUTED, TEXT))
        if action.get("_synced") is True:
            line1.Children.Add(tag(u"SYNCED", "#0E6027", "#A7F0BA"))
        elif action.get("_synced") is False:
            line1.Children.Add(tag(u"LOCAL", ACCENT, BG))
        body.Children.Add(line1)

        parts = []
        for kind, word in (("added", u"new"), ("modified", u"modified"), ("deleted", u"deleted")):
            n = len(action.get(kind) or [])
            if n:
                parts.append(u"{0} {1}".format(n, word))
        if action.get("unindexed_deleted"):
            parts.append(u"{0} deleted before indexing finished (names unknown)".format(action["unindexed_deleted"]))
        body.Children.Add(tb(SEP.join(parts) + SEP + (action.get("user") or u""), 12, SUB,
                             margin=Thickness(22, 4, 0, 0)))
        head.Content = body

        children = StackPanel()
        children.Visibility = Visibility.Collapsed
        node = {"chev": chev, "children": children, "built": False, "open": False, "rows": rows}
        head.Click += RoutedEventHandler(lambda s, e: self.toggle(node))
        self.nodes.append(node)

        container.Children.Add(head)
        container.Children.Add(children)
        return container

    def toggle(self, node, force=None):
        opened = (not node["open"]) if force is None else force
        if opened and not node["built"]:
            self.build_rows(node)
            node["built"] = True
        node["children"].Visibility = Visibility.Visible if opened else Visibility.Collapsed
        node["chev"].Text = CHEV_OPEN if opened else CHEV_CLOSED
        node["open"] = opened

    def build_rows(self, node):
        shown = 0
        total = sum(len(r) for r in node["rows"].values())
        for kind in KINDS:
            for row in node["rows"].get(kind, []):
                if shown >= ROW_CAP:
                    break
                node["children"].Children.Add(self.make_row(kind, row))
                shown += 1
        if total > shown:
            node["children"].Children.Add(tb(u"+ {0} more elements in this action".format(total - shown),
                                             12, SUB, margin=Thickness(28, 4, 0, 4)))

    def make_row(self, kind, row):
        label, bg, fg = KIND_STYLE[kind]
        name, eid, path = row_text(row)
        btn = Button()
        btn.Style = self.win.FindResource("RowBtn")
        btn.Background = br(CARD)
        btn.BorderBrush = br(CARD)
        btn.Margin = Thickness(28, 2, 0, 2)
        btn.Padding = Thickness(10, 6, 10, 6)
        line = WrapPanel()
        line.Children.Add(tag(label, bg, fg))
        line.Children.Add(tb(u"{0} ({1})".format(name, eid), 13, TEXT, True, Thickness(2, 0, 10, 0)))
        line.Children.Add(tb(path, 12, SUB))
        btn.Content = line
        btn.Click += RoutedEventHandler(lambda s, e: self.pick(kind, row))
        return btn

    # ------------------------------------------------------------- selection
    def pick(self, kind, row):
        name, eid, _ = row_text(row)
        label = u"{0} {1}".format(name, eid)
        if kind == "deleted":
            self.set_status(u"{0} was deleted by this action{1}nothing to select".format(label, SEP), ERROR)
            return
        el = doc.GetElement(row[1])
        if el is None:
            self.set_status(u"{0} no longer exists (deleted by a later action).".format(label), WARN)
            return
        ids = List[ElementId]()
        ids.Add(el.Id)
        uidoc.Selection.SetElementIds(ids)
        self.set_status(u"Selected {0} in Revit".format(label))

    # ---------------------------------------------------------------- status
    def update_status(self, n_shown, label):
        if not sr.is_armed():
            self.set_status(u"The recorder is not running in this session: add the startup.py block "
                            u"and restart Revit.", ERROR)
            return
        parts = [u"{0} action(s) in the {1}".format(n_shown, label.lower())]
        if doc.IsWorkshared:
            parts.append(u"last sync {0} {1}".format(day_label(self.last_sync), clock(self.last_sync))
                         if self.last_sync else u"no sync recorded yet")
        parts.append(u"recording")
        self.set_status(SEP.join(parts))

    def set_status(self, text, color=OK):
        self.status_text.Text = text
        self.status_dot.Fill = br(color)

    # ---------------------------------------------------------------- events
    def _kind_handler(self, key):
        def handler(sender, args):
            self.kind = key
            for k, chip in self.chips.items():
                chip.IsChecked = (k == key)
            self.rebuild()
        return handler

    def _window_handler(self, key):
        def handler(sender, args):
            self.window_key = key
            for k, btn in self.win_btns.items():
                btn.IsChecked = (k == key)
            self.rebuild()
        return handler

    def on_search_changed(self, sender, args):
        self.hint.Visibility = Visibility.Collapsed if self.search.Text else Visibility.Visible
        self.timer.Stop()
        self.timer.Start()

    def on_timer(self, sender, args):
        self.timer.Stop()
        self.query = self.search.Text or u""
        self.rebuild()

    def on_reload(self, sender, args):
        self.load()

    def set_all(self, opened):
        for node in self.nodes:
            self.toggle(node, opened)

    def show(self):
        try:
            WindowInteropHelper(self.win).Owner = __revit__.MainWindowHandle
        except Exception:
            pass
        frame = DispatcherFrame()

        def on_closed(sender, args):
            frame.Continue = False

        self.win.Closed += EventHandler(on_closed)
        self.win.Show()
        Dispatcher.PushFrame(frame)


# =============================================================================
# ENTRY
# =============================================================================
def main():
    try:
        shift = __shiftclick__
    except NameError:
        shift = False

    if doc.IsFamilyDocument:
        TaskDialog.Show("BIM Brother", "My Session works on project documents only.")
        return
    path = sr.log_path(doc)
    if shift:
        if os.path.exists(path):
            Process.Start("explorer.exe", u'/select,"{0}"'.format(path))
        else:
            if not os.path.isdir(sr.SESSION_DIR):
                os.makedirs(sr.SESSION_DIR)
            Process.Start("explorer.exe", u'"{0}"'.format(sr.SESSION_DIR))
        return
    SessionWindow(path).show()


main()
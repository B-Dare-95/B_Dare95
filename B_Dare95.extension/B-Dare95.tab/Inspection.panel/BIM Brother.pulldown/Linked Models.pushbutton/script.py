# -*- coding: utf-8 -*-

__author__ = "Mohamed Bedair"
__doc__ = """BIM Brother for Revit links: pick a loaded link to monitor, then see its New, Deleted,
Moved, Resized and Data changes after every reload.
Click: open the report.
Shift+Click: open the link registers folder."""

import os
import time
import clr
clr.AddReference("System")
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from System import EventHandler, TimeSpan
from System.Diagnostics import Process
from System.Collections.Generic import List
from System.Windows import (
    Thickness, Visibility, HorizontalAlignment, VerticalAlignment, TextWrapping,
    FontWeights, CornerRadius, TextTrimming, RoutedEventHandler, MessageBox,
    MessageBoxButton, MessageBoxResult
)
from System import DateTime, Action
from System.Windows.Controls import (
    Button, StackPanel, TextBlock, Border, DockPanel, Dock, WrapPanel, Orientation
)
from System.Windows.Controls.Primitives import UniformGrid
from System.Windows.Markup import XamlReader
from System.Windows.Media import BrushConverter, Brushes
from System.Windows.Input import Mouse, Cursors
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Threading import Dispatcher, DispatcherFrame, DispatcherTimer, DispatcherPriority

from Autodesk.Revit.DB import ElementId, XYZ, Reference, ViewType
from Autodesk.Revit.UI import TaskDialog

import change_tracker as ct
import link_tracker as lt

uidoc = __revit__.ActiveUIDocument
doc = uidoc.Document

# =============================================================================
# IBM CARBON (Gray 100)
# =============================================================================
BG, CARD, SURFACE, MUTED = "#161616", "#262626", "#393939", "#525252"
TEXT, SUB, ACCENT = "#F4F4F4", "#A8A8A8", "#F1C21B"
SELECTED_BG = "#474747"
OK, WARN, ERROR = "#42BE65", "#F1C21B", "#FA4D56"

# Carbon dark tag tokens: (background, text, label)
KIND_STYLE = {
    ct.NEW:     ("#0E6027", "#A7F0BA", u"NEW"),
    ct.DELETED: ("#A2191F", "#FFD7D9", u"DELETED"),
    ct.MOVED:   ("#0043CE", "#D0E2FF", u"MOVED"),
    ct.RESIZED: ("#005D5D", "#9EF0F0", u"RESIZED"),
    ct.DATA:    ("#6929C4", "#E8DAFF", u"DATA"),
}
CHIP_LABELS = [("All", u"All"), (ct.NEW, u"New"), (ct.DELETED, u"Deleted"),
               (ct.MOVED, u"Moved"), (ct.RESIZED, u"Resized"), (ct.DATA, u"Data")]
AUTO_EXPAND_LIMIT = 150
MODEL_VIEW_TYPES = [ViewType.FloorPlan, ViewType.CeilingPlan, ViewType.EngineeringPlan, ViewType.AreaPlan,
                    ViewType.Section, ViewType.Elevation, ViewType.Detail, ViewType.ThreeD]
CHEV_CLOSED, CHEV_OPEN = u"\u25B8", u"\u25BE"
SEP = u"  \u00B7  "

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


def badge(kind):
    bg, fg, label = KIND_STYLE[kind]
    b = Border()
    b.Background = br(bg)
    b.CornerRadius = CornerRadius(10)
    b.Padding = Thickness(8, 1, 8, 2)
    b.Margin = Thickness(0, 0, 6, 0)
    b.VerticalAlignment = VerticalAlignment.Center
    b.Child = tb(label, 10, fg, True)
    return b


def section(text):
    return tb(text.upper(), 11, SUB, True, Thickness(0, 14, 0, 6))


def count_text(n):
    return u"1 change" if n == 1 else u"{0} changes".format(n)


def ordered_kinds(rec):
    return [k for k in ct.KIND_ORDER if k in (rec.get("kinds") or [])]


# =============================================================================
# XAML
# =============================================================================
XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="BIM Brother · Links" Width="1240" Height="840" MinWidth="940" MinHeight="560"
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

    <Style x:Key="HeadBtn" TargetType="Button">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="HorizontalContentAlignment" Value="Stretch"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="bd" Background="{TemplateBinding Background}" CornerRadius="4" Padding="{TemplateBinding Padding}">
              <ContentPresenter HorizontalAlignment="{TemplateBinding HorizontalContentAlignment}" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True"><Setter TargetName="bd" Property="Background" Value="#333333"/></Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
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
    <Style x:Key="PickerBtn" TargetType="Button">
      <Setter Property="Background" Value="#262626"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="BorderBrush" Value="#525252"/>
      <Setter Property="HorizontalContentAlignment" Value="Stretch"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="bd" Background="{TemplateBinding Background}" BorderBrush="{TemplateBinding BorderBrush}"
                    BorderThickness="1" CornerRadius="4" Padding="12,6">
              <ContentPresenter HorizontalAlignment="{TemplateBinding HorizontalContentAlignment}" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True"><Setter TargetName="bd" Property="BorderBrush" Value="#F1C21B"/></Trigger>
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

    <DockPanel Grid.Row="0" LastChildFill="True">
      <StackPanel DockPanel.Dock="Right" Orientation="Horizontal" VerticalAlignment="Center">
        <Button x:Name="ScanAllBtn" Style="{StaticResource GhostBtn}" Content="Scan all stale"/>
        <Button x:Name="StopBtn" Style="{StaticResource GhostBtn}" Content="Stop monitoring"/>
        <Button x:Name="RefreshBtn" Style="{StaticResource PrimaryBtn}" Content="Refresh now"/>
        <Button x:Name="ExpandBtn" Style="{StaticResource GhostBtn}" Content="Expand all"/>
        <Button x:Name="CollapseBtn" Style="{StaticResource GhostBtn}" Content="Collapse all"/>
      </StackPanel>
      <StackPanel>
        <TextBlock Text="BIM Brother · Links" FontSize="22" FontWeight="SemiBold"/>
        <Grid HorizontalAlignment="Left" Width="480" Margin="0,10,0,0">
          <Button x:Name="PickerBtn" Style="{StaticResource PickerBtn}" Height="46">
            <DockPanel>
              <TextBlock DockPanel.Dock="Right" Text="&#x25BE;" Foreground="#A8A8A8" FontSize="14" VerticalAlignment="Center"/>
              <StackPanel>
                <TextBlock x:Name="PickerName" FontWeight="SemiBold" TextTrimming="CharacterEllipsis"/>
                <TextBlock x:Name="PickerSub" FontSize="11" Foreground="#A8A8A8" Margin="0,2,0,0" TextTrimming="CharacterEllipsis"/>
              </StackPanel>
            </DockPanel>
          </Button>
          <Popup x:Name="LinkPopup" PlacementTarget="{Binding ElementName=PickerBtn}" Placement="Bottom"
                 StaysOpen="False" AllowsTransparency="True" VerticalOffset="4">
            <Border Background="#262626" BorderBrush="#525252" BorderThickness="1" CornerRadius="4" Padding="8" Width="480">
              <StackPanel>
                <Grid Margin="0,0,0,8">
                  <TextBox x:Name="LinkSearch" Height="34" Padding="10,0" VerticalContentAlignment="Center"
                           Background="#161616" Foreground="#F4F4F4" BorderBrush="#525252" CaretBrush="#F4F4F4"/>
                  <TextBlock x:Name="LinkSearchHint" Text="Search links..." Foreground="#6F6F6F"
                             Margin="12,0,0,0" VerticalAlignment="Center" IsHitTestVisible="False"/>
                </Grid>
                <ScrollViewer MaxHeight="340" VerticalScrollBarVisibility="Auto">
                  <StackPanel x:Name="LinkList"/>
                </ScrollViewer>
              </StackPanel>
            </Border>
          </Popup>
        </Grid>
        <TextBlock x:Name="DocText" Foreground="#A8A8A8" Margin="0,8,0,0" TextTrimming="CharacterEllipsis"/>
      </StackPanel>
    </DockPanel>

    <Border Grid.Row="1" Background="#262626" CornerRadius="6" Padding="12" Margin="0,16,0,14">
      <DockPanel>
        <ToggleButton x:Name="SortTimeBtn" DockPanel.Dock="Right" Style="{StaticResource ChipBtn}"
                      Content="Sort by time" Margin="14,0,0,0" VerticalAlignment="Center"/>
        <Grid DockPanel.Dock="Left" Width="320" Margin="0,0,14,0">
          <TextBox x:Name="SearchBox" Height="34" Padding="10,0" VerticalContentAlignment="Center"
                   Background="#161616" Foreground="#F4F4F4" BorderBrush="#525252" CaretBrush="#F4F4F4"/>
          <TextBlock x:Name="SearchHint" Text="Filter by ID, type, user, change..." Foreground="#6F6F6F"
                     Margin="12,0,0,0" VerticalAlignment="Center" IsHitTestVisible="False"/>
        </Grid>
        <WrapPanel VerticalAlignment="Center">
          <ToggleButton x:Name="ChipAll" Style="{StaticResource ChipBtn}" IsChecked="True"/>
          <ToggleButton x:Name="ChipNew" Style="{StaticResource ChipBtn}"/>
          <ToggleButton x:Name="ChipDeleted" Style="{StaticResource ChipBtn}"/>
          <ToggleButton x:Name="ChipMoved" Style="{StaticResource ChipBtn}"/>
          <ToggleButton x:Name="ChipResized" Style="{StaticResource ChipBtn}"/>
          <ToggleButton x:Name="ChipData" Style="{StaticResource ChipBtn}"/>
        </WrapPanel>
      </DockPanel>
    </Border>

    <Grid Grid.Row="2">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="16"/>
        <ColumnDefinition Width="400"/>
      </Grid.ColumnDefinitions>
      <Border Grid.Column="0" Background="#262626" CornerRadius="6" Padding="8">
        <ScrollViewer VerticalScrollBarVisibility="Auto">
          <StackPanel x:Name="TreePanel"/>
        </ScrollViewer>
      </Border>
      <Border Grid.Column="2" Background="#262626" CornerRadius="6" Padding="18">
        <ScrollViewer VerticalScrollBarVisibility="Auto">
          <StackPanel x:Name="DetailPanel"/>
        </ScrollViewer>
      </Border>
    </Grid>

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
# REPORT WINDOW
# =============================================================================
class ReportWindow(object):

    def __init__(self, links, start_link):
        self.links = links
        self.link = None
        self.reg, self.reg_path = {}, None
        self.win = XamlReader.Parse(XAML)
        find = self.win.FindName
        self.tree_panel = find("TreePanel")
        self.detail_panel = find("DetailPanel")
        self.search = find("SearchBox")
        self.hint = find("SearchHint")
        self.status_text = find("StatusText")
        self.status_dot = find("StatusDot")
        self.doc_text = find("DocText")
        self.chips = {
            "All": find("ChipAll"), ct.NEW: find("ChipNew"), ct.DELETED: find("ChipDeleted"),
            ct.MOVED: find("ChipMoved"), ct.RESIZED: find("ChipResized"), ct.DATA: find("ChipData"),
        }

        self.kind = "All"
        self.query = u""
        self.records = []
        self.nodes = []
        self.sel_uid = None
        self.sel_btn = None
        self.sort_time = False
        self.cycle_uid = None          # card whose views are being cycled
        self.cycle_seen = set()        # view ids already visited for that card

        self.sort_btn = find("SortTimeBtn")
        self.sort_btn.Click += RoutedEventHandler(self.on_sort_toggle)
        find("RefreshBtn").Click += RoutedEventHandler(self.on_refresh)
        find("ExpandBtn").Click += RoutedEventHandler(self.on_expand_all)
        find("CollapseBtn").Click += RoutedEventHandler(self.on_collapse_all)
        for key, chip in self.chips.items():
            chip.Click += RoutedEventHandler(self._chip_handler(key))
        self.search.TextChanged += self.on_search_changed

        self.timer = DispatcherTimer()
        self.timer.Interval = TimeSpan.FromMilliseconds(250)
        self.timer.Tick += EventHandler(self.on_timer)

        # link picker
        self.picker_btn = find("PickerBtn")
        self.picker_name = find("PickerName")
        self.picker_sub = find("PickerSub")
        self.popup = find("LinkPopup")
        self.link_search = find("LinkSearch")
        self.link_hint = find("LinkSearchHint")
        self.link_list = find("LinkList")
        self.stop_btn = find("StopBtn")
        self.popup_closed_at = DateTime.MinValue
        self.picker_btn.Click += RoutedEventHandler(self.on_picker_click)
        self.popup.Closed += EventHandler(self.on_popup_closed)
        self.link_search.TextChanged += self.on_link_search_changed
        self.stop_btn.Click += RoutedEventHandler(self.on_stop)
        self.scan_all_btn = find("ScanAllBtn")
        self.scan_all_btn.Click += RoutedEventHandler(self.on_scan_all)
        self.busy = False

        self.set_link(start_link)

    # ------------------------------------------------------------------ state
    def set_link(self, link):
        """Show a link's report (None = nothing picked yet)."""
        self.link = link
        self.sel_uid, self.sel_btn = None, None
        if link is not None and link["monitored"]:
            self.reg, self.reg_path = lt.load_link_register(link)
            self.reg = self.reg or {}
        else:
            self.reg, self.reg_path = {}, None
        self.update_picker()
        self.load_state()

    def update_picker(self):
        stale = len(self._stale_links())
        self.scan_all_btn.Visibility = Visibility.Visible if stale else Visibility.Collapsed
        self.scan_all_btn.Content = u"Scan all stale ({0})".format(stale)
        if self.link is None:
            self.picker_name.Text = u"Choose a link to monitor"
            self.picker_sub.Text = u"{0} loaded link(s) in {1}".format(len(self.links), doc.Title)
            self.stop_btn.Visibility = Visibility.Collapsed
            return
        self.picker_name.Text = self.link["name"]
        self.picker_sub.Text = self._link_sub(self.link)
        self.stop_btn.Visibility = Visibility.Visible if self.link["monitored"] else Visibility.Collapsed

    def _link_sub(self, link):
        n = len(link["instances"])
        inst = u"1 instance" if n == 1 else u"{0} instances".format(n)
        if not link["monitored"]:
            return u"Not monitored{0}{1}{0}select to start watching".format(SEP, inst)
        if link.get("stale"):
            return u"Monitored{0}{1}{0}new version, not scanned yet".format(SEP, inst)
        last = link.get("last_refresh") or {}
        when = ct.fmt_time(last.get("time")) if last else u"\u2014"
        took = last.get("seconds_total") or last.get("seconds")
        took = u" ({0} s)".format(took) if took is not None else u""
        return u"Monitored{0}{1}{0}last scan {2}{3}".format(SEP, inst, when, took)

    def _stale_links(self):
        return [l for l in self.links if l["monitored"] and l.get("stale")]

    def load_state(self):
        self.records = list((self.reg.get("changes") or {}).values())
        if self.link is None:
            self.doc_text.Text = u"Pick a link above. Its changes are recorded every time it is reloaded."
        else:
            self.doc_text.Text = u"Host: {0}{1}{2}".format(
                doc.Title, SEP, os.path.basename(self.reg_path) if self.reg_path else u"no register yet")

        counts = dict((k, 0) for k in ct.KIND_ORDER)
        for rec in self.records:
            for k in rec.get("kinds") or []:
                if k in counts:
                    counts[k] += 1
        for key, label in CHIP_LABELS:
            n = len(self.records) if key == "All" else counts[key]
            self.chips[key].Content = u"{0}   {1}".format(label, n)

        last = self.reg.get("last_refresh") or {}
        if self.link is None:
            self.set_status(u"Waiting for a link to watch.", WARN)
        elif last:
            self.set_status(u"Last refresh: {0}{1}{2}{1}{3} elements scanned in {4} s".format(
                last.get("trigger"), SEP, ct.fmt_time(last.get("time")),
                last.get("scanned"), last.get("seconds")))
        self.rebuild()
        self.show_placeholder()

    def visible_records(self):
        q = self.query.lower()
        out = []
        for rec in self.records:
            if self.kind != "All" and self.kind not in (rec.get("kinds") or []):
                continue
            if q:
                hay = u" ".join(
                    [unicode(rec.get(f) or u"") for f in
                     ("id", "cat", "fam", "typ", "summary", "created_by", "modified_by", "trigger")]
                    + [u" ".join(unicode(x) for x in d) for d in rec.get("details") or []]
                ).lower()
                if q not in hay:
                    continue
            out.append(rec)
        out.sort(key=lambda r: r.get("detected") or u"")       # chronological
        return out

    # ------------------------------------------------------------------- tree
    def rebuild(self):
        self.tree_panel.Children.Clear()
        self.nodes = []
        self.sel_btn = None
        recs = self.visible_records()
        if not recs:
            if self.link is None:
                msg = u"Choose a link from the dropdown above to start monitoring it."
            elif not self.records:
                msg = (u"No changes recorded yet. They appear once a newer version of the link "
                       u"is loaded and scanned here, or on Refresh now.")
            else:
                msg = u"No changes match this filter."
            self.tree_panel.Children.Add(tb(msg, 13, SUB, margin=Thickness(16), wrap=True))
            return

        if self.sort_time:
            # flat list, most recent first, regardless of category / family / type
            for rec in reversed(recs):
                self.tree_panel.Children.Add(self.make_row(rec, flat=True))
            return

        groups = {}
        for rec in recs:
            groups.setdefault(rec.get("cat") or u"\u2014", {}) \
                  .setdefault(rec.get("fam") or u"\u2014", {}) \
                  .setdefault(rec.get("typ") or u"\u2014", []).append(rec)

        for cat in sorted(groups):
            fams = groups[cat]
            total = sum(len(r) for f in fams.values() for r in f.values())
            container, node = self.make_header(0, u"Category", cat, total, self._families_builder(fams))
            self.tree_panel.Children.Add(container)
            self.nodes.append(node)

        if len(recs) <= AUTO_EXPAND_LIMIT:
            self.on_expand_all(None, None)

    def make_header(self, level, label, name, count, builder):
        indent = (0, 22, 44)[level]
        btn = Button()
        btn.Style = self.win.FindResource("HeadBtn")
        btn.Background = br(SURFACE) if level == 0 else Brushes.Transparent
        btn.Padding = Thickness(10 + indent, 9 if level == 0 else 7, 12, 9 if level == 0 else 7)
        btn.Margin = Thickness(0, 4 if level == 0 else 1, 0, 0)

        row = DockPanel()
        cnt = tb(count_text(count), 12, SUB)
        DockPanel.SetDock(cnt, Dock.Right)
        row.Children.Add(cnt)
        left = StackPanel()
        left.Orientation = Orientation.Horizontal
        chev = tb(CHEV_CLOSED, 12, SUB, margin=Thickness(0, 0, 8, 0))
        left.Children.Add(chev)
        left.Children.Add(tb(label.upper(), 10, SUB, margin=Thickness(0, 0, 8, 0)))
        left.Children.Add(tb(name, 14 if level == 0 else 13, TEXT, bold=(level < 2)))
        row.Children.Add(left)
        btn.Content = row

        children = StackPanel()
        children.Visibility = Visibility.Collapsed
        container = StackPanel()
        container.Children.Add(btn)
        container.Children.Add(children)

        node = {"chev": chev, "children": children, "built": False, "open": False,
                "build": builder, "subnodes": []}
        btn.Click += RoutedEventHandler(lambda s, e: self.toggle(node))
        return container, node

    def toggle(self, node, force=None):
        opened = (not node["open"]) if force is None else force
        if opened and not node["built"]:
            node["subnodes"] = node["build"](node["children"]) or []
            node["built"] = True
        node["children"].Visibility = Visibility.Visible if opened else Visibility.Collapsed
        node["chev"].Text = CHEV_OPEN if opened else CHEV_CLOSED
        node["open"] = opened

    def _families_builder(self, fams):
        def build(panel):
            nodes = []
            for fam in sorted(fams):
                types = fams[fam]
                total = sum(len(r) for r in types.values())
                container, node = self.make_header(1, u"Family", fam, total, self._types_builder(types))
                panel.Children.Add(container)
                nodes.append(node)
            return nodes
        return build

    def _types_builder(self, types):
        def build(panel):
            nodes = []
            for typ in sorted(types):
                recs = types[typ]
                container, node = self.make_header(2, u"Type", typ, len(recs), self._rows_builder(recs))
                panel.Children.Add(container)
                nodes.append(node)
            return nodes
        return build

    def _rows_builder(self, recs):
        def build(panel):
            for rec in recs:
                panel.Children.Add(self.make_row(rec))
            return []
        return build

    def make_row(self, rec, flat=False):
        btn = Button()
        btn.Style = self.win.FindResource("RowBtn")
        btn.Margin = Thickness(0 if flat else 70, 2, 0, 2)
        btn.Padding = Thickness(12, 9, 12, 9)
        self._paint_row(btn, rec.get("uid") == self.sel_uid)
        if rec.get("uid") == self.sel_uid:
            self.sel_btn = btn

        body = StackPanel()
        line1 = WrapPanel()
        for k in ordered_kinds(rec):
            line1.Children.Add(badge(k))
        line1.Children.Add(tb(u"{0} ({1})".format(ct.noun(rec.get("cat")), rec.get("id")), 13, TEXT, True,
                              Thickness(2, 0, 10, 0)))
        line1.Children.Add(tb(rec.get("summary"), 13, TEXT))
        body.Children.Add(line1)

        if flat:
            body.Children.Add(tb(u"{0} \u203A {1} \u203A {2}".format(
                rec.get("cat"), rec.get("fam"), rec.get("typ")), 12, SUB, margin=Thickness(0, 4, 0, 0)))

        line2 = WrapPanel()
        line2.Margin = Thickness(0, 6, 0, 0)
        meta = [u"Created By: {0}".format(rec.get("created_by") or u"\u2014"),
                u"Modified By: {0}".format(rec.get("modified_by") or u"\u2014"),
                u"Detected: {0}".format(ct.fmt_time(rec.get("detected")))]
        for m in meta:
            line2.Children.Add(tb(m, 12, SUB, margin=Thickness(0, 0, 18, 0)))
        left = ct.days_left(rec)
        if left is not None:
            line2.Children.Add(tb(u"Expires today" if left == 0 else u"Expires in {0} days".format(left),
                                  12, "#FF8389"))
        body.Children.Add(line2)

        btn.Content = body
        btn.Click += RoutedEventHandler(lambda s, e: self.select(rec, s))
        return btn

    def _paint_row(self, btn, selected):
        btn.Background = br(SELECTED_BG if selected else SURFACE)
        btn.BorderBrush = br(ACCENT if selected else SURFACE)

    # -------------------------------------------------------------- selection
    def select(self, rec, btn):
        if self.sel_btn is not None:
            self._paint_row(self.sel_btn, False)
        self._paint_row(btn, True)
        self.sel_btn, self.sel_uid = btn, rec.get("uid")
        self.render_detail(rec)
        self.go_to(rec)

    def _instance(self):
        return self.link["instances"][0] if self.link and self.link["instances"] else None

    def _host_box(self, bb):
        """Box in link coordinates -> padded (min, max) XYZ in host coordinates."""
        inst = self._instance()
        if not bb or inst is None:
            return None
        t = inst.GetTotalTransform()
        pts = [t.OfPoint(XYZ(x, y, z)) for x in (bb[0], bb[3]) for y in (bb[1], bb[4]) for z in (bb[2], bb[5])]
        pad = 3.0
        return (XYZ(min(q.X for q in pts) - pad, min(q.Y for q in pts) - pad, min(q.Z for q in pts) - pad),
                XYZ(max(q.X for q in pts) + pad, max(q.Y for q in pts) + pad, max(q.Z for q in pts) + pad))

    def _open_model_views(self):
        """Open views that can show model geometry, in Revit's open order: [(UIView, View)]."""
        out = []
        for uiv in uidoc.GetOpenUIViews():
            view = doc.GetElement(uiv.ViewId)
            if view is None or view.IsTemplate:
                continue
            if view.ViewType in MODEL_VIEW_TYPES:
                out.append((uiv, view))
        return out

    def _next_view(self, uid, views):
        """First click on a card: the active view. Every further click: the next open view not yet visited."""
        active = ct.eid_value(doc.ActiveView.Id)
        if uid != self.cycle_uid:
            self.cycle_uid, self.cycle_seen = uid, set()
            for i, (_, view) in enumerate(views):
                if ct.eid_value(view.Id) == active:
                    return i
        remaining = [i for i, (_, view) in enumerate(views) if ct.eid_value(view.Id) not in self.cycle_seen]
        if not remaining:                                  # all visited: start a new round
            self.cycle_seen = set()
            remaining = [i for i, (_, view) in enumerate(views) if ct.eid_value(view.Id) != active] or [0]
        return remaining[0]

    def zoom_cycle(self, rec, bb, label):
        """Zoom the element in one open view per click, activating that view."""
        box = self._host_box(bb)
        views = self._open_model_views()
        if box is None:
            self.set_status(u"{0} has no stored location to zoom to.".format(label), ERROR)
            return
        if not views:
            self.set_status(u"No open plan, section, elevation or 3D view to zoom in.", WARN)
            return

        i = self._next_view(rec.get("uid"), views)
        uiview, view = views[i]
        self.cycle_seen.add(ct.eid_value(view.Id))
        try:
            if ct.eid_value(view.Id) != ct.eid_value(doc.ActiveView.Id):
                uidoc.ActiveView = view
            for uiv in uidoc.GetOpenUIViews():              # re-fetch: activation can replace UIView objects
                if ct.eid_value(uiv.ViewId) == ct.eid_value(view.Id):
                    uiview = uiv
                    break
            uiview.ZoomAndCenterRectangle(box[0], box[1])
        except Exception as ex:
            ct.log_error("zoom cycle")
            self.set_status(u"Could not zoom in {0}: {1}".format(view.Name, ex), ERROR)
            return

        more = u"click the card again for the next open view" if len(views) > 1 else u"only open model view"
        prefix = (u"{0} no longer exists (last known location)".format(label)
                  if ct.DELETED in (rec.get("kinds") or []) else label)
        self.set_status(u"{0}{1}view {2} of {3}: {4}{1}{5}".format(
            prefix, SEP, i + 1, len(views), view.Name, more),
            ERROR if ct.DELETED in (rec.get("kinds") or []) else OK)

    def go_to(self, rec):
        """Card click: zoom only, cycling through the open views on repeated clicks."""
        label = u"{0} {1}".format(ct.noun(rec.get("cat")), rec.get("id"))
        if ct.DELETED in (rec.get("kinds") or []):
            self.zoom_cycle(rec, rec.get("bb"), label)
            return
        link_el = self.link["doc"].GetElement(rec.get("uid"))
        if link_el is None:
            self.set_status(u"{0} is no longer in the loaded link. Refresh to update the register.".format(label), WARN)
            return
        self.zoom_cycle(rec, ct._bbox(link_el), label)

    def pick_element(self, rec):
        """Detail button: select the linked element so Revit highlights it."""
        label = u"{0} {1}".format(ct.noun(rec.get("cat")), rec.get("id"))
        link_el = self.link["doc"].GetElement(rec.get("uid"))
        if link_el is None:
            self.set_status(u"{0} is no longer in the loaded link. Refresh to update the register.".format(label), WARN)
            return
        try:
            refs = List[Reference]()
            refs.Add(Reference(link_el).CreateLinkReference(self._instance()))
            uidoc.Selection.SetReferences(refs)
            self.set_status(u"Picked {0} in the link{1}highlighted in every view that shows it".format(label, SEP))
        except Exception as ex:
            ct.log_error("pick linked element")
            self.set_status(u"Could not pick {0}: {1}".format(label, ex), ERROR)

    # ----------------------------------------------------------------- detail
    def show_placeholder(self):
        self.detail_panel.Children.Clear()
        self.detail_panel.Children.Add(
            tb(u"Select an element to see what changed and jump to it in the model.", 13, SUB, wrap=True))

    def render_detail(self, rec):
        p = self.detail_panel
        p.Children.Clear()

        badges = WrapPanel()
        for k in ordered_kinds(rec):
            badges.Children.Add(badge(k))
        p.Children.Add(badges)
        p.Children.Add(tb(u"{0} ({1})".format(ct.noun(rec.get("cat")), rec.get("id")), 18, TEXT, True,
                          Thickness(0, 10, 0, 2)))
        p.Children.Add(tb(u"{0} \u203A {1} \u203A {2}".format(rec.get("cat"), rec.get("fam"), rec.get("typ")),
                          12, SUB, wrap=True))
        p.Children.Add(tb(rec.get("summary"), 14, TEXT, margin=Thickness(0, 10, 0, 0), wrap=True))

        if ct.DELETED in (rec.get("kinds") or []):
            note = Border()
            note.Background = br("#2D0709")
            note.CornerRadius = CornerRadius(4)
            note.Padding = Thickness(12, 10, 12, 10)
            note.Margin = Thickness(0, 12, 0, 0)
            left = ct.days_left(rec)
            expiry = u"" if left is None else u" It leaves the register in {0} days.".format(left)
            note.Child = tb(u"This element no longer exists. Selecting it zooms the active view to its "
                            u"last known location." + expiry, 12, "#FFB3B8", wrap=True)
            p.Children.Add(note)

        p.Children.Add(section(u"What changed"))
        details = rec.get("details") or []
        if not details:
            p.Children.Add(tb(u"Element created.", 13, SUB))
        for field, old, new in details:
            box = Border()
            box.Background = br(SURFACE)
            box.CornerRadius = CornerRadius(4)
            box.Padding = Thickness(12, 8, 12, 8)
            box.Margin = Thickness(0, 0, 0, 4)
            inner = StackPanel()
            inner.Children.Add(tb(field, 11, SUB))
            value = new if not old else u"{0}  \u2192  {1}".format(old, new)
            inner.Children.Add(tb(value, 13, TEXT, margin=Thickness(0, 2, 0, 0), wrap=True))
            box.Child = inner
            p.Children.Add(box)

        grid = UniformGrid()
        grid.Columns = 2
        grid.Margin = Thickness(0, 14, 0, 0)
        for label, value in ((u"Created By", rec.get("created_by")),
                             (u"Modified By", rec.get("modified_by")),
                             (u"Detected", ct.fmt_time(rec.get("detected"))),
                             (u"Detected On", rec.get("trigger"))):
            cell = StackPanel()
            cell.Margin = Thickness(0, 0, 8, 10)
            cell.Children.Add(tb(label.upper(), 11, SUB, True))
            cell.Children.Add(tb(value or u"\u2014", 13, TEXT, margin=Thickness(0, 2, 0, 0), wrap=True))
            grid.Children.Add(cell)
        p.Children.Add(grid)

        history = rec.get("history") or []
        if history:
            p.Children.Add(section(u"Earlier changes"))
            for h in history:
                p.Children.Add(tb(u"{0}{1}{2}{1}{3}".format(
                    ct.fmt_time(h.get("detected")), SEP, h.get("summary") or u"\u2014",
                    h.get("modified_by") or u"\u2014"), 12, SUB, margin=Thickness(0, 0, 0, 4), wrap=True))

        if ct.DELETED not in (rec.get("kinds") or []):
            pick = Button()
            pick.Style = self.win.FindResource("PrimaryBtn")
            pick.Margin = Thickness(0, 16, 0, 0)
            pick.HorizontalAlignment = HorizontalAlignment.Left
            pick.Content = u"Pick Element"
            pick.Click += RoutedEventHandler(lambda s, e: self.pick_element(rec))
            p.Children.Add(pick)

    # ----------------------------------------------------------------- events
    def _chip_handler(self, key):
        def handler(sender, args):
            self.kind = key
            for k, chip in self.chips.items():
                chip.IsChecked = (k == key)
            self.rebuild()
        return handler

    def on_sort_toggle(self, sender, args):
        self.sort_time = bool(self.sort_btn.IsChecked)
        self.rebuild()

    def on_search_changed(self, sender, args):
        self.hint.Visibility = Visibility.Collapsed if self.search.Text else Visibility.Visible
        self.timer.Stop()
        self.timer.Start()

    def on_timer(self, sender, args):
        self.timer.Stop()
        self.query = self.search.Text or u""
        self.rebuild()

    def on_expand_all(self, sender, args):
        def expand(node):
            self.toggle(node, True)
            for sub in node["subnodes"]:
                expand(sub)
        for node in self.nodes:
            expand(node)

    def on_collapse_all(self, sender, args):
        for node in self.nodes:
            self.toggle(node, False)

    def _reload_links(self, keep_uid):
        self.links = lt.list_links(doc)
        for link in self.links:
            if link["type_uid"] == keep_uid:
                return link
        return None

    def on_refresh(self, sender, args):
        if self.link is not None:
            self.scan([self.link], lt.TRIGGER_MANUAL, force=True)

    def on_scan_all(self, sender, args):
        stale = self._stale_links()
        if stale:
            self.scan(stale, lt.TRIGGER_REPORT)

    # ------------------------------------------------------------------- scan
    def run_later(self, fn):
        """Queue work below render priority, so the status bar repaints before Revit gets busy."""
        self.win.Dispatcher.BeginInvoke(DispatcherPriority.Background, Action(fn))

    def scan(self, links, trigger, force=False, start=False, show_uid=None):
        """Scan links one after another, repainting the status between them."""
        if self.busy or not links:
            return
        self.busy = True
        queue = list(links)
        total = len(queue)
        keep = show_uid or (self.link["type_uid"] if self.link else None)
        state = {"n": 0, "errors": [], "t0": time.time()}

        def step():
            if not queue:
                finish()
                return
            link = queue.pop(0)
            state["n"] += 1
            self.set_status(u"Scanning {0} ({1} of {2}){3}Revit stays busy until it finishes".format(
                link["name"], state["n"], total, SEP), WARN)
            Mouse.OverrideCursor = Cursors.Wait

            def work():
                try:
                    if start:
                        lt.start_monitoring(doc, link)
                    else:
                        lt.refresh_link(doc, link, trigger, force=force)
                except Exception:
                    ct.log_error(u"link scan: " + link["name"])
                    state["errors"].append(link["name"])
                self.run_later(step)
            self.run_later(work)

        def finish():
            Mouse.OverrideCursor = None
            self.busy = False
            self.set_link(self._reload_links(keep) if keep else None)
            took = round(time.time() - state["t0"], 1)
            if state["errors"]:
                self.set_status(u"Scan failed for: {0} (see tracker_errors.log)".format(
                    u", ".join(state["errors"])), ERROR)
            elif start:
                self.set_status(u"Now watching {0}. Baseline captured in {1} s{2}changes appear once a newer "
                                u"version of the link is loaded.".format(links[0]["name"], took, SEP))
            else:
                self.set_status(u"Scanned {0} link(s) in {1} s".format(total, took))

        self.run_later(step)

    def on_stop(self, sender, args):
        if self.link is None:
            return
        answer = MessageBox.Show(
            self.win,
            u"Stop monitoring {0}?\n\nIt will no longer refresh automatically from this project. "
            u"Its register file is kept, so picking it again later continues from where it left off."
            .format(self.link["name"]),
            u"BIM Brother", MessageBoxButton.YesNo)
        if answer != MessageBoxResult.Yes:
            return
        lt.stop_monitoring(doc, self.link["type_uid"])
        name = self.link["name"]
        self.links = lt.list_links(doc)
        self.set_link(None)
        self.set_status(u"Stopped monitoring {0}.".format(name), WARN)

    # ----------------------------------------------------------------- picker
    def on_picker_click(self, sender, args):
        # a click on the button while open closes the popup first; don't reopen it
        if (DateTime.Now - self.popup_closed_at).TotalMilliseconds < 250:
            return
        self.link_search.Text = u""
        self.build_link_list()
        self.popup.IsOpen = True
        self.link_search.Focus()

    def on_popup_closed(self, sender, args):
        self.popup_closed_at = DateTime.Now

    def on_link_search_changed(self, sender, args):
        self.link_hint.Visibility = Visibility.Collapsed if self.link_search.Text else Visibility.Visible
        self.build_link_list()

    def build_link_list(self):
        self.link_list.Children.Clear()
        q = (self.link_search.Text or u"").lower()
        shown = [l for l in self.links if not q or q in l["name"].lower()]
        if not shown:
            self.link_list.Children.Add(tb(u"No loaded link matches." if self.links
                                           else u"This project has no loaded Revit links.",
                                           12, SUB, margin=Thickness(8)))
            return
        for link in shown:
            current = self.link is not None and link["type_uid"] == self.link["type_uid"]
            btn = Button()
            btn.Style = self.win.FindResource("RowBtn")
            btn.Margin = Thickness(0, 0, 0, 4)
            btn.Padding = Thickness(12, 8, 12, 8)
            self._paint_row(btn, current)
            body = StackPanel()
            top = WrapPanel()
            top.Children.Add(tb(link["name"], 13, TEXT, True, Thickness(0, 0, 8, 0)))
            if link["monitored"]:
                tag = Border()
                tag.Background = br("#0E6027")
                tag.CornerRadius = CornerRadius(10)
                tag.Padding = Thickness(8, 1, 8, 2)
                tag.VerticalAlignment = VerticalAlignment.Center
                tag.Child = tb(u"WATCHING", 10, "#A7F0BA", True)
                top.Children.Add(tag)
            if link.get("stale"):
                new = Border()
                new.Background = br(ACCENT)
                new.CornerRadius = CornerRadius(10)
                new.Padding = Thickness(8, 1, 8, 2)
                new.Margin = Thickness(6, 0, 0, 0)
                new.VerticalAlignment = VerticalAlignment.Center
                new.Child = tb(u"NEW VERSION", 10, BG, True)
                top.Children.Add(new)
            body.Children.Add(top)
            body.Children.Add(tb(self._link_sub(link), 11, SUB, margin=Thickness(0, 3, 0, 0)))
            btn.Content = body
            btn.Click += RoutedEventHandler(self._pick_handler(link))
            self.link_list.Children.Add(btn)

    def _pick_handler(self, link):
        def handler(sender, args):
            self.popup.IsOpen = False
            self.pick(link)
        return handler

    def pick(self, link):
        if not link["monitored"]:
            self.scan([link], lt.TRIGGER_MONITOR, start=True, show_uid=link["type_uid"])
            return
        lt.set_last_picked(doc, link["type_uid"])
        self.set_link(link)                                   # show what is already recorded right away
        if link.get("stale"):
            self.scan([link], lt.TRIGGER_REPORT, show_uid=link["type_uid"])

    def set_status(self, text, color=OK):
        self.status_text.Text = text
        self.status_dot.Fill = br(color)

    # ------------------------------------------------------------------- show
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
        if self.link is not None and self.link.get("stale"):   # the link on screen catches up first
            self.scan([self.link], lt.TRIGGER_REPORT)
        Dispatcher.PushFrame(frame)


# =============================================================================
# ENTRY
# =============================================================================
def open_location():
    lt._ensure_dir()
    target = None
    try:
        data = lt.load_monitored(doc)
        info = data["links"].get(data.get("last") or u"") or {}
        if info.get("register"):
            candidate = os.path.join(lt.LINK_DIR, info["register"])
            if os.path.exists(candidate):
                target = candidate
    except Exception:
        ct.log_error("links: open location")
    if target:
        Process.Start("explorer.exe", u'/select,"{0}"'.format(target))
    else:
        Process.Start("explorer.exe", u'"{0}"'.format(lt.LINK_DIR))


def show_report():
    links = lt.list_links(doc)
    if not links:
        TaskDialog.Show("BIM Brother", "This project has no loaded Revit links to monitor.")
        return
    data = lt.load_monitored(doc)
    start = None
    for link in links:
        if link["type_uid"] == data.get("last") and link["monitored"]:
            start = link
            break
    if start is None:
        start = next((l for l in links if l["monitored"]), None)
    ReportWindow(links, start).show()


def main():
    try:
        shift = __shiftclick__
    except NameError:
        shift = False

    if doc.IsFamilyDocument:
        TaskDialog.Show("BIM Brother", "BIM Brother works on project documents only.")
        return
    if shift:
        open_location()
    else:
        show_report()


main()
# -*- coding: utf-8 -*-

__author__ = "Mohamed Bedair"
__doc__ = """Change report for the active document: New, Deleted, Moved, Resized and Data changes.
Click: open the report.
Shift+Click: open the register file location."""

import os
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
    FontWeights, CornerRadius, TextTrimming, RoutedEventHandler
)
from System.Windows.Controls import (
    Button, StackPanel, TextBlock, Border, DockPanel, Dock, WrapPanel, Orientation
)
from System.Windows.Controls.Primitives import UniformGrid
from System.Windows.Markup import XamlReader
from System.Windows.Media import BrushConverter, Brushes
from System.Windows.Input import Mouse, Cursors
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Threading import Dispatcher, DispatcherFrame, DispatcherTimer

from Autodesk.Revit.DB import ElementId, XYZ
from Autodesk.Revit.UI import TaskDialog

import change_tracker as ct

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
        Title="Change Tracker" Width="1240" Height="820" MinWidth="940" MinHeight="560"
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
        <Button x:Name="RefreshBtn" Style="{StaticResource PrimaryBtn}" Content="Refresh now"/>
        <Button x:Name="ExpandBtn" Style="{StaticResource GhostBtn}" Content="Expand all"/>
        <Button x:Name="CollapseBtn" Style="{StaticResource GhostBtn}" Content="Collapse all"/>
      </StackPanel>
      <StackPanel>
        <TextBlock Text="Change Tracker" FontSize="22" FontWeight="SemiBold"/>
        <TextBlock x:Name="DocText" Foreground="#A8A8A8" Margin="0,4,0,0" TextTrimming="CharacterEllipsis"/>
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

    def __init__(self, reg, reg_path):
        self.reg, self.reg_path = reg, reg_path
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

        self.load_state()

    # ------------------------------------------------------------------ state
    def load_state(self):
        self.records = list((self.reg.get("changes") or {}).values())
        self.doc_text.Text = u"{0}{1}{2}".format(
            self.reg.get("doc_title") or doc.Title, SEP, os.path.basename(self.reg_path))

        counts = dict((k, 0) for k in ct.KIND_ORDER)
        for rec in self.records:
            for k in rec.get("kinds") or []:
                if k in counts:
                    counts[k] += 1
        for key, label in CHIP_LABELS:
            n = len(self.records) if key == "All" else counts[key]
            self.chips[key].Content = u"{0}   {1}".format(label, n)

        last = self.reg.get("last_refresh") or {}
        if last:
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
            msg = (u"No changes recorded yet. They appear after the next Sync with Central, "
                   u"Reload Latest, document open, or Refresh now."
                   if not self.records else u"No changes match this filter.")
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

    def go_to(self, rec):
        label = u"{0} {1}".format(ct.noun(rec.get("cat")), rec.get("id"))
        if ct.DELETED in (rec.get("kinds") or []):
            self.zoom_to_last_location(rec, label)
            return
        el = doc.GetElement(rec.get("uid"))
        if el is None:
            self.set_status(u"{0} is no longer in the model. Refresh to update the register.".format(label), WARN)
            return
        ids = List[ElementId]()
        ids.Add(el.Id)
        uidoc.Selection.SetElementIds(ids)
        try:
            uidoc.ShowElements(el.Id)
            self.set_status(u"Selected {0} in Revit{1}view zoomed to element".format(label, SEP))
        except Exception:
            self.set_status(u"Selected {0}, but no open view can show it.".format(label), WARN)

    def zoom_to_last_location(self, rec, label):
        bb = rec.get("bb")
        view = doc.ActiveView
        uiview = None
        for v in uidoc.GetOpenUIViews():
            if ct.eid_value(v.ViewId) == ct.eid_value(view.Id):
                uiview = v
                break
        if not bb or uiview is None:
            self.set_status(u"{0} no longer exists and has no stored location to zoom to.".format(label), ERROR)
            return
        pad = 3.0
        uidoc.Selection.SetElementIds(List[ElementId]())
        uiview.ZoomAndCenterRectangle(XYZ(bb[0] - pad, bb[1] - pad, bb[2] - pad),
                                      XYZ(bb[3] + pad, bb[4] + pad, bb[5] + pad))
        self.set_status(u"{0} no longer exists{1}active view zoomed to its last known location".format(label, SEP),
                        ERROR)

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

        go = Button()
        go.Style = self.win.FindResource("PrimaryBtn")
        go.Margin = Thickness(0, 16, 0, 0)
        go.HorizontalAlignment = HorizontalAlignment.Left
        go.Content = u"Zoom to last location" if ct.DELETED in (rec.get("kinds") or []) else u"Zoom to element"
        go.Click += RoutedEventHandler(lambda s, e: self.go_to(rec))
        p.Children.Add(go)

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

    def on_refresh(self, sender, args):
        Mouse.OverrideCursor = Cursors.Wait
        try:
            ct.refresh(doc, ct.TRIGGER_MANUAL)
            self.reg, self.reg_path = ct.load_register(doc)
            self.load_state()
        except Exception as ex:
            ct.log_error("manual refresh")
            self.set_status(u"Refresh failed: {0}".format(ex), ERROR)
        finally:
            Mouse.OverrideCursor = None

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
        Dispatcher.PushFrame(frame)


# =============================================================================
# ENTRY
# =============================================================================
def run_refresh(trigger):
    Mouse.OverrideCursor = Cursors.Wait
    try:
        ct.refresh(doc, trigger)
        return True
    except Exception as ex:
        ct.log_error("button refresh")
        TaskDialog.Show("Change Tracker", u"Could not build the register:\n{0}".format(ex))
        return False
    finally:
        Mouse.OverrideCursor = None


def open_location():
    reg_path = ct.register_paths(doc)[0]
    if not os.path.exists(reg_path) and not run_refresh(ct.TRIGGER_CREATED):
        return
    Process.Start("explorer.exe", u'/select,"{0}"'.format(reg_path))


def show_report():
    if not ct.register_exists(doc) and not run_refresh(ct.TRIGGER_CREATED):
        return
    reg, reg_path = ct.load_register(doc)
    if reg is None:
        TaskDialog.Show("Change Tracker", "The register for this document could not be read.")
        return
    ReportWindow(reg, reg_path).show()


def main():
    try:
        shift = __shiftclick__
    except NameError:
        shift = False

    if doc.IsFamilyDocument:
        TaskDialog.Show("Change Tracker", "Change Tracker works on project documents only.")
        return
    if shift:
        open_location()
    else:
        show_report()


main()
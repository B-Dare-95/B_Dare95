# -*- coding: utf-8 -*-
"""Family Cleaner result window.

Same build as the Model Health Quick Reports (bd_health_window): a modeless
window in IBM Carbon, an ExternalEvent queue for every Revit call made after the
script has returned, and a pyRevit env var holding the open window so it stays
alive. A new run closes the previous report.

The calling button script needs ``__persistentengine__ = True``.

    show_report(__revit__, title, subtitle, rows, preview, started, notes=[...])

Put this file in B_Dare95.extension/lib/ next to bd_family_cleaner.py.
"""
from collections import Counter, OrderedDict
from datetime import datetime

import clr
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from System import EventHandler, Int64
from System.Collections.Generic import List
from System.Windows import (Clipboard, CornerRadius, FontWeights, HorizontalAlignment, RoutedEventHandler,
                            TextAlignment, TextTrimming, TextWrapping, Thickness, VerticalAlignment,
                            Visibility)
from System.Windows.Controls import (Border, Dock, DockPanel, StackPanel, TextBlock,
                                     TextChangedEventHandler)
from System.Windows.Input import Cursors, MouseButtonEventHandler
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Markup import XamlReader
from System.Windows.Media import BrushConverter, FontFamily

from Autodesk.Revit.DB import ElementId
from Autodesk.Revit.UI import ExternalEvent, IExternalEventHandler

from pyrevit import script
from pyrevit.coreutils import envvars

import bd_family_cleaner as fc

logger = script.get_logger()

SESSION_KEY = "BD_FAMILY_CLEANER_REPORT_SESSION"

# kind -> (background, foreground)
PILLS = {
    "ok":      ("#0E2A18", "#A7F0BA"),
    "preview": ("#0A2350", "#A6C8FF"),
    "warn":    ("#3A2E06", "#FDDC69"),
    "fail":    ("#4A0E12", "#FFB3B8"),
    "plain":   ("#393939", "#C6C6C6"),
}
STATUS_COLORS = {
    "info": ("#262626", "#A8A8A8"),
    "ok":   ("#0E2A18", "#A7F0BA"),
    "warn": ("#3A2E06", "#FDDC69"),
}

_bc = BrushConverter()


def brush(hex_value):
    return _bc.ConvertFromString(hex_value)


def plural(n, word, word_pl=None):
    return u"{0:,} {1}".format(n, word if n == 1 else (word_pl or word + u"s"))


def status_kind(status):
    """(pill kind, short pill text) for a row's full status."""
    s = (status or u"").lower()
    if u"loading it back" in s:
        return "warn", u"Problem"
    if u"failed" in s:
        return "fail", u"Failed"
    if s.startswith(u"rolled back"):
        return "warn", u"Rolled back"
    if u"discarded" in s:
        return "warn", u"Discarded"
    if s.startswith(u"skipped"):
        return "plain", u"Skipped"
    if s.startswith(u"not opened"):
        return "plain", u"Not opened"
    if s.startswith(u"would clean"):
        return "preview", u"Would clean"
    if s.startswith(u"cleaned"):
        return "ok", u"Cleaned"
    if s.startswith(u"nothing to clean, saved"):
        return "plain", u"Copied"
    return "plain", u"Unchanged"


def is_problem(node):
    return status_kind(node.status)[0] in ("fail", "warn") or bool(node.errors)


def breakdown(counter):
    return u", ".join(u"{0} {1}".format(v, k) for k, v in counter.most_common())


def kept_grouped(kept):
    """{reason: [names]} in reason order of frequency."""
    groups = OrderedDict()
    for reason, _ in Counter(kept.values()).most_common():
        groups[reason] = sorted(n for n, r in kept.items() if r == reason)
    return groups


def root_of(node):
    while node.parent is not None:
        node = node.parent
    return node


def report_text(title, subtitle, rows):
    """Plain text of the whole report, for the clipboard."""
    lines = [title, subtitle, u""]
    for n in rows:
        ind = u"    " * n.depth
        lines.append(u"{0}{1}  [{2}]  purged {3}, parameters removed {4}".format(
            ind, n.name, n.status, sum(n.purged.values()), len(n.removed)))
        if n.purged:
            lines.append(u"{0}    purged: {1}".format(ind, breakdown(n.purged)))
        if n.removed:
            lines.append(u"{0}    parameters removed: {1}".format(ind, u", ".join(sorted(n.removed))))
        for reason, names in kept_grouped(n.kept).items():
            lines.append(u"{0}    kept ({1}): {2}".format(ind, reason, u", ".join(names)))
        for e in n.errors:
            lines.append(u"{0}    problem: {1}".format(ind, e))
    return u"\r\n".join(lines)


def get_session():
    try:
        return envvars.get_pyrevit_env_var(SESSION_KEY)
    except Exception:
        return None


def set_session(value):
    try:
        envvars.set_pyrevit_env_var(SESSION_KEY, value)
    except Exception:
        logger.debug("Could not store the Family Cleaner report session.")


class ReportEventHandler(IExternalEventHandler):
    """Runs queued Revit work (selection) inside a valid API context. A queue, not a
    single slot: Revit may merge quick Raise() calls."""

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

    def GetName(self):
        return self.name


# --------------------------------------------------------------------------- UI --
XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Family Cleaner Report" Width="820" Height="800" MinWidth="620" MinHeight="480"
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
    <Style x:Key="PlainRow" TargetType="Border">
      <Setter Property="Background" Value="Transparent"/>
      <Setter Property="BorderBrush" Value="#262626"/>
      <Setter Property="BorderThickness" Value="0,0,0,1"/>
    </Style>
    <Style x:Key="Chip" TargetType="Border">
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
    <Style x:Key="Tile" TargetType="Border">
      <Setter Property="Background" Value="#262626"/>
      <Setter Property="CornerRadius" Value="6"/>
      <Setter Property="Padding" Value="12,8"/>
      <Setter Property="Margin" Value="0,0,8,0"/>
    </Style>
  </Window.Resources>

  <Grid Margin="14">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <DockPanel Grid.Row="0">
      <Button x:Name="btnCopy" DockPanel.Dock="Right" Content="Copy as text"
              ToolTip="Copy the whole report as plain text"/>
      <StackPanel VerticalAlignment="Center">
        <TextBlock x:Name="tbTitle" Text="Family Cleaner" FontSize="18" FontWeight="SemiBold"/>
        <TextBlock x:Name="tbSub" Foreground="#A8A8A8" FontSize="12" Margin="0,2,0,0"
                   TextTrimming="CharacterEllipsis"/>
      </StackPanel>
    </DockPanel>

    <UniformGrid Grid.Row="1" Columns="5" Margin="0,12,-8,0">
      <Border Style="{StaticResource Tile}">
        <StackPanel>
          <TextBlock x:Name="tvFamilies" FontSize="20" FontWeight="SemiBold"/>
          <TextBlock x:Name="tcFamilies" FontSize="11" Foreground="#A8A8A8"/>
        </StackPanel>
      </Border>
      <Border Style="{StaticResource Tile}">
        <StackPanel>
          <TextBlock x:Name="tvOpened" FontSize="20" FontWeight="SemiBold"/>
          <TextBlock x:Name="tcOpened" FontSize="11" Foreground="#A8A8A8"/>
        </StackPanel>
      </Border>
      <Border Style="{StaticResource Tile}">
        <StackPanel>
          <TextBlock x:Name="tvPurged" FontSize="20" FontWeight="SemiBold"/>
          <TextBlock x:Name="tcPurged" FontSize="11" Foreground="#A8A8A8"/>
        </StackPanel>
      </Border>
      <Border Style="{StaticResource Tile}">
        <StackPanel>
          <TextBlock x:Name="tvParams" FontSize="20" FontWeight="SemiBold"/>
          <TextBlock x:Name="tcParams" FontSize="11" Foreground="#A8A8A8"/>
        </StackPanel>
      </Border>
      <Border Style="{StaticResource Tile}">
        <StackPanel>
          <TextBlock x:Name="tvProblems" FontSize="20" FontWeight="SemiBold"/>
          <TextBlock x:Name="tcProblems" FontSize="11" Foreground="#A8A8A8"/>
        </StackPanel>
      </Border>
    </UniformGrid>

    <StackPanel Grid.Row="2">
      <Border x:Name="bdPreview" Visibility="Collapsed" Background="#0A2350" CornerRadius="6"
              Padding="10,8" Margin="0,10,0,0">
        <TextBlock Foreground="#A6C8FF" FontSize="12" TextWrapping="Wrap"
                   Text="Inspection Mode: nothing was changed. Every setting was on, so this is everything a full clean would remove."/>
      </Border>
      <Border x:Name="bdNotes" Visibility="Collapsed" Background="#262626" CornerRadius="6"
              Padding="10,8" Margin="0,10,0,0">
        <TextBlock x:Name="tbNotes" Foreground="#A8A8A8" FontSize="12" TextWrapping="Wrap"/>
      </Border>
    </StackPanel>

    <DockPanel Grid.Row="3" Margin="0,12,0,0">
      <Button x:Name="btnCollapse" DockPanel.Dock="Right" Content="Collapse all" Margin="6,0,0,0"/>
      <Button x:Name="btnExpand" DockPanel.Dock="Right" Content="Expand all" Margin="6,0,0,0"/>
      <CheckBox x:Name="chkZoom" DockPanel.Dock="Right" Content="Zoom to selection" Margin="10,0,4,0"
                ToolTip="Also zoom to the placed copies you select"/>
      <CheckBox x:Name="chkProblems" DockPanel.Dock="Right" Content="Problems only" Margin="10,0,4,0"
                ToolTip="Show only families with a failure, a roll-back or a Revit error"/>
      <CheckBox x:Name="chkChanged" DockPanel.Dock="Right" Content="Changed only" Margin="10,0,4,0"
                ToolTip="Hide families where nothing was removed"/>
      <Grid>
        <TextBox x:Name="txtSearch"/>
        <TextBlock x:Name="tbPlaceholder" Text="Search families and parameters" Foreground="#8D8D8D"
                   Margin="10,0,0,0" VerticalAlignment="Center" IsHitTestVisible="False"/>
      </Grid>
    </DockPanel>

    <Border Grid.Row="4" Margin="0,10,0,0" BorderBrush="#393939" BorderThickness="1" CornerRadius="6">
      <ScrollViewer VerticalScrollBarVisibility="Auto">
        <StackPanel>
          <StackPanel x:Name="spList"/>
          <TextBlock x:Name="tbEmpty" Visibility="Collapsed" Foreground="#8D8D8D" FontSize="12"
                     Margin="14,16" Text="No families match."/>
        </StackPanel>
      </ScrollViewer>
    </Border>

    <Border Grid.Row="5" x:Name="bdStatus" Background="#262626" CornerRadius="6" Padding="10,8" Margin="0,10,0,0">
      <TextBlock x:Name="tbStatus" Foreground="#A8A8A8" FontSize="12" TextWrapping="Wrap"/>
    </Border>

    <DockPanel Grid.Row="6" Margin="0,12,0,0">
      <Button x:Name="btnClose" DockPanel.Dock="Right" Style="{StaticResource Accent}" Content="Close"/>
      <TextBlock x:Name="tbTotals" Foreground="#A8A8A8" FontSize="12" VerticalAlignment="Center"
                 TextTrimming="CharacterEllipsis"/>
    </DockPanel>
  </Grid>
</Window>
"""

UI_NAMES = ["btnCopy", "tbTitle", "tbSub", "tvFamilies", "tcFamilies", "tvOpened", "tcOpened",
            "tvPurged", "tcPurged", "tvParams", "tcParams", "tvProblems", "tcProblems", "bdPreview",
            "bdNotes", "tbNotes", "btnCollapse", "btnExpand", "chkZoom", "chkProblems", "chkChanged",
            "txtSearch", "tbPlaceholder", "spList", "tbEmpty", "bdStatus", "tbStatus", "btnClose",
            "tbTotals"]

HINT = (u"Click a family to see its nested levels, and a nested family to see its result. "
        u"Click a level to fold it. Select picks the placed copies in the model.")


def show_report(uiapp, title, subtitle, rows, preview, started, notes=None):
    """Open the result window. preview = Inspection Mode (nothing was changed)."""
    old = get_session()
    if old:
        try:
            old["window"].Close()
        except Exception:
            pass

    window = XamlReader.Parse(XAML)
    ui = {}
    for name in UI_NAMES:
        ui[name] = window.FindName(name)
    window.Title = title
    ui["tbTitle"].Text = title
    elapsed = u"{0}".format(datetime.now() - started).split(u".")[0]
    ui["tbSub"].Text = u"{0}  ·  {1}  ·  took {2}".format(
        subtitle, started.strftime("%d %b %Y %H:%M"), elapsed)

    uidoc = uiapp.ActiveUIDocument
    doc_title = uidoc.Document.Title if uidoc is not None else u""

    event_handler = ReportEventHandler(u"Family Cleaner Report")
    external_event = ExternalEvent.Create(event_handler)

    def queue(action):
        event_handler.enqueue(action)
        external_event.Raise()

    state = {"groups": []}

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
                logger.error("Family Cleaner report error: {0}".format(ex))
                set_status(u"Something went wrong: {0}".format(ex), "warn")
        return wrapped

    # ------------------------------------------------------------- selection --
    def select_family(node):
        zoom = ui["chkZoom"].IsChecked == True
        set_status(u"Selecting the placed copies of {0}…".format(node.name))

        def action():
            ud = uiapp.ActiveUIDocument
            d = ud.Document if ud is not None else None
            if d is None or d.Title != doc_title:
                set_status(u"This report is for “{0}”. Switch back to it to select.".format(
                    doc_title), "warn")
                return
            fam = fc.find_family(d, None, node.name)
            if fam is None:
                set_status(u"{0} is no longer in this document.".format(node.name), "warn")
                return
            ids = List[ElementId](fc.placed_instance_ids(d, fam))
            if ids.Count == 0:
                set_status(u"{0} has no placed copies here.".format(node.name), "warn")
                return
            ud.Selection.SetElementIds(ids)
            if zoom:
                ud.ShowElements(ids)
            set_status(u"Selected {0} of {1}.".format(plural(ids.Count, u"placed copy", u"placed copies"),
                                                      node.name), "ok")

        queue(action)

    def can_select(node):
        return node.depth == 0 and not status_kind(node.status)[1] in (u"Failed", u"Skipped")

    def make_select_handler(node):
        def handler(sender, args):
            args.Handled = True
            select_family(node)
        return safe(handler)

    # ------------------------------------------------------------- builders --
    def text_block(text, size=13, color="#F4F4F4", bold=False):
        tb = TextBlock()
        tb.Text = text
        tb.FontSize = size
        tb.Foreground = brush(color)
        tb.VerticalAlignment = VerticalAlignment.Center
        if bold:
            tb.FontWeight = FontWeights.SemiBold
        return tb

    def pill(node, small=False):
        kind, text = status_kind(node.status)
        bg, fg = PILLS[kind]
        b = Border()
        b.Background = brush(bg)
        b.CornerRadius = CornerRadius(8)
        b.Padding = Thickness(8, 1, 8, 2)
        b.Margin = Thickness(8, 0, 0, 0)
        b.VerticalAlignment = VerticalAlignment.Center
        b.MinWidth = 0 if small else 84
        t = text_block(text, 10 if small else 11, fg)
        t.HorizontalAlignment = HorizontalAlignment.Center
        b.Child = t
        b.ToolTip = node.status
        return b

    def count_block(n, caption):
        sp = StackPanel()
        sp.VerticalAlignment = VerticalAlignment.Center
        sp.Margin = Thickness(12, 0, 0, 0)
        sp.MinWidth = 76
        big = text_block(u"{0:,}".format(n), 14, "#F4F4F4" if n else "#6F6F6F", bold=True)
        big.HorizontalAlignment = HorizontalAlignment.Right
        small = text_block(caption, 11, "#8D8D8D")
        small.HorizontalAlignment = HorizontalAlignment.Right
        sp.Children.Add(big)
        sp.Children.Add(small)
        return sp

    def select_chip(node):
        chip = Border()
        chip.Style = window.FindResource("Chip")
        chip.Child = text_block(u"Select", 11, "#F4F4F4")
        chip.ToolTip = u"Select its placed copies in the model"
        chip.MouseLeftButtonUp += MouseButtonEventHandler(make_select_handler(node))
        return chip

    def detail_line(label, text, indent, color="#C6C6C6"):
        tb = TextBlock()
        tb.TextWrapping = TextWrapping.Wrap
        tb.FontSize = 12
        tb.Margin = Thickness(indent, 2, 12, 2)
        if label:
            tb.Inlines.Add(_run(label + u"  ", "#8D8D8D"))
        tb.Inlines.Add(_run(text, color))
        return tb

    def node_details(node, indent):
        """The lines under one family: purged, removed, kept, size, problems."""
        lines = []
        removed_word = u"Would remove" if preview else u"Removed"
        if node.purged:
            lines.append(detail_line(u"{0} content".format(removed_word), breakdown(node.purged), indent))
        if node.removed:
            lines.append(detail_line(u"{0} parameters".format(removed_word),
                                     u", ".join(sorted(node.removed)), indent, "#A7F0BA"))
        for reason, names in kept_grouped(node.kept).items():
            lines.append(detail_line(u"Kept ({0})".format(reason), u", ".join(names), indent, "#A8A8A8"))
        for err in node.errors:
            lines.append(detail_line(u"Revit", err, indent, "#FDDC69"))
        if status_kind(node.status)[0] in ("fail", "warn") or (
                node.status and status_kind(node.status)[1] in (u"Not opened", u"Skipped")):
            lines.append(detail_line(u"Status", node.status, indent,
                                     "#FFB3B8" if status_kind(node.status)[0] == "fail" else "#FDDC69"))
        return lines

    def path_block(node):
        """Full path: the parents in grey, the family itself in bold."""
        tb = TextBlock()
        tb.TextTrimming = TextTrimming.CharacterEllipsis
        tb.VerticalAlignment = VerticalAlignment.Center
        tb.FontSize = 13
        if node.parent is not None:
            tb.Inlines.Add(_run(node.parent.path + u"  >  ", "#8D8D8D", 11))
        name = _run(node.name, "#F4F4F4")
        name.FontWeight = FontWeights.SemiBold
        tb.Inlines.Add(name)
        tb.ToolTip = node.path
        return tb

    def make_result_toggle(results, chevron):
        def handler(sender, args):
            is_open = results.Visibility != Visibility.Visible
            results.Visibility = Visibility.Visible if is_open else Visibility.Collapsed
            chevron.Text = u"\u25BE" if is_open else u"\u25B8"
        return safe(handler)

    def family_row(node, left, chip=True):
        """One family: path, pill and counts. Its result lines open on click."""
        r = Border()
        r.Style = window.FindResource("Row")
        r.Padding = Thickness(left, 7, 12, 7)
        holder = StackPanel()
        dp = DockPanel()
        chevron = text_block(u"\u25B8", 11, "#A8A8A8")
        chevron.FontFamily = FontFamily(u"Segoe UI Symbol")
        chevron.Width = 16
        DockPanel.SetDock(chevron, Dock.Left)
        dp.Children.Add(chevron)
        if chip and can_select(node):
            select = select_chip(node)
            DockPanel.SetDock(select, Dock.Right)
            dp.Children.Add(select)
        nums = text_block(u"{0} {1}  \u00b7  {2}".format(
            sum(node.purged.values()), u"to purge" if preview else u"purged",
            plural(len(node.removed), u"param")), 11, "#8D8D8D")
        nums.Margin = Thickness(12, 0, 0, 0)
        DockPanel.SetDock(nums, Dock.Right)
        dp.Children.Add(nums)
        p = pill(node, small=True)
        DockPanel.SetDock(p, Dock.Right)
        dp.Children.Add(p)
        dp.Children.Add(path_block(node))
        holder.Children.Add(dp)

        results = StackPanel()
        results.Visibility = Visibility.Collapsed
        results.Margin = Thickness(0, 4, 0, 2)
        lines = node_details(node, 22)
        if not lines:
            lines = [detail_line(u"", u"Nothing was removed, and no parameters needed checking.", 22, "#8D8D8D")]
        for line in lines:
            results.Children.Add(line)
        holder.Children.Add(results)
        r.Child = holder
        r.ToolTip = u"Click to show or hide the result"
        r.MouseLeftButtonUp += MouseButtonEventHandler(make_result_toggle(results, chevron))
        return r

    def section_head(text, top):
        head = text_block(text, 10, "#F1C21B", bold=True)
        head.Margin = Thickness(30, top, 12, 4)
        return head

    def make_level_toggle(body, chevron):
        def handler(sender, args):
            is_open = body.Visibility != Visibility.Visible
            body.Visibility = Visibility.Visible if is_open else Visibility.Collapsed
            chevron.Text = u"\u25BE" if is_open else u"\u25B8"
        return safe(handler)

    def level_band(depth, nodes):
        """'Level N  ·  k families' with the level's result on the right; folds its families."""
        purged = sum(sum(n.purged.values()) for n in nodes)
        params = sum(len(n.removed) for n in nodes)
        problems = len([n for n in nodes if is_problem(n)])
        not_opened = len([n for n in nodes if n.status.startswith(u"Not opened")])

        band = Border()
        band.Background = brush("#262626")
        band.BorderBrush = brush("#F1C21B")
        band.BorderThickness = Thickness(3, 0, 0, 0)
        band.Padding = Thickness(12, 7, 12, 7)
        band.Margin = Thickness(30, 10, 12, 0)
        band.Cursor = Cursors.Hand
        dp = DockPanel()
        chevron = text_block(u"\u25BE", 11, "#A8A8A8")
        chevron.FontFamily = FontFamily(u"Segoe UI Symbol")
        chevron.Width = 16
        DockPanel.SetDock(chevron, Dock.Left)
        dp.Children.Add(chevron)

        result = TextBlock()
        result.FontSize = 11
        result.VerticalAlignment = VerticalAlignment.Center
        word = u"to purge" if preview else u"purged"
        pword = u"to remove" if preview else u"removed"
        result.Inlines.Add(_run(u"Result: {0} {1}  \u00b7  {2} {3}  \u00b7  ".format(
            purged, word, plural(params, u"param"), pword), "#8D8D8D"))
        result.Inlines.Add(_run(plural(problems, u"problem"), "#FDDC69" if problems else "#8D8D8D"))
        if not_opened:
            result.Inlines.Add(_run(u"  \u00b7  {0} not opened".format(not_opened), "#FDDC69"))
        DockPanel.SetDock(result, Dock.Right)
        dp.Children.Add(result)

        title = TextBlock()
        title.VerticalAlignment = VerticalAlignment.Center
        lvl = _run(u"Level {0}".format(depth), "#F4F4F4")
        lvl.FontWeight = FontWeights.SemiBold
        title.Inlines.Add(lvl)
        title.Inlines.Add(_run(u"  \u00b7  " + plural(len(nodes), u"family", u"families"), "#8D8D8D", 11))
        dp.Children.Add(title)
        band.Child = dp

        body = StackPanel()
        for node in nodes:
            body.Children.Add(family_row(node, 46))
        band.MouseLeftButtonUp += MouseButtonEventHandler(make_level_toggle(body, chevron))
        return band, body

    def fill_box(group):
        """The family first, then one band per nested level with that level's families."""
        box = group["box"]
        box.Children.Clear()
        root = group["root"]
        box.Children.Add(section_head(u"THE FAMILY", 10))
        box.Children.Add(family_row(root, 30, chip=False))
        levels = OrderedDict()
        for node in sorted(group["nested"], key=lambda n: n.depth):
            levels.setdefault(node.depth, []).append(node)
        for depth, nodes in levels.items():
            band, body = level_band(depth, nodes)
            box.Children.Add(band)
            box.Children.Add(body)
        spacer = Border()
        spacer.Height = 10
        box.Children.Add(spacer)
        group["built"] = True

    def make_toggle_handler(group):
        def handler(sender, args):
            group["open"] = not group["open"]
            refresh_list()
        return safe(handler)

    def build_group(root, nested):
        subtree = [root] + nested
        purged = sum(sum(n.purged.values()) for n in subtree)
        params = sum(len(n.removed) for n in subtree)
        problem = any(is_problem(n) for n in subtree)
        hay = []
        for n in subtree:
            hay.append(n.name)
            hay.extend(n.removed)
            hay.extend(n.kept.keys())
            hay.append(n.status)
        group = {"root": root, "nested": nested, "open": False, "built": False,
                 "changed": bool(purged or params), "problem": problem,
                 "search": u" ".join(hay).lower()}

        row = Border()
        row.Style = window.FindResource("Row")
        row.Padding = Thickness(8, 8, 12, 8)
        dp = DockPanel()

        chevron = text_block(u"▸", 12, "#A8A8A8")
        chevron.FontFamily = FontFamily(u"Segoe UI Symbol")
        chevron.Width = 26
        chevron.TextAlignment = TextAlignment.Center

        info = StackPanel()
        info.VerticalAlignment = VerticalAlignment.Center
        name = text_block(root.name, 13, "#F4F4F4", bold=True)
        name.TextTrimming = TextTrimming.CharacterEllipsis
        opened = len([n for n in nested if not n.status.startswith((u"Not opened", u"Failed to open"))])
        sub_parts = [root.category or u"No category"]
        if nested:
            sub_parts.append(plural(max(n.depth for n in nested), u"nested level"))
            sub_parts.append(plural(opened, u"nested family", u"nested families") + u" opened")
        sub_parts.append(root.status)
        sub = text_block(u"  ·  ".join(sub_parts), 11, "#8D8D8D")
        sub.TextTrimming = TextTrimming.CharacterEllipsis
        info.Children.Add(name)
        info.Children.Add(sub)
        if problem and not is_problem(root):
            warn = text_block(u"A nested family has a problem - open the details", 11, "#FDDC69")
            info.Children.Add(warn)

        removed_caption = u"to purge" if preview else u"purged"
        params_caption = u"params to remove" if preview else u"params removed"
        right = [count_block(params, params_caption), count_block(purged, removed_caption), pill(root)]
        if can_select(root):
            right.insert(0, select_chip(root))
        DockPanel.SetDock(chevron, Dock.Left)
        dp.Children.Add(chevron)
        for el in right:
            DockPanel.SetDock(el, Dock.Right)
            dp.Children.Add(el)
        dp.Children.Add(info)
        row.Child = dp
        row.ToolTip = u"Click to show or hide the details"
        row.MouseLeftButtonUp += MouseButtonEventHandler(make_toggle_handler(group))

        box = StackPanel()
        box.Visibility = Visibility.Collapsed
        box.Background = brush("#1B1B1B")
        group["row"] = row
        group["chevron"] = chevron
        group["box"] = box
        return group

    def refresh_list():
        raw = ui["txtSearch"].Text or u""
        q = raw.strip().lower()
        ui["tbPlaceholder"].Visibility = Visibility.Collapsed if raw else Visibility.Visible
        changed_only = ui["chkChanged"].IsChecked == True
        problems_only = ui["chkProblems"].IsChecked == True
        visible = 0
        for group in state["groups"]:
            show = ((not q or q in group["search"])
                    and (not changed_only or group["changed"])
                    and (not problems_only or group["problem"]))
            group["row"].Visibility = Visibility.Visible if show else Visibility.Collapsed
            is_open = show and group["open"]
            group["chevron"].Text = u"▾" if is_open else u"▸"
            if is_open and not group["built"]:
                fill_box(group)
            group["box"].Visibility = Visibility.Visible if is_open else Visibility.Collapsed
            if show:
                visible += 1
        ui["tbEmpty"].Visibility = Visibility.Collapsed if visible else Visibility.Visible

    def set_all(is_open):
        for group in state["groups"]:
            group["open"] = is_open
        refresh_list()

    # ---------------------------------------------------------------- fill --
    roots = [r for r in rows if r.parent is None]
    nested_of = dict((id(r), []) for r in roots)
    for n in rows:
        if n.parent is not None:
            nested_of.setdefault(id(root_of(n)), []).append(n)
    for r in roots:
        group = build_group(r, nested_of.get(id(r), []))
        state["groups"].append(group)
        ui["spList"].Children.Add(group["row"])
        ui["spList"].Children.Add(group["box"])

    opened = [n for n in rows if not n.status.startswith((u"Not opened", u"Failed to open", u"Skipped"))]
    problems = [n for n in rows if is_problem(n)]
    purged = sum(sum(n.purged.values()) for n in rows)
    params = sum(len(n.removed) for n in rows)
    ui["tvFamilies"].Text = u"{0:,}".format(len(roots))
    ui["tcFamilies"].Text = u"families cleaned"
    ui["tvOpened"].Text = u"{0:,}".format(len(opened))
    ui["tcOpened"].Text = u"opened incl. nested"
    ui["tvPurged"].Text = u"{0:,}".format(purged)
    ui["tcPurged"].Text = u"items to purge" if preview else u"unused items purged"
    ui["tvParams"].Text = u"{0:,}".format(params)
    ui["tcParams"].Text = u"params to remove" if preview else u"parameters removed"
    ui["tvProblems"].Text = u"{0:,}".format(len(problems))
    ui["tvProblems"].Foreground = brush("#FFB3B8" if problems else "#6F6F6F")
    ui["tcProblems"].Text = u"problems"
    ui["bdPreview"].Visibility = Visibility.Visible if preview else Visibility.Collapsed
    if notes:
        ui["tbNotes"].Text = u"\n".join(notes)
        ui["bdNotes"].Visibility = Visibility.Visible
    ui["tbTotals"].Text = u"{0}  ·  {1}".format(
        plural(len(roots), u"family", u"families"),
        u"{0} with problems".format(len(problems)) if problems else u"no problems")

    # ------------------------------------------------------------- buttons --
    def on_copy(sender, args):
        Clipboard.SetText(report_text(title, ui["tbSub"].Text, rows))
        set_status(u"The report is on the clipboard as plain text.", "ok")

    def on_closed(sender, args):
        session = get_session()
        if session and session.get("window") is window:
            set_session(None)
        try:
            external_event.Dispose()
        except Exception:
            logger.debug("ExternalEvent was already disposed.")

    ui["btnExpand"].Click += RoutedEventHandler(safe(lambda s, a: set_all(True)))
    ui["btnCollapse"].Click += RoutedEventHandler(safe(lambda s, a: set_all(False)))
    ui["btnCopy"].Click += RoutedEventHandler(safe(on_copy))
    ui["btnClose"].Click += RoutedEventHandler(safe(lambda s, a: window.Close()))
    ui["chkChanged"].Click += RoutedEventHandler(safe(lambda s, a: refresh_list()))
    ui["chkProblems"].Click += RoutedEventHandler(safe(lambda s, a: refresh_list()))
    ui["txtSearch"].TextChanged += TextChangedEventHandler(safe(lambda s, a: refresh_list()))
    window.Closed += EventHandler(on_closed)

    if len(state["groups"]) == 1:
        state["groups"][0]["open"] = True  # one family: show it straight away
    refresh_list()
    set_status(HINT)

    try:
        WindowInteropHelper(window).Owner = uiapp.MainWindowHandle
    except Exception:
        logger.debug("Could not set Revit as the owner window.")

    # Parked where it outlives this scope: keeps the ExternalEvent alive while the window is open.
    set_session({"window": window, "handler": event_handler, "event": external_event})

    # Show(), not ShowDialog(): the script ends here and Revit is free while the window stays open.
    window.Show()


def _run(text, color, size=None):
    from System.Windows.Documents import Run
    r = Run(text)
    r.Foreground = brush(color)
    if size:
        r.FontSize = size
    return r
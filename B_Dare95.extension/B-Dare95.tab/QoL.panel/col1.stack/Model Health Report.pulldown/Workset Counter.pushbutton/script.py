# -*- coding: utf-8 -*-
__doc__ = """__________________________________________________
Description:

Reports every user workset with its creator, current owner, open/closed state and how many elements it holds, with a breakdown by category.
Click a workset or a category to select those elements in the model. The window stays open while you work.
Empty worksets are listed too, and closed worksets are flagged.
__________________________________________________
How-to:

-> Open a workshared model
-> Make sure the worksets you care about are open
-> Click on the button
-> Click a workset to select all its model elements, or expand it and click a category
-> Ctrl+click adds to the current selection
-> Click Refresh after changing the model
__________________________________________________
Author: Mohamed Bedair"""

__persistentengine__ = True

import clr
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from System import EventHandler
from System.Collections.Generic import List
from System.Windows import (CornerRadius, FontWeights, HorizontalAlignment, RoutedEventHandler,
                            TextAlignment, TextTrimming, TextWrapping, Thickness, VerticalAlignment, Visibility)
from System.Windows.Controls import (Border, Dock, DockPanel, StackPanel, TextBlock,
                                     TextChangedEventHandler)
from System.Windows.Input import Cursors, Keyboard, ModifierKeys, MouseButtonEventHandler
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Markup import XamlReader
from System.Windows.Media import BrushConverter, FontFamily

from Autodesk.Revit.UI import ExternalEvent, IExternalEventHandler

from pyrevit import DB, forms, revit, script
from pyrevit.coreutils import envvars

logger = script.get_logger()

# --------------------------------------------------------------- settings --
# Set to True to also report View / Family / Project Standards worksets.
INCLUDE_NON_USER_WORKSETS = False

# Categories allowed through from the Annotation bucket.
ALLOWED_ANNOTATION_CATS = set([
    int(DB.BuiltInCategory.OST_Levels),
    int(DB.BuiltInCategory.OST_Grids),
])

KIND_NAMES = {
    DB.WorksetKind.UserWorkset: u"User-Created",
    DB.WorksetKind.FamilyWorkset: u"Family",
    DB.WorksetKind.ViewWorkset: u"View",
    DB.WorksetKind.StandardWorkset: u"Project Standard",
}

SESSION_KEY = "WORKSET_COUNTER_SESSION"

_bc = BrushConverter()


def brush(hex_value):
    return _bc.ConvertFromString(hex_value)


# --------------------------------------------------------------- helpers ---
def id_int(some_id):
    """ElementId / WorksetId integer value, Revit 2024-2027 safe."""
    try:
        return some_id.Value
    except AttributeError:
        return some_id.IntegerValue


def fmt_n(n):
    return u"{:,}".format(n)


def plural(n, word, word_pl=None):
    return u"{} {}".format(fmt_n(n), word if n == 1 else (word_pl or word + u"s"))


def get_creator(doc, workset):
    """Worksets are backed by real elements, so the worksharing tooltip works."""
    try:
        info = DB.WorksharingUtils.GetWorksharingTooltipInfo(
            doc, DB.ElementId(id_int(workset.Id)))
        if info.Creator:
            return info.Creator
    except Exception:
        pass
    return u"<unknown>"


def get_owner(workset):
    try:
        if workset.Owner:
            return workset.Owner
    except Exception:
        pass
    return u"-"


def is_valid_model_element(el):
    try:
        cat = el.Category
    except Exception:
        return False

    if cat is None:
        return False
    if cat.Parent is not None:
        # Subcategory (Mullions, Balusters, Top Rails, ...) - skip
        return False
    if cat.CategoryType == DB.CategoryType.Model:
        return True
    if cat.CategoryType == DB.CategoryType.Annotation:
        return id_int(cat.Id) in ALLOWED_ANNOTATION_CATS
    return False


# ------------------------------------------------------------ data collection --
def collect(doc):
    """Scan the model. ElementIds are kept (they are plain values, not tied to
    the document) so a click can select them later without re-scanning."""
    rows = {}
    for ws in DB.FilteredWorksetCollector(doc):
        if not INCLUDE_NON_USER_WORKSETS and ws.Kind != DB.WorksetKind.UserWorkset:
            continue
        key = id_int(ws.Id)
        rows[key] = {
            "name": ws.Name,
            "kind": KIND_NAMES.get(ws.Kind, u"Other"),
            "creator": get_creator(doc, ws),
            "owner": get_owner(ws),
            "is_open": ws.IsOpen,
            "ids": List[DB.ElementId](),   # model elements only
            "raw": 0,                      # every non-type element on the workset
            "cats": {},                    # category name -> List[ElementId]
        }

    collector = DB.FilteredElementCollector(doc)\
                  .WhereElementIsNotElementType()\
                  .ToElements()

    for el in collector:
        try:
            rec = rows.get(id_int(el.WorksetId))
        except Exception:
            continue
        if rec is None:
            continue
        rec["raw"] += 1
        if not is_valid_model_element(el):
            continue
        rec["ids"].Add(el.Id)
        cat_name = el.Category.Name
        ids = rec["cats"].get(cat_name)
        if ids is None:
            ids = rec["cats"][cat_name] = List[DB.ElementId]()
        ids.Add(el.Id)

    ordered = sorted(rows.values(), key=lambda r: (-r["ids"].Count, r["name"].lower()))
    return {"title": doc.Title, "path": doc.PathName, "rows": ordered}


# ---------------------------------------------------------------- session state --
# A persistent engine hands each run a fresh module scope. pyRevit's env vars
# live above that: they let a second press find the open window, and they hold
# the strong reference that keeps the ExternalEvent alive while the window is up.

def get_session():
    try:
        return envvars.get_pyrevit_env_var(SESSION_KEY)
    except Exception:
        return None


def set_session(value):
    try:
        envvars.set_pyrevit_env_var(SESSION_KEY, value)
    except Exception:
        logger.debug("Could not store the Workset Counter session.")


class WorksetEventHandler(IExternalEventHandler):
    """Runs queued work inside a valid Revit API context. After the script
    returns, a WPF click is just a callback with no API context open, so every
    Revit call (selection, zoom, re-scan) is queued and run here when Revit is
    idle. A queue, not a single slot: Revit may merge quick Raise() calls."""

    def __init__(self):
        self.queue = []

    def enqueue(self, action):
        self.queue.append(action)

    def Execute(self, uiapp):
        pending, self.queue = self.queue, []
        for action in pending:
            try:
                action()
            except Exception as ex:
                logger.error("Workset Counter error: {0}".format(ex))
                forms.alert("Workset Counter ran into an error:\n\n{0}".format(ex))

    def GetName(self):
        return "Workset Counter"


# --------------------------------------------------------------------------- UI --
XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Workset Counter" Width="720" Height="760" MinWidth="560" MinHeight="460"
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
              ToolTip="Scan the active model again"/>
      <StackPanel VerticalAlignment="Center">
        <TextBlock Text="Workset Report" FontSize="18" FontWeight="SemiBold"/>
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
      <Grid>
        <TextBox x:Name="txtSearch"/>
        <TextBlock x:Name="tbPlaceholder" Text="Search worksets and categories" Foreground="#8D8D8D"
                   Margin="10,0,0,0" VerticalAlignment="Center" IsHitTestVisible="False"/>
      </Grid>
    </DockPanel>

    <Border Grid.Row="3" Margin="0,10,0,0" BorderBrush="#393939" BorderThickness="1" CornerRadius="6">
      <ScrollViewer VerticalScrollBarVisibility="Auto">
        <StackPanel x:Name="spList"/>
      </ScrollViewer>
    </Border>

    <Border Grid.Row="4" x:Name="bdStatus" Background="#262626" CornerRadius="6" Padding="10,8" Margin="0,10,0,0">
      <TextBlock x:Name="tbStatus" Foreground="#A8A8A8" FontSize="12" TextWrapping="Wrap"
                 Text="Click a workset or a category to select its elements in the model. Ctrl+click adds to the current selection."/>
    </Border>

    <DockPanel Grid.Row="5" Margin="0,12,0,0">
      <Button x:Name="btnClose" DockPanel.Dock="Right" Style="{StaticResource Accent}" Content="Close"/>
      <TextBlock x:Name="tbTotals" Foreground="#A8A8A8" FontSize="12" VerticalAlignment="Center"/>
    </DockPanel>
  </Grid>
</Window>
"""

STATUS_COLORS = {
    "info": ("#262626", "#A8A8A8"),
    "ok":   ("#0E2A18", "#A7F0BA"),
    "warn": ("#3A2E06", "#FDDC69"),
}


def run():
    # Pressing the button while the window is open brings it forward instead
    # of opening a second one.
    session = get_session()
    if session:
        existing = session.get("window")
        if existing is not None and existing.IsVisible:
            existing.Activate()
            return

    doc = revit.doc
    if not doc.IsWorkshared:
        forms.alert("This model is not workshared - there are no worksets to report.",
                    title="Workset Report")
        return

    window = XamlReader.Parse(XAML)
    ui = {}
    for name in ["btnRefresh", "tbModel", "bdWarn", "tbWarn", "btnCollapse", "btnExpand",
                 "chkZoom", "txtSearch", "tbPlaceholder", "spList", "bdStatus", "tbStatus",
                 "btnClose", "tbTotals"]:
        ui[name] = window.FindName(name)

    event_handler = WorksetEventHandler()
    external_event = ExternalEvent.Create(event_handler)

    def queue(action):
        event_handler.enqueue(action)
        external_event.Raise()

    state = {"report": collect(doc), "groups": []}

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
                logger.error("Workset Counter error: {0}".format(ex))
                set_status(u"Something went wrong: {0}".format(ex), "warn")
        return wrapped

    # ------------------------------------------------------------- selection --
    def same_document(d):
        rep = state["report"]
        return d is not None and d.Title == rep["title"] and d.PathName == rep["path"]

    def select_ids(ids, label):
        append = (Keyboard.Modifiers & ModifierKeys.Control) == ModifierKeys.Control
        zoom = ui["chkZoom"].IsChecked == True
        if ids.Count == 0:
            set_status(u"Nothing to select: {0} has no model elements.".format(label), "warn")
            return
        set_status(u"Selecting {0}\u2026".format(label))

        def action():
            uidoc = __revit__.ActiveUIDocument
            d = uidoc.Document if uidoc is not None else None
            if not same_document(d):
                set_status(u"This report is for \u201C{0}\u201D. Switch back to that model, or click "
                           u"Refresh to scan the active one.".format(state["report"]["title"]), "warn")
                return
            live = List[DB.ElementId]()
            seen = set()
            missing = 0
            for eid in ids:
                if d.GetElement(eid) is None:
                    missing += 1
                    continue
                live.Add(eid)
                seen.add(id_int(eid))
            added = live.Count
            if append:
                for eid in uidoc.Selection.GetElementIds():
                    if id_int(eid) not in seen:
                        live.Add(eid)
                        seen.add(id_int(eid))
            uidoc.Selection.SetElementIds(live)
            if zoom and added:
                uidoc.ShowElements(live)
            text = u"{0} {1}: {2}.".format(
                u"Added" if append else u"Selected", plural(added, u"element"), label)
            if append:
                text += u" {0} selected in total.".format(fmt_n(live.Count))
            if missing:
                text += u" {0} no longer exist. Click Refresh to update the counts.".format(
                    plural(missing, u"element"))
            set_status(text, "warn" if missing else "ok")

        queue(action)

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
        b.Child = text_block(text, 11, fg)
        return b

    def count_block(n, caption):
        sp = StackPanel()
        sp.VerticalAlignment = VerticalAlignment.Center
        sp.Margin = Thickness(12, 0, 0, 0)
        sp.MinWidth = 100
        big = text_block(fmt_n(n), 14, "#F4F4F4" if n else "#6F6F6F", bold=True)
        big.HorizontalAlignment = HorizontalAlignment.Right
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
            args.Handled = True     # don't also select the workset
            refresh_list()
        return safe(handler)

    def build_category_row(rec, cat_name, ids):
        row = Border()
        row.Style = window.FindResource("Row")
        row.Padding = Thickness(44, 6, 12, 6)
        dp = DockPanel()
        cnt = text_block(fmt_n(ids.Count), 12, "#F4F4F4")
        cnt.Margin = Thickness(12, 0, 0, 0)
        DockPanel.SetDock(cnt, Dock.Right)
        name = text_block(cat_name, 12, "#C6C6C6")
        name.TextTrimming = TextTrimming.CharacterEllipsis
        dp.Children.Add(cnt)
        dp.Children.Add(name)
        row.Child = dp
        label = u"{0} on {1}".format(cat_name, rec["name"])
        row.ToolTip = u"Click to select these {0}. Ctrl+click adds to the current selection.".format(
            plural(ids.Count, u"element"))
        row.MouseLeftButtonUp += MouseButtonEventHandler(make_select_handler(ids, label))
        return row

    def build_group(rec):
        group = {"rec": rec, "open": False, "cats": []}

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
        chevron.ToolTip = u"Show or hide the categories"

        info = StackPanel()
        info.VerticalAlignment = VerticalAlignment.Center
        title = text_block(rec["name"], 13, "#F4F4F4", bold=True)
        title.TextTrimming = TextTrimming.CharacterEllipsis
        sub_parts = [rec["kind"], u"Created by " + rec["creator"], u"Owner: " + rec["owner"],
                     plural(rec["raw"], u"element") + u" in total",
                     plural(len(rec["cats"]), u"category", u"categories")]
        sub = text_block(u"  \u00B7  ".join(sub_parts), 11, "#8D8D8D")
        sub.TextWrapping = TextWrapping.Wrap
        info.Children.Add(title)
        info.Children.Add(sub)

        if rec["is_open"]:
            state_pill = pill(u"Open", "#0E2A18", "#A7F0BA")
        else:
            state_pill = pill(u"Closed", "#3A2E06", "#FDDC69")

        counts = count_block(rec["ids"].Count, u"model elements")

        DockPanel.SetDock(chevron, Dock.Left)
        DockPanel.SetDock(counts, Dock.Right)
        DockPanel.SetDock(state_pill, Dock.Right)
        for child in (chevron, counts, state_pill, info):
            dp.Children.Add(child)
        row.Child = dp

        n = rec["ids"].Count
        if n:
            row.ToolTip = (u"Click to select the {0} on this workset. Ctrl+click adds to the "
                           u"current selection.").format(plural(n, u"model element"))
        elif rec["raw"]:
            row.ToolTip = (u"No model elements. Holds {0} (views, annotations, subcategories, "
                           u"etc.)").format(plural(rec["raw"], u"other element"))
        else:
            row.ToolTip = u"Empty workset"
        row.MouseLeftButtonUp += MouseButtonEventHandler(
            make_select_handler(rec["ids"], u"model elements on {0}".format(rec["name"])))

        if rec["cats"]:
            chevron.MouseLeftButtonUp += MouseButtonEventHandler(make_toggle_handler(group))
        else:
            chevron.Text = u""

        cat_names = sorted(rec["cats"].keys(), key=lambda c: (-rec["cats"][c].Count, c.lower()))
        for cat_name in cat_names:
            cat_row = build_category_row(rec, cat_name, rec["cats"][cat_name])
            group["cats"].append((cat_name, cat_row))

        group["row"] = row
        group["chevron"] = chevron
        return group

    def build_list():
        rep = state["report"]
        ui["spList"].Children.Clear()
        state["groups"] = []
        for rec in rep["rows"]:
            group = build_group(rec)
            state["groups"].append(group)
            ui["spList"].Children.Add(group["row"])
            for _name, cat_row in group["cats"]:
                ui["spList"].Children.Add(cat_row)

        rows = rep["rows"]
        ui["tbModel"].Text = u"{0}  \u2014  {1}".format(
            rep["title"], plural(len(rows), u"workset"))
        closed = [r["name"] for r in rows if not r["is_open"]]
        if closed:
            ui["tbWarn"].Text = (u"{0} closed in this session, so their elements are not loaded "
                                 u"and report as 0: {1}").format(
                plural(len(closed), u"workset is", u"worksets are"), u", ".join(closed))
            ui["bdWarn"].Visibility = Visibility.Visible
        else:
            ui["bdWarn"].Visibility = Visibility.Collapsed
        total = sum(r["ids"].Count for r in rows)
        empty = len([r for r in rows if r["ids"].Count == 0])
        ui["tbTotals"].Text = u"Total model elements: {0}  \u00B7  Empty worksets: {1}".format(
            fmt_n(total), fmt_n(empty))
        refresh_list()

    def refresh_list():
        raw = ui["txtSearch"].Text or u""
        q = raw.strip().lower()
        ui["tbPlaceholder"].Visibility = Visibility.Collapsed if raw else Visibility.Visible
        for group in state["groups"]:
            rec = group["rec"]
            ws_hit = not q or q in rec["name"].lower()
            cat_hits = [c for c, _r in group["cats"] if q and q in c.lower()]
            show_group = ws_hit or bool(cat_hits)
            group["row"].Visibility = Visibility.Visible if show_group else Visibility.Collapsed
            # a category match opens its workset so the match is visible
            is_open = group["open"] or (bool(cat_hits) and not ws_hit)
            if group["cats"]:
                group["chevron"].Text = u"\u25BE" if is_open else u"\u25B8"
            for cat_name, cat_row in group["cats"]:
                if not show_group or not is_open:
                    vis = False
                elif ws_hit:
                    vis = True
                else:
                    vis = cat_name in cat_hits
                cat_row.Visibility = Visibility.Visible if vis else Visibility.Collapsed

    # ----------------------------------------------------------------- buttons --
    def on_expand(sender, args):
        for group in state["groups"]:
            group["open"] = True
        refresh_list()

    def on_collapse(sender, args):
        for group in state["groups"]:
            group["open"] = False
        refresh_list()

    def on_search(sender, args):
        refresh_list()

    def on_refresh(sender, args):
        set_status(u"Scanning the active model\u2026")
        ui["btnRefresh"].IsEnabled = False

        def action():
            try:
                uidoc = __revit__.ActiveUIDocument
                d = uidoc.Document if uidoc is not None else None
                if d is None or not d.IsWorkshared:
                    set_status(u"The active model is not workshared, so there is nothing to scan.", "warn")
                    return
                opened = set(g["rec"]["name"] for g in state["groups"] if g["open"])
                state["report"] = collect(d)
                build_list()
                for group in state["groups"]:
                    group["open"] = group["rec"]["name"] in opened
                refresh_list()
                set_status(u"Scanned \u201C{0}\u201D.".format(d.Title), "ok")
            finally:
                ui["btnRefresh"].IsEnabled = True

        queue(action)

    def on_close_click(sender, args):
        window.Close()

    def on_closed(sender, args):
        # Let a later press open a fresh window, and release the ExternalEvent.
        set_session(None)
        try:
            external_event.Dispose()
        except Exception:
            logger.debug("ExternalEvent was already disposed.")

    ui["btnExpand"].Click += RoutedEventHandler(safe(on_expand))
    ui["btnCollapse"].Click += RoutedEventHandler(safe(on_collapse))
    ui["btnRefresh"].Click += RoutedEventHandler(safe(on_refresh))
    ui["btnClose"].Click += RoutedEventHandler(safe(on_close_click))
    ui["txtSearch"].TextChanged += TextChangedEventHandler(safe(on_search))
    window.Closed += EventHandler(on_closed)

    build_list()

    try:
        WindowInteropHelper(window).Owner = __revit__.MainWindowHandle
    except Exception:
        logger.debug("Could not set Revit as the owner window.")

    # Parked where it outlives this scope: the strong reference that keeps the
    # ExternalEvent alive while the window is open.
    set_session({"window": window, "handler": event_handler, "event": external_event})

    # Show(), not ShowDialog(), and nothing after it: the script ends here and
    # Revit is free while the window stays open.
    window.Show()


run()

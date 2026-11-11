# -*- coding: utf-8 -*-
__doc__ = """__________________________________________________
Description:

Counts the model elements on each level, broken down by category, from lowest level to highest.
Click a level or a category to select those elements in the model. The window stays open while you work.
Elements with no level and whole-model totals by category are listed too.
__________________________________________________
How-to:

-> Click on the button
-> Wait while the whole model is scanned
-> Click a level to select all its elements, or expand it and click a category
-> Ctrl+click adds to the current selection
-> Click Refresh after changing the model
__________________________________________________
Author: Mohamed Bedair"""

__persistentengine__ = True

import clr
import System
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

from pyrevit import DB, revit, script
from pyrevit.coreutils import envvars
import bd_core as bd

logger = script.get_logger()

FT_TO_MM = bd.MM_PER_FT
UNASSIGNED = -1
SESSION_KEY = "ITEMS_ON_LEVELS_SESSION"
NO_LEVEL_NAME = u"No Level / Unassigned"
TOTALS_NAME = u"Totals by Category (all levels)"

_bc = BrushConverter()


def brush(hex_value):
    return _bc.ConvertFromString(hex_value)


# --------------------------------------------------------------- helpers ---
id_int = bd.eid_int


def fmt_n(n):
    return u"{:,}".format(n)


plural = bd.plural


def _bic(name):
    """Fetch a BuiltInCategory by name, or None if it doesn't exist in this version."""
    return getattr(DB.BuiltInCategory, name, None)


def _bip(name):
    return getattr(DB.BuiltInParameter, name, None)


def get_bic(cat):
    """BuiltInCategory of a Category (2023+ property, enum fallback)."""
    try:
        return cat.BuiltInCategory
    except AttributeError:
        try:
            return System.Enum.ToObject(DB.BuiltInCategory, id_int(cat.Id))
        except Exception:
            return None


# Categories to skip: sub-elements / parts of a parent element. Edit freely.
EXCLUDED_CATS = set(b for b in [
    _bic('OST_CurtainWallPanels'),
    _bic('OST_CurtainWallMullions'),
    # stair sub-parts (parent = OST_Stairs)
    _bic('OST_StairsRuns'),
    _bic('OST_StairsLandings'),
    _bic('OST_StairsSupports'),
    _bic('OST_StairsStringerCarriage'),
    # railing sub-parts (parent = OST_StairsRailing / OST_Railings)
    _bic('OST_RailingTopRail'),
    _bic('OST_RailingHandRail'),
    _bic('OST_RailingSupport'),
    _bic('OST_RailingTermination'),
    # datum noise
    _bic('OST_Levels'),
    _bic('OST_Grids'),
] if b is not None)

# Parameters searched (in order) to find an element's level when LevelId is empty.
LEVEL_BIPS = [p for p in [
    _bip('LEVEL_PARAM'),
    _bip('SCHEDULE_LEVEL_PARAM'),
    _bip('FAMILY_LEVEL_PARAM'),
    _bip('FAMILY_BASE_LEVEL_PARAM'),
    _bip('INSTANCE_REFERENCE_LEVEL_PARAM'),
    _bip('INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM'),
    _bip('WALL_BASE_CONSTRAINT'),
    _bip('ROOF_BASE_LEVEL_PARAM'),
    _bip('ROOM_LEVEL_ID'),
    _bip('STAIRS_BASE_LEVEL_PARAM'),
    _bip('RBS_START_LEVEL_PARAM'),
    _bip('FABRICATION_LEVEL_PARAM'),
] if p is not None]


def get_level_int(doc, elem):
    """Return the associated level's int id, or UNASSIGNED."""
    # 1) direct property (fast, covers most elements)
    try:
        lid = elem.LevelId
        if lid is not None and id_int(lid) > 0:
            return id_int(lid)
    except Exception:
        pass
    # 2) fall back to known level parameters
    for bip in LEVEL_BIPS:
        try:
            p = elem.get_Parameter(bip)
        except Exception:
            p = None
        if p and p.HasValue and p.StorageType == DB.StorageType.ElementId:
            v = p.AsElementId()
            if v is not None and id_int(v) > 0:
                if isinstance(doc.GetElement(v), DB.Level):
                    return id_int(v)
    return UNASSIGNED


def new_row(name, kind):
    return {"name": name, "kind": kind, "sub": u"", "ids": List[DB.ElementId](), "cats": {}}


def add_to(row, cat_name, eid):
    row["ids"].Add(eid)
    ids = row["cats"].get(cat_name)
    if ids is None:
        ids = row["cats"][cat_name] = List[DB.ElementId]()
    ids.Add(eid)


# ------------------------------------------------------------ data collection --
def collect(doc):
    """Scan the model. ElementIds are kept (they are plain values, not tied to
    the document) so a click can select them later without re-scanning."""
    levels = list(DB.FilteredElementCollector(doc)
                  .OfClass(DB.Level).WhereElementIsNotElementType().ToElements())
    levels.sort(key=lambda l: l.Elevation)

    by_level = {}
    order = []
    for lvl in levels:
        key = id_int(lvl.Id)
        row = new_row(lvl.Name, "level")
        row["elev"] = lvl.Elevation * FT_TO_MM
        by_level[key] = row
        order.append(key)

    no_level = new_row(NO_LEVEL_NAME, "none")
    totals = new_row(TOTALS_NAME, "total")

    for elem in DB.FilteredElementCollector(doc).WhereElementIsNotElementType():
        cat = elem.Category
        if cat is None:
            continue
        try:
            if cat.CategoryType != DB.CategoryType.Model:   # drops annotation + analytical
                continue
        except Exception:
            continue
        bic = get_bic(cat)
        if bic is not None and bic in EXCLUDED_CATS:       # drops sub-elements
            continue

        key = get_level_int(doc, elem)
        if key == UNASSIGNED:
            row = no_level
        else:
            row = by_level.get(key)
            if row is None:                                # a level not in the list above
                row = by_level[key] = new_row(u"Level id {0}".format(key), "level")
                order.append(key)
        add_to(row, cat.Name, elem.Id)
        add_to(totals, cat.Name, elem.Id)

    rows = []
    for key in order:
        row = by_level[key]
        parts = []
        if "elev" in row:
            parts.append(u"Elevation {0} mm".format(fmt_n(int(round(row["elev"])))))
        parts.append(plural(len(row["cats"]), u"category", u"categories"))
        row["sub"] = u"  \u00B7  ".join(parts)
        rows.append(row)
    if no_level["ids"].Count:
        no_level["sub"] = (u"Elements with no level of their own  \u00B7  " +
                           plural(len(no_level["cats"]), u"category", u"categories"))
        rows.append(no_level)
    totals["sub"] = (u"Every counted element in the model  \u00B7  " +
                     plural(len(totals["cats"]), u"category", u"categories"))
    rows.append(totals)
    return {"title": doc.Title, "path": doc.PathName, "rows": rows, "levels": len(levels)}


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
        logger.debug("Could not store the Items on Levels session.")


class LevelsEventHandler(IExternalEventHandler):
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
                logger.error("Items on Levels error: {0}".format(ex))
                bd.alert("Items on Levels ran into an error:\n\n{0}".format(ex), u"Items on Levels")

    def GetName(self):
        return "Items on Levels"


# --------------------------------------------------------------------------- UI --
XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Items on Levels" Width="720" Height="760" MinWidth="560" MinHeight="460"
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
        <TextBlock Text="Elements per Level" FontSize="18" FontWeight="SemiBold"/>
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
        <TextBlock x:Name="tbPlaceholder" Text="Search levels and categories" Foreground="#8D8D8D"
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
                 Text="Click a level or a category to select its elements in the model. Ctrl+click adds to the current selection."/>
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

    window = XamlReader.Parse(XAML)
    ui = {}
    for name in ["btnRefresh", "tbModel", "bdWarn", "tbWarn", "btnCollapse", "btnExpand",
                 "chkZoom", "txtSearch", "tbPlaceholder", "spList", "bdStatus", "tbStatus",
                 "btnClose", "tbTotals"]:
        ui[name] = window.FindName(name)

    event_handler = LevelsEventHandler()
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
                logger.error("Items on Levels error: {0}".format(ex))
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
            set_status(u"Nothing to select: {0} has no elements.".format(label), "warn")
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
            args.Handled = True     # don't also select the level
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
        if rec["kind"] == "total":
            label = u"all {0}".format(cat_name)
        elif rec["kind"] == "none":
            label = u"{0} with no level".format(cat_name)
        else:
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
        sub = text_block(rec["sub"], 11, "#8D8D8D")
        sub.TextWrapping = TextWrapping.Wrap
        info.Children.Add(title)
        info.Children.Add(sub)

        counts = count_block(rec["ids"].Count, u"elements")
        DockPanel.SetDock(chevron, Dock.Left)
        DockPanel.SetDock(counts, Dock.Right)
        dp.Children.Add(chevron)
        dp.Children.Add(counts)
        if rec["kind"] == "none":
            tag = pill(u"No level", "#3A2E06", "#FDDC69")
        elif rec["kind"] == "total":
            tag = pill(u"All levels", "#393939", "#C6C6C6")
        else:
            tag = None
        if tag is not None:
            DockPanel.SetDock(tag, Dock.Right)
            dp.Children.Add(tag)
        dp.Children.Add(info)
        row.Child = dp

        n = rec["ids"].Count
        if rec["kind"] == "total":
            sel_label = u"every counted element"
            what = u"every counted element in the model"
        elif rec["kind"] == "none":
            sel_label = u"elements with no level"
            what = u"the {0} with no level".format(plural(n, u"element"))
        else:
            sel_label = u"elements on {0}".format(rec["name"])
            what = u"the {0} on this level".format(plural(n, u"element"))
        if n:
            row.ToolTip = u"Click to select {0}. Ctrl+click adds to the current selection.".format(what)
        else:
            row.ToolTip = u"No elements on this level"
        row.MouseLeftButtonUp += MouseButtonEventHandler(make_select_handler(rec["ids"], sel_label))

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
        ui["tbModel"].Text = u"{0}  \u2014  {1}".format(rep["title"], plural(rep["levels"], u"level"))
        ui["bdWarn"].Visibility = Visibility.Collapsed
        total = rows[-1]["ids"].Count if rows else 0
        no_level = sum(r["ids"].Count for r in rows if r["kind"] == "none")
        ui["tbTotals"].Text = u"Total elements counted: {0}  \u00B7  With no level: {1}".format(
            fmt_n(total), fmt_n(no_level))
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
            # a category match opens its level so the match is visible
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
                if d is None:
                    set_status(u"There is no active model to scan.", "warn")
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

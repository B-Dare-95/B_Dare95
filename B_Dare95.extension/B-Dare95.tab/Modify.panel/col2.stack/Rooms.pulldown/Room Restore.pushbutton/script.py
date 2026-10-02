# -*- coding: utf-8 -*-
"""Room Register - restore unplaced / deleted rooms from the room register.

Click        : restore unplaced / deleted rooms from this document's register.
Shift+Click  : open the register's folder (or create the register if it doesn't exist).

Live tracking is armed by the extension's startup.py, so it runs in every session
without clicking this button.
"""
__title__ = "Room\nRegister"
__author__ = "Mohamed Bedair"
__persistentengine__ = True     # only matters if this button has to arm the tracker itself

import os
import re

import clr
clr.AddReference("System")                # System.Diagnostics.Process lives in System.dll
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from System import EventHandler
from System.Diagnostics import Process

from System.Windows import (Thickness, Visibility, FontWeights, TextTrimming, RoutedEventHandler,
                            MessageBox, MessageBoxButton, MessageBoxImage, MessageBoxResult)
from System.Windows.Input import Cursors, MouseButtonEventHandler
from System.Windows.Controls import StackPanel, TextBlock, CheckBox, Orientation, TextChangedEventHandler
from System.Windows.Markup import XamlReader
from System.Windows.Media import BrushConverter, Brushes
from System.Windows.Threading import Dispatcher, DispatcherFrame
from System.Windows.Interop import WindowInteropHelper

from Autodesk.Revit.DB import ReloadLatestOptions

from pyrevit import revit, forms, script

from room_register import (ensure_tracker, doc_key, find_register,
                           collect_candidates, dry_run, run_restore, remove_records)


TITLE = "Room Register"

# IBM Carbon palette + status colors
C_BG, C_CARD, C_SURFACE, C_MUTED = "#161616", "#262626", "#393939", "#525252"
C_TEXT, C_SUB, C_ACCENT = "#F4F4F4", "#A8A8A8", "#F1C21B"
C_OK, C_WARN, C_BAD = "#42BE65", "#F1C21B", "#FA4D56"


def _open_folder(path):
    Process.Start("explorer.exe", '/select,"{}"'.format(path))


def report(doc, results):
    out = script.get_output()
    ok = [r for r in results if r["ok"]]
    out.print_md("## Room Register - Restore report")
    out.print_md("**{} of {} rooms restored**".format(len(ok), len(results)))
    for r in results:
        c = r["c"]
        link = ""
        if r["ok"]:
            el = doc.GetElement(r["uid"])
            if el is not None:
                link = out.linkify(el.Id)
        print("{} {} {}  [{}]  -  {}".format(link, c.number, c.name, c.kind, r["msg"]))
        if r["missing"]:
            print("      skipped, no longer in the project: " + ", ".join(r["missing"]))
        if r["failed"]:
            print("      could not set: " + ", ".join(r["failed"]))


# ==================================================================== UI
XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Room Register - Restore" Width="1120" Height="660"
        WindowStartupLocation="CenterScreen" Background="#161616"
        FontFamily="Segoe UI" FontSize="12">
  <Window.Resources>
    <Style x:Key="Btn" TargetType="Button">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="Padding" Value="14,6"/>
      <Setter Property="Margin" Value="6,0,0,0"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="bd" Background="{TemplateBinding Background}"
                    CornerRadius="4" Padding="{TemplateBinding Padding}">
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
    <Style x:Key="Primary" TargetType="Button" BasedOn="{StaticResource Btn}">
      <Setter Property="Background" Value="#F1C21B"/>
      <Setter Property="Foreground" Value="#161616"/>
    </Style>
    <Style x:Key="Danger" TargetType="Button" BasedOn="{StaticResource Btn}">
      <Setter Property="Background" Value="#DA1E28"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
    </Style>
    <Style x:Key="Tgl" TargetType="ToggleButton">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="Padding" Value="12,6"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ToggleButton">
            <Border x:Name="bd" Background="{TemplateBinding Background}"
                    CornerRadius="4" Padding="{TemplateBinding Padding}">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
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
  </Window.Resources>

  <Grid Margin="16">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <StackPanel Grid.Row="0">
      <TextBlock Text="Recoverable rooms" Foreground="#F4F4F4" FontSize="18" FontWeight="SemiBold"/>
      <TextBlock x:Name="SubText" Foreground="#A8A8A8" Margin="0,4,0,12"/>
    </StackPanel>

    <DockPanel Grid.Row="1" Margin="0,0,0,8">
      <TextBlock DockPanel.Dock="Left" Text="Search" Foreground="#A8A8A8"
                 VerticalAlignment="Center" Margin="0,0,8,0"/>
      <ToggleButton x:Name="RebuildToggle" DockPanel.Dock="Right" Style="{StaticResource Tgl}"
                    Margin="8,0,0,0" Content="Rebuild blocked deleted rooms unplaced"/>
      <TextBox x:Name="SearchBox" Background="#262626" Foreground="#F4F4F4"
               BorderBrush="#525252" CaretBrush="#F4F4F4" Padding="6,5"/>
    </DockPanel>

    <Border Grid.Row="2" Background="#262626" CornerRadius="4,4,0,0" Padding="8,6">
      <StackPanel x:Name="HeaderRow" Orientation="Horizontal"/>
    </Border>

    <Border Grid.Row="3" Background="#262626" CornerRadius="0,0,4,4"
            BorderBrush="#393939" BorderThickness="0,1,0,0">
      <ScrollViewer VerticalScrollBarVisibility="Auto" HorizontalScrollBarVisibility="Auto">
        <StackPanel x:Name="RowsPanel" Margin="0,4,0,4"/>
      </ScrollViewer>
    </Border>

    <DockPanel Grid.Row="4" Margin="0,12,0,0">
      <TextBlock x:Name="CountText" Foreground="#A8A8A8" VerticalAlignment="Center"/>
      <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
        <Button x:Name="RemoveBtn" Content="Remove from register" Style="{StaticResource Danger}"
                Margin="0,0,18,0"/>
        <Button x:Name="SelectReadyBtn" Content="Select ready" Style="{StaticResource Btn}"/>
        <Button x:Name="ClearBtn" Content="Clear" Style="{StaticResource Btn}"/>
        <Button x:Name="CancelBtn" Content="Cancel" Style="{StaticResource Btn}"/>
        <Button x:Name="RestoreBtn" Content="Restore selected" Style="{StaticResource Primary}"/>
      </StackPanel>
    </DockPanel>
  </Grid>
</Window>
"""

COLS = [("Status", 80), ("Number", 80), ("Name", 200), ("Level", 130),
        ("Data as of", 130), ("Note", 360)]

_BRUSHES = {}


def _brush(hex_color):
    if hex_color not in _BRUSHES:
        _BRUSHES[hex_color] = BrushConverter().ConvertFromString(hex_color)
    return _BRUSHES[hex_color]


def _cell(text, width, color, bold=False):
    tb = TextBlock()
    tb.Text = text or ""
    tb.Width = width
    tb.Margin = Thickness(0, 0, 8, 0)
    tb.Foreground = _brush(color)
    tb.TextTrimming = TextTrimming.CharacterEllipsis
    if bold:
        tb.FontWeight = FontWeights.SemiBold
    if text:
        tb.ToolTip = text
    return tb


def _note_for(c, allow):
    notes = [n for n in (c.number_note, c.height_note) if n]
    extra = " - " + "; ".join(notes) if notes else ""
    if c.can_place:
        return ("Ready" + extra), (C_WARN if extra else C_OK)
    if c.check_failed:
        return (c.note + extra), C_WARN
    if allow and c.can_rebuild_unplaced:
        return "Will rebuild unplaced - {}{}".format(c.note, extra), C_WARN
    return (c.note + extra), C_BAD


def _natural(text):
    """Sort key where '109' < '1010' and 'Level 2' < 'Level 10'."""
    parts = re.split(r"(\d+)", (text or u"").lower())
    return [(0, int(p), u"") if p.isdigit() else (1, 0, p) for p in parts if p]


def _restorable(c, allow):
    return c.can_place or c.check_failed or (allow and c.can_rebuild_unplaced)


def show_menu(cands, subtitle, remove_fn):
    """remove_fn(uids) -> number removed; permanently drops Deleted records."""
    win = XamlReader.Parse(XAML)
    search = win.FindName("SearchBox")
    toggle = win.FindName("RebuildToggle")
    header = win.FindName("HeaderRow")
    rows_panel = win.FindName("RowsPanel")
    count = win.FindName("CountText")
    restore_btn = win.FindName("RestoreBtn")
    remove_btn = win.FindName("RemoveBtn")
    win.FindName("SubText").Text = subtitle

    state = {"selected": [], "allow": False, "removed": 0}
    rows = []
    sort_state = {"col": None, "desc": False}
    header_cells = []

    # ---------------------------------------------------------- header + sorting
    def row_key(r, col):
        c = r["c"]
        if col == 0:
            return _natural(c.kind)
        if col == 1:
            return _natural(c.number)
        if col == 2:
            return _natural(c.name)
        if col == 3:
            return _natural(c.level_name)
        if col == 4:
            return c.data_age or u""          # ISO timestamps sort as text
        return _natural(r["note"].Text)

    def apply_sort(col):
        if sort_state["col"] == col:
            sort_state["desc"] = not sort_state["desc"]
        else:
            sort_state["col"], sort_state["desc"] = col, False
        rows.sort(key=lambda r: row_key(r, col), reverse=sort_state["desc"])
        rows_panel.Children.Clear()
        for r in rows:
            rows_panel.Children.Add(r["cb"])
        for i, (name, _) in enumerate(COLS):
            arrow = u""
            if i == col:
                arrow = u"  \u25BC" if sort_state["desc"] else u"  \u25B2"
            header_cells[i].Text = name + arrow

    def sort_handler(col):
        return MouseButtonEventHandler(lambda s, e: apply_sort(col))

    spacer = TextBlock()
    spacer.Width = 22
    header.Children.Add(spacer)
    for i, (name, w) in enumerate(COLS):
        tb = _cell(name, w, C_SUB, bold=True)
        tb.Background = Brushes.Transparent     # whole cell is clickable, not just the text
        tb.Cursor = Cursors.Hand
        tb.ToolTip = "Sort by {}".format(name)
        tb.MouseLeftButtonUp += sort_handler(i)
        header.Children.Add(tb)
        header_cells.append(tb)

    # ---------------------------------------------------------- state refresh
    def refresh():
        allow = toggle.IsChecked == True
        n_sel = n_restore = n_remove = 0
        for r in rows:
            c, cb = r["c"], r["cb"]
            can_restore = _restorable(c, allow)
            # deleted rooms stay selectable even when blocked, so they can be removed
            enabled = can_restore or c.kind == "Deleted"
            cb.IsEnabled = enabled
            cb.Opacity = 1.0 if enabled else 0.45
            if not enabled:
                cb.IsChecked = False
            text, color = _note_for(c, allow)
            r["note"].Text = text
            r["note"].ToolTip = text
            r["note"].Foreground = _brush(color)
            if cb.IsChecked == True:
                n_sel += 1
                if can_restore:
                    n_restore += 1
                if c.kind == "Deleted":
                    n_remove += 1
        restore_btn.IsEnabled = n_restore > 0
        remove_btn.IsEnabled = n_remove > 0
        count.Text = "{} rooms  |  {} selected  ({} restorable, {} removable)".format(
            len(rows), n_sel, n_restore, n_remove)

    # ---------------------------------------------------------- rows
    for c in cands:
        cells = StackPanel()
        cells.Orientation = Orientation.Horizontal
        status_tb = _cell(c.kind, COLS[0][1], C_TEXT)
        status_tb.ToolTip = c.status_tip()
        cells.Children.Add(status_tb)
        for text, (_, w) in zip((c.number, c.name, c.level_name, c.data_age), COLS[1:5]):
            cells.Children.Add(_cell(text, w, C_TEXT))
        note_tb = _cell("", COLS[5][1], C_SUB)
        cells.Children.Add(note_tb)

        cb = CheckBox()
        cb.Content = cells
        cb.Margin = Thickness(8, 3, 8, 3)
        cb.Foreground = _brush(C_TEXT)
        cb.Click += RoutedEventHandler(lambda s, e: refresh())
        rows_panel.Children.Add(cb)
        hay = u" ".join([c.kind, c.number, c.name, c.level_name, c.note]).lower()
        rows.append({"cb": cb, "c": c, "note": note_tb, "hay": hay})

    toggle.IsEnabled = any(c.can_rebuild_unplaced and not c.can_place for c in cands)

    # ---------------------------------------------------------- handlers
    def on_search(sender, e):
        q = (search.Text or "").strip().lower()
        for r in rows:
            r["cb"].Visibility = Visibility.Visible if (not q or q in r["hay"]) \
                else Visibility.Collapsed

    def on_toggle(sender, e):
        refresh()

    def on_select_ready(sender, e):
        allow = toggle.IsChecked == True
        for r in rows:
            if _restorable(r["c"], allow) and r["cb"].Visibility == Visibility.Visible:
                r["cb"].IsChecked = True
        refresh()

    def on_clear(sender, e):
        for r in rows:
            r["cb"].IsChecked = False
        refresh()

    def on_remove(sender, e):
        targets = [r for r in rows if r["cb"].IsChecked == True and r["c"].kind == "Deleted"]
        if not targets:
            return
        listed = u"\n".join(u"    {}  {}".format(r["c"].number or "(no number)", r["c"].name)
                            for r in targets[:12])
        if len(targets) > 12:
            listed += u"\n    ... and {} more".format(len(targets) - 12)
        msg = (u"Permanently remove {} deleted room(s) from the register?\n\n{}\n\n"
               u"Their stored data is erased and they can no longer be restored.\n"
               u"Selected unplaced rooms are not affected.").format(len(targets), listed)
        answer = MessageBox.Show(win, msg, TITLE, MessageBoxButton.YesNo,
                                 MessageBoxImage.Warning, MessageBoxResult.No)
        if answer != MessageBoxResult.Yes:
            return
        try:
            removed = remove_fn([r["c"].uid for r in targets])
        except Exception as err:
            MessageBox.Show(win, u"Could not update the register, nothing was removed:\n\n{}"
                            .format(err), TITLE, MessageBoxButton.OK, MessageBoxImage.Error)
            return
        for r in targets:
            rows_panel.Children.Remove(r["cb"])
            rows.remove(r)
        state["removed"] += removed
        refresh()

    def on_restore(sender, e):
        allow = toggle.IsChecked == True
        state["selected"] = [r["c"] for r in rows
                             if r["cb"].IsChecked == True and _restorable(r["c"], allow)]
        state["allow"] = allow
        win.Close()

    def on_cancel(sender, e):
        win.Close()

    search.TextChanged += TextChangedEventHandler(on_search)
    toggle.Click += RoutedEventHandler(on_toggle)
    remove_btn.Click += RoutedEventHandler(on_remove)
    win.FindName("SelectReadyBtn").Click += RoutedEventHandler(on_select_ready)
    win.FindName("ClearBtn").Click += RoutedEventHandler(on_clear)
    restore_btn.Click += RoutedEventHandler(on_restore)
    win.FindName("CancelBtn").Click += RoutedEventHandler(on_cancel)
    refresh()

    frame = DispatcherFrame()

    def on_closed(sender, e):
        frame.Continue = False

    win.Closed += EventHandler(on_closed)
    try:
        WindowInteropHelper(win).Owner = __revit__.MainWindowHandle
    except Exception:
        pass
    win.Show()
    Dispatcher.PushFrame(frame)
    return state


# ================================================================= modes
def shift_mode(tracker, doc):
    key = doc_key(doc)
    if not key:
        forms.alert("Save the model first.\n\nAn unsaved document has no stable "
                    "identity to register.", title=TITLE)
        return
    path = find_register(key)
    if path:
        _open_folder(path)
        return
    reg = tracker.create_register(doc)
    forms.alert("Register created for '{}'.\n\n{} rooms recorded.\n"
                "Live tracking runs automatically in every Revit session."
                .format(reg.data.get("doc_title"), len(reg.rooms)), title=TITLE)


def restore_mode(tracker, doc):
    reg = tracker.register_for(doc)
    if reg is None:
        forms.alert("This document has no room register yet.\n\n"
                    "Shift+Click the button to create one.", title=TITLE)
        return

    # safety net: catches anything missed if tracking was interrupted this session
    tracker.rescan_doc(doc, "restore")

    if doc.IsWorkshared:
        choice = forms.alert("Reload Latest before restoring?\n\nRooms that other users "
                             "already restored only become visible after a reload.",
                             title=TITLE, options=["Reload Latest", "Skip"])
        if choice == "Reload Latest":
            try:
                doc.ReloadLatest(ReloadLatestOptions())
            except Exception as e:
                forms.alert("Reload Latest failed:\n\n{}".format(e), title=TITLE)
            reg.rescan(doc, "reload latest")
            if reg.dirty:
                reg.save()

    cands = collect_candidates(doc, reg)
    if not cands:
        forms.alert("No unplaced or deleted rooms in the register.\n\n"
                    "Live tracking is active.", title=TITLE)
        return

    dry_run(doc, cands)
    user = doc.Application.Username
    state = show_menu(cands,
                      "{}   |   {}".format(reg.data.get("doc_title"), os.path.basename(reg.path)),
                      lambda uids: remove_records(reg, uids, user))
    if not state["selected"]:
        return
    results, error = run_restore(doc, reg, state["selected"], state["allow"])
    if error:
        forms.alert(error, title=TITLE)
    elif results:
        report(doc, results)


# ================================================================== main
try:
    SHIFT = __shiftclick__
except NameError:
    SHIFT = False

tracker = ensure_tracker(__revit__)
doc = revit.doc

if doc is None or doc.IsFamilyDocument:
    forms.alert("Open a project document first.", title=TITLE)
elif SHIFT:
    shift_mode(tracker, doc)
else:
    restore_mode(tracker, doc)
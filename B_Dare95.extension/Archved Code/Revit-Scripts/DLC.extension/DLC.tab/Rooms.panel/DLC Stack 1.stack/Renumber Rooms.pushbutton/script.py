# -*- coding: utf-8 -*-
"""
DLC_RenumberRooms - bd_family_cleaner.py  (v1.1.0)
=======================================
Renumbers rooms clockwise, starting from a number you type, over the scope
you choose: Whole Model (one level at a time), Selected Rooms, or Active View.

Ordering methods
----------------
  Pick Starting Room   clockwise angle sweep around the scope's centre,
                       beginning at the room you pick.
  Pick Reference Line  path order along a detail/model line you pick -
                       better for long corridors and non-convex plans.

The number format is taken from whatever you type as the first room number
(101, G-001, L1-05 ...). Prefix, zero-padding and any trailing letter are
detected and carried through the sequence; only the last digit run counts up.

Unplaced / zero-area rooms are always skipped and reported, never numbered.
Numbers are written in two passes (unique temporary numbers, then the final
numbers) so swaps and cycles inside the set never trip Revit's duplicate
room number error.

Author: Ahmed Mohsen - DLC (Diyar Liban Consulting)
"""

import os
import sys

_THIS_DIR = os.path.dirname(__file__)
if _THIS_DIR not in sys.path:
    sys.path.append(_THIS_DIR)

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")
clr.AddReference("System")
clr.AddReference("System.Data")

from Autodesk.Revit.DB import Architecture
from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException

from pyrevit import forms, script, revit

from System.Collections.Generic import List as NetList
from System.Data import DataTable
from System.Windows import Visibility

import dlc_renumber_core as core
import dlc_renumber_revit as rvt


__title__ = "Renumber\nRooms"
__author__ = "Ahmed Mohsen - DLC"
__version__ = "1.1.0"


SETTINGS = {
    "DEFAULT_FIRST_NUMBER": "101",
    "CONFIG_KEY_SCOPE": "last_scope",
    "CONFIG_KEY_METHOD": "last_method",
    "CONFIG_KEY_FIRST_NUMBER": "last_first_number",
    "MAX_COLLISIONS_LISTED": 10,
}

logger = script.get_logger()
output = script.get_output()


# ---------------------------------------------------------------------------
# Context - survives across dialog instances
# ---------------------------------------------------------------------------

class RenumberContext(object):
    """
    Holds everything the dialog needs to rebuild itself identically after it
    has been closed to let the user pick something in the model.

    selected_room_ids is captured ONCE, at launch, on purpose: PickObject
    clears the Revit selection, so re-reading uidoc.Selection after a pick
    would quietly shrink a 'Selected Rooms' scope down to a single room.
    """

    ACTION_NONE = None
    ACTION_PICK_ROOM = "pick_room"
    ACTION_PICK_LINE = "pick_line"

    def __init__(self, doc, uidoc):
        self.doc = doc
        self.uidoc = uidoc

        self.levels = rvt.get_all_levels(doc)
        self.selected_room_ids = list(uidoc.Selection.GetElementIds())
        self.active_view = uidoc.ActiveView

        config = script.get_config()
        self.scope = getattr(config, SETTINGS["CONFIG_KEY_SCOPE"], "whole_model")
        self.method = getattr(config, SETTINGS["CONFIG_KEY_METHOD"], "start_room")
        self.first_number = getattr(
            config, SETTINGS["CONFIG_KEY_FIRST_NUMBER"], SETTINGS["DEFAULT_FIRST_NUMBER"]
        )

        self.level_index = self._default_level_index()
        self.start_room_id = None
        self.picked_curve = None
        self.picked_label = "Nothing picked yet."
        self.action = self.ACTION_NONE

    def _default_level_index(self):
        """Preselect the active view's level when there is one."""
        try:
            view_level = getattr(self.active_view, "GenLevel", None)
            if view_level is not None:
                for index, level in enumerate(self.levels):
                    if level.Id == view_level.Id:
                        return index
        except Exception:
            pass
        return 0 if self.levels else -1

    def save(self):
        config = script.get_config()
        setattr(config, SETTINGS["CONFIG_KEY_SCOPE"], self.scope)
        setattr(config, SETTINGS["CONFIG_KEY_METHOD"], self.method)
        setattr(config, SETTINGS["CONFIG_KEY_FIRST_NUMBER"], self.first_number)
        try:
            script.save_config()
        except Exception:
            logger.debug("Could not persist settings.")

    def clear_pick(self):
        self.start_room_id = None
        self.picked_curve = None
        self.picked_label = "Nothing picked yet."

    def current_rooms(self):
        if self.scope == "whole_model":
            if not self.levels or self.level_index < 0:
                return []
            return rvt.collect_rooms_on_level(
                self.doc, self.levels[self.level_index].Id
            )
        if self.scope == "selected":
            return rvt.collect_rooms_by_ids(self.doc, self.selected_room_ids)
        return rvt.collect_rooms_in_view(self.doc, self.active_view)


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------

XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="DLC Renumber Rooms" Height="660" Width="600"
        WindowStartupLocation="CenterScreen" ResizeMode="CanResize"
        ShowInTaskbar="False">
    <Grid Margin="12">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <GroupBox Header="1. Scope" Grid.Row="0" Margin="0,0,0,8">
            <StackPanel Margin="6">
                <RadioButton x:Name="rbScopeWhole" Content="Whole Model - one level at a time" GroupName="scope" IsChecked="True" Margin="0,2"/>
                <RadioButton x:Name="rbScopeSelected" Content="Selected Rooms - captured when this dialog opened" GroupName="scope" Margin="0,2"/>
                <RadioButton x:Name="rbScopeView" Content="Active View" GroupName="scope" Margin="0,2"/>
                <StackPanel x:Name="pnlLevel" Orientation="Horizontal" Margin="20,6,0,0">
                    <TextBlock Text="Level:" VerticalAlignment="Center" Margin="0,0,8,0"/>
                    <ComboBox x:Name="cmbLevel" Width="280"/>
                </StackPanel>
            </StackPanel>
        </GroupBox>

        <GroupBox Header="2. Clockwise order" Grid.Row="1" Margin="0,0,0,8">
            <StackPanel Margin="6">
                <RadioButton x:Name="rbMethodStartRoom" Content="Pick Starting Room - sweep clockwise from that room" GroupName="method" IsChecked="True" Margin="0,2"/>
                <RadioButton x:Name="rbMethodRefLine" Content="Pick Reference Line - order along a line (corridors)" GroupName="method" Margin="0,2"/>
                <StackPanel Orientation="Horizontal" Margin="20,6,0,0">
                    <Button x:Name="btnPick" Content="Pick in model..." Width="120" Height="26"/>
                    <TextBlock x:Name="txtPicked" Text="Nothing picked yet." VerticalAlignment="Center" Margin="10,0,0,0" TextWrapping="Wrap"/>
                </StackPanel>
            </StackPanel>
        </GroupBox>

        <StackPanel Grid.Row="2" Orientation="Horizontal" Margin="0,0,0,8">
            <TextBlock Text="3. First room number:" VerticalAlignment="Center" Width="150"/>
            <TextBox x:Name="txtFirstNumber" Width="150" Height="24"/>
            <TextBlock Text="  e.g. 101, G-001, L1-05" VerticalAlignment="Center" Foreground="Gray"/>
        </StackPanel>

        <TextBlock x:Name="txtSummary" Grid.Row="3" Text="" Margin="0,0,0,8" TextWrapping="Wrap"/>

        <StackPanel Grid.Row="4" Orientation="Horizontal" Margin="0,0,0,8">
            <Button x:Name="btnPreview" Content="Preview" Width="110" Height="28" Margin="0,0,8,0"/>
            <Button x:Name="btnApply" Content="Apply" Width="110" Height="28" IsEnabled="False"/>
        </StackPanel>

        <TextBlock Grid.Row="5" Text="Preview" FontWeight="Bold" Margin="0,0,0,4"/>

        <DataGrid x:Name="gridPreview" Grid.Row="6" AutoGenerateColumns="True" IsReadOnly="True"
                  CanUserAddRows="False" HeadersVisibility="Column" Margin="0,0,0,8"/>

        <StackPanel Grid.Row="7" Orientation="Horizontal" HorizontalAlignment="Right">
            <Button x:Name="btnClose" Content="Close" Width="100" Height="28"/>
        </StackPanel>
    </Grid>
</Window>
"""


class RenumberRoomsWindow(forms.WPFWindow):
    def __init__(self, xaml_source, ctx):
        try:
            forms.WPFWindow.__init__(self, xaml_source, literal_string=True)
        except TypeError:
            # Older pyRevit builds have no literal_string kwarg.
            import tempfile
            tmp_path = os.path.join(tempfile.gettempdir(), "DLC_RenumberRooms_ui.xaml")
            handle = open(tmp_path, "w")
            try:
                handle.write(xaml_source)
            finally:
                handle.close()
            forms.WPFWindow.__init__(self, tmp_path)

        self.ctx = ctx
        self._pending_plan = None
        self._id_to_room = {}
        self._original_numbers = {}
        self._loading = True

        names = NetList[str]()
        for level in ctx.levels:
            names.Add(rvt.get_element_name(level))
        self.cmbLevel.ItemsSource = names
        if ctx.levels and 0 <= ctx.level_index < len(ctx.levels):
            self.cmbLevel.SelectedIndex = ctx.level_index

        if ctx.scope == "selected":
            self.rbScopeSelected.IsChecked = True
        elif ctx.scope == "view":
            self.rbScopeView.IsChecked = True
        else:
            self.rbScopeWhole.IsChecked = True

        if ctx.method == "ref_line":
            self.rbMethodRefLine.IsChecked = True
        else:
            self.rbMethodStartRoom.IsChecked = True

        self.txtFirstNumber.Text = ctx.first_number
        self.txtPicked.Text = ctx.picked_label

        self.rbScopeWhole.Checked += self._on_scope_changed
        self.rbScopeSelected.Checked += self._on_scope_changed
        self.rbScopeView.Checked += self._on_scope_changed
        self.rbMethodStartRoom.Checked += self._on_method_changed
        self.rbMethodRefLine.Checked += self._on_method_changed
        self.cmbLevel.SelectionChanged += self._on_level_changed
        self.btnPick.Click += self._on_pick_click
        self.btnPreview.Click += self._on_preview_click
        self.btnApply.Click += self._on_apply_click
        self.btnClose.Click += self._on_close_click

        self._loading = False
        self._sync_level_visibility()
        self._refresh_summary()

    # -- helpers -------------------------------------------------------------

    def _sync_level_visibility(self):
        self.pnlLevel.Visibility = (
            Visibility.Visible if self.rbScopeWhole.IsChecked else Visibility.Collapsed
        )

    def _read_scope(self):
        if self.rbScopeSelected.IsChecked:
            return "selected"
        if self.rbScopeView.IsChecked:
            return "view"
        return "whole_model"

    def _read_method(self):
        return "ref_line" if self.rbMethodRefLine.IsChecked else "start_room"

    def _push_to_context(self):
        self.ctx.scope = self._read_scope()
        self.ctx.method = self._read_method()
        self.ctx.first_number = self.txtFirstNumber.Text
        self.ctx.level_index = self.cmbLevel.SelectedIndex

    def _invalidate(self):
        self._pending_plan = None
        self.btnApply.IsEnabled = False
        self.gridPreview.ItemsSource = None

    def _refresh_summary(self):
        if self._loading:
            return
        self._push_to_context()
        try:
            rooms = self.ctx.current_rooms()
        except Exception as error:
            self.txtSummary.Text = "Could not read rooms for this scope: %s" % str(error)
            return
        records, _ = rvt.build_records(rooms)
        placed, skipped = core.filter_placed_rooms(records)
        message = "%d room(s) in scope - %d placed, %d unplaced (will be skipped)." % (
            len(records), len(placed), len(skipped)
        )
        if self.ctx.scope == "selected" and not rooms:
            message += "  Select rooms in Revit, then reopen this tool."
        self.txtSummary.Text = message

    # -- events --------------------------------------------------------------

    def _on_scope_changed(self, sender, args):
        if self._loading:
            return
        self._sync_level_visibility()
        self.ctx.clear_pick()
        self.txtPicked.Text = self.ctx.picked_label
        self._invalidate()
        self._refresh_summary()

    def _on_method_changed(self, sender, args):
        if self._loading:
            return
        self.ctx.clear_pick()
        self.txtPicked.Text = self.ctx.picked_label
        self._invalidate()

    def _on_level_changed(self, sender, args):
        if self._loading:
            return
        self.ctx.clear_pick()
        self.txtPicked.Text = self.ctx.picked_label
        self._invalidate()
        self._refresh_summary()

    def _on_pick_click(self, sender, args):
        """
        Closes the dialog and hands control back to the main loop, which does
        the pick and reopens a fresh dialog. WPF refuses ShowDialog() on a
        window that has already been shown, so hiding and re-showing the same
        instance throws InvalidOperationException - hence close-and-reopen.
        """
        self._push_to_context()
        self.ctx.action = (
            RenumberContext.ACTION_PICK_LINE
            if self.ctx.method == "ref_line"
            else RenumberContext.ACTION_PICK_ROOM
        )
        self.Close()

    def _on_preview_click(self, sender, args):
        self._push_to_context()
        rooms = self.ctx.current_rooms()
        if not rooms:
            forms.alert("No rooms found in the scope you chose.", title="DLC Renumber Rooms")
            return

        records, id_to_room = rvt.build_records(rooms)
        self._id_to_room = id_to_room
        self._original_numbers = dict((r["id"], r["number"]) for r in records)

        try:
            if self.ctx.method == "start_room":
                if self.ctx.start_room_id is None:
                    forms.alert("Pick a starting room first.", title="DLC Renumber Rooms")
                    return
                plan = core.plan_polar_renumber(
                    records, self.ctx.start_room_id, self.ctx.first_number
                )
                path_mode = None
            else:
                if self.ctx.picked_curve is None:
                    forms.alert("Pick a reference line first.", title="DLC Renumber Rooms")
                    return
                pairs, path_mode = rvt.build_path_parameters(records, self.ctx.picked_curve)
                plan = core.plan_path_renumber(records, pairs, self.ctx.first_number)
        except ValueError as error:
            forms.alert(str(error), title="DLC Renumber Rooms")
            return
        except Exception as error:
            logger.error(str(error))
            forms.alert("Could not build the preview: %s" % str(error),
                        title="DLC Renumber Rooms")
            return

        self._pending_plan = plan

        numbers = dict((r["id"], r["number"]) for r in records)
        names = dict((r["id"], r["name"]) for r in records)

        table = DataTable()
        table.Columns.Add("#")
        table.Columns.Add("Old Number")
        table.Columns.Add("Room Name")
        table.Columns.Add("New Number")
        for index, room_id in enumerate(plan["order"]):
            row = table.NewRow()
            row["#"] = str(index + 1)
            row["Old Number"] = numbers.get(room_id, "")
            row["Room Name"] = names.get(room_id, "")
            row["New Number"] = plan["new_numbers"][room_id]
            table.Rows.Add(row)
        self.gridPreview.ItemsSource = table.DefaultView

        notes = ["%d room(s) will be renumbered." % len(plan["order"])]
        if plan["skipped_ids"]:
            notes.append("%d unplaced room(s) skipped." % len(plan["skipped_ids"]))
        if plan.get("unordered_ids"):
            notes.append(
                "%d placed room(s) could not be measured against the line and "
                "keep their current numbers." % len(plan["unordered_ids"])
            )
        if path_mode == "chord":
            notes.append(
                "Some rooms sit beyond the ends of the line, so ordering used the "
                "line's direction rather than the line itself."
            )

        try:
            collisions = rvt.find_external_collisions(
                self.ctx.doc, plan["new_numbers"], plan["order"]
            )
        except Exception:
            collisions = []
        if collisions:
            notes.append(
                "%d of these numbers are already used by rooms outside this scope "
                "(Revit allows it, but you will get duplicate-number warnings)."
                % len(collisions)
            )
            output.print_md("### Numbers already in use outside this scope")
            for number, room_id, room_name in collisions[:SETTINGS["MAX_COLLISIONS_LISTED"]]:
                output.print_md("- **%s** is on room id %s (%s)" % (number, room_id, room_name))
            if len(collisions) > SETTINGS["MAX_COLLISIONS_LISTED"]:
                output.print_md("- ...and %d more."
                                % (len(collisions) - SETTINGS["MAX_COLLISIONS_LISTED"]))

        self.txtSummary.Text = "  ".join(notes)
        self.btnApply.IsEnabled = True

    def _on_apply_click(self, sender, args):
        if not self._pending_plan:
            forms.alert("Run Preview first.", title="DLC Renumber Rooms")
            return

        plan = self._pending_plan
        confirmed = forms.alert(
            "Apply new numbers to %d room(s)?\n\nUse Revit's Undo if you need to "
            "reverse it." % len(plan["order"]),
            title="DLC Renumber Rooms", yes=True, no=True,
        )
        if not confirmed:
            return

        try:
            errors, applied = rvt.apply_rename_plan(
                self.ctx.doc, self._id_to_room, plan["temp_pass"],
                plan["final_pass"], self._original_numbers,
            )
        except Exception as error:
            logger.error(str(error))
            forms.alert("Nothing was changed. Revit reported: %s" % str(error),
                        title="DLC Renumber Rooms")
            return

        self._push_to_context()
        self.ctx.save()

        if errors:
            for message in errors:
                logger.warning(message)
            output.print_md("### DLC Renumber Rooms - %d issue(s)" % len(errors))
            for message in errors:
                output.print_md("- %s" % message)
            forms.alert(
                "Renumbered %d room(s) with %d issue(s).\n\nThe details are in the "
                "pyRevit output window." % (applied, len(errors)),
                title="DLC Renumber Rooms",
            )
        else:
            forms.alert("Renumbered %d room(s)." % applied, title="DLC Renumber Rooms")

        self._invalidate()
        self._refresh_summary()

    def _on_close_click(self, sender, args):
        self._push_to_context()
        self.ctx.action = RenumberContext.ACTION_NONE
        self.Close()


# ---------------------------------------------------------------------------
# Pick handlers - run OUTSIDE the dialog, which is why it closes first
# ---------------------------------------------------------------------------

def do_pick_start_room(ctx):
    rooms = ctx.current_rooms()
    records, _ = rvt.build_records(rooms)
    placed, _ = core.filter_placed_rooms(records)
    scope_ids = set(r["id"] for r in placed)

    if not scope_ids:
        forms.alert("There are no placed rooms in this scope to pick from.",
                    title="DLC Renumber Rooms")
        return

    try:
        reference = ctx.uidoc.Selection.PickObject(
            ObjectType.Element, rvt.RoomPickFilter(),
            "Select the room to start from - numbering runs clockwise from it",
        )
    except OperationCanceledException:
        return
    except Exception as error:
        forms.alert("Could not complete the pick: %s" % str(error),
                    title="DLC Renumber Rooms")
        return

    room = ctx.doc.GetElement(reference.ElementId)
    if not isinstance(room, Architecture.Room):
        forms.alert("That is not a room.", title="DLC Renumber Rooms")
        return

    room_id = room.Id.IntegerValue
    if room_id not in scope_ids:
        forms.alert(
            "That room is not inside the scope you chose. Pick a room on the "
            "selected level, or change the scope.",
            title="DLC Renumber Rooms",
        )
        return

    ctx.start_room_id = room_id
    ctx.picked_curve = None
    ctx.picked_label = "Start room: %s - %s" % (
        rvt.get_room_number(room), rvt.get_room_name(room)
    )


def do_pick_reference_line(ctx):
    try:
        reference = ctx.uidoc.Selection.PickObject(
            ObjectType.Element, rvt.CurvePickFilter(),
            "Select a detail line or model line to set the numbering path",
        )
    except OperationCanceledException:
        return
    except Exception as error:
        forms.alert("Could not complete the pick: %s" % str(error),
                    title="DLC Renumber Rooms")
        return

    element = ctx.doc.GetElement(reference.ElementId)
    curve = getattr(element, "GeometryCurve", None)
    if curve is None:
        forms.alert("That element has no line geometry to follow.",
                    title="DLC Renumber Rooms")
        return

    ctx.picked_curve = curve
    ctx.start_room_id = None
    ctx.picked_label = "Reference line: element id %s" % element.Id.IntegerValue


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    doc = revit.doc
    uidoc = revit.uidoc

    if doc is None:
        forms.alert("Open a Revit project first.", title="DLC Renumber Rooms")
        return
    if doc.IsFamilyDocument:
        forms.alert("This tool runs on projects, not family files.",
                    title="DLC Renumber Rooms")
        return

    ctx = RenumberContext(doc, uidoc)

    if not rvt.collect_all_rooms(doc):
        forms.alert("This model has no rooms to renumber.", title="DLC Renumber Rooms")
        return

    # The dialog closes itself whenever the user needs to pick something in the
    # model, because PickObject cannot run while a modal window is open. The
    # loop then reopens a fresh dialog with all settings carried over.
    guard = 0
    while True:
        guard += 1
        if guard > 200:
            break

        ctx.action = RenumberContext.ACTION_NONE
        window = RenumberRoomsWindow(XAML, ctx)
        window.ShowDialog()

        if ctx.action == RenumberContext.ACTION_PICK_ROOM:
            do_pick_start_room(ctx)
            continue
        if ctx.action == RenumberContext.ACTION_PICK_LINE:
            do_pick_reference_line(ctx)
            continue
        break

    ctx.save()


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-

TOOL_NAME   = "Wipe Unplaced"
__author__  = "Mohamed Bedair"
__version__ = "1.0.0"
__doc__ = """__________________________________________________
Description:

Deletes unplaced rooms, areas and MEP spaces from the model. You choose which of the three to clean and confirm before anything is deleted.
__________________________________________________
How-to:

-> Click on the button
-> Check Rooms, Areas and/or MEP Spaces (counts appear when checked)
-> Click OK
-> Confirm the list of elements to delete
-> A summary shows how many were deleted
__________________________________________________
Author: Mohamed Bedair"""

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')
clr.AddReference('System.Xml')

from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory,
    LocationPoint, TransactionGroup, Transaction
)
from System.Windows import Window, Visibility
from System.Windows.Media import SolidColorBrush, Color
import sys

import bd_core as bd

doc = __revit__.ActiveUIDocument.Document  # noqa: F821

# ─────────────────────────────────────────────────────────────
#  Collectors
# ─────────────────────────────────────────────────────────────

def _is_unplaced_by_location(element):
    """Rooms and Spaces: unplaced when Location is None or has no Point."""
    loc = element.Location
    return loc is None or (isinstance(loc, LocationPoint) and loc.Point is None)


def _is_unplaced_area(element):
    """Areas: unplaced when the Level parameter has no value."""
    param = element.LookupParameter("Level")
    return param is None or not param.HasValue


def _collect(category, predicate):
    return [
        e for e in
        FilteredElementCollector(doc)
            .OfCategory(category)
            .WhereElementIsNotElementType()
            .ToElements()
        if predicate(e)
    ]


unplaced = {
    "Rooms":  _collect(BuiltInCategory.OST_Rooms,      _is_unplaced_by_location),
    "Areas":  _collect(BuiltInCategory.OST_Areas,      _is_unplaced_area),
    "Spaces": _collect(BuiltInCategory.OST_MEPSpaces,  _is_unplaced_by_location),
}

# ─────────────────────────────────────────────────────────────
#  XAML  (Catppuccin dark — bg #161616, accent #F1C21B)
# ─────────────────────────────────────────────────────────────

# Window layout: ui.xaml next to this script (shared colours and styles: lib/bd_theme.xaml)

# ─────────────────────────────────────────────────────────────
#  Build window & wire up events
# ─────────────────────────────────────────────────────────────

window    = bd.load_window(__file__)

chk_rooms  = window.FindName("ChkRooms")
chk_areas  = window.FindName("ChkAreas")
chk_spaces = window.FindName("ChkSpaces")
lbl_rooms  = window.FindName("LblRooms")
lbl_areas  = window.FindName("LblAreas")
lbl_spaces = window.FindName("LblSpaces")
btn_ok     = window.FindName("BtnOK")
btn_cancel = window.FindName("BtnCancel")

ACCENT  = SolidColorBrush(Color.FromRgb(0xF0, 0xA5, 0x00))   # #F1C21B
MUTED   = SolidColorBrush(Color.FromRgb(0xA6, 0xAD, 0xC8))   # #A8A8A8


def _set_count_label(label, count, singular, plural=None):
    plural = plural or singular + "s"
    if count == 0:
        label.Text       = u"\u26a0  No unplaced {} found".format(plural)
        label.Foreground = MUTED
    elif count == 1:
        label.Text       = u"\u2714  1 unplaced {} found".format(singular)
        label.Foreground = ACCENT
    else:
        label.Text       = u"\u2714  {} unplaced {} found".format(count, plural)
        label.Foreground = ACCENT
    label.Visibility = Visibility.Visible


def on_rooms_checked(s, e):
    _set_count_label(lbl_rooms, len(unplaced["Rooms"]), "Room")

def on_rooms_unchecked(s, e):
    lbl_rooms.Visibility = Visibility.Collapsed

def on_areas_checked(s, e):
    _set_count_label(lbl_areas, len(unplaced["Areas"]), "Area")

def on_areas_unchecked(s, e):
    lbl_areas.Visibility = Visibility.Collapsed

def on_spaces_checked(s, e):
    _set_count_label(lbl_spaces, len(unplaced["Spaces"]), "Space")

def on_spaces_unchecked(s, e):
    lbl_spaces.Visibility = Visibility.Collapsed


chk_rooms.Checked    += on_rooms_checked
chk_rooms.Unchecked  += on_rooms_unchecked
chk_areas.Checked    += on_areas_checked
chk_areas.Unchecked  += on_areas_unchecked
chk_spaces.Checked   += on_spaces_checked
chk_spaces.Unchecked += on_spaces_unchecked

# Mutable flag — IronPython 2.7 closure-safe pattern
confirmed = [False]

def on_ok(s, e):
    confirmed[0] = True
    window.Close()

def on_cancel(s, e):
    window.Close()

btn_ok.Click    += on_ok
btn_cancel.Click += on_cancel

window.ShowDialog()

if not confirmed[0]:
    sys.exit()

# ─────────────────────────────────────────────────────────────
#  Build deletion list from checked categories
# ─────────────────────────────────────────────────────────────

to_delete = []  # list of (ElementId, category_label)

if chk_rooms.IsChecked:
    to_delete += [(rm.Id, "Room") for rm in unplaced["Rooms"]]
if chk_areas.IsChecked:
    to_delete += [(ar.Id, "Area") for ar in unplaced["Areas"]]
if chk_spaces.IsChecked:
    to_delete += [(sp.Id, "Space") for sp in unplaced["Spaces"]]

if not to_delete:
    bd.alert(u"No categories were selected. Nothing to purge.", TOOL_NAME, exit=True)

# ─────────────────────────────────────────────────────────────
#  Confirmation dialog
# ─────────────────────────────────────────────────────────────

lines = []
if chk_rooms.IsChecked  and unplaced["Rooms"]:
    lines.append(u"  \u2022 {} Room(s)".format(len(unplaced["Rooms"])))
if chk_areas.IsChecked  and unplaced["Areas"]:
    lines.append(u"  \u2022 {} Area(s)".format(len(unplaced["Areas"])))
if chk_spaces.IsChecked and unplaced["Spaces"]:
    lines.append(u"  \u2022 {} MEP Space(s)".format(len(unplaced["Spaces"])))

confirm_msg = (
    u"The following unplaced elements will be permanently deleted:\n\n"
    + u"\n".join(lines)
    + u"\n\nTotal: {} element(s)\n\nDo you want to proceed?".format(len(to_delete))
)

bd.confirm(confirm_msg, TOOL_NAME, heading=u"Confirm Deletion", default_yes=False, exit=True)

# ─────────────────────────────────────────────────────────────
#  Execute deletions
# ─────────────────────────────────────────────────────────────

tgrp = TransactionGroup(doc, TOOL_NAME)
tgrp.Start()

deleted_count = 0
failed_count  = 0

for elem_id, category_label in to_delete:
    t = Transaction(doc, u"Delete Unplaced {}".format(category_label))
    t.Start()
    try:
        result = doc.Delete(elem_id)
        if result and result.Count > 0:
            deleted_count += 1
        else:
            failed_count += 1
    except Exception:  # noqa: BLE001
        failed_count += 1
    t.Commit()

tgrp.Assimilate()

# ─────────────────────────────────────────────────────────────
#  Summary
# ─────────────────────────────────────────────────────────────

summary = (
    u"Operation complete.\n\n"
    u"  \u2714  Deleted : {}\n"
    u"  \u26a0  Failed  : {}"
).format(deleted_count, failed_count)

bd.alert(summary, TOOL_NAME)
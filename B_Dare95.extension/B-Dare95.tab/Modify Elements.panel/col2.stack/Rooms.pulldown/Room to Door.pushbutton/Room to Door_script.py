# -*- coding: utf-8 -*-
__doc__ = """__________________________________________________
Description:

Copies a value from each door's room (From Room or To Room) into a door parameter, for every door in the model.
You can combine several room parameters with a separator, and add A, B, C or 1, 2, 3 when several doors share the same room.
__________________________________________________
How-to:

-> Click on the button
-> Choose From Room or To Room
-> Pick a room parameter, or several in Combine mode
-> Pick the door parameter to fill
-> Check Add Designator for doors that share a room, if needed
-> Click Run Transfer and check the status line
__________________________________________________
Author: Mohamed Bedair"""


import clr
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')
clr.AddReference('System.Xml')

from Autodesk.Revit.DB import *
import System
from System.Collections.Generic import List
from System.Windows import Window, MessageBox, MessageBoxButton, MessageBoxResult
from System.Windows.Controls import ListBoxItem
from collections import defaultdict
import bd_core as bd

app   = __revit__.Application
doc   = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def collect_parameters_for_category(bic):
    """Return sorted unique parameter names (instance + type) for a given BuiltInCategory."""
    instances = (FilteredElementCollector(doc)
                 .OfCategory(bic)
                 .WhereElementIsNotElementType()
                 .ToElements())
    names = set()
    seen_type_ids = set()
    for el in instances:
        for p in el.Parameters:
            if p.Definition and p.StorageType != StorageType.None:
                names.add(p.Definition.Name)
        type_id = el.GetTypeId()
        if type_id is not None and type_id not in seen_type_ids:
            seen_type_ids.add(type_id)
            el_type = doc.GetElement(type_id)
            if el_type is not None:
                for p in el_type.Parameters:
                    if p.Definition and p.StorageType != StorageType.None:
                        names.add(p.Definition.Name)
    return sorted(names, key=lambda x: x.lower())


def get_param_value_as_string(element, param_name):
    p = element.LookupParameter(param_name)
    if p is None or not p.HasValue:
        return ""
    st = p.StorageType
    if st == StorageType.String:
        v = p.AsString()
        return v if v is not None else ""
    elif st == StorageType.Integer:
        return str(p.AsInteger())
    elif st == StorageType.Double:
        return p.AsValueString() or str(p.AsDouble())
    elif st == StorageType.ElementId:
        eid = p.AsElementId()
        return str(eid.Value if hasattr(eid, 'Value') else eid.IntegerValue)
    return ""


def set_param_value(element, param_name, value):
    p = element.LookupParameter(param_name)
    if p is None or p.IsReadOnly:
        return False
    try:
        if p.StorageType == StorageType.String:
            p.Set(value)
        else:
            p.SetValueString(value)
        return True
    except Exception:
        return False


def get_element_id_int(element):
    return bd.eid_int(element.Id)


def to_alpha_designator(rank):
    """0→A, 1→B, …, 25→Z, 26→AA, 27→AB, …"""
    if rank < 26:
        return chr(ord('A') + rank)
    return chr(ord('A') + rank // 26 - 1) + chr(ord('A') + rank % 26)


def get_last_phase():
    phases = doc.Phases
    return phases[phases.Size - 1]


# ──────────────────────────────────────────────
# XAML
# ──────────────────────────────────────────────

# Window layout: ui.xaml next to this script (shared colours and styles: lib/bd_theme.xaml)

# ──────────────────────────────────────────────
# Build window
# ──────────────────────────────────────────────

window = bd.load_window(__file__)

rb_from    = window.FindName("rbFromRoom")
rb_to      = window.FindName("rbToRoom")
rb_single  = window.FindName("rbSingle")
rb_combine = window.FindName("rbCombine")

tb_room_search = window.FindName("tbRoomSearch")
tb_door_search = window.FindName("tbDoorSearch")
lb_room        = window.FindName("lbRoomParams")
lb_door        = window.FindName("lbDoorParams")

pnl_combine      = window.FindName("pnlCombine")
lb_combine_order = window.FindName("lbCombineOrder")
btn_add_combine  = window.FindName("btnAddCombine")
btn_rem_combine  = window.FindName("btnRemoveCombine")
btn_up           = window.FindName("btnMoveUp")
btn_down         = window.FindName("btnMoveDown")
tb_sep           = window.FindName("tbSeparator")

chk_designator  = window.FindName("chkDesignator")
pnl_des_opts    = window.FindName("pnlDesignatorOpts")
rb_des_alpha    = window.FindName("rbDesAlpha")
rb_des_num      = window.FindName("rbDesNum")
tb_des_sep      = window.FindName("tbDesSep")

tb_status    = window.FindName("tbStatus")
btn_run      = window.FindName("btnRun")
btn_cancel   = window.FindName("btnCancel")
tb_room_note = window.FindName("tbRoomSideNote")

# ──────────────────────────────────────────────
# Parameter lists
# ──────────────────────────────────────────────

all_room_params = collect_parameters_for_category(BuiltInCategory.OST_Rooms)
all_door_params = collect_parameters_for_category(BuiltInCategory.OST_Doors)


def populate_list(listbox, items, filter_text=""):
    listbox.Items.Clear()
    ft = filter_text.strip().lower()
    for name in items:
        if ft and ft not in name.lower():
            continue
        item = ListBoxItem()
        item.Content = name
        listbox.Items.Add(item)


populate_list(lb_room, all_room_params)
populate_list(lb_door, all_door_params)

# ──────────────────────────────────────────────
# Search
# ──────────────────────────────────────────────

def on_room_search(sender, e):
    populate_list(lb_room, all_room_params, tb_room_search.Text)

def on_door_search(sender, e):
    populate_list(lb_door, all_door_params, tb_door_search.Text)

tb_room_search.TextChanged += on_room_search
tb_door_search.TextChanged += on_door_search

# ──────────────────────────────────────────────
# Room-side toggle label
# ──────────────────────────────────────────────

def on_room_side_changed(sender, e):
    tb_room_note.Text = "Using FromRoom" if rb_from.IsChecked == True else "Using ToRoom"

rb_from.Checked += on_room_side_changed
rb_to.Checked   += on_room_side_changed

# ──────────────────────────────────────────────
# Mode toggle
# ──────────────────────────────────────────────

def on_mode_changed(sender, e):
    if rb_combine.IsChecked == True:
        pnl_combine.Visibility = System.Windows.Visibility.Visible
        lb_room.SelectionMode = System.Windows.Controls.SelectionMode.Extended
    else:
        pnl_combine.Visibility = System.Windows.Visibility.Collapsed
        lb_room.SelectionMode = System.Windows.Controls.SelectionMode.Extended

rb_single.Checked  += on_mode_changed
rb_combine.Checked += on_mode_changed

# ──────────────────────────────────────────────
# Designator toggle
# ──────────────────────────────────────────────

def on_designator_toggle(sender, e):
    if chk_designator.IsChecked == True:
        pnl_des_opts.Visibility = System.Windows.Visibility.Visible
    else:
        pnl_des_opts.Visibility = System.Windows.Visibility.Collapsed

chk_designator.Checked   += on_designator_toggle
chk_designator.Unchecked += on_designator_toggle

# ──────────────────────────────────────────────
# Combine order controls
# ──────────────────────────────────────────────

def on_add_combine(sender, e):
    selected = [item.Content for item in lb_room.SelectedItems]
    existing = [lb_combine_order.Items.GetItemAt(i).Content
                for i in range(lb_combine_order.Items.Count)]
    for name in selected:
        if name not in existing:
            item = ListBoxItem()
            item.Content = name
            lb_combine_order.Items.Add(item)

def on_remove_combine(sender, e):
    sel = lb_combine_order.SelectedItem
    if sel is not None:
        lb_combine_order.Items.Remove(sel)

def on_move_up(sender, e):
    idx = lb_combine_order.SelectedIndex
    if idx > 0:
        item = lb_combine_order.Items.GetItemAt(idx)
        lb_combine_order.Items.RemoveAt(idx)
        lb_combine_order.Items.Insert(idx - 1, item)
        lb_combine_order.SelectedIndex = idx - 1

def on_move_down(sender, e):
    idx = lb_combine_order.SelectedIndex
    count = lb_combine_order.Items.Count
    if 0 <= idx < count - 1:
        item = lb_combine_order.Items.GetItemAt(idx)
        lb_combine_order.Items.RemoveAt(idx)
        lb_combine_order.Items.Insert(idx + 1, item)
        lb_combine_order.SelectedIndex = idx + 1

btn_add_combine.Click  += on_add_combine
btn_rem_combine.Click  += on_remove_combine
btn_up.Click           += on_move_up
btn_down.Click         += on_move_down

# ──────────────────────────────────────────────
# Run
# ──────────────────────────────────────────────

def on_run(sender, e):
    phase        = get_last_phase()
    use_from     = (rb_from.IsChecked == True)
    is_combine   = (rb_combine.IsChecked == True)
    use_designator = (chk_designator.IsChecked == True)

    # ── Validate door param ──
    door_param_item = lb_door.SelectedItem
    if door_param_item is None:
        tb_status.Text = "Please select a door parameter."
        return
    door_param_name = door_param_item.Content

    # ── Validate room params ──
    if is_combine:
        room_param_names = [lb_combine_order.Items.GetItemAt(i).Content
                            for i in range(lb_combine_order.Items.Count)]
        if not room_param_names:
            tb_status.Text = "Add at least one room parameter to the combine list."
            return
        combine_sep = tb_sep.Text
    else:
        room_param_item = lb_room.SelectedItem
        if room_param_item is None:
            tb_status.Text = "Please select a room parameter."
            return
        room_param_names = [room_param_item.Content]
        combine_sep = ""

    # ── Designator settings ──
    is_alpha  = (rb_des_alpha.IsChecked == True)
    des_sep   = tb_des_sep.Text if use_designator else ""

    # ── Collect all doors ──
    all_doors = (FilteredElementCollector(doc)
                 .OfCategory(BuiltInCategory.OST_Doors)
                 .WhereElementIsNotElementType()
                 .ToElements())

    no_room    = 0
    skip_count = 0
    no_param   = 0
    read_only  = 0

    # ── Pass 1: compute base values + level key ──
    # record = (door, base_value, level_key)
    # level_key = str(room.LevelId)  — resets designator per level
    records = []

    for door in all_doors:
        try:
            room = door.FromRoom[phase] if use_from else door.ToRoom[phase]
        except Exception:
            room = None

        if room is None:
            no_room += 1
            continue

        if is_combine:
            parts = [get_param_value_as_string(room, n) for n in room_param_names]
            base_value = combine_sep.join(parts)
        else:
            base_value = get_param_value_as_string(room, room_param_names[0])

        if base_value == "":
            skip_count += 1
            continue

        # Level key from the room's LevelId
        try:
            lvl_id = room.LevelId
            level_key = str(lvl_id.Value if hasattr(lvl_id, 'Value') else lvl_id.IntegerValue)
        except Exception:
            level_key = "none"

        records.append((door, base_value, level_key))

    # ── Pass 2: build designator map ──
    # Group key = (base_value, level_key)
    # This means: same room number on a different level starts its own A/B/C sequence.
    designator_map = {}   # record index -> designator string

    if use_designator and records:
        groups = defaultdict(list)
        for i, (door, val, lvl) in enumerate(records):
            groups[(val, lvl)].append(i)

        for grp_indices in groups.values():
            if len(grp_indices) < 2:
                continue  # single door — no designator needed
            # Sort within group by ElementId for a deterministic, stable order
            grp_indices.sort(key=lambda i: get_element_id_int(records[i][0]))
            for rank, idx in enumerate(grp_indices):
                designator_map[idx] = (
                    to_alpha_designator(rank) if is_alpha else str(rank + 1)
                )

    # ── Pass 3: write to Revit in a single transaction ──
    ok_count = 0

    t = Transaction(doc, "Room to Door Parameter Transfer")
    t.Start()
    try:
        for i, (door, base_value, _) in enumerate(records):
            if use_designator and i in designator_map:
                final_value = base_value + des_sep + designator_map[i]
            else:
                final_value = base_value

            success = set_param_value(door, door_param_name, final_value)
            if success:
                ok_count += 1
            else:
                dp = door.LookupParameter(door_param_name)
                if dp is None:
                    no_param += 1
                elif dp.IsReadOnly:
                    read_only += 1
                else:
                    skip_count += 1

        t.Commit()

        parts = ["Transfer complete —", "{} updated".format(ok_count)]
        if no_room:    parts.append("{} had no room".format(no_room))
        if skip_count: parts.append("{} skipped".format(skip_count))
        if no_param:   parts.append("{} missing param".format(no_param))
        if read_only:  parts.append("{} read-only".format(read_only))
        if use_designator:
            parts.append("{} designators assigned".format(len(designator_map)))
        tb_status.Text = "  |  ".join(parts)

    except Exception as ex:
        t.RollBack()
        tb_status.Text = "Error: {}".format(str(ex))


def on_cancel(sender, e):
    window.Close()

btn_run.Click    += on_run
btn_cancel.Click += on_cancel

# ──────────────────────────────────────────────
# Show
# ──────────────────────────────────────────────

window.ShowDialog()
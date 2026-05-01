# -*- coding: utf-8 -*-
# Author: Mohamed Bedair

import os
import clr

clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")

import System.Drawing
import System.Windows.Forms as WinForms

from Autodesk.Revit.DB import *
from pyrevit import forms, script

PATH_SCRIPT = os.path.dirname(__file__)

app         = __revit__.Application
doc         = __revit__.ActiveUIDocument.Document
uidoc       = __revit__.ActiveUIDocument
active_view = doc.ActiveView

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def room_label(room):
    number    = room.get_Parameter(BuiltInParameter.ROOM_NUMBER).AsValueString() or "?"
    name      = room.get_Parameter(BuiltInParameter.ROOM_NAME).AsValueString()   or "Unnamed"
    is_placed = room.get_Parameter(BuiltInParameter.ROOM_AREA).AsDouble() != 0
    suffix    = "" if is_placed else "  [⚠ Unplaced]"
    return "{} - {}{}".format(number, name, suffix)


def get_user_worksets():
    """Returns a name→Workset dict, or empty dict if not workshared."""
    if not doc.IsWorkshared:
        return {}
    ws_list = (FilteredWorksetCollector(doc)
               .OfKind(WorksetKind.UserWorkset)
               .ToWorksets())
    return {ws.Name: ws for ws in ws_list}


def show_main_dialog(room_map, workset_map, default_rgb, default_transparency):
    """Single combined WinForms dialog.
    Returns (selected_labels, revit_color, transparency_int, workset_or_none)
    or (None, None, None, None) on cancel."""

    # ── Mutable closure containers ────────────
    chosen_drawing_color = [System.Drawing.Color.FromArgb(
        default_rgb[0], default_rgb[1], default_rgb[2]
    )]
    # Tracks checked state across search filtering
    checked_labels = [[]]

    # ── Fonts ─────────────────────────────────
    font_normal  = System.Drawing.Font("Segoe UI", 9)
    font_bold    = System.Drawing.Font("Segoe UI", 9,  System.Drawing.FontStyle.Bold)
    font_small   = System.Drawing.Font("Segoe UI", 8)
    font_mono    = System.Drawing.Font("Consolas",  9)
    font_mono_lg = System.Drawing.Font("Consolas", 10, System.Drawing.FontStyle.Bold)

    # ── Catppuccin Mocha palette ──────────────
    BG        = System.Drawing.Color.FromArgb(30,  30,  46)   # #1E1E2E  base
    BG_CARD   = System.Drawing.Color.FromArgb(42,  42,  60)   # #2A2A3C  card
    BG_CTRL   = System.Drawing.Color.FromArgb(49,  50,  68)   # #313244  surface0
    BG_BTN    = System.Drawing.Color.FromArgb(69,  71,  90)   # #45475A  surface1
    BG_ACCENT = System.Drawing.Color.FromArgb(240, 165,  0)   # #F0A500  accent
    FG        = System.Drawing.Color.FromArgb(205, 214, 244)   # #CDD6F4  text
    FG_DIM    = System.Drawing.Color.FromArgb(166, 173, 200)   # #A6ADC8  subtext1
    FG_LABEL  = System.Drawing.Color.FromArgb(166, 173, 200)   # #A6ADC8  subtext1
    BORDER    = System.Drawing.Color.FromArgb(69,  71,  90)   # #45475A  surface1
    DIVIDER   = System.Drawing.Color.FromArgb(42,  42,  60)   # #2A2A3C  card

    # ══════════════════════════════════════════
    # FORM
    # ══════════════════════════════════════════
    form = WinForms.Form()
    form.Text            = "3D Room Visualization"
    form.Width           = 700
    form.Height          = 600
    form.StartPosition   = WinForms.FormStartPosition.CenterScreen
    form.FormBorderStyle = WinForms.FormBorderStyle.FixedDialog
    form.MaximizeBox     = False
    form.MinimizeBox     = False
    form.BackColor       = BG
    form.ForeColor       = FG

    # ══════════════════════════════════════════
    # LEFT — Room list
    # ══════════════════════════════════════════
    lbl_rooms = WinForms.Label()
    lbl_rooms.Text      = "ROOMS"
    lbl_rooms.Font      = font_bold
    lbl_rooms.ForeColor = FG_LABEL
    lbl_rooms.Location  = System.Drawing.Point(20, 18)
    lbl_rooms.Size      = System.Drawing.Size(295, 18)

    # Search bar
    search_box = WinForms.TextBox()
    search_box.Location    = System.Drawing.Point(20, 42)
    search_box.Size        = System.Drawing.Size(295, 26)
    search_box.Font        = font_normal
    search_box.BackColor   = BG_CTRL
    search_box.ForeColor   = FG
    search_box.BorderStyle = WinForms.BorderStyle.FixedSingle

    # Placeholder text behaviour
    PLACEHOLDER = "Search rooms..."
    search_box.Text      = PLACEHOLDER
    search_box.ForeColor = FG_DIM

    def on_search_enter(sender, e):
        if search_box.Text == PLACEHOLDER:
            search_box.Text      = ""
            search_box.ForeColor = FG

    def on_search_leave(sender, e):
        if search_box.Text.strip() == "":
            search_box.Text      = PLACEHOLDER
            search_box.ForeColor = FG_DIM

    search_box.Enter += on_search_enter
    search_box.Leave += on_search_leave

    # Room checklist
    room_list = WinForms.CheckedListBox()
    room_list.Location     = System.Drawing.Point(20, 74)
    room_list.Size         = System.Drawing.Size(295, 355)
    room_list.Font         = font_normal
    room_list.CheckOnClick = True
    room_list.BackColor    = BG_CTRL
    room_list.ForeColor    = FG
    room_list.BorderStyle  = WinForms.BorderStyle.None

    all_sorted_labels = sorted(room_map.keys())

    def populate_list(filter_text=""):
        """Repopulate the checklist, restoring checked states after filtering."""
        room_list.ItemCheck -= on_item_check     # disconnect to avoid phantom events
        room_list.Items.Clear()
        ft = filter_text.lower()
        for label in all_sorted_labels:
            if ft in label.lower():
                room_list.Items.Add(label)
                if label in checked_labels[0]:
                    room_list.SetItemChecked(room_list.Items.Count - 1, True)
        room_list.ItemCheck += on_item_check     # reconnect

    def on_item_check(sender, e):
        """ItemCheck fires BEFORE the state changes — use e.NewValue."""
        label = str(room_list.Items[e.Index])
        if e.NewValue == WinForms.CheckState.Checked:
            if label not in checked_labels[0]:
                checked_labels[0].append(label)
        else:
            if label in checked_labels[0]:
                checked_labels[0].remove(label)

    def on_search_changed(sender, e):
        query = search_box.Text
        if query == PLACEHOLDER:
            query = ""
        populate_list(query)

    room_list.ItemCheck        += on_item_check
    search_box.TextChanged     += on_search_changed

    populate_list()   # initial fill

    # Select All / None
    def make_small_btn(text, x):
        b = WinForms.Button()
        b.Text      = text
        b.Location  = System.Drawing.Point(x, 437)
        b.Size      = System.Drawing.Size(100, 26)
        b.Font      = font_small
        b.FlatStyle = WinForms.FlatStyle.Flat
        b.BackColor = BG_BTN
        b.ForeColor = FG
        b.FlatAppearance.BorderColor = BORDER
        return b

    btn_all  = make_small_btn("Select All",  20)
    btn_none = make_small_btn("Select None", 128)

    def on_select_all(sender, e):
        # Check only visible (filtered) items
        for i in range(room_list.Items.Count):
            label = str(room_list.Items[i])
            if label not in checked_labels[0]:
                checked_labels[0].append(label)
        populate_list(search_box.Text if search_box.Text != PLACEHOLDER else "")

    def on_select_none(sender, e):
        # Uncheck only visible (filtered) items
        for i in range(room_list.Items.Count):
            label = str(room_list.Items[i])
            if label in checked_labels[0]:
                checked_labels[0].remove(label)
        populate_list(search_box.Text if search_box.Text != PLACEHOLDER else "")

    btn_all.Click  += on_select_all
    btn_none.Click += on_select_none

    # ── Vertical divider ──────────────────────
    divider = WinForms.Panel()
    divider.Location  = System.Drawing.Point(333, 15)
    divider.Size      = System.Drawing.Size(1, 490)
    divider.BackColor = DIVIDER

    # ══════════════════════════════════════════
    # RIGHT — Color
    # ══════════════════════════════════════════
    RX = 352   # right-panel X origin

    lbl_color = WinForms.Label()
    lbl_color.Text      = "COLOR"
    lbl_color.Font      = font_bold
    lbl_color.ForeColor = FG_LABEL
    lbl_color.Location  = System.Drawing.Point(RX, 18)
    lbl_color.Size      = System.Drawing.Size(310, 18)

    color_swatch = WinForms.Panel()
    color_swatch.Location    = System.Drawing.Point(RX, 42)
    color_swatch.Size        = System.Drawing.Size(310, 85)
    color_swatch.BackColor   = chosen_drawing_color[0]
    color_swatch.BorderStyle = WinForms.BorderStyle.None
    color_swatch.Cursor      = WinForms.Cursors.Hand

    lbl_swatch_hint = WinForms.Label()
    lbl_swatch_hint.Text      = "click to change"
    lbl_swatch_hint.Font      = font_small
    lbl_swatch_hint.ForeColor = FG_DIM
    lbl_swatch_hint.BackColor = System.Drawing.Color.Transparent
    lbl_swatch_hint.TextAlign = System.Drawing.ContentAlignment.MiddleCenter
    lbl_swatch_hint.Dock      = WinForms.DockStyle.Fill
    color_swatch.Controls.Add(lbl_swatch_hint)

    lbl_hex = WinForms.Label()
    lbl_hex.Text      = "#{:02X}{:02X}{:02X}".format(*default_rgb)
    lbl_hex.Font      = font_mono
    lbl_hex.ForeColor = FG_DIM
    lbl_hex.Location  = System.Drawing.Point(RX, 133)
    lbl_hex.Size      = System.Drawing.Size(310, 18)
    lbl_hex.TextAlign = System.Drawing.ContentAlignment.MiddleCenter

    def open_color_dialog(sender, e):
        dlg          = WinForms.ColorDialog()
        dlg.Color    = chosen_drawing_color[0]
        dlg.FullOpen = True
        if dlg.ShowDialog() == WinForms.DialogResult.OK:
            chosen_drawing_color[0] = dlg.Color
            color_swatch.BackColor  = dlg.Color
            lbl_hex.Text = "#{:02X}{:02X}{:02X}".format(
                int(dlg.Color.R), int(dlg.Color.G), int(dlg.Color.B)
            )

    color_swatch.Click    += open_color_dialog
    lbl_swatch_hint.Click += open_color_dialog

    # ── Transparency ──────────────────────────
    lbl_trans_title = WinForms.Label()
    lbl_trans_title.Text      = "TRANSPARENCY"
    lbl_trans_title.Font      = font_bold
    lbl_trans_title.ForeColor = FG_LABEL
    lbl_trans_title.Location  = System.Drawing.Point(RX, 165)
    lbl_trans_title.Size      = System.Drawing.Size(210, 18)

    lbl_trans_value = WinForms.Label()
    lbl_trans_value.Text      = "{}%".format(default_transparency)
    lbl_trans_value.Font      = font_mono_lg
    lbl_trans_value.ForeColor = FG
    lbl_trans_value.Location  = System.Drawing.Point(RX + 210, 162)
    lbl_trans_value.Size      = System.Drawing.Size(100, 22)
    lbl_trans_value.TextAlign = System.Drawing.ContentAlignment.MiddleRight

    slider = WinForms.TrackBar()
    slider.Location      = System.Drawing.Point(RX - 4, 188)
    slider.Size          = System.Drawing.Size(318, 40)
    slider.Minimum       = 0
    slider.Maximum       = 100
    slider.Value         = default_transparency
    slider.TickFrequency = 10
    slider.LargeChange   = 10
    slider.SmallChange   = 1
    slider.BackColor     = BG

    lbl_trans_min = WinForms.Label()
    lbl_trans_min.Text      = "0%"
    lbl_trans_min.Font      = font_small
    lbl_trans_min.ForeColor = FG_DIM
    lbl_trans_min.Location  = System.Drawing.Point(RX, 228)
    lbl_trans_min.Size      = System.Drawing.Size(30, 16)

    lbl_trans_max = WinForms.Label()
    lbl_trans_max.Text      = "100%"
    lbl_trans_max.Font      = font_small
    lbl_trans_max.ForeColor = FG_DIM
    lbl_trans_max.Location  = System.Drawing.Point(RX + 272, 228)
    lbl_trans_max.Size      = System.Drawing.Size(38, 16)

    def on_slider_change(sender, e):
        lbl_trans_value.Text = "{}%".format(slider.Value)

    slider.ValueChanged += on_slider_change

    # ── Workset drop-down ─────────────────────
    lbl_workset = WinForms.Label()
    lbl_workset.Text      = "WORKSET"
    lbl_workset.Font      = font_bold
    lbl_workset.ForeColor = FG_LABEL
    lbl_workset.Location  = System.Drawing.Point(RX, 262)
    lbl_workset.Size      = System.Drawing.Size(310, 18)

    workset_combo = WinForms.ComboBox()
    workset_combo.Location         = System.Drawing.Point(RX, 285)
    workset_combo.Size             = System.Drawing.Size(310, 26)
    workset_combo.Font             = font_normal
    workset_combo.BackColor        = BG_CTRL
    workset_combo.ForeColor        = FG
    workset_combo.FlatStyle        = WinForms.FlatStyle.Flat
    workset_combo.DropDownStyle    = WinForms.ComboBoxStyle.DropDownList

    if workset_map:
        for ws_name in sorted(workset_map.keys()):
            workset_combo.Items.Add(ws_name)
        workset_combo.SelectedIndex = 0
    else:
        workset_combo.Items.Add("Not workshared / no worksets")
        workset_combo.SelectedIndex = 0
        workset_combo.Enabled       = False
        workset_combo.ForeColor     = FG_DIM

    # ══════════════════════════════════════════
    # BOTTOM BUTTONS
    # ══════════════════════════════════════════
    btn_visualize = WinForms.Button()
    btn_visualize.Text             = "Visualize →"
    btn_visualize.Location         = System.Drawing.Point(462, 522)
    btn_visualize.Size             = System.Drawing.Size(120, 32)
    btn_visualize.Font             = font_bold
    btn_visualize.FlatStyle        = WinForms.FlatStyle.Flat
    btn_visualize.BackColor        = BG_ACCENT
    btn_visualize.ForeColor        = System.Drawing.Color.White
    btn_visualize.DialogResult     = WinForms.DialogResult.OK
    btn_visualize.FlatAppearance.BorderSize = 0

    btn_cancel = WinForms.Button()
    btn_cancel.Text            = "Cancel"
    btn_cancel.Location        = System.Drawing.Point(594, 522)
    btn_cancel.Size            = System.Drawing.Size(80, 32)
    btn_cancel.Font            = font_normal
    btn_cancel.FlatStyle       = WinForms.FlatStyle.Flat
    btn_cancel.BackColor       = BG_BTN
    btn_cancel.ForeColor       = FG
    btn_cancel.DialogResult    = WinForms.DialogResult.Cancel
    btn_cancel.FlatAppearance.BorderColor = BORDER

    form.AcceptButton = btn_visualize
    form.CancelButton = btn_cancel

    # ── Add all controls ──────────────────────
    for ctrl in [
        lbl_rooms, search_box, room_list, btn_all, btn_none,
        divider,
        lbl_color, color_swatch, lbl_hex,
        lbl_trans_title, lbl_trans_value, slider, lbl_trans_min, lbl_trans_max,
        lbl_workset, workset_combo,
        btn_visualize, btn_cancel,
    ]:
        form.Controls.Add(ctrl)

    result = form.ShowDialog()

    if result != WinForms.DialogResult.OK:
        return None, None, None, None

    if not checked_labels[0]:
        forms.alert("No rooms were checked. Please select at least one room.")
        return None, None, None, None

    c           = chosen_drawing_color[0]
    revit_color = Color(int(c.R), int(c.G), int(c.B))

    chosen_workset = None
    if workset_map and workset_combo.Enabled and workset_combo.SelectedItem:
        chosen_workset = workset_map.get(str(workset_combo.SelectedItem))

    return list(checked_labels[0]), revit_color, slider.Value, chosen_workset


def build_overrides(revit_color, solid_pattern, transparency):
    ogs = OverrideGraphicSettings()
    ogs.SetSurfaceForegroundPatternId(solid_pattern.Id)
    ogs.SetSurfaceForegroundPatternColor(revit_color)
    ogs.SetCutForegroundPatternId(solid_pattern.Id)
    ogs.SetCutForegroundPatternColor(revit_color)
    ogs.SetSurfaceTransparency(transparency)
    return ogs


def create_room_shapes(selected_rooms, overrides, calculator, workset_id):
    created_ids = []
    skipped     = []

    tgrp = TransactionGroup(doc, "3D Room Visualization")
    tgrp.Start()

    t = Transaction(doc, "Create 3D Room Shapes")
    t.Start()

    for room in selected_rooms:
        try:
            results    = calculator.CalculateSpatialElementGeometry(room)
            room_solid = results.GetGeometry()

            ds = DirectShape.CreateElement(doc, ElementId(BuiltInCategory.OST_GenericModel))
            ds.SetShape([room_solid])

            number = room.get_Parameter(BuiltInParameter.ROOM_NUMBER).AsValueString() or "?"
            name   = room.get_Parameter(BuiltInParameter.ROOM_NAME).AsValueString()   or "Unnamed"

            comment_param = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
            if comment_param and not comment_param.IsReadOnly:
                comment_param.Set("{} - {}".format(name, number))

            if workset_id is not None:
                ws_param = ds.get_Parameter(BuiltInParameter.ELEM_PARTITION_PARAM)
                if ws_param and not ws_param.IsReadOnly:
                    ws_param.Set(workset_id.IntegerValue)

            active_view.SetElementOverrides(ds.Id, overrides)
            created_ids.append(ds.Id)

        except Exception as e:
            lbl = room_label(room)
            skipped.append(lbl)
            print("Skipped [{}]: {}".format(lbl, e))
            continue

    t.Commit()
    tgrp.Assimilate()

    return created_ids, skipped


# ─────────────────────────────────────────────
# ONE-TIME SETUP
# ─────────────────────────────────────────────

all_patterns  = FilteredElementCollector(doc).OfClass(FillPatternElement).ToElements()
solid_pattern = next((p for p in all_patterns if p.GetFillPattern().IsSolidFill), None)

if solid_pattern is None:
    forms.alert("No solid fill pattern found in the document.", exitscript=True)

calculator = SpatialElementGeometryCalculator(doc)

# ─────────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────────

last_rgb          = (89, 42, 250)
last_transparency = 25

while True:

    all_rooms = (FilteredElementCollector(doc)
                 .OfCategory(BuiltInCategory.OST_Rooms)
                 .WhereElementIsNotElementType()
                 .ToElements())

    if not all_rooms:
        forms.alert("No rooms found in the active document.")
        break

    room_map    = {room_label(r): r for r in all_rooms}
    workset_map = get_user_worksets()

    selected_labels, chosen_color, chosen_transparency, chosen_workset = show_main_dialog(
        room_map, workset_map, last_rgb, last_transparency
    )

    if selected_labels is None:
        break

    last_rgb          = (chosen_color.Red, chosen_color.Green, chosen_color.Blue)
    last_transparency = chosen_transparency
    selected_rooms    = [room_map[label] for label in selected_labels if label in room_map]
    overrides         = build_overrides(chosen_color, solid_pattern, chosen_transparency)
    workset_id        = chosen_workset.Id if chosen_workset else None

    created_ids, skipped = create_room_shapes(selected_rooms, overrides, calculator, workset_id)

    summary = "{} room shape(s) created on workset: {}.".format(
        len(created_ids),
        chosen_workset.Name if chosen_workset else "N/A"
    )
    if skipped:
        summary += "\n\n{} room(s) skipped (no valid geometry):\n  {}".format(
            len(skipped), "\n  ".join(skipped)
        )
    forms.alert(summary, title="3D Room Visualization")

    repeat = forms.alert(
        "Would you like to visualize another set of rooms?",
        title  = "3D Room Visualization",
        ok     = True,
        cancel = True,
    )

    if not repeat:
        break
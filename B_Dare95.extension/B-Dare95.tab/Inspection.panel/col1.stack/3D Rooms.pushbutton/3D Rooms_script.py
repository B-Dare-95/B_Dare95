# -*- coding: utf-8 -*-
# Author: Mohamed Bedair

import os
import clr

clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")

import System.Drawing
from System.Windows.Forms import ColorDialog, DialogResult

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
    number = room.get_Parameter(BuiltInParameter.ROOM_NUMBER).AsValueString() or "?"
    name   = room.get_Parameter(BuiltInParameter.ROOM_NAME).AsValueString()   or "Unnamed"
    return "{} - {}".format(number, name)


def pick_color(default_rgb=(89, 42, 250)):
    """Open a Windows color-picker dialog.
    Returns a Revit Color on OK, or the default color if the user cancels."""
    dialog          = ColorDialog()
    dialog.Color    = System.Drawing.Color.FromArgb(default_rgb[0], default_rgb[1], default_rgb[2])
    dialog.FullOpen = True

    if dialog.ShowDialog() == DialogResult.OK:
        c = dialog.Color
        return Color(int(c.R), int(c.G), int(c.B))
    else:
        return Color(default_rgb[0], default_rgb[1], default_rgb[2])


def build_overrides(revit_color, solid_pattern):
    """Build and return an OverrideGraphicSettings object."""
    ogs = OverrideGraphicSettings()
    ogs.SetSurfaceForegroundPatternId(solid_pattern.Id)
    ogs.SetSurfaceForegroundPatternColor(revit_color)
    ogs.SetCutForegroundPatternId(solid_pattern.Id)
    ogs.SetCutForegroundPatternColor(revit_color)
    return ogs


def pick_workset():
    """Prompt the user to select a workset from the document's user worksets.
    Returns the selected Workset object, None if doc is not workshared,
    or raises SystemExit if the user cancels."""
    if not doc.IsWorkshared:
        forms.alert(
            "This document is not workshared. Workset assignment will be skipped.",
            title="Worksets"
        )
        return None

    all_worksets = FilteredWorksetCollector(doc)\
                    .OfKind(WorksetKind.UserWorkset)\
                    .ToWorksets()

    workset_map = {ws.Name: ws for ws in all_worksets}

    if not workset_map:
        forms.alert(
            "No user worksets found in the document. Workset assignment will be skipped.",
            title="Worksets"
        )
        return None

    chosen = forms.SelectFromList.show(
        sorted(workset_map.keys()),
        title       = "Select a Workset",
        width       = 380,
        button_name = "Assign Workset",
        multiselect = False,
    )

    # Return sentinel value so the caller can detect cancellation
    # without calling script.exit() here
    if not chosen:
        return "CANCELLED"

    return workset_map[chosen]


def create_room_shapes(selected_rooms, overrides, calculator, workset_id):
    """Create DirectShapes for the given rooms and assign them to the chosen workset."""
    created_ids = []

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

            # ── Comments: "Room Name - Room Number" ──
            number = room.get_Parameter(BuiltInParameter.ROOM_NUMBER).AsValueString() or "?"
            name   = room.get_Parameter(BuiltInParameter.ROOM_NAME).AsValueString()   or "Unnamed"

            comment_param = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
            if comment_param and not comment_param.IsReadOnly:
                comment_param.Set("{} - {}".format(name, number))

            # ── Workset assignment ──
            if workset_id is not None:
                ws_param = ds.get_Parameter(BuiltInParameter.ELEM_PARTITION_PARAM)
                if ws_param and not ws_param.IsReadOnly:
                    ws_param.Set(workset_id.IntegerValue)

            active_view.SetElementOverrides(ds.Id, overrides)
            created_ids.append(ds.Id)

        except Exception as e:
            print("Skipped room [{}]: {}".format(room_label(room), e))
            continue

    t.Commit()
    tgrp.Assimilate()

    return created_ids


# ─────────────────────────────────────────────
# ONE-TIME SETUP
# ─────────────────────────────────────────────

all_patterns  = FilteredElementCollector(doc).OfClass(FillPatternElement).ToElements()
solid_pattern = next((p for p in all_patterns if p.GetFillPattern().IsSolidFill), None)

if solid_pattern is None:
    forms.alert("No solid fill pattern found in the document.", exitscript=True)

calculator = SpatialElementGeometryCalculator(doc)

# ─────────────────────────────────────────────
# MAIN LOOP  –  break instead of script.exit()
#              so the script ends naturally and
#              Revit never rolls back committed
#              transactions
# ─────────────────────────────────────────────

last_rgb = (89, 42, 250)

while True:

    # ── 1. Collect bounded rooms ──────────────
    all_rooms = (FilteredElementCollector(doc)
                 .OfCategory(BuiltInCategory.OST_Rooms)
                 .WhereElementIsNotElementType()
                 .ToElements())

    only_bound_rooms = [
        r for r in all_rooms
        if r.get_Parameter(BuiltInParameter.ROOM_AREA).AsDouble() != 0
    ]

    if not only_bound_rooms:
        forms.alert("No bounded rooms found in the active document.")
        break

    room_map = {room_label(r): r for r in only_bound_rooms}

    # ── 2. Room selection form ────────────────
    selected_labels = forms.SelectFromList.show(
        sorted(room_map.keys()),
        title       = "Select Rooms to Visualize",
        width       = 420,
        button_name = "Choose Color →",
        multiselect = True,
    )

    if not selected_labels:
        break                           # ESC or close → end naturally

    selected_rooms = [room_map[label] for label in selected_labels]

    # ── 3. Color picker ───────────────────────
    chosen_color = pick_color(default_rgb=last_rgb)
    last_rgb     = (chosen_color.Red, chosen_color.Green, chosen_color.Blue)

    overrides = build_overrides(chosen_color, solid_pattern)

    # ── 4. Workset picker ─────────────────────
    chosen_workset = pick_workset()

    if chosen_workset == "CANCELLED":
        break                           # ESC on workset form → end naturally

    chosen_workset_id = chosen_workset.Id if chosen_workset else None

    # ── 5. Create shapes ──────────────────────
    created_ids = create_room_shapes(selected_rooms, overrides, calculator, chosen_workset_id)

    forms.alert(
        "{} room shape(s) created and placed on workset: {}.".format(
            len(created_ids),
            chosen_workset.Name if chosen_workset else "N/A"
        ),
        title = "3D Room Visualization",
    )

    # ── 6. Repeat or exit ─────────────────────
    repeat = forms.alert(
        "Would you like to visualize another set of rooms?",
        title  = "3D Room Visualization",
        ok     = True,
        cancel = True,
    )

    if not repeat:
        break                           # Cancel / ESC → end naturally

# Script ends here naturally — no script.exit() needed
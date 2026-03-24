# -*- coding: utf-8 -*-
# Author: Mohamed Bedair

import os
from Autodesk.Revit.DB import *
from pyrevit import forms, script

PATH_SCRIPT = os.path.dirname(__file__)

app  = __revit__.Application
doc  = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
active_view = doc.ActiveView

# ─────────────────────────────────────────────
# 1.  Collect only bounded rooms
# ─────────────────────────────────────────────
all_rooms = (FilteredElementCollector(doc)
             .OfCategory(BuiltInCategory.OST_Rooms)
             .WhereElementIsNotElementType()
             .ToElements())

only_bound_rooms = [
    room for room in all_rooms
    if room.get_Parameter(BuiltInParameter.ROOM_AREA).AsDouble() != 0
]

if not only_bound_rooms:
    forms.alert("No bounded rooms found in the active document.", exitscript=True)

# ─────────────────────────────────────────────
# 2.  Build a display-name → Room element map
# ─────────────────────────────────────────────
def room_label(room):
    number = room.get_Parameter(BuiltInParameter.ROOM_NUMBER).AsValueString() or "?"
    name   = room.get_Parameter(BuiltInParameter.ROOM_NAME).AsValueString()   or "Unnamed"
    return "{} - {}".format(number, name)

room_map = {room_label(r): r for r in only_bound_rooms}

# ─────────────────────────────────────────────
# 3.  Show selection form  (ESC / Cancel → exit)
# ─────────────────────────────────────────────
selected_labels = forms.SelectFromList.show(
    sorted(room_map.keys()),
    title       = "Select Rooms to Visualize",
    width       = 420,
    button_name = "Visualize Selected Rooms",
    multiselect = True,
)

if not selected_labels:          # user hit ESC or closed without selecting
    script.exit()

selected_rooms = [room_map[label] for label in selected_labels]

# ─────────────────────────────────────────────
# 4.  Build graphic overrides
# ─────────────────────────────────────────────
all_patterns = (FilteredElementCollector(doc)
                .OfClass(FillPatternElement)
                .ToElements())

solid_pattern = next(
    (p for p in all_patterns if p.GetFillPattern().IsSolidFill), None
)

if solid_pattern is None:
    forms.alert("No solid fill pattern found in the document.", exitscript=True)

color = Color(89, 42, 250)

override_settings = OverrideGraphicSettings()
override_settings.SetSurfaceForegroundPatternId(solid_pattern.Id)
override_settings.SetSurfaceForegroundPatternColor(color)
override_settings.SetCutForegroundPatternId(solid_pattern.Id)
override_settings.SetCutForegroundPatternColor(color)
override_settings.SetSurfaceTransparency(25)

# ─────────────────────────────────────────────
# 5.  Create DirectShapes inside a transaction
# ─────────────────────────────────────────────
created_shape_ids = []
calculator = SpatialElementGeometryCalculator(doc)

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

        # Tag the shape with room info for easy identification
        comment_param = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        if comment_param:
            comment_param.Set(room_label(room))

        active_view.SetElementOverrides(ds.Id, override_settings)
        created_shape_ids.append(ds.Id)

    except Exception as e:
        print("Skipped room [{}]: {}".format(room_label(room), e))
        continue

t.Commit()
tgrp.Assimilate()

# ─────────────────────────────────────────────
# 6.  Prompt user to keep or discard
#     ESC / Cancel  →  delete the shapes
# ─────────────────────────────────────────────
keep = forms.alert(
    "{} room shape(s) created.\n\n"
    "• OK     – keep the shapes in the model\n"
    "• Cancel – remove them and exit".format(len(created_shape_ids)),
    title  = "3D Room Visualization",
    ok     = True,
    cancel = True,
)

if not keep:                     # None is returned when the user cancels / ESCs
    t_del = Transaction(doc, "Delete 3D Room Shapes")
    t_del.Start()
    try:
        for shape_id in created_shape_ids:
            doc.Delete(shape_id)
        t_del.Commit()
    except Exception as e:
        t_del.RollBack()
        print("Cleanup failed: {}".format(e))
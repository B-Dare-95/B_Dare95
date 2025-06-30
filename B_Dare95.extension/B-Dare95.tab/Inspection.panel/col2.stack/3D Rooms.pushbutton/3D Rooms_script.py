# -*- coding: utf-8 -*-
import json, os, codecs

from Autodesk.Revit.DB import *

from pyrevit import script
from pyrevit.script import toggle_icon

PATH_SCRIPT = os.path.dirname(__file__)

#Revit Variables
app = __revit__.Application
doc = __revit__.ActiveUIDocument.Document

def read_toggle_config():
    """Function to read toggle_state.json config located in the script's folder.
    If file is not found it will be created with False value."""
    json_toggle_state = os.path.join(PATH_SCRIPT, 'toggle_state.json')

    # READ/CREATE file
    if os.path.exists(json_toggle_state):
        with open(json_toggle_state) as f:
            json_data = json.load(f)
            TOGGLE = json_data['toggle_state']
    else:
        TOGGLE = False
    # REVERSE VALUE
    with open(json_toggle_state, "w") as f:
        x = not TOGGLE
        new_data = {"toggle_state": x}
        json.dump(new_data, f)
    return TOGGLE

all_rooms        = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType().ToElements()

non_bound_rooms  = [room for room in all_rooms if room.get_Parameter(BuiltInParameter.ROOM_AREA).AsDouble() == 0]

only_bound_rooms = [room for room in all_rooms if room not in non_bound_rooms]

TOGGLE = read_toggle_config()

# ACTIVATE/DEACTIVATE ICON
icon_on  = os.path.join(PATH_SCRIPT, 'on.png')
icon_off = os.path.join(PATH_SCRIPT, 'off.png')
toggle_icon(TOGGLE, icon_on, icon_off) #Change icon

room_solids = []

for room in only_bound_rooms:

    calculator = SpatialElementGeometryCalculator(doc)

    results = calculator.CalculateSpatialElementGeometry(room)

    room_solid = results.GetGeometry()

    room_solids.append(room_solid)

#Collecting Solid patterns
all_patterns  = FilteredElementCollector(doc).OfClass(FillPatternElement).ToElements()
solid_pattern = [i for i in all_patterns if i.GetFillPattern().IsSolidFill][0]

color = Color(89,42,250)

override_settings = OverrideGraphicSettings()

override_settings.SetSurfaceForegroundPatternId(solid_pattern.Id)
override_settings.SetSurfaceForegroundPatternColor(color)

override_settings.SetCutForegroundPatternId(solid_pattern.Id)
override_settings.SetCutForegroundPatternColor(color)

override_settings.SetSurfaceTransparency(25)

tgrp = TransactionGroup(doc,"3D Rooms")

tgrp.Start()

t1 = Transaction(doc,"create 3D Rooms")

t1.Start()

shapes = []

for solid in room_solids:
    try:
        direct_shape = DirectShape.CreateElement(doc, ElementId(BuiltInCategory.OST_GenericModel)).SetShape([solid])
    except:
        continue
    created_shapes = FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType().ToElements()
    for shape in created_shapes:
        try:
            shapes.append(shape)
            doc.ActiveView.SetElementOverrides(shape.Id, override_settings)
        except:
            continue

t1.Commit()

tgrp.Assimilate()

if not TOGGLE:
    try:
        t = Transaction(doc, "Delete 3D Rooms")

        t.Start()

        for shape in created_shapes:
            doc.Delete(shape.Id)

        t.Commit()
    except Exception as e:
        t.RollBack()
        script.exit()
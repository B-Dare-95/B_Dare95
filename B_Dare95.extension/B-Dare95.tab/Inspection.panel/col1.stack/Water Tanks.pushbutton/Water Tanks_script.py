# -*- coding: utf-8 -*-
import json, os, codecs

from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import TaskDialog

from pyrevit import script
from pyrevit.script import toggle_icon

PATH_SCRIPT = os.path.dirname(__file__)

#Revit Variables
app = __revit__.Application
doc = __revit__.ActiveUIDocument.Document

all_rooms = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType().ToElements()

water_tanks = [room for room in all_rooms
                    if "WATER" in room.get_Parameter(BuiltInParameter.ROOM_NAME).AsString()
                    and not "FIRE" in room.get_Parameter(BuiltInParameter.ROOM_NAME).AsString()]

if len(water_tanks) == 0:
    TaskDialog.Show("Error", "No Water Tanks Found")
    script.exit()

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

TOGGLE = read_toggle_config()

# ACTIVATE/DEACTIVATE ICON
icon_on  = os.path.join(PATH_SCRIPT, 'on.png')
icon_off = os.path.join(PATH_SCRIPT, 'off.png')
toggle_icon(TOGGLE, icon_on, icon_off) #Change icon

room_solids_tanks = []

room_solids_pumps = []

for room in water_tanks:

    calculator = SpatialElementGeometryCalculator(doc)

    results = calculator.CalculateSpatialElementGeometry(room)

    room_solid = results.GetGeometry()

    room_solids_tanks.append(room_solid)

#Collecting Solid patterns
all_patterns  = FilteredElementCollector(doc).OfClass(FillPatternElement).ToElements()
solid_pattern = [i for i in all_patterns if i.GetFillPattern().IsSolidFill][0]

color_tanks = Color(0,0,255)

#Override Color Settings
override_settings = OverrideGraphicSettings()

override_settings.SetSurfaceForegroundPatternId(solid_pattern.Id)
override_settings.SetSurfaceForegroundPatternColor(color_tanks)

override_settings.SetSurfaceBackgroundPatternId(solid_pattern.Id)
override_settings.SetSurfaceBackgroundPatternColor(color_tanks)

override_settings.SetCutForegroundPatternId(solid_pattern.Id)
override_settings.SetCutForegroundPatternColor(color_tanks)

override_settings.SetSurfaceTransparency(0)


tgrp = TransactionGroup(doc,"3D Fire Water Tanks")

tgrp.Start()

t1 = Transaction(doc,"Create 3D Fire Water Tanks")

t1.Start()

shapes = []

for solid in room_solids_tanks:
    try:
        direct_shape = DirectShape.CreateElement(doc, ElementId(BuiltInCategory.OST_GenericModel)).SetShape([solid])
    except:
        continue

    created_shapes = FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType().ToElements()

    for shape in created_shapes:

        shapes.append(shape)
        doc.ActiveView.SetElementOverrides(shape.Id, override_settings)

t1.Commit()

tgrp.Assimilate()

if not TOGGLE:
    try:
        t = Transaction(doc, "Delete 3D Fire Water Tanks")

        t.Start()

        for shape in created_shapes:
            doc.Delete(shape.Id)

        t.Commit()
    except Exception as e:
        t.RollBack()
        script.exit()
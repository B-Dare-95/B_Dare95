# -*- coding: utf-8 -*-

import clr
from Autodesk.Revit.DB import *
from Autodesk.Revit.DB.Structure import *
import System
from System.Collections.Generic import List
from pyrevit import forms

app = __revit__.Application
doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
active_view = doc.ActiveView

all_doors = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Doors).WhereElementIsNotElementType().ToElements()

phases = doc.Phases

phase = phases[phases.Size - 1]

doors_without_rooms = []

doors_in_same_room = {}

t=Transaction(doc, "Room Data Script")

t.Start()

for door in all_doors:

    try:
        door_toroom = door.ToRoom[phase]

        if door_toroom == None:
            doors_without_rooms.append(door)
            continue

        to_room_level = door_toroom.get_Parameter(BuiltInParameter.LEVEL_NAME).AsValueString()

        to_room_number = door_toroom.LookupParameter("SDC_Room_Number").AsValueString()

        door_room_data_number= door.LookupParameter("SDC_A_DOR_TOROOM_NUMBER")

        door_room_data_number.Set(to_room_number)

        door_room_data_level = door.LookupParameter("SDC_A_DOR_TOROOM_LEVEL")

        door_room_data_level.Set(to_room_level)

        # door_room_designator_param = door.LookupParameter("SDC_A_DOR_TOROOM_DESIGNATOR")
        #
        # door_room_designator_param.Set("1")

        room_data = to_room_level + to_room_number

        doors_in_same_room[door] = room_data

    except:
        continue

value_counts = {}
result_dict = {}

for key, value in doors_in_same_room.items():
    current_count = value_counts.get(value, 0) + 1
    value_counts[value] = current_count
    result_dict[key] = current_count

# Inner loop moved outside — runs only after all doors are counted
for door, designator in result_dict.items():
    try:
        door_room_designator_param = door.LookupParameter("SDC_A_DOR_TOROOM_DESIGNATOR")
        door_room_designator_param.Set(str(designator))  # Cast to string for text parameters
    except:
        pass

t.Commit()
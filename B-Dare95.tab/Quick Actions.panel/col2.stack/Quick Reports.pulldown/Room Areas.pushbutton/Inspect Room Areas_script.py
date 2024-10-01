# -*- coding: utf-8 -*-

#Imports
from Autodesk.Revit.DB import *
from pyrevit import script

#Revit Variables
doc = __revit__.ActiveUIDocument.Document
output = script.get_output()

all_rooms = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType().ToElements()

for room in all_rooms:
    linkify_rooms = output.linkify(room.Id,"Room Name: {} >> Area = {} " .format(room.get_Parameter(BuiltInParameter.ROOM_NAME).AsString(),room.get_Parameter(BuiltInParameter.ROOM_AREA).AsValueString()))
    print(linkify_rooms)
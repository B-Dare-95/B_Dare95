# -*- coding: utf-8 -*-

from Autodesk.Revit.DB import *

doc      = __revit__.ActiveUIDocument.Document
uidoc    = __revit__.ActiveUIDocument
app      = __revit__.Application

all_rooms = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType().ToElements()

t=Transaction(doc,"Room Capitalize")

t.Start()

for room in all_rooms:

    room_name_param = room.LookupParameter("Name")

    room_name = room_name_param.AsString()

    capital_room_name = room_name.upper()

    room_name_param.Set(capital_room_name)

t.Commit()
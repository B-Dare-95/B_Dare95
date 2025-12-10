# -*- coding: utf-8 -*-

import clr
import Autodesk.Revit.DB as DB
from Autodesk.Revit.DB import *
from Autodesk.Revit.DB.Structure import *
import System
from System.Collections.Generic import List
from pyrevit import forms

app = __revit__.Application
doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
active_view = doc.ActiveView


all_rooms = FilteredElementCollector(doc,active_view.Id).OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType().ToElements()

all_room_names = list(set([room.get_Parameter(BuiltInParameter.ROOM_NAME).AsString() for room in all_rooms]))

#Get all Room names

names_chosen = forms.SelectFromList.show(
    all_room_names,
    title="Choose Rooms",
    width=300,
    button_name="Make A Selection",
    multiselect=True
)

selected_rooms = []

for room in all_rooms:
    for name in names_chosen:
        if room.get_Parameter(BuiltInParameter.ROOM_NAME).AsString() == name:
            selected_rooms.append(room)


selected_ids = [room.Id for room in selected_rooms]
uidoc.Selection.SetElementIds(List[ElementId](selected_ids))

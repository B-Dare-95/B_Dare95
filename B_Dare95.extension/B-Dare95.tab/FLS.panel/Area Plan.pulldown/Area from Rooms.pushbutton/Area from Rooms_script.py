# -*- coding: utf-8 -*-

#Imports

from Autodesk.Revit.DB import *
from System.Collections.Generic import List
from pyrevit import forms, revit,script

#Revit Variables
uidoc       = __revit__.ActiveUIDocument
doc         = __revit__.ActiveUIDocument.Document
selection   = uidoc.Selection
app         = __revit__.Application
active_view = doc.ActiveView

# ===================================
def create_areas_from_rooms(doc,views):

    new_areas = []

    for view in views:

        all_rooms_in_view = (FilteredElementCollector(doc,view.Id).OfCategory(BuiltInCategory.OST_Rooms)
                             .WhereElementIsNotElementType().ToElements())

        for room in all_rooms_in_view:

            room_name     = room.get_Parameter(BuiltInParameter.ROOM_NAME).AsString()
            room_number   = room.get_Parameter(BuiltInParameter.ROOM_NUMBER).AsString()

            room_location = room.Location
            if isinstance(room_location,LocationPoint):
                room_pt = room_location.Point

            new_area = doc.Create.NewArea(view,UV(room_pt.X,room_pt.Y))

            new_area_name   = new_area.get_Parameter(BuiltInParameter.ROOM_NAME)
            new_area_number = new_area.get_Parameter(BuiltInParameter.ROOM_NUMBER)

            new_area_name.Set(str(room_name))
            new_area_number.Set(str(room_number))

            new_areas.append(new_area)

    return new_areas

fls_area_views = []

all_views = FilteredElementCollector(doc).OfClass(View).WhereElementIsNotElementType().ToElements()

for view in all_views:
    if view.ViewType == ViewType.AreaPlan:
        if view.AreaScheme.Name == "FLS":
            fls_area_views.append(view)

fls_views_dict = {view.Name : view for view in fls_area_views}

try:
    selected_area_view_names = forms.SelectFromList.show(
        fls_views_dict.keys(),
        title="Choose Area Plans",
        width=300,
        button_name="Make A Selection",
        multiselect=True)
except:
    script.exit()

for name in selected_area_view_names:
    selected_area_views = [fls_views_dict[name]]

t=Transaction(doc,"Create Areas")

t.Start()

new_areas = create_areas_from_rooms(doc,selected_area_views)

t.Commit()
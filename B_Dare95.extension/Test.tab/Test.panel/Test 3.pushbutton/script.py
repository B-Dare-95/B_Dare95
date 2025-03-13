# -*- coding: utf-8 -*-
from symbol import continue_stmt

#IMPORTS
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from Autodesk.Revit.UI.Selection import *
from System.Collections.Generic import List
from pyrevit import forms, revit,script
from pyrevit import EXEC_PARAMS

#VARIABLES
uidoc       = __revit__.ActiveUIDocument
doc         = __revit__.ActiveUIDocument.Document
selection   = uidoc.Selection
app         = __revit__.Application
active_view = doc.ActiveView

#FUNCTIONS

#Filter out Unbounded Rooms
def check_room_area(rooms):
    bounded_rooms = []
    for room in rooms:
        if room.Area == 0:
            continue
        else:
            bounded_rooms.append(room)

    return bounded_rooms

#Associate every room with its boundaries as curves
def get_rooms_bounds(rooms):
    room_dictionary = {}
    for room in rooms:
        curve_bounds = []
        room_bounds = room.GetBoundarySegments(SpatialElementBoundaryOptions())
        for bound_list in room_bounds:
            for bound in bound_list:
                curve_bounds.append(bound.GetCurve())

        room_dictionary.update({room:curve_bounds})
    return room_dictionary


#COLLECTORS
all_views = (FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Views).WhereElementIsNotElementType().ToElements())

all_rooms = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType().ToElements()

all_levels = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Levels).WhereElementIsNotElementType().ToElements()

all_area_schemes = FilteredElementCollector(doc).OfClass(AreaScheme).WhereElementIsNotElementType().ToElements()
#Get an Area Scheme


area_scheme_id = FilteredElementCollector(doc).OfClass(AreaScheme).WhereElementIsNotElementType().FirstElementId()


#Check Rooms for non_bounded rooms

bounded_rooms = check_room_area(all_rooms)

#Associate every room with its boundaries as curves

room_dictionary = get_rooms_bounds(bounded_rooms)

plan_views_names = [view.Name for view in all_views if not view.IsTemplate and view.ViewType == ViewType.FloorPlan]

selected_view_names = forms.SelectFromList.show(plan_views_names, title="Choose Views"
                                                , width=300
                                                , button_name="Done"
                                                , multiselect=True)

if not selected_view_names:
    pass
    script.exit()

plan_views = [view for view in all_views if view.Name in selected_view_names]

#Failsafe if no views are found
if len(plan_views) == 0:
    TaskDialog.Show("Error","Couldn't find Plan Views")
    script.exit()

t=Transaction(doc,"Create Area Views")

t.Start()

#Create a new area scheme from existing one
fls_area_scheme_id = ElementTransformUtils.CopyElement(doc, area_scheme_id, XYZ.Zero)

fls_area_scheme = doc.GetElement(fls_area_scheme_id[0])

#Naming New Area Scheme
if "FLS" in [area_scheme.Name for area_scheme in all_area_schemes]:
    pass
else:
    fls_area_scheme.Name = "FLS"

area_views = []

for view in plan_views:

    view_level = view.GenLevel

    new_area_view = ViewPlan.CreateAreaPlan(doc,fls_area_scheme_id[0],view_level.Id)

    area_views.append(new_area_view)

for plan_view,area_view in zip(plan_views,area_views):

    area_view.Name = plan_view.Name


t.Commit()
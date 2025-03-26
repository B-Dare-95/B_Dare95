# -*- coding: utf-8 -*-

# IMPORTS
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from Autodesk.Revit.UI.Selection import *
from System.Collections.Generic import List
from pyrevit import forms, revit, script

# VARIABLES
uidoc = __revit__.ActiveUIDocument
doc = __revit__.ActiveUIDocument.Document
selection = uidoc.Selection
app = __revit__.Application
active_view = doc.ActiveView

# FUNCTIONS

# Filter out Unbounded Rooms
def check_room_area(rooms):
    return [room for room in rooms if room.Area > 0]

#Check for FLS Area Scheme
def check_fls_area_scheme(area_schemes):
    for scheme in area_schemes:
        if scheme.Name == "FLS":
            return scheme


# Associate every room with its boundaries as curves
def get_rooms_bounds(rooms):
    room_dictionary = {}
    for room in rooms:
        curve_bounds = []
        room_bounds = room.GetBoundarySegments(SpatialElementBoundaryOptions())
        for bound_list in room_bounds:
            for bound in bound_list:
                curve_bounds.append(bound.GetCurve())
        room_dictionary[room] = curve_bounds
    return room_dictionary


# COLLECTORS
all_views        = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Views).WhereElementIsNotElementType().ToElements()

all_rooms        = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType().ToElements()

all_levels       = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Levels).WhereElementIsNotElementType().ToElements()

all_area_schemes = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_AreaSchemes).WhereElementIsNotElementType().ToElements()

# Check if "FLS" area scheme exists
fls_area_scheme = check_fls_area_scheme(all_area_schemes)

tgrp=TransactionGroup(doc,"Create FLS Area Views")

tgrp.Start()

#Create FLS Area Scheme if not found
if not fls_area_scheme:

    t_scheme = Transaction(doc, 'Create FLS Area Scheme')

    t_scheme.Start()

    try:
        fls_area_scheme_id = ElementTransformUtils.CopyElement(doc,all_area_schemes[0].Id,XYZ.Zero)
    except Exception as e:
        print(e)
    fls_area_scheme = doc.GetElement(fls_area_scheme_id[0])
    fls_area_scheme.Name = "FLS"

    t_scheme.Commit()

# Get Plan Views
plan_views_names = [view.Name for view in all_views if not view.IsTemplate and view.ViewType == ViewType.FloorPlan]

selected_view_names = forms.SelectFromList.show(
    plan_views_names, title="Choose Views", width=300, button_name="Done", multiselect=True)

if not selected_view_names:
    script.exit()

plan_views = [view for view in all_views if view.Name in selected_view_names]

# Failsafe if no views are found
if not plan_views:
    TaskDialog.Show("Error", "Couldn't find Plan Views")
    script.exit()

t_area_views = Transaction(doc,"Create Area Views")

t_area_views.Start()
# Create Area Views inside a transaction
area_views = []

for view in plan_views:
    view_level = view.GenLevel
    new_area_view = ViewPlan.CreateAreaPlan(doc, fls_area_scheme.Id, view_level.Id)
    area_views.append(new_area_view)

t_area_views.Commit()

tgrp.Assimilate()
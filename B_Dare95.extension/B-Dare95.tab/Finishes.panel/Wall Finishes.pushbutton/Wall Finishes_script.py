# -*- coding: utf-8 -*-
# Imports
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from Autodesk.Revit.UI.Selection import *

# .NET Imports
import clr

clr.AddReference('System')
from System.Collections.Generic import List

# pyRevit Imports
from pyrevit import forms, revit, script
from pyrevit import EXEC_PARAMS

# Variables
uidoc = __revit__.ActiveUIDocument
doc = __revit__.ActiveUIDocument.Document


# Override ISelectionFilter to Select Rooms
class RoomFilter(ISelectionFilter):
    def AllowElement(self, elem):
        if elem.Category.Name == "Rooms":
            return True


try:
    reference_room = uidoc.Selection.PickObject(ObjectType.Element, RoomFilter(), "Select Room")
except:
    script.exit()

# Get All Wall Types Names

all_wall_types = FilteredElementCollector(doc).OfClass(WallType).ToElements()
wall_type_dictionary = {Element.Name.GetValue(wall_type): wall_type for wall_type in all_wall_types
                        if "FIN" in wall_type.LookupParameter("Type Name").AsString() }

wall_type_names = wall_type_dictionary.keys()

# Prompt the user to select a wall type
selected_type_name = forms.SelectFromList.show(wall_type_names,
                                               title="Choose Wall Type",
                                               width=400,
                                               button_name="Make A Selection",
                                               multiselect=False)

# Error Handling in case user selected nothing or aborted selection
if not selected_type_name:
    script.exit()

selected_wall_type = wall_type_dictionary[selected_type_name]
wall_type_id = selected_wall_type.Id
wall_width = selected_wall_type.Width

# Extract Room Parameters
element_room = doc.GetElement(reference_room)
height = element_room.LookupParameter("Unbounded Height").AsDouble()
# bottom     = element_room .LookupParameter("Base Offset").AsDouble()
room_level = element_room.Level
level_id = room_level.Id
room_bounds_list = element_room.GetBoundarySegments(SpatialElementBoundaryOptions())


t = Transaction(doc, "Create Wall Finishes.panel")

t.Start()

bounding_walls = []
new_walls = []

for bound_list in room_bounds_list:

    for bound in bound_list:

        curve = bound.GetCurve()

        bounding_wall = doc.GetElement(bound.ElementId)
        if not type(bounding_wall) == Wall:
            continue
        bounding_walls.append(bounding_wall)

        bounding_wall_height = bounding_wall.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM).AsDouble()

        new_curve = curve.CreateOffset(-wall_width / 2, XYZ.BasisZ)

        new_wall = Wall.Create(doc, new_curve, wall_type_id, level_id, height, 0, False, False)

        new_wall.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM).Set(bounding_wall_height)

        new_walls.append(new_wall)

for wall1 in new_walls:
    for wall2 in bounding_walls:

        try:
            JoinGeometryUtils.JoinGeometry(doc, wall1, wall2)
        except:
            pass

t.Commit()
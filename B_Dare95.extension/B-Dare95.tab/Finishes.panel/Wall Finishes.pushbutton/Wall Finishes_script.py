# -*- coding: utf-8 -*-

__title__     = "Wall Finish Generator"
__author__    = "Mohamed Bedair"
__version__   = 'Version = 1.0'
__doc__       = """Version = 1.0
Date    = 20.02.2025
_____________________________________________________________________
Description:

Creates Wall Finishes from selected Rooms.
_____________________________________________________________________
How-to:

-> Run the script
-> Select a Room
-> Select The Wall Type for Finish
-> Done!
_____________________________________________________________________
Last update:
- [20.02.2025] - 1.0.0 RELEASE
_____________________________________________________________________
Author: Mohamed Bedair"""

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

#CLASSES
class SupressWarnings(IFailuresPreprocessor):
    def PreprocessFailures(self, failuresAccessor):
        try:
            failures = failuresAccessor.GetFailureMessages()

            for fail in failures: #type: FailureMessageAccessor
                severity    = fail.GetSeverity()
                description = fail.GetDescriptionText()
                fail_id     = fail.GetFailureDefinitionId()

                if severity == FailureSeverity.Warning:

                    if fail_id == BuiltInFailures.JoinElementsFailures.JoiningDisjointWarn:
                        failuresAccessor.DeleteWarning(fail)
                    else:
                        pass
        except:
            import traceback
            print(traceback.format_exc())

        return FailureProcessingResult.Continue

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

room_volume = element_room.get_Parameter(BuiltInParameter.ROOM_VOLUME).AsDouble()

room_area = element_room.get_Parameter(BuiltInParameter.ROOM_AREA).AsDouble()

room_height = room_volume / room_area

offset = UnitUtils.ConvertToInternalUnits(100, UnitTypeId.Millimeters)

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

        if room_volume == 0:
            new_wall.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM).Set(bounding_wall_height)

        else:
            new_wall.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM).Set(room_height+offset)

        new_walls.append(new_wall)

for wall1 in new_walls:
    for wall2 in bounding_walls:

        try:
            JoinGeometryUtils.JoinGeometry(doc, wall1, wall2)
        except:
            pass

#💡 Assign Error Handler

fail_hand_opts = t.GetFailureHandlingOptions()
fail_hand_opts.SetFailuresPreprocessor(SupressWarnings())
t.SetFailureHandlingOptions(fail_hand_opts)

t.Commit()
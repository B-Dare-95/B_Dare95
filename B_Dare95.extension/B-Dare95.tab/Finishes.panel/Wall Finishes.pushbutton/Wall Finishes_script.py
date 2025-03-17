# -*- coding: utf-8 -*-

__title__ = "Wall Finish Generator"
__author__ = "Mohamed Bedair"
__version__ = '1.1.0'
__doc__ = """
Version = 1.1.0
Date    = 20.02.2025

Description:
Creates Wall Finishes from selected Rooms.

How-to:
-> Run the script
-> Select a Room
-> Select The Wall Type for Finish
-> Done!

Last update:
- [20.02.2025] - 1.1.0 RELEASE
  - Improved Code Readability
  - Added Better Error Handling
  - Refactored Key Sections into Functions

Author: Mohamed Bedair
"""

# Imports
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from Autodesk.Revit.UI.Selection import *
import clr

clr.AddReference('System')
from System.Collections.Generic import List
from pyrevit import forms, revit, script
from pyrevit import EXEC_PARAMS

# Variables
uidoc = __revit__.ActiveUIDocument
doc = __revit__.ActiveUIDocument.Document


# Failure Preprocessor to Suppress Warnings
class SuppressWarnings(IFailuresPreprocessor):
    def PreprocessFailures(self, failuresAccessor):
        """Suppresses specific warnings during the transaction."""
        try:
            for failure in failuresAccessor.GetFailureMessages():
                if failure.GetSeverity() == FailureSeverity.Warning:
                    failuresAccessor.DeleteWarning(failure)
        except Exception as e:
            print("Error suppressing warnings:", e)
        return FailureProcessingResult.Continue


# Selection Filter for Rooms
class RoomFilter(ISelectionFilter):
    def AllowElement(self, elem):
        return elem.Category and elem.Category.Name == "Rooms"


def select_room():
    """Prompts user to select a Room and returns the Room element."""
    try:
        room_ref = uidoc.Selection.PickObject(ObjectType.Element, RoomFilter(), "Select Room")
        return doc.GetElement(room_ref)
    except:
        script.exit()


def get_wall_types():
    """Retrieves all wall types that contain 'FIN' in their type name."""
    all_wall_types = FilteredElementCollector(doc).OfClass(WallType).ToElements()
    return {
        wt.LookupParameter("Type Name").AsString(): wt
        for wt in all_wall_types if "FIN" in wt.LookupParameter("Type Name").AsString()
    }


def get_room_parameters(room):
    """Extracts necessary parameters from the selected Room."""
    height = room.LookupParameter("Unbounded Height").AsDouble()
    room_level = room.Level
    level_id = room_level.Id
    room_bounds = room.GetBoundarySegments(SpatialElementBoundaryOptions())
    room_volume = room.get_Parameter(BuiltInParameter.ROOM_VOLUME).AsDouble()
    room_area = room.get_Parameter(BuiltInParameter.ROOM_AREA).AsDouble()
    room_height = room_volume / room_area if room_area else 0
    offset = UnitUtils.ConvertToInternalUnits(100, UnitTypeId.Millimeters)
    return height, level_id, room_bounds, room_height, offset


def create_wall_finishes(room, wall_type, level_id, room_bounds, room_height, offset):
    """Creates wall finishes based on the selected room's boundaries."""
    t = Transaction(doc, "Create Wall Finishes")
    t.Start()

    failure_handling = t.GetFailureHandlingOptions()
    failure_handling.SetFailuresPreprocessor(SuppressWarnings())
    t.SetFailureHandlingOptions(failure_handling)

    new_walls = []
    bounding_walls = []

    for boundary_list in room_bounds:
        for boundary in boundary_list:
            curve = boundary.GetCurve()
            bounding_wall = doc.GetElement(boundary.ElementId)
            if not isinstance(bounding_wall, Wall):
                continue

            bounding_walls.append(bounding_wall)
            bounding_wall_height = bounding_wall.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM).AsDouble()

            new_curve = curve.CreateOffset(-wall_type.Width / 2, XYZ.BasisZ)
            new_wall = Wall.Create(doc, new_curve, wall_type.Id, level_id, room_height + offset, 0, False, False)
            new_wall.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM).Set(
                bounding_wall_height if room_height == 0 else room_height + offset
            )
            new_walls.append(new_wall)

    # Join new walls with existing walls
    for new_wall in new_walls:
        for bounding_wall in bounding_walls:
            try:
                JoinGeometryUtils.JoinGeometry(doc, new_wall, bounding_wall)
            except:
                pass

    t.Commit()


# Main Execution
room = select_room()
wall_types = get_wall_types()

selected_wall_type_name = forms.SelectFromList.show(
    sorted(wall_types.keys()),
    title="Choose Wall Type",
    width=400,
    button_name="Make A Selection",
    multiselect=False
)

if not selected_wall_type_name:
    script.exit()

selected_wall_type = wall_types[selected_wall_type_name]
height, level_id, room_bounds, room_height, offset = get_room_parameters(room)

create_wall_finishes(room, selected_wall_type, level_id, room_bounds, room_height, offset)
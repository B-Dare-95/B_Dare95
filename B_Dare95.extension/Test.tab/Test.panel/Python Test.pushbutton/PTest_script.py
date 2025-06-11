# -*- coding: utf-8 -*-

#Imports
import clr
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from Autodesk.Revit.UI.Selection import *
from System.Collections.Generic import List
from pyrevit import forms, revit,script
from pyrevit import EXEC_PARAMS

#Revit Variables
uidoc       = __revit__.ActiveUIDocument
doc         = __revit__.ActiveUIDocument.Document
selection   = uidoc.Selection
app         = __revit__.Application
active_view = doc.ActiveView
output      = script.get_output()

# ===================================

#FUNCTIONS

def get_location_key(elements):

    el_by_location = {}

    for el in elements:
        # Skip if floor is not valid
        if el is None or not el.IsValidObject:
            continue

        try:
            # Get floor geometry
            geo_elem = el.get_Geometry(Options())

            # Skip if no geometry
            if geo_elem is None:
                continue

            # Calculate a location key for the floor
            location_key = ""
            for geo_obj in geo_elem:
                if isinstance(geo_obj, Solid) and geo_obj.Volume > 0:
                    # Use the bounding box of the solid as a location key
                    bbox = geo_obj.GetBoundingBox()
                    if bbox:
                        location_key = "{0:.3f},{1:.3f},{2:.3f}-{3:.3f},{4:.3f},{5:.3f}".format(
                            bbox.Min.X,
                            bbox.Min.Y,
                            bbox.Min.Z,
                            bbox.Max.X,
                            bbox.Max.Y,
                            bbox.Max.Z)
                        break

            # If location key was found, add to dictionary
            if location_key:
                if not el_by_location.has_key(location_key):
                    el_by_location[location_key] = []
                el_by_location[location_key].append(el)
        except:
            # Skip any element that causes an error
            continue

    return el_by_location

def get_location_key_walls(walls):
    walls_by_location = {}

    for wall in walls:
        # Skip if wall is not valid
        if wall is None or not wall.IsValidObject:
            continue

        try:
            # Get wall geometry
            geo_elem = wall.get_Geometry(Options())

            # Skip if no geometry
            if geo_elem is None:
                continue

            # Calculate a location key for the wall
            location_key = ""
            for geo_obj in geo_elem:
                if isinstance(geo_obj, Solid) and geo_obj.Volume > 0:
                    # Use the bounding box of the solid as a location key
                    bbox = geo_obj.GetBoundingBox()
                    if bbox:
                        # Round values to account for floating point precision
                        location_key = "{0:.3f},{1:.3f},{2:.3f}-{3:.3f},{4:.3f},{5:.3f}".format(
                            bbox.Min.X,
                            bbox.Min.Y,
                            bbox.Min.Z,
                            bbox.Max.X,
                            bbox.Max.Y,
                            bbox.Max.Z)
                        break

            # Try using wall location curve if no location key was found
            if not location_key:
                loc = wall.Location
                if isinstance(loc, LocationCurve):
                    curve = loc.Curve
                    start = curve.GetEndPoint(0)
                    end = curve.GetEndPoint(1)
                    location_key = "{0:.3f},{1:.3f},{2:.3f}-{3:.3f},{4:.3f},{5:.3f}".format(
                        start.X,
                        start.Y,
                        start.Z,
                        end.X,
                        end.Y,
                        end.Z)

            # If location key was found, add to dictionary
            if location_key:
                if not walls_by_location.has_key(location_key):
                    walls_by_location[location_key] = []
                walls_by_location[location_key].append(wall)
        except:
            # Skip any wall that causes an error
            continue
    return walls_by_location

def get_items_to_delete(locations):
    # Collect duplicate floors to delete
    elements_to_delete = []

    for loc in locations:
        items_list = locations[loc]
        if len(items_list) > 1:
            # Sort floors by ID (ascending)
            sorted_items = sorted(items_list, key=lambda f: f.Id.IntegerValue)

            # Keep the first floor (lowest ID), delete the rest
            elements_to_delete.extend(sorted_items[1:])

    # Delete the duplicate floors
    if elements_to_delete:
        # Convert to ElementId list
        element_ids = List[ElementId]([i.Id for i in elements_to_delete])

        return element_ids
#COLLECTORS

# Collect all floors in the document
all_floors   = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Floors).WhereElementIsNotElementType().ToElements()
# Collect all walls in the document
all_walls    = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Walls).WhereElementIsNotElementType().ToElements()
# Collect all ceilings in the document
all_ceilings = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Ceilings).WhereElementIsNotElementType().ToElements()


floors_by_location = get_location_key(all_floors)

ceilings_by_location = get_location_key(all_ceilings)

walls_by_location = get_location_key_walls(all_walls)

# Collect duplicates to delete
floors_to_delete = get_items_to_delete(floors_by_location)

walls_to_delete = get_items_to_delete(walls_by_location)

ceilings_to_delete = get_items_to_delete(ceilings_by_location)

# for location in floors_by_location:
#     floor_list = floors_by_location[location]
#     if len(floor_list) > 1:
#         # Sort floors by ID (ascending)
#         sorted_floors = sorted(floor_list, key=lambda f: f.Id.IntegerValue)
#
#         # Keep the first floor (lowest ID), delete the rest
#         floors_to_delete.extend(sorted_floors[1:])
#
# # Delete the duplicate floors
# if floors_to_delete:
#     # Convert to ElementId list
#     element_ids = List[ElementId]([floor.Id for floor in floors_to_delete])

# Start a transaction to delete elements
t = Transaction(doc, "Delete Duplicates")
t.Start()
try:
    # Delete the elements
    doc.Delete(floors_to_delete)
    doc.Delete(walls_to_delete)
    doc.Delete(ceilings_to_delete)

    t.Commit()
    print("Deleted {0} duplicate floors".format(len(floors_to_delete)))
    print("Deleted {0} duplicate walls" .format(len(walls_to_delete)))
    print("Deleted {0} duplicate ceilings" .format(len(ceilings_to_delete)))

except Exception as e:
    t.RollBack()
    print("Error deleting floors: {0}".format(e))
    print("Error deleting walls: {0}".format(e))
    print("Error deleting ceilings: {0}".format(e))


# Collect duplicate walls to delete


# for location in walls_by_location:
#     wall_list = walls_by_location[location]
#     if len(wall_list) > 1:
#         # Sort walls by ID (ascending)
#         sorted_walls = sorted(wall_list, key=lambda w: w.Id.IntegerValue)
#
#         # Keep the first wall (lowest ID), delete the rest
#         walls_to_delete.extend(sorted_walls[1:])
#
# # Delete the duplicate walls
# if walls_to_delete:
#     # Convert to ElementId list
#     element_ids = List[ElementId]([wall.Id for wall in walls_to_delete])

# # Start a transaction to delete elements
# t_walls= Transaction(doc, "Delete Duplicate Walls")
# t_walls.Start()
# try:
#     # Delete the elements
#     doc.Delete(element_ids)
#     t_walls.Commit()
#     print("Deleted {0} duplicate walls".format(len(element_ids)))
# except Exception as e:
#     t_walls.RollBack()
#     print("Error deleting walls: {0}".format(e))

# Collect duplicate ceilings to delete


# for location in ceilings_by_location:
#     ceiling_list = ceilings_by_location[location]
#     if len(ceiling_list) > 1:
#         # Sort ceilings by ID (ascending)
#         sorted_ceilings = sorted(ceiling_list, key=lambda c: c.Id.IntegerValue)
#
#         # Keep the first ceiling (lowest ID), delete the rest
#         ceilings_to_delete.extend(sorted_ceilings[1:])
#
# # Delete the duplicate ceilings
# if ceilings_to_delete:
#     # Convert to ElementId list
#     element_ids = List[ElementId]([ceiling.Id for ceiling in ceilings_to_delete])

# Start a transaction to delete elements
# t_ceil = Transaction(doc, "Delete Duplicate Ceilings")
# t_ceil.Start()
# try:
#     # Delete the elements
#     doc.Delete(element_ids)
#     t_ceil.Commit()
#     print("Deleted {0} duplicate ceilings".format(len(element_ids)))
# except Exception as e:
#     t_ceil.RollBack()
#     print("Error deleting ceilings: {0}".format(e))

# tgrp = TransactionGroup(doc,"Delete Duplicates")
# tgrp.Start()
#
# tgrp.Assimilate()
# -*- coding: utf-8 -*-

#Imports
import clr
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from Autodesk.Revit.UI.Selection import *
from System.Collections.Generic import List

#Revit Variables
uidoc       = __revit__.ActiveUIDocument
doc         = __revit__.ActiveUIDocument.Document

# ===================================

#FUNCTIONS

def get_location_key(elements):

    el_by_location = {}

    for el in elements:
        # Skip if element is not valid
        if el is None or not el.IsValidObject:
            continue

        try:
            # Get element geometry
            geo_elem = el.get_Geometry(Options())

            # Skip if no geometry
            if geo_elem is None:
                continue

            # Calculate a location key for the element
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

def get_location_point(element):
    loc = element.Location
    if isinstance(loc, LocationPoint):
        pt = loc.Point
        return (round(pt.X, 4), round(pt.Y, 4), round(pt.Z, 4))
    else:
        return None

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
    # Collect duplicate elements to delete
    elements_to_delete = []

    for loc in locations:
        items_list = locations[loc]
        if len(items_list) > 1:
            # Sort elements by ID (ascending)
            sorted_items = sorted(items_list, key=lambda f: f.Id)

            # Keep the first element (lowest ID), delete the rest
            elements_to_delete.extend(sorted_items[1:])

    # Delete the duplicate elements
    if elements_to_delete:
        # Convert to ElementId list
        element_ids = List[ElementId]([i.Id for i in elements_to_delete])

        return element_ids

# COLLECTORS

# Collect all Elements
all_elements = FilteredElementCollector(doc).WhereElementIsNotElementType().ToElements()

# Collect all floors in the document
all_floors   = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Floors).WhereElementIsNotElementType().ToElements()
# Collect all walls in the document
all_walls    = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Walls).WhereElementIsNotElementType().ToElements()
# Collect all ceilings in the document
all_ceilings = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Ceilings).WhereElementIsNotElementType().ToElements()

#Collect Locations
floors_by_location   = get_location_key(all_floors)

ceilings_by_location = get_location_key(all_ceilings)

walls_by_location    = get_location_key_walls(all_walls)

# Collect Duplicates to delete
floors_to_delete = get_items_to_delete(floors_by_location)

walls_to_delete = get_items_to_delete(walls_by_location)

ceilings_to_delete = get_items_to_delete(ceilings_by_location)

# Start a transaction to delete elements

tgrp = TransactionGroup(doc,"Delete Duplicates")

tgrp.Start()

t1 = Transaction(doc, "Delete Duplicate Floors")

t1.Start()

try:
    # Delete the elements
    if not floors_to_delete:
        print("No Dupicate Floors Found")


    else:
        doc.Delete(floors_to_delete)
        print("Deleted {0} duplicate floors".format(len(floors_to_delete)))

    t1.Commit()

except Exception as e:
    t1.RollBack()
    print("Error deleting floors: {0}".format(e))

t2 = Transaction(doc,"Delete Duplicate Walls")

t2.Start()
try:

    if not walls_to_delete:
        print("No Duplicate Walls Found")

    else:
        doc.Delete(walls_to_delete)
        print("Deleted {0} duplicate walls".format(len(walls_to_delete)))

    t2.Commit()

except Exception as e:
    t2.RollBack()
    print("Error deleting walls: {0}".format(e))

t3 =Transaction(doc,"Delete Duplicate Ceilings")

t3.Start()
try:

    if not ceilings_to_delete:
        print("No Duplicate Ceilings Found")

    else:
        doc.Delete(ceilings_to_delete)
        print("Deleted {0} duplicate ceilings".format(len(ceilings_to_delete)))

    t3.Commit()

except Exception as e:
    t3.RollBack()
    print("Error deleting ceilings: {0}".format(e))

tgrp.Assimilate()


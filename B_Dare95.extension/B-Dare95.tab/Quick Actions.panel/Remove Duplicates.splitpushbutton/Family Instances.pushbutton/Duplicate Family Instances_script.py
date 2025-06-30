# -*- coding: utf-8 -*-
__title__  = "Delete Duplicate Family Instances"
__author__ = "Mohamed Bedair"
__doc__ = """

Description:
Deletes all duplicate family instances in the model.

How-to:
-> Run the script
-> a report will be printed with the number of duplicates deleted

Author: Mohamed Bedair"""

#Imports
from Autodesk.Revit.DB import *

from System.Collections.Generic import List
#Revit Variables
uidoc       = __revit__.ActiveUIDocument
doc         = __revit__.ActiveUIDocument.Document
app         = __revit__.Application

# ===================================

def get_location_point(element):
    loc = element.Location
    if isinstance(loc, LocationPoint):
        pt = loc.Point
        return (round(pt.X, 4), round(pt.Y, 4), round(pt.Z, 4))
    else:
        return None

# Get all warning descriptions
failure_messages = doc.GetWarnings()

# Find warnings about identical instances
duplicate_warnings = [warning for warning in failure_messages
                     if "identical instances in the same place" in warning.GetDescriptionText()]

# Get element IDs from these warnings
duplicate_element_ids = []
for warning in duplicate_warnings:
    duplicate_element_ids.extend(warning.GetFailingElements())

# Convert to set for faster lookup
duplicate_element_id_set = set(duplicate_element_ids)

# Get all model elements with warnings
problematic_elements = []
for elem_id in duplicate_element_ids:
    elem = doc.GetElement(elem_id)
    if elem and elem.Category and elem.Category.CategoryType == CategoryType.Model:
        problematic_elements.append(elem)

# Group elements by type + location
element_groups   = {}

for el in problematic_elements:
    el_type = el.GetTypeId()
    loc_point = get_location_point(el)
    if not loc_point:
        continue  # skip elements with no point-based location

    key = (el_type, loc_point)
    if key not in element_groups:
        element_groups[key] = []
    element_groups[key].append(el)

# Delete duplicates (keep lowest ID)
els_to_delete = []

for group in element_groups.values():
    if len(group) > 1:
        if int(app.VersionNumber) > 2021:
            group.sort(key=lambda x: x.Id.Value)
        else:
            group.sort(key=lambda x: x.Id.IntegerValue)
        to_keep = group[0]
        duplicates = group[1:]
        els_to_delete.extend(duplicates)


# Start Transaction and Delete
t = Transaction(doc,__title__)
t.Start()

for el in els_to_delete:

    try:
        doc.Delete(el.Id)
        print("Duplicate Element Deleted")
    except:
        continue

t.Commit()
# -*- coding: utf-8 -*-

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

# Filter elements by category
elements_in_active_view = FilteredElementCollector(doc).WhereElementIsNotElementType().ToElements()

# Group elements by type + location
element_groups   = {}

for el in elements_in_active_view:
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
t = Transaction(doc,"Delete Duplicate Elements")
t.Start()

for el in els_to_delete:

    try:
        doc.Delete(el.Id)
        print("Duplicate Element Deleted")
    except:
        continue

t.Commit()
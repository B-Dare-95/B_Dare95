# -*- coding: utf-8 -*-
__title__  = "Delete Duplicate Instances"
__author__ = "Mohamed Bedair"
__doc__ = """

Description:
Deletes all duplicate family instances in the model.
Only Model Elements with point-based locations are processed.

How-to:
-> Run the script
-> A report will be printed with the number of duplicates deleted

Author: Mohamed Bedair"""

# Imports
from Autodesk.Revit.DB import (
    Transaction, LocationPoint, CategoryType
)

# Revit Variables
uidoc = __revit__.ActiveUIDocument
doc   = __revit__.ActiveUIDocument.Document
app   = __revit__.Application

# ===================================

def is_model_element(element):
    """Returns True only for valid, placed Model Elements."""
    return (
        element is not None
        and element.IsValidObject
        and element.Category is not None
        and element.Category.CategoryType == CategoryType.Model
    )

def get_element_id_value(element):
    """Returns the ElementId as an integer in a version-agnostic way.
    Relies on ElementId.ToString(), which consistently returns the
    numeric value across all Revit versions."""
    return int(str(element.Id))

def get_location_point(element):
    """Returns a rounded (X, Y, Z) tuple for point-based elements, else None."""
    loc = element.Location
    if isinstance(loc, LocationPoint):
        pt = loc.Point
        return (round(pt.X, 4), round(pt.Y, 4), round(pt.Z, 4))
    return None

# ── Step 1: Collect warnings about identical instances ──────────────────────

duplicate_warnings = [
    w for w in doc.GetWarnings()
    if "identical instances in the same place" in w.GetDescriptionText()
]

if not duplicate_warnings:
    print("No duplicate instance warnings found. Nothing to delete.")
    script.exit()

# ── Step 2: Resolve elements from warning IDs ───────────────────────────────

# Use a set to avoid processing the same element twice across multiple warnings
warning_element_ids = set()
for warning in duplicate_warnings:
    for elem_id in warning.GetFailingElements():
        warning_element_ids.add(elem_id)

model_elements = []
for elem_id in warning_element_ids:
    elem = doc.GetElement(elem_id)
    if is_model_element(elem):
        model_elements.append(elem)

# ── Step 3: Group by Type ID + Location ─────────────────────────────────────

element_groups = {}
for elem in model_elements:
    loc_point = get_location_point(elem)
    if loc_point is None:
        continue  # Skip line- or curve-based elements

    key = (elem.GetTypeId(), loc_point)
    element_groups.setdefault(key, []).append(elem)

# ── Step 4: Identify duplicates to delete (keep the lowest ID) ──────────────

ids_to_delete = []
for group in element_groups.values():
    if len(group) < 2:
        continue
    group.sort(key=get_element_id_value)
    ids_to_delete.extend(el.Id for el in group[1:])  # Keep group[0], delete the rest

if not ids_to_delete:
    print("No duplicate Model Elements identified for deletion.")
    script.exit()

# ── Step 5: Delete within a single Transaction ──────────────────────────────

deleted_count = 0
skipped_count = 0

t = Transaction(doc, __title__)
t.Start()

for elem_id in ids_to_delete:
    # Guard: element may have already been removed as part of a prior deletion
    elem = doc.GetElement(elem_id)
    if elem is None or not elem.IsValidObject:
        skipped_count += 1
        continue
    try:
        doc.Delete(elem_id)
        deleted_count += 1
    except Exception as e:
        print("Could not delete element {0}: {1}".format(elem_id, e))
        skipped_count += 1

t.Commit()

# ── Report ───────────────────────────────────────────────────────────────────

print("-" * 40)
print("Duplicate deletion complete.")
print("  Deleted : {0}".format(deleted_count))
print("  Skipped : {0}".format(skipped_count))
print("-" * 40)
# -*- coding: utf-8 -*-

import clr
import Autodesk.Revit.DB as DB
from Autodesk.Revit.DB import *
from Autodesk.Revit.DB.Structure import *
import System
from System.Collections.Generic import List

app = __revit__.Application
doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

# Start a transaction
t = Transaction(doc, "Cut Walls with Structural Columns")
t.Start()


# Get all walls in the active document
wall_collector = FilteredElementCollector(doc)
walls = wall_collector.OfClass(Wall).ToElements()

# Get all structural columns in the active document
column_collector = FilteredElementCollector(doc).OfClass(FamilyInstance).OfCategory(
    BuiltInCategory.OST_StructuralColumns)
columns = column_collector.ToElements()

# Also check linked documents for structural columns
linkInstances = FilteredElementCollector(doc).OfClass(RevitLinkInstance).ToElements()
linked_columns = []

# for linkInstance in linkInstances:
#     # Skip if the link is not loaded
#     if not linkInstance.GetLinkDocument():
#         continue
#
#     linkDoc = linkInstance.GetLinkDocument()
#     transform = linkInstance.GetTotalTransform()
#
#     # Get all columns in the linked document
#     col_collector = FilteredElementCollector(linkDoc).OfClass(FamilyInstance).OfCategory(
#         BuiltInCategory.OST_StructuralColumns)
#     linked_cols = col_collector.ToElements()
#
#     for col in linked_cols:
#         linked_columns.append((col, transform, linkInstance))

# Process each column in the host model
for column in columns:
    # Get column geometry
    options = Options()
    options.DetailLevel = ViewDetailLevel.Fine
    options.ComputeReferences = True
    options.IncludeNonVisibleObjects = True

    geo = column.get_Geometry(options)
    solid = None

    # Find the solid in the column geometry
    for geo_obj in geo:
        if isinstance(geo_obj, Solid) and geo_obj.Volume > 0:
            solid = geo_obj
            break

    if solid is None:
        continue

    # Check each wall for intersection
    for wall in walls:
        # Skip non-architectural walls
        if wall.WallType.Kind != WallKind.Basic:
            continue

        # Check if the wall and column intersect
        wall_bbox = wall.get_BoundingBox(None)
        column_bbox = column.get_BoundingBox(None)

        if wall_bbox is not None and column_bbox is not None:
            if wall_bbox.Intersects(column_bbox):
                try:

                    # Create the cut between wall and column
                    if not InstanceVoidCutUtils.IsVoidInstanceCuttingElement(doc, wall.Id, column.Id):
                        InstanceVoidCutUtils.AddInstanceVoidCut(doc, wall, column)

                except Exception as e:
                    print(e)

t.Commit()
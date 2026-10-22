__doc__ = """__________________________________________________
Description:

Pins every level, grid and Revit link in the project in one click, so they can't be moved by accident.
__________________________________________________
How-to:

-> Click the arrow under Pin Manager
-> Choose "Levels, Grids & Links"
-> All levels, grids and Revit links are pinned straight away
-> Use Undo if you need to reverse it
__________________________________________________
Author: Mohamed Bedair"""

from Autodesk.Revit.DB import *

doc = __revit__.ActiveUIDocument.Document

t=Transaction(doc,"Pin Levels, Grids & Links")

t.Start()

all_grids=FilteredElementCollector(doc).OfClass(Grid).ToElements()
all_levels=FilteredElementCollector(doc).OfClass(Level).ToElements()
all_links=FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_RvtLinks).WhereElementIsNotElementType().ToElements()

for grid in all_grids:
    grid.Pinned = True
for level in all_levels:
    level.Pinned = True
for link in all_links:
    link.Pinned = True

t.Commit()
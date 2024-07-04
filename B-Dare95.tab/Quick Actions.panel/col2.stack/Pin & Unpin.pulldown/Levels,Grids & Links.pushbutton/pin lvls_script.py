from Autodesk.Revit.DB import *

doc = __revit__.ActiveUIDocument.Document

t=Transaction(doc,"Quick Pin")

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
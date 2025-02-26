# -*- coding: utf-8 -*-
__title__   = "Unbound Finish Walls"
__doc__     = """Version = 1.0
________________________________________________________________
Description:
- Press the Button to remove Room Bounding from Finish Walls
________________________________________________________________
Author: Mohamed Bedair"""

from Autodesk.Revit.DB import *

doc =__revit__.ActiveUIDocument.Document

all_walls=FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Walls).WhereElementIsNotElementType().ToElements()

finish_walls=[wall for wall in all_walls if "_FIN_" in wall.Name]

t=Transaction(doc,"Unbound Finishes.panel")

t.Start()

for wall in finish_walls:
    try:
        wall.LookupParameter("Room Bounding").Set(0)
    except:
        pass
t.Commit()

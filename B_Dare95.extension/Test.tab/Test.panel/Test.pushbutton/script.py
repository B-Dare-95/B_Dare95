# -*- coding: utf-8 -*-

#Imports
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from Autodesk.Revit.UI.Selection import *
from System.Collections.Generic import List
from pyrevit import forms, revit,script

#Revit Variables
uidoc       = __revit__.ActiveUIDocument
doc         = __revit__.ActiveUIDocument.Document
selection   = uidoc.Selection
app         = __revit__.Application
active_view = doc.ActiveView
output = script.get_output()

#Linkify Single Walls

all_walls = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Walls).WhereElementIsNotElementType().ToElements()

# for wall in all_walls:
#     linkify_wall = output.linkify(wall.Id,wall.Name)
#     print(linkify_wall)

wall_ids = [wall.Id for wall in all_walls]

linkify_walls = output.linkify(wall_ids, "Walls {}".format(len(wall_ids)))
print(linkify_walls)





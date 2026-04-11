# -*- coding: utf-8 -*-

__title__   = "3D Shaft"
__doc__     = """
________________________________________________________________
Description:
- Creates Generic Models to represent Shafts in 3D Views

How to Use:
- Run the script
- Generic Models will be generated to represent Shafts
________________________________________________________________
Author: Mohamed Bedair"""

#Imports
import clr
clr.AddReference('System')
from System.Collections.Generic import List

from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from Autodesk.Revit.UI.Selection import *
from pyrevit import forms, revit, script
from pyrevit import EXEC_PARAMS

#Revit Variables
uidoc       = __revit__.ActiveUIDocument
doc         = __revit__.ActiveUIDocument.Document
selection   = uidoc.Selection
app         = __revit__.Application
active_view = doc.ActiveView
output      = script.get_output()

all_shafts = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_ShaftOpening).WhereElementIsNotElementType().ToElements()

for shaft in all_shafts:
    print(shaft.BoundaryCurves)
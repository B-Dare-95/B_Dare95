# -*- coding: utf-8 -*-

#Imports
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from Autodesk.Revit.UI.Selection import *
from System.Collections.Generic import List
from pyrevit import forms, revit,script
from pyrevit import EXEC_PARAMS

#Revit Variables
uidoc       = __revit__.ActiveUIDocument
doc         = __revit__.ActiveUIDocument.Document
selection   = uidoc.Selection
app         = __revit__.Application
active_view = doc.ActiveView
output      = script.get_output()

try:
    selected_elements = selection.PickObjects(ObjectType.Element,"Select Lines")
except:
    script.exit()
    
for ref_element in selected_elements:
    element = doc.GetElement(ref_element)
    element_params = element.Parameters
    for param in element_params:
        print(param.Definition.Name + ">>" + str(param.AsValueString()))
        
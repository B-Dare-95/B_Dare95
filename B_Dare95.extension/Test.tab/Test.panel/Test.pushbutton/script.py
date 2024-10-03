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

unknown_id = int(forms.ask_for_string(
    default='ID',
    prompt='Enter ID to search:',
    title="What's This ID?"))

all_elements=FilteredElementCollector(doc).WhereElementIsNotElementType().ToElements()

unknown_element = [element for element in all_elements if element.Id.IntegerValue == unknown_id]

if not unknown_element:
    TaskDialog.Show("What's This ID?","Element not found, Please Try Again")

else: print(unknown_element)










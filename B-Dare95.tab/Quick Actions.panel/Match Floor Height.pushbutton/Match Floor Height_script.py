# -*- coding: utf-8 -*-

#Imports
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from Autodesk.Revit.UI.Selection import *
from System.Collections.Generic import List
from pyrevit import forms, revit

#Revit Variables
uidoc       = __revit__.ActiveUIDocument
doc         = __revit__.ActiveUIDocument.Document
selection   = uidoc.Selection
app         = __revit__.Application
active_view = doc.ActiveView


class CustomISelectionFilter(ISelectionFilter):
    def AllowElement(self, elem):
        if elem.Category.Name == "Floors":
            return True

#Select an Element from The UI
custom_filter = CustomISelectionFilter()

try: floor_reference = selection.PickObject(ObjectType.Element,"Select A Floor")
except: forms.alert("Script is canceled.",exitscript=True,title="Script Canceled.")

floor_element = doc.GetElement(floor_reference.ElementId)

source_floor_height = floor_element.get_Parameter(BuiltInParameter.FLOOR_HEIGHTABOVELEVEL_PARAM).AsDouble()

with forms.WarningBar(title="Pick Floor to match Height:", handle_esc=True):
    while True:

        try: target_floor_reference = selection.PickObject(ObjectType.Element,"Select A Floor")

        except: break

        target_floor_element = doc.GetElement(target_floor_reference.ElementId)

        with Transaction(doc,"Match Floor Height") as t:

                t.Start()

                target_floor_element.get_Parameter(BuiltInParameter.FLOOR_HEIGHTABOVELEVEL_PARAM).Set(source_floor_height)

                t.Commit()
# -*- coding: utf-8 -*-

#Imports
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI.Selection import *
from pyrevit import forms, revit

#Revit Variables
uidoc       = __revit__.ActiveUIDocument
doc         = __revit__.ActiveUIDocument.Document
selection   = uidoc.Selection

class CustomISelectionFilter(ISelectionFilter):
    def AllowElement(self, elem):
        if elem.Category.Name == "Ceilings":
            return True

#Select an Element from The UI
custom_filter = CustomISelectionFilter()

try: ceiling_reference = selection.PickObject(ObjectType.Element,"Select A Ceiling")
except: forms.alert("Script is canceled.",exitscript=True,title="Script Canceled.")

ceiling_element = doc.GetElement(ceiling_reference.ElementId)

source_ceiling_height = ceiling_element.get_Parameter(BuiltInParameter.CEILING_HEIGHTABOVELEVEL_PARAM).AsDouble()

with forms.WarningBar(title="Pick Wall to match base constrains:", handle_esc=True):
    while True:

        try: target_ceiling_reference = selection.PickObject(ObjectType.Element,"Select A Ceiling")

        except: break

        target_ceiling_element = doc.GetElement(target_ceiling_reference.ElementId)

        with Transaction(doc,"Match Ceiling Height") as t:

                t.Start()

                target_ceiling_element.get_Parameter(BuiltInParameter.CEILING_HEIGHTABOVELEVEL_PARAM).Set(source_ceiling_height)

                t.Commit()
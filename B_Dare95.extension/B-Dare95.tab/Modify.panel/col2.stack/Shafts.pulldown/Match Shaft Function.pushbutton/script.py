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
active_view = doc.ActiveView


class CustomISelectionFilter(ISelectionFilter):
    def AllowElement(self, elem):
        if elem.Category.Name == "Shaft Openings":
            return True

#Select an Element from The UI
custom_filter = CustomISelectionFilter()

try: shaft_reference = selection.PickObject(ObjectType.Element,custom_filter,"Select A Source Shaft")
except: forms.alert("Script is canceled.",exitscript=True,title="Script Canceled.")

shaft_element = doc.GetElement(shaft_reference.ElementId)

try:
    source_shaft_function = shaft_element.LookupParameter("Shaft Function").AsValueString()
except:
    forms.alert("The Parameter (Shaft Function) was not found, Command will exit now" ,exitscript=True,title="Parameter not found")

with forms.WarningBar(title="Pick Shaft to match:", handle_esc=True):
    while True:

        try: target_shaft_reference = selection.PickObject(ObjectType.Element,custom_filter,"Select A Shaft")

        except: break

        target_shaft_element = doc.GetElement(target_shaft_reference.ElementId)

        with Transaction(doc,"Match Shafts") as t:

                t.Start()

                target_shaft_element.LookupParameter("Shaft Function").Set(source_shaft_function)

                t.Commit()
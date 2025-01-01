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
output = script.get_output()

element_ids = []
#Select an Element from The UI

ref_selected_element=selection.PickObjects(ObjectType.Element,"Select Element") #type: Reference

if EXEC_PARAMS.config_mode:

    #Get Category ID from Resulting Reference
    for ref_element in ref_selected_element:
        element_id = doc.GetElement(ref_element).Id
        selected_element = doc.GetElement(ref_element)
        element_category = selected_element.Category
        all_same_category_elements = FilteredElementCollector(doc,active_view.Id).OfCategoryId(element_category.Id).WhereElementIsNotElementType().ToElements()
        for element in all_same_category_elements:
            if element.Name == selected_element.Name:
                element_ids.append(element.Id)

    List_el_ids = List[ElementId](element_ids)

    uidoc.Selection.SetElementIds(List_el_ids)
else:
    # Get Category ID from Resulting Reference
    for ref_element in ref_selected_element:
        element_id = doc.GetElement(ref_element).Id
        selected_element = doc.GetElement(ref_element)
        element_category = selected_element.Category
        all_same_category_elements = FilteredElementCollector(doc).OfCategoryId(
            element_category.Id).WhereElementIsNotElementType().ToElements()
        for element in all_same_category_elements:
            if element.Name == selected_element.Name:
                element_ids.append(element.Id)

    List_el_ids = List[ElementId](element_ids)

    uidoc.Selection.SetElementIds(List_el_ids)
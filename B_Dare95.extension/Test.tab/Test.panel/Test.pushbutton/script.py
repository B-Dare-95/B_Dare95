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

# try: element_reference = selection.PickObject(ObjectType.Element,"Select A Floor")
# except: forms.alert("Script is canceled.",exitscript=True,title="Script Canceled.")
#
# floor_element = doc.GetElement(floor_reference.ElementId)
#
# source_floor_height = floor_element.get_Parameter(BuiltInParameter.FLOOR_HEIGHTABOVELEVEL_PARAM).AsDouble()

# with forms.WarningBar(title="Pick Floor to match Height:", handle_esc=True):
#     while True:
#
#         try: element_reference = selection.PickObject(ObjectType.Element,"Select an element")
#
#         except: break
#
#         element = doc.GetElement(element_reference.ElementId)
#         element_category_id = element.Category.Id
#         element_name = element.Name
#
#         with Transaction(doc,"Get all Similar Elements") as t:
#
#                 t.Start()
#
#                 collector = FilteredElementCollector(doc) \
#                     .OfCategoryId(element_category_id) \
#                     .WhereElementIsNotElementType() \
#                     .ToElements()
#
#                 el_ids = [el.Id for el in collector if el.Name == element_name]
#
#                 List_el_ids = List[ElementId](el_ids)
#
#                 uidoc.Selection.SetElementIds(List_el_ids)
#
#                 t.Commit()

























































# element_reference = selection.PickObject(ObjectType.Element,"Select Element")
# selected_element = doc.GetElement(element_reference.ElementId)
#
# element_geometry = (selected_element.get_Geometry(Options()))
#
# print(element_geometry)
# enum = element_geometry.GetEnumerator()
# print (enum)
#
# for e in enum:
#     print(e)











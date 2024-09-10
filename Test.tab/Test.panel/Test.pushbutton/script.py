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





#
# ref_lnk_id=selected_reference.LinkedElementId
#

#
# lnkd_doc=selected_element.GetLinkDocument()
#
# lnkd_selected_element=lnkd_doc.GetElement(ref_lnk_id)
#
#
# print(lnkd_selected_element.get_Geometry)

# t=Transaction(doc,"Unpin & Delete")
#
# t.Start()
#
# for element in selected_elements:
#     if element.Pinned :
#         element.Pinned = False
#         deleted_elements = doc.Delete(element.Id)
#         if not deleted_elements:
#             pass
#
# t.Commit()


# el_ids      = [el.Id for el in selected_hosted_elements]
# List_el_ids = List[ElementId](el_ids)
#
# uidoc.Selection.SetElementIds(List_el_ids)

# selected_hosted_references = selection.PickObjects(ObjectType.Element,"Select Elements")
#
# selected_hosted_elements = [doc.GetElement(ref.ElementId) for ref in selected_hosted_references]
#
# el_ids      = [el.Id for el in selected_hosted_elements]
# List_el_ids = List[ElementId](el_ids)
#
# uidoc.Selection.SetElementIds(List_el_ids)


# all_cats = doc.Settings.Categories
# cat_names = []
#
# for cat in all_cats:
#     cat_names.append(cat.Name)
#
# chosen_cats=forms.SelectFromList.show(cat_names,title="Choose Categories"\
#                                        ,width=300\
#                                        ,button_name="Make A Selection"\
#                                        ,multiselect=True)
#
# def get_cat_by_name(list_of_names):
#     cats = []
#     for name in list_of_names:
#         if name in [cat.Name for cat in all_cats]:
#             cats.append(cat)
#     return cats
#
# for cat in get_cat_by_name(chosen_cats):
#     elements_to_inspect = FilteredElementCollector(doc).OfCategoryId(cat.Id).WhereElementIsNotElementType().ToElements()
#     print(elements_to_inspect)
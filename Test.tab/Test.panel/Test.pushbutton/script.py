# -*- coding: utf-8 -*-


# ╔╦╗╔═╗╦╔╗╔
# ║║║╠═╣║║║║
# ╩ ╩╩ ╩╩╝╚╝

from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from Autodesk.Revit.UI.Selection import *
from System.Collections.Generic import List

#Revit Variables
uidoc     = __revit__.ActiveUIDocument
doc       = __revit__.ActiveUIDocument.Document
selection = uidoc.Selection
app       = __revit__.Application


class CustomISelectionFilter(ISelectionFilter):
    def AllowElement(self, elem):
        if elem.Category.Name == "Walls":
            return True


#Select an Element from The UI
custom_filter = CustomISelectionFilter()
selected_references = selection.PickObjects(ObjectType.Element,custom_filter,"Select Wall")

selected_elements = [doc.GetElement(ref.ElementId) for ref in selected_references]
t=Transaction(doc,"Offseter")

t.Start()

for element in selected_elements:
    base_offset = element.LookupParameter("Base Offset").AsDouble()
    # mm_base_offset =  UnitUtils.ConvertToInternalUnits(base_offset,UnitTypeId.Millimeters)
    # print(base_offset)

    top_offset = element.LookupParameter("Top Offset").AsDouble()
    # mm_top_offset = UnitUtils.ConvertToInternalUnits(top_offset, UnitTypeId.Millimeters)
    # print(top_offset)

    element.LookupParameter("Top Offset").Set(top_offset - UnitUtils.ConvertToInternalUnits(40, UnitTypeId.Millimeters))
    element.LookupParameter("Base Offset").Set(base_offset - UnitUtils.ConvertToInternalUnits(40, UnitTypeId.Millimeters))

t.Commit()

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
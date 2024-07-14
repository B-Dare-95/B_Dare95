# -*- coding: utf-8 -*-

from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from Autodesk.Revit.UI.Selection import *
from pyrevit import forms,script
from System.Collections.Generic import List

#Revit Variables
uidoc     = __revit__.ActiveUIDocument
doc       = __revit__.ActiveUIDocument.Document
selection = uidoc.Selection
app       = __revit__.Application


# 🔴 checking the wall type names
all_wall_type = FilteredElementCollector(doc).OfClass(WallType).WhereElementIsElementType().ToElements()
class CustomISelectionFilter(ISelectionFilter):
    def AllowElement(self, elem):
        if elem.Category.Name == "Walls":
            return True

#Select Wall to Slice
custom_filter = CustomISelectionFilter()
selected_wall_reference = selection.PickObject(ObjectType.Element,custom_filter,"Select Wall to Slice")
selected_wall_element = doc.GetElement(selected_wall_reference.ElementId)

tgrp=TransactionGroup(doc,"Wall Peeler")
tgrp.Start()

t=Transaction(doc,"Wall Splitter")

t.Start()

new_walls = []


wall_level_id=selected_wall_element.LevelId
wall_loc = selected_wall_element.Location
wall_curve = wall_loc.Curve

wall_type = selected_wall_element.WallType
wall_type_name = wall_type.FamilyName
wall_comp = wall_type.GetCompoundStructure()
wall_layers = list(wall_comp.GetLayers())

total_thickness = sum(layer.Width for layer in wall_layers)
counter_thickness = 0

for layer in wall_layers:
    new_layers = []
    wall_mat = doc.GetElement(layer.MaterialId)
    wall_func = layer.Function
    wall_width = layer.Width
    wall_mat_id = layer.MaterialId

    new_layers.append(CompoundStructureLayer(wall_width, wall_func, wall_mat_id))
    new_wall_type = wall_type.Duplicate(str(wall_func) + wall_mat.Name)
    new_wall_type.Name = wall_mat.Name

    compound = CompoundStructure.CreateSimpleCompoundStructure(new_layers)
    new_wall_type.SetCompoundStructure(compound)
    # offset for wall origin
    offset = ((total_thickness - (2 * counter_thickness)) - wall_width) / 2
    if not selected_wall_element.Flipped:
        offset = -offset
    #  Creates a new curve that is an offset of the existing curve.
    offset_curve = wall_curve.CreateOffset(offset, XYZ.BasisZ)
    wall_create = Wall.Create(doc, offset_curve, new_wall_type.Id, wall_level_id, 10, 0, False, False)
    # accumulated thickness
    counter_thickness += wall_width
    new_walls.append(wall_create)




for new_wall in new_walls:

    base_off = selected_wall_element.get_Parameter(BuiltInParameter.WALL_BASE_OFFSET).AsDouble()
    top_cons = selected_wall_element.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE).AsElementId()
    top_off = selected_wall_element.get_Parameter(BuiltInParameter.WALL_TOP_OFFSET).AsDouble()
    unconnected_ht = selected_wall_element.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM).AsDouble()

    base_off_param = new_wall.get_Parameter(BuiltInParameter.WALL_BASE_OFFSET)
    top_cons_param = new_wall.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE)
    top_off_param = new_wall.get_Parameter(BuiltInParameter.WALL_TOP_OFFSET)
    unconnected_ht_param = new_wall.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM)

    if base_off:
        base_off_param.Set(base_off)

    if top_cons == ElementId.InvalidElementId:
        unconnected_ht_param.Set(unconnected_ht)
    else:
        top_cons_param.Set(top_cons)
        top_off_param.Set(top_off)

t.Commit()

t_collect_hosted_elements = Transaction(doc,"Collect Hosted Elements")

t_collect_hosted_elements.Start()

# IMPORTANT MESSAGE

important_message = TaskDialog.Show("Wall Peeler",
                                    "Wall Split Succesful \n Please Select any hosted elements on the wall")

selected_hosted_references = selection.PickObjects(ObjectType.Element, "Select Wall Hosted Elements to Store")

selected_hosted_elements = [doc.GetElement(ref.ElementId) for ref in selected_hosted_references]



# for elem in selected_hosted_elements:
#     all_params = elem.Parameters
#     for param in all_params:




# el_ids = [el.Id for el in selected_hosted_elements]
# List_el_ids = List[ElementId](el_ids)
#
# uidoc.Selection.SetElementIds(List_el_ids)



# cut_to_clipboard_id = RevitCommandId.LookupPostableCommandId(PostableCommand.CutToClipboard)
#
# if cut_to_clipboard_id:
#     posted_command = UIApplication(app).PostCommand(cut_to_clipboard_id)

t_collect_hosted_elements.Commit()

t_delete = Transaction(doc,"Delete Original Wall")

t_delete.Start()
if wall_create:

    doc.Delete(selected_wall_element.Id)
else:
    sys.exit()
t_delete.Commit()
tgrp.Assimilate()

###############################################################

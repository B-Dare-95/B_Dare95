# -*- coding: utf-8 -*-
__author__    = "Mohamed Bedair"
__version__   = 'Version = 1.0'
__doc__ = """__________________________________________________
Description:

Copies every element in a link that has the same category and type name as the one you click into your model. The copies are pinned.
They land exactly where you see them in the link, however the link is placed or rotated.
__________________________________________________
How-to:

-> Click on the button
-> Click one element in the link
-> All matching elements in that link are copied and pinned
__________________________________________________
Author: Mohamed Bedair"""

#IMPORTS

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
from System.Collections.Generic import List
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from Autodesk.Revit.UI.Selection import *
from pyrevit import script,EXEC_PARAMS

#VARIABLES

doc         = __revit__.ActiveUIDocument.Document
uidoc       = __revit__.ActiveUIDocument
selection   = uidoc.Selection
active_view = doc.ActiveView

#Prompt user to Select a Linked Element
try:
    ref_selected_element=selection.PickObject(ObjectType.LinkedElement,"Select Linked Element") #type: Reference
except:
    TaskDialog.Show("B-Dare95","Please, Select a Linked Element")
    script.exit()

#Get Linked Element ID from Resulting Reference
ref_lnk_id=ref_selected_element.LinkedElementId

#Get RevitLinkInstance from Selection using ElementID
selected_element=doc.GetElement(ref_selected_element.ElementId)

# Get the Linked document from the RevitLinkInstance
lnkd_doc=selected_element.GetLinkDocument()

# Get the Linked Selected Element using the Linked Document & LinkedElementId
lnkd_selected_element=lnkd_doc.GetElement(ref_lnk_id)

#Get Category Id & Element Name for Filtering
lnkd_selected_element_ctgr=lnkd_selected_element.Category.Id

lnkd_selected_element_name=lnkd_selected_element.Name

# Create a filtered element collector for FamilyInstances of the same FamilySymbol
collector = FilteredElementCollector(lnkd_doc)\
    .OfCategoryId(lnkd_selected_element_ctgr)\
    .WhereElementIsNotElementType()\
    .ToElements()

# Link-to-host transform, so copies land where the link shows them
# (not at the link's internal origin)
link_transform=selected_element.GetTotalTransform()

t=Transaction(doc,"Bulk Copy from Link")

t.Start()

try:
    el_ids=[el.Id for el in collector if el.Name == lnkd_selected_element_name]
    List_el_ids=List[ElementId](el_ids)

    els_to_copy=ElementTransformUtils.CopyElements(lnkd_doc,List_el_ids,doc,
                                                   link_transform,
                                                   CopyPasteOptions())
    for el_id in els_to_copy:
        copied_el=doc.GetElement(el_id)
        try:
            copied_el.Pinned=True
        except:
            pass

    t.Commit()
except Exception as e:
    t.RollBack()
    TaskDialog.Show("B-Dare95","Copy failed:\n" + str(e))
    script.exit()
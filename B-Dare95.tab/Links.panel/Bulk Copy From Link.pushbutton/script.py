# -*- coding: utf-8 -*-
__title__     = "Bulk Copy from Link"
__author__    = "Mohamed Bedair"
__version__   = 'Version = 1.0'
__doc__       = """Version = 1.0
Date    = 21.12.2023
_____________________________________________________________________
Description:

Copies all elements of the same type from a link. 
the copied elements will be pasted in project and pinned.
_____________________________________________________________________
How-to:

-> Run the script
-> select an element from a link(no tab required)
-> all elements of the same type will be copied
_____________________________________________________________________
Last update:
- [21.12.2023] - 1.0 RELEASE
_____________________________________________________________________
Author: Mohamed Bedair"""

#IMPORTS

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
from System.Collections.Generic import List
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI.Selection import *
from pyrevit import script

#VARIABLES

doc         =__revit__.ActiveUIDocument.Document
uidoc       =__revit__.ActiveUIDocument
selection   =uidoc.Selection

#Prompt user to Select a Linked Element

ref_selected_element=selection.PickObject(ObjectType.LinkedElement,"Select Linked Element") #type: Reference

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

t=Transaction(doc,"Bulk Copy from Link")

t.Start()

el_ids=[el.Id for el in collector if el.Name == lnkd_selected_element_name]
List_el_ids=List[ElementId](el_ids)

els_to_copy=ElementTransformUtils.CopyElements(lnkd_doc,List_el_ids,doc,
                                               Transform.CreateTranslation(XYZ(0,0,0)),
                                               CopyPasteOptions())
for el_id in els_to_copy:
    copied_el=doc.GetElement(el_id)
    copied_el.Pinned=True

t.Commit()
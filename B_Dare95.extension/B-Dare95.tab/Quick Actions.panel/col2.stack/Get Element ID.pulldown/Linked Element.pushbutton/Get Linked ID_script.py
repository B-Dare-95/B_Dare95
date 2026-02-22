# -*- coding: utf-8 -*-
__title__     = "Linked Element"
__author__    = "Mohamed Bedair"
__version__   = 'Version = 1.0'
__doc__       = """Version = 1.0
Date    = 21.12.2023
_____________________________________________________________________
Description:

Gets Linked Element ID.
_____________________________________________________________________
How-to:

-> Run the script
-> select an element from a link(no tab required)
-> copy and paste the resulting IDs
_____________________________________________________________________
Last update:
- [21.12.2023] - 1.0 RELEASE
_____________________________________________________________________
Author: Mohamed Bedair"""

#IMPORTS

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
from Autodesk.Revit.UI.Selection import ObjectType
from pyrevit import script

#VARIABLES

doc         =  __revit__.ActiveUIDocument.Document
uidoc       =  __revit__.ActiveUIDocument
selection   =  uidoc.Selection

#Prompt user to Select a Linked Element
try:
    ref_selected_elements=selection.PickObjects(ObjectType.LinkedElement,"Select Linked Element") #type: Reference

except:
    script.exit()

for lnk_elem in ref_selected_elements:
    ref_lnk_id=lnk_elem.LinkedElementId

    selected_element = doc.GetElement(lnk_elem.ElementId)

    linked_doc = selected_element.GetLinkDocument()

    lnkd_selected_element = linked_doc.GetElement(ref_lnk_id)

    print("Element Name : " + lnkd_selected_element.Name + " >> ID: " + str(ref_lnk_id.IntegerValue))
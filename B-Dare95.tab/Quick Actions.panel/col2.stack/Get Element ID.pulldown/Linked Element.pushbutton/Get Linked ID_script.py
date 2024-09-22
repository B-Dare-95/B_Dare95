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
from System.Collections.Generic import List
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI.Selection import *

#VARIABLES

doc         =  __revit__.ActiveUIDocument.Document
uidoc       =  __revit__.ActiveUIDocument
selection   =  uidoc.Selection

#Prompt user to Select a Linked Element
ref_selected_element=selection.PickObjects(ObjectType.LinkedElement,"Select Linked Element") #type: Reference

#Get Linked Element ID from Resulting Reference
for lnk_elem in ref_selected_element:
    lnk_id=lnk_elem.LinkedElementId
    print("Element ID: "+ str(lnk_id.IntegerValue))
__title__     = "Get Linked Element ID"
__author__    = "Mohamed Bedair"
__version__   = 'Version = 1.0'
__doc__       = """Version = 1.0
Date    = 21.12.2023
_____________________________________________________________________
Description:

Gets Element ID.
_____________________________________________________________________
How-to:

-> Run the script
-> select an element
-> copy and paste the resulting IDs
_____________________________________________________________________
Last update:
- [19.9.2024] - 1.0 RELEASE
_____________________________________________________________________
Author: Mohamed Bedair"""

#IMPORTS

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI.Selection import *

#VARIABLES

doc         =  __revit__.ActiveUIDocument.Document
uidoc       =  __revit__.ActiveUIDocument
selection   =  uidoc.Selection

#Prompt user to Select a Linked Element
ref_selected_element=selection.PickObjects(ObjectType.Element,"Select Linked Element") #type: Reference

#Get Linked Element ID from Resulting Reference
for element in ref_selected_element:
    element_id = element.Id
    print("Element ID: " + str(element_id.IntegerValue))
__author__    = "Mohamed Bedair"
__version__   = 'Version = 1.0'
__doc__ = """__________________________________________________
Description:

Shows the name and ID of the elements you pick in your model, ready to copy from the output window.
__________________________________________________
How-to:

-> Click on the button
-> Pick one or more elements
-> Click "Finish" (or press Enter)
-> Copy the names and IDs from the output window
__________________________________________________
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
    ref_selected_element=selection.PickObjects(ObjectType.Element,"Select Element") #type: Reference
except:
    script.exit()
#Get Linked Element ID from Resulting Reference
for ref_element in ref_selected_element:
    element_id = doc.GetElement(ref_element).Id
    element_name = doc.GetElement(ref_element).Name
    print("Element Name : " + element_name + ">>ID: " + str(element_id.IntegerValue))
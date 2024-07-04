# -*- coding: utf-8 -*-
__title__     = "Family Cleaner"
__author__    = "Mohamed Bedair"
__version__   = 'Version = 1.0'
__doc__       = """Version = 1.0
Date    = 29.02.2024
_____________________________________________________________________
Description:

Purges a Family from any unwanted parameters in a click.
_____________________________________________________________________
How-to:

-> Run the script
-> select paramter group to delete parameters from
-> a message will appear with deleted paramters
_____________________________________________________________________
Last update:
- [29.02.2024] - 1.0 RELEASE
_____________________________________________________________________
Author: Mohamed Bedair"""

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from pyrevit import forms,script
from Autodesk.Revit.DB import *

# Variables
doc = __revit__.ActiveUIDocument.Document
param_groups=[BuiltInParameterGroup.PG_IDENTITY_DATA,
              BuiltInParameterGroup.PG_IFC,
              BuiltInParameterGroup.PG_GENERAL]

# Check if the document is a family document
if doc.IsFamilyDocument:

    chosen_groups = forms.SelectFromList.show(param_groups,
                                            title="Choose Parameter Groups to Delete from",
                                            width=500,
                                            button_name="Make A Selection",
                                            multiselect=True)
    if not chosen_groups:
        pass
        script.exit()
    #Get Parameters to Delete
    parameters_to_delete=[]
    parameters_in_family=doc.FamilyManager.Parameters
    for param in parameters_in_family:
        if (param.Definition.ParameterGroup in chosen_groups):
            if param.Definition.BuiltInParameter == BuiltInParameter.INVALID:
                parameters_to_delete.append(param)

    t=Transaction(doc,"Family Parameter Cleaner")
    t.Start()

    for param in parameters_to_delete:
        print("Parameter:" + param.Definition.Name + " >>> Deleted")
        doc.FamilyManager.RemoveParameter(param)
    t.Commit()

else:
    print("Please Run this Tool in a Family Document")
    pass
    script.exit()
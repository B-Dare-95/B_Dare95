# -*- coding: utf-8 -*-
__title__   = "Ghost Model"
__doc__     = """
________________________________________________________________
Description:
- Run the script
- Entire Model will be Transparent except for Lines
- Press again to toggle Ghost Mode off
________________________________________________________________
Author: Mohamed Bedair"""

#Imports
import json, os, codecs
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from Autodesk.Revit.UI.Selection import *
from System.Collections.Generic import List
from pyrevit import forms, revit,script
from pyrevit import EXEC_PARAMS
from pyrevit.script import toggle_icon
from pyrevit.coreutils.ribbon import ICON_MEDIUM

#Revit Variables
uidoc       = __revit__.ActiveUIDocument
doc         = __revit__.ActiveUIDocument.Document
selection   = uidoc.Selection
app         = __revit__.Application
active_view = doc.ActiveView
output      = script.get_output()

#Check for View Template
if not active_view.ViewTemplateId.IntegerValue == -1:
    TaskDialog.Show('Error', 'This View has a View Template. Please Turn off')
    script.exit()

PATH_SCRIPT = os.path.dirname(__file__)

def read_toggle_config():
    """Function to read toggle_state.json config located in the script's folder.
    If file is not found it will be created with False value."""
    json_toggle_state = os.path.join(PATH_SCRIPT, 'toggle_state.json')

    # READ/CREATE file
    if os.path.exists(json_toggle_state):
        with open(json_toggle_state) as f:
            json_data = json.load(f)
            TOGGLE = json_data['toggle_state']
    else:
        TOGGLE = False
    # REVERSE VALUE
    with open(json_toggle_state, "w") as f:
        x = not TOGGLE
        new_data = {"toggle_state": x}
        json.dump(new_data, f)
    return TOGGLE

TOGGLE = read_toggle_config()

# ACTIVATE/DEACTIVATE ICON
icon_on  = os.path.join(PATH_SCRIPT, 'on.png')
icon_off = os.path.join(PATH_SCRIPT, 'off.png')
toggle_icon(TOGGLE, icon_on, icon_off) #Change icon

all_categories = doc.Settings.Categories
line_category = Category.GetCategory(doc,BuiltInCategory.OST_Lines)

override_settings = OverrideGraphicSettings()
override_settings.SetSurfaceTransparency(95)

t=Transaction(doc,"Ghost Model")
t.Start()

doc.ActiveView.DisplayStyle = DisplayStyle.Shading

try:
    doc.ActiveView.SetCategoryHidden(line_category.Id, True)
except:
    pass

for category in all_categories:
    try:
        doc.ActiveView.SetCategoryOverrides(category.Id, override_settings)

    except:
        continue
t.Commit()

reset_override = OverrideGraphicSettings()

if not TOGGLE:
    t = Transaction(doc, "Reset Ghost Model")

    t.Start()

    doc.ActiveView.DisplayStyle = DisplayStyle.ShadingWithEdges

    for category in all_categories:
        try:

            doc.ActiveView.SetCategoryOverrides(category.Id, reset_override)
        except:
            pass
    t.Commit()
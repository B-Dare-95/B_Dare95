# -*- coding: utf-8 -*-
__title__   = "Highlight MEP"
__doc__     = """Version = 1.0
________________________________________________________________
Description:
- Press the Button to Highlight all MEP Elements
- Press+Shift to Reset The Highlight
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


category_names_to_hide = [
    'Walls',
    'Columns',
    'Floors',
    'Ceilings',
    'Doors',
    'Furniture',
    'Parking',
    'Parts',
    'Casework',
    'Curtain',
    'Planting',
    'Railing',
    'Ramps',
    'Roads',
    'Roofs',
    'Site',
    'Stairs',
    'Structural',
    'Specialty Equipment',
    'Topography',
    'Windows',
    'Parts',
    'Generic Models',
    'Entourage'
    ]

all_categories = doc.Settings.Categories
line_category = Category.GetCategory(doc,BuiltInCategory.OST_Lines)

categories_to_hide = [category for category in all_categories
                      if any(keyword.lower() in category.Name.lower() for keyword in category_names_to_hide)]

override_settings = OverrideGraphicSettings()
override_settings.SetSurfaceTransparency(95)

t=Transaction(doc,"MEP Highlight")
t.Start()

doc.ActiveView.DisplayStyle = DisplayStyle.Shading

doc.ActiveView.SetCategoryHidden(line_category.Id, True)

for category in categories_to_hide:
    try:
        doc.ActiveView.SetCategoryOverrides(category.Id, override_settings)

    except:
        continue
t.Commit()

reset_override = OverrideGraphicSettings()

if not TOGGLE:
    t = Transaction(doc, "Reset MEP Highlight")

    t.Start()

    doc.ActiveView.DisplayStyle = DisplayStyle.ShadingWithEdges

    for category in all_categories:
        try:

            doc.ActiveView.SetCategoryOverrides(category.Id, reset_override)
        except:
            pass
    t.Commit()
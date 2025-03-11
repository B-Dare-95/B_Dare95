# -*- coding: utf-8 -*-
__title__   = "Unbound Finishes"
__doc__     = """Version = 1.0
________________________________________________________________
Description:
- Press the Button to remove Room Bounding from Finish Walls
________________________________________________________________
Author: Mohamed Bedair"""

import json, os, codecs

from pyrevit import forms, revit,script
from pyrevit.script import toggle_icon

from Autodesk.Revit.DB import *



doc =__revit__.ActiveUIDocument.Document

all_walls=FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Walls).WhereElementIsNotElementType().ToElements()

finish_walls=[wall for wall in all_walls if "_FIN_" in wall.Name]

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

t=Transaction(doc,"Unbound Finishes")

t.Start()

for wall in finish_walls:
    try:
        wall.LookupParameter("Room Bounding").Set(0)
    except:
        pass
t.Commit()

if not TOGGLE:
    t = Transaction(doc, "Bound Finishes")

    t.Start()

    for wall in finish_walls:
        try:
            wall.LookupParameter("Room Bounding").Set(1)
        except:
            pass
    t.Commit()



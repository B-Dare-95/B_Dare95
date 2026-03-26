# -*- coding: utf-8 -*-



# ╦╔╦╗╔═╗╔═╗╦═╗╔╦╗╔═╗
# ║║║║╠═╝║ ║╠╦╝ ║ ╚═╗
# ╩╩ ╩╩  ╚═╝╩╚═ ╩ ╚═╝ IMPORTS
#==================================================

import clr
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI.Selection import *
from Autodesk.Revit.UI import TaskDialog
from System.Collections.Generic import List

# ╦  ╦╔═╗╦═╗╦╔═╗╔╗ ╦  ╔═╗╔═╗
# ╚╗╔╝╠═╣╠╦╝║╠═╣╠╩╗║  ║╣ ╚═╗
#  ╚╝ ╩ ╩╩╚═╩╩ ╩╚═╝╩═╝╚═╝╚═╝ VARIABLES
#==================================================
uidoc     = __revit__.ActiveUIDocument
doc       = __revit__.ActiveUIDocument.Document #type: Document
app       = __revit__.Application
active_view = doc.ActiveView

from pyrevit import forms,script


swatch = forms.select_swatch(
    title='test title',
    button_name='Test button name'
)

print(type(swatch))
#
# # Selection Filter for Curtain Walls
# class CurtainWallSelectionFilter(ISelectionFilter):
#     def AllowElement(self, element):
#         # Check if element is a Wall
#         if isinstance(element, Wall):
#             # Get the wall type
#             wall_type = element.WallType
#             # Check if it's a curtain wall (Kind property)
#             if wall_type.Kind == WallKind.Curtain:
#                 return True
#         return False
#
#     def AllowReference(self, reference, point):
#         return False
#
# glaze_elems = []
#
# try:
#     glaze_refs = uidoc.Selection.PickObjects(ObjectType.Element, CurtainWallSelectionFilter(), "Select Glazing")
#
#     for ref in glaze_refs:
#         glaze_elem = doc.GetElement(ref)
#         glaze_elems.append(glaze_elem)
#
# except:
#     script.exit()
#
# t=Transaction(doc,"Test 2.pushbutton")
#
# t.Start()
#
# for glaze_elem in glaze_elems:
#     glaze_loc_curve = glaze_elem.Location.Curve
#     glaze_mid = glaze_loc_curve.Evaluate(0.5,True)
#
#     TextNote.Create(doc,active_view.Id,glaze_mid,"MidPoint",ElementId(445954))
#
# t.Commit()
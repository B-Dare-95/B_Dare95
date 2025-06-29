# -*- coding: utf-8 -*-

__title__ = "Unpin All in View"
__author__ = "Mohamed Bedair"
__version__ = '1.0.0'
__doc__ = """
Version = 1.0.0

Description:
Unpins all elements in the active view.

How-to:
-> Run the script

Author: Mohamed Bedair
"""

from Autodesk.Revit.DB import *

doc = __revit__.ActiveUIDocument.Document


all_elements=FilteredElementCollector(doc,doc.ActiveView.Id).WhereElementIsNotElementType().ToElements()

t=Transaction(doc,__title__)

t.Start()

for element in all_elements:
    try:
        element.Pinned = False
    except:
        continue

t.Commit()
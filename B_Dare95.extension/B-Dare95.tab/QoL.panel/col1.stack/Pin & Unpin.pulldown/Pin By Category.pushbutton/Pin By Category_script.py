# -*- coding: utf-8 -*-

__title__ = "Pin By Category"
__author__ = "Mohamed Bedair"
__version__ = '1.0.0'
__doc__ = """
Version = 1.0.0

Description:
Pins all elements in the selected category(s).

How-to:
-> Run the script
-> Select category(s) from the menu
-> The selected category(s) will be pinned

Author: Mohamed Bedair
"""

from Autodesk.Revit.DB import *
from pyrevit import forms,script

doc = __revit__.ActiveUIDocument.Document

t=Transaction(doc,__title__)

t.Start()
def get_all_cats(doc):
    cats = doc.Settings.Categories
    return [cat.Name for cat in cats]

all_cats=sorted(get_all_cats(doc))

cats_chosen = forms.SelectFromList.show(all_cats, title="Choose Category" \
                                                , width=300 \
                                                , button_name="Done" \
                                                , multiselect=True)

if not cats_chosen:
    pass
    script.exit()

for chosen_cat in cats_chosen:
    for cat in doc.Settings.Categories:
        if cat.Name == chosen_cat:
            elements_to_pin=FilteredElementCollector(doc).OfCategory(cat.BuiltInCategory).WhereElementIsNotElementType().ToElements()

            for elem in elements_to_pin:
                try:
                    elem.Pinned = True
                except:
                    continue
t.Commit()
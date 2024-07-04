# -*- coding: utf-8 -*-
__title__     = "Pre-Filter Selection"
__author__    = "Mohamed Bedair"
__version__   = 'Version = 1.0'
__doc__       = """Version = 1.0
Date    = 24.11.2023
_____________________________________________________________________
Description:

Filters the Selection box to only selected categories. 
_____________________________________________________________________
How-to:

-> Run the script
-> select desired categories from the menu
-> the selection box will only highlight selected categories
_____________________________________________________________________
Last update:
- [24.11.2023] - 1.0 RELEASE
_____________________________________________________________________
Author: Mohamed Bedair"""

#IMPORTS

import System
from System.Collections.Generic import List
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI.Selection import *
from pyrevit import forms,script

#Variables
doc         =__revit__.ActiveUIDocument.Document
uidoc       =__revit__.ActiveUIDocument
selection   =uidoc.Selection

#Create Custom Selection Filter Class
class CustomISelectionFilter(ISelectionFilter):
    def __init__(self,nom_cat):
        self.nom_cat=nom_cat
    def AllowElement(self,elem):
        if elem.Category.Name in self.nom_cat:
            return True
        else:
            return False
# 👆 This part compares the given category name to its actual Category name in Revit DB

#List of Category Names

def get_all_cats(doc):
    cats = doc.Settings.Categories
    return [cat.Name for cat in cats]

all_cats=get_all_cats(doc)

names_choose=sorted(all_cats)

names_chosen=forms.SelectFromList.show(names_choose,title="Choose Categories"\
                                       ,width=300\
                                       ,button_name="Make A Selection"\
                                       ,multiselect=True)
if not names_chosen:
    script.exit()
else:
    sel_elems=[]
    try:
        sel_filter=CustomISelectionFilter(names_chosen)
        selected_elements =selection.PickElementsByRectangle(sel_filter,"Select Elements")
    except:
        sel_elems=[]

el_ids      = [el.Id for el in selected_elements]
List_el_ids = List[ElementId](el_ids)

uidoc.Selection.SetElementIds(List_el_ids)
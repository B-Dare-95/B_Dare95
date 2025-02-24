# -*- coding: utf-8 -*-
__title__     = "Link Workset Inspector"
__author__    = "Mohamed Bedair"
__version__   = 'Version = 1.0'
__doc__       = """Version = 1.0
Date    = 20.02.2025
_____________________________________________________________________
Description:

Copies all elements of the same type from a link. 
the copied elements will be pasted in project and pinned.
_____________________________________________________________________
How-to:

-> Run the script
-> select a document from the list
-> choose a category to inspect its elements
_____________________________________________________________________
Author: Mohamed Bedair"""

#IMPORTS

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
from System.Collections.Generic import List
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI.Selection import *
from pyrevit import forms,script

#VARIABLES

doc         =__revit__.ActiveUIDocument.Document
uidoc       =__revit__.ActiveUIDocument
selection   =uidoc.Selection


actions_to_do=["Copy Elements from Link","Get Element IDs","Get Parameters","Check Grids & Levels Worksets"]
def get_all_cats(doc):
    cats = doc.Settings.Categories
    return [cat.Name for cat in cats]

def get_doc_by_name(_links,_name):
    for lnk in _links:
        if lnk.GetLinkDocument().Title == _name:
            return lnk

#Get All Link Documents

all_links=[lnk for lnk in FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_RvtLinks).WhereElementIsNotElementType().ToElements()]
if not all_links:
    print("No Links Found in this Project")
    pass
    script.exit()
link_names=[lnk.GetLinkDocument().Title for lnk in all_links]

#Get Linked Documents Names
selected_lnk_name=forms.ask_for_one_item(link_names,
                                    default=link_names[0],
                                    prompt="Select Link",
                                    title="Link Selection")
if not selected_lnk_name:
    pass
    script.exit()
#Filter out Selected Link Document
selected_lnk=get_doc_by_name(all_links,selected_lnk_name)

all_cats = sorted(get_all_cats(doc))
chosen_cats = forms.SelectFromList.show(all_cats, title="Choose Categories",
                                        width=300,
                                        button_name="Make A Selection",
                                        multiselect=True)
if not chosen_cats:
    pass
    script.exit()


# Override ISelectionFilter Functions
class LinkedElemSelectionFilter(ISelectionFilter):

    def AllowElement(self, element):
        return True

    def AllowReference(self, reference, position):
        linked_doc = selected_lnk.GetLinkDocument()
        linked_elem = linked_doc.GetElement(reference.LinkedElementId)
        if linked_elem.Category.Name in chosen_cats:
            return True

elements_to_inspect = []
refs_to_inspect=selection.PickObjects(ObjectType.LinkedElement,LinkedElemSelectionFilter())
for ref in refs_to_inspect:
    linked_doc = selected_lnk.GetLinkDocument()
    linked_elem = linked_doc.GetElement(ref.LinkedElementId)
    elements_to_inspect.append(linked_elem)

for elem in elements_to_inspect:
    print(elem.Name + ">> Workset : " + elem.LookupParameter("Workset").AsValueString())
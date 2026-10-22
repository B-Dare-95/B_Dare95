# -*- coding: utf-8 -*-
__title__     = "Linked Element"
__author__    = "Mohamed Bedair"
__version__   = 'Version = 1.2'
__doc__ = """__________________________________________________
Description:

Shows the names and IDs of elements you pick inside linked models, grouped by link.
Each link ends with a comma-separated ID list, ready to paste into Select by ID in that linked model.
__________________________________________________
How-to:

-> Make sure the links are loaded
-> Click on the button
-> Pick elements in one or more links (no Tab needed)
-> Click "Finish" (or press Enter)
-> Copy the IDs per link from the output window
__________________________________________________
Author: Mohamed Bedair"""

#IMPORTS

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
from Autodesk.Revit import DB
from Autodesk.Revit.UI.Selection import ObjectType
from pyrevit import script

#VARIABLES

doc         =  __revit__.ActiveUIDocument.Document
uidoc       =  __revit__.ActiveUIDocument
selection   =  uidoc.Selection

#HELPERS

def get_id_value(element_id):
    """ElementId.Value (Revit 2025+) with IntegerValue fallback (2024 and earlier)."""
    try:
        return element_id.Value
    except AttributeError:
        return element_id.IntegerValue


def get_element_name(element):
    """Avoids the IronPython Element.Name property/method ambiguity."""
    try:
        return DB.Element.Name.__get__(element)
    except Exception:
        return "<unnamed>"


#Prompt user to Select a Linked Element
try:
    ref_selected_elements=selection.PickObjects(ObjectType.LinkedElement,"Select Linked Element") #type: Reference

except:
    script.exit()

link_cache   = {}   # RevitLinkInstance id value -> linked Document
link_order   = []   # link titles in the order they were first picked
link_groups  = {}   # link title -> {"lines": [...], "ids": [...]}

for lnk_elem in ref_selected_elements:
    ref_lnk_id = lnk_elem.LinkedElementId

    link_key = get_id_value(lnk_elem.ElementId)
    if link_key not in link_cache:
        selected_element      = doc.GetElement(lnk_elem.ElementId)
        link_cache[link_key]  = selected_element.GetLinkDocument()
    linked_doc = link_cache[link_key]

    if linked_doc is None:
        continue

    lnkd_selected_element = linked_doc.GetElement(ref_lnk_id)
    if lnkd_selected_element is None:
        continue

    link_title = linked_doc.Title
    if link_title not in link_groups:
        link_groups[link_title] = {"lines": [], "ids": []}
        link_order.append(link_title)

    id_value = get_id_value(ref_lnk_id)
    group    = link_groups[link_title]
    group["ids"].append(str(id_value))
    group["lines"].append("-Element Name : {} >> ID: {}".format(
        get_element_name(lnkd_selected_element),
        id_value))

#OUTPUT

for i, link_title in enumerate(link_order):
    group = link_groups[link_title]

    if i > 0:
        print("")

    print("Link : {}:".format(link_title))
    for line in group["lines"]:
        print(line)
    print("_" * 60)
    print(",".join(group["ids"]))
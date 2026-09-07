# -*- coding: utf-8 -*-
__title__     = "Linked Element"
__author__    = "Mohamed Bedair"
__version__   = 'Version = 1.1'
__doc__       = """Version = 1.1
Date    = 21.12.2023
_____________________________________________________________________
Description:

Gets Linked Element ID.
_____________________________________________________________________
How-to:

-> Run the script
-> select an element from a link(no tab required)
-> copy and paste the resulting IDs
_____________________________________________________________________
Last update:
- [16.08.2026] - 1.1 Added comma separated ID list at the end of the report
- [21.12.2023] - 1.0 RELEASE
_____________________________________________________________________
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

report_lines = []
id_values    = []
link_cache   = {}   # RevitLinkInstance id value -> linked Document

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

    id_value = get_id_value(ref_lnk_id)
    id_values.append(str(id_value))

    report_lines.append("Element Name : {} >> Link : {} >> ID: {}".format(
        get_element_name(lnkd_selected_element),
        linked_doc.Title,
        id_value))

#OUTPUT

for line in report_lines:
    print(line)

if id_values:
    print("_" * 60)
    print(",".join(id_values))
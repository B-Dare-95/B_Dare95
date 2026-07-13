# -*- coding: utf-8 -*-
__title__     = "Copy Selected from Link"
__author__    = "Mohamed Bedair"
__version__   = 'Version = 2.0'
__doc__       = """Version = 2.0
Date    = 23.06.2026
_____________________________________________________________________
Description:

Copies selected linked elements into the active document at the same
location. Selection uses PickObjects(ObjectType.LinkedElement), which
lets you box-drag and/or ctrl-click multiple linked elements in one
pick session - click "Finish" on the options bar when done. Only the
picked elements are copied (no type-matching). Copied elements are
pinned.

Note: Revit's PickElementsByRectangle API only returns elements from
the ACTIVE document - it has no ObjectType.LinkedElement overload, so
it cannot be used to box-select linked geometry. PickObjects(Linked
Element) is the correct API for this; Revit's own pick-session UI
still allows a rectangle drag while it is active.
_____________________________________________________________________
How-to:

-> Run the script
-> Box-drag and/or ctrl-click the Linked Elements you want to copy
-> Click "Finish" on the options bar to confirm the selection
_____________________________________________________________________
Last update:
- [23.06.2026] - 2.0 Multi-select linked elements via PickObjects
- [21.12.2023] - 1.0 RELEASE
_____________________________________________________________________
Author: Mohamed Bedair"""

#IMPORTS

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
from System.Collections.Generic import List
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from Autodesk.Revit.UI.Selection import *
from pyrevit import script, EXEC_PARAMS

#VARIABLES

doc         = __revit__.ActiveUIDocument.Document
uidoc       = __revit__.ActiveUIDocument
selection   = uidoc.Selection
active_view = doc.ActiveView


#Prompt user to box-drag / ctrl-click multiple Linked Elements, then hit Finish
try:
    picked_refs = selection.PickObjects(
        ObjectType.LinkedElement,
        "Select Linked Elements (box-drag or ctrl-click), then click Finish"
    )  # type: List[Reference]
except:
    TaskDialog.Show("B-Dare95", "Please, select at least one Linked Element")
    script.exit()

if not picked_refs or len(picked_refs) == 0:
    TaskDialog.Show("B-Dare95", "No Linked Elements were selected")
    script.exit()

#Group the picked references by their parent RevitLinkInstance,
#since a rectangle can span multiple link instances/documents
link_groups = {}  # link_instance_id (str) -> {"doc": lnkd_doc, "ids": [ElementId, ...]}

for ref in picked_refs:
    # ref.ElementId is the RevitLinkInstance's ElementId in the host doc
    link_instance = doc.GetElement(ref.ElementId)

    if link_instance is None or not hasattr(link_instance, "GetLinkDocument"):
        continue

    lnkd_doc = link_instance.GetLinkDocument()
    if lnkd_doc is None:
        continue

    lnkd_el_id = ref.LinkedElementId
    if lnkd_el_id is None or lnkd_el_id == ElementId.InvalidElementId:
        continue

    key = link_instance.Id.IntegerValue if hasattr(link_instance.Id, "IntegerValue") else link_instance.Id.Value

    if key not in link_groups:
        link_groups[key] = {"doc": lnkd_doc, "ids": []}

    link_groups[key]["ids"].append(lnkd_el_id)


if len(link_groups) == 0:
    TaskDialog.Show("B-Dare95", "Could not resolve any Linked Elements from the selection")
    script.exit()


#Copy elements in-place, group by group (each group = one linked document)
t = Transaction(doc, "Bulk Copy from Link")
t.Start()

total_copied = 0

try:
    for key in link_groups:
        lnkd_doc = link_groups[key]["doc"]

        # de-duplicate ids in case the same element was picked more than once
        unique_ids = list(set(link_groups[key]["ids"]))
        List_el_ids = List[ElementId](unique_ids)

        els_to_copy = ElementTransformUtils.CopyElements(
            lnkd_doc,
            List_el_ids,
            doc,
            Transform.CreateTranslation(XYZ(0, 0, 0)),
            CopyPasteOptions()
        )

        for el_id in els_to_copy:
            copied_el = doc.GetElement(el_id)
            try:
                copied_el.Pinned = True
            except:
                pass
            total_copied += 1

    t.Commit()
except Exception as e:
    t.RollBack()
    TaskDialog.Show("B-Dare95", "Copy failed:\n" + str(e))
    script.exit()

TaskDialog.Show("B-Dare95", "Copied {} element(s) from link.".format(total_copied))
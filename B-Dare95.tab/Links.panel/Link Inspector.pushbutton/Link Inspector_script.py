# -*- coding: utf-8 -*-
__title__     = "Link Inspector"
__author__    = "Mohamed Bedair"
__version__   = 'Version = 1.0'
__doc__       = """Version = 1.0
Date    = 14.02.2024
_____________________________________________________________________
Description:

Copies all elements of the same type from a link. 
the copied elements will be pasted in project and pinned.
_____________________________________________________________________
How-to:

-> Run the script
-> select an element from a link(no tab required)
-> all elements of the same type will be copied
_____________________________________________________________________
Last update:
- [21.12.2023] - 1.0 RELEASE
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

#Start Desired Action
desired_action=forms.ask_for_one_item(actions_to_do,
                                    default=actions_to_do[0],
                                    prompt="What do you want to do?",
                                    title="Select Desired Action")
if not desired_action:
    pass
    script.exit()

#  ██████╗ ██████╗ ██████╗ ██╗   ██╗    ███████╗██╗     ███████╗███╗   ███╗███████╗███╗   ██╗████████╗███████╗    ███████╗██████╗  ██████╗ ███╗   ███╗    ██╗     ██╗███╗   ██╗██╗  ██╗
# ██╔════╝██╔═══██╗██╔══██╗╚██╗ ██╔╝    ██╔════╝██║     ██╔════╝████╗ ████║██╔════╝████╗  ██║╚══██╔══╝██╔════╝    ██╔════╝██╔══██╗██╔═══██╗████╗ ████║    ██║     ██║████╗  ██║██║ ██╔╝
# ██║     ██║   ██║██████╔╝ ╚████╔╝     █████╗  ██║     █████╗  ██╔████╔██║█████╗  ██╔██╗ ██║   ██║   ███████╗    █████╗  ██████╔╝██║   ██║██╔████╔██║    ██║     ██║██╔██╗ ██║█████╔╝
# ██║     ██║   ██║██╔═══╝   ╚██╔╝      ██╔══╝  ██║     ██╔══╝  ██║╚██╔╝██║██╔══╝  ██║╚██╗██║   ██║   ╚════██║    ██╔══╝  ██╔══██╗██║   ██║██║╚██╔╝██║    ██║     ██║██║╚██╗██║██╔═██╗
# ╚██████╗╚██████╔╝██║        ██║       ███████╗███████╗███████╗██║ ╚═╝ ██║███████╗██║ ╚████║   ██║   ███████║    ██║     ██║  ██║╚██████╔╝██║ ╚═╝ ██║    ███████╗██║██║ ╚████║██║  ██╗
#  ╚═════╝ ╚═════╝ ╚═╝        ╚═╝       ╚══════╝╚══════╝╚══════╝╚═╝     ╚═╝╚══════╝╚═╝  ╚═══╝   ╚═╝   ╚══════╝    ╚═╝     ╚═╝  ╚═╝ ╚═════╝ ╚═╝     ╚═╝    ╚══════╝╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝

elif desired_action == "Copy Elements from Link":

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


    # Selecting from Link
    ref_picked_objects = selection.PickObjects(ObjectType.LinkedElement, LinkedElemSelectionFilter())
    selected_lnk_doc = selected_lnk.GetLinkDocument()

    linked_elements = []
    for ref in ref_picked_objects:
        linked_doc = selected_lnk.GetLinkDocument()
        linked_elem = linked_doc.GetElement(ref.LinkedElementId)
        linked_elements.append(linked_elem)

    #Start A Transaction
    t = Transaction(doc,"Copy Elements from Link")

    t.Start()

    el_ids = [elem.Id for elem in linked_elements]
    List_el_ids = List[ElementId](el_ids)

    els_to_copy = ElementTransformUtils.CopyElements(selected_lnk_doc, List_el_ids, doc,
                                                     Transform.CreateTranslation(XYZ(0, 0, 0)),
                                                     CopyPasteOptions())
    for el_id in els_to_copy:
        copied_el = doc.GetElement(el_id)
        copied_el.Pinned = True

    t.Commit()

#  ██████╗ ███████╗████████╗    ███████╗██╗     ███████╗███╗   ███╗███████╗███╗   ██╗████████╗    ██╗██████╗ ███████╗
# ██╔════╝ ██╔════╝╚══██╔══╝    ██╔════╝██║     ██╔════╝████╗ ████║██╔════╝████╗  ██║╚══██╔══╝    ██║██╔══██╗██╔════╝
# ██║  ███╗█████╗     ██║       █████╗  ██║     █████╗  ██╔████╔██║█████╗  ██╔██╗ ██║   ██║       ██║██║  ██║███████╗
# ██║   ██║██╔══╝     ██║       ██╔══╝  ██║     ██╔══╝  ██║╚██╔╝██║██╔══╝  ██║╚██╗██║   ██║       ██║██║  ██║╚════██║
# ╚██████╔╝███████╗   ██║       ███████╗███████╗███████╗██║ ╚═╝ ██║███████╗██║ ╚████║   ██║       ██║██████╔╝███████║
#  ╚═════╝ ╚══════╝   ╚═╝       ╚══════╝╚══════╝╚══════╝╚═╝     ╚═╝╚══════╝╚═╝  ╚═══╝   ╚═╝       ╚═╝╚═════╝ ╚══════╝

elif desired_action == "Get Element IDs":

    all_cats = sorted(get_all_cats(doc))
    chosen_cats = forms.SelectFromList.show(all_cats, title="Choose Categories",
                                            width=300,
                                            button_name="Make A Selection",
                                            multiselect=True)
    if not chosen_cats:
        pass
        script.exit()
    class LinkedElemSelectionFilter(ISelectionFilter):

        def AllowElement(self, element):
            return True

        def AllowReference(self, reference, position):
            linked_doc = selected_lnk.GetLinkDocument()
            linked_elem = linked_doc.GetElement(reference.LinkedElementId)
            if linked_elem.Category.Name in chosen_cats:
                return True


    # Selecting from Link
    ref_picked_objects = selection.PickObjects(ObjectType.LinkedElement, LinkedElemSelectionFilter())
    selected_lnk_doc = selected_lnk.GetLinkDocument()

    linked_elements = []
    for ref in ref_picked_objects:
        linked_doc = selected_lnk.GetLinkDocument()
        linked_elem = linked_doc.GetElement(ref.LinkedElementId)
        linked_elements.append(linked_elem)

    for linked_elem in linked_elements:
       print(linked_elem.Name + " >> Element ID: " + str(linked_elem.Id.IntegerValue))

#  ██████╗ ███████╗████████╗    ██████╗  █████╗ ██████╗  █████╗ ███╗   ███╗███████╗████████╗███████╗██████╗ ███████╗
# ██╔════╝ ██╔════╝╚══██╔══╝    ██╔══██╗██╔══██╗██╔══██╗██╔══██╗████╗ ████║██╔════╝╚══██╔══╝██╔════╝██╔══██╗██╔════╝
# ██║  ███╗█████╗     ██║       ██████╔╝███████║██████╔╝███████║██╔████╔██║█████╗     ██║   █████╗  ██████╔╝███████╗
# ██║   ██║██╔══╝     ██║       ██╔═══╝ ██╔══██║██╔══██╗██╔══██║██║╚██╔╝██║██╔══╝     ██║   ██╔══╝  ██╔══██╗╚════██║
# ╚██████╔╝███████╗   ██║       ██║     ██║  ██║██║  ██║██║  ██║██║ ╚═╝ ██║███████╗   ██║   ███████╗██║  ██║███████║
#  ╚═════╝ ╚══════╝   ╚═╝       ╚═╝     ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝     ╚═╝╚══════╝   ╚═╝   ╚══════╝╚═╝  ╚═╝╚══════╝

elif desired_action == "Get Parameters":

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

    elements_to_inspect=[]
    refs_to_inspect=selection.PickObjects(ObjectType.LinkedElement,LinkedElemSelectionFilter())
    for ref in refs_to_inspect:
        linked_doc = selected_lnk.GetLinkDocument()
        linked_elem = linked_doc.GetElement(ref.LinkedElementId)
        elements_to_inspect.append(linked_elem)


    parameters_to_inspect=[]
    for elem in elements_to_inspect:
        paramset_to_inspect=elem.Parameters
        for p in paramset_to_inspect:
            if p.Definition.Name not in parameters_to_inspect:
                parameters_to_inspect.append(p.Definition.Name)

    chosen_params_to_inspect = forms.SelectFromList.show(parameters_to_inspect, title="Choose Parameters",
                                            width=300,
                                            button_name="Make A Selection",
                                            multiselect=True)

    for elem in elements_to_inspect:
        for chosen_p in chosen_params_to_inspect:
            p=elem.LookupParameter(chosen_p)
            if p.StorageType == StorageType.Integer:
                p_value = p.AsInteger()
            elif p.StorageType == StorageType.String:
                p_value = p.AsString()
            elif p.StorageType == StorageType.Double:
                p_value = p.AsDouble()

            if not p_value:
                print(elem.Name + " doesn't contain this parameter > " + chosen_p)
            else:
                print(elem.Name + " >> " + chosen_p + " : " + p_value )


#  ██████╗██╗  ██╗███████╗ ██████╗██╗  ██╗    ██╗    ██╗ ██████╗ ██████╗ ██╗  ██╗███████╗███████╗████████╗███████╗
# ██╔════╝██║  ██║██╔════╝██╔════╝██║ ██╔╝    ██║    ██║██╔═══██╗██╔══██╗██║ ██╔╝██╔════╝██╔════╝╚══██╔══╝██╔════╝
# ██║     ███████║█████╗  ██║     █████╔╝     ██║ █╗ ██║██║   ██║██████╔╝█████╔╝ ███████╗█████╗     ██║   ███████╗
# ██║     ██╔══██║██╔══╝  ██║     ██╔═██╗     ██║███╗██║██║   ██║██╔══██╗██╔═██╗ ╚════██║██╔══╝     ██║   ╚════██║
# ╚██████╗██║  ██║███████╗╚██████╗██║  ██╗    ╚███╔███╔╝╚██████╔╝██║  ██║██║  ██╗███████║███████╗   ██║   ███████║
#  ╚═════╝╚═╝  ╚═╝╚══════╝ ╚═════╝╚═╝  ╚═╝     ╚══╝╚══╝  ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝╚══════╝   ╚═╝   ╚══════╝

elif desired_action == "Check Grids & Levels Worksets":

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
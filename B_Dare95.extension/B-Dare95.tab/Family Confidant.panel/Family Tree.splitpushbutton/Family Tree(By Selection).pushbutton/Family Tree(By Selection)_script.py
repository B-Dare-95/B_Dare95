import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitServices")
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from Autodesk.Revit.UI.Selection import *
from pyrevit import forms,script,revit

# Get the current Revit document
doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

try:
    selected_ref = uidoc.Selection.PickObject(ObjectType.Element, "Select Element")

except:
    print("No Element Selected")
    script.exit()

try:

    selected_element = doc.GetElement(selected_ref)

    family_type_id = selected_element.GetTypeId()

    family_type = doc.GetElement(family_type_id)

    family_to_investigate = family_type.Family

except:
    print("Selected Element doesn't have an editable family, please select another element")
    script.exit()

def family_tree(family,lvl=1):
    if family.IsEditable:
        family_doc=doc.EditFamily(family)
        nested_families = FilteredElementCollector(family_doc).OfClass(Family).ToElements()
        print(family_doc.Title + " has " + str(len(nested_families)) + " Nested Families @ Level " + str(lvl))

        lvl += 1
        for fam in nested_families:
            if fam.IsEditable:
                family_tree(fam,lvl)
        if not nested_families:
            print("No Further Levels found")

print(family_tree(family_to_investigate))
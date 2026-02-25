# -*- coding: utf-8 -*-
import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitServices")
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from Autodesk.Revit.UI.Selection import *
from pyrevit import forms, script, revit

doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

# ── Annotation Category Filter ───────────────────────────────────────────────

EXCLUDED_CATEGORIES = {
    int(BuiltInCategory.OST_SectionHeads),
    int(BuiltInCategory.OST_LevelHeads),
    int(BuiltInCategory.OST_GridHeads),
    int(BuiltInCategory.OST_CalloutHeads),
    int(BuiltInCategory.OST_ElevationMarks),
    int(BuiltInCategory.OST_SpotElevSymbols),
    int(BuiltInCategory.OST_ViewportLabel),
}

def is_annotation_family(family):
    """Returns True if the family belongs to an annotation category that should be skipped."""
    try:
        cat_id = int(family.FamilyCategory.Id.IntegerValue)
        return cat_id in EXCLUDED_CATEGORIES
    except:
        return False

# ── Element Selection ────────────────────────────────────────────────────────

try:
    selected_ref = uidoc.Selection.PickObject(ObjectType.Element, "Select Element")
except:
    print("No element selected. Exiting.")
    script.exit()

try:
    selected_element = doc.GetElement(selected_ref)
    family_type_id   = selected_element.GetTypeId()
    family_type      = doc.GetElement(family_type_id)
    root_family      = family_type.Family
except:
    print("The selected element does not belong to an editable family. Please select another element.")
    script.exit()

# ── Parameter Helpers ────────────────────────────────────────────────────────

def get_parameter_counts(family_doc):
    mgr = family_doc.FamilyManager
    instance_params = 0
    type_params     = 0
    for param in mgr.GetParameters():
        if param.IsInstance:
            instance_params += 1
        else:
            type_params += 1
    return instance_params, type_params

# ── Recursive Tree Builder ───────────────────────────────────────────────────

def family_tree(family, level=0, prefix="", is_last=True):
    if is_annotation_family(family):
        return

    if not family.IsEditable:
        connector = "L-- " if is_last else "|-- "
        print(prefix + connector + "[Non-editable] " + family.Name)
        return

    try:
        family_doc = doc.EditFamily(family)
    except Exception as e:
        print(prefix + "L-- [Could not open] " + family.Name + " -- " + str(e))
        return

    inst_count, type_count = get_parameter_counts(family_doc)

    # Filter annotation families from nested list before counting
    nested_families = [
        f for f in FilteredElementCollector(family_doc).OfClass(Family).ToElements()
        if not is_annotation_family(f)
    ]
    nested_count = len(nested_families)

    connector   = "L-- " if is_last else "|-- "
    level_tag   = "[ROOT]" if level == 0 else "[L{}]".format(level)
    param_info  = "| Params -> Instance: {}, Type: {}".format(inst_count, type_count)
    nested_info = "| Nested Families: {}".format(nested_count)

    print(
        prefix
        + (connector if level > 0 else "")
        + "{} {} {} {}".format(level_tag, family_doc.Title, param_info, nested_info)
    )

    child_prefix = "" if level == 0 else prefix + ("    " if is_last else "|   ")

    for i, nested_fam in enumerate(nested_families):
        child_is_last = (i == nested_count - 1)
        family_tree(
            nested_fam,
            level=level + 1,
            prefix=child_prefix,
            is_last=child_is_last
        )

    if nested_count == 0:
        print(child_prefix + "L-- (no further nesting)")

# ── Run ──────────────────────────────────────────────────────────────────────

print("\n" + "=" * 60)
print("FAMILY TREE ANALYSIS")
print("=" * 60 + "\n")

family_tree(root_family)

print("\n" + "=" * 60)
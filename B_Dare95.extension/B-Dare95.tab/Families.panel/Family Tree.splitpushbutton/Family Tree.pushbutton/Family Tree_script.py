# -*- coding: utf-8 -*-
import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitServices")
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from Autodesk.Revit.UI.Selection import *
from pyrevit import forms, script, revit

doc  = __revit__.ActiveUIDocument.Document
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
    try:
        cat_id = int(family.FamilyCategory.Id.IntegerValue)
        return cat_id in EXCLUDED_CATEGORIES
    except:
        return False

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

# ── Load All Editable Families ───────────────────────────────────────────────

all_loaded_families = FilteredElementCollector(doc).OfClass(Family).ToElements()
editable_families   = [f for f in all_loaded_families if f.IsEditable]

print("\n" + "=" * 60)
print("PROJECT FAMILY ANALYSIS")
print("=" * 60)
print("Total Editable Families Found: {}".format(len(editable_families)))
print("=" * 60 + "\n")

# ── Category Selection ───────────────────────────────────────────────────────

all_cats   = sorted([cat.Name for cat in doc.Settings.Categories])
cat_chosen = forms.SelectFromList.show(
    all_cats,
    title="Choose a Category",
    width=300,
    button_name="Make a Selection",
    multiselect=False
)

if not cat_chosen:
    script.exit()

print("Investigating Category: {}".format(cat_chosen))
print("-" * 60)

# ── Filter by Category ───────────────────────────────────────────────────────

families_to_inspect = [
    f for f in editable_families
    if f.FamilyCategory and f.FamilyCategory.Name == cat_chosen
]

if not families_to_inspect:
    print("No editable families found under category: {}".format(cat_chosen))
    script.exit()

print("{} Families Found\n".format(len(families_to_inspect)))

# ── Run Tree for Each Family ─────────────────────────────────────────────────

for serial, family in enumerate(families_to_inspect):
    print("=" * 60)
    print("Family No.{} -- {}".format(serial + 1, family.Name))
    print("=" * 60)
    family_tree(family)
    print("")
# -*- coding: utf-8 -*-
"""Count Model Elements per User-Created Workset, broken down by Category."""

from pyrevit import revit, DB, script
from collections import defaultdict

doc = revit.doc
output = script.get_output()

if not doc.IsWorkshared:
    script.exit()

workset_table = doc.GetWorksetTable()

# Only user-created worksets (excludes View, Family, and other internal worksets)
user_worksets = {
    ws.Id: ws.Name
    for ws in DB.FilteredWorksetCollector(doc).OfKind(DB.WorksetKind.UserWorkset)
}

# Categories we allow through from the Annotation bucket
ALLOWED_ANNOTATION_CATS = set([
    int(DB.BuiltInCategory.OST_Levels),
    int(DB.BuiltInCategory.OST_Grids),
])

def is_valid_model_element(el):
    cat = el.Category
    if cat is None:
        return False
    if cat.Parent is not None:
        # It's a subcategory (Mullions, Balusters, Top Rails, etc.) - skip
        return False
    if cat.CategoryType == DB.CategoryType.Model:
        return True
    if cat.CategoryType == DB.CategoryType.Annotation:
        return cat.Id.IntegerValue in ALLOWED_ANNOTATION_CATS
    return False

# data[workset_name][category_name] = count
data = defaultdict(lambda: defaultdict(int))
workset_totals = defaultdict(int)

collector = DB.FilteredElementCollector(doc).WhereElementIsNotElementType().ToElements()

for el in collector:
    ws_id = el.WorksetId
    if ws_id not in user_worksets:
        continue

    if not is_valid_model_element(el):
        continue

    ws_name = user_worksets[ws_id]
    cat_name = el.Category.Name

    data[ws_name][cat_name] += 1
    workset_totals[ws_name] += 1

# ---- Output, sorted by biggest Workset first ----
sorted_worksets = sorted(workset_totals.keys(), key=lambda k: -workset_totals[k])

for ws_name in sorted_worksets:
    total = workset_totals[ws_name]
    output.print_md(u"### Workset: **{}**  \u2014  Holds {} Elements".format(ws_name, total))

    cat_counts = data[ws_name]
    sorted_cats = sorted(cat_counts.keys(), key=lambda k: -cat_counts[k])

    for cat_name in sorted_cats:
        output.print_md(u"- {} `{}`".format(cat_name, cat_counts[cat_name]))

    output.print_md("---")

output.print_md(u"**Total Model Elements Scanned:** `{}`".format(sum(workset_totals.values())))
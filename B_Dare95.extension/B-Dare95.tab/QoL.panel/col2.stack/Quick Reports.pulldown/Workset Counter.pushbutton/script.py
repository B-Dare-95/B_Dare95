# -*- coding: utf-8 -*-
"""Workset Report.

Lists every workset in the project with its creator, owner, open/closed state,
element count and a per-category breakdown. Worksets holding zero elements are
still reported.
"""

from collections import defaultdict

from pyrevit import revit, DB, forms, script

doc = revit.doc
output = script.get_output()

# --------------------------------------------------------------- settings --
# Set to True to also report View / Family / Project Standards worksets.
INCLUDE_NON_USER_WORKSETS = False

# Categories allowed through from the Annotation bucket.
ALLOWED_ANNOTATION_CATS = set([
    int(DB.BuiltInCategory.OST_Levels),
    int(DB.BuiltInCategory.OST_Grids),
])

KIND_NAMES = {
    DB.WorksetKind.UserWorkset: u"User-Created",
    DB.WorksetKind.FamilyWorkset: u"Family",
    DB.WorksetKind.ViewWorkset: u"View",
    DB.WorksetKind.StandardWorkset: u"Project Standard",
}

if not doc.IsWorkshared:
    forms.alert("This model is not workshared - there are no worksets to report.",
                title="Workset Report", exitscript=True)


# --------------------------------------------------------------- helpers ---
def id_int(some_id):
    """ElementId / WorksetId integer value, Revit 2024-2027 safe."""
    try:
        return some_id.Value
    except AttributeError:
        return some_id.IntegerValue


def get_creator(workset):
    """Worksets are backed by real elements, so the worksharing tooltip works."""
    try:
        info = DB.WorksharingUtils.GetWorksharingTooltipInfo(
            doc, DB.ElementId(id_int(workset.Id)))
        if info.Creator:
            return info.Creator
    except Exception:
        pass
    return u"<unknown>"


def get_owner(workset):
    try:
        if workset.Owner:
            return workset.Owner
    except Exception:
        pass
    return u"-"


def is_valid_model_element(el):
    try:
        cat = el.Category
    except Exception:
        return False

    if cat is None:
        return False
    if cat.Parent is not None:
        # Subcategory (Mullions, Balusters, Top Rails, ...) - skip
        return False
    if cat.CategoryType == DB.CategoryType.Model:
        return True
    if cat.CategoryType == DB.CategoryType.Annotation:
        return id_int(cat.Id) in ALLOWED_ANNOTATION_CATS
    return False


# ------------------------------------------------------- collect worksets --
worksets = []
for ws in DB.FilteredWorksetCollector(doc):
    if not INCLUDE_NON_USER_WORKSETS and ws.Kind != DB.WorksetKind.UserWorkset:
        continue
    worksets.append(ws)

# keyed by integer id - safer than hashing WorksetId objects
ws_info = {}
for ws in worksets:
    ws_info[id_int(ws.Id)] = {
        "name": ws.Name,
        "kind": KIND_NAMES.get(ws.Kind, u"Other"),
        "creator": get_creator(ws),
        "owner": get_owner(ws),
        "is_open": ws.IsOpen,
    }

# --------------------------------------------------------- count elements --
# data[ws_key][category_name] = count
data = defaultdict(lambda: defaultdict(int))
model_totals = defaultdict(int)   # model elements only
raw_totals = defaultdict(int)     # every non-type element sitting on the workset

for key in ws_info:
    model_totals[key] += 0
    raw_totals[key] += 0

collector = DB.FilteredElementCollector(doc)\
              .WhereElementIsNotElementType()\
              .ToElements()

for el in collector:
    try:
        ws_key = id_int(el.WorksetId)
    except Exception:
        continue

    if ws_key not in ws_info:
        continue

    raw_totals[ws_key] += 1

    if not is_valid_model_element(el):
        continue

    data[ws_key][el.Category.Name] += 1
    model_totals[ws_key] += 1

# ---------------------------------------------------------------- output ---
sorted_keys = sorted(ws_info.keys(),
                     key=lambda k: (-model_totals[k], ws_info[k]["name"].lower()))

closed_worksets = [ws_info[k]["name"] for k in sorted_keys if not ws_info[k]["is_open"]]

output.print_md(u"# Workset Report")
output.print_md(u"**Model:** `{}`  \u2014  **Worksets:** `{}`".format(
    doc.Title, len(sorted_keys)))

if closed_worksets:
    output.print_md(
        u"> **Warning:** {} workset(s) are closed in this session, so their elements "
        u"are not loaded and will report as 0: {}".format(
            len(closed_worksets), u", ".join(closed_worksets)))

# Summary table
table_data = []
for key in sorted_keys:
    info = ws_info[key]
    table_data.append([
        info["name"],
        info["kind"],
        info["creator"],
        info["owner"],
        u"Open" if info["is_open"] else u"Closed",
        model_totals[key],
        raw_totals[key],
        len(data[key]),
    ])

output.print_table(
    table_data=table_data,
    title="Summary",
    columns=["Workset", "Kind", "Creator", "Owner", "State",
             "Model Elements", "All Elements", "Categories"],
)

# Per-workset breakdown
output.print_md(u"# Category Breakdown")

for key in sorted_keys:
    info = ws_info[key]
    total = model_totals[key]

    output.print_md(u"### {}  \u2014  Holds {} Model Elements".format(
        info["name"], total))
    output.print_md(u"*Created by* **{}**  \u00b7  *Owner:* {}  \u00b7  *{}*".format(
        info["creator"], info["owner"],
        u"Open" if info["is_open"] else u"Closed"))

    if total == 0:
        if raw_totals[key]:
            output.print_md(
                u"- *No model elements. Holds {} other element(s) "
                u"(views, annotations, subcategories, etc.)*".format(raw_totals[key]))
        else:
            output.print_md(u"- *Empty workset*")
    else:
        cat_counts = data[key]
        sorted_cats = sorted(cat_counts.keys(),
                             key=lambda c: (-cat_counts[c], c.lower()))
        for cat_name in sorted_cats:
            output.print_md(u"- {} `{}`".format(cat_name, cat_counts[cat_name]))

    output.print_md("---")

output.print_md(u"**Total Model Elements Scanned:** `{}`  \u00b7  "
                u"**Empty Worksets:** `{}`".format(
                    sum(model_totals.values()),
                    len([k for k in sorted_keys if model_totals[k] == 0])))
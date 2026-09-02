# -*- coding: utf-8 -*-
"""Finds every "There are identical instances in the same place" warning in the
active document and deletes the duplicates, keeping the element with the oldest
(lowest) ElementId in each cluster.

Warnings that share an element are merged into a single cluster first, so a set
of three identical instances reported as three separate warnings still ends up
with exactly one survivor.

Per element, in order:
  - owned by another user  -> skipped, owner recorded
  - pinned                 -> unpinned, then deleted
  - deletion refused       -> skipped, reason recorded

Every deletion runs in its own SubTransaction, so a refusal rolls back only
that element (including its unpin) and the run carries on.
"""

__title__ = "Delete\nDuplicates"
__author__ = "Mohamed Bedair"

from Autodesk.Revit.DB import (
    BuiltInFailures,
    CheckoutStatus,
    SubTransaction,
    Transaction,
    WorksharingUtils,
)

from pyrevit import forms, script

doc = __revit__.ActiveUIDocument.Document
output = script.get_output()

CHECK = u"\u2714"
CROSS = u"\u2716"
DASH = u"\u2013"
KEEP = u"\u2691"

# Set to True to also resolve the sibling "identical <x> in the same place"
# warnings for rebar, fabric sheets and points.
INCLUDE_RELATED = False

TARGET_PROPS = ["DuplicateInstances"]
RELATED_PROPS = ["DuplicateRebar", "DuplicateFabricSheet", "DuplicatePoints"]

TARGET_TEXT = "identical instances in the same place"
RELATED_TEXT = "in the same place"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_id_value(element_id):
    """ElementId.Value (Revit 2025+) with an .IntegerValue fallback."""
    try:
        return element_id.Value
    except AttributeError:
        return element_id.IntegerValue


def collect_target_guids():
    guids = []
    props = list(TARGET_PROPS)
    if INCLUDE_RELATED:
        props.extend(RELATED_PROPS)
    for prop_name in props:
        try:
            failure_id = getattr(BuiltInFailures.OverlapFailures, prop_name)
            guids.append(failure_id.Guid)
        except Exception:
            pass
    return guids


TARGET_GUIDS = collect_target_guids()


def is_target_warning(failure):
    """True if this FailureMessage is a duplicate-instances warning."""
    try:
        failure_id = failure.GetFailureDefinitionId()
        if failure_id is not None:
            for guid in TARGET_GUIDS:
                if failure_id.Guid == guid:
                    return True
    except Exception:
        pass
    # Fallback for localized / unexpected definitions.
    try:
        text = (failure.GetDescriptionText() or "").lower()
    except Exception:
        return False
    if TARGET_TEXT in text:
        return True
    return INCLUDE_RELATED and RELATED_TEXT in text and "identical" in text


def describe(element_id):
    """Readable 'Category: Name' label for an element id."""
    element = doc.GetElement(element_id)
    if element is None:
        return u"<missing element>"
    category = u"?"
    try:
        if element.Category is not None:
            category = element.Category.Name
    except Exception:
        pass
    name = u""
    try:
        name = element.Name or u""
    except Exception:
        name = u""
    if name:
        return u"{0}: {1}".format(category, name)
    return category


def get_owner(element_id):
    """Name of the user holding the element, or an empty string."""
    try:
        info = WorksharingUtils.GetWorksharingTooltipInfo(doc, element_id)
        return info.Owner or u""
    except Exception:
        return u""


def group_note(element):
    """'member of group <name>' when the element sits inside a group."""
    try:
        group_id = element.GroupId
    except Exception:
        return u""
    if group_id is None or get_id_value(group_id) == -1:
        return u""
    group = doc.GetElement(group_id)
    label = u""
    if group is not None:
        try:
            label = group.Name or u""
        except Exception:
            label = u""
    if label:
        return u"member of group '{0}'".format(label)
    return u"member of a group"


# ---------------------------------------------------------------------------
# Gather the warnings and merge them into clusters
# ---------------------------------------------------------------------------

if doc.IsFamilyDocument:
    forms.alert("This tool runs on project documents only.", exitscript=True)

is_workshared = doc.IsWorkshared

matched_count = 0
id_lookup = {}   # value -> ElementId
reported = []    # [[value, value, ...], ...]
incomplete = []  # warnings that reported fewer than two elements

for failure in doc.GetWarnings():
    if not is_target_warning(failure):
        continue
    matched_count += 1

    raw_ids = []
    try:
        raw_ids.extend(list(failure.GetFailingElements()))
    except Exception:
        pass
    try:
        raw_ids.extend(list(failure.GetAdditionalElements()))
    except Exception:
        pass

    values = []
    for element_id in raw_ids:
        value = get_id_value(element_id)
        if value in values:
            continue
        values.append(value)
        id_lookup[value] = element_id

    if len(values) < 2:
        incomplete.append(values)
        continue
    reported.append(values)

# Union warnings that share at least one element.
clusters = []
cluster_of = {}

for values in reported:
    hits = []
    for value in values:
        index = cluster_of.get(value)
        if index is not None and index not in hits:
            hits.append(index)
    hits.sort()

    if not hits:
        clusters.append(set(values))
        target_index = len(clusters) - 1
    else:
        target_index = hits[0]
        clusters[target_index].update(values)
        for other_index in hits[1:]:
            clusters[target_index].update(clusters[other_index])
            clusters[other_index] = set()

    for value in clusters[target_index]:
        cluster_of[value] = target_index

clusters = [c for c in clusters if len(c) > 1]

plan = []  # [(keep_value, [delete_value, ...]), ...]
for cluster in clusters:
    ordered = sorted(cluster)
    plan.append((ordered[0], ordered[1:]))

total_to_delete = sum([len(item[1]) for item in plan])

if not plan:
    forms.alert(
        "No 'identical instances in the same place' warnings found "
        "in this document.",
        title="Nothing to delete",
        exitscript=True,
    )

if not forms.alert(
    "Found {0} warning(s) resolving to {1} duplicate group(s).\n\n"
    "{2} element(s) will be deleted, keeping the oldest ID in each group.\n\n"
    "Proceed?".format(matched_count, len(plan), total_to_delete),
    title="Delete Identical Instances",
    yes=True,
    no=True,
):
    script.exit()

# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

deleted = []      # [(value, label, was_pinned), ...]
skipped = []      # [(value, label, reason), ...]
cascaded = []     # values removed as a side effect of another deletion

processed = 0
output.print_md("## Deleting {0} duplicate(s) across {1} group(s)"
                .format(total_to_delete, len(plan)))

transaction = Transaction(doc, "Delete Identical Instances")
transaction.Start()
try:
    for keep_value, delete_values in plan:
        keep_id = id_lookup[keep_value]
        output.print_md("**{0} Keeping {1}** {2} {3}"
                        .format(KEEP, keep_value, DASH, describe(keep_id)))

        for delete_value in delete_values:
            processed += 1
            output.update_progress(processed, total_to_delete)

            element_id = id_lookup[delete_value]
            element = doc.GetElement(element_id)

            if element is None:
                if delete_value in cascaded:
                    print(u"    {0} {1} {2} already removed with a previous "
                          u"deletion".format(DASH, delete_value, DASH))
                else:
                    skipped.append((delete_value, u"<missing element>",
                                    u"no longer in the model"))
                    print(u"    {0} Skipped {1} {2} no longer in the model"
                          .format(DASH, delete_value, DASH))
                continue

            label = describe(element_id)

            # Ownership check first -- nothing else is worth attempting.
            if is_workshared:
                try:
                    status = WorksharingUtils.GetCheckoutStatus(doc, element_id)
                except Exception:
                    status = None
                if status == CheckoutStatus.OwnedByOtherUser:
                    owner = get_owner(element_id)
                    reason = u"owned by another user"
                    if owner:
                        reason = u"owned by '{0}'".format(owner)
                    skipped.append((delete_value, label, reason))
                    print(u"    {0} Skipped {1} {2} {3}"
                          .format(CROSS, delete_value, DASH, reason))
                    continue

            sub = SubTransaction(doc)
            sub.Start()
            was_pinned = False
            try:
                try:
                    if element.Pinned:
                        element.Pinned = False
                        was_pinned = True
                except Exception:
                    pass

                removed = doc.Delete(element_id)
                sub.Commit()

                deleted.append((delete_value, label, was_pinned))
                for removed_id in removed:
                    removed_value = get_id_value(removed_id)
                    if removed_value != delete_value:
                        cascaded.append(removed_value)

                suffix = u" (was pinned)" if was_pinned else u""
                extra = u""
                if len(removed) > 1:
                    extra = u" [+{0} dependent element(s)]".format(len(removed) - 1)
                print(u"    {0} Deleted {1} {2} {3}{4}{5}"
                      .format(CHECK, delete_value, DASH, label, suffix, extra))

            except Exception as ex:
                try:
                    sub.RollBack()
                except Exception:
                    pass
                reason = str(ex).replace("\n", " ").strip()
                note = group_note(element)
                if note:
                    reason = u"{0} ({1})".format(reason, note)
                skipped.append((delete_value, label, reason))
                print(u"    {0} Skipped {1} {2} {3}"
                      .format(CROSS, delete_value, DASH, reason))

    transaction.Commit()

except Exception as ex:
    transaction.RollBack()
    forms.alert(
        "The run was aborted and everything was rolled back:\n\n{0}".format(ex),
        title="Delete Identical Instances",
        exitscript=True,
    )

# ---------------------------------------------------------------------------
# Final report
# ---------------------------------------------------------------------------

unpinned_count = len([item for item in deleted if item[2]])

output.print_md("---")
output.print_md("## Summary")
output.print_md("- Warnings matched: **{0}**".format(matched_count))
output.print_md("- Duplicate groups: **{0}**".format(len(plan)))
output.print_md("- Elements kept: **{0}**".format(len(plan)))
output.print_md("- Elements deleted: **{0}**".format(len(deleted)))
output.print_md("- Of those, unpinned first: **{0}**".format(unpinned_count))
output.print_md("- Removed as dependents: **{0}**".format(len(cascaded)))
output.print_md("- Skipped: **{0}**".format(len(skipped)))

if skipped:
    output.print_md("### Failed deletions")
    lines = []
    for value, label, reason in skipped:
        lines.append(u"{0}  |  {1}  ->  {2}".format(value, label, reason))
    output.print_md(u"```\n{0}\n```".format(u"\n".join(lines)))

    output.print_md("Paste into **Manage > Inquiry > Select by ID**:")
    output.print_md("```\n{0}\n```".format(
        ",".join([str(item[0]) for item in skipped])))

if deleted:
    output.print_md("### Deleted element IDs")
    lines = []
    for value, label, was_pinned in deleted:
        suffix = u"  (was pinned)" if was_pinned else u""
        lines.append(u"{0}  |  {1}{2}".format(value, label, suffix))
    output.print_md(u"```\n{0}\n```".format(u"\n".join(lines)))

if incomplete:
    output.print_md("### Warnings without a usable pair")
    lines = []
    for values in incomplete:
        lines.append(", ".join([str(value) for value in values]) or "<no elements>")
    output.print_md("```\n{0}\n```".format("\n".join(lines)))
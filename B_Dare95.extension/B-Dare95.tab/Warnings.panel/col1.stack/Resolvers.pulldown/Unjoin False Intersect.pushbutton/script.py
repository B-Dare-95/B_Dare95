# -*- coding: utf-8 -*-
"""Finds every "Highlighted elements are joined but do not intersect" warning
in the active document and unjoins the reported element pairs.

Each pair is processed inside its own SubTransaction, so a pair that refuses
to unjoin is rolled back on its own and the run continues. A live report is
printed as the script works, followed by a summary listing the IDs of every
pair that could not be unjoined.
"""

__title__ = "Unjoin\nDisjoint"
__author__ = "Mohamed Bedair"

from Autodesk.Revit.DB import (
    BuiltInFailures,
    JoinGeometryUtils,
    SubTransaction,
    Transaction,
)

from pyrevit import forms, script

doc = __revit__.ActiveUIDocument.Document
output = script.get_output()

CHECK = u"\u2714"
CROSS = u"\u2716"
DASH = u"\u2013"
LINK = u"\u2194"

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
    """GUIDs of the two 'joined but do not intersect' failure definitions."""
    guids = []
    for prop_name in ("JoiningDisjoint", "JoiningDisjointWarn"):
        try:
            failure_id = getattr(BuiltInFailures.JoinElementsFailures, prop_name)
            guids.append(failure_id.Guid)
        except Exception:
            pass
    return guids


TARGET_GUIDS = collect_target_guids()
TARGET_TEXT = "joined but do not intersect"


def is_target_warning(failure):
    """True if this FailureMessage is the disjoint-join warning."""
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
        text = failure.GetDescriptionText() or ""
    except Exception:
        return False
    return TARGET_TEXT in text.lower()


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


def tag(element_id):
    """Clickable id link for the pyRevit output window."""
    value = get_id_value(element_id)
    return u"{0} [{1}]".format(output.linkify(element_id), describe(element_id))


# ---------------------------------------------------------------------------
# Gather the warnings and build a deduplicated list of element pairs
# ---------------------------------------------------------------------------

if doc.IsFamilyDocument:
    forms.alert("This tool runs on project documents only.", exitscript=True)

warnings = doc.GetWarnings()

pairs = []          # [(id_a, id_b), ...]
seen_pairs = set()  # {(min_value, max_value), ...}
incomplete = []     # warnings that did not report at least two elements
matched_count = 0

for failure in warnings:
    if not is_target_warning(failure):
        continue
    matched_count += 1

    ids = []
    try:
        ids.extend(list(failure.GetFailingElements()))
    except Exception:
        pass
    try:
        ids.extend(list(failure.GetAdditionalElements()))
    except Exception:
        pass

    unique_ids = []
    seen_values = set()
    for element_id in ids:
        value = get_id_value(element_id)
        if value in seen_values:
            continue
        seen_values.add(value)
        unique_ids.append(element_id)

    if len(unique_ids) < 2:
        incomplete.append([get_id_value(i) for i in unique_ids])
        continue

    for i in range(len(unique_ids)):
        for j in range(i + 1, len(unique_ids)):
            id_a = unique_ids[i]
            id_b = unique_ids[j]
            key = tuple(sorted([get_id_value(id_a), get_id_value(id_b)]))
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            pairs.append((id_a, id_b))

if not pairs:
    forms.alert(
        "No 'elements are joined but do not intersect' warnings found "
        "in this document.",
        title="Nothing to unjoin",
        exitscript=True,
    )

if not forms.alert(
    "Found {0} warning(s) resolving to {1} element pair(s).\n\n"
    "Unjoin them now?".format(matched_count, len(pairs)),
    title="Unjoin Disjoint Elements",
    yes=True,
    no=True,
):
    script.exit()

# ---------------------------------------------------------------------------
# Unjoin
# ---------------------------------------------------------------------------

unjoined = []   # [(value_a, value_b), ...]
skipped = []    # [(value_a, value_b, reason), ...]
failed = []     # [(value_a, value_b, reason), ...]

total = len(pairs)
output.print_md("## Unjoining {0} pair(s)".format(total))

transaction = Transaction(doc, "Unjoin Disjoint Elements")
transaction.Start()
try:
    for index, (id_a, id_b) in enumerate(pairs, 1):
        output.update_progress(index, total)

        value_a = get_id_value(id_a)
        value_b = get_id_value(id_b)

        element_a = doc.GetElement(id_a)
        element_b = doc.GetElement(id_b)

        if element_a is None or element_b is None:
            skipped.append((value_a, value_b, "element no longer in the model"))
            print(u"{0}/{1} {2} Skipped {3} {4} {5} {6} no longer in the model"
                  .format(index, total, DASH, value_a, LINK, value_b, DASH))
            continue

        sub = SubTransaction(doc)
        sub.Start()
        try:
            if not JoinGeometryUtils.AreElementsJoined(doc, element_a, element_b):
                sub.RollBack()
                skipped.append((value_a, value_b, "already unjoined"))
                print(u"{0}/{1} {2} Skipped {3} {4} {5} {6} already unjoined"
                      .format(index, total, DASH, value_a, LINK, value_b, DASH))
                continue

            JoinGeometryUtils.UnjoinGeometry(doc, element_a, element_b)
            sub.Commit()
            unjoined.append((value_a, value_b))
            print(u"{0}/{1} {2} Unjoined {3} {4} {5}"
                  .format(index, total, CHECK, tag(id_a), LINK, tag(id_b)))

        except Exception as ex:
            try:
                sub.RollBack()
            except Exception:
                pass
            reason = str(ex).replace("\n", " ").strip()
            failed.append((value_a, value_b, reason))
            print(u"{0}/{1} {2} Failed {3} {4} {5} {6} {7}"
                  .format(index, total, CROSS, value_a, LINK, value_b, DASH, reason))

    transaction.Commit()

except Exception as ex:
    transaction.RollBack()
    forms.alert(
        "The run was aborted and everything was rolled back:\n\n{0}".format(ex),
        title="Unjoin Disjoint Elements",
        exitscript=True,
    )

# ---------------------------------------------------------------------------
# Final report
# ---------------------------------------------------------------------------

output.print_md("---")
output.print_md("## Summary")
output.print_md("- Warnings matched: **{0}**".format(matched_count))
output.print_md("- Pairs processed: **{0}**".format(total))
output.print_md("- Successfully unjoined: **{0}**".format(len(unjoined)))
output.print_md("- Skipped: **{0}**".format(len(skipped)))
output.print_md("- Failed: **{0}**".format(len(failed)))

if failed:
    output.print_md("### Failed pairs")
    lines = []
    for value_a, value_b, reason in failed:
        lines.append("{0}, {1}  ->  {2}".format(value_a, value_b, reason))
    output.print_md("```\n{0}\n```".format("\n".join(lines)))

    flat = []
    for value_a, value_b, _reason in failed:
        for value in (value_a, value_b):
            if value not in flat:
                flat.append(value)
    output.print_md("Paste into **Manage > Inquiry > Select by ID**:")
    output.print_md("```\n{0}\n```".format(
        ",".join([str(value) for value in flat])))

if skipped:
    output.print_md("### Skipped pairs")
    lines = []
    for value_a, value_b, reason in skipped:
        lines.append("{0}, {1}  ->  {2}".format(value_a, value_b, reason))
    output.print_md("```\n{0}\n```".format("\n".join(lines)))

if incomplete:
    output.print_md("### Warnings without a usable pair")
    lines = []
    for values in incomplete:
        lines.append(", ".join([str(value) for value in values]) or "<no elements>")
    output.print_md("```\n{0}\n```".format("\n".join(lines)))
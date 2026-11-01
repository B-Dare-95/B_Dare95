# -*- coding: utf-8 -*-
"""DLC Link Duplicates - user-facing flows (Find / Delete / Reset)."""
from __future__ import print_function, division

import re

from pyrevit import forms, script
from Autodesk.Revit.DB import Transaction

from dlc_linkdup import engine
from dlc_linkdup import revit_ops as ops

TITLE = "DLC Link Duplicates"

DEFAULT_SETTINGS = {
    # Host categories ticked by default the first time (afterwards the
    # picker remembers your last choice)
    "HOST_CATEGORIES": ["OST_Walls", "OST_Floors", "OST_Ceilings"],
    # Host categories offered in the picker (only ones present are shown)
    "CATEGORY_CHOICES": ["OST_Walls", "OST_Floors", "OST_Ceilings", "OST_Roofs",
                         "OST_StructuralFraming", "OST_StructuralColumns",
                         "OST_Columns", "OST_StructuralFoundation",
                         "OST_GenericModel", "OST_Stairs", "OST_Ramps"],
    # Structural link categories a host element may duplicate
    "LINK_CATEGORIES": ["OST_Floors", "OST_Walls", "OST_StructuralFraming",
                        "OST_StructuralColumns", "OST_StructuralFoundation",
                        "OST_Roofs", "OST_Stairs", "OST_Ramps"],
    # Share of the host element's volume that must sit inside link geometry
    "DUPLICATE_THRESHOLD": 0.80,
    # Partial overlaps above this are listed in the report (not coloured)
    "PARTIAL_REPORT_MIN": 0.25,
    "HIGHLIGHT_RGB": (255, 0, 0),
    "BBOX_TOLERANCE_MM": 10.0,
    "COPLANAR_NUDGE_MM": 0.5,
    "GRID_CELL_MM": 6000.0,
    # Links whose name matches this are offered first
    "LINK_NAME_HINT": r"(?i)(str|struct|\bs[-_ ])",
    "REPORT_PARTIALS": True,
}

OPT_ALL = "Delete ALL detected ({0})"
OPT_SEL = "Delete SELECTED only ({0} selected in the model)"
OPT_LIST = "Choose from a list..."
OPT_REVIEW = "Review first - I'll run Delete Duplicates later"
OPT_DELETE_NOW = "Open delete options now"
OPT_HOST_DEL = "Delete them anyway (their doors/windows/openings go too)"
OPT_HOST_SKIP = "Skip elements that host doors/windows/openings"
OPT_PIN_UNPIN = "Unpin them and delete"
OPT_PIN_SKIP = "Skip pinned elements and continue"


def _settings(overrides):
    s = dict(DEFAULT_SETTINGS)
    if overrides:
        s.update(overrides)
    return s


def doc_key(doc):
    return doc.PathName or doc.Title


def _store(doc):
    return engine.store_path(doc_key(doc))


class _Item(object):
    def __init__(self, row):
        self.row = row
        self.label = "%s  |  %s  |  %s  |  %s overlap  |  ID %d" % (
            row.get("category", ""), row.get("type", ""), row.get("level", "") or "-",
            engine.pct(row.get("ratio", 0)), row["id"])


# ---------------------------------------------------------------------------
# FIND
# ---------------------------------------------------------------------------
class _Cat(object):
    def __init__(self, bic_name, label, count):
        self.bic = bic_name
        self.label = "%s  (%d)" % (label, count)


def pick_categories(doc, s, view_id):
    """Checklist of host categories that exist in scope, with element counts.
    Ticks default to the last choice (remembered per user), else settings."""
    found = []
    for name in s["CATEGORY_CHOICES"]:
        try:
            els = ops.collect_host_elements(doc, [name], view_id)
        except Exception:
            continue  # category not in this Revit version
        if els:
            label = els[0].Category.Name if els[0].Category is not None else name
            found.append(_Cat(name, label, len(els)))
    if not found:
        forms.alert("None of the checkable categories (%s) have elements in this "
                    "scope." % ", ".join(c.replace("OST_", "") for c in
                                         s["CATEGORY_CHOICES"]), title=TITLE)
        return None
    prefs = engine.load_prefs()
    ticked = set(prefs.get("host_categories") or s["HOST_CATEGORIES"])
    items = [forms.TemplateListItem(c, checked=(c.bic in ticked), name_attr="label")
             for c in found]
    picked = forms.SelectFromList.show(items, title="Which categories to check?",
                                       button_name="Check these", multiselect=True)
    if not picked:
        return None
    chosen = [c.bic for c in picked]
    prefs["host_categories"] = chosen
    try:
        engine.save_prefs(prefs)
    except Exception:
        pass  # remembering the choice is a convenience, never a blocker
    return chosen


def pick_link(doc, settings):
    links = ops.loaded_links(doc)
    if not links:
        forms.alert("There are no loaded Revit links in this model.\n\n"
                    "Load the structural model (Manage > Manage Links) and run again.",
                    title=TITLE)
        return None
    if len(links) == 1:
        return links[0]
    hint = re.compile(settings["LINK_NAME_HINT"])
    links = sorted(links, key=lambda li: (0 if hint.search(ops.link_label(li)) else 1,
                                          ops.link_label(li)))
    by_name = dict((ops.link_label(li), li) for li in links)
    picked = forms.SelectFromList.show([ops.link_label(li) for li in links],
                                       title="Which link is the structural model?",
                                       button_name="Use this link", multiselect=False)
    return by_name.get(picked) if picked else None


def run_find(doc, uidoc, overrides=None):
    s = _settings(overrides)
    view = doc.ActiveView
    if not ops.view_supports_overrides(view):
        forms.alert("The duplicates are coloured in the active view, but this view "
                    "can't take colour overrides.\n\nOpen a 3D view, plan or section "
                    "(not a sheet, schedule or view template) and run again.",
                    title=TITLE)
        return None
    link = pick_link(doc, s)
    if link is None:
        return None
    scope = forms.CommandSwitchWindow.show(
        ["Whole model", "Only elements visible in this view"],
        message="Check which host elements?")
    if not scope:
        return None
    view_id = view.Id if scope.startswith("Only") else None
    cats = pick_categories(doc, s, view_id)
    if not cats:
        return None
    s["HOST_CATEGORIES"] = cats

    with forms.ProgressBar(title="Checking against link... ({value} of {max_value})",
                           cancellable=True) as pb:
        def progress(n, total):
            if n % 10 == 0:
                pb.update_progress(n, total)
            return pb.cancelled
        result = ops.detect(doc, link, s, view_id, progress)

    if result["stats"].get("cancelled"):
        forms.alert("Cancelled - nothing was changed.", title=TITLE)
        return result

    dups = [r for r in result["rows"] if r["status"] == "duplicate"]
    partial = [r for r in result["rows"] if r["status"] == "partial"]
    rgb = s["HIGHLIGHT_RGB"]

    previous = engine.load_results(_store(doc))
    t = Transaction(doc, "DLC: Colour link duplicates")
    t.Start()
    try:
        if previous:
            old_ids = [it["id"] for it in previous["items"]]
            for vid in previous.get("view_ids", []):
                v = doc.GetElement(ops.make_eid(vid))
                if v is not None and ops.view_supports_overrides(v):
                    ops.clear_overrides(doc, v, old_ids)
        applied = ops.apply_overrides(doc, view, [r["id"] for r in dups],
                                      ops.highlight_settings(doc, rgb))
        t.Commit()
    except Exception:
        t.RollBack()
        raise

    engine.save_results(_store(doc), {
        "doc": doc_key(doc), "link": ops.link_label(link),
        "view_ids": [ops.eid_int(view.Id)],
        "threshold": s["DUPLICATE_THRESHOLD"], "items": dups,
    })
    _report_find(link, view, s, result, dups, partial, applied)

    if not dups:
        forms.alert("No duplicates found.\n\nNo host %s overlaps the link by %s or more."
                    % (_cats(s), engine.pct(s["DUPLICATE_THRESHOLD"])), title=TITLE)
        return result
    msg = "%d duplicate element(s) are now RED in '%s'." % (len(dups), view.Name)
    sub = "Full list with clickable IDs is in the report window."
    if applied < len(dups):
        sub += ("\n\n%d could not be coloured - the view may be owned by another "
                "user." % (len(dups) - applied))
    choice = forms.alert(msg, title=TITLE, sub_msg=sub,
                         options=[OPT_DELETE_NOW, OPT_REVIEW])
    if choice == OPT_DELETE_NOW:
        run_delete(doc, uidoc)
    return result


def _cats(s):
    return "/".join(c.replace("OST_", "").lower() for c in s["HOST_CATEGORIES"])


def _report_find(link, view, s, result, dups, partial, applied):
    out = script.get_output()
    st = result["stats"]
    out.print_md("## Link duplicates: %s" % ops.link_label(link))
    out.print_md("Checked **%d** host elements against **%d** link elements. "
                 "Threshold **%s** of host volume." % (
                     st["checked"], st["link_elements"],
                     engine.pct(s["DUPLICATE_THRESHOLD"])))
    out.print_md("**%d duplicates** coloured red in *%s* (%d applied)." %
                 (len(dups), view.Name, applied))
    if dups:
        _table(out, dups, "Duplicates (red)")
    if partial and s.get("REPORT_PARTIALS"):
        _table(out, partial, "Partial overlaps - genuine clashes, NOT coloured")
    notes = []
    if st["bbox_fallback"]:
        notes.append("%d element(s) were measured by bounding box because Revit "
                     "could not intersect their geometry (method = bbox) - check "
                     "these by eye." % st["bbox_fallback"])
    if st["errors"]:
        notes.append("%d element(s) were skipped after a geometry error." % st["errors"])
    for n in notes:
        out.print_md("> " + n)


def _table(out, rows, title):
    data = []
    for r in sorted(rows, key=lambda x: (-x["ratio"], x["category"])):
        data.append([out.linkify(ops.make_eid(r["id"])), r["category"], r["type"],
                     r["level"] or "-", engine.pct(r["ratio"]), r["method"], r["match"]])
    out.print_table(table_data=data, title=title,
                    columns=["ID", "Category", "Type", "Level", "Overlap",
                             "Method", "Overlaps link element"])


# ---------------------------------------------------------------------------
# DELETE
# ---------------------------------------------------------------------------
def run_delete(doc, uidoc):
    data = engine.load_results(_store(doc))
    if not data or not data["items"]:
        forms.alert("No detected duplicates for this model.\n\n"
                    "Run 'Find Link Duplicates' first.", title=TITLE)
        return None
    rows_by_id = dict((it["id"], it) for it in data["items"])
    ids = [it["id"] for it in data["items"]]
    facts = ops.delete_facts(doc, ids)
    live = [f["id"] for f in facts if f["exists"]]
    if not live:
        engine.save_results(_store(doc), engine.remove_ids(data, ids))
        forms.alert("All previously detected duplicates are already gone.", title=TITLE)
        return None

    selection = [ops.eid_int(e) for e in uidoc.Selection.GetElementIds()]
    sel = engine.selected_duplicates(live, selection)
    options = [OPT_ALL.format(len(live))]
    if sel:
        options.append(OPT_SEL.format(len(sel)))
    options.append(OPT_LIST)
    sub = ("Tip: select the red elements you want to remove in the model before "
           "running this, then choose 'Delete SELECTED only'.") if not sel else None
    choice = forms.alert("%d detected duplicate(s) from link '%s'.\nWhat do you want "
                         "to delete?" % (len(live), data.get("link", "")),
                         title=TITLE, sub_msg=sub, options=options)
    if not choice:
        return None
    if choice.startswith("Delete ALL"):
        wanted = live
    elif choice.startswith("Delete SELECTED"):
        wanted = sel
    else:
        sel_set = set(sel)
        items = [forms.TemplateListItem(_Item(rows_by_id[i]), checked=(i in sel_set),
                                        name_attr="label") for i in live]
        picked = forms.SelectFromList.show(items, title="Tick the duplicates to delete",
                                           button_name="Delete ticked",
                                           multiselect=True, width=900, height=600)
        if not picked:
            return None
        wanted = [p.row["id"] for p in picked]

    fact_map = dict((f["id"], f) for f in facts)
    hosting = [i for i in wanted if fact_map[i]["inserts"] > 0]
    skip_hosting = False
    if hosting:
        n_ins = sum(fact_map[i]["inserts"] for i in hosting)
        c = forms.alert("%d of these host %d door/window/opening(s).\nDeleting a host "
                        "deletes what it hosts." % (len(hosting), n_ins),
                        title=TITLE, options=[OPT_HOST_SKIP, OPT_HOST_DEL])
        if not c:
            return None
        skip_hosting = (c == OPT_HOST_SKIP)

    pinned = engine.pinned_candidates(facts, wanted)
    if skip_hosting:
        pinned = [i for i in pinned if fact_map[i]["inserts"] == 0]
    skip_pinned = False
    if pinned:
        c = forms.alert("%d of the elements to delete are PINNED." % len(pinned),
                        title=TITLE,
                        sub_msg="Pinned elements are usually locked on purpose. "
                                "Unpin and delete them, or skip them and delete "
                                "the rest.",
                        options=[OPT_PIN_SKIP, OPT_PIN_UNPIN])
        if not c:
            return None
        skip_pinned = (c == OPT_PIN_SKIP)

    to_delete, skipped = engine.plan_delete(facts, wanted, skip_hosting, skip_pinned)
    if not to_delete:
        _report_delete([], skipped, rows_by_id)
        forms.alert("Nothing can be deleted - see the report for reasons.", title=TITLE)
        return None
    if not forms.alert("Delete %d element(s) from the host model?" % len(to_delete),
                       title=TITLE, sub_msg="You can undo with Ctrl+Z.",
                       yes=True, no=True):
        return None

    deleted, failed, unpinned = ops.delete_elements(
        doc, to_delete, "DLC: Delete link duplicates", unpin=not skip_pinned)
    gone = deleted + [i for i, _ in skipped if _ == engine.SKIP_MISSING]
    engine.save_results(_store(doc), engine.remove_ids(data, gone))
    _report_delete(deleted, skipped + failed, rows_by_id)
    msg = "Deleted %d element(s)." % len(deleted)
    if unpinned:
        msg += "\n%d of them were unpinned first." % unpinned
    if skipped or failed:
        msg += "\n%d skipped - see the report." % len(skipped + failed)
    forms.alert(msg, title=TITLE)
    return {"deleted": deleted, "skipped": skipped, "failed": failed,
            "unpinned": unpinned}


def _report_delete(deleted, problems, rows_by_id):
    out = script.get_output()
    out.print_md("## Delete link duplicates")
    out.print_md("**%d deleted.**" % len(deleted))
    if problems:
        data = []
        for i, reason in problems:
            r = rows_by_id.get(i, {})
            data.append([out.linkify(ops.make_eid(i)), r.get("category", ""),
                         r.get("type", ""), reason])
        out.print_table(table_data=data, title="Not deleted",
                        columns=["ID", "Category", "Type", "Reason"])


# ---------------------------------------------------------------------------
# RESET
# ---------------------------------------------------------------------------
def run_reset(doc):
    data = engine.load_results(_store(doc))
    if not data or not data["items"]:
        forms.alert("Nothing to reset - no detected duplicates stored for this model.",
                    title=TITLE)
        return 0
    ids = [it["id"] for it in data["items"]]
    view_ids = list(data.get("view_ids", []))
    active = ops.eid_int(doc.ActiveView.Id)
    if active not in view_ids:
        view_ids.append(active)
    n = 0
    t = Transaction(doc, "DLC: Reset duplicate colours")
    t.Start()
    try:
        for vid in view_ids:
            v = doc.GetElement(ops.make_eid(vid))
            if v is not None and ops.view_supports_overrides(v):
                n += ops.clear_overrides(doc, v, ids)
        t.Commit()
    except Exception:
        t.RollBack()
        raise
    forms.alert("Colours cleared (%d override(s) removed).\n\nThe detected list is kept, "
                "so 'Delete Duplicates' still works." % n, title=TITLE)
    return n

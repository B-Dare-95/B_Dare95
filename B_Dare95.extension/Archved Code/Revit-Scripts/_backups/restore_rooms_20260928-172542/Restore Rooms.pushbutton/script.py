# -*- coding: utf-8 -*-
"""
DLC Restore Rooms - put 'Not Placed' rooms back into their spaces.

Rooms deleted from plan views stay in the project as 'Not Placed' (that is
why they still show in the room schedule). This tool places those SAME rooms
back - number, name and every parameter kept. You click inside each space.

Modes: highlight the missing rooms in the room schedule (no model changes),
or restore them (rows selected in a room schedule, or a whole floor).
"""
__title__ = "Restore\nRooms"
__author__ = "DLC"

# --- bootstrap: find the dlc_roomrestore library -------------------------
import os
import sys

LIB_NAME = "dlc_roomrestore"


def find_lib(start):
    """Look next to script.py, then in <each parent>\\lib up to the
    .extension folder. Returns (found_dir or None, expected_dir)."""
    here = os.path.dirname(os.path.abspath(start))
    cands = [here]
    d, ext = here, None
    for _ in range(8):
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
        cands.append(os.path.join(d, "lib"))
        if d.lower().endswith(".extension"):
            ext = d
            break
    expected = os.path.join(ext or os.path.dirname(os.path.dirname(
        os.path.dirname(here))), "lib", LIB_NAME)
    for c in cands:
        if os.path.isfile(os.path.join(c, LIB_NAME, "__init__.py")):
            if c not in sys.path:
                sys.path.insert(0, c)
            return c, expected
    return None, expected


try:
    _this = __file__
except NameError:
    _this = __commandpath__ + "\\script.py"       # noqa: F821 (pyRevit)
_found, _expected = find_lib(_this)
# --- end bootstrap ---------------------------------------------------------

from pyrevit import forms, script, revit
from Autodesk.Revit import DB

if _found is None:
    forms.alert(u"The tool's library folder is missing.\n\nCopy the folder "
                u"'%s' from the download to:\n%s\n\n(so that this file "
                u"exists: %s)\n\nThen pyRevit > Reload."
                % (LIB_NAME, _expected, os.path.join(_expected, "__init__.py")),
                title=u"DLC Restore Rooms", exitscript=True)

from dlc_roomrestore import core, revit_rooms as rr

SETTINGS = {
    "TAG_RESTORED_ROOMS": True,   # tag restored rooms in the active plan
    "PICK_RETRIES": 2,            # bad clicks allowed per room before skipping
    "OFFER_HIGHLIGHT_AFTER": True,  # offer to highlight rooms still missing
}

MODE_HIGHLIGHT = u"Highlight 'Not Placed' rooms in the room schedule"
MODE_RESTORE = u"Restore rooms (click inside each space)"

doc = revit.doc
uidoc = revit.uidoc
output = script.get_output()


def alert(msg, **kw):
    return forms.alert(msg, title=core.TOOL_NAME, **kw)


def pick_schedule(missing):
    """Best room schedule for these rooms, asking only when it's unclear."""
    ranked = rr.rank_schedules(doc, [i["key"] for i in missing], doc.ActiveView)
    if not ranked:
        alert(u"This model has no room schedule. Create one (View > Schedules > "
              u"Rooms), then run again.", exitscript=True)
    useful = [(s, n) for s, n in ranked if n > 0]
    if not useful:
        alert(u"None of the room schedules list these rooms - their filters "
              u"probably hide them (e.g. a filter on Area or Level). Remove the "
              u"filter or add an unfiltered room schedule.", exitscript=True)
    act = rr.eid_int(doc.ActiveView.Id)
    if len(useful) == 1 or rr.eid_int(useful[0][0].Id) == act or \
            useful[0][1] > useful[1][1]:
        return useful[0]
    labels = {}
    for s_, n in useful:
        labels[u"%s  -  shows %d of %d" % (DB.Element.Name.GetValue(s_), n,
                                          len(missing))] = (s_, n)
    lab = forms.SelectFromList.show(sorted(labels), multiselect=False,
                                    title=u"Highlight in which schedule?")
    if not lab:
        script.exit()
    return labels[lab]


def highlight(missing, title):
    sched, n = pick_schedule(missing)
    shown = rr.schedule_element_keys(doc, sched)
    ids = [i["room"].Id for i in missing if i["key"] in shown]
    rr.highlight_in_schedule(uidoc, sched, ids)
    output.print_md(u"## %s - %s" % (core.TOOL_NAME, title))
    output.print_md(u"**%d room(s) highlighted in '%s'.** The highlight is a "
                    u"selection: clicking elsewhere clears it. To restore them, "
                    u"keep the selection, open the floor plan and run the tool "
                    u"-> *Rooms selected in schedule*."
                    % (len(ids), DB.Element.Name.GetValue(sched)))
    rows = [[output.linkify(i["room"].Id), i["number"], i["name"],
             i["level_name"], u"yes" if i["key"] in shown else
             u"NO - hidden by schedule filters"] for i in missing]
    output.print_table(rows, columns=["Room", "Number", "Name", "Level",
                                      "In schedule"])


mode = forms.CommandSwitchWindow.show([MODE_HIGHLIGHT, MODE_RESTORE],
                                      message=u"What do you want to do?")
if not mode:
    script.exit()

if mode == MODE_HIGHLIGHT:
    all_infos = rr.rooms_in_scope(doc)
    missing_all = [i for i in all_infos if i["status"] == core.NOT_PLACED]
    if not missing_all:
        alert(u"No 'Not Placed' rooms in this model.", exitscript=True)
    per_level = {}
    for i in missing_all:
        per_level.setdefault(i["level_name"] or u"(no level)", []).append(i)
    opt_all = u"All floors  -  %d not placed" % len(missing_all)
    labels = [opt_all] + [u"%s  -  %d not placed" % (k, len(v))
                          for k, v in sorted(per_level.items())]
    lab = forms.SelectFromList.show(labels, multiselect=False,
                                    title=u"Highlight 'Not Placed' rooms on...")
    if not lab:
        script.exit()
    if lab == opt_all:
        highlight(missing_all, u"'Not Placed' rooms, all floors")
    else:
        lvl = lab.rsplit(u"  -  ", 1)[0]
        highlight(per_level[lvl], u"'Not Placed' rooms on %s" % lvl)
    script.exit()


# ----------------------------------------------------- must be in a plan view
active = doc.ActiveView
if not (isinstance(active, DB.ViewPlan) and active.GenLevel is not None):
    alert(u"Open a floor plan first.\n\nYou will click inside each space, so "
          u"the active view must be a floor plan of the floor you're restoring. "
          u"(Select the schedule rows first, then switch to the plan - the "
          u"selection is kept.)", exitscript=True)
plan_level = active.GenLevel
plan_level_key = rr.eid_int(plan_level.Id)
plan_level_name = DB.Element.Name.GetValue(plan_level)

# ------------------------------------------------------------------- scope
sel = [doc.GetElement(i) for i in uidoc.Selection.GetElementIds()]
sel_rooms = [e for e in sel if isinstance(e, DB.Architecture.Room)]
opt_sel = u"Rooms selected in schedule (%d)" % len(sel_rooms)
opt_floor = u"All rooms on this floor (%s)" % plan_level_name
choice = forms.CommandSwitchWindow.show([opt_sel, opt_floor],
                                        message=u"Which rooms?")
if not choice:
    script.exit()
if choice == opt_sel:
    if not sel_rooms:
        alert(u"No rooms are selected.\n\nIn the room schedule select the rows "
              u"of the missing rooms (Ctrl/Shift+click), switch to the floor "
              u"plan, then run the tool.", exitscript=True)
    infos = rr.rooms_in_scope(doc, ids=[r.Id for r in sel_rooms])
else:
    infos = rr.rooms_in_scope(doc, level=plan_level)

other_floor = [i for i in infos if i["level_key"] != plan_level_key]
infos = [i for i in infos if i["level_key"] == plan_level_key]
todo = [i for i in infos if i["status"] == core.NOT_PLACED]
enclosed_issue = [i for i in infos if i["status"] == core.NOT_ENCLOSED]

if not todo:
    msg = u"No 'Not Placed' rooms on %s in this selection." % plan_level_name
    if other_floor:
        msg += (u"\n\n%d selected room(s) belong to other floors - open their "
                u"plan and run again." % len(other_floor))
    if enclosed_issue:
        msg += (u"\n\n%d room(s) are 'Not Enclosed / Redundant': still placed, "
                u"but their walls/room separators are missing or they overlap "
                u"another room. Rebuild the boundaries first." % len(enclosed_issue))
    alert(msg, exitscript=True)


class RoomItem(forms.TemplateListItem):
    @property
    def name(self):
        return u"%s  %s" % (self.item["number"], self.item["name"])


chosen = forms.SelectFromList.show(
    [RoomItem(i, checked=True) for i in todo], multiselect=True,
    title=u"'Not Placed' rooms on %s (%d) - you'll click each one"
    % (plan_level_name, len(todo)), button_name=u"Start clicking")
if not chosen:
    script.exit()

# ------------------------------------------------------ empty spaces + clicks
groups = {}
for i in chosen:
    groups.setdefault(i["phase_key"], []).append(i)

jobs, not_done = [], []
for pkey, rooms in sorted(groups.items()):
    phase = rooms[0]["phase"]
    if phase is None:
        for r in rooms:
            not_done.append((r, u"Room has no phase."))
        continue
    with forms.ProgressBar(title=u"Finding empty spaces on %s..."
                           % plan_level_name, indeterminate=True):
        regions = rr.scan_empty_regions(doc, plan_level, phase)
    if not regions:
        for r in rooms:
            not_done.append((r, u"No empty enclosed space on this floor for its "
                                u"phase - boundaries may be missing."))
        continue

    def pick(prompt):
        try:
            p = uidoc.Selection.PickPoint(prompt)
            return (p.X, p.Y)
        except Exception:          # Esc -> OperationCanceledException
            return None

    assign, reasons = rr.collect_clicks(pick, rooms, regions, set(),
                                        SETTINGS["PICK_RETRIES"])
    for r in rooms:
        if r["key"] in assign:
            jobs.append({"info": r, "region": regions[assign[r["key"]]]})
        else:
            not_done.append((r, reasons.get(r["key"], u"Not placed.")))

results = []
if jobs:
    if alert(u"Place %d room(s) now?\n(one undo step - Ctrl+Z reverts all)"
             % len(jobs), yes=True, no=True):
        tag_view = active if SETTINGS["TAG_RESTORED_ROOMS"] else None
        results = rr.place_rooms(doc, jobs, tag_view=tag_view)
    else:
        script.exit()

# ------------------------------------------------------------------- report
ok_n = len([r for r in results if r[1]])
output.print_md(u"## %s v%s - %d of %d restored on %s"
                % (core.TOOL_NAME, core.TOOL_VERSION, ok_n, len(chosen),
                   plan_level_name))
rows = []
for info, ok, msg in results:
    rows.append([output.linkify(info["room"].Id), info["number"], info["name"],
                 (u"OK - " if ok else u"FAILED - ") + msg])
for r, why in not_done:
    rows.append([output.linkify(r["room"].Id), r["number"], r["name"],
                 u"NOT PLACED - " + why])
if rows:
    output.print_table(rows, columns=["Room", "Number", "Name", "Result"])
if other_floor:
    output.print_md(u"**%d selected room(s) are on other floors** - open their "
                    u"plan and run again." % len(other_floor))
if enclosed_issue:
    output.print_md(u"**%d room(s) are 'Not Enclosed / Redundant'** - fix "
                    u"walls/room separators first." % len(enclosed_issue))

still_missing = [r for r, why in not_done] + \
    [info for info, ok, msg in results if not ok]
if still_missing and SETTINGS["OFFER_HIGHLIGHT_AFTER"]:
    if alert(u"%d room(s) are still not placed.\n\nHighlight them in the room "
             u"schedule?" % len(still_missing), yes=True, no=True):
        highlight(still_missing, u"rooms still not placed")

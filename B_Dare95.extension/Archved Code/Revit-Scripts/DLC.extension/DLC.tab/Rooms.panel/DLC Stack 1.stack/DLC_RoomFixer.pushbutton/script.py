# -*- coding: utf-8 -*-
"""DLC Room Fixer - automatically fixes unbounded rooms, and verifies it.

Uses the Room Doctor diagnosis, then for every unbounded room tries fixes in
order of confidence. EVERY fix is applied in its own transaction and is only
kept when Revit, after regenerating, shows that:
  1. the room now has an area (it is bounded), and
  2. no room that was already enclosed changed area (nothing else broken).
Otherwise that fix is rolled back and the next one is tried.

Fixes (you choose which are allowed):
  * Close gaps with Room Separation Lines
  * Add Room Separation Lines along elements that do not bound rooms
    (Room Bounding off, too low/high, wrong phase, design option, link)
  * Tick Room Bounding on host walls/columns where it is unchecked
  * Move room points that sit inside a wall/column into the open space
  * Delete redundant duplicate rooms (the unbounded copy)

All changes are one Undo step, and you are asked to KEEP or ROLL BACK
everything at the end. New lines get the comment 'DLC Room Fixer'.
"""
__title__ = "Room\nFixer"
__author__ = "DLC"

import os
import sys
import time

try:
    _HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:
    from pyrevit import script as _s
    _HERE = _s.get_script_path() or ""
    if _HERE.lower().endswith(".py"):
        _HERE = os.path.dirname(_HERE)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from pyrevit import revit, DB, forms, script   # noqa: E402
import roomgaps_core as core                     # noqa: E402
import roomdoctor_core as doctor                 # noqa: E402
import roomdoctor_engine as E                    # noqa: E402

SETTINGS = {
    "version": "1.3.0",
    "min_room_area_m2": 0.5,        # a "fixed" room must be at least this big
    "collateral_tol_pct": 0.5,      # enclosed rooms may not change more than
    "collateral_tol_m2": 0.05,      # max(pct of area, m2)
    "line_extend_mm": 30.0,
    "comment": "DLC Room Fixer",
    # pass 2 searches wider for rooms pass 1 could not fix
    # pass 2 also catches TINY gaps (e.g. host wall ending 3 mm short of a
    # linked structural column) that pass 1 treats as joined
    "pass2": {"near_radius_m": 100.0, "near_gaps": 15, "max_candidates": 20,
              "ray_reach_m": 200.0, "join_tolerance_mm": 0.5},
    "move_offset_mm": 300.0,        # how far past the wall face to move a room
}

TITLE = "DLC Room Fixer"
M2 = 1.0 / (0.3048 * 0.3048)        # ft2 per m2

OPT_LINKS = ("Turn ON Room Bounding for linked models (e.g. Structure) when "
             "that bounds the rooms - verified, applies to the whole link type")
OPT_COMP = ("Raise a level's room Computation Height (to 1219 mm) when it is "
            "so low that walls are ignored - verified, applies to the level")
OPT_OVERLAP = ("Resolve overlaps Revit ignores (untick Room Bounding on one of "
               "two overlapping walls / delete a separation line lying on a "
               "wall) - verified")
OPT_GAPS = "Close gaps with Room Separation Lines"
OPT_NB_LINES = ("Add Room Separation Lines along elements that do not bound "
                "rooms (Room Bounding off, too low/high, wrong phase, design "
                "option, link)")
OPT_TICK = ("Tick Room Bounding on walls/columns where it is unchecked "
            "(edits the element instead of adding a line)")
OPT_MOVE = "Move room points that sit inside a wall/column into the open space"
OPT_DELETE = ("Delete redundant duplicate rooms (the unbounded copy - its "
              "tags are deleted too)")
OPTIONS = [(OPT_LINKS, True), (OPT_COMP, True), (OPT_OVERLAP, True),
           (OPT_GAPS, True), (OPT_NB_LINES, True),
           (OPT_TICK, False), (OPT_MOVE, True), (OPT_DELETE, True)]

FIXED = "FIXED"
FIXED_SIDE = "FIXED (by another fix)"
DELETED = "DELETED (duplicate)"
NOT_FIXED = "NOT FIXED"


# ==========================================================================
# helpers
# ==========================================================================
def eid_int(eid):
    return E.eid_int(eid)


def area_ok(room):
    try:
        return room is not None and room.Area >= \
            SETTINGS["min_room_area_m2"] * M2
    except Exception:
        return False


def owned_by_other(doc, eid):
    """Name of the other user who owns the element, else None."""
    try:
        if not doc.IsWorkshared:
            return None
        st = DB.WorksharingUtils.GetCheckoutStatus(doc, eid)
        if str(st) == "OwnedByOtherUser":
            try:
                return DB.WorksharingUtils.GetWorksharingTooltipInfo(
                    doc, eid).Owner or "another user"
            except Exception:
                return "another user"
    except Exception:
        pass
    return None


def active_option_is_main(doc):
    try:
        aid = DB.DesignOption.GetActiveDesignOptionId(doc)
        return aid is None or aid == DB.ElementId.InvalidElementId or \
            eid_int(aid) < 0
    except Exception:
        return True


class _Quiet(DB.IFailuresPreprocessor):
    """Swallow warnings (e.g. 'separation line overlaps wall'); roll back
    on errors so Revit never shows a dialog mid-run."""

    def PreprocessFailures(self, fa):
        has_error = False
        for f in fa.GetFailureMessages():
            if f.GetSeverity() == DB.FailureSeverity.Warning:
                fa.DeleteWarning(f)
            else:
                has_error = True
        if has_error:
            return DB.FailureProcessingResult.ProceedWithRollBack
        return DB.FailureProcessingResult.Continue


def quiet(t):
    try:
        opts = t.GetFailureHandlingOptions()
        opts.SetFailuresPreprocessor(_Quiet())
        opts.SetClearAfterRollback(True)
        t.SetFailureHandlingOptions(opts)
    except Exception:
        pass


class SkipFix(Exception):
    pass


# ==========================================================================
# options
# ==========================================================================
def choose_options():
    items = [forms.TemplateListItem(name, checked=on) for name, on in OPTIONS]
    picked = forms.SelectFromList.show(
        items, title="%s - which fixes may I apply?" % TITLE,
        multiselect=True, button_name="Fix rooms")
    if picked is None:
        return None
    return set(picked)


# ==========================================================================
# the fixer
# ==========================================================================
class Outcome(object):
    def __init__(self, room):
        self.room = room
        self.key = eid_int(room.Id)
        self.text = E.room_text(room)
        self.level = E.elem_name(room.Document.GetElement(room.LevelId))
        self.status = NOT_FIXED
        self.actions = []          # what was done
        self.why = ""              # why not fixed / manual step
        self.tried = 0


class Fixer(object):
    def __init__(self, doc, active, opts):
        self.doc = doc
        self.active = active
        self.opts = opts
        self.outcomes = {}
        self.created = []          # ElementIds of new separation lines
        self.ticked = []
        self.moved = 0
        self.deleted = 0
        self.applied = set()       # (group id, fix key) already in the model
        self.sketch = {}
        self.views = {}
        self.new_views = []
        self.cancelled = False
        self.whatif = E.WhatIf(doc, active)
        self.links = []            # rows for the report
        self.links_on = []         # link type names switched on
        self.global_rows = []      # model-level fixes for the report
        self.globals_done = []

    # -- low level ----------------------------------------------------------
    def view_for(self, level):
        k = eid_int(level.Id)
        if k not in self.views:
            v = E.plan_for_level(self.doc, level, self.active)
            if v is None:
                vft = self.whatif.vft
                v = DB.ViewPlan.Create(self.doc, vft, level.Id)
                try:
                    v.Name = "DLC Room Fixer - %s" % E.elem_name(level)
                except Exception:
                    pass
                self.new_views.append(E.elem_name(level))
            self.views[k] = v
        return self.views[k]

    def lines(self, level, phase_id, segments):
        doc = self.doc
        z = level.ProjectElevation
        sp = DB.SketchPlane.Create(doc, DB.Plane.CreateByNormalAndOrigin(
            DB.XYZ.BasisZ, DB.XYZ(0, 0, z)))
        arr = DB.CurveArray()
        short = doc.Application.ShortCurveTolerance
        for a, b in segments:
            if core.dist(a, b) > short:
                arr.Append(DB.Line.CreateBound(DB.XYZ(a[0], a[1], z),
                                               DB.XYZ(b[0], b[1], z)))
        if arr.Size == 0:
            raise SkipFix("nothing to draw")
        made = doc.Create.NewRoomBoundaryLines(sp, arr, self.view_for(level))
        ids = []
        for crv in made:
            if phase_id is not None:
                p = E.get_param(crv, "PHASE_CREATED")
                if p is not None:
                    p.Set(phase_id)
            c = E.get_param(crv, "ALL_MODEL_INSTANCE_COMMENTS")
            if c is not None:
                try:
                    c.Set(SETTINGS["comment"])
                except Exception:
                    pass
            ids.append(crv.Id)
        return ids

    def apply_fix(self, grp, fix, made, ticked):
        kind, i = fix
        ext = SETTINGS["line_extend_mm"] / 304.8
        if kind == "gap":
            if OPT_GAPS not in self.opts:
                raise SkipFix("closing gaps is switched off")
            g = grp.result.gaps[i]
            made.extend(self.lines(grp.level, grp.phase_id,
                                   [doctor.extend(g.a, g.b, ext)]))
            return "Room Separation Line across: %s" % E.gap_text(g)
        nb = grp.nbs[i]
        src, eid, is_link = nb.ref
        only_unchecked = (nb.reason == "Room Bounding is unchecked")
        if OPT_TICK in self.opts and only_unchecked and not is_link:
            who = owned_by_other(self.doc, eid)
            if who is None:
                el = self.doc.GetElement(eid)
                p = E.get_param(el, "WALL_ATTR_ROOM_BOUNDING", "Room Bounding")
                p.Set(1)
                ticked.append(eid)
                return "Ticked Room Bounding on %s" % nb.label
            if OPT_NB_LINES not in self.opts:
                raise SkipFix("%s is owned by %s" % (nb.label, who))
        if OPT_NB_LINES not in self.opts:
            raise SkipFix("lines along non-bounding elements are switched off")
        segs = [doctor.extend(a, b, ext) for a, b in nb.segments()]
        made.extend(self.lines(grp.level, grp.phase_id, segs))
        return "Room Separation Line along %s (%s)" % (nb.label, nb.reason)

    def enclosed_areas(self, grp):
        out = {}
        for r in E.get_rooms(self.doc):
            if r.LevelId != grp.level.Id or not E.is_placed(r):
                continue
            if grp.phase_id is not None and \
                    E.param_id(r, "ROOM_PHASE") != grp.phase_id:
                continue
            if r.Area > 1e-6:
                out[eid_int(r.Id)] = r.Area
        return out

    def collateral(self, before):
        """Text naming an enclosed room that changed, else None."""
        pct = SETTINGS["collateral_tol_pct"] / 100.0
        abs_tol = SETTINGS["collateral_tol_m2"] * M2
        for k, a0 in before.items():
            r = self.doc.GetElement(DB.ElementId(k))
            a1 = r.Area if r is not None else 0.0
            if abs(a1 - a0) > max(a0 * pct, abs_tol):
                return "it would change already-enclosed room %s (%.1f -> "  \
                    "%.1f m2)" % (E.room_text(r) if r else k, a0 / M2, a1 / M2)
        return None

    def attempt(self, case, label, work, may_change=(), must_stay=()):
        """Run work(made, ticked) -> [action texts] in a verified transaction.

        may_change: room keys allowed to change area (split of a shared space)
        must_stay:  rooms that must still be bounded afterwards
        Returns ("ok"|"shared"|"fail", info).
        """
        doc = self.doc
        grp = case.group
        before = self.enclosed_areas(grp)
        for k in may_change:
            before.pop(k, None)
        t = DB.Transaction(doc, "DLC Room Fixer - %s" % label)
        quiet(t)
        t.Start()
        made, ticked, acts = [], [], []
        try:
            acts = work(made, ticked)
            doc.Regenerate()
            room = doc.GetElement(case.room.Id)
            state = "fail"
            info = "room still not enclosed"
            if area_ok(room):
                state = "ok"
            else:
                pt = DB.XYZ(case.pt[0], case.pt[1], grp.ctx.level_z + 1.0)
                for r in E.get_rooms(doc):
                    if eid_int(r.Id) in before or r.Id == case.room.Id:
                        continue
                    if r.LevelId == grp.level.Id and area_ok(r):
                        try:
                            if r.IsPointInRoom(pt):
                                state, info = "shared", r
                                break
                        except Exception:
                            pass
            if state != "fail":
                bad = self.collateral(before)
                for r in must_stay:
                    if not area_ok(doc.GetElement(r.Id)):
                        bad = bad or ("room %s would lose its boundary"
                                      % E.room_text(r))
                if bad:
                    state, info = "fail", bad
            if state == "fail":
                t.RollBack()
                return "fail", info
            st = t.Commit()
            if str(st) != "Committed":
                return "fail", "Revit rejected the change (%s)" % st
        except SkipFix as ex:
            if t.HasStarted() and not t.HasEnded():
                t.RollBack()
            return "fail", str(ex)
        except Exception as ex:
            if t.HasStarted() and not t.HasEnded():
                t.RollBack()
            return "fail", "error: %s" % ex
        self.created.extend(made)
        self.ticked.extend(ticked)
        return state, (acts, info)

    # -- per room ----------------------------------------------------------
    def fix_case(self, case):
        out = self.outcomes[case.key]
        doc = self.doc
        grp = case.group

        # redundant ------------------------------------------------------
        if case.redundant_of is not None:
            self.handle_redundant(case, out, case.redundant_of)
            return

        # point inside a wall / column --------------------------------
        if case.inside is not None:
            if OPT_MOVE not in self.opts:
                out.why = ("Room point is inside %s - moving rooms is "
                           "switched off." % case.inside.label)
                return
            who = owned_by_other(doc, case.room.Id)
            if who:
                out.why = "Room is owned by %s - ask them to sync." % who
                return
            for target in self.move_targets(case):
                def work(made, ticked, target=target):
                    v = DB.XYZ(target[0] - case.pt[0], target[1] - case.pt[1], 0)
                    DB.ElementTransformUtils.MoveElement(doc, case.room.Id, v)
                    return ["Moved room point out of %s by %d mm"
                            % (case.inside.label,
                               core.dist(target, case.pt) * 304.8)]
                out.tried += 1
                state, info = self.attempt(case, "move %s" % out.text, work)
                if state == "ok":
                    self.moved += 1
                    out.status = FIXED
                    out.actions.extend(info[0])
                    return
            out.why = ("Room point is inside %s. Moving it to either side "
                       "did not give a bounded room (both sides may already "
                       "have a room) - check for a duplicate." % case.inside.label)
            return

        if case.open_space:
            out.why = ("Nothing bounds this room in any direction: it is in "
                       "open space or on the wrong level. Move or delete it.")
            return

        # single fixes, then the smallest working combination -------------
        cands = [f for f in case.cands if (id(grp), f) not in self.applied]
        reasons = []
        for fix in cands:
            if self.cancelled:
                return
            out.tried += 1
            state, info = self.attempt(
                case, out.text,
                lambda made, ticked, fix=fix: [self.apply_fix(grp, fix, made,
                                                              ticked)])
            if state in ("ok", "shared"):
                self.applied.add((id(grp), fix))
                out.actions.extend(info[0])
                if state == "ok":
                    out.status = FIXED
                else:
                    self.handle_redundant(case, out, info[1])
                return
            reasons.append(info)
        if len(cands) >= 2 and not self.cancelled:
            usable = [f for f in cands if self.allowed(grp, f)]
            segs_for = lambda fixes: [s for f in fixes  # noqa: E731
                                      for s in E.fix_segments(grp, f)]

            def encloses(fixes):
                res = self.whatif.test(grp.level, segs_for(fixes), [case])
                return bool(res and res.get(case.key))
            if len(usable) >= 2 and encloses(usable):
                need = doctor.reduce_set(usable, encloses)

                def work(made, ticked, need=need):
                    return [self.apply_fix(grp, f, made, ticked) for f in need]
                out.tried += 1
                state, info = self.attempt(case, out.text, work)
                if state in ("ok", "shared"):
                    for f in need:
                        self.applied.add((id(grp), f))
                    out.actions.extend(info[0])
                    if state == "ok":
                        out.status = FIXED
                    else:
                        self.handle_redundant(case, out, info[1])
                    return
                reasons.append(info)
        if not out.why:
            main = case.main()
            text = [r for r in reasons if isinstance(r, str) and
                    r.startswith("it would change")]
            if text:
                out.why = "The fix was rejected because %s." % text[0]
            elif main is not None:
                out.why = "%s %s" % (main.text, main.fix)
            else:
                out.why = "No open boundary found near this room."

    def allowed(self, grp, fix):
        if fix[0] == "gap":
            return OPT_GAPS in self.opts
        return OPT_NB_LINES in self.opts or OPT_TICK in self.opts

    def move_targets(self, case):
        ch = case.inside
        off = SETTINGS["move_offset_mm"] / 304.8
        d, c = ch.distance_to(case.pt)
        best = None
        for a, b in ch.segments():
            dd, cc = core.dist_point_segment(case.pt, a, b)
            if best is None or dd < best[0]:
                best = (dd, cc, a, b)
        _, cc, a, b = best
        dx, dy = b[0] - a[0], b[1] - a[1]
        n = (dx * dx + dy * dy) ** 0.5 or 1.0
        nx, ny = -dy / n, dx / n
        if ch.closed:                                  # column: 4 sides
            bb = ch.bbox
            cx, cy = (bb[0] + bb[2]) / 2.0, (bb[1] + bb[3]) / 2.0
            hx, hy = (bb[2] - bb[0]) / 2.0 + off, (bb[3] - bb[1]) / 2.0 + off
            return [(cx + hx, cy), (cx - hx, cy), (cx, cy + hy), (cx, cy - hy)]
        w = ch.half_width + off
        return [(cc[0] + nx * w, cc[1] + ny * w), (cc[0] - nx * w, cc[1] - ny * w)]

    def try_split(self, case, out, host):
        """Shared space: make the ignored element between the two room
        points bound rooms, so BOTH rooms become bounded."""
        if OPT_NB_LINES not in self.opts and OPT_TICK not in self.opts:
            return False
        grp = case.group
        hp = host.Location.Point
        a, b = case.pt, (hp.X, hp.Y)
        tol = E.mm(E.SETTINGS["join_tolerance_mm"])
        between = [("nb", i) for i, nb in enumerate(grp.nbs)
                   if not nb.closed and
                   nb.distance_to_segment(a, b) <= nb.half_width + tol]
        if not between:
            return False

        def work(made, ticked):
            return [self.apply_fix(grp, f, made, ticked) for f in between]
        out.tried += 1
        state, info = self.attempt(case, "split %s" % out.text, work,
                                   may_change=(eid_int(host.Id),),
                                   must_stay=(host,))
        if state == "ok":
            for f in between:
                self.applied.add((id(grp), f))
            out.status = FIXED
            out.actions.extend(info[0])
            out.actions.append("Split the space shared with room %s"
                               % E.room_text(host))
            return True
        return False

    def handle_redundant(self, case, out, host):
        host_txt = E.room_text(host)
        if self.try_split(case, out, host):
            return
        if OPT_DELETE not in self.opts:
            out.why = ("Redundant: it shares its space with room %s. Delete "
                       "one of them (deleting is switched off)." % host_txt)
            return
        who = owned_by_other(self.doc, case.room.Id)
        if who:
            out.why = "Redundant with %s, but owned by %s." % (host_txt, who)
            return

        def work(made, ticked):
            self.doc.Delete(case.room.Id)
            return ["Deleted duplicate room (its space belongs to room %s)"
                    % host_txt]
        t = DB.Transaction(self.doc, "DLC Room Fixer - delete duplicate")
        quiet(t)
        before_host = host.Area
        t.Start()
        try:
            acts = work([], [])
            self.doc.Regenerate()
            h = self.doc.GetElement(host.Id)
            if h is None or abs(h.Area - before_host) > 1e-6 * max(1.0, before_host):
                t.RollBack()
                out.why = "Deleting it would change room %s - left as is." \
                    % host_txt
                return
            st = t.Commit()
            if str(st) != "Committed":
                out.why = "Revit refused to delete it (%s)." % st
                return
        except Exception as ex:
            if t.HasStarted() and not t.HasEnded():
                t.RollBack()
            out.why = "Could not delete: %s" % ex
            return
        self.deleted += 1
        out.status = DELETED
        out.actions.extend(acts)

    # -- linked models -------------------------------------------------------
    def fix_links(self, rooms):
        """Turn ON Room Bounding on link types when that bounds rooms.

        Kept only if at least one room in scope becomes bounded and NO room
        anywhere that was enclosed loses its boundary. Area changes of other
        rooms are expected (they now stop at the structure) and reported.
        """
        doc = self.doc
        seen = set()
        for li in DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkInstance):
            lt = doc.GetElement(li.GetTypeId())
            if lt is None or eid_int(lt.Id) in seen:
                continue
            seen.add(eid_int(lt.Id))
            name = E.link_name(li, lt, li.GetLinkDocument())
            row = {"name": name, "loaded": li.GetLinkDocument() is not None,
                   "rb": E.param_int(lt, "WALL_ATTR_ROOM_BOUNDING",
                                     "Room Bounding"),
                   "result": ""}
            self.links.append(row)
            if not row["loaded"]:
                row["result"] = ("Not loaded - Revit cannot use it for rooms. "
                                 "Reload it in Manage Links.")
                continue
            if row["rb"] != 0:
                row["result"] = "Room Bounding already ON."
                continue
            if OPT_LINKS not in self.opts:
                row["result"] = "Room Bounding OFF (turning links on is "                      "switched off)."
                continue
            who = owned_by_other(doc, lt.Id)
            if who:
                row["result"] = ("Room Bounding OFF - the link type is owned "
                                 "by %s; ask them to sync, then run again."
                                 % who)
                continue
            self.try_link(lt, row, rooms)

    def try_link(self, lt, row, rooms):
        doc = self.doc
        before = {}
        for r in E.get_rooms(doc):
            if E.is_placed(r) and r.Area > 1e-6:
                before[eid_int(r.Id)] = r.Area
        targets = [r for r in rooms if doc.GetElement(r.Id) is not None and
                   E.is_unbounded(doc.GetElement(r.Id))]
        t = DB.Transaction(doc, "DLC Room Fixer - link %s" % row["name"])
        quiet(t)
        t.Start()
        try:
            p = E.get_param(lt, "WALL_ATTR_ROOM_BOUNDING", "Room Bounding")
            p.Set(1)
            doc.Regenerate()
            fixed = [r for r in targets if area_ok(doc.GetElement(r.Id))]
            broken, changed = [], 0
            for k, a0 in before.items():
                r = doc.GetElement(DB.ElementId(k))
                if r is None or not r.Area > 1e-6:
                    broken.append(r)
                elif abs(r.Area - a0) > max(
                        a0 * SETTINGS["collateral_tol_pct"] / 100.0,
                        SETTINGS["collateral_tol_m2"] * M2):
                    changed += 1
            if not fixed or broken:
                t.RollBack()
                if broken:
                    row["result"] = ("NOT turned on: it would unbound "
                                     "enclosed room(s) %s (their room point "
                                     "sits inside a linked element). Move "
                                     "those rooms, then run again."
                                     % ", ".join(E.room_text(r) for r in
                                                 broken[:5] if r is not None))
                else:
                    row["result"] = ("Room Bounding OFF - turning it on does "
                                     "not bound any of these rooms, so it was "
                                     "left off.")
                return
            st = t.Commit()
            if str(st) != "Committed":
                row["result"] = "Revit rejected the change (%s)." % st
                return
        except Exception as ex:
            if t.HasStarted() and not t.HasEnded():
                t.RollBack()
            row["result"] = "Could not change it: %s" % ex
            return
        self.links_on.append(row["name"])
        row["result"] = ("Room Bounding turned ON - bounded %d room(s) here%s."
                         % (len(fixed), ("; %d other room(s) now stop at the "
                                         "linked elements (area adjusted)"
                                         % changed) if changed else ""))
        for r in fixed:
            o = self.outcomes.get(eid_int(r.Id))
            if o is not None and o.status == NOT_FIXED:
                o.status = FIXED
                o.actions.append("Turned ON Room Bounding for link '%s'"
                                 % row["name"])

    # -- model-level fixes (Computation Height, overlaps) ----------------
    def fix_globals(self, rooms):
        doc = self.doc
        todo = [r for r in rooms if doc.GetElement(r.Id) is not None and
                E.is_unbounded(doc.GetElement(r.Id))]
        if not todo:
            return
        groups, _ = self.build_groups(todo)
        acts = E.global_actions(doc, groups, E.warnings_list(doc))
        for a in acts:
            kind = a.key[0]
            if kind == "link":
                continue                       # handled by fix_links
            if kind in ("comp", "comp+links") and OPT_COMP not in self.opts:
                continue
            if kind == "comp+links" and OPT_LINKS not in self.opts:
                continue
            if kind in ("rboff", "delsep") and OPT_OVERLAP not in self.opts:
                continue
            left = [r for r in todo if doc.GetElement(r.Id) is not None and
                    E.is_unbounded(doc.GetElement(r.Id))]
            if not left:
                break
            row = {"what": a.done_text, "result": ""}
            who = None
            for i in a.owner_ids:
                who = who or owned_by_other(doc, i)
            if who:
                row["result"] = "Skipped - owned by %s." % who
                self.global_rows.append(row)
                continue
            self.try_global(a, row, left)
            if row["result"]:
                self.global_rows.append(row)

    def try_global(self, a, row, targets):
        doc = self.doc
        before = {}
        for r in E.get_rooms(doc):
            if E.is_placed(r) and r.Area > 1e-6:
                before[eid_int(r.Id)] = r.Area
        t = DB.Transaction(doc, "DLC Room Fixer - %s" % a.done_text[:60])
        quiet(t)
        t.Start()
        try:
            a.apply(doc)
            doc.Regenerate()
            fixed = [r for r in targets if area_ok(doc.GetElement(r.Id))]
            broken, changed = [], 0
            for k, a0 in before.items():
                r = doc.GetElement(DB.ElementId(k))
                if r is None or not r.Area > 1e-6:
                    broken.append(r)
                elif abs(r.Area - a0) > max(
                        a0 * SETTINGS["collateral_tol_pct"] / 100.0,
                        SETTINGS["collateral_tol_m2"] * M2):
                    changed += 1
            if not fixed or broken:
                t.RollBack()
                if broken:
                    row["result"] = ("Not applied: it would unbound enclosed "
                                     "room(s) %s." % ", ".join(
                                         E.room_text(r) for r in broken[:5]
                                         if r is not None))
                return
            st = t.Commit()
            if str(st) != "Committed":
                row["result"] = "Revit rejected it (%s)." % st
                return
        except Exception as ex:
            if t.HasStarted() and not t.HasEnded():
                t.RollBack()
            row["result"] = "Could not apply: %s" % ex
            return
        self.globals_done.append(a.done_text)
        row["result"] = "APPLIED - bounded %d room(s)%s." % (
            len(fixed), ("; %d other room(s) changed area" % changed)
            if changed else "")
        for r in fixed:
            o = self.outcomes.get(eid_int(r.Id))
            if o is not None and o.status == NOT_FIXED:
                o.status = FIXED
                o.actions.append(a.done_text)

    # -- driver ------------------------------------------------------------
    def build_groups(self, rooms):
        doc = self.doc
        link_notes = {}
        groups, by_key = [], {}
        for r in rooms:
            lv = doc.GetElement(r.LevelId)
            if lv is None:
                continue
            ph = E.param_id(r, "ROOM_PHASE")
            k = (eid_int(lv.Id), eid_int(ph) if ph is not None else -1)
            if k not in by_key:
                by_key[k] = E.Group(doc, lv, ph, link_notes)
                groups.append(by_key[k])
            by_key[k].cases.append(E.Case(r, by_key[k]))
        all_rooms = E.get_rooms(doc)
        for grp in groups:
            enclosed = [x for x in all_rooms
                        if x.LevelId == grp.level.Id and E.is_placed(x)
                        and not E.is_unbounded(x)
                        and (grp.phase_id is None or
                             E.param_id(x, "ROOM_PHASE") == grp.phase_id)]
            E.diagnose_group(doc, grp, enclosed, {})
        return groups, sorted(link_notes.keys())

    def run(self, rooms, pb_factory):
        for r in rooms:
            self.outcomes[eid_int(r.Id)] = Outcome(r)
        base = dict(E.SETTINGS)
        notes = []
        passes = [{}, SETTINGS["pass2"]]
        self.fix_links(rooms)
        self.fix_globals(rooms)
        with pb_factory() as pb:
            for pi, over in enumerate(passes):
                E.SETTINGS.clear()
                E.SETTINGS.update(base)
                E.SETTINGS.update(over)
                todo = []
                for k, o in self.outcomes.items():
                    if o.status != NOT_FIXED:
                        continue
                    r = self.doc.GetElement(o.room.Id)
                    if r is None:
                        continue
                    if not E.is_unbounded(r):
                        o.status = FIXED_SIDE
                        continue
                    o.why = ""
                    todo.append(r)
                if not todo:
                    break
                groups, ln = self.build_groups(todo)
                for n in ln:
                    if n not in notes:
                        notes.append(n)
                cases = [c for g in groups for c in g.cases]
                for i, c in enumerate(cases):
                    pb.update_progress(i + 1, len(cases))
                    if pb.cancelled:
                        self.cancelled = True
                        break
                    r = self.doc.GetElement(c.room.Id)
                    if r is not None and not E.is_unbounded(r):
                        self.outcomes[c.key].status = FIXED_SIDE
                        continue
                    self.fix_case(c)
                if self.cancelled:
                    notes.append("Cancelled - remaining rooms were not "
                                 "attempted.")
                    break
        E.SETTINGS.clear()
        E.SETTINGS.update(base)
        # final truth: re-read every room
        for o in self.outcomes.values():
            r = self.doc.GetElement(o.room.Id)
            if o.status == DELETED:
                continue
            if r is not None and not E.is_unbounded(r) and o.status == NOT_FIXED:
                o.status = FIXED_SIDE
            if o.status in (FIXED, FIXED_SIDE) and (r is None or not area_ok(r)):
                o.status = NOT_FIXED
                o.why = o.why or "Room is not bounded after all fixes."
        if self.new_views:
            notes.append("Created a floor plan for level(s) with none: %s."
                         % ", ".join(self.new_views))
        return notes

    def changes(self):
        return len(self.created) + len(self.ticked) + self.moved + \
            self.deleted + len(self.links_on) + len(self.globals_done)


# ==========================================================================
# report
# ==========================================================================
ORDER = {FIXED: 0, FIXED_SIDE: 1, DELETED: 2, NOT_FIXED: 3}


def report(output, scope, fixer, notes, kept, elapsed):
    outs = sorted(fixer.outcomes.values(),
                  key=lambda o: (ORDER[o.status], o.level, o.text))
    n_fixed = len([o for o in outs if o.status in (FIXED, FIXED_SIDE)])
    n_del = len([o for o in outs if o.status == DELETED])
    n_not = len([o for o in outs if o.status == NOT_FIXED])
    output.print_md("# %s - %s" % (TITLE, scope))
    if kept:
        output.print_md("**%d bounded, %d duplicate(s) deleted, %d not fixed** "
                        "out of %d unbounded room(s). Changes KEPT - one Undo "
                        "('DLC Room Fixer') reverses them all.  (v%s, %.0f s)"
                        % (n_fixed, n_del, n_not, len(outs),
                           SETTINGS["version"], elapsed))
    else:
        output.print_md("**Nothing was changed** - all fixes were rolled back. "
                        "The table shows what WOULD have been fixed.")
    output.print_md("- %d Room Separation Line(s) added (comment '%s'), %d "
                    "element(s) set to Room Bounding, %d room(s) moved, %d "
                    "duplicate(s) deleted." % (len(fixer.created),
                                               SETTINGS["comment"],
                                               len(fixer.ticked), fixer.moved,
                                               fixer.deleted))
    if kept and fixer.created:
        try:
            output.print_md("- Select them: %s" % output.linkify(
                fixer.created, "all %d added lines" % len(fixer.created)))
        except Exception:
            pass
    for n in notes:
        output.print_md("- **Note:** %s" % n)
    if fixer.links:
        output.print_table(
            [[lk["name"], "Yes" if lk["loaded"] else "NO",
              {0: "OFF", 1: "ON"}.get(lk["rb"], "?"), lk["result"]]
             for lk in fixer.links],
            columns=["Linked model", "Loaded", "Room Bounding (before)",
                     "Result"], title="Linked models")
    if fixer.global_rows:
        output.print_table([[g["what"], g["result"]] for g in fixer.global_rows],
                           columns=["Model-level fix tried", "Result"],
                           title="Model-level fixes")
    rows = []
    for o in outs:
        try:
            rid = output.linkify(o.room.Id) if o.status != DELETED or not kept \
                else str(o.key)
        except Exception:
            rid = str(o.key)
        did = "<br>".join(o.actions) if o.actions else "-"
        rows.append([rid, o.text, o.level, o.status, did,
                     o.why if o.status == NOT_FIXED else ""])
    output.print_table(rows, columns=["Room", "Number / Name", "Level",
                                      "Result", "What was done",
                                      "Why not fixed / do this manually"],
                       title="Results")
    if n_not:
        output.print_md("_Rooms NOT FIXED need a design decision. Run Room "
                        "Doctor on them for full evidence._")


# ==========================================================================
# main
# ==========================================================================
def main():
    doc = revit.doc
    uidoc = revit.uidoc
    if doc.IsFamilyDocument:
        forms.alert("Open a project model, not a family.", title=TITLE)
        return
    if getattr(doc, "IsReadOnly", False):
        forms.alert("This model is read-only - nothing can be fixed.",
                    title=TITLE)
        return
    if not active_option_is_main(doc):
        forms.alert("A design option is active. Set Design Options to "
                    "'Main Model' first, otherwise the fixes would go into "
                    "that option.", title=TITLE)
        return
    all_rooms = E.get_rooms(doc)
    if not all_rooms:
        forms.alert("This model has no rooms.", title=TITLE)
        return
    rooms, scope = E.choose_rooms(doc, uidoc, all_rooms)
    if rooms is None:
        return
    unbounded = [r for r in rooms if E.is_unbounded(r)]
    if not unbounded:
        forms.alert("No unbounded rooms in '%s' - nothing to fix." % scope,
                    title=TITLE)
        return
    opts = choose_options()
    if not opts:
        return
    t0 = time.time()

    fixer = Fixer(doc, uidoc.ActiveView, opts)
    tg = DB.TransactionGroup(doc, "DLC Room Fixer")
    tg.Start()
    kept = False
    try:
        def pbf():
            return forms.ProgressBar(title="Room Fixer - fixing rooms "
                                           "({value}/{max_value})",
                                     cancellable=True)
        notes = fixer.run(unbounded, pbf)
        if fixer.changes() == 0:
            tg.RollBack()
        else:
            outs = fixer.outcomes.values()
            nf = len([o for o in outs if o.status in (FIXED, FIXED_SIDE)])
            nd = len([o for o in outs if o.status == DELETED])
            nn = len([o for o in outs if o.status == NOT_FIXED])
            msg = ("%d of %d room(s) are now bounded%s.%s\n\n"
                   "Changes: %s%d separation line(s), %d Room Bounding "
                   "tick(s), %d room(s) moved, %d duplicate room(s) "
                   "DELETED.\n\n"
                   "KEEP these changes?  (No = roll everything back)"
                   % (nf, len(outs),
                      (", %d duplicate(s) deleted" % nd) if nd else "",
                      ("\n%d room(s) need a manual decision - see the report."
                       % nn) if nn else "",
                      (("Room Bounding ON for link(s): %s; "
                        % ", ".join(fixer.links_on)) if fixer.links_on
                       else "") + "".join("%s; " % g for g in
                                          fixer.globals_done),
                      len(fixer.created), len(fixer.ticked), fixer.moved,
                      fixer.deleted))
            if forms.alert(msg, title=TITLE, yes=True, no=True):
                tg.Assimilate()
                kept = True
            else:
                tg.RollBack()
    except Exception as ex:
        if tg.HasStarted() and not tg.HasEnded():
            tg.RollBack()
        forms.alert("Something went wrong - every change was rolled back, "
                    "the model is as before.\n\nReason: %s" % ex, title=TITLE)
        return

    output = script.get_output()
    try:
        output.set_title(TITLE)
    except Exception:
        pass
    report(output, scope, fixer, notes, kept, time.time() - t0)


if __name__ == "__main__":
    main()

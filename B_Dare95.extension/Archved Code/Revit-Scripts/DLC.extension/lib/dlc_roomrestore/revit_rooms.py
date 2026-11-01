# -*- coding: utf-8 -*-
"""
DLC Restore Rooms - Revit API layer (Revit 2025/2026, IronPython 2.7).

Key facts:
- An unplaced room ('Not Placed' in schedules) can only be placed back with
  Document.NewRoom(Room, PlanCircuit) - there is no (Room, point) overload.
- PlanCircuit exposes no outline, so empty regions are measured by placing
  temporary rooms and reading their boundaries, then rolling back.
- Circuits go stale after regeneration -> topology is re-read every time.
- Room.Name/Number are read through parameters (IronPython explicit-interface
  issue).
"""
from dlc_roomrestore import core

try:
    from Autodesk.Revit import DB                     # noqa
except Exception:                                     # pragma: no cover
    DB = None


def eid_int(eid):
    v = getattr(eid, "Value", None)
    if v is None:
        v = eid.IntegerValue
    return int(v)


def _p_str(el, bip):
    try:
        p = el.get_Parameter(bip)
        return (p.AsString() or u"") if p is not None else u""
    except Exception:
        return u""


def room_phase_id(room):
    try:
        return room.get_Parameter(DB.BuiltInParameter.ROOM_PHASE).AsElementId()
    except Exception:
        return None


def room_info(doc, room):
    loc = None
    try:
        loc = room.Location
    except Exception:
        pass
    try:
        area = room.Area
    except Exception:
        area = 0.0
    lvl = doc.GetElement(room.LevelId) if room.LevelId is not None else None
    ph = room_phase_id(room)
    phe = doc.GetElement(ph) if ph is not None else None
    return {
        "room": room, "key": eid_int(room.Id),
        "number": _p_str(room, DB.BuiltInParameter.ROOM_NUMBER),
        "name": _p_str(room, DB.BuiltInParameter.ROOM_NAME),
        "level": lvl, "level_name": DB.Element.Name.GetValue(lvl) if lvl else u"",
        "level_key": eid_int(room.LevelId) if room.LevelId is not None else None,
        "phase": phe, "phase_key": eid_int(ph) if ph is not None else None,
        "status": core.classify(loc is not None, area),
    }


def rooms_in_scope(doc, level=None, ids=None):
    """All rooms on a level, or the rooms among the given element ids."""
    if ids is not None:
        els = [doc.GetElement(i) for i in ids]
    else:
        els = list(DB.FilteredElementCollector(doc)
                   .OfCategory(DB.BuiltInCategory.OST_Rooms)
                   .WhereElementIsNotElementType())
    out = []
    for el in els:
        if el is None or not isinstance(el, DB.Architecture.Room):
            continue
        info = room_info(doc, el)
        if level is not None and info["level_key"] != eid_int(level.Id):
            continue
        out.append(info)
    out.sort(key=lambda r: (r["level_name"], core.norm_number(r["number"])))
    return out


# ----------------------------------------------------------- empty regions
def _loops_of(room):
    loops = []
    opts = DB.SpatialElementBoundaryOptions()
    for seg_list in room.GetBoundarySegments(opts) or []:
        pts = []
        for seg in seg_list:
            for p in seg.GetCurve().Tessellate():
                q = (round(p.X, 6), round(p.Y, 6))
                if not pts or pts[-1] != q:
                    pts.append(q)
        if len(pts) > 1 and pts[0] == pts[-1]:
            pts.pop()
        if len(pts) >= 3:
            loops.append(pts)
    return loops


def scan_empty_regions(doc, level, phase, max_regions=2000):
    """
    Outline of every enclosed region on level/phase that has no room.
    Places temporary rooms and ROLLS BACK - the model is not changed.
    Must be called with no transaction open.
    """
    regions, failed = {}, set()
    t = DB.Transaction(doc, "DLC scan empty room regions (rolled back)")
    t.Start()
    try:
        rid = 0
        while rid < max_regions:
            topo = doc.get_PlanTopology(level, phase)
            target = None
            for c in topo.Circuits:
                if c.IsRoomLocated:
                    continue
                uv = c.GetPointInside()
                k = (round(uv.U, 4), round(uv.V, 4))
                if k in failed:
                    continue
                target, key = c, k
                break
            if target is None:
                break
            try:
                tmp = doc.Create.NewRoom(None, target)
                loops = _loops_of(tmp) if tmp is not None else []
            except Exception:
                loops = []
            if loops:
                regions[rid] = {"loops": loops, "inside": key,
                                "area": core.loops_area(loops)}
                rid += 1
            failed.add(key)       # never pick this circuit again
    finally:
        t.RollBack()
    return regions


# ------------------------------------------------------------------ clicks
def collect_clicks(pick, rooms, regions, taken, max_retries=2):
    """
    pick(prompt) -> (x, y) or None (Esc). Called BEFORE any transaction.
    Returns ({key: rid}, {key: reason}).
    """
    assign, reasons = {}, {}
    used = set(taken)
    n = len(rooms)
    for i, r in enumerate(rooms):
        label = u"%s %s" % (r["number"], r["name"])
        tries = 0
        while True:
            pt = pick(u"[%d/%d] Click inside the space for room %s  (Esc = skip)"
                      % (i + 1, n, label.strip()))
            if pt is None:
                reasons[r["key"]] = u"Skipped (Esc)."
                break
            rid = core.region_at(pt, regions, exclude=used)
            if rid is not None:
                assign[r["key"]] = rid
                used.add(rid)
                break
            tries += 1
            already = core.region_at(pt, regions) is not None
            if tries > max_retries:
                reasons[r["key"]] = (u"Clicked space already taken by another "
                                     u"restored room." if already else
                                     u"Clicked point is not an empty enclosed "
                                     u"space (existing room, or not closed).")
                break
    return assign, reasons


# ---------------------------------------------------------------- placement
if DB is not None:
    class _Quiet(DB.IFailuresPreprocessor):
        def PreprocessFailures(self, accessor):
            try:
                for f in accessor.GetFailureMessages():
                    if f.GetSeverity() == DB.FailureSeverity.Warning:
                        accessor.DeleteWarning(f)
            except Exception:
                pass
            return DB.FailureProcessingResult.Continue
else:                                                    # pragma: no cover
    _Quiet = None


def _find_circuit(doc, level, phase, region):
    topo = doc.get_PlanTopology(level, phase)
    for c in topo.Circuits:
        if c.IsRoomLocated:
            continue
        uv = c.GetPointInside()
        if core.point_in_loops((uv.U, uv.V), region["loops"]):
            return c
    return None


def place_rooms(doc, jobs, tag_view=None, tx_name=u"DLC Restore Rooms"):
    """
    jobs: [{'info': room_info, 'region': region}]
    One Transaction (single Ctrl+Z), each room isolated in a SubTransaction.
    Returns [(info, ok, message)].
    """
    results = []
    if not jobs:
        return results
    tag_level = None
    if tag_view is not None:
        try:
            tag_level = eid_int(tag_view.GenLevel.Id)
        except Exception:
            tag_view = None
    t = DB.Transaction(doc, tx_name)
    t.Start()
    try:
        fho = t.GetFailureHandlingOptions()
        fho.SetFailuresPreprocessor(_Quiet())
        t.SetFailureHandlingOptions(fho)
    except Exception:
        pass
    try:
        for job in jobs:
            info = job["info"]
            st = DB.SubTransaction(doc)
            st.Start()
            try:
                c = _find_circuit(doc, info["level"], info["phase"], job["region"])
                if c is None:
                    raise Exception(u"The space is no longer empty/enclosed.")
                doc.Create.NewRoom(info["room"], c)
                room = info["room"]
                if room.Location is None or room.Area <= 1e-6:
                    raise Exception(u"Room did not enclose (area 0).")
                if tag_view is not None and info["level_key"] == tag_level:
                    try:
                        pt = room.Location.Point
                        doc.Create.NewRoomTag(DB.LinkElementId(room.Id),
                                              DB.UV(pt.X, pt.Y), tag_view.Id)
                    except Exception:
                        pass
                st.Commit()
                results.append((info, True, u"Placed (%.1f m2)." %
                                (room.Area * 0.09290304)))
            except Exception as ex:
                st.RollBack()
                msg = getattr(ex, "Message", None) or core.to_text(ex)
                results.append((info, False, core.to_text(msg)))
        t.Commit()
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise
    return results


# ------------------------------------------------------ schedule highlight
def room_schedules(doc):
    """Real room schedules (no templates, key schedules, revision tables)."""
    rooms_cat = eid_int(DB.ElementId(DB.BuiltInCategory.OST_Rooms))
    out = []
    for v in DB.FilteredElementCollector(doc).OfClass(DB.ViewSchedule):
        try:
            if v.IsTemplate or v.IsTitleblockRevisionSchedule:
                continue
            d = v.Definition
            if d.IsKeySchedule or eid_int(d.CategoryId) != rooms_cat:
                continue
        except Exception:
            continue
        out.append(v)
    return out


def schedule_element_keys(doc, sched):
    """Element ids actually listed by the schedule (its own filters applied)."""
    keys = set()
    for e in DB.FilteredElementCollector(doc, sched.Id):
        try:
            keys.add(eid_int(e.Id))
        except Exception:
            pass
    return keys


def rank_schedules(doc, room_keys, active_view=None):
    """[(schedule, n_missing_shown)] best first: most coverage, then the
    active view, then name."""
    want = set(room_keys)
    act = eid_int(active_view.Id) if active_view is not None else None
    ranked = []
    for s in room_schedules(doc):
        n = len(schedule_element_keys(doc, s) & want)
        ranked.append((-n, 0 if eid_int(s.Id) == act else 1,
                       DB.Element.Name.GetValue(s), s, n))
    ranked.sort(key=lambda t: t[:3])
    return [(t[3], t[4]) for t in ranked]


def highlight_in_schedule(uidoc, sched, room_ids):
    """Open the schedule and select the rows (Revit highlights them).
    Must run outside a transaction."""
    if eid_int(uidoc.ActiveView.Id) != eid_int(sched.Id):
        uidoc.ActiveView = sched
    try:
        from System.Collections.Generic import List
        col = List[DB.ElementId](room_ids)
    except Exception:
        col = list(room_ids)
    uidoc.Selection.SetElementIds(col)
    return len(room_ids)

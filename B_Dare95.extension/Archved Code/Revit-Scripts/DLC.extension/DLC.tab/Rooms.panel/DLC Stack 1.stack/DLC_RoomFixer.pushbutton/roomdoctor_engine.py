# -*- coding: utf-8 -*-
"""DLC Room Doctor - states WHY each room is 'Not Enclosed', and proves it.

Scope: selected rooms / one level / whole model (asked at start).

For every unbounded room it collects evidence:
  * Redundant room (shares an enclosed space with another room)
  * Room point placed inside a wall or column
  * Room placed in open space (nothing bounds it in any direction)
  * Leak directions (rays from the room point that never hit a boundary)
  * Gaps in walls / curtain walls / separation lines / columns
  * Elements in the way that do NOT bound rooms: Room Bounding unchecked,
    too low / too high for the level Computation Height, wrong phase for
    the ROOM'S phase, secondary design option, link with Room Bounding off
  * Revit warnings on the room and on the elements involved
  * Closed worksets / unloaded links that hide boundaries

Then it PROVES causes with what-if tests: inside a transaction that is always
rolled back it adds temporary Room Separation Lines (across a gap, along an
ignored element, ...) and checks whether the room becomes enclosed.
Only NEW temporary lines are created - your walls, links and levels are never
edited, so nothing is borrowed from other users. Nothing is saved.

Results: output window (clickable IDs) + markers in each level's plan:
  green = confirmed fix, red = gap, orange = element that does not bound,
  magenta X = unbounded room.  Markers are one Undo step.
"""
__title__ = "Room\nDoctor"
__author__ = "DLC"

import math
import os
import sys
import time

try:
    _HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:                       # older pyRevit engines
    from pyrevit import script as _s
    _HERE = _s.get_script_path() or ""
    if _HERE.lower().endswith(".py"):
        _HERE = os.path.dirname(_HERE)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from pyrevit import revit, DB, forms, script   # noqa: E402
import roomgaps_core as core                     # noqa: E402
import roomdoctor_core as doctor                 # noqa: E402

# ==========================================================================
# SETTINGS - firm-level knobs. Lengths in millimetres unless noted.
# ==========================================================================
SETTINGS = {
    "version": "1.2.0",
    "join_tolerance_mm": 10.0,
    "max_gap_mm": 3000.0,
    "scan_band_mm": 3000.0,
    "separation_line_z_tol_mm": 300.0,
    # probing
    "ray_count": 16,
    "ray_reach_m": 100.0,         # "escapes" = no boundary within this
    "near_gaps": 5,               # also test the N nearest gaps
    "near_radius_m": 30.0,
    "max_candidates": 8,          # per room
    "bridge_max_mm": 15000.0,     # wide openings (missing bay/wall) up to this
    # model-level what-ifs (one test each, shared by all rooms)
    "comp_height_low_mm": 300.0,  # a level below this gets a height test
    "comp_height_test_mm": 1219.2,  # Revit's default room Computation Height
    "max_global_tests": 40,
    # Revit spill tracer for rooms still unexplained
    "spill_trace": True,
    "spill_margin_m": 10.0,
    # what-if confirmation
    "confirm": True,
    "ask_if_longer_than_s": 90,   # ask before long confirmation runs
    "reduce_combined": True,      # find the minimal set when 1 fix isn't enough
    "line_extend_mm": 30.0,       # temp lines overlap elements by this
    "test_box_mm": 600.0,         # self-test / last-resort box size
    # what counts as boundary
    "include_walls": True,
    "include_curtain_walls": True,
    "include_separation_lines": True,
    "include_columns": True,
    "include_links": True,
    "check_phase": True,
    "check_design_options": True,
    # markers
    "draw_markers": True,
    "marker_radius_mm": 250.0,
    "room_marker_mm": 600.0,
    "styles": {
        "gap": {"name": "DLC_RoomGap", "rgb": (255, 0, 0),
                "weight": 8, "pattern": "dash"},
        "cause": {"name": "DLC_RoomGap_NotBounding", "rgb": (255, 140, 0),
                  "weight": 8, "pattern": "dash"},
        "room": {"name": "DLC_RoomGap_Room", "rgb": (200, 0, 200),
                 "weight": 5, "pattern": None},
        "fix": {"name": "DLC_RoomGap_Fix", "rgb": (0, 170, 0),
                "weight": 10, "pattern": None},
        "spill": {"name": "DLC_RoomGap_Spill", "rgb": (0, 160, 255),
                  "weight": 6, "pattern": None},
    },
}

TITLE = "DLC Room Doctor"
FT_PER_MM = 1.0 / 304.8
BIP = DB.BuiltInParameter
OK_PHASE_STATUS = ("Existing", "New", "Temporary")
IGNORED_WARNINGS = ("not in a properly enclosed region",)

CONFIRMED = "CONFIRMED"     # proven by a what-if test
PROVEN = "PROVEN"           # proven by geometry / model data
LIKELY = "LIKELY"           # strong evidence, not confirmed
NEARBY = "NOT NEEDED"       # found nearby, but the room is fixed without it
INFO = "INFO"
STATUS_ORDER = {CONFIRMED: 0, PROVEN: 1, LIKELY: 2, INFO: 3, NEARBY: 4}


# ==========================================================================
# helpers
# ==========================================================================
def mm(v):
    return float(v) * FT_PER_MM


def to_mm(v):
    return float(v) * 304.8


def eid_int(eid):
    try:
        return int(eid.Value)
    except AttributeError:
        return int(eid.IntegerValue)


def elem_name(el):
    """Element name that works for types, links, rooms in IronPython 2/3."""
    if el is None:
        return "?"
    for get in (lambda e: DB.Element.Name.__get__(e),
                lambda e: DB.Element.Name.GetValue(e),
                lambda e: e.Name):
        try:
            n = get(el)
            if n:
                return n
        except Exception:
            pass
    for bip in ("SYMBOL_NAME_PARAM", "ALL_MODEL_TYPE_NAME"):
        try:
            b = getattr(DB.BuiltInParameter, bip, None)
            p = el.get_Parameter(b) if b is not None else None
            if p is not None and p.AsString():
                return p.AsString()
        except Exception:
            pass
    try:
        return "#%d" % eid_int(el.Id)
    except Exception:
        return "?"


def link_name(li, lt, ldoc):
    """Readable name of a linked model."""
    n = elem_name(lt)
    if n and not n.startswith("#") and n != "?":
        return n
    try:
        if ldoc is not None and ldoc.Title:
            return ldoc.Title
    except Exception:
        pass
    try:
        ref = DB.ExternalFileUtils.GetExternalFileReference(lt.Document, lt.Id)
        path = DB.ModelPathUtils.ConvertModelPathToUserVisiblePath(
            ref.GetAbsolutePath())
        if path:
            return path.replace("\\", "/").split("/")[-1]
    except Exception:
        pass
    n = elem_name(li)
    return n if n != "?" else "link #%d" % eid_int(lt.Id)


# --- wall centre line ------------------------------------------------------
# A wall's LocationCurve sits on its LOCATION LINE (centre, core centre,
# finish face ext/int, core face ext/int). Room geometry needs the true
# centre line, so walls placed by a face are shifted by up to half their
# thickness. Measure the shift from the real side faces; fall back to the
# compound-structure layers.
def _face_offset(w, refs, p, o):
    best = None
    for r in refs:
        try:
            f = w.GetGeometryObjectFromReference(r)
            res = f.Project(p) if f is not None else None
        except Exception:
            res = None
        if res is None:
            continue
        q = res.XYZPoint
        dx, dy = q.X - p.X, q.Y - p.Y
        horiz = (dx * dx + dy * dy) ** 0.5
        d = dx * o.X + dy * o.Y
        if best is None or horiz < best[0]:
            best = (horiz, d)
    return best[1] if best else None


def _centre_shift_faces(w, p, o):
    try:
        ext = list(DB.HostObjectUtils.GetSideFaces(w, DB.ShellLayerType.Exterior))
        inn = list(DB.HostObjectUtils.GetSideFaces(w, DB.ShellLayerType.Interior))
    except Exception:
        return None
    de = _face_offset(w, ext, p, o)
    di = _face_offset(w, inn, p, o)
    if de is None or di is None:
        return None
    try:
        width = float(w.Width)
    except Exception:
        width = 0.0
    if width > 0 and abs(abs(de - di) - width) > 0.2 * width + 0.003:
        return None
    return (de + di) / 2.0


def _centre_shift_layers(w, key):
    try:
        cs = w.WallType.GetCompoundStructure()
    except Exception:
        cs = None
    if cs is None:
        return 0.0
    try:
        widths = [float(l.Width) for l in cs.GetLayers()]
        total = sum(widths)
        first = cs.GetFirstCoreLayerIndex()
        last = cs.GetLastCoreLayerIndex()
    except Exception:
        return 0.0
    if first < 0 or last < first:
        first, last = 0, len(widths) - 1
    before = sum(widths[:first])
    core = sum(widths[first:last + 1])
    s = {0: total / 2.0, 1: before + core / 2.0, 2: 0.0, 3: total,
         4: before, 5: before + core}.get(key, total / 2.0)
    return s - total / 2.0


def wall_centre_points(w, loc):
    """Tessellated TRUE centre line of a wall (in its own document)."""
    crv = loc.Curve
    pts = list(crv.Tessellate())
    key = param_int(w, "WALL_KEY_REF_PARAM", "Location Line")
    if not key:
        return pts
    try:
        if w.WallType.Kind == DB.WallKind.Curtain:
            return pts
        o = w.Orientation
        mid = crv.Evaluate(0.5, True)
    except Exception:
        return pts
    off = _centre_shift_faces(w, mid, o)
    if off is None:
        off = _centre_shift_layers(w, key)
    if abs(off) < 1e-9:
        return pts
    c = getattr(crv, "Center", None)
    if c is not None:                                   # arc wall: radial
        mx, my = mid.X - c.X, mid.Y - c.Y
        sign = 1.0 if (mx * o.X + my * o.Y) >= 0 else -1.0
        out = []
        for p in pts:
            rx, ry = p.X - c.X, p.Y - c.Y
            n = (rx * rx + ry * ry) ** 0.5 or 1.0
            out.append(DB.XYZ(p.X + rx / n * off * sign,
                              p.Y + ry / n * off * sign, p.Z))
        return out
    return [DB.XYZ(p.X + o.X * off, p.Y + o.Y * off, p.Z) for p in pts]


def get_param(el, bip_name, fallback_name=None):
    p = None
    bip = getattr(BIP, bip_name, None) if bip_name else None
    if bip is not None:
        try:
            p = el.get_Parameter(bip)
        except Exception:
            p = None
    if p is None and fallback_name:
        try:
            p = el.LookupParameter(fallback_name)
        except Exception:
            p = None
    return p


def param_int(el, bip_name, fallback_name=None):
    p = get_param(el, bip_name, fallback_name)
    if p is None:
        return None
    try:
        if not p.HasValue:
            return None
        return p.AsInteger()
    except Exception:
        return None


def param_id(el, bip_name):
    p = get_param(el, bip_name)
    try:
        return p.AsElementId() if p else None
    except Exception:
        return None


def room_text(room):
    num = get_param(room, "ROOM_NUMBER")
    nam = get_param(room, "ROOM_NAME")
    num = (num.AsString() if num else "") or ""
    nam = (nam.AsString() if nam else "") or ""
    return ("%s %s" % (num, nam)).strip() or "(no number)"


def is_placed(room):
    loc = room.Location
    return loc is not None and isinstance(loc, DB.LocationPoint)


def is_unbounded(room):
    if not is_placed(room):
        return False
    try:
        return not room.Area > 1e-6
    except Exception:
        return True


def get_rooms(doc):
    return list(DB.FilteredElementCollector(doc)
                .OfCategory(DB.BuiltInCategory.OST_Rooms)
                .WhereElementIsNotElementType())


def get_levels(doc):
    lv = list(DB.FilteredElementCollector(doc).OfClass(DB.Level)
              .WhereElementIsNotElementType())
    lv.sort(key=lambda l: l.ProjectElevation)
    return lv


def is_usable_plan(v):
    try:
        return (v is not None and isinstance(v, DB.ViewPlan)
                and not v.IsTemplate
                and v.ViewType == DB.ViewType.FloorPlan
                and v.GenLevel is not None)
    except Exception:
        return False


def plan_for_level(doc, level, active):
    if is_usable_plan(active) and active.GenLevel.Id == level.Id:
        return active
    plans = [v for v in DB.FilteredElementCollector(doc).OfClass(DB.ViewPlan)
             if is_usable_plan(v) and v.GenLevel.Id == level.Id]
    plans.sort(key=elem_name)
    return plans[0] if plans else None


# ==========================================================================
# scope
# ==========================================================================
SCOPE_SEL = "Selected rooms"
SCOPE_LEVEL = "One level"
SCOPE_ALL = "Whole model"


def selected_room_ids(doc, uidoc):
    ids = set()
    try:
        sel = list(uidoc.Selection.GetElementIds())
    except Exception:
        sel = []
    for i in sel:
        el = doc.GetElement(i)
        if el is None:
            continue
        rid = getattr(el, "TaggedLocalRoomId", None)     # room tag
        if rid is not None:
            ids.add(eid_int(rid))
        else:
            ids.add(eid_int(i))
    return ids


def choose_rooms(doc, uidoc, all_rooms):
    """Return (rooms in scope, scope label) or (None, None) if cancelled."""
    room_ids = set(eid_int(r.Id) for r in all_rooms)
    sel = selected_room_ids(doc, uidoc) & room_ids
    options = [SCOPE_LEVEL, SCOPE_ALL]
    if sel:
        options.insert(0, "%s (%d)" % (SCOPE_SEL, len(sel)))
    else:
        options.append(SCOPE_SEL)
    choice = forms.CommandSwitchWindow.show(
        options, message="Diagnose which unbounded rooms?")
    if not choice:
        return None, None
    if choice.startswith(SCOPE_SEL):
        if not sel:
            forms.alert("Select the rooms (or their room tags) first, then "
                        "run again.", title=TITLE)
            return None, None
        return [r for r in all_rooms if eid_int(r.Id) in sel], choice
    if choice == SCOPE_ALL:
        return list(all_rooms), choice

    levels = get_levels(doc)
    count = {}
    for r in all_rooms:
        if is_unbounded(r):
            k = eid_int(r.LevelId)
            count[k] = count.get(k, 0) + 1
    labels, by_label, default = [], {}, None
    active = uidoc.ActiveView
    for lv in levels:
        n = count.get(eid_int(lv.Id), 0)
        lab = "%s   (%d unbounded room%s)" % (elem_name(lv), n,
                                               "" if n == 1 else "s")
        labels.append(lab)
        by_label[lab] = lv
        if is_usable_plan(active) and active.GenLevel.Id == lv.Id:
            default = lab
    if not labels:
        forms.alert("This model has no levels.", title=TITLE)
        return None, None
    if default is None:
        for lab in labels:
            if count.get(eid_int(by_label[lab].Id), 0):
                default = lab
                break
    pick = forms.ask_for_one_item(labels, default=default or labels[0],
                                  prompt="Level to diagnose:", title=TITLE)
    if not pick:
        return None, None
    lv = by_label[pick]
    return [r for r in all_rooms if r.LevelId == lv.Id], elem_name(lv)


# ==========================================================================
# collecting boundary elements (per level + room phase)
# ==========================================================================
class Ctx(object):
    def __init__(self, level, phase_id):
        self.level = level
        self.level_z = level.ProjectElevation
        ch = get_param(level, "LEVEL_ROOM_COMPUTATION_HEIGHT")
        comp = None
        try:
            comp = ch.AsDouble() if ch else None
        except Exception:
            comp = None
        self.comp_height = 4.0 if comp is None else comp
        self.cut_z = self.level_z + self.comp_height
        self.band_top = self.level_z + mm(SETTINGS["scan_band_mm"])
        self.sep_tol = mm(SETTINGS["separation_line_z_tol_mm"])
        self.phase_id = phase_id
        self.eps = mm(1.0)


def _pt(t, p):
    return t.OfPoint(p) if t is not None else p


def _xy(t, pts):
    out = []
    for p in pts:
        q = _pt(t, p)
        out.append((q.X, q.Y))
    return out


def _z_range(el, t):
    try:
        bb = el.get_BoundingBox(None)
    except Exception:
        bb = None
    if bb is None:
        return None
    a = _pt(t, bb.Min)
    b = _pt(t, bb.Max)
    return min(a.Z, b.Z), max(a.Z, b.Z), bb


def _on_level(zmin, zmax, ctx):
    return zmax > ctx.level_z + ctx.eps and zmin < ctx.band_top


def _height_reasons(zmin, zmax, ctx):
    r = []
    ch = to_mm(ctx.comp_height)
    if zmax < ctx.cut_z - ctx.eps:
        r.append("its top is below the level's room Computation Height "
                 "(%d mm above the level)" % ch)
    if zmin > ctx.cut_z + ctx.eps:
        r.append("its base is above the level's room Computation Height "
                 "(%d mm above the level) - e.g. a linked wall that starts on "
                 "a slab above the level" % ch)
    return r


def _phase_reasons(el, ctx, doc):
    if not SETTINGS["check_phase"] or ctx.phase_id is None:
        return []
    try:
        st = str(el.GetPhaseStatus(ctx.phase_id))
    except Exception:
        return []
    if st in OK_PHASE_STATUS:
        return []
    return ["it does not exist in the room's phase '%s' (status: %s)"
            % (elem_name(doc.GetElement(ctx.phase_id)), st)]


def _option_reasons(el):
    if not SETTINGS["check_design_options"]:
        return []
    try:
        opt = el.DesignOption
    except Exception:
        opt = None
    if opt is None:
        return []
    try:
        if opt.IsPrimary:
            return []
    except Exception:
        return []
    return ["it is in secondary design option '%s'" % elem_name(opt)]


def _is_curtain(wall):
    try:
        return wall.WallType.Kind == DB.WallKind.Curtain
    except Exception:
        return False


def collect_source(src, t, source, is_link, link_rb_on, ctx, host_doc,
                   bounding, non_bounding):
    base = []
    if is_link and not link_rb_on:
        base.append("linked model '%s' has Room Bounding OFF" % source)

    def ref(el):
        return (source, el.Id, is_link)

    def label(kind, el, extra=""):
        s = "%s %d" % (kind, eid_int(el.Id))
        if extra:
            s += " (%s)" % extra
        if is_link:
            s += " in link '%s'" % source
        return s

    def host_reasons(el):
        if is_link:
            return []
        return _phase_reasons(el, ctx, host_doc) + _option_reasons(el)

    def add(chain):
        (non_bounding if chain.reason else bounding).append(chain)

    if SETTINGS["include_walls"] or SETTINGS["include_curtain_walls"]:
        for w in (DB.FilteredElementCollector(src).OfClass(DB.Wall)
                  .WhereElementIsNotElementType()):
            curtain = _is_curtain(w)
            if curtain and not SETTINGS["include_curtain_walls"]:
                continue
            if not curtain and not SETTINGS["include_walls"]:
                continue
            loc = w.Location
            if not isinstance(loc, DB.LocationCurve):
                continue
            zr = _z_range(w, t)
            if zr is None or not _on_level(zr[0], zr[1], ctx):
                continue
            reasons = list(base)
            if param_int(w, "WALL_ATTR_ROOM_BOUNDING", "Room Bounding") == 0:
                reasons.append("Room Bounding is unchecked")
            reasons += _height_reasons(zr[0], zr[1], ctx)
            reasons += host_reasons(w)
            try:
                pts = wall_centre_points(w, loc)
                hw = float(w.Width) / 2.0
            except Exception:
                continue
            kind = core.KIND_CURTAIN if curtain else core.KIND_WALL
            add(core.Chain(_xy(t, pts), hw, kind, False, ref(w),
                           label(kind, w, elem_name(w.WallType)),
                           "; ".join(reasons) or None))

    if SETTINGS["include_separation_lines"]:
        for c in (DB.FilteredElementCollector(src)
                  .OfCategory(DB.BuiltInCategory.OST_RoomSeparationLines)
                  .WhereElementIsNotElementType()):
            crv = getattr(c, "GeometryCurve", None)
            if crv is None:
                continue
            try:
                raw = [_pt(t, p) for p in crv.Tessellate()]
            except Exception:
                continue
            if not raw or any(abs(p.Z - ctx.level_z) > ctx.sep_tol
                              for p in raw):
                continue
            reasons = list(base) + host_reasons(c)
            add(core.Chain([(p.X, p.Y) for p in raw], 0.0,
                           core.KIND_SEPARATION, False, ref(c),
                           label("Separation line", c),
                           "; ".join(reasons) or None))

    if SETTINGS["include_columns"]:
        for bic in (DB.BuiltInCategory.OST_Columns,
                    DB.BuiltInCategory.OST_StructuralColumns):
            for col in (DB.FilteredElementCollector(src).OfCategory(bic)
                        .WhereElementIsNotElementType()):
                zr = _z_range(col, t)
                if zr is None or not _on_level(zr[0], zr[1], ctx):
                    continue
                bb = zr[2]
                z = bb.Min.Z
                corners = [DB.XYZ(bb.Min.X, bb.Min.Y, z),
                           DB.XYZ(bb.Max.X, bb.Min.Y, z),
                           DB.XYZ(bb.Max.X, bb.Max.Y, z),
                           DB.XYZ(bb.Min.X, bb.Max.Y, z)]
                reasons = list(base)
                if param_int(col, "WALL_ATTR_ROOM_BOUNDING",
                             "Room Bounding") == 0:
                    reasons.append("Room Bounding is unchecked")
                reasons += _height_reasons(zr[0], zr[1], ctx)
                reasons += host_reasons(col)
                add(core.Chain(_xy(t, corners), 0.0, core.KIND_COLUMN, True,
                               ref(col), label("Column", col),
                               "; ".join(reasons) or None))


def collect_all(doc, ctx, link_notes):
    bounding, non_bounding = [], []
    collect_source(doc, None, "this model", False, True, ctx, doc,
                   bounding, non_bounding)
    if not SETTINGS["include_links"]:
        return bounding, non_bounding
    for li in DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkInstance):
        lt = doc.GetElement(li.GetTypeId())
        ldoc = li.GetLinkDocument()
        name = link_name(li, lt, ldoc)
        if ldoc is None:
            link_notes["Link '%s' is NOT LOADED - Revit cannot use its walls "
                       "for rooms and this tool cannot see them. Reload it "
                       "(Manage Links) if rooms rely on it." % name] = 1
            continue
        rb = param_int(lt, "WALL_ATTR_ROOM_BOUNDING", "Room Bounding")
        collect_source(ldoc, li.GetTotalTransform(), name, True, rb != 0,
                       ctx, doc, bounding, non_bounding)
    return bounding, non_bounding


# ==========================================================================
# model-wide checks
# ==========================================================================
def closed_worksets(doc):
    out = []
    try:
        if not doc.IsWorkshared:
            return out
        for ws in (DB.FilteredWorksetCollector(doc)
                   .OfKind(DB.WorksetKind.UserWorkset)):
            if not ws.IsOpen:
                out.append(ws.Name)
    except Exception:
        pass
    return out


def warnings_by_element(doc):
    m = {}
    try:
        warns = list(doc.GetWarnings())
    except Exception:
        return m
    for w in warns:
        try:
            txt = w.GetDescriptionText()
        except Exception:
            continue
        if any(s in txt.lower() for s in IGNORED_WARNINGS):
            continue
        ids = []
        try:
            ids += list(w.GetFailingElements())
            ids += list(w.GetAdditionalElements())
        except Exception:
            pass
        for i in ids:
            m.setdefault(eid_int(i), [])
            if txt not in m[eid_int(i)]:
                m[eid_int(i)].append(txt)
    return m


def warnings_list(doc):
    """[(text, [ElementId, ...])] for every model warning."""
    out = []
    try:
        warns = list(doc.GetWarnings())
    except Exception:
        return out
    for w in warns:
        try:
            txt = w.GetDescriptionText()
            ids = list(w.GetFailingElements()) + list(w.GetAdditionalElements())
        except Exception:
            continue
        out.append((txt, ids))
    return out


# ==========================================================================
# diagnosis model
# ==========================================================================
class Finding(object):
    def __init__(self, status, text, fix="", chains=None, fix_key=None):
        self.status = status
        self.text = text
        self.fix = fix
        self.chains = list(chains or [])
        self.fix_key = fix_key


class Case(object):
    def __init__(self, room, group):
        self.room = room
        self.group = group
        self.key = eid_int(room.Id)
        pt = room.Location.Point
        self.pt = (pt.X, pt.Y)
        self.text = room_text(room)
        self.findings = []
        self.cands = []          # fix keys
        self.confirmed = []      # fix keys that alone enclose the room
        self.combo = []          # minimal set that encloses together
        self.needs_box = False
        self.box_result = None
        self.shared = None       # (fix, other room text): would be Redundant
        self.link_fix = []        # (kept for compatibility)
        self.global_fix = []      # GlobalAction that encloses the room
        self.spill = None         # Revit spill-trace result for this room
        self.redundant_of = None  # enclosed room sharing this room's space
        self.inside = None        # Chain whose body contains the room point
        self.open_space = False   # nothing bounds it in any direction
        self.status_line = "Not Enclosed"

    def main(self):
        fs = sorted(self.findings, key=lambda f: STATUS_ORDER[f.status])
        for f in fs:
            if f.status in (CONFIRMED, PROVEN, LIKELY):
                return f
        return fs[0] if fs else None


class Group(object):
    def __init__(self, doc, level, phase_id, link_notes):
        self.level = level
        self.phase_id = phase_id
        self.ctx = Ctx(level, phase_id)
        self.bounding, self.nbs = collect_all(doc, self.ctx, link_notes)
        self.cases = []
        self.result = None


def nb_fix_text(chain):
    r = chain.reason or ""
    tips = []
    if "Room Bounding OFF" in r:
        tips.append("select the link > Edit Type > tick Room Bounding")
    if "unchecked" in r:
        tips.append("select it > Properties > tick Room Bounding")
    if "top is below" in r:
        tips.append("raise its top, or lower the level's Computation Height "
                    "(Area and Volume Computations / level properties)")
    if "base is above" in r:
        tips.append("lower its base, or raise the level's Computation Height")
    if "phase" in r:
        tips.append("fix its Phase Created/Demolished, or the room's phase")
    if "design option" in r:
        tips.append("make that option primary, or model the boundary in the "
                    "main model")
    tips.append("or draw a Room Separation Line along it")
    return "; ".join(tips) + "."


def gap_text(g):
    a = g.chain_a.label if g.chain_a else "?"
    b = g.chain_b.label if g.chain_b else "?"
    n = int(round(to_mm(g.length)))
    if getattr(g, "bridge", False):
        return ("Opening of %d mm between %s and %s - nothing fills it "
                "(missing wall / curtain-wall bay, or a wall in an unloaded "
                "link)" % (n, a, b))
    if g.kind == core.GAP_PAIR:
        return "Gap of %d mm between %s and %s" % (n, a, b)
    return "%s stops %d mm short of %s" % (a, n, b)


GAP_FIX = ("Extend / join the elements so they meet (Trim/Extend, or drag the "
           "wall end), or draw a Room Separation Line across the gap.")


def diagnose_group(doc, grp, enclosed_rooms, warnings):
    tol = mm(SETTINGS["join_tolerance_mm"])
    grp.result = core.analyse(grp.bounding, grp.nbs,
                              [(c, c.pt) for c in grp.cases],
                              tolerance=tol,
                              max_gap=mm(SETTINGS["max_gap_mm"]),
                              bridge_max=mm(SETTINGS["bridge_max_mm"]))
    gaps = grp.result.gaps
    reach = SETTINGS["ray_reach_m"] * 1000.0 * FT_PER_MM
    n_rays = int(SETTINGS["ray_count"])
    for c in grp.cases:
        room = c.room
        # 1. redundant ----------------------------------------------------
        probe_pt = DB.XYZ(c.pt[0], c.pt[1], grp.ctx.level_z + 1.0)
        host = None
        for er in enclosed_rooms:
            try:
                if er.IsPointInRoom(probe_pt):
                    host = er
                    break
            except Exception:
                pass
        if host is not None:
            c.redundant_of = host
            c.status_line = "Redundant"
            c.findings.append(Finding(
                PROVEN, "Redundant room: it sits inside the enclosed area of "
                "room %s, and one enclosed area can only hold one room."
                % room_text(host),
                "Delete one of the two rooms, or split the space with a "
                "Room Separation Line.", fix_key=("room", eid_int(host.Id))))
            continue
        # 2. point inside an element -------------------------------------
        inside = doctor.inside_body(c.pt, grp.bounding)
        if inside is not None:
            c.inside = inside
            c.findings.append(Finding(
                PROVEN, "The room's location point is inside %s, so it is "
                "not in any open space." % inside.label,
                "Move the room point into the open area (select room > drag "
                "the X, or Cut/Paste Aligned).", [inside]))
            continue
        # 3. rays ---------------------------------------------------------
        pr = doctor.probe(c.pt, grp.bounding, grp.nbs, gaps, n_rays, reach, tol)
        if len(pr.escapes) >= n_rays:
            c.open_space = not pr.ray_nbs
            if pr.ray_nbs:
                c.findings.append(Finding(
                    PROVEN, "Only elements that do NOT bound rooms surround "
                    "this room - no room-bounding element in any direction "
                    "within %d m." % SETTINGS["ray_reach_m"], ""))
            else:
                c.findings.append(Finding(
                    PROVEN, "Nothing bounds this point in any direction within "
                    "%d m: the room is placed in open space (outside the "
                    "building) or on the wrong level." % SETTINGS["ray_reach_m"],
                    "Check the room's Level; move or delete the room."))
        elif pr.escapes:
            c.findings.append(Finding(
                INFO, "The room leaks to the open toward: %s."
                % ", ".join(pr.escapes)))
        # 4. candidates -----------------------------------------------------
        cands = doctor.candidates(
            c.pt, pr, gaps, grp.nbs, int(SETTINGS["near_gaps"]),
            SETTINGS["near_radius_m"] * 1000.0 * FT_PER_MM,
            int(SETTINGS["max_candidates"]))
        # a wide opening filled only by non-bounding elements: point at
        # those elements (a line along them), not at "an empty opening"
        nb_index = dict((id(x), j) for j, x in enumerate(grp.nbs))
        fixed_cands = []
        for kind, i in cands:
            if kind == "gap" and getattr(gaps[i], "bridge", False) and \
                    gaps[i].causes:
                for x in gaps[i].causes:
                    k2 = ("nb", nb_index.get(id(x)))
                    if k2[1] is not None and k2 not in fixed_cands:
                        fixed_cands.append(k2)
            elif (kind, i) not in fixed_cands:
                fixed_cands.append((kind, i))
        cands = fixed_cands
        for kind, i in cands:
            if kind == "gap":
                g = gaps[i]
                ch = [x for x in (g.chain_a, g.chain_b) if x is not None]
                txt = gap_text(g)
                fix = GAP_FIX
                if g.causes:
                    txt += " (in the gap: %s)" % "; ".join(
                        "%s - %s" % (x.label, x.reason) for x in g.causes)
                    fix = ("The gap is filled by %s, which does not bound "
                           "rooms - %s" % (g.causes[0].label,
                                           nb_fix_text(g.causes[0])))
                    ch = ch + list(g.causes)
                c.findings.append(Finding(LIKELY, txt, fix, ch,
                                          ("gap", i)))
            else:
                nb = grp.nbs[i]
                c.findings.append(Finding(
                    LIKELY, "%s stands in front of the room's boundary but "
                    "does NOT bound rooms: %s." % (nb.label, nb.reason),
                    "Fix: " + nb_fix_text(nb), [nb], ("nb", i)))
            c.cands.append((kind, i))
        if not cands and not any(f.status == PROVEN for f in c.findings):
            c.needs_box = True
        # identical findings (same gap reached from both ends) -> once
        seen_txt, uniq = set(), []
        for f in c.findings:
            if f.text in seen_txt:
                if f.fix_key is not None and f.fix_key in c.cands:
                    c.cands.remove(f.fix_key)
                continue
            seen_txt.add(f.text)
            uniq.append(f)
        c.findings = uniq
        # 5. Revit warnings ------------------------------------------------
        seen = set()
        involved = [(room.Id, "this room")]
        for f in c.findings:
            for ch in f.chains:
                if not ch.ref[2]:
                    involved.append((ch.ref[1], ch.label))
        for eid, who in involved:
            for txt in warnings.get(eid_int(eid), []):
                if (who, txt) in seen:
                    continue
                seen.add((who, txt))
                c.findings.append(Finding(
                    INFO, "Revit warning on %s: \"%s\"" % (who, txt),
                    "Resolve it in Manage > Review Warnings."))


# ==========================================================================
# what-if engine (always rolled back)
# ==========================================================================
class WhatIf(object):
    def __init__(self, doc, active):
        self.doc = doc
        self.active = active
        self.tests = 0
        self.seconds = 0.0
        self.errors = []
        self.shared = {}
        self.first_phase = None
        try:
            for ph in doc.Phases:
                self.first_phase = ph
                break
        except Exception:
            pass
        self.vft = None
        for v in DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType):
            try:
                if v.ViewFamily == DB.ViewFamily.FloorPlan:
                    self.vft = v.Id
                    break
            except Exception:
                pass

    def test(self, level, segments, cases):
        """Add temp separation lines, regenerate, see which cases enclose.

        Returns {case.key: True/False} or None if the test could not run.
        """
        doc = self.doc
        t0 = time.time()
        self.shared = {}
        t = DB.Transaction(doc, "DLC Room Doctor what-if (rolled back)")
        result = None
        t.Start()
        try:
            view = plan_for_level(doc, level, self.active)
            if view is None and self.vft is not None:
                view = DB.ViewPlan.Create(doc, self.vft, level.Id)
            z = level.ProjectElevation
            plane = DB.Plane.CreateByNormalAndOrigin(DB.XYZ.BasisZ,
                                                     DB.XYZ(0, 0, z))
            sp = DB.SketchPlane.Create(doc, plane)
            arr = DB.CurveArray()
            short = doc.Application.ShortCurveTolerance
            for a, b in segments:
                if core.dist(a, b) <= short:
                    continue
                arr.Append(DB.Line.CreateBound(DB.XYZ(a[0], a[1], z),
                                               DB.XYZ(b[0], b[1], z)))
            if arr.Size > 0:
                made = doc.Create.NewRoomBoundaryLines(sp, arr, view)
                if self.first_phase is not None:
                    for crv in made:
                        p = get_param(crv, "PHASE_CREATED")
                        if p is not None:
                            try:
                                p.Set(self.first_phase.Id)
                            except Exception:
                                pass
                doc.Regenerate()
                result = {}
                closed = []
                for c in cases:
                    r = doc.GetElement(c.room.Id)
                    ok = r is not None and r.Area > 1e-6
                    result[c.key] = ok
                    if ok:
                        closed.append(r)
                self.shared = {}
                for c in cases:
                    if result[c.key]:
                        continue
                    pt = DB.XYZ(c.pt[0], c.pt[1], z + 1.0)
                    for r in closed:
                        try:
                            if r.IsPointInRoom(pt):
                                self.shared[c.key] = r
                                break
                        except Exception:
                            pass
        except Exception as ex:
            self.errors.append(str(ex))
            result = None
        finally:
            if t.HasStarted():
                t.RollBack()
            self.tests += 1
            self.seconds += time.time() - t0
        return result


def run_action(wi, apply, cases, capture=None):
    """Rolled-back test of a model change: apply(doc), regenerate, check.

    Returns {case.key: bool} (or None). capture(doc, z_cases) may read the
    regenerated model before the rollback; its result is wi.captured.
    """
    doc = wi.doc
    t0 = time.time()
    wi.captured = None
    t = DB.Transaction(doc, "DLC Room Doctor what-if (rolled back)")
    res = None
    t.Start()
    try:
        apply(doc)
        doc.Regenerate()
        res = {}
        for c in cases:
            r = doc.GetElement(c.room.Id)
            res[c.key] = r is not None and r.Area > 1e-6
        if capture is not None:
            wi.captured = capture(doc)
    except Exception as ex:
        wi.errors.append(str(ex))
        res = None
    finally:
        if t.HasStarted():
            t.RollBack()
        wi.tests += 1
        wi.seconds += time.time() - t0
    return res


class GlobalAction(object):
    """A model-level change, tested once for every room."""

    def __init__(self, key, text, fix, apply, owner_ids, done_text):
        self.key = key
        self.text = text
        self.fix = fix
        self.apply = apply
        self.owner_ids = list(owner_ids)
        self.done_text = done_text          # for Room Fixer's report


def _set_int(el, bip, v):
    get_param(el, bip, "Room Bounding").Set(v)


def _set_double(el, bip, v):
    get_param(el, bip).Set(v)


def _near_any(el, pts, radius):
    try:
        bb = el.get_BoundingBox(None)
    except Exception:
        bb = None
    if bb is not None:
        mn, mx = (bb.Min.X, bb.Min.Y), (bb.Max.X, bb.Max.Y)
    else:
        try:
            q = [(v.X, v.Y) for v in el.GeometryCurve.Tessellate()]
        except Exception:
            return False
        mn = (min(a for a, b in q), min(b for a, b in q))
        mx = (max(a for a, b in q), max(b for a, b in q))
    cx, cy = (mn[0] + mx[0]) / 2.0, (mn[1] + mx[1]) / 2.0
    half = core.dist(mn, mx) / 2.0
    for p in pts:
        if core.dist((cx, cy), p) <= radius + half:
            return True
    return False


def global_actions(doc, groups, warns):
    """Model-level what-ifs worth testing for these rooms."""
    acts, keys = [], set()

    def add(a):
        if a.key not in keys:
            keys.add(a.key)
            acts.append(a)

    offs = link_types_off(doc)
    for lt, name in offs:
        add(GlobalAction(
            ("link", name),
            "Linked model '%s' has Room Bounding OFF. Turning it ON encloses "
            "this room." % name,
            "Select the link > Edit Type > tick Room Bounding (Room Fixer "
            "does this, verified).",
            lambda d, lt=lt: _set_int(lt, "WALL_ATTR_ROOM_BOUNDING", 1),
            [lt.Id], "Turned ON Room Bounding for link '%s'" % name))
    seen = set()
    for g in groups:
        lv = g.level
        if eid_int(lv.Id) in seen:
            continue
        seen.add(eid_int(lv.Id))
        cur = to_mm(g.ctx.comp_height)
        if cur >= SETTINGS["comp_height_low_mm"]:
            continue
        new = SETTINGS["comp_height_test_mm"]
        lname = elem_name(lv)
        base_txt = ("Level '%s' computes rooms at %d mm above the level, so "
                    "walls that start even slightly above it (on a screed, "
                    "a raised floor, a linked slab) are ignored. Raising its "
                    "room Computation Height to %d mm" % (lname, cur, new))
        fix = ("Select level '%s' > Properties > Computation Height = %d mm "
               "(Room Fixer does this, verified)." % (lname, new))
        add(GlobalAction(
            ("comp", lname), base_txt + " encloses this room.", fix,
            lambda d, lv=lv, v=mm(new): _set_double(
                lv, "LEVEL_ROOM_COMPUTATION_HEIGHT", v),
            [lv.Id], "Raised Computation Height of level '%s' from %d to %d "
            "mm" % (lname, cur, new)))
        if offs:
            names = ", ".join(n for _, n in offs)

            def both(d, lv=lv, v=mm(new), offs=offs):
                _set_double(lv, "LEVEL_ROOM_COMPUTATION_HEIGHT", v)
                for lt, _ in offs:
                    _set_int(lt, "WALL_ATTR_ROOM_BOUNDING", 1)
            add(GlobalAction(
                ("comp+links", lname), base_txt + " AND turning ON Room "
                "Bounding for linked model(s) %s encloses this room "
                "(neither change alone is enough)." % names,
                fix + " Then tick Room Bounding on those links.", both,
                [lv.Id] + [lt.Id for lt, _ in offs],
                "Raised Computation Height of level '%s' to %d mm and turned "
                "ON Room Bounding for %s" % (lname, new, names)))

    pts = [c.pt for g in groups for c in g.cases]
    radius = SETTINGS["near_radius_m"] * 1000.0 * FT_PER_MM
    sep_ids = set(eid_int(e.Id) for e in DB.FilteredElementCollector(doc)
                  .OfCategory(DB.BuiltInCategory.OST_RoomSeparationLines)
                  .WhereElementIsNotElementType())
    for txt, ids in warns:
        if "overlap" not in txt.lower():
            continue
        for i in ids:
            el = doc.GetElement(i)
            if el is None or not _near_any(el, pts, radius):
                continue
            k = eid_int(i)
            if isinstance(el, DB.Wall):
                if param_int(el, "WALL_ATTR_ROOM_BOUNDING",
                             "Room Bounding") != 1:
                    continue
                lab = "Wall %d (%s)" % (k, elem_name(el.WallType))
                add(GlobalAction(
                    ("rboff", k),
                    "Revit warns: \"%s\" - it ignores one of the overlapping "
                    "elements. Unticking Room Bounding on %s lets the other "
                    "one bound the room, and the room encloses." % (txt, lab),
                    "Untick Room Bounding on %s, or delete the duplicate / "
                    "use Cut Geometry." % lab,
                    lambda d, el=el: _set_int(el, "WALL_ATTR_ROOM_BOUNDING", 0),
                    [i], "Unticked Room Bounding on %s (overlapping wall "
                    "Revit was ignoring)" % lab))
            elif k in sep_ids:
                add(GlobalAction(
                    ("delsep", k),
                    "Revit warns: \"%s\". Deleting Room Separation Line %d "
                    "(the wall already bounds the room) encloses the room."
                    % (txt, k),
                    "Delete Room Separation Line %d." % k,
                    lambda d, i=i: d.Delete(i),
                    [i], "Deleted Room Separation Line %d (it overlapped a "
                    "wall)" % k))
    return acts[:int(SETTINGS["max_global_tests"])]


def trace_spill(wi, grp, cases):
    """Revit-native flood: temporary boundary around the whole level, then
    read Revit's own outline of the space each room spills into."""
    xs, ys = [], []
    for ch in list(grp.bounding) + list(grp.nbs):
        if ch.bbox:
            xs += [ch.bbox[0], ch.bbox[2]]
            ys += [ch.bbox[1], ch.bbox[3]]
    for c in cases:
        xs.append(c.pt[0])
        ys.append(c.pt[1])
    m = SETTINGS["spill_margin_m"] * 1000.0 * FT_PER_MM
    x0, y0, x1, y1 = min(xs) - m, min(ys) - m, max(xs) + m, max(ys) + m
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    box = [(corners[i], corners[(i + 1) % 4]) for i in range(4)]
    z = grp.level.ProjectElevation
    eps = mm(300.0)      # the temporary boundary is 10 m clear of everything

    def on_box(pts):
        return all(abs(p[0] - x0) < eps or abs(p[0] - x1) < eps or
                   abs(p[1] - y0) < eps or abs(p[1] - y1) < eps for p in pts)

    def capture(doc):
        out = {}
        owners = []
        for c in cases:
            r = doc.GetElement(c.room.Id)
            if r is None or not r.Area > 1e-6:
                continue
            segs, touches = [], False
            try:
                loops = r.GetBoundarySegments(
                    DB.SpatialElementBoundaryOptions())
            except Exception:
                loops = []
            for loop in loops or []:
                for sg in loop:
                    try:
                        pts = [(q.X, q.Y) for q in sg.GetCurve().Tessellate()]
                    except Exception:
                        continue
                    if on_box(pts):
                        touches = True
                    else:
                        segs.append(pts)
            owners.append((c, r))
            out[c.key] = {"owner": c, "area": r.Area, "segs": segs,
                          "outside": touches, "members": [c]}
        for c in cases:
            if c.key in out:
                continue
            p = DB.XYZ(c.pt[0], c.pt[1], z + 1.0)
            for oc, r in owners:
                try:
                    if r.IsPointInRoom(p):
                        out[oc.key]["members"].append(c)
                        out[c.key] = out[oc.key]
                        break
                except Exception:
                    pass
        return out

    def apply(doc):
        _temp_lines(wi, grp.level, box)

    run_action(wi, apply, cases, capture)
    return wi.captured or {}


def _temp_lines(wi, level, segments):
    doc = wi.doc
    view = plan_for_level(doc, level, wi.active)
    if view is None and wi.vft is not None:
        view = DB.ViewPlan.Create(doc, wi.vft, level.Id)
    z = level.ProjectElevation
    sp = DB.SketchPlane.Create(doc, DB.Plane.CreateByNormalAndOrigin(
        DB.XYZ.BasisZ, DB.XYZ(0, 0, z)))
    arr = DB.CurveArray()
    for a, b in segments:
        arr.Append(DB.Line.CreateBound(DB.XYZ(a[0], a[1], z),
                                       DB.XYZ(b[0], b[1], z)))
    made = doc.Create.NewRoomBoundaryLines(sp, arr, view)
    if wi.first_phase is not None:
        for crv in made:
            p = get_param(crv, "PHASE_CREATED")
            if p is not None:
                try:
                    p.Set(wi.first_phase.Id)
                except Exception:
                    pass


def link_types_off(doc):
    """[(link type, name)] for LOADED links with Room Bounding OFF."""
    out, seen = [], set()
    for li in DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkInstance):
        lt = doc.GetElement(li.GetTypeId())
        if lt is None or eid_int(lt.Id) in seen:
            continue
        seen.add(eid_int(lt.Id))
        ldoc = li.GetLinkDocument()
        if ldoc is None:
            continue
        if param_int(lt, "WALL_ATTR_ROOM_BOUNDING", "Room Bounding") == 0:
            out.append((lt, link_name(li, lt, ldoc)))
    return out


def test_link(wi, lt, cases):
    """Rolled-back test: Room Bounding ON for one link type."""
    doc = wi.doc
    t0 = time.time()
    t = DB.Transaction(doc, "DLC Room Doctor link test (rolled back)")
    res = None
    t.Start()
    try:
        p = get_param(lt, "WALL_ATTR_ROOM_BOUNDING", "Room Bounding")
        p.Set(1)
        doc.Regenerate()
        res = {}
        for c in cases:
            r = doc.GetElement(c.room.Id)
            res[c.key] = r is not None and r.Area > 1e-6
    except Exception as ex:
        wi.errors.append(str(ex))
        res = None
    finally:
        if t.HasStarted():
            t.RollBack()
        wi.tests += 1
        wi.seconds += time.time() - t0
    return res


def fix_segments(grp, fix_key):
    ext = mm(SETTINGS["line_extend_mm"])
    kind, i = fix_key
    if kind == "gap":
        g = grp.result.gaps[i]
        return [doctor.extend(g.a, g.b, ext)]
    nb = grp.nbs[i]
    return [doctor.extend(a, b, ext) for a, b in nb.segments()]


def confirm(doc, groups, active, notes):
    cases = [c for g in groups for c in g.cases]
    work = [c for c in cases if c.cands or c.needs_box]
    if not work:
        return None
    wi = WhatIf(doc, active)

    # self-test: a closed box around a room must enclose it ----------------
    ok = False
    for c in work[:3]:
        res = wi.test(c.group.level,
                      doctor.box(c.pt, mm(SETTINGS["test_box_mm"])), [c])
        if res and res.get(c.key):
            ok = True
            break
    if not ok:
        notes.append("What-if confirmation is OFF for this run: Revit did not "
                     "re-enclose a room even inside a temporary closed box "
                     "(%s). Causes below are evidence-based (LIKELY), not "
                     "confirmed." % ("; ".join(wi.errors[:2]) or
                                     "rooms not recomputed in a rolled-back "
                                     "transaction"))
        return wi

    # model-level what-ifs: links, Computation Height, overlaps ---------
    for a in global_actions(doc, groups, warnings_list(doc)):
        res = run_action(wi, a.apply, work)
        if not res:
            continue
        for c in work:
            if res.get(c.key):
                c.global_fix.append(a)

    per = max(wi.seconds / max(wi.tests, 1), 0.05)
    plans = []
    for gi, grp in enumerate(groups):
        rc = dict((c.key, c.cands) for c in grp.cases
                  if c.cands and not c.global_fix)
        for fix, users in doctor.plan_single_tests(rc):
            plans.append((grp, fix, users))
    est = per * (len(plans) + len(work))
    if est > SETTINGS["ask_if_longer_than_s"]:
        if not forms.alert(
                "Confirming the causes needs about %d what-if tests "
                "(~%d min on this model). Nothing is saved.\n\nRun them now?"
                "\n(No = show likely causes only.)"
                % (len(plans) + len(work), max(1, int(est / 60.0))),
                title=TITLE, yes=True, no=True):
            notes.append("Confirmation skipped by user - causes are LIKELY, "
                         "not confirmed.")
            return wi

    by_key = dict((c.key, c) for c in cases)
    total = len(plans) + len(work)
    step = [0]
    cancelled = [False]

    with forms.ProgressBar(title="Room Doctor - testing causes "
                                 "({value}/{max_value})",
                           cancellable=True) as pb:
        def tick():
            step[0] += 1
            pb.update_progress(min(step[0], total), total)
            if pb.cancelled:
                cancelled[0] = True
            return not cancelled[0]

        # 1. each unique fix alone, checked on every room that lists it
        for grp, fix, users in plans:
            if not tick():
                break
            us = [by_key[k] for k in users]
            res = wi.test(grp.level, fix_segments(grp, fix), us)
            if not res:
                continue
            for c in us:
                if res.get(c.key):
                    c.confirmed.append(fix)
                elif c.key in wi.shared and not c.shared:
                    c.shared = (fix, room_text(wi.shared[c.key]))

        # 2. rooms not fixed by any single fix: all candidates together
        for c in work:
            if cancelled[0] or not tick():
                break
            grp = c.group
            if c.confirmed or c.shared or c.global_fix or not c.cands:
                continue
            if len(c.cands) < 2:
                c.needs_box = True
                continue

            def encloses(fixes, c=c, grp=grp):
                segs = []
                for f in fixes:
                    segs.extend(fix_segments(grp, f))
                res = wi.test(grp.level, segs, [c])
                return bool(res and res.get(c.key))

            if encloses(c.cands):
                if SETTINGS["reduce_combined"]:
                    c.combo = doctor.reduce_set(c.cands, encloses)
                else:
                    c.combo = list(c.cands)
            else:
                c.needs_box = True

        # 3. last resort: can this room enclose at all?
        for c in work:
            if cancelled[0]:
                break
            if not c.needs_box or c.confirmed or c.combo or c.shared or \
                    c.global_fix:
                continue
            res = wi.test(c.group.level,
                          doctor.box(c.pt, mm(SETTINGS["test_box_mm"])), [c])
            c.box_result = bool(res and res.get(c.key)) if res else None

    if cancelled[0]:
        notes.append("Confirmation was cancelled part-way - some causes are "
                     "LIKELY, not confirmed.")
        return wi

    # Revit spill tracer for rooms nothing above explained ---------------
    if SETTINGS["spill_trace"]:
        for grp in groups:
            left = [c for c in grp.cases
                    if not (c.confirmed or c.combo or c.shared or
                            c.global_fix or c.redundant_of is not None or
                            c.inside is not None)]
            if not left:
                continue
            res = trace_spill(wi, grp, grp.cases)
            for c in left:
                c.spill = res.get(c.key)
    return wi


def apply_confirmation(groups):
    for grp in groups:
        for c in grp.cases:
            fixed = set(c.confirmed) | set(c.combo)
            if c.shared:
                fixed.add(c.shared[0])
            for a in c.global_fix:
                c.findings.append(Finding(CONFIRMED, a.text, a.fix,
                                          fix_key=("global", a.key)))
            if c.global_fix:
                fixed.add(("global",))
            sp = c.spill
            if sp:
                others = [m.text for m in sp["members"] if m is not c]
                area = sp["area"] * 0.09290304          # ft2 -> m2
                txt = ("Revit's own view (temporary boundary drawn around the "
                       "whole level): this room floods into a space of "
                       "%d m2%s%s. That space is outlined in BLUE in the plan "
                       "- follow it from the room to where it leaves; that "
                       "opening is the leak." % (
                           area,
                           " that reaches OUTSIDE the building"
                           if sp["outside"] else "",
                           (" - shared with %d other unbounded room(s): %s, so "
                            "one leak opens all of them"
                            % (len(others), ", ".join(others[:6])))
                           if others else ""))
                c.findings.append(Finding(
                    PROVEN, txt, "Close the opening where the blue outline "
                    "leaves the rooms: usually a missing wall or curtain-wall "
                    "bay, a wall in an UNLOADED link, or a wall Revit ignores "
                    "(overlap warning).", fix_key=("spill", c.key)))
            for f in c.findings:
                if f.fix_key is None or f.fix_key[0] in ("room", "link",
                                                         "global", "spill"):
                    continue
                if f.fix_key in c.confirmed:
                    f.status = CONFIRMED
                    f.text += "  -> Closing this ALONE encloses the room."
                elif f.fix_key in c.combo:
                    f.status = CONFIRMED
                    f.text += ("  -> Needed: the room encloses only when "
                               "this AND the other %d confirmed item(s) are "
                               "fixed." % (len(c.combo) - 1))
                elif c.shared and f.fix_key == c.shared[0]:
                    f.status = CONFIRMED
                    f.text += ("  -> Closing this encloses the space, but room "
                               "%s is in the same space, so THIS room would "
                               "then be Redundant." % c.shared[1])
                    f.fix += (" Also delete one of the two rooms (this one or "
                              "%s)." % c.shared[1])
                elif fixed:
                    f.status = NEARBY
            if c.box_result is True and not c.spill:
                c.findings.append(Finding(
                    INFO, "The room DOES enclose inside a small temporary "
                    "box, so the room itself is fine - its open boundary is "
                    "further away than the search radius (%d m) or around "
                    "a corner." % SETTINGS["near_radius_m"],
                    "Run Room Gaps on this level to see every open end, or "
                    "raise near_radius_m / near_gaps in SETTINGS."))
            elif c.box_result is False:
                ph = elem_name(c.room.Document.GetElement(c.group.phase_id)) \
                    if c.group.phase_id is not None else "?"
                c.findings.append(Finding(
                    PROVEN, "The room does NOT enclose even inside a closed "
                    "box of separation lines drawn right around it. The "
                    "problem is the room itself, not its walls.",
                    "Check: room phase ('%s') matches the view you work in; "
                    "room is not in a design option; then delete the room and "
                    "place it again." % ph))


# ==========================================================================
# drawing (markers)
# ==========================================================================
def _find_dash_pattern(doc, word):
    best = None
    for lp in DB.FilteredElementCollector(doc).OfClass(DB.LinePatternElement):
        n = elem_name(lp)
        if word in n.lower() and (best is None or len(n) < len(best[0])):
            best = (n, lp.Id)
    return best[1] if best else None


def ensure_style(doc, spec):
    cats = doc.Settings.Categories
    lines = cats.get_Item(DB.BuiltInCategory.OST_Lines)
    sub = None
    for sc in lines.SubCategories:
        if sc.Name == spec["name"]:
            sub = sc
            break
    if sub is None:
        sub = cats.NewSubcategory(lines, spec["name"])
        r, g, b = spec["rgb"]
        sub.LineColor = DB.Color(r, g, b)
        try:
            sub.SetLineWeight(spec["weight"], DB.GraphicsStyleType.Projection)
        except Exception:
            pass
        if spec.get("pattern"):
            pid = _find_dash_pattern(doc, spec["pattern"])
            if pid is not None:
                try:
                    sub.SetLinePatternId(pid, DB.GraphicsStyleType.Projection)
                except Exception:
                    pass
    return sub.GetGraphicsStyle(DB.GraphicsStyleType.Projection)


def clear_markers(doc, view):
    names = set(s["name"] for s in SETTINGS["styles"].values())
    ids = []
    for ce in DB.FilteredElementCollector(doc, view.Id).OfClass(DB.CurveElement):
        try:
            ls = ce.LineStyle
            if ls is not None and elem_name(ls) in names:
                ids.append(ce.Id)
        except Exception:
            pass
    n = 0
    for i in ids:
        try:
            doc.Delete(i)
            n += 1
        except Exception:
            pass
    return n


class Painter(object):
    def __init__(self, doc, view, z):
        self.doc, self.view, self.z = doc, view, z
        self.ok = 0
        self.failed = 0
        try:
            self.short = doc.Application.ShortCurveTolerance
        except Exception:
            self.short = 0.003

    def _xyz(self, p):
        return DB.XYZ(p[0], p[1], self.z)

    def curve(self, crv, style):
        try:
            dc = self.doc.Create.NewDetailCurve(self.view, crv)
            dc.LineStyle = style
            self.ok += 1
        except Exception:
            self.failed += 1

    def line(self, a, b, style):
        if core.dist(a, b) <= self.short:
            return
        try:
            crv = DB.Line.CreateBound(self._xyz(a), self._xyz(b))
        except Exception:
            self.failed += 1
            return
        self.curve(crv, style)

    def circle(self, c, r, style):
        for s, e in ((0.0, math.pi), (math.pi, 2.0 * math.pi)):
            try:
                arc = DB.Arc.Create(self._xyz(c), r, s, e,
                                    DB.XYZ.BasisX, DB.XYZ.BasisY)
            except Exception:
                self.failed += 1
                continue
            self.curve(arc, style)

    def cross(self, c, size, style):
        h = size / 2.0
        self.line((c[0] - h, c[1] - h), (c[0] + h, c[1] + h), style)
        self.line((c[0] - h, c[1] + h), (c[0] + h, c[1] - h), style)


def draw_markers(doc, groups, active, notes):
    by_level = {}
    for g in groups:
        by_level.setdefault(eid_int(g.level.Id), []).append(g)
    views = {}
    t = DB.Transaction(doc, "DLC Room Doctor markers")
    t.Start()
    try:
        styles = dict((k, ensure_style(doc, v))
                      for k, v in SETTINGS["styles"].items())
        r = mm(SETTINGS["marker_radius_mm"])
        failed = 0
        for lid, grps in by_level.items():
            level = grps[0].level
            view = plan_for_level(doc, level, active)
            if view is None:
                notes.append("No floor plan for level '%s' - markers not "
                              "drawn there (the report is still complete)."
                              % elem_name(level))
                continue
            views[lid] = view
            clear_markers(doc, view)
            p = Painter(doc, view, level.ProjectElevation)
            done = set()
            for grp in grps:
                for c in grp.cases:
                    p.cross(c.pt, mm(SETTINGS["room_marker_mm"]), styles["room"])
                    for f in c.findings:
                        if f.fix_key is None or f.fix_key[0] in (
                                "room", "link", "global", "spill"):
                            continue
                        if f.status == NEARBY:
                            continue
                        key = (id(grp), f.fix_key, f.status)
                        if key in done:
                            continue
                        done.add(key)
                        kind, i = f.fix_key
                        if kind == "gap":
                            g = grp.result.gaps[i]
                            p.circle(g.a, r, styles["gap"])
                            p.line(g.a, g.b, styles["gap"])
                        else:
                            nb = grp.nbs[i]
                            for a, b in nb.segments():
                                p.line(a, b, styles["cause"])
                        if f.status == CONFIRMED:
                            for a, b in fix_segments(grp, f.fix_key):
                                p.line(a, b, styles["fix"])
            drawn = set()
            for grp in grps:
                for c in grp.cases:
                    sp = c.spill
                    if not sp or id(sp) in drawn:
                        continue
                    drawn.add(id(sp))
                    for pts in sp["segs"]:
                        for i in range(len(pts) - 1):
                            p.line(pts[i], pts[i + 1], styles["spill"])
            failed += p.failed
        t.Commit()
        if failed:
            notes.append("%d marker(s) could not be drawn." % failed)
    except Exception as ex:
        if t.HasStarted():
            t.RollBack()
        notes.append("Markers could not be drawn (%s) - the report below is "
                     "still valid." % ex)
        return {}
    return views


# ==========================================================================
# report
# ==========================================================================
def link_el(output, chain):
    source, eid, is_link = chain.ref
    if is_link:
        return chain.label
    try:
        return "%s %s" % (output.linkify(eid), chain.label)
    except Exception:
        return chain.label


def report(output, scope, groups, unplaced, notes, wi, elapsed):
    cases = [c for g in groups for c in g.cases]
    output.print_md("# %s - %s" % (TITLE, scope))
    output.print_md("**%d unbounded room(s)** diagnosed. Status: CONFIRMED = "
                    "proven by a rolled-back test, PROVEN = proven by model "
                    "data, LIKELY = strong evidence. Plan markers: green = "
                    "confirmed fix, red = gap, orange = element that does not "
                    "bound, magenta X = room, blue = Revit's outline of the "
                    "space a room leaks into.  (v%s, %.0f s)"
                    % (len(cases), SETTINGS["version"], elapsed))
    for n in notes:
        output.print_md("- **Note:** %s" % n)
    if unplaced:
        output.print_md("- %d unplaced room(s) in scope were skipped (no "
                        "location - place or delete them)." % unplaced)

    rows = []
    for c in cases:
        m = c.main()
        try:
            rid = output.linkify(c.room.Id)
        except Exception:
            rid = str(c.key)
        rows.append([rid, c.text, elem_name(c.group.level),
                     m.status if m else "-",
                     m.text if m else "No cause found - see details.",
                     m.fix if m else ""])
    rows.sort(key=lambda r: (STATUS_ORDER.get(r[3], 9), r[2], r[1]))
    output.print_table(rows, columns=["Room", "Number / Name", "Level",
                                      "Status", "Main cause", "How to fix"],
                       title="Summary")

    output.print_md("## Details")
    for c in cases:
        try:
            rid = output.linkify(c.room.Id)
        except Exception:
            rid = str(c.key)
        output.print_md("### %s %s - %s (%s)"
                        % (rid, c.text, c.status_line, elem_name(c.group.level)))
        fs = sorted(c.findings, key=lambda f: STATUS_ORDER[f.status])
        if not fs:
            output.print_md("- No cause found within the search limits.")
        for f in fs:
            els = ", ".join(link_el(output, ch) for ch in f.chains)
            line = "- **[%s]** %s" % (f.status, f.text)
            if els:
                line += "<br>Elements: %s" % els
            if f.fix and f.status != NEARBY:
                line += "<br>*Fix:* %s" % f.fix
            output.print_md(line)
    if wi is not None:
        output.print_md("_%d what-if test(s) run and rolled back in %.0f s. "
                        "Nothing was saved to the model._"
                        % (wi.tests, wi.seconds))


# ==========================================================================
# main
# ==========================================================================
def main():
    doc = revit.doc
    uidoc = revit.uidoc
    if doc.IsFamilyDocument:
        forms.alert("Open a project model, not a family.", title=TITLE)
        return
    all_rooms = get_rooms(doc)
    if not all_rooms:
        forms.alert("This model has no rooms.", title=TITLE)
        return
    rooms, scope = choose_rooms(doc, uidoc, all_rooms)
    if rooms is None:
        return
    t0 = time.time()
    unbounded = [r for r in rooms if is_unbounded(r)]
    unplaced = len([r for r in rooms if not is_placed(r)])
    if not unbounded:
        forms.alert("No unbounded rooms in '%s' - every placed room is "
                    "enclosed.%s" % (scope, "\n\n%d unplaced room(s) were "
                                     "skipped." % unplaced if unplaced else ""),
                    title=TITLE)
        return

    notes = []
    cw = closed_worksets(doc)
    if cw:
        notes.append("Closed worksets: %s. Elements on closed worksets are "
                     "invisible to this tool, so results may show false gaps. "
                     "Open all worksets for an exact diagnosis." % ", ".join(cw))
    link_notes = {}
    warnings = warnings_by_element(doc)

    # group unbounded rooms by level + phase (bounding depends on both)
    groups, by_key = [], {}
    for r in unbounded:
        lv = doc.GetElement(r.LevelId)
        if lv is None:
            continue
        ph = param_id(r, "ROOM_PHASE")
        k = (eid_int(lv.Id), eid_int(ph) if ph is not None else -1)
        if k not in by_key:
            by_key[k] = Group(doc, lv, ph, link_notes)
            groups.append(by_key[k])
        by_key[k].cases.append(Case(r, by_key[k]))
    notes.extend(sorted(link_notes.keys()))

    for grp in groups:
        enclosed = [r for r in all_rooms
                    if r.LevelId == grp.level.Id and is_placed(r)
                    and not is_unbounded(r)
                    and (grp.phase_id is None or
                         param_id(r, "ROOM_PHASE") == grp.phase_id)]
        diagnose_group(doc, grp, enclosed, warnings)

    wi = None
    if SETTINGS["confirm"]:
        if getattr(doc, "IsReadOnly", False):
            notes.append("Model is read-only - causes are not confirmed.")
        else:
            wi = confirm(doc, groups, uidoc.ActiveView, notes)
            apply_confirmation(groups)

    views = {}
    if SETTINGS["draw_markers"]:
        views = draw_markers(doc, groups, uidoc.ActiveView, notes)

    output = script.get_output()
    try:
        output.set_title(TITLE)
    except Exception:
        pass
    report(output, scope, groups, unplaced, notes, wi, time.time() - t0)

    if len(views) == 1:
        v = list(views.values())[0]
        if uidoc.ActiveView.Id != v.Id:
            try:
                uidoc.ActiveView = v
            except Exception:
                pass


if __name__ == "__main__":
    main()

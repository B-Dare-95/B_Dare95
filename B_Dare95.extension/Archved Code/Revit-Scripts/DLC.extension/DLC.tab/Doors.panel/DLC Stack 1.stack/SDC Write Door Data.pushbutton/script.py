# -*- coding: utf-8 -*-
"""SDC_DoorRoomTagging  -  Door <-> Room <-> Fire <-> Schedule tool (pyRevit).

One dialog drives the whole workflow:
  * Resolve the room each door serves (host model, one link, or all links).
  * Write room data + composite door number + computed fire rating onto doors.
  * Ensure all firm door parameters exist (created in the firm main SP file).
  * Optionally build/refresh the "DOOR SCHEDULE".
  * Optionally tag doors (missing only, or all/replace) in chosen views.
  * Export an .xlsx report (DOORS sheet + QA sheet).

See SETTINGS for every tuneable value. IronPython 2.7 / pyRevit, stdlib only.
"""

import os
import re
import math
import datetime
import zipfile

from System.Collections.Generic import List

from pyrevit import revit, DB, forms, script

doc = revit.doc
uidoc = revit.uidoc
app = doc.Application
output = script.get_output()

MM_TO_FT = 1.0 / 304.8
FT_TO_MM = 304.8
TITLE = "SDC Door Room + Fire Tagging"

# ---------------------------------------------------------------------------
# SETTINGS
# ---------------------------------------------------------------------------
SETTINGS = {
    "MAIN_SP_FILE_PATH": "",
    "SP_GROUP": "SDC_DoorRoom",

    # Room source parameters (read from the resolved room, host or link).
    "ROOM_BUILDING_CODE": "SDC_G_BUILDING CODE",
    "ROOM_LEVEL_CODE": "SDC_G_LEVEL CODE",

    # Door target parameters (written by the tool).
    "DOOR_NUMBER_PARAM": "SDC_Door_Number",
    "DOOR_BUILDING_CODE_PARAM": "SDC_G_BUILDING CODE",
    "DOOR_LEVEL_CODE_PARAM": "SDC_G_LEVEL CODE",
    "DOOR_ROOM_NUMBER_PARAM": "Room_Number",
    "DOOR_ROOM_NAME_PARAM": "Room_Name",
    "DOOR_FIRE_PARAM": "SDC_Fire_Rating",

    # The door's type identifier shown in the DOOR TYPE column / report.
    # "Type Mark" (default) or "Mark".
    "DOOR_TYPE_ID_PARAM": "Type Mark",

    # New manually-filled shared parameters (created empty, bound to Doors).
    "MANUAL_TEXT_PARAMS": ["SDC_FRAME", "SDC_PANEL", "SDC_SADDLE", "SDC_HARDWARE"],
    "MANUAL_INT_PARAMS": ["SDC_LEAVES"],

    "SERIAL_SEPARATOR": ".",

    # When a room has more than one door, append a/b/c... to the door number.
    # Order: "clockwise" (plan reading order around the room), "mark" (by the
    # door's Type Mark), "xy" (left-to-right then top-to-bottom), "elementid"
    # (arbitrary but perfectly stable across runs).
    "SUFFIX_MULTI_DOORS": True,
    "SUFFIX_ORDER": "clockwise",

    # Fire rating.
    "WALL_FIRE_PARAM": "Fire Rating",
    "FIRE_FACTOR": 0.75,
    "FIRE_OUTPUT": "{value} min",
    "FIRE_NONE_TEXT": "NON-FIRE RATED",
    "FIRE_BARE_NUMBER_IS": "min",

    # Geometric fallback.
    "GEOM_MARGIN_MM": 300.0,
    "GEOM_Z_MARGIN_MM": 1200.0,
    "GEOM_TWOROOM_TIEBREAK": "smaller",

    # Schedule.
    "SCHEDULE_NAME": "DOOR SCHEDULE",

    # Output.
    "CSV_DIR": "",

    "PARAM_UI_GROUP": DB.GroupTypeId.IdentityData,
    "EMPTY_VALUE": "",
}

# Report / schedule / xlsx column plan: (Excel header, revit param for schedule)
COLUMN_PLAN = [
    ("BUILDING", "SDC_G_BUILDING CODE"),
    ("LEVEL", "SDC_G_LEVEL CODE"),
    ("DOOR TYPE", SETTINGS["DOOR_TYPE_ID_PARAM"]),
    ("DOOR NUMBER", "SDC_Door_Number"),
    ("ROOM NAME", "Room_Name"),
    ("WIDTH", "Width"),
    ("HEIGHT", "Height"),
    ("ROUGH WIDTH", "Rough Width"),
    ("ROUGH HEIGHT", "Rough Height"),
    ("NUMBER OF LEAVES", "SDC_LEAVES"),
    ("FIRE RATING", "SDC_Fire_Rating"),
    ("FRAME TYPE", "SDC_FRAME"),
    ("PANEL MATERIAL", "SDC_PANEL"),
    ("SADDLE TYPE", "SDC_SADDLE"),
    ("HARDWARE SET", "SDC_HARDWARE"),
    ("COMMENTS", "Comments"),
]

MODE_TO_FROM = "To Room (fallback From)"
MODE_FROM_TO = "From Room (fallback To)"
MODE_TO_ONLY = "To Room only"
MODE_FROM_ONLY = "From Room only"
_MODES = [MODE_TO_FROM, MODE_FROM_TO, MODE_TO_ONLY, MODE_FROM_ONLY]

SCOPE_MODEL = "Whole model"
SCOPE_VIEW = "Active view"
SCOPE_SELECTION = "Current selection"

SRC_HOST = "host"
SRC_LINK = "link"
SRC_ALL_LINKS = "all_links"
SRC_HOST_AND_LINKS = "host_and_links"

TAG_MISSING = "missing"
TAG_ALL = "all"

VIEWS_ACTIVE = "Active view"
VIEWS_ALL_PLANS = "All plan views"
VIEWS_SELECT = "Selected views..."

DOOR_CAT = doc.Settings.Categories.get_Item(DB.BuiltInCategory.OST_Doors)
DOOR_CAT_ID = DOOR_CAT.Id.IntegerValue

# Runtime options set by the UI.
OPT = {"do_fire": True, "geom_fallback": True, "export_csv": True}


# ---------------------------------------------------------------------------
# Parameter helpers
# ---------------------------------------------------------------------------
def param_text(elem, name):
    if elem is None:
        return None
    p = elem.LookupParameter(name)
    if p is None:
        return None
    try:
        v = p.AsString()
        if v is not None and v != "":
            return v
    except Exception:
        pass
    try:
        v2 = p.AsValueString()
        if v2:
            return v2
    except Exception:
        pass
    return None


def len_mm(elem, name):
    if elem is None:
        return None
    p = elem.LookupParameter(name)
    if p is None:
        return None
    try:
        if p.StorageType == DB.StorageType.Double:
            return int(round(p.AsDouble() * FT_TO_MM))
    except Exception:
        pass
    return None


def int_val(elem, name):
    if elem is None:
        return None
    p = elem.LookupParameter(name)
    if p is None:
        return None
    try:
        if p.StorageType == DB.StorageType.Integer:
            return p.AsInteger()
    except Exception:
        pass
    return param_text(elem, name)


# ---------------------------------------------------------------------------
# Shared parameters -> firm main file
# ---------------------------------------------------------------------------
def _firm_sp_path():
    p = SETTINGS["MAIN_SP_FILE_PATH"].strip()
    if not p:
        p = app.SharedParametersFilename or ""
    return p


def _binding_and_def(name):
    it = doc.ParameterBindings.ForwardIterator()
    it.Reset()
    while it.MoveNext():
        d = it.Key
        if d is not None and d.Name == name:
            return d, it.Current
    return None, None


def _has_doors(cat_set):
    for c in cat_set:
        if c.Id.IntegerValue == DOOR_CAT_ID:
            return True
    return False


def _is_bound_to_doors(name):
    d, b = _binding_and_def(name)
    if b is None:
        return False
    return _has_doors(b.Categories)


def _get_or_create_group(spf):
    for g in spf.Groups:
        if g.Name == SETTINGS["SP_GROUP"]:
            return g
    return spf.Groups.Create(SETTINGS["SP_GROUP"])


def _file_defs_by_name(spf):
    result = {}
    for g in spf.Groups:
        for d in g.Definitions:
            result[d.Name] = d
    return result


def _spec(kind):
    return DB.SpecTypeId.Int.Integer if kind == "int" else DB.SpecTypeId.String.Text


def ensure_door_params():
    """Bind every door parameter, creating new ones in the firm SP file.
    Returns (ok, message, sp_path, notes)."""
    notes = []
    specs = [
        (SETTINGS["DOOR_NUMBER_PARAM"], False, "text"),
        (SETTINGS["DOOR_ROOM_NUMBER_PARAM"], False, "text"),
        (SETTINGS["DOOR_ROOM_NAME_PARAM"], False, "text"),
        (SETTINGS["DOOR_FIRE_PARAM"], False, "text"),
    ]
    for n in SETTINGS["MANUAL_INT_PARAMS"]:
        specs.append((n, False, "int"))
    for n in SETTINGS["MANUAL_TEXT_PARAMS"]:
        specs.append((n, False, "text"))
    specs.append((SETTINGS["DOOR_BUILDING_CODE_PARAM"], True, "text"))
    specs.append((SETTINGS["DOOR_LEVEL_CODE_PARAM"], True, "text"))

    if all(_is_bound_to_doors(n) for (n, _m, _k) in specs):
        return True, "All door parameters already present.", _firm_sp_path(), notes

    sp_path = _firm_sp_path()
    if not sp_path or not os.path.isfile(sp_path):
        return (False, "Firm shared-parameter file not found. Set MAIN_SP_FILE_"
                "PATH or point Revit at it. Looked for: '{0}'".format(sp_path),
                sp_path, notes)

    original = app.SharedParametersFilename
    app.SharedParametersFilename = sp_path
    try:
        spf = app.OpenSharedParameterFile()
        if spf is None:
            return False, "Could not open the shared-parameter file.", sp_path, notes
        defs_by_name = _file_defs_by_name(spf)
        group = None

        t = DB.Transaction(doc, "SDC - Bind door parameters")
        t.Start()
        try:
            for (name, must_exist, kind) in specs:
                if _is_bound_to_doors(name):
                    continue
                d_internal, b_existing = _binding_and_def(name)
                if b_existing is not None:
                    cats = b_existing.Categories
                    if not _has_doors(cats):
                        cats.Insert(DOOR_CAT)
                        doc.ParameterBindings.ReInsert(
                            d_internal, b_existing, SETTINGS["PARAM_UI_GROUP"])
                    continue
                defn = defs_by_name.get(name)
                if defn is None:
                    if must_exist:
                        notes.append("'{0}' not in the SP file; not bound to "
                                     "doors.".format(name))
                        continue
                    if group is None:
                        group = _get_or_create_group(spf)
                    opt = DB.ExternalDefinitionCreationOptions(name, _spec(kind))
                    defn = group.Definitions.Create(opt)
                    defs_by_name[name] = defn
                cats = app.Create.NewCategorySet()
                cats.Insert(DOOR_CAT)
                doc.ParameterBindings.Insert(
                    defn, app.Create.NewInstanceBinding(cats),
                    SETTINGS["PARAM_UI_GROUP"])
            t.Commit()
        except Exception as ex:
            t.RollBack()
            return False, "Binding failed: {0}".format(ex), sp_path, notes
    finally:
        app.SharedParametersFilename = original
    return True, "Door parameters ensured.", sp_path, notes


# ---------------------------------------------------------------------------
# Phases + native From/To room (host only)
# ---------------------------------------------------------------------------
def _last_phase(document):
    last = None
    for p in document.Phases:
        last = p
    return last


def door_phase(door):
    try:
        cp = door.CreatedPhaseId
        if cp is not None and cp != DB.ElementId.InvalidElementId:
            ph = doc.GetElement(cp)
            if ph is not None:
                return ph
    except Exception:
        pass
    return _last_phase(doc)


def _phases_in_priority(door):
    ordered = []
    seen = set()
    ph = door_phase(door)
    if ph is not None:
        ordered.append(ph)
        seen.add(ph.Id.IntegerValue)
    for p in doc.Phases:
        if p.Id.IntegerValue not in seen:
            ordered.append(p)
            seen.add(p.Id.IntegerValue)
    ordered.reverse()
    return ordered


def native_rooms(door):
    for ph in _phases_in_priority(door):
        fr = tr = None
        try:
            fr = door.get_FromRoom(ph)
        except Exception:
            fr = None
        try:
            tr = door.get_ToRoom(ph)
        except Exception:
            tr = None
        if fr is not None or tr is not None:
            return fr, tr, ph
    return None, None, None


# ---------------------------------------------------------------------------
# Geometry helpers (host + link)
# ---------------------------------------------------------------------------
def _door_geometry(door):
    loc = door.Location
    if not isinstance(loc, DB.LocationPoint):
        return None, None, None
    p = loc.Point
    try:
        facing = door.FacingOrientation
    except Exception:
        facing = None
    if facing is None or facing.GetLength() < 1e-9:
        return None, None, None
    facing = facing.Normalize()
    margin = SETTINGS["GEOM_MARGIN_MM"] * MM_TO_FT
    off = margin
    try:
        host = door.Host
        if isinstance(host, DB.Wall):
            off = host.Width / 2.0 + margin
    except Exception:
        pass
    base = DB.XYZ(p.X, p.Y, p.Z + SETTINGS["GEOM_Z_MARGIN_MM"] * MM_TO_FT)
    return base.Add(facing.Multiply(off)), base.Subtract(facing.Multiply(off)), facing


def _room_at(document, pt, phase):
    try:
        return document.GetRoomAtPoint(pt, phase)
    except Exception:
        try:
            return document.GetRoomAtPoint(pt)
        except Exception:
            return None


def geometric_rooms_host(door):
    front, back, _f = _door_geometry(door)
    if front is None:
        return None, None
    ph = door_phase(door)
    return _room_at(doc, front, ph), _room_at(doc, back, ph)


def geometric_rooms_link(door, link_inst):
    front, back, _f = _door_geometry(door)
    if front is None:
        return None, None
    ldoc = link_inst.GetLinkDocument()
    if ldoc is None:
        return None, None
    inv = link_inst.GetTotalTransform().Inverse
    ph = _last_phase(ldoc)
    return (_room_at(ldoc, inv.OfPoint(front), ph),
            _room_at(ldoc, inv.OfPoint(back), ph))


def _room_area(room):
    try:
        pa = room.get_Parameter(DB.BuiltInParameter.ROOM_AREA)
        return pa.AsDouble() if pa else 1e18
    except Exception:
        return 1e18


def _tiebreak(r1, r2):
    if SETTINGS["GEOM_TWOROOM_TIEBREAK"] == "larger":
        return r1 if _room_area(r1) >= _room_area(r2) else r2
    return r1 if _room_area(r1) <= _room_area(r2) else r2


# ---------------------------------------------------------------------------
# Room value getters
# ---------------------------------------------------------------------------
def room_number(room):
    if room is None:
        return None
    try:
        v = room.Number
        if v:
            return v
    except Exception:
        pass
    return param_text(room, "Number")


def room_name(room):
    if room is None:
        return None
    p = room.get_Parameter(DB.BuiltInParameter.ROOM_NAME)
    if p is not None:
        v = p.AsString()
        if v:
            return v
    try:
        return room.Name
    except Exception:
        return None


def pick_direction(from_room, to_room, mode):
    if mode == MODE_TO_FROM:
        primary, secondary, plabel = to_room, from_room, "To"
    elif mode == MODE_FROM_TO:
        primary, secondary, plabel = from_room, to_room, "From"
    elif mode == MODE_TO_ONLY:
        primary, secondary, plabel = to_room, None, "To"
    else:
        primary, secondary, plabel = from_room, None, "From"
    if primary is not None:
        return primary, plabel
    if secondary is not None:
        return secondary, ("From" if plabel == "To" else "To")
    return None, "-"


def resolve_room(door, mode, source, links):
    """Return (room, method, a, b).

    Host / host+links first try the host model (native From/To, then host
    geometry); if nothing is found and links are allowed, fall through to the
    linked models. Pure-link sources go straight to the links.
    """
    if source in (SRC_HOST, SRC_HOST_AND_LINKS):
        fr, tr, _ph = native_rooms(door)
        if fr is not None and tr is not None:
            chosen, label = pick_direction(fr, tr, mode)
            return chosen, label, fr, tr
        if fr is not None or tr is not None:
            return (fr or tr), "Single", fr, tr
        if OPT["geom_fallback"]:
            gf, gb = geometric_rooms_host(door)
            if gf is not None and gb is not None:
                return _tiebreak(gf, gb), "Geometry2", gf, gb
            if gf is not None or gb is not None:
                return (gf or gb), "Geometry", gf, gb
        if source == SRC_HOST:
            return None, "None", None, None
        # SRC_HOST_AND_LINKS: nothing in host, fall through to links below.

    # Linked source(s) - geometry only.
    for li in links:
        gf, gb = geometric_rooms_link(door, li)
        if gf is not None and gb is not None:
            return _tiebreak(gf, gb), "Link2", gf, gb
        if gf is not None or gb is not None:
            return (gf or gb), "Link", gf, gb
    return None, "None", None, None


# ---------------------------------------------------------------------------
# Fire rating
# ---------------------------------------------------------------------------
def parse_minutes(text):
    if not text:
        return None
    s = text.strip().lower()
    m = re.search(r"[-+]?\d*\.?\d+", s)
    if not m:
        return None
    try:
        val = float(m.group())
    except Exception:
        return None
    if "hr" in s or "hour" in s or re.search(r"\bh\b", s):
        unit = "hr"
    elif "min" in s or re.search(r"\bm\b", s):
        unit = "min"
    else:
        unit = SETTINGS["FIRE_BARE_NUMBER_IS"]
    return val * 60.0 if unit == "hr" else val


def compute_fire(door):
    none_text = SETTINGS["FIRE_NONE_TEXT"]
    try:
        host = door.Host
    except Exception:
        host = None
    if not isinstance(host, DB.Wall):
        return none_text, None
    wall_fr = None
    try:
        wt = doc.GetElement(host.GetTypeId())
        wall_fr = param_text(wt, SETTINGS["WALL_FIRE_PARAM"])
    except Exception:
        wall_fr = None
    if not wall_fr:
        wall_fr = param_text(host, SETTINGS["WALL_FIRE_PARAM"])
    mins = parse_minutes(wall_fr)
    if mins is None or mins <= 0:
        return none_text, wall_fr
    door_min = int(math.ceil(mins * SETTINGS["FIRE_FACTOR"]))
    return SETTINGS["FIRE_OUTPUT"].replace("{value}", str(door_min)), wall_fr


# ---------------------------------------------------------------------------
# Door collection / labels
# ---------------------------------------------------------------------------
def collect_doors(scope):
    if scope == SCOPE_VIEW:
        col = DB.FilteredElementCollector(doc, doc.ActiveView.Id)
    elif scope == SCOPE_SELECTION:
        sel_ids = uidoc.Selection.GetElementIds()
        if sel_ids is None or sel_ids.Count == 0:
            return []
        col = DB.FilteredElementCollector(doc, List[DB.ElementId](sel_ids))
    else:
        col = DB.FilteredElementCollector(doc)
    doors = col.OfCategory(DB.BuiltInCategory.OST_Doors) \
               .WhereElementIsNotElementType().ToElements()
    return [d for d in doors if isinstance(d, DB.FamilyInstance)]


def door_mark(door):
    v = param_text(door, SETTINGS["DOOR_TYPE_ID_PARAM"])
    return v if v else "-"


def door_level(door):
    try:
        lid = door.LevelId
        if lid is not None and lid != DB.ElementId.InvalidElementId:
            lvl = doc.GetElement(lid)
            if lvl is not None:
                return lvl.Name
    except Exception:
        pass
    return "-"


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------
def apply_value(door, pname, new_val, wmode):
    p = door.LookupParameter(pname)
    if p is None:
        return "missing"
    old = ""
    try:
        if p.StorageType == DB.StorageType.String:
            old = p.AsString() or ""
    except Exception:
        old = ""
    nv = new_val if new_val is not None else ""
    if wmode == "fill" and old.strip() != "":
        return "skip"
    if old == nv:
        return "same"
    if wmode == "preview":
        return "would"
    if p.IsReadOnly:
        return "readonly"
    try:
        p.Set(nv)
        return "set"
    except Exception:
        return "fail"


CHANGED = ("set", "would")


def _door_xy(door):
    loc = door.Location
    if isinstance(loc, DB.LocationPoint):
        p = loc.Point
        return (p.X, p.Y)
    return None


def _num_letter(n):
    """0->a, 1->b, ... 25->z, 26->aa, 27->ab ..."""
    s = ""
    while True:
        s = chr(97 + (n % 26)) + s
        n = n // 26 - 1
        if n < 0:
            break
    return s


def _natural(s):
    s = s or ""
    return [int(x) if x.isdigit() else x.lower()
            for x in re.split(r"(\d+)", s)]


def compute_door(door, mode, source, links):
    """Resolve the room and build the BASE serial - no writing, no suffix."""
    room, method, side_a, side_b = resolve_room(door, mode, source, links)
    building = param_text(room, SETTINGS["ROOM_BUILDING_CODE"])
    level = param_text(room, SETTINGS["ROOM_LEVEL_CODE"])
    rnum = room_number(room)
    rname = room_name(room)
    have_all = bool(building) and bool(level) and bool(rnum)
    base = SETTINGS["SERIAL_SEPARATOR"].join([building, level, rnum]) \
        if have_all else SETTINGS["EMPTY_VALUE"]
    if OPT["do_fire"]:
        fire_text, wall_fr = compute_fire(door)
    else:
        fire_text, wall_fr = "-", None
    return {
        "door": door, "id": door.Id, "mark": door_mark(door),
        "level": door_level(door), "method": method,
        "building": building, "level_code": level, "rnum": rnum, "rname": rname,
        "have_all": have_all, "base": base, "serial": base,
        "fire_text": fire_text, "wall_fr": wall_fr, "xy": _door_xy(door),
        "room_is_none": room is None,
    }


def _sort_members(members, order):
    if order == "mark":
        members.sort(key=lambda p: (_natural(p["mark"]), p["id"].IntegerValue))
        return
    if order == "xy":
        members.sort(key=lambda p: ((p["xy"][0] if p["xy"] else 0.0),
                                    -(p["xy"][1] if p["xy"] else 0.0),
                                    p["id"].IntegerValue))
        return
    if order == "elementid":
        members.sort(key=lambda p: p["id"].IntegerValue)
        return
    # clockwise around the group's centroid, starting from north (+Y)
    pts = [p["xy"] for p in members if p["xy"]]
    if len(pts) < len(members) or not pts:
        members.sort(key=lambda p: p["id"].IntegerValue)
        return
    cx = sum(x for (x, _y) in pts) / len(pts)
    cy = sum(y for (_x, y) in pts) / len(pts)

    def _ang(p):
        x, y = p["xy"]
        a = math.atan2(x - cx, y - cy)   # 0 = north, increases clockwise
        if a < 0:
            a += 2.0 * math.pi
        return a

    members.sort(key=lambda p: (_ang(p), p["id"].IntegerValue))


def assign_suffixes(plans):
    """Append a/b/c... to the door number where a room has >1 door."""
    if not SETTINGS["SUFFIX_MULTI_DOORS"]:
        return 0
    groups = {}
    for p in plans:
        if p.get("have_all") and p.get("base"):
            groups.setdefault(p["base"], []).append(p)
    order = SETTINGS["SUFFIX_ORDER"]
    suffixed = 0
    for base, members in groups.items():
        if len(members) < 2:
            continue
        _sort_members(members, order)
        for i, p in enumerate(members):
            p["serial"] = p["base"] + _num_letter(i)
            suffixed += 1
    return suffixed


def write_door(plan, wmode):
    """Write the (already suffixed) serial and room data onto the door."""
    door = plan["door"]
    writes = [
        (SETTINGS["DOOR_BUILDING_CODE_PARAM"],
         plan["building"] or SETTINGS["EMPTY_VALUE"]),
        (SETTINGS["DOOR_LEVEL_CODE_PARAM"],
         plan["level_code"] or SETTINGS["EMPTY_VALUE"]),
        (SETTINGS["DOOR_ROOM_NUMBER_PARAM"],
         plan["rnum"] or SETTINGS["EMPTY_VALUE"]),
        (SETTINGS["DOOR_ROOM_NAME_PARAM"],
         plan["rname"] or SETTINGS["EMPTY_VALUE"]),
        (SETTINGS["DOOR_NUMBER_PARAM"], plan["serial"]),
    ]
    if OPT["do_fire"]:
        writes.append((SETTINGS["DOOR_FIRE_PARAM"], plan["fire_text"]))

    changed = 0
    if wmode == "preview":
        for (pn, v) in writes:
            if apply_value(door, pn, v, "preview") in CHANGED:
                changed += 1
    else:
        st = DB.SubTransaction(doc)
        st.Start()
        try:
            for (pn, v) in writes:
                if apply_value(door, pn, v, wmode) in CHANGED:
                    changed += 1
            st.Commit()
        except Exception as ex:
            st.RollBack()
            raise ex

    if plan["room_is_none"]:
        status = "noroom"
    elif not plan["have_all"]:
        status = "partial"
    else:
        status = "ok"

    return {
        "id": plan["id"], "mark": plan["mark"], "level": plan["level"],
        "method": plan["method"], "bldg": plan["building"] or "-",
        "lvl": plan["level_code"] or "-", "rnum": plan["rnum"] or "-",
        "serial": plan["serial"] or "-", "rname": plan["rname"] or "-",
        "wall_fr": plan["wall_fr"] or "-", "door_fr": plan["fire_text"],
        "fire_ok": OPT["do_fire"]
        and plan["fire_text"] != SETTINGS["FIRE_NONE_TEXT"],
        "rcp_suspect": plan["method"] in ("Geometry", "Geometry2"),
        "changed": changed, "status": status,
    }


# ---------------------------------------------------------------------------
# Door schedule
# ---------------------------------------------------------------------------
def build_or_refresh_schedule(notes):
    name = SETTINGS["SCHEDULE_NAME"]
    existing = None
    for vs in DB.FilteredElementCollector(doc).OfClass(DB.ViewSchedule):
        if vs.Name == name:
            existing = vs
            break

    t = DB.Transaction(doc, "SDC - Door schedule")
    t.Start()
    try:
        if existing is None:
            vs = DB.ViewSchedule.CreateSchedule(
                doc, DB.ElementId(DB.BuiltInCategory.OST_Doors))
            vs.Name = name
            action = "created"
        else:
            vs = existing
            for fid in list(vs.Definition.GetFieldOrder()):
                vs.Definition.RemoveField(fid)
            action = "refreshed"

        d = vs.Definition
        d.IsItemized = True
        sfields = {}
        for sfid in d.GetSchedulableFields():
            try:
                nm = sfid.GetName(doc)
            except Exception:
                continue
            if nm not in sfields:
                sfields[nm] = sfid

        added = {}
        missing = []
        for (header, rev_name) in COLUMN_PLAN:
            sf = sfields.get(rev_name)
            if sf is None:
                missing.append(header)
                continue
            fld = d.AddField(sf)
            try:
                fld.ColumnHeading = header
            except Exception:
                pass
            added[rev_name] = fld.FieldId

        def add_sg(rev_name, show_header):
            fid = added.get(rev_name)
            if fid is None:
                return
            sg = DB.ScheduleSortGroupField(fid, DB.ScheduleSortOrder.Ascending)
            if show_header:
                sg.ShowHeader = True
            d.AddSortGroupField(sg)

        add_sg("SDC_G_BUILDING CODE", True)
        add_sg("SDC_G_LEVEL CODE", False)
        add_sg(SETTINGS["DOOR_TYPE_ID_PARAM"], False)

        t.Commit()
        if missing:
            notes.append("Schedule: fields not found -> {0}".format(
                ", ".join(missing)))
        return "Schedule '{0}' {1}.".format(name, action)
    except Exception as ex:
        t.RollBack()
        return "Schedule failed: {0}".format(ex)


# ---------------------------------------------------------------------------
# Tagging
# ---------------------------------------------------------------------------
def door_tag_types():
    result = []
    for s in DB.FilteredElementCollector(doc) \
            .OfCategory(DB.BuiltInCategory.OST_DoorTags) \
            .WhereElementIsElementType():
        try:
            nm = "{0} : {1}".format(s.FamilyName, DB.Element.Name.__get__(s))
        except Exception:
            nm = str(s.Id)
        result.append((nm, s.Id))
    return sorted(result, key=lambda x: x[0])


def _tagged_ids_in_view(view):
    tagged = set()
    for t in DB.FilteredElementCollector(doc, view.Id) \
            .OfClass(DB.IndependentTag):
        try:
            for eid in t.GetTaggedLocalElementIds():
                tagged.add(eid.IntegerValue)
        except Exception:
            try:
                tagged.add(t.TaggedLocalElementId.IntegerValue)
            except Exception:
                pass
    return tagged


def tag_views(choice):
    if choice == VIEWS_ACTIVE:
        av = doc.ActiveView
        return [av] if av is not None else []
    if choice == VIEWS_ALL_PLANS:
        return [v for v in DB.FilteredElementCollector(doc).OfClass(DB.ViewPlan)
                if not v.IsTemplate]
    try:
        picked = forms.select_views(title="Select views to tag")
        return list(picked) if picked else []
    except Exception:
        return []


def do_tagging(tag_type_id, mode, views):
    if tag_type_id is None:
        return "Tagging skipped: no tag type."
    symbol = doc.GetElement(tag_type_id)
    placed = 0
    removed = 0
    t = DB.Transaction(doc, "SDC - Tag doors")
    t.Start()
    try:
        if symbol is not None and not symbol.IsActive:
            symbol.Activate()
            doc.Regenerate()
        for view in views:
            doors = DB.FilteredElementCollector(doc, view.Id) \
                .OfCategory(DB.BuiltInCategory.OST_Doors) \
                .WhereElementIsNotElementType().ToElements()
            if mode == TAG_ALL:
                for tg in list(DB.FilteredElementCollector(doc, view.Id)
                               .OfClass(DB.IndependentTag)):
                    try:
                        doc.Delete(tg.Id)
                        removed += 1
                    except Exception:
                        pass
                tagged = set()
            else:
                tagged = _tagged_ids_in_view(view)
            for door in doors:
                if not isinstance(door, DB.FamilyInstance):
                    continue
                if door.Id.IntegerValue in tagged:
                    continue
                loc = door.Location
                if not isinstance(loc, DB.LocationPoint):
                    continue
                try:
                    DB.IndependentTag.Create(
                        doc, tag_type_id, view.Id, DB.Reference(door),
                        False, DB.TagOrientation.Horizontal, loc.Point)
                    placed += 1
                except Exception:
                    pass
        t.Commit()
    except Exception as ex:
        t.RollBack()
        return "Tagging failed: {0}".format(ex)
    extra = " ({0} replaced)".format(removed) if removed else ""
    return "Placed {0} tag(s){1}.".format(placed, extra)


# ---------------------------------------------------------------------------
# XLSX writer (stdlib only)
# ---------------------------------------------------------------------------
def _col_letter(n):
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _xesc(t):
    return (t.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _cell(col, row, value, style):
    ref = "{0}{1}".format(_col_letter(col), row)
    sa = ' s="{0}"'.format(style) if style else ""
    if value is None or value == "":
        return '<c r="{0}"{1}/>'.format(ref, sa)
    if isinstance(value, bool):
        value = str(value)
    if isinstance(value, (int, float)):
        num = str(value) if isinstance(value, int) else repr(value)
        return '<c r="{0}"{1}><v>{2}</v></c>'.format(ref, sa, num)
    return ('<c r="{0}"{1} t="inlineStr"><is><t xml:space="preserve">{2}'
            '</t></is></c>').format(ref, sa, _xesc(u"{0}".format(value)))


def _sheet_xml(rows, ncols):
    p = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
         '<worksheet xmlns="http://schemas.openxmlformats.org/'
         'spreadsheetml/2006/main">',
         '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" '
         'topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
         '</sheetView></sheetViews>', '<cols>']
    for c in range(1, ncols + 1):
        p.append('<col min="{0}" max="{0}" width="18" customWidth="1"/>'
                 .format(c))
    p.append('</cols><sheetData>')
    ri = 0
    for row in rows:
        ri += 1
        p.append('<row r="{0}">'.format(ri))
        kind = row[0]
        if kind == "group":
            p.append(_cell(1, ri, row[1], 2))
        else:
            style = 1 if kind == "header" else 0
            for ci, val in enumerate(row[1], 1):
                p.append(_cell(ci, ri, val, style))
        p.append('</row>')
    p.append('</sheetData></worksheet>')
    return "".join(p)


_STYLES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/'
    '2006/main"><fonts count="3">'
    '<font><sz val="11"/><name val="Calibri"/></font>'
    '<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font>'
    '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
    '<fills count="3"><fill><patternFill patternType="none"/></fill>'
    '<fill><patternFill patternType="gray125"/></fill>'
    '<fill><patternFill patternType="solid"><fgColor rgb="FF0F6E56"/>'
    '<bgColor indexed="64"/></patternFill></fill></fills>'
    '<borders count="1"><border/></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" '
    'borderId="0"/></cellStyleXfs><cellXfs count="3">'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" '
    'applyFont="1" applyFill="1"/>'
    '<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" '
    'applyFont="1"/></cellXfs>'
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/>'
    '</cellStyles></styleSheet>')


def build_xlsx(path, sheets):
    content_types = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
        'content-types"><Default Extension="rels" ContentType="application/'
        'vnd.openxmlformats-package.relationships+xml"/><Default '
        'Extension="xml" ContentType="application/xml"/><Override '
        'PartName="/xl/workbook.xml" ContentType="application/vnd.'
        'openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.'
        'openxmlformats-officedocument.spreadsheetml.styles+xml"/>')
    wb_sheets = []
    wb_rels = []
    for i, (nm, _rows, _nc) in enumerate(sheets, 1):
        content_types += ('<Override PartName="/xl/worksheets/sheet{0}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.'
            'spreadsheetml.worksheet+xml"/>').format(i)
        wb_sheets.append('<sheet name="{0}" sheetId="{1}" r:id="rId{1}"/>'
                         .format(_xesc(nm), i))
        wb_rels.append('<Relationship Id="rId{0}" Type="http://schemas.'
            'openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            'Target="worksheets/sheet{0}.xml"/>'.format(i))
    content_types += '</Types>'
    style_rid = len(sheets) + 1
    wb_rels.append('<Relationship Id="rId{0}" Type="http://schemas.'
        'openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/>'.format(style_rid))

    workbook = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/'
        '2006/main" xmlns:r="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships"><sheets>{0}</sheets></workbook>'
        ).format("".join(wb_sheets))
    wb_rels_xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/'
        '2006/relationships">{0}</Relationships>').format("".join(wb_rels))
    root_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/'
        '2006/relationships"><Relationship Id="rId1" Type="http://schemas.'
        'openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/></Relationships>')

    zf = zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED)
    try:
        zf.writestr("[Content_Types].xml", content_types.encode("utf-8"))
        zf.writestr("_rels/.rels", root_rels.encode("utf-8"))
        zf.writestr("xl/workbook.xml", workbook.encode("utf-8"))
        zf.writestr("xl/_rels/workbook.xml.rels", wb_rels_xml.encode("utf-8"))
        zf.writestr("xl/styles.xml", _STYLES.encode("utf-8"))
        for i, (nm, rows, nc) in enumerate(sheets, 1):
            zf.writestr("xl/worksheets/sheet{0}.xml".format(i),
                        _sheet_xml(rows, nc).encode("utf-8"))
    finally:
        zf.close()


def _desktop_dir():
    if SETTINGS["CSV_DIR"].strip():
        return SETTINGS["CSV_DIR"].strip()
    cands = []
    up = os.environ.get("USERPROFILE", "")
    if up:
        cands.append(os.path.join(up, "Desktop"))
        cands.append(os.path.join(up, "OneDrive", "Desktop"))
    one = os.environ.get("OneDrive", "")
    if one:
        cands.append(os.path.join(one, "Desktop"))
    for c in cands:
        if os.path.isdir(c):
            return c
    import tempfile
    return tempfile.gettempdir()


def _export_value(door, r, rev_name):
    if rev_name == "SDC_G_BUILDING CODE":
        return "" if r["bldg"] == "-" else r["bldg"]
    if rev_name == "SDC_G_LEVEL CODE":
        return "" if r["lvl"] == "-" else r["lvl"]
    if rev_name == SETTINGS["DOOR_TYPE_ID_PARAM"]:
        return param_text(door, SETTINGS["DOOR_TYPE_ID_PARAM"]) or ""
    if rev_name == "SDC_Door_Number":
        return "" if r["serial"] == "-" else r["serial"]
    if rev_name == "Room_Name":
        return "" if r["rname"] == "-" else r["rname"]
    if rev_name in ("Width", "Height", "Rough Width", "Rough Height"):
        return len_mm(door, rev_name)
    if rev_name == "SDC_LEAVES":
        return int_val(door, rev_name)
    if rev_name == "SDC_Fire_Rating":
        return "" if r["door_fr"] in ("-",) else r["door_fr"]
    if rev_name == "Comments":
        return param_text(door, "Comments") or ""
    return param_text(door, rev_name) or ""


def export_xlsx(pairs, meta):
    try:
        headers = [h for (h, _p) in COLUMN_PLAN]
        rev_names = [p for (_h, p) in COLUMN_PLAN]
        data = []
        for (door, r) in pairs:
            vals = [_export_value(door, r, rn) for rn in rev_names]
            key = (str(vals[0]), str(vals[1]), str(vals[2]))
            data.append((key, vals))
        data.sort(key=lambda x: x[0])

        doors_rows = [("header", headers)]
        cur = None
        for (key, vals) in data:
            b = vals[0] if vals[0] else "(no building)"
            if b != cur:
                cur = b
                doors_rows.append(("group", u"BUILDING: {0}".format(b)))
            doors_rows.append(("data", vals))

        qa_head = ["DOOR TYPE", "LEVEL", "METHOD", "ROOM NO", "DOOR NUMBER",
                   "WALL FR", "DOOR FR", "RCP SUSPECT", "STATUS", "CHANGED"]
        qa_rows = [("header", qa_head)]
        for (door, r) in pairs:
            qa_rows.append(("data", [
                r["mark"], r["level"], r["method"], r["rnum"], r["serial"],
                r["wall_fr"], r["door_fr"], "YES" if r["rcp_suspect"] else "",
                r["status"], r["changed"]]))

        folder = _desktop_dir()
        path = os.path.join(folder, "DOOR SCHEDULE {0}.xlsx".format(
            meta["stamp_file"]))
        build_xlsx(path, [("DOORS", doors_rows, len(headers)),
                          ("QA", qa_rows, len(qa_head))])
        return path
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
GREEN = "#2e7d32"
AMBER = "#f9a825"
RED = "#c62828"
GREY = "#757575"
BLUE = "#1565c0"
PURPLE = "#6a1b9a"
TEAL = "#0f6e56"


def badge(text, color, dark=False):
    fg = "#000" if dark else "#fff"
    return ('<span style="background:{0};color:{1};padding:2px 8px;'
            'border-radius:4px;font-size:11px;white-space:nowrap;">{2}</span>'
            ).format(color, fg, text)


def card(label, value, color):
    return ('<div style="display:inline-block;min-width:92px;margin:4px;'
            'padding:8px 12px;border-radius:8px;background:{0};color:#fff;'
            'text-align:center;"><div style="font-size:20px;font-weight:700;">'
            '{1}</div><div style="font-size:11px;opacity:.9;">{2}</div></div>'
            ).format(color, value, label)


METHOD_BADGE = {
    "To": badge("To", BLUE), "From": badge("From", BLUE),
    "Single": badge("Single", GREEN), "Geometry": badge("Geometry", PURPLE),
    "Geometry2": badge("Geometry x2", PURPLE), "Link": badge("Link", TEAL),
    "Link2": badge("Link x2", TEAL), "None": badge("None", GREY),
}
STATUS_BADGE = {
    "ok": badge("OK", GREEN), "partial": badge("Partial", AMBER, dark=True),
    "noroom": badge("No room", RED), "error": badge("Error", GREY),
}


def render_report(rows, meta, notes, xlsx_path, sched_msg, tag_msg):
    output.print_md("# SDC \u2014 Door Room + Fire Tagging")
    output.print_md("_{0}_".format(meta["stamp"]))
    output.print_md("**Direction:** {0}  |  **Scope:** {1}  |  **Source:** {2}"
                    "  |  **Write mode:** {3}".format(
                        meta["mode"], meta["scope"], meta["source_label"],
                        meta["wmode_label"]))
    output.print_md("**Firm SP file:** `{0}`".format(meta["sp_path"]))
    if meta["wmode"] == "preview":
        output.print_md("> \U0001f9ea **Preview only** \u2014 no changes were "
                        "made.")
    for n in notes:
        output.print_md("> \u26a0 {0}".format(n))

    total = len(rows)
    ok = sum(1 for r in rows if r["status"] == "ok")
    partial = sum(1 for r in rows if r["status"] == "partial")
    noroom = sum(1 for r in rows if r["status"] == "noroom")
    errors = sum(1 for r in rows if r["status"] == "error")
    fire_ok = sum(1 for r in rows if r["fire_ok"])
    rcp = sum(1 for r in rows if r["rcp_suspect"])
    changed = sum(r["changed"] for r in rows)

    cards = "".join([
        card("Doors", total, "#37474f"), card("OK", ok, GREEN),
        card("Partial", partial, AMBER), card("No room", noroom, RED),
        card("Fire rated", fire_ok, BLUE), card("RCP suspect", rcp, PURPLE),
        card("Suffixed", meta.get("suffixed", 0), "#5d4037"),
        card("Errors", errors, "#b71c1c"),
        card(("Would change" if meta["wmode"] == "preview" else "Changed"),
             changed, "#00695c")])
    try:
        output.print_html("<div>" + cards + "</div>")
    except Exception:
        pass

    for msg in (sched_msg, tag_msg):
        if msg:
            output.print_md("> {0}".format(msg))
    if xlsx_path:
        output.print_md("**Excel report:** `{0}`".format(xlsx_path))

    heads = ["Door", "Level", "Method", "Bldg", "Lvl", "Room No",
             "SDC_Door_Number", "Room Name", "Wall FR", "SDC_Fire_Rating",
             "Chg", "Status"]
    html = ['<table style="border-collapse:collapse;font-size:12px;">',
            '<tr style="background:#eee;text-align:left;">'
            + "".join('<th style="padding:4px 8px;">{0}</th>'.format(h)
                      for h in heads) + "</tr>"]
    for r in rows:
        cells = [output.linkify(r["id"], r["mark"]), r["level"],
                 METHOD_BADGE.get(r["method"], r["method"]), r["bldg"],
                 r["lvl"], r["rnum"], r["serial"], r["rname"], r["wall_fr"],
                 r["door_fr"], str(r["changed"]),
                 STATUS_BADGE.get(r["status"], r["status"])]
        html.append('<tr style="border-bottom:1px solid #ddd;">'
                    + "".join('<td style="padding:4px 8px;">{0}</td>'.format(c)
                              for c in cells) + "</tr>")
    html.append("</table>")
    try:
        output.print_html("".join(html))
    except Exception:
        data = [[r["mark"], r["level"], r["method"], r["bldg"], r["lvl"],
                 r["rnum"], r["serial"], r["rname"], r["wall_fr"], r["door_fr"],
                 str(r["changed"]), r["status"]] for r in rows]
        output.print_table(table_data=data, columns=heads)


def _error_row(door, ex):
    return {"id": door.Id, "mark": door_mark(door), "level": door_level(door),
            "method": "None", "bldg": "-", "lvl": "-", "rnum": "-",
            "serial": "-", "rname": str(ex), "wall_fr": "-", "door_fr": "-",
            "fire_ok": False, "rcp_suspect": False, "changed": 0,
            "status": "error"}


# ---------------------------------------------------------------------------
# Run engine
# ---------------------------------------------------------------------------
def run_tool(ch, wmode):
    OPT["do_fire"] = ch["do_fire"]
    OPT["geom_fallback"] = ch["geom"]

    notes = []
    sp_path = _firm_sp_path()
    if wmode != "preview":
        ok, msg, sp_path, pnotes = ensure_door_params()
        notes.extend(pnotes)
        if not ok:
            forms.alert(msg, title=TITLE)
            return None

    doors = collect_doors(ch["scope"])
    if not doors:
        forms.alert("No doors found for scope '{0}'.".format(ch["scope"]),
                    title=TITLE)
        return None

    now = datetime.datetime.now()
    wlabels = {"preview": "Preview (no changes)", "fill": "Fill blanks only",
               "overwrite": "Full overwrite"}
    meta = {"mode": ch["mode"], "scope": ch["scope"], "wmode": wmode,
            "wmode_label": wlabels.get(wmode, wmode), "sp_path": sp_path,
            "source_label": ch["source_label"],
            "stamp": now.strftime("%Y-%m-%d %H:%M:%S"),
            "stamp_file": now.strftime("%Y%m%d_%H%M%S")}

    rows = []
    pairs = []

    # Pass 1: resolve rooms + base serials (no writing).
    plans = []
    with forms.ProgressBar(title="Reading {value}/{max_value}",
                           cancellable=True) as pb:
        n = len(doors)
        for i, door in enumerate(doors, 1):
            if pb.cancelled:
                break
            pb.update_progress(i, n)
            try:
                plans.append(compute_door(door, ch["mode"], ch["source"],
                                          ch["links"]))
            except Exception as ex:
                plans.append({"error": ex, "door": door})

    # Pass 2: append a/b/c... where a room has more than one door.
    suffixed = assign_suffixes([p for p in plans if "error" not in p])

    # Pass 3: write (or preview).
    ttl = "Preview {value}/{max_value}" if wmode == "preview" \
        else "Doors {value}/{max_value}"
    if wmode == "preview":
        with forms.ProgressBar(title=ttl, cancellable=True) as pb:
            n = len(plans)
            for i, plan in enumerate(plans, 1):
                if pb.cancelled:
                    break
                pb.update_progress(i, n)
                if "error" in plan:
                    rows.append(_error_row(plan["door"], plan["error"]))
                    continue
                r = write_door(plan, wmode)
                rows.append(r)
                pairs.append((plan["door"], r))
    else:
        t = DB.Transaction(doc, "SDC - Door room + fire tagging")
        t.Start()
        with forms.ProgressBar(title=ttl, cancellable=True) as pb:
            n = len(plans)
            for i, plan in enumerate(plans, 1):
                if pb.cancelled:
                    break
                pb.update_progress(i, n)
                if "error" in plan:
                    rows.append(_error_row(plan["door"], plan["error"]))
                    continue
                try:
                    r = write_door(plan, wmode)
                except Exception as ex:
                    r = _error_row(plan["door"], ex)
                rows.append(r)
                pairs.append((plan["door"], r))
        t.Commit()
    meta["suffixed"] = suffixed

    sched_msg = tag_msg = xlsx_path = None
    if wmode != "preview":
        if ch["schedule"]:
            sched_msg = build_or_refresh_schedule(notes)
        if ch["tag"]:
            views = tag_views(ch["tag_views"])
            if not views:
                tag_msg = "Tagging skipped: no target views."
            else:
                tag_msg = do_tagging(ch["tag_type_id"], ch["tag_mode"], views)
        if ch["xlsx"]:
            xlsx_path = export_xlsx(pairs, meta)

    render_report(rows, meta, notes, xlsx_path, sched_msg, tag_msg)
    return {"changed": sum(r["changed"] for r in rows), "total": len(rows),
            "rcp": sum(1 for r in rows if r["rcp_suspect"]),
            "noroom": sum(1 for r in rows if r["status"] == "noroom")}


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Door room + fire tagging" Width="486" SizeToContent="Height"
        ResizeMode="NoResize" WindowStartupLocation="CenterScreen"
        Background="#FFF7F7F5" FontFamily="Segoe UI">
  <Window.Resources>
    <Style TargetType="TextBlock" x:Key="Section">
      <Setter Property="Foreground" Value="#FF8A8A82"/>
      <Setter Property="FontSize" Value="11"/>
      <Setter Property="Margin" Value="0,12,0,5"/>
    </Style>
    <Style TargetType="CheckBox"><Setter Property="Margin" Value="0,5"/></Style>
  </Window.Resources>
  <StackPanel>
    <Border Background="#FF0F6E56" Padding="16,12">
      <StackPanel Orientation="Horizontal">
        <Border Width="34" Height="34" Background="#FF085041" CornerRadius="8"
                VerticalAlignment="Center">
          <TextBlock Text="SDC" Foreground="#FF9FE1CB" FontSize="11"
                     FontWeight="Bold" HorizontalAlignment="Center"
                     VerticalAlignment="Center"/>
        </Border>
        <StackPanel Margin="12,0,0,0" VerticalAlignment="Center">
          <TextBlock Text="Door room + fire tagging" Foreground="#FFE1F5EE"
                     FontSize="15" FontWeight="SemiBold"/>
          <TextBlock Text="Rooms, serial, fire, schedule and tags"
                     Foreground="#FF9FE1CB" FontSize="11"/>
        </StackPanel>
      </StackPanel>
    </Border>
    <StackPanel Margin="16,4,16,14">
      <TextBlock Text="Which doors" Style="{StaticResource Section}"/>
      <StackPanel Orientation="Horizontal">
        <RadioButton x:Name="scope_model" GroupName="scope" Content="Whole model"
                     IsChecked="True" Checked="scope_changed" Margin="0,0,16,0"/>
        <RadioButton x:Name="scope_view" GroupName="scope" Content="Active view"
                     Checked="scope_changed" Margin="0,0,16,0"/>
        <RadioButton x:Name="scope_sel" GroupName="scope" Content="Selection"
                     Checked="scope_changed"/>
      </StackPanel>
      <TextBlock x:Name="door_count" Foreground="#FF185FA5" FontSize="12"
                 Margin="0,6,0,0"/>

      <TextBlock Text="Read rooms from" Style="{StaticResource Section}"/>
      <ComboBox x:Name="source_combo" Height="26"/>

      <TextBlock Text="Which room does a door report"
                 Style="{StaticResource Section}"/>
      <ComboBox x:Name="direction_combo" SelectedIndex="0" Height="26">
        <ComboBoxItem Content="To room, fall back to From  (recommended)"/>
        <ComboBoxItem Content="From room, fall back to To"/>
        <ComboBoxItem Content="To room only"/>
        <ComboBoxItem Content="From room only"/>
      </ComboBox>

      <TextBlock Text="Options" Style="{StaticResource Section}"/>
      <Border BorderBrush="#FFE0E0DA" BorderThickness="1" CornerRadius="6"
              Padding="12,6">
        <StackPanel>
          <CheckBox x:Name="fire_chk" IsChecked="True"
                    Content="Compute fire rating (SDC_Fire_Rating)"/>
          <CheckBox x:Name="geom_chk" IsChecked="True"
                    Content="Geometric fallback for RCP-less doors"/>
          <CheckBox x:Name="sched_chk" IsChecked="True"
                    Content="Create / refresh DOOR SCHEDULE"/>
          <CheckBox x:Name="xlsx_chk" IsChecked="True"
                    Content="Export Excel report to Desktop"/>
        </StackPanel>
      </Border>

      <TextBlock Text="Tagging" Style="{StaticResource Section}"/>
      <Border BorderBrush="#FFE0E0DA" BorderThickness="1" CornerRadius="6"
              Padding="12,8">
        <StackPanel>
          <CheckBox x:Name="tag_chk" Content="Tag doors" Margin="0,0,0,6"/>
          <Grid Margin="0,0,0,4">
            <Grid.ColumnDefinitions>
              <ColumnDefinition Width="Auto"/><ColumnDefinition Width="*"/>
            </Grid.ColumnDefinitions>
            <TextBlock Text="Mode" VerticalAlignment="Center" Width="46"
                       Foreground="#FF5F5E5A"/>
            <ComboBox x:Name="tag_mode_combo" Grid.Column="1" Height="24"
                      SelectedIndex="0">
              <ComboBoxItem Content="Only doors with no tag"/>
              <ComboBoxItem Content="All doors (replace existing)"/>
            </ComboBox>
          </Grid>
          <Grid Margin="0,0,0,4">
            <Grid.ColumnDefinitions>
              <ColumnDefinition Width="Auto"/><ColumnDefinition Width="*"/>
            </Grid.ColumnDefinitions>
            <TextBlock Text="Views" VerticalAlignment="Center" Width="46"
                       Foreground="#FF5F5E5A"/>
            <ComboBox x:Name="tag_views_combo" Grid.Column="1" Height="24"
                      SelectedIndex="0">
              <ComboBoxItem Content="Active view"/>
              <ComboBoxItem Content="All plan views"/>
              <ComboBoxItem Content="Selected views..."/>
            </ComboBox>
          </Grid>
          <Grid>
            <Grid.ColumnDefinitions>
              <ColumnDefinition Width="Auto"/><ColumnDefinition Width="*"/>
              <ColumnDefinition Width="Auto"/>
            </Grid.ColumnDefinitions>
            <TextBlock Text="Tag" VerticalAlignment="Center" Width="46"
                       Foreground="#FF5F5E5A"/>
            <ComboBox x:Name="tag_type_combo" Grid.Column="1" Height="24"/>
            <Button x:Name="load_btn" Grid.Column="2" Content="Load..."
                    Click="load_click" Width="64" Height="24" Margin="6,0,0,0"/>
          </Grid>
        </StackPanel>
      </Border>

      <Border BorderBrush="#FFE0E0DA" BorderThickness="0,1,0,0"
              Margin="0,14,0,0" Padding="0,10,0,0">
        <Grid>
          <CheckBox x:Name="fill_chk" Content="Fill blanks only"
                    VerticalAlignment="Center" HorizontalAlignment="Left"
                    Foreground="#FF5F5E5A"/>
          <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
            <Button x:Name="preview_btn" Content="Preview" Click="preview_click"
                    Width="92" Height="30" Margin="0,0,8,0"/>
            <Button x:Name="apply_btn" Content="Apply" Click="apply_click"
                    Width="92" Height="30" Background="#FF0F6E56"
                    Foreground="White" BorderBrush="#FF0F6E56"/>
          </StackPanel>
        </Grid>
      </Border>
    </StackPanel>
    <Border Background="#FFEFEFEA" BorderBrush="#FFE0E0DA"
            BorderThickness="0,1,0,0" Padding="16,6">
      <TextBlock x:Name="sp_path_lbl" Foreground="#FFA0A099" FontSize="11"
                 TextTrimming="CharacterEllipsis"/>
    </Border>
  </StackPanel>
</Window>
"""


def loaded_links():
    result = []
    for li in DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkInstance):
        ldoc = li.GetLinkDocument()
        if ldoc is None:
            continue
        try:
            title = ldoc.Title
        except Exception:
            title = li.Name
        result.append((title, li))
    return result


class TaggingWindow(forms.WPFWindow):
    def __init__(self):
        try:
            forms.WPFWindow.__init__(self, XAML, literal_string=True)
        except TypeError:
            import tempfile
            import codecs
            tmp = os.path.join(tempfile.gettempdir(), "SDC_DoorTag_ui.xaml")
            fh = codecs.open(tmp, "w", "utf-8")
            fh.write(XAML)
            fh.close()
            forms.WPFWindow.__init__(self, tmp)

        self.result = None
        self.choices = None
        self.tag_load_path = None

        self._links = loaded_links()
        all_links = [li for (_t, li) in self._links]
        self._source_items = []  # (label, source_kind, links_list)
        self.source_combo.Items.Clear()

        def _add_src(label, kind, lks):
            self._source_items.append((label, kind, lks))
            self.source_combo.Items.Add(label)

        _add_src("Host model", SRC_HOST, [])
        if self._links:
            _add_src("Host + all links", SRC_HOST_AND_LINKS, all_links)
            for (title, li) in self._links:
                _add_src("Link: " + title, SRC_LINK, [li])
            _add_src("All loaded links", SRC_ALL_LINKS, all_links)
        self.source_combo.SelectedIndex = 0

        self._tag_types = door_tag_types()
        self.tag_type_combo.Items.Clear()
        for (nm, _tid) in self._tag_types:
            self.tag_type_combo.Items.Add(nm)
        if self._tag_types:
            self.tag_type_combo.SelectedIndex = 0

        self._load_config()
        self.sp_path_lbl.Text = "SP file: " + (_firm_sp_path()
                                               or "(set MAIN_SP_FILE_PATH)")
        self._update_count()

    # helpers
    def _current_scope(self):
        if self.scope_view.IsChecked:
            return SCOPE_VIEW
        if self.scope_sel.IsChecked:
            return SCOPE_SELECTION
        return SCOPE_MODEL

    def _update_count(self):
        try:
            n = len(collect_doors(self._current_scope()))
        except Exception:
            n = 0
        self.door_count.Text = "{0} {1} in scope".format(
            n, "door" if n == 1 else "doors")

    def _resolve_source(self):
        idx = self.source_combo.SelectedIndex
        if 0 <= idx < len(self._source_items):
            label, kind, lks = self._source_items[idx]
            return kind, lks, label
        return SRC_HOST, [], "Host model"

    def _gather(self):
        di = self.direction_combo.SelectedIndex
        mode = _MODES[di] if 0 <= di < len(_MODES) else MODE_TO_FROM
        source, links, source_label = self._resolve_source()
        tag_tid = None
        if self.tag_load_path:
            tag_tid = "LOAD"
        elif self._tag_types and self.tag_type_combo.SelectedIndex >= 0:
            tag_tid = self._tag_types[self.tag_type_combo.SelectedIndex][1]
        views_map = [VIEWS_ACTIVE, VIEWS_ALL_PLANS, VIEWS_SELECT]
        vi = self.tag_views_combo.SelectedIndex
        return {
            "scope": self._current_scope(), "mode": mode,
            "source": source, "links": links, "source_label": source_label,
            "fill": bool(self.fill_chk.IsChecked),
            "do_fire": bool(self.fire_chk.IsChecked),
            "geom": bool(self.geom_chk.IsChecked),
            "schedule": bool(self.sched_chk.IsChecked),
            "xlsx": bool(self.xlsx_chk.IsChecked),
            "tag": bool(self.tag_chk.IsChecked),
            "tag_mode": TAG_ALL if self.tag_mode_combo.SelectedIndex == 1
            else TAG_MISSING,
            "tag_views": views_map[vi] if 0 <= vi < 3 else VIEWS_ACTIVE,
            "tag_type_id": tag_tid, "tag_load_path": self.tag_load_path,
        }

    # config
    def _load_config(self):
        try:
            cfg = script.get_config("door_tag")
            sc = cfg.get_option("scope", SCOPE_MODEL)
            self.scope_model.IsChecked = (sc == SCOPE_MODEL)
            self.scope_view.IsChecked = (sc == SCOPE_VIEW)
            self.scope_sel.IsChecked = (sc == SCOPE_SELECTION)
            self.direction_combo.SelectedIndex = int(cfg.get_option("dir_idx", 0))
            self.fill_chk.IsChecked = bool(cfg.get_option("fill", False))
            self.fire_chk.IsChecked = bool(cfg.get_option("fire", True))
            self.geom_chk.IsChecked = bool(cfg.get_option("geom", True))
            self.sched_chk.IsChecked = bool(cfg.get_option("sched", True))
            self.xlsx_chk.IsChecked = bool(cfg.get_option("xlsx", True))
            self.tag_chk.IsChecked = bool(cfg.get_option("tag", False))
            self.tag_mode_combo.SelectedIndex = int(cfg.get_option("tmode", 0))
            self.tag_views_combo.SelectedIndex = int(cfg.get_option("tviews", 0))
        except Exception:
            pass

    def _save_config(self):
        try:
            cfg = script.get_config("door_tag")
            cfg.scope = self._current_scope()
            cfg.dir_idx = self.direction_combo.SelectedIndex
            cfg.fill = bool(self.fill_chk.IsChecked)
            cfg.fire = bool(self.fire_chk.IsChecked)
            cfg.geom = bool(self.geom_chk.IsChecked)
            cfg.sched = bool(self.sched_chk.IsChecked)
            cfg.xlsx = bool(self.xlsx_chk.IsChecked)
            cfg.tag = bool(self.tag_chk.IsChecked)
            cfg.tmode = self.tag_mode_combo.SelectedIndex
            cfg.tviews = self.tag_views_combo.SelectedIndex
            script.save_config()
        except Exception:
            pass

    # events
    def scope_changed(self, sender, args):
        self._update_count()

    def load_click(self, sender, args):
        path = forms.pick_file(file_ext="rfa", title="Select a door tag family")
        if path:
            self.tag_load_path = path
            self.tag_type_combo.Items.Add("(will load: {0})".format(
                os.path.basename(path)))
            self.tag_type_combo.SelectedIndex = self.tag_type_combo.Items.Count - 1
            self.tag_chk.IsChecked = True

    def preview_click(self, sender, args):
        self.result = "preview"
        self.choices = self._gather()
        self._save_config()
        self.Close()

    def apply_click(self, sender, args):
        self.result = "apply"
        self.choices = self._gather()
        self._save_config()
        self.Close()


def _load_tag_family(path):
    """Load a tag .rfa after the dialog closes; return a FamilySymbol id."""
    t = DB.Transaction(doc, "SDC - Load door tag family")
    t.Start()
    try:
        ok, fam = doc.LoadFamily(path)
        t.Commit()
    except Exception:
        t.RollBack()
        return None
    fam_obj = fam if ok else None
    if fam_obj is None:
        for f in DB.FilteredElementCollector(doc).OfClass(DB.Family):
            if f.Name == os.path.splitext(os.path.basename(path))[0]:
                fam_obj = f
                break
    if fam_obj is None:
        return None
    for sid in fam_obj.GetFamilySymbolIds():
        return sid
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    if doc is None or doc.IsFamilyDocument:
        forms.alert("Run this in a Revit project (not the Family Editor).",
                    title=TITLE, exitscript=True)

    win = TaggingWindow()
    win.show_dialog()
    if not win.result:
        return

    ch = win.choices
    if ch["tag"] and ch["tag_type_id"] == "LOAD" and ch["tag_load_path"]:
        ch["tag_type_id"] = _load_tag_family(ch["tag_load_path"])

    write_mode = "fill" if ch["fill"] else "overwrite"

    if win.result == "apply":
        run_tool(ch, write_mode)
        return

    summary = run_tool(ch, "preview")
    if summary is None:
        return
    msg = ("Preview complete.\n\nWould change {0} field(s) across {1} door(s)."
           "\n{2} with no room, {3} resolved by geometry.\n\nApply now ({4})?"
           ).format(summary["changed"], summary["total"], summary["noroom"],
                    summary["rcp"], "fill blanks" if ch["fill"] else "overwrite")
    ans = forms.alert(msg, title=TITLE, options=["Apply changes", "Close"])
    if ans == "Apply changes":
        run_tool(ch, write_mode)


if __name__ == "__main__":
    main()

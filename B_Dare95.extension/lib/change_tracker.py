# -*- coding: utf-8 -*-
"""
Change Tracker - core engine (B_Dare95)

Snapshot-and-diff tracker for the active document.

  Storage (strictly local), one pair of files per document under
  %LOCALAPPDATA%\\B_Dare95\\ChangeTracker :
      <Title>__<key>.json            register: meta + change records (what the report reads)
      <Title>__<key>.snapshot.json   baseline: fingerprint of every tracked element

  Refresh triggers: Sync with Central and Reload Latest (armed from startup.py),
  plus Refresh now in the report. Opening a document never scans: it used to
  hold the open for minutes on large models, and the next sync catches up anyway.

  Tracked change kinds: New, Deleted, Moved, Resized, Data.
  Records whose kinds have a life expectancy (Deleted by default) are purged
  automatically once they expire.
"""

import clr
clr.AddReference("System")
clr.AddReference("RevitAPI")

import os
import json
import time
import math
import hashlib
import traceback
from datetime import datetime, timedelta

from System import EventHandler
from System.IO import File, Directory
from System.Text import UTF8Encoding
from System.Collections.Generic import List

from Autodesk.Revit.DB import (
    FilteredElementCollector, ElementMulticategoryFilter, BuiltInCategory,
    BuiltInParameter, Element, LocationPoint, LocationCurve, StorageType,
    WorksharingUtils, CheckoutStatus, ModelPathUtils,
    FilteredWorksetCollector, WorksetKind
)
from Autodesk.Revit.DB.Events import (
    DocumentOpenedEventArgs, DocumentSynchronizedWithCentralEventArgs,
    DocumentReloadedLatestEventArgs, RevitAPIEventStatus
)


# =============================================================================
# CONFIG
# =============================================================================
REGISTER_DIR = os.path.join(os.environ.get("LOCALAPPDATA", ""), "B_Dare95", "ChangeTracker")
ERROR_LOG = os.path.join(REGISTER_DIR, "tracker_errors.log")
SCHEMA = 1

# Create a register automatically the first time a project is opened
# (same reasoning as the room register: other users won't click the button).
AUTO_REGISTER = True

# Geometry tolerances
TOL_MM = 1.0           # moves / size changes below this are ignored
ANG_TOL_DEG = 0.1      # rotations below this are ignored

# Life expectancy per change kind, in days. None / missing = kept until superseded.
LIFE_EXPECTANCY_DAYS = {
    "Deleted": 30,
}

# Earlier changes kept per element (shown under "Earlier changes" in the report)
HISTORY_LIMIT = 10

# Editable parameters to ignore when diffing "Data"
IGNORE_PARAM_NAMES = set()
IGNORE_BIPS = ["EDITED_BY"]

# Categories considered "vital". Names that don't exist in a Revit version are skipped.
TRACKED_CATEGORIES = [
    # Architecture
    "OST_Walls", "OST_Floors", "OST_Roofs", "OST_Ceilings", "OST_Doors", "OST_Windows",
    "OST_Stairs", "OST_StairsRailing", "OST_Columns", "OST_GenericModel", "OST_ShaftOpening",
    # Structure
    "OST_StructuralColumns", "OST_StructuralFraming", "OST_StructuralFoundation",
    # Mechanical
    "OST_DuctCurves", "OST_FlexDuctCurves", "OST_DuctFitting", "OST_DuctAccessory",
    "OST_DuctTerminal", "OST_MechanicalEquipment",
    # Plumbing / Fire protection
    "OST_PipeCurves", "OST_FlexPipeCurves", "OST_PipeFitting", "OST_PipeAccessory",
    "OST_PlumbingFixtures", "OST_Sprinklers",
    # Electrical
    "OST_CableTray", "OST_CableTrayFitting", "OST_Conduit", "OST_ConduitFitting",
    "OST_ElectricalEquipment", "OST_ElectricalFixtures", "OST_LightingFixtures",
]


# =============================================================================
# CONSTANTS
# =============================================================================
NEW, DELETED, MOVED, RESIZED, DATA = "New", "Deleted", "Moved", "Resized", "Data"
KIND_ORDER = [NEW, DELETED, MOVED, RESIZED, DATA]

TRIGGER_OPEN = u"Document opened"
TRIGGER_SYNC = u"Sync with Central"
TRIGGER_RELOAD = u"Reload Latest"
TRIGGER_MANUAL = u"Manual refresh"
TRIGGER_CREATED = u"Register created"

FT_TO_MM = 304.8
ST_NONE = getattr(StorageType, "None")
ARROW = u"\u2192"
DOT = u"\u00B7"
DEG = u"\u00B0"
_ISO = "%Y-%m-%dT%H:%M:%S"
_ENV_KEY = "B_DARE95_CHANGE_TRACKER_HANDLERS"


# =============================================================================
# SMALL HELPERS
# =============================================================================
def eid_value(eid):
    """ElementId -> plain int (Revit 2025+ .Value, older .IntegerValue)."""
    try:
        return int(eid.Value)
    except AttributeError:
        return int(eid.IntegerValue)


def _iso(dt):
    return dt.strftime(_ISO)


def _parse_iso(text):
    try:
        return datetime.strptime(text, _ISO)
    except Exception:
        return None


def fmt_time(text):
    """'2026-10-10T14:24:00' -> '2026-10-10 (2:24 PM)'"""
    dt = _parse_iso(text) if text else None
    if dt is None:
        return u"\u2014"
    hour = dt.strftime("%I").lstrip("0") or "12"
    return u"{0} ({1}:{2} {3})".format(dt.strftime("%Y-%m-%d"), hour, dt.strftime("%M"), dt.strftime("%p"))


def days_left(rec, now=None):
    """Whole days until a record expires, or None if it never expires."""
    exp = _parse_iso(rec.get("expires")) if rec.get("expires") else None
    if exp is None:
        return None
    now = now or datetime.now()
    return max(0, (exp - now).days)


def noun(category_name):
    """'Structural Columns' -> 'Structural Column' (display only)."""
    name = category_name or u"Element"
    if name.endswith("ies"):
        return name[:-3] + "y"
    if name.endswith("s") and not name.endswith("ss"):
        return name[:-1]
    return name


def _ensure_dir():
    if not Directory.Exists(REGISTER_DIR):
        Directory.CreateDirectory(REGISTER_DIR)


def log_error(context):
    """Append the current traceback to the tracker's error log. Never raises."""
    try:
        _ensure_dir()
        text = u"[{0}] {1}\n{2}\n".format(_iso(datetime.now()), context, traceback.format_exc())
        File.AppendAllText(ERROR_LOG, text, UTF8Encoding(False))
    except Exception:
        pass


def _read_json(path):
    if not File.Exists(path):
        return None
    return json.loads(File.ReadAllText(path, UTF8Encoding(False)))


def _write_json(path, data):
    """Atomic write through .NET (UTF-8 safe), previous version kept as .bak."""
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    tmp = path + ".tmp"
    File.WriteAllText(tmp, text, UTF8Encoding(False))
    if File.Exists(path):
        File.Replace(tmp, path, path + ".bak")
    else:
        File.Move(tmp, path)


# =============================================================================
# DOCUMENT IDENTITY / REGISTER PATHS
# =============================================================================
_BAD_CHARS = set(u'<>:"/\\|?*')


def _safe(name):
    clean = u"".join(u"_" if (ch in _BAD_CHARS or ord(ch) < 32) else ch for ch in (name or u""))
    return clean.strip() or u"Untitled"


def doc_identity(doc):
    """
    (key, title)
      workshared (file) : central GUID, title from the central file name
                          (local copies add _username to doc.Title)
      workshared (ACC)  : cloud model GUID
      standalone        : hash of ProjectInformation UniqueId + file path
    """
    title = doc.Title or u"Untitled"
    key = None
    try:
        if doc.IsWorkshared:
            in_cloud = False
            try:
                in_cloud = doc.IsModelInCloud
            except Exception:
                pass
            if in_cloud:
                key = "acc_" + str(doc.GetCloudModelPath().GetModelGUID())
            else:
                key = "ws_" + str(doc.WorksharingCentralGUID)
                try:
                    central = ModelPathUtils.ConvertModelPathToUserVisiblePath(
                        doc.GetWorksharingCentralModelPath())
                    if central:
                        title = os.path.splitext(os.path.basename(central))[0]
                except Exception:
                    pass
    except Exception:
        key = None

    if not key:
        info = doc.ProjectInformation
        uid = info.UniqueId if info is not None else u""
        raw = u"{0}|{1}".format(uid, (doc.PathName or u"").lower())
        key = "sa_" + hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]
    return key, title


def register_paths(doc):
    """(register_path, snapshot_path, key, title). Renames the files if the title changed."""
    key, title = doc_identity(doc)
    _ensure_dir()
    base = os.path.join(REGISTER_DIR, u"{0}__{1}".format(_safe(title), key))
    reg_path, snap_path = base + ".json", base + ".snapshot.json"

    if not File.Exists(reg_path):
        for found in Directory.GetFiles(REGISTER_DIR, "*__" + key + ".json"):
            old_base = found[:-len(".json")]
            try:
                File.Move(found, reg_path)
                if File.Exists(old_base + ".snapshot.json") and not File.Exists(snap_path):
                    File.Move(old_base + ".snapshot.json", snap_path)
            except Exception:
                log_error("register rename")
            break
    return reg_path, snap_path, key, title


def register_exists(doc):
    return File.Exists(register_paths(doc)[0])


# =============================================================================
# FINGERPRINTING
# =============================================================================
def _r(value, digits=5):
    return round(value, digits)


def _name(element):
    try:
        return Element.Name.GetValue(element)
    except Exception:
        try:
            return element.Name
        except Exception:
            return u""


def _tracked_filter():
    cats = List[BuiltInCategory]()
    for name in TRACKED_CATEGORIES:
        bic = getattr(BuiltInCategory, name, None)
        if bic is not None:
            cats.Add(bic)
    return ElementMulticategoryFilter(cats)


def _ignored_bips():
    out = []
    for name in IGNORE_BIPS:
        bip = getattr(BuiltInParameter, name, None)
        if bip is not None:
            out.append(bip)
    return out


def _type_info(doc, el, cache):
    tid = el.GetTypeId()
    tv = eid_value(tid)
    if tv in cache:
        return cache[tv]
    fam, typ = u"\u2014", u"\u2014"
    if tv != -1:
        etype = doc.GetElement(tid)
        if etype is not None:
            typ = _name(etype) or typ
            try:
                fam = etype.FamilyName or fam
            except Exception:
                pass
    cache[tv] = (tv, fam, typ)
    return cache[tv]


def _location(el):
    try:
        loc = el.Location
    except Exception:
        return None
    if isinstance(loc, LocationPoint):
        try:
            p = loc.Point
        except Exception:
            return None
        rot = None
        try:
            rot = _r(loc.Rotation, 6)
        except Exception:
            pass
        return ["P", _r(p.X), _r(p.Y), _r(p.Z), rot]
    if isinstance(loc, LocationCurve):
        try:
            crv = loc.Curve
            a, b = crv.GetEndPoint(0), crv.GetEndPoint(1)
            length = crv.Length
        except Exception:
            return None
        return ["C", _r(a.X), _r(a.Y), _r(a.Z), _r(b.X), _r(b.Y), _r(b.Z), _r(length)]
    return None


def _bbox(el):
    try:
        bb = el.get_BoundingBox(None)
    except Exception:
        return None
    if bb is None:
        return None
    return [_r(bb.Min.X), _r(bb.Min.Y), _r(bb.Min.Z), _r(bb.Max.X), _r(bb.Max.Y), _r(bb.Max.Z)]


def _params(el, ignored_bips):
    """Editable parameters only: {name: [raw_value, display_value]}."""
    out = {}
    for p in el.Parameters:
        try:
            if p.IsReadOnly:
                continue
            st = p.StorageType
            if st == ST_NONE:
                continue
            definition = p.Definition
            name = definition.Name
            if name in IGNORE_PARAM_NAMES:
                continue
            try:
                if definition.BuiltInParameter in ignored_bips:
                    continue
            except Exception:
                pass

            if st == StorageType.String:
                raw = p.AsString() or u""
                disp = raw
            elif st == StorageType.Double:
                raw = _r(p.AsDouble(), 6)
                disp = p.AsValueString() or unicode(raw)
            elif st == StorageType.Integer:
                raw = p.AsInteger()
                disp = p.AsValueString() or unicode(raw)
            elif st == StorageType.ElementId:
                raw = eid_value(p.AsElementId())
                disp = p.AsValueString() or (u"<None>" if raw == -1 else unicode(raw))
            else:
                continue

            key, n = name, 2
            while key in out:
                key = u"{0} ({1})".format(name, n)
                n += 1
            out[key] = [raw, disp]
        except Exception:
            continue
    return out


def _tooltip(doc, eid, attr):
    try:
        value = getattr(WorksharingUtils.GetWorksharingTooltipInfo(doc, eid), attr)
        return value or None
    except Exception:
        return None


def _modifier(doc, el, user):
    """Who last changed the element. Own unsynced edits -> current user."""
    if not doc.IsWorkshared:
        return user
    try:
        if WorksharingUtils.GetCheckoutStatus(doc, el.Id) == CheckoutStatus.OwnedByCurrentUser:
            return user
    except Exception:
        pass
    return _tooltip(doc, el.Id, "LastChangedBy")


def _closed_worksets(doc):
    closed = set()
    if not doc.IsWorkshared:
        return closed
    try:
        for ws in FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset):
            if not ws.IsOpen:
                closed.add(ws.Id.IntegerValue)
    except Exception:
        log_error("closed worksets")
    return closed


def collect(doc, old_snap):
    """Fingerprint every tracked element: {UniqueId: fingerprint}."""
    snap = {}
    type_cache = {}
    ignored = _ignored_bips()
    workshared = doc.IsWorkshared
    failures = 0

    collector = (FilteredElementCollector(doc)
                 .WherePasses(_tracked_filter())
                 .WhereElementIsNotElementType())
    for el in collector:
        try:
            if el.Category is None or el.ViewSpecific:
                continue
            try:
                if el.SuperComponent is not None:      # nested shared components move with their parent
                    continue
            except AttributeError:
                pass

            uid = el.UniqueId
            tv, fam, typ = _type_info(doc, el, type_cache)
            ws_id = -1
            try:
                ws_id = el.WorksetId.IntegerValue
            except Exception:
                pass

            fp = {
                "i": eid_value(el.Id), "c": el.Category.Name, "f": fam, "t": typ, "ti": tv,
                "w": ws_id, "l": _location(el), "b": _bbox(el), "p": _params(el, ignored),
            }
            prev = old_snap.get(uid) if old_snap else None
            if prev is not None and "cr" in prev:
                fp["cr"] = prev["cr"]          # creator never changes: fetch once
            else:
                fp["cr"] = _tooltip(doc, el.Id, "Creator") if workshared else None
            snap[uid] = fp
        except Exception:
            failures += 1
            if failures <= 5:
                log_error("fingerprint element")
    return snap


# =============================================================================
# DIFF
# =============================================================================
def _dist(a, b):
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def _mm(ft):
    return int(round(ft * FT_TO_MM))


def _fmt_mm(ft):
    return u"{0} mm".format(_mm(ft))


def _signed(ft):
    v = _mm(ft)
    return u"+{0}".format(v) if v > 0 else u"{0}".format(v)


def _extents(b):
    return [b[3] - b[0], b[4] - b[1], b[5] - b[2]]


def _center(b):
    return [(b[0] + b[3]) / 2.0, (b[1] + b[4]) / 2.0, (b[2] + b[5]) / 2.0]


def _fmt_ext(b):
    e = _extents(b)
    return u"{0} x {1} x {2} mm".format(_mm(e[0]), _mm(e[1]), _mm(e[2]))


def _angle_diff(a, b):
    d = abs(a - b) % (2 * math.pi)
    return min(d, 2 * math.pi - d)


def _direction_angle(a0, a1, b0, b1):
    va = [a1[i] - a0[i] for i in range(3)]
    vb = [b1[i] - b0[i] for i in range(3)]
    la = math.sqrt(sum(v * v for v in va))
    lb = math.sqrt(sum(v * v for v in vb))
    if la < 1e-9 or lb < 1e-9:
        return 0.0
    dot = sum(va[i] * vb[i] for i in range(3)) / (la * lb)
    return math.acos(max(-1.0, min(1.0, dot)))


def _shift_text(a, b):
    return u"Shifted {0} (X {1}, Y {2}, Z {3})".format(
        _fmt_mm(_dist(a, b)), _signed(b[0] - a[0]), _signed(b[1] - a[1]), _signed(b[2] - a[2]))


def _differs(a, b):
    if isinstance(a, (int, long, float)) and isinstance(b, (int, long, float)):
        return abs(a - b) > 1e-6
    return a != b


def compare(old, new):
    """(kinds, details, summary). details = [[field, old_text, new_text], ...]"""
    tol = TOL_MM / FT_TO_MM
    ang_tol = math.radians(ANG_TOL_DEG)
    ol, nl, ob, nb = old.get("l"), new.get("l"), old.get("b"), new.get("b")

    kinds, geo, data = [], [], []
    moved = resized = rotated = False
    move_ft = 0.0
    length_change = None
    ext_changed = bool(ob and nb) and any(
        abs(x - y) > tol for x, y in zip(_extents(ob), _extents(nb)))
    bbox_row = [u"Bounding box (X x Y x Z)", _fmt_ext(ob), _fmt_ext(nb)] if (ob and nb) else None

    if ol and nl and ol[0] == "P" and nl[0] == "P":
        d = _dist(ol[1:4], nl[1:4])
        if ol[4] is not None and nl[4] is not None and _angle_diff(ol[4], nl[4]) > ang_tol:
            rotated = moved = True
            geo.append([u"Rotation", u"{0:.1f}{1}".format(math.degrees(ol[4]), DEG),
                        u"{0:.1f}{1}".format(math.degrees(nl[4]), DEG)])
        if d > tol:
            moved, move_ft = True, d
            geo.append([u"Location", u"", _shift_text(ol[1:4], nl[1:4])])
        if ext_changed and not rotated:
            resized = True
            geo.append(bbox_row)

    elif ol and nl and ol[0] == "C" and nl[0] == "C":
        a0, a1, b0, b1 = ol[1:4], ol[4:7], nl[1:4], nl[4:7]
        if abs(nl[7] - ol[7]) > tol:
            resized = True
            length_change = (ol[7], nl[7])
            geo.append([u"Length", _fmt_mm(ol[7]), _fmt_mm(nl[7])])
        ds, de = _dist(a0, b0), _dist(a1, b1)
        dir_changed = _direction_angle(a0, a1, b0, b1) > ang_tol
        if not resized and (ds > tol or de > tol):
            moved, move_ft = True, max(ds, de)
            if dir_changed:
                rotated = True
                geo.append([u"Location", u"", u"Rotated / relocated (start moved {0}, end moved {1})".format(
                    _fmt_mm(ds), _fmt_mm(de))])
            else:
                geo.append([u"Location", u"", _shift_text(a0, b0)])
        if not resized and not dir_changed and ext_changed:
            resized = True
            geo.append(bbox_row)

    elif ext_changed:
        resized = True
        geo.append(bbox_row)

    # vertical moves through offsets, sketch-based elements, etc.
    if not moved and not resized and ob and nb:
        c_old, c_new = _center(ob), _center(nb)
        c = _dist(c_old, c_new)
        if c > tol:
            moved, move_ft = True, c
            geo.append([u"Location", u"", _shift_text(c_old, c_new)])

    if moved:
        kinds.append(MOVED)
    if resized:
        kinds.append(RESIZED)

    if old.get("ti") != new.get("ti"):
        data.append([u"Type", u"{0}: {1}".format(old.get("f"), old.get("t")),
                     u"{0}: {1}".format(new.get("f"), new.get("t"))])
    op, np_ = old.get("p") or {}, new.get("p") or {}
    for key in sorted(set(op) & set(np_)):      # params added/removed from the project are not changes
        if _differs(op[key][0], np_[key][0]):
            data.append([key, op[key][1], np_[key][1]])
    if data:
        kinds.append(DATA)

    parts = []
    if moved:
        if rotated and move_ft <= tol:
            parts.append(u"Rotated")
        elif rotated:
            parts.append(u"Moved {0}, rotated".format(_fmt_mm(move_ft)))
        else:
            parts.append(u"Moved {0}".format(_fmt_mm(move_ft)))
    if resized:
        if length_change:
            parts.append(u"Resized (Length {0} {1} {2})".format(
                _fmt_mm(length_change[0]), ARROW, _fmt_mm(length_change[1])))
        else:
            parts.append(u"Resized")
    if data:
        parts.append(u"{0} changed".format(data[0][0]) if len(data) == 1
                     else u"{0} parameters changed".format(len(data)))

    return kinds, geo + data, (u" " + DOT + u" ").join(parts)


# =============================================================================
# RECORDS
# =============================================================================
def _expiry(kinds, now):
    days = [LIFE_EXPECTANCY_DAYS[k] for k in kinds if LIFE_EXPECTANCY_DAYS.get(k)]
    return _iso(now + timedelta(days=min(days))) if days else None


def _record(uid, fp, kinds, details, summary, created_by, modified_by, now, trigger):
    return {
        "uid": uid, "id": fp.get("i"), "cat": fp.get("c"), "fam": fp.get("f"), "typ": fp.get("t"),
        "kinds": kinds, "summary": summary, "details": details,
        "created_by": created_by, "modified_by": modified_by,
        "detected": _iso(now), "trigger": trigger,
        "expires": _expiry(kinds, now), "bb": fp.get("b"), "history": [],
    }


def _store(changes, rec):
    """Latest change wins; the previous one moves into history."""
    prev = changes.get(rec["uid"])
    if prev is not None:
        history = list(prev.get("history") or [])
        history.append({
            "detected": prev.get("detected"), "kinds": prev.get("kinds"),
            "summary": prev.get("summary"), "details": prev.get("details"),
            "modified_by": prev.get("modified_by"), "trigger": prev.get("trigger"),
        })
        rec["history"] = history[-HISTORY_LIMIT:]
        if not rec.get("created_by"):
            rec["created_by"] = prev.get("created_by")
    changes[rec["uid"]] = rec


def purge_expired(reg, now=None):
    now = now or datetime.now()
    changes = reg.get("changes") or {}
    dead = []
    for uid, rec in changes.items():
        exp = _parse_iso(rec.get("expires")) if rec.get("expires") else None
        if exp is not None and exp <= now:
            dead.append(uid)
    for uid in dead:
        del changes[uid]
    return len(dead)


# =============================================================================
# PUBLIC API
# =============================================================================
def refresh(doc, trigger, create_if_missing=True):
    """Scan, diff against the baseline, record changes, save. Returns the register (or None)."""
    t0 = time.time()
    reg_path, snap_path, key, title = register_paths(doc)
    user = doc.Application.Username

    reg = _read_json(reg_path)
    old_snap = None
    if reg is None:
        if not create_if_missing:
            return None
        reg = {"schema": SCHEMA, "doc_key": key, "created": _iso(datetime.now()), "changes": {}}
    else:
        try:
            old_snap = _read_json(snap_path)
        except Exception:
            log_error("snapshot unreadable, rebuilding baseline")
            old_snap = None

    new_snap = collect(doc, old_snap)
    now = datetime.now()
    changes = reg.setdefault("changes", {})
    counts = dict((k, 0) for k in KIND_ORDER)
    workshared = doc.IsWorkshared

    if old_snap is not None:
        for uid, nfp in new_snap.items():
            ofp = old_snap.get(uid)
            if ofp is None:
                kinds, details, summary = [NEW], [], u"New element"
            else:
                kinds, details, summary = compare(ofp, nfp)
                if not kinds:
                    continue
            el = doc.GetElement(uid)
            modified = _modifier(doc, el, user) if el is not None else None
            created = nfp.get("cr") or (user if (ofp is None and not workshared) else None)
            _store(changes, _record(uid, nfp, kinds, details, summary, created, modified, now, trigger))
            for k in kinds:
                counts[k] += 1

        closed = _closed_worksets(doc)
        for uid, ofp in old_snap.items():
            if uid in new_snap:
                continue
            if ofp.get("w", -1) in closed:
                new_snap[uid] = ofp            # on a closed workset, not deleted: keep it in the baseline
                continue
            details = [[u"Last known type", u"", u"{0}: {1}".format(ofp.get("f"), ofp.get("t"))]]
            _store(changes, _record(uid, ofp, [DELETED], details, u"Element deleted",
                                    ofp.get("cr"), None, now, trigger))
            counts[DELETED] += 1

    purge_expired(reg, now)
    reg["doc_title"] = title
    reg["doc_path"] = doc.PathName
    reg["last_refresh"] = {
        "time": _iso(now), "trigger": trigger, "user": user,
        "scanned": len(new_snap), "seconds": round(time.time() - t0, 1), "counts": counts,
    }

    # Register first: if Revit dies between the two writes, the next refresh
    # simply detects the same changes again instead of losing them.
    _write_json(reg_path, reg)
    _write_json(snap_path, new_snap)
    return reg


def load_register(doc):
    """(register, register_path). Purges expired records on load."""
    reg_path = register_paths(doc)[0]
    reg = _read_json(reg_path)
    if reg is not None and purge_expired(reg):
        _write_json(reg_path, reg)
    return reg, reg_path


# =============================================================================
# EVENT ARMING (called from startup.py)
# =============================================================================
def _eligible(doc):
    try:
        return doc is not None and not doc.IsFamilyDocument and not doc.IsLinked
    except Exception:
        return False


def _handle(doc, trigger):
    try:
        if not _eligible(doc):
            return
        if not AUTO_REGISTER and not register_exists(doc):
            return
        refresh(doc, trigger)
    except Exception:
        log_error(u"event: " + trigger)


def _on_opened(sender, args):
    if args.Status == RevitAPIEventStatus.Succeeded:
        _handle(args.Document, TRIGGER_OPEN)


def _on_synced(sender, args):
    if args.Status == RevitAPIEventStatus.Succeeded:
        _handle(args.Document, TRIGGER_SYNC)


def _on_reloaded(sender, args):
    if args.Status == RevitAPIEventStatus.Succeeded:
        _handle(args.Document, TRIGGER_RELOAD)


def arm(app):
    """Subscribe sync / reload-latest handlers once per session (re-arm safe on pyRevit reload).
    Slot 0 (document open) is intentionally empty: it is only unsubscribed if an older version armed it."""
    from pyrevit.coreutils import envvars

    old = envvars.get_pyrevit_env_var(_ENV_KEY)
    if old is not None:
        try:
            app.DocumentOpened -= old[0]
        except Exception:
            pass
        try:
            app.DocumentSynchronizedWithCentral -= old[1]
        except Exception:
            pass
        try:
            app.DocumentReloadedLatest -= old[2]
        except Exception:
            pass

    h_sync = EventHandler[DocumentSynchronizedWithCentralEventArgs](_on_synced)
    h_reload = EventHandler[DocumentReloadedLatestEventArgs](_on_reloaded)
    app.DocumentSynchronizedWithCentral += h_sync
    app.DocumentReloadedLatest += h_reload

    handlers = List[object]()
    handlers.Add(None)
    handlers.Add(h_sync)
    handlers.Add(h_reload)
    envvars.set_pyrevit_env_var(_ENV_KEY, handlers)
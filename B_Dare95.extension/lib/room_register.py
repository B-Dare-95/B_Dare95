# -*- coding: utf-8 -*-
"""Room Register core - register storage, live tracker and restore logic.

Imported by the extension's startup.py (arms the tracker for every session) and by the
Room Register button (restore UI). Contains no UI.
"""
import os
import re
import json
import hashlib
import datetime
import traceback

from System import EventHandler, Guid, Int64
from System.IO import File
from System.Text import UTF8Encoding
from System.Collections.Generic import List

from Autodesk.Revit.DB import (FilteredElementCollector, BuiltInCategory, BuiltInParameter,
                               ElementCategoryFilter, ElementId, StorageType, Transaction,
                               SubTransaction, TransactionStatus, XYZ, Level, Phase,
                               WorksharingUtils, CheckoutStatus, ModelPathUtils,
                               SpatialElementBoundaryOptions)
from Autodesk.Revit.DB.Architecture import Room
from Autodesk.Revit.DB.Events import (DocumentChangedEventArgs, DocumentOpenedEventArgs,
                                      DocumentClosingEventArgs,
                                      DocumentSynchronizedWithCentralEventArgs)
from Autodesk.Revit.UI.Events import IdlingEventArgs
try:
    from Autodesk.Revit.DB.Events import DocumentReloadedLatestEventArgs
except ImportError:
    DocumentReloadedLatestEventArgs = None

from pyrevit.coreutils import envvars


ENV_KEY = "B_DARE95_ROOM_REGISTER_TRACKER"
SCHEMA = 1
LIVE = ("Placed", "Unplaced")
PROBE = 1.0          # ft above a location point when testing IsPointInRoom
TOL = 1e-7           # tolerance when comparing stored doubles / points
REG_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                       "B_Dare95", "RoomRegister")

# Create a register automatically for every saved project that has rooms, so tracking
# doesn't depend on anyone Shift+Clicking. Set False to require the manual Shift+Click.
AUTO_REGISTER = True


# =============================================================== helpers
def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _log(msg):
    try:
        if not os.path.isdir(REG_DIR):
            os.makedirs(REG_DIR)
        File.AppendAllText(os.path.join(REG_DIR, "tracker.log"),
                           u"{}  {}\n".format(_now(), msg), UTF8Encoding(False))
    except Exception:
        pass


def id_value(eid):
    # ElementId.Value is System.Int64 in 2024+; IronPython's json can't serialize it,
    # so always hand back a plain Python int
    try:
        return int(eid.Value)
    except AttributeError:
        return int(eid.IntegerValue)


def make_id(n):
    try:
        return ElementId(Int64(n))
    except Exception:
        return ElementId(int(n))


def _json_default(o):
    """Converts .NET values (Int64, Int32, Double, ...) that IronPython's json rejects."""
    for cast in (int, float):
        try:
            return cast(o)
        except Exception:
            pass
    return str(o)


def _md5(text):
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:10]


def _safe(title):
    s = re.sub(r"[^A-Za-z0-9_\-]+", "_", title or "").strip("_")
    return (s or "Model")[:60]


def _rooms(doc):
    col = (FilteredElementCollector(doc)
           .OfCategory(BuiltInCategory.OST_Rooms)
           .WhereElementIsNotElementType())
    return [e for e in col if isinstance(e, Room)]


def _has_rooms(doc):
    first = (FilteredElementCollector(doc)
             .OfCategory(BuiltInCategory.OST_Rooms)
             .WhereElementIsNotElementType()
             .FirstElementId())
    return first is not None and id_value(first) > 0


def _room_name(room):
    p = room.get_Parameter(BuiltInParameter.ROOM_NAME)
    return (p.AsString() if p else None) or ""


def _level_uid(room):
    try:
        lv = room.Level
        return lv.UniqueId if lv is not None else None
    except Exception:
        return None


def _phase_id(room):
    for bip in (BuiltInParameter.ROOM_PHASE_ID, BuiltInParameter.ROOM_PHASE):
        try:
            p = room.get_Parameter(bip)
            if p is not None and p.StorageType == StorageType.ElementId:
                eid = p.AsElementId()
                if eid is not None and id_value(eid) > 0:
                    return eid
        except Exception:
            pass
    return None


def _phase_uid(doc, room):
    eid = _phase_id(room)
    el = doc.GetElement(eid) if eid is not None else None
    return el.UniqueId if el is not None else None


def _tooltip(doc, eid):
    if not doc.IsWorkshared:
        return None
    try:
        return WorksharingUtils.GetWorksharingTooltipInfo(doc, eid)
    except Exception:
        return None


# ====================================================== document identity
def doc_key(doc):
    """Stable identity: central GUID > cloud GUID > ProjectInfo UniqueId + path."""
    try:
        if doc.IsWorkshared:
            try:
                g = doc.WorksharingCentralGUID
                if g != Guid.Empty:
                    return "ws_" + str(g)
            except Exception:
                pass
            mp = doc.GetWorksharingCentralModelPath()
            return "wsp_" + _md5(ModelPathUtils.ConvertModelPathToUserVisiblePath(mp).lower())
    except Exception:
        pass
    try:
        if doc.IsModelInCloud:
            return "cloud_" + str(doc.GetCloudModelPath().GetModelGUID())
    except Exception:
        pass
    if not doc.PathName:
        return None
    return "file_{}_{}".format(doc.ProjectInformation.UniqueId, _md5(doc.PathName.lower()))


def doc_title(doc):
    try:
        if doc.IsWorkshared and not doc.IsModelInCloud:
            p = ModelPathUtils.ConvertModelPathToUserVisiblePath(doc.GetWorksharingCentralModelPath())
            return os.path.splitext(os.path.basename(p))[0]
    except Exception:
        pass
    return doc.Title


def find_register(key):
    if not key or not os.path.isdir(REG_DIR):
        return None
    suffix = "__{}.json".format(key)
    for fn in os.listdir(REG_DIR):
        if fn.endswith(suffix):
            return os.path.join(REG_DIR, fn)
    return None


# ============================================================ parameters
def param_key(p):
    d = p.Definition
    try:
        bip = d.BuiltInParameter
        if bip != BuiltInParameter.INVALID:
            return "bip:" + str(bip)
    except Exception:
        pass
    if p.IsShared:
        return "guid:" + str(p.GUID)
    return "name:" + d.Name


def read_params(doc, el):
    """Writable instance parameters only, stored as internal values."""
    out = {}
    for p in el.Parameters:
        try:
            if p.IsReadOnly:
                continue
            st = p.StorageType
            v = {"name": p.Definition.Name}
            if st == StorageType.String:
                v.update(t="S", v=p.AsString())
            elif st == StorageType.Integer:
                v.update(t="I", v=p.AsInteger())
            elif st == StorageType.Double:
                v.update(t="D", v=round(p.AsDouble(), 9))
            elif st == StorageType.ElementId:
                eid = p.AsElementId()
                n = id_value(eid)
                if n < 0:
                    v.update(t="E", v=None, neg=n)
                else:
                    target = doc.GetElement(eid)
                    v.update(t="E", v=target.UniqueId if target is not None else None)
            else:
                continue
            out[param_key(p)] = v
        except Exception:
            continue
    return out


def write_params(doc, room, stored):
    """Returns (missing, failed) lists of parameter display names."""
    live = {}
    for p in room.Parameters:
        try:
            live[param_key(p)] = p
        except Exception:
            pass
    missing, failed = [], []
    for key, sv in stored.items():
        label = sv.get("name") or key
        p = live.get(key)
        if p is None:
            missing.append(label)
            continue
        if p.IsReadOnly:
            continue
        try:
            t, v = sv.get("t"), sv.get("v")
            ok = True
            if t == "S":
                if v is not None:
                    ok = p.Set(v)
            elif t == "I":
                if v is not None:
                    ok = p.Set(int(v))
            elif t == "D":
                if v is not None:
                    ok = p.Set(float(v))
            elif t == "E":
                if v:
                    target = doc.GetElement(v)
                    ok = p.Set(target.Id) if target is not None else False
                elif sv.get("neg") is not None:
                    ok = p.Set(make_id(sv["neg"]))
            if ok is False:
                failed.append(label)
        except Exception:
            failed.append(label)
    return missing, failed


def _same_value(a, b):
    if a.get("t") != b.get("t"):
        return False
    if a.get("t") == "D":
        va, vb = a.get("v"), b.get("v")
        if va is None or vb is None:
            return va == vb
        return abs(float(va) - float(vb)) < TOL
    return a.get("v") == b.get("v") and a.get("neg") == b.get("neg")


def _same_params(a, b):
    if a is None or b is None:
        return a == b
    if set(a.keys()) != set(b.keys()):
        return False
    for k in a:
        if not _same_value(a[k], b[k]):
            return False
    return True


def _same_point(a, b):
    if a is None or b is None:
        return a == b
    return all(abs(float(x) - float(y)) < TOL for x, y in zip(a, b))


# ============================================================== register
class Register(object):
    def __init__(self, path, data):
        self.path = path
        self.data = data
        data.setdefault("rooms", {})
        self.rooms = data["rooms"]
        self.dirty = False
        self.idmap = {}
        self.rebuild_idmap()

    @classmethod
    def load(cls, path):
        last_error = None
        for candidate in (path, path + ".bak"):
            if not os.path.exists(candidate):
                continue
            try:
                text = File.ReadAllText(candidate, UTF8Encoding(False))
                return cls(path, json.loads(text))
            except Exception as e:
                last_error = e
                _log("Could not read {}: {}".format(candidate, e))
        raise IOError("Register unreadable: {} ({})".format(path, last_error))

    def save(self):
        self.data["updated"] = _now()
        tmp = self.path + ".tmp"
        # ensure_ascii=False skips IronPython json's str->bytes decode, which fails on
        # non-ASCII text (e.g. accented parameter names); .NET writes the UTF-8 file
        text = json.dumps(self.data, indent=1, sort_keys=True,
                          ensure_ascii=False, default=_json_default)
        File.WriteAllText(tmp, text, UTF8Encoding(False))
        if File.Exists(self.path):
            File.Replace(tmp, self.path, self.path + ".bak")
        else:
            File.Move(tmp, self.path)
        self.dirty = False

    def rebuild_idmap(self):
        self.idmap = {}
        for uid, rec in self.rooms.items():
            eid = rec.get("element_id")
            if rec.get("status") in LIVE and eid is not None:
                self.idmap[int(eid)] = uid

    def upsert(self, doc, room, source, user=None):
        """source: 'live' (own edits, user = app.Username) or 'scan' (open/sync/reload)."""
        uid = room.UniqueId
        eid = int(id_value(room.Id))
        loc = room.Location
        status = "Placed" if loc is not None else "Unplaced"
        location = None
        if loc is not None:
            p = loc.Point
            location = [round(p.X, 9), round(p.Y, 9), round(p.Z, 9)]
        level_uid = _level_uid(room)
        phase_uid = _phase_uid(doc, room)
        params = read_params(doc, room)

        rec = self.rooms.get(uid)
        if rec is None:
            tip = _tooltip(doc, room.Id) if source == "scan" else None
            self.rooms[uid] = {
                "uid": uid, "element_id": eid, "status": status,
                "level_uid": level_uid, "phase_uid": phase_uid, "location": location,
                "created_by": user if source == "live" else ((tip.Creator if tip else None) or None),
                "last_modified_by": user if source == "live" else ((tip.LastChangedBy if tip else None) or None),
                "last_updated": _now(), "status_changed": _now(),
                "deleted_by": None, "deleted_in": None,
                "restored_from": None, "restored_to": None,
                "params": params,
            }
            self.idmap[eid] = uid
            self.dirty = True
            return True

        changed = False
        old_eid = rec.get("element_id")
        if old_eid is None or int(old_eid) != eid:
            if old_eid is not None and self.idmap.get(int(old_eid)) == uid:
                del self.idmap[int(old_eid)]
            rec["element_id"] = eid
            changed = True
        self.idmap[eid] = uid
        if rec.get("status") != status:
            rec["status"] = status
            rec["status_changed"] = _now()
            rec["deleted_by"] = None
            rec["deleted_in"] = None
            changed = True

        # Unplaced rooms are frozen: location, level, phase and parameters keep the
        # last placed state. Revit alters an unplaced room's height limits, so letting
        # them update would overwrite the values needed to restore it correctly.
        data_changed = False
        if status != "Unplaced":
            if location is not None and not _same_point(rec.get("location"), location):
                rec["location"] = location
                data_changed = True
            if level_uid and rec.get("level_uid") != level_uid:
                rec["level_uid"] = level_uid
                data_changed = True
            if phase_uid and rec.get("phase_uid") != phase_uid:
                rec["phase_uid"] = phase_uid
                data_changed = True
            if not _same_params(rec.get("params"), params):
                rec["params"] = params
                data_changed = True

        if data_changed:
            # last_updated is the age of the stored snapshot, so only real data moves it
            rec["last_updated"] = _now()
            if source == "live":
                rec["last_modified_by"] = user
            else:
                tip = _tooltip(doc, room.Id)
                rec["last_modified_by"] = (tip.LastChangedBy if tip else None) or None
        if changed or data_changed:
            self.dirty = True
        return changed or data_changed

    def mark_deleted(self, eid, user, tx):
        uid = self.idmap.pop(int(eid), None)
        if uid is None:
            return False
        rec = self.rooms.get(uid)
        if rec is None or rec.get("status") not in LIVE:
            return False
        rec["status"] = "Deleted"
        rec["status_changed"] = _now()
        rec["deleted_by"] = user
        rec["deleted_in"] = tx
        self.dirty = True
        return True

    def rescan(self, doc, source):
        seen = set()
        for room in _rooms(doc):
            seen.add(room.UniqueId)
            self.upsert(doc, room, "scan")
        for uid, rec in self.rooms.items():
            if rec.get("status") in LIVE and uid not in seen:
                # removed while untracked or by another user: deleter unknown,
                # data is as of the last time this register saw the room
                rec["status"] = "Deleted"
                rec["status_changed"] = _now()
                rec["deleted_by"] = None
                rec["deleted_in"] = "Detected on {}".format(source)
                self.dirty = True
        self.rebuild_idmap()


# =============================================================== tracker
def _subscribe(uiapp, name, delegate, add):
    owner = uiapp if name == "Idling" else uiapp.Application
    ev = getattr(owner, name)
    if add:
        ev += delegate
    else:
        ev -= delegate


class Tracker(object):
    def __init__(self, uiapp, source="unknown"):
        self.uiapp = uiapp
        self.source = source
        self.app = uiapp.Application
        self.regs = {}
        self.missing = set()
        self.delegates = []
        self.room_filter = ElementCategoryFilter(BuiltInCategory.OST_Rooms)

    # -- register lookup
    def register_for(self, doc):
        if doc is None:
            return None
        try:
            if doc.IsFamilyDocument or doc.IsLinked:
                return None
            key = doc_key(doc)
        except Exception:
            return None
        if not key:
            return None
        if key in self.regs:
            return self.regs[key]
        if key in self.missing:
            return None
        path = find_register(key)
        if not path:
            self.missing.add(key)
            return None
        try:
            reg = Register.load(path)
        except Exception:
            _log(traceback.format_exc())
            self.missing.add(key)
            return None
        self.regs[key] = reg
        return reg

    def create_register(self, doc):
        if not os.path.isdir(REG_DIR):
            os.makedirs(REG_DIR)
        key, title = doc_key(doc), doc_title(doc)
        path = os.path.join(REG_DIR, "{}__{}.json".format(_safe(title), key))
        data = {"schema": SCHEMA, "doc_key": key, "doc_title": title,
                "created": _now(), "created_by": self.app.Username, "rooms": {}}
        reg = Register(path, data)
        reg.rescan(doc, "baseline")
        reg.save()
        self.regs[key] = reg
        self.missing.discard(key)
        return reg

    def flush_all(self):
        for reg in self.regs.values():
            if reg.dirty:
                try:
                    reg.save()
                except Exception:
                    _log(traceback.format_exc())

    # -- arming
    def arm(self):
        pairs = [
            ("DocumentChanged", EventHandler[DocumentChangedEventArgs](self._on_changed)),
            ("DocumentOpened", EventHandler[DocumentOpenedEventArgs](self._on_opened)),
            ("DocumentClosing", EventHandler[DocumentClosingEventArgs](self._on_closing)),
            ("DocumentSynchronizedWithCentral",
             EventHandler[DocumentSynchronizedWithCentralEventArgs](self._on_synced)),
            ("Idling", EventHandler[IdlingEventArgs](self._on_idling)),
        ]
        if DocumentReloadedLatestEventArgs is not None:
            pairs.append(("DocumentReloadedLatest",
                          EventHandler[DocumentReloadedLatestEventArgs](self._on_reloaded)))
        for name, d in pairs:
            try:
                _subscribe(self.uiapp, name, d, True)
                self.delegates.append((name, d))
            except Exception:
                _log("Could not subscribe {}: {}".format(name, traceback.format_exc()))
        _log("Tracker armed ({}) - {} events subscribed".format(self.source, len(self.delegates)))
        # catch up on every open document: register it if needed, otherwise rescan it
        for doc in self.app.Documents:
            if self.auto_register(doc) is None:
                self._rescan(doc, "tracker armed")

    def auto_register(self, doc):
        """Creates a register for a saved project that has rooms and doesn't have one yet."""
        if not AUTO_REGISTER or doc is None:
            return None
        try:
            if doc.IsFamilyDocument or doc.IsLinked:
                return None
            key = doc_key(doc)
            if not key or find_register(key) or not _has_rooms(doc):
                return None
            reg = self.create_register(doc)
            _log("Auto-registered '{}' ({} rooms)".format(reg.data.get("doc_title"), len(reg.rooms)))
            return reg
        except Exception:
            _log("Auto-register: " + traceback.format_exc())
            return None

    def rescan_doc(self, doc, source):
        self._rescan(doc, source)

    # -- handlers (must never throw into Revit)
    def _on_changed(self, sender, args):
        try:
            doc = args.GetDocument()
            reg = self.register_for(doc)
            if reg is None:
                # first rooms added to an unregistered project: register it now
                # (the baseline scan already includes the new rooms)
                if AUTO_REGISTER and args.GetAddedElementIds(self.room_filter).Count:
                    self.auto_register(doc)
                return
            user = self.app.Username
            for eid in args.GetAddedElementIds(self.room_filter):
                el = doc.GetElement(eid)
                if isinstance(el, Room):
                    reg.upsert(doc, el, "live", user)
            for eid in args.GetModifiedElementIds(self.room_filter):
                el = doc.GetElement(eid)
                if isinstance(el, Room):
                    reg.upsert(doc, el, "live", user)
            deleted = args.GetDeletedElementIds()
            if deleted.Count:
                tx = "{}: {}".format(args.Operation, ", ".join(args.GetTransactionNames()))
                for eid in deleted:
                    reg.mark_deleted(id_value(eid), user, tx)
        except Exception:
            _log("DocumentChanged: " + traceback.format_exc())

    def _rescan(self, doc, source):
        try:
            reg = self.register_for(doc)
            if reg is None:
                return
            reg.rescan(doc, source)
            if reg.dirty:
                reg.save()
        except Exception:
            _log("Rescan ({}): {}".format(source, traceback.format_exc()))

    def _on_opened(self, sender, args):
        if self.auto_register(args.Document) is None:
            self._rescan(args.Document, "open")

    def _on_synced(self, sender, args):
        self._rescan(args.Document, "sync")

    def _on_reloaded(self, sender, args):
        self._rescan(args.Document, "reload latest")

    def _on_closing(self, sender, args):
        try:
            key = doc_key(args.Document)
            reg = self.regs.pop(key, None)
            if reg is not None and reg.dirty:
                reg.save()
        except Exception:
            _log("DocumentClosing: " + traceback.format_exc())

    def _on_idling(self, sender, args):
        for reg in self.regs.values():
            if reg.dirty:
                try:
                    reg.save()
                except Exception:
                    reg.dirty = False     # retried on the next change, avoids log spam
                    _log("Save failed: " + traceback.format_exc())


def get_tracker():
    try:
        return envvars.get_pyrevit_env_var(ENV_KEY)
    except Exception:
        return None


def ensure_tracker(uiapp):
    """Returns the session tracker armed at startup, arming one only if it is missing."""
    tracker = get_tracker()
    if tracker is None:
        tracker = rearm_tracker(uiapp, "button - startup tracker not found")
    return tracker


def rearm_tracker(uiapp, source="startup"):
    """Flush and unsubscribe any existing tracker (e.g. after a pyRevit reload), then arm a fresh one."""
    old = envvars.get_pyrevit_env_var(ENV_KEY)
    if old is not None:
        try:
            old.flush_all()
        except Exception:
            pass
        try:
            for name, d in old.delegates:
                try:
                    _subscribe(uiapp, name, d, False)
                except Exception:
                    pass
        except Exception:
            pass
    tracker = Tracker(uiapp, source)
    tracker.arm()
    envvars.set_pyrevit_env_var(ENV_KEY, tracker)
    return tracker


# ============================================================= placement
def resolve(doc, rec):
    level = doc.GetElement(rec["level_uid"]) if rec.get("level_uid") else None
    if not isinstance(level, Level):
        level = None
    phase = doc.GetElement(rec["phase_uid"]) if rec.get("phase_uid") else None
    if not isinstance(phase, Phase):
        phase = None
    loc = rec.get("location")
    pt = XYZ(float(loc[0]), float(loc[1]), float(loc[2])) if loc else None
    return level, phase, pt


def _point_in_room_2d(room, x, y):
    """Even-odd test of (x, y) against the room's boundary loops (holes handled).

    Plan-only on purpose: IsPointInRoom tests the room's 3D volume, so its answer
    depends on the probe height, limit offsets and volume settings.
    """
    loops = room.GetBoundarySegments(SpatialElementBoundaryOptions())
    if loops is None or loops.Count == 0:
        return False
    inside = False
    for loop in loops:
        pts = []
        for seg in loop:
            for p in seg.GetCurve().Tessellate():
                pts.append((p.X, p.Y))
        n = len(pts)
        for i in range(n):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % n]
            if (y1 > y) != (y2 > y):
                if x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                    inside = not inside
    return inside


def occupied_by(doc, level, phase, pt, exclude_uid=None):
    level_val, phase_val = id_value(level.Id), id_value(phase.Id)
    for r in _rooms(doc):
        if r.UniqueId == exclude_uid or r.Location is None or r.Area <= 0:
            continue
        if id_value(r.LevelId) != level_val:
            continue
        ph = _phase_id(r)
        if ph is None or id_value(ph) != phase_val:
            continue
        bb = r.get_BoundingBox(None)
        if bb is not None and not (bb.Min.X <= pt.X <= bb.Max.X and
                                   bb.Min.Y <= pt.Y <= bb.Max.Y):
            continue
        if _point_in_room_2d(r, pt.X, pt.Y):
            return r
    return None


def owner_if_other(doc, eid):
    if not doc.IsWorkshared:
        return None
    try:
        if WorksharingUtils.GetCheckoutStatus(doc, eid) == CheckoutStatus.OwnedByOtherUser:
            tip = WorksharingUtils.GetWorksharingTooltipInfo(doc, eid)
            return (tip.Owner if tip else None) or "another user"
    except Exception:
        pass
    return None


def _move_to(room, pt):
    cur = room.Location.Point
    room.Location.Move(XYZ(pt.X - cur.X, pt.Y - cur.Y, 0))


def _err(e):
    return "{}: {}".format(type(e).__name__, e)


def _contains(room, pt):
    """Returns (True, "") or (False, why) for 'the placed room holds the stored point'."""
    try:
        if room.Location is None:
            return False, "room has no location after placement"
        if room.Area <= 1e-6:
            return False, "room area is 0 after placement"
        if _point_in_room_2d(room, pt.X, pt.Y):
            try:
                z = room.Location.Point.Z
                if not room.IsPointInRoom(XYZ(pt.X, pt.Y, z + PROBE)):
                    _log("IsPointInRoom disagreed with the boundary test for room {} "
                         "(probe z = location z + {} ft)".format(room.UniqueId, PROBE))
            except Exception:
                pass
            return True, ""
        return False, "stored point is outside the region it was placed in"
    except Exception as e:
        return False, _err(e)


LIMIT_KEYS = ("bip:ROOM_UPPER_LEVEL", "bip:ROOM_UPPER_OFFSET", "bip:ROOM_LOWER_OFFSET")


def _mm(ft):
    return "{:.0f} mm".format(float(ft) * 304.8)


def stored_limits(doc, rec):
    """Returns ((upper_level, limit_offset, base_offset), "") or (None, what is missing).

    No fallbacks: a missing Upper Limit is reported, never assumed to be the room's
    own level (that assumption turns 'level above + 0 offset' into zero height).
    """
    prm = rec.get("params") or {}
    up, uo, lo = [prm.get(k) for k in LIMIT_KEYS]
    if not up:
        return None, "Upper Limit is not in the record"
    if not up.get("v"):
        return None, "Upper Limit is stored empty (raw id {})".format(up.get("neg"))
    upper = doc.GetElement(up["v"])
    if not isinstance(upper, Level):
        return None, "stored Upper Limit level no longer exists"
    if not uo or uo.get("v") is None:
        return None, "Limit Offset is not in the record"
    if not lo or lo.get("v") is None:
        return None, "Base Offset is not in the record"
    return (upper, float(uo["v"]), float(lo["v"])), ""


def limits_height(level, limits):
    upper, limit_offset, base_offset = limits
    return (upper.ProjectElevation + limit_offset) - (level.ProjectElevation + base_offset)


def apply_limits(room, level, limits):
    """Writes the stored height limits. Called before Revit regenerates the placement."""
    upper, limit_offset, base_offset = limits
    for bip, value in ((BuiltInParameter.ROOM_UPPER_LEVEL, upper.Id),
                       (BuiltInParameter.ROOM_UPPER_OFFSET, limit_offset),
                       (BuiltInParameter.ROOM_LOWER_OFFSET, base_offset)):
        try:
            p = room.get_Parameter(bip)
            if p is not None and not p.IsReadOnly:
                p.Set(value)
        except Exception:
            _log("Could not set {} on {}: {}".format(bip, room.UniqueId, traceback.format_exc()))


def resolve_limits(doc, rec, level):
    """Returns (limits or None, note). Unusable limits are left to Revit, with the reason."""
    if level is None:
        return None, ""
    limits, missing = stored_limits(doc, rec)
    if limits is None:
        return None, "{} - Revit may ask to adjust limits".format(missing)
    upper, limit_offset, base_offset = limits
    height = limits_height(level, limits)
    if height <= 1e-6:
        return None, ("stored limits give {} height (level {}, upper {}, limit offset {}, "
                      "base offset {}) - Revit will ask to adjust limits").format(
            _mm(height), level.Name, upper.Name, _mm(limit_offset), _mm(base_offset))
    return limits, ""


def place_in_region(doc, room, level, phase, pt, limits=None):
    """Places an unplaced room into the free enclosed region containing pt.

    Returns (True, "") or (False, reason). The reason names the step that failed,
    so a real 'not enclosed' is never confused with an API error.
    """
    try:
        circuits = list(doc.get_PlanTopology(level, phase).Circuits)
    except Exception as e:
        return False, "could not read the plan topology ({})".format(_err(e))
    free = [c for c in circuits if not c.IsRoomLocated]
    if limits is not None:
        apply_limits(room, level, limits)       # set while unplaced, so placement never sees 0 height
    if not free:
        return False, "no free region on this level and phase ({} regions, all occupied)" \
            .format(len(circuits))

    # Strategy A: place in any free region, then move the point to the stored location
    st = SubTransaction(doc)
    st.Start()
    ok, a_why = False, ""
    try:
        doc.Create.NewRoom(room, free[0])
        if limits is not None:
            apply_limits(room, level, limits)
        doc.Regenerate()
        _move_to(room, pt)
        doc.Regenerate()
        ok, a_why = _contains(room, pt)
    except Exception as e:
        ok, a_why = False, _err(e)
    if ok:
        st.Commit()
        return True, ""
    st.RollBack()

    # Strategy B: try each free region until one contains the stored point
    tried, outside, first_error = 0, 0, None
    for c in doc.get_PlanTopology(level, phase).Circuits:
        if c.IsRoomLocated:
            continue
        tried += 1
        st = SubTransaction(doc)
        st.Start()
        ok = False
        try:
            doc.Create.NewRoom(room, c)
            if limits is not None:
                apply_limits(room, level, limits)
            doc.Regenerate()
            ok, why = _contains(room, pt)
            if ok:
                _move_to(room, pt)
            elif why.startswith("stored point"):
                outside += 1
            elif first_error is None:
                first_error = why
        except Exception as e:
            ok = False
            if first_error is None:
                first_error = _err(e)
        if ok:
            st.Commit()
            return True, ""
        st.RollBack()

    reason = "A: {} | B: tried {} free regions, {} did not contain the point".format(
        a_why or "failed", tried, outside)
    if first_error:
        reason += ", others raised errors (first: {})".format(first_error)
    return False, reason


# ============================================================ candidates
class Candidate(object):
    def __init__(self, doc, uid, rec, kind):
        self.uid, self.rec, self.kind = uid, rec, kind
        prm = rec.get("params") or {}
        self.number = (prm.get("bip:ROOM_NUMBER") or {}).get("v") or ""
        self.name = (prm.get("bip:ROOM_NAME") or {}).get("v") or ""
        lv = doc.GetElement(rec["level_uid"]) if rec.get("level_uid") else None
        self.level_name = lv.Name if isinstance(lv, Level) else "(missing level)"
        self.data_age = rec.get("last_updated") or ""
        self.can_place = False
        self.check_failed = False       # trial placement failed: warn, don't block
        self.can_rebuild_unplaced = False
        self.note = ""
        self.number_note = ""
        self.height_note = ""

    def status_tip(self):
        r = self.rec
        if self.kind == "Deleted":
            return "Deleted {} by {}  ({})".format(r.get("status_changed") or "?",
                                                   r.get("deleted_by") or "unknown user",
                                                   r.get("deleted_in") or "")
        return "Unplaced {} - last modified by {}".format(r.get("status_changed") or "?",
                                                          r.get("last_modified_by") or "unknown")


def collect_candidates(doc, reg):
    in_use = {}
    for r in _rooms(doc):
        in_use.setdefault(r.Number or "", set()).add(r.UniqueId)
    out = []
    for uid, rec in reg.rooms.items():
        status = rec.get("status")
        if status == "Unplaced":
            el = doc.GetElement(uid)
            if not isinstance(el, Room) or el.Location is not None:
                continue
            c = Candidate(doc, uid, rec, "Unplaced")
            c.number, c.name = el.Number or "", _room_name(el)
        elif status == "Deleted":
            if doc.GetElement(uid) is not None:
                continue
            c = Candidate(doc, uid, rec, "Deleted")
        else:
            continue
        if c.number and (in_use.get(c.number, set()) - set([uid])):
            c.number_note = "number {} already in use".format(c.number)
        out.append(c)
    out.sort(key=lambda c: (0 if c.kind == "Unplaced" else 1, c.level_name, c.number))
    return out


def evaluate(doc, c):
    """Hard blocks only where restore is impossible; a failed trial is a warning."""
    level, phase, pt = resolve(doc, c.rec)
    c.can_rebuild_unplaced = (c.kind == "Deleted" and phase is not None)
    if phase is None:
        c.note = "Phase no longer exists"
        return
    if level is None:
        c.note = "Level no longer exists"
        return
    if pt is None:
        c.note = "No recorded location"
        return
    room = None
    if c.kind == "Unplaced":
        room = doc.GetElement(c.uid)
        owner = owner_if_other(doc, room.Id)
        if owner:
            c.note = "Owned by {}".format(owner)
            return
    occ = occupied_by(doc, level, phase, pt, c.uid)
    if occ is not None:
        c.note = "Location occupied by room {}".format(occ.Number or "(no number)")
        return
    if room is None:
        room = doc.Create.NewRoom(phase)
    limits, c.height_note = resolve_limits(doc, c.rec, level)
    ok, why = place_in_region(doc, room, level, phase, pt, limits)
    if ok:
        c.can_place = True
        c.note = "Ready"
    else:
        c.check_failed = True
        c.note = "Check could not place it - restore will try again ({})".format(why)
        _log("Check failed for {} {}: {}".format(c.number, c.uid, why))


def dry_run(doc, cands):
    """Simulates the restore in order, so candidates competing for a region show it."""
    t = Transaction(doc, "Room Register - dry run")
    t.Start()
    try:
        for c in cands:
            try:
                evaluate(doc, c)
            except Exception as e:
                c.can_place = False
                c.check_failed = True
                c.note = "Check raised an error - restore will try again ({})".format(_err(e))
                _log("Check error for {}: {}".format(c.uid, traceback.format_exc()))
    except Exception:
        _log("Dry run: " + traceback.format_exc())
    t.RollBack()      # dry run: every trial placement is discarded on purpose


# =============================================================== restore
class _Skip(Exception):
    pass


def restore_one(doc, c, allow_unplaced):
    res = {"c": c, "ok": False, "placed": False, "uid": None,
           "msg": "", "missing": [], "failed": []}
    level, phase, pt = resolve(doc, c.rec)
    st = SubTransaction(doc)
    st.Start()
    try:
        if c.kind == "Unplaced":
            room = doc.GetElement(c.uid)
            if room is None or room.Location is not None:
                raise _Skip("already placed or no longer in the model")
            if level is None or phase is None or pt is None:
                raise _Skip(c.note or "missing level, phase or location")
            occ = occupied_by(doc, level, phase, pt, c.uid)
            if occ is not None:
                raise _Skip("location occupied by room {}".format(occ.Number or "(no number)"))
            limits, height_note = resolve_limits(doc, c.rec, level)
            ok, why = place_in_region(doc, room, level, phase, pt, limits)
            if not ok:
                raise _Skip("could not place: {}".format(why))
            res.update(ok=True, placed=True, uid=room.UniqueId,
                       msg="Placed back at its last location" +
                           (" ({})".format(height_note) if height_note else ""))
        else:
            if phase is None:
                raise _Skip("phase no longer exists")
            room = doc.Create.NewRoom(phase)
            placed, why = False, "no level or location recorded"
            if level is not None and pt is not None:
                occ = occupied_by(doc, level, phase, pt)
                if occ is not None:
                    why = "location occupied by room {}".format(occ.Number or "(no number)")
                else:
                    limits, _ = resolve_limits(doc, c.rec, level)
                    placed, why = place_in_region(doc, room, level, phase, pt, limits)
            if not placed and not allow_unplaced:
                raise _Skip("could not place: {}".format(why))
            res["missing"], res["failed"] = write_params(doc, room, c.rec.get("params") or {})
            res.update(ok=True, placed=placed, uid=room.UniqueId,
                       msg="Rebuilt at its last location" if placed
                       else "Rebuilt unplaced ({}) - place it manually".format(why))
        st.Commit()
    except _Skip as s:
        st.RollBack()
        res["msg"] = str(s)
    except Exception as e:
        st.RollBack()
        res["msg"] = "Error: {}".format(_err(e))
        _log("Restore {}: {}".format(c.uid, traceback.format_exc()))
    return res


def run_restore(doc, reg, selected, allow_unplaced):
    selected = sorted(selected, key=lambda c: 0 if c.kind == "Unplaced" else 1)

    blocked = set()
    if doc.IsWorkshared:
        ids = List[ElementId]()
        for c in selected:
            if c.kind == "Unplaced":
                el = doc.GetElement(c.uid)
                if el is not None:
                    ids.Add(el.Id)
        if ids.Count:
            try:
                got = set(id_value(i) for i in WorksharingUtils.CheckoutElements(doc, ids))
                for c in selected:
                    el = doc.GetElement(c.uid) if c.kind == "Unplaced" else None
                    if el is not None and id_value(el.Id) not in got:
                        blocked.add(c.uid)
            except Exception:
                _log("Checkout: " + traceback.format_exc())

    results = []
    t = Transaction(doc, "Room Register - Restore rooms")
    t.Start()
    try:
        for c in selected:
            if c.uid in blocked:
                results.append({"c": c, "ok": False, "placed": False, "uid": None,
                                "msg": "could not borrow the room (owned by another user)",
                                "missing": [], "failed": []})
                continue
            results.append(restore_one(doc, c, allow_unplaced))
        status = t.Commit()
    except Exception as e:
        t.RollBack()
        return None, "Restore failed, nothing was changed:\n\n{}".format(e)
    if status != TransactionStatus.Committed:
        return None, "Revit did not commit the restore. Nothing was changed."

    update_register(doc, reg, results)
    return results, None


def remove_records(reg, uids, user=None):
    """Permanently drops Deleted records (tombstones) from the register.

    Only status Deleted is ever removed: unplaced rooms still exist in the model and
    would be re-registered by the next scan anyway. If the save fails, the records
    are put back so memory and file stay in step.
    """
    removed = {}
    for uid in uids:
        rec = reg.rooms.get(uid)
        if rec is not None and rec.get("status") == "Deleted":
            removed[uid] = reg.rooms.pop(uid)
    if not removed:
        return 0
    try:
        reg.save()
    except Exception:
        reg.rooms.update(removed)
        raise
    numbers = [((r.get("params") or {}).get("bip:ROOM_NUMBER") or {}).get("v") or "?"
               for r in removed.values()]
    _log("{} removed {} deleted room(s) from {}: {}".format(
        user or "unknown user", len(removed), os.path.basename(reg.path), ", ".join(numbers)))
    return len(removed)


def update_register(doc, reg, results):
    user = doc.Application.Username
    for r in results:
        if not r["ok"]:
            continue
        c = r["c"]
        room = doc.GetElement(r["uid"])
        if room is None:
            continue
        reg.upsert(doc, room, "live", user)
        if c.kind == "Deleted":
            new = reg.rooms.get(room.UniqueId)
            if new is not None:
                new["restored_from"] = c.uid
                if not r["placed"]:
                    # keep the old location so it can be placed later as an Unplaced room
                    new["location"] = c.rec.get("location")
                    new["level_uid"] = new.get("level_uid") or c.rec.get("level_uid")
            old = reg.rooms.get(c.uid)
            if old is not None:
                old["status"] = "Restored"
                old["restored_to"] = room.UniqueId
                old["status_changed"] = _now()
    reg.dirty = True
    try:
        reg.save()
    except Exception:
        _log("Save after restore: " + traceback.format_exc())
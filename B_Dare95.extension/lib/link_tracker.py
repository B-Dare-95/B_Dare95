# -*- coding: utf-8 -*-
"""
BIM Brother - Links engine (B_Dare95)

Same snapshot-and-diff engine as change_tracker, pointed at linked documents.

  Storage, under %LOCALAPPDATA%\\B_Dare95\\ChangeTracker\\Links :
      <HostTitle>__<hostkey>.monitored.json   which links this host monitors (+ last picked)
      <LinkTitle>__<linkkey>.json             link register: meta + change records
      <LinkTitle>__<linkkey>.snapshot.json    link baseline

  A link register belongs to the linked MODEL, not to the host: if two of your
  projects link the same model, they share one register, so a change you have
  already seen through one host is not reported again through the other.

  Fingerprints are taken in the link's own coordinates, so moving the link
  instance in the host never reports every element as moved.

  Scanning is ON DEMAND only. Nothing runs while a host opens or a link reloads:
  a link whose document version differs from its last scan is flagged "stale",
  and stale links are scanned when the BIM Brother Links report asks for it
  (the link on screen when the report opens, a picked link, or Scan all stale).
  Checking a version is a few milliseconds; a full scan of a large link is minutes.
"""

import clr
clr.AddReference("System")
clr.AddReference("RevitAPI")

import os
import time
from datetime import datetime

from System.IO import File, Directory

from Autodesk.Revit.DB import Document, FilteredElementCollector, RevitLinkInstance

import change_tracker as ct


LINK_DIR = os.path.join(ct.REGISTER_DIR, "Links")

TRIGGER_REPORT = u"New version found"
TRIGGER_MONITOR = u"Monitoring started"
TRIGGER_MANUAL = ct.TRIGGER_MANUAL

_ENV_KEY = "B_DARE95_BIM_BROTHER_LINK_HANDLERS"


# =============================================================================
# PATHS
# =============================================================================
def _ensure_dir():
    if not Directory.Exists(LINK_DIR):
        Directory.CreateDirectory(LINK_DIR)


def _find_or_rename(key, suffix, wanted):
    """Keep files findable by key when the title in their name changes."""
    if File.Exists(wanted):
        return
    for found in Directory.GetFiles(LINK_DIR, "*__" + key + suffix):
        try:
            File.Move(found, wanted)
            old_snap = found[:-len(suffix)] + ".snapshot.json"
            new_snap = wanted[:-len(suffix)] + ".snapshot.json"
            if suffix == ".json" and File.Exists(old_snap) and not File.Exists(new_snap):
                File.Move(old_snap, new_snap)
        except Exception:
            ct.log_error("link file rename")
        break


def monitored_path(host):
    key, title = ct.doc_identity(host)
    _ensure_dir()
    path = os.path.join(LINK_DIR, u"{0}__{1}.monitored.json".format(ct._safe(title), key))
    _find_or_rename(key, ".monitored.json", path)
    return path


def link_paths(link_doc):
    """(register_path, snapshot_path, key, title) for a linked document."""
    key, title = ct.doc_identity(link_doc)
    _ensure_dir()
    base = os.path.join(LINK_DIR, u"{0}__{1}".format(ct._safe(title), key))
    _find_or_rename(key, ".json", base + ".json")
    return base + ".json", base + ".snapshot.json", key, title


# =============================================================================
# MONITORED-LINK REGISTRY (per host)
# =============================================================================
def load_monitored(host):
    data = ct._read_json(monitored_path(host)) or {}
    data.setdefault("links", {})
    return data


def save_monitored(host, data):
    data["host_title"] = ct.doc_identity(host)[1]
    ct._write_json(monitored_path(host), data)


def set_last_picked(host, type_uid):
    data = load_monitored(host)
    data["last"] = type_uid
    save_monitored(host, data)


def stop_monitoring(host, type_uid):
    """Stops automatic refreshes for this host. The link register itself is kept."""
    data = load_monitored(host)
    data["links"].pop(type_uid, None)
    if data.get("last") == type_uid:
        data["last"] = None
    save_monitored(host, data)


# =============================================================================
# LOADED LINKS
# =============================================================================
def list_links(host):
    """Loaded, top-level links of the host, one entry per link type, sorted by name."""
    monitored = load_monitored(host)["links"]
    by_type = {}
    for inst in FilteredElementCollector(host).OfClass(RevitLinkInstance):
        try:
            ltype = host.GetElement(inst.GetTypeId())
            if ltype is None:
                continue
            try:
                if ltype.IsNestedLink:
                    continue
            except Exception:
                pass
            link_doc = inst.GetLinkDocument()
            if link_doc is None:                     # unloaded: never treat as "everything deleted"
                continue
            uid = ltype.UniqueId
            if uid not in by_type:
                info = monitored.get(uid) or {}
                version = _version(link_doc)
                stale = False
                if uid in monitored:
                    stored = info.get("version")
                    if "version" not in info:            # entries written before versions were stored
                        stored = _register_version(link_doc)
                    stale = version is None or version != stored
                by_type[uid] = {
                    "type_uid": uid,
                    "type_id": ct.eid_value(ltype.Id),
                    "name": ct._name(ltype) or link_doc.Title,
                    "doc": link_doc,
                    "instances": [],
                    "monitored": uid in monitored,
                    "last_refresh": info.get("last_refresh"),
                    "version": version,
                    "stale": stale,
                }
            by_type[uid]["instances"].append(inst)
        except Exception:
            ct.log_error("list links")
    return sorted(by_type.values(), key=lambda l: l["name"].lower())


def _register_version(link_doc):
    try:
        reg = ct._read_json(link_paths(link_doc)[0]) or {}
        return reg.get("version")
    except Exception:
        return None


def _version(link_doc):
    """Document version GUID (Revit 2023+), or None if unavailable."""
    try:
        return str(Document.GetDocumentVersion(link_doc).VersionGUID)
    except Exception:
        return None


# =============================================================================
# REFRESH
# =============================================================================
def refresh_link(host, link, trigger, force=False):
    """
    Scan the link, diff against its baseline, record changes, save.
    Returns (register, scanned). scanned is False when the version gate skipped the scan.
    """
    t0 = time.time()
    link_doc = link["doc"]
    reg_path, snap_path, key, title = link_paths(link_doc)
    version = _version(link_doc)

    reg = ct._read_json(reg_path)
    if reg is not None and not force and version and reg.get("version") == version:
        return reg, False

    old_snap = None
    if reg is None:
        reg = {"schema": ct.SCHEMA, "doc_key": key, "created": ct._iso(datetime.now()), "changes": {}}
    else:
        try:
            old_snap = ct._read_json(snap_path)
        except Exception:
            ct.log_error("link snapshot unreadable, rebuilding baseline")

    new_snap = ct.collect(link_doc, old_snap)
    now = datetime.now()
    changes = reg.setdefault("changes", {})
    counts = dict((k, 0) for k in ct.KIND_ORDER)
    workshared = link_doc.IsWorkshared

    if old_snap is not None:
        for uid, nfp in new_snap.items():
            ofp = old_snap.get(uid)
            if ofp is None:
                kinds, details, summary = [ct.NEW], [], u"New element"
            else:
                kinds, details, summary = ct.compare(ofp, nfp)
                if not kinds:
                    continue
            modified = None
            if workshared:                           # nobody in this session edits a link: tooltip only
                el = link_doc.GetElement(uid)
                if el is not None:
                    modified = ct._tooltip(link_doc, el.Id, "LastChangedBy")
            ct._store(changes, ct._record(uid, nfp, kinds, details, summary,
                                          nfp.get("cr"), modified, now, trigger))
            for k in kinds:
                counts[k] += 1

        closed = ct._closed_worksets(link_doc)
        for uid, ofp in old_snap.items():
            if uid in new_snap:
                continue
            if ofp.get("w", -1) in closed:
                new_snap[uid] = ofp
                continue
            details = [[u"Last known type", u"", u"{0}: {1}".format(ofp.get("f"), ofp.get("t"))]]
            ct._store(changes, ct._record(uid, ofp, [ct.DELETED], details, u"Element deleted",
                                          ofp.get("cr"), None, now, trigger))
            counts[ct.DELETED] += 1

    ct.purge_expired(reg, now)
    reg["doc_title"] = title
    reg["doc_path"] = link_doc.PathName
    reg["version"] = version
    reg["last_refresh"] = {
        "time": ct._iso(now), "trigger": trigger, "user": host.Application.Username,
        "host": ct.doc_identity(host)[1], "scanned": len(new_snap),
        "seconds": round(time.time() - t0, 1), "counts": counts,
    }
    ct._write_json(reg_path, reg)
    ct._write_json(snap_path, new_snap)

    summary = dict(reg["last_refresh"])
    summary["seconds_total"] = round(time.time() - t0, 1)    # scan + saving the files
    data = load_monitored(host)
    data["links"][link["type_uid"]] = {
        "name": link["name"], "doc_key": key, "version": version,
        "register": os.path.basename(reg_path), "last_refresh": summary,
    }
    save_monitored(host, data)
    link["version"], link["stale"], link["last_refresh"] = version, False, summary
    return reg, True


def start_monitoring(host, link):
    reg, _ = refresh_link(host, link, TRIGGER_MONITOR, force=True)
    set_last_picked(host, link["type_uid"])
    return reg


def load_link_register(link):
    """(register, register_path). Purges expired records on load."""
    reg_path = link_paths(link["doc"])[0]
    reg = ct._read_json(reg_path)
    if reg is not None and ct.purge_expired(reg):
        ct._write_json(reg_path, reg)
    return reg, reg_path


# =============================================================================
# EVENT ARMING (called from startup.py)
# =============================================================================
def arm(app):
    """
    Nothing is subscribed any more: scanning is on demand from the report.
    This only detaches handlers an older version may have attached in this session,
    so the startup.py block can stay as it is.
    """
    from pyrevit.coreutils import envvars

    old = envvars.get_pyrevit_env_var(_ENV_KEY)
    if old is not None:
        try:
            app.DocumentOpened -= old[0]
        except Exception:
            pass
        try:
            app.DocumentChanged -= old[1]
        except Exception:
            pass
    envvars.set_pyrevit_env_var(_ENV_KEY, None)
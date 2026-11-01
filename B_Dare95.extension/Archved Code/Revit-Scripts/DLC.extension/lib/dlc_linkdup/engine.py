# -*- coding: utf-8 -*-
"""DLC Link Duplicates - pure logic (no Revit imports).

Everything here is plain Python so it can be unit-tested outside Revit.
Compatible with IronPython 2.7 and CPython 3.
"""
from __future__ import print_function, division

import hashlib
import json
import os
import re
import time

MM_PER_FT = 304.8
EPS = 1e-9


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------
def mm_to_ft(mm):
    return float(mm) / MM_PER_FT


# ---------------------------------------------------------------------------
# Bounding boxes  (a box is ((minx, miny, minz), (maxx, maxy, maxz)))
# ---------------------------------------------------------------------------
def box_corners(bmin, bmax):
    xs = (bmin[0], bmax[0])
    ys = (bmin[1], bmax[1])
    zs = (bmin[2], bmax[2])
    return [(x, y, z) for x in xs for y in ys for z in zs]


def transform_box(bmin, bmax, point_fn):
    """Axis-aligned box that encloses the 8 transformed corners.
    point_fn maps an (x, y, z) tuple to an (x, y, z) tuple."""
    pts = [point_fn(c) for c in box_corners(bmin, bmax)]
    return (
        (min(p[0] for p in pts), min(p[1] for p in pts), min(p[2] for p in pts)),
        (max(p[0] for p in pts), max(p[1] for p in pts), max(p[2] for p in pts)),
    )


def expand_box(bmin, bmax, tol):
    return ((bmin[0] - tol, bmin[1] - tol, bmin[2] - tol),
            (bmax[0] + tol, bmax[1] + tol, bmax[2] + tol))


def boxes_overlap(amin, amax, bmin, bmax):
    for i in range(3):
        if amax[i] < bmin[i] or bmax[i] < amin[i]:
            return False
    return True


def box_volume(bmin, bmax):
    v = 1.0
    for i in range(3):
        d = bmax[i] - bmin[i]
        if d <= 0:
            return 0.0
        v *= d
    return v


def box_overlap_volume(amin, amax, bmin, bmax):
    v = 1.0
    for i in range(3):
        d = min(amax[i], bmax[i]) - max(amin[i], bmin[i])
        if d <= 0:
            return 0.0
        v *= d
    return v


# ---------------------------------------------------------------------------
# Spatial index - uniform XY grid so we never test every host vs every link
# ---------------------------------------------------------------------------
class GridIndex(object):
    def __init__(self, cell_size):
        if cell_size <= 0:
            raise ValueError("cell_size must be positive")
        self.cell = float(cell_size)
        self._cells = {}
        self._boxes = {}

    def _range(self, bmin, bmax):
        c = self.cell
        x0, x1 = int(bmin[0] // c), int(bmax[0] // c)
        y0, y1 = int(bmin[1] // c), int(bmax[1] // c)
        return x0, x1, y0, y1

    def insert(self, key, bmin, bmax):
        self._boxes[key] = (bmin, bmax)
        x0, x1, y0, y1 = self._range(bmin, bmax)
        for ix in range(x0, x1 + 1):
            for iy in range(y0, y1 + 1):
                self._cells.setdefault((ix, iy), []).append(key)

    def query(self, bmin, bmax):
        """Keys whose box overlaps (bmin, bmax) - exact box test, no dupes."""
        x0, x1, y0, y1 = self._range(bmin, bmax)
        seen = set()
        out = []
        for ix in range(x0, x1 + 1):
            for iy in range(y0, y1 + 1):
                for key in self._cells.get((ix, iy), ()):
                    if key in seen:
                        continue
                    seen.add(key)
                    kmin, kmax = self._boxes[key]
                    if boxes_overlap(bmin, bmax, kmin, kmax):
                        out.append(key)
        return out

    def __len__(self):
        return len(self._boxes)


# ---------------------------------------------------------------------------
# Duplicate decision
# ---------------------------------------------------------------------------
def overlap_ratio(host_volume, overlap_volumes):
    """Share of the host element's volume covered by link geometry (0..1).
    Contributions are summed and capped at 1.0 (link elements that overlap
    each other could otherwise push a partial clash past 100%)."""
    if host_volume is None or host_volume <= EPS:
        return 0.0
    total = 0.0
    for v in overlap_volumes:
        if v is not None and v > 0:
            total += v
    r = total / host_volume
    if r > 1.0:
        r = 1.0
    return r


def classify(ratio, threshold, partial_min):
    """'duplicate' | 'partial' | 'clear'."""
    if ratio >= threshold - EPS:
        return "duplicate"
    if ratio >= partial_min - EPS and ratio > EPS:
        return "partial"
    return "clear"


def pct(ratio):
    return "%d%%" % int(round(ratio * 100.0))


# ---------------------------------------------------------------------------
# Delete planning
# ---------------------------------------------------------------------------
SKIP_MISSING = "Already deleted / not found"
SKIP_GROUP = "Inside a model group - ungroup or edit the group first"
SKIP_OWNED = "Owned by another user - ask them to sync and relinquish"
SKIP_HOSTS = "Hosts doors/windows/openings - skipped by your choice"
SKIP_PINNED = "Pinned - skipped by your choice"


def pinned_candidates(rows, wanted_ids):
    """Wanted ids that are pinned AND would otherwise be deletable - the only
    ones worth asking about (grouped/owned ones are skipped anyway)."""
    wanted = set(wanted_ids)
    return [r["id"] for r in rows if r["id"] in wanted and r.get("exists", True)
            and r.get("pinned") and not r.get("in_group")
            and not r.get("owned_by_other")]


def plan_delete(rows, wanted_ids, skip_hosting, skip_pinned=False):
    """rows: dicts with keys id, exists, in_group, owned_by_other, pinned, inserts.
    Returns (ids_to_delete, [(id, reason), ...])."""
    wanted = set(wanted_ids)
    to_delete = []
    skipped = []
    for r in rows:
        if r["id"] not in wanted:
            continue
        if not r.get("exists", True):
            skipped.append((r["id"], SKIP_MISSING))
        elif r.get("in_group"):
            skipped.append((r["id"], SKIP_GROUP))
        elif r.get("owned_by_other"):
            skipped.append((r["id"], SKIP_OWNED))
        elif skip_pinned and r.get("pinned"):
            skipped.append((r["id"], SKIP_PINNED))
        elif skip_hosting and r.get("inserts", 0) > 0:
            skipped.append((r["id"], SKIP_HOSTS))
        else:
            to_delete.append(r["id"])
    return to_delete, skipped


def selected_duplicates(detected_ids, selection_ids):
    """Selection filtered to detected duplicates, in detected order."""
    sel = set(selection_ids)
    return [i for i in detected_ids if i in sel]


# ---------------------------------------------------------------------------
# Results store (JSON in %APPDATA%) - written atomically
# ---------------------------------------------------------------------------
STORE_VERSION = 1


def safe_name(text):
    text = text or "untitled"
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_")
    return (text or "untitled")[:120]


def store_dir(base=None):
    if base is None:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "DLC", "LinkDuplicates")


def store_path(doc_key, base=None):
    """Readable prefix + short hash, so long ACC paths never collide."""
    key = doc_key or "untitled"
    digest = hashlib.md5(key.encode("utf-8")).hexdigest()[:10]
    name = safe_name(os.path.basename(key.replace("\\", "/")))[:60]
    return os.path.join(store_dir(base), "%s_%s.json" % (name, digest))


def save_results(path, data):
    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    data = dict(data)
    data["version"] = STORE_VERSION
    data.setdefault("saved", time.strftime("%Y-%m-%d %H:%M:%S"))
    text = json.dumps(data, indent=1, sort_keys=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(text)
    # verify the new file before touching the old one
    with open(tmp, "r") as f:
        json.loads(f.read())
    if os.path.exists(path):
        bak = path + ".bak"
        if os.path.exists(bak):
            os.remove(bak)
        os.rename(path, bak)
        os.rename(tmp, path)
        os.remove(bak)
    else:
        os.rename(tmp, path)
    return path


def load_results(path):
    """Returns dict or None (missing / unreadable / wrong version)."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            data = json.loads(f.read())
    except Exception:
        return None
    if not isinstance(data, dict) or data.get("version") != STORE_VERSION:
        return None
    if not isinstance(data.get("items"), list):
        return None
    return data


def remove_ids(data, ids):
    gone = set(ids)
    data = dict(data)
    data["items"] = [it for it in data.get("items", []) if it.get("id") not in gone]
    return data


# ---------------------------------------------------------------------------
# User preferences (last category choice etc.)
# ---------------------------------------------------------------------------
def prefs_path(base=None):
    return os.path.join(store_dir(base), "_prefs.json")


def load_prefs(base=None):
    p = prefs_path(base)
    try:
        with open(p, "r") as f:
            data = json.loads(f.read())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_prefs(prefs, base=None):
    data = dict(prefs)
    data["items"] = []  # reuse the atomic writer's format check
    return save_results(prefs_path(base), data)

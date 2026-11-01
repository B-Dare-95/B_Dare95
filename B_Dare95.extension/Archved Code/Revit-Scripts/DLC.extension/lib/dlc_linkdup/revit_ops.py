# -*- coding: utf-8 -*-
"""DLC Link Duplicates - Revit API layer (geometry, overrides, deletion).
IronPython 2.7 / Revit 2025-2026."""
from __future__ import print_function, division

from Autodesk.Revit.DB import (
    BooleanOperationsType, BooleanOperationsUtils, BuiltInCategory,
    CheckoutStatus, Color, ElementId, FillPatternElement,
    FilteredElementCollector, GeometryInstance, HostObject,
    OverrideGraphicSettings, Options, RevitLinkInstance, Solid, SolidUtils,
    SubTransaction, Transaction, Transform, ViewDetailLevel,
    WorksharingUtils, XYZ,
)
import Autodesk.Revit.DB as DB

from dlc_linkdup import engine

MIN_SOLID_VOL = 1e-7  # ft3


# ---------------------------------------------------------------------------
# ElementId helpers (Revit 2024+ uses Int64 .Value; IntegerValue is gone in 2026)
# ---------------------------------------------------------------------------
def eid_int(eid):
    v = getattr(eid, "Value", None)
    if v is None:
        v = eid.IntegerValue
    return int(v)


def make_eid(i):
    try:
        from System import Int64
        return ElementId(Int64(int(i)))
    except Exception:
        return ElementId(int(i))


def invalid_id():
    return ElementId.InvalidElementId


# ---------------------------------------------------------------------------
# Element info
# ---------------------------------------------------------------------------
def element_name(el):
    try:
        return DB.Element.Name.GetValue(el)
    except Exception:
        try:
            return el.Name
        except Exception:
            return ""


def describe(doc, el):
    cat = el.Category.Name if el.Category is not None else "?"
    tname = ""
    try:
        t = doc.GetElement(el.GetTypeId())
        if t is not None:
            tname = element_name(t)
    except Exception:
        pass
    lvl = ""
    try:
        lid = el.LevelId
        if lid is not None and lid != invalid_id():
            lv = doc.GetElement(lid)
            if lv is not None:
                lvl = element_name(lv)
    except Exception:
        pass
    return {"category": cat, "type": tname, "level": lvl}


def bic(name):
    return getattr(BuiltInCategory, name)


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------
def loaded_links(doc):
    out = []
    for li in FilteredElementCollector(doc).OfClass(RevitLinkInstance):
        try:
            if li.GetLinkDocument() is not None:
                out.append(li)
        except Exception:
            pass
    return out


def link_label(li):
    return element_name(li) or ("Link %d" % eid_int(li.Id))


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------
def geometry_options():
    opts = Options()
    opts.DetailLevel = ViewDetailLevel.Fine
    opts.IncludeNonVisibleObjects = False
    opts.ComputeReferences = False
    return opts


def _collect_solids(geo, out):
    if geo is None:
        return
    for g in geo:
        if isinstance(g, Solid):
            try:
                if g.Volume > MIN_SOLID_VOL:
                    out.append(g)
            except Exception:
                pass
        elif isinstance(g, GeometryInstance):
            _collect_solids(g.GetInstanceGeometry(), out)


def element_solids(el, opts, transform=None):
    out = []
    try:
        _collect_solids(el.get_Geometry(opts), out)
    except Exception:
        return []
    if transform is not None and not transform.IsIdentity:
        moved = []
        for s in out:
            try:
                moved.append(SolidUtils.CreateTransformed(s, transform))
            except Exception:
                pass
        out = moved
    return out


def element_box(el, transform=None):
    """World (host) axis-aligned bbox as tuples, or None."""
    bb = el.get_BoundingBox(None)
    if bb is None:
        return None
    bmin = (bb.Min.X, bb.Min.Y, bb.Min.Z)
    bmax = (bb.Max.X, bb.Max.Y, bb.Max.Z)
    # BoundingBoxXYZ may carry its own transform (e.g. family instances)
    try:
        bbt = bb.Transform
        if bbt is not None and not bbt.IsIdentity:
            bmin, bmax = engine.transform_box(bmin, bmax, _point_fn(bbt))
    except Exception:
        pass
    if transform is not None and not transform.IsIdentity:
        bmin, bmax = engine.transform_box(bmin, bmax, _point_fn(transform))
    return bmin, bmax


def _point_fn(t):
    def f(p):
        q = t.OfPoint(XYZ(p[0], p[1], p[2]))
        return (q.X, q.Y, q.Z)
    return f


def _jitters(step_ft):
    return [Transform.CreateTranslation(XYZ(step_ft, step_ft, step_ft)),
            Transform.CreateTranslation(XYZ(-step_ft, step_ft, -step_ft)),
            Transform.CreateTranslation(XYZ(step_ft * 2.5, -step_ft * 1.5, step_ft * 0.5))]


def intersect_volume(hs, ls, jitters):
    """Volume of hs n ls. Exact duplicates have coplanar faces, which makes
    Revit's boolean engine throw - so on failure we retry with the link solid
    nudged by a fraction of a millimetre. Returns (volume or None, method)."""
    for j in [None] + list(jitters):
        try:
            b = ls if j is None else SolidUtils.CreateTransformed(ls, j)
            r = BooleanOperationsUtils.ExecuteBooleanOperation(
                hs, b, BooleanOperationsType.Intersect)
            vol = r.Volume if r is not None else 0.0
            return max(vol, 0.0), ("solid" if j is None else "solid~")
        except Exception:
            continue
    return None, "failed"


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------
def collect_host_elements(doc, cat_names, view_id=None):
    out = []
    seen = set()
    for name in cat_names:
        if view_id is not None:
            col = FilteredElementCollector(doc, view_id)
        else:
            col = FilteredElementCollector(doc)
        for el in col.OfCategory(bic(name)).WhereElementIsNotElementType():
            k = eid_int(el.Id)
            if k not in seen:
                seen.add(k)
                out.append(el)
    return out


def build_link_index(link_doc, cat_names, transform, cell_ft):
    index = engine.GridIndex(cell_ft)
    elements = {}
    for name in cat_names:
        col = FilteredElementCollector(link_doc).OfCategory(bic(name))
        for el in col.WhereElementIsNotElementType():
            box = element_box(el, transform)
            if box is None:
                continue
            k = eid_int(el.Id)
            elements[k] = el
            index.insert(k, box[0], box[1])
    return index, elements


def detect(doc, link_inst, settings, host_view_id=None, progress=None):
    """Returns dict with 'rows' (one per host element that touches the link)
    and counters. A row: id, category, type, level, ratio, status, method,
    match (best link element description)."""
    link_doc = link_inst.GetLinkDocument()
    T = link_inst.GetTotalTransform()
    tol = engine.mm_to_ft(settings["BBOX_TOLERANCE_MM"])
    cell = engine.mm_to_ft(settings["GRID_CELL_MM"])
    jit = _jitters(engine.mm_to_ft(settings["COPLANAR_NUDGE_MM"]))
    opts = geometry_options()

    index, link_els = build_link_index(
        link_doc, settings["LINK_CATEGORIES"], T, cell)
    hosts = collect_host_elements(doc, settings["HOST_CATEGORIES"], host_view_id)

    link_solids = {}

    def solids_for(k):
        if k not in link_solids:
            link_solids[k] = element_solids(link_els[k], opts, T)
        return link_solids[k]

    stats = {"checked": len(hosts), "link_elements": len(link_els),
             "no_geometry": 0, "bbox_fallback": 0, "errors": 0}
    rows = []
    total = len(hosts)
    for n, el in enumerate(hosts):
        if progress is not None:
            if progress(n, total):
                stats["cancelled"] = True
                break
        try:
            box = element_box(el)
            if box is None:
                stats["no_geometry"] += 1
                continue
            qmin, qmax = engine.expand_box(box[0], box[1], tol)
            cands = index.query(qmin, qmax)
            if not cands:
                continue
            hsolids = element_solids(el, opts)
            hvol = sum(s.Volume for s in hsolids)
            if hvol <= MIN_SOLID_VOL:
                stats["no_geometry"] += 1
                continue
            hbox_vol = engine.box_volume(box[0], box[1])
            contributions = []
            best = (0.0, None)
            method = "solid"
            for k in cands:
                lsolids = solids_for(k)
                vol_k = 0.0
                failed = False
                for hs in hsolids:
                    for ls in lsolids:
                        v, m = intersect_volume(hs, ls, jit)
                        if v is None:
                            failed = True
                        else:
                            vol_k += v
                            if m == "solid~" and method == "solid":
                                method = "solid~"
                if failed:
                    # Last resort: bbox overlap, scaled to the solid volume.
                    # Only counts (and only flags 'bbox') when it adds overlap -
                    # a broken neighbour that merely touches must not taint it.
                    lbox = element_box(link_els[k], T)
                    if lbox is not None and hbox_vol > engine.EPS:
                        ov = engine.box_overlap_volume(box[0], box[1], lbox[0], lbox[1])
                        est = ov / hbox_vol * hvol
                        if est > vol_k + engine.EPS:
                            vol_k = est
                            method = "bbox"
                contributions.append(vol_k)
                if vol_k > best[0]:
                    best = (vol_k, k)
            if method == "bbox":
                stats["bbox_fallback"] += 1
            ratio = engine.overlap_ratio(hvol, contributions)
            status = engine.classify(ratio, settings["DUPLICATE_THRESHOLD"],
                                     settings["PARTIAL_REPORT_MIN"])
            if status == "clear":
                continue
            info = describe(doc, el)
            match = ""
            if best[1] is not None:
                li = describe(link_doc, link_els[best[1]])
                match = "%s: %s [%d]" % (li["category"], li["type"], best[1])
            row = {"id": eid_int(el.Id), "ratio": round(ratio, 4),
                   "status": status, "method": method, "match": match}
            row.update(info)
            rows.append(row)
        except Exception:
            stats["errors"] += 1
    return {"rows": rows, "stats": stats}


# ---------------------------------------------------------------------------
# Colour overrides
# ---------------------------------------------------------------------------
def view_supports_overrides(view):
    try:
        if view.IsTemplate:
            return False
        return bool(view.AreGraphicsOverridesAllowed())
    except Exception:
        return False


def solid_fill_id(doc):
    for fp in FilteredElementCollector(doc).OfClass(FillPatternElement):
        try:
            if fp.GetFillPattern().IsSolidFill:
                return fp.Id
        except Exception:
            pass
    return None


def highlight_settings(doc, rgb):
    c = Color(rgb[0], rgb[1], rgb[2])
    ogs = OverrideGraphicSettings()
    fid = solid_fill_id(doc)
    if fid is not None:
        ogs.SetSurfaceForegroundPatternId(fid)
        ogs.SetSurfaceForegroundPatternColor(c)
        ogs.SetCutForegroundPatternId(fid)
        ogs.SetCutForegroundPatternColor(c)
    ogs.SetProjectionLineColor(c)
    ogs.SetCutLineColor(c)
    return ogs


def apply_overrides(doc, view, ids, ogs):
    """ids: ints. Returns number applied. Caller owns the transaction."""
    n = 0
    for i in ids:
        eid = make_eid(i)
        if doc.GetElement(eid) is None:
            continue
        try:
            view.SetElementOverrides(eid, ogs)
            n += 1
        except Exception:
            pass
    return n


def clear_overrides(doc, view, ids):
    return apply_overrides(doc, view, ids, OverrideGraphicSettings())


# ---------------------------------------------------------------------------
# Deletion
# ---------------------------------------------------------------------------
def delete_facts(doc, ids):
    """Per-id facts the delete planner needs."""
    rows = []
    shared = doc.IsWorkshared
    for i in ids:
        eid = make_eid(i)
        el = doc.GetElement(eid)
        r = {"id": i, "exists": el is not None, "in_group": False,
             "owned_by_other": False, "pinned": False, "inserts": 0}
        if el is not None:
            try:
                r["pinned"] = bool(el.Pinned)
            except Exception:
                pass
            try:
                r["in_group"] = el.GroupId != invalid_id()
            except Exception:
                pass
            if shared:
                try:
                    st = WorksharingUtils.GetCheckoutStatus(doc, eid)
                    r["owned_by_other"] = (st == CheckoutStatus.OwnedByOtherUser)
                except Exception:
                    pass
            if isinstance(el, HostObject):
                try:
                    r["inserts"] = len(list(el.FindInserts(True, False, False, False)))
                except Exception:
                    pass
        rows.append(r)
    return rows


def delete_elements(doc, ids, title, unpin=False):
    """One transaction, one SubTransaction per element so a single failure
    never rolls back the batch. With unpin=True, pinned elements are unpinned
    inside their own SubTransaction first (rolled back too if the delete
    fails). Returns (deleted_ids, [(id, reason)], unpinned_count)."""
    deleted, failed = [], []
    unpinned = 0
    t = Transaction(doc, title)
    t.Start()
    try:
        for i in ids:
            st = SubTransaction(doc)
            st.Start()
            try:
                eid = make_eid(i)
                was_pinned = False
                el = doc.GetElement(eid)
                if unpin and el is not None and el.Pinned:
                    el.Pinned = False
                    was_pinned = True
                doc.Delete(eid)
                st.Commit()
                deleted.append(i)
                if was_pinned:
                    unpinned += 1
            except Exception as ex:
                st.RollBack()
                failed.append((i, "Revit refused: %s" % _short(ex)))
        t.Commit()
    except Exception:
        t.RollBack()
        raise
    return deleted, failed, unpinned


def _short(ex):
    msg = getattr(ex, "Message", None) or str(ex)
    msg = msg.strip().splitlines()[0] if msg.strip() else type(ex).__name__
    return msg[:160]

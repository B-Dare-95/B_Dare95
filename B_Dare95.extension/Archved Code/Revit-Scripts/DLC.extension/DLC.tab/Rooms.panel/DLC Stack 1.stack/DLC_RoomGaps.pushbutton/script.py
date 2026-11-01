# -*- coding: utf-8 -*-
"""DLC Room Gaps - show why rooms are 'Not Enclosed'.

Pick a level from the drop-down. The tool:
  * finds the unbounded (Not Enclosed / Redundant) rooms on that level,
  * finds open ends of room-bounding walls, curtain walls, room separation
    lines and columns - in this model AND in linked models,
  * draws the missing boundary segments in RED in the level's plan view,
  * draws elements that sit in a gap but do NOT bound rooms in ORANGE
    (Room Bounding off, too low, wrong phase, link not room bounding),
  * marks each unbounded room with a magenta X,
  * lists everything in the output window with clickable element IDs.

Markers are detail lines on line styles DLC_RoomGap*. Re-running replaces
them. To remove: select one marker > right-click > Select All Instances >
Visible in View > Delete.
Everything is one Undo step.
"""
__title__ = "Room\nGaps"
__author__ = "DLC"

import math
import os
import sys

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

# ==========================================================================
# SETTINGS - firm-level knobs. Lengths in millimetres.
# ==========================================================================
SETTINGS = {
    "version": "1.1.0",
    # ends closer than this (plus element half-width) count as joined
    "join_tolerance_mm": 10.0,
    # biggest gap reported as a missing segment; bigger -> "loose end"
    "max_gap_mm": 3000.0,
    # element counted on the level if it starts below level + this
    "scan_band_mm": 3000.0,
    # room separation lines accepted within this height of the level
    "separation_line_z_tol_mm": 300.0,
    # marker sizes (model units, so scale with the view)
    "marker_radius_mm": 250.0,
    "room_marker_mm": 600.0,
    # what counts as boundary
    "include_walls": True,
    "include_curtain_walls": True,
    "include_separation_lines": True,
    "include_columns": True,
    "include_links": True,
    "check_phase": True,
    "styles": {
        "gap": {"name": "DLC_RoomGap", "rgb": (255, 0, 0),
                "weight": 8, "pattern": "dash"},
        "cause": {"name": "DLC_RoomGap_NotBounding", "rgb": (255, 140, 0),
                  "weight": 8, "pattern": "dash"},
        "room": {"name": "DLC_RoomGap_Room", "rgb": (200, 0, 200),
                 "weight": 5, "pattern": None},
    },
}

TITLE = "DLC Room Gaps"
FT_PER_MM = 1.0 / 304.8
BIP = DB.BuiltInParameter
OK_PHASE_STATUS = ("Existing", "New", "Temporary")


# ==========================================================================
# small helpers
# ==========================================================================
def mm(v):
    return float(v) * FT_PER_MM


def to_mm(v):
    return float(v) * 304.8


def eid_int(eid):
    """ElementId -> int (Revit 2024+ .Value, older .IntegerValue)."""
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


def _bip(name):
    return getattr(BIP, name, None)


def get_param(el, bip_name, fallback_name=None):
    p = None
    bip = _bip(bip_name) if bip_name else None
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


def room_text(room):
    num = get_param(room, "ROOM_NUMBER")
    nam = get_param(room, "ROOM_NAME")
    num = (num.AsString() if num else "") or ""
    nam = (nam.AsString() if nam else "") or ""
    return ("%s %s" % (num, nam)).strip() or "(no number)"


def room_phase_id(room):
    p = get_param(room, "ROOM_PHASE")
    try:
        return p.AsElementId() if p else None
    except Exception:
        return None


# ==========================================================================
# levels / rooms / views
# ==========================================================================
def get_levels(doc):
    lv = list(DB.FilteredElementCollector(doc).OfClass(DB.Level)
              .WhereElementIsNotElementType())
    lv.sort(key=lambda l: l.ProjectElevation)
    return lv


def get_rooms(doc):
    return list(DB.FilteredElementCollector(doc)
                .OfCategory(DB.BuiltInCategory.OST_Rooms)
                .WhereElementIsNotElementType())


def room_state(room):
    """'ok' | 'unbounded' | 'unplaced'."""
    loc = room.Location
    if loc is None or not isinstance(loc, DB.LocationPoint):
        return "unplaced"
    try:
        if room.Area > 1e-6:
            return "ok"
    except Exception:
        pass
    return "unbounded"


def is_usable_plan(v):
    try:
        return (v is not None and isinstance(v, DB.ViewPlan)
                and not v.IsTemplate
                and v.ViewType == DB.ViewType.FloorPlan
                and v.GenLevel is not None)
    except Exception:
        return False


def pick_plan_view(doc, active, level):
    if is_usable_plan(active) and active.GenLevel.Id == level.Id:
        return active
    plans = [v for v in DB.FilteredElementCollector(doc).OfClass(DB.ViewPlan)
             if is_usable_plan(v) and v.GenLevel.Id == level.Id]
    if not plans:
        return None
    if len(plans) == 1:
        return plans[0]
    by_name = dict((elem_name(v), v) for v in plans)
    choice = forms.SelectFromList.show(
        sorted(by_name.keys()),
        title="%s - which plan view to draw in?" % TITLE,
        multiselect=False, button_name="Draw here")
    if not choice:
        return None
    return by_name.get(choice)


def view_phase_id(view):
    p = get_param(view, "VIEW_PHASE")
    try:
        return p.AsElementId() if p else None
    except Exception:
        return None


# ==========================================================================
# collecting boundary elements
# ==========================================================================
class Ctx(object):
    def __init__(self, level, phase_id):
        self.level_z = level.ProjectElevation
        ch = get_param(level, "LEVEL_ROOM_COMPUTATION_HEIGHT")
        comp = None
        try:
            comp = ch.AsDouble() if ch else None
        except Exception:
            comp = None
        if comp is None:
            comp = 4.0          # Revit default = 1219.2 mm
        self.comp_height = comp
        self.cut_z = self.level_z + comp
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
        r.append("top is below the room computation height "
                 "(%d mm above level)" % ch)
    if zmin > ctx.cut_z + ctx.eps:
        r.append("base is above the room computation height "
                 "(%d mm above level)" % ch)
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
    return ["not in view phase '%s' (status: %s)"
            % (elem_name(doc.GetElement(ctx.phase_id)), st)]


def _is_curtain(wall):
    try:
        return wall.WallType.Kind == DB.WallKind.Curtain
    except Exception:
        return False


def collect_source(src, t, source, is_link, link_rb_on, ctx, host_doc,
                   bounding, non_bounding):
    """Add Chains from one document (host or link) to the two lists."""
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

    def add(chain):
        (non_bounding if chain.reason else bounding).append(chain)

    # walls + curtain walls -------------------------------------------------
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
            if not is_link:
                reasons += _phase_reasons(w, ctx, host_doc)
            try:
                pts = wall_centre_points(w, loc)
                hw = float(w.Width) / 2.0
            except Exception:
                continue
            kind = core.KIND_CURTAIN if curtain else core.KIND_WALL
            add(core.Chain(_xy(t, pts), hw, kind, False, ref(w),
                           label(kind, w, elem_name(w.WallType)),
                           "; ".join(reasons) or None))

    # room separation lines -------------------------------------------------
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
            reasons = list(base)
            if not is_link:
                reasons += _phase_reasons(c, ctx, host_doc)
            add(core.Chain([(p.X, p.Y) for p in raw], 0.0,
                           core.KIND_SEPARATION, False, ref(c),
                           label("Separation line", c),
                           "; ".join(reasons) or None))

    # columns (architectural + structural) ---------------------------------
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
                if not is_link:
                    reasons += _phase_reasons(col, ctx, host_doc)
                add(core.Chain(_xy(t, corners), 0.0, core.KIND_COLUMN, True,
                               ref(col), label("Column", col),
                               "; ".join(reasons) or None))


def collect_all(doc, ctx):
    bounding, non_bounding, notes = [], [], []
    collect_source(doc, None, "this model", False, True, ctx, doc,
                   bounding, non_bounding)
    if not SETTINGS["include_links"]:
        return bounding, non_bounding, notes
    for li in DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkInstance):
        lt = doc.GetElement(li.GetTypeId())
        ldoc = li.GetLinkDocument()
        name = link_name(li, lt, ldoc)
        if ldoc is None:
            notes.append("Link '%s' is not loaded - its elements could not "
                         "be checked. Load it if rooms rely on it." % name)
            continue
        rb = param_int(lt, "WALL_ATTR_ROOM_BOUNDING", "Room Bounding")
        rb_on = (rb != 0)
        n_before = len(non_bounding)
        collect_source(ldoc, li.GetTotalTransform(), name, True, rb_on, ctx,
                       doc, bounding, non_bounding)
        n_off = len(non_bounding) - n_before
        if not rb_on and n_off:
            notes.append("Link '%s' has Room Bounding OFF - %d of its "
                         "elements are on this level and are ignored by "
                         "rooms. If rooms should use them: select the link "
                         "> Edit Type > tick Room Bounding." % (name, n_off))
    return bounding, non_bounding, notes


# ==========================================================================
# drawing
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
    removed = 0
    for i in ids:
        try:
            doc.Delete(i)
            removed += 1
        except Exception:
            pass
    return removed


class Painter(object):
    def __init__(self, doc, view, z):
        self.doc = doc
        self.view = view
        self.z = z
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

    def polyline(self, pts, closed, style):
        for i in range(len(pts) - 1):
            self.line(pts[i], pts[i + 1], style)
        if closed and len(pts) > 2:
            self.line(pts[-1], pts[0], style)


def draw(doc, view, level_z, result, unbounded):
    styles = dict((k, ensure_style(doc, v))
                  for k, v in SETTINGS["styles"].items())
    removed = clear_markers(doc, view)
    p = Painter(doc, view, level_z)
    r = mm(SETTINGS["marker_radius_mm"])
    drawn_causes = set()
    for g in result.gaps:
        p.circle(g.a, r, styles["gap"])
        if g.b is not None:
            if g.kind == core.GAP_PAIR:
                p.circle(g.b, r, styles["gap"])
            p.line(g.a, g.b, styles["gap"])
        else:
            p.circle(g.a, r * 1.6, styles["gap"])
        for nb in g.causes:
            if id(nb) in drawn_causes:
                continue
            drawn_causes.add(id(nb))
            p.polyline(nb.pts, nb.closed, styles["cause"])
    for room, pt, status in unbounded:
        p.cross(pt, mm(SETTINGS["room_marker_mm"]), styles["room"])
    return p, removed, styles


def lines_hidden(doc, view):
    try:
        lines = doc.Settings.Categories.get_Item(DB.BuiltInCategory.OST_Lines)
        if view.GetCategoryHidden(lines.Id):
            return True
        for sc in lines.SubCategories:
            if sc.Name.startswith("DLC_RoomGap") and \
                    view.GetCategoryHidden(sc.Id):
                return True
    except Exception:
        pass
    return False


# ==========================================================================
# report
# ==========================================================================
def elem_link(output, chain):
    if chain is None:
        return ""
    source, eid, is_link = chain.ref
    if is_link:
        return chain.label
    try:
        return "%s %s" % (output.linkify(eid), chain.label)
    except Exception:
        return chain.label


GAP_TEXT = {
    core.GAP_PAIR: "Missing boundary between two open ends",
    core.GAP_TO_ELEMENT: "Element stops short of another element",
    core.GAP_LOOSE: "Open end - nothing within max gap",
}


def report(output, level, view, unbounded, unplaced_n, result, notes,
           painter, removed, hidden):
    output.print_md("# %s - %s" % (TITLE, elem_name(level)))
    output.print_md("Drawn in view **%s**. Red = missing boundary, orange = "
                    "element in the gap that does not bound rooms, magenta X "
                    "= unbounded room. (v%s)"
                    % (elem_name(view), SETTINGS["version"]))

    if unbounded:
        rows = []
        for room, pt, status in unbounded:
            try:
                rid = output.linkify(room.Id)
            except Exception:
                rid = str(eid_int(room.Id))
            rows.append([rid, room_text(room), status])
        output.print_table(rows, columns=["Room", "Number / Name", "Status"],
                           title="Unbounded rooms (%d)" % len(unbounded))
    else:
        output.print_md("No unbounded rooms on this level.")
    if unplaced_n:
        output.print_md("_%d unplaced room(s) on this level were skipped - "
                        "they have no location to check._" % unplaced_n)

    if result.gaps:
        rows = []
        for i, g in enumerate(result.gaps):
            els = elem_link(output, g.chain_a)
            if g.chain_b is not None:
                els += "<br>" + elem_link(output, g.chain_b)
            causes = "<br>".join("%s: %s" % (elem_link(output, c), c.reason)
                                 for c in g.causes) or "-"
            near = "-"
            if g.nearest_room is not None:
                near = "%s (%.1f m)" % (room_text(g.nearest_room),
                                        to_mm(g.room_distance) / 1000.0)
            length = ("%d" % round(to_mm(g.length))) if g.b is not None \
                else "-"
            rows.append([str(i + 1), GAP_TEXT[g.kind], length, els, causes,
                         near])
        output.print_table(
            rows, columns=["#", "Problem", "Gap (mm)", "Elements",
                           "Likely cause (orange)", "Nearest unbounded room"],
            title="Boundary gaps (%d)" % len(result.gaps))
    else:
        output.print_md("**No open boundary ends found** on this level.")
        if unbounded:
            output.print_md(
                "If rooms still say Not Enclosed, check: rooms marked "
                "Redundant (two rooms in one space - delete one); "
                "boundaries in unloaded links; overlapping walls that are "
                "not joined; a gap smaller than %s mm (raise "
                "join_tolerance_mm in SETTINGS to ignore, lower it to "
                "catch)." % SETTINGS["join_tolerance_mm"])

    extra = list(notes)
    if hidden:
        extra.append("Lines (or DLC_RoomGap line styles) are hidden in this "
                     "view or its view template - markers exist but are not "
                     "visible. Turn them on in Visibility/Graphics.")
    if painter.failed:
        extra.append("%d marker(s) could not be drawn." % painter.failed)
    if removed:
        extra.append("%d old marker(s) from a previous run were removed."
                     % removed)
    extra.append("Checked %d bounding and %d non-bounding elements; "
                 "%d open end(s)." % (result.bounding_count,
                                      result.non_bounding_count,
                                      result.open_end_count))
    for n in extra:
        output.print_md("- %s" % n)


# ==========================================================================
# main
# ==========================================================================
def main():
    doc = revit.doc
    uidoc = revit.uidoc
    if doc.IsFamilyDocument:
        forms.alert("Open a project model, not a family.", title=TITLE)
        return

    levels = get_levels(doc)
    if not levels:
        forms.alert("This model has no levels.", title=TITLE)
        return
    all_rooms = get_rooms(doc)
    count = {}
    for r in all_rooms:
        if room_state(r) == "unbounded":
            k = eid_int(r.LevelId)
            count[k] = count.get(k, 0) + 1

    labels, by_label = [], {}
    for lv in levels:
        n = count.get(eid_int(lv.Id), 0)
        lab = "%s   (%d unbounded room%s)" % (elem_name(lv), n,
                                               "" if n == 1 else "s")
        labels.append(lab)
        by_label[lab] = lv
    default = None
    active = uidoc.ActiveView
    if is_usable_plan(active):
        for lab, lv in by_label.items():
            if lv.Id == active.GenLevel.Id:
                default = lab
    if default is None:
        for lab in labels:
            if count.get(eid_int(by_label[lab].Id), 0):
                default = lab
                break
    choice = forms.ask_for_one_item(labels, default=default or labels[0],
                                    prompt="Level to check:", title=TITLE)
    if not choice:
        return
    level = by_label[choice]

    view = pick_plan_view(doc, active, level)
    if view is None:
        forms.alert("No floor plan view found for level '%s'.\n\nCreate a "
                    "floor plan for this level, then run again."
                    % elem_name(level), title=TITLE)
        return

    phase_id = view_phase_id(view)
    ctx = Ctx(level, phase_id)

    unbounded, enclosed, unplaced_n = [], [], 0
    for r in all_rooms:
        if r.LevelId != level.Id:
            continue
        rp = room_phase_id(r)
        if phase_id is not None and rp is not None and rp != phase_id:
            continue
        st = room_state(r)
        if st == "unplaced":
            unplaced_n += 1
        elif st == "ok":
            enclosed.append(r)
        else:
            unbounded.append(r)

    if not unbounded:
        if not forms.alert("All placed rooms on '%s' are enclosed.\n\nScan "
                           "the level for open boundary ends anyway?"
                           % elem_name(level), title=TITLE,
                           yes=True, no=True):
            return

    rows = []
    for r in unbounded:
        pt = r.Location.Point
        status = "Not Enclosed"
        probe = DB.XYZ(pt.X, pt.Y, pt.Z + 1.0)
        for er in enclosed:
            try:
                if er.IsPointInRoom(probe):
                    status = "Redundant - inside room %s" % room_text(er)
                    break
            except Exception:
                pass
        rows.append((r, (pt.X, pt.Y), status))

    bounding, non_bounding, notes = collect_all(doc, ctx)
    result = core.analyse(
        bounding, non_bounding,
        [(r, pt) for r, pt, st in rows if st == "Not Enclosed"],
        tolerance=mm(SETTINGS["join_tolerance_mm"]),
        max_gap=mm(SETTINGS["max_gap_mm"]))

    t = DB.Transaction(doc, "DLC Room Gaps - %s" % elem_name(level))
    t.Start()
    try:
        painter, removed, _ = draw(doc, view, ctx.level_z, result, rows)
        t.Commit()
    except Exception as ex:
        if t.HasStarted():
            t.RollBack()
        forms.alert("Could not draw the markers - nothing was changed.\n\n"
                    "Reason: %s\n\nIf the model is workshared, make sure you "
                    "can edit the view and the Lines category." % ex,
                    title=TITLE)
        return

    output = script.get_output()
    try:
        output.set_title(TITLE)
    except Exception:
        pass
    report(output, level, view, rows, unplaced_n, result, notes, painter,
           removed, lines_hidden(doc, view))

    if uidoc.ActiveView.Id != view.Id:
        try:
            uidoc.ActiveView = view
        except Exception:
            pass


if __name__ == "__main__":
    main()

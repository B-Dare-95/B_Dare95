# -*- coding: utf-8 -*-
__title__ = "DWG to\nRevit"
__doc__ = """Turns a linked or imported DWG plan into real Revit elements: walls, railings, doors, windows, columns and grids.

You tell the tool which DWG layer holds which category and which family type to use. Walls and railings can be drawn along each single line in the DWG, or along the centerline between two parallel lines. In Single mode every element on the layer gets one type. In Multiple mode you add size rules, such as "Equal 100 mm -> 100 mm wall type", and each element gets the type of the first rule its size matches. For walls and railings drawn from two lines the size is the distance between them, for doors and windows it's the opening width, and for columns you enter width and length, or one size for square and round columns.

How to use:
-> Link or import the DWG plan into a plan view.
-> Click the button and pick the DWG at the top. Elements go on the DWG's own level (the plan view it sits in, or its Base Level).
-> Map each layer to a category, then pick a type (Single) or add size rules (Multiple). Click the rules button to fold the rule list away.
-> Press Create Elements. Walls and columns go up to the next level, or 3000 mm on the top level.

Your layer mapping and rules are saved in the project, so the next run on the same DWG remembers them. Keep "Replace previous result" switched on to rebuild cleanly after the drawing changes.

Author: Mohamed Bedair"""

import clr
import math
import json
import bisect

clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")
clr.AddReference("System.Xml")

from System import Guid, String, EventHandler
from System.Collections.Generic import List
from System.Windows import RoutedEventHandler, Visibility
from System.Windows.Markup import XamlReader
from System.Windows.Threading import Dispatcher, DispatcherFrame
from System.Windows.Controls import SelectionChangedEventHandler, TextChangedEventHandler
from System.Windows.Controls import Grid as WpfGrid

from Autodesk.Revit.DB import (FilteredElementCollector, ImportInstance, Options,
                               GeometryInstance, Curve, Line, Arc, PolyLine, XYZ,
                               Transaction, TransactionGroup, Level, Wall, WallType,
                               WallKind, BuiltInCategory, BuiltInParameter, FamilySymbol,
                               ElementId, ElementTransformUtils, Grid, GridType,
                               LocationCurve, CurveLoop, Element, SpecTypeId)
from Autodesk.Revit.DB.Structure import StructuralType
from Autodesk.Revit.DB.Architecture import Railing, RailingType
from Autodesk.Revit.DB.ExtensibleStorage import (Schema, SchemaBuilder, Entity,
                                                 AccessLevel, ExtensibleStorageFilter)
from Autodesk.Revit.UI import TaskDialog

uidoc = __revit__.ActiveUIDocument
doc = uidoc.Document

MM = 1.0 / 304.8
ROLES = ["Ignore", "Walls", "Railings", "Doors", "Windows", "Columns", "Grids"]
GEOM_ROLES = ("Walls", "Railings")
SRC_GUID = "8c1f0e7a-3b5d-4f2a-9e61-2d7b4c9a1e53"
MAP_GUID = "4e9b2c61-7a3f-4d18-b5e0-91c6f2a8d374"


# =====================================================================
# PURE GEOMETRY (no Revit API) - points are (x, y) tuples in feet
# =====================================================================
# --- PURE START

def v_sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def v_add(a, b):
    return (a[0] + b[0], a[1] + b[1])


def v_mul(a, s):
    return (a[0] * s, a[1] * s)


def v_dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def v_mid(a, b):
    return ((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5)


def norm_ang(a):
    return a % (2.0 * math.pi)


def subtract_intervals(intervals, used):
    res = list(intervals)
    for u0, u1 in used:
        out = []
        for a, b in res:
            if u1 <= a or u0 >= b:
                out.append((a, b))
                continue
            if u0 > a:
                out.append((a, u0))
            if u1 < b:
                out.append((u1, b))
        res = out
    return res


def canon_seg(x0, y0, x1, y1):
    """Direction normalised so parallel lines share (almost) the same u."""
    dx = x1 - x0
    dy = y1 - y0
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return None
    ux = dx / length
    uy = dy / length
    ang = math.degrees(math.atan2(uy, ux))
    if ang < 0.0:
        ang += 180.0
        ux, uy = -ux, -uy
        x0, y0, x1, y1 = x1, y1, x0, y0
    if ang >= 179.5:
        ang -= 180.0
        ux, uy = -ux, -uy
        x0, y0, x1, y1 = x1, y1, x0, y0
    return {'p0': (x0, y0), 'p1': (x1, y1), 'u': (ux, uy), 'n': (-uy, ux),
            'L': length, 'ang': ang, 'used': []}


def pair_lines(segs, tmin, tmax, ang_tol, min_ov, accept=None):
    """Find parallel line pairs whose spacing is a wall thickness.
    Returns wall centerline dicts {'kind':'L','p0','p1','t'}."""
    buckets = {}
    for i, s in enumerate(segs):
        buckets.setdefault(int(math.floor(s['ang'])), []).append(i)

    index = {}
    for b in buckets:
        a = math.radians(b + 0.5)
        nb = (-math.sin(a), math.cos(a))
        members = []
        lmax = 0.0
        for bb in (b - 1, b, b + 1):
            for j in buckets.get(bb, []):
                s = segs[j]
                members.append((v_dot(v_mid(s['p0'], s['p1']), nb), j))
                if s['L'] > lmax:
                    lmax = s['L']
        members.sort()
        index[b] = (nb, [m[0] for m in members], [m[1] for m in members], lmax)

    cands = []
    deg = [0] * len(segs)
    eps = 0.5 * MM
    for i, si in enumerate(segs):
        nb, keys, ids, lmax = index[int(math.floor(si['ang']))]
        ci = v_dot(v_mid(si['p0'], si['p1']), nb)
        margin = math.radians(1.5) * (si['L'] + lmax) + tmax
        lo = bisect.bisect_left(keys, ci - margin)
        hi = bisect.bisect_right(keys, ci + margin)
        ui, ni, pi0 = si['u'], si['n'], si['p0']
        for k in range(lo, hi):
            j = ids[k]
            if j == i:
                continue
            sj = segs[j]
            if abs(sj['ang'] - si['ang']) > ang_tol:
                continue
            d0 = v_dot(v_sub(sj['p0'], pi0), ni)
            d1 = v_dot(v_sub(sj['p1'], pi0), ni)
            if d0 < tmin - eps or d0 > tmax + eps or d1 < tmin - eps or d1 > tmax + eps:
                continue
            s0 = v_dot(v_sub(sj['p0'], pi0), ui)
            s1 = v_dot(v_sub(sj['p1'], pi0), ui)
            a = max(0.0, min(s0, s1))
            b = min(si['L'], max(s0, s1))
            if b - a < min_ov:
                continue
            d = (d0 + d1) * 0.5
            if accept is not None and not accept(d):
                continue
            cands.append((d, i, j))
            deg[i] += 1
            deg[j] += 1

    # lines with fewer options first, then thinnest first
    cands.sort(key=lambda c: (min(deg[c[1]], deg[c[2]]), c[0]))

    walls = []
    for d, i, j in cands:
        si = segs[i]
        sj = segs[j]
        ui, pi0 = si['u'], si['p0']
        uj, pj0 = sj['u'], sj['p0']
        s0 = v_dot(v_sub(sj['p0'], pi0), ui)
        s1 = v_dot(v_sub(sj['p1'], pi0), ui)
        a = max(0.0, min(s0, s1))
        b = min(si['L'], max(s0, s1))
        for x0, x1 in subtract_intervals([(a, b)], si['used']):
            if x1 - x0 < min_ov:
                continue
            y0 = v_dot(v_sub(v_add(pi0, v_mul(ui, x0)), pj0), uj)
            y1 = v_dot(v_sub(v_add(pi0, v_mul(ui, x1)), pj0), uj)
            if y0 > y1:
                y0, y1 = y1, y0
            for q0, q1 in subtract_intervals([(y0, y1)], sj['used']):
                if q1 - q0 < min_ov:
                    continue
                Q0 = v_add(pj0, v_mul(uj, q0))
                Q1 = v_add(pj0, v_mul(uj, q1))
                r0 = v_dot(v_sub(Q0, pi0), ui)
                r1 = v_dot(v_sub(Q1, pi0), ui)
                A0 = v_add(pi0, v_mul(ui, r0))
                A1 = v_add(pi0, v_mul(ui, r1))
                m0 = v_mid(A0, Q0)
                m1 = v_mid(A1, Q1)
                if r0 > r1:
                    m0, m1 = m1, m0
                walls.append({'kind': 'L', 'p0': m0, 'p1': m1, 't': d})
                si['used'].append((min(r0, r1), max(r0, r1)))
                sj['used'].append((q0, q1))
    return walls


def _arc_pieces(off, swj, swi):
    """Overlap of j=[off, off+swj] (with wrap) and i=[0, swi], in i-local angles.
    Returns [(a, b, k)] where j-local = a - off + 2*pi*k."""
    two = 2.0 * math.pi
    out = []
    for k in (0, 1):
        lo = off - two * k
        hi = lo + swj
        a = max(0.0, lo)
        b = min(swi, hi)
        if b > a:
            out.append((a, b, k))
    return out


def pair_arcs(arcs, tmin, tmax, ctol, min_ov, accept=None):
    """Concentric arc pairs -> curved wall centerlines."""
    two = 2.0 * math.pi
    eps = 0.5 * MM
    cands = []
    deg = [0] * len(arcs)
    for i in range(len(arcs)):
        ai = arcs[i]
        for j in range(i + 1, len(arcs)):
            aj = arcs[j]
            if math.hypot(ai['c'][0] - aj['c'][0], ai['c'][1] - aj['c'][1]) > ctol:
                continue
            d = abs(ai['r'] - aj['r'])
            if d < tmin - eps or d > tmax + eps:
                continue
            if accept is not None and not accept(d):
                continue
            off = norm_ang(aj['a0'] - ai['a0'])
            rmid = (ai['r'] + aj['r']) * 0.5
            pieces = _arc_pieces(off, aj['sw'], ai['sw'])
            if not [p for p in pieces if (p[1] - p[0]) * rmid >= min_ov]:
                continue
            cands.append((d, i, j))
            deg[i] += 1
            deg[j] += 1
    cands.sort(key=lambda c: (min(deg[c[1]], deg[c[2]]), c[0]))

    walls = []
    for d, i, j in cands:
        ai = arcs[i]
        aj = arcs[j]
        off = norm_ang(aj['a0'] - ai['a0'])
        rmid = (ai['r'] + aj['r']) * 0.5
        for a, b, k in _arc_pieces(off, aj['sw'], ai['sw']):
            for x0, x1 in subtract_intervals([(a, b)], ai['used']):
                y0 = x0 - off + two * k
                y1 = x1 - off + two * k
                for q0, q1 in subtract_intervals([(y0, y1)], aj['used']):
                    if (q1 - q0) * rmid < min_ov:
                        continue
                    r0 = q0 + off - two * k
                    r1 = q1 + off - two * k
                    c = v_mid(ai['c'], aj['c'])
                    walls.append({'kind': 'A', 'c': c, 'r': rmid,
                                  'a0': ai['a0'] + r0, 'a1': ai['a0'] + r1, 't': d})
                    ai['used'].append((r0, r1))
                    aj['used'].append((q0, q1))
    return walls


def _bb_contains(bb, p, grow):
    return (bb[0] - grow <= p[0] <= bb[2] + grow) and (bb[1] - grow <= p[1] <= bb[3] + grow)


def merge_collinear(walls, join_tol, bridge_max, bridge_all, open_bbs):
    """Join collinear centerlines of equal thickness. Gaps up to bridge_max are
    closed when a door/window sits in them (or always, if bridge_all)."""
    out = [w for w in walls if w['kind'] != 'L']
    groups = {}
    for w in walls:
        if w['kind'] != 'L':
            continue
        s = canon_seg(w['p0'][0], w['p0'][1], w['p1'][0], w['p1'][1])
        if s is None:
            continue
        s['t'] = w['t']
        key = (int(round(s['ang'] * 2.0)), int(round(w['t'] / (2.0 * MM))))
        groups.setdefault(key, []).append(s)

    for key, segs in groups.items():
        a = math.radians(key[0] / 2.0)
        nb = (-math.sin(a), math.cos(a))
        segs.sort(key=lambda s: v_dot(v_mid(s['p0'], s['p1']), nb))
        chains = []
        cur = [segs[0]]
        for s in segs[1:]:
            prev = cur[-1]
            gap = v_dot(v_sub(v_mid(s['p0'], s['p1']), v_mid(prev['p0'], prev['p1'])), prev['n'])
            if abs(gap) <= 10.0 * MM:
                cur.append(s)
            else:
                chains.append(cur)
                cur = [s]
        chains.append(cur)

        for chain in chains:
            t = sum(s['t'] for s in chain) / len(chain)
            if len(chain) == 1:
                s = chain[0]
                out.append({'kind': 'L', 'p0': s['p0'], 'p1': s['p1'], 't': t})
                continue
            tot = sum(s['L'] for s in chain)
            ux = sum(s['u'][0] * s['L'] for s in chain) / tot
            uy = sum(s['u'][1] * s['L'] for s in chain) / tot
            ln = math.hypot(ux, uy)
            u = (ux / ln, uy / ln)
            n = (-u[1], u[0])
            c = sum(v_dot(v_mid(s['p0'], s['p1']), n) * s['L'] for s in chain) / tot
            ivs = sorted([(min(v_dot(s['p0'], u), v_dot(s['p1'], u)),
                           max(v_dot(s['p0'], u), v_dot(s['p1'], u))) for s in chain])
            merged = []
            c0, c1 = ivs[0]
            for n0, n1 in ivs[1:]:
                gap = n0 - c1
                join = gap <= join_tol
                if not join and gap <= bridge_max:
                    if bridge_all:
                        join = True
                    else:
                        gm = (n0 + c1) * 0.5
                        gp = (gm * u[0] + c * n[0], gm * u[1] + c * n[1])
                        for bb in open_bbs:
                            if _bb_contains(bb, gp, t * 0.5 + 50.0 * MM):
                                join = True
                                break
                if join:
                    c1 = max(c1, n1)
                else:
                    merged.append((c0, c1))
                    c0, c1 = n0, n1
            merged.append((c0, c1))
            for m0, m1 in merged:
                p0 = (m0 * u[0] + c * n[0], m0 * u[1] + c * n[1])
                p1 = (m1 * u[0] + c * n[0], m1 * u[1] + c * n[1])
                out.append({'kind': 'L', 'p0': p0, 'p1': p1, 't': t})
    return out


def extend_junctions(walls, ext_max):
    """Extend straight wall ends to meet the centerline of a crossing wall
    (closes L corners and T junctions)."""
    lines = [w for w in walls if w['kind'] == 'L']
    info = []
    for w in lines:
        d = v_sub(w['p1'], w['p0'])
        ln = math.hypot(d[0], d[1])
        info.append((v_mul(d, 1.0 / ln), ln))
    min_sin = math.sin(math.radians(10.0))
    tol = 1.0 * MM
    result = []
    for i, w in enumerate(lines):
        u, ln = info[i]
        ends = [w['p0'], w['p1']]
        for e in (0, 1):
            E = ends[e]
            v = u if e == 1 else (-u[0], -u[1])
            best = None
            for k, o in enumerate(lines):
                if k == i:
                    continue
                ou, olen = info[k]
                cross = v[0] * ou[1] - v[1] * ou[0]
                if abs(cross) < min_sin:
                    continue
                w0 = v_sub(o['p0'], E)
                s = (w0[0] * ou[1] - w0[1] * ou[0]) / cross
                if s < -tol or s > ext_max:
                    continue
                r = (v[1] * w0[0] - v[0] * w0[1]) / cross
                if r < -ext_max or r > olen + ext_max:
                    continue
                if best is None or s < best:
                    best = s
            if best is not None and best > tol:
                ends[e] = v_add(E, v_mul(v, best))
        result.append({'kind': 'L', 'p0': ends[0], 'p1': ends[1], 't': w['t']})
    return result + [w for w in walls if w['kind'] != 'L']


def bbox_of(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def cluster_items(items, tol):
    """items: (kind, geom, pts, block_key). Block contents stay together;
    loose curves are grouped when their boxes touch."""
    groups = {}
    loose = []
    for it in items:
        if not it[2]:
            continue
        if it[3] is not None:
            groups.setdefault(it[3], []).append(it)
        else:
            loose.append(it)
    clusters = list(groups.values())

    n = len(loose)
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    bbs = []
    for it in loose:
        b = bbox_of(it[2])
        bbs.append((b[0] - tol, b[1] - tol, b[2] + tol, b[3] + tol))
    cell = 500.0 * MM
    grid = {}
    for idx, bb in enumerate(bbs):
        for cx in range(int(math.floor(bb[0] / cell)), int(math.floor(bb[2] / cell)) + 1):
            for cy in range(int(math.floor(bb[1] / cell)), int(math.floor(bb[3] / cell)) + 1):
                grid.setdefault((cx, cy), []).append(idx)
    for lst in grid.values():
        for a in range(len(lst)):
            ba = bbs[lst[a]]
            for b in range(a + 1, len(lst)):
                bb = bbs[lst[b]]
                if ba[0] <= bb[2] and bb[0] <= ba[2] and ba[1] <= bb[3] and bb[1] <= ba[3]:
                    ra = find(lst[a])
                    rb = find(lst[b])
                    if ra != rb:
                        parent[ra] = rb
    loose_groups = {}
    for idx in range(n):
        loose_groups.setdefault(find(idx), []).append(loose[idx])
    clusters.extend(loose_groups.values())

    out = []
    for cl in clusters:
        pts = []
        for it in cl:
            pts.extend(it[2])
        out.append({'items': cl, 'pts': pts, 'bb': bbox_of(pts)})
    return out


def column_frame(cluster):
    """Centre, rotation and size of a column outline (min-area rectangle
    over the angles of its own lines)."""
    pts = cluster['pts']
    angs = set()
    has_line = False
    for kind, g, p, bk in cluster['items']:
        if kind == 'L':
            has_line = True
            a = math.atan2(g[3] - g[1], g[2] - g[0]) % (math.pi / 2.0)
            angs.add(round(a, 3))
    if not angs:
        angs.add(0.0)
    best = None
    for a in angs:
        ca, sa = math.cos(a), math.sin(a)
        xs = [p[0] * ca + p[1] * sa for p in pts]
        ys = [-p[0] * sa + p[1] * ca for p in pts]
        w = max(xs) - min(xs)
        h = max(ys) - min(ys)
        if best is None or w * h < best[0] - 1e-9:
            cx = (max(xs) + min(xs)) * 0.5
            cy = (max(ys) + min(ys)) * 0.5
            best = (w * h, a, w, h, (cx * ca - cy * sa, cx * sa + cy * ca))
    _, a, w, h, c = best
    return {'center': c, 'angle': a, 'w': w, 'h': h, 'round': not has_line}


def merge_grid_lines(segs):
    """Collinear grid segments become one grid line."""
    groups = []
    for s in segs:
        placed = False
        for g in groups:
            r = g[0]
            if abs(s['ang'] - r['ang']) > 0.5:
                continue
            if abs(v_dot(v_sub(v_mid(s['p0'], s['p1']), r['p0']), r['n'])) > 10.0 * MM:
                continue
            g.append(s)
            placed = True
            break
        if not placed:
            groups.append([s])
    out = []
    for g in groups:
        r = g[0]
        ts = []
        for s in g:
            ts.append(v_dot(v_sub(s['p0'], r['p0']), r['u']))
            ts.append(v_dot(v_sub(s['p1'], r['p0']), r['u']))
        out.append((v_add(r['p0'], v_mul(r['u'], min(ts))),
                    v_add(r['p0'], v_mul(r['u'], max(ts)))))
    return out


def path_ends(w):
    if w['kind'] == 'L':
        return w['p0'], w['p1']
    c, rr = w['c'], w['r']
    return ((c[0] + rr * math.cos(w['a0']), c[1] + rr * math.sin(w['a0'])),
            (c[0] + rr * math.cos(w['a1']), c[1] + rr * math.sin(w['a1'])))


def chain_paths(paths, tol):
    """Connected paths -> chains of (path, reversed) in drawing order."""
    n = len(paths)
    ends = [path_ends(w) for w in paths]
    cell = {}

    def key(pt):
        return (int(math.floor(pt[0] / tol)), int(math.floor(pt[1] / tol)))

    for i in range(n):
        for e in (0, 1):
            cell.setdefault(key(ends[i][e]), []).append((i, e))
    used = [False] * n

    def find(pt):
        kx, ky = key(pt)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for i, e in cell.get((kx + dx, ky + dy), []):
                    if not used[i] and math.hypot(ends[i][e][0] - pt[0], ends[i][e][1] - pt[1]) <= tol:
                        return i, e
        return None

    chains = []
    for s in range(n):
        if used[s]:
            continue
        used[s] = True
        chain = [(s, False)]
        tail = ends[s][1]
        while True:
            hit = find(tail)
            if hit is None:
                break
            i, e = hit
            used[i] = True
            chain.append((i, e == 1))
            tail = ends[i][0] if e == 1 else ends[i][1]
        head = ends[s][0]
        while True:
            hit = find(head)
            if hit is None:
                break
            i, e = hit
            used[i] = True
            chain.insert(0, (i, e == 0))
            head = ends[i][1] if e == 0 else ends[i][0]
        chains.append([(paths[i], rev) for i, rev in chain])
    return chains


def letter_name(i):
    letters = "ABCDEFGHJKLMNPQRSTUVWXYZ"
    name = ""
    i += 1
    while i > 0:
        i -= 1
        name = letters[i % 24] + name
        i //= 24
    return name

# --- PURE END


# =====================================================================
# REVIT HELPERS
# =====================================================================

def eid_int(eid):
    try:
        return eid.Value
    except AttributeError:
        return eid.IntegerValue


def el_name(e):
    try:
        return e.Name
    except Exception:
        return Element.Name.GetValue(e)


def layer_name(gobj):
    try:
        sid = gobj.GraphicsStyleId
        if sid is None or sid == ElementId.InvalidElementId:
            return None
        gs = doc.GetElement(sid)
        if gs is None or gs.GraphicsStyleCategory is None:
            return None
        return gs.GraphicsStyleCategory.Name
    except Exception:
        return None


def curve_items(c):
    """Revit curve -> list of (kind, geom, pts)."""
    if isinstance(c, Line):
        p0 = c.GetEndPoint(0)
        p1 = c.GetEndPoint(1)
        if math.hypot(p1.X - p0.X, p1.Y - p0.Y) < 1.0 * MM:
            return []
        return [('L', (p0.X, p0.Y, p1.X, p1.Y), [(p0.X, p0.Y), (p1.X, p1.Y)])]
    if isinstance(c, Arc):
        ctr = c.Center
        r = c.Radius
        full = [(ctr.X + r * math.cos(k * math.pi / 4.0), ctr.Y + r * math.sin(k * math.pi / 4.0))
                for k in range(8)]
        if not c.IsBound:
            return [('C', (ctr.X, ctr.Y, r), full)]
        p0 = c.GetEndPoint(0)
        p1 = c.GetEndPoint(1)
        if c.Normal.Z < 0:
            p0, p1 = p1, p0
        a0 = math.atan2(p0.Y - ctr.Y, p0.X - ctr.X)
        a1 = math.atan2(p1.Y - ctr.Y, p1.X - ctr.X)
        sw = norm_ang(a1 - a0)
        if sw < 1e-6 or sw > 2.0 * math.pi - 1e-4:
            return [('C', (ctr.X, ctr.Y, r), full)]
        pts = [(ctr.X + r * math.cos(a0 + sw * k / 8.0), ctr.Y + r * math.sin(a0 + sw * k / 8.0))
               for k in range(9)]
        return [('A', (ctr.X, ctr.Y, r, a0, sw), pts)]
    try:
        pts = [(p.X, p.Y) for p in c.Tessellate()]
    except Exception:
        return []
    return [('P', None, pts)] if pts else []


def read_dwg(inst):
    """Layer name -> {'items': [(kind, geom, pts, block_key)], 'blocks': set()}"""
    opts = Options()
    opts.IncludeNonVisibleObjects = False
    if inst.ViewSpecific:
        v = doc.GetElement(inst.OwnerViewId)
        if v is not None:
            opts.View = v
    layers = {}
    counter = [0]

    def add(lname, kind, geom, pts, bkey):
        rec = layers.setdefault(lname, {'items': [], 'blocks': set()})
        rec['items'].append((kind, geom, pts, bkey))
        if bkey is not None:
            rec['blocks'].add(bkey)

    def resolve(own, inherited):
        if own and own != "0":
            return own
        return inherited or own or "0"

    def walk(geom, inherited, bkey, depth):
        if geom is None:
            return
        for g in geom:
            if isinstance(g, GeometryInstance):
                lname = resolve(layer_name(g), inherited)
                key = bkey
                if depth == 0:
                    counter[0] += 1
                    key = counter[0]
                walk(g.GetInstanceGeometry(), lname, key, depth + 1)
            elif isinstance(g, PolyLine):
                lname = resolve(layer_name(g), inherited)
                pts = list(g.GetCoordinates())
                for k in range(len(pts) - 1):
                    a, b = pts[k], pts[k + 1]
                    if math.hypot(b.X - a.X, b.Y - a.Y) >= 1.0 * MM:
                        add(lname, 'L', (a.X, a.Y, b.X, b.Y), [(a.X, a.Y), (b.X, b.Y)], bkey)
            elif isinstance(g, Curve):
                lname = resolve(layer_name(g), inherited)
                for kind, geo, pts in curve_items(g):
                    add(lname, kind, geo, pts, bkey)

    top = inst.get_Geometry(opts)
    if top is None:
        return layers
    for g in top:
        if isinstance(g, GeometryInstance):
            walk(g.GetInstanceGeometry(), None, None, 0)
    return layers


# ---------- extensible storage ----------

def get_schema(guid_str, name, field, create):
    s = Schema.Lookup(Guid(guid_str))
    if s is not None or not create:
        return s
    sb = SchemaBuilder(Guid(guid_str))
    sb.SetSchemaName(name)
    sb.SetReadAccessLevel(AccessLevel.Public)
    sb.SetWriteAccessLevel(AccessLevel.Public)
    sb.AddSimpleField(field, String)
    return sb.Finish()


def load_store():
    s = get_schema(MAP_GUID, "BDare95DwgToRevitMap", "Json", False)
    if s is None:
        return {}
    ent = doc.ProjectInformation.GetEntity(s)
    if ent is None or not ent.IsValid():
        return {}
    try:
        return json.loads(ent.Get[String]("Json"))
    except Exception:
        return {}


def save_store(data):
    s = get_schema(MAP_GUID, "BDare95DwgToRevitMap", "Json", True)
    ent = Entity(s)
    ent.Set[String]("Json", json.dumps(data))
    doc.ProjectInformation.SetEntity(ent)


def tag_element(el, schema, src):
    ent = Entity(schema)
    ent.Set[String]("SourceDwg", src)
    el.SetEntity(ent)


def previous_results(src):
    s = get_schema(SRC_GUID, "BDare95DwgToRevitSource", "SourceDwg", False)
    if s is None:
        return []
    ids = []
    col = FilteredElementCollector(doc).WherePasses(ExtensibleStorageFilter(s.GUID)) \
        .WhereElementIsNotElementType()
    for el in col:
        ent = el.GetEntity(s)
        if ent.IsValid() and ent.Get[String]("SourceDwg") == src:
            ids.append(el.Id)
    return ids


# ---------- type options and size rules ----------

SIZED_ROLES = ("Walls", "Railings", "Doors", "Windows", "Columns")
EVALUATORS = ["Equal", "Greater than", "Less than", "Greater or equal", "Less or equal"]
SIZE_HINT = {
    "Railings": u"Size = distance between the two parallel lines. The first matching rule wins.",
    "Walls": u"Size = distance between the two parallel lines. The first matching rule wins.",
    "Doors": u"Size = door width measured along the wall. The first matching rule wins.",
    "Windows": u"Size = window width measured along the wall. The first matching rule wins.",
    "Columns": u"Width and length of the column outline, in any order. Switch on One size for "
               u"square or round columns. The first matching rule wins.",
}
TOL = {"Walls": 2.0 * MM, "Railings": 2.0 * MM, "Doors": 5.0 * MM, "Windows": 5.0 * MM, "Columns": 5.0 * MM}
WALL_RANGE = (20.0 * MM, 600.0 * MM)
DEFAULT_HEIGHT = 3000.0 * MM
STRICT = 0.5 * MM


def symbol_options(bics):
    out = []
    for bic in bics:
        for s in FilteredElementCollector(doc).OfClass(FamilySymbol).OfCategory(bic):
            out.append((u"{0} : {1}".format(el_name(s.Family), el_name(s)), s.Id))
    out.sort(key=lambda o: o[0].lower())
    return out


def build_type_options():
    opts = {}
    wts = [w for w in FilteredElementCollector(doc).OfClass(WallType) if w.Kind == WallKind.Basic]
    opts["Walls"] = sorted([(u"{0}  ({1:.0f} mm)".format(el_name(w), w.Width / MM), w.Id) for w in wts],
                           key=lambda o: o[0].lower())
    opts["Doors"] = symbol_options([BuiltInCategory.OST_Doors])
    opts["Windows"] = symbol_options([BuiltInCategory.OST_Windows])
    opts["Columns"] = symbol_options([BuiltInCategory.OST_Columns,
                                      BuiltInCategory.OST_StructuralColumns])
    opts["Railings"] = sorted([(el_name(t), t.Id) for t in FilteredElementCollector(doc).OfClass(RailingType)],
                              key=lambda o: o[0].lower())
    opts["Grids"] = sorted([(el_name(g), g.Id) for g in FilteredElementCollector(doc).OfClass(GridType)],
                           key=lambda o: o[0].lower())
    return opts


def parse_size(text):
    t = text.strip().lower().replace(u"\u00d7", "x").replace("*", "x").replace(",", ".")
    parts = [p.strip() for p in t.split("x") if p.strip()]
    if not 1 <= len(parts) <= 2:
        raise ValueError()
    vals = [float(p) * MM for p in parts]
    if [v for v in vals if v <= 0]:
        raise ValueError()
    return vals


def compare(ev, m, v, tol):
    if ev == "Equal":
        return abs(m - v) <= tol
    if ev == "Greater than":
        return m > v + STRICT
    if ev == "Less than":
        return m < v - STRICT
    if ev == "Greater or equal":
        return m >= v - tol
    if ev == "Less or equal":
        return m <= v + tol
    return False


class TypeChooser(object):
    """Single type, or the first size rule that matches the measured size.
    dims: measured sizes in feet, largest first."""

    def __init__(self, entry, tol):
        self.entry = entry
        self.tol = tol

    def pick(self, dims):
        if self.entry['mode'] == 'single':
            return self.entry['single']
        for r in self.entry['rules']:
            vals = r['vals']
            ok = compare(r['ev'], dims[0], max(vals), self.tol)
            if ok and len(dims) == 2:
                # one value on a rectangular outline means "square": both sides must match
                ok = compare(r['ev'], dims[1], min(vals), self.tol)
            if ok:
                return r['type']
        return None

    def wall_range(self):
        """Thickness range the rules can ever accept (open ends capped)."""
        if self.entry['mode'] == 'single':
            return WALL_RANGE
        lo = None
        hi = None
        t = self.tol
        for r in self.entry['rules']:
            v = max(r['vals'])
            ev = r['ev']
            if ev == "Equal":
                a, b = v - t, v + t
            elif ev == "Greater than":
                a, b = v + STRICT, WALL_RANGE[1]
            elif ev == "Greater or equal":
                a, b = v - t, WALL_RANGE[1]
            elif ev == "Less than":
                a, b = WALL_RANGE[0], v - STRICT
            else:
                a, b = WALL_RANGE[0], v + t
            lo = a if lo is None else min(lo, a)
            hi = b if hi is None else max(hi, b)
        return max(lo, 1.0 * MM), hi


def size_text(dims):
    return u" x ".join([u"{0:.0f}".format(d / MM) for d in dims]) + u" mm"


# =====================================================================
# BUILDERS
# =====================================================================

class Report(object):
    def __init__(self):
        self.counts = {}
        self.issues = {}
        self.created = []

    def made(self, role, el=None):
        self.counts[role] = self.counts.get(role, 0) + 1
        if el is not None:
            self.created.append(el.Id)

    def issue(self, msg):
        self.issues[msg] = self.issues.get(msg, 0) + 1


def find_length_param(el, names):
    for nm in names:
        p = el.LookupParameter(nm)
        if p is not None and p.Definition.GetDataType().Equals(SpecTypeId.Length):
            return p
    return None


def column_type_dims(sym):
    pw = find_length_param(sym, ["b", "Width", "B", "W"])
    ph = find_length_param(sym, ["h", "Depth", "H", "D"])
    if pw is not None and ph is not None:
        return pw.AsDouble(), ph.AsDouble()
    pd = find_length_param(sym, ["Diameter", "d", "Dia"])
    if pd is not None:
        return pd.AsDouble(), pd.AsDouble()
    return None

def activate(sym):
    if not sym.IsActive:
        sym.Activate()
        doc.Regenerate()


def host_records(level):
    recs = []
    for w in FilteredElementCollector(doc).OfClass(Wall):
        if w.LevelId != level.Id or not isinstance(w.Location, LocationCurve):
            continue
        c = w.Location.Curve
        hw = w.Width * 0.5
        if isinstance(c, Line):
            p0 = c.GetEndPoint(0)
            p1 = c.GetEndPoint(1)
            s = canon_seg(p0.X, p0.Y, p1.X, p1.Y)
            if s is None:
                continue
            bb = bbox_of([s['p0'], s['p1']])
            recs.append({'wall': w, 'kind': 'L', 'p0': s['p0'], 'u': s['u'], 'n': s['n'],
                         'L': s['L'], 'hw': hw,
                         'bb': (bb[0] - hw, bb[1] - hw, bb[2] + hw, bb[3] + hw)})
        elif isinstance(c, Arc):
            ctr = (c.Center.X, c.Center.Y)
            r = c.Radius
            recs.append({'wall': w, 'kind': 'A', 'c': ctr, 'r': r, 'hw': hw,
                         'bb': (ctr[0] - r - hw, ctr[1] - r - hw, ctr[0] + r + hw, ctr[1] + r + hw)})
    return recs


def best_host(cluster, hosts):
    tol = 50.0 * MM
    bb = cluster['bb']
    best = None
    best_n = 0
    for h in hosts:
        hb = h['bb']
        if hb[0] > bb[2] + tol or bb[0] > hb[2] + tol or hb[1] > bb[3] + tol or bb[1] > hb[3] + tol:
            continue
        cnt = 0
        for P in cluster['pts']:
            if h['kind'] == 'L':
                d = v_sub(P, h['p0'])
                s = v_dot(d, h['u'])
                if -tol <= s <= h['L'] + tol and abs(v_dot(d, h['n'])) <= h['hw'] + tol:
                    cnt += 1
            else:
                if abs(math.hypot(P[0] - h['c'][0], P[1] - h['c'][1]) - h['r']) <= h['hw'] + tol:
                    cnt += 1
        if cnt > best_n:
            best = h
            best_n = cnt
    return best


def opening_frame(cluster, h):
    """Insertion point, width, wall direction and wall normal at the opening."""
    pts = cluster['pts']
    if h['kind'] == 'L':
        ss = [v_dot(v_sub(P, h['p0']), h['u']) for P in pts]
        s0, s1 = min(ss), max(ss)
        mid = (s0 + s1) * 0.5
        point = v_add(h['p0'], v_mul(h['u'], mid))
        return point, s1 - s0, h['u'], h['n'], mid, ss
    c = h['c']
    angs = [math.atan2(P[1] - c[1], P[0] - c[0]) for P in pts]
    ref = angs[0]
    angs = [ref + ((a - ref + math.pi) % (2.0 * math.pi) - math.pi) for a in angs]
    a0, a1 = min(angs), max(angs)
    am = (a0 + a1) * 0.5
    point = (c[0] + h['r'] * math.cos(am), c[1] + h['r'] * math.sin(am))
    u = (-math.sin(am), math.cos(am))
    n = (math.cos(am), math.sin(am))
    ss = [(a - am) * h['r'] for a in angs]
    return point, (a1 - a0) * h['r'], u, n, 0.0, ss


def find_paths(items, chooser, geom, role, report, bridge, open_bbs):
    """Wall/railing paths: each drawn line as-is (single), or the centerline
    between pairs of parallel lines (parallel)."""
    if geom == 'single':
        paths = []
        for kind, g, pts, bk in items:
            if kind == 'L' and math.hypot(g[2] - g[0], g[3] - g[1]) >= 5.0 * MM:
                paths.append({'kind': 'L', 'p0': (g[0], g[1]), 'p1': (g[2], g[3]), 't': 0.0})
            elif kind == 'A':
                paths.append({'kind': 'A', 'c': (g[0], g[1]), 'r': g[2], 'a0': g[3],
                              'a1': g[3] + g[4], 't': 0.0})
        return merge_collinear(paths, 1.0 * MM, 0.0, False, [])
    segs = []
    arcs = []
    for kind, g, pts, bk in items:
        if kind == 'L':
            s = canon_seg(g[0], g[1], g[2], g[3])
            if s is not None and s['L'] >= 5.0 * MM:
                segs.append(s)
        elif kind == 'A':
            arcs.append({'c': (g[0], g[1]), 'r': g[2], 'a0': g[3], 'sw': g[4], 'used': []})
    tmin, tmax = chooser.wall_range()
    if tmax <= tmin:
        report.issue(u"{0}: the size rules don't allow any thickness".format(role))
        return []
    accept = None
    if chooser.entry['mode'] == 'multiple':
        accept = lambda d: chooser.pick([d]) is not None
    min_ov = max(tmin, 20.0 * MM)
    centerlines = pair_lines(segs, tmin, tmax, 0.5, min_ov, accept)
    centerlines += pair_arcs(arcs, tmin, tmax, 5.0 * MM, min_ov, accept)
    centerlines = merge_collinear(centerlines, tmax + 50.0 * MM, bridge, False, open_bbs)
    return extend_junctions(centerlines, tmax + 50.0 * MM)


def build_walls(items, chooser, geom, cfg, level, z, schema, src, report, open_bbs):
    centerlines = find_paths(items, chooser, geom, "Walls", report, cfg['bridge'], open_bbs)
    short = doc.Application.ShortCurveTolerance
    for w in centerlines:
        type_id = chooser.pick([w['t']])
        if type_id is None:
            report.issue(u"Walls: no rule matches {0}".format(size_text([w['t']])))
            continue
        try:
            if w['kind'] == 'L':
                p0 = XYZ(w['p0'][0], w['p0'][1], z)
                p1 = XYZ(w['p1'][0], w['p1'][1], z)
                if p0.DistanceTo(p1) <= short:
                    continue
                curve = Line.CreateBound(p0, p1)
            else:
                if (w['a1'] - w['a0']) * w['r'] <= short:
                    continue
                curve = Arc.Create(XYZ(w['c'][0], w['c'][1], z), w['r'], w['a0'], w['a1'],
                                   XYZ.BasisX, XYZ.BasisY)
            wall = Wall.Create(doc, curve, type_id, level.Id, cfg['height'], 0.0, False, False)
            if cfg['top'] is not None:
                wall.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE).Set(cfg['top'].Id)
                wall.get_Parameter(BuiltInParameter.WALL_TOP_OFFSET).Set(0.0)
            tag_element(wall, schema, src)
            report.made("Walls", wall)
        except Exception as e:
            report.issue(u"Wall skipped: {0}".format(e))


def build_railings(items, chooser, geom, level, z, schema, src, report):
    paths = find_paths(items, chooser, geom, "Railings", report, 0.0, [])
    by_type = {}
    for w in paths:
        type_id = chooser.pick([w['t']])
        if type_id is None:
            report.issue(u"Railings: no rule matches {0}".format(size_text([w['t']])))
            continue
        by_type.setdefault(eid_int(type_id), (type_id, []))[1].append(w)
    short = doc.Application.ShortCurveTolerance
    for type_id, group in by_type.values():
        for chain in chain_paths(group, 2.0 * MM):
            curves = List[Curve]()
            prev = None
            for w, rev in chain:
                a, b = path_ends(w)
                if rev:
                    a, b = b, a
                if prev is not None:
                    a = prev          # snap so the loop is truly continuous
                if math.hypot(b[0] - a[0], b[1] - a[1]) <= short:
                    continue
                p0 = XYZ(a[0], a[1], z)
                p1 = XYZ(b[0], b[1], z)
                if w['kind'] == 'L':
                    curves.Add(Line.CreateBound(p0, p1))
                else:
                    am = (w['a0'] + w['a1']) * 0.5
                    pm = XYZ(w['c'][0] + w['r'] * math.cos(am), w['c'][1] + w['r'] * math.sin(am), z)
                    curves.Add(Arc.Create(p0, p1, pm))
                prev = b
            if curves.Count == 0:
                continue
            try:
                rail = Railing.Create(doc, CurveLoop.Create(curves), type_id, level.Id)
                tag_element(rail, schema, src)
                report.made("Railings", rail)
            except Exception as e:
                report.issue(u"Railing skipped: {0}".format(e))


def build_openings(clusters, role, chooser, level, z, schema, src, report):
    hosts = host_records(level)
    placed = []
    for cl in clusters:
        ext = max(cl['bb'][2] - cl['bb'][0], cl['bb'][3] - cl['bb'][1])
        if ext < 200.0 * MM or ext > 6000.0 * MM:
            report.issue(u"{0}: drawing piece ignored (too small or too large)".format(role))
            continue
        h = best_host(cl, hosts)
        if h is None:
            report.issue(u"{0}: no wall found under the symbol".format(role))
            continue
        point, width, u, n, mid, ss = opening_frame(cl, h)
        type_id = chooser.pick([width])
        if type_id is None:
            report.issue(u"{0}: no rule matches width {1}".format(role, size_text([width])))
            continue
        try:
            sym = doc.GetElement(type_id)
            activate(sym)
            inst = doc.Create.NewFamilyInstance(XYZ(point[0], point[1], z), sym, h['wall'],
                                                level, StructuralType.NonStructural)
            tag_element(inst, schema, src)
            report.made(role, inst)
            if role != "Doors":
                continue
            cen = (sum(p[0] for p in cl['pts']) / len(cl['pts']),
                   sum(p[1] for p in cl['pts']) / len(cl['pts']))
            side = 1.0 if v_dot(v_sub(cen, point), n) >= 0 else -1.0
            hinge = None
            arcs = [it for it in cl['items'] if it[0] == 'A']
            if arcs:
                g = max(arcs, key=lambda it: it[1][2])[1]
                d = v_sub((g[0], g[1]), point)
                hinge = v_mul(u, 1.0 if v_dot(d, u) >= 0 else -1.0)
            placed.append((inst, v_mul(n, side), hinge))
        except Exception as e:
            report.issue(u"{0} skipped: {1}".format(role, e))

    if not placed:
        return
    # Revit door families normally swing away from the facing side and
    # hinge opposite the hand direction.
    doc.Regenerate()
    for inst, swing, hinge in placed:
        fo = inst.FacingOrientation
        if fo.X * -swing[0] + fo.Y * -swing[1] < 0 and inst.CanFlipFacing:
            inst.flipFacing()
    doc.Regenerate()
    for inst, swing, hinge in placed:
        if hinge is None or not inst.CanFlipHand:
            continue
        ho = inst.HandOrientation
        if ho.X * -hinge[0] + ho.Y * -hinge[1] < 0:
            inst.flipHand()


def build_columns(clusters, chooser, cfg, level, z, schema, src, report):
    str_cat = int(BuiltInCategory.OST_StructuralColumns)
    for cl in clusters:
        f = column_frame(cl)
        if max(f['w'], f['h']) < 50.0 * MM or max(f['w'], f['h']) > 3000.0 * MM:
            report.issue(u"Columns: outline ignored (too small or too large)")
            continue
        dims = [max(f['w'], f['h'])] if f['round'] else sorted([f['w'], f['h']], reverse=True)
        type_id = chooser.pick(dims)
        if type_id is None:
            report.issue(u"Columns: no rule matches {0}".format(size_text(dims)))
            continue
        try:
            sym = doc.GetElement(type_id)
            activate(sym)
            st = StructuralType.Column if eid_int(sym.Category.Id) == str_cat \
                else StructuralType.NonStructural
            pt = XYZ(f['center'][0], f['center'][1], z)
            inst = doc.Create.NewFamilyInstance(pt, sym, level, st)
            top = inst.get_Parameter(BuiltInParameter.FAMILY_TOP_LEVEL_PARAM)
            off = inst.get_Parameter(BuiltInParameter.FAMILY_TOP_LEVEL_OFFSET_PARAM)
            if top is not None and not top.IsReadOnly:
                top.Set(cfg['top'].Id if cfg['top'] is not None else level.Id)
                if off is not None and not off.IsReadOnly:
                    off.Set(0.0 if cfg['top'] is not None else cfg['height'])
            angle = f['angle']
            td = column_type_dims(sym)
            if td is not None and not f['round']:
                straight = abs(td[0] - f['w']) + abs(td[1] - f['h'])
                swapped = abs(td[1] - f['w']) + abs(td[0] - f['h'])
                if swapped < straight:
                    angle += math.pi / 2.0
            if abs(angle) > 1e-6:
                axis = Line.CreateBound(pt, pt + XYZ.BasisZ)
                ElementTransformUtils.RotateElement(doc, inst.Id, axis, angle)
            tag_element(inst, schema, src)
            report.made("Columns", inst)
        except Exception as e:
            report.issue(u"Column skipped: {0}".format(e))


def build_grids(items, type_id, schema, src, report):
    segs = []
    arcs = []
    for kind, g, pts, bk in items:
        if kind == 'L':
            s = canon_seg(g[0], g[1], g[2], g[3])
            if s is not None and s['L'] >= 1000.0 * MM:
                segs.append(s)
        elif kind == 'A' and g[2] >= 3000.0 * MM:
            arcs.append(g)
    lines = merge_grid_lines(segs)

    existing = list(FilteredElementCollector(doc).OfClass(Grid))
    names = set(el_name(g) for g in existing)
    ex_lines = []
    for g in existing:
        c = g.Curve
        if isinstance(c, Line):
            p0 = c.GetEndPoint(0)
            p1 = c.GetEndPoint(1)
            s = canon_seg(p0.X, p0.Y, p1.X, p1.Y)
            if s is not None:
                ex_lines.append(s)

    def exists(p0, p1):
        s = canon_seg(p0[0], p0[1], p1[0], p1[1])
        for e in ex_lines:
            if abs(e['ang'] - s['ang']) <= 0.5 and \
                    abs(v_dot(v_sub(v_mid(p0, p1), e['p0']), e['n'])) <= 10.0 * MM:
                return True
        return False

    vertical = []
    horizontal = []
    for p0, p1 in lines:
        if exists(p0, p1):
            report.issue("Grids: line already has a grid, skipped")
            continue
        d = v_sub(p1, p0)
        if abs(d[1]) >= abs(d[0]):
            if d[1] < 0:
                p0, p1 = p1, p0
            vertical.append((p0, p1))
        else:
            if d[0] < 0:
                p0, p1 = p1, p0
            horizontal.append((p0, p1))
    vertical.sort(key=lambda l: (l[0][0] + l[1][0]))
    horizontal.sort(key=lambda l: -(l[0][1] + l[1][1]))

    counter = [0, 0]

    def next_number():
        while True:
            counter[0] += 1
            nm = str(counter[0])
            if nm not in names:
                names.add(nm)
                return nm

    def next_letter():
        while True:
            nm = letter_name(counter[1])
            counter[1] += 1
            if nm not in names:
                names.add(nm)
                return nm

    jobs = [(l, next_number) for l in vertical] + [(l, next_letter) for l in horizontal]
    for (p0, p1), namer in jobs:
        try:
            grid = Grid.Create(doc, Line.CreateBound(XYZ(p0[0], p0[1], 0), XYZ(p1[0], p1[1], 0)))
            grid.Name = namer()
            if type_id is not None:
                grid.ChangeTypeId(type_id)
            tag_element(grid, schema, src)
            report.made("Grids", grid)
        except Exception as e:
            report.issue("Grid skipped: {0}".format(e))
    for g in arcs:
        try:
            arc = Arc.Create(XYZ(g[0], g[1], 0), g[2], g[3], g[3] + g[4], XYZ.BasisX, XYZ.BasisY)
            grid = Grid.Create(doc, arc)
            grid.Name = next_number()
            if type_id is not None:
                grid.ChangeTypeId(type_id)
            tag_element(grid, schema, src)
            report.made("Grids", grid)
        except Exception as e:
            report.issue("Curved grid skipped: {0}".format(e))


# =====================================================================
# UI
# =====================================================================

XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="DWG to Revit" Width="1280" Height="760" MinWidth="1100" MinHeight="560"
        WindowStartupLocation="CenterScreen" Background="#161616"
        FontFamily="Segoe UI" FontSize="12">
  <Window.Resources>
    <Style TargetType="TextBox">
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="BorderBrush" Value="#525252"/>
      <Setter Property="BorderThickness" Value="0,0,0,1"/>
      <Setter Property="Padding" Value="8,5"/>
      <Setter Property="CaretBrush" Value="#F4F4F4"/>
      <Setter Property="VerticalContentAlignment" Value="Center"/>
      <Setter Property="Height" Value="30"/>
    </Style>
    <Style TargetType="ComboBox">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Height" Value="30"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ComboBox">
            <Grid>
              <ToggleButton Focusable="False" ClickMode="Press"
                  IsChecked="{Binding IsDropDownOpen, Mode=TwoWay, RelativeSource={RelativeSource TemplatedParent}}">
                <ToggleButton.Template>
                  <ControlTemplate TargetType="ToggleButton">
                    <Border x:Name="Bd" Background="#393939" BorderBrush="#525252"
                            BorderThickness="0,0,0,1" CornerRadius="3">
                      <Path HorizontalAlignment="Right" VerticalAlignment="Center" Margin="0,0,10,0"
                            Data="M0,0 L4,4 L8,0" Stroke="#A8A8A8" StrokeThickness="1.5"/>
                    </Border>
                    <ControlTemplate.Triggers>
                      <Trigger Property="IsMouseOver" Value="True">
                        <Setter TargetName="Bd" Property="BorderBrush" Value="#F1C21B"/>
                      </Trigger>
                    </ControlTemplate.Triggers>
                  </ControlTemplate>
                </ToggleButton.Template>
              </ToggleButton>
              <ContentPresenter IsHitTestVisible="False" Margin="10,0,28,0" VerticalAlignment="Center"
                  Content="{TemplateBinding SelectionBoxItem}"
                  ContentTemplate="{TemplateBinding SelectionBoxItemTemplate}"/>
              <Popup IsOpen="{TemplateBinding IsDropDownOpen}" Placement="Bottom"
                     AllowsTransparency="True" Focusable="False" PopupAnimation="Fade">
                <Border Background="#262626" BorderBrush="#525252" BorderThickness="1"
                        MinWidth="{TemplateBinding ActualWidth}" MaxHeight="340">
                  <ScrollViewer><ItemsPresenter/></ScrollViewer>
                </Border>
              </Popup>
            </Grid>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
      <Style.Triggers>
        <Trigger Property="IsEnabled" Value="False">
          <Setter Property="Opacity" Value="0.35"/>
        </Trigger>
      </Style.Triggers>
    </Style>
    <Style TargetType="ComboBoxItem">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ComboBoxItem">
            <Border x:Name="Bd" Background="Transparent" Padding="10,6">
              <ContentPresenter/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsHighlighted" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#393939"/>
              </Trigger>
              <Trigger Property="IsSelected" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#525252"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style TargetType="Button">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="Padding" Value="22,9"/>
      <Setter Property="Margin" Value="10,0,0,0"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="Bd" Background="{TemplateBinding Background}" CornerRadius="4"
                    Padding="{TemplateBinding Padding}">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="Bd" Property="Opacity" Value="0.8"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style x:Key="Primary" TargetType="Button" BasedOn="{StaticResource {x:Type Button}}">
      <Setter Property="Background" Value="#F1C21B"/>
      <Setter Property="Foreground" Value="#161616"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
    </Style>
    <Style x:Key="Ghost" TargetType="Button" BasedOn="{StaticResource {x:Type Button}}">
      <Setter Property="Background" Value="Transparent"/>
      <Setter Property="Foreground" Value="#F1C21B"/>
      <Setter Property="Padding" Value="4,6"/>
      <Setter Property="Margin" Value="0"/>
    </Style>
    <Style x:Key="Icon" TargetType="Button" BasedOn="{StaticResource {x:Type Button}}">
      <Setter Property="Background" Value="Transparent"/>
      <Setter Property="Foreground" Value="#A8A8A8"/>
      <Setter Property="Padding" Value="0"/>
      <Setter Property="Margin" Value="0"/>
      <Setter Property="Width" Value="30"/>
      <Setter Property="Height" Value="30"/>
    </Style>
    <Style x:Key="Seg" TargetType="ToggleButton">
      <Setter Property="Foreground" Value="#A8A8A8"/>
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ToggleButton">
            <Border Background="{TemplateBinding Background}" CornerRadius="4" Padding="12,6">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
      <Style.Triggers>
        <Trigger Property="IsChecked" Value="True">
          <Setter Property="Background" Value="#F1C21B"/>
          <Setter Property="Foreground" Value="#161616"/>
        </Trigger>
        <Trigger Property="IsEnabled" Value="False">
          <Setter Property="Opacity" Value="0.35"/>
        </Trigger>
      </Style.Triggers>
    </Style>
    <Style x:Key="Fold" TargetType="ToggleButton">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Height" Value="30"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ToggleButton">
            <Border x:Name="Bd" Background="#393939" BorderBrush="#525252" BorderThickness="0,0,0,1"
                    CornerRadius="3" Padding="10,0">
              <Grid>
                <ContentPresenter VerticalAlignment="Center" HorizontalAlignment="Left"/>
                <Path x:Name="Chev" HorizontalAlignment="Right" VerticalAlignment="Center"
                      Data="M0,0 L4,4 L8,0" Stroke="#A8A8A8" StrokeThickness="1.5"
                      RenderTransformOrigin="0.5,0.5">
                  <Path.RenderTransform>
                    <RotateTransform Angle="0"/>
                  </Path.RenderTransform>
                </Path>
              </Grid>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsChecked" Value="True">
                <Setter TargetName="Chev" Property="RenderTransform">
                  <Setter.Value>
                    <RotateTransform Angle="180"/>
                  </Setter.Value>
                </Setter>
              </Trigger>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="Bd" Property="BorderBrush" Value="#F1C21B"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style x:Key="Switch" TargetType="ToggleButton">
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ToggleButton">
            <StackPanel Orientation="Horizontal" Background="Transparent">
              <Grid Width="38" Height="20" VerticalAlignment="Center">
                <Border x:Name="Track" CornerRadius="10" Background="#525252"/>
                <Ellipse x:Name="Knob" Width="14" Height="14" Fill="#F4F4F4"
                         HorizontalAlignment="Left" Margin="3,0,0,0"/>
              </Grid>
              <ContentPresenter VerticalAlignment="Center" Margin="10,0,0,0"/>
            </StackPanel>
            <ControlTemplate.Triggers>
              <Trigger Property="IsChecked" Value="True">
                <Setter TargetName="Track" Property="Background" Value="#F1C21B"/>
                <Setter TargetName="Knob" Property="HorizontalAlignment" Value="Right"/>
                <Setter TargetName="Knob" Property="Margin" Value="0,0,3,0"/>
                <Setter TargetName="Knob" Property="Fill" Value="#161616"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
  </Window.Resources>

  <Grid Margin="20">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <StackPanel Grid.Row="0" Margin="0,0,0,14">
      <TextBlock Text="DWG to Revit" Foreground="#F4F4F4" FontSize="20" FontWeight="SemiBold"/>
      <TextBlock Text="Map DWG layers to Revit elements, then build walls, doors, windows, columns and grids."
                 Foreground="#A8A8A8" Margin="0,4,0,0"/>
    </StackPanel>

    <Border Grid.Row="1" Background="#262626" CornerRadius="6" Padding="16,12" Margin="0,0,0,14">
      <Grid>
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="Auto"/>
          <ColumnDefinition Width="*"/>
          <ColumnDefinition Width="Auto"/>
        </Grid.ColumnDefinitions>
        <TextBlock Text="Source DWG" Foreground="#A8A8A8" VerticalAlignment="Center" Margin="0,0,12,0"/>
        <ComboBox x:Name="cbDwg" Grid.Column="1"/>
        <ToggleButton x:Name="tgReplace" Grid.Column="2" Style="{StaticResource Switch}"
                      Margin="24,0,0,0" IsChecked="True" VerticalAlignment="Center">
          <TextBlock Text="Replace previous result" Foreground="#F4F4F4"/>
        </ToggleButton>
      </Grid>
    </Border>

    <Border Grid.Row="2" Background="#262626" CornerRadius="6" Padding="16">
      <Grid>
        <Grid.RowDefinitions>
          <RowDefinition Height="Auto"/>
          <RowDefinition Height="Auto"/>
          <RowDefinition Height="*"/>
        </Grid.RowDefinitions>
        <Grid Grid.Row="0" Margin="0,0,0,12">
          <TextBox x:Name="tbSearch"/>
          <TextBlock x:Name="tbSearchHint" Text="Filter layers..." Foreground="#8D8D8D"
                     IsHitTestVisible="False" Margin="10,0,0,0" VerticalAlignment="Center"/>
        </Grid>
        <Grid Grid.Row="1" Margin="0,0,14,6">
          <Grid.ColumnDefinitions>
            <ColumnDefinition Width="*"/>
            <ColumnDefinition Width="150"/>
            <ColumnDefinition Width="200"/>
            <ColumnDefinition Width="170"/>
            <ColumnDefinition Width="320"/>
          </Grid.ColumnDefinitions>
          <TextBlock Text="LAYER" Foreground="#A8A8A8" FontSize="11" FontWeight="SemiBold"/>
          <TextBlock Grid.Column="1" Text="CATEGORY" Foreground="#A8A8A8" FontSize="11" FontWeight="SemiBold"/>
          <TextBlock Grid.Column="2" Text="DRAW FROM" Foreground="#A8A8A8" FontSize="11" FontWeight="SemiBold"/>
          <TextBlock Grid.Column="3" Text="MODE" Foreground="#A8A8A8" FontSize="11" FontWeight="SemiBold"/>
          <TextBlock Grid.Column="4" Text="FAMILY TYPE" Foreground="#A8A8A8" FontSize="11" FontWeight="SemiBold"/>
        </Grid>
        <ScrollViewer Grid.Row="2" VerticalScrollBarVisibility="Auto">
          <StackPanel x:Name="spRows" Margin="0,0,14,0"/>
        </ScrollViewer>
      </Grid>
    </Border>

    <Grid Grid.Row="3" Margin="0,14,0,0">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="Auto"/>
      </Grid.ColumnDefinitions>
      <TextBlock x:Name="tbStatus" Foreground="#A8A8A8" VerticalAlignment="Center" TextWrapping="Wrap"/>
      <StackPanel Grid.Column="1" Orientation="Horizontal">
        <Button x:Name="btnCancel" Content="Cancel"/>
        <Button x:Name="btnBuild" Content="Create Elements" Style="{StaticResource Primary}"/>
      </StackPanel>
    </Grid>
  </Grid>
</Window>
"""

ROW_XAML = u"""
<Border xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        BorderBrush="#393939" BorderThickness="0,0,0,1" Padding="0,10,0,10">
  <StackPanel>
    <Grid>
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="150"/>
        <ColumnDefinition Width="200"/>
        <ColumnDefinition Width="170"/>
        <ColumnDefinition Width="320"/>
      </Grid.ColumnDefinitions>
      <StackPanel Grid.Column="0" VerticalAlignment="Center" Margin="0,0,12,0">
        <TextBlock Foreground="#F4F4F4" TextTrimming="CharacterEllipsis"/>
        <TextBlock Foreground="#A8A8A8" FontSize="11"/>
      </StackPanel>
      <ComboBox Grid.Column="1" Margin="0,0,10,0"/>
      <StackPanel Grid.Column="3" Orientation="Horizontal" VerticalAlignment="Center">
        <ToggleButton Content="Single" Style="{DynamicResource Seg}" Margin="0,0,4,0"/>
        <ToggleButton Content="Multiple" Style="{DynamicResource Seg}"/>
      </StackPanel>
      <ComboBox Grid.Column="4"/>
      <ToggleButton Grid.Column="4" Style="{DynamicResource Fold}" Visibility="Collapsed"/>
      <StackPanel Grid.Column="2" Orientation="Horizontal" VerticalAlignment="Center" Visibility="Collapsed">
        <ToggleButton Content="Single line" Style="{DynamicResource Seg}" Margin="0,0,4,0"
                      ToolTip="Each drawn line becomes the element's path"/>
        <ToggleButton Content="Two lines" Style="{DynamicResource Seg}"
                      ToolTip="The centerline between two parallel lines becomes the path"/>
      </StackPanel>
    </Grid>
    <Border Margin="0,10,0,0" Padding="12" Background="#161616" CornerRadius="4" Visibility="Collapsed">
      <StackPanel>
        <Grid Margin="0,0,0,6">
          <Grid.ColumnDefinitions>
            <ColumnDefinition Width="*"/>
            <ColumnDefinition Width="160"/>
            <ColumnDefinition Width="120"/>
            <ColumnDefinition Width="30"/>
          </Grid.ColumnDefinitions>
          <TextBlock Text="FAMILY TYPE" Foreground="#A8A8A8" FontSize="11"/>
          <TextBlock Grid.Column="1" Text="EVALUATOR" Foreground="#A8A8A8" FontSize="11"/>
          <TextBlock Grid.Column="2" Text="SIZE (MM)" Foreground="#A8A8A8" FontSize="11"/>
        </Grid>
        <Grid Margin="0,0,0,6" Visibility="Collapsed">
          <Grid.ColumnDefinitions>
            <ColumnDefinition Width="*"/>
            <ColumnDefinition Width="160"/>
            <ColumnDefinition Width="250"/>
            <ColumnDefinition Width="30"/>
          </Grid.ColumnDefinitions>
          <TextBlock Text="FAMILY TYPE" Foreground="#A8A8A8" FontSize="11"/>
          <TextBlock Grid.Column="1" Text="EVALUATOR" Foreground="#A8A8A8" FontSize="11"/>
          <TextBlock Grid.Column="2" Text="WIDTH &#x00D7; LENGTH (MM)" Foreground="#A8A8A8" FontSize="11"/>
          <TextBlock Grid.Column="2" Text="ONE SIZE" Foreground="#A8A8A8" FontSize="11"
                     HorizontalAlignment="Right" Margin="0,0,4,0"/>
        </Grid>
        <StackPanel/>
        <Grid>
          <Grid.ColumnDefinitions>
            <ColumnDefinition Width="Auto"/>
            <ColumnDefinition Width="*"/>
          </Grid.ColumnDefinitions>
          <Button Content="+ Add rule" Style="{DynamicResource Ghost}"/>
          <TextBlock Grid.Column="1" Foreground="#8D8D8D" FontSize="11" VerticalAlignment="Center"
                     Margin="14,0,0,0" TextWrapping="Wrap"/>
        </Grid>
      </StackPanel>
    </Border>
  </StackPanel>
</Border>
"""

RULE_XAML = u"""
<Grid xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" Margin="0,0,0,6">
  <Grid.ColumnDefinitions>
    <ColumnDefinition Width="*"/>
    <ColumnDefinition Width="160"/>
    <ColumnDefinition Width="120"/>
    <ColumnDefinition Width="30"/>
  </Grid.ColumnDefinitions>
  <ComboBox Grid.Column="0" Margin="0,0,8,0"/>
  <ComboBox Grid.Column="1" Margin="0,0,8,0"/>
  <TextBox Grid.Column="2" Margin="0,0,0,0"/>
  <Button Grid.Column="3" Content="&#x2715;" Style="{DynamicResource Icon}"/>
</Grid>
"""


COLUMN_RULE_XAML = u"""
<Grid xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" Margin="0,0,0,6">
  <Grid.ColumnDefinitions>
    <ColumnDefinition Width="*"/>
    <ColumnDefinition Width="160"/>
    <ColumnDefinition Width="250"/>
    <ColumnDefinition Width="30"/>
  </Grid.ColumnDefinitions>
  <ComboBox Grid.Column="0" Margin="0,0,8,0"/>
  <ComboBox Grid.Column="1" Margin="0,0,8,0"/>
  <Grid Grid.Column="2">
    <Grid.ColumnDefinitions>
      <ColumnDefinition Width="*"/>
      <ColumnDefinition Width="18"/>
      <ColumnDefinition Width="*"/>
      <ColumnDefinition Width="Auto"/>
    </Grid.ColumnDefinitions>
    <TextBox Grid.Column="0" ToolTip="Width (mm)"/>
    <TextBlock Grid.Column="1" Text="&#x00D7;" Foreground="#A8A8A8"
               HorizontalAlignment="Center" VerticalAlignment="Center"/>
    <TextBox Grid.Column="2" ToolTip="Length (mm)"/>
    <ToggleButton Grid.Column="3" Style="{DynamicResource Switch}" Margin="10,0,0,0"
                  VerticalAlignment="Center" ToolTip="Square or round column: one size"/>
  </Grid>
  <Button Grid.Column="3" Content="&#x2715;" Style="{DynamicResource Icon}"/>
</Grid>
"""


def dwg_key(inst):
    t = doc.GetElement(inst.GetTypeId())
    return el_name(t) if t is not None else "DWG {0}".format(eid_int(inst.Id))


def dwg_level(inst):
    """Level the DWG belongs to: its view's level, its Base Level, or the
    highest level at or below the drawing."""
    if inst.ViewSpecific:
        v = doc.GetElement(inst.OwnerViewId)
        lv = getattr(v, "GenLevel", None) if v is not None else None
        if lv is not None:
            return lv
    try:
        p = inst.get_Parameter(BuiltInParameter.IMPORT_BASE_LEVEL)
        if p is not None:
            lv = doc.GetElement(p.AsElementId())
            if isinstance(lv, Level):
                return lv
    except Exception:
        pass
    lv = doc.GetElement(inst.LevelId)
    if isinstance(lv, Level):
        return lv
    levels = sorted(FilteredElementCollector(doc).OfClass(Level), key=lambda l: l.ProjectElevation)
    if not levels:
        return None
    bb = inst.get_BoundingBox(None)
    if bb is None:
        return levels[0]
    below = [l for l in levels if l.ProjectElevation <= bb.Min.Z + 1.0 * MM]
    return below[-1] if below else levels[0]


def show_window(imports, type_opts, store):
    win = XamlReader.Parse(XAML)
    f = win.FindName
    cb_dwg, sp_rows = f("cbDwg"), f("spRows")
    tb_search, tb_hint = f("tbSearch"), f("tbSearchHint")
    tg_replace, tb_status = f("tgReplace"), f("tbStatus")

    rows = []
    cache = {}
    result = [None]
    settings = store.get("_settings", {})
    if not isinstance(settings, dict):
        settings = {}

    for inst in imports:
        kind = "Linked" if inst.IsLinked else "Imported"
        view = ""
        if inst.ViewSpecific:
            v = doc.GetElement(inst.OwnerViewId)
            view = u"  \u00b7  current view only: {0}".format(el_name(v)) if v is not None else ""
        cb_dwg.Items.Add(u"{0}  \u00b7  {1}{2}".format(dwg_key(inst), kind, view))
    tg_replace.IsChecked = settings.get("replace", True)

    # ---------- rows ----------

    def labels_for(role):
        return [o[0] for o in type_opts.get(role, [])]

    def add_rule(row, type_label=None, ev="Equal", value=u""):
        is_col = row['role'].SelectedItem == "Columns"
        el = XamlReader.Parse(COLUMN_RULE_XAML if is_col else RULE_XAML)
        cmb_t, cmb_e, btn = el.Children[0], el.Children[1], el.Children[3]
        labels = labels_for(row['role'].SelectedItem)
        for lbl in labels:
            cmb_t.Items.Add(lbl)
        if labels:
            cmb_t.SelectedIndex = labels.index(type_label) if type_label in labels else 0
        for e in EVALUATORS:
            cmb_e.Items.Add(e)
        cmb_e.SelectedIndex = EVALUATORS.index(ev) if ev in EVALUATORS else 0
        if is_col:
            size = el.Children[2]
            tb_w, times, tb_l, tg_one = (size.Children[0], size.Children[1],
                                         size.Children[2], size.Children[3])
            parts = [x.strip() for x in value.lower().replace(u"\u00d7", "x").split("x") if x.strip()]
            tb_w.Text = parts[0] if parts else u""
            tb_l.Text = parts[1] if len(parts) > 1 else u""
            tg_one.IsChecked = len(parts) == 1

            def set_one(sender, args):
                one = bool(tg_one.IsChecked)
                times.Visibility = Visibility.Collapsed if one else Visibility.Visible
                tb_l.Visibility = Visibility.Collapsed if one else Visibility.Visible
                WpfGrid.SetColumnSpan(tb_w, 3 if one else 1)
                tb_w.ToolTip = u"Size (mm) of the square side or round diameter" if one else u"Width (mm)"

            def get_text():
                if tg_one.IsChecked:
                    return tb_w.Text.strip()
                return u"{0}x{1}".format(tb_w.Text.strip(), tb_l.Text.strip())

            set_one(None, None)
            tg_one.Click += RoutedEventHandler(set_one)
        else:
            tb_v = el.Children[2]
            tb_v.Text = value

            def get_text():
                return tb_v.Text.strip()
        rec = {'el': el, 'type': cmb_t, 'ev': cmb_e, 'get_text': get_text}

        def on_remove(sender, args):
            row['rules_list'].Children.Remove(el)
            row['rules'].remove(rec)
            update_fold(row)

        btn.Click += RoutedEventHandler(on_remove)
        row['rules_list'].Children.Add(el)
        row['rules'].append(rec)
        update_fold(row)

    def update_fold(row):
        row['fold'].Content = u"Add Rules"
        row['fold'].IsChecked = row['expanded']
        multi = row['mode'] == 'multiple'
        row['rules_box'].Visibility = Visibility.Visible if multi and row['expanded'] \
            else Visibility.Collapsed

    def clear_rules(row):
        row['rules_list'].Children.Clear()
        del row['rules'][:]

    def apply_mode(row):
        role = row['role'].SelectedItem
        geo = role in GEOM_ROLES
        row['geom_panel'].Visibility = Visibility.Visible if geo else Visibility.Collapsed
        row['btn_line'].IsChecked = row['geom'] == 'single'
        row['btn_pair'].IsChecked = row['geom'] == 'parallel'
        sized = role in SIZED_ROLES and not (geo and row['geom'] == 'single')
        if not sized:
            row['mode'] = 'single'
        multi = row['mode'] == 'multiple'
        row['btn_single'].IsChecked = not multi
        row['btn_multi'].IsChecked = multi
        row['btn_single'].IsEnabled = sized
        row['btn_multi'].IsEnabled = sized
        row['type'].Visibility = Visibility.Collapsed if multi else Visibility.Visible
        row['fold'].Visibility = Visibility.Visible if multi else Visibility.Collapsed
        row['hint'].Text = SIZE_HINT.get(role, u"")
        row['head'].Visibility = Visibility.Collapsed if role == "Columns" else Visibility.Visible
        row['head_col'].Visibility = Visibility.Visible if role == "Columns" else Visibility.Collapsed
        if multi and not row['rules']:
            row['expanded'] = True
            add_rule(row)
        update_fold(row)

    def fill_single(row, wanted):
        cmb = row['type']
        cmb.Items.Clear()
        labels = labels_for(row['role'].SelectedItem)
        for lbl in labels:
            cmb.Items.Add(lbl)
        cmb.IsEnabled = bool(labels)
        if labels:
            cmb.SelectedIndex = labels.index(wanted) if wanted in labels else 0

    def default_geom(role):
        return 'single' if role == "Railings" else 'parallel'

    def make_geom_handler(row, geom):
        def handler(sender, args):
            row['geom'] = geom
            apply_mode(row)
        return handler

    def make_role_handler(row):
        def handler(sender, args):
            row['geom'] = default_geom(row['role'].SelectedItem)
            clear_rules(row)
            fill_single(row, None)
            apply_mode(row)
        return handler

    def make_mode_handler(row, mode):
        def handler(sender, args):
            if mode == 'multiple' and row['mode'] != 'multiple':
                row['expanded'] = True
            row['mode'] = mode
            apply_mode(row)
        return handler

    def make_fold_handler(row):
        def handler(sender, args):
            row['expanded'] = bool(row['fold'].IsChecked)
            update_fold(row)
        return handler

    def make_add_handler(row):
        def handler(sender, args):
            add_rule(row)
        return handler

    def build_row(name, rec, saved):
        root = XamlReader.Parse(ROW_XAML)
        body = root.Child
        top = body.Children[0]
        texts = top.Children[0].Children
        texts[0].Text = name
        texts[0].ToolTip = name
        texts[1].Text = u"{0} curves  \u00b7  {1} blocks".format(len(rec['items']), len(rec['blocks']))
        segs = top.Children[2].Children
        rules_box = body.Children[1]
        inner = rules_box.Child
        footer = inner.Children[3]
        row = {'layer': name, 'el': root, 'role': top.Children[1], 'type': top.Children[3],
               'btn_single': segs[0], 'btn_multi': segs[1], 'rules_box': rules_box,
               'rules_list': inner.Children[2],
               'head': inner.Children[0], 'head_col': inner.Children[1], 'hint': footer.Children[1],
               'fold': top.Children[4], 'rules': [], 'mode': 'single', 'expanded': False,
               'geom_panel': top.Children[5], 'btn_line': top.Children[5].Children[0],
               'btn_pair': top.Children[5].Children[1], 'geom': 'parallel'}
        for r in ROLES:
            row['role'].Items.Add(r)
        entry = saved if isinstance(saved, dict) else {}
        role = entry.get('role', "Ignore")
        row['role'].SelectedIndex = ROLES.index(role) if role in ROLES else 0
        fill_single(row, entry.get('single'))
        row['mode'] = entry.get('mode', 'single')
        row['geom'] = entry.get('geom') or default_geom(role)
        for r in entry.get('rules', []):
            add_rule(row, r[0], r[1], r[2])
        apply_mode(row)
        row['role'].SelectionChanged += SelectionChangedEventHandler(make_role_handler(row))
        row['btn_single'].Click += RoutedEventHandler(make_mode_handler(row, 'single'))
        row['btn_multi'].Click += RoutedEventHandler(make_mode_handler(row, 'multiple'))
        footer.Children[0].Click += RoutedEventHandler(make_add_handler(row))
        row['fold'].Click += RoutedEventHandler(make_fold_handler(row))
        row['btn_line'].Click += RoutedEventHandler(make_geom_handler(row, 'single'))
        row['btn_pair'].Click += RoutedEventHandler(make_geom_handler(row, 'parallel'))
        return row

    def load_layers(sender, args):
        idx = cb_dwg.SelectedIndex
        if idx < 0:
            return
        inst = imports[idx]
        key = eid_int(inst.Id)
        if key not in cache:
            cache[key] = read_dwg(inst)
        layers = cache[key]
        saved = store.get(dwg_key(inst), {})
        if not isinstance(saved, dict):
            saved = {}
        sp_rows.Children.Clear()
        del rows[:]
        for name in sorted(layers.keys(), key=lambda n: n.lower()):
            row = build_row(name, layers[name], saved.get(name))
            sp_rows.Children.Add(row['el'])
            rows.append(row)
        apply_filter(None, None)
        lv = dwg_level(inst)
        if not rows:
            tb_status.Text = u"No curves found in this DWG. Is it loaded and visible?"
        elif lv is None:
            tb_status.Text = u"{0} layers read. Couldn't find the DWG's level.".format(len(rows))
        else:
            tb_status.Text = u"{0} layers read. Elements will be placed on {1}, the DWG's level.".format(
                len(rows), el_name(lv))

    def apply_filter(sender, args):
        text = tb_search.Text.strip().lower()
        tb_hint.Visibility = Visibility.Collapsed if text else Visibility.Visible
        for row in rows:
            show = (not text) or (text in row['layer'].lower())
            row['el'].Visibility = Visibility.Visible if show else Visibility.Collapsed

    # ---------- build ----------

    def on_build(sender, args):
        if cb_dwg.SelectedIndex < 0 or not rows:
            tb_status.Text = u"Pick a DWG with layers first."
            return
        mapping = {}
        for row in rows:
            role = row['role'].SelectedItem
            if not role or role == "Ignore":
                continue
            if not labels_for(role):
                tb_status.Text = u"Layer '{0}': no {1} types are loaded in the project.".format(
                    row['layer'], role.lower())
                return
            entry = {'role': role, 'mode': row['mode'], 'single': row['type'].SelectedItem,
                     'rules': [], 'geom': row['geom'] if role in GEOM_ROLES else None}
            if row['mode'] == 'multiple':
                row['expanded'] = True
                update_fold(row)
                if not row['rules']:
                    tb_status.Text = u"Layer '{0}': add at least one rule.".format(row['layer'])
                    return
                for k, r in enumerate(row['rules']):
                    try:
                        parse_size(r['get_text']())
                    except ValueError:
                        tb_status.Text = u"Layer '{0}', rule {1}: every size box needs a number " \
                                         u"in mm.".format(row['layer'], k + 1)
                        return
                    entry['rules'].append([r['type'].SelectedItem, r['ev'].SelectedItem,
                                           r['get_text']()])
            mapping[row['layer']] = entry
        if not mapping:
            tb_status.Text = u"Map at least one layer to an element category."
            return
        inst = imports[cb_dwg.SelectedIndex]
        base = dwg_level(inst)
        if base is None:
            tb_status.Text = u"Couldn't find the DWG's level. Link it into a plan view or set its Base Level."
            return
        result[0] = {
            'inst': inst, 'layers': cache[eid_int(inst.Id)], 'mapping': mapping,
            'base': base, 'replace': bool(tg_replace.IsChecked),
        }
        win.Close()

    def on_cancel(sender, args):
        win.Close()

    frame = DispatcherFrame()

    def on_closed(sender, args):
        frame.Continue = False

    cb_dwg.SelectionChanged += SelectionChangedEventHandler(load_layers)
    tb_search.TextChanged += TextChangedEventHandler(apply_filter)
    f("btnBuild").Click += RoutedEventHandler(on_build)
    f("btnCancel").Click += RoutedEventHandler(on_cancel)
    win.Closed += EventHandler(on_closed)

    start = 0
    for i, inst in enumerate(imports):
        if dwg_key(inst) == store.get("_last_dwg"):
            start = i
    cb_dwg.SelectedIndex = start

    win.Show()
    Dispatcher.PushFrame(frame)
    return result[0]


# =====================================================================
# RUN
# =====================================================================

def run_tx(name, fn, report):
    t = Transaction(doc, name)
    t.Start()
    try:
        fn()
        t.Commit()
        return True
    except Exception as e:
        t.RollBack()
        report.issue(u"{0} failed: {1}".format(name, e))
        return False


def runtime_entry(entry, type_opts, report, layer):
    """Labels saved in the UI -> element ids and parsed sizes."""
    ids = dict(type_opts.get(entry['role'], []))
    out = {'mode': entry['mode'], 'single': ids.get(entry['single']), 'rules': [],
           'geom': entry.get('geom') or 'parallel'}
    if entry['mode'] == 'multiple':
        for lbl, ev, text in entry['rules']:
            if lbl not in ids:
                report.issue(u"Layer '{0}': a rule's type no longer exists, rule skipped".format(layer))
                continue
            out['rules'].append({'type': ids[lbl], 'ev': ev, 'vals': parse_size(text)})
        if not out['rules']:
            return None
    elif out['single'] is None:
        report.issue(u"Layer '{0}': the chosen type no longer exists".format(layer))
        return None
    return out


def run(cfg, type_opts, store):
    inst = cfg['inst']
    src = inst.UniqueId
    level = cfg['base']
    z = level.ProjectElevation
    above = [lv for lv in FilteredElementCollector(doc).OfClass(Level)
             if lv.Elevation > level.Elevation + 1e-6]
    cfg['top'] = min(above, key=lambda lv: lv.Elevation) if above else None
    cfg['height'] = DEFAULT_HEIGHT
    cfg['bridge'] = 3000.0 * MM
    report = Report()

    jobs = {}
    for layer, entry in cfg['mapping'].items():
        rt = runtime_entry(entry, type_opts, report, layer)
        if rt is None:
            continue
        items = cfg['layers'].get(layer, {'items': []})['items']
        jobs.setdefault(entry['role'], []).append((layer, rt, items))

    clusters = {}
    for role in ("Doors", "Windows", "Columns"):
        for layer, rt, items in jobs.get(role, []):
            clusters[(role, layer)] = cluster_items(items, 20.0 * MM)
    open_bbs = [c['bb'] for (role, layer), cl in clusters.items()
                if role in ("Doors", "Windows") for c in cl]

    tg = TransactionGroup(doc, "DWG to Revit")
    tg.Start()
    schema = [None]

    def prepare():
        schema[0] = get_schema(SRC_GUID, "BDare95DwgToRevitSource", "SourceDwg", True)
        if cfg['replace']:
            old = [i for i in previous_results(src) if doc.GetElement(i) is not None]
            if old:
                doc.Delete(List[ElementId](old))
                report.counts["Previous result removed"] = len(old)

    def do_walls():
        for layer, rt, items in jobs["Walls"]:
            build_walls(items, TypeChooser(rt, TOL["Walls"]), rt['geom'], cfg, level, z,
                        schema[0], src, report, open_bbs)

    def do_railings():
        for layer, rt, items in jobs["Railings"]:
            build_railings(items, TypeChooser(rt, TOL["Railings"]), rt['geom'], level, z,
                           schema[0], src, report)

    def do_openings(role):
        for layer, rt, items in jobs[role]:
            build_openings(clusters[(role, layer)], role, TypeChooser(rt, TOL[role]),
                           level, z, schema[0], src, report)

    def do_columns():
        for layer, rt, items in jobs["Columns"]:
            build_columns(clusters[("Columns", layer)], TypeChooser(rt, TOL["Columns"]), cfg,
                          level, z, schema[0], src, report)

    def do_grids():
        for layer, rt, items in jobs["Grids"]:
            build_grids(items, rt['single'], schema[0], src, report)

    ok = run_tx("DWG to Revit - Prepare", prepare, report)
    if ok and "Walls" in jobs:
        run_tx("DWG to Revit - Walls", do_walls, report)
    if ok and "Railings" in jobs:
        run_tx("DWG to Revit - Railings", do_railings, report)
    for role in ("Doors", "Windows"):
        if ok and role in jobs:
            run_tx("DWG to Revit - " + role, lambda r=role: do_openings(r), report)
    if ok and "Columns" in jobs:
        run_tx("DWG to Revit - Columns", do_columns, report)
    if ok and "Grids" in jobs:
        run_tx("DWG to Revit - Grids", do_grids, report)

    def save():
        key = dwg_key(inst)
        store[key] = cfg['mapping']
        store["_settings"] = {'replace': cfg['replace']}
        store["_last_dwg"] = key
        save_store(store)

    if ok:
        run_tx("DWG to Revit - Save mapping", save, report)
    tg.Assimilate()

    created = [i for i in report.created if doc.GetElement(i) is not None]
    if created:
        uidoc.Selection.SetElementIds(List[ElementId](created))

    lines = []
    for k in ("Walls", "Railings", "Doors", "Windows", "Columns", "Grids", "Previous result removed"):
        if k in report.counts:
            lines.append(u"{0}: {1}".format(k, report.counts[k]))
    if not lines:
        lines.append(u"Nothing was created.")
    if report.issues:
        lines.append(u"")
        lines.append(u"Notes:")
        for msg, n in sorted(report.issues.items(), key=lambda kv: -kv[1]):
            lines.append(u"\u2022 {0}{1}".format(msg, u"  (x{0})".format(n) if n > 1 else u""))
    td = TaskDialog("DWG to Revit")
    td.MainInstruction = u"Build finished"
    td.MainContent = u"\n".join(lines)
    td.Show()


def main():
    imports = [i for i in FilteredElementCollector(doc).OfClass(ImportInstance)]
    if not imports:
        TaskDialog.Show("DWG to Revit", "No linked or imported DWG was found in this project.\n\n"
                                        "Link the DWG plan into a plan view first.")
        return
    type_opts = build_type_options()
    store = load_store()
    cfg = show_window(imports, type_opts, store)
    if cfg is None:
        return
    run(cfg, type_opts, store)


main()
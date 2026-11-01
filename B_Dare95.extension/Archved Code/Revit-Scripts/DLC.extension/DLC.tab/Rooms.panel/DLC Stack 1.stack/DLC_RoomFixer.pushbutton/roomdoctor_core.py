# -*- coding: utf-8 -*-
"""roomdoctor_core - DLC Room Doctor diagnosis logic.

Pure Python (no Revit imports), IronPython 2.7 / CPython 3 compatible.
Builds on roomgaps_core (Chain, Gap, analyse).

For one unbounded room point it answers:
  * is the point inside an element body (wall / column)?
  * in which compass directions does the room "leak" to infinity?
  * which gaps do those leak rays pass through?
  * which NON-bounding elements stand closer than the first real boundary
    (i.e. elements the room is relying on but Revit ignores)?
and turns that into a short, ranked list of candidate causes.

It also plans the what-if tests (one test per unique fix, shared by all
rooms that list it) and reduces a combined fix to a minimal set.
"""
import math

import roomgaps_core as rg

COMPASS = ["E", "ENE", "NE", "NNE", "N", "NNW", "NW", "WNW",
           "W", "WSW", "SW", "SSW", "S", "SSE", "SE", "ESE"]

_EPS = 1e-9


def compass(angle):
    a = angle % (2.0 * math.pi)
    i = int(round(a / (2.0 * math.pi) * 16.0)) % 16
    return COMPASS[i]


# --------------------------------------------------------------------------
# ray casting
# --------------------------------------------------------------------------
def ray_segment(p, d, a, b):
    """Distance t >= 0 along ray p + t*d to segment ab, or None."""
    ex = b[0] - a[0]
    ey = b[1] - a[1]
    den = d[0] * ey - d[1] * ex
    if abs(den) < 1e-12:
        return None
    wx = a[0] - p[0]
    wy = a[1] - p[1]
    t = (wx * ey - wy * ex) / den
    u = (wx * d[1] - wy * d[0]) / den
    if t >= -1e-9 and -1e-9 <= u <= 1.0 + 1e-9:
        return max(t, 0.0)
    return None


def body_edges(chain, tol):
    """Outline edges of an element body, inflated by tol (cached)."""
    key = "_edges_%r" % tol
    cached = getattr(chain, key, None)
    if cached is not None:
        return cached
    edges = []
    if chain.closed or chain.half_width <= 0.0:
        edges = list(chain.segments())
        setattr(chain, key, edges)
        return edges
    w = chain.half_width + tol
    for a, b in chain.segments():
        dx = b[0] - a[0]
        dy = b[1] - a[1]
        n = math.hypot(dx, dy)
        if n <= _EPS:
            continue
        ux, uy = dx / n, dy / n
        vx, vy = -uy, ux
        a2 = (a[0] - ux * tol, a[1] - uy * tol)
        b2 = (b[0] + ux * tol, b[1] + uy * tol)
        c1 = (a2[0] + vx * w, a2[1] + vy * w)
        c2 = (b2[0] + vx * w, b2[1] + vy * w)
        c3 = (b2[0] - vx * w, b2[1] - vy * w)
        c4 = (a2[0] - vx * w, a2[1] - vy * w)
        edges.extend([(c1, c2), (c2, c3), (c3, c4), (c4, c1)])
    setattr(chain, key, edges)
    return edges


def first_hit(p, d, chains, tol, reach):
    """(t, index) of the first element body hit along the ray, or None."""
    best = None
    for i, c in enumerate(chains):
        for a, b in body_edges(c, tol):
            t = ray_segment(p, d, a, b)
            if t is not None and t <= reach and (best is None or t < best[0]):
                best = (t, i)
    return best


def _near(chains, p, reach):
    """Indices of chains whose bbox lies within reach of p."""
    out = []
    for i, c in enumerate(chains):
        bb = c.bbox
        if bb is None:
            continue
        if bb[0] - reach <= p[0] <= bb[2] + reach and \
                bb[1] - reach <= p[1] <= bb[3] + reach:
            out.append(i)
    return out


class Probe(object):
    def __init__(self):
        self.escapes = []        # compass names that reach `reach`
        self.ray_gaps = []       # gap indices crossed before the first wall
        self.ray_nbs = []        # non-bounding indices before the first wall
        self.rays = 0


def probe(p, bounding, non_bounding, gaps, n_rays=16, reach=300.0, tol=0.03):
    pr = Probe()
    bi = _near(bounding, p, reach)
    ni = _near(non_bounding, p, reach)
    bsub = [bounding[i] for i in bi]
    nsub = [non_bounding[i] for i in ni]
    gseg = [(k, g.a, g.b) for k, g in enumerate(gaps) if g.b is not None]
    for r in range(n_rays):
        ang = 2.0 * math.pi * r / float(n_rays) + 0.013   # avoid exact corners
        d = (math.cos(ang), math.sin(ang))
        pr.rays += 1
        hit = first_hit(p, d, bsub, tol, reach)
        limit = hit[0] if hit else reach
        if hit is None:
            name = compass(ang)
            if name not in pr.escapes:
                pr.escapes.append(name)
        for k, a, b in gseg:
            t = ray_segment(p, d, a, b)
            if t is not None and t <= limit + tol and k not in pr.ray_gaps:
                pr.ray_gaps.append(k)
        nh = first_hit(p, d, nsub, tol, limit)
        if nh is not None:
            idx = ni[nh[1]]
            if idx not in pr.ray_nbs:
                pr.ray_nbs.append(idx)
    return pr


def inside_body(p, chains):
    """First element whose body contains p (room point inside a wall)."""
    for c in chains:
        if not c.is_valid():
            continue
        d = c.body_distance(p)[0]
        if d <= _EPS:
            return c
    return None


# --------------------------------------------------------------------------
# candidates
# --------------------------------------------------------------------------
def gap_distance(p, g):
    if g.b is None:
        return rg.dist(p, g.a)
    return rg.dist_point_segment(p, g.a, g.b)[0]


def candidates(p, pr, gaps, non_bounding, near_count=5, near_radius=100.0,
               max_total=8):
    """Ranked candidate fixes for one room.

    Returns list of ("gap", index) / ("nb", index).
    Order: gaps the leak rays pass through, non-bounding elements standing in
    front of the walls, nearest other gaps, causes of chosen gaps.
    """
    out = []

    def add(item):
        if item not in out and len(out) < max_total:
            out.append(item)

    for k in pr.ray_gaps:
        if gaps[k].b is not None:
            add(("gap", k))
    for i in pr.ray_nbs:
        add(("nb", i))
    ranked = sorted((gap_distance(p, g), k) for k, g in enumerate(gaps)
                    if g.b is not None)
    n = 0
    for d, k in ranked:
        if d > near_radius or n >= near_count:
            break
        add(("gap", k))
        n += 1
    nb_index = dict((id(c), i) for i, c in enumerate(non_bounding))
    for kind, k in list(out):
        if kind == "gap":
            for c in gaps[k].causes:
                if id(c) in nb_index:
                    add(("nb", nb_index[id(c)]))
    return out


# --------------------------------------------------------------------------
# what-if planning
# --------------------------------------------------------------------------
def plan_single_tests(room_candidates):
    """{room_key: [fix, ...]} -> [(fix, [room_key, ...]), ...] unique fixes."""
    order = []
    users = {}
    for rk, cands in room_candidates.items():
        for f in cands:
            if f not in users:
                users[f] = []
                order.append(f)
            users[f].append(rk)
    order.sort(key=lambda f: (-len(users[f]), f))
    return [(f, users[f]) for f in order]


def reduce_set(fixes, encloses):
    """Smallest subset (greedy) that still encloses. encloses(list)->bool.

    Assumes encloses(fixes) is True. Drops one fix at a time and keeps the
    drop if the room still encloses.
    """
    keep = list(fixes)
    for f in list(fixes):
        trial = [x for x in keep if x != f]
        if trial and encloses(trial):
            keep = trial
    return keep


def extend(a, b, by):
    """Segment ab extended by `by` at both ends."""
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    n = math.hypot(dx, dy)
    if n <= _EPS:
        return a, b
    ux, uy = dx / n * by, dy / n * by
    return (a[0] - ux, a[1] - uy), (b[0] + ux, b[1] + uy)


def box(p, size):
    h = size / 2.0
    c = [(p[0] - h, p[1] - h), (p[0] + h, p[1] - h),
         (p[0] + h, p[1] + h), (p[0] - h, p[1] + h)]
    return [(c[i], c[(i + 1) % 4]) for i in range(4)]


def chain_segments(chain):
    return list(chain.segments())

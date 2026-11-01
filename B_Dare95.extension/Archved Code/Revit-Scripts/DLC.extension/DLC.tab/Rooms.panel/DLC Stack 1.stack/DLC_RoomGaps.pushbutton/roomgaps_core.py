# -*- coding: utf-8 -*-
"""roomgaps_core - DLC Room Gaps geometry engine.

Pure Python, no Revit imports, so it can be unit tested outside Revit.
IronPython 2.7 and CPython 3 compatible.

Everything is 2D plan geometry: points are (x, y) tuples in one consistent
unit (the Revit layer passes decimal feet).

Idea
----
A room is "Not Enclosed" when the room-bounding elements around it do not form
a closed loop. Every break in a loop shows up as an OPEN END: an end of a wall
or separation line that touches no other bounding element. The engine:

1. finds all open ends,
2. pairs open ends that face each other  -> the missing segment between them,
3. links remaining open ends to the nearest element face -> "stops short",
4. anything left is a loose end,
5. tags each gap with non-bounding elements sitting in it (the likely cause),
6. ranks gaps by distance to the nearest unbounded room.
"""
import math

KIND_WALL = "Wall"
KIND_CURTAIN = "Curtain wall"
KIND_SEPARATION = "Room separation line"
KIND_COLUMN = "Column"

GAP_PAIR = "pair"
GAP_TO_ELEMENT = "to_element"
GAP_LOOSE = "loose"

_EPS = 1e-9


# --------------------------------------------------------------------------
# basic geometry
# --------------------------------------------------------------------------
def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def dist_point_segment(p, a, b):
    """Return (distance, closest_point) from p to segment ab."""
    ax, ay = a
    bx, by = b
    dx = bx - ax
    dy = by - ay
    l2 = dx * dx + dy * dy
    if l2 <= _EPS * _EPS:
        return dist(p, a), a
    t = ((p[0] - ax) * dx + (p[1] - ay) * dy) / l2
    if t < 0.0:
        t = 0.0
    elif t > 1.0:
        t = 1.0
    c = (ax + t * dx, ay + t * dy)
    return dist(p, c), c


def dist_point_body(p, a, b, hw):
    """Clear distance from p to a wall body: segment ab thickened by hw with
    FLAT end caps (like a real wall). Returns (distance, closest point)."""
    ax, ay = a
    dx = b[0] - ax
    dy = b[1] - ay
    length = math.hypot(dx, dy)
    if length <= _EPS:
        d, c = dist(p, a), a
        return max(0.0, d - hw), c
    ux, uy = dx / length, dy / length          # along the wall
    vx, vy = -uy, ux                           # across the wall
    px, py = p[0] - ax, p[1] - ay
    u = px * ux + py * uy
    v = px * vx + py * vy
    cu = min(max(u, 0.0), length)
    cv = min(max(v, -hw), hw)
    c = (ax + cu * ux + cv * vx, ay + cu * uy + cv * vy)
    return math.hypot(u - cu, v - cv), c


def _cross(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def segments_intersect(p1, p2, q1, q2):
    d1 = _cross(q1, q2, p1)
    d2 = _cross(q1, q2, p2)
    d3 = _cross(p1, p2, q1)
    d4 = _cross(p1, p2, q2)
    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and \
       ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)):
        return True
    return False


def dist_segment_segment(p1, p2, q1, q2):
    if segments_intersect(p1, p2, q1, q2):
        return 0.0
    return min(dist_point_segment(p1, q1, q2)[0],
               dist_point_segment(p2, q1, q2)[0],
               dist_point_segment(q1, p1, p2)[0],
               dist_point_segment(q2, p1, p2)[0])


def point_in_polygon(p, poly):
    x, y = p
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y):
            xc = (xj - xi) * (y - yi) / float(yj - yi) + xi
            if x < xc:
                inside = not inside
        j = i
    return inside


def _clean_points(pts):
    out = []
    for p in pts:
        q = (float(p[0]), float(p[1]))
        if not out or dist(out[-1], q) > _EPS:
            out.append(q)
    return out


# --------------------------------------------------------------------------
# data classes
# --------------------------------------------------------------------------
class Chain(object):
    """One boundary element projected to plan: a polyline (or closed polygon).

    half_width -- half the element thickness (walls); 0 for lines.
    reason     -- None if the element bounds rooms; otherwise a text saying why
                  it does NOT (used to explain gaps).
    ref        -- opaque handle back to the Revit element.
    """

    def __init__(self, pts, half_width=0.0, kind=KIND_WALL, closed=False,
                 ref=None, label="", reason=None):
        self.pts = _clean_points(pts)
        self.closed = bool(closed)
        if self.closed and len(self.pts) > 2 and \
                dist(self.pts[0], self.pts[-1]) <= _EPS:
            self.pts.pop()
        try:
            hw = float(half_width or 0.0)
        except (TypeError, ValueError):
            hw = 0.0
        self.half_width = max(0.0, hw)
        self.kind = kind
        self.ref = ref
        self.label = label
        self.reason = reason
        self._segs = None
        if self.pts:
            xs = [p[0] for p in self.pts]
            ys = [p[1] for p in self.pts]
            self.bbox = (min(xs), min(ys), max(xs), max(ys))
        else:
            self.bbox = None

    def is_valid(self):
        if self.closed:
            return len(self.pts) >= 3
        return len(self.pts) >= 2

    def segments(self):
        if self._segs is None:
            p = self.pts
            segs = [(p[i], p[i + 1]) for i in range(len(p) - 1)]
            if self.closed and len(p) > 2:
                segs.append((p[-1], p[0]))
            self._segs = segs
        return self._segs

    def ends(self):
        if self.closed or len(self.pts) < 2:
            return []
        return [self.pts[0], self.pts[-1]]

    def distance_to(self, p):
        """(centre-line distance, closest point). Inside a polygon -> 0."""
        if self.closed and point_in_polygon(p, self.pts):
            return 0.0, p
        best = None
        for a, b in self.segments():
            d, c = dist_point_segment(p, a, b)
            if best is None or d < best[0]:
                best = (d, c)
        return best

    def body_distance(self, p):
        """(clear distance to the element's body, closest body point)."""
        if self.closed:
            return self.distance_to(p)
        best = None
        for a, b in self.segments():
            d, c = dist_point_body(p, a, b, self.half_width)
            if best is None or d < best[0]:
                best = (d, c)
        return best

    def end_directions(self):
        """Unit vectors pointing OUT of the element at each end."""
        p = self.pts
        out = []
        for e, prev in ((p[0], p[1]), (p[-1], p[-2])):
            dx, dy = e[0] - prev[0], e[1] - prev[1]
            n = math.hypot(dx, dy) or 1.0
            out.append((dx / n, dy / n))
        return out

    def distance_to_segment(self, a, b):
        if self.closed and (point_in_polygon(a, self.pts) or
                            point_in_polygon(b, self.pts)):
            return 0.0
        best = None
        for s1, s2 in self.segments():
            d = dist_segment_segment(a, b, s1, s2)
            if best is None or d < best:
                best = d
        return best

    def __repr__(self):
        return "<Chain %s %s>" % (self.kind, self.label)


class Gap(object):
    def __init__(self, kind, a, b=None, chain_a=None, chain_b=None,
                 length=None):
        self.kind = kind
        self.a = a
        self.b = b
        self.chain_a = chain_a
        self.chain_b = chain_b
        if length is None:
            length = dist(a, b) if b is not None else 0.0
        self.length = length        # CLEAR gap between element bodies
        self.causes = []
        self.bridge = False         # wide opening between two loose ends
        self.nearest_room = None
        self.room_distance = None

    @property
    def mid(self):
        if self.b is None:
            return self.a
        return ((self.a[0] + self.b[0]) / 2.0, (self.a[1] + self.b[1]) / 2.0)

    def __repr__(self):
        return "<Gap %s len=%.3f>" % (self.kind, self.length)


class Result(object):
    def __init__(self):
        self.gaps = []
        self.open_end_count = 0
        self.bounding_count = 0
        self.non_bounding_count = 0


# --------------------------------------------------------------------------
# spatial grid (keeps big levels fast in IronPython)
# --------------------------------------------------------------------------
class _Grid(object):
    MAX_CELLS_PER_ITEM = 4000

    def __init__(self, cell):
        self.cell = float(cell) if cell > 0 else 1.0
        self.cells = {}
        self.oversize = []

    def _rng(self, lo, hi):
        return range(int(math.floor(lo / self.cell)),
                     int(math.floor(hi / self.cell)) + 1)

    def insert(self, idx, bbox, pad):
        xr = self._rng(bbox[0] - pad, bbox[2] + pad)
        yr = self._rng(bbox[1] - pad, bbox[3] + pad)
        if len(xr) * len(yr) > self.MAX_CELLS_PER_ITEM:
            self.oversize.append(idx)      # always returned by query()
            return
        for i in xr:
            for j in yr:
                self.cells.setdefault((i, j), []).append(idx)

    def query(self, p, r=0.0):
        found = set(self.oversize)
        for i in self._rng(p[0] - r, p[0] + r):
            for j in self._rng(p[1] - r, p[1] + r):
                found.update(self.cells.get((i, j), ()))
        return found


# --------------------------------------------------------------------------
# main analysis
# --------------------------------------------------------------------------
def _is_connected(p, own, chains, grid, tol):
    for j in grid.query(p):
        if j == own:
            continue
        other = chains[j]
        d = other.distance_to(p)[0]
        if d <= other.half_width + tol:
            return True
    return False


# an open end only "looks" forward: up to ~105 deg off its own direction.
# Stops it from finding targets behind itself, through its own wall.
_MIN_COS = -0.26


def _in_front(p, direction, q):
    vx, vy = q[0] - p[0], q[1] - p[1]
    n = math.hypot(vx, vy)
    if n <= _EPS:
        return True
    return (vx * direction[0] + vy * direction[1]) / n >= _MIN_COS


def _nearest_body(p, direction, own, chains, grid, reach):
    """Closest other element body in front of the open end, within reach."""
    best = None
    for j in grid.query(p, reach):
        if j == own:
            continue
        d, c = chains[j].body_distance(p)
        if d > reach or not _in_front(p, direction, c):
            continue
        if best is None or d < best[0]:
            best = (d, c, j)
    return best


def _nearest_centre(p, direction, own, chains, grid, reach):
    best = None
    for j in grid.query(p, reach):
        if j == own:
            continue
        d, c = chains[j].distance_to(p)
        if d > reach or not _in_front(p, direction, c):
            continue
        if best is None or d < best:
            best = d
    return best


def analyse(bounding, non_bounding=None, room_points=None,
            tolerance=0.03, max_gap=10.0, bridge_max=0.0):
    """Find the gaps in the room-bounding network.

    bounding     -- list of Chain that DO bound rooms
    non_bounding -- list of Chain that sit on the level but do NOT bound rooms
    room_points  -- list of (ref, (x, y)) for unbounded rooms (for ranking)
    tolerance    -- ends closer than this (+ element half width) are joined
    max_gap      -- largest gap reported as a missing segment
    """
    res = Result()
    chains = [c for c in (bounding or []) if c.is_valid()]
    nbs = [c for c in (non_bounding or []) if c.is_valid()]
    rooms = list(room_points or [])
    res.bounding_count = len(chains)
    res.non_bounding_count = len(nbs)
    tol = max(0.0, float(tolerance))
    max_gap = max(0.0, float(max_gap))

    max_hw = 0.0
    for c in chains:
        if c.half_width > max_hw:
            max_hw = c.half_width
    cell = max(max_gap, tol * 10.0, 1e-3)

    grid = _Grid(cell)
    for i, c in enumerate(chains):
        grid.insert(i, c.bbox, c.half_width + tol)

    # 1. open ends ----------------------------------------------------------
    ends = []          # (chain index, point, outward direction)
    for i, c in enumerate(chains):
        if c.kind == KIND_COLUMN:
            continue
        e = c.ends()
        if not e:
            continue
        if len(c.pts) > 2 and dist(e[0], e[1]) <= tol:
            continue                   # polyline that closes on itself
        for p, direction in zip(e, c.end_directions()):
            if not _is_connected(p, i, chains, grid, tol):
                ends.append((i, p, direction))
    res.open_end_count = len(ends)

    reach = max_gap + max_hw + tol
    centre = [_nearest_centre(p, dr, ci, chains, grid, reach)
              for ci, p, dr in ends]
    body = [_nearest_body(p, dr, ci, chains, grid, max_gap)
            for ci, p, dr in ends]

    # 2. pair open ends that face each other --------------------------------
    egrid = _Grid(cell)
    for k, (ci, p, dr) in enumerate(ends):
        egrid.insert(k, (p[0], p[1], p[0], p[1]), 0.0)
    cands = []
    slack = 2.0 * tol + 1e-9
    for k, (ci, p, dk) in enumerate(ends):
        for m in egrid.query(p, max_gap + max_hw * 2.0):
            if m <= k:
                continue
            cj, q, dm = ends[m]
            if cj == ci:
                continue
            d = dist(p, q)
            if d > max_gap + max_hw * 2.0:
                continue
            if not (_in_front(p, dk, q) and _in_front(q, dm, p)):
                continue
            # only pair if nothing else is clearly closer to either end
            if centre[k] is not None and d > centre[k] + slack:
                continue
            if centre[m] is not None and d > centre[m] + slack:
                continue
            clear = min(chains[cj].body_distance(p)[0],
                        chains[ci].body_distance(q)[0])
            if clear > max_gap:
                continue
            cands.append((d, k, m, clear))
    cands.sort()
    used = set()
    gaps = []
    for d, k, m, clear in cands:
        if k in used or m in used:
            continue
        used.add(k)
        used.add(m)
        gaps.append(Gap(GAP_PAIR, ends[k][1], ends[m][1],
                        chains[ends[k][0]], chains[ends[m][0]], clear))

    # 3./4. stops short / loose -------------------------------------------
    loose = []
    for k, (ci, p, dr) in enumerate(ends):
        if k in used:
            continue
        f = body[k]
        if f is not None:
            d, c, j = f
            gaps.append(Gap(GAP_TO_ELEMENT, p, c, chains[ci], chains[j], d))
            continue
        loose.append(k)

    # 4b. bridge wide openings between loose ends that face each other -------
    if bridge_max > max_gap and len(loose) > 1:
        bc = []
        for x in range(len(loose)):
            k = loose[x]
            ci, p, dk = ends[k]
            for y in range(x + 1, len(loose)):
                m = loose[y]
                cj, q, dm = ends[m]
                if cj == ci:
                    continue
                d = dist(p, q)
                if d <= bridge_max and _in_front(p, dk, q) and \
                        _in_front(q, dm, p):
                    bc.append((d, k, m))
        bc.sort()
        bused = set()
        for d, k, m in bc:
            if k in bused or m in bused:
                continue
            bused.add(k)
            bused.add(m)
            g = Gap(GAP_PAIR, ends[k][1], ends[m][1], chains[ends[k][0]],
                    chains[ends[m][0]], d)
            g.bridge = True
            gaps.append(g)
        loose = [k for k in loose if k not in bused]
    for k in loose:
        gaps.append(Gap(GAP_LOOSE, ends[k][1], None, chains[ends[k][0]], None))

    # 5. likely causes: non-bounding elements sitting in the gap -----------
    if nbs:
        ngrid = _Grid(cell)
        for i, c in enumerate(nbs):
            ngrid.insert(i, c.bbox, c.half_width + tol)
        for g in gaps:
            if g.b is None:
                r = 0.0
            else:
                r = g.length / 2.0
            seen = set()
            for i in ngrid.query(g.mid, r):
                nb = nbs[i]
                if g.b is None:
                    d = nb.distance_to(g.a)[0]
                else:
                    d = nb.distance_to_segment(g.a, g.b)
                if d <= nb.half_width + tol and i not in seen:
                    seen.add(i)
                    g.causes.append(nb)

    # 6. rank by nearest unbounded room -----------------------------------
    if rooms:
        for g in gaps:
            best = None
            for ref, pt in rooms:
                d = dist(g.mid, pt)
                if best is None or d < best[0]:
                    best = (d, ref)
            g.room_distance, g.nearest_room = best

    def _key(g):
        rd = g.room_distance if g.room_distance is not None else float("inf")
        order = {GAP_PAIR: 0, GAP_TO_ELEMENT: 1, GAP_LOOSE: 2}[g.kind]
        return (rd, order, g.length)

    gaps.sort(key=_key)
    res.gaps = gaps
    return res

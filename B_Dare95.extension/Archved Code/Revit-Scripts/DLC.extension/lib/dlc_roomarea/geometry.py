# -*- coding: utf-8 -*-
"""DLC Room Areas - pure geometry engine.

Variable-offset polygon: every boundary edge of a room is pushed outward
(away from the room) by its own distance, adjacent offset edges are joined
by mitre intersection (or a straight step where they are parallel), and any
self-intersection the offset creates is cleaned up before the area is taken.

No Revit imports. Runs unchanged on IronPython 2.7 and CPython 3.
Units are whatever the caller uses (Revit internal feet in production).
"""
from __future__ import division
import math

KIND_WALL = 'WALL'
KIND_COLUMN = 'COLUMN'
KIND_SEPARATION = 'SEPARATION'
KIND_OTHER = 'OTHER'

LENGTH_TOL = 1e-4          # ft  (~0.03 mm) - shorter edges are noise
PARALLEL_TOL = 1e-6        # |sin(angle)| below this = parallel
MITRE_RATIO = 10.0         # mitre longer than this x offset -> bevel


class Edge(object):
    """One straight boundary piece with an outward offset per measure."""
    __slots__ = ('p0', 'p1', 'kind', 'off', 'ref')

    def __init__(self, p0, p1, kind=KIND_OTHER, off=None, ref=None):
        self.p0 = (float(p0[0]), float(p0[1]))
        self.p1 = (float(p1[0]), float(p1[1]))
        self.kind = kind
        self.off = off if off is not None else {}
        self.ref = ref

    def d(self, mode):
        return float(self.off.get(mode, 0.0))

    def length(self):
        return math.hypot(self.p1[0] - self.p0[0], self.p1[1] - self.p0[1])

    def reversed(self):
        return Edge(self.p1, self.p0, self.kind, self.off, self.ref)


# --------------------------------------------------------------------------
# basic helpers
# --------------------------------------------------------------------------
def signed_area(pts):
    """Shoelace. Positive = counter-clockwise."""
    n = len(pts)
    if n < 3:
        return 0.0
    a = 0.0
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        a += x1 * y2 - x2 * y1
    return a / 2.0


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _dedupe(pts, tol):
    out = []
    for p in pts:
        if not out or _dist(out[-1], p) > tol:
            out.append(p)
    while len(out) > 1 and _dist(out[0], out[-1]) <= tol:
        out.pop()
    return out


def point_in_polygon(pt, pts):
    """Ray casting, strict-ish (boundary points are undefined)."""
    x, y = pt
    inside = False
    n = len(pts)
    j = n - 1
    for i in range(n):
        xi, yi = pts[i]
        xj, yj = pts[j]
        if (yi > y) != (yj > y):
            xc = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < xc:
                inside = not inside
        j = i
    return inside


def _interior_point(pts, sign):
    """A point just inside a simple polygon (left of CCW / right of CW)."""
    n = len(pts)
    best, bl = 0, -1.0
    for i in range(n):
        L = _dist(pts[i], pts[(i + 1) % n])
        if L > bl:
            best, bl = i, L
    a = pts[best]
    b = pts[(best + 1) % n]
    mx, my = (a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0
    ux, uy = (b[0] - a[0]) / bl, (b[1] - a[1]) / bl
    lx, ly = -uy, ux                     # left normal
    s = 1e-4 * bl if sign > 0 else -1e-4 * bl
    return (mx + lx * s, my + ly * s)


# --------------------------------------------------------------------------
# loop preparation
# --------------------------------------------------------------------------
def loop_points(edges):
    return [e.p0 for e in edges]


def clean_loop(edges, tol=LENGTH_TOL):
    return [e for e in edges if e.length() > tol]


def reverse_loop(edges):
    return [e.reversed() for e in reversed(edges)]


def orient_loops(loops):
    """Outer loop (largest |area|) counter-clockwise, holes clockwise.

    With that orientation the room is always on the LEFT of travel, so the
    right-hand normal of every edge points away from the room.
    Returns (oriented_loops, outer_index).
    """
    if not loops:
        return [], -1
    areas = [signed_area(loop_points(l)) for l in loops]
    outer = max(range(len(loops)), key=lambda i: abs(areas[i]))
    out = []
    for i, l in enumerate(loops):
        want_positive = (i == outer)
        if (areas[i] > 0) != want_positive:
            l = reverse_loop(l)
        out.append(l)
    return out, outer


# --------------------------------------------------------------------------
# offsetting
# --------------------------------------------------------------------------
def offset_polygon(edges, mode, tol=LENGTH_TOL, parallel_tol=PARALLEL_TOL,
                   mitre_ratio=MITRE_RATIO, report_collapse=False):
    """Offset each edge to its right by edge.d(mode) and rebuild vertices.

    With report_collapse=True returns (pts, collapsed) where collapsed means
    every offset edge now runs backwards - the loop shrank through itself
    (e.g. a shaft smaller than its wall offsets) and encloses nothing.
    """
    lines = []
    for e in edges:
        L = e.length()
        ux = (e.p1[0] - e.p0[0]) / L
        uy = (e.p1[1] - e.p0[1]) / L
        nx, ny = uy, -ux                         # right-hand normal
        d = e.d(mode)
        a = (e.p0[0] + d * nx, e.p0[1] + d * ny)
        b = (e.p1[0] + d * nx, e.p1[1] + d * ny)
        lines.append((a, b, (ux, uy), d, e))

    n = len(lines)
    pts = []
    ends = [None] * n          # end point of each offset edge
    starts = [None] * n        # start point of each offset edge
    for i in range(n):
        a1, b1, u1, d1, e1 = lines[i]
        a2, b2, u2, d2, e2 = lines[(i + 1) % n]
        j = (i + 1) % n
        cross = u1[0] * u2[1] - u1[1] * u2[0]
        if abs(cross) < parallel_tol:
            # parallel: continuation, step (thickness change) or reversal
            pts.append(b1)
            pts.append(a2)
            ends[i], starts[j] = b1, a2
            continue
        dx = a2[0] - a1[0]
        dy = a2[1] - a1[1]
        t = (dx * u2[1] - dy * u2[0]) / cross
        x = (a1[0] + t * u1[0], a1[1] + t * u1[1])
        ref = ((b1[0] + a2[0]) / 2.0, (b1[1] + a2[1]) / 2.0)
        limit = mitre_ratio * max(d1, d2, tol) + _dist(e1.p1, e2.p0)
        if _dist(x, ref) > limit:
            pts.append(b1)                       # bevel - mitre runs away
            pts.append(a2)
            ends[i], starts[j] = b1, a2
        else:
            pts.append(x)
            ends[i], starts[j] = x, x
    pts = _dedupe(pts, tol * 0.1)
    if not report_collapse:
        return pts
    collapsed = True
    for i in range(n):
        u = lines[i][2]
        vx = ends[i][0] - starts[i][0]
        vy = ends[i][1] - starts[i][1]
        if vx * u[0] + vy * u[1] > 0:
            collapsed = False
            break
    return pts, collapsed


# --------------------------------------------------------------------------
# self-intersection cleanup
# --------------------------------------------------------------------------
def _seg_hit(p1, p2, q1, q2, eps=1e-9):
    rx, ry = p2[0] - p1[0], p2[1] - p1[1]
    sx, sy = q2[0] - q1[0], q2[1] - q1[1]
    den = rx * sy - ry * sx
    if abs(den) < 1e-14:
        return None
    qx, qy = q1[0] - p1[0], q1[1] - p1[1]
    t = (qx * sy - qy * sx) / den
    u = (qx * ry - qy * rx) / den
    if -eps <= t <= 1 + eps and -eps <= u <= 1 + eps:
        return (p1[0] + t * rx, p1[1] + t * ry)
    return None


def _first_crossing(pts, tol):
    n = len(pts)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue                         # adjacent through closure
            c, d = pts[j], pts[(j + 1) % n]
            x = _seg_hit(a, b, c, d)
            if x is None:
                continue
            # ignore the trivial touch of a vertex shared by neighbours
            return i, j, x
    return None


def resolve_self_intersections(pts, sign, tol=LENGTH_TOL, max_iter=5000):
    """Split a self-intersecting ring at its crossings.

    Splitting preserves the shoelace sum exactly; loops whose orientation is
    opposite to `sign` are the 'swallowtails' an offset creates and are
    discarded, and loops nested inside another kept loop are dropped so the
    result is the union. Returns (kept_loops, overlap_found).
    """
    stack = [_dedupe(pts, tol * 0.1)]
    done = []
    it = 0
    while stack:
        it += 1
        if it > max_iter:
            raise RuntimeError('Polygon cleanup did not converge')
        poly = _dedupe(stack.pop(), tol * 0.1)
        if len(poly) < 3:
            continue
        hit = _first_crossing(poly, tol)
        if hit is None:
            done.append(poly)
            continue
        i, j, x = hit
        loop1 = [x] + poly[i + 1:j + 1]
        loop2 = poly[:i + 1] + [x] + poly[j + 1:]
        stack.append(loop1)
        stack.append(loop2)

    area_tol = tol * tol
    kept = [p for p in done if signed_area(p) * sign > area_tol]
    if len(kept) < 2:
        return kept, False
    kept.sort(key=lambda p: -abs(signed_area(p)))
    final = []
    overlap = False
    for p in kept:
        probe = _interior_point(p, sign)
        if any(point_in_polygon(probe, q) for q in final):
            overlap = True
            continue
        final.append(p)
    return final, overlap


# --------------------------------------------------------------------------
# public: area of a room after offsets
# --------------------------------------------------------------------------
def compute_area(loops, mode, bridge_columns=True,
                 deduct_freestanding_columns=False, tol=LENGTH_TOL):
    """Area enclosed by the offset boundary for one measure (mode).

    loops : list of lists of Edge (any orientation; first/largest = outer)
    mode  : key into Edge.off, e.g. 'GLA' or 'GFA'
    Returns (area, warnings).
    """
    loops = [clean_loop(l, tol) for l in loops]
    loops = [l for l in loops if len(l) >= 3]
    if not loops:
        return 0.0, ['NO_BOUNDARY']
    oriented, outer = orient_loops(loops)
    total = 0.0
    warnings = []
    for idx, loop in enumerate(oriented):
        is_outer = (idx == outer)
        sign = 1 if is_outer else -1
        kinds = set(e.kind for e in loop)
        work = loop
        if KIND_COLUMN in kinds:
            if kinds == set([KIND_COLUMN]):
                if not is_outer and not deduct_freestanding_columns:
                    continue                     # free-standing column: no deduction
                work = [Edge(e.p0, e.p1, KIND_OTHER, {}, e.ref) for e in loop]
            elif bridge_columns:
                bridged = [e for e in loop if e.kind != KIND_COLUMN]
                if len(bridged) >= 3:
                    work = bridged
                else:
                    warnings.append('COLUMN_BRIDGE_SKIPPED')
                    work = [e if e.kind != KIND_COLUMN else
                            Edge(e.p0, e.p1, KIND_OTHER, {}, e.ref) for e in loop]
            else:
                work = [e if e.kind != KIND_COLUMN else
                        Edge(e.p0, e.p1, KIND_OTHER, {}, e.ref) for e in loop]
        pts, collapsed = offset_polygon(work, mode, tol, report_collapse=True)
        if collapsed:
            continue                             # loop shrank to nothing
        parts, overlap = resolve_self_intersections(pts, sign, tol)
        if overlap:
            warnings.append('SELF_OVERLAP')
        total += sum(signed_area(p) for p in parts)
    return max(total, 0.0), warnings

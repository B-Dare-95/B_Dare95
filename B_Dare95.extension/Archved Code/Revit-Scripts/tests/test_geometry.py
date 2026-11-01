# -*- coding: utf-8 -*-
"""Geometry engine: analytic cases."""
from __future__ import division
import math
from harness import check, close, run_suite
from dlc_roomarea import geometry as g


def poly(P, offs, kinds=None, mode='M'):
    n = len(P)
    if not isinstance(offs, (list, tuple)):
        offs = [offs] * n
    kinds = kinds or [g.KIND_WALL] * n
    return [g.Edge(P[i], P[(i + 1) % n], kinds[i], {mode: offs[i]})
            for i in range(n)]


def rect_pts(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def area(loops, **kw):
    return g.compute_area(loops, 'M', **kw)[0]


def test_zero_offset_is_shoelace():
    P = [(0, 0), (5, 0), (5, 2), (3, 2), (3, 4), (0, 4)]
    close(area([poly(P, 0.0)]), abs(g.signed_area(P)))


def test_uniform_rectangle():
    close(area([poly(rect_pts(0, 0, 4, 3), 0.1)]), 4.2 * 3.2)


def test_orientation_and_start_independent():
    base = area([poly(rect_pts(0, 0, 4, 3), [0.1, 0.2, 0.3, 0.4])])
    close(base, (4 + 0.2 + 0.4) * (3 + 0.1 + 0.3))
    for k in range(4):
        P = rect_pts(0, 0, 4, 3)
        offs = [0.1, 0.2, 0.3, 0.4]
        P = P[k:] + P[:k]
        offs = offs[k:] + offs[:k]
        close(area([poly(P, offs)]), base, msg='rotated start %d' % k)
        close(area([g.reverse_loop(poly(P, offs))]), base, msg='reversed')


def test_mixed_exterior_interior():
    # bottom exterior GFA 0.3, others interior centreline 0.1
    close(area([poly(rect_pts(0, 0, 4, 3), [0.3, 0.1, 0.1, 0.1])]),
          (4.2) * (3 + 0.3 + 0.1))


def test_collinear_step():
    # bottom edge split in two with different offsets -> step
    P = [(0, 0), (2, 0), (4, 0), (4, 3), (0, 3)]
    offs = [0.1, 0.3, 0.0, 0.0, 0.0]
    close(area([poly(P, offs)]), 12 + 2 * 0.1 + 2 * 0.3)


def test_collinear_same_offset_merge():
    P = [(0, 0), (1, 0), (2, 0), (3, 0), (3, 3), (0, 3)]
    close(area([poly(P, 0.25)]), 3.5 * 3.5)


def test_l_shape_reflex_corner():
    P = [(0, 0), (4, 0), (4, 2), (2, 2), (2, 4), (0, 4)]
    d = 0.1
    # offset L: outer dims 4.2 x 4.2 minus notch (2-0.1+... ) computed by hand
    expect = 4.2 * 4.2 - (4.1 - 2.1) * (4.1 - 2.1)
    close(area([poly(P, d)]), expect)


def test_hole_shrinks():
    outer = poly(rect_pts(0, 0, 10, 10), 0.0)
    hole = poly(rect_pts(4, 4, 6, 6), 0.1)
    close(area([outer, hole]), 100 - 1.8 * 1.8)
    # hole given CCW too - engine must orient it
    hole2 = g.reverse_loop(hole)
    close(area([outer, hole2]), 100 - 1.8 * 1.8)


def test_hole_vanishes_when_offset_exceeds():
    outer = poly(rect_pts(0, 0, 10, 10), 0.0)
    hole = poly(rect_pts(4, 4, 4.1, 4.1), 0.1)  # 0.1 hole, offset 0.1 each side
    close(area([outer, hole]), 100.0)


def test_freestanding_column_not_deducted():
    outer = poly(rect_pts(0, 0, 10, 10), 0.0)
    col = poly(rect_pts(4, 4, 4.5, 4.5), 0.0, [g.KIND_COLUMN] * 4)
    close(area([outer, col]), 100.0)
    close(area([outer, col], deduct_freestanding_columns=True), 99.75)


def test_column_in_wall_bridged():
    # pilaster 0.4 wide protruding 0.2 into the room from the bottom wall
    P = [(0, 0), (3, 0), (3, 0.2), (3.4, 0.2), (3.4, 0), (8, 0),
         (8, 5), (0, 5)]
    kinds = [g.KIND_WALL, g.KIND_COLUMN, g.KIND_COLUMN, g.KIND_COLUMN,
             g.KIND_WALL, g.KIND_WALL, g.KIND_WALL, g.KIND_WALL]
    offs = [0.1] * 8
    close(area([poly(P, offs, kinds)]), 8.2 * 5.2)
    # without bridging, columns get offset 0 -> notch stays (0.4 x 0.2 + ...)
    nb = area([poly(P, offs, kinds)], bridge_columns=False)
    check(nb < 8.2 * 5.2, 'unbridged pilaster must reduce area')


def test_column_at_corner_bridged():
    # column fills the bottom-right corner of the room
    P = [(0, 0), (7.5, 0), (7.5, 0.5), (8, 0.5), (8, 5), (0, 5)]
    kinds = [g.KIND_WALL, g.KIND_COLUMN, g.KIND_COLUMN, g.KIND_WALL,
             g.KIND_WALL, g.KIND_WALL]
    close(area([poly(P, 0.1, kinds)]), 8.2 * 5.2)


def test_narrow_notch_closes():
    P = [(0, 0), (1.95, 0), (1.95, 1), (2.05, 1), (2.05, 0), (4, 0),
         (4, 4), (0, 4)]
    close(area([poly(P, 0.1)]), 4.2 * 4.2)


def test_wide_notch_stays():
    P = [(0, 0), (1.5, 0), (1.5, 1), (2.5, 1), (2.5, 0), (4, 0),
         (4, 4), (0, 4)]
    d = 0.1
    # notch 1.0 wide shrinks to 0.8; its depth stays 1.0 (y -0.1 .. 0.9)
    close(area([poly(P, d)]), 4.2 * 4.2 - 0.8 * 1.0)


def test_circle_tessellated():
    r, d, N = 3.0, 0.2, 360
    P = [(r * math.cos(2 * math.pi * k / N), r * math.sin(2 * math.pi * k / N))
         for k in range(N)]
    a = area([poly(P, d)])
    apothem = r * math.cos(math.pi / N) + d
    close(a, N * apothem ** 2 * math.tan(math.pi / N), 1e-9)
    close(a, math.pi * (r + d) ** 2, 2e-3)


def test_semicircle_room_with_mixed_offsets():
    r, N = 4.0, 180
    arc = [(r * math.cos(math.pi * k / N), r * math.sin(math.pi * k / N))
           for k in range(N + 1)]
    P = arc + []     # closes back along the diameter
    offs = [0.3] * N + [0.1]
    a = area([poly(P, offs)])
    # semicircle radius r+0.3 sitting on a line shifted down by 0.1
    expect = 0.5 * math.pi * (r + 0.3) ** 2 + 2 * (r + 0.3) * 0.1
    close(a, expect, 2e-3)


def test_acute_angle_mitre_and_bevel():
    P = [(0, 0), (10, 0), (0, 1)]       # ~5.7 degree tip
    a = area([poly(P, 0.05)])
    check(a > g.signed_area(P), 'offset grows area')
    check(a < g.signed_area(P) + 0.05 * (10 + 10.05 + 1) + 0.6,
          'bevel keeps the sharp tip bounded')


def test_degenerate_inputs():
    check(g.compute_area([], 'M')[0] == 0.0)
    check('NO_BOUNDARY' in g.compute_area([], 'M')[1])
    tiny = poly([(0, 0), (1e-6, 0), (0, 1e-6)], 0.1)
    check(g.compute_area([tiny], 'M')[0] == 0.0)


def test_duplicate_and_zero_length_edges():
    P = [(0, 0), (4, 0), (4, 0), (4, 3), (0, 3)]
    close(area([poly(P, 0.1)]), 4.2 * 3.2)


def test_point_in_polygon():
    sq = rect_pts(0, 0, 1, 1)
    check(g.point_in_polygon((0.5, 0.5), sq))
    check(not g.point_in_polygon((1.5, 0.5), sq))


def test_resolve_bowtie():
    pts = [(0, 0), (2, 2), (2, 0), (0, 2)]     # figure-eight
    parts, _ = g.resolve_self_intersections(pts, 1)
    close(sum(g.signed_area(p) for p in parts), 1.0)
    parts, _ = g.resolve_self_intersections(pts, -1)
    close(sum(g.signed_area(p) for p in parts), -1.0)


TESTS = [test_zero_offset_is_shoelace, test_uniform_rectangle,
         test_orientation_and_start_independent, test_mixed_exterior_interior,
         test_collinear_step, test_collinear_same_offset_merge,
         test_l_shape_reflex_corner, test_hole_shrinks,
         test_hole_vanishes_when_offset_exceeds,
         test_freestanding_column_not_deducted, test_column_in_wall_bridged,
         test_column_at_corner_bridged, test_narrow_notch_closes,
         test_wide_notch_stays, test_circle_tessellated,
         test_semicircle_room_with_mixed_offsets,
         test_acute_angle_mitre_and_bevel, test_degenerate_inputs,
         test_duplicate_and_zero_length_edges, test_point_in_polygon,
         test_resolve_bowtie]


def run():
    return run_suite('geometry', TESTS)

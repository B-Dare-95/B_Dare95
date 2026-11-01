# -*- coding: utf-8 -*-
"""Measurement rules + randomized floor-plan property tests."""
from __future__ import division
import math
import random
from harness import check, close, run_suite
from dlc_roomarea import engine, geometry as g

ST = {'EXTERIOR_FUNCTIONS': engine.DEFAULT_EXTERIOR_FUNCTIONS,
      'BRIDGE_COLUMNS': True, 'DEDUCT_FREESTANDING_COLUMNS': False,
      'CURTAIN_WALL_DEPTH': 0.0}


# --------------------------------------------------------------------------
# classification table
# --------------------------------------------------------------------------
def test_classify_function_wins():
    c = engine.classify_wall('EXTERIOR', 0.8, False)
    check(c['exterior'] and c['d_gla'] == 0 and c['d_gfa'] == 0.8)
    check(c['flags'] == [])
    c = engine.classify_wall('INTERIOR', 0.4, True)
    check(not c['exterior'] and c['d_gla'] == 0.2 and c['d_gfa'] == 0.2)
    check(c['flags'] == [])


def test_classify_mismatch_flags():
    c = engine.classify_wall('EXTERIOR', 0.8, True)
    check(c['exterior'] and 'EXT_TYPE_ROOM_BEHIND' in c['flags'])
    c = engine.classify_wall('INTERIOR', 0.4, False)
    check(not c['exterior'] and 'INT_TYPE_NOTHING_BEHIND' in c['flags'])
    c = engine.classify_wall('CORESHAFT', 0.4, False)
    check(not c['exterior'] and 'INT_TYPE_NOTHING_BEHIND' in c['flags'])


def test_classify_foundation_retaining_exterior():
    for f in ('FOUNDATION', 'RETAINING'):
        check(engine.classify_wall(f, 1.0, None)['exterior'])
    check(not engine.classify_wall('SOFFIT', 1.0, None)['exterior'])


def test_classify_geometry_fallback():
    c = engine.classify_wall(None, 0.6, False)
    check(c['exterior'] and 'NO_FUNCTION_GEOMETRY' in c['flags'])
    c = engine.classify_wall(None, 0.6, True)
    check(not c['exterior'] and c['d_gla'] == 0.3)
    c = engine.classify_wall(None, 0.6, None)
    check(not c['exterior'] and 'UNRESOLVED' in c['flags'])


def test_classify_width_and_curtain():
    c = engine.classify_wall('EXTERIOR', None, False)
    check(c['d_gfa'] == 0 and 'NO_WIDTH' in c['flags'])
    c = engine.classify_wall('EXTERIOR', 0.0, False, True, 0.5)
    check(c['d_gfa'] == 0.5 and c['d_gla'] == 0 and 'CURTAIN_DEPTH' in c['flags'])
    c = engine.classify_wall('EXTERIOR', 0.0, False, True, 0.0)
    check(c['d_gfa'] == 0.0 and 'CURTAIN_DEPTH' not in c['flags'])


def test_custom_exterior_functions():
    c = engine.classify_wall('RETAINING', 1.0, None,
                             exterior_functions=('EXTERIOR',))
    check(not c['exterior'])


def test_resolve_leasable():
    check(engine.resolve_leasable(True) == (True, []))
    check(engine.resolve_leasable(False, True) == (False, []))
    check(engine.resolve_leasable(None) == (False, ['LEASABLE_BLANK']))
    check(engine.resolve_leasable(None, True) == (True, ['LEASABLE_BLANK']))


def test_orient_and_probe_side():
    # clockwise outer loop must be flipped; probe must land outside the room
    seg = lambda a, b: {'pts': [a, b], 'kind': g.KIND_WALL}
    cw = [seg((0, 0), (0, 3)), seg((0, 3), (4, 3)), seg((4, 3), (4, 0)),
          seg((4, 0), (0, 0))]
    loops = engine.orient_segment_loops([cw])
    pts = [s['pts'][0] for s in loops[0]]
    check(g.signed_area(pts) > 0, 'outer must be CCW')
    for s in loops[0]:
        p = engine.probe_point(s, 0.5)
        check(not (0 < p[0] < 4 and 0 < p[1] < 3), 'probe outside room')


def test_orient_puts_outer_first():
    seg = lambda a, b: {'pts': [a, b], 'kind': g.KIND_WALL}
    small = [seg((4, 4), (6, 4)), seg((6, 4), (6, 6)), seg((6, 6), (4, 6)),
             seg((4, 6), (4, 4))]
    big = [seg((0, 0), (10, 0)), seg((10, 0), (10, 10)),
           seg((10, 10), (0, 10)), seg((0, 10), (0, 0))]
    loops = engine.orient_segment_loops([small, big])
    check(abs(g.signed_area([s['pts'][0] for s in loops[0]])) == 100)
    check(g.signed_area([s['pts'][0] for s in loops[1]]) < 0, 'hole CW')
    # probe behind hole walls goes INTO the hole
    for s in loops[1]:
        p = engine.probe_point(s, 0.5)
        check(4 < p[0] < 6 and 4 < p[1] < 6, 'probe inside shaft')


# --------------------------------------------------------------------------
# hand-checked two-room plan
# --------------------------------------------------------------------------
def test_two_rooms_hand_checked():
    # centreline grid 0..5 and 5..9 (ft), height 4; exterior 1.0 thick
    # (grid at inner face), middle interior wall 0.5 thick on x = 5
    te, ti = 1.0, 0.5

    def wall(a, b, fn, w, behind):
        return {'pts': [a, b], 'kind': g.KIND_WALL, 'function': fn,
                'width': w, 'room_behind': behind, 'label': 'w'}
    left = [wall((0, 0), (5 - ti / 2, 0), 'EXTERIOR', te, False),
            wall((5 - ti / 2, 0), (5 - ti / 2, 4), 'INTERIOR', ti, True),
            wall((5 - ti / 2, 4), (0, 4), 'EXTERIOR', te, False),
            wall((0, 4), (0, 0), 'EXTERIOR', te, False)]
    res = engine.compute_room(engine.orient_segment_loops([left]), ST)
    close(res['base'], (5 - 0.25) * 4)
    close(res['gla'], 5 * 4)
    close(res['gfa'], (5 + 1) * (4 + 2))
    check(len(res['walls']) == 4 and res['flags'] == [])


def test_room_with_separation_line():
    segs = [{'pts': [(0, 0), (4, 0)], 'kind': g.KIND_SEPARATION},
            {'pts': [(4, 0), (4, 3)], 'kind': g.KIND_WALL,
             'function': 'INTERIOR', 'width': 0.4, 'room_behind': True},
            {'pts': [(4, 3), (0, 3)], 'kind': g.KIND_SEPARATION},
            {'pts': [(0, 3), (0, 0)], 'kind': g.KIND_SEPARATION}]
    res = engine.compute_room(engine.orient_segment_loops([segs]), ST)
    close(res['gla'], 4.2 * 3)
    close(res['gfa'], 4.2 * 3)


# --------------------------------------------------------------------------
# randomized floor plans  (property test)
# --------------------------------------------------------------------------
def _rot(p, ang, ox, oy):
    c, s = math.cos(ang), math.sin(ang)
    return (p[0] * c - p[1] * s + ox, p[0] * s + p[1] * c + oy)


def _cell_union_boundary(cells):
    """CCW rectilinear boundary (grid indices) of a union of unit cells."""
    edges = {}
    for (i, j) in cells:
        for a, b in (((i, j), (i + 1, j)), ((i + 1, j), (i + 1, j + 1)),
                     ((i + 1, j + 1), (i, j + 1)), ((i, j + 1), (i, j))):
            if (b, a) in edges:
                del edges[(b, a)]
            else:
                edges[(a, b)] = True
    nxt = dict(edges.keys())
    start = min(nxt)
    loop = [start]
    cur = nxt[start]
    while cur != start:
        loop.append(cur)
        cur = nxt[cur]
    # drop collinear grid vertices
    out = []
    n = len(loop)
    for k in range(n):
        a, b, c = loop[k - 1], loop[k], loop[(k + 1) % n]
        if (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]) != 0:
            out.append(b)
    return out


def make_plan(rng):
    nx, ny = rng.randint(1, 5), rng.randint(1, 4)
    xs = [0.0]
    for _ in range(nx):
        xs.append(xs[-1] + rng.uniform(6, 20))
    ys = [0.0]
    for _ in range(ny):
        ys.append(ys[-1] + rng.uniform(6, 20))
    te = {'L': rng.uniform(0.5, 1.6), 'R': rng.uniform(0.5, 1.6),
          'B': rng.uniform(0.5, 1.6), 'T': rng.uniform(0.5, 1.6)}
    tvx = [rng.uniform(0.3, 1.0) for _ in xs]       # interior x-lines
    tvy = [rng.uniform(0.3, 1.0) for _ in ys]
    # partition cells into rooms of 1, 2 (bar) or 3 (L) cells
    owner = {}
    rooms = []
    for j in range(ny):
        for i in range(nx):
            if (i, j) in owner:
                continue
            cells = [(i, j)]
            if rng.random() < 0.4 and i + 1 < nx and (i + 1, j) not in owner:
                cells.append((i + 1, j))
                if rng.random() < 0.5 and j + 1 < ny and (i, j + 1) not in owner:
                    cells.append((i, j + 1))
            elif rng.random() < 0.3 and j + 1 < ny and (i, j + 1) not in owner:
                cells.append((i, j + 1))
            for c in cells:
                owner[c] = len(rooms)
            rooms.append(cells)
    return xs, ys, te, tvx, tvy, rooms


def plan_room_segments(plan, cells, rng, ang, ox, oy, add_columns):
    xs, ys, te, tvx, tvy, _ = plan
    nx, ny = len(xs) - 1, len(ys) - 1
    poly = _cell_union_boundary(cells)        # CCW grid vertices
    n = len(poly)
    # each edge: grid line, inset, wall props
    info = []
    for k in range(n):
        a, b = poly[k], poly[(k + 1) % n]
        if a[1] == b[1]:                     # horizontal on y-line a[1]
            line = a[1]
            ext = line in (0, ny)
            w = (te['B'] if line == 0 else te['T']) if ext else tvy[line]
        else:
            line = a[0]
            ext = line in (0, nx)
            w = (te['L'] if line == 0 else te['R']) if ext else tvx[line]
        info.append((ext, w, 0.0 if ext else w / 2.0))
    # finish-face vertices: intersection of consecutive inset lines
    fin = []
    for k in range(n):
        a, b = poly[k], poly[(k + 1) % n]           # edge k
        pa = poly[k - 1]                            # edge k-1 from pa to a
        ins_prev, ins_cur = info[k - 1][2], info[k][2]
        # inward (left) normals for CCW
        def lnorm(p, q):
            dx, dy = q[0] - p[0], q[1] - p[1]
            L = abs(dx) + abs(dy)
            return (-dy / L, dx / L)
        np_ = lnorm(pa, a)
        nc = lnorm(a, b)
        X, Y = xs[a[0]], ys[a[1]]
        # one of the two edges is vertical, the other horizontal
        x = X + (np_[0] * ins_prev + nc[0] * ins_cur)
        y = Y + (np_[1] * ins_prev + nc[1] * ins_cur)
        fin.append((x, y))
    segs = []
    for k in range(n):
        p0, p1 = fin[k], fin[(k + 1) % n]
        ext, w, _ = info[k]
        props = {'kind': g.KIND_WALL, 'function': 'EXTERIOR' if ext else
                 rng.choice(['INTERIOR', 'INTERIOR', 'CORESHAFT', None]),
                 'width': w, 'room_behind': not ext, 'label': 'e%d' % k}
        # random splits (Revit splits faces at T-junctions)
        cuts = sorted(rng.uniform(0.15, 0.85) for _ in range(rng.randint(0, 2)))
        stations = [0.0] + cuts + [1.0]
        L = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        for s0, s1 in zip(stations[:-1], stations[1:]):
            q0 = (p0[0] + (p1[0] - p0[0]) * s0, p0[1] + (p1[1] - p0[1]) * s0)
            q1 = (p0[0] + (p1[0] - p0[0]) * s1, p0[1] + (p1[1] - p0[1]) * s1)
            if add_columns and rng.random() < 0.3 and L * (s1 - s0) > 3.0:
                # pilaster: 1.0 wide, protruding 0.4 into the room
                ux, uy = (q1[0] - q0[0]), (q1[1] - q0[1])
                ll = math.hypot(ux, uy)
                ux, uy = ux / ll, uy / ll
                nlx, nly = -uy, ux                   # into room (left)
                m = rng.uniform(1.0, ll - 2.0)
                c0 = (q0[0] + ux * m, q0[1] + uy * m)
                c1 = (c0[0] + nlx * 0.4, c0[1] + nly * 0.4)
                c2 = (c1[0] + ux * 1.0, c1[1] + uy * 1.0)
                c3 = (c0[0] + ux * 1.0, c0[1] + uy * 1.0)
                d = dict(props)
                d['pts'] = [q0, c0]
                segs.append(d)
                for a2, b2 in ((c0, c1), (c1, c2), (c2, c3)):
                    segs.append({'pts': [a2, b2], 'kind': g.KIND_COLUMN})
                d = dict(props)
                d['pts'] = [c3, q1]
                segs.append(d)
            else:
                d = dict(props)
                d['pts'] = [q0, q1]
                segs.append(d)
    # rigid transform + random start + random direction
    for s in segs:
        s['pts'] = [_rot(p, ang, ox, oy) for p in s['pts']]
    k = rng.randrange(len(segs))
    segs = segs[k:] + segs[:k]
    if rng.random() < 0.5:
        segs = [dict(s, pts=list(reversed(s['pts']))) for s in reversed(segs)]
    grid_area = sum((xs[i + 1] - xs[i]) * (ys[j + 1] - ys[j])
                    for (i, j) in cells)
    return segs, grid_area, abs(g.signed_area(fin))


def _plan_property(seed, add_columns):
    rng = random.Random(seed)
    plan = make_plan(rng)
    xs, ys, te, _, _, rooms = plan
    ang = rng.uniform(0, 2 * math.pi)
    ox, oy = rng.uniform(-1e4, 1e4), rng.uniform(-1e4, 1e4)
    tot_gla = tot_gfa = 0.0
    for cells in rooms:
        segs, grid_area, fin_area = plan_room_segments(
            plan, cells, rng, ang, ox, oy, add_columns)
        res = engine.compute_room(engine.orient_segment_loops([segs]), ST)
        close(res['gla'], grid_area, 1e-7, 'seed %d GLA' % seed)
        if not add_columns:
            close(res['base'], fin_area, 1e-7, 'seed %d base' % seed)
        else:
            check(res['base'] <= fin_area + 1e-6, 'pilasters reduce base')
        tot_gla += res['gla']
        tot_gfa += res['gfa']
    W, H = xs[-1], ys[-1]
    close(tot_gla, W * H, 1e-7, 'seed %d sum GLA' % seed)
    close(tot_gfa, (W + te['L'] + te['R']) * (H + te['B'] + te['T']), 1e-7,
          'seed %d sum GFA = external footprint' % seed)


def test_random_plans_tile_exactly():
    for seed in range(300):
        _plan_property(seed, False)


def test_random_plans_with_pilasters_bridged():
    for seed in range(1000, 1300):
        _plan_property(seed, True)


TESTS = [test_classify_function_wins, test_classify_mismatch_flags,
         test_classify_foundation_retaining_exterior,
         test_classify_geometry_fallback, test_classify_width_and_curtain,
         test_custom_exterior_functions, test_resolve_leasable,
         test_orient_and_probe_side, test_orient_puts_outer_first,
         test_two_rooms_hand_checked, test_room_with_separation_line,
         test_random_plans_tile_exactly,
         test_random_plans_with_pilasters_bridged]


def run():
    return run_suite('engine', TESTS)

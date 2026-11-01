# -*- coding: utf-8 -*-
"""DLC Room Areas - measurement rules (pure Python, no Revit imports).

Rules (agreed with the BIM lead):
  GLA  interior walls -> wall centreline      (offset = width / 2)
       exterior walls -> inner finish face    (offset = 0)
  GFA  interior walls -> wall centreline      (offset = width / 2)
       exterior walls -> outer face           (offset = width)
  Room separation lines and other bounding elements -> offset 0.
  Columns are bridged (no deduction); free-standing columns are not deducted.
  Exterior detection: wall type Function first; when the Function cannot be
  read, geometry decides (no room found behind the wall = exterior).
  GLA is reported only for rooms with DLC_Is_Leasable = Yes.
"""
from __future__ import division

from . import geometry as g

FUNCTION_NAMES = {0: 'INTERIOR', 1: 'EXTERIOR', 2: 'FOUNDATION',
                  3: 'RETAINING', 4: 'SOFFIT', 5: 'CORESHAFT'}
DEFAULT_EXTERIOR_FUNCTIONS = ('EXTERIOR', 'FOUNDATION', 'RETAINING')

# QA flag codes -> plain-language explanation for the report
FLAG_TEXT = {
    'EXT_TYPE_ROOM_BEHIND': 'Wall type Function is Exterior but a room was '
                            'found behind it. Measured as EXTERIOR - check '
                            'the wall type is correct.',
    'INT_TYPE_NOTHING_BEHIND': 'Wall type Function is Interior but no room '
                               'was found behind it (shaft, void or outside). '
                               'Measured to CENTRELINE - if this is a facade '
                               'wall, set its type Function to Exterior.',
    'NO_FUNCTION_GEOMETRY': 'Wall Function could not be read - decided by '
                            'geometry (room behind = interior).',
    'UNRESOLVED': 'Wall Function unreadable and the probe failed - measured '
                  'as interior (centreline).',
    'NO_WIDTH': 'Wall thickness could not be read - offset taken as 0.',
    'CURTAIN_DEPTH': 'Curtain wall - GFA uses CURTAIN_WALL_DEPTH_MM from '
                     'SETTINGS as its thickness.',
    'STACKED_WALL': 'Stacked wall - thickness taken from its first member.',
    'LINKED_WALL': 'Bounding wall is in a linked model.',
    'OFFSET_CLEANUP': 'Offset outline overlapped itself (narrow recess or '
                      'pilaster closed up) - overlap removed automatically.',
    'COLUMN_BRIDGE_SKIPPED': 'Room bounded mostly by columns - columns '
                             'measured at their face instead of bridged.',
    'LEASABLE_BLANK': 'DLC_Is_Leasable has no value.',
    'NO_BOUNDARY': 'Room has no usable boundary (not enclosed or redundant).',
}


def classify_wall(function, width, room_behind, is_curtain=False,
                  curtain_depth=0.0,
                  exterior_functions=DEFAULT_EXTERIOR_FUNCTIONS):
    """Decide interior/exterior and the GLA/GFA offsets for one wall face.

    function    : 'EXTERIOR', 'INTERIOR', ... or None if unreadable
    width       : total wall thickness (None if unreadable)
    room_behind : True / False / None (probe failed or not run)
    Returns dict(exterior, d_gla, d_gfa, flags).
    """
    flags = []
    w = width
    if w is None or w < 0:
        flags.append('NO_WIDTH')
        w = 0.0
    if is_curtain and curtain_depth > w:
        w = curtain_depth
        flags.append('CURTAIN_DEPTH')

    if function is not None:
        exterior = function in exterior_functions
        if exterior and room_behind is True:
            flags.append('EXT_TYPE_ROOM_BEHIND')
        if not exterior and room_behind is False:
            flags.append('INT_TYPE_NOTHING_BEHIND')
    else:
        if room_behind is None:
            exterior = False
            flags.append('UNRESOLVED')
        else:
            exterior = not room_behind
            flags.append('NO_FUNCTION_GEOMETRY')

    if exterior:
        return {'exterior': True, 'd_gla': 0.0, 'd_gfa': w, 'flags': flags}
    return {'exterior': False, 'd_gla': w / 2.0, 'd_gfa': w / 2.0,
            'flags': flags}


def resolve_leasable(value, blank_as_leasable=False):
    """value: True / False / None (blank). Returns (is_leasable, flags)."""
    if value is None:
        return bool(blank_as_leasable), ['LEASABLE_BLANK']
    return bool(value), []


# --------------------------------------------------------------------------
# segment loops  (what the Revit adapter produces)
# --------------------------------------------------------------------------
# A segment is a dict:
#   pts        : [(x, y), ...]  2+ points along the boundary curve
#   kind       : geometry.KIND_*
#   width      : wall thickness or None
#   function   : 'EXTERIOR' / 'INTERIOR' / ... / None
#   is_curtain : bool
#   room_behind: True / False / None  (filled after orientation)
#   label      : text for the QA report
#   extra_flags: list of flag codes from the adapter (linked, stacked ...)

def _seg_loop_points(loop):
    pts = []
    for s in loop:
        pts.extend(s['pts'][:-1])
    return pts


def _reverse_seg(s):
    r = dict(s)
    r['pts'] = list(reversed(s['pts']))
    return r


def orient_segment_loops(loops):
    """Outer loop CCW, holes CW (room on the left of travel).

    After this, the right-hand normal of every segment points AWAY from the
    room - i.e. towards whatever is behind the wall.
    """
    loops = [l for l in loops if l]
    if not loops:
        return []
    areas = [g.signed_area(_seg_loop_points(l)) for l in loops]
    outer = max(range(len(loops)), key=lambda i: abs(areas[i]))
    out = []
    for i, l in enumerate(loops):
        want_positive = (i == outer)
        if (areas[i] > 0) != want_positive:
            l = [_reverse_seg(s) for s in reversed(l)]
        if i == outer:
            out.insert(0, l)
        else:
            out.append(l)
    return out


def probe_point(seg, distance):
    """Point `distance` behind the middle of a segment (away from room)."""
    pts = seg['pts']
    k = (len(pts) - 1) // 2
    a, b = pts[k], pts[k + 1]
    L = ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
    if L <= 0:
        return None
    ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
    mx, my = (a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0
    return (mx + uy * distance, my - ux * distance)


def compute_room(loops, settings):
    """Measure one room.

    loops    : oriented segment loops (see orient_segment_loops)
    settings : dict with CURTAIN_WALL_DEPTH, EXTERIOR_FUNCTIONS,
               BRIDGE_COLUMNS, DEDUCT_FREESTANDING_COLUMNS
    Returns dict(base, gla, gfa, flags, walls) - areas in input units^2;
    gla here is the measured value before the leasable switch is applied.
    """
    curtain_depth = settings.get('CURTAIN_WALL_DEPTH', 0.0)
    ext_funcs = settings.get('EXTERIOR_FUNCTIONS', DEFAULT_EXTERIOR_FUNCTIONS)
    edge_loops = []
    walls = []
    room_flags = []
    for loop in loops:
        edges = []
        for s in loop:
            kind = s.get('kind', g.KIND_OTHER)
            off = {'BASE': 0.0, 'GLA': 0.0, 'GFA': 0.0}
            if kind == g.KIND_WALL:
                c = classify_wall(s.get('function'), s.get('width'),
                                  s.get('room_behind'),
                                  s.get('is_curtain', False),
                                  curtain_depth, ext_funcs)
                off['GLA'] = c['d_gla']
                off['GFA'] = c['d_gfa']
                flags = list(s.get('extra_flags', [])) + c['flags']
                walls.append({'label': s.get('label', ''),
                              'function': s.get('function'),
                              'width': s.get('width'),
                              'room_behind': s.get('room_behind'),
                              'exterior': c['exterior'],
                              'flags': flags})
            pts = s['pts']
            for i in range(len(pts) - 1):
                edges.append(g.Edge(pts[i], pts[i + 1], kind, off,
                                    s.get('label')))
        edge_loops.append(edges)

    res = {'walls': walls}
    bridge = settings.get('BRIDGE_COLUMNS', True)
    deduct = settings.get('DEDUCT_FREESTANDING_COLUMNS', False)
    for mode in ('BASE', 'GLA', 'GFA'):
        if mode == 'BASE':
            # raw finish-face area, columns as Revit sees them - this is the
            # number that must match Revit's own Area (finish-face setting)
            area, warns = g.compute_area(edge_loops, mode, False, True)
        else:
            area, warns = g.compute_area(edge_loops, mode, bridge, deduct)
        res[mode.lower()] = area
        for w in warns:
            code = 'OFFSET_CLEANUP' if w == 'SELF_OVERLAP' else w
            if code not in room_flags:
                room_flags.append(code)
    res['flags'] = room_flags
    return res

# -*- coding: utf-8 -*-
"""
DLC Restore Rooms - pure logic (no Revit API). IronPython 2.7 / CPython 3.
"""
TOOL_NAME = "DLC Restore Rooms"
TOOL_VERSION = "1.2.2"

NOT_PLACED = "Not Placed"
NOT_ENCLOSED = "Not Enclosed / Redundant"
PLACED = "Placed"

try:
    text_type = unicode  # noqa: F821
except NameError:
    text_type = str


def to_text(v):
    if v is None:
        return u""
    if isinstance(v, text_type):
        return v
    try:
        return text_type(v)
    except Exception:
        return u"?"


def classify(has_location, area):
    """Revit's own schedule states."""
    if not has_location:
        return NOT_PLACED
    if area is None or area <= 1e-6:
        return NOT_ENCLOSED
    return PLACED


def norm_number(n):
    return to_text(n).strip().upper()


# ------------------------------------------------------------------ geometry
def point_in_loops(pt, loops):
    """Even-odd rule over ALL loops -> holes (courtyards, shafts) handled."""
    x, y = pt
    inside = False
    for loop in loops:
        n = len(loop)
        if n < 3:
            continue
        j = n - 1
        for i in range(n):
            xi, yi = loop[i]
            xj, yj = loop[j]
            if (yi > y) != (yj > y):
                xc = (xj - xi) * (y - yi) / float(yj - yi) + xi
                if x < xc:
                    inside = not inside
            j = i
    return inside


def loops_area(loops):
    """Signed-area sum with holes subtracted (outer assumed largest)."""
    areas = []
    for loop in loops:
        a = 0.0
        n = len(loop)
        for i in range(n):
            x1, y1 = loop[i]
            x2, y2 = loop[(i + 1) % n]
            a += x1 * y2 - x2 * y1
        areas.append(abs(a) / 2.0)
    if not areas:
        return 0.0
    big = max(areas)
    return big - (sum(areas) - big)


def region_at(pt, regions, exclude=()):
    """Id of the empty region containing pt (smallest if nested), else None."""
    hits = [(loops_area(r["loops"]), rid) for rid, r in regions.items()
            if rid not in exclude and point_in_loops(pt, r["loops"])]
    if not hits:
        return None
    hits.sort()
    return hits[0][1]

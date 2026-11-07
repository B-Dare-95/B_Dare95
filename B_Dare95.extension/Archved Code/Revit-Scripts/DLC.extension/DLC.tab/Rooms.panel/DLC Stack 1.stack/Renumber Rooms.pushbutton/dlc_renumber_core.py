# -*- coding: utf-8 -*-
"""
DLC_RenumberRooms - dlc_renumber_core.py  (v1.1.0)

Pure logic for clockwise room renumbering. Deliberately has ZERO Revit API
imports so it can be unit-tested with plain CPython. Written to IronPython
2.7 rules (no f-strings, no walrus, stdlib only) because bd_family_cleaner.py imports
it at runtime inside Revit.

Room record shape used throughout:
    {"id": <hashable>, "x": float|None, "y": float|None, "z": float|None,
     "area": float, "number": str, "name": str}
"""

import re
import math

TWO_PI = 2.0 * math.pi

# Lazy prefix + digit run + non-digit suffix, anchored. Backtracking forces
# the prefix to swallow everything up to the LAST contiguous digit run, so
# "L1-05" -> prefix "L1-", digits "05" (the level digit is not the counter).
_NUMBER_PATTERN_RE = re.compile(r'^(.*?)(\d+)([^\d]*)$')


# ---------------------------------------------------------------------------
# Number pattern parsing / generation
# ---------------------------------------------------------------------------

def parse_number_pattern(first_number_text):
    """Parse the user-typed first room number into prefix/start/width/suffix."""
    if first_number_text is None:
        raise ValueError("Enter a first room number before previewing.")
    text = first_number_text.strip()
    if text == "":
        raise ValueError("Enter a first room number before previewing.")

    match = _NUMBER_PATTERN_RE.match(text)
    if not match:
        raise ValueError(
            "There is no number in '%s' to count up from. Include at least one "
            "digit, for example 101 or G-001." % text
        )

    prefix, digits, suffix = match.group(1), match.group(2), match.group(3)
    return {
        "prefix": prefix,
        "start": int(digits),
        "width": len(digits),
        "suffix": suffix,
        "source_text": text,
    }


def format_number(pattern, offset):
    """Format the number at 0-based position `offset` in the sequence."""
    value = pattern["start"] + offset
    digits = str(value)
    if len(digits) < pattern["width"]:
        digits = digits.zfill(pattern["width"])
    return "%s%s%s" % (pattern["prefix"], digits, pattern["suffix"])


def build_new_numbers(ordered_room_ids, pattern):
    """Returns {room_id: new_number_string} following the given order."""
    result = {}
    for index, room_id in enumerate(ordered_room_ids):
        result[room_id] = format_number(pattern, index)
    return result


# ---------------------------------------------------------------------------
# Room filtering / geometry
# ---------------------------------------------------------------------------

def filter_placed_rooms(rooms):
    """
    Split into (placed, skipped_ids). Placed == positive area AND a resolvable
    location point. Unplaced / redundant rooms are reported, never numbered.
    """
    placed = []
    skipped_ids = []
    for room in rooms:
        area = room.get("area", 0.0)
        has_point = room.get("x") is not None and room.get("y") is not None
        if area and area > 0.0 and has_point:
            placed.append(room)
        else:
            skipped_ids.append(room["id"])
    return placed, skipped_ids


def compute_centroid(rooms):
    """Average (x, y) of the given room records."""
    if not rooms:
        raise ValueError("There are no placed rooms to measure a centre point from.")
    sum_x = sum(r["x"] for r in rooms)
    sum_y = sum(r["y"] for r in rooms)
    n = float(len(rooms))
    return (sum_x / n, sum_y / n)


# ---------------------------------------------------------------------------
# Ordering A: clockwise polar sweep from a chosen start room
# ---------------------------------------------------------------------------

def polar_clockwise_order(rooms, center, start_room_id):
    """
    Clockwise order by bearing around `center`, starting at `start_room_id`.
    Revit's +Y is north / +X is east, so clockwise travel is decreasing
    atan2 angle; we measure (theta_start - theta) wrapped into [0, 2pi).
    Same-bearing ties break by distance from centre, nearest first.
    """
    cx, cy = center

    start_room = None
    others = []
    for room in rooms:
        if room["id"] == start_room_id:
            start_room = room
        else:
            others.append(room)

    if start_room is None:
        raise ValueError(
            "The room you picked as the start is not inside the scope you chose. "
            "Pick a room on the selected level / in the selected set."
        )

    theta0 = math.atan2(start_room["y"] - cy, start_room["x"] - cx)

    def _delta(room):
        theta = math.atan2(room["y"] - cy, room["x"] - cx)
        return (theta0 - theta) % TWO_PI

    def _dist(room):
        return math.hypot(room["x"] - cx, room["y"] - cy)

    decorated = [(_delta(r), _dist(r), r["id"]) for r in others]
    decorated.sort(key=lambda t: (t[0], t[1]))

    return [start_room_id] + [d[2] for d in decorated]


# ---------------------------------------------------------------------------
# Ordering B: path order along a picked reference curve
# ---------------------------------------------------------------------------

def order_by_parameter(id_parameter_pairs):
    """Sort (room_id, parameter) pairs ascending by parameter."""
    decorated = sorted(id_parameter_pairs, key=lambda t: t[1])
    return [t[0] for t in decorated]


# ---------------------------------------------------------------------------
# Two-pass rename planning (collision-safe)
# ---------------------------------------------------------------------------

def build_rename_plan(ordered_room_ids, new_numbers_by_id, temp_prefix="~DLCTMP~"):
    """
    Returns (temp_pass, final_pass) as lists of (room_id, number) tuples.

    Revit rejects a room number colliding with another room's CURRENT number,
    so a direct swap (A:101<->B:102) fails mid-batch. Writing every room to a
    temp number that embeds its own element id - guaranteed unique - and only
    then writing finals makes swaps and cycles safe.
    """
    temp_pass = []
    final_pass = []
    for room_id in ordered_room_ids:
        temp_pass.append((room_id, "%s%s" % (temp_prefix, str(room_id))))
        final_pass.append((room_id, new_numbers_by_id[room_id]))
    return temp_pass, final_pass


def find_internal_duplicates(new_numbers_by_id):
    """
    Safety net: any target number assigned to more than one room. Should never
    happen with sequential generation, but a corrupted pattern or a future
    caller could produce it, and silently creating duplicate room numbers is
    far worse than refusing to run.
    """
    seen = {}
    dupes = {}
    for room_id, number in new_numbers_by_id.items():
        if number in seen:
            dupes.setdefault(number, [seen[number]]).append(room_id)
        else:
            seen[number] = room_id
    return dupes


# ---------------------------------------------------------------------------
# High-level pipelines
# ---------------------------------------------------------------------------

def _finish_plan(order, first_number_text, placed, skipped_ids, extra=None):
    pattern = parse_number_pattern(first_number_text)
    new_numbers = build_new_numbers(order, pattern)

    dupes = find_internal_duplicates(new_numbers)
    if dupes:
        raise ValueError(
            "Internal error: the generated numbering contains duplicates (%s). "
            "Nothing was changed." % ", ".join(sorted(dupes.keys()))
        )

    temp_pass, final_pass = build_rename_plan(order, new_numbers)

    plan = {
        "placed": placed,
        "skipped_ids": skipped_ids,
        "order": order,
        "new_numbers": new_numbers,
        "temp_pass": temp_pass,
        "final_pass": final_pass,
        "unordered_ids": [],
    }
    if extra:
        plan.update(extra)
    return plan


def plan_polar_renumber(rooms, start_room_id, first_number_text):
    """Full pipeline for 'pick a starting room' mode."""
    placed, skipped_ids = filter_placed_rooms(rooms)
    if not placed:
        raise ValueError("No placed rooms were found in the scope you chose.")

    center = compute_centroid(placed)
    order = polar_clockwise_order(placed, center, start_room_id)
    return _finish_plan(order, first_number_text, placed, skipped_ids,
                        extra={"center": center})


def plan_path_renumber(rooms, id_parameter_pairs, first_number_text):
    """
    Full pipeline for 'pick a reference line' mode.

    Any placed room with no usable projection onto the curve is reported in
    plan["unordered_ids"] rather than being silently dropped from the
    sequence - a missing room here would otherwise keep its old number with
    no indication anything went wrong.
    """
    placed, skipped_ids = filter_placed_rooms(rooms)
    if not placed:
        raise ValueError("No placed rooms were found in the scope you chose.")

    placed_ids = set(r["id"] for r in placed)
    param_by_id = {}
    for room_id, param in id_parameter_pairs:
        if room_id in placed_ids:
            param_by_id[room_id] = param

    unordered_ids = sorted(
        [rid for rid in placed_ids if rid not in param_by_id],
        key=lambda v: str(v),
    )

    order = order_by_parameter(list(param_by_id.items()))
    if not order:
        raise ValueError(
            "None of the rooms in this scope could be measured against the line "
            "you picked. Try a line that runs through the rooms."
        )

    ordered_placed = [r for r in placed if r["id"] in param_by_id]
    return _finish_plan(order, first_number_text, ordered_placed, skipped_ids,
                        extra={"unordered_ids": unordered_ids})

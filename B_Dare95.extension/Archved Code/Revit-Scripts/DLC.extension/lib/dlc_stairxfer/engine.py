# -*- coding: utf-8 -*-
"""
DLC Stair Transfer - pure-Python planning engine.

No Revit imports. Everything here works on plain numbers so it can be
unit-tested outside Revit. All lengths are Revit internal units (feet)
unless a name ends in _mm.

The problem it solves
---------------------
Architecture levels sit at finished floor level (FFL). Structure levels sit
at structural slab level (SSL), which is lower by the finish build-up, and
that build-up differs floor by floor. A stair copied as-is would be hosted on
the wrong levels and start on top of the finishes.

For every flight we:
  1. take the arch level each end references (base / top),
  2. find the structural level directly below it (within MAX_FINISH),
  3. drop that end by the finish thickness found (slab-to-slab), keeping any
     intentional offset the architect set,
  4. host the flight on the structural levels with recalculated offsets.
"""

MM_TO_FT = 1.0 / 304.8

MODE_SLAB_TO_SLAB = "SLAB_TO_SLAB"   # each end drops by its own finish
MODE_SHIFT_BY_BASE = "SHIFT_BY_BASE"  # whole flight drops by the base finish


class MappingError(Exception):
    """A flight end could not be matched to a structural level."""
    pass


class LevelRec(object):
    """A level reduced to what the engine needs. elev is in the host frame."""

    def __init__(self, key, name, elev):
        self.key = key
        self.name = name
        self.elev = float(elev)

    def __repr__(self):
        return "LevelRec(%r, %r, %.4f)" % (self.key, self.name, self.elev)


class FlightSource(object):
    """One flight to create, as read from the architecture model.

    base_elev / top_elev are the arch level elevations the flight references
    BEFORE any multistorey placement shift. top_elev is None when the stair has
    no top level (height driven) - then top_offset holds the full height above
    the base level.
    """

    def __init__(self, key, label, base_elev, base_offset, top_elev, top_offset,
                 risers, max_riser=None, dz=0.0):
        self.key = key
        self.label = label
        self.base_elev = float(base_elev)
        self.base_offset = float(base_offset)
        self.top_elev = None if top_elev is None else float(top_elev)
        self.top_offset = float(top_offset)
        self.risers = int(risers)
        self.max_riser = None if max_riser is None else float(max_riser)
        self.dz = float(dz)


class FlightPlan(object):
    def __init__(self):
        self.source = None
        self.ok = False
        self.error = None
        self.warnings = []
        self.arch_base_name = ""
        self.arch_top_name = ""
        self.base_level = None
        self.top_level = None
        self.base_offset = 0.0
        self.top_offset = 0.0
        self.finish_base = 0.0
        self.finish_top = 0.0
        self.arch_height = 0.0
        self.str_height = 0.0
        self.riser_height = 0.0
        self.z_bottom = 0.0
        self.z_top = 0.0


def default_settings():
    return {
        "GEOMETRY_MODE": MODE_SLAB_TO_SLAB,
        "MAX_FINISH_MM": 600.0,      # largest finish build-up we will accept
        "MATCH_TOL_MM": 5.0,         # STR level may sit this much ABOVE FFL
        "LEVEL_NAME_MAP": {},        # {"ARCH level name": "STR level name"}
        "HEIGHT_CHANGE_WARN_MM": 50.0,
    }


def mm(v):
    return float(v) * MM_TO_FT


def to_mm(ft):
    return float(ft) * 304.8


def find_level_by_elev(levels, elev, tol):
    """Closest level within tol of elev, else None."""
    best = None
    best_d = None
    for lv in levels:
        d = abs(lv.elev - elev)
        if d <= tol and (best_d is None or d < best_d):
            best, best_d = lv, d
    return best


def find_level_by_name(levels, name):
    if not name:
        return None
    want = name.strip().lower()
    for lv in levels:
        if (lv.name or "").strip().lower() == want:
            return lv
    return None


def map_end(ref_elev, arch_name, str_levels, settings):
    """Return (str_level, finish_thickness, how) for one flight end.

    ref_elev is the architectural level elevation (FFL) in the host frame.
    """
    name_map = settings.get("LEVEL_NAME_MAP") or {}
    if arch_name:
        for k in name_map:
            if k.strip().lower() == arch_name.strip().lower():
                target = find_level_by_name(str_levels, name_map[k])
                if target is None:
                    raise MappingError(
                        "LEVEL_NAME_MAP sends '%s' to '%s', but no structural "
                        "level has that name. Fix the name in SETTINGS."
                        % (arch_name, name_map[k]))
                return target, ref_elev - target.elev, "name map"

    tol = mm(settings.get("MATCH_TOL_MM", 5.0))
    max_finish = mm(settings.get("MAX_FINISH_MM", 600.0))
    best = None
    for lv in str_levels:
        finish = ref_elev - lv.elev
        if -tol <= finish <= max_finish:
            if best is None or lv.elev > best.elev:
                best = lv
    if best is None:
        raise MappingError(
            "No structural level found between 0 and %d mm below arch level "
            "'%s' (elev %.0f mm). Either the structural level is missing, or "
            "the finish is thicker than MAX_FINISH_MM - add it to "
            "LEVEL_NAME_MAP or raise MAX_FINISH_MM."
            % (settings.get("MAX_FINISH_MM", 600.0), arch_name or "?",
               to_mm(ref_elev)))
    return best, ref_elev - best.elev, "nearest below"


def map_end_chosen(ref_elev, arch_rec, str_levels, settings, level_map):
    """Like map_end, but an explicit user choice wins.

    level_map: {arch_level_key: str LevelRec or None}. A key present with
    None means the user left that level unmapped - that is an error, never a
    silent guess. Ends that do not sit on an arch level (height-driven tops)
    fall back to automatic matching.
    """
    if level_map is not None and arch_rec is not None and \
            arch_rec.key in level_map:
        target = level_map[arch_rec.key]
        if target is None:
            raise MappingError("No structural level chosen for arch level "
                               "'%s'." % arch_rec.name)
        return target, ref_elev - target.elev, "chosen"
    return map_end(ref_elev, arch_rec.name if arch_rec else None,
                   str_levels, settings)


def plan_flight(src, arch_levels, str_levels, settings=None, level_map=None):
    """Compute where one flight goes in the structural model."""
    s = default_settings()
    if settings:
        s.update(settings)
    p = FlightPlan()
    p.source = src
    try:
        if src.risers < 1:
            raise MappingError("Stair has no risers - nothing to copy.")
        tol = mm(s.get("MATCH_TOL_MM", 5.0))

        base_ref = src.base_elev + src.dz
        z_bot = base_ref + src.base_offset
        if src.top_elev is None:
            # height-driven stair: map the top by its absolute height
            top_ref = base_ref + src.top_offset
            z_top = top_ref
        else:
            top_ref = src.top_elev + src.dz
            z_top = top_ref + src.top_offset

        a_base = find_level_by_elev(arch_levels, base_ref, tol)
        a_top = find_level_by_elev(arch_levels, top_ref, tol)
        p.arch_base_name = a_base.name if a_base else "(%.0f)" % to_mm(base_ref)
        p.arch_top_name = a_top.name if a_top else "(%.0f)" % to_mm(top_ref)

        sb, fb, _ = map_end_chosen(base_ref, a_base, str_levels, s, level_map)
        st, ft, _ = map_end_chosen(top_ref, a_top, str_levels, s, level_map)
        p.finish_base, p.finish_top = fb, ft

        mode = s.get("GEOMETRY_MODE", MODE_SLAB_TO_SLAB)
        if mode == MODE_SHIFT_BY_BASE:
            nz_bot = z_bot - fb
            nz_top = z_top - fb
        elif mode == MODE_SLAB_TO_SLAB:
            nz_bot = z_bot - fb
            nz_top = z_top - ft
        else:
            raise MappingError("Unknown GEOMETRY_MODE '%s'." % mode)

        p.arch_height = z_top - z_bot
        p.str_height = nz_top - nz_bot
        if p.str_height <= mm(1.0):
            raise MappingError(
                "Structural stair height would be %.0f mm - check the level "
                "mapping for %s -> %s." % (to_mm(p.str_height),
                                           p.arch_base_name, p.arch_top_name))

        if st.key == sb.key and src.top_elev is not None:
            p.warnings.append(
                "Base and top map to the same structural level '%s'; the top "
                "will be hosted on it with an offset." % sb.name)

        p.base_level, p.top_level = sb, st
        p.base_offset = nz_bot - sb.elev
        p.top_offset = nz_top - st.elev
        p.z_bottom, p.z_top = nz_bot, nz_top
        p.riser_height = p.str_height / float(src.risers)

        if src.max_riser and p.riser_height > src.max_riser + 1e-9:
            p.warnings.append(
                "Riser becomes %.1f mm, above the type maximum of %.1f mm. "
                "Revit will warn; use a structural stair type with a higher "
                "max riser or accept the warning."
                % (to_mm(p.riser_height), to_mm(src.max_riser)))
        if abs(p.str_height - p.arch_height) > mm(s.get("HEIGHT_CHANGE_WARN_MM",
                                                        50.0)):
            p.warnings.append(
                "Flight height changes by %.0f mm (finish differs top vs "
                "bottom) - riser height adjusted, tread count kept."
                % to_mm(p.str_height - p.arch_height))
        p.ok = True
    except MappingError as ex:
        p.ok = False
        p.error = str(ex)
    return p


# ---------------------------------------------------------------- rebuild
# Geometry read from the arch stair, already in the host frame, XY only.
# Points are (x, y) tuples in feet.

class RunGeom(object):
    def __init__(self, style, path_pts, footprint_pts, width, base_raw,
                 risers):
        self.style = str(style)
        self.path_pts = list(path_pts)        # ordered along the walk path
        self.footprint_pts = list(footprint_pts)
        self.width = float(width)
        self.base_raw = float(base_raw)       # run.BaseElevation as read
        self.risers = int(risers)


class LandingGeom(object):
    def __init__(self, curves, base_raw):
        # curves: [("L", [p0, p1]) | ("A", [p0, p1, p_mid])], closed loop
        self.curves = list(curves)
        self.base_raw = float(base_raw)


class StairGeom(object):
    def __init__(self, runs, landings, riser_h, base_abs):
        self.runs = list(runs)
        self.landings = list(landings)
        self.riser_h = float(riser_h)     # arch actual riser height
        self.base_abs = float(base_abs)   # arch stair bottom, arch internal z


class RunSpec(object):
    def __init__(self, p0, p1, width, rel, risers):
        self.p0, self.p1 = p0, p1         # centre line, first->last riser
        self.width = width
        self.rel = rel                    # base elevation above stair base
        self.risers = risers


class LandingSpec(object):
    def __init__(self, curves, rel):
        self.curves = curves
        self.rel = rel


class BuildSpec(object):
    def __init__(self, runs, landings):
        self.runs = runs
        self.landings = landings


class RebuildNotPossible(Exception):
    """The flight can't be rebuilt from geometry; fall back to copying."""
    pass


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def _unit(v):
    ln = (v[0] ** 2 + v[1] ** 2) ** 0.5
    if ln < 1e-9:
        raise RebuildNotPossible("A run has a zero-length path.")
    return (v[0] / ln, v[1] / ln)


def _rel_mode(geom):
    """Are BaseElevation values relative to the stair base (documented) or
    absolute? Decide from the lowest run, which starts at the stair base."""
    low = min(r.base_raw for r in geom.runs)
    if abs(low) <= mm(1.0):
        return 0.0
    if abs(low - geom.base_abs) <= mm(1.0):
        return geom.base_abs
    return 0.0


def build_spec(geom, new_riser):
    """Turn arch stair geometry into what the STR stair is built from.

    Run positions are recomputed as the centre line of each run's footprint
    (so the result does not depend on the arch run's justification). Base
    elevations are kept as a number of risers and re-multiplied by the new
    riser height, so runs and landings stay on whole risers.
    """
    if not geom.runs:
        raise RebuildNotPossible("The stair has no runs.")
    if geom.riser_h <= 1e-9 or new_riser <= 1e-9:
        raise RebuildNotPossible("Riser height is zero.")
    for i, r in enumerate(geom.runs):
        if r.style.lower() != "straight" or len(r.path_pts) != 2:
            raise RebuildNotPossible(
                "Run %d is a '%s' run; only straight runs are rebuilt."
                % (i + 1, r.style))
    base0 = _rel_mode(geom)
    runs = []
    for r in geom.runs:
        p0, p1 = r.path_pts
        d = _unit(_sub(p1, p0))
        n = (-d[1], d[0])
        if r.footprint_pts:
            offs = [_dot(_sub(v, p0), n) for v in r.footprint_pts]
            mid = (min(offs) + max(offs)) / 2.0
        else:
            mid = 0.0
        c0 = (p0[0] + n[0] * mid, p0[1] + n[1] * mid)
        c1 = (p1[0] + n[0] * mid, p1[1] + n[1] * mid)
        k = int(round((r.base_raw - base0) / geom.riser_h))
        runs.append(RunSpec(c0, c1, r.width, k * new_riser, r.risers))
    landings = []
    for i, l in enumerate(geom.landings):
        k = int(round((l.base_raw - base0) / geom.riser_h))
        rel = k * new_riser
        if rel < new_riser / 2.0:
            raise RebuildNotPossible(
                "Landing %d sits at the stair base; Revit needs landings at "
                "least half a riser up." % (i + 1))
        landings.append(LandingSpec(l.curves, rel))
    runs.sort(key=lambda s: s.rel)
    return BuildSpec(runs, landings)


class LevelRow(object):
    """One row of the level-mapping dialog."""

    def __init__(self, arch):
        self.arch = arch
        self.is_base = False      # some flight starts here -> can be ticked
        self.n_flights = 0        # flights starting here
        self.candidates = []      # STR LevelRecs on the same floor, top first
        self.suggested = None     # default choice (LevelRec or None)


def flight_ends(src, arch_levels, settings=None):
    """(arch base LevelRec, arch top LevelRec or None) a flight touches."""
    s = default_settings()
    if settings:
        s.update(settings)
    tol = mm(s.get("MATCH_TOL_MM", 5.0))
    base_ref = src.base_elev + src.dz
    if src.top_elev is None:
        top_ref = base_ref + src.top_offset
    else:
        top_ref = src.top_elev + src.dz
    return (find_level_by_elev(arch_levels, base_ref, tol),
            find_level_by_elev(arch_levels, top_ref, tol))


def floor_candidates(arch, touched, str_levels, settings=None):
    """STR levels that belong to the same floor as `arch`.

    Same floor = above the next touched arch level down and no higher than
    `arch` itself (+ MATCH_TOL). Using only levels the stair touches keeps
    extra arch levels (ceilings, SSL references) from shrinking the band.
    Nearest first.
    """
    s = default_settings()
    if settings:
        s.update(settings)
    tol = mm(s.get("MATCH_TOL_MM", 5.0))
    lower = None
    for t in touched:
        if t.elev < arch.elev - tol and (lower is None or t.elev > lower):
            lower = t.elev
    out = [lv for lv in str_levels
           if lv.elev <= arch.elev + tol and
           (lower is None or lv.elev > lower + tol)]
    out.sort(key=lambda lv: -lv.elev)
    return out


def suggest_level(arch, candidates, str_levels, settings=None):
    """Default dropdown choice: name hint, then LEVEL_NAME_MAP / nearest
    below, then nearest candidate. None if the floor has no STR level."""
    if not candidates:
        return None
    s = default_settings()
    if settings:
        s.update(settings)
    hint = (s.get("STR_LEVEL_NAME_CONTAINS") or "").strip().lower()
    pool = candidates
    if hint:
        hinted = [c for c in candidates if hint in (c.name or "").lower()]
        if hinted:
            pool = hinted
    if pool is candidates:
        # without a name hint, skip STR levels sitting AT the finish level
        # (reference FFL levels) when a real slab level exists below
        below = [c for c in pool if arch.elev - c.elev >= mm(1.0)]
        if below:
            pool = below
    try:
        lv, _, _ = map_end(arch.elev, arch.name, pool, s)
        if lv in pool:
            return lv
    except MappingError:
        pass
    return pool[0]


def build_level_rows(flights, arch_levels, str_levels, settings=None,
                     saved=None):
    """Rows for the mapping dialog, highest level first.

    saved: {arch level name: STR level name} from the last run; used as the
    default when that STR level is still a candidate.
    """
    rows = {}
    order = []

    def row_for(a):
        if a.key not in rows:
            rows[a.key] = LevelRow(a)
            order.append(a.key)
        return rows[a.key]

    for f in flights:
        a_base, a_top = flight_ends(f, arch_levels, settings)
        if a_base is not None:
            r = row_for(a_base)
            r.is_base = True
            r.n_flights += 1
        if a_top is not None:
            row_for(a_top)
    touched = [rows[k].arch for k in order]
    saved = saved or {}
    for k in order:
        r = rows[k]
        r.candidates = floor_candidates(r.arch, touched, str_levels, settings)
        r.suggested = suggest_level(r.arch, r.candidates, str_levels,
                                    settings)
        want = saved.get(r.arch.name)
        if want:
            for c in r.candidates:
                if c.name == want:
                    r.suggested = c
                    break
    out = [rows[k] for k in order]
    out.sort(key=lambda r: -r.arch.elev)
    return out


def select_flights(flights, arch_levels, copy_keys, settings=None):
    """Flights whose base arch level is ticked."""
    out = []
    for f in flights:
        a_base, _ = flight_ends(f, arch_levels, settings)
        if a_base is not None and a_base.key in copy_keys:
            out.append(f)
    return out


def missing_mappings(flights, arch_levels, copy_keys, level_map,
                     settings=None):
    """Names of arch levels the ticked flights need but have no STR level."""
    missing = []
    for f in select_flights(flights, arch_levels, copy_keys, settings):
        for a in flight_ends(f, arch_levels, settings):
            if a is not None and level_map.get(a.key) is None \
                    and a.name not in missing:
                missing.append(a.name)
    return missing


def expand_placements(stair_key, base_level_elev, placement_elevs):
    """dz values for each level a (multistorey) stair is placed on.

    Always includes the stair's own base (dz = 0). Duplicates are removed and
    the result is sorted bottom to top.
    """
    dzs = [0.0]
    for e in placement_elevs:
        dz = float(e) - float(base_level_elev)
        if not any(abs(dz - d) < 1e-6 for d in dzs):
            dzs.append(dz)
    dzs.sort()
    return dzs


def placements_at(dzs, base_elev, height, z, tol=None):
    """Keep only the placement the user clicked on.

    A pinned stair group in a multistorey stair is ONE element placed on
    several floors, so the clicked element alone can't say which floor was
    meant; the pick point's height can. dzs: placement shifts; base_elev /
    height: the stair's base and height; z: pick point height (same frame).
    No point, or a point outside every placement -> all placements.
    """
    if z is None:
        return list(dzs)
    if tol is None:
        tol = mm(50.0)
    hits = [dz for dz in dzs
            if base_elev + dz - tol <= z <= base_elev + dz + height + tol]
    if not hits:
        return list(dzs)
    hits.sort(key=lambda dz: abs(base_elev + dz + height / 2.0 - z))
    return [hits[0]]


def plan_all(sources, arch_levels, str_levels, settings=None):
    plans = [plan_flight(s, arch_levels, str_levels, settings) for s in sources]
    plans.sort(key=lambda p: (p.source.base_elev + p.source.dz, p.source.key))
    return plans


def preview_rows(plans):
    """Rows for the pyRevit output table (all text, mm)."""
    rows = []
    for p in plans:
        if p.ok:
            status = "OK" if not p.warnings else "OK - see note"
            rows.append([
                p.source.label,
                "%s -> %s" % (p.arch_base_name, p.arch_top_name),
                "%s -> %s" % (p.base_level.name, p.top_level.name),
                "%.0f / %.0f" % (to_mm(p.finish_base), to_mm(p.finish_top)),
                "%.0f / %.0f" % (to_mm(p.base_offset), to_mm(p.top_offset)),
                "%.0f -> %.0f" % (to_mm(p.arch_height), to_mm(p.str_height)),
                "%d x %.1f" % (p.source.risers, to_mm(p.riser_height)),
                status + ("" if not p.warnings else ": " + " | ".join(p.warnings)),
            ])
        else:
            rows.append([p.source.label, "", "", "", "", "", "",
                         "SKIP: " + (p.error or "unknown")])
    return rows


PREVIEW_COLUMNS = ["Flight", "Arch levels", "STR levels", "Finish B/T (mm)",
                   "Offsets B/T (mm)", "Height A->S (mm)", "Risers",
                   "Status"]

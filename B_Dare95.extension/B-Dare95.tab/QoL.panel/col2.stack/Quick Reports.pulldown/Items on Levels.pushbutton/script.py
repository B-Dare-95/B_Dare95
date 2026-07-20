# -*- coding: utf-8 -*-
"""Elements per Level
Lists, per level, how many model elements sit on it and their category breakdown.

Rules:
  * Only real model elements are counted (CategoryType.Model). This automatically
    excludes annotation AND analytical elements (analytical cats are AnalyticalModel).
  * Sub-elements / parts are excluded via EXCLUDED_CATS below -- this covers
    Curtain Panels & Mullions (belong to Curtain Walls) plus stair/railing parts.
  * Element types are excluded (WhereElementIsNotElementType).
Read-only: no transaction required.
"""

import System
from Autodesk.Revit.DB import (
    FilteredElementCollector, Level, BuiltInCategory, BuiltInParameter,
    CategoryType, StorageType,
)
from pyrevit import revit, script

doc = revit.doc
output = script.get_output()

UNASSIGNED = -1


# ---- helpers ---------------------------------------------------------------
def eid_val(eid):
    """ElementId int value, Revit 2025+ (.Value) with .IntegerValue fallback."""
    try:
        return eid.Value
    except AttributeError:
        return eid.IntegerValue


def _bic(name):
    """Fetch a BuiltInCategory by name, or None if it doesn't exist in this version."""
    return getattr(BuiltInCategory, name, None)


def _bip(name):
    return getattr(BuiltInParameter, name, None)


def get_bic(cat):
    """BuiltInCategory of a Category (2023+ property, enum fallback)."""
    try:
        return cat.BuiltInCategory
    except AttributeError:
        try:
            return System.Enum.ToObject(BuiltInCategory, eid_val(cat.Id))
        except Exception:
            return None


# Categories to skip: sub-elements / parts of a parent element. Edit freely.
EXCLUDED_CATS = set(b for b in [
    _bic('OST_CurtainWallPanels'),
    _bic('OST_CurtainWallMullions'),
    # stair sub-parts (parent = OST_Stairs)
    _bic('OST_StairsRuns'),
    _bic('OST_StairsLandings'),
    _bic('OST_StairsSupports'),
    _bic('OST_StairsStringerCarriage'),
    # railing sub-parts (parent = OST_StairsRailing / OST_Railings)
    _bic('OST_RailingTopRail'),
    _bic('OST_RailingHandRail'),
    _bic('OST_RailingSupport'),
    _bic('OST_RailingTermination'),
    # datum noise
    _bic('OST_Levels'),
    _bic('OST_Grids'),
] if b is not None)

# Parameters searched (in order) to find an element's level when LevelId is empty.
LEVEL_BIPS = [p for p in [
    _bip('LEVEL_PARAM'),
    _bip('SCHEDULE_LEVEL_PARAM'),
    _bip('FAMILY_LEVEL_PARAM'),
    _bip('FAMILY_BASE_LEVEL_PARAM'),
    _bip('INSTANCE_REFERENCE_LEVEL_PARAM'),
    _bip('INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM'),
    _bip('WALL_BASE_CONSTRAINT'),
    _bip('ROOF_BASE_LEVEL_PARAM'),
    _bip('ROOM_LEVEL_ID'),
    _bip('STAIRS_BASE_LEVEL_PARAM'),
    _bip('RBS_START_LEVEL_PARAM'),
    _bip('FABRICATION_LEVEL_PARAM'),
] if p is not None]


def get_level_int(elem):
    """Return the associated level's int id, or UNASSIGNED."""
    # 1) direct property (fast, covers most elements)
    try:
        lid = elem.LevelId
        if lid is not None and eid_val(lid) > 0:
            return eid_val(lid)
    except Exception:
        pass
    # 2) fall back to known level parameters
    for bip in LEVEL_BIPS:
        try:
            p = elem.get_Parameter(bip)
        except Exception:
            p = None
        if p and p.HasValue and p.StorageType == StorageType.ElementId:
            v = p.AsElementId()
            if v is not None and eid_val(v) > 0:
                if isinstance(doc.GetElement(v), Level):
                    return eid_val(v)
    return UNASSIGNED


# ---- gather levels ---------------------------------------------------------
levels = list(FilteredElementCollector(doc)
              .OfClass(Level).WhereElementIsNotElementType().ToElements())
levels.sort(key=lambda l: l.Elevation)
level_map = {}                       # int -> Level
for l in levels:
    level_map[eid_val(l.Id)] = l


# ---- count -----------------------------------------------------------------
counts = {}      # level_int -> {cat_name: n}
totals = {}      # level_int -> n
cat_grand = {}   # cat_name  -> n

for elem in FilteredElementCollector(doc).WhereElementIsNotElementType():
    cat = elem.Category
    if cat is None:
        continue
    try:
        if cat.CategoryType != CategoryType.Model:   # drops annotation + analytical
            continue
    except Exception:
        continue
    bic = get_bic(cat)
    if bic is not None and bic in EXCLUDED_CATS:      # drops sub-elements
        continue

    lint = get_level_int(elem)
    name = cat.Name
    counts.setdefault(lint, {})
    counts[lint][name] = counts[lint].get(name, 0) + 1
    totals[lint] = totals.get(lint, 0) + 1
    cat_grand[name] = cat_grand.get(name, 0) + 1


# ---- report ----------------------------------------------------------------
output.print_md('# Elements per Level')

ordered = [eid_val(l.Id) for l in levels]
for k in counts:                     # any stray level ids not in the model list
    if k != UNASSIGNED and k not in ordered:
        ordered.append(k)

grand_total = 0
for lint in ordered:
    lvl = level_map.get(lint)
    lname = lvl.Name if lvl else 'Level id {}'.format(lint)
    mm = (lvl.Elevation * 304.8) if lvl else 0.0
    tot = totals.get(lint, 0)
    grand_total += tot

    output.print_md('---')
    if lvl:
        output.print_md('## {}  (elev {:.0f} mm)  —  {} elements'.format(lname, mm, tot))
    else:
        output.print_md('## {}  —  {} elements'.format(lname, tot))

    if tot == 0:
        output.print_md('_(no elements)_')
        continue
    cats = counts[lint]
    for cname in sorted(cats, key=lambda c: (-cats[c], c)):
        output.print_md('- **{}**: {}'.format(cname, cats[cname]))

# elements with no resolvable level
if UNASSIGNED in totals:
    tot = totals[UNASSIGNED]
    grand_total += 0  # already added above only for real levels; add here explicitly
    output.print_md('---')
    output.print_md('## No Level / Unassigned  —  {} elements'.format(tot))
    cats = counts[UNASSIGNED]
    for cname in sorted(cats, key=lambda c: (-cats[c], c)):
        output.print_md('- **{}**: {}'.format(cname, cats[cname]))

# totals across the whole model
total_all = sum(totals.values())
output.print_md('---')
output.print_md('# Totals by Category (all levels)')
for cname in sorted(cat_grand, key=lambda c: (-cat_grand[c], c)):
    output.print_md('- **{}**: {}'.format(cname, cat_grand[cname]))

output.print_md('---')
output.print_md('**Grand total counted: {} elements across {} levels.**'
                .format(total_all, len(levels)))
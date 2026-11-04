# -*- coding: utf-8 -*-
"""Elements per Level
Expandable, per-level breakdown of model elements, with click-to-select links.

Rules:
  * Only real model elements are counted (CategoryType.Model). This automatically
    excludes annotation AND analytical elements (analytical cats are AnalyticalModel).
  * Sub-elements / parts are excluded via EXCLUDED_CATS below -- this covers
    Curtain Panels & Mullions (belong to Curtain Walls) plus stair/railing parts.
  * Element types are excluded (WhereElementIsNotElementType).
  * Each level is a collapsible block; every level and every category row carries a
    link that selects those elements in Revit. Very long id lists are split into
    numbered chunks so the revit:// link stays valid.
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
output.set_width(1100)

UNASSIGNED = -1
MAX_LINK_IDS = 750          # ids per select link; longer lists are split in chunks
OPEN_BY_DEFAULT = False     # True = every level starts expanded


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


def esc(txt):
    """Minimal HTML escaping for category / level names."""
    return (txt.replace('&', '&amp;')
               .replace('<', '&lt;')
               .replace('>', '&gt;'))


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
buckets = {}     # level_int -> {cat_name: [ElementId, ...]}
totals = {}      # level_int -> n
cat_grand = {}   # cat_name  -> [ElementId, ...]

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
    buckets.setdefault(lint, {})
    buckets[lint].setdefault(name, []).append(elem.Id)
    totals[lint] = totals.get(lint, 0) + 1
    cat_grand.setdefault(name, []).append(elem.Id)


# ---- html building ---------------------------------------------------------
BLOCK_ID = [0]      # mutable counter (no nonlocal in IronPython 2.7)

ARROW_R = '&#9654;'     # collapsed
ARROW_D = '&#9660;'     # expanded

TOGGLE_JS = (
    "var b=document.getElementById('%s');"
    "var a=document.getElementById('%s');"
    "if(b.style.display=='none'){b.style.display='block';a.innerHTML='" + ARROW_D + "';}"
    "else{b.style.display='none';a.innerHTML='" + ARROW_R + "';}"
)

ALL_JS = (
    "var b=document.getElementsByClassName('epl-body');"
    "for(var i=0;i<b.length;i++){b[i].style.display='%s';}"
    "var a=document.getElementsByClassName('epl-arrow');"
    "for(var i=0;i<a.length;i++){a[i].innerHTML='%s';}"
)


def sel_links(ids, label='select'):
    """linkify link(s) for a list of ElementIds, chunked to keep the URL valid."""
    if not ids:
        return ''
    if len(ids) <= MAX_LINK_IDS:
        return output.linkify(ids, title=label)
    parts = []
    i = 0
    while i < len(ids):
        chunk = ids[i:i + MAX_LINK_IDS]
        parts.append(output.linkify(
            chunk, title='{} {}-{}'.format(label, i + 1, i + len(chunk))))
        i += MAX_LINK_IDS
    return '&nbsp;'.join(parts)


def cat_rows(cat_dict):
    """Table rows: category name, count, select link. Sorted by count desc."""
    rows = []
    for cname in sorted(cat_dict, key=lambda c: (-len(cat_dict[c]), c)):
        ids = cat_dict[cname]
        rows.append(
            '<tr>'
            '<td style="padding:3px 10px 3px 24px;">{}</td>'
            '<td style="padding:3px 10px;text-align:right;font-weight:bold;">{:,}</td>'
            '<td style="padding:3px 10px;">{}</td>'
            '</tr>'.format(esc(cname), len(ids), sel_links(ids))
        )
    return ''.join(rows)


def block(header_txt, all_ids, cat_dict, note=None):
    """One collapsible level block."""
    BLOCK_ID[0] += 1
    bid = 'epl-b{}'.format(BLOCK_ID[0])
    aid = 'epl-a{}'.format(BLOCK_ID[0])

    arrow = ARROW_D if OPEN_BY_DEFAULT else ARROW_R
    disp = 'block' if OPEN_BY_DEFAULT else 'none'

    head = (
        '<div onclick="{js}" style="cursor:pointer;padding:7px 10px;'
        'background:#2A2A3C;color:#CDD6F4;border-radius:5px 5px 0 0;'
        'font-size:14px;font-weight:bold;">'
        '<span class="epl-arrow" id="{aid}" style="color:#F0A500;">{arrow}</span>'
        '&nbsp;{head}</div>'
    ).format(js=TOGGLE_JS % (bid, aid), aid=aid, arrow=arrow, head=header_txt)

    body_bits = ['<div class="epl-body" id="{}" style="display:{};padding:6px 4px;">'
                 .format(bid, disp)]
    if note:
        body_bits.append('<div style="padding:4px 10px;color:#888;">{}</div>'.format(note))
    if all_ids:
        body_bits.append(
            '<div style="padding:4px 10px 8px 10px;">Select every element on this '
            'level:&nbsp;{}</div>'.format(sel_links(all_ids, 'select all')))
    if cat_dict:
        body_bits.append(
            '<table style="width:100%;border-collapse:collapse;">{}</table>'
            .format(cat_rows(cat_dict)))
    body_bits.append('</div>')

    return ('<div style="border:1px solid #45475A;border-radius:6px;margin:6px 0;'
            'overflow:hidden;">{}{}</div>'.format(head, ''.join(body_bits)))


# ---- report ----------------------------------------------------------------
output.print_md('# Elements per Level')

output.print_html(
    '<div style="margin:6px 0;">'
    '<a href="#" onclick="{expand};return false;" style="margin-right:14px;">'
    'Expand all</a>'
    '<a href="#" onclick="{collapse};return false;">Collapse all</a>'
    '</div>'.format(expand=ALL_JS % ('block', ARROW_D),
                    collapse=ALL_JS % ('none', ARROW_R))
)

ordered = [eid_val(l.Id) for l in levels]
for k in buckets:                    # any stray level ids not in the model list
    if k != UNASSIGNED and k not in ordered:
        ordered.append(k)

for lint in ordered:
    lvl = level_map.get(lint)
    lname = lvl.Name if lvl else 'Level id {}'.format(lint)
    tot = totals.get(lint, 0)
    cats = buckets.get(lint, {})

    all_ids = []
    for cname in cats:
        all_ids.extend(cats[cname])

    if lvl:
        mm = lvl.Elevation * 304.8
        header = ('{}&nbsp; <span style="font-weight:normal;color:#A6ADC8;">'
                  '(elev {:.0f} mm)</span>&nbsp; &mdash;&nbsp; '
                  '<span style="color:#F0A500;">{:,} elements</span>'
                  .format(esc(lname), mm, tot))
    else:
        header = ('{}&nbsp; &mdash;&nbsp; <span style="color:#F0A500;">'
                  '{:,} elements</span>'.format(esc(lname), tot))

    output.print_html(block(header, all_ids, cats,
                            note=None if tot else '<i>(no elements)</i>'))

# elements with no resolvable level
if UNASSIGNED in totals:
    cats = buckets[UNASSIGNED]
    all_ids = []
    for cname in cats:
        all_ids.extend(cats[cname])
    header = ('No Level / Unassigned&nbsp; &mdash;&nbsp; '
              '<span style="color:#F0A500;">{:,} elements</span>'
              .format(totals[UNASSIGNED]))
    output.print_html(block(header, all_ids, cats))

# totals across the whole model
total_all = sum(totals.values())
grand_header = ('Totals by Category (all levels)&nbsp; &mdash;&nbsp; '
                '<span style="color:#F0A500;">{:,} elements</span>'.format(total_all))
output.print_html(block(grand_header, None, cat_grand))

output.print_md('---')
output.print_md('**Grand total counted: {:,} elements across {} levels.**'
                .format(total_all, len(levels)))
# -*- coding: utf-8 -*-

__title__ = "Level Elements Lister"
__author__ = "Mohamed Bedair"
__version__ = '1.0.0'
__doc__ = """

Description:
 Scans your entire Revit project and generates a collapsible, clickable report
 of every Level in the model, showing the count of associated elements grouped
 by category — with an expand button to reveal each element individually.

How-to:
>> Click the tool button.
>> The output window opens and lists all levels sorted by elevation.
>> Each level shows element counts per category.
>> Click [+] to expand a category and see individual elements with clickable links.

Author: Mohamed Bedair
"""

# ─── Imports ─────────────────────────────────────────────────────────────────
from Autodesk.Revit.DB import (
    FilteredElementCollector,
    BuiltInCategory,
    BuiltInParameter,
    ElementLevelFilter,
    Level,
)
from pyrevit import script
from collections import defaultdict

# ─── Revit Variables ─────────────────────────────────────────────────────────
doc   = __revit__.ActiveUIDocument.Document
output = script.get_output()

# ─── Categories to scan ──────────────────────────────────────────────────────
CATEGORY_MAP = {
    "Rooms":               BuiltInCategory.OST_Rooms,
    "Floors":              BuiltInCategory.OST_Floors,
    "Walls":               BuiltInCategory.OST_Walls,
    "Structural Columns":  BuiltInCategory.OST_StructuralColumns,
    "Ceilings":            BuiltInCategory.OST_Ceilings,
    "Doors":               BuiltInCategory.OST_Doors,
    "Windows":             BuiltInCategory.OST_Windows,
    "Stairs":              BuiltInCategory.OST_Stairs,
    "Railings":            BuiltInCategory.OST_Railings,
    "Furniture":           BuiltInCategory.OST_Furniture,
    "Lighting Fixtures":   BuiltInCategory.OST_LightingFixtures,
    "Mechanical Equipment":BuiltInCategory.OST_MechanicalEquipment,
    "Plumbing Fixtures":   BuiltInCategory.OST_PlumbingFixtures,
    "Electrical Fixtures": BuiltInCategory.OST_ElectricalFixtures,
    "Generic Models":      BuiltInCategory.OST_GenericModel,
    "Specialty Equipment": BuiltInCategory.OST_SpecialityEquipment,
}

# ─── Helper: get a display name for an element ───────────────────────────────
def get_element_label(elem):
    """Return a human-readable label for an element."""
    try:
        # Try Mark parameter first (most elements)
        mark_p = elem.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark   = mark_p.AsString() if mark_p and mark_p.AsString() else ""

        # Family name + type name
        elem_type = doc.GetElement(elem.GetTypeId())
        if elem_type:
            fam_name  = ""
            fam_p = elem_type.get_Parameter(BuiltInParameter.SYMBOL_FAMILY_NAME_PARAM)
            if fam_p:
                fam_name = fam_p.AsString() or ""
            type_name = elem_type.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
            type_name = type_name.AsString() if type_name else ""
            label = "{} : {}".format(fam_name, type_name) if fam_name else type_name
        else:
            label = elem.Name if hasattr(elem, "Name") else "Element"

        # For rooms use their name
        name_p = elem.get_Parameter(BuiltInParameter.ROOM_NAME)
        if name_p:
            label = name_p.AsString() or label

        if mark:
            label = "[{}] {}".format(mark, label)

        return label if label.strip() else "Id {}".format(elem.Id)
    except Exception:
        return "Id {}".format(elem.Id)

# ─── Collect all levels sorted by elevation ──────────────────────────────────
levels = (
    FilteredElementCollector(doc)
    .OfClass(Level)
    .WhereElementIsNotElementType()
    .ToElements()
)

levels = sorted(levels, key=lambda l: l.Elevation)

if not levels:
    output.print_html("<b>No Levels found in the project.</b>")
    script.exit()

# ─── Build level → category → [elements] map ─────────────────────────────────
# Key: level Id (int)   Value: { cat_name: [elem, ...] }
level_data = { l.Id.Value: defaultdict(list) for l in levels }

for cat_name, bic in CATEGORY_MAP.items():
    try:
        elems = (
            FilteredElementCollector(doc)
            .OfCategory(bic)
            .WhereElementIsNotElementType()
            .ToElements()
        )
        for elem in elems:
            level_id_param = elem.get_Parameter(BuiltInParameter.FAMILY_LEVEL_PARAM) \
                          or elem.get_Parameter(BuiltInParameter.ROOM_LEVEL_ID)      \
                          or elem.get_Parameter(BuiltInParameter.STAIRS_BASE_LEVEL_PARAM)
            if level_id_param:
                lid = level_id_param.AsElementId()
                if lid and lid.Value in level_data:
                    level_data[lid.Value][cat_name].append(elem)
    except Exception:
        pass  # category may not exist in this model

# ─── Render output ────────────────────────────────────────────────────────────
output.print_html("""
<style>
  body        { font-family: Consolas, monospace; font-size: 13px; }
  .lvl-header { background:#2A2A3C; color:#F0A500; padding:6px 10px;
                border-left:4px solid #F0A500; margin-top:14px; margin-bottom:4px;
                border-radius:3px; font-size:14px; font-weight:bold; }
  .lvl-elev   { color:#A6ADC8; font-size:11px; font-weight:normal; margin-left:8px; }
  .lvl-empty  { color:#585B70; padding-left:12px; font-style:italic; }
  .cat-row    { display:flex; align-items:center; padding:2px 0 2px 14px; }
  .cat-toggle { cursor:pointer; color:#F0A500; font-weight:bold;
                margin-right:6px; user-select:none; min-width:18px;
                display:inline-block; text-align:center; }
  .cat-name   { color:#CDD6F4; min-width:200px; }
  .cat-count  { color:#A6ADC8; font-size:11px; margin-left:6px; }
  .elem-list  { display:none; padding:2px 0 4px 42px; }
  .elem-list a{ color:#89B4FA; text-decoration:none; display:block;
                padding:1px 0; font-size:12px; }
  .elem-list a:hover { text-decoration:underline; }
  hr          { border:none; border-top:1px solid #313244; margin:6px 0; }
</style>
<script>
function toggle(id){
  var el = document.getElementById(id);
  var btn = document.getElementById('btn_'+id);
  if(el.style.display === 'block'){
    el.style.display = 'none'; btn.innerText = '[+]';
  } else {
    el.style.display = 'block'; btn.innerText = '[–]';
  }
}
</script>
""")

total_levels_with_data = 0

for level in levels:
    lid     = level.Id.Value
    cat_map = level_data[lid]

    # Elevation label
    try:
        elev_str = "{:.3f}".format(level.Elevation)
    except Exception:
        elev_str = "?"

    output.print_html(
        '<div class="lvl-header">'
        '&#9660; {name}'
        '<span class="lvl-elev">elev: {elev}</span>'
        '</div>'.format(name=level.Name, elev=elev_str)
    )

    if not cat_map:
        output.print_html('<div class="lvl-empty">— no tracked elements on this level —</div>')
        continue

    total_levels_with_data += 1

    for cat_name in sorted(cat_map.keys()):
        elems    = cat_map[cat_name]
        uid      = "lv{}_{}".format(lid, cat_name.replace(" ", "_"))

        output.print_html(
            '<div class="cat-row">'
            '  <span class="cat-toggle" id="btn_{uid}" onclick="toggle(\'{uid}\')">[+]</span>'
            '  <span class="cat-name">{cat}</span>'
            '  <span class="cat-count">({count} element{s})</span>'
            '</div>'
            '<div class="elem-list" id="{uid}">'.format(
                uid=uid,
                cat=cat_name,
                count=len(elems),
                s="s" if len(elems) != 1 else "",
            )
        )

        for elem in elems:
            label = get_element_label(elem)
            link  = output.linkify(elem.Id, label)
            output.print_html('  ' + link)

        output.print_html('</div>')

    output.print_html('<hr/>')

# ─── Footer summary ───────────────────────────────────────────────────────────
output.print_html(
    '<div style="color:#585B70;font-size:11px;margin-top:10px;">'
    'Scanned {lc} level(s) &nbsp;|&nbsp; {dc} level(s) with elements'
    '</div>'.format(lc=len(levels), dc=total_levels_with_data)
)
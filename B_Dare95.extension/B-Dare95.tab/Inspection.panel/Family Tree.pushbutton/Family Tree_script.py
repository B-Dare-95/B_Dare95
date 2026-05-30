# -*- coding: utf-8 -*-
"""
Family Tree Investigator  -  B_Dare95.extension
Builds a visual HTML family-nesting tree for selected Revit families.
"""
import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitServices")
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from Autodesk.Revit.DB import (
    FilteredElementCollector, Family, FamilySymbol,
    BuiltInCategory, StorageType
)
from System.Windows import Window, WindowStartupLocation, Thickness, ResizeMode
from System.Windows.Controls import (
    StackPanel, ListBox, ListBoxItem, Button, TextBox,
    Label, Orientation, SelectionMode
)
from System.Windows.Media import SolidColorBrush, Color
from System.Windows import FontWeights
from System.Windows.Threading import Dispatcher, DispatcherFrame
import os, sys, tempfile, re

doc   = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

# =============================================================================
#  THEME  (Catppuccin Mocha)
# =============================================================================
BG      = Color.FromRgb(0x1E, 0x1E, 0x2E)
CARD    = Color.FromRgb(0x2A, 0x2A, 0x3C)
SURFACE = Color.FromRgb(0x31, 0x32, 0x44)
MUTED   = Color.FromRgb(0x45, 0x47, 0x5A)
TEXT    = Color.FromRgb(0xCD, 0xD6, 0xF4)
SUBTEXT = Color.FromRgb(0xA6, 0xAD, 0xC8)
ACCENT  = Color.FromRgb(0xF0, 0xA5, 0x00)

def brush(c): return SolidColorBrush(c)

# =============================================================================
#  EXCLUDED ANNOTATION CATEGORIES
# =============================================================================
EXCLUDED_CATS = {
    int(BuiltInCategory.OST_SectionHeads),
    int(BuiltInCategory.OST_LevelHeads),
    int(BuiltInCategory.OST_GridHeads),
    int(BuiltInCategory.OST_CalloutHeads),
    int(BuiltInCategory.OST_ElevationMarks),
    int(BuiltInCategory.OST_SpotElevSymbols),
    int(BuiltInCategory.OST_ViewportLabel),
}

def is_excluded(family):
    try:
        return int(family.FamilyCategory.Id.Value) in EXCLUDED_CATS
    except:
        try:
            return int(family.FamilyCategory.Id.IntegerValue) in EXCLUDED_CATS
        except:
            return False

# =============================================================================
#  HELPERS
# =============================================================================

def get_family_id_int(fam):
    try:
        return int(fam.Id.Value)
    except:
        return int(fam.Id.IntegerValue)

def get_type_count(family):
    """Count FamilySymbol types for a root family in the project."""
    try:
        fam_id = get_family_id_int(family)
        count = 0
        for s in FilteredElementCollector(doc).OfClass(FamilySymbol).ToElements():
            try:
                if get_family_id_int(s.Family) == fam_id:
                    count += 1
            except:
                pass
        return count
    except:
        return 0

def get_nested_type_count(nested_fam, family_doc):
    """Count types of a nested family inside an open family document."""
    try:
        fam_id = get_family_id_int(nested_fam)
        count = 0
        for s in FilteredElementCollector(family_doc).OfClass(FamilySymbol).ToElements():
            try:
                if get_family_id_int(s.Family) == fam_id:
                    count += 1
            except:
                pass
        return count
    except:
        return 0

def storage_type_label(st):
    """Human-readable storage type name."""
    try:
        name = str(st)
        mapping = {
            "String"        : "Text",
            "Double"        : "Number",
            "Integer"       : "Integer",
            "ElementId"     : "Element",
            "None"          : "—",
        }
        for k, v in mapping.items():
            if k in name:
                return v
        return name
    except:
        return "?"

def param_group_label(param):
    """Get the BuiltInParameterGroup display name (best-effort)."""
    try:
        # Revit 2023+ uses GetGroupTypeId / LabelUtils
        try:
            from Autodesk.Revit.DB import LabelUtils, GroupTypeId
            return LabelUtils.GetLabelForGroup(param.Definition.GetGroupTypeId())
        except:
            pass
        # Older API: Definition.ParameterGroup
        try:
            pg = param.Definition.ParameterGroup
            raw = str(pg)
            # Strip "PG_" prefix and title-case
            raw = raw.replace("PG_", "").replace("_", " ").title()
            return raw
        except:
            pass
    except:
        pass
    return "Other"

def get_param_details(family_doc):
    """
    Returns a list of dicts:
      { name, group, is_instance, data_type }
    sorted by group then name.
    """
    result = []
    try:
        mgr = family_doc.FamilyManager
        for p in mgr.GetParameters():
            try:
                name        = p.Definition.Name
                group       = param_group_label(p)
                is_instance = p.IsInstance
                data_type   = storage_type_label(p.StorageType)
                result.append({
                    "name"        : name,
                    "group"       : group,
                    "is_instance" : is_instance,
                    "data_type"   : data_type,
                })
            except:
                pass
    except:
        pass
    result.sort(key=lambda x: (x["group"], x["name"]))
    return result

# =============================================================================
#  RECURSIVE TREE DATA BUILDER
# =============================================================================

def build_tree(family, level=0, visited_names=None):
    if visited_names is None:
        visited_names = set()

    node = {
        "name"        : family.Name,
        "level"       : level,
        "type_count"  : 0,
        "inst_params" : 0,
        "type_params" : 0,
        "param_details": [],
        "editable"    : family.IsEditable,
        "children"    : [],
        "error"       : None,
    }

    if not family.Name or not family.Name.strip():
        node["error"] = "Unnamed system family skipped"
        return node

    if is_excluded(family):
        node["error"] = "Excluded annotation category"
        return node

    if not family.IsEditable:
        node["error"] = "Non-editable family"
        return node

    if family.Name in visited_names:
        node["error"] = "Circular reference skipped"
        return node
    visited_names.add(family.Name)

    if level == 0:
        node["type_count"] = get_type_count(family)

    try:
        family_doc = doc.EditFamily(family)
    except Exception as e:
        node["error"] = "Could not open: {}".format(str(e)[:60])
        return node

    details = get_param_details(family_doc)
    node["param_details"] = details
    node["inst_params"]   = sum(1 for p in details if p["is_instance"])
    node["type_params"]   = sum(1 for p in details if not p["is_instance"])

    nested = [
        f for f in FilteredElementCollector(family_doc).OfClass(Family).ToElements()
        if not is_excluded(f) and f.Name and f.Name.strip()
    ]

    for nf in nested:
        child = build_tree(nf, level + 1, visited_names)
        if child["error"] is None or child["error"] == "Non-editable family":
            child["type_count"] = get_nested_type_count(nf, family_doc)
        node["children"].append(child)

    return node

# =============================================================================
#  HTML GENERATOR
# =============================================================================

# Each tuple: (card_bg_tint, border_color, badge_bg, connector_color)
LEVEL_COLORS = [
    ("#2A2060", "#9D8FF7", "#7C6FF7", "#7C6FF7"),   # L0  lavender
    ("#2B1F00", "#F0C050", "#F0A500", "#F0A500"),   # L1  amber
    ("#082820", "#4DD9B8", "#22C9A0", "#22C9A0"),   # L2  teal
    ("#2E0F1A", "#F07FAA", "#E05C8A", "#E05C8A"),   # L3  pink
    ("#0A1E30", "#7FC0F0", "#5BA4E0", "#5BA4E0"),   # L4  blue
    ("#1A1040", "#C4B5FD", "#A78BFA", "#A78BFA"),   # L5+ purple
]

def lc(level):
    return LEVEL_COLORS[min(level, len(LEVEL_COLORS) - 1)]

def escape_html(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

def build_params_table(param_details, level):
    if not param_details:
        return ""
    _, border, _, _ = lc(level)

    # Group params
    groups = {}
    for p in param_details:
        groups.setdefault(p["group"], []).append(p)

    rows_html = ""
    for grp_name in sorted(groups.keys()):
        params = groups[grp_name]
        rows_html += """
        <tr class="group-row">
          <td colspan="3">{grp} <span class="grp-count">({cnt})</span></td>
        </tr>""".format(grp=escape_html(grp_name), cnt=len(params))
        for p in params:
            kind_class = "badge-inst" if p["is_instance"] else "badge-type"
            kind_label = "Instance"   if p["is_instance"] else "Type"
            rows_html += """
        <tr>
          <td class="param-name">{name}</td>
          <td><span class="param-dtype">{dtype}</span></td>
          <td><span class="param-kind {kclass}">{klabel}</span></td>
        </tr>""".format(
                name   = escape_html(p["name"]),
                dtype  = escape_html(p["data_type"]),
                kclass = kind_class,
                klabel = kind_label,
            )

    uid = "params_" + re.sub(r"[^a-zA-Z0-9]", "_", str(id(param_details)))

    return """
    <div class="params-section">
      <button class="params-toggle" onclick="toggleParams('{uid}')" style="border-color:{border};">
        <span class="toggle-icon" id="icon_{uid}">&#9654;</span>
        Parameters ({total})
      </button>
      <div class="params-table-wrap" id="{uid}" style="display:none;">
        <table class="params-table">
          <thead>
            <tr><th>Name</th><th>Data Type</th><th>Kind</th></tr>
          </thead>
          <tbody>
            {rows}
          </tbody>
        </table>
      </div>
    </div>""".format(
        uid    = uid,
        border = border,
        total  = len(param_details),
        rows   = rows_html,
    )

def node_to_html(node, is_last=True, ancestors_last=None):
    if ancestors_last is None:
        ancestors_last = []

    card_bg, border, badge_bg, conn_color = lc(node["level"])
    name  = escape_html(node["name"].replace(".rfa", ""))
    level = node["level"]
    kids  = node["children"]
    err   = node["error"]

    badge_label = "ROOT" if level == 0 else "L{}".format(level)

    # ── Stats pills
    if err and err not in ("Non-editable family",):
        stats_html = '<span class="stat stat-err">{}</span>'.format(escape_html(err))
        params_html = ""
    else:
        stats_html = (
            '<span class="stat stat-types" style="border-color:{bc};">'
            '&#128196; {tc} Types</span>'
            '<span class="stat stat-inst" style="border-color:#22C9A0;">'
            '&#9881; {ip} Instance Params</span>'
            '<span class="stat stat-type-p" style="border-color:#F0A500;">'
            '&#9881; {tp} Type Params</span>'
        ).format(
            bc = border,
            tc = node["type_count"],
            ip = node["inst_params"],
            tp = node["type_params"],
        )
        params_html = build_params_table(node["param_details"], level)

    # ── Tree branch connectors
    connector_html = ""
    for al in ancestors_last:
        connector_html += (
            '<div class="branch-space"></div>' if al
            else '<div class="branch-vert" style="--conn:{c};"></div>'.format(c=conn_color)
        )
    if level > 0:
        if is_last:
            connector_html += '<div class="branch-last" style="--conn:{c};"></div>'.format(c=conn_color)
        else:
            connector_html += '<div class="branch-mid" style="--conn:{c};"></div>'.format(c=conn_color)

    # ── Children
    children_html = ""
    for i, child in enumerate(kids):
        child_is_last = (i == len(kids) - 1)
        children_html += node_to_html(
            child,
            is_last=child_is_last,
            ancestors_last=ancestors_last + [is_last]
        )

    card_extra = " root-card" if level == 0 else ""

    return """
<div class="node-row">
  <div class="node-connectors">{connectors}</div>
  <div class="node-card{card_extra}" style="background:{card_bg}; border-color:{border}; border-left-color:{badge_bg};">
    <div class="node-header">
      <span class="node-badge" style="background:{badge_bg};">{badge_label}</span>
      <span class="node-name" title="{name_full}">{name}</span>
    </div>
    <div class="node-stats">{stats}</div>
    {params}
  </div>
</div>
{children}""".format(
        connectors = connector_html,
        card_extra = card_extra,
        card_bg    = card_bg,
        border     = border,
        badge_bg   = badge_bg,
        badge_label= badge_label,
        name_full  = name,
        name       = name,
        stats      = stats_html,
        params     = params_html,
        children   = children_html,
    )

def generate_html(family_name, root_node):
    tree_html = node_to_html(root_node, is_last=True, ancestors_last=[])

    legend_items = "".join([
        '<div class="legend-item">'
        '<div class="legend-dot" style="background:{bg};"></div>'
        'Level {lbl}'
        '</div>'.format(
            bg  = LEVEL_COLORS[i][2],
            lbl = i if i < len(LEVEL_COLORS) - 1 else "{}+".format(len(LEVEL_COLORS) - 1)
        )
        for i in range(len(LEVEL_COLORS))
    ])

    return u"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<title>Family Tree - {title}</title>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Syne:wght@700;800&display=swap" rel="stylesheet"/>
<style>
  :root {{
    --bg:      #0A0A14;
    --surface: #12121F;
    --card:    #1A1A2E;
    --border:  #2A2A42;
    --text:    #E2E8F8;
    --subtext: #8892B0;
    --accent:  #F0A500;
    --radius:  10px;
    --mono:    'JetBrains Mono', monospace;
    --display: 'Syne', sans-serif;
    --conn:    #3A3A5A;
  }}
  *, *::before, *::after {{ box-sizing: border-box; margin:0; padding:0; }}
  body {{
    background: var(--bg);
    color: var(--text);
    font-family: var(--mono);
    font-size: 13px;
    min-height: 100vh;
    padding: 40px 48px;
  }}

  /* === HEADER === */
  .report-header {{
    margin-bottom: 40px;
    border-left: 4px solid var(--accent);
    padding-left: 20px;
  }}
  .report-header h1 {{
    font-family: var(--display);
    font-size: 26px;
    font-weight: 800;
    letter-spacing: -0.5px;
    color: var(--text);
    margin-top: 8px;
  }}
  .report-header .subtitle {{
    color: var(--subtext);
    font-size: 11px;
    margin-top: 5px;
  }}
  .report-header .tag {{
    display: inline-block;
    background: var(--accent);
    color: #0A0A14;
    font-weight: 700;
    font-size: 10px;
    padding: 3px 10px;
    border-radius: 20px;
    letter-spacing: 1px;
    text-transform: uppercase;
  }}

  /* === TREE LAYOUT === */
  .tree-root {{ padding: 8px 0; }}

  .node-row {{
    display: flex;
    align-items: flex-start;
    margin: 5px 0;
  }}

  /* === CONNECTORS === */
  .node-connectors {{
    display: flex;
    align-items: stretch;
    flex-shrink: 0;
    align-self: stretch;
  }}
  .branch-space,
  .branch-vert,
  .branch-last,
  .branch-mid {{
    width: 32px;
    position: relative;
    flex-shrink: 0;
  }}
  /* Continuous vertical line (ancestor still has children below) */
  .branch-vert::before {{
    content: '';
    position: absolute;
    left: 15px; top: 0; bottom: 0;
    width: 2px;
    background: var(--conn);
  }}
  /* Last child: vertical line only to mid-point, then horizontal */
  .branch-last::before {{
    content: '';
    position: absolute;
    left: 15px; top: 0; height: 26px;
    width: 2px;
    background: var(--conn);
  }}
  .branch-last::after {{
    content: '';
    position: absolute;
    left: 15px; top: 24px;
    width: 17px; height: 2px;
    background: var(--conn);
  }}
  /* Mid child: full vertical + horizontal */
  .branch-mid::before {{
    content: '';
    position: absolute;
    left: 15px; top: 0; bottom: 0;
    width: 2px;
    background: var(--conn);
  }}
  .branch-mid::after {{
    content: '';
    position: absolute;
    left: 15px; top: 24px;
    width: 17px; height: 2px;
    background: var(--conn);
  }}

  /* === NODE CARD === */
  .node-card {{
    border: 1.5px solid var(--border);
    border-left: 4px solid;
    border-radius: var(--radius);
    padding: 10px 14px;
    min-width: 280px;
    max-width: 560px;
    width: max-content;
    transition: transform 0.12s, box-shadow 0.12s;
    margin-top: 2px;
  }}
  .node-card:hover {{
    transform: translateY(-2px);
    box-shadow: 0 8px 28px rgba(0,0,0,0.5);
  }}
  .root-card {{
    min-width: 320px;
    border-left-width: 5px;
  }}
  .node-header {{
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 8px;
    flex-wrap: wrap;
  }}
  .node-badge {{
    font-family: var(--display);
    font-size: 10px;
    font-weight: 700;
    padding: 2px 9px;
    border-radius: 20px;
    color: #08080F;
    letter-spacing: 0.8px;
    flex-shrink: 0;
  }}
  .node-name {{
    font-size: 13px;
    font-weight: 600;
    color: var(--text);
    word-break: break-word;
  }}
  .root-card .node-name {{
    font-family: var(--display);
    font-size: 15px;
  }}

  /* === STAT PILLS === */
  .node-stats {{
    display: flex;
    flex-wrap: wrap;
    gap: 5px;
    margin-bottom: 4px;
  }}
  .stat {{
    display: inline-flex;
    align-items: center;
    gap: 4px;
    border-radius: 6px;
    padding: 3px 9px;
    font-size: 11px;
    white-space: nowrap;
    border: 1px solid transparent;
  }}
  .stat-types  {{ background: rgba(93,  120, 255, 0.12); color: #9BAFF8; border-color: rgba(93,120,255,0.3); }}
  .stat-inst   {{ background: rgba(34,  201, 160, 0.12); color: #4DD9B8; border-color: rgba(34,201,160,0.3); }}
  .stat-type-p {{ background: rgba(240, 165,   0, 0.12); color: #F0C050; border-color: rgba(240,165,0,0.3); }}
  .stat-err    {{ background: rgba(248, 113, 113, 0.12); color: #F87171; border-color: rgba(248,113,113,0.3); }}

  /* === PARAMS SECTION === */
  .params-section {{
    margin-top: 8px;
  }}
  .params-toggle {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: rgba(255,255,255,0.04);
    border: 1px solid;
    border-radius: 6px;
    padding: 3px 10px;
    font-family: var(--mono);
    font-size: 11px;
    color: var(--subtext);
    cursor: pointer;
    transition: background 0.1s, color 0.1s;
  }}
  .params-toggle:hover {{
    background: rgba(255,255,255,0.08);
    color: var(--text);
  }}
  .toggle-icon {{
    font-size: 9px;
    transition: transform 0.15s;
  }}
  .toggle-icon.open {{
    transform: rotate(90deg);
  }}
  .params-table-wrap {{
    margin-top: 8px;
    border-radius: 8px;
    overflow: hidden;
    border: 1px solid var(--border);
  }}
  .params-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 11px;
  }}
  .params-table thead tr {{
    background: rgba(255,255,255,0.06);
  }}
  .params-table th {{
    text-align: left;
    padding: 6px 10px;
    color: var(--subtext);
    font-weight: 600;
    font-size: 10px;
    letter-spacing: 0.5px;
    text-transform: uppercase;
    border-bottom: 1px solid var(--border);
  }}
  .params-table td {{
    padding: 5px 10px;
    border-bottom: 1px solid rgba(255,255,255,0.04);
    color: var(--text);
    vertical-align: middle;
  }}
  .params-table tbody tr:last-child td {{
    border-bottom: none;
  }}
  .params-table tbody tr:hover td {{
    background: rgba(255,255,255,0.03);
  }}
  .group-row td {{
    background: rgba(255,255,255,0.05);
    color: var(--subtext);
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.6px;
    padding: 4px 10px;
    border-bottom: 1px solid var(--border) !important;
  }}
  .grp-count {{
    font-weight: 400;
    opacity: 0.7;
  }}
  .param-name {{
    color: var(--text);
  }}
  .param-dtype {{
    display: inline-block;
    background: rgba(93,120,255,0.15);
    color: #9BAFF8;
    border-radius: 4px;
    padding: 1px 6px;
    font-size: 10px;
  }}
  .param-kind {{
    display: inline-block;
    border-radius: 4px;
    padding: 1px 6px;
    font-size: 10px;
    font-weight: 600;
  }}
  .badge-inst {{ background: rgba(34,201,160,0.18); color: #4DD9B8; }}
  .badge-type {{ background: rgba(240,165,  0,0.18); color: #F0C050; }}

  /* === LEGEND === */
  .legend {{
    margin-top: 48px;
    padding: 18px 24px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    display: flex;
    flex-wrap: wrap;
    gap: 14px;
    align-items: center;
  }}
  .legend-title {{
    width: 100%;
    font-family: var(--display);
    font-size: 11px;
    color: var(--subtext);
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-bottom: 2px;
  }}
  .legend-item {{
    display: flex;
    align-items: center;
    gap: 7px;
    font-size: 11px;
    color: var(--subtext);
  }}
  .legend-dot {{
    width: 10px; height: 10px;
    border-radius: 3px;
    flex-shrink: 0;
  }}

  /* === SCROLLBAR === */
  ::-webkit-scrollbar {{ width: 7px; height: 7px; }}
  ::-webkit-scrollbar-track {{ background: var(--bg); }}
  ::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 4px; }}
</style>
</head>
<body>
<div class="report-header">
  <div class="tag">Family Tree Report</div>
  <h1>{title}</h1>
  <div class="subtitle">Revit Family Nesting Analysis &nbsp;&middot;&nbsp; Generated by B_Dare95 Tools</div>
</div>
<div class="tree-root">
{tree}
</div>
<div class="legend">
  <div class="legend-title">Nesting Level Colors</div>
  {legend_items}
</div>
<script>
function toggleParams(uid) {{
  var el   = document.getElementById(uid);
  var icon = document.getElementById('icon_' + uid);
  if (el.style.display === 'none') {{
    el.style.display = 'block';
    icon.classList.add('open');
  }} else {{
    el.style.display = 'none';
    icon.classList.remove('open');
  }}
}}
</script>
</body>
</html>""".format(
        title        = escape_html(family_name),
        tree         = tree_html,
        legend_items = legend_items,
    )

# =============================================================================
#  WPF DISPATCHER HELPERS
# =============================================================================
frame = [None]

def run_dispatcher_frame():
    frame[0] = DispatcherFrame()
    Dispatcher.PushFrame(frame[0])

def stop_frame():
    if frame[0] and frame[0].Continue:
        frame[0].Continue = False

# =============================================================================
#  WPF UI WIDGET HELPERS
# =============================================================================

def make_label(text, bold=False, size=13, color=TEXT):
    lbl            = Label()
    lbl.Content    = text
    lbl.Foreground = brush(color)
    lbl.FontSize   = size
    if bold:
        lbl.FontWeight = FontWeights.Bold
    lbl.Padding = Thickness(0)
    return lbl

def make_textbox(placeholder=""):
    tb                 = TextBox()
    tb.Background      = brush(SURFACE)
    tb.Foreground      = brush(TEXT)
    tb.BorderBrush     = brush(MUTED)
    tb.BorderThickness = Thickness(1)
    tb.Padding         = Thickness(8, 6, 8, 6)
    tb.FontSize        = 13
    tb.Text            = placeholder
    tb.Margin          = Thickness(0, 0, 0, 8)
    return tb

def style_button(btn, accent=False):
    btn.Background      = brush(ACCENT if accent else SURFACE)
    btn.Foreground      = brush(Color.FromRgb(0x0A, 0x0A, 0x14) if accent else TEXT)
    btn.BorderThickness = Thickness(0)
    btn.FontSize        = 13
    btn.Padding         = Thickness(14, 8, 14, 8)
    btn.Margin          = Thickness(0, 8, 8, 0)

def make_listbox(height=None, multi=False):
    lb                 = ListBox()
    lb.Background      = brush(CARD)
    lb.Foreground      = brush(TEXT)
    lb.BorderBrush     = brush(MUTED)
    lb.BorderThickness = Thickness(1)
    lb.FontSize        = 13
    lb.Padding         = Thickness(4)
    if height:
        lb.Height = height
    if multi:
        lb.SelectionMode = SelectionMode.Multiple
    return lb

# =============================================================================
#  DATA – collect editable families by category
# =============================================================================

all_families = [
    f for f in FilteredElementCollector(doc).OfClass(Family).ToElements()
    if f.IsEditable and not is_excluded(f) and f.FamilyCategory
]

cat_to_families = {}
for fam in all_families:
    cat_to_families.setdefault(fam.FamilyCategory.Name, []).append(fam)

all_cats = sorted(cat_to_families.keys())

# =============================================================================
#  STEP 1 – Category selection window
# =============================================================================
cat_selected = [None]

def show_category_window():
    win                        = Window()
    win.Title                  = "Family Tree  -  Step 1: Select Category"
    win.Width                  = 420
    win.Height                 = 580
    win.Background             = brush(BG)
    win.WindowStartupLocation  = WindowStartupLocation.CenterScreen
    win.ResizeMode             = ResizeMode.CanResize

    sp        = StackPanel()
    sp.Margin = Thickness(20)

    sp.Children.Add(make_label("Select Category", bold=True, size=16))
    sp.Children.Add(make_label(
        "{} categories with editable families".format(len(all_cats)),
        size=11, color=SUBTEXT
    ))

    search = make_textbox("")
    sp.Children.Add(search)

    lb = make_listbox(height=390)

    def populate_cats(cats):
        lb.Items.Clear()
        for cat in cats:
            count = len(cat_to_families[cat])
            item  = ListBoxItem()
            row   = StackPanel()
            row.Orientation = Orientation.Horizontal
            row.Children.Add(make_label(cat, size=13))
            row.Children.Add(make_label("  ({})".format(count), size=11, color=SUBTEXT))
            item.Content = row
            item.Tag     = cat
            lb.Items.Add(item)

    populate_cats(all_cats)
    search.TextChanged += lambda s, e: populate_cats(
        [c for c in all_cats if search.Text.lower() in c.lower()]
    )

    sp.Children.Add(lb)

    row_btns             = StackPanel()
    row_btns.Orientation = Orientation.Horizontal

    btn_next             = Button()
    btn_next.Content     = "Next  ->"
    style_button(btn_next, accent=True)

    btn_cancel           = Button()
    btn_cancel.Content   = "Cancel"
    style_button(btn_cancel)

    def on_next(s, e):
        sel = lb.SelectedItem
        if sel:
            cat_selected[0] = sel.Tag
            win.Close()

    def on_cancel(s, e):
        win.Close()

    btn_next.Click   += on_next
    btn_cancel.Click += on_cancel

    row_btns.Children.Add(btn_next)
    row_btns.Children.Add(btn_cancel)
    sp.Children.Add(row_btns)

    win.Content = sp
    win.Closed += lambda s, e: stop_frame()
    win.Show()
    run_dispatcher_frame()

show_category_window()

if not cat_selected[0]:
    sys.exit(0)

selected_cat     = cat_selected[0]
families_in_cat  = cat_to_families[selected_cat]

# =============================================================================
#  STEP 2 – Family selection window
# =============================================================================
fam_selected = [None]

def show_family_window():
    win                       = Window()
    win.Title                 = "Family Tree  -  Step 2: Select Families  [{}]".format(selected_cat)
    win.Width                 = 520
    win.Height                = 620
    win.Background            = brush(BG)
    win.WindowStartupLocation = WindowStartupLocation.CenterScreen

    sp        = StackPanel()
    sp.Margin = Thickness(20)

    sp.Children.Add(make_label("Category: {}".format(selected_cat), bold=True, size=15))
    sp.Children.Add(make_label(
        "{} families  -  Ctrl+Click for multi-select".format(len(families_in_cat)),
        size=11, color=SUBTEXT
    ))

    search = make_textbox("")
    sp.Children.Add(search)

    lb = make_listbox(height=420, multi=True)

    def populate_fams(fams):
        lb.Items.Clear()
        for fam in fams:
            type_count = get_type_count(fam)
            item       = ListBoxItem()
            item.Tag   = fam

            row             = StackPanel()
            row.Orientation = Orientation.Horizontal

            name_lbl       = make_label(fam.Name, size=13)
            name_lbl.Width = 300

            types_lbl = make_label(
                "  {} types".format(type_count), size=11, color=SUBTEXT
            )

            row.Children.Add(name_lbl)
            row.Children.Add(types_lbl)
            item.Content = row
            lb.Items.Add(item)

    populate_fams(families_in_cat)
    search.TextChanged += lambda s, e: populate_fams(
        [f for f in families_in_cat if search.Text.lower() in f.Name.lower()]
    )

    sp.Children.Add(lb)

    row_btns             = StackPanel()
    row_btns.Orientation = Orientation.Horizontal

    btn_run            = Button()
    btn_run.Content    = "Investigate  ->"
    style_button(btn_run, accent=True)

    btn_cancel         = Button()
    btn_cancel.Content = "Cancel"
    style_button(btn_cancel)

    def on_run(s, e):
        sel = [item.Tag for item in lb.SelectedItems]
        if sel:
            fam_selected[0] = sel
            win.Close()

    def on_cancel(s, e):
        win.Close()

    btn_run.Click    += on_run
    btn_cancel.Click += on_cancel

    row_btns.Children.Add(btn_run)
    row_btns.Children.Add(btn_cancel)
    sp.Children.Add(row_btns)

    win.Content = sp
    win.Closed += lambda s, e: stop_frame()
    win.Show()
    run_dispatcher_frame()

show_family_window()

if not fam_selected[0]:
    sys.exit(0)

selected_families = fam_selected[0]

# =============================================================================
#  BUILD TREES & WRITE HTML
# =============================================================================
output_paths = []

for fam in selected_families:
    root_node = build_tree(fam, level=0)
    html_str  = generate_html(fam.Name.replace(".rfa", ""), root_node)

    safe_name = re.sub(r'[^A-Za-z0-9_-]', '_', fam.Name)
    tmp_path  = os.path.join(tempfile.gettempdir(), "FamilyTree_{}.html".format(safe_name))

    with open(tmp_path, "w") as f:
        if isinstance(html_str, unicode):
            f.write(html_str.encode("utf-8"))
        else:
            f.write(html_str)

    output_paths.append(tmp_path)
    os.startfile(tmp_path)

print("Family Tree HTML reports generated:")
for p in output_paths:
    print("  " + p)
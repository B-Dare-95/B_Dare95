# -*- coding: utf-8 -*-

__title__   = "MEP Filters"
__doc__     = """
________________________________________________________________
Description:
- Creates View Filters for MEP for Visual Inspection

How to Use:
- Run the script
- A configuration dialog will open
- For MEP Systems:
    * Edit the filter name (pre-filled with defaults)
    * Pick a System Classification from the dropdown
      (values are loaded from all linked Revit files)
    * Choose a highlight color
- For Electrical (Cable Trays / Conduits):
    * Edit the filter name
    * Type any match text (Type Name contains...)
    * Choose a highlight color
- Click "Apply Filters" to create/apply the filters
________________________________________________________________
Author: Mohamed Bedair"""

# ── Imports ───────────────────────────────────────────────────────────────────
import clr
clr.AddReference('System')
clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Drawing')

from System.Collections.Generic import List
import System.Windows.Forms as WinForms
import System.Drawing as Drawing

from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from pyrevit import script

# ── Revit Variables ───────────────────────────────────────────────────────────
uidoc       = __revit__.ActiveUIDocument
doc         = __revit__.ActiveUIDocument.Document
app         = __revit__.Application
active_view = doc.ActiveView
output      = script.get_output()

# ── UI Theme ──────────────────────────────────────────────────────────────────
DARK_BG    = Drawing.Color.FromArgb(28,  28,  28)
ROW_A      = Drawing.Color.FromArgb(48,  48,  48)
ROW_B      = Drawing.Color.FromArgb(43,  43,  43)
HEADER_BG  = Drawing.Color.FromArgb(33,  33,  33)
SECTION_BG = Drawing.Color.FromArgb(30,  60, 100)
WARN_BG    = Drawing.Color.FromArgb(80,  55,  10)
TEXT_FG    = Drawing.Color.FromArgb(220, 220, 220)
DIM_FG     = Drawing.Color.FromArgb(150, 150, 150)
ACCENT_FG  = Drawing.Color.FromArgb(100, 180, 255)
WARN_FG    = Drawing.Color.FromArgb(255, 200,  80)
INPUT_BG   = Drawing.Color.FromArgb(58,  58,  58)
BTN_BG     = Drawing.Color.FromArgb(58,  58,  58)
BTN_OK_BG  = Drawing.Color.FromArgb(0,   100, 180)
BORDER_CLR = Drawing.Color.FromArgb(72,  72,  72)

FONT_NORM  = Drawing.Font("Segoe UI", 9)
FONT_BOLD  = Drawing.Font("Segoe UI", 9, Drawing.FontStyle.Bold)
FONT_TITLE = Drawing.Font("Segoe UI", 11, Drawing.FontStyle.Bold)
FONT_WARN  = Drawing.Font("Segoe UI", 8, Drawing.FontStyle.Italic)

# ── Filter Defaults ───────────────────────────────────────────────────────────
mp_default_names = [
    "COORD_SUPPLY DUCTS",
    "COORD_RETURN DUCTS",
    "COORD_EXHAUST DUCTS",
    "COORD_FIRE PIPES",
    "COORD_NOVEC PIPES",
    "COORD_COLD WATER PIPES",
    "COORD_HOT WATER PIPES",
    "COORD_SUPPLY CHILLED WATER",
    "COORD_RETURN CHILLED WATER",
    "COORD_DRAINAGE",
]

mp_default_colors = [
    Drawing.Color.FromArgb(0,   128, 255),
    Drawing.Color.FromArgb(255, 128,  64),
    Drawing.Color.FromArgb(0,   128,   0),
    Drawing.Color.FromArgb(255,   0,   0),
    Drawing.Color.FromArgb(128, 128,   0),
    Drawing.Color.FromArgb(0,     0, 255),
    Drawing.Color.FromArgb(255, 115,  47),
    Drawing.Color.FromArgb(128, 128, 255),
    Drawing.Color.FromArgb(255, 255, 128),
    Drawing.Color.FromArgb(64,    0,  64),
]

# Used to pre-select the matching ComboBox item if found in the linked-file values
mp_default_classifications = [
    "Supply Air",
    "Return Air",
    "Exhaust Air",
    "Fire Protection Wet",
    "Fire Protection Other",
    "Domestic Cold Water",
    "Domestic Hot Water",
    "Hydronic Supply",
    "Hydronic Return",
    "Sanitary",
]

mp_categories = [
    BuiltInCategory.OST_DuctSystem,
    BuiltInCategory.OST_DuctAccessory,
    BuiltInCategory.OST_DuctCurves,
    BuiltInCategory.OST_DuctFitting,
    BuiltInCategory.OST_FlexDuctCurves,
    BuiltInCategory.OST_DuctTerminal,
    BuiltInCategory.OST_PipeCurves,
    BuiltInCategory.OST_PipeFitting,
    BuiltInCategory.OST_PipeAccessory,
    BuiltInCategory.OST_FlexPipeCurves,
    BuiltInCategory.OST_PipingSystem,
]

elec_default_names  = ["COORD_ELECTRIC TRAYS",            "COORD_ICT TRAYS"            ]
elec_default_texts  = ["_E_",                              "_T_"                        ]
elec_default_colors = [Drawing.Color.FromArgb(255, 255, 0), Drawing.Color.FromArgb(128, 255, 255)]

electrical_categories = [
    BuiltInCategory.OST_CableTray,
    BuiltInCategory.OST_CableTrayFitting,
    BuiltInCategory.OST_Conduit,
    BuiltInCategory.OST_ConduitFitting,
]

mp_param_id   = ElementId(BuiltInParameter.RBS_SYSTEM_CLASSIFICATION_PARAM)
elec_param_id = ElementId(BuiltInParameter.SYMBOL_NAME_PARAM)


# ── Linked-File Scanner ───────────────────────────────────────────────────────
def get_linked_system_classifications():
    """
    Scans every loaded RevitLinkInstance for unique values of
    RBS_SYSTEM_CLASSIFICATION_PARAM on duct / pipe system elements.

    Returns a sorted list of unique strings.
    Returns an empty list when no links are loaded or none are resolved.
    """
    values = set()
    link_instances = FilteredElementCollector(doc).OfClass(RevitLinkInstance).ToElements()

    for link_inst in link_instances:
        link_doc = link_inst.GetLinkDocument()
        if link_doc is None:
            continue   # link not loaded / not resolved

        for bic in [BuiltInCategory.OST_DuctSystem, BuiltInCategory.OST_PipingSystem]:
            try:
                collector = (FilteredElementCollector(link_doc)
                             .OfCategory(bic)
                             .WhereElementIsNotElementType())
                for elem in collector:
                    param = elem.get_Parameter(BuiltInParameter.RBS_SYSTEM_CLASSIFICATION_PARAM)
                    if param and param.HasValue:
                        val = param.AsString()
                        if val and val.strip():
                            values.add(val.strip())
            except Exception:
                pass   # skip categories that fail on a particular link

    return sorted(values)


# ── Revit Helper Functions ────────────────────────────────────────────────────
def get_existing_filter(filter_name):
    all_filters = FilteredElementCollector(doc).OfClass(ParameterFilterElement).ToElements()
    for f in all_filters:
        if f.Name == filter_name:
            return f
    return None


def is_filter_applied_to_view(view, filter_id):
    return filter_id in view.GetFilters()


def _get_pattern_elements():
    all_fill    = FilteredElementCollector(doc).OfClass(FillPatternElement).ToElements()
    solid_fp    = next(p for p in all_fill if p.GetFillPattern().IsSolidFill)
    all_line    = FilteredElementCollector(doc).OfClass(LinePatternElement).ToElements()
    solid_lp_id = all_line[0].GetSolidPatternId()
    return solid_fp, solid_lp_id


def _build_overrides(drawing_color):
    solid_fp, solid_lp_id = _get_pattern_elements()
    rv_color = Color(drawing_color.R, drawing_color.G, drawing_color.B)
    ogs = OverrideGraphicSettings()
    ogs.SetSurfaceForegroundPatternId(solid_fp.Id)
    ogs.SetSurfaceForegroundPatternColor(rv_color)
    ogs.SetSurfaceBackgroundPatternId(solid_fp.Id)
    ogs.SetSurfaceBackgroundPatternColor(rv_color)
    ogs.SetProjectionLinePatternId(solid_lp_id)
    ogs.SetProjectionLineColor(rv_color)
    ogs.SetProjectionLineWeight(1)
    return ogs


def create_view_filter(filter_name, cats, param_id, param_value, drawing_color):
    overrides       = _build_overrides(drawing_color)
    existing_filter = get_existing_filter(filter_name)

    if existing_filter is not None:
        if is_filter_applied_to_view(active_view, existing_filter.Id):
            output.print_md("**Skipped (already applied):** {}".format(filter_name))
        else:
            active_view.AddFilter(existing_filter.Id)
            active_view.SetFilterOverrides(existing_filter.Id, overrides)
            output.print_md("**Applied existing filter:** {}".format(filter_name))
    else:
        cats_ids    = [ElementId(c) for c in cats]
        pvp         = ParameterValueProvider(param_id)
        if app.VersionNumber <= "2021":
            rule = FilterStringRule(pvp, FilterStringContains(), param_value, True)
        else:
            rule = FilterStringRule(pvp, FilterStringContains(), param_value)
        elem_filter = ElementParameterFilter(rule)
        view_filter = ParameterFilterElement.Create(
            doc, filter_name, List[ElementId](cats_ids), elem_filter
        )
        active_view.AddFilter(view_filter.Id)
        active_view.SetFilterOverrides(view_filter.Id, overrides)
        output.print_md("**Created new filter:** {}".format(filter_name))


# ── UI Layout Constants ───────────────────────────────────────────────────────
ROW_H   = 34
COL1_W  = 210   # editable filter name
COL2_W  = 200   # classification combo / match textbox
COL3_W  = 82    # colour swatch
GUTTER  = 8
TOTAL_W = GUTTER + COL1_W + COL2_W + COL3_W + GUTTER   # 508


# ── Primitive Builders ────────────────────────────────────────────────────────
def _lbl(text, x, y, w, h, font=None, fg=None, bg=None,
         align=Drawing.ContentAlignment.MiddleLeft):
    lb = WinForms.Label()
    lb.Text      = text
    lb.Location  = Drawing.Point(x, y)
    lb.Size      = Drawing.Size(w, h)
    lb.Font      = font or FONT_NORM
    lb.ForeColor = fg   or TEXT_FG
    lb.BackColor = bg   or Drawing.Color.Transparent
    lb.TextAlign = align
    return lb


def _input_tb(default_text):
    tb = WinForms.TextBox()
    tb.Text        = default_text
    tb.Height      = 22
    tb.BackColor   = INPUT_BG
    tb.ForeColor   = TEXT_FG
    tb.Font        = FONT_NORM
    tb.BorderStyle = WinForms.BorderStyle.FixedSingle
    return tb


def _classification_combo(items, preselect=None):
    cb = WinForms.ComboBox()
    cb.DropDownStyle = WinForms.ComboBoxStyle.DropDownList
    cb.BackColor     = INPUT_BG
    cb.ForeColor     = TEXT_FG
    cb.Font          = FONT_NORM
    cb.FlatStyle     = WinForms.FlatStyle.Flat
    cb.Height        = 22
    for item in items:
        cb.Items.Add(item)
    if preselect and preselect in items:
        cb.SelectedItem = preselect
    elif cb.Items.Count > 0:
        cb.SelectedIndex = 0
    return cb


def _swatch_btn(color):
    btn = WinForms.Button()
    btn.Size      = Drawing.Size(COL3_W - 12, ROW_H - 10)
    btn.BackColor = color
    btn.FlatStyle = WinForms.FlatStyle.Flat
    btn.FlatAppearance.BorderColor = BORDER_CLR
    btn.FlatAppearance.BorderSize  = 1
    btn.Text      = ""
    btn.Cursor    = WinForms.Cursors.Hand
    return btn


def _separator(y, w):
    sep = WinForms.Panel()
    sep.Location  = Drawing.Point(GUTTER, y)
    sep.Size      = Drawing.Size(w, 1)
    sep.BackColor = BORDER_CLR
    return sep


# ── Main Dialog ───────────────────────────────────────────────────────────────
def show_filter_dialog(linked_classifications, fallback_used):
    """
    linked_classifications  - sorted list of system classification strings
    fallback_used           - True when no links were found (hardcoded defaults used)

    Returns result dict on confirmation, or None if cancelled.
    """
    # Mutable state (IronPython 2.7 – no nonlocal)
    mp_colors      = list(mp_default_colors)
    elec_colors    = list(elec_default_colors)
    confirmed      = [False]
    mp_name_tbs    = []    # TextBox  – MEP filter names
    mp_combos      = []    # ComboBox – system classifications
    elec_name_tbs  = []    # TextBox  – electrical filter names
    elec_match_tbs = []    # TextBox  – electrical match text

    form_w = TOTAL_W + 20

    form = WinForms.Form()
    form.Text            = "MEP Filters Configuration"
    form.BackColor       = DARK_BG
    form.ForeColor       = TEXT_FG
    form.Width           = form_w
    form.FormBorderStyle = WinForms.FormBorderStyle.FixedDialog
    form.StartPosition   = WinForms.FormStartPosition.CenterScreen
    form.MaximizeBox     = False
    form.MinimizeBox     = False
    form.Font            = FONT_NORM

    y = [10]   # running vertical cursor (list for closure mutability)

    # ── Title bar ─────────────────────────────────────────────────────────────
    form.Controls.Add(_lbl(
        "  MEP FILTER CONFIGURATION",
        0, y[0], form_w, 36,
        font=FONT_TITLE, fg=ACCENT_FG,
        bg=Drawing.Color.FromArgb(22, 22, 22)
    ))
    y[0] += 44

    # ── Helpers inside the dialog ─────────────────────────────────────────────
    def add_section_hdr(title):
        form.Controls.Add(_lbl(
            "  " + title,
            GUTTER, y[0], TOTAL_W, 26,
            font=FONT_BOLD,
            fg=Drawing.Color.FromArgb(180, 220, 255),
            bg=SECTION_BG
        ))
        y[0] += 26

    def add_col_headers(mid_label):
        hdr = WinForms.Panel()
        hdr.Location  = Drawing.Point(GUTTER, y[0])
        hdr.Size      = Drawing.Size(TOTAL_W, 24)
        hdr.BackColor = HEADER_BG
        hdr.Controls.Add(_lbl("Filter Name",  4,       0, COL1_W,    24, fg=DIM_FG, font=FONT_BOLD))
        hdr.Controls.Add(_lbl(mid_label,      COL1_W,  0, COL2_W,    24, fg=DIM_FG, font=FONT_BOLD))
        hdr.Controls.Add(_lbl("Color",
            COL1_W + COL2_W, 0, COL3_W, 24,
            fg=DIM_FG, font=FONT_BOLD,
            align=Drawing.ContentAlignment.MiddleCenter))
        form.Controls.Add(hdr)
        y[0] += 24

    def add_row(row_idx, name_widget, mid_widget, swatch):
        row = WinForms.Panel()
        row.Location  = Drawing.Point(GUTTER, y[0])
        row.Size      = Drawing.Size(TOTAL_W, ROW_H)
        row.BackColor = ROW_A if row_idx % 2 == 0 else ROW_B

        name_widget.Location = Drawing.Point(4, (ROW_H - name_widget.Height) // 2)
        name_widget.Width    = COL1_W - 8

        mid_widget.Location  = Drawing.Point(COL1_W, (ROW_H - mid_widget.Height) // 2)
        mid_widget.Width     = COL2_W - 8

        swatch.Location = Drawing.Point(
            COL1_W + COL2_W + (COL3_W - swatch.Width) // 2,
            (ROW_H - swatch.Height) // 2
        )

        row.Controls.Add(name_widget)
        row.Controls.Add(mid_widget)
        row.Controls.Add(swatch)
        form.Controls.Add(row)
        y[0] += ROW_H

    # ══════════════════════════════════════════════════════════════════════════
    # Section 1 – MEP Systems
    # ══════════════════════════════════════════════════════════════════════════
    add_section_hdr("MEP Systems  (filtered by System Classification)")

    if fallback_used:
        form.Controls.Add(_lbl(
            "  \u26a0  No loaded Revit links found – showing default classification values.",
            GUTTER, y[0], TOTAL_W, 20,
            font=FONT_WARN, fg=WARN_FG, bg=WARN_BG
        ))
        y[0] += 20

    add_col_headers("System Classification")

    for i in range(len(mp_default_names)):
        name_tb = _input_tb(mp_default_names[i])
        mp_name_tbs.append(name_tb)

        combo = _classification_combo(
            linked_classifications,
            preselect=mp_default_classifications[i]
        )
        mp_combos.append(combo)

        swatch = _swatch_btn(mp_default_colors[i])

        def mp_click(s, e, idx=i, btn=swatch):
            dlg          = WinForms.ColorDialog()
            dlg.Color    = mp_colors[idx]
            dlg.FullOpen = True
            if dlg.ShowDialog() == WinForms.DialogResult.OK:
                mp_colors[idx] = dlg.Color
                btn.BackColor  = dlg.Color

        swatch.Click += mp_click
        add_row(i, name_tb, combo, swatch)

    y[0] += 12

    # ══════════════════════════════════════════════════════════════════════════
    # Section 2 – Electrical
    # ══════════════════════════════════════════════════════════════════════════
    add_section_hdr("Electrical  (Cable Trays & Conduits – match by Type Name)")
    add_col_headers("Match Text  (Type Name contains...)")

    for i in range(len(elec_default_names)):
        name_tb  = _input_tb(elec_default_names[i])
        elec_name_tbs.append(name_tb)

        match_tb = _input_tb(elec_default_texts[i])
        elec_match_tbs.append(match_tb)

        swatch = _swatch_btn(elec_default_colors[i])

        def elec_click(s, e, idx=i, btn=swatch):
            dlg          = WinForms.ColorDialog()
            dlg.Color    = elec_colors[idx]
            dlg.FullOpen = True
            if dlg.ShowDialog() == WinForms.DialogResult.OK:
                elec_colors[idx] = dlg.Color
                btn.BackColor    = dlg.Color

        swatch.Click += elec_click
        add_row(i, name_tb, match_tb, swatch)

    y[0] += 14

    # ── Footer ────────────────────────────────────────────────────────────────
    form.Controls.Add(_separator(y[0], TOTAL_W))
    y[0] += 10

    btn_cancel = WinForms.Button()
    btn_cancel.Text      = "Cancel"
    btn_cancel.Size      = Drawing.Size(100, 32)
    btn_cancel.Location  = Drawing.Point(form_w - 244, y[0])
    btn_cancel.BackColor = BTN_BG
    btn_cancel.ForeColor = TEXT_FG
    btn_cancel.FlatStyle = WinForms.FlatStyle.Flat
    btn_cancel.FlatAppearance.BorderColor = BORDER_CLR
    btn_cancel.Font      = FONT_NORM
    btn_cancel.Cursor    = WinForms.Cursors.Hand

    btn_apply = WinForms.Button()
    btn_apply.Text      = "Apply Filters"
    btn_apply.Size      = Drawing.Size(128, 32)
    btn_apply.Location  = Drawing.Point(form_w - 136, y[0])
    btn_apply.BackColor = BTN_OK_BG
    btn_apply.ForeColor = Drawing.Color.White
    btn_apply.FlatStyle = WinForms.FlatStyle.Flat
    btn_apply.FlatAppearance.BorderColor = Drawing.Color.FromArgb(0, 140, 220)
    btn_apply.Font      = FONT_BOLD
    btn_apply.Cursor    = WinForms.Cursors.Hand

    def on_cancel(s, e):
        form.Close()

    def on_apply(s, e):
        # Validate MEP filter names
        for i, tb in enumerate(mp_name_tbs):
            if not tb.Text.strip():
                WinForms.MessageBox.Show(
                    "Filter name for MEP row {} cannot be empty.".format(i + 1),
                    "Validation", WinForms.MessageBoxButtons.OK,
                    WinForms.MessageBoxIcon.Warning)
                return
        # Validate MEP combo selections
        for i, cb in enumerate(mp_combos):
            if cb.SelectedIndex < 0:
                WinForms.MessageBox.Show(
                    "Please select a System Classification for row {}.".format(i + 1),
                    "Validation", WinForms.MessageBoxButtons.OK,
                    WinForms.MessageBoxIcon.Warning)
                return
        # Validate electrical filter names
        for i, tb in enumerate(elec_name_tbs):
            if not tb.Text.strip():
                WinForms.MessageBox.Show(
                    "Filter name for Electrical row {} cannot be empty.".format(i + 1),
                    "Validation", WinForms.MessageBoxButtons.OK,
                    WinForms.MessageBoxIcon.Warning)
                return
        # Validate electrical match texts
        for i, tb in enumerate(elec_match_tbs):
            if not tb.Text.strip():
                WinForms.MessageBox.Show(
                    "Match text for '{}' cannot be empty.".format(
                        elec_name_tbs[i].Text.strip() or "row {}".format(i + 1)),
                    "Validation", WinForms.MessageBoxButtons.OK,
                    WinForms.MessageBoxIcon.Warning)
                return
        confirmed[0] = True
        form.Close()

    btn_cancel.Click += on_cancel
    btn_apply.Click  += on_apply

    form.Controls.Add(btn_cancel)
    form.Controls.Add(btn_apply)

    y[0] += 42
    form.Height = y[0] + 42   # +42 for OS window chrome

    form.ShowDialog()

    if not confirmed[0]:
        return None

    return {
        "mp_names"           : [tb.Text.strip()      for tb in mp_name_tbs],
        "mp_classifications" : [str(cb.SelectedItem) for cb in mp_combos],
        "mp_colors"          : mp_colors,
        "elec_names"         : [tb.Text.strip()      for tb in elec_name_tbs],
        "elec_texts"         : [tb.Text.strip()      for tb in elec_match_tbs],
        "elec_colors"        : elec_colors,
    }


# ── Entry Point ───────────────────────────────────────────────────────────────

# 1. Scan all loaded linked files for unique System Classification values
linked_classifications = get_linked_system_classifications()
fallback_used          = len(linked_classifications) == 0

if fallback_used:
    # No links loaded – fall back to hardcoded defaults so the dialog is usable
    linked_classifications = list(mp_default_classifications)

# 2. Show the configuration dialog
result = show_filter_dialog(linked_classifications, fallback_used)

if result is None:
    script.exit()

# 3. Create / apply all filters in a single transaction
with Transaction(doc, __title__) as t:
    t.Start()

    for i in range(len(result["mp_names"])):
        create_view_filter(
            result["mp_names"][i],
            mp_categories,
            mp_param_id,
            result["mp_classifications"][i],
            result["mp_colors"][i],
        )

    for i in range(len(result["elec_names"])):
        create_view_filter(
            result["elec_names"][i],
            electrical_categories,
            elec_param_id,
            result["elec_texts"][i],
            result["elec_colors"][i],
        )

    t.Commit()
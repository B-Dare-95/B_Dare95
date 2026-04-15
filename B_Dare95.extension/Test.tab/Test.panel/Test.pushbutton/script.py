# -*- coding: utf-8 -*-

__title__   = "MEP Filters"
__doc__     = """
________________________________________________________________
Description:
- Creates View Filters for MEP for Visual Inspection

How to Use:
- Run the script
- A configuration dialog will open
- For MEP Systems: assign a color to each System Classification
- For Electrical (Cable Trays): type a match text and assign a color
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
PANEL_BG   = Drawing.Color.FromArgb(38,  38,  38)
ROW_A      = Drawing.Color.FromArgb(48,  48,  48)
ROW_B      = Drawing.Color.FromArgb(43,  43,  43)
HEADER_BG  = Drawing.Color.FromArgb(33,  33,  33)
SECTION_BG = Drawing.Color.FromArgb(30,  60, 100)
TEXT_FG    = Drawing.Color.FromArgb(220, 220, 220)
DIM_FG     = Drawing.Color.FromArgb(150, 150, 150)
ACCENT_FG  = Drawing.Color.FromArgb(100, 180, 255)
GREEN_FG   = Drawing.Color.FromArgb(140, 200, 140)
BTN_BG     = Drawing.Color.FromArgb(58,  58,  58)
BTN_OK_BG  = Drawing.Color.FromArgb(0,   100, 180)
BORDER_CLR = Drawing.Color.FromArgb(72,  72,  72)

FONT_NORM  = Drawing.Font("Segoe UI", 9)
FONT_BOLD  = Drawing.Font("Segoe UI", 9, Drawing.FontStyle.Bold)
FONT_TITLE = Drawing.Font("Segoe UI", 11, Drawing.FontStyle.Bold)

# ── Filter Data ───────────────────────────────────────────────────────────────
mp_filters_names = [
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

system_class_names = [
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

elec_filters_names   = ["COORD_ELECTRIC TRAYS",          "COORD_ICT TRAYS"           ]
elec_default_colors  = [Drawing.Color.FromArgb(255,255,0), Drawing.Color.FromArgb(128,255,255)]
elec_default_texts   = ["_E_",                            "_T_"                        ]

electrical_categories = [
    BuiltInCategory.OST_CableTray,
    BuiltInCategory.OST_CableTrayFitting,
    BuiltInCategory.OST_Conduit,
    BuiltInCategory.OST_ConduitFitting,
]

mp_param_id   = ElementId(BuiltInParameter.RBS_SYSTEM_CLASSIFICATION_PARAM)
elec_param_id = ElementId(BuiltInParameter.SYMBOL_NAME_PARAM)

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
    """Cache-friendly fetch of solid fill + solid line pattern IDs."""
    all_fill = FilteredElementCollector(doc).OfClass(FillPatternElement).ToElements()
    solid_fp  = next(p for p in all_fill if p.GetFillPattern().IsSolidFill)

    all_line  = FilteredElementCollector(doc).OfClass(LinePatternElement).ToElements()
    solid_lp_id = all_line[0].GetSolidPatternId()
    return solid_fp, solid_lp_id


def _build_overrides(drawing_color):
    """Convert a System.Drawing.Color into a Revit OverrideGraphicSettings."""
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
    overrides        = _build_overrides(drawing_color)
    existing_filter  = get_existing_filter(filter_name)

    if existing_filter is not None:
        if is_filter_applied_to_view(active_view, existing_filter.Id):
            output.print_md("**Skipped (already applied):** {}".format(filter_name))
        else:
            active_view.AddFilter(existing_filter.Id)
            active_view.SetFilterOverrides(existing_filter.Id, overrides)
            output.print_md("**Applied existing filter:** {}".format(filter_name))
    else:
        cats_ids       = [ElementId(c) for c in cats]
        pvp            = ParameterValueProvider(param_id)

        if app.VersionNumber <= "2021":
            rule = FilterStringRule(pvp, FilterStringContains(), param_value, True)
        else:
            rule = FilterStringRule(pvp, FilterStringContains(), param_value)

        elem_filter  = ElementParameterFilter(rule)
        view_filter  = ParameterFilterElement.Create(
            doc, filter_name, List[ElementId](cats_ids), elem_filter
        )
        active_view.AddFilter(view_filter.Id)
        active_view.SetFilterOverrides(view_filter.Id, overrides)
        output.print_md("**Created new filter:** {}".format(filter_name))


# ── UI Helpers ────────────────────────────────────────────────────────────────
ROW_H  = 34
COL1_W = 220   # Filter name
COL2_W = 195   # System class / text input
COL3_W = 80    # Color swatch
GUTTER = 8     # Left margin inside form
TOTAL_W = GUTTER + COL1_W + COL2_W + COL3_W + GUTTER  # 511


def _lbl(text, x, y, w, h, font=None, fg=None, bg=None,
         align=Drawing.ContentAlignment.MiddleLeft):
    lb = WinForms.Label()
    lb.Text      = text
    lb.Location  = Drawing.Point(x, y)
    lb.Size      = Drawing.Size(w, h)
    lb.Font      = font  or FONT_NORM
    lb.ForeColor = fg    or TEXT_FG
    lb.BackColor = bg    or Drawing.Color.Transparent
    lb.TextAlign = align
    return lb


def _color_btn(x, y, color):
    """Square swatch button that opens a ColorDialog when clicked."""
    btn = WinForms.Button()
    btn.Location  = Drawing.Point(x, y)
    btn.Size      = Drawing.Size(COL3_W - 10, ROW_H - 8)
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
def show_filter_dialog():
    # Mutable state (IronPython 2.7 – no nonlocal)
    mp_colors   = list(mp_default_colors)
    elec_colors = list(elec_default_colors)
    confirmed   = [False]

    form_w = TOTAL_W + 20   # outer form width

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

    y = [10]   # running vertical cursor as a list for closure access

    # ── Title bar ────────────────────────────────────────────────────────────
    form.Controls.Add(_lbl(
        "  MEP FILTER CONFIGURATION",
        0, y[0], form_w, 36,
        font=FONT_TITLE, fg=ACCENT_FG,
        bg=Drawing.Color.FromArgb(22, 22, 22)
    ))
    y[0] += 44

    # ── Column header row ────────────────────────────────────────────────────
    def add_column_headers():
        hdr = WinForms.Panel()
        hdr.Location  = Drawing.Point(GUTTER, y[0])
        hdr.Size      = Drawing.Size(TOTAL_W, 24)
        hdr.BackColor = HEADER_BG
        hdr.Controls.Add(_lbl("Filter Name",            2,       0, COL1_W,    24, fg=DIM_FG, font=FONT_BOLD))
        hdr.Controls.Add(_lbl("System Classification",  COL1_W, 0, COL2_W,    24, fg=DIM_FG, font=FONT_BOLD))
        hdr.Controls.Add(_lbl("Color",                  COL1_W + COL2_W, 0, COL3_W, 24, fg=DIM_FG, font=FONT_BOLD,
                               align=Drawing.ContentAlignment.MiddleCenter))
        form.Controls.Add(hdr)
        y[0] += 24

    # ── Section header ───────────────────────────────────────────────────────
    def add_section_hdr(title):
        form.Controls.Add(_lbl(
            "  " + title,
            GUTTER, y[0], TOTAL_W, 26,
            font=FONT_BOLD,
            fg=Drawing.Color.FromArgb(180, 220, 255),
            bg=SECTION_BG
        ))
        y[0] += 26

    # ── Row builder (returns color button for wiring) ────────────────────────
    def add_row(idx, name_text, right_widget, row_color, color_btn_obj):
        """
        Adds a single filter row to the form.
        right_widget  – a pre-built Control (Label or TextBox)
        color_btn_obj – the swatch Button for this row
        """
        row = WinForms.Panel()
        row.Location  = Drawing.Point(GUTTER, y[0] + idx * ROW_H)
        row.Size      = Drawing.Size(TOTAL_W, ROW_H)
        row.BackColor = ROW_A if idx % 2 == 0 else ROW_B

        name_lbl = _lbl(name_text, 4, 0, COL1_W - 4, ROW_H)

        right_widget.Location = Drawing.Point(COL1_W, (ROW_H - right_widget.Height) // 2)
        right_widget.Width    = COL2_W - 8

        color_btn_obj.Location = Drawing.Point(
            COL1_W + COL2_W + (COL3_W - color_btn_obj.Width) // 2,
            (ROW_H - color_btn_obj.Height) // 2
        )

        row.Controls.Add(name_lbl)
        row.Controls.Add(right_widget)
        row.Controls.Add(color_btn_obj)
        form.Controls.Add(row)

    # ═════════════════════════════════════════════════════════════════════════
    # Section 1 – MEP Systems
    # ═════════════════════════════════════════════════════════════════════════
    add_section_hdr("MEP Systems  (filtered by System Classification)")
    add_column_headers()

    for i in range(len(mp_filters_names)):
        # Right side: read-only label showing the classification value
        cls_lbl = WinForms.Label()
        cls_lbl.Text      = system_class_names[i]
        cls_lbl.Height    = ROW_H - 8
        cls_lbl.Font      = FONT_NORM
        cls_lbl.ForeColor = GREEN_FG
        cls_lbl.BackColor = Drawing.Color.Transparent
        cls_lbl.TextAlign = Drawing.ContentAlignment.MiddleLeft

        swatch = _color_btn(0, 0, mp_default_colors[i])

        # Click handler – closure captures index and button correctly
        def mp_click(s, e, idx=i, btn=swatch):
            dlg       = WinForms.ColorDialog()
            dlg.Color = mp_colors[idx]
            dlg.FullOpen = True
            if dlg.ShowDialog() == WinForms.DialogResult.OK:
                mp_colors[idx] = dlg.Color
                btn.BackColor  = dlg.Color

        swatch.Click += mp_click
        add_row(i, mp_filters_names[i], cls_lbl, ROW_A, swatch)

    y[0] += len(mp_filters_names) * ROW_H + 12

    # ═════════════════════════════════════════════════════════════════════════
    # Section 2 – Electrical (Cable Trays / Conduits)
    # ═════════════════════════════════════════════════════════════════════════
    add_section_hdr("Electrical  (Cable Trays & Conduits – match by Type Name)")
    add_column_headers()

    # Override header label for the middle column
    form.Controls.Add(_lbl(
        "Match Text  (Type Name contains…)",
        GUTTER + COL1_W, y[0] - 24, COL2_W, 24,
        fg=DIM_FG, font=FONT_BOLD
    ))

    elec_textboxes = []   # kept for reading values after dialog closes

    for i in range(len(elec_filters_names)):
        tb = WinForms.TextBox()
        tb.Text        = elec_default_texts[i]
        tb.Height      = 22
        tb.BackColor   = Drawing.Color.FromArgb(62, 62, 62)
        tb.ForeColor   = TEXT_FG
        tb.Font        = FONT_NORM
        tb.BorderStyle = WinForms.BorderStyle.FixedSingle
        elec_textboxes.append(tb)

        swatch = _color_btn(0, 0, elec_default_colors[i])

        def elec_click(s, e, idx=i, btn=swatch):
            dlg       = WinForms.ColorDialog()
            dlg.Color = elec_colors[idx]
            dlg.FullOpen = True
            if dlg.ShowDialog() == WinForms.DialogResult.OK:
                elec_colors[idx] = dlg.Color
                btn.BackColor    = dlg.Color

        swatch.Click += elec_click
        add_row(i, elec_filters_names[i], tb, ROW_A, swatch)

    y[0] += len(elec_filters_names) * ROW_H + 16

    # ═════════════════════════════════════════════════════════════════════════
    # Bottom bar – Cancel / Apply
    # ═════════════════════════════════════════════════════════════════════════
    form.Controls.Add(_separator(y[0], TOTAL_W))
    y[0] += 10

    btn_cancel = WinForms.Button()
    btn_cancel.Text      = "Cancel"
    btn_cancel.Size      = Drawing.Size(100, 32)
    btn_cancel.Location  = Drawing.Point(form_w - 240, y[0])
    btn_cancel.BackColor = BTN_BG
    btn_cancel.ForeColor = TEXT_FG
    btn_cancel.FlatStyle = WinForms.FlatStyle.Flat
    btn_cancel.FlatAppearance.BorderColor = BORDER_CLR
    btn_cancel.Font      = FONT_NORM
    btn_cancel.Cursor    = WinForms.Cursors.Hand

    btn_apply = WinForms.Button()
    btn_apply.Text      = "Apply Filters"
    btn_apply.Size      = Drawing.Size(120, 32)
    btn_apply.Location  = Drawing.Point(form_w - 130, y[0])
    btn_apply.BackColor = BTN_OK_BG
    btn_apply.ForeColor = Drawing.Color.White
    btn_apply.FlatStyle = WinForms.FlatStyle.Flat
    btn_apply.FlatAppearance.BorderColor = Drawing.Color.FromArgb(0, 140, 220)
    btn_apply.Font      = FONT_BOLD
    btn_apply.Cursor    = WinForms.Cursors.Hand

    def on_cancel(s, e):
        form.Close()

    def on_apply(s, e):
        for i, tb in enumerate(elec_textboxes):
            if not tb.Text.strip():
                WinForms.MessageBox.Show(
                    "Match text for '{}' cannot be empty.".format(elec_filters_names[i]),
                    "Validation Error",
                    WinForms.MessageBoxButtons.OK,
                    WinForms.MessageBoxIcon.Warning
                )
                return
        confirmed[0] = True
        form.Close()

    btn_cancel.Click += on_cancel
    btn_apply.Click  += on_apply

    form.Controls.Add(btn_cancel)
    form.Controls.Add(btn_apply)

    y[0] += 42
    form.Height = y[0] + 40   # +40 for window chrome

    form.ShowDialog()

    if not confirmed[0]:
        return None

    return {
        "mp_colors"   : mp_colors,
        "elec_colors" : elec_colors,
        "elec_texts"  : [tb.Text.strip() for tb in elec_textboxes],
    }


# ── Entry Point ───────────────────────────────────────────────────────────────
result = show_filter_dialog()

if result is None:
    script.exit()

with Transaction(doc, __title__) as t:
    t.Start()

    for i in range(len(mp_filters_names)):
        create_view_filter(
            mp_filters_names[i],
            mp_categories,
            mp_param_id,
            system_class_names[i],
            result["mp_colors"][i],
        )

    for i in range(len(elec_filters_names)):
        create_view_filter(
            elec_filters_names[i],
            electrical_categories,
            elec_param_id,
            result["elec_texts"][i],
            result["elec_colors"][i],
        )

    t.Commit()
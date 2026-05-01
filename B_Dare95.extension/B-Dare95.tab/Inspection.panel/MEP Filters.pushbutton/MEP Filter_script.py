# -*- coding: utf-8 -*-

__title__   = "MEP Filters"
__doc__     = """
________________________________________________________________
Description:
- Creates View Filters for MEP for Visual Inspection

How to Use:
- Run the script
- A configuration dialog opens with four discipline sections:
    HVAC / Plumbing / Fire Protection / Electrical
- Each section starts with pre-filled default rows.
- Click "+" at the bottom of any section to add a new row.
- Click "×" on a row to delete it.
- For HVAC / Plumbing / Fire:
    * Edit the filter name
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

# ── UI Theme (Catppuccin Mocha) ───────────────────────────────────────────────
DARK_BG    = Drawing.Color.FromArgb(30,  30,  46)   # #1E1E2E  base
ROW_A      = Drawing.Color.FromArgb(49,  50,  68)   # #313244  surface
ROW_B      = Drawing.Color.FromArgb(42,  42,  60)   # #2A2A3C  card
HEADER_BG  = Drawing.Color.FromArgb(30,  30,  46)   # #1E1E2E  base
SECTION_BG = Drawing.Color.FromArgb(69,  71,  90)   # #45475A  muted
WARN_BG    = Drawing.Color.FromArgb(62,  48,  18)   # amber-tinted surface
TEXT_FG    = Drawing.Color.FromArgb(205, 214, 244)  # #CDD6F4  text
DIM_FG     = Drawing.Color.FromArgb(166, 173, 200)  # #A6ADC8  subtext
ACCENT_FG  = Drawing.Color.FromArgb(240, 165,   0)  # #F0A500  accent
WARN_FG    = Drawing.Color.FromArgb(249, 226, 175)  # #F9E2AF  yellow
INPUT_BG   = Drawing.Color.FromArgb(49,  50,  68)   # #313244  surface
BTN_BG     = Drawing.Color.FromArgb(69,  71,  90)   # #45475A  muted
BTN_OK_BG  = Drawing.Color.FromArgb(240, 165,   0)  # #F0A500  accent
BORDER_CLR = Drawing.Color.FromArgb(69,  71,  90)   # #45475A  muted

FONT_NORM  = Drawing.Font("Segoe UI", 9)
FONT_BOLD  = Drawing.Font("Segoe UI", 9, Drawing.FontStyle.Bold)
FONT_TITLE = Drawing.Font("Segoe UI", 11, Drawing.FontStyle.Bold)
FONT_WARN  = Drawing.Font("Segoe UI", 8, Drawing.FontStyle.Italic)

# ── Layout Constants ──────────────────────────────────────────────────────────
ROW_H       = 34
COL1_W      = 210    # filter name
COL2_W      = 200    # classification / match text
SWATCH_W    = 56     # colour swatch column
DEL_W       = 22     # delete button column
COL3_W      = SWATCH_W + DEL_W + 4   # = 82  (colour + delete, combined header)
GUTTER      = 8
TOTAL_W     = GUTTER + COL1_W + COL2_W + COL3_W + GUTTER   # 508
HDR_H       = 26
COL_HDR_H   = 24
ADD_BTN_H   = 30
SECTION_GAP = 14
TITLE_H     = 44
FORM_W      = TOTAL_W + 20            # 528
MAX_FORM_H  = 780

# ── Revit Parameter IDs ───────────────────────────────────────────────────────
MP_PARAM_ID   = ElementId(BuiltInParameter.RBS_SYSTEM_CLASSIFICATION_PARAM)
ELEC_PARAM_ID = ElementId(BuiltInParameter.SYMBOL_NAME_PARAM)

# ── Category Groups ───────────────────────────────────────────────────────────
HVAC_CATS = [
    BuiltInCategory.OST_DuctSystem,
    BuiltInCategory.OST_DuctAccessory,
    BuiltInCategory.OST_DuctCurves,
    BuiltInCategory.OST_DuctFitting,
    BuiltInCategory.OST_FlexDuctCurves,
    BuiltInCategory.OST_DuctTerminal,
]
PIPE_CATS = [
    BuiltInCategory.OST_PipeCurves,
    BuiltInCategory.OST_PipeFitting,
    BuiltInCategory.OST_PipeAccessory,
    BuiltInCategory.OST_FlexPipeCurves,
    BuiltInCategory.OST_PipingSystem,
]
ELEC_CATS = [
    BuiltInCategory.OST_CableTray,
    BuiltInCategory.OST_CableTrayFitting,
    BuiltInCategory.OST_Conduit,
    BuiltInCategory.OST_ConduitFitting,
]

# ── Section Definitions ───────────────────────────────────────────────────────
# Each section: key, display title, column-2 label, whether it uses the
# classification combo (True) or a free-text match box (False),
# the Revit categories to filter, the parameter to match on,
# whether to show the "no links" warning, and the initial default rows.
SECTIONS_CONFIG = [
    {
        "key":               "hvac",
        "title":             "HVAC",
        "col2_label":        "System Classification",
        "is_classification": True,
        "categories":        HVAC_CATS,
        "param_id":          MP_PARAM_ID,
        "show_warn":         True,
        "default_rows": [
            ("COORD_SUPPLY DUCTS",  "Supply Air",  Drawing.Color.FromArgb(0,   128, 255)),
            ("COORD_RETURN DUCTS",  "Return Air",  Drawing.Color.FromArgb(255, 128,  64)),
            ("COORD_EXHAUST DUCTS", "Exhaust Air", Drawing.Color.FromArgb(0,   128,   0)),
        ],
    },
    {
        "key":               "plumbing",
        "title":             "Plumbing",
        "col2_label":        "System Classification",
        "is_classification": True,
        "categories":        PIPE_CATS,
        "param_id":          MP_PARAM_ID,
        "show_warn":         False,
        "default_rows": [
            ("COORD_COLD WATER PIPES",     "Domestic Cold Water", Drawing.Color.FromArgb(0,     0, 255)),
            ("COORD_HOT WATER PIPES",      "Domestic Hot Water",  Drawing.Color.FromArgb(255, 115,  47)),
            ("COORD_SUPPLY CHILLED WATER", "Hydronic Supply",     Drawing.Color.FromArgb(128, 128, 255)),
            ("COORD_RETURN CHILLED WATER", "Hydronic Return",     Drawing.Color.FromArgb(255, 255, 128)),
            ("COORD_DRAINAGE",             "Sanitary",            Drawing.Color.FromArgb(64,    0,  64)),
        ],
    },
    {
        "key":               "fire",
        "title":             "Fire Protection",
        "col2_label":        "System Classification",
        "is_classification": True,
        "categories":        PIPE_CATS,
        "param_id":          MP_PARAM_ID,
        "show_warn":         False,
        "default_rows": [
            ("COORD_FIRE PIPES",  "Fire Protection Wet",   Drawing.Color.FromArgb(255,   0,   0)),
            ("COORD_NOVEC PIPES", "Fire Protection Other", Drawing.Color.FromArgb(128, 128,   0)),
        ],
    },
    {
        "key":               "electric",
        "title":             "Electrical  (Cable Trays & Conduits \u2013 match by Type Name)",
        "col2_label":        "Match Text  (Type Name contains...)",
        "is_classification": False,
        "categories":        ELEC_CATS,
        "param_id":          ELEC_PARAM_ID,
        "show_warn":         False,
        "default_rows": [
            ("COORD_ELECTRIC TRAYS", "_E_", Drawing.Color.FromArgb(255, 255,   0)),
            ("COORD_ICT TRAYS",      "_T_", Drawing.Color.FromArgb(128, 255, 255)),
        ],
    },
]


# ── Linked-File Scanner ───────────────────────────────────────────────────────
def get_linked_system_classifications():
    values = set()
    link_instances = FilteredElementCollector(doc).OfClass(RevitLinkInstance).ToElements()
    for link_inst in link_instances:
        link_doc = link_inst.GetLinkDocument()
        if link_doc is None:
            continue
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
                pass
    return sorted(values)


# ── Revit Filter Helpers ──────────────────────────────────────────────────────
def get_existing_filter(filter_name):
    for f in FilteredElementCollector(doc).OfClass(ParameterFilterElement).ToElements():
        if f.Name == filter_name:
            return f
    return None


def is_filter_applied_to_view(view, filter_id):
    return filter_id in view.GetFilters()


def _get_pattern_elements():
    all_fill = FilteredElementCollector(doc).OfClass(FillPatternElement).ToElements()
    solid_fp = next(p for p in all_fill if p.GetFillPattern().IsSolidFill)
    all_line = FilteredElementCollector(doc).OfClass(LinePatternElement).ToElements()
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


# ── WinForms Primitive Builders ───────────────────────────────────────────────
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


# ── Main Dialog ───────────────────────────────────────────────────────────────
def show_filter_dialog(linked_classifications, fallback_used):
    confirmed = [False]

    # Build runtime section state from config
    sections = []
    for cfg in SECTIONS_CONFIG:
        sections.append({
            "key":               cfg["key"],
            "title":             cfg["title"],
            "col2_label":        cfg["col2_label"],
            "is_classification": cfg["is_classification"],
            "categories":        cfg["categories"],
            "param_id":          cfg["param_id"],
            "show_warn":         cfg["show_warn"],
            "default_rows":      cfg["default_rows"],
            "rows":              [],   # list of row-dicts (name_tb, col2_widget, color_ref, row_panel)
            # UI handles – filled during build:
            "hdr_panel":         None,
            "warn_panel":        None,
            "col_hdr_panel":     None,
            "add_btn":           None,
        })

        # ── Form shell ────────────────────────────────────────────────────────────
        form = WinForms.Form()
        form.Text = "MEP Filters Configuration"
        form.BackColor = DARK_BG
        form.ForeColor = TEXT_FG
        form.Width = FORM_W

        # --- CHANGED: Make the form resizable ---
        form.FormBorderStyle = WinForms.FormBorderStyle.Sizable
        form.MaximizeBox = True
        form.MinimumSize = Drawing.Size(FORM_W, 300)  # Prevents squishing the UI
        # ----------------------------------------

        form.StartPosition = WinForms.FormStartPosition.CenterScreen
        form.MinimizeBox = False
        form.Font = FONT_NORM
        form.AutoScroll = True

    # Title
    form.Controls.Add(_lbl(
        "  MEP FILTER CONFIGURATION",
        0, 10, FORM_W, 36,
        font=FONT_TITLE, fg=ACCENT_FG,
        bg=Drawing.Color.FromArgb(30, 30, 46)
    ))

    # Footer controls (positioned by relayout)
    sep = WinForms.Panel()
    sep.Size      = Drawing.Size(TOTAL_W, 1)
    sep.BackColor = BORDER_CLR
    form.Controls.Add(sep)

    btn_cancel = WinForms.Button()
    btn_cancel.Text      = "Cancel"
    btn_cancel.Size      = Drawing.Size(100, 32)
    btn_cancel.BackColor = BTN_BG
    btn_cancel.ForeColor = TEXT_FG
    btn_cancel.FlatStyle = WinForms.FlatStyle.Flat
    btn_cancel.FlatAppearance.BorderColor = BORDER_CLR
    btn_cancel.Font      = FONT_NORM
    btn_cancel.Cursor    = WinForms.Cursors.Hand
    form.Controls.Add(btn_cancel)

    btn_apply = WinForms.Button()
    btn_apply.Text      = "Apply Filters"
    btn_apply.Size      = Drawing.Size(128, 32)
    btn_apply.BackColor = BTN_OK_BG
    btn_apply.ForeColor = Drawing.Color.FromArgb(30, 30, 46)
    btn_apply.FlatStyle = WinForms.FlatStyle.Flat
    btn_apply.FlatAppearance.BorderColor = Drawing.Color.FromArgb(255, 185, 20)
    btn_apply.Font      = FONT_BOLD
    btn_apply.Cursor    = WinForms.Cursors.Hand
    form.Controls.Add(btn_apply)

    # ── Relayout ──────────────────────────────────────────────────────────────
    def relayout():
        """Reposition every section panel + footer based on current row counts."""
        # 1. Suspend layout to prevent flickering
        form.SuspendLayout()

        # 2. IMPORTANT: Save and reset AutoScrollPosition to prevent WinForms
        # from compounding the scroll offset onto our absolute Y coordinates.
        saved_scroll = form.AutoScrollPosition
        form.AutoScrollPosition = Drawing.Point(0, 0)

        y = TITLE_H + 10
        for sec in sections:
            sec["hdr_panel"].Location = Drawing.Point(GUTTER, y)
            y += HDR_H

            if sec["warn_panel"] is not None:
                sec["warn_panel"].Location = Drawing.Point(GUTTER, y)
                y += 20

            sec["col_hdr_panel"].Location = Drawing.Point(GUTTER, y)
            y += COL_HDR_H

            for rd in sec["rows"]:
                rd["row_panel"].Location = Drawing.Point(GUTTER, y)
                y += ROW_H

            sec["add_btn"].Location = Drawing.Point(GUTTER + 4, y + 4)
            y += ADD_BTN_H + SECTION_GAP

        y += 6
        sep.Location = Drawing.Point(GUTTER, y)
        y += 10
        btn_cancel.Location = Drawing.Point(FORM_W - 244, y)
        btn_apply.Location = Drawing.Point(FORM_W - 136, y)
        y += 46

        desired_h = y + 42  # +42 for OS window chrome

        # 1. Always update the scrollable area bounds
        form.AutoScrollMinSize = Drawing.Size(0, desired_h - 42)

        # 2. CHANGED: Only force the window height BEFORE it is shown on screen.
        # This prevents the window from "snapping" back to a smaller size
        # if you manually resize or maximize it, then click "+" or "x".
        if not form.Visible:
            form.Height = min(desired_h, MAX_FORM_H)

        # 3. Restore the scroll position.
        form.AutoScrollPosition = Drawing.Point(abs(saved_scroll.X), abs(saved_scroll.Y))

        # 4. Resume layout
        form.ResumeLayout()

    # ── Row Builder ───────────────────────────────────────────────────────────
    def _build_row(sec, name_default, col2_default, color_default):
        """
        Creates one row panel + widgets and returns a row-dict.
        Does NOT append to sec["rows"] or add to form.Controls – caller does that.
        """
        color_ref = [color_default]
        row_idx   = len(sec["rows"])   # index this row will occupy after append
        row_bg    = ROW_A if row_idx % 2 == 0 else ROW_B

        # ── widgets ──
        name_tb = _input_tb(name_default)
        name_tb.Location = Drawing.Point(4, (ROW_H - 22) // 2)
        name_tb.Width    = COL1_W - 8

        if sec["is_classification"]:
            col2_widget = _classification_combo(linked_classifications, preselect=col2_default)
        else:
            col2_widget = _input_tb(col2_default)
        col2_widget.Location = Drawing.Point(COL1_W, (ROW_H - col2_widget.Height) // 2)
        col2_widget.Width    = COL2_W - 8

        swatch_btn = WinForms.Button()
        swatch_btn.Size      = Drawing.Size(SWATCH_W - 4, ROW_H - 10)
        swatch_btn.BackColor = color_default
        swatch_btn.FlatStyle = WinForms.FlatStyle.Flat
        swatch_btn.FlatAppearance.BorderColor = BORDER_CLR
        swatch_btn.FlatAppearance.BorderSize  = 1
        swatch_btn.Text      = ""
        swatch_btn.Cursor    = WinForms.Cursors.Hand
        swatch_x             = COL1_W + COL2_W + 2
        swatch_btn.Location  = Drawing.Point(swatch_x, (ROW_H - swatch_btn.Height) // 2)

        del_btn = WinForms.Button()
        del_btn.Text      = u"\u00d7"   # ×
        del_btn.Size      = Drawing.Size(DEL_W - 2, ROW_H - 10)
        del_btn.Location  = Drawing.Point(swatch_x + SWATCH_W, (ROW_H - del_btn.Height) // 2)
        del_btn.BackColor = Drawing.Color.FromArgb(58,  30,  40)   # dark red-tinted surface
        del_btn.ForeColor = Drawing.Color.FromArgb(243, 139, 168)  # #F38BA8 Catppuccin red
        del_btn.FlatStyle = WinForms.FlatStyle.Flat
        del_btn.FlatAppearance.BorderColor = Drawing.Color.FromArgb(100, 60, 75)
        del_btn.Font      = FONT_BOLD
        del_btn.Cursor    = WinForms.Cursors.Hand

        row_panel = WinForms.Panel()
        row_panel.Size      = Drawing.Size(TOTAL_W, ROW_H)
        row_panel.BackColor = row_bg
        for ctrl in [name_tb, col2_widget, swatch_btn, del_btn]:
            row_panel.Controls.Add(ctrl)

        row_dict = {
            "name_tb":    name_tb,
            "col2_widget": col2_widget,
            "color_ref":  color_ref,
            "row_panel":  row_panel,
        }

        # Color picker
        def on_swatch(s, e, cr=color_ref, btn=swatch_btn):
            dlg          = WinForms.ColorDialog()
            dlg.Color    = cr[0]
            dlg.FullOpen = True
            if dlg.ShowDialog() == WinForms.DialogResult.OK:
                cr[0]         = dlg.Color
                btn.BackColor = dlg.Color
        swatch_btn.Click += on_swatch

        # Delete row
        def on_delete(s, e, _sec=sec, _rd=row_dict):
            _sec["rows"].remove(_rd)
            form.Controls.Remove(_rd["row_panel"])
            # Re-stripe remaining rows
            for idx, rd in enumerate(_sec["rows"]):
                rd["row_panel"].BackColor = ROW_A if idx % 2 == 0 else ROW_B
            relayout()
        del_btn.Click += on_delete

        return row_dict

    def _add_blank_row(sec):
        """Called by the '+' button – adds an empty row with neutral grey colour."""
        rd = _build_row(sec,
                        name_default="COORD_NEW FILTER",
                        col2_default="",
                        color_default=Drawing.Color.FromArgb(110, 110, 110))
        sec["rows"].append(rd)
        form.Controls.Add(rd["row_panel"])
        relayout()

    # ── Build each section ────────────────────────────────────────────────────
    for sec in sections:
        # Section header
        hdr = WinForms.Panel()
        hdr.Size      = Drawing.Size(TOTAL_W, HDR_H)
        hdr.BackColor = SECTION_BG
        hdr.Controls.Add(_lbl(
            "  " + sec["title"], 0, 0, TOTAL_W, HDR_H,
            font=FONT_BOLD,
            fg=Drawing.Color.FromArgb(180, 190, 254),   # #B4BEFE lavender
            bg=Drawing.Color.Transparent
        ))
        form.Controls.Add(hdr)
        sec["hdr_panel"] = hdr

        # Optional fallback warning (classification sections only, shown once on HVAC)
        if fallback_used and sec["show_warn"]:
            warn = WinForms.Panel()
            warn.Size      = Drawing.Size(TOTAL_W, 20)
            warn.BackColor = WARN_BG
            warn.Controls.Add(_lbl(
                u"  \u26a0  No loaded Revit links found \u2013 showing default classification values.",
                0, 0, TOTAL_W, 20,
                font=FONT_WARN, fg=WARN_FG, bg=Drawing.Color.Transparent
            ))
            form.Controls.Add(warn)
            sec["warn_panel"] = warn
        else:
            sec["warn_panel"] = None

        # Column headers
        col_hdr = WinForms.Panel()
        col_hdr.Size      = Drawing.Size(TOTAL_W, COL_HDR_H)
        col_hdr.BackColor = HEADER_BG
        col_hdr.Controls.Add(_lbl("Filter Name",     4,       0, COL1_W, COL_HDR_H, fg=DIM_FG, font=FONT_BOLD))
        col_hdr.Controls.Add(_lbl(sec["col2_label"],  COL1_W, 0, COL2_W, COL_HDR_H, fg=DIM_FG, font=FONT_BOLD))
        col_hdr.Controls.Add(_lbl("Color",
            COL1_W + COL2_W, 0, COL3_W, COL_HDR_H,
            fg=DIM_FG, font=FONT_BOLD,
            align=Drawing.ContentAlignment.MiddleCenter
        ))
        form.Controls.Add(col_hdr)
        sec["col_hdr_panel"] = col_hdr

        # Default rows
        for (def_name, def_col2, def_color) in sec["default_rows"]:
            rd = _build_row(sec, def_name, def_col2, def_color)
            sec["rows"].append(rd)
            form.Controls.Add(rd["row_panel"])

        # "+" button
        add_btn = WinForms.Button()
        add_btn.Text      = "+"
        add_btn.Size      = Drawing.Size(26, 22)
        add_btn.BackColor = Drawing.Color.FromArgb(69,  71,  90)   # #45475A muted
        add_btn.ForeColor = Drawing.Color.FromArgb(240, 165,   0)  # #F0A500 accent
        add_btn.FlatStyle = WinForms.FlatStyle.Flat
        add_btn.FlatAppearance.BorderColor = Drawing.Color.FromArgb(240, 165, 0)
        add_btn.Font      = FONT_BOLD
        add_btn.Cursor    = WinForms.Cursors.Hand

        def on_add(s, e, _sec=sec):
            _add_blank_row(_sec)
        add_btn.Click += on_add

        form.Controls.Add(add_btn)
        sec["add_btn"] = add_btn

    # ── Footer handlers ───────────────────────────────────────────────────────
    def on_cancel(s, e):
        form.Close()

    def on_apply(s, e):
        for sec in sections:
            sec_label = sec["title"].split("(")[0].strip()
            for i, rd in enumerate(sec["rows"]):
                if not rd["name_tb"].Text.strip():
                    WinForms.MessageBox.Show(
                        "Filter name in '{}' row {} cannot be empty.".format(sec_label, i + 1),
                        "Validation",
                        WinForms.MessageBoxButtons.OK,
                        WinForms.MessageBoxIcon.Warning)
                    return
                if sec["is_classification"]:
                    if rd["col2_widget"].SelectedIndex < 0:
                        WinForms.MessageBox.Show(
                            "Please select a System Classification for '{}' row {}.".format(sec_label, i + 1),
                            "Validation",
                            WinForms.MessageBoxButtons.OK,
                            WinForms.MessageBoxIcon.Warning)
                        return
                else:
                    if not rd["col2_widget"].Text.strip():
                        WinForms.MessageBox.Show(
                            "Match text for '{}' row {} cannot be empty.".format(sec_label, i + 1),
                            "Validation",
                            WinForms.MessageBoxButtons.OK,
                            WinForms.MessageBoxIcon.Warning)
                        return
        confirmed[0] = True
        form.Close()

    btn_cancel.Click += on_cancel
    btn_apply.Click  += on_apply

    # Initial layout + show
    relayout()
    form.ShowDialog()

    if not confirmed[0]:
        return None

    # Collect results
    result = []
    for sec in sections:
        filters = []
        for rd in sec["rows"]:
            if sec["is_classification"]:
                value = str(rd["col2_widget"].SelectedItem)
            else:
                value = rd["col2_widget"].Text.strip()
            filters.append({
                "name":  rd["name_tb"].Text.strip(),
                "value": value,
                "color": rd["color_ref"][0],
            })
        result.append({
            "categories": sec["categories"],
            "param_id":   sec["param_id"],
            "filters":    filters,
        })
    return result


# ── Entry Point ───────────────────────────────────────────────────────────────

# 1. Scan linked files for System Classification values
linked_classifications = get_linked_system_classifications()
fallback_used          = len(linked_classifications) == 0

if fallback_used:
    # Build a deduplicated, sorted list from all classification default rows
    defaults = set()
    for cfg in SECTIONS_CONFIG:
        if cfg["is_classification"]:
            for (_, col2, _) in cfg["default_rows"]:
                defaults.add(col2)
    linked_classifications = sorted(defaults)

# 2. Show dialog
result_sections = show_filter_dialog(linked_classifications, fallback_used)

if result_sections is None:
    script.exit()

# 3. Create / apply all filters in one transaction
with Transaction(doc, __title__) as t:
    t.Start()
    for sec in result_sections:
        for f in sec["filters"]:
            create_view_filter(
                f["name"],
                sec["categories"],
                sec["param_id"],
                f["value"],
                f["color"],
            )
    t.Commit()
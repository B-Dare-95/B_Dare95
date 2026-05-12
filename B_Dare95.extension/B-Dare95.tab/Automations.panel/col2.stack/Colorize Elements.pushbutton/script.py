# -*- coding: utf-8 -*-
"""
Universal Element Colorizer
════════════════════════════
Two colorize modes selectable via the MODE toggle at the top:

  • By View Filter     — creates ParameterFilterElement objects (WPC_ prefix)
                         stored in the document and applied to the active view.
  • By Graphic Override — applies per-element solid surface/cut fill overrides
                         directly on each instance in the active view.

Workflow
────────
1. Pick a MODE at the top (Filter or Override).
2. Pick a category from the left list  (use the search box to narrow).
3. Toggle Instance / Type to control which parameters are shown.
4. Pick a parameter from the dropdown.
5. All unique values appear on the right with auto-assigned palette colours.
   • Click a colour swatch to open the colour picker.
   • Click the ON / OFF pill to exclude that value from being colourised.
6. Press Apply.

Reset button
   Filter mode  → removes all WPC_ filters from the active view.
   Override mode → clears overrides on every loaded element.

Config-mode (right-click the button) also removes WPC_ filters.
"""

import clr
clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Drawing')

from System.Windows.Forms import (
    Form, SplitContainer, FixedPanel,
    FlowLayoutPanel, FlowDirection,
    Panel, Label, RadioButton,
    ComboBox, ComboBoxStyle, TextBox, ListBox, SelectionMode,
    Button, FlatStyle, ColorDialog,
    DataGridView, DataGridViewTextBoxColumn,
    DataGridViewAutoSizeColumnsMode, DataGridViewSelectionMode,
    DataGridViewColumnSortMode,
    DockStyle, Padding, FormStartPosition, FormBorderStyle,
    BorderStyle as WFBorderStyle,
    MessageBox, MessageBoxButtons, MessageBoxIcon, DialogResult,
)
from System.Drawing import (
    Color as DC, Size, Font, FontStyle,
    SolidBrush, Rectangle, RectangleF, StringFormat, StringAlignment,
)
from System.Collections.Generic import List
from Autodesk.Revit.DB import (
    FilteredElementCollector, FillPatternElement,
    OverrideGraphicSettings, Transaction,
    StorageType, ElementId, CategoryType,
    Color as RC,
    ParameterFilterElement, ParameterFilterRuleFactory,
    ElementParameterFilter, FilterRule,
)
from pyrevit import EXEC_PARAMS

# ── Revit context ─────────────────────────────────────────────────────────────

uidoc       = __revit__.ActiveUIDocument
doc         = uidoc.Document
active_view = doc.ActiveView

_pats         = FilteredElementCollector(doc).OfClass(FillPatternElement).ToElements()
SOLID_PATTERN = next((p for p in _pats if p.GetFillPattern().IsSolidFill), None)

# ── Catppuccin Mocha palette ──────────────────────────────────────────────────

BG      = DC.FromArgb(0x1E, 0x1E, 0x2E)
CARD    = DC.FromArgb(0x2A, 0x2A, 0x3C)
SURFACE = DC.FromArgb(0x31, 0x32, 0x44)
MUTED   = DC.FromArgb(0x45, 0x47, 0x5A)
TEXT    = DC.FromArgb(0xCD, 0xD6, 0xF4)
SUBTEXT = DC.FromArgb(0xA6, 0xAD, 0xC8)
ACCENT  = DC.FromArgb(0xF0, 0xA5, 0x00)
GREEN   = DC.FromArgb(166, 227, 161)   # Catppuccin green  – ON  state
DARK    = DC.FromArgb(0x1E, 0x1E, 0x2E)  # base – ON label text

PALETTE = [
    DC.FromArgb(243, 139, 168),
    DC.FromArgb(250, 179, 135),
    DC.FromArgb(249, 226, 175),
    DC.FromArgb(166, 227, 161),
    DC.FromArgb(137, 180, 250),
    DC.FromArgb(203, 166, 247),
    DC.FromArgb(148, 226, 213),
    DC.FromArgb(116, 199, 236),
    DC.FromArgb(245, 194, 231),
    DC.FromArgb(180, 190, 254),
]

WPC_PREFIX = "WPC_"

# ── Helpers ───────────────────────────────────────────────────────────────────

def _eid(eid):
    try:    return str(eid.Value)
    except: return str(eid.IntegerValue)


def pval(param):
    """Return a display string for a parameter value."""
    if param is None or not param.HasValue:
        return "<No Value>"
    st = param.StorageType
    if st == StorageType.String:
        v = param.AsString()
        return v if v else "<Empty>"
    if st == StorageType.Integer:
        return str(param.AsInteger())
    if st == StorageType.Double:
        return str(round(param.AsDouble(), 4))
    if st == StorageType.ElementId:
        eid = param.AsElementId()
        if eid == ElementId.InvalidElementId:
            return "<None>"
        el = doc.GetElement(eid)
        try:   return el.Name if el else _eid(eid)
        except: return _eid(eid)
    return "<Unknown>"


def all_model_cats():
    cats = []
    for c in doc.Settings.Categories:
        try:
            if c.CategoryType == CategoryType.Model:
                cats.append(c)
        except:
            pass
    return sorted(cats, key=lambda c: c.Name)


def get_instances(cat_id):
    try:
        return list(
            FilteredElementCollector(doc, active_view.Id)
            .OfCategoryId(cat_id)
            .WhereElementIsNotElementType()
            .ToElements()
        )
    except:
        return []


def get_unique_types(instances):
    seen, types = set(), []
    for inst in instances:
        try:
            tid = inst.GetTypeId()
            k   = _eid(tid)
            if k not in seen and tid != ElementId.InvalidElementId:
                seen.add(k)
                t = doc.GetElement(tid)
                if t:
                    types.append(t)
        except:
            pass
    return types


def collect_params_with_meta(elems):
    """
    Returns:
      { param_name: {
          'values'  : [sorted display strings],
          'storage' : StorageType,
          'pid'     : ElementId,   ← parameter definition ID
          'raw'     : {display_str: raw_value}
      }}
    """
    meta = {}
    for el in elems:
        for p in el.Parameters:
            try:
                if p.Definition is None:
                    continue
                n  = p.Definition.Name
                st = p.StorageType
                if n not in meta:
                    meta[n] = {'values': set(), 'storage': st, 'pid': p.Id, 'raw': {}}
                display = pval(p)
                if display not in meta[n]['raw']:
                    if not p.HasValue:
                        raw = None
                    elif st == StorageType.String:
                        raw = p.AsString() or ""
                    elif st == StorageType.Integer:
                        raw = p.AsInteger()
                    elif st == StorageType.Double:
                        raw = p.AsDouble()
                    elif st == StorageType.ElementId:
                        raw = p.AsElementId()
                    else:
                        raw = None
                    meta[n]['raw'][display] = raw
                meta[n]['values'].add(display)
            except:
                pass
    return {k: dict(v, values=sorted(v['values'])) for k, v in sorted(meta.items())}


def make_filter_name(cat_name, param_name, val_str):
    def _safe(s, maxlen):
        import re
        return re.sub(r'[^\w\-]', '_', s)[:maxlen]
    return "{0}{1}_{2}_{3}".format(
        WPC_PREFIX, _safe(cat_name, 24), _safe(param_name, 24), _safe(val_str, 40))


def find_filter_by_name(name):
    for el in FilteredElementCollector(doc).OfClass(ParameterFilterElement).ToElements():
        try:
            if el.Name == name:
                return el
        except:
            pass
    return None


def make_rule(param_id, storage_type, display_str, raw_value):
    """Build a ParameterFilterRule for a single value. Returns None on failure."""
    try:
        if display_str == "<No Value>" or raw_value is None:
            try:
                return ParameterFilterRuleFactory.CreateHasNoValueRule(param_id)
            except:
                return None
        if storage_type == StorageType.String:
            val = "" if display_str == "<Empty>" else str(raw_value)
            return ParameterFilterRuleFactory.CreateEqualsRule(param_id, val, False)
        if storage_type == StorageType.Integer:
            return ParameterFilterRuleFactory.CreateEqualsRule(param_id, int(raw_value))
        if storage_type == StorageType.Double:
            return ParameterFilterRuleFactory.CreateEqualsRule(
                param_id, float(raw_value), 1e-9)
        if storage_type == StorageType.ElementId:
            if isinstance(raw_value, ElementId):
                return ParameterFilterRuleFactory.CreateEqualsRule(param_id, raw_value)
    except:
        pass
    return None


# ── Form ──────────────────────────────────────────────────────────────────────

class ColorizerForm(Form):

    def __init__(self):
        Form.__init__(self)
        self.Text            = "Universal Element Colorizer"
        self.Size            = Size(1020, 720)
        self.MinimumSize     = Size(800, 560)
        self.StartPosition   = FormStartPosition.CenterScreen
        self.FormBorderStyle = FormBorderStyle.Sizable
        self.BackColor       = BG

        # ── State ─────────────────────────────────────────────────────────────
        self._all_cats  = all_model_cats()
        self._instances = []
        self._pmeta     = {}
        self._colors    = {}     # {val_str: DC}
        self._enabled   = {}     # {val_str: bool}   ← ON / OFF per value
        self._pal_idx   = 0
        self._busy      = False

        self._build_ui()
        self._fill_cat_list("")

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        self.SuspendLayout()

        # ── Bottom action bar ─────────────────────────────────────────────────
        bar               = FlowLayoutPanel()
        bar.Dock          = DockStyle.Bottom
        bar.Height        = 54
        bar.FlowDirection = FlowDirection.RightToLeft
        bar.WrapContents  = False
        bar.Padding       = Padding(8, 10, 8, 0)
        bar.BackColor     = CARD

        def mk_btn(text, fn, accent=False, w=120):
            b = Button()
            b.Text      = text
            b.Width     = w
            b.Height    = 32
            b.Margin    = Padding(6, 0, 0, 0)
            b.FlatStyle = FlatStyle.Flat
            b.BackColor = ACCENT if accent else SURFACE
            b.ForeColor = BG if accent else TEXT
            b.Font      = Font(self.Font.FontFamily, 9, FontStyle.Regular)
            b.FlatAppearance.BorderColor = MUTED
            b.FlatAppearance.BorderSize  = 1
            b.Click += fn
            return b

        bar.Controls.Add(mk_btn("Cancel",         self._cancel, w=100))
        self._btn_reset = mk_btn("Remove Filters", self._reset, w=140)
        bar.Controls.Add(self._btn_reset)
        bar.Controls.Add(mk_btn("Apply",           self._apply, accent=True, w=110))

        # ── MODE toggle strip (top) ───────────────────────────────────────────
        mode_bar           = Panel()
        mode_bar.Dock      = DockStyle.Top
        mode_bar.Height    = 46
        mode_bar.BackColor = CARD

        # Vertical separator accent line on the left
        accent_line           = Panel()
        accent_line.Left      = 0
        accent_line.Top       = 0
        accent_line.Width     = 4
        accent_line.Height    = 46
        accent_line.BackColor = ACCENT

        lbl_mode           = Label()
        lbl_mode.Text      = "MODE"
        lbl_mode.ForeColor = ACCENT
        lbl_mode.BackColor = CARD
        lbl_mode.Font      = Font(self.Font.FontFamily, 8, FontStyle.Bold)
        lbl_mode.Left      = 18
        lbl_mode.Top       = 15
        lbl_mode.AutoSize  = True

        self.rb_filter           = RadioButton()
        self.rb_filter.Text      = "By View Filter"
        self.rb_filter.ForeColor = TEXT
        self.rb_filter.BackColor = CARD
        self.rb_filter.Checked   = True
        self.rb_filter.Left      = 78
        self.rb_filter.Top       = 12
        self.rb_filter.Width     = 130
        self.rb_filter.Height    = 22
        self.rb_filter.Font      = Font(self.Font.FontFamily, 9, FontStyle.Regular)
        self.rb_filter.CheckedChanged += self._on_mode_change

        self.rb_override           = RadioButton()
        self.rb_override.Text      = "By Graphic Override"
        self.rb_override.ForeColor = TEXT
        self.rb_override.BackColor = CARD
        self.rb_override.Left      = 218
        self.rb_override.Top       = 12
        self.rb_override.Width     = 180
        self.rb_override.Height    = 22
        self.rb_override.Font      = Font(self.Font.FontFamily, 9, FontStyle.Regular)
        self.rb_override.CheckedChanged += self._on_mode_change

        mode_info           = Label()
        mode_info.Text      = "Filter: creates WPC_ view filters   |   Override: per-element surface colour"
        mode_info.ForeColor = SUBTEXT
        mode_info.BackColor = CARD
        mode_info.Font      = Font(self.Font.FontFamily, 7.5, FontStyle.Italic)
        mode_info.Left      = 410
        mode_info.Top       = 15
        mode_info.AutoSize  = True

        mode_bar.Controls.Add(accent_line)
        mode_bar.Controls.Add(lbl_mode)
        mode_bar.Controls.Add(self.rb_filter)
        mode_bar.Controls.Add(self.rb_override)
        mode_bar.Controls.Add(mode_info)

        # ── SplitContainer ────────────────────────────────────────────────────
        sc           = SplitContainer()
        sc.Dock      = DockStyle.Fill
        sc.BackColor = MUTED
        self._sc     = sc

        # ═══════════════════════════════════════════════════
        # LEFT PANEL  — Category + Parameter
        # ═══════════════════════════════════════════════════
        lp           = Panel()
        lp.Dock      = DockStyle.Fill
        lp.Padding   = Padding(20, 20, 10, 10)
        lp.BackColor = BG

        # ── Parameter section (pinned at bottom) ──────────────────────────────
        pp           = Panel()
        pp.Dock      = DockStyle.Bottom
        pp.Height    = 120
        pp.BackColor = BG
        pp.Padding   = Padding(0, 4, 0, 2)

        lbl_param           = Label()
        lbl_param.Text      = "PARAMETER"
        lbl_param.ForeColor = ACCENT
        lbl_param.BackColor = BG
        lbl_param.Dock      = DockStyle.Top
        lbl_param.Height    = 20
        lbl_param.Font      = Font(self.Font.FontFamily, 8, FontStyle.Bold)

        rp           = Panel()
        rp.Dock      = DockStyle.Top
        rp.Height    = 32
        rp.BackColor = BG

        self.rb_inst           = RadioButton()
        self.rb_inst.Text      = "Instance"
        self.rb_inst.ForeColor = TEXT
        self.rb_inst.BackColor = BG
        self.rb_inst.Left      = 0
        self.rb_inst.Top       = 3
        self.rb_inst.Width     = 90
        self.rb_inst.Height    = 22
        self.rb_inst.Checked   = True
        self.rb_inst.CheckedChanged += self._on_toggle

        self.rb_type           = RadioButton()
        self.rb_type.Text      = "Type"
        self.rb_type.ForeColor = TEXT
        self.rb_type.BackColor = BG
        self.rb_type.Left      = 94
        self.rb_type.Top       = 3
        self.rb_type.Width     = 70
        self.rb_type.Height    = 22
        self.rb_type.CheckedChanged += self._on_toggle

        rp.Controls.Add(self.rb_inst)
        rp.Controls.Add(self.rb_type)

        self.cb_param               = ComboBox()
        self.cb_param.Dock          = DockStyle.Top
        self.cb_param.Height        = 30
        self.cb_param.DropDownStyle = ComboBoxStyle.DropDownList
        self.cb_param.BackColor     = SURFACE
        self.cb_param.ForeColor     = TEXT
        self.cb_param.SelectedIndexChanged += self._on_param

        pp.Controls.Add(self.cb_param)
        pp.Controls.Add(rp)
        pp.Controls.Add(lbl_param)

        # ── Category section (fills remaining) ────────────────────────────────
        cp           = Panel()
        cp.Dock      = DockStyle.Fill
        cp.BackColor = BG
        cp.Padding   = Padding(0, 0, 0, 6)

        lbl_cat           = Label()
        lbl_cat.Text      = "CATEGORY"
        lbl_cat.ForeColor = ACCENT
        lbl_cat.BackColor = BG
        lbl_cat.Dock      = DockStyle.Top
        lbl_cat.Height    = 20
        lbl_cat.Font      = Font(self.Font.FontFamily, 8, FontStyle.Bold)

        self.tb_search             = TextBox()
        self.tb_search.Dock        = DockStyle.Top
        self.tb_search.Height      = 26
        self.tb_search.BackColor   = SURFACE
        self.tb_search.ForeColor   = TEXT
        self.tb_search.BorderStyle = WFBorderStyle.FixedSingle
        self.tb_search.Font        = self.Font
        self.tb_search.TextChanged += self._on_cat_search

        self.lb               = ListBox()
        self.lb.Dock          = DockStyle.Fill
        self.lb.BackColor     = SURFACE
        self.lb.ForeColor     = TEXT
        self.lb.BorderStyle   = WFBorderStyle.FixedSingle
        self.lb.SelectionMode = SelectionMode.One
        self.lb.SelectedIndexChanged += self._on_cat

        cp.Controls.Add(self.lb)
        cp.Controls.Add(self.tb_search)
        cp.Controls.Add(lbl_cat)

        lp.Controls.Add(cp)
        lp.Controls.Add(pp)

        sc.Panel1.BackColor = BG
        sc.Panel1.Controls.Add(lp)

        # ═══════════════════════════════════════════
        # RIGHT PANEL  — Colour assignments DGV
        # ═══════════════════════════════════════════
        rr           = Panel()
        rr.Dock      = DockStyle.Fill
        rr.Padding   = Padding(6, 10, 10, 10)
        rr.BackColor = BG

        lbl_head           = Label()
        lbl_head.Text      = "COLOUR ASSIGNMENTS"
        lbl_head.ForeColor = ACCENT
        lbl_head.BackColor = BG
        lbl_head.Dock      = DockStyle.Top
        lbl_head.Height    = 22
        lbl_head.Font      = Font(self.Font.FontFamily, 8, FontStyle.Bold)

        self.lbl_hint           = Label()
        self.lbl_hint.Text      = "\u2190  Select a category and parameter to populate."
        self.lbl_hint.ForeColor = SUBTEXT
        self.lbl_hint.BackColor = BG
        self.lbl_hint.Dock      = DockStyle.Top
        self.lbl_hint.Height    = 22
        self.lbl_hint.Visible   = True

        # ── DataGridView ──────────────────────────────────────────────────────
        self.dgv = DataGridView()
        self.dgv.Dock                  = DockStyle.Fill
        self.dgv.RowHeadersVisible     = False
        self.dgv.AllowUserToAddRows    = False
        self.dgv.AllowUserToDeleteRows = False
        self.dgv.AllowUserToResizeRows = False
        self.dgv.ReadOnly              = True
        self.dgv.MultiSelect           = False
        self.dgv.SelectionMode         = DataGridViewSelectionMode.FullRowSelect
        self.dgv.AutoSizeColumnsMode   = DataGridViewAutoSizeColumnsMode.Fill
        self.dgv.ColumnHeadersHeightSizeMode = \
            self.dgv.ColumnHeadersHeightSizeMode.DisableResizing
        self.dgv.ColumnHeadersHeight   = 30
        self.dgv.RowTemplate.Height    = 38
        self.dgv.BackgroundColor       = BG
        self.dgv.GridColor             = MUTED
        self.dgv.BorderStyle           = self.dgv.BorderStyle.FixedSingle
        self.dgv.CellBorderStyle       = self.dgv.CellBorderStyle.SingleHorizontal
        self.dgv.EnableHeadersVisualStyles = False

        self.dgv.DefaultCellStyle.BackColor          = SURFACE
        self.dgv.DefaultCellStyle.ForeColor          = TEXT
        self.dgv.DefaultCellStyle.SelectionBackColor = MUTED
        self.dgv.DefaultCellStyle.SelectionForeColor = TEXT
        self.dgv.ColumnHeadersDefaultCellStyle.BackColor = CARD
        self.dgv.ColumnHeadersDefaultCellStyle.ForeColor = ACCENT
        self.dgv.ColumnHeadersDefaultCellStyle.SelectionBackColor = CARD
        self.dgv.AlternatingRowsDefaultCellStyle.BackColor = CARD

        # Col 0 — Value
        c0            = DataGridViewTextBoxColumn()
        c0.HeaderText = "Value"
        c0.FillWeight = 60
        c0.SortMode   = DataGridViewColumnSortMode.NotSortable
        c0.ReadOnly   = True

        # Col 1 — Colour swatch
        c1            = DataGridViewTextBoxColumn()
        c1.HeaderText = "Colour  (click swatch)"
        c1.FillWeight = 22
        c1.SortMode   = DataGridViewColumnSortMode.NotSortable
        c1.ReadOnly   = True

        # Col 2 — On / Off toggle
        c2            = DataGridViewTextBoxColumn()
        c2.HeaderText = "Active"
        c2.FillWeight = 18
        c2.SortMode   = DataGridViewColumnSortMode.NotSortable
        c2.ReadOnly   = True

        self.dgv.Columns.Add(c0)
        self.dgv.Columns.Add(c1)
        self.dgv.Columns.Add(c2)
        self.dgv.CellClick    += self._on_cell_click
        self.dgv.CellPainting += self._on_cell_paint

        rr.Controls.Add(self.dgv)
        rr.Controls.Add(self.lbl_hint)
        rr.Controls.Add(lbl_head)
        self.lbl_hint.BringToFront()

        sc.Panel2.BackColor = BG
        sc.Panel2.Controls.Add(rr)

        # ── Assemble form ─────────────────────────────────────────────────────
        self.Controls.Add(bar)       # DockStyle.Bottom  → bottom strip
        self.Controls.Add(mode_bar)  # DockStyle.Top     → top strip
        self.Controls.Add(sc)        # DockStyle.Fill    → middle

        self.Load += self._on_load
        self.ResumeLayout(True)

    def _on_load(self, s, e):
        self._sc.FixedPanel    = FixedPanel.Panel1
        self._sc.Panel1MinSize = 260
        self._sc.Panel2MinSize = 320
        w = self._sc.Width
        self._sc.SplitterDistance = max(260, min(380, w - 320 - self._sc.SplitterWidth))

    # ── Mode change ───────────────────────────────────────────────────────────

    def _on_mode_change(self, s, e):
        if self._busy or not s.Checked:
            return
        if self.rb_filter.Checked:
            self._btn_reset.Text = "Remove Filters"
        else:
            self._btn_reset.Text = "Reset Overrides"

    # ── Data helpers ──────────────────────────────────────────────────────────

    def _fill_cat_list(self, search):
        self._busy = True
        self.lb.Items.Clear()
        s = search.strip().lower()
        for c in self._all_cats:
            if not s or s in c.Name.lower():
                self.lb.Items.Add(c.Name)
        self._busy = False

    def _selected_cat(self):
        if self.lb.SelectedIndex < 0:
            return None
        name = str(self.lb.SelectedItem)
        for c in self._all_cats:
            if c.Name == name:
                return c
        return None

    def _load_params(self):
        cat = self._selected_cat()
        if cat is None:
            return
        self._instances = get_instances(cat.Id)
        elems = (get_unique_types(self._instances)
                 if self.rb_type.Checked
                 else self._instances)
        self._pmeta = collect_params_with_meta(elems)

        self._busy = True
        self.cb_param.Items.Clear()
        for name in sorted(self._pmeta.keys()):
            self.cb_param.Items.Add(name)
        self._busy = False

        self._clear_dgv()
        if self.cb_param.Items.Count > 0:
            self.cb_param.SelectedIndex = 0

    def _clear_dgv(self):
        self.dgv.Rows.Clear()
        self._colors  = {}
        self._enabled = {}
        self._pal_idx = 0
        self.lbl_hint.Text    = "\u2190  Select a category and parameter to populate."
        self.lbl_hint.Visible = True

    def _fill_dgv(self):
        self.dgv.Rows.Clear()
        self._colors  = {}
        self._enabled = {}
        self._pal_idx = 0

        if self.cb_param.SelectedItem is None:
            self.lbl_hint.Visible = True
            return

        meta = self._pmeta.get(str(self.cb_param.SelectedItem), {})
        vals = meta.get('values', [])

        if not vals:
            self.lbl_hint.Text    = "No values found for this parameter."
            self.lbl_hint.Visible = True
            return

        self.lbl_hint.Visible = False
        for v in vals:
            self._colors[v]  = PALETTE[self._pal_idx % len(PALETTE)]
            self._enabled[v] = True
            self._pal_idx   += 1
            self.dgv.Rows.Add(v, "", "")   # 3 columns: value | swatch | on/off

    # ── Events ────────────────────────────────────────────────────────────────

    def _on_cat_search(self, s, e):
        if self._busy: return
        self._fill_cat_list(self.tb_search.Text)

    def _on_cat(self, s, e):
        if self._busy: return
        self._load_params()

    def _on_toggle(self, s, e):
        if self._busy or not s.Checked: return
        self._load_params()

    def _on_param(self, s, e):
        if self._busy: return
        self._fill_dgv()

    def _on_cell_click(self, s, e):
        if e.RowIndex < 0:
            return
        val = str(self.dgv.Rows[e.RowIndex].Cells[0].Value)

        if e.ColumnIndex == 1:
            # ── Colour picker ─────────────────────────────────────────────────
            dlg = ColorDialog()
            dlg.Color = self._colors.get(val, DC.White)
            if dlg.ShowDialog() == DialogResult.OK:
                self._colors[val] = dlg.Color
                self.dgv.InvalidateRow(e.RowIndex)

        elif e.ColumnIndex == 2:
            # ── On / Off toggle ───────────────────────────────────────────────
            self._enabled[val] = not self._enabled.get(val, True)
            row = self.dgv.Rows[e.RowIndex]
            # Dim the value text when OFF
            row.DefaultCellStyle.ForeColor = (
                TEXT if self._enabled[val] else MUTED)
            self.dgv.InvalidateRow(e.RowIndex)

    def _on_cell_paint(self, s, e):
        if e.RowIndex < 0:
            return

        if e.ColumnIndex == 1:
            # ── Colour swatch ─────────────────────────────────────────────────
            e.PaintBackground(e.CellBounds, True)
            val = str(self.dgv.Rows[e.RowIndex].Cells[0].Value)
            col = self._colors.get(val)
            if col:
                # Dim swatch when the row is OFF
                enabled = self._enabled.get(val, True)
                if not enabled:
                    col = DC.FromArgb(
                        int(col.R * 0.35), int(col.G * 0.35), int(col.B * 0.35))
                pad = 5
                r   = e.CellBounds
                br  = SolidBrush(col)
                e.Graphics.FillRectangle(
                    br, Rectangle(r.X + pad, r.Y + pad,
                                  r.Width - pad * 2, r.Height - pad * 2))
                br.Dispose()
            e.Handled = True

        elif e.ColumnIndex == 2:
            # ── ON / OFF pill ─────────────────────────────────────────────────
            e.PaintBackground(e.CellBounds, True)
            val     = str(self.dgv.Rows[e.RowIndex].Cells[0].Value)
            enabled = self._enabled.get(val, True)

            pad  = 5
            r    = e.CellBounds
            rect = Rectangle(r.X + pad, r.Y + pad,
                             r.Width - pad * 2, r.Height - pad * 2)

            bg_col  = GREEN if enabled else MUTED
            txt_col = DARK  if enabled else SUBTEXT
            label   = "ON"  if enabled else "OFF"

            # Fill pill background
            br = SolidBrush(bg_col)
            e.Graphics.FillRectangle(br, rect)
            br.Dispose()

            # Draw centred label
            sf               = StringFormat()
            sf.Alignment     = StringAlignment.Center
            sf.LineAlignment = StringAlignment.Center
            pill_font = Font(e.CellStyle.Font.FontFamily, 8, FontStyle.Bold)
            br2 = SolidBrush(txt_col)
            e.Graphics.DrawString(
                label, pill_font, br2,
                RectangleF(float(rect.X), float(rect.Y),
                           float(rect.Width), float(rect.Height)),
                sf)
            br2.Dispose()
            pill_font.Dispose()
            e.Handled = True

    # ── Apply dispatcher ──────────────────────────────────────────────────────

    def _apply(self, s, e):
        if not self._instances:
            MessageBox.Show(
                "No elements found in the active view for this category.",
                "Nothing to Colorize",
                MessageBoxButtons.OK, MessageBoxIcon.Warning)
            return
        if self.cb_param.SelectedItem is None:
            MessageBox.Show(
                "Please select a parameter from the dropdown.",
                "No Parameter Selected",
                MessageBoxButtons.OK, MessageBoxIcon.Warning)
            return
        if SOLID_PATTERN is None:
            MessageBox.Show(
                "No solid fill pattern found in the document.",
                "Missing Pattern", MessageBoxButtons.OK, MessageBoxIcon.Error)
            return

        if self.rb_filter.Checked:
            self._apply_filters()
        else:
            self._apply_overrides()

    # ── Apply: View Filters ───────────────────────────────────────────────────

    def _apply_filters(self):
        pname    = str(self.cb_param.SelectedItem)
        cat      = self._selected_cat()
        meta     = self._pmeta.get(pname, {})
        param_id = meta.get('pid')
        storage  = meta.get('storage')
        raw_map  = meta.get('raw', {})

        if param_id is None:
            MessageBox.Show(
                "Could not find parameter definition for '{0}'.".format(pname),
                "Error", MessageBoxButtons.OK, MessageBoxIcon.Error)
            return

        cat_ids = List[ElementId]()
        cat_ids.Add(cat.Id)

        applied    = 0
        skipped    = []
        first_fail = [None]

        t = Transaction(doc, "Filter Colorize: {0} \u2014 {1}".format(cat.Name, pname))
        t.Start()
        try:
            for val, col in self._colors.items():
                # Skip values that are toggled OFF
                if not self._enabled.get(val, True):
                    continue

                fname = make_filter_name(cat.Name, pname, val)
                rule  = make_rule(param_id, storage, val, raw_map.get(val))
                if rule is None:
                    skipped.append(val)
                    continue

                rules_list = List[FilterRule]()
                rules_list.Add(rule)
                elem_filter = ElementParameterFilter(rules_list)

                pfe = find_filter_by_name(fname)
                if pfe is None:
                    try:
                        pfe = ParameterFilterElement.Create(
                            doc, fname, cat_ids, elem_filter)
                    except Exception as ce:
                        if first_fail[0] is None:
                            first_fail[0] = str(ce)
                        skipped.append(val)
                        continue
                else:
                    try:
                        pfe.SetElementFilter(elem_filter)
                    except:
                        pass

                view_filter_ids = set(_eid(fid) for fid in active_view.GetFilters())
                if _eid(pfe.Id) not in view_filter_ids:
                    active_view.AddFilter(pfe.Id)

                ogs = OverrideGraphicSettings()
                rc  = RC(col.R, col.G, col.B)
                ogs.SetSurfaceForegroundPatternId(SOLID_PATTERN.Id)
                ogs.SetSurfaceForegroundPatternColor(rc)
                ogs.SetCutForegroundPatternId(SOLID_PATTERN.Id)
                ogs.SetCutForegroundPatternColor(rc)
                active_view.SetFilterOverrides(pfe.Id, ogs)
                active_view.SetFilterVisibility(pfe.Id, True)
                applied += 1

            t.Commit()

            msg = "Applied {0} view filter(s) for '{1}'.".format(applied, cat.Name)
            if skipped:
                msg += "\n\nSkipped ({0}):\n  {1}".format(
                    len(skipped), "\n  ".join(skipped[:10]))
            if first_fail[0]:
                msg += ("\n\nNote: category may have limited filter support.\n"
                        "First error: " + first_fail[0])
            MessageBox.Show(msg, "Done", MessageBoxButtons.OK,
                            MessageBoxIcon.Information if applied else MessageBoxIcon.Warning)

        except Exception as ex:
            try: t.RollBack()
            except: pass
            MessageBox.Show("Error:\n" + str(ex), "Error",
                            MessageBoxButtons.OK, MessageBoxIcon.Error)

    # ── Apply: Graphic Overrides ──────────────────────────────────────────────

    def _apply_overrides(self):
        pname    = str(self.cb_param.SelectedItem)
        use_type = self.rb_type.Checked
        cat      = self._selected_cat()

        reset_ogs = OverrideGraphicSettings()

        # Build override map only for ON values
        val_ogs = {}
        for val, col in self._colors.items():
            if not self._enabled.get(val, True):
                continue
            ogs = OverrideGraphicSettings()
            rc  = RC(col.R, col.G, col.B)
            ogs.SetSurfaceForegroundPatternId(SOLID_PATTERN.Id)
            ogs.SetSurfaceForegroundPatternColor(rc)
            ogs.SetCutForegroundPatternId(SOLID_PATTERN.Id)
            ogs.SetCutForegroundPatternColor(rc)
            val_ogs[val] = ogs

        t = Transaction(doc, "Override Colorize: {0} \u2014 {1}".format(cat.Name, pname))
        t.Start()
        try:
            applied = 0
            for inst in self._instances:
                # Always reset first so switching values clears old colours
                active_view.SetElementOverrides(inst.Id, reset_ogs)

                if use_type:
                    tid  = inst.GetTypeId()
                    elem = doc.GetElement(tid) if tid != ElementId.InvalidElementId else None
                else:
                    elem = inst

                if elem is None:
                    continue

                # Look up on the resolved element; fall back to instance if needed
                param = elem.LookupParameter(pname)
                if param is None and use_type:
                    param = inst.LookupParameter(pname)
                if param is None:
                    continue

                v = pval(param)
                if v in val_ogs:
                    active_view.SetElementOverrides(inst.Id, val_ogs[v])
                    applied += 1

            t.Commit()
            MessageBox.Show(
                "Applied overrides to {0} of {1} element(s).".format(
                    applied, len(self._instances)),
                "Done", MessageBoxButtons.OK, MessageBoxIcon.Information)

        except Exception as ex:
            try: t.RollBack()
            except: pass
            MessageBox.Show("Error:\n" + str(ex), "Error",
                            MessageBoxButtons.OK, MessageBoxIcon.Error)

    # ── Reset dispatcher ──────────────────────────────────────────────────────

    def _reset(self, s, e):
        if self.rb_filter.Checked:
            self._reset_filters()
        else:
            self._reset_overrides()

    def _reset_filters(self):
        wpc_ids = []
        for fid in list(active_view.GetFilters()):
            el = doc.GetElement(fid)
            if el is None:
                continue
            try:
                if el.Name.startswith(WPC_PREFIX):
                    wpc_ids.append(fid)
            except:
                pass

        if not wpc_ids:
            MessageBox.Show(
                "No WPC_ filters found in the active view.",
                "Nothing to Remove", MessageBoxButtons.OK, MessageBoxIcon.Information)
            return

        t = Transaction(doc, "Remove WPC_ View Filters")
        t.Start()
        try:
            for fid in wpc_ids:
                try: active_view.RemoveFilter(fid)
                except: pass
                try: doc.Delete(fid)
                except: pass
            t.Commit()
            MessageBox.Show(
                "Removed {0} WPC_ filter(s) from the active view.".format(len(wpc_ids)),
                "Done", MessageBoxButtons.OK, MessageBoxIcon.Information)
        except Exception as ex:
            try: t.RollBack()
            except: pass
            MessageBox.Show("Error:\n" + str(ex), "Error",
                            MessageBoxButtons.OK, MessageBoxIcon.Error)

    def _reset_overrides(self):
        if not self._instances:
            MessageBox.Show(
                "No elements loaded. Select a category first.",
                "Nothing to Reset", MessageBoxButtons.OK, MessageBoxIcon.Warning)
            return
        reset_ogs = OverrideGraphicSettings()
        t = Transaction(doc, "Reset Element Overrides")
        t.Start()
        try:
            for inst in self._instances:
                active_view.SetElementOverrides(inst.Id, reset_ogs)
            t.Commit()
            MessageBox.Show(
                "Overrides cleared for {0} element(s).".format(len(self._instances)),
                "Done", MessageBoxButtons.OK, MessageBoxIcon.Information)
        except Exception as ex:
            try: t.RollBack()
            except: pass
            MessageBox.Show("Error:\n" + str(ex), "Error",
                            MessageBoxButtons.OK, MessageBoxIcon.Error)

    def _cancel(self, s, e):
        self.Close()


# ── Entry point ───────────────────────────────────────────────────────────────

if EXEC_PARAMS.config_mode:
    # Config / right-click: remove all WPC_ filters from the active view
    wpc_ids = []
    for fid in active_view.GetFilters():
        el = doc.GetElement(fid)
        if el is not None:
            try:
                if el.Name.startswith(WPC_PREFIX):
                    wpc_ids.append(fid)
            except:
                pass
    if wpc_ids:
        t = Transaction(doc, "Remove WPC_ Filters (config)")
        t.Start()
        try:
            for fid in wpc_ids:
                try: active_view.RemoveFilter(fid)
                except: pass
                try: doc.Delete(fid)
                except: pass
            t.Commit()
        except:
            try: t.RollBack()
            except: pass
else:
    ColorizerForm().ShowDialog()
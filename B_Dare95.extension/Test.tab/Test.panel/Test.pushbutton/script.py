# -*- coding: utf-8 -*-
"""
Element Parameter Colorizer  –  View Filters
─────────────────────────────────────────────
Pick a category visible in the active view → toggle Instance / Type
parameters → pick a parameter → check values → assign colours → Apply.

Creates persistent ParameterFilterElement objects in the document and
adds them to the active view with graphic overrides.
Filter names are prefixed "[Colorizer]" for easy identification.

Right-click the button → Reset (config mode) – removes all [Colorizer]
filters from the active view (does not delete them from the document).

Note: Filters support String, Integer, Double, and ElementId parameters.
"""

import clr
clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Drawing')

from System.Windows.Forms import (
    Form, SplitContainer, FixedPanel,
    FlowLayoutPanel, FlowDirection,
    Panel, GroupBox, RadioButton, Label,
    ComboBox, ComboBoxStyle, TextBox,
    CheckedListBox, CheckState,
    Button, FlatStyle, ColorDialog,
    DataGridView, DataGridViewTextBoxColumn,
    DataGridViewAutoSizeColumnsMode,
    DataGridViewSelectionMode,
    DataGridViewColumnSortMode,
    DockStyle, Padding, FormStartPosition, FormBorderStyle,
    MessageBox, MessageBoxButtons, MessageBoxIcon, DialogResult,
    BorderStyle as WFBorderStyle,
)
from System.Drawing import (
    Color  as DrawingColor,
    Size, Font, FontStyle, SolidBrush, Rectangle,
)
from System.Collections.Generic import List

from Autodesk.Revit.DB import (
    FilteredElementCollector, FillPatternElement,
    OverrideGraphicSettings, Transaction,
    StorageType, ElementId,
    Color as RevitColor,
    ParameterFilterElement,
    ElementParameterFilter,
    ParameterValueProvider,
    FilterStringRule, FilterStringEquals,
    FilterIntegerRule, FilterDoubleRule,
    FilterNumericEquals,
    FilterElementIdRule,
)
from pyrevit import EXEC_PARAMS

# ── Revit context ─────────────────────────────────────────────────────────────

uidoc       = __revit__.ActiveUIDocument
doc         = __revit__.ActiveUIDocument.Document
active_view = doc.ActiveView

_all_pats     = FilteredElementCollector(doc).OfClass(FillPatternElement).ToElements()
solid_pattern = next((p for p in _all_pats if p.GetFillPattern().IsSolidFill), None)

FILTER_PREFIX = "[Colorizer]"

# ── Catppuccin Mocha palette ──────────────────────────────────────────────────

BG      = DrawingColor.FromArgb(0x1E, 0x1E, 0x2E)
CARD    = DrawingColor.FromArgb(0x2A, 0x2A, 0x3C)
SURFACE = DrawingColor.FromArgb(0x31, 0x32, 0x44)
MUTED   = DrawingColor.FromArgb(0x45, 0x47, 0x5A)
TEXT    = DrawingColor.FromArgb(0xCD, 0xD6, 0xF4)
SUBTEXT = DrawingColor.FromArgb(0xA6, 0xAD, 0xC8)
ACCENT  = DrawingColor.FromArgb(0xF0, 0xA5, 0x00)

PALETTE = [
    DrawingColor.FromArgb(243,  139, 168),
    DrawingColor.FromArgb(250,  179, 135),
    DrawingColor.FromArgb(249,  226, 175),
    DrawingColor.FromArgb(166,  227, 161),
    DrawingColor.FromArgb(137,  220, 235),
    DrawingColor.FromArgb(116,  199, 236),
    DrawingColor.FromArgb(137,  180, 250),
    DrawingColor.FromArgb(180,  190, 254),
    DrawingColor.FromArgb(203,  166, 247),
    DrawingColor.FromArgb(245,  194, 231),
]

# ── Category collection ───────────────────────────────────────────────────────

def _get_categories():
    cats = {}
    for el in (FilteredElementCollector(doc, active_view.Id)
               .WhereElementIsNotElementType()):
        try:
            cat = el.Category
            if cat is not None and cat.Name:
                cats[cat.Name] = cat.Id
        except Exception:
            pass
    return dict(sorted(cats.items()))


ALL_CATEGORIES = _get_categories()

# ── Revit helpers ─────────────────────────────────────────────────────────────

def _eid_str(eid):
    try:
        return str(eid.Value)
    except AttributeError:
        return str(eid.IntegerValue)


def param_value_str(param):
    if param is None or not param.HasValue:
        return "<No Value>"
    st = param.StorageType
    if st == StorageType.String:
        v = param.AsString()
        return v if v else "<Empty>"
    elif st == StorageType.Integer:
        return str(param.AsInteger())
    elif st == StorageType.Double:
        return str(round(param.AsDouble(), 3))
    elif st == StorageType.ElementId:
        eid = param.AsElementId()
        if eid == ElementId.InvalidElementId:
            return "<None>"
        el = doc.GetElement(eid)
        try:
            return el.Name if el else _eid_str(eid)
        except Exception:
            return _eid_str(eid)
    return "<Unknown>"


def get_elements_by_cat(cat_id):
    return list(
        FilteredElementCollector(doc, active_view.Id)
        .OfCategoryId(cat_id)
        .WhereElementIsNotElementType()
        .ToElements()
    )


def collect_params(cat_id, use_type):
    """
    Return {param_name: {'storage_type', 'param_id', 'values': {disp: raw}}}
    Only parameters with a valid (non-None) StorageType are included.
    """
    elements = get_elements_by_cat(cat_id)

    if use_type:
        seen, type_els = set(), []
        for el in elements:
            key = _eid_str(el.GetTypeId())
            if key not in seen:
                seen.add(key)
                tel = doc.GetElement(el.GetTypeId())
                if tel is not None:
                    type_els.append(tel)
        elements = type_els

    pdata = {}
    for el in elements:
        for p in el.Parameters:
            if p.Definition is None:
                continue
            name = p.Definition.Name
            if name not in pdata:
                pdata[name] = {
                    'storage_type': p.StorageType,
                    'param_id':     p.Id,
                    'values':       {},
                }
            disp = param_value_str(p)
            if disp not in pdata[name]['values']:
                st = p.StorageType
                if st == StorageType.String:
                    raw = p.AsString() or u""
                elif st == StorageType.Integer:
                    raw = p.AsInteger()
                elif st == StorageType.Double:
                    raw = p.AsDouble()
                elif st == StorageType.ElementId:
                    raw = p.AsElementId()
                else:
                    raw = None
                pdata[name]['values'][disp] = raw

    # Sort values per parameter
    result = {}
    for k, v in sorted(pdata.items()):
        v['values_sorted'] = sorted(v['values'].keys())
        result[k] = v
    return result


# ── Filter helpers ────────────────────────────────────────────────────────────

def _make_filter_rule(param_id, storage_type, raw_value):
    """Build a FilterRule for the given parameter and raw value."""
    pvp = ParameterValueProvider(param_id)
    try:
        if storage_type == StorageType.String:
            s = raw_value if raw_value is not None else u""
            try:
                # Revit 2022+ – 3-arg (no caseSensitive)
                return FilterStringRule(pvp, FilterStringEquals(), s)
            except Exception:
                return FilterStringRule(pvp, FilterStringEquals(), s, False)

        elif storage_type == StorageType.Integer:
            return FilterIntegerRule(pvp, FilterNumericEquals(), int(raw_value))

        elif storage_type == StorageType.Double:
            return FilterDoubleRule(pvp, FilterNumericEquals(), float(raw_value), 1e-6)

        elif storage_type == StorageType.ElementId:
            return FilterElementIdRule(pvp, FilterNumericEquals(), raw_value)

    except Exception:
        pass
    return None


def _make_filter_name(cat_name, param_name, val_disp):
    """Build a unique, human-readable filter name (max 100 chars)."""
    raw = u"{} {} – {} – {}".format(FILTER_PREFIX, cat_name, param_name, val_disp)
    return raw[:100]


def _get_existing_filter(name):
    """Return an existing ParameterFilterElement by name, or None."""
    for f in FilteredElementCollector(doc).OfClass(ParameterFilterElement):
        if f.Name == name:
            return f
    return None


def _ensure_filter(name, cat_id, param_id, storage_type, raw_value):
    """
    Return a ParameterFilterElement for this (name, category, rule) combination.
    Creates it if it doesn't exist; updates its rule if it does.
    Caller must be inside a Transaction.
    """
    rule = _make_filter_rule(param_id, storage_type, raw_value)
    if rule is None:
        return None

    elem_filter = ElementParameterFilter(rule)
    cat_ids     = List[ElementId]([cat_id])

    existing = _get_existing_filter(name)
    if existing is not None:
        try:
            existing.SetElementFilter(elem_filter)
        except Exception:
            pass
        return existing

    # Create new
    try:
        # Revit 2021+ 4-arg Create
        return ParameterFilterElement.Create(doc, name, cat_ids, elem_filter)
    except Exception:
        try:
            pf = ParameterFilterElement.Create(doc, name, cat_ids)
            pf.SetElementFilter(elem_filter)
            return pf
        except Exception:
            return None


def _remove_colorizer_filters_from_view():
    """Remove all [Colorizer] filters from the active view (does not delete them)."""
    for fid in list(active_view.GetFilters()):
        f = doc.GetElement(fid)
        if f is not None and f.Name.startswith(FILTER_PREFIX):
            try:
                active_view.RemoveFilter(fid)
            except Exception:
                pass


# ── Form ──────────────────────────────────────────────────────────────────────

class ColorizeForm(Form):

    def __init__(self):
        Form.__init__(self)
        self.Text            = "Element Parameter Colorizer  –  Filters"
        self.Size            = Size(940, 640)
        self.MinimumSize     = Size(720, 480)
        self.StartPosition   = FormStartPosition.CenterScreen
        self.FormBorderStyle = FormBorderStyle.Sizable
        self.BackColor       = BG

        self._current_cat_id   = None
        self._current_cat_name = ""
        self.param_data        = {}   # name -> dict from collect_params
        self.check_order       = []
        self.checked_vals      = set()
        self.val_colors        = {}
        self._pal_idx          = 0
        self._val_to_row       = {}
        self._updating         = False

        self._build_ui()
        self._populate_categories()

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _lbl(text, h=20):
        l           = Label()
        l.Text      = text
        l.Dock      = DockStyle.Top
        l.Height    = h
        l.Padding   = Padding(0, 5, 0, 0)
        l.BackColor = DrawingColor.Transparent
        l.ForeColor = SUBTEXT
        return l

    @staticmethod
    def _combo():
        cb               = ComboBox()
        cb.Dock          = DockStyle.Top
        cb.DropDownStyle = ComboBoxStyle.DropDownList
        cb.Height        = 26
        cb.BackColor     = SURFACE
        cb.ForeColor     = TEXT
        cb.FlatStyle     = FlatStyle.Flat
        return cb

    @staticmethod
    def _textbox():
        tb             = TextBox()
        tb.Dock        = DockStyle.Top
        tb.Height      = 24
        tb.BackColor   = SURFACE
        tb.ForeColor   = TEXT
        tb.BorderStyle = WFBorderStyle.FixedSingle
        return tb

    @staticmethod
    def _btn(text, fn, width=100):
        b             = Button()
        b.Text        = text
        b.Width       = width
        b.Height      = 32
        b.Margin      = Padding(6, 0, 0, 0)
        b.BackColor   = MUTED
        b.ForeColor   = TEXT
        b.FlatStyle   = FlatStyle.Flat
        b.FlatAppearance.BorderColor = SURFACE
        b.FlatAppearance.BorderSize  = 1
        b.Click      += fn
        return b

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        self.SuspendLayout()

        # ── Bottom bar ────────────────────────────────────────────────────────
        bp               = FlowLayoutPanel()
        bp.Dock          = DockStyle.Bottom
        bp.Height        = 50
        bp.FlowDirection = FlowDirection.RightToLeft
        bp.WrapContents  = False
        bp.Padding       = Padding(8, 8, 8, 0)
        bp.BackColor     = CARD

        bp.Controls.Add(self._btn("Cancel",       self._on_cancel))
        bp.Controls.Add(self._btn("Remove Filters", self._on_reset, width=120))

        apply_btn = self._btn("Apply Filters", self._on_apply, width=120)
        apply_btn.BackColor = ACCENT
        apply_btn.ForeColor = BG
        bp.Controls.Add(apply_btn)

        div            = Panel()
        div.Dock       = DockStyle.Bottom
        div.Height     = 1
        div.BackColor  = MUTED

        # ── SplitContainer ────────────────────────────────────────────────────
        split           = SplitContainer()
        split.Dock      = DockStyle.Fill
        split.BackColor = MUTED
        self._split     = split

        # ── LEFT ──────────────────────────────────────────────────────────────
        lp           = Panel()
        lp.Dock      = DockStyle.Fill
        lp.Padding   = Padding(10, 8, 10, 8)
        lp.BackColor = BG

        self.cb_cat = self._combo()
        self.cb_cat.SelectedIndexChanged += self._on_cat_changed

        grp           = GroupBox()
        grp.Text      = "Parameter Source"
        grp.Dock      = DockStyle.Top
        grp.Height    = 56
        grp.Padding   = Padding(8, 2, 6, 0)
        grp.ForeColor = SUBTEXT
        grp.BackColor = DrawingColor.Transparent

        self.rb_inst         = RadioButton()
        self.rb_inst.Text    = "Instance"
        self.rb_inst.Checked = True
        self.rb_inst.Left    = 10
        self.rb_inst.Top     = 20
        self.rb_inst.Width   = 90
        self.rb_inst.Height  = 24
        self.rb_inst.ForeColor = TEXT
        self.rb_inst.BackColor = DrawingColor.Transparent

        self.rb_type         = RadioButton()
        self.rb_type.Text    = "Type"
        self.rb_type.Left    = 108
        self.rb_type.Top     = 20
        self.rb_type.Width   = 70
        self.rb_type.Height  = 24
        self.rb_type.ForeColor = TEXT
        self.rb_type.BackColor = DrawingColor.Transparent

        self.rb_inst.CheckedChanged += self._on_toggle
        self.rb_type.CheckedChanged += self._on_toggle
        grp.Controls.Add(self.rb_inst)
        grp.Controls.Add(self.rb_type)

        self.cb_param = self._combo()
        self.cb_param.SelectedIndexChanged += self._on_param_changed

        self.tb_search             = self._textbox()
        self.tb_search.TextChanged += self._on_search

        self.clb              = CheckedListBox()
        self.clb.Dock         = DockStyle.Fill
        self.clb.CheckOnClick = True
        self.clb.BackColor    = SURFACE
        self.clb.ForeColor    = TEXT
        self.clb.BorderStyle  = WFBorderStyle.None
        self.clb.ItemCheck   += self._on_item_check

        for ctrl in [
            self._lbl("Category:"),   self.cb_cat,
            grp,
            self._lbl("Parameter:"),  self.cb_param,
            self._lbl("Search Values:"), self.tb_search,
            self._lbl("Values  (check to assign colour):", h=22),
        ]:
            lp.Controls.Add(ctrl)
        lp.Controls.Add(self.clb)

        split.Panel1.Controls.Add(lp)
        split.Panel1.BackColor = BG

        # ── RIGHT ─────────────────────────────────────────────────────────────
        rp           = Panel()
        rp.Dock      = DockStyle.Fill
        rp.Padding   = Padding(10, 8, 10, 8)
        rp.BackColor = BG

        lbl_head          = Label()
        lbl_head.Text     = "Colour Assignments"
        lbl_head.Dock     = DockStyle.Top
        lbl_head.Height   = 24
        lbl_head.Font     = Font(self.Font, FontStyle.Bold)
        lbl_head.ForeColor = TEXT
        lbl_head.BackColor = DrawingColor.Transparent

        self.lbl_hint           = Label()
        self.lbl_hint.Text      = "Check values on the left to assign colours."
        self.lbl_hint.Dock      = DockStyle.Top
        self.lbl_hint.Height    = 20
        self.lbl_hint.ForeColor = SUBTEXT
        self.lbl_hint.BackColor = DrawingColor.Transparent

        self.dgv = DataGridView()
        self.dgv.Dock                        = DockStyle.Fill
        self.dgv.RowHeadersVisible           = False
        self.dgv.AllowUserToAddRows          = False
        self.dgv.AllowUserToDeleteRows       = False
        self.dgv.AllowUserToResizeRows       = False
        self.dgv.ReadOnly                    = True
        self.dgv.MultiSelect                 = False
        self.dgv.SelectionMode               = DataGridViewSelectionMode.FullRowSelect
        self.dgv.AutoSizeColumnsMode         = DataGridViewAutoSizeColumnsMode.Fill
        self.dgv.ColumnHeadersHeightSizeMode = self.dgv.ColumnHeadersHeightSizeMode.DisableResizing
        self.dgv.ColumnHeadersHeight         = 28
        self.dgv.RowTemplate.Height          = 34
        self.dgv.BackgroundColor             = CARD
        self.dgv.BorderStyle                 = self.dgv.BorderStyle.None
        self.dgv.CellBorderStyle             = self.dgv.CellBorderStyle.SingleHorizontal
        self.dgv.GridColor                   = MUTED
        self.dgv.EnableHeadersVisualStyles   = False

        hdr = self.dgv.ColumnHeadersDefaultCellStyle
        hdr.BackColor          = MUTED
        hdr.ForeColor          = TEXT
        hdr.SelectionBackColor = MUTED
        hdr.SelectionForeColor = TEXT
        self.dgv.ColumnHeadersDefaultCellStyle = hdr

        row = self.dgv.DefaultCellStyle
        row.BackColor          = SURFACE
        row.ForeColor          = TEXT
        row.SelectionBackColor = MUTED
        row.SelectionForeColor = TEXT
        self.dgv.DefaultCellStyle = row

        col_val            = DataGridViewTextBoxColumn()
        col_val.HeaderText = "Value"
        col_val.FillWeight = 80
        col_val.SortMode   = DataGridViewColumnSortMode.NotSortable
        col_val.ReadOnly   = True

        col_clr            = DataGridViewTextBoxColumn()
        col_clr.HeaderText = "Colour  (click to change)"
        col_clr.FillWeight = 20
        col_clr.SortMode   = DataGridViewColumnSortMode.NotSortable
        col_clr.ReadOnly   = True

        self.dgv.Columns.Add(col_val)
        self.dgv.Columns.Add(col_clr)
        self.dgv.CellClick    += self._on_dgv_cell_click
        self.dgv.CellPainting += self._on_dgv_cell_paint

        rp.Controls.Add(lbl_head)
        rp.Controls.Add(self.lbl_hint)
        rp.Controls.Add(self.dgv)

        split.Panel2.Controls.Add(rp)
        split.Panel2.BackColor = BG

        self.Controls.Add(split)
        self.Controls.Add(div)
        self.Controls.Add(bp)

        self.Load += self._on_load
        self.ResumeLayout(True)

    # ── Form.Load ─────────────────────────────────────────────────────────────

    def _on_load(self, s, e):
        self._split.FixedPanel    = FixedPanel.Panel1
        self._split.Panel1MinSize = 270
        self._split.Panel2MinSize = 250
        w    = self._split.Width
        dist = max(270, min(430, w - 250 - self._split.SplitterWidth))
        self._split.SplitterDistance = dist

    # ── Data loading ──────────────────────────────────────────────────────────

    def _populate_categories(self):
        self._updating = True
        self.cb_cat.Items.Clear()
        for name in ALL_CATEGORIES:
            self.cb_cat.Items.Add(name)
        self._updating = False
        if self.cb_cat.Items.Count > 0:
            self.cb_cat.SelectedIndex = 0

    def _load_params(self):
        if self._current_cat_id is None:
            return
        use_type        = self.rb_type.Checked
        self.param_data = collect_params(self._current_cat_id, use_type)

        self._updating = True
        self.cb_param.Items.Clear()
        for name in sorted(self.param_data):
            self.cb_param.Items.Add(name)
        self._updating = False

        self._reset_state()
        if self.cb_param.Items.Count > 0:
            self.cb_param.SelectedIndex = 0

    def _reset_state(self):
        self.check_order  = []
        self.checked_vals = set()
        self.val_colors   = {}
        self._pal_idx     = 0
        self._val_to_row  = {}
        self.dgv.Rows.Clear()
        self.lbl_hint.Visible = True

    def _populate_values(self):
        sel = self.cb_param.SelectedItem
        if sel is None:
            self.clb.Items.Clear()
            return
        pinfo  = self.param_data.get(str(sel))
        if pinfo is None:
            return
        all_vals = pinfo.get('values_sorted', [])
        search   = self.tb_search.Text.strip().lower()
        filtered = [v for v in all_vals if search in v.lower()] if search else all_vals

        self._updating = True
        self.clb.ItemCheck -= self._on_item_check
        self.clb.Items.Clear()
        for v in filtered:
            self.clb.Items.Add(v, v in self.checked_vals)
        self.clb.ItemCheck += self._on_item_check
        self._updating = False

    # ── DataGridView helpers ──────────────────────────────────────────────────

    def _dgv_add_row(self, val):
        if val not in self.val_colors:
            self.val_colors[val] = PALETTE[self._pal_idx % len(PALETTE)]
            self._pal_idx += 1
        idx = self.dgv.Rows.Add(val, "")
        self._val_to_row[val] = idx
        self._dgv_colour_cell(idx, self.val_colors[val])

    def _dgv_colour_cell(self, row_idx, color):
        cell = self.dgv.Rows[row_idx].Cells[1]
        cell.Style.BackColor          = color
        cell.Style.SelectionBackColor = color

    def _dgv_rebuild(self):
        self.dgv.Rows.Clear()
        self._val_to_row = {}
        for val in self.check_order:
            self._dgv_add_row(val)

    # ── Event handlers ────────────────────────────────────────────────────────

    def _on_cat_changed(self, s, e):
        if self._updating:
            return
        sel = self.cb_cat.SelectedItem
        if sel is None:
            return
        self._current_cat_name = str(sel)
        self._current_cat_id   = ALL_CATEGORIES.get(self._current_cat_name)
        self.tb_search.Text    = ""
        self._load_params()

    def _on_toggle(self, s, e):
        if self._updating or not s.Checked:
            return
        self._updating = True
        self.tb_search.Text = ""
        self._updating = False
        self._load_params()

    def _on_param_changed(self, s, e):
        if self._updating:
            return
        self._updating = True
        self.tb_search.Text = ""
        self._updating = False
        self._reset_state()
        self._populate_values()

    def _on_search(self, s, e):
        if not self._updating:
            self._populate_values()

    def _on_item_check(self, s, e):
        if self._updating:
            return
        val = str(self.clb.Items[e.Index])
        if e.NewValue == CheckState.Checked:
            self.checked_vals.add(val)
            if val not in self.check_order:
                self.check_order.append(val)
            if val not in self._val_to_row:
                self._dgv_add_row(val)
            self.lbl_hint.Visible = False
        else:
            self.checked_vals.discard(val)
            if val in self.check_order:
                self.check_order.remove(val)
            if val in self._val_to_row:
                del self._val_to_row[val]
            self._dgv_rebuild()
            self.lbl_hint.Visible = (len(self.check_order) == 0)

    def _on_dgv_cell_click(self, s, e):
        if e.ColumnIndex != 1 or e.RowIndex < 0:
            return
        val = str(self.dgv.Rows[e.RowIndex].Cells[0].Value)
        dlg = ColorDialog()
        dlg.Color = self.val_colors.get(val, DrawingColor.White)
        if dlg.ShowDialog() == DialogResult.OK:
            self.val_colors[val] = dlg.Color
            row_idx = self._val_to_row.get(val)
            if row_idx is not None:
                self._dgv_colour_cell(row_idx, dlg.Color)
                self.dgv.InvalidateRow(row_idx)

    def _on_dgv_cell_paint(self, s, e):
        if e.ColumnIndex != 1 or e.RowIndex < 0:
            return
        e.PaintBackground(e.CellBounds, True)
        val = str(self.dgv.Rows[e.RowIndex].Cells[0].Value)
        col = self.val_colors.get(val)
        if col is not None:
            pad  = 4
            r    = e.CellBounds
            rect = Rectangle(r.X + pad, r.Y + pad, r.Width - pad * 2, r.Height - pad * 2)
            brush = SolidBrush(col)
            e.Graphics.FillRectangle(brush, rect)
            brush.Dispose()
        e.Handled = True

    # ── Apply / Reset / Cancel ────────────────────────────────────────────────

    def _on_apply(self, s, e):
        if not self.checked_vals:
            MessageBox.Show(
                "Please check at least one value on the left.",
                "Nothing Selected",
                MessageBoxButtons.OK, MessageBoxIcon.Warning,
            )
            return

        param_name = str(self.cb_param.SelectedItem) if self.cb_param.SelectedItem else None
        if not param_name or self._current_cat_id is None:
            return

        pinfo = self.param_data.get(param_name)
        if pinfo is None:
            return

        storage_type = pinfo['storage_type']
        param_id     = pinfo['param_id']
        raw_values   = pinfo['values']   # disp -> raw

        t = Transaction(doc, "Colorize {} by {} [Filters]".format(
            self._current_cat_name, param_name))
        t.Start()
        errors = []
        try:
            # Remove any existing Colorizer filters for this param from the view
            # so stale entries don't linger
            for fid in list(active_view.GetFilters()):
                f = doc.GetElement(fid)
                if f is not None and f.Name.startswith(
                        u"{} {} – {} –".format(FILTER_PREFIX, self._current_cat_name, param_name)):
                    active_view.RemoveFilter(fid)

            for val_disp in self.check_order:
                col = self.val_colors.get(val_disp)
                if col is None:
                    continue

                raw = raw_values.get(val_disp)
                if raw is None:
                    continue

                fname = _make_filter_name(self._current_cat_name, param_name, val_disp)
                pf    = _ensure_filter(fname, self._current_cat_id,
                                       param_id, storage_type, raw)
                if pf is None:
                    errors.append(val_disp)
                    continue

                # Add to view if not already there
                existing_ids = list(active_view.GetFilters())
                if pf.Id not in existing_ids:
                    active_view.AddFilter(pf.Id)

                # Build and apply overrides
                ogs = OverrideGraphicSettings()
                rc  = RevitColor(col.R, col.G, col.B)
                if solid_pattern:
                    ogs.SetSurfaceForegroundPatternId(solid_pattern.Id)
                    ogs.SetSurfaceForegroundPatternColor(rc)
                    ogs.SetCutForegroundPatternId(solid_pattern.Id)
                    ogs.SetCutForegroundPatternColor(rc)
                active_view.SetFilterOverrides(pf.Id, ogs)

            t.Commit()

            msg = "Filters applied: {}.".format(len(self.check_order))
            if errors:
                msg += "\n\nCould not create rules for:\n" + "\n".join(errors)
                msg += "\n(Parameters with unsupported types may not support filter rules.)"
            MessageBox.Show(msg, "Done", MessageBoxButtons.OK, MessageBoxIcon.Information)

        except Exception as ex:
            try:
                t.RollBack()
            except Exception:
                pass
            MessageBox.Show(
                "Error:\n" + str(ex), "Error",
                MessageBoxButtons.OK, MessageBoxIcon.Error,
            )

    def _on_reset(self, s, e):
        t = Transaction(doc, "Remove [Colorizer] Filters from View")
        t.Start()
        try:
            _remove_colorizer_filters_from_view()
            t.Commit()
            MessageBox.Show(
                "All [Colorizer] filters removed from the active view.",
                "Done", MessageBoxButtons.OK, MessageBoxIcon.Information,
            )
        except Exception as ex:
            try:
                t.RollBack()
            except Exception:
                pass
            MessageBox.Show(
                "Error:\n" + str(ex), "Error",
                MessageBoxButtons.OK, MessageBoxIcon.Error,
            )

    def _on_cancel(self, s, e):
        self.Close()


# ── Entry point ───────────────────────────────────────────────────────────────

if EXEC_PARAMS.config_mode:
    t = Transaction(doc, "Remove [Colorizer] Filters from View")
    t.Start()
    _remove_colorizer_filters_from_view()
    t.Commit()
else:
    form = ColorizeForm()
    form.ShowDialog()
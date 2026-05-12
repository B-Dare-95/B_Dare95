# -*- coding: utf-8 -*-
"""
Universal Element Colorizer  —  View Filters (ParameterFilterElement)
══════════════════════════════════════════════════════════════════════
1. Pick a category from the left list.
2. Pick a parameter (Instance or Type).
3. Colour-coded values appear automatically on the right.
4. Click any colour swatch to change it, then press Apply.

Filters are named  WPC_<Category>_<Parameter>_<Value>  and are stored
inside the Revit document. The Reset button removes all WPC_ filters
created by this tool from the active view.

Note: not all categories support View Filters. The tool will warn you
if the selected category cannot be used with ParameterFilterElement.
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
    Color as DC, Size, Font, FontStyle, SolidBrush, Rectangle,
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

# ── Solid fill pattern ────────────────────────────────────────────────────────
_pats         = FilteredElementCollector(doc).OfClass(FillPatternElement).ToElements()
SOLID_PATTERN = next((p for p in _pats if p.GetFillPattern().IsSolidFill), None)

# ── Catppuccin dark palette ───────────────────────────────────────────────────
BG      = DC.FromArgb(0x1E, 0x1E, 0x2E)
CARD    = DC.FromArgb(0x2A, 0x2A, 0x3C)
SURFACE = DC.FromArgb(0x31, 0x32, 0x44)
MUTED   = DC.FromArgb(0x45, 0x47, 0x5A)
TEXT    = DC.FromArgb(0xCD, 0xD6, 0xF4)
SUBTEXT = DC.FromArgb(0xA6, 0xAD, 0xC8)
ACCENT  = DC.FromArgb(0xF0, 0xA5, 0x00)

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
    Return a dict:
      {
        param_name: {
          'values'  : [sorted display strings],
          'storage' : StorageType,
          'pid'     : ElementId,   ← parameter definition ElementId
          'raw'     : {display_str: raw_value}
        }
      }
    raw_value type matches StorageType:
      String  → str   (empty string for <Empty>)
      Integer → int
      Double  → float (full precision AsDouble())
      ElementId → ElementId
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
                    meta[n] = {
                        'values' : set(),
                        'storage': st,
                        'pid'    : p.Id,
                        'raw'    : {},
                    }

                display = pval(p)

                # Extract raw value for filter rule creation
                if display not in meta[n]['raw']:
                    if not p.HasValue:
                        raw = None  # <No Value>
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

    # Sort values and return
    return {k: dict(v, values=sorted(v['values'])) for k, v in sorted(meta.items())}


def make_filter_name(cat_name, param_name, val_str):
    """Build a short, filesystem-safe WPC_ filter name (max 200 chars)."""
    def _safe(s, maxlen):
        import re
        s = re.sub(r'[^\w\-]', '_', s)
        return s[:maxlen]
    return "{0}{1}_{2}_{3}".format(
        WPC_PREFIX,
        _safe(cat_name, 24),
        _safe(param_name, 24),
        _safe(val_str, 40),
    )


def find_filter_by_name(name):
    """Return ParameterFilterElement with the given name, or None."""
    for el in FilteredElementCollector(doc).OfClass(ParameterFilterElement).ToElements():
        try:
            if el.Name == name:
                return el
        except:
            pass
    return None


def make_rule(param_id, storage_type, display_str, raw_value):
    """
    Build a ParameterFilterRule for a single value.
    Returns None if the rule cannot be created for this value.
    """
    try:
        # <No Value> → has-no-value rule
        if display_str == "<No Value>" or raw_value is None:
            try:
                return ParameterFilterRuleFactory.CreateHasNoValueRule(param_id)
            except:
                return None  # Not all Revit versions support HasNoValueRule

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

class FilterColorizerForm(Form):

    def __init__(self):
        Form.__init__(self)
        self.Text            = "Universal Element Colorizer  —  View Filters"
        self.Size            = Size(1000, 660)
        self.MinimumSize     = Size(780, 520)
        self.StartPosition   = FormStartPosition.CenterScreen
        self.FormBorderStyle = FormBorderStyle.Sizable
        self.BackColor       = BG

        # ── state ─────────────────────────────────────────────────────────────
        self._all_cats  = all_model_cats()
        self._instances = []
        self._pmeta     = {}     # full param metadata (with raw values)
        self._colors    = {}     # {val_str: DC}
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

        def mk_btn(text, fn, accent=False):
            b = Button()
            b.Text      = text
            b.Width     = 110
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

        bar.Controls.Add(mk_btn("Cancel",         self._cancel))
        bar.Controls.Add(mk_btn("Remove Filters", self._reset))
        bar.Controls.Add(mk_btn("Apply",          self._apply, accent=True))

        # ── SplitContainer ────────────────────────────────────────────────────
        sc           = SplitContainer()
        sc.Dock      = DockStyle.Fill
        sc.BackColor = MUTED
        self._sc     = sc

        # ═══════════════════════════════════════════════
        # LEFT PANEL  — Category + Parameter
        # ═══════════════════════════════════════════════
        lp           = Panel()
        lp.Dock      = DockStyle.Fill
        lp.Padding   = Padding(20, 20, 10, 10)
        lp.BackColor = BG

        # ── Parameter section (pinned bottom) ─────────────────────────────────
        pp           = Panel()
        pp.Dock      = DockStyle.Bottom
        pp.Height    =120
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
        cp.Padding = Padding(0, 0, 0, 6)

        lp.Controls.Add(cp)
        lp.Controls.Add(pp)

        sc.Panel1.BackColor = BG
        sc.Panel1.Controls.Add(lp)

        # ═══════════════════════════════════════
        # RIGHT PANEL  — Colour assignments DGV
        # ═══════════════════════════════════════
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
        self.lbl_hint.Text      = "← Select a category and parameter to populate."
        self.lbl_hint.ForeColor = SUBTEXT
        self.lbl_hint.BackColor = BG
        self.lbl_hint.Dock      = DockStyle.Top
        self.lbl_hint.Height    = 22
        self.lbl_hint.Visible   = True

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

        c0            = DataGridViewTextBoxColumn()
        c0.HeaderText = "Value"
        c0.FillWeight = 76
        c0.SortMode   = DataGridViewColumnSortMode.NotSortable
        c0.ReadOnly   = True

        c1            = DataGridViewTextBoxColumn()
        c1.HeaderText = "Colour  (click swatch to change)"
        c1.FillWeight = 24
        c1.SortMode   = DataGridViewColumnSortMode.NotSortable
        c1.ReadOnly   = True

        self.dgv.Columns.Add(c0)
        self.dgv.Columns.Add(c1)
        self.dgv.CellClick    += self._on_cell_click
        self.dgv.CellPainting += self._on_cell_paint

        rr.Controls.Add(self.dgv)  # Fill first
        rr.Controls.Add(self.lbl_hint)  # Then top controls
        rr.Controls.Add(lbl_head)
        self.lbl_hint.BringToFront()

        sc.Panel2.BackColor = BG
        sc.Panel2.Controls.Add(rr)

        self.Controls.Add(bar)
        self.Controls.Add(sc)

        self.Load += self._on_load
        self.ResumeLayout(True)

    def _on_load(self, s, e):
        self._sc.FixedPanel    = FixedPanel.Panel1
        self._sc.Panel1MinSize = 260
        self._sc.Panel2MinSize = 320
        w = self._sc.Width
        self._sc.SplitterDistance = max(260, min(380, w - 320 - self._sc.SplitterWidth))

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
        self._pal_idx = 0
        self.lbl_hint.Text    = "← Select a category and parameter to populate."
        self.lbl_hint.Visible = True

    def _fill_dgv(self):
        self.dgv.Rows.Clear()
        self._colors  = {}
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
            self._pal_idx   += 1
            self.dgv.Rows.Add(v, "")

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
        if e.ColumnIndex != 1 or e.RowIndex < 0: return
        val = str(self.dgv.Rows[e.RowIndex].Cells[0].Value)
        dlg = ColorDialog()
        dlg.Color = self._colors.get(val, DC.White)
        if dlg.ShowDialog() == DialogResult.OK:
            self._colors[val] = dlg.Color
            self.dgv.InvalidateRow(e.RowIndex)

    def _on_cell_paint(self, s, e):
        if e.ColumnIndex != 1 or e.RowIndex < 0: return
        e.PaintBackground(e.CellBounds, True)
        val = str(self.dgv.Rows[e.RowIndex].Cells[0].Value)
        col = self._colors.get(val)
        if col:
            pad = 5
            r   = e.CellBounds
            br  = SolidBrush(col)
            e.Graphics.FillRectangle(
                br, Rectangle(r.X + pad, r.Y + pad,
                              r.Width - pad * 2, r.Height - pad * 2))
            br.Dispose()
        e.Handled = True

    # ── Apply ─────────────────────────────────────────────────────────────────

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

        # Category ID list for ParameterFilterElement
        cat_ids = List[ElementId]()
        cat_ids.Add(cat.Id)

        applied    = 0
        skipped    = []
        first_fail = [None]    # mutable container for closure

        t = Transaction(doc, "Filter Colorize: {0} — {1}".format(cat.Name, pname))
        t.Start()
        try:
            for val, col in self._colors.items():
                fname = make_filter_name(cat.Name, pname, val)

                # Build the filter rule
                rule = make_rule(param_id, storage, val, raw_map.get(val))
                if rule is None:
                    skipped.append(val)
                    continue

                rules_list = List[FilterRule]()
                rules_list.Add(rule)
                elem_filter = ElementParameterFilter(rules_list)

                # Get or create the ParameterFilterElement
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
                    # Update the element filter on the existing PFE
                    try:
                        pfe.SetElementFilter(elem_filter)
                    except:
                        pass

                # Add to the active view if not already present
                view_filter_ids = set(_eid(fid) for fid in active_view.GetFilters())
                if _eid(pfe.Id) not in view_filter_ids:
                    active_view.AddFilter(pfe.Id)

                # Apply graphic overrides
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

            # ── Result message ────────────────────────────────────────────────
            msg = "Applied {0} view filter(s) for category '{1}'.".format(
                applied, cat.Name)
            if skipped:
                msg += "\n\nSkipped values ({0}):\n  {1}".format(
                    len(skipped), "\n  ".join(skipped[:10]))
            if first_fail[0]:
                msg += ("\n\nNote: the selected category may have limited support "
                        "for View Filters.\nFirst error: " + first_fail[0])

            MessageBox.Show(msg, "Done", MessageBoxButtons.OK,
                            MessageBoxIcon.Information if applied else MessageBoxIcon.Warning)

        except Exception as ex:
            try: t.RollBack()
            except: pass
            MessageBox.Show("Error:\n" + str(ex), "Error",
                            MessageBoxButtons.OK, MessageBoxIcon.Error)

    # ── Reset ─────────────────────────────────────────────────────────────────

    def _reset(self, s, e):
        """Remove all WPC_ filters from the active view (and delete orphaned ones)."""
        view_filter_ids = list(active_view.GetFilters())
        wpc_ids = []
        for fid in view_filter_ids:
            el = doc.GetElement(fid)
            if el is not None:
                try:
                    if el.Name.startswith(WPC_PREFIX):
                        wpc_ids.append(fid)
                except:
                    pass

        if not wpc_ids:
            MessageBox.Show(
                "No WPC_ filters found in the active view.",
                "Nothing to Remove",
                MessageBoxButtons.OK, MessageBoxIcon.Information)
            return

        t = Transaction(doc, "Remove WPC_ View Filters")
        t.Start()
        try:
            for fid in wpc_ids:
                try:
                    active_view.RemoveFilter(fid)
                except:
                    pass
                # Attempt to delete the filter element if unused elsewhere
                try:
                    doc.Delete(fid)
                except:
                    pass
            t.Commit()
            MessageBox.Show(
                "Removed {0} WPC_ filter(s) from the active view.".format(len(wpc_ids)),
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
    # Config mode: remove all WPC_ filters from the active view
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
    FilterColorizerForm().ShowDialog()
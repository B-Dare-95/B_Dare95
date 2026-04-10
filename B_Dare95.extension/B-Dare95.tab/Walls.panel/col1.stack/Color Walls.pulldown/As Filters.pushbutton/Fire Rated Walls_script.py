# -*- coding: utf-8 -*-
"""
Wall Parameter Colorizer  —  Filter Edition
────────────────────────────────────────────
Toggle Instance / Type parameters  →  pick a parameter  →  pick values
→  assign a colour to each value  →  Apply.

Creates ParameterFilterElements (View Filters) in the active view instead
of per-element graphic overrides.  Each filter is named:

    WPC_<ParamName>_<Value>

so the Reset action can identify and delete them.

Right-click the pushbutton  →  Reset (config mode):  removes all WPC_
filters from the active view and deletes the ParameterFilterElements.

──────────────────────────────────────────────────────────────────────────
Backwards-compatibility notes
──────────────────────────────────────────────────────────────────────────
• Revit 2019-2022  :  ParameterFilterElement.Create(doc, name, cats,
                       IList<FilterRule>)           ← primary path
• Revit 2023+      :  same overload still exists (deprecated but works);
                       also tries ElementParameterFilter wrapper as fallback
• ElementId.Value vs .IntegerValue  →  _eid_str() tries Value first (2025+)
• ParameterFilterRuleFactory.CreateEqualsRule(id, str, bool)
                       3-arg overload exists 2019 → 2027
• HasNoValue rule  :  tries CreateHasNoValueParameterRule (2022+) then
                       falls back to FilterHasNoValueRule(ParameterValueProvider)
• Double params    :  uses CreateEqualsRule with 1e-9 epsilon; shown with
                       a warning in the hint label
• ElementId params :  skipped — cannot reliably reconstruct ElementId from
                       the stored display name string
"""

import clr
clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Drawing')

# ── .NET / WinForms imports ───────────────────────────────────────────────────
# Both System.Drawing and Autodesk.Revit.DB export 'Color' and 'Panel'.
# Everything is imported explicitly and aliased where needed.

from System.Windows.Forms import (
    Form, SplitContainer, FixedPanel,
    FlowLayoutPanel, FlowDirection,
    Panel,
    GroupBox, RadioButton, Label,
    ComboBox, ComboBoxStyle, TextBox,
    CheckedListBox, CheckState,
    Button, FlatStyle, ColorDialog,
    DataGridView, DataGridViewTextBoxColumn,
    DataGridViewAutoSizeColumnsMode,
    DataGridViewAutoSizeColumnMode,
    DataGridViewSelectionMode,
    DataGridViewColumnSortMode,
    DockStyle, Padding, FormStartPosition, FormBorderStyle,
    MessageBox, MessageBoxButtons, MessageBoxIcon, DialogResult,
)
from System.Drawing import (
    Color  as DrawingColor,
    Size, Font, FontStyle, ContentAlignment, SolidBrush, Rectangle,
)
from System.Collections.Generic import List as CsList

# ── Revit DB imports ──────────────────────────────────────────────────────────

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    FillPatternElement,
    BuiltInCategory,
    OverrideGraphicSettings,
    Transaction,
    StorageType,
    ElementId,
    Color          as RevitColor,
    ParameterFilterElement,
    ParameterFilterRuleFactory,
    ElementParameterFilter,
    FilterRule,
)
from pyrevit import EXEC_PARAMS

# ── Revit context ─────────────────────────────────────────────────────────────

uidoc       = __revit__.ActiveUIDocument
doc         = __revit__.ActiveUIDocument.Document
active_view = doc.ActiveView

_all_pats     = FilteredElementCollector(doc).OfClass(FillPatternElement).ToElements()
solid_pattern = next(p for p in _all_pats if p.GetFillPattern().IsSolidFill)

all_walls = list(
    FilteredElementCollector(doc, active_view.Id)
    .OfCategory(BuiltInCategory.OST_Walls)
    .WhereElementIsNotElementType()
    .ToElements()
)

# ── Constants ─────────────────────────────────────────────────────────────────

# Every filter created by this tool is prefixed so Reset can find them.
FILTER_PREFIX = "WPC_"

# ── Auto-colour palette ───────────────────────────────────────────────────────

PALETTE = [
    DrawingColor.FromArgb(230,  57,  70),
    DrawingColor.FromArgb(255, 165,   0),
    DrawingColor.FromArgb(240, 215,  30),
    DrawingColor.FromArgb( 42, 157, 143),
    DrawingColor.FromArgb( 67, 170, 239),
    DrawingColor.FromArgb(132,  94, 194),
    DrawingColor.FromArgb(244, 114, 182),
    DrawingColor.FromArgb( 38, 200, 155),
    DrawingColor.FromArgb(200, 130,  60),
    DrawingColor.FromArgb(120, 144, 156),
]

# ── Revit parameter helpers ───────────────────────────────────────────────────

def _eid_str(eid):
    """ElementId → string.  Handles Revit 2025+ (.Value) and earlier (.IntegerValue)."""
    try:
        return str(eid.Value)
    except AttributeError:
        return str(eid.IntegerValue)


def param_value_str(param):
    """Convert any parameter to a human-readable string for display & matching."""
    if param is None or not param.HasValue:
        return "<No Value>"
    st = param.StorageType
    if st == StorageType.String:
        v = param.AsString()
        return v if v else "<Empty>"
    elif st == StorageType.Integer:
        return str(param.AsInteger())
    elif st == StorageType.Double:
        return str(round(param.AsDouble(), 9))
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


def collect_params(use_type):
    """Return {param_name: sorted_value_list} for walls visible in the active view."""
    pdata = {}
    if use_type:
        seen, elements = set(), []
        for w in all_walls:
            key = _eid_str(w.GetTypeId())
            if key not in seen:
                seen.add(key)
                el = doc.GetElement(w.GetTypeId())
                if el is not None:
                    elements.append(el)
    else:
        elements = list(all_walls)

    for el in elements:
        for p in el.Parameters:
            if p.Definition is None:
                continue
            name = p.Definition.Name
            val  = param_value_str(p)
            if name not in pdata:
                pdata[name] = set()
            pdata[name].add(val)

    return {k: sorted(v) for k, v in sorted(pdata.items())}


# ── Filter-building helpers ───────────────────────────────────────────────────

def _sanitize_filter_name(s):
    """Strip characters that Revit won't accept in filter names, cap length."""
    bad = set('<>:"/\\|?*{}[]')
    clean = ''.join('_' if c in bad else c for c in s)
    return clean[:100]


def _make_filter_name(param_name, val):
    return _sanitize_filter_name("{}{}_{}".format(FILTER_PREFIX, param_name, val))


def _get_param_id_and_storage(param_name, use_type):
    """
    Walk walls to find the first occurrence of param_name and return
    (Definition.Id, StorageType).  Returns (None, None) if not found.
    """
    for wall in all_walls:
        el = doc.GetElement(wall.GetTypeId()) if use_type else wall
        p  = el.LookupParameter(param_name)
        if p is not None and p.Definition is not None:
            try:
                return p.Definition.Id, p.StorageType
            except Exception:
                pass
    return None, None


def _make_rule(param_id, val, storage_type):
    """
    Build a FilterRule for  param == val.

    Returns (rule, warning_string).  rule is None when the value cannot be
    represented as a filter rule (ElementId params, unparseable numbers).

    Backwards-compatibility strategy
    ─────────────────────────────────
    • String  : CreateEqualsRule(id, str, bool)  — 3-arg overload present
                2019 → 2027.  Falls back to 2-arg if TypeError is raised.
    • Integer : CreateEqualsRule(id, int)
    • Double  : CreateEqualsRule(id, double, epsilon=1e-9)
    • No-value: tries CreateHasNoValueParameterRule (2022+) then
                FilterHasNoValueRule(ParameterValueProvider) for older builds.
    • ElementId: not supported — returns (None, warning).
    """
    # ── "no value" special cases ──────────────────────────────────────────────
    if val in ("<No Value>", "<None>", "<Unknown>"):
        try:
            rule = ParameterFilterRuleFactory.CreateHasNoValueParameterRule(param_id)
            return rule, None
        except Exception:
            pass
        try:
            from Autodesk.Revit.DB import FilterHasNoValueRule, ParameterValueProvider
            rule = FilterHasNoValueRule(ParameterValueProvider(param_id))
            return rule, None
        except Exception:
            return None, "Cannot create a 'has no value' rule for this Revit version."

    # ── ElementId params ──────────────────────────────────────────────────────
    if storage_type == StorageType.ElementId:
        return None, (
            "Filters for ElementId parameters are not supported "
            "(cannot reconstruct ElementId from display name)."
        )

    # ── String ────────────────────────────────────────────────────────────────
    if storage_type == StorageType.String:
        str_val = "" if val == "<Empty>" else val
        try:
            # 3-arg (case-sensitive=True): exists in Revit 2019 → 2027
            rule = ParameterFilterRuleFactory.CreateEqualsRule(param_id, str_val, True)
            return rule, None
        except TypeError:
            pass
        try:
            # 2-arg fallback for any future API that drops case sensitivity
            rule = ParameterFilterRuleFactory.CreateEqualsRule(param_id, str_val)
            return rule, None
        except Exception as ex:
            return None, "Could not create string rule: " + str(ex)

    # ── Integer ───────────────────────────────────────────────────────────────
    if storage_type == StorageType.Integer:
        try:
            rule = ParameterFilterRuleFactory.CreateEqualsRule(param_id, int(val))
            return rule, None
        except Exception as ex:
            return None, "Could not parse '{}' as integer: {}".format(val, ex)

    # ── Double ────────────────────────────────────────────────────────────────
    if storage_type == StorageType.Double:
        try:
            rule = ParameterFilterRuleFactory.CreateEqualsRule(
                param_id, float(val), 1e-9
            )
            return rule, (
                "Note: double-precision filter for '{}' uses epsilon 1e-9. "
                "Results may miss values if units differ.".format(val)
            )
        except Exception as ex:
            return None, "Could not parse '{}' as double: {}".format(val, ex)

    return None, "Unsupported storage type: {}".format(storage_type)


def _find_or_create_filter_elem(filter_name, param_id, rule):
    """
    Return an existing ParameterFilterElement named filter_name, or create
    a new one.  Tries the classic IList<FilterRule> overload first (2019-2022),
    then falls back to the ElementParameterFilter overload (2023+).
    """
    # Reuse if already exists in the document
    for f in FilteredElementCollector(doc).OfClass(ParameterFilterElement):
        if f.Name == filter_name:
            return f

    cats = CsList[ElementId]()
    cats.Add(ElementId(BuiltInCategory.OST_Walls))

    # Primary: IList<FilterRule>  — works 2019 → 2027 (deprecated but present)
    try:
        rules = CsList[FilterRule]()
        rules.Add(rule)
        return ParameterFilterElement.Create(doc, filter_name, cats, rules)
    except Exception:
        pass

    # Fallback: ElementParameterFilter wrapper  (2023+)
    try:
        elem_filter = ElementParameterFilter(rule)
        return ParameterFilterElement.Create(doc, filter_name, cats, elem_filter)
    except Exception as ex:
        raise RuntimeError(
            "Failed to create filter '{}': {}".format(filter_name, ex)
        )


def _make_ogs(drawing_color):
    """Build an OverrideGraphicSettings that paints elements solid in drawing_color."""
    ogs = OverrideGraphicSettings()
    rc  = RevitColor(drawing_color.R, drawing_color.G, drawing_color.B)
    ogs.SetSurfaceForegroundPatternId(solid_pattern.Id)
    ogs.SetSurfaceForegroundPatternColor(rc)
    ogs.SetCutForegroundPatternId(solid_pattern.Id)
    ogs.SetCutForegroundPatternColor(rc)
    return ogs


def _remove_wpc_filters_from_view(view):
    """Remove all WPC_ filters applied to view (does not delete the elements)."""
    for fid in list(view.GetFilters()):
        fe = doc.GetElement(fid)
        if fe is not None and fe.Name.startswith(FILTER_PREFIX):
            view.RemoveFilter(fid)


def _delete_wpc_filter_elements():
    """Delete all ParameterFilterElements whose name starts with WPC_."""
    to_delete = [
        f.Id
        for f in FilteredElementCollector(doc).OfClass(ParameterFilterElement)
        if f.Name.startswith(FILTER_PREFIX)
    ]
    for fid in to_delete:
        try:
            doc.Delete(fid)
        except Exception:
            pass


# ── Form ──────────────────────────────────────────────────────────────────────

class ColorizeForm(Form):

    def __init__(self):
        Form.__init__(self)
        self.Text            = "Wall Parameter Colorizer — Filters"
        self.Size            = Size(900, 600)
        self.MinimumSize     = Size(700, 460)
        self.StartPosition   = FormStartPosition.CenterScreen
        self.FormBorderStyle = FormBorderStyle.Sizable

        # state
        self.param_data   = {}
        self.check_order  = []
        self.checked_vals = set()
        self.val_colors   = {}
        self._pal_idx     = 0
        self._val_to_row  = {}
        self._updating    = False

        self._build_ui()
        self._load_params()

    # ──────────────────────────────────────────────────────── UI construction ──

    def _build_ui(self):
        self.SuspendLayout()

        def mklbl(text, h=20):
            l         = Label()
            l.Text    = text
            l.Dock    = DockStyle.Top
            l.Height  = h
            l.Padding = Padding(0, 4, 0, 0)
            return l

        def mk_btn(text, fn, width=92):
            b        = Button()
            b.Text   = text
            b.Width  = width
            b.Height = 30
            b.Margin = Padding(4, 0, 0, 0)
            b.Click += fn
            return b

        # ── Bottom button bar ─────────────────────────────────────────────────
        bp               = FlowLayoutPanel()
        bp.Dock          = DockStyle.Bottom
        bp.Height        = 46
        bp.FlowDirection = FlowDirection.RightToLeft
        bp.WrapContents  = False
        bp.Padding       = Padding(8, 7, 8, 0)
        bp.Controls.Add(mk_btn("Cancel", self._on_cancel))
        bp.Controls.Add(mk_btn("Reset",  self._on_reset))
        bp.Controls.Add(mk_btn("Apply",  self._on_apply))

        # ── SplitContainer — all sizing deferred to _on_load ──────────────────
        split       = SplitContainer()
        split.Dock  = DockStyle.Fill
        self._split = split

        # ── LEFT: source toggle + parameter combo + value list ────────────────
        grp         = GroupBox()
        grp.Text    = "Parameter Source"
        grp.Dock    = DockStyle.Top
        grp.Height  = 52
        grp.Padding = Padding(6, 0, 6, 0)

        self.rb_inst         = RadioButton()
        self.rb_inst.Text    = "Instance Parameters"
        self.rb_inst.Checked = True
        self.rb_inst.Left    = 12
        self.rb_inst.Top     = 18
        self.rb_inst.Width   = 170
        self.rb_inst.Height  = 24

        self.rb_type         = RadioButton()
        self.rb_type.Text    = "Type Parameters"
        self.rb_type.Left    = 192
        self.rb_type.Top     = 18
        self.rb_type.Width   = 150
        self.rb_type.Height  = 24

        self.rb_inst.CheckedChanged += self._on_toggle
        self.rb_type.CheckedChanged += self._on_toggle
        grp.Controls.Add(self.rb_inst)
        grp.Controls.Add(self.rb_type)

        lp         = Panel()
        lp.Dock    = DockStyle.Fill
        lp.Padding = Padding(8, 4, 8, 6)

        self.cb_param               = ComboBox()
        self.cb_param.Dock          = DockStyle.Top
        self.cb_param.DropDownStyle = ComboBoxStyle.DropDownList
        self.cb_param.Height        = 24
        self.cb_param.SelectedIndexChanged += self._on_param_changed

        self.tb_search             = TextBox()
        self.tb_search.Dock        = DockStyle.Top
        self.tb_search.Height      = 22
        self.tb_search.TextChanged += self._on_search

        self.clb              = CheckedListBox()
        self.clb.Dock         = DockStyle.Fill
        self.clb.CheckOnClick = True
        self.clb.ItemCheck   += self._on_item_check

        lp.Controls.Add(mklbl("Parameter:"))
        lp.Controls.Add(self.cb_param)
        lp.Controls.Add(mklbl("Values:", h=24))
        lp.Controls.Add(mklbl("Search:"))
        lp.Controls.Add(self.tb_search)
        lp.Controls.Add(self.clb)

        split.Panel1.Controls.Add(grp)
        split.Panel1.Controls.Add(lp)

        # ── RIGHT: Colour Assignments (DataGridView) ──────────────────────────
        rp         = Panel()
        rp.Dock    = DockStyle.Fill
        rp.Padding = Padding(8, 6, 8, 6)

        lbl_head        = Label()
        lbl_head.Text   = "Colour Assignments"
        lbl_head.Dock   = DockStyle.Top
        lbl_head.Height = 22
        lbl_head.Font   = Font(self.Font, FontStyle.Bold)

        self.lbl_hint           = Label()
        self.lbl_hint.Text      = "Check values on the left to assign colours."
        self.lbl_hint.Dock      = DockStyle.Top
        self.lbl_hint.Height    = 20
        self.lbl_hint.ForeColor = DrawingColor.FromArgb(120, 120, 120)

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
        self.dgv.ColumnHeadersHeightSizeMode = (
            self.dgv.ColumnHeadersHeightSizeMode.DisableResizing
        )
        self.dgv.ColumnHeadersHeight = 26
        self.dgv.RowTemplate.Height  = 34
        self.dgv.BackgroundColor     = DrawingColor.White
        self.dgv.BorderStyle         = self.dgv.BorderStyle.FixedSingle
        self.dgv.CellBorderStyle     = self.dgv.CellBorderStyle.SingleHorizontal
        self.dgv.GridColor           = DrawingColor.FromArgb(220, 220, 220)

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

        # ── Assemble form ─────────────────────────────────────────────────────
        self.Controls.Add(bp)
        self.Controls.Add(split)

        self.Load += self._on_load
        self.ResumeLayout(True)

    # ──────────────────────────────────────────────────────────── Form.Load ────

    def _on_load(self, s, e):
        """Defer all SplitContainer sizing to here — form has real dimensions."""
        self._split.FixedPanel    = FixedPanel.Panel1
        self._split.Panel1MinSize = 260
        self._split.Panel2MinSize = 240
        w    = self._split.Width
        dist = max(260, min(420, w - 240 - self._split.SplitterWidth))
        self._split.SplitterDistance = dist

    # ────────────────────────────────────────────────────────── Data loading ───

    def _load_params(self):
        use_type        = self.rb_type.Checked
        self.param_data = collect_params(use_type)

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
        self.lbl_hint.Text    = "Check values on the left to assign colours."
        self.lbl_hint.Visible = True

    def _populate_values(self):
        sel = self.cb_param.SelectedItem
        if sel is None:
            self.clb.Items.Clear()
            return
        all_vals = self.param_data.get(str(sel), [])
        search   = self.tb_search.Text.strip().lower()
        filtered = [v for v in all_vals if search in v.lower()] if search else all_vals

        self._updating = True
        self.clb.ItemCheck -= self._on_item_check
        self.clb.Items.Clear()
        for v in filtered:
            self.clb.Items.Add(v, v in self.checked_vals)
        self.clb.ItemCheck += self._on_item_check
        self._updating = False

    # ───────────────────────────────────────────── DataGridView helpers ─────────

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

    # ─────────────────────────────────────────────────────── Event handlers ────

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
        if self._updating:
            return
        self._populate_values()

    def _on_item_check(self, s, e):
        # ItemCheck fires BEFORE visual state changes — use e.NewValue.
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
        """Click the Colour column → open ColorDialog."""
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
        """Paint the Colour column as a solid filled rectangle."""
        if e.ColumnIndex != 1 or e.RowIndex < 0:
            return
        e.PaintBackground(e.CellBounds, True)
        val = str(self.dgv.Rows[e.RowIndex].Cells[0].Value)
        col = self.val_colors.get(val)
        if col is not None:
            pad  = 4
            r    = e.CellBounds
            rect = Rectangle(r.X + pad, r.Y + pad,
                             r.Width  - pad * 2,
                             r.Height - pad * 2)
            brush = SolidBrush(col)
            e.Graphics.FillRectangle(brush, rect)
            brush.Dispose()
        e.Handled = True

    # ─────────────────────────────────────────────────── Apply (create filters) ─

    def _on_apply(self, s, e):
        if not self.checked_vals:
            MessageBox.Show(
                "Please check at least one value on the left.",
                "Nothing Selected",
                MessageBoxButtons.OK, MessageBoxIcon.Warning,
            )
            return

        param_name = str(self.cb_param.SelectedItem) if self.cb_param.SelectedItem else None
        if not param_name:
            return

        use_type = self.rb_type.Checked

        # Get the parameter ElementId and storage type from the first wall that has it
        param_id, storage_type = _get_param_id_and_storage(param_name, use_type)
        if param_id is None:
            MessageBox.Show(
                "Could not find parameter '{}' on any wall in this view.".format(param_name),
                "Parameter Not Found",
                MessageBoxButtons.OK, MessageBoxIcon.Warning,
            )
            return

        # Collect any warnings to report after the transaction
        warnings   = []
        skipped    = []
        applied    = 0

        t = Transaction(doc, "Create Wall Filters - " + param_name)
        t.Start()
        try:
            # Step 1: Remove existing WPC_ filters from the view so we start clean.
            # (Filter elements themselves are preserved/reused.)
            _remove_wpc_filters_from_view(active_view)

            # Step 2: For each checked value, build a rule → filter → apply to view.
            for val in self.check_order:   # use check_order to preserve stacking order
                if val not in self.checked_vals:
                    continue

                rule, warn = _make_rule(param_id, val, storage_type)

                if warn:
                    warnings.append(u"{}: {}".format(val, warn))

                if rule is None:
                    skipped.append(val)
                    continue

                filter_name = _make_filter_name(param_name, val)

                try:
                    fe = _find_or_create_filter_elem(filter_name, param_id, rule)
                except Exception as ex:
                    warnings.append(u"Could not create filter for '{}': {}".format(val, ex))
                    skipped.append(val)
                    continue

                # Add the filter to the view (idempotent if already there)
                if not active_view.IsFilterApplied(fe.Id):
                    active_view.AddFilter(fe.Id)

                # Apply colour override through the filter
                active_view.SetFilterOverrides(fe.Id, _make_ogs(self.val_colors[val]))
                active_view.SetFilterVisibility(fe.Id, True)
                applied += 1

            t.Commit()

        except Exception as ex:
            try:
                t.RollBack()
            except Exception:
                pass
            MessageBox.Show(
                "Transaction failed:\n" + str(ex),
                "Error", MessageBoxButtons.OK, MessageBoxIcon.Error,
            )
            return

        # ── Summary message ───────────────────────────────────────────────────
        lines = ["{} filter(s) applied to the active view.".format(applied)]
        if skipped:
            lines.append(
                "\nSkipped ({} value(s) — unsupported type):".format(len(skipped))
            )
            lines.extend(u"  • " + v for v in skipped)
        if warnings:
            lines.append("\nWarnings:")
            lines.extend(u"  • " + w for w in warnings)

        icon = MessageBoxIcon.Warning if (skipped or warnings) else MessageBoxIcon.Information
        MessageBox.Show(
            "\n".join(lines), "Done",
            MessageBoxButtons.OK, icon,
        )

    # ───────────────────────────────────── Reset (remove + delete WPC filters) ──

    def _on_reset(self, s, e):
        t = Transaction(doc, "Remove Wall Filters (WPC)")
        t.Start()
        try:
            _remove_wpc_filters_from_view(active_view)
            _delete_wpc_filter_elements()
            t.Commit()
            MessageBox.Show(
                "All WPC_ filters removed from view and deleted.",
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
    # Right-click → immediately remove and delete all WPC_ filters
    t = Transaction(doc, "Remove Wall Filters (WPC)")
    t.Start()
    try:
        _remove_wpc_filters_from_view(active_view)
        _delete_wpc_filter_elements()
        t.Commit()
    except Exception:
        try:
            t.RollBack()
        except Exception:
            pass
else:
    form = ColorizeForm()
    form.ShowDialog()
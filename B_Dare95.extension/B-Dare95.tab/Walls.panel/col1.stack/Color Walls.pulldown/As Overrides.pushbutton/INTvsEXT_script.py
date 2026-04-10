# -*- coding: utf-8 -*-
"""
Wall Parameter Colorizer
────────────────────────
Toggle Instance / Type parameters → pick a parameter → pick values →
assign a colour to each value → Apply.

Right-click the button → Reset (config mode).
"""

import clr
clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Drawing')

# ── Imports ───────────────────────────────────────────────────────────────────
# System.Drawing and Autodesk.Revit.DB both export 'Color' and 'Panel'.
# Import explicitly and alias to avoid silent shadowing.

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
from Autodesk.Revit.DB import (
    FilteredElementCollector, FillPatternElement,
    BuiltInCategory, OverrideGraphicSettings, Transaction,
    StorageType, ElementId,
    Color as RevitColor,
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

# ── Colour palette ────────────────────────────────────────────────────────────

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

# ── Revit helpers ─────────────────────────────────────────────────────────────

def _eid_str(eid):
    try:
        return str(eid.Value)        # Revit 2025+
    except AttributeError:
        return str(eid.IntegerValue) # Revit 2024 and earlier


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


def collect_params(use_type):
    """Return {param_name: sorted_value_list} for walls in the active view."""
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


# ── Form ──────────────────────────────────────────────────────────────────────

class ColorizeForm(Form):

    def __init__(self):
        Form.__init__(self)
        self.Text            = "Wall Parameter Colorizer"
        self.Size            = Size(900, 600)
        self.MinimumSize     = Size(700, 460)
        self.StartPosition   = FormStartPosition.CenterScreen
        self.FormBorderStyle = FormBorderStyle.Sizable

        # state
        self.param_data   = {}   # param_name -> [sorted value strings]
        self.check_order  = []   # insertion-ordered checked values
        self.checked_vals = set()
        self.val_colors   = {}   # val_str -> DrawingColor
        self._pal_idx     = 0
        self._val_to_row  = {}   # val_str -> dgv row index
        self._updating    = False

        self._build_ui()
        self._load_params()

    # ──────────────────────────────────────────────────────── UI construction ──

    def _build_ui(self):
        self.SuspendLayout()

        # ── helpers ───────────────────────────────────────────────────────────
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

        # ── SplitContainer ────────────────────────────────────────────────────
        # All sizing deferred to _on_load.
        split       = SplitContainer()
        split.Dock  = DockStyle.Fill
        self._split = split

        # ── LEFT: toggle + parameter combo + value list ───────────────────────
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

        # ── RIGHT: Colour Assignments via DataGridView ─────────────────────────
        # DataGridView owns its own scrolling, sizing, and painting entirely.
        # No manual layout panels, no AutoScroll fighting.

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
        self.dgv.ColumnHeadersHeightSizeMode = self.dgv.ColumnHeadersHeightSizeMode.DisableResizing
        self.dgv.ColumnHeadersHeight         = 26
        self.dgv.RowTemplate.Height          = 34
        self.dgv.BackgroundColor             = DrawingColor.White
        self.dgv.BorderStyle                 = self.dgv.BorderStyle.FixedSingle
        self.dgv.CellBorderStyle             = self.dgv.CellBorderStyle.SingleHorizontal
        self.dgv.GridColor                   = DrawingColor.FromArgb(220, 220, 220)

        # Column 0 — value name (stretches to fill most of width)
        col_val            = DataGridViewTextBoxColumn()
        col_val.HeaderText = "Value"
        col_val.FillWeight = 80
        col_val.SortMode   = DataGridViewColumnSortMode.NotSortable
        col_val.ReadOnly   = True

        # Column 1 — colour swatch (narrow fixed proportion)
        col_clr            = DataGridViewTextBoxColumn()
        col_clr.HeaderText = "Colour"
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
        self.Controls.Add(bp)      # Bottom first
        self.Controls.Add(split)   # Fill last

        self.Load += self._on_load
        self.ResumeLayout(True)

    # ──────────────────────────────────────────────────────── Form.Load ─────────

    def _on_load(self, s, e):
        """Set SplitContainer sizing only after layout resolves."""
        self._split.FixedPanel    = FixedPanel.Panel1
        self._split.Panel1MinSize = 260
        self._split.Panel2MinSize = 240
        w    = self._split.Width
        dist = max(260, min(420, w - 240 - self._split.SplitterWidth))
        self._split.SplitterDistance = dist

    # ──────────────────────────────────────────────────────── Data loading ──────

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

    # ──────────────────────────────────────────── DataGridView helpers ──────────

    def _dgv_add_row(self, val):
        """Append a row for val; paint its colour cell."""
        if val not in self.val_colors:
            self.val_colors[val] = PALETTE[self._pal_idx % len(PALETTE)]
            self._pal_idx += 1
        idx = self.dgv.Rows.Add(val, "")
        self._val_to_row[val] = idx
        self._dgv_colour_cell(idx, self.val_colors[val])

    def _dgv_colour_cell(self, row_idx, color):
        """Apply BackColor to the swatch cell so CellPainting can read it."""
        cell = self.dgv.Rows[row_idx].Cells[1]
        cell.Style.BackColor          = color
        cell.Style.SelectionBackColor = color

    def _dgv_rebuild(self):
        """Rebuild DGV entirely from check_order (used after an uncheck)."""
        self.dgv.Rows.Clear()
        self._val_to_row = {}
        for val in self.check_order:
            self._dgv_add_row(val)

    # ──────────────────────────────────────────────────────── Event handlers ────

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
        # ItemCheck fires BEFORE visual state changes; use e.NewValue.
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
        """Clicking the Colour column opens a ColorDialog."""
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
        # Draw the standard cell background (selection highlight etc.)
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

    # ─────────────────────────────────────────────────────── Apply / Reset ──────

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

        use_type  = self.rb_type.Checked
        reset_ogs = OverrideGraphicSettings()

        val_ogs = {}
        for val in self.checked_vals:
            col = self.val_colors.get(val)
            if col is None:
                continue
            ogs = OverrideGraphicSettings()
            rc  = RevitColor(col.R, col.G, col.B)
            ogs.SetSurfaceForegroundPatternId(solid_pattern.Id)
            ogs.SetSurfaceForegroundPatternColor(rc)
            ogs.SetCutForegroundPatternId(solid_pattern.Id)
            ogs.SetCutForegroundPatternColor(rc)
            val_ogs[val] = ogs

        t = Transaction(doc, "Colorize Walls - " + param_name)
        t.Start()
        try:
            for wall in all_walls:
                active_view.SetElementOverrides(wall.Id, reset_ogs)
                elem  = doc.GetElement(wall.GetTypeId()) if use_type else wall
                param = elem.LookupParameter(param_name)
                if param is None:
                    continue
                val = param_value_str(param)
                if val in val_ogs:
                    active_view.SetElementOverrides(wall.Id, val_ogs[val])
            t.Commit()
            MessageBox.Show(
                "Overrides applied ({} walls).".format(len(all_walls)),
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

    def _on_reset(self, s, e):
        reset_ogs = OverrideGraphicSettings()
        t = Transaction(doc, "Reset Wall Overrides")
        t.Start()
        try:
            for wall in all_walls:
                active_view.SetElementOverrides(wall.Id, reset_ogs)
            t.Commit()
            MessageBox.Show(
                "All wall overrides cleared.", "Done",
                MessageBoxButtons.OK, MessageBoxIcon.Information,
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
    reset_ogs = OverrideGraphicSettings()
    t = Transaction(doc, "Reset Wall Overrides")
    t.Start()
    for wall in all_walls:
        active_view.SetElementOverrides(wall.Id, reset_ogs)
    t.Commit()
else:
    form = ColorizeForm()
    form.ShowDialog()
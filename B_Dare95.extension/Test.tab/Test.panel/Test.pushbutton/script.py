# -*- coding: utf-8 -*-
"""
Wall Parameter Colorizer
────────────────────────
Lets the user pick any instance or type parameter on walls,
choose which values to colour, and assign a colour to each value —
all from a single WinForms dialog.

Right-click button  →  Reset overrides  (config mode)
"""

import clr
clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Drawing')

# ── Explicit imports to avoid name collisions ─────────────────────────────────
# Both System.Drawing AND Autodesk.Revit.DB export 'Color' and 'Panel'.
# We alias them here to keep things unambiguous throughout.

from System.Windows.Forms import (
    Form, SplitContainer, FixedPanel,
    FlowLayoutPanel, FlowDirection,         # still used for the bottom button bar
    Panel,                          # WinForms Panel (not Revit curtain Panel)
    GroupBox, RadioButton, Label,
    ComboBox, ComboBoxStyle, TextBox,
    CheckedListBox, CheckState,
    Button, FlatStyle, ColorDialog,
    DockStyle, Padding, FormStartPosition, FormBorderStyle,
    BorderStyle,
    MessageBox, MessageBoxButtons, MessageBoxIcon, DialogResult,
)
from System.Drawing import (
    Color  as DrawingColor,         # System.Drawing.Color  (WinForms / GDI+)
    Size, Point, Font, FontStyle, ContentAlignment,
)

from Autodesk.Revit.DB import (
    FilteredElementCollector, FillPatternElement,
    BuiltInCategory, OverrideGraphicSettings, Transaction,
    StorageType, ElementId,
    Color as RevitColor,            # Autodesk.Revit.DB.Color (for API overrides)
)
from pyrevit import EXEC_PARAMS

# ── Revit context ─────────────────────────────────────────────────────────────

uidoc       = __revit__.ActiveUIDocument
doc         = __revit__.ActiveUIDocument.Document
active_view = doc.ActiveView

# Solid-fill pattern (needed for SetSurface/CutForegroundPatternId)
_all_pats     = FilteredElementCollector(doc).OfClass(FillPatternElement).ToElements()
solid_pattern = next(p for p in _all_pats if p.GetFillPattern().IsSolidFill)

# Walls visible in the active view
all_walls = list(
    FilteredElementCollector(doc, active_view.Id)
    .OfCategory(BuiltInCategory.OST_Walls)
    .WhereElementIsNotElementType()
    .ToElements()
)

# ── Auto-colour palette ───────────────────────────────────────────────────────

PALETTE = [
    DrawingColor.FromArgb(230,  57,  70),   # red
    DrawingColor.FromArgb(255, 165,   0),   # orange
    DrawingColor.FromArgb(240, 215,  30),   # yellow
    DrawingColor.FromArgb( 42, 157, 143),   # teal
    DrawingColor.FromArgb( 67, 170, 239),   # sky-blue
    DrawingColor.FromArgb(132,  94, 194),   # purple
    DrawingColor.FromArgb(244, 114, 182),   # pink
    DrawingColor.FromArgb( 38, 200, 155),   # mint
    DrawingColor.FromArgb(200, 130,  60),   # brown
    DrawingColor.FromArgb(120, 144, 156),   # slate
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def _eid_str(eid):
    """
    Return a string representation of an ElementId.
    Revit 2025+ replaced IntegerValue (int) with Value (long).
    This helper tries both so the script works on 2024 and 2026+.
    """
    try:
        return str(eid.Value)           # Revit 2025+
    except AttributeError:
        return str(eid.IntegerValue)    # Revit 2024 and earlier


def param_value_str(param):
    """Convert any Revit parameter to a human-readable string."""
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
    """
    Walk either wall instances (use_type=False) or the unique wall types
    (use_type=True) that appear in the active view, and return:

        { param_name: sorted_list_of_unique_value_strings }

    Sorted alphabetically by name so the combo-box is easy to navigate.
    """
    pdata = {}

    if use_type:
        seen, elements = set(), []
        for w in all_walls:
            iid = _eid_str(w.GetTypeId())   # Value (2025+) or IntegerValue (≤2024)
            if iid not in seen:
                seen.add(iid)
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

        # ── Internal state ────────────────────────────────────────────────────
        self.param_data   = {}      # name  -> [sorted value strings]
        self.check_order  = []      # ordered list of checked value strings
        self.checked_vals = set()   # fast membership test
        self.val_colors   = {}      # val_str -> DrawingColor
        self._pal_idx     = 0       # cycles through PALETTE
        self._color_btns  = {}      # val_str -> colour-swatch Button
        self._updating    = False   # suppress re-entrant events

        self._build_ui()
        self._load_params()

    # ─────────────────────────────────────────── UI construction ─────────────

    def _build_ui(self):
        self.SuspendLayout()

        # ── helpers ───────────────────────────────────────────────────────────
        def mklbl(text, h=20):
            l        = Label()
            l.Text   = text
            l.Dock   = DockStyle.Top
            l.Height = h
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

        # ── 1. Bottom buttons ─────────────────────────────────────────────────
        bp               = FlowLayoutPanel()
        bp.Dock          = DockStyle.Bottom
        bp.Height        = 46
        bp.FlowDirection = FlowDirection.RightToLeft
        bp.WrapContents  = False
        bp.Padding       = Padding(8, 7, 8, 0)

        bp.Controls.Add(mk_btn("Cancel", self._on_cancel))
        bp.Controls.Add(mk_btn("Reset",  self._on_reset))
        bp.Controls.Add(mk_btn("Apply",  self._on_apply))

        # ── 3. SplitContainer (fills remaining space) ─────────────────────────
        split       = SplitContainer()
        split.Dock  = DockStyle.Fill
        self._split = split

        # ── LEFT side ─────────────────────────────────────────────────────────
        # Layout (top → bottom inside split.Panel1):
        #   [GroupBox: Parameter Source]   ← DockStyle.Top
        #   [lbl_param]                    ← DockStyle.Top
        #   [cb_param]                     ← DockStyle.Top
        #   [lbl_values]                   ← DockStyle.Top
        #   [lbl_search]                   ← DockStyle.Top
        #   [tb_search]                    ← DockStyle.Top
        #   [clb]                          ← DockStyle.Fill

        # GroupBox now lives inside Panel1, not on the form
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

        self.rb_type        = RadioButton()
        self.rb_type.Text   = "Type Parameters"
        self.rb_type.Left   = 192
        self.rb_type.Top    = 18
        self.rb_type.Width  = 150
        self.rb_type.Height = 24

        self.rb_inst.CheckedChanged += self._on_toggle
        self.rb_type.CheckedChanged += self._on_toggle
        grp.Controls.Add(self.rb_inst)
        grp.Controls.Add(self.rb_type)

        lp         = Panel()
        lp.Dock    = DockStyle.Fill
        lp.Padding = Padding(8, 6, 8, 6)

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

        lbl_search = mklbl("Search:")
        lbl_values = mklbl("Values:", h=26)
        lbl_param  = mklbl("Parameter:")

        lp.Controls.Add(lbl_param)
        lp.Controls.Add(self.cb_param)
        lp.Controls.Add(lbl_values)
        lp.Controls.Add(lbl_search)
        lp.Controls.Add(self.tb_search)
        lp.Controls.Add(self.clb)

        # GroupBox docks Top first, then lp fills the rest of Panel1
        split.Panel1.Controls.Add(grp)
        split.Panel1.Controls.Add(lp)

        # ── RIGHT side ────────────────────────────────────────────────────────
        rp         = Panel()
        rp.Dock    = DockStyle.Fill
        rp.Padding = Padding(8, 6, 8, 6)

        lbl_head           = Label()
        lbl_head.Text      = "Colour Assignments"
        lbl_head.Dock      = DockStyle.Top
        lbl_head.Height    = 22
        lbl_head.Font      = Font(self.Font, FontStyle.Bold)

        self.lbl_hint           = Label()
        self.lbl_hint.Text      = "Check values on the left to assign colours."
        self.lbl_hint.Dock      = DockStyle.Top
        self.lbl_hint.Height    = 20
        self.lbl_hint.ForeColor = DrawingColor.FromArgb(120, 120, 120)

        self.color_panel             = Panel()
        self.color_panel.Dock        = DockStyle.Fill
        self.color_panel.AutoScroll  = True
        self.color_panel.BorderStyle = BorderStyle.FixedSingle
        self.color_panel.Padding     = Padding(2)

        rp.Controls.Add(lbl_head)
        rp.Controls.Add(self.lbl_hint)
        rp.Controls.Add(self.color_panel)

        split.Panel2.Controls.Add(rp)

        # ── Assemble form (Bottom before Fill) ───────────────────────────────
        self.Controls.Add(bp)
        self.Controls.Add(split)

        self.Load += self._on_load
        self.ResumeLayout(True)

    # ───────────────────────────────────────── Form.Load handler ─────────────

    def _on_load(self, s, e):
        """
        Form.Load fires after layout — the SplitContainer has real pixel dims.

        Strategy: fix Panel1 at 420 px so the parameter list always has a
        comfortable width regardless of how wide the user stretches the form.
        Panel2 (colour assignments) gets all the extra space on resize.

        Order matters:
          1. FixedPanel    — must be set before SplitterDistance
          2. Panel1MinSize / Panel2MinSize
          3. SplitterDistance — validated last against real Width + both mins
        """
        self._split.FixedPanel    = FixedPanel.Panel1
        self._split.Panel1MinSize = 260
        self._split.Panel2MinSize = 240
        w    = self._split.Width
        # Clamp to a fixed 420 px left panel, respecting both minimums
        dist = max(260, min(420, w - 240 - self._split.SplitterWidth))
        self._split.SplitterDistance = dist

    # ───────────────────────────────────────────── Data loading ──────────────

    def _load_params(self):
        """Re-collect parameters for the current source mode and repopulate."""
        use_type        = self.rb_type.Checked
        self.param_data = collect_params(use_type)

        self._updating = True
        self.cb_param.Items.Clear()
        for name in self.param_data:
            self.cb_param.Items.Add(name)
        self._updating = False

        self._reset_state()

        if self.cb_param.Items.Count > 0:
            self.cb_param.SelectedIndex = 0   # triggers _on_param_changed

    def _reset_state(self):
        """Wipe all selection / colour state."""
        self.check_order  = []
        self.checked_vals = set()
        self.val_colors   = {}
        self._pal_idx     = 0
        self._color_btns  = {}
        self.color_panel.Controls.Clear()
        self.lbl_hint.Text    = "Check values on the left to assign colours."
        self.lbl_hint.Visible = True

    def _populate_values(self):
        """Rebuild the CheckedListBox for the current parameter + search text."""
        sel = self.cb_param.SelectedItem
        if sel is None:
            self.clb.Items.Clear()
            return

        all_vals = self.param_data.get(str(sel), [])
        search   = self.tb_search.Text.strip().lower()
        filtered = [v for v in all_vals if search in v.lower()] if search else all_vals

        # Detach event, repopulate (preserving checked state), reattach.
        self._updating = True
        self.clb.ItemCheck -= self._on_item_check
        self.clb.Items.Clear()
        for v in filtered:
            self.clb.Items.Add(v, v in self.checked_vals)
        self.clb.ItemCheck += self._on_item_check
        self._updating = False

    # ───────────────────────────────────────── Colour panel helpers ───────────

    ROW_H = 36   # height of each colour row in pixels
    ROW_G = 2    # gap between rows

    def _rebuild_color_panel(self):
        """Clear and redraw every row from check_order."""
        self.color_panel.Controls.Clear()
        self._color_btns = {}
        for val in self.check_order:
            self._add_color_row(val)
        # Prevent WinForms auto-scroll-to-last-child from hiding top rows
        self.color_panel.AutoScrollPosition = Point(0, 0)

    def _add_color_row(self, val):
        """
        Append one row to the colour panel using absolute Y positioning.
        DockStyle.Top rows inside an AutoScroll Panel don't contribute to the
        virtual scroll height, so the panel can't measure its own content and
        clips/hides early rows.  Absolute positioning avoids this entirely.
        """
        if val not in self.val_colors:
            self.val_colors[val] = PALETTE[self._pal_idx % len(PALETTE)]
            self._pal_idx += 1

        idx = len(self._color_btns)           # 0-based insertion index
        y   = idx * (self.ROW_H + self.ROW_G) + 2

        cw  = self.color_panel.ClientSize.Width
        pw  = max(cw - 8, 120)               # row width fits inside the panel

        row        = Panel()
        row.Left   = 4
        row.Top    = y
        row.Width  = pw
        row.Height = self.ROW_H

        swatch               = Button()
        swatch.Dock          = DockStyle.Right
        swatch.Width         = 60
        swatch.BackColor     = self.val_colors[val]
        swatch.FlatStyle     = FlatStyle.Flat
        swatch.FlatAppearance.BorderSize = 1

        val_lbl              = Label()
        val_lbl.Dock         = DockStyle.Fill
        val_lbl.Text         = val
        val_lbl.AutoEllipsis = True
        val_lbl.TextAlign    = ContentAlignment.MiddleLeft

        def make_handler(v, btn):
            def on_click(s, e):
                dlg = ColorDialog()
                dlg.Color = self.val_colors[v]
                if dlg.ShowDialog() == DialogResult.OK:
                    self.val_colors[v] = dlg.Color
                    btn.BackColor      = dlg.Color
            return on_click

        swatch.Click += make_handler(val, swatch)

        row.Controls.Add(swatch)
        row.Controls.Add(val_lbl)

        self.color_panel.Controls.Add(row)
        self._color_btns[val] = swatch
        # WinForms scrolls the panel to show the newly added control —
        # reset to top so earlier rows are never pushed out of view.
        self.color_panel.AutoScrollPosition = Point(0, 0)

    # ───────────────────────────────────────────── Event handlers ─────────────

    def _on_toggle(self, s, e):
        """Instance ↔ Type radio-button toggle."""
        # CheckedChanged fires for both buttons (old → unchecked, new → checked).
        # Only act on the newly-checked one.
        if self._updating or not s.Checked:
            return
        self._updating = True
        self.tb_search.Text = ""
        self._updating = False
        self._load_params()

    def _on_param_changed(self, s, e):
        """User chose a different parameter from the combo-box."""
        if self._updating:
            return
        self._updating = True
        self.tb_search.Text = ""
        self._updating = False
        self._reset_state()
        self._populate_values()

    def _on_search(self, s, e):
        """Search box text changed — filter the value list."""
        if self._updating:
            return
        self._populate_values()

    def _on_item_check(self, s, e):
        """
        CheckedListBox item is about to change state.
        Note: ItemCheck fires BEFORE the visual state changes,
        so e.NewValue tells us the incoming state.
        """
        if self._updating:
            return

        val = str(self.clb.Items[e.Index])

        if e.NewValue == CheckState.Checked:
            self.checked_vals.add(val)
            if val not in self.check_order:
                self.check_order.append(val)
            if val not in self._color_btns:
                self._add_color_row(val)
            self.lbl_hint.Visible = False
        else:
            self.checked_vals.discard(val)
            if val in self.check_order:
                self.check_order.remove(val)
            self._rebuild_color_panel()
            self.lbl_hint.Visible = (len(self.check_order) == 0)

    def _on_apply(self, s, e):
        """Apply graphic overrides to all walls in the active view."""
        if not self.checked_vals:
            MessageBox.Show(
                "Please check at least one value on the left.",
                "Nothing Selected",
                MessageBoxButtons.OK,
                MessageBoxIcon.Warning,
            )
            return

        param_name = str(self.cb_param.SelectedItem) if self.cb_param.SelectedItem else None
        if not param_name:
            return

        use_type  = self.rb_type.Checked
        reset_ogs = OverrideGraphicSettings()

        # Build a map: value string -> OverrideGraphicSettings
        val_ogs = {}
        for val in self.checked_vals:
            col = self.val_colors.get(val)
            if col is None:
                continue
            ogs = OverrideGraphicSettings()
            rc  = RevitColor(col.R, col.G, col.B)   # must use Revit's Color type
            ogs.SetSurfaceForegroundPatternId(solid_pattern.Id)
            ogs.SetSurfaceForegroundPatternColor(rc)
            ogs.SetCutForegroundPatternId(solid_pattern.Id)
            ogs.SetCutForegroundPatternColor(rc)
            val_ogs[val] = ogs

        t = Transaction(doc, "Colorize Walls — " + param_name)
        t.Start()
        try:
            for wall in all_walls:
                # Reset first so previously coloured walls don't linger
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
                "Colour overrides applied ({} walls processed).".format(len(all_walls)),
                "Done",
                MessageBoxButtons.OK,
                MessageBoxIcon.Information,
            )
        except Exception as ex:
            try:
                t.RollBack()
            except Exception:
                pass
            MessageBox.Show(
                "An error occurred:\n" + str(ex),
                "Error",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error,
            )

    def _on_reset(self, s, e):
        """Strip all graphic overrides from every wall in the active view."""
        reset_ogs = OverrideGraphicSettings()
        t = Transaction(doc, "Reset Wall Overrides")
        t.Start()
        try:
            for wall in all_walls:
                active_view.SetElementOverrides(wall.Id, reset_ogs)
            t.Commit()
            MessageBox.Show(
                "All wall overrides have been cleared.",
                "Done",
                MessageBoxButtons.OK,
                MessageBoxIcon.Information,
            )
        except Exception as ex:
            try:
                t.RollBack()
            except Exception:
                pass
            MessageBox.Show(
                "An error occurred:\n" + str(ex),
                "Error",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error,
            )

    def _on_cancel(self, s, e):
        self.Close()


# ── Entry point ───────────────────────────────────────────────────────────────

if EXEC_PARAMS.config_mode:
    # Right-click → "Reset overrides" without opening the dialog
    reset_ogs = OverrideGraphicSettings()
    t = Transaction(doc, "Reset Wall Overrides")
    t.Start()
    for wall in all_walls:
        active_view.SetElementOverrides(wall.Id, reset_ogs)
    t.Commit()
else:
    form = ColorizeForm()
    form.ShowDialog()
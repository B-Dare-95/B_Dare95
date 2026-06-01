# -*- coding: utf-8 -*-
__title__   = "Wall Peeler"
__doc__     = """Version = 2.0
Date    = 2025
________________________________________________________________
Description:
- Select a wall
- Choose which layers to split out via interactive plan-view UI
- Choose which wall (split or combined) hosts openings/doors/windows
- Remaining layers are combined into one wall
________________________________________________________________
Authors: Erik Frits / Mohamed Bedair / Joven Mark Gumana"""

# ╦╔╦╗╔═╗╔═╗╦═╗╔╦╗╔═╗
# ║║║║╠═╝║ ║╠╦╝ ║ ╚═╗
# ╩╩ ╩╩  ╚═╝╩╚═ ╩ ╚═╝
#====================================================================================================
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI.Selection import *
from pyrevit import forms

import clr
clr.AddReference('System')
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')

import System
from System                     import Action
from System.Collections.Generic import List
from System.Windows             import Window, WindowStartupLocation, SizeToContent, Thickness, \
                                       VerticalAlignment, HorizontalAlignment, Visibility, \
                                       GridLength, GridUnitType
from System.Windows.Controls    import Grid, RowDefinition, ColumnDefinition, Border, \
                                       StackPanel, Label, Button, ScrollViewer, \
                                       Orientation, TextBlock
from System.Windows.Media       import SolidColorBrush, Color, Brushes
from System.Windows.Threading   import Dispatcher, DispatcherFrame

# ╦  ╦╔═╗╦═╗╦╔═╗╔╗ ╦  ╔═╗╔═╗
# ╚╗╔╝╠═╣╠╦╝║╠═╣╠╩╗║  ║╣ ╚═╗
#  ╚╝ ╩ ╩╩╚═╩╩ ╩╚═╝╩═╝╚═╝╚═╝
#====================================================================================================
doc   = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
app   = __revit__.Application

# ╦ ╦╔═╗╦  ╔═╗╔═╗╦═╗╔═╗
# ╠═╣║╣ ║  ╠═╝║╣ ╠╦╝╚═╗
# ╩ ╩╚═╝╩═╝╩  ╚═╝╩╚═╚═╝  (ElementId.Value compat)
#====================================================================================================
def get_id_value(eid):
    try:
        return eid.Value          # Revit 2025+
    except AttributeError:
        return eid.IntegerValue   # Revit <= 2024


# ╔═╗╦  ╔═╗╔═╗╔═╗╔═╗╔═╗
# ║  ║  ╠═╣╚═╗╚═╗║╣ ╚═╗
# ╚═╝╩═╝╩ ╩╚═╝╚═╝╚═╝╚═╝
#====================================================================================================

class LayerData(object):
    """Holds display + Revit data for one compound structure layer."""
    def __init__(self, index, layer, doc):
        self.index    = index          # index in GetLayers() list
        self.layer    = layer          # CompoundStructureLayer
        self.is_cb    = (layer.Width == 0 and
                         layer.Function in (MaterialFunctionAssignment.StructuralAsset,
                                            MaterialFunctionAssignment.StructuralAsset)
                         ) if False else (layer.Width == 0)
        self.width    = layer.Width    # internal units (feet)
        self.func     = str(layer.Function)
        self.mat_name = 'Empty'
        self.color    = Color.FromRgb(200, 200, 200)  # fallback gray
        self.is_split = False

        if get_id_value(layer.MaterialId) != get_id_value(ElementId.InvalidElementId):
            mat = doc.GetElement(layer.MaterialId)
            if mat:
                self.mat_name = mat.Name
                # Use the material's cut pattern color (what Revit shows in plan section)
                c = mat.Color
                if c.IsValid:
                    self.color = Color.FromRgb(c.Red, c.Green, c.Blue)

        width_cm      = UnitUtils.ConvertFromInternalUnits(self.width, UnitTypeId.Centimeters)
        self.width_cm = width_cm
        self.label    = self.mat_name


def get_layer_func_label(layer):
    """Return a readable function label from the layer Function enum."""
    func_map = {
        MaterialFunctionAssignment.Structure          : 'Structure',
        MaterialFunctionAssignment.Substrate          : 'Substrate',
        MaterialFunctionAssignment.Insulation       : 'Thermal / Air',
        MaterialFunctionAssignment.Finish1            : 'Finish 1',
        MaterialFunctionAssignment.Finish2            : 'Finish 2',
        MaterialFunctionAssignment.Membrane      : 'Membrane',
        MaterialFunctionAssignment.StructuralDeck    : 'Structural Asset',
    }
    return func_map.get(layer.layer.Function, str(layer.layer.Function))


# ╦ ╦╔═╗╔═╗
# ║║║╠═╝╠╣
# ╚╩╝╩  ╚  (WPF UI)
#====================================================================================================

# ── Catppuccin Mocha palette ──────────────────────────────────────────────
C_BG      = Color.FromRgb(0x1E, 0x1E, 0x2E)
C_CARD    = Color.FromRgb(0x2A, 0x2A, 0x3C)
C_SURFACE = Color.FromRgb(0x31, 0x32, 0x44)
C_MUTED   = Color.FromRgb(0x45, 0x47, 0x5A)
C_TEXT    = Color.FromRgb(0xCD, 0xD6, 0xF4)
C_SUBTEXT = Color.FromRgb(0xA6, 0xAD, 0xC8)
C_ACCENT  = Color.FromRgb(0xF0, 0xA5, 0x00)

# Phase colors
C_SPLIT_BG     = Color.FromRgb(0x1A, 0x3A, 0x55)   # dark blue tint
C_SPLIT_BORDER = Color.FromRgb(0x37, 0x8A, 0xDD)
C_HOST_BG      = Color.FromRgb(0x0F, 0x35, 0x28)   # dark green tint
C_HOST_BORDER  = Color.FromRgb(0x1D, 0x9E, 0x75)
C_CB_BG        = Color.FromRgb(0x28, 0x28, 0x38)

def brush(color):
    return SolidColorBrush(color)

def blend(base_color, tint, t=0.5):
    """Blend base_color toward tint by factor t."""
    r = int(base_color.R * (1-t) + tint.R * t)
    g = int(base_color.G * (1-t) + tint.G * t)
    b = int(base_color.B * (1-t) + tint.B * t)
    return Color.FromRgb(r, g, b)

# Height scaling constants (pixels)
MIN_H = 26
MAX_H = 62
CB_H  = 14

def layer_height(width_internal, min_t, max_t):
    if width_internal == 0:
        return CB_H
    if max_t == min_t:
        return 38
    frac = (width_internal - min_t) / float(max_t - min_t)
    return int(MIN_H + frac * (MAX_H - MIN_H))


def make_label(text, font_size=12, color=None, bold=False, margin=None):
    lbl = TextBlock()
    lbl.Text     = text
    lbl.FontSize = font_size
    lbl.Foreground = brush(color if color else C_TEXT)
    if bold:
        from System.Windows import FontWeights
        lbl.FontWeight = FontWeights.SemiBold
    if margin:
        lbl.Margin = Thickness(*margin)
    lbl.VerticalAlignment = VerticalAlignment.Center
    return lbl


def make_swatch(color, size=13):
    b = Border()
    b.Width  = size
    b.Height = size
    b.Background = brush(color)
    b.CornerRadius = System.Windows.CornerRadius(2)
    b.BorderBrush     = brush(Color.FromArgb(60, 0, 0, 0))
    b.BorderThickness = Thickness(1)
    b.Margin = Thickness(0, 0, 6, 0)
    b.VerticalAlignment = VerticalAlignment.Center
    return b


class LayerPickerWindow(Window):

    def __init__(self, wall, layer_data_list):
        self.wall             = wall
        self.all_layers       = layer_data_list           # list[LayerData] incl CB rows
        self.real_layers      = [l for l in layer_data_list if not l.is_cb]
        self.phase            = 1
        self.host_key         = None     # string key = ','.join(str(idx) for idx in group_indices)
        self.confirmed        = [False]

        real_widths = [l.width for l in self.real_layers]
        self.min_t  = min(real_widths) if real_widths else 0
        self.max_t  = max(real_widths) if real_widths else 0

        self._build_window()

    # ── window shell ──────────────────────────────────────────────────────
    def _build_window(self):
        self.Title                  = "Wall Peeler"
        self.Width                  = 520
        self.SizeToContent          = SizeToContent.Height
        self.WindowStartupLocation  = WindowStartupLocation.CenterScreen
        self.Background             = brush(C_BG)
        self.ResizeMode             = System.Windows.ResizeMode.NoResize

        outer = StackPanel()
        outer.Margin = Thickness(16)

        # ── header ──
        header = StackPanel()
        header.Margin = Thickness(0, 0, 0, 10)

        title_row = Grid()
        title_row.ColumnDefinitions.Add(ColumnDefinition())
        cd = ColumnDefinition()
        cd.Width = GridLength(1, GridUnitType.Auto)
        title_row.ColumnDefinitions.Add(cd)

        title_lbl = make_label("Wall Peeler", 15, C_TEXT, bold=True)
        Grid.SetColumn(title_lbl, 0)
        title_row.Children.Add(title_lbl)

        self.phase_badge = Border()
        self.phase_badge.CornerRadius    = System.Windows.CornerRadius(99)
        self.phase_badge.Padding         = Thickness(10, 3, 10, 3)
        self.phase_badge.VerticalAlignment = VerticalAlignment.Center
        Grid.SetColumn(self.phase_badge, 1)
        self.phase_badge_text = make_label("", 11)
        self.phase_badge.Child = self.phase_badge_text
        title_row.Children.Add(self.phase_badge)
        header.Children.Add(title_row)

        self.instr_lbl = make_label("", 12, C_SUBTEXT)
        self.instr_lbl.Margin = Thickness(0, 6, 0, 0)
        self.instr_lbl.TextWrapping = System.Windows.TextWrapping.Wrap
        header.Children.Add(self.instr_lbl)
        outer.Children.Add(header)

        # ── legend ──
        legend = StackPanel()
        legend.Orientation = Orientation.Horizontal
        legend.Margin = Thickness(0, 0, 0, 10)
        for col, label_txt in [
            (Color.FromRgb(0x6C, 0x70, 0x86), "Keep"),
            (C_SPLIT_BORDER,                   "Split out"),
            (C_HOST_BORDER,                    "Host elements"),
        ]:
            item = StackPanel()
            item.Orientation = Orientation.Horizontal
            item.Margin = Thickness(0, 0, 14, 0)
            dot = Border()
            dot.Width  = 11
            dot.Height = 11
            dot.Background    = brush(col)
            dot.CornerRadius  = System.Windows.CornerRadius(2)
            dot.Margin        = Thickness(0, 0, 5, 0)
            dot.VerticalAlignment = VerticalAlignment.Center
            item.Children.Add(dot)
            item.Children.Add(make_label(label_txt, 12, C_SUBTEXT))
            legend.Children.Add(item)
        outer.Children.Add(legend)

        # ── section label ──
        sec = make_label("CROSS-SECTION — PLAN VIEW (EXTERIOR → INTERIOR)", 10, C_MUTED)
        sec.Margin = Thickness(0, 0, 0, 6)
        outer.Children.Add(sec)

        # ── wall canvas ──
        canvas_border = Border()
        canvas_border.Background      = brush(C_CARD)
        canvas_border.CornerRadius    = System.Windows.CornerRadius(8)
        canvas_border.Padding         = Thickness(10)
        canvas_border.Margin          = Thickness(0, 0, 0, 10)

        self.layer_stack = StackPanel()
        self.layer_stack.Orientation = Orientation.Vertical
        canvas_border.Child = self.layer_stack
        outer.Children.Add(canvas_border)

        # ── info box ──
        self.info_border = Border()
        self.info_border.CornerRadius    = System.Windows.CornerRadius(6)
        self.info_border.Padding         = Thickness(10, 7, 10, 7)
        self.info_border.Margin          = Thickness(0, 0, 0, 12)
        self.info_border.BorderThickness = Thickness(0, 0, 0, 0)
        self.info_lbl = make_label("", 12, C_SUBTEXT)
        self.info_lbl.TextWrapping = System.Windows.TextWrapping.Wrap
        self.info_border.Child = self.info_lbl
        outer.Children.Add(self.info_border)

        # ── buttons ──
        btn_row = StackPanel()
        btn_row.Orientation           = Orientation.Horizontal
        btn_row.HorizontalAlignment   = HorizontalAlignment.Right

        self.reset_btn   = self._make_btn("Reset",    self._on_reset,   accent=False)
        self.next_btn    = self._make_btn("Next  →",  self._on_next,    accent=True)
        self.confirm_btn = self._make_btn("Confirm",  self._on_confirm, accent=True)
        self.confirm_btn.Visibility = Visibility.Collapsed

        btn_row.Children.Add(self.reset_btn)
        btn_row.Children.Add(self.next_btn)
        btn_row.Children.Add(self.confirm_btn)
        outer.Children.Add(btn_row)

        self.Content = outer
        self._refresh()

    def _make_btn(self, text, handler, accent=False):
        btn = Button()
        btn.Content    = text
        btn.FontSize   = 13
        btn.Padding    = Thickness(18, 7, 18, 7)
        btn.Margin     = Thickness(8, 0, 0, 0)
        btn.Cursor     = System.Windows.Input.Cursors.Hand
        if accent:
            btn.Background = brush(Color.FromRgb(0x18, 0x5F, 0xA5))
            btn.Foreground = brush(Color.FromRgb(0xFF, 0xFF, 0xFF))
            btn.BorderBrush = brush(Color.FromRgb(0x18, 0x5F, 0xA5))
        else:
            btn.Background = brush(C_SURFACE)
            btn.Foreground = brush(C_TEXT)
            btn.BorderBrush = brush(C_MUTED)
        btn.BorderThickness = Thickness(1)

        # Rounded corners via style template workaround — set CornerRadius via border in template
        from System.Windows import Style
        from System.Windows.Controls import ControlTemplate
        # Simpler: wrap content in a border using the button's template override
        # For IronPython WPF, easiest is to just set border via XAML-like approach:
        btn.Tag = "rounded"
        btn.Click += handler

        # Apply corner radius via a Border wrapper trick by overriding template in code
        _apply_rounded_button_template(btn, accent)
        return btn

    # ── data helpers ──────────────────────────────────────────────────────
    def _get_groups(self):
        """Return ordered list of dicts: {type:'split'|'kept', indices:[...]}"""
        groups = []
        cur    = []
        for ld in self.real_layers:
            if ld.is_split:
                if cur:
                    groups.append({'type': 'kept', 'indices': list(cur)})
                    cur = []
                groups.append({'type': 'split', 'indices': [ld.index]})
            else:
                cur.append(ld.index)
        if cur:
            groups.append({'type': 'kept', 'indices': list(cur)})
        return groups

    def _group_key(self, group):
        return ','.join(str(i) for i in group['indices'])

    def _layer_by_index(self, idx):
        for ld in self.all_layers:
            if ld.index == idx:
                return ld
        return None

    # ── rendering ─────────────────────────────────────────────────────────
    def _refresh(self):
        self.layer_stack.Children.Clear()
        if self.phase == 1:
            self._render_phase1()
        else:
            self._render_phase2()
        self._refresh_header()

    def _render_phase1(self):
        for ld in self.all_layers:
            row = self._make_phase1_row(ld)
            self.layer_stack.Children.Add(row)

    def _make_phase1_row(self, ld):
        h = layer_height(ld.width, self.min_t, self.max_t)

        outer = Border()
        outer.Height          = h
        outer.CornerRadius    = System.Windows.CornerRadius(5)
        outer.Margin          = Thickness(0, 1, 0, 1)
        outer.BorderThickness = Thickness(2)
        outer.Cursor          = System.Windows.Input.Cursors.Arrow

        if ld.is_cb:
            outer.Background   = brush(C_CB_BG)
            outer.BorderBrush  = brush(C_CB_BG)
            inner = StackPanel()
            inner.Orientation = Orientation.Horizontal
            inner.Margin = Thickness(10, 0, 10, 0)
            inner.VerticalAlignment = VerticalAlignment.Center
            cb_lbl = make_label(ld.mat_name if ld.mat_name != 'Empty' else 'Core Boundary', 11, C_MUTED)
            inner.Children.Add(cb_lbl)
            outer.Child = inner
            return outer

        if ld.is_split:
            bg_col     = blend(ld.color, C_SPLIT_BG, 0.6)
            border_col = C_SPLIT_BORDER
        else:
            bg_col     = blend(ld.color, C_CARD, 0.15)
            border_col = C_MUTED

        outer.Background  = brush(bg_col)
        outer.BorderBrush = brush(border_col)
        outer.Cursor      = System.Windows.Input.Cursors.Hand

        # Left accent ribbon
        grid = Grid()
        col_ribbon = ColumnDefinition()
        col_ribbon.Width = GridLength(4)
        col_content = ColumnDefinition()
        grid.ColumnDefinitions.Add(col_ribbon)
        grid.ColumnDefinitions.Add(col_content)

        ribbon = Border()
        ribbon.Background = brush(C_SPLIT_BORDER if ld.is_split else Color.FromArgb(0,0,0,0))
        ribbon.CornerRadius = System.Windows.CornerRadius(3, 0, 0, 3)
        Grid.SetColumn(ribbon, 0)
        grid.Children.Add(ribbon)

        content = StackPanel()
        content.Orientation       = Orientation.Horizontal
        content.Margin            = Thickness(8, 0, 10, 0)
        content.VerticalAlignment = VerticalAlignment.Center
        Grid.SetColumn(content, 1)

        content.Children.Add(make_swatch(ld.color))
        content.Children.Add(make_label(ld.label, 12, C_TEXT, bold=True))
        content.Children.Add(make_label("  " + get_layer_func_label(ld), 11, C_SUBTEXT))

        thick_lbl = make_label("{:.2f} cm".format(ld.width_cm), 11, C_SUBTEXT)
        thick_lbl.HorizontalAlignment = HorizontalAlignment.Right
        thick_lbl.Margin = Thickness(0)

        # Use a stretching grid for right-align of thickness
        inner_grid = Grid()
        ic1 = ColumnDefinition()
        ic2 = ColumnDefinition()
        ic2.Width = GridLength(1, GridUnitType.Auto)
        inner_grid.ColumnDefinitions.Add(ic1)
        inner_grid.ColumnDefinitions.Add(ic2)
        Grid.SetColumn(content, 0)
        Grid.SetColumn(thick_lbl, 1)
        inner_grid.Children.Add(content)
        inner_grid.Children.Add(thick_lbl)
        Grid.SetColumn(inner_grid, 1)
        grid.Children.Add(inner_grid)

        outer.Child = grid

        # Click handler (capture ld in closure via default arg)
        def on_click(s, e, _ld=ld):
            _ld.is_split = not _ld.is_split
            self._refresh()

        outer.MouseLeftButtonUp += on_click
        return outer

    def _render_phase2(self):
        groups = self._get_groups()
        for group in groups:
            row = self._make_phase2_row(group)
            self.layer_stack.Children.Add(row)

    def _make_phase2_row(self, group):
        key     = self._group_key(group)
        is_host = (self.host_key == key)
        is_split_group = (group['type'] == 'split')

        indices = group['indices']
        layers  = [self._layer_by_index(i) for i in indices]
        layers  = [l for l in layers if l is not None]

        if not layers:
            return Border()

        total_w = sum(l.width for l in layers)

        if is_split_group:
            # Single layer row (same as phase1 appearance but host-aware)
            ld = layers[0]
            h  = layer_height(ld.width, self.min_t, self.max_t)

            outer = Border()
            outer.Height          = h
            outer.CornerRadius    = System.Windows.CornerRadius(5)
            outer.Margin          = Thickness(0, 1, 0, 1)
            outer.BorderThickness = Thickness(2)
            outer.Cursor          = System.Windows.Input.Cursors.Hand

            if is_host:
                bg_col     = blend(ld.color, C_HOST_BG, 0.65)
                border_col = C_HOST_BORDER
            else:
                bg_col     = blend(ld.color, C_SPLIT_BG, 0.6)
                border_col = C_SPLIT_BORDER

            outer.Background  = brush(bg_col)
            outer.BorderBrush = brush(border_col)

            grid = Grid()
            col_r = ColumnDefinition(); col_r.Width = GridLength(4)
            col_c = ColumnDefinition()
            grid.ColumnDefinitions.Add(col_r)
            grid.ColumnDefinitions.Add(col_c)

            ribbon = Border()
            ribbon.Background   = brush(C_HOST_BORDER if is_host else C_SPLIT_BORDER)
            ribbon.CornerRadius = System.Windows.CornerRadius(3, 0, 0, 3)
            Grid.SetColumn(ribbon, 0)
            grid.Children.Add(ribbon)

            content = StackPanel()
            content.Orientation       = Orientation.Horizontal
            content.Margin            = Thickness(8, 0, 10, 0)
            content.VerticalAlignment = VerticalAlignment.Center

            content.Children.Add(make_swatch(ld.color))
            content.Children.Add(make_label(ld.label, 12, C_TEXT, bold=True))
            content.Children.Add(make_label("  " + get_layer_func_label(ld), 11, C_SUBTEXT))

            thick_lbl = make_label("{:.2f} cm".format(ld.width_cm), 11, C_SUBTEXT)
            thick_lbl.HorizontalAlignment = HorizontalAlignment.Right

            inner_grid = Grid()
            inner_grid.ColumnDefinitions.Add(ColumnDefinition())
            ic2 = ColumnDefinition(); ic2.Width = GridLength(1, GridUnitType.Auto)
            inner_grid.ColumnDefinitions.Add(ic2)
            Grid.SetColumn(content, 0)
            Grid.SetColumn(thick_lbl, 1)
            inner_grid.Children.Add(content)
            inner_grid.Children.Add(thick_lbl)
            Grid.SetColumn(inner_grid, 1)
            grid.Children.Add(inner_grid)

            outer.Child = grid

        else:
            # Combined kept group — multi-segment bar
            total_h = max(layer_height(l.width, self.min_t, self.max_t) for l in layers)
            if len(layers) > 1:
                total_h = min(int(total_h * 1.12), MAX_H + 14)

            outer = Border()
            outer.Height          = total_h
            outer.CornerRadius    = System.Windows.CornerRadius(5)
            outer.Margin          = Thickness(0, 1, 0, 1)
            outer.BorderThickness = Thickness(2)
            outer.Cursor          = System.Windows.Input.Cursors.Hand

            border_col = C_HOST_BORDER if is_host else C_MUTED
            outer.BorderBrush = brush(border_col)

            # Segmented background grid
            seg_grid = Grid()
            for l in layers:
                cd = ColumnDefinition()
                cd.Width = GridLength(l.width, GridUnitType.Star)
                seg_grid.ColumnDefinitions.Add(cd)

            for ci, l in enumerate(layers):
                seg_bg = blend(l.color, C_HOST_BG, 0.55) if is_host else blend(l.color, C_CARD, 0.15)
                seg = Border()
                seg.Background = brush(seg_bg)
                if ci == 0:
                    seg.CornerRadius = System.Windows.CornerRadius(3, 0, 0, 3)
                elif ci == len(layers) - 1:
                    seg.CornerRadius = System.Windows.CornerRadius(0, 3, 3, 0)
                Grid.SetColumn(seg, ci)
                seg_grid.Children.Add(seg)

            # Overlay label
            overlay = Grid()
            col_r2 = ColumnDefinition(); col_r2.Width = GridLength(4)
            col_c2 = ColumnDefinition()
            overlay.ColumnDefinitions.Add(col_r2)
            overlay.ColumnDefinitions.Add(col_c2)

            ribbon2 = Border()
            ribbon2.Background   = brush(C_HOST_BORDER if is_host else Color.FromArgb(0,0,0,0))
            ribbon2.CornerRadius = System.Windows.CornerRadius(3, 0, 0, 3)
            Grid.SetColumn(ribbon2, 0)
            overlay.Children.Add(ribbon2)

            content2 = StackPanel()
            content2.Orientation       = Orientation.Horizontal
            content2.Margin            = Thickness(8, 0, 10, 0)
            content2.VerticalAlignment = VerticalAlignment.Center

            swatch_col = C_HOST_BORDER if is_host else C_MUTED
            content2.Children.Add(make_swatch(swatch_col))

            lbl_txt = "{} layers combined".format(len(layers)) if len(layers) > 1 else layers[0].label
            content2.Children.Add(make_label(lbl_txt, 12, C_TEXT, bold=True))

            total_cm = UnitUtils.ConvertFromInternalUnits(total_w, UnitTypeId.Centimeters)
            thick_lbl2 = make_label("{:.2f} cm".format(total_cm), 11, C_SUBTEXT)
            thick_lbl2.HorizontalAlignment = HorizontalAlignment.Right

            inner_grid2 = Grid()
            inner_grid2.ColumnDefinitions.Add(ColumnDefinition())
            ic2b = ColumnDefinition(); ic2b.Width = GridLength(1, GridUnitType.Auto)
            inner_grid2.ColumnDefinitions.Add(ic2b)
            Grid.SetColumn(content2, 0)
            Grid.SetColumn(thick_lbl2, 1)
            inner_grid2.Children.Add(content2)
            inner_grid2.Children.Add(thick_lbl2)
            Grid.SetColumn(inner_grid2, 1)
            overlay.Children.Add(inner_grid2)

            # Stack segments + overlay
            root_grid = Grid()
            root_grid.Children.Add(seg_grid)
            root_grid.Children.Add(overlay)
            outer.Child = root_grid

        # Click handler
        def on_click(s, e, _key=key):
            self.host_key = _key
            self._refresh()

        outer.MouseLeftButtonUp += on_click
        return outer

    def _refresh_header(self):
        split_count = sum(1 for l in self.real_layers if l.is_split)

        if self.phase == 1:
            self.phase_badge.Background = brush(Color.FromRgb(0x1A, 0x3A, 0x55))
            self.phase_badge_text.Text       = "Phase 1 — select layers to split"
            self.phase_badge_text.Foreground = brush(C_SPLIT_BORDER)
            self.instr_lbl.Text = "Click layers to mark them for splitting. Core Boundary rows are informational only."

            self.next_btn.Visibility    = Visibility.Visible
            self.confirm_btn.Visibility = Visibility.Collapsed
            self.next_btn.IsEnabled     = split_count > 0

            self.info_border.Background = brush(Color.FromRgb(0x1A, 0x2A, 0x3A))
            if split_count == 0:
                self.info_lbl.Text = "No layers selected — all layers will be kept as one wall."
            else:
                self.info_lbl.Text = "{} layer{} marked for splitting.".format(
                    split_count, 's' if split_count > 1 else '')
        else:
            self.phase_badge.Background = brush(Color.FromRgb(0x0A, 0x28, 0x1E))
            self.phase_badge_text.Text       = "Phase 2 — pick the host layer"
            self.phase_badge_text.Foreground = brush(C_HOST_BORDER)
            self.instr_lbl.Text = "Click any wall — split or combined — to designate it as the host for doors, windows, and openings."

            self.next_btn.Visibility    = Visibility.Collapsed
            self.confirm_btn.Visibility = Visibility.Visible
            self.confirm_btn.IsEnabled  = self.host_key is not None

            self.info_border.Background = brush(Color.FromRgb(0x0A, 0x28, 0x1E))
            if not self.host_key:
                self.info_lbl.Text = "No host selected yet. Any wall can be the host, including split-out layers."
            else:
                groups = self._get_groups()
                g = next((x for x in groups if self._group_key(x) == self.host_key), None)
                if g:
                    layers = [self._layer_by_index(i) for i in g['indices'] if self._layer_by_index(i)]
                    if g['type'] == 'split':
                        self.info_lbl.Text = 'Host: "{}" ({}) — split-out layer.'.format(
                            layers[0].label, get_layer_func_label(layers[0]))
                    elif len(layers) > 1:
                        total_cm = UnitUtils.ConvertFromInternalUnits(
                            sum(l.width for l in layers), UnitTypeId.Centimeters)
                        self.info_lbl.Text = "Host: combined wall ({} layers, {:.2f} cm total).".format(
                            len(layers), total_cm)
                    else:
                        self.info_lbl.Text = 'Host: "{}" ({}).'.format(
                            layers[0].label, get_layer_func_label(layers[0]))

    # ── button handlers ───────────────────────────────────────────────────
    def _on_reset(self, s, e):
        for ld in self.real_layers:
            ld.is_split = False
        self.phase    = 1
        self.host_key = None
        self._refresh()

    def _on_next(self, s, e):
        self.phase    = 2
        self.host_key = None
        self._refresh()

    def _on_confirm(self, s, e):
        self.confirmed[0] = True
        self.Close()

    # ── result accessors ──────────────────────────────────────────────────
    def get_result(self):
        """Returns (groups, host_key) after dialog closes."""
        return self._get_groups(), self.host_key


# ── Rounded button template helper ────────────────────────────────────────
import System.Windows.Markup as Markup

def _apply_rounded_button_template(btn, accent=False):
    bg_hex   = "#185FA5" if accent else "#313244"
    fg_hex   = "#FFFFFF" if accent else "#CDD6F4"
    hover_hex = "#0C447C" if accent else "#45475A"
    xaml = (
        '<ControlTemplate xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"'
        ' xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"'
        ' TargetType="Button">'
        '<Border x:Name="bd" Background="{}" CornerRadius="6"'
        ' BorderBrush="{}" BorderThickness="1">'
        '<ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>'
        '</Border>'
        '<ControlTemplate.Triggers>'
        '<Trigger Property="IsMouseOver" Value="True">'
        '<Setter TargetName="bd" Property="Background" Value="{}"/>'
        '</Trigger>'
        '<Trigger Property="IsEnabled" Value="False">'
        '<Setter TargetName="bd" Property="Opacity" Value="0.35"/>'
        '</Trigger>'
        '</ControlTemplate.Triggers>'
        '</ControlTemplate>'
    ).format(bg_hex, bg_hex, hover_hex)
    try:
        btn.Template = Markup.XamlReader.Parse(xaml)
        btn.Foreground = brush(Color.FromRgb(0xFF,0xFF,0xFF) if accent else C_TEXT)
    except:
        pass  # fallback to default button style if XAML parse fails


# ╦ ╦╔═╗╦  ╦     ╔═╗╔═╗╦  ╦╦╔╦╗
# ║║║╠═╣║  ║     ╚═╗╠═╝║  ║ ║
# ╚╩╝╩ ╩╩═╝╩═╝  ╚═╝╩  ╩═╝╩ ╩
#====================================================================================================

def pick_wall():
    class WallFilter(ISelectionFilter):
        def AllowElement(self, elem):
            return elem.Category is not None and elem.Category.Name == "Walls"
        def AllowReference(self, ref, point):
            return False
    try:
        ref  = uidoc.Selection.PickObject(ObjectType.Element, WallFilter(), "Select Wall to Peel")
        return doc.GetElement(ref)
    except:
        forms.alert("No wall selected. Exiting.", exitscript=True)


def build_layer_data(wall):
    """Build LayerData list from wall's compound structure."""
    raw_layers = wall.WallType.GetCompoundStructure().GetLayers()
    result     = []
    for i, layer in enumerate(raw_layers):
        ld       = LayerData(i, layer, doc)
        # Override is_cb: zero-width layers are always Core Boundary display rows
        ld.is_cb = (layer.Width == 0)
        result.append(ld)
    return result


def get_wall_type_by_name(name):
    rvt_year = int(app.VersionNumber)
    pvp      = ParameterValueProvider(ElementId(BuiltInParameter.ALL_MODEL_TYPE_NAME))
    cond     = FilterStringEquals()
    rule     = FilterStringRule(pvp, cond, name, True) if rvt_year < 2022 \
          else FilterStringRule(pvp, cond, name)
    return FilteredElementCollector(doc).OfClass(WallType) \
               .WherePasses(ElementParameterFilter(rule)).FirstElement()


def make_wall_type_for_group(base_wall_type, group_layers, group_label):
    """
    Get or create a WallType whose compound structure matches the given layers
    (in original order). group_layers is a list of LayerData.
    """
    # Build a name from the layers
    parts = []
    for ld in group_layers:
        cm = "{:.1f}".format(ld.width_cm).rstrip('0').rstrip('.')
        parts.append("{} ({}cm)".format(ld.label, cm))
    type_name = " - ".join(parts)
    if len(type_name) > 100:
        type_name = type_name[:97] + "..."

    existing = get_wall_type_by_name(type_name)
    if existing:
        return existing

    new_type = base_wall_type.Duplicate(type_name)
    raw_layers_for_group = [ld.layer for ld in group_layers]
    compound = CompoundStructure.CreateSimpleCompoundStructure(raw_layers_for_group)
    new_type.SetCompoundStructure(compound)
    return new_type


def get_hosted_elements(wall):
    dep_ids = wall.GetDependentElements(None)
    result  = []
    for eid in dep_ids:
        el = doc.GetElement(eid)
        if el is not None and el.Category is not None:
            result.append(el)
    return result


def duplicate_wall(wall, keep_hosted):
    ids     = List[ElementId]([wall.Id])
    new_ids = ElementTransformUtils.CopyElements(doc, ids, XYZ(0, 0, 0))
    new_w   = doc.GetElement(new_ids[0])
    if keep_hosted:
        return new_w
    for el in get_hosted_elements(new_w):
        if not isinstance(el, Wall):
            doc.Delete(el.Id)
    return new_w


def compute_offset(wall, group_layers, all_real_layers):
    """
    Compute the XY offset from the original wall's location line to the
    centerline of the new wall formed by group_layers.

    all_real_layers : list[LayerData] of ALL non-CB layers in order (exterior→interior)
    group_layers    : list[LayerData] subset belonging to this group
    """
    cs           = wall.WallType.GetCompoundStructure()
    loc_line_enum = WallLocationLine(
        wall.get_Parameter(BuiltInParameter.WALL_KEY_REF_PARAM).AsInteger())
    loc_line_offset = cs.GetOffsetForLocationLine(loc_line_enum)
    # loc_line_offset = distance from location line to exterior face

    # Find where this group starts in the full layer stack
    start_thickness = 0.0
    first_idx = all_real_layers.index(group_layers[0])
    for ld in all_real_layers[:first_idx]:
        start_thickness += ld.width

    group_thickness = sum(ld.width for ld in group_layers)
    # Center of this group from the exterior face
    group_center_from_ext = start_thickness + group_thickness / 2.0

    # Offset from the location line to this group's center
    offset = group_center_from_ext - loc_line_offset

    if wall.Flipped:
        offset = -offset

    return offset


def join_walls(wall_list):
    for w1 in wall_list:
        for w2 in wall_list:
            if w1.Id != w2.Id:
                try:
                    JoinGeometryUtils.JoinGeometry(doc, w1, w2)
                except:
                    pass


# ╔╦╗╔═╗╦╔╗╔
# ║║║╠═╣║║║║
# ╩ ╩╩ ╩╩╝╚╝
#====================================================================================================

# 1. Pick wall (before transaction — needs UI interaction)
sel_wall = pick_wall()

# 2. Build layer data
layer_data = build_layer_data(sel_wall)
real_layers = [ld for ld in layer_data if not ld.is_cb]

if not real_layers:
    forms.alert("Wall has no real layers to split.", exitscript=True)

# 3. Show WPF picker (modeless pattern with PushFrame)
win         = LayerPickerWindow(sel_wall, layer_data)
frame       = [DispatcherFrame()]

def on_closed(s, e):
    frame[0].Continue = False

win.Closed += on_closed
win.Show()
Dispatcher.PushFrame(frame[0])

# 4. Check if user confirmed
if not win.confirmed[0]:
    import sys
    sys.exit(0)

groups, host_key = win.get_result()

if not groups:
    forms.alert("Nothing to do.", exitscript=True)

# If only one kept group and no splits, nothing to do
if len(groups) == 1 and groups[0]['type'] == 'kept':
    forms.alert("No layers were selected for splitting. Nothing to do.", exitscript=True)

# 5. Execute inside transaction
t = Transaction(doc, "Wall Peeler — Split Layers")
t.Start()

new_walls  = []
base_type  = sel_wall.WallType

for group in groups:
    group_lds   = [next(ld for ld in real_layers if ld.index == i) for i in group['indices']]
    is_host     = (host_key == ','.join(str(i) for i in group['indices']))
    keep_hosted = is_host

    # Build / get wall type for this group
    new_type = make_wall_type_for_group(base_type, group_lds, group['type'])

    # Compute location line offset
    offset       = compute_offset(sel_wall, group_lds, real_layers)
    offset_curve = sel_wall.Location.Curve.CreateOffset(offset, XYZ.BasisZ)

    # Duplicate wall (preserves all instance parameters)
    new_wall = duplicate_wall(sel_wall, keep_hosted)
    new_wall.WallType            = new_type
    new_wall.Location.Curve      = offset_curve

    new_walls.append(new_wall)

# Join all new walls so openings cut correctly
join_walls(new_walls)

# Delete the original wall
doc.Delete(sel_wall.Id)

t.Commit()
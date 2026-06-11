# -*- coding: utf-8 -*-
__title__   = "Wall Peeler"
__doc__     = """Version = 4.0
Date    = 2025
________________________________________________________________
Description:
- Select a wall
- Phase 1 : click layers to mark for splitting
            link-button between adjacent split layers groups them
- Phase 2 : pick which resulting wall hosts doors / openings
- Phase 3 : rename each resulting wall type before creation
- Walls land at geometrically correct positions
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
from System.Collections.Generic import List
from System.Windows import (Window, WindowStartupLocation, SizeToContent,
                             Thickness, VerticalAlignment, HorizontalAlignment,
                             Visibility, GridLength, GridUnitType, FontWeights,
                             Rect as WpfRect, Point as WpfPoint)
from System.Windows.Controls import (Grid, ColumnDefinition, Border, StackPanel,
                                      Button, Orientation, TextBlock, ScrollViewer,
                                      TextBox)
from System.Windows.Media import (SolidColorBrush, Color,
                                   DrawingBrush, DrawingGroup, GeometryDrawing,
                                   Pen, TileMode, BrushMappingMode,
                                   LineGeometry, EllipseGeometry, GeometryGroup,
                                   RectangleGeometry)
from System.Windows.Threading import Dispatcher, DispatcherFrame
import System.Windows.Markup as Markup

# ╦  ╦╔═╗╦═╗╦╔═╗╔╗ ╦  ╔═╗╔═╗
# ╚╗╔╝╠═╣╠╦╝║╠═╣╠╩╗║  ║╣ ╚═╗
#  ╚╝ ╩ ╩╩╚═╩╩ ╩╚═╝╩═╝╚═╝╚═╝
#====================================================================================================
doc   = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
app   = __revit__.Application

# ╦ ╦╔═╗╦  ╔═╗╔═╗╦═╗╔═╗
# ╠═╣║╣ ║  ╠═╝║╣ ╠╦╝╚═╗
# ╩ ╩╚═╝╩═╝╩  ╚═╝╩╚═╚═╝
#====================================================================================================
def get_id_value(eid):
    try:
        return eid.Value
    except AttributeError:
        return eid.IntegerValue


# ╔═╗╦  ╔═╗╔═╗╔═╗╔═╗╔═╗
# ║  ║  ╠═╣╚═╗╚═╗║╣ ╚═╗
# ╚═╝╩═╝╩ ╩╚═╝╚═╝╚═╝╚═╝  DATA
#====================================================================================================

FUNC_PATTERN = {
    MaterialFunctionAssignment.Finish1       : 'diagonal',
    MaterialFunctionAssignment.Finish2       : 'diagonal',
    MaterialFunctionAssignment.Substrate     : 'dots',
    MaterialFunctionAssignment.Insulation    : 'waves',
    MaterialFunctionAssignment.Membrane      : 'solid',
    MaterialFunctionAssignment.Structure     : 'crosshatch',
    MaterialFunctionAssignment.StructuralDeck: 'crosshatch',
}

FUNC_LABEL = {
    MaterialFunctionAssignment.Structure     : 'Structure',
    MaterialFunctionAssignment.Substrate     : 'Substrate',
    MaterialFunctionAssignment.Insulation    : 'Thermal / Air',
    MaterialFunctionAssignment.Finish1       : 'Finish 1',
    MaterialFunctionAssignment.Finish2       : 'Finish 2',
    MaterialFunctionAssignment.Membrane      : 'Membrane',
    MaterialFunctionAssignment.StructuralDeck: 'Structural Deck',
}


class LayerData(object):
    def __init__(self, index, layer, doc):
        self.index     = index
        self.layer     = layer
        self.is_cb     = (layer.Width == 0)
        self.width     = layer.Width
        self.func_enum = layer.Function
        self.mat_name  = 'Empty'
        self.color     = Color.FromRgb(180, 180, 180)
        self.is_split  = False
        self.pattern   = FUNC_PATTERN.get(layer.Function, 'diagonal')

        if get_id_value(layer.MaterialId) != get_id_value(ElementId.InvalidElementId):
            mat = doc.GetElement(layer.MaterialId)
            if mat:
                self.mat_name = mat.Name
                c = mat.Color
                if c.IsValid:
                    self.color = Color.FromRgb(c.Red, c.Green, c.Blue)

        self.width_cm = UnitUtils.ConvertFromInternalUnits(self.width, UnitTypeId.Centimeters)
        self.label    = self.mat_name

    def func_label(self):
        return FUNC_LABEL.get(self.func_enum, str(self.func_enum))


# ╔═╗╔═╗╦  ╔═╗╦ ╦╦═╗╔═╗  ╔═╗╔═╗╦  ╔═╗╔╦╗╔╦╗╔═╗
# ║  ║ ║║  ║ ║║ ║╠╦╝╚═╗  ╠═╝╠═╣║  ║╣  ║  ║ ║╣
# ╚═╝╚═╝╩═╝╚═╝╚═╝╩╚═╚═╝  ╩  ╩ ╩╩═╝╚═╝ ╩  ╩ ╚═╝  PALETTE
#====================================================================================================
C_BG           = Color.FromRgb(0x1E, 0x1E, 0x2E)
C_CARD         = Color.FromRgb(0x2A, 0x2A, 0x3C)
C_SURFACE      = Color.FromRgb(0x31, 0x32, 0x44)
C_MUTED        = Color.FromRgb(0x45, 0x47, 0x5A)
C_TEXT         = Color.FromRgb(0xCD, 0xD6, 0xF4)
C_SUBTEXT      = Color.FromRgb(0xA6, 0xAD, 0xC8)
C_ACCENT       = Color.FromRgb(0xF0, 0xA5, 0x00)
C_SPLIT_BG     = Color.FromRgb(0x1A, 0x3A, 0x55)
C_SPLIT_BORDER = Color.FromRgb(0x37, 0x8A, 0xDD)
C_HOST_BG      = Color.FromRgb(0x0F, 0x35, 0x28)
C_HOST_BORDER  = Color.FromRgb(0x1D, 0x9E, 0x75)
C_CB_BG        = Color.FromRgb(0x28, 0x28, 0x38)
C_PILL_BG      = Color.FromArgb(0xD0, 0x1E, 0x1E, 0x2E)

MIN_H = 28
MAX_H = 64
CB_H  = 13


def brush(color):
    return SolidColorBrush(color)


def blend(base, tint, t=0.5):
    return Color.FromRgb(
        int(base.R * (1 - t) + tint.R * t),
        int(base.G * (1 - t) + tint.G * t),
        int(base.B * (1 - t) + tint.B * t),
    )


def layer_height(w, min_t, max_t):
    if w == 0:    return CB_H
    if max_t == min_t: return 38
    return int(MIN_H + (w - min_t) / float(max_t - min_t) * (MAX_H - MIN_H))


# ── Hatch DrawingBrush factory ────────────────────────────────────────────
def _darker(color, factor=0.45):
    return Color.FromRgb(int(color.R * factor),
                         int(color.G * factor),
                         int(color.B * factor))


def draw_hatch_brush(pattern, base_color):
    line_color = _darker(base_color, 0.45)
    line_pen   = Pen(brush(line_color), 0.8)
    line_pen.Freeze()

    dg = DrawingGroup()

    bg = GeometryDrawing()
    bg.Brush    = brush(base_color)
    bg.Geometry = RectangleGeometry(WpfRect(0, 0, 8, 8))
    dg.Children.Add(bg)

    if pattern == 'diagonal':
        fg = GeometryDrawing(); fg.Pen = line_pen
        gg = GeometryGroup()
        gg.Children.Add(LineGeometry(WpfPoint(0, 8), WpfPoint(8, 0)))
        fg.Geometry = gg; dg.Children.Add(fg)

    elif pattern == 'crosshatch':
        fg = GeometryDrawing(); fg.Pen = line_pen
        gg = GeometryGroup()
        gg.Children.Add(LineGeometry(WpfPoint(0, 8), WpfPoint(8, 0)))
        gg.Children.Add(LineGeometry(WpfPoint(0, 0), WpfPoint(8, 8)))
        fg.Geometry = gg; dg.Children.Add(fg)

    elif pattern == 'dots':
        fg = GeometryDrawing()
        fg.Brush    = brush(line_color)
        fg.Geometry = EllipseGeometry(WpfPoint(4, 4), 1.0, 1.0)
        dg.Children.Add(fg)

    elif pattern == 'waves':
        fg = GeometryDrawing(); fg.Pen = line_pen
        gg = GeometryGroup()
        gg.Children.Add(LineGeometry(WpfPoint(0, 4), WpfPoint(4, 0)))
        gg.Children.Add(LineGeometry(WpfPoint(4, 8), WpfPoint(8, 4)))
        fg.Geometry = gg; dg.Children.Add(fg)

    # 'solid' → background only
    dg.Freeze()

    db = DrawingBrush()
    db.Drawing       = dg
    db.TileMode      = TileMode.Tile
    db.ViewportUnits = BrushMappingMode.Absolute
    db.ViewboxUnits  = BrushMappingMode.Absolute
    db.Viewbox       = WpfRect(0, 0, 8, 8)
    db.Viewport      = WpfRect(0, 0, 8, 8)
    db.Freeze()
    return db


# ── Small UI helpers ──────────────────────────────────────────────────────
def make_text(text, size=12, color=None, bold=False):
    t = TextBlock()
    t.Text              = text
    t.FontSize          = size
    t.Foreground        = brush(color if color else C_TEXT)
    t.VerticalAlignment = VerticalAlignment.Center
    if bold: t.FontWeight = FontWeights.SemiBold
    return t


def make_swatch(color, size=11):
    b = Border()
    b.Width             = size
    b.Height            = size
    b.Background        = brush(color)
    b.CornerRadius      = System.Windows.CornerRadius(2)
    b.BorderBrush       = brush(Color.FromArgb(80, 0, 0, 0))
    b.BorderThickness   = Thickness(1)
    b.Margin            = Thickness(0, 0, 5, 0)
    b.VerticalAlignment = VerticalAlignment.Center
    return b


def make_pill(children_list):
    """Semi-opaque dark pill — text always readable over hatch backgrounds."""
    pill = Border()
    pill.Background        = brush(C_PILL_BG)
    pill.CornerRadius      = System.Windows.CornerRadius(4)
    pill.Padding           = Thickness(6, 2, 6, 2)
    pill.VerticalAlignment = VerticalAlignment.Center
    pill.IsHitTestVisible  = False
    sp = StackPanel()
    sp.Orientation = Orientation.Horizontal
    for child in children_list:
        sp.Children.Add(child)
    pill.Child = sp
    return pill


def _apply_rounded_btn_template(btn, accent=False):
    bg_hex    = "#185FA5" if accent else "#313244"
    hover_hex = "#0C447C" if accent else "#45475A"
    xaml = (
        '<ControlTemplate'
        ' xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"'
        ' xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"'
        ' TargetType="Button">'
        '<Border x:Name="bd" Background="{bg}" CornerRadius="6"'
        ' BorderBrush="{bg}" BorderThickness="1">'
        '<ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>'
        '</Border>'
        '<ControlTemplate.Triggers>'
        '<Trigger Property="IsMouseOver" Value="True">'
        '<Setter TargetName="bd" Property="Background" Value="{hv}"/>'
        '</Trigger>'
        '<Trigger Property="IsEnabled" Value="False">'
        '<Setter TargetName="bd" Property="Opacity" Value="0.35"/>'
        '</Trigger>'
        '</ControlTemplate.Triggers>'
        '</ControlTemplate>'
    ).replace('{bg}', bg_hex).replace('{hv}', hover_hex)
    try:
        btn.Template   = Markup.XamlReader.Parse(xaml)
        btn.Foreground = brush(Color.FromRgb(0xFF, 0xFF, 0xFF) if accent else C_TEXT)
    except:
        pass


def _make_textbox_style():
    """Return XAML-parsed Style for a dark-themed TextBox."""
    xaml = (
        '<Style xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"'
        '       TargetType="TextBox">'
        '<Setter Property="Background"   Value="#313244"/>'
        '<Setter Property="Foreground"   Value="#CDD6F4"/>'
        '<Setter Property="BorderBrush"  Value="#45475A"/>'
        '<Setter Property="BorderThickness" Value="1"/>'
        '<Setter Property="Padding"      Value="6,4,6,4"/>'
        '<Setter Property="FontSize"     Value="12"/>'
        '<Setter Property="CaretBrush"   Value="#CDD6F4"/>'
        '<Setter Property="SelectionBrush" Value="#378ADD"/>'
        '<Style.Triggers>'
        '<Trigger Property="IsFocused" Value="True">'
        '<Setter Property="BorderBrush" Value="#378ADD"/>'
        '</Trigger>'
        '</Style.Triggers>'
        '</Style>'
    )
    try:
        return Markup.XamlReader.Parse(xaml)
    except:
        return None


# ╦ ╦╔═╗╔═╗
# ║║║╠═╝╠╣
# ╚╩╝╩  ╚   WPF Window
#====================================================================================================

class LayerPickerWindow(Window):

    def __init__(self, wall, layer_data_list):
        self.wall        = wall
        self.all_layers  = layer_data_list
        self.real_layers = [l for l in layer_data_list if not l.is_cb]
        self.phase       = 1    # 1 = split selection, 2 = host pick, 3 = rename
        self.host_key    = None
        self.confirmed   = [False]
        self.link_set    = set()   # "i,j" pairs of linked adjacent split layers
        # phase-3 state: group_key -> TextBox widget  (populated in _render_phase3)
        self._name_boxes = {}
        # cached auto-names per group key, built when entering phase 3
        self._auto_names = {}

        ws = [l.width for l in self.real_layers]
        self.min_t = min(ws) if ws else 0
        self.max_t = max(ws) if ws else 0

        self._tb_style = _make_textbox_style()
        self._build_window()

    # ─────────────────────────────────────────────────────────────────────
    # Window shell
    # ─────────────────────────────────────────────────────────────────────
    def _build_window(self):
        self.Title                 = "Wall Peeler"
        self.Width                 = 560
        self.SizeToContent         = SizeToContent.Height
        self.WindowStartupLocation = WindowStartupLocation.CenterScreen
        self.Background            = brush(C_BG)
        self.ResizeMode            = System.Windows.ResizeMode.NoResize

        outer = StackPanel()
        outer.Margin = Thickness(16)

        # Title row
        title_row = Grid()
        title_row.Margin = Thickness(0, 0, 0, 4)
        title_row.ColumnDefinitions.Add(ColumnDefinition())
        auto_cd = ColumnDefinition(); auto_cd.Width = GridLength(1, GridUnitType.Auto)
        title_row.ColumnDefinitions.Add(auto_cd)

        title_lbl = make_text("Wall Peeler", 15, C_TEXT, bold=True)
        Grid.SetColumn(title_lbl, 0)
        title_row.Children.Add(title_lbl)

        self.phase_badge      = Border()
        self.phase_badge.CornerRadius      = System.Windows.CornerRadius(99)
        self.phase_badge.Padding           = Thickness(10, 3, 10, 3)
        self.phase_badge.VerticalAlignment = VerticalAlignment.Center
        self.phase_badge_text              = make_text("", 11)
        self.phase_badge.Child             = self.phase_badge_text
        Grid.SetColumn(self.phase_badge, 1)
        title_row.Children.Add(self.phase_badge)
        outer.Children.Add(title_row)

        self.instr_lbl             = make_text("", 12, C_SUBTEXT)
        self.instr_lbl.Margin      = Thickness(0, 0, 0, 10)
        self.instr_lbl.TextWrapping = System.Windows.TextWrapping.Wrap
        outer.Children.Add(self.instr_lbl)

        # Legend (hidden in phase 3)
        self.legend_panel = StackPanel()
        self.legend_panel.Orientation = Orientation.Horizontal
        self.legend_panel.Margin      = Thickness(0, 0, 0, 10)
        for col, txt in [
            (Color.FromRgb(0x6C, 0x70, 0x86), "Keep"),
            (C_SPLIT_BORDER,                   "Split out"),
            (C_ACCENT,                         "Grouped split"),
            (C_HOST_BORDER,                    "Host elements"),
        ]:
            item = StackPanel(); item.Orientation = Orientation.Horizontal
            item.Margin = Thickness(0, 0, 12, 0)
            dot = Border()
            dot.Width = 10; dot.Height = 10
            dot.Background = brush(col)
            dot.CornerRadius = System.Windows.CornerRadius(2)
            dot.Margin = Thickness(0, 0, 4, 0)
            dot.VerticalAlignment = VerticalAlignment.Center
            item.Children.Add(dot)
            item.Children.Add(make_text(txt, 11, C_SUBTEXT))
            self.legend_panel.Children.Add(item)
        outer.Children.Add(self.legend_panel)

        self.sec_lbl        = make_text("CROSS-SECTION — PLAN VIEW  (EXTERIOR → INTERIOR)", 10, C_MUTED)
        self.sec_lbl.Margin = Thickness(0, 0, 0, 6)
        outer.Children.Add(self.sec_lbl)

        # Scrollable canvas
        scroll = ScrollViewer()
        scroll.MaxHeight = 460
        scroll.VerticalScrollBarVisibility   = System.Windows.Controls.ScrollBarVisibility.Auto
        scroll.HorizontalScrollBarVisibility = System.Windows.Controls.ScrollBarVisibility.Disabled
        scroll.Margin = Thickness(0, 0, 0, 10)

        canvas_border = Border()
        canvas_border.Background   = brush(C_CARD)
        canvas_border.CornerRadius = System.Windows.CornerRadius(8)
        canvas_border.Padding      = Thickness(10)

        self.layer_stack             = StackPanel()
        self.layer_stack.Orientation = Orientation.Vertical
        canvas_border.Child          = self.layer_stack
        scroll.Content               = canvas_border
        outer.Children.Add(scroll)

        # Info box
        self.info_border = Border()
        self.info_border.CornerRadius    = System.Windows.CornerRadius(6)
        self.info_border.Padding         = Thickness(10, 7, 10, 7)
        self.info_border.Margin          = Thickness(0, 0, 0, 12)
        self.info_border.BorderThickness = Thickness(0)
        self.info_lbl                    = make_text("", 12, C_SUBTEXT)
        self.info_lbl.TextWrapping       = System.Windows.TextWrapping.Wrap
        self.info_border.Child           = self.info_lbl
        outer.Children.Add(self.info_border)

        # Buttons
        btn_row = StackPanel()
        btn_row.Orientation         = Orientation.Horizontal
        btn_row.HorizontalAlignment = HorizontalAlignment.Right

        self.reset_btn   = self._make_btn("Reset",    self._on_reset,   accent=False)
        self.next_btn    = self._make_btn("Next  →",  self._on_next,    accent=True)
        self.confirm_btn = self._make_btn("Confirm",  self._on_confirm, accent=True)
        self.confirm_btn.Visibility = Visibility.Collapsed

        for b in [self.reset_btn, self.next_btn, self.confirm_btn]:
            btn_row.Children.Add(b)
        outer.Children.Add(btn_row)

        self.Content = outer
        self._refresh()

    def _make_btn(self, text, handler, accent=False):
        btn = Button()
        btn.Content   = text
        btn.FontSize  = 13
        btn.Padding   = Thickness(18, 7, 18, 7)
        btn.Margin    = Thickness(8, 0, 0, 0)
        btn.Cursor    = System.Windows.Input.Cursors.Hand
        btn.Click    += handler
        _apply_rounded_btn_template(btn, accent)
        return btn

    # ─────────────────────────────────────────────────────────────────────
    # Group / link helpers
    # ─────────────────────────────────────────────────────────────────────
    def _get_groups(self):
        """
        Ordered list of {type, indices} dicts.
        Linked adjacent split layers are merged (union-find).
        """
        split_indices = [ld.index for ld in self.real_layers if ld.is_split]
        parent = {i: i for i in split_indices}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a, b):
            parent[find(a)] = find(b)

        for key in self.link_set:
            parts = key.split(',')
            a, b = int(parts[0]), int(parts[1])
            if a in parent and b in parent:
                union(a, b)

        groups          = []
        kept_buf        = []
        open_split_roots = {}

        for ld in self.real_layers:
            if not ld.is_split:
                kept_buf.append(ld.index)
            else:
                if kept_buf:
                    groups.append({'type': 'kept', 'indices': list(kept_buf)})
                    kept_buf = []
                root = find(ld.index)
                if root in open_split_roots:
                    open_split_roots[root]['indices'].append(ld.index)
                else:
                    g = {'type': 'split', 'indices': [ld.index]}
                    groups.append(g)
                    open_split_roots[root] = g

        if kept_buf:
            groups.append({'type': 'kept', 'indices': list(kept_buf)})
        return groups

    def _group_key(self, group):
        return ','.join(str(i) for i in group['indices'])

    def _layer_by_index(self, idx):
        for ld in self.all_layers:
            if ld.index == idx:
                return ld
        return None

    def _get_link_zones(self):
        zones     = []
        split_set = set(ld.index for ld in self.real_layers if ld.is_split)
        for k in range(len(self.real_layers) - 1):
            a_ld = self.real_layers[k]
            b_ld = self.real_layers[k + 1]
            if a_ld.index in split_set and b_ld.index in split_set:
                key = '{},{}'.format(a_ld.index, b_ld.index)
                zones.append({'a': a_ld.index, 'b': b_ld.index,
                               'key': key, 'active': key in self.link_set})
        return zones

    def _auto_name_for_group(self, group):
        """Build the default type name for a group from its layers."""
        lyrs = [self._layer_by_index(i) for i in group['indices'] if self._layer_by_index(i)]
        parts = []
        for ld in lyrs:
            cm = '{:.1f}'.format(ld.width_cm).rstrip('0').rstrip('.')
            parts.append('{} ({}cm)'.format(ld.label, cm))
        name = ' - '.join(parts)
        return name[:100] + ('...' if len(name) > 100 else '')

    # ─────────────────────────────────────────────────────────────────────
    # Rendering dispatcher
    # ─────────────────────────────────────────────────────────────────────
    def _refresh(self):
        self.layer_stack.Children.Clear()
        if   self.phase == 1: self._render_phase1()
        elif self.phase == 2: self._render_phase2()
        else:                 self._render_phase3()
        self._refresh_header()

    # ─────────────────────────────────────────────────────────────────────
    # Phase 1 – split / link selection
    # ─────────────────────────────────────────────────────────────────────
    def _render_phase1(self):
        link_zones = self._get_link_zones()
        link_map   = {z['key']: z for z in link_zones}
        linked_top = set()
        linked_bot = set()
        for z in link_zones:
            if z['active']:
                linked_bot.add(z['a'])
                linked_top.add(z['b'])

        for ld in self.all_layers:
            if ld.is_cb:
                self.layer_stack.Children.Add(self._make_cb_divider())
                continue

            is_linked = ld.index in linked_top or ld.index in linked_bot
            row = self._make_p1_layer_row(ld, is_linked,
                                           ld.index in linked_top,
                                           ld.index in linked_bot)
            self.layer_stack.Children.Add(row)

            real_idx = self.real_layers.index(ld)
            if real_idx < len(self.real_layers) - 1:
                next_ld  = self.real_layers[real_idx + 1]
                zone_key = '{},{}'.format(ld.index, next_ld.index)
                zone     = link_map.get(zone_key)
                if zone:
                    self.layer_stack.Children.Add(self._make_link_connector(zone))
                else:
                    sp = Border(); sp.Height = 2
                    self.layer_stack.Children.Add(sp)

    def _make_cb_divider(self):
        row = Grid(); row.Height = 14; row.Margin = Thickness(0, 1, 0, 1)
        cd1 = ColumnDefinition()
        cd2 = ColumnDefinition(); cd2.Width = GridLength(1, GridUnitType.Auto)
        cd3 = ColumnDefinition()
        row.ColumnDefinitions.Add(cd1)
        row.ColumnDefinitions.Add(cd2)
        row.ColumnDefinitions.Add(cd3)

        def make_line():
            b = Border(); b.Height = 1; b.Background = brush(C_MUTED)
            b.VerticalAlignment = VerticalAlignment.Center; b.Opacity = 0.5
            return b

        lbl = make_text("Core Boundary", 9, C_MUTED); lbl.Margin = Thickness(6, 0, 6, 0)
        l1 = make_line(); l2 = make_line()
        Grid.SetColumn(l1, 0); Grid.SetColumn(lbl, 1); Grid.SetColumn(l2, 2)
        row.Children.Add(l1); row.Children.Add(lbl); row.Children.Add(l2)
        return row

    def _make_p1_layer_row(self, ld, is_linked, linked_top, linked_bot):
        h = layer_height(ld.width, self.min_t, self.max_t)

        if ld.is_split and is_linked: border_col = C_ACCENT
        elif ld.is_split:              border_col = C_SPLIT_BORDER
        else:                          border_col = C_MUTED

        outer = Border()
        outer.Height = h; outer.Margin = Thickness(0, 1, 0, 1)
        outer.CornerRadius = System.Windows.CornerRadius(5)
        outer.BorderThickness = Thickness(2); outer.BorderBrush = brush(border_col)
        outer.Cursor = System.Windows.Input.Cursors.Hand; outer.ClipToBounds = True
        outer.Background = draw_hatch_brush(ld.pattern, ld.color)

        if   ld.is_split and is_linked: tint_col = Color.FromArgb(100, C_ACCENT.R,    C_ACCENT.G,    C_ACCENT.B)
        elif ld.is_split:               tint_col = Color.FromArgb(90,  C_SPLIT_BG.R,  C_SPLIT_BG.G,  C_SPLIT_BG.B)
        else:                           tint_col = Color.FromArgb(0,   0,             0,             0)

        root = Grid()
        col_r = ColumnDefinition(); col_r.Width = GridLength(4)
        root.ColumnDefinitions.Add(col_r)
        root.ColumnDefinitions.Add(ColumnDefinition())

        if tint_col.A > 0:
            tint = Border(); tint.Background = brush(tint_col)
            Grid.SetColumnSpan(tint, 2); root.Children.Add(tint)

        if linked_top:
            tl = Border(); tl.Height = 2; tl.Background = brush(C_ACCENT)
            tl.VerticalAlignment = VerticalAlignment.Top
            Grid.SetColumnSpan(tl, 2); root.Children.Add(tl)

        if linked_bot:
            bl = Border(); bl.Height = 2; bl.Background = brush(C_ACCENT)
            bl.VerticalAlignment = VerticalAlignment.Bottom
            Grid.SetColumnSpan(bl, 2); root.Children.Add(bl)

        ribbon = Border()
        if   ld.is_split and is_linked: ribbon.Background = brush(C_ACCENT)
        elif ld.is_split:               ribbon.Background = brush(C_SPLIT_BORDER)
        else:                           ribbon.Background = brush(Color.FromArgb(0, 0, 0, 0))
        ribbon.CornerRadius = System.Windows.CornerRadius(3, 0, 0, 3)
        Grid.SetColumn(ribbon, 0); root.Children.Add(ribbon)

        pill = make_pill([
            make_swatch(ld.color),
            make_text(ld.label, 12, C_TEXT, bold=True),
            make_text("  " + ld.func_label(), 11, C_SUBTEXT),
            make_text("  {:.1f} cm".format(ld.width_cm), 11, C_SUBTEXT),
        ])
        pill.HorizontalAlignment = HorizontalAlignment.Right
        pill.Margin = Thickness(0, 0, 8, 0)
        Grid.SetColumn(pill, 1); root.Children.Add(pill)

        outer.Child = root

        def on_click(s, e, _ld=ld):
            _ld.is_split = not _ld.is_split
            if not _ld.is_split:
                to_rm = [k for k in self.link_set if str(_ld.index) in k.split(',')]
                for k in to_rm: self.link_set.discard(k)
            self._refresh()

        outer.MouseLeftButtonUp += on_click
        return outer

    def _make_link_connector(self, zone):
        is_active = zone['active']

        container = Grid(); container.Height = 20

        line = Border(); line.Width = 2
        line.Background = brush(C_ACCENT if is_active else C_MUTED)
        line.HorizontalAlignment = HorizontalAlignment.Center; line.Opacity = 0.6
        container.Children.Add(line)

        btn_b = Border()
        btn_b.Width = 22; btn_b.Height = 22
        btn_b.CornerRadius = System.Windows.CornerRadius(11)
        btn_b.BorderThickness = Thickness(1.5)
        btn_b.HorizontalAlignment = HorizontalAlignment.Center
        btn_b.VerticalAlignment   = VerticalAlignment.Center
        btn_b.Cursor = System.Windows.Input.Cursors.Hand
        if is_active:
            btn_b.Background  = brush(Color.FromRgb(0x2A, 0x22, 0x18))
            btn_b.BorderBrush = brush(C_ACCENT)
        else:
            btn_b.Background  = brush(C_SURFACE)
            btn_b.BorderBrush = brush(C_MUTED)

        icon = make_text(u"\U0001F517", 10)
        icon.HorizontalAlignment = HorizontalAlignment.Center
        icon.VerticalAlignment   = VerticalAlignment.Center
        btn_b.Child = icon
        container.Children.Add(btn_b)

        def on_link(s, e, _zone=zone):
            e.Handled = True
            if _zone['key'] in self.link_set: self.link_set.discard(_zone['key'])
            else:                             self.link_set.add(_zone['key'])
            self._refresh()

        btn_b.MouseLeftButtonUp += on_link
        return container

    # ─────────────────────────────────────────────────────────────────────
    # Phase 2 – host selection
    # ─────────────────────────────────────────────────────────────────────
    def _render_phase2(self):
        for group in self._get_groups():
            self.layer_stack.Children.Add(self._make_p2_row(group))
            sp = Border(); sp.Height = 2
            self.layer_stack.Children.Add(sp)

    def _make_p2_row(self, group):
        key     = self._group_key(group)
        is_host = (self.host_key == key)
        lyrs    = [self._layer_by_index(i) for i in group['indices']
                   if self._layer_by_index(i)]
        if not lyrs: return Border()

        is_split_group  = (group['type'] == 'split')
        is_linked_group = is_split_group and len(lyrs) > 1
        total_w  = sum(l.width for l in lyrs)
        total_cm = UnitUtils.ConvertFromInternalUnits(total_w, UnitTypeId.Centimeters)

        def click_handler(s, e, _key=key):
            self.host_key = _key; self._refresh()

        if is_split_group and not is_linked_group:
            ld = lyrs[0]
            h  = layer_height(ld.width, self.min_t, self.max_t)
            outer = self._make_hatch_row_border(h, ld,
                        C_HOST_BORDER if is_host else C_SPLIT_BORDER,
                        C_HOST_BG     if is_host else C_SPLIT_BG)
            outer.MouseLeftButtonUp += click_handler
            return outer

        elif is_linked_group:
            border_col = C_HOST_BORDER if is_host else C_ACCENT
            outer = Border()
            outer.Margin = Thickness(0, 1, 0, 1)
            outer.CornerRadius = System.Windows.CornerRadius(5)
            outer.BorderThickness = Thickness(2); outer.BorderBrush = brush(border_col)
            outer.Cursor = System.Windows.Input.Cursors.Hand; outer.ClipToBounds = True

            inner_stack = StackPanel(); inner_stack.Orientation = Orientation.Vertical
            for li, ld in enumerate(lyrs):
                h = layer_height(ld.width, self.min_t, self.max_t)
                seg = self._make_hatch_row_border(h, ld, border_col,
                          C_HOST_BG if is_host else C_ACCENT,
                          margin=False)
                inner_stack.Children.Add(seg)
                if li < len(lyrs) - 1:
                    div = Border(); div.Height = 1
                    div.Background = brush(Color.FromArgb(120, border_col.R, border_col.G, border_col.B))
                    inner_stack.Children.Add(div)

            badge_txt = "Grouped — {} layers  ({:.1f} cm)".format(len(lyrs), total_cm)
            badge = make_pill([make_text(badge_txt, 10,
                                C_HOST_BORDER if is_host else C_ACCENT, bold=True)])
            badge.HorizontalAlignment = HorizontalAlignment.Center
            badge.VerticalAlignment   = VerticalAlignment.Top
            badge.Margin = Thickness(0, 4, 0, 0)

            wrapper = Grid()
            wrapper.Children.Add(inner_stack); wrapper.Children.Add(badge)
            outer.Child = wrapper
            outer.MouseLeftButtonUp += click_handler
            return outer

        else:
            # Kept combined group – proportional segmented bar
            total_h = max(layer_height(l.width, self.min_t, self.max_t) for l in lyrs)
            if len(lyrs) > 1: total_h = min(int(total_h * 1.1) + 4, MAX_H + 16)

            outer = Border()
            outer.Height = total_h; outer.Margin = Thickness(0, 1, 0, 1)
            outer.CornerRadius = System.Windows.CornerRadius(5)
            outer.BorderThickness = Thickness(2)
            outer.BorderBrush = brush(C_HOST_BORDER if is_host else C_MUTED)
            outer.Cursor = System.Windows.Input.Cursors.Hand; outer.ClipToBounds = True

            seg_grid = Grid()
            for l in lyrs:
                cd = ColumnDefinition(); cd.Width = GridLength(l.width, GridUnitType.Star)
                seg_grid.ColumnDefinitions.Add(cd)
            for ci, l in enumerate(lyrs):
                seg = Border()
                seg.Background = draw_hatch_brush(l.pattern, l.color)
                if   ci == 0:             seg.CornerRadius = System.Windows.CornerRadius(3, 0, 0, 3)
                elif ci == len(lyrs) - 1: seg.CornerRadius = System.Windows.CornerRadius(0, 3, 3, 0)
                Grid.SetColumn(seg, ci); seg_grid.Children.Add(seg)

            if is_host:
                host_tint = Border()
                host_tint.Background = brush(Color.FromArgb(70, C_HOST_BG.R, C_HOST_BG.G, C_HOST_BG.B))
                Grid.SetColumnSpan(host_tint, max(len(lyrs), 1))
                seg_grid.Children.Add(host_tint)

            overlay = Grid()
            col_r = ColumnDefinition(); col_r.Width = GridLength(4)
            overlay.ColumnDefinitions.Add(col_r)
            overlay.ColumnDefinitions.Add(ColumnDefinition())

            ribbon = Border()
            ribbon.Background   = brush(C_HOST_BORDER if is_host else Color.FromArgb(0,0,0,0))
            ribbon.CornerRadius = System.Windows.CornerRadius(3, 0, 0, 3)
            Grid.SetColumn(ribbon, 0); overlay.Children.Add(ribbon)

            lbl_txt = "{} layers combined".format(len(lyrs)) if len(lyrs) > 1 else lyrs[0].label
            pill = make_pill([
                make_swatch(C_HOST_BORDER if is_host else C_MUTED),
                make_text(lbl_txt, 12, C_TEXT, bold=True),
                make_text("  {:.1f} cm".format(total_cm), 11, C_SUBTEXT),
            ])
            pill.HorizontalAlignment = HorizontalAlignment.Right
            pill.Margin = Thickness(0, 0, 8, 0)
            Grid.SetColumn(pill, 1); overlay.Children.Add(pill)

            root_grid = Grid()
            root_grid.Children.Add(seg_grid); root_grid.Children.Add(overlay)
            outer.Child = root_grid
            outer.MouseLeftButtonUp += click_handler
            return outer

    def _make_hatch_row_border(self, h, ld, border_col, tint_bg, margin=True):
        """Single-layer hatch row used in phase 2 and phase 3 previews."""
        outer = Border()
        outer.Height = h
        if margin: outer.Margin = Thickness(0, 1, 0, 1)
        outer.CornerRadius    = System.Windows.CornerRadius(5)
        outer.BorderThickness = Thickness(2); outer.BorderBrush = brush(border_col)
        outer.Cursor = System.Windows.Input.Cursors.Hand; outer.ClipToBounds = True
        outer.Background = draw_hatch_brush(ld.pattern, ld.color)

        root = Grid()
        col_r = ColumnDefinition(); col_r.Width = GridLength(4)
        root.ColumnDefinitions.Add(col_r)
        root.ColumnDefinitions.Add(ColumnDefinition())

        tint = Border()
        tint.Background = brush(Color.FromArgb(90, tint_bg.R, tint_bg.G, tint_bg.B))
        Grid.SetColumnSpan(tint, 2); root.Children.Add(tint)

        ribbon = Border(); ribbon.Background = brush(border_col)
        ribbon.CornerRadius = System.Windows.CornerRadius(3, 0, 0, 3)
        Grid.SetColumn(ribbon, 0); root.Children.Add(ribbon)

        pill = make_pill([
            make_swatch(ld.color),
            make_text(ld.label, 12, C_TEXT, bold=True),
            make_text("  " + ld.func_label(), 11, C_SUBTEXT),
            make_text("  {:.1f} cm".format(ld.width_cm), 11, C_SUBTEXT),
        ])
        pill.HorizontalAlignment = HorizontalAlignment.Right
        pill.Margin = Thickness(0, 0, 8, 0)
        Grid.SetColumn(pill, 1); root.Children.Add(pill)

        outer.Child = root
        return outer

    # ─────────────────────────────────────────────────────────────────────
    # Phase 3 – rename resulting walls
    # ─────────────────────────────────────────────────────────────────────
    def _render_phase3(self):
        """
        For each output group show:
          - a compact read-only hatch preview (same visual language as phases 1/2)
          - a host badge if this is the host group
          - a TextBox pre-filled with the auto-generated type name
        """
        self._name_boxes = {}
        groups = self._get_groups()

        for gi, group in enumerate(groups):
            key     = self._group_key(group)
            is_host = (self.host_key == key)
            lyrs    = [self._layer_by_index(i) for i in group['indices']
                       if self._layer_by_index(i)]
            if not lyrs: continue

            is_split_group = (group['type'] == 'split')
            total_w  = sum(l.width for l in lyrs)
            total_cm = UnitUtils.ConvertFromInternalUnits(total_w, UnitTypeId.Centimeters)

            # Outer card for this group
            card = Border()
            card.Background     = brush(C_SURFACE)
            card.CornerRadius   = System.Windows.CornerRadius(7)
            card.Padding        = Thickness(10, 8, 10, 10)
            card.Margin         = Thickness(0, 0, 0, 8)
            card.BorderThickness = Thickness(1)
            if is_host:
                card.BorderBrush = brush(C_HOST_BORDER)
            elif is_split_group and len(lyrs) > 1:
                card.BorderBrush = brush(C_ACCENT)
            elif is_split_group:
                card.BorderBrush = brush(C_SPLIT_BORDER)
            else:
                card.BorderBrush = brush(C_MUTED)

            card_inner = StackPanel(); card_inner.Orientation = Orientation.Vertical

            # ── header row: label + host badge ──
            hdr = Grid()
            hdr.Margin = Thickness(0, 0, 0, 6)
            hdr.ColumnDefinitions.Add(ColumnDefinition())
            auto_c = ColumnDefinition(); auto_c.Width = GridLength(1, GridUnitType.Auto)
            hdr.ColumnDefinitions.Add(auto_c)

            if is_split_group and len(lyrs) > 1:
                grp_txt = "Grouped wall  ({} layers, {:.1f} cm)".format(len(lyrs), total_cm)
                grp_col = C_ACCENT
            elif is_split_group:
                grp_txt = "Split wall  ({:.1f} cm)".format(total_cm)
                grp_col = C_SPLIT_BORDER
            else:
                grp_txt = "Combined wall  ({} layer{}, {:.1f} cm)".format(
                    len(lyrs), 's' if len(lyrs) != 1 else '', total_cm)
                grp_col = C_SUBTEXT

            grp_lbl = make_text(grp_txt, 11, grp_col, bold=True)
            Grid.SetColumn(grp_lbl, 0); hdr.Children.Add(grp_lbl)

            if is_host:
                host_badge = Border()
                host_badge.Background   = brush(Color.FromRgb(0x0A, 0x28, 0x1E))
                host_badge.BorderBrush  = brush(C_HOST_BORDER)
                host_badge.BorderThickness = Thickness(1)
                host_badge.CornerRadius = System.Windows.CornerRadius(99)
                host_badge.Padding      = Thickness(8, 2, 8, 2)
                host_badge.VerticalAlignment = VerticalAlignment.Center
                host_badge_txt = make_text(u"\u2693 Host", 10, C_HOST_BORDER, bold=True)
                host_badge.Child = host_badge_txt
                Grid.SetColumn(host_badge, 1); hdr.Children.Add(host_badge)

            card_inner.Children.Add(hdr)

            # ── compact hatch preview ──
            if len(lyrs) == 1:
                ld = lyrs[0]
                h  = max(layer_height(ld.width, self.min_t, self.max_t), MIN_H)
                border_col = C_HOST_BORDER if is_host else (C_SPLIT_BORDER if is_split_group else C_MUTED)
                tint_bg    = C_HOST_BG     if is_host else (C_SPLIT_BG     if is_split_group else C_CARD)
                preview = self._make_hatch_row_border(h, ld, border_col, tint_bg, margin=False)
                preview.Cursor = System.Windows.Input.Cursors.Arrow
                preview.Margin = Thickness(0, 0, 0, 8)
                card_inner.Children.Add(preview)
            else:
                # Horizontal segmented preview strip
                strip_h = 36
                border_col = C_HOST_BORDER if is_host else (C_ACCENT if is_split_group else C_MUTED)

                strip_outer = Border()
                strip_outer.Height = strip_h
                strip_outer.CornerRadius = System.Windows.CornerRadius(4)
                strip_outer.BorderThickness = Thickness(2); strip_outer.BorderBrush = brush(border_col)
                strip_outer.ClipToBounds = True; strip_outer.Margin = Thickness(0, 0, 0, 8)

                seg_grid = Grid()
                for l in lyrs:
                    cd = ColumnDefinition(); cd.Width = GridLength(l.width, GridUnitType.Star)
                    seg_grid.ColumnDefinitions.Add(cd)
                for ci, l in enumerate(lyrs):
                    seg = Border(); seg.Background = draw_hatch_brush(l.pattern, l.color)
                    Grid.SetColumn(seg, ci); seg_grid.Children.Add(seg)

                # Label overlay
                lbl_overlay = StackPanel()
                lbl_overlay.Orientation = Orientation.Horizontal
                lbl_overlay.VerticalAlignment = VerticalAlignment.Center
                lbl_overlay.Margin = Thickness(8, 0, 8, 0)
                lbl_overlay.IsHitTestVisible = False

                for l in lyrs:
                    lbl_overlay.Children.Add(make_swatch(l.color, 9))

                total_lbl_txt = "{} layers  |  {:.1f} cm total".format(len(lyrs), total_cm)
                lbl_overlay.Children.Add(make_pill([make_text(total_lbl_txt, 10, C_TEXT)]))

                strip_root = Grid()
                strip_root.Children.Add(seg_grid); strip_root.Children.Add(lbl_overlay)
                strip_outer.Child = strip_root
                card_inner.Children.Add(strip_outer)

            # ── name label + TextBox ──
            name_lbl = make_text("Wall Type Name", 11, C_SUBTEXT)
            name_lbl.Margin = Thickness(0, 0, 0, 4)
            card_inner.Children.Add(name_lbl)

            auto_name = self._auto_names.get(key, self._auto_name_for_group(group))
            self._auto_names[key] = auto_name

            tb = TextBox()
            tb.Text                    = auto_name
            tb.AcceptsReturn           = False
            tb.VerticalContentAlignment = VerticalAlignment.Center
            if self._tb_style: tb.Style = self._tb_style
            tb.Margin = Thickness(0)
            self._name_boxes[key] = tb
            card_inner.Children.Add(tb)

            card.Child = card_inner
            self.layer_stack.Children.Add(card)

    # ─────────────────────────────────────────────────────────────────────
    # Header / info refresh
    # ─────────────────────────────────────────────────────────────────────
    def _refresh_header(self):
        split_count = sum(1 for l in self.real_layers if l.is_split)

        if self.phase == 1:
            self.phase_badge.Background      = brush(Color.FromRgb(0x1A, 0x3A, 0x55))
            self.phase_badge_text.Text       = "Phase 1 — select layers to split"
            self.phase_badge_text.Foreground = brush(C_SPLIT_BORDER)
            self.instr_lbl.Text = (
                "Click layers to mark them for splitting. "
                u"When two adjacent split layers appear, use the \U0001F517 connector to group them into one wall."
            )
            self.legend_panel.Visibility = Visibility.Visible
            self.sec_lbl.Visibility      = Visibility.Visible
            self.next_btn.Visibility     = Visibility.Visible
            self.confirm_btn.Visibility  = Visibility.Collapsed
            self.next_btn.Content        = "Next  \u2192"
            self.next_btn.IsEnabled      = split_count > 0

            self.info_border.Background = brush(Color.FromRgb(0x1A, 0x2A, 0x3A))
            self.info_lbl.Foreground    = brush(C_SUBTEXT)
            if split_count == 0:
                self.info_lbl.Text = "No layers selected — all layers will be kept as one wall."
            else:
                groups  = [g for g in self._get_groups() if g['type'] == 'split']
                linked  = [g for g in groups if len(g['indices']) > 1]
                msg = "{} layer{} \u2192 {} output wall{}.".format(
                    split_count, 's' if split_count != 1 else '',
                    len(groups),  's' if len(groups)  != 1 else '')
                if linked:
                    msg += "  {} linked group{}.".format(
                        len(linked), 's' if len(linked) != 1 else '')
                self.info_lbl.Text = msg

        elif self.phase == 2:
            self.phase_badge.Background      = brush(Color.FromRgb(0x0A, 0x28, 0x1E))
            self.phase_badge_text.Text       = "Phase 2 — pick the host layer"
            self.phase_badge_text.Foreground = brush(C_HOST_BORDER)
            self.instr_lbl.Text = (
                "Click any wall to designate it as the host for doors, windows, and openings."
            )
            self.legend_panel.Visibility = Visibility.Collapsed
            self.sec_lbl.Visibility      = Visibility.Visible
            self.next_btn.Visibility     = Visibility.Visible
            self.confirm_btn.Visibility  = Visibility.Collapsed
            self.next_btn.Content        = "Next  \u2192"
            self.next_btn.IsEnabled      = self.host_key is not None

            self.info_border.Background = brush(Color.FromRgb(0x0A, 0x1E, 0x18))
            self.info_lbl.Foreground    = brush(C_SUBTEXT)
            if not self.host_key:
                self.info_lbl.Text = "No host selected yet."
            else:
                groups = self._get_groups()
                g = next((x for x in groups if self._group_key(x) == self.host_key), None)
                if g:
                    lyrs = [self._layer_by_index(i) for i in g['indices'] if self._layer_by_index(i)]
                    total = UnitUtils.ConvertFromInternalUnits(
                        sum(l.width for l in lyrs), UnitTypeId.Centimeters)
                    if   g['type'] == 'split' and len(lyrs) > 1:
                        self.info_lbl.Text = "Host: grouped wall ({} linked layers, {:.1f} cm).".format(len(lyrs), total)
                    elif g['type'] == 'split':
                        self.info_lbl.Text = 'Host: "{}" ({}).'.format(lyrs[0].label, lyrs[0].func_label())
                    elif len(lyrs) > 1:
                        self.info_lbl.Text = "Host: combined kept wall ({} layers, {:.1f} cm).".format(len(lyrs), total)
                    else:
                        self.info_lbl.Text = 'Host: "{}" ({}).'.format(lyrs[0].label, lyrs[0].func_label())

        else:  # phase 3
            self.phase_badge.Background      = brush(Color.FromRgb(0x28, 0x1E, 0x40))
            self.phase_badge_text.Text       = "Phase 3 — name resulting walls"
            self.phase_badge_text.Foreground = brush(C_ACCENT)
            self.instr_lbl.Text = (
                "Edit the wall type name for each resulting wall. "
                "Names must be unique. Press Confirm to create the walls."
            )
            self.legend_panel.Visibility = Visibility.Collapsed
            self.sec_lbl.Visibility      = Visibility.Collapsed
            self.next_btn.Visibility     = Visibility.Collapsed
            self.confirm_btn.Visibility  = Visibility.Visible
            self.confirm_btn.IsEnabled   = True

            self.info_border.Background = brush(Color.FromRgb(0x20, 0x18, 0x30))
            self.info_lbl.Foreground    = brush(C_SUBTEXT)
            groups = self._get_groups()
            self.info_lbl.Text = (
                "{} wall{} will be created. Edit names above, then click Confirm.".format(
                    len(groups), 's' if len(groups) != 1 else '')
            )

    # ─────────────────────────────────────────────────────────────────────
    # Button handlers
    # ─────────────────────────────────────────────────────────────────────
    def _on_reset(self, s, e):
        for ld in self.real_layers: ld.is_split = False
        self.link_set.clear()
        self.phase    = 1
        self.host_key = None
        self._name_boxes.clear()
        self._auto_names.clear()
        self._refresh()

    def _on_next(self, s, e):
        if self.phase == 1:
            self.phase    = 2
            self.host_key = None
        elif self.phase == 2:
            # Pre-populate auto-names when entering phase 3
            for group in self._get_groups():
                key = self._group_key(group)
                if key not in self._auto_names:
                    self._auto_names[key] = self._auto_name_for_group(group)
            self.phase = 3
        self._refresh()

    def _on_confirm(self, s, e):
        self.confirmed[0] = True
        self.Close()

    # ─────────────────────────────────────────────────────────────────────
    # Result
    # ─────────────────────────────────────────────────────────────────────
    def get_result(self):
        """
        Returns (groups, host_key, name_map)
        name_map: group_key -> wall type name string
        """
        groups   = self._get_groups()
        name_map = {}
        for group in groups:
            key = self._group_key(group)
            tb  = self._name_boxes.get(key)
            if tb and tb.Text.strip():
                name_map[key] = tb.Text.strip()
            else:
                name_map[key] = self._auto_names.get(key, self._auto_name_for_group(group))
        return groups, self.host_key, name_map


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
        ref = uidoc.Selection.PickObject(ObjectType.Element, WallFilter(), "Select Wall to Peel")
        return doc.GetElement(ref)
    except:
        forms.alert("No wall selected. Exiting.", exitscript=True)


def build_layer_data(wall):
    raw = wall.WallType.GetCompoundStructure().GetLayers()
    result = []
    for i, layer in enumerate(raw):
        ld       = LayerData(i, layer, doc)
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


def make_wall_type_for_group(base_wall_type, group_layers, type_name):
    """Get existing WallType by name or create a new one."""
    existing = get_wall_type_by_name(type_name)
    if existing:
        return existing
    new_type = base_wall_type.Duplicate(type_name)
    compound = CompoundStructure.CreateSimpleCompoundStructure(
        [ld.layer for ld in group_layers])
    new_type.SetCompoundStructure(compound)
    return new_type


def get_hosted_elements(wall):
    result = []
    for eid in wall.GetDependentElements(None):
        el = doc.GetElement(eid)
        if el is not None and el.Category is not None:
            result.append(el)
    return result


def duplicate_wall(wall, keep_hosted):
    new_ids = ElementTransformUtils.CopyElements(
        doc, List[ElementId]([wall.Id]), XYZ(0, 0, 0))
    new_w = doc.GetElement(new_ids[0])
    if keep_hosted:
        return new_w
    for el in get_hosted_elements(new_w):
        if not isinstance(el, Wall):
            doc.Delete(el.Id)
    return new_w


def get_interior_direction(wall):
    """
    Return a unit XYZ vector pointing from the wall's physical exterior face
    toward its interior, derived from actual wall geometry via HostObjectUtils.
    No CreateOffset, no Flipped arithmetic — pure geometry.
    """
    try:
        refs = HostObjectUtils.GetSideFaces(wall, ShellLayerType.Exterior)
        face = wall.GetGeometryObjectFromReference(refs[0])
        # FaceNormal points OUTWARD from the wall body; negate = toward interior
        return face.FaceNormal.Negate()
    except:
        # Fallback for curved walls or API failure: derive from test offset + Flipped
        crv     = wall.Location.Curve
        pt_orig = crv.GetEndPoint(0)
        pt_off  = crv.CreateOffset(1.0, XYZ.BasisZ).GetEndPoint(0)
        raw_dir = (pt_off - pt_orig).Normalize()
        return raw_dir if not wall.Flipped else raw_dir.Negate()


def compute_group_curve_absolute(original_curve, interior_dir,
                                  ext_face_origin, ext_face_normal,
                                  wall_flipped,
                                  group_layers, all_real_layers):
    """
    Compute the ABSOLUTE centerline curve for a new wall group.

    No offsets from the original location curve are used at all.
    Everything is anchored to the physical exterior face of the original wall.

    Strategy (layer-average):
      For each layer in the group, compute its centreline distance from the
      PHYSICAL exterior face.  The new wall's curve sits at the AVERAGE of
      those distances, translated from the exterior face along interior_dir.

    Physical layer ordering:
      Flipped = False  →  compound layer 0 = physical exterior  (normal order)
      Flipped = True   →  compound layer 0 = physical interior  (reversed order)

    Curve construction:
      1. Project the original curve's endpoints onto the exterior face plane.
         This removes any dependency on where the original location line sits.
      2. Translate those projected points by  avg_center × interior_dir.
      3. Build an absolute Line.CreateBound(pt0, pt1).
    """
    total_width = sum(ld.width for ld in all_real_layers)
    first_idx   = all_real_layers.index(group_layers[0])

    # ── Layer centre positions from the PHYSICAL exterior face ────────────
    centers = []
    if not wall_flipped:
        # Layer 0 is physical exterior — count inward
        running = sum(ld.width for ld in all_real_layers[:first_idx])
        for ld in group_layers:
            centers.append(running + ld.width / 2.0)
            running += ld.width
    else:
        # Layer 0 is physical INTERIOR — compound structure is reversed in space.
        # Distance of compound layer k from physical exterior:
        #   centre_from_phys_ext = total_width − (offset_from_layer0_face + width/2)
        running_from_layer0 = sum(ld.width for ld in all_real_layers[:first_idx])
        for ld in group_layers:
            centre_from_layer0 = running_from_layer0 + ld.width / 2.0
            centers.append(total_width - centre_from_layer0)
            running_from_layer0 += ld.width

    avg_center = sum(centers) / float(len(centers))

    # ── Project original curve endpoints onto the exterior face plane ─────
    # Plane:  (pt − ext_face_origin) · ext_face_normal = 0
    # Projection of pt along ext_face_normal direction:
    #   d       = (pt − origin) · normal          (signed distance from plane)
    #   pt_proj = pt − d × normal
    def proj(pt):
        d = (pt - ext_face_origin).DotProduct(ext_face_normal)
        return pt - ext_face_normal.Multiply(d)

    pt0_ext = proj(original_curve.GetEndPoint(0))
    pt1_ext = proj(original_curve.GetEndPoint(1))

    # ── Translate from exterior face toward interior by avg_center ────────
    v       = interior_dir.Multiply(avg_center)
    new_pt0 = XYZ(pt0_ext.X + v.X, pt0_ext.Y + v.Y, pt0_ext.Z + v.Z)
    new_pt1 = XYZ(pt1_ext.X + v.X, pt1_ext.Y + v.Y, pt1_ext.Z + v.Z)

    return Line.CreateBound(new_pt0, new_pt1)


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
layer_data  = build_layer_data(sel_wall)
real_layers = [ld for ld in layer_data if not ld.is_cb]

if not real_layers:
    forms.alert("Wall has no real layers to split.", exitscript=True)

# 3. Show WPF picker (modeless + PushFrame so Revit stays responsive)
win   = LayerPickerWindow(sel_wall, layer_data)
frame = [DispatcherFrame()]

def on_closed(s, e):
    frame[0].Continue = False

win.Closed += on_closed
win.Show()
Dispatcher.PushFrame(frame[0])

# 4. Check confirmation
if not win.confirmed[0]:
    import sys
    sys.exit(0)

groups, host_key, name_map = win.get_result()

if not groups:
    forms.alert("Nothing to do.", exitscript=True)

if len(groups) == 1 and groups[0]['type'] == 'kept':
    forms.alert("No layers were selected for splitting. Nothing to do.", exitscript=True)

# 5. Cache original wall geometry BEFORE the transaction.
#    All geometry queries (HostObjectUtils, face normals, curve endpoints)
#    must be read here so the transaction body is purely write-only.
original_curve   = sel_wall.Location.Curve
wall_flipped     = sel_wall.Flipped
base_type        = sel_wall.WallType

# Get the physical interior direction from the actual exterior face geometry.
# This replaces every previous approach based on CreateOffset / Flipped arithmetic.
interior_dir = get_interior_direction(sel_wall)

# Get the exterior face plane (origin + outward normal) for absolute curve placement.
# These two values are all we need; no loc_line_offset, no reference line enum.
try:
    _ext_refs       = HostObjectUtils.GetSideFaces(sel_wall, ShellLayerType.Exterior)
    _ext_face       = sel_wall.GetGeometryObjectFromReference(_ext_refs[0])
    ext_face_origin = _ext_face.Origin
    ext_face_normal = _ext_face.FaceNormal  # outward = -interior_dir
except Exception as e:
    forms.alert("Could not read wall exterior face geometry.\n{}".format(str(e)),
                exitscript=True)

# 6. Execute inside a single transaction
t = Transaction(doc, "Wall Peeler — Split Layers")
t.Start()

new_walls = []

for group in groups:
    group_lds = [next(ld for ld in real_layers if ld.index == i)
                 for i in group['indices']]
    is_host   = (host_key == ','.join(str(i) for i in group['indices']))
    key       = ','.join(str(i) for i in group['indices'])
    type_name = name_map.get(key, '')

    # Build / retrieve wall type for this group
    new_type = make_wall_type_for_group(base_type, group_lds, type_name)

    # Compute the ABSOLUTE centerline curve for this group.
    # No offset from the original location curve — everything is derived from
    # the physical exterior face position and the layer widths.
    new_crv = compute_group_curve_absolute(
        original_curve, interior_dir,
        ext_face_origin, ext_face_normal,
        wall_flipped,
        group_lds, real_layers)

    # Duplicate wall (keeps hosted elements only for the host group)
    new_wall = duplicate_wall(sel_wall, is_host)

    # Assignment order — critical:
    #   1. WallCenterline first → locks reference before any type change
    #   2. WallType             → compound structure changes with fixed reference
    #   3. Location.Curve last  → definitive placement; reference is WallCenterline
    new_wall.get_Parameter(BuiltInParameter.WALL_KEY_REF_PARAM).Set(
        int(WallLocationLine.WallCenterline))
    new_wall.WallType       = new_type
    new_wall.Location.Curve = new_crv

    new_walls.append(new_wall)

join_walls(new_walls)
doc.Delete(sel_wall.Id)
t.Commit()
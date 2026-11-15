# -*- coding: utf-8 -*-
__doc__ = """__________________________________________________
Description:

Colours the elements in the active view by the value of a parameter, e.g. walls by Fire Rating or pipes by System Type.
Choose view filters (stay correct as the model changes) or direct graphic overrides, and which surface, cut and line colours to set.
__________________________________________________
How-to:

-> Open the view you want to colour
-> Click on the button and choose By View Filter or By Graphic Override
-> Pick a category, then an instance or type parameter
-> Adjust colours or turn values off, check the override targets
-> Click Apply
-> Shift+Click the button to remove the tool's filters from the view
__________________________________________________
Author: Mohamed Bedair"""


import clr
clr.AddReference('PresentationCore')
clr.AddReference('PresentationFramework')
clr.AddReference('WindowsBase')
clr.AddReference('System.Xml')
clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Drawing')

from System import EventHandler
from System.Windows import (
    Thickness, CornerRadius, Visibility, RoutedEventHandler,
    VerticalAlignment, TextAlignment, TextTrimming, FontWeights,
)
from System.Windows.Controls import (
    Button, TextBlock, Border, DockPanel, Dock, StackPanel, Orientation,
)
from System.Windows.Controls.Primitives import ToggleButton
from System.Windows.Media import SolidColorBrush, Color as WColor
from System.Windows.Threading import Dispatcher, DispatcherFrame

from System.Windows.Forms import ColorDialog, DialogResult as WinDialogResult
from System.Drawing import Color as DrawColor

from System.Collections.Generic import List
from Autodesk.Revit.DB import (
    FilteredElementCollector, FillPatternElement,
    OverrideGraphicSettings, Transaction,
    StorageType, ElementId, CategoryType, BuiltInParameter,
    Color as RC,
    ParameterFilterElement, ParameterFilterRuleFactory,
    ElementParameterFilter, FilterRule,
)
from pyrevit import EXEC_PARAMS
import bd_core
import bd_core as bd

# -- Revit context ------------------------------------------------------------

uidoc       = __revit__.ActiveUIDocument
doc         = uidoc.Document
active_view = doc.ActiveView

_pats         = FilteredElementCollector(doc).OfClass(FillPatternElement).ToElements()
SOLID_PATTERN = next((p for p in _pats if p.GetFillPattern().IsSolidFill), None)

WPC_PREFIX = "WPC_"

# -- Catppuccin Mocha palette -------------------------------------------------

HEX_BG      = "#161616"
HEX_CARD    = "#262626"
HEX_SURFACE = "#393939"
HEX_MUTED   = "#525252"
HEX_TEXT    = "#F4F4F4"
HEX_SUBTEXT = "#A8A8A8"
HEX_ACCENT  = "#F1C21B"
HEX_GREEN   = "#42BE65"
HEX_RED     = "#FF8389"

PALETTE = [
    (243, 139, 168), (250, 179, 135), (249, 226, 175), (166, 227, 161),
    (137, 180, 250), (203, 166, 247), (148, 226, 213), (116, 199, 236),
    (245, 194, 231), (180, 190, 254),
]

# -- Small helpers ------------------------------------------------------------


def _eid(eid):
    return str(bd_core.eid_int(eid))


def hex_to_rgb(hexstr):
    h = hexstr.lstrip('#')
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def brush(hexstr):
    r, g, b = hex_to_rgb(hexstr)
    return SolidColorBrush(WColor.FromRgb(r, g, b))


def rgb_brush(rgb):
    return SolidColorBrush(WColor.FromRgb(rgb[0], rgb[1], rgb[2]))


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
        try:
            return el.Name if el else _eid(eid)
        except Exception:
            return _eid(eid)
    return "<Unknown>"


def all_model_cats():
    cats = []
    for c in doc.Settings.Categories:
        try:
            if c.CategoryType == CategoryType.Model:
                cats.append(c)
        except Exception:
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
    except Exception:
        return []


def get_unique_types(instances):
    seen, types = set(), []
    for inst in instances:
        try:
            tid = inst.GetTypeId()
            k = _eid(tid)
            if k not in seen and tid != ElementId.InvalidElementId:
                seen.add(k)
                t = doc.GetElement(tid)
                if t:
                    types.append(t)
        except Exception:
            pass
    return types


def collect_params_with_meta(elems):
    """
    Returns:
      { param_name: {
          'values'  : [sorted display strings],
          'storage' : StorageType,
          'pid'     : ElementId,   <- parameter definition ID
          'raw'     : {display_str: raw_value},
          'counts'  : {display_str: int}
      }}
    """
    meta = {}
    for el in elems:
        for p in el.Parameters:
            try:
                if p.Definition is None:
                    continue
                n = p.Definition.Name
                st = p.StorageType
                if n not in meta:
                    meta[n] = {'values': set(), 'storage': st,
                               'pid': p.Id, 'raw': {}, 'counts': {}}
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
                meta[n]['counts'][display] = meta[n]['counts'].get(display, 0) + 1
            except Exception:
                pass
    return dict((k, dict(v, values=sorted(v['values'])))
                for k, v in sorted(meta.items()))


def make_filter_name(cat_name, param_name, val_str):
    import re

    def _safe(s, maxlen):
        return re.sub(r'[^\w\-]', '_', s)[:maxlen]

    return "{0}{1}_{2}_{3}".format(
        WPC_PREFIX, _safe(cat_name, 24), _safe(param_name, 24), _safe(val_str, 40))


def find_filter_by_name(name):
    for el in FilteredElementCollector(doc).OfClass(ParameterFilterElement).ToElements():
        try:
            if el.Name == name:
                return el
        except Exception:
            pass
    return None


def make_rule(param_id, storage_type, display_str, raw_value):
    """Build a ParameterFilterRule for a single value. Returns None on failure."""
    try:
        if display_str == "<No Value>" or raw_value is None:
            # NOTE: the method is CreateHasNoValueParameterRule - the shorter
            # CreateHasNoValueRule name does not exist on any Revit version,
            # which is why "<No Value>" rows used to be silently skipped.
            try:
                return ParameterFilterRuleFactory.CreateHasNoValueParameterRule(param_id)
            except Exception:
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
    except Exception:
        pass
    return None


# -- View template inspection -------------------------------------------------


def template_of(view):
    """Return the view template element driving this view, or None."""
    try:
        tid = view.ViewTemplateId
    except Exception:
        return None
    if tid is None or tid == ElementId.InvalidElementId:
        return None
    tpl = doc.GetElement(tid)
    return tpl if tpl is not None else None


def template_controls_filters(tpl):
    """True if the template owns V/G Overrides Filters (so the view can't)."""
    if tpl is None:
        return False
    try:
        blocked = ElementId(BuiltInParameter.VIS_GRAPHICS_FILTERS)
        for pid in tpl.GetNonControlledTemplateParameterIds():
            if _eid(pid) == _eid(blocked):
                return False   # explicitly released to the view
    except Exception:
        pass
    return True


# -- Shared XAML style block --------------------------------------------------

# Window layout: dialog.xaml, ui.xaml next to this script (shared colours and styles: lib/bd_theme.xaml)

# -- Themed dialog ------------------------------------------------------------


MAIN_WINDOW = [None]


def show_dialog(title, message, buttons, accent=HEX_ACCENT):
    """buttons: list of (key, label, is_accent). Returns the chosen key or None."""
    win = bd.load_window(__file__, "dialog.xaml")
    win.Title = title
    win.FindName("txt_title").Text = title
    win.FindName("txt_msg").Text = message
    win.FindName("bar_accent").Background = brush(accent)

    holder = win.FindName("btn_holder")
    result = [None]

    def make_handler(key):
        def handler(sender, args):
            result[0] = key
            win.Close()
        return RoutedEventHandler(handler)

    for key, label, is_accent in buttons:
        b = Button()
        b.Content = label
        b.Style = win.FindResource("BtnAccent" if is_accent else "Btn")
        b.MinWidth = 108
        b.Margin = Thickness(8, 0, 0, 0)
        b.Click += make_handler(key)
        holder.Children.Add(b)

    try:
        if MAIN_WINDOW[0] is not None:
            win.Owner = MAIN_WINDOW[0]
    except Exception:
        pass

    win.ShowDialog()
    return result[0]


def info(message, title="Done"):
    show_dialog(title, message, [("ok", "OK", True)], HEX_GREEN)


def warn(message, title="Heads up"):
    show_dialog(title, message, [("ok", "OK", True)], HEX_ACCENT)


def error(message, title="Error"):
    show_dialog(title, message, [("ok", "OK", True)], HEX_RED)


# -- Main window XAML ---------------------------------------------------------


# -- Value row model ----------------------------------------------------------


CHANNELS = ["surf", "cut", "proj", "line"]

CHANNEL_LABELS = {
    "surf": "SURF",
    "cut": "CUT",
    "proj": "PROJ",
    "line": "LINE",
}

CHANNEL_TIPS = {
    "surf": "Surface pattern colour",
    "cut": "Cut pattern colour",
    "proj": "Projection line colour",
    "line": "Cut line colour",
}

SWATCH_W = 42
SWATCH_GAP = 4
PILL_W = 54
COUNT_W = 34


class ValueRow(object):
    """One parameter value, with an independent colour per channel."""

    def __init__(self, value, rgb, count):
        self.value = value
        self.count = count
        self.enabled = True
        self.rgb = dict((c, rgb) for c in CHANNELS)
        self.swatches = {}
        self.pill = None
        self.label = None


# -- Main window --------------------------------------------------------------


class ColorizerWindow(object):

    def __init__(self):
        self.window = bd.load_window(__file__)
        MAIN_WINDOW[0] = self.window

        self._all_cats = all_model_cats()
        self._cat_names = []
        self._param_names = []
        self._instances = []
        self._pmeta = {}
        self._rows = []
        self._busy = False

        f = self.window.FindName
        self.tg_filter = f("tg_filter")
        self.tg_override = f("tg_override")
        self.txt_view = f("txt_view")
        self.badge_tpl = f("badge_tpl")
        self.txt_badge = f("txt_badge")
        self.tb_cat_search = f("tb_cat_search")
        self.ph_cat = f("ph_cat")
        self.lb_cat = f("lb_cat")
        self.tg_inst = f("tg_inst")
        self.tg_type = f("tg_type")
        self.tb_param_search = f("tb_param_search")
        self.ph_param = f("ph_param")
        self.lb_param = f("lb_param")
        self.pnl_values = f("pnl_values")
        self.hdr_holder = f("hdr_holder")
        self.txt_hint = f("txt_hint")
        self.chk_sync = f("chk_sync")
        self.txt_status = f("txt_status")
        self.btn_shuffle = f("btn_shuffle")
        self.btn_all_on = f("btn_all_on")
        self.btn_all_off = f("btn_all_off")
        self.btn_apply = f("btn_apply")
        self.btn_reset = f("btn_reset")
        self.btn_cancel = f("btn_cancel")

        self.chk_surf_fg = f("chk_surf_fg")
        self.chk_surf_bg = f("chk_surf_bg")
        self.chk_cut_fg = f("chk_cut_fg")
        self.chk_cut_bg = f("chk_cut_bg")
        self.chk_proj_line = f("chk_proj_line")
        self.chk_cut_line = f("chk_cut_line")
        self.tb_weight = f("tb_weight")

        self._wire_events()
        self._show_view_context()
        self._fill_cat_list("")
        self._set_status("Ready.")

    # -- wiring ---------------------------------------------------------------

    def _wire_events(self):
        self.tg_filter.Checked += RoutedEventHandler(self._on_mode)
        self.tg_filter.Unchecked += RoutedEventHandler(self._on_mode)
        self.tg_override.Checked += RoutedEventHandler(self._on_mode)
        self.tg_override.Unchecked += RoutedEventHandler(self._on_mode)

        self.tg_inst.Checked += RoutedEventHandler(self._on_scope)
        self.tg_inst.Unchecked += RoutedEventHandler(self._on_scope)
        self.tg_type.Checked += RoutedEventHandler(self._on_scope)
        self.tg_type.Unchecked += RoutedEventHandler(self._on_scope)

        self.tb_cat_search.TextChanged += self._on_cat_search
        self.tb_param_search.TextChanged += self._on_param_search
        self.lb_cat.SelectionChanged += self._on_cat_pick
        self.lb_param.SelectionChanged += self._on_param_pick

        for chk in (self.chk_surf_fg, self.chk_surf_bg, self.chk_cut_fg,
                    self.chk_cut_bg, self.chk_proj_line, self.chk_cut_line):
            chk.Checked += RoutedEventHandler(self._on_target_changed)
            chk.Unchecked += RoutedEventHandler(self._on_target_changed)

        self.btn_shuffle.Click += RoutedEventHandler(self._on_shuffle)
        self.btn_all_on.Click += RoutedEventHandler(self._on_all_on)
        self.btn_all_off.Click += RoutedEventHandler(self._on_all_off)
        self.btn_apply.Click += RoutedEventHandler(self._on_apply)
        self.btn_reset.Click += RoutedEventHandler(self._on_reset)
        self.btn_cancel.Click += RoutedEventHandler(self._on_close)

    def show(self):
        frame = DispatcherFrame()

        def on_closed(sender, args):
            frame.Continue = False

        self.window.Closed += EventHandler(on_closed)
        self.window.Show()
        Dispatcher.PushFrame(frame)

    # -- small UI helpers -----------------------------------------------------

    def _set_status(self, text):
        self.txt_status.Text = text

    def _show_view_context(self):
        try:
            self.txt_view.Text = u"Active view: {0}".format(active_view.Name)
        except Exception:
            self.txt_view.Text = u"Active view"
        tpl = template_of(active_view)
        if tpl is not None:
            self.txt_badge.Text = u"TEMPLATE: {0}".format(tpl.Name).upper()
            self.badge_tpl.Visibility = Visibility.Visible
            if template_controls_filters(tpl):
                # This template owns the view's filters, so Filter mode will
                # refuse to run - say so before the user picks anything.
                self.txt_badge.Foreground = brush(HEX_RED)
                self.badge_tpl.ToolTip = (
                    "This template controls V/G Overrides Filters, "
                    "so view filters cannot be added or removed on this view.")

    def _mode_is_filter(self):
        return bool(self.tg_filter.IsChecked)

    def _use_type_params(self):
        return bool(self.tg_type.IsChecked)

    # -- toggles --------------------------------------------------------------

    def _on_mode(self, sender, args):
        if self._busy:
            return
        self._busy = True
        try:
            if sender.Name == "tg_filter":
                if self.tg_filter.IsChecked:
                    self.tg_override.IsChecked = False
                else:
                    self.tg_filter.IsChecked = True   # keep one always on
            else:
                if self.tg_override.IsChecked:
                    self.tg_filter.IsChecked = False
                else:
                    self.tg_override.IsChecked = True
        finally:
            self._busy = False
        self.btn_reset.Content = ("Remove Filters" if self._mode_is_filter()
                                  else "Reset Overrides")

    def _on_scope(self, sender, args):
        if self._busy:
            return
        self._busy = True
        try:
            if sender.Name == "tg_inst":
                if self.tg_inst.IsChecked:
                    self.tg_type.IsChecked = False
                else:
                    self.tg_inst.IsChecked = True
            else:
                if self.tg_type.IsChecked:
                    self.tg_inst.IsChecked = False
                else:
                    self.tg_type.IsChecked = True
        finally:
            self._busy = False
        self._load_params()

    # -- category / parameter lists -------------------------------------------

    def _on_cat_search(self, sender, args):
        if self._busy:
            return
        txt = self.tb_cat_search.Text
        self.ph_cat.Visibility = Visibility.Collapsed if txt else Visibility.Visible
        self._fill_cat_list(txt)

    def _on_param_search(self, sender, args):
        if self._busy:
            return
        txt = self.tb_param_search.Text
        self.ph_param.Visibility = Visibility.Collapsed if txt else Visibility.Visible
        self._fill_param_list(txt)

    def _fill_cat_list(self, search):
        self._busy = True
        try:
            self.lb_cat.Items.Clear()
            s = (search or "").strip().lower()
            self._cat_names = []
            for c in self._all_cats:
                if not s or s in c.Name.lower():
                    self._cat_names.append(c.Name)
                    self.lb_cat.Items.Add(c.Name)
        finally:
            self._busy = False

    def _fill_param_list(self, search):
        self._busy = True
        try:
            self.lb_param.Items.Clear()
            s = (search or "").strip().lower()
            for name in sorted(self._pmeta.keys()):
                if not s or s in name.lower():
                    self.lb_param.Items.Add(name)
        finally:
            self._busy = False

    def _selected_cat(self):
        item = self.lb_cat.SelectedItem
        if item is None:
            return None
        name = str(item)
        for c in self._all_cats:
            if c.Name == name:
                return c
        return None

    def _selected_param(self):
        item = self.lb_param.SelectedItem
        return str(item) if item is not None else None

    def _on_cat_pick(self, sender, args):
        if self._busy:
            return
        self._load_params()

    def _on_param_pick(self, sender, args):
        if self._busy:
            return
        self._fill_values()

    def _load_params(self):
        cat = self._selected_cat()
        if cat is None:
            return
        self._instances = get_instances(cat.Id)
        elems = (get_unique_types(self._instances)
                 if self._use_type_params() else self._instances)
        self._pmeta = collect_params_with_meta(elems)

        self._fill_param_list(self.tb_param_search.Text)
        self._clear_values()
        self._set_status(u"{0}: {1} element(s) in view, {2} parameter(s).".format(
            cat.Name, len(self._instances), len(self._pmeta)))

    # -- value rows -----------------------------------------------------------

    def _clear_values(self):
        self.pnl_values.Children.Clear()
        self.hdr_holder.Visibility = Visibility.Collapsed
        self._rows = []
        self.txt_hint.Text = "Select a category and a parameter to populate."
        self.txt_hint.Visibility = Visibility.Visible

    def _fill_values(self):
        self.pnl_values.Children.Clear()
        self.hdr_holder.Visibility = Visibility.Collapsed
        self._rows = []

        pname = self._selected_param()
        if pname is None:
            self.txt_hint.Visibility = Visibility.Visible
            return

        meta = self._pmeta.get(pname, {})
        vals = meta.get('values', [])
        counts = meta.get('counts', {})

        if not vals:
            self.txt_hint.Text = "No values found for this parameter."
            self.txt_hint.Visibility = Visibility.Visible
            return

        self.txt_hint.Visibility = Visibility.Collapsed
        self.hdr_holder.Child = self._build_value_header()
        self.hdr_holder.Visibility = Visibility.Visible
        for i, v in enumerate(vals):
            row = ValueRow(v, PALETTE[i % len(PALETTE)], counts.get(v, 0))
            self._rows.append(row)
            self.pnl_values.Children.Add(self._build_row(row))

        self._set_status(u"'{0}': {1} unique value(s).".format(pname, len(vals)))

    def _build_row(self, row):
        bd = Border()
        bd.Background = brush(HEX_CARD)
        bd.CornerRadius = CornerRadius(6)
        bd.Margin = Thickness(0, 0, 0, 4)
        bd.Padding = Thickness(8, 6, 8, 6)

        dp = DockPanel()
        dp.LastChildFill = True

        # Right-docked children claim the right edge in the order they are added,
        # so this gives:  value ... count | SURF CUT PROJ LINE | ON/OFF
        pill = ToggleButton()
        pill.Style = self.window.FindResource("Pill")
        pill.Width = PILL_W
        pill.Height = 22
        pill.Content = "ON"
        pill.IsChecked = True
        pill.Margin = Thickness(10, 0, 0, 0)
        pill.VerticalAlignment = VerticalAlignment.Center
        pill.Click += self._make_pill_handler(row)
        DockPanel.SetDock(pill, Dock.Right)
        dp.Children.Add(pill)
        row.pill = pill

        sp = StackPanel()
        sp.Orientation = Orientation.Horizontal
        sp.VerticalAlignment = VerticalAlignment.Center
        for ch in CHANNELS:
            swatch = Button()
            swatch.Style = self.window.FindResource("Swatch")
            swatch.Width = SWATCH_W
            swatch.Height = 26
            swatch.Margin = Thickness(SWATCH_GAP, 0, 0, 0)
            swatch.Background = rgb_brush(row.rgb[ch])
            swatch.ToolTip = CHANNEL_TIPS[ch] + " - click to pick"
            swatch.Click += self._make_swatch_handler(row, ch)
            sp.Children.Add(swatch)
            row.swatches[ch] = swatch
        DockPanel.SetDock(sp, Dock.Right)
        dp.Children.Add(sp)

        cnt = TextBlock()
        cnt.Text = str(row.count)
        cnt.Foreground = brush(HEX_SUBTEXT)
        cnt.FontSize = 10
        cnt.MinWidth = COUNT_W
        cnt.TextAlignment = TextAlignment.Right
        cnt.VerticalAlignment = VerticalAlignment.Center
        cnt.Margin = Thickness(8, 0, 0, 0)
        DockPanel.SetDock(cnt, Dock.Right)
        dp.Children.Add(cnt)

        lbl = TextBlock()
        lbl.Text = row.value
        lbl.Foreground = brush(HEX_TEXT)
        lbl.VerticalAlignment = VerticalAlignment.Center
        lbl.TextTrimming = TextTrimming.CharacterEllipsis
        lbl.Margin = Thickness(2, 0, 6, 0)
        lbl.ToolTip = row.value
        dp.Children.Add(lbl)
        row.label = lbl

        bd.Child = dp
        self._apply_row_state(row)
        return bd

    def _build_value_header(self):
        """Column captions lined up with the swatch columns of each row."""
        dp = DockPanel()
        dp.LastChildFill = True
        dp.Margin = Thickness(8, 0, 17, 6)   # 8 = row padding, 17 = padding + scrollbar

        spacer = TextBlock()
        spacer.MinWidth = PILL_W
        spacer.Margin = Thickness(10, 0, 0, 0)
        DockPanel.SetDock(spacer, Dock.Right)
        dp.Children.Add(spacer)

        sp = StackPanel()
        sp.Orientation = Orientation.Horizontal
        for ch in CHANNELS:
            tb = TextBlock()
            tb.Text = CHANNEL_LABELS[ch]
            tb.ToolTip = CHANNEL_TIPS[ch]
            tb.Foreground = brush(HEX_SUBTEXT)
            tb.FontSize = 9
            tb.FontWeight = FontWeights.Bold
            tb.Width = SWATCH_W
            tb.Margin = Thickness(SWATCH_GAP, 0, 0, 0)
            tb.TextAlignment = TextAlignment.Center
            sp.Children.Add(tb)
        DockPanel.SetDock(sp, Dock.Right)
        dp.Children.Add(sp)

        cnt = TextBlock()
        cnt.Text = "N"
        cnt.Foreground = brush(HEX_SUBTEXT)
        cnt.FontSize = 9
        cnt.FontWeight = FontWeights.Bold
        cnt.MinWidth = COUNT_W
        cnt.TextAlignment = TextAlignment.Right
        cnt.Margin = Thickness(8, 0, 0, 0)
        DockPanel.SetDock(cnt, Dock.Right)
        dp.Children.Add(cnt)

        lbl = TextBlock()
        lbl.Text = "VALUE"
        lbl.Foreground = brush(HEX_SUBTEXT)
        lbl.FontSize = 9
        lbl.FontWeight = FontWeights.Bold
        lbl.Margin = Thickness(2, 0, 6, 0)
        dp.Children.Add(lbl)

        return dp

    def _apply_row_state(self, row):
        """Dim the label, and any swatch whose channel is switched off."""
        active = self._active_channels()
        row.label.Foreground = brush(HEX_TEXT if row.enabled else HEX_MUTED)
        for ch in CHANNELS:
            sw = row.swatches.get(ch)
            if sw is None:
                continue
            sw.Opacity = 1.0 if (row.enabled and active[ch]) else 0.25

    def _set_row_color(self, row, ch, rgb):
        row.rgb[ch] = rgb
        row.swatches[ch].Background = rgb_brush(rgb)

    def _make_swatch_handler(self, row, ch):
        def handler(sender, args):
            cur = row.rgb[ch]
            dlg = ColorDialog()
            dlg.FullOpen = True
            dlg.Color = DrawColor.FromArgb(cur[0], cur[1], cur[2])
            if dlg.ShowDialog() == WinDialogResult.OK:
                picked = (dlg.Color.R, dlg.Color.G, dlg.Color.B)
                if self.chk_sync.IsChecked:
                    for other in CHANNELS:
                        self._set_row_color(row, other, picked)
                else:
                    self._set_row_color(row, ch, picked)
        return RoutedEventHandler(handler)

    def _make_pill_handler(self, row):
        def handler(sender, args):
            row.enabled = bool(row.pill.IsChecked)
            row.pill.Content = "ON" if row.enabled else "OFF"
            self._apply_row_state(row)
        return RoutedEventHandler(handler)

    def _on_shuffle(self, sender, args):
        for i, row in enumerate(self._rows):
            for ch in CHANNELS:
                self._set_row_color(row, ch, PALETTE[(i + 3) % len(PALETTE)])

    def _set_all(self, state):
        for row in self._rows:
            row.enabled = state
            row.pill.IsChecked = state
            row.pill.Content = "ON" if state else "OFF"
            self._apply_row_state(row)

    def _on_all_on(self, sender, args):
        self._set_all(True)

    def _on_all_off(self, sender, args):
        self._set_all(False)

    def _on_close(self, sender, args):
        self.window.Close()

    # -- override targets -----------------------------------------------------

    def _targets(self):
        return {
            'surf_fg': bool(self.chk_surf_fg.IsChecked),
            'surf_bg': bool(self.chk_surf_bg.IsChecked),
            'cut_fg': bool(self.chk_cut_fg.IsChecked),
            'cut_bg': bool(self.chk_cut_bg.IsChecked),
            'proj_line': bool(self.chk_proj_line.IsChecked),
            'cut_line': bool(self.chk_cut_line.IsChecked),
        }

    def _active_channels(self):
        """Which of the four colour channels the current targets actually use."""
        tg = self._targets()
        return {
            'surf': tg['surf_fg'] or tg['surf_bg'],
            'cut': tg['cut_fg'] or tg['cut_bg'],
            'proj': tg['proj_line'],
            'line': tg['cut_line'],
        }

    def _on_target_changed(self, sender, args):
        for row in self._rows:
            self._apply_row_state(row)

    def _line_weight(self):
        """Returns an int 1-16, or None for 'leave as is'. Raises ValueError."""
        txt = (self.tb_weight.Text or "").strip()
        if not txt:
            return None
        w = int(txt)
        if w < 1 or w > 16:
            raise ValueError("Line weight must be between 1 and 16.")
        return w

    def _needs_pattern(self, tg):
        return tg['surf_fg'] or tg['surf_bg'] or tg['cut_fg'] or tg['cut_bg']

    def _build_ogs(self, row, tg, weight):
        """One OverrideGraphicSettings using this row's four channel colours."""
        ogs = OverrideGraphicSettings()

        surf = RC(row.rgb['surf'][0], row.rgb['surf'][1], row.rgb['surf'][2])
        cut = RC(row.rgb['cut'][0], row.rgb['cut'][1], row.rgb['cut'][2])
        proj = RC(row.rgb['proj'][0], row.rgb['proj'][1], row.rgb['proj'][2])
        line = RC(row.rgb['line'][0], row.rgb['line'][1], row.rgb['line'][2])

        if tg['surf_fg']:
            ogs.SetSurfaceForegroundPatternVisible(True)
            ogs.SetSurfaceForegroundPatternId(SOLID_PATTERN.Id)
            ogs.SetSurfaceForegroundPatternColor(surf)
        if tg['surf_bg']:
            ogs.SetSurfaceBackgroundPatternVisible(True)
            ogs.SetSurfaceBackgroundPatternId(SOLID_PATTERN.Id)
            ogs.SetSurfaceBackgroundPatternColor(surf)
        if tg['cut_fg']:
            ogs.SetCutForegroundPatternVisible(True)
            ogs.SetCutForegroundPatternId(SOLID_PATTERN.Id)
            ogs.SetCutForegroundPatternColor(cut)
        if tg['cut_bg']:
            ogs.SetCutBackgroundPatternVisible(True)
            ogs.SetCutBackgroundPatternId(SOLID_PATTERN.Id)
            ogs.SetCutBackgroundPatternColor(cut)
        if tg['proj_line']:
            ogs.SetProjectionLineColor(proj)
            if weight is not None:
                ogs.SetProjectionLineWeight(weight)
        if tg['cut_line']:
            ogs.SetCutLineColor(line)
            if weight is not None:
                ogs.SetCutLineWeight(weight)
        return ogs

    # -- view template failsafe -----------------------------------------------

    def _template_blocks_filters(self, what):
        """
        True (and warns) when a view template owns this view's filter list,
        in which case nothing should be attempted.
        """
        tpl = template_of(active_view)
        if tpl is None or not template_controls_filters(tpl):
            return False

        warn(u"The active view '{0}' is driven by the view template '{1}', "
             u"which controls V/G Overrides Filters.\n\n"
             u"While that is the case Revit will not accept any filter change on "
             u"the view, so {2}.\n\n"
             u"Edit the filters on the template itself, release Filters from the "
             u"template, or remove the template from this view, then run the tool "
             u"again.".format(active_view.Name, tpl.Name, what),
             "View Template Detected")
        return True

    # -- apply dispatcher -----------------------------------------------------

    def _on_apply(self, sender, args):
        if not self._instances:
            warn("No elements found in the active view for this category.",
                 "Nothing to Colorize")
            return
        if self._selected_param() is None:
            warn("Please select a parameter from the list.", "No Parameter Selected")
            return
        if not self._rows:
            warn("No values to colorize.", "Nothing to Colorize")
            return

        tg = self._targets()
        if not any(tg.values()):
            warn("Check at least one override target (surface, cut or lines).",
                 "No Target Selected")
            return
        if self._needs_pattern(tg) and SOLID_PATTERN is None:
            error("No solid fill pattern found in the document, so pattern "
                  "overrides cannot be applied.", "Missing Pattern")
            return

        try:
            weight = self._line_weight()
        except ValueError:
            warn("Line weight must be a whole number between 1 and 16, "
                 "or left blank to keep the current weight.", "Invalid Line Weight")
            return

        if not [r for r in self._rows if r.enabled]:
            warn("Every value is switched OFF - nothing to apply.",
                 "Nothing to Colorize")
            return

        if self._mode_is_filter():
            self._apply_filters(tg, weight)
        else:
            self._apply_overrides(tg, weight)

    # -- apply: view filters --------------------------------------------------

    def _apply_filters(self, tg, weight):
        pname = self._selected_param()
        cat = self._selected_cat()
        meta = self._pmeta.get(pname, {})
        param_id = meta.get('pid')
        storage = meta.get('storage')
        raw_map = meta.get('raw', {})

        if param_id is None:
            error("Could not find a parameter definition for '{0}'.".format(pname))
            return

        if self._template_blocks_filters("no filters were created"):
            self._set_status("Blocked by view template - no filters were created.")
            return

        cat_ids = List[ElementId]()
        cat_ids.Add(cat.Id)

        applied = 0
        skipped = []
        first_fail = [None]

        t = Transaction(doc, u"Filter Colorize: {0} - {1}".format(cat.Name, pname))
        t.Start()
        try:
            existing = set(_eid(fid) for fid in active_view.GetFilters())

            for row in self._rows:
                if not row.enabled:
                    continue

                fname = make_filter_name(cat.Name, pname, row.value)
                rule = make_rule(param_id, storage, row.value, raw_map.get(row.value))
                if rule is None:
                    skipped.append(row.value)
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
                        skipped.append(row.value)
                        continue
                else:
                    try:
                        pfe.SetElementFilter(elem_filter)
                    except Exception:
                        pass

                if _eid(pfe.Id) not in existing:
                    active_view.AddFilter(pfe.Id)
                    existing.add(_eid(pfe.Id))

                active_view.SetFilterOverrides(pfe.Id, self._build_ogs(row, tg, weight))
                active_view.SetFilterVisibility(pfe.Id, True)
                applied += 1

            t.Commit()

            msg = u"Applied {0} view filter(s) for '{1}' on view '{2}'.".format(
                applied, cat.Name, active_view.Name)
            if skipped:
                msg += u"\n\nSkipped ({0}):\n  {1}".format(
                    len(skipped), "\n  ".join(skipped[:10]))
            if first_fail[0]:
                msg += (u"\n\nNote: this category may have limited filter support.\n"
                        u"First error: " + first_fail[0])
            self._set_status(u"Applied {0} filter(s).".format(applied))
            if applied:
                info(msg)
            else:
                warn(msg, "Nothing Applied")

        except Exception as ex:
            try:
                t.RollBack()
            except Exception:
                pass
            error(str(ex))

    # -- apply: graphic overrides ---------------------------------------------

    def _apply_overrides(self, tg, weight):
        pname = self._selected_param()
        use_type = self._use_type_params()
        cat = self._selected_cat()

        reset_ogs = OverrideGraphicSettings()
        val_ogs = {}
        for row in self._rows:
            if row.enabled:
                val_ogs[row.value] = self._build_ogs(row, tg, weight)

        t = Transaction(doc, u"Override Colorize: {0} - {1}".format(cat.Name, pname))
        t.Start()
        try:
            applied = 0
            for inst in self._instances:
                # Always reset first so switching values clears old colours
                active_view.SetElementOverrides(inst.Id, reset_ogs)

                if use_type:
                    tid = inst.GetTypeId()
                    elem = doc.GetElement(tid) if tid != ElementId.InvalidElementId else None
                else:
                    elem = inst

                if elem is None:
                    continue

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
            self._set_status(u"Overrode {0} of {1} element(s).".format(
                applied, len(self._instances)))
            info(u"Applied overrides to {0} of {1} element(s).".format(
                applied, len(self._instances)))

        except Exception as ex:
            try:
                t.RollBack()
            except Exception:
                pass
            error(str(ex))

    # -- reset ----------------------------------------------------------------

    def _on_reset(self, sender, args):
        if self._mode_is_filter():
            self._reset_filters()
        else:
            self._reset_overrides()

    def _reset_filters(self):
        if self._template_blocks_filters("nothing was removed"):
            self._set_status("Blocked by view template - nothing was removed.")
            return

        wpc_ids = []
        for fid in list(active_view.GetFilters()):
            el = doc.GetElement(fid)
            if el is None:
                continue
            try:
                if el.Name.startswith(WPC_PREFIX):
                    wpc_ids.append(fid)
            except Exception:
                pass

        if not wpc_ids:
            warn(u"No {0} filters found on '{1}'.".format(
                WPC_PREFIX, active_view.Name), "Nothing to Remove")
            return

        t = Transaction(doc, "Remove WPC_ View Filters")
        t.Start()
        try:
            for fid in wpc_ids:
                try:
                    active_view.RemoveFilter(fid)
                except Exception:
                    pass
                try:
                    doc.Delete(fid)
                except Exception:
                    pass
            t.Commit()
            self._set_status(u"Removed {0} filter(s).".format(len(wpc_ids)))
            info(u"Removed {0} {1} filter(s) from '{2}'.".format(
                len(wpc_ids), WPC_PREFIX, active_view.Name))
        except Exception as ex:
            try:
                t.RollBack()
            except Exception:
                pass
            error(str(ex))

    def _reset_overrides(self):
        if not self._instances:
            warn("No elements loaded. Select a category first.", "Nothing to Reset")
            return
        reset_ogs = OverrideGraphicSettings()
        t = Transaction(doc, "Reset Element Overrides")
        t.Start()
        try:
            for inst in self._instances:
                active_view.SetElementOverrides(inst.Id, reset_ogs)
            t.Commit()
            self._set_status(u"Cleared overrides on {0} element(s).".format(
                len(self._instances)))
            info(u"Overrides cleared for {0} element(s).".format(len(self._instances)))
        except Exception as ex:
            try:
                t.RollBack()
            except Exception:
                pass
            error(str(ex))


# -- Entry point --------------------------------------------------------------

if EXEC_PARAMS.config_mode:
    # Config / right-click: remove all WPC_ filters from the active view.
    _wpc_ids = []
    for _fid in active_view.GetFilters():
        _el = doc.GetElement(_fid)
        if _el is not None:
            try:
                if _el.Name.startswith(WPC_PREFIX):
                    _wpc_ids.append(_fid)
            except Exception:
                pass

    if _wpc_ids:
        _t = Transaction(doc, "Remove WPC_ Filters (config)")
        _t.Start()
        try:
            for _fid in _wpc_ids:
                try:
                    active_view.RemoveFilter(_fid)
                except Exception:
                    pass
                try:
                    doc.Delete(_fid)
                except Exception:
                    pass
            _t.Commit()
        except Exception:
            try:
                _t.RollBack()
            except Exception:
                pass
else:
    ColorizerWindow().show()
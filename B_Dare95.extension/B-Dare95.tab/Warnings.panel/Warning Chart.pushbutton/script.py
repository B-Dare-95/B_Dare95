# -*- coding: utf-8 -*-
# Keeps the IronPython engine alive after the script returns, which a genuinely
# modeless window requires.
__persistentengine__ = True

__author__ = "Mohamed Bedair"
__doc__ = """__________________________________________________
Description:

Shows all the warnings in your model as a live pie chart, one slice per warning type. Click a slice or its row to select every element involved, and watch the chart update as you fix them.
You can keep working in Revit while the window is open.
__________________________________________________
How-to:

-> Click on the button to open the chart window
-> Hover a slice to see the warning text and counts
-> Click a slice or a list row to select its elements
-> Turn on Isolate on click to also isolate them in the active view
-> Use the gear for settings and the camera to save a PNG
__________________________________________________
Author: Mohamed Bedair"""

import clr
import os
import json
import math

clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")
clr.AddReference("System.Xml")

from System import EventHandler, TimeSpan
from System.Collections.Generic import List
from System.IO import FileStream, FileMode
from System.Windows import (Window, Point, Size, Thickness, Visibility, Clipboard,
                            CornerRadius, RoutedEventHandler, SizeChangedEventHandler,
                            VerticalAlignment, TextAlignment, TextWrapping, TextTrimming,
                            FontWeights)
from System.Windows.Controls import (TextBlock, Border, DockPanel, Dock, Canvas,
                                     TextChangedEventHandler)
from System.Windows.Input import MouseButtonEventHandler, MouseEventHandler, Cursors
from System.Windows.Media import (SolidColorBrush, ColorConverter, PathGeometry,
                                  PathFigure, LineSegment, ArcSegment, SweepDirection,
                                  EllipseGeometry, TranslateTransform, PixelFormats)
from System.Windows.Media.Imaging import RenderTargetBitmap, PngBitmapEncoder, BitmapFrame
from System.Windows.Shapes import Path as WpfPath, Ellipse
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Threading import Dispatcher, DispatcherFrame, DispatcherTimer
from Microsoft.Win32 import SaveFileDialog

from Autodesk.Revit.DB import ElementId, Transaction, TemporaryViewMode
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent
import bd_core as bd

uidoc = __revit__.ActiveUIDocument
doc = uidoc.Document

# Holds open chart instances so they survive after the script returns.
ACTIVE_CHARTS = []


# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------

BG = "#161616"
CARD = "#262626"
SURFACE = "#393939"
MUTED = "#525252"
TEXT = "#F4F4F4"
SUBTEXT = "#A8A8A8"
ACCENT = "#F1C21B"

# Colour-blind friendly defaults, matching the original tool's shades.
DEFAULT_PALETTE = ["#EDE3CC", "#E8EFF3", "#FFC800", "#C4200A", "#9E031E"]

DEFAULTS = {
    "max_warning_count": 1500,
    "palette": list(DEFAULT_PALETTE),
    "auto_refresh": True,
    "refresh_seconds": 3,
    "zoom_on_select": False,
    "isolate_on_select": False,
    "count_mode": "warnings",  # "warnings" or "elements"
}

SETTINGS_DIR = os.path.join(os.getenv("APPDATA") or os.path.expanduser("~"), "B_Dare95")
SETTINGS_PATH = os.path.join(SETTINGS_DIR, "warchart_settings.json")


def load_settings():
    data = dict(DEFAULTS)
    data["palette"] = list(DEFAULT_PALETTE)
    try:
        if os.path.isfile(SETTINGS_PATH):
            f = open(SETTINGS_PATH, "r")
            try:
                stored = json.load(f)
            finally:
                f.close()
            for key in DEFAULTS.keys():
                if key in stored:
                    data[key] = stored[key]
            pal = data.get("palette")
            if not isinstance(pal, list) or len(pal) == 0:
                data["palette"] = list(DEFAULT_PALETTE)
            else:
                data["palette"] = [str(c) for c in pal]
    except Exception:
        data = dict(DEFAULTS)
        data["palette"] = list(DEFAULT_PALETTE)
    return data


def save_settings(data):
    try:
        if not os.path.isdir(SETTINGS_DIR):
            os.makedirs(SETTINGS_DIR)
        f = open(SETTINGS_PATH, "w")
        try:
            json.dump(data, f, indent=2)
        finally:
            f.close()
        return True
    except Exception:
        return False


SETTINGS = load_settings()


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

eid_value = bd.eid_int


def brush(hex_string):
    try:
        return SolidColorBrush(ColorConverter.ConvertFromString(hex_string))
    except Exception:
        return SolidColorBrush(ColorConverter.ConvertFromString("#808080"))


def color_from_hex(hex_string):
    try:
        return ColorConverter.ConvertFromString(hex_string)
    except Exception:
        return ColorConverter.ConvertFromString("#808080")


def hex_from_color(col):
    return "#{0:02X}{1:02X}{2:02X}".format(col.R, col.G, col.B)


def contrast_text(hex_string):
    col = color_from_hex(hex_string)
    lum = 0.299 * col.R + 0.587 * col.G + 0.114 * col.B
    if lum > 150:
        return BG
    return "#FFFFFF"


def show_blocking(window, owner=None):
    """Modeless-but-blocking window, the extension's standard pattern."""
    frame = DispatcherFrame()

    def on_closed(sender, args):
        frame.Continue = False

    window.Closed += EventHandler(on_closed)
    if owner is not None:
        window.Owner = owner
        owner.IsEnabled = False
    else:
        # Parent the window to the Revit main window so it never drops behind it.
        try:
            WindowInteropHelper(window).Owner = __revit__.MainWindowHandle
        except Exception:
            pass
    window.Show()
    Dispatcher.PushFrame(frame)
    if owner is not None:
        owner.IsEnabled = True
        try:
            owner.Activate()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Warning collection
# ---------------------------------------------------------------------------

class WarningGroup(object):
    def __init__(self, key, description):
        self.key = key
        self.description = description
        self.message_count = 0
        self.element_ids = []
        self._seen = {}
        self.color = "#808080"

    def add(self, failure_message):
        self.message_count += 1
        for getter in ("GetFailingElements", "GetAdditionalElements"):
            try:
                ids = getattr(failure_message, getter)()
            except Exception:
                continue
            if ids is None:
                continue
            for eid in ids:
                val = eid_value(eid)
                if val is None or val < 0:
                    continue
                if val in self._seen:
                    continue
                self._seen[val] = True
                self.element_ids.append(eid)

    @property
    def element_count(self):
        return len(self.element_ids)

    def metric(self, mode):
        if mode == "elements":
            return self.element_count
        return self.message_count


def collect_groups():
    """Returns (ordered groups, total metric, total warnings, truncated flag)."""
    groups = {}
    order = []
    truncated = False
    try:
        warnings = doc.GetWarnings()
    except Exception:
        return [], 0, 0, False

    total_warnings = 0
    try:
        total_warnings = warnings.Count
    except Exception:
        total_warnings = len(list(warnings))

    cap = SETTINGS.get("max_warning_count", 1500)
    try:
        cap = int(cap)
    except Exception:
        cap = 1500
    if cap < 1:
        cap = 1

    processed = 0
    for fmsg in warnings:
        if processed >= cap:
            truncated = True
            break
        processed += 1
        try:
            desc = fmsg.GetDescriptionText()
        except Exception:
            desc = "Unknown warning"
        if not desc:
            desc = "Unknown warning"
        try:
            key = fmsg.GetFailureDefinitionId().Guid.ToString()
        except Exception:
            key = desc
        grp = groups.get(key)
        if grp is None:
            grp = WarningGroup(key, desc)
            groups[key] = grp
            order.append(grp)
        grp.add(fmsg)

    mode = SETTINGS.get("count_mode", "warnings")
    ordered = sorted(order, key=lambda g: (-g.metric(mode), g.description))
    ordered = [g for g in ordered if g.metric(mode) > 0]

    palette = SETTINGS.get("palette") or list(DEFAULT_PALETTE)
    for i, grp in enumerate(ordered):
        grp.color = palette[i % len(palette)]

    total = sum([g.metric(mode) for g in ordered])
    return ordered, total, total_warnings, truncated


# ---------------------------------------------------------------------------
# Colour picker dialog
# ---------------------------------------------------------------------------

PICKER_SWATCHES = [
    "#FFFFFF", "#D9D9D9", "#BFBFBF", "#A6A6A6", "#8C8C8C", "#737373", "#000000", "#404040",
    "#FADBD8", "#F5B7B1", "#EC7063", "#E74C3C", "#D64541", "#C0392B", "#9E031E", "#7D2181",
    "#D6EAF8", "#AED6F1", "#3498DB", "#2E86C1", "#2471A3", "#1F618D", "#1A5276", "#154360",
    "#D4EFDF", "#7DCEA0", "#52BE80", "#27AE60", "#FFE95C", "#FFC800", "#F39C12", "#E8542A",
]

# Window layout: picker.xaml, settings.xaml, ui.xaml next to this script (shared colours and styles: lib/bd_theme.xaml)


def pick_color(start_hex, owner):
    """Returns a hex string, or None if cancelled."""
    win = bd.load_window(__file__, "picker.xaml")
    host = win.FindName("SwatchHost")
    preview = win.FindName("Preview")
    hexbox = win.FindName("HexBox")
    state = {"hex": start_hex, "result": None}

    def apply_hex(value):
        try:
            col = ColorConverter.ConvertFromString(value)
        except Exception:
            return False
        state["hex"] = hex_from_color(col)
        preview.Background = SolidColorBrush(col)
        return True

    def on_swatch(sender, args):
        value = sender.Tag
        apply_hex(value)
        hexbox.Text = state["hex"]

    for hexval in PICKER_SWATCHES:
        sw = Border()
        sw.Width = 32
        sw.Height = 32
        sw.Margin = Thickness(2)
        sw.CornerRadius = CornerRadius(4)
        sw.BorderBrush = brush(MUTED)
        sw.BorderThickness = Thickness(1)
        sw.Background = brush(hexval)
        sw.Cursor = Cursors.Hand
        sw.Tag = hexval
        sw.ToolTip = hexval
        sw.MouseLeftButtonDown += MouseButtonEventHandler(on_swatch)
        host.Children.Add(sw)

    apply_hex(start_hex)
    hexbox.Text = state["hex"]

    def on_hex_changed(sender, args):
        apply_hex(hexbox.Text.strip())

    def on_ok(sender, args):
        if apply_hex(hexbox.Text.strip()):
            state["result"] = state["hex"]
        else:
            state["result"] = start_hex
        win.Close()

    def on_cancel(sender, args):
        state["result"] = None
        win.Close()

    hexbox.TextChanged += TextChangedEventHandler(on_hex_changed)
    win.FindName("OkBtn").Click += RoutedEventHandler(on_ok)
    win.FindName("CancelBtn").Click += RoutedEventHandler(on_cancel)

    show_blocking(win, owner)
    return state["result"]


# ---------------------------------------------------------------------------
# Settings dialog
# ---------------------------------------------------------------------------


def open_settings(owner):
    """Returns True when settings were saved."""
    win = bd.load_window(__file__, "settings.xaml")
    state = {
        "palette": list(SETTINGS.get("palette") or DEFAULT_PALETTE),
        "saved": False,
    }
    while len(state["palette"]) < 5:
        state["palette"].append(DEFAULT_PALETTE[len(state["palette"])])
    state["palette"] = state["palette"][:5]

    swatches = [win.FindName("Sw" + str(i)) for i in range(5)]
    maxbox = win.FindName("MaxBox")
    tgl_w = win.FindName("TglWarnings")
    tgl_e = win.FindName("TglElements")
    chk_auto = win.FindName("ChkAuto")
    chk_zoom = win.FindName("ChkZoom")

    maxbox.Text = str(SETTINGS.get("max_warning_count", 1500))
    chk_auto.IsChecked = bool(SETTINGS.get("auto_refresh", True))
    chk_zoom.IsChecked = bool(SETTINGS.get("zoom_on_select", False))
    is_elements = SETTINGS.get("count_mode", "warnings") == "elements"
    tgl_w.IsChecked = not is_elements
    tgl_e.IsChecked = is_elements

    def paint_swatches():
        for i in range(5):
            swatches[i].Background = brush(state["palette"][i])
            swatches[i].ToolTip = state["palette"][i]

    def on_swatch(sender, args):
        idx = int(sender.Tag)
        new_hex = pick_color(state["palette"][idx], win)
        if new_hex:
            state["palette"][idx] = new_hex
            paint_swatches()

    for i in range(5):
        swatches[i].Tag = str(i)
        swatches[i].Click += RoutedEventHandler(on_swatch)
    paint_swatches()

    def on_reset(sender, args):
        state["palette"] = list(DEFAULT_PALETTE)
        paint_swatches()

    def on_tgl_w(sender, args):
        tgl_w.IsChecked = True
        tgl_e.IsChecked = False

    def on_tgl_e(sender, args):
        tgl_w.IsChecked = False
        tgl_e.IsChecked = True

    def on_save(sender, args):
        try:
            cap = int(str(maxbox.Text).strip())
        except Exception:
            cap = DEFAULTS["max_warning_count"]
        if cap < 1:
            cap = 1
        if cap > 1000000:
            cap = 1000000
        SETTINGS["max_warning_count"] = cap
        SETTINGS["palette"] = list(state["palette"])
        SETTINGS["auto_refresh"] = bool(chk_auto.IsChecked)
        SETTINGS["zoom_on_select"] = bool(chk_zoom.IsChecked)
        SETTINGS["count_mode"] = "elements" if tgl_e.IsChecked else "warnings"
        save_settings(SETTINGS)
        state["saved"] = True
        win.Close()

    def on_cancel(sender, args):
        win.Close()

    win.FindName("ResetBtn").Click += RoutedEventHandler(on_reset)
    tgl_w.Click += RoutedEventHandler(on_tgl_w)
    tgl_e.Click += RoutedEventHandler(on_tgl_e)
    win.FindName("SaveBtn").Click += RoutedEventHandler(on_save)
    win.FindName("CancelBtn").Click += RoutedEventHandler(on_cancel)

    show_blocking(win, owner)
    return state["saved"]


# ---------------------------------------------------------------------------
# External event handlers
#
# A modeless window is NOT in a valid Revit API context. Calling
# Selection.SetElementIds() straight from a WPF click handler makes Revit draw
# the elements in the selection colour but never commits the selection set --
# the status bar stays at 0 and the Modify ribbon never appears. Routing the
# call through an ExternalEvent hands it back to Revit's own loop, where the
# selection registers properly.
# ---------------------------------------------------------------------------

class SelectionHandler(IExternalEventHandler):

    def __init__(self, chart):
        self.chart = chart
        self.key = None
        self.action = "select"

    def Execute(self, uiapp):
        try:
            if self.action == "restore":
                self.chart.apply_restore_view(uiapp)
            else:
                self.chart.apply_selection(uiapp, self.key)
        except Exception:
            pass
        self.action = "select"

    def GetName(self):
        return "WarChart Selection Handler"


class RefreshHandler(IExternalEventHandler):

    def __init__(self, chart):
        self.chart = chart
        self.force = False

    def Execute(self, uiapp):
        try:
            self.chart.apply_refresh(uiapp, self.force)
        except Exception:
            pass
        self.force = False

    def GetName(self):
        return "WarChart Refresh Handler"


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------


class WarChart(object):

    def __init__(self):
        self.window = bd.load_window(__file__)
        self.canvas = self.window.FindName("ChartCanvas")
        self.legend_host = self.window.FindName("LegendHost")
        self.filter_box = self.window.FindName("FilterBox")
        self.filter_hint = self.window.FindName("FilterHint")
        self.total_text = self.window.FindName("TotalText")
        self.total_caption = self.window.FindName("TotalCaption")
        self.types_text = self.window.FindName("TypesText")
        self.banner = self.window.FindName("Banner")
        self.banner_text = self.window.FindName("BannerText")
        self.empty_text = self.window.FindName("EmptyText")
        self.isolate_toggle = self.window.FindName("IsolateToggle")

        self.groups = []
        self.total = 0
        self.slice_paths = {}
        self.legend_rows = {}
        self.signature = None
        self.timer = None
        self.last_key = None

        self.select_handler = None
        self.refresh_handler = None
        self.select_event = None
        self.refresh_event = None

        self._wire()

    # -- wiring ------------------------------------------------------------

    def _wire(self):
        self.window.FindName("SettingsBtn").Click += RoutedEventHandler(self.on_settings)
        self.window.FindName("SnapBtn").Click += RoutedEventHandler(self.on_snapshot)
        self.window.FindName("RefreshBtn").Click += RoutedEventHandler(self.on_refresh)
        self.window.FindName("CloseBtn").Click += RoutedEventHandler(self.on_close)
        self.window.FindName("HeaderBar").MouseLeftButtonDown += \
            MouseButtonEventHandler(self.on_drag)
        self.canvas.SizeChanged += SizeChangedEventHandler(self.on_canvas_resized)
        self.filter_box.TextChanged += TextChangedEventHandler(self.on_filter_changed)
        self.isolate_toggle.IsChecked = bool(SETTINGS.get("isolate_on_select", False))
        self.isolate_toggle.Click += RoutedEventHandler(self.on_isolate_toggled)
        self.window.Closed += EventHandler(self.on_closed)

    def on_drag(self, sender, args):
        try:
            self.window.DragMove()
        except Exception:
            pass

    def on_close(self, sender, args):
        self.window.Close()

    def on_closed(self, sender, args):
        if self.timer is not None:
            try:
                self.timer.Stop()
            except Exception:
                pass
            self.timer = None
        for event in (self.select_event, self.refresh_event):
            try:
                if event is not None:
                    event.Dispose()
            except Exception:
                pass
        self.select_event = None
        self.refresh_event = None
        ACTIVE_CHARTS[:] = [c for c in ACTIVE_CHARTS if c is not self]

    def on_canvas_resized(self, sender, args):
        self.draw_chart()

    def on_refresh(self, sender, args):
        self.request_refresh(force=True)

    def on_settings(self, sender, args):
        if open_settings(self.window):
            self.restart_timer()
            self.request_refresh(force=True)

    def on_isolate_toggled(self, sender, args):
        enabled = bool(self.isolate_toggle.IsChecked)
        SETTINGS["isolate_on_select"] = enabled
        save_settings(SETTINGS)
        if enabled:
            # Apply straight away to whatever the user last clicked.
            if self.last_key is not None:
                self.select_group(self.last_key)
        else:
            self.request_restore_view()

    def request_restore_view(self):
        """Queue removal of the temporary isolation put in place by this tool."""
        if self.select_event is None:
            return
        self.select_handler.action = "restore"
        try:
            self.select_event.Raise()
        except Exception:
            pass

    def request_refresh(self, force=False):
        """Ask Revit to re-read warnings from inside a valid API context."""
        if self.refresh_event is None:
            return
        if force:
            self.refresh_handler.force = True
        try:
            self.refresh_event.Raise()
        except Exception:
            pass

    def on_filter_changed(self, sender, args):
        text = self.filter_box.Text or ""
        if text.strip():
            self.filter_hint.Visibility = Visibility.Collapsed
        else:
            self.filter_hint.Visibility = Visibility.Visible
        self.build_legend()

    # -- data --------------------------------------------------------------

    def reload(self, force=False):
        groups, total, total_warnings, truncated = collect_groups()
        signature = (total, len(groups), total_warnings)
        if not force and signature == self.signature:
            return
        self.signature = signature
        self.groups = groups
        self.total = total

        mode = SETTINGS.get("count_mode", "warnings")
        self.total_text.Text = str(total)
        self.total_caption.Text = "elements" if mode == "elements" else "warnings"
        self.types_text.Text = "{0} warning type{1}".format(
            len(groups), "" if len(groups) == 1 else "s")

        if truncated:
            self.banner_text.Text = (
                "Only the first {0} of {1} warnings were read. Raise "
                "'Maximum Warning Count' in settings to include the rest."
            ).format(SETTINGS.get("max_warning_count", 1500), total_warnings)
            self.banner.Visibility = Visibility.Visible
        else:
            self.banner.Visibility = Visibility.Collapsed

        if len(groups) == 0:
            self.empty_text.Visibility = Visibility.Visible
        else:
            self.empty_text.Visibility = Visibility.Collapsed

        self.draw_chart()
        self.build_legend()

    # -- chart -------------------------------------------------------------

    def draw_chart(self):
        self.canvas.Children.Clear()
        self.slice_paths = {}

        width = self.canvas.ActualWidth
        height = self.canvas.ActualHeight
        if width < 60 or height < 60 or self.total <= 0:
            return

        cx = width / 2.0
        cy = height / 2.0
        radius = min(width, height) / 2.0 - 24.0
        if radius < 20:
            return

        mode = SETTINGS.get("count_mode", "warnings")
        start = 0.0
        for grp in self.groups:
            value = grp.metric(mode)
            sweep = 360.0 * value / float(self.total)
            path = self._make_slice(cx, cy, radius, start, sweep, grp)
            self.canvas.Children.Add(path)
            self.slice_paths[grp.key] = path

            if sweep >= 13.0:
                label = self._make_label(cx, cy, radius, start, sweep, grp, value)
                self.canvas.Children.Add(label)
            start += sweep

    def _make_slice(self, cx, cy, radius, start, sweep, grp):
        path = WpfPath()
        path.Fill = brush(grp.color)
        path.Stroke = brush(BG)
        path.StrokeThickness = 1.5
        path.Cursor = Cursors.Hand
        path.Tag = grp.key
        path.ToolTip = "{0}\n{1} warning(s)  |  {2} element(s)  |  {3:.2f}%".format(
            grp.description, grp.message_count, grp.element_count,
            100.0 * grp.metric(SETTINGS.get("count_mode", "warnings")) / float(self.total))

        if sweep >= 359.99:
            path.Data = EllipseGeometry(Point(cx, cy), radius, radius)
        else:
            a0 = math.radians(start)
            a1 = math.radians(start + sweep)
            p0 = Point(cx + radius * math.sin(a0), cy - radius * math.cos(a0))
            p1 = Point(cx + radius * math.sin(a1), cy - radius * math.cos(a1))
            fig = PathFigure()
            fig.StartPoint = Point(cx, cy)
            fig.Segments.Add(LineSegment(p0, True))
            fig.Segments.Add(ArcSegment(p1, Size(radius, radius), 0.0,
                                        sweep > 180.0, SweepDirection.Clockwise, True))
            fig.IsClosed = True
            geo = PathGeometry()
            geo.Figures.Add(fig)
            path.Data = geo

        mid = math.radians(start + sweep / 2.0)
        path.RenderTransform = TranslateTransform(0, 0)

        offset = [math.sin(mid) * 9.0, -math.cos(mid) * 9.0]

        def on_enter(sender, args, off=offset):
            sender.RenderTransform = TranslateTransform(off[0], off[1])
            sender.Stroke = brush(ACCENT)
            sender.StrokeThickness = 2.0
            self.highlight_legend(sender.Tag, True)

        def on_leave(sender, args):
            sender.RenderTransform = TranslateTransform(0, 0)
            sender.Stroke = brush(BG)
            sender.StrokeThickness = 1.5
            self.highlight_legend(sender.Tag, False)

        def on_click(sender, args):
            self.select_group(sender.Tag)

        path.MouseEnter += MouseEventHandler(on_enter)
        path.MouseLeave += MouseEventHandler(on_leave)
        path.MouseLeftButtonDown += MouseButtonEventHandler(on_click)
        return path

    def _make_label(self, cx, cy, radius, start, sweep, grp, value):
        mid = math.radians(start + sweep / 2.0)
        lx = cx + radius * 0.64 * math.sin(mid)
        ly = cy - radius * 0.64 * math.cos(mid)

        block = TextBlock()
        block.Text = "{0}\n({1:.2f}%)".format(value, 100.0 * value / float(self.total))
        block.Foreground = brush(contrast_text(grp.color))
        block.FontSize = 11
        block.FontWeight = FontWeights.SemiBold
        block.TextAlignment = TextAlignment.Center
        block.IsHitTestVisible = False
        block.Measure(Size(400, 400))
        Canvas.SetLeft(block, lx - block.DesiredSize.Width / 2.0)
        Canvas.SetTop(block, ly - block.DesiredSize.Height / 2.0)
        return block

    # -- legend ------------------------------------------------------------

    def build_legend(self):
        self.legend_host.Children.Clear()
        self.legend_rows = {}
        needle = (self.filter_box.Text or "").strip().lower()
        mode = SETTINGS.get("count_mode", "warnings")

        shown = 0
        for grp in self.groups:
            if needle and needle not in grp.description.lower():
                continue
            shown += 1
            row = Border()
            row.Background = brush(CARD)
            row.CornerRadius = CornerRadius(5)
            row.Padding = Thickness(8, 6, 8, 6)
            row.Margin = Thickness(0, 0, 0, 4)
            row.Cursor = Cursors.Hand
            row.Tag = grp.key
            row.ToolTip = "{0}\n{1} warning(s)  |  {2} element(s)".format(
                grp.description, grp.message_count, grp.element_count)

            panel = DockPanel()
            panel.LastChildFill = True

            count = TextBlock()
            count.Text = str(grp.metric(mode))
            count.Foreground = brush(TEXT)
            count.FontSize = 12
            count.FontWeight = FontWeights.SemiBold
            count.Width = 34
            count.TextAlignment = TextAlignment.Right
            count.VerticalAlignment = VerticalAlignment.Center
            DockPanel.SetDock(count, Dock.Left)
            panel.Children.Add(count)

            dot = Ellipse()
            dot.Width = 11
            dot.Height = 11
            dot.Fill = brush(grp.color)
            dot.Margin = Thickness(10, 0, 8, 0)
            dot.VerticalAlignment = VerticalAlignment.Center
            DockPanel.SetDock(dot, Dock.Left)
            panel.Children.Add(dot)

            desc = TextBlock()
            desc.Text = grp.description
            desc.Foreground = brush(SUBTEXT)
            desc.FontSize = 12
            desc.TextTrimming = TextTrimming.CharacterEllipsis
            desc.TextWrapping = TextWrapping.NoWrap
            desc.VerticalAlignment = VerticalAlignment.Center
            panel.Children.Add(desc)

            row.Child = panel

            def on_enter(sender, args):
                sender.Background = brush(SURFACE)
                self.explode_slice(sender.Tag, True)

            def on_leave(sender, args):
                sender.Background = brush(CARD)
                self.explode_slice(sender.Tag, False)

            def on_click(sender, args):
                self.select_group(sender.Tag)

            row.MouseEnter += MouseEventHandler(on_enter)
            row.MouseLeave += MouseEventHandler(on_leave)
            row.MouseLeftButtonDown += MouseButtonEventHandler(on_click)

            self.legend_host.Children.Add(row)
            self.legend_rows[grp.key] = row

        if shown == 0 and needle:
            empty = TextBlock()
            empty.Text = "No warning matches this search."
            empty.Foreground = brush(MUTED)
            empty.FontSize = 12
            empty.Margin = Thickness(4, 8, 0, 0)
            self.legend_host.Children.Add(empty)

    def highlight_legend(self, key, on):
        row = self.legend_rows.get(key)
        if row is None:
            return
        row.Background = brush(SURFACE) if on else brush(CARD)

    def explode_slice(self, key, on):
        path = self.slice_paths.get(key)
        if path is None:
            return
        if not on:
            path.RenderTransform = TranslateTransform(0, 0)
            path.Stroke = brush(BG)
            path.StrokeThickness = 1.5
            return
        idx = None
        mode = SETTINGS.get("count_mode", "warnings")
        start = 0.0
        for grp in self.groups:
            sweep = 360.0 * grp.metric(mode) / float(self.total or 1)
            if grp.key == key:
                idx = start + sweep / 2.0
                break
            start += sweep
        if idx is None:
            return
        mid = math.radians(idx)
        path.RenderTransform = TranslateTransform(math.sin(mid) * 9.0, -math.cos(mid) * 9.0)
        path.Stroke = brush(ACCENT)
        path.StrokeThickness = 2.0

    # -- actions -----------------------------------------------------------

    def find_group(self, key):
        for grp in self.groups:
            if grp.key == key:
                return grp
        return None

    def select_group(self, key):
        """Queue the selection. Revit performs it inside a valid API context."""
        if self.select_event is None or self.find_group(key) is None:
            return
        self.last_key = key
        self.select_handler.key = key
        self.select_handler.action = "select"
        try:
            self.select_event.Raise()
        except Exception:
            pass

    def apply_selection(self, uiapp, key):
        """Runs inside the ExternalEvent, i.e. in a valid Revit API context."""
        global uidoc, doc
        if key is None:
            return
        active_uidoc = uiapp.ActiveUIDocument
        if active_uidoc is None:
            return
        uidoc = active_uidoc
        doc = active_uidoc.Document

        grp = self.find_group(key)
        if grp is None:
            return

        ids = List[ElementId]()
        for eid in grp.element_ids:
            try:
                if doc.GetElement(eid) is not None:
                    ids.Add(eid)
            except Exception:
                continue

        if ids.Count == 0:
            self.banner_text.Text = ("No selectable element found for this warning "
                                     "(its elements may live in a linked model).")
            self.banner.Visibility = Visibility.Visible
            return

        try:
            active_uidoc.Selection.SetElementIds(ids)
        except Exception:
            return
        if SETTINGS.get("isolate_on_select", False):
            self.isolate_in_view(active_uidoc, ids)
        elif SETTINGS.get("zoom_on_select", False):
            try:
                active_uidoc.ShowElements(ids)
            except Exception:
                pass
        try:
            active_uidoc.RefreshActiveView()
        except Exception:
            pass

    def isolate_in_view(self, active_uidoc, ids):
        """Temporary isolate in the active view. Needs a transaction."""
        view = active_uidoc.ActiveView
        if view is None:
            return
        try:
            usable = view.CanUseTemporaryVisibilityModes()
        except Exception:
            usable = False
        if not usable:
            self.banner_text.Text = ("The active view does not support temporary "
                                     "isolation, so the elements were only selected.")
            self.banner.Visibility = Visibility.Visible
            return

        t = Transaction(active_uidoc.Document, "WarChart: Isolate Warning Elements")
        t.Start()
        try:
            if view.IsTemporaryHideIsolateActive():
                view.DisableTemporaryViewMode(TemporaryViewMode.TemporaryHideIsolate)
            view.IsolateElementsTemporary(ids)
            t.Commit()
        except Exception:
            t.RollBack()

    def apply_restore_view(self, uiapp):
        """Drop the temporary isolation again. Runs in a valid API context."""
        active_uidoc = uiapp.ActiveUIDocument
        if active_uidoc is None:
            return
        view = active_uidoc.ActiveView
        if view is None:
            return
        try:
            if not view.IsTemporaryHideIsolateActive():
                return
        except Exception:
            return

        t = Transaction(active_uidoc.Document, "WarChart: Restore View")
        t.Start()
        try:
            view.DisableTemporaryViewMode(TemporaryViewMode.TemporaryHideIsolate)
            t.Commit()
        except Exception:
            t.RollBack()
        try:
            active_uidoc.RefreshActiveView()
        except Exception:
            pass

    def apply_refresh(self, uiapp, force):
        """Runs inside the ExternalEvent, i.e. in a valid Revit API context."""
        global uidoc, doc
        active_uidoc = uiapp.ActiveUIDocument
        if active_uidoc is None:
            return
        uidoc = active_uidoc
        doc = active_uidoc.Document
        self.reload(force=force)

    def on_snapshot(self, sender, args):
        root = self.window.FindName("SnapRoot")
        try:
            width = int(root.ActualWidth)
            height = int(root.ActualHeight)
            if width < 2 or height < 2:
                return
            rtb = RenderTargetBitmap(width, height, 96, 96, PixelFormats.Pbgra32)
            rtb.Render(root)
            try:
                Clipboard.SetImage(rtb)
            except Exception:
                pass
            dlg = SaveFileDialog()
            dlg.Filter = "PNG image (*.png)|*.png"
            dlg.FileName = "WarChart.png"
            if dlg.ShowDialog():
                encoder = PngBitmapEncoder()
                encoder.Frames.Add(BitmapFrame.Create(rtb))
                stream = FileStream(dlg.FileName, FileMode.Create)
                try:
                    encoder.Save(stream)
                finally:
                    stream.Close()
        except Exception:
            pass

    # -- timer -------------------------------------------------------------

    def restart_timer(self):
        if self.timer is not None:
            try:
                self.timer.Stop()
            except Exception:
                pass
            self.timer = None
        if not SETTINGS.get("auto_refresh", True):
            return
        seconds = SETTINGS.get("refresh_seconds", 3)
        try:
            seconds = float(seconds)
        except Exception:
            seconds = 3.0
        if seconds < 1.0:
            seconds = 1.0
        self.timer = DispatcherTimer()
        self.timer.Interval = TimeSpan.FromSeconds(seconds)
        self.timer.Tick += EventHandler(self.on_tick)
        self.timer.Start()

    def on_tick(self, sender, args):
        self.request_refresh(force=False)

    # -- run ---------------------------------------------------------------

    def run(self):
        # ExternalEvent.Create must be called from a valid API context, which is
        # exactly where we are right now (inside the pyRevit command).
        self.select_handler = SelectionHandler(self)
        self.refresh_handler = RefreshHandler(self)
        self.select_event = ExternalEvent.Create(self.select_handler)
        self.refresh_event = ExternalEvent.Create(self.refresh_handler)

        self.reload(force=True)
        self.restart_timer()

        try:
            WindowInteropHelper(self.window).Owner = __revit__.MainWindowHandle
        except Exception:
            pass

        # Truly modeless: no PushFrame, so Revit's main loop stays free to run
        # the external events. ACTIVE_CHARTS keeps the instance alive after the
        # script returns.
        ACTIVE_CHARTS.append(self)
        self.window.Show()


def main():
    if doc is None:
        return
    for chart in list(ACTIVE_CHARTS):
        try:
            chart.window.Activate()
            chart.request_refresh(force=True)
            return
        except Exception:
            ACTIVE_CHARTS.remove(chart)
    WarChart().run()


main()
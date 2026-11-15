# -*- coding: utf-8 -*-
__doc__ = """Turns CAD layers into Revit detail lines in the active view, with each group of layers drawn in the line style you bind it to.

How-to:
-> Open the plan, section, elevation, detail or drafting view you want the lines in
-> Select the CAD first, or click the button and pick it
-> Pick one or more layers on the left, pick a line style in the middle, then press Bind (or double-click the style)
-> Repeat for the next group of layers, each binding shows up on the right
-> Press Convert to draw everything in one go, and the new lines are selected when it finishes

Author: Mohamed Bedair"""

import clr
clr.AddReference("System")
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from System import EventHandler
from System.Collections.Generic import List
from System.Windows import (
    CornerRadius, FontWeights, RoutedEventHandler, TextTrimming, Thickness,
    VerticalAlignment, Visibility
)
from System.Windows.Controls import (
    Border, Button, DockPanel, Dock, ListBoxItem, StackPanel, TextBlock,
    SelectionChangedEventHandler, TextChangedEventHandler
)
from System.Windows.Input import Key, KeyEventHandler, MouseButtonEventHandler
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Media import BrushConverter
from System.Windows.Threading import Dispatcher, DispatcherFrame

from Autodesk.Revit.DB import (
    BuiltInCategory, Curve, ElementId, GeometryInstance, GraphicsStyleType,
    ImportInstance, Line, Options, PolyLine, Transaction, Transform,
    ViewPlan, XYZ
)
from Autodesk.Revit.UI import (
    TaskDialog, TaskDialogCommonButtons, TaskDialogResult
)
from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException
import bd_core as bd


uidoc = __revit__.ActiveUIDocument
doc = uidoc.Document
view = uidoc.ActiveView

TOOL_NAME = "CAD to Detail Lines"
NO_LAYER = "(no layer)"
PLANE_TOL = 0.001          # ft - how far a curve may wander off a flat plane
BIG_RUN = 5000             # ask before drawing more curves than this
ALLOWED_VIEWS = {
    "FloorPlan", "CeilingPlan", "EngineeringPlan", "AreaPlan",
    "Section", "Elevation", "Detail", "DraftingView", "Legend"
}
# Line styles that belong to other tools and can't be given to detail lines
NOT_DETAIL_STYLES = [
    "OST_RoomSeparationLines", "OST_MEPSpaceSeparationLines",
    "OST_AreaSchemeLines", "OST_SketchLines", "OST_InsulationLines",
    "OST_AxisOfRotation"
]


class StyleNotAllowed(Exception):
    pass


# ---------------------------------------------------------------- helpers
eid_int = bd.eid_int


def alert(message):
    TaskDialog.Show(TOOL_NAME, message)


def confirm(message):
    res = TaskDialog.Show(
        TOOL_NAME, message,
        TaskDialogCommonButtons.Yes | TaskDialogCommonButtons.No
    )
    return res == TaskDialogResult.Yes


def CadFilter():
    return bd.ClassFilter(ImportInstance)


def get_cad():
    picked = [doc.GetElement(i) for i in uidoc.Selection.GetElementIds()]
    cads = [e for e in picked if isinstance(e, ImportInstance)]
    if len(cads) == 1:
        return cads[0]
    try:
        ref = uidoc.Selection.PickObject(
            ObjectType.Element, CadFilter(), "Pick the CAD to convert")
    except OperationCanceledException:
        return None
    return doc.GetElement(ref.ElementId)


def get_line_styles():
    """{name: GraphicsStyle} for every line style a detail line can use."""
    blocked = set()
    for bic_name in NOT_DETAIL_STYLES:
        bic = getattr(BuiltInCategory, bic_name, None)
        if bic is not None:
            blocked.add(int(bic))

    lines_cat = doc.Settings.Categories.get_Item(BuiltInCategory.OST_Lines)
    styles = {}
    for sub in lines_cat.SubCategories:
        if eid_int(sub.Id) in blocked:
            continue
        gs = sub.GetGraphicsStyle(GraphicsStyleType.Projection)
        if gs is not None:
            styles[sub.Name] = gs
    return styles


# ---------------------------------------------------------------- CAD geometry
def layer_of(geo_obj, cache):
    gid = geo_obj.GraphicsStyleId
    key = eid_int(gid)
    if key not in cache:
        name = NO_LAYER
        style = doc.GetElement(gid) if gid != ElementId.InvalidElementId else None
        if style is not None and style.GraphicsStyleCategory is not None:
            name = style.GraphicsStyleCategory.Name
        cache[key] = name
    return cache[key]


def move_curve(curve, tf):
    """Curve into model space. Falls back to points if the transform is refused."""
    if tf.IsIdentity:
        return curve
    try:
        return curve.CreateTransformed(tf)
    except Exception:
        return [tf.OfPoint(p) for p in curve.Tessellate()]


def collect_cad_geometry(cad):
    """Returns ([(layer, curve_or_points), ...], skipped_count).
    Blocks are walked with their transforms stacked up."""
    opts = Options()
    opts.ComputeReferences = False
    opts.IncludeNonVisibleObjects = False

    items = []
    skipped = 0
    cache = {}
    stack = [(cad.get_Geometry(opts), Transform.Identity)]
    while stack:
        geo_elem, tf = stack.pop()
        if geo_elem is None:
            continue
        for obj in geo_elem:
            if isinstance(obj, GeometryInstance):
                stack.append((obj.GetSymbolGeometry(), tf.Multiply(obj.Transform)))
            elif isinstance(obj, Curve):
                items.append((layer_of(obj, cache), move_curve(obj, tf)))
            elif isinstance(obj, PolyLine):
                pts = [tf.OfPoint(p) for p in obj.GetCoordinates()]
                items.append((layer_of(obj, cache), pts))
            else:
                skipped += 1
    return items, skipped


# ---------------------------------------------------------------- view plane
def view_plane(v):
    normal = v.ViewDirection.Normalize()
    sketch = v.SketchPlane
    if sketch is not None:
        plane = sketch.GetPlane()
        return plane.Origin, plane.Normal
    if isinstance(v, ViewPlan) and v.GenLevel is not None:
        return XYZ(0, 0, v.GenLevel.ProjectElevation), normal
    return v.Origin, normal


def lines_from_points(pts, short):
    lines = []
    if not pts:
        return lines
    prev = pts[0]
    for p in pts[1:]:
        if p.DistanceTo(prev) >= short:
            lines.append(Line.CreateBound(prev, p))
            prev = p
    return lines


def fit_to_plane(geom, origin, normal, short):
    """Returns (curves, approximated). Flat curves are slid onto the view plane
    unchanged; anything tilted is flattened into straight segments."""
    if isinstance(geom, Curve):
        try:
            pts = list(geom.Tessellate())
        except Exception:
            return [], False
        dists = [(p - origin).DotProduct(normal) for p in pts]
        if max(dists) - min(dists) <= PLANE_TOL:
            d = dists[0]
            if abs(d) < 1e-9:
                return [geom], False
            try:
                tf = Transform.CreateTranslation(normal.Multiply(-d))
                return [geom.CreateTransformed(tf)], False
            except Exception:
                pass
        flat = [p - normal.Multiply(d) for p, d in zip(pts, dists)]
        return lines_from_points(flat, short), not isinstance(geom, Line)

    flat = [p - normal.Multiply((p - origin).DotProduct(normal)) for p in geom]
    return lines_from_points(flat, short), False


# ---------------------------------------------------------------- conversion
def convert(cad_items, bindings, styles):
    """bindings: {layer_name: style_name}. Every bound layer is drawn with its style."""
    origin, normal = view_plane(view)
    short = doc.Application.ShortCurveTolerance
    stats = {"created": [], "by_style": {}, "approx": 0, "short": 0, "failed": 0}
    checked = set()

    def draw(curve, style_name):
        try:
            dc = doc.Create.NewDetailCurve(view, curve)
        except Exception:
            return False
        if style_name not in checked:
            allowed = set(eid_int(i) for i in dc.GetLineStyleIds())
            if eid_int(styles[style_name].Id) not in allowed:
                raise StyleNotAllowed(style_name)
            checked.add(style_name)
        dc.LineStyle = styles[style_name]
        stats["created"].append(dc.Id)
        stats["by_style"][style_name] = stats["by_style"].get(style_name, 0) + 1
        return True

    t = Transaction(doc, TOOL_NAME)
    t.Start()
    try:
        for layer, geom in cad_items:
            style_name = bindings.get(layer)
            if style_name is None:
                continue
            curves, approx = fit_to_plane(geom, origin, normal, short)
            if not curves:
                stats["short"] += 1
                continue
            if approx:
                stats["approx"] += 1
            for crv in curves:
                if crv.Length < short:
                    stats["short"] += 1
                    continue
                if draw(crv, style_name):
                    continue
                # Revit refused this curve type - draw it as straight segments
                segs = lines_from_points(list(crv.Tessellate()), short)
                made = [draw(s, style_name) for s in segs]
                if any(made):
                    stats["approx"] += 1
                else:
                    stats["failed"] += 1
        t.Commit()
    except Exception:
        t.RollBack()
        raise
    return stats


def report(stats, skipped, bindings):
    layers_per_style = {}
    for layer, style_name in bindings.items():
        layers_per_style[style_name] = layers_per_style.get(style_name, 0) + 1

    lines = ["Created {:,} detail lines in '{}'.".format(len(stats["created"]), view.Name), ""]
    for style_name in sorted(layers_per_style, key=lambda n: n.lower()):
        lines.append("{}:  {:,} lines from {} layer(s)".format(
            style_name, stats["by_style"].get(style_name, 0), layers_per_style[style_name]))

    extras = []
    if stats["approx"]:
        extras.append("{:,} curves were redrawn as straight segments.".format(stats["approx"]))
    if stats["short"]:
        extras.append("{:,} curves were too short for Revit and were skipped.".format(stats["short"]))
    if stats["failed"]:
        extras.append("{:,} curves could not be drawn.".format(stats["failed"]))
    if skipped:
        extras.append("{:,} non-line objects (points, solids, fills) were ignored.".format(skipped))
    if extras:
        lines.append("")
        lines.extend(extras)
    alert("\n".join(lines))


# ---------------------------------------------------------------- UI (IBM Carbon)
# Window layout: ui.xaml next to this script (shared colours and styles: lib/bd_theme.xaml)

_BC = BrushConverter()
TEXT_BRUSH = _BC.ConvertFromString("#F4F4F4")
SUB_BRUSH = _BC.ConvertFromString("#A8A8A8")
ACCENT_BRUSH = _BC.ConvertFromString("#F1C21B")
SURFACE_BRUSH = _BC.ConvertFromString("#393939")


def text_block(text, brush, size=None, bold=False):
    tb = TextBlock()
    tb.Text = text
    tb.Foreground = brush
    tb.VerticalAlignment = VerticalAlignment.Center
    tb.TextTrimming = TextTrimming.CharacterEllipsis
    if size:
        tb.FontSize = size
    if bold:
        tb.FontWeight = FontWeights.SemiBold
    return tb


def make_layer_item(name, count):
    """Layer row: name | bound style (accent) | line count. Returns (item, style_tb)."""
    item = ListBoxItem()
    panel = DockPanel()
    tb_count = text_block("{:,}".format(count), SUB_BRUSH)
    tb_count.Margin = Thickness(10, 0, 0, 0)
    DockPanel.SetDock(tb_count, Dock.Right)
    tb_style = text_block("", ACCENT_BRUSH, size=11)
    tb_style.Margin = Thickness(10, 0, 0, 0)
    tb_style.MaxWidth = 120
    DockPanel.SetDock(tb_style, Dock.Right)
    panel.Children.Add(tb_count)
    panel.Children.Add(tb_style)
    panel.Children.Add(text_block(name, TEXT_BRUSH))
    item.Content = panel
    item.Tag = name
    item.ToolTip = name
    return item, tb_style


def make_style_item(name):
    item = ListBoxItem()
    item.Content = text_block(name, TEXT_BRUSH)
    item.Tag = name
    item.ToolTip = name
    return item


def ask_bindings(cad_name, layer_counts, style_names):
    """Returns {layer_name: style_name} or None if cancelled."""
    window = bd.load_window(__file__)
    find = window.FindName
    layer_list = find("LayerList")
    style_list = find("StyleList")
    layer_search = find("LayerSearch")
    style_search = find("StyleSearch")
    hide_bound = find("HideBoundBtn")
    bind_btn = find("BindBtn")
    convert_btn = find("ConvertBtn")
    bind_panel = find("BindPanel")
    link_style = window.FindResource("LinkBtn")

    bindings = {}            # layer -> style
    style_labels = {}        # layer -> TextBlock showing its bound style
    result = {"ok": False}

    find("SubTitle").Text = u"{}   \u00b7   {}".format(cad_name, view.Name)

    for name in sorted(layer_counts, key=lambda n: n.lower()):
        item, tb_style = make_layer_item(name, layer_counts[name])
        style_labels[name] = tb_style
        layer_list.Items.Add(item)
    for name in sorted(style_names, key=lambda n: n.lower()):
        style_list.Items.Add(make_style_item(name))

    # ---- filtering
    def filter_layers(*_):
        query = layer_search.Text.strip().lower()
        find("LayerHint").Visibility = Visibility.Collapsed if layer_search.Text else Visibility.Visible
        hide = bool(hide_bound.IsChecked)
        for it in layer_list.Items:
            show = (not query or query in it.Tag.lower()) and not (hide and it.Tag in bindings)
            it.Visibility = Visibility.Visible if show else Visibility.Collapsed
            if not show and it.IsSelected and hide and it.Tag in bindings:
                it.IsSelected = False

    def filter_styles(*_):
        query = style_search.Text.strip().lower()
        find("StyleHint").Visibility = Visibility.Collapsed if style_search.Text else Visibility.Visible
        for it in style_list.Items:
            show = not query or query in it.Tag.lower()
            it.Visibility = Visibility.Visible if show else Visibility.Collapsed

    # ---- state / status
    def refresh(*_):
        picked = layer_list.SelectedItems.Count
        style_item = style_list.SelectedItem
        can_bind = picked > 0 and style_item is not None
        bind_btn.IsEnabled = can_bind
        bind_btn.Content = u"Bind {} layer(s)".format(picked) if picked else "Bind"

        bound_lines = sum(layer_counts[l] for l in bindings)
        n_styles = len(set(bindings.values()))
        status = find("StatusText")
        if bindings:
            status.Text = u"{} line style(s)  \u00b7  {} layer(s)  \u00b7  {:,} lines ready".format(
                n_styles, len(bindings), bound_lines)
        else:
            status.Text = "Nothing bound yet"
        convert_btn.IsEnabled = bool(bindings)

    # ---- bindings panel
    def rebuild_bindings():
        bind_panel.Children.Clear()
        groups = {}
        for layer, style_name in bindings.items():
            groups.setdefault(style_name, []).append(layer)

        for style_name in sorted(groups, key=lambda n: n.lower()):
            layers = sorted(groups[style_name], key=lambda n: n.lower())
            card = Border()
            card.Background = SURFACE_BRUSH
            card.CornerRadius = CornerRadius(4)
            card.BorderBrush = ACCENT_BRUSH
            card.BorderThickness = Thickness(3, 0, 0, 0)
            card.Padding = Thickness(10, 8, 4, 8)
            card.Margin = Thickness(0, 0, 6, 8)
            stack = StackPanel()

            head = DockPanel()
            head.Margin = Thickness(0, 0, 0, 4)
            rm = Button()
            rm.Style = link_style
            rm.Content = "Remove"
            rm.Tag = style_name
            rm.ToolTip = "Unbind every layer from this style"
            rm.Click += RoutedEventHandler(on_remove_style)
            DockPanel.SetDock(rm, Dock.Right)
            lines = sum(layer_counts[l] for l in layers)
            tb_lines = text_block("{:,} lines".format(lines), SUB_BRUSH, size=12)
            tb_lines.Margin = Thickness(8, 0, 4, 0)
            DockPanel.SetDock(tb_lines, Dock.Right)
            head.Children.Add(rm)
            head.Children.Add(tb_lines)
            head.Children.Add(text_block(style_name, TEXT_BRUSH, bold=True))
            stack.Children.Add(head)

            for layer in layers:
                row = DockPanel()
                x = Button()
                x.Style = link_style
                x.Content = u"\u2715"
                x.Tag = layer
                x.ToolTip = "Unbind this layer"
                x.Click += RoutedEventHandler(on_remove_layer)
                DockPanel.SetDock(x, Dock.Right)
                row.Children.Add(x)
                tb_layer = text_block(layer, SUB_BRUSH, size=12)
                tb_layer.ToolTip = layer
                row.Children.Add(tb_layer)
                stack.Children.Add(row)

            card.Child = stack
            bind_panel.Children.Add(card)

        find("BindEmpty").Visibility = Visibility.Collapsed if bindings else Visibility.Visible
        for layer, tb in style_labels.items():
            tb.Text = bindings.get(layer, "")
        filter_layers()
        refresh()

    # ---- actions
    def do_bind():
        style_item = style_list.SelectedItem
        picked = [it.Tag for it in layer_list.SelectedItems]
        if style_item is None or not picked:
            return
        for layer in picked:
            bindings[layer] = style_item.Tag      # re-binding moves the layer
        layer_list.UnselectAll()
        rebuild_bindings()

    def on_remove_style(sender, args):
        for layer in [l for l, s in bindings.items() if s == sender.Tag]:
            del bindings[layer]
        rebuild_bindings()

    def on_remove_layer(sender, args):
        bindings.pop(sender.Tag, None)
        rebuild_bindings()

    def on_clear_all(sender, args):
        bindings.clear()
        rebuild_bindings()

    def set_visible(selected):
        for it in layer_list.Items:
            if it.Visibility == Visibility.Visible:
                it.IsSelected = selected

    def on_style_double_click(sender, args):
        if bind_btn.IsEnabled:
            do_bind()

    def on_convert(sender, args):
        result["ok"] = True
        window.Close()

    def on_key(sender, args):
        if args.Key == Key.Escape:
            window.Close()

    layer_search.TextChanged += TextChangedEventHandler(filter_layers)
    style_search.TextChanged += TextChangedEventHandler(filter_styles)
    hide_bound.Click += RoutedEventHandler(filter_layers)
    layer_list.SelectionChanged += SelectionChangedEventHandler(refresh)
    style_list.SelectionChanged += SelectionChangedEventHandler(refresh)
    style_list.MouseDoubleClick += MouseButtonEventHandler(on_style_double_click)
    bind_btn.Click += RoutedEventHandler(lambda s, e: do_bind())
    find("ClearBindBtn").Click += RoutedEventHandler(on_clear_all)
    find("AllBtn").Click += RoutedEventHandler(lambda s, e: set_visible(True))
    find("NoneBtn").Click += RoutedEventHandler(lambda s, e: set_visible(False))
    find("CancelBtn").Click += RoutedEventHandler(lambda s, e: window.Close())
    find("CloseBtn").Click += RoutedEventHandler(lambda s, e: window.Close())
    convert_btn.Click += RoutedEventHandler(on_convert)
    find("HeaderBar").MouseLeftButtonDown += MouseButtonEventHandler(
        lambda s, e: window.DragMove())
    window.KeyDown += KeyEventHandler(on_key)
    rebuild_bindings()

    try:
        WindowInteropHelper(window).Owner = __revit__.MainWindowHandle
    except Exception:
        pass

    frame = DispatcherFrame()

    def on_closed(sender, args):
        frame.Continue = False

    window.Closed += EventHandler(on_closed)
    window.Show()
    layer_search.Focus()
    Dispatcher.PushFrame(frame)

    if not result["ok"] or not bindings:
        return None
    return dict(bindings)


# ---------------------------------------------------------------- main
def main():
    if view.IsTemplate or str(view.ViewType) not in ALLOWED_VIEWS:
        alert("Detail lines can't be drawn in this view.\n"
              "Open a plan, section, elevation, detail or drafting view and try again.")
        return

    cad = get_cad()
    if cad is None:
        return

    items, skipped = collect_cad_geometry(cad)
    if not items:
        alert("No lines were found in '{}'.".format(cad.Category.Name))
        return

    layer_counts = {}
    for layer, _geom in items:
        layer_counts[layer] = layer_counts.get(layer, 0) + 1

    styles = get_line_styles()
    bindings = ask_bindings(cad.Category.Name, layer_counts, list(styles.keys()))
    if bindings is None:
        return

    chosen = [it for it in items if it[0] in bindings]
    if len(chosen) > BIG_RUN and not confirm(
            "The bound layers have {:,} lines. Converting them may take a while.\n\n"
            "Continue?".format(len(chosen))):
        return

    try:
        stats = convert(chosen, bindings, styles)
    except StyleNotAllowed as err:
        alert("'{}' can't be used for detail lines. Nothing was changed.\n"
              "Run the tool again and bind those layers to another line style.".format(err.args[0]))
        return

    if stats["created"]:
        uidoc.Selection.SetElementIds(List[ElementId](stats["created"]))
    report(stats, skipped, bindings)


main()
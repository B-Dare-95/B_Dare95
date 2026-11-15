# -*- coding: utf-8 -*-
__doc__ = """Turns every line in a linked or imported CAD into Revit detail lines in the active view. All layers are converted, drawn in the line style you pick.

How-to:
-> Open the plan, section, elevation, detail or drafting view you want the lines in
-> Select the CAD first, or click the button and pick it
-> Pick a line style and press Convert (or double-click the style)
-> The new detail lines are selected when it finishes

Author: Mohamed Bedair"""

import clr
clr.AddReference("System")
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from System import EventHandler
from System.Collections.Generic import List
from System.Windows import RoutedEventHandler, TextTrimming, Visibility
from System.Windows.Controls import (
    ListBoxItem, TextBlock, SelectionChangedEventHandler, TextChangedEventHandler
)
from System.Windows.Input import Key, KeyEventHandler, MouseButtonEventHandler
from System.Windows.Interop import WindowInteropHelper
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


# ---------------------------------------------------------------- line styles
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


# ---------------------------------------------------------------- conversion
def convert(cad_items, line_style):
    origin, normal = view_plane(view)
    short = doc.Application.ShortCurveTolerance
    style_key = eid_int(line_style.Id)
    stats = {"created": [], "approx": 0, "short": 0, "failed": 0}
    checked = [False]

    def draw(curve):
        try:
            dc = doc.Create.NewDetailCurve(view, curve)
        except Exception:
            return False
        if not checked[0]:
            allowed = set(eid_int(i) for i in dc.GetLineStyleIds())
            if style_key not in allowed:
                raise StyleNotAllowed()
            checked[0] = True
        dc.LineStyle = line_style
        stats["created"].append(dc.Id)
        return True

    t = Transaction(doc, TOOL_NAME)
    t.Start()
    try:
        for _layer, geom in cad_items:
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
                if draw(crv):
                    continue
                # Revit refused this curve type - draw it as straight segments
                segs = lines_from_points(list(crv.Tessellate()), short)
                made = [draw(s) for s in segs]
                if any(made):
                    stats["approx"] += 1
                else:
                    stats["failed"] += 1
        t.Commit()
    except Exception:
        t.RollBack()
        raise
    return stats


def report(stats, skipped, style_name):
    lines = ["Created {:,} detail lines in '{}', drawn as '{}'.".format(
        len(stats["created"]), view.Name, style_name)]
    if stats["approx"]:
        lines.append("{:,} curves were redrawn as straight segments.".format(stats["approx"]))
    if stats["short"]:
        lines.append("{:,} curves were too short for Revit and were skipped.".format(stats["short"]))
    if stats["failed"]:
        lines.append("{:,} curves could not be drawn.".format(stats["failed"]))
    if skipped:
        lines.append("{:,} non-line objects (points, solids, fills) were ignored.".format(skipped))
    alert("\n".join(lines))


# ---------------------------------------------------------------- UI (IBM Carbon)
# Window layout: ui.xaml next to this script (shared colours and styles: lib/bd_theme.xaml)


def ask_line_style(cad_name, line_count, style_names):
    """Returns the chosen style name, or None if cancelled."""
    window = bd.load_window(__file__)
    find = window.FindName
    style_list = find("StyleList")
    search = find("StyleSearch")
    convert_btn = find("ConvertBtn")
    status = find("StatusText")
    result = {"style": None}

    find("SubTitle").Text = u"{}   \u00b7   {}".format(cad_name, view.Name)

    for name in sorted(style_names, key=lambda n: n.lower()):
        item = ListBoxItem()
        tb = TextBlock()
        tb.Text = name
        tb.TextTrimming = TextTrimming.CharacterEllipsis
        item.Content = tb
        item.Tag = name
        item.ToolTip = name
        style_list.Items.Add(item)

    def on_search(sender, args):
        query = search.Text.strip().lower()
        find("StyleHint").Visibility = Visibility.Collapsed if search.Text else Visibility.Visible
        for it in style_list.Items:
            show = not query or query in it.Tag.lower()
            it.Visibility = Visibility.Visible if show else Visibility.Collapsed

    def refresh(*_):
        picked = style_list.SelectedItem
        text = u"All layers  \u00b7  {:,} lines".format(line_count)
        if picked is not None:
            text += u"   \u2192   {}".format(picked.Tag)
        status.Text = text
        convert_btn.IsEnabled = picked is not None

    def accept(*_):
        if style_list.SelectedItem is not None:
            result["style"] = style_list.SelectedItem.Tag
            window.Close()

    def on_key(sender, args):
        if args.Key == Key.Escape:
            window.Close()

    search.TextChanged += TextChangedEventHandler(on_search)
    style_list.SelectionChanged += SelectionChangedEventHandler(refresh)
    style_list.MouseDoubleClick += MouseButtonEventHandler(accept)
    convert_btn.Click += RoutedEventHandler(accept)
    find("CancelBtn").Click += RoutedEventHandler(lambda s, e: window.Close())
    find("CloseBtn").Click += RoutedEventHandler(lambda s, e: window.Close())
    find("HeaderBar").MouseLeftButtonDown += MouseButtonEventHandler(
        lambda s, e: window.DragMove())
    window.KeyDown += KeyEventHandler(on_key)
    refresh()

    try:
        WindowInteropHelper(window).Owner = __revit__.MainWindowHandle
    except Exception:
        pass

    frame = DispatcherFrame()

    def on_closed(sender, args):
        frame.Continue = False

    window.Closed += EventHandler(on_closed)
    window.Show()
    search.Focus()
    Dispatcher.PushFrame(frame)
    return result["style"]


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

    styles = get_line_styles()
    style_name = ask_line_style(cad.Category.Name, len(items), list(styles.keys()))
    if style_name is None:
        return

    if len(items) > BIG_RUN and not confirm(
            "This CAD has {:,} lines. Converting them may take a while.\n\n"
            "Continue?".format(len(items))):
        return

    try:
        stats = convert(items, styles[style_name])
    except StyleNotAllowed:
        alert("'{}' can't be used for detail lines. Nothing was changed.\n"
              "Run the tool again and pick another line style.".format(style_name))
        return

    if stats["created"]:
        uidoc.Selection.SetElementIds(List[ElementId](stats["created"]))
    report(stats, skipped, style_name)


main()
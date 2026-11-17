# -*- coding: utf-8 -*-
__doc__ = """__________________________________________________
Description:

Links several DWG (or DXF) files in one go, each with its own options, the same choices as Revit's Link CAD dialog: Positioning, Place at, Colors, Layers/Levels and Import units, plus Current view only.
Manual - Origin and Manual - Center ask you to click the point in the view for each of those files, one after the other.
Each file is linked in its own step, so one bad file doesn't stop the rest, and one Undo removes them all. Each file shows what happened after linking.
__________________________________________________
How-to:

-> Click on the button
-> Click Add files or Add folder to list the DWG files
-> Set the options of each file in its row, or set the defaults on the right and click Apply to checked files
-> Layers/Levels > Specify... opens the list of that file's layers to pick from
-> Choose the workset and the pin option on the right
-> Click Link checked files, then click the point in the view for any Manual file (Esc skips it)
-> Each file shows its result; add more files or click Close
__________________________________________________
Author: Mohamed Bedair"""

import clr

clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")
clr.AddReference("System.Windows.Forms")

from Autodesk.Revit.DB import (
    BuiltInParameter,
    CADLinkType,
    DWGImportOptions,
    ElementId,
    ExternalFileUtils,
    FilteredElementCollector,
    FilteredWorksetCollector,
    ImportColorMode,
    ImportPlacement,
    ImportUnit,
    ModelPathUtils,
    Transaction,
    TransactionGroup,
    ViewPlan,
    ViewType,
    WorksetKind,
    XYZ,
)
from Autodesk.Revit.Exceptions import OperationCanceledException

from Microsoft.Win32 import OpenFileDialog
from System import String
from System.Collections.Generic import List
from System.IO import Directory, File, FileInfo, Path
from System.Windows import (
    CornerRadius,
    FontWeights,
    GridLength,
    GridUnitType,
    RoutedEventHandler,
    TextTrimming,
    Thickness,
    VerticalAlignment,
    Visibility,
)
from System.Windows.Controls import (
    Border,
    Button,
    CheckBox,
    ColumnDefinition,
    ComboBox,
    Dock,
    DockPanel,
    Grid,
    Orientation,
    SelectionChangedEventHandler,
    StackPanel,
    TextBlock,
    TextBox,
    TextChangedEventHandler,
)
from System.Windows.Forms import DialogResult, FolderBrowserDialog
from System.Windows.Input import Cursors, Mouse, MouseButtonEventHandler
from System.Windows.Media import BrushConverter
from pyrevit import script
from bd_combo_search import enable_combo_search
import bd_core as bd

uidoc = __revit__.ActiveUIDocument  # noqa: F821
doc = uidoc.Document
cfg = script.get_config()
TOOL = "Link DWG Files"

C_TEXT = "#F4F4F4"
C_SUBTEXT = "#A8A8A8"
C_MUTED = "#8D8D8D"
C_ACCENT = "#F1C21B"
C_OK = "#42BE65"
C_BAD = "#FF8389"
DOT = u"  \u00b7  "

W_SIZE = 80
W_DATE = 120
W_STATE = 120

# (label, centre placement, manual)
POSITIONS = (
    ("Auto - Center to Center", True, False),
    ("Auto - Origin to Internal Origin", False, False),
    ("Manual - Origin", False, True),
    ("Manual - Center", True, True),
)
COLORS = (
    ("Invert", ImportColorMode.Inverted),
    ("Preserve", ImportColorMode.Preserved),
    ("Black and White", ImportColorMode.BlackAndWhite),
)
LAYER_MODES = ("All", "Visible", "Specify...")
SPECIFY = 2
UNITS = (
    ("Auto-Detect", ImportUnit.Default),
    ("feet", ImportUnit.Foot),
    ("inch", ImportUnit.Inch),
    ("meter", ImportUnit.Meter),
    ("decimeter", ImportUnit.Decimeter),
    ("centimeter", ImportUnit.Centimeter),
    ("millimeter", ImportUnit.Millimeter),
    ("US survey feet", ImportUnit.USSurveyFoot),
    ("Custom factor:", ImportUnit.Custom),
)
CUSTOM = 8

PLAN_TYPES = (ViewType.FloorPlan, ViewType.CeilingPlan, ViewType.EngineeringPlan, ViewType.AreaPlan)
VIEW_ONLY_TYPES = PLAN_TYPES + (ViewType.Section, ViewType.Elevation, ViewType.Detail, ViewType.DraftingView,
                                ViewType.DrawingSheet, ViewType.Legend)
# Revit links into these views only (no level to place on)
FORCE_VIEW_ONLY = (ViewType.DraftingView, ViewType.DrawingSheet, ViewType.Legend)

_BC = BrushConverter()
_BRUSHES = {}


def brush(hex_string):
    if hex_string not in _BRUSHES:
        _BRUSHES[hex_string] = _BC.ConvertFromString(hex_string)
    return _BRUSHES[hex_string]


id_value = bd.eid_int
plural = bd.plural


def norm(path):
    try:
        return Path.GetFullPath(path).lower()
    except Exception:
        return (path or "").lower()


# ---------------------------------------------------------------------------
# Project data
# ---------------------------------------------------------------------------
def cad_link_paths():
    """Lower-case full paths of every DWG/DXF already linked in the project."""
    out = set()
    for link_type in FilteredElementCollector(doc).OfClass(CADLinkType):
        try:
            if not ExternalFileUtils.IsExternalFileReference(doc, link_type.Id):
                continue
            ref = ExternalFileUtils.GetExternalFileReference(doc, link_type.Id)
            path = ModelPathUtils.ConvertModelPathToUserVisiblePath(ref.GetAbsolutePath())
            if path:
                out.add(norm(path))
        except Exception:
            pass
    return out


def collect_worksets():
    if not doc.IsWorkshared:
        return [], -1
    worksets = list(FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset))
    worksets.sort(key=lambda w: w.Name.lower())
    active = id_value(doc.GetWorksetTable().GetActiveWorksetId())
    ids = [id_value(w.Id) for w in worksets]
    return worksets, (ids.index(active) if active in ids else 0)


def level_views():
    """[(level, plan view)] sorted by elevation: one plan view per level, used
    to place the link on that level. Levels without a plan view are left out."""
    best = {}
    for view in FilteredElementCollector(doc).OfClass(ViewPlan):
        try:
            if view.IsTemplate or view.ViewType not in PLAN_TYPES or not view.CanBePrinted:
                continue
            level = view.GenLevel
        except Exception:
            continue
        if level is None:
            continue
        key = id_value(level.Id)
        rank = PLAN_TYPES.index(view.ViewType)
        if key not in best or rank < best[key][0]:
            best[key] = (rank, level, view)
    out = [(level, view) for _, level, view in best.values()]
    out.sort(key=lambda pair: pair[0].ProjectElevation)
    return out


def set_workset(element, workset_id):
    try:
        param = element.get_Parameter(BuiltInParameter.ELEM_PARTITION_PARAM)
        if param is not None and not param.IsReadOnly and id_value(element.WorksetId) != workset_id:
            param.Set(workset_id)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# File list
# ---------------------------------------------------------------------------
def file_entry(path, defaults):
    entry = {"path": path, "name": Path.GetFileName(path), "folder": Path.GetDirectoryName(path) or "",
             "size": "", "date": "", "result": None, "box": None, "border": None, "state": "ready",
             "opt": dict(defaults), "layers": None, "layer_names": None, "point": None}
    try:
        info = FileInfo(path)
        entry["size"] = "{0:,.1f} MB".format(info.Length / 1048576.0)
        entry["date"] = info.LastWriteTime.ToString("yyyy-MM-dd HH:mm")
    except Exception:
        pass
    return entry


def refresh_states(files):
    """ready / linked (already linked, can be linked again) / missing."""
    have = cad_link_paths()
    for entry in files:
        if not File.Exists(entry["path"]):
            entry["state"] = "missing"
        elif norm(entry["path"]) in have:
            entry["state"] = "linked"
        else:
            entry["state"] = "ready"


STATE_TEXT = {"ready": ("Ready", C_SUBTEXT), "linked": ("Already linked", C_ACCENT),
              "missing": ("File not found", C_BAD)}


def parse_factor(text):
    try:
        value = float((text or "").strip().replace(",", "."))
        return value if value > 0 else None
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Layers (Specify...)
# ---------------------------------------------------------------------------
def read_layers(path, ctx):
    """Layer names of a DWG: links it in a transaction that is rolled back and
    reads the layer sub-categories. Returns a sorted list or None."""
    t = Transaction(doc, "Read DWG layers")
    t.Start()
    try:
        options = DWGImportOptions()
        options.Placement = ImportPlacement.Origin
        if ctx["levels"]:
            view = ctx["levels"][0][1]
            options.ThisViewOnly = False
        else:
            view = ctx["view"]
            options.ThisViewOnly = True
        new_id = clr.Reference[ElementId]()
        if not doc.Link(path, options, view, new_id):
            return None
        instance = doc.GetElement(new_id.Value)
        names = set()
        if instance is not None and instance.Category is not None:
            for sub in instance.Category.SubCategories:
                names.add(sub.Name)
        return sorted(names, key=lambda n: n.lower())
    finally:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()


def pick_layers(owner, entry):
    """Layer picker window. Returns the checked names, or None if cancelled."""
    window = bd.load_window(__file__, "layers.xaml")
    window.Owner = owner
    f = window.FindName
    panel, search_box, search_hint, count_text = f("LayerPanel"), f("SearchBox"), f("SearchHint"), f("CountText")
    f("FileText").Text = u"{0}{1}{2}".format(entry["name"], DOT, plural(len(entry["layer_names"]), "layer"))
    chosen = set(entry["layers"] if entry["layers"] is not None else entry["layer_names"])
    boxes = []
    result = [None]

    def update_count(*_):
        count_text.Text = u"{0} of {1} checked".format(len([b for b in boxes if b.IsChecked]), len(boxes))

    for name in entry["layer_names"]:
        box = CheckBox()
        box.Content = name
        box.Tag = name
        box.IsChecked = name in chosen
        box.Click += RoutedEventHandler(update_count)
        panel.Children.Add(box)
        boxes.append(box)

    def on_search(sender, args):
        needle = (search_box.Text or "").strip().lower()
        search_hint.Visibility = Visibility.Collapsed if needle else Visibility.Visible
        for box in boxes:
            box.Visibility = Visibility.Visible if needle in box.Tag.lower() else Visibility.Collapsed

    def set_visible(value):
        for box in boxes:
            if box.Visibility == Visibility.Visible:
                box.IsChecked = value
        update_count()

    def on_ok(sender, args):
        picked = [b.Tag for b in boxes if b.IsChecked]
        if not picked:
            bd.alert("Check at least one layer.", TOOL)
            return
        result[0] = picked
        window.Close()

    search_box.TextChanged += TextChangedEventHandler(on_search)
    f("AllBtn").Click += RoutedEventHandler(lambda s, e: set_visible(True))
    f("NoneBtn").Click += RoutedEventHandler(lambda s, e: set_visible(False))
    f("OkBtn").Click += RoutedEventHandler(on_ok)
    f("CancelBtn").Click += RoutedEventHandler(lambda s, e: window.Close())
    update_count()
    bd.show_modal(window)
    return result[0]


# ---------------------------------------------------------------------------
# Linking
# ---------------------------------------------------------------------------
def view_only_for(entry, ctx):
    return ctx["force_view"] or (entry["opt"]["view"] and ctx["view_ok"])


def pick_points(entries, ctx):
    """Click the insertion point of every Manual file. Esc skips that file."""
    for entry in entries:
        label, centre, manual = POSITIONS[entry["opt"]["pos"]]
        entry["point"] = None
        if not manual:
            continue
        prompt = u"Click the {0} point for {1}  (Esc skips this file)".format(
            "center" if centre else "origin", entry["name"])
        try:
            point = uidoc.Selection.PickPoint(prompt)
        except OperationCanceledException:
            entry["result"] = ("bad", u"Skipped: no point was clicked")
            continue
        except Exception as ex:
            entry["result"] = ("bad", u"Skipped: could not pick a point in this view ({0})".format(ex))
            continue
        if view_only_for(entry, ctx):
            entry["point"] = point
        else:
            level = ctx["levels"][entry["opt"]["level"]][0]
            entry["point"] = XYZ(point.X, point.Y, level.ProjectElevation)


def build_options(entry, ctx, view_only):
    opt = entry["opt"]
    label, centre, manual = POSITIONS[opt["pos"]]
    options = DWGImportOptions()
    options.Placement = ImportPlacement.Centered if centre else ImportPlacement.Origin
    if manual:
        options.ReferencePoint = entry["point"]
    options.ThisViewOnly = view_only
    options.ColorMode = COLORS[opt["color"]][1]
    options.AutoCorrectAlmostVHLines = ctx["settings"]["axis"]
    if opt["units"] == CUSTOM:
        options.CustomScale = parse_factor(opt["factor"])
        try:
            options.Unit = ImportUnit.Custom
        except Exception:
            pass
    else:
        options.Unit = UNITS[opt["units"]][1]
    if opt["layers"] == SPECIFY:
        options.VisibleLayersOnly = False
        names = List[String]()
        for name in entry["layers"]:
            names.Add(name)
        options.SetLayerSelection(names)
    else:
        options.VisibleLayersOnly = opt["layers"] == 1
    return options


def describe(entry, ctx, view_only):
    opt = entry["opt"]
    where = "current view only" if view_only else ctx["levels"][opt["level"]][0].Name
    layers = plural(len(entry["layers"]), "layer") if opt["layers"] == SPECIFY else LAYER_MODES[opt["layers"]] + " layers"
    units = u"factor " + opt["factor"].strip() if opt["units"] == CUSTOM else UNITS[opt["units"]][0]
    return [POSITIONS[opt["pos"]][0], where, COLORS[opt["color"]][0], layers, units]


def link_one(entry, ctx, workset):
    """One file in its own transaction. Returns ('ok' / 'bad', text)."""
    view_only = view_only_for(entry, ctx)
    view = ctx["view"] if view_only else ctx["levels"][entry["opt"]["level"]][1]
    t = Transaction(doc, u"Link {0}".format(entry["name"]))
    t.Start()
    try:
        options = build_options(entry, ctx, view_only)
        new_id = clr.Reference[ElementId]()
        if not doc.Link(entry["path"], options, view, new_id):
            t.RollBack()
            return "bad", u"Revit could not link this file"
        instance = doc.GetElement(new_id.Value)
        notes = describe(entry, ctx, view_only)
        if workset is not None and instance is not None:
            set_workset(instance, id_value(workset.Id))
            link_type = doc.GetElement(instance.GetTypeId())
            if link_type is not None:
                set_workset(link_type, id_value(workset.Id))
            notes.append(u"on " + workset.Name)
        if ctx["settings"]["pin"] and instance is not None:
            instance.Pinned = True
            notes.append("pinned")
        t.Commit()
        return "ok", u"Linked: " + u" \u00b7 ".join(notes)
    except Exception as ex:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        return "bad", u"Failed: {0}".format(ex)


def link_files(entries, ctx, workset):
    group = TransactionGroup(doc, TOOL)
    group.Start()
    Mouse.OverrideCursor = Cursors.Wait
    try:
        for entry in entries:
            entry["result"] = link_one(entry, ctx, workset)
        group.Assimilate()
    except Exception:
        if group.HasStarted() and not group.HasEnded():
            group.RollBack()
        raise
    finally:
        Mouse.OverrideCursor = None


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
# Window layout: ui.xaml and layers.xaml next to this script (shared colours and styles: lib/bd_theme.xaml)
def text_block(text, size=12, color=C_TEXT, bold=False):
    block = TextBlock()
    block.Text = text
    block.FontSize = size
    block.Foreground = brush(color)
    block.VerticalAlignment = VerticalAlignment.Center
    block.TextTrimming = TextTrimming.CharacterEllipsis
    if bold:
        block.FontWeight = FontWeights.SemiBold
    return block


def fixed(child, width):
    holder = Border()
    holder.Width = width
    holder.Margin = Thickness(8, 0, 0, 0)
    holder.VerticalAlignment = VerticalAlignment.Center
    holder.Child = child
    return holder


def chip(text, back, fore):
    border = Border()
    border.Background = brush(back)
    border.CornerRadius = CornerRadius(9)
    border.Padding = Thickness(8, 1, 8, 1)
    border.Margin = Thickness(12, 0, 0, 0)
    border.VerticalAlignment = VerticalAlignment.Center
    block = text_block(text, 10, fore, bold=True)
    border.Child = block
    return border, block


def make_combo(window, items, index):
    combo = ComboBox()
    combo.Style = window.FindResource("DarkCombo")
    for item in items:
        combo.Items.Add(item)
    combo.SelectedIndex = max(0, min(index, len(items) - 1))
    return combo


def make_header(window):
    header = window.FindName("HeaderRow")
    style = window.FindResource("HeaderCell")
    for text, width in (("STATUS", W_STATE), ("MODIFIED", W_DATE), ("SIZE", W_SIZE)):
        block = TextBlock()
        block.Text = text
        block.Style = style
        cell = fixed(block, width)
        DockPanel.SetDock(cell, Dock.Right)
        header.Children.Add(cell)
    name = TextBlock()
    name.Text = "FILE"
    name.Style = style
    name.Margin = Thickness(28, 0, 0, 0)
    header.Children.Add(name)


def build_row(window, entry, ctx, on_change):
    opt = entry["opt"]
    usable = entry["state"] != "missing"
    border = Border()
    border.Background = brush("#262626")
    border.CornerRadius = CornerRadius(6)
    border.Padding = Thickness(12, 8, 12, 10)
    border.Margin = Thickness(0, 0, 0, 6)
    outer = StackPanel()

    # --- top line: check box, name, folder, result, date, size, status
    dock = DockPanel()
    state_text, state_color = STATE_TEXT[entry["state"]]
    if entry["result"] is not None and entry["result"][0] == "ok":
        state_text, state_color = "Linked now", C_OK
    for cell in (fixed(text_block(state_text, 12, state_color), W_STATE),
                 fixed(text_block(entry["date"], 12, C_SUBTEXT), W_DATE),
                 fixed(text_block(entry["size"], 12, C_SUBTEXT), W_SIZE)):
        DockPanel.SetDock(cell, Dock.Right)
        dock.Children.Add(cell)

    box = CheckBox()
    box.IsChecked = usable and entry.get("ticked", entry["state"] == "ready")
    box.IsEnabled = usable
    box.Margin = Thickness(0, 0, 12, 0)
    box.VerticalAlignment = VerticalAlignment.Center
    DockPanel.SetDock(box, Dock.Left)
    dock.Children.Add(box)
    entry["box"] = box

    info = StackPanel()
    info.VerticalAlignment = VerticalAlignment.Center
    info.Children.Add(text_block(entry["name"], 13, C_TEXT if usable else C_MUTED, bold=True))
    folder = text_block(entry["folder"], 11, C_SUBTEXT)
    folder.ToolTip = entry["path"]
    info.Children.Add(folder)
    if entry["result"] is not None:
        kind, text = entry["result"]
        line = text_block(text, 11, C_OK if kind == "ok" else C_BAD, bold=True)
        line.ToolTip = text
        info.Children.Add(line)
    dock.Children.Add(info)
    outer.Children.Add(dock)

    # --- options: one column each
    grid = Grid()
    grid.Margin = Thickness(26, 8, 0, 0)
    for star in (1.45, 1.0, 1.0, 1.0, 1.0):
        column = ColumnDefinition()
        column.Width = GridLength(star, GridUnitType.Star)
        grid.ColumnDefinitions.Add(column)

    level_names = [level.Name for level, _ in ctx["levels"]] or ["(no plan views)"]
    combos = {}
    cells = (("pos", "POSITIONING", [p[0] for p in POSITIONS]),
             ("level", "PLACE AT", level_names),
             ("color", "COLORS", [c[0] for c in COLORS]),
             ("layers", "LAYERS/LEVELS", list(LAYER_MODES)),
             ("units", "IMPORT UNITS", [u[0] for u in UNITS]))
    factor_panel = StackPanel()
    for column, (key, label, items) in enumerate(cells):
        cell = StackPanel()
        cell.Margin = Thickness(0, 0, 8 if column < 4 else 0, 0)
        head = TextBlock()
        head.Text = label
        head.Style = window.FindResource("OptLabel")
        cell.Children.Add(head)
        combo = make_combo(window, items, opt[key])
        combo.IsEnabled = usable
        cell.Children.Add(combo)
        combos[key] = combo
        if key == "units":
            factor_panel.Orientation = Orientation.Horizontal
            factor_panel.Margin = Thickness(0, 4, 0, 0)
            factor_panel.Children.Add(text_block("Factor", 11, C_SUBTEXT))
            factor_box = TextBox()
            factor_box.Text = opt["factor"]
            factor_box.Width = 70
            factor_box.Height = 22
            factor_box.FontSize = 11
            factor_box.Margin = Thickness(6, 0, 0, 0)
            factor_box.IsEnabled = usable
            factor_panel.Children.Add(factor_box)
            cell.Children.Add(factor_panel)
        Grid.SetColumn(cell, column)
        grid.Children.Add(cell)
    outer.Children.Add(grid)

    # --- bottom line: current view only, layer count, manual note
    bottom = StackPanel()
    bottom.Orientation = Orientation.Horizontal
    bottom.Margin = Thickness(26, 6, 0, 0)
    view_box = CheckBox()
    view_box.Content = "Current view only"
    view_box.FontSize = 11
    view_box.IsChecked = view_only_for(entry, ctx)
    view_box.IsEnabled = usable and ctx["view_ok"] and not ctx["force_view"]
    bottom.Children.Add(view_box)
    layers_chip, layers_text = chip("", "#1D2B3D", "#78A9FF")
    bottom.Children.Add(layers_chip)
    edit_btn = Button()
    edit_btn.Content = "Edit layers"
    edit_btn.Style = window.FindResource("TextLink")
    edit_btn.Margin = Thickness(8, 0, 0, 0)
    edit_btn.IsEnabled = usable
    bottom.Children.Add(edit_btn)
    manual_chip, manual_text = chip("", "#3A3214", C_ACCENT)
    bottom.Children.Add(manual_chip)
    outer.Children.Add(bottom)
    border.Child = outer

    busy = [False]

    def refresh_row():
        label, centre, manual = POSITIONS[opt["pos"]]
        manual_chip.Visibility = Visibility.Visible if manual else Visibility.Collapsed
        manual_text.Text = u"You'll click the {0} point in the view".format("center" if centre else "origin")
        specify = opt["layers"] == SPECIFY
        layers_chip.Visibility = Visibility.Visible if specify else Visibility.Collapsed
        edit_btn.Visibility = layers_chip.Visibility
        if specify:
            layers_text.Text = u"{0} of {1} layers".format(len(entry["layers"] or []),
                                                          len(entry["layer_names"] or [])) \
                if entry["layers"] else u"No layers picked yet"
        factor_panel.Visibility = Visibility.Visible if opt["units"] == CUSTOM else Visibility.Collapsed
        combos["level"].IsEnabled = usable and bool(ctx["levels"]) and not view_only_for(entry, ctx)

    def choose_layers():
        """Read the file's layers once, then open the picker. True if picked."""
        if entry["layer_names"] is None:
            Mouse.OverrideCursor = Cursors.Wait
            try:
                entry["layer_names"] = read_layers(entry["path"], ctx)
            except Exception as ex:
                entry["layer_names"] = None
                Mouse.OverrideCursor = None
                bd.alert(u"Could not read the layers of {0}.".format(entry["name"]), TOOL, details=str(ex))
                return False
            finally:
                Mouse.OverrideCursor = None
            if not entry["layer_names"]:
                bd.alert(u"No layers were found in {0}.".format(entry["name"]), TOOL)
                entry["layer_names"] = None
                return False
        picked = pick_layers(window, entry)
        if picked is None:
            return False
        entry["layers"] = picked
        return True

    def on_combo(key):
        def handler(sender, args):
            if busy[0]:
                return
            index = combos[key].SelectedIndex
            if key == "layers" and index == SPECIFY and not choose_layers() and not entry["layers"]:
                busy[0] = True
                combos[key].SelectedIndex = opt["layers"]
                busy[0] = False
                return
            opt[key] = index
            refresh_row()
            on_change()
        return handler

    for key in combos:
        combos[key].SelectionChanged += SelectionChangedEventHandler(on_combo(key))

    def on_factor(sender, args):
        opt["factor"] = factor_box.Text or ""

    def on_view(sender, args):
        opt["view"] = bool(view_box.IsChecked)
        refresh_row()

    def on_edit(sender, args):
        if choose_layers():
            refresh_row()
            on_change()

    def on_box(sender, args):
        entry["ticked"] = bool(box.IsChecked)
        on_change()

    def on_row(sender, args):
        if not usable or isinstance(args.OriginalSource, CheckBox):
            return
        box.IsChecked = not bool(box.IsChecked)
        entry["ticked"] = bool(box.IsChecked)
        on_change()

    factor_box.TextChanged += TextChangedEventHandler(on_factor)
    view_box.Click += RoutedEventHandler(on_view)
    edit_btn.Click += RoutedEventHandler(on_edit)
    box.Click += RoutedEventHandler(on_box)
    if usable:
        dock.Cursor = Cursors.Hand
    dock.MouseLeftButtonUp += MouseButtonEventHandler(on_row)
    entry["border"] = border
    refresh_row()
    return border


def show_window(files, defaults, settings, worksets, ctx, banner):
    """Returns 'link', 'refresh' (the list changed) or None (closed)."""
    window = bd.load_window(__file__)
    f = window.FindName
    rows_panel = f("RowsPanel")
    search_box, search_hint = f("SearchBox"), f("SearchHint")
    count_text, link_btn, empty_text = f("CountText"), f("LinkBtn"), f("EmptyText")
    workset_combo, pin_check, axis_check = f("WorksetCombo"), f("PinCheck"), f("AxisCheck")

    f("SubTitle").Text = u"{0}{1}Active view: {2}{1}Set the options of each file in its row, " \
                         u"then click Link checked files.".format(doc.Title, DOT, ctx["view"].Name)
    f("ViewNote").Text = ctx["note"]
    make_header(window)

    def ticked():
        return [e for e in files if e["box"] is not None and e["box"].IsChecked]

    def update():
        chosen = ticked()
        empty_text.Visibility = Visibility.Collapsed if files else Visibility.Visible
        visible = len([e for e in files if e["border"].Visibility == Visibility.Visible])
        text = u"Showing {0} of {1}{2}{3} checked".format(visible, plural(len(files), "file"), DOT, len(chosen))
        manual = len([e for e in chosen if POSITIONS[e["opt"]["pos"]][2]])
        if manual:
            text += u"{0}{1} placed by clicking in the view".format(DOT, manual)
        if banner[0]:
            text = banner[0] + DOT + text
        count_text.Text = text
        link_btn.Content = u"Link checked files ({0})".format(len(chosen)) if chosen else u"Link checked files"
        link_btn.IsEnabled = bool(chosen)

    for entry in files:
        rows_panel.Children.Add(build_row(window, entry, ctx, update))

    # --- defaults panel
    level_names = [level.Name for level, _ in ctx["levels"]] or ["(no plan views)"]
    def_combos = {}
    for key, name, items in (("pos", "DefPos", [p[0] for p in POSITIONS]),
                             ("level", "DefLevel", level_names),
                             ("color", "DefColor", [c[0] for c in COLORS]),
                             ("layers", "DefLayers", list(LAYER_MODES[:2])),
                             ("units", "DefUnits", [u[0] for u in UNITS])):
        combo = f(name)
        for item in items:
            combo.Items.Add(item)
        combo.SelectedIndex = max(0, min(defaults[key], len(items) - 1))
        def_combos[key] = combo
    def_factor, def_factor_panel, def_view = f("DefFactor"), f("DefFactorPanel"), f("DefView")
    def_factor.Text = defaults["factor"]
    def_view.IsChecked = ctx["force_view"] or (defaults["view"] and ctx["view_ok"])
    def_view.IsEnabled = ctx["view_ok"] and not ctx["force_view"]

    def refresh_defaults():
        def_factor_panel.Visibility = Visibility.Visible if defaults["units"] == CUSTOM else Visibility.Collapsed
        def_combos["level"].IsEnabled = bool(ctx["levels"]) and not bool(def_view.IsChecked)

    def on_default(key):
        def handler(sender, args):
            defaults[key] = max(0, def_combos[key].SelectedIndex)
            refresh_defaults()
        return handler

    for key in def_combos:
        def_combos[key].SelectionChanged += SelectionChangedEventHandler(on_default(key))

    def on_def_factor(sender, args):
        defaults["factor"] = def_factor.Text or ""

    def on_def_view(sender, args):
        defaults["view"] = bool(def_view.IsChecked)
        refresh_defaults()

    def_factor.TextChanged += TextChangedEventHandler(on_def_factor)
    def_view.Click += RoutedEventHandler(on_def_view)
    refresh_defaults()

    if worksets:
        for workset in worksets:
            workset_combo.Items.Add(workset.Name)
        workset_combo.SelectedIndex = settings["workset"]
    else:
        workset_combo.Items.Add("Not workshared")
        workset_combo.SelectedIndex = 0
        workset_combo.IsEnabled = False
    pin_check.IsChecked = settings["pin"]
    axis_check.IsChecked = settings["axis"]

    outcome = [None]

    def save_settings():
        if worksets and workset_combo.SelectedIndex >= 0:
            settings["workset"] = workset_combo.SelectedIndex
        settings["pin"] = bool(pin_check.IsChecked)
        settings["axis"] = bool(axis_check.IsChecked)
        for entry in files:
            if entry["box"] is not None and entry["box"].IsEnabled:
                entry["ticked"] = bool(entry["box"].IsChecked)

    def reopen(text):
        banner[0] = text
        save_settings()
        outcome[0] = "refresh"
        window.Close()

    def add_paths(paths):
        known = set([norm(e["path"]) for e in files])
        added = 0
        for path in paths:
            if norm(path) in known:
                continue
            known.add(norm(path))
            files.append(file_entry(path, defaults))
            added += 1
        reopen(u"Added {0}".format(plural(added, "file")) if added else u"Those files are already in the list")

    def on_add(sender, args):
        dialog = OpenFileDialog()
        dialog.Title = "DWG files to link"
        dialog.Filter = "CAD drawings (*.dwg;*.dxf)|*.dwg;*.dxf"
        dialog.Multiselect = True
        if files:
            try:
                dialog.InitialDirectory = files[-1]["folder"]
            except Exception:
                pass
        if not dialog.ShowDialog(window):
            return
        add_paths(list(dialog.FileNames))

    def on_folder(sender, args):
        dialog = FolderBrowserDialog()
        dialog.Description = "Folder with the DWG files to link (sub-folders are not searched)"
        if dialog.ShowDialog() != DialogResult.OK:
            return
        paths = list(Directory.GetFiles(dialog.SelectedPath, "*.dwg")) + \
            list(Directory.GetFiles(dialog.SelectedPath, "*.dxf"))
        if not paths:
            bd.alert("There are no DWG or DXF files in that folder.", TOOL)
            return
        add_paths(sorted(paths, key=lambda p: p.lower()))

    def on_remove(sender, args):
        chosen = ticked()
        if not chosen:
            return
        for entry in chosen:
            files.remove(entry)
        reopen(u"Removed {0}".format(plural(len(chosen), "file")))

    def on_clear(sender, args):
        if files:
            del files[:]
            reopen(u"")

    def on_apply(sender, args):
        chosen = ticked()
        if not chosen:
            bd.alert("Check the files to copy the defaults onto.", TOOL)
            return
        for entry in chosen:
            entry["opt"] = dict(defaults)
            entry["layers"] = None
        reopen(u"Defaults applied to {0}".format(plural(len(chosen), "file")))

    def on_search(sender, args):
        needle = (search_box.Text or "").strip().lower()
        search_hint.Visibility = Visibility.Collapsed if needle else Visibility.Visible
        for entry in files:
            haystack = u" ".join([entry["name"], entry["folder"], STATE_TEXT[entry["state"]][0]]).lower()
            entry["border"].Visibility = Visibility.Visible if (not needle or needle in haystack) \
                else Visibility.Collapsed
        update()

    def on_link(sender, args):
        chosen = ticked()
        if not chosen:
            return
        no_layers = [e["name"] for e in chosen if e["opt"]["layers"] == SPECIFY and not e["layers"]]
        if no_layers:
            bd.alert(u"Pick the layers first (Layers/Levels is set to Specify...):\n\n" + u"\n".join(no_layers), TOOL)
            return
        bad_factor = [e["name"] for e in chosen if e["opt"]["units"] == CUSTOM and parse_factor(e["opt"]["factor"]) is None]
        if bad_factor:
            bd.alert(u"Type a custom factor above 0 for:\n\n" + u"\n".join(bad_factor), TOOL)
            return
        if not ctx["levels"] and [e for e in chosen if not view_only_for(e, ctx)]:
            bd.alert("This model has no plan views to place the links on. Check Current view only.", TOOL)
            return
        save_settings()
        outcome[0] = "link"
        window.Close()

    search_box.TextChanged += TextChangedEventHandler(on_search)
    f("AddBtn").Click += RoutedEventHandler(on_add)
    f("FolderBtn").Click += RoutedEventHandler(on_folder)
    f("RemoveBtn").Click += RoutedEventHandler(on_remove)
    f("ClearBtn").Click += RoutedEventHandler(on_clear)
    f("ApplyBtn").Click += RoutedEventHandler(on_apply)
    link_btn.Click += RoutedEventHandler(on_link)
    f("CloseBtn").Click += RoutedEventHandler(lambda s, e: window.Close())
    update()

    def on_closed(sender, args):
        save_settings()

    window.Closed += on_closed
    enable_combo_search(window)
    bd.show_modal(window, __revit__)  # noqa: F821
    return outcome[0]


# ---------------------------------------------------------------------------
# Settings (remembered between runs)
# ---------------------------------------------------------------------------
def load_settings(levels, view):
    def number(name, default, top):
        try:
            value = int(cfg.get_option(name, default))
        except Exception:
            value = default
        return value if 0 <= value < top else default

    level_ids = [id_value(level.Id) for level, _ in levels]
    level_index = 0
    try:
        saved = int(cfg.get_option("level_id", -1))
    except Exception:
        saved = -1
    if saved in level_ids:
        level_index = level_ids.index(saved)
    else:
        try:
            if view.GenLevel is not None and id_value(view.GenLevel.Id) in level_ids:
                level_index = level_ids.index(id_value(view.GenLevel.Id))
        except Exception:
            pass
    defaults = {"pos": number("pos", 1, len(POSITIONS)), "level": level_index,
                "color": number("color", 1, len(COLORS)), "layers": number("layers", 0, 2),
                "units": number("units", 0, len(UNITS)), "factor": str(cfg.get_option("factor", "1.0")),
                "view": bool(cfg.get_option("view", False))}
    settings = {"pin": bool(cfg.get_option("pin", True)), "axis": bool(cfg.get_option("axis", True))}
    return defaults, settings


def save_config(defaults, settings, levels):
    for key in ("pos", "color", "layers", "units"):
        cfg.set_option(key, defaults[key])
    cfg.set_option("factor", defaults["factor"])
    cfg.set_option("view", defaults["view"])
    cfg.set_option("pin", settings["pin"])
    cfg.set_option("axis", settings["axis"])
    if levels:
        cfg.set_option("level_id", id_value(levels[defaults["level"]][0].Id))
    try:
        script.save_config()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    if doc.IsFamilyDocument:
        bd.alert("DWG files can only be linked into a project. In a family, use Import CAD.", TOOL)
        return
    view = doc.ActiveView
    levels = level_views()
    view_ok = view.ViewType in VIEW_ONLY_TYPES and not view.IsTemplate
    force_view = view.ViewType in FORCE_VIEW_ONLY or not levels
    if not view_ok and not levels:
        bd.alert("Open a plan, section or drafting view first. This model has no plan view to link into.", TOOL)
        return

    if view.ViewType in FORCE_VIEW_ONLY:
        note = u"The active view is a {0}, so every file is linked into this view only.".format(
            "sheet" if view.ViewType == ViewType.DrawingSheet else
            "legend" if view.ViewType == ViewType.Legend else "drafting view")
    elif not levels:
        note = u"This model has no plan views, so every file is linked into the active view only."
    elif not view_ok:
        note = u"Current view only isn't available in this view (3D views and schedules)."
    else:
        note = u"Place at lists the levels that have a plan view. Current view only links into the active view."

    worksets, active_index = collect_worksets()
    defaults, settings = load_settings(levels, view)
    settings["workset"] = max(active_index, 0)
    ctx = {"view": view, "levels": levels, "view_ok": view_ok, "force_view": force_view,
           "settings": settings, "note": note}
    files = []
    banner = [""]
    try:
        while True:
            refresh_states(files)
            for entry in files:
                if entry["state"] == "missing":
                    entry["ticked"] = False
            action = show_window(files, defaults, settings, worksets, ctx, banner)
            if action is None:
                return
            if action == "refresh":
                continue
            chosen = [e for e in files if e.get("ticked") and e["state"] != "missing"]
            for entry in files:
                entry["result"] = None
            pick_points(chosen, ctx)
            todo = [e for e in chosen if e["result"] is None]
            workset = worksets[settings["workset"]] if worksets else None
            if todo:
                link_files(todo, ctx, workset)
            done = [e for e in chosen if e["result"] and e["result"][0] == "ok"]
            for entry in done:
                entry["ticked"] = False
            banner[0] = u"Last run: {0} of {1} linked".format(len(done), len(chosen))
    finally:
        save_config(defaults, settings, levels)


main()

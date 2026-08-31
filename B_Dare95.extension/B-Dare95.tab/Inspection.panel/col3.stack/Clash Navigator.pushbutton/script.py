# -*- coding: utf-8 -*-
"""
Clash Navigator (single-file)
Loads a Navisworks HTML clash report, lets the user browse clashes, and
either isolates the two clashing elements in view or marks/frames the
clash point in the model.
"""

# ============================================================== parser
# Header-driven parser for Navisworks HTML clash reports. Navisworks lets
# users choose which columns to export, so this reads the actual header
# row (respecting colspan) and maps every data row to it by column
# start-offset, instead of hardcoding positions.

import re
import codecs
import urllib

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
TD_RE = re.compile(r"<td([^>]*)>(.*?)</td>", re.DOTALL | re.IGNORECASE)
COLSPAN_RE = re.compile(r'colspan="(\d+)"', re.IGNORECASE)
CLASS_RE = re.compile(r'class="([^"]*)"', re.IGNORECASE)
TEST_NAME_RE = re.compile(r'class="testName"[^>]*>(.*?)</td>', re.DOTALL | re.IGNORECASE)

# Only these row classes are real, individual clashes. "clashGroupRow" is a
# group HEADER that Navisworks inserts when it clusters similar clashes --
# its Item1/Item2/status/etc. duplicate the first real clash beneath it, so
# it is intentionally excluded here (confirmed against the sample report:
# including it over-counts clashes vs. the declared "Clashes" total).
TR_RE = re.compile(
    r'<tr\s+class="(contentRow|childRow|childRowLast)">(.*?)</tr>',
    re.DOTALL | re.IGNORECASE,
)
HEADER_TR_RE = re.compile(r'<tr\s+class="headerRow">(.*?)</tr>', re.DOTALL | re.IGNORECASE)
MAINTABLE_RE = re.compile(r'<table class="mainTable">(.*?)</table>', re.DOTALL | re.IGNORECASE)

ELEMENT_ID_RE = re.compile(r"(\d+)\s*$")
CLASH_POINT_RE = re.compile(
    r"(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)"
)
IMG_SRC_RE = re.compile(r'<img[^>]*\ssrc="([^"]+)"', re.IGNORECASE)


def read_report_text(path):
    """Reads the report as unicode. Navisworks writes UTF-8 (often with a BOM)
    but UTF-16 and cp1252 exports exist in the wild. Reading with a plain
    open(path, "r") and letting a non-ASCII character blow up later inside a
    WPF callback is one of the easier ways to lose a Revit session, so the
    decode is pinned down here instead."""
    f = open(path, "rb")
    try:
        raw = f.read()
    finally:
        f.close()

    if raw.startswith(codecs.BOM_UTF8):
        return raw[len(codecs.BOM_UTF8):].decode("utf-8", "replace")
    if raw.startswith(codecs.BOM_UTF16_LE) or raw.startswith(codecs.BOM_UTF16_BE):
        return raw.decode("utf-16", "replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", "replace")


def clean_text(raw_html_fragment):
    text = TAG_RE.sub("", raw_html_fragment)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = text.replace("&lt;", "<").replace("&gt;", ">")
    return WS_RE.sub(" ", text).strip()


def parse_td_cells(row_html):
    cells = []
    for match in TD_RE.finditer(row_html):
        attrs, inner = match.group(1), match.group(2)
        span_match = COLSPAN_RE.search(attrs)
        colspan = int(span_match.group(1)) if span_match else 1
        class_match = CLASS_RE.search(attrs)
        css_class = class_match.group(1) if class_match else ""
        cells.append({
            "colspan": colspan,
            "class": css_class,
            "text": clean_text(inner),
        })
    return cells


def build_column_map(header_cells):
    """Each header cell's start-offset, span, name, AND which side of the report it
    belongs to (item1 / item2 / general) -- derived from its own class attribute.
    Needed because some reports (unlike the original sample) put several columns
    per side (Item ID, Element Diameter, Element Id, ...) all sharing the same
    item1Content/item2Content class -- name+group is what disambiguates them."""
    col_map = []
    start = 0
    for cell in header_cells:
        css = (cell["class"] or "").lower()
        if "item1" in css:
            group = "item1"
        elif "item2" in css:
            group = "item2"
        else:
            group = "general"
        col_map.append((start, cell["colspan"], cell["text"], group))
        start += cell["colspan"]
    return col_map


def align_row_to_columns(row_cells, col_map):
    """Returns (general_cols, item1_cols, item2_cols), each {header_name: cell}.
    Keeping the three groups separate avoids collisions when item1 and item2
    happen to share identical column names (e.g. both sides have "Element Id")."""
    col_lookup = {}
    for c_start, c_span, c_name, c_group in col_map:
        col_lookup[c_start] = (c_name, c_group)

    general_cols, item1_cols, item2_cols = {}, {}, {}
    start = 0
    for cell in row_cells:
        name, group = col_lookup.get(start, ("col_{0}".format(start), "general"))
        target = item1_cols if group == "item1" else item2_cols if group == "item2" else general_cols
        target[name] = cell
        start += cell["colspan"]
    return general_cols, item1_cols, item2_cols


def extract_group_element_id(group_cols):
    """Find the Revit ElementId within one side's columns. Prefers a column
    literally named "Element Id"/"Element ID" (clean numeric id); falls back to
    any column whose header mentions "id" and whose text ends in digits (covers
    reports like the original sample, where the numeric id is embedded in a
    single "Item ID" cell as "Element ID: 542442")."""
    for name, cell in group_cols.items():
        if re.sub(r"\s+", "", name).lower() == "elementid":
            m = re.search(r"(\d+)", cell["text"])
            if m:
                return int(m.group(1))
    for name, cell in group_cols.items():
        if "id" in name.lower():
            m = ELEMENT_ID_RE.search(cell["text"])
            if m:
                return int(m.group(1))
    return None


def extract_clash_point(cell):
    if cell is None:
        return None
    m = CLASH_POINT_RE.search(cell["text"])
    if not m:
        return None
    return (float(m.group(1)), float(m.group(2)), float(m.group(3)))


def parse_report(html_text):
    """
    Returns a list of dicts: [{"name": "<Test Name>", "clashes": [ {...}, ... ]}, ...]
    Each clash dict: name, status, distance, grid_location, date_found,
    item1_id, item2_id, clash_point (X, Y, Z tuple in report units, or None).
    """
    tests = []
    chunks = html_text.split('<table class="testSummaryTable">')
    for chunk in chunks[1:]:
        name_match = TEST_NAME_RE.search(chunk)
        test_name = clean_text(name_match.group(1)) if name_match else "Unnamed Test"

        maintable_match = MAINTABLE_RE.search(chunk)
        if not maintable_match:
            continue
        maintable_html = maintable_match.group(1)

        header_matches = HEADER_TR_RE.findall(maintable_html)
        if len(header_matches) < 2:
            continue
        header_cells = parse_td_cells(header_matches[1])
        col_map = build_column_map(header_cells)

        clashes = []
        for row_match in TR_RE.finditer(maintable_html):
            row_cells = parse_td_cells(row_match.group(2))
            general_cols, item1_cols, item2_cols = align_row_to_columns(row_cells, col_map)

            point_cell = None
            for col_name, cell in general_cols.items():
                if "point" in col_name.lower():
                    point_cell = cell
                    break

            clash_name_cell = general_cols.get("Clash Name")
            status_cell = general_cols.get("Status")
            distance_cell = general_cols.get("Distance")
            grid_cell = general_cols.get("Grid Location")
            date_cell = general_cols.get("Date Found")

            img_match = IMG_SRC_RE.search(row_match.group(2))
            image_path = img_match.group(1).strip() if img_match else None

            clashes.append({
                "name": clash_name_cell["text"] if clash_name_cell else None,
                "status": status_cell["text"] if status_cell else None,
                "distance": distance_cell["text"] if distance_cell else None,
                "grid_location": grid_cell["text"] if grid_cell else None,
                "date_found": date_cell["text"] if date_cell else None,
                "item1_id": extract_group_element_id(item1_cols),
                "item2_id": extract_group_element_id(item2_cols),
                "clash_point": extract_clash_point(point_cell),
                "image_path": image_path,
            })

        tests.append({"name": test_name, "clashes": clashes})
    return tests

# ============================================================== main tool
import os
import clr
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")
clr.AddReference("System")

from System import EventHandler
from System import Uri, UriKind
from System.Collections.Generic import List
from System.Diagnostics import Process
from System.Windows import RoutedEventHandler
from System.Windows.Controls import SelectionChangedEventHandler, TextChangedEventHandler
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Markup import XamlReader
from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption
from System.Windows.Threading import Dispatcher, DispatcherFrame

from Autodesk.Revit.DB import (
    Transaction, BoundingBoxXYZ, XYZ, ElementId, FilteredElementCollector,
    RevitLinkInstance, FamilySymbol, UnitUtils, UnitTypeId, View3D,
    Structure,
)

from pyrevit import forms, script

logger = script.get_logger()

REPORT_LENGTH_UNIT = UnitTypeId.Meters       # unit the report's coordinates are in
BOX_SIZE_UNIT = UnitTypeId.Meters            # the "Clash Box Size (m)" field is always meters
CLASH_POINT_FAMILY_NAME = "Clash_Point"
DEFAULT_BOX_SIZE_M = 3.0


# ---------------------------------------------------------------- document access
# The window outlives any single Revit API call, so nothing here caches `doc` or
# `uidoc` at module level. If the user closes or switches documents while the
# window is open, a cached Document becomes a dead COM wrapper and touching it
# takes Revit down with it. Always re-fetch.

def get_uidoc():
    return __revit__.ActiveUIDocument


def get_doc():
    uidoc = __revit__.ActiveUIDocument
    return uidoc.Document if uidoc is not None else None


def require_doc():
    """Returns the active Document, or None after alerting the user."""
    doc = get_doc()
    if doc is None:
        forms.alert("No active Revit document. Open a project and try again.")
        return None
    return doc


# ---------------------------------------------------------------- element resolution

def get_link_instances(doc):
    return FilteredElementCollector(doc).OfClass(RevitLinkInstance).ToElements()


def resolve_element(doc, element_id):
    """
    Returns (element, doc_it_lives_in, link_instance_or_None) or (None, None, None).
    Checks host doc first, then every loaded link.

    Note: ids are NOT interchangeable across documents -- the same integer can be a
    valid element in the host and in a link. Host wins, which matches how the
    Navisworks report is normally read back.
    """
    if element_id is None or doc is None:
        return None, None, None

    eid = ElementId(element_id)
    el = doc.GetElement(eid)
    if el is not None:
        return el, doc, None

    for link_inst in get_link_instances(doc):
        link_doc = link_inst.GetLinkDocument()
        if link_doc is None:
            continue
        link_el = link_doc.GetElement(eid)
        if link_el is not None:
            return link_el, link_doc, link_inst
    return None, None, None


def element_label(element, link_instance):
    if element is None:
        return "(not found in host or any loaded link)"
    try:
        cat = element.Category.Name if element.Category else "?"
    except Exception:
        cat = "?"
    try:
        name = element.Name
    except Exception:
        name = "?"
    if link_instance is not None:
        try:
            link_name = link_instance.Name
        except Exception:
            link_name = "link"
        return u"{0}  |  {1}   [in link: {2}]".format(cat, name, link_name)
    return u"{0}  |  {1}".format(cat, name)


def load_bitmap(path):
    """Loads an image file into a WPF BitmapImage, or returns None if the path is
    missing/invalid. CacheOption.OnLoad releases the file handle immediately so the
    image file isn't left locked."""
    if not path or not os.path.isfile(path):
        return None
    try:
        bmp = BitmapImage()
        bmp.BeginInit()
        bmp.UriSource = Uri(path, UriKind.Absolute)
        bmp.CacheOption = BitmapCacheOption.OnLoad
        bmp.EndInit()
        return bmp
    except Exception:
        return None


def safe_handler(func):
    """Wraps a WPF event handler so an unhandled exception shows an alert instead of
    an unhandled .NET exception potentially crashing Revit. Every single handler
    attached below goes through this -- an escaped Python exception inside a WPF
    callback is a hard Revit crash, not a traceback."""
    def wrapper(sender, args):
        try:
            func(sender, args)
        except Exception as ex:
            logger.error("Clash Navigator error: {0}".format(ex))
            forms.alert("Clash Navigator ran into an error:\n\n{0}".format(ex))
    return wrapper


# ---------------------------------------------------------------- actions
# These run straight from the WPF handlers. That is legal here *because* of
# PushFrame: the external command's Execute() has not returned yet, so Revit's
# API context is still open for the whole life of the window.

def to_internal(point_tuple):
    x, y, z = point_tuple
    return XYZ(
        UnitUtils.ConvertToInternalUnits(x, REPORT_LENGTH_UNIT),
        UnitUtils.ConvertToInternalUnits(y, REPORT_LENGTH_UNIT),
        UnitUtils.ConvertToInternalUnits(z, REPORT_LENGTH_UNIT),
    )


def do_focus(clash):
    doc = require_doc()
    if doc is None:
        return

    el1, doc1, link1 = resolve_element(doc, clash["item1_id"])
    el2, doc2, link2 = resolve_element(doc, clash["item2_id"])

    ids = []
    for el, link in ((el1, link1), (el2, link2)):
        if el is None:
            continue
        # elements inside a link can't be isolated individually -- isolate the link instance
        ids.append(link.Id if link is not None else el.Id)

    if not ids:
        forms.alert("Neither Item 1 nor Item 2 could be resolved in the host model or any loaded link.")
        return

    view = doc.ActiveView
    if view is None or not view.CanUseTemporaryVisibilityModes():
        forms.alert("The active view doesn't support temporary isolate. Switch to a plan, section or 3D view.")
        return

    t = Transaction(doc, "Clash Navigator - Focus")
    t.Start()
    try:
        # IsolateElementsTemporary wants a real .NET ICollection[ElementId] -- a plain
        # Python list doesn't satisfy that interface here, so wrap it explicitly.
        view.IsolateElementsTemporary(List[ElementId](ids))
        t.Commit()
    except Exception:
        t.RollBack()
        raise

    get_uidoc().RefreshActiveView()


def do_clash_box(clash, box_size_m):
    doc = require_doc()
    if doc is None:
        return

    if clash["clash_point"] is None:
        forms.alert("This clash has no clash-point coordinates in the report.")
        return

    view = doc.ActiveView
    if not isinstance(view, View3D):
        forms.alert("Switch to a 3D view first -- Clash Box sets that view's section box.")
        return
    if view.IsLocked:
        forms.alert("The active 3D view is locked; unlock it to set a section box.")
        return

    center = to_internal(clash["clash_point"])
    # The box size is entered in meters regardless of REPORT_LENGTH_UNIT, so it is
    # converted with BOX_SIZE_UNIT -- converting it with the report unit would make
    # a "3" mean 3 mm on a millimeter report.
    half = UnitUtils.ConvertToInternalUnits(box_size_m / 2.0, BOX_SIZE_UNIT)
    bbox = BoundingBoxXYZ()
    bbox.Min = XYZ(center.X - half, center.Y - half, center.Z - half)
    bbox.Max = XYZ(center.X + half, center.Y + half, center.Z + half)

    t = Transaction(doc, "Clash Navigator - Clash Box")
    t.Start()
    try:
        view.SetSectionBox(bbox)
        view.IsSectionBoxActive = True
        t.Commit()
    except Exception:
        t.RollBack()
        raise

    get_uidoc().RefreshActiveView()


def find_clash_point_symbol(doc):
    symbols = FilteredElementCollector(doc).OfClass(FamilySymbol).ToElements()
    for sym in symbols:
        if sym.Family.Name == CLASH_POINT_FAMILY_NAME:
            return sym
    return None


def do_model_point(clash):
    doc = require_doc()
    if doc is None:
        return

    if clash["clash_point"] is None:
        forms.alert("This clash has no clash-point coordinates in the report.")
        return

    symbol = find_clash_point_symbol(doc)
    if symbol is None:
        forms.alert(
            "No family named '{0}' is loaded. Load a small generic-model "
            "marker family with that name and try again.".format(CLASH_POINT_FAMILY_NAME)
        )
        return

    point = to_internal(clash["clash_point"])
    t = Transaction(doc, "Clash Navigator - Model Clash Point")
    t.Start()
    try:
        if not symbol.IsActive:
            symbol.Activate()
            doc.Regenerate()
        doc.Create.NewFamilyInstance(point, symbol, Structure.StructuralType.NonStructural)
        t.Commit()
    except Exception:
        t.RollBack()
        raise


# ---------------------------------------------------------------- WPF UI

XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Clash Navigator" Height="620" Width="820"
        WindowStartupLocation="CenterScreen"
        Background="#1E1E2E">
    <Window.Resources>
        <Style x:Key="RoundButton" TargetType="Button">
            <Setter Property="Background" Value="#313244"/>
            <Setter Property="Foreground" Value="#CDD6F4"/>
            <Setter Property="BorderThickness" Value="0"/>
            <Setter Property="Padding" Value="10,6"/>
            <Setter Property="Margin" Value="0,0,0,8"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="Button">
                        <Border Background="{TemplateBinding Background}" CornerRadius="6">
                            <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
                        </Border>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>
        <Style x:Key="AccentButton" TargetType="Button" BasedOn="{StaticResource RoundButton}">
            <Setter Property="Background" Value="#F0A500"/>
            <Setter Property="Foreground" Value="#1E1E2E"/>
        </Style>
    </Window.Resources>
    <Grid Margin="12">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <DockPanel Grid.Row="0" Margin="0,0,0,10">
            <Button x:Name="LoadButton" Content="Load HTML Report..." DockPanel.Dock="Left"
                    Width="170" Style="{StaticResource AccentButton}" Margin="0,0,10,0"/>
            <TextBlock x:Name="ReportLabel" Text="No report loaded" Foreground="#A6ADC8"
                       VerticalAlignment="Center"/>
        </DockPanel>

        <Grid Grid.Row="1">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="260"/>
            </Grid.ColumnDefinitions>

            <DockPanel Grid.Column="0" Margin="0,0,10,0">
                <TextBox x:Name="FilterBox" DockPanel.Dock="Top" Margin="0,0,0,8"
                         Background="#2A2A3C" Foreground="#CDD6F4" BorderBrush="#45475A"
                         Padding="6" Tag="Filter clashes..."/>
                <ListBox x:Name="ClashList" Background="#2A2A3C" Foreground="#CDD6F4"
                         BorderThickness="0"/>
            </DockPanel>

            <StackPanel Grid.Column="1">
                <Image x:Name="ClashImage" Height="160" Stretch="Uniform" Margin="0,0,0,10"/>
                <TextBlock Text="Clash Details" Foreground="#CDD6F4" FontWeight="Bold" Margin="0,0,0,8"/>
                <TextBlock x:Name="Item1Label" Foreground="#A6ADC8" TextWrapping="Wrap" Margin="0,0,0,6"/>
                <TextBlock x:Name="Item2Label" Foreground="#A6ADC8" TextWrapping="Wrap" Margin="0,0,0,16"/>

                <Button x:Name="FocusButton" Content="Focus / Isolate" Style="{StaticResource RoundButton}"/>

                <TextBlock Text="Clash Box Size (m)" Foreground="#A6ADC8" Margin="0,8,0,2"/>
                <TextBox x:Name="BoxSizeBox" Background="#2A2A3C" Foreground="#CDD6F4"
                         BorderBrush="#45475A" Padding="6" Margin="0,0,0,8"/>
                <Button x:Name="ClashBoxButton" Content="Create Clash Box" Style="{StaticResource RoundButton}"/>

                <Button x:Name="ModelPointButton" Content="Model Clash Point"
                        Style="{StaticResource RoundButton}" Margin="0,16,0,0"/>
            </StackPanel>
        </Grid>

        <TextBlock x:Name="StatusLabel" Grid.Row="2" Margin="0,10,0,0"
                   Foreground="#A6ADC8" Text="Ready."/>
    </Grid>
</Window>
"""


def build_flat_list(tests):
    flat = []
    for test in tests:
        for c in test["clashes"]:
            entry = dict(c)
            entry["test"] = test["name"]
            entry["label"] = u"[{0}] {1}  ({2} vs {3})".format(
                test["name"], c["name"], c["item1_id"], c["item2_id"]
            )
            flat.append(entry)
    return flat


def resolve_image_path(report_dir, rel):
    """Navisworks writes image srcs relative to the report, URL-escaped
    (%20 for spaces). Un-escape before joining or every path with a space in it
    silently resolves to nothing."""
    if not rel:
        return None
    try:
        rel = urllib.unquote(rel)
    except Exception:
        pass
    rel = rel.replace("/", os.sep).replace("\\", os.sep)
    if os.path.isabs(rel):
        return rel
    return os.path.join(report_dir, rel)


def run():
    window = XamlReader.Parse(XAML)

    # Parent the window to Revit's main window so it floats above Revit instead of
    # disappearing behind it, and so pyRevit's file dialog opens over it.
    try:
        helper = WindowInteropHelper(window)
        helper.Owner = Process.GetCurrentProcess().MainWindowHandle
    except Exception:
        logger.debug("Could not set Revit as the owner window.")

    load_button = window.FindName("LoadButton")
    report_label = window.FindName("ReportLabel")
    clash_list = window.FindName("ClashList")
    filter_box = window.FindName("FilterBox")
    clash_image = window.FindName("ClashImage")
    item1_label = window.FindName("Item1Label")
    item2_label = window.FindName("Item2Label")
    focus_button = window.FindName("FocusButton")
    box_size_box = window.FindName("BoxSizeBox")
    clash_box_button = window.FindName("ClashBoxButton")
    model_point_button = window.FindName("ModelPointButton")
    status_label = window.FindName("StatusLabel")

    box_size_box.Text = str(DEFAULT_BOX_SIZE_M)

    # mutable containers stand in for closures over primitives (IronPython 2.7 has no nonlocal)
    flat_items = [[]]
    visible_items = [[]]
    selected = [None]

    def set_status(text):
        status_label.Text = text

    def refresh_list():
        clash_list.Items.Clear()
        for entry in visible_items[0]:
            clash_list.Items.Add(entry["label"])

    def on_filter_changed(sender, args):
        query = filter_box.Text.strip().lower()
        if not query:
            visible_items[0] = flat_items[0]
        else:
            visible_items[0] = [e for e in flat_items[0] if query in e["label"].lower()]
        refresh_list()
        set_status(u"{0} of {1} clashes shown.".format(len(visible_items[0]), len(flat_items[0])))

    def on_load_click(sender, args):
        html_path = forms.pick_file(file_ext="html", title="Select Navisworks Clash Report (HTML)")
        if not html_path:
            return

        html_text = read_report_text(html_path)
        tests = parse_report(html_text)
        items = build_flat_list(tests)
        if not items:
            forms.alert("No clashes were found in this report.")
            return

        report_dir = os.path.dirname(html_path)
        for entry in items:
            entry["image_abs_path"] = resolve_image_path(report_dir, entry.get("image_path"))

        flat_items[0] = items
        visible_items[0] = items
        filter_box.Text = ""          # fires on_filter_changed, which re-renders the list
        item1_label.Text = ""
        item2_label.Text = ""
        clash_image.Source = None
        selected[0] = None
        report_label.Text = os.path.basename(html_path)
        refresh_list()
        set_status(u"Loaded {0} clashes from {1} test(s).".format(len(items), len(tests)))

    def on_selection_changed(sender, args):
        idx = clash_list.SelectedIndex
        if idx < 0 or idx >= len(visible_items[0]):
            selected[0] = None
            item1_label.Text = ""
            item2_label.Text = ""
            clash_image.Source = None
            return

        clash = visible_items[0][idx]
        selected[0] = clash
        clash_image.Source = load_bitmap(clash.get("image_abs_path"))

        doc = get_doc()
        if doc is None:
            item1_label.Text = u"Item 1 (ID {0}): (no active document)".format(clash["item1_id"])
            item2_label.Text = u"Item 2 (ID {0}): (no active document)".format(clash["item2_id"])
            return

        el1, _, link1 = resolve_element(doc, clash["item1_id"])
        el2, _, link2 = resolve_element(doc, clash["item2_id"])
        item1_label.Text = u"Item 1 (ID {0}): {1}".format(clash["item1_id"], element_label(el1, link1))
        item2_label.Text = u"Item 2 (ID {0}): {1}".format(clash["item2_id"], element_label(el2, link2))

    def on_focus_click(sender, args):
        if selected[0] is None:
            set_status("Select a clash first.")
            return
        do_focus(selected[0])

    def on_clash_box_click(sender, args):
        if selected[0] is None:
            set_status("Select a clash first.")
            return
        try:
            size = float(box_size_box.Text)
        except ValueError:
            forms.alert("Clash box size must be a number.")
            return
        if size <= 0:
            forms.alert("Clash box size must be greater than zero.")
            return
        do_clash_box(selected[0], size)

    def on_model_point_click(sender, args):
        if selected[0] is None:
            set_status("Select a clash first.")
            return
        do_model_point(selected[0])

    frame = DispatcherFrame()

    def on_closed(sender, args):
        # Ends the nested message loop below, which lets run() -- and therefore the
        # pyRevit script -- finish cleanly. Without this the engine would sit in
        # PushFrame forever after the window is gone.
        frame.Continue = False

    load_button.Click += RoutedEventHandler(safe_handler(on_load_click))
    focus_button.Click += RoutedEventHandler(safe_handler(on_focus_click))
    clash_box_button.Click += RoutedEventHandler(safe_handler(on_clash_box_click))
    model_point_button.Click += RoutedEventHandler(safe_handler(on_model_point_click))
    filter_box.TextChanged += TextChangedEventHandler(safe_handler(on_filter_changed))
    clash_list.SelectionChanged += SelectionChangedEventHandler(safe_handler(on_selection_changed))
    window.Closed += EventHandler(on_closed)

    refresh_list()

    # Non-modal show + nested dispatcher frame. Show() does not block, so Revit is
    # never put into a modal state (the ribbon stays enabled and the view stays
    # navigable); PushFrame keeps pumping messages and keeps this script -- and the
    # Revit API context it owns -- alive until the window is closed.
    window.Show()
    Dispatcher.PushFrame(frame)


run()
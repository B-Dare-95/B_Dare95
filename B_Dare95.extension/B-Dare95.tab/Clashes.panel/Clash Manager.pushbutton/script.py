# -*- coding: utf-8 -*-
__doc__ = """__________________________________________________
Description:

Go through your Navisworks clash reports without leaving Revit: find each clash, fix it, and tick it off.
Your Solved / Approved ticks are saved next to the report, so your team sees them too.
__________________________________________________
How-to:

-> Click on the button
-> Click Load HTML Reports and pick one or more reports
-> Click a clash, then Focus (zoom to it) or Isolate (hide the rest)
-> In a 3D view, Create Clash Box boxes in the clash point
-> Tick Solved or Approved as you go
-> Click Export Results for a progress report to share
__________________________________________________
Author: Mohamed Bedair"""

__persistentengine__ = True

# ============================================================== parser
# Header-driven parser for Navisworks HTML clash reports. Navisworks lets
# users choose which columns to export, so this reads the actual header
# row (respecting colspan) and maps every data row to it by column
# start-offset, instead of hardcoding positions.
#
# PERFORMANCE NOTE: real reports get wide. A single-test export with the
# "Element" property set switched on runs to ~6,900 columns and ~2.6 million
# table cells across 383 clashes (85 MB of HTML). Cleaning and boxing every
# one of those cells is minutes of work in IronPython and hundreds of MB of
# garbage inside Revit's process, for maybe a dozen cells per row that are
# actually read. So: the column map is built once per test, the set of column
# offsets worth keeping is derived from it, and every other cell is skipped
# after reading nothing but its colspan. Nothing is sliced out of the source
# string either -- the compiled patterns are given (pos, endpos) ranges over
# the one copy of the document, because .group() on an 85 MB table is another
# 170 MB of UTF-16 in Revit's heap.

import re
import codecs
import urllib

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
TD_RE = re.compile(r"<td([^>]*)>(.*?)</td>", re.DOTALL | re.IGNORECASE)
COLSPAN_RE = re.compile(r'colspan="(\d+)"', re.IGNORECASE)
CLASS_RE = re.compile(r'class="([^"]*)"', re.IGNORECASE)
TEST_NAME_RE = re.compile(r'class="testName"[^>]*>(.*?)</td>', re.DOTALL | re.IGNORECASE)
SUMMARY_TABLE_RE = re.compile(r'<table class="testSummaryTable">', re.IGNORECASE)

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
IMG_SRC_RE = re.compile(r'<img[^>]*\ssrc="([^"]+)"', re.IGNORECASE)

# Clash-point cell text. Navisworks writes the axis LABELS into the cell:
#     x:585799.215, y:2368832.543, z:648.240
# so a pattern that expects a bare "n, n, n" triple never matches and every
# clash silently reports "no clash point". Labelled form is tried first, then
# the bare triple (older/other exports), then a last-ditch "first three
# numbers in the cell".
_NUM = r"(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)"
CLASH_POINT_LABELED_RE = re.compile(
    r"x\s*[:=]\s*" + _NUM + r"\s*[,;]\s*"
    r"y\s*[:=]\s*" + _NUM + r"\s*[,;]\s*"
    r"z\s*[:=]\s*" + _NUM,
    re.IGNORECASE,
)
CLASH_POINT_BARE_RE = re.compile(
    _NUM + r"\s*[,;]\s*" + _NUM + r"\s*[,;]\s*" + _NUM
)
NUMBER_RE = re.compile(_NUM)


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


def make_cell(colspan, css_class, inner_html):
    return {"colspan": colspan, "class": css_class, "text": clean_text(inner_html)}


def iter_row_cells(text, pos, endpos, wanted_starts=None):
    """Walks one <tr>'s cells over text[pos:endpos] without slicing it out.

    Yields (column_start_offset, cell_dict). When wanted_starts is given, only
    cells starting at one of those offsets are built -- every other cell costs
    one colspan check and nothing else. That is the difference between ~3,400
    cells built and ~2,660,000 on a wide report."""
    start = 0
    for match in TD_RE.finditer(text, pos, endpos):
        attrs = match.group(1)
        # cheap containment test first: most cells carry no colspan at all,
        # and running the regex on every one of 2.6M cells is not free
        if "olspan" in attrs:
            span_match = COLSPAN_RE.search(attrs)
            colspan = int(span_match.group(1)) if span_match else 1
        else:
            colspan = 1

        if wanted_starts is None or start in wanted_starts:
            class_match = CLASS_RE.search(attrs)
            yield start, make_cell(colspan, class_match.group(1) if class_match else "",
                                   match.group(2))
        start += colspan


def build_column_map(text, pos, endpos):
    """Each header cell's start-offset, span, name, AND which side of the report it
    belongs to (item1 / item2 / general) -- derived from its own class attribute.
    Needed because some reports put several columns per side (Item ID, Element
    Diameter, Element Id, ...) all sharing the same item1Content/item2Content
    class -- name+group is what disambiguates them."""
    col_map = []
    for start, cell in iter_row_cells(text, pos, endpos):
        css = (cell["class"] or "").lower()
        if "item1" in css:
            group = "item1"
        elif "item2" in css:
            group = "item2"
        else:
            group = "general"
        col_map.append((start, cell["colspan"], cell["text"], group))
    return col_map


def find_point_column(col_map):
    """Returns (start, span) of the general "Clash Point" column, or None."""
    for start, span, name, group in col_map:
        if group == "general" and "point" in name.lower():
            return (start, span)
    return None


def id_column_starts(col_map, group):
    """Which columns on one side could hold the Revit ElementId. Mirrors the
    preference order in extract_group_element_id: an exact "Element Id" column
    if the export has one, otherwise every column whose header mentions "id".
    (The loose pass is deliberately wide -- on a 3,464-column side it matches
    ~300 headers like "Category IsValid" -- but it only runs when there is no
    exact column, and the ordered scan means the leftmost real id still wins.)"""
    side = [(start, name) for start, span, name, g in col_map if g == group]
    exact = [start for start, name in side
             if re.sub(r"\s+", "", name).lower() == "elementid"]
    if exact:
        return exact
    return [start for start, name in side if "id" in name.lower()]


def build_kept_columns(col_map):
    """Returns (kept_cols, wanted_starts). kept_cols is the small subset of the
    column map that rows are aligned against; wanted_starts also covers every
    offset inside the Clash Point column's span, because some exports split
    X/Y/Z into three separate <td>s under one spanning header."""
    wanted = set()
    kept = []

    for entry in col_map:
        start, span, name, group = entry
        if group == "general":
            kept.append(entry)
            wanted.add(start)

    point_col = find_point_column(col_map)
    if point_col is not None:
        p_start, p_span = point_col
        for offset in range(p_start, p_start + p_span):
            wanted.add(offset)

    for group in ("item1", "item2"):
        starts = set(id_column_starts(col_map, group))
        wanted.update(starts)
        for entry in col_map:
            if entry[3] == group and entry[0] in starts:
                kept.append(entry)

    return kept, wanted


def align_row(cells_by_start, kept_cols):
    """Returns (general_cols, item1_cols, item2_cols).

    general_cols is a {header_name: cell} dict; the two item groups are ORDERED
    lists of (header_name, cell) so that id extraction scans left-to-right.
    Dict iteration order is not defined in IronPython 2.7, and picking "the
    first column whose header mentions id" out of an unordered dict is how you
    get a different ElementId on different runs of the same report."""
    general_cols = {}
    item1_cols = []
    item2_cols = []
    for start, span, name, group in kept_cols:
        cell = cells_by_start.get(start)
        if cell is None:
            continue
        if group == "item1":
            item1_cols.append((name, cell))
        elif group == "item2":
            item2_cols.append((name, cell))
        else:
            general_cols[name] = cell
    return general_cols, item1_cols, item2_cols


def extract_group_element_id(group_cols):
    """Find the Revit ElementId within one side's columns. Prefers a column
    literally named "Element Id"/"Element ID" (clean numeric id); falls back to
    any column whose header mentions "id" and whose text ends in digits (covers
    reports where the numeric id is embedded in a single "Item ID" cell as
    "Element ID: 542442")."""
    for name, cell in group_cols:
        if re.sub(r"\s+", "", name).lower() == "elementid":
            m = re.search(r"(\d+)", cell["text"])
            if m:
                return int(m.group(1))
    for name, cell in group_cols:
        if "id" in name.lower():
            m = ELEMENT_ID_RE.search(cell["text"])
            if m:
                return int(m.group(1))
    return None


def extract_clash_point(cells_by_start, point_col):
    """point_col is (start, span). The X/Y/Z may sit in one spanning cell
    ("x:1.0, y:2.0, z:3.0") or in separate cells under a spanning header, so
    every cell inside the span is joined before matching."""
    if point_col is None:
        return None

    p_start, p_span = point_col
    parts = []
    for offset in range(p_start, p_start + p_span):
        cell = cells_by_start.get(offset)
        if cell is not None and cell["text"]:
            parts.append(cell["text"])
    if not parts:
        return None
    text = ", ".join(parts)

    m = CLASH_POINT_LABELED_RE.search(text)
    if m is None:
        m = CLASH_POINT_BARE_RE.search(text)
    if m is not None:
        return (float(m.group(1)), float(m.group(2)), float(m.group(3)))

    numbers = NUMBER_RE.findall(text)
    if len(numbers) >= 3:
        return (float(numbers[0]), float(numbers[1]), float(numbers[2]))
    return None


def parse_report(html_text, progress=None):
    """
    Returns a list of dicts: [{"name": "<Test Name>", "clashes": [ {...}, ... ]}, ...]
    Each clash dict: name, status, distance, grid_location, date_found,
    item1_id, item2_id, clash_point (X, Y, Z tuple in report units, or None).

    progress, if given, is called as progress(test_name, clashes_so_far) every
    so often so the caller can keep the UI painting on a big report.
    """
    tests = []

    # test boundaries, as (start, end) index pairs into html_text -- no slicing
    bounds = [m.start() for m in SUMMARY_TABLE_RE.finditer(html_text)]
    if not bounds:
        return tests
    bounds.append(len(html_text))

    for i in range(len(bounds) - 1):
        chunk_start, chunk_end = bounds[i], bounds[i + 1]

        name_match = TEST_NAME_RE.search(html_text, chunk_start, chunk_end)
        test_name = clean_text(name_match.group(1)) if name_match else "Unnamed Test"

        maintable_match = MAINTABLE_RE.search(html_text, chunk_start, chunk_end)
        if not maintable_match:
            continue
        main_start, main_end = maintable_match.start(1), maintable_match.end(1)

        header_spans = []
        for hm in HEADER_TR_RE.finditer(html_text, main_start, main_end):
            header_spans.append((hm.start(1), hm.end(1)))
            if len(header_spans) >= 2:
                break
        if len(header_spans) < 2:
            continue

        # header_spans[0] is the Item 1 / Item 2 banner row; [1] is the real one
        col_map = build_column_map(html_text, header_spans[1][0], header_spans[1][1])
        kept_cols, wanted_starts = build_kept_columns(col_map)
        point_col = find_point_column(col_map)

        clashes = []
        for row_index, row_match in enumerate(TR_RE.finditer(html_text, main_start, main_end)):
            row_start, row_end = row_match.start(2), row_match.end(2)

            cells_by_start = {}
            for start, cell in iter_row_cells(html_text, row_start, row_end, wanted_starts):
                cells_by_start[start] = cell

            general_cols, item1_cols, item2_cols = align_row(cells_by_start, kept_cols)

            clash_name_cell = general_cols.get("Clash Name")
            status_cell = general_cols.get("Status")
            distance_cell = general_cols.get("Distance")
            grid_cell = general_cols.get("Grid Location")
            date_cell = general_cols.get("Date Found")

            img_match = IMG_SRC_RE.search(html_text, row_start, row_end)
            image_path = img_match.group(1).strip() if img_match else None

            clashes.append({
                "name": clash_name_cell["text"] if clash_name_cell else None,
                "status": status_cell["text"] if status_cell else None,
                "distance": distance_cell["text"] if distance_cell else None,
                "grid_location": grid_cell["text"] if grid_cell else None,
                "date_found": date_cell["text"] if date_cell else None,
                "item1_id": extract_group_element_id(item1_cols),
                "item2_id": extract_group_element_id(item2_cols),
                "clash_point": extract_clash_point(cells_by_start, point_col),
                "image_path": image_path,
            })

            if progress is not None and row_index % 25 == 0:
                progress(test_name, len(clashes))

        tests.append({"name": test_name, "clashes": clashes})
    return tests

# ============================================================== main tool
import os
import math
import json
import hashlib
import datetime
import clr
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")
clr.AddReference("System")

from System import Action, EventHandler
from System import Uri, UriKind
from System.Collections.Generic import List
from System.Diagnostics import Process
from System.Windows import (
    RoutedEventHandler, Thickness, CornerRadius, VerticalAlignment, HorizontalAlignment, TextTrimming,
    Point,
)
from System.Windows.Controls import (
    SelectionChangedEventHandler,
    CheckBox, TextBlock, DockPanel, Border, Dock, Button,
)
from System.Windows.Input import MouseButtonEventHandler, Cursors
from System.Windows.Media import BrushConverter, ColorConverter, LinearGradientBrush, GradientStop
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Markup import XamlReader
from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption
from System.Windows.Threading import DispatcherPriority

from Autodesk.Revit.DB import (
    Transaction, BoundingBoxXYZ, XYZ, ElementId, FilteredElementCollector,
    RevitLinkInstance, UnitUtils, UnitTypeId, View3D, Reference, TemporaryViewMode,
    ElementType, CategoryType, BuiltInCategory, FamilyInstance, Wall,
    BoundingBoxIntersectsFilter, Outline,
)
from Autodesk.Revit.DB.Architecture import (
    Railing, ContinuousRail, Stairs, StairsRun, StairsLanding,
)
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent

from pyrevit import forms, script
from pyrevit.coreutils import envvars

logger = script.get_logger()

REPORT_LENGTH_UNIT = UnitTypeId.Meters       # unit the report's coordinates are in
BOX_SIZE_UNIT = UnitTypeId.Meters            # the "Clash Box Size (m)" field is always meters
DEFAULT_BOX_SIZE_M = 3.0

# Clearance added on every side of the two clashing elements when Focus fits
# its section box and zoom around them. Without it a thin element (a pipe, a
# duct) gets a section box that slices its own surfaces off.
FOCUS_BOX_PADDING_M = 0.5

# How the report's clash-point coordinates map onto Revit internal coordinates.
#
#   "auto"                  -> try every mode below on the first clash that has
#                              resolvable elements, keep whichever lands on top
#                              of those elements, and reuse it for the session.
#   "internal"              -> the numbers are already Revit internal coordinates.
#   "location_transform"    -> ActiveProjectLocation.GetTotalTransform().OfPoint()
#   "location_transform_inverse" -> ...GetTotalTransform().Inverse.OfPoint()
#
# The two transform modes exist because which direction GetTotalTransform() runs
# depends on the project, and getting it backwards does not fail loudly -- it
# just puts the point a few thousand kilometres away. Rather than hardcode a
# guess, "auto" measures: the clash point must land on or near the two elements
# the report says are clashing, and only one candidate ever will. Pin this to a
# fixed mode once you know which one your exports use.
CLASH_POINT_COORD_SYSTEM = "auto"

COORD_MODES = ("internal", "location_transform", "location_transform_inverse")

# How close a candidate point has to land to the clashing elements to be
# believed. Generous on purpose: the wrong candidates miss by kilometres, so
# there is no risk of an ambiguous winner.
COORD_DETECT_TOLERANCE_M = 500.0

# Remembers the mode detected this session so it is worked out once, not per clash.
_COORD_MODE = [None]

# Revit refuses to work reliably more than ~20 miles from the internal origin.
# A point beyond this almost always means CLASH_POINT_COORD_SYSTEM (or
# REPORT_LENGTH_UNIT) is set wrong, so it is worth catching before Revit throws
# something far less informative.
REVIT_MODEL_LIMIT_FT = 20.0 * 5280.0


# ---------------------------------------------------------------- session state
# A persistent engine reuses the same AppDomain but hands each run a fresh
# module scope, so plain module globals are wiped every time the button is
# pressed. pyRevit's env vars live above that and are what lets a second press
# find the window that is already open -- and what holds the only strong
# reference keeping the ExternalEvent alive while the window is up.

SESSION_KEY = "CLASHNAV_SESSION"


def get_session():
    try:
        return envvars.get_pyrevit_env_var(SESSION_KEY)
    except Exception:
        return None


def set_session(value):
    try:
        envvars.set_pyrevit_env_var(SESSION_KEY, value)
    except Exception:
        logger.debug("Could not store the Clash Navigator session.")


# ---------------------------------------------------------------- external event

class ClashEventHandler(IExternalEventHandler):
    """Runs queued work inside a valid Revit API context.

    Once the script has returned, a WPF button handler is just a callback on
    Revit's UI thread with no API context open -- Transactions and even element
    lookups are illegal there. Raise() hands the work to Revit, which calls
    Execute() back when it is idle, i.e. when the user is not mid-command. That
    is also why the user can be halfway through dragging a pipe when they click
    Focus: Revit simply runs it once they are done.

    Execute() itself runs on the UI thread, so the actions may touch the WPF
    controls directly.

    A queue rather than a single slot: two quick clicks are two pieces of work,
    and Revit may coalesce the Raise() calls into one Execute().
    """

    def __init__(self):
        self.queue = []

    def enqueue(self, action):
        self.queue.append(action)

    def Execute(self, uiapp):
        pending, self.queue = self.queue, []
        for action in pending:
            try:
                action()
            except Exception as ex:
                logger.error("Clash Navigator error: {0}".format(ex))
                forms.alert("Clash Navigator ran into an error:\n\n{0}".format(ex))

    def GetName(self):
        return "Clash Navigator"


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


def is_model_element(element):
    """A placed, physical element -- the only kind Navisworks can report as
    clashing. Types, link instances, views and other non-model elements are
    exactly what a stray id-number collision tends to land on."""
    if element is None or isinstance(element, (ElementType, RevitLinkInstance)):
        return False
    try:
        category = element.Category
        return category is not None and category.CategoryType == CategoryType.Model
    except Exception:
        return False


def element_candidates(doc, element_id):
    """Every (element, link_instance_or_None, host_extent) this id number could
    mean: the host, then every loaded link instance, model elements only.

    Ids are NOT unique across documents. Each model numbers its own elements,
    so the id of a linked duct routinely also exists in the host as something
    else. Taking the first hit ("host wins") turns a host-vs-link clash into a
    host-vs-host one and isolates the link out of sight. A link loaded more
    than once gives one candidate per instance; proximity picks the right one."""
    if element_id is None or doc is None:
        return []

    eid = ElementId(element_id)
    sources = [(doc, None)]
    for link_inst in get_link_instances(doc):
        link_doc = link_inst.GetLinkDocument()
        if link_doc is not None:
            sources.append((link_doc, link_inst))

    found = []
    for source_doc, link_inst in sources:
        el = source_doc.GetElement(eid)
        if not is_model_element(el):
            continue
        extent = host_extent([(el, link_inst)])
        if extent is not None:
            found.append((el, link_inst, extent))
    return found


def extent_gap(a, b):
    """Shortest distance between two (low, high) boxes, zero if they overlap."""
    (alo, ahi), (blo, bhi) = a, b
    dx = max(alo.X - bhi.X, 0.0, blo.X - ahi.X)
    dy = max(alo.Y - bhi.Y, 0.0, blo.Y - ahi.Y)
    dz = max(alo.Z - bhi.Z, 0.0, blo.Z - ahi.Z)
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def same_element(el_a, link_a, el_b, link_b):
    if id_value(el_a.Id) != id_value(el_b.Id):
        return False
    if link_a is None or link_b is None:
        return link_a is None and link_b is None
    return id_value(link_a.Id) == id_value(link_b.Id)


def resolve_clash_pair(doc, clash):
    """Returns ((el1, link1), (el2, link2)); either element may be None.

    When an id matches in several models, the pair that is physically closest
    wins -- the two items of a clash are, by definition, touching. Ties go to
    the pair with fewer linked elements, so a genuine host-vs-host clash is
    never pulled into a link. A side with no other side to measure against
    falls back to its first candidate (host first)."""
    cands1 = element_candidates(doc, clash["item1_id"])
    cands2 = element_candidates(doc, clash["item2_id"])

    best = None
    for el1, link1, ext1 in cands1:
        for el2, link2, ext2 in cands2:
            if same_element(el1, link1, el2, link2):
                continue
            key = (extent_gap(ext1, ext2), (link1 is not None) + (link2 is not None))
            if best is None or key < best[0]:
                best = (key, (el1, link1), (el2, link2))
    if best is not None:
        return best[1], best[2]

    side1 = (cands1[0][0], cands1[0][1]) if cands1 else (None, None)
    side2 = (cands2[0][0], cands2[0][1]) if cands2 else (None, None)
    return side1, side2


def id_value(element_id):
    """ElementId -> number, across Revit 2024-2027 (.Value from 2025 on)."""
    try:
        return element_id.Value
    except AttributeError:
        return element_id.IntegerValue


def host_corners(element, link_instance):
    """All 8 corners of an element's model bounding box, in HOST coordinates.

    Transforming only Min/Max of a linked element's box is wrong as soon as the
    link is rotated -- the two points swap or cross over and the result is a
    box that misses the element. Transforming all 8 and re-taking min/max
    gives a correct (axis-aligned, slightly loose) host box."""
    try:
        bbox = element.get_BoundingBox(None)
    except Exception:
        bbox = None
    if bbox is None:
        return []

    lo, hi = bbox.Min, bbox.Max
    corners = [XYZ(x, y, z)
               for x in (lo.X, hi.X) for y in (lo.Y, hi.Y) for z in (lo.Z, hi.Z)]

    if bbox.Transform is not None:
        corners = [bbox.Transform.OfPoint(c) for c in corners]
    if link_instance is not None:
        link_transform = link_instance.GetTotalTransform()
        corners = [link_transform.OfPoint(c) for c in corners]
    return corners


def host_extent(resolved, padding_ft=0.0):
    """(low, high) host-coordinate box around a list of (element, link_or_None)
    pairs, grown by padding_ft on every side, or None if none have a box."""
    corners = []
    for element, link in resolved:
        if element is not None:
            corners.extend(host_corners(element, link))
    if not corners:
        return None
    low = XYZ(min(c.X for c in corners) - padding_ft,
              min(c.Y for c in corners) - padding_ft,
              min(c.Z for c in corners) - padding_ft)
    high = XYZ(max(c.X for c in corners) + padding_ft,
               max(c.Y for c in corners) + padding_ft,
               max(c.Z for c in corners) + padding_ft)
    return (low, high)


def element_reference(element, link_instance):
    """A selectable Reference to a host element, or to a linked element through
    the link instance that places it.

    Selection.SetElementIds only understands host ids -- handing it a linked
    element's id selects whatever host element happens to share that number,
    or nothing. Selection.SetReferences (Revit 2023+) with a link reference is
    the API equivalent of Tab-picking into a link, and is the only route that
    selects and highlights the linked element itself."""
    ref = Reference(element)
    if link_instance is not None:
        ref = ref.CreateLinkReference(link_instance)
    return ref


# ---------------------------------------------------------- sub-element -> main
# Navisworks reports the exact piece that clashed: one curtain panel, one
# mullion, one stair landing, one top rail. Selecting that piece is rarely
# useful -- the thing you open, move or edit is the curtain wall, the stair,
# the railing. These helpers climb from the reported piece to that element.
#
# Only the selection (and the Isolate targets) climb. The section box and the
# zoom stay fitted to the reported pieces themselves: fitting them to a whole
# curtain wall would crop to the facade and lose the clash.


def _bics(*names):
    """BuiltInCategory members by name, skipping any this Revit version lacks."""
    return tuple(getattr(BuiltInCategory, n) for n in names if hasattr(BuiltInCategory, n))


CURTAIN_PART_BICS = _bics("OST_CurtainWallPanels", "OST_CurtainWallMullions")
RAILING_PART_BICS = _bics(
    "OST_StairsRailingBaluster", "OST_RailingSupport", "OST_RailingTermination",
    "OST_RailingTopRail", "OST_RailingHandRail",
)
# Stringers / carriages. No API class of their own (there is no StairsSupport
# type) and no property pointing at their stair -- found from the stair side.
STAIR_SUPPORT_BICS = _bics("OST_StairsStringerCarriage", "OST_StairsSupports")
MAX_PARENT_DEPTH = 6   # a nested shared family inside a panel inside a wall is 2; 6 is plenty


def category_bic(element):
    try:
        return element.Category.BuiltInCategory if element.Category else None
    except Exception:
        return None


def railing_parts(owner):
    return owner.GetDependentElements(None)


def stair_supports(owner):
    return owner.GetStairsSupports()


def owner_listing(element, owner_class, list_parts=railing_parts):
    """The owner_class element whose list_parts(owner) includes this element.

    Balusters, railing supports, terminations and stair stringers have no API
    property pointing back at their owner. The owner does list them, though --
    so ask the few owners whose box overlaps this element, rather than every
    railing or stair in the model."""
    doc = element.Document
    bbox = element.get_BoundingBox(None)
    if bbox is None:
        return None
    nearby = (FilteredElementCollector(doc)
              .OfClass(owner_class)
              .WherePasses(BoundingBoxIntersectsFilter(Outline(bbox.Min, bbox.Max))))
    target = id_value(element.Id)
    for owner in nearby:
        try:
            parts = list_parts(owner)
        except Exception:
            continue
        if target in set(id_value(p) for p in parts):
            return owner
    return None


def parent_element(element):
    """One step up from a sub-element to what owns it, or None if it is
    already a main element."""
    doc = element.Document

    if isinstance(element, (StairsRun, StairsLanding)):
        return element.GetStairs()

    if isinstance(element, ContinuousRail):              # top rail, handrail
        return doc.GetElement(element.HostRailingId)

    if isinstance(element, Wall) and element.IsStackedWallMember:
        return doc.GetElement(element.StackedWallOwnerId)

    bic = category_bic(element)

    # Panels and mullions report their curtain wall / curtain system / sloped
    # glazing roof as Host. Deliberately category-gated: a door's Host is also
    # its wall, and a door must stay a door.
    if bic in CURTAIN_PART_BICS and isinstance(element, FamilyInstance):
        return element.Host

    if isinstance(element, FamilyInstance) and element.SuperComponent is not None:
        return element.SuperComponent                    # nested shared family

    if bic in STAIR_SUPPORT_BICS:
        return owner_listing(element, Stairs, stair_supports)

    if bic in RAILING_PART_BICS:
        return (owner_listing(element, ContinuousRail)
                or owner_listing(element, Railing))

    return None


def main_element(element):
    """Climbs to the top-level owner. Returns the element itself when it isn't
    a sub-element, so callers can always use the result."""
    current = element
    for _ in range(MAX_PARENT_DEPTH):
        try:
            parent = parent_element(current)
        except Exception as ex:
            logger.debug("Parent lookup failed for {0}: {1}".format(id_value(current.Id), ex))
            parent = None
        if parent is None or id_value(parent.Id) == id_value(current.Id):
            break
        current = parent
    return current


def main_targets(resolved):
    """(element, link) pairs to select and isolate: each clashing piece swapped
    for its main element, deduplicated -- a panel clashing with a mullion of the
    same curtain wall is one wall, selected once. Also returns how many were
    swapped."""
    targets = []
    swapped = 0
    for element, link in resolved:
        main = main_element(element)
        if id_value(main.Id) != id_value(element.Id):
            swapped += 1
        if not any(same_element(main, link, t_el, t_link) for t_el, t_link in targets):
            targets.append((main, link))
    return targets, swapped


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


def element_label_with_main(element, link_instance):
    """The label, plus the main element Focus/Isolate will actually select
    when the reported element is only a part of it."""
    label = element_label(element, link_instance)
    if element is None:
        return label
    main = main_element(element)
    if id_value(main.Id) == id_value(element.Id):
        return label
    return u"{0}\n    \u2192 selects: {1}  (ID {2})".format(
        label, element_label(main, None), id_value(main.Id))


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


# ---------------------------------------------------------------- coordinates

def to_meters(length_ft):
    return UnitUtils.ConvertFromInternalUnits(length_ft, UnitTypeId.Meters)


def raw_point(point_tuple):
    """The report's three numbers, unit-converted but not otherwise moved."""
    x, y, z = point_tuple
    return XYZ(
        UnitUtils.ConvertToInternalUnits(x, REPORT_LENGTH_UNIT),
        UnitUtils.ConvertToInternalUnits(y, REPORT_LENGTH_UNIT),
        UnitUtils.ConvertToInternalUnits(z, REPORT_LENGTH_UNIT),
    )


def apply_coord_mode(doc, point, mode):
    if mode == "internal":
        return point
    transform = doc.ActiveProjectLocation.GetTotalTransform()
    if mode == "location_transform":
        return transform.OfPoint(point)
    return transform.Inverse.OfPoint(point)


def clash_element_extent(doc, clash):
    """A rough host-internal bounding box around whichever of the two clashing
    elements resolve, or None.

    This is the yardstick the coordinate modes are measured against: whatever
    coordinate system the report used, the clash point has to sit on top of the
    elements the same row names. A rotated link gives a slightly loose box --
    irrelevant here, where the wrong answers are out by kilometres."""
    return host_extent(list(resolve_clash_pair(doc, clash)))


def distance_to_extent(point, extent):
    """Shortest distance from a point to a box (zero if inside), in feet."""
    low, high = extent
    dx = max(low.X - point.X, 0.0, point.X - high.X)
    dy = max(low.Y - point.Y, 0.0, point.Y - high.Y)
    dz = max(low.Z - point.Z, 0.0, point.Z - high.Z)
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def score_coord_modes(doc, clash):
    """[(distance_ft, mode, point), ...] sorted best first, or None if the
    clash's elements couldn't be resolved to measure against."""
    extent = clash_element_extent(doc, clash)
    if extent is None:
        return None

    base = raw_point(clash["clash_point"])
    scored = []
    for mode in COORD_MODES:
        try:
            candidate = apply_coord_mode(doc, base, mode)
        except Exception as ex:
            logger.debug("Coordinate mode {0} failed: {1}".format(mode, ex))
            continue
        scored.append((distance_to_extent(candidate, extent), mode, candidate))
    scored.sort()
    return scored


def detect_coord_mode(doc, clash):
    """Returns the winning mode name, or None after explaining why not."""
    scored = score_coord_modes(doc, clash)

    if scored is None:
        # No elements to measure against. Fall back to the weaker test: exactly
        # one candidate being inside Revit's working range is still decisive.
        base = raw_point(clash["clash_point"])
        in_range = []
        for mode in COORD_MODES:
            try:
                candidate = apply_coord_mode(doc, base, mode)
            except Exception:
                continue
            if candidate.GetLength() <= REVIT_MODEL_LIMIT_FT:
                in_range.append(mode)
        if len(in_range) == 1:
            return in_range[0]
        forms.alert(
            "Can't work out which coordinate system this report uses, because "
            "neither of this clash's elements could be found in the host model "
            "or any loaded link.\n\n"
            "Pick a clash whose elements do resolve, or set "
            "CLASH_POINT_COORD_SYSTEM at the top of the script to one of: "
            + ", ".join(COORD_MODES)
        )
        return None

    tolerance_ft = UnitUtils.ConvertToInternalUnits(COORD_DETECT_TOLERANCE_M, UnitTypeId.Meters)
    best_distance, best_mode, _ = scored[0]
    if best_distance > tolerance_ft:
        lines = ["    {0}: {1:,.0f} m away".format(mode, to_meters(dist))
                 for dist, mode, _pt in scored]
        forms.alert(
            "None of the coordinate conversions put this clash point anywhere near "
            "the elements the report says are clashing:\n\n" + "\n".join(lines) +
            "\n\nThe usual cause is REPORT_LENGTH_UNIT not matching the report "
            "(check the Tolerance cell in the report's summary table -- it carries "
            "the unit), or the elements having been remodelled since the clash test "
            "was run."
        )
        return None

    logger.debug("Clash point coordinate mode: {0} ({1:.2f} m from elements)".format(
        best_mode, to_meters(best_distance)))
    return best_mode


def resolve_clash_point(doc, clash):
    """Report coordinates -> Revit internal XYZ, or None after alerting.

    Navisworks writes clash points in whatever coordinate system the NWCs were
    exported with, which for a federated model is normally the SHARED (survey)
    one. Those numbers are nowhere near Revit's internal origin -- this project's
    report reads x:585799, y:2368832 -- so using them unconverted puts a section
    box a couple of thousand kilometres from the model."""
    if clash["clash_point"] is None:
        forms.alert("This clash has no clash-point coordinates in the report.")
        return None

    mode = CLASH_POINT_COORD_SYSTEM
    if mode == "auto":
        if _COORD_MODE[0] is None:
            _COORD_MODE[0] = detect_coord_mode(doc, clash)
            if _COORD_MODE[0] is None:
                return None
        mode = _COORD_MODE[0]

    point = apply_coord_mode(doc, raw_point(clash["clash_point"]), mode)
    if not point_is_reachable(point, mode):
        return None
    return point


def point_is_reachable(point, mode):
    """False (after alerting) if the converted point is so far from the internal
    origin that the coordinate or unit setting must be wrong."""
    if point.GetLength() <= REVIT_MODEL_LIMIT_FT:
        return True
    forms.alert(
        "The clash point converts to a location about {0:,.0f} m from this model's "
        "internal origin, which is outside Revit's working range.\n\n"
        "Coordinate mode '{1}' with coordinates read as {2}. Try a different "
        "CLASH_POINT_COORD_SYSTEM or REPORT_LENGTH_UNIT at the top of the "
        "script.".format(
            to_meters(point.GetLength()),
            mode,
            "meters" if REPORT_LENGTH_UNIT == UnitTypeId.Meters else "the configured unit",
        )
    )
    return False


# ---------------------------------------------------------------- actions
# None of these may be called from a WPF handler directly -- there is no API
# context there once the script has returned. They are only ever reached from
# inside ClashEventHandler.Execute(), via queue() in the UI section below.
# Each returns True only if it actually completed.

def select_clash_elements(uidoc, resolved):
    """Selects (and so highlights) both clashing elements, linked ones
    included. Returns True if the linked elements made it into the selection."""
    refs = List[Reference]()
    for element, link in resolved:
        refs.Add(element_reference(element, link))
    try:
        uidoc.Selection.SetReferences(refs)
        return True
    except Exception as ex:
        # Should not happen on 2024-2027, but a failed selection is no reason
        # to throw away the section box that already committed.
        logger.debug("SetReferences failed ({0}); selecting host elements only.".format(ex))
    host_ids = List[ElementId]([el.Id for el, link in resolved if link is None])
    uidoc.Selection.SetElementIds(host_ids)
    return False


def resolve_for_view(clash):
    """Shared front half of Focus and Isolate: the active doc, a model view,
    and the clash's resolved (element, link) pairs. None after alerting."""
    doc = require_doc()
    if doc is None:
        return None

    resolved = [(el, link) for el, link in resolve_clash_pair(doc, clash) if el is not None]
    if not resolved:
        forms.alert("Neither Item 1 nor Item 2 could be resolved in the host model or any loaded link.")
        return None

    view = doc.ActiveView
    # CanUseTemporaryVisibilityModes doubles as a "this is a model view" test:
    # sheets, schedules and legends all return False.
    if view is None or not view.CanUseTemporaryVisibilityModes():
        forms.alert("The active view can't show model elements this way. "
                    "Switch to a plan, section or 3D view.")
        return None
    return doc, view, resolved


def section_box_blocker(view, extent):
    """Why the section box can't be set in this view, or None if it can."""
    if extent is None:
        return "no section box (elements have no geometry extent)"
    if not isinstance(view, View3D):
        return "no section box (not a 3D view)"
    if view.IsLocked:
        return "no section box (3D view is locked)"
    return None


def isolate_ids_for(resolved):
    """Host elements isolate directly; a linked element can only be isolated
    through its whole link instance (deduplicated -- both items are often in
    the same link)."""
    ids = []
    seen = set()
    for element, link in resolved:
        target = link.Id if link is not None else element.Id
        key = id_value(target)
        if key not in seen:
            seen.add(key)
            ids.append(target)
    return ids


def apply_isolate(view, resolved):
    """Must run inside an open transaction. Clears any existing temporary
    hide/isolate first, so the previous clash's isolate doesn't intersect with
    this one and hide part of it."""
    if view.IsTemporaryHideIsolateActive():
        view.DisableTemporaryViewMode(TemporaryViewMode.TemporaryHideIsolate)
    # IsolateElementsTemporary wants a real .NET ICollection[ElementId] -- a plain
    # Python list doesn't satisfy that interface here, so wrap it explicitly.
    view.IsolateElementsTemporary(List[ElementId](isolate_ids_for(resolved)))


def do_focus(clash, isolate=False):
    """Section-box, select and zoom onto the two clashing elements.

    Focus (isolate=False) never isolates; instead it clears any temporary
    hide/isolate left on the view, so a previous Isolate can't keep this
    clash's elements hidden. Isolate (isolate=True) does the same thing plus a
    fresh temporary isolate, inside the same transaction.

    Returns a one-line summary, or None if nothing was done."""
    context = resolve_for_view(clash)
    if context is None:
        return None
    doc, view, resolved = context

    # The box and zoom fit the pieces that actually clash; selection and
    # isolate use their main elements (curtain wall, stair, railing).
    padding_ft = UnitUtils.ConvertToInternalUnits(FOCUS_BOX_PADDING_M, UnitTypeId.Meters)
    extent = host_extent(resolved, padding_ft)
    box_note = section_box_blocker(view, extent)
    targets, swapped = main_targets(resolved)

    clear_isolate = (not isolate) and view.IsTemporaryHideIsolateActive()

    if box_note is None or isolate or clear_isolate:
        t = Transaction(doc, "Clash Navigator - Isolate" if isolate else "Clash Navigator - Focus")
        t.Start()
        try:
            if isolate:
                apply_isolate(view, targets)
            elif clear_isolate:
                view.DisableTemporaryViewMode(TemporaryViewMode.TemporaryHideIsolate)
            if box_note is None:
                bbox = BoundingBoxXYZ()
                bbox.Min = extent[0]
                bbox.Max = extent[1]
                view.SetSectionBox(bbox)
                view.IsSectionBoxActive = True
            t.Commit()
        except Exception:
            t.RollBack()
            raise

    # Selection is UI state, not a model change, so it sits outside the
    # transaction. It survives the section box (and the isolate), which is
    # what keeps the two elements highlighted inside the cropped view.
    uidoc = get_uidoc()
    links_selected = select_clash_elements(uidoc, targets)
    uidoc.RefreshActiveView()
    if extent is not None:
        zoom_to_box(uidoc, view, extent[0], extent[1])

    linked_count = len([1 for _el, link in targets if link is not None])
    parts = []
    if isolate:
        parts.append("isolated")
    elif clear_isolate:
        parts.append("isolation cleared")
    parts.append(box_note or "section box set")
    if linked_count and not links_selected:
        parts.append("host element(s) selected -- linked selection failed")
    else:
        parts.append("{0} element(s) selected{1}".format(
            len(targets), " ({0} linked)".format(linked_count) if linked_count else ""))
    if swapped:
        parts.append("{0} sub-element(s) swapped for their main element".format(swapped))
    return (u"Isolate: " if isolate else u"Focus: ") + u", ".join(parts) + u"."


def do_clash_box(clash, box_size_m):
    doc = require_doc()
    if doc is None:
        return False

    view = doc.ActiveView
    if not isinstance(view, View3D):
        forms.alert("Switch to a 3D view first -- Clash Box sets that view's section box.")
        return False
    if view.IsLocked:
        forms.alert("The active 3D view is locked; unlock it to set a section box.")
        return False

    center = resolve_clash_point(doc, clash)
    if center is None:
        return False

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

    uidoc = get_uidoc()
    uidoc.RefreshActiveView()
    zoom_to_box(uidoc, view, bbox.Min, bbox.Max)
    return True


def zoom_to_box(uidoc, view, low, high):
    """Zoom the view onto a host-coordinate box (the section box that was
    just set, or the padded extent of the clashing elements).

    ZoomAndCenterRectangle needs the open UIView for this view, which only
    exists if the view is actually on screen -- GetOpenUIViews() is how you get
    from a View to its UIView, and there is no other route. It also has to
    happen after the transaction commits, or it frames the view as it was
    before the section box existed.

    ZoomToFit is the fallback: with the section box active the visible geometry
    is already clipped to the box, so fitting the view amounts to the same
    thing, and it still works when the box happens to be empty."""
    target = None
    for uiview in uidoc.GetOpenUIViews():
        if uiview.ViewId == view.Id:
            target = uiview
            break
    if target is None:
        return

    try:
        target.ZoomAndCenterRectangle(low, high)
    except Exception as ex:
        logger.debug("ZoomAndCenterRectangle failed ({0}); falling back to ZoomToFit.".format(ex))
        try:
            target.ZoomToFit()
        except Exception:
            logger.debug("ZoomToFit failed as well; leaving the camera alone.")


# ---------------------------------------------------------------- WPF UI

XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Clash Navigator" Height="660" Width="900"
        WindowStartupLocation="CenterScreen"
        Background="#161616">
    <Window.Resources>
        <Style x:Key="RoundButton" TargetType="Button">
            <Setter Property="Background" Value="#393939"/>
            <Setter Property="Foreground" Value="#F4F4F4"/>
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
            <Setter Property="Background" Value="#F1C21B"/>
            <Setter Property="Foreground" Value="#161616"/>
        </Style>
        <Style x:Key="TabCloseButton" TargetType="Button">
            <Setter Property="Foreground" Value="#A8A8A8"/>
            <Setter Property="Width" Value="18"/>
            <Setter Property="Height" Value="18"/>
            <Setter Property="Margin" Value="8,0,0,0"/>
            <Setter Property="Cursor" Value="Hand"/>
            <Setter Property="ToolTip" Value="Close this report"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="Button">
                        <Border x:Name="Bg" Background="Transparent" CornerRadius="9">
                            <TextBlock Text="&#x2715;" FontSize="10" Foreground="{TemplateBinding Foreground}"
                                       HorizontalAlignment="Center" VerticalAlignment="Center"/>
                        </Border>
                        <ControlTemplate.Triggers>
                            <Trigger Property="IsMouseOver" Value="True">
                                <Setter TargetName="Bg" Property="Background" Value="#DA1E28"/>
                                <Setter Property="Foreground" Value="#FFFFFF"/>
                            </Trigger>
                        </ControlTemplate.Triggers>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>
    </Window.Resources>
    <Grid Margin="12">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <StackPanel Grid.Row="0" Margin="0,0,0,10">
            <DockPanel Margin="0,0,0,8">
                <Button x:Name="LoadButton" Content="Load HTML Reports..." DockPanel.Dock="Left"
                        Width="170" Style="{StaticResource AccentButton}" Margin="0,0,10,0"/>
                <Button x:Name="ExportButton" Content="Export Results..." DockPanel.Dock="Right"
                        Width="140" Style="{StaticResource RoundButton}" Margin="10,0,0,0"/>
                <TextBlock x:Name="ReportLabel" Text="No report loaded" Foreground="#A8A8A8"
                           VerticalAlignment="Center" TextTrimming="CharacterEllipsis"/>
            </DockPanel>
            <Border BorderBrush="#393939" BorderThickness="0,0,0,1">
                <WrapPanel x:Name="ReportTabs"/>
            </Border>
        </StackPanel>

        <Grid Grid.Row="1">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="260"/>
            </Grid.ColumnDefinitions>

            <DockPanel Grid.Column="0" Margin="0,0,10,0">
                <Border DockPanel.Dock="Top" Margin="0,0,0,8" Padding="12,7"
                        Background="#262626" BorderBrush="#525252" BorderThickness="1">
                    <StackPanel Orientation="Horizontal">
                        <TextBlock Text="Total" Foreground="#A8A8A8" VerticalAlignment="Center"/>
                        <TextBlock x:Name="SumTotal" Text="-" Foreground="#F4F4F4" FontWeight="Bold"
                                   FontSize="14" Margin="8,0,28,0" VerticalAlignment="Center"/>
                        <TextBlock Text="Solved" Foreground="#A8A8A8" VerticalAlignment="Center"/>
                        <TextBlock x:Name="SumSolved" Text="-" Foreground="#42BE65" FontWeight="Bold"
                                   FontSize="14" Margin="8,0,28,0" VerticalAlignment="Center"/>
                        <TextBlock Text="Approved" Foreground="#A8A8A8" VerticalAlignment="Center"/>
                        <TextBlock x:Name="SumApproved" Text="-" Foreground="#78A9FF" FontWeight="Bold"
                                   FontSize="14" Margin="8,0,28,0" VerticalAlignment="Center"/>
                        <TextBlock Text="Remaining" Foreground="#A8A8A8" VerticalAlignment="Center"/>
                        <TextBlock x:Name="SumRemaining" Text="-" Foreground="#FF8389" FontWeight="Bold"
                                   FontSize="14" Margin="8,0,0,0" VerticalAlignment="Center"/>
                    </StackPanel>
                </Border>
                <Border DockPanel.Dock="Top" Background="#393939" CornerRadius="4,4,0,0" Padding="4,5">
                    <DockPanel>
                        <TextBlock Text="Solved" Width="52" TextAlignment="Center"
                                   Foreground="#A8A8A8" FontWeight="SemiBold"/>
                        <TextBlock Text="Approved" Width="66" TextAlignment="Center"
                                   Foreground="#A8A8A8" FontWeight="SemiBold"/>
                        <TextBlock Text="Clash" Margin="6,0,0,0"
                                   Foreground="#A8A8A8" FontWeight="SemiBold"/>
                    </DockPanel>
                </Border>
                <ListBox x:Name="ClashList" Background="#262626" Foreground="#F4F4F4"
                         BorderThickness="0" HorizontalContentAlignment="Stretch"/>
            </DockPanel>

            <StackPanel Grid.Column="1">
                <Image x:Name="ClashImage" Height="160" Stretch="Uniform" Margin="0,0,0,10"/>
                <TextBlock Text="Clash Details" Foreground="#F4F4F4" FontWeight="Bold" Margin="0,0,0,8"/>
                <TextBlock x:Name="Item1Label" Foreground="#A8A8A8" TextWrapping="Wrap" Margin="0,0,0,6"/>
                <TextBlock x:Name="Item2Label" Foreground="#A8A8A8" TextWrapping="Wrap" Margin="0,0,0,6"/>
                <TextBlock x:Name="PointLabel" Foreground="#A8A8A8" TextWrapping="Wrap" Margin="0,0,0,16"/>

                <Grid>
                    <Grid.ColumnDefinitions>
                        <ColumnDefinition Width="*"/>
                        <ColumnDefinition Width="8"/>
                        <ColumnDefinition Width="*"/>
                    </Grid.ColumnDefinitions>
                    <Button x:Name="FocusButton" Grid.Column="0" Content="Focus"
                            Style="{StaticResource RoundButton}"/>
                    <Button x:Name="IsolateButton" Grid.Column="2" Content="Isolate"
                            Style="{StaticResource RoundButton}"/>
                </Grid>

                <TextBlock Text="Clash Box Size (m)" Foreground="#A8A8A8" Margin="0,8,0,2"/>
                <TextBox x:Name="BoxSizeBox" Background="#262626" Foreground="#F4F4F4"
                         BorderBrush="#525252" Padding="6" Margin="0,0,0,8"/>
                <Button x:Name="ClashBoxButton" Content="Create Clash Box" Style="{StaticResource RoundButton}"/>
            </StackPanel>
        </Grid>

        <TextBlock x:Name="StatusLabel" Grid.Row="2" Margin="0,10,0,0"
                   Foreground="#A8A8A8" Text="Ready."/>
    </Grid>
</Window>
"""


# ---------------------------------------------------------- solved / approved
# Which clashes the user has ticked as solved or approved, kept per report.
# The two are independent ticks. The file sits
# next to the report ("<report>.html.solved.json") so it travels with it and a
# coordinator opening the same report from the shared folder sees the same
# ticks. If that folder is read-only, it falls back to %APPDATA%, keyed by the
# report's full path.
#
# A clash is identified by test + clash name + both element ids rather than by
# its position in the list, so a re-exported report (same file name, clashes
# added, removed or reordered) keeps the ticks of every clash still in it.
# Keys of clashes that are no longer in the report are kept, not pruned -- a
# clash that comes back in a later export comes back still ticked.
#
# The file keeps its original ".solved.json" name so reports ticked before the
# Approved column existed still load; a file without "approved" just means
# nothing is approved yet.

SOLVED_SUFFIX = ".solved.json"

# (flag, header, column width, checkbox tooltip) -- the header widths in the
# XAML match these
STATE_COLUMNS = (
    ("solved", "Solved", 52, "Tick when this clash is solved."),
    ("approved", "Approved", 66, "Tick when this clash is approved (accepted as is)."),
)
STATE_FLAGS = tuple(c[0] for c in STATE_COLUMNS)


def clash_key(entry):
    return u"{0}||{1}||{2}||{3}".format(
        entry.get("test"), entry.get("name"), entry.get("item1_id"), entry.get("item2_id"))


def solved_state_paths(report_path):
    """[sidecar, appdata] -- read in that order, written to the first that works."""
    paths = [report_path + SOLVED_SUFFIX]
    appdata = os.environ.get("APPDATA")
    if appdata:
        digest = hashlib.md5(os.path.abspath(report_path).lower().encode("utf-8")).hexdigest()
        name = u"{0}_{1}{2}".format(os.path.basename(report_path), digest[:10], SOLVED_SUFFIX)
        paths.append(os.path.join(appdata, "pyRevit", "ClashNavigator", name))
    return paths


def load_clash_state(report_path):
    """Returns ({flag: set_of_keys}, path_it_came_from_or_None)."""
    for path in solved_state_paths(report_path):
        if not os.path.isfile(path):
            continue
        try:
            f = open(path, "rb")
            try:
                data = json.loads(f.read().decode("utf-8"))
            finally:
                f.close()
            return dict((flag, set(data.get(flag, []))) for flag in STATE_FLAGS), path
        except Exception as ex:
            logger.warning("Could not read clash state from {0}: {1}".format(path, ex))
    return dict((flag, set()) for flag in STATE_FLAGS), None


def save_clash_state(report_path, state):
    """Writes every flag's key set to the first location that accepts it.
    Returns that path, or None if neither did."""
    data = {"report": os.path.basename(report_path)}
    for flag in STATE_FLAGS:
        data[flag] = sorted(state[flag])
    payload = json.dumps(data, indent=2, sort_keys=True)
    for path in solved_state_paths(report_path):
        try:
            folder = os.path.dirname(path)
            if not os.path.isdir(folder):
                os.makedirs(folder)
            f = open(path, "wb")
            try:
                f.write(payload.encode("utf-8"))
            finally:
                f.close()
            return path
        except Exception as ex:
            logger.debug("Could not write clash state to {0}: {1}".format(path, ex))
    return None


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


# ------------------------------------------------------------ results export
# A self-contained HTML of the solved / approved state of one or more reports.
# Pure Python -- no Revit API -- so it runs straight from the button handler.
#
# Clash images are linked, not embedded: a few hundred Navisworks snapshots
# embedded as base64 would turn the export into a 20+ MB file. The links are
# absolute file:/// URIs, so they work as long as the report's image folder
# stays where it is.

def html_escape(value):
    if value is None:
        return u""
    text = value if isinstance(value, basestring) else unicode(value)
    return (text.replace(u"&", u"&amp;").replace(u"<", u"&lt;")
                .replace(u">", u"&gt;").replace(u'"', u"&quot;"))


def result_of(entry):
    """(css class, label) for an entry's ticks."""
    if entry["solved"] and entry["approved"]:
        return "both", u"Solved & Approved"
    if entry["solved"]:
        return "solved", u"Solved"
    if entry["approved"]:
        return "approved", u"Approved"
    return "open", u"Open"


def tally(entries):
    counts = {"total": len(entries), "solved": 0, "approved": 0, "open": 0}
    for e in entries:
        if e["solved"]:
            counts["solved"] += 1
        if e["approved"]:
            counts["approved"] += 1
        if not e["solved"] and not e["approved"]:
            counts["open"] += 1
    return counts


def percent(part, whole):
    return u"{0:.0f}%".format(100.0 * part / whole) if whole else u"-"


def file_uri(path):
    try:
        return Uri(path).AbsoluteUri
    except Exception:
        return None


EXPORT_CSS = u"""
* { box-sizing: border-box; }
body { font-family: "Segoe UI", Arial, sans-serif; margin: 0; padding: 28px 36px;
       color: #161616; background: #f4f4f4; font-size: 13px; }
h1 { font-size: 24px; margin: 0 0 4px 0; }
h2 { font-size: 18px; margin: 0; display: inline; }
.meta { color: #525252; margin-bottom: 20px; }
.cards { display: flex; flex-wrap: wrap; gap: 10px; margin: 12px 0 18px 0; }
.card { background: #fff; border-left: 4px solid #8d8d8d; padding: 10px 16px; min-width: 120px; }
.card b { display: block; font-size: 22px; }
.card.solved { border-color: #24a148; } .card.approved { border-color: #0f62fe; }
.card.open { border-color: #da1e28; }
.controls { background: #fff; padding: 10px 14px; margin-bottom: 18px; display: flex;
            gap: 8px; align-items: center; flex-wrap: wrap; position: sticky; top: 0; z-index: 2;
            box-shadow: 0 1px 3px rgba(0,0,0,.15); }
.controls button { border: 1px solid #8d8d8d; background: #fff; padding: 5px 12px; cursor: pointer; }
.controls button.on { background: #161616; color: #fff; border-color: #161616; }
.controls input { padding: 5px 8px; border: 1px solid #8d8d8d; min-width: 260px; }
details.report { background: #fff; margin-bottom: 22px; padding: 14px 18px; }
details.report > summary { cursor: pointer; list-style: none; }
.path { color: #6f6f6f; font-size: 12px; margin-top: 2px; word-break: break-all; }
table { border-collapse: collapse; width: 100%; margin-top: 10px; }
th, td { border-bottom: 1px solid #e0e0e0; padding: 6px 8px; text-align: left; vertical-align: middle; }
th { background: #e0e0e0; font-weight: 600; }
table.tests { width: auto; min-width: 520px; }
td.num, th.num { text-align: right; }
.pill { display: inline-block; padding: 2px 9px; border-radius: 10px; font-size: 12px; white-space: nowrap; }
.pill.open { background: #ffd7d9; color: #750e13; }
.pill.solved { background: #defbe6; color: #0e6027; }
.pill.approved { background: #d0e2ff; color: #002d9c; }
.pill.both { background: linear-gradient(90deg, #defbe6 50%, #d0e2ff 50%); color: #161616; }
img.thumb { height: 54px; border: 1px solid #c6c6c6; }
.footer { color: #8d8d8d; margin-top: 24px; font-size: 11px; }
@media print {
  body { background: #fff; padding: 0; }
  .controls { display: none; }
  details.report { padding: 0; page-break-after: always; }
  tr { page-break-inside: avoid; }
  img.thumb { height: 40px; }
}
"""

EXPORT_JS = u"""
(function () {
  var current = 'all';
  var buttons = document.querySelectorAll('.controls button');
  var search = document.getElementById('search');
  function apply() {
    var q = search.value.toLowerCase();
    var rows = document.querySelectorAll('tr.clash');
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i];
      var okStatus = current === 'all' || r.getAttribute('data-status').indexOf(current) >= 0;
      var okText = !q || r.getAttribute('data-text').indexOf(q) >= 0;
      r.style.display = (okStatus && okText) ? '' : 'none';
    }
  }
  for (var i = 0; i < buttons.length; i++) {
    buttons[i].addEventListener('click', function () {
      for (var j = 0; j < buttons.length; j++) { buttons[j].className = ''; }
      this.className = 'on';
      current = this.getAttribute('data-filter');
      apply();
    });
  }
  search.addEventListener('input', apply);
})();
"""


def cards_html(counts):
    out = [u'<div class="cards">']
    for key, label in (("total", u"Clashes"), ("open", u"Open"),
                       ("solved", u"Solved"), ("approved", u"Approved")):
        extra = u"" if key == "total" else u" ({0})".format(percent(counts[key], counts["total"]))
        out.append(u'<div class="card {0}"><b>{1}</b>{2}{3}</div>'.format(
            key, counts[key], label, extra))
    out.append(u"</div>")
    return u"".join(out)


def report_section_html(report):
    entries = report["items"]
    out = [u'<details class="report" open><summary><h2>{0}</h2>'.format(html_escape(report["name"])),
           u'<div class="path">{0}</div></summary>'.format(html_escape(report["path"])),
           cards_html(tally(entries))]

    # per-test breakdown, in report order
    out.append(u'<table class="tests"><tr><th>Test</th><th class="num">Clashes</th>'
               u'<th class="num">Open</th><th class="num">Solved</th><th class="num">Approved</th></tr>')
    order = []
    by_test = {}
    for e in entries:
        if e["test"] not in by_test:
            by_test[e["test"]] = []
            order.append(e["test"])
        by_test[e["test"]].append(e)
    for test in order:
        c = tally(by_test[test])
        out.append(u'<tr><td>{0}</td><td class="num">{1}</td><td class="num">{2}</td>'
                   u'<td class="num">{3}</td><td class="num">{4}</td></tr>'.format(
                       html_escape(test), c["total"], c["open"], c["solved"], c["approved"]))
    out.append(u"</table>")

    out.append(u'<table class="clashes"><tr><th class="num">#</th><th>Test</th><th>Clash</th>'
               u'<th>Result</th><th>Navisworks status</th><th>Distance</th><th>Grid</th>'
               u'<th>Item 1 ID</th><th>Item 2 ID</th><th>Clash point</th><th>Image</th></tr>')
    for index, e in enumerate(entries, 1):
        css, label = result_of(e)
        point = e.get("clash_point")
        point_text = u"{0:.3f}, {1:.3f}, {2:.3f}".format(*point) if point else u""
        image = u""
        image_path = e.get("image_abs_path")
        if image_path and os.path.isfile(image_path):
            uri = file_uri(image_path)
            if uri:
                image = u'<a href="{0}" target="_blank"><img class="thumb" loading="lazy" src="{0}"></a>'.format(
                    html_escape(uri))
        search_text = u" ".join(unicode(v) for v in (
            e["test"], e.get("name"), e.get("item1_id"), e.get("item2_id"),
            e.get("grid_location"), label) if v is not None).lower()
        out.append(
            u'<tr class="clash" data-status="{0}" data-text="{1}">'
            u'<td class="num">{2}</td><td>{3}</td><td>{4}</td>'
            u'<td><span class="pill {0}">{5}</span></td><td>{6}</td><td>{7}</td><td>{8}</td>'
            u'<td>{9}</td><td>{10}</td><td>{11}</td><td>{12}</td></tr>'.format(
                # "both" must match the Solved and the Approved filter
                u"both solved approved" if css == "both" else css,
                html_escape(search_text), index, html_escape(e["test"]), html_escape(e.get("name")),
                label, html_escape(e.get("status")), html_escape(e.get("distance")),
                html_escape(e.get("grid_location")), html_escape(e.get("item1_id")),
                html_escape(e.get("item2_id")), point_text, image))
    out.append(u"</table></details>")
    return u"".join(out)


def build_results_html(reports):
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    all_entries = []
    for report in reports:
        all_entries.extend(report["items"])

    out = [u'<!DOCTYPE html><html><head><meta charset="utf-8">',
           u'<title>Clash Results {0}</title><style>{1}</style></head><body>'.format(stamp, EXPORT_CSS),
           u'<h1>Clash Results</h1>',
           u'<div class="meta">{0} report(s) &middot; exported {1} &middot; Clash Navigator</div>'.format(
               len(reports), stamp)]
    if len(reports) > 1:
        out.append(cards_html(tally(all_entries)))
    out.append(u'<div class="controls"><b>Show:</b>'
               u'<button class="on" data-filter="all">All</button>'
               u'<button data-filter="open">Open</button>'
               u'<button data-filter="solved">Solved</button>'
               u'<button data-filter="approved">Approved</button>'
               u'<input id="search" type="text" placeholder="Search test, clash, element id, grid...">'
               u'</div>')
    for report in reports:
        out.append(report_section_html(report))
    out.append(u'<div class="footer">Results reflect the Solved / Approved ticks at export time. '
               u'Filter, then print (Ctrl+P) to print only what is shown.</div>')
    out.append(u"<script>{0}</script></body></html>".format(EXPORT_JS))
    return u"".join(out)


def write_text_utf8(path, text):
    f = open(path, "wb")
    try:
        f.write(text.encode("utf-8"))
    finally:
        f.close()


def run():
    # Pressing the button while the window is already open should bring it
    # forward, not open a second one against the same model.
    session = get_session()
    if session:
        existing = session.get("window")
        if existing is not None and existing.IsVisible:
            existing.Activate()
            return

    window = XamlReader.Parse(XAML)
    event_handler = ClashEventHandler()
    external_event = ExternalEvent.Create(event_handler)

    def queue(action):
        """Hand a piece of Revit work to Revit. It runs as soon as Revit is idle,
        which may be immediately or may be after the user finishes whatever
        command they are in the middle of."""
        event_handler.enqueue(action)
        external_event.Raise()

    # Parent the window to Revit's main window so it floats above Revit instead of
    # disappearing behind it, and so pyRevit's file dialog opens over it.
    try:
        helper = WindowInteropHelper(window)
        helper.Owner = Process.GetCurrentProcess().MainWindowHandle
    except Exception:
        logger.debug("Could not set Revit as the owner window.")

    load_button = window.FindName("LoadButton")
    export_button = window.FindName("ExportButton")
    report_tabs = window.FindName("ReportTabs")
    report_label = window.FindName("ReportLabel")
    clash_list = window.FindName("ClashList")
    sum_total = window.FindName("SumTotal")
    sum_solved = window.FindName("SumSolved")
    sum_approved = window.FindName("SumApproved")
    sum_remaining = window.FindName("SumRemaining")
    clash_image = window.FindName("ClashImage")
    item1_label = window.FindName("Item1Label")
    item2_label = window.FindName("Item2Label")
    point_label = window.FindName("PointLabel")
    focus_button = window.FindName("FocusButton")
    isolate_button = window.FindName("IsolateButton")
    box_size_box = window.FindName("BoxSizeBox")
    clash_box_button = window.FindName("ClashBoxButton")
    status_label = window.FindName("StatusLabel")

    box_size_box.Text = str(DEFAULT_BOX_SIZE_M)
    for button in (focus_button, isolate_button):
        button.IsEnabled = False
        button.ToolTip = "Select a clash first."

    # mutable containers stand in for closures over primitives (IronPython 2.7 has no nonlocal)
    #
    # Every open report is one dict, shown as one tab:
    #   path, name, tests, items (all clashes), state ({flag: set of clash keys}),
    #   remembered (last clash selected in it), tab / tab_text (its tab chip).
    # Switching tabs only swaps which report the shared list, summary and
    # detail panel are showing; each report keeps its own selection.
    reports = [[]]
    active = [None]
    selected = [None]
    busy = [False]

    brushes = BrushConverter()
    TEXT_BRUSH = brushes.ConvertFromString("#F4F4F4")
    MUTED_BRUSH = brushes.ConvertFromString("#A8A8A8")
    # One colour language everywhere: solved green, approved blue, remaining red.
    # Row text uses softer shades of the same colours so a long list stays readable.
    SOLVED_BRUSH = brushes.ConvertFromString("#6FBF85")
    APPROVED_BRUSH = brushes.ConvertFromString("#82A8E6")
    TAB_ACTIVE_BG = brushes.ConvertFromString("#393939")
    TAB_IDLE_BG = brushes.ConvertFromString("#262626")
    TAB_EMPTY_LINE = brushes.ConvertFromString("#525252")
    colors = ColorConverter()
    LINE_SOLVED = colors.ConvertFromString("#42BE65")
    LINE_APPROVED = colors.ConvertFromString("#4589FF")
    LINE_REMAINING = colors.ConvertFromString("#FA4D56")

    def set_status(text):
        status_label.Text = text

    def pump():
        """WPF's equivalent of DoEvents: queue an empty delegate at Background
        priority and wait for it, which forces everything of higher priority
        (layout, render, input) to run first. Parsing an 85 MB report takes long
        enough that without this the window looks hung and users kill Revit."""
        window.Dispatcher.Invoke(DispatcherPriority.Background, Action(lambda: None))

    FOCUS_TIP = ("Clear any temporary isolation, then section-box, zoom to and "
                 "select both clashing elements -- or their main element when one is "
                 "only a part (curtain panel -> curtain wall, landing -> stair).")
    ISOLATE_TIP = ("Same as Focus, plus temporarily isolate both elements. "
                   "A linked element can only be isolated through its whole link.")

    def set_focus_enabled(enabled, reason=None):
        """Focus and Isolate share one enabled state. Greyed out, both need to
        say why, or they just look broken; enabled, each explains itself."""
        focus_button.IsEnabled = enabled
        isolate_button.IsEnabled = enabled
        focus_button.ToolTip = FOCUS_TIP if enabled else reason
        isolate_button.ToolTip = ISOLATE_TIP if enabled else reason

    def clear_details(reason="Select a clash first."):
        selected[0] = None
        item1_label.Text = ""
        item2_label.Text = ""
        point_label.Text = ""
        clash_image.Source = None
        set_focus_enabled(False, reason)

    # ------------------------------------------------------------ ticks
    def state_summary(report):
        c = tally(report["items"])
        return u"{0}: {1} solved, {2} approved, {3} open, of {4} clashes.".format(
            report["name"], c["solved"], c["approved"], c["open"], c["total"])

    def style_row(entry):
        """Ticked clashes stay in the list: solved ones green, approved ones
        (not solved) blue."""
        if entry["solved"]:
            entry["row_text"].Foreground = SOLVED_BRUSH
        elif entry["approved"]:
            entry["row_text"].Foreground = APPROVED_BRUSH
        else:
            entry["row_text"].Foreground = TEXT_BRUSH

    def make_row_handler(report, entry, flag):
        # one handler per row and column, bound to its report, entry and flag --
        # a closure over the loop variables would leave every checkbox pointing
        # at the last clash
        def on_state_click(sender, args):
            entry[flag] = bool(sender.IsChecked)
            key = clash_key(entry)
            if entry[flag]:
                report["state"][flag].add(key)
            else:
                report["state"][flag].discard(key)
            style_row(entry)

            update_summary(report)
            update_tab_progress(report)
            if save_clash_state(report["path"], report["state"]) is None:
                set_status(u"Couldn't save the solved/approved state -- neither the report "
                           u"folder nor %APPDATA% is writable.")
            else:
                set_status(state_summary(report))
        return on_state_click

    def build_row(report, entry):
        """Built once per clash and reused: the tabs only re-add the same rows,
        so a checkbox never loses its state to a tab switch. DockPanel rather than a Grid, so no GridLength is needed
        from Python."""
        row = DockPanel()
        for flag, _header, width, tip in STATE_COLUMNS:
            check = CheckBox()
            check.IsChecked = entry[flag]
            check.HorizontalAlignment = HorizontalAlignment.Center
            check.VerticalAlignment = VerticalAlignment.Center
            check.ToolTip = tip
            check.Click += RoutedEventHandler(safe_handler(make_row_handler(report, entry, flag)))

            check_cell = Border()
            check_cell.Width = width
            check_cell.Child = check
            DockPanel.SetDock(check_cell, Dock.Left)
            row.Children.Add(check_cell)

        text = TextBlock()
        text.Text = entry["label"]
        text.Margin = Thickness(6, 2, 0, 2)
        text.VerticalAlignment = VerticalAlignment.Center
        text.TextTrimming = TextTrimming.CharacterEllipsis
        text.ToolTip = entry["label"]

        row.Children.Add(text)

        entry["row"] = row
        entry["row_text"] = text
        style_row(entry)

    # ------------------------------------------------------------ list
    def refresh_list():
        clash_list.Items.Clear()
        report = active[0]
        if report is None:
            return
        for entry in report["items"]:
            clash_list.Items.Add(entry["row"])

    def update_summary(report):
        """The bar above the list. Remaining = neither solved nor approved,
        the same definition the export uses for Open."""
        if report is None:
            for label in (sum_total, sum_solved, sum_approved, sum_remaining):
                label.Text = u"-"
            return
        c = tally(report["items"])
        sum_total.Text = unicode(c["total"])
        sum_solved.Text = u"{0}  ({1})".format(c["solved"], percent(c["solved"], c["total"]))
        sum_approved.Text = u"{0}  ({1})".format(c["approved"], percent(c["approved"], c["total"]))
        sum_remaining.Text = u"{0}  ({1})".format(c["open"], percent(c["open"], c["total"]))

    # ------------------------------------------------------------ tabs
    def progress_brush(counts):
        """The line under a tab as a progress bar: solved | approved | remaining,
        left to right, each as wide as its share of the report.

        A horizontal gradient with two stops at every boundary offset gives
        hard edges instead of a blend -- a segmented bar without building
        Grid columns (GridLength isn't constructible from IronPython). A clash
        both solved and approved counts once, as solved, so the segments add
        up to the whole tab."""
        total = counts["total"]
        if not total:
            return TAB_EMPTY_LINE
        solved_end = float(counts["solved"]) / total
        approved_end = solved_end + float(total - counts["solved"] - counts["open"]) / total

        brush = LinearGradientBrush()
        brush.StartPoint = Point(0, 0)
        brush.EndPoint = Point(1, 0)
        for color, start, end in ((LINE_SOLVED, 0.0, solved_end),
                                  (LINE_APPROVED, solved_end, approved_end),
                                  (LINE_REMAINING, approved_end, 1.0)):
            if end > start:
                brush.GradientStops.Add(GradientStop(color, start))
                brush.GradientStops.Add(GradientStop(color, end))
        return brush

    def update_tab_progress(report):
        c = tally(report["items"])
        report["tab"].BorderBrush = progress_brush(c)
        report["tab"].ToolTip = u"{0}\n{1} solved, {2} approved, {3} remaining, of {4}".format(
            report["path"], c["solved"], c["approved"], c["open"], c["total"])

    def style_tabs():
        """Active tab: lighter background and bright text. The progress line
        shows on every tab, so the state of all reports is visible at once."""
        for report in reports[0]:
            is_active = report is active[0]
            report["tab"].Background = TAB_ACTIVE_BG if is_active else TAB_IDLE_BG
            report["tab_text"].Foreground = TEXT_BRUSH if is_active else MUTED_BRUSH

    def update_tab_text(report):
        report["tab_text"].Text = u"{0}  ({1})".format(report["name"], len(report["items"]))
        update_tab_progress(report)

    def activate(report):
        """Show a report in the shared list / summary / details. None empties them."""
        active[0] = report
        clear_details()
        update_summary(report)
        if report is None:
            report_label.Text = "No report loaded"
            refresh_list()
            style_tabs()
            set_status("Ready.")
            return

        refresh_list()
        report_label.Text = report["path"]
        style_tabs()

        # bring back the clash that was selected when this tab was left
        remembered = report.get("remembered")
        if remembered is not None and remembered in report["items"]:
            clash_list.SelectedItem = remembered["row"]
            clash_list.ScrollIntoView(remembered["row"])
        set_status(state_summary(report))

    def close_report(report):
        index = reports[0].index(report)
        reports[0].remove(report)
        report_tabs.Children.Remove(report["tab"])
        if report is active[0]:
            # the tab to the right takes its place, or the one before it
            remaining = reports[0]
            activate(remaining[min(index, len(remaining) - 1)] if remaining else None)
        else:
            style_tabs()
        if active[0] is not None:
            set_status(u"Closed {0}. {1}".format(report["name"], state_summary(active[0])))
        else:
            set_status(u"Closed {0}.".format(report["name"]))

    def build_tab(report):
        text = TextBlock()
        text.VerticalAlignment = VerticalAlignment.Center
        text.MaxWidth = 240
        text.TextTrimming = TextTrimming.CharacterEllipsis

        close = Button()
        close.Style = window.FindResource("TabCloseButton")
        close.Click += RoutedEventHandler(safe_handler(lambda s, a: close_report(report)))

        content = DockPanel()
        DockPanel.SetDock(close, Dock.Right)
        content.Children.Add(close)
        content.Children.Add(text)

        tab = Border()
        tab.Child = content
        tab.Padding = Thickness(12, 6, 6, 6)
        tab.Margin = Thickness(0, 0, 4, 0)
        tab.CornerRadius = CornerRadius(4, 4, 0, 0)
        tab.BorderThickness = Thickness(0, 0, 0, 3)
        tab.Cursor = Cursors.Hand
        # The close button handles its own mouse-up, so clicking it never
        # also activates the tab it is closing.
        tab.MouseLeftButtonUp += MouseButtonEventHandler(
            safe_handler(lambda s, a: activate(report) if report is not active[0] else None))

        report["tab"] = tab
        report["tab_text"] = text
        update_tab_text(report)
        report_tabs.Children.Add(tab)

    # ------------------------------------------------------------ loading
    def find_open_report(path):
        wanted = os.path.normcase(os.path.abspath(path))
        for report in reports[0]:
            if os.path.normcase(os.path.abspath(report["path"])) == wanted:
                return report
        return None

    def load_one(html_path, position, total):
        """Parses one report into a report dict (rows built, ticks applied).
        Returns None if it holds no clashes."""
        prefix = u"[{0}/{1}] ".format(position, total) if total > 1 else u""
        name = os.path.basename(html_path)
        set_status(u"{0}Reading {1}...".format(prefix, name))
        pump()
        html_text = read_report_text(html_path)

        def report_progress(test_name, count):
            set_status(u"{0}Parsing {1}: {2} -- {3} clashes so far...".format(
                prefix, name, test_name, count))
            pump()

        tests = parse_report(html_text, progress=report_progress)
        items = build_flat_list(tests)
        if not items:
            return None

        report = {"path": html_path, "name": name, "tests": tests, "items": items,
                  "remembered": None}
        report_dir = os.path.dirname(html_path)
        state, _source = load_clash_state(html_path)
        report["state"] = state
        for entry in items:
            entry["image_abs_path"] = resolve_image_path(report_dir, entry.get("image_path"))
            key = clash_key(entry)
            for flag in STATE_FLAGS:
                entry[flag] = key in state[flag]
            build_row(report, entry)
        return report

    def on_load_click(sender, args):
        # pump() lets input through, so without this guard a second click during
        # a long parse would re-enter this handler
        if busy[0]:
            return

        picked = forms.pick_file(file_ext="html", multi_file=True,
                                 title="Select Navisworks Clash Reports (HTML)")
        if not picked:
            return
        if isinstance(picked, basestring):
            picked = [picked]

        loaded, reloaded, empty, failed = [], [], [], []
        busy[0] = True
        load_button.IsEnabled = False
        export_button.IsEnabled = False
        try:
            for position, html_path in enumerate(picked, 1):
                try:
                    report = load_one(html_path, position, len(picked))
                except Exception as ex:
                    logger.warning("Failed to load {0}: {1}".format(html_path, ex))
                    failed.append(os.path.basename(html_path))
                    continue
                if report is None:
                    empty.append(os.path.basename(html_path))
                    continue

                existing = find_open_report(html_path)
                if existing is not None:
                    # Loading an open report again re-reads it in place -- the way
                    # to pick up a re-export. Its tab stays put.
                    existing["tests"] = report["tests"]
                    existing["items"] = report["items"]
                    existing["state"] = report["state"]
                    existing["remembered"] = None
                    for entry in existing["items"]:
                        build_row(existing, entry)
                    update_tab_text(existing)
                    reloaded.append(existing)
                else:
                    reports[0].append(report)
                    build_tab(report)
                    loaded.append(report)
        finally:
            busy[0] = False
            load_button.IsEnabled = True
            export_button.IsEnabled = True

        landed = loaded + reloaded
        if landed:
            activate(landed[-1])

        notes = []
        if loaded:
            notes.append(u"{0} report(s) opened".format(len(loaded)))
        if reloaded:
            notes.append(u"{0} reloaded".format(len(reloaded)))
        if landed:
            notes.append(u"{0} clashes in total".format(sum(len(r["items"]) for r in landed)))
        if notes:
            set_status(u", ".join(notes) + u".")

        problems = []
        if empty:
            problems.append(u"No clashes found in:\n  " + u"\n  ".join(empty))
        if failed:
            problems.append(u"Could not be read:\n  " + u"\n  ".join(failed))
        if problems:
            forms.alert(u"\n\n".join(problems))

    # ------------------------------------------------------------ export
    def on_export_click(sender, args):
        if busy[0]:
            return
        if not reports[0]:
            forms.alert("Load at least one clash report first.")
            return

        if len(reports[0]) == 1:
            chosen = list(reports[0])
        else:
            # Same file name in two folders is common (one per discipline), so
            # the folder goes in the option text to keep them apart.
            options = []
            by_option = {}
            for report in reports[0]:
                option = u"{0}   ({1})".format(report["name"], os.path.dirname(report["path"]))
                options.append(option)
                by_option[option] = report
            picked = forms.SelectFromList.show(
                options, title="Export results for which reports?",
                multiselect=True, button_name="Export", width=700, height=420)
            if not picked:
                return
            chosen = [r for r in reports[0] if any(by_option[p] is r for p in picked)]

        if len(chosen) == 1:
            default_name = os.path.splitext(chosen[0]["name"])[0] + u" - Results"
        else:
            default_name = u"Clash Results {0}".format(datetime.date.today().isoformat())

        # no title= here: older pyRevit builds' save_file doesn't accept one
        out_path = forms.save_file(file_ext="html", default_name=default_name)
        if not out_path:
            return

        set_status(u"Writing results for {0} report(s)...".format(len(chosen)))
        pump()
        write_text_utf8(out_path, build_results_html(chosen))
        set_status(u"Exported {0} report(s) to {1}".format(len(chosen), out_path))
        try:
            Process.Start(out_path)
        except Exception:
            logger.debug("Could not open the exported file automatically.")

    # ------------------------------------------------------------ selection
    def on_selection_changed(sender, args):
        report = active[0]
        idx = clash_list.SelectedIndex
        if report is None or idx < 0 or idx >= len(report["items"]):
            # Deliberately leaves report["remembered"] alone: the list empties
            # on every tab switch, and that must not
            # forget where the user was.
            clear_details()
            return

        clash = report["items"][idx]
        selected[0] = clash
        report["remembered"] = clash
        clash_image.Source = load_bitmap(clash.get("image_abs_path"))

        point = clash["clash_point"]
        if point is None:
            point_label.Text = u"Clash point: none in report"
        else:
            point_label.Text = u"Clash point: {0:.3f}, {1:.3f}, {2:.3f}".format(*point)

        # Resolving elements is an API call, so it can't happen here -- it is
        # queued and fills the labels in a moment. The identity check stops a
        # slow lookup from overwriting the labels of a clash the user has since
        # moved on from, which is easy to trigger by arrowing down the list.
        item1_label.Text = u"Item 1 (ID {0}): ...".format(clash["item1_id"])
        item2_label.Text = u"Item 2 (ID {0}): ...".format(clash["item2_id"])
        set_focus_enabled(False, "Checking whether both elements exist in this model...")

        def fill_labels():
            if selected[0] is not clash:
                return
            doc = get_doc()
            if doc is None:
                item1_label.Text = u"Item 1 (ID {0}): (no active document)".format(clash["item1_id"])
                item2_label.Text = u"Item 2 (ID {0}): (no active document)".format(clash["item2_id"])
                set_focus_enabled(False, "No active document.")
                return
            (el1, link1), (el2, link2) = resolve_clash_pair(doc, clash)
            item1_label.Text = u"Item 1 (ID {0}): {1}".format(
                clash["item1_id"], element_label_with_main(el1, link1))
            item2_label.Text = u"Item 2 (ID {0}): {1}".format(
                clash["item2_id"], element_label_with_main(el2, link2))

            # Isolating one of two elements is worse than not isolating at all --
            # it looks like it worked while hiding half of what you needed to see.
            if el1 is not None and el2 is not None:
                set_focus_enabled(True)
            else:
                missing = []
                if el1 is None:
                    missing.append("Item 1")
                if el2 is None:
                    missing.append("Item 2")
                set_focus_enabled(False, "{0} not found in this model or any loaded link.".format(
                    " and ".join(missing)))

        queue(fill_labels)

    def queue_focus(isolate):
        if selected[0] is None:
            set_status("Select a clash first.")
            return
        clash = selected[0]

        def action():
            summary = do_focus(clash, isolate=isolate)
            if summary:
                set_status(summary)

        queue(action)

    def on_focus_click(sender, args):
        queue_focus(False)

    def on_isolate_click(sender, args):
        queue_focus(True)

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
        clash = selected[0]

        def action():
            if do_clash_box(clash, size):
                set_status(u"Section box set{0}.".format(coord_mode_note()))

        queue(action)

    def coord_mode_note():
        """Shows which conversion won, so it can be pinned in the constants once
        it's known for a given exporter setup."""
        if CLASH_POINT_COORD_SYSTEM != "auto" or _COORD_MODE[0] is None:
            return ""
        return u" (coordinate mode: {0})".format(_COORD_MODE[0])

    def on_closed(sender, args):
        # Drop the env-var reference so a later press opens a fresh window, and
        # release the ExternalEvent rather than leaving it registered with Revit
        # for the rest of the session.
        set_session(None)
        try:
            external_event.Dispose()
        except Exception:
            logger.debug("ExternalEvent was already disposed.")

    load_button.Click += RoutedEventHandler(safe_handler(on_load_click))
    export_button.Click += RoutedEventHandler(safe_handler(on_export_click))
    focus_button.Click += RoutedEventHandler(safe_handler(on_focus_click))
    isolate_button.Click += RoutedEventHandler(safe_handler(on_isolate_click))
    clash_box_button.Click += RoutedEventHandler(safe_handler(on_clash_box_click))
    clash_list.SelectionChanged += SelectionChangedEventHandler(safe_handler(on_selection_changed))
    window.Closed += EventHandler(on_closed)

    refresh_list()

    # The window and its plumbing are parked where they outlive this scope. This
    # is the strong reference that keeps the ExternalEvent from being collected
    # while the window is still open.
    set_session({"window": window, "handler": event_handler, "event": external_event})

    # Show(), not ShowDialog(), and nothing after it: the script ends here and
    # Revit goes back to being completely free.
    window.Show()


run()
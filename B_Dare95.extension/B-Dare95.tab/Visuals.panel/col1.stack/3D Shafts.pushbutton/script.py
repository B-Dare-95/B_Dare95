# -*- coding: utf-8 -*-

__title__ = "3D Shafts"
__doc__ = """
________________________________________________________________
Description:
- Live, modeless 3D visualization of Shaft Openings, colored by
  "Shaft Function", drawn with DirectContext3D.

Nothing is created in the model:
- No DirectShapes, no transaction, no worksets, no view overrides.
- The overlay exists only while this window is open.

How to Use:
- Activate a 3D View and run the tool.
- Pick colors per Shaft Function, toggle visibility, set transparency.
- Edit shafts in Revit; the overlay follows every change live.
________________________________________________________________
REQUIRES in bundle.yaml:

    engine:
      persistent: true
      clean: false

Without a persistent engine the IronPython scope is disposed while
the DirectContext3D server is still registered, and Revit will crash
on the next frame.
________________________________________________________________
Author: Mohamed Bedair"""

# ---------------------------------------------------------------------------
# Duplicate-window guard - runs BEFORE any heavy import.
# With engine {persistent: true, clean: false} the same IronPython engine and
# scope survive across clicks, so a second click must not build a second
# server or re-register a second set of event handlers. script.exit() raises
# SystemExit, which the runner catches without disposing the engine.
# ---------------------------------------------------------------------------
from pyrevit import script

logger = script.get_logger()

SHAFTS_WINDOW_KEY = "PYREVIT_SHAFTS3D_WINDOW"
SHAFTS_EXECID_KEY = "PYREVIT_SHAFTS3D_EXECID"

_existing = script.get_envvar(SHAFTS_WINDOW_KEY)
if _existing:
    try:
        if _existing.IsVisible:
            try:
                _existing.Activate()
            except Exception:
                pass
            script.exit()
    except SystemExit:
        raise
    except Exception:
        script.set_envvar(SHAFTS_WINDOW_KEY, None)
        script.set_envvar(SHAFTS_EXECID_KEY, None)

# ---------------------------------------------------------------------------
# Full imports
# ---------------------------------------------------------------------------
import os
import tempfile

import clr
clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")

import System.Windows.Forms as WinForms
import System.Drawing as Drawing

from pyrevit import forms, revit, DB, UI, EXEC_PARAMS
from pyrevit.revit import events
from pyrevit.framework import Convert, List, Color, SolidColorBrush
from pyrevit.compat import get_elementid_value_func

get_elementid_value = get_elementid_value_func()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
FUNC_PARAM_NAME = "Shaft Function"
UNDEFINED = "(Undefined)"

SHAFT_BIC = DB.BuiltInCategory.OST_ShaftOpening
SHAFT_CAT_ID = DB.ElementId(SHAFT_BIC)

# Tessellation level of detail, 0.0 (coarsest) .. 1.0 (finest).
# Only matters for curved shaft profiles.
TESSELLATION_LOD = 0.5

# Cap the triangles / lines placed in a single DirectContext3D buffer.
# Several small meshes are safer than one huge one.
MAX_TRIS_PER_MESH = 1500
MAX_LINES_PER_MESH = 3000

# Above this many shafts the tool warns instead of silently grinding.
HEAVY_MODEL_WARNING = 1500

# Rebuild levels, ascending cost. The scheduler keeps the highest requested.
LEVEL_DRAW = 0      # colors / visibility only, reuse cached geometry
LEVEL_PARTIAL = 1   # re-read a known set of shafts
LEVEL_FULL = 2      # re-collect everything from the document

# DirectContext3D vertex colors arrive with red and blue transposed on this
# Revit / pyRevit combination. Verify with a pure red (255, 0, 0): if the
# overlay renders it blue, leave this True. See dc3d_color() below.
DC3D_SWAP_RED_BLUE = True

# Catppuccin Mocha
CLR_BG = "#1E1E2E"
CLR_CARD = "#2A2A3C"
CLR_SURFACE = "#313244"
CLR_MUTED = "#45475A"
CLR_TEXT = "#CDD6F4"
CLR_SUBTEXT = "#A6ADC8"
CLR_ACCENT = "#F0A500"

DEFAULT_PALETTE = [
    (137, 180, 250),
    (250, 179, 135),
    (166, 227, 161),
    (243, 139, 168),
    (203, 166, 247),
    (249, 226, 175),
    (148, 226, 213),
    (245, 194, 231),
    (116, 199, 236),
    (250, 227, 176),
]

# Mutable container holding the Context singleton, so reactive property
# setters defined before Context exists can still reach it.
CTX = [None]

CFG = script.get_config("shafts3d_visualizer")


# ---------------------------------------------------------------------------
# Preference persistence
# ---------------------------------------------------------------------------
def load_prefs():
    """Return (color_map, transparency). Never raises."""
    colors = {}
    transparency = 50
    try:
        raw = CFG.get_option("colors", {})
        for key, value in dict(raw).items():
            parts = str(value).split(",")
            if len(parts) == 3:
                colors[key] = (int(parts[0]), int(parts[1]), int(parts[2]))
    except Exception:
        colors = {}
    try:
        transparency = int(CFG.get_option("transparency", 50))
    except Exception:
        transparency = 50
    return colors, max(0, min(100, transparency))


def save_prefs(color_map, transparency):
    try:
        stored = {}
        for key, rgb in color_map.items():
            stored[key] = "{},{},{}".format(rgb[0], rgb[1], rgb[2])
        CFG.colors = stored
        CFG.transparency = int(transparency)
        script.save_config()
    except Exception as ex:
        logger.debug("Could not save preferences: {}".format(ex))


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def to_brush(rgb):
    return SolidColorBrush(
        Color.FromRgb(
            Convert.ToByte(rgb[0]), Convert.ToByte(rgb[1]), Convert.ToByte(rgb[2])
        )
    )


def dc3d_color(rgb, alpha):
    """Build the ColorWithTransparency handed to DirectContext3D.

    On this pyRevit / Revit combination the vertex color reaches the GPU with
    the red and blue channels transposed, so a Catppuccin blue renders as
    peach and vice versa. WPF swatches are unaffected because they go through
    Color.FromRgb instead. Set the flag to False if your build renders pure
    red (255, 0, 0) as red.
    """
    red, green, blue = rgb[0], rgb[1], rgb[2]
    if DC3D_SWAP_RED_BLUE:
        red, blue = blue, red
    return DB.ColorWithTransparency(red, green, blue, alpha)


def palette_color(index):
    return DEFAULT_PALETTE[index % len(DEFAULT_PALETTE)]


def is_shaft(element):
    try:
        return (
            element is not None
            and element.Category is not None
            and element.Category.Id == SHAFT_CAT_ID
        )
    except Exception:
        return False


def get_function_value(element):
    """Read 'Shaft Function' as a display string, tolerant of storage type."""
    try:
        param = element.LookupParameter(FUNC_PARAM_NAME)
        if param is not None:
            value = None
            if param.StorageType == DB.StorageType.String:
                value = param.AsString()
            if not value:
                value = param.AsValueString()
            if value and value.strip():
                return value.strip()
    except Exception:
        pass
    return UNDEFINED


def compare_views(view1, view2):
    if not view1 and not view2:
        return True
    if not view1 or not view2:
        return False
    try:
        return (
            view1.Document.GetHashCode() == view2.Document.GetHashCode()
            and view1.Id == view2.Id
        )
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Geometry - unchanged logic from the DirectShape version, then tessellated
# ---------------------------------------------------------------------------
def split_closed_curve(curve):
    """Split one closed curve into halves so CurveLoop will accept it."""
    p0 = curve.GetEndParameter(0)
    p1 = curve.GetEndParameter(1)
    pmid = (p0 + p1) / 2.0

    if isinstance(curve, DB.Arc):
        return [
            DB.Arc.Create(
                curve.Center, curve.Radius, p0, pmid, curve.XDirection, curve.YDirection
            ),
            DB.Arc.Create(
                curve.Center, curve.Radius, pmid, p1, curve.XDirection, curve.YDirection
            ),
        ]

    if isinstance(curve, DB.Ellipse):
        return [
            DB.Ellipse.CreateCurve(
                curve.Center,
                curve.RadiusX,
                curve.RadiusY,
                curve.XDirection,
                curve.YDirection,
                p0,
                pmid,
            ),
            DB.Ellipse.CreateCurve(
                curve.Center,
                curve.RadiusX,
                curve.RadiusY,
                curve.XDirection,
                curve.YDirection,
                pmid,
                p1,
            ),
        ]

    points = list(curve.Tessellate())
    segments = []
    for i in range(len(points) - 1):
        segments.append(DB.Line.CreateBound(points[i], points[i + 1]))
    return segments


def chain_curves(curves):
    """Order curves into one continuous end-to-end chain, reversing as needed."""
    tol = 1e-6
    ordered = [curves[0]]
    remaining = list(curves[1:])

    while remaining:
        tail = ordered[-1].GetEndPoint(1)
        found = False
        for i, curve in enumerate(remaining):
            if tail.DistanceTo(curve.GetEndPoint(0)) < tol:
                ordered.append(remaining.pop(i))
                found = True
                break
            if tail.DistanceTo(curve.GetEndPoint(1)) < tol:
                ordered.append(curve.CreateReversed())
                remaining.pop(i)
                found = True
                break
        if not found:
            gap = min(tail.DistanceTo(c.GetEndPoint(0)) for c in remaining)
            raise Exception(
                "Cannot form a continuous loop, gap of {:.6f} ft.".format(gap)
            )
    return ordered


def build_solid(shaft):
    """Extrude the shaft boundary to its height. Returns a Solid or None."""
    curves = [c for c in shaft.BoundaryCurves if c is not None]
    if not curves:
        return None

    if len(curves) == 1:
        curves = split_closed_curve(curves[0])
    curves = chain_curves(curves)

    loop = DB.CurveLoop()
    for curve in curves:
        loop.Append(curve)

    profile = List[DB.CurveLoop]()
    profile.Add(loop)

    height_param = shaft.get_Parameter(DB.BuiltInParameter.WALL_USER_HEIGHT_PARAM)
    if height_param is None:
        return None
    height = height_param.AsDouble()
    if height <= 1e-9:
        return None

    return DB.GeometryCreationUtilities.CreateExtrusionGeometry(
        profile, DB.XYZ.BasisZ, height
    )


def tessellate_solid(solid):
    """Convert a Solid into raw vertex data.

    Returns (triangles, lines) where triangles is a list of 3-tuples of XYZ
    and lines is a list of 2-tuples of XYZ. Nothing here holds a reference to
    a Revit Element, which is what makes the result safe to hand to the
    render thread.
    """
    triangles = []
    lines = []

    if solid is None:
        return triangles, lines

    try:
        if solid.Faces.Size == 0:
            return triangles, lines
    except Exception:
        return triangles, lines

    for face in solid.Faces:
        try:
            mesh = face.Triangulate(TESSELLATION_LOD)
        except Exception:
            mesh = None
        if mesh is None:
            continue
        for i in range(mesh.NumTriangles):
            try:
                tri = mesh.get_Triangle(i)
                triangles.append(
                    (tri.get_Vertex(0), tri.get_Vertex(1), tri.get_Vertex(2))
                )
            except Exception:
                continue

    for edge in solid.Edges:
        try:
            points = list(edge.Tessellate())
        except Exception:
            continue
        for i in range(len(points) - 1):
            lines.append((points[i], points[i + 1]))

    return triangles, lines


# ---------------------------------------------------------------------------
# Data record - plain vertex data, no live Revit references
# ---------------------------------------------------------------------------
class ShaftRecord(object):
    def __init__(self, id_value, element_id, function):
        self.id_value = id_value        # plain int, used as a dict key
        self.element_id = element_id    # real ElementId, avoids ElementId(int)
        self.function = function
        self.triangles = None           # None means "not tessellated yet"
        self.lines = None
        self.failed = False

    def invalidate(self):
        self.triangles = None
        self.lines = None
        self.failed = False


# ---------------------------------------------------------------------------
# View models
# ---------------------------------------------------------------------------
class FunctionRow(forms.Reactive):
    """One row in the function list. Reactive so WPF two-way binding works."""

    def __init__(self, name, count, rgb, visible):
        self._name_text = name
        self._count_text = "{} shaft{}".format(count, "" if count == 1 else "s")
        self._swatch = to_brush(rgb)
        self._is_visible = visible

    @forms.reactive
    def name_text(self):
        return self._name_text

    @name_text.setter
    def name_text(self, value):
        self._name_text = value

    @forms.reactive
    def count_text(self):
        return self._count_text

    @count_text.setter
    def count_text(self, value):
        self._count_text = value

    @forms.reactive
    def swatch(self):
        return self._swatch

    @swatch.setter
    def swatch(self, value):
        self._swatch = value

    @forms.reactive
    def is_visible(self):
        return self._is_visible

    @is_visible.setter
    def is_visible(self, value):
        self._is_visible = bool(value)
        ctx = CTX[0]
        if ctx is not None:
            ctx.visibility[self._name_text] = self._is_visible
            ctx.request(LEVEL_DRAW)


class MainViewModel(forms.Reactive):

    _TRANSPARENT_BG = SolidColorBrush(
        Color.FromArgb(
            Convert.ToByte(0), Convert.ToByte(0), Convert.ToByte(0), Convert.ToByte(0)
        )
    )
    _ERROR_BG = SolidColorBrush(
        Color.FromArgb(
            Convert.ToByte(255), Convert.ToByte(58), Convert.ToByte(30), Convert.ToByte(38)
        )
    )
    _ERROR_FG = SolidColorBrush(
        Color.FromRgb(Convert.ToByte(243), Convert.ToByte(139), Convert.ToByte(168))
    )
    _INFO_BG = SolidColorBrush(
        Color.FromArgb(
            Convert.ToByte(255), Convert.ToByte(35), Convert.ToByte(48), Convert.ToByte(40)
        )
    )
    _INFO_FG = SolidColorBrush(
        Color.FromRgb(Convert.ToByte(166), Convert.ToByte(227), Convert.ToByte(161))
    )

    def __init__(self, transparency):
        self._status_message = "Starting up..."
        self._rows = []
        self._all_rows = []
        self._selected_row = None
        self._filter_text = ""
        self._transparency = transparency
        self._transparency_label = "{}%".format(transparency)
        self._selection_only = False
        self._banner_message = ""
        self._banner_icon = ""
        self._banner_bg = self._TRANSPARENT_BG
        self._banner_fg = self._ERROR_FG

    # -- banner -------------------------------------------------------------
    def show_error(self, message):
        self.banner_icon = u"\u26A0"
        self.banner_bg = self._ERROR_BG
        self.banner_fg = self._ERROR_FG
        self.banner_message = message

    def show_info(self, message):
        self.banner_icon = u"\u2714"
        self.banner_bg = self._INFO_BG
        self.banner_fg = self._INFO_FG
        self.banner_message = message

    def clear_banner(self):
        self.banner_icon = ""
        self.banner_bg = self._TRANSPARENT_BG
        self.banner_fg = self._ERROR_FG
        self.banner_message = ""

    # -- properties ---------------------------------------------------------
    @forms.reactive
    def status_message(self):
        return self._status_message

    @status_message.setter
    def status_message(self, value):
        self._status_message = value

    @forms.reactive
    def rows(self):
        return self._rows

    @rows.setter
    def rows(self, value):
        self._rows = value

    @forms.reactive
    def selected_row(self):
        return self._selected_row

    @selected_row.setter
    def selected_row(self, value):
        self._selected_row = value

    @forms.reactive
    def filter_text(self):
        return self._filter_text

    @filter_text.setter
    def filter_text(self, value):
        self._filter_text = value or ""
        self.apply_filter()

    @forms.reactive
    def transparency(self):
        return self._transparency

    @transparency.setter
    def transparency(self, value):
        try:
            new_value = int(round(float(value)))
        except Exception:
            return
        if new_value == self._transparency:
            return
        self._transparency = new_value
        self.transparency_label = "{}%".format(new_value)
        ctx = CTX[0]
        if ctx is not None:
            ctx.request(LEVEL_DRAW)

    @forms.reactive
    def transparency_label(self):
        return self._transparency_label

    @transparency_label.setter
    def transparency_label(self, value):
        self._transparency_label = value

    @forms.reactive
    def selection_only(self):
        return self._selection_only

    @selection_only.setter
    def selection_only(self, value):
        self._selection_only = bool(value)
        ctx = CTX[0]
        if ctx is not None:
            ctx.request(LEVEL_DRAW)

    @forms.reactive
    def banner_message(self):
        return self._banner_message

    @banner_message.setter
    def banner_message(self, value):
        self._banner_message = value

    @forms.reactive
    def banner_icon(self):
        return self._banner_icon

    @banner_icon.setter
    def banner_icon(self, value):
        self._banner_icon = value

    @forms.reactive
    def banner_bg(self):
        return self._banner_bg

    @banner_bg.setter
    def banner_bg(self, value):
        self._banner_bg = value

    @forms.reactive
    def banner_fg(self):
        return self._banner_fg

    @banner_fg.setter
    def banner_fg(self, value):
        self._banner_fg = value

    # -- row list -----------------------------------------------------------
    def set_rows(self, row_list):
        self._all_rows = row_list
        self.apply_filter()

    def apply_filter(self):
        needle = (self._filter_text or "").strip().lower()
        if not needle:
            self.rows = list(self._all_rows)
        else:
            self.rows = [
                r for r in self._all_rows if needle in r.name_text.lower()
            ]

    def all_rows(self):
        return list(self._all_rows)


# ---------------------------------------------------------------------------
# Context - owns document state, the geometry cache and the redraw scheduler
# ---------------------------------------------------------------------------
class Context(object):
    def __new__(cls, *args, **kwargs):
        if not hasattr(cls, "instance"):
            cls.instance = super(Context, cls).__new__(cls)
        return cls.instance

    def __init__(self, view_model, color_map):
        self.vm = view_model
        self.color_map = color_map      # function name -> (r, g, b)
        self.visibility = {}            # function name -> bool
        self.records = {}               # element id value -> ShaftRecord
        self.selected_ids = set()

        self._active_view = None
        self._doc_hash = None
        self._func_signature = None

        self._scheduled = False
        self._level = LEVEL_DRAW
        self._dirty = {}

    # -- active view --------------------------------------------------------
    @property
    def active_view(self):
        if self._active_view is not None and not self._active_view.IsValidObject:
            self._active_view = None
        return self._active_view

    @active_view.setter
    def active_view(self, value):
        if compare_views(self._active_view, value):
            return
        previous_hash = self._doc_hash
        self._active_view = value
        try:
            self._doc_hash = (
                value.Document.GetHashCode() if value is not None else None
            )
        except Exception:
            self._doc_hash = None

        if self._doc_hash != previous_hash:
            self.records = {}
            self._func_signature = None
            self.request(LEVEL_FULL)
        else:
            self.request(LEVEL_DRAW)

    @property
    def document(self):
        view = self.active_view
        if view is None:
            return None
        try:
            return view.Document
        except Exception:
            return None

    def owns_document(self, other_doc):
        try:
            return (
                self._doc_hash is not None
                and other_doc is not None
                and other_doc.GetHashCode() == self._doc_hash
            )
        except Exception:
            return False

    def is_valid(self):
        return isinstance(self.active_view, DB.View3D)

    # -- scheduler ----------------------------------------------------------
    def request(self, level, dirty_map=None):
        """Coalesce work and run it inside a valid Revit API context.

        Everything that reads the model or touches the server funnels through
        here. Nothing below this line ever runs straight off a WPF handler.
        """
        if level > self._level:
            self._level = level
        if dirty_map:
            self._dirty.update(dirty_map)
        if self._scheduled:
            return
        self._scheduled = True
        try:
            events.execute_in_revit_context(self._flush)
        except Exception as ex:
            self._scheduled = False
            logger.exception(ex)

    def _flush(self):
        self._scheduled = False
        level = self._level
        dirty = self._dirty
        self._level = LEVEL_DRAW
        self._dirty = {}

        try:
            if level == LEVEL_FULL:
                self._rebuild_all()
            elif level == LEVEL_PARTIAL:
                self._rebuild_partial(dirty)

            if self.vm.selection_only:
                self._refresh_selection()

            self._draw()
            self._update_status()
        except Exception as ex:
            logger.exception(ex)
            self.vm.show_error("Rebuild failed: {}".format(ex))

    # -- model reads --------------------------------------------------------
    def _refresh_selection(self):
        try:
            ids = revit.uidoc.Selection.GetElementIds()
            self.selected_ids = set(get_elementid_value(i) for i in ids)
        except Exception:
            self.selected_ids = set()

    def _rebuild_all(self):
        doc = self.document
        if doc is None:
            self.records = {}
            return

        collected = (
            DB.FilteredElementCollector(doc)
            .OfCategory(SHAFT_BIC)
            .WhereElementIsNotElementType()
            .ToElements()
        )

        previous = self.records
        records = {}
        for shaft in collected:
            id_value = get_elementid_value(shaft.Id)
            function = get_function_value(shaft)
            old = previous.get(id_value)
            if old is not None and old.function == function:
                old.element_id = shaft.Id
                records[id_value] = old        # keep cached tessellation
            else:
                records[id_value] = ShaftRecord(id_value, shaft.Id, function)
        self.records = records

        if len(records) > HEAVY_MODEL_WARNING:
            self.vm.show_error(
                "{} shafts in this model. Use the filter or "
                "'Selected shafts only' to keep it responsive.".format(len(records))
            )

        self._sync_functions()

    def _rebuild_partial(self, dirty_map):
        doc = self.document
        if doc is None:
            return

        for id_value, element_id in dirty_map.items():
            element = None
            try:
                element = doc.GetElement(element_id)
            except Exception:
                element = None

            if element is None or not is_shaft(element):
                self.records.pop(id_value, None)
                continue

            function = get_function_value(element)
            record = self.records.get(id_value)
            if record is None:
                record = ShaftRecord(id_value, element_id, function)
                self.records[id_value] = record
            else:
                record.element_id = element_id
                record.function = function
            record.invalidate()

        self._sync_functions()

    def _sync_functions(self):
        """Rebuild the function list, keeping existing colors and toggles."""
        counts = {}
        for record in self.records.values():
            counts[record.function] = counts.get(record.function, 0) + 1

        # Pick the first palette color not already in use. Indexing by
        # len(color_map) breaks as soon as saved preferences carry entries for
        # functions that no longer exist in the model.
        used = set(self.color_map.values())
        index = 0
        for function in sorted(counts.keys()):
            if function not in self.color_map:
                while index < len(DEFAULT_PALETTE) and palette_color(index) in used:
                    index += 1
                rgb = palette_color(index)
                self.color_map[function] = rgb
                used.add(rgb)
                index += 1
            if function not in self.visibility:
                self.visibility[function] = True

        # Only rebuild the row objects when the breakdown actually changed,
        # otherwise every small Revit edit would flicker the list.
        signature = tuple(sorted(counts.items()))
        if signature == self._func_signature:
            return
        self._func_signature = signature

        previous_name = None
        if self.vm.selected_row is not None:
            previous_name = self.vm.selected_row.name_text

        rows = []
        for function in sorted(counts.keys()):
            rows.append(
                FunctionRow(
                    function,
                    counts[function],
                    self.color_map[function],
                    self.visibility.get(function, True),
                )
            )
        self.vm.set_rows(rows)

        if previous_name:
            for row in rows:
                if row.name_text == previous_name:
                    self.vm.selected_row = row
                    break

    def _ensure_geometry(self, record):
        """Tessellate on demand, once, and cache the raw vertices."""
        if record.triangles is not None or record.failed:
            return
        doc = self.document
        if doc is None:
            record.failed = True
            return
        try:
            element = doc.GetElement(record.element_id)
            if element is None or not element.IsValidObject:
                record.failed = True
                return
            solid = build_solid(element)
            triangles, lines = tessellate_solid(solid)
            record.triangles = triangles
            record.lines = lines
            if not triangles and not lines:
                record.failed = True
        except Exception as ex:
            logger.debug("Shaft {} skipped: {}".format(record.id_value, ex))
            record.failed = True

    # -- drawing ------------------------------------------------------------
    def _wanted(self, record):
        if not self.visibility.get(record.function, True):
            return False
        if self.vm.selection_only and record.id_value not in self.selected_ids:
            return False
        return True

    def _build_meshes(self):
        alpha_faces = int(255.0 * self.vm.transparency / 100.0)
        alpha_faces = max(0, min(255, alpha_faces))
        alpha_edges = min(alpha_faces, 60)

        grouped = {}
        for record in self.records.values():
            if not self._wanted(record):
                continue
            self._ensure_geometry(record)
            if record.failed or not record.triangles:
                continue
            bucket = grouped.setdefault(record.function, ([], []))
            bucket[0].extend(record.triangles)
            bucket[1].extend(record.lines or [])

        meshes = []
        for function, (triangles, lines) in grouped.items():
            rgb = self.color_map.get(function, (200, 200, 200))
            face_color = dc3d_color(rgb, alpha_faces)
            edge_color = dc3d_color(rgb, alpha_edges)

            tri_objects = []
            for v0, v1, v2 in triangles:
                try:
                    normal = revit.dc3dserver.Mesh.calculate_triangle_normal(
                        v0, v1, v2
                    )
                    tri_objects.append(
                        revit.dc3dserver.Triangle(v0, v1, v2, normal, face_color)
                    )
                except Exception:
                    continue

            edge_objects = []
            for start, end in lines:
                try:
                    edge_objects.append(
                        revit.dc3dserver.Edge(start, end, edge_color)
                    )
                except Exception:
                    continue

            meshes.extend(self._chunk(edge_objects, tri_objects))

        return meshes

    def _chunk(self, edge_objects, tri_objects):
        """Split into several small meshes rather than one oversized buffer."""
        meshes = []
        tri_count = len(tri_objects)
        edge_count = len(edge_objects)
        tri_batches = (tri_count + MAX_TRIS_PER_MESH - 1) // MAX_TRIS_PER_MESH
        edge_batches = (edge_count + MAX_LINES_PER_MESH - 1) // MAX_LINES_PER_MESH
        batches = max(tri_batches, edge_batches)

        for i in range(batches):
            tris = tri_objects[i * MAX_TRIS_PER_MESH:(i + 1) * MAX_TRIS_PER_MESH]
            edges = edge_objects[i * MAX_LINES_PER_MESH:(i + 1) * MAX_LINES_PER_MESH]
            if not tris and not edges:
                continue
            try:
                meshes.append(revit.dc3dserver.Mesh(edges, tris))
            except Exception as ex:
                logger.debug("Mesh chunk skipped: {}".format(ex))
        return meshes

    def _draw(self):
        """Swap the server's geometry.

        The server is ALWAYS unregistered before meshes are touched, so the
        render thread can never walk a list that is being replaced.
        """
        if not self.is_valid():
            self.clear_geometry()
            return

        try:
            server.uidoc = UI.UIDocument(self.active_view.Document)
        except Exception:
            pass

        meshes = self._build_meshes()

        try:
            server.remove_server()
        except Exception:
            pass
        server.meshes = meshes
        if meshes:
            try:
                server.add_server()
            except Exception as ex:
                logger.exception(ex)

        refresh_active_view()

    def clear_geometry(self):
        try:
            server.remove_server()
        except Exception:
            pass
        server.meshes = []
        refresh_active_view()

    def _update_status(self):
        if not isinstance(self.active_view, DB.View3D):
            self.vm.status_message = "Activate a 3D View to see the overlay."
            return

        total = len(self.records)
        if total == 0:
            self.vm.status_message = "No Shaft Openings found in this model."
            return

        drawn = len([r for r in self.records.values() if self._wanted(r)])
        self.vm.status_message = "Drawing {} of {} shafts in [{}]".format(
            drawn, total, self.active_view.Name
        )


# ---------------------------------------------------------------------------
# XAML - inline, Catppuccin Mocha
# ---------------------------------------------------------------------------
XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="3D Shafts - Live Visualizer"
        Height="640" Width="470" MinHeight="520" MinWidth="420"
        Background="#1E1E2E" WindowStartupLocation="CenterScreen"
        ResizeMode="CanResize" ShowInTaskbar="True">

  <Window.Resources>
    <Style x:Key="FlatButton" TargetType="Button">
      <Setter Property="Foreground" Value="#CDD6F4"/>
      <Setter Property="Background" Value="#45475A"/>
      <Setter Property="FontFamily" Value="Segoe UI"/>
      <Setter Property="FontSize" Value="11"/>
      <Setter Property="Height" Value="28"/>
      <Setter Property="Margin" Value="0,0,6,0"/>
      <Setter Property="Padding" Value="10,0"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="bd" Background="{TemplateBinding Background}"
                    CornerRadius="4" Padding="{TemplateBinding Padding}">
              <ContentPresenter HorizontalAlignment="Center"
                                VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="bd" Property="Background" Value="#585B70"/>
              </Trigger>
              <Trigger Property="IsEnabled" Value="False">
                <Setter TargetName="bd" Property="Opacity" Value="0.45"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="AccentButton" TargetType="Button"
           BasedOn="{StaticResource FlatButton}">
      <Setter Property="Background" Value="#F0A500"/>
      <Setter Property="Foreground" Value="#1E1E2E"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
    </Style>

    <Style x:Key="Caption" TargetType="TextBlock">
      <Setter Property="Foreground" Value="#A6ADC8"/>
      <Setter Property="FontFamily" Value="Segoe UI"/>
      <Setter Property="FontSize" Value="11"/>
    </Style>

    <Style x:Key="DarkCheck" TargetType="CheckBox">
      <Setter Property="Foreground" Value="#CDD6F4"/>
      <Setter Property="FontFamily" Value="Segoe UI"/>
      <Setter Property="FontSize" Value="11"/>
      <Setter Property="VerticalContentAlignment" Value="Center"/>
    </Style>

    <Style x:Key="RowItemStyle" TargetType="ListBoxItem">
      <Setter Property="Margin" Value="0,0,0,4"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ListBoxItem">
            <Border x:Name="bd" Background="#2A2A3C" CornerRadius="4"
                    BorderThickness="1" BorderBrush="#2A2A3C" Padding="8,6">
              <ContentPresenter/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsSelected" Value="True">
                <Setter TargetName="bd" Property="BorderBrush" Value="#F0A500"/>
                <Setter TargetName="bd" Property="Background" Value="#313244"/>
              </Trigger>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="bd" Property="Background" Value="#313244"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <DataTemplate x:Key="RowTemplate">
      <Grid>
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="Auto"/>
          <ColumnDefinition Width="Auto"/>
          <ColumnDefinition Width="*"/>
          <ColumnDefinition Width="Auto"/>
        </Grid.ColumnDefinitions>
        <CheckBox Grid.Column="0" VerticalAlignment="Center" Margin="0,0,8,0"
                  IsChecked="{Binding is_visible, Mode=TwoWay}"/>
        <Border Grid.Column="1" Width="18" Height="18" CornerRadius="3"
                Margin="0,0,10,0" Background="{Binding swatch}"/>
        <TextBlock Grid.Column="2" Text="{Binding name_text}"
                   Foreground="#CDD6F4" FontFamily="Segoe UI" FontSize="12"
                   VerticalAlignment="Center" TextTrimming="CharacterEllipsis"/>
        <TextBlock Grid.Column="3" Text="{Binding count_text}"
                   Foreground="#A6ADC8" FontFamily="Segoe UI" FontSize="10"
                   VerticalAlignment="Center" Margin="8,0,0,0"/>
      </Grid>
    </DataTemplate>
  </Window.Resources>

  <Grid Margin="14">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <TextBlock Grid.Row="0" Text="{Binding status_message}" Foreground="#CDD6F4"
               FontFamily="Segoe UI" FontSize="12" TextWrapping="Wrap"
               Margin="0,0,0,10"/>

    <TextBox Grid.Row="1" x:Name="filter_box" Height="26" Margin="0,0,0,8"
             Background="#313244" Foreground="#CDD6F4" BorderBrush="#45475A"
             BorderThickness="1" FontFamily="Segoe UI" FontSize="11"
             VerticalContentAlignment="Center" Padding="6,0"
             Text="{Binding filter_text, UpdateSourceTrigger=PropertyChanged}"/>

    <ListBox Grid.Row="2" x:Name="rows_list"
             ItemsSource="{Binding rows}"
             SelectedItem="{Binding selected_row, Mode=TwoWay}"
             ItemTemplate="{StaticResource RowTemplate}"
             ItemContainerStyle="{StaticResource RowItemStyle}"
             Background="Transparent" BorderThickness="0"
             ScrollViewer.HorizontalScrollBarVisibility="Disabled"
             MouseDoubleClick="change_color_click"/>

    <StackPanel Grid.Row="3" Orientation="Horizontal" Margin="0,10,0,0">
      <Button Content="Change Color" Style="{StaticResource AccentButton}"
              Click="change_color_click"/>
      <Button Content="Show All" Style="{StaticResource FlatButton}"
              Click="show_all_click"/>
      <Button Content="Hide All" Style="{StaticResource FlatButton}"
              Click="hide_all_click"/>
      <Button Content="Reset Palette" Style="{StaticResource FlatButton}"
              Click="reset_palette_click"/>
    </StackPanel>

    <Grid Grid.Row="4" Margin="0,14,0,0">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="Auto"/>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="Auto"/>
      </Grid.ColumnDefinitions>
      <TextBlock Grid.Column="0" Text="Transparency"
                 Style="{StaticResource Caption}" VerticalAlignment="Center"/>
      <Slider Grid.Column="1" Minimum="0" Maximum="100" Margin="10,0"
              IsSnapToTickEnabled="True" TickFrequency="5"
              VerticalAlignment="Center"
              Value="{Binding transparency, Mode=TwoWay, Delay=120}"/>
      <TextBlock Grid.Column="2" Text="{Binding transparency_label}"
                 Foreground="#CDD6F4" FontFamily="Segoe UI" FontSize="11"
                 FontWeight="SemiBold" VerticalAlignment="Center" Width="34"
                 TextAlignment="Right"/>
    </Grid>

    <StackPanel Grid.Row="5" Orientation="Horizontal" Margin="0,12,0,0">
      <CheckBox Content="Selected shafts only" Style="{StaticResource DarkCheck}"
                IsChecked="{Binding selection_only, Mode=TwoWay}"/>
    </StackPanel>

    <StackPanel Grid.Row="6" Orientation="Horizontal" Margin="0,14,0,0"
                HorizontalAlignment="Right">
      <Button Content="Refresh" Style="{StaticResource FlatButton}"
              Click="refresh_click"/>
      <Button Content="Close" Style="{StaticResource FlatButton}"
              Click="close_click" Margin="0"/>
    </StackPanel>

    <Border Grid.Row="7" Background="{Binding banner_bg}" CornerRadius="4"
            Padding="10,6" Margin="0,12,0,0">
      <StackPanel Orientation="Horizontal">
        <TextBlock Text="{Binding banner_icon}" FontSize="13"
                   Foreground="{Binding banner_fg}" VerticalAlignment="Center"
                   Margin="0,0,6,0"/>
        <TextBlock Text="{Binding banner_message}" FontFamily="Segoe UI"
                   FontSize="11" Foreground="{Binding banner_fg}"
                   TextWrapping="Wrap" VerticalAlignment="Center"/>
      </StackPanel>
    </Border>
  </Grid>
</Window>
"""


# ---------------------------------------------------------------------------
# Window
# ---------------------------------------------------------------------------
class MainWindow(forms.WPFWindow):
    def __init__(self):
        try:
            forms.WPFWindow.__init__(self, XAML, literal_string=True)
        except TypeError:
            # Older pyRevit builds without literal_string support.
            temp_path = os.path.join(
                tempfile.gettempdir(), "b_dare95_shafts3d.xaml"
            )
            handle = open(temp_path, "w")
            try:
                handle.write(XAML.encode("utf-8"))
            finally:
                handle.close()
            forms.WPFWindow.__init__(self, temp_path)

        self.Closed += self.window_closed
        script.restore_window_position(self)
        # Deliberately NOT calling server.add_server() here. The server is
        # registered by Context._draw(), and only once it actually holds
        # meshes, so the render thread never sees an empty server.

    # -- lifecycle ----------------------------------------------------------
    def window_closed(self, sender, args):
        try:
            save_prefs(context.color_map, context.vm.transparency)
        except Exception as ex:
            logger.debug("Preference save failed: {}".format(ex))
        try:
            script.save_window_position(self)
        except Exception:
            pass
        events.execute_in_revit_context(_on_close_cleanup)

    def close_click(self, sender, e):
        self.Close()

    # -- commands -----------------------------------------------------------
    def change_color_click(self, sender, e):
        try:
            row = self.DataContext.selected_row
            if row is None:
                self.DataContext.show_error("Select a function row first.")
                return

            current = context.color_map.get(row.name_text, (200, 200, 200))
            dialog = WinForms.ColorDialog()
            dialog.FullOpen = True
            dialog.Color = Drawing.Color.FromArgb(
                current[0], current[1], current[2]
            )
            if dialog.ShowDialog() != WinForms.DialogResult.OK:
                return

            rgb = (dialog.Color.R, dialog.Color.G, dialog.Color.B)
            context.color_map[row.name_text] = rgb
            row.swatch = to_brush(rgb)
            self.DataContext.clear_banner()
            context.request(LEVEL_DRAW)
        except Exception as ex:
            self.DataContext.show_error("Color change failed: {}".format(ex))

    def show_all_click(self, sender, e):
        self._set_all_visible(True)

    def hide_all_click(self, sender, e):
        self._set_all_visible(False)

    def _set_all_visible(self, state):
        try:
            for row in self.DataContext.all_rows():
                row.is_visible = state
            context.request(LEVEL_DRAW)
        except Exception as ex:
            self.DataContext.show_error("Toggle failed: {}".format(ex))

    def reset_palette_click(self, sender, e):
        try:
            rows = self.DataContext.all_rows()
            for index, row in enumerate(rows):
                rgb = palette_color(index)
                context.color_map[row.name_text] = rgb
                row.swatch = to_brush(rgb)
            self.DataContext.clear_banner()
            context.request(LEVEL_DRAW)
        except Exception as ex:
            self.DataContext.show_error("Reset failed: {}".format(ex))

    def refresh_click(self, sender, e):
        self.DataContext.clear_banner()
        context.request(LEVEL_FULL)


# ---------------------------------------------------------------------------
# Module-level helpers used from inside the Revit API context
# ---------------------------------------------------------------------------
def refresh_active_view():
    try:
        revit.uidoc.RefreshActiveView()
    except Exception as ex:
        logger.debug("Refresh failed: {}".format(ex))


def _on_close_cleanup():
    """Deferred teardown, in a valid Revit API context.

    Order matters:
    1. Unregister event handlers, using the stored exec id.
    2. Remove the DC3D server, which stops render-thread calls.
    3. Refresh the view to clear stale rendering.
    4. Clear the window envvar last, so the guard blocks re-entry until
       everything above has finished.
    """
    try:
        stored_exec_id = script.get_envvar(SHAFTS_EXECID_KEY)
        if stored_exec_id:
            events.unregister_exec_handlers(stored_exec_id)
            script.set_envvar(SHAFTS_EXECID_KEY, None)
    except Exception as ex:
        logger.error("Error stopping events: {}".format(ex))
    try:
        server.remove_server()
        server.meshes = []
    except Exception as ex:
        logger.error("Error removing DC3D server: {}".format(ex))
    try:
        revit.uidoc.RefreshActiveView()
    except Exception as ex:
        logger.error("Error refreshing view: {}".format(ex))
    script.set_envvar(SHAFTS_WINDOW_KEY, None)


# ---------------------------------------------------------------------------
# Revit event handlers
# ---------------------------------------------------------------------------
@events.handle("view-activated")
def view_activated(sender, args):
    try:
        ctx = CTX[0]
        if ctx is None:
            return
        ctx.active_view = args.CurrentActiveView
    except Exception as ex:
        logger.exception(ex)


@events.handle("selection-changed")
def selection_changed(sender, args):
    try:
        ctx = CTX[0]
        if ctx is None or not ctx.vm.selection_only:
            return
        ids = set()
        for element_id in args.GetSelectedElements():
            ids.add(get_elementid_value(element_id))
        if ids == ctx.selected_ids:
            return
        ctx.selected_ids = ids
        ctx.request(LEVEL_DRAW)
    except Exception as ex:
        logger.exception(ex)


@events.handle("doc-changed")
def doc_changed(sender, args):
    """Turn a Revit edit into the smallest possible rebuild."""
    try:
        ctx = CTX[0]
        if ctx is None:
            return

        changed_doc = args.GetDocument()
        if not ctx.owns_document(changed_doc):
            return

        dirty = {}
        needs_full = False

        for element_id in args.GetDeletedElementIds():
            value = get_elementid_value(element_id)
            if value in ctx.records:
                dirty[value] = element_id

        touched = list(args.GetAddedElementIds()) + list(
            args.GetModifiedElementIds()
        )
        for element_id in touched:
            value = get_elementid_value(element_id)
            if value in ctx.records:
                dirty[value] = element_id
                continue
            element = changed_doc.GetElement(element_id)
            if element is None:
                continue
            if is_shaft(element):
                dirty[value] = element_id
            elif isinstance(element, DB.Level):
                # A moved level shifts every shaft that references it.
                needs_full = True

        if needs_full:
            ctx.request(LEVEL_FULL)
        elif dirty:
            ctx.request(LEVEL_PARTIAL, dirty)
    except Exception as ex:
        logger.exception(ex)


# ---------------------------------------------------------------------------
# Initialization - only ever reached on the first click
# ---------------------------------------------------------------------------
saved_colors, saved_transparency = load_prefs()

server = revit.dc3dserver.Server(register=False)

vm = MainViewModel(saved_transparency)
context = Context(vm, saved_colors)
CTX[0] = context

main_window = MainWindow()
main_window.DataContext = vm

script.set_envvar(SHAFTS_WINDOW_KEY, main_window)
script.set_envvar(SHAFTS_EXECID_KEY, EXEC_PARAMS.exec_id)

main_window.show()

# Seed the first build. Setting active_view schedules a LEVEL_FULL rebuild
# through the external event, so no model reads happen on this thread.
try:
    context.active_view = revit.uidoc.ActiveGraphicalView
except Exception as ex:
    logger.exception(ex)
    vm.show_error("Could not read the active view: {}".format(ex))

context.request(LEVEL_FULL)
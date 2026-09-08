# -*- coding: utf-8 -*-
# Author: Mohamed Bedair
"""3D Room Visualization by Sets (DirectContext3D).

Draws room solids as transient overlay geometry in 3D views, colored by
user-defined Sets. Nothing is written to the model: no DirectShape, no
transaction, no undo entries, no worksets. The geometry is unclickable and
disappears the moment the window is closed.

Sets:
- Check rooms on the left, then "New Set from Checked".
- Sets can be renamed, recolored, deleted, and edited by adding or removing
  checked rooms.
- Membership is exclusive: a room lives in at most one Set, so two colors can
  never fight over the same solid.
- Only rooms belonging to a visible Set are drawn.
- Sets are saved per document and restored on the next run.

REQUIRES in bundle.yaml:

    engine:
      persistent: true
      clean: false
"""

# ---------------------------------------------------------------------------
# Duplicate-window guard -- must run BEFORE any heavy import
# ---------------------------------------------------------------------------
from pyrevit import script

logger = script.get_logger()

WINDOW_KEY = "ROOMS3D_WINDOW"
EXECID_KEY = "ROOMS3D_EXECID"

_existing = script.get_envvar(WINDOW_KEY)
if _existing:
    try:
        if _existing.IsVisible:
            _existing.Activate()
            script.exit()
    except SystemExit:
        raise
    except Exception:
        script.set_envvar(WINDOW_KEY, None)
        script.set_envvar(EXECID_KEY, None)

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
import clr

clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")

import System.Drawing
import System.Windows.Forms as WinForms

from System import TimeSpan
from System.Windows import RoutedEventHandler, Thickness, CornerRadius
from System.Windows import VerticalAlignment, HorizontalAlignment
from System.Windows.Controls import CheckBox, StackPanel, TextBlock, Border, Orientation
from System.Windows.Media import SolidColorBrush
from System.Windows.Media import Color as WpfColor
from System.Windows.Threading import DispatcherTimer

from pyrevit import forms, revit, script, HOST_APP, DB, UI, EXEC_PARAMS
from pyrevit.revit import events
from pyrevit.compat import get_elementid_value_func

get_elementid_value = get_elementid_value_func()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_TRANSPARENCY = 25          # percent

# DirectContext3D vertex colors arrive with red and blue transposed on this
# Revit / pyRevit combination: a pure red (255, 0, 0) renders blue. The WPF
# swatches are unaffected because they go through Color.FromRgb. Set this to
# False if your build renders red as red.
DC3D_SWAP_RED_BLUE = True

# Starting colors for new Sets. Only a convenience -- every Set's color is
# meant to be picked by hand from the color dialog.
STARTER_COLORS = [
    (137, 180, 250),
    (250, 179, 135),
    (166, 227, 161),
    (243, 139, 168),
    (203, 166, 247),
    (249, 226, 175),
    (148, 226, 213),
    (245, 194, 231),
]

# Cap the primitives placed in one DirectContext3D buffer.
MAX_TRIS_PER_MESH = 1500
MAX_LINES_PER_MESH = 3000

PLACEHOLDER = "Search rooms..."

ROOM_CAT_ID = DB.ElementId(DB.BuiltInCategory.OST_Rooms)

# Cached tessellation per room, keyed by ElementId value.
# { id_value: (triangle_vertex_triples, edge_segment_pairs) or None }
ROOM_CACHE = {}

# User-defined Sets, in display order.
SETS = []

# Reverse index: room id value -> RoomSet. Rebuilt after every mutation.
ROOM_TO_SET = {}

# Lazily built per document, since a SpatialElementGeometryCalculator is bound
# to the document it was constructed with.
DOC_STATE = {"hash": None, "calc": None, "key": None}

server = revit.dc3dserver.Server(register=False)

CFG = script.get_config("rooms3d_sets")


# ---------------------------------------------------------------------------
# Document helpers
# ---------------------------------------------------------------------------
def active_doc():
    try:
        return revit.doc
    except Exception:
        return None


def doc_key(document):
    try:
        return document.PathName or document.Title
    except Exception:
        return "unknown"


def get_calculator(document):
    """One SpatialElementGeometryCalculator per document, cached."""
    try:
        current = document.GetHashCode()
    except Exception:
        return None
    if DOC_STATE.get("hash") != current or DOC_STATE.get("calc") is None:
        DOC_STATE["hash"] = current
        DOC_STATE["calc"] = DB.SpatialElementGeometryCalculator(document)
    return DOC_STATE["calc"]


# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------
def dc3d_color(rgb, transparency):
    """Build the ColorWithTransparency handed to DirectContext3D.

    See DC3D_SWAP_RED_BLUE above for why the channels are transposed here and
    nowhere else.
    """
    red, green, blue = int(rgb[0]), int(rgb[1]), int(rgb[2])
    if DC3D_SWAP_RED_BLUE:
        red, blue = blue, red
    return DB.ColorWithTransparency(red, green, blue, transparency)


def wpf_brush(rgb):
    return SolidColorBrush(WpfColor.FromRgb(int(rgb[0]), int(rgb[1]), int(rgb[2])))


def contrast_brush(rgb):
    """Readable text color for a row filled with rgb.

    Set colors are picked by hand and can land anywhere from a pale pastel to
    near-black, so the label has to flip rather than sit at one fixed color.
    """
    luminance = 0.299 * int(rgb[0]) + 0.587 * int(rgb[1]) + 0.114 * int(rgb[2])
    if luminance > 145:
        return SolidColorBrush(WpfColor.FromRgb(22, 22, 22))     # #161616
    return SolidColorBrush(WpfColor.FromRgb(244, 244, 244))      # #F4F4F4


def hex_of(rgb):
    return "#{:02X}{:02X}{:02X}".format(int(rgb[0]), int(rgb[1]), int(rgb[2]))


def pct_to_transparency(pct):
    """UI is 0-100% -- ColorWithTransparency wants 0-255 (0 = fully opaque)."""
    value = int(round(pct * 2.55))
    return max(0, min(255, value))


def pick_color(initial_rgb):
    """Open the system color picker. Returns an (r, g, b) tuple or None."""
    dialog = WinForms.ColorDialog()
    dialog.FullOpen = True
    try:
        dialog.Color = System.Drawing.Color.FromArgb(
            int(initial_rgb[0]), int(initial_rgb[1]), int(initial_rgb[2])
        )
    except Exception:
        pass
    if dialog.ShowDialog() == WinForms.DialogResult.OK:
        return (int(dialog.Color.R), int(dialog.Color.G), int(dialog.Color.B))
    return None


# ---------------------------------------------------------------------------
# Room helpers
# ---------------------------------------------------------------------------
def room_label(room):
    number = room.get_Parameter(DB.BuiltInParameter.ROOM_NUMBER).AsValueString() or "?"
    name = room.get_Parameter(DB.BuiltInParameter.ROOM_NAME).AsValueString() or "Unnamed"
    return u"{} - {}".format(number, name)


def collect_rooms(document):
    rooms = (DB.FilteredElementCollector(document)
             .OfCategory(DB.BuiltInCategory.OST_Rooms)
             .WhereElementIsNotElementType()
             .ToElements())
    # Unplaced rooms have no geometry -- there is nothing to draw for them.
    return [r for r in rooms
            if r.get_Parameter(DB.BuiltInParameter.ROOM_AREA).AsDouble() != 0]


class RoomEntry(object):
    """One row in the left-hand list."""

    def __init__(self, element_id, id_value, label):
        self.element_id = element_id
        self.id_value = id_value
        self.label = label
        self.checkbox = None
        self.row = None        # Border wrapper that carries the Set fill


# ---------------------------------------------------------------------------
# Tessellation -- Solid -> raw vertex data (color-independent, so it caches)
# ---------------------------------------------------------------------------
def tessellate_solid(solid):
    """Return (triangle_vertex_triples, edge_segment_pairs) as plain XYZ.

    DirectContext3D only speaks triangles and line segments, so every face has
    to be triangulated and every edge tessellated up front. The result carries
    no color, which is what lets it survive a palette change untouched, and no
    Revit references, which is what makes it safe for the render thread.
    """
    tris = []
    segs = []

    for face in solid.Faces:
        try:
            mesh = face.Triangulate()
        except Exception:
            continue
        if mesh is None:
            continue
        for i in range(mesh.NumTriangles):
            try:
                mt = mesh.get_Triangle(i)
                tris.append((mt.get_Vertex(0), mt.get_Vertex(1), mt.get_Vertex(2)))
            except Exception:
                continue

    for edge in solid.Edges:
        try:
            pts = list(edge.Tessellate())
        except Exception:
            continue
        for i in range(len(pts) - 1):
            segs.append((pts[i], pts[i + 1]))

    return tris, segs


def get_room_tessellation(document, element_id, id_value):
    """Cached tessellation for one room. Returns None if it has no geometry."""
    if id_value in ROOM_CACHE:
        return ROOM_CACHE[id_value]

    try:
        room = document.GetElement(element_id)
        if room is None or not room.IsValidObject:
            ROOM_CACHE[id_value] = None
            return None
        calculator = get_calculator(document)
        if calculator is None:
            return None
        results = calculator.CalculateSpatialElementGeometry(room)
        solid = results.GetGeometry()
    except Exception as ex:
        logger.debug("No geometry for {}: {}".format(id_value, ex))
        ROOM_CACHE[id_value] = None
        return None

    if solid is None or solid.Volume <= 0:
        ROOM_CACHE[id_value] = None
        return None

    data = tessellate_solid(solid)
    ROOM_CACHE[id_value] = data
    return data


# ---------------------------------------------------------------------------
# Sets
# ---------------------------------------------------------------------------
class RoomSet(object):
    def __init__(self, name, rgb, room_ids=None, visible=True):
        self.name = name
        self.rgb = (int(rgb[0]), int(rgb[1]), int(rgb[2]))
        self.room_ids = set(room_ids or ())
        self.visible = bool(visible)


def reindex_sets():
    """Rebuild the room -> set lookup. Call after any membership change."""
    ROOM_TO_SET.clear()
    for room_set in SETS:
        for id_value in room_set.room_ids:
            ROOM_TO_SET[id_value] = room_set


def set_of_room(id_value):
    return ROOM_TO_SET.get(id_value)


def assign_rooms(target_set, id_values):
    """Move rooms into target_set, removing them from every other Set."""
    for other in SETS:
        if other is target_set:
            continue
        other.room_ids.difference_update(id_values)
    target_set.room_ids.update(id_values)
    reindex_sets()


def unassign_rooms(target_set, id_values):
    target_set.room_ids.difference_update(id_values)
    reindex_sets()


def next_starter_color():
    used = set(rs.rgb for rs in SETS)
    for rgb in STARTER_COLORS:
        if rgb not in used:
            return rgb
    return STARTER_COLORS[len(SETS) % len(STARTER_COLORS)]


def unique_set_name(proposed):
    existing = set(rs.name for rs in SETS)
    if proposed not in existing:
        return proposed
    counter = 2
    while "{} ({})".format(proposed, counter) in existing:
        counter += 1
    return "{} ({})".format(proposed, counter)


# ---------------------------------------------------------------------------
# Set persistence, per document
# ---------------------------------------------------------------------------
def load_sets(document, valid_ids):
    """Restore this document's Sets, dropping rooms that no longer exist."""
    del SETS[:]
    try:
        stored = dict(CFG.get_option("documents", {}))
        entries = stored.get(doc_key(document), [])
    except Exception as ex:
        logger.debug("Could not read saved sets: {}".format(ex))
        entries = []

    for entry in entries:
        try:
            rgb = entry.get("rgb", [200, 200, 200])
            ids = set(int(i) for i in entry.get("rooms", []))
            ids.intersection_update(valid_ids)
            SETS.append(
                RoomSet(
                    entry.get("name", "Set"),
                    rgb,
                    ids,
                    entry.get("visible", True),
                )
            )
        except Exception:
            continue
    reindex_sets()


def save_sets(document, transparency):
    try:
        stored = dict(CFG.get_option("documents", {}))
    except Exception:
        stored = {}
    try:
        stored[doc_key(document)] = [
            {
                "name": rs.name,
                "rgb": [rs.rgb[0], rs.rgb[1], rs.rgb[2]],
                "rooms": sorted(rs.room_ids),
                "visible": rs.visible,
            }
            for rs in SETS
        ]
        CFG.documents = stored
        CFG.transparency = int(transparency)
        script.save_config()
    except Exception as ex:
        logger.debug("Could not save sets: {}".format(ex))


def load_transparency():
    try:
        return max(0, min(100, int(CFG.get_option("transparency",
                                                  DEFAULT_TRANSPARENCY))))
    except Exception:
        return DEFAULT_TRANSPARENCY


# ---------------------------------------------------------------------------
# DirectContext3D drawing
# ---------------------------------------------------------------------------
def chunk_meshes(edge_objects, tri_objects):
    """Several small buffers rather than one oversized one."""
    meshes = []
    tri_batches = (len(tri_objects) + MAX_TRIS_PER_MESH - 1) // MAX_TRIS_PER_MESH
    edge_batches = (len(edge_objects) + MAX_LINES_PER_MESH - 1) // MAX_LINES_PER_MESH
    for i in range(max(tri_batches, edge_batches)):
        tris = tri_objects[i * MAX_TRIS_PER_MESH:(i + 1) * MAX_TRIS_PER_MESH]
        edges = edge_objects[i * MAX_LINES_PER_MESH:(i + 1) * MAX_LINES_PER_MESH]
        if not tris and not edges:
            continue
        try:
            meshes.append(revit.dc3dserver.Mesh(edges, tris))
        except Exception as ex:
            logger.debug("Mesh chunk skipped: {}".format(ex))
    return meshes


def build_all_meshes(document, entries_by_id, transparency_pct):
    """Turn every visible Set's cached tessellation into dc3dserver objects.

    Returns (meshes, drawn_count, skipped_count).
    """
    face_trans = pct_to_transparency(transparency_pct)
    # Keep outlines noticeably crisper than the fill so rooms stay readable.
    edge_trans = max(0, face_trans - 80)

    calc_normal = revit.dc3dserver.Mesh.calculate_triangle_normal
    meshes = []
    drawn = 0
    skipped = 0

    for room_set in SETS:
        if not room_set.visible or not room_set.room_ids:
            continue

        face_color = dc3d_color(room_set.rgb, face_trans)
        edge_color = dc3d_color(room_set.rgb, edge_trans)

        tri_objects = []
        edge_objects = []

        for id_value in room_set.room_ids:
            entry = entries_by_id.get(id_value)
            if entry is None:
                continue
            data = get_room_tessellation(document, entry.element_id, id_value)
            if data is None:
                skipped += 1
                continue

            tris, segs = data
            for a, b, c in tris:
                try:
                    tri_objects.append(
                        revit.dc3dserver.Triangle(
                            a, b, c, calc_normal(a, b, c), face_color
                        )
                    )
                except Exception:
                    continue
            for a, b in segs:
                try:
                    edge_objects.append(revit.dc3dserver.Edge(a, b, edge_color))
                except Exception:
                    continue
            drawn += 1

        meshes.extend(chunk_meshes(edge_objects, tri_objects))

    return meshes, drawn, skipped


def push_meshes(meshes):
    """Swap the mesh set safely.

    remove_server() FIRST: Revit's draw thread runs concurrently and reads the
    mesh list. Mutating it while the server is registered is a hard crash, not
    a catchable exception.
    """
    try:
        server.remove_server()
    except Exception:
        pass

    server.meshes = meshes

    if meshes:
        try:
            server.add_server()
        except Exception as ex:
            logger.error("Error adding DC3D server: {}".format(ex))

    refresh_active_view()


def refresh_active_view():
    """Must run in a valid Revit API context -- unregistering alone leaves the
    last painted frame on screen until something forces a redraw."""
    try:
        revit.uidoc.RefreshActiveView()
    except Exception as ex:
        logger.debug("Refresh failed: {}".format(ex))


def clear_overlay():
    try:
        server.remove_server()
    except Exception:
        pass
    server.meshes = []
    refresh_active_view()


# ---------------------------------------------------------------------------
# Teardown
# ---------------------------------------------------------------------------
def _on_close_cleanup():
    """Deferred cleanup in a valid API context. Order matters:
    unregister handlers -> remove server -> refresh -> release the window key.
    """
    try:
        stored_exec_id = script.get_envvar(EXECID_KEY)
        if stored_exec_id:
            events.unregister_exec_handlers(stored_exec_id)
            script.set_envvar(EXECID_KEY, None)
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

    script.set_envvar(WINDOW_KEY, None)


# ---------------------------------------------------------------------------
# XAML -- Catppuccin Mocha
# ---------------------------------------------------------------------------
XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="3D Room Visualization - Sets"
        Height="700" Width="920" MinHeight="600" MinWidth="820"
        WindowStartupLocation="CenterScreen"
        Background="#161616" Foreground="#F4F4F4"
        FontFamily="Segoe UI" FontSize="12"
        ShowInTaskbar="True">

  <Window.Resources>
    <Style x:Key="SectionLabel" TargetType="TextBlock">
      <Setter Property="Foreground" Value="#A8A8A8"/>
      <Setter Property="FontWeight" Value="Bold"/>
      <Setter Property="FontSize" Value="11"/>
      <Setter Property="Margin" Value="0,0,0,6"/>
    </Style>

    <Style x:Key="FlatButton" TargetType="Button">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Background" Value="#525252"/>
      <Setter Property="BorderBrush" Value="#525252"/>
      <Setter Property="Padding" Value="10,6"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="bd"
                    Background="{TemplateBinding Background}"
                    BorderBrush="{TemplateBinding BorderBrush}"
                    BorderThickness="1" CornerRadius="4">
              <ContentPresenter HorizontalAlignment="Center"
                                VerticalAlignment="Center"
                                Margin="{TemplateBinding Padding}"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="bd" Property="Background" Value="#6F6F6F"/>
              </Trigger>
              <Trigger Property="IsEnabled" Value="False">
                <Setter TargetName="bd" Property="Opacity" Value="0.5"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="AccentButton" TargetType="Button"
           BasedOn="{StaticResource FlatButton}">
      <Setter Property="Background" Value="#F1C21B"/>
      <Setter Property="BorderBrush" Value="#F1C21B"/>
      <Setter Property="Foreground" Value="#161616"/>
      <Setter Property="FontWeight" Value="Bold"/>
    </Style>

    <Style x:Key="DangerButton" TargetType="Button"
           BasedOn="{StaticResource FlatButton}">
      <Setter Property="Foreground" Value="#FF8389"/>
    </Style>
  </Window.Resources>

  <Grid Margin="16">
    <Grid.ColumnDefinitions>
      <ColumnDefinition Width="*"/>
      <ColumnDefinition Width="16"/>
      <ColumnDefinition Width="380"/>
    </Grid.ColumnDefinitions>
    <Grid.RowDefinitions>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <!-- LEFT: room list -->
    <DockPanel Grid.Column="0" Grid.Row="0">
      <TextBlock DockPanel.Dock="Top" Text="ROOMS"
                 Style="{StaticResource SectionLabel}"/>
      <TextBox x:Name="search_box" DockPanel.Dock="Top"
               Height="28" Padding="6,4" Margin="0,0,0,8"
               Background="#393939" Foreground="#F4F4F4"
               CaretBrush="#F4F4F4" BorderBrush="#525252" BorderThickness="1"/>
      <Grid DockPanel.Dock="Bottom" Margin="0,8,0,0">
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="Auto"/>
          <ColumnDefinition Width="8"/>
          <ColumnDefinition Width="Auto"/>
          <ColumnDefinition Width="*"/>
        </Grid.ColumnDefinitions>
        <Button x:Name="btn_all" Grid.Column="0" Content="Check All"
                Width="100" Style="{StaticResource FlatButton}"/>
        <Button x:Name="btn_none" Grid.Column="2" Content="Uncheck All"
                Width="100" Style="{StaticResource FlatButton}"/>
        <TextBlock x:Name="lbl_count" Grid.Column="3"
                   Foreground="#A8A8A8" FontSize="11"
                   VerticalAlignment="Center" TextAlignment="Right"/>
      </Grid>
      <ListBox x:Name="room_list"
               Background="#393939" Foreground="#F4F4F4"
               BorderBrush="#525252" BorderThickness="1"
               ScrollViewer.HorizontalScrollBarVisibility="Disabled">
        <ListBox.ItemContainerStyle>
          <Style TargetType="ListBoxItem">
            <Setter Property="Padding" Value="0"/>
            <Setter Property="Margin" Value="0,0,0,2"/>
            <Setter Property="HorizontalContentAlignment" Value="Stretch"/>
            <!-- No selection or hover chrome: the row fill is the Set color,
                 and a highlight painted over it would misread as membership. -->
            <Setter Property="Template">
              <Setter.Value>
                <ControlTemplate TargetType="ListBoxItem">
                  <ContentPresenter HorizontalAlignment="Stretch"/>
                </ControlTemplate>
              </Setter.Value>
            </Setter>
          </Style>
        </ListBox.ItemContainerStyle>
      </ListBox>
    </DockPanel>

    <!-- RIGHT: sets and appearance -->
    <DockPanel Grid.Column="2" Grid.Row="0">
      <TextBlock DockPanel.Dock="Top" Text="SETS"
                 Style="{StaticResource SectionLabel}"/>

      <Border DockPanel.Dock="Bottom" Background="#262626" CornerRadius="4"
              Padding="10" Margin="0,14,0,0">
        <TextBlock x:Name="lbl_status" Foreground="#A8A8A8" FontSize="11"
                   TextWrapping="Wrap" Text=""/>
      </Border>

      <StackPanel DockPanel.Dock="Bottom" Margin="0,16,0,0">
        <Grid>
          <TextBlock Text="TRANSPARENCY" Style="{StaticResource SectionLabel}"
                     HorizontalAlignment="Left"/>
          <TextBlock x:Name="lbl_trans_value" Text="25%" FontFamily="Consolas"
                     FontWeight="Bold" Foreground="#F4F4F4"
                     HorizontalAlignment="Right" Margin="0,-2,0,0"/>
        </Grid>
        <Slider x:Name="slider" Minimum="0" Maximum="100" Value="25"
                TickFrequency="10" IsSnapToTickEnabled="False"
                SmallChange="1" LargeChange="10" Margin="0,2,0,0"/>
      </StackPanel>

      <StackPanel DockPanel.Dock="Bottom" Margin="0,10,0,0">
        <Button x:Name="btn_new_set" Content="New Set from Checked Rooms"
                Height="30" Style="{StaticResource AccentButton}"/>
        <StackPanel Orientation="Horizontal" Margin="0,6,0,0">
          <Button x:Name="btn_rename" Content="Rename" Width="118"
                  Margin="0,0,6,0" Style="{StaticResource FlatButton}"/>
          <Button x:Name="btn_color" Content="Color" Width="118"
                  Margin="0,0,6,0" Style="{StaticResource FlatButton}"/>
          <Button x:Name="btn_delete" Content="Delete" Width="118"
                  Style="{StaticResource DangerButton}"/>
        </StackPanel>
        <StackPanel Orientation="Horizontal" Margin="0,6,0,0">
          <Button x:Name="btn_add" Content="Add Checked" Width="182"
                  Margin="0,0,6,0" Style="{StaticResource FlatButton}"/>
          <Button x:Name="btn_remove" Content="Remove Checked" Width="182"
                  Style="{StaticResource FlatButton}"/>
        </StackPanel>
        <Button x:Name="btn_check_members" Content="Check This Set's Rooms"
                Margin="0,6,0,0" Style="{StaticResource FlatButton}"/>
      </StackPanel>

      <ListBox x:Name="sets_list"
               Background="#393939" Foreground="#F4F4F4"
               BorderBrush="#525252" BorderThickness="1"
               ScrollViewer.HorizontalScrollBarVisibility="Disabled">
        <ListBox.ItemContainerStyle>
          <Style TargetType="ListBoxItem">
            <Setter Property="Background" Value="Transparent"/>
            <Setter Property="Padding" Value="4,3"/>
          </Style>
        </ListBox.ItemContainerStyle>
      </ListBox>
    </DockPanel>

    <!-- BOTTOM -->
    <StackPanel Grid.Column="0" Grid.ColumnSpan="3" Grid.Row="1"
                Orientation="Horizontal" HorizontalAlignment="Right"
                Margin="0,16,0,0">
      <Button x:Name="btn_reload" Content="Reload Rooms" Width="120"
              Style="{StaticResource FlatButton}" Margin="0,0,8,0"/>
      <Button x:Name="btn_close" Content="Close" Width="90"
              Style="{StaticResource FlatButton}"/>
    </StackPanel>
  </Grid>
</Window>
"""


# ---------------------------------------------------------------------------
# Window
# ---------------------------------------------------------------------------
class RoomVizWindow(forms.WPFWindow):
    def __init__(self):
        forms.WPFWindow.__init__(self, XAML, literal_string=True)

        for name in ("search_box", "room_list", "btn_all", "btn_none",
                     "lbl_count", "sets_list", "btn_new_set", "btn_rename",
                     "btn_color", "btn_delete", "btn_add", "btn_remove",
                     "btn_check_members", "slider", "lbl_trans_value",
                     "lbl_status", "btn_reload", "btn_close"):
            setattr(self, name, self.FindName(name))

        # State -- mutable containers, no nonlocal in IronPython 2.7
        self._entries = []             # RoomEntry, sorted by label
        self._by_id = {}               # id_value -> RoomEntry
        self._suppress = [False]       # blocks redraws during bulk operations
        self._drawing = [False]        # an external event is already queued
        self._default_fg = self.room_list.Foreground

        # Debounce: slider drags fire continuously, so coalesce into one redraw
        self._timer = DispatcherTimer()
        self._timer.Interval = TimeSpan.FromMilliseconds(120)
        self._timer.Tick += self.on_timer_tick

        # Wiring
        self.search_box.TextChanged += self.on_search_changed
        self.search_box.GotFocus += self.on_search_enter
        self.search_box.LostFocus += self.on_search_leave
        self.btn_all.Click += RoutedEventHandler(self.on_check_all)
        self.btn_none.Click += RoutedEventHandler(self.on_uncheck_all)
        self.btn_new_set.Click += RoutedEventHandler(self.on_new_set)
        self.btn_rename.Click += RoutedEventHandler(self.on_rename_set)
        self.btn_color.Click += RoutedEventHandler(self.on_recolor_set)
        self.btn_delete.Click += RoutedEventHandler(self.on_delete_set)
        self.btn_add.Click += RoutedEventHandler(self.on_add_checked)
        self.btn_remove.Click += RoutedEventHandler(self.on_remove_checked)
        self.btn_check_members.Click += RoutedEventHandler(self.on_check_members)
        self.btn_reload.Click += RoutedEventHandler(self.on_reload)
        self.btn_close.Click += RoutedEventHandler(self.on_close_click)
        self.slider.ValueChanged += self.on_slider_change
        self.Closed += self.window_closed

        self.reset_search()
        self.slider.Value = load_transparency()
        self.lbl_trans_value.Text = "{}%".format(int(self.slider.Value))

        # Reading the model is safe here: script execution is already inside a
        # valid Revit API context. Later reads go through an ExternalEvent.
        self.load_rooms(restore_sets=True)

        script.restore_window_position(self)
        # The server is registered by the first draw, once it actually holds
        # meshes, so the render thread never sees an empty server.
        self.request_redraw()

    # -- room list ---------------------------------------------------------
    def load_rooms(self, restore_sets=False):
        document = active_doc()
        if document is None:
            return

        # A rebuild must not silently discard what the user has checked,
        # because doc-changed can trigger one mid-edit.
        previously_checked = set(
            e.id_value for e in self._entries if e.checkbox.IsChecked
        )

        self._entries = []
        self._by_id = {}

        for room in collect_rooms(document):
            id_value = get_elementid_value(room.Id)
            entry = RoomEntry(room.Id, id_value, room_label(room))
            checkbox = CheckBox()
            checkbox.Content = entry.label
            checkbox.Foreground = self._default_fg
            checkbox.Tag = entry
            # Set the state BEFORE wiring handlers, so restoring it is silent.
            checkbox.IsChecked = id_value in previously_checked
            checkbox.Checked += self.on_item_toggled
            checkbox.Unchecked += self.on_item_toggled
            # Stretch so a click anywhere along the row toggles the box.
            checkbox.HorizontalAlignment = HorizontalAlignment.Stretch
            checkbox.HorizontalContentAlignment = HorizontalAlignment.Left
            checkbox.VerticalContentAlignment = VerticalAlignment.Center

            # A CheckBox's own Background paints only the little square, so the
            # row fill has to live on a wrapping Border.
            row = Border()
            row.CornerRadius = CornerRadius(3)
            row.Padding = Thickness(6, 3, 6, 3)
            row.Child = checkbox

            entry.checkbox = checkbox
            entry.row = row
            self._entries.append(entry)
            self._by_id[id_value] = entry

        self._entries.sort(key=lambda e: e.label)

        if restore_sets:
            load_sets(document, set(self._by_id.keys()))
        else:
            # Drop rooms that vanished from the model.
            valid = set(self._by_id.keys())
            for room_set in SETS:
                room_set.room_ids.intersection_update(valid)
            reindex_sets()

        DOC_STATE["key"] = doc_key(document)
        self.populate_room_list()
        self.refresh_sets_list()

    def visible_entries(self):
        query = self.current_query().lower()
        return [e for e in self._entries if query in e.label.lower()]

    def populate_room_list(self):
        self.room_list.Items.Clear()
        for entry in self.visible_entries():
            self.room_list.Items.Add(entry.row)
        self.decorate_rooms()
        self.update_count()

    def decorate_rooms(self):
        """Fill each row with its Set color, label included."""
        for entry in self._entries:
            room_set = set_of_room(entry.id_value)
            if room_set is None:
                entry.checkbox.Content = entry.label
                entry.checkbox.Foreground = self._default_fg
                entry.row.Background = None
            else:
                entry.checkbox.Content = u"{}   [{}]".format(
                    entry.label, room_set.name
                )
                entry.row.Background = wpf_brush(room_set.rgb)
                entry.checkbox.Foreground = contrast_brush(room_set.rgb)

    def current_query(self):
        text = self.search_box.Text or ""
        return "" if text == PLACEHOLDER else text

    def checked_ids(self):
        return set(e.id_value for e in self._entries if e.checkbox.IsChecked)

    def update_count(self):
        assigned = len(ROOM_TO_SET)
        self.lbl_count.Text = "{} checked  |  {} of {} in a Set".format(
            len(self.checked_ids()), assigned, len(self._entries)
        )

    # -- sets list ---------------------------------------------------------
    def refresh_sets_list(self):
        previous = self.selected_set()
        self.sets_list.Items.Clear()

        for room_set in SETS:
            row = StackPanel()
            row.Orientation = Orientation.Horizontal
            row.Tag = room_set

            visible_box = CheckBox()
            visible_box.IsChecked = room_set.visible
            visible_box.Tag = room_set
            visible_box.VerticalAlignment = VerticalAlignment.Center
            visible_box.Margin = Thickness(0, 0, 8, 0)
            visible_box.Checked += self.on_set_visibility
            visible_box.Unchecked += self.on_set_visibility
            row.Children.Add(visible_box)

            swatch = Border()
            swatch.Width = 15
            swatch.Height = 15
            swatch.CornerRadius = CornerRadius(3)
            swatch.Background = wpf_brush(room_set.rgb)
            swatch.Margin = Thickness(0, 0, 8, 0)
            swatch.VerticalAlignment = VerticalAlignment.Center
            row.Children.Add(swatch)

            name_block = TextBlock()
            name_block.Text = room_set.name
            name_block.Foreground = self._default_fg
            name_block.VerticalAlignment = VerticalAlignment.Center
            row.Children.Add(name_block)

            count_block = TextBlock()
            count_block.Text = u"   ({} rooms)".format(len(room_set.room_ids))
            count_block.Foreground = wpf_brush((166, 173, 200))
            count_block.FontSize = 11
            count_block.VerticalAlignment = VerticalAlignment.Center
            row.Children.Add(count_block)

            self.sets_list.Items.Add(row)

        # Restore selection on the same Set object where possible.
        if previous is not None:
            for item in self.sets_list.Items:
                if item.Tag is previous:
                    self.sets_list.SelectedItem = item
                    break
        elif self.sets_list.Items.Count:
            self.sets_list.SelectedIndex = 0

        self.decorate_rooms()
        self.update_count()

    def selected_set(self):
        item = self.sets_list.SelectedItem
        if item is None:
            return None
        try:
            return item.Tag
        except Exception:
            return None

    def require_set(self):
        room_set = self.selected_set()
        if room_set is None:
            self.lbl_status.Text = "Select a Set in the list first."
        return room_set

    # -- search ------------------------------------------------------------
    def reset_search(self):
        self.search_box.Text = PLACEHOLDER

    def on_search_enter(self, sender, args):
        if self.search_box.Text == PLACEHOLDER:
            self.search_box.Text = ""

    def on_search_leave(self, sender, args):
        if not (self.search_box.Text or "").strip():
            self.search_box.Text = PLACEHOLDER

    def on_search_changed(self, sender, args):
        self.populate_room_list()

    # -- room checking -----------------------------------------------------
    def on_item_toggled(self, sender, args):
        if not self._suppress[0]:
            self.update_count()

    def _set_visible_checked(self, state):
        self._suppress[0] = True
        try:
            for entry in self.visible_entries():
                entry.checkbox.IsChecked = state
        finally:
            self._suppress[0] = False
        self.update_count()

    def uncheck_everything(self):
        """Clear every room, including any hidden by the current search.

        Iterating room_list.Items would only reach the filtered rows, which is
        exactly how stale checks survive into the next Set.
        """
        self._suppress[0] = True
        try:
            for entry in self._entries:
                entry.checkbox.IsChecked = False
        finally:
            self._suppress[0] = False
        self.update_count()

    def on_check_all(self, sender, args):
        # Deliberately filtered: search, then Check All, is a useful way to
        # gather a Set.
        self._set_visible_checked(True)

    def on_uncheck_all(self, sender, args):
        self.uncheck_everything()

    def on_check_members(self, sender, args):
        room_set = self.require_set()
        if room_set is None:
            return
        self._suppress[0] = True
        try:
            for entry in self._entries:
                entry.checkbox.IsChecked = entry.id_value in room_set.room_ids
        finally:
            self._suppress[0] = False
        self.update_count()
        self.lbl_status.Text = "Checked the {} room(s) in [{}].".format(
            len(room_set.room_ids), room_set.name
        )

    # -- set commands ------------------------------------------------------
    def on_new_set(self, sender, args):
        ids = self.checked_ids()
        if not ids:
            self.lbl_status.Text = "Check some rooms first, then create a Set."
            return

        name = forms.ask_for_string(
            default="Set {}".format(len(SETS) + 1),
            prompt="Name for the new Set:",
            title="New Set",
        )
        if not name:
            return
        name = unique_set_name(name.strip())

        rgb = pick_color(next_starter_color())
        if rgb is None:
            rgb = next_starter_color()

        room_set = RoomSet(name, rgb)
        SETS.append(room_set)
        assign_rooms(room_set, ids)

        # Start clean for the next Set, otherwise these rooms get swept into
        # it the moment the user checks a few more and creates again.
        self.uncheck_everything()

        self.refresh_sets_list()
        self.select_set(room_set)
        self.persist()
        self.request_redraw()
        self.lbl_status.Text = u"Created [{}] with {} room(s). " \
                               u"Selection cleared.".format(name, len(ids))

    def on_rename_set(self, sender, args):
        room_set = self.require_set()
        if room_set is None:
            return
        name = forms.ask_for_string(
            default=room_set.name, prompt="New name:", title="Rename Set"
        )
        if not name or not name.strip():
            return
        old = room_set.name
        candidate = name.strip()
        if candidate != old:
            room_set.name = unique_set_name(candidate)
        self.refresh_sets_list()
        self.select_set(room_set)
        self.persist()
        self.lbl_status.Text = u"Renamed [{}] to [{}].".format(old, room_set.name)

    def on_recolor_set(self, sender, args):
        room_set = self.require_set()
        if room_set is None:
            return
        rgb = pick_color(room_set.rgb)
        if rgb is None:
            return
        room_set.rgb = rgb
        self.refresh_sets_list()
        self.select_set(room_set)
        self.persist()
        self.request_redraw()
        self.lbl_status.Text = u"[{}] is now {}.".format(
            room_set.name, hex_of(rgb)
        )

    def on_delete_set(self, sender, args):
        room_set = self.require_set()
        if room_set is None:
            return
        confirmed = forms.alert(
            u"Delete the Set [{}]?\n\n{} room(s) will become unassigned and "
            u"stop being drawn. The rooms themselves are untouched.".format(
                room_set.name, len(room_set.room_ids)
            ),
            title="Delete Set",
            ok=False,
            yes=True,
            no=True,
        )
        if not confirmed:
            return
        name = room_set.name
        SETS.remove(room_set)
        reindex_sets()
        self.refresh_sets_list()
        self.persist()
        self.request_redraw()
        self.lbl_status.Text = u"Deleted [{}].".format(name)

    def on_add_checked(self, sender, args):
        room_set = self.require_set()
        if room_set is None:
            return
        ids = self.checked_ids()
        if not ids:
            self.lbl_status.Text = "Check the rooms you want to add first."
            return

        moved = len([i for i in ids
                     if set_of_room(i) is not None and set_of_room(i) is not room_set])
        before = len(room_set.room_ids)
        assign_rooms(room_set, ids)
        added = len(room_set.room_ids) - before

        self.refresh_sets_list()
        self.select_set(room_set)
        self.persist()
        self.request_redraw()
        message = u"Added {} room(s) to [{}].".format(added, room_set.name)
        if moved:
            message += " {} moved out of another Set.".format(moved)
        self.lbl_status.Text = message

    def on_remove_checked(self, sender, args):
        room_set = self.require_set()
        if room_set is None:
            return
        ids = self.checked_ids()
        if not ids:
            self.lbl_status.Text = "Check the rooms you want to remove first."
            return

        before = len(room_set.room_ids)
        unassign_rooms(room_set, ids)
        removed = before - len(room_set.room_ids)

        self.refresh_sets_list()
        self.select_set(room_set)
        self.persist()
        self.request_redraw()
        self.lbl_status.Text = u"Removed {} room(s) from [{}].".format(
            removed, room_set.name
        )

    def on_set_visibility(self, sender, args):
        try:
            room_set = sender.Tag
            room_set.visible = bool(sender.IsChecked)
            self.persist()
            self.request_redraw()
        except Exception as ex:
            logger.exception(ex)

    def select_set(self, room_set):
        for item in self.sets_list.Items:
            if item.Tag is room_set:
                self.sets_list.SelectedItem = item
                return

    # -- appearance --------------------------------------------------------
    def on_slider_change(self, sender, args):
        self.lbl_trans_value.Text = "{}%".format(int(self.slider.Value))
        self.request_redraw()

    def on_reload(self, sender, args):
        events.execute_in_revit_context(self._do_reload)

    def _do_reload(self):
        try:
            ROOM_CACHE.clear()
            self.load_rooms(restore_sets=False)
            self.redraw_now()
        except Exception as ex:
            logger.exception(ex)
            self.lbl_status.Text = "Reload failed: {}".format(ex)

    def persist(self):
        document = active_doc()
        if document is not None:
            save_sets(document, int(self.slider.Value))

    # -- redraw ------------------------------------------------------------
    def request_redraw(self):
        """Coalesce rapid UI changes into a single geometry rebuild."""
        self._timer.Stop()
        self._timer.Start()

    def on_timer_tick(self, sender, args):
        self._timer.Stop()
        if self._drawing[0]:
            # An external event is still pending; try again shortly.
            self._timer.Start()
            return
        self._drawing[0] = True
        try:
            # Every model read and every server call happens inside a valid
            # Revit API context, never straight off a WPF handler.
            events.execute_in_revit_context(self.redraw_now)
        except Exception as ex:
            self._drawing[0] = False
            logger.exception(ex)

    def redraw_now(self):
        self._drawing[0] = False
        document = active_doc()
        if document is None:
            return
        try:
            meshes, drawn, skipped = build_all_meshes(
                document, self._by_id, int(self.slider.Value)
            )
            if meshes:
                try:
                    server.uidoc = UI.UIDocument(document)
                except Exception:
                    pass
                push_meshes(meshes)
            else:
                clear_overlay()
            self.update_status(drawn, skipped)
        except Exception as ex:
            logger.exception(ex)
            self.lbl_status.Text = "Error: {}".format(ex)

    def update_status(self, drawn=0, skipped=0):
        parts = []
        try:
            view = revit.uidoc.ActiveGraphicalView
            if view is None or view.ViewType != DB.ViewType.ThreeD:
                parts.append(
                    "Active view is not 3D. The overlay only renders in 3D views."
                )
        except Exception:
            pass

        if not SETS:
            parts.append(
                "No Sets yet. Check rooms on the left, then "
                "'New Set from Checked Rooms'."
            )
        else:
            hidden = len([s for s in SETS if not s.visible])
            parts.append("{} room(s) drawn across {} Set(s).".format(
                drawn, len(SETS) - hidden
            ))
            if hidden:
                parts.append("{} Set(s) hidden.".format(hidden))
            if skipped:
                parts.append("{} skipped (no geometry).".format(skipped))

        parts.append("Geometry is view-only: not selectable, not in the model.")
        self.lbl_status.Text = "\n".join(parts)

    # -- lifecycle ---------------------------------------------------------
    def on_close_click(self, sender, args):
        self.Close()

    def window_closed(self, sender, args):
        try:
            self._timer.Stop()
        except Exception:
            pass
        try:
            self.persist()
        except Exception as ex:
            logger.debug("Could not save sets on close: {}".format(ex))
        script.save_window_position(self)
        # WPF events fire outside a valid Revit API context -- marshal cleanup
        # onto Revit's main thread via an ExternalEvent.
        events.execute_in_revit_context(_on_close_cleanup)


# ---------------------------------------------------------------------------
# Live-update handlers -- reached only on the first click
# ---------------------------------------------------------------------------
@events.handle("view-activated")
def view_activated(sender, args):
    try:
        document = args.CurrentActiveView.Document
        server.uidoc = UI.UIDocument(document)

        # Switching documents means a different room list and a different
        # saved Set collection.
        if doc_key(document) != DOC_STATE.get("key"):
            ROOM_CACHE.clear()
            main_window.load_rooms(restore_sets=True)
            main_window.request_redraw()
        else:
            main_window.update_status()
    except Exception as ex:
        logger.exception(ex)


@events.handle("doc-changed")
def doc_changed(sender, args):
    """Room edits invalidate the cached tessellation for those rooms only."""
    try:
        changed_doc = args.GetDocument()
        dirty = False
        structural = False

        def is_room(element_id):
            """Only ask the document about ids we don't already know."""
            try:
                element = changed_doc.GetElement(element_id)
                return (element is not None
                        and element.Category is not None
                        and element.Category.Id == ROOM_CAT_ID)
            except Exception:
                return False

        for element_id in list(args.GetModifiedElementIds()):
            key = get_elementid_value(element_id)
            if key in ROOM_CACHE:
                del ROOM_CACHE[key]
                dirty = True
            elif key not in main_window._by_id and is_room(element_id):
                # An unplaced room that just got placed.
                structural = True

        for element_id in list(args.GetDeletedElementIds()):
            key = get_elementid_value(element_id)
            if key in ROOM_CACHE:
                del ROOM_CACHE[key]
            if key in main_window._by_id:
                structural = True
            room_set = ROOM_TO_SET.get(key)
            if room_set is not None:
                # A deleted room has to leave its Set, or it lingers in the
                # saved data and in the counts forever.
                room_set.room_ids.discard(key)
                structural = True

        for element_id in list(args.GetAddedElementIds()):
            if is_room(element_id):
                structural = True
                break

        if structural:
            reindex_sets()
            main_window.load_rooms(restore_sets=False)
            main_window.request_redraw()
        elif dirty:
            main_window.request_redraw()
    except Exception as ex:
        logger.exception(ex)


# ---------------------------------------------------------------------------
# Launch
# ---------------------------------------------------------------------------
if not collect_rooms(HOST_APP.doc):
    forms.alert("No placed rooms found in the active document.", exitscript=True)

main_window = RoomVizWindow()
script.set_envvar(WINDOW_KEY, main_window)
script.set_envvar(EXECID_KEY, EXEC_PARAMS.exec_id)
main_window.show()
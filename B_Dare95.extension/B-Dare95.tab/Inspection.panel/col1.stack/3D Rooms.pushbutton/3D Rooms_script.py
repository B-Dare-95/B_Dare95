# -*- coding: utf-8 -*-
# Author: Mohamed Bedair
"""3D Room Visualization (DirectContext3D).

Draws room solids as transient overlay geometry in 3D views. Nothing is written
to the model: no DirectShape, no transaction, no undo entries, no worksets. The
geometry is unclickable and disappears the moment the window is closed.

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
from System.Windows import RoutedEventHandler
from System.Windows.Controls import CheckBox
from System.Windows.Media import SolidColorBrush
from System.Windows.Media import Color as WpfColor
from System.Windows.Threading import DispatcherTimer

from pyrevit import forms, revit, script, HOST_APP, DB, UI, EXEC_PARAMS
from pyrevit.revit import events
from pyrevit.compat import get_elementid_value_func

doc = HOST_APP.doc
uidoc = HOST_APP.uidoc

get_elementid_value = get_elementid_value_func()

DEFAULT_RGB = (89, 42, 250)
DEFAULT_TRANSPARENCY = 25          # percent, matches the original default

# Cached tessellation per room, keyed by ElementId value.
# { id_value: (triangle_vertex_triples, edge_segment_pairs) }
ROOM_CACHE = {}

calculator = DB.SpatialElementGeometryCalculator(doc)
server = revit.dc3dserver.Server(register=False)


# ---------------------------------------------------------------------------
# Room helpers
# ---------------------------------------------------------------------------
def room_label(room):
    number = room.get_Parameter(DB.BuiltInParameter.ROOM_NUMBER).AsValueString() or "?"
    name = room.get_Parameter(DB.BuiltInParameter.ROOM_NAME).AsValueString() or "Unnamed"
    is_placed = room.get_Parameter(DB.BuiltInParameter.ROOM_AREA).AsDouble() != 0
    suffix = u"" if is_placed else u"  [\u26a0 Unplaced]"
    return u"{} - {}{}".format(number, name, suffix)


def collect_rooms():
    rooms = (DB.FilteredElementCollector(doc)
             .OfCategory(DB.BuiltInCategory.OST_Rooms)
             .WhereElementIsNotElementType()
             .ToElements())
    # Unplaced rooms have no geometry -- there is nothing to draw for them.
    return [r for r in rooms
            if r.get_Parameter(DB.BuiltInParameter.ROOM_AREA).AsDouble() != 0]


# ---------------------------------------------------------------------------
# Tessellation -- Solid -> raw vertex data (colour-independent, so it caches)
# ---------------------------------------------------------------------------
def tessellate_solid(solid):
    """Return (triangle_vertex_triples, edge_segment_pairs) as plain XYZ.

    DirectContext3D only speaks triangles and line segments, so every face has
    to be triangulated and every edge tessellated up front. The result carries
    no colour, which is what lets it survive a palette change untouched.
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
            mt = mesh.get_Triangle(i)
            tris.append((mt.get_Vertex(0), mt.get_Vertex(1), mt.get_Vertex(2)))

    for edge in solid.Edges:
        try:
            pts = list(edge.Tessellate())
        except Exception:
            continue
        for i in range(len(pts) - 1):
            segs.append((pts[i], pts[i + 1]))

    return tris, segs


def get_room_tessellation(room):
    """Cached tessellation for one room. Returns None if it has no geometry."""
    key = get_elementid_value(room.Id)
    if key in ROOM_CACHE:
        return ROOM_CACHE[key]

    try:
        results = calculator.CalculateSpatialElementGeometry(room)
        solid = results.GetGeometry()
    except Exception as e:
        logger.debug("No geometry for {}: {}".format(room.Id, e))
        ROOM_CACHE[key] = None
        return None

    if solid is None or solid.Volume <= 0:
        ROOM_CACHE[key] = None
        return None

    data = tessellate_solid(solid)
    ROOM_CACHE[key] = data
    return data


# ---------------------------------------------------------------------------
# DirectContext3D drawing
# ---------------------------------------------------------------------------
def pct_to_transparency(pct):
    """UI is 0-100% -- ColorWithTransparency wants 0-255 (0 = fully opaque)."""
    value = int(round(pct * 2.55))
    return max(0, min(255, value))


def build_meshes(rooms, rgb, transparency_pct):
    """Turn cached tessellation + current colour into dc3dserver objects."""
    face_trans = pct_to_transparency(transparency_pct)
    # Keep outlines noticeably crisper than the fill so rooms stay readable.
    edge_trans = max(0, face_trans - 80)

    face_color = DB.ColorWithTransparency(rgb[0], rgb[1], rgb[2], face_trans)
    edge_color = DB.ColorWithTransparency(rgb[0], rgb[1], rgb[2], edge_trans)

    calc_normal = revit.dc3dserver.Mesh.calculate_triangle_normal
    triangles = []
    edges = []
    skipped = []

    for room in rooms:
        if not room.IsValidObject:
            continue
        data = get_room_tessellation(room)
        if data is None:
            skipped.append(room_label(room))
            continue

        tris, segs = data
        for a, b, c in tris:
            triangles.append(
                revit.dc3dserver.Triangle(a, b, c, calc_normal(a, b, c), face_color)
            )
        for a, b in segs:
            edges.append(revit.dc3dserver.Edge(a, b, edge_color))

    return edges, triangles, skipped


def push_to_server(edges, triangles):
    """Swap the mesh set safely.

    remove_server() FIRST: Revit's draw thread runs concurrently and reads the
    mesh list. Mutating it while the server is registered is a hard crash, not
    a catchable exception.
    """
    try:
        server.remove_server()
    except Exception:
        pass

    server.meshes = (
        [revit.dc3dserver.Mesh(edges, triangles)] if (edges or triangles) else []
    )

    if server.meshes:
        try:
            server.add_server()
        except Exception as ex:
            logger.error("Error adding DC3D server: {}".format(ex))

    events.execute_in_revit_context(refresh_active_view)


def refresh_active_view():
    """Must run in a valid Revit API context -- unregistering alone leaves the
    last painted frame on screen until something forces a redraw."""
    try:
        revit.uidoc.RefreshActiveView()
    except Exception as ex:
        logger.exception(ex)


def clear_overlay():
    try:
        server.remove_server()
    except Exception:
        pass
    server.meshes = []
    events.execute_in_revit_context(refresh_active_view)


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
        Title="3D Room Visualization"
        Height="620" Width="720" MinHeight="520" MinWidth="660"
        WindowStartupLocation="CenterScreen"
        Background="#1E1E2E" Foreground="#CDD6F4"
        FontFamily="Segoe UI" FontSize="12"
        ShowInTaskbar="True">

  <Window.Resources>
    <Style x:Key="SectionLabel" TargetType="TextBlock">
      <Setter Property="Foreground" Value="#A6ADC8"/>
      <Setter Property="FontWeight" Value="Bold"/>
      <Setter Property="FontSize" Value="11"/>
      <Setter Property="Margin" Value="0,0,0,6"/>
    </Style>

    <Style x:Key="FlatButton" TargetType="Button">
      <Setter Property="Foreground" Value="#CDD6F4"/>
      <Setter Property="Background" Value="#45475A"/>
      <Setter Property="BorderBrush" Value="#45475A"/>
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
                <Setter TargetName="bd" Property="Background" Value="#585B70"/>
              </Trigger>
              <Trigger Property="IsEnabled" Value="False">
                <Setter TargetName="bd" Property="Opacity" Value="0.5"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="AccentButton" TargetType="Button" BasedOn="{StaticResource FlatButton}">
      <Setter Property="Background" Value="#F0A500"/>
      <Setter Property="BorderBrush" Value="#F0A500"/>
      <Setter Property="Foreground" Value="#1E1E2E"/>
      <Setter Property="FontWeight" Value="Bold"/>
    </Style>
  </Window.Resources>

  <Grid Margin="16">
    <Grid.ColumnDefinitions>
      <ColumnDefinition Width="*"/>
      <ColumnDefinition Width="17"/>
      <ColumnDefinition Width="320"/>
    </Grid.ColumnDefinitions>
    <Grid.RowDefinitions>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <!-- LEFT: room list -->
    <DockPanel Grid.Column="0" Grid.Row="0">
      <TextBlock DockPanel.Dock="Top" Text="ROOMS" Style="{StaticResource SectionLabel}"/>
      <TextBox x:Name="search_box" DockPanel.Dock="Top"
               Height="28" Padding="6,4" Margin="0,0,0,8"
               Background="#313244" Foreground="#CDD6F4"
               CaretBrush="#CDD6F4" BorderBrush="#45475A" BorderThickness="1"/>
      <Grid DockPanel.Dock="Bottom" Margin="0,8,0,0">
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="Auto"/>
          <ColumnDefinition Width="8"/>
          <ColumnDefinition Width="Auto"/>
          <ColumnDefinition Width="*"/>
        </Grid.ColumnDefinitions>
        <Button x:Name="btn_all" Grid.Column="0" Content="Select All"
                Width="100" Style="{StaticResource FlatButton}"/>
        <Button x:Name="btn_none" Grid.Column="2" Content="Select None"
                Width="100" Style="{StaticResource FlatButton}"/>
        <TextBlock x:Name="lbl_count" Grid.Column="3"
                   Foreground="#A6ADC8" FontSize="11"
                   VerticalAlignment="Center" TextAlignment="Right"/>
      </Grid>
      <ListBox x:Name="room_list"
               Background="#313244" Foreground="#CDD6F4"
               BorderBrush="#45475A" BorderThickness="1"
               ScrollViewer.HorizontalScrollBarVisibility="Disabled">
        <ListBox.ItemContainerStyle>
          <Style TargetType="ListBoxItem">
            <Setter Property="Background" Value="Transparent"/>
            <Setter Property="Padding" Value="4,2"/>
          </Style>
        </ListBox.ItemContainerStyle>
      </ListBox>
    </DockPanel>

    <!-- RIGHT: appearance -->
    <StackPanel Grid.Column="2" Grid.Row="0">
      <TextBlock Text="COLOR" Style="{StaticResource SectionLabel}"/>
      <Border x:Name="color_swatch" Height="85" CornerRadius="4"
              Background="#592AFA" Cursor="Hand">
        <TextBlock Text="click to change" Foreground="#CDD6F4" FontSize="11"
                   HorizontalAlignment="Center" VerticalAlignment="Center"/>
      </Border>
      <TextBlock x:Name="lbl_hex" Text="#592AFA" FontFamily="Consolas"
                 Foreground="#A6ADC8" TextAlignment="Center" Margin="0,8,0,0"/>

      <TextBlock Text="TRANSPARENCY" Style="{StaticResource SectionLabel}"
                 Margin="0,22,0,6"/>
      <Grid>
        <TextBlock x:Name="lbl_trans_value" Text="25%" FontFamily="Consolas"
                   FontWeight="Bold" FontSize="14" Foreground="#CDD6F4"
                   HorizontalAlignment="Right" Margin="0,-24,0,0"/>
      </Grid>
      <Slider x:Name="slider" Minimum="0" Maximum="100" Value="25"
              TickFrequency="10" IsSnapToTickEnabled="False"
              SmallChange="1" LargeChange="10" Margin="0,4,0,0"/>
      <Grid>
        <TextBlock Text="0%" Foreground="#A6ADC8" FontSize="11"
                   HorizontalAlignment="Left"/>
        <TextBlock Text="100%" Foreground="#A6ADC8" FontSize="11"
                   HorizontalAlignment="Right"/>
      </Grid>

      <Border Background="#2A2A3C" CornerRadius="4" Padding="10"
              Margin="0,22,0,0">
        <TextBlock x:Name="lbl_status" Foreground="#A6ADC8" FontSize="11"
                   TextWrapping="Wrap" Text=""/>
      </Border>
    </StackPanel>

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
PLACEHOLDER = "Search rooms..."


class RoomVizWindow(forms.WPFWindow):
    def __init__(self):
        forms.WPFWindow.__init__(self, XAML, literal_string=True)

        # Named controls
        for name in ("search_box", "room_list", "btn_all", "btn_none",
                     "lbl_count", "color_swatch", "lbl_hex", "lbl_trans_value",
                     "slider", "lbl_status", "btn_reload", "btn_close"):
            setattr(self, name, self.FindName(name))

        # State -- mutable containers, no nonlocal in IronPython 2.7
        self._rgb = [DEFAULT_RGB[0], DEFAULT_RGB[1], DEFAULT_RGB[2]]
        self._checkboxes = []          # (label, CheckBox, room)
        self._suppress = [False]       # blocks redraws during bulk operations

        # Debounce: slider drags fire continuously, so coalesce into one redraw
        self._timer = DispatcherTimer()
        self._timer.Interval = TimeSpan.FromMilliseconds(120)
        self._timer.Tick += self.on_timer_tick

        # Wiring
        self.search_box.TextChanged += self.on_search_changed
        self.search_box.GotFocus += self.on_search_enter
        self.search_box.LostFocus += self.on_search_leave
        self.btn_all.Click += RoutedEventHandler(self.on_select_all)
        self.btn_none.Click += RoutedEventHandler(self.on_select_none)
        self.btn_reload.Click += RoutedEventHandler(self.on_reload)
        self.btn_close.Click += RoutedEventHandler(self.on_close_click)
        self.color_swatch.MouseLeftButtonUp += self.on_color_click
        self.slider.ValueChanged += self.on_slider_change
        self.Closed += self.window_closed

        self.reset_search()
        self.load_rooms()
        self.apply_color_to_ui()

        script.restore_window_position(self)
        server.add_server()
        self.update_status()

    # -- room list ---------------------------------------------------------
    def load_rooms(self):
        self._checkboxes = []
        rooms = collect_rooms()
        for room in sorted(rooms, key=room_label):
            cb = CheckBox()
            cb.Content = room_label(room)
            cb.Foreground = self.room_list.Foreground
            cb.Checked += self.on_item_toggled
            cb.Unchecked += self.on_item_toggled
            self._checkboxes.append((room_label(room), cb, room))
        self.populate_list()

    def populate_list(self):
        query = self.current_query().lower()
        self.room_list.Items.Clear()
        for label, cb, _ in self._checkboxes:
            if query in label.lower():
                self.room_list.Items.Add(cb)
        self.update_count()

    def current_query(self):
        text = self.search_box.Text or ""
        return "" if text == PLACEHOLDER else text

    def checked_rooms(self):
        return [room for _, cb, room in self._checkboxes if cb.IsChecked]

    def update_count(self):
        self.lbl_count.Text = "{} of {} checked".format(
            len(self.checked_rooms()), len(self._checkboxes)
        )

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
        self.populate_list()

    # -- selection ---------------------------------------------------------
    def on_item_toggled(self, sender, args):
        self.update_count()
        if not self._suppress[0]:
            self.request_redraw()

    def _set_visible_checked(self, state):
        self._suppress[0] = True
        try:
            for item in self.room_list.Items:
                item.IsChecked = state
        finally:
            self._suppress[0] = False
        self.update_count()
        self.request_redraw()

    def on_select_all(self, sender, args):
        self._set_visible_checked(True)

    def on_select_none(self, sender, args):
        self._set_visible_checked(False)

    def on_reload(self, sender, args):
        ROOM_CACHE.clear()
        self.load_rooms()
        self.request_redraw()

    # -- appearance --------------------------------------------------------
    def apply_color_to_ui(self):
        r, g, b = self._rgb
        self.lbl_hex.Text = "#{:02X}{:02X}{:02X}".format(r, g, b)
        self.color_swatch.Background = SolidColorBrush(WpfColor.FromRgb(r, g, b))

    def on_color_click(self, sender, args):
        dlg = WinForms.ColorDialog()
        dlg.FullOpen = True
        dlg.Color = System.Drawing.Color.FromArgb(*self._rgb)
        if dlg.ShowDialog() == WinForms.DialogResult.OK:
            self._rgb = [int(dlg.Color.R), int(dlg.Color.G), int(dlg.Color.B)]
            self.apply_color_to_ui()
            self.request_redraw()

    def on_slider_change(self, sender, args):
        self.lbl_trans_value.Text = "{}%".format(int(self.slider.Value))
        self.request_redraw()

    # -- redraw ------------------------------------------------------------
    def request_redraw(self):
        """Coalesce rapid UI changes into a single geometry rebuild."""
        self._timer.Stop()
        self._timer.Start()

    def on_timer_tick(self, sender, args):
        self._timer.Stop()
        self.redraw()

    def redraw(self):
        rooms = self.checked_rooms()
        if not rooms:
            clear_overlay()
            self.update_status()
            return
        try:
            edges, triangles, skipped = build_meshes(
                rooms, self._rgb, int(self.slider.Value)
            )
            push_to_server(edges, triangles)
            self.update_status(len(rooms) - len(skipped), skipped)
        except Exception as ex:
            logger.exception(ex)
            self.lbl_status.Text = "Error: {}".format(ex)

    def update_status(self, drawn=0, skipped=None):
        parts = []
        try:
            view = revit.uidoc.ActiveGraphicalView
            if view is None or view.ViewType != DB.ViewType.ThreeD:
                parts.append(
                    "Active view is not 3D. The overlay only renders in 3D views."
                )
        except Exception:
            pass
        parts.append("{} room(s) drawn.".format(drawn))
        if skipped:
            parts.append("{} skipped (no geometry).".format(len(skipped)))
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
        server.uidoc = UI.UIDocument(args.CurrentActiveView.Document)
        main_window.update_status()
    except Exception as ex:
        logger.exception(ex)


@events.handle("doc-changed")
def doc_changed(sender, args):
    """Room edits invalidate the cached tessellation for those rooms only."""
    try:
        touched = list(args.GetModifiedElementIds()) + list(
            args.GetDeletedElementIds()
        )
        dirty = False
        for eid in touched:
            key = get_elementid_value(eid)
            if key in ROOM_CACHE:
                del ROOM_CACHE[key]
                dirty = True
        if dirty:
            main_window.request_redraw()
    except Exception as ex:
        logger.exception(ex)


# ---------------------------------------------------------------------------
# Launch
# ---------------------------------------------------------------------------
if not collect_rooms():
    forms.alert("No placed rooms found in the active document.", exitscript=True)

main_window = RoomVizWindow()
script.set_envvar(WINDOW_KEY, main_window)
script.set_envvar(EXECID_KEY, EXEC_PARAMS.exec_id)
main_window.show()
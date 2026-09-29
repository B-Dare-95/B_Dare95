# -*- coding: utf-8 -*-
"""Number stair treads up to the active view's cut plane.

Pick a stair run (active model or linked) in a plan view. Treads are walked
up from the run's base elevation, one riser at a time; every tread is numbered
until the first tread whose top is above the view cut plane - that tread is
the last one numbered. Each number is a TextNote centred inside one
full-circle detail curve. Keep picking runs until Esc.

Numbers follow the stairs' "Tread/Riser Start Number" parameter and continue
through the runs of the same stairs (runs below the picked run are counted).
Bubbles sit on the left or right side of the run (as seen walking up), with
a user offset between the run edge and the bubble edge.
The landing at the top of the picked run counts as a tread and is numbered
too, as long as the walk up hasn't already stopped at the cut plane.
"""
__title__ = "Stair Tread\nNumbering"

import clr
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

import math

from System import EventHandler
from System.Windows import RoutedEventHandler, Visibility
from System.Windows.Controls import (
    TextChangedEventHandler, SelectionChangedEventHandler
)
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Markup import XamlReader
from System.Windows.Threading import Dispatcher, DispatcherFrame

from Autodesk.Revit.DB import (
    Arc, BuiltInCategory, BuiltInParameter, ElementId,
    FilteredElementCollector, GraphicsStyleType, HorizontalTextAlignment,
    Level, PlanViewPlane, RevitLinkInstance, TextNote, TextNoteOptions,
    TextNoteType, Transaction, Transform, UnitTypeId, UnitUtils,
    VerticalTextAlignment, ViewPlan, XYZ
)
from Autodesk.Revit.DB.Architecture import StairsLanding, StairsRun
from Autodesk.Revit.Exceptions import OperationCanceledException
from Autodesk.Revit.UI import TaskDialog
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType

from pyrevit import script


uidoc = __revit__.ActiveUIDocument
doc = uidoc.Document
view = doc.ActiveView
cfg = script.get_config()

TITLE = "Stair Tread Numbering"
TOL = 1e-6
START_NUMBER_PARAM = "Tread/Riser Start Number"
SIDE_LEFT, SIDE_CENTER, SIDE_RIGHT = 1, 0, -1

# System line styles that a detail line cannot use
EXCLUDED_LINE_STYLES = set([
    "<Area Boundary>", "<Room Separation>", "<Space Separation>",
    "<Sketch>", "<Insulation Batting Lines>", "<Path of Travel Lines>",
])


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def eid_int(eid):
    try:
        return eid.Value
    except AttributeError:
        return eid.IntegerValue


def mm_to_ft(v):
    return UnitUtils.ConvertToInternalUnits(v, UnitTypeId.Millimeters)


def ft_to_mm(v):
    return UnitUtils.ConvertFromInternalUnits(v, UnitTypeId.Millimeters)


def type_name(el):
    for bip in (BuiltInParameter.SYMBOL_NAME_PARAM,
                BuiltInParameter.ALL_MODEL_TYPE_NAME):
        p = el.get_Parameter(bip)
        if p is not None and p.AsString():
            return p.AsString()
    return str(eid_int(el.Id))


def cfg_get(name, default):
    value = cfg.get_option(name, default)
    return default if value is None else value


def collect_text_types():
    types = {}
    for t in FilteredElementCollector(doc).OfClass(TextNoteType):
        types[type_name(t)] = t.Id
    return types


def collect_line_styles():
    styles = {}
    lines_cat = doc.Settings.Categories.get_Item(BuiltInCategory.OST_Lines)
    for sub in lines_cat.SubCategories:
        if sub.Name in EXCLUDED_LINE_STYLES:
            continue
        gs = sub.GetGraphicsStyle(GraphicsStyleType.Projection)
        if gs is not None:
            styles[sub.Name] = gs
    return styles


def loaded_links():
    return [li for li in FilteredElementCollector(doc).OfClass(RevitLinkInstance)
            if li.GetLinkDocument() is not None]


def sort_names(names):
    return sorted(names, key=lambda s: s.lower())


def cut_plane_info(v):
    """Level, offset and absolute Z (host internal coords) of the cut plane."""
    vr = v.GetViewRange()
    lid = vr.GetLevelId(PlanViewPlane.CutPlane)
    lvl = doc.GetElement(lid) if lid != ElementId.InvalidElementId else None
    if not isinstance(lvl, Level):
        lvl = v.GenLevel
    off = vr.GetOffset(PlanViewPlane.CutPlane)
    return lvl, off, lvl.ProjectElevation + off


# --------------------------------------------------------------------------
# Selection
# --------------------------------------------------------------------------
class HostRunFilter(ISelectionFilter):
    def AllowElement(self, el):
        return isinstance(el, StairsRun)

    def AllowReference(self, ref, pt):
        return True


class LinkedRunFilter(ISelectionFilter):
    def __init__(self, host_doc):
        self.host_doc = host_doc

    def AllowElement(self, el):
        return isinstance(el, RevitLinkInstance)

    def AllowReference(self, ref, pt):
        link = self.host_doc.GetElement(ref.ElementId)
        if not isinstance(link, RevitLinkInstance):
            return False
        ldoc = link.GetLinkDocument()
        if ldoc is None:
            return False
        return isinstance(ldoc.GetElement(ref.LinkedElementId), StairsRun)


def pick_run(use_link):
    """Returns (run, transform link->host, run's document)."""
    if use_link:
        ref = uidoc.Selection.PickObject(
            ObjectType.LinkedElement, LinkedRunFilter(doc),
            "Pick a LINKED stair run (Tab to cycle, Esc to finish)")
        link = doc.GetElement(ref.ElementId)
        ldoc = link.GetLinkDocument()
        return ldoc.GetElement(ref.LinkedElementId), link.GetTotalTransform(), ldoc
    ref = uidoc.Selection.PickObject(
        ObjectType.Element, HostRunFilter(),
        "Pick a stair run (Tab to cycle, Esc to finish)")
    return doc.GetElement(ref.ElementId), Transform.Identity, doc


# --------------------------------------------------------------------------
# Stair geometry
# --------------------------------------------------------------------------
def stairs_base_z(stairs, sdoc):
    """Absolute base Z of the stairs, in its own document's internal coords."""
    try:
        p_lvl = stairs.get_Parameter(BuiltInParameter.STAIRS_BASE_LEVEL_PARAM)
        p_off = stairs.get_Parameter(BuiltInParameter.STAIRS_BASE_OFFSET)
    except AttributeError:
        p_lvl = p_off = None
    if p_lvl is not None:
        lvl = sdoc.GetElement(p_lvl.AsElementId())
        if isinstance(lvl, Level):
            off = p_off.AsDouble() if p_off is not None else 0.0
            return lvl.ProjectElevation + off
    return stairs.BaseElevation


def path_curves(run):
    curves = [c for c in run.GetStairsPath() if c.Length > TOL]
    if not curves:
        raise ValueError("The run has no stairs path.")
    return curves


def frame_along(curves, dist):
    """Point and horizontal unit tangent at a distance along the path."""
    acc = 0.0
    last = len(curves) - 1
    for i, c in enumerate(curves):
        length = c.Length
        if dist <= acc + length or i == last:
            t = max(0.0, min(1.0, (dist - acc) / length))
            d = c.ComputeDerivatives(t, True)
            tangent = XYZ(d.BasisX.X, d.BasisX.Y, 0.0).Normalize()
            return d.Origin, tangent
        acc += length


def stairs_start_number(stairs):
    """Value of 'Tread/Riser Start Number', or None if not found."""
    p = stairs.LookupParameter(START_NUMBER_PARAM)
    if p is None or not p.HasValue:
        return None
    return p.AsInteger()


def lowest_tread_rel(stairs, sdoc):
    """Height of the stairs' first tread, relative to the stairs base.

    Every run is checked, so the result doesn't depend on run order.
    """
    lowest = None
    for rid in stairs.GetStairsRuns():
        r = sdoc.GetElement(rid)
        if not isinstance(r, StairsRun) or r.ActualRisersNumber < 1:
            continue
        r_riser = (r.TopElevation - r.BaseElevation) / float(r.ActualRisersNumber)
        z = r.BaseElevation + (r_riser if r.BeginsWithRiser else 0.0)
        if lowest is None or z < lowest:
            lowest = z
    return lowest


def treads_to_number(run, transform, sdoc, cut_z, layout):
    """Walk up the run tread by tread; stop after the first tread above cut_z.

    Returns (items, radius, start_found) where items = [(number, host_point)].
    """
    n = run.ActualTreadsNumber
    risers = run.ActualRisersNumber
    if n < 1 or risers < 1:
        raise ValueError("The run reports no treads or risers.")

    stairs = run.GetStairs()
    curves = path_curves(run)
    depth = sum(c.Length for c in curves) / float(n)
    radius = layout["radius"] if layout["radius"] else depth / 2.0

    # Numbering is by risers climbed, so landings consume a number too:
    # number = start + (tread height - first tread height) / riser height
    start = stairs_start_number(stairs)
    start_found = start is not None
    if not start_found:
        start = 1
    stairs_riser = stairs.ActualRiserHeight
    lowest_rel = lowest_tread_rel(stairs, sdoc)
    if stairs_riser <= TOL or lowest_rel is None:
        raise ValueError("Could not read the riser height of the stairs.")

    # Sideways shift from the walk line (run centre) to the bubble centre
    lateral = 0.0
    if layout["side"] != SIDE_CENTER:
        lateral = run.ActualRunWidth / 2.0 - layout["offset"] - radius

    # Run base = stairs base + run's relative base height
    stairs_base = stairs_base_z(stairs, sdoc)
    riser = (run.TopElevation - run.BaseElevation) / float(risers)
    first = 1 if run.BeginsWithRiser else 0

    def number_at(rel_z):
        return start + int(round((rel_z - lowest_rel) / stairs_riser))

    items = []
    reached_cut = False
    for k in range(1, n + 1):
        p, tan = frame_along(curves, (k - 0.5) * depth)
        left = XYZ(-tan.Y, tan.X, 0.0)
        p = p + left * (layout["side"] * lateral)
        tread_rel = run.BaseElevation + (k - 1 + first) * riser
        hp = transform.OfPoint(XYZ(p.X, p.Y, stairs_base + tread_rel))
        items.append((number_at(tread_rel), hp))
        if hp.Z > cut_z + TOL:
            reached_cut = True
            break

    # The landing at the top of the run is the next "tread" in the walk up
    if not reached_cut:
        run_len = sum(c.Length for c in curves)
        end_pt, tan = frame_along(curves, run_len)
        landing = top_landing(run, stairs, sdoc, stairs_riser, end_pt)
        if landing is not None:
            number = number_at(landing.BaseElevation)
            # A run that ends without a riser is flush with its landing:
            # the last tread already holds that number
            if not items or number > items[-1][0]:
                left = XYZ(-tan.Y, tan.X, 0.0)
                # One tread depth past the last tread, same row as the treads
                p = end_pt + tan * (depth / 2.0) + left * (layout["side"] * lateral)
                hp = transform.OfPoint(
                    XYZ(p.X, p.Y, stairs_base + landing.BaseElevation))
                items.append((number, hp))
    return items, radius, start_found


def footprint_distance(landing, pt):
    """Plan distance from pt to the landing's footprint boundary."""
    best = None
    for c in landing.GetFootprintBoundary():
        z = c.GetEndPoint(0).Z
        res = c.Project(XYZ(pt.X, pt.Y, z))
        if res is not None and (best is None or res.Distance < best):
            best = res.Distance
    return best if best is not None else float("inf")


def top_landing(run, stairs, sdoc, stairs_riser, end_pt):
    """Landing of the same stairs sitting at the top of this run, or None.

    Matched by height (landing top = run top); if several landings share
    that height, the one nearest the run's end point wins.
    """
    candidates = []
    for lid in stairs.GetStairsLandings():
        lnd = sdoc.GetElement(lid)
        if not isinstance(lnd, StairsLanding):
            continue
        if abs(lnd.BaseElevation - run.TopElevation) < stairs_riser / 2.0:
            candidates.append(lnd)
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    return min(candidates, key=lambda l: footprint_distance(l, end_pt))


def place_numbers(items, radius, plane_z, style, opts):
    for k, hp in items:
        c = XYZ(hp.X, hp.Y, plane_z)
        # One closed arc = one full circle element (not two halves)
        circle = Arc.Create(c, radius, 0.0, 2.0 * math.pi,
                            XYZ.BasisX, XYZ.BasisY)
        dc = doc.Create.NewDetailCurve(view, circle)
        dc.LineStyle = style
        TextNote.Create(doc, view.Id, c, str(k), opts)


# --------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------
XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Stair Tread Numbering" Width="400" SizeToContent="Height"
        WindowStartupLocation="CenterOwner" ResizeMode="NoResize"
        Background="#161616" Foreground="#F4F4F4"
        FontFamily="Segoe UI" FontSize="12">
  <Window.Resources>
    <Style x:Key="Label" TargetType="TextBlock">
      <Setter Property="Foreground" Value="#A8A8A8"/>
      <Setter Property="FontSize" Value="11"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
      <Setter Property="Margin" Value="0,14,0,5"/>
    </Style>

    <Style x:Key="Radio" TargetType="ToggleButton">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="Height" Value="30"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ToggleButton">
            <Border x:Name="Bd" Background="{TemplateBinding Background}"
                    BorderBrush="#525252" BorderThickness="1" CornerRadius="4">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsChecked" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#F1C21B"/>
                <Setter TargetName="Bd" Property="BorderBrush" Value="#F1C21B"/>
                <Setter Property="Foreground" Value="#161616"/>
              </Trigger>
              <Trigger Property="IsEnabled" Value="False">
                <Setter Property="Opacity" Value="0.4"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="Btn" TargetType="Button">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="Height" Value="32"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="Bd" Background="{TemplateBinding Background}" CornerRadius="4">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="Bd" Property="Opacity" Value="0.85"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style TargetType="TextBox">
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="BorderBrush" Value="#525252"/>
      <Setter Property="CaretBrush" Value="#F4F4F4"/>
      <Setter Property="Padding" Value="6,5"/>
    </Style>

    <Style TargetType="ListBox">
      <Setter Property="Background" Value="#262626"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="BorderBrush" Value="#525252"/>
      <Setter Property="Height" Value="140"/>
      <Setter Property="Margin" Value="0,4,0,0"/>
    </Style>

    <Style TargetType="ListBoxItem">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ListBoxItem">
            <Border x:Name="Bd" Background="Transparent" Padding="8,4">
              <ContentPresenter/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#393939"/>
              </Trigger>
              <Trigger Property="IsSelected" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#F1C21B"/>
                <Setter Property="Foreground" Value="#161616"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
  </Window.Resources>

  <StackPanel Margin="16">
    <TextBlock x:Name="txtInfo" Foreground="#A8A8A8" TextWrapping="Wrap"/>

    <TextBlock Text="STAIR SOURCE" Style="{StaticResource Label}"/>
    <Grid>
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="*"/>
      </Grid.ColumnDefinitions>
      <ToggleButton x:Name="tgHost" Grid.Column="0" Content="Active Model"
                    Style="{StaticResource Radio}" Margin="0,0,4,0"/>
      <ToggleButton x:Name="tgLink" Grid.Column="1" Content="Linked Model"
                    Style="{StaticResource Radio}" Margin="4,0,0,0"/>
    </Grid>

    <TextBlock Text="TEXT NOTE TYPE" Style="{StaticResource Label}"/>
    <Grid>
      <TextBox x:Name="tbTextFilter"/>
      <TextBlock x:Name="phText" Text="Search..." Foreground="#6F6F6F"
                 IsHitTestVisible="False" Margin="9,0,0,0" VerticalAlignment="Center"/>
    </Grid>
    <ListBox x:Name="lbText"/>

    <TextBlock Text="CIRCLE LINE STYLE" Style="{StaticResource Label}"/>
    <Grid>
      <TextBox x:Name="tbStyleFilter"/>
      <TextBlock x:Name="phStyle" Text="Search..." Foreground="#6F6F6F"
                 IsHitTestVisible="False" Margin="9,0,0,0" VerticalAlignment="Center"/>
    </Grid>
    <ListBox x:Name="lbStyle"/>

    <TextBlock Text="CIRCLE DIAMETER (MM)" Style="{StaticResource Label}"/>
    <TextBox x:Name="tbDia"/>
    <TextBlock Text="0 = match the tread depth" Foreground="#A8A8A8"
               FontSize="11" Margin="0,4,0,0"/>

    <TextBlock Text="BUBBLE POSITION (WALKING UP THE RUN)" Style="{StaticResource Label}"/>
    <Grid>
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="*"/>
      </Grid.ColumnDefinitions>
      <ToggleButton x:Name="tgLeft" Grid.Column="0" Content="Left"
                    Style="{StaticResource Radio}" Margin="0,0,4,0"/>
      <ToggleButton x:Name="tgCenter" Grid.Column="1" Content="Center"
                    Style="{StaticResource Radio}" Margin="4,0,4,0"/>
      <ToggleButton x:Name="tgRight" Grid.Column="2" Content="Right"
                    Style="{StaticResource Radio}" Margin="4,0,0,0"/>
    </Grid>

    <TextBlock Text="OFFSET FROM STAIR EDGE (MM)" Style="{StaticResource Label}"/>
    <TextBox x:Name="tbOffset"/>
    <TextBlock Text="Gap between the run edge and the bubble edge. Negative = outside the run."
               Foreground="#A8A8A8" FontSize="11" Margin="0,4,0,0" TextWrapping="Wrap"/>

    <TextBlock x:Name="txtError" Foreground="#FA4D56" TextWrapping="Wrap"
               Visibility="Collapsed" Margin="0,12,0,0"/>

    <Grid Margin="0,18,0,0">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="*"/>
      </Grid.ColumnDefinitions>
      <Button x:Name="btnCancel" Grid.Column="0" Content="Cancel"
              Style="{StaticResource Btn}" Margin="0,0,4,0"/>
      <Button x:Name="btnStart" Grid.Column="1" Content="Start Numbering"
              Style="{StaticResource Btn}" Background="#F1C21B"
              Foreground="#161616" FontWeight="SemiBold" Margin="4,0,0,0"/>
    </Grid>
  </StackPanel>
</Window>
"""


def bind_list(tb, placeholder, lb, names, preselect):
    """Live-filtered list. Returns a getter for the chosen name."""
    chosen = [preselect if preselect in names else None]

    def on_select(sender, args):
        if lb.SelectedItem is not None:
            chosen[0] = lb.SelectedItem

    def refresh(sender=None, args=None):
        q = tb.Text.strip().lower()
        lb.Items.Clear()
        for n in names:
            if not q or q in n.lower():
                lb.Items.Add(n)
        placeholder.Visibility = (Visibility.Collapsed if tb.Text
                                  else Visibility.Visible)
        if chosen[0] is not None and lb.Items.Contains(chosen[0]):
            lb.SelectedItem = chosen[0]
            lb.ScrollIntoView(chosen[0])

    lb.SelectionChanged += SelectionChangedEventHandler(on_select)
    tb.TextChanged += TextChangedEventHandler(refresh)
    refresh()
    return lambda: chosen[0]


def show_ui(text_names, style_names, has_links, info):
    win = XamlReader.Parse(XAML)
    WindowInteropHelper(win).Owner = __revit__.MainWindowHandle

    tg_host = win.FindName("tgHost")
    tg_link = win.FindName("tgLink")
    tb_dia = win.FindName("tbDia")
    txt_err = win.FindName("txtError")
    win.FindName("txtInfo").Text = info

    result = [None]
    source = [False]  # True = linked

    def set_source(is_link):
        source[0] = is_link
        tg_host.IsChecked = not is_link
        tg_link.IsChecked = is_link

    tg_host.Click += RoutedEventHandler(lambda s, e: set_source(False))
    tg_link.Click += RoutedEventHandler(lambda s, e: set_source(True))
    if not has_links:
        tg_link.IsEnabled = False
        tg_link.ToolTip = "No loaded Revit links in this model"
    set_source(has_links and cfg_get("source", "host") == "link")

    get_text = bind_list(win.FindName("tbTextFilter"), win.FindName("phText"),
                         win.FindName("lbText"), text_names,
                         cfg_get("text_type", ""))
    get_style = bind_list(win.FindName("tbStyleFilter"), win.FindName("phStyle"),
                          win.FindName("lbStyle"), style_names,
                          cfg_get("line_style", ""))
    tb_dia.Text = cfg_get("diameter", "0")

    # Side toggles (Left / Center / Right)
    tb_off = win.FindName("tbOffset")
    side_btns = {SIDE_LEFT: win.FindName("tgLeft"),
                 SIDE_CENTER: win.FindName("tgCenter"),
                 SIDE_RIGHT: win.FindName("tgRight")}
    side = [SIDE_LEFT]

    def set_side(value):
        side[0] = value
        for key, btn in side_btns.items():
            btn.IsChecked = (key == value)
        tb_off.IsEnabled = (value != SIDE_CENTER)

    def side_handler(value):
        return RoutedEventHandler(lambda s, e: set_side(value))

    for key, btn in side_btns.items():
        btn.Click += side_handler(key)
    try:
        saved_side = int(cfg_get("side", str(SIDE_LEFT)))
    except ValueError:
        saved_side = SIDE_LEFT
    set_side(saved_side if saved_side in side_btns else SIDE_LEFT)
    tb_off.Text = cfg_get("offset", "50")

    def parse_mm(tb, allow_negative):
        value = float(tb.Text.strip().replace(",", ".") or "0")
        if value < 0 and not allow_negative:
            raise ValueError()
        return value

    def on_start(sender, args):
        errors = []
        text, style = get_text(), get_style()
        if not text:
            errors.append("Choose a text note type.")
        if not style:
            errors.append("Choose a line style for the circle.")
        dia = offset = None
        try:
            dia = parse_mm(tb_dia, False)
        except ValueError:
            errors.append("Circle diameter must be a number, 0 or larger.")
        try:
            offset = parse_mm(tb_off, True)
        except ValueError:
            errors.append("Offset must be a number (mm).")
        if errors:
            txt_err.Text = "\n".join(errors)
            txt_err.Visibility = Visibility.Visible
            return
        result[0] = {"link": source[0], "text": text, "style": style,
                     "dia": dia, "side": side[0], "offset": offset}
        win.Close()

    win.FindName("btnStart").Click += RoutedEventHandler(on_start)
    win.FindName("btnCancel").Click += RoutedEventHandler(lambda s, e: win.Close())

    frame = DispatcherFrame()

    def on_closed(sender, args):
        frame.Continue = False

    win.Closed += EventHandler(on_closed)
    win.Show()
    Dispatcher.PushFrame(frame)
    return result[0]


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main():
    if not isinstance(view, ViewPlan):
        TaskDialog.Show(TITLE, "Open a plan view first - the numbering "
                               "stops at that view's cut plane.")
        return

    text_types = collect_text_types()
    line_styles = collect_line_styles()
    if not text_types or not line_styles:
        TaskDialog.Show(TITLE, "No text note types or line styles found.")
        return

    cut_lvl, cut_off, cut_z = cut_plane_info(view)
    info = "View: {0}\nCut plane: {1} {2:+.0f} mm".format(
        view.Name, cut_lvl.Name, ft_to_mm(cut_off))

    settings = show_ui(sort_names(text_types.keys()),
                       sort_names(line_styles.keys()),
                       bool(loaded_links()), info)
    if settings is None:
        return

    cfg.source = "link" if settings["link"] else "host"
    cfg.text_type = settings["text"]
    cfg.line_style = settings["style"]
    cfg.diameter = "{0:g}".format(settings["dia"])
    cfg.side = str(settings["side"])
    cfg.offset = "{0:g}".format(settings["offset"])
    script.save_config()

    opts = TextNoteOptions(text_types[settings["text"]])
    opts.HorizontalAlignment = HorizontalTextAlignment.Center
    opts.VerticalAlignment = VerticalTextAlignment.Middle
    style = line_styles[settings["style"]]
    layout = {
        "radius": (mm_to_ft(settings["dia"]) / 2.0
                   if settings["dia"] > 0 else None),
        "side": settings["side"],
        "offset": mm_to_ft(settings["offset"]),
    }
    plane_lvl = view.GenLevel if view.GenLevel is not None else cut_lvl
    plane_z = plane_lvl.ProjectElevation
    warned_start = [False]

    while True:
        try:
            run, transform, sdoc = pick_run(settings["link"])
        except OperationCanceledException:
            break

        try:
            items, radius, start_found = treads_to_number(
                run, transform, sdoc, cut_z, layout)
        except Exception as ex:
            TaskDialog.Show(TITLE, "Run {0}: could not read the tread "
                                   "layout.\n\n{1}".format(eid_int(run.Id), ex))
            continue

        if not start_found and not warned_start[0]:
            warned_start[0] = True
            TaskDialog.Show(TITLE, "'{0}' was not found on these stairs - "
                                   "numbering starts at 1.".format(START_NUMBER_PARAM))

        t = Transaction(doc, "Number Stair Treads")
        t.Start()
        try:
            place_numbers(items, radius, plane_z, style, opts)
            t.Commit()
        except Exception as ex:
            t.RollBack()
            TaskDialog.Show(TITLE, "Run {0}: numbering failed and was rolled "
                                   "back.\n\n{1}".format(eid_int(run.Id), ex))


main()
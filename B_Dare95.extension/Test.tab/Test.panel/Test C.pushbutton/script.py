# -*- coding: utf-8 -*-
"""Shaft X-Marks

Lets the user rubber-band (rectangle) select Shaft Openings in the active view,
asks for a Line Style (searchable, radio-style single-select), then for each shaft:

    1. Deletes the existing X-mark symbolic lines (overwrite).
    2. Redraws the shaft boundary + X-mark as SYMBOLIC LINES inside the shaft's
       own Sketch (via SketchEditScope), NOT as standalone model/detail lines.

Why symbolic lines: the X-marks belong to the shaft's Sketch. Because they are
sketch children, Element.GetDependentElements returns them, and they carry the
"Lines" line style. Detection = dependent ModelCurves whose LineStyle is "Lines"
or the chosen style. The shaft's boundary/profile curves use a different style,
so they are never selected for deletion.

Adding the new curves inside SketchEditScope with the sketch's own SketchPlane
makes them true sketch symbolic lines. Curves that don't close the boundary loop
(the two diagonals) become symbolic and never affect the opening geometry.
"""

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('PresentationCore')
clr.AddReference('PresentationFramework')
clr.AddReference('WindowsBase')
clr.AddReference('System.Xaml')

from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory, GraphicsStyleType,
    Transaction, ElementId, XYZ, Line,
    ModelCurve, CurveElement, ElementClassFilter,
    Sketch, SketchEditScope, IFailuresPreprocessor, FailureProcessingResult
)
from Autodesk.Revit.UI import TaskDialog
from Autodesk.Revit.UI.Selection import ISelectionFilter
from Autodesk.Revit.Exceptions import OperationCanceledException

from System import EventHandler
from System.Collections.Generic import List
from System.Windows import Visibility, RoutedEventHandler
from System.Windows.Controls import RadioButton, TextChangedEventHandler
from System.Windows.Markup import XamlReader
from System.Windows.Threading import Dispatcher, DispatcherFrame

uidoc = __revit__.ActiveUIDocument
doc = uidoc.Document

TITLE = "Shaft X-Marks"


# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #
def eid_int(element_id):
    """ElementId -> int, compatible with Revit 2025+ (.Value) and older (.IntegerValue)."""
    try:
        return element_id.Value
    except AttributeError:
        return element_id.IntegerValue


def get_line_styles():
    """Return {name: GraphicsStyle} for the 'Lines' category and its subcategories."""
    styles = {}
    line_cat = doc.Settings.Categories.get_Item(BuiltInCategory.OST_Lines)
    if line_cat is not None:
        gs = line_cat.GetGraphicsStyle(GraphicsStyleType.Projection)
        if gs is not None:
            styles[line_cat.Name] = gs
        for sub in line_cat.SubCategories:
            g = sub.GetGraphicsStyle(GraphicsStyleType.Projection)
            if g is not None:
                styles[sub.Name] = g
    return styles


class KeepWarnings(IFailuresPreprocessor):
    """Does not resolve or suppress anything - lets Revit show warnings normally."""
    def PreprocessFailures(self, failures_accessor):
        return FailureProcessingResult.Continue


def get_shaft_sketch(shaft):
    """Return the Sketch element that defines the shaft opening, or None."""
    try:
        for did in shaft.GetDependentElements(ElementClassFilter(Sketch)):
            el = doc.GetElement(did)
            if isinstance(el, Sketch):
                return el
    except Exception:
        pass
    return None


def get_sketch_geometry(sketch):
    """Return (corners, boundary_curves) from the sketch's outer profile loop."""
    corners = []
    boundary = []
    profile = sketch.Profile  # CurveArrArray
    if profile is not None and profile.Size > 0:
        outer = None
        for loop in profile:  # CurveArray per loop
            if outer is None or loop.Size > outer.Size:
                outer = loop
        if outer is not None:
            for c in outer:
                boundary.append(c)
                corners.append(c.GetEndPoint(0))
    return corners, boundary


def diagonals_for(corners, shaft, z):
    """Two diagonal lines forming the X (corner 1->3, corner 2->4)."""
    lines = []
    if len(corners) == 4:
        pairs = [(corners[0], corners[2]), (corners[1], corners[3])]
    else:
        # Non-rectangular / unusual profile: span the bounding box so an X still appears.
        bb = shaft.get_BoundingBox(None)  # None = model space (never a view)
        if bb is None:
            return lines
        p1 = XYZ(bb.Min.X, bb.Min.Y, z)
        p2 = XYZ(bb.Max.X, bb.Min.Y, z)
        p3 = XYZ(bb.Max.X, bb.Max.Y, z)
        p4 = XYZ(bb.Min.X, bb.Max.Y, z)
        pairs = [(p1, p3), (p2, p4)]
    for a, b in pairs:
        if a.DistanceTo(b) > 1e-6:
            lines.append(Line.CreateBound(a, b))
    return lines


def get_existing_symbolic_ids(shaft, target_names):
    """{int: ElementId} of the shaft's dependent symbolic model curves to overwrite."""
    result = {}
    try:
        for did in shaft.GetDependentElements(ElementClassFilter(CurveElement)):
            el = doc.GetElement(did)
            if isinstance(el, ModelCurve):
                ls = el.LineStyle
                if ls is not None and ls.Name in target_names:
                    result[eid_int(el.Id)] = el.Id
    except Exception:
        pass
    return result


# --------------------------------------------------------------------------- #
#  Selection
# --------------------------------------------------------------------------- #
class ShaftFilter(ISelectionFilter):
    """Restricts the rectangle pick to Shaft Openings only."""
    _cat_id = ElementId(BuiltInCategory.OST_ShaftOpening)

    def AllowElement(self, elem):
        try:
            return elem.Category is not None and elem.Category.Id == ShaftFilter._cat_id
        except Exception:
            return False

    def AllowReference(self, reference, point):
        return False


# --------------------------------------------------------------------------- #
#  Line-style picker (WPF, searchable, radio-style single-select)
# --------------------------------------------------------------------------- #
XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Shaft X-Marks" Height="580" Width="440"
        WindowStartupLocation="CenterScreen" ResizeMode="CanResizeWithGrip"
        Background="#1E1E2E" Foreground="#CDD6F4" FontFamily="Segoe UI" FontSize="13">
  <Window.Resources>
    <Style x:Key="ToggleItem" TargetType="RadioButton">
      <Setter Property="Margin" Value="0,3,0,0"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="RadioButton">
            <Border x:Name="bd" CornerRadius="6" Padding="12,9" Background="#313244">
              <TextBlock x:Name="txt" Text="{TemplateBinding Content}"
                         Foreground="#CDD6F4" TextTrimming="CharacterEllipsis"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="bd" Property="Background" Value="#45475A"/>
              </Trigger>
              <Trigger Property="IsChecked" Value="True">
                <Setter TargetName="bd" Property="Background" Value="#F0A500"/>
                <Setter TargetName="txt" Property="Foreground" Value="#1E1E2E"/>
                <Setter TargetName="txt" Property="FontWeight" Value="SemiBold"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style x:Key="Btn" TargetType="Button">
      <Setter Property="Height" Value="34"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Foreground" Value="#CDD6F4"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="bd" CornerRadius="6" Background="#45475A">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="bd" Property="Background" Value="#585B70"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style x:Key="BtnAccent" TargetType="Button">
      <Setter Property="Height" Value="34"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Foreground" Value="#1E1E2E"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="bd" CornerRadius="6" Background="#F0A500">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="bd" Property="Background" Value="#F7B733"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
  </Window.Resources>

  <Grid Margin="16">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <StackPanel Grid.Row="0" Margin="0,0,0,12">
      <TextBlock Text="Select a Line Style" FontSize="16" FontWeight="SemiBold"/>
      <TextBlock Text="The boundary and the X-mark will be drawn with this style."
                 Foreground="#A6ADC8" Margin="0,3,0,0"/>
    </StackPanel>

    <Border Grid.Row="1" Background="#2A2A3C" CornerRadius="6" Padding="10,4" Margin="0,0,0,10">
      <TextBox x:Name="SearchBox" BorderThickness="0" Background="Transparent"
               Foreground="#CDD6F4" CaretBrush="#F0A500"
               VerticalContentAlignment="Center" Height="26"/>
    </Border>

    <Border Grid.Row="2" Background="#2A2A3C" CornerRadius="6" Padding="8">
      <ScrollViewer VerticalScrollBarVisibility="Auto">
        <StackPanel x:Name="ListPanel"/>
      </ScrollViewer>
    </Border>

    <Grid Grid.Row="3" Margin="0,12,0,0">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="10"/>
        <ColumnDefinition Width="*"/>
      </Grid.ColumnDefinitions>
      <Button x:Name="CancelBtn" Grid.Column="0" Content="Cancel" Style="{StaticResource Btn}"/>
      <Button x:Name="OkBtn" Grid.Column="2" Content="Draw X-Marks" Style="{StaticResource BtnAccent}"/>
    </Grid>
  </Grid>
</Window>
"""


def prompt_line_style(styles):
    """Show the picker and return the chosen GraphicsStyle, or None if cancelled."""
    window = XamlReader.Parse(XAML)
    list_panel = window.FindName("ListPanel")
    search_box = window.FindName("SearchBox")
    ok_btn = window.FindName("OkBtn")
    cancel_btn = window.FindName("CancelBtn")
    rb_style = window.FindResource("ToggleItem")

    radios = []
    for name in sorted(styles.keys(), key=lambda s: s.lower()):
        rb = RadioButton()
        rb.Content = name
        rb.GroupName = "lineStyles"
        rb.Style = rb_style
        list_panel.Children.Add(rb)
        radios.append(rb)

    state = {"name": None}

    def on_search(sender, args):
        q = search_box.Text.strip().lower()
        for rb in radios:
            show = (q == "" or q in str(rb.Content).lower())
            rb.Visibility = Visibility.Visible if show else Visibility.Collapsed

    def on_ok(sender, args):
        chosen = None
        for rb in radios:
            if rb.IsChecked == True:
                chosen = str(rb.Content)
                break
        if chosen is None:
            TaskDialog.Show(TITLE, "Please select a line style first.")
            return
        state["name"] = chosen
        window.Close()

    def on_cancel(sender, args):
        state["name"] = None
        window.Close()

    search_box.TextChanged += TextChangedEventHandler(on_search)
    ok_btn.Click += RoutedEventHandler(on_ok)
    cancel_btn.Click += RoutedEventHandler(on_cancel)

    frame = DispatcherFrame()

    def on_closed(sender, args):
        frame.Continue = False

    window.Closed += EventHandler(on_closed)
    window.Show()
    window.Activate()
    search_box.Focus()
    Dispatcher.PushFrame(frame)

    if state["name"] is None:
        return None
    return styles[state["name"]]


# --------------------------------------------------------------------------- #
#  Per-shaft work
# --------------------------------------------------------------------------- #
def _log(counters, shaft, msg):
    counters["errors"].append("Shaft {0}: {1}".format(eid_int(shaft.Id), msg))


def draw_shaft(shaft, gstyle, target_names, counters):
    """Overwrite + redraw one shaft's symbolic X-mark.

    Deletion of the old marks happens OUTSIDE the sketch edit (they are
    independent elements; deleting them inside a SketchEditScope raises
    "EditModeMgr element modifiable checker"). The new marks are then created
    INSIDE the scope so they become true sketch symbolic lines. Any old mark
    that is itself sketch-owned survives Phase A and is removed in Phase B.
    """
    # --- locate the sketch (scan all dependents; no class filter) ---
    sketch = None
    try:
        for did in shaft.GetDependentElements(None):
            el = doc.GetElement(did)
            if isinstance(el, Sketch):
                sketch = el
                break
    except Exception as ex:
        counters["failed"] += 1
        _log(counters, shaft, "dependent scan failed: {0}".format(ex))
        return

    if sketch is None:
        counters["skipped"] += 1
        _log(counters, shaft, "no Sketch found among dependents")
        return

    corners, boundary = get_sketch_geometry(sketch)
    if not boundary:
        counters["skipped"] += 1
        _log(counters, shaft, "sketch profile has no curves")
        return

    existing = get_existing_symbolic_ids(shaft, target_names)
    z = corners[0].Z if corners else 0.0

    # --- Phase A: delete old marks OUTSIDE the sketch edit ---
    survivors = {}
    if existing:
        ta = Transaction(doc, "Clear old shaft marks")
        ta.Start()
        try:
            for k, e_id in existing.items():
                try:
                    doc.Delete(e_id)
                    counters["deleted"] += 1
                except Exception:
                    survivors[k] = e_id  # sketch-owned -> handle in Phase B
            ta.Commit()
        except Exception as ex:
            if ta.HasStarted() and not ta.HasEnded():
                ta.RollBack()
            counters["failed"] += 1
            _log(counters, shaft, "clear step failed: {0}".format(ex))
            return

    # --- Phase B: draw new marks INSIDE the sketch edit ---
    scope = SketchEditScope(doc, "Edit shaft sketch")
    try:
        scope.Start(sketch.Id)
    except Exception as ex:
        counters["failed"] += 1
        _log(counters, shaft, "SketchEditScope.Start failed: {0}".format(ex))
        try:
            scope.Cancel()
        except Exception:
            pass
        return

    t = Transaction(doc, "Draw Shaft X-Mark (symbolic)")
    t.Start()
    try:
        # remove any sketch-owned marks that survived Phase A
        if survivors:
            id_list = List[ElementId]()
            for e_id in survivors.values():
                id_list.Add(e_id)
            try:
                doc.Delete(id_list)
                counters["deleted"] += id_list.Count
            except Exception:
                pass

        sp = sketch.SketchPlane

        for c in boundary:
            mc = doc.Create.NewModelCurve(c, sp)
            mc.LineStyle = gstyle
            counters["drawn"] += 1

        for ln in diagonals_for(corners, shaft, z):
            mc = doc.Create.NewModelCurve(ln, sp)
            mc.LineStyle = gstyle
            counters["drawn"] += 1

        t.Commit()
    except Exception as ex:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        counters["failed"] += 1
        _log(counters, shaft, "draw failed: {0}".format(ex))
        try:
            scope.Cancel()
        except Exception:
            pass
        return

    # --- finalize the sketch edit ---
    try:
        scope.Commit(KeepWarnings())
    except Exception as ex:
        counters["failed"] += 1
        _log(counters, shaft, "SketchEditScope.Commit failed: {0}".format(ex))
        try:
            scope.Cancel()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
#  Main
# --------------------------------------------------------------------------- #
def main():
    styles = get_line_styles()
    if not styles:
        TaskDialog.Show(TITLE, "No line styles were found.")
        return

    # 1) Rubber-band select the shafts to mark.
    try:
        picked = uidoc.Selection.PickElementsByRectangle(
            ShaftFilter(), "Drag a rectangle across the shaft openings to mark.")
    except OperationCanceledException:
        return  # user pressed Esc

    shafts = [e for e in picked] if picked is not None else []
    if not shafts:
        TaskDialog.Show(TITLE, "No shaft openings were inside the selection rectangle.")
        return

    # 2) Pick the line style.
    gstyle = prompt_line_style(styles)
    if gstyle is None:
        return  # cancelled

    target_names = set(["Lines", gstyle.Name])

    # 3) Draw (one SketchEditScope per shaft).
    counters = {"skipped": 0, "deleted": 0, "drawn": 0, "failed": 0, "errors": []}
    for shaft in shafts:
        draw_shaft(shaft, gstyle, target_names, counters)

    detail = ""
    if counters["errors"]:
        detail = "\n\nDetails (first 5):\n- " + "\n- ".join(counters["errors"][:5])

    TaskDialog.Show(
        TITLE,
        "Done.\n\n"
        "Shafts selected:         {0}\n"
        "Skipped (no sketch):     {1}\n"
        "Failed (see below):      {2}\n"
        "Existing lines deleted:  {3}\n"
        "New symbolic lines:      {4}\n"
        "Line style:              {5}{6}".format(
            len(shafts), counters["skipped"], counters["failed"],
            counters["deleted"], counters["drawn"], gstyle.Name, detail
        ),
    )


main()
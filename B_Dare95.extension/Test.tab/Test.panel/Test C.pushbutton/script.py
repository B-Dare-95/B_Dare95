# -*- coding: utf-8 -*-
__title__ = "Shaft X Mark"
__doc__ = "Draws boundary + X mark as Symbolic Lines on all Shafts. Overwrites existing ones."

import clr

clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")
clr.AddReference("System")
clr.AddReference("System.Xml")

from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory, Transaction,
    Line, XYZ, CurveArray, ModelLine, GraphicsStyle,
    ElementId, ElementFilter
)
from Autodesk.Revit.UI import TaskDialog
from System.Windows import Window, WindowStartupLocation, SizeToContent, Thickness, GridLength, GridUnitType
from System.Windows.Controls import (
    Grid, ColumnDefinition, RowDefinition, StackPanel, ListBox,
    ListBoxItem, SelectionMode, Button, Label, TextBox, ScrollViewer,
    Border, Orientation
)
from System.Windows.Media import SolidColorBrush, Color
from System.Windows import FontWeights
from System.Xml import XmlReader
from System.IO import StringReader
import System

doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

# ─────────────────────────────────────────────
# 1. Collect all Shaft Openings
# ─────────────────────────────────────────────
shafts = FilteredElementCollector(doc) \
    .OfCategory(BuiltInCategory.OST_ShaftOpening) \
    .WhereElementIsNotElementType() \
    .ToElements()

if not shafts:
    TaskDialog.Show("Shaft X Mark", "No Shaft Openings found in the project.")
    raise SystemExit

# ─────────────────────────────────────────────
# 2. Collect Line Styles (GraphicsStyle of Model Lines)
# ─────────────────────────────────────────────
line_styles = FilteredElementCollector(doc) \
    .OfClass(GraphicsStyle) \
    .ToElements()

# Filter to model-line-style subcategories only
line_style_list = []
for gs in line_styles:
    cat = gs.GraphicsStyleCategory
    if cat is None:
        continue
    parent = cat.Parent
    if parent is not None and parent.Name == "Lines":
        line_style_list.append(gs)
    elif cat.Name == "Lines" and parent is None:
        line_style_list.append(gs)

line_style_list = sorted(line_style_list, key=lambda g: g.Name)

if not line_style_list:
    TaskDialog.Show("Shaft X Mark", "No Line Styles found.")
    raise SystemExit

# ─────────────────────────────────────────────
# 3. WPF Dialog – Line Style Picker
# ─────────────────────────────────────────────
XAML = u"""
<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Shaft X Mark – Line Style"
    Width="420" SizeToContent="Height"
    WindowStartupLocation="CenterScreen"
    Background="#1E1E2E">

    <Window.Resources>
        <Style TargetType="ListBoxItem">
            <Setter Property="Foreground" Value="#CDD6F4"/>
            <Setter Property="Background" Value="Transparent"/>
            <Setter Property="Padding"    Value="8,5"/>
            <Setter Property="FontSize"   Value="13"/>
            <Style.Triggers>
                <Trigger Property="IsSelected" Value="True">
                    <Setter Property="Background" Value="#F0A500"/>
                    <Setter Property="Foreground" Value="#1E1E2E"/>
                    <Setter Property="FontWeight" Value="SemiBold"/>
                </Trigger>
                <Trigger Property="IsMouseOver" Value="True">
                    <Setter Property="Background" Value="#313244"/>
                </Trigger>
            </Style.Triggers>
        </Style>
        <Style TargetType="Button">
            <Setter Property="Background"   Value="#F0A500"/>
            <Setter Property="Foreground"   Value="#1E1E2E"/>
            <Setter Property="FontWeight"   Value="Bold"/>
            <Setter Property="FontSize"     Value="13"/>
            <Setter Property="Padding"      Value="18,8"/>
            <Setter Property="BorderThickness" Value="0"/>
            <Setter Property="Cursor"       Value="Hand"/>
        </Style>
        <Style x:Key="CancelBtn" TargetType="Button">
            <Setter Property="Background"   Value="#45475A"/>
            <Setter Property="Foreground"   Value="#CDD6F4"/>
            <Setter Property="FontWeight"   Value="Bold"/>
            <Setter Property="FontSize"     Value="13"/>
            <Setter Property="Padding"      Value="18,8"/>
            <Setter Property="BorderThickness" Value="0"/>
            <Setter Property="Cursor"       Value="Hand"/>
        </Style>
    </Window.Resources>

    <StackPanel Margin="18">

        <!-- Header -->
        <TextBlock Text="Shaft X Mark" FontSize="17" FontWeight="Bold"
                   Foreground="#F0A500" Margin="0,0,0,4"/>
        <TextBlock Text="Select a Line Style for the boundary and X mark."
                   Foreground="#A6ADC8" FontSize="12" Margin="0,0,0,14"/>

        <!-- Search -->
        <Border Background="#313244" CornerRadius="6" Margin="0,0,0,8" Padding="8,4">
            <TextBox x:Name="SearchBox" Background="Transparent" BorderThickness="0"
                     Foreground="#CDD6F4" CaretBrush="#F0A500"
                     FontSize="13" ToolTip="Filter line styles…"/>
        </Border>

        <!-- List -->
        <Border Background="#2A2A3C" CornerRadius="6" Margin="0,0,0,14">
            <ListBox x:Name="StyleList" SelectionMode="Single"
                     Background="Transparent" BorderThickness="0"
                     Height="260" ScrollViewer.HorizontalScrollBarVisibility="Disabled"/>
        </Border>

        <!-- Info -->
        <TextBlock x:Name="InfoLabel" Foreground="#A6ADC8" FontSize="11"
                   Margin="0,0,0,14" TextWrapping="Wrap"
                   Text="No style selected."/>

        <!-- Buttons -->
        <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
            <Button x:Name="CancelBtn" Style="{StaticResource CancelBtn}"
                    Content="Cancel" Margin="0,0,10,0"/>
            <Button x:Name="OkBtn" Content="Draw X Marks"/>
        </StackPanel>

    </StackPanel>
</Window>
"""

# Build window
reader = XmlReader.Create(StringReader(XAML))
win = System.Windows.Markup.XamlReader.Load(reader)

search_box = win.FindName("SearchBox")
style_list = win.FindName("StyleList")
ok_btn = win.FindName("OkBtn")
cancel_btn = win.FindName("CancelBtn")
info_label = win.FindName("InfoLabel")


# Populate list helper
def populate_list(filter_text=""):
    style_list.Items.Clear()
    for gs in line_style_list:
        if filter_text.lower() not in gs.Name.lower():
            continue
        item = ListBoxItem()
        item.Content = gs.Name
        item.Tag = gs
        style_list.Items.Add(item)
    if style_list.Items.Count > 0:
        style_list.SelectedIndex = 0


populate_list()


# Search filter
def on_search_changed(sender, e):
    populate_list(search_box.Text)


search_box.TextChanged += on_search_changed


# Selection change → info label
def on_selection_changed(sender, e):
    item = style_list.SelectedItem
    if item:
        info_label.Text = u"Selected: {}".format(item.Tag.Name)
    else:
        info_label.Text = u"No style selected."


style_list.SelectionChanged += on_selection_changed

# Result holder
_result = [None]


def on_ok(sender, e):
    item = style_list.SelectedItem
    if item is None:
        info_label.Text = u"Please select a line style first."
        return
    _result[0] = item.Tag
    win.Close()


def on_cancel(sender, e):
    win.Close()


ok_btn.Click += System.Windows.RoutedEventHandler(on_ok)
cancel_btn.Click += System.Windows.RoutedEventHandler(on_cancel)

win.ShowDialog()

chosen_style = _result[0]
if chosen_style is None:
    raise SystemExit

# ─────────────────────────────────────────────
# 4. Helper – get sketch plane of shaft
# ─────────────────────────────────────────────
from Autodesk.Revit.DB import SketchPlane, Plane


def get_shaft_sketch_plane(shaft):
    """Return the SketchPlane already owned by the shaft, or None."""
    sp_id = shaft.SketchId if hasattr(shaft, "SketchId") else ElementId.InvalidElementId
    if sp_id != ElementId.InvalidElementId:
        return doc.GetElement(sp_id)
    return None


# ─────────────────────────────────────────────
# 5. Helper – get shaft boundary corner points
#    Returns ordered list of XYZ from the profile curves
# ─────────────────────────────────────────────
def get_shaft_corners(shaft):
    """
    Extract corner XYZ points from the shaft's sketch profile.
    Returns a flat list of unique XYZ in curve order.
    """
    sketch_id = ElementId.InvalidElementId
    # Try to get the sketch element that owns the shaft profile
    dep_ids = shaft.GetDependentElements(None)
    sketch = None
    for eid in dep_ids:
        el = doc.GetElement(eid)
        if el and el.GetType().Name == "Sketch":
            sketch = el
            break

    curves = []
    if sketch is not None:
        profile = sketch.Profile  # CurveArrArray
        for curve_arr in profile:
            for curve in curve_arr:
                curves.append(curve)

    # Fallback: bounding box corners
    if not curves:
        bb = shaft.get_BoundingBox(None)
        if bb is None:
            return None
        mn, mx = bb.Min, bb.Max
        z = mn.Z
        return [
            XYZ(mn.X, mn.Y, z),
            XYZ(mx.X, mn.Y, z),
            XYZ(mx.X, mx.Y, z),
            XYZ(mn.X, mx.Y, z),
        ]

    # Collect ordered unique points from curves
    pts = []
    for c in curves:
        p = c.GetEndPoint(0)
        if not pts or pts[-1].DistanceTo(p) > 1e-6:
            pts.append(p)
    return pts


# ─────────────────────────────────────────────
# 6. Helper – delete existing symbolic lines on a shaft
#    Uses GetDependentElements; deletes ModelLine where
#    LineStyle.Name == "Lines"  (i.e. drawn by this tool)
# ─────────────────────────────────────────────
def delete_existing_symbolic_lines(shaft, t):
    dep_ids = shaft.GetDependentElements(None)
    deleted = 0
    for eid in dep_ids:
        el = doc.GetElement(eid)
        if el is None:
            continue
        if not isinstance(el, ModelLine):
            continue
        try:
            ls = el.LineStyle
            if ls is not None and ls.Name == "Lines":
                doc.Delete(eid)
                deleted += 1
        except Exception:
            pass
    return deleted


# ─────────────────────────────────────────────
# 7. Helper – draw a single model line on shaft's plane
# ─────────────────────────────────────────────
from Autodesk.Revit.DB import ModelCurve


def draw_line_on_shaft(start, end, sketch_plane, line_style):
    """Create a ModelLine between start and end on the given SketchPlane."""
    line = Line.CreateBound(start, end)
    mc = doc.Create.NewModelCurve(line, sketch_plane)
    mc.LineStyle = line_style
    return mc


# ─────────────────────────────────────────────
# 8. Main Transaction – Draw on all shafts
# ─────────────────────────────────────────────
drawn = 0
skipped = 0
errors = []

t = Transaction(doc, "Shaft X Mark – Draw Symbolic Lines")
t.Start()

try:
    for shaft in shafts:
        try:
            # 8a. Locate or create sketch plane
            dep_ids = shaft.GetDependentElements(None)
            sp = None
            for eid in dep_ids:
                el = doc.GetElement(eid)
                if el and el.GetType().Name == "Sketch":
                    # Get the sketch plane from an existing ModelLine if present,
                    # or build one from the sketch's plane
                    sk = el
                    try:
                        sp = SketchPlane.Create(doc, sk.SketchPlane.GetPlane())
                    except Exception:
                        pass
                    break

            # Fallback: build plane from bounding box Z
            if sp is None:
                bb = shaft.get_BoundingBox(None)
                if bb is None:
                    skipped += 1
                    continue
                z = bb.Min.Z
                plane = Plane.CreateByNormalAndOrigin(XYZ.BasisZ, XYZ(0, 0, z))
                sp = SketchPlane.Create(doc, plane)

            # 8b. Delete existing symbolic lines
            delete_existing_symbolic_lines(shaft, t)

            # 8c. Get corner points
            pts = get_shaft_corners(shaft)
            if pts is None or len(pts) < 3:
                skipped += 1
                continue

            # 8d. Draw boundary (close the loop)
            n = len(pts)
            for i in range(n):
                p0 = pts[i]
                p1 = pts[(i + 1) % n]
                # Flatten to sketch plane Z
                z0 = sp.GetPlane().Origin.Z
                p0 = XYZ(p0.X, p0.Y, z0)
                p1 = XYZ(p1.X, p1.Y, z0)
                if p0.DistanceTo(p1) < 1e-6:
                    continue
                draw_line_on_shaft(p0, p1, sp, chosen_style)

            # 8e. Draw X mark: pt[0]→pt[2] and pt[1]→pt[3]
            z0 = sp.GetPlane().Origin.Z


            def flat(p):
                return XYZ(p.X, p.Y, z0)


            # For non-rectangular shafts use bounding box corners for the X
            bb = shaft.get_BoundingBox(None)
            mn = bb.Min
            mx = bb.Max
            c0 = XYZ(mn.X, mn.Y, z0)  # bottom-left
            c1 = XYZ(mx.X, mn.Y, z0)  # bottom-right
            c2 = XYZ(mx.X, mx.Y, z0)  # top-right
            c3 = XYZ(mn.X, mx.Y, z0)  # top-left

            # Diagonal 1: c0 → c2  (pt1 → pt3)
            draw_line_on_shaft(c0, c2, sp, chosen_style)
            # Diagonal 2: c1 → c3  (pt2 → pt4)
            draw_line_on_shaft(c1, c3, sp, chosen_style)

            drawn += 1

        except Exception as ex:
            errors.append(u"{} – {}".format(shaft.Id, str(ex)))

    t.Commit()

except Exception as ex:
    t.RollBack()
    TaskDialog.Show("Error", str(ex))
    raise

# ─────────────────────────────────────────────
# 9. Summary
# ─────────────────────────────────────────────
msg = u"Done.\n\nShafts drawn: {}\nShafts skipped: {}".format(drawn, skipped)
if errors:
    msg += u"\n\nErrors ({}):\n{}".format(len(errors), u"\n".join(errors[:10]))
TaskDialog.Show("Shaft X Mark", msg)
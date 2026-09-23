# -*- coding: utf-8 -*-
"""
Dimension Text Writer
---------------------
1. Enter the text for Top (Above), Bottom (Below), Prefix and Suffix.
2. Pick dimensions one after another - text is written instantly on pick.
3. Press ESC to finish. Everything happens inside ONE Transaction (one Undo).

Target: Revit 2024-2027, IronPython 2.7 (pyRevit)
"""

__title__ = "Dim\nText"
__doc__ = "Write Top / Bottom / Prefix / Suffix text into picked dimensions. ESC to finish."

import clr
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from System import EventHandler
from System.Windows import RoutedEventHandler
from System.Windows.Input import Key, KeyEventHandler
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Markup import XamlReader
from System.Windows.Threading import Dispatcher, DispatcherFrame

from Autodesk.Revit.DB import Transaction, SubTransaction, Dimension, SpotDimension
from Autodesk.Revit.UI import TaskDialog
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter
from Autodesk.Revit.Exceptions import OperationCanceledException

uiapp = __revit__
uidoc = uiapp.ActiveUIDocument
doc = uidoc.Document


# =============================================================================
# Helpers
# =============================================================================
def id_val(element_id):
    """ElementId -> int, Revit 2024-2027 safe."""
    try:
        return element_id.Value
    except AttributeError:
        return element_id.IntegerValue


def flatten(pt, view_dir):
    """Project a point onto the view plane (remove the view-depth component)."""
    return pt.Subtract(view_dir.Multiply(pt.DotProduct(view_dir)))


def nearest_segment(segments, pick_pt, view_dir):
    """Segment whose text origin is closest to the pick point, measured in the view plane."""
    p = flatten(pick_pt, view_dir)
    best = [None, None]  # [segment, distance]
    for seg in segments:
        origin = seg.Origin
        if origin is None:
            continue
        d = flatten(origin, view_dir).DistanceTo(p)
        if best[1] is None or d < best[1]:
            best[0], best[1] = seg, d
    return best[0]


class DimensionFilter(ISelectionFilter):
    """Linear / angular / radial / diameter / arc-length dims only (no spot dims)."""
    def AllowElement(self, elem):
        return isinstance(elem, Dimension) and not isinstance(elem, SpotDimension)

    def AllowReference(self, reference, position):
        return False


# =============================================================================
# UI  (IBM Carbon palette)
# =============================================================================
XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Dimension Text Writer" Width="440" SizeToContent="Height"
        WindowStartupLocation="CenterScreen" ResizeMode="NoResize"
        Background="#161616" FontFamily="Segoe UI" FontSize="12"
        FocusManager.FocusedElement="{Binding ElementName=TbAbove}">

  <Window.Resources>
    <Style x:Key="Label" TargetType="TextBlock">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="VerticalAlignment" Value="Center"/>
    </Style>
    <Style x:Key="Sub" TargetType="TextBlock">
      <Setter Property="Foreground" Value="#A8A8A8"/>
      <Setter Property="TextWrapping" Value="Wrap"/>
    </Style>

    <Style TargetType="TextBox">
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="CaretBrush" Value="#F4F4F4"/>
      <Setter Property="BorderBrush" Value="#525252"/>
      <Setter Property="Height" Value="28"/>
      <Setter Property="Padding" Value="6,0"/>
      <Setter Property="VerticalContentAlignment" Value="Center"/>
    </Style>

    <Style TargetType="CheckBox">
      <Setter Property="VerticalAlignment" Value="Center"/>
      <Setter Property="ToolTip" Value="Unchecked = leave this property untouched"/>
    </Style>

    <Style x:Key="Btn" TargetType="Button">
      <Setter Property="Height" Value="32"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="Bd" Background="{TemplateBinding Background}" CornerRadius="4" Padding="14,0">
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

    <Style x:Key="Mode" TargetType="ToggleButton">
      <Setter Property="Height" Value="30"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ToggleButton">
            <Border x:Name="Bd" Background="#393939" CornerRadius="4" Padding="10,0">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsChecked" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#F1C21B"/>
                <Setter Property="Foreground" Value="#161616"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
  </Window.Resources>

  <Border Margin="14" Background="#262626" CornerRadius="6" Padding="16">
    <StackPanel>
      <TextBlock Text="Dimension Text Writer" Style="{StaticResource Label}" FontSize="16" FontWeight="SemiBold"/>
      <TextBlock Style="{StaticResource Sub}" Margin="0,4,0,14"
                 Text="Checked fields are written to every dimension you pick. An empty checked field clears that property."/>

      <Grid Margin="0,0,0,8">
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="26"/><ColumnDefinition Width="64"/><ColumnDefinition Width="*"/>
        </Grid.ColumnDefinitions>
        <CheckBox x:Name="CbAbove" IsChecked="True" Grid.Column="0"/>
        <TextBlock Text="Top" Style="{StaticResource Label}" Grid.Column="1"/>
        <TextBox x:Name="TbAbove" Grid.Column="2" IsEnabled="{Binding IsChecked, ElementName=CbAbove}"/>
      </Grid>

      <Grid Margin="0,0,0,8">
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="26"/><ColumnDefinition Width="64"/><ColumnDefinition Width="*"/>
        </Grid.ColumnDefinitions>
        <CheckBox x:Name="CbBelow" IsChecked="True" Grid.Column="0"/>
        <TextBlock Text="Bottom" Style="{StaticResource Label}" Grid.Column="1"/>
        <TextBox x:Name="TbBelow" Grid.Column="2" IsEnabled="{Binding IsChecked, ElementName=CbBelow}"/>
      </Grid>

      <Grid Margin="0,0,0,8">
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="26"/><ColumnDefinition Width="64"/><ColumnDefinition Width="*"/>
        </Grid.ColumnDefinitions>
        <CheckBox x:Name="CbPrefix" IsChecked="True" Grid.Column="0"/>
        <TextBlock Text="Prefix" Style="{StaticResource Label}" Grid.Column="1"/>
        <TextBox x:Name="TbPrefix" Grid.Column="2" IsEnabled="{Binding IsChecked, ElementName=CbPrefix}"/>
      </Grid>

      <Grid Margin="0,0,0,14">
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="26"/><ColumnDefinition Width="64"/><ColumnDefinition Width="*"/>
        </Grid.ColumnDefinitions>
        <CheckBox x:Name="CbSuffix" IsChecked="True" Grid.Column="0"/>
        <TextBlock Text="Suffix" Style="{StaticResource Label}" Grid.Column="1"/>
        <TextBox x:Name="TbSuffix" Grid.Column="2" IsEnabled="{Binding IsChecked, ElementName=CbSuffix}"/>
      </Grid>

      <TextBlock Text="Multi-segment dimensions" Style="{StaticResource Sub}" Margin="0,0,0,6"/>
      <Grid Margin="0,0,0,14">
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="*"/><ColumnDefinition Width="8"/><ColumnDefinition Width="*"/>
        </Grid.ColumnDefinitions>
        <ToggleButton x:Name="TgAll" Content="All segments" Style="{StaticResource Mode}" IsChecked="True" Grid.Column="0"/>
        <ToggleButton x:Name="TgPicked" Content="Picked segment only" Style="{StaticResource Mode}" Grid.Column="2"/>
      </Grid>

      <Border Background="#393939" CornerRadius="4" Padding="10,8" Margin="0,0,0,14">
        <TextBlock Style="{StaticResource Sub}"
                   Text="Enter = start picking. While picking, text is applied on each click. Press ESC to finish - all changes are one Undo."/>
      </Border>

      <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
        <Button x:Name="BtnCancel" Content="Cancel" Style="{StaticResource Btn}" Background="#525252" Foreground="#F4F4F4" Margin="0,0,8,0"/>
        <Button x:Name="BtnStart" Content="Start Picking" Style="{StaticResource Btn}" Background="#F1C21B" Foreground="#161616" FontWeight="SemiBold"/>
      </StackPanel>
    </StackPanel>
  </Border>
</Window>
"""


def show_ui():
    """Returns (values, mode) or None if cancelled. values = [(api_property, text), ...]"""
    window = XamlReader.Parse(XAML)
    WindowInteropHelper(window).Owner = uiapp.MainWindowHandle

    f = window.FindName
    fields = [
        ("Above",  f("CbAbove"),  f("TbAbove")),
        ("Below",  f("CbBelow"),  f("TbBelow")),
        ("Prefix", f("CbPrefix"), f("TbPrefix")),
        ("Suffix", f("CbSuffix"), f("TbSuffix")),
    ]
    tg_all, tg_picked = f("TgAll"), f("TgPicked")

    result = {"go": False, "values": [], "mode": "all"}
    frame = DispatcherFrame()

    def on_mode(sender, args):
        is_all = sender is tg_all
        tg_all.IsChecked = is_all
        tg_picked.IsChecked = not is_all

    def on_start(sender, args):
        values = [(prop, tb.Text or "") for prop, cb, tb in fields if cb.IsChecked == True]
        if not values:
            TaskDialog.Show("Dimension Text Writer", "Check at least one property to write.")
            return
        result["go"] = True
        result["values"] = values
        result["mode"] = "all" if tg_all.IsChecked == True else "picked"
        window.Close()

    def on_cancel(sender, args):
        window.Close()

    def on_key(sender, args):
        if args.Key == Key.Escape:
            args.Handled = True
            window.Close()
        elif args.Key == Key.Enter:
            args.Handled = True
            on_start(sender, args)

    def on_closed(sender, args):
        frame.Continue = False

    tg_all.Click += RoutedEventHandler(on_mode)
    tg_picked.Click += RoutedEventHandler(on_mode)
    f("BtnStart").Click += RoutedEventHandler(on_start)
    f("BtnCancel").Click += RoutedEventHandler(on_cancel)
    window.PreviewKeyDown += KeyEventHandler(on_key)
    window.Closed += EventHandler(on_closed)

    window.Show()
    Dispatcher.PushFrame(frame)

    if not result["go"]:
        return None
    return result["values"], result["mode"]


# =============================================================================
# Core
# =============================================================================
def write_text(dim, values, mode, pick_pt, view_dir):
    """Write the values into the dimension (or its segments). Raises on failure."""
    if dim.NumberOfSegments > 0:
        segments = list(dim.Segments)
        if mode == "picked":
            if pick_pt is None:
                raise Exception("Pick point unavailable - could not resolve segment")
            seg = nearest_segment(segments, pick_pt, view_dir)
            if seg is None:
                raise Exception("Could not resolve picked segment")
            targets = [seg]
        else:
            targets = segments
    else:
        targets = [dim]

    for target in targets:
        for prop, text in values:
            setattr(target, prop, text)


def run():
    ui = show_ui()
    if ui is None:
        return
    values, mode = ui

    view_dir = doc.ActiveView.ViewDirection
    sel_filter = DimensionFilter()
    done = [0]
    failures = []

    t = Transaction(doc, "Write Dimension Text")
    t.Start()
    try:
        while True:
            prompt = "Pick a dimension to write text  ({} done)  |  ESC to finish".format(done[0])
            try:
                ref = uidoc.Selection.PickObject(ObjectType.Element, sel_filter, prompt)
            except OperationCanceledException:
                break

            dim = doc.GetElement(ref.ElementId)
            st = SubTransaction(doc)
            st.Start()
            try:
                write_text(dim, values, mode, ref.GlobalPoint, view_dir)
                st.Commit()
                done[0] += 1
            except Exception as ex:
                st.RollBack()
                failures.append("Id {}: {}".format(id_val(dim.Id), ex))

            # show the change immediately while still inside the open transaction
            doc.Regenerate()
            uidoc.RefreshActiveView()

        t.Commit()
    except Exception as ex:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        TaskDialog.Show("Dimension Text Writer", "Rolled back - unexpected error:\n\n{}".format(ex))
        return

    if failures:
        TaskDialog.Show(
            "Dimension Text Writer",
            "{} dimension(s) updated, {} failed:\n\n{}".format(done[0], len(failures), "\n".join(failures))
        )


run()
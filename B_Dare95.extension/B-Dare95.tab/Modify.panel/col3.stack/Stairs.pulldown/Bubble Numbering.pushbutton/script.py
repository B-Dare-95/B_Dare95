# -*- coding: utf-8 -*-
"""Bubble Numbering

Places a numbered (or lettered) TextNote inside a detail-line circle at every
point you pick, incrementing the label after each placement.

Pick points one after another; press ESC to stop.
"""

__title__ = "Bubble\nNumbering"
__author__ = "Mohamed Bedair"

import math

import clr

clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")

from System import EventHandler
from System.Windows import RoutedEventHandler
from System.Windows.Controls import ListBoxItem, TextChangedEventHandler
from System.Windows.Markup import XamlReader
from System.Windows.Media import ColorConverter, SolidColorBrush
from System.Windows.Threading import Dispatcher, DispatcherFrame

from Autodesk.Revit import DB
from Autodesk.Revit import Exceptions as RvtEx

from pyrevit import forms, revit

doc = revit.doc
uidoc = revit.uidoc

MM_PER_FT = 304.8
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

CLR_SUBTEXT = "#A8A8A8"
CLR_ACCENT = "#F1C21B"
CLR_ERROR = "#FA4D56"

ANCHOR_WORDS = {
    "top": "top quadrant",
    "left": "left quadrant",
    "center": "center",
    "right": "right quadrant",
    "bottom": "bottom quadrant",
}

PLACEABLE_VIEW_TYPES = [
    DB.ViewType.FloorPlan,
    DB.ViewType.CeilingPlan,
    DB.ViewType.EngineeringPlan,
    DB.ViewType.AreaPlan,
    DB.ViewType.Section,
    DB.ViewType.Elevation,
    DB.ViewType.Detail,
    DB.ViewType.DraftingView,
    DB.ViewType.Legend,
]


# ---------------------------------------------------------------- helpers ---
def brush(hex_color):
    return SolidColorBrush(ColorConverter.ConvertFromString(hex_color))


def elem_name(element):
    try:
        return DB.Element.Name.GetValue(element)
    except Exception:
        return element.Name


def letters_to_index(text):
    """A -> 1, Z -> 26, AA -> 27."""
    index = 0
    for char in text:
        index = index * 26 + (LETTERS.index(char) + 1)
    return index


def index_to_letters(index):
    """1 -> A, 26 -> Z, 27 -> AA."""
    out = ""
    left = index
    while left > 0:
        left, rem = divmod(left - 1, 26)
        out = LETTERS[rem] + out
    return out or "A"


def parse_start(raw_text):
    """Return (kind, index, pad, error). kind is 'number' or 'letter'."""
    raw = (raw_text or "").strip()
    if not raw:
        return None, 0, 0, "Start value cannot be empty."

    digits = raw[1:] if raw[:1] in ("+", "-") else raw
    if digits.isdigit():
        value = int(raw)
        if value < 1:
            return None, 0, 0, "Start value must be 1 or greater."
        pad = len(digits) if digits.startswith("0") and len(digits) > 1 else 0
        return "number", value, pad, None

    upper = raw.upper()
    for char in upper:
        if char not in LETTERS:
            return None, 0, 0, "Start value must be digits or letters only (1, 07, A, AA...)."
    return "letter", letters_to_index(upper), 0, None


def make_label(kind, index, pad, prefix, suffix):
    if kind == "number":
        core = str(index).zfill(pad) if pad else str(index)
    else:
        core = index_to_letters(index)
    return "{}{}{}".format(prefix, core, suffix)


def collect_text_types():
    """[(display, TextNoteType), ...] sorted by name."""
    rows = []
    collector = DB.FilteredElementCollector(doc).OfClass(DB.TextNoteType)
    for text_type in collector.ToElements():
        size_param = text_type.get_Parameter(DB.BuiltInParameter.TEXT_SIZE)
        size_mm = size_param.AsDouble() * MM_PER_FT if size_param else 0.0
        rows.append((elem_name(text_type), size_mm, text_type))
    rows.sort(key=lambda row: row[0].lower())
    return [("{}   -   {:.1f} mm".format(r[0], r[1]), r[2]) for r in rows]


def collect_line_styles():
    """[(display, GraphicsStyle), ...] sorted by name."""
    rows = []
    lines_cat = doc.Settings.Categories.get_Item(DB.BuiltInCategory.OST_Lines)
    for sub_cat in lines_cat.SubCategories:
        name = sub_cat.Name
        if name.startswith("<"):
            continue
        style = sub_cat.GetGraphicsStyle(DB.GraphicsStyleType.Projection)
        if style is None:
            continue
        rows.append((name, style))
    rows.sort(key=lambda row: row[0].lower())
    return rows


# ------------------------------------------------------------------- xaml ---
XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Bubble Numbering"
        Width="790" Height="750" MinWidth="720" MinHeight="690"
        WindowStartupLocation="CenterScreen"
        Background="#161616"
        Foreground="#F4F4F4"
        FontFamily="IBM Plex Sans, Segoe UI"
        UseLayoutRounding="True">

  <Window.Resources>

    <Style x:Key="H1" TargetType="TextBlock">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="FontSize" Value="19"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
    </Style>

    <Style x:Key="Sub" TargetType="TextBlock">
      <Setter Property="Foreground" Value="#A8A8A8"/>
      <Setter Property="FontSize" Value="12"/>
    </Style>

    <Style x:Key="Lbl" TargetType="TextBlock">
      <Setter Property="Foreground" Value="#A8A8A8"/>
      <Setter Property="FontSize" Value="11"/>
      <Setter Property="Margin" Value="0,0,0,5"/>
    </Style>

    <Style x:Key="Fld" TargetType="TextBox">
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="BorderBrush" Value="#525252"/>
      <Setter Property="BorderThickness" Value="0,0,0,1"/>
      <Setter Property="Padding" Value="8,6"/>
      <Setter Property="FontSize" Value="13"/>
      <Setter Property="CaretBrush" Value="#F1C21B"/>
      <Style.Triggers>
        <Trigger Property="IsFocused" Value="True">
          <Setter Property="BorderBrush" Value="#F1C21B"/>
        </Trigger>
      </Style.Triggers>
    </Style>

    <Style x:Key="Lst" TargetType="ListBox">
      <Setter Property="Background" Value="#262626"/>
      <Setter Property="BorderBrush" Value="#393939"/>
      <Setter Property="BorderThickness" Value="1"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="Padding" Value="0,4"/>
      <Setter Property="ScrollViewer.HorizontalScrollBarVisibility" Value="Disabled"/>
    </Style>

    <Style TargetType="ListBoxItem">
      <Setter Property="Padding" Value="10,6"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ListBoxItem">
            <Border x:Name="Bd"
                    Background="Transparent"
                    BorderBrush="Transparent"
                    BorderThickness="3,0,0,0"
                    Padding="{TemplateBinding Padding}">
              <ContentPresenter/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#333333"/>
              </Trigger>
              <Trigger Property="IsSelected" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#393939"/>
                <Setter TargetName="Bd" Property="BorderBrush" Value="#F1C21B"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="Chip" TargetType="ToggleButton">
      <Setter Property="Foreground" Value="#A8A8A8"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="Height" Value="32"/>
      <Setter Property="Padding" Value="14,0"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ToggleButton">
            <Border x:Name="Bd"
                    CornerRadius="3"
                    Background="#262626"
                    BorderBrush="#525252"
                    BorderThickness="1">
              <ContentPresenter HorizontalAlignment="Center"
                                VerticalAlignment="Center"
                                Margin="{TemplateBinding Padding}"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#333333"/>
              </Trigger>
              <Trigger Property="IsChecked" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#F1C21B"/>
                <Setter TargetName="Bd" Property="BorderBrush" Value="#F1C21B"/>
                <Setter Property="Foreground" Value="#161616"/>
                <Setter Property="FontWeight" Value="SemiBold"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="BtnGhost" TargetType="Button">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="FontSize" Value="13"/>
      <Setter Property="Height" Value="34"/>
      <Setter Property="Padding" Value="18,0"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="Bd"
                    CornerRadius="3"
                    Background="#393939"
                    BorderBrush="#525252"
                    BorderThickness="1">
              <ContentPresenter HorizontalAlignment="Center"
                                VerticalAlignment="Center"
                                Margin="{TemplateBinding Padding}"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#525252"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="BtnPrimary" TargetType="Button">
      <Setter Property="Foreground" Value="#161616"/>
      <Setter Property="FontSize" Value="13"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
      <Setter Property="Height" Value="34"/>
      <Setter Property="Padding" Value="20,0"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="Bd"
                    CornerRadius="3"
                    Background="#F1C21B"
                    BorderBrush="#F1C21B"
                    BorderThickness="1">
              <ContentPresenter HorizontalAlignment="Center"
                                VerticalAlignment="Center"
                                Margin="{TemplateBinding Padding}"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#DDB01A"/>
                <Setter TargetName="Bd" Property="BorderBrush" Value="#DDB01A"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

  </Window.Resources>

  <Grid>
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <Border Grid.Row="0" Background="#262626" BorderBrush="#393939"
            BorderThickness="0,0,0,1" Padding="20,14">
      <StackPanel>
        <TextBlock Text="Bubble Numbering" Style="{StaticResource H1}"/>
        <TextBlock Text="A numbered text note inside a detail circle, placed point by point."
                   Style="{StaticResource Sub}" Margin="0,4,0,0"/>
      </StackPanel>
    </Border>

    <Grid Grid.Row="1" Margin="20,16,20,0">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="16"/>
        <ColumnDefinition Width="*"/>
      </Grid.ColumnDefinitions>

      <DockPanel Grid.Column="0">
        <TextBlock DockPanel.Dock="Top" Text="TEXT NOTE TYPE" Style="{StaticResource Lbl}"/>
        <TextBox DockPanel.Dock="Top" x:Name="TxtTypeSearch"
                 Style="{StaticResource Fld}" Margin="0,0,0,8"/>
        <ListBox x:Name="LstTypes" Style="{StaticResource Lst}"/>
      </DockPanel>

      <DockPanel Grid.Column="2">
        <TextBlock DockPanel.Dock="Top" Text="CIRCLE LINE STYLE" Style="{StaticResource Lbl}"/>
        <TextBox DockPanel.Dock="Top" x:Name="TxtStyleSearch"
                 Style="{StaticResource Fld}" Margin="0,0,0,8"/>
        <ListBox x:Name="LstStyles" Style="{StaticResource Lst}"/>
      </DockPanel>
    </Grid>

    <Border Grid.Row="2" Margin="20,16,20,0" Background="#262626"
            BorderBrush="#393939" BorderThickness="1" Padding="16">
      <StackPanel>
        <Grid>
          <Grid.ColumnDefinitions>
            <ColumnDefinition Width="*"/>
            <ColumnDefinition Width="12"/>
            <ColumnDefinition Width="*"/>
            <ColumnDefinition Width="12"/>
            <ColumnDefinition Width="*"/>
            <ColumnDefinition Width="12"/>
            <ColumnDefinition Width="*"/>
          </Grid.ColumnDefinitions>

          <StackPanel Grid.Column="0">
            <TextBlock Text="CIRCLE DIAMETER (MM)" Style="{StaticResource Lbl}"/>
            <TextBox x:Name="TxtDiameter" Text="280" Style="{StaticResource Fld}"/>
          </StackPanel>

          <StackPanel Grid.Column="2">
            <TextBlock Text="START VALUE" Style="{StaticResource Lbl}"/>
            <TextBox x:Name="TxtStart" Text="1" Style="{StaticResource Fld}"/>
          </StackPanel>

          <StackPanel Grid.Column="4">
            <TextBlock Text="PREFIX" Style="{StaticResource Lbl}"/>
            <TextBox x:Name="TxtPrefix" Style="{StaticResource Fld}"/>
          </StackPanel>

          <StackPanel Grid.Column="6">
            <TextBlock Text="SUFFIX" Style="{StaticResource Lbl}"/>
            <TextBox x:Name="TxtSuffix" Style="{StaticResource Fld}"/>
          </StackPanel>
        </Grid>

        <Grid Margin="0,16,0,0">
          <Grid.ColumnDefinitions>
            <ColumnDefinition Width="Auto"/>
            <ColumnDefinition Width="*"/>
          </Grid.ColumnDefinitions>

          <StackPanel Grid.Column="0">
            <TextBlock Text="PICKED POINT IS THE" Style="{StaticResource Lbl}"/>
            <Grid>
              <Grid.RowDefinitions>
                <RowDefinition Height="Auto"/>
                <RowDefinition Height="Auto"/>
                <RowDefinition Height="Auto"/>
              </Grid.RowDefinitions>
              <Grid.ColumnDefinitions>
                <ColumnDefinition Width="Auto"/>
                <ColumnDefinition Width="Auto"/>
                <ColumnDefinition Width="Auto"/>
              </Grid.ColumnDefinitions>

              <ToggleButton x:Name="TglTop" Grid.Row="0" Grid.Column="1"
                            Content="Top" Width="104" Margin="3"
                            Style="{StaticResource Chip}"/>
              <ToggleButton x:Name="TglLeft" Grid.Row="1" Grid.Column="0"
                            Content="Left" Width="104" Margin="3"
                            Style="{StaticResource Chip}"/>
              <ToggleButton x:Name="TglCenter" Grid.Row="1" Grid.Column="1"
                            Content="Center" Width="104" Margin="3"
                            Style="{StaticResource Chip}"/>
              <ToggleButton x:Name="TglRight" Grid.Row="1" Grid.Column="2"
                            Content="Right" Width="104" Margin="3"
                            Style="{StaticResource Chip}"/>
              <ToggleButton x:Name="TglBottom" Grid.Row="2" Grid.Column="1"
                            Content="Bottom" Width="104" Margin="3"
                            Style="{StaticResource Chip}" IsChecked="True"/>
            </Grid>
          </StackPanel>

          <StackPanel Grid.Column="1" HorizontalAlignment="Right" VerticalAlignment="Bottom">
            <TextBlock Text="DIRECTION" Style="{StaticResource Lbl}"
                       HorizontalAlignment="Right"/>
            <StackPanel Orientation="Horizontal" HorizontalAlignment="Right"
                        Margin="0,0,0,12">
              <ToggleButton x:Name="TglUp" Content="Count up" Width="104"
                            Margin="3" Style="{StaticResource Chip}" IsChecked="True"/>
              <ToggleButton x:Name="TglDown" Content="Count down" Width="104"
                            Margin="3" Style="{StaticResource Chip}"/>
            </StackPanel>
            <TextBlock Text="SEQUENCE PREVIEW" Style="{StaticResource Lbl}"
                       HorizontalAlignment="Right"/>
            <TextBlock x:Name="TxtPreview" Text="-" Foreground="#F1C21B"
                       FontSize="14" HorizontalAlignment="Right"/>
          </StackPanel>
        </Grid>
      </StackPanel>
    </Border>

    <TextBlock Grid.Row="3" x:Name="TxtStatus" Margin="20,12,20,0"
               Foreground="#A8A8A8" FontSize="12" TextWrapping="Wrap"
               Text="Pick points in the active view one by one. Press ESC to finish."/>

    <Border Grid.Row="4" Margin="0,14,0,0" Background="#262626" BorderBrush="#393939"
            BorderThickness="0,1,0,0" Padding="20,12">
      <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
        <Button x:Name="BtnCancel" Content="Cancel" Style="{StaticResource BtnGhost}"/>
        <Button x:Name="BtnStart" Content="Start placing"
                Style="{StaticResource BtnPrimary}" Margin="10,0,0,0"/>
      </StackPanel>
    </Border>

  </Grid>
</Window>
"""


# ------------------------------------------------------------------- form ---
def show_dialog(type_rows, style_rows):
    """Return a settings dict, or None if cancelled."""
    window = XamlReader.Parse(XAML)

    txt_type_search = window.FindName("TxtTypeSearch")
    txt_style_search = window.FindName("TxtStyleSearch")
    lst_types = window.FindName("LstTypes")
    lst_styles = window.FindName("LstStyles")
    txt_diameter = window.FindName("TxtDiameter")
    txt_start = window.FindName("TxtStart")
    txt_prefix = window.FindName("TxtPrefix")
    txt_suffix = window.FindName("TxtSuffix")
    txt_preview = window.FindName("TxtPreview")
    txt_status = window.FindName("TxtStatus")
    btn_cancel = window.FindName("BtnCancel")
    btn_start = window.FindName("BtnStart")

    anchors = [
        (window.FindName("TglTop"), "top"),
        (window.FindName("TglLeft"), "left"),
        (window.FindName("TglCenter"), "center"),
        (window.FindName("TglRight"), "right"),
        (window.FindName("TglBottom"), "bottom"),
    ]

    directions = [
        (window.FindName("TglUp"), False),
        (window.FindName("TglDown"), True),
    ]

    result = {}

    def selected_tag(listbox):
        item = listbox.SelectedItem
        return item.Tag if item is not None else None

    def fill_list(listbox, rows, needle):
        keep = selected_tag(listbox)
        listbox.Items.Clear()
        low = (needle or "").strip().lower()
        restore = None
        for display, tag in rows:
            if low and low not in display.lower():
                continue
            item = ListBoxItem()
            item.Content = display
            item.Tag = tag
            listbox.Items.Add(item)
            if keep is not None and tag is keep:
                restore = item
        if restore is not None:
            listbox.SelectedItem = restore
        elif listbox.Items.Count > 0:
            listbox.SelectedIndex = 0

    def set_status(message, is_error):
        txt_status.Text = message
        txt_status.Foreground = brush(CLR_ERROR if is_error else CLR_SUBTEXT)

    def update_preview():
        kind, index, pad, error = parse_start(txt_start.Text)
        if kind is None:
            txt_preview.Text = "-"
            return
        descending = group_value(directions, False)
        prefix = txt_prefix.Text or ""
        suffix = txt_suffix.Text or ""
        labels = []
        value = index
        finished = False
        while len(labels) < 4:
            labels.append(make_label(kind, value, pad, prefix, suffix))
            if descending:
                if value <= 1:
                    finished = True
                    break
                value -= 1
            else:
                value += 1
        txt_preview.Text = "  ".join(labels) + ("" if finished else "  ...")

    def on_type_search(sender, args):
        fill_list(lst_types, type_rows, txt_type_search.Text)

    def on_style_search(sender, args):
        fill_list(lst_styles, style_rows, txt_style_search.Text)

    def on_sequence_changed(sender, args):
        update_preview()

    def bind_toggle_group(items):
        """Radio behaviour for a list of (ToggleButton, value) pairs."""
        guard = [False]

        def on_checked(sender, args):
            if guard[0]:
                return
            guard[0] = True
            for toggle, _value in items:
                if toggle is not sender:
                    toggle.IsChecked = False
            guard[0] = False

        def on_unchecked(sender, args):
            if guard[0]:
                return
            if not [t for t, _v in items if t.IsChecked]:
                guard[0] = True
                sender.IsChecked = True
                guard[0] = False

        for toggle, _value in items:
            toggle.Checked += RoutedEventHandler(on_checked)
            toggle.Unchecked += RoutedEventHandler(on_unchecked)

    def group_value(items, fallback):
        for toggle, value in items:
            if toggle.IsChecked:
                return value
        return fallback

    def on_cancel(sender, args):
        window.Close()

    def on_start(sender, args):
        text_item = lst_types.SelectedItem
        if text_item is None:
            set_status("Select a text note type.", True)
            return

        style_item = lst_styles.SelectedItem

        try:
            diameter_mm = float((txt_diameter.Text or "").strip())
        except ValueError:
            set_status("Circle diameter must be a number.", True)
            return
        if diameter_mm <= 0:
            set_status("Circle diameter must be greater than zero.", True)
            return

        kind, index, pad, error = parse_start(txt_start.Text)
        if kind is None:
            set_status(error, True)
            return

        descending = group_value(directions, False)
        anchor = group_value(anchors, "bottom")

        result["text_type"] = text_item.Tag
        result["line_style"] = style_item.Tag if style_item is not None else None
        result["diameter_mm"] = diameter_mm
        result["kind"] = kind
        result["index"] = index
        result["pad"] = pad
        result["descending"] = descending
        result["prefix"] = txt_prefix.Text or ""
        result["suffix"] = txt_suffix.Text or ""
        result["anchor"] = anchor
        window.Close()

    txt_type_search.TextChanged += TextChangedEventHandler(on_type_search)
    txt_style_search.TextChanged += TextChangedEventHandler(on_style_search)
    txt_start.TextChanged += TextChangedEventHandler(on_sequence_changed)
    txt_prefix.TextChanged += TextChangedEventHandler(on_sequence_changed)
    txt_suffix.TextChanged += TextChangedEventHandler(on_sequence_changed)

    bind_toggle_group(anchors)
    bind_toggle_group(directions)

    for toggle, _value in directions:
        toggle.Checked += RoutedEventHandler(on_sequence_changed)

    btn_cancel.Click += RoutedEventHandler(on_cancel)
    btn_start.Click += RoutedEventHandler(on_start)

    fill_list(lst_types, type_rows, "")
    fill_list(lst_styles, style_rows, "")
    update_preview()

    frame = DispatcherFrame()

    def on_closed(sender, args):
        frame.Continue = False

    window.Closed += EventHandler(on_closed)
    window.Show()
    Dispatcher.PushFrame(frame)

    return result if result else None


# -------------------------------------------------------------- placement ---
def place_bubbles(view, settings):
    x_axis = view.RightDirection
    y_axis = view.UpDirection
    radius = (settings["diameter_mm"] / MM_PER_FT) / 2.0
    anchor = settings["anchor"]
    line_style = settings["line_style"]

    options = DB.TextNoteOptions()
    options.TypeId = settings["text_type"].Id
    options.HorizontalAlignment = DB.HorizontalTextAlignment.Center
    options.VerticalAlignment = DB.VerticalTextAlignment.Middle

    anchor_word = ANCHOR_WORDS[anchor]
    index = settings["index"]
    placed = 0
    hit_floor = False

    while True:
        prompt = "Pick the {} of bubble '{}'   -   ESC to finish".format(
            anchor_word,
            make_label(settings["kind"], index, settings["pad"],
                       settings["prefix"], settings["suffix"])
        )
        try:
            picked = uidoc.Selection.PickPoint(prompt)
        except RvtEx.OperationCanceledException:
            break
        except RvtEx.InvalidOperationException:
            forms.alert("This view does not allow picking points.", title="Bubble Numbering")
            break

        if anchor == "bottom":
            center = picked.Add(y_axis.Multiply(radius))
        elif anchor == "top":
            center = picked.Subtract(y_axis.Multiply(radius))
        elif anchor == "left":
            center = picked.Add(x_axis.Multiply(radius))
        elif anchor == "right":
            center = picked.Subtract(x_axis.Multiply(radius))
        else:
            center = picked

        label = make_label(settings["kind"], index, settings["pad"],
                           settings["prefix"], settings["suffix"])

        t = DB.Transaction(doc, "Place bubble {}".format(label))
        t.Start()
        try:
            DB.TextNote.Create(doc, view.Id, center, label, options)

            circle = DB.Ellipse.CreateCurve(
                center, radius, radius, x_axis, y_axis, 0.0, 2.0 * math.pi
            )
            detail_curve = doc.Create.NewDetailCurve(view, circle)
            if line_style is not None:
                detail_curve.LineStyle = line_style

            t.Commit()
        except Exception as ex:
            t.RollBack()
            forms.alert(
                "Could not place bubble '{}':\n\n{}".format(label, ex),
                title="Bubble Numbering"
            )
            break

        index += -1 if settings["descending"] else 1
        placed += 1

        if settings["descending"] and index < 1:
            hit_floor = True
            break

    return placed, hit_floor


# ------------------------------------------------------------------- main ---
def main():
    view = doc.ActiveView

    if view.IsTemplate or view.ViewType not in PLACEABLE_VIEW_TYPES:
        forms.alert(
            "Open a plan, section, elevation, detail, drafting or legend view first.\n"
            "Text notes and detail lines cannot be placed in the current view.",
            title="Bubble Numbering"
        )
        return

    type_rows = collect_text_types()
    if not type_rows:
        forms.alert("This project has no text note types.", title="Bubble Numbering")
        return

    style_rows = collect_line_styles()

    settings = show_dialog(type_rows, style_rows)
    if not settings:
        return

    placed, hit_floor = place_bubbles(view, settings)
    message = "Placed {} bubble{} in '{}'.".format(
        placed, "" if placed == 1 else "s", view.Name
    )
    if hit_floor:
        message += "\n\nThe count-down reached 1, so placement stopped there."
    forms.alert(message, title="Bubble Numbering")


main()
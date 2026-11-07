# -*- coding: utf-8 -*-
__doc__ = """__________________________________________________
Description:

Links several Revit models in one go. Add files or a whole folder, pick how they are placed (Origin to Origin, Shared Coordinates, Project Base Point or Center to Center), Attachment or Overlay, the workset they go on, and whether they are pinned.

Files that are already linked, or the model you are working in, are marked and skipped. Each file is linked in its own step, so one bad file doesn't stop the rest, and one Undo removes them all. Each file shows what happened after linking.
__________________________________________________
How-to:

-> Click on the button
-> Click Add files or Add folder to list the Revit models
-> Untick any file you don't want, or remove it from the list
-> On the right, pick the placement, Attachment or Overlay, the workset and the pin option
-> Click Link ticked files
-> Each file shows its result; add more files or click Close
__________________________________________________
Author: Mohamed Bedair"""

__author__ = "Mohamed Bedair"

import re

import clr

clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")
clr.AddReference("System.Xml")
clr.AddReference("System.Windows.Forms")

from Autodesk.Revit.DB import (
    AttachmentType,
    BuiltInParameter,
    ElementId,
    FilteredElementCollector,
    FilteredWorksetCollector,
    ImportPlacement,
    ModelPathUtils,
    RevitLinkInstance,
    RevitLinkOptions,
    RevitLinkType,
    Transaction,
    TransactionGroup,
    WorksetKind,
)
from Autodesk.Revit.UI import TaskDialog

from Microsoft.Win32 import OpenFileDialog
from System import EventHandler
from System.IO import Directory, File, FileInfo, Path
from System.Windows import (
    CornerRadius,
    FontWeights,
    RoutedEventHandler,
    TextTrimming,
    Thickness,
    VerticalAlignment,
    Visibility,
)
from System.Windows.Controls import (
    Border,
    CheckBox,
    Dock,
    DockPanel,
    StackPanel,
    TextBlock,
    TextChangedEventHandler,
)
from System.Windows.Controls.Primitives import ToggleButton
from System.Windows.Forms import DialogResult, FolderBrowserDialog
from System.Windows.Input import Cursors, Mouse, MouseButtonEventHandler
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Markup import XamlReader
from System.Windows.Media import BrushConverter
from System.Windows.Threading import Dispatcher, DispatcherFrame
from bd_combo_search import enable_combo_search

doc = __revit__.ActiveUIDocument.Document  # noqa: F821
TOOL = "Link Files"

C_TEXT = "#F4F4F4"
C_SUBTEXT = "#A8A8A8"
C_MUTED = "#8D8D8D"
C_ACCENT = "#F1C21B"
C_OK = "#42BE65"
C_WARN = "#F1C21B"
C_BAD = "#FF8389"
DOT = u"  \u00b7  "

W_SIZE = 80
W_DATE = 120
W_STATE = 150

PLACEMENTS = (
    ("Origin to Origin", ImportPlacement.Origin, "Internal origin of the link on the internal origin of this model"),
    ("Shared Coordinates", ImportPlacement.Shared, "By the shared coordinates the two models agree on"),
    ("Project Base Point", ImportPlacement.Site, "Project base point of the link on the project base point here"),
    ("Center to Center", ImportPlacement.Centered, "Centre of the link on the centre of this model"),
)
ATTACHMENTS = (
    ("Overlay", AttachmentType.Overlay, "Not carried into models that link this one"),
    ("Attachment", AttachmentType.Attachment, "Carried along when this model is linked elsewhere"),
)
BACKUP = re.compile(r"\.\d{4}\.rvt$", re.IGNORECASE)  # Revit backups: name.0001.rvt

_BC = BrushConverter()
_BRUSHES = {}


def brush(hex_string):
    if hex_string not in _BRUSHES:
        _BRUSHES[hex_string] = _BC.ConvertFromString(hex_string)
    return _BRUSHES[hex_string]


def id_value(id_obj):
    """ElementId / WorksetId integer value, valid on Revit 2024 through 2027."""
    try:
        return id_obj.Value
    except AttributeError:
        return id_obj.IntegerValue


def plural(n, word, word_pl=None):
    return "{0} {1}".format(n, word if n == 1 else (word_pl or word + "s"))


def norm(path):
    try:
        return Path.GetFullPath(path).lower()
    except Exception:
        return (path or "").lower()


# ---------------------------------------------------------------------------
# Project data
# ---------------------------------------------------------------------------
def linked_paths():
    """Lower-case full paths of every Revit link already in the project."""
    out = set()
    for link_type in FilteredElementCollector(doc).OfClass(RevitLinkType):
        try:
            path = ModelPathUtils.ConvertModelPathToUserVisiblePath(
                link_type.GetExternalFileReference().GetAbsolutePath())
            if path:
                out.add(norm(path))
        except Exception:
            pass
    return out


def host_paths():
    out = set()
    if doc.PathName:
        out.add(norm(doc.PathName))
    if doc.IsWorkshared:
        try:
            central = ModelPathUtils.ConvertModelPathToUserVisiblePath(doc.GetWorksharingCentralModelPath())
            if central:
                out.add(norm(central))
        except Exception:
            pass
    return out


def collect_worksets():
    if not doc.IsWorkshared:
        return [], -1
    worksets = list(FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset))
    worksets.sort(key=lambda w: w.Name.lower())
    active = id_value(doc.GetWorksetTable().GetActiveWorksetId())
    ids = [id_value(w.Id) for w in worksets]
    return worksets, (ids.index(active) if active in ids else 0)


# ---------------------------------------------------------------------------
# File list
# ---------------------------------------------------------------------------
def file_entry(path):
    entry = {"path": path, "name": Path.GetFileName(path), "folder": Path.GetDirectoryName(path) or "",
             "size": "", "date": "", "result": None, "box": None, "border": None, "state": "ready"}
    try:
        info = FileInfo(path)
        entry["size"] = "{0:,.1f} MB".format(info.Length / 1048576.0)
        entry["date"] = info.LastWriteTime.ToString("yyyy-MM-dd HH:mm")
    except Exception:
        pass
    return entry


def refresh_states(files):
    """ready / linked (already in the project) / host (this model) / missing."""
    have = linked_paths()
    host = host_paths()
    for entry in files:
        key = norm(entry["path"])
        if not File.Exists(entry["path"]):
            entry["state"] = "missing"
        elif key in host:
            entry["state"] = "host"
        elif key in have:
            entry["state"] = "linked"
        else:
            entry["state"] = "ready"


STATE_TEXT = {"ready": ("Ready", C_SUBTEXT), "linked": ("Already linked", C_MUTED),
              "host": ("This model", C_MUTED), "missing": ("File not found", C_BAD)}


# ---------------------------------------------------------------------------
# Linking
# ---------------------------------------------------------------------------
def set_workset(element, workset_id):
    try:
        param = element.get_Parameter(BuiltInParameter.ELEM_PARTITION_PARAM)
        if param is not None and not param.IsReadOnly and id_value(element.WorksetId) != workset_id:
            param.Set(workset_id)
    except Exception:
        pass


def link_one(entry, settings, workset):
    """One file in its own transaction. Returns ('ok' / 'bad', text)."""
    placement = PLACEMENTS[settings["placement"]]
    attachment = ATTACHMENTS[settings["attachment"]]
    t = Transaction(doc, u"Link {0}".format(entry["name"]))
    t.Start()
    try:
        model_path = ModelPathUtils.ConvertUserVisiblePathToModelPath(entry["path"])
        result = RevitLinkType.Create(doc, model_path, RevitLinkOptions(settings["relative"]))
        if result.ElementId is None or result.ElementId == ElementId.InvalidElementId:
            t.RollBack()
            return "bad", u"Not linked: {0}".format(result.LoadResult)
        link_type = doc.GetElement(result.ElementId)
        instance = RevitLinkInstance.Create(doc, result.ElementId, placement[1])
        notes = [placement[0]]
        try:
            if link_type.AttachmentType != attachment[1]:
                link_type.AttachmentType = attachment[1]
            notes.append(attachment[0])
        except Exception as ex:
            notes.append(u"type not changed ({0})".format(ex))
        if workset is not None:
            set_workset(link_type, id_value(workset.Id))
            set_workset(instance, id_value(workset.Id))
            notes.append(u"on " + workset.Name)
        if settings["pin"]:
            instance.Pinned = True
            notes.append("pinned")
        t.Commit()
        load = str(result.LoadResult)
        head = "Linked" if load in ("LinkLoaded", "Success") else u"Linked ({0})".format(load)
        return "ok", head + u": " + u", ".join(notes)
    except Exception as ex:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        return "bad", u"Failed: {0}".format(ex)


def link_files(entries, settings, workset):
    group = TransactionGroup(doc, TOOL)
    group.Start()
    Mouse.OverrideCursor = Cursors.Wait
    try:
        for entry in entries:
            entry["result"] = link_one(entry, settings, workset)
        group.Assimilate()
    except Exception:
        if group.HasStarted() and not group.HasEnded():
            group.RollBack()
        raise
    finally:
        Mouse.OverrideCursor = None


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Link Files" Width="1220" Height="740" MinWidth="980" MinHeight="500"
        WindowStartupLocation="CenterScreen" Background="#161616" FontFamily="Segoe UI">
  <Window.Resources>


    <Style x:Key="DarkComboItem" TargetType="ComboBoxItem">
      <Setter Property="Background" Value="Transparent"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Padding" Value="8,5"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ComboBoxItem">
            <Border x:Name="Bd" Background="{TemplateBinding Background}"
                    Padding="{TemplateBinding Padding}" CornerRadius="3">
              <ContentPresenter/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsHighlighted" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#525252"/>
                <Setter Property="Foreground" Value="#F1C21B"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="DarkCombo" TargetType="ComboBox">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="Height" Value="26"/>
      <Setter Property="ItemContainerStyle" Value="{StaticResource DarkComboItem}"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ComboBox">
            <Grid>
              <ToggleButton x:Name="Toggle" Focusable="False" ClickMode="Press"
                            IsChecked="{Binding IsDropDownOpen, Mode=TwoWay,
                                        RelativeSource={RelativeSource TemplatedParent}}">
                <ToggleButton.Template>
                  <ControlTemplate TargetType="ToggleButton">
                    <Border x:Name="Bd" Background="#393939" BorderBrush="#525252"
                            BorderThickness="1" CornerRadius="4">
                      <Path x:Name="Arrow" HorizontalAlignment="Right" VerticalAlignment="Center"
                            Margin="0,0,9,0" Data="M 0 0 L 4 4 L 8 0 Z" Fill="#A8A8A8"/>
                    </Border>
                    <ControlTemplate.Triggers>
                      <Trigger Property="IsMouseOver" Value="True">
                        <Setter TargetName="Bd" Property="BorderBrush" Value="#F1C21B"/>
                      </Trigger>
                      <Trigger Property="IsEnabled" Value="False">
                        <Setter TargetName="Bd" Property="Background" Value="#262626"/>
                        <Setter TargetName="Arrow" Property="Fill" Value="#525252"/>
                      </Trigger>
                    </ControlTemplate.Triggers>
                  </ControlTemplate>
                </ToggleButton.Template>
              </ToggleButton>
              <ContentPresenter x:Name="ContentSite" IsHitTestVisible="False"
                                Content="{TemplateBinding SelectionBoxItem}"
                                ContentTemplate="{TemplateBinding SelectionBoxItemTemplate}"
                                Margin="9,0,26,0" VerticalAlignment="Center"/>
              <Popup x:Name="Popup" Placement="Bottom" AllowsTransparency="True"
                     Focusable="False" PopupAnimation="Slide"
                     IsOpen="{TemplateBinding IsDropDownOpen}">
                <Border Background="#262626" BorderBrush="#525252" BorderThickness="1"
                        CornerRadius="4" Margin="0,2,0,0" MaxHeight="280"
                        MinWidth="{TemplateBinding ActualWidth}">
                  <ScrollViewer SnapsToDevicePixels="True">
                    <StackPanel IsItemsHost="True" Margin="3"/>
                  </ScrollViewer>
                </Border>
              </Popup>
            </Grid>
            <ControlTemplate.Triggers>
              <Trigger Property="IsEnabled" Value="False">
                <Setter Property="Foreground" Value="#525252"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="FlatBtn" TargetType="Button">
      <Setter Property="Background" Value="#F1C21B"/>
      <Setter Property="Foreground" Value="#161616"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="Height" Value="30"/>
      <Setter Property="Padding" Value="18,0"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="Bd" Background="{TemplateBinding Background}" CornerRadius="5"
                    Padding="{TemplateBinding Padding}">
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

    <Style x:Key="GhostBtn" TargetType="Button" BasedOn="{StaticResource FlatBtn}">
      <Setter Property="Background" Value="#525252"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
    </Style>

    <Style x:Key="HeaderCell" TargetType="TextBlock">
      <Setter Property="Foreground" Value="#A8A8A8"/>
      <Setter Property="FontSize" Value="11"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
      <Setter Property="Margin" Value="0,0,8,0"/>
    </Style>


    <Style x:Key="Seg" TargetType="ToggleButton">
      <Setter Property="Foreground" Value="#C6C6C6"/>
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="BorderBrush" Value="Transparent"/>
      <Setter Property="FontSize" Value="11"/>
      <Setter Property="Height" Value="24"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ToggleButton">
            <Border x:Name="Bd" Background="{TemplateBinding Background}"
                    BorderBrush="{TemplateBinding BorderBrush}" BorderThickness="0,0,0,2" Padding="8,0">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsChecked" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#F1C21B"/>
                <Setter Property="Foreground" Value="#161616"/>
              </Trigger>
              <Trigger Property="IsEnabled" Value="False">
                <Setter TargetName="Bd" Property="Opacity" Value="0.35"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style TargetType="CheckBox">
      <Setter Property="Foreground" Value="#A8A8A8"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="VerticalAlignment" Value="Center"/>
      <Setter Property="Cursor" Value="Hand"/>
    </Style>
  </Window.Resources>

  <Grid Margin="16">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>
    <Grid.ColumnDefinitions>
      <ColumnDefinition Width="*"/>
      <ColumnDefinition Width="300"/>
    </Grid.ColumnDefinitions>

    <StackPanel Grid.Row="0" Grid.ColumnSpan="2" Margin="0,0,0,12">
      <TextBlock Text="LINK FILES" Foreground="#F1C21B" FontSize="16" FontWeight="Bold"/>
      <TextBlock x:Name="SubTitle" Foreground="#A8A8A8" FontSize="12" Margin="0,3,0,0"/>
    </StackPanel>

    <DockPanel Grid.Row="1" Grid.Column="0" Margin="0,0,14,0">
      <Border DockPanel.Dock="Top" Background="#262626" CornerRadius="6" Padding="10" Margin="0,0,0,10">
        <DockPanel>
          <Button x:Name="ClearBtn" DockPanel.Dock="Right" Content="Clear list" Style="{StaticResource GhostBtn}"
                  Height="26" Padding="14,0" Margin="8,0,0,0"/>
          <Button x:Name="RemoveBtn" DockPanel.Dock="Right" Content="Remove ticked" Style="{StaticResource GhostBtn}"
                  Height="26" Padding="14,0" Margin="8,0,0,0"/>
          <Button x:Name="FolderBtn" DockPanel.Dock="Right" Content="Add folder..." Style="{StaticResource GhostBtn}"
                  Height="26" Padding="14,0" Margin="8,0,0,0"/>
          <Button x:Name="AddBtn" DockPanel.Dock="Right" Content="Add files..." Style="{StaticResource FlatBtn}"
                  Height="26" Padding="14,0" Margin="16,0,0,0"/>
          <Grid>
            <Border Background="#393939" BorderBrush="#525252" BorderThickness="1" CornerRadius="4" Height="26">
              <TextBox x:Name="SearchBox" Background="Transparent" BorderThickness="0"
                       Foreground="#F4F4F4" CaretBrush="#F1C21B" FontSize="12"
                       VerticalContentAlignment="Center" Padding="8,0"/>
            </Border>
            <TextBlock x:Name="SearchHint" Text="Search files..." Foreground="#6F6F6F"
                       FontSize="12" Margin="10,0,0,0" VerticalAlignment="Center" IsHitTestVisible="False"/>
          </Grid>
        </DockPanel>
      </Border>
      <DockPanel x:Name="HeaderRow" DockPanel.Dock="Top" Margin="12,0,30,6"/>
      <Grid>
        <ScrollViewer VerticalScrollBarVisibility="Auto" HorizontalScrollBarVisibility="Disabled">
          <StackPanel x:Name="RowsPanel"/>
        </ScrollViewer>
        <TextBlock x:Name="EmptyText" Foreground="#8D8D8D" FontSize="13" TextWrapping="Wrap"
                   HorizontalAlignment="Center" VerticalAlignment="Center" TextAlignment="Center" Margin="40"
                   Text="No files yet. Click Add files or Add folder to pick the Revit models to link."/>
      </Grid>
    </DockPanel>

    <Border Grid.Row="1" Grid.Column="1" Background="#262626" CornerRadius="6" Padding="14">
      <StackPanel>
        <TextBlock Text="PLACEMENT" Style="{StaticResource HeaderCell}" Margin="0,0,0,6"/>
        <StackPanel x:Name="PlacementPanel"/>
        <TextBlock x:Name="PlacementHint" Foreground="#8D8D8D" FontSize="11" TextWrapping="Wrap" Margin="0,6,0,16"/>

        <TextBlock Text="REFERENCE TYPE" Style="{StaticResource HeaderCell}" Margin="0,0,0,6"/>
        <StackPanel x:Name="AttachmentPanel" Orientation="Horizontal"/>
        <TextBlock x:Name="AttachmentHint" Foreground="#8D8D8D" FontSize="11" TextWrapping="Wrap" Margin="0,6,0,16"/>

        <TextBlock Text="WORKSET" Style="{StaticResource HeaderCell}" Margin="0,0,0,6"/>
        <ComboBox x:Name="WorksetCombo" Style="{StaticResource DarkCombo}"/>
        <TextBlock Foreground="#8D8D8D" FontSize="11" TextWrapping="Wrap" Margin="0,6,0,16"
                   Text="The link and its placed copy both go on this workset."/>

        <TextBlock Text="OPTIONS" Style="{StaticResource HeaderCell}" Margin="0,0,0,8"/>
        <CheckBox x:Name="PinCheck" Content="Pin the links after placing them" Margin="0,0,0,8"/>
        <CheckBox x:Name="RelativeCheck" Content="Save the path as relative"/>
      </StackPanel>
    </Border>

    <Grid Grid.Row="2" Grid.ColumnSpan="2" Margin="0,12,0,0">
      <TextBlock x:Name="CountText" Foreground="#A8A8A8" FontSize="12" VerticalAlignment="Center"
                 HorizontalAlignment="Left" TextWrapping="Wrap" Margin="0,0,320,0"/>
      <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
        <Button x:Name="CloseBtn" Content="Close" Style="{StaticResource GhostBtn}"/>
        <Button x:Name="LinkBtn" Content="Link ticked files" Style="{StaticResource FlatBtn}" Margin="10,0,0,0"/>
      </StackPanel>
    </Grid>
  </Grid>
</Window>
"""


def text_block(text, size=12, color=C_TEXT, bold=False):
    block = TextBlock()
    block.Text = text
    block.FontSize = size
    block.Foreground = brush(color)
    block.VerticalAlignment = VerticalAlignment.Center
    block.TextTrimming = TextTrimming.CharacterEllipsis
    if bold:
        block.FontWeight = FontWeights.SemiBold
    return block


def fixed(child, width):
    holder = Border()
    holder.Width = width
    holder.Margin = Thickness(8, 0, 0, 0)
    holder.VerticalAlignment = VerticalAlignment.Center
    holder.Child = child
    return holder


def make_header(window):
    header = window.FindName("HeaderRow")
    style = window.Resources["HeaderCell"]
    for text, width in (("STATUS", W_STATE), ("MODIFIED", W_DATE), ("SIZE", W_SIZE)):
        block = TextBlock()
        block.Text = text
        block.Style = style
        cell = fixed(block, width)
        DockPanel.SetDock(cell, Dock.Right)
        header.Children.Add(cell)
    name = TextBlock()
    name.Text = "FILE"
    name.Style = style
    name.Margin = Thickness(28, 0, 0, 0)
    header.Children.Add(name)


def build_row(entry, on_change):
    border = Border()
    border.Background = brush("#262626")
    border.CornerRadius = CornerRadius(6)
    border.Padding = Thickness(12, 8, 12, 8)
    border.Margin = Thickness(0, 0, 0, 6)
    usable = entry["state"] == "ready"

    dock = DockPanel()
    state_text, state_color = STATE_TEXT[entry["state"]]
    if entry["result"] is not None and entry["result"][0] == "ok":
        state_text, state_color = "Linked now", C_OK
    for cell in (fixed(text_block(state_text, 12, state_color), W_STATE),
                 fixed(text_block(entry["date"], 12, C_SUBTEXT), W_DATE),
                 fixed(text_block(entry["size"], 12, C_SUBTEXT), W_SIZE)):
        DockPanel.SetDock(cell, Dock.Right)
        dock.Children.Add(cell)

    box = CheckBox()
    box.IsChecked = usable and entry.get("ticked", True)
    box.IsEnabled = usable
    box.Margin = Thickness(0, 0, 12, 0)
    box.VerticalAlignment = VerticalAlignment.Center
    DockPanel.SetDock(box, Dock.Left)
    dock.Children.Add(box)
    entry["box"] = box

    info = StackPanel()
    info.VerticalAlignment = VerticalAlignment.Center
    info.Children.Add(text_block(entry["name"], 13, C_TEXT if usable else C_MUTED, bold=True))
    folder = text_block(entry["folder"], 11, C_SUBTEXT)
    folder.ToolTip = entry["path"]
    info.Children.Add(folder)
    if entry["result"] is not None:
        kind, text = entry["result"]
        line = text_block(text, 11, C_OK if kind == "ok" else C_BAD, bold=True)
        line.ToolTip = text
        info.Children.Add(line)
    dock.Children.Add(info)
    border.Child = dock

    def on_box(sender, args):
        entry["ticked"] = bool(box.IsChecked)
        on_change()

    def on_row(sender, args):
        if not usable or isinstance(args.OriginalSource, CheckBox):
            return
        box.IsChecked = not bool(box.IsChecked)
        entry["ticked"] = bool(box.IsChecked)
        on_change()

    box.Click += RoutedEventHandler(on_box)
    if usable:
        border.Cursor = Cursors.Hand
    border.MouseLeftButtonUp += MouseButtonEventHandler(on_row)
    entry["border"] = border
    return border


def seg_group(window, panel, options, current, on_pick, hint):
    """ToggleButtons that behave like radio buttons. options: [(label, value, tip)]."""
    buttons = []

    def pick(index):
        for i, b in enumerate(buttons):
            b.IsChecked = (i == index)
        hint.Text = options[index][2]
        on_pick(index)

    def handler_for(index):
        def handler(sender, args):
            pick(index)

        return handler

    for index, option in enumerate(options):
        b = ToggleButton()
        b.Style = window.Resources["Seg"]
        b.Content = option[0]
        b.Height = 28
        b.Margin = Thickness(0, 0, 4, 4)
        b.ToolTip = option[2]
        b.Click += RoutedEventHandler(handler_for(index))
        buttons.append(b)
        panel.Children.Add(b)
    pick(current)


def show_window(files, settings, worksets, banner):
    """Returns 'link', 'refresh' (the list changed) or None (closed)."""
    window = XamlReader.Parse(XAML)
    try:
        WindowInteropHelper(window).Owner = __revit__.MainWindowHandle  # noqa: F821
    except Exception:
        pass
    rows_panel = window.FindName("RowsPanel")
    search_box = window.FindName("SearchBox")
    search_hint = window.FindName("SearchHint")
    count_text = window.FindName("CountText")
    link_btn = window.FindName("LinkBtn")
    empty_text = window.FindName("EmptyText")
    workset_combo = window.FindName("WorksetCombo")
    pin_check = window.FindName("PinCheck")
    relative_check = window.FindName("RelativeCheck")

    window.FindName("SubTitle").Text = u"{0}{1}Add the Revit models, set how they are placed on the right, " \
                                       u"then click Link ticked files.".format(doc.Title, DOT)
    make_header(window)

    def ticked():
        return [f for f in files if f["box"] is not None and f["box"].IsChecked]

    def update():
        chosen = ticked()
        empty_text.Visibility = Visibility.Collapsed if files else Visibility.Visible
        visible = len([f for f in files if f["border"].Visibility == Visibility.Visible])
        text = "Showing {0} of {1}{2}{3} ticked".format(visible, plural(len(files), "file"), DOT, len(chosen))
        if banner[0]:
            text = banner[0] + DOT + text
        count_text.Text = text
        link_btn.Content = "Link ticked files ({0})".format(len(chosen)) if chosen else "Link ticked files"
        link_btn.IsEnabled = bool(chosen)

    for entry in files:
        rows_panel.Children.Add(build_row(entry, update))

    # settings panel
    def set_placement(index):
        settings["placement"] = index

    def set_attachment(index):
        settings["attachment"] = index

    seg_group(window, window.FindName("PlacementPanel"), PLACEMENTS, settings["placement"], set_placement,
              window.FindName("PlacementHint"))
    seg_group(window, window.FindName("AttachmentPanel"), ATTACHMENTS, settings["attachment"], set_attachment,
              window.FindName("AttachmentHint"))
    if worksets:
        for workset in worksets:
            workset_combo.Items.Add(workset.Name)
        workset_combo.SelectedIndex = settings["workset"]
    else:
        workset_combo.Items.Add("Not workshared")
        workset_combo.SelectedIndex = 0
        workset_combo.IsEnabled = False
    pin_check.IsChecked = settings["pin"]
    relative_check.IsChecked = settings["relative"]

    outcome = [None]

    def save_settings():
        if worksets and workset_combo.SelectedIndex >= 0:
            settings["workset"] = workset_combo.SelectedIndex
        settings["pin"] = bool(pin_check.IsChecked)
        settings["relative"] = bool(relative_check.IsChecked)
        for entry in files:
            if entry["box"] is not None and entry["box"].IsEnabled:
                entry["ticked"] = bool(entry["box"].IsChecked)

    def add_paths(paths):
        known = set([norm(f["path"]) for f in files])
        added = 0
        for path in paths:
            if norm(path) in known:
                continue
            known.add(norm(path))
            files.append(file_entry(path))
            added += 1
        banner[0] = "Added {0}".format(plural(added, "file")) if added else "Those files are already in the list"
        save_settings()
        outcome[0] = "refresh"
        window.Close()

    def on_add(sender, args):
        dialog = OpenFileDialog()
        dialog.Title = "Revit models to link"
        dialog.Filter = "Revit models (*.rvt)|*.rvt"
        dialog.Multiselect = True
        if files:
            try:
                dialog.InitialDirectory = files[-1]["folder"]
            except Exception:
                pass
        if not dialog.ShowDialog(window):
            return
        add_paths(list(dialog.FileNames))

    def on_folder(sender, args):
        dialog = FolderBrowserDialog()
        dialog.Description = "Folder with the Revit models to link (backup copies like name.0001.rvt are left out)"
        if dialog.ShowDialog() != DialogResult.OK:
            return
        paths = [p for p in Directory.GetFiles(dialog.SelectedPath, "*.rvt") if not BACKUP.search(p)]
        if not paths:
            TaskDialog.Show(TOOL, "There are no Revit models in that folder.")
            return
        add_paths(sorted(paths, key=lambda p: p.lower()))

    def on_remove(sender, args):
        chosen = ticked()
        if not chosen:
            return
        save_settings()
        for entry in chosen:
            files.remove(entry)
        banner[0] = "Removed {0}".format(plural(len(chosen), "file"))
        outcome[0] = "refresh"
        window.Close()

    def on_clear(sender, args):
        if not files:
            return
        save_settings()
        del files[:]
        banner[0] = ""
        outcome[0] = "refresh"
        window.Close()

    def on_search(sender, args):
        needle = (search_box.Text or "").strip().lower()
        search_hint.Visibility = Visibility.Collapsed if needle else Visibility.Visible
        for entry in files:
            haystack = u" ".join([entry["name"], entry["folder"], STATE_TEXT[entry["state"]][0]]).lower()
            entry["border"].Visibility = Visibility.Visible if (not needle or needle in haystack) \
                else Visibility.Collapsed
        update()

    def on_link(sender, args):
        if not ticked():
            return
        save_settings()
        outcome[0] = "link"
        window.Close()

    def on_close(sender, args):
        outcome[0] = None
        window.Close()

    search_box.TextChanged += TextChangedEventHandler(on_search)
    window.FindName("AddBtn").Click += RoutedEventHandler(on_add)
    window.FindName("FolderBtn").Click += RoutedEventHandler(on_folder)
    window.FindName("RemoveBtn").Click += RoutedEventHandler(on_remove)
    window.FindName("ClearBtn").Click += RoutedEventHandler(on_clear)
    link_btn.Click += RoutedEventHandler(on_link)
    window.FindName("CloseBtn").Click += RoutedEventHandler(on_close)
    update()

    frame = DispatcherFrame()

    def on_closed(sender, args):
        frame.Continue = False

    window.Closed += EventHandler(on_closed)
    enable_combo_search(window)
    window.Show()
    Dispatcher.PushFrame(frame)
    return outcome[0]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    if doc.IsFamilyDocument:
        TaskDialog.Show(TOOL, "Revit models can only be linked into a project.")
        return
    worksets, active_index = collect_worksets()
    settings = {"placement": 0, "attachment": 0, "workset": max(active_index, 0), "pin": True, "relative": True}
    files = []
    banner = [""]
    while True:
        refresh_states(files)
        for entry in files:
            if entry["state"] != "ready" and entry["result"] is None:
                entry["ticked"] = False
        action = show_window(files, settings, worksets, banner)
        if action is None:
            return
        if action == "refresh":
            continue
        chosen = [f for f in files if f.get("ticked", True) and f["state"] == "ready"]
        for entry in files:
            entry["result"] = None
        workset = worksets[settings["workset"]] if worksets else None
        link_files(chosen, settings, workset)
        done = len([f for f in chosen if f["result"][0] == "ok"])
        banner[0] = "Last run: {0} of {1} linked".format(done, len(chosen))


main()
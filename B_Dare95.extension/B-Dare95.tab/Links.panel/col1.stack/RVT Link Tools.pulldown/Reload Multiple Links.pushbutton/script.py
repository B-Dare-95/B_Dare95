# -*- coding: utf-8 -*-
__doc__ = """__________________________________________________
Description:

Reloads several Revit links in one go. Every link in the project is listed, loaded or not, with its status, whether it is an Attachment or an Overlay, how many copies are placed and the path it loads from.

Check the links you want and click Reload checked: each one is loaded again from its saved path, loaded or not, so it picks up the latest saved changes in that file. For a link whose file has moved, check it alone and use Reload From to point it at the new file. Each link shows what happened after the reload.
__________________________________________________
How-to:

-> Click on the button
-> Check the links to reload, or click a row to check it
-> Use Check visible or Check not loaded to check several at once
-> Click Reload checked
-> To repoint a link whose file has moved, check only that link and click Reload From
-> Each link shows its result; reload more or click Close
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

from Autodesk.Revit.DB import (
    BuiltInParameter,
    FilteredElementCollector,
    ModelPathUtils,
    RevitLinkInstance,
    RevitLinkType,
    WorksetConfiguration,
)
from Autodesk.Revit.UI import TaskDialog

from Microsoft.Win32 import OpenFileDialog
from System import DateTime, EventHandler
from System.IO import File, Path
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
from System.Windows.Input import Cursors, Mouse, MouseButtonEventHandler
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Markup import XamlReader
from System.Windows.Media import BrushConverter
from System.Windows.Threading import Dispatcher, DispatcherFrame

doc = __revit__.ActiveUIDocument.Document  # noqa: F821
TOOL = "Reload Links"

C_TEXT = "#F4F4F4"
C_SUBTEXT = "#A8A8A8"
C_MUTED = "#8D8D8D"
C_ACCENT = "#F1C21B"
C_OK = "#42BE65"
C_WARN = "#F1C21B"
C_BAD = "#FF8389"
DOT = u"  \u00b7  "

W_STATUS = 170
W_TYPE = 96
W_COUNT = 84

STATUS_TEXT = {
    "Loaded": "Loaded",
    "Unloaded": "Unloaded (all users)",
    "LocallyUnloaded": "Unloaded (this user)",
    "NotFound": "Not Found",
    "InClosedWorkset": "In Closed Workset",
    "Invalid": "Invalid",
}
STATUS_COLOR = {
    "Loaded": C_OK,
    "Unloaded (all users)": C_BAD,
    "Unloaded (this user)": C_WARN,
    "Not Found": C_BAD,
    "In Closed Workset": C_WARN,
    "Invalid": C_BAD,
}

_BC = BrushConverter()
_BRUSHES = {}


def brush(hex_string):
    if hex_string not in _BRUSHES:
        _BRUSHES[hex_string] = _BC.ConvertFromString(hex_string)
    return _BRUSHES[hex_string]


def id_value(id_obj):
    """ElementId integer value, valid on Revit 2024 through 2027."""
    try:
        return id_obj.Value
    except AttributeError:
        return id_obj.IntegerValue


def plural(n, word, word_pl=None):
    return "{0} {1}".format(n, word if n == 1 else (word_pl or word + "s"))


def element_name(el):
    try:
        name = el.Name
    except Exception:
        name = ""
    if not name:
        try:
            name = el.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM).AsString() or ""
        except Exception:
            name = ""
    return name or "<unnamed>"


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
def link_status(link_type):
    try:
        status = link_type.GetLinkedFileStatus()
    except Exception:
        try:
            status = link_type.GetExternalFileReference().GetLinkedFileStatus()
        except Exception:
            return "Unknown"
    return STATUS_TEXT.get(str(status), str(status))


def link_path(link_type):
    try:
        reference = link_type.GetExternalFileReference()
        return ModelPathUtils.ConvertModelPathToUserVisiblePath(reference.GetAbsolutePath()) or ""
    except Exception:
        return ""


def collect_links():
    counts = {}
    for inst in FilteredElementCollector(doc).OfClass(RevitLinkInstance):
        key = id_value(inst.GetTypeId())
        counts[key] = counts.get(key, 0) + 1

    links = []
    for link_type in FilteredElementCollector(doc).OfClass(RevitLinkType):
        try:
            if link_type.IsNestedLink:
                continue
        except Exception:
            pass
        key = id_value(link_type.Id)
        path = link_path(link_type)
        try:
            attachment = str(link_type.AttachmentType)
        except Exception:
            attachment = "?"
        try:
            exists = bool(path) and File.Exists(path)
        except Exception:
            exists = False
        links.append({
            "type": link_type,
            "key": key,
            "name": element_name(link_type),
            "status": link_status(link_type),
            "loaded": RevitLinkType.IsLoaded(doc, link_type.Id),
            "path": path,
            "exists": exists,
            "attachment": attachment,
            "count": counts.get(key, 0),
            "box": None,
            "border": None,
        })
    links.sort(key=lambda l: l["name"].lower())
    return links


# ---------------------------------------------------------------------------
# Reload
# ---------------------------------------------------------------------------
FAILURE_TEXT = {
    "LinkNotFound": "the file wasn't found at the saved path",
    "LinkNotLoaded": "the file couldn't be loaded",
}


def readable(kind):
    """LinkNotFound -> link not found"""
    return re.sub(r"(?<!^)([A-Z])", r" \1", kind).lower()


def describe(result, link_type):
    """('ok' / 'bad', text) for the LinkLoadResult of a reload.
    Revit reports a good reload as LinkLoaded; the link being loaded afterwards confirms it."""
    try:
        kind = str(result.LoadResult)
    except Exception:
        kind = str(result)
    try:
        loaded = RevitLinkType.IsLoaded(doc, link_type.Id)
    except Exception:
        loaded = False
    if kind == "LinkLoaded" or (loaded and "Not" not in kind):
        return "ok", u"Reloaded with the latest saved version at {0}".format(DateTime.Now.ToString("HH:mm"))
    return "bad", u"Not reloaded: {0}".format(FAILURE_TEXT.get(kind, readable(kind)))


def reload_links(links, results):
    """Reload each link from its saved path, loaded or not, so it picks up the latest saved version of
    the file. Reload runs outside any transaction, one link at a time."""
    Mouse.OverrideCursor = Cursors.Wait
    try:
        for link in links:
            try:
                results[link["key"]] = describe(link["type"].Reload(), link["type"])
            except Exception as ex:
                results[link["key"]] = ("bad", u"Failed: {0}".format(ex))
    finally:
        Mouse.OverrideCursor = None


def reload_from(link, new_path, results):
    """Point a link at another file and load it. All the link's worksets are opened."""
    Mouse.OverrideCursor = Cursors.Wait
    try:
        model_path = ModelPathUtils.ConvertUserVisiblePathToModelPath(new_path)
        kind, text = describe(link["type"].LoadFrom(model_path, WorksetConfiguration()), link["type"])
        if kind == "ok":
            text = u"Reloaded from {0}".format(Path.GetFileName(new_path))
        results[link["key"]] = (kind, text)
    except Exception as ex:
        results[link["key"]] = ("bad", u"Reload From failed: {0}".format(ex))
    finally:
        Mouse.OverrideCursor = None


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Reload Links" Width="1080" Height="720" MinWidth="820" MinHeight="460"
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
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <StackPanel Grid.Row="0" Margin="0,0,0,12">
      <TextBlock Text="RELOAD LINKS" Foreground="#F1C21B" FontSize="16" FontWeight="Bold"/>
      <TextBlock x:Name="SubTitle" Foreground="#A8A8A8" FontSize="12" Margin="0,3,0,0"/>
    </StackPanel>

    <Border Grid.Row="1" Background="#262626" CornerRadius="6" Padding="10" Margin="0,0,0,10">
      <DockPanel>
        <Button x:Name="ClearBtn" DockPanel.Dock="Right" Content="Clear" Style="{StaticResource GhostBtn}"
                Height="26" Padding="14,0" Margin="8,0,0,0"/>
        <Button x:Name="TickUnloadedBtn" DockPanel.Dock="Right" Content="Check not loaded"
                Style="{StaticResource GhostBtn}" Height="26" Padding="14,0" Margin="8,0,0,0"/>
        <Button x:Name="TickVisibleBtn" DockPanel.Dock="Right" Content="Check visible"
                Style="{StaticResource GhostBtn}" Height="26" Padding="14,0" Margin="16,0,0,0"/>
        <Grid>
          <Border Background="#393939" BorderBrush="#525252" BorderThickness="1" CornerRadius="4" Height="26">
            <TextBox x:Name="SearchBox" Background="Transparent" BorderThickness="0"
                     Foreground="#F4F4F4" CaretBrush="#F1C21B" FontSize="12"
                     VerticalContentAlignment="Center" Padding="8,0"/>
          </Border>
          <TextBlock x:Name="SearchHint" Text="Search links, status or path..." Foreground="#6F6F6F"
                     FontSize="12" Margin="10,0,0,0" VerticalAlignment="Center" IsHitTestVisible="False"/>
        </Grid>
      </DockPanel>
    </Border>

    <DockPanel x:Name="HeaderRow" Grid.Row="2" Margin="12,0,30,6"/>

    <ScrollViewer Grid.Row="3" VerticalScrollBarVisibility="Auto" HorizontalScrollBarVisibility="Disabled">
      <StackPanel x:Name="RowsPanel"/>
    </ScrollViewer>

    <Grid Grid.Row="4" Margin="0,12,0,0">
      <TextBlock x:Name="CountText" Foreground="#A8A8A8" FontSize="12" VerticalAlignment="Center"
                 HorizontalAlignment="Left" TextWrapping="Wrap" Margin="0,0,420,0"/>
      <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
        <Button x:Name="CloseBtn" Content="Close" Style="{StaticResource GhostBtn}"/>
        <Button x:Name="FromBtn" Content="Reload From..." Style="{StaticResource GhostBtn}" Margin="10,0,0,0"
                ToolTip="Check one link, then pick the file it should load from"/>
        <Button x:Name="ReloadBtn" Content="Reload checked" Style="{StaticResource FlatBtn}" Margin="10,0,0,0"/>
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
    for text, width in (("PLACED", W_COUNT), ("TYPE", W_TYPE), ("STATUS", W_STATUS)):
        block = TextBlock()
        block.Text = text
        block.Style = style
        cell = fixed(block, width)
        DockPanel.SetDock(cell, Dock.Right)
        header.Children.Add(cell)
    name = TextBlock()
    name.Text = "LINK"
    name.Style = style
    name.Margin = Thickness(28, 0, 0, 0)
    header.Children.Add(name)


def build_row(link, result, ticked, on_change):
    border = Border()
    border.Background = brush("#262626")
    border.CornerRadius = CornerRadius(6)
    border.Padding = Thickness(12, 8, 12, 8)
    border.Margin = Thickness(0, 0, 0, 6)
    border.Cursor = Cursors.Hand

    dock = DockPanel()
    status = text_block(link["status"], 12, STATUS_COLOR.get(link["status"], C_SUBTEXT))
    for cell in (fixed(text_block(plural(link["count"], "copy", "copies") if link["count"] else "not placed",
                                  12, C_SUBTEXT if link["count"] else C_MUTED), W_COUNT),
                 fixed(text_block(link["attachment"], 12, C_SUBTEXT), W_TYPE),
                 fixed(status, W_STATUS)):
        DockPanel.SetDock(cell, Dock.Right)
        dock.Children.Add(cell)

    box = CheckBox()
    box.IsChecked = link["key"] in ticked
    box.Margin = Thickness(0, 0, 12, 0)
    box.VerticalAlignment = VerticalAlignment.Center
    DockPanel.SetDock(box, Dock.Left)
    dock.Children.Add(box)
    link["box"] = box

    info = StackPanel()
    info.VerticalAlignment = VerticalAlignment.Center
    info.Children.Add(text_block(link["name"], 13, C_TEXT, bold=True))
    if link["path"]:
        path_text = link["path"] if link["exists"] else link["path"] + DOT + "file not found at this path"
        path_line = text_block(path_text, 11, C_SUBTEXT if link["exists"] else C_BAD)
        path_line.ToolTip = link["path"]
        info.Children.Add(path_line)
    else:
        info.Children.Add(text_block("No saved path", 11, C_MUTED))
    if result is not None:
        kind, text = result
        info.Children.Add(text_block(text, 11, C_OK if kind == "ok" else C_BAD, bold=True))
    dock.Children.Add(info)
    border.Child = dock

    def on_box(sender, args):
        on_change()

    def on_row(sender, args):
        source = args.OriginalSource
        if source is box or isinstance(source, CheckBox):
            return
        box.IsChecked = not bool(box.IsChecked)
        on_change()

    box.Click += RoutedEventHandler(on_box)
    border.MouseLeftButtonUp += MouseButtonEventHandler(on_row)
    link["border"] = border
    return border


def show_window(links, results, ticked, banner):
    """Returns ('reload', [links]), ('from', link, path) or None."""
    window = XamlReader.Parse(XAML)
    try:
        WindowInteropHelper(window).Owner = __revit__.MainWindowHandle  # noqa: F821
    except Exception:
        pass
    rows_panel = window.FindName("RowsPanel")
    search_box = window.FindName("SearchBox")
    search_hint = window.FindName("SearchHint")
    count_text = window.FindName("CountText")
    reload_btn = window.FindName("ReloadBtn")
    from_btn = window.FindName("FromBtn")

    loaded = len([l for l in links if l["loaded"]])
    window.FindName("SubTitle").Text = u"{0}{1}{2}{1}{3} loaded, {4} not loaded".format(
        doc.Title, DOT, plural(len(links), "Revit link"), loaded, len(links) - loaded)
    make_header(window)

    def picked():
        return [l for l in links if l["box"].IsChecked]

    def update():
        chosen = picked()
        for link in links:
            if link["box"].IsChecked:
                ticked.add(link["key"])
            else:
                ticked.discard(link["key"])
        visible = len([l for l in links if l["border"].Visibility == Visibility.Visible])
        text = "Showing {0} of {1}{2}{3} checked".format(visible, len(links), DOT, len(chosen))
        if banner[0]:
            text = banner[0] + DOT + text
        count_text.Text = text
        reload_btn.Content = "Reload checked ({0})".format(len(chosen)) if chosen else "Reload checked"
        reload_btn.IsEnabled = bool(chosen)
        from_btn.IsEnabled = len(chosen) == 1

    for link in links:
        rows_panel.Children.Add(build_row(link, results.get(link["key"]), ticked, update))

    outcome = [None]

    def visible_links():
        return [l for l in links if l["border"].Visibility == Visibility.Visible]

    def on_search(sender, args):
        needle = (search_box.Text or "").strip().lower()
        search_hint.Visibility = Visibility.Collapsed if needle else Visibility.Visible
        for link in links:
            haystack = u" ".join([link["name"], link["status"], link["path"], link["attachment"]]).lower()
            link["border"].Visibility = Visibility.Visible if (not needle or needle in haystack) \
                else Visibility.Collapsed
        update()

    def on_tick_visible(sender, args):
        for link in visible_links():
            link["box"].IsChecked = True
        update()

    def on_tick_unloaded(sender, args):
        for link in links:
            if not link["loaded"]:
                link["box"].IsChecked = True
        update()

    def on_clear(sender, args):
        for link in links:
            link["box"].IsChecked = False
        update()

    def on_reload(sender, args):
        chosen = picked()
        if not chosen:
            return
        outcome[0] = ("reload", chosen)
        window.Close()

    def on_from(sender, args):
        chosen = picked()
        if len(chosen) != 1:
            TaskDialog.Show(TOOL, "Check exactly one link to use Reload From.")
            return
        link = chosen[0]
        dialog = OpenFileDialog()
        dialog.Title = u"Reload {0} from".format(link["name"])
        dialog.Filter = "Revit models (*.rvt)|*.rvt"
        dialog.Multiselect = False
        try:
            folder = Path.GetDirectoryName(link["path"]) if link["path"] else ""
            if folder:
                dialog.InitialDirectory = folder
        except Exception:
            pass
        if not dialog.ShowDialog(window):
            return
        outcome[0] = ("from", link, dialog.FileName)
        window.Close()

    def on_close(sender, args):
        outcome[0] = None
        window.Close()

    search_box.TextChanged += TextChangedEventHandler(on_search)
    window.FindName("TickVisibleBtn").Click += RoutedEventHandler(on_tick_visible)
    window.FindName("TickUnloadedBtn").Click += RoutedEventHandler(on_tick_unloaded)
    window.FindName("ClearBtn").Click += RoutedEventHandler(on_clear)
    reload_btn.Click += RoutedEventHandler(on_reload)
    from_btn.Click += RoutedEventHandler(on_from)
    window.FindName("CloseBtn").Click += RoutedEventHandler(on_close)
    update()

    frame = DispatcherFrame()

    def on_closed(sender, args):
        frame.Continue = False

    window.Closed += EventHandler(on_closed)
    window.Show()
    Dispatcher.PushFrame(frame)
    return outcome[0]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    if not collect_links():
        TaskDialog.Show(TOOL, "There are no Revit links in this project.")
        return

    results = {}
    ticked = set()
    banner = [""]
    while True:
        links = collect_links()
        action = show_window(links, results, ticked, banner)
        if action is None:
            return
        if action[0] == "reload":
            chosen = action[1]
            results.clear()
            reload_links(chosen, results)
            done = len([k for k in results if results[k][0] == "ok"])
            banner[0] = "Last run: {0} of {1} reloaded".format(done, len(chosen))
            for key in list(ticked):
                if results.get(key, ("bad",))[0] == "ok":
                    ticked.discard(key)  # uncheck what worked, keep the failures checked to retry
        else:
            link, new_path = action[1], action[2]
            results.clear()
            reload_from(link, new_path, results)
            ok = results[link["key"]][0] == "ok"
            banner[0] = "Last run: Reload From " + ("worked" if ok else "failed")
            if ok:
                ticked.discard(link["key"])


main()
# -*- coding: utf-8 -*-
"""Link Workset Assigner

Lists every RVT and DWG link/import in the project with its loading status and
current workset, and lets the user assign a workset to each one from a dropdown.

Assigns the workset to the link TYPE element (this is what controls whether the
link loads when a workset is closed) and, optionally, to all of its instances.

IronPython 2.7 / Revit 2024-2027
"""

__title__ = "Link\nWorksets"
__author__ = "Mohamed Bedair"

import clr

clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")
clr.AddReference("System.Xml")

from Autodesk.Revit.DB import (
    BuiltInParameter,
    CADLinkType,
    ElementId,
    ExternalFileUtils,
    FilteredElementCollector,
    FilteredWorksetCollector,
    ImportInstance,
    RevitLinkInstance,
    RevitLinkType,
    Transaction,
    WorksetKind,
    WorksharingUtils,
)
from Autodesk.Revit.UI import TaskDialog

from System import EventHandler
from System.Collections.Generic import List
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
    ComboBox,
    Orientation,
    StackPanel,
    TextBlock,
    TextChangedEventHandler,
)
from System.Windows.Markup import XamlReader
from System.Windows.Media import BrushConverter
from System.Windows.Threading import Dispatcher, DispatcherFrame

doc = __revit__.ActiveUIDocument.Document

# ---------------------------------------------------------------------------
# Palette (Catppuccin Mocha)
# ---------------------------------------------------------------------------
C_TEXT = "#F4F4F4"
C_SUBTEXT = "#A8A8A8"
C_ACCENT = "#F1C21B"
C_OK = "#42BE65"
C_WARN = "#F1C21B"
C_BAD = "#FF8389"

_BC = BrushConverter()
_BRUSH_CACHE = {}


def brush(hex_string):
    if hex_string not in _BRUSH_CACHE:
        _BRUSH_CACHE[hex_string] = _BC.ConvertFromString(hex_string)
    return _BRUSH_CACHE[hex_string]


# Column widths, shared between the header row and the data rows
W_NAME = 300
W_KIND = 70
W_STATUS = 160
W_WORKSET = 170
W_COMBO = 210

KEEP_CURRENT = "-- Keep current --"

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
    "Imported (not linked)": C_SUBTEXT,
    "Unknown": C_SUBTEXT,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def id_value(id_obj):
    """ElementId/WorksetId integer value, valid on Revit 2024 through 2027."""
    try:
        return id_obj.Value
    except AttributeError:
        return id_obj.IntegerValue


def element_name(el):
    try:
        name = el.Name
    except Exception:
        name = ""
    if not name:
        try:
            param = el.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
            if param:
                name = param.AsString() or ""
        except Exception:
            pass
    return name or "<unnamed>"


def is_external_reference(el):
    try:
        return ExternalFileUtils.IsExternalFileReference(doc, el.Id)
    except Exception:
        return False


def link_status(el, is_cad):
    """Readable loading status for a link type element."""
    if is_cad and not is_external_reference(el):
        return "Imported (not linked)"

    status = None
    try:
        status = el.GetLinkedFileStatus()
    except AttributeError:
        try:
            status = el.GetExternalFileReference().GetLinkedFileStatus()
        except Exception:
            status = None
    except Exception:
        status = None

    if status is None:
        return "Unknown"
    return STATUS_TEXT.get(str(status), str(status))


def other_user_owner(el):
    """Returns the owning username if somebody else has the element checked out."""
    try:
        info = WorksharingUtils.GetWorksharingTooltipInfo(doc, el.Id)
        owner = info.Owner or ""
    except Exception:
        return ""
    if not owner:
        return ""
    try:
        me = doc.Application.Username
    except Exception:
        me = ""
    if owner.lower() == (me or "").lower():
        return ""
    return owner


def workset_param(el):
    try:
        return el.get_Parameter(BuiltInParameter.ELEM_PARTITION_PARAM)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------
def collect_worksets():
    worksets = list(FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset))
    worksets.sort(key=lambda w: w.Name.lower())
    return worksets


def instances_by_type(instance_class):
    mapping = {}
    for inst in FilteredElementCollector(doc).OfClass(instance_class).ToElements():
        try:
            key = id_value(inst.GetTypeId())
        except Exception:
            continue
        mapping.setdefault(key, []).append(inst)
    return mapping


def collect_rows(workset_names):
    rows = []

    rvt_instances = instances_by_type(RevitLinkInstance)
    for link_type in FilteredElementCollector(doc).OfClass(RevitLinkType).ToElements():
        try:
            if link_type.IsNestedLink:
                continue
        except AttributeError:
            pass
        rows.append(build_row(link_type, "RVT", False,
                              rvt_instances.get(id_value(link_type.Id), []),
                              workset_names))

    cad_instances = instances_by_type(ImportInstance)
    for cad_type in FilteredElementCollector(doc).OfClass(CADLinkType).ToElements():
        kind = "DWG" if is_external_reference(cad_type) else "IMPORT"
        rows.append(build_row(cad_type, kind, True,
                              cad_instances.get(id_value(cad_type.Id), []),
                              workset_names))

    rows.sort(key=lambda r: (r["kind"], r["name"].lower()))
    return rows


def build_row(type_elem, kind, is_cad, instances, workset_names):
    current_id = id_value(type_elem.WorksetId)
    param = workset_param(type_elem)
    owner = other_user_owner(type_elem)

    locked_reason = ""
    if param is None:
        locked_reason = "no workset parameter"
    elif param.IsReadOnly:
        locked_reason = "workset is read-only"
    elif owner:
        locked_reason = "owned by " + owner

    return {
        "type_elem": type_elem,
        "kind": kind,
        "is_cad": is_cad,
        "name": element_name(type_elem),
        "status": link_status(type_elem, is_cad),
        "instances": instances,
        "current_id": current_id,
        "current_name": workset_names.get(current_id, "<not on a workset>"),
        "locked_reason": locked_reason,
        "combo": None,
        "border": None,
    }


# ---------------------------------------------------------------------------
# XAML shell
# ---------------------------------------------------------------------------
XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Link Workset Assigner"
        Width="1020" Height="720"
        WindowStartupLocation="CenterScreen"
        Background="#161616"
        FontFamily="Segoe UI">
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
      <TextBlock Text="LINK WORKSET ASSIGNER" Foreground="#F1C21B"
                 FontSize="16" FontWeight="Bold"/>
      <TextBlock Text="Pick a workset for each RVT / DWG link, then click Assign."
                 Foreground="#A8A8A8" FontSize="12" Margin="0,3,0,0"/>
    </StackPanel>

    <Border Grid.Row="1" Background="#262626" CornerRadius="6" Padding="10" Margin="0,0,0,10">
      <StackPanel Orientation="Horizontal">
        <TextBlock Text="Search" Foreground="#A8A8A8" FontSize="12"
                   VerticalAlignment="Center" Margin="0,0,8,0"/>
        <Border Background="#393939" BorderBrush="#525252" BorderThickness="1"
                CornerRadius="4" Width="300" Height="26">
          <TextBox x:Name="SearchBox" Background="Transparent" BorderThickness="0"
                   Foreground="#F4F4F4" CaretBrush="#F1C21B" FontSize="12"
                   VerticalContentAlignment="Center" Padding="8,0"/>
        </Border>
        <TextBlock Text="Set all visible to" Foreground="#A8A8A8" FontSize="12"
                   VerticalAlignment="Center" Margin="24,0,8,0"/>
        <ComboBox x:Name="BulkCombo" Style="{StaticResource DarkCombo}" Width="200"/>
        <Button x:Name="BulkBtn" Content="Apply" Style="{StaticResource GhostBtn}"
                Height="26" Padding="14,0" Margin="8,0,0,0"/>
      </StackPanel>
    </Border>

    <StackPanel x:Name="HeaderRow" Grid.Row="2" Orientation="Horizontal"
                Margin="10,0,26,6"/>

    <ScrollViewer Grid.Row="3" VerticalScrollBarVisibility="Auto"
                  HorizontalScrollBarVisibility="Disabled">
      <StackPanel x:Name="RowsPanel"/>
    </ScrollViewer>

    <Grid Grid.Row="4" Margin="0,12,0,0">
      <StackPanel Orientation="Horizontal" HorizontalAlignment="Left">
        <CheckBox x:Name="InstancesCheck" IsChecked="True" Foreground="#A8A8A8"
                  FontSize="12" VerticalAlignment="Center"
                  Content="Also assign the link instances"/>
        <TextBlock x:Name="CountText" Foreground="#A8A8A8" FontSize="12"
                   VerticalAlignment="Center" Margin="20,0,0,0"/>
      </StackPanel>
      <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
        <Button x:Name="CancelBtn" Content="Cancel" Style="{StaticResource GhostBtn}"/>
        <Button x:Name="OkBtn" Content="Assign Worksets" Style="{StaticResource FlatBtn}"
                Margin="10,0,0,0"/>
      </StackPanel>
    </Grid>

  </Grid>
</Window>
"""


# ---------------------------------------------------------------------------
# UI construction
# ---------------------------------------------------------------------------
def make_cell(text, width, color, tooltip=None, bold=False):
    block = TextBlock()
    block.Text = text
    block.Width = width
    block.FontSize = 12
    block.Foreground = brush(color)
    block.VerticalAlignment = VerticalAlignment.Center
    block.TextTrimming = TextTrimming.CharacterEllipsis
    block.Margin = Thickness(0, 0, 8, 0)
    if bold:
        block.FontWeight = FontWeights.SemiBold
    if tooltip:
        block.ToolTip = tooltip
    return block


def make_header(window):
    header = window.FindName("HeaderRow")
    style = window.Resources["HeaderCell"]
    for text, width in (("LINK NAME", W_NAME),
                        ("TYPE", W_KIND),
                        ("STATUS", W_STATUS),
                        ("CURRENT WORKSET", W_WORKSET),
                        ("ASSIGN TO", W_COMBO)):
        block = TextBlock()
        block.Text = text
        block.Width = width
        block.Style = style
        header.Children.Add(block)


def make_row(window, row, workset_list):
    border = Border()
    border.Background = brush("#262626")
    border.CornerRadius = CornerRadius(5)
    border.Padding = Thickness(10, 6, 10, 6)
    border.Margin = Thickness(0, 0, 0, 4)

    panel = StackPanel()
    panel.Orientation = Orientation.Horizontal

    panel.Children.Add(make_cell(row["name"], W_NAME, C_TEXT, row["name"], True))
    panel.Children.Add(make_cell(row["kind"], W_KIND, C_SUBTEXT))
    panel.Children.Add(make_cell(row["status"], W_STATUS,
                                 STATUS_COLOR.get(row["status"], C_SUBTEXT)))

    current_text = row["current_name"]
    if row["locked_reason"]:
        current_text = current_text + "  (" + row["locked_reason"] + ")"
    panel.Children.Add(make_cell(current_text, W_WORKSET, C_SUBTEXT, current_text))

    combo = ComboBox()
    combo.Style = window.Resources["DarkCombo"]
    combo.Width = W_COMBO
    combo.Items.Add(KEEP_CURRENT)
    for workset in workset_list:
        combo.Items.Add(workset.Name)
    combo.SelectedIndex = 0
    if row["locked_reason"]:
        combo.IsEnabled = False
        combo.ToolTip = "Cannot be reassigned: " + row["locked_reason"]
    panel.Children.Add(combo)

    border.Child = panel
    row["combo"] = combo
    row["border"] = border
    return border


# ---------------------------------------------------------------------------
# Workset assignment
# ---------------------------------------------------------------------------
def assign_worksets(pending, include_instances):
    """pending is a list of (row, workset) tuples."""
    targets = []
    for row, workset in pending:
        elements = [row["type_elem"]]
        if include_instances:
            elements = elements + list(row["instances"])
        targets.append((row, workset, elements))

    # Checkout must happen outside of a transaction
    ids = List[ElementId]()
    for _row, _workset, elements in targets:
        for element in elements:
            ids.Add(element.Id)
    try:
        WorksharingUtils.CheckoutElements(doc, ids)
    except Exception:
        pass

    changed = 0
    skipped = 0
    failures = []

    transaction = Transaction(doc, "Assign Links to Worksets")
    transaction.Start()
    try:
        for row, workset, elements in targets:
            target_id = id_value(workset.Id)
            for element in elements:
                param = workset_param(element)
                if param is None or param.IsReadOnly:
                    skipped += 1
                    continue
                if id_value(element.WorksetId) == target_id:
                    skipped += 1
                    continue
                try:
                    param.Set(target_id)
                    changed += 1
                except Exception as err:
                    failures.append("{0} -> {1}: {2}".format(
                        row["name"], workset.Name, err))
        transaction.Commit()
    except Exception as err:
        transaction.RollBack()
        raise err

    return changed, skipped, failures


def report(changed, skipped, failures):
    lines = ["Elements moved: {0}".format(changed),
             "Already correct or read-only: {0}".format(skipped)]
    if failures:
        lines.append("")
        lines.append("Failed ({0}):".format(len(failures)))
        lines.extend(failures[:15])
        if len(failures) > 15:
            lines.append("... and {0} more".format(len(failures) - 15))
    dialog = TaskDialog("Link Workset Assigner")
    dialog.MainInstruction = "Done"
    dialog.MainContent = "\n".join(lines)
    dialog.Show()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    if not doc.IsWorkshared:
        TaskDialog.Show("Link Workset Assigner",
                        "This project is not workshared, so it has no worksets.")
        return

    workset_list = collect_worksets()
    if not workset_list:
        TaskDialog.Show("Link Workset Assigner",
                        "No user worksets were found in this project.")
        return

    workset_names = {}
    for workset in workset_list:
        workset_names[id_value(workset.Id)] = workset.Name

    rows = collect_rows(workset_names)
    if not rows:
        TaskDialog.Show("Link Workset Assigner",
                        "No RVT or DWG links were found in this project.")
        return

    window = XamlReader.Parse(XAML)
    rows_panel = window.FindName("RowsPanel")
    search_box = window.FindName("SearchBox")
    bulk_combo = window.FindName("BulkCombo")
    bulk_btn = window.FindName("BulkBtn")
    instances_check = window.FindName("InstancesCheck")
    count_text = window.FindName("CountText")
    ok_btn = window.FindName("OkBtn")
    cancel_btn = window.FindName("CancelBtn")

    make_header(window)
    for row in rows:
        rows_panel.Children.Add(make_row(window, row, workset_list))

    for workset in workset_list:
        bulk_combo.Items.Add(workset.Name)
    if bulk_combo.Items.Count:
        bulk_combo.SelectedIndex = 0

    result = [False]
    pending = [[]]
    include_instances = [True]

    def update_count(visible):
        count_text.Text = "Showing {0} of {1} links".format(visible, len(rows))

    update_count(len(rows))

    def on_search(sender, args):
        needle = (search_box.Text or "").strip().lower()
        visible = 0
        for row in rows:
            haystack = " ".join([row["name"], row["kind"], row["status"],
                                 row["current_name"]]).lower()
            match = (not needle) or (needle in haystack)
            row["border"].Visibility = Visibility.Visible if match else Visibility.Collapsed
            if match:
                visible += 1
        update_count(visible)

    def on_bulk(sender, args):
        index = bulk_combo.SelectedIndex
        if index < 0:
            return
        for row in rows:
            if row["border"].Visibility != Visibility.Visible:
                continue
            if not row["combo"].IsEnabled:
                continue
            row["combo"].SelectedIndex = index + 1

    def on_ok(sender, args):
        selections = []
        for row in rows:
            index = row["combo"].SelectedIndex
            if index <= 0 or not row["combo"].IsEnabled:
                continue
            selections.append((row, workset_list[index - 1]))
        if not selections:
            TaskDialog.Show("Link Workset Assigner",
                            "No worksets were assigned. Pick at least one link.")
            return
        pending[0] = selections
        include_instances[0] = bool(instances_check.IsChecked)
        result[0] = True
        window.Close()

    def on_cancel(sender, args):
        result[0] = False
        window.Close()

    search_box.TextChanged += TextChangedEventHandler(on_search)
    bulk_btn.Click += RoutedEventHandler(on_bulk)
    ok_btn.Click += RoutedEventHandler(on_ok)
    cancel_btn.Click += RoutedEventHandler(on_cancel)

    frame = DispatcherFrame()

    def on_closed(sender, args):
        frame.Continue = False

    window.Closed += EventHandler(on_closed)
    window.Show()
    Dispatcher.PushFrame(frame)

    if not result[0]:
        return

    changed, skipped, failures = assign_worksets(pending[0], include_instances[0])
    report(changed, skipped, failures)

main()
# -*- coding: utf-8 -*-
"""Model Group Manager.

WPF tool that lists every Model Group type in the active document with its
creator, instance count and contents, and adds two clean-up actions:

    * Ungroup every model group that has exactly one placed instance.
    * Delete every model group that contains no elements (empty definitions and
      unplaced group types).

IronPython 2.7 / Revit 2024-2027.
"""

__title__ = "Model Group\nManager"
__author__ = "Mohamed Bedair"

import traceback
from collections import defaultdict

import clr

clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")
clr.AddReference("System.Xml")

from System import EventHandler
from System.Windows import Clipboard, RoutedEventHandler, Visibility
from System.Windows.Controls import SelectionChangedEventHandler, TextChangedEventHandler
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Markup import XamlReader
from System.Windows.Threading import Dispatcher, DispatcherFrame

from Autodesk.Revit.DB import (
    BuiltInCategory,
    BuiltInParameter,
    Element,
    ElementId,
    FilteredElementCollector,
    Group,
    GroupType,
    Transaction,
    WorksharingUtils,
)
from Autodesk.Revit.UI import TaskDialog, TaskDialogCommonButtons, TaskDialogResult

from pyrevit import revit

doc = revit.doc


# ---------------------------------------------------------------------------
# Revit helpers
# ---------------------------------------------------------------------------
def eid_value(element_id):
    """ElementId -> int, compatible with Revit 2024 (.IntegerValue) and 2025+ (.Value)."""
    try:
        return element_id.Value
    except AttributeError:
        return element_id.IntegerValue


def safe_name(element):
    if element is None:
        return "<None>"
    try:
        return element.Name
    except Exception:
        pass
    try:
        return Element.Name.GetValue(element)
    except Exception:
        return "<Unnamed>"


def worksharing_info(document, element_id):
    """(creator, last_changed_by, owner) - degrades gracefully on non-workshared docs."""
    if not document.IsWorkshared:
        return ("N/A - not workshared", "N/A", "N/A")
    try:
        info = WorksharingUtils.GetWorksharingTooltipInfo(document, element_id)
        return (info.Creator or "<unknown>",
                info.LastChangedBy or "<unknown>",
                info.Owner or "<none>")
    except Exception:
        return ("<unavailable>", "<unavailable>", "<unavailable>")


def category_name(element):
    try:
        if element.Category is not None:
            return element.Category.Name
    except Exception:
        pass
    return "<No Category>"


def type_label(document, element):
    type_element = document.GetElement(element.GetTypeId())
    if type_element is None:
        return safe_name(element)
    type_name = safe_name(type_element)
    family_name = ""
    try:
        family_name = type_element.FamilyName or ""
    except Exception:
        family_name = ""
    if family_name and family_name != type_name:
        return "{0}: {1}".format(family_name, type_name)
    return type_name


def group_level_name(document, group_instance):
    try:
        param = group_instance.get_Parameter(BuiltInParameter.GROUP_LEVEL)
        if param is not None:
            level = document.GetElement(param.AsElementId())
            if level is not None:
                return safe_name(level)
    except Exception:
        pass
    return "<n/a>"


def is_nested(element):
    """True when this group instance sits inside another group."""
    try:
        owner = element.GroupId
        return owner is not None and owner != ElementId.InvalidElementId
    except Exception:
        return False


# ---------------------------------------------------------------------------
# View model rows (bound directly by WPF - plain attributes, lowercase names)
# ---------------------------------------------------------------------------
class MemberRow(object):
    def __init__(self, category, label, count):
        self.category = category
        self.label = label
        self.count = count


class GroupRow(object):
    def __init__(self, group_type, instances, document):
        self.type_id = group_type.Id
        self.type_id_value = eid_value(group_type.Id)
        self.name = safe_name(group_type)

        creator, changed_by, owner = worksharing_info(document, group_type.Id)
        self.creator = creator
        self.changed_by = changed_by
        self.owner = owner

        self.instance_ids = [g.Id for g in instances]
        self.instances = len(instances)
        self.pinned_count = len([g for g in instances if g.Pinned])
        self.nested_count = len([g for g in instances if is_nested(g)])

        self.members = []
        self.elements = 0
        self.unique_types = 0
        if instances:
            try:
                member_ids = list(instances[0].GetMemberIds())
            except Exception:
                member_ids = []
            counts = defaultdict(int)
            for member_id in member_ids:
                element = document.GetElement(member_id)
                if element is None:
                    continue
                self.elements += 1
                counts[(category_name(element), type_label(document, element))] += 1
            self.members = [MemberRow(cat, label, num)
                            for (cat, label), num in sorted(counts.items())]
            self.unique_types = len(self.members)

        self.levels = ", ".join(sorted(set(group_level_name(document, g)
                                           for g in instances))) or "-"

        # Action eligibility
        self.is_unplaced = self.instances == 0
        self.is_empty = self.instances > 0 and self.elements == 0
        self.deletable = self.is_unplaced or self.is_empty
        self.ungroupable = (self.instances == 1
                            and not self.deletable
                            and self.nested_count == 0)

        if self.is_empty:
            self.status = "Empty (0 elements)"
        elif self.is_unplaced:
            self.status = "Unplaced"
        elif self.instances == 1 and self.nested_count:
            self.status = "Single instance (nested)"
        elif self.instances == 1:
            self.status = "Single instance"
        else:
            self.status = "OK"

    @property
    def instances_text(self):
        return str(self.instances)

    @property
    def elements_text(self):
        return "-" if self.is_unplaced else str(self.elements)

    @property
    def unique_types_text(self):
        return "-" if self.is_unplaced else str(self.unique_types)

    def matches(self, needle):
        if not needle:
            return True
        needle = needle.lower()
        return (needle in self.name.lower()
                or needle in self.creator.lower()
                or needle in self.changed_by.lower()
                or needle in self.status.lower())


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------
def collect_group_rows(document):
    group_types = [gt for gt in FilteredElementCollector(document)
                   .OfCategory(BuiltInCategory.OST_IOSModelGroups)
                   .WhereElementIsElementType()
                   .ToElements()
                   if isinstance(gt, GroupType)]

    instances_by_type = defaultdict(list)
    for grp in (FilteredElementCollector(document)
                .OfCategory(BuiltInCategory.OST_IOSModelGroups)
                .WhereElementIsNotElementType()
                .ToElements()):
        if isinstance(grp, Group):
            instances_by_type[eid_value(grp.GetTypeId())].append(grp)

    rows = [GroupRow(gt, instances_by_type.get(eid_value(gt.Id), []), document)
            for gt in group_types]
    rows.sort(key=lambda r: r.name.lower())
    return rows


def build_text_report(document, rows):
    lines = ["MODEL GROUP REPORT - {0}".format(document.Title), "=" * 72]
    for row in rows:
        lines.append("")
        lines.append("GROUP: {0}   [{1}]".format(row.name, row.status))
        lines.append("  Created by      : {0}".format(row.creator))
        lines.append("  Last changed by : {0}".format(row.changed_by))
        lines.append("  Instances       : {0}".format(row.instances))
        lines.append("  Levels          : {0}".format(row.levels))
        if row.is_unplaced:
            lines.append("  Contents        : <unplaced - not available>")
            continue
        lines.append("  Contents        : {0} elements / {1} unique types".format(
            row.elements, row.unique_types))
        for member in row.members:
            lines.append("      {0:>4} x  [{1}] {2}".format(
                member.count, member.category, member.label))
    lines.append("")
    lines.append("=" * 72)
    lines.append("Totals: {0} group types, {1} placed instances".format(
        len(rows), sum(r.instances for r in rows)))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# XAML
# ---------------------------------------------------------------------------
XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Model Group Manager" Height="740" Width="1180"
        WindowStartupLocation="CenterScreen"
        ShowInTaskbar="True"
        Background="#161616">
  <Window.Resources>
    <Style x:Key="FlatButton" TargetType="Button">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="BorderBrush" Value="#525252"/>
      <Setter Property="Padding" Value="14,8"/>
      <Setter Property="Margin" Value="0,0,8,0"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="Bd" CornerRadius="6"
                    Background="{TemplateBinding Background}"
                    BorderBrush="{TemplateBinding BorderBrush}"
                    BorderThickness="1"
                    Padding="{TemplateBinding Padding}">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#525252"/>
                <Setter TargetName="Bd" Property="BorderBrush" Value="#F1C21B"/>
              </Trigger>
              <Trigger Property="IsEnabled" Value="False">
                <Setter TargetName="Bd" Property="Background" Value="#262626"/>
                <Setter Property="Foreground" Value="#8D8D8D"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="AccentButton" TargetType="Button" BasedOn="{StaticResource FlatButton}">
      <Setter Property="Foreground" Value="#161616"/>
      <Setter Property="Background" Value="#F1C21B"/>
      <Setter Property="BorderBrush" Value="#F1C21B"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
    </Style>

    <Style x:Key="ToggleChip" TargetType="ToggleButton">
      <Setter Property="Foreground" Value="#A8A8A8"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Margin" Value="0,0,12,0"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ToggleButton">
            <Border x:Name="Chip" CornerRadius="6" BorderThickness="1"
                    Background="#393939" BorderBrush="#525252" Padding="12,7">
              <ContentPresenter VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsChecked" Value="True">
                <Setter TargetName="Chip" Property="Background" Value="#F1C21B"/>
                <Setter TargetName="Chip" Property="BorderBrush" Value="#F1C21B"/>
                <Setter Property="Foreground" Value="#161616"/>
              </Trigger>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="Chip" Property="BorderBrush" Value="#F1C21B"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="HeaderStyle" TargetType="GridViewColumnHeader">
      <Setter Property="Background" Value="#262626"/>
      <Setter Property="Foreground" Value="#A8A8A8"/>
      <Setter Property="BorderBrush" Value="#525252"/>
      <Setter Property="BorderThickness" Value="0,0,1,1"/>
      <Setter Property="Padding" Value="8,6"/>
      <Setter Property="HorizontalContentAlignment" Value="Left"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
    </Style>

    <Style x:Key="RowStyle" TargetType="ListViewItem">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Background" Value="Transparent"/>
      <Setter Property="BorderThickness" Value="0"/>
      <Setter Property="Padding" Value="4,5"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ListViewItem">
            <Border x:Name="RowBd" Background="{TemplateBinding Background}"
                    BorderBrush="#262626" BorderThickness="0,0,0,1"
                    Padding="{TemplateBinding Padding}">
              <GridViewRowPresenter Content="{TemplateBinding Content}"
                                    Columns="{TemplateBinding GridView.ColumnCollection}"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="RowBd" Property="Background" Value="#262626"/>
              </Trigger>
              <Trigger Property="IsSelected" Value="True">
                <Setter TargetName="RowBd" Property="Background" Value="#525252"/>
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
      <TextBlock Text="Model Group Manager" Foreground="#F4F4F4"
                 FontSize="20" FontWeight="Bold"/>
      <TextBlock x:Name="SubHeader" Foreground="#A8A8A8" FontSize="12" Margin="0,4,0,0"/>
    </StackPanel>

    <Border Grid.Row="1" Background="#262626" CornerRadius="6" Padding="10,6"
            BorderBrush="#525252" BorderThickness="1" Margin="0,0,0,12">
      <Grid>
        <TextBlock x:Name="SearchHint" Text="Search group name, creator or status..."
                   Foreground="#8D8D8D" FontSize="12" VerticalAlignment="Center"
                   IsHitTestVisible="False"/>
        <TextBox x:Name="SearchBox" Background="Transparent" BorderThickness="0"
                 Foreground="#F4F4F4" CaretBrush="#F1C21B" FontSize="12"
                 VerticalAlignment="Center"/>
      </Grid>
    </Border>

    <Grid Grid.Row="2">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="2.05*"/>
        <ColumnDefinition Width="12"/>
        <ColumnDefinition Width="1*"/>
      </Grid.ColumnDefinitions>

      <Border Grid.Column="0" Background="#262626" CornerRadius="8"
              BorderBrush="#525252" BorderThickness="1" Padding="1">
        <ListView x:Name="GroupList" Background="Transparent" BorderThickness="0"
                  Foreground="#F4F4F4"
                  ItemContainerStyle="{StaticResource RowStyle}"
                  ScrollViewer.HorizontalScrollBarVisibility="Auto">
          <ListView.View>
            <GridView ColumnHeaderContainerStyle="{StaticResource HeaderStyle}">
              <GridViewColumn Header="Group Name" Width="260"
                              DisplayMemberBinding="{Binding name}"/>
              <GridViewColumn Header="Created By" Width="130"
                              DisplayMemberBinding="{Binding creator}"/>
              <GridViewColumn Header="Last Changed By" Width="130"
                              DisplayMemberBinding="{Binding changed_by}"/>
              <GridViewColumn Header="Inst." Width="52"
                              DisplayMemberBinding="{Binding instances_text}"/>
              <GridViewColumn Header="Elements" Width="70"
                              DisplayMemberBinding="{Binding elements_text}"/>
              <GridViewColumn Header="Types" Width="60"
                              DisplayMemberBinding="{Binding unique_types_text}"/>
              <GridViewColumn Header="Status" Width="150"
                              DisplayMemberBinding="{Binding status}"/>
            </GridView>
          </ListView.View>
        </ListView>
      </Border>

      <Border Grid.Column="2" Background="#262626" CornerRadius="8"
              BorderBrush="#525252" BorderThickness="1" Padding="10">
        <Grid>
          <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
          </Grid.RowDefinitions>
          <StackPanel Grid.Row="0" Margin="0,0,0,8">
            <TextBlock Text="CONTENTS" Foreground="#F1C21B" FontSize="11" FontWeight="Bold"/>
            <TextBlock x:Name="ContentsHeader" Text="Select a group"
                       Foreground="#A8A8A8" FontSize="11" TextWrapping="Wrap" Margin="0,4,0,0"/>
          </StackPanel>
          <ListView x:Name="MemberList" Grid.Row="1" Background="Transparent"
                    BorderThickness="0" Foreground="#F4F4F4"
                    ItemContainerStyle="{StaticResource RowStyle}">
            <ListView.View>
              <GridView ColumnHeaderContainerStyle="{StaticResource HeaderStyle}">
                <GridViewColumn Header="Qty" Width="42"
                                DisplayMemberBinding="{Binding count}"/>
                <GridViewColumn Header="Category" Width="110"
                                DisplayMemberBinding="{Binding category}"/>
                <GridViewColumn Header="Family: Type" Width="180"
                                DisplayMemberBinding="{Binding label}"/>
              </GridView>
            </ListView.View>
          </ListView>
        </Grid>
      </Border>
    </Grid>

    <Grid Grid.Row="3" Margin="0,14,0,0">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="Auto"/>
      </Grid.ColumnDefinitions>

      <StackPanel Grid.Column="0" Orientation="Horizontal" VerticalAlignment="Center">
        <Button x:Name="UngroupButton" Style="{StaticResource AccentButton}"
                Content="Ungroup single-instance groups"/>
        <Button x:Name="DeleteButton" Style="{StaticResource AccentButton}"
                Content="Delete empty groups"/>
        <ToggleButton x:Name="PurgeToggle" Style="{StaticResource ToggleChip}"
                      IsChecked="True" Content="Purge leftover type after ungroup"/>
      </StackPanel>

      <StackPanel Grid.Column="1" Orientation="Horizontal" VerticalAlignment="Center">
        <Button x:Name="CopyButton" Style="{StaticResource FlatButton}" Content="Copy report"/>
        <Button x:Name="RefreshButton" Style="{StaticResource FlatButton}" Content="Refresh"/>
        <Button x:Name="CloseButton" Style="{StaticResource FlatButton}" Content="Close"
                Margin="0"/>
      </StackPanel>
    </Grid>
  </Grid>
</Window>
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    window = XamlReader.Parse(XAML)

    sub_header = window.FindName("SubHeader")
    search_box = window.FindName("SearchBox")
    search_hint = window.FindName("SearchHint")
    group_list = window.FindName("GroupList")
    member_list = window.FindName("MemberList")
    contents_header = window.FindName("ContentsHeader")
    ungroup_button = window.FindName("UngroupButton")
    delete_button = window.FindName("DeleteButton")
    purge_toggle = window.FindName("PurgeToggle")
    copy_button = window.FindName("CopyButton")
    refresh_button = window.FindName("RefreshButton")
    close_button = window.FindName("CloseButton")

    missing = [n for n, c in [("SubHeader", sub_header), ("SearchBox", search_box),
                              ("SearchHint", search_hint), ("GroupList", group_list),
                              ("MemberList", member_list),
                              ("ContentsHeader", contents_header),
                              ("UngroupButton", ungroup_button),
                              ("DeleteButton", delete_button),
                              ("PurgeToggle", purge_toggle),
                              ("CopyButton", copy_button),
                              ("RefreshButton", refresh_button),
                              ("CloseButton", close_button)] if c is None]
    if missing:
        TaskDialog.Show("Model Group Manager",
                        "The UI failed to load. Missing controls:\n{0}".format(
                            ", ".join(missing)))
        return

    # IronPython 2.7 has no nonlocal - state lives in mutable containers.
    all_rows = []
    frame_holder = [None]

    def eligible_ungroup():
        return [r for r in all_rows if r.ungroupable]

    def eligible_delete():
        return [r for r in all_rows if r.deletable]

    def refresh_buttons():
        ungroup_count = len(eligible_ungroup())
        delete_count = len(eligible_delete())
        ungroup_button.Content = "Ungroup single-instance groups ({0})".format(ungroup_count)
        delete_button.Content = "Delete empty groups ({0})".format(delete_count)
        ungroup_button.IsEnabled = ungroup_count > 0
        delete_button.IsEnabled = delete_count > 0

    def refresh_header():
        sub_header.Text = ("{0}  |  {1} model group types  |  {2} placed instances  |  "
                           "workshared: {3}".format(
                               doc.Title,
                               len(all_rows),
                               sum(r.instances for r in all_rows),
                               "yes" if doc.IsWorkshared else "no"))

    def apply_filter():
        needle = search_box.Text or ""
        search_hint.Visibility = Visibility.Collapsed if needle else Visibility.Visible
        group_list.ItemsSource = [r for r in all_rows if r.matches(needle)]

    def reload_data():
        all_rows[:] = collect_group_rows(doc)
        apply_filter()
        refresh_header()
        refresh_buttons()
        member_list.ItemsSource = []
        contents_header.Text = "Select a group"

    def on_search_changed(sender, args):
        apply_filter()

    def on_selection_changed(sender, args):
        row = group_list.SelectedItem
        if row is None:
            member_list.ItemsSource = []
            contents_header.Text = "Select a group"
            return
        member_list.ItemsSource = row.members
        if row.is_unplaced:
            contents_header.Text = ("{0}\nUnplaced - Revit exposes members only through a "
                                    "placed instance.".format(row.name))
        else:
            contents_header.Text = ("{0}\n{1} elements / {2} unique types  |  "
                                    "Levels: {3}".format(row.name, row.elements,
                                                         row.unique_types, row.levels))

    def confirm(title, main_text, names):
        preview = "\n".join("  - " + n for n in names[:15])
        if len(names) > 15:
            preview += "\n  - ... and {0} more".format(len(names) - 15)
        dialog = TaskDialog(title)
        dialog.MainInstruction = main_text
        dialog.MainContent = preview
        dialog.CommonButtons = TaskDialogCommonButtons.Yes | TaskDialogCommonButtons.No
        dialog.DefaultButton = TaskDialogResult.No
        return dialog.Show() == TaskDialogResult.Yes

    def on_ungroup(sender, args):
        targets = eligible_ungroup()
        if not targets:
            return
        if not confirm("Ungroup single-instance groups",
                       "Ungroup {0} model group(s) with exactly one instance?".format(
                           len(targets)),
                       [r.name for r in targets]):
            return

        purge_types = bool(purge_toggle.IsChecked)
        done = []
        unpinned = []
        failed = []

        t = Transaction(doc, "Ungroup single-instance model groups")
        t.Start()
        try:
            for row in targets:
                try:
                    instance = doc.GetElement(row.instance_ids[0])
                    if instance is None or not instance.IsValidObject:
                        failed.append((row.name, "instance no longer valid"))
                        continue
                    if instance.Pinned:
                        instance.Pinned = False
                        unpinned.append(row.name)
                    instance.UngroupMembers()
                    if purge_types:
                        group_type = doc.GetElement(row.type_id)
                        if group_type is not None and group_type.IsValidObject:
                            doc.Delete(group_type.Id)
                    done.append(row.name)
                except Exception as e:
                    failed.append((row.name, str(e)))
            t.Commit()
        except Exception as e:
            t.RollBack()
            TaskDialog.Show("Ungroup failed", "Transaction rolled back:\n{0}".format(e))
            return

        reload_data()
        report = ["Ungrouped: {0}".format(len(done))]
        if unpinned:
            report.append("Unpinned first: {0}".format(len(unpinned)))
        if purge_types:
            report.append("Leftover group types deleted: {0}".format(len(done)))
        if failed:
            report.append("")
            report.append("Skipped ({0}):".format(len(failed)))
            for name, reason in failed[:15]:
                report.append("  - {0}: {1}".format(name, reason))
        TaskDialog.Show("Ungroup complete", "\n".join(report))

    def on_delete(sender, args):
        targets = eligible_delete()
        if not targets:
            return
        if not confirm("Delete empty groups",
                       "Delete {0} model group type(s) that contain no elements?".format(
                           len(targets)),
                       ["{0}  [{1}]".format(r.name, r.status) for r in targets]):
            return

        done = []
        failed = []

        t = Transaction(doc, "Delete empty model groups")
        t.Start()
        try:
            for row in targets:
                try:
                    group_type = doc.GetElement(row.type_id)
                    if group_type is None or not group_type.IsValidObject:
                        continue
                    doc.Delete(group_type.Id)
                    done.append(row.name)
                except Exception as e:
                    failed.append((row.name, str(e)))
            t.Commit()
        except Exception as e:
            t.RollBack()
            TaskDialog.Show("Delete failed", "Transaction rolled back:\n{0}".format(e))
            return

        reload_data()
        report = ["Deleted group types: {0}".format(len(done))]
        if failed:
            report.append("")
            report.append("Skipped ({0}):".format(len(failed)))
            for name, reason in failed[:15]:
                report.append("  - {0}: {1}".format(name, reason))
        TaskDialog.Show("Delete complete", "\n".join(report))

    def on_copy(sender, args):
        Clipboard.SetText(build_text_report(doc, all_rows))
        TaskDialog.Show("Model Group Manager",
                        "Full report copied to the clipboard ({0} group types).".format(
                            len(all_rows)))

    def on_refresh(sender, args):
        reload_data()

    def on_close(sender, args):
        window.Close()

    def on_window_closed(sender, args):
        if frame_holder[0] is not None:
            frame_holder[0].Continue = False

    search_box.TextChanged += TextChangedEventHandler(on_search_changed)
    group_list.SelectionChanged += SelectionChangedEventHandler(on_selection_changed)
    ungroup_button.Click += RoutedEventHandler(on_ungroup)
    delete_button.Click += RoutedEventHandler(on_delete)
    copy_button.Click += RoutedEventHandler(on_copy)
    refresh_button.Click += RoutedEventHandler(on_refresh)
    close_button.Click += RoutedEventHandler(on_close)
    window.Closed += EventHandler(on_window_closed)

    reload_data()

    # Parent the window to Revit so it can never open behind the main window.
    try:
        WindowInteropHelper(window).Owner = __revit__.MainWindowHandle
    except Exception:
        pass

    window.Show()
    window.Activate()
    frame_holder[0] = DispatcherFrame()
    Dispatcher.PushFrame(frame_holder[0])


try:
    main()
except Exception:
    TaskDialog.Show("Model Group Manager - unexpected error",
                    traceback.format_exc())
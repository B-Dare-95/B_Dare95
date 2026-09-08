# -*- coding: utf-8 -*-
"""Duplicate Views
Select a view, choose how many duplicates and which duplicate mode
(Duplicate View / Duplicate with Detailing / Duplicate as Dependent),
optionally assign a Scope Box + naming pattern to each dependent view,
then create them and show a brief report.

Author: Mohamed Bedair (B-Dare95)
"""
__title__ = 'Duplicate\nViews'
__author__ = 'Mohamed Bedair (B-Dare95)'
__doc__ = 'Batch-duplicate a view as Duplicate / With Detailing / As Dependent, ' \
          'with per-dependent Scope Box assignment and Prefix-Serial-Suffix naming.'

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('PresentationCore')
clr.AddReference('PresentationFramework')
clr.AddReference('WindowsBase')

from Autodesk.Revit.DB import (
    FilteredElementCollector, View, ViewSheet, ViewSchedule, ViewType,
    ViewDuplicateOption, BuiltInCategory, BuiltInParameter, Transaction
)
from Autodesk.Revit.UI import TaskDialog

from System.Windows.Markup import XamlReader
from System.Windows.Threading import Dispatcher, DispatcherFrame

doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

# ---------------------------------------------------------------------------
# Catppuccin Mocha palette
# ---------------------------------------------------------------------------
BG = "#1E1E2E"
CARD = "#2A2A3C"
SURFACE = "#313244"
MUTED = "#45475A"
TEXT = "#CDD6F4"
SUBTEXT = "#A6ADC8"
ACCENT = "#F0A500"
DANGER = "#F38BA8"


def theme(xaml_text):
    xaml_text = xaml_text.replace("@BG@", BG).replace("@CARD@", CARD)
    xaml_text = xaml_text.replace("@SURFACE@", SURFACE).replace("@MUTED@", MUTED)
    xaml_text = xaml_text.replace("@TEXT@", TEXT).replace("@SUBTEXT@", SUBTEXT)
    xaml_text = xaml_text.replace("@ACCENT@", ACCENT).replace("@DANGER@", DANGER)
    return xaml_text


ROUNDED_BUTTON_STYLE = u"""
<Window.Resources>
    <Style x:Key="RoundedButton" TargetType="Button">
        <Setter Property="Foreground" Value="@BG@"/>
        <Setter Property="FontWeight" Value="Bold"/>
        <Setter Property="Cursor" Value="Hand"/>
        <Setter Property="Template">
            <Setter.Value>
                <ControlTemplate TargetType="Button">
                    <Border Background="{TemplateBinding Background}" CornerRadius="6" BorderThickness="0">
                        <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center" Margin="8,0,8,0"/>
                    </Border>
                </ControlTemplate>
            </Setter.Value>
        </Setter>
    </Style>
    <Style x:Key="RoundedButtonMuted" TargetType="Button" BasedOn="{StaticResource RoundedButton}">
        <Setter Property="Foreground" Value="@TEXT@"/>
        <Setter Property="Background" Value="@MUTED@"/>
    </Style>
</Window.Resources>
"""


def show_dialog(window):
    """Modeless-but-blocking show, per established Dispatcher.PushFrame convention."""
    frame = DispatcherFrame()

    def on_closed(sender, args):
        frame.Continue = False

    window.Closed += on_closed
    window.Show()
    Dispatcher.PushFrame(frame)


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------
def get_all_views():
    collector = FilteredElementCollector(doc).OfClass(View)
    views = []
    for v in collector:
        if v.IsTemplate:
            continue
        if isinstance(v, ViewSheet) or isinstance(v, ViewSchedule):
            continue
        if v.ViewType in (ViewType.Internal, ViewType.ProjectBrowser, ViewType.SystemBrowser, ViewType.Undefined):
            continue
        views.append(v)
    views.sort(key=lambda x: x.Name)
    return views


# Ordered (label, ViewType) pairs used to populate the type-filter dropdown.
# "All Views" (None) always comes first; the rest are only shown if at least
# one view of that type exists in the project.
VIEW_TYPE_CATEGORIES = [
    (u"All Views", None),
    (u"Floor Plans", ViewType.FloorPlan),
    (u"Reflected Ceiling Plans", ViewType.CeilingPlan),
    (u"Area Plans", ViewType.AreaPlan),
    (u"Structural Plans", ViewType.EngineeringPlan),
    (u"Elevations", ViewType.Elevation),
    (u"Sections", ViewType.Section),
    (u"3D Views", ViewType.ThreeD),
    (u"Detail Views", ViewType.Detail),
    (u"Drafting Views", ViewType.DraftingView),
    (u"Legends", ViewType.Legend),
    (u"Renderings", ViewType.Rendering),
    (u"Walkthroughs", ViewType.Walkthrough),
]


def get_scope_boxes():
    collector = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_VolumeOfInterest)
    collector = collector.WhereElementIsNotElementType()
    boxes = list(collector)
    boxes.sort(key=lambda x: x.Name)
    return boxes


# ---------------------------------------------------------------------------
# Window 1 - view picker, count, duplicate mode
# ---------------------------------------------------------------------------
WINDOW1_XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Duplicate Views" Height="580" Width="420"
        WindowStartupLocation="CenterScreen"
        Background="@BG@" ResizeMode="NoResize">
    __ROUNDED_BUTTON_STYLE__
    <Grid Margin="16">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <TextBlock Grid.Row="0" Text="Select a View to Duplicate" Foreground="@TEXT@"
                   FontSize="16" FontWeight="Bold" Margin="0,0,0,10"/>

        <Grid Grid.Row="1" Margin="0,0,0,8">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="150"/>
            </Grid.ColumnDefinitions>
            <TextBox Grid.Column="0" Name="SearchBox" Height="28" Padding="6,4" Margin="0,0,6,0"
                     Background="@SURFACE@" Foreground="@TEXT@" BorderBrush="@MUTED@"/>
            <ComboBox Grid.Column="1" Name="TypeFilterBox" Height="28"
                      Background="@SURFACE@" Foreground="@BG@"/>
        </Grid>

        <ListBox Grid.Row="2" Name="ViewListBox" Background="@CARD@" Foreground="@TEXT@"
                 BorderBrush="@MUTED@" Margin="0,0,0,10"/>

        <StackPanel Grid.Row="3" Orientation="Horizontal" Margin="0,0,0,10">
            <TextBlock Text="Number of Duplicates:" Foreground="@TEXT@" VerticalAlignment="Center" Margin="0,0,8,0"/>
            <TextBox Name="CountBox" Width="60" Height="26" Text="1"
                     Background="@SURFACE@" Foreground="@TEXT@" BorderBrush="@MUTED@"/>
        </StackPanel>

        <StackPanel Grid.Row="4" Margin="0,0,0,10">
            <TextBlock Text="Duplicate Option:" Foreground="@TEXT@" Margin="0,0,0,6"/>
            <RadioButton Name="RbDuplicate" Content="Duplicate View" GroupName="opt"
                         Foreground="@TEXT@" IsChecked="True" Margin="0,0,0,4"/>
            <RadioButton Name="RbDetailing" Content="Duplicate with Detailing" GroupName="opt"
                         Foreground="@TEXT@" Margin="0,0,0,4"/>
            <RadioButton Name="RbDependent" Content="Duplicate as Dependent" GroupName="opt"
                         Foreground="@TEXT@"/>
        </StackPanel>

        <TextBlock Grid.Row="5" Name="ErrorText" Foreground="@DANGER@" Margin="0,0,0,8" TextWrapping="Wrap"/>

        <Button Grid.Row="6" Name="NextButton" Content="Continue" Height="34"
                Background="@ACCENT@" Style="{StaticResource RoundedButton}"/>
    </Grid>
</Window>
"""


def build_window1(views):
    xaml = WINDOW1_XAML.replace("__ROUNDED_BUTTON_STYLE__", ROUNDED_BUTTON_STYLE)
    window = XamlReader.Parse(theme(xaml))

    search_box = window.FindName("SearchBox")
    type_filter_box = window.FindName("TypeFilterBox")
    view_list = window.FindName("ViewListBox")
    count_box = window.FindName("CountBox")
    rb_duplicate = window.FindName("RbDuplicate")
    rb_detailing = window.FindName("RbDetailing")
    rb_dependent = window.FindName("RbDependent")
    error_text = window.FindName("ErrorText")
    next_button = window.FindName("NextButton")

    present_types = set(v.ViewType for v in views)
    category_map = {}
    for label, vtype in VIEW_TYPE_CATEGORIES:
        if vtype is None or vtype in present_types:
            category_map[label] = vtype
            type_filter_box.Items.Add(label)
    type_filter_box.SelectedIndex = 0

    def apply_filter(sender, args):
        term = search_box.Text.lower()
        selected_label = type_filter_box.SelectedItem
        selected_type = category_map.get(selected_label)
        view_list.Items.Clear()
        for v in views:
            if selected_type is not None and v.ViewType != selected_type:
                continue
            if term and term not in v.Name.lower():
                continue
            view_list.Items.Add(v.Name)

    search_box.TextChanged += apply_filter
    type_filter_box.SelectionChanged += apply_filter
    apply_filter(None, None)

    result = {"view": None, "count": 0, "option": None}

    def on_next(sender, args):
        error_text.Text = u""

        if view_list.SelectedItem is None:
            error_text.Text = u"Please select a view."
            return

        try:
            count = int(count_box.Text)
            if count < 1:
                raise ValueError()
        except ValueError:
            error_text.Text = u"Enter a valid whole number of duplicates."
            return

        selected_name = view_list.SelectedItem
        selected_view = None
        for v in views:
            if v.Name == selected_name:
                selected_view = v
                break

        if rb_dependent.IsChecked:
            option_key = "dependent"
        elif rb_detailing.IsChecked:
            option_key = "detailing"
        else:
            option_key = "duplicate"

        result["view"] = selected_view
        result["count"] = count
        result["option"] = option_key
        window.Close()

    next_button.Click += on_next
    show_dialog(window)
    return result


# ---------------------------------------------------------------------------
# Window 2 - per-dependent Scope Box assignment + Prefix/Suffix
# ---------------------------------------------------------------------------
WINDOW2_XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Dependent Views - Scope Boxes" Height="560" Width="480"
        WindowStartupLocation="CenterScreen"
        Background="@BG@" ResizeMode="NoResize">
    __ROUNDED_BUTTON_STYLE__
    <Grid Margin="16">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <TextBlock Grid.Row="0" Text="Assign a Scope Box to each Dependent View"
                   Foreground="@TEXT@" FontSize="16" FontWeight="Bold" Margin="0,0,0,10"/>

        <ScrollViewer Grid.Row="1" VerticalScrollBarVisibility="Auto" Margin="0,0,0,10">
            <StackPanel Name="RowsPanel">
                __ROWS__
            </StackPanel>
        </ScrollViewer>

        <Grid Grid.Row="2" Margin="0,0,0,10">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="*"/>
            </Grid.ColumnDefinitions>
            <StackPanel Grid.Column="0" Margin="0,0,6,0">
                <TextBlock Text="Prefix" Foreground="@SUBTEXT@" Margin="0,0,0,4"/>
                <TextBox Name="PrefixBox" Height="26" Background="@SURFACE@" Foreground="@TEXT@" BorderBrush="@MUTED@"/>
            </StackPanel>
            <StackPanel Grid.Column="1" Margin="6,0,0,0">
                <TextBlock Text="Suffix" Foreground="@SUBTEXT@" Margin="0,0,0,4"/>
                <TextBox Name="SuffixBox" Height="26" Background="@SURFACE@" Foreground="@TEXT@" BorderBrush="@MUTED@"/>
            </StackPanel>
        </Grid>

        <Button Grid.Row="3" Name="CreateButton" Content="Create Views" Height="34"
                Background="@ACCENT@" Style="{StaticResource RoundedButton}"/>
    </Grid>
</Window>
"""

ROW_XAML_TEMPLATE = u"""
<Grid Margin="0,0,0,8">
    <Grid.ColumnDefinitions>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="170"/>
    </Grid.ColumnDefinitions>
    <TextBlock Grid.Column="0" Text="__ROW_LABEL__" Foreground="@TEXT@"
               VerticalAlignment="Center" TextWrapping="Wrap"/>
    <ComboBox Grid.Column="1" Name="__COMBO_NAME__" Height="26"
              Background="@SURFACE@" Foreground="@BG@"/>
</Grid>
"""


def build_window2(parent_view, count, scope_boxes):
    rows_xaml_parts = []
    for i in range(count):
        row = ROW_XAML_TEMPLATE
        row = row.replace("__ROW_LABEL__", u"%s  \u2014  #%d" % (parent_view.Name, i + 1))
        row = row.replace("__COMBO_NAME__", u"cmb_%d" % i)
        rows_xaml_parts.append(row)
    rows_xaml = u"".join(rows_xaml_parts)

    xaml = WINDOW2_XAML.replace("__ROUNDED_BUTTON_STYLE__", ROUNDED_BUTTON_STYLE)
    xaml = xaml.replace("__ROWS__", rows_xaml)
    window = XamlReader.Parse(theme(xaml))

    scope_box_names = [b.Name for b in scope_boxes]
    combos = []
    for i in range(count):
        combo = window.FindName(u"cmb_%d" % i)
        combo.Items.Add(u"<None>")
        for name in scope_box_names:
            combo.Items.Add(name)
        combo.SelectedIndex = 0
        combos.append(combo)

    prefix_box = window.FindName("PrefixBox")
    suffix_box = window.FindName("SuffixBox")
    create_button = window.FindName("CreateButton")

    result = {"cancelled": True, "assignments": None, "prefix": u"", "suffix": u""}

    def on_create(sender, args):
        assignments = []
        for i in range(count):
            selected_name = combos[i].SelectedItem
            if selected_name == u"<None>" or selected_name is None:
                assignments.append(None)
            else:
                match = None
                for b in scope_boxes:
                    if b.Name == selected_name:
                        match = b.Id
                        break
                assignments.append(match)

        result["cancelled"] = False
        result["assignments"] = assignments
        result["prefix"] = prefix_box.Text.strip() if prefix_box.Text else u""
        result["suffix"] = suffix_box.Text.strip() if suffix_box.Text else u""
        window.Close()

    create_button.Click += on_create
    show_dialog(window)

    if result["cancelled"]:
        return None
    return result


# ---------------------------------------------------------------------------
# Naming helper
# ---------------------------------------------------------------------------
def build_dependent_name(parent_name, prefix, serial, suffix):
    parts = [parent_name]
    if prefix:
        parts.append(prefix)
    parts.append(str(serial))
    if suffix:
        parts.append(suffix)
    return u"-".join(parts)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    views = get_all_views()
    if not views:
        TaskDialog.Show(u"Duplicate Views", u"No eligible views were found in the project.")
        return

    selection = build_window1(views)
    if selection["view"] is None:
        return  # cancelled

    parent_view = selection["view"]
    count = selection["count"]
    option_key = selection["option"]

    option_map = {
        "duplicate": ViewDuplicateOption.Duplicate,
        "detailing": ViewDuplicateOption.WithDetailing,
        "dependent": ViewDuplicateOption.AsDependent,
    }
    dup_option = option_map[option_key]

    if not parent_view.CanViewBeDuplicated(dup_option):
        TaskDialog.Show(u"Duplicate Views", u"The selected view does not support this duplicate option.")
        return

    assignments = None
    prefix = u""
    suffix = u""

    if option_key == "dependent":
        scope_boxes = get_scope_boxes()
        dep_result = build_window2(parent_view, count, scope_boxes)
        if dep_result is None:
            return  # cancelled
        assignments = dep_result["assignments"]
        prefix = dep_result["prefix"]
        suffix = dep_result["suffix"]

    created = []
    failed = []
    existing_names = set(v.Name for v in FilteredElementCollector(doc).OfClass(View))

    t = Transaction(doc, u"Duplicate Views")
    t.Start()
    try:
        for i in range(count):
            serial = i + 1
            try:
                new_id = parent_view.Duplicate(dup_option)
                new_view = doc.GetElement(new_id)
            except Exception as ex:
                failed.append(u"#%d: %s" % (serial, str(ex)))
                continue

            if option_key == "dependent":
                base_name = build_dependent_name(parent_view.Name, prefix, serial, suffix)
            else:
                base_name = u"%s - Copy %d" % (parent_view.Name, serial)

            final_name = base_name
            counter = 2
            while final_name in existing_names:
                final_name = u"%s (%d)" % (base_name, counter)
                counter += 1

            try:
                new_view.Name = final_name
            except Exception:
                final_name = new_view.Name  # keep whatever Revit assigned

            existing_names.add(final_name)

            if option_key == "dependent" and assignments is not None:
                scope_id = assignments[i]
                if scope_id is not None:
                    param = new_view.get_Parameter(BuiltInParameter.VIEWER_VOLUME_OF_INTEREST_CROP)
                    if param is not None and not param.IsReadOnly:
                        try:
                            param.Set(scope_id)
                        except Exception:
                            pass

            created.append(final_name)

        t.Commit()
    except Exception as ex:
        t.RollBack()
        TaskDialog.Show(u"Duplicate Views", u"An unexpected error occurred:\n%s" % str(ex))
        return

    report_lines = [u"Created %d of %d view(s) from '%s'." % (len(created), count, parent_view.Name)]
    if failed:
        report_lines.append(u"")
        report_lines.append(u"Failed:")
        for f in failed:
            report_lines.append(u"- %s" % f)

    TaskDialog.Show(u"Duplicate Views - Report", u"\n".join(report_lines))


main()
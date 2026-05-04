# -*- coding: utf-8 -*-
__title__ = "Pre-Filter by Parameter"
__author__ = "Mohamed Bedair"
__doc__ = """

Description:
Filters the Selection box to only the selected category.
Optionally refines the selection further by matching a specific
parameter value for an even more targeted pick.
Also allows negating selection with SHIFT click.

How-to:
-> Run the script
-> Select a single category from the list
-> (Optional) Check "Filter by Parameter Value"
->   Pick a parameter from the left dropdown
->   Pick a value  from the right dropdown
-> Click "Make A Selection" and draw a rectangle

Author: Mohamed Bedair
"""

# ─── IMPORTS ──────────────────────────────────────────────────────────────────
import System
import clr
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from System.Collections.Generic import List
from Autodesk.Revit.DB import (
    FilteredElementCollector, ElementCategoryFilter,
    CategoryType, ElementId, StorageType
)
from Autodesk.Revit.UI.Selection import ISelectionFilter
from pyrevit import script
from pyrevit import EXEC_PARAMS

import System.Windows
import System.Windows.Controls as Controls
from System.Windows.Markup import XamlReader

# ─── REVIT HANDLES ────────────────────────────────────────────────────────────
doc       = __revit__.ActiveUIDocument.Document
uidoc     = __revit__.ActiveUIDocument
selection = uidoc.Selection

# ─── THEME ────────────────────────────────────────────────────────────────────
BG      = "#1E1E2E"
CARD    = "#2A2A3C"
SURFACE = "#313244"
MUTED   = "#45475A"
TEXT    = "#CDD6F4"
SUBTEXT = "#A6ADC8"
ACCENT  = "#F0A500"
# ──────────────────────────────────────────────────────────────────────────────

XAML_TEMPLATE = """
<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Choose Category"
    Width="370" MinHeight="120" MaxHeight="700"
    SizeToContent="Height"
    WindowStartupLocation="CenterScreen"
    ResizeMode="NoResize"
    Background="{BG}"
    Foreground="{TEXT}"
    FontFamily="Segoe UI"
    FontSize="13">

    <Window.Resources>

        <!-- ── Slim ScrollBar ── -->
        <Style x:Key="ScrollThumbStyle" TargetType="Thumb">
            <Setter Property="Background" Value="{MUTED}"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="Thumb">
                        <Border Background="{TemplateBinding Background}" CornerRadius="3"/>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
            <Style.Triggers>
                <Trigger Property="IsMouseOver" Value="True">
                    <Setter Property="Background" Value="{SUBTEXT}"/>
                </Trigger>
            </Style.Triggers>
        </Style>

        <Style TargetType="ScrollBar">
            <Setter Property="Background" Value="{CARD}"/>
            <Setter Property="Width" Value="6"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="ScrollBar">
                        <Grid Background="{CARD}">
                            <Track Name="PART_Track" IsDirectionReversed="True">
                                <Track.Thumb>
                                    <Thumb Style="{StaticResource ScrollThumbStyle}"/>
                                </Track.Thumb>
                            </Track>
                        </Grid>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>

        <!-- ── RadioButton (category row) ── -->
        <Style TargetType="RadioButton">
            <Setter Property="Foreground" Value="{TEXT}"/>
            <Setter Property="Margin"     Value="0,2,0,2"/>
            <Setter Property="Cursor"     Value="Hand"/>
            <Setter Property="VerticalContentAlignment" Value="Center"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="RadioButton">
                        <Grid>
                            <Grid.ColumnDefinitions>
                                <ColumnDefinition Width="18"/>
                                <ColumnDefinition Width="*"/>
                            </Grid.ColumnDefinitions>
                            <Border x:Name="Ring"
                                    Grid.Column="0"
                                    Width="14" Height="14"
                                    CornerRadius="7"
                                    Background="{SURFACE}"
                                    BorderBrush="{MUTED}"
                                    BorderThickness="1.5"
                                    VerticalAlignment="Center"/>
                            <Ellipse x:Name="Dot"
                                     Grid.Column="0"
                                     Width="6" Height="6"
                                     Fill="{BG}"
                                     HorizontalAlignment="Center"
                                     VerticalAlignment="Center"
                                     Visibility="Collapsed"/>
                            <ContentPresenter Grid.Column="1"
                                              Margin="8,0,0,0"
                                              VerticalAlignment="Center"/>
                        </Grid>
                        <ControlTemplate.Triggers>
                            <Trigger Property="IsChecked" Value="True">
                                <Setter TargetName="Ring" Property="Background"   Value="{ACCENT}"/>
                                <Setter TargetName="Ring" Property="BorderBrush"  Value="{ACCENT}"/>
                                <Setter TargetName="Dot"  Property="Visibility"   Value="Visible"/>
                            </Trigger>
                            <Trigger Property="IsMouseOver" Value="True">
                                <Setter TargetName="Ring" Property="BorderBrush" Value="{ACCENT}"/>
                            </Trigger>
                        </ControlTemplate.Triggers>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>

        <!-- ── CheckBox (param filter toggle) ── -->
        <Style TargetType="CheckBox">
            <Setter Property="Foreground" Value="{TEXT}"/>
            <Setter Property="Margin"     Value="0,2,0,2"/>
            <Setter Property="Cursor"     Value="Hand"/>
            <Setter Property="VerticalContentAlignment" Value="Center"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="CheckBox">
                        <Grid>
                            <Grid.ColumnDefinitions>
                                <ColumnDefinition Width="18"/>
                                <ColumnDefinition Width="*"/>
                            </Grid.ColumnDefinitions>
                            <Border x:Name="Box"
                                    Grid.Column="0"
                                    Width="14" Height="14"
                                    CornerRadius="3"
                                    Background="{SURFACE}"
                                    BorderBrush="{MUTED}"
                                    BorderThickness="1.5"
                                    VerticalAlignment="Center"/>
                            <TextBlock x:Name="Tick"
                                       Grid.Column="0"
                                       Text="&#x2714;"
                                       FontSize="10"
                                       Foreground="{BG}"
                                       HorizontalAlignment="Center"
                                       VerticalAlignment="Center"
                                       Visibility="Collapsed"/>
                            <ContentPresenter Grid.Column="1"
                                              Margin="8,0,0,0"
                                              VerticalAlignment="Center"/>
                        </Grid>
                        <ControlTemplate.Triggers>
                            <Trigger Property="IsChecked" Value="True">
                                <Setter TargetName="Box"  Property="Background"  Value="{ACCENT}"/>
                                <Setter TargetName="Box"  Property="BorderBrush" Value="{ACCENT}"/>
                                <Setter TargetName="Tick" Property="Visibility"  Value="Visible"/>
                            </Trigger>
                            <Trigger Property="IsMouseOver" Value="True">
                                <Setter TargetName="Box" Property="BorderBrush" Value="{ACCENT}"/>
                            </Trigger>
                            <Trigger Property="IsEnabled" Value="False">
                                <Setter Property="Opacity" Value="0.4"/>
                            </Trigger>
                        </ControlTemplate.Triggers>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>

        <!-- ── Accent (confirm) button ── -->
        <Style x:Key="AccentButton" TargetType="Button">
            <Setter Property="Background"   Value="{ACCENT}"/>
            <Setter Property="Foreground"   Value="{BG}"/>
            <Setter Property="FontWeight"   Value="SemiBold"/>
            <Setter Property="FontSize"     Value="13"/>
            <Setter Property="Height"       Value="36"/>
            <Setter Property="Cursor"       Value="Hand"/>
            <Setter Property="BorderThickness" Value="0"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="Button">
                        <Border x:Name="Bd"
                                Background="{TemplateBinding Background}"
                                CornerRadius="6">
                            <ContentPresenter HorizontalAlignment="Center"
                                              VerticalAlignment="Center"/>
                        </Border>
                        <ControlTemplate.Triggers>
                            <Trigger Property="IsMouseOver" Value="True">
                                <Setter TargetName="Bd" Property="Opacity" Value="0.85"/>
                            </Trigger>
                            <Trigger Property="IsPressed" Value="True">
                                <Setter TargetName="Bd" Property="Opacity" Value="0.7"/>
                            </Trigger>
                            <Trigger Property="IsEnabled" Value="False">
                                <Setter TargetName="Bd" Property="Opacity" Value="0.4"/>
                            </Trigger>
                        </ControlTemplate.Triggers>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>

    </Window.Resources>

    <Border Padding="16" Background="{BG}">
        <StackPanel>

            <!-- Header -->
            <TextBlock Text="Choose Category"
                       FontSize="15" FontWeight="SemiBold"
                       Foreground="{TEXT}"
                       Margin="0,0,0,10"/>

            <!-- Search box -->
            <Border Background="{SURFACE}" CornerRadius="6" Margin="0,0,0,10"
                    BorderBrush="{MUTED}" BorderThickness="1">
                <TextBox x:Name="SearchBox"
                         Background="Transparent"
                         BorderThickness="0"
                         Foreground="{TEXT}"
                         CaretBrush="{ACCENT}"
                         Padding="8,6"
                         FontSize="12"
                         ToolTip="Filter categories…"/>
            </Border>

            <!-- Category list (RadioButtons) -->
            <Border Background="{CARD}" CornerRadius="8"
                    Padding="10,8" Margin="0,0,0,14">
                <ScrollViewer MaxHeight="320"
                              VerticalScrollBarVisibility="Auto"
                              HorizontalScrollBarVisibility="Disabled"
                              Padding="0,0,4,0">
                    <StackPanel x:Name="CategoryPanel"/>
                </ScrollViewer>
            </Border>

            <!-- Divider -->
            <Border Height="1" Background="{MUTED}" Opacity="0.4" Margin="0,0,0,12"/>

            <!-- Parameter filter toggle -->
            <CheckBox x:Name="ParamFilterCheck"
                      Content="Filter by Parameter Value"
                      Margin="0,0,0,10"
                      IsEnabled="False"/>

            <!-- Parameter + Value dropdowns (hidden until checkbox is checked) -->
            <Border x:Name="ParamFilterPanel"
                    Visibility="Collapsed"
                    Margin="0,0,0,14">
                <StackPanel>

                    <!-- Column labels -->
                    <Grid Margin="0,0,0,5">
                        <Grid.ColumnDefinitions>
                            <ColumnDefinition Width="*"/>
                            <ColumnDefinition Width="10"/>
                            <ColumnDefinition Width="*"/>
                        </Grid.ColumnDefinitions>
                        <TextBlock Grid.Column="0" Text="Parameter"
                                   Foreground="{SUBTEXT}" FontSize="11" Margin="4,0,0,0"/>
                        <TextBlock Grid.Column="2" Text="Value"
                                   Foreground="{SUBTEXT}" FontSize="11" Margin="4,0,0,0"/>
                    </Grid>

                    <!-- Dropdown row -->
                    <Grid>
                        <Grid.ColumnDefinitions>
                            <ColumnDefinition Width="*"/>
                            <ColumnDefinition Width="10"/>
                            <ColumnDefinition Width="*"/>
                        </Grid.ColumnDefinitions>

                        <Border Grid.Column="0"
                                Background="{SURFACE}" CornerRadius="6"
                                BorderBrush="{MUTED}" BorderThickness="1">
                            <ComboBox x:Name="ParamCombo"
                                      Background="Transparent"
                                      Foreground="{TEXT}"
                                      BorderThickness="0"
                                      Height="30" FontSize="12" Padding="6,0"
                                      ToolTip="Select a parameter"/>
                        </Border>

                        <Border Grid.Column="2"
                                Background="{SURFACE}" CornerRadius="6"
                                BorderBrush="{MUTED}" BorderThickness="1">
                            <ComboBox x:Name="ValueCombo"
                                      Background="Transparent"
                                      Foreground="{TEXT}"
                                      BorderThickness="0"
                                      Height="30" FontSize="12" Padding="6,0"
                                      IsEnabled="False"
                                      ToolTip="Select a value"/>
                        </Border>

                    </Grid>
                </StackPanel>
            </Border>

            <!-- Confirm button -->
            <Button x:Name="ConfirmBtn"
                    Content="Make A Selection"
                    Style="{StaticResource AccentButton}"
                    IsEnabled="False"/>

        </StackPanel>
    </Border>
</Window>
""".replace("{BG}", BG).replace("{CARD}", CARD).replace("{SURFACE}", SURFACE) \
   .replace("{MUTED}", MUTED).replace("{TEXT}", TEXT).replace("{SUBTEXT}", SUBTEXT) \
   .replace("{ACCENT}", ACCENT)


# ─── HELPERS ──────────────────────────────────────────────────────────────────

def get_all_category_names(doc):
    """Return sorted list of all model category names in the document."""
    return sorted(
        cat.Name for cat in doc.Settings.Categories
        if cat.CategoryType == CategoryType.Model
    )


def get_category_by_name(doc, name):
    """Look up a Category object by display name."""
    for cat in doc.Settings.Categories:
        if cat.Name == name:
            return cat
    return None


def _eid_int(eid):
    """Return the integer value of an ElementId regardless of Revit version."""
    try:
        return eid.IntegerValue
    except AttributeError:
        return eid.Value  # Revit 2025+ Int64


def get_param_value_string(param):
    """
    Convert any parameter's current value to a human-readable string.
    Returns None when the parameter has no value.
    """
    try:
        if param is None or not param.HasValue:
            return None
        st = param.StorageType
        if st == StorageType.String:
            v = param.AsString()
            return v if v else None
        elif st == StorageType.Integer:
            vs = param.AsValueString()          # catches Yes/No, enum labels, etc.
            return vs if vs else str(param.AsInteger())
        elif st == StorageType.Double:
            vs = param.AsValueString()          # includes units
            return vs if vs else str(round(param.AsDouble(), 6))
        elif st == StorageType.ElementId:
            eid = param.AsElementId()
            if eid is None or _eid_int(eid) < 0:
                return None
            try:
                e = doc.GetElement(eid)
                if e is not None and hasattr(e, 'Name') and e.Name:
                    return e.Name
            except Exception:
                pass
            return str(_eid_int(eid))
        return None
    except Exception:
        return None


def get_params_for_category(category_name):
    """
    Return a sorted list of every parameter name that appears on elements
    (instance or type) belonging to *category_name*.
    Uses ElementCategoryFilter for efficient collection.
    """
    cat_obj = get_category_by_name(doc, category_name)
    if cat_obj is None:
        return []

    params        = set()
    seen_type_ints = set()

    try:
        col = (FilteredElementCollector(doc)
               .WherePasses(ElementCategoryFilter(cat_obj.Id))
               .WhereElementIsNotElementType())

        for elem in col:
            # Instance parameters
            for p in elem.Parameters:
                if p.Definition:
                    params.add(p.Definition.Name)

            # Type parameters (collect each unique type only once)
            try:
                tid = elem.GetTypeId()
                if tid and _eid_int(tid) > 0:
                    k = _eid_int(tid)
                    if k not in seen_type_ints:
                        seen_type_ints.add(k)
                        etype = doc.GetElement(tid)
                        if etype:
                            for p in etype.Parameters:
                                if p.Definition:
                                    params.add(p.Definition.Name)
            except Exception:
                pass
    except Exception:
        pass

    return sorted(params)


def get_values_for_param(category_name, param_name):
    """
    Return a sorted list of unique human-readable values that *param_name*
    holds across all elements (instance or type) of *category_name*.
    """
    cat_obj = get_category_by_name(doc, category_name)
    if cat_obj is None:
        return []

    values         = set()
    seen_type_ints = set()

    try:
        col = (FilteredElementCollector(doc)
               .WherePasses(ElementCategoryFilter(cat_obj.Id))
               .WhereElementIsNotElementType())

        for elem in col:
            # Instance
            p = elem.LookupParameter(param_name)
            if p:
                v = get_param_value_string(p)
                if v is not None:
                    values.add(v)

            # Type (deduplicated)
            try:
                tid = elem.GetTypeId()
                if tid and _eid_int(tid) > 0:
                    k = _eid_int(tid)
                    if k not in seen_type_ints:
                        seen_type_ints.add(k)
                        etype = doc.GetElement(tid)
                        if etype:
                            p = etype.LookupParameter(param_name)
                            if p:
                                v = get_param_value_string(p)
                                if v is not None:
                                    values.add(v)
            except Exception:
                pass
    except Exception:
        pass

    return sorted(values)


def element_matches_param_filter(elem, param_name, param_value):
    """
    Return True if *elem* (or its type) has *param_name* == *param_value*
    (both expressed as the string produced by get_param_value_string).
    """
    try:
        p = elem.LookupParameter(param_name)
        if p and get_param_value_string(p) == param_value:
            return True
    except Exception:
        pass
    try:
        tid = elem.GetTypeId()
        if tid and _eid_int(tid) > 0:
            etype = doc.GetElement(tid)
            if etype:
                p = etype.LookupParameter(param_name)
                if p and get_param_value_string(p) == param_value:
                    return True
    except Exception:
        pass
    return False


# ─── DIALOG ───────────────────────────────────────────────────────────────────

def show_category_picker(all_categories):
    """
    Display the themed category picker.

    Returns (category_name, param_filter) where:
        category_name  – str
        param_filter   – None  OR  (param_name_str, param_value_str)

    Returns None when the user closes without confirming.
    """
    window = XamlReader.Parse(XAML_TEMPLATE)

    search_box         = window.FindName("SearchBox")
    cat_panel          = window.FindName("CategoryPanel")
    confirm_btn        = window.FindName("ConfirmBtn")
    param_filter_check = window.FindName("ParamFilterCheck")
    param_filter_panel = window.FindName("ParamFilterPanel")
    param_combo        = window.FindName("ParamCombo")
    value_combo        = window.FindName("ValueCombo")

    result_holder      = [None]   # mutable container (IronPython 2.7 closure)
    selected_cat       = [None]   # currently selected category name
    radio_buttons      = []

    # ── Helper: decide whether Confirm should be active ────────────────────────
    def update_confirm():
        if selected_cat[0] is None:
            confirm_btn.IsEnabled = False
            return
        if param_filter_check.IsChecked == True:
            confirm_btn.IsEnabled = (
                param_combo.SelectedItem is not None and
                value_combo.SelectedItem is not None
            )
        else:
            confirm_btn.IsEnabled = True

    # ── Load parameter names into param_combo ──────────────────────────────────
    def load_params():
        param_combo.Items.Clear()
        value_combo.Items.Clear()
        value_combo.IsEnabled = False
        if selected_cat[0] is None:
            return
        for name in get_params_for_category(selected_cat[0]):
            param_combo.Items.Add(name)
        update_confirm()

    # ── Events ─────────────────────────────────────────────────────────────────
    def on_radio_checked(sender, e):
        selected_cat[0] = sender.Tag
        param_filter_check.IsEnabled = True
        # Refresh dropdowns if param panel is already visible
        if param_filter_check.IsChecked == True:
            load_params()
        else:
            param_combo.Items.Clear()
            value_combo.Items.Clear()
            value_combo.IsEnabled = False
        update_confirm()

    def on_search_changed(sender, e):
        query = search_box.Text.strip().lower()
        for rb in radio_buttons:
            rb.Visibility = (
                System.Windows.Visibility.Visible
                if query in rb.Tag.lower()
                else System.Windows.Visibility.Collapsed
            )

    def on_param_filter_toggled(sender, e):
        if param_filter_check.IsChecked == True:
            param_filter_panel.Visibility = System.Windows.Visibility.Visible
            load_params()
        else:
            param_filter_panel.Visibility = System.Windows.Visibility.Collapsed
            param_combo.Items.Clear()
            value_combo.Items.Clear()
        update_confirm()

    def on_param_changed(sender, e):
        value_combo.Items.Clear()
        value_combo.IsEnabled = False
        if selected_cat[0] is None or param_combo.SelectedItem is None:
            update_confirm()
            return
        for v in get_values_for_param(selected_cat[0], str(param_combo.SelectedItem)):
            value_combo.Items.Add(v)
        value_combo.IsEnabled = value_combo.Items.Count > 0
        update_confirm()

    def on_value_changed(sender, e):
        update_confirm()

    def on_confirm(sender, e):
        cat = selected_cat[0]
        if cat is None:
            return
        param_filter = None
        if param_filter_check.IsChecked == True:
            p = param_combo.SelectedItem
            v = value_combo.SelectedItem
            if p is not None and v is not None:
                param_filter = (str(p), str(v))
        result_holder[0] = (cat, param_filter)
        window.Close()

    # ── Build RadioButton list ─────────────────────────────────────────────────
    for name in all_categories:
        rb          = Controls.RadioButton()
        rb.Content  = name
        rb.Tag      = name
        rb.Checked += on_radio_checked
        cat_panel.Children.Add(rb)
        radio_buttons.append(rb)

    # ── Wire remaining events ──────────────────────────────────────────────────
    search_box.TextChanged        += on_search_changed
    param_filter_check.Checked    += on_param_filter_toggled
    param_filter_check.Unchecked  += on_param_filter_toggled
    param_combo.SelectionChanged  += on_param_changed
    value_combo.SelectionChanged  += on_value_changed
    confirm_btn.Click             += on_confirm

    update_confirm()
    window.ShowDialog()
    return result_holder[0]


# ─── SELECTION FILTER ─────────────────────────────────────────────────────────

class CustomISelectionFilter(ISelectionFilter):
    """
    Allows only elements that match *category_name*.
    If *param_filter* is supplied as (param_name, param_value),
    the element (or its type) must also carry that exact value.
    """
    def __init__(self, category_name, param_filter=None):
        self.category_name = category_name
        self.param_filter  = param_filter   # None | (str, str)

    def AllowElement(self, elem):
        if not (elem.Category and elem.Category.Name == self.category_name):
            return False
        if self.param_filter:
            pname, pval = self.param_filter
            return element_matches_param_filter(elem, pname, pval)
        return True

    def AllowReference(self, reference, position):
        return False


# ─── ACTIONS ──────────────────────────────────────────────────────────────────

def apply_category_filter(category_name, param_filter=None):
    """Restrict rectangle selection to elements matching the criteria."""
    try:
        sel_filter       = CustomISelectionFilter(category_name, param_filter)
        selected_elems   = selection.PickElementsByRectangle(sel_filter, "Select Elements")
        selected_ids     = [el.Id for el in selected_elems]
        uidoc.Selection.SetElementIds(List[ElementId](selected_ids))
    except Exception:
        script.exit()


def negate_selection(category_name, param_filter=None):
    """
    Rectangle select all, then DESELECT elements matching the criteria
    (keep everything that does NOT match).
    """
    try:
        elems = selection.PickElementsByRectangle("Select Elements")
        if param_filter:
            pname, pval = param_filter
            filtered_ids = [
                el.Id for el in elems
                if not (el.Category
                        and el.Category.Name == category_name
                        and element_matches_param_filter(el, pname, pval))
            ]
        else:
            filtered_ids = [
                el.Id for el in elems
                if not (el.Category and el.Category.Name == category_name)
            ]
        uidoc.Selection.SetElementIds(List[ElementId](filtered_ids))
    except Exception:
        script.exit()


# ─── MAIN ─────────────────────────────────────────────────────────────────────

all_categories = get_all_category_names(doc)
result         = show_category_picker(all_categories)

if not result:
    script.exit()

category_name, param_filter = result

if EXEC_PARAMS.config_mode:
    negate_selection(category_name, param_filter)
else:
    apply_category_filter(category_name, param_filter)
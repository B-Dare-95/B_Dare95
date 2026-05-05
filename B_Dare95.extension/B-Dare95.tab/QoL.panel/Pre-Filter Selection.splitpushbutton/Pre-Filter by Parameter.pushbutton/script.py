# -*- coding: utf-8 -*-
__title__ = "Pre-Filter by Parameter"
__author__ = "Mohamed Bedair"
__version__ = '1.3.1'
__doc__ = """

Description:
Filters the Selection box to only the selected category.
Optionally refines the selection further by stacking one or more
parameter-value filters (all filters applied with AND logic).
Also allows negating selection with SHIFT click.

How-to:
-> Run the script
-> Select a single category from the list
-> (Optional) Pick a parameter and value from the filter row
-> (Optional) Click "+ Add Filter" to stack more constraints
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
import System.Windows.Media as Media
import System.Windows.Input as WinInput
from System.Windows import (
    Thickness, CornerRadius, GridLength, GridUnitType, Visibility
)
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
SUBTEXT = "#000000"
ACCENT  = "#F0A500"

def _brush(hex_str):
    h = hex_str.lstrip('#')
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return Media.SolidColorBrush(Media.Color.FromRgb(r, g, b))

# Brushes used when building rows programmatically
SURFACE_BRUSH = _brush(SURFACE)
MUTED_BRUSH   = _brush(MUTED)
TEXT_BRUSH    = _brush(TEXT)
DARK_BRUSH    = Media.SolidColorBrush(Media.Color.FromRgb(20, 20, 20))  # dropdown item text
TRANS_BRUSH   = Media.Brushes.Transparent
# ──────────────────────────────────────────────────────────────────────────────

XAML_TEMPLATE = """
<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Choose Category"
    Width="390" MinHeight="120" MaxHeight="750"
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
                                <Setter TargetName="Ring" Property="Background"  Value="{ACCENT}"/>
                                <Setter TargetName="Ring" Property="BorderBrush" Value="{ACCENT}"/>
                                <Setter TargetName="Dot"  Property="Visibility"  Value="Visible"/>
                            </Trigger>
                            <Trigger Property="IsMouseOver" Value="True">
                                <Setter TargetName="Ring" Property="BorderBrush" Value="{ACCENT}"/>
                            </Trigger>
                        </ControlTemplate.Triggers>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>

        <!-- ── Accent (confirm) button ── -->
        <Style x:Key="AccentButton" TargetType="Button">
            <Setter Property="Background"      Value="{ACCENT}"/>
            <Setter Property="Foreground"      Value="{BG}"/>
            <Setter Property="FontWeight"      Value="SemiBold"/>
            <Setter Property="FontSize"        Value="13"/>
            <Setter Property="Height"          Value="36"/>
            <Setter Property="Cursor"          Value="Hand"/>
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

        <!-- ── Ghost button (+ Add Filter) ── -->
        <Style x:Key="GhostButton" TargetType="Button">
            <Setter Property="Background"      Value="Transparent"/>
            <Setter Property="Foreground"      Value="{TEXT}"/>
            <Setter Property="FontSize"        Value="12"/>
            <Setter Property="BorderThickness" Value="0"/>
            <Setter Property="Cursor"          Value="Hand"/>
            <Setter Property="Padding"         Value="0"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="Button">
                        <TextBlock x:Name="Tb"
                                   Text="{TemplateBinding Content}"
                                   Foreground="{TemplateBinding Foreground}"
                                   FontSize="{TemplateBinding FontSize}"
                                   VerticalAlignment="Center"/>
                        <ControlTemplate.Triggers>
                            <Trigger Property="IsMouseOver" Value="True">
                                <Setter TargetName="Tb" Property="Foreground" Value="{ACCENT}"/>
                            </Trigger>
                            <Trigger Property="IsEnabled" Value="False">
                                <Setter TargetName="Tb" Property="Opacity" Value="0.35"/>
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
                         ToolTip="Filter categories..."/>
            </Border>

            <!-- Category list (RadioButtons) -->
            <Border Background="{CARD}" CornerRadius="8"
                    Padding="10,8" Margin="0,0,0,14">
                <ScrollViewer MaxHeight="300"
                              VerticalScrollBarVisibility="Auto"
                              HorizontalScrollBarVisibility="Disabled"
                              Padding="0,0,4,0">
                    <StackPanel x:Name="CategoryPanel"/>
                </ScrollViewer>
            </Border>

            <!-- Divider -->
            <Border Height="1" Background="{MUTED}" Opacity="0.4" Margin="0,0,0,12"/>

            <!-- Parameter Filters header -->
            <DockPanel Margin="0,0,0,8" LastChildFill="False">
                <TextBlock Text="PARAMETER FILTERS"
                           Foreground="{TEXT}" FontSize="10" FontWeight="SemiBold"
                           VerticalAlignment="Center"
                           DockPanel.Dock="Left"/>
                <Button x:Name="AddRowBtn"
                        Content="+ Add Filter"
                        Style="{StaticResource GhostButton}"
                        DockPanel.Dock="Right"
                        IsEnabled="False"/>
            </DockPanel>

            <!-- Column labels — widths mirror the row grid -->
            <Grid Margin="0,0,0,5">
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="10"/>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="34"/>
                </Grid.ColumnDefinitions>
                <TextBlock Grid.Column="0" Text="Parameter"
                           Foreground="{TEXT}" FontSize="11" Margin="4,0,0,0"/>
                <TextBlock Grid.Column="2" Text="Value"
                           Foreground="{TEXT}" FontSize="11" Margin="4,0,0,0"/>
            </Grid>

            <!-- Dynamic filter rows injected by Python -->
            <StackPanel x:Name="RowsPanel" Margin="0,0,0,12"/>

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


# ─── REVIT HELPERS ────────────────────────────────────────────────────────────

def get_all_category_names(doc):
    return sorted(
        cat.Name for cat in doc.Settings.Categories
        if cat.CategoryType == CategoryType.Model
    )


def get_category_by_name(doc, name):
    for cat in doc.Settings.Categories:
        if cat.Name == name:
            return cat
    return None


def _eid_int(eid):
    """Read ElementId integer safely across Revit versions."""
    try:
        return eid.IntegerValue
    except AttributeError:
        return eid.Value      # Revit 2025+ (Int64)


def get_param_value_string(param):
    """Convert any parameter value to a readable string, or None."""
    try:
        if param is None or not param.HasValue:
            return None
        st = param.StorageType
        if st == StorageType.String:
            v = param.AsString()
            return v if v else None
        elif st == StorageType.Integer:
            vs = param.AsValueString()      # catches Yes/No, enum labels
            return vs if vs else str(param.AsInteger())
        elif st == StorageType.Double:
            vs = param.AsValueString()      # includes units
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
    Sorted list of every parameter name (instance + type) on elements
    of *category_name*, via an efficient ElementCategoryFilter pass.
    """
    cat_obj = get_category_by_name(doc, category_name)
    if cat_obj is None:
        return []

    params         = set()
    seen_type_ints = set()

    try:
        col = (FilteredElementCollector(doc)
               .WherePasses(ElementCategoryFilter(cat_obj.Id))
               .WhereElementIsNotElementType())
        for elem in col:
            for p in elem.Parameters:
                if p.Definition:
                    params.add(p.Definition.Name)
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
    Sorted list of unique human-readable values for *param_name* across all
    elements (instance + type) of *category_name*.
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
            p = elem.LookupParameter(param_name)
            if p:
                v = get_param_value_string(p)
                if v is not None:
                    values.add(v)
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


def element_matches_single_param(elem, param_name, param_value):
    """True if elem or its type has param_name equal to param_value."""
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


def element_matches_all_filters(elem, param_filters):
    """True if elem satisfies every (param_name, param_value) pair (AND logic)."""
    if not param_filters:
        return True
    for pname, pval in param_filters:
        if not element_matches_single_param(elem, pname, pval):
            return False
    return True


# ─── DIALOG ───────────────────────────────────────────────────────────────────

def _combo_item(text):
    """ComboBoxItem with dark text — readable in the default white popup."""
    item = Controls.ComboBoxItem()
    item.Content    = text
    item.Foreground = DARK_BRUSH
    item.Padding    = Thickness(6, 4, 6, 4)
    return item


def _combo_value(combo):
    """Return the selected value string from a ComboBox, or None."""
    sel = combo.SelectedItem
    if sel is None:
        return None
    return str(sel.Content) if hasattr(sel, 'Content') else str(sel)


def show_category_picker(all_categories):
    """
    Display the themed picker.

    Returns (category_name, param_filters) where:
        category_name  – str
        param_filters  – [] or [(param_name, param_value), ...]

    Returns None when the user closes without confirming.
    """
    window = XamlReader.Parse(XAML_TEMPLATE)

    search_box  = window.FindName("SearchBox")
    cat_panel   = window.FindName("CategoryPanel")
    confirm_btn = window.FindName("ConfirmBtn")
    add_row_btn = window.FindName("AddRowBtn")
    rows_panel  = window.FindName("RowsPanel")

    result_holder = [None]
    selected_cat  = [None]
    radio_buttons = []
    rows          = []        # list of row dicts

    # ── Confirm state ──────────────────────────────────────────────────────────
    def update_confirm():
        if selected_cat[0] is None:
            confirm_btn.IsEnabled = False
            return
        # Block only if a row has a param chosen, values exist, but none selected
        for row in rows:
            p_sel = _combo_value(row['param_combo'])
            v_sel = _combo_value(row['value_combo'])
            has_values = row['value_combo'].Items.Count > 0
            if p_sel is not None and has_values and v_sel is None:
                confirm_btn.IsEnabled = False
                return
        confirm_btn.IsEnabled = True

    # ── Populate param combo for one row ──────────────────────────────────────
    def populate_row_params(row):
        row['param_combo'].Items.Clear()
        row['value_combo'].Items.Clear()
        row['value_combo'].IsEnabled = False
        if selected_cat[0] is None:
            return
        for name in get_params_for_category(selected_cat[0]):
            row['param_combo'].Items.Add(_combo_item(name))

    # ── Populate value combo for one row ──────────────────────────────────────
    def reload_row_values(row):
        row['value_combo'].Items.Clear()
        row['value_combo'].IsEnabled = False
        p_val = _combo_value(row['param_combo'])
        if p_val is None or selected_cat[0] is None:
            update_confirm()
            return
        for v in get_values_for_param(selected_cat[0], p_val):
            row['value_combo'].Items.Add(_combo_item(v))
        row['value_combo'].IsEnabled = row['value_combo'].Items.Count > 0
        update_confirm()

    # ── Remove a row ──────────────────────────────────────────────────────────
    def remove_row(row):
        rows_panel.Children.Remove(row['grid'])
        rows.remove(row)
        update_confirm()

    # ── Create and attach one new filter row ──────────────────────────────────
    def create_filter_row():
        # Grid columns: [param | 10 | value | 8 | ×]
        grid = Controls.Grid()
        grid.Margin = Thickness(0, 0, 0, 6)
        for w in [
            GridLength(1, GridUnitType.Star),
            GridLength(10),
            GridLength(1, GridUnitType.Star),
            GridLength(8),
            GridLength.Auto,
        ]:
            cd = Controls.ColumnDefinition()
            cd.Width = w
            grid.ColumnDefinitions.Add(cd)

        # ── Parameter ComboBox ────────────────────────────────────────────────
        param_combo = Controls.ComboBox()
        param_combo.Background      = TRANS_BRUSH
        param_combo.Foreground      = DARK_BRUSH
        param_combo.BorderThickness = Thickness(0)
        param_combo.Height          = 30
        param_combo.FontSize        = 12
        param_combo.Padding         = Thickness(6, 0, 4, 0)
        param_combo.ToolTip         = "Select a parameter"

        param_border = Controls.Border()
        param_border.Background      = SURFACE_BRUSH
        param_border.CornerRadius    = CornerRadius(6)
        param_border.BorderBrush     = MUTED_BRUSH
        param_border.BorderThickness = Thickness(1)
        param_border.Child           = param_combo
        Controls.Grid.SetColumn(param_border, 0)
        grid.Children.Add(param_border)

        # ── Value ComboBox ────────────────────────────────────────────────────
        value_combo = Controls.ComboBox()
        value_combo.Background      = TRANS_BRUSH
        value_combo.Foreground      = DARK_BRUSH
        value_combo.BorderThickness = Thickness(0)
        value_combo.Height          = 30
        value_combo.FontSize        = 12
        value_combo.Padding         = Thickness(6, 0, 4, 0)
        value_combo.IsEnabled       = False
        value_combo.ToolTip         = "Select a value"

        value_border = Controls.Border()
        value_border.Background      = SURFACE_BRUSH
        value_border.CornerRadius    = CornerRadius(6)
        value_border.BorderBrush     = MUTED_BRUSH
        value_border.BorderThickness = Thickness(1)
        value_border.Child           = value_combo
        Controls.Grid.SetColumn(value_border, 2)
        grid.Children.Add(value_border)

        # ── Remove (×) button ─────────────────────────────────────────────────
        remove_btn = Controls.Button()
        remove_btn.Content           = "×"
        remove_btn.Width             = 26
        remove_btn.Height            = 26
        remove_btn.Background        = TRANS_BRUSH
        remove_btn.BorderThickness   = Thickness(0)
        remove_btn.Foreground        = MUTED_BRUSH
        remove_btn.FontSize          = 17
        remove_btn.Cursor            = WinInput.Cursors.Hand
        remove_btn.VerticalAlignment = System.Windows.VerticalAlignment.Center
        Controls.Grid.SetColumn(remove_btn, 4)
        grid.Children.Add(remove_btn)

        row = {
            'grid':        grid,
            'param_combo': param_combo,
            'value_combo': value_combo,
            'remove_btn':  remove_btn,
        }
        rows.append(row)
        rows_panel.Children.Add(grid)

        # Pre-populate params if category already chosen
        if selected_cat[0] is not None:
            populate_row_params(row)

        # Wire events — r=row default arg safely captures this row's reference
        def _on_param(s, e, r=row):
            reload_row_values(r)

        def _on_value(s, e):
            update_confirm()

        def _on_remove(s, e, r=row):
            remove_row(r)

        param_combo.SelectionChanged += _on_param
        value_combo.SelectionChanged += _on_value
        remove_btn.Click             += _on_remove

        update_confirm()

    # ── Category radio changed ─────────────────────────────────────────────────
    def on_radio_checked(sender, e):
        selected_cat[0] = sender.Tag
        add_row_btn.IsEnabled = True
        for row in rows:
            populate_row_params(row)
        update_confirm()

    # ── Search filter ──────────────────────────────────────────────────────────
    def on_search_changed(sender, e):
        query = search_box.Text.strip().lower()
        for rb in radio_buttons:
            rb.Visibility = (
                Visibility.Visible
                if query in rb.Tag.lower()
                else Visibility.Collapsed
            )

    # ── Add row button ─────────────────────────────────────────────────────────
    def on_add_row(sender, e):
        create_filter_row()

    # ── Confirm ────────────────────────────────────────────────────────────────
    def on_confirm(sender, e):
        cat = selected_cat[0]
        if cat is None:
            return
        param_filters = []
        for row in rows:
            p = _combo_value(row['param_combo'])
            v = _combo_value(row['value_combo'])
            if p is not None and v is not None:
                param_filters.append((p, v))
        result_holder[0] = (cat, param_filters)
        window.Close()

    # ── Build RadioButton list ─────────────────────────────────────────────────
    for name in all_categories:
        rb          = Controls.RadioButton()
        rb.Content  = name
        rb.Tag      = name
        rb.Checked += on_radio_checked
        cat_panel.Children.Add(rb)
        radio_buttons.append(rb)

    # ── Wire static events ─────────────────────────────────────────────────────
    search_box.TextChanged += on_search_changed
    add_row_btn.Click      += on_add_row
    confirm_btn.Click      += on_confirm

    # Start with one empty filter row
    create_filter_row()

    update_confirm()
    window.ShowDialog()
    return result_holder[0]


# ─── SELECTION FILTER ─────────────────────────────────────────────────────────

class CustomISelectionFilter(ISelectionFilter):
    """
    Allows elements whose category matches *category_name*.
    If *param_filters* is a non-empty list of (param_name, param_value) tuples,
    the element must also satisfy every filter (AND logic).
    """
    def __init__(self, category_name, param_filters=None):
        self.category_name = category_name
        self.param_filters = param_filters or []

    def AllowElement(self, elem):
        if not (elem.Category and elem.Category.Name == self.category_name):
            return False
        if self.param_filters:
            return element_matches_all_filters(elem, self.param_filters)
        return True

    def AllowReference(self, reference, position):
        return False


# ─── ACTIONS ──────────────────────────────────────────────────────────────────

def apply_category_filter(category_name, param_filters=None):
    """Restrict rectangle selection to elements matching all criteria."""
    try:
        sel_filter     = CustomISelectionFilter(category_name, param_filters)
        selected_elems = selection.PickElementsByRectangle(sel_filter, "Select Elements")
        selected_ids   = [el.Id for el in selected_elems]
        uidoc.Selection.SetElementIds(List[ElementId](selected_ids))
    except Exception:
        script.exit()


def negate_selection(category_name, param_filters=None):
    """
    Rectangle select all, then keep elements that do NOT match all criteria
    (SHIFT-click mode — inverts the filter).
    """
    try:
        elems = selection.PickElementsByRectangle("Select Elements")
        if param_filters:
            filtered_ids = [
                el.Id for el in elems
                if not (el.Category
                        and el.Category.Name == category_name
                        and element_matches_all_filters(el, param_filters))
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

category_name, param_filters = result

if EXEC_PARAMS.config_mode:
    negate_selection(category_name, param_filters)
else:
    apply_category_filter(category_name, param_filters)
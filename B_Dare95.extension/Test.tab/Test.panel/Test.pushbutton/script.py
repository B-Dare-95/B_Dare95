# -*- coding: utf-8 -*-

__title__   = "Shaft Function Tag"
__doc__     = """
________________________________________________________________
Description:
Reads the "Shaft Function" instance parameter from each Shaft
Opening and places a Text Note at the inner bottom-left corner
of the shaft boundary in every selected Plan View.

How to Use:
1. Run the script
2. Tick the target plan views
3. Choose a Text Note Type from the dropdown
4. Click Apply
________________________________________________________________
Author: Mohamed Bedair"""

# ─────────────────────────────────────────────────────────────────────
# Imports
# ─────────────────────────────────────────────────────────────────────
import clr
clr.AddReference('System')
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')

from System.IO       import MemoryStream
from System.Text     import Encoding
from System.Windows  import Thickness
from System.Windows.Controls import CheckBox
from System.Windows.Media    import SolidColorBrush, Color
import System.Windows.Markup as Markup

from Autodesk.Revit.DB import (
    FilteredElementCollector, ViewPlan, ViewType,
    BuiltInCategory, BuiltInParameter, ElementId,
    TextNote, TextNoteOptions, HorizontalTextAlignment,
    TextNoteType, Transaction, PlanViewPlane, Level, XYZ
)
from pyrevit import forms, script

# ─────────────────────────────────────────────────────────────────────
# Revit handles
# ─────────────────────────────────────────────────────────────────────
uidoc  = __revit__.ActiveUIDocument
doc    = __revit__.ActiveUIDocument.Document
output = script.get_output()

# ─────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────
SHAFT_FUNCTION_PARAM = "Shaft Function"

# Small inset from the bounding-box corner so the text sits inside
# the shaft boundary rather than on its edge (in Revit feet).
INSET_FT = 0.25


# ═════════════════════════════════════════════════════════════════════
# DATA COLLECTION
# ═════════════════════════════════════════════════════════════════════

def get_plan_views():
    views = FilteredElementCollector(doc).OfClass(ViewPlan).ToElements()
    return sorted(
        [v for v in views
         if not v.IsTemplate
         and v.ViewType in [ViewType.FloorPlan, ViewType.EngineeringPlan]],
        key=lambda v: v.Name
    )


def get_text_note_types():
    types = FilteredElementCollector(doc).OfClass(TextNoteType).ToElements()
    return sorted(
        types,
        key=lambda t: t.get_Parameter(
            BuiltInParameter.ALL_MODEL_TYPE_NAME).AsString()
    )


def get_all_shafts():
    return list(
        FilteredElementCollector(doc)
        .OfCategory(BuiltInCategory.OST_ShaftOpening)
        .WhereElementIsNotElementType()
        .ToElements()
    )


# ═════════════════════════════════════════════════════════════════════
# PARAMETER READING
# ═════════════════════════════════════════════════════════════════════

def get_shaft_function(shaft):
    """
    Returns the string value of the 'Shaft Function' parameter,
    or None if the parameter does not exist on this shaft.
    Returns an empty string if the parameter exists but has no value.
    """
    param = shaft.LookupParameter(SHAFT_FUNCTION_PARAM)
    if param is None:
        return None                         # parameter not found at all
    val = param.AsString()
    if val is None:
        val = param.AsValueString() or ""   # fallback for non-string storage
    return val


def validate_shaft_function_param(all_shafts):
    """
    Checks that at least one shaft carries the 'Shaft Function' parameter.
    Returns True if the parameter exists on any shaft, False otherwise.
    """
    for shaft in all_shafts:
        if shaft.LookupParameter(SHAFT_FUNCTION_PARAM) is not None:
            return True
    return False


# ═════════════════════════════════════════════════════════════════════
# SHAFT ELEVATION / VISIBILITY
# ═════════════════════════════════════════════════════════════════════

def get_view_cut_elevation(view):
    """Absolute cut-plane elevation (ft) for a ViewPlan."""
    try:
        vr         = view.GetViewRange()
        cut_lvl_id = vr.GetLevelId(PlanViewPlane.CutPlane)
        cut_offset = vr.GetOffset(PlanViewPlane.CutPlane)

        if cut_lvl_id != ElementId.InvalidElementId:
            cut_lvl = doc.GetElement(cut_lvl_id)
            if cut_lvl and isinstance(cut_lvl, Level):
                return cut_lvl.Elevation + cut_offset

        if view.GenLevel:
            return view.GenLevel.Elevation + cut_offset

        return cut_offset
    except Exception:
        try:
            return view.GenLevel.Elevation + 4.0
        except Exception:
            return 4.0


def shaft_elevations(shaft):
    """Returns (base_elev_ft, top_elev_ft). top is None if unconnected."""
    try:
        base_lvl_id = shaft.get_Parameter(
            BuiltInParameter.WALL_BASE_CONSTRAINT).AsElementId()
        base_offset = shaft.get_Parameter(
            BuiltInParameter.WALL_BASE_OFFSET).AsDouble()
        base_lvl    = doc.GetElement(base_lvl_id)
        if not base_lvl or not isinstance(base_lvl, Level):
            return None, None
        base_elev = base_lvl.Elevation + base_offset

        top_lvl_param = shaft.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE)
        top_lvl_id    = (top_lvl_param.AsElementId()
                         if top_lvl_param else ElementId.InvalidElementId)

        if top_lvl_id != ElementId.InvalidElementId:
            top_lvl = doc.GetElement(top_lvl_id)
            if not top_lvl or not isinstance(top_lvl, Level):
                return base_elev, None
            top_offset = shaft.get_Parameter(
                BuiltInParameter.WALL_TOP_OFFSET).AsDouble()
            top_elev = top_lvl.Elevation + top_offset
        else:
            uncon    = shaft.get_Parameter(BuiltInParameter.WALL_UNCONNECTED_HEIGHT)
            top_elev = (base_elev + uncon.AsDouble()) if uncon else None

        return base_elev, top_elev
    except Exception:
        return None, None


def shaft_visible_in_view(shaft, cut_elev):
    """True if the shaft straddles the view's cut-plane elevation."""
    base, top = shaft_elevations(shaft)
    if base is None:
        return False
    if top is None:
        return base < cut_elev
    return base < cut_elev < top


# ═════════════════════════════════════════════════════════════════════
# TEXT NOTE PLACEMENT
# ═════════════════════════════════════════════════════════════════════

def get_bottom_left_position(shaft, view):
    """
    Returns an XYZ point at the inner bottom-left corner of the shaft's
    bounding box in the given view, offset inward by INSET_FT.
    Returns None if no bounding box is available.
    """
    bbox = shaft.get_BoundingBox(view) or shaft.get_BoundingBox(None)
    if not bbox:
        return None

    x    = bbox.Min.X + INSET_FT
    y    = bbox.Min.Y + INSET_FT
    elev = view.GenLevel.Elevation if view.GenLevel else 0.0
    return XYZ(x, y, elev)


# ═════════════════════════════════════════════════════════════════════
# PER-VIEW PROCESSING  (called inside an active Transaction)
# ═════════════════════════════════════════════════════════════════════

def process_view(view, all_shafts, text_type_id):
    """
    For every shaft visible in this view that has a non-empty
    'Shaft Function' parameter value, place a left-aligned Text Note
    at the inner bottom-left of the shaft boundary.

    Returns a tuple (placed, skipped_no_value, skipped_no_bbox)
    """
    cut_elev         = get_view_cut_elevation(view)
    placed           = 0
    skipped_no_value = 0
    skipped_no_bbox  = 0

    for shaft in all_shafts:

        # 1. Must be visible at this view's cut plane
        if not shaft_visible_in_view(shaft, cut_elev):
            continue

        # 2. Read the Shaft Function parameter
        func_value = get_shaft_function(shaft)
        # func_value is None  → parameter doesn't exist (already validated globally)
        # func_value is ""    → exists but empty; skip gracefully
        if not func_value:
            skipped_no_value += 1
            continue

        # 3. Resolve text note position
        pos = get_bottom_left_position(shaft, view)
        if not pos:
            skipped_no_bbox += 1
            continue

        # 4. Create text note
        try:
            opts = TextNoteOptions(text_type_id)
            opts.HorizontalAlignment = HorizontalTextAlignment.Left
            TextNote.Create(doc, view.Id, pos, func_value, opts)
            placed += 1
        except Exception as tex:
            output.print_md(
                "  ⚠ Text note failed — shaft `{}` in **{}**: {}".format(
                    shaft.Id.IntegerValue, view.Name, str(tex)))

    return placed, skipped_no_value, skipped_no_bbox


# ═════════════════════════════════════════════════════════════════════
# WPF FORM
# ═════════════════════════════════════════════════════════════════════

def hex_brush(hex_str):
    h = hex_str.lstrip('#')
    return SolidColorBrush(
        Color.FromRgb(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)))


XAML = """
<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Shaft Function Tag"
    Height="540" Width="460"
    MinHeight="420"
    WindowStartupLocation="CenterScreen"
    ResizeMode="CanResizeWithGrip"
    Background="#1E1E2E"
    Foreground="#CDD6F4"
    FontFamily="Segoe UI"
    FontSize="12">

    <Grid Margin="18,18,18,16">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>  <!-- 0  Header             -->
            <RowDefinition Height="Auto"/>  <!-- 1  Views label row    -->
            <RowDefinition Height="*"/>     <!-- 2  Checkbox list      -->
            <RowDefinition Height="Auto"/>  <!-- 3  Text type label    -->
            <RowDefinition Height="Auto"/>  <!-- 4  Text type combo    -->
            <RowDefinition Height="Auto"/>  <!-- 5  Buttons            -->
        </Grid.RowDefinitions>

        <!-- 0  Header -->
        <StackPanel Grid.Row="0" Margin="0,0,0,14">
            <TextBlock Text="SHAFT FUNCTION TAG"
                       FontSize="16" FontWeight="Bold"
                       Foreground="#F0A500"/>
            <TextBlock Text="Place a text note with the shaft function at each shaft's bottom-left corner"
                       Foreground="#6C7086" FontSize="10.5" Margin="0,3,0,0"
                       TextWrapping="Wrap"/>
        </StackPanel>

        <!-- 1  Plan Views label + Select All / Clear -->
        <Grid Grid.Row="1" Margin="0,0,0,6">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="Auto"/>
                <ColumnDefinition Width="10"/>
                <ColumnDefinition Width="Auto"/>
            </Grid.ColumnDefinitions>
            <TextBlock Grid.Column="0" Text="Plan Views"
                       Foreground="#BAC2DE" FontWeight="SemiBold"
                       VerticalAlignment="Center"/>
            <Button Grid.Column="1" x:Name="SelectAllBtn" Content="Select All"
                    Background="Transparent" BorderBrush="Transparent"
                    Foreground="#F0A500" Cursor="Hand" FontSize="11"
                    Padding="0" VerticalAlignment="Center"/>
            <Button Grid.Column="3" x:Name="ClearAllBtn" Content="Clear All"
                    Background="Transparent" BorderBrush="Transparent"
                    Foreground="#6C7086" Cursor="Hand" FontSize="11"
                    Padding="0" VerticalAlignment="Center"/>
        </Grid>

        <!-- 2  Scrollable checkbox list -->
        <Border Grid.Row="2"
                Background="#181825" BorderBrush="#45475A"
                BorderThickness="1" CornerRadius="3"
                Margin="0,0,0,14">
            <ScrollViewer VerticalScrollBarVisibility="Auto">
                <StackPanel x:Name="ViewsPanel" Margin="6,4,6,4"/>
            </ScrollViewer>
        </Border>

        <!-- 3  Text Note Type label -->
        <TextBlock Grid.Row="3" Text="Text Note Type"
                   Foreground="#BAC2DE" FontWeight="SemiBold"
                   Margin="0,0,0,5"/>

        <!-- 4  Text Note Type combo — light bg, dark text -->
        <ComboBox Grid.Row="4" x:Name="TextTypeCombo"
                  Height="30" Margin="0,0,0,18"
                  Background="#FFFFFF" Foreground="#1E1E2E"
                  BorderBrush="#45475A">
            <ComboBox.ItemContainerStyle>
                <Style TargetType="ComboBoxItem">
                    <Setter Property="Foreground" Value="#1E1E2E"/>
                    <Setter Property="Background" Value="#FFFFFF"/>
                    <Style.Triggers>
                        <Trigger Property="IsHighlighted" Value="True">
                            <Setter Property="Background" Value="#E0E0E0"/>
                        </Trigger>
                    </Style.Triggers>
                </Style>
            </ComboBox.ItemContainerStyle>
        </ComboBox>

        <!-- 5  Buttons -->
        <StackPanel Grid.Row="5" Orientation="Horizontal"
                    HorizontalAlignment="Right">
            <Button x:Name="CancelBtn" Content="Cancel"
                    Width="90" Height="32" Margin="0,0,10,0"
                    Background="#313244" Foreground="#CDD6F4"
                    BorderBrush="#45475A"/>
            <Button x:Name="ApplyBtn" Content="Apply"
                    Width="90" Height="32"
                    Background="#F0A500" Foreground="#1E1E2E"
                    FontWeight="Bold" BorderBrush="#F0A500"/>
        </StackPanel>

    </Grid>
</Window>
"""


def show_form(plan_views, text_note_types):
    """
    Display the settings dialog.
    Returns:
      { 'ok': bool, 'views': [...], 'text_type_id': ElementId }
    or { 'ok': False } when cancelled.
    """
    stream = MemoryStream(Encoding.UTF8.GetBytes(XAML))
    window = Markup.XamlReader.Load(stream)

    views_panel    = window.FindName('ViewsPanel')
    tt_combo       = window.FindName('TextTypeCombo')
    apply_btn      = window.FindName('ApplyBtn')
    cancel_btn     = window.FindName('CancelBtn')
    select_all_btn = window.FindName('SelectAllBtn')
    clear_all_btn  = window.FindName('ClearAllBtn')

    # ── Build checkbox items ─────────────────────────────────────────
    view_checkboxes = []
    transparent     = SolidColorBrush(Color.FromArgb(0, 0, 0, 0))
    text_brush      = hex_brush('#CDD6F4')

    for v in plan_views:
        cb            = CheckBox()
        cb.Content    = v.Name
        cb.Foreground = text_brush
        cb.Background = transparent
        cb.Margin     = Thickness(4, 3, 4, 3)
        view_checkboxes.append(cb)
        views_panel.Children.Add(cb)

    # ── Populate text note type combo ────────────────────────────────
    for tt in text_note_types:
        name = tt.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME).AsString()
        tt_combo.Items.Add(name)
    if tt_combo.Items.Count > 0:
        tt_combo.SelectedIndex = 0

    result = {'ok': False}

    def on_select_all(s, e):
        for cb in view_checkboxes:
            cb.IsChecked = True

    def on_clear_all(s, e):
        for cb in view_checkboxes:
            cb.IsChecked = False

    def on_apply(s, e):
        selected_views = [plan_views[i]
                          for i, cb in enumerate(view_checkboxes)
                          if cb.IsChecked]
        if not selected_views:
            forms.alert("Please tick at least one plan view.",
                        title="No Views Selected")
            return
        if tt_combo.SelectedIndex < 0:
            forms.alert("Please select a text note type.",
                        title="No Text Note Type Selected")
            return

        result['ok']           = True
        result['views']        = selected_views
        result['text_type_id'] = text_note_types[tt_combo.SelectedIndex].Id
        window.Close()

    def on_cancel(s, e):
        window.Close()

    apply_btn.Click      += on_apply
    cancel_btn.Click     += on_cancel
    select_all_btn.Click += on_select_all
    clear_all_btn.Click  += on_clear_all

    window.ShowDialog()
    return result


# ═════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════

def main():

    # ── Pre-flight: collect data ─────────────────────────────────────
    plan_views      = get_plan_views()
    text_note_types = get_text_note_types()
    all_shafts      = get_all_shafts()

    if not plan_views:
        forms.alert("No floor plan views found in the document.",
                    title="Shaft Function Tag")
        return

    if not text_note_types:
        forms.alert("No text note types found in the document.",
                    title="Shaft Function Tag")
        return

    if not all_shafts:
        forms.alert("No shaft openings found in the document.",
                    title="Shaft Function Tag")
        return

    # ── Pre-flight: validate that the parameter exists on at least one shaft
    if not validate_shaft_function_param(all_shafts):
        forms.alert(
            'The parameter "{}" was not found on any Shaft Opening in this '
            'document.\n\n'
            'Please ensure the parameter exists as an Instance parameter on '
            'the Shaft Opening category before running this script.'.format(
                SHAFT_FUNCTION_PARAM),
            title="Parameter Not Found")
        return

    # ── Show dialog ──────────────────────────────────────────────────
    result = show_form(plan_views, text_note_types)
    if not result.get('ok'):
        return

    selected_views = result['views']
    text_type_id   = result['text_type_id']

    # ── Process each view in its own transaction ─────────────────────
    output.print_md("## Shaft Function Tag — Results\n")

    total_placed = 0
    error_views  = []

    for view in selected_views:
        t = Transaction(doc, "Shaft Function Tag — {}".format(view.Name))
        t.Start()
        try:
            placed, no_val, no_bbox = process_view(view, all_shafts, text_type_id)
            t.Commit()
            total_placed += placed

            detail = "{}  tagged".format(placed)
            if no_val:
                detail += ",  {}  skipped (empty parameter)".format(no_val)
            if no_bbox:
                detail += ",  {}  skipped (no bounding box)".format(no_bbox)

            output.print_md("- ✅ **{}** — {}".format(view.Name, detail))

        except Exception as ex:
            try:
                t.RollBack()
            except Exception:
                pass
            error_views.append(view.Name)
            output.print_md(
                "- ❌ **{}** — Error: `{}`".format(view.Name, str(ex)))

    # ── Summary alert ────────────────────────────────────────────────
    summary = (
        "Done!\n\n"
        "Views processed : {}\n"
        "Text notes placed: {}"
    ).format(len(selected_views) - len(error_views), total_placed)

    if error_views:
        summary += "\n\nFailed views:\n" + "\n".join("  • " + n for n in error_views)

    forms.alert(summary, title="Shaft Function Tag")


main()
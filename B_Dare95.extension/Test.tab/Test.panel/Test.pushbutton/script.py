# -*- coding: utf-8 -*-

__title__   = "Shaft Open Above"
__doc__     = """
________________________________________________________________
Description:
Detects Shaft Openings in selected 2D Plan Views and marks
shafts that are open above the view level with:
  - A graphical line style override on the shaft boundary
  - A text annotation placed beneath the shaft

How to Use:
1. Run the script
2. Tick the target plan views in the list
3. Choose the override line style
4. Choose the text note type
5. Edit the annotation text (default: "Open Above")
6. Click Apply
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

import System
from System.IO       import MemoryStream
from System.Text     import Encoding
from System.Windows  import Thickness
from System.Windows.Controls import CheckBox
from System.Windows.Media    import SolidColorBrush, Color
import System.Windows.Markup as Markup

from Autodesk.Revit.DB import (
    FilteredElementCollector, ViewPlan, ViewType,
    BuiltInCategory, BuiltInParameter, GraphicsStyle,
    GraphicsStyleType, OverrideGraphicSettings, ElementId,
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
# Elevation tolerance in feet (~1.2 inches).
# A shaft whose top is within this margin of the view level is NOT
# considered "open above" — this prevents false positives from shafts
# that end at a level with a tiny floating-point top offset, or shafts
# that only protrude BELOW the view level via a negative base offset.
ELEV_TOLERANCE_FT = 0.1

# Vertical gap below the shaft bounding box for text note placement (ft).
TEXT_OFFSET_FT = 1.5


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


def get_line_styles():
    lines_cat = doc.Settings.Categories.get_Item(BuiltInCategory.OST_Lines)
    styles = []
    for sub in lines_cat.SubCategories:
        gs = sub.GetGraphicsStyle(GraphicsStyleType.Projection)
        if gs is not None:
            styles.append(gs)
    return sorted(styles, key=lambda s: s.Name)


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
# SHAFT ELEVATION ANALYSIS
# ═════════════════════════════════════════════════════════════════════

def get_shaft_elevations(shaft):
    """
    Returns (base_elev_ft, top_elev_ft).
    top_elev_ft is None when shaft is unconnected (no top constraint).
    Returns (None, None) on any error.
    """
    try:
        # ── Base ──────────────────────────────────────────────────────
        base_lvl_id = shaft.get_Parameter(
            BuiltInParameter.WALL_BASE_CONSTRAINT).AsElementId()
        base_offset = shaft.get_Parameter(
            BuiltInParameter.WALL_BASE_OFFSET).AsDouble()
        base_lvl    = doc.GetElement(base_lvl_id)
        if not base_lvl or not isinstance(base_lvl, Level):
            return None, None
        base_elev = base_lvl.Elevation + base_offset

        # ── Top ───────────────────────────────────────────────────────
        top_lvl_param = shaft.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE)
        top_lvl_id    = (top_lvl_param.AsElementId()
                         if top_lvl_param else ElementId.InvalidElementId)

        if top_lvl_id != ElementId.InvalidElementId:
            top_lvl = doc.GetElement(top_lvl_id)
            if not top_lvl or not isinstance(top_lvl, Level):
                return base_elev, None
            top_offset = shaft.get_Parameter(
                BuiltInParameter.WALL_TOP_OFFSET).AsDouble()
            top_elev   = top_lvl.Elevation + top_offset
        else:
            # Unconnected — explicit height if available, else None
            uncon    = shaft.get_Parameter(BuiltInParameter.WALL_UNCONNECTED_HEIGHT)
            top_elev = (base_elev + uncon.AsDouble()) if uncon else None

        return base_elev, top_elev

    except Exception:
        return None, None


def get_view_cut_elevation(view):
    """
    Returns the absolute cut-plane elevation (ft) for a ViewPlan.
    Falls back gracefully when the view range API is unavailable.
    """
    try:
        vr         = view.GetViewRange()
        cut_lvl_id = vr.GetLevelId(PlanViewPlane.CutPlane)
        cut_offset = vr.GetOffset(PlanViewPlane.CutPlane)

        if cut_lvl_id != ElementId.InvalidElementId:
            cut_lvl = doc.GetElement(cut_lvl_id)
            if cut_lvl and isinstance(cut_lvl, Level):
                return cut_lvl.Elevation + cut_offset

        # Cut plane is relative to the view's associated level
        if view.GenLevel:
            return view.GenLevel.Elevation + cut_offset

        return cut_offset

    except Exception:
        try:
            return view.GenLevel.Elevation + 4.0   # typical default
        except Exception:
            return 4.0


def shaft_crosses_cut_plane(shaft, cut_elev):
    """
    True if the shaft's vertical range straddles the cut-plane elevation
    (i.e. the shaft is visible at this view's cut plane).
    """
    base, top = get_shaft_elevations(shaft)
    if base is None:
        return False
    if top is None:                     # unconnected — visible if base below cut
        return base < cut_elev
    return base < cut_elev < top


def shaft_is_open_above(shaft, view_level_elev):
    """
    True if the shaft's top extends MEANINGFULLY above the view's
    associated level elevation.

    The ELEV_TOLERANCE_FT guard prevents false positives in two cases:
      a) Floating-point noise: a shaft whose top constraint is the same
         level as the view but whose stored offset is 0.001 ft.
      b) Negative-base-offset shafts: a shaft modelled to start below
         the view level (negative base offset) but whose TOP is exactly
         at — or just barely above — the view level due to modelling
         convention rather than actual openness.
    """
    _, top = get_shaft_elevations(shaft)
    if top is None:                     # unconnected = always open above
        return True
    return top > view_level_elev + ELEV_TOLERANCE_FT


# ═════════════════════════════════════════════════════════════════════
# TEXT NOTE PLACEMENT
# ═════════════════════════════════════════════════════════════════════

def get_text_position(shaft, view):
    """
    XYZ centred on the shaft, TEXT_OFFSET_FT below its min-Y extent,
    at the view's level elevation. Returns None if bbox unavailable.
    """
    bbox = shaft.get_BoundingBox(view) or shaft.get_BoundingBox(None)
    if not bbox:
        return None
    cx   = (bbox.Min.X + bbox.Max.X) / 2.0
    cy   = bbox.Min.Y - TEXT_OFFSET_FT
    elev = view.GenLevel.Elevation if view.GenLevel else 0.0
    return XYZ(cx, cy, elev)


# ═════════════════════════════════════════════════════════════════════
# GRAPHICAL OVERRIDE
# ═════════════════════════════════════════════════════════════════════

def build_override_settings(line_style_gs):
    """
    Build OverrideGraphicSettings from the chosen GraphicsStyle:
    applies colour, weight and line pattern to both projection and
    cut lines.
    """
    ogs    = OverrideGraphicSettings()
    cat    = line_style_gs.GraphicsStyleCategory
    color  = cat.LineColor
    weight = cat.GetLineWeight(GraphicsStyleType.Projection)
    pat_id = cat.GetLinePatternId(GraphicsStyleType.Projection)

    if color and color.IsValid:
        ogs.SetProjectionLineColor(color)
        ogs.SetCutLineColor(color)
    if weight and weight > 0:
        ogs.SetProjectionLineWeight(weight)
        ogs.SetCutLineWeight(weight)
    if pat_id and pat_id != ElementId.InvalidElementId:
        ogs.SetProjectionLinePatternId(pat_id)
        ogs.SetCutLinePatternId(pat_id)

    return ogs


# ═════════════════════════════════════════════════════════════════════
# PER-VIEW PROCESSING  (must be called inside an active Transaction)
# ═════════════════════════════════════════════════════════════════════

def process_view(view, all_shafts, ogs, annotation_text, text_type_id):
    """
    Evaluate every shaft against the view's cut plane and level elevation.
    Applies override + text annotation to qualifying shafts.
    Returns the count of shafts marked.
    """
    cut_elev      = get_view_cut_elevation(view)
    view_lvl_elev = view.GenLevel.Elevation if view.GenLevel else 0.0
    count         = 0

    for shaft in all_shafts:

        # 1. Must be visible at this view's cut plane
        if not shaft_crosses_cut_plane(shaft, cut_elev):
            continue

        # 2. Top must meaningfully extend above the view level
        if not shaft_is_open_above(shaft, view_lvl_elev):
            continue

        # 3. Apply line style graphical override
        view.SetElementOverrides(shaft.Id, ogs)

        # 4. Place annotation below the shaft
        if text_type_id:
            pos = get_text_position(shaft, view)
            if pos:
                try:
                    opts = TextNoteOptions(text_type_id)
                    opts.HorizontalAlignment = HorizontalTextAlignment.Center
                    TextNote.Create(doc, view.Id, pos, annotation_text, opts)
                except Exception as tex:
                    output.print_md(
                        "  ⚠ Text note failed — shaft `{}` in **{}**: {}".format(
                            shaft.Id.IntegerValue, view.Name, str(tex)))

        count += 1

    return count


# ═════════════════════════════════════════════════════════════════════
# WPF FORM
# ═════════════════════════════════════════════════════════════════════

def hex_brush(hex_str):
    """Return a SolidColorBrush from a '#RRGGBB' hex string."""
    h = hex_str.lstrip('#')
    return SolidColorBrush(
        Color.FromRgb(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)))


XAML = """
<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Shaft Open Above"
    Height="620" Width="480"
    MinHeight="500"
    WindowStartupLocation="CenterScreen"
    ResizeMode="CanResizeWithGrip"
    Background="#1E1E2E"
    Foreground="#CDD6F4"
    FontFamily="Segoe UI"
    FontSize="12">

    <Grid Margin="18,18,18,16">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <!-- 0  Header -->
        <StackPanel Grid.Row="0" Margin="0,0,0,14">
            <TextBlock Text="SHAFT OPEN ABOVE"
                       FontSize="16" FontWeight="Bold"
                       Foreground="#F0A500"/>
            <TextBlock Text="Detect and annotate shafts that protrude above the view level"
                       Foreground="#6C7086" FontSize="10.5" Margin="0,3,0,0"/>
        </StackPanel>

        <!-- 1  Plan Views label row -->
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

        <!-- 3  Line Style label -->
        <TextBlock Grid.Row="3" Text="Override Line Style"
                   Foreground="#BAC2DE" FontWeight="SemiBold"
                   Margin="0,0,0,5"/>

        <!-- 4  Line Style combo — light background, dark text -->
        <ComboBox Grid.Row="4" x:Name="LineStyleCombo"
                  Height="30" Margin="0,0,0,14"
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

        <!-- 5  Annotation labels row -->
        <Grid Grid.Row="5" Margin="0,0,0,5">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="12"/>
                <ColumnDefinition Width="180"/>
            </Grid.ColumnDefinitions>
            <TextBlock Grid.Column="0" Text="Annotation Text"
                       Foreground="#BAC2DE" FontWeight="SemiBold"/>
            <TextBlock Grid.Column="2" Text="Text Note Type"
                       Foreground="#BAC2DE" FontWeight="SemiBold"/>
        </Grid>

        <!-- 6  Annotation inputs row -->
        <Grid Grid.Row="6" Margin="0,0,0,18">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="12"/>
                <ColumnDefinition Width="180"/>
            </Grid.ColumnDefinitions>

            <TextBox Grid.Column="0" x:Name="AnnotationTextBox"
                     Height="30" Padding="8,5"
                     Background="#181825" Foreground="#CDD6F4"
                     BorderBrush="#45475A" CaretBrush="#F0A500"
                     Text="Open Above"/>

            <!-- Text Note Type combo — light background, dark text -->
            <ComboBox Grid.Column="2" x:Name="TextTypeCombo"
                      Height="30"
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
        </Grid>

        <!-- 7  Buttons -->
        <StackPanel Grid.Row="7" Orientation="Horizontal"
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


def show_form(plan_views, line_styles, text_note_types):
    """
    Display the settings dialog.
    Returns:
      { 'ok': bool, 'views': [...], 'line_style': GraphicsStyle,
        'text': str, 'text_type_id': ElementId }
    """
    stream = MemoryStream(Encoding.UTF8.GetBytes(XAML))
    window = Markup.XamlReader.Load(stream)

    views_panel    = window.FindName('ViewsPanel')
    ls_combo       = window.FindName('LineStyleCombo')
    tt_combo       = window.FindName('TextTypeCombo')
    text_box       = window.FindName('AnnotationTextBox')
    apply_btn      = window.FindName('ApplyBtn')
    cancel_btn     = window.FindName('CancelBtn')
    select_all_btn = window.FindName('SelectAllBtn')
    clear_all_btn  = window.FindName('ClearAllBtn')

    # ── Build checkbox items for each plan view ──────────────────────
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

    # ── Populate Line Style combo ────────────────────────────────────
    for ls in line_styles:
        ls_combo.Items.Add(ls.Name)
    if ls_combo.Items.Count > 0:
        ls_combo.SelectedIndex = 0

    # ── Populate Text Note Type combo ────────────────────────────────
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
        if ls_combo.SelectedIndex < 0:
            forms.alert("Please select a line style.",
                        title="No Line Style Selected")
            return
        if tt_combo.SelectedIndex < 0:
            forms.alert("Please select a text note type.",
                        title="No Text Note Type Selected")
            return

        result['ok']           = True
        result['views']        = selected_views
        result['line_style']   = line_styles[ls_combo.SelectedIndex]
        result['text']         = text_box.Text.strip() or "Open Above"
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
    plan_views      = get_plan_views()
    line_styles     = get_line_styles()
    text_note_types = get_text_note_types()

    if not plan_views:
        forms.alert("No floor plan views found in the document.",
                    title="Shaft Open Above")
        return
    if not line_styles:
        forms.alert(
            "No custom line styles found.\n"
            "Create one via  Manage → Additional Settings → Line Styles.",
            title="Shaft Open Above")
        return
    if not text_note_types:
        forms.alert("No text note types found in the document.",
                    title="Shaft Open Above")
        return

    result = show_form(plan_views, line_styles, text_note_types)
    if not result.get('ok'):
        return

    selected_views = result['views']
    chosen_style   = result['line_style']
    annot_text     = result['text']
    text_type_id   = result['text_type_id']
    all_shafts     = get_all_shafts()
    ogs            = build_override_settings(chosen_style)

    if not all_shafts:
        forms.alert("No shaft openings found in the document.",
                    title="Shaft Open Above")
        return

    # ── Process each selected view in its own transaction ────────────
    output.print_md("## Shaft Open Above — Results\n")
    output.print_md(
        "**Line Style:** `{}`  |  **Text:** `{}`  |  **Elev. tolerance:** {:.2f} ft\n".format(
            chosen_style.Name, annot_text, ELEV_TOLERANCE_FT))

    total_shafts = 0
    error_views  = []

    for view in selected_views:
        t = Transaction(doc, "Shaft Open Above — {}".format(view.Name))
        t.Start()
        try:
            count = process_view(
                view, all_shafts, ogs, annot_text, text_type_id)
            t.Commit()
            total_shafts += count
            output.print_md(
                "- ✅ **{}** — {} shaft(s) marked".format(view.Name, count))
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
        "Shafts marked   : {}"
    ).format(len(selected_views) - len(error_views), total_shafts)

    if error_views:
        summary += "\n\nFailed views:\n" + "\n".join("  • " + n for n in error_views)

    forms.alert(summary, title="Shaft Open Above")


main()
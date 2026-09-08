# -*- coding: utf-8 -*-

__title__   = "Shaft Function Tag"
__doc__     = """
________________________________________________________________
Description:
Reads the "Shaft Function" instance parameter from each Shaft
Opening — in the ACTIVE model and in every LOADED LINKED model —
and places a Text Note at the inner bottom-left corner of the
shaft boundary in every selected Plan View.

How to Use:
1. Run the script
2. Optionally toggle "Include shafts from linked models"
3. Tick the target plan views
4. Choose a Text Note Type from the dropdown
5. Click Apply
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
from System.Windows  import Thickness, Visibility
from System.Windows.Controls import CheckBox, TextBox
from System.Windows.Media    import SolidColorBrush, Color
import System.Windows.Markup as Markup

from Autodesk.Revit.DB import (
    FilteredElementCollector, ViewPlan, ViewType,
    BuiltInCategory, BuiltInParameter, ElementId,
    TextNote, TextNoteOptions, HorizontalTextAlignment,
    TextNoteType, Transaction, PlanViewPlane, Level, XYZ,
    RevitLinkInstance, Transform
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
# HELPERS
# ═════════════════════════════════════════════════════════════════════

def safe_id_int(element_id):
    """.Value with .IntegerValue fallback (Revit 2025+ compatibility)."""
    try:
        return element_id.Value
    except Exception:
        return element_id.IntegerValue

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
    """
    Collects Shaft Opening elements from the ACTIVE document and from
    every loaded RevitLinkInstance in the model.

    Returns a list of dicts:
        {
            'element':   the Shaft Opening element
            'doc':       the Document the shaft actually lives in
                         (host doc, or the linked doc)
            'transform': Transform mapping the shaft's local (link)
                         coordinates into HOST coordinates.
                         Transform.Identity for host shafts.
            'link_name': "Host Model" or the RevitLinkInstance name
            'is_linked': bool
        }
    """
    results = []

    # ── Host (active) model shafts ───────────────────────────────────
    host_shafts = (
        FilteredElementCollector(doc)
        .OfCategory(BuiltInCategory.OST_ShaftOpening)
        .WhereElementIsNotElementType()
        .ToElements()
    )
    for s in host_shafts:
        results.append({
            'element':   s,
            'doc':       doc,
            'transform': Transform.Identity,
            'link_name': 'Host Model',
            'is_linked': False
        })

    # ── Linked model shafts ───────────────────────────────────────────
    link_instances = (
        FilteredElementCollector(doc)
        .OfClass(RevitLinkInstance)
        .ToElements()
    )

    for li in link_instances:
        try:
            link_doc = li.GetLinkDocument()
        except Exception:
            link_doc = None

        if link_doc is None:
            continue  # link is unloaded / not resolved — skip it

        try:
            transform = li.GetTotalTransform()
        except Exception:
            continue

        link_name = li.Name

        try:
            link_shafts = (
                FilteredElementCollector(link_doc)
                .OfCategory(BuiltInCategory.OST_ShaftOpening)
                .WhereElementIsNotElementType()
                .ToElements()
            )
        except Exception:
            continue

        for s in link_shafts:
            results.append({
                'element':   s,
                'doc':       link_doc,
                'transform': transform,
                'link_name': link_name,
                'is_linked': True
            })

    return results

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
    Checks that at least one shaft (host OR linked) carries the
    'Shaft Function' parameter.
    Returns True if the parameter exists on any shaft, False otherwise.
    """
    for shaft_info in all_shafts:
        if shaft_info['element'].LookupParameter(SHAFT_FUNCTION_PARAM) is not None:
            return True
    return False

# ═════════════════════════════════════════════════════════════════════
# SHAFT ELEVATION / VISIBILITY
# ═════════════════════════════════════════════════════════════════════

def get_view_cut_elevation(view):
    """Absolute cut-plane elevation (ft) for a ViewPlan (host coordinates)."""
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


def shaft_elevations(shaft_info):
    """
    Returns (base_elev_ft, top_elev_ft) in HOST coordinates.
    top is None if unconnected.

    For linked shafts, the base/top levels live in the LINKED document,
    so we look them up there, then map the resulting elevation into
    host coordinates via the link's total transform. Revit link
    transforms only rotate about the vertical (Z) axis, so applying the
    transform to a (0, 0, elevation) point yields an exact host Z.
    """
    shaft     = shaft_info['element']
    sdoc      = shaft_info['doc']
    transform = shaft_info['transform']

    try:
        base_lvl_id = shaft.get_Parameter(
            BuiltInParameter.WALL_BASE_CONSTRAINT).AsElementId()
        base_offset = shaft.get_Parameter(
            BuiltInParameter.WALL_BASE_OFFSET).AsDouble()
        base_lvl    = sdoc.GetElement(base_lvl_id)
        if not base_lvl or not isinstance(base_lvl, Level):
            return None, None
        base_elev_local = base_lvl.Elevation + base_offset

        top_lvl_param = shaft.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE)
        top_lvl_id    = (top_lvl_param.AsElementId()
                         if top_lvl_param else ElementId.InvalidElementId)

        top_elev_local = None
        if top_lvl_id != ElementId.InvalidElementId:
            top_lvl = sdoc.GetElement(top_lvl_id)
            if top_lvl and isinstance(top_lvl, Level):
                top_offset = shaft.get_Parameter(
                    BuiltInParameter.WALL_TOP_OFFSET).AsDouble()
                top_elev_local = top_lvl.Elevation + top_offset
        else:
            uncon = shaft.get_Parameter(BuiltInParameter.WALL_UNCONNECTED_HEIGHT)
            top_elev_local = (base_elev_local + uncon.AsDouble()) if uncon else None

        # Map local (link) elevations into host coordinates.
        base_elev = transform.OfPoint(XYZ(0, 0, base_elev_local)).Z
        top_elev  = (transform.OfPoint(XYZ(0, 0, top_elev_local)).Z
                     if top_elev_local is not None else None)

        return base_elev, top_elev
    except Exception:
        return None, None


def shaft_visible_in_view(shaft_info, cut_elev):
    """True if the shaft straddles the view's cut-plane elevation (host)."""
    base, top = shaft_elevations(shaft_info)
    if base is None:
        return False
    if top is None:
        return base < cut_elev
    return base < cut_elev < top

# ═════════════════════════════════════════════════════════════════════
# TEXT NOTE PLACEMENT
# ═════════════════════════════════════════════════════════════════════

def get_bottom_left_position(shaft_info, view):
    """
    Returns an XYZ point (in HOST coordinates) at the inner bottom-left
    corner of the shaft's model-space bounding box, offset inward by
    INSET_FT, then mapped through the shaft's link transform.

    IMPORTANT: We deliberately pass None (not the view) to get_BoundingBox.
    Passing a non-active view forces Revit to regenerate graphics for that
    view on every call, causing the 'Generating Graphics for View' infinite
    loop. The model-space bbox gives identical X/Y results for a plan view
    and requires no view regeneration.

    Returns None if no bounding box is available.
    """
    shaft     = shaft_info['element']
    transform = shaft_info['transform']

    bbox = shaft.get_BoundingBox(None)
    if not bbox:
        return None

    local_pt = XYZ(bbox.Min.X + INSET_FT, bbox.Min.Y + INSET_FT, bbox.Min.Z)
    host_pt  = transform.OfPoint(local_pt)

    elev = view.GenLevel.Elevation if view.GenLevel else 0.0
    return XYZ(host_pt.X, host_pt.Y, elev)

# ═════════════════════════════════════════════════════════════════════
# PER-VIEW PROCESSING  (called inside an active Transaction)
# ═════════════════════════════════════════════════════════════════════

def process_view(view, shafts_to_use, text_type_id):
    """
    For every shaft (host or linked) visible in this view that has a
    non-empty 'Shaft Function' parameter value, place a left-aligned
    Text Note at the inner bottom-left of the shaft boundary.

    Returns a tuple (placed, skipped_no_value, skipped_no_bbox)
    """
    cut_elev         = get_view_cut_elevation(view)
    placed           = 0
    skipped_no_value = 0
    skipped_no_bbox  = 0

    for shaft_info in shafts_to_use:
        shaft = shaft_info['element']

        # 1. Must be visible at this view's cut plane
        if not shaft_visible_in_view(shaft_info, cut_elev):
            continue

        # 2. Read the Shaft Function parameter
        func_value = get_shaft_function(shaft)
        # func_value is None  → parameter doesn't exist (already validated globally)
        # func_value is ""    → exists but empty; skip gracefully
        if not func_value:
            skipped_no_value += 1
            continue

        # 3. Resolve text note position (host coordinates)
        pos = get_bottom_left_position(shaft_info, view)
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
                "  ⚠ Text note failed — shaft `{}` ({}) in **{}**: {}".format(
                    safe_id_int(shaft.Id), shaft_info['link_name'],
                    view.Name, str(tex)))

    return placed, skipped_no_value, skipped_no_bbox

# ═════════════════════════════════════════════════════════════════════
# WPF FORM
# ═════════════════════════════════════════════════════════════════════

XAML = """
<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Shaft Function Tag"
    Height="640" Width="460"
    MinHeight="480"
    WindowStartupLocation="CenterScreen"
    Background="#1E1E2E" Foreground="#CDD6F4"
    FontFamily="Segoe UI" FontSize="12">

    <Window.Resources>
        <Style TargetType="CheckBox">
            <Setter Property="Foreground" Value="White"/>
            <Setter Property="Margin" Value="4,3,4,3"/>
            <Setter Property="VerticalContentAlignment" Value="Center"/>
        </Style>
    </Window.Resources>

    <Grid Margin="18">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <StackPanel Grid.Row="0" Margin="0,0,0,10">
            <TextBlock Text="SHAFT FUNCTION TAG" FontSize="16" FontWeight="Bold" Foreground="#F0A500"/>
        </StackPanel>

        <CheckBox Grid.Row="1" x:Name="IncludeLinkedCheckBox"
                  Content="Include shafts from linked models"
                  IsChecked="True" Margin="0,0,0,10"/>

        <TextBox Grid.Row="2" x:Name="SearchBox" Height="25" Margin="0,0,0,10"
                 Background="#181825" Foreground="White" BorderBrush="#45475A"
                 VerticalContentAlignment="Center" Padding="5,0,0,0"/>

        <Grid Grid.Row="3" Margin="0,0,0,6">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="Auto"/>
                <ColumnDefinition Width="10"/>
                <ColumnDefinition Width="Auto"/>
            </Grid.ColumnDefinitions>
            <TextBlock Grid.Column="0" Text="Plan Views" Foreground="#BAC2DE" FontWeight="SemiBold"/>
            <Button Grid.Column="1" x:Name="SelectAllBtn" Content="Select All" Background="Transparent" BorderBrush="Transparent" Foreground="#F0A500"/>
            <Button Grid.Column="3" x:Name="ClearAllBtn" Content="Clear All" Background="Transparent" BorderBrush="Transparent" Foreground="#6C7086"/>
        </Grid>

        <Border Grid.Row="4" Background="#181825" BorderBrush="#45475A" BorderThickness="1" CornerRadius="3" Margin="0,0,0,14">
            <ScrollViewer VerticalScrollBarVisibility="Auto">
                <StackPanel x:Name="ViewsPanel" Margin="6"/>
            </ScrollViewer>
        </Border>

        <TextBlock Grid.Row="5" Text="Text Note Type" Foreground="#BAC2DE" FontWeight="SemiBold" Margin="0,0,0,5"/>
        <ComboBox Grid.Row="6" x:Name="TextTypeCombo" Height="30" Margin="0,0,0,18" Background="White" Foreground="#1E1E2E"/>

        <StackPanel Grid.Row="7" Orientation="Horizontal" HorizontalAlignment="Right">
            <Button x:Name="CancelBtn" Content="Cancel" Width="90" Height="32" Margin="0,0,10,0" Background="#313244" Foreground="#CDD6F4"/>
            <Button x:Name="ApplyBtn" Content="Apply" Width="90" Height="32" Background="#F0A500" Foreground="#1E1E2E" FontWeight="Bold"/>
        </StackPanel>
    </Grid>
</Window>
"""

def show_form(plan_views, text_note_types, link_count, linked_shaft_count):
    stream = MemoryStream(Encoding.UTF8.GetBytes(XAML))
    window = Markup.XamlReader.Load(stream)

    search_box       = window.FindName('SearchBox')
    views_panel      = window.FindName('ViewsPanel')
    tt_combo         = window.FindName('TextTypeCombo')
    apply_btn        = window.FindName('ApplyBtn')
    cancel_btn       = window.FindName('CancelBtn')
    select_all_btn   = window.FindName('SelectAllBtn')
    clear_all_btn    = window.FindName('ClearAllBtn')
    include_link_cb  = window.FindName('IncludeLinkedCheckBox')

    if link_count > 0:
        include_link_cb.Content = (
            "Include shafts from linked models "
            "({} link(s), {} shaft(s))".format(link_count, linked_shaft_count)
        )
        include_link_cb.IsEnabled = True
    else:
        include_link_cb.Content    = "Include shafts from linked models (none found)"
        include_link_cb.IsChecked  = False
        include_link_cb.IsEnabled  = False

    view_checkboxes = []
    for v in plan_views:
        cb = CheckBox()
        cb.Content = v.Name
        view_checkboxes.append(cb)
        views_panel.Children.Add(cb)

    def on_search_changed(s, e):
        search_text = search_box.Text.lower()
        for cb in view_checkboxes:
            cb.Visibility = (Visibility.Visible
                             if search_text in cb.Content.lower()
                             else Visibility.Collapsed)

    search_box.TextChanged += on_search_changed

    def on_select_all(s, e):
        for cb in view_checkboxes:
            if cb.Visibility == Visibility.Visible:
                cb.IsChecked = True

    def on_clear_all(s, e):
        for cb in view_checkboxes:
            cb.IsChecked = False

    for tt in text_note_types:
        name = tt.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME).AsString()
        tt_combo.Items.Add(name)
    if tt_combo.Items.Count > 0:
        tt_combo.SelectedIndex = 0

    result = {'ok': False}

    def on_apply(s, e):
        selected = [plan_views[i] for i, cb in enumerate(view_checkboxes) if cb.IsChecked]
        if not selected:
            forms.alert("Please tick at least one plan view.")
            return
        result['ok']             = True
        result['views']          = selected
        result['text_type_id']   = text_note_types[tt_combo.SelectedIndex].Id
        result['include_linked'] = bool(include_link_cb.IsChecked)
        window.Close()

    apply_btn.Click      += on_apply
    cancel_btn.Click     += lambda s, e: window.Close()
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

    host_shafts     = [s for s in all_shafts if not s['is_linked']]
    linked_shafts   = [s for s in all_shafts if s['is_linked']]
    link_names      = sorted(set(s['link_name'] for s in linked_shafts))
    link_count      = len(link_names)

    if not plan_views:
        forms.alert("No floor plan views found in the document.",
                    title="Shaft Function Tag")
        return

    if not text_note_types:
        forms.alert("No text note types found in the document.",
                    title="Shaft Function Tag")
        return

    if not all_shafts:
        forms.alert(
            "No shaft openings found in the active document or in any "
            "loaded linked model.",
            title="Shaft Function Tag")
        return

    # ── Pre-flight: validate that the parameter exists on at least one shaft
    if not validate_shaft_function_param(all_shafts):
        forms.alert(
            'The parameter "{}" was not found on any Shaft Opening '
            '(host or linked) in this document.\n\n'
            'Please ensure the parameter exists as an Instance parameter on '
            'the Shaft Opening category before running this script.'.format(
                SHAFT_FUNCTION_PARAM),
            title="Parameter Not Found")
        return

    # ── Show dialog ──────────────────────────────────────────────────
    result = show_form(plan_views, text_note_types, link_count, len(linked_shafts))
    if not result.get('ok'):
        return

    selected_views  = result['views']
    text_type_id    = result['text_type_id']
    include_linked  = result['include_linked']

    shafts_to_use = all_shafts if include_linked else host_shafts

    # ── Process each view in its own transaction ─────────────────────
    output.print_md("## Shaft Function Tag — Results\n")

    if include_linked and link_names:
        output.print_md(
            "_Linked models included: {}_\n".format(", ".join(link_names)))
    elif linked_shafts:
        output.print_md("_Linked model shafts excluded (checkbox unticked)._\n")

    total_placed = 0
    error_views  = []

    for view in selected_views:
        t = Transaction(doc, "Shaft Function Tag — {}".format(view.Name))
        t.Start()
        try:
            placed, no_val, no_bbox = process_view(view, shafts_to_use, text_type_id)
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

    if include_linked and link_names:
        summary += "\n\nLinked models included:\n" + "\n".join(
            "  • " + n for n in link_names)

    if error_views:
        summary += "\n\nFailed views:\n" + "\n".join("  • " + n for n in error_views)

    forms.alert(summary, title="Shaft Function Tag")

main()
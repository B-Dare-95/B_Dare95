# -*- coding: utf-8 -*-

__title__   = "Pick Shaft-Open Above"
__doc__     = """
________________________________________________________________
Description:
Interactively pick Shaft Openings in a 2D Plan View.
After each pick:
  - The chosen Line Style is applied as a Graphical Override
    on the shaft's Symbolic Lines
  - A Text Note is placed below the shaft with your chosen text

How to Use:
1. Open a Floor Plan or Engineering Plan view
2. Run the script
3. Choose a Line Style and type the annotation text, click OK
4. Click shafts one by one — each is annotated immediately
5. Press Esc (or close) to finish
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
from System.Windows.Media import SolidColorBrush, Color
import System.Windows.Markup as Markup

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    BuiltInCategory, BuiltInParameter,
    GraphicsStyle, GraphicsStyleType,
    OverrideGraphicSettings, ElementId,
    TextNote, TextNoteOptions, HorizontalTextAlignment,
    TextNoteType, Transaction,
    ViewType, XYZ
)
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from Autodesk.Revit.Exceptions   import OperationCanceledException

from pyrevit import forms, script

# ─────────────────────────────────────────────────────────────────────
# Revit handles
# ─────────────────────────────────────────────────────────────────────
uidoc       = __revit__.ActiveUIDocument
doc         = __revit__.ActiveUIDocument.Document
active_view = doc.ActiveView

# ─────────────────────────────────────────────────────────────────────
# Constant — gap below bbox for the text note (Revit feet)
# ─────────────────────────────────────────────────────────────────────
TEXT_OFFSET_FT = 1.0


# ═════════════════════════════════════════════════════════════════════
# ACTIVE-VIEW GUARD
# ═════════════════════════════════════════════════════════════════════

ALLOWED_VIEW_TYPES = {ViewType.FloorPlan, ViewType.EngineeringPlan}

def check_active_view():
    """
    Returns True when the active view is a plan view.
    Alerts the user and returns False otherwise.
    """
    if active_view.ViewType not in ALLOWED_VIEW_TYPES:
        forms.alert(
            "This tool can only run in a Floor Plan or Engineering Plan view.\n\n"
            "Current view type: {}\n\n"
            "Please switch to a plan view and try again.".format(
                str(active_view.ViewType)),
            title="Wrong View Type")
        return False
    return True


# ═════════════════════════════════════════════════════════════════════
# DATA COLLECTION
# ═════════════════════════════════════════════════════════════════════

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


# ═════════════════════════════════════════════════════════════════════
# SELECTION FILTER — shafts only
# ═════════════════════════════════════════════════════════════════════

class ShaftSelectionFilter(ISelectionFilter):
    def AllowElement(self, element):
        return element.Category is not None and \
               element.Category.Id == ElementId(BuiltInCategory.OST_ShaftOpening)

    def AllowReference(self, reference, point):
        return False


# ═════════════════════════════════════════════════════════════════════
# GRAPHICAL OVERRIDE
# ═════════════════════════════════════════════════════════════════════

def build_override_settings(line_style_gs):
    """
    Build OverrideGraphicSettings from the chosen GraphicsStyle.
    Applies colour, weight and pattern to both projection and cut lines
    (projection lines are what you see as symbolic lines in plan views).
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
# TEXT NOTE PLACEMENT
# ═════════════════════════════════════════════════════════════════════

def get_text_position(shaft, view):
    """
    XYZ centred below the shaft bounding box, TEXT_OFFSET_FT beneath
    the minimum Y extent, at the view's level elevation.
    Returns None if no bounding box is available.
    """
    bbox = shaft.get_BoundingBox(view) or shaft.get_BoundingBox(None)
    if not bbox:
        return None
    cx   = (bbox.Min.X + bbox.Max.X) / 2.0
    cy   = bbox.Min.Y - TEXT_OFFSET_FT
    elev = view.GenLevel.Elevation if view.GenLevel else 0.0
    return XYZ(cx, cy, elev)


# ═════════════════════════════════════════════════════════════════════
# PROCESS A SINGLE PICKED SHAFT
# ═════════════════════════════════════════════════════════════════════

def annotate_shaft(shaft, view, ogs, annotation_text, text_type_id):
    """
    Apply override + text note to one shaft inside a single transaction.
    Returns (True, None) on success, (False, error_message) on failure.
    """
    t = Transaction(doc, "Shaft Text Note")
    t.Start()
    try:
        # 1. Apply graphic override on the shaft element
        view.SetElementOverrides(shaft.Id, ogs)

        # 2. Place text note below the shaft
        if text_type_id:
            pos = get_text_position(shaft, view)
            if pos:
                opts = TextNoteOptions(text_type_id)
                opts.HorizontalAlignment = HorizontalTextAlignment.Center
                TextNote.Create(doc, view.Id, pos, annotation_text, opts)

        t.Commit()
        return True, None

    except Exception as ex:
        try:
            t.RollBack()
        except Exception:
            pass
        return False, str(ex)


# ═════════════════════════════════════════════════════════════════════
# WPF SETTINGS DIALOG
# ═════════════════════════════════════════════════════════════════════

def hex_brush(hex_str):
    h = hex_str.lstrip('#')
    return SolidColorBrush(
        Color.FromRgb(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)))


XAML = """
<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Pick Shaft — Open Above"
    Height="400" Width="420"
    WindowStartupLocation="CenterScreen"
    ResizeMode="NoResize"
    Background="#1E1E2E"
    Foreground="#CDD6F4"
    FontFamily="Segoe UI"
    FontSize="12">

    <Window.Resources>
        <Style TargetType="Button">
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="Button">
                        <Border Background="{TemplateBinding Background}"
                                BorderBrush="{TemplateBinding BorderBrush}"
                                BorderThickness="{TemplateBinding BorderThickness}"
                                CornerRadius="6"
                                Padding="{TemplateBinding Padding}">
                            <ContentPresenter HorizontalAlignment="Center"
                                              VerticalAlignment="Center"/>
                        </Border>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>
    </Window.Resources>

    <Grid Margin="20,20,20,18">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>  <!-- 0  Header            -->
            <RowDefinition Height="Auto"/>  <!-- 1  Line style label  -->
            <RowDefinition Height="Auto"/>  <!-- 2  Line style combo  -->
            <RowDefinition Height="Auto"/>  <!-- 3  Text type label   -->
            <RowDefinition Height="Auto"/>  <!-- 4  Text type combo   -->
            <RowDefinition Height="Auto"/>  <!-- 5  Annot label       -->
            <RowDefinition Height="Auto"/>  <!-- 6  Annot textbox     -->
            <RowDefinition Height="*"/>     <!-- 7  Spacer            -->
            <RowDefinition Height="Auto"/>  <!-- 8  Buttons           -->
        </Grid.RowDefinitions>

        <!-- 0  Header -->
        <StackPanel Grid.Row="0" Margin="0,0,0,18">
            <TextBlock Text="PICK SHAFT — OPEN ABOVE"
                       FontSize="15" FontWeight="Bold"
                       Foreground="#F0A500"/>
            <TextBlock Text="Configure the override style and annotation text, then click OK to begin picking."
                       Foreground="#6C7086" FontSize="10.5"
                       TextWrapping="Wrap" Margin="0,4,0,0"/>
        </StackPanel>

        <!-- 1  Line Style label -->
        <TextBlock Grid.Row="1" Text="Override Line Style"
                   Foreground="#BAC2DE" FontWeight="SemiBold"
                   Margin="0,0,0,5"/>

        <!-- 2  Line Style combo -->
        <ComboBox Grid.Row="2" x:Name="LineStyleCombo"
                  Height="30" Margin="0,0,0,14"
                  Background="#313244" Foreground="#CDD6F4"
                  BorderBrush="#45475A">
            <ComboBox.ItemContainerStyle>
                <Style TargetType="ComboBoxItem">
                    <Setter Property="Foreground" Value="#CDD6F4"/>
                    <Setter Property="Background" Value="#313244"/>
                    <Style.Triggers>
                        <Trigger Property="IsHighlighted" Value="True">
                            <Setter Property="Background" Value="#45475A"/>
                        </Trigger>
                    </Style.Triggers>
                </Style>
            </ComboBox.ItemContainerStyle>
        </ComboBox>

        <!-- 3  Text Note Type label -->
        <TextBlock Grid.Row="3" Text="Text Note Type"
                   Foreground="#BAC2DE" FontWeight="SemiBold"
                   Margin="0,0,0,5"/>

        <!-- 4  Text Note Type combo -->
        <ComboBox Grid.Row="4" x:Name="TextTypeCombo"
                  Height="30" Margin="0,0,0,14"
                  Background="#313244" Foreground="#CDD6F4"
                  BorderBrush="#45475A">
            <ComboBox.ItemContainerStyle>
                <Style TargetType="ComboBoxItem">
                    <Setter Property="Foreground" Value="#CDD6F4"/>
                    <Setter Property="Background" Value="#313244"/>
                    <Style.Triggers>
                        <Trigger Property="IsHighlighted" Value="True">
                            <Setter Property="Background" Value="#45475A"/>
                        </Trigger>
                    </Style.Triggers>
                </Style>
            </ComboBox.ItemContainerStyle>
        </ComboBox>

        <!-- 5  Annotation label -->
        <TextBlock Grid.Row="5" Text="Annotation Text"
                   Foreground="#BAC2DE" FontWeight="SemiBold"
                   Margin="0,0,0,5"/>

        <!-- 6  Annotation textbox -->
        <TextBox Grid.Row="6" x:Name="AnnotationTextBox"
                 Height="32" Padding="8,6"
                 Background="#181825" Foreground="#CDD6F4"
                 BorderBrush="#45475A" CaretBrush="#F0A500"
                 Text="OPEN ABOVE"/>

        <!-- 8  Buttons -->
        <StackPanel Grid.Row="8" Orientation="Horizontal"
                    HorizontalAlignment="Right">
            <Button x:Name="CancelBtn" Content="Cancel"
                    Width="90" Height="32" Margin="0,0,10,0"
                    Background="#313244" Foreground="#CDD6F4"
                    BorderBrush="#45475A"/>
            <Button x:Name="OkBtn" Content="OK  →  Pick"
                    Width="110" Height="32"
                    Background="#F0A500" Foreground="#1E1E2E"
                    FontWeight="Bold" BorderBrush="#F0A500"/>
        </StackPanel>

    </Grid>
</Window>
"""


def show_settings_dialog(line_styles, text_note_types):
    """
    Show the configuration dialog.
    Returns:
      { 'ok': bool, 'line_style': GraphicsStyle,
        'text': str, 'text_type_id': ElementId }
    """
    stream = MemoryStream(Encoding.UTF8.GetBytes(XAML))
    window = Markup.XamlReader.Load(stream)

    ls_combo   = window.FindName('LineStyleCombo')
    tt_combo   = window.FindName('TextTypeCombo')
    text_box   = window.FindName('AnnotationTextBox')
    ok_btn     = window.FindName('OkBtn')
    cancel_btn = window.FindName('CancelBtn')

    # ── Populate line styles ─────────────────────────────────────────
    for ls in line_styles:
        ls_combo.Items.Add(ls.Name)
    if ls_combo.Items.Count > 0:
        ls_combo.SelectedIndex = 0

    # ── Populate text note types ─────────────────────────────────────
    for tt in text_note_types:
        name = tt.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME).AsString()
        tt_combo.Items.Add(name)
    if tt_combo.Items.Count > 0:
        tt_combo.SelectedIndex = 0

    result = {'ok': False}

    def on_ok(s, e):
        if ls_combo.SelectedIndex < 0:
            forms.alert("Please select a line style.",
                        title="No Line Style Selected")
            return
        if tt_combo.SelectedIndex < 0:
            forms.alert("Please select a text note type.",
                        title="No Text Note Type Selected")
            return
        result['ok']           = True
        result['line_style']   = line_styles[ls_combo.SelectedIndex]
        result['text']         = text_box.Text.strip() or "OPEN ABOVE"
        result['text_type_id'] = text_note_types[tt_combo.SelectedIndex].Id
        window.Close()

    def on_cancel(s, e):
        window.Close()

    ok_btn.Click     += on_ok
    cancel_btn.Click += on_cancel

    window.ShowDialog()
    return result


# ═════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════

def main():

    # ── 1. Enforce plan-view-only constraint ─────────────────────────
    if not check_active_view():
        return

    # ── 2. Collect resources ─────────────────────────────────────────
    line_styles     = get_line_styles()
    text_note_types = get_text_note_types()

    if not line_styles:
        forms.alert(
            "No custom line styles found.\n"
            "Create one via  Manage → Additional Settings → Line Styles.",
            title="Pick Shaft — Open Above")
        return

    if not text_note_types:
        forms.alert("No text note types found in the document.",
                    title="Pick Shaft — Open Above")
        return

    # ── 3. Show settings dialog ──────────────────────────────────────
    cfg = show_settings_dialog(line_styles, text_note_types)
    if not cfg.get('ok'):
        return

    chosen_style = cfg['line_style']
    annot_text   = cfg['text']
    text_type_id = cfg['text_type_id']
    ogs          = build_override_settings(chosen_style)
    sel_filter   = ShaftSelectionFilter()

    # ── 4. Interactive pick loop ─────────────────────────────────────
    count    = 0
    failures = []   # list of (shaft_id_int, error_message)

    while True:
        try:
            ref = uidoc.Selection.PickObject(
                ObjectType.Element,
                sel_filter,
                "Click a Shaft Opening  [Esc to finish]")

            shaft = doc.GetElement(ref.ElementId)

            # Re-check view type in case the user switched views somehow
            if doc.ActiveView.ViewType not in ALLOWED_VIEW_TYPES:
                forms.alert(
                    "The active view changed to a non-plan view.\n"
                    "The script will now exit.",
                    title="Wrong View Type")
                break

            success, err = annotate_shaft(
                shaft, active_view, ogs, annot_text, text_type_id)

            if success:
                count += 1
            else:
                failures.append((shaft.Id, err))

        except OperationCanceledException:
            break

        except Exception as ex:
            # Unexpected error outside the transaction — stop the loop
            forms.alert(
                "Unexpected error during picking:\n\n{}".format(str(ex)),
                title="Pick Shaft — Open Above")
            break

    # ── 5. Report failures only ──────────────────────────────────────
    if failures:
        lines = [
            "The following shaft(s) could not be annotated:\n"
        ]
        for shaft_id, err in failures:
            lines.append("  • ID {}:\n    {}".format(shaft_id, err))
        lines.append(
            "\n{} shaft(s) annotated successfully.".format(count))
        forms.alert(
            "\n".join(lines),
            title="Pick Shaft — Open Above  |  Errors")

main()
# -*- coding: utf-8 -*-

__title__   = "Pick Linked Shaft-Open Above"
__doc__     = """
________________________________________________________________
Description:
Interactively pick Shaft Openings from a Linked Model in a 2D
Plan View. After each pick:
  - The shaft boundary is redrawn as Detail Lines in the chosen
    Line Style directly in the host document's active view
  - A Text Note is placed below the shaft with your chosen text

How to Use:
1. Open a Floor Plan or Engineering Plan view
2. Run the script
3. Choose a Line Style and type the annotation text, click OK
4. Click linked shafts one by one — each is annotated immediately
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
    GraphicsStyleType,
    ElementId,
    Line, Arc,
    TextNote, TextNoteOptions, HorizontalTextAlignment,
    TextNoteType, Transaction,
    RevitLinkInstance,
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
# Constant — gap below shaft curves for the text note (Revit feet)
# ─────────────────────────────────────────────────────────────────────
TEXT_OFFSET_FT = 1.0


# ═════════════════════════════════════════════════════════════════════
# ACTIVE-VIEW GUARD
# ═════════════════════════════════════════════════════════════════════

ALLOWED_VIEW_TYPES = {ViewType.FloorPlan, ViewType.EngineeringPlan}


def check_active_view():
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
# SELECTION FILTER — linked shafts only
# ═════════════════════════════════════════════════════════════════════

class LinkedShaftSelectionFilter(ISelectionFilter):
    """
    AllowElement: receives the RevitLinkInstance — accept all links.
    AllowReference: resolves the actual linked element and checks that
                    it is a Shaft Opening.
    """

    def AllowElement(self, element):
        # When picking ObjectType.LinkedElement, element is the
        # RevitLinkInstance; we allow any link and refine in AllowReference.
        return isinstance(element, RevitLinkInstance)

    def AllowReference(self, reference, point):
        try:
            link_inst = doc.GetElement(reference.ElementId)
            if link_inst is None:
                return False
            link_doc = link_inst.GetLinkDocument()
            if link_doc is None:
                return False
            linked_elem = link_doc.GetElement(reference.LinkedElementId)
            if linked_elem is None or linked_elem.Category is None:
                return False
            return (linked_elem.Category.Id.IntegerValue ==
                    int(BuiltInCategory.OST_ShaftOpening))
        except Exception:
            return False


# ═════════════════════════════════════════════════════════════════════
# SHAFT BOUNDARY CURVES
# ═════════════════════════════════════════════════════════════════════

def get_shaft_boundary_curves(shaft):
    """
    Returns a list of Curve objects defining the shaft plan boundary.
    Tries shaft.BoundaryCurves first; falls back to a bounding-box
    rectangle if BoundaryCurves is empty or unavailable.
    """
    # Primary: BoundaryCurves property on Opening / ShaftOpening
    try:
        bc = shaft.BoundaryCurves
        if bc is not None and bc.Size > 0:
            return list(bc)
    except Exception:
        pass

    # Fallback: reconstruct a rectangle from the bounding box
    bbox = shaft.get_BoundingBox(None)
    if not bbox:
        return []

    mn, mx = bbox.Min, bbox.Max
    z      = mn.Z
    p1 = XYZ(mn.X, mn.Y, z)
    p2 = XYZ(mx.X, mn.Y, z)
    p3 = XYZ(mx.X, mx.Y, z)
    p4 = XYZ(mn.X, mx.Y, z)
    return [
        Line.CreateBound(p1, p2),
        Line.CreateBound(p2, p3),
        Line.CreateBound(p3, p4),
        Line.CreateBound(p4, p1),
    ]


def flatten_curve_to_z(curve, z):
    """
    Project a curve to a fixed Z elevation so it lies in the floor
    plan's horizontal sketch plane.
    Handles Line and Arc; all other types fall back to a straight
    Line between the two projected endpoints.
    """
    try:
        p0  = curve.GetEndPoint(0)
        p1  = curve.GetEndPoint(1)
        p0f = XYZ(p0.X, p0.Y, z)
        p1f = XYZ(p1.X, p1.Y, z)

        if isinstance(curve, Arc):
            # Sample the mid-parameter to reconstruct the arc
            t_mid  = (curve.GetEndParameter(0) + curve.GetEndParameter(1)) / 2.0
            mid    = curve.Evaluate(t_mid, False)
            midf   = XYZ(mid.X, mid.Y, z)
            try:
                return Arc.Create(p0f, p1f, midf)
            except Exception:
                pass  # degenerate arc — fall through to Line

        # Line or any unsupported type → straight segment
        # Guard against zero-length segments (can happen with
        # coincident points after flattening)
        if p0f.DistanceTo(p1f) < 1e-6:
            return None
        return Line.CreateBound(p0f, p1f)

    except Exception:
        return None


# ═════════════════════════════════════════════════════════════════════
# BOUNDS HELPER + TEXT NOTE POSITION
# ═════════════════════════════════════════════════════════════════════

def get_curve_bounds(curves):
    """
    Returns (min_x, max_x, min_y, max_y) for all curve endpoints,
    or None if the list is empty.
    Used by both the text position and the X-mark diagonal logic.
    """
    xs, ys = [], []
    for curve in curves:
        for pt in [curve.GetEndPoint(0), curve.GetEndPoint(1)]:
            xs.append(pt.X)
            ys.append(pt.Y)
    if not xs:
        return None
    return min(xs), max(xs), min(ys), max(ys)


def get_text_position_from_curves(curves, view_elev):
    """
    Centred horizontally on the shaft, TEXT_OFFSET_FT below the
    lowest Y endpoint found in the curve list.
    Returns None if curves is empty.
    """
    bounds = get_curve_bounds(curves)
    if bounds is None:
        return None
    min_x, max_x, min_y, max_y = bounds
    cx = (min_x + max_x) / 2.0
    cy = min_y - TEXT_OFFSET_FT
    return XYZ(cx, cy, view_elev)


# ═════════════════════════════════════════════════════════════════════
# ANNOTATE A SINGLE PICKED LINKED SHAFT
# ═════════════════════════════════════════════════════════════════════

def annotate_linked_shaft(ref, view, line_style_gs, annotation_text,
                          text_type_id, draw_x=False):
    """
    1. Resolve the linked document, shaft element, and link transform.
    2. Extract the shaft boundary curves.
    3. Transform + flatten each curve into the host view's plane.
    4. Draw Detail Lines with the chosen line style.
    5. Optionally draw two diagonal X lines connecting opposite corners.
    6. Place the Text Note below the shaft.

    Returns (True, None) on success, (False, error_message) on failure.
    All work is done inside a single transaction.
    """
    # ── Resolve link ─────────────────────────────────────────────────
    try:
        link_inst  = doc.GetElement(ref.ElementId)
        link_doc   = link_inst.GetLinkDocument()
        link_xform = link_inst.GetTotalTransform()
        shaft      = link_doc.GetElement(ref.LinkedElementId)
    except Exception as ex:
        return False, "Could not resolve linked element: {}".format(str(ex))

    # ── Get boundary curves from the linked shaft ────────────────────
    raw_curves = get_shaft_boundary_curves(shaft)
    if not raw_curves:
        return False, "No boundary curves found on shaft ID {}".format(
            ref.LinkedElementId.IntegerValue)

    # ── Transform → host coordinates, then flatten to view elevation ─
    view_elev    = view.GenLevel.Elevation if view.GenLevel else 0.0
    final_curves = []

    for raw in raw_curves:
        try:
            host_curve = raw.CreateTransformed(link_xform)
        except Exception:
            continue
        flat = flatten_curve_to_z(host_curve, view_elev)
        if flat is not None:
            final_curves.append(flat)

    if not final_curves:
        return False, "All curves were invalid after transformation."

    # ── Text note position (computed before the transaction) ─────────
    text_pos = get_text_position_from_curves(final_curves, view_elev)

    # ── Single transaction: detail lines + text note ─────────────────
    t = Transaction(doc, "Shaft Open Above (Linked)")
    t.Start()
    try:
        # Draw each boundary segment as a Detail Line
        for curve in final_curves:
            try:
                dc = doc.Create.NewDetailCurve(view, curve)
                try:
                    dc.LineStyle = line_style_gs
                    dc.Pinned = True
                except Exception:
                    dc.ChangeTypeId(line_style_gs.Id)
                    dc.Pinned = True
            except Exception:
                pass  # one bad segment must not abort the whole shaft

        # ── Optional X mark: two diagonals across the bounding box ───
        if draw_x:
            bounds = get_curve_bounds(final_curves)
            if bounds:
                min_x, max_x, min_y, max_y = bounds
                z   = view_elev
                # Corner points (matching the rectangle convention)
                # p1 = bottom-left, p2 = bottom-right
                # p3 = top-right,   p4 = top-left
                p1 = XYZ(min_x, min_y, z)
                p2 = XYZ(max_x, min_y, z)
                p3 = XYZ(max_x, max_y, z)
                p4 = XYZ(min_x, max_y, z)
                for diag in [Line.CreateBound(p1, p3),   # p1 → p3
                             Line.CreateBound(p2, p4)]:  # p2 → p4
                    try:
                        dc = doc.Create.NewDetailCurve(view, diag)
                        try:
                            dc.LineStyle = line_style_gs
                            dc.Pinned = True
                        except Exception:
                            dc.ChangeTypeId(line_style_gs.Id)
                            dc.Pinned = True
                    except Exception:
                        pass

        # Place text note
        if text_type_id and text_pos:
            opts = TextNoteOptions(text_type_id)
            opts.HorizontalAlignment = HorizontalTextAlignment.Center
            TextNote.Create(doc, view.Id, text_pos, annotation_text, opts)

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
    Title="Pick Linked Shaft — Open Above"
    Height="440" Width="420"
    WindowStartupLocation="CenterScreen"
    ResizeMode="NoResize"
    Background="#1E1E2E"
    Foreground="#CDD6F4"
    FontFamily="Segoe UI"
    FontSize="12">

    <Grid Margin="20,20,20,18">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>  <!-- 0  Header            -->
            <RowDefinition Height="Auto"/>  <!-- 1  Line style label  -->
            <RowDefinition Height="Auto"/>  <!-- 2  Line style combo  -->
            <RowDefinition Height="Auto"/>  <!-- 3  Text type label   -->
            <RowDefinition Height="Auto"/>  <!-- 4  Text type combo   -->
            <RowDefinition Height="Auto"/>  <!-- 5  Annot label       -->
            <RowDefinition Height="Auto"/>  <!-- 6  Annot textbox     -->
            <RowDefinition Height="Auto"/>  <!-- 7  X-mark checkbox   -->
            <RowDefinition Height="*"/>     <!-- 8  Spacer            -->
            <RowDefinition Height="Auto"/>  <!-- 9  Buttons           -->
        </Grid.RowDefinitions>

        <!-- 0  Header -->
        <StackPanel Grid.Row="0" Margin="0,0,0,18">
            <TextBlock Text="PICK LINKED SHAFT — OPEN ABOVE"
                       FontSize="14" FontWeight="Bold"
                       Foreground="#F0A500" TextWrapping="Wrap"/>
            <TextBlock Text="Configure the detail line style and annotation text, then click OK to begin picking."
                       Foreground="#6C7086" FontSize="10.5"
                       TextWrapping="Wrap" Margin="0,4,0,0"/>
        </StackPanel>

        <!-- 1  Line Style label -->
        <TextBlock Grid.Row="1" Text="Detail Line Style"
                   Foreground="#BAC2DE" FontWeight="SemiBold"
                   Margin="0,0,0,5"/>

        <!-- 2  Line Style combo -->
        <ComboBox Grid.Row="2" x:Name="LineStyleCombo"
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

        <!-- 3  Text Note Type label -->
        <TextBlock Grid.Row="3" Text="Text Note Type"
                   Foreground="#BAC2DE" FontWeight="SemiBold"
                   Margin="0,0,0,5"/>

        <!-- 4  Text Note Type combo -->
        <ComboBox Grid.Row="4" x:Name="TextTypeCombo"
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

        <!-- 7  X-mark checkbox -->
        <CheckBox Grid.Row="7" x:Name="DrawXCheckBox"
                  Margin="0,14,0,0"
                  Foreground="#CDD6F4"
                  IsChecked="True">
            <TextBlock Text="Draw X mark (diagonals across shaft)"
                       Foreground="#CDD6F4" VerticalAlignment="Center"/>
        </CheckBox>

        <!-- 9  Buttons -->
        <StackPanel Grid.Row="9" Orientation="Horizontal"
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
    stream = MemoryStream(Encoding.UTF8.GetBytes(XAML))
    window = Markup.XamlReader.Load(stream)

    ls_combo    = window.FindName('LineStyleCombo')
    tt_combo    = window.FindName('TextTypeCombo')
    text_box    = window.FindName('AnnotationTextBox')
    draw_x_cb   = window.FindName('DrawXCheckBox')
    ok_btn      = window.FindName('OkBtn')
    cancel_btn  = window.FindName('CancelBtn')

    for ls in line_styles:
        ls_combo.Items.Add(ls.Name)
    if ls_combo.Items.Count > 0:
        ls_combo.SelectedIndex = 0

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
        result['draw_x']       = draw_x_cb.IsChecked == True
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

    # ── 1. Plan-view-only guard ──────────────────────────────────────
    if not check_active_view():
        return

    # ── 2. Pre-flight: verify at least one link is loaded ────────────
    loaded_links = [
        inst for inst in
        FilteredElementCollector(doc)
        .OfClass(RevitLinkInstance)
        .ToElements()
        if inst.GetLinkDocument() is not None
    ]
    if not loaded_links:
        forms.alert(
            "No loaded Revit links found in this document.\n"
            "Please load at least one linked model that contains "
            "Shaft Openings and try again.",
            title="Pick Linked Shaft — Open Above")
        return

    # ── 3. Collect resources ─────────────────────────────────────────
    line_styles     = get_line_styles()
    text_note_types = get_text_note_types()

    if not line_styles:
        forms.alert(
            "No custom line styles found.\n"
            "Create one via  Manage → Additional Settings → Line Styles.",
            title="Pick Linked Shaft — Open Above")
        return

    if not text_note_types:
        forms.alert("No text note types found in the document.",
                    title="Pick Linked Shaft — Open Above")
        return

    # ── 4. Settings dialog ───────────────────────────────────────────
    cfg = show_settings_dialog(line_styles, text_note_types)
    if not cfg.get('ok'):
        return

    chosen_style   = cfg['line_style']
    annot_text     = cfg['text']
    text_type_id   = cfg['text_type_id']
    draw_x         = cfg['draw_x']
    sel_filter     = LinkedShaftSelectionFilter()

    # ── 5. Interactive pick loop ─────────────────────────────────────
    count    = 0
    failures = []   # list of (linked_elem_id_int, error_message)

    while True:
        try:
            ref = uidoc.Selection.PickObject(
                ObjectType.LinkedElement,
                sel_filter,
                "Click a Linked Shaft Opening  [Esc to finish]")

            # Re-check view type in case the user switched views
            if doc.ActiveView.ViewType not in ALLOWED_VIEW_TYPES:
                forms.alert(
                    "The active view changed to a non-plan view.\n"
                    "The script will now exit.",
                    title="Wrong View Type")
                break

            success, err = annotate_linked_shaft(
                ref, active_view, chosen_style, annot_text,
                text_type_id, draw_x=draw_x)

            if success:
                count += 1
            else:
                failures.append((ref.LinkedElementId.IntegerValue, err))

        except OperationCanceledException:
            break

        except Exception as ex:
            forms.alert(
                "Unexpected error during picking:\n\n{}".format(str(ex)),
                title="Pick Linked Shaft — Open Above")
            break

    # ── 6. Report failures only ──────────────────────────────────────
    if failures:
        lines = ["The following shaft(s) could not be annotated:\n"]
        for elem_id, err in failures:
            lines.append("  • Linked ID {}:\n    {}".format(elem_id, err))
        lines.append("\n{} shaft(s) annotated successfully.".format(count))
        forms.alert(
            "\n".join(lines),
            title="Pick Linked Shaft — Open Above  |  Errors")


main()
# -*- coding: utf-8 -*-
__title__   = "What's This ID?"
__author__  = "Mohamed Bedair"
__version__ = "2.0.0"
__doc__ = """
Version = 2.0.0
Date    = 05.10.2026

Description:
Type an Element ID and the tool looks for it in the host model AND in every
loaded Revit link. The element is reported (category, family, type, level,
phase, workset, mark, comments, bounding box) and selected in the Revit UI -
linked elements stay selected the same way as in Pre-Filter Selection (Links).

Element IDs are only unique inside one document, so the same number can exist
in the host and in several links (or in several instances of the same link).
When that happens a picker opens so you can choose which one you meant.

How-to:
-> Run the script
-> Enter the Element ID
-> If the ID exists in more than one place, pick the one you want
   (double-click or Enter also confirms)
-> The element is selected, the view zooms to it, and the report opens

Notes:
- Linked selection needs Revit 2023+ (Selection.SetReferences).
- Unloaded links are skipped.
- Zoom on a linked element only happens when its link instance is visible in
  the active view. The bounding box of a linked element is reported in HOST
  coordinates (link transform applied), so it matches host elements.

Last update:
- [05.10.2026] - 2.0.0 Linked elements: search all loaded links, picker for
                 duplicate IDs, selection through SetReferences
- 1.0.0 Host-only version

Author: Mohamed Bedair
"""

# ─── IMPORTS ──────────────────────────────────────────────────────────────────
import System
import clr
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from System import EventHandler
from System.Collections.Generic import List

from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import TaskDialog

from pyrevit import forms, script

import System.Windows
import System.Windows.Controls as Controls
from System.Windows import RoutedEventHandler
from System.Windows.Input import MouseButtonEventHandler, KeyEventHandler, Key
from System.Windows.Markup import XamlReader
from System.Windows.Threading import Dispatcher, DispatcherFrame

# ─── REVIT VARIABLES ──────────────────────────────────────────────────────────
uidoc = __revit__.ActiveUIDocument
doc   = uidoc.Document

TITLE = "What's This ID?"
DASH  = u"\u2014"
DOT   = u"\u00b7"


# ─── THEME COLOURS (IBM Carbon) ───────────────────────────────────────────────
BG      = "#161616"
CARD    = "#262626"
SURFACE = "#393939"
MUTED   = "#525252"
TEXT    = "#F4F4F4"
SUBTEXT = "#A8A8A8"
ACCENT  = "#F1C21B"
# ──────────────────────────────────────────────────────────────────────────────

XAML_TEMPLATE = """
<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="What's This ID?"
    Width="480" MaxHeight="640"
    SizeToContent="Height"
    WindowStartupLocation="CenterScreen"
    ResizeMode="NoResize"
    Background="{BG}"
    Foreground="{TEXT}"
    FontFamily="Segoe UI"
    FontSize="13">

    <Window.Resources>

        <!-- ScrollBar thumb -->
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

        <!-- Minimal ScrollBar -->
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

        <!-- One row per hit: radio behaviour, accent fill when checked -->
        <Style x:Key="HitRow" TargetType="RadioButton">
            <Setter Property="Foreground" Value="{TEXT}"/>
            <Setter Property="Background" Value="{SURFACE}"/>
            <Setter Property="Margin" Value="0,0,0,6"/>
            <Setter Property="Cursor" Value="Hand"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="RadioButton">
                        <Border x:Name="Bd"
                                Background="{TemplateBinding Background}"
                                BorderBrush="{MUTED}"
                                BorderThickness="1"
                                CornerRadius="6"
                                Padding="10,8">
                            <ContentPresenter/>
                        </Border>
                        <ControlTemplate.Triggers>
                            <Trigger Property="IsMouseOver" Value="True">
                                <Setter TargetName="Bd" Property="BorderBrush" Value="{ACCENT}"/>
                            </Trigger>
                        </ControlTemplate.Triggers>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
            <Style.Triggers>
                <Trigger Property="IsChecked" Value="True">
                    <Setter Property="Background" Value="{ACCENT}"/>
                    <Setter Property="Foreground" Value="{BG}"/>
                </Trigger>
            </Style.Triggers>
        </Style>

        <!-- Confirm button -->
        <Style x:Key="AccentButton" TargetType="Button">
            <Setter Property="Background" Value="{ACCENT}"/>
            <Setter Property="Foreground" Value="{BG}"/>
            <Setter Property="FontWeight" Value="SemiBold"/>
            <Setter Property="Height" Value="36"/>
            <Setter Property="Cursor" Value="Hand"/>
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

        <!-- Cancel button -->
        <Style x:Key="GhostButton" TargetType="Button">
            <Setter Property="Background" Value="{SURFACE}"/>
            <Setter Property="Foreground" Value="{TEXT}"/>
            <Setter Property="Height" Value="36"/>
            <Setter Property="Cursor" Value="Hand"/>
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
                                <Setter TargetName="Bd" Property="Background" Value="{MUTED}"/>
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
            <TextBlock x:Name="HeaderText"
                       FontSize="15" FontWeight="SemiBold"
                       Foreground="{TEXT}"
                       Margin="0,0,0,2"/>
            <TextBlock x:Name="SubHeader"
                       Text="IDs are only unique per document - pick the one you meant."
                       FontSize="11"
                       Foreground="{SUBTEXT}"
                       TextWrapping="Wrap"
                       Margin="0,0,0,10"/>

            <!-- Search box with placeholder -->
            <Border Background="{SURFACE}" CornerRadius="6" Margin="0,0,0,10"
                    BorderBrush="{MUTED}" BorderThickness="1">
                <Grid>
                    <TextBlock x:Name="SearchHint"
                               Text="Filter by link, category, family or type..."
                               Foreground="{SUBTEXT}"
                               FontSize="12"
                               Margin="10,6"
                               IsHitTestVisible="False"/>
                    <TextBox x:Name="SearchBox"
                             Background="Transparent"
                             BorderThickness="0"
                             Foreground="{TEXT}"
                             CaretBrush="{ACCENT}"
                             Padding="8,6"
                             FontSize="12"/>
                </Grid>
            </Border>

            <!-- Hit list -->
            <Border Background="{CARD}" CornerRadius="8"
                    Padding="10,10,10,4" Margin="0,0,0,14">
                <ScrollViewer MaxHeight="360"
                              VerticalScrollBarVisibility="Auto"
                              HorizontalScrollBarVisibility="Disabled"
                              Padding="0,0,4,0">
                    <StackPanel x:Name="HitPanel"/>
                </ScrollViewer>
            </Border>

            <!-- Buttons -->
            <Grid>
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="10"/>
                    <ColumnDefinition Width="2*"/>
                </Grid.ColumnDefinitions>
                <Button x:Name="CancelBtn" Grid.Column="0"
                        Content="Cancel"
                        Style="{StaticResource GhostButton}"/>
                <Button x:Name="ConfirmBtn" Grid.Column="2"
                        Content="Inspect &amp; Select"
                        Style="{StaticResource AccentButton}"
                        IsEnabled="False"/>
            </Grid>

        </StackPanel>
    </Border>
</Window>
""".replace("{BG}", BG).replace("{CARD}", CARD).replace("{SURFACE}", SURFACE) \
   .replace("{MUTED}", MUTED).replace("{TEXT}", TEXT).replace("{SUBTEXT}", SUBTEXT) \
   .replace("{ACCENT}", ACCENT)


# ─── HELPERS ──────────────────────────────────────────────────────────────────

def safe(fn):
    """Run fn(), return its string or a dash on any failure / empty value."""
    try:
        result = fn()
        if result is None or result == "":
            return DASH
        return str(result)
    except Exception:
        return DASH


def eid_value(eid):
    """ElementId integer, Revit 2024-2027 safe."""
    try:
        return eid.Value
    except AttributeError:
        return eid.IntegerValue


def make_element_id(number):
    """ElementId from a Python int. Int64 constructor first (only one left in 2026+)."""
    try:
        return ElementId(System.Int64(number))
    except Exception:
        return ElementId(number)


def show(message):
    TaskDialog.Show(TITLE, message)


class Hit(object):
    """One place the ID resolved to: the host doc, or one link instance."""

    def __init__(self, elem, src_doc, link_inst=None):
        self.elem      = elem
        self.doc       = src_doc          # document the element lives in
        self.link      = link_inst        # RevitLinkInstance in the HOST doc, or None
        self.transform = link_inst.GetTotalTransform() if link_inst is not None else None

    @property
    def is_linked(self):
        return self.link is not None

    def source_label(self):
        if self.link is None:
            return u"Host model {0} {1}".format(DASH, safe(lambda: doc.Title))
        return u"Link {0} {1}".format(DASH, safe(lambda: self.link.Name))

    def detail_label(self):
        family, type_name = family_and_type(self.elem, self.doc)
        category = safe(lambda: self.elem.Category.Name)
        return u"{0}  {1}  {2} : {3}".format(category, DOT, family, type_name)


def family_and_type(elem, src_doc):
    el_type = None
    try:
        el_type = src_doc.GetElement(elem.GetTypeId())
    except Exception:
        pass
    if el_type is None:
        return DASH, DASH
    type_name   = safe(lambda: el_type.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM).AsString())
    family_name = safe(lambda: el_type.get_Parameter(BuiltInParameter.SYMBOL_FAMILY_NAME_PARAM).AsString())
    return family_name, type_name


# ─── FIND ─────────────────────────────────────────────────────────────────────

def find_hits(number):
    """Look the ID up in the host doc and in every loaded link instance.

    Returns (hits, unloaded_link_count). Each link INSTANCE is its own hit, because
    two instances of the same link are two different places in the host model.
    """
    eid  = make_element_id(number)
    hits = []
    unloaded = 0

    host_elem = doc.GetElement(eid)
    if host_elem is not None:
        hits.append(Hit(host_elem, doc))

    for li in FilteredElementCollector(doc).OfClass(RevitLinkInstance):
        ldoc = li.GetLinkDocument()
        if ldoc is None:
            unloaded += 1
            continue
        linked_elem = ldoc.GetElement(eid)
        if linked_elem is not None:
            hits.append(Hit(linked_elem, ldoc, li))

    return hits, unloaded


def visible_link_ids():
    """Ids of link instances visible in the active view (empty for sheets/schedules)."""
    try:
        col = FilteredElementCollector(doc, doc.ActiveView.Id).OfClass(RevitLinkInstance)
        return set(eid_value(li.Id) for li in col)
    except Exception:
        return set()


# ─── PICKER (only when the ID exists in more than one place) ──────────────────

def pick_hit(hits, number):
    """Themed WPF picker. Returns the chosen Hit or None."""

    window = XamlReader.Parse(XAML_TEMPLATE)

    header_text = window.FindName("HeaderText")
    search_box  = window.FindName("SearchBox")
    search_hint = window.FindName("SearchHint")
    hit_panel   = window.FindName("HitPanel")
    confirm_btn = window.FindName("ConfirmBtn")
    cancel_btn  = window.FindName("CancelBtn")
    row_style   = window.FindResource("HitRow")

    header_text.Text = "ID {0} exists in {1} places".format(number, len(hits))

    result_holder = [None]   # mutable container for IronPython 2.7 closure
    rows = []                # (RadioButton, hit, search_text)

    def confirm():
        for rb, hit, _ in rows:
            if rb.IsChecked:
                result_holder[0] = hit
                break
        if result_holder[0] is not None:
            window.Close()

    def on_checked(sender, e):
        confirm_btn.IsEnabled = True

    def on_double_click(sender, e):
        sender.IsChecked = True
        confirm()

    for hit in hits:
        source = hit.source_label()
        detail = hit.detail_label()

        t1 = Controls.TextBlock()
        t1.Text         = source
        t1.FontWeight   = System.Windows.FontWeights.SemiBold
        t1.TextTrimming = System.Windows.TextTrimming.CharacterEllipsis

        t2 = Controls.TextBlock()
        t2.Text         = detail
        t2.FontSize     = 11
        t2.Opacity      = 0.8
        t2.Margin       = System.Windows.Thickness(0, 2, 0, 0)
        t2.TextTrimming = System.Windows.TextTrimming.CharacterEllipsis

        content = Controls.StackPanel()
        content.Children.Add(t1)
        content.Children.Add(t2)

        rb = Controls.RadioButton()
        rb.Style     = row_style
        rb.GroupName = "hits"
        rb.Content   = content
        rb.ToolTip   = u"{0}\n{1}".format(source, detail)
        rb.Checked          += RoutedEventHandler(on_checked)
        rb.MouseDoubleClick += MouseButtonEventHandler(on_double_click)

        hit_panel.Children.Add(rb)
        rows.append((rb, hit, (source + u" " + detail).lower()))

    def on_search(sender, e):
        query = search_box.Text.strip().lower()
        search_hint.Visibility = (
            System.Windows.Visibility.Collapsed if search_box.Text
            else System.Windows.Visibility.Visible)
        for rb, _, text in rows:
            rb.Visibility = (
                System.Windows.Visibility.Visible if query in text
                else System.Windows.Visibility.Collapsed)

    def on_confirm(sender, e):
        confirm()

    def on_cancel(sender, e):
        window.Close()

    def on_key(sender, e):
        if e.Key == Key.Escape:
            window.Close()
        elif e.Key == Key.Enter:
            confirm()

    frame = DispatcherFrame()

    def on_closed(sender, args):
        frame.Continue = False

    search_box.TextChanged += Controls.TextChangedEventHandler(on_search)
    confirm_btn.Click      += RoutedEventHandler(on_confirm)
    cancel_btn.Click       += RoutedEventHandler(on_cancel)
    window.KeyDown         += KeyEventHandler(on_key)
    window.Closed          += EventHandler(on_closed)

    if rows:
        rows[0][0].IsChecked = True

    window.Show()
    search_box.Focus()
    Dispatcher.PushFrame(frame)

    return result_holder[0]


# ─── REPORT ───────────────────────────────────────────────────────────────────

def host_bounding_box(hit):
    """Model bounding box in HOST coordinates as (min, max), or None."""
    bb = hit.elem.get_BoundingBox(None)
    if bb is None:
        return None

    t = bb.Transform
    if hit.transform is not None:
        t = hit.transform.Multiply(t)

    xs, ys, zs = [], [], []
    for x in (bb.Min.X, bb.Max.X):
        for y in (bb.Min.Y, bb.Max.Y):
            for z in (bb.Min.Z, bb.Max.Z):
                p = t.OfPoint(XYZ(x, y, z))
                xs.append(p.X)
                ys.append(p.Y)
                zs.append(p.Z)

    return XYZ(min(xs), min(ys), min(zs)), XYZ(max(xs), max(ys), max(zs))


def build_report(hit, number, box):
    elem    = hit.elem
    src_doc = hit.doc

    category = safe(lambda: elem.Category.Name)
    family_name, type_name = family_and_type(elem, src_doc)

    # Level (looked up in the element's own document)
    level_name = DASH
    try:
        level_id = elem.LevelId
        if level_id is not None and level_id != ElementId.InvalidElementId:
            level_elem = src_doc.GetElement(level_id)
            if level_elem is not None:
                level_name = safe(lambda: level_elem.Name)
    except Exception:
        pass

    # Phase Created
    phase_param = elem.get_Parameter(BuiltInParameter.PHASE_CREATED)
    phase = safe(lambda: src_doc.GetElement(phase_param.AsElementId()).Name) if phase_param else DASH

    # Workset (of the element inside its own document)
    if src_doc.IsWorkshared:
        workset_id = elem.WorksetId
        workset = safe(lambda: src_doc.GetWorksetTable().GetWorkset(workset_id).Name)
    else:
        workset = "Not workshared"

    # Mark & Comments
    mark_param    = elem.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
    comment_param = elem.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    mark     = safe(lambda: mark_param.AsString())    if mark_param    else DASH
    comments = safe(lambda: comment_param.AsString()) if comment_param else DASH

    # Bounding box (host coordinates)
    if box is not None:
        bmin, bmax = box
        loc = "Min({:.2f}, {:.2f}, {:.2f})  Max({:.2f}, {:.2f}, {:.2f})".format(
            bmin.X, bmin.Y, bmin.Z, bmax.X, bmax.Y, bmax.Z)
        if hit.is_linked:
            loc += "  [host coords]"
    else:
        loc = DASH

    # Source
    if hit.is_linked:
        source = u"Link {0} {1}".format(DASH, safe(lambda: src_doc.Title))
        link_line = u"Link Inst.  : {0}  (ID {1})\n".format(
            safe(lambda: hit.link.Name), eid_value(hit.link.Id))
    else:
        source = "Host model"
        link_line = u""

    return (
        u"ID          : {}\n"
        u"Source      : {}\n"
        u"{}"
        u"Category    : {}\n"
        u"Family      : {}\n"
        u"Type        : {}\n"
        u"Level       : {}\n"
        u"Phase       : {}\n"
        u"Workset     : {}\n"
        u"Mark        : {}\n"
        u"Comments    : {}\n"
        u"Bounding Box: {}"
    ).format(
        number, source, link_line, category, family_name, type_name,
        level_name, phase, workset, mark, comments, loc)


# ─── SELECT & ZOOM ────────────────────────────────────────────────────────────

def zoom_to_box(box):
    """Zoom the active view's UIView to a host-coordinate box."""
    bmin, bmax = box
    pad = max(1.0, 0.25 * max(bmax.X - bmin.X, bmax.Y - bmin.Y, bmax.Z - bmin.Z))
    lo = XYZ(bmin.X - pad, bmin.Y - pad, bmin.Z - pad)
    hi = XYZ(bmax.X + pad, bmax.Y + pad, bmax.Z + pad)

    view_id = doc.ActiveView.Id
    for ui_view in uidoc.GetOpenUIViews():
        if ui_view.ViewId == view_id:
            ui_view.ZoomAndCenterRectangle(lo, hi)
            return True
    return False


def select_hit(hit, box):
    """Select the element. Returns (selected, zoomed, note)."""

    # Host element - same route as v1
    if not hit.is_linked:
        ids = List[ElementId]()
        ids.Add(hit.elem.Id)
        try:
            uidoc.Selection.SetElementIds(ids)
        except Exception:
            return False, False, None
        try:
            uidoc.ShowElements(ids)
            return True, True, None
        except Exception:
            return True, False, None

    # Linked element - whole-element link reference, as in Pre-Filter (Links)
    if not hasattr(uidoc.Selection, "SetReferences"):
        return False, False, "Selecting linked elements needs Revit 2023 or newer."

    try:
        link_ref = Reference(hit.elem).CreateLinkReference(hit.link)
        refs = List[Reference]()
        refs.Add(link_ref)
        uidoc.Selection.SetReferences(refs)
    except Exception:
        return False, False, None

    if eid_value(hit.link.Id) not in visible_link_ids():
        return True, False, "The link instance is not visible in the active view."
    if box is None:
        return True, False, None

    try:
        return True, zoom_to_box(box), None
    except Exception:
        return True, False, None


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    raw = forms.ask_for_string(
        default='',
        prompt='Enter Element ID to inspect (host or linked):',
        title=TITLE)

    if raw is None:            # dialog cancelled
        return
    if not raw.strip():
        show("No ID entered.")
        return

    try:
        number = int(raw.strip())
    except ValueError:
        show(u"Invalid ID {0} please enter a whole number.".format(DASH))
        return
    if number <= 0:
        show(u"Invalid ID {0} please enter a positive whole number.".format(DASH))
        return

    hits, unloaded = find_hits(number)

    if not hits:
        msg = "No element with ID {0} in the host model or any loaded link.".format(number)
        if unloaded:
            msg += "\n\n{0} unloaded link{1} could not be searched.".format(
                unloaded, "" if unloaded == 1 else "s")
        show(msg)
        return

    hit = hits[0] if len(hits) == 1 else pick_hit(hits, number)
    if hit is None:
        return

    box  = host_bounding_box(hit)
    info = build_report(hit, number, box)

    selected, zoomed, note = select_hit(hit, box)

    if selected and zoomed:
        footer = u"\n\n\u2714 Element selected and view zoomed."
    elif selected:
        footer = u"\n\n\u2714 Element selected (view not zoomed)."
    else:
        footer = u"\n\n\u2718 Element could not be selected (view-only, non-graphical or an element type)."
    if note:
        footer += u"\n" + note

    show(info + footer)


main()
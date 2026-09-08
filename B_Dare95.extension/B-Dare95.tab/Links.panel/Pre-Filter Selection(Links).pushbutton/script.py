# -*- coding: utf-8 -*-
__title__ = "Pre-Filter Selection (Links)"
__author__ = "Mohamed Bedair"
__version__ = '1.0.0'
__doc__ = """
Version = 1.0.0
Date    = 08.09.2026

Description:
Linked-model counterpart of "Pre-Filter Selection".
Restricts picking to chosen categories inside ANY loaded Revit link visible in the
active view - no link has to be chosen beforehand. The resulting linked elements stay
selected in the Revit UI. SHIFT click negates (pick everything EXCEPT the chosen
categories).

How-to:
-> Run the script
-> Pick the categories you want (the list is built from what actually exists in the
   loaded links, with element counts)
-> Click elements in any link; only the chosen categories pre-highlight
-> Press Finish on the options bar - the picked linked elements stay selected

Notes:
- Requires Revit 2023+ (Selection.SetReferences).
- Rectangle selection is NOT possible for linked elements - PickElementsByRectangle
  ignores links entirely. Click-picking is the only route.

Last update:
- [08.09.2026] - 1.0.0 RELEASE

Author: Mohamed Bedair,inspired by work of Stephane Rospars Dupin
"""

# IMPORTS
import System
import clr
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from System import EventHandler
from System.Collections.Generic import List

from Autodesk.Revit.DB import *
from Autodesk.Revit.UI.Selection import *
import Autodesk.Revit.Exceptions as RvtEx

from pyrevit import script, forms
from pyrevit import EXEC_PARAMS

import System.Windows
import System.Windows.Controls as Controls
from System.Windows import RoutedEventHandler
from System.Windows.Markup import XamlReader
from System.Windows.Threading import Dispatcher, DispatcherFrame

# Get active Revit document and selection objects
uidoc     = __revit__.ActiveUIDocument
doc       = uidoc.Document
app       = __revit__.Application
rvt_year  = int(app.VersionNumber)
curview   = doc.ActiveView
selection = uidoc.Selection

INVERT_MODE = EXEC_PARAMS.config_mode


# ─── THEME COLOURS ────────────────────────────────────────────────────────────
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
    Title="Choose Categories"
    Width="340" MinHeight="120" MaxHeight="640"
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

        <!-- CheckBox -->
        <Style TargetType="CheckBox">
            <Setter Property="Foreground" Value="{TEXT}"/>
            <Setter Property="Background" Value="{SURFACE}"/>
            <Setter Property="Margin" Value="0,2,0,2"/>
            <Setter Property="Padding" Value="6,0,0,0"/>
            <Setter Property="VerticalContentAlignment" Value="Center"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="CheckBox">
                        <Grid>
                            <Grid.ColumnDefinitions>
                                <ColumnDefinition Width="18"/>
                                <ColumnDefinition Width="*"/>
                            </Grid.ColumnDefinitions>
                            <Border x:Name="CheckBorder"
                                    Grid.Column="0"
                                    Width="14" Height="14"
                                    CornerRadius="3"
                                    Background="{SURFACE}"
                                    BorderBrush="{MUTED}"
                                    BorderThickness="1.5"
                                    VerticalAlignment="Center"/>
                            <TextBlock x:Name="CheckMark"
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
                                <Setter TargetName="CheckBorder" Property="Background" Value="{ACCENT}"/>
                                <Setter TargetName="CheckBorder" Property="BorderBrush" Value="{ACCENT}"/>
                                <Setter TargetName="CheckMark" Property="Visibility" Value="Visible"/>
                            </Trigger>
                            <Trigger Property="IsMouseOver" Value="True">
                                <Setter TargetName="CheckBorder" Property="BorderBrush" Value="{ACCENT}"/>
                            </Trigger>
                        </ControlTemplate.Triggers>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>

        <!-- Confirm button -->
        <Style x:Key="AccentButton" TargetType="Button">
            <Setter Property="Background" Value="{ACCENT}"/>
            <Setter Property="Foreground" Value="{BG}"/>
            <Setter Property="FontWeight" Value="SemiBold"/>
            <Setter Property="FontSize" Value="13"/>
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

        <!-- Select-All / Clear toggle button -->
        <Style x:Key="GhostButton" TargetType="Button">
            <Setter Property="Background" Value="Transparent"/>
            <Setter Property="Foreground" Value="{SUBTEXT}"/>
            <Setter Property="FontSize" Value="11"/>
            <Setter Property="BorderThickness" Value="0"/>
            <Setter Property="Cursor" Value="Hand"/>
            <Setter Property="Padding" Value="0"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="Button">
                        <TextBlock x:Name="Tb"
                                   Text="{TemplateBinding Content}"
                                   Foreground="{TemplateBinding Foreground}"
                                   FontSize="{TemplateBinding FontSize}"/>
                        <ControlTemplate.Triggers>
                            <Trigger Property="IsMouseOver" Value="True">
                                <Setter TargetName="Tb" Property="Foreground" Value="{ACCENT}"/>
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
                       Text="Choose Categories"
                       FontSize="15" FontWeight="SemiBold"
                       Foreground="{TEXT}"
                       Margin="0,0,0,2"/>
            <TextBlock x:Name="SubHeader"
                       Text=""
                       FontSize="11"
                       Foreground="{SUBTEXT}"
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

            <!-- Select-all / Clear row -->
            <DockPanel Margin="0,0,0,8" LastChildFill="False">
                <Button x:Name="SelectAllBtn" Content="Select All"
                        Style="{StaticResource GhostButton}"
                        DockPanel.Dock="Left" Margin="0,0,12,0"/>
                <Button x:Name="ClearBtn" Content="Clear"
                        Style="{StaticResource GhostButton}"
                        DockPanel.Dock="Left"/>
                <TextBlock x:Name="CountLabel"
                           Foreground="{SUBTEXT}" FontSize="11"
                           VerticalAlignment="Center"
                           DockPanel.Dock="Right"/>
            </DockPanel>

            <!-- Category list -->
            <Border Background="{CARD}" CornerRadius="8"
                    Padding="10,8" Margin="0,0,0,14">
                <ScrollViewer MaxHeight="380"
                              VerticalScrollBarVisibility="Auto"
                              HorizontalScrollBarVisibility="Disabled"
                              Padding="0,0,4,0">
                    <StackPanel x:Name="CategoryPanel"/>
                </ScrollViewer>
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

def eid_value(eid):
    """ElementId integer, Revit 2024-2027 safe."""
    try:
        return eid.Value
    except AttributeError:
        return eid.IntegerValue


def get_link_instances():
    """RevitLinkInstances visible in the active view that have a loaded document."""
    try:
        col = FilteredElementCollector(doc, curview.Id).OfClass(RevitLinkInstance).ToElements()
    except Exception:
        col = FilteredElementCollector(doc).OfClass(RevitLinkInstance).ToElements()

    return [li for li in col if li.GetLinkDocument() is not None]


def scan_link_categories(link_insts):
    """Model categories that actually contain elements across every loaded link.

    Returns {category_name: element_count}. One quick collector per category per
    unique link document - no element instantiation, so this stays fast on big links.
    """
    counts = {}
    scanned = set()

    for li in link_insts:
        ldoc = li.GetLinkDocument()
        key = ldoc.PathName
        if key in scanned:
            continue
        scanned.add(key)

        for cat in ldoc.Settings.Categories:
            if cat.CategoryType != CategoryType.Model:
                continue
            try:
                n = FilteredElementCollector(ldoc)\
                        .OfCategoryId(cat.Id)\
                        .WhereElementIsNotElementType()\
                        .GetElementCount()
            except Exception:
                continue
            if n > 0:
                counts[cat.Name] = counts.get(cat.Name, 0) + n

    return counts


def build_link_references(picked_refs, link_map):
    """Rebuild every picked reference as a whole-element host-context link reference.

    Returns (List[Reference], {link_title: count}, skipped_count).
    """
    refs = List[Reference]()
    per_link = {}
    skipped = 0

    for ref in picked_refs:
        li = link_map.get(eid_value(ref.ElementId))
        if li is None:
            skipped += 1
            continue

        ldoc = li.GetLinkDocument()
        if ldoc is None:
            skipped += 1
            continue

        linked_elem = ldoc.GetElement(ref.LinkedElementId)
        if linked_elem is None:
            skipped += 1
            continue

        try:
            link_ref = Reference(linked_elem).CreateLinkReference(li)
        except Exception:
            link_ref = ref  # fall back to the raw picked reference

        refs.Add(link_ref)
        title = ldoc.Title
        per_link[title] = per_link.get(title, 0) + 1

    return refs, per_link, skipped


# ─── SELECTION FILTER ─────────────────────────────────────────────────────────

class LinkedCategoryFilter(ISelectionFilter):
    """Allows linked elements of the chosen categories, in ANY loaded link.

    AllowElement gates which link instances can be hovered; AllowReference does the
    real category test against the element inside the link document. Results are
    cached because Revit calls AllowReference on every mouse move.
    """

    def __init__(self, allowed_names, invert, link_map):
        self.allowed  = set(allowed_names)
        self.invert   = invert
        self.link_map = link_map
        self._cache   = {}

    def _match(self, cat_name):
        if cat_name is None:
            return False
        hit = cat_name in self.allowed
        if self.invert:
            return not hit
        return hit

    def AllowElement(self, elem):
        try:
            if isinstance(elem, RevitLinkInstance):
                return eid_value(elem.Id) in self.link_map
            # Defensive: some builds hand the linked element itself to AllowElement
            cat = elem.Category
            return self._match(cat.Name if cat is not None else None)
        except Exception:
            return False

    def AllowReference(self, reference, position):
        try:
            if reference.LinkedElementId == ElementId.InvalidElementId:
                return False

            link_key = eid_value(reference.ElementId)
            li = self.link_map.get(link_key)
            if li is None:
                return False

            cache_key = (link_key, eid_value(reference.LinkedElementId))
            if cache_key in self._cache:
                return self._cache[cache_key]

            ldoc = li.GetLinkDocument()
            if ldoc is None:
                self._cache[cache_key] = False
                return False

            linked_elem = ldoc.GetElement(reference.LinkedElementId)
            cat = linked_elem.Category if linked_elem is not None else None
            ok = self._match(cat.Name if cat is not None else None)

            self._cache[cache_key] = ok
            return ok
        except Exception:
            return False


# ─── SELECTION DIALOG ─────────────────────────────────────────────────────────

def show_category_picker(cat_counts, invert, link_count):
    """Themed WPF category picker. Returns list of chosen category names or None."""

    window = XamlReader.Parse(XAML_TEMPLATE)

    header_text    = window.FindName("HeaderText")
    sub_header     = window.FindName("SubHeader")
    search_box     = window.FindName("SearchBox")
    cat_panel      = window.FindName("CategoryPanel")
    confirm_btn    = window.FindName("ConfirmBtn")
    select_all_btn = window.FindName("SelectAllBtn")
    clear_btn      = window.FindName("ClearBtn")
    count_label    = window.FindName("CountLabel")

    if invert:
        window.Title       = "Exclude Categories"
        header_text.Text   = "Exclude Categories"
        confirm_btn.Content = "Select Everything Else"
    else:
        window.Title       = "Choose Categories"
        header_text.Text   = "Choose Categories"
        confirm_btn.Content = "Make A Selection"

    sub_header.Text = "{0} loaded link{1} in this view".format(
        link_count, "" if link_count == 1 else "s")

    result_holder = [None]   # mutable container for IronPython 2.7 closure

    # Build a CheckBox for every category found in the links
    checkboxes = []
    for name in sorted(cat_counts.keys()):
        cb = Controls.CheckBox()
        cb.Content = "{0}   ({1:,})".format(name, cat_counts[name])
        cb.Tag     = name
        cat_panel.Children.Add(cb)
        checkboxes.append(cb)

    def update_count():
        n = sum(1 for cb in checkboxes if cb.IsChecked)
        count_label.Text = "{0} selected".format(n)
        confirm_btn.IsEnabled = n > 0

    def update_filter(sender, e):
        query = search_box.Text.strip().lower()
        for cb in checkboxes:
            cb.Visibility = (
                System.Windows.Visibility.Visible
                if query in cb.Tag.lower()
                else System.Windows.Visibility.Collapsed
            )

    def on_checked(sender, e):
        update_count()

    def on_select_all(sender, e):
        for cb in checkboxes:
            if cb.Visibility == System.Windows.Visibility.Visible:
                cb.IsChecked = True
        update_count()

    def on_clear(sender, e):
        for cb in checkboxes:
            cb.IsChecked = False
        update_count()

    def on_confirm(sender, e):
        result_holder[0] = [cb.Tag for cb in checkboxes if cb.IsChecked]
        window.Close()

    # Wire events
    frame = DispatcherFrame()

    def on_closed(sender, args):
        frame.Continue = False

    search_box.TextChanged += Controls.TextChangedEventHandler(update_filter)
    select_all_btn.Click   += RoutedEventHandler(on_select_all)
    clear_btn.Click        += RoutedEventHandler(on_clear)
    confirm_btn.Click      += RoutedEventHandler(on_confirm)
    window.Closed          += EventHandler(on_closed)

    for cb in checkboxes:
        cb.Checked   += RoutedEventHandler(on_checked)
        cb.Unchecked += RoutedEventHandler(on_checked)

    update_count()
    window.Show()
    Dispatcher.PushFrame(frame)

    return result_holder[0]


# ─── MAIN ─────────────────────────────────────────────────────────────────────

if rvt_year < 2023:
    forms.alert(
        "Keeping linked elements selected needs Selection.SetReferences(), "
        "which was added in the Revit 2023 API.\n\n"
        "This Revit is {0}.".format(rvt_year),
        title=__title__, exitscript=True)

link_instances = get_link_instances()

if not link_instances:
    forms.alert(
        "No loaded Revit links are visible in the active view.",
        title=__title__, exitscript=True)

LINK_MAP = {}
for li in link_instances:
    LINK_MAP[eid_value(li.Id)] = li

cat_counts = scan_link_categories(link_instances)

if not cat_counts:
    forms.alert(
        "The loaded links contain no model elements to pick.",
        title=__title__, exitscript=True)

names_chosen = show_category_picker(cat_counts, INVERT_MODE, len(link_instances))

if not names_chosen:
    script.exit()

sel_filter = LinkedCategoryFilter(names_chosen, INVERT_MODE, LINK_MAP)

if INVERT_MODE:
    prompt = "Pick linked elements OUTSIDE the excluded categories, then press Finish"
else:
    prompt = "Pick linked elements of the chosen categories, then press Finish"

try:
    picked_refs = uidoc.Selection.PickObjects(ObjectType.LinkedElement, sel_filter, prompt)
except RvtEx.OperationCanceledException:
    script.exit()

if picked_refs is None or picked_refs.Count == 0:
    script.exit()

final_refs, per_link, skipped = build_link_references(picked_refs, LINK_MAP)

if final_refs.Count == 0:
    forms.alert(
        "None of the picked references could be resolved back to linked elements.",
        title=__title__, exitscript=True)

uidoc.Selection.SetReferences(final_refs)
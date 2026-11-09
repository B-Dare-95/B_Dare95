# -*- coding: utf-8 -*-
__author__ = "Mohamed Bedair"
__doc__ = """__________________________________________________
Description:

Makes your selection pick only the categories you choose, model or annotation, so you can grab just what you need from a busy view.
Switch to Linked models to pick elements inside the loaded links instead: only the categories you chose can be picked, in every loaded link in the view, and the picked linked elements stay selected.
Check Everything except the checked categories, above the list, to do the opposite: select everything but those categories.
__________________________________________________
How-to:

-> Click on the button
-> Choose This model or Linked models at the top
-> Check the categories you want (use search or Select All); annotation categories in the view are listed under the model ones
-> Check Everything except the checked categories, above the list, to leave them out instead
-> Click the button at the bottom
-> This model: drag a box in the view; only those categories are selected
-> Linked models: click elements in any link, then press Finish on the Options Bar
__________________________________________________
Author: Mohamed Bedair
Linked models mode inspired by the work of Stephane Rospars Dupin"""

import clr
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from System import EventHandler
from System.Collections.Generic import List

from Autodesk.Revit.DB import (CategoryType, ElementId, FilteredElementCollector, Reference,
                               RevitLinkInstance)
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
import Autodesk.Revit.Exceptions as RvtEx

from pyrevit import forms, script

import System.Windows.Controls as Controls
from System.Windows.Controls import ToolTipService
from System.Windows import FontWeights, RoutedEventHandler, Thickness, Visibility
from System.Windows.Input import Cursors, Mouse
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Media import ColorConverter, SolidColorBrush
from System.Windows.Markup import XamlReader
from System.Windows.Threading import Dispatcher, DispatcherFrame

TOOL_NAME = "Pre-Filter Selection"
uidoc = __revit__.ActiveUIDocument  # noqa: F821
doc = uidoc.Document
selection = uidoc.Selection
curview = doc.ActiveView
rvt_year = int(__revit__.Application.VersionNumber)  # noqa: F821
cfg = script.get_config()


# --- THEME COLOURS -----------------------------------------------------------
BG = "#161616"
CARD = "#262626"
SURFACE = "#393939"
MUTED = "#525252"
TEXT = "#F4F4F4"
SUBTEXT = "#A8A8A8"
ACCENT = "#F1C21B"

XAML_TEMPLATE = """
<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Choose Categories"
    Width="340" MinHeight="120" MaxHeight="680"
    SizeToContent="Height"
    WindowStartupLocation="CenterScreen"
    ResizeMode="NoResize"
    Background="{BG}"
    Foreground="{TEXT}"
    FontFamily="Segoe UI"
    FontSize="13">

    <Window.Resources>

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
                            <Border x:Name="CheckBorder" Grid.Column="0" Width="14" Height="14"
                                    CornerRadius="3" Background="{SURFACE}" BorderBrush="{MUTED}"
                                    BorderThickness="1.5" VerticalAlignment="Center"/>
                            <TextBlock x:Name="CheckMark" Grid.Column="0" Text="&#x2714;" FontSize="10"
                                       Foreground="{BG}" HorizontalAlignment="Center"
                                       VerticalAlignment="Center" Visibility="Collapsed"/>
                            <ContentPresenter Grid.Column="1" Margin="8,0,0,0" VerticalAlignment="Center"/>
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

        <!-- This model / Linked models switch -->
        <Style x:Key="Seg" TargetType="ToggleButton">
            <Setter Property="Background" Value="Transparent"/>
            <Setter Property="Foreground" Value="{SUBTEXT}"/>
            <Setter Property="FontSize" Value="12"/>
            <Setter Property="Height" Value="30"/>
            <Setter Property="Cursor" Value="Hand"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="ToggleButton">
                        <Border x:Name="Bd" Background="{TemplateBinding Background}" CornerRadius="6">
                            <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
                        </Border>
                        <ControlTemplate.Triggers>
                            <Trigger Property="IsMouseOver" Value="True">
                                <Setter Property="Foreground" Value="{TEXT}"/>
                            </Trigger>
                            <Trigger Property="IsChecked" Value="True">
                                <Setter TargetName="Bd" Property="Background" Value="{ACCENT}"/>
                                <Setter Property="Foreground" Value="{BG}"/>
                                <Setter Property="FontWeight" Value="SemiBold"/>
                            </Trigger>
                            <Trigger Property="IsEnabled" Value="False">
                                <Setter Property="Opacity" Value="0.4"/>
                            </Trigger>
                        </ControlTemplate.Triggers>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>

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
                        <Border x:Name="Bd" Background="{TemplateBinding Background}" CornerRadius="6">
                            <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
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
                        <TextBlock x:Name="Tb" Text="{TemplateBinding Content}"
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

            <TextBlock x:Name="HeaderText" Text="Choose Categories" FontSize="15" FontWeight="SemiBold"
                       Foreground="{TEXT}" Margin="0,0,0,10"/>

            <!-- Mode switch -->
            <Border Background="{CARD}" CornerRadius="8" Padding="3" Margin="0,0,0,6">
                <UniformGrid Columns="2">
                    <ToggleButton x:Name="ModeActive" Content="This model" Style="{StaticResource Seg}"/>
                    <ToggleButton x:Name="ModeLinked" Content="Linked models" Style="{StaticResource Seg}"/>
                </UniformGrid>
            </Border>
            <TextBlock x:Name="SubHeader" FontSize="11" Foreground="{SUBTEXT}" TextWrapping="Wrap"
                       Margin="2,0,0,10"/>

            <Border Background="{SURFACE}" CornerRadius="6" Margin="0,0,0,10"
                    BorderBrush="{MUTED}" BorderThickness="1">
                <Grid>
                    <TextBox x:Name="SearchBox" Background="Transparent" BorderThickness="0"
                             Foreground="{TEXT}" CaretBrush="{ACCENT}" Padding="8,6" FontSize="12"/>
                    <TextBlock x:Name="SearchHint" Text="Search categories..." Foreground="#6F6F6F"
                               FontSize="12" Margin="10,0,0,0" VerticalAlignment="Center"
                               IsHitTestVisible="False"/>
                </Grid>
            </Border>

            <CheckBox x:Name="ChkExcept" Content="Everything except the checked categories"
                      FontSize="12" Margin="0,0,0,8"
                      ToolTip="Select everything in the box (or everything you click) except the checked categories"/>

            <DockPanel Margin="0,0,0,8" LastChildFill="False">
                <Button x:Name="SelectAllBtn" Content="Select All" Style="{StaticResource GhostButton}"
                        DockPanel.Dock="Left" Margin="0,0,12,0"/>
                <Button x:Name="ClearBtn" Content="Clear" Style="{StaticResource GhostButton}"
                        DockPanel.Dock="Left"/>
                <TextBlock x:Name="CountLabel" Foreground="{SUBTEXT}" FontSize="11"
                           VerticalAlignment="Center" DockPanel.Dock="Right"/>
            </DockPanel>

            <Border Background="{CARD}" CornerRadius="8" Padding="10,8" Margin="0,0,0,14">
                <Grid>
                    <ScrollViewer MaxHeight="380" VerticalScrollBarVisibility="Auto"
                                  HorizontalScrollBarVisibility="Disabled" Padding="0,0,4,0">
                        <StackPanel x:Name="CategoryPanel"/>
                    </ScrollViewer>
                    <TextBlock x:Name="EmptyText" Foreground="{SUBTEXT}" FontSize="12" TextWrapping="Wrap"
                               Margin="2,6" Visibility="Collapsed"/>
                </Grid>
            </Border>

            <Button x:Name="ConfirmBtn" Content="Make A Selection"
                    Style="{StaticResource AccentButton}" IsEnabled="False"/>

        </StackPanel>
    </Border>
</Window>
""".replace("{BG}", BG).replace("{CARD}", CARD).replace("{SURFACE}", SURFACE) \
   .replace("{MUTED}", MUTED).replace("{TEXT}", TEXT).replace("{SUBTEXT}", SUBTEXT) \
   .replace("{ACCENT}", ACCENT)


# --- HELPERS -----------------------------------------------------------------
def eid_value(eid):
    """ElementId integer, Revit 2024-2027 safe."""
    try:
        return int(eid.Value)
    except AttributeError:
        return int(eid.IntegerValue)


def get_all_category_names():
    """Every model category name of the active document."""
    return sorted(cat.Name for cat in doc.Settings.Categories if cat.CategoryType == CategoryType.Model)


def get_view_annotation_counts():
    """{annotation category name: element count} of what is in the active view.
    Only these are listed: Revit has hundreds of annotation categories."""
    counts = {}
    try:
        elems = FilteredElementCollector(doc, curview.Id).WhereElementIsNotElementType()
    except Exception:
        return counts
    for el in elems:
        cat = el.Category
        if cat is None or cat.CategoryType != CategoryType.Annotation:
            continue
        counts[cat.Name] = counts.get(cat.Name, 0) + 1
    return counts


def get_link_instances():
    """RevitLinkInstances visible in the active view that have a loaded document."""
    try:
        col = FilteredElementCollector(doc, curview.Id).OfClass(RevitLinkInstance).ToElements()
    except Exception:
        col = FilteredElementCollector(doc).OfClass(RevitLinkInstance).ToElements()
    return [li for li in col if li.GetLinkDocument() is not None]


def scan_link_categories(link_insts):
    """{category name: element count} of the model categories that actually hold elements
    across every loaded link. One quick count per category per unique link document."""
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
                n = FilteredElementCollector(ldoc).OfCategoryId(cat.Id) \
                    .WhereElementIsNotElementType().GetElementCount()
            except Exception:
                continue
            if n > 0:
                counts[cat.Name] = counts.get(cat.Name, 0) + n
    return counts


def linked_unavailable_reason(link_insts):
    if rvt_year < 2023:
        return u"Linked models needs Revit 2023 or newer (this is Revit {0}).".format(rvt_year)
    if not link_insts:
        return u"No loaded Revit links are visible in this view."
    return None


# --- SELECTION FILTERS -------------------------------------------------------
class CategoryFilter(ISelectionFilter):
    """This model: only elements of the chosen categories."""

    def __init__(self, allowed_categories):
        self.allowed = set(allowed_categories)

    def AllowElement(self, elem):
        return elem.Category is not None and elem.Category.Name in self.allowed

    def AllowReference(self, reference, position):
        return False


class LinkedCategoryFilter(ISelectionFilter):
    """Linked models: linked elements of the chosen categories, in any loaded link.
    AllowElement gates which link instances can be hovered; AllowReference tests the
    element inside the link. Results are cached: Revit calls it on every mouse move."""

    def __init__(self, allowed_names, invert, link_map):
        self.allowed = set(allowed_names)
        self.invert = invert
        self.link_map = link_map
        self._cache = {}

    def _match(self, cat_name):
        if cat_name is None:
            return False
        hit = cat_name in self.allowed
        return (not hit) if self.invert else hit

    def AllowElement(self, elem):
        try:
            if isinstance(elem, RevitLinkInstance):
                return eid_value(elem.Id) in self.link_map
            cat = elem.Category        # some builds hand over the linked element itself
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
            linked_elem = ldoc.GetElement(reference.LinkedElementId) if ldoc is not None else None
            cat = linked_elem.Category if linked_elem is not None else None
            ok = self._match(cat.Name if cat is not None else None)
            self._cache[cache_key] = ok
            return ok
        except Exception:
            return False


# --- WINDOW ------------------------------------------------------------------
def show_category_picker(link_insts):
    """Returns {'names': [...], 'linked': bool} or None when closed."""
    window = XamlReader.Parse(XAML_TEMPLATE)
    f = window.FindName
    header_text, sub_header = f("HeaderText"), f("SubHeader")
    mode_active, mode_linked = f("ModeActive"), f("ModeLinked")
    search_box, search_hint = f("SearchBox"), f("SearchHint")
    cat_panel, empty_text = f("CategoryPanel"), f("EmptyText")
    confirm_btn, count_label = f("ConfirmBtn"), f("CountLabel")

    chk_except = f("ChkExcept")

    reason = linked_unavailable_reason(link_insts)
    if reason:
        mode_linked.IsEnabled = False
        mode_linked.ToolTip = reason
        ToolTipService.SetShowOnDisabled(mode_linked, True)

    state = {"linked": False, "exclude": False}
    try:
        state["linked"] = float(cfg.get_option("linked_mode", 0.0)) > 0.5 and reason is None
        state["exclude"] = float(cfg.get_option("exclude_mode", 0.0)) > 0.5
    except Exception:
        pass
    cache = {"active": None, "linked": None}
    checkboxes = []
    groups = []        # [(header TextBlock, [checkboxes])]
    result = [None]

    def categories(linked):
        """[(group title or None, [(name, count or None)])] for the mode, built once."""
        if linked:
            if cache["linked"] is None:
                Mouse.OverrideCursor = Cursors.Wait
                try:
                    counts = scan_link_categories(link_insts)
                finally:
                    Mouse.OverrideCursor = None
                items = sorted(counts.items(), key=lambda kv: kv[0].lower())
                cache["linked"] = [(None, items)] if items else []
            return cache["linked"]
        if cache["active"] is None:
            annotation = sorted(get_view_annotation_counts().items(), key=lambda kv: kv[0].lower())
            cache["active"] = [(u"MODEL CATEGORIES", [(n, None) for n in get_all_category_names()])]
            if annotation:
                cache["active"].append((u"ANNOTATION CATEGORIES IN THIS VIEW", annotation))
        return cache["active"]

    def update_count(*args):
        n = sum(1 for cb in checkboxes if cb.IsChecked)
        count_label.Text = u"{0} selected".format(n)
        confirm_btn.IsEnabled = n > 0

    def apply_search(*args):
        query = search_box.Text.strip().lower()
        search_hint.Opacity = 0.0 if search_box.Text else 1.0
        for cb in checkboxes:
            cb.Visibility = Visibility.Visible if query in cb.Tag.lower() else Visibility.Collapsed
        for header, members in groups:
            shown = any(cb.Visibility == Visibility.Visible for cb in members)
            header.Visibility = Visibility.Visible if shown else Visibility.Collapsed

    def update_texts():
        linked, exclude = state["linked"], state["exclude"]
        mode_active.IsChecked = not linked
        mode_linked.IsChecked = linked
        chk_except.IsChecked = exclude
        title = u"Exclude Categories" if exclude else u"Choose Categories"
        window.Title = title
        header_text.Text = title
        n = len(link_insts)
        links_text = u"{0} loaded link{1} in this view".format(n, u"" if n == 1 else u"s")
        if linked:
            sub_header.Text = links_text + (
                u". Click linked elements outside the checked categories, then press Finish."
                if exclude else u". Click linked elements, then press Finish on the Options Bar.")
            confirm_btn.Content = u"Pick Everything Else" if exclude else u"Pick Linked Elements"
        else:
            sub_header.Text = (u"Drag a box in the view: everything except the checked categories is selected."
                               if exclude else
                               u"Drag a box in the view: only the checked categories are selected.")
            confirm_btn.Content = u"Select Everything Else" if exclude else u"Make A Selection"

    def rebuild():
        """Fill the list for the current mode. Check marks carry over by category name."""
        ticked = set(cb.Tag for cb in checkboxes if cb.IsChecked)
        cat_panel.Children.Clear()
        del checkboxes[:]
        del groups[:]
        sections = categories(state["linked"])
        for title, items in sections:
            members = []
            if title:
                header = Controls.TextBlock()
                header.Text = title
                header.FontSize = 10
                header.FontWeight = FontWeights.SemiBold
                header.Foreground = SolidColorBrush(ColorConverter.ConvertFromString(ACCENT))
                header.Margin = Thickness(0, 8 if groups else 0, 0, 4)
                cat_panel.Children.Add(header)
                groups.append((header, members))
            for name, count in items:
                cb = Controls.CheckBox()
                cb.Content = name if count is None else u"{0}   ({1:,})".format(name, count)
                cb.Tag = name
                cb.IsChecked = name in ticked
                cb.Checked += RoutedEventHandler(update_count)
                cb.Unchecked += RoutedEventHandler(update_count)
                cat_panel.Children.Add(cb)
                checkboxes.append(cb)
                members.append(cb)
        if sections:
            empty_text.Visibility = Visibility.Collapsed
        else:
            empty_text.Text = u"The loaded links contain no model elements to pick."
            empty_text.Visibility = Visibility.Visible
        update_texts()
        apply_search()
        update_count()

    def set_mode(linked):
        def handler(sender, args):
            if state["linked"] != linked:
                state["linked"] = linked
                rebuild()
            else:
                update_texts()          # keep the clicked button checked
        return handler

    def on_except(sender, args):
        state["exclude"] = bool(chk_except.IsChecked)
        update_texts()

    def on_select_all(sender, args):
        for cb in checkboxes:
            if cb.Visibility == Visibility.Visible:
                cb.IsChecked = True
        update_count()

    def on_clear(sender, args):
        for cb in checkboxes:
            cb.IsChecked = False
        update_count()

    def on_confirm(sender, args):
        result[0] = {"names": [cb.Tag for cb in checkboxes if cb.IsChecked], "linked": state["linked"],
                     "exclude": state["exclude"]}
        window.Close()

    mode_active.Click += RoutedEventHandler(set_mode(False))
    mode_linked.Click += RoutedEventHandler(set_mode(True))
    chk_except.Click += RoutedEventHandler(on_except)
    search_box.TextChanged += Controls.TextChangedEventHandler(apply_search)
    f("SelectAllBtn").Click += RoutedEventHandler(on_select_all)
    f("ClearBtn").Click += RoutedEventHandler(on_clear)
    confirm_btn.Click += RoutedEventHandler(on_confirm)
    rebuild()

    frame = DispatcherFrame()

    def on_closed(sender, args):
        frame.Continue = False

    window.Closed += EventHandler(on_closed)
    try:
        WindowInteropHelper(window).Owner = __revit__.MainWindowHandle  # noqa: F821
    except Exception:
        pass
    window.Show()
    Dispatcher.PushFrame(frame)
    return result[0]


# --- SELECTING ---------------------------------------------------------------
def select_in_model(names, exclude):
    """Box selection in this model, limited to (or excluding) the chosen categories."""
    try:
        if exclude:
            picked = selection.PickElementsByRectangle(u"Select Elements")
            ids = [el.Id for el in picked if el.Category is not None and el.Category.Name not in names]
        else:
            picked = selection.PickElementsByRectangle(CategoryFilter(names), u"Select Elements")
            ids = [el.Id for el in picked]
    except RvtEx.OperationCanceledException:
        return
    selection.SetElementIds(List[ElementId](ids))


def link_reference(ref, link_map):
    """The picked reference rebuilt as a whole-element link reference, or None."""
    li = link_map.get(eid_value(ref.ElementId))
    ldoc = li.GetLinkDocument() if li is not None else None
    linked_elem = ldoc.GetElement(ref.LinkedElementId) if ldoc is not None else None
    if linked_elem is None:
        return None
    try:
        return Reference(linked_elem).CreateLinkReference(li)
    except Exception:
        return ref


def select_in_links(names, link_insts, exclude):
    """Click-pick linked elements of the chosen categories; they stay selected."""
    link_map = dict((eid_value(li.Id), li) for li in link_insts)
    prompt = (u"Pick linked elements OUTSIDE the excluded categories, then press Finish"
              if exclude else u"Pick linked elements of the chosen categories, then press Finish")
    try:
        picked = selection.PickObjects(ObjectType.LinkedElement,
                                       LinkedCategoryFilter(names, exclude, link_map), prompt)
    except RvtEx.OperationCanceledException:
        return
    if picked is None or picked.Count == 0:
        return
    refs = List[Reference]()
    for ref in picked:
        r = link_reference(ref, link_map)
        if r is not None:
            refs.Add(r)
    if refs.Count == 0:
        forms.alert(u"None of the picked elements could be found in their links again.", title=TOOL_NAME)
        return
    selection.SetReferences(refs)


# --- MAIN --------------------------------------------------------------------
links = get_link_instances()
choice = show_category_picker(links)
if not choice or not choice["names"]:
    script.exit()

cfg.set_option("linked_mode", 1.0 if choice["linked"] else 0.0)
cfg.set_option("exclude_mode", 1.0 if choice["exclude"] else 0.0)
script.save_config()

if choice["linked"]:
    select_in_links(choice["names"], links, choice["exclude"])
else:
    select_in_model(choice["names"], choice["exclude"])

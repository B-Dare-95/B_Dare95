# -*- coding: utf-8 -*-
__title__     = "Bulk Copy from Link"
__author__    = "Mohamed Bedair"
__version__   = 'Version = 2.2'
__doc__       = """Version = 2.2
Date    = 22.06.2026
_____________________________________________________________________
Description:

Copies one element per distinct Type, from one or more selected
Model Categories, out of a chosen Linked Model, into the active model
in the same place (pinned).
_____________________________________________________________________
How-to:

-> Run the script
-> Pick a Linked Model from the list (use the search bar to filter)
-> Pick one or more Categories from the list (use the search bar to filter)
   (only Model categories that actually exist in that link are shown)
-> Click Copy
-> One element per distinct Type under the selected Categories will
   be copied into the active model, in place, and pinned.
_____________________________________________________________________
Precautions:
- Curtain Panels masquerading as Doors (door panels placed in a
  curtain grid) are skipped when copying the Doors category, since
  they fail to copy via CopyElements.
- Any hosted element (door, window, etc.) automatically brings its
  Host element along, even if the host's category wasn't selected.
- The category list only shows Model Categories (Annotation,
  Internal, and Analytical Model categories are excluded).
_____________________________________________________________________
Last update:
- [22.06.2026] - 2.2 RELEASE - Skip curtain-panel-as-door elements,
                                auto-include hosts of hosted elements,
                                restrict category list to Model Categories
- [22.06.2026] - 2.1 RELEASE - Added live search/filter bar to both the
                                link picker and category picker
- [22.06.2026] - 2.0 RELEASE - Link picker + multi-category picker +
                                one-per-type copy logic
- [21.12.2023] - 1.0 RELEASE
_____________________________________________________________________
Author: Mohamed Bedair"""

# IMPORTS ---------------------------------------------------------------
import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')

from System.Collections.Generic import List
from System.Windows import Window, Application
from System.Windows.Markup import XamlReader
from System.IO import StringReader
from System.Windows.Threading import Dispatcher, DispatcherFrame

from Autodesk.Revit.DB import (
    FilteredElementCollector, RevitLinkInstance, ElementId, Transaction,
    ElementTransformUtils, Transform, XYZ, CopyPasteOptions, CategoryType,
    FamilyInstance, Wall, WallKind, BuiltInCategory
)
from Autodesk.Revit.UI import TaskDialog
from pyrevit import script

# VARIABLES ---------------------------------------------------------------
doc   = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

# THEME -------------------------------------------------------------------
THEME = {
    "bg":      "#1E1E2E",
    "card":    "#2A2A3C",
    "surface": "#313244",
    "muted":   "#45475A",
    "text":    "#CDD6F4",
    "subtext": "#A6ADC8",
    "accent":  "#F0A500",
}


# ---------------------------------------------------------------------
# MODELESS WINDOW HELPER (Dispatcher.PushFrame pattern)
# ---------------------------------------------------------------------
def show_modeless(window):
    """Show a WPF window modelessly while keeping Revit responsive,
    and block this script until the window is closed."""
    frame = DispatcherFrame()

    def on_closed(sender, args):
        frame.Continue = False

    window.Closed += on_closed
    window.Show()
    Dispatcher.PushFrame(frame)


# ---------------------------------------------------------------------
# XAML BUILDERS
# ---------------------------------------------------------------------
def build_link_picker_xaml():
    return u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Bulk Copy from Link - Select Linked Model"
        Height="500" Width="480"
        WindowStartupLocation="CenterScreen"
        Background="{theme_bg}">
    <Window.Resources>
        <Style x:Key="RoundButton" TargetType="Button">
            <Setter Property="Background" Value="{theme_accent}"/>
            <Setter Property="Foreground" Value="{theme_bg}"/>
            <Setter Property="FontWeight" Value="Bold"/>
            <Setter Property="BorderThickness" Value="0"/>
            <Setter Property="Padding" Value="14,8"/>
            <Setter Property="Cursor" Value="Hand"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="Button">
                        <Border Background="{TemplateBinding Background}"
                                CornerRadius="6">
                            <ContentPresenter HorizontalAlignment="Center"
                                              VerticalAlignment="Center"
                                              Margin="{TemplateBinding Padding}"/>
                        </Border>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>
        <Style x:Key="RoundButtonSecondary" TargetType="Button" BasedOn="{StaticResource RoundButton}">
            <Setter Property="Background" Value="{theme_muted}"/>
            <Setter Property="Foreground" Value="{theme_text}"/>
        </Style>
        <Style TargetType="ListBoxItem">
            <Setter Property="Padding" Value="10,8"/>
            <Setter Property="Foreground" Value="{theme_text}"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="ListBoxItem">
                        <Border x:Name="Bd" Background="{theme_surface}" CornerRadius="6" Margin="0,3"
                                Padding="{TemplateBinding Padding}">
                            <ContentPresenter/>
                        </Border>
                        <ControlTemplate.Triggers>
                            <Trigger Property="IsSelected" Value="True">
                                <Setter TargetName="Bd" Property="Background" Value="{theme_accent}"/>
                            </Trigger>
                            <Trigger Property="IsMouseOver" Value="True">
                                <Setter TargetName="Bd" Property="Background" Value="{theme_muted}"/>
                            </Trigger>
                        </ControlTemplate.Triggers>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>
        <Style x:Key="SearchBox" TargetType="TextBox">
            <Setter Property="Background" Value="{theme_surface}"/>
            <Setter Property="Foreground" Value="{theme_text}"/>
            <Setter Property="CaretBrush" Value="{theme_text}"/>
            <Setter Property="BorderThickness" Value="0"/>
            <Setter Property="Padding" Value="10,7"/>
            <Setter Property="FontSize" Value="13"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="TextBox">
                        <Border Background="{TemplateBinding Background}" CornerRadius="6">
                            <ScrollViewer x:Name="PART_ContentHost" Margin="{TemplateBinding Padding}"/>
                        </Border>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>
    </Window.Resources>

    <Grid Margin="16">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <TextBlock Grid.Row="0" Text="Select Linked Model" FontSize="18" FontWeight="Bold"
                   Foreground="{theme_text}" Margin="0,0,0,4"/>
        <TextBlock Grid.Row="1" Text="Choose the linked model to copy elements from."
                   FontSize="12" Foreground="{theme_subtext}" Margin="0,0,0,10"/>

        <TextBox Grid.Row="2" x:Name="SearchBox" Style="{StaticResource SearchBox}"
                  Tag="Search linked models..." Margin="0,0,0,8"/>

        <Border Grid.Row="3" Background="{theme_card}" CornerRadius="8" Padding="8">
            <ListBox x:Name="LinkList" Background="Transparent" BorderThickness="0"
                     ScrollViewer.HorizontalScrollBarVisibility="Disabled">
                <ListBox.ItemTemplate>
                    <DataTemplate>
                        <TextBlock Text="{Binding DocTitle}" Foreground="{theme_text}"/>
                    </DataTemplate>
                </ListBox.ItemTemplate>
            </ListBox>
        </Border>

        <Grid Grid.Row="4" Margin="0,14,0,0">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="Auto"/>
                <ColumnDefinition Width="Auto"/>
            </Grid.ColumnDefinitions>
            <Button Grid.Column="1" Content="Cancel" x:Name="CancelBtn"
                    Style="{StaticResource RoundButtonSecondary}" Margin="0,0,8,0"/>
            <Button Grid.Column="2" Content="Next  ->" x:Name="NextBtn"
                    Style="{StaticResource RoundButton}"/>
        </Grid>
    </Grid>
</Window>
""".replace("{theme_bg}", THEME["bg"]) \
   .replace("{theme_card}", THEME["card"]) \
   .replace("{theme_surface}", THEME["surface"]) \
   .replace("{theme_muted}", THEME["muted"]) \
   .replace("{theme_text}", THEME["text"]) \
   .replace("{theme_subtext}", THEME["subtext"]) \
   .replace("{theme_accent}", THEME["accent"])


def build_category_picker_xaml():
    return u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Bulk Copy from Link - Select Categories"
        Height="560" Width="480"
        WindowStartupLocation="CenterScreen"
        Background="{theme_bg}">
    <Window.Resources>
        <Style x:Key="RoundButton" TargetType="Button">
            <Setter Property="Background" Value="{theme_accent}"/>
            <Setter Property="Foreground" Value="{theme_bg}"/>
            <Setter Property="FontWeight" Value="Bold"/>
            <Setter Property="BorderThickness" Value="0"/>
            <Setter Property="Padding" Value="14,8"/>
            <Setter Property="Cursor" Value="Hand"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="Button">
                        <Border Background="{TemplateBinding Background}"
                                CornerRadius="6">
                            <ContentPresenter HorizontalAlignment="Center"
                                              VerticalAlignment="Center"
                                              Margin="{TemplateBinding Padding}"/>
                        </Border>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>
        <Style x:Key="RoundButtonSecondary" TargetType="Button" BasedOn="{StaticResource RoundButton}">
            <Setter Property="Background" Value="{theme_muted}"/>
            <Setter Property="Foreground" Value="{theme_text}"/>
        </Style>
        <Style x:Key="CheckRow" TargetType="CheckBox">
            <Setter Property="Foreground" Value="{theme_text}"/>
            <Setter Property="Padding" Value="8,8"/>
            <Setter Property="FontSize" Value="13"/>
        </Style>
        <Style x:Key="SearchBox" TargetType="TextBox">
            <Setter Property="Background" Value="{theme_surface}"/>
            <Setter Property="Foreground" Value="{theme_text}"/>
            <Setter Property="CaretBrush" Value="{theme_text}"/>
            <Setter Property="BorderThickness" Value="0"/>
            <Setter Property="Padding" Value="10,7"/>
            <Setter Property="FontSize" Value="13"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="TextBox">
                        <Border Background="{TemplateBinding Background}" CornerRadius="6">
                            <ScrollViewer x:Name="PART_ContentHost" Margin="{TemplateBinding Padding}"/>
                        </Border>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>
    </Window.Resources>

    <Grid Margin="16">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <TextBlock Grid.Row="0" Text="Select Categories" FontSize="18" FontWeight="Bold"
                   Foreground="{theme_text}" Margin="0,0,0,4"/>
        <TextBlock Grid.Row="1" x:Name="SubtitleText" Text="Categories found in the selected link."
                   FontSize="12" Foreground="{theme_subtext}" Margin="0,0,0,10"/>

        <TextBox Grid.Row="2" x:Name="SearchBox" Style="{StaticResource SearchBox}"
                  Tag="Search categories..." Margin="0,0,0,8"/>

        <Grid Grid.Row="3" Margin="0,0,0,8">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="Auto"/>
                <ColumnDefinition Width="Auto"/>
            </Grid.ColumnDefinitions>
            <TextBlock Grid.Column="0" Text="" />
            <Button Grid.Column="1" Content="Select All" x:Name="SelectAllBtn"
                    Style="{StaticResource RoundButtonSecondary}" Margin="0,0,8,0" Padding="10,4"/>
            <Button Grid.Column="2" Content="Clear" x:Name="ClearAllBtn"
                    Style="{StaticResource RoundButtonSecondary}" Padding="10,4"/>
        </Grid>

        <Border Grid.Row="4" Background="{theme_card}" CornerRadius="8" Padding="8">
            <ScrollViewer VerticalScrollBarVisibility="Auto">
                <ItemsControl x:Name="CategoryList">
                    <ItemsControl.ItemTemplate>
                        <DataTemplate>
                            <Border Background="{theme_surface}" CornerRadius="6" Margin="0,3" Padding="4,0">
                                <CheckBox Content="{Binding Display}" IsChecked="{Binding IsChecked}"
                                          Style="{StaticResource CheckRow}"/>
                            </Border>
                        </DataTemplate>
                    </ItemsControl.ItemTemplate>
                </ItemsControl>
            </ScrollViewer>
        </Border>

        <Grid Grid.Row="5" Margin="0,14,0,0">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="Auto"/>
                <ColumnDefinition Width="Auto"/>
            </Grid.ColumnDefinitions>
            <Button Grid.Column="1" Content="Cancel" x:Name="CancelBtn"
                    Style="{StaticResource RoundButtonSecondary}" Margin="0,0,8,0"/>
            <Button Grid.Column="2" Content="Copy" x:Name="CopyBtn"
                    Style="{StaticResource RoundButton}"/>
        </Grid>
    </Grid>
</Window>
""".replace("{theme_bg}", THEME["bg"]) \
   .replace("{theme_card}", THEME["card"]) \
   .replace("{theme_surface}", THEME["surface"]) \
   .replace("{theme_muted}", THEME["muted"]) \
   .replace("{theme_text}", THEME["text"]) \
   .replace("{theme_subtext}", THEME["subtext"]) \
   .replace("{theme_accent}", THEME["accent"])


# ---------------------------------------------------------------------
# DATA HELPERS
# ---------------------------------------------------------------------
class LinkItem(object):
    """Simple display wrapper for a RevitLinkInstance in the ListBox."""
    def __init__(self, link_instance, doc_title):
        self.link_instance = link_instance
        self.DocTitle = doc_title


class CategoryRow(object):
    """Bindable row for the category checklist ItemsControl."""
    def __init__(self, category, count):
        self.category = category
        self.Display = u"{0}  ({1})".format(category.Name, count)
        self.IsChecked = False


def get_link_instances():
    """Collect all RevitLinkInstances in the active model that have a
    loaded linked document, returning LinkItem wrappers."""
    link_instances = FilteredElementCollector(doc) \
        .OfClass(RevitLinkInstance) \
        .ToElements()

    items = []
    for li in link_instances:
        lnk_doc = li.GetLinkDocument()
        if lnk_doc is None:
            # Link is unloaded - skip, can't read elements from it
            continue
        title = lnk_doc.Title
        items.append(LinkItem(li, title))
    return items


def get_categories_with_elements(lnkd_doc):
    """Return a dict {category_id_value: (category, count)} for every
    MODEL category in the linked document that has at least one model
    element. Annotation, Internal, and AnalyticalModel categories are
    excluded - this tool only copies physical model elements."""
    all_elements = FilteredElementCollector(lnkd_doc) \
        .WhereElementIsNotElementType() \
        .ToElements()

    cat_counts = {}   # category_id_value -> [Category, count]
    for el in all_elements:
        cat = el.Category
        if cat is None:
            continue
        if cat.CategoryType != CategoryType.Model:
            continue
        cat_id_val = cat.Id.Value if hasattr(cat.Id, "Value") else cat.Id.IntegerValue
        if cat_id_val in cat_counts:
            cat_counts[cat_id_val][1] += 1
        else:
            cat_counts[cat_id_val] = [cat, 1]

    return cat_counts


def is_curtain_panel_masquerading_as_door(el):
    """Detect a Curtain Panel that is reporting under the Doors category
    (a 'door panel' placed in a curtain grid). These elements typically
    fail to copy via ElementTransformUtils.CopyElements and should be
    skipped when bulk-copying the Doors category.

    Two independent signals are checked, since family/category metadata
    can vary across Revit versions and curtain panel setups:
      1. FamilyInstance.Symbol.Family.IsCurtainPanelFamily
      2. The element's Host is a Wall whose WallType.Kind is Curtain
    """
    if not isinstance(el, FamilyInstance):
        return False

    try:
        symbol = el.Symbol
        if symbol is not None and symbol.Family is not None:
            if symbol.Family.IsCurtainPanelFamily:
                return True
    except Exception:
        pass

    try:
        host = el.Host
        if isinstance(host, Wall) and host.WallType is not None:
            if host.WallType.Kind == WallKind.Curtain:
                return True
    except Exception:
        pass

    return False


def get_host_id(el):
    """Return the ElementId of el's Host if it has one and is hosted
    by a real element (not a face/work-plane based host without an
    Element), otherwise None."""
    try:
        host = el.Host
    except Exception:
        return None

    if host is None:
        return None

    try:
        host_id = host.Id
    except Exception:
        return None

    if host_id is None or host_id == ElementId.InvalidElementId:
        return None

    return host_id


def get_one_element_per_type(lnkd_doc, category_ids, doors_category_id=None):
    """For the given list of Category Ids (linked doc category ids),
    collect every element in those categories, group by ElementType Id,
    and return a list of one representative ElementId per distinct type.

    Elements with no type (TypeId == InvalidElementId) are each treated
    as their own distinct 'type' bucket, keyed by element Id, so nothing
    is silently dropped.

    Precautions applied:
    - If doors_category_id is provided and an element belongs to it,
      Curtain Panels masquerading as Doors are skipped entirely.
    - Any hosted element (window, door, etc.) automatically pulls its
      Host element's Id into the copy set as well, so the host comes
      along regardless of whether it was independently selected.
    """

    collector = FilteredElementCollector(lnkd_doc) \
        .WhereElementIsNotElementType() \
        .ToElements()

    invalid_id = ElementId.InvalidElementId

    seen_type_ids = set()
    representative_ids = []
    host_ids_to_add = set()  # collected separately, deduped, added at the end

    for el in collector:
        if el.Category is None:
            continue
        cat_id_val = el.Category.Id.Value if hasattr(el.Category.Id, "Value") else el.Category.Id.IntegerValue
        if cat_id_val not in category_ids:
            continue

        # PRECAUTION 1: skip Curtain Panels masquerading as Doors
        if doors_category_id is not None and cat_id_val == doors_category_id:
            if is_curtain_panel_masquerading_as_door(el):
                continue

        type_id = el.GetTypeId()

        if type_id == invalid_id or type_id is None:
            # No type relationship - treat this element as unique on its own
            key = ("__no_type__", el.Id.Value if hasattr(el.Id, "Value") else el.Id.IntegerValue)
        else:
            key = ("type", type_id.Value if hasattr(type_id, "Value") else type_id.IntegerValue)

        if key in seen_type_ids:
            continue

        seen_type_ids.add(key)
        representative_ids.append(el.Id)

        # PRECAUTION 2: if this element requires a host, bring the host along
        host_id = get_host_id(el)
        if host_id is not None:
            host_ids_to_add.add(host_id.Value if hasattr(host_id, "Value") else host_id.IntegerValue)

    # Merge in hosts that aren't already part of the representative set
    existing_id_vals = set(
        (rid.Value if hasattr(rid, "Value") else rid.IntegerValue) for rid in representative_ids
    )
    for host_id_val in host_ids_to_add:
        if host_id_val not in existing_id_vals:
            host_element = lnkd_doc.GetElement(ElementId(host_id_val))
            if host_element is not None:
                representative_ids.append(host_element.Id)
                existing_id_vals.add(host_id_val)

    return representative_ids


# ---------------------------------------------------------------------
# STEP 1 - PICK LINKED MODEL
# ---------------------------------------------------------------------
def pick_link_instance():
    link_items = get_link_instances()

    if not link_items:
        TaskDialog.Show("B-Dare95", "No loaded linked models were found in this project.")
        script.exit()

    xaml = build_link_picker_xaml()
    window = XamlReader.Parse(xaml)  # type: Window

    search_box = window.FindName("SearchBox")
    link_list_box = window.FindName("LinkList")
    next_btn = window.FindName("NextBtn")
    cancel_btn = window.FindName("CancelBtn")

    link_list_box.ItemsSource = link_items

    if link_list_box.Items.Count > 0:
        link_list_box.SelectedIndex = 0

    result_holder = [None]  # mutable container (IronPython 2.7 closure workaround)

    def on_search_changed(sender, args):
        query = search_box.Text.strip().lower() if search_box.Text else u""
        if not query:
            filtered = link_items
        else:
            filtered = [i for i in link_items if query in i.DocTitle.lower()]
        link_list_box.ItemsSource = filtered
        if link_list_box.Items.Count > 0:
            link_list_box.SelectedIndex = 0

    def on_next(sender, args):
        selected = link_list_box.SelectedItem
        if selected is not None:
            result_holder[0] = selected
        window.Close()

    def on_cancel(sender, args):
        result_holder[0] = None
        window.Close()

    search_box.TextChanged += on_search_changed
    next_btn.Click += on_next
    cancel_btn.Click += on_cancel
    link_list_box.MouseDoubleClick += on_next

    show_modeless(window)

    return result_holder[0]  # LinkItem or None


# ---------------------------------------------------------------------
# STEP 2 - PICK CATEGORIES
# ---------------------------------------------------------------------
def pick_categories(cat_counts):
    """cat_counts: dict {cat_id_val: [Category, count]}"""

    rows = [CategoryRow(cat, count) for (cat, count) in
            sorted(cat_counts.values(), key=lambda pair: pair[0].Name)]

    xaml = build_category_picker_xaml()
    window = XamlReader.Parse(xaml)  # type: Window

    search_box = window.FindName("SearchBox")
    category_list = window.FindName("CategoryList")
    copy_btn = window.FindName("CopyBtn")
    cancel_btn = window.FindName("CancelBtn")
    select_all_btn = window.FindName("SelectAllBtn")
    clear_all_btn = window.FindName("ClearAllBtn")

    visible_rows = [None]  # tracks the currently-filtered subset (mutable container)

    def refresh_list():
        category_list.ItemsSource = None
        category_list.ItemsSource = visible_rows[0]  # force refresh (no INotifyPropertyChanged)

    def apply_filter():
        query = search_box.Text.strip().lower() if search_box.Text else u""
        if not query:
            visible_rows[0] = rows
        else:
            visible_rows[0] = [r for r in rows if query in r.category.Name.lower()]
        refresh_list()

    apply_filter()

    result_holder = [None]

    def on_search_changed(sender, args):
        apply_filter()

    def on_select_all(sender, args):
        # Only affects categories currently visible under the active filter
        for r in visible_rows[0]:
            r.IsChecked = True
        refresh_list()

    def on_clear_all(sender, args):
        for r in visible_rows[0]:
            r.IsChecked = False
        refresh_list()

    def on_copy(sender, args):
        chosen = [r.category for r in rows if r.IsChecked]
        result_holder[0] = chosen
        window.Close()

    def on_cancel(sender, args):
        result_holder[0] = None
        window.Close()

    search_box.TextChanged += on_search_changed
    select_all_btn.Click += on_select_all
    clear_all_btn.Click += on_clear_all
    copy_btn.Click += on_copy
    cancel_btn.Click += on_cancel

    show_modeless(window)

    return result_holder[0]  # list of Category or None


# ---------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------
def main():
    # STEP 1: pick the linked model
    link_item = pick_link_instance()
    if link_item is None:
        script.exit()

    lnkd_doc = link_item.link_instance.GetLinkDocument()

    # STEP 2: collect categories present in the link, let user pick
    cat_counts = get_categories_with_elements(lnkd_doc)
    if not cat_counts:
        TaskDialog.Show("B-Dare95", "The selected link contains no model elements.")
        script.exit()

    chosen_categories = pick_categories(cat_counts)
    if not chosen_categories:
        script.exit()

    category_ids = set()
    doors_category_id = None
    for cat in chosen_categories:
        cat_id_val = cat.Id.Value if hasattr(cat.Id, "Value") else cat.Id.IntegerValue
        category_ids.add(cat_id_val)
        try:
            if cat.Id == ElementId(BuiltInCategory.OST_Doors):
                doors_category_id = cat_id_val
        except Exception:
            pass

    # STEP 3: one representative element per distinct type, across all chosen categories
    representative_ids = get_one_element_per_type(lnkd_doc, category_ids, doors_category_id)

    if not representative_ids:
        TaskDialog.Show("B-Dare95", "No elements found for the selected categories.")
        script.exit()

    list_el_ids = List[ElementId](representative_ids)

    t = Transaction(doc, "Bulk Copy from Link")
    t.Start()

    try:
        copied_ids = ElementTransformUtils.CopyElements(
            lnkd_doc, list_el_ids, doc,
            Transform.CreateTranslation(XYZ(0, 0, 0)),
            CopyPasteOptions()
        )
        for el_id in copied_ids:
            copied_el = doc.GetElement(el_id)
            copied_el.Pinned = True
        t.Commit()
    except Exception as ex:
        t.RollBack()
        TaskDialog.Show("B-Dare95", "Copy failed:\n{0}".format(ex))
        script.exit()

    TaskDialog.Show(
        "B-Dare95",
        "Copied {0} element(s) (one per distinct type, hosts included) across {1} category(ies).".format(
            len(list(copied_ids)), len(chosen_categories)
        )
    )


main()
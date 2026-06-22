# -*- coding: utf-8 -*-
__title__     = "Bulk Copy from Link"
__author__    = "Mohamed Bedair"
__version__   = 'Version = 2.0'
__doc__       = """Version = 2.0
Date    = 22.06.2026
_____________________________________________________________________
Description:

Copies one element per distinct Type, from one or more selected
Categories, out of a chosen Linked Model, into the active model
in the same place (pinned).
_____________________________________________________________________
How-to:

-> Run the script
-> Pick a Linked Model from the list
-> Pick one or more Categories from the list
   (only categories that actually exist in that link are shown)
-> Click Copy
-> One element per distinct Type under the selected Categories will
   be copied into the active model, in place, and pinned.
_____________________________________________________________________
Last update:
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
    ElementTransformUtils, Transform, XYZ, CopyPasteOptions
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
    </Window.Resources>

    <Grid Margin="16">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <TextBlock Grid.Row="0" Text="Select Linked Model" FontSize="18" FontWeight="Bold"
                   Foreground="{theme_text}" Margin="0,0,0,4"/>
        <TextBlock Grid.Row="1" Text="Choose the linked model to copy elements from."
                   FontSize="12" Foreground="{theme_subtext}" Margin="0,0,0,12"/>

        <Border Grid.Row="2" Background="{theme_card}" CornerRadius="8" Padding="8">
            <ListBox x:Name="LinkList" Background="Transparent" BorderThickness="0"
                     ScrollViewer.HorizontalScrollBarVisibility="Disabled">
                <ListBox.ItemTemplate>
                    <DataTemplate>
                        <TextBlock Text="{Binding DocTitle}" Foreground="{theme_text}"/>
                    </DataTemplate>
                </ListBox.ItemTemplate>
            </ListBox>
        </Border>

        <Grid Grid.Row="3" Margin="0,14,0,0">
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
    </Window.Resources>

    <Grid Margin="16">
        <Grid.RowDefinitions>
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

        <Grid Grid.Row="2" Margin="0,0,0,8">
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

        <Border Grid.Row="3" Background="{theme_card}" CornerRadius="8" Padding="8">
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

        <Grid Grid.Row="4" Margin="0,14,0,0">
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
    category in the linked document that has at least one model element."""
    all_elements = FilteredElementCollector(lnkd_doc) \
        .WhereElementIsNotElementType() \
        .ToElements()

    cat_counts = {}   # category_id_value -> [Category, count]
    for el in all_elements:
        cat = el.Category
        if cat is None:
            continue
        cat_id_val = cat.Id.Value if hasattr(cat.Id, "Value") else cat.Id.IntegerValue
        if cat_id_val in cat_counts:
            cat_counts[cat_id_val][1] += 1
        else:
            cat_counts[cat_id_val] = [cat, 1]

    return cat_counts


def get_one_element_per_type(lnkd_doc, category_ids):
    """For the given list of Category Ids (linked doc category ids),
    collect every element in those categories, group by ElementType Id,
    and return a list of one representative ElementId per distinct type.

    Elements with no type (TypeId == InvalidElementId) are each treated
    as their own distinct 'type' bucket, keyed by element Id, so nothing
    is silently dropped."""

    collector = FilteredElementCollector(lnkd_doc) \
        .WhereElementIsNotElementType() \
        .ToElements()

    invalid_id = ElementId.InvalidElementId

    seen_type_ids = set()
    representative_ids = []

    for el in collector:
        if el.Category is None:
            continue
        cat_id_val = el.Category.Id.Value if hasattr(el.Category.Id, "Value") else el.Category.Id.IntegerValue
        if cat_id_val not in category_ids:
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

    link_list_box = window.FindName("LinkList")
    next_btn = window.FindName("NextBtn")
    cancel_btn = window.FindName("CancelBtn")

    for item in link_items:
        link_list_box.Items.Add(item)

    if link_list_box.Items.Count > 0:
        link_list_box.SelectedIndex = 0

    result_holder = [None]  # mutable container (IronPython 2.7 closure workaround)

    def on_next(sender, args):
        selected = link_list_box.SelectedItem
        if selected is not None:
            result_holder[0] = selected
        window.Close()

    def on_cancel(sender, args):
        result_holder[0] = None
        window.Close()

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

    category_list = window.FindName("CategoryList")
    copy_btn = window.FindName("CopyBtn")
    cancel_btn = window.FindName("CancelBtn")
    select_all_btn = window.FindName("SelectAllBtn")
    clear_all_btn = window.FindName("ClearAllBtn")

    category_list.ItemsSource = rows

    result_holder = [None]

    def on_select_all(sender, args):
        for r in rows:
            r.IsChecked = True
        category_list.ItemsSource = None
        category_list.ItemsSource = rows  # force refresh (no INotifyPropertyChanged)

    def on_clear_all(sender, args):
        for r in rows:
            r.IsChecked = False
        category_list.ItemsSource = None
        category_list.ItemsSource = rows

    def on_copy(sender, args):
        chosen = [r.category for r in rows if r.IsChecked]
        result_holder[0] = chosen
        window.Close()

    def on_cancel(sender, args):
        result_holder[0] = None
        window.Close()

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
    for cat in chosen_categories:
        cat_id_val = cat.Id.Value if hasattr(cat.Id, "Value") else cat.Id.IntegerValue
        category_ids.add(cat_id_val)

    # STEP 3: one representative element per distinct type, across all chosen categories
    representative_ids = get_one_element_per_type(lnkd_doc, category_ids)

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
        "Copied {0} element(s) (one per distinct type) across {1} category(ies).".format(
            len(list(copied_ids)), len(chosen_categories)
        )
    )


main()
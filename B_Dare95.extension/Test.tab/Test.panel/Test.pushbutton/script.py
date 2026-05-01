# -*- coding: utf-8 -*-
__title__ = "Pre-Filter Selection"
__author__ = "Mohamed Bedair"
__version__ = '1.2.0'
__doc__ = """
Version = 1.2.0
Date    = 01.05.2025

Description:
Filters the Selection box to only selected categories. Also allows negating selection with SHIFT click.

How-to:
-> Run the script
-> Select desired categories from the menu
-> The selection box will only highlight selected categories

Last update:
- [01.05.2025] - 1.2.0 RELEASE
  - Updated UI to Catppuccin dark theme
- [19.02.2025] - 1.1.0 RELEASE
  - Added Feature to Negate Selection with SHIFT Click

Author: Mohamed Bedair
"""

# IMPORTS
import System
import clr
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from System.Collections.Generic import List
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI.Selection import *
from pyrevit import script
from pyrevit import EXEC_PARAMS

import System.Windows
import System.Windows.Controls as Controls
import System.Windows.Media as Media
from System.Windows.Markup import XamlReader
from System.Windows import Window, Thickness
from System.Windows.Controls import ScrollBarVisibility

# Get active Revit document and selection objects
doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
selection = uidoc.Selection


# ─── THEME COLOURS ────────────────────────────────────────────────────────────
BG      = "#1E1E2E"
CARD    = "#2A2A3C"
SURFACE = "#313244"
MUTED   = "#45475A"
TEXT    = "#CDD6F4"
SUBTEXT = "#A6ADC8"
ACCENT  = "#F0A500"
# ──────────────────────────────────────────────────────────────────────────────

XAML_TEMPLATE = """
<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Choose Categories"
    Width="320" MinHeight="120" MaxHeight="620"
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
            <TextBlock Text="Choose Categories"
                       FontSize="15" FontWeight="SemiBold"
                       Foreground="{TEXT}"
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


# ─── SELECTION DIALOG ─────────────────────────────────────────────────────────

def show_category_picker(all_categories):
    """Show a themed WPF category picker. Returns list of chosen names or None."""

    window = XamlReader.Parse(XAML_TEMPLATE)

    search_box      = window.FindName("SearchBox")
    cat_panel       = window.FindName("CategoryPanel")
    confirm_btn     = window.FindName("ConfirmBtn")
    select_all_btn  = window.FindName("SelectAllBtn")
    clear_btn       = window.FindName("ClearBtn")
    count_label     = window.FindName("CountLabel")

    result_holder   = [None]   # mutable container for IronPython 2.7 closure

    # Build a CheckBox for every category
    checkboxes = []
    for name in all_categories:
        cb = Controls.CheckBox()
        cb.Content = name
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
    search_box.TextChanged    += update_filter
    select_all_btn.Click      += on_select_all
    clear_btn.Click           += on_clear
    confirm_btn.Click         += on_confirm

    for cb in checkboxes:
        cb.Checked   += on_checked
        cb.Unchecked += on_checked

    update_count()
    window.ShowDialog()

    return result_holder[0]


# ─── SELECTION FILTER ─────────────────────────────────────────────────────────

class CustomISelectionFilter(ISelectionFilter):
    """Custom Selection Filter to allow only elements belonging to specified categories."""

    def __init__(self, allowed_categories):
        self.allowed_categories = set(allowed_categories)

    def AllowElement(self, elem):
        return elem.Category and elem.Category.Name in self.allowed_categories

    def AllowReference(self, reference, position):
        return False


# ─── HELPERS ──────────────────────────────────────────────────────────────────

def get_all_category_names(doc):
    """Retrieve all model category names from the document."""
    return sorted(cat.Name for cat in doc.Settings.Categories if cat.CategoryType == CategoryType.Model)


def negate_selection(names_chosen):
    """Allows rectangle selection then removes elements matching chosen categories."""
    try:
        elements_to_filter = selection.PickElementsByRectangle("Select Elements")
        filtered_ids = [el.Id for el in elements_to_filter
                        if el.Category and el.Category.Name not in names_chosen]
        uidoc.Selection.SetElementIds(List[ElementId](filtered_ids))
    except Exception:
        script.exit()


def apply_category_filter(names_chosen):
    """Applies category filter and restricts rectangle selection to chosen categories."""
    try:
        sel_filter      = CustomISelectionFilter(names_chosen)
        selected_elements = selection.PickElementsByRectangle(sel_filter, "Select Elements")
        selected_ids    = [el.Id for el in selected_elements]
        uidoc.Selection.SetElementIds(List[ElementId](selected_ids))
    except Exception:
        script.exit()


# ─── MAIN ─────────────────────────────────────────────────────────────────────

all_categories = get_all_category_names(doc)
names_chosen   = show_category_picker(all_categories)

if not names_chosen:
    script.exit()

if EXEC_PARAMS.config_mode:
    negate_selection(names_chosen)
else:
    apply_category_filter(names_chosen)
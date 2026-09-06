# -*- coding: utf-8 -*-

__title__   = "Wipe Unplaced Elements"
__author__  = "Mohamed Bedair"
__version__ = "1.0.0"
__doc__     = """
Version = 1.0.0

Description:
Purges unplaced Rooms, Areas, and/or MEP Spaces from the active
Revit document.  An element is considered "unplaced" when it has
no location in any view and is not associated with a Level.

How-to:
-> Run the script
-> Tick the categories you want to purge
-> Confirm the operation

Author: Mohamed Bedair
"""

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')
clr.AddReference('System.Xml')

from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory,
    LocationPoint, TransactionGroup, Transaction
)
from System.Windows import (
    Window, Visibility,
    MessageBox, MessageBoxButton, MessageBoxResult, MessageBoxImage
)
from System.Windows.Markup import XamlReader
from System.Windows.Media import SolidColorBrush, Color
from System.IO import StringReader
from System.Xml import XmlReader
import sys

doc = __revit__.ActiveUIDocument.Document  # noqa: F821

# ─────────────────────────────────────────────────────────────
#  Collectors
# ─────────────────────────────────────────────────────────────

def _is_unplaced_by_location(element):
    """Rooms and Spaces: unplaced when Location is None or has no Point."""
    loc = element.Location
    return loc is None or (isinstance(loc, LocationPoint) and loc.Point is None)


def _is_unplaced_area(element):
    """Areas: unplaced when the Level parameter has no value."""
    param = element.LookupParameter("Level")
    return param is None or not param.HasValue


def _collect(category, predicate):
    return [
        e for e in
        FilteredElementCollector(doc)
            .OfCategory(category)
            .WhereElementIsNotElementType()
            .ToElements()
        if predicate(e)
    ]


unplaced = {
    "Rooms":  _collect(BuiltInCategory.OST_Rooms,      _is_unplaced_by_location),
    "Areas":  _collect(BuiltInCategory.OST_Areas,      _is_unplaced_area),
    "Spaces": _collect(BuiltInCategory.OST_MEPSpaces,  _is_unplaced_by_location),
}

# ─────────────────────────────────────────────────────────────
#  XAML  (Catppuccin dark — bg #1E1E2E, accent #F0A500)
# ─────────────────────────────────────────────────────────────

XAML = """
<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Wipe Unplaced Elements"
    Width="380"
    SizeToContent="Height"
    WindowStartupLocation="CenterScreen"
    ResizeMode="NoResize"
    Background="#1E1E2E"
    FontFamily="Segoe UI">

    <Window.Resources>

        <!-- Card border -->
        <Style x:Key="Card" TargetType="Border">
            <Setter Property="Background"     Value="#2A2A3C"/>
            <Setter Property="CornerRadius"   Value="8"/>
            <Setter Property="Padding"        Value="14,12"/>
            <Setter Property="Margin"         Value="0,0,0,8"/>
        </Style>

        <!-- CheckBox -->
        <Style TargetType="CheckBox">
            <Setter Property="Foreground"              Value="#CDD6F4"/>
            <Setter Property="FontSize"                Value="13"/>
            <Setter Property="FontWeight"              Value="SemiBold"/>
            <Setter Property="VerticalContentAlignment" Value="Center"/>
            <Setter Property="Cursor"                  Value="Hand"/>
        </Style>

        <!-- Count label (hidden by default) -->
        <Style x:Key="CountLbl" TargetType="TextBlock">
            <Setter Property="FontSize"   Value="11"/>
            <Setter Property="Margin"     Value="22,5,0,0"/>
            <Setter Property="Visibility" Value="Collapsed"/>
        </Style>

        <!-- OK button -->
        <Style x:Key="BtnOK" TargetType="Button">
            <Setter Property="Background"   Value="#F0A500"/>
            <Setter Property="Foreground"   Value="#1E1E2E"/>
            <Setter Property="FontWeight"   Value="Bold"/>
            <Setter Property="FontSize"     Value="13"/>
            <Setter Property="Height"       Value="34"/>
            <Setter Property="Width"        Value="88"/>
            <Setter Property="Cursor"       Value="Hand"/>
            <Setter Property="BorderThickness" Value="0"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="Button">
                        <Border Background="{TemplateBinding Background}"
                                CornerRadius="6" Padding="12,6">
                            <ContentPresenter HorizontalAlignment="Center"
                                              VerticalAlignment="Center"/>
                        </Border>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>

        <!-- Cancel button -->
        <Style x:Key="BtnCancel" TargetType="Button">
            <Setter Property="Background"   Value="#45475A"/>
            <Setter Property="Foreground"   Value="#CDD6F4"/>
            <Setter Property="FontSize"     Value="13"/>
            <Setter Property="Height"       Value="34"/>
            <Setter Property="Width"        Value="88"/>
            <Setter Property="Cursor"       Value="Hand"/>
            <Setter Property="BorderThickness" Value="0"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="Button">
                        <Border Background="{TemplateBinding Background}"
                                CornerRadius="6" Padding="12,6">
                            <ContentPresenter HorizontalAlignment="Center"
                                              VerticalAlignment="Center"/>
                        </Border>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>

    </Window.Resources>

    <StackPanel Margin="20">

        <!-- ── Header ── -->
        <TextBlock Text="Wipe Unplaced Elements"
                   Foreground="#CDD6F4"
                   FontSize="16" FontWeight="Bold"
                   Margin="0,0,0,4"/>
        <TextBlock Text="Select the categories you want to purge from this document."
                   Foreground="#A6ADC8" FontSize="11"
                   TextWrapping="Wrap"
                   Margin="0,0,0,18"/>

        <!-- ── Rooms ── -->
        <Border Style="{StaticResource Card}">
            <StackPanel>
                <CheckBox x:Name="ChkRooms" Content="Rooms"/>
                <TextBlock x:Name="LblRooms" Style="{StaticResource CountLbl}"/>
            </StackPanel>
        </Border>

        <!-- ── Areas ── -->
        <Border Style="{StaticResource Card}">
            <StackPanel>
                <CheckBox x:Name="ChkAreas" Content="Areas"/>
                <TextBlock x:Name="LblAreas" Style="{StaticResource CountLbl}"/>
            </StackPanel>
        </Border>

        <!-- ── MEP Spaces ── -->
        <Border Style="{StaticResource Card}">
            <StackPanel>
                <CheckBox x:Name="ChkSpaces" Content="MEP Spaces"/>
                <TextBlock x:Name="LblSpaces" Style="{StaticResource CountLbl}"/>
            </StackPanel>
        </Border>

        <!-- ── Buttons ── -->
        <StackPanel Orientation="Horizontal"
                    HorizontalAlignment="Right"
                    Margin="0,18,0,0">
            <Button x:Name="BtnCancel" Content="Cancel"
                    Style="{StaticResource BtnCancel}"
                    Margin="0,0,10,0"/>
            <Button x:Name="BtnOK" Content="OK"
                    Style="{StaticResource BtnOK}"/>
        </StackPanel>

    </StackPanel>
</Window>
"""

# ─────────────────────────────────────────────────────────────
#  Build window & wire up events
# ─────────────────────────────────────────────────────────────

window    = XamlReader.Load(XmlReader.Create(StringReader(XAML)))

chk_rooms  = window.FindName("ChkRooms")
chk_areas  = window.FindName("ChkAreas")
chk_spaces = window.FindName("ChkSpaces")
lbl_rooms  = window.FindName("LblRooms")
lbl_areas  = window.FindName("LblAreas")
lbl_spaces = window.FindName("LblSpaces")
btn_ok     = window.FindName("BtnOK")
btn_cancel = window.FindName("BtnCancel")

ACCENT  = SolidColorBrush(Color.FromRgb(0xF0, 0xA5, 0x00))   # #F0A500
MUTED   = SolidColorBrush(Color.FromRgb(0xA6, 0xAD, 0xC8))   # #A6ADC8


def _set_count_label(label, count, singular, plural=None):
    plural = plural or singular + "s"
    if count == 0:
        label.Text       = u"\u26a0  No unplaced {} found".format(plural)
        label.Foreground = MUTED
    elif count == 1:
        label.Text       = u"\u2714  1 unplaced {} found".format(singular)
        label.Foreground = ACCENT
    else:
        label.Text       = u"\u2714  {} unplaced {} found".format(count, plural)
        label.Foreground = ACCENT
    label.Visibility = Visibility.Visible


def on_rooms_checked(s, e):
    _set_count_label(lbl_rooms, len(unplaced["Rooms"]), "Room")

def on_rooms_unchecked(s, e):
    lbl_rooms.Visibility = Visibility.Collapsed

def on_areas_checked(s, e):
    _set_count_label(lbl_areas, len(unplaced["Areas"]), "Area")

def on_areas_unchecked(s, e):
    lbl_areas.Visibility = Visibility.Collapsed

def on_spaces_checked(s, e):
    _set_count_label(lbl_spaces, len(unplaced["Spaces"]), "Space")

def on_spaces_unchecked(s, e):
    lbl_spaces.Visibility = Visibility.Collapsed


chk_rooms.Checked    += on_rooms_checked
chk_rooms.Unchecked  += on_rooms_unchecked
chk_areas.Checked    += on_areas_checked
chk_areas.Unchecked  += on_areas_unchecked
chk_spaces.Checked   += on_spaces_checked
chk_spaces.Unchecked += on_spaces_unchecked

# Mutable flag — IronPython 2.7 closure-safe pattern
confirmed = [False]

def on_ok(s, e):
    confirmed[0] = True
    window.Close()

def on_cancel(s, e):
    window.Close()

btn_ok.Click    += on_ok
btn_cancel.Click += on_cancel

window.ShowDialog()

if not confirmed[0]:
    sys.exit()

# ─────────────────────────────────────────────────────────────
#  Build deletion list from checked categories
# ─────────────────────────────────────────────────────────────

to_delete = []  # list of (ElementId, category_label)

if chk_rooms.IsChecked:
    to_delete += [(rm.Id, "Room") for rm in unplaced["Rooms"]]
if chk_areas.IsChecked:
    to_delete += [(ar.Id, "Area") for ar in unplaced["Areas"]]
if chk_spaces.IsChecked:
    to_delete += [(sp.Id, "Space") for sp in unplaced["Spaces"]]

if not to_delete:
    MessageBox.Show(
        "No categories were selected. Nothing to purge.",
        __title__,
        MessageBoxButton.OK,
        MessageBoxImage.Information
    )
    sys.exit()

# ─────────────────────────────────────────────────────────────
#  Confirmation dialog
# ─────────────────────────────────────────────────────────────

lines = []
if chk_rooms.IsChecked  and unplaced["Rooms"]:
    lines.append(u"  \u2022 {} Room(s)".format(len(unplaced["Rooms"])))
if chk_areas.IsChecked  and unplaced["Areas"]:
    lines.append(u"  \u2022 {} Area(s)".format(len(unplaced["Areas"])))
if chk_spaces.IsChecked and unplaced["Spaces"]:
    lines.append(u"  \u2022 {} MEP Space(s)".format(len(unplaced["Spaces"])))

confirm_msg = (
    u"The following unplaced elements will be permanently deleted:\n\n"
    + u"\n".join(lines)
    + u"\n\nTotal: {} element(s)\n\nDo you want to proceed?".format(len(to_delete))
)

answer = MessageBox.Show(
    confirm_msg,
    u"Confirm Deletion",
    MessageBoxButton.OKCancel,
    MessageBoxImage.Warning
)

if answer != MessageBoxResult.OK:
    sys.exit()

# ─────────────────────────────────────────────────────────────
#  Execute deletions
# ─────────────────────────────────────────────────────────────

tgrp = TransactionGroup(doc, __title__)
tgrp.Start()

deleted_count = 0
failed_count  = 0

for elem_id, category_label in to_delete:
    t = Transaction(doc, u"Delete Unplaced {}".format(category_label))
    t.Start()
    try:
        result = doc.Delete(elem_id)
        if result and result.Count > 0:
            deleted_count += 1
        else:
            failed_count += 1
    except Exception:  # noqa: BLE001
        failed_count += 1
    t.Commit()

tgrp.Assimilate()

# ─────────────────────────────────────────────────────────────
#  Summary
# ─────────────────────────────────────────────────────────────

summary = (
    u"Operation complete.\n\n"
    u"  \u2714  Deleted : {}\n"
    u"  \u26a0  Failed  : {}"
).format(deleted_count, failed_count)

MessageBox.Show(
    summary,
    __title__,
    MessageBoxButton.OK,
    MessageBoxImage.Information
)
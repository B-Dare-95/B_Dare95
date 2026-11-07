# -*- coding: utf-8 -*-

TOOL_NAME   = "Wipe Unplaced"
__author__  = "Mohamed Bedair"
__doc__ = """__________________________________________________
Description:

Deletes unplaced rooms, areas and MEP spaces from the model. You choose which of the three to clean and confirm before anything is deleted. Rooms that are placed but not enclosed or redundant are never touched, and in a shared model, ones another user owns are skipped.
__________________________________________________
How-to:

-> Click on the button
-> Tick Rooms, Areas and/or MEP Spaces (counts appear when ticked)
-> Click OK
-> Confirm the list of elements to delete
-> A summary shows how many were deleted
__________________________________________________
Author: Mohamed Bedair"""

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')

from System import EventHandler
from System.Collections.Generic import List
from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory, ElementId, SpatialElement,
    Transaction, WorksharingUtils, CheckoutStatus
)
from System.Windows import (
    Visibility, RoutedEventHandler,
    MessageBox, MessageBoxButton, MessageBoxResult, MessageBoxImage
)
from System.Windows.Markup import XamlReader
from System.Windows.Media import SolidColorBrush, Color
from System.Windows.Threading import Dispatcher, DispatcherFrame
from System.Windows.Interop import WindowInteropHelper
import sys

doc = __revit__.ActiveUIDocument.Document  # noqa: F821

# ─────────────────────────────────────────────────────────────
#  Collectors
#  Unplaced = no Location. Language-independent, and it is what separates them
#  from rooms that are placed but not enclosed or redundant: those still have a
#  Location (with an area of 0), so they are never collected.
# ─────────────────────────────────────────────────────────────

def _owned_by_other(element):
    """True when another user owns the element in a shared model (it can't be deleted)."""
    if not doc.IsWorkshared:
        return False
    try:
        return WorksharingUtils.GetCheckoutStatus(doc, element.Id) == CheckoutStatus.OwnedByOtherUser
    except Exception:
        return False


def _collect(category):
    """(deletable unplaced elements, unplaced ones owned by other users)."""
    free, owned = [], []
    for e in (FilteredElementCollector(doc)
              .OfCategory(category)
              .WhereElementIsNotElementType()
              .ToElements()):
        if not isinstance(e, SpatialElement) or e.Location is not None:
            continue
        if _owned_by_other(e):
            owned.append(e)
        else:
            free.append(e)
    return free, owned


unplaced, owned = {}, {}
for key, bic in (("Rooms",  BuiltInCategory.OST_Rooms),
                 ("Areas",  BuiltInCategory.OST_Areas),
                 ("Spaces", BuiltInCategory.OST_MEPSpaces)):
    unplaced[key], owned[key] = _collect(bic)

if not any(unplaced[k] or owned[k] for k in unplaced):
    MessageBox.Show(
        "No Unplaced Elements found",
        TOOL_NAME,
        MessageBoxButton.OK,
        MessageBoxImage.Information
    )
    sys.exit()

# ─────────────────────────────────────────────────────────────
#  XAML  (IBM Carbon — bg #161616, accent #F1C21B)
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
    Background="#161616"
    FontFamily="Segoe UI">

    <Window.Resources>

        <!-- Card border -->
        <Style x:Key="Card" TargetType="Border">
            <Setter Property="Background"     Value="#262626"/>
            <Setter Property="CornerRadius"   Value="8"/>
            <Setter Property="Padding"        Value="14,12"/>
            <Setter Property="Margin"         Value="0,0,0,8"/>
        </Style>

        <!-- CheckBox -->
        <Style TargetType="CheckBox">
            <Setter Property="Foreground"              Value="#F4F4F4"/>
            <Setter Property="FontSize"                Value="13"/>
            <Setter Property="FontWeight"              Value="SemiBold"/>
            <Setter Property="VerticalContentAlignment" Value="Center"/>
            <Setter Property="Cursor"                  Value="Hand"/>
        </Style>

        <!-- Count label (hidden by default) -->
        <Style x:Key="CountLbl" TargetType="TextBlock">
            <Setter Property="FontSize"     Value="11"/>
            <Setter Property="Margin"       Value="22,5,0,0"/>
            <Setter Property="TextWrapping" Value="Wrap"/>
            <Setter Property="Visibility"   Value="Collapsed"/>
        </Style>

        <!-- OK button -->
        <Style x:Key="BtnOK" TargetType="Button">
            <Setter Property="Background"   Value="#F1C21B"/>
            <Setter Property="Foreground"   Value="#161616"/>
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
            <Setter Property="Background"   Value="#525252"/>
            <Setter Property="Foreground"   Value="#F4F4F4"/>
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
                   Foreground="#F4F4F4"
                   FontSize="16" FontWeight="Bold"
                   Margin="0,0,0,4"/>
        <TextBlock Text="Select the categories you want to purge from this document."
                   Foreground="#A8A8A8" FontSize="11"
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

window = XamlReader.Parse(XAML)
try:
    WindowInteropHelper(window).Owner = __revit__.MainWindowHandle  # noqa: F821
except Exception:
    pass

chk_rooms  = window.FindName("ChkRooms")
chk_areas  = window.FindName("ChkAreas")
chk_spaces = window.FindName("ChkSpaces")
lbl_rooms  = window.FindName("LblRooms")
lbl_areas  = window.FindName("LblAreas")
lbl_spaces = window.FindName("LblSpaces")
btn_ok     = window.FindName("BtnOK")
btn_cancel = window.FindName("BtnCancel")

ACCENT  = SolidColorBrush(Color.FromRgb(0xF1, 0xC2, 0x1B))   # #F1C21B
MUTED   = SolidColorBrush(Color.FromRgb(0xA8, 0xA8, 0xA8))   # #A8A8A8


def _set_count_label(label, key, singular, plural=None):
    plural = plural or singular + "s"
    count = len(unplaced[key])
    if count == 0:
        label.Text       = u"⚠  No unplaced {} found".format(plural)
        label.Foreground = MUTED
    elif count == 1:
        label.Text       = u"✔  1 unplaced {} found".format(singular)
        label.Foreground = ACCENT
    else:
        label.Text       = u"✔  {} unplaced {} found".format(count, plural)
        label.Foreground = ACCENT
    if owned[key]:
        label.Text += u"  ({} owned by other users will be skipped)".format(len(owned[key]))
    label.Visibility = Visibility.Visible


def on_rooms_checked(s, e):
    _set_count_label(lbl_rooms, "Rooms", "Room")

def on_rooms_unchecked(s, e):
    lbl_rooms.Visibility = Visibility.Collapsed

def on_areas_checked(s, e):
    _set_count_label(lbl_areas, "Areas", "Area")

def on_areas_unchecked(s, e):
    lbl_areas.Visibility = Visibility.Collapsed

def on_spaces_checked(s, e):
    _set_count_label(lbl_spaces, "Spaces", "Space")

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

btn_ok.Click     += RoutedEventHandler(on_ok)
btn_cancel.Click += RoutedEventHandler(on_cancel)

# Show + PushFrame instead of ShowDialog
frame = DispatcherFrame()

def on_closed(s, e):
    frame.Continue = False

window.Closed += EventHandler(on_closed)
window.Show()
Dispatcher.PushFrame(frame)

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
        "No categories with unplaced elements were selected. Nothing to purge.",
        TOOL_NAME,
        MessageBoxButton.OK,
        MessageBoxImage.Information
    )
    sys.exit()

# ─────────────────────────────────────────────────────────────
#  Confirmation dialog
# ─────────────────────────────────────────────────────────────

lines = []
if chk_rooms.IsChecked  and unplaced["Rooms"]:
    lines.append(u"  • {} Room(s)".format(len(unplaced["Rooms"])))
if chk_areas.IsChecked  and unplaced["Areas"]:
    lines.append(u"  • {} Area(s)".format(len(unplaced["Areas"])))
if chk_spaces.IsChecked and unplaced["Spaces"]:
    lines.append(u"  • {} MEP Space(s)".format(len(unplaced["Spaces"])))

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
#  Execute deletions: one transaction (one undo).
#  All at once first; one by one only if the batch fails, so one bad
#  element doesn't stop the rest.
# ─────────────────────────────────────────────────────────────

deleted_count = 0
failed_count  = 0

t = Transaction(doc, TOOL_NAME)
t.Start()
try:
    try:
        doc.Delete(List[ElementId]([elem_id for elem_id, _ in to_delete]))
        deleted_count = len(to_delete)
    except Exception:
        for elem_id, category_label in to_delete:
            if doc.GetElement(elem_id) is None:
                continue
            try:
                doc.Delete(elem_id)
                deleted_count += 1
            except Exception:  # noqa: BLE001
                failed_count += 1
    t.Commit()
except Exception as ex:
    t.RollBack()
    MessageBox.Show(
        u"Nothing was deleted: {}".format(ex),
        TOOL_NAME,
        MessageBoxButton.OK,
        MessageBoxImage.Error
    )
    sys.exit()

# ─────────────────────────────────────────────────────────────
#  Summary
# ─────────────────────────────────────────────────────────────

skipped = 0
if chk_rooms.IsChecked:
    skipped += len(owned["Rooms"])
if chk_areas.IsChecked:
    skipped += len(owned["Areas"])
if chk_spaces.IsChecked:
    skipped += len(owned["Spaces"])

summary = (
    u"Operation complete.\n\n"
    u"  ✔  Deleted : {}\n"
    u"  ⚠  Failed  : {}"
).format(deleted_count, failed_count)
if skipped:
    summary += u"\n  →  Skipped : {} (owned by other users)".format(skipped)

MessageBox.Show(
    summary,
    TOOL_NAME,
    MessageBoxButton.OK,
    MessageBoxImage.Information
)

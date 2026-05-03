# -*- coding: utf-8 -*-
"""
ResetFLSAreaPlans.py
────────────────────
Detects all Area Plan views under the Area Scheme "FLS" and lets the user
selectively delete Area Elements and/or Area Boundary Lines from chosen views.

UI  : Catppuccin-dark WPF  (bg #1E1E2E, card #2A2A3C, accent #F0A500)
API : IronPython 2.7 / Revit API (no Id.IntegerValue usage)
"""

__title__  = "Reset FLS\nArea Plans"
__doc__    = "Delete Area elements and/or Boundary lines from FLS Area Plan views."
__author__ = "B_Dare95"

# ── stdlib / clr ──────────────────────────────────────────────────────────────
import clr
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")
clr.AddReference("System")

import System
from System.Windows.Markup  import XamlReader
from System.Windows          import MessageBox, MessageBoxButton, MessageBoxResult
from System.Windows.Controls import CheckBox
from System.Windows          import Thickness

# ── Revit / pyRevit ───────────────────────────────────────────────────────────
from Autodesk.Revit.DB import (
    FilteredElementCollector,
    AreaScheme,
    ViewPlan,
    BuiltInCategory,
    ElementId,
)
from pyrevit import revit, script

doc    = revit.doc
output = script.get_output()

# ─────────────────────────────────────────────────────────────────────────────
# XAML
# ─────────────────────────────────────────────────────────────────────────────
XAML = """
<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Reset FLS Area Plans"
    Width="500" MinHeight="400" MaxHeight="700"
    SizeToContent="Height"
    WindowStartupLocation="CenterScreen"
    ResizeMode="NoResize"
    Background="#1E1E2E"
    FontFamily="Segoe UI">

    <Window.Resources>

        <!-- ── Accent button (orange) ───────────────────────────── -->
        <Style x:Key="AccentBtn" TargetType="Button">
            <Setter Property="Background"       Value="#F0A500"/>
            <Setter Property="Foreground"       Value="#1E1E2E"/>
            <Setter Property="FontWeight"       Value="SemiBold"/>
            <Setter Property="FontSize"         Value="13"/>
            <Setter Property="Padding"          Value="22,9"/>
            <Setter Property="BorderThickness"  Value="0"/>
            <Setter Property="Cursor"           Value="Hand"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="Button">
                        <Border x:Name="Bd"
                                Background="{TemplateBinding Background}"
                                CornerRadius="9"
                                Padding="{TemplateBinding Padding}">
                            <ContentPresenter HorizontalAlignment="Center"
                                              VerticalAlignment="Center"/>
                        </Border>
                        <ControlTemplate.Triggers>
                            <Trigger Property="IsMouseOver" Value="True">
                                <Setter TargetName="Bd" Property="Opacity" Value="0.82"/>
                            </Trigger>
                            <Trigger Property="IsPressed" Value="True">
                                <Setter TargetName="Bd" Property="Opacity" Value="0.65"/>
                            </Trigger>
                            <Trigger Property="IsEnabled" Value="False">
                                <Setter TargetName="Bd" Property="Opacity" Value="0.40"/>
                            </Trigger>
                        </ControlTemplate.Triggers>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>

        <!-- ── Muted button (grey) ──────────────────────────────── -->
        <Style x:Key="MutedBtn" TargetType="Button" BasedOn="{StaticResource AccentBtn}">
            <Setter Property="Background" Value="#45475A"/>
            <Setter Property="Foreground" Value="#CDD6F4"/>
        </Style>

        <!-- ── Danger button (red) ──────────────────────────────── -->
        <Style x:Key="DangerBtn" TargetType="Button" BasedOn="{StaticResource AccentBtn}">
            <Setter Property="Background" Value="#F38BA8"/>
            <Setter Property="Foreground" Value="#1E1E2E"/>
        </Style>

        <!-- ── CheckBox ─────────────────────────────────────────── -->
        <Style TargetType="CheckBox">
            <Setter Property="Foreground"  Value="#CDD6F4"/>
            <Setter Property="FontSize"    Value="13"/>
            <Setter Property="Cursor"      Value="Hand"/>
            <Setter Property="Padding"     Value="6,2"/>
        </Style>

        <!-- ── TextBox (rounded) ────────────────────────────────── -->
        <Style TargetType="TextBox">
            <Setter Property="Background"      Value="#313244"/>
            <Setter Property="Foreground"      Value="#CDD6F4"/>
            <Setter Property="BorderBrush"     Value="#45475A"/>
            <Setter Property="BorderThickness" Value="1"/>
            <Setter Property="Padding"         Value="10,7"/>
            <Setter Property="FontSize"        Value="13"/>
            <Setter Property="CaretBrush"      Value="#CDD6F4"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="TextBox">
                        <Border Background="{TemplateBinding Background}"
                                BorderBrush="{TemplateBinding BorderBrush}"
                                BorderThickness="{TemplateBinding BorderThickness}"
                                CornerRadius="8"
                                Padding="{TemplateBinding Padding}">
                            <ScrollViewer x:Name="PART_ContentHost"
                                          VerticalAlignment="Center"/>
                        </Border>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>

        <!-- ── ScrollBar slim dark theme ───────────────────────── -->
        <Style TargetType="ScrollBar">
            <Setter Property="Width"      Value="6"/>
            <Setter Property="Background" Value="Transparent"/>
        </Style>

    </Window.Resources>

    <!-- ════════════════  MAIN LAYOUT  ═════════════════════════════════ -->
    <Grid Margin="24,22,24,22">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>  <!-- header          -->
            <RowDefinition Height="12"/>    <!-- spacer          -->
            <RowDefinition Height="Auto"/>  <!-- search          -->
            <RowDefinition Height="8"/>     <!-- spacer          -->
            <RowDefinition Height="Auto"/>  <!-- select-all row  -->
            <RowDefinition Height="6"/>     <!-- spacer          -->
            <RowDefinition Height="200"/>   <!-- views list      -->
            <RowDefinition Height="14"/>    <!-- spacer          -->
            <RowDefinition Height="Auto"/>  <!-- delete options  -->
            <RowDefinition Height="18"/>    <!-- spacer          -->
            <RowDefinition Height="Auto"/>  <!-- buttons         -->
        </Grid.RowDefinitions>

        <!-- ── Header ─────────────────────────────────────────── -->
        <StackPanel Grid.Row="0">
            <TextBlock Text="Reset FLS Area Plans"
                       FontSize="19" FontWeight="Bold" Foreground="#CDD6F4"/>
            <TextBlock Text="Select views, choose what to remove, then confirm."
                       FontSize="12" Foreground="#A6ADC8" Margin="0,5,0,0"/>
        </StackPanel>

        <!-- ── Search bar ─────────────────────────────────────── -->
        <TextBox x:Name="SearchBox" Grid.Row="2" Height="36"
                 VerticalContentAlignment="Center"/>

        <!-- ── Select-all checkbox ────────────────────────────── -->
        <CheckBox x:Name="ChkSelectAll" Grid.Row="4"
                  Content="Select / Deselect All"
                  Foreground="#A6ADC8" FontSize="12"
                  Margin="4,0,0,0"/>

        <!-- ── Views list ─────────────────────────────────────── -->
        <Border Grid.Row="6" Background="#2A2A3C" CornerRadius="10" Padding="8,6">
            <ScrollViewer VerticalScrollBarVisibility="Auto">
                <StackPanel x:Name="ViewsPanel" Margin="4,4,4,4"/>
            </ScrollViewer>
        </Border>

        <!-- ── Deletion options card ──────────────────────────── -->
        <Border Grid.Row="8" Background="#2A2A3C" CornerRadius="10" Padding="16,14">
            <StackPanel>
                <TextBlock Text="Elements to delete from selected views:"
                           Foreground="#A6ADC8" FontSize="12" Margin="0,0,0,10"/>
                <CheckBox x:Name="ChkAreas"
                          Content="  Area Elements  (area tags will also be removed)"/>
                <CheckBox x:Name="ChkBoundaries"
                          Content="  Area Boundary Lines"
                          Margin="0,8,0,0"/>
            </StackPanel>
        </Border>

        <!-- ── Action buttons ─────────────────────────────────── -->
        <StackPanel Grid.Row="10" Orientation="Horizontal" HorizontalAlignment="Right">
            <Button x:Name="BtnCancel"
                    Content="Cancel"
                    Style="{StaticResource MutedBtn}"
                    Margin="0,0,10,0"/>
            <Button x:Name="BtnReset"
                    Content="Reset Selected"
                    Style="{StaticResource DangerBtn}"/>
        </StackPanel>

    </Grid>
</Window>
"""


# ─────────────────────────────────────────────────────────────────────────────
# Data collection
# ─────────────────────────────────────────────────────────────────────────────

def collect_fls_area_plans():
    """Return (list[ViewPlan], AreaScheme) for the 'FLS' scheme, or ([], None)."""
    fls_scheme = None
    for scheme in FilteredElementCollector(doc).OfClass(AreaScheme):
        if scheme.Name == "FLS":
            fls_scheme = scheme
            break

    if fls_scheme is None:
        return [], None

    plans = []
    for view in FilteredElementCollector(doc).OfClass(ViewPlan):
        if view.IsTemplate:
            continue
        try:
            if view.AreaScheme is not None and view.AreaScheme.Id == fls_scheme.Id:
                plans.append(view)
        except Exception:
            pass

    return sorted(plans, key=lambda v: v.Name), fls_scheme


# ─────────────────────────────────────────────────────────────────────────────
# WPF window
# ─────────────────────────────────────────────────────────────────────────────

class ResetFLSWindow(object):
    """WPF dialog for selecting views and deletion options."""

    def __init__(self, all_views):
        self._all_views = all_views       # full sorted list of ViewPlan
        self._guard     = [False]         # mutable flag – avoids re-entrant SelectAll sync

        # public results (set only when user confirms)
        self.result            = False
        self.selected_views    = []
        self.delete_areas      = False
        self.delete_boundaries = False

        self.window = XamlReader.Parse(XAML)
        self._bind_controls()
        self._populate(self._all_views)
        self._wire_events()

    # ── setup ─────────────────────────────────────────────────────────────────

    def _bind_controls(self):
        find = self.window.FindName
        self.search_box      = find("SearchBox")
        self.chk_select_all  = find("ChkSelectAll")
        self.views_panel     = find("ViewsPanel")
        self.chk_areas       = find("ChkAreas")
        self.chk_boundaries  = find("ChkBoundaries")
        self.btn_reset       = find("BtnReset")
        self.btn_cancel      = find("BtnCancel")

    def _wire_events(self):
        self.search_box.TextChanged       += self._on_search
        self.chk_select_all.Checked       += self._on_select_all_checked
        self.chk_select_all.Unchecked     += self._on_select_all_unchecked
        self.btn_reset.Click              += self._on_reset_click
        self.btn_cancel.Click             += self._on_cancel_click

    # ── view list helpers ──────────────────────────────────────────────────────

    def _make_checkbox(self, view):
        cb          = CheckBox()
        cb.Content  = view.Name
        cb.Tag      = view
        cb.Margin   = Thickness(2, 3, 2, 3)
        cb.Checked   += self._on_item_toggled
        cb.Unchecked += self._on_item_toggled
        return cb

    def _populate(self, views):
        self.views_panel.Children.Clear()
        for v in views:
            self.views_panel.Children.Add(self._make_checkbox(v))
        self._sync_select_all_state()

    def _visible_checkboxes(self):
        return list(self.views_panel.Children)

    # ── event handlers ────────────────────────────────────────────────────────

    def _on_search(self, sender, e):
        text     = self.search_box.Text.strip().lower()
        filtered = [v for v in self._all_views if text in v.Name.lower()]
        self._populate(filtered)

    def _on_select_all_checked(self, sender, e):
        if self._guard[0]:
            return
        for cb in self._visible_checkboxes():
            cb.IsChecked = True

    def _on_select_all_unchecked(self, sender, e):
        if self._guard[0]:
            return
        for cb in self._visible_checkboxes():
            cb.IsChecked = False

    def _on_item_toggled(self, sender, e):
        self._sync_select_all_state()

    def _sync_select_all_state(self):
        children = self._visible_checkboxes()
        if not children:
            self._guard[0] = True
            self.chk_select_all.IsChecked = False
            self._guard[0] = False
            return
        all_on  = all(cb.IsChecked == True  for cb in children)
        self._guard[0] = True
        self.chk_select_all.IsChecked = all_on
        self._guard[0] = False

    def _checked_views(self):
        return [cb.Tag for cb in self._visible_checkboxes() if cb.IsChecked == True]

    # ── reset button ──────────────────────────────────────────────────────────

    def _on_reset_click(self, sender, e):
        checked    = self._checked_views()
        del_areas  = self.chk_areas.IsChecked      == True
        del_bounds = self.chk_boundaries.IsChecked == True

        # ── validation
        if not checked:
            MessageBox.Show(
                "Please select at least one view from the list.",
                "No Views Selected",
                MessageBoxButton.OK
            )
            return

        if not del_areas and not del_bounds:
            MessageBox.Show(
                "Please tick at least one deletion option:\n"
                "  \u2022 Area Elements\n"
                "  \u2022 Area Boundary Lines",
                "Nothing to Delete",
                MessageBoxButton.OK
            )
            return

        # ── confirmation message
        lines = [
            "The following will be permanently deleted:\n",
        ]
        if del_areas:
            lines.append("  \u2022 Area Elements  (and their tags)")
        if del_bounds:
            lines.append("  \u2022 Area Boundary Lines")
        lines.append(
            "\nFrom {:d} selected view(s):".format(len(checked))
        )
        for v in checked:
            lines.append("    \u2013 {}".format(v.Name))
        lines.append("\n\u26A0  This action cannot be undone.  Continue?")

        confirm = MessageBox.Show(
            "\n".join(lines),
            "Confirm Reset",
            MessageBoxButton.YesNo
        )

        if confirm == MessageBoxResult.Yes:
            self.selected_views    = checked
            self.delete_areas      = del_areas
            self.delete_boundaries = del_bounds
            self.result            = True
            self.window.Close()

    def _on_cancel_click(self, sender, e):
        self.window.Close()

    # ── entry point ───────────────────────────────────────────────────────────

    def show(self):
        self.window.ShowDialog()
        return self.result


# ─────────────────────────────────────────────────────────────────────────────
# Deletion logic
# ─────────────────────────────────────────────────────────────────────────────

def execute_reset(views, delete_areas, delete_boundaries):
    """
    Delete area elements and/or boundary lines from the given views.
    Uses a single transaction; tracks deleted IDs to avoid double-deletion
    when elements appear in multiple views.
    Returns (n_areas_deleted, n_bounds_deleted).
    """
    n_areas  = 0
    n_bounds = 0
    seen     = set()   # ElementId objects already deleted this session

    with revit.Transaction("Reset FLS Area Plans"):
        for view in views:
            view_id = view.Id

            # ── Area Elements ────────────────────────────────────────────────
            if delete_areas:
                area_elems = (
                    FilteredElementCollector(doc, view_id)
                    .OfCategory(BuiltInCategory.OST_Areas)
                    .ToElements()
                )
                for el in area_elems:
                    eid = el.Id
                    if eid in seen:
                        continue
                    try:
                        doc.Delete(eid)
                        seen.add(eid)
                        n_areas += 1
                    except Exception:
                        pass

            # ── Area Boundary Lines ──────────────────────────────────────────
            if delete_boundaries:
                bound_elems = (
                    FilteredElementCollector(doc, view_id)
                    .OfCategory(BuiltInCategory.OST_AreaSchemeLines)
                    .ToElements()
                )
                for el in bound_elems:
                    eid = el.Id
                    if eid in seen:
                        continue
                    try:
                        doc.Delete(eid)
                        seen.add(eid)
                        n_bounds += 1
                    except Exception:
                        pass

    return n_areas, n_bounds


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    # 1. Collect FLS area plans -----------------------------------------------
    plans, fls_scheme = collect_fls_area_plans()

    if not plans:
        MessageBox.Show(
            "No Area Plan views were found under the 'FLS' Area Scheme.\n\n"
            "Make sure the scheme is named exactly 'FLS' and that at least\n"
            "one Area Plan view has been created under it.",
            "FLS Area Plans Not Found",
            MessageBoxButton.OK
        )
        return

    # 2. Show UI ---------------------------------------------------------------
    win = ResetFLSWindow(plans)
    confirmed = win.show()

    if not confirmed:
        output.print_md("**Cancelled** – no changes were made.")
        return

    # 3. Execute ---------------------------------------------------------------
    n_areas, n_bounds = execute_reset(
        win.selected_views,
        win.delete_areas,
        win.delete_boundaries,
    )

    # 4. Report ----------------------------------------------------------------
    output.print_md("## Reset FLS Area Plans — Complete")
    output.print_md("**Views processed:** {:d}".format(len(win.selected_views)))
    if win.delete_areas:
        output.print_md("**Area elements deleted:** {:d}".format(n_areas))
    if win.delete_boundaries:
        output.print_md("**Boundary lines deleted:** {:d}".format(n_bounds))

    MessageBox.Show(
        "Reset complete!\n\n"
        + ("  \u2022 {:d} Area element(s) deleted\n".format(n_areas) if win.delete_areas else "")
        + ("  \u2022 {:d} Boundary line(s) deleted\n".format(n_bounds) if win.delete_boundaries else ""),
        "Done",
        MessageBoxButton.OK
    )


# ── run ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    main()
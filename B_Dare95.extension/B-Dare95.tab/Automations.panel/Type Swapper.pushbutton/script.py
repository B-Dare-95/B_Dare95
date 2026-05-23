# -*- coding: utf-8 -*-
__title__   = "Type\nSwapper"
__doc__     = (
    "Bulk-swap family types across the project by category.\n\n"
    "1. Select a category from the left panel.\n"
    "2. Build swap pairs: pick a FROM type (in use) and a TO type (any loaded).\n"
    "3. Add more rows with '+ Add Row'.\n"
    "4. Click CONFIRM SWAP to apply all changes in a single transaction."
)

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('System')
clr.AddReference('System.Xml')
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')

from Autodesk.Revit.DB import (
    FilteredElementCollector, CategoryType, ElementId, Transaction
)

from pyrevit import DB


from pyrevit import revit
from System.Windows.Markup import XamlReader
from System.Windows.Controls import (
    ComboBox, ComboBoxItem, Grid, ColumnDefinition, ListBoxItem, TextBlock
)
from System.Windows import (
    GridLength, Thickness,
    HorizontalAlignment, VerticalAlignment, Visibility
)
from System.Windows.Media import SolidColorBrush, Color
import System

doc = revit.doc

# ══════════════════════════════════════════════════════════════════════════════
#  Color / brush helpers
# ══════════════════════════════════════════════════════════════════════════════

def _b(h):
    """Create a SolidColorBrush from a hex colour string."""
    h = h.lstrip('#')
    return SolidColorBrush(Color.FromRgb(
        System.Byte(int(h[0:2], 16)),
        System.Byte(int(h[2:4], 16)),
        System.Byte(int(h[4:6], 16))
    ))

# ══════════════════════════════════════════════════════════════════════════════
#  Revit data helpers
# ══════════════════════════════════════════════════════════════════════════════

def _get_categories():
    """Return sorted [(name, CategoryId)] for all model categories that have placed instances."""
    seen = {}
    for el in FilteredElementCollector(doc).WhereElementIsNotElementType():
        cat = el.Category
        if cat is None:
            continue
        try:
            if cat.CategoryType != CategoryType.Model:
                continue
        except Exception:
            continue
        n = cat.Name
        if n and n not in seen:
            seen[n] = cat.Id
    return sorted(seen.items(), key=lambda kv: kv[0].lower())


def _in_use_types(cat_id):
    """Return sorted [(display_name, ElementId)] for types with at least one placed instance."""
    instances = (
        FilteredElementCollector(doc)
        .OfCategoryId(cat_id)
        .WhereElementIsNotElementType()
        .ToElements()
    )
    tid_set = set()
    for inst in instances:
        tid = inst.GetTypeId()
        if tid is not None and tid != ElementId.InvalidElementId:
            tid_set.add(tid)

    result = []
    for tid in tid_set:
        el = doc.GetElement(tid)
        if el is None:
            continue
        fname = ''
        try:
            fname = el.FamilyName or ''
        except Exception:
            pass
        tname = DB.Element.Name.__get__(el) or '(unnamed)'
        disp  = u'{} : {}'.format(fname, tname) if fname else tname
        result.append((disp, tid))
    return sorted(result, key=lambda x: x[0].lower())


def _all_types(cat_id):
    """Return sorted [(display_name, ElementId)] for every type loaded for this category."""
    result = []
    for t in (
        FilteredElementCollector(doc)
        .OfCategoryId(cat_id)
        .WhereElementIsElementType()
        .ToElements()
    ):
        fname = ''
        try:
            fname = t.FamilyName or ''
        except Exception:
            pass
        tname = DB.Element.Name.__get__(t) or '(unnamed)'
        disp  = u'{} : {}'.format(fname, tname) if fname else tname
        result.append((disp, t.Id))
    return sorted(result, key=lambda x: x[0].lower())

# ══════════════════════════════════════════════════════════════════════════════
#  XAML  –  main window skeleton
# ══════════════════════════════════════════════════════════════════════════════

WINDOW_XAML = u"""
<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Type Swapper \u2014 Bulk Family Type Replacement"
    Height="660" Width="1000"
    MinHeight="520" MinWidth="740"
    WindowStartupLocation="CenterScreen"
    ResizeMode="CanResizeWithGrip"
    Background="#1E1E2E">

  <Grid Margin="16">
    <Grid.ColumnDefinitions>
      <ColumnDefinition Width="230"/>
      <ColumnDefinition Width="12"/>
      <ColumnDefinition Width="*"/>
    </Grid.ColumnDefinitions>

    <!-- ═══════════════════════════  LEFT  ═══════════════════════════ -->
    <Border Grid.Column="0" Background="#2A2A3C" CornerRadius="9" Padding="12">
      <DockPanel>

        <!-- Section label -->
        <TextBlock DockPanel.Dock="Top"
            Text="CATEGORY"
            Foreground="#F0A500" FontSize="10" FontWeight="Bold"
            Margin="2,0,0,8"/>

        <!-- Search box -->
        <TextBox DockPanel.Dock="Top" x:Name="SearchBox"
            Background="#313244" Foreground="#CDD6F4" CaretBrush="#CDD6F4"
            BorderBrush="#45475A" BorderThickness="1"
            Padding="8,6" Margin="0,0,0,6" FontSize="12"/>

        <!-- Category list -->
        <ListBox x:Name="CategoryList"
            Background="Transparent" BorderThickness="0"
            Foreground="#CDD6F4" FontSize="12"
            HorizontalContentAlignment="Stretch"
            ScrollViewer.HorizontalScrollBarVisibility="Disabled">
          <ListBox.ItemContainerStyle>
            <Style TargetType="ListBoxItem">
              <Setter Property="Padding" Value="8,5"/>
              <Setter Property="Margin"  Value="0,1"/>
              <Setter Property="Foreground" Value="#CDD6F4"/>
              <Setter Property="Template">
                <Setter.Value>
                  <ControlTemplate TargetType="ListBoxItem">
                    <Border x:Name="Bd" Background="Transparent"
                        CornerRadius="6" Padding="{TemplateBinding Padding}">
                      <ContentPresenter/>
                    </Border>
                    <ControlTemplate.Triggers>
                      <Trigger Property="IsSelected" Value="True">
                        <Setter TargetName="Bd" Property="Background" Value="#F0A500"/>
                        <Setter Property="Foreground" Value="#1E1E2E"/>
                      </Trigger>
                      <MultiTrigger>
                        <MultiTrigger.Conditions>
                          <Condition Property="IsMouseOver" Value="True"/>
                          <Condition Property="IsSelected"  Value="False"/>
                        </MultiTrigger.Conditions>
                        <Setter TargetName="Bd" Property="Background" Value="#3D3D55"/>
                      </MultiTrigger>
                    </ControlTemplate.Triggers>
                  </ControlTemplate>
                </Setter.Value>
              </Setter>
            </Style>
          </ListBox.ItemContainerStyle>
        </ListBox>

      </DockPanel>
    </Border>

    <!-- ═══════════════════════════  RIGHT  ═══════════════════════════ -->
    <Border Grid.Column="2" Background="#2A2A3C" CornerRadius="9" Padding="16,14">
      <Grid>
        <Grid.RowDefinitions>
          <RowDefinition Height="Auto"/>   <!-- column headers  -->
          <RowDefinition Height="Auto"/>   <!-- separator       -->
          <RowDefinition Height="*"/>      <!-- rows / hint     -->
          <RowDefinition Height="Auto"/>   <!-- confirm bar     -->
        </Grid.RowDefinitions>

        <!-- Column headers + Add Row button -->
        <Grid Grid.Row="0" Margin="0,0,0,8">
          <Grid.ColumnDefinitions>
            <ColumnDefinition Width="*"/>
            <ColumnDefinition Width="36"/>
            <ColumnDefinition Width="*"/>
            <ColumnDefinition Width="90"/>
          </Grid.ColumnDefinitions>

          <StackPanel Grid.Column="0" Orientation="Horizontal" VerticalAlignment="Center">
            <TextBlock Text="FROM TYPE" Foreground="#A6ADC8"
                FontSize="10" FontWeight="Bold" VerticalAlignment="Center"/>
            <TextBlock Text="  (instances present)" Foreground="#585B70"
                FontSize="10" VerticalAlignment="Center"/>
          </StackPanel>

          <StackPanel Grid.Column="2" Orientation="Horizontal" VerticalAlignment="Center">
            <TextBlock Text="TO TYPE" Foreground="#A6ADC8"
                FontSize="10" FontWeight="Bold" VerticalAlignment="Center"/>
            <TextBlock Text="  (any loaded type)" Foreground="#585B70"
                FontSize="10" VerticalAlignment="Center"/>
          </StackPanel>

          <Button Grid.Column="3" x:Name="AddRowBtn"
              Content="&#xFF0B;  Add Row"
              Foreground="#CDD6F4" FontSize="11"
              Cursor="Hand" IsEnabled="False" HorizontalAlignment="Right">
            <Button.Template>
              <ControlTemplate TargetType="Button">
                <Border x:Name="ABd" Background="#313244"
                    CornerRadius="6" Padding="10,5">
                  <ContentPresenter HorizontalAlignment="Center"
                                    VerticalAlignment="Center"/>
                </Border>
                <ControlTemplate.Triggers>
                  <Trigger Property="IsEnabled" Value="False">
                    <Setter TargetName="ABd" Property="Background" Value="#252535"/>
                    <Setter Property="Foreground" Value="#45475A"/>
                  </Trigger>
                  <Trigger Property="IsMouseOver" Value="True">
                    <Setter TargetName="ABd" Property="Background" Value="#45475A"/>
                  </Trigger>
                </ControlTemplate.Triggers>
              </ControlTemplate>
            </Button.Template>
          </Button>
        </Grid>

        <Separator Grid.Row="1" Background="#3D3D55" Margin="0,0,0,10"/>

        <!-- Hint  OR  scrollable rows -->
        <Grid Grid.Row="2">
          <TextBlock x:Name="HintLabel"
              Text="&#8592; Select a category to start building swap pairs"
              Foreground="#585B70" FontSize="13"
              HorizontalAlignment="Center" VerticalAlignment="Center"/>

          <ScrollViewer x:Name="RowsScroll"
              VerticalScrollBarVisibility="Auto"
              HorizontalScrollBarVisibility="Disabled"
              Visibility="Collapsed">
            <StackPanel x:Name="RowsPanel" Margin="0,2,4,2"/>
          </ScrollViewer>
        </Grid>

        <!-- Confirm bar -->
        <Grid Grid.Row="3" Margin="0,10,0,0">
          <Grid.ColumnDefinitions>
            <ColumnDefinition Width="*"/>
            <ColumnDefinition Width="Auto"/>
          </Grid.ColumnDefinitions>
          <TextBlock x:Name="StatusLabel" Grid.Column="0"
              Foreground="#A6ADC8" FontSize="11"
              VerticalAlignment="Center"
              TextWrapping="Wrap" Margin="2,0,12,0"/>
          <Button x:Name="ConfirmBtn" Grid.Column="1"
              Content="CONFIRM SWAP"
              Foreground="#1E1E2E"
              FontSize="13" FontWeight="Bold"
              Cursor="Hand" IsEnabled="False">
            <Button.Template>
              <ControlTemplate TargetType="Button">
                <Border x:Name="CBd" Background="#F0A500"
                    CornerRadius="9" Padding="22,10">
                  <ContentPresenter HorizontalAlignment="Center"
                                    VerticalAlignment="Center"/>
                </Border>
                <ControlTemplate.Triggers>
                  <Trigger Property="IsEnabled" Value="False">
                    <Setter TargetName="CBd" Property="Background" Value="#45475A"/>
                    <Setter Property="Foreground" Value="#585B70"/>
                  </Trigger>
                  <Trigger Property="IsMouseOver" Value="True">
                    <Setter TargetName="CBd" Property="Background" Value="#FFB800"/>
                  </Trigger>
                </ControlTemplate.Triggers>
              </ControlTemplate>
            </Button.Template>
          </Button>
        </Grid>

      </Grid>
    </Border>

  </Grid>
</Window>
"""

# ── Remove-button XAML  (parsed once per added row, no .format() needed) ─────
_RM_BTN_XAML = u"""
<Button
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Content="\u2212"
    Background="#45475A"
    Foreground="#CDD6F4"
    BorderThickness="0"
    Width="28"
    Height="28"
    FontSize="15"
    Cursor="Hand"
    VerticalAlignment="Center">

  <Button.Template>
    <ControlTemplate TargetType="Button">
      <Border x:Name="RBd"
              Background="{TemplateBinding Background}"
              CornerRadius="6"
              Padding="2">

        <ContentPresenter HorizontalAlignment="Center"
                          VerticalAlignment="Center"/>
      </Border>

      <ControlTemplate.Triggers>
        <Trigger Property="IsMouseOver" Value="True">
          <Setter TargetName="RBd"
                  Property="Background"
                  Value="#585B70"/>
        </Trigger>
      </ControlTemplate.Triggers>

    </ControlTemplate>
  </Button.Template>
</Button>
"""

# ══════════════════════════════════════════════════════════════════════════════
#  Build window
# ══════════════════════════════════════════════════════════════════════════════

win = XamlReader.Parse(WINDOW_XAML)

search_box   = win.FindName('SearchBox')
cat_list     = win.FindName('CategoryList')
add_row_btn  = win.FindName('AddRowBtn')
rows_panel   = win.FindName('RowsPanel')
rows_scroll  = win.FindName('RowsScroll')
hint_label   = win.FindName('HintLabel')
status_label = win.FindName('StatusLabel')
confirm_btn  = win.FindName('ConfirmBtn')

# ── Mutable state containers (IronPython 2.7 — no nonlocal) ──────────────────
all_cats      = _get_categories()   # [(name, CategoryId)]
current_cat   = [None]              # [CategoryId | None]
in_use_data   = [[]]                # [(disp, ElementId)]
all_type_data = [[]]                # [(disp, ElementId)]
rows          = []                  # [{'from_cb', 'to_cb', 'container'}]

# ══════════════════════════════════════════════════════════════════════════════
#  Category list
# ══════════════════════════════════════════════════════════════════════════════

def _refresh_cats(filt=''):
    cat_list.Items.Clear()
    filt = filt.lower()
    for name, cat_id in all_cats:
        if filt in name.lower():
            li = ListBoxItem()
            li.Content = name
            li.Tag     = cat_id
            cat_list.Items.Add(li)

_refresh_cats()

def _on_search(s, e):
    _refresh_cats(search_box.Text or '')

search_box.TextChanged += _on_search

# ══════════════════════════════════════════════════════════════════════════════
#  Row management
# ══════════════════════════════════════════════════════════════════════════════

def _make_combo(items, placeholder):
    """Build a styled ComboBox populated with (display_name, ElementId) pairs."""
    cb = ComboBox()
    cb.Background      = _b('#313244')
    cb.Foreground      = _b('#000000')
    cb.BorderBrush     = _b('#45475A')
    cb.BorderThickness = Thickness(1)
    cb.Padding         = Thickness(6, 4, 6, 4)
    cb.FontSize        = 12
    cb.Height          = 32

    ph            = ComboBoxItem()
    ph.Content    = placeholder
    ph.Foreground = _b('#585B70')
    ph.IsEnabled  = False
    cb.Items.Add(ph)
    cb.SelectedIndex = 0

    for disp, eid in items:
        ci         = ComboBoxItem()
        ci.Content = disp
        ci.Tag     = eid
        cb.Items.Add(ci)
    return cb


def _update_status():
    """Recalculate how many valid pairs exist and toggle the Confirm button."""
    valid = 0
    for r in rows:
        fs = r['from_cb'].SelectedItem
        ts = r['to_cb'].SelectedItem
        if (fs is not None and fs.Tag is not None and
                ts is not None and ts.Tag is not None):
            valid += 1

    confirm_btn.IsEnabled = (valid > 0)
    if valid > 0:
        status_label.Foreground = _b('#A6ADC8')
        status_label.Text = u'{} swap pair{} configured \u2014 ready to apply'.format(
            valid, 's' if valid != 1 else '')
    elif rows:
        status_label.Foreground = _b('#585B70')
        status_label.Text = u'Select FROM and TO types for each row'
    else:
        status_label.Text = u''


def _clear_rows():
    del rows[:]
    rows_panel.Children.Clear()
    hint_label.Visibility  = Visibility.Visible
    rows_scroll.Visibility = Visibility.Collapsed
    confirm_btn.IsEnabled  = False
    status_label.Text      = u''


def _add_row():
    """Append a new FROM → TO swap row to the panel."""
    g = Grid()
    g.Margin = Thickness(0, 0, 0, 6)

    # Columns: from(*) | arrow(36) | to(*) | remove(34)
    g.ColumnDefinitions.Add(ColumnDefinition())          # star — FROM combo
    cd_arrow = ColumnDefinition()
    cd_arrow.Width = GridLength(36)
    g.ColumnDefinitions.Add(cd_arrow)
    g.ColumnDefinitions.Add(ColumnDefinition())          # star — TO combo
    cd_rm = ColumnDefinition()
    cd_rm.Width = GridLength(34)
    g.ColumnDefinitions.Add(cd_rm)

    # FROM combo — only types with placed instances
    from_cb = _make_combo(in_use_data[0], u'  Select FROM type\u2026')
    Grid.SetColumn(from_cb, 0)
    g.Children.Add(from_cb)

    # Arrow label
    arrow = TextBlock()
    arrow.Text                = u'\u2192'
    arrow.Foreground          = _b('#000000')
    arrow.FontSize            = 18
    arrow.HorizontalAlignment = HorizontalAlignment.Center
    arrow.VerticalAlignment   = VerticalAlignment.Center
    Grid.SetColumn(arrow, 1)
    g.Children.Add(arrow)

    # TO combo — all loaded types for this category
    to_cb = _make_combo(all_type_data[0], u'  Select TO type\u2026')
    Grid.SetColumn(to_cb, 2)
    g.Children.Add(to_cb)

    # Remove (−) button
    rm_btn = XamlReader.Parse(_RM_BTN_XAML)
    rm_btn.Margin = Thickness(3, 0, 0, 0)
    Grid.SetColumn(rm_btn, 3)
    g.Children.Add(rm_btn)

    row_data = {'from_cb': from_cb, 'to_cb': to_cb, 'container': g}
    rows.append(row_data)
    rows_panel.Children.Add(g)

    # Wire remove button (default-arg capture for IronPython 2.7 closure)
    def _on_rm(s, e, rd=row_data):
        rows.remove(rd)
        rows_panel.Children.Remove(rd['container'])
        if not rows:
            hint_label.Visibility  = Visibility.Visible
            rows_scroll.Visibility = Visibility.Collapsed
        _update_status()

    rm_btn.Click             += _on_rm
    from_cb.SelectionChanged += lambda s, e: _update_status()
    to_cb.SelectionChanged   += lambda s, e: _update_status()

    hint_label.Visibility  = Visibility.Collapsed
    rows_scroll.Visibility = Visibility.Visible
    _update_status()

# ══════════════════════════════════════════════════════════════════════════════
#  Category selection handler
# ══════════════════════════════════════════════════════════════════════════════

def _on_cat_selected(s, e):
    sel = cat_list.SelectedItem
    if sel is None:
        return
    cat_id = sel.Tag
    current_cat[0] = cat_id

    in_use_data[0]   = _in_use_types(cat_id)
    all_type_data[0] = _all_types(cat_id)

    _clear_rows()

    if not in_use_data[0]:
        add_row_btn.IsEnabled = False
        hint_label.Text = (
            u'\u2190 No placed instances found for this category.\n'
            u'Select a different category.'
        )
        return

    if not all_type_data[0]:
        add_row_btn.IsEnabled = False
        hint_label.Text = u'\u2190 No types loaded for this category.'
        return

    add_row_btn.IsEnabled = True
    status_label.Foreground = _b('#585B70')
    status_label.Text = u'{} type{} in use  \u00b7  {} type{} available'.format(
        len(in_use_data[0]),   's' if len(in_use_data[0])   != 1 else '',
        len(all_type_data[0]), 's' if len(all_type_data[0]) != 1 else '',
    )
    _add_row()   # auto-add first row

cat_list.SelectionChanged += _on_cat_selected
add_row_btn.Click         += lambda s, e: _add_row()

# ══════════════════════════════════════════════════════════════════════════════
#  Confirm / swap
# ══════════════════════════════════════════════════════════════════════════════

def _on_confirm(s, e):
    cat_id = current_cat[0]
    if cat_id is None:
        return

    # Build swap map  {from_ElementId -> to_ElementId}
    # If the same FROM appears in multiple rows, the last definition wins.
    swap_map = {}
    for r in rows:
        fs = r['from_cb'].SelectedItem
        ts = r['to_cb'].SelectedItem
        if fs is None or fs.Tag is None or ts is None or ts.Tag is None:
            continue
        fid = fs.Tag
        tid = ts.Tag
        if fid != tid:
            swap_map[fid] = tid

    if not swap_map:
        status_label.Foreground = _b('#F38BA8')
        status_label.Text = u'\u26A0  No valid swap pairs \u2014 check your selections.'
        return

    # Collect every instance of the target category
    all_inst = (
        FilteredElementCollector(doc)
        .OfCategoryId(cat_id)
        .WhereElementIsNotElementType()
        .ToElements()
    )

    # Snapshot which elements need to change BEFORE executing any changes
    to_change = []
    for inst in all_inst:
        inst_tid = inst.GetTypeId()
        if inst_tid is None or inst_tid == ElementId.InvalidElementId:
            continue
        if inst_tid in swap_map:
            to_change.append((inst, swap_map[inst_tid]))

    if not to_change:
        status_label.Foreground = _b('#F38BA8')
        status_label.Text = u'\u26A0  No instances matched the selected FROM types.'
        return

    changed = [0]
    failed  = [0]

    t = Transaction(doc, u'Type Swapper \u2014 Bulk Swap')
    t.Start()
    try:
        for inst, new_tid in to_change:
            try:
                inst.ChangeTypeId(new_tid)
                changed[0] += 1
            except Exception:
                failed[0] += 1
        t.Commit()
    except Exception as ex:
        t.RollBack()
        status_label.Foreground = _b('#F38BA8')
        status_label.Text = u'\u274C  Transaction failed: {}'.format(str(ex))
        return

    # Report result
    if failed[0] == 0:
        status_label.Foreground = _b('#A6E3A1')
        status_label.Text = u'\u2713  {} element{} swapped successfully.'.format(
            changed[0], 's' if changed[0] != 1 else '')
    else:
        status_label.Foreground = _b('#F9E2AF')
        status_label.Text = u'\u26A0  {} swapped, {} could not be changed.'.format(
            changed[0], failed[0])

confirm_btn.Click += _on_confirm

# ══════════════════════════════════════════════════════════════════════════════
#  Launch
# ══════════════════════════════════════════════════════════════════════════════
win.ShowDialog()
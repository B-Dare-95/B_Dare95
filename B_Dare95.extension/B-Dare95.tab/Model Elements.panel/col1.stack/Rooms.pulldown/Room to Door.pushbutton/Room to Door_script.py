# -*- coding: utf-8 -*-
"""
Room → Door Parameter Transfer
Transfers parameter values from room (ToRoom/FromRoom) to door parameters.
Supports single-param and combine (multi-param with separator) modes.
Supports designator suffixes for doors sharing the same room, with per-level reset.
"""

import clr
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')
clr.AddReference('System.Xml')

from Autodesk.Revit.DB import *
import System
from System.Collections.Generic import List
from System.Windows.Markup import XamlReader
from System.Windows import Window, MessageBox, MessageBoxButton, MessageBoxResult
from System.Windows.Controls import ListBoxItem
from collections import defaultdict

app   = __revit__.Application
doc   = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def collect_parameters_for_category(bic):
    """Return sorted unique parameter names (instance + type) for a given BuiltInCategory."""
    instances = (FilteredElementCollector(doc)
                 .OfCategory(bic)
                 .WhereElementIsNotElementType()
                 .ToElements())
    names = set()
    seen_type_ids = set()
    for el in instances:
        for p in el.Parameters:
            if p.Definition and p.StorageType != StorageType.None:
                names.add(p.Definition.Name)
        type_id = el.GetTypeId()
        if type_id is not None and type_id not in seen_type_ids:
            seen_type_ids.add(type_id)
            el_type = doc.GetElement(type_id)
            if el_type is not None:
                for p in el_type.Parameters:
                    if p.Definition and p.StorageType != StorageType.None:
                        names.add(p.Definition.Name)
    return sorted(names, key=lambda x: x.lower())


def get_param_value_as_string(element, param_name):
    p = element.LookupParameter(param_name)
    if p is None or not p.HasValue:
        return ""
    st = p.StorageType
    if st == StorageType.String:
        v = p.AsString()
        return v if v is not None else ""
    elif st == StorageType.Integer:
        return str(p.AsInteger())
    elif st == StorageType.Double:
        return p.AsValueString() or str(p.AsDouble())
    elif st == StorageType.ElementId:
        eid = p.AsElementId()
        return str(eid.Value if hasattr(eid, 'Value') else eid.IntegerValue)
    return ""


def set_param_value(element, param_name, value):
    p = element.LookupParameter(param_name)
    if p is None or p.IsReadOnly:
        return False
    try:
        if p.StorageType == StorageType.String:
            p.Set(value)
        else:
            p.SetValueString(value)
        return True
    except Exception:
        return False


def get_element_id_int(element):
    eid = element.Id
    return eid.Value if hasattr(eid, 'Value') else eid.IntegerValue


def to_alpha_designator(rank):
    """0→A, 1→B, …, 25→Z, 26→AA, 27→AB, …"""
    if rank < 26:
        return chr(ord('A') + rank)
    return chr(ord('A') + rank // 26 - 1) + chr(ord('A') + rank % 26)


def get_last_phase():
    phases = doc.Phases
    return phases[phases.Size - 1]


# ──────────────────────────────────────────────
# XAML
# ──────────────────────────────────────────────

XAML = """
<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Room to Door Parameter Transfer"
    Width="880" Height="720"
    MinWidth="720" MinHeight="580"
    WindowStartupLocation="CenterScreen"
    Background="#1E1E2E"
    Foreground="#CDD6F4"
    FontFamily="Segoe UI"
    FontSize="13">

  <Window.Resources>

    <Style TargetType="ScrollBar">
      <Setter Property="Background" Value="#2A2A3C"/>
      <Setter Property="Foreground" Value="#45475A"/>
      <Setter Property="Width" Value="6"/>
    </Style>

    <Style TargetType="TextBox">
      <Setter Property="Background" Value="#313244"/>
      <Setter Property="Foreground" Value="#CDD6F4"/>
      <Setter Property="BorderBrush" Value="#45475A"/>
      <Setter Property="BorderThickness" Value="1"/>
      <Setter Property="Padding" Value="6,4"/>
      <Setter Property="CaretBrush" Value="#F0A500"/>
    </Style>

    <Style TargetType="ListBox">
      <Setter Property="Background" Value="#313244"/>
      <Setter Property="Foreground" Value="#CDD6F4"/>
      <Setter Property="BorderBrush" Value="#45475A"/>
      <Setter Property="BorderThickness" Value="1"/>
      <Setter Property="ScrollViewer.HorizontalScrollBarVisibility" Value="Disabled"/>
    </Style>
    <Style TargetType="ListBoxItem">
      <Setter Property="Padding" Value="8,4"/>
      <Setter Property="Foreground" Value="#CDD6F4"/>
      <Setter Property="Background" Value="Transparent"/>
      <Style.Triggers>
        <Trigger Property="IsSelected" Value="True">
          <Setter Property="Background" Value="#F0A500"/>
          <Setter Property="Foreground" Value="#1E1E2E"/>
        </Trigger>
        <Trigger Property="IsMouseOver" Value="True">
          <Setter Property="Background" Value="#45475A"/>
        </Trigger>
      </Style.Triggers>
    </Style>

    <Style TargetType="Button">
      <Setter Property="Background" Value="#45475A"/>
      <Setter Property="Foreground" Value="#CDD6F4"/>
      <Setter Property="BorderThickness" Value="0"/>
      <Setter Property="Padding" Value="14,6"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border Background="{TemplateBinding Background}"
                    CornerRadius="6"
                    Padding="{TemplateBinding Padding}">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter Property="Background" Value="#585B70"/>
              </Trigger>
              <Trigger Property="IsPressed" Value="True">
                <Setter Property="Background" Value="#F0A500"/>
                <Setter Property="Foreground" Value="#1E1E2E"/>
              </Trigger>
              <Trigger Property="IsEnabled" Value="False">
                <Setter Property="Opacity" Value="0.4"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="AccentButton" TargetType="Button" BasedOn="{StaticResource {x:Type Button}}">
      <Setter Property="Background" Value="#F0A500"/>
      <Setter Property="Foreground" Value="#1E1E2E"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
      <Style.Triggers>
        <Trigger Property="IsMouseOver" Value="True">
          <Setter Property="Background" Value="#FFB833"/>
        </Trigger>
        <Trigger Property="IsPressed" Value="True">
          <Setter Property="Background" Value="#CC8C00"/>
        </Trigger>
      </Style.Triggers>
    </Style>

    <Style x:Key="ToggleBtn" TargetType="RadioButton">
      <Setter Property="Background" Value="#45475A"/>
      <Setter Property="Foreground" Value="#A6ADC8"/>
      <Setter Property="BorderThickness" Value="0"/>
      <Setter Property="Padding" Value="18,7"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="RadioButton">
            <Border Background="{TemplateBinding Background}"
                    CornerRadius="9"
                    Padding="{TemplateBinding Padding}">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsChecked" Value="True">
                <Setter Property="Background" Value="#F0A500"/>
                <Setter Property="Foreground" Value="#1E1E2E"/>
              </Trigger>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter Property="Background" Value="#585B70"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="ModeBtn" TargetType="RadioButton" BasedOn="{StaticResource ToggleBtn}">
      <Setter Property="Padding" Value="14,6"/>
      <Setter Property="FontSize" Value="12"/>
    </Style>

    <Style x:Key="IconBtn" TargetType="Button">
      <Setter Property="Background" Value="#45475A"/>
      <Setter Property="Foreground" Value="#CDD6F4"/>
      <Setter Property="BorderThickness" Value="0"/>
      <Setter Property="Width" Value="28"/>
      <Setter Property="Height" Value="28"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="FontSize" Value="14"/>
      <Setter Property="Padding" Value="0"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border Background="{TemplateBinding Background}"
                    CornerRadius="6"
                    Padding="{TemplateBinding Padding}">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter Property="Background" Value="#585B70"/>
              </Trigger>
              <Trigger Property="IsPressed" Value="True">
                <Setter Property="Background" Value="#F0A500"/>
                <Setter Property="Foreground" Value="#1E1E2E"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <!-- CheckBox style -->
    <Style TargetType="CheckBox">
      <Setter Property="Foreground" Value="#CDD6F4"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="VerticalContentAlignment" Value="Center"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="CheckBox">
            <StackPanel Orientation="Horizontal">
              <Border x:Name="box" Width="16" Height="16" CornerRadius="4"
                      Background="#313244" BorderBrush="#45475A" BorderThickness="1.5"
                      VerticalAlignment="Center">
                <TextBlock x:Name="tick" Text="✓" FontSize="11" FontWeight="Bold"
                           Foreground="#1E1E2E" HorizontalAlignment="Center"
                           VerticalAlignment="Center" Visibility="Collapsed"/>
              </Border>
              <ContentPresenter Margin="8,0,0,0" VerticalAlignment="Center"/>
            </StackPanel>
            <ControlTemplate.Triggers>
              <Trigger Property="IsChecked" Value="True">
                <Setter TargetName="box"  Property="Background"    Value="#F0A500"/>
                <Setter TargetName="box"  Property="BorderBrush"   Value="#F0A500"/>
                <Setter TargetName="tick" Property="Visibility"     Value="Visible"/>
              </Trigger>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="box" Property="BorderBrush" Value="#F0A500"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

  </Window.Resources>

  <Grid Margin="16">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>   <!-- 0 header -->
      <RowDefinition Height="Auto"/>   <!-- 1 toggles -->
      <RowDefinition Height="*"/>      <!-- 2 panels -->
      <RowDefinition Height="Auto"/>   <!-- 3 combine (collapsed) -->
      <RowDefinition Height="Auto"/>   <!-- 4 designator -->
      <RowDefinition Height="Auto"/>   <!-- 5 status + run -->
    </Grid.RowDefinitions>

    <!-- ── Row 0: Header ── -->
    <StackPanel Grid.Row="0" Margin="0,0,0,14">
      <TextBlock Text="Room to Door Parameter Transfer"
                 FontSize="18" FontWeight="SemiBold" Foreground="#F0A500"/>
      <TextBlock Text="Map room parameter values to door parameters via FromRoom / ToRoom"
                 Foreground="#A6ADC8" FontSize="11" Margin="0,2,0,0"/>
    </StackPanel>

    <!-- ── Row 1: Toggles ── -->
    <Grid Grid.Row="1" Margin="0,0,0,12">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="Auto"/>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="Auto"/>
      </Grid.ColumnDefinitions>

      <StackPanel Grid.Column="0" Orientation="Horizontal">
        <Border Background="#2A2A3C" CornerRadius="9" Padding="3">
          <StackPanel Orientation="Horizontal">
            <RadioButton x:Name="rbFromRoom" Content="FromRoom" IsChecked="True"
                         Style="{StaticResource ToggleBtn}" GroupName="RoomSide"/>
            <RadioButton x:Name="rbToRoom" Content="ToRoom"
                         Style="{StaticResource ToggleBtn}" GroupName="RoomSide" Margin="2,0,0,0"/>
          </StackPanel>
        </Border>
        <TextBlock x:Name="tbRoomSideNote" Text="Using FromRoom"
                   VerticalAlignment="Center" Foreground="#A6ADC8"
                   FontSize="11" Margin="10,0,0,0"/>
      </StackPanel>

      <StackPanel Grid.Column="2" Orientation="Horizontal">
        <TextBlock Text="Mode:" VerticalAlignment="Center"
                   Foreground="#A6ADC8" Margin="0,0,8,0" FontSize="12"/>
        <Border Background="#2A2A3C" CornerRadius="9" Padding="3">
          <StackPanel Orientation="Horizontal">
            <RadioButton x:Name="rbSingle"  Content="Single"  IsChecked="True"
                         Style="{StaticResource ModeBtn}" GroupName="TransferMode"/>
            <RadioButton x:Name="rbCombine" Content="Combine"
                         Style="{StaticResource ModeBtn}" GroupName="TransferMode" Margin="2,0,0,0"/>
          </StackPanel>
        </Border>
      </StackPanel>
    </Grid>

    <!-- ── Row 2: Two panels ── -->
    <Grid Grid.Row="2">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="16"/>
        <ColumnDefinition Width="*"/>
      </Grid.ColumnDefinitions>

      <!-- LEFT: Room Parameters -->
      <Border Grid.Column="0" Background="#2A2A3C" CornerRadius="8" Padding="12">
        <Grid>
          <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
          </Grid.RowDefinitions>
          <TextBlock Text="ROOM PARAMETERS" FontSize="10" FontWeight="SemiBold"
                     Foreground="#F0A500" Margin="0,0,0,8"/>
          <TextBox x:Name="tbRoomSearch" Grid.Row="1" Margin="0,0,0,6"/>
          <ListBox x:Name="lbRoomParams" Grid.Row="2" SelectionMode="Extended"/>
        </Grid>
      </Border>

      <TextBlock Grid.Column="1" Text="&#x2192;" FontSize="22" Foreground="#F0A500"
                 HorizontalAlignment="Center" VerticalAlignment="Center"/>

      <!-- RIGHT: Door Parameters -->
      <Border Grid.Column="2" Background="#2A2A3C" CornerRadius="8" Padding="12">
        <Grid>
          <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
          </Grid.RowDefinitions>
          <TextBlock Text="DOOR PARAMETERS" FontSize="10" FontWeight="SemiBold"
                     Foreground="#F0A500" Margin="0,0,0,8"/>
          <TextBox x:Name="tbDoorSearch" Grid.Row="1" Margin="0,0,0,6"/>
          <ListBox x:Name="lbDoorParams" Grid.Row="2" SelectionMode="Single"/>
        </Grid>
      </Border>
    </Grid>

    <!-- ── Row 3: Combine panel ── -->
    <Border x:Name="pnlCombine" Grid.Row="3"
            Background="#2A2A3C" CornerRadius="8" Padding="12"
            Margin="0,10,0,0" Visibility="Collapsed">
      <Grid>
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="*"/>
          <ColumnDefinition Width="14"/>
          <ColumnDefinition Width="Auto"/>
        </Grid.ColumnDefinitions>
        <Grid Grid.Column="0">
          <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="110"/>
          </Grid.RowDefinitions>
          <TextBlock Text="COMBINE ORDER" FontSize="10" FontWeight="SemiBold"
                     Foreground="#F0A500" Margin="0,0,0,6"/>
          <TextBlock Grid.Row="1" Foreground="#A6ADC8" FontSize="11" Margin="0,0,0,6"
                     Text="Select params in the room list then click Add  •  Use arrows to reorder"/>
          <ListBox x:Name="lbCombineOrder" Grid.Row="2" SelectionMode="Single"/>
        </Grid>
        <StackPanel Grid.Column="2" VerticalAlignment="Center" Margin="0,22,0,0">
          <Button x:Name="btnAddCombine"    Content="+ Add"    Style="{StaticResource IconBtn}" Width="80" Height="28" Margin="0,0,0,4"/>
          <Button x:Name="btnRemoveCombine" Content="- Remove" Style="{StaticResource IconBtn}" Width="80" Height="28" Margin="0,0,0,4"/>
          <Button x:Name="btnMoveUp"   Content="Up"   Style="{StaticResource IconBtn}" Width="80" Height="28" Margin="0,0,0,4"/>
          <Button x:Name="btnMoveDown" Content="Down" Style="{StaticResource IconBtn}" Width="80" Height="28" Margin="0,8,0,0"/>
          <TextBlock Text="Separator" Foreground="#A6ADC8" FontSize="10" Margin="0,10,0,3"/>
          <TextBox x:Name="tbSeparator" Width="80" Text=" - " TextAlignment="Center"/>
        </StackPanel>
      </Grid>
    </Border>

    <!-- ── Row 4: Designator panel ── -->
    <Border Grid.Row="4" Background="#2A2A3C" CornerRadius="8"
            Padding="14,10" Margin="0,10,0,0">
      <Grid>
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="Auto"/>
          <ColumnDefinition Width="*"/>
        </Grid.ColumnDefinitions>

        <!-- Checkbox -->
        <CheckBox x:Name="chkDesignator" Grid.Column="0"
                  Content="Add Designator for shared rooms"
                  VerticalAlignment="Center"/>

        <!-- Options row (hidden until checkbox is on) -->
        <StackPanel x:Name="pnlDesignatorOpts" Grid.Column="1"
                    Orientation="Horizontal" HorizontalAlignment="Right"
                    VerticalAlignment="Center" Visibility="Collapsed">

          <TextBlock Text="Type:" Foreground="#A6ADC8" VerticalAlignment="Center"
                     Margin="0,0,10,0" FontSize="12"/>
          <Border Background="#313244" CornerRadius="9" Padding="3">
            <StackPanel Orientation="Horizontal">
              <RadioButton x:Name="rbDesAlpha" Content="A, B, C" IsChecked="True"
                           Style="{StaticResource ModeBtn}" GroupName="DesType"/>
              <RadioButton x:Name="rbDesNum"   Content="1, 2, 3"
                           Style="{StaticResource ModeBtn}" GroupName="DesType" Margin="2,0,0,0"/>
            </StackPanel>
          </Border>

          <TextBlock Text="Separator:" Foreground="#A6ADC8" VerticalAlignment="Center"
                     Margin="20,0,10,0" FontSize="12"/>
          <TextBox x:Name="tbDesSep" Width="55" Text="-" TextAlignment="Center"/>

          <Border Background="#313244" CornerRadius="6" Padding="10,4" Margin="20,0,0,0">
            <StackPanel Orientation="Horizontal">
              <TextBlock Text="&#x2139;" Foreground="#F0A500" FontSize="13"
                         VerticalAlignment="Center" Margin="0,0,6,0"/>
              <TextBlock Foreground="#A6ADC8" FontSize="11" VerticalAlignment="Center"
                         Text="Designator resets per level — same room numbers on different levels are treated independently"/>
            </StackPanel>
          </Border>

        </StackPanel>
      </Grid>
    </Border>

    <!-- ── Row 5: Status + Run ── -->
    <Grid Grid.Row="5" Margin="0,12,0,0">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="Auto"/>
      </Grid.ColumnDefinitions>
      <TextBlock x:Name="tbStatus" Grid.Column="0"
                 Foreground="#A6ADC8" FontSize="12" VerticalAlignment="Center"
                 Text="Select a room parameter and a door parameter, then click Run."/>
      <StackPanel Grid.Column="1" Orientation="Horizontal">
        <Button x:Name="btnCancel" Content="Cancel"       Margin="0,0,8,0"/>
        <Button x:Name="btnRun"    Content="Run Transfer" Style="{StaticResource AccentButton}"/>
      </StackPanel>
    </Grid>

  </Grid>
</Window>
"""

# ──────────────────────────────────────────────
# Build window
# ──────────────────────────────────────────────

window = XamlReader.Parse(XAML)

rb_from    = window.FindName("rbFromRoom")
rb_to      = window.FindName("rbToRoom")
rb_single  = window.FindName("rbSingle")
rb_combine = window.FindName("rbCombine")

tb_room_search = window.FindName("tbRoomSearch")
tb_door_search = window.FindName("tbDoorSearch")
lb_room        = window.FindName("lbRoomParams")
lb_door        = window.FindName("lbDoorParams")

pnl_combine      = window.FindName("pnlCombine")
lb_combine_order = window.FindName("lbCombineOrder")
btn_add_combine  = window.FindName("btnAddCombine")
btn_rem_combine  = window.FindName("btnRemoveCombine")
btn_up           = window.FindName("btnMoveUp")
btn_down         = window.FindName("btnMoveDown")
tb_sep           = window.FindName("tbSeparator")

chk_designator  = window.FindName("chkDesignator")
pnl_des_opts    = window.FindName("pnlDesignatorOpts")
rb_des_alpha    = window.FindName("rbDesAlpha")
rb_des_num      = window.FindName("rbDesNum")
tb_des_sep      = window.FindName("tbDesSep")

tb_status    = window.FindName("tbStatus")
btn_run      = window.FindName("btnRun")
btn_cancel   = window.FindName("btnCancel")
tb_room_note = window.FindName("tbRoomSideNote")

# ──────────────────────────────────────────────
# Parameter lists
# ──────────────────────────────────────────────

all_room_params = collect_parameters_for_category(BuiltInCategory.OST_Rooms)
all_door_params = collect_parameters_for_category(BuiltInCategory.OST_Doors)


def populate_list(listbox, items, filter_text=""):
    listbox.Items.Clear()
    ft = filter_text.strip().lower()
    for name in items:
        if ft and ft not in name.lower():
            continue
        item = ListBoxItem()
        item.Content = name
        listbox.Items.Add(item)


populate_list(lb_room, all_room_params)
populate_list(lb_door, all_door_params)

# ──────────────────────────────────────────────
# Search
# ──────────────────────────────────────────────

def on_room_search(sender, e):
    populate_list(lb_room, all_room_params, tb_room_search.Text)

def on_door_search(sender, e):
    populate_list(lb_door, all_door_params, tb_door_search.Text)

tb_room_search.TextChanged += on_room_search
tb_door_search.TextChanged += on_door_search

# ──────────────────────────────────────────────
# Room-side toggle label
# ──────────────────────────────────────────────

def on_room_side_changed(sender, e):
    tb_room_note.Text = "Using FromRoom" if rb_from.IsChecked == True else "Using ToRoom"

rb_from.Checked += on_room_side_changed
rb_to.Checked   += on_room_side_changed

# ──────────────────────────────────────────────
# Mode toggle
# ──────────────────────────────────────────────

def on_mode_changed(sender, e):
    if rb_combine.IsChecked == True:
        pnl_combine.Visibility = System.Windows.Visibility.Visible
        lb_room.SelectionMode = System.Windows.Controls.SelectionMode.Extended
    else:
        pnl_combine.Visibility = System.Windows.Visibility.Collapsed
        lb_room.SelectionMode = System.Windows.Controls.SelectionMode.Extended

rb_single.Checked  += on_mode_changed
rb_combine.Checked += on_mode_changed

# ──────────────────────────────────────────────
# Designator toggle
# ──────────────────────────────────────────────

def on_designator_toggle(sender, e):
    if chk_designator.IsChecked == True:
        pnl_des_opts.Visibility = System.Windows.Visibility.Visible
    else:
        pnl_des_opts.Visibility = System.Windows.Visibility.Collapsed

chk_designator.Checked   += on_designator_toggle
chk_designator.Unchecked += on_designator_toggle

# ──────────────────────────────────────────────
# Combine order controls
# ──────────────────────────────────────────────

def on_add_combine(sender, e):
    selected = [item.Content for item in lb_room.SelectedItems]
    existing = [lb_combine_order.Items.GetItemAt(i).Content
                for i in range(lb_combine_order.Items.Count)]
    for name in selected:
        if name not in existing:
            item = ListBoxItem()
            item.Content = name
            lb_combine_order.Items.Add(item)

def on_remove_combine(sender, e):
    sel = lb_combine_order.SelectedItem
    if sel is not None:
        lb_combine_order.Items.Remove(sel)

def on_move_up(sender, e):
    idx = lb_combine_order.SelectedIndex
    if idx > 0:
        item = lb_combine_order.Items.GetItemAt(idx)
        lb_combine_order.Items.RemoveAt(idx)
        lb_combine_order.Items.Insert(idx - 1, item)
        lb_combine_order.SelectedIndex = idx - 1

def on_move_down(sender, e):
    idx = lb_combine_order.SelectedIndex
    count = lb_combine_order.Items.Count
    if 0 <= idx < count - 1:
        item = lb_combine_order.Items.GetItemAt(idx)
        lb_combine_order.Items.RemoveAt(idx)
        lb_combine_order.Items.Insert(idx + 1, item)
        lb_combine_order.SelectedIndex = idx + 1

btn_add_combine.Click  += on_add_combine
btn_rem_combine.Click  += on_remove_combine
btn_up.Click           += on_move_up
btn_down.Click         += on_move_down

# ──────────────────────────────────────────────
# Run
# ──────────────────────────────────────────────

def on_run(sender, e):
    phase        = get_last_phase()
    use_from     = (rb_from.IsChecked == True)
    is_combine   = (rb_combine.IsChecked == True)
    use_designator = (chk_designator.IsChecked == True)

    # ── Validate door param ──
    door_param_item = lb_door.SelectedItem
    if door_param_item is None:
        tb_status.Text = "Please select a door parameter."
        return
    door_param_name = door_param_item.Content

    # ── Validate room params ──
    if is_combine:
        room_param_names = [lb_combine_order.Items.GetItemAt(i).Content
                            for i in range(lb_combine_order.Items.Count)]
        if not room_param_names:
            tb_status.Text = "Add at least one room parameter to the combine list."
            return
        combine_sep = tb_sep.Text
    else:
        room_param_item = lb_room.SelectedItem
        if room_param_item is None:
            tb_status.Text = "Please select a room parameter."
            return
        room_param_names = [room_param_item.Content]
        combine_sep = ""

    # ── Designator settings ──
    is_alpha  = (rb_des_alpha.IsChecked == True)
    des_sep   = tb_des_sep.Text if use_designator else ""

    # ── Collect all doors ──
    all_doors = (FilteredElementCollector(doc)
                 .OfCategory(BuiltInCategory.OST_Doors)
                 .WhereElementIsNotElementType()
                 .ToElements())

    no_room    = 0
    skip_count = 0
    no_param   = 0
    read_only  = 0

    # ── Pass 1: compute base values + level key ──
    # record = (door, base_value, level_key)
    # level_key = str(room.LevelId)  — resets designator per level
    records = []

    for door in all_doors:
        try:
            room = door.FromRoom[phase] if use_from else door.ToRoom[phase]
        except Exception:
            room = None

        if room is None:
            no_room += 1
            continue

        if is_combine:
            parts = [get_param_value_as_string(room, n) for n in room_param_names]
            base_value = combine_sep.join(parts)
        else:
            base_value = get_param_value_as_string(room, room_param_names[0])

        if base_value == "":
            skip_count += 1
            continue

        # Level key from the room's LevelId
        try:
            lvl_id = room.LevelId
            level_key = str(lvl_id.Value if hasattr(lvl_id, 'Value') else lvl_id.IntegerValue)
        except Exception:
            level_key = "none"

        records.append((door, base_value, level_key))

    # ── Pass 2: build designator map ──
    # Group key = (base_value, level_key)
    # This means: same room number on a different level starts its own A/B/C sequence.
    designator_map = {}   # record index -> designator string

    if use_designator and records:
        groups = defaultdict(list)
        for i, (door, val, lvl) in enumerate(records):
            groups[(val, lvl)].append(i)

        for grp_indices in groups.values():
            if len(grp_indices) < 2:
                continue  # single door — no designator needed
            # Sort within group by ElementId for a deterministic, stable order
            grp_indices.sort(key=lambda i: get_element_id_int(records[i][0]))
            for rank, idx in enumerate(grp_indices):
                designator_map[idx] = (
                    to_alpha_designator(rank) if is_alpha else str(rank + 1)
                )

    # ── Pass 3: write to Revit in a single transaction ──
    ok_count = 0

    t = Transaction(doc, "Room to Door Parameter Transfer")
    t.Start()
    try:
        for i, (door, base_value, _) in enumerate(records):
            if use_designator and i in designator_map:
                final_value = base_value + des_sep + designator_map[i]
            else:
                final_value = base_value

            success = set_param_value(door, door_param_name, final_value)
            if success:
                ok_count += 1
            else:
                dp = door.LookupParameter(door_param_name)
                if dp is None:
                    no_param += 1
                elif dp.IsReadOnly:
                    read_only += 1
                else:
                    skip_count += 1

        t.Commit()

        parts = ["Transfer complete —", "{} updated".format(ok_count)]
        if no_room:    parts.append("{} had no room".format(no_room))
        if skip_count: parts.append("{} skipped".format(skip_count))
        if no_param:   parts.append("{} missing param".format(no_param))
        if read_only:  parts.append("{} read-only".format(read_only))
        if use_designator:
            parts.append("{} designators assigned".format(len(designator_map)))
        tb_status.Text = "  |  ".join(parts)

    except Exception as ex:
        t.RollBack()
        tb_status.Text = "Error: {}".format(str(ex))


def on_cancel(sender, e):
    window.Close()

btn_run.Click    += on_run
btn_cancel.Click += on_cancel

# ──────────────────────────────────────────────
# Show
# ──────────────────────────────────────────────

window.ShowDialog()
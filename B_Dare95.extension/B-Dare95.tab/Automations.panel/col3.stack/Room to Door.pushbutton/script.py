# -*- coding: utf-8 -*-
"""
Room → Door Parameter Transfer
Transfers parameter values from room (ToRoom/FromRoom) to door parameters.
Supports single-param and combine (multi-param with separator) modes.
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
from System.Windows.Media import SolidColorBrush, Color

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
        # Instance parameters
        for p in el.Parameters:
            if p.Definition and p.StorageType != StorageType.None:
                names.add(p.Definition.Name)
        # Type parameters (only visit each type once)
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
        return str(p.AsElementId().Value if hasattr(p.AsElementId(), 'Value') else p.AsElementId().IntegerValue)
    return ""


def set_param_value(element, param_name, value):
    p = element.LookupParameter(param_name)
    if p is None or p.IsReadOnly:
        return False
    st = p.StorageType
    try:
        if st == StorageType.String:
            p.Set(value)
        else:
            p.SetValueString(value)
        return True
    except Exception:
        return False


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
    Title="Room → Door Parameter Transfer"
    Width="860" Height="680"
    MinWidth="720" MinHeight="560"
    WindowStartupLocation="CenterScreen"
    Background="#1E1E2E"
    Foreground="#CDD6F4"
    FontFamily="Segoe UI"
    FontSize="13">

  <Window.Resources>

    <!-- ScrollBar -->
    <Style TargetType="ScrollBar">
      <Setter Property="Background" Value="#2A2A3C"/>
      <Setter Property="Foreground" Value="#45475A"/>
      <Setter Property="Width" Value="6"/>
    </Style>

    <!-- TextBox -->
    <Style TargetType="TextBox">
      <Setter Property="Background" Value="#313244"/>
      <Setter Property="Foreground" Value="#CDD6F4"/>
      <Setter Property="BorderBrush" Value="#45475A"/>
      <Setter Property="BorderThickness" Value="1"/>
      <Setter Property="Padding" Value="6,4"/>
      <Setter Property="CaretBrush" Value="#F0A500"/>
    </Style>

    <!-- ListBox -->
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

    <!-- Button -->
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

    <!-- Accent Button -->
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

    <!-- Toggle (RadioButton) -->
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

    <!-- Mode ToggleButton -->
    <Style x:Key="ModeBtn" TargetType="RadioButton" BasedOn="{StaticResource ToggleBtn}">
      <Setter Property="Padding" Value="14,6"/>
      <Setter Property="FontSize" Value="12"/>
    </Style>

    <!-- Small icon button -->
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

  </Window.Resources>

  <Grid Margin="16">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <!-- header -->
      <RowDefinition Height="Auto"/>
      <!-- room toggle + mode toggle -->
      <RowDefinition Height="*"/>
      <!-- panels -->
      <RowDefinition Height="Auto"/>
      <!-- combine row (shown in combine mode) -->
      <RowDefinition Height="Auto"/>
      <!-- status + run -->
    </Grid.RowDefinitions>

    <!-- ── Header ── -->
    <StackPanel Grid.Row="0" Margin="0,0,0,14">
      <TextBlock Text="Room → Door Parameter Transfer"
                 FontSize="18" FontWeight="SemiBold"
                 Foreground="#F0A500"/>
      <TextBlock Text="Map room parameter values to door parameters via FromRoom / ToRoom"
                 Foreground="#A6ADC8" FontSize="11" Margin="0,2,0,0"/>
    </StackPanel>

    <!-- ── Row 1: Room-side toggle + Mode toggle ── -->
    <Grid Grid.Row="1" Margin="0,0,0,12">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="Auto"/>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="Auto"/>
      </Grid.ColumnDefinitions>

      <!-- FromRoom / ToRoom -->
      <StackPanel Grid.Column="0" Orientation="Horizontal">
        <Border Background="#2A2A3C" CornerRadius="9" Padding="3">
          <StackPanel Orientation="Horizontal">
            <RadioButton x:Name="rbFromRoom" Content="FromRoom" IsChecked="True"
                         Style="{StaticResource ToggleBtn}" GroupName="RoomSide"/>
            <RadioButton x:Name="rbToRoom"   Content="ToRoom"
                         Style="{StaticResource ToggleBtn}" GroupName="RoomSide" Margin="2,0,0,0"/>
          </StackPanel>
        </Border>
        <TextBlock x:Name="tbRoomSideNote" Text="Using FromRoom"
                   VerticalAlignment="Center" Foreground="#A6ADC8"
                   FontSize="11" Margin="10,0,0,0"/>
      </StackPanel>

      <!-- Single / Combine mode -->
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
          <TextBox x:Name="tbRoomSearch" Grid.Row="1" Margin="0,0,0,6"
                   Text="" Tag="Search room parameters…">
            <TextBox.Style>
              <Style TargetType="TextBox" BasedOn="{StaticResource {x:Type TextBox}}">
                <Style.Triggers>
                  <Trigger Property="Text" Value="">
                    <Setter Property="Foreground" Value="#45475A"/>
                  </Trigger>
                </Style.Triggers>
              </Style>
            </TextBox.Style>
          </TextBox>
          <ListBox x:Name="lbRoomParams" Grid.Row="2" SelectionMode="Extended"/>
        </Grid>
      </Border>

      <!-- Divider arrow -->
      <TextBlock Grid.Column="1" Text="→" FontSize="22" Foreground="#F0A500"
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
          <TextBox x:Name="tbDoorSearch" Grid.Row="1" Margin="0,0,0,6"
                   Text="" Tag="Search door parameters…"/>
          <ListBox x:Name="lbDoorParams" Grid.Row="2" SelectionMode="Single"/>
        </Grid>
      </Border>
    </Grid>

    <!-- ── Row 3: Combine controls (shown only in Combine mode) ── -->
    <Border x:Name="pnlCombine" Grid.Row="3"
            Background="#2A2A3C" CornerRadius="8" Padding="12"
            Margin="0,12,0,0" Visibility="Collapsed">
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
            <RowDefinition Height="120"/>
          </Grid.RowDefinitions>
          <TextBlock Text="COMBINE ORDER" FontSize="10" FontWeight="SemiBold"
                     Foreground="#F0A500" Margin="0,0,0,6"/>
          <TextBlock Grid.Row="1" Foreground="#A6ADC8" FontSize="11" Margin="0,0,0,6"
                     Text="Select params in the room list then click Add ↓  •  Drag or use arrows to reorder"/>
          <ListBox x:Name="lbCombineOrder" Grid.Row="2" SelectionMode="Single"/>
        </Grid>
        <StackPanel Grid.Column="2" VerticalAlignment="Center" Margin="0,24,0,0">
          <Button x:Name="btnAddCombine"    Content="＋ Add"    Style="{StaticResource IconBtn}" Width="72" Height="28" Margin="0,0,0,4"/>
          <Button x:Name="btnRemoveCombine" Content="− Remove"  Style="{StaticResource IconBtn}" Width="72" Height="28" Margin="0,0,0,4"/>
          <Button x:Name="btnMoveUp"   Content="▲" Style="{StaticResource IconBtn}" Width="72" Height="28" Margin="0,0,0,4"/>
          <Button x:Name="btnMoveDown" Content="▼" Style="{StaticResource IconBtn}" Width="72" Height="28" Margin="0,8,0,0"/>
          <TextBlock Text="Separator" Foreground="#A6ADC8" FontSize="10" Margin="0,10,0,3"/>
          <TextBox x:Name="tbSeparator" Width="72" Text=" - " TextAlignment="Center"/>
        </StackPanel>
      </Grid>
    </Border>

    <!-- ── Row 4: Status + Run ── -->
    <Grid Grid.Row="4" Margin="0,12,0,0">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="Auto"/>
      </Grid.ColumnDefinitions>
      <TextBlock x:Name="tbStatus" Grid.Column="0"
                 Foreground="#A6ADC8" FontSize="12"
                 VerticalAlignment="Center"
                 Text="Select a room parameter and a door parameter, then click Run."/>
      <StackPanel Grid.Column="1" Orientation="Horizontal">
        <Button x:Name="btnCancel" Content="Cancel"  Margin="0,0,8,0"/>
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

# Wire up named elements
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
# Search handlers
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
    if rb_from.IsChecked == True:
        tb_room_note.Text = "Using FromRoom"
    else:
        tb_room_note.Text = "Using ToRoom"

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
btn_up.Click   += on_move_up
btn_down.Click += on_move_down

# ──────────────────────────────────────────────
# Run
# ──────────────────────────────────────────────

result_holder = [None]  # "ok" | "cancel"

def on_run(sender, e):
    phase = get_last_phase()
    use_from = (rb_from.IsChecked == True)
    is_combine = (rb_combine.IsChecked == True)

    # Validate door parameter selection
    door_param_item = lb_door.SelectedItem
    if door_param_item is None:
        tb_status.Text = "⚠  Please select a door parameter."
        return
    door_param_name = door_param_item.Content

    # Build list of room param names to read
    if is_combine:
        room_param_names = [lb_combine_order.Items.GetItemAt(i).Content
                            for i in range(lb_combine_order.Items.Count)]
        if not room_param_names:
            tb_status.Text = "⚠  Add at least one room parameter to the combine list."
            return
        separator = tb_sep.Text
    else:
        room_param_item = lb_room.SelectedItem
        if room_param_item is None:
            tb_status.Text = "⚠  Please select a room parameter."
            return
        room_param_names = [room_param_item.Content]
        separator = ""

    # Collect doors
    all_doors = (FilteredElementCollector(doc)
                 .OfCategory(BuiltInCategory.OST_Doors)
                 .WhereElementIsNotElementType()
                 .ToElements())

    ok_count    = 0
    skip_count  = 0
    no_room     = 0
    no_param    = 0
    read_only   = 0

    t = Transaction(doc, "Room → Door Parameter Transfer")
    t.Start()
    try:
        for door in all_doors:
            try:
                room = door.FromRoom[phase] if use_from else door.ToRoom[phase]
            except Exception:
                room = None

            if room is None:
                no_room += 1
                continue

            # Build the value string
            if is_combine:
                parts = []
                for rp_name in room_param_names:
                    parts.append(get_param_value_as_string(room, rp_name))
                value = separator.join(parts)
            else:
                value = get_param_value_as_string(room, room_param_names[0])

            if value == "":
                skip_count += 1
                continue

            success = set_param_value(door, door_param_name, value)
            if success:
                ok_count += 1
            else:
                # Check why it failed
                dp = door.LookupParameter(door_param_name)
                if dp is None:
                    no_param += 1
                elif dp.IsReadOnly:
                    read_only += 1
                else:
                    skip_count += 1

        t.Commit()
        result_holder[0] = "ok"

        status_parts = ["✓ Transfer complete —"]
        status_parts.append("{} updated".format(ok_count))
        if no_room:    status_parts.append("{} doors had no room".format(no_room))
        if skip_count: status_parts.append("{} skipped (empty/type mismatch)".format(skip_count))
        if no_param:   status_parts.append("{} missing param".format(no_param))
        if read_only:  status_parts.append("{} read-only".format(read_only))
        tb_status.Text = "  •  ".join(status_parts)

    except Exception as ex:
        t.RollBack()
        tb_status.Text = "✗ Error: {}".format(str(ex))


def on_cancel(sender, e):
    result_holder[0] = "cancel"
    window.Close()

btn_run.Click    += on_run
btn_cancel.Click += on_cancel

# ──────────────────────────────────────────────
# Show
# ──────────────────────────────────────────────

window.ShowDialog()
# -*- coding: utf-8 -*-

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')
clr.AddReference('System')

from Autodesk.Revit.DB import *
from System.Windows import Window, Thickness, HorizontalAlignment, VerticalAlignment
from System.Windows.Controls import (
    ComboBox, ComboBoxItem, Button, TextBox, StackPanel,
    Label, Border, Orientation, Grid, ColumnDefinition,
    RowDefinition, TextBlock
)
from System.Windows.Media import SolidColorBrush, Color
from System.Windows.Markup import XamlReader
from System import Array
import System.Windows

doc   = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

# ── helpers ──────────────────────────────────────────────────────────────────

def title_case(s):
    """Capitalize first letter of each word."""
    return ' '.join(w.capitalize() for w in s.split(' '))

def get_text_parameters(rooms):
    """Return a sorted list of unique parameter names whose StorageType is String."""
    seen = set()
    names = []
    for room in rooms:
        for param in room.Parameters:
            n = param.Definition.Name
            if param.StorageType == StorageType.String and n not in seen:
                seen.add(n)
                names.append(n)
    return sorted(names)

# ── collect rooms & parameters ────────────────────────────────────────────────

all_rooms = (FilteredElementCollector(doc)
             .OfCategory(BuiltInCategory.OST_Rooms)
             .WhereElementIsNotElementType()
             .ToElements())

if not all_rooms:
    System.Windows.MessageBox.Show("No rooms found in the project.", "Room Name Formatter")
    import sys; sys.exit()

text_params = get_text_parameters(all_rooms)

if not text_params:
    System.Windows.MessageBox.Show("No text parameters found on rooms.", "Room Name Formatter")
    import sys; sys.exit()

# ── XAML ─────────────────────────────────────────────────────────────────────

XAML = """
<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Room Name Formatter"
    Width="580" Height="310"
    WindowStartupLocation="CenterScreen"
    ResizeMode="NoResize"
    Background="#1E1E2E">

  <Window.Resources>

    <!-- Base button style with rounded corners -->
    <Style x:Key="BaseBtn" TargetType="Button">
      <Setter Property="Foreground"   Value="#CDD6F4"/>
      <Setter Property="Background"   Value="#313244"/>
      <Setter Property="BorderBrush"  Value="#45475A"/>
      <Setter Property="BorderThickness" Value="1"/>
      <Setter Property="FontSize"     Value="12"/>
      <Setter Property="FontFamily"   Value="Segoe UI"/>
      <Setter Property="Padding"      Value="10,6"/>
      <Setter Property="Cursor"       Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="bd"
                    Background="{TemplateBinding Background}"
                    BorderBrush="{TemplateBinding BorderBrush}"
                    BorderThickness="{TemplateBinding BorderThickness}"
                    CornerRadius="6"
                    Padding="{TemplateBinding Padding}">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="bd" Property="Background" Value="#45475A"/>
              </Trigger>
              <Trigger Property="IsPressed" Value="True">
                <Setter TargetName="bd" Property="Background" Value="#F0A500"/>
                <Setter Property="Foreground" Value="#1E1E2E"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <!-- Toggle/selected state button -->
    <Style x:Key="OpBtn" TargetType="Button" BasedOn="{StaticResource BaseBtn}">
      <Setter Property="FontWeight" Value="SemiBold"/>
    </Style>

    <!-- Apply button -->
    <Style x:Key="ApplyBtn" TargetType="Button" BasedOn="{StaticResource BaseBtn}">
      <Setter Property="Background"  Value="#F0A500"/>
      <Setter Property="Foreground"  Value="#1E1E2E"/>
      <Setter Property="FontWeight"  Value="Bold"/>
      <Setter Property="FontSize"    Value="13"/>
    </Style>

    <!-- ComboBox style -->
    <Style TargetType="ComboBox">
      <Setter Property="Background"         Value="#313244"/>
      <Setter Property="Foreground"         Value="#CDD6F4"/>
      <Setter Property="BorderBrush"        Value="#45475A"/>
      <Setter Property="BorderThickness"    Value="1"/>
      <Setter Property="FontFamily"         Value="Segoe UI"/>
      <Setter Property="FontSize"           Value="12"/>
      <Setter Property="Padding"            Value="8,5"/>
      <Setter Property="Height"             Value="34"/>
    </Style>

    <!-- TextBox style -->
    <Style TargetType="TextBox">
      <Setter Property="Background"      Value="#313244"/>
      <Setter Property="Foreground"      Value="#CDD6F4"/>
      <Setter Property="BorderBrush"     Value="#45475A"/>
      <Setter Property="BorderThickness" Value="1"/>
      <Setter Property="FontFamily"      Value="Segoe UI"/>
      <Setter Property="FontSize"        Value="12"/>
      <Setter Property="Padding"         Value="8,5"/>
      <Setter Property="Height"          Value="34"/>
      <Setter Property="VerticalContentAlignment" Value="Center"/>
    </Style>

    <!-- Label style -->
    <Style TargetType="Label">
      <Setter Property="Foreground"  Value="#A6ADC8"/>
      <Setter Property="FontFamily"  Value="Segoe UI"/>
      <Setter Property="FontSize"    Value="11"/>
      <Setter Property="Padding"     Value="0,0,0,4"/>
    </Style>

  </Window.Resources>

  <Border Margin="20" Background="#1E1E2E">
    <StackPanel>

      <!-- Title -->
      <TextBlock Text="Room Name Formatter"
                 Foreground="#CDD6F4"
                 FontFamily="Segoe UI"
                 FontSize="16"
                 FontWeight="SemiBold"
                 Margin="0,0,0,18"/>

      <!-- Row 1 : Parameter selector + Operation buttons -->
      <Grid Margin="0,0,0,16">
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="*"/>
          <ColumnDefinition Width="16"/>
          <ColumnDefinition Width="Auto"/>
        </Grid.ColumnDefinitions>

        <!-- Parameter selector -->
        <StackPanel Grid.Column="0">
          <Label Content="Room Parameter"/>
          <ComboBox x:Name="cbParam"/>
        </StackPanel>

        <!-- Operation buttons -->
        <StackPanel Grid.Column="2" VerticalAlignment="Bottom">
          <Label Content="Casing Operation"/>
          <StackPanel Orientation="Horizontal">
            <Button x:Name="btnUpper"  Content="UPPERCASE"       Style="{StaticResource OpBtn}" Width="110" Margin="0,0,8,0"/>
            <Button x:Name="btnLower"  Content="lowercase"       Style="{StaticResource OpBtn}" Width="110" Margin="0,0,8,0"/>
            <Button x:Name="btnTitle"  Content="Title Case"      Style="{StaticResource OpBtn}" Width="110"/>
          </StackPanel>
        </StackPanel>
      </Grid>

      <!-- Row 2 : Prefix / Suffix -->
      <Grid Margin="0,0,0,24">
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="*"/>
          <ColumnDefinition Width="16"/>
          <ColumnDefinition Width="*"/>
        </Grid.ColumnDefinitions>

        <StackPanel Grid.Column="0">
          <Label Content="Prefix  (optional)"/>
          <TextBox x:Name="tbPrefix" />
        </StackPanel>

        <StackPanel Grid.Column="2">
          <Label Content="Suffix  (optional)"/>
          <TextBox x:Name="tbSuffix" />
        </StackPanel>
      </Grid>

      <!-- Row 3 : Apply + Cancel -->
      <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
        <Button x:Name="btnCancel" Content="Cancel"  Style="{StaticResource BaseBtn}" Width="90"  Margin="0,0,10,0"/>
        <Button x:Name="btnApply"  Content="Apply"   Style="{StaticResource ApplyBtn}" Width="90"/>
      </StackPanel>

    </StackPanel>
  </Border>
</Window>
"""

# ── build window ──────────────────────────────────────────────────────────────

win     = XamlReader.Parse(XAML)
cbParam = win.FindName("cbParam")
tbPrefix = win.FindName("tbPrefix")
tbSuffix = win.FindName("tbSuffix")
btnUpper  = win.FindName("btnUpper")
btnLower  = win.FindName("btnLower")
btnTitle  = win.FindName("btnTitle")
btnApply  = win.FindName("btnApply")
btnCancel = win.FindName("btnCancel")

# ── populate combobox ─────────────────────────────────────────────────────────

for name in text_params:
    item = ComboBoxItem()
    item.Content = name
    item.Foreground = SolidColorBrush(Color.FromRgb(0xCD, 0xD6, 0xF4))
    item.Background = SolidColorBrush(Color.FromRgb(0x31, 0x32, 0x44))
    cbParam.Items.Add(item)

# pre-select "Name" if present, else first item
default_idx = 0
for i, name in enumerate(text_params):
    if name.lower() == "name":
        default_idx = i
        break
cbParam.SelectedIndex = default_idx

# ── operation selection state ─────────────────────────────────────────────────

selected_op = ["upper"]   # mutable container for IronPython closure

ACCENT   = SolidColorBrush(Color.FromRgb(0xF0, 0xA5, 0x00))
ACCENT_FG= SolidColorBrush(Color.FromRgb(0x1E, 0x1E, 0x2E))
NORMAL   = SolidColorBrush(Color.FromRgb(0x31, 0x32, 0x44))
NORMAL_FG= SolidColorBrush(Color.FromRgb(0xCD, 0xD6, 0xF4))

def highlight_op(active):
    for btn, key in [(btnUpper, "upper"), (btnLower, "lower"), (btnTitle, "title")]:
        if key == active:
            btn.Background = ACCENT
            btn.Foreground  = ACCENT_FG
        else:
            btn.Background = NORMAL
            btn.Foreground  = NORMAL_FG

highlight_op("upper")   # default

def on_upper(s, e):
    selected_op[0] = "upper"
    highlight_op("upper")

def on_lower(s, e):
    selected_op[0] = "lower"
    highlight_op("lower")

def on_title(s, e):
    selected_op[0] = "title"
    highlight_op("title")

btnUpper.Click += on_upper
btnLower.Click += on_lower
btnTitle.Click += on_title

# ── apply ─────────────────────────────────────────────────────────────────────

def on_apply(s, e):
    if cbParam.SelectedItem is None:
        System.Windows.MessageBox.Show("Please select a parameter.", "Room Name Formatter")
        return

    param_name = cbParam.SelectedItem.Content
    op         = selected_op[0]
    prefix     = tbPrefix.Text.strip()
    suffix     = tbSuffix.Text.strip()

    changed = 0
    errors  = 0

    t = Transaction(doc, "Room Name Formatter")
    t.Start()
    for room in all_rooms:
        p = room.LookupParameter(param_name)
        if p is None or p.IsReadOnly:
            continue
        raw = p.AsString()
        if raw is None:
            raw = ""
        # apply casing
        if op == "upper":
            result = raw.upper()
        elif op == "lower":
            result = raw.lower()
        else:
            result = title_case(raw)
        # apply prefix / suffix
        result = prefix + result + suffix
        try:
            p.Set(result)
            changed += 1
        except Exception:
            errors += 1
    t.Commit()

    msg = "Done!  {} room(s) updated.".format(changed)
    if errors:
        msg += "\n{} room(s) skipped (read-only or error).".format(errors)
    System.Windows.MessageBox.Show(msg, "Room Name Formatter")
    win.Close()

def on_cancel(s, e):
    win.Close()

btnApply.Click  += on_apply
btnCancel.Click += on_cancel

# ── show ──────────────────────────────────────────────────────────────────────

win.ShowDialog()
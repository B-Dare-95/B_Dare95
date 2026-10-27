# -*- coding: utf-8 -*-
# =====================================================================
# HOOK  --  B_Dare95.extension
# File location : B_Dare95.extension/hooks/command-before-exec[ID_FILE_IMPORT].py
# Bound event   : command-before-exec for ID_FILE_IMPORT (Insert > Import CAD)
# Purpose       : Block Import CAD and point the user to Link CAD instead.
# Author        : Mohamed Bedair
#
# Reload pyRevit after adding/renaming this file so the hook registers.
# =====================================================================


# =====================================================================
# 1. IMPORTS
# =====================================================================
import os
import datetime
import traceback

import clr
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")

from System import Uri, UriKind, EventHandler
from System.Windows import Visibility, RoutedEventHandler
from System.Windows.Input import (MouseButtonEventHandler, MouseButtonState,
                                  KeyEventHandler, Key)
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Markup import XamlReader
from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption
from System.Windows.Threading import Dispatcher, DispatcherFrame

from Autodesk.Revit.UI import RevitCommandId, PostableCommand, TaskDialog

from pyrevit import EXEC_PARAMS
from pyrevit import HOST_APP


# =====================================================================
# 2. CONFIG
# =====================================================================
HOOK_NAME = "command-before-exec[ID_FILE_IMPORT]"

ENABLED = True          # False = Import CAD works normally again
WRITE_LOG = True        # file log only - never print from a hook
LOG_PATH = os.path.join(os.path.expanduser("~"), "pyrevit_hooks.log")

DIALOG_TITLE = "B_Dare95"
MSG_BOLD = "Import CAD is denied,"
MSG_REST = " please use Link CAD Instead"

# Logo paths relative to the extension root (B_Dare95.extension/).
# First one that exists is used; if none exist the logo is hidden.
LOGO_CANDIDATES = [
    "logo.png",
    os.path.join("assets", "logo.png"),
]

try:
    EXT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
except NameError:
    EXT_ROOT = None

# IBM Carbon palette (extension-wide theme)
C_BG = "#161616"
C_CARD = "#262626"
C_SURFACE = "#393939"
C_MUTED = "#525252"
C_TEXT = "#F4F4F4"
C_SUBTEXT = "#A8A8A8"
C_ACCENT = "#F1C21B"


# =====================================================================
# 7. SILENT LOGGING  (defined early so every slot can use it)
# =====================================================================
def log(message):
    if not WRITE_LOG:
        return
    try:
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_PATH, "a") as f:
            f.write("{0} [{1}] {2}\n".format(stamp, HOOK_NAME, message))
    except Exception:
        pass


# =====================================================================
# UI  --  Carbon-styled task dialog
# =====================================================================
XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="{TITLE}" Width="460" SizeToContent="Height"
        WindowStyle="None" AllowsTransparency="True" Background="Transparent"
        ResizeMode="NoResize" ShowInTaskbar="False" Topmost="False"
        WindowStartupLocation="CenterOwner"
        FontFamily="IBM Plex Sans, Segoe UI">

  <Window.Resources>
    <Style x:Key="BtnBase" TargetType="Button">
      <Setter Property="Foreground" Value="{TEXT}"/>
      <Setter Property="Background" Value="{SURFACE}"/>
      <Setter Property="FontSize" Value="13"/>
      <Setter Property="Padding" Value="20,8"/>
      <Setter Property="Margin" Value="8,0,0,0"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="Bd" Background="{TemplateBinding Background}"
                    CornerRadius="4" Padding="{TemplateBinding Padding}">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="Bd" Property="Opacity" Value="0.85"/>
              </Trigger>
              <Trigger Property="IsPressed" Value="True">
                <Setter TargetName="Bd" Property="Opacity" Value="0.7"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="BtnPrimary" TargetType="Button" BasedOn="{StaticResource BtnBase}">
      <Setter Property="Background" Value="{ACCENT}"/>
      <Setter Property="Foreground" Value="{BG}"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
    </Style>

    <Style x:Key="BtnGhost" TargetType="Button" BasedOn="{StaticResource BtnBase}">
      <Setter Property="Background" Value="Transparent"/>
      <Setter Property="Foreground" Value="{SUBTEXT}"/>
      <Setter Property="Padding" Value="8,2"/>
      <Setter Property="Margin" Value="0"/>
    </Style>
  </Window.Resources>

  <Border Background="{BG}" CornerRadius="6" BorderBrush="{SURFACE}" BorderThickness="1">
    <Grid>
      <Grid.RowDefinitions>
        <RowDefinition Height="Auto"/>
        <RowDefinition Height="Auto"/>
        <RowDefinition Height="Auto"/>
      </Grid.RowDefinitions>

      <!-- Header (drag handle) -->
      <Border x:Name="Header" Grid.Row="0" Background="{CARD}"
              CornerRadius="6,6,0,0" BorderBrush="{ACCENT}" BorderThickness="0,0,0,2"
              Padding="16,10,8,10">
        <DockPanel LastChildFill="True">
          <Button x:Name="BtnX" DockPanel.Dock="Right" Style="{StaticResource BtnGhost}"
                  Content="&#x2715;" FontSize="12"/>
          <TextBlock Text="{TITLE}  &#x00B7;  Command blocked" Foreground="{SUBTEXT}"
                     FontSize="12" VerticalAlignment="Center"/>
        </DockPanel>
      </Border>

      <!-- Body: logo + message -->
      <Grid Grid.Row="1" Margin="20,22,20,22">
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="Auto"/>
          <ColumnDefinition Width="*"/>
        </Grid.ColumnDefinitions>
        <Image x:Name="LogoImg" Grid.Column="0" Width="56" Height="56"
               Margin="0,0,18,0" VerticalAlignment="Center" Stretch="Uniform"
               RenderOptions.BitmapScalingMode="HighQuality"/>
        <TextBlock Grid.Column="1" TextWrapping="Wrap" VerticalAlignment="Center"
                   Foreground="{TEXT}" FontSize="15">
          <Run Text="{MSG_BOLD}" FontWeight="SemiBold"/><Run Text="{MSG_REST}"/>
        </TextBlock>
      </Grid>

      <!-- Footer: buttons -->
      <Border Grid.Row="2" Background="{CARD}" CornerRadius="0,0,6,6" Padding="16,12">
        <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
          <Button x:Name="BtnClose" Style="{StaticResource BtnBase}" Content="Close"/>
          <Button x:Name="BtnLink" Style="{StaticResource BtnPrimary}" Content="Link CAD"/>
        </StackPanel>
      </Border>
    </Grid>
  </Border>
</Window>
"""


def build_xaml():
    text = XAML
    for key, val in [("{TITLE}", DIALOG_TITLE), ("{MSG_BOLD}", MSG_BOLD),
                     ("{MSG_REST}", MSG_REST), ("{BG}", C_BG), ("{CARD}", C_CARD),
                     ("{SURFACE}", C_SURFACE), ("{MUTED}", C_MUTED),
                     ("{TEXT}", C_TEXT), ("{SUBTEXT}", C_SUBTEXT),
                     ("{ACCENT}", C_ACCENT)]:
        text = text.replace(key, val)
    return text


def find_logo():
    if not EXT_ROOT:
        return None
    for rel in LOGO_CANDIDATES:
        path = os.path.join(EXT_ROOT, rel)
        if os.path.isfile(path):
            return path
    log("Logo not found under {0} (tried: {1})".format(EXT_ROOT, ", ".join(LOGO_CANDIDATES)))
    return None


def load_logo(image_ctrl):
    path = find_logo()
    if not path:
        image_ctrl.Visibility = Visibility.Collapsed
        return
    try:
        bmp = BitmapImage()
        bmp.BeginInit()
        bmp.UriSource = Uri(path, UriKind.Absolute)
        bmp.CacheOption = BitmapCacheOption.OnLoad   # don't lock the file
        bmp.EndInit()
        image_ctrl.Source = bmp
    except Exception:
        log("Logo failed to load: {0}".format(traceback.format_exc()))
        image_ctrl.Visibility = Visibility.Collapsed


def show_denied_dialog():
    """Returns 'link' if the user asked to open Link CAD, else 'close'."""
    window = XamlReader.Parse(build_xaml())
    result = ["close"]
    frame = DispatcherFrame()

    load_logo(window.FindName("LogoImg"))

    try:
        WindowInteropHelper(window).Owner = HOST_APP.proc_window
    except Exception:
        log("Could not set Revit as owner: {0}".format(traceback.format_exc()))

    def on_link(sender, args):
        result[0] = "link"
        window.Close()

    def on_close(sender, args):
        window.Close()

    def on_closed(sender, args):
        frame.Continue = False

    def on_drag(sender, args):
        if args.ButtonState == MouseButtonState.Pressed:
            window.DragMove()

    def on_key(sender, args):
        if args.Key == Key.Escape:
            window.Close()
        elif args.Key == Key.Enter:
            result[0] = "link"
            window.Close()

    window.FindName("BtnLink").Click += RoutedEventHandler(on_link)
    window.FindName("BtnClose").Click += RoutedEventHandler(on_close)
    window.FindName("BtnX").Click += RoutedEventHandler(on_close)
    window.FindName("Header").MouseLeftButtonDown += MouseButtonEventHandler(on_drag)
    window.KeyDown += KeyEventHandler(on_key)
    window.Closed += EventHandler(on_closed)

    window.Show()
    window.Activate()
    Dispatcher.PushFrame(frame)
    return result[0]


def open_link_cad():
    cmd_id = RevitCommandId.LookupPostableCommandId(PostableCommand.LinkCAD)
    uiapp = HOST_APP.uiapp
    if cmd_id and uiapp.CanPostCommand(cmd_id):
        uiapp.PostCommand(cmd_id)   # runs after this hook returns
    else:
        log("Link CAD command could not be posted.")


# =====================================================================
# 3. GUARD CLAUSES
# =====================================================================
def should_run():
    return ENABLED


# =====================================================================
# 5. EVENT RESULT  --  cancel first, so the block holds even if the UI fails
# =====================================================================
def deny_command():
    try:
        EXEC_PARAMS.event_args.Cancel = True
        try:
            user = HOST_APP.username
        except Exception:
            user = "unknown"
        log("Import CAD denied for user '{0}'.".format(user))
        return True
    except Exception:
        log("Failed to cancel Import CAD: {0}".format(traceback.format_exc()))
        return False


# =====================================================================
# 4. PAYLOAD  +  6. ERROR CONTAINMENT
# =====================================================================
if should_run() and deny_command():
    try:
        if show_denied_dialog() == "link":
            open_link_cad()
    except Exception:
        log("Dialog failed, falling back to TaskDialog: {0}".format(traceback.format_exc()))
        try:
            TaskDialog.Show(DIALOG_TITLE, MSG_BOLD + MSG_REST)
        except Exception:
            log("Fallback TaskDialog failed: {0}".format(traceback.format_exc()))
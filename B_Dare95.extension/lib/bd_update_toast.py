# -*- coding: utf-8 -*-
"""B_Dare95 update notification.

A small non-blocking card in the bottom-right corner of the screen Revit is
on. It never takes focus, never blocks Revit, and closes with Revit.

    prepare(uiapp)            startup.py, on the UI thread, every load
    on_update_result(result)  called by bd_updater from its worker thread

"Reload now" goes through an ExternalEvent so pyRevit reloads inside a valid
Revit API context - the same way pyRevit's own Settings window triggers it.

IronPython 2.7: no f-strings, no nonlocal; unicode escapes only in u"" strings.
"""

import os

import clr
clr.AddReference('PresentationCore')
clr.AddReference('PresentationFramework')
clr.AddReference('WindowsBase')
clr.AddReference('System.Windows.Forms')

from System import Action, EventHandler, IntPtr
from System.Windows import (FontWeights, Point, PresentationSource,
                            RoutedEventHandler, TextWrapping, Thickness,
                            Visibility)
from System.Windows.Controls import TextBlock
from System.Windows.Documents import Run
from System.Windows.Forms import Screen
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Markup import XamlReader
from System.Windows.Media import BrushConverter
from System.Windows.Threading import Dispatcher, DispatcherPriority

from Autodesk.Revit.UI import ExternalEvent, IExternalEventHandler

from pyrevit.coreutils import envvars
from pyrevit.coreutils.ribbon import load_bitmapimage

import bd_updater

try:
    from pyrevit.loader import sessionmgr
except Exception:                               # very old / unusual pyRevit
    sessionmgr = None


ENV_BAG = 'BDARE95_UPDATE_UI'
RELOAD_COMMAND = 'pyrevitcore_pyrevit_pyrevit_tools_reload'
MAX_NAMES = 5
EDGE_MARGIN = 16.0

_LOGO_DARK = os.path.join(bd_updater.EXT_DIR, 'resources', 'logo_dark.png')
_LOGO = os.path.join(bd_updater.EXT_DIR, 'resources', 'logo.png')

# Catppuccin Mocha
C_TEXT = '#CDD6F4'
C_SUBTEXT = '#A6ADC8'

_REASONS = {
    'zip_no_git': u"This copy was installed without git, so it can't update itself.",
    'git_missing': u"git is no longer available on this PC, so the tools can't update themselves.",
    'git_broken': u"git is installed on this PC but could not be started.",
    'unreachable': u"The tools haven't been able to reach GitHub for several days "
                   u"(network, proxy or firewall).",
}


XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="B_Dare95" Width="400" SizeToContent="Height"
        WindowStyle="None" AllowsTransparency="True" Background="Transparent"
        ResizeMode="NoResize" ShowInTaskbar="False" ShowActivated="False"
        WindowStartupLocation="Manual" Left="-32000" Top="-32000"
        FontFamily="Segoe UI" FontSize="12.5">
  <Window.Resources>
    <Style x:Key="Btn" TargetType="Button">
      <Setter Property="Foreground" Value="#CDD6F4"/>
      <Setter Property="Background" Value="#313244"/>
      <Setter Property="Padding" Value="14,6"/>
      <Setter Property="Margin" Value="8,0,0,0"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Focusable" Value="False"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="Bd" Background="{TemplateBinding Background}"
                    CornerRadius="6" Padding="{TemplateBinding Padding}">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="Bd" Property="Opacity" Value="0.85"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style x:Key="AccentBtn" TargetType="Button" BasedOn="{StaticResource Btn}">
      <Setter Property="Background" Value="#F0A500"/>
      <Setter Property="Foreground" Value="#1E1E2E"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
    </Style>
    <Style x:Key="CloseBtn" TargetType="Button" BasedOn="{StaticResource Btn}">
      <Setter Property="Background" Value="Transparent"/>
      <Setter Property="Foreground" Value="#A6ADC8"/>
      <Setter Property="Padding" Value="6,2"/>
      <Setter Property="Margin" Value="8,0,0,0"/>
    </Style>
  </Window.Resources>

  <Border Margin="12" Background="#1E1E2E" BorderBrush="#45475A"
          BorderThickness="1" CornerRadius="10" Padding="16,14,16,14">
    <Border.Effect>
      <DropShadowEffect BlurRadius="16" ShadowDepth="2" Opacity="0.45" Color="#000000"/>
    </Border.Effect>
    <StackPanel>
      <DockPanel LastChildFill="True">
        <Button x:Name="CloseBtn" DockPanel.Dock="Right" Style="{StaticResource CloseBtn}"
                Content="&#x2715;" VerticalAlignment="Center"/>
        <Image x:Name="Logo" Width="18" Height="18" Margin="0,0,8,0"
               VerticalAlignment="Center" Stretch="Uniform"/>
        <TextBlock x:Name="TitleText" Foreground="#CDD6F4" FontSize="14"
                   FontWeight="SemiBold" VerticalAlignment="Center"
                   TextTrimming="CharacterEllipsis"/>
      </DockPanel>
      <Border Height="2" Width="36" Background="#F0A500" CornerRadius="1"
              HorizontalAlignment="Left" Margin="0,8,0,10"/>
      <StackPanel x:Name="Body"/>
      <StackPanel Orientation="Horizontal" HorizontalAlignment="Right" Margin="0,8,0,0">
        <Button x:Name="LaterBtn" Style="{StaticResource Btn}" Content="Later"/>
        <Button x:Name="ReloadBtn" Style="{StaticResource AccentBtn}" Content="Reload now"/>
      </StackPanel>
    </StackPanel>
  </Border>
</Window>
"""


# ---------------------------------------------------------------------------
# session bag (survives script-engine teardown)
# ---------------------------------------------------------------------------

def _bag():
    bag = envvars.get_pyrevit_env_var(ENV_BAG)
    if bag is None:
        bag = {}
        envvars.set_pyrevit_env_var(ENV_BAG, bag)
    return bag


# ---------------------------------------------------------------------------
# reload via ExternalEvent
# ---------------------------------------------------------------------------

class _ReloadHandler(IExternalEventHandler):
    """Runs inside a Revit API context.

    reload_pyrevit() from an ExternalEvent is exactly what pyRevit's own HTTP
    routes do; running the Reload button's command is the fallback.
    """

    def Execute(self, uiapp):
        if sessionmgr is None:
            bd_updater.log('toast', 'reload failed: pyRevit session manager is not available')
            return
        try:
            sessionmgr.reload_pyrevit()
            return
        except Exception as err:
            bd_updater.log('toast', 'reload_pyrevit failed ({0}) - trying the Reload command'.format(err))
        try:
            command = sessionmgr.find_pyrevitcmd(RELOAD_COMMAND)
            if command is None:
                raise Exception('Reload command not found')
            sessionmgr.execute_command_cls(command)
        except Exception as err:
            bd_updater.log('toast', 'reload failed: {0}'.format(err))

    def GetName(self):
        return 'B_Dare95 - reload pyRevit'


def prepare(uiapp):
    """UI thread, every load: remember the dispatcher, Revit's window and a
    fresh reload ExternalEvent (ExternalEvent.Create needs an API context)."""
    bag = _bag()
    bag['dispatcher'] = Dispatcher.CurrentDispatcher
    try:
        bag['owner'] = uiapp.MainWindowHandle
    except Exception:
        bag['owner'] = None

    handler = _ReloadHandler()
    try:
        event = ExternalEvent.Create(handler)
    except Exception as err:
        bd_updater.log('startup', 'reload button unavailable this session: {0}'.format(err))
        return
    old = bag.get('event')
    bag['event'] = event
    bag['handler'] = handler
    if old is not None:
        try:
            old.Dispose()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# worker thread -> UI thread
# ---------------------------------------------------------------------------

def on_update_result(result):
    """Called on the updater's worker thread. Never raises."""
    try:
        bag = _bag()
        dispatcher = bag.get('dispatcher')
        if dispatcher is None:
            return

        def _show():
            try:
                _show_toast(result)
            except Exception as err:
                bd_updater.log('toast', 'could not show the notification: {0}'.format(err))

        action = Action(_show)
        bag['pending_action'] = action          # keep the delegate alive
        dispatcher.BeginInvoke(DispatcherPriority.ApplicationIdle, action)
    except Exception as err:
        bd_updater.log('toast', 'could not schedule the notification: {0}'.format(err))


# ---------------------------------------------------------------------------
# building the card
# ---------------------------------------------------------------------------

_BRUSHES = BrushConverter()


def _brush(hex_color):
    return _BRUSHES.ConvertFromString(hex_color)


def _names(items):
    if len(items) <= MAX_NAMES:
        return ', '.join(items)
    return u'{0} +{1} more'.format(', '.join(items[:MAX_NAMES]), len(items) - MAX_NAMES)


def _row(body, label, text):
    block = TextBlock()
    block.TextWrapping = TextWrapping.Wrap
    block.Margin = Thickness(0, 0, 0, 6)
    if label:
        head = Run(label + u'  ')
        head.FontWeight = FontWeights.SemiBold
        head.Foreground = _brush(C_TEXT)
        block.Inlines.Add(head)
    tail = Run(text)
    tail.Foreground = _brush(C_SUBTEXT if label else C_TEXT)
    block.Inlines.Add(tail)
    body.Children.Add(block)


def _fill_updated(win, result, can_reload):
    body = win.FindName('Body')
    win.FindName('TitleText').Text = u'B_Dare95 updated'

    if result.get('converted'):
        _row(body, None, u'This copy now updates itself automatically.')
    if result.get('new'):
        _row(body, u'New tools', _names(result['new']))
    if result.get('updated'):
        _row(body, u'Updated', _names(result['updated']))
    if result.get('removed'):
        _row(body, u'Removed', _names(result['removed']))
    if not (result.get('new') or result.get('updated') or result.get('removed')
            or result.get('converted')):
        _row(body, None, u'Behind-the-scenes improvements.')

    reload_btn = win.FindName('ReloadBtn')
    later_btn = win.FindName('LaterBtn')
    if not result.get('needs_reload'):
        _row(body, None, u'Already active - nothing to do.')
        reload_btn.Visibility = Visibility.Collapsed
        later_btn.Content = u'OK'
    elif can_reload:
        _row(body, None, u'Reload pyRevit to load the changes. Your open projects stay open.')
    else:
        _row(body, None, u'Click Reload on the pyRevit tab (or restart Revit) to load the changes.')
        reload_btn.Visibility = Visibility.Collapsed
        later_btn.Content = u'OK'


def _fill_off(win, result):
    body = win.FindName('Body')
    win.FindName('TitleText').Text = u'B_Dare95 auto-updates are off'
    _row(body, None, _REASONS.get(result.get('reason'), u'The tools cannot update themselves.'))
    _row(body, None, u'Run B_Dare95_Installer.bat once to turn automatic updates back on. '
                     u'This reminder shows at most once a day.')
    win.FindName('ReloadBtn').Visibility = Visibility.Collapsed
    win.FindName('LaterBtn').Content = u'OK'


def _close_current():
    bag = _bag()
    win = bag.get('window')
    bag['window'] = None
    if win is not None:
        try:
            win.Close()
        except Exception:
            pass


def _place(win, owner):
    """Bottom-right of the monitor Revit is on, in DPI-independent units."""
    try:
        if owner is not None and owner != IntPtr.Zero:
            screen = Screen.FromHandle(owner)
        else:
            screen = Screen.PrimaryScreen
        area = screen.WorkingArea
        corner = Point(area.Right, area.Bottom)
        source = PresentationSource.FromVisual(win)
        if source is not None and source.CompositionTarget is not None:
            corner = source.CompositionTarget.TransformFromDevice.Transform(corner)
        win.Left = corner.X - win.ActualWidth - EDGE_MARGIN
        win.Top = corner.Y - win.ActualHeight - EDGE_MARGIN
    except Exception as err:
        bd_updater.log('toast', 'could not position the notification: {0}'.format(err))
        win.Left = 40
        win.Top = 40


def _show_toast(result):
    _close_current()
    bag = _bag()
    win = XamlReader.Parse(XAML)

    logo = _LOGO_DARK if os.path.isfile(_LOGO_DARK) else _LOGO
    if os.path.isfile(logo):
        try:
            win.FindName('Logo').Source = load_bitmapimage(logo)
        except Exception:
            win.FindName('Logo').Visibility = Visibility.Collapsed
    else:
        win.FindName('Logo').Visibility = Visibility.Collapsed

    event = bag.get('event')
    if result.get('kind') == 'off':
        _fill_off(win, result)
    else:
        _fill_updated(win, result, event is not None)

    def _on_reload(sender, args):
        _close_current()
        current = _bag().get('event')
        if current is None:
            return
        bd_updater.log('toast', 'user clicked "Reload now"')
        try:
            current.Raise()
        except Exception as err:
            bd_updater.log('toast', 'could not request the reload: {0}'.format(err))

    def _on_dismiss(sender, args):
        _close_current()

    def _on_loaded(sender, args):
        _place(win, bag.get('owner'))

    def _on_closed(sender, args):
        if _bag().get('window') is win:
            _bag()['window'] = None

    handlers = {
        'reload': RoutedEventHandler(_on_reload),
        'dismiss': RoutedEventHandler(_on_dismiss),
        'loaded': RoutedEventHandler(_on_loaded),
        'closed': EventHandler(_on_closed),       # Window.Closed is a plain EventHandler
    }
    win.FindName('ReloadBtn').Click += handlers['reload']
    win.FindName('LaterBtn').Click += handlers['dismiss']
    win.FindName('CloseBtn').Click += handlers['dismiss']
    win.Loaded += handlers['loaded']
    win.Closed += handlers['closed']

    owner = bag.get('owner')
    if owner is not None and owner != IntPtr.Zero:
        try:
            WindowInteropHelper(win).Owner = owner  # floats over Revit, closes with it
        except Exception:
            pass

    bag['window'] = win
    bag['window_handlers'] = handlers               # keep delegates alive
    win.Show()

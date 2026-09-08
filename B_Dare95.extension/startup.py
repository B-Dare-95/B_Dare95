# -*- coding: utf-8 -*-
"""Injects the B_Dare95 logo into the ribbon tab header.

Runs automatically when pyRevit loads the extension. No user interaction.

Placement:
    B_Dare95.extension/startup.py
    B_Dare95.extension/resources/logo.png        (required)
    B_Dare95.extension/resources/logo_dark.png   (optional, dark theme)

There is no Revit API or pyRevit feature for tab icons. This reaches into the
WPF visual tree behind ComponentManager.Ribbon and inserts an Image into the
tab header's StackPanel, ahead of the title TextBlock.

Three internal Autodesk template names carry the whole thing:
    RibbonTabButton   the tab header element type
    mStackPanel       the panel holding the header content
    mContent          the TextBlock holding the tab title

They are not public API. Everything is defensive because they can change
between Revit versions, and because an exception thrown out of startup.py is
loud and can disrupt the extension load.
"""

import os

import clr

clr.AddReference('AdWindows')
clr.AddReference('PresentationCore')
clr.AddReference('PresentationFramework')
clr.AddReference('WindowsBase')

from System import Action, EventHandler, Object, TimeSpan
from System.Windows import (HorizontalAlignment, PresentationSource,
                            RoutedEventHandler, SizeChangedEventHandler,
                            Thickness, VerticalAlignment)
from System.Windows.Controls import Image, Orientation, Panel, StackPanel, TextBlock
from System.Windows.Media import Stretch, VisualTreeHelper
from System.Windows.Threading import DispatcherPriority, DispatcherTimer

from Autodesk.Windows import ComponentManager

from pyrevit import script
from pyrevit.coreutils import envvars
from pyrevit.coreutils.ribbon import load_bitmapimage


logger = script.get_logger()


# ---------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------

# Must match the .tab folder name (or its bundle.yaml title).
TAB_NAME = 'B-Dare95'

ICON_TAG = 'BDare95.RibbonTabIcon'
ICON_SIZE = 16.0        # displayed size; ship the PNG at 32 or 64 px
ICON_GAP = 4.0          # gap between icon and title
MAX_ATTEMPTS = 12
RETRY_MS = 120

_HERE = os.path.dirname(__file__)
LIGHT_ICON = os.path.join(_HERE, 'resources', 'logo.png')
DARK_ICON = os.path.join(_HERE, 'resources', 'logo_dark.png')

# Script engines are torn down after a run, so the icon reference, the event
# handlers and the retry timer are parked in envvars (AppDomain-backed) to keep
# them alive for the whole Revit session.
ENV_ICON = 'BDARE95_TABICON'
ENV_STATE = 'BDARE95_TABICON_STATE'


def _state():
    """Session-wide mutable state bag."""
    bag = envvars.get_pyrevit_env_var(ENV_STATE)
    if bag is None:
        bag = {'retry_pending': False, 'watched_ribbon': None}
        envvars.set_pyrevit_env_var(ENV_STATE, bag)
    return bag


# ---------------------------------------------------------------------------
# theme
# ---------------------------------------------------------------------------

def _icon_path():
    """Dark variant when Revit is dark and the file exists, else the default."""
    if os.path.isfile(DARK_ICON):
        try:
            from Autodesk.Revit.UI import UIThemeManager, UITheme
            if UIThemeManager.CurrentTheme == UITheme.Dark:
                return DARK_ICON
        except Exception as err:
            logger.debug('tab icon: theme probe failed: %s', err)
    return LIGHT_ICON


def _on_theme_changed(sender, args):
    icon = envvars.get_pyrevit_env_var(ENV_ICON)
    if icon is None:
        return
    try:
        icon.Source = load_bitmapimage(_icon_path())
    except Exception as err:
        logger.debug('tab icon: theme swap failed: %s', err)


def _subscribe_theme(uiapp):
    """Only worth wiring up if there is a dark variant to swap to."""
    if not os.path.isfile(DARK_ICON):
        return
    bag = _state()
    if bag.get('themechanged') is not None:
        return
    try:
        from Autodesk.Revit.UI.Events import ThemeChangedEventArgs
        handler = EventHandler[ThemeChangedEventArgs](_on_theme_changed)
        uiapp.ThemeChanged += handler
        bag['themechanged'] = handler
    except Exception as err:
        logger.debug('tab icon: ThemeChanged unavailable: %s', err)


# ---------------------------------------------------------------------------
# visual tree walking
# ---------------------------------------------------------------------------

def _child_count(node):
    try:
        return VisualTreeHelper.GetChildrenCount(node)
    except Exception:
        return 0    # not a Visual / Visual3D


def _find_descendant(root, wanted_type, name=None):
    """Depth-first search for the first element of a type, optionally by Name."""
    if root is None:
        return None
    if isinstance(root, wanted_type):
        if name is None or root.Name == name:
            return root
    for i in range(_child_count(root)):
        found = _find_descendant(VisualTreeHelper.GetChild(root, i),
                                 wanted_type, name)
        if found is not None:
            return found
    return None


def _find_tab(tab_name):
    """Returns (ribbon, tab). Either may be None early in the session."""
    ribbon = ComponentManager.Ribbon
    if ribbon is None:
        return None, None
    for tab in ribbon.Tabs:
        if tab.Name == tab_name:
            return ribbon, tab
    return ribbon, None


def _find_tab_button(root, tab, tab_name):
    """Breadth-first search for the RibbonTabButton belonging to this tab.

    Preferred match is DataContext identity. Title-text match is the fallback
    for when the button exists but is not yet bound.
    """
    fallback = None
    queue = [root]
    while queue:
        node = queue.pop(0)
        try:
            is_tab_button = node.GetType().Name == 'RibbonTabButton'
        except Exception:
            is_tab_button = False
        if is_tab_button:
            if Object.ReferenceEquals(node.DataContext, tab):
                return node
            if fallback is None:
                label = _find_descendant(node, TextBlock, 'mContent')
                if label is not None and label.Text == tab_name:
                    fallback = node
        for i in range(_child_count(node)):
            queue.append(VisualTreeHelper.GetChild(node, i))
    return fallback


def _find_header_panel(tab_button):
    """The panel the icon gets inserted into."""
    panel = _find_descendant(tab_button, StackPanel, 'mStackPanel')
    if panel is not None:
        return panel
    label = (_find_descendant(tab_button, TextBlock, 'mContent')
             or _find_descendant(tab_button, TextBlock))
    if label is None:
        return None
    parent = VisualTreeHelper.GetParent(label)
    return parent if isinstance(parent, Panel) else None


# ---------------------------------------------------------------------------
# liveness
# ---------------------------------------------------------------------------

def _icon_alive():
    """True only if the tracked icon is still connected to a rendered surface."""
    icon = envvars.get_pyrevit_env_var(ENV_ICON)
    if icon is None:
        return False
    try:
        return PresentationSource.FromVisual(icon) is not None
    except Exception:
        return False


def _tagged_icon(panel):
    for child in panel.Children:
        if isinstance(child, Image) and child.Tag == ICON_TAG:
            return child
    return None


# ---------------------------------------------------------------------------
# injection
# ---------------------------------------------------------------------------

def _inject(panel):
    if isinstance(panel, StackPanel):
        panel.Orientation = Orientation.Horizontal

    icon = _tagged_icon(panel)
    if icon is None:
        icon = Image()
        icon.Tag = ICON_TAG              # marker: only ever touch our own element
        icon.Stretch = Stretch.Uniform
        icon.VerticalAlignment = VerticalAlignment.Center
        icon.HorizontalAlignment = HorizontalAlignment.Center
        icon.IsHitTestVisible = False    # never steal clicks from the tab
        icon.Focusable = False
        panel.Children.Insert(0, icon)   # index 0 puts it before the title

    icon.Source = load_bitmapimage(_icon_path())
    icon.Width = ICON_SIZE
    icon.Height = ICON_SIZE
    icon.Margin = Thickness(0.0, 0.0, ICON_GAP, 0.0)

    for child in panel.Children:
        try:
            child.VerticalAlignment = VerticalAlignment.Center
        except Exception:
            pass

    envvars.set_pyrevit_env_var(ENV_ICON, icon)
    _watch_icon(icon)


# ---------------------------------------------------------------------------
# keeping it there
# ---------------------------------------------------------------------------

def _unloaded_handler():
    bag = _state()
    handler = bag.get('unloaded')
    if handler is None:
        handler = RoutedEventHandler(_on_icon_unloaded)
        bag['unloaded'] = handler
    return handler


def _on_icon_unloaded(sender, args):
    """Revit tears down and rebuilds tab headers on its own schedule."""
    try:
        sender.Unloaded -= _unloaded_handler()
    except Exception:
        pass
    envvars.set_pyrevit_env_var(ENV_ICON, None)
    try:
        _schedule_retry(sender.Dispatcher, 2)
    except Exception as err:
        logger.debug('tab icon: reschedule after unload failed: %s', err)


def _watch_icon(icon):
    handler = _unloaded_handler()
    try:
        icon.Unloaded -= handler
        icon.Unloaded += handler
    except Exception as err:
        logger.debug('tab icon: could not watch Unloaded: %s', err)


def _on_ribbon_size_changed(sender, args):
    if _icon_alive():
        return
    try:
        _schedule_retry(sender.Dispatcher, 2)
    except Exception as err:
        logger.debug('tab icon: reschedule after resize failed: %s', err)


def _watch_ribbon(ribbon):
    bag = _state()
    if Object.ReferenceEquals(bag.get('watched_ribbon'), ribbon):
        return
    handler = bag.get('sizechanged')
    if handler is None:
        handler = SizeChangedEventHandler(_on_ribbon_size_changed)
        bag['sizechanged'] = handler
    try:
        ribbon.SizeChanged -= handler
        ribbon.SizeChanged += handler
        bag['watched_ribbon'] = ribbon
    except Exception as err:
        logger.debug('tab icon: could not watch SizeChanged: %s', err)


def _schedule_retry(dispatcher, attempt):
    """First attempt rides the dispatcher queue; later ones use a short timer."""
    bag = _state()
    if attempt > MAX_ATTEMPTS or dispatcher is None or bag.get('retry_pending'):
        return
    bag['retry_pending'] = True

    if attempt < 2:
        def _run():
            bag['retry_pending'] = False
            _try_apply(attempt)

        action = Action(_run)
        bag['pending_action'] = action
        dispatcher.BeginInvoke(DispatcherPriority.Background, action)
        return

    def _tick(sender, args):
        sender.Stop()
        bag['retry_pending'] = False
        bag['timer'] = None
        if _icon_alive():
            return
        _try_apply(attempt)

    timer = DispatcherTimer(DispatcherPriority.Background, dispatcher)
    timer.Interval = TimeSpan.FromMilliseconds(RETRY_MS)
    tick = EventHandler(_tick)
    timer.Tick += tick
    bag['timer'] = timer
    bag['timer_handler'] = tick
    timer.Start()


def _try_apply(attempt):
    """One attempt at finding the header panel and injecting the icon."""
    try:
        ribbon, tab = _find_tab(TAB_NAME)
        if ribbon is None:
            return                       # ribbon not up yet, SizeChanged will retry
        _watch_ribbon(ribbon)

        if tab is None:
            _schedule_retry(ribbon.Dispatcher, attempt + 1)
            return

        button = _find_tab_button(ribbon, tab, TAB_NAME)
        panel = _find_header_panel(button) if button is not None else None
        if panel is None:
            # Tab exists but its header visual is not realized yet.
            _schedule_retry(ribbon.Dispatcher, attempt + 1)
            return

        _inject(panel)
    except Exception as err:
        logger.debug('tab icon: attempt %s failed: %s', attempt, err)


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

try:
    if os.path.isfile(LIGHT_ICON):
        _try_apply(0)
        _subscribe_theme(__revit__)      # noqa: F821 - injected by pyRevit
    else:
        logger.debug('tab icon: %s not found, skipping', LIGHT_ICON)
except Exception as err:
    logger.debug('tab icon: startup failed: %s', err)

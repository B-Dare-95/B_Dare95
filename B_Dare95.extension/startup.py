# -*- coding: utf-8 -*-
"""B_Dare95 extension startup: auto-update + ribbon tab logo + room tracking.

Runs automatically every time pyRevit loads the extension (Revit start and
every pyRevit Reload). No user interaction.

1. Auto-update  (lib/bd_updater.py + lib/bd_update_toast.py)
    Only on the installer's copy (%LOCALAPPDATA%\\B_Dare95_dist), never on a
    development folder. A background thread brings the copy to exactly what is
    on GitHub (fetch + forced checkout of origin/main), repairing a dirty,
    diverged or ZIP install on the way. It never blocks the load.
    When new commits arrive, a small notification lists the new/updated tools
    and offers "Reload now"; a ZIP/no-git install gets a daily reminder to run
    the installer. While Revit stays open, GitHub is checked again every hour
    and the same notification appears on its own when you push something new.
    hooks/app-closing.py updates again as Revit exits, so the
    next start opens on the new version. Every outcome is logged to
    %LOCALAPPDATA%\\B_Dare95\\update.log.

2. Tab logo

3. Room Register live tracking
    Arms the room tracker from lib/room_register.py, so room changes are
    recorded in every session without anyone clicking the Room Register
    button. The tracker parks itself in envvars under its own key and replaces
    any tracker from a previous load, so a pyRevit Reload never subscribes its
    events twice.

4. Native-tab panels
    Moves chosen B-Dare95 panels (e.g. B95-Monitoring) into Revit's own tabs
    such as Collaborate. Before pyRevit rebuilds the ribbon on a Reload, the
    panels are sent back to the B-Dare95 tab so pyRevit can update and colour
    them; on Revit's first idle moment they move out again.
    Panels listed as contextual (e.g. B95-Selection) live in the Modify tab
    and only show while something is selected, optionally only for chosen
    categories, driven by UIApplication.SelectionChanged (Revit 2023+).

Placement:
    B_Dare95.extension/startup.py
    B_Dare95.extension/resources/logo.png        (required)
    B_Dare95.extension/resources/logo_dark.png   (optional, dark theme)
    B_Dare95.extension/lib/room_register.py      (Room Register core)
    B_Dare95.extension/lib/bd_updater.py         (auto-update core)
    B_Dare95.extension/lib/bd_update_toast.py    (update notification)
    B_Dare95.extension/hooks/app-closing.py      (update on Revit close)

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

clr.AddReference('System')
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
MULTI_CATEGORY = 'multi-category'   # contextual panel rule, see _b95_panel_mover

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
# auto-update
# ---------------------------------------------------------------------------

def _auto_update(uiapp):
    """Starts the background updater; the notification is optional."""
    import bd_updater                    # lib/bd_updater.py
    if not bd_updater.is_install_copy():
        bd_updater.note_skipped()        # dev copy (or a stray second copy)
        return
    callback = None
    try:
        import bd_update_toast           # lib/bd_update_toast.py
        bd_update_toast.prepare(uiapp)
        callback = bd_update_toast.on_update_result
    except Exception as err:             # updates still run without the UI
        bd_updater.log('startup', 'notification unavailable: {0}'.format(err))
    bd_updater.start_background_update(callback)


def _log_auto_update_failure(err):
    logger.debug('auto-update: failed: %s', err)
    try:
        import bd_updater
        bd_updater.log('startup', 'auto-update could not start: {0}'.format(err))
    except Exception:
        pass


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
# room register live tracking
# ---------------------------------------------------------------------------

def _arm_room_register(uiapp):
    """Arms the Room Register tracker for this Revit session."""
    import room_register                 # lib/room_register.py
    room_register.rearm_tracker(uiapp, 'startup')


def _log_room_register_failure(err):
    """pyRevit debug log plus the register's own tracker.log, where users look."""
    logger.debug('room register: arming failed: %s', err)
    try:
        import room_register
        room_register._log('Startup arming failed: {0}'.format(err))
    except Exception:
        pass

# ---------------------------------------------------------------------------
# native-tab panels + contextual panels
# ---------------------------------------------------------------------------
# Everything lives inside one uniquely named function, so none of its helper
# names can overwrite the module-level helpers above (e.g. the logo's
# _find_tab, which its delayed retries look up by name).

def _b95_panel_mover(uiapp):
    """Moves B-Dare95 panels into Revit's native tabs, and shows contextual
    panels only while something is selected."""
    from System import Array
    from System.Collections.Generic import List
    from Autodesk.Revit.DB import (BuiltInCategory, ElementId,
                                   ElementMulticategoryFilter,
                                   FilteredElementCollector)

    # (panel folder name without ".panel", native tab to move it into)
    panel_moves = [
        ('Monitoring', 'Collaborate'),
        ('B95-Walls', 'Modify'),
        ('B95-Floors', 'Modify'),
        ('B95-Shafts', 'Modify'),
        ('B95-Ceilings', 'Modify'),
        ('B95-Rooms', 'Modify'),
    ]

    # Panels that only show while elements are selected. They live in the
    # Modify tab while shown: Revit merges the Modify tab into every
    # "Modify | <Category>" tab it shows for a selection.
    #   None                        -> any selection
    #   ['OST_Walls', 'OST_Floors'] -> when the selection holds one of these
    #   MULTI_CATEGORY              -> when the selection holds 2+ categories
    #                                  (kept available, not used right now)
    # Several panels can show at once, e.g. selecting a wall shows B95-Walls
    # and B95-Selection together.
    contextual_panels = {
        'B95-Walls': ['OST_Walls'],
        'B95-Floors': ['OST_Floors'],
        'B95-Shafts': ['OST_ShaftOpening'],
        'B95-Ceilings': ['OST_Ceilings'],
        'B95-Rooms': ['OST_Rooms'],
        'B95-Selection': None,
    }

    # contextual panels are always moved into 'Modify'; no need to repeat them
    # in panel_moves above
    panel_moves = panel_moves + [(title, 'Modify') for title in contextual_panels
                                 if (title, 'Modify') not in panel_moves]

    env_key = 'BDARE95_CONTEXT_PANELS'
    state = {'done': False}

    def find_tab(name):
        ribbon = ComponentManager.Ribbon
        if ribbon is None:
            return None
        for tab in ribbon.Tabs:
            if tab.Id == name or tab.Title == name:
                return tab
        return None

    def find_panel(tab, title):
        for panel in tab.Panels:
            if panel.Source is not None and panel.Source.Title == title:
                return panel
        return None

    # -- moving panels ------------------------------------------------------

    def send_home():
        # startup.py runs before pyRevit rebuilds the ribbon. On a Reload, put
        # moved panels back in our tab so pyRevit can find, update and colour
        # them. On a cold start the ribbon isn't built yet: nothing to return.
        source = find_tab(TAB_NAME)
        if source is None:
            return
        for panel_title, target_name in panel_moves:
            target = find_tab(target_name)
            if target is None:
                continue
            panel = find_panel(target, panel_title)
            if panel is None:
                continue
            target.Panels.Remove(panel)
            source.Panels.Add(panel)

    def move_out():
        source = find_tab(TAB_NAME)
        if source is None:
            return
        for panel_title, target_name in panel_moves:
            if panel_title in contextual_panels:
                continue                 # placed by refresh(), see below
            target = find_tab(target_name)
            if target is None or find_panel(target, panel_title) is not None:
                continue
            panel = find_panel(source, panel_title)
            if panel is None:
                continue
            source.Panels.Remove(panel)
            target.Panels.Add(panel)

    # -- contextual visibility ---------------------------------------------

    def build_category_filters():
        filters = {}
        for title, names in contextual_panels.items():
            if names is None or names == MULTI_CATEGORY:
                filters[title] = names
                continue
            cats = List[BuiltInCategory]()
            for name in names:
                try:
                    cats.Add(getattr(BuiltInCategory, name))
                except Exception:
                    logger.debug('contextual panels: unknown category %s', name)
            filters[title] = ElementMulticategoryFilter(cats) if cats.Count else False
        return filters

    category_filters = build_category_filters()

    def spans_categories(doc, ids):
        # True as soon as two different categories are found
        first = None
        for eid in ids:
            el = doc.GetElement(eid)
            cat = el.Category if el is not None else None
            if cat is None:
                continue
            if first is None:
                first = cat.Id
            elif cat.Id != first:
                return True
        return False

    def selection_matches(doc, ids, cat_filter):
        if cat_filter is None:
            return True                  # any selection
        if cat_filter == MULTI_CATEGORY:
            return spans_categories(doc, ids)
        if cat_filter is False:
            return False                 # no valid categories configured
        try:
            hit = (FilteredElementCollector(doc, List[ElementId](ids))
                   .WherePasses(cat_filter)
                   .FirstElementId())
            return hit != ElementId.InvalidElementId
        except Exception as err:
            logger.debug('contextual panels: category check failed: %s', err)
            return False

    def refresh(doc, ids):
        # Revit's "Modify | <Category>" tab ignores IsVisible on the Modify
        # tab's panels (the debug log showed them hidden while Revit still drew
        # them). So a contextual panel is shown by moving it INTO the Modify
        # tab, and hidden by moving it back to our tab and hiding it there,
        # where IsVisible is respected.
        modify_tab = find_tab('Modify')
        home_tab = find_tab(TAB_NAME)
        if modify_tab is None or home_tab is None:
            return
        has_selection = doc is not None and ids is not None and ids.Count > 0
        for title, cat_filter in category_filters.items():
            in_modify = find_panel(modify_tab, title)
            at_home = find_panel(home_tab, title)
            panel = in_modify or at_home
            if panel is None:
                continue                 # not built yet (startup / reload)
            show = has_selection and selection_matches(doc, ids, cat_filter)
            if show:
                if in_modify is None:
                    home_tab.Panels.Remove(panel)
                    modify_tab.Panels.Add(panel)
                if not panel.IsVisible:
                    panel.IsVisible = True
            else:
                if in_modify is not None:
                    modify_tab.Panels.Remove(panel)
                    home_tab.Panels.Add(panel)
                if panel.IsVisible:
                    panel.IsVisible = False

    def current_selection():
        try:
            uidoc = uiapp.ActiveUIDocument
        except Exception:
            uidoc = None
        if uidoc is None:
            return None, None
        return uidoc.Document, uidoc.Selection.GetElementIds()

    def deferred_refresh():
        try:
            doc, ids = current_selection()
            refresh(doc, ids)
        except Exception as err:
            logger.debug('contextual panels: refresh failed: %s', err)

    def on_selection_changed(sender, args):
        # Place the panels now, so Revit merges the right ones into the
        # "Modify | <Category>" tab it is about to build, and once more after
        # Revit has finished (ContextIdle) in case it reshuffled anything.
        deferred_refresh()
        try:
            from System.Windows.Threading import Dispatcher
            Dispatcher.CurrentDispatcher.BeginInvoke(DispatcherPriority.ContextIdle,
                                                     Action(deferred_refresh))
        except Exception as err:
            logger.debug('contextual panels: could not schedule refresh: %s', err)

    def watch_selection():
        # Drop the handler from a previous load first, so a pyRevit Reload
        # never stacks a second listener. The handler is parked in envvars so
        # it outlives this script engine, like the logo's handlers.
        # pyRevit's envvars did not survive a Reload here (the debug log showed
        # every reload adding one more listener), so the handler is parked in
        # the AppDomain itself, which lives as long as Revit.
        from System import AppDomain
        domain = AppDomain.CurrentDomain
        old = domain.GetData(env_key)
        if old is not None:
            try:
                old[0].SelectionChanged -= old[1]
            except Exception:
                pass
            domain.SetData(env_key, None)
        if not contextual_panels:
            return
        try:
            from Autodesk.Revit.UI.Events import SelectionChangedEventArgs
            handler = EventHandler[SelectionChangedEventArgs](on_selection_changed)
            uiapp.SelectionChanged += handler
            domain.SetData(env_key, Array[Object]([uiapp, handler]))
        except Exception as err:
            logger.debug('contextual panels: SelectionChanged unavailable: %s', err)

    # -- wiring -------------------------------------------------------------

    def on_idling(sender, args):
        # pyRevit has built the ribbon by Revit's first idle moment.
        if state['done']:
            return
        state['done'] = True
        try:
            uiapp.Idling -= on_idling
        except Exception:
            pass
        try:
            move_out()
        except Exception as err:
            logger.debug('panel mover: move failed: %s', err)
        try:
            doc, ids = current_selection()
            refresh(doc, ids)            # hide contextual panels right away
        except Exception as err:
            logger.debug('contextual panels: first refresh failed: %s', err)

    try:
        send_home()
    except Exception as err:
        logger.debug('panel mover: return home failed: %s', err)

    try:
        watch_selection()
    except Exception as err:
        logger.debug('contextual panels: setup failed: %s', err)

    uiapp.Idling += on_idling



# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

# Kept in separate try blocks so a failure in one never stops the others.
try:
    _auto_update(__revit__)              # noqa: F821 - injected by pyRevit
except Exception as err:
    _log_auto_update_failure(err)

try:
    if os.path.isfile(LIGHT_ICON):
        _try_apply(0)
        _subscribe_theme(__revit__)      # noqa: F821 - injected by pyRevit
    else:
        logger.debug('tab icon: %s not found, skipping', LIGHT_ICON)
except Exception as err:
    logger.debug('tab icon: startup failed: %s', err)

try:
    _arm_room_register(__revit__)        # noqa: F821 - injected by pyRevit
except Exception as err:
    _log_room_register_failure(err)
# --- Change Tracker: refresh on document open / sync / reload latest ---
try:
    import change_tracker
    change_tracker.arm(__revit__.Application)
except Exception:
    try:
        import change_tracker
        change_tracker.log_error("startup arming")
    except Exception:
        pass
# --- BIM Brother Links: refresh monitored links on host open / link reload ---
try:
    import link_tracker
    link_tracker.arm(__revit__.Application)
except Exception:
    try:
        import change_tracker
        change_tracker.log_error("startup arming (links)")
    except Exception:
        pass

# --- Native-tab panels: move B-Dare95 panels into Revit's own tabs ---
try:
    _b95_panel_mover(__revit__)          # noqa: F821 - injected by pyRevit
except Exception as err:
    logger.debug('panel mover: startup failed: %s', err)
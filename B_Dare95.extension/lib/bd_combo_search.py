# -*- coding: utf-8 -*-
"""Search box for the dropdowns (ComboBoxes) in B_Dare95 windows.

WPF windows - one call per window, before Show() / ShowDialog():

    from bd_combo_search import enable_combo_search
    enable_combo_search(window)

    When a dropdown opens, a "Search..." box sits at the top of its list and
    filters the items as you type (not case-sensitive, every word you type must
    appear). It covers dropdowns written in the XAML and dropdowns created later
    in code (table rows, grid cells), with or without a custom ComboBox template.
    The filter is cleared when the dropdown closes, and typing alone never
    changes the selection (only clicking an item or pressing Enter does).

    Keys in the search box:  Down = move into the list,  Enter = pick the first
    match,  Esc = close.

WinForms dropdowns - one call per ComboBox:

    from bd_combo_search import enable_winforms_combo_search
    enable_winforms_combo_search(combo)

    Opening the dropdown shows a small list with a search box on top instead of
    the plain Windows list.
"""

import clr
clr.AddReference('PresentationCore')
clr.AddReference('PresentationFramework')
clr.AddReference('WindowsBase')

from System import Action
from System.Windows import (
    UIElement, Thickness, Visibility, HorizontalAlignment, VerticalAlignment,
    DependencyObject, LogicalTreeHelper, RoutedEventHandler,
)
from System.Windows.Controls import (
    ComboBox, ComboBoxItem, ContentControl, ContentPresenter, Decorator, Dock,
    DockPanel, Grid, ItemsPresenter, Panel, ScrollViewer, TextBlock, TextBox,
    TextChangedEventHandler, TextSearch, VirtualizingPanel,
)
from System.Windows.Controls.Primitives import GeneratorStatus, Popup
from System.Windows.Input import Key, KeyEventHandler, Keyboard, MouseButtonEventHandler
from System.Windows.Markup import XamlReader
from System.Windows.Media import Color, FontFamily, SolidColorBrush, Visual, VisualTreeHelper
from System.Windows.Threading import DispatcherPriority


HOST_NAME = 'bdComboSearchHost'

# IBM Carbon colours. The dark set is used on dark dropdown lists, the light
# set on white ones (e.g. dropdowns that keep the default Windows look).
_DARK = {
    'bg':    '#262626', 'bg_alt': '#393939', 'fg': '#F4F4F4',
    'hint':  '#A8A8A8', 'line':   '#525252', 'focus': '#F1C21B',
}
_LIGHT = {
    'bg':    '#F4F4F4', 'bg_alt': '#FFFFFF', 'fg': '#161616',
    'hint':  '#6F6F6F', 'line':   '#C6C6C6', 'focus': '#0F62FE',
}

_BOX_TEMPLATE_XAML = u"""
<ControlTemplate xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
                 xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
                 TargetType="TextBox">
  <Border Background="{TemplateBinding Background}"
          BorderBrush="{TemplateBinding BorderBrush}"
          BorderThickness="{TemplateBinding BorderThickness}"
          SnapsToDevicePixels="True">
    <ScrollViewer x:Name="PART_ContentHost" Focusable="False"
                  Margin="{TemplateBinding Padding}" VerticalAlignment="Center"
                  HorizontalScrollBarVisibility="Hidden"
                  VerticalScrollBarVisibility="Hidden"/>
  </Border>
</ControlTemplate>
"""
_BOX_TEMPLATE = [None]


# ═══════════════════════════════════════════════════════════════════════════
#  SMALL HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _brush(hex_str):
    h = hex_str.lstrip('#')
    brush = SolidColorBrush(Color.FromRgb(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)))
    brush.Freeze()
    return brush


def _luminance(brush):
    """0 (black) .. 1 (white) for an opaque solid brush, None otherwise."""
    try:
        c = brush.Color
    except Exception:
        return None
    if c.A < 60:
        return None
    return (0.2126 * c.R + 0.7152 * c.G + 0.0722 * c.B) / 255.0


def _box_template():
    if _BOX_TEMPLATE[0] is None:
        _BOX_TEMPLATE[0] = XamlReader.Parse(_BOX_TEMPLATE_XAML)
    return _BOX_TEMPLATE[0]


def _content_text(obj):
    """Readable text of an item / item content."""
    if obj is None:
        return u''
    if isinstance(obj, basestring):
        return obj
    if isinstance(obj, TextBlock):
        return obj.Text or u''
    if isinstance(obj, ContentControl):
        return _content_text(obj.Content)
    if isinstance(obj, Decorator):
        return _content_text(obj.Child)
    if isinstance(obj, Panel):
        return u' '.join(_content_text(ch) for ch in obj.Children)
    if isinstance(obj, UIElement):
        return u''
    try:
        return unicode(obj)
    except Exception:
        return u''


def _item_text(combo, item):
    try:
        if isinstance(item, ComboBoxItem):
            text = TextSearch.GetText(item)
            if text:
                return text
            return _content_text(item.Content)
        path = combo.DisplayMemberPath or TextSearch.GetTextPath(combo)
        if path:
            obj = item
            for part in path.split('.'):
                obj = getattr(obj, part)
            return _content_text(obj)
        return _content_text(item)
    except Exception:
        try:
            return unicode(item)
        except Exception:
            return u''


def _matches(text, terms):
    low = (text or u'').lower()
    for term in terms:
        if term not in low:
            return False
    return True


# ═══════════════════════════════════════════════════════════════════════════
#  FINDING THE DROPDOWN LIST INSIDE A COMBOBOX TEMPLATE
# ═══════════════════════════════════════════════════════════════════════════

def _visual_children(el):
    try:
        count = VisualTreeHelper.GetChildrenCount(el)
    except Exception:
        return []
    return [VisualTreeHelper.GetChild(el, i) for i in range(count)]


def _find_popup(combo):
    try:
        combo.ApplyTemplate()
    except Exception:
        pass
    stack = [combo]
    while stack:
        el = stack.pop()
        if isinstance(el, Popup):
            return el
        stack.extend(_visual_children(el))
    for name in ('PART_Popup', 'Popup'):
        try:
            found = combo.Template.FindName(name, combo)
            if isinstance(found, Popup):
                return found
        except Exception:
            pass
    return None


def _tree_children(el):
    """Children by property, so it works before the popup content is shown."""
    if isinstance(el, ScrollViewer):
        return []
    if isinstance(el, Decorator):
        return [el.Child] if el.Child is not None else []
    if isinstance(el, Panel):
        return list(el.Children)
    if isinstance(el, (ContentControl, ContentPresenter)) and isinstance(el.Content, UIElement):
        return [el.Content]
    return []


def _find_list(root):
    """(list element, its parent, chain root->parent) for the scrolling list
    inside the popup: the ScrollViewer, else the ItemsPresenter, else the
    items panel. (None, None, []) when nothing suitable is found."""
    for wanted in (ScrollViewer, ItemsPresenter):
        stack = [(root, None, [])]
        while stack:
            el, parent, chain = stack.pop()
            if isinstance(el, wanted):
                return el, parent, chain
            for ch in reversed(_tree_children(el)):
                stack.append((ch, el, chain + [el]))
    stack = [(root, None, [])]
    while stack:
        el, parent, chain = stack.pop()
        if isinstance(el, Panel) and el.IsItemsHost:
            return el, parent, chain
        for ch in reversed(_tree_children(el)):
            stack.append((ch, el, chain + [el]))
    return None, None, []


def _has_host(root):
    stack = [root]
    while stack:
        el = stack.pop()
        if getattr(el, 'Name', None) == HOST_NAME:
            return True
        stack.extend(_tree_children(el))
    return False


def _palette(combo, chain):
    for el in reversed(chain):
        lum = _luminance(getattr(el, 'Background', None))
        if lum is not None:
            return _DARK if lum < 0.5 else _LIGHT, lum
    lum = _luminance(getattr(combo, 'Background', None))
    if lum is not None:
        return _DARK if lum < 0.5 else _LIGHT, lum
    return _LIGHT, 1.0


# ═══════════════════════════════════════════════════════════════════════════
#  WPF: MAKE ONE COMBOBOX SEARCHABLE
# ═══════════════════════════════════════════════════════════════════════════

def _build_search_ui(pal, popup_lum):
    if pal is _DARK:
        bg = pal['bg'] if popup_lum < 0.12 else pal['bg_alt']
    else:
        bg = pal['bg'] if popup_lum > 0.9 else pal['bg_alt']
    line_brush  = _brush(pal['line'])
    focus_brush = _brush(pal['focus'])

    grid = Grid()

    box = TextBox()
    box.Template        = _box_template()
    box.Background      = _brush(bg)
    box.Foreground      = _brush(pal['fg'])
    box.CaretBrush      = _brush(pal['fg'])
    box.BorderBrush     = line_brush
    box.BorderThickness = Thickness(0, 0, 0, 1)
    box.Padding         = Thickness(26, 6, 8, 6)
    box.FontSize        = 12
    box.MinWidth        = 60

    icon = TextBlock()
    icon.Text                = u'\uE721'
    icon.FontFamily          = FontFamily(u'Segoe MDL2 Assets')
    icon.FontSize            = 11
    icon.Foreground          = _brush(pal['hint'])
    icon.Margin              = Thickness(9, 0, 0, 1)
    icon.HorizontalAlignment = HorizontalAlignment.Left
    icon.VerticalAlignment   = VerticalAlignment.Center
    icon.IsHitTestVisible    = False

    hint = TextBlock()
    hint.Text                = u'Search\u2026'
    hint.FontSize            = 12
    hint.Foreground          = _brush(pal['hint'])
    hint.Margin              = Thickness(28, 0, 0, 1)
    hint.HorizontalAlignment = HorizontalAlignment.Left
    hint.VerticalAlignment   = VerticalAlignment.Center
    hint.IsHitTestVisible    = False

    def on_focus(s, e):
        box.BorderBrush = focus_brush

    def on_blur(s, e):
        box.BorderBrush = line_brush

    box.GotKeyboardFocus  += on_focus
    box.LostKeyboardFocus += on_blur

    grid.Children.Add(box)
    grid.Children.Add(icon)
    grid.Children.Add(hint)
    return grid, box, hint, _brush(bg)


def _insert_host(popup, root, target, parent, search_root, bg_brush):
    host = DockPanel()
    host.Name          = HOST_NAME
    host.LastChildFill = True
    DockPanel.SetDock(search_root, Dock.Top)

    if target is None or parent is None:
        popup.Child = None
        host.Background = bg_brush
        host.Children.Add(search_root)
        host.Children.Add(root)
        popup.Child = host
    elif isinstance(parent, Decorator):
        parent.Child = None
        host.Children.Add(search_root)
        host.Children.Add(target)
        parent.Child = host
    elif isinstance(parent, Panel):
        idx = parent.Children.IndexOf(target)
        for prop in (Grid.RowProperty, Grid.ColumnProperty,
                     Grid.RowSpanProperty, Grid.ColumnSpanProperty):
            host.SetValue(prop, target.GetValue(prop))
        parent.Children.RemoveAt(idx)
        host.Children.Add(search_root)
        host.Children.Add(target)
        parent.Children.Insert(idx, host)
    else:
        return None
    return host


def make_combo_searchable(combo):
    """Add the search box to one WPF ComboBox. Safe to call more than once.
    Returns True when the ComboBox has (or already had) a search box."""
    if combo is None or combo.IsEditable:
        return False
    popup = _find_popup(combo)
    if popup is None or popup.Child is None:
        return False
    root = popup.Child
    if _has_host(root):
        return True

    target, parent, chain = _find_list(root)
    pal, popup_lum = _palette(combo, chain or [root])
    search_root, box, hint, bg_brush = _build_search_ui(pal, popup_lum)
    host = _insert_host(popup, root, target, parent, search_root, bg_brush)
    if host is None:
        return False

    # Rows are hidden rather than filtering combo.Items: dropdowns that share
    # one list (e.g. one per table row) share its collection view, so a filter
    # would hit all of them and could clear their selections.
    try:
        VirtualizingPanel.SetIsVirtualizing(combo, False)   # every row gets a container
    except Exception:
        pass

    state = {'terms': [], 'orig': {}}

    def apply_filter():
        terms = state['terms']
        orig  = state['orig']
        gen   = combo.ItemContainerGenerator
        items = combo.Items
        for i in range(items.Count):
            cont = gen.ContainerFromIndex(i)
            if cont is None:
                continue
            if cont not in orig:
                if not terms:
                    continue
                orig[cont] = cont.Visibility
            if not terms or _matches(_item_text(combo, items[i]), terms):
                cont.Visibility = orig[cont]
            else:
                cont.Visibility = Visibility.Collapsed
        if not terms:
            for cont, vis in orig.items():
                try:
                    cont.Visibility = vis
                except Exception:
                    pass
            orig.clear()
        if isinstance(target, ScrollViewer):
            try:
                target.ScrollToTop()
            except Exception:
                pass

    def on_generated(s, e):
        if state['terms'] and combo.ItemContainerGenerator.Status == GeneratorStatus.ContainersGenerated:
            apply_filter()

    def on_text(s, e):
        text = box.Text or u''
        hint.Visibility = Visibility.Visible if not text else Visibility.Collapsed
        state['terms'] = [t for t in text.lower().split() if t]
        apply_filter()

    def first_match_index():
        items = combo.Items
        gen   = combo.ItemContainerGenerator
        for i in range(items.Count):
            cont = gen.ContainerFromIndex(i)
            if cont is not None and cont.Visibility != Visibility.Visible:
                continue
            if not state['terms'] or _matches(_item_text(combo, items[i]), state['terms']):
                return i
        return -1

    def on_box_key(s, e):
        if e.Key == Key.Down:
            idx = first_match_index()
            if idx >= 0:
                cont = combo.ItemContainerGenerator.ContainerFromIndex(idx)
                if cont is not None:
                    cont.Focus()
            e.Handled = True
        elif e.Key == Key.Enter:
            idx = first_match_index()
            if idx >= 0:
                combo.SelectedItem = combo.Items[idx]
            combo.IsDropDownOpen = False
            e.Handled = True
        elif e.Key == Key.Escape:
            combo.IsDropDownOpen = False
            e.Handled = True

    def focus_box():
        if combo.IsDropDownOpen:
            try:
                host.MinWidth = host.ActualWidth     # stop the list shrinking while filtering
            except Exception:
                pass
            box.Focus()
            Keyboard.Focus(box)

    def on_opened(s, e):
        if box.Text:
            box.Text = u''
        combo.Dispatcher.BeginInvoke(DispatcherPriority.Input, Action(focus_box))

    def on_closed(s, e):
        if box.Text:
            box.Text = u''
        host.MinWidth = 0

    box.TextChanged    += TextChangedEventHandler(on_text)
    box.PreviewKeyDown += KeyEventHandler(on_box_key)
    combo.DropDownOpened += on_opened
    combo.DropDownClosed += on_closed
    combo.ItemContainerGenerator.StatusChanged += on_generated
    return True


def _combo_from(source):
    el = source
    for _ in range(80):
        if el is None:
            return None
        if isinstance(el, ComboBox):
            return el
        parent = None
        if isinstance(el, Visual):
            parent = VisualTreeHelper.GetParent(el)
        if parent is None and isinstance(el, DependencyObject):
            parent = LogicalTreeHelper.GetParent(el)
        el = parent
    return None


def _all_combos(root):
    found, seen, stack = [], set([root]), [root]
    while stack:
        el = stack.pop()
        if isinstance(el, ComboBox):
            found.append(el)
        children = _visual_children(el)
        try:
            children.extend(LogicalTreeHelper.GetChildren(el))
        except Exception:
            pass
        for ch in children:
            if isinstance(ch, DependencyObject) and ch not in seen:
                seen.add(ch)
                stack.append(ch)
    return found


def enable_combo_search(window):
    """Give every dropdown in *window* a search box, including dropdowns the
    tool adds later (rows, grid cells). Call once, before showing the window."""
    ready = set()

    def prepare(combo):
        if combo is None or combo in ready:
            return
        if make_combo_searchable(combo):
            ready.add(combo)

    def scan(*args):
        for combo in _all_combos(window):
            prepare(combo)

    def on_mouse(s, e):
        prepare(_combo_from(e.OriginalSource))

    def on_key(s, e):
        prepare(_combo_from(e.OriginalSource))

    window.AddHandler(UIElement.PreviewMouseLeftButtonDownEvent, MouseButtonEventHandler(on_mouse), True)
    window.AddHandler(UIElement.PreviewKeyDownEvent, KeyEventHandler(on_key), True)
    if window.IsLoaded:
        scan()
    else:
        window.Loaded += RoutedEventHandler(scan)
    return window


# ═══════════════════════════════════════════════════════════════════════════
#  WINFORMS
# ═══════════════════════════════════════════════════════════════════════════

def enable_winforms_combo_search(combo, max_height=320):
    """Replace a WinForms ComboBox's dropdown list with a small list that has
    a search box on top. The ComboBox itself keeps working as before."""
    clr.AddReference('System.Windows.Forms')
    clr.AddReference('System.Drawing')
    import System.Windows.Forms as WF
    import System.Drawing as DR
    from System import EventHandler

    combo.IntegralHeight = False
    combo.DropDownHeight = 1            # the native list is closed straight away
    state = {'dd': None}

    def item_text(item):
        try:
            return unicode(combo.GetItemText(item))
        except Exception:
            return unicode(item)

    def open_popup():
        combo.DroppedDown = False
        if state['dd'] is not None and state['dd'].Visible:
            return
        back, fore = combo.BackColor, combo.ForeColor

        panel = WF.Panel()
        panel.BackColor = back
        panel.Padding   = WF.Padding(1)

        search = WF.TextBox()
        search.BorderStyle = WF.BorderStyle.FixedSingle
        search.BackColor   = back
        search.ForeColor   = fore
        search.Font        = combo.Font
        search.Dock        = WF.DockStyle.Top

        lst = WF.ListBox()
        lst.BorderStyle    = getattr(WF.BorderStyle, 'None')
        lst.BackColor      = back
        lst.ForeColor      = fore
        lst.Font           = combo.Font
        lst.Dock           = WF.DockStyle.Fill
        lst.IntegralHeight = False

        all_items = [combo.Items[i] for i in range(combo.Items.Count)]

        def refill():
            terms = [t for t in (search.Text or u'').lower().split() if t]
            lst.BeginUpdate()
            lst.Items.Clear()
            for item in all_items:
                if _matches(item_text(item), terms):
                    lst.Items.Add(item)
            lst.EndUpdate()
            if combo.SelectedItem is not None and lst.Items.Contains(combo.SelectedItem):
                lst.SelectedItem = combo.SelectedItem
            elif lst.Items.Count:
                lst.SelectedIndex = 0

        dd = WF.ToolStripDropDown()
        dd.Padding   = WF.Padding.Empty
        dd.AutoClose = True

        def pick(item):
            if item is not None:
                combo.SelectedItem = item
            dd.Close()
            combo.Focus()

        def on_search_key(s, e):
            if e.KeyCode == WF.Keys.Down:
                if lst.Items.Count:
                    lst.Focus()
                    if lst.SelectedIndex < 0:
                        lst.SelectedIndex = 0
                e.Handled = True
            elif e.KeyCode == WF.Keys.Enter:
                pick(lst.SelectedItem if lst.Items.Count else None)
                e.Handled = True
                e.SuppressKeyPress = True
            elif e.KeyCode == WF.Keys.Escape:
                dd.Close()
                e.Handled = True

        def on_list_key(s, e):
            if e.KeyCode == WF.Keys.Enter:
                pick(lst.SelectedItem)
                e.Handled = True
            elif e.KeyCode == WF.Keys.Escape:
                dd.Close()
                e.Handled = True

        def on_list_click(s, e):
            idx = lst.IndexFromPoint(e.Location)
            if idx >= 0:
                pick(lst.Items[idx])

        search.TextChanged += EventHandler(lambda s, e: refill())
        search.KeyDown     += WF.KeyEventHandler(on_search_key)
        lst.KeyDown        += WF.KeyEventHandler(on_list_key)
        lst.MouseClick     += WF.MouseEventHandler(on_list_click)

        panel.Controls.Add(lst)
        panel.Controls.Add(search)
        refill()

        row_h  = max(lst.ItemHeight, 14)
        height = min(max_height, search.Height + row_h * max(lst.Items.Count, 1) + 6)
        width  = max(combo.Width, 160)
        panel.Size = DR.Size(width, height)

        host = WF.ToolStripControlHost(panel)
        host.Margin   = WF.Padding.Empty
        host.Padding  = WF.Padding.Empty
        host.AutoSize = False
        host.Size     = panel.Size
        dd.Items.Add(host)
        state['dd'] = dd

        dd.Show(combo, DR.Point(0, combo.Height))
        search.Focus()

    def on_dropdown(s, e):
        combo.BeginInvoke(Action(open_popup))

    combo.DropDown += EventHandler(on_dropdown)
    return combo
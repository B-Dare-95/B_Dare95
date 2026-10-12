# -*- coding: utf-8 -*-
__title__   = "Ghost by Category"
__doc__     = """
________________________________________________________________
Description:
- Modeless window: pick the categories to dim in the active view
- Stays open while you work and follows the active view
- Negate mode (checkbox, or Shift+Click the button): everything
  EXCEPT the checked categories goes transparent
- "Restore View" clears ghost transparency on every model category
- Existing colour / pattern / halftone overrides are preserved
- Pressing the button again brings the open window to the front
________________________________________________________________
Author: Mohamed Bedair"""

__persistentengine__ = True

# ── Imports ────────────────────────────────────────────────────────────────────
import clr
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')

from Autodesk.Revit.DB import (Transaction, OverrideGraphicSettings,
                               FilteredElementCollector, CategoryType,
                               DisplayStyle)
from Autodesk.Revit.UI import TaskDialog, IExternalEventHandler, ExternalEvent
from Autodesk.Revit.UI.Events import ViewActivatedEventArgs

from System import EventHandler
from System.Windows import (Visibility, Thickness, TextAlignment,
                            VerticalAlignment, RoutedEventHandler, WindowState)
from System.Windows.Controls import Border, DockPanel, Dock, TextBlock, CheckBox
from System.Windows.Input import Key
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Markup import XamlReader
from System.Windows.Media import BrushConverter

from pyrevit import script, EXEC_PARAMS
from pyrevit.coreutils import envvars

# ── Globals ────────────────────────────────────────────────────────────────────
UIAPP       = __revit__
SHIFT_CLICK = bool(EXEC_PARAMS.config_mode)   # keep config.py OUT of this bundle
ENV_KEY     = 'B_DARE95_GHOST_BY_CATEGORY'

DEFAULT_TRANSPARENCY = 95
SHADED_NEEDED = (DisplayStyle.Wireframe, DisplayStyle.HLR)

# ── Second press: re-focus the open window instead of opening another ──────────
_existing  = envvars.get_pyrevit_env_var(ENV_KEY)
_refocused = False
if _existing is not None:
    try:
        # A window closed while its engine was dead never cleared this entry,
        # so check the window itself before trusting it
        if _existing['window'].IsVisible:
            _existing['focus'](SHIFT_CLICK)
            _refocused = True
    except Exception:
        try:
            _existing['window'].Close()   # dead window from a broken session
        except Exception:
            pass
    if not _refocused:
        envvars.set_pyrevit_env_var(ENV_KEY, None)
if _refocused:
    script.exit()

# ── IBM Carbon palette ─────────────────────────────────────────────────────────
C_TEXT    = '#F4F4F4'
C_SUBTEXT = '#A8A8A8'
C_ACCENT  = '#F1C21B'
C_LINE    = '#393939'
C_ERROR   = '#FA4D56'
C_OK      = '#42BE65'

_brush_conv = BrushConverter()
def brush(hex_code):
    return _brush_conv.ConvertFromString(hex_code)

# ── ElementId Compatibility ────────────────────────────────────────────────────
def eid_value(element_id):
    """.Value on Revit 2025+, .IntegerValue fallback for 2024."""
    try:
        return element_id.Value
    except AttributeError:
        return element_id.IntegerValue

# ── Revit Helpers (API context only) ───────────────────────────────────────────
def view_problem(view):
    """Reason this view can't be ghosted, or None if it can."""
    if view is None:
        return "No active view."
    if eid_value(view.ViewTemplateId) != -1:
        return "This view has a View Template. Turn it off to ghost categories."
    try:
        if not view.AreGraphicsOverridesAllowed():
            return "This view type does not support graphic overrides."
    except Exception:
        return "This view type does not support graphic overrides."
    return None

def collect_rows(doc, view):
    """Every overridable model category, with its element count in the view
    and its current surface transparency."""
    counts = {}
    for el in FilteredElementCollector(doc, view.Id).WhereElementIsNotElementType():
        cat = el.Category
        if cat is None:
            continue
        if cat.Parent is not None:
            cat = cat.Parent
        key = eid_value(cat.Id)
        counts[key] = counts.get(key, 0) + 1

    rows = []
    for cat in doc.Settings.Categories:
        try:
            if cat.CategoryType != CategoryType.Model:
                continue
            if not cat.get_AllowsVisibilityControl(view):
                continue
            if not view.IsCategoryOverridable(cat.Id):
                continue
            current = view.GetCategoryOverrides(cat.Id).Transparency
        except Exception:
            continue
        key = eid_value(cat.Id)
        rows.append({'id': cat.Id, 'key': key, 'name': cat.Name,
                     'count': counts.get(key, 0), 'now': current})

    rows.sort(key=lambda r: r['name'].lower())
    return rows

def set_transparency(view, row, value, report):
    """Change ONLY surface transparency; every other override on the
    category (colours, patterns, halftone, line weights) is kept."""
    try:
        current = view.GetCategoryOverrides(row['id'])
        if current.Transparency == value:
            return
        ogs = OverrideGraphicSettings(current)
        ogs.SetSurfaceTransparency(value)
        view.SetCategoryOverrides(row['id'], ogs)
        report['changed'] += 1
    except Exception as ex:
        report['failed'].append(u"{}: {}".format(row['name'], ex))

# ── XAML ───────────────────────────────────────────────────────────────────────
XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Ghost by Category" Width="480" Height="680"
        MinWidth="420" MinHeight="500"
        WindowStartupLocation="CenterOwner" ShowInTaskbar="False"
        Background="#161616" FontFamily="Segoe UI" FontSize="12"
        Foreground="#F4F4F4">
  <Window.Resources>

    <Style x:Key="Btn" TargetType="Button">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="Padding" Value="16,7"/>
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
                <Setter TargetName="Bd" Property="Opacity" Value="0.82"/>
              </Trigger>
              <Trigger Property="IsEnabled" Value="False">
                <Setter TargetName="Bd" Property="Opacity" Value="0.35"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="SmallBtn" TargetType="Button" BasedOn="{StaticResource Btn}">
      <Setter Property="Padding" Value="10,4"/>
      <Setter Property="FontSize" Value="11"/>
      <Setter Property="Margin" Value="0,0,6,0"/>
    </Style>

    <Style x:Key="AccentBtn" TargetType="Button" BasedOn="{StaticResource Btn}">
      <Setter Property="Background" Value="#F1C21B"/>
      <Setter Property="Foreground" Value="#161616"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
    </Style>

    <Style TargetType="CheckBox">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="CheckBox">
            <DockPanel Background="Transparent">
              <Border x:Name="Box" Width="16" Height="16" CornerRadius="3"
                      BorderThickness="1" BorderBrush="#8D8D8D"
                      Background="Transparent" VerticalAlignment="Center">
                <Path x:Name="Mark" Data="M 3 7.5 L 6 10.5 L 12 4"
                      Stroke="#161616" StrokeThickness="2" Visibility="Collapsed"/>
              </Border>
              <ContentPresenter Margin="8,0,0,0" VerticalAlignment="Center"/>
            </DockPanel>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="Box" Property="BorderBrush" Value="#F4F4F4"/>
              </Trigger>
              <Trigger Property="IsChecked" Value="True">
                <Setter TargetName="Box" Property="Background" Value="#F1C21B"/>
                <Setter TargetName="Box" Property="BorderBrush" Value="#F1C21B"/>
                <Setter TargetName="Mark" Property="Visibility" Value="Visible"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style TargetType="TextBox">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Background" Value="#262626"/>
      <Setter Property="CaretBrush" Value="#F4F4F4"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="TextBox">
            <Border x:Name="Bd" Background="{TemplateBinding Background}"
                    BorderBrush="#525252" BorderThickness="0,0,0,1"
                    CornerRadius="4,4,0,0" Padding="8,7">
              <ScrollViewer x:Name="PART_ContentHost"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsKeyboardFocused" Value="True">
                <Setter TargetName="Bd" Property="BorderBrush" Value="#F1C21B"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
  </Window.Resources>

  <Grid Margin="18">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <!-- Header -->
    <StackPanel Grid.Row="0">
      <TextBlock Text="Ghost by Category" FontSize="18" FontWeight="SemiBold"/>
      <TextBlock x:Name="ViewName" Foreground="#A8A8A8" Margin="0,2,0,0"
                 TextTrimming="CharacterEllipsis"/>
    </StackPanel>

    <!-- Negate mode -->
    <CheckBox Grid.Row="1" x:Name="ChkNegate" Margin="0,14,0,0">
      <StackPanel Orientation="Horizontal">
        <TextBlock Text="Negate mode" FontWeight="SemiBold"/>
        <TextBlock Text="  -  ghost everything except the checked categories"
                   Foreground="#A8A8A8"/>
      </StackPanel>
    </CheckBox>

    <!-- Search -->
    <Grid Grid.Row="2" Margin="0,12,0,8">
      <TextBox x:Name="SearchBox"/>
      <TextBlock x:Name="SearchHint" Text="Search categories..." Foreground="#6F6F6F"
                 Margin="10,0,0,0" VerticalAlignment="Center" IsHitTestVisible="False"/>
    </Grid>

    <!-- Category list -->
    <Border Grid.Row="3" Background="#262626" CornerRadius="4">
      <DockPanel>
        <Border DockPanel.Dock="Top" Padding="10,8" BorderBrush="#393939"
                BorderThickness="0,0,0,1">
          <DockPanel>
            <TextBlock DockPanel.Dock="Right" Text="Now" Width="48"
                       TextAlignment="Right" Foreground="#A8A8A8"/>
            <TextBlock DockPanel.Dock="Right" Text="In view" Width="56"
                       TextAlignment="Right" Foreground="#A8A8A8"/>
            <TextBlock x:Name="ListHeader" Margin="24,0,0,0" Foreground="#A8A8A8"/>
          </DockPanel>
        </Border>
        <ScrollViewer VerticalScrollBarVisibility="Auto">
          <StackPanel x:Name="ListPanel"/>
        </ScrollViewer>
      </DockPanel>
    </Border>

    <!-- List tools -->
    <DockPanel Grid.Row="4" Margin="0,8,0,0">
      <CheckBox x:Name="ShowAll" DockPanel.Dock="Right" Content="Show all model categories"
                Foreground="#A8A8A8" VerticalAlignment="Center"/>
      <StackPanel Orientation="Horizontal">
        <Button x:Name="BtnAll"     Content="Select all" Style="{StaticResource SmallBtn}"/>
        <Button x:Name="BtnNone"    Content="Clear"      Style="{StaticResource SmallBtn}"/>
        <Button x:Name="BtnFlip"    Content="Flip"       Style="{StaticResource SmallBtn}"/>
        <Button x:Name="BtnRefresh" Content="Refresh"    Style="{StaticResource SmallBtn}"
                ToolTip="Recount the elements in the active view"/>
      </StackPanel>
    </DockPanel>

    <!-- Settings -->
    <Border Grid.Row="5" Background="#262626" CornerRadius="4" Padding="12" Margin="0,12,0,0">
      <StackPanel>
        <DockPanel>
          <TextBlock Text="Transparency" Width="90" VerticalAlignment="Center"/>
          <TextBlock x:Name="TransValue" DockPanel.Dock="Right" Width="40"
                     TextAlignment="Right" VerticalAlignment="Center"
                     Foreground="#F1C21B" FontWeight="SemiBold"/>
          <Slider x:Name="TransSlider" Minimum="10" Maximum="100" TickFrequency="5"
                  IsSnapToTickEnabled="True" VerticalAlignment="Center"/>
        </DockPanel>
        <CheckBox x:Name="ChkReset" Margin="0,10,0,0"
                  Content="Clear transparency on categories that are not ghosted"/>
        <CheckBox x:Name="ChkShade" Margin="0,8,0,0"
                  Content="Switch Wireframe / Hidden Line view to Shaded with Edges"/>
      </StackPanel>
    </Border>

    <!-- Status + feedback -->
    <StackPanel Grid.Row="6" Margin="0,10,0,0">
      <TextBlock x:Name="Status" Foreground="#A8A8A8" TextWrapping="Wrap"/>
      <TextBlock x:Name="Feedback" Margin="0,4,0,0" TextWrapping="Wrap"/>
    </StackPanel>

    <!-- Footer -->
    <DockPanel Grid.Row="7" Margin="0,12,0,0">
      <Button x:Name="BtnRestore" Content="Restore View" Style="{StaticResource Btn}"
              ToolTip="Set surface transparency back to 0 on every model category in this view"/>
      <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
        <Button x:Name="BtnClose" Content="Close" Style="{StaticResource Btn}" Margin="0,0,8,0"/>
        <Button x:Name="BtnApply" Content="Apply" Style="{StaticResource AccentBtn}"/>
      </StackPanel>
    </DockPanel>
  </Grid>
</Window>
"""

# ── Build Window ───────────────────────────────────────────────────────────────
window = XamlReader.Parse(XAML)
find   = window.FindName

txt_view     = find('ViewName')
chk_negate   = find('ChkNegate')
search_box   = find('SearchBox')
search_hint  = find('SearchHint')
list_header  = find('ListHeader')
list_panel   = find('ListPanel')
chk_show_all = find('ShowAll')
btn_all      = find('BtnAll')
btn_none     = find('BtnNone')
btn_flip     = find('BtnFlip')
btn_refresh  = find('BtnRefresh')
trans_value  = find('TransValue')
trans_slider = find('TransSlider')
chk_reset    = find('ChkReset')
chk_shade    = find('ChkShade')
status_text  = find('Status')
feedback     = find('Feedback')
btn_restore  = find('BtnRestore')
btn_close    = find('BtnClose')
btn_apply    = find('BtnApply')

# Mutable containers instead of nonlocal (IronPython 2.7)
state = {
    'doc'        : None,    # Document the list was loaded from
    'view_id'    : None,    # View the list was loaded from
    'token'      : 0,       # bumps on every reload request (identity check)
    'problem'    : None,    # why the current view can't be ghosted
    'checked'    : set(),   # checked category keys, carried across views
    'loaded_once': False,
    'closed'     : False,
}
rows_ui = []

chk_negate.IsChecked = SHIFT_CLICK
trans_slider.Value   = DEFAULT_TRANSPARENCY
trans_value.Text     = "{}%".format(DEFAULT_TRANSPARENCY)
chk_reset.IsChecked  = True

# ── External Event: queued Revit API calls ─────────────────────────────────────
class JobQueueHandler(IExternalEventHandler):
    """Every Revit API call from the window goes through this queue."""
    def __init__(self):
        self.jobs = []

    def Execute(self, uiapp):
        while self.jobs:
            job = self.jobs.pop(0)
            if state['closed']:
                continue
            try:
                job(uiapp)
            except Exception as ex:
                set_feedback(u"Error: {}".format(ex), C_ERROR)

    def GetName(self):
        return "Ghost by Category"

handler   = JobQueueHandler()
ext_event = ExternalEvent.Create(handler)

def queue_job(job):
    handler.jobs.append(job)
    ext_event.Raise()

def request_load():
    state['token'] += 1
    token = state['token']
    queue_job(lambda uiapp: job_load(uiapp, token))

# ── UI Helpers ─────────────────────────────────────────────────────────────────
def set_feedback(text, color=C_SUBTEXT):
    feedback.Text       = text
    feedback.Foreground = brush(color)

def update_status():
    if state['problem']:
        list_header.Text       = "Categories"
        status_text.Text       = state['problem']
        status_text.Foreground = brush(C_ERROR)
        return
    status_text.Foreground = brush(C_SUBTEXT)
    n_checked = len([r for r in rows_ui if r['cb'].IsChecked])
    if chk_negate.IsChecked:
        list_header.Text = "Categories to keep SOLID"
        status_text.Text = u"{} kept solid  \u2192  {} categories will be ghosted".format(
            n_checked, len(rows_ui) - n_checked)
    else:
        list_header.Text = "Categories to ghost"
        status_text.Text = u"{} selected  \u2192  {} categories will be ghosted".format(
            n_checked, n_checked)

def apply_filter():
    query    = search_box.Text.strip().lower()
    show_all = bool(chk_show_all.IsChecked)
    for r in rows_ui:
        in_scope = show_all or r['count'] > 0
        matches  = query in r['name'].lower()
        r['row'].Visibility = Visibility.Visible if (in_scope and matches) \
                              else Visibility.Collapsed
    search_hint.Visibility = Visibility.Collapsed if search_box.Text \
                             else Visibility.Visible

def visible_rows():
    return [r for r in rows_ui if r['row'].Visibility == Visibility.Visible]

def make_row(data, checked):
    border = Border()
    border.Padding         = Thickness(10, 6, 10, 6)
    border.BorderThickness = Thickness(0, 0, 0, 1)
    border.BorderBrush     = brush(C_LINE)

    dock = DockPanel()
    dock.LastChildFill = True

    now_tb = TextBlock()
    now_tb.Width             = 48
    now_tb.TextAlignment     = TextAlignment.Right
    now_tb.VerticalAlignment = VerticalAlignment.Center
    if data['now'] > 0:
        now_tb.Text       = "{}%".format(data['now'])
        now_tb.Foreground = brush(C_ACCENT)
    DockPanel.SetDock(now_tb, Dock.Right)

    cnt_tb = TextBlock()
    cnt_tb.Width             = 56
    cnt_tb.TextAlignment     = TextAlignment.Right
    cnt_tb.VerticalAlignment = VerticalAlignment.Center
    cnt_tb.Foreground        = brush(C_SUBTEXT)
    cnt_tb.Text              = str(data['count']) if data['count'] else u"\u2013"
    DockPanel.SetDock(cnt_tb, Dock.Right)

    cb = CheckBox()
    cb.Content           = data['name']
    cb.Tag               = data['key']
    cb.VerticalAlignment = VerticalAlignment.Center
    cb.IsChecked         = checked
    cb.Checked   += RoutedEventHandler(safe(on_row_checked))
    cb.Unchecked += RoutedEventHandler(safe(on_row_checked))

    dock.Children.Add(now_tb)
    dock.Children.Add(cnt_tb)
    dock.Children.Add(cb)
    border.Child = dock
    return border, cb

def rebuild_list(rows):
    if rows and not state['loaded_once']:
        # First real load: pre-check what is already ghosted in this view
        if not chk_negate.IsChecked:
            state['checked'] = set(r['key'] for r in rows
                                   if r['now'] > 0 and r['count'] > 0)
        state['loaded_once'] = True

    list_panel.Children.Clear()
    del rows_ui[:]
    for data in rows:
        row_border, row_cb = make_row(data, data['key'] in state['checked'])
        list_panel.Children.Add(row_border)
        entry = dict(data)
        entry['row'] = row_border
        entry['cb']  = row_cb
        rows_ui.append(entry)

    apply_filter()
    update_status()

def refresh_controls(view):
    ok = state['problem'] is None
    btn_apply.IsEnabled   = ok
    btn_restore.IsEnabled = ok
    if ok and view is not None and view.DisplayStyle in SHADED_NEEDED:
        chk_shade.Visibility = Visibility.Visible
        chk_shade.IsChecked  = True
    else:
        chk_shade.Visibility = Visibility.Collapsed

# ── Jobs (run inside the External Event = valid API context) ──────────────────
def job_load(uiapp, token):
    if token != state['token']:
        return   # a newer reload was requested, skip this stale one

    uidoc = uiapp.ActiveUIDocument
    if uidoc is None:
        state['doc'], state['view_id'] = None, None
        state['problem'] = "No document is open."
        txt_view.Text = u"View: -"
        rebuild_list([])
        refresh_controls(None)
        return

    doc  = uidoc.Document
    view = doc.ActiveView
    state['doc']     = doc
    state['view_id'] = view.Id if view is not None else None
    state['problem'] = view_problem(view)
    txt_view.Text    = u"View: {}".format(view.Name) if view is not None else u"View: -"

    rows = [] if state['problem'] else collect_rows(doc, view)
    rebuild_list(rows)
    refresh_controls(view)

def is_same_target(doc, view, params):
    """Identity check: is the active view still the one the list was built for?"""
    try:
        return (params['doc'] is not None and doc.Equals(params['doc'])
                and view is not None and params['view_id'] is not None
                and eid_value(view.Id) == eid_value(params['view_id']))
    except Exception:
        return False

def job_overrides(uiapp, params):
    uidoc = uiapp.ActiveUIDocument
    if uidoc is None:
        set_feedback("No document is open.", C_ERROR)
        return
    doc  = uidoc.Document
    view = doc.ActiveView

    if not is_same_target(doc, view, params):
        set_feedback("The active view changed - list reloaded. Review it and Apply again.",
                     C_ERROR)
        request_load()
        return

    problem = view_problem(view)
    if problem:
        set_feedback(problem, C_ERROR)
        return

    rows = collect_rows(doc, view)
    if params['action'] == 'restore':
        targets, keep_solid, reset = set(), set(), True
        tx_name = "Ghost by Category - Restore"
    else:
        all_keys = set(r['key'] for r in rows)
        if params['negate']:
            targets    = all_keys - params['checked']
            keep_solid = set(params['checked'])
            tx_name    = "Ghost by Category - Negate"
        else:
            targets    = set(params['checked'])
            keep_solid = set()
            tx_name    = "Ghost by Category"
        reset = params['reset']

    report = {'changed': 0, 'failed': []}

    t = Transaction(doc, tx_name)
    t.Start()
    try:
        if (params['action'] == 'apply' and targets and params['shade']
                and view.DisplayStyle in SHADED_NEEDED):
            view.DisplayStyle = DisplayStyle.ShadingWithEdges

        for row in rows:
            if row['key'] in targets:
                set_transparency(view, row, params['transparency'], report)
            elif row['key'] in keep_solid or reset:
                set_transparency(view, row, 0, report)

        t.Commit()
    except Exception as e:
        t.RollBack()
        set_feedback(u"Failed: {}".format(e), C_ERROR)
        return

    if params['action'] == 'restore':
        msg = u"View restored - {} categories updated.".format(report['changed'])
    else:
        msg = u"Done - {} categories ghosted at {}%, {} updated.".format(
            len(targets), params['transparency'], report['changed'])

    if report['failed']:
        msg += u" {} skipped.".format(len(report['failed']))
        shown = report['failed'][:15]
        more  = len(report['failed']) - len(shown)
        detail = u"\n".join(shown)
        if more:
            detail += u"\n... and {} more".format(more)
        TaskDialog.Show("Ghost by Category", u"Skipped categories:\n\n" + detail)
        set_feedback(msg, C_ACCENT)
    else:
        set_feedback(msg, C_OK)

    request_load()   # refresh the "Now" column

# ── Event Handlers ─────────────────────────────────────────────────────────────
def safe(fn):
    """Wrap a WPF handler so an exception shows on the feedback line instead
    of escaping into WPF input processing."""
    def wrapper(sender, args):
        try:
            fn(sender, args)
        except Exception as ex:
            try:
                set_feedback(u"UI error in {}: {}".format(fn.__name__, ex), C_ERROR)
            except Exception:
                pass
    return wrapper

def on_row_checked(sender, args):
    if sender.IsChecked:
        state['checked'].add(sender.Tag)
    else:
        state['checked'].discard(sender.Tag)
    update_status()

def on_negate_changed(sender, args):
    update_status()

def on_search(sender, args):
    apply_filter()

def on_show_all(sender, args):
    apply_filter()

def on_select_all(sender, args):
    for r in visible_rows():
        r['cb'].IsChecked = True

def on_clear(sender, args):
    for r in visible_rows():
        r['cb'].IsChecked = False

def on_flip(sender, args):
    for r in visible_rows():
        r['cb'].IsChecked = not r['cb'].IsChecked

def on_refresh(sender, args):
    set_feedback("")
    request_load()

def on_slider(sender, args):
    trans_value.Text = "{}%".format(int(trans_slider.Value))

def on_apply(sender, args):
    params = {
        'action'      : 'apply',
        'negate'      : bool(chk_negate.IsChecked),
        'checked'     : set(r['key'] for r in rows_ui if r['cb'].IsChecked),
        'transparency': int(trans_slider.Value),
        'reset'       : bool(chk_reset.IsChecked),
        'shade'       : (chk_shade.Visibility == Visibility.Visible
                         and bool(chk_shade.IsChecked)),
        'doc'         : state['doc'],
        'view_id'     : state['view_id'],
    }
    set_feedback("Working...")
    queue_job(lambda uiapp: job_overrides(uiapp, params))

def on_restore(sender, args):
    params = {'action': 'restore', 'doc': state['doc'], 'view_id': state['view_id']}
    set_feedback("Working...")
    queue_job(lambda uiapp: job_overrides(uiapp, params))

def on_close_click(sender, args):
    window.Close()

def on_key(sender, args):
    if args.Key == Key.Escape:
        window.Close()

def on_view_activated(sender, args):
    if state['closed']:
        return
    set_feedback("")
    request_load()

view_activated_delegate = EventHandler[ViewActivatedEventArgs](safe(on_view_activated))

def on_closed(sender, args):
    state['closed'] = True
    try:
        UIAPP.ViewActivated -= view_activated_delegate
    except Exception:
        pass
    envvars.set_pyrevit_env_var(ENV_KEY, None)
    try:
        ext_event.Dispose()
    except Exception:
        pass

def focus_window(shift):
    """Called when the button is pressed while the window is already open."""
    if state['closed']:
        raise RuntimeError("window already closed")
    if window.WindowState == WindowState.Minimized:
        window.WindowState = WindowState.Normal
    window.Activate()
    if shift:
        chk_negate.IsChecked = True
    request_load()

# ── Wire Events ────────────────────────────────────────────────────────────────
chk_negate.Checked     += RoutedEventHandler(safe(on_negate_changed))
chk_negate.Unchecked   += RoutedEventHandler(safe(on_negate_changed))
chk_show_all.Checked   += RoutedEventHandler(safe(on_show_all))
chk_show_all.Unchecked += RoutedEventHandler(safe(on_show_all))
btn_all.Click          += RoutedEventHandler(safe(on_select_all))
btn_none.Click         += RoutedEventHandler(safe(on_clear))
btn_flip.Click         += RoutedEventHandler(safe(on_flip))
btn_refresh.Click      += RoutedEventHandler(safe(on_refresh))
btn_apply.Click        += RoutedEventHandler(safe(on_apply))
btn_restore.Click      += RoutedEventHandler(safe(on_restore))
btn_close.Click        += RoutedEventHandler(safe(on_close_click))
search_box.TextChanged    += safe(on_search)
trans_slider.ValueChanged += safe(on_slider)
window.KeyDown            += safe(on_key)
window.Closed             += EventHandler(safe(on_closed))
UIAPP.ViewActivated       += view_activated_delegate

# ── First load (script run = valid API context, no event needed) ───────────────
job_load(UIAPP, state['token'])

# ── Park everything so it survives the script scope, then show modeless ────────
envvars.set_pyrevit_env_var(ENV_KEY, {
    'window' : window,
    'handler': handler,
    'event'  : ext_event,
    'focus'  : focus_window,
})

try:
    WindowInteropHelper(window).Owner = UIAPP.MainWindowHandle
except Exception:
    pass
window.Show()
search_box.Focus()
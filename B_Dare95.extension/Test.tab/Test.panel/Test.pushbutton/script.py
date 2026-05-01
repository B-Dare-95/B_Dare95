# -*- coding: utf-8 -*-
__title__   = "Pin / Unpin Manager"
__author__  = "Mohamed Bedair"
__version__ = "1.0.0"
__doc__     = """Version = 1.0.0

Description:
Unified Pin / Unpin Manager. Combines all pin/unpin workflows
into a single configurable tool.

How-to:
1. Select Action      ->  Pin  or  Unpin
2. Select Scope       ->  Current View / Selected Views / Entire Project
3. (Optional) Enable Category Filter and pick model categories
4. Click Run

Author: Mohamed Bedair"""

# ─────────────────────────────────────────────────────────────────────────────
import clr
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')

from System.Windows import (
    Visibility, MessageBox, MessageBoxButton, MessageBoxImage
)
from System.Windows.Controls import ListBoxItem
from System.Windows.Markup   import XamlReader

from Autodesk.Revit.DB import (
    FilteredElementCollector, Transaction, View, ViewType, CategoryType
)
from pyrevit import script

doc = __revit__.ActiveUIDocument.Document

# ── Data Collection ───────────────────────────────────────────────────────────
_SKIP_VT = {
    int(ViewType.SystemBrowser),
    int(ViewType.ProjectBrowser),
    int(ViewType.Undefined),
    int(ViewType.Internal),
}

def collect_views():
    result = []
    for v in FilteredElementCollector(doc).OfClass(View).ToElements():
        if not v.IsTemplate and int(v.ViewType) not in _SKIP_VT:
            result.append(v)
    return sorted(result, key=lambda v: (str(v.ViewType), v.Name))

def collect_model_cats():
    names = []
    for cat in doc.Settings.Categories:
        try:
            if cat.CategoryType == CategoryType.Model:
                names.append(cat.Name)
        except Exception:
            pass
    return sorted(names)

ALL_VIEWS = collect_views()
ALL_CATS  = collect_model_cats()

# ── XAML ──────────────────────────────────────────────────────────────────────
XAML = """
<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Pin / Unpin Manager"
    Width="420"
    SizeToContent="Height"
    WindowStartupLocation="CenterScreen"
    Background="#1E1E2E"
    ResizeMode="NoResize"
    FontFamily="Segoe UI"
    FontSize="13">

  <Window.Resources>

    <!-- ── Radio-style toggle button ── -->
    <Style x:Key="TogBtn" TargetType="ToggleButton">
      <Setter Property="Background"      Value="#313244"/>
      <Setter Property="Foreground"      Value="#CDD6F4"/>
      <Setter Property="BorderThickness" Value="0"/>
      <Setter Property="Padding"         Value="10,8"/>
      <Setter Property="Cursor"          Value="Hand"/>
      <Setter Property="FontSize"        Value="12"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ToggleButton">
            <Border x:Name="bd"
                    Background="{TemplateBinding Background}"
                    CornerRadius="5"
                    Padding="{TemplateBinding Padding}">
              <ContentPresenter HorizontalAlignment="Center"
                                VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsChecked" Value="True">
                <Setter Property="Background" Value="#F0A500"/>
                <Setter Property="Foreground" Value="#1E1E2E"/>
                <Setter Property="FontWeight" Value="SemiBold"/>
              </Trigger>
              <MultiTrigger>
                <MultiTrigger.Conditions>
                  <Condition Property="IsMouseOver" Value="True"/>
                  <Condition Property="IsChecked"   Value="False"/>
                </MultiTrigger.Conditions>
                <Setter Property="Background" Value="#45475A"/>
              </MultiTrigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <!-- ── Pill-style ON/OFF toggle ── -->
    <Style x:Key="PillTogBtn" TargetType="ToggleButton">
      <Setter Property="Background"      Value="#45475A"/>
      <Setter Property="Foreground"      Value="#A6ADC8"/>
      <Setter Property="BorderThickness" Value="0"/>
      <Setter Property="Padding"         Value="10,3"/>
      <Setter Property="Cursor"          Value="Hand"/>
      <Setter Property="FontSize"        Value="10"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ToggleButton">
            <Border Background="{TemplateBinding Background}"
                    CornerRadius="10"
                    Padding="{TemplateBinding Padding}">
              <ContentPresenter HorizontalAlignment="Center"
                                VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsChecked" Value="True">
                <Setter Property="Background" Value="#F0A500"/>
                <Setter Property="Foreground" Value="#1E1E2E"/>
                <Setter Property="FontWeight" Value="SemiBold"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <!-- ── Section card ── -->
    <Style x:Key="Card" TargetType="Border">
      <Setter Property="Background"   Value="#2A2A3C"/>
      <Setter Property="CornerRadius" Value="8"/>
      <Setter Property="Padding"      Value="14"/>
      <Setter Property="Margin"       Value="0,0,0,10"/>
    </Style>

    <!-- ── Section heading ── -->
    <Style x:Key="SHead" TargetType="TextBlock">
      <Setter Property="Foreground" Value="#F0A500"/>
      <Setter Property="FontSize"   Value="10"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
      <Setter Property="Margin"     Value="0,0,0,10"/>
    </Style>

    <!-- ── Sub-label ── -->
    <Style x:Key="Sub" TargetType="TextBlock">
      <Setter Property="Foreground" Value="#A6ADC8"/>
      <Setter Property="FontSize"   Value="11"/>
      <Setter Property="Margin"     Value="0,0,0,6"/>
    </Style>

    <!-- ── Dark ListBox ── -->
    <Style x:Key="DarkList" TargetType="ListBox">
      <Setter Property="Background"      Value="#1E1E2E"/>
      <Setter Property="BorderBrush"     Value="#45475A"/>
      <Setter Property="BorderThickness" Value="1"/>
      <Setter Property="Foreground"      Value="#CDD6F4"/>
      <Setter Property="Padding"         Value="2"/>
      <Setter Property="ScrollViewer.VerticalScrollBarVisibility" Value="Auto"/>
    </Style>

    <Style TargetType="ListBoxItem">
      <Setter Property="Padding"    Value="8,5"/>
      <Setter Property="Foreground" Value="#CDD6F4"/>
      <Setter Property="Background" Value="Transparent"/>
      <Style.Triggers>
        <Trigger Property="IsSelected"  Value="True">
          <Setter Property="Background" Value="#F0A500"/>
          <Setter Property="Foreground" Value="#1E1E2E"/>
        </Trigger>
        <Trigger Property="IsMouseOver" Value="True">
          <Setter Property="Background" Value="#313244"/>
        </Trigger>
      </Style.Triggers>
    </Style>

    <!-- ── Primary (Run) button ── -->
    <Style x:Key="RunBtn" TargetType="Button">
      <Setter Property="Background"      Value="#F0A500"/>
      <Setter Property="Foreground"      Value="#1E1E2E"/>
      <Setter Property="BorderThickness" Value="0"/>
      <Setter Property="FontWeight"      Value="Bold"/>
      <Setter Property="Cursor"          Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border Background="{TemplateBinding Background}"
                    CornerRadius="5" Padding="0">
              <ContentPresenter HorizontalAlignment="Center"
                                VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter Property="Background" Value="#D99300"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <!-- ── Secondary (Cancel) button ── -->
    <Style x:Key="SecBtn" TargetType="Button">
      <Setter Property="Background"      Value="#313244"/>
      <Setter Property="Foreground"      Value="#CDD6F4"/>
      <Setter Property="BorderThickness" Value="0"/>
      <Setter Property="Cursor"          Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border Background="{TemplateBinding Background}"
                    CornerRadius="5" Padding="0">
              <ContentPresenter HorizontalAlignment="Center"
                                VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter Property="Background" Value="#45475A"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

  </Window.Resources>

  <StackPanel Margin="14,14,14,12">

    <!-- ══════════════════════════════════════════════════════════════════ -->
    <!--  SECTION 1 · ACTION                                               -->
    <!-- ══════════════════════════════════════════════════════════════════ -->
    <Border Style="{StaticResource Card}">
      <StackPanel>
        <TextBlock Text="ACTION" Style="{StaticResource SHead}"/>
        <Grid>
          <Grid.ColumnDefinitions>
            <ColumnDefinition Width="*"/>
            <ColumnDefinition Width="8"/>
            <ColumnDefinition Width="*"/>
          </Grid.ColumnDefinitions>
          <ToggleButton x:Name="btn_pin"
                        Grid.Column="0"
                        Content="&#x1F4CC;  PIN"
                        Style="{StaticResource TogBtn}"
                        IsChecked="True"/>
          <ToggleButton x:Name="btn_unpin"
                        Grid.Column="2"
                        Content="&#x1F4CD;  UNPIN"
                        Style="{StaticResource TogBtn}"/>
        </Grid>
      </StackPanel>
    </Border>

    <!-- ══════════════════════════════════════════════════════════════════ -->
    <!--  SECTION 2 · SCOPE                                                -->
    <!-- ══════════════════════════════════════════════════════════════════ -->
    <Border Style="{StaticResource Card}">
      <StackPanel>
        <TextBlock Text="SCOPE" Style="{StaticResource SHead}"/>
        <Grid>
          <Grid.ColumnDefinitions>
            <ColumnDefinition Width="*"/>
            <ColumnDefinition Width="6"/>
            <ColumnDefinition Width="*"/>
            <ColumnDefinition Width="6"/>
            <ColumnDefinition Width="*"/>
          </Grid.ColumnDefinitions>
          <ToggleButton x:Name="btn_cur"
                        Grid.Column="0"
                        Content="Current View"
                        Style="{StaticResource TogBtn}"
                        IsChecked="True"/>
          <ToggleButton x:Name="btn_sel"
                        Grid.Column="2"
                        Content="Selected Views"
                        Style="{StaticResource TogBtn}"/>
          <ToggleButton x:Name="btn_proj"
                        Grid.Column="4"
                        Content="Entire Project"
                        Style="{StaticResource TogBtn}"/>
        </Grid>

        <!-- View list — shown only when Selected Views is active -->
        <Border x:Name="pnl_views" Visibility="Collapsed" Margin="0,10,0,0">
          <StackPanel>
            <TextBlock Text="Select views  (hold Ctrl for multiple):"
                       Style="{StaticResource Sub}"/>
            <ListBox x:Name="lst_views"
                     Height="140"
                     Style="{StaticResource DarkList}"
                     SelectionMode="Extended"/>
          </StackPanel>
        </Border>
      </StackPanel>
    </Border>

    <!-- ══════════════════════════════════════════════════════════════════ -->
    <!--  SECTION 3 · CATEGORY FILTER                                      -->
    <!-- ══════════════════════════════════════════════════════════════════ -->
    <Border Style="{StaticResource Card}">
      <StackPanel>
        <StackPanel Orientation="Horizontal">
          <TextBlock Text="CATEGORY FILTER"
                     Style="{StaticResource SHead}"
                     VerticalAlignment="Center"
                     Margin="0,0,10,0"/>
          <ToggleButton x:Name="btn_cat_tog"
                        Content="OFF"
                        Style="{StaticResource PillTogBtn}"
                        Width="44" Height="20"/>
        </StackPanel>

        <!-- Category list — shown only when filter is ON -->
        <Border x:Name="pnl_cats" Visibility="Collapsed" Margin="0,10,0,0">
          <StackPanel>
            <TextBlock Text="Select categories  (hold Ctrl for multiple):"
                       Style="{StaticResource Sub}"/>
            <ListBox x:Name="lst_cats"
                     Height="170"
                     Style="{StaticResource DarkList}"
                     SelectionMode="Extended"/>
          </StackPanel>
        </Border>
      </StackPanel>
    </Border>

    <!-- ══════════════════════════════════════════════════════════════════ -->
    <!--  FOOTER                                                           -->
    <!-- ══════════════════════════════════════════════════════════════════ -->
    <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
      <Button x:Name="btn_cancel"
              Content="Cancel"
              Width="90" Height="32"
              Style="{StaticResource SecBtn}"
              Margin="0,0,8,0"/>
      <Button x:Name="btn_run"
              Content="&#x25B6;  Run"
              Width="90" Height="32"
              Style="{StaticResource RunBtn}"/>
    </StackPanel>

  </StackPanel>
</Window>
"""

# ── Dialog Class ──────────────────────────────────────────────────────────────
class PinUnpinDialog(object):
    """
    WPF dialog for the Pin / Unpin Manager.

    Radio-toggle behaviour is implemented entirely in Python:
      _radio()  – mutually excludes buttons within a group
      _guard()  – prevents the user from unchecking the active button
                  (IronPython mutable-list trick for closure state)
    """

    def __init__(self):
        self.result = None
        self._lock  = [False]   # mutable single-element list → shared across closures

        self.win = XamlReader.Parse(XAML)

        # ── Named controls ────────────────────────────────────────────────
        self.btn_pin     = self.win.FindName('btn_pin')
        self.btn_unpin   = self.win.FindName('btn_unpin')

        self.btn_cur     = self.win.FindName('btn_cur')
        self.btn_sel     = self.win.FindName('btn_sel')
        self.btn_proj    = self.win.FindName('btn_proj')
        self.pnl_views   = self.win.FindName('pnl_views')
        self.lst_views   = self.win.FindName('lst_views')

        self.btn_cat_tog = self.win.FindName('btn_cat_tog')
        self.pnl_cats    = self.win.FindName('pnl_cats')
        self.lst_cats    = self.win.FindName('lst_cats')

        self.btn_cancel  = self.win.FindName('btn_cancel')
        self.btn_run     = self.win.FindName('btn_run')

        # ── Populate view list ────────────────────────────────────────────
        for v in ALL_VIEWS:
            it = ListBoxItem()
            it.Content = u"[{}]  {}".format(str(v.ViewType), v.Name)
            it.Tag     = v.Id
            self.lst_views.Items.Add(it)

        # ── Populate category list ────────────────────────────────────────
        for name in ALL_CATS:
            it = ListBoxItem()
            it.Content = name
            self.lst_cats.Items.Add(it)

        # ── Wire events ───────────────────────────────────────────────────
        # Action group
        self.btn_pin.Checked     += self._on_action
        self.btn_unpin.Checked   += self._on_action
        self.btn_pin.Unchecked   += self._guard
        self.btn_unpin.Unchecked += self._guard

        # Scope group
        self.btn_cur.Checked    += self._on_scope
        self.btn_sel.Checked    += self._on_scope
        self.btn_proj.Checked   += self._on_scope
        self.btn_cur.Unchecked  += self._guard
        self.btn_sel.Unchecked  += self._guard
        self.btn_proj.Unchecked += self._guard

        # Category toggle
        self.btn_cat_tog.Checked   += self._on_cat_tog
        self.btn_cat_tog.Unchecked += self._on_cat_tog

        # Footer
        self.btn_cancel.Click += self._cancel
        self.btn_run.Click    += self._run

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _radio(self, group, active):
        """Keep only `active` checked in `group`; suppress re-entrant calls."""
        if self._lock[0]:
            return
        self._lock[0] = True
        for btn in group:
            btn.IsChecked = (btn is active)
        self._lock[0] = False

    def _guard(self, sender, e):
        """Prevent the user from unchecking the currently active radio toggle."""
        if not self._lock[0]:
            # Re-check: this fires Checked, which calls _on_action / _on_scope,
            # but _lock is still False so the radio handler runs cleanly.
            sender.IsChecked = True

    # ── Event handlers ────────────────────────────────────────────────────────
    def _on_action(self, sender, e):
        if self._lock[0]:
            return
        self._radio([self.btn_pin, self.btn_unpin], sender)

    def _on_scope(self, sender, e):
        if self._lock[0]:
            return
        self._radio([self.btn_cur, self.btn_sel, self.btn_proj], sender)
        # Show the view-picker only for "Selected Views"
        self.pnl_views.Visibility = (
            Visibility.Visible if sender is self.btn_sel else Visibility.Collapsed
        )

    def _on_cat_tog(self, sender, e):
        on = bool(sender.IsChecked)
        sender.Content           = "ON"  if on else "OFF"
        self.pnl_cats.Visibility = Visibility.Visible if on else Visibility.Collapsed

    def _cancel(self, sender, e):
        self.win.Close()

    def _run(self, sender, e):
        # ── Determine scope ───────────────────────────────────────────────
        if   self.btn_cur.IsChecked:  scope = 'current'
        elif self.btn_sel.IsChecked:  scope = 'views'
        else:                         scope = 'project'

        # ── Validate view selection ───────────────────────────────────────
        sel_view_ids = []
        if scope == 'views':
            for it in self.lst_views.SelectedItems:
                sel_view_ids.append(it.Tag)
            if not sel_view_ids:
                MessageBox.Show(
                    "Please select at least one view.",
                    "Pin / Unpin Manager",
                    MessageBoxButton.OK,
                    MessageBoxImage.Warning
                )
                return

        # ── Validate category selection ───────────────────────────────────
        use_cats = bool(self.btn_cat_tog.IsChecked)
        sel_cats = []
        if use_cats:
            for it in self.lst_cats.SelectedItems:
                sel_cats.append(str(it.Content))
            if not sel_cats:
                MessageBox.Show(
                    "Category filter is ON but no categories are selected.\n"
                    "Please pick at least one category, or turn the filter OFF.",
                    "Pin / Unpin Manager",
                    MessageBoxButton.OK,
                    MessageBoxImage.Warning
                )
                return

        self.result = {
            'pin'      : bool(self.btn_pin.IsChecked),
            'scope'    : scope,
            'view_ids' : sel_view_ids,
            'use_cats' : use_cats,
            'cats'     : sel_cats,
        }
        self.win.Close()

    def show(self):
        self.win.ShowDialog()
        return self.result


# ── Launch UI ─────────────────────────────────────────────────────────────────
dlg = PinUnpinDialog()
cfg = dlg.show()

if cfg is None:
    script.exit()

pin_val  = cfg['pin']
scope    = cfg['scope']
view_ids = set(cfg['view_ids'])
use_cats = cfg['use_cats']
cats     = set(cfg['cats'])
label    = "Pin" if pin_val else "Unpin"

# ── Element Collection ────────────────────────────────────────────────────────
def passes_cat_filter(elem):
    """True when the element's category is in the selected set (or filter is off)."""
    if not use_cats:
        return True
    try:
        return elem.Category is not None and elem.Category.Name in cats
    except Exception:
        return False

def elements_in_view(view_id):
    """All non-type elements visible in a given view."""
    try:
        return list(
            FilteredElementCollector(doc, view_id)
            .WhereElementIsNotElementType()
            .ToElements()
        )
    except Exception:
        return []

elements = []

# ── Current View ──────────────────────────────────────────────────────────────
if scope == 'current':
    elements = [
        e for e in elements_in_view(doc.ActiveView.Id)
        if passes_cat_filter(e)
    ]

# ── Selected Views (deduplicated by element id) ───────────────────────────────
elif scope == 'views':
    seen = set()
    for v in ALL_VIEWS:
        if v.Id not in view_ids:
            continue
        for e in elements_in_view(v.Id):
            eid = e.Id
            if eid not in seen:
                seen.add(eid)
                if passes_cat_filter(e):
                    elements.append(e)

# ── Entire Project ────────────────────────────────────────────────────────────
elif scope == 'project':
    if use_cats:
        # Use per-BuiltInCategory collectors → fast + precise
        seen    = set()
        cat_map = {c.Name: c for c in doc.Settings.Categories}
        for cname in cats:
            cat = cat_map.get(cname)
            if cat is None:
                continue
            try:
                bic   = cat.BuiltInCategory
                elems = (
                    FilteredElementCollector(doc)
                    .OfCategory(bic)
                    .WhereElementIsNotElementType()
                    .ToElements()
                )
                for e in elems:
                    eid = e.Id.IntegerValue
                    if eid not in seen:
                        seen.add(eid)
                        elements.append(e)
            except Exception:
                pass
    else:
        # No category filter → grab everything
        elements = list(
            FilteredElementCollector(doc)
            .WhereElementIsNotElementType()
            .ToElements()
        )

# ── Transaction ───────────────────────────────────────────────────────────────
t = Transaction(doc, "{} — Pin/Unpin Manager".format(label))
t.Start()

ok_count   = 0
skip_count = 0

for e in elements:
    try:
        e.Pinned = pin_val
        ok_count += 1
    except Exception:
        skip_count += 1

t.Commit()

# ── Output ────────────────────────────────────────────────────────────────────
out = script.get_output()

scope_display = {
    'current': u'Current View  ({})'.format(doc.ActiveView.Name),
    'views'  : u'Selected Views',
    'project': u'Entire Project',
}[scope]

out.print_md(u"## {} {} Complete".format(
    u"\U0001F4CC" if pin_val else u"\U0001F4CD", label
))
out.print_md(u"| | |")
out.print_md(u"|---|---|")
out.print_md(u"| **Action** | {} |".format(label))
out.print_md(u"| **Scope** | {} |".format(scope_display))
if use_cats:
    out.print_md(u"| **Categories** | {} |".format(u', '.join(sorted(cats))))
out.print_md(u"| **Processed** | {} elements |".format(ok_count))
if skip_count:
    out.print_md(u"| **Skipped** | {} (not pinnable) |".format(skip_count))
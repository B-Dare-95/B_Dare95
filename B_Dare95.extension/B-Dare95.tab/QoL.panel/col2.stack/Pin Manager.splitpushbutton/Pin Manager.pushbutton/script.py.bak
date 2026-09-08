# -*- coding: utf-8 -*-
__title__   = "Pin / Unpin Manager"
__author__  = "Mohamed Bedair"
__version__ = "2.0.0"
__doc__     = """Version = 2.0.0

Description:
Unified Pin / Unpin Manager.

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
from System.Windows.Controls import CheckBox
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
            <Border Background="{TemplateBinding Background}"
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

    <!-- ── Pill ON/OFF toggle ── -->
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

    <!-- ── Search border (accent outline on keyboard focus) ── -->
    <Style x:Key="SearchBorder" TargetType="Border">
      <Setter Property="Background"      Value="#1E1E2E"/>
      <Setter Property="BorderBrush"     Value="#45475A"/>
      <Setter Property="BorderThickness" Value="1"/>
      <Setter Property="CornerRadius"    Value="5"/>
      <Setter Property="Margin"          Value="0,0,0,6"/>
      <Setter Property="Padding"         Value="8,5"/>
      <Style.Triggers>
        <Trigger Property="IsKeyboardFocusWithin" Value="True">
          <Setter Property="BorderBrush" Value="#F0A500"/>
        </Trigger>
      </Style.Triggers>
    </Style>

    <!-- ── Custom dark CheckBox ── -->
    <Style x:Key="DarkChk" TargetType="CheckBox">
      <Setter Property="Foreground" Value="#CDD6F4"/>
      <Setter Property="Padding"    Value="8,0,0,0"/>
      <Setter Property="Margin"     Value="4,3,4,3"/>
      <Setter Property="Cursor"     Value="Hand"/>
      <Setter Property="FontSize"   Value="12"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="CheckBox">
            <Grid Background="Transparent">
              <Grid.ColumnDefinitions>
                <ColumnDefinition Width="18"/>
                <ColumnDefinition Width="*"/>
              </Grid.ColumnDefinitions>
              <!-- Checkbox square -->
              <Border x:Name="chkBox"
                      Grid.Column="0"
                      Width="15" Height="15"
                      BorderBrush="#45475A" BorderThickness="1.5"
                      Background="Transparent" CornerRadius="3"
                      VerticalAlignment="Center">
                <!-- Checkmark path -->
                <Path x:Name="chkMark"
                      Data="M 2,7 L 6,11 L 13,3"
                      Stroke="#1E1E2E" StrokeThickness="2"
                      Visibility="Collapsed"
                      VerticalAlignment="Center"
                      HorizontalAlignment="Center"/>
              </Border>
              <ContentPresenter Grid.Column="1"
                                VerticalAlignment="Center"
                                Margin="{TemplateBinding Padding}"/>
            </Grid>
            <ControlTemplate.Triggers>
              <Trigger Property="IsChecked" Value="True">
                <Setter TargetName="chkBox"  Property="Background"  Value="#F0A500"/>
                <Setter TargetName="chkBox"  Property="BorderBrush" Value="#F0A500"/>
                <Setter TargetName="chkMark" Property="Visibility"  Value="Visible"/>
              </Trigger>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="chkBox" Property="BorderBrush" Value="#F0A500"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <!-- ── Run button ── -->
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

    <!-- ── Cancel button ── -->
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
          <ToggleButton x:Name="btn_pin"   Grid.Column="0" Content="&#x1F4CC;  PIN"
                        Style="{StaticResource TogBtn}" IsChecked="True"/>
          <ToggleButton x:Name="btn_unpin" Grid.Column="2" Content="&#x1F4CD;  UNPIN"
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
          <ToggleButton x:Name="btn_cur"  Grid.Column="0" Content="Current View"
                        Style="{StaticResource TogBtn}" IsChecked="True"/>
          <ToggleButton x:Name="btn_sel"  Grid.Column="2" Content="Selected Views"
                        Style="{StaticResource TogBtn}"/>
          <ToggleButton x:Name="btn_proj" Grid.Column="4" Content="Entire Project"
                        Style="{StaticResource TogBtn}"/>
        </Grid>

        <!-- View picker — visible only when "Selected Views" is active -->
        <Border x:Name="pnl_views" Visibility="Collapsed" Margin="0,12,0,0">
          <StackPanel>
            <TextBlock Text="Select views:" Style="{StaticResource Sub}"/>
            <!-- Search bar -->
            <Border Style="{StaticResource SearchBorder}">
              <Grid>
                <Grid.ColumnDefinitions>
                  <ColumnDefinition Width="Auto"/>
                  <ColumnDefinition Width="*"/>
                </Grid.ColumnDefinitions>
                <TextBlock Grid.Column="0" Text="&#x1F50D;"
                           Foreground="#45475A" FontSize="11"
                           VerticalAlignment="Center" Margin="0,0,6,0"/>
                <TextBox x:Name="txt_view_search"
                         Grid.Column="1"
                         Background="Transparent" Foreground="#CDD6F4"
                         CaretBrush="#F0A500" BorderThickness="0"
                         VerticalAlignment="Center" FontSize="12"/>
              </Grid>
            </Border>
            <!-- Checkbox list -->
            <Border Background="#1E1E2E" BorderBrush="#45475A"
                    BorderThickness="1" CornerRadius="5">
              <ScrollViewer Height="145" VerticalScrollBarVisibility="Auto">
                <StackPanel x:Name="panel_views" Margin="4"/>
              </ScrollViewer>
            </Border>
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
                     VerticalAlignment="Center" Margin="0,0,10,0"/>
          <ToggleButton x:Name="btn_cat_tog" Content="OFF"
                        Style="{StaticResource PillTogBtn}"
                        Width="44" Height="20"/>
        </StackPanel>

        <!-- Category picker — visible only when filter is ON -->
        <Border x:Name="pnl_cats" Visibility="Collapsed" Margin="0,12,0,0">
          <StackPanel>
            <TextBlock Text="Select categories:" Style="{StaticResource Sub}"/>
            <!-- Search bar -->
            <Border Style="{StaticResource SearchBorder}">
              <Grid>
                <Grid.ColumnDefinitions>
                  <ColumnDefinition Width="Auto"/>
                  <ColumnDefinition Width="*"/>
                </Grid.ColumnDefinitions>
                <TextBlock Grid.Column="0" Text="&#x1F50D;"
                           Foreground="#45475A" FontSize="11"
                           VerticalAlignment="Center" Margin="0,0,6,0"/>
                <TextBox x:Name="txt_cat_search"
                         Grid.Column="1"
                         Background="Transparent" Foreground="#CDD6F4"
                         CaretBrush="#F0A500" BorderThickness="0"
                         VerticalAlignment="Center" FontSize="12"/>
              </Grid>
            </Border>
            <!-- Checkbox list -->
            <Border Background="#1E1E2E" BorderBrush="#45475A"
                    BorderThickness="1" CornerRadius="5">
              <ScrollViewer Height="172" VerticalScrollBarVisibility="Auto">
                <StackPanel x:Name="panel_cats" Margin="4"/>
              </ScrollViewer>
            </Border>
          </StackPanel>
        </Border>
      </StackPanel>
    </Border>

    <!-- ══════════════════════════════════════════════════════════════════ -->
    <!--  FOOTER                                                           -->
    <!-- ══════════════════════════════════════════════════════════════════ -->
    <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
      <Button x:Name="btn_cancel" Content="Cancel"
              Width="90" Height="32"
              Style="{StaticResource SecBtn}" Margin="0,0,8,0"/>
      <Button x:Name="btn_run"    Content="&#x25B6;  Run"
              Width="90" Height="32"
              Style="{StaticResource RunBtn}"/>
    </StackPanel>

  </StackPanel>
</Window>
"""

# ── Dialog Class ──────────────────────────────────────────────────────────────
class PinUnpinDialog(object):
    """
    WPF dialog for Pin / Unpin Manager v2.

    Two key design decisions for IronPython 2.7:

    1. CHECKBOX LISTS via ScrollViewer + StackPanel (not ListBox).
       No selection-highlight conflicts; check state is tracked
       independently in Python dicts.

    2. STATE PERSISTENCE across search redraws.
       _view_checked / _cat_checked dicts store {key: bool} and
       are read/written by per-item Checked/Unchecked handlers.
       When the search filter changes, the panel is cleared and
       rebuilt; IsChecked is seeded from the dict so ticks survive.
    """

    def __init__(self):
        self.result        = None
        self._lock         = [False]     # re-entrancy guard for radio groups

        # Persistent check-state dicts (survive search filter changes)
        self._view_checked = {v.Id: False for v in ALL_VIEWS}
        self._cat_checked  = {n: False for n in ALL_CATS}

        self.win = XamlReader.Parse(XAML)

        # ── Named controls ────────────────────────────────────────────────
        self.btn_pin         = self.win.FindName('btn_pin')
        self.btn_unpin       = self.win.FindName('btn_unpin')

        self.btn_cur         = self.win.FindName('btn_cur')
        self.btn_sel         = self.win.FindName('btn_sel')
        self.btn_proj        = self.win.FindName('btn_proj')
        self.pnl_views       = self.win.FindName('pnl_views')
        self.panel_views     = self.win.FindName('panel_views')
        self.txt_view_search = self.win.FindName('txt_view_search')

        self.btn_cat_tog     = self.win.FindName('btn_cat_tog')
        self.pnl_cats        = self.win.FindName('pnl_cats')
        self.panel_cats      = self.win.FindName('panel_cats')
        self.txt_cat_search  = self.win.FindName('txt_cat_search')

        self.btn_cancel = self.win.FindName('btn_cancel')
        self.btn_run    = self.win.FindName('btn_run')

        # Cache shared CheckBox style (avoids repeated ResourceDictionary look-ups)
        self._chk_style = self.win.Resources['DarkChk']

        # ── Initial list render (no filter active yet) ────────────────────
        self._render_views('')
        self._render_cats('')

        # ── Wire events ───────────────────────────────────────────────────
        self.btn_pin.Checked     += self._on_action
        self.btn_unpin.Checked   += self._on_action
        self.btn_pin.Unchecked   += self._guard
        self.btn_unpin.Unchecked += self._guard

        self.btn_cur.Checked    += self._on_scope
        self.btn_sel.Checked    += self._on_scope
        self.btn_proj.Checked   += self._on_scope
        self.btn_cur.Unchecked  += self._guard
        self.btn_sel.Unchecked  += self._guard
        self.btn_proj.Unchecked += self._guard

        self.txt_view_search.TextChanged += self._on_view_search
        self.txt_cat_search.TextChanged  += self._on_cat_search

        self.btn_cat_tog.Checked   += self._on_cat_tog
        self.btn_cat_tog.Unchecked += self._on_cat_tog

        self.btn_cancel.Click += self._cancel
        self.btn_run.Click    += self._run

    # ── CheckBox factories ────────────────────────────────────────────────────
    def _make_view_cb(self, label, view_id):
        """Create a styled CheckBox for a view entry."""
        cb           = CheckBox()
        cb.Content   = label
        cb.Style     = self._chk_style
        cb.IsChecked = self._view_checked.get(view_id, False)

        # Default-arg captures view_id correctly in IronPython 2.7 closures
        def on_toggle(s, e, vid=view_id):
            self._view_checked[vid] = bool(s.IsChecked)

        cb.Checked   += on_toggle
        cb.Unchecked += on_toggle
        return cb

    def _make_cat_cb(self, name):
        """Create a styled CheckBox for a category entry."""
        cb           = CheckBox()
        cb.Content   = name
        cb.Style     = self._chk_style
        cb.IsChecked = self._cat_checked.get(name, False)

        def on_toggle(s, e, n=name):
            self._cat_checked[n] = bool(s.IsChecked)

        cb.Checked   += on_toggle
        cb.Unchecked += on_toggle
        return cb

    # ── List renderers ────────────────────────────────────────────────────────
    def _render_views(self, filter_text):
        """Clear and rebuild the view checkbox panel, respecting the search filter."""
        ft = filter_text.strip().lower()
        self.panel_views.Children.Clear()
        for v in ALL_VIEWS:
            label = u"[{}]  {}".format(str(v.ViewType), v.Name)
            if ft and ft not in label.lower():
                continue
            self.panel_views.Children.Add(
                self._make_view_cb(label, v.Id)
            )

    def _render_cats(self, filter_text):
        """Clear and rebuild the category checkbox panel, respecting the search filter."""
        ft = filter_text.strip().lower()
        self.panel_cats.Children.Clear()
        for name in ALL_CATS:
            if ft and ft not in name.lower():
                continue
            self.panel_cats.Children.Add(self._make_cat_cb(name))

    # ── Radio-toggle helpers ──────────────────────────────────────────────────
    def _radio(self, group, active):
        """Enforce single-active-item within a toggle-button group."""
        if self._lock[0]:
            return
        self._lock[0] = True
        for btn in group:
            btn.IsChecked = (btn is active)
        self._lock[0] = False

    def _guard(self, sender, e):
        """Prevent the user from unchecking the already-active radio button."""
        if not self._lock[0]:
            sender.IsChecked = True

    # ── Event handlers ────────────────────────────────────────────────────────
    def _on_action(self, sender, e):
        if not self._lock[0]:
            self._radio([self.btn_pin, self.btn_unpin], sender)

    def _on_scope(self, sender, e):
        if not self._lock[0]:
            self._radio([self.btn_cur, self.btn_sel, self.btn_proj], sender)
        self.pnl_views.Visibility = (
            Visibility.Visible if sender is self.btn_sel else Visibility.Collapsed
        )

    def _on_view_search(self, sender, e):
        self._render_views(sender.Text)

    def _on_cat_search(self, sender, e):
        self._render_cats(sender.Text)

    def _on_cat_tog(self, sender, e):
        on = bool(sender.IsChecked)
        sender.Content           = "ON"  if on else "OFF"
        self.pnl_cats.Visibility = Visibility.Visible if on else Visibility.Collapsed

    def _cancel(self, sender, e):
        self.win.Close()

    def _run(self, sender, e):
        # Determine scope
        if   self.btn_cur.IsChecked:  scope = 'current'
        elif self.btn_sel.IsChecked:  scope = 'views'
        else:                         scope = 'project'

        # Validate view selection
        sel_view_ids = [vid for vid, chk in self._view_checked.items() if chk]
        if scope == 'views' and not sel_view_ids:
            MessageBox.Show(
                "Please check at least one view.",
                "Pin / Unpin Manager",
                MessageBoxButton.OK,
                MessageBoxImage.Warning
            )
            return

        # Validate category selection
        use_cats = bool(self.btn_cat_tog.IsChecked)
        sel_cats = [n for n, chk in self._cat_checked.items() if chk]
        if use_cats and not sel_cats:
            MessageBox.Show(
                "Category filter is ON but no categories are checked.\n"
                "Please check at least one category, or turn the filter OFF.",
                "Pin / Unpin Manager",
                MessageBoxButton.OK,
                MessageBoxImage.Warning
            )
            return

        self.result = {
            'pin'      : bool(self.btn_pin.IsChecked),
            'scope'    : scope,
            'view_ids' : set(sel_view_ids),
            'use_cats' : use_cats,
            'cats'     : set(sel_cats),
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
view_ids = cfg['view_ids']
use_cats = cfg['use_cats']
cats     = cfg['cats']
label    = "Pin" if pin_val else "Unpin"

# ── Element collection helpers ────────────────────────────────────────────────
def passes_cat(elem):
    """True if element passes the category filter (or filter is off)."""
    if not use_cats:
        return True
    try:
        return elem.Category is not None and elem.Category.Name in cats
    except Exception:
        return False

def elems_in_view(view_id):
    """Non-type elements visible in the given view."""
    try:
        return list(
            FilteredElementCollector(doc, view_id)
            .WhereElementIsNotElementType()
            .ToElements()
        )
    except Exception:
        return []

# ── Collect elements based on scope + category filter ────────────────────────
elements = []

if scope == 'current':
    elements = [e for e in elems_in_view(doc.ActiveView.Id) if passes_cat(e)]

elif scope == 'views':
    seen = set()
    for v in ALL_VIEWS:
        if v.Id not in view_ids:
            continue
        for e in elems_in_view(v.Id):
            eid = e.Id
            if eid not in seen:
                seen.add(eid)
                if passes_cat(e):
                    elements.append(e)

elif scope == 'project':
    if use_cats:
        # Per-BuiltInCategory collectors are fast and precise
        seen    = set()
        cat_map = {c.Name: c for c in doc.Settings.Categories}
        for cname in cats:
            cat = cat_map.get(cname)
            if cat is None:
                continue
            try:
                for e in (
                    FilteredElementCollector(doc)
                    .OfCategory(cat.BuiltInCategory)
                    .WhereElementIsNotElementType()
                    .ToElements()
                ):
                    eid = e.Id
                    if eid not in seen:
                        seen.add(eid)
                        elements.append(e)
            except Exception:
                pass
    else:
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
        e.Pinned  = pin_val
        ok_count += 1
    except Exception:
        skip_count += 1

t.Commit()

# ── Output summary ────────────────────────────────────────────────────────────
out = script.get_output()

scope_display = {
    'current': u'Current View  ({})'.format(doc.ActiveView.Name),
    'views'  : u'Selected Views  ({} views)'.format(len(view_ids)),
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
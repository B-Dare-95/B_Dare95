# -*- coding: utf-8 -*-
__title__ = "Enlarged Plan Generator"
__doc__   = """
_____________________________________________________________________
Description:
Generates Enlarged Plan views and two cross-sections for selected
rooms. Both sections are centred on each room:
  - Section X  : cut plane is a YZ plane, camera looks along +X
  - Section Y  : cut plane is an XZ plane, camera looks along +Y

View names follow the pattern:
  {Prefix}{RoomName}_{RoomNumber}{Suffix}
  {Prefix}{RoomName}_{RoomNumber} - Section X{Suffix}
  {Prefix}{RoomName}_{RoomNumber} - Section Y{Suffix}

All settings are configured in a single Catppuccin-themed WPF window.
_____________________________________________________________________
Author: Mohamed Bedair"""

# ── Imports ──────────────────────────────────────────────────────────────────
from Autodesk.Revit.DB import (
    BoundingBoxXYZ, BuiltInCategory, BuiltInParameter,
    ElementTypeGroup, FilteredElementCollector,
    Transaction, Transform, UnitTypeId, UnitUtils,
    ViewDetailLevel, ViewFamilyType, ViewFamily, ViewPlan, ViewSection,
    XYZ, View,
)

import clr
clr.AddReference("System")
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from System.Windows        import MessageBox, MessageBoxButton, Visibility
from System.Windows.Controls import CheckBox, ListBoxItem, ComboBoxItem
from System.Windows.Markup   import XamlReader
from System.Windows.Media    import SolidColorBrush, Color

# ── Revit handles ─────────────────────────────────────────────────────────────
uidoc = __revit__.ActiveUIDocument
doc   = __revit__.ActiveUIDocument.Document

# ── Constants ─────────────────────────────────────────────────────────────────
OFFSET_CM = 50   # padding around crop box (centimetres)

# ══════════════════════════════════════════════════════════════════════════════
# UTILITY FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def rename_view(view, new_name):
    """Set view.Name; append '*' until the name is unique."""
    for _ in range(20):
        try:
            view.Name = new_name
            return
        except Exception:
            new_name += '*'


def get_cm(value_cm):
    """Convert centimetres to Revit internal units (decimal feet)."""
    return UnitUtils.ConvertToInternalUnits(value_cm, UnitTypeId.Centimeters)


def get_room_corners(bb):
    """Return all 8 corners of a BoundingBoxXYZ as a list of XYZ points."""
    pts = []
    for x in [bb.Min.X, bb.Max.X]:
        for y in [bb.Min.Y, bb.Max.Y]:
            for z in [bb.Min.Z, bb.Max.Z]:
                pts.append(XYZ(x, y, z))
    return pts


def get_local_extents(bb, transform):
    """
    Return axis-aligned extents of all 8 BB corners expressed in *transform*'s
    local frame. Returns (min_x, max_x, min_y, max_y, min_z, max_z).
    """
    inv   = transform.Inverse
    local = [inv.OfPoint(p) for p in get_room_corners(bb)]
    return (
        min(p.X for p in local), max(p.X for p in local),
        min(p.Y for p in local), max(p.Y for p in local),
        min(p.Z for p in local), max(p.Z for p in local),
    )


# ══════════════════════════════════════════════════════════════════════════════
# VIEW GEOMETRY HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def make_floor_plan_crop_box(room, ref_view):
    """
    Axis-aligned BoundingBoxXYZ tightly fitted around *room* with uniform
    padding on all sides. No transform applied — keeps north-up orientation.
    """
    offset = get_cm(OFFSET_CM)
    bb = room.get_BoundingBox(ref_view)
    if bb is None:
        return None
    new_bb     = BoundingBoxXYZ()
    new_bb.Min = XYZ(bb.Min.X - offset, bb.Min.Y - offset, bb.Min.Z - offset)
    new_bb.Max = XYZ(bb.Max.X + offset, bb.Max.Y + offset, bb.Max.Z + offset)
    return new_bb


def get_section_type_id(doc):
    """Return the ElementId of the first Section ViewFamilyType found."""
    for vft in FilteredElementCollector(doc).OfClass(ViewFamilyType):
        if vft.ViewFamily == ViewFamily.Section:
            return vft.Id
    return None


def make_section_bb(room, ref_view, origin, view_dir_xy):
    """
    Build a BoundingBoxXYZ suitable for ViewSection.CreateSection.

    Convention
    ----------
    BasisZ  — look direction (camera looks along +BasisZ)
    BasisX  — right direction in section (horizontal)
    BasisY  — up direction in section  (world Z)

    The cut plane sits at *origin*. Min.Z = 0 (the cut plane itself);
    Max.Z spans the room depth plus padding.
    """
    offset = get_cm(OFFSET_CM)
    bb = room.get_BoundingBox(ref_view)
    if bb is None:
        return None

    world_up  = XYZ(0.0, 0.0, 1.0)
    z_axis    = view_dir_xy
    x_axis    = z_axis.CrossProduct(world_up).Normalize()
    y_axis    = world_up

    tf         = Transform.Identity
    tf.BasisX  = x_axis
    tf.BasisY  = y_axis
    tf.BasisZ  = z_axis
    tf.Origin  = origin

    mn_x, mx_x, mn_y, mx_y, mn_z, mx_z = get_local_extents(bb, tf)

    sec_bb           = BoundingBoxXYZ()
    sec_bb.Transform = tf
    sec_bb.Min       = XYZ(mn_x - offset, mn_y - offset, 0.0)
    sec_bb.Max       = XYZ(mx_x + offset, mx_y + offset, (mx_z - mn_z) + offset)
    return sec_bb


# ══════════════════════════════════════════════════════════════════════════════
# DATA COLLECTION
# ══════════════════════════════════════════════════════════════════════════════

_all_rooms_raw = (
    FilteredElementCollector(doc)
    .OfCategory(BuiltInCategory.OST_Rooms)
    .WhereElementIsNotElementType()
    .ToElements()
)

placed_rooms = sorted(
    [r for r in _all_rooms_raw if r.Area > 0],
    key=lambda r: (
        r.get_Parameter(BuiltInParameter.ROOM_NAME).AsString()   or '',
        r.get_Parameter(BuiltInParameter.ROOM_NUMBER).AsString() or '',
    )
)

_all_views_raw = FilteredElementCollector(doc).OfClass(View).ToElements()
view_templates = sorted(
    [vt for vt in _all_views_raw if vt.IsTemplate],
    key=lambda vt: vt.Name
)
vt_names = [vt.Name for vt in view_templates]
vt_dict  = {vt.Name: vt for vt in view_templates}

plan_type_id = doc.GetDefaultElementTypeId(ElementTypeGroup.ViewTypeFloorPlan)
sec_type_id  = get_section_type_id(doc)


# ══════════════════════════════════════════════════════════════════════════════
# WPF WINDOW — XAML
# ══════════════════════════════════════════════════════════════════════════════

XAML = """<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Enlarged Plan Generator"
    Width="780" Height="600"
    MinWidth="680" MinHeight="480"
    WindowStartupLocation="CenterScreen"
    Background="#1E1E2E"
    ResizeMode="CanResizeWithGrip"
    FontFamily="Segoe UI">

    <Window.Resources>

        <!-- ── ListBoxItem ── -->
        <Style TargetType="ListBoxItem">
            <Setter Property="Background"  Value="Transparent"/>
            <Setter Property="Padding"     Value="2,1"/>
            <Setter Property="Margin"      Value="0,1"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="ListBoxItem">
                        <Border Name="Bd"
                                Background="{TemplateBinding Background}"
                                CornerRadius="5"
                                Padding="6,3">
                            <ContentPresenter/>
                        </Border>
                        <ControlTemplate.Triggers>
                            <Trigger Property="IsMouseOver" Value="True">
                                <Setter TargetName="Bd" Property="Background" Value="#45475A"/>
                            </Trigger>
                            <Trigger Property="IsSelected" Value="True">
                                <Setter TargetName="Bd" Property="Background" Value="#313244"/>
                            </Trigger>
                        </ControlTemplate.Triggers>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>

        <!-- ── CheckBox ── -->
        <Style TargetType="CheckBox">
            <Setter Property="Foreground"              Value="#CDD6F4"/>
            <Setter Property="FontSize"                Value="12"/>
            <Setter Property="VerticalContentAlignment" Value="Center"/>
            <Setter Property="Cursor"                  Value="Hand"/>
        </Style>

        <!-- ── ComboBoxItem ── -->
        <Style TargetType="ComboBoxItem">
            <Setter Property="Background" Value="#313244"/>
            <Setter Property="Foreground" Value="#CDD6F4"/>
            <Setter Property="Padding"    Value="10,6"/>
            <Setter Property="FontSize"   Value="12"/>
        </Style>

        <!-- ── Generate Button ── -->
        <Style x:Key="AccentButton" TargetType="Button">
            <Setter Property="Background"   Value="#F0A500"/>
            <Setter Property="Foreground"   Value="#1E1E2E"/>
            <Setter Property="FontWeight"   Value="Bold"/>
            <Setter Property="FontSize"     Value="13"/>
            <Setter Property="BorderThickness" Value="0"/>
            <Setter Property="Cursor"       Value="Hand"/>
            <Setter Property="Height"       Value="42"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="Button">
                        <Border Name="Bd"
                                Background="{TemplateBinding Background}"
                                CornerRadius="9">
                            <ContentPresenter HorizontalAlignment="Center"
                                              VerticalAlignment="Center"/>
                        </Border>
                        <ControlTemplate.Triggers>
                            <Trigger Property="IsMouseOver" Value="True">
                                <Setter TargetName="Bd" Property="Background" Value="#D4940A"/>
                            </Trigger>
                            <Trigger Property="IsPressed" Value="True">
                                <Setter TargetName="Bd" Property="Background" Value="#A87200"/>
                            </Trigger>
                            <Trigger Property="IsEnabled" Value="False">
                                <Setter TargetName="Bd" Property="Background" Value="#45475A"/>
                                <Setter Property="Foreground" Value="#585B70"/>
                            </Trigger>
                        </ControlTemplate.Triggers>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>

    </Window.Resources>

    <!-- ══════════════════ ROOT GRID ══════════════════ -->
    <Grid Margin="20,18,20,20">
        <Grid.ColumnDefinitions>
            <ColumnDefinition Width="260"/>
            <ColumnDefinition Width="20"/>
            <ColumnDefinition Width="*"/>
        </Grid.ColumnDefinitions>

        <!-- ════════════════ LEFT — Room List ════════════════ -->
        <Grid Grid.Column="0">
            <Grid.RowDefinitions>
                <RowDefinition Height="Auto"/>   <!-- section label  -->
                <RowDefinition Height="10"/>
                <RowDefinition Height="Auto"/>   <!-- search bar     -->
                <RowDefinition Height="8"/>
                <RowDefinition Height="Auto"/>   <!-- select-all     -->
                <RowDefinition Height="8"/>
                <RowDefinition Height="*"/>      <!-- room list      -->
            </Grid.RowDefinitions>

            <!-- Section label -->
            <TextBlock Grid.Row="0"
                       Text="R O O M S"
                       Foreground="#F0A500"
                       FontSize="10"
                       FontWeight="Bold"
                       />

            <!-- Search box -->
            <Border Grid.Row="2"
                    Background="#313244"
                    CornerRadius="6"
                    BorderBrush="#45475A"
                    BorderThickness="1">
                <Grid>
                    <TextBlock x:Name="SearchPlaceholder"
                               Text="Search rooms..."
                               Foreground="#585B70"
                               FontSize="12"
                               Padding="10,7,0,0"
                               IsHitTestVisible="False"/>
                    <TextBox x:Name="SearchBox"
                             Background="Transparent"
                             Foreground="#CDD6F4"
                             BorderThickness="0"
                             Padding="8,6"
                             FontSize="12"
                             CaretBrush="#CDD6F4"
                             VerticalContentAlignment="Center"/>
                </Grid>
            </Border>

            <!-- Select All -->
            <CheckBox x:Name="SelectAllBox"
                      Grid.Row="4"
                      Content="Select All"
                      Foreground="#A6ADC8"
                      FontSize="11"/>

            <!-- Room list container -->
            <Border Grid.Row="6"
                    Background="#2A2A3C"
                    CornerRadius="9"
                    BorderBrush="#313244"
                    BorderThickness="1"
                    Padding="6,6,3,6">
                <ListBox x:Name="RoomListBox"
                         Background="Transparent"
                         BorderThickness="0"
                         ScrollViewer.VerticalScrollBarVisibility="Auto"
                         ScrollViewer.HorizontalScrollBarVisibility="Disabled"/>
            </Border>
        </Grid>

        <!-- ════════════════ RIGHT — Settings ════════════════ -->
        <Grid Grid.Column="2">
            <Grid.RowDefinitions>
                <RowDefinition Height="Auto"/>   <!-- section label       -->
                <RowDefinition Height="16"/>
                <RowDefinition Height="Auto"/>   <!-- plan template       -->
                <RowDefinition Height="14"/>
                <RowDefinition Height="Auto"/>   <!-- section template    -->
                <RowDefinition Height="20"/>
                <RowDefinition Height="Auto"/>   <!-- divider             -->
                <RowDefinition Height="20"/>
                <RowDefinition Height="Auto"/>   <!-- prefix/suffix label -->
                <RowDefinition Height="8"/>
                <RowDefinition Height="Auto"/>   <!-- prefix/suffix boxes -->
                <RowDefinition Height="*"/>      <!-- spacer + preview    -->
                <RowDefinition Height="Auto"/>   <!-- generate button     -->
            </Grid.RowDefinitions>

            <!-- Section label -->
            <TextBlock Grid.Row="0"
                       Text="S E T T I N G S"
                       Foreground="#F0A500"
                       FontSize="10"
                       FontWeight="Bold"
                       />

            <!-- ── Plan View Template ── -->
            <StackPanel Grid.Row="2">
                <TextBlock Text="Enlarged Plan  —  View Template"
                           Foreground="#A6ADC8"
                           FontSize="11"
                           Margin="0,0,0,7"/>
                <Border Background="#313244"
                        CornerRadius="6"
                        BorderBrush="#45475A"
                        BorderThickness="1">
                    <ComboBox x:Name="PlanTemplateCombo"
                              Background="Transparent"
                              Foreground="#000000"
                              BorderThickness="0"
                              Padding="8,0"
                              FontSize="12"
                              Height="36"/>
                </Border>
            </StackPanel>

            <!-- ── Section View Template ── -->
            <StackPanel Grid.Row="4">
                <TextBlock Text="Section  —  View Template"
                           Foreground="#A6ADC8"
                           FontSize="11"
                           Margin="0,0,0,7"/>
                <Border Background="#313244"
                        CornerRadius="6"
                        BorderBrush="#45475A"
                        BorderThickness="1">
                    <ComboBox x:Name="SectionTemplateCombo"
                              Background="Transparent"
                              Foreground="#000000"
                              BorderThickness="0"
                              Padding="8,0"
                              FontSize="12"
                              Height="36"/>
                </Border>
            </StackPanel>

            <!-- Divider -->
            <Border Grid.Row="6" Height="1" Background="#45475A"/>

            <!-- ── Prefix / Suffix labels ── -->
            <Grid Grid.Row="8">
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="12"/>
                    <ColumnDefinition Width="*"/>
                </Grid.ColumnDefinitions>
                <TextBlock Grid.Column="0"
                           Text="Prefix"
                           Foreground="#A6ADC8"
                           FontSize="11"/>
                <TextBlock Grid.Column="2"
                           Text="Suffix"
                           Foreground="#A6ADC8"
                           FontSize="11"/>
            </Grid>

            <!-- ── Prefix / Suffix text boxes ── -->
            <Grid Grid.Row="10">
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="12"/>
                    <ColumnDefinition Width="*"/>
                </Grid.ColumnDefinitions>

                <Border Grid.Column="0"
                        Background="#313244"
                        CornerRadius="6"
                        BorderBrush="#45475A"
                        BorderThickness="1">
                    <TextBox x:Name="PrefixBox"
                             Background="Transparent"
                             Foreground="#CDD6F4"
                             BorderThickness="0"
                             Padding="8,0"
                             FontSize="12"
                             Height="36"
                             CaretBrush="#CDD6F4"
                             Text="EP - "
                             VerticalContentAlignment="Center"/>
                </Border>

                <Border Grid.Column="2"
                        Background="#313244"
                        CornerRadius="6"
                        BorderBrush="#45475A"
                        BorderThickness="1">
                    <TextBox x:Name="SuffixBox"
                             Background="Transparent"
                             Foreground="#CDD6F4"
                             BorderThickness="0"
                             Padding="8,0"
                             FontSize="12"
                             Height="36"
                             CaretBrush="#CDD6F4"
                             VerticalContentAlignment="Center"/>
                </Border>
            </Grid>

            <!-- Preview / spacer -->
            <StackPanel Grid.Row="11" VerticalAlignment="Bottom" Margin="0,0,0,16">
                <TextBlock x:Name="PreviewLabel"
                           Foreground="#585B70"
                           FontSize="11"
                           TextWrapping="Wrap"/>
            </StackPanel>

            <!-- Generate button -->
            <Button x:Name="GenerateBtn"
                    Grid.Row="12"
                    Content="Generate Views"
                    Style="{StaticResource AccentButton}"/>
        </Grid>
    </Grid>
</Window>"""


# ══════════════════════════════════════════════════════════════════════════════
# WPF WINDOW — PYTHON CONTROLLER
# ══════════════════════════════════════════════════════════════════════════════

class EnlargedPlanUI(object):
    """Single-window controller for the Enlarged Plan Generator."""

    # Catppuccin palette shortcuts
    _TEXT    = Color.FromRgb(0xCD, 0xD6, 0xF4)   # #CDD6F4
    _SUBTEXT = Color.FromRgb(0xA6, 0xAD, 0xC8)   # #A6ADC8

    def __init__(self):
        self.window     = XamlReader.Parse(XAML)
        self.confirmed  = [False]
        # Each entry: (display_lower, room, CheckBox, ListBoxItem)
        self._all_items = []

        self._get_controls()
        self._populate_rooms()
        self._populate_combos()
        self._attach_events()
        self._update_preview()

    # ── Control References ────────────────────────────────────────────────────

    def _get_controls(self):
        w = self.window
        self.search_placeholder  = w.FindName('SearchPlaceholder')
        self.search_box          = w.FindName('SearchBox')
        self.room_listbox        = w.FindName('RoomListBox')
        self.select_all_cb       = w.FindName('SelectAllBox')
        self.plan_combo          = w.FindName('PlanTemplateCombo')
        self.sec_combo           = w.FindName('SectionTemplateCombo')
        self.prefix_box          = w.FindName('PrefixBox')
        self.suffix_box          = w.FindName('SuffixBox')
        self.preview_label       = w.FindName('PreviewLabel')
        self.generate_btn        = w.FindName('GenerateBtn')

    # ── Population ────────────────────────────────────────────────────────────

    def _populate_rooms(self):
        fg = SolidColorBrush(self._TEXT)
        for room in placed_rooms:
            name   = room.get_Parameter(BuiltInParameter.ROOM_NAME).AsString()   or ''
            number = room.get_Parameter(BuiltInParameter.ROOM_NUMBER).AsString() or ''
            display = u'{} \u2014 {}'.format(number, name) if number else name

            cb          = CheckBox()
            cb.Content  = display
            cb.Foreground = fg
            cb.Tag      = room

            li         = ListBoxItem()
            li.Content = cb

            self.room_listbox.Items.Add(li)
            self._all_items.append((display.lower(), room, cb, li))

    def _populate_combos(self):
        subtext_brush = SolidColorBrush(self._SUBTEXT)
        text_brush    = SolidColorBrush(self._TEXT)

        for combo in [self.plan_combo, self.sec_combo]:
            none_ci           = ComboBoxItem()
            none_ci.Content   = u'<None>'
            none_ci.Foreground = subtext_brush
            combo.Items.Add(none_ci)

            for name in vt_names:
                ci           = ComboBoxItem()
                ci.Content   = name
                ci.Foreground = text_brush
                combo.Items.Add(ci)

            combo.SelectedIndex = 0

    # ── Event Wiring ──────────────────────────────────────────────────────────

    def _attach_events(self):
        self.search_box.TextChanged   += self._on_search
        self.search_box.GotFocus      += self._on_search_focus
        self.search_box.LostFocus     += self._on_search_blur
        self.select_all_cb.Checked    += self._on_select_all_checked
        self.select_all_cb.Unchecked  += self._on_select_all_unchecked
        self.prefix_box.TextChanged   += self._on_naming_changed
        self.suffix_box.TextChanged   += self._on_naming_changed
        self.generate_btn.Click       += self._on_generate

    # ── Event Handlers ────────────────────────────────────────────────────────

    def _on_search_focus(self, sender, e):
        self.search_placeholder.Visibility = Visibility.Collapsed

    def _on_search_blur(self, sender, e):
        if not self.search_box.Text:
            self.search_placeholder.Visibility = Visibility.Visible

    def _on_search(self, sender, e):
        query = (self.search_box.Text or u'').strip().lower()
        for display_lower, room, cb, li in self._all_items:
            li.Visibility = (
                Visibility.Visible
                if not query or query in display_lower
                else Visibility.Collapsed
            )

    def _on_select_all_checked(self, sender, e):
        for _, _, cb, li in self._all_items:
            if li.Visibility == Visibility.Visible:
                cb.IsChecked = True

    def _on_select_all_unchecked(self, sender, e):
        for _, _, cb, li in self._all_items:
            cb.IsChecked = False

    def _on_naming_changed(self, sender, e):
        self._update_preview()

    def _update_preview(self):
        prefix = self.prefix_box.Text or u''
        suffix = self.suffix_box.Text or u''
        self.preview_label.Text = (
            u'\u2192  e.g.  \u201c{prefix}RoomName_RoomNumber{suffix}\u201d'
            u'\n\u2192  e.g.  \u201c{prefix}RoomName_RoomNumber - Section X{suffix}\u201d'
        ).format(prefix=prefix, suffix=suffix)

    def _get_selected_vt(self, combo):
        """Return the ViewTemplate element for the combo's selection, or None."""
        item = combo.SelectedItem
        if item is None:
            return None
        name = item.Content
        return vt_dict.get(name, None)

    def _on_generate(self, sender, e):
        selected = [room for _, room, cb, _ in self._all_items if cb.IsChecked]
        if not selected:
            MessageBox.Show(
                'Please check at least one room.',
                'No Rooms Selected',
                MessageBoxButton.OK
            )
            return

        self.confirmed[0] = True
        self.window.Tag   = (
            selected,
            self._get_selected_vt(self.plan_combo),
            self._get_selected_vt(self.sec_combo),
            self.prefix_box.Text or u'',
            self.suffix_box.Text or u'',
        )
        self.window.Close()

    # ── Entry Point ───────────────────────────────────────────────────────────

    def show(self):
        self.window.ShowDialog()
        if self.confirmed[0]:
            return self.window.Tag
        return None


# ══════════════════════════════════════════════════════════════════════════════
# MAIN — Show UI, then create views
# ══════════════════════════════════════════════════════════════════════════════

ui     = EnlargedPlanUI()
result = ui.show()

if result is None:
    print('Cancelled — no views were created.')
else:
    selected_rooms, vt_plans, vt_secs, prefix, suffix = result

    print('Processing {} room(s)...\n'.format(len(selected_rooms)))

    t = Transaction(doc, 'Enlarged Plan Generator v4')
    t.Start()

    try:
        for room in selected_rooms:
            room_name   = room.get_Parameter(BuiltInParameter.ROOM_NAME).AsString()   or 'Room'
            room_number = room.get_Parameter(BuiltInParameter.ROOM_NUMBER).AsString() or ''
            lvl_id      = room.LevelId
            tag         = '{}_{}'.format(room_name, room_number) if room_number else room_name

            print('Processing: {}'.format(tag))

            # ── 1. Enlarged Floor Plan ─────────────────────────────────────────
            plan_name = u'{}{}{}'.format(prefix, tag, suffix)
            new_plan  = ViewPlan.Create(doc, plan_type_id, lvl_id)
            rename_view(new_plan, plan_name)

            crop_bb = make_floor_plan_crop_box(room, new_plan)
            if crop_bb is not None:
                new_plan.CropBox        = crop_bb
                new_plan.CropBoxActive  = True
                new_plan.CropBoxVisible = True

            # new_plan.DetailLevel = ViewDetailLevel.Fine

            if vt_plans is not None:
                try:
                    new_plan.ViewTemplateId = vt_plans.Id
                except Exception as ex:
                    print('  [WARN] Could not apply plan template: {}'.format(ex))

            print('  [OK] Enlarged Plan  :  {}'.format(plan_name))

            # Derive room centre from the newly created plan's bounding box.
            plan_bb     = room.get_BoundingBox(new_plan)
            room_centre = (plan_bb.Min + plan_bb.Max) * 0.5 if plan_bb else XYZ.Zero

            # ── 2. Section X — cut plane is YZ, camera looks along +X ─────────
            #
            #   view_dir = (1, 0, 0)
            #   → BasisX  = (1,0,0) × (0,0,1) normalised  =  (0,-1,0)  (right)
            #   → BasisY  = (0,0,1)                                      (up)
            #   → BasisZ  = (1,0,0)                                      (look)
            #
            sec_x_name = u'{}{} - Section X{}'.format(prefix, tag, suffix)
            sec_x_bb   = make_section_bb(room, new_plan, room_centre, XYZ(1.0, 0.0, 0.0))

            if sec_x_bb is not None and sec_type_id is not None:
                sec_x             = ViewSection.CreateSection(doc, sec_type_id, sec_x_bb)
                # sec_x.DetailLevel = ViewDetailLevel.Fine
                rename_view(sec_x, sec_x_name)
                if vt_secs is not None:
                    try:
                        sec_x.ViewTemplateId = vt_secs.Id
                    except Exception as ex:
                        print('  [WARN] Could not apply section template: {}'.format(ex))
                print('  [OK] Section X      :  {}'.format(sec_x_name))
            else:
                print('  [WARN] Could not create Section X for {}.'.format(tag))

            # ── 3. Section Y — cut plane is XZ, camera looks along +Y ─────────
            #
            #   view_dir = (0, 1, 0)
            #   → BasisX  = (0,1,0) × (0,0,1) normalised  =  (1, 0,0)  (right)
            #   → BasisY  = (0,0,1)                                      (up)
            #   → BasisZ  = (0,1,0)                                      (look)
            #
            sec_y_name = u'{}{} - Section Y{}'.format(prefix, tag, suffix)
            sec_y_bb   = make_section_bb(room, new_plan, room_centre, XYZ(0.0, 1.0, 0.0))

            if sec_y_bb is not None and sec_type_id is not None:
                sec_y             = ViewSection.CreateSection(doc, sec_type_id, sec_y_bb)
                # sec_y.DetailLevel = ViewDetailLevel.Fine
                rename_view(sec_y, sec_y_name)
                if vt_secs is not None:
                    try:
                        sec_y.ViewTemplateId = vt_secs.Id
                    except Exception as ex:
                        print('  [WARN] Could not apply section template: {}'.format(ex))
                print('  [OK] Section Y      :  {}'.format(sec_y_name))
            else:
                print('  [WARN] Could not create Section Y for {}.'.format(tag))

            print('')

        t.Commit()
        print('Done. {} room(s) processed successfully.'.format(len(selected_rooms)))

    except Exception:
        t.RollBack()
        import traceback
        print(traceback.format_exc())
        raise
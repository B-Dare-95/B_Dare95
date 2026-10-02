# -*- coding: utf-8 -*-
"""Orphaned Tag Fixer

Scans every view in the document for orphaned tags and fixes them in one go:
  - Tagged element still exists (host or link)  -> tag is re-attached to it
  - Tagged element no longer exists             -> tag is deleted
A per-category summary is shown before anything is changed.
"""
__title__ = "Orphaned\nTags"
__author__ = "Mohamed Bedair"

import clr
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")
clr.AddReference("System.Data")

from System import Boolean, String, Int32, EventHandler
from System.Collections.Generic import List
from System.Data import DataTable
from System.Windows import Clipboard, RoutedEventHandler, Visibility
from System.Windows.Controls import TextChangedEventHandler
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Markup import XamlReader
from System.Windows.Threading import Dispatcher, DispatcherFrame

from Autodesk.Revit.DB import (
    AreaTag, CheckoutStatus, ElementId, ElementTransformUtils,
    FilteredElementCollector, IndependentTag, LinkElementId, LocationCurve,
    LocationPoint, Reference, SpatialElementTag, SubTransaction, TagOrientation,
    Transaction, TransactionStatus, UV, ViewPlan, WorksharingUtils, XYZ
)
from Autodesk.Revit.DB.Architecture import RoomTag
from Autodesk.Revit.DB.Mechanical import SpaceTag
from Autodesk.Revit.UI import TaskDialog

from pyrevit import forms, script


doc = __revit__.ActiveUIDocument.Document

TITLE = "Orphaned Tag Fixer"
INVALID = ElementId.InvalidElementId

REATTACH = "reattach"
DELETE = "delete"
SKIP = "skip"

KIND_INDEPENDENT = "independent"
KIND_SPATIAL = "spatial"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def eid_int(eid):
    try:
        return eid.Value
    except AttributeError:
        return eid.IntegerValue


def is_valid_id(eid):
    return eid is not None and eid != INVALID


def short_error(ex):
    lines = [l for l in str(ex).strip().splitlines() if l.strip()]
    msg = lines[0] if lines else "Unknown error"
    return msg[:110]


_view_cache = {}


def get_view(view_id):
    key = eid_int(view_id)
    if key not in _view_cache:
        _view_cache[key] = doc.GetElement(view_id)
    return _view_cache[key]


def resolve_link_element_id(leid):
    """Return (status, element, link_instance). status: ok | missing | unloaded."""
    if leid is None:
        return "missing", None, None
    if is_valid_id(leid.LinkInstanceId):
        inst = doc.GetElement(leid.LinkInstanceId)
        if inst is None:
            return "missing", None, None
        link_doc = inst.GetLinkDocument()
        if link_doc is None:
            return "unloaded", None, inst
        el = link_doc.GetElement(leid.LinkedElementId)
        return ("ok" if el is not None else "missing"), el, inst
    el = doc.GetElement(leid.HostElementId) if is_valid_id(leid.HostElementId) else None
    return ("ok" if el is not None else "missing"), el, None


def element_point(el, inst):
    """Representative point of an element, in host coordinates."""
    pt = None
    try:
        loc = el.Location
        if isinstance(loc, LocationPoint):
            pt = loc.Point
        elif isinstance(loc, LocationCurve):
            pt = loc.Curve.Evaluate(0.5, True)
    except Exception:
        pt = None
    if pt is None:
        bb = el.get_BoundingBox(None)
        if bb is not None:
            pt = bb.Min.Add(bb.Max).Multiply(0.5)
    if pt is not None and inst is not None:
        pt = inst.GetTotalTransform().OfPoint(pt)
    return pt


def common_skip_reason(tag):
    """Reasons to leave a tag alone regardless of its orphan state."""
    if is_valid_id(tag.GroupId):
        return "Inside a group"
    if doc.IsWorkshared:
        try:
            if WorksharingUtils.GetCheckoutStatus(doc, tag.Id) == CheckoutStatus.OwnedByOtherUser:
                return "Owned by another user"
        except Exception:
            pass
    return None


def spatial_label(tag):
    if isinstance(tag, RoomTag):
        return "Room"
    if isinstance(tag, SpaceTag):
        return "Space"
    return "Area"


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------
class TagRecord(object):
    def __init__(self, tag, kind, view, action, reason, targets):
        self.tag_id = tag.Id
        self.tag_int = eid_int(tag.Id)
        self.kind = kind
        try:
            self.category = tag.Category.Name
        except Exception:
            self.category = "Uncategorized Tags"
        self.view_int = eid_int(tag.OwnerViewId)
        self.view_name = view.Name if view is not None else "<no view>"
        self.action = action
        self.reason = reason
        self.targets = targets  # list of (element, link_instance or None)


def classify_independent(tag):
    try:
        orphan = tag.IsOrphaned
    except Exception:
        orphan = False
    try:
        leids = list(tag.GetTaggedElementIds())
    except Exception:
        leids = []

    resolved = [resolve_link_element_id(l) for l in leids]
    found = [(el, inst) for status, el, inst in resolved if status == "ok"]
    unloaded = any(status == "unloaded" for status, _, _ in resolved)

    if not orphan and (found or not leids):
        return None  # healthy
    if unloaded:
        return SKIP, "Tagged link is not loaded", []
    if found:
        if tag.IsMaterialTag:
            return SKIP, "Material tag - re-attach manually", []
        return REATTACH, "Element exists - reference lost", found
    return DELETE, "Tagged element no longer exists", []


def spatial_host(tag):
    try:
        if isinstance(tag, RoomTag):
            try:
                return resolve_link_element_id(tag.TaggedRoomId)
            except Exception:
                el = tag.Room
        elif isinstance(tag, SpaceTag):
            el = tag.Space
        elif isinstance(tag, AreaTag):
            el = tag.Area
        else:
            el = None
    except Exception:
        el = None
    return ("ok" if el is not None else "missing"), el, None


def classify_spatial(tag, view):
    try:
        orphan = tag.IsOrphaned
    except Exception:
        orphan = False
    outside = False
    if not orphan and isinstance(tag, RoomTag):
        try:
            # Tags placed outside on purpose use a leader - leave those alone
            outside = (not tag.IsInRoom) and (not tag.HasLeader)
        except Exception:
            outside = False
    if not orphan and not outside:
        return None

    label = spatial_label(tag)
    status, el, inst = spatial_host(tag)
    if status == "unloaded":
        return SKIP, "Tagged link is not loaded", []
    if status == "missing":
        return DELETE, "{} no longer exists".format(label), []
    if element_point(el, inst) is None:
        return DELETE, "{} is not placed".format(label), []
    if not isinstance(view, ViewPlan):
        return SKIP, "Not a plan view - fix manually", []
    reason = "{} exists - tag orphaned".format(label) if orphan else "Tag sits outside its {}".format(label.lower())
    return REATTACH, reason, [(el, inst)]


def collect_orphans():
    ind = list(FilteredElementCollector(doc).OfClass(IndependentTag).WhereElementIsNotElementType())
    spa = list(FilteredElementCollector(doc).OfClass(SpatialElementTag).WhereElementIsNotElementType())
    all_tags = [(t, KIND_INDEPENDENT) for t in ind] + [(t, KIND_SPATIAL) for t in spa]
    total = len(all_tags)
    records = []
    if total == 0:
        return records

    with forms.ProgressBar(title="Scanning tags ({value} of {max_value})", cancellable=True) as pb:
        for i, (tag, kind) in enumerate(all_tags):
            if pb.cancelled:
                return None
            if i % 25 == 0:
                pb.update_progress(i, total)
            view = get_view(tag.OwnerViewId)
            if kind == KIND_INDEPENDENT:
                res = classify_independent(tag)
            else:
                res = classify_spatial(tag, view)
            if res is None:
                continue
            action, reason, targets = res
            if action != SKIP:
                blocked = common_skip_reason(tag)
                if blocked:
                    action, reason, targets = SKIP, blocked, []
            records.append(TagRecord(tag, kind, view, action, reason, targets))
    return records


# ---------------------------------------------------------------------------
# Summary window (IBM Carbon)
# ---------------------------------------------------------------------------
XAML = u'''
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Orphaned Tag Fixer" Width="780" Height="660"
        WindowStartupLocation="CenterScreen" ResizeMode="NoResize"
        Background="#161616" FontFamily="IBM Plex Sans, Segoe UI" FontSize="13">
  <Window.Resources>
    <Style x:Key="Btn" TargetType="Button">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="Padding" Value="18,8"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="bd" Background="{TemplateBinding Background}" CornerRadius="4" Padding="{TemplateBinding Padding}">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="bd" Property="Opacity" Value="0.85"/>
              </Trigger>
              <Trigger Property="IsEnabled" Value="False">
                <Setter TargetName="bd" Property="Opacity" Value="0.4"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style x:Key="AccentBtn" TargetType="Button" BasedOn="{StaticResource Btn}">
      <Setter Property="Background" Value="#F1C21B"/>
      <Setter Property="Foreground" Value="#161616"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
    </Style>
    <Style x:Key="Toggle" TargetType="ToggleButton">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="Padding" Value="14,6"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ToggleButton">
            <Border x:Name="bd" Background="{TemplateBinding Background}" CornerRadius="4" Padding="{TemplateBinding Padding}">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsChecked" Value="True">
                <Setter TargetName="bd" Property="Background" Value="#F1C21B"/>
                <Setter Property="Foreground" Value="#161616"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style TargetType="GridViewColumnHeader">
      <Setter Property="Foreground" Value="#A8A8A8"/>
      <Setter Property="HorizontalContentAlignment" Value="Left"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="GridViewColumnHeader">
            <Border Background="#262626" BorderBrush="#525252" BorderThickness="0,0,0,1" Padding="6,8">
              <ContentPresenter HorizontalAlignment="{TemplateBinding HorizontalContentAlignment}" VerticalAlignment="Center"/>
            </Border>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style TargetType="ListViewItem">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ListViewItem">
            <Border x:Name="bd" Background="Transparent" BorderBrush="#393939" BorderThickness="0,0,0,1" Padding="0,6">
              <GridViewRowPresenter VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="bd" Property="Background" Value="#393939"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
  </Window.Resources>

  <Grid Margin="20">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <StackPanel Grid.Row="0" Margin="0,0,0,14">
      <TextBlock Text="Orphaned Tag Fixer" FontSize="20" FontWeight="SemiBold" Foreground="#F4F4F4"/>
      <TextBlock x:Name="SubTitle" Foreground="#A8A8A8" Margin="0,4,0,0"/>
    </StackPanel>

    <UniformGrid Grid.Row="1" Columns="3" Margin="0,0,0,14">
      <Border Background="#262626" CornerRadius="4" Padding="14,10" Margin="0,0,6,0">
        <StackPanel>
          <TextBlock x:Name="StatReattach" FontSize="24" FontWeight="SemiBold" Foreground="#42BE65"/>
          <TextBlock Text="Re-attach (element found)" Foreground="#A8A8A8"/>
        </StackPanel>
      </Border>
      <Border Background="#262626" CornerRadius="4" Padding="14,10" Margin="3,0,3,0">
        <StackPanel>
          <TextBlock x:Name="StatDelete" FontSize="24" FontWeight="SemiBold" Foreground="#FA4D56"/>
          <TextBlock Text="Delete (element gone)" Foreground="#A8A8A8"/>
        </StackPanel>
      </Border>
      <Border Background="#262626" CornerRadius="4" Padding="14,10" Margin="6,0,0,0">
        <StackPanel>
          <TextBlock x:Name="StatSkip" FontSize="24" FontWeight="SemiBold" Foreground="#A8A8A8"/>
          <TextBlock Text="Skipped (left untouched)" Foreground="#A8A8A8"/>
        </StackPanel>
      </Border>
    </UniformGrid>

    <Border Grid.Row="2" Background="#262626" CornerRadius="4" Padding="10,6" Margin="0,0,0,8">
      <Grid>
        <TextBlock x:Name="SearchHint" Text="Filter tag categories\u2026" Foreground="#6F6F6F"
                   IsHitTestVisible="False" VerticalAlignment="Center" Margin="2,0,0,0"/>
        <TextBox x:Name="SearchBox" Background="Transparent" BorderThickness="0"
                 Foreground="#F4F4F4" CaretBrush="#F4F4F4" VerticalAlignment="Center"/>
      </Grid>
    </Border>

    <ListView Grid.Row="3" x:Name="CatList" Background="#262626" BorderThickness="0" Foreground="#F4F4F4">
      <ListView.View>
        <GridView>
          <GridViewColumn Header="Fix" Width="50">
            <GridViewColumn.CellTemplate>
              <DataTemplate>
                <CheckBox IsChecked="{Binding Include, Mode=TwoWay, UpdateSourceTrigger=PropertyChanged}" Margin="4,0,0,0"/>
              </DataTemplate>
            </GridViewColumn.CellTemplate>
          </GridViewColumn>
          <GridViewColumn Header="Tag Category" Width="300" DisplayMemberBinding="{Binding Category}"/>
          <GridViewColumn Header="Re-attach" Width="100" DisplayMemberBinding="{Binding Reattach}"/>
          <GridViewColumn Header="Delete" Width="90" DisplayMemberBinding="{Binding Delete}"/>
          <GridViewColumn Header="Skipped" Width="90" DisplayMemberBinding="{Binding Skipped}"/>
          <GridViewColumn Header="Views" Width="80" DisplayMemberBinding="{Binding Views}"/>
        </GridView>
      </ListView.View>
    </ListView>

    <TextBlock Grid.Row="4" x:Name="SkipInfo" Foreground="#A8A8A8" TextWrapping="Wrap" Margin="0,10,0,0"/>

    <Border Grid.Row="5" Background="#262626" CornerRadius="4" Padding="14,10" Margin="0,12,0,0">
      <StackPanel>
        <StackPanel Orientation="Horizontal">
          <TextBlock Text="Re-attached tags:" Foreground="#F4F4F4" VerticalAlignment="Center" Margin="0,0,12,0"/>
          <ToggleButton x:Name="ModeMove" Style="{StaticResource Toggle}" Content="Move to element" Margin="0,0,6,0"/>
          <ToggleButton x:Name="ModeKeep" Style="{StaticResource Toggle}" Content="Keep position + leader"/>
        </StackPanel>
        <TextBlock Text="Room, Space and Area tags are always moved back inside their room / space / area."
                   Foreground="#A8A8A8" FontSize="12" Margin="0,8,0,0"/>
      </StackPanel>
    </Border>

    <DockPanel Grid.Row="6" Margin="0,14,0,0" LastChildFill="False">
      <Button x:Name="CopyBtn" DockPanel.Dock="Left" Style="{StaticResource Btn}" Content="Copy Report"/>
      <Button x:Name="FixBtn" DockPanel.Dock="Right" Style="{StaticResource AccentBtn}" Content="Fix Selected"/>
      <Button x:Name="CancelBtn" DockPanel.Dock="Right" Style="{StaticResource Btn}" Content="Cancel" Margin="0,0,8,0"/>
    </DockPanel>
  </Grid>
</Window>
'''


def escape_like(text):
    out = []
    for ch in text:
        if ch in "[]*%":
            out.append("[" + ch + "]")
        elif ch == "'":
            out.append("''")
        else:
            out.append(ch)
    return "".join(out)


def build_report(records):
    lines = [u"Tag Id\tCategory\tView\tAction\tReason"]
    for r in sorted(records, key=lambda x: (x.category, x.action, x.view_name)):
        lines.append(u"{}\t{}\t{}\t{}\t{}".format(r.tag_int, r.category, r.view_name, r.action, r.reason))
    return u"\n".join(lines)


def show_summary(records):
    cats = {}
    for r in records:
        c = cats.setdefault(r.category, {REATTACH: 0, DELETE: 0, SKIP: 0, "views": set()})
        c[r.action] += 1
        c["views"].add(r.view_int)

    win = XamlReader.Parse(XAML)
    find = win.FindName
    try:
        WindowInteropHelper(win).Owner = __revit__.MainWindowHandle
    except Exception:
        pass

    n_re = len([r for r in records if r.action == REATTACH])
    n_del = len([r for r in records if r.action == DELETE])
    n_skip = len([r for r in records if r.action == SKIP])
    n_views = len(set(r.view_int for r in records))
    find("SubTitle").Text = u"{} orphaned tags found in {} views \u2014 review, then confirm the fix.".format(
        len(records), n_views)
    find("StatReattach").Text = str(n_re)
    find("StatDelete").Text = str(n_del)
    find("StatSkip").Text = str(n_skip)

    table = DataTable("categories")
    table.Columns.Add("Include", clr.GetClrType(Boolean))
    table.Columns.Add("Category", clr.GetClrType(String))
    table.Columns.Add("Reattach", clr.GetClrType(Int32))
    table.Columns.Add("Delete", clr.GetClrType(Int32))
    table.Columns.Add("Skipped", clr.GetClrType(Int32))
    table.Columns.Add("Views", clr.GetClrType(Int32))
    for name in sorted(cats):
        c = cats[name]
        row = table.NewRow()
        row["Include"] = (c[REATTACH] + c[DELETE]) > 0
        row["Category"] = name
        row["Reattach"] = c[REATTACH]
        row["Delete"] = c[DELETE]
        row["Skipped"] = c[SKIP]
        row["Views"] = len(c["views"])
        table.Rows.Add(row)
    data_view = table.DefaultView
    data_view.Sort = "Category ASC"
    find("CatList").ItemsSource = data_view

    reasons = {}
    for r in records:
        if r.action == SKIP:
            reasons[r.reason] = reasons.get(r.reason, 0) + 1
    if reasons:
        parts = [u"{} {}".format(v, k) for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])]
        find("SkipInfo").Text = u"Skipped: " + u"  \u00B7  ".join(parts)
    else:
        find("SkipInfo").Visibility = Visibility.Collapsed

    state = {"go": False, "mode": "move", "cats": set()}

    def set_mode(mode):
        state["mode"] = mode
        find("ModeMove").IsChecked = (mode == "move")
        find("ModeKeep").IsChecked = (mode == "keep")

    def on_mode_move(sender, args):
        set_mode("move")

    def on_mode_keep(sender, args):
        set_mode("keep")

    def on_search(sender, args):
        txt = find("SearchBox").Text or ""
        find("SearchHint").Visibility = Visibility.Collapsed if txt else Visibility.Visible
        if txt.strip():
            data_view.RowFilter = "Category LIKE '%{}%'".format(escape_like(txt.strip()))
        else:
            data_view.RowFilter = ""

    def on_copy(sender, args):
        try:
            Clipboard.SetText(build_report(records))
            find("CopyBtn").Content = u"Copied \u2713"
        except Exception:
            find("CopyBtn").Content = "Copy failed"

    def on_fix(sender, args):
        picked = set()
        for row in table.Rows:
            if row["Include"] is True:
                picked.add(str(row["Category"]))
        state["cats"] = picked
        state["go"] = True
        win.Close()

    def on_cancel(sender, args):
        win.Close()

    find("ModeMove").Click += RoutedEventHandler(on_mode_move)
    find("ModeKeep").Click += RoutedEventHandler(on_mode_keep)
    find("SearchBox").TextChanged += TextChangedEventHandler(on_search)
    find("CopyBtn").Click += RoutedEventHandler(on_copy)
    find("FixBtn").Click += RoutedEventHandler(on_fix)
    find("CancelBtn").Click += RoutedEventHandler(on_cancel)
    set_mode("move")

    frame = DispatcherFrame()

    def on_closed(sender, args):
        frame.Continue = False

    win.Closed += EventHandler(on_closed)
    win.Show()
    Dispatcher.PushFrame(frame)

    return state if state["go"] else None


# ---------------------------------------------------------------------------
# Fixing
# ---------------------------------------------------------------------------
def rollback_if_open(st):
    try:
        if st.GetStatus() == TransactionStatus.Started:
            st.RollBack()
    except Exception:
        pass


def delete_tag(tag):
    try:
        doc.Delete(tag.Id)
        return True, None
    except Exception as ex:
        return False, short_error(ex)


def reattach_independent(tag, targets, mode):
    st = SubTransaction(doc)
    st.Start()
    try:
        refs = []
        for el, inst in targets:
            ref = Reference(el)
            if inst is not None:
                ref = ref.CreateLinkReference(inst)
            refs.append(ref)

        if mode == "move":
            head = element_point(targets[0][0], targets[0][1])
            leader = False
            if head is None:
                head = tag.TagHeadPosition
                leader = True
        else:
            head = tag.TagHeadPosition
            leader = True

        orientation = tag.TagOrientation
        new_tag = IndependentTag.Create(doc, tag.GetTypeId(), tag.OwnerViewId,
                                        refs[0], leader, orientation, head)
        if len(refs) > 1:
            try:
                new_tag.AddReferences(List[Reference](refs[1:]))
            except Exception:
                pass
        any_dir = getattr(TagOrientation, "AnyModelDirection", None)
        if any_dir is not None and orientation == any_dir:
            try:
                new_tag.RotationAngle = tag.RotationAngle
            except Exception:
                pass

        doc.Regenerate()
        if new_tag.IsOrphaned:
            st.RollBack()
            return False, "Element is not visible in the tag's view"

        doc.Delete(tag.Id)
        st.Commit()
        return True, None
    except Exception as ex:
        rollback_if_open(st)
        return False, short_error(ex)


def recreate_spatial(tag, el, inst, pt, view):
    uv = UV(pt.X, pt.Y)
    if isinstance(tag, RoomTag):
        if inst is not None:
            leid = LinkElementId(inst.Id, el.Id)
        else:
            leid = LinkElementId(el.Id)
        new_tag = doc.Create.NewRoomTag(leid, uv, view.Id)
    elif isinstance(tag, SpaceTag):
        new_tag = doc.Create.NewSpaceTag(el, uv, view)
    else:
        new_tag = doc.Create.NewAreaTag(view, el, uv)
    if new_tag is not None and new_tag.GetTypeId() != tag.GetTypeId():
        new_tag.ChangeTypeId(tag.GetTypeId())
    return new_tag


def spatial_still_broken(tag):
    try:
        if tag.IsOrphaned:
            return True
        if isinstance(tag, RoomTag) and not tag.HasLeader and not tag.IsInRoom:
            return True
    except Exception:
        return True
    return False


def reattach_spatial(tag, targets):
    el, inst = targets[0]
    label = spatial_label(tag)
    st = SubTransaction(doc)
    st.Start()
    try:
        pt = element_point(el, inst)
        if pt is None:
            st.RollBack()
            return False, "{} has no location".format(label)

        if tag.IsOrphaned:
            new_tag = recreate_spatial(tag, el, inst, pt, get_view(tag.OwnerViewId))
            if new_tag is None:
                st.RollBack()
                return False, "Revit could not create the tag"
            doc.Delete(tag.Id)
            check = new_tag
        else:
            cur = tag.Location.Point
            vec = XYZ(pt.X - cur.X, pt.Y - cur.Y, 0.0)
            if not vec.IsZeroLength():
                ElementTransformUtils.MoveElement(doc, tag.Id, vec)
            check = tag

        doc.Regenerate()
        if spatial_still_broken(check):
            st.RollBack()
            return False, "{} is not shown in the tag's view".format(label)
        st.Commit()
        return True, None
    except Exception as ex:
        rollback_if_open(st)
        return False, short_error(ex)


def run_fix(todo, mode):
    results = {}
    failures = []
    t = Transaction(doc, "Fix Orphaned Tags")
    t.Start()
    try:
        with forms.ProgressBar(title="Fixing tags ({value} of {max_value})") as pb:
            for i, rec in enumerate(todo):
                pb.update_progress(i + 1, len(todo))
                res = results.setdefault(rec.category, {REATTACH: 0, DELETE: 0, "failed": 0})
                tag = doc.GetElement(rec.tag_id)
                if tag is None:
                    continue
                if rec.action == DELETE:
                    ok, why = delete_tag(tag)
                elif rec.kind == KIND_INDEPENDENT:
                    ok, why = reattach_independent(tag, rec.targets, mode)
                else:
                    ok, why = reattach_spatial(tag, rec.targets)
                if ok:
                    res[rec.action] += 1
                else:
                    res["failed"] += 1
                    failures.append((rec, why))
        status = t.Commit()
        if status != TransactionStatus.Committed:
            forms.alert("Revit did not commit the changes (status: {}). Nothing was changed.".format(status),
                        title=TITLE)
            return None, None
    except Exception as ex:
        if t.GetStatus() == TransactionStatus.Started:
            t.RollBack()
        forms.alert("The fix failed and was rolled back. Nothing was changed.\n\n{}".format(short_error(ex)),
                    title=TITLE)
        return None, None
    return results, failures


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def print_leftovers(records, failures):
    left = [(r, r.reason) for r in records if r.action == SKIP] + failures
    if not left:
        return 0
    output = script.get_output()
    output.set_title(TITLE)
    output.print_md("## Tags left for manual review")
    by_cat = {}
    for rec, why in left:
        by_cat.setdefault(rec.category, []).append((rec, why))
    for cat in sorted(by_cat):
        rows = []
        for rec, why in sorted(by_cat[cat], key=lambda x: x[0].view_name):
            rows.append([output.linkify(rec.tag_id), rec.view_name, why])
        output.print_table(table_data=rows, columns=["Tag", "View", "Reason"], title=cat)
    return len(left)


def show_results(results, leftovers):
    tot_re = sum(v[REATTACH] for v in results.values())
    tot_del = sum(v[DELETE] for v in results.values())
    tot_fail = sum(v["failed"] for v in results.values())
    lines = []
    for cat in sorted(results):
        v = results[cat]
        line = u"{}: {} re-attached, {} deleted".format(cat, v[REATTACH], v[DELETE])
        if v["failed"]:
            line += u", {} failed".format(v["failed"])
        lines.append(line)
    td = TaskDialog(TITLE)
    td.MainInstruction = u"{} re-attached  \u00B7  {} deleted  \u00B7  {} failed".format(tot_re, tot_del, tot_fail)
    content = u"\n".join(lines)
    if leftovers:
        content += u"\n\nSkipped and failed tags are listed in the pyRevit output window (click an Id to zoom to it)."
    td.MainContent = content
    td.Show()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if doc.IsFamilyDocument:
    forms.alert("Run this in a project document, not a family.", title=TITLE, exitscript=True)

records = collect_orphans()
if records is None:
    script.exit()
if not records:
    forms.alert("No orphaned tags found in this document.", title=TITLE, exitscript=True)

choice = show_summary(records)
if choice is None:
    script.exit()

todo = [r for r in records if r.category in choice["cats"] and r.action != SKIP]
if not todo:
    forms.alert("Nothing to fix in the selected categories.", title=TITLE, exitscript=True)

results, failures = run_fix(todo, choice["mode"])
if results is None:
    script.exit()

leftover_count = print_leftovers(records, failures)
show_results(results, leftover_count)
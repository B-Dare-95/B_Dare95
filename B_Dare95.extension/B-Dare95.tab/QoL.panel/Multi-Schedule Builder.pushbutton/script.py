# -*- coding: utf-8 -*-
__doc__ = """__________________________________________________
Description:

Builds Revit schedules for several categories in one window. Check the categories, and for each one pick its fields and their order, filter rules, sorting and grouping, itemizing and totals, then create all the schedules at once.
The preview shows the real schedule Revit will make. Elements in linked models can be included per category, and each category's setup is remembered for next time.
__________________________________________________
How-to:

-> Click on the button
-> Check the categories you want schedules for; click a name to set it up
-> Fields: add, remove and order the columns; the sum button adds totals to a number column
-> Filter: keep only the elements that pass your rules
-> Sorting / grouping: sort levels with headers, footers and blank lines, itemize on or off, grand totals
-> Check the Preview, then click Create schedules
__________________________________________________
Author: Mohamed Bedair"""

import json
import re

import clr
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from System import EventHandler, Enum, Guid
from System.Windows import (RoutedEventHandler, Thickness, CornerRadius,
                            TextTrimming, VerticalAlignment, Visibility, FontWeights)
from System.Windows.Markup import XamlReader
from System.Windows.Controls import (Border, CheckBox, ComboBox, ComboBoxItem,
                                     DockPanel, Dock, StackPanel, TextBlock,
                                     Orientation, Button, TextChangedEventHandler,
                                     SelectionChangedEventHandler)
from System.Windows.Controls.Primitives import ToggleButton
from System.Windows.Input import MouseButtonEventHandler
from System.Windows.Media import SolidColorBrush, ColorConverter, Brushes
from System.Windows.Threading import Dispatcher, DispatcherFrame
from System.Windows.Interop import WindowInteropHelper

from Autodesk.Revit.DB import (FilteredElementCollector, BuiltInParameter,
                               StorageType, Transaction, ViewSchedule,
                               ScheduleFieldType, ScheduleFieldDisplayType,
                               ScheduleFilter, ScheduleFilterType,
                               ScheduleSortGroupField, ScheduleSortOrder,
                               SectionType, UnitUtils)
from Autodesk.Revit.UI import TaskDialog, TaskDialogCommonButtons

from pyrevit import revit, script, forms

from bd_combo_search import enable_combo_search

doc = revit.doc
uidoc = revit.uidoc
cfg = script.get_config()

TITLE = "Schedule Builder"
MAX_SORTS = 4
MAX_FILTERS = 8
MAX_SAMPLE = 3000       # elements read for value lists and number detection
MAX_VALUES = 300        # values offered in a filter's value list
MAX_PREVIEW_ROWS = 150

# shown name -> ScheduleFilterType member
OPERATORS = [
    (u"equals", "Equal"),
    (u"does not equal", "NotEqual"),
    (u"is greater than", "GreaterThan"),
    (u"is greater than or equal to", "GreaterThanOrEqual"),
    (u"is less than", "LessThan"),
    (u"is less than or equal to", "LessThanOrEqual"),
    (u"contains", "Contains"),
    (u"does not contain", "NotContains"),
    (u"begins with", "BeginsWith"),
    (u"does not begin with", "NotBeginsWith"),
    (u"ends with", "EndsWith"),
    (u"does not end with", "NotEndsWith"),
    (u"has a value", "HasValue"),
    (u"has no value", "HasNoValue"),
]
NO_VALUE_OPS = (u"has a value", u"has no value")
DEFAULT_FIELDS = (u"Level", u"Family", u"Type", u"Count")
DEFAULT_SORTS = (u"Level", u"Family", u"Type")

BG, CARD, SURFACE, MUTED = "#161616", "#262626", "#393939", "#525252"
TEXT, SUB, HINT, ACCENT = "#F4F4F4", "#A8A8A8", "#6F6F6F", "#F1C21B"
ERROR, OK_GREEN = "#FA4D56", "#A7F0BA"


# ---------------------------------------------------------------- helpers
def id_val(eid):
    try:
        return eid.Value
    except AttributeError:
        return eid.IntegerValue


_brushes = {}


def brush(hexs):
    if hexs not in _brushes:
        _brushes[hexs] = SolidColorBrush(ColorConverter.ConvertFromString(hexs))
    return _brushes[hexs]


DARK_TEXT = SolidColorBrush(ColorConverter.ConvertFromString("#141414"))


def natural_key(text):
    return [(0, int(t), u"") if t.isdigit() else (1, 0, t.lower())
            for t in re.split(r"(\d+)", u"{}".format(text)) if t]


def is_yes_no(p):
    try:
        from Autodesk.Revit.DB import SpecTypeId
        return p.Definition.GetDataType() == SpecTypeId.Boolean.YesNo
    except Exception:
        return False


# ------------------------------------------------------------- categories
def collect_categories():
    """{cat id int: {...}} of schedulable categories that hold elements."""
    counts, cats = {}, {}
    for e in FilteredElementCollector(doc).WhereElementIsNotElementType():
        c = e.Category
        if c is None or c.Parent is not None:
            continue
        k = id_val(c.Id)
        counts[k] = counts.get(k, 0) + 1
        if k not in cats:
            cats[k] = c
    out = {}
    for k, c in cats.items():
        try:
            if not ViewSchedule.IsValidCategoryForSchedule(c.Id):
                continue
        except Exception:
            continue
        out[k] = {"key": k, "name": c.Name, "cat_id": c.Id, "count": counts[k],
                  "fields": None, "error": None, "elements": None, "info": {}}
    return out


def field_key(sf):
    return (int(sf.FieldType), int(id_val(sf.ParameterId)))


def load_fields(cat):
    """Read the category's schedulable fields through a throwaway schedule."""
    if cat["fields"] is not None or cat["error"]:
        return
    t = Transaction(doc, "Read schedulable fields")
    t.Start()
    try:
        sched = ViewSchedule.CreateSchedule(doc, cat["cat_id"])
        fields, names = [], {}
        count_key = (int(ScheduleFieldType.Count), -1)
        has_count = False
        for sf in sched.Definition.GetSchedulableFields():
            ft = sf.FieldType
            name = sf.GetName(doc)
            k = field_key(sf)
            if ft == ScheduleFieldType.Count:
                has_count = True
                count_key = k
            fields.append({"key": k, "name": name, "label": name,
                           "is_type": ft == ScheduleFieldType.ElementType,
                           "is_count": ft == ScheduleFieldType.Count,
                           "readable": ft in (ScheduleFieldType.Instance,
                                              ScheduleFieldType.ElementType)})
            names[name] = names.get(name, 0) + 1
        if not has_count:
            fields.append({"key": count_key, "name": u"Count", "label": u"Count",
                           "is_type": False, "is_count": True, "readable": False})
        for f in fields:
            if names.get(f["name"], 0) > 1 and f["is_type"]:
                f["label"] = f["name"] + u" (type)"
        fields.sort(key=lambda f: natural_key(f["label"]))
        cat["fields"] = fields
        cat["by_key"] = dict((f["key"], f) for f in fields)
    except Exception as ex:
        cat["error"] = u"{}".format(ex)
    finally:
        t.RollBack()


def category_elements(cat):
    if cat["elements"] is None:
        out = []
        for e in FilteredElementCollector(doc).OfCategoryId(cat["cat_id"]) \
                .WhereElementIsNotElementType():
            out.append(e)
            if len(out) >= MAX_SAMPLE:
                break
        cat["elements"] = out
    return cat["elements"]


def param_of(e, field):
    target = e
    if field["is_type"]:
        tid = e.GetTypeId()
        target = doc.GetElement(tid) if tid is not None and id_val(tid) > 0 else None
    if target is None:
        return None
    pid = field["key"][1]
    if pid < 0:
        try:
            return target.get_Parameter(Enum.ToObject(clr.GetClrType(BuiltInParameter), pid))
        except Exception:
            return None
    for p in target.Parameters:
        if id_val(p.Id) == pid:
            return p
    return None


def field_info(cat, key):
    """{'storage', 'unit', 'numeric', 'values': {text: raw}} read from the
    category's elements (cached)."""
    if key in cat["info"]:
        return cat["info"][key]
    info = {"storage": None, "unit": None, "numeric": False, "values": {}}
    field = cat["by_key"].get(key)
    if field is not None and field["is_count"]:
        info["numeric"] = True
    elif field is not None and field["readable"]:
        for e in category_elements(cat):
            p = param_of(e, field)
            if p is None or not p.HasValue:
                continue
            st = p.StorageType
            if info["storage"] is None:
                info["storage"] = st
                if st == StorageType.Double:
                    info["numeric"] = True
                    try:
                        info["unit"] = p.GetUnitTypeId()
                    except Exception:
                        pass
                elif st == StorageType.Integer and not is_yes_no(p):
                    info["numeric"] = True
            if len(info["values"]) >= MAX_VALUES:
                continue
            try:
                if st == StorageType.String:
                    raw = p.AsString()
                    text = raw
                elif st == StorageType.Double:
                    raw = p.AsDouble()
                    text = p.AsValueString()
                elif st == StorageType.Integer:
                    raw = p.AsInteger()
                    text = p.AsValueString() or u"{}".format(raw)
                elif st == StorageType.ElementId:
                    raw = p.AsElementId()
                    text = p.AsValueString()
                else:
                    continue
            except Exception:
                continue
            if text:
                info["values"].setdefault(text, raw)
    cat["info"][key] = info
    return info


# --------------------------------------------------------------- setups
def load_saved():
    try:
        return json.loads(cfg.get_option("setups", "{}") or "{}")
    except Exception:
        return {}


def save_setups(cats, setups):
    saved = load_saved()
    for k, s in setups.items():
        cat = cats[k]
        if cat["fields"] is None:
            continue
        saved[cat["name"]] = {
            "fields": [list(f) for f in s["fields"]],
            "totals": [list(f) for f in s["totals"]],
            "filters": [{"key": list(r["key"]), "op": r["op"], "value": r["value"]}
                        for r in s["filters"]],
            "sorts": [{"key": list(o["key"]), "desc": o["desc"], "h": o["h"],
                       "ft": o["ft"], "b": o["b"]} for o in s["sorts"] if o["key"]],
            "itemize": s["itemize"], "grand": s["grand"], "links": s["links"]}
    try:
        cfg.set_option("setups", json.dumps(saved))
        script.save_config()
    except Exception:
        pass


def default_setup(cat, saved):
    s = {"on": False, "name": u"{} Schedule".format(cat["name"]), "links": False,
         "fields": [], "totals": set(), "filters": [], "sorts": [],
         "itemize": False, "grand": True}
    if cat["fields"] is None:
        return s
    keys = cat["by_key"]
    old = saved.get(cat["name"])
    if old:
        tup = lambda v: tuple(v)
        s["fields"] = [tup(f) for f in old.get("fields", []) if tup(f) in keys]
        s["totals"] = set(tup(f) for f in old.get("totals", []) if tup(f) in keys)
        s["filters"] = [{"key": tup(r["key"]), "op": r["op"], "value": r.get("value", u"")}
                        for r in old.get("filters", []) if tup(r["key"]) in keys]
        s["sorts"] = [{"key": tup(o["key"]), "desc": o["desc"], "h": o["h"], "ft": o["ft"],
                       "b": o["b"]} for o in old.get("sorts", [])
                      if tup(o["key"]) in s["fields"]]
        s["itemize"] = old.get("itemize", False)
        s["grand"] = old.get("grand", True)
        s["links"] = old.get("links", False)
        if s["fields"]:
            return s
    by_name = {}
    for f in cat["fields"]:          # instance fields first, then type fields
        if not f["is_type"]:
            by_name.setdefault(f["name"], f["key"])
    for f in cat["fields"]:
        if f["is_type"]:
            by_name.setdefault(f["name"], f["key"])
    s["fields"] = [by_name[n] for n in DEFAULT_FIELDS if n in by_name]
    for n in DEFAULT_SORTS:
        if n in by_name and by_name[n] in s["fields"]:
            first = not s["sorts"]
            s["sorts"].append({"key": by_name[n], "desc": False, "h": first,
                               "ft": first, "b": False})
    return s


# ------------------------------------------------------------- building
def make_filter(cat, field_id, rule, notes, label):
    op = rule["op"]
    member = dict(OPERATORS).get(op)
    ftype = getattr(ScheduleFilterType, member)
    if op in NO_VALUE_OPS:
        return ScheduleFilter(field_id, ftype)
    text = u"{}".format(rule["value"] or u"").strip()
    info = field_info(cat, rule["key"])
    if text in info["values"]:
        raw = info["values"][text]
    else:
        st = info["storage"]
        try:
            if st == StorageType.Double:
                v = float(text.replace(u",", u".").split()[0])
                raw = UnitUtils.ConvertToInternalUnits(v, info["unit"]) if info["unit"] else v
            elif st == StorageType.Integer:
                raw = int(float(text.replace(u",", u".").split()[0]))
            elif st == StorageType.ElementId:
                notes.append(u"{}: rule on {} skipped - pick its value from the list".format(
                    cat["name"], label))
                return None
            else:
                raw = text
        except Exception:
            notes.append(u"{}: rule on {} skipped - '{}' is not a number".format(
                cat["name"], label, text))
            return None
    if isinstance(raw, bool):
        raw = int(raw)
    return ScheduleFilter(field_id, ftype, raw)


def build_schedule(cat, s, name, notes):
    """Create the schedule (call inside a transaction). Returns the schedule."""
    sched = ViewSchedule.CreateSchedule(doc, cat["cat_id"])
    try:
        sched.Name = name
    except Exception:
        notes.append(u"{}: name '{}' refused - Revit's name kept".format(cat["name"], name))
    d = sched.Definition
    available = {}
    for sf in d.GetSchedulableFields():
        available[field_key(sf)] = sf
    added = {}

    def add(key, hidden=False):
        sf = available.get(key)
        if sf is not None:
            f = d.AddField(sf)
        elif key[0] == int(ScheduleFieldType.Count):
            f = d.AddField(ScheduleFieldType.Count)
        else:
            return None
        if hidden:
            f.IsHidden = True
        added[key] = f
        return f

    for key in s["fields"]:
        label = cat["by_key"][key]["label"] if key in cat["by_key"] else u"?"
        f = add(key)
        if f is None:
            notes.append(u"{}: field {} is no longer available".format(cat["name"], label))
            continue
        if key in s["totals"]:
            try:
                if f.CanTotal():
                    f.DisplayType = ScheduleFieldDisplayType.Totals
                else:
                    notes.append(u"{}: {} can't be totalled".format(cat["name"], label))
            except Exception:
                notes.append(u"{}: totals not set on {}".format(cat["name"], label))

    for rule in s["filters"]:
        label = cat["by_key"][rule["key"]]["label"] if rule["key"] in cat["by_key"] else u"?"
        f = added.get(rule["key"]) or add(rule["key"], hidden=True)
        if f is None:
            continue
        try:
            filt = make_filter(cat, f.FieldId, rule, notes, label)
            if filt is not None:
                d.AddFilter(filt)
        except Exception as ex:
            notes.append(u"{}: rule '{} {}' refused by Revit ({})".format(
                cat["name"], label, rule["op"], ex))

    for o in s["sorts"]:
        f = added.get(o["key"])
        if f is None:
            continue
        g = ScheduleSortGroupField(f.FieldId, ScheduleSortOrder.Descending if o["desc"]
                                   else ScheduleSortOrder.Ascending)
        g.ShowHeader = bool(o["h"])
        g.ShowFooter = bool(o["ft"])
        if o["ft"]:
            g.ShowFooterTitle = True
            g.ShowFooterCount = True
        g.ShowBlankLine = bool(o["b"])
        d.AddSortGroupField(g)

    d.IsItemized = bool(s["itemize"])
    d.ShowGrandTotal = bool(s["grand"])
    if s["grand"]:
        d.ShowGrandTotalTitle = True
        d.ShowGrandTotalCount = True
    if s["links"]:
        try:
            d.IncludeLinkedFiles = True
        except Exception:
            notes.append(u"{}: elements in linked models can't be included".format(cat["name"]))
    return sched


def unique_name(name, taken):
    base = name.strip() or u"Schedule"
    out, n = base, 2
    while out.lower() in taken:
        out = u"{} ({})".format(base, n)
        n += 1
    taken.add(out.lower())
    return out


def existing_names():
    return set(v.Name.lower() for v in FilteredElementCollector(doc).OfClass(ViewSchedule))


def preview_table(cat, s):
    """(rows of cell texts, notes) of the schedule Revit would make - built in a
    transaction that is rolled back."""
    notes = []
    rows = []
    t = Transaction(doc, "Preview schedule")
    t.Start()
    try:
        sched = build_schedule(cat, s, u"BD preview {}".format(Guid.NewGuid()), notes)
        doc.Regenerate()
        body = sched.GetTableData().GetSectionData(SectionType.Body)
        nr, nc = body.NumberOfRows, body.NumberOfColumns
        for r in range(min(nr, MAX_PREVIEW_ROWS)):
            rows.append([sched.GetCellText(SectionType.Body, r, c) for c in range(nc)])
        if nr > MAX_PREVIEW_ROWS:
            notes.append(u"Showing the first {} of {} rows".format(MAX_PREVIEW_ROWS, nr))
    finally:
        t.RollBack()
    return rows, notes


# ------------------------------------------------------------------ UI
XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Schedule Builder" Width="1060" Height="740" MinWidth="900" MinHeight="560"
        ResizeMode="CanResizeWithGrip" WindowStartupLocation="CenterScreen"
        Background="#161616" FontFamily="Segoe UI" FontSize="12">
  <Window.Resources>
    <Style x:Key="Btn" TargetType="Button">
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Height" Value="30"/>
      <Setter Property="Padding" Value="12,0"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="bd" Background="{TemplateBinding Background}"
                    CornerRadius="6" Padding="{TemplateBinding Padding}">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="bd" Property="Background" Value="#525252"/>
              </Trigger>
              <Trigger Property="IsEnabled" Value="False">
                <Setter Property="Opacity" Value="0.4"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style x:Key="AccentBtn" TargetType="Button">
      <Setter Property="Background" Value="#F1C21B"/>
      <Setter Property="Foreground" Value="#161616"/>
      <Setter Property="Height" Value="30"/>
      <Setter Property="Padding" Value="12,0"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="bd" Background="{TemplateBinding Background}"
                    CornerRadius="6" Padding="{TemplateBinding Padding}">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="bd" Property="Background" Value="#F4D35E"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style x:Key="Tgl" TargetType="ToggleButton">
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Height" Value="30"/>
      <Setter Property="Padding" Value="10,0"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ToggleButton">
            <Border x:Name="bd" Background="{TemplateBinding Background}"
                    CornerRadius="6" Padding="{TemplateBinding Padding}">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="bd" Property="Background" Value="#525252"/>
              </Trigger>
              <Trigger Property="IsChecked" Value="True">
                <Setter TargetName="bd" Property="Background" Value="#F1C21B"/>
                <Setter Property="Foreground" Value="#161616"/>
              </Trigger>
              <Trigger Property="IsEnabled" Value="False">
                <Setter Property="Opacity" Value="0.4"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style TargetType="TextBox">
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="BorderBrush" Value="#525252"/>
      <Setter Property="BorderThickness" Value="1"/>
      <Setter Property="CaretBrush" Value="#F4F4F4"/>
      <Setter Property="Height" Value="30"/>
      <Setter Property="Padding" Value="6,0"/>
      <Setter Property="VerticalContentAlignment" Value="Center"/>
    </Style>
    <Style TargetType="CheckBox">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="VerticalContentAlignment" Value="Center"/>
      <Setter Property="Cursor" Value="Hand"/>
    </Style>
    <Style x:Key="Sub" TargetType="TextBlock">
      <Setter Property="Foreground" Value="#A8A8A8"/>
    </Style>
    <Style x:Key="Hint" TargetType="TextBlock">
      <Setter Property="Foreground" Value="#6F6F6F"/>
      <Setter Property="FontSize" Value="11"/>
      <Setter Property="TextWrapping" Value="Wrap"/>
    </Style>
    <Style x:Key="Row" TargetType="Border">
      <Setter Property="Background" Value="Transparent"/>
      <Setter Property="CornerRadius" Value="4"/>
      <Setter Property="Padding" Value="6,4"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Style.Triggers>
        <Trigger Property="IsMouseOver" Value="True">
          <Setter Property="Background" Value="#393939"/>
        </Trigger>
      </Style.Triggers>
    </Style>
  </Window.Resources>

  <Grid Margin="12">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <StackPanel Grid.Row="0" Margin="0,0,0,10">
      <TextBlock Text="Schedule Builder" Foreground="#F4F4F4" FontSize="18" FontWeight="SemiBold"/>
      <TextBlock Text="Check the categories, set each one up, and create all the schedules in one go"
                 Style="{StaticResource Sub}" Margin="0,2,0,0"/>
    </StackPanel>

    <Grid Grid.Row="1">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="270"/>
        <ColumnDefinition Width="10"/>
        <ColumnDefinition Width="*"/>
      </Grid.ColumnDefinitions>

      <Border Grid.Column="0" Background="#262626" CornerRadius="8" Padding="12">
        <DockPanel>
          <TextBlock DockPanel.Dock="Top" Text="Categories" Style="{StaticResource Sub}" Margin="0,0,0,8"/>
          <Grid DockPanel.Dock="Top">
            <TextBox x:Name="txtCatSearch"/>
            <TextBlock x:Name="txtCatHint" Text="Search categories" Foreground="#6F6F6F"
                       Margin="9,0,0,0" VerticalAlignment="Center" IsHitTestVisible="False"/>
          </Grid>
          <DockPanel DockPanel.Dock="Top" Margin="0,6,0,4">
            <StackPanel DockPanel.Dock="Right" Orientation="Horizontal">
              <Button x:Name="btnCatAll" Content="All" Style="{StaticResource Btn}" Height="24" Margin="0,0,4,0"/>
              <Button x:Name="btnCatNone" Content="None" Style="{StaticResource Btn}" Height="24"/>
            </StackPanel>
            <TextBlock x:Name="txtCatCount" Style="{StaticResource Sub}" VerticalAlignment="Center"/>
          </DockPanel>
          <TextBlock DockPanel.Dock="Bottom" Style="{StaticResource Hint}" Margin="0,6,0,0"
                     Text="Check = create its schedule. Click a name to set it up."/>
          <Border Background="#161616" CornerRadius="6">
            <ScrollViewer VerticalScrollBarVisibility="Auto">
              <StackPanel x:Name="spCats" Margin="4"/>
            </ScrollViewer>
          </Border>
        </DockPanel>
      </Border>

      <Border Grid.Column="2" Background="#262626" CornerRadius="8" Padding="12">
        <DockPanel>
          <DockPanel DockPanel.Dock="Top" Margin="0,0,0,8">
            <TextBlock x:Name="tbCat" Foreground="#F4F4F4" FontSize="15" FontWeight="SemiBold"
                       VerticalAlignment="Center"/>
            <TextBlock x:Name="tbCatCount" Style="{StaticResource Sub}" VerticalAlignment="Center" Margin="10,0,0,0"/>
          </DockPanel>
          <Grid DockPanel.Dock="Top" Margin="0,0,0,10">
            <Grid.ColumnDefinitions>
              <ColumnDefinition Width="Auto"/>
              <ColumnDefinition Width="*"/>
              <ColumnDefinition Width="Auto"/>
            </Grid.ColumnDefinitions>
            <TextBlock Grid.Column="0" Text="Schedule name" Style="{StaticResource Sub}"
                       VerticalAlignment="Center" Margin="0,0,8,0"/>
            <TextBox Grid.Column="1" x:Name="txtName"/>
            <CheckBox Grid.Column="2" x:Name="chkLinks" Content="Include elements in linked models"
                      Margin="12,0,0,0"/>
          </Grid>
          <StackPanel DockPanel.Dock="Top" Orientation="Horizontal" Margin="0,0,0,10">
            <ToggleButton x:Name="tabFields" Content="Fields" Style="{StaticResource Tgl}" Margin="0,0,6,0"/>
            <ToggleButton x:Name="tabFilter" Content="Filter" Style="{StaticResource Tgl}" Margin="0,0,6,0"/>
            <ToggleButton x:Name="tabSort" Content="Sorting / grouping" Style="{StaticResource Tgl}" Margin="0,0,6,0"/>
            <ToggleButton x:Name="tabPreview" Content="Preview" Style="{StaticResource Tgl}"/>
          </StackPanel>

          <Grid>
            <TextBlock x:Name="tbCatError" Foreground="#FA4D56" TextWrapping="Wrap" Visibility="Collapsed"/>

            <Grid x:Name="pnlFields">
              <Grid.ColumnDefinitions>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="48"/>
                <ColumnDefinition Width="*"/>
              </Grid.ColumnDefinitions>
              <Grid.RowDefinitions>
                <RowDefinition Height="*"/>
                <RowDefinition Height="Auto"/>
              </Grid.RowDefinitions>
              <DockPanel Grid.Column="0">
                <TextBlock DockPanel.Dock="Top" Text="Available fields" Style="{StaticResource Sub}" Margin="0,0,0,4"/>
                <Grid DockPanel.Dock="Top" Margin="0,0,0,4">
                  <TextBox x:Name="txtFieldSearch"/>
                  <TextBlock x:Name="txtFieldHint" Text="Search fields" Foreground="#6F6F6F"
                             Margin="9,0,0,0" VerticalAlignment="Center" IsHitTestVisible="False"/>
                </Grid>
                <Border Background="#161616" CornerRadius="6">
                  <ScrollViewer VerticalScrollBarVisibility="Auto">
                    <StackPanel x:Name="spAvail" Margin="4"/>
                  </ScrollViewer>
                </Border>
              </DockPanel>
              <StackPanel Grid.Column="1" VerticalAlignment="Center" Margin="6,0">
                <Button x:Name="btnAdd" Content="&#x2192;" Style="{StaticResource Btn}" Padding="0" Margin="0,0,0,6" ToolTip="Add the field"/>
                <Button x:Name="btnRemove" Content="&#x2190;" Style="{StaticResource Btn}" Padding="0" Margin="0,0,0,16" ToolTip="Remove the field"/>
                <Button x:Name="btnUp" Content="&#x2191;" Style="{StaticResource Btn}" Padding="0" Margin="0,0,0,6" ToolTip="Move up"/>
                <Button x:Name="btnDown" Content="&#x2193;" Style="{StaticResource Btn}" Padding="0" ToolTip="Move down"/>
              </StackPanel>
              <DockPanel Grid.Column="2">
                <DockPanel DockPanel.Dock="Top" Margin="0,0,0,4">
                  <TextBlock DockPanel.Dock="Right" Text="&#x03A3; = calculate totals" Style="{StaticResource Hint}" VerticalAlignment="Center"/>
                  <TextBlock Text="Scheduled fields (in order)" Style="{StaticResource Sub}"/>
                </DockPanel>
                <Border Background="#161616" CornerRadius="6" Margin="0,34,0,0">
                  <ScrollViewer VerticalScrollBarVisibility="Auto">
                    <StackPanel x:Name="spSched" Margin="4"/>
                  </ScrollViewer>
                </Border>
              </DockPanel>
              <TextBlock Grid.Row="1" Grid.ColumnSpan="3" Style="{StaticResource Hint}" Margin="0,6,0,0"
                         Text="Double-click a field to add or remove it. &#x03A3; shows on number fields: it adds the column's total to group footers and the grand total."/>
            </Grid>

            <DockPanel x:Name="pnlFilter">
              <TextBlock DockPanel.Dock="Top" Style="{StaticResource Sub}" Margin="0,0,0,8"
                         Text="Keep only the elements that pass every rule (Revit joins schedule filters with And)"/>
              <TextBlock DockPanel.Dock="Bottom" Style="{StaticResource Hint}" Margin="0,8,0,0"
                         Text="A rule on a field that isn't scheduled adds it as a hidden column, as Revit needs. Pick values from the list, or type one (numbers in project units)."/>
              <StackPanel>
                <StackPanel x:Name="spFilters"/>
                <Button x:Name="btnAddRule" Content="+  Add rule" Style="{StaticResource Btn}"
                        HorizontalAlignment="Left" Margin="0,2,0,0"/>
              </StackPanel>
            </DockPanel>

            <StackPanel x:Name="pnlSort">
              <StackPanel x:Name="spSorts"/>
              <StackPanel Orientation="Horizontal" Margin="0,10,0,4">
                <CheckBox x:Name="chkItemize" Content="Itemize every instance" Margin="0,0,24,0"/>
                <CheckBox x:Name="chkGrand" Content="Grand totals"/>
              </StackPanel>
              <TextBlock Style="{StaticResource Hint}"
                         Text="Itemize off = one row per combination of the sort fields, with Count and &#x03A3; columns added up (BOQ style). Footers and grand totals show the title and count."/>
            </StackPanel>

            <DockPanel x:Name="pnlPreview">
              <DockPanel DockPanel.Dock="Top" Margin="0,0,0,8">
                <Button x:Name="btnRefresh" DockPanel.Dock="Right" Content="Refresh" Style="{StaticResource Btn}"/>
                <TextBlock x:Name="tbPreviewInfo" Style="{StaticResource Sub}" VerticalAlignment="Center" TextWrapping="Wrap"/>
              </DockPanel>
              <Border Background="#161616" CornerRadius="6">
                <ScrollViewer VerticalScrollBarVisibility="Auto" HorizontalScrollBarVisibility="Auto">
                  <StackPanel x:Name="spPreview" Margin="6"/>
                </ScrollViewer>
              </Border>
            </DockPanel>
          </Grid>
        </DockPanel>
      </Border>
    </Grid>

    <DockPanel Grid.Row="2" Margin="0,12,0,0">
      <StackPanel DockPanel.Dock="Right" Orientation="Horizontal">
        <Button x:Name="btnCancel" Content="Cancel" Style="{StaticResource Btn}" Width="90" Margin="0,0,8,0"/>
        <Button x:Name="btnCreate" Content="Create schedules" Style="{StaticResource AccentBtn}" Width="140"/>
      </StackPanel>
      <TextBlock x:Name="txtMsg" Foreground="#FA4D56" VerticalAlignment="Center" TextWrapping="Wrap"/>
    </DockPanel>
  </Grid>
</Window>
"""


def text_block(text, color=TEXT, size=12, bold=False):
    tb = TextBlock()
    tb.Text = text
    tb.Foreground = brush(color)
    tb.FontSize = size
    tb.VerticalAlignment = VerticalAlignment.Center
    tb.TextTrimming = TextTrimming.CharacterEllipsis
    if bold:
        tb.FontWeight = FontWeights.SemiBold
    return tb


def combo_item(text, tag=None):
    item = ComboBoxItem()
    item.Content = text
    item.Tag = tag
    item.Foreground = DARK_TEXT
    item.Padding = Thickness(6, 3, 6, 3)
    return item


def boxed(combo, width=None):
    """ComboBox wrapped like the other B-Dare95 dropdowns."""
    combo.Background = Brushes.Transparent
    combo.Foreground = DARK_TEXT
    combo.BorderThickness = Thickness(0)
    combo.Height = 28
    combo.FontSize = 12
    combo.Padding = Thickness(6, 0, 4, 0)
    b = Border()
    b.Background = brush(SURFACE)
    b.CornerRadius = CornerRadius(6)
    b.BorderBrush = brush(MUTED)
    b.BorderThickness = Thickness(1)
    b.Child = combo
    if width:
        b.Width = width
    return b


def tag_of(combo):
    item = combo.SelectedItem
    return item.Tag if item is not None else None


def show_ui(cats):
    w = XamlReader.Parse(XAML)
    f = w.FindName
    saved = load_saved()
    order = sorted(cats.keys(), key=lambda k: natural_key(cats[k]["name"]))
    setups = {}
    st = {"act": order[0], "tab": "fields", "sel_a": None, "sel_s": None,
          "filter_rows": [], "busy": False}
    result = {"ok": False}

    tabs = {"fields": f("tabFields"), "filter": f("tabFilter"),
            "sort": f("tabSort"), "preview": f("tabPreview")}
    panels = {"fields": f("pnlFields"), "filter": f("pnlFilter"),
              "sort": f("pnlSort"), "preview": f("pnlPreview")}
    txt_msg = f("txtMsg")

    def msg(text, ok=False):
        txt_msg.Text = text
        txt_msg.Foreground = brush(OK_GREEN if ok else ERROR)

    def setup_of(k):
        cat = cats[k]
        load_fields(cat)
        if k not in setups or (cat["fields"] is not None and setups[k].get("_bare")):
            on = setups[k]["on"] if k in setups else False
            setups[k] = default_setup(cat, saved)
            setups[k]["on"] = on
        return setups[k]

    for k in order:     # bare setups until a category is opened
        setups[k] = {"on": False, "name": u"{} Schedule".format(cats[k]["name"]),
                     "links": False, "fields": [], "totals": set(), "filters": [],
                     "sorts": [], "itemize": False, "grand": True, "_bare": True}

    def label(cat, key):
        fld = cat["by_key"].get(key)
        return fld["label"] if fld else u"?"

    # ------------------------------------------------------- categories
    def render_cats():
        q = (f("txtCatSearch").Text or u"").strip().lower()
        f("txtCatHint").Opacity = 0.0 if f("txtCatSearch").Text else 1.0
        sp = f("spCats")
        sp.Children.Clear()
        for k in order:
            cat = cats[k]
            if q and q not in cat["name"].lower():
                continue
            sp.Children.Add(cat_row(k))
        n = len([k for k in order if setups[k]["on"]])
        f("txtCatCount").Text = u"{} of {} checked".format(n, len(order))

    def cat_row(k):
        cat, s = cats[k], setups[k]
        row = Border()
        row.Style = w.FindResource("Row")
        if k == st["act"]:
            row.BorderBrush = brush(ACCENT)
            row.BorderThickness = Thickness(1)
        dp = DockPanel()
        cb = CheckBox()
        cb.IsChecked = s["on"]
        cb.Margin = Thickness(0, 0, 6, 0)
        DockPanel.SetDock(cb, Dock.Left)
        n_fields = u"" if s.get("_bare") else u"{}f".format(len(s["fields"]))
        right = text_block(u"{}  {}".format(cat["count"], n_fields).strip(), HINT, 11)
        right.Margin = Thickness(6, 0, 0, 0)
        DockPanel.SetDock(right, Dock.Right)
        dp.Children.Add(cb)
        dp.Children.Add(right)
        dp.Children.Add(text_block(cat["name"]))
        row.Child = dp
        row.ToolTip = u"{} elements".format(cat["count"])

        def on_tick(sender, args):
            s["on"] = bool(sender.IsChecked)
            msg(u"")
            n = len([x for x in order if setups[x]["on"]])
            f("txtCatCount").Text = u"{} of {} checked".format(n, len(order))

        def on_open(sender, args):
            sync_widgets()
            st["act"] = k
            st["sel_a"] = st["sel_s"] = None
            f("txtFieldSearch").Text = u""
            render_all()

        cb.Click += RoutedEventHandler(on_tick)
        row.MouseLeftButtonUp += MouseButtonEventHandler(on_open)
        return row

    # ----------------------------------------------------------- header
    def render_header():
        k = st["act"]
        cat, s = cats[k], setup_of(k)
        st["busy"] = True
        f("tbCat").Text = cat["name"]
        f("tbCatCount").Text = u"{} elements in this model".format(cat["count"])
        f("txtName").Text = s["name"]
        f("chkLinks").IsChecked = s["links"]
        f("chkItemize").IsChecked = s["itemize"]
        f("chkGrand").IsChecked = s["grand"]
        st["busy"] = False
        err = f("tbCatError")
        if cat["error"]:
            err.Text = u"Revit can't make a schedule for this category: {}".format(cat["error"])
            err.Visibility = Visibility.Visible
        else:
            err.Visibility = Visibility.Collapsed

    def render_tab():
        cat = cats[st["act"]]
        for name, t in tabs.items():
            t.IsChecked = (name == st["tab"])
            panels[name].Visibility = (Visibility.Visible if name == st["tab"] and not cat["error"]
                                       else Visibility.Collapsed)
        if cat["error"]:
            return
        {"fields": render_fields, "filter": render_filters,
         "sort": render_sorts, "preview": render_preview}[st["tab"]]()

    def render_all():
        render_cats()
        render_header()
        render_tab()

    # ------------------------------------------------------------ fields
    def field_row(text, selected, side_text=u"", on_click=None, on_double=None, extra=None):
        row = Border()
        row.Style = w.FindResource("Row")
        if selected:
            row.Background = brush(MUTED)
        dp = DockPanel()
        if extra is not None:
            DockPanel.SetDock(extra, Dock.Right)
            dp.Children.Add(extra)
        if side_text:
            side = text_block(side_text, HINT, 11)
            side.Margin = Thickness(6, 0, 0, 0)
            DockPanel.SetDock(side, Dock.Right)
            dp.Children.Add(side)
        dp.Children.Add(text_block(text))
        row.Child = dp

        def down(sender, args):
            if args.ClickCount == 2 and on_double is not None:
                on_double()
            elif on_click is not None:
                on_click()
        row.MouseLeftButtonDown += MouseButtonEventHandler(down)
        return row

    def render_fields():
        cat, s = cats[st["act"]], setup_of(st["act"])
        q = (f("txtFieldSearch").Text or u"").strip().lower()
        f("txtFieldHint").Opacity = 0.0 if f("txtFieldSearch").Text else 1.0
        sp_a, sp_s = f("spAvail"), f("spSched")
        sp_a.Children.Clear()
        sp_s.Children.Clear()
        for fld in cat["fields"]:
            if fld["key"] in s["fields"] or (q and q not in fld["label"].lower()):
                continue
            kind = u"type" if fld["is_type"] else (u"#" if fld["is_count"] else u"")
            sp_a.Children.Add(field_row(fld["label"], st["sel_a"] == fld["key"], kind,
                                        on_click=sel_avail(fld["key"]),
                                        on_double=add_field(fld["key"])))
        if not sp_a.Children.Count:
            sp_a.Children.Add(text_block(u"No fields left" if not q else u"No match", HINT))
        for i, key in enumerate(s["fields"]):
            extra = None
            info = field_info(cat, key)
            if info["numeric"] and not cat["by_key"].get(key, {}).get("is_count"):
                extra = ToggleButton()
                extra.Style = w.FindResource("Tgl")
                extra.Content = u"\u03A3"
                extra.Height = 22
                extra.Padding = Thickness(7, 0, 7, 0)
                extra.IsChecked = key in s["totals"]
                extra.ToolTip = u"Calculate totals"
                extra.Click += RoutedEventHandler(toggle_total(key))
            sp_s.Children.Add(field_row(u"{}.  {}".format(i + 1, label(cat, key)),
                                        st["sel_s"] == key, on_click=sel_sched(key),
                                        on_double=remove_field(key), extra=extra))
        if not s["fields"]:
            sp_s.Children.Add(text_block(u"Add at least one field", HINT))
        render_cats_light()

    def render_cats_light():
        n = len([k for k in order if setups[k]["on"]])
        f("txtCatCount").Text = u"{} of {} checked".format(n, len(order))

    def sel_avail(key):
        def h():
            st["sel_a"] = key
            render_fields()
        return h

    def sel_sched(key):
        def h():
            st["sel_s"] = key
            render_fields()
        return h

    def add_field(key):
        def h():
            s = setup_of(st["act"])
            if key not in s["fields"]:
                s["fields"].append(key)
            st["sel_a"] = None
            st["sel_s"] = key
            msg(u"")
            render_fields()
            render_cats()
        return h

    def remove_field(key):
        def h():
            s = setup_of(st["act"])
            if key in s["fields"]:
                s["fields"].remove(key)
            s["totals"].discard(key)
            s["sorts"] = [o for o in s["sorts"] if o["key"] != key]
            st["sel_s"] = None
            render_fields()
            render_cats()
        return h

    def toggle_total(key):
        def h(sender, args):
            s = setup_of(st["act"])
            if sender.IsChecked:
                s["totals"].add(key)
            else:
                s["totals"].discard(key)
        return h

    def move(step):
        s = setup_of(st["act"])
        key = st["sel_s"]
        if key not in s["fields"]:
            return
        i = s["fields"].index(key)
        j = i + step
        if 0 <= j < len(s["fields"]):
            s["fields"].pop(i)
            s["fields"].insert(j, key)
            render_fields()

    f("btnAdd").Click += RoutedEventHandler(
        lambda s_, a: add_field(st["sel_a"])() if st["sel_a"] else None)
    f("btnRemove").Click += RoutedEventHandler(
        lambda s_, a: remove_field(st["sel_s"])() if st["sel_s"] else None)
    f("btnUp").Click += RoutedEventHandler(lambda s_, a: move(-1))
    f("btnDown").Click += RoutedEventHandler(lambda s_, a: move(1))
    f("txtFieldSearch").TextChanged += TextChangedEventHandler(lambda s_, a: render_fields())

    # ----------------------------------------------------------- filters
    def sync_filters():
        """Read the filter rows' widgets back into the setup."""
        if st["act"] not in setups:
            return
        s = setups[st["act"]]
        for rule, widgets in st["filter_rows"]:
            fcombo, ocombo, vcombo = widgets
            key = tag_of(fcombo)
            if key is not None:
                rule["key"] = key
            op = tag_of(ocombo)
            if op is not None:
                rule["op"] = op
            rule["value"] = vcombo.Text or u""
        st["filter_rows"] = [x for x in st["filter_rows"] if x[0] in s["filters"]]

    def render_filters():
        cat, s = cats[st["act"]], setup_of(st["act"])
        sp = f("spFilters")
        sp.Children.Clear()
        st["filter_rows"] = []
        choices = [fld for fld in cat["fields"] if not fld["is_count"]]
        for i, rule in enumerate(s["filters"]):
            sp.Children.Add(filter_row(cat, s, rule, choices))
        if not s["filters"]:
            sp.Children.Add(text_block(u"No rules: every element is scheduled", HINT))
        f("btnAddRule").IsEnabled = len(s["filters"]) < MAX_FILTERS

    def filter_row(cat, s, rule, choices):
        g = StackPanel()
        g.Orientation = Orientation.Horizontal
        g.Margin = Thickness(0, 0, 0, 6)
        fcombo, ocombo, vcombo = ComboBox(), ComboBox(), ComboBox()
        for fld in choices:
            item = combo_item(fld["label"], fld["key"])
            fcombo.Items.Add(item)
            if fld["key"] == rule["key"]:
                fcombo.SelectedItem = item
        for name, _member in OPERATORS:
            item = combo_item(name, name)
            ocombo.Items.Add(item)
            if name == rule["op"]:
                ocombo.SelectedItem = item
        vcombo.IsEditable = True
        fill_values(cat, rule["key"], vcombo)
        vcombo.Text = rule["value"] or u""
        vcombo.IsEnabled = rule["op"] not in NO_VALUE_OPS
        remove = Button()
        remove.Style = w.FindResource("Btn")
        remove.Content = u"\u2715"
        remove.Padding = Thickness(0)
        remove.ToolTip = u"Remove the rule"
        remove.Width = 32
        for el, gap in ((boxed(fcombo, 210), 6), (boxed(ocombo, 180), 6),
                        (boxed(vcombo, 230), 6), (remove, 0)):
            el.Margin = Thickness(0, 0, gap, 0)
            g.Children.Add(el)
        st["filter_rows"].append((rule, (fcombo, ocombo, vcombo)))

        def on_field(sender, args):
            key = tag_of(fcombo)
            if key is None or key == rule["key"]:
                return
            rule["key"] = key
            rule["value"] = u""
            fill_values(cat, key, vcombo)
            vcombo.Text = u""

        def on_op(sender, args):
            op = tag_of(ocombo)
            if op is not None:
                rule["op"] = op
                vcombo.IsEnabled = op not in NO_VALUE_OPS

        def on_remove(sender, args):
            sync_filters()
            s["filters"].remove(rule)
            render_filters()

        fcombo.SelectionChanged += SelectionChangedEventHandler(on_field)
        ocombo.SelectionChanged += SelectionChangedEventHandler(on_op)
        remove.Click += RoutedEventHandler(on_remove)
        return g

    def fill_values(cat, key, vcombo):
        vcombo.Items.Clear()
        values = field_info(cat, key)["values"]
        for text in sorted(values.keys(), key=natural_key):
            vcombo.Items.Add(combo_item(text, text))

    def on_add_rule(sender, args):
        cat, s = cats[st["act"]], setup_of(st["act"])
        sync_filters()
        choices = [fld for fld in cat["fields"] if not fld["is_count"]]
        if not choices or len(s["filters"]) >= MAX_FILTERS:
            return
        first = s["fields"][0] if s["fields"] and s["fields"][0] in \
            [c["key"] for c in choices] else choices[0]["key"]
        s["filters"].append({"key": first, "op": OPERATORS[0][0], "value": u""})
        render_filters()

    f("btnAddRule").Click += RoutedEventHandler(on_add_rule)

    # ------------------------------------------------------------- sorts
    def render_sorts():
        cat, s = cats[st["act"]], setup_of(st["act"])
        sp = f("spSorts")
        sp.Children.Clear()
        while len(s["sorts"]) < MAX_SORTS:
            s["sorts"].append({"key": None, "desc": False, "h": False, "ft": False, "b": False})
        for i, o in enumerate(s["sorts"][:MAX_SORTS]):
            sp.Children.Add(sort_row(cat, s, i, o))

    def sort_row(cat, s, i, o):
        row = StackPanel()
        row.Orientation = Orientation.Horizontal
        row.Margin = Thickness(0, 0, 0, 6)
        lbl = text_block(u"Sort by" if i == 0 else u"Then by", SUB)
        lbl.Width = 60
        row.Children.Add(lbl)
        combo = ComboBox()
        none_item = combo_item(u"(none)", None)
        combo.Items.Add(none_item)
        combo.SelectedItem = none_item
        for key in s["fields"]:
            item = combo_item(label(cat, key), key)
            combo.Items.Add(item)
            if key == o["key"]:
                combo.SelectedItem = item
        row.Children.Add(boxed(combo, 230))
        toggles = []

        def tgl(text, attr, width=None, tip=None):
            t = ToggleButton()
            t.Style = w.FindResource("Tgl")
            t.Content = text
            t.Margin = Thickness(6, 0, 0, 0)
            t.Height = 28
            if width:
                t.Width = width
            t.ToolTip = tip
            t.IsChecked = bool(o[attr])

            def h(sender, args):
                o[attr] = bool(sender.IsChecked)
                if attr == "desc":
                    sender.Content = u"Z \u2192 A" if o["desc"] else u"A \u2192 Z"
            t.Click += RoutedEventHandler(h)
            toggles.append(t)
            row.Children.Add(t)
            return t

        tgl(u"Z \u2192 A" if o["desc"] else u"A \u2192 Z", "desc", 66, u"Ascending or descending")
        tgl(u"Header", "h", tip=u"A title row above each group")
        tgl(u"Footer", "ft", tip=u"A row under each group with its title, count and totals")
        tgl(u"Blank line", "b", tip=u"An empty row after each group")

        def refresh_enabled():
            on = o["key"] is not None
            for t in toggles:
                t.IsEnabled = on

        def on_pick(sender, args):
            o["key"] = tag_of(combo)
            refresh_enabled()

        combo.SelectionChanged += SelectionChangedEventHandler(on_pick)
        refresh_enabled()
        return row

    def on_check(attr):
        def h(sender, args):
            if not st["busy"]:
                setup_of(st["act"])[attr] = bool(sender.IsChecked)
        return h

    for chk, attr in ((f("chkItemize"), "itemize"), (f("chkGrand"), "grand"),
                      (f("chkLinks"), "links")):
        chk.Checked += RoutedEventHandler(on_check(attr))
        chk.Unchecked += RoutedEventHandler(on_check(attr))

    def on_name(sender, args):
        if not st["busy"]:
            setup_of(st["act"])["name"] = f("txtName").Text

    f("txtName").TextChanged += TextChangedEventHandler(on_name)

    # ----------------------------------------------------------- preview
    def render_preview():
        cat, s = cats[st["act"]], setup_of(st["act"])
        grid = f("spPreview")
        grid.Children.Clear()
        info = f("tbPreviewInfo")
        if not s["fields"]:
            info.Text = u"Add fields to see the schedule."
            return
        sync_filters()
        try:
            rows, notes = preview_table(cat, s)
        except Exception as ex:
            info.Text = u"Revit couldn't build this schedule: {}".format(ex)
            return
        parts = [u"{} - the schedule Revit will make{}".format(
            s["name"], u", linked models included" if s["links"] else u"")]
        parts += notes
        info.Text = u"\n".join(parts)
        if not rows:
            return
        ncols = max(len(r) for r in rows)
        widths = []
        for c in range(ncols):
            longest = max(len(r[c]) if c < len(r) else 0 for r in rows)
            widths.append(max(70, min(260, 14 + longest * 7)))
        for r, cells in enumerate(rows):
            line = StackPanel()
            line.Orientation = Orientation.Horizontal
            empty = not any(cells)
            for c, text in enumerate(cells):
                cell = Border()
                cell.Width = widths[c]
                cell.Padding = Thickness(6, 3, 6, 3)
                cell.BorderBrush = brush(CARD)
                cell.BorderThickness = Thickness(0, 0, 0, 1)
                if r == 0:
                    cell.Background = brush(SURFACE)
                cell.Child = text_block(text, SUB if r == 0 else TEXT, 11, bold=(r == 0))
                if empty:
                    cell.Height = 10
                line.Children.Add(cell)
            grid.Children.Add(line)

    f("btnRefresh").Click += RoutedEventHandler(lambda s_, a: render_preview())

    # ------------------------------------------------------------- tabs
    def tab_handler(name):
        def h(sender, args):
            sync_widgets()
            st["tab"] = name
            render_tab()
        return h

    for name, t in tabs.items():
        t.Click += RoutedEventHandler(tab_handler(name))

    def sync_widgets():
        sync_filters()

    # -------------------------------------------------------- left list
    def on_cat_search(sender, args):
        render_cats()

    def set_all(value):
        q = (f("txtCatSearch").Text or u"").strip().lower()
        for k in order:
            if not q or q in cats[k]["name"].lower():
                setups[k]["on"] = value
        render_cats()

    f("txtCatSearch").TextChanged += TextChangedEventHandler(on_cat_search)
    f("btnCatAll").Click += RoutedEventHandler(lambda s_, a: set_all(True))
    f("btnCatNone").Click += RoutedEventHandler(lambda s_, a: set_all(False))

    # ------------------------------------------------------ create / cancel
    def on_create(sender, args):
        sync_widgets()
        picked = [k for k in order if setups[k]["on"]]
        if not picked:
            return msg(u"Check at least one category.")
        problems = []
        for k in picked:
            s = setup_of(k)
            if cats[k]["error"]:
                problems.append(u"{} can't be scheduled".format(cats[k]["name"]))
            elif not s["fields"]:
                problems.append(u"{}: add at least one field".format(cats[k]["name"]))
        if problems:
            return msg(u"; ".join(problems) + u".")
        result.update({"ok": True, "picked": picked, "setups": setups})
        w.Close()

    f("btnCreate").Click += RoutedEventHandler(on_create)
    f("btnCancel").Click += RoutedEventHandler(lambda s_, a: w.Close())

    # pick the first category that holds elements of a common BOQ kind
    for k in order:
        if cats[k]["name"] in (u"Walls", u"Doors", u"Floors"):
            st["act"] = k
            break
    render_all()
    enable_combo_search(w)

    frame = DispatcherFrame()

    def on_closed(s_, e):
        frame.Continue = False

    w.Closed += EventHandler(on_closed)
    try:
        WindowInteropHelper(w).Owner = __revit__.MainWindowHandle
    except Exception:
        pass
    w.Show()
    Dispatcher.PushFrame(frame)
    return result


# --------------------------------------------------------------- result
def show_result(created, notes):
    td = TaskDialog(TITLE)
    td.MainInstruction = u"{} schedule{} created".format(len(created), u"" if len(created) == 1 else u"s")
    lines = [u"\u2022 " + n for n in created]
    if notes:
        lines.append(u"")
        lines.append(u"{} notes - expand details for the list.".format(len(notes)))
        td.ExpandedContent = u"\n".join(notes[:40])
    td.MainContent = u"\n".join(lines)
    td.CommonButtons = TaskDialogCommonButtons.Ok
    td.Show()


# ----------------------------------------------------------------- main
def main():
    if doc.IsFamilyDocument:
        forms.alert(u"Schedule Builder works in a project model.", title=TITLE)
        return
    cats = collect_categories()
    if not cats:
        forms.alert(u"No schedulable elements found in this model.", title=TITLE)
        return
    res = show_ui(cats)
    if not res["ok"]:
        return
    setups = res["setups"]
    save_setups(cats, dict((k, v) for k, v in setups.items() if not v.get("_bare")))

    taken = existing_names()
    created, notes, first = [], [], [None]
    t = Transaction(doc, "Create schedules")
    t.Start()
    try:
        for k in res["picked"]:
            cat, s = cats[k], setups[k]
            name = unique_name(s["name"], taken)
            if name != s["name"].strip():
                notes.append(u"{}: '{}' already exists - named '{}'".format(
                    cat["name"], s["name"].strip(), name))
            sched = build_schedule(cat, s, name, notes)
            created.append(sched.Name)
            if first[0] is None:
                first[0] = sched.Id
        t.Commit()
    except Exception as ex:
        t.RollBack()
        forms.alert(u"Failed - no schedules were created.\n\n{}".format(ex), title=TITLE)
        return

    show_result(created, notes)
    if first[0] is not None:
        try:
            uidoc.ActiveView = doc.GetElement(first[0])
        except Exception:
            pass


main()

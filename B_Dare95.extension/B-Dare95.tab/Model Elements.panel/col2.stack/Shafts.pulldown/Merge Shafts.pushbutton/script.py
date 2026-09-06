# -*- coding: utf-8 -*-
"""Shaft Merger

Groups every Shaft Opening in the project by:
    - Shaft Function   (custom / shared instance parameter)
    - Base Constraint  (WALL_BASE_CONSTRAINT)
    - Base Offset      (WALL_BASE_OFFSET)
    - Top Constraint   (WALL_HEIGHT_TYPE)
    - Top Offset       (WALL_TOP_OFFSET)
    - Unconnected Height (only when Top Constraint is <Unconnected>)

Every group that holds more than one shaft can be merged into a single shaft
element: one sketch that carries all the boundary loops of its members.
Overlapping / touching loops can optionally be unioned into a clean outline.

IronPython 2.7 / Revit 2024-2027.
"""

__title__ = "Merge\nShafts"
__author__ = "B_Dare95"

import clr

clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")
clr.AddReference("System.Xaml")

from System import EventHandler
from System.Collections.Generic import List
from System.Windows import Visibility, RoutedEventHandler
from System.Windows.Controls import CheckBox, TextChangedEventHandler
from System.Windows.Markup import XamlReader
from System.Windows.Threading import Dispatcher, DispatcherFrame

from pyrevit import revit, DB, UI, script

doc = revit.doc
uidoc = revit.uidoc
output = script.get_output()

# ----------------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------------

# Candidate names for the "Shaft Function" instance parameter. The first one
# found on an element wins. Add your own naming variants here.
FUNCTION_PARAM_NAMES = [
    "Shaft Function",
    "SHAFT FUNCTION",
    "Shaft_Function",
]

# Grouping tolerance for offsets, in feet (1e-4 ft ~ 0.03 mm).
OFFSET_TOL = 1e-4

# Endpoint matching tolerance when chaining sketch curves, in feet.
CHAIN_TOL = 1e-5

# Extrusion height used for the boolean union of shaft profiles, in feet.
UNION_EXTRUSION_HEIGHT = 10.0

# Parameters never copied onto the merged shaft (handled explicitly instead).
SKIP_COPY_PARAMS = set([
    "Base Constraint", "Base Offset",
    "Top Constraint", "Top Offset",
    "Unconnected Height", "Height",
])


# ----------------------------------------------------------------------------
# SMALL HELPERS
# ----------------------------------------------------------------------------

def id_value(eid):
    """ElementId -> int, Revit 2024-2027 safe."""
    if eid is None:
        return -1
    try:
        return eid.Value
    except AttributeError:
        return eid.IntegerValue


def elem_name(el):
    """Bypass IronPython's Element.Name overload ambiguity."""
    if el is None:
        return "<none>"
    try:
        return DB.Element.Name.__get__(el)
    except Exception:
        return "<unnamed>"


def get_param(el, bip, fallback_name):
    """BuiltInParameter first, then a name lookup as a safety net."""
    p = None
    try:
        p = el.get_Parameter(bip)
    except Exception:
        p = None
    if p is None:
        p = el.LookupParameter(fallback_name)
    return p


def get_function_param(el):
    for nm in FUNCTION_PARAM_NAMES:
        p = el.LookupParameter(nm)
        if p is not None:
            return p
    return None


def param_text(p):
    """Readable value of a parameter, project units respected."""
    if p is None:
        return ""
    try:
        s = p.AsValueString()
        if s:
            return s
    except Exception:
        pass
    st = p.StorageType
    if st == DB.StorageType.String:
        return p.AsString() or ""
    if st == DB.StorageType.Integer:
        return str(p.AsInteger())
    if st == DB.StorageType.Double:
        return str(round(p.AsDouble(), 6))
    if st == DB.StorageType.ElementId:
        return elem_name(doc.GetElement(p.AsElementId()))
    return ""


def quantize(v):
    """Round a length so tiny authoring noise doesn't split a group."""
    return int(round(v / OFFSET_TOL))


# ----------------------------------------------------------------------------
# SKETCH / GEOMETRY
# ----------------------------------------------------------------------------

def get_sketch(opening):
    """The Sketch element behind a shaft opening."""
    try:
        ids = opening.GetDependentElements(DB.ElementClassFilter(DB.Sketch))
    except Exception:
        return None
    for eid in ids:
        el = doc.GetElement(eid)
        if isinstance(el, DB.Sketch):
            return el
    return None


def get_loops(opening):
    """All boundary loops of a shaft as [[Curve, ...], ...]."""
    loops = []
    sk = get_sketch(opening)
    if sk is not None:
        try:
            for arr in sk.Profile:
                curves = [c for c in arr]
                if curves:
                    loops.append(curves)
        except Exception:
            pass
    if not loops:
        # Fallback: flat curve list, treated as a single loop.
        try:
            curves = [c for c in opening.BoundaryCurves]
            if curves:
                loops.append(curves)
        except Exception:
            pass
    return loops


def chain_curves(curves):
    """Order curves head-to-tail so they can feed a CurveLoop / CurveArray."""
    if not curves:
        return []
    remaining = list(curves)
    ordered = [remaining.pop(0)]
    while remaining:
        end = ordered[-1].GetEndPoint(1)
        picked = None
        for i, c in enumerate(remaining):
            if c.GetEndPoint(0).DistanceTo(end) < CHAIN_TOL:
                picked = remaining.pop(i)
                break
            if c.GetEndPoint(1).DistanceTo(end) < CHAIN_TOL:
                remaining.pop(i)
                picked = c.CreateReversed()
                break
        if picked is None:
            # Not a single continuous loop - hand back what we have.
            return ordered + remaining
        ordered.append(picked)
    return ordered


def move_curves(curves, dz):
    tr = DB.Transform.CreateTranslation(DB.XYZ(0, 0, dz))
    return [c.CreateTransformed(tr) for c in curves]


def flatten_loops(loops):
    """Drop every loop onto Z = 0 so boolean ops line up."""
    flat = []
    for lp in loops:
        z = lp[0].GetEndPoint(0).Z
        flat.append(move_curves(lp, -z) if abs(z) > 1e-9 else list(lp))
    return flat


def to_curve_loop(curves):
    cl = DB.CurveLoop()
    for c in chain_curves(curves):
        cl.Append(c)
    return cl


def union_loops(loops):
    """Boolean-union overlapping profiles; returns merged loops at Z = 0.

    Falls back to the untouched loop list if anything about the union fails.
    """
    solids = []
    for lp in loops:
        try:
            cl = to_curve_loop(lp)
            cls = List[DB.CurveLoop]()
            cls.Add(cl)
            solids.append(DB.GeometryCreationUtilities.CreateExtrusionGeometry(
                cls, DB.XYZ.BasisZ, UNION_EXTRUSION_HEIGHT))
        except Exception:
            return None

    if not solids:
        return None

    merged = solids[0]
    for s in solids[1:]:
        try:
            merged = DB.BooleanOperationsUtils.ExecuteBooleanOperation(
                merged, s, DB.BooleanOperationsType.Union)
        except Exception:
            return None

    result = []
    try:
        for f in merged.Faces:
            if not isinstance(f, DB.PlanarFace):
                continue
            n = f.FaceNormal
            if abs(n.Z + 1.0) > 1e-6:      # bottom faces only
                continue
            for cl in f.GetEdgesAsCurveLoops():
                curves = [c for c in cl]
                if curves:
                    result.append(move_curves(curves, -curves[0].GetEndPoint(0).Z))
    except Exception:
        return None

    return result if result else None


# ----------------------------------------------------------------------------
# GROUPING
# ----------------------------------------------------------------------------

def collect_shafts():
    return list(DB.FilteredElementCollector(doc)
                .OfCategory(DB.BuiltInCategory.OST_ShaftOpening)
                .WhereElementIsNotElementType()
                .ToElements())


def read_key(shaft):
    """(key tuple, display dict) for one shaft, or (None, reason) if unusable."""
    p_func = get_function_param(shaft)
    p_base = get_param(shaft, DB.BuiltInParameter.WALL_BASE_CONSTRAINT, "Base Constraint")
    p_boff = get_param(shaft, DB.BuiltInParameter.WALL_BASE_OFFSET, "Base Offset")
    p_top = get_param(shaft, DB.BuiltInParameter.WALL_HEIGHT_TYPE, "Top Constraint")
    p_toff = get_param(shaft, DB.BuiltInParameter.WALL_TOP_OFFSET, "Top Offset")
    p_uh = get_param(shaft, DB.BuiltInParameter.WALL_USER_HEIGHT_PARAM, "Unconnected Height")

    if p_base is None or p_top is None:
        return None, "Base/Top Constraint parameter not found"

    base_id = p_base.AsElementId()
    top_id = p_top.AsElementId()
    base_off = p_boff.AsDouble() if p_boff is not None else 0.0
    top_off = p_toff.AsDouble() if p_toff is not None else 0.0
    unconnected = (id_value(top_id) < 0)
    user_h = p_uh.AsDouble() if (unconnected and p_uh is not None) else 0.0

    func = ""
    if p_func is not None:
        func = (param_text(p_func) or "").strip()

    key = (
        func,
        id_value(base_id), quantize(base_off),
        id_value(top_id), quantize(top_off),
        quantize(user_h),
    )

    disp = {
        "func": func if func else "<none>",
        "base": elem_name(doc.GetElement(base_id)),
        "base_off": param_text(p_boff),
        "top": "<Unconnected>" if unconnected else elem_name(doc.GetElement(top_id)),
        "top_off": param_text(p_toff),
        "height": param_text(p_uh) if unconnected else "",
        "base_id": base_id,
        "top_id": top_id,
        "base_off_val": base_off,
        "top_off_val": top_off,
        "user_h": user_h,
        "unconnected": unconnected,
    }
    return key, disp


def build_groups():
    groups = {}
    skipped = []
    for sh in collect_shafts():
        if id_value(sh.GroupId) > 0:
            skipped.append((sh, "inside a Revit group"))
            continue
        key, disp = read_key(sh)
        if key is None:
            skipped.append((sh, disp))
            continue
        if not get_loops(sh):
            skipped.append((sh, "no readable boundary sketch"))
            continue
        g = groups.get(key)
        if g is None:
            g = {"key": key, "disp": disp, "shafts": []}
            groups[key] = g
        g["shafts"].append(sh)

    mergeable = [g for g in groups.values() if len(g["shafts"]) > 1]
    mergeable.sort(key=lambda g: (-len(g["shafts"]), g["disp"]["func"]))
    return mergeable, len(groups), skipped


def group_label(g):
    d = g["disp"]
    txt = u"[{0} shafts]   Function: {1}   \u2022   Base: {2} ({3})   \u2022   Top: {4} ({5})".format(
        len(g["shafts"]), d["func"], d["base"], d["base_off"], d["top"], d["top_off"])
    if d["unconnected"] and d["height"]:
        txt += u"   \u2022   Height: {0}".format(d["height"])
    return txt


# ----------------------------------------------------------------------------
# MERGE EXECUTION
# ----------------------------------------------------------------------------

class KeepAllWarnings(DB.IFailuresPreprocessor):
    """Required by SketchEditScope.Commit.

    Deliberately does NOT delete, resolve or suppress anything - it returns
    Continue so every Revit warning still reaches the user normally.
    """

    def PreprocessFailures(self, failuresAccessor):
        return DB.FailureProcessingResult.Continue


def set_constraints(opening, disp):
    p_base = get_param(opening, DB.BuiltInParameter.WALL_BASE_CONSTRAINT, "Base Constraint")
    if p_base is not None and not p_base.IsReadOnly:
        p_base.Set(disp["base_id"])

    p_top = get_param(opening, DB.BuiltInParameter.WALL_HEIGHT_TYPE, "Top Constraint")
    if p_top is not None and not p_top.IsReadOnly:
        p_top.Set(DB.ElementId.InvalidElementId if disp["unconnected"] else disp["top_id"])

    if disp["unconnected"]:
        p_uh = get_param(opening, DB.BuiltInParameter.WALL_USER_HEIGHT_PARAM, "Unconnected Height")
        if p_uh is not None and not p_uh.IsReadOnly and disp["user_h"] > 0:
            p_uh.Set(disp["user_h"])

    p_boff = get_param(opening, DB.BuiltInParameter.WALL_BASE_OFFSET, "Base Offset")
    if p_boff is not None and not p_boff.IsReadOnly:
        p_boff.Set(disp["base_off_val"])

    p_toff = get_param(opening, DB.BuiltInParameter.WALL_TOP_OFFSET, "Top Offset")
    if p_toff is not None and not p_toff.IsReadOnly:
        p_toff.Set(disp["top_off_val"])


# "None" is a Python keyword, so this enum member has to be fetched by name.
ST_NONE = getattr(DB.StorageType, "None")


def common_param_values(shafts):
    """Instance parameters whose value is identical on every group member."""
    first = shafts[0]
    candidates = {}
    for p in first.Parameters:
        try:
            if p.IsReadOnly or p.StorageType == ST_NONE:
                continue
        except Exception:
            continue
        nm = p.Definition.Name
        if nm in SKIP_COPY_PARAMS:
            continue
        candidates[nm] = p

    common = {}
    for nm, p in candidates.items():
        st = p.StorageType
        if st == DB.StorageType.String:
            val = p.AsString()
        elif st == DB.StorageType.Integer:
            val = p.AsInteger()
        elif st == DB.StorageType.Double:
            val = p.AsDouble()
        elif st == DB.StorageType.ElementId:
            val = p.AsElementId()
        else:
            continue

        same = True
        for other in shafts[1:]:
            op = other.LookupParameter(nm)
            if op is None or op.StorageType != st:
                same = False
                break
            if st == DB.StorageType.String:
                oval = op.AsString()
            elif st == DB.StorageType.Integer:
                oval = op.AsInteger()
            elif st == DB.StorageType.Double:
                oval = op.AsDouble()
            else:
                oval = op.AsElementId()

            if st == DB.StorageType.Double:
                if abs((oval or 0.0) - (val or 0.0)) > OFFSET_TOL:
                    same = False
                    break
            elif st == DB.StorageType.ElementId:
                if id_value(oval) != id_value(val):
                    same = False
                    break
            elif oval != val:
                same = False
                break

        if same and val is not None:
            common[nm] = (st, val)
    return common


def apply_common_params(opening, common):
    for nm, pair in common.items():
        st, val = pair
        p = opening.LookupParameter(nm)
        if p is None or p.IsReadOnly or p.StorageType != st:
            continue
        try:
            p.Set(val)
        except Exception:
            pass


def add_loops_to_sketch(opening, loops):
    """Push extra closed loops into an existing shaft sketch."""
    sk = get_sketch(opening)
    if sk is None:
        raise Exception("Merged shaft has no accessible sketch.")

    plane = sk.SketchPlane
    target_z = plane.GetPlane().Origin.Z

    scope = DB.SketchEditScope(doc, "Add shaft boundary loops")
    scope.Start(sk.Id)

    t = DB.Transaction(doc, "Add shaft boundary loops")
    t.Start()
    try:
        for lp in loops:
            dz = target_z - lp[0].GetEndPoint(0).Z
            curves = move_curves(lp, dz) if abs(dz) > 1e-9 else lp
            for c in chain_curves(curves):
                doc.Create.NewModelCurve(c, plane)
        t.Commit()
    except Exception:
        if not t.HasEnded():
            t.RollBack()
        scope.Cancel()
        raise

    scope.Commit(KeepAllWarnings())


def merge_group(g, do_union, do_delete, do_copy):
    """Merge one group. Returns (ok, message)."""
    shafts = g["shafts"]
    disp = g["disp"]

    raw_loops = []
    for sh in shafts:
        for lp in get_loops(sh):
            raw_loops.append(lp)
    if not raw_loops:
        return False, "no boundary loops found"

    sketch_z = raw_loops[0][0].GetEndPoint(0).Z
    loops = flatten_loops(raw_loops)

    unioned = False
    if do_union and len(loops) > 1:
        merged = union_loops(loops)
        if merged:
            unioned = len(merged) != len(loops)
            loops = merged

    loops = [move_curves(lp, sketch_z) for lp in loops]

    base_level = doc.GetElement(disp["base_id"])
    top_level = doc.GetElement(disp["top_id"]) if not disp["unconnected"] else base_level
    if base_level is None or top_level is None:
        return False, "base or top level could not be resolved"

    common = common_param_values(shafts) if do_copy else {}
    old_ids = List[DB.ElementId]()
    for sh in shafts:
        old_ids.Add(sh.Id)

    tg = DB.TransactionGroup(doc, "Merge shaft group")
    tg.Start()
    t = None
    try:
        t = DB.Transaction(doc, "Create merged shaft")
        t.Start()

        ca = DB.CurveArray()
        for c in chain_curves(loops[0]):
            ca.Append(c)
        new_op = doc.Create.NewOpening(base_level, top_level, ca)
        if new_op is None:
            raise Exception("NewOpening returned nothing.")

        set_constraints(new_op, disp)
        if common:
            apply_common_params(new_op, common)
        t.Commit()

        if len(loops) > 1:
            add_loops_to_sketch(new_op, loops[1:])

        if do_delete:
            t = DB.Transaction(doc, "Delete source shafts")
            t.Start()
            doc.Delete(old_ids)
            t.Commit()

        tg.Assimilate()

        msg = "merged {0} shafts into ID {1} ({2} loop(s){3})".format(
            len(shafts), id_value(new_op.Id), len(loops),
            ", unioned" if unioned else "")
        if not do_delete:
            msg += " - originals kept"
        return True, msg

    except Exception as ex:
        try:
            if t is not None and not t.HasEnded():
                t.RollBack()
        except Exception:
            pass
        try:
            tg.RollBack()
        except Exception:
            pass
        return False, str(ex)


# ----------------------------------------------------------------------------
# UI
# ----------------------------------------------------------------------------

XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Merge Shafts" Height="700" Width="900"
        WindowStartupLocation="CenterScreen" Background="#1E1E2E">
  <Window.Resources>

    <Style TargetType="TextBox">
      <Setter Property="Background" Value="#313244"/>
      <Setter Property="Foreground" Value="#CDD6F4"/>
      <Setter Property="BorderBrush" Value="#45475A"/>
      <Setter Property="BorderThickness" Value="1"/>
      <Setter Property="Padding" Value="6,4"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="Height" Value="28"/>
    </Style>

    <Style x:Key="ItemCheck" TargetType="CheckBox">
      <Setter Property="Foreground" Value="#CDD6F4"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="Margin" Value="8,5,8,5"/>
      <Setter Property="VerticalContentAlignment" Value="Center"/>
    </Style>

    <Style x:Key="OptCheck" TargetType="CheckBox">
      <Setter Property="Foreground" Value="#A6ADC8"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="Margin" Value="0,4,18,4"/>
      <Setter Property="VerticalContentAlignment" Value="Center"/>
    </Style>

    <Style x:Key="AccentButton" TargetType="Button">
      <Setter Property="Foreground" Value="#1E1E2E"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="Height" Value="32"/>
      <Setter Property="MinWidth" Value="130"/>
      <Setter Property="Margin" Value="8,0,0,0"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="bd" Background="#F0A500" CornerRadius="6" Padding="14,4">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="bd" Property="Opacity" Value="0.85"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="GhostButton" TargetType="Button">
      <Setter Property="Foreground" Value="#CDD6F4"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="Height" Value="28"/>
      <Setter Property="MinWidth" Value="90"/>
      <Setter Property="Margin" Value="8,0,0,0"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="bd" Background="#313244" BorderBrush="#45475A"
                    BorderThickness="1" CornerRadius="6" Padding="10,3">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="bd" Property="Background" Value="#45475A"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

  </Window.Resources>

  <Grid Margin="16">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <StackPanel Grid.Row="0" Margin="0,0,0,12">
      <TextBlock Text="Merge Shafts" Foreground="#F0A500" FontSize="20" FontWeight="Bold"/>
      <TextBlock x:Name="tbHeader" Foreground="#A6ADC8" FontSize="12" Margin="0,4,0,0"
                 TextWrapping="Wrap"/>
    </StackPanel>

    <Grid Grid.Row="1" Margin="0,0,0,8">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="Auto"/>
        <ColumnDefinition Width="Auto"/>
      </Grid.ColumnDefinitions>
      <TextBox x:Name="tbSearch" Grid.Column="0"/>
      <Button x:Name="btnAll" Grid.Column="1" Content="Select All" Style="{StaticResource GhostButton}"/>
      <Button x:Name="btnNone" Grid.Column="2" Content="Select None" Style="{StaticResource GhostButton}"/>
    </Grid>

    <Border Grid.Row="2" Background="#2A2A3C" BorderBrush="#45475A" BorderThickness="1"
            CornerRadius="8" Padding="4">
      <ScrollViewer VerticalScrollBarVisibility="Auto">
        <StackPanel x:Name="spGroups"/>
      </ScrollViewer>
    </Border>

    <Border Grid.Row="3" Background="#2A2A3C" BorderBrush="#45475A" BorderThickness="1"
            CornerRadius="8" Padding="12,8" Margin="0,10,0,0">
      <WrapPanel>
        <CheckBox x:Name="chkUnion" Style="{StaticResource OptCheck}" IsChecked="True"
                  Content="Union overlapping / touching outlines"/>
        <CheckBox x:Name="chkDelete" Style="{StaticResource OptCheck}" IsChecked="True"
                  Content="Delete original shafts"/>
        <CheckBox x:Name="chkCopy" Style="{StaticResource OptCheck}" IsChecked="True"
                  Content="Copy parameters shared by all members"/>
      </WrapPanel>
    </Border>

    <StackPanel Grid.Row="4" Orientation="Horizontal" HorizontalAlignment="Right"
                Margin="0,12,0,0">
      <Button x:Name="btnCancel" Content="Cancel" Style="{StaticResource GhostButton}"/>
      <Button x:Name="btnRun" Content="Merge Selected" Style="{StaticResource AccentButton}"/>
    </StackPanel>
  </Grid>
</Window>
"""


def show_window(groups, total_groups, skipped):
    window = XamlReader.Parse(XAML)

    tb_header = window.FindName("tbHeader")
    tb_search = window.FindName("tbSearch")
    sp_groups = window.FindName("spGroups")
    btn_all = window.FindName("btnAll")
    btn_none = window.FindName("btnNone")
    btn_run = window.FindName("btnRun")
    btn_cancel = window.FindName("btnCancel")
    chk_union = window.FindName("chkUnion")
    chk_delete = window.FindName("chkDelete")
    chk_copy = window.FindName("chkCopy")

    item_style = window.Resources["ItemCheck"]

    total_shafts = sum(len(g["shafts"]) for g in groups)
    tb_header.Text = (u"{0} mergeable group(s) found across {1} distinct parameter "
                      u"combination(s) - {2} shafts will collapse into {3}. "
                      u"{4} shaft(s) skipped.").format(
        len(groups), total_groups, total_shafts, len(groups), len(skipped))

    rows = []
    for g in groups:
        cb = CheckBox()
        cb.Style = item_style
        cb.Content = group_label(g)
        cb.IsChecked = True
        sp_groups.Children.Add(cb)
        rows.append((cb, g, group_label(g).lower()))

    result = {"ok": False}

    def on_search(sender, args):
        needle = (tb_search.Text or "").strip().lower()
        for cb, g, text in rows:
            cb.Visibility = Visibility.Visible if (not needle or needle in text) \
                else Visibility.Collapsed

    def on_all(sender, args):
        for cb, g, text in rows:
            if cb.Visibility == Visibility.Visible:
                cb.IsChecked = True

    def on_none(sender, args):
        for cb, g, text in rows:
            if cb.Visibility == Visibility.Visible:
                cb.IsChecked = False

    def on_run(sender, args):
        result["ok"] = True
        window.Close()

    def on_cancel(sender, args):
        window.Close()

    tb_search.TextChanged += TextChangedEventHandler(on_search)
    btn_all.Click += RoutedEventHandler(on_all)
    btn_none.Click += RoutedEventHandler(on_none)
    btn_run.Click += RoutedEventHandler(on_run)
    btn_cancel.Click += RoutedEventHandler(on_cancel)

    frame = DispatcherFrame()

    def on_closed(sender, args):
        frame.Continue = False

    window.Closed += EventHandler(on_closed)
    window.Show()
    Dispatcher.PushFrame(frame)

    if not result["ok"]:
        return None

    chosen = [g for cb, g, text in rows if cb.IsChecked]
    return {
        "groups": chosen,
        "union": bool(chk_union.IsChecked),
        "delete": bool(chk_delete.IsChecked),
        "copy": bool(chk_copy.IsChecked),
    }


# ----------------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------------

def main():
    groups, total_groups, skipped = build_groups()

    if not groups:
        UI.TaskDialog.Show(
            "Merge Shafts",
            "No shaft openings share the same Shaft Function, Base Constraint, "
            "Base Offset, Top Constraint and Top Offset.\n\n"
            "{0} distinct parameter combination(s) found, "
            "{1} shaft(s) skipped.".format(total_groups, len(skipped)))
        return

    opts = show_window(groups, total_groups, skipped)
    if opts is None or not opts["groups"]:
        return

    ok_count = 0
    fail_count = 0
    removed = 0
    lines = []

    for g in opts["groups"]:
        count = len(g["shafts"])
        ok, msg = merge_group(g, opts["union"], opts["delete"], opts["copy"])
        if ok:
            ok_count += 1
            if opts["delete"]:
                removed += count
            lines.append(u"OK    | {0} | {1}".format(group_label(g), msg))
        else:
            fail_count += 1
            lines.append(u"FAIL  | {0} | {1}".format(group_label(g), msg))

    output.print_md("## Merge Shafts - Report")
    output.print_md("**{0} group(s) merged, {1} failed, {2} shaft(s) deleted.**".format(
        ok_count, fail_count, removed))
    for ln in lines:
        print(ln)

    if skipped:
        output.print_md("### Skipped shafts")
        for sh, why in skipped:
            print(u"ID {0} - {1}".format(id_value(sh.Id), why))

    UI.TaskDialog.Show(
        "Merge Shafts",
        "{0} group(s) merged.\n{1} group(s) failed.\n{2} original shaft(s) deleted.\n\n"
        "See the pyRevit output window for the full report.".format(
            ok_count, fail_count, removed))


main()
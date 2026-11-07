# -*- coding: utf-8 -*-
__doc__ = """__________________________________________________
Description:

Manages every Revit link, DWG link and CAD import in one window: its workset, Room Bounding, whether it is pinned, and where it sits.

Under each placed Revit link a status line checks its position: Shared Coordinates, Base Point and Internal Origin get a tick when the link sits there, or the offset when it doesn't, followed by its rotation and how many grids and levels with the same name line up exactly. Pick Internal Origin, Base Point or Shared Coords to move a link there; it is pinned again after the move.
__________________________________________________
How-to:

-> Click on the button
-> Pick a workset for each link, or use Set all visible to
-> Tick or untick Room bounding and Pinned
-> Read the status line under each link, and click a position to move it there
-> Changed links get a yellow dot; nothing changes until you click Apply changes
-> A summary shows what was changed
__________________________________________________
Author: Mohamed Bedair"""


__author__ = "Mohamed Bedair"

import math

import clr

clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")
clr.AddReference("System.Xml")

from Autodesk.Revit.DB import (
    Arc,
    BasePoint,
    BuiltInParameter,
    CADLinkType,
    ElementId,
    ElementTransformUtils,
    ExternalFileUtils,
    FilteredElementCollector,
    FilteredWorksetCollector,
    Grid,
    ImportInstance,
    Level,
    Line,
    RevitLinkInstance,
    RevitLinkType,
    Transaction,
    TransactionGroup,
    Transform,
    WorksetKind,
    WorksharingUtils,
    XYZ,
)
from Autodesk.Revit.UI import TaskDialog

from System import EventHandler
from System.Collections.Generic import List
from System.Windows import (
    CornerRadius,
    FontWeights,
    HorizontalAlignment,
    RoutedEventHandler,
    TextTrimming,
    Thickness,
    VerticalAlignment,
    Visibility,
)
from System.Windows.Controls import (
    Border,
    CheckBox,
    ComboBox,
    Dock,
    DockPanel,
    Orientation,
    StackPanel,
    TextBlock,
    TextChangedEventHandler,
    WrapPanel,
)
from System.Windows.Controls.Primitives import ToggleButton
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Markup import XamlReader
from System.Windows.Media import BrushConverter
from System.Windows.Shapes import Ellipse
from System.Windows.Threading import Dispatcher, DispatcherFrame
from bd_combo_search import enable_combo_search

doc = __revit__.ActiveUIDocument.Document  # noqa: F821
TOOL = "Link Manager"

# ---------------------------------------------------------------------------
# Palette (IBM Carbon)
# ---------------------------------------------------------------------------
C_TEXT = "#F4F4F4"
C_SUBTEXT = "#A8A8A8"
C_MUTED = "#8D8D8D"
C_ACCENT = "#F1C21B"
C_OK = "#42BE65"
C_WARN = "#F1C21B"
C_BAD = "#FF8389"
CHIP = {
    "ok": ("#0E2A18", "#A7F0BA"),
    "warn": ("#3A2E06", "#FDDC69"),
    "bad": ("#4A0E12", "#FFB3B8"),
    "na": ("#2E2E2E", "#8D8D8D"),
}

_BC = BrushConverter()
_BRUSH_CACHE = {}


def brush(hex_string):
    if hex_string not in _BRUSH_CACHE:
        _BRUSH_CACHE[hex_string] = _BC.ConvertFromString(hex_string)
    return _BRUSH_CACHE[hex_string]


# Column widths, shared between the header row and the data rows
W_WORKSET = 190
W_ROOM = 96
W_PIN = 64
W_POS = 262

TOL = 0.001          # ft (0.3 mm)
ANG_TOL = 1e-4       # rad
POSITIONS = ("Internal Origin", "Base Point", "Shared Coordinates")
SEG_LABEL = {"Internal Origin": "Internal Origin", "Base Point": "Base Point",
             "Shared Coordinates": "Shared Coords"}

STATUS_TEXT = {
    "Loaded": "Loaded",
    "Unloaded": "Unloaded (all users)",
    "LocallyUnloaded": "Unloaded (this user)",
    "NotFound": "Not Found",
    "InClosedWorkset": "In Closed Workset",
    "Invalid": "Invalid",
}

STATUS_COLOR = {
    "Loaded": C_OK,
    "Unloaded (all users)": C_BAD,
    "Unloaded (this user)": C_WARN,
    "Not Found": C_BAD,
    "In Closed Workset": C_WARN,
    "Invalid": C_BAD,
    "Imported (not linked)": C_SUBTEXT,
    "Unknown": C_SUBTEXT,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def id_value(id_obj):
    """ElementId/WorksetId integer value, valid on Revit 2024 through 2027."""
    try:
        return id_obj.Value
    except AttributeError:
        return id_obj.IntegerValue


def element_name(el):
    try:
        name = el.Name
    except Exception:
        name = ""
    if not name:
        try:
            param = el.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
            if param:
                name = param.AsString() or ""
        except Exception:
            pass
    return name or "<unnamed>"


def plural(n, word, word_pl=None):
    return "{0} {1}".format(n, word if n == 1 else (word_pl or word + "s"))


def fmt_mm(ft):
    return "{0:,} mm".format(int(round(abs(ft) * 304.8)))


def fmt_signed_mm(ft):
    mm = int(round(ft * 304.8))
    if mm == 0:
        return "0 mm"
    return u"{0}{1:,} mm".format(u"+" if mm > 0 else u"\u2212", abs(mm))


def fmt_deg(rad):
    deg = math.degrees(rad)
    if abs(deg) < 0.005:
        return u"0\u00b0"
    return u"{0:.2f}\u00b0".format(deg)


def is_external_reference(el):
    try:
        return ExternalFileUtils.IsExternalFileReference(doc, el.Id)
    except Exception:
        return False


def link_status(el, is_cad):
    """Readable loading status for a link type element."""
    if is_cad and not is_external_reference(el):
        return "Imported (not linked)"

    status = None
    try:
        status = el.GetLinkedFileStatus()
    except AttributeError:
        try:
            status = el.GetExternalFileReference().GetLinkedFileStatus()
        except Exception:
            status = None
    except Exception:
        status = None

    if status is None:
        return "Unknown"
    return STATUS_TEXT.get(str(status), str(status))


def other_user_owner(el):
    """Returns the owning username if somebody else has the element checked out."""
    if not doc.IsWorkshared:
        return ""
    try:
        info = WorksharingUtils.GetWorksharingTooltipInfo(doc, el.Id)
        owner = info.Owner or ""
    except Exception:
        return ""
    if not owner:
        return ""
    try:
        me = doc.Application.Username
    except Exception:
        me = ""
    if owner.lower() == (me or "").lower():
        return ""
    return owner


def workset_param(el):
    try:
        return el.get_Parameter(BuiltInParameter.ELEM_PARTITION_PARAM)
    except Exception:
        return None


def room_bounding_param(el):
    """The link type's Room Bounding setting."""
    try:
        p = el.get_Parameter(BuiltInParameter.WALL_ATTR_ROOM_BOUNDING)
        if p is not None:
            return p
    except Exception:
        pass
    try:
        return el.LookupParameter("Room Bounding")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Position: where a Revit link sits (same checks as Crop by Linked Scopebox)
# ---------------------------------------------------------------------------
def flat(p):
    return XYZ(p.X, p.Y, 0)


def angle_of(t):
    """Rotation of a transform about Z, in radians."""
    return math.atan2(t.BasisX.Y, t.BasisX.X)


def angle_diff(a, b):
    d = a - b
    while d > math.pi:
        d -= 2 * math.pi
    while d < -math.pi:
        d += 2 * math.pi
    return d


def internal_to_shared(d):
    """Internal -> shared transform. The direction of GetTotalTransform is
    confirmed against the base points' SharedPosition instead of assumed."""
    g = d.ActiveProjectLocation.GetTotalTransform()
    try:
        for bp in (BasePoint.GetProjectBasePoint(d), BasePoint.GetSurveyPoint(d)):
            pi, ps = bp.Position, bp.SharedPosition
            e_fwd = g.OfPoint(pi).DistanceTo(ps)
            e_inv = g.Inverse.OfPoint(pi).DistanceTo(ps)
            if abs(e_fwd - e_inv) > 1e-6:
                return g if e_fwd < e_inv else g.Inverse
    except Exception:
        pass
    return g.Inverse


def names_map(d, cls):
    out = {}
    for e in FilteredElementCollector(d).OfClass(cls).ToElements():
        out[e.Name] = e
    return out


def grid_offset(hc, lc, t):
    """Worst offset between the host grid and the transformed link grid.
    Compares position only, not grid length. None = different shape."""
    if isinstance(hc, Arc) and isinstance(lc, Arc):
        c = flat(t.OfPoint(lc.Center))
        return max(c.DistanceTo(flat(hc.Center)), abs(hc.Radius - lc.Radius))
    if isinstance(hc, Line) and isinstance(lc, Line):
        a = flat(hc.GetEndPoint(0))
        d = flat(hc.GetEndPoint(1)).Subtract(a).Normalize()
        worst = 0.0
        for i in (0, 1):
            v = flat(t.OfPoint(lc.GetEndPoint(i))).Subtract(a)
            worst = max(worst, abs(v.X * d.Y - v.Y * d.X))
        return worst
    return None


def off_list(fails):
    parts = []
    for name, off in sorted(fails, key=lambda f: f[0])[:5]:
        parts.append("{0} {1}".format(name, "shape differs" if off is None else "off by " + fmt_mm(off)))
    more = "" if len(fails) <= 5 else ", +{0} more".format(len(fails) - 5)
    return ", ".join(parts) + more


def targets_for(inst, ld):
    """{position: Transform (link internal -> host internal)} that would put the link there."""
    out = {"Internal Origin": Transform.Identity}
    if ld is None:
        return out
    try:
        sh, sl = internal_to_shared(doc), internal_to_shared(ld)
        out["Shared Coordinates"] = sh.Inverse.Multiply(sl)
    except Exception:
        pass
    try:
        hp = BasePoint.GetProjectBasePoint(doc).Position
        lp = BasePoint.GetProjectBasePoint(ld).Position
        out["Base Point"] = Transform.CreateTranslation(hp.Subtract(lp))
    except Exception:
        pass
    return out


def same_place(a, b):
    return a.Origin.DistanceTo(b.Origin) <= TOL and abs(angle_diff(angle_of(a), angle_of(b))) <= ANG_TOL


def check_position(inst):
    """Status chips for one placed Revit link:
    [(kind, text)] for Shared Coordinates, Base Point, Internal Origin, Rotation, Grids, Levels,
    plus the positions it sits on now."""
    ld = inst.GetLinkDocument()
    t = inst.GetTotalTransform()
    rotation = angle_of(t)
    now = []
    chips = {}

    # grids and levels decide whether a mismatch is amber (geometry still lines up) or red
    grids = levels = None
    aligned = True
    if ld is not None:
        host_g, link_g = names_map(doc, Grid), names_map(ld, Grid)
        g_match, g_fail = 0, []
        for name, lg in link_g.items():
            hg = host_g.get(name)
            if hg is None:
                continue
            g_match += 1
            try:
                off = grid_offset(hg.Curve, lg.Curve, t)
            except Exception:
                off = None
            if off is None or off > TOL:
                g_fail.append((name, off))
        if g_match == 0:
            grids = ("na", "Grids: no grid names shared")
        elif not g_fail:
            grids = ("ok", "Grids: {0} of {0} matching".format(g_match))
        else:
            aligned = False
            grids = ("bad", "Grids: {0} of {1} matching ({2})".format(
                g_match - len(g_fail), g_match, off_list(g_fail)))

        host_l, link_l = names_map(doc, Level), names_map(ld, Level)
        l_match, l_fail = 0, []
        for name, ll in link_l.items():
            hl = host_l.get(name)
            if hl is None:
                continue
            l_match += 1
            z = t.OfPoint(XYZ(0, 0, ll.ProjectElevation)).Z
            diff = abs(z - hl.ProjectElevation)
            if diff > TOL:
                l_fail.append((name, diff))
        if l_match == 0:
            levels = ("na", "Levels: no level names shared")
        elif not l_fail:
            levels = ("ok", "Levels: {0} of {0} matching".format(l_match))
        else:
            aligned = False
            levels = ("bad", "Levels: {0} of {1} matching ({2})".format(
                l_match - len(l_fail), l_match, off_list(l_fail)))
    off_kind = "warn" if aligned else "bad"

    # Shared coordinates
    if ld is None:
        chips["Shared Coordinates"] = ("na", "Shared Coordinates: needs the link loaded")
    else:
        try:
            sh, sl = internal_to_shared(doc), internal_to_shared(ld)
            a = sh.OfPoint(t.OfPoint(XYZ.Zero))
            b = sl.OfPoint(XYZ.Zero)
            d = a.Subtract(b)
            va = sh.OfVector(t.OfVector(XYZ.BasisX))
            vb = sl.OfVector(XYZ.BasisX)
            ang = angle_diff(math.atan2(va.Y, va.X), math.atan2(vb.Y, vb.X))
            if d.GetLength() <= TOL and abs(ang) <= ANG_TOL:
                chips["Shared Coordinates"] = ("ok", u"Shared Coordinates: \u2713")
                now.append("Shared Coordinates")
            else:
                chips["Shared Coordinates"] = (off_kind, "Shared Coordinates: off by X {0}, Y {1}, Z {2}, rotation {3}"
                                               .format(fmt_signed_mm(d.X), fmt_signed_mm(d.Y), fmt_signed_mm(d.Z),
                                                       fmt_deg(ang)))
        except Exception as ex:
            chips["Shared Coordinates"] = ("na", "Shared Coordinates: couldn't compare ({0})".format(ex))

    # Base point
    if ld is None:
        chips["Base Point"] = ("na", "Base Point: needs the link loaded")
    else:
        try:
            hp = BasePoint.GetProjectBasePoint(doc).Position
            lp = t.OfPoint(BasePoint.GetProjectBasePoint(ld).Position)
            d = lp.Subtract(hp)
            if d.GetLength() <= TOL and abs(rotation) <= ANG_TOL:
                chips["Base Point"] = ("ok", u"Base Point: \u2713")
                now.append("Base Point")
            else:
                chips["Base Point"] = (off_kind, "Base Point: off by X {0}, Y {1}, Z {2}".format(
                    fmt_signed_mm(d.X), fmt_signed_mm(d.Y), fmt_signed_mm(d.Z)))
        except Exception as ex:
            chips["Base Point"] = ("na", "Base Point: couldn't compare ({0})".format(ex))

    # Internal origin
    o = t.Origin
    if o.GetLength() <= TOL and abs(rotation) <= ANG_TOL:
        chips["Internal Origin"] = ("ok", u"Internal Origin: \u2713")
        now.append("Internal Origin")
    else:
        chips["Internal Origin"] = (off_kind, "Internal Origin: off by X {0}, Y {1}, Z {2}".format(
            fmt_signed_mm(o.X), fmt_signed_mm(o.Y), fmt_signed_mm(o.Z)))

    rot_chip = ("ok" if abs(rotation) <= ANG_TOL else off_kind, "Rotation: " + fmt_deg(rotation))

    out = [chips["Shared Coordinates"], chips["Base Point"], chips["Internal Origin"], rot_chip]
    out.append(grids or ("na", "Grids: needs the link loaded"))
    out.append(levels or ("na", "Levels: needs the link loaded"))
    return out, now


def move_link(inst, target):
    """Rotate about Z and move so the instance transform equals target, then pin it.
    Call inside a transaction."""
    inst.Pinned = False
    turn = angle_diff(angle_of(target), angle_of(inst.GetTotalTransform()))
    if abs(turn) > 1e-9:
        ElementTransformUtils.RotateElement(doc, inst.Id, Line.CreateBound(XYZ.Zero, XYZ.BasisZ), turn)
    shift = target.Origin.Subtract(inst.GetTotalTransform().Origin)
    if shift.GetLength() > 1e-9:
        ElementTransformUtils.MoveElement(doc, inst.Id, shift)
    inst.Pinned = True


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------
def collect_worksets():
    if not doc.IsWorkshared:
        return []
    worksets = list(FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset))
    worksets.sort(key=lambda w: w.Name.lower())
    return worksets


def instances_by_type(instance_class):
    mapping = {}
    for inst in FilteredElementCollector(doc).OfClass(instance_class).ToElements():
        try:
            key = id_value(inst.GetTypeId())
        except Exception:
            continue
        mapping.setdefault(key, []).append(inst)
    return mapping


def collect_rows(workset_names):
    rows = []

    rvt_instances = instances_by_type(RevitLinkInstance)
    for link_type in FilteredElementCollector(doc).OfClass(RevitLinkType).ToElements():
        try:
            if link_type.IsNestedLink:
                continue
        except AttributeError:
            pass
        rows.append(build_row(link_type, "RVT", False,
                              rvt_instances.get(id_value(link_type.Id), []),
                              workset_names))

    cad_instances = instances_by_type(ImportInstance)
    for cad_type in FilteredElementCollector(doc).OfClass(CADLinkType).ToElements():
        kind = "DWG" if is_external_reference(cad_type) else "IMPORT"
        rows.append(build_row(cad_type, kind, True,
                              cad_instances.get(id_value(cad_type.Id), []),
                              workset_names))

    rows.sort(key=lambda r: (r["kind"], r["name"].lower()))
    return rows


def build_row(type_elem, kind, is_cad, instances, workset_names):
    current_id = id_value(type_elem.WorksetId)
    param = workset_param(type_elem)
    owner = other_user_owner(type_elem)

    locked_reason = ""
    if not doc.IsWorkshared:
        locked_reason = "not workshared"
    elif param is None:
        locked_reason = "no workset parameter"
    elif param.IsReadOnly:
        locked_reason = "workset is read-only"
    elif owner:
        locked_reason = "owned by " + owner

    room = None
    if not is_cad:
        rb = room_bounding_param(type_elem)
        if rb is not None and not rb.IsReadOnly and not owner:
            room = bool(rb.AsInteger())

    inst_rows = []
    for inst in sorted(instances, key=lambda i: id_value(i.Id)):
        inst_owner = other_user_owner(inst)
        entry = {"inst": inst, "pinned": bool(inst.Pinned), "owner": inst_owner,
                 "chips": None, "now": [], "target": None, "pin_box": None, "seg": {}}
        if not is_cad:
            try:
                entry["chips"], entry["now"] = check_position(inst)
            except Exception as ex:
                entry["chips"] = [("na", "Position: couldn't be checked ({0})".format(ex))]
        inst_rows.append(entry)

    return {
        "type_elem": type_elem,
        "kind": kind,
        "is_cad": is_cad,
        "name": element_name(type_elem),
        "status": link_status(type_elem, is_cad),
        "instances": inst_rows,
        "current_id": current_id,
        "current_name": workset_names.get(current_id, "<not on a workset>"),
        "locked_reason": locked_reason,
        "room": room,
        "room_box": None,
        "combo": None,
        "border": None,
        "dot": None,
    }


# ---------------------------------------------------------------------------
# XAML shell
# ---------------------------------------------------------------------------
XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Link Manager"
        Width="1180" Height="780"
        WindowStartupLocation="CenterScreen"
        Background="#161616"
        FontFamily="Segoe UI">
  <Window.Resources>


    <Style x:Key="DarkComboItem" TargetType="ComboBoxItem">
      <Setter Property="Background" Value="Transparent"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Padding" Value="8,5"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ComboBoxItem">
            <Border x:Name="Bd" Background="{TemplateBinding Background}"
                    Padding="{TemplateBinding Padding}" CornerRadius="3">
              <ContentPresenter/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsHighlighted" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#525252"/>
                <Setter Property="Foreground" Value="#F1C21B"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="DarkCombo" TargetType="ComboBox">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="Height" Value="26"/>
      <Setter Property="ItemContainerStyle" Value="{StaticResource DarkComboItem}"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ComboBox">
            <Grid>
              <ToggleButton x:Name="Toggle" Focusable="False" ClickMode="Press"
                            IsChecked="{Binding IsDropDownOpen, Mode=TwoWay,
                                        RelativeSource={RelativeSource TemplatedParent}}">
                <ToggleButton.Template>
                  <ControlTemplate TargetType="ToggleButton">
                    <Border x:Name="Bd" Background="#393939" BorderBrush="#525252"
                            BorderThickness="1" CornerRadius="4">
                      <Path x:Name="Arrow" HorizontalAlignment="Right" VerticalAlignment="Center"
                            Margin="0,0,9,0" Data="M 0 0 L 4 4 L 8 0 Z" Fill="#A8A8A8"/>
                    </Border>
                    <ControlTemplate.Triggers>
                      <Trigger Property="IsMouseOver" Value="True">
                        <Setter TargetName="Bd" Property="BorderBrush" Value="#F1C21B"/>
                      </Trigger>
                      <Trigger Property="IsEnabled" Value="False">
                        <Setter TargetName="Bd" Property="Background" Value="#262626"/>
                        <Setter TargetName="Arrow" Property="Fill" Value="#525252"/>
                      </Trigger>
                    </ControlTemplate.Triggers>
                  </ControlTemplate>
                </ToggleButton.Template>
              </ToggleButton>
              <ContentPresenter x:Name="ContentSite" IsHitTestVisible="False"
                                Content="{TemplateBinding SelectionBoxItem}"
                                ContentTemplate="{TemplateBinding SelectionBoxItemTemplate}"
                                Margin="9,0,26,0" VerticalAlignment="Center"/>
              <Popup x:Name="Popup" Placement="Bottom" AllowsTransparency="True"
                     Focusable="False" PopupAnimation="Slide"
                     IsOpen="{TemplateBinding IsDropDownOpen}">
                <Border Background="#262626" BorderBrush="#525252" BorderThickness="1"
                        CornerRadius="4" Margin="0,2,0,0" MaxHeight="280"
                        MinWidth="{TemplateBinding ActualWidth}">
                  <ScrollViewer SnapsToDevicePixels="True">
                    <StackPanel IsItemsHost="True" Margin="3"/>
                  </ScrollViewer>
                </Border>
              </Popup>
            </Grid>
            <ControlTemplate.Triggers>
              <Trigger Property="IsEnabled" Value="False">
                <Setter Property="Foreground" Value="#525252"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="FlatBtn" TargetType="Button">
      <Setter Property="Background" Value="#F1C21B"/>
      <Setter Property="Foreground" Value="#161616"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="Height" Value="30"/>
      <Setter Property="Padding" Value="18,0"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="Bd" Background="{TemplateBinding Background}" CornerRadius="5"
                    Padding="{TemplateBinding Padding}">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="Bd" Property="Opacity" Value="0.85"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="GhostBtn" TargetType="Button" BasedOn="{StaticResource FlatBtn}">
      <Setter Property="Background" Value="#525252"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
    </Style>

    <Style x:Key="HeaderCell" TargetType="TextBlock">
      <Setter Property="Foreground" Value="#A8A8A8"/>
      <Setter Property="FontSize" Value="11"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
      <Setter Property="Margin" Value="0,0,8,0"/>
    </Style>

  
    <Style x:Key="Seg" TargetType="ToggleButton">
      <Setter Property="Foreground" Value="#C6C6C6"/>
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="BorderBrush" Value="Transparent"/>
      <Setter Property="FontSize" Value="11"/>
      <Setter Property="Height" Value="24"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ToggleButton">
            <Border x:Name="Bd" Background="{TemplateBinding Background}"
                    BorderBrush="{TemplateBinding BorderBrush}" BorderThickness="0,0,0,2" Padding="8,0">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsChecked" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#F1C21B"/>
                <Setter Property="Foreground" Value="#161616"/>
              </Trigger>
              <Trigger Property="IsEnabled" Value="False">
                <Setter TargetName="Bd" Property="Opacity" Value="0.35"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style TargetType="CheckBox">
      <Setter Property="Foreground" Value="#A8A8A8"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="VerticalAlignment" Value="Center"/>
      <Setter Property="Cursor" Value="Hand"/>
    </Style>
  </Window.Resources>

  <Grid Margin="16">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <StackPanel Grid.Row="0" Margin="0,0,0,12">
      <TextBlock Text="LINK MANAGER" Foreground="#F1C21B" FontSize="16" FontWeight="Bold"/>
      <TextBlock x:Name="SubTitle" Foreground="#A8A8A8" FontSize="12" Margin="0,3,0,0"/>
    </StackPanel>

    <Border Grid.Row="1" Background="#262626" CornerRadius="6" Padding="10" Margin="0,0,0,10">
      <DockPanel>
        <Button x:Name="PinAllBtn" DockPanel.Dock="Right" Content="Pin all" Style="{StaticResource GhostBtn}"
                Height="26" Padding="14,0" Margin="8,0,0,0"/>
        <Button x:Name="RoomOnBtn" DockPanel.Dock="Right" Content="Room bounding on" Style="{StaticResource GhostBtn}"
                Height="26" Padding="14,0" Margin="8,0,0,0"/>
        <Button x:Name="BulkBtn" DockPanel.Dock="Right" Content="Apply" Style="{StaticResource GhostBtn}"
                Height="26" Padding="14,0" Margin="8,0,0,0"/>
        <ComboBox x:Name="BulkCombo" DockPanel.Dock="Right" Style="{StaticResource DarkCombo}" Width="190"/>
        <TextBlock DockPanel.Dock="Right" Text="Set all visible to" Foreground="#A8A8A8" FontSize="12"
                   VerticalAlignment="Center" Margin="16,0,8,0"/>
        <Grid>
          <Border Background="#393939" BorderBrush="#525252" BorderThickness="1" CornerRadius="4" Height="26">
            <TextBox x:Name="SearchBox" Background="Transparent" BorderThickness="0"
                     Foreground="#F4F4F4" CaretBrush="#F1C21B" FontSize="12"
                     VerticalContentAlignment="Center" Padding="8,0"/>
          </Border>
          <TextBlock x:Name="SearchHint" Text="Search links..." Foreground="#6F6F6F" FontSize="12"
                     Margin="10,0,0,0" VerticalAlignment="Center" IsHitTestVisible="False"/>
        </Grid>
      </DockPanel>
    </Border>

    <DockPanel x:Name="HeaderRow" Grid.Row="2" Margin="12,0,30,6"/>

    <ScrollViewer Grid.Row="3" VerticalScrollBarVisibility="Auto"
                  HorizontalScrollBarVisibility="Disabled">
      <StackPanel x:Name="RowsPanel"/>
    </ScrollViewer>

    <TextBlock Grid.Row="4" Foreground="#8D8D8D" FontSize="11" Margin="2,8,0,0" TextWrapping="Wrap"
               Text="Green underline = where the link sits now. Yellow = where it moves on Apply (it is pinned again after the move). Status colours: green matches, amber off but grids and levels still line up, red grids or levels don't line up, grey can't check."/>

    <Grid Grid.Row="5" Margin="0,12,0,0">
      <StackPanel Orientation="Horizontal" HorizontalAlignment="Left">
        <CheckBox x:Name="InstancesCheck" IsChecked="True"
                  Content="Also assign the link instances to the workset"/>
        <TextBlock x:Name="CountText" Foreground="#A8A8A8" FontSize="12"
                   VerticalAlignment="Center" Margin="20,0,0,0"/>
      </StackPanel>
      <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
        <Button x:Name="CancelBtn" Content="Close" Style="{StaticResource GhostBtn}"/>
        <Button x:Name="OkBtn" Content="Apply changes" Style="{StaticResource FlatBtn}"
                Margin="10,0,0,0"/>
      </StackPanel>
    </Grid>

  </Grid>
</Window>
"""


# ---------------------------------------------------------------------------
# Row builders
# ---------------------------------------------------------------------------
def text_block(text, size=12, color=C_TEXT, bold=False):
    block = TextBlock()
    block.Text = text
    block.FontSize = size
    block.Foreground = brush(color)
    block.VerticalAlignment = VerticalAlignment.Center
    block.TextTrimming = TextTrimming.CharacterEllipsis
    if bold:
        block.FontWeight = FontWeights.SemiBold
    return block


def fixed(child, width, center=True):
    """A fixed-width cell for the right side of a row."""
    holder = Border()
    holder.Width = width
    holder.Margin = Thickness(8, 0, 0, 0)
    holder.VerticalAlignment = VerticalAlignment.Center
    if child is not None:
        if center:
            try:
                child.HorizontalAlignment = HorizontalAlignment.Center
            except Exception:
                pass
        holder.Child = child
    return holder


def make_header(window):
    header = window.FindName("HeaderRow")
    style = window.Resources["HeaderCell"]
    cells = []
    for text, width in (("POSITION: MOVE TO", W_POS), ("PINNED", W_PIN), ("ROOM BOUNDING", W_ROOM),
                        ("WORKSET", W_WORKSET)):
        block = TextBlock()
        block.Text = text
        block.Style = style
        cell = fixed(block, width, center=(width in (W_PIN, W_ROOM)))
        DockPanel.SetDock(cell, Dock.Right)
        header.Children.Add(cell)
    name = TextBlock()
    name.Text = "LINK"
    name.Style = style
    header.Children.Add(name)


def chip(kind, text):
    bg, fg = CHIP[kind]
    b = Border()
    b.Background = brush(bg)
    b.CornerRadius = CornerRadius(6)
    b.Padding = Thickness(8, 1, 8, 2)
    b.Margin = Thickness(0, 0, 6, 4)
    t = TextBlock()
    t.Text = text
    t.FontSize = 11
    t.Foreground = brush(fg)
    b.Child = t
    return b


def chips_panel(entry):
    wrap = WrapPanel()
    wrap.Margin = Thickness(0, 8, 0, 0)
    for kind, text in entry["chips"] or []:
        wrap.Children.Add(chip(kind, text))
    return wrap


class RowUi(object):
    """Builds one link's card and keeps track of what changed."""

    def __init__(self, window, row, workset_list, on_change):
        self.window = window
        self.row = row
        self.worksets = workset_list
        self.on_change = on_change

    def changed(self):
        row = self.row
        if row["combo"] is not None and row["combo"].IsEnabled and row["combo"].SelectedIndex >= 0:
            picked = self.worksets[row["combo"].SelectedIndex]
            if id_value(picked.Id) != row["current_id"]:
                return True
        if row["room_box"] is not None and bool(row["room_box"].IsChecked) != row["room"]:
            return True
        for entry in row["instances"]:
            if entry["target"]:
                return True
            if entry["pin_box"] is not None and bool(entry["pin_box"].IsChecked) != entry["pinned"]:
                return True
        return False

    def refresh(self):
        self.row["dot"].Visibility = Visibility.Visible if self.changed() else Visibility.Hidden

    def _changed_handler(self, sender, args):
        self.refresh()
        self.on_change()

    def _seg_handler(self, entry, name):
        def handler(sender, args):
            button = entry["seg"][name]
            if button.IsChecked:
                for other, b in entry["seg"].items():
                    if other != name:
                        b.IsChecked = False
                entry["target"] = name if name not in entry["now"] else None
                if entry["target"] is None:
                    button.IsChecked = False   # already there: nothing to move
            else:
                entry["target"] = None
            self.refresh()
            self.on_change()
        return handler

    def _position_cell(self, entry):
        if self.row["is_cad"]:
            return fixed(text_block("Revit links only", 11, C_MUTED), W_POS, center=False)
        outer = Border()
        outer.BorderBrush = brush("#525252")
        outer.BorderThickness = Thickness(1)
        outer.CornerRadius = CornerRadius(6)
        outer.HorizontalAlignment = HorizontalAlignment.Left
        panel = StackPanel()
        panel.Orientation = Orientation.Horizontal
        loaded = entry["inst"].GetLinkDocument() is not None
        for name in POSITIONS:
            b = ToggleButton()
            b.Style = self.window.Resources["Seg"]
            b.Content = SEG_LABEL[name]
            if name in entry["now"]:
                b.BorderBrush = brush("#A7F0BA")
                b.Foreground = brush(C_TEXT)
                b.ToolTip = "The link sits here now"
            else:
                b.ToolTip = "Move the link here on Apply"
            if entry["owner"]:
                b.IsEnabled = False
                b.ToolTip = "Owned by " + entry["owner"]
            elif not loaded and name != "Internal Origin":
                b.IsEnabled = False
                b.ToolTip = "Load the link to move it here"
            b.Click += RoutedEventHandler(self._seg_handler(entry, name))
            entry["seg"][name] = b
            panel.Children.Add(b)
        outer.Child = panel
        return fixed(outer, W_POS, center=False)

    def _pin_cell(self, entry):
        box = CheckBox()
        box.IsChecked = entry["pinned"]
        if entry["owner"]:
            box.IsEnabled = False
            box.ToolTip = "Owned by " + entry["owner"]
        box.Click += RoutedEventHandler(self._changed_handler)
        entry["pin_box"] = box
        return fixed(box, W_PIN)

    def _room_cell(self):
        row = self.row
        if row["is_cad"]:
            return fixed(None, W_ROOM)
        box = CheckBox()
        if row["room"] is None:
            box.IsEnabled = False
            box.ToolTip = "Room Bounding can't be changed on this link"
        else:
            box.IsChecked = row["room"]
            box.ToolTip = "Room Bounding (a link type setting: all its placed copies)"
        box.Click += RoutedEventHandler(self._changed_handler)
        row["room_box"] = box if row["room"] is not None else None
        return fixed(box, W_ROOM)

    def _workset_cell(self):
        row = self.row
        combo = ComboBox()
        combo.Style = self.window.Resources["DarkCombo"]
        combo.Width = W_WORKSET
        if not self.worksets:
            combo.Items.Add("Not workshared")
            combo.SelectedIndex = 0
            combo.IsEnabled = False
        else:
            for workset in self.worksets:
                combo.Items.Add(workset.Name)
            index = [id_value(w.Id) for w in self.worksets].index(row["current_id"]) \
                if row["current_id"] in [id_value(w.Id) for w in self.worksets] else -1
            combo.SelectedIndex = index
            if row["locked_reason"]:
                combo.IsEnabled = False
                combo.ToolTip = "Cannot be reassigned: " + row["locked_reason"]
        combo.SelectionChanged += self._changed_handler
        row["combo"] = combo
        return fixed(combo, W_WORKSET, center=False)

    def build(self):
        row = self.row
        border = Border()
        border.Background = brush("#262626")
        border.CornerRadius = CornerRadius(6)
        border.Padding = Thickness(12, 9, 12, 9)
        border.Margin = Thickness(0, 0, 0, 6)
        stack = StackPanel()

        instances = row["instances"]
        first = instances[0] if instances else None

        top = DockPanel()
        if first is not None:
            pos = self._position_cell(first)
            pin = self._pin_cell(first)
        else:
            pos = fixed(text_block("Not placed", 11, C_MUTED), W_POS, center=False)
            pin = fixed(None, W_PIN)
        for cell in (pos, pin, self._room_cell(), self._workset_cell()):
            DockPanel.SetDock(cell, Dock.Right)
            top.Children.Add(cell)

        info = StackPanel()
        info.VerticalAlignment = VerticalAlignment.Center
        title = StackPanel()
        title.Orientation = Orientation.Horizontal
        title.Children.Add(text_block(row["name"], 13, C_TEXT, bold=True))
        status = text_block(u"  {0}".format(row["status"]), 11, STATUS_COLOR.get(row["status"], C_SUBTEXT))
        title.Children.Add(status)
        dot = Ellipse()
        dot.Width = 7
        dot.Height = 7
        dot.Fill = brush(C_ACCENT)
        dot.Margin = Thickness(8, 0, 0, 0)
        dot.VerticalAlignment = VerticalAlignment.Center
        dot.Visibility = Visibility.Hidden
        dot.ToolTip = "Changed: applied when you click Apply changes"
        row["dot"] = dot
        title.Children.Add(dot)
        info.Children.Add(title)
        kind = {"RVT": "Revit link", "DWG": "CAD link", "IMPORT": "CAD import"}[row["kind"]]
        count = len(instances)
        if count == 0:
            sub = kind + u"  \u00b7  not placed"
        elif count == 1:
            sub = kind + u"  \u00b7  1 instance"
        else:
            sub = u"{0}  \u00b7  instance 1 of {1}".format(kind, count)
        if row["locked_reason"] and row["locked_reason"] != "not workshared":
            sub += u"  \u00b7  workset " + row["locked_reason"]
        info.Children.Add(text_block(sub, 11, C_SUBTEXT))
        top.Children.Add(info)
        stack.Children.Add(top)
        if first is not None and first["chips"]:
            stack.Children.Add(chips_panel(first))

        for n, entry in enumerate(instances[1:], 2):
            line = Border()
            line.BorderBrush = brush("#393939")
            line.BorderThickness = Thickness(0, 1, 0, 0)
            line.Margin = Thickness(0, 8, 0, 0)
            line.Padding = Thickness(0, 8, 0, 0)
            sub_stack = StackPanel()
            sub_row = DockPanel()
            for cell in (self._position_cell(entry), self._pin_cell(entry), fixed(None, W_ROOM),
                         fixed(None, W_WORKSET)):
                DockPanel.SetDock(cell, Dock.Right)
                sub_row.Children.Add(cell)
            sub_row.Children.Add(text_block(
                u"instance {0} of {1}  \u00b7  same workset and room bounding as instance 1".format(n, count),
                11, C_SUBTEXT))
            sub_stack.Children.Add(sub_row)
            if entry["chips"]:
                sub_stack.Children.Add(chips_panel(entry))
            line.Child = sub_stack
            stack.Children.Add(line)

        border.Child = stack
        row["border"] = border
        return border


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------
def apply_changes(rows, row_uis, worksets, include_instances):
    """Worksets, Room Bounding, moves (pinned afterwards) and pins - one transaction, one Undo."""
    plan = []
    checkout = List[ElementId]()
    for row in rows:
        combo = row["combo"]
        workset = None
        if worksets and combo is not None and combo.IsEnabled and combo.SelectedIndex >= 0:
            picked = worksets[combo.SelectedIndex]
            if id_value(picked.Id) != row["current_id"]:
                workset = picked
        room = None
        if row["room_box"] is not None and bool(row["room_box"].IsChecked) != row["room"]:
            room = bool(row["room_box"].IsChecked)
        inst_plan = []
        for entry in row["instances"]:
            pin = None
            if entry["pin_box"] is not None and bool(entry["pin_box"].IsChecked) != entry["pinned"]:
                pin = bool(entry["pin_box"].IsChecked)
            if entry["target"] or pin is not None:
                inst_plan.append((entry, entry["target"], pin))
        if workset is None and room is None and not inst_plan:
            continue
        plan.append((row, workset, room, inst_plan))
        if doc.IsWorkshared:
            checkout.Add(row["type_elem"].Id)
            for entry in row["instances"]:
                checkout.Add(entry["inst"].Id)

    if not plan:
        return None

    # Checkout must happen outside of a transaction
    if doc.IsWorkshared and checkout.Count:
        try:
            WorksharingUtils.CheckoutElements(doc, checkout)
        except Exception:
            pass

    done = {"worksets": 0, "room": 0, "moved": 0, "pins": 0}
    failures = []

    group = TransactionGroup(doc, TOOL)
    group.Start()
    transaction = Transaction(doc, TOOL)
    transaction.Start()
    try:
        for row, workset, room, inst_plan in plan:
            if workset is not None:
                target_id = id_value(workset.Id)
                elements = [row["type_elem"]]
                if include_instances:
                    elements = elements + [e["inst"] for e in row["instances"]]
                for element in elements:
                    param = workset_param(element)
                    if param is None or param.IsReadOnly or id_value(element.WorksetId) == target_id:
                        continue
                    try:
                        param.Set(target_id)
                        done["worksets"] += 1
                    except Exception as err:
                        failures.append(u"{0}: workset {1} - {2}".format(row["name"], workset.Name, err))
            if room is not None:
                try:
                    room_bounding_param(row["type_elem"]).Set(1 if room else 0)
                    done["room"] += 1
                except Exception as err:
                    failures.append(u"{0}: Room Bounding - {1}".format(row["name"], err))
            for entry, target_name, pin in inst_plan:
                inst = entry["inst"]
                if target_name:
                    target = targets_for(inst, inst.GetLinkDocument()).get(target_name)
                    if target is None:
                        failures.append(u"{0}: can't work out {1} (load the link)".format(row["name"], target_name))
                    else:
                        try:
                            move_link(inst, target)
                            done["moved"] += 1
                        except Exception as err:
                            failures.append(u"{0}: move to {1} - {2}".format(row["name"], target_name, err))
                        continue   # a moved link is pinned again
                if pin is not None:
                    try:
                        inst.Pinned = pin
                        done["pins"] += 1
                    except Exception as err:
                        failures.append(u"{0}: pin - {1}".format(row["name"], err))
        transaction.Commit()
        group.Assimilate()
    except Exception:
        if transaction.HasStarted() and not transaction.HasEnded():
            transaction.RollBack()
        if group.HasStarted() and not group.HasEnded():
            group.RollBack()
        raise
    return done, failures


def report(done, failures):
    lines = ["Workset changes: {0}".format(done["worksets"]),
             "Room Bounding changes: {0}".format(done["room"]),
             "Links moved (and pinned): {0}".format(done["moved"]),
             "Pin changes: {0}".format(done["pins"])]
    if failures:
        lines.append("")
        lines.append("Failed ({0}):".format(len(failures)))
        lines.extend(failures[:15])
        if len(failures) > 15:
            lines.append("... and {0} more".format(len(failures) - 15))
    dialog = TaskDialog(TOOL)
    dialog.MainInstruction = "Done - one Undo puts it all back"
    dialog.MainContent = "\n".join(lines)
    dialog.Show()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    workset_list = collect_worksets()
    workset_names = {}
    for workset in workset_list:
        workset_names[id_value(workset.Id)] = workset.Name

    rows = collect_rows(workset_names)
    if not rows:
        TaskDialog.Show(TOOL, "No Revit or CAD links were found in this project.")
        return

    window = XamlReader.Parse(XAML)
    try:
        WindowInteropHelper(window).Owner = __revit__.MainWindowHandle  # noqa: F821
    except Exception:
        pass
    rows_panel = window.FindName("RowsPanel")
    search_box = window.FindName("SearchBox")
    search_hint = window.FindName("SearchHint")
    bulk_combo = window.FindName("BulkCombo")
    bulk_btn = window.FindName("BulkBtn")
    room_btn = window.FindName("RoomOnBtn")
    pin_btn = window.FindName("PinAllBtn")
    instances_check = window.FindName("InstancesCheck")
    count_text = window.FindName("CountText")
    ok_btn = window.FindName("OkBtn")
    cancel_btn = window.FindName("CancelBtn")

    rvt = len([r for r in rows if r["kind"] == "RVT"])
    window.FindName("SubTitle").Text = u"{0}  \u00b7  {1}, {2}  \u00b7  Change what you need, then click Apply changes.".format(
        doc.Title, plural(rvt, "Revit link"), plural(len(rows) - rvt, "CAD link"))

    make_header(window)
    row_uis = []

    def update_count():
        visible = len([r for r in rows if r["border"].Visibility == Visibility.Visible])
        changed = len([u for u in row_uis if u.changed()])
        text = "Showing {0} of {1} links".format(visible, len(rows))
        if changed:
            text += u"  \u00b7  {0} changed - nothing is applied until you click Apply changes".format(changed)
        count_text.Text = text
        ok_btn.Content = "Apply changes ({0})".format(changed) if changed else "Apply changes"

    for row in rows:
        ui = RowUi(window, row, workset_list, update_count)
        rows_panel.Children.Add(ui.build())
        row_uis.append(ui)

    if workset_list:
        for workset in workset_list:
            bulk_combo.Items.Add(workset.Name)
        bulk_combo.SelectedIndex = 0
    else:
        bulk_combo.Items.Add("Not workshared")
        bulk_combo.SelectedIndex = 0
        bulk_combo.IsEnabled = False
        bulk_btn.IsEnabled = False
        instances_check.IsEnabled = False

    update_count()
    result = [False]
    include_instances = [True]

    def visible_rows():
        return [r for r in rows if r["border"].Visibility == Visibility.Visible]

    def refresh_all():
        for ui in row_uis:
            ui.refresh()
        update_count()

    def on_search(sender, args):
        needle = (search_box.Text or "").strip().lower()
        search_hint.Visibility = Visibility.Collapsed if needle else Visibility.Visible
        for row in rows:
            haystack = " ".join([row["name"], row["kind"], row["status"], row["current_name"]]).lower()
            match = (not needle) or (needle in haystack)
            row["border"].Visibility = Visibility.Visible if match else Visibility.Collapsed
        update_count()

    def on_bulk(sender, args):
        index = bulk_combo.SelectedIndex
        if index < 0 or not workset_list:
            return
        for row in visible_rows():
            if row["combo"].IsEnabled:
                row["combo"].SelectedIndex = index
        refresh_all()

    def on_room(sender, args):
        for row in visible_rows():
            if row["room_box"] is not None and row["room_box"].IsEnabled:
                row["room_box"].IsChecked = True
        refresh_all()

    def on_pin(sender, args):
        for row in visible_rows():
            for entry in row["instances"]:
                if entry["pin_box"] is not None and entry["pin_box"].IsEnabled:
                    entry["pin_box"].IsChecked = True
        refresh_all()

    def on_ok(sender, args):
        if not any(u.changed() for u in row_uis):
            TaskDialog.Show(TOOL, "Nothing has changed yet. Change a workset, a tick box or a position first.")
            return
        include_instances[0] = bool(instances_check.IsChecked)
        result[0] = True
        window.Close()

    def on_cancel(sender, args):
        result[0] = False
        window.Close()

    search_box.TextChanged += TextChangedEventHandler(on_search)
    bulk_btn.Click += RoutedEventHandler(on_bulk)
    room_btn.Click += RoutedEventHandler(on_room)
    pin_btn.Click += RoutedEventHandler(on_pin)
    ok_btn.Click += RoutedEventHandler(on_ok)
    cancel_btn.Click += RoutedEventHandler(on_cancel)

    frame = DispatcherFrame()

    def on_closed(sender, args):
        frame.Continue = False

    window.Closed += EventHandler(on_closed)
    enable_combo_search(window)
    window.Show()
    Dispatcher.PushFrame(frame)

    if not result[0]:
        return

    outcome = apply_changes(rows, row_uis, workset_list, include_instances[0])
    if outcome is None:
        return
    report(outcome[0], outcome[1])


main()

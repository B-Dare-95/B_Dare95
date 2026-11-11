# -*- coding: utf-8 -*-
__doc__ = """__________________________________________________
Description:

Tidies your views in one go. Grid Align, Level Align and Label Align in one window:
- Grids: choose which sides show grid bubbles and line up grid ends at a set distance from the crop region.
- Levels (sections and elevations): choose which sides show level heads and line up level ends past the crop region, or past the outermost grids when the view isn't cropped. The levels' 3D extents never move.
- Viewport titles (on sheets): move each title just under the bottom-left corner of its viewport and trim the title line to fit the text.
Only the chosen views and viewports change. Works on the active view, active sheet, selected views or viewports, or sheets you pick.
__________________________________________________
How-to:

-> Select viewports or views first if you want to work on just those
-> Click on the button
-> Choose: active view, active sheet, selected views or picked sheets
-> Check Grids, Levels and / or Viewport titles, and set their options
-> Check the preview next to each section and click Apply
-> A summary shows what was updated and what was skipped
__________________________________________________
Author: Mohamed Bedair"""

import clr
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from System import EventHandler
from System.Windows import (FontWeights, RoutedEventHandler, Size, TextAlignment, Thickness,
                            TextTrimming, VerticalAlignment, Visibility)
from System.Windows.Markup import XamlReader
from System.Windows.Controls import (Canvas, CheckBox, Orientation, StackPanel, TextBlock,
                                     TextChangedEventHandler)
from System.Windows.Media import ColorConverter, DoubleCollection, SolidColorBrush
from System.Windows.Shapes import Ellipse, Line as WLine, Rectangle
from System.Windows.Threading import Dispatcher, DispatcherFrame
from System.Windows.Interop import WindowInteropHelper

from Autodesk.Revit.DB import (BuiltInCategory, BuiltInParameter, DatumEnds, DatumExtentType,
                               ElementId, FilteredElementCollector, Grid, Level,
                               MultiSegmentGrid, SubTransaction, Transaction, View, ViewSheet,
                               ViewType, Viewport, ViewportRotation, XYZ)
from Autodesk.Revit.DB import Line as DBLine
from Autodesk.Revit.UI import TaskDialog, TaskDialogCommonButtons

from pyrevit import revit, script
import bd_core as bd

doc = revit.doc
uidoc = revit.uidoc
cfg = script.get_config()

TITLE = "Tidy Views"
MM = 1.0 / 304.8                      # mm -> feet
ENDS = (DatumEnds.End0, DatumEnds.End1)
VS = DatumExtentType.ViewSpecific
MODEL = DatumExtentType.Model
GRID_SIDES = ("t", "b", "l", "r")
LEVEL_SIDES = ("l", "r")
SAME = 1e-6                           # feet: two points closer than this are the same
MAX_LISTED = 30
SHORT_LINE = 1.0 * MM                 # paper: a title line shorter than any text
ROT_NONE = getattr(ViewportRotation, "None")     # "None" is a keyword in Python 3 linters

GRID_VIEW_TYPES = (ViewType.FloorPlan, ViewType.CeilingPlan, ViewType.EngineeringPlan,
                   ViewType.AreaPlan, ViewType.Section, ViewType.Elevation, ViewType.Detail)
LEVEL_VIEW_TYPES = (ViewType.Section, ViewType.Elevation)


# =========================================================================
#  Shared helpers
# =========================================================================
id_val = bd.eid_int


def view_frame(view):
    return (view.Origin, view.RightDirection, view.UpDirection)


def crop_extents(view, frame):
    """(umin, umax, vmin, vmax) of the crop in view right / up coordinates."""
    o, r, u = frame
    pts = []
    try:
        for loop in view.GetCropRegionShapeManager().GetCropShape():
            for c in loop:
                pts.append(c.GetEndPoint(0))
                pts.append(c.GetEndPoint(1))
    except Exception:
        pts = []
    if not pts:
        bb = view.CropBox
        tf = bb.Transform
        for x in (bb.Min.X, bb.Max.X):
            for y in (bb.Min.Y, bb.Max.Y):
                pts.append(tf.OfPoint(XYZ(x, y, bb.Min.Z)))
    us = [p.Subtract(o).DotProduct(r) for p in pts]
    vs = [p.Subtract(o).DotProduct(u) for p in pts]
    return (min(us), max(us), min(vs), max(vs))


def view_curve(datum, view):
    """The datum's line as drawn in the view (2D extent first, then 3D)."""
    for et in (VS, MODEL):
        try:
            cs = datum.GetCurvesInView(et, view)
            if cs is not None and cs.Count > 0:
                return cs[0]
        except Exception:
            pass
    return None


def make_2d(datum, end, view):
    if datum.GetDatumExtentTypeInView(end, view) != VS:
        datum.SetDatumExtentType(end, view, VS)


def has_leader(datum, end, view):
    try:
        return datum.GetLeader(end, view) is not None
    except Exception:
        return False


def set_heads(datum, view, sides, wanted):
    """Show / hide the bubble (grid) or head (level) at each end. True when changed."""
    changed = False
    for end, side in zip(ENDS, sides):
        want = wanted[side]
        if bool(datum.IsBubbleVisibleInView(end, view)) == want:
            continue
        make_2d(datum, end, view)   # keeps the change in this view only
        if want:
            datum.ShowBubbleInView(end, view)
        else:
            datum.HideBubbleInView(end, view)
        changed = True
    return changed


def sheet_views(sheet):
    out = []
    for vid in sheet.GetAllPlacedViews():
        v = doc.GetElement(vid)
        if v is not None:
            out.append(v)
    return out


def sheet_viewports(sheet):
    out = []
    for vid in sheet.GetAllViewports():
        vp = doc.GetElement(vid)
        if vp is not None:
            out.append(vp)
    return out


# =========================================================================
#  Grids  (from Grid Align)
# =========================================================================
def grid_view_issue(v):
    """None, or (kind, message): 'type' = never shows grids (ignored quietly),
    'crop' = could show grids but its crop region is off (reported)."""
    if v is None or v.IsTemplate:
        return ("type", u"not a usable view")
    if v.ViewType not in GRID_VIEW_TYPES:
        return ("type", u"{0} views can't show grids".format(v.ViewType))
    if not v.CropBoxActive:
        return ("crop", u"grids: crop region is off")
    return None


def multi_segment_ids():
    ids = set()
    for msg in FilteredElementCollector(doc).OfClass(MultiSegmentGrid):
        try:
            for gid in msg.GetGridIds():
                ids.add(id_val(gid))
        except Exception:
            pass
    return ids


def grid_end_sides(p0, p1, frame):
    """View side of (End0, End1): 't'/'b' for grids running mostly up-down on
    screen, 'l'/'r' for grids running mostly left-right."""
    o, r, u = frame
    d = p1.Subtract(p0)
    du = d.DotProduct(r)
    dv = d.DotProduct(u)
    if abs(du) < 1e-6 and abs(dv) < 1e-6:
        return None
    if abs(dv) >= abs(du):
        return ("b", "t") if dv > 0 else ("t", "b")
    return ("l", "r") if du > 0 else ("r", "l")


def grid_end_target(p0, d, side, frame, ext, off):
    """Point on the grid line where it meets crop edge + offset."""
    o, r, u = frame
    rel = p0.Subtract(o)
    if side in ("t", "b"):
        cur, comp = rel.DotProduct(u), d.DotProduct(u)
        goal = ext[3] + off["t"] if side == "t" else ext[2] - off["b"]
    else:
        cur, comp = rel.DotProduct(r), d.DotProduct(r)
        goal = ext[0] - off["l"] if side == "l" else ext[1] + off["r"]
    return p0.Add(d.Multiply((goal - cur) / comp))


def align_grid(g, view, frame, ext, off, note):
    for end in ENDS:
        make_2d(g, end, view)
    c = g.GetCurvesInView(VS, view)[0]
    p0, p1 = c.GetEndPoint(0), c.GetEndPoint(1)
    sides = grid_end_sides(p0, p1, frame)
    if sides is None:
        return False
    d = p1.Subtract(p0).Normalize()
    pts = [p0, p1]
    for i in (0, 1):
        if has_leader(g, ENDS[i], view):
            note(u"end with a leader left in place")
            continue
        pts[i] = grid_end_target(p0, d, sides[i], frame, ext, off)
    q0, q1 = pts
    if q1.Subtract(q0).DotProduct(d) < 0.01:
        note(u"offsets would collapse the grid - not aligned")
        return False
    if q0.IsAlmostEqualTo(p0) and q1.IsAlmostEqualTo(p1):
        return False
    new = DBLine.CreateBound(q0, q1)
    if not g.IsCurveValidInView(VS, view, new):
        note(u"Revit rejected the new extents")
        return False
    g.SetCurveInView(VS, view, new)
    return True


def tidy_grids(view, where, opts, multiseg, report):
    """Grids of one view. Returns the number of grids changed."""
    frame = view_frame(view)
    ext = crop_extents(view, frame)
    grids = [e for e in FilteredElementCollector(doc, view.Id).OfCategory(BuiltInCategory.OST_Grids)
             .WhereElementIsNotElementType() if isinstance(e, Grid)]
    updated = 0
    for g in grids:
        tag = u"{0}  |  grid {1}".format(where, g.Name)

        def note(msg, tag=tag):
            report.append(u"{0}  -  {1}".format(tag, msg))

        if id_val(g.Id) in multiseg:
            note(u"multi-segment grid - skipped")
            continue
        try:
            c = view_curve(g, view)
            if c is None:
                note(u"no curve in this view")
                continue
            sides = grid_end_sides(c.GetEndPoint(0), c.GetEndPoint(1), frame)
            if sides is None:
                continue        # seen end-on in this view: nothing to tidy
            changed = False
            if opts["align"]:
                if g.IsCurved:
                    note(u"curved grid - ends not aligned")
                else:
                    changed = align_grid(g, view, frame, ext, opts["off"], note) or changed
            if opts["bubbles"]:
                changed = set_heads(g, view, sides, opts["bub"]) or changed
            if changed:
                updated += 1
        except Exception as ex:
            note(u"failed: {0}".format(ex))
    return updated


# =========================================================================
#  Levels  (from Level Align)
# =========================================================================
def level_view_ok(v):
    return v is not None and not v.IsTemplate and v.ViewType in LEVEL_VIEW_TYPES


def scope_box_name(level):
    """Name of the scope box controlling the level's extents, or None."""
    try:
        p = level.get_Parameter(BuiltInParameter.DATUM_VOLUME_OF_INTEREST)
        eid = p.AsElementId() if p is not None else None
    except Exception:
        return None
    if eid is None or eid == ElementId.InvalidElementId:
        return None
    box = doc.GetElement(eid)
    return box.Name if box is not None else u"a scope box"


def grid_extents(view, frame):
    """(umin, umax) of the outermost grids showing in a section / elevation, or
    None. There a grid shows as an up-down line, one position across the view."""
    o, r, u = frame
    us = []
    for g in FilteredElementCollector(doc, view.Id).OfClass(Grid):
        c = view_curve(g, view)
        if c is None:
            continue
        p0, p1 = c.GetEndPoint(0), c.GetEndPoint(1)
        d = p1.Subtract(p0)
        if abs(d.DotProduct(u)) < abs(d.DotProduct(r)):
            continue
        us.append(p0.Subtract(o).DotProduct(r))
        us.append(p1.Subtract(o).DotProduct(r))
    return (min(us), max(us)) if us else None


def level_end_sides(p0, p1, frame):
    """View side ('l'/'r') of (End0, End1), or None when the level does not run
    left-right on screen."""
    o, r, u = frame
    d = p1.Subtract(p0)
    du = d.DotProduct(r)
    dv = d.DotProduct(u)
    if abs(du) < 1e-6 or abs(dv) > abs(du):
        return None
    return ("l", "r") if du > 0 else ("r", "l")


def point_at_u(p0, d, goal, frame):
    """Point on the level line whose view-right coordinate is goal (Z unchanged)."""
    o, r, u = frame
    cur = p0.Subtract(o).DotProduct(r)
    return p0.Add(d.Multiply((goal - cur) / d.DotProduct(r)))


def model_ends(lv, view):
    """(End0, End1) of the level's 3D extent as seen in the view, or None."""
    try:
        cs = lv.GetCurvesInView(MODEL, view)
        if cs is not None and cs.Count > 0:
            return (cs[0].GetEndPoint(0), cs[0].GetEndPoint(1))
    except Exception:
        pass
    return None


def moved(before, after):
    if before is None or after is None:
        return before is not after
    return any(before[i].DistanceTo(after[i]) > SAME for i in (0, 1))


def view_levels(view, frame):
    out = []
    for e in FilteredElementCollector(doc, view.Id).OfCategory(BuiltInCategory.OST_Levels) \
            .WhereElementIsNotElementType():
        if not isinstance(e, Level):
            continue
        c = view_curve(e, view)
        if c is None or level_end_sides(c.GetEndPoint(0), c.GetEndPoint(1), frame) is None:
            continue
        out.append(e)
    return out


def align_level(lv, view, frame, goals, note):
    """Move the level's 2D ends to goals {'l': u, 'r': u}. True when changed."""
    c = view_curve(lv, view)
    p0, p1 = c.GetEndPoint(0), c.GetEndPoint(1)
    sides = level_end_sides(p0, p1, frame)
    if sides is None:
        return False
    d = p1.Subtract(p0).Normalize()
    pts = [p0, p1]
    for i in (0, 1):
        if has_leader(lv, ENDS[i], view):
            note(u"end with an elbow left in place")
            continue
        pts[i] = point_at_u(p0, d, goals[sides[i]], frame)
    q0, q1 = pts
    if q1.Subtract(q0).DotProduct(d) < 0.01:
        note(u"offsets would collapse the level - not aligned")
        return False
    if q0.DistanceTo(p0) <= SAME and q1.DistanceTo(p1) <= SAME:
        return False
    for end in ENDS:
        make_2d(lv, end, view)      # 2D first: the 3D extent is never edited
    new = DBLine.CreateBound(q0, q1)
    if not lv.IsCurveValidInView(VS, view, new):
        note(u"Revit rejected the new extents")
        return False
    lv.SetCurveInView(VS, view, new)
    return True


def tidy_levels(view, where, opts, report):
    """Levels of one section / elevation. Returns the number of levels changed."""
    frame = view_frame(view)
    goals = None
    if opts["align"]:
        if view.CropBoxActive:
            ext = crop_extents(view, frame)
        else:
            ext = grid_extents(view, frame)
            if ext is None:
                report.append(u"{0}  -  levels: not cropped and no grids show in it - ends not "
                              u"aligned".format(where))
        if ext is not None:
            goals = {"l": ext[0] - opts["off"]["l"], "r": ext[1] + opts["off"]["r"]}

    updated = 0
    for lv in view_levels(view, frame):
        tag = u"{0}  |  level {1}".format(where, lv.Name)

        def note(msg, tag=tag):
            report.append(u"{0}  -  {1}".format(tag, msg))

        box = scope_box_name(lv)
        if box:
            note(u"extents follow scope box \u201c{0}\u201d - skipped".format(box))
            continue
        st = SubTransaction(doc)
        st.Start()
        try:
            before = model_ends(lv, view)
            changed = False
            if goals is not None:
                changed = align_level(lv, view, frame, goals, note) or changed
            if opts["heads"]:
                c = view_curve(lv, view)
                sides = level_end_sides(c.GetEndPoint(0), c.GetEndPoint(1), frame)
                if sides is not None:
                    changed = set_heads(lv, view, sides, opts["head"]) or changed
            if not changed:
                st.RollBack()
                continue
            doc.Regenerate()
            if moved(before, model_ends(lv, view)):
                st.RollBack()
                note(u"its 3D extent would have moved - left as it was")
                continue
            st.Commit()
            updated += 1
        except Exception as ex:
            if st.HasStarted() and not st.HasEnded():
                st.RollBack()
            note(u"failed: {0}".format(ex))
    return updated


# =========================================================================
#  Viewport titles  (from Label Align)
# =========================================================================
def outline_ok(o):
    if o is None:
        return False
    try:
        if o.IsEmpty:
            return False
    except Exception:
        pass
    return (o.MaximumPoint.X - o.MinimumPoint.X) > 1e-9


def vp_where(vp):
    sheet = doc.GetElement(vp.SheetId)
    view = doc.GetElement(vp.ViewId)
    return u"{0}  |  {1}".format(sheet.SheetNumber if sheet else u"-", view.Name if view else u"-")


def restore_title(w):
    try:
        w["vp"].LabelLineLength = w["len0"]
        w["vp"].LabelOffset = w["off0"]
    except Exception:
        pass


def tidy_titles(vps, opts, report):
    """Batch passes so the document regenerates a few times in total, not per
    viewport. Returns the number of titles updated."""
    work = []
    for vp in vps:
        if vp.Rotation != ROT_NONE:
            report.append(u"{0}  -  title: viewport is rotated - skipped".format(vp_where(vp)))
            continue
        work.append({"vp": vp, "len0": vp.LabelLineLength, "off0": vp.LabelOffset})

    def skip(w, msg):
        restore_title(w)
        report.append(u"{0}  -  title: {1}".format(vp_where(w["vp"]), msg))

    if opts["fit"]:
        # A: shrink the line so the outline's right edge is the text's right edge
        alive = []
        for w in work:
            try:
                w["vp"].LabelLineLength = SHORT_LINE
                alive.append(w)
            except Exception as ex:
                skip(w, u"{0} - skipped".format(ex))
        work = alive
        doc.Regenerate()
        # B: stretch it past the text, so the outline's right edge is the line end
        alive = []
        for w in work:
            o = w["vp"].GetLabelOutline()
            if not outline_ok(o):
                skip(w, u"title is not shown - skipped")
                continue
            w["text_right"] = o.MaximumPoint.X
            w["long"] = (o.MaximumPoint.X - o.MinimumPoint.X) * 3.0 + 0.5
            try:
                w["vp"].LabelLineLength = w["long"]
                alive.append(w)
            except Exception as ex:
                skip(w, u"{0} - skipped".format(ex))
        work = alive
        doc.Regenerate()
        # C: final length = text right - line start + extension
        alive = []
        for w in work:
            o = w["vp"].GetLabelOutline()
            line_start = o.MaximumPoint.X - w["long"]
            try:
                w["vp"].LabelLineLength = max(w["text_right"] - line_start + opts["extra"], SHORT_LINE)
                alive.append(w)
            except Exception as ex:
                skip(w, u"{0} - skipped".format(ex))
        work = alive
        doc.Regenerate()
    elif opts["align"]:
        alive = []
        for w in work:
            if outline_ok(w["vp"].GetLabelOutline()):
                alive.append(w)
            else:
                report.append(u"{0}  -  title: title is not shown - skipped".format(vp_where(w["vp"])))
        work = alive

    if not opts["align"]:
        return len(work)

    # D: move the title so its top-left sits at (box left + shift, box bottom - gap)
    done = 0
    for w in work:
        vp = w["vp"]
        o = vp.GetLabelOutline()
        box = vp.GetBoxOutline()
        dx = (box.MinimumPoint.X + opts["h"]) - o.MinimumPoint.X
        dy = (box.MinimumPoint.Y - opts["v"]) - o.MaximumPoint.Y
        off = vp.LabelOffset
        try:
            vp.LabelOffset = XYZ(off.X + dx, off.Y + dy, 0.0)
            done += 1
        except Exception as ex:
            skip(w, u"{0} - skipped".format(ex))
    return done


# =========================================================================
#  Scope
# =========================================================================
def collect_sheets():
    rows = []
    for s in FilteredElementCollector(doc).OfClass(ViewSheet):
        if s.IsPlaceholder:
            continue
        rows.append({"sheet": s, "views": len(list(s.GetAllPlacedViews()))})
    rows.sort(key=lambda r: r["sheet"].SheetNumber)
    return rows


def selected_scope():
    """What was selected before running: viewports on a sheet, or views in the
    Project Browser. ([(where, view)], [viewport])"""
    views, vps, seen = [], [], set()
    for eid in uidoc.Selection.GetElementIds():
        e = doc.GetElement(eid)
        if isinstance(e, Viewport):
            vps.append(e)
            v = doc.GetElement(e.ViewId)
            sheet = doc.GetElement(e.SheetId)
            where = u"{0}  |  {1}".format(sheet.SheetNumber, v.Name) if (sheet and v) else None
        elif isinstance(e, View) and not isinstance(e, ViewSheet):
            v, where = e, e.Name
        else:
            continue
        if v is None or id_val(v.Id) in seen:
            continue
        seen.add(id_val(v.Id))
        views.append((where or v.Name, v))
    return views, vps


# =========================================================================
#  UI
# =========================================================================
XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Tidy Views" SizeToContent="WidthAndHeight"
        ResizeMode="NoResize" WindowStartupLocation="CenterScreen"
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
    <Style x:Key="AccentBtn" TargetType="Button" BasedOn="{StaticResource Btn}">
      <Setter Property="Background" Value="#F1C21B"/>
      <Setter Property="Foreground" Value="#161616"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
    </Style>
    <Style x:Key="Tgl" TargetType="ToggleButton">
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Height" Value="28"/>
      <Setter Property="Padding" Value="8,0"/>
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
      <Setter Property="Height" Value="28"/>
      <Setter Property="Padding" Value="6,0"/>
      <Setter Property="VerticalContentAlignment" Value="Center"/>
    </Style>
    <Style x:Key="Num" TargetType="TextBox" BasedOn="{StaticResource {x:Type TextBox}}">
      <Setter Property="Width" Value="64"/>
      <Setter Property="TextAlignment" Value="Center"/>
    </Style>
    <Style TargetType="CheckBox">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="VerticalContentAlignment" Value="Center"/>
      <Setter Property="Cursor" Value="Hand"/>
    </Style>
    <Style x:Key="Head" TargetType="CheckBox" BasedOn="{StaticResource {x:Type CheckBox}}">
      <Setter Property="FontSize" Value="14"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
      <Setter Property="Margin" Value="0,0,0,4"/>
    </Style>
    <Style x:Key="Sub" TargetType="TextBlock">
      <Setter Property="Foreground" Value="#A8A8A8"/>
      <Setter Property="TextWrapping" Value="Wrap"/>
    </Style>
    <Style x:Key="Lbl" TargetType="TextBlock">
      <Setter Property="Foreground" Value="#A8A8A8"/>
      <Setter Property="FontSize" Value="11"/>
      <Setter Property="VerticalAlignment" Value="Center"/>
      <Setter Property="Margin" Value="0,0,6,0"/>
    </Style>
    <Style x:Key="Card" TargetType="Border">
      <Setter Property="Background" Value="#262626"/>
      <Setter Property="CornerRadius" Value="8"/>
      <Setter Property="Padding" Value="12"/>
    </Style>
    <Style x:Key="PreviewBox" TargetType="Border">
      <Setter Property="Background" Value="#161616"/>
      <Setter Property="CornerRadius" Value="6"/>
      <Setter Property="Padding" Value="2"/>
      <Setter Property="VerticalAlignment" Value="Top"/>
    </Style>
  </Window.Resources>

  <StackPanel Margin="12">
    <TextBlock Text="Tidy Views" Foreground="#F4F4F4" FontSize="20" FontWeight="Bold"/>
    <TextBlock Style="{StaticResource Sub}" Margin="0,2,0,12"
               Text="Grids, levels and viewport titles in one go. Only the chosen views and viewports change."/>
    <Grid>
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="330"/>
        <ColumnDefinition Width="12"/>
        <ColumnDefinition Width="570"/>
      </Grid.ColumnDefinitions>

      <!-- Apply to -->
      <Border Grid.Column="0" Style="{StaticResource Card}">
        <StackPanel>
          <TextBlock Text="APPLY TO" Foreground="#F1C21B" FontSize="11" FontWeight="Bold" Margin="0,0,0,8"/>
          <UniformGrid Columns="2">
            <ToggleButton x:Name="tglView" Content="Active view" Style="{StaticResource Tgl}" Margin="0,0,3,6"/>
            <ToggleButton x:Name="tglSheet" Content="Active sheet" Style="{StaticResource Tgl}" Margin="3,0,0,6"/>
            <ToggleButton x:Name="tglSel" Content="Selected views" Style="{StaticResource Tgl}" Margin="0,0,3,0"/>
            <ToggleButton x:Name="tglPick" Content="Picked sheets" Style="{StaticResource Tgl}" Margin="3,0,0,0"/>
          </UniformGrid>
          <TextBlock x:Name="txtScopeNote" Style="{StaticResource Sub}" FontSize="11" Margin="0,8,0,0"/>
          <StackPanel x:Name="pnlSheets" Margin="0,10,0,0">
            <Grid>
              <TextBox x:Name="txtSearch"/>
              <TextBlock x:Name="txtHint" Text="Search sheets" Foreground="#6F6F6F"
                         Margin="9,0,0,0" VerticalAlignment="Center" IsHitTestVisible="False"/>
            </Grid>
            <DockPanel Margin="0,6,0,4">
              <StackPanel DockPanel.Dock="Right" Orientation="Horizontal">
                <Button x:Name="btnAll" Content="All" Style="{StaticResource Btn}" Height="24" Margin="0,0,4,0"/>
                <Button x:Name="btnNone" Content="None" Style="{StaticResource Btn}" Height="24"/>
              </StackPanel>
              <TextBlock x:Name="txtCount" Style="{StaticResource Sub}" VerticalAlignment="Center"/>
            </DockPanel>
            <Border Background="#161616" CornerRadius="6" Height="330">
              <ScrollViewer VerticalScrollBarVisibility="Auto">
                <StackPanel x:Name="pnlList" Margin="4"/>
              </ScrollViewer>
            </Border>
          </StackPanel>
        </StackPanel>
      </Border>

      <StackPanel Grid.Column="2">
        <!-- Grids -->
        <Border Style="{StaticResource Card}" Margin="0,0,0,10">
          <DockPanel>
          <Border DockPanel.Dock="Right" Style="{StaticResource PreviewBox}">
            <Canvas x:Name="cvGrids" Width="210" Height="170" ClipToBounds="True"/>
          </Border>
          <StackPanel Margin="0,0,12,0">
            <CheckBox x:Name="chkGrids" Content="Grids" Style="{StaticResource Head}"/>
            <TextBlock Style="{StaticResource Sub}" FontSize="11" Margin="0,0,0,8"
                       Text="Plans, sections, elevations and detail views with the crop region on."/>
            <StackPanel x:Name="pnlGrids">
              <CheckBox x:Name="chkGBub" Content="Set grid bubbles on" Margin="0,0,0,6"/>
              <StackPanel x:Name="pnlGBub" Orientation="Horizontal" Margin="20,0,0,10">
                <ToggleButton x:Name="tglGT" Content="Top" Style="{StaticResource Tgl}" Width="64" Margin="0,0,4,0"/>
                <ToggleButton x:Name="tglGB" Content="Bottom" Style="{StaticResource Tgl}" Width="64" Margin="0,0,4,0"/>
                <ToggleButton x:Name="tglGL" Content="Left" Style="{StaticResource Tgl}" Width="64" Margin="0,0,4,0"/>
                <ToggleButton x:Name="tglGR" Content="Right" Style="{StaticResource Tgl}" Width="64"/>
              </StackPanel>
              <CheckBox x:Name="chkGAlign" Content="Line up grid ends past the crop (mm)" Margin="0,0,0,6"/>
              <StackPanel x:Name="pnlGAlign" Margin="20,0,0,0">
                <Grid>
                  <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="Auto"/>
                    <ColumnDefinition Width="Auto"/>
                    <ColumnDefinition Width="Auto"/>
                    <ColumnDefinition Width="Auto"/>
                  </Grid.ColumnDefinitions>
                  <Grid.RowDefinitions>
                    <RowDefinition Height="Auto"/>
                    <RowDefinition Height="Auto"/>
                  </Grid.RowDefinitions>
                  <TextBlock Grid.Row="0" Grid.Column="0" Text="Top" Style="{StaticResource Lbl}"/>
                  <TextBox Grid.Row="0" Grid.Column="1" x:Name="txtGT" Style="{StaticResource Num}" Margin="0,0,14,4"/>
                  <TextBlock Grid.Row="0" Grid.Column="2" Text="Bottom" Style="{StaticResource Lbl}"/>
                  <TextBox Grid.Row="0" Grid.Column="3" x:Name="txtGB" Style="{StaticResource Num}" Margin="0,0,0,4"/>
                  <TextBlock Grid.Row="1" Grid.Column="0" Text="Left" Style="{StaticResource Lbl}"/>
                  <TextBox Grid.Row="1" Grid.Column="1" x:Name="txtGL" Style="{StaticResource Num}" Margin="0,0,14,0"/>
                  <TextBlock Grid.Row="1" Grid.Column="2" Text="Right" Style="{StaticResource Lbl}"/>
                  <TextBox Grid.Row="1" Grid.Column="3" x:Name="txtGR" Style="{StaticResource Num}"/>
                </Grid>
                <CheckBox x:Name="chkGLink" Content="Same offset on all sides" Margin="0,6,0,0"/>
              </StackPanel>
            </StackPanel>
          </StackPanel>
          </DockPanel>
        </Border>

        <!-- Levels -->
        <Border Style="{StaticResource Card}" Margin="0,0,0,10">
          <DockPanel>
          <Border DockPanel.Dock="Right" Style="{StaticResource PreviewBox}">
            <Canvas x:Name="cvLevels" Width="210" Height="150" ClipToBounds="True"/>
          </Border>
          <StackPanel Margin="0,0,12,0">
            <CheckBox x:Name="chkLevels" Content="Levels" Style="{StaticResource Head}"/>
            <TextBlock Style="{StaticResource Sub}" FontSize="11" Margin="0,0,0,8"
                       Text="Sections and elevations. The levels' 3D extents never move."/>
            <StackPanel x:Name="pnlLevels">
              <CheckBox x:Name="chkLHead" Content="Set level heads on" Margin="0,0,0,6"/>
              <StackPanel x:Name="pnlLHead" Orientation="Horizontal" Margin="20,0,0,10">
                <ToggleButton x:Name="tglLL" Content="Left" Style="{StaticResource Tgl}" Width="64" Margin="0,0,4,0"/>
                <ToggleButton x:Name="tglLR" Content="Right" Style="{StaticResource Tgl}" Width="64"/>
              </StackPanel>
              <CheckBox x:Name="chkLAlign" Content="Line up level ends past the crop (mm)" Margin="0,0,0,6"/>
              <StackPanel x:Name="pnlLAlign" Margin="20,0,0,0">
                <StackPanel Orientation="Horizontal">
                  <TextBlock Text="Left" Style="{StaticResource Lbl}"/>
                  <TextBox x:Name="txtLL" Style="{StaticResource Num}" Margin="0,0,10,0"/>
                  <TextBlock Text="Right" Style="{StaticResource Lbl}"/>
                  <TextBox x:Name="txtLR" Style="{StaticResource Num}"/>
                </StackPanel>
                <TextBlock Style="{StaticResource Sub}" FontSize="11" Margin="0,6,0,0"
                           Text="In a view with the crop region off, measured from the outermost grids instead."/>
              </StackPanel>
            </StackPanel>
          </StackPanel>
          </DockPanel>
        </Border>

        <!-- Viewport titles -->
        <Border Style="{StaticResource Card}">
          <DockPanel>
          <Border DockPanel.Dock="Right" Style="{StaticResource PreviewBox}">
            <Canvas x:Name="cvTitles" Width="210" Height="150" ClipToBounds="True"/>
          </Border>
          <StackPanel Margin="0,0,12,0">
            <CheckBox x:Name="chkTitles" Content="Viewport titles" Style="{StaticResource Head}"/>
            <TextBlock Style="{StaticResource Sub}" FontSize="11" Margin="0,0,0,8"
                       Text="Viewports on sheets. Paper mm. Rotated viewports and hidden titles are skipped."/>
            <StackPanel x:Name="pnlTitles">
              <CheckBox x:Name="chkTAlign" Content="Put the title under the bottom-left corner" Margin="0,0,0,6"/>
              <StackPanel x:Name="pnlTAlign" Orientation="Horizontal" Margin="20,0,0,10">
                <TextBlock Text="Shift right" Style="{StaticResource Lbl}"/>
                <TextBox x:Name="txtTH" Style="{StaticResource Num}" Margin="0,0,10,0"/>
                <TextBlock Text="Gap below" Style="{StaticResource Lbl}"/>
                <TextBox x:Name="txtTV" Style="{StaticResource Num}"/>
              </StackPanel>
              <CheckBox x:Name="chkTFit" Content="Fit the title line to the text" Margin="0,0,0,6"/>
              <StackPanel x:Name="pnlTFit" Orientation="Horizontal" Margin="20,0,0,0">
                <TextBlock Text="Line extends past the text by" Style="{StaticResource Lbl}"/>
                <TextBox x:Name="txtTX" Style="{StaticResource Num}"/>
              </StackPanel>
            </StackPanel>
          </StackPanel>
          </DockPanel>
        </Border>
      </StackPanel>
    </Grid>

    <DockPanel Margin="0,12,0,0">
      <StackPanel DockPanel.Dock="Right" Orientation="Horizontal">
        <Button x:Name="btnCancel" Content="Cancel" Style="{StaticResource Btn}" Width="84" Margin="0,0,8,0"/>
        <Button x:Name="btnApply" Content="Apply" Style="{StaticResource AccentBtn}" Width="84"/>
      </StackPanel>
      <TextBlock x:Name="txtMsg" Foreground="#FA4D56" VerticalAlignment="Center" TextWrapping="Wrap"/>
    </DockPanel>
  </StackPanel>
</Window>
"""

_brushes = {}


def brush(hexs):
    if hexs not in _brushes:
        _brushes[hexs] = SolidColorBrush(ColorConverter.ConvertFromString(hexs))
    return _brushes[hexs]


# =========================================================================
#  Previews (schematic only - they show what the options do, not your model)
# =========================================================================
GRID_DASH = "10 3 2 3"
HILITE = "#F1C21B"


def cv_line(cv, x1, y1, x2, y2, color, th=1.0, dash=None):
    ln = WLine()
    ln.X1, ln.Y1, ln.X2, ln.Y2 = x1, y1, x2, y2
    ln.Stroke = brush(color)
    ln.StrokeThickness = th
    if dash:
        ln.StrokeDashArray = DoubleCollection.Parse(dash)
    cv.Children.Add(ln)


def cv_rect(cv, x, y, w, h, stroke=None, fill=None, dash=None, opacity=1.0):
    r = Rectangle()
    r.Width, r.Height = max(w, 0.0), max(h, 0.0)
    if stroke:
        r.Stroke = brush(stroke)
        r.StrokeThickness = 1
    if fill:
        r.Fill = brush(fill)
    if dash:
        r.StrokeDashArray = DoubleCollection.Parse(dash)
    r.Opacity = opacity
    Canvas.SetLeft(r, x)
    Canvas.SetTop(r, y)
    cv.Children.Add(r)


def cv_circle(cv, cx, cy, rad):
    e = Ellipse()
    e.Width = e.Height = rad * 2
    e.Fill = brush("#161616")
    e.Stroke = brush("#F4F4F4")
    e.StrokeThickness = 1
    Canvas.SetLeft(e, cx - rad)
    Canvas.SetTop(e, cy - rad)
    cv.Children.Add(e)


def cv_text(cv, x, y, text, size=9, color="#F4F4F4", width=None, align=None, bold=False):
    tb = TextBlock()
    tb.Text = text
    tb.FontSize = size
    tb.Foreground = brush(color)
    if bold:
        tb.FontWeight = FontWeights.SemiBold
    if width:
        tb.Width = width
    if align is not None:
        tb.TextAlignment = align
    Canvas.SetLeft(tb, x)
    Canvas.SetTop(tb, y)
    cv.Children.Add(tb)
    return tb


def text_width(text, size, bold=False):
    tb = TextBlock()
    tb.Text = text
    tb.FontSize = size
    if bold:
        tb.FontWeight = FontWeights.SemiBold
    tb.Measure(Size(10000.0, 10000.0))
    return tb.DesiredSize.Width


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


def draw_grids(cv, do_b, do_a, bub, off):
    """Crop region (dashed box), three vertical and two horizontal grids."""
    cv.Children.Clear()
    x0, x1, y0, y1 = 55.0, 155.0, 45.0, 125.0
    rad = 7.0
    vgrids = [(80.0, u"1"), (105.0, u"2"), (130.0, u"3")]
    hgrids = [(70.0, u"A"), (100.0, u"B")]
    messy = {"t": [22, 14, 30], "b": [146, 152, 138], "l": [28, 18], "r": [178, 186]}

    def px(mm):
        return clamp(mm * 0.013, -26.0, 26.0)

    shown = bub if do_b else {"t": True, "b": True, "l": True, "r": False}
    cv_rect(cv, x0 + 15, y0 + 15, x1 - x0 - 30, y1 - y0 - 30, fill="#393939", opacity=0.5)
    cv_rect(cv, x0, y0, x1 - x0, y1 - y0, stroke="#A8A8A8", dash="5 3")

    def bubble(cx, cy, text):
        cv_circle(cv, cx, cy, rad)
        cv_text(cv, cx - rad, cy - 6.5, text, 9, width=rad * 2, align=TextAlignment.Center)

    for i, (x, n) in enumerate(vgrids):
        t = y0 - px(off["t"]) if do_a else messy["t"][i]
        b = y1 + px(off["b"]) if do_a else messy["b"][i]
        cv_line(cv, x, t, x, b, "#A8A8A8", 1, GRID_DASH)
        if do_a:
            cv_line(cv, x, y0, x, t, HILITE, 2)
            cv_line(cv, x, y1, x, b, HILITE, 2)
        if shown["t"]:
            bubble(x, t - rad, n)
        if shown["b"]:
            bubble(x, b + rad, n)

    for i, (y, n) in enumerate(hgrids):
        l = x0 - px(off["l"]) if do_a else messy["l"][i]
        r = x1 + px(off["r"]) if do_a else messy["r"][i]
        cv_line(cv, l, y, r, y, "#A8A8A8", 1, GRID_DASH)
        if do_a:
            cv_line(cv, x0, y, l, y, HILITE, 2)
            cv_line(cv, x1, y, r, y, HILITE, 2)
        if shown["l"]:
            bubble(l - rad, y, n)
        if shown["r"]:
            bubble(r + rad, y, n)


def draw_levels(cv, do_h, do_a, heads, off):
    """A section: crop region (dashed box) with three levels across it."""
    cv.Children.Clear()
    x0, x1, y0, y1 = 65.0, 145.0, 22.0, 140.0
    rad = 5.0
    levels = [(48.0, u"Roof"), (88.0, u"L02"), (122.0, u"L01")]
    messy_l = [34, 50, 26]
    messy_r = [176, 160, 186]

    def px(mm):
        return clamp(mm * 0.013, -26.0, 26.0)

    shown = heads if do_h else {"l": False, "r": True}
    cv_rect(cv, x0 + 12, y0 + 20, x1 - x0 - 24, y1 - y0 - 20, fill="#393939", opacity=0.5)
    cv_rect(cv, x0, y0, x1 - x0, y1 - y0, stroke="#A8A8A8", dash="5 3")

    def head(x, y, name, side):
        cv_circle(cv, x, y, rad)
        cv_line(cv, x - rad, y, x + rad, y, "#F4F4F4", 1)
        if side == "l":
            cv_text(cv, x - 44, y - 18, name, 9, width=44, align=TextAlignment.Right)
        else:
            cv_text(cv, x, y - 18, name, 9, width=44, align=TextAlignment.Left)

    for i, (y, name) in enumerate(levels):
        if do_a:
            l, r = x0 - px(off["l"]), x1 + px(off["r"])
        else:
            l, r = messy_l[i], messy_r[i]
        cv_line(cv, l, y, r, y, "#A8A8A8", 1, GRID_DASH)
        if do_a:
            cv_line(cv, x0, y, l, y, HILITE, 2)
            cv_line(cv, x1, y, r, y, HILITE, 2)
        if shown["l"]:
            head(l, y, name, "l")
        if shown["r"]:
            head(r, y, name, "r")


def draw_titles(cv, do_a, do_f, mm):
    """A viewport on a sheet with its title (name, title line, scale)."""
    cv.Children.Clear()
    bx0, bx1, by0, by1 = 20.0, 170.0, 12.0, 92.0
    scale = 4.0                                   # px per paper mm
    name, size = u"Level 01 Plan", 10
    tw = text_width(name, size, True)

    cv_rect(cv, bx0 + 12, by0 + 10, bx1 - bx0 - 24, by1 - by0 - 20, fill="#393939", opacity=0.5)
    cv_rect(cv, bx0, by0, bx1 - bx0, by1 - by0, stroke="#A8A8A8", dash="5 3")

    if do_a:
        tx = bx0 + clamp(mm["h"] * scale, -18.0, 60.0)
        ty = by1 + clamp(mm["v"] * scale, -20.0, 28.0)
    else:
        tx, ty = 64.0, 104.0
    if do_f:
        line_len = max(tw + clamp(mm["x"] * scale, 4.0 - tw, 60.0), 4.0)
    else:
        line_len = 132.0

    if do_a:
        cv_line(cv, bx0, by1, tx, by1, HILITE, 2)           # shift right
        cv_line(cv, tx, by1, tx, ty, HILITE, 2)             # gap below
    cv_text(cv, tx, ty, name, size, bold=True)
    line_y = ty + 15
    cv_line(cv, tx, line_y, tx + line_len, line_y, "#F4F4F4", 1.5)
    if do_f and line_len > tw:
        cv_line(cv, tx + tw, line_y, tx + line_len, line_y, HILITE, 2)   # extension past the text
    cv_text(cv, tx, line_y + 2, u"1 : 100", 8, "#A8A8A8")


def opt_bool(name, default):
    try:
        return float(cfg.get_option(name, 1.0 if default else 0.0)) > 0.5
    except Exception:
        return default


def opt_float(name, default):
    try:
        return float(cfg.get_option(name, default))
    except Exception:
        return default


def parse_mm(text):
    return float(text.strip().replace(",", "."))


def show_ui(active, active_is_sheet, sheet_rows, sel_views, sel_vps):
    w = XamlReader.Parse(XAML)
    f = w.FindName
    result = {"ok": False}

    tgl_scope = {"view": f("tglView"), "sheet": f("tglSheet"), "sel": f("tglSel"), "pick": f("tglPick")}
    pnl_sheets, pnl_list = f("pnlSheets"), f("pnlList")
    txt_search, txt_hint, txt_count = f("txtSearch"), f("txtHint"), f("txtCount")
    txt_msg, txt_scope_note = f("txtMsg"), f("txtScopeNote")

    chk = dict((k, f(n)) for k, n in [
        ("grids", "chkGrids"), ("g_bub", "chkGBub"), ("g_align", "chkGAlign"), ("g_link", "chkGLink"),
        ("levels", "chkLevels"), ("l_head", "chkLHead"), ("l_align", "chkLAlign"),
        ("titles", "chkTitles"), ("t_align", "chkTAlign"), ("t_fit", "chkTFit")])
    pnl = dict((k, f(n)) for k, n in [
        ("grids", "pnlGrids"), ("g_bub", "pnlGBub"), ("g_align", "pnlGAlign"),
        ("levels", "pnlLevels"), ("l_head", "pnlLHead"), ("l_align", "pnlLAlign"),
        ("titles", "pnlTitles"), ("t_align", "pnlTAlign"), ("t_fit", "pnlTFit")])
    g_bub = {"t": f("tglGT"), "b": f("tglGB"), "l": f("tglGL"), "r": f("tglGR")}
    g_off = {"t": f("txtGT"), "b": f("txtGB"), "l": f("txtGL"), "r": f("txtGR")}
    l_head = {"l": f("tglLL"), "r": f("tglLR")}
    l_off = {"l": f("txtLL"), "r": f("txtLR")}
    t_h, t_v, t_x = f("txtTH"), f("txtTV"), f("txtTX")
    cv = {"grids": f("cvGrids"), "levels": f("cvLevels"), "titles": f("cvTitles")}

    # ---- restore settings
    for key, default in [("grids", True), ("g_bub", True), ("g_align", True), ("g_link", False),
                         ("levels", True), ("l_head", True), ("l_align", True),
                         ("titles", True), ("t_align", True), ("t_fit", True)]:
        chk[key].IsChecked = opt_bool("do_" + key, default)
    for s, default in zip(GRID_SIDES, (True, False, True, False)):
        g_bub[s].IsChecked = opt_bool("g_bub_" + s, default)
        g_off[s].Text = u"{0:g}".format(opt_float("g_off_" + s, 1000.0))
    for s, default in zip(LEVEL_SIDES, (False, True)):
        l_head[s].IsChecked = opt_bool("l_head_" + s, default)
        l_off[s].Text = u"{0:g}".format(opt_float("l_off_" + s, 1000.0))
    t_h.Text = u"{0:g}".format(opt_float("t_h_mm", 0.0))
    t_v.Text = u"{0:g}".format(opt_float("t_v_mm", 2.0))
    t_x.Text = u"{0:g}".format(opt_float("t_x_mm", 3.0))

    # ---- scope buttons
    n_sel = len(sel_views)
    tgl_scope["sel"].IsEnabled = n_sel > 0
    if n_sel:
        tgl_scope["sel"].Content = u"Selected views ({0})".format(n_sel)
    else:
        tgl_scope["sel"].ToolTip = u"Select viewports on a sheet, or views in the Project Browser, before running"
    tgl_scope["view"].IsEnabled = not active_is_sheet
    tgl_scope["sheet"].IsEnabled = active_is_sheet
    tgl_scope["view"].ToolTip = u"The active view is a sheet" if active_is_sheet else None
    tgl_scope["sheet"].ToolTip = None if active_is_sheet else u"The active view isn't a sheet"
    state = {"scope": None, "busy": [False]}

    # ---- sheet list
    list_rows = []

    def update_count(*args):
        n = len([r for r in list_rows if r["cb"].IsChecked])
        txt_count.Text = u"{0} of {1} selected".format(n, len(list_rows))
        txt_msg.Text = u""

    for r in sheet_rows:
        sh = r["sheet"]
        cb = CheckBox()
        cb.Margin = Thickness(2, 2, 2, 2)
        sp = StackPanel()
        sp.Orientation = Orientation.Horizontal
        t1 = TextBlock()
        t1.Text = sh.SheetNumber
        t1.Width = 64
        t1.Foreground = brush("#A8A8A8")
        t1.TextTrimming = TextTrimming.CharacterEllipsis
        t2 = TextBlock()
        t2.Text = sh.Name
        t2.Width = 170
        t2.Foreground = brush("#F4F4F4")
        t2.TextTrimming = TextTrimming.CharacterEllipsis
        t3 = TextBlock()
        t3.Text = u"{0} views".format(r["views"])
        t3.Foreground = brush("#6F6F6F")
        t3.FontSize = 11
        t3.VerticalAlignment = VerticalAlignment.Center
        for t in (t1, t2, t3):
            sp.Children.Add(t)
        cb.Content = sp
        cb.Checked += RoutedEventHandler(update_count)
        cb.Unchecked += RoutedEventHandler(update_count)
        pnl_list.Children.Add(cb)
        list_rows.append({"cb": cb, "sheet": sh, "key": (sh.SheetNumber + u" " + sh.Name).lower()})

    def on_search(s, e):
        q = txt_search.Text.strip().lower()
        txt_hint.Opacity = 0.0 if txt_search.Text else 1.0
        for lr in list_rows:
            lr["cb"].Visibility = Visibility.Visible if q in lr["key"] else Visibility.Collapsed

    txt_search.TextChanged += TextChangedEventHandler(on_search)

    def set_visible_rows(value):
        for lr in list_rows:
            if lr["cb"].Visibility == Visibility.Visible:
                lr["cb"].IsChecked = value

    f("btnAll").Click += RoutedEventHandler(lambda s, e: set_visible_rows(True))
    f("btnNone").Click += RoutedEventHandler(lambda s, e: set_visible_rows(False))

    scope_notes = {
        "view": u"Grids and levels in the active view. Viewport titles are tidied only on sheets.",
        "sheet": u"Every view and viewport title on the active sheet.",
        "sel": u"The views you selected. Titles are tidied for selected viewports.",
        "pick": u"Every view and viewport title on the sheets you check below.",
    }

    def set_scope(name):
        if not tgl_scope[name].IsEnabled:
            name = "pick"
        state["scope"] = name
        for k, t in tgl_scope.items():
            t.IsChecked = (k == name)
        pnl_sheets.IsEnabled = (name == "pick")
        pnl_sheets.Opacity = 1.0 if name == "pick" else 0.4
        txt_scope_note.Text = scope_notes[name]
        txt_msg.Text = u""

    def scope_handler(name):
        def handler(s, e):
            set_scope(name)
        return handler

    for k, t in tgl_scope.items():
        t.Click += RoutedEventHandler(scope_handler(k))

    # ---- previews
    def num(box, default):
        try:
            return parse_mm(box.Text)
        except Exception:
            return default

    def redraw(*args):
        def on(section, sub):
            return bool(chk[section].IsChecked) and bool(chk[sub].IsChecked)
        try:
            draw_grids(cv["grids"], on("grids", "g_bub"), on("grids", "g_align"),
                       dict((s, bool(g_bub[s].IsChecked)) for s in GRID_SIDES),
                       dict((s, num(g_off[s], 0.0)) for s in GRID_SIDES))
            draw_levels(cv["levels"], on("levels", "l_head"), on("levels", "l_align"),
                        dict((s, bool(l_head[s].IsChecked)) for s in LEVEL_SIDES),
                        dict((s, num(l_off[s], 0.0)) for s in LEVEL_SIDES))
            draw_titles(cv["titles"], on("titles", "t_align"), on("titles", "t_fit"),
                        {"h": num(t_h, 0.0), "v": num(t_v, 0.0), "x": num(t_x, 0.0)})
        except Exception:
            pass                      # a preview must never block the tool
        for section in ("grids", "levels", "titles"):
            cv[section].Opacity = 1.0 if chk[section].IsChecked else 0.35

    for t in list(g_bub.values()) + list(l_head.values()):
        t.Click += RoutedEventHandler(redraw)
    for box in list(g_off.values()) + list(l_off.values()) + [t_h, t_v, t_x]:
        box.TextChanged += TextChangedEventHandler(redraw)

    # ---- enable / dim the option panels
    def sync(*args):
        for section, subs in (("grids", ("g_bub", "g_align")), ("levels", ("l_head", "l_align")),
                              ("titles", ("t_align", "t_fit"))):
            on = bool(chk[section].IsChecked)
            pnl[section].IsEnabled = on
            pnl[section].Opacity = 1.0 if on else 0.4
            for sub in subs:
                sub_on = bool(chk[sub].IsChecked)
                pnl[sub].IsEnabled = sub_on
                pnl[sub].Opacity = 1.0 if sub_on else 0.45
        txt_msg.Text = u""
        redraw()

    for c in chk.values():
        c.Click += RoutedEventHandler(sync)

    # ---- "same offset on all sides" for grids
    def g_off_handler(side):
        def handler(s, e):
            if state["busy"][0] or not chk["g_link"].IsChecked:
                return
            state["busy"][0] = True
            for o in GRID_SIDES:
                if o != side:
                    g_off[o].Text = g_off[side].Text
            state["busy"][0] = False
        return handler

    for s in GRID_SIDES:
        g_off[s].TextChanged += TextChangedEventHandler(g_off_handler(s))

    def on_link(s, e):
        if chk["g_link"].IsChecked:
            state["busy"][0] = True
            for o in ("b", "l", "r"):
                g_off[o].Text = g_off["t"].Text
            state["busy"][0] = False

    chk["g_link"].Click += RoutedEventHandler(on_link)

    saved_scope = cfg.get_option("scope", "view")
    if saved_scope not in tgl_scope or saved_scope == "sel":
        saved_scope = "view"
    if n_sel:
        saved_scope = "sel"
    if saved_scope != "pick" and not tgl_scope[saved_scope].IsEnabled:
        saved_scope = "sheet" if active_is_sheet else "view"
    set_scope(saved_scope)
    update_count()
    sync()

    # ---- apply / cancel
    def fail(msg):
        txt_msg.Text = msg

    def read_offsets(boxes, label):
        out = {}
        for side, box in boxes.items():
            out[side] = parse_mm(box.Text)
        return out

    def on_apply(s, e):
        do = dict((k, bool(c.IsChecked)) for k, c in chk.items())
        grids_on = do["grids"] and (do["g_bub"] or do["g_align"])
        levels_on = do["levels"] and (do["l_head"] or do["l_align"])
        titles_on = do["titles"] and (do["t_align"] or do["t_fit"])
        if not (grids_on or levels_on or titles_on):
            return fail(u"Check at least one option under Grids, Levels or Viewport titles.")
        try:
            g_off_mm = read_offsets(g_off, u"grid") if grids_on and do["g_align"] else \
                dict((k, opt_float("g_off_" + k, 1000.0)) for k in GRID_SIDES)
        except Exception:
            return fail(u"Grids: enter a number (mm) for every offset.")
        try:
            l_off_mm = read_offsets(l_off, u"level") if levels_on and do["l_align"] else \
                dict((k, opt_float("l_off_" + k, 1000.0)) for k in LEVEL_SIDES)
        except Exception:
            return fail(u"Levels: enter a number (mm) for both offsets.")
        try:
            t_mm = {"h": parse_mm(t_h.Text) if titles_on and do["t_align"] else opt_float("t_h_mm", 0.0),
                    "v": parse_mm(t_v.Text) if titles_on and do["t_align"] else opt_float("t_v_mm", 2.0),
                    "x": parse_mm(t_x.Text) if titles_on and do["t_fit"] else opt_float("t_x_mm", 3.0)}
        except Exception:
            return fail(u"Viewport titles: the distances must be numbers (mm).")

        scope = state["scope"]
        views, vps = [], []       # views: [(where, view)]
        if scope == "view":
            views.append((active.Name, active))
        elif scope == "sel":
            views = list(sel_views)
            vps = list(sel_vps)
        else:
            if scope == "sheet":
                sheets = [active]
            else:
                sheets = [lr["sheet"] for lr in list_rows if lr["cb"].IsChecked]
                if not sheets:
                    return fail(u"Pick at least one sheet.")
            for sh in sheets:
                for v in sheet_views(sh):
                    views.append((u"{0}  |  {1}".format(sh.SheetNumber, v.Name), v))
                vps += sheet_viewports(sh)

        result.update({
            "ok": True, "scope": scope, "views": views, "vps": vps, "do": do,
            "grids_on": grids_on, "levels_on": levels_on, "titles_on": titles_on,
            "g_bub": dict((k, bool(g_bub[k].IsChecked)) for k in GRID_SIDES), "g_off_mm": g_off_mm,
            "l_head": dict((k, bool(l_head[k].IsChecked)) for k in LEVEL_SIDES), "l_off_mm": l_off_mm,
            "t_mm": t_mm})
        w.Close()

    f("btnApply").Click += RoutedEventHandler(on_apply)
    f("btnCancel").Click += RoutedEventHandler(lambda s, e: w.Close())

    frame = DispatcherFrame()

    def on_closed(s, e):
        frame.Continue = False

    w.Closed += EventHandler(on_closed)
    try:
        WindowInteropHelper(w).Owner = __revit__.MainWindowHandle
    except Exception:
        pass
    w.Show()
    Dispatcher.PushFrame(frame)
    return result


# =========================================================================
#  Main
# =========================================================================
def save_settings(res):
    for key, value in res["do"].items():
        cfg.set_option("do_" + key, 1.0 if value else 0.0)
    for s in GRID_SIDES:
        cfg.set_option("g_bub_" + s, 1.0 if res["g_bub"][s] else 0.0)
        cfg.set_option("g_off_" + s, res["g_off_mm"][s])
    for s in LEVEL_SIDES:
        cfg.set_option("l_head_" + s, 1.0 if res["l_head"][s] else 0.0)
        cfg.set_option("l_off_" + s, res["l_off_mm"][s])
    cfg.set_option("t_h_mm", res["t_mm"]["h"])
    cfg.set_option("t_v_mm", res["t_mm"]["v"])
    cfg.set_option("t_x_mm", res["t_mm"]["x"])
    if res["scope"] != "sel":       # a selection is one-off, never the default
        cfg.set_option("scope", res["scope"])
    script.save_config()


def show_result(res, counts, report):
    lines = []
    if res["grids_on"]:
        lines.append(u"Grids: {0} updated in {1} views.".format(counts["grids"], counts["grid_views"]))
    if res["levels_on"]:
        lines.append(u"Levels: {0} updated in {1} sections / elevations.".format(
            counts["levels"], counts["level_views"]))
    if res["titles_on"]:
        if res["vps"]:
            lines.append(u"Viewport titles: {0} of {1} updated.".format(counts["titles"], len(res["vps"])))
        else:
            lines.append(u"Viewport titles: none in this scope. Choose Active sheet or Picked sheets, "
                         u"or select viewports on a sheet.")
    if counts["ignored"]:
        lines.append(u"{0} views have no grids or levels to tidy (legends, drafting, 3D, schedules...) "
                     u"and were left alone.".format(counts["ignored"]))
    td = TaskDialog(TITLE)
    td.MainInstruction = u"Views tidied" if (counts["grids"] or counts["levels"] or counts["titles"]) \
        else u"Nothing needed changing"
    if report:
        lines.append(u"{0} issues - expand details for the list.".format(len(report)))
        shown = report[:MAX_LISTED]
        if len(report) > MAX_LISTED:
            shown.append(u"... and {0} more".format(len(report) - MAX_LISTED))
        td.ExpandedContent = u"\n".join(shown)
    td.MainContent = u"\n".join(lines)
    td.CommonButtons = TaskDialogCommonButtons.Ok
    td.Show()


def main():
    active = doc.ActiveView
    active_is_sheet = isinstance(active, ViewSheet)
    sel_views, sel_vps = selected_scope()
    res = show_ui(active, active_is_sheet, collect_sheets(), sel_views, sel_vps)
    if not res["ok"]:
        return
    save_settings(res)

    do = res["do"]
    grid_opts = {"bubbles": do["g_bub"], "align": do["g_align"], "bub": res["g_bub"],
                 "off": dict((s, res["g_off_mm"][s] * MM) for s in GRID_SIDES)}
    level_opts = {"heads": do["l_head"], "align": do["l_align"], "head": res["l_head"],
                  "off": dict((s, res["l_off_mm"][s] * MM) for s in LEVEL_SIDES)}
    title_opts = {"align": do["t_align"], "fit": do["t_fit"], "h": res["t_mm"]["h"] * MM,
                  "v": res["t_mm"]["v"] * MM, "extra": res["t_mm"]["x"] * MM}
    multiseg = multi_segment_ids() if res["grids_on"] else set()

    report = []
    counts = {"grids": 0, "grid_views": 0, "levels": 0, "level_views": 0, "titles": 0, "ignored": 0}
    seen = set()

    t = Transaction(doc, TITLE)
    t.Start()
    try:
        for where, view in res["views"]:
            key = id_val(view.Id)
            if key in seen:
                continue
            seen.add(key)
            did_something = False
            if res["grids_on"]:
                issue = grid_view_issue(view)
                if issue is None:
                    did_something = True
                    n = tidy_grids(view, where, grid_opts, multiseg, report)
                    counts["grids"] += n
                    if n:
                        counts["grid_views"] += 1
                elif issue[0] == "crop":
                    did_something = True
                    report.append(u"{0}  -  {1}".format(where, issue[1]))
            if res["levels_on"] and level_view_ok(view):
                did_something = True
                n = tidy_levels(view, where, level_opts, report)
                counts["levels"] += n
                if n:
                    counts["level_views"] += 1
            if not did_something and (res["grids_on"] or res["levels_on"]):
                counts["ignored"] += 1
        if res["titles_on"] and res["vps"]:
            doc.Regenerate()        # grid / level ends can change a viewport's outline
            counts["titles"] = tidy_titles(res["vps"], title_opts, report)
        t.Commit()
    except Exception as ex:
        t.RollBack()
        bd.alert(u"Failed - nothing changed.\n\n{0}".format(ex), TITLE)
        return

    show_result(res, counts, report)


main()

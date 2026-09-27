# -*- coding: utf-8 -*-

__title__   = "Shafts\nOpen Above"
__author__  = "Mohamed Bedair"
__doc__     = """
________________________________________________________________
Description:
Batch-annotates "open above" shafts in the selected plan views,
from the host model AND from loaded Revit links.

For every selected Floor / Structural Plan the tool collects the
Shaft Openings that:
  - use the view's Associated Level as their Base Constraint
      host  -> same Level element
      link  -> link level at the same elevation (after the link
               transform) as the view's level
  - have a positive Base Offset
  - start above the view's Cut Plane

For each of those shafts it draws, in that view (all pinned):
  - the shaft boundary + X mark as Detail Lines (one line style)
  - a label text note centred below the shaft ("OPEN ABOVE")
  - the "Shaft Function" value inside the bottom-left corner

How to Use:
1. Run the script
2. Tick the plan views to annotate (search box filters the list)
3. Choose host / linked sources, line style, text types and label
4. Click Draw
________________________________________________________________
Author: Mohamed Bedair"""

# ─────────────────────────────────────────────────────────────────────
# Imports
# ─────────────────────────────────────────────────────────────────────
import clr
import math

clr.AddReference('System')
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')

from System import EventHandler
from System.Windows import (
    Thickness, Visibility, RoutedEventHandler, VerticalAlignment
)
from System.Windows.Controls import (
    CheckBox, StackPanel, TextBlock, TextChangedEventHandler
)
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Markup import XamlReader
from System.Windows.Media import SolidColorBrush, Color
from System.Windows.Threading import Dispatcher, DispatcherFrame

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    BuiltInCategory, BuiltInParameter,
    GraphicsStyleType, StorageType,
    ElementId, Level, ViewPlan, ViewType, PlanViewPlane,
    RevitLinkInstance,
    Line, XYZ, Transform,
    TextNote, TextNoteOptions, TextNoteType,
    HorizontalTextAlignment, VerticalTextAlignment,
    Transaction, TransactionGroup, SubTransaction
)

from pyrevit import forms

# ─────────────────────────────────────────────────────────────────────
# Revit handles
# ─────────────────────────────────────────────────────────────────────
uidoc = __revit__.ActiveUIDocument
doc   = uidoc.Document

# ─────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────
TOOL_TITLE      = "Shafts - Open Above"
FUNCTION_PARAM  = "Shaft Function"
FT_PER_MM       = 1.0 / 304.8
ELEV_TOL        = 1e-4                  # feet (~0.03 mm)
LEVEL_MATCH_TOL = 10.0 * FT_PER_MM      # link level vs host level (10 mm)

ALLOWED_VIEW_TYPES = [ViewType.FloorPlan, ViewType.EngineeringPlan]

# IBM Carbon palette
C_TEXT    = "#F4F4F4"
C_SUBTEXT = "#A8A8A8"
C_DIM     = "#6F6F6F"


# ═════════════════════════════════════════════════════════════════════
# GENERIC HELPERS
# ═════════════════════════════════════════════════════════════════════

def eid_int(eid):
    """ElementId -> int, Revit 2024-2027 safe."""
    try:
        return eid.Value
    except AttributeError:
        return eid.IntegerValue


def hex_brush(hex_str):
    h = hex_str.lstrip('#')
    return SolidColorBrush(
        Color.FromRgb(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)))


def type_name(elem_type):
    for bip in (BuiltInParameter.ALL_MODEL_TYPE_NAME,
                BuiltInParameter.SYMBOL_NAME_PARAM):
        p = elem_type.get_Parameter(bip)
        if p is not None and p.AsString():
            return p.AsString()
    return "Type {}".format(eid_int(elem_type.Id))


def view_type_label(view):
    if view.ViewType == ViewType.EngineeringPlan:
        return "Structural Plan"
    return "Floor Plan"


def parse_mm(text):
    """Non-negative float from a TextBox string, or None."""
    try:
        val = float((text or "").strip())
    except Exception:
        return None
    if val < 0:
        return None
    return val


def plural(n, word):
    return u"{} {}{}".format(n, word, u"" if n == 1 else u"s")


# ═════════════════════════════════════════════════════════════════════
# DATA COLLECTION — resources
# ═════════════════════════════════════════════════════════════════════

def get_line_styles():
    lines_cat = doc.Settings.Categories.get_Item(BuiltInCategory.OST_Lines)
    styles = []
    for sub in lines_cat.SubCategories:
        gs = sub.GetGraphicsStyle(GraphicsStyleType.Projection)
        if gs is not None:
            styles.append(gs)
    return sorted(styles, key=lambda s: s.Name)


def get_text_note_types():
    types = list(FilteredElementCollector(doc).OfClass(TextNoteType))
    return sorted(types, key=type_name)


def collect_plan_views():
    views = []
    for v in FilteredElementCollector(doc).OfClass(ViewPlan):
        try:
            if v.IsTemplate:
                continue
            if v.ViewType not in ALLOWED_VIEW_TYPES:
                continue
            if v.GenLevel is None:
                continue
        except Exception:
            continue
        views.append(v)
    views.sort(key=lambda v: (v.GenLevel.ProjectElevation, v.Name))
    return views


def get_loaded_links():
    links = []
    for inst in FilteredElementCollector(doc).OfClass(RevitLinkInstance):
        try:
            if inst.GetLinkDocument() is not None:
                links.append(inst)
        except Exception:
            pass
    return links


def get_cut_plane_elevation(view):
    """
    Absolute cut-plane elevation (ProjectElevation basis, host) of a
    plan view, or None when the view has no usable view range.
    """
    try:
        vr = view.GetViewRange()
    except Exception:
        return None
    if vr is None:
        return None

    lvl = None
    lvl_id = vr.GetLevelId(PlanViewPlane.CutPlane)
    if lvl_id is not None and lvl_id != ElementId.InvalidElementId:
        lvl = doc.GetElement(lvl_id)
    if not isinstance(lvl, Level):
        lvl = view.GenLevel
    if lvl is None:
        return None
    return lvl.ProjectElevation + vr.GetOffset(PlanViewPlane.CutPlane)


# ═════════════════════════════════════════════════════════════════════
# DATA COLLECTION — shafts (host + links)
# ═════════════════════════════════════════════════════════════════════
# Every lookup goes through shaft.Document so the same code serves the
# host document and each link document. ElementIds are never mixed
# across documents: host shafts are matched to views by Level Id, linked
# shafts by transformed level elevation.

def get_base_level(shaft):
    p = shaft.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT)
    if p is None:
        p = shaft.LookupParameter("Base Constraint")
    if p is None or p.StorageType != StorageType.ElementId:
        return None
    lvl = shaft.Document.GetElement(p.AsElementId())
    return lvl if isinstance(lvl, Level) else None


def get_base_offset(shaft):
    p = shaft.get_Parameter(BuiltInParameter.WALL_BASE_OFFSET)
    if p is None:
        p = shaft.LookupParameter("Base Offset")
    if p is None or p.StorageType != StorageType.Double:
        return None
    return p.AsDouble()


def get_shaft_function(shaft):
    """'Shaft Function' value from the instance, then its type (if any)."""
    src_doc = shaft.Document
    candidates = [shaft]
    try:
        type_id = shaft.GetTypeId()
        if type_id != ElementId.InvalidElementId:
            candidates.append(src_doc.GetElement(type_id))
    except Exception:
        pass

    for el in candidates:
        if el is None:
            continue
        p = el.LookupParameter(FUNCTION_PARAM)
        if p is None or not p.HasValue:
            continue
        if p.StorageType == StorageType.String:
            val = p.AsString()
        else:
            val = p.AsValueString()
        if val and val.strip():
            return val.strip()
    return None


def rectangle_curves(p_min, p_max, z):
    p1 = XYZ(p_min.X, p_min.Y, z)
    p2 = XYZ(p_max.X, p_min.Y, z)
    p3 = XYZ(p_max.X, p_max.Y, z)
    p4 = XYZ(p_min.X, p_max.Y, z)
    return [Line.CreateBound(p1, p2), Line.CreateBound(p2, p3),
            Line.CreateBound(p3, p4), Line.CreateBound(p4, p1)]


def get_raw_boundary(shaft):
    """
    Shaft sketch boundary in the shaft's OWN document coordinates:
    BoundaryCurves, then BoundaryRect, then a bounding-box rectangle.
    """
    try:
        bc = shaft.BoundaryCurves
        if bc is not None and bc.Size > 0:
            return [c for c in bc]
    except Exception:
        pass

    try:
        if shaft.IsRectBoundary:
            pts = list(shaft.BoundaryRect)
            if len(pts) == 2:
                mn = XYZ(min(pts[0].X, pts[1].X), min(pts[0].Y, pts[1].Y), 0)
                mx = XYZ(max(pts[0].X, pts[1].X), max(pts[0].Y, pts[1].Y), 0)
                return rectangle_curves(mn, mx, pts[0].Z)
    except Exception:
        pass

    bbox = shaft.get_BoundingBox(None)
    if bbox is None:
        return []
    return rectangle_curves(bbox.Min, bbox.Max, bbox.Min.Z)


def flatten_curve(curve, z, min_len):
    """
    Move a (horizontal) curve to elevation z by translation, which keeps
    the curve type intact (Line, Arc, Ellipse, Spline...).
    """
    try:
        dz = z - curve.GetEndPoint(0).Z
        flat = curve
        if abs(dz) > 1e-9:
            flat = curve.CreateTransformed(
                Transform.CreateTranslation(XYZ(0, 0, dz)))
        if flat.Length < min_len:
            return None
        return flat
    except Exception:
        return None


class ShaftData(object):
    """
    One shaft, already expressed in HOST coordinates.

    link_inst is None for host shafts. level_id_int is only meaningful
    for host shafts (it is a host ElementId). plane_z is the base level
    elevation in host coordinates for both sources.
    """
    def __init__(self, shaft, base_level, base_offset, curves, plane_z,
                 link_inst, source_label):
        self.shaft        = shaft
        self.link_inst    = link_inst
        self.source_label = source_label
        self.is_linked    = link_inst is not None
        self.level_id_int = None if self.is_linked else eid_int(base_level.Id)
        self.base_offset  = base_offset
        self.plane_z      = plane_z
        self.bottom_elev  = plane_z + base_offset
        self.curves       = curves
        self.function     = get_shaft_function(shaft)
        self.points = []
        for c in curves:
            try:
                self.points.extend(list(c.Tessellate()))
            except Exception:
                self.points.append(c.GetEndPoint(0))
                self.points.append(c.GetEndPoint(1))

    @property
    def ref_label(self):
        return u"{} | Shaft {}".format(self.source_label, eid_int(self.shaft.Id))


def collect_from_document(src_doc, xform, link_inst, source_label,
                          min_len, out, no_geom):
    shafts = (FilteredElementCollector(src_doc)
              .OfCategory(BuiltInCategory.OST_ShaftOpening)
              .WhereElementIsNotElementType()
              .ToElements())

    for shaft in shafts:
        base_level = get_base_level(shaft)
        if base_level is None:
            continue
        offset = get_base_offset(shaft)
        if offset is None or offset <= ELEV_TOL:
            continue

        # Base level elevation in host coordinates
        plane_z = xform.OfPoint(XYZ(0, 0, base_level.ProjectElevation)).Z

        curves = []
        for raw in get_raw_boundary(shaft):
            try:
                host_curve = raw if xform.IsIdentity else raw.CreateTransformed(xform)
            except Exception:
                continue
            flat = flatten_curve(host_curve, plane_z, min_len)
            if flat is not None:
                curves.append(flat)

        if not curves:
            no_geom.append(u"{} | Shaft {}".format(source_label, eid_int(shaft.Id)))
            continue

        out.append(ShaftData(shaft, base_level, offset, curves, plane_z,
                             link_inst, source_label))


def collect_shafts(links):
    """
    Returns (host_by_level, linked_list, no_geom_labels)
      host_by_level -> {host_level_id_int: [ShaftData, ...]}
      linked_list   -> [ShaftData, ...] from every loaded link instance
    Only shafts with a positive Base Offset are kept.
    """
    min_len = doc.Application.ShortCurveTolerance
    no_geom = []

    host_list = []
    collect_from_document(doc, Transform.Identity, None, u"Host",
                          min_len, host_list, no_geom)
    host_by_level = {}
    for sd in host_list:
        host_by_level.setdefault(sd.level_id_int, []).append(sd)

    linked_list = []
    for inst in links:
        try:
            link_doc = inst.GetLinkDocument()
            xform    = inst.GetTotalTransform()
            label    = link_doc.Title
        except Exception:
            continue
        collect_from_document(link_doc, xform, inst, label,
                              min_len, linked_list, no_geom)

    return host_by_level, linked_list, no_geom


# ═════════════════════════════════════════════════════════════════════
# VIEW ↔ SHAFT MATCHING
# ═════════════════════════════════════════════════════════════════════

def points_in_crop(view, points):
    """True when the shaft outline overlaps the view's active crop box."""
    try:
        if not view.CropBoxActive:
            return True
        cb  = view.CropBox
        inv = cb.Transform.Inverse
        local = [inv.OfPoint(p) for p in points]
        xs = [p.X for p in local]
        ys = [p.Y for p in local]
        if max(xs) < cb.Min.X or min(xs) > cb.Max.X:
            return False
        if max(ys) < cb.Min.Y or min(ys) > cb.Max.Y:
            return False
        return True
    except Exception:
        return True


def links_category_hidden(view):
    try:
        return view.GetCategoryHidden(ElementId(BuiltInCategory.OST_RvtLinks))
    except Exception:
        return False


def link_hidden_in_view(view, link_inst, cache):
    key = eid_int(link_inst.Id)
    if key not in cache:
        try:
            cache[key] = link_inst.IsHidden(view)
        except Exception:
            cache[key] = False
    return cache[key]


class ViewRow(object):
    def __init__(self, view, cut_elev, candidates):
        self.view       = view
        self.level      = view.GenLevel
        self.cut_elev   = cut_elev
        self.candidates = candidates      # [(ShaftData, inside_crop), ...]

    def count(self, host_on=True, link_on=True, crop_only=False):
        n = 0
        for sd, inside in self.candidates:
            if sd.is_linked and not link_on:
                continue
            if not sd.is_linked and not host_on:
                continue
            if crop_only and not inside:
                continue
            n += 1
        return n


def build_view_rows(views, host_by_level, linked_list):
    rows = []
    for view in views:
        cut_elev   = get_cut_plane_elevation(view)
        candidates = []

        if cut_elev is not None:
            view_z = view.GenLevel.ProjectElevation

            # Host: same Level element as the view
            for sd in host_by_level.get(eid_int(view.GenLevel.Id), []):
                if sd.bottom_elev > cut_elev + ELEV_TOL:
                    candidates.append((sd, points_in_crop(view, sd.points)))

            # Links: level at the view's elevation, link visible in view
            if linked_list and not links_category_hidden(view):
                hidden_cache = {}
                for sd in linked_list:
                    if abs(sd.plane_z - view_z) > LEVEL_MATCH_TOL:
                        continue
                    if sd.bottom_elev <= cut_elev + ELEV_TOL:
                        continue
                    if link_hidden_in_view(view, sd.link_inst, hidden_cache):
                        continue
                    candidates.append((sd, points_in_crop(view, sd.points)))

        rows.append(ViewRow(view, cut_elev, candidates))
    return rows


# ═════════════════════════════════════════════════════════════════════
# GEOMETRY IN VIEW AXES
# ═════════════════════════════════════════════════════════════════════

def view_bounds(points, right, up):
    """(u_min, u_max, v_min, v_max) of points along the view's axes."""
    us = [p.X * right.X + p.Y * right.Y for p in points]
    vs = [p.X * up.X + p.Y * up.Y for p in points]
    return min(us), max(us), min(vs), max(vs)


def to_model(right, up, u, v, z):
    return XYZ(right.X * u + up.X * v, right.Y * u + up.Y * v, z)


def quad_corners(curves):
    """
    Four corner points (ordered around the centroid) when the boundary
    is a single 4-line loop, e.g. a rotated rectangle. Otherwise None.
    """
    if len(curves) != 4:
        return None
    if any(not isinstance(c, Line) for c in curves):
        return None

    pts = []
    for c in curves:
        for i in (0, 1):
            p = c.GetEndPoint(i)
            if not any(p.IsAlmostEqualTo(q) for q in pts):
                pts.append(p)
    if len(pts) != 4:
        return None

    cx = sum(p.X for p in pts) / 4.0
    cy = sum(p.Y for p in pts) / 4.0
    pts.sort(key=lambda p: math.atan2(p.Y - cy, p.X - cx))
    return pts


def x_mark_lines(curves, bounds, right, up, z):
    corners = quad_corners(curves)
    if corners:
        pairs = [(corners[0], corners[2]), (corners[1], corners[3])]
    else:
        u_min, u_max, v_min, v_max = bounds
        bl = to_model(right, up, u_min, v_min, z)
        br = to_model(right, up, u_max, v_min, z)
        tr = to_model(right, up, u_max, v_max, z)
        tl = to_model(right, up, u_min, v_max, z)
        pairs = [(bl, tr), (br, tl)]

    lines = []
    for a, b in pairs:
        pa = XYZ(a.X, a.Y, z)
        pb = XYZ(b.X, b.Y, z)
        if pa.DistanceTo(pb) > 1e-6:
            lines.append(Line.CreateBound(pa, pb))
    return lines


# ═════════════════════════════════════════════════════════════════════
# ANNOTATE ONE SHAFT IN ONE VIEW (caller owns the transaction)
# ═════════════════════════════════════════════════════════════════════

def new_detail_line(view, curve, line_style):
    dc = doc.Create.NewDetailCurve(view, curve)
    dc.LineStyle = line_style
    dc.Pinned = True
    return dc


def new_text_note(view, pos, text, type_id, h_align, v_align):
    opts = TextNoteOptions(type_id)
    opts.HorizontalAlignment = h_align
    opts.VerticalAlignment   = v_align
    note = TextNote.Create(doc, view.Id, pos, text, opts)
    note.Pinned = True
    return note


def annotate_shaft(view, sd, cfg):
    right   = view.RightDirection
    up      = view.UpDirection
    z       = view.GenLevel.ProjectElevation
    scale   = float(view.Scale) if view.Scale else 100.0
    min_len = doc.Application.ShortCurveTolerance
    style   = cfg['line_style']

    # Curves sit on the shaft's base level plane; linked levels can be a
    # few mm off the host level, so drop them onto the view's level.
    curves = []
    for c in sd.curves:
        flat = flatten_curve(c, z, min_len)
        if flat is not None:
            curves.append(flat)
    if not curves:
        raise Exception("No valid boundary curves at the view level.")

    # 1. Boundary
    for curve in curves:
        new_detail_line(view, curve, style)

    bounds = view_bounds(sd.points, right, up)
    u_min, u_max, v_min, v_max = bounds

    # 2. X mark (same line style)
    if cfg['draw_x']:
        for diag in x_mark_lines(curves, bounds, right, up, z):
            new_detail_line(view, diag, style)

    # 3. Label below the shaft (centred, hanging from its top edge)
    if cfg['label_text']:
        gap = cfg['label_gap_mm'] * FT_PER_MM * scale
        pos = to_model(right, up, (u_min + u_max) / 2.0, v_min - gap, z)
        new_text_note(view, pos, cfg['label_text'], cfg['label_type_id'],
                      HorizontalTextAlignment.Center, VerticalTextAlignment.Top)

    # 4. Shaft Function — inner bottom-left corner
    if cfg['function_on'] and sd.function:
        inset = cfg['function_inset_mm'] * FT_PER_MM * scale
        pos = to_model(right, up, u_min + inset, v_min + inset, z)
        new_text_note(view, pos, sd.function, cfg['function_type_id'],
                      HorizontalTextAlignment.Left, VerticalTextAlignment.Bottom)


# ═════════════════════════════════════════════════════════════════════
# RUN — one TransactionGroup, one Transaction per view,
#       one SubTransaction per shaft
# ═════════════════════════════════════════════════════════════════════

def run(cfg):
    results = []

    tg = TransactionGroup(doc, TOOL_TITLE)
    tg.Start()
    try:
        for row in cfg['rows']:
            res = {'view': row.view.Name, 'host': 0, 'linked': 0,
                   'outside': 0, 'failed': [], 'error': None}

            t = Transaction(doc, "{} - {}".format(TOOL_TITLE, row.view.Name))
            t.Start()
            try:
                for sd, inside in row.candidates:
                    if sd.is_linked and not cfg['link_on']:
                        continue
                    if not sd.is_linked and not cfg['host_on']:
                        continue
                    if cfg['crop_only'] and not inside:
                        res['outside'] += 1
                        continue

                    st = SubTransaction(doc)
                    st.Start()
                    try:
                        annotate_shaft(row.view, sd, cfg)
                        st.Commit()
                        res['linked' if sd.is_linked else 'host'] += 1
                    except Exception as ex:
                        st.RollBack()
                        res['failed'].append((sd.ref_label, str(ex)))
                t.Commit()
            except Exception as ex:
                t.RollBack()
                res['host'] = 0
                res['linked'] = 0
                res['error'] = str(ex)

            results.append(res)

        tg.Assimilate()
    except Exception:
        tg.RollBack()
        raise

    return results


def report(results, no_geom):
    total = sum(r['host'] + r['linked'] for r in results)
    lines = ["{} shaft(s) annotated in {} view(s).".format(total, len(results)),
             ""]

    for r in results[:30]:
        line = u"\u2022 {}: {} host, {} linked".format(
            r['view'], r['host'], r['linked'])
        if r['outside']:
            line += ", {} outside crop (skipped)".format(r['outside'])
        if r['failed']:
            line += ", {} failed".format(len(r['failed']))
        if r['error']:
            line += "  [view rolled back: {}]".format(r['error'])
        lines.append(line)
    if len(results) > 30:
        lines.append("  ... and {} more view(s)".format(len(results) - 30))

    failures = [(r['view'], f) for r in results for f in r['failed']]
    if failures:
        lines.append("")
        lines.append("Failures:")
        for view_name, (ref, err) in failures[:15]:
            lines.append(u"  {} | {}: {}".format(view_name, ref, err))

    if no_geom:
        lines.append("")
        lines.append(u"Shafts with no readable boundary (ignored):")
        for ref in no_geom[:15]:
            lines.append(u"  " + ref)

    forms.alert("\n".join(lines), title=TOOL_TITLE)


# ═════════════════════════════════════════════════════════════════════
# WPF DIALOG
# ═════════════════════════════════════════════════════════════════════

XAML = u"""
<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Shafts - Open Above"
    Width="880" Height="720" MinWidth="780" MinHeight="560"
    WindowStartupLocation="CenterScreen"
    Background="#161616" Foreground="#F4F4F4"
    FontFamily="Segoe UI" FontSize="12">

    <Window.Resources>
        <Style x:Key="BtnBase" TargetType="Button">
            <Setter Property="Foreground" Value="#F4F4F4"/>
            <Setter Property="Background" Value="#393939"/>
            <Setter Property="BorderBrush" Value="#525252"/>
            <Setter Property="Height" Value="32"/>
            <Setter Property="Padding" Value="14,0"/>
            <Setter Property="Cursor" Value="Hand"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="Button">
                        <Border x:Name="Bd"
                                Background="{TemplateBinding Background}"
                                BorderBrush="{TemplateBinding BorderBrush}"
                                BorderThickness="1" CornerRadius="4"
                                Padding="{TemplateBinding Padding}">
                            <ContentPresenter HorizontalAlignment="Center"
                                              VerticalAlignment="Center"/>
                        </Border>
                        <ControlTemplate.Triggers>
                            <Trigger Property="IsMouseOver" Value="True">
                                <Setter TargetName="Bd" Property="Opacity" Value="0.85"/>
                            </Trigger>
                            <Trigger Property="IsEnabled" Value="False">
                                <Setter TargetName="Bd" Property="Opacity" Value="0.4"/>
                            </Trigger>
                        </ControlTemplate.Triggers>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>

        <Style x:Key="BtnPrimary" TargetType="Button" BasedOn="{StaticResource BtnBase}">
            <Setter Property="Background" Value="#F1C21B"/>
            <Setter Property="Foreground" Value="#161616"/>
            <Setter Property="BorderBrush" Value="#F1C21B"/>
            <Setter Property="FontWeight" Value="Bold"/>
        </Style>

        <Style x:Key="Section" TargetType="TextBlock">
            <Setter Property="Foreground" Value="#F1C21B"/>
            <Setter Property="FontWeight" Value="Bold"/>
            <Setter Property="FontSize" Value="11"/>
            <Setter Property="Margin" Value="0,2,0,10"/>
        </Style>

        <Style x:Key="FieldLabel" TargetType="TextBlock">
            <Setter Property="Foreground" Value="#A8A8A8"/>
            <Setter Property="FontWeight" Value="SemiBold"/>
            <Setter Property="Margin" Value="0,0,0,4"/>
        </Style>

        <Style x:Key="Input" TargetType="TextBox">
            <Setter Property="Height" Value="28"/>
            <Setter Property="Padding" Value="6,0"/>
            <Setter Property="Margin" Value="0,0,0,12"/>
            <Setter Property="Background" Value="#161616"/>
            <Setter Property="Foreground" Value="#F4F4F4"/>
            <Setter Property="BorderBrush" Value="#525252"/>
            <Setter Property="CaretBrush" Value="#F1C21B"/>
            <Setter Property="VerticalContentAlignment" Value="Center"/>
        </Style>

        <Style TargetType="ComboBox">
            <Setter Property="Height" Value="28"/>
            <Setter Property="Margin" Value="0,0,0,12"/>
            <Setter Property="Background" Value="#FFFFFF"/>
            <Setter Property="Foreground" Value="#161616"/>
            <Setter Property="BorderBrush" Value="#525252"/>
            <Setter Property="VerticalContentAlignment" Value="Center"/>
            <Setter Property="ItemContainerStyle">
                <Setter.Value>
                    <Style TargetType="ComboBoxItem">
                        <Setter Property="Foreground" Value="#161616"/>
                        <Setter Property="Background" Value="#FFFFFF"/>
                        <Style.Triggers>
                            <Trigger Property="IsHighlighted" Value="True">
                                <Setter Property="Background" Value="#E0E0E0"/>
                            </Trigger>
                        </Style.Triggers>
                    </Style>
                </Setter.Value>
            </Setter>
        </Style>

        <Style TargetType="CheckBox">
            <Setter Property="Foreground" Value="#F4F4F4"/>
            <Setter Property="VerticalContentAlignment" Value="Center"/>
        </Style>
    </Window.Resources>

    <Grid Margin="18">
        <Grid.ColumnDefinitions>
            <ColumnDefinition Width="*"/>
            <ColumnDefinition Width="16"/>
            <ColumnDefinition Width="320"/>
        </Grid.ColumnDefinitions>
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <!-- Header -->
        <StackPanel Grid.Row="0" Grid.ColumnSpan="3" Margin="0,0,0,14">
            <TextBlock Text="SHAFTS - OPEN ABOVE" FontSize="15"
                       FontWeight="Bold" Foreground="#F1C21B"/>
            <TextBlock x:Name="SummaryText" Foreground="#A8A8A8"
                       FontSize="11" Margin="0,4,0,0" TextWrapping="Wrap"/>
        </StackPanel>

        <!-- Left: plan views -->
        <Border Grid.Row="1" Grid.Column="0" Background="#262626"
                CornerRadius="4" Padding="14">
            <Grid>
                <Grid.RowDefinitions>
                    <RowDefinition Height="Auto"/>
                    <RowDefinition Height="Auto"/>
                    <RowDefinition Height="Auto"/>
                    <RowDefinition Height="*"/>
                </Grid.RowDefinitions>

                <TextBlock Grid.Row="0" Text="PLAN VIEWS" Style="{StaticResource Section}"/>

                <Grid Grid.Row="1">
                    <TextBox x:Name="SearchBox" Style="{StaticResource Input}"/>
                    <TextBlock x:Name="SearchHint" Text="Search views or levels..."
                               Foreground="#6F6F6F" Margin="9,6,0,0"
                               IsHitTestVisible="False"/>
                </Grid>

                <DockPanel Grid.Row="2" Margin="0,0,0,10" LastChildFill="False">
                    <CheckBox x:Name="ApplicableOnly" DockPanel.Dock="Left"
                              IsChecked="True" VerticalAlignment="Center">
                        <TextBlock Text="Only views with open-above shafts"
                                   Foreground="#F4F4F4"/>
                    </CheckBox>
                    <Button x:Name="SelectNoneBtn" DockPanel.Dock="Right"
                            Content="None" Height="26" Margin="6,0,0,0"
                            Style="{StaticResource BtnBase}"/>
                    <Button x:Name="SelectAllBtn" DockPanel.Dock="Right"
                            Content="All" Height="26"
                            Style="{StaticResource BtnBase}"/>
                </DockPanel>

                <Border Grid.Row="3" Background="#161616" BorderBrush="#393939"
                        BorderThickness="1" CornerRadius="4">
                    <Grid>
                        <ScrollViewer VerticalScrollBarVisibility="Auto"
                                      HorizontalScrollBarVisibility="Disabled">
                            <StackPanel x:Name="ViewPanel" Margin="6"/>
                        </ScrollViewer>
                        <TextBlock x:Name="EmptyHint" Text="No views match."
                                   Foreground="#6F6F6F"
                                   HorizontalAlignment="Center"
                                   VerticalAlignment="Center"
                                   Visibility="Collapsed"/>
                    </Grid>
                </Border>
            </Grid>
        </Border>

        <!-- Right: settings -->
        <Border Grid.Row="1" Grid.Column="2" Background="#262626"
                CornerRadius="4" Padding="14">
            <ScrollViewer VerticalScrollBarVisibility="Auto"
                          HorizontalScrollBarVisibility="Disabled">
                <StackPanel>
                    <TextBlock Text="SOURCES" Style="{StaticResource Section}"/>
                    <CheckBox x:Name="HostCheck" IsChecked="True" Margin="0,0,0,8">
                        <TextBlock Text="Host model shafts" Foreground="#F4F4F4"/>
                    </CheckBox>
                    <CheckBox x:Name="LinkCheck" IsChecked="True" Margin="0,0,0,12">
                        <TextBlock x:Name="LinkCheckText" Text="Linked model shafts"
                                   Foreground="#F4F4F4"/>
                    </CheckBox>

                    <TextBlock Text="DETAIL LINES" Style="{StaticResource Section}" Margin="0,8,0,10"/>
                    <TextBlock Text="Line style (boundary + X mark)" Style="{StaticResource FieldLabel}"/>
                    <ComboBox x:Name="LineStyleCombo"/>
                    <CheckBox x:Name="DrawXCheck" IsChecked="True" Margin="0,0,0,12">
                        <TextBlock Text="Draw X mark" Foreground="#F4F4F4"/>
                    </CheckBox>

                    <TextBlock Text="LABEL" Style="{StaticResource Section}" Margin="0,8,0,10"/>
                    <TextBlock Text="Label text (below shaft)" Style="{StaticResource FieldLabel}"/>
                    <TextBox x:Name="LabelTextBox" Text="OPEN ABOVE" Style="{StaticResource Input}"/>
                    <TextBlock Text="Label text type" Style="{StaticResource FieldLabel}"/>
                    <ComboBox x:Name="LabelTypeCombo"/>
                    <TextBlock Text="Gap below shaft (paper mm)" Style="{StaticResource FieldLabel}"/>
                    <TextBox x:Name="LabelGapBox" Text="2" Style="{StaticResource Input}"/>

                    <TextBlock Text="SHAFT FUNCTION" Style="{StaticResource Section}" Margin="0,8,0,10"/>
                    <CheckBox x:Name="FunctionCheck" IsChecked="True" Margin="0,0,0,8">
                        <TextBlock Text="Write the Shaft Function value" Foreground="#F4F4F4"/>
                    </CheckBox>
                    <TextBlock Text="Function text type" Style="{StaticResource FieldLabel}"/>
                    <ComboBox x:Name="FunctionTypeCombo"/>
                    <TextBlock Text="Inset from bottom-left corner (paper mm)"
                               Style="{StaticResource FieldLabel}"/>
                    <TextBox x:Name="FunctionInsetBox" Text="1" Style="{StaticResource Input}"/>

                    <TextBlock Text="OPTIONS" Style="{StaticResource Section}" Margin="0,8,0,10"/>
                    <CheckBox x:Name="CropOnlyCheck" IsChecked="True">
                        <TextBlock Text="Skip shafts outside the view's crop region"
                                   Foreground="#F4F4F4" TextWrapping="Wrap"/>
                    </CheckBox>
                </StackPanel>
            </ScrollViewer>
        </Border>

        <!-- Footer -->
        <DockPanel Grid.Row="2" Grid.ColumnSpan="3" Margin="0,14,0,0">
            <Button x:Name="DrawBtn" DockPanel.Dock="Right" Content="Draw"
                    Width="110" Style="{StaticResource BtnPrimary}"/>
            <Button x:Name="CancelBtn" DockPanel.Dock="Right" Content="Cancel"
                    Width="90" Margin="0,0,10,0" Style="{StaticResource BtnBase}"/>
            <TextBlock x:Name="StatusText" Foreground="#A8A8A8"
                       VerticalAlignment="Center"/>
        </DockPanel>
    </Grid>
</Window>
"""


def row_subtext(row, host_on, link_on):
    parts = [row.level.Name, view_type_label(row.view)]
    n_host = row.count(host_on, False)
    n_link = row.count(False, link_on)
    n = n_host + n_link

    if row.cut_elev is None:
        parts.append(u"no view range")
    elif n == 0:
        parts.append(u"no open-above shafts")
    else:
        s = plural(n, u"open-above shaft")
        split = []
        if n_host:
            split.append(u"{} host".format(n_host))
        if n_link:
            split.append(u"{} linked".format(n_link))
        s += u" ({})".format(u", ".join(split))
        outside = n - row.count(host_on, link_on, crop_only=True)
        if outside:
            s += u", {} outside crop".format(outside)
        parts.append(s)
    return u"  \u00B7  ".join(parts)


def make_view_checkbox(row):
    cb = CheckBox()
    cb.Margin = Thickness(4, 4, 4, 4)
    cb.VerticalContentAlignment = VerticalAlignment.Center

    panel = StackPanel()
    panel.Margin = Thickness(4, 0, 0, 0)

    title = TextBlock()
    title.Text = row.view.Name
    sub = TextBlock()
    sub.FontSize = 10.5

    panel.Children.Add(title)
    panel.Children.Add(sub)
    cb.Content = panel
    return cb, title, sub


def show_dialog(rows, line_styles, text_types, n_host, n_linked, n_links, no_geom):
    window = XamlReader.Parse(XAML)
    try:
        WindowInteropHelper(window).Owner = __revit__.MainWindowHandle
    except Exception:
        pass

    f = window.FindName
    summary_txt   = f('SummaryText')
    search_box    = f('SearchBox')
    search_hint   = f('SearchHint')
    applicable_cb = f('ApplicableOnly')
    all_btn       = f('SelectAllBtn')
    none_btn      = f('SelectNoneBtn')
    view_panel    = f('ViewPanel')
    empty_hint    = f('EmptyHint')
    host_cb       = f('HostCheck')
    link_cb       = f('LinkCheck')
    link_cb_text  = f('LinkCheckText')
    style_cmb     = f('LineStyleCombo')
    draw_x_cb     = f('DrawXCheck')
    label_tb      = f('LabelTextBox')
    label_cmb     = f('LabelTypeCombo')
    gap_tb        = f('LabelGapBox')
    function_cb   = f('FunctionCheck')
    function_cmb  = f('FunctionTypeCombo')
    inset_tb      = f('FunctionInsetBox')
    crop_cb       = f('CropOnlyCheck')
    status_txt    = f('StatusText')
    cancel_btn    = f('CancelBtn')
    draw_btn      = f('DrawBtn')

    # ── Header summary ───────────────────────────────────────────────
    summary = (u"Shafts with a positive Base Offset: {} host, {} linked "
               u"(across {}). Views list the ones that start above their "
               u"cut plane.".format(n_host, n_linked,
                                    plural(n_links, u"loaded link")))
    if no_geom:
        summary += u"  {} had no readable boundary.".format(len(no_geom))
    summary_txt.Text = summary

    if n_links == 0:
        link_cb.IsChecked = False
        link_cb.IsEnabled = False
        link_cb_text.Text = u"Linked model shafts (no loaded links)"

    # ── Combos ───────────────────────────────────────────────────────
    for gs in line_styles:
        style_cmb.Items.Add(gs.Name)
    for tt in text_types:
        name = type_name(tt)
        label_cmb.Items.Add(name)
        function_cmb.Items.Add(name)
    for cmb in (style_cmb, label_cmb, function_cmb):
        if cmb.Items.Count > 0:
            cmb.SelectedIndex = 0

    # ── View list ────────────────────────────────────────────────────
    items = []
    state = {'cfg': None}
    active_id = eid_int(doc.ActiveView.Id)

    def sources():
        return host_cb.IsChecked == True, link_cb.IsChecked == True

    def update_status(*args):
        host_on, link_on = sources()
        crop_only = crop_cb.IsChecked == True
        selected = [it for it in items if it['cb'].IsChecked == True]
        n_shafts = sum(it['row'].count(host_on, link_on, crop_only)
                       for it in selected)
        status_txt.Text = u"{} selected  \u00B7  {} to annotate".format(
            plural(len(selected), u"view"), plural(n_shafts, u"shaft"))
        draw_btn.IsEnabled = n_shafts > 0

    def refresh_rows():
        host_on, link_on = sources()
        for it in items:
            n = it['row'].count(host_on, link_on)
            it['title'].Foreground = hex_brush(C_TEXT if n else C_DIM)
            it['sub'].Foreground = hex_brush(C_SUBTEXT if n else C_DIM)
            it['sub'].Text = row_subtext(it['row'], host_on, link_on)

    def apply_filter(*args):
        host_on, link_on = sources()
        query = (search_box.Text or u"").strip().lower()
        search_hint.Visibility = (Visibility.Collapsed if search_box.Text
                                  else Visibility.Visible)
        only_applicable = applicable_cb.IsChecked == True
        visible = 0
        for it in items:
            show = True
            if only_applicable and it['row'].count(host_on, link_on) == 0:
                show = False
            if show and query and query not in it['key']:
                show = False
            it['cb'].Visibility = Visibility.Visible if show else Visibility.Collapsed
            if show:
                visible += 1
        empty_hint.Visibility = (Visibility.Visible if visible == 0
                                 else Visibility.Collapsed)
        update_status()

    def on_sources_changed(*args):
        refresh_rows()
        apply_filter()

    for row in rows:
        cb, title, sub = make_view_checkbox(row)
        if eid_int(row.view.Id) == active_id and row.count() > 0:
            cb.IsChecked = True
        cb.Checked   += RoutedEventHandler(update_status)
        cb.Unchecked += RoutedEventHandler(update_status)
        view_panel.Children.Add(cb)
        items.append({
            'row':   row,
            'cb':    cb,
            'title': title,
            'sub':   sub,
            'key':   u"{} {}".format(row.view.Name, row.level.Name).lower(),
        })

    # ── Handlers ─────────────────────────────────────────────────────
    def set_visible(checked):
        for it in items:
            if it['cb'].Visibility == Visibility.Visible:
                it['cb'].IsChecked = checked
        update_status()

    def on_all(s, e):
        set_visible(True)

    def on_none(s, e):
        set_visible(False)

    def sync_enabled(*args):
        fn_on = function_cb.IsChecked == True
        function_cmb.IsEnabled = fn_on
        inset_tb.IsEnabled = fn_on

    def on_cancel(s, e):
        window.Close()

    def on_draw(s, e):
        host_on, link_on = sources()
        if not host_on and not link_on:
            forms.alert("Tick at least one source (host or linked).",
                        title=TOOL_TITLE)
            return
        selected = [it['row'] for it in items if it['cb'].IsChecked == True]
        if not selected:
            forms.alert("Select at least one plan view.", title=TOOL_TITLE)
            return
        if style_cmb.SelectedIndex < 0:
            forms.alert("Select a line style.", title=TOOL_TITLE)
            return
        if label_cmb.SelectedIndex < 0 or function_cmb.SelectedIndex < 0:
            forms.alert("Select the text note types.", title=TOOL_TITLE)
            return

        gap_mm = parse_mm(gap_tb.Text)
        inset_mm = parse_mm(inset_tb.Text)
        if gap_mm is None or inset_mm is None:
            forms.alert("Gap and inset must be numbers of 0 or more (paper mm).",
                        title=TOOL_TITLE)
            return

        state['cfg'] = {
            'rows':              selected,
            'host_on':           host_on,
            'link_on':           link_on,
            'line_style':        line_styles[style_cmb.SelectedIndex],
            'draw_x':            draw_x_cb.IsChecked == True,
            'label_text':        (label_tb.Text or u"").strip(),
            'label_type_id':     text_types[label_cmb.SelectedIndex].Id,
            'label_gap_mm':      gap_mm,
            'function_on':       function_cb.IsChecked == True,
            'function_type_id':  text_types[function_cmb.SelectedIndex].Id,
            'function_inset_mm': inset_mm,
            'crop_only':         crop_cb.IsChecked == True,
        }
        window.Close()

    search_box.TextChanged  += TextChangedEventHandler(apply_filter)
    applicable_cb.Checked   += RoutedEventHandler(apply_filter)
    applicable_cb.Unchecked += RoutedEventHandler(apply_filter)
    host_cb.Checked         += RoutedEventHandler(on_sources_changed)
    host_cb.Unchecked       += RoutedEventHandler(on_sources_changed)
    link_cb.Checked         += RoutedEventHandler(on_sources_changed)
    link_cb.Unchecked       += RoutedEventHandler(on_sources_changed)
    crop_cb.Checked         += RoutedEventHandler(update_status)
    crop_cb.Unchecked       += RoutedEventHandler(update_status)
    function_cb.Checked     += RoutedEventHandler(sync_enabled)
    function_cb.Unchecked   += RoutedEventHandler(sync_enabled)
    all_btn.Click           += RoutedEventHandler(on_all)
    none_btn.Click          += RoutedEventHandler(on_none)
    cancel_btn.Click        += RoutedEventHandler(on_cancel)
    draw_btn.Click          += RoutedEventHandler(on_draw)

    refresh_rows()
    apply_filter()
    sync_enabled()

    # ── Blocking show via PushFrame ──────────────────────────────────
    frame = DispatcherFrame()

    def on_closed(s, e):
        frame.Continue = False

    window.Closed += EventHandler(on_closed)
    window.Show()
    Dispatcher.PushFrame(frame)

    return state['cfg']


# ═════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════

def main():
    views = collect_plan_views()
    if not views:
        forms.alert("No Floor Plan or Structural Plan views found.",
                    title=TOOL_TITLE)
        return

    line_styles = get_line_styles()
    if not line_styles:
        forms.alert("No line styles found in the document.", title=TOOL_TITLE)
        return

    text_types = get_text_note_types()
    if not text_types:
        forms.alert("No text note types found in the document.",
                    title=TOOL_TITLE)
        return

    links = get_loaded_links()
    host_by_level, linked_list, no_geom = collect_shafts(links)
    n_host   = sum(len(v) for v in host_by_level.values())
    n_linked = len(linked_list)
    if n_host + n_linked == 0:
        forms.alert("No Shaft Openings with a positive Base Offset were found "
                    "in the host model or in any loaded link.", title=TOOL_TITLE)
        return

    rows = build_view_rows(views, host_by_level, linked_list)

    cfg = show_dialog(rows, line_styles, text_types,
                      n_host, n_linked, len(links), no_geom)
    if not cfg:
        return

    results = run(cfg)
    report(results, no_geom)


main()
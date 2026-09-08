# -*- coding: utf-8 -*-
"""
MEP Branch Tracer  (v6 — Revit 2024+ Compatible · Catppuccin UI)
=================================================================
Traces the complete connected branch of a selected MEP element residing
in a Revit linked file, then:
  1. Applies a section box to the active 3D view isolating the branch.
  2. Creates one Generic Model DirectShape bounding-box solid per traced
     element with a cyan / 50 % transparent override in the active view.
  3. Shows a Catppuccin-themed WPF overlay dialog with trace statistics.
  4. On dismiss (ESC / button / close), deletes every DirectShape and exits.

Fix (v6):  Category recognition no longer uses int() or IntegerValue.
           ElementId-based set lookup + Category.BuiltInCategory (2023+)
           covers every Revit version cleanly.

Compatible with: pyRevit 4.x, IronPython 2.7, Revit 2020–2027+
"""

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('System')
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')

from Autodesk.Revit.DB import (
    FilteredElementCollector, RevitLinkInstance,
    BoundingBoxIntersectsFilter, BoundingBoxXYZ, Outline,
    Transform, XYZ, ElementId, BuiltInCategory, BuiltInParameter,
    Transaction, View3D,
    DirectShape, CurveLoop, Line,
    GeometryCreationUtilities,
    OverrideGraphicSettings, Color,
    FillPatternElement,
)
from Autodesk.Revit.UI import TaskDialog
from Autodesk.Revit.UI.Selection import ObjectType
from System.Collections.Generic import List
from System.Windows.Markup import XamlReader
from System.Windows.Threading import Dispatcher, DispatcherFrame
import System.Windows as SW

# ── pyRevit output ─────────────────────────────────────────────────────────────
try:
    from pyrevit import script
    output = script.get_output()
    def log(msg):              output.print_md(msg)
    def log_header(msg):       output.print_md("### " + msg)
    def log_table(hdrs, rows): output.print_table(rows, columns=hdrs)
    HAS_OUTPUT = True
except Exception:
    HAS_OUTPUT = False
    _log_lines = []
    def log(msg):        _log_lines.append(str(msg))
    def log_header(msg): _log_lines.append("\n" + msg.upper())
    def log_table(h, rows):
        _log_lines.append("\t".join(h))
        for r in rows: _log_lines.append("\t".join(str(c) for c in r))

doc   = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

# ── Tuneable constants ─────────────────────────────────────────────────────────
MATCH_TOLERANCE     = 0.05   # feet (~15 mm)
SECTION_BOX_PADDING = 1.0    # feet (~300 mm)
HIGHLIGHT_PADDING   = 0.05   # feet (~15 mm)
HIGHLIGHT_COLOR     = Color(0, 255, 255)   # cyan
HIGHLIGHT_TRANSP    = 50                   # percent

# ── MEP category registry ──────────────────────────────────────────────────────
#
#   IMPORTANT (Revit 2024+):
#   ElementId's internal storage moved from Int32 to Int64.  Converting a
#   BuiltInCategory to int and using that as a dict key breaks equality checks
#   against ElementId objects (different types → different hashes).
#
#   Fix: build lookup structures from ElementId(bic) objects and, where
#   available, from the BuiltInCategory enum directly via
#   Category.BuiltInCategory (added in Revit 2023).  Both paths avoid
#   IntegerValue / int() entirely.
#
MEP_CATEGORY_MAP = [
    (BuiltInCategory.OST_PipeCurves,          "Pipe"),
    (BuiltInCategory.OST_PipeFitting,         "Pipe Fitting"),
    (BuiltInCategory.OST_PipeAccessory,       "Pipe Accessory"),
    (BuiltInCategory.OST_FlexPipeCurves,      "Flex Pipe"),
    (BuiltInCategory.OST_DuctCurves,          "Duct"),
    (BuiltInCategory.OST_DuctFitting,         "Duct Fitting"),
    (BuiltInCategory.OST_DuctAccessory,       "Duct Accessory"),
    (BuiltInCategory.OST_FlexDuctCurves,      "Flex Duct"),
    (BuiltInCategory.OST_CableTray,           "Cable Tray"),
    (BuiltInCategory.OST_CableTrayFitting,    "Cable Tray Fitting"),
    (BuiltInCategory.OST_Conduit,             "Conduit"),
    (BuiltInCategory.OST_ConduitFitting,      "Conduit Fitting"),
    (BuiltInCategory.OST_MechanicalEquipment, "Mech. Equipment"),
    (BuiltInCategory.OST_PlumbingFixtures,    "Plumbing Fixture"),
]

# Path A — BuiltInCategory enum  (Revit 2023+, most direct)
_BIC_LABEL = {bic: label for bic, label in MEP_CATEGORY_MAP}
_BIC_SET   = set(_BIC_LABEL.keys())

# Path B — ElementId equality  (all Revit versions; no int/IntegerValue)
_MEP_ID_LABEL = {ElementId(bic): label for bic, label in MEP_CATEGORY_MAP}


def _elem_bic(elem):
    """Return the BuiltInCategory of elem.Category, or None if not available."""
    try:
        return elem.Category.BuiltInCategory   # Revit 2023+
    except Exception:
        return None


def is_mep_element(elem):
    if elem is None or elem.Category is None:
        return False
    bic = _elem_bic(elem)
    if bic is not None:
        return bic in _BIC_SET                 # fast enum comparison
    return elem.Category.Id in _MEP_ID_LABEL  # ElementId equality fallback


def cat_label(elem):
    if elem is None or elem.Category is None:
        return "Unknown"
    bic = _elem_bic(elem)
    if bic is not None:
        return _BIC_LABEL.get(bic, elem.Category.Name)
    return _MEP_ID_LABEL.get(elem.Category.Id,
                              elem.Category.Name if elem.Category else "Unknown")

# ── Misc helpers ───────────────────────────────────────────────────────────────

def type_name(elem, elem_doc):
    try:
        t = elem_doc.GetElement(elem.GetTypeId())
        if t:
            p = t.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME)
            if p and p.AsString():
                return p.AsString()
            return t.Name
    except Exception:
        pass
    return ""


def elem_key(elem, elem_doc):
    return (elem_doc.PathName, elem.Id)

# ── Connector helpers ──────────────────────────────────────────────────────────

def get_connector_manager(elem):
    cm = getattr(elem, 'ConnectorManager', None)
    if cm is not None:
        return cm
    mep = getattr(elem, 'MEPModel', None)
    if mep is not None:
        return getattr(mep, 'ConnectorManager', None)
    return None


def get_connectors(elem):
    cm = get_connector_manager(elem)
    return list(cm.Connectors) if cm else []

# ── Linked file cache ──────────────────────────────────────────────────────────

def get_link_data():
    links = {}
    for inst in FilteredElementCollector(doc).OfClass(RevitLinkInstance):
        ldoc = inst.GetLinkDocument()
        if ldoc is None:
            continue
        links[inst.Id] = {
            'doc'      : ldoc,
            'transform': inst.GetTotalTransform(),
            'title'    : ldoc.Title,
        }
    return links

# ── Cross-boundary geometric search ───────────────────────────────────────────

def find_cross_boundary(world_pt, current_doc_path, link_data):
    results = []
    d = MATCH_TOLERANCE

    if current_doc_path != doc.PathName:
        outline = Outline(
            XYZ(world_pt.X - d, world_pt.Y - d, world_pt.Z - d),
            XYZ(world_pt.X + d, world_pt.Y + d, world_pt.Z + d),
        )
        for cand in (FilteredElementCollector(doc)
                     .WherePasses(BoundingBoxIntersectsFilter(outline))
                     .ToElements()):
            if not is_mep_element(cand):
                continue
            for cc in get_connectors(cand):
                if world_pt.DistanceTo(cc.Origin) < MATCH_TOLERANCE:
                    results.append({
                        'elem': cand, 'elem_doc': doc,
                        'link_id': None, 'world_transform': Transform.Identity,
                    })

    for link_id, ldata in link_data.items():
        ldoc  = ldata['doc']
        xform = ldata['transform']
        if ldoc.PathName == current_doc_path:
            continue
        local = xform.Inverse.OfPoint(world_pt)
        outline = Outline(
            XYZ(local.X - d, local.Y - d, local.Z - d),
            XYZ(local.X + d, local.Y + d, local.Z + d),
        )
        for cand in (FilteredElementCollector(ldoc)
                     .WherePasses(BoundingBoxIntersectsFilter(outline))
                     .ToElements()):
            if not is_mep_element(cand):
                continue
            for cc in get_connectors(cand):
                if world_pt.DistanceTo(xform.OfPoint(cc.Origin)) < MATCH_TOLERANCE:
                    results.append({
                        'elem': cand, 'elem_doc': ldoc,
                        'link_id': link_id, 'world_transform': xform,
                    })

    return results

# ── BFS traversal ──────────────────────────────────────────────────────────────

def trace_branch(start_elem, start_doc, start_world_transform, link_data):
    visited         = set()
    host_elements   = []
    linked_elements = {}
    terminals       = []

    queue = [(start_elem, start_doc, start_world_transform)]
    visited.add(elem_key(start_elem, start_doc))

    while queue:
        cur_elem, cur_doc, cur_xform = queue.pop(0)
        in_host = (cur_doc.PathName == doc.PathName)

        if in_host:
            host_elements.append(cur_elem)

        for conn in get_connectors(cur_elem):
            if conn.IsConnected:
                try:
                    refs = list(conn.AllRefs)
                except Exception:
                    refs = []
                for ref in refs:
                    owner = ref.Owner
                    if owner is None or not is_mep_element(owner):
                        continue
                    key = elem_key(owner, cur_doc)
                    if key in visited:
                        continue
                    visited.add(key)
                    queue.append((owner, cur_doc, cur_xform))
                    if not in_host:
                        for lid, ldata in link_data.items():
                            if ldata['doc'].PathName == cur_doc.PathName:
                                linked_elements.setdefault(lid, []).append(owner)
                                break
            else:
                world_pt = cur_xform.OfPoint(conn.Origin)
                cross = find_cross_boundary(world_pt, cur_doc.PathName, link_data)
                if not cross:
                    terminals.append((cur_elem, world_pt))
                else:
                    for match in cross:
                        key = elem_key(match['elem'], match['elem_doc'])
                        if key in visited:
                            continue
                        visited.add(key)
                        queue.append((
                            match['elem'],
                            match['elem_doc'],
                            match['world_transform'],
                        ))
                        if match['link_id'] is not None:
                            linked_elements.setdefault(
                                match['link_id'], []
                            ).append(match['elem'])

    return host_elements, linked_elements, terminals

# ── World bounding-box helpers ─────────────────────────────────────────────────

def compute_world_bbox(host_elems, linked_elems, link_data):
    """Collective world-space bbox used to set the view section box."""
    extents = [1e18, 1e18, 1e18, -1e18, -1e18, -1e18, 0]

    def expand(pt):
        if pt.X < extents[0]: extents[0] = pt.X
        if pt.Y < extents[1]: extents[1] = pt.Y
        if pt.Z < extents[2]: extents[2] = pt.Z
        if pt.X > extents[3]: extents[3] = pt.X
        if pt.Y > extents[4]: extents[4] = pt.Y
        if pt.Z > extents[5]: extents[5] = pt.Z
        extents[6] = 1

    def process(elems, to_world):
        for elem in elems:
            try:
                bb = elem.get_BoundingBox(None)
                if bb is None:
                    continue
                lmin, lmax = bb.Min, bb.Max
                for cx in (lmin.X, lmax.X):
                    for cy in (lmin.Y, lmax.Y):
                        for cz in (lmin.Z, lmax.Z):
                            expand(to_world.OfPoint(XYZ(cx, cy, cz)))
            except Exception:
                pass

    process(host_elems, Transform.Identity)
    for link_id, elems in linked_elems.items():
        ldata = link_data.get(link_id)
        if ldata:
            process(elems, ldata['transform'])

    if not extents[6]:
        return None
    p        = SECTION_BOX_PADDING
    bbox     = BoundingBoxXYZ()
    bbox.Min = XYZ(extents[0] - p, extents[1] - p, extents[2] - p)
    bbox.Max = XYZ(extents[3] + p, extents[4] + p, extents[5] + p)
    return bbox


def _world_corners(elem, to_world):
    """Return (world_min, world_max) XYZ pair, or None if no bounding box."""
    bb = elem.get_BoundingBox(None)
    if bb is None:
        return None
    lmin, lmax = bb.Min, bb.Max
    corners = [
        to_world.OfPoint(XYZ(cx, cy, cz))
        for cx in (lmin.X, lmax.X)
        for cy in (lmin.Y, lmax.Y)
        for cz in (lmin.Z, lmax.Z)
    ]
    mn = XYZ(min(c.X for c in corners), min(c.Y for c in corners), min(c.Z for c in corners))
    mx = XYZ(max(c.X for c in corners), max(c.Y for c in corners), max(c.Z for c in corners))
    return mn, mx

# ── Section box ────────────────────────────────────────────────────────────────

def apply_section_box(bbox, view):
    with Transaction(doc, "MEP Branch Tracer - Section Box") as t:
        t.Start()
        view.SetSectionBox(bbox)
        view.IsSectionBoxActive = True
        t.Commit()

# ── Solid fill pattern ─────────────────────────────────────────────────────────

def get_solid_fill_pattern_id():
    for fpe in (FilteredElementCollector(doc)
                .OfClass(FillPatternElement)
                .ToElements()):
        try:
            fp = fpe.GetFillPattern()
            if fp is not None and fp.IsSolidFill:
                return fpe.Id
        except Exception:
            pass
    return ElementId.InvalidElementId

# ── Box solid builder ──────────────────────────────────────────────────────────

def _make_box_solid(world_min, world_max):
    p  = HIGHLIGHT_PADDING
    mn = XYZ(world_min.X - p, world_min.Y - p, world_min.Z - p)
    mx = XYZ(world_max.X + p, world_max.Y + p, world_max.Z + p)

    MIN_DIM = 1e-4
    if mx.X - mn.X < MIN_DIM:
        h = MIN_DIM / 2.0; mn = XYZ(mn.X - h, mn.Y, mn.Z); mx = XYZ(mx.X + h, mx.Y, mx.Z)
    if mx.Y - mn.Y < MIN_DIM:
        h = MIN_DIM / 2.0; mn = XYZ(mn.X, mn.Y - h, mn.Z); mx = XYZ(mx.X, mx.Y + h, mx.Z)
    if mx.Z - mn.Z < MIN_DIM:
        h = MIN_DIM / 2.0; mn = XYZ(mn.X, mn.Y, mn.Z - h); mx = XYZ(mx.X, mx.Y, mx.Z + h)

    p1 = XYZ(mn.X, mn.Y, mn.Z)
    p2 = XYZ(mx.X, mn.Y, mn.Z)
    p3 = XYZ(mx.X, mx.Y, mn.Z)
    p4 = XYZ(mn.X, mx.Y, mn.Z)
    loop = CurveLoop()
    loop.Append(Line.CreateBound(p1, p2))
    loop.Append(Line.CreateBound(p2, p3))
    loop.Append(Line.CreateBound(p3, p4))
    loop.Append(Line.CreateBound(p4, p1))
    return GeometryCreationUtilities.CreateExtrusionGeometry(
        List[CurveLoop]([loop]), XYZ(0, 0, 1), mx.Z - mn.Z
    )

# ── DirectShape creation / deletion ───────────────────────────────────────────

def create_per_element_directshapes(host_elems, linked_elems, link_data, view):
    solid_fill_id = get_solid_fill_pattern_id()
    ogs = OverrideGraphicSettings()
    ogs.SetSurfaceTransparency(HIGHLIGHT_TRANSP)
    ogs.SetProjectionLineColor(HIGHLIGHT_COLOR)
    ogs.SetCutLineColor(HIGHLIGHT_COLOR)
    if solid_fill_id != ElementId.InvalidElementId:
        ogs.SetSurfaceForegroundPatternId(solid_fill_id)
        ogs.SetSurfaceForegroundPatternColor(HIGHLIGHT_COLOR)
        ogs.SetSurfaceBackgroundPatternId(solid_fill_id)
        ogs.SetSurfaceBackgroundPatternColor(HIGHLIGHT_COLOR)

    work_items = [(e, Transform.Identity) for e in host_elems]
    for link_id, elems in linked_elems.items():
        ldata = link_data.get(link_id)
        xform = ldata['transform'] if ldata else Transform.Identity
        work_items.extend([(e, xform) for e in elems])

    cat_id  = ElementId(BuiltInCategory.OST_GenericModel)
    created = []

    with Transaction(doc, "MEP Branch Tracer - Create Highlights") as t:
        t.Start()
        for elem, to_world in work_items:
            try:
                corners = _world_corners(elem, to_world)
                if corners is None:
                    continue
                solid = _make_box_solid(corners[0], corners[1])
                ds    = DirectShape.CreateElement(doc, cat_id)
                ds.SetShape([solid])
                ds.Name = "MEP_BranchHighlight"
                view.SetElementOverrides(ds.Id, ogs)
                created.append(ds.Id)
            except Exception as ex:
                log("  *Skipped element {} — {}*".format(elem.Id, ex))
        t.Commit()

    return created


def delete_all_directshapes(ds_ids):
    if not ds_ids:
        return
    with Transaction(doc, "MEP Branch Tracer - Remove Highlights") as t:
        t.Start()
        try:
            doc.Delete(List[ElementId](ds_ids))
            t.Commit()
        except Exception:
            t.RollBack()

# ── Catppuccin Mocha WPF overlay ───────────────────────────────────────────────
#
#   Palette  bg=#1E1E2E  card=#2A2A3C  surface=#313244  muted=#45475A
#            text=#CDD6F4  subtext=#A6ADC8  accent=#F0A500
#

_DIALOG_XAML = u"""
<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="MEP Branch Tracer"
    Width="400"
    SizeToContent="Height"
    WindowStyle="None"
    AllowsTransparency="True"
    Background="Transparent"
    ResizeMode="NoResize"
    Topmost="True"
    WindowStartupLocation="Manual">

    <Border Background="#1E1E2E" CornerRadius="14"
            BorderBrush="#45475A" BorderThickness="1">
        <StackPanel Margin="22,18,22,22">

            <!-- ── Title / drag strip ── -->
            <DockPanel x:Name="TitleBar" Margin="0,0,0,16" Cursor="SizeAll">
                <Ellipse DockPanel.Dock="Left"
                         Width="9" Height="9" Fill="#F0A500"
                         Margin="0,0,10,0" VerticalAlignment="Center"/>
                <TextBlock Text="MEP Branch Tracer  —  Highlight Active"
                           Foreground="#CDD6F4" FontFamily="Segoe UI"
                           FontSize="13" FontWeight="SemiBold"
                           VerticalAlignment="Center"/>
            </DockPanel>

            <!-- ── Stats card ── -->
            <Border Background="#2A2A3C" CornerRadius="10"
                    Padding="14,12,14,12" Margin="0,0,0,14">
                <StackPanel x:Name="StatsPanel"/>
            </Border>

            <!-- ── Hint ── -->
            <TextBlock Text="Press ESC or click below to remove all highlights."
                       Foreground="#45475A" FontFamily="Segoe UI" FontSize="10"
                       HorizontalAlignment="Center" Margin="0,0,0,12"/>

            <!-- ── Action button ── -->
            <Button x:Name="CloseBtn" Height="38" Cursor="Hand"
                    BorderThickness="0" Background="#F0A500">
                <Button.Template>
                    <ControlTemplate TargetType="Button">
                        <Border x:Name="BtnBorder"
                                Background="{TemplateBinding Background}"
                                CornerRadius="9">
                            <TextBlock Text="Remove Highlights &amp; Exit"
                                       Foreground="#1E1E2E"
                                       FontFamily="Segoe UI" FontSize="11"
                                       FontWeight="SemiBold"
                                       HorizontalAlignment="Center"
                                       VerticalAlignment="Center"/>
                        </Border>
                        <ControlTemplate.Triggers>
                            <Trigger Property="IsMouseOver" Value="True">
                                <Setter TargetName="BtnBorder"
                                        Property="Background" Value="#E09600"/>
                            </Trigger>
                            <Trigger Property="IsPressed" Value="True">
                                <Setter TargetName="BtnBorder"
                                        Property="Background" Value="#C87E00"/>
                            </Trigger>
                        </ControlTemplate.Triggers>
                    </ControlTemplate>
                </Button.Template>
            </Button>

        </StackPanel>
    </Border>
</Window>
"""


def _stat_row(label, value):
    """Build one two-column stats row as a WPF Grid."""
    grid = SW.Controls.Grid()
    grid.Margin = SW.Thickness(0, 4, 0, 4)

    col0 = SW.Controls.ColumnDefinition()
    col1 = SW.Controls.ColumnDefinition()
    col1.Width = SW.GridLength.Auto
    grid.ColumnDefinitions.Add(col0)
    grid.ColumnDefinitions.Add(col1)

    def tb(text, col, color_hex, bold=False):
        t = SW.Controls.TextBlock()
        t.Text       = text
        t.FontFamily = SW.Media.FontFamily("Segoe UI")
        t.FontSize   = 11
        t.Foreground = SW.Media.SolidColorBrush(
            SW.Media.ColorConverter.ConvertFromString(color_hex)
        )
        if bold:
            t.FontWeight = SW.FontWeights.SemiBold
        if col == 1:
            t.HorizontalAlignment = SW.HorizontalAlignment.Right
        SW.Controls.Grid.SetColumn(t, col)
        return t

    grid.Children.Add(tb(label,      0, "#A6ADC8"))
    grid.Children.Add(tb(str(value), 1, "#CDD6F4", bold=True))
    return grid


def show_highlight_dialog(stats):
    """
    Display the Catppuccin overlay and block until dismissed.
    stats: list of (label, value) tuples.
    """
    win = XamlReader.Parse(_DIALOG_XAML)

    # Position: top-right of primary work area
    work  = SW.SystemParameters.WorkArea
    win.Left = work.Right - 424
    win.Top  = work.Top + 24

    # Populate stats rows
    stats_panel = win.FindName("StatsPanel")
    if stats_panel:
        for label, value in stats:
            stats_panel.Children.Add(_stat_row(label, str(value)))

    # Wire up interactions
    close_btn = win.FindName("CloseBtn")
    if close_btn:
        close_btn.Click += lambda s, e: win.Close()

    title_bar = win.FindName("TitleBar")
    if title_bar:
        title_bar.MouseLeftButtonDown += lambda s, e: win.DragMove()

    win.KeyDown += lambda s, e: (win.Close() if e.Key == SW.Input.Key.Escape else None)

    # PushFrame blocks the script (preventing early cleanup) while still
    # processing all Win32 messages freely — Revit's viewport stays interactive.
    # ShowDialog() calls ComponentDispatcher.PushModal() which restricts all
    # input to the dialog window; PushFrame() does not.
    frame = DispatcherFrame()
    win.Closed += lambda s, e: setattr(frame, 'Continue', False)
    win.Show()
    Dispatcher.PushFrame(frame)

# ── Report ─────────────────────────────────────────────────────────────────────

def build_report(start_elem, start_doc, host_elems, linked_elems,
                 terminals, link_data, ds_count):
    log_header("MEP Branch Trace Report")
    log("**Starting element:** {} — ID `{}` — {} — *linked: {}*".format(
        cat_label(start_elem), start_elem.Id,
        type_name(start_elem, start_doc), start_doc.Title))
    log("")

    total_linked = sum(len(v) for v in linked_elems.values())
    log_header("Summary")
    log(
        "| Metric | Count |\n"
        "|--------|-------|\n"
        "| Host model elements | {} |\n"
        "| Linked file elements | {} |\n"
        "| Linked files crossed | {} |\n"
        "| Terminal / dead-end connectors | {} |\n"
        "| Cyan highlight boxes created | {} |".format(
            len(host_elems), total_linked,
            len(linked_elems), len(terminals), ds_count))
    log("")

    if host_elems:
        log_header("Host Model Elements ({})".format(len(host_elems)))
        cat_groups = {}
        for e in host_elems:
            cat_groups.setdefault(cat_label(e), []).append(e)
        rows = []
        for cl in sorted(cat_groups):
            for e in cat_groups[cl]:
                rows.append([cl, str(e.Id), type_name(e, doc)])
        log_table(["Category", "Element ID", "Type"], rows)
        log("")

    if linked_elems:
        log_header("Linked File Elements ({})".format(total_linked))
        for lid, elems in linked_elems.items():
            ldata = link_data.get(lid, {})
            ldoc  = ldata.get('doc', doc)
            log("**{}** — {} element(s)".format(ldata.get('title', str(lid)), len(elems)))
            cat_groups = {}
            for e in elems:
                cat_groups.setdefault(cat_label(e), []).append(e)
            rows = []
            for cl in sorted(cat_groups):
                for e in cat_groups[cl]:
                    rows.append([cl, str(e.Id), type_name(e, ldoc)])
            log_table(["Category", "Element ID", "Type"], rows)
            log("")

    if terminals:
        log_header("Terminal Connectors ({})".format(len(terminals)))
        rows = []
        for elem, world_pt in terminals:
            rows.append([
                cat_label(elem), str(elem.Id),
                "{:.3f}, {:.3f}, {:.3f}".format(world_pt.X, world_pt.Y, world_pt.Z),
            ])
        log_table(["Category", "Element ID", "Open Connector XYZ (ft, world)"], rows)
        log("")

    log("*Section box active.  {} cyan highlight boxes visible — dismiss overlay to remove.*".format(ds_count))

# ── Interactive session ────────────────────────────────────────────────────────

def run_interactive_session(host_elems, linked_elems, terminals, ds_ids):
    total_linked = sum(len(v) for v in linked_elems.values())
    total        = len(host_elems) + total_linked

    stats = [
        (u"Total elements traced",  total),
        (u"  \u2023  Host model",   len(host_elems)),
        (u"  \u2023  Linked files", u"{} file(s)  \u00b7  {} elements".format(
             len(linked_elems), total_linked)),
        (u"Open terminals",         len(terminals)),
        (u"Cyan highlight boxes",   len(ds_ids)),
    ]

    show_highlight_dialog(stats)

    delete_all_directshapes(ds_ids)
    log("*All {} highlight boxes removed.  Script exited cleanly.*".format(len(ds_ids)))

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    active_view = uidoc.ActiveView
    if not isinstance(active_view, View3D):
        TaskDialog.Show(
            "MEP Branch Tracer",
            "Please activate a 3D view before running this script.\n\n"
            "The branch isolation uses the view's section box, which is "
            "only available in 3D views."
        )
        return

    try:
        ref = uidoc.Selection.PickObject(
            ObjectType.LinkedElement,
            "Pick a MEP element from a linked file to trace its branch"
        )
    except Exception:
        return

    link_instance = doc.GetElement(ref.ElementId)
    if not isinstance(link_instance, RevitLinkInstance):
        TaskDialog.Show("MEP Branch Tracer", "Could not resolve the linked file instance.")
        return

    link_doc    = link_instance.GetLinkDocument()
    world_xform = link_instance.GetTotalTransform()

    if link_doc is None:
        TaskDialog.Show("MEP Branch Tracer",
                        "The selected linked file is not currently loaded.")
        return

    start_elem = link_doc.GetElement(ref.LinkedElementId)
    if start_elem is None or not is_mep_element(start_elem):
        TaskDialog.Show(
            "MEP Branch Tracer",
            "The selected element is not a traceable MEP element.\n\n"
            "Please select a pipe, duct, cable tray, conduit, "
            "fitting, or accessory."
        )
        return

    log("**Tracing branch from:** {} — ID `{}` in *{}* ...".format(
        cat_label(start_elem), start_elem.Id, link_doc.Title))

    link_data = get_link_data()
    if link_instance.Id not in link_data:
        link_data[link_instance.Id] = {
            'doc'      : link_doc,
            'transform': world_xform,
            'title'    : link_doc.Title,
        }

    host_elems, linked_elems, terminals = trace_branch(
        start_elem, link_doc, world_xform, link_data
    )

    # Ensure the seed element is included in the linked set
    seed_key = elem_key(start_elem, link_doc)
    if not any(elem_key(e, link_doc) == seed_key
               for e in linked_elems.get(link_instance.Id, [])):
        linked_elems.setdefault(link_instance.Id, []).insert(0, start_elem)

    total = len(host_elems) + sum(len(v) for v in linked_elems.values())
    if total == 0:
        TaskDialog.Show("MEP Branch Tracer",
                        "No connected elements were found from the selected element.")
        return

    bbox = compute_world_bbox(host_elems, linked_elems, link_data)
    if bbox is None:
        log("**Warning:** Could not compute a bounding box for the traced elements.")
        return
    apply_section_box(bbox, active_view)

    ds_ids = create_per_element_directshapes(
        host_elems, linked_elems, link_data, active_view
    )
    log("**Created {} cyan highlight boxes.**".format(len(ds_ids)))

    if host_elems:
        uidoc.Selection.SetElementIds(List[ElementId]([e.Id for e in host_elems]))

    build_report(start_elem, link_doc, host_elems, linked_elems,
                 terminals, link_data, len(ds_ids))

    run_interactive_session(host_elems, linked_elems, terminals, ds_ids)

    if not HAS_OUTPUT:
        TaskDialog.Show("MEP Branch Tracer", "\n".join(_log_lines[-80:]))


if __name__ == '__main__':
    main()
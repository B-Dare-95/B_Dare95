# -*- coding: utf-8 -*-
"""
MEP Branch Tracer  (v5 — Per-Element DirectShape Highlights)
=============================================================
Traces the complete connected branch of a selected MEP element residing
in a Revit linked file, then:
  1. Applies a section box to the active 3D view isolating the branch.
  2. Creates one Generic Model DirectShape bounding-box solid per traced
     element and applies a cyan / 50 % transparent graphic override on
     each shape in the active view.
  3. Shows a small overlay dialog with trace statistics.
  4. When the user presses ESC or closes the overlay, every DirectShape is
     deleted and the script exits — the section box and view settings are
     left untouched.

Compatible with: pyRevit 4.x, IronPython 2.7, Revit 2020+
"""

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('System')
clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Drawing')

from Autodesk.Revit.DB import (
    FilteredElementCollector, RevitLinkInstance,
    BoundingBoxIntersectsFilter, BoundingBoxXYZ, Outline,
    Transform, XYZ, ElementId, BuiltInCategory, BuiltInParameter,
    Transaction, View3D,
    DirectShape,
    CurveLoop, Line,
    GeometryCreationUtilities,
    OverrideGraphicSettings, Color,
    FillPatternElement, FillPatternTarget,
)
from Autodesk.Revit.UI import TaskDialog
from Autodesk.Revit.UI.Selection import ObjectType
from System.Collections.Generic import List
import System.Windows.Forms as WinForms
import System.Drawing as Drawing

# ── pyRevit output ─────────────────────────────────────────────────────────────
try:
    from pyrevit import script
    output = script.get_output()
    def log(msg):        output.print_md(msg)
    def log_header(msg): output.print_md("### " + msg)
    def log_table(headers, rows): output.print_table(rows, columns=headers)
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
MATCH_TOLERANCE     = 0.05   # feet (~15 mm) — cross-link endpoint matching
SECTION_BOX_PADDING = 1.0    # feet (~300 mm) — section box expansion margin
HIGHLIGHT_PADDING   = 0.05   # feet (~15 mm)  — per-element box expansion margin
HIGHLIGHT_COLOR     = Color(0, 255, 255)   # cyan
HIGHLIGHT_TRANSP    = 50     # percent (0 = opaque, 100 = invisible)

# ── MEP category registry ──────────────────────────────────────────────────────
MEP_CATEGORIES = {
    int(BuiltInCategory.OST_PipeCurves)         : "Pipe",
    int(BuiltInCategory.OST_PipeFitting)        : "Pipe Fitting",
    int(BuiltInCategory.OST_PipeAccessory)      : "Pipe Accessory",
    int(BuiltInCategory.OST_FlexPipeCurves)     : "Flex Pipe",
    int(BuiltInCategory.OST_DuctCurves)         : "Duct",
    int(BuiltInCategory.OST_DuctFitting)        : "Duct Fitting",
    int(BuiltInCategory.OST_DuctAccessory)      : "Duct Accessory",
    int(BuiltInCategory.OST_FlexDuctCurves)     : "Flex Duct",
    int(BuiltInCategory.OST_CableTray)          : "Cable Tray",
    int(BuiltInCategory.OST_CableTrayFitting)   : "Cable Tray Fitting",
    int(BuiltInCategory.OST_Conduit)            : "Conduit",
    int(BuiltInCategory.OST_ConduitFitting)     : "Conduit Fitting",
    int(BuiltInCategory.OST_MechanicalEquipment): "Mech. Equipment",
    int(BuiltInCategory.OST_PlumbingFixtures)   : "Plumbing Fixture",
}

def is_mep_element(elem):
    if elem is None or elem.Category is None:
        return False
    return elem.Category.Id.IntegerValue in MEP_CATEGORIES

def cat_label(elem):
    if elem is None or elem.Category is None:
        return "Unknown"
    return MEP_CATEGORIES.get(elem.Category.Id.IntegerValue, elem.Category.Name)

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
    return (elem_doc.PathName, elem.Id.IntegerValue)

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
    """Returns {ElementId: {doc, transform, title}} for all loaded linked files."""
    links = {}
    for inst in FilteredElementCollector(doc).OfClass(RevitLinkInstance):
        ldoc = inst.GetLinkDocument()
        if ldoc is None:
            continue
        links[inst.Id] = {
            'doc'      : ldoc,
            'transform': inst.GetTotalTransform(),
            'title'    : ldoc.Title
        }
    return links

# ── Cross-boundary geometric search ───────────────────────────────────────────

def find_cross_boundary(world_pt, current_doc_path, link_data):
    results = []
    d = MATCH_TOLERANCE

    if current_doc_path != doc.PathName:
        outline = Outline(
            XYZ(world_pt.X - d, world_pt.Y - d, world_pt.Z - d),
            XYZ(world_pt.X + d, world_pt.Y + d, world_pt.Z + d)
        )
        for cand in (FilteredElementCollector(doc)
                     .WherePasses(BoundingBoxIntersectsFilter(outline))
                     .ToElements()):
            if not is_mep_element(cand):
                continue
            for cc in get_connectors(cand):
                if world_pt.DistanceTo(cc.Origin) < MATCH_TOLERANCE:
                    results.append({
                        'elem'           : cand,
                        'elem_doc'       : doc,
                        'link_id'        : None,
                        'world_transform': Transform.Identity
                    })

    for link_id, ldata in link_data.items():
        ldoc  = ldata['doc']
        xform = ldata['transform']
        if ldoc.PathName == current_doc_path:
            continue
        local = xform.Inverse.OfPoint(world_pt)
        outline = Outline(
            XYZ(local.X - d, local.Y - d, local.Z - d),
            XYZ(local.X + d, local.Y + d, local.Z + d)
        )
        for cand in (FilteredElementCollector(ldoc)
                     .WherePasses(BoundingBoxIntersectsFilter(outline))
                     .ToElements()):
            if not is_mep_element(cand):
                continue
            for cc in get_connectors(cand):
                if world_pt.DistanceTo(xform.OfPoint(cc.Origin)) < MATCH_TOLERANCE:
                    results.append({
                        'elem'           : cand,
                        'elem_doc'       : ldoc,
                        'link_id'        : link_id,
                        'world_transform': xform
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
                            match['world_transform']
                        ))
                        if match['link_id'] is not None:
                            linked_elements.setdefault(
                                match['link_id'], []
                            ).append(match['elem'])

    return host_elements, linked_elements, terminals

# ── Bounding box for section box ───────────────────────────────────────────────

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

    def process_elements(elems, to_world):
        for elem in elems:
            try:
                bb = elem.get_BoundingBox(None)
                if bb is None:
                    continue
                lmin, lmax = bb.Min, bb.Max
                for corner in [
                    XYZ(lmin.X, lmin.Y, lmin.Z), XYZ(lmax.X, lmin.Y, lmin.Z),
                    XYZ(lmin.X, lmax.Y, lmin.Z), XYZ(lmin.X, lmin.Y, lmax.Z),
                    XYZ(lmax.X, lmax.Y, lmin.Z), XYZ(lmax.X, lmin.Y, lmax.Z),
                    XYZ(lmin.X, lmax.Y, lmax.Z), XYZ(lmax.X, lmax.Y, lmax.Z),
                ]:
                    expand(to_world.OfPoint(corner))
            except Exception:
                pass

    process_elements(host_elems, Transform.Identity)
    for link_id, elems in linked_elems.items():
        ldata = link_data.get(link_id)
        if ldata is None:
            continue
        process_elements(elems, ldata['transform'])

    if not extents[6]:
        return None

    p = SECTION_BOX_PADDING
    bbox     = BoundingBoxXYZ()
    bbox.Min = XYZ(extents[0] - p, extents[1] - p, extents[2] - p)
    bbox.Max = XYZ(extents[3] + p, extents[4] + p, extents[5] + p)
    return bbox

# ── Section box application ────────────────────────────────────────────────────

def apply_section_box(bbox, view):
    with Transaction(doc, "MEP Branch Tracer - Section Box") as t:
        t.Start()
        view.SetSectionBox(bbox)
        view.IsSectionBoxActive = True
        t.Commit()

# ── Solid fill pattern lookup ──────────────────────────────────────────────────

def get_solid_fill_pattern_id():
    """
    Returns the ElementId of the first solid-fill pattern found in the
    document (drafting or model).  Returns ElementId.InvalidElementId if none.
    """
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

# ── Per-element world corners ──────────────────────────────────────────────────

def _world_corners(elem, to_world):
    """
    Transforms all 8 bbox corners to world space and returns (min_XYZ, max_XYZ).
    Returns None if the element has no bounding box.
    """
    bb = elem.get_BoundingBox(None)
    if bb is None:
        return None
    lmin, lmax = bb.Min, bb.Max
    corners = [
        to_world.OfPoint(XYZ(lmin.X, lmin.Y, lmin.Z)),
        to_world.OfPoint(XYZ(lmax.X, lmin.Y, lmin.Z)),
        to_world.OfPoint(XYZ(lmin.X, lmax.Y, lmin.Z)),
        to_world.OfPoint(XYZ(lmin.X, lmin.Y, lmax.Z)),
        to_world.OfPoint(XYZ(lmax.X, lmax.Y, lmin.Z)),
        to_world.OfPoint(XYZ(lmax.X, lmin.Y, lmax.Z)),
        to_world.OfPoint(XYZ(lmin.X, lmax.Y, lmax.Z)),
        to_world.OfPoint(XYZ(lmax.X, lmax.Y, lmax.Z)),
    ]
    mn = XYZ(min(c.X for c in corners),
             min(c.Y for c in corners),
             min(c.Z for c in corners))
    mx = XYZ(max(c.X for c in corners),
             max(c.Y for c in corners),
             max(c.Z for c in corners))
    return mn, mx

# ── Box solid builder ──────────────────────────────────────────────────────────

def _make_box_solid(world_min, world_max):
    """
    Builds an axis-aligned extruded box Solid from world-space min/max points.
    Applies HIGHLIGHT_PADDING and guards against degenerate (zero-size) dims.
    Returns the Solid or raises on geometry failure.
    """
    p  = HIGHLIGHT_PADDING
    mn = XYZ(world_min.X - p, world_min.Y - p, world_min.Z - p)
    mx = XYZ(world_max.X + p, world_max.Y + p, world_max.Z + p)

    MIN_DIM = 1e-4  # feet — floor for any single dimension
    dx = mx.X - mn.X
    dy = mx.Y - mn.Y
    dz = mx.Z - mn.Z

    if dx < MIN_DIM:
        half = MIN_DIM
        mn = XYZ(mn.X - half, mn.Y, mn.Z)
        mx = XYZ(mx.X + half, mx.Y, mx.Z)
    if dy < MIN_DIM:
        half = MIN_DIM
        mn = XYZ(mn.X, mn.Y - half, mn.Z)
        mx = XYZ(mx.X, mx.Y + half, mx.Z)
    if dz < MIN_DIM:
        half = MIN_DIM
        mn = XYZ(mn.X, mn.Y, mn.Z - half)
        mx = XYZ(mx.X, mx.Y, mx.Z + half)

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

# ── Per-element DirectShape creation ──────────────────────────────────────────

def create_per_element_directshapes(host_elems, linked_elems, link_data, view):
    """
    Creates one Generic Model DirectShape bounding-box solid per traced element
    and immediately applies a cyan / 50 % transparent graphic override to each
    in *view*.  Everything happens inside a single transaction.

    Returns a list of ElementIds for later bulk deletion.
    """
    solid_fill_id = get_solid_fill_pattern_id()

    # Build the override settings template (same for every box)
    ogs = OverrideGraphicSettings()
    ogs.SetSurfaceTransparency(HIGHLIGHT_TRANSP)
    ogs.SetProjectionLineColor(HIGHLIGHT_COLOR)
    ogs.SetCutLineColor(HIGHLIGHT_COLOR)
    if solid_fill_id != ElementId.InvalidElementId:
        ogs.SetSurfaceForegroundPatternId(solid_fill_id)
        ogs.SetSurfaceForegroundPatternColor(HIGHLIGHT_COLOR)
        ogs.SetSurfaceBackgroundPatternId(solid_fill_id)
        ogs.SetSurfaceBackgroundPatternColor(HIGHLIGHT_COLOR)

    # Flatten all elements with their respective world transforms
    work_items = []
    for elem in host_elems:
        work_items.append((elem, Transform.Identity))
    for link_id, elems in linked_elems.items():
        ldata = link_data.get(link_id)
        xform = ldata['transform'] if ldata else Transform.Identity
        for elem in elems:
            work_items.append((elem, xform))

    cat_id  = ElementId(BuiltInCategory.OST_GenericModel)
    created = []   # list[ElementId] — all successfully created DirectShape ids

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
                # Apply cyan override in this view
                view.SetElementOverrides(ds.Id, ogs)
                created.append(ds.Id)
            except Exception as ex:
                log("  *Skipped element {} — {}*".format(
                    elem.Id.IntegerValue, ex))
        t.Commit()

    return created

# ── Bulk DirectShape deletion ──────────────────────────────────────────────────

def delete_all_directshapes(ds_ids):
    """Deletes all highlight DirectShapes in a single transaction."""
    if not ds_ids:
        return
    with Transaction(doc, "MEP Branch Tracer - Remove Highlights") as t:
        t.Start()
        try:
            doc.Delete(List[ElementId](ds_ids))
            t.Commit()
        except Exception:
            t.RollBack()

# ── Overlay dialog ─────────────────────────────────────────────────────────────

class BranchHighlightDialog(WinForms.Form):
    """
    Always-on-top status overlay.  Dismissing via ESC, the X button, or the
    'Remove & Exit' button triggers cleanup and exits the script.
    """

    def __init__(self, summary_lines):
        WinForms.Form.__init__(self)

        self.Text            = "MEP Branch Tracer  —  Highlight Active"
        self.FormBorderStyle = WinForms.FormBorderStyle.FixedSingle
        self.MaximizeBox     = False
        self.MinimizeBox     = False
        self.TopMost         = True
        self.StartPosition   = WinForms.FormStartPosition.Manual
        self.KeyPreview      = True

        padding = 12
        lbl_w   = 360
        row_h   = 20
        form_h  = (padding
                   + len(summary_lines) * row_h
                   + padding + row_h + 6 + 36 + padding)

        self.ClientSize = Drawing.Size(lbl_w + padding * 2, form_h)

        screen = WinForms.Screen.PrimaryScreen.WorkingArea
        self.Location = Drawing.Point(
            screen.Right - self.Width - 24,
            screen.Top   + 24
        )

        y = padding
        for line in summary_lines:
            lbl          = WinForms.Label()
            lbl.Text     = line
            lbl.Location = Drawing.Point(padding, y)
            lbl.Size     = Drawing.Size(lbl_w, row_h)
            lbl.Font     = Drawing.Font("Segoe UI", 9)
            self.Controls.Add(lbl)
            y += row_h

        hint           = WinForms.Label()
        hint.Text      = "Press  ESC  or close this window to remove all highlights."
        hint.Location  = Drawing.Point(padding, y + 4)
        hint.Size      = Drawing.Size(lbl_w, row_h)
        hint.Font      = Drawing.Font("Segoe UI", 8, Drawing.FontStyle.Italic)
        hint.ForeColor = Drawing.Color.Gray
        self.Controls.Add(hint)
        y += row_h + 6

        btn          = WinForms.Button()
        btn.Text     = "Remove Highlights && Exit"
        btn.Location = Drawing.Point(padding, y + 6)
        btn.Size     = Drawing.Size(lbl_w, 30)
        btn.Font     = Drawing.Font("Segoe UI", 9)
        btn.Click   += self._on_close_clicked
        self.Controls.Add(btn)

        self.KeyDown += self._on_key_down

    def _on_key_down(self, sender, e):
        if e.KeyCode == WinForms.Keys.Escape:
            self.Close()

    def _on_close_clicked(self, sender, e):
        self.Close()


def show_highlight_dialog(summary_lines):
    WinForms.Application.Run(BranchHighlightDialog(summary_lines))

# ── Report ─────────────────────────────────────────────────────────────────────

def build_report(start_elem, start_doc, host_elems, linked_elems,
                 terminals, link_data, ds_count):
    log_header("MEP Branch Trace Report")
    log("**Starting element:** {} — ID `{}` — {} — *linked: {}*".format(
        cat_label(start_elem),
        start_elem.Id.IntegerValue,
        type_name(start_elem, start_doc),
        start_doc.Title
    ))
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
            len(linked_elems), len(terminals), ds_count
        )
    )
    log("")

    if host_elems:
        log_header("Host Model Elements ({})".format(len(host_elems)))
        cat_groups = {}
        for e in host_elems:
            cat_groups.setdefault(cat_label(e), []).append(e)
        rows = []
        for cl in sorted(cat_groups):
            for e in cat_groups[cl]:
                rows.append([cl, str(e.Id.IntegerValue), type_name(e, doc)])
        log_table(["Category", "Element ID", "Type"], rows)
        log("")

    if linked_elems:
        total_linked = sum(len(v) for v in linked_elems.values())
        log_header("Linked File Elements ({})".format(total_linked))
        for lid, elems in linked_elems.items():
            ldata = link_data.get(lid, {})
            ldoc  = ldata.get('doc', doc)
            log("**{}** — {} element(s)".format(
                ldata.get('title', str(lid)), len(elems)))
            cat_groups = {}
            for e in elems:
                cat_groups.setdefault(cat_label(e), []).append(e)
            rows = []
            for cl in sorted(cat_groups):
                for e in cat_groups[cl]:
                    rows.append([cl, str(e.Id.IntegerValue), type_name(e, ldoc)])
            log_table(["Category", "Element ID", "Type"], rows)
            log("")

    if terminals:
        log_header("Terminal Connectors ({})".format(len(terminals)))
        rows = []
        for elem, world_pt in terminals:
            rows.append([
                cat_label(elem),
                str(elem.Id.IntegerValue),
                "{:.3f}, {:.3f}, {:.3f}".format(world_pt.X, world_pt.Y, world_pt.Z)
            ])
        log_table(["Category", "Element ID", "Open Connector XYZ (ft, world)"], rows)
        log("")

    log("*Section box active.  {} cyan highlight boxes visible — dismiss overlay to remove.*".format(
        ds_count))

# ── Interactive session ────────────────────────────────────────────────────────

def run_interactive_session(host_elems, linked_elems, terminals, ds_ids):
    total_linked = sum(len(v) for v in linked_elems.values())
    total        = len(host_elems) + total_linked

    summary_lines = [
        u"\u2022  Total elements traced  : {}".format(total),
        u"\u2022  Host model             : {}".format(len(host_elems)),
        u"\u2022  Linked files           : {}  ({} elements)".format(
            len(linked_elems), total_linked),
        u"\u2022  Open terminals         : {}".format(len(terminals)),
        u"\u2022  Cyan highlight boxes   : {}".format(len(ds_ids)),
    ]

    show_highlight_dialog(summary_lines)

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
        cat_label(start_elem), start_elem.Id.IntegerValue, link_doc.Title
    ))

    link_data = get_link_data()
    if link_instance.Id not in link_data:
        link_data[link_instance.Id] = {
            'doc'      : link_doc,
            'transform': world_xform,
            'title'    : link_doc.Title
        }

    host_elems, linked_elems, terminals = trace_branch(
        start_elem, link_doc, world_xform, link_data
    )

    seed_key = elem_key(start_elem, link_doc)
    already  = any(
        elem_key(e, link_doc) == seed_key
        for e in linked_elems.get(link_instance.Id, [])
    )
    if not already:
        linked_elems.setdefault(link_instance.Id, []).insert(0, start_elem)

    total = len(host_elems) + sum(len(v) for v in linked_elems.values())
    if total == 0:
        TaskDialog.Show("MEP Branch Tracer",
                        "No connected elements were found from the selected element.")
        return

    # Section box
    bbox = compute_world_bbox(host_elems, linked_elems, link_data)
    if bbox is None:
        log("**Warning:** Could not compute a bounding box for the traced elements.")
        return
    apply_section_box(bbox, active_view)

    # Per-element cyan DirectShape highlights
    ds_ids = create_per_element_directshapes(
        host_elems, linked_elems, link_data, active_view
    )
    log("**Created {} cyan highlight boxes.**".format(len(ds_ids)))

    # Select host elements
    if host_elems:
        uidoc.Selection.SetElementIds(List[ElementId]([e.Id for e in host_elems]))

    build_report(start_elem, link_doc, host_elems, linked_elems,
                 terminals, link_data, len(ds_ids))

    run_interactive_session(host_elems, linked_elems, terminals, ds_ids)

    if not HAS_OUTPUT:
        TaskDialog.Show("MEP Branch Tracer", "\n".join(_log_lines[-80:]))


if __name__ == '__main__':
    main()
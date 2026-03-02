# -*- coding: utf-8 -*-
"""
MEP Branch Tracer  (v3 — Linked-file only, bounding box isolation)
==================================================================
Traces the complete connected branch of a selected MEP element residing
in a Revit linked file, then isolates all discovered elements in the
active 3D view by applying a collective section box.

Usage:
  1. Open (or activate) a 3D view.
  2. Run the script and click any pipe, duct, cable tray, conduit,
     fitting, or accessory inside a linked file.
  3. The script walks the full connected branch — crossing into the host
     model or other linked files wherever the network continues.
  4. A section box enclosing every discovered element (plus a small
     padding margin) is applied to the active 3D view, isolating the
     branch visually without touching any other view settings.

Notes:
  - The active view must be a 3D view. The script will warn and abort
    if a 2D view is active.
  - Section box padding is controlled by SECTION_BOX_PADDING (default
    1.0 ft / ~300 mm). Increase this for dense assemblies.
  - Cross-link geometric matching tolerance is MATCH_TOLERANCE
    (default 0.05 ft / ~15 mm). Increase if your project has slight
    coordinate offsets between linked files.

Compatible with: pyRevit 4.x, IronPython 2.7, Revit 2020+
"""

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('System')

from Autodesk.Revit.DB import (
    FilteredElementCollector, RevitLinkInstance,
    BoundingBoxIntersectsFilter, BoundingBoxXYZ, Outline,
    Transform, XYZ, ElementId, BuiltInCategory, BuiltInParameter,
    Transaction, View3D
)
from Autodesk.Revit.UI import TaskDialog
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter
from System.Collections.Generic import List

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
MATCH_TOLERANCE    = 0.05   # feet (~15 mm) — cross-link endpoint matching
SECTION_BOX_PADDING = 1.0   # feet (~300 mm) — bounding box expansion margin

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
    """
    Searches the host model and all other linked files for MEP connectors
    whose world-space origin is within MATCH_TOLERANCE of world_pt.
    Skips the document identified by current_doc_path to avoid self-matches.
    """
    results = []
    d = MATCH_TOLERANCE

    # Search host model
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

    # Search each linked file
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
    """
    BFS through the MEP connector graph starting from start_elem.
    Returns:
      host_elements   : [Element]           — elements in the host document
      linked_elements : {link_id: [Element]}— elements per linked file
      terminals       : [(elem, world_xyz)] — open / dead-end connectors
    """
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
                # Traverse within the same document via the connector graph
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
                # Open connector — search geometrically across boundaries
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

# ── Bounding box computation ───────────────────────────────────────────────────

def compute_world_bbox(host_elems, linked_elems, link_data):
    """
    Computes the collective world-space axis-aligned bounding box
    enclosing every discovered element.  Each element's own BoundingBox
    is retrieved in its local document space and then transformed into
    world coordinates using the appropriate link transform.

    Returns a BoundingBoxXYZ with SECTION_BOX_PADDING applied, or None
    if no bounding box data could be collected.

    Note: uses a mutable list for running extents to avoid 'nonlocal',
    which is unsupported in IronPython 2.7.
    """
    # extents[0..2] = min_x, min_y, min_z
    # extents[3..5] = max_x, max_y, max_z
    # extents[6]    = found_any flag (0 or 1)
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
                    XYZ(lmin.X, lmin.Y, lmin.Z),
                    XYZ(lmax.X, lmin.Y, lmin.Z),
                    XYZ(lmin.X, lmax.Y, lmin.Z),
                    XYZ(lmin.X, lmin.Y, lmax.Z),
                    XYZ(lmax.X, lmax.Y, lmin.Z),
                    XYZ(lmax.X, lmin.Y, lmax.Z),
                    XYZ(lmin.X, lmax.Y, lmax.Z),
                    XYZ(lmax.X, lmax.Y, lmax.Z),
                ]:
                    expand(to_world.OfPoint(corner))
            except Exception:
                pass

    # Host model elements (already in world space)
    process_elements(host_elems, Transform.Identity)

    # Linked file elements
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
    """Applies bbox as the section box on a View3D inside a transaction."""
    with Transaction(doc, "MEP Branch Tracer - Section Box") as t:
        t.Start()
        view.SetSectionBox(bbox)
        view.IsSectionBoxActive = True
        t.Commit()

# ── Report ─────────────────────────────────────────────────────────────────────

def build_report(start_elem, start_doc, host_elems, linked_elems,
                 terminals, link_data):
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
        "| Terminal / dead-end connectors | {} |".format(
            len(host_elems), total_linked,
            len(linked_elems), len(terminals)
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

    log("*Section box applied to the active 3D view, isolating the traced branch.*")

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    # Validate that the active view is a 3D view
    active_view = uidoc.ActiveView
    if not isinstance(active_view, View3D):
        TaskDialog.Show(
            "MEP Branch Tracer",
            "Please activate a 3D view before running this script.\n\n"
            "The branch isolation uses the view's section box, which is "
            "only available in 3D views."
        )
        return

    # Prompt for a linked MEP element
    try:
        ref = uidoc.Selection.PickObject(
            ObjectType.LinkedElement,
            "Pick a MEP element from a linked file to trace its branch"
        )
    except Exception:
        return  # User cancelled

    # Resolve the link instance and the element within it
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

    # Run traversal
    link_data = get_link_data()

    # Ensure the starting element's link is registered in link_data
    if link_instance.Id not in link_data:
        link_data[link_instance.Id] = {
            'doc'      : link_doc,
            'transform': world_xform,
            'title'    : link_doc.Title
        }
    # Register starting element as first linked entry
    link_data[link_instance.Id]  # just ensure key exists
    linked_seed = {link_instance.Id: [start_elem]}

    host_elems, linked_elems, terminals = trace_branch(
        start_elem, link_doc, world_xform, link_data
    )

    # Merge the starting element into linked_elems if not already present
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

    # Compute collective bounding box and apply section box
    bbox = compute_world_bbox(host_elems, linked_elems, link_data)
    if bbox is not None:
        apply_section_box(bbox, active_view)
    else:
        log("**Warning:** Could not compute a bounding box for the traced elements.")

    # Select host-model elements (secondary highlight where possible)
    if host_elems:
        id_list = List[ElementId]([e.Id for e in host_elems])
        uidoc.Selection.SetElementIds(id_list)

    build_report(start_elem, link_doc, host_elems, linked_elems, terminals, link_data)

    if not HAS_OUTPUT:
        TaskDialog.Show("MEP Branch Tracer", "\n".join(_log_lines[-80:]))


if __name__ == '__main__':
    main()
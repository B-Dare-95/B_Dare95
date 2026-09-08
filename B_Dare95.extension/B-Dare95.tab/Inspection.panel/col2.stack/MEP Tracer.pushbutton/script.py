# -*- coding: utf-8 -*-
"""
MEP Branch Tracer  (v7 — Selection-based highlighting)
=================================================================
Traces the complete connected branch of a selected MEP element residing
in a Revit linked file, then:
  1. Applies a section box to the active 3D view isolating the branch.
  2. Selects every traced element in the Revit UI — host elements and
     linked elements together — via Selection.SetReferences().
  3. Prints a short category summary (no element IDs).

Change (v7):  Generic Model DirectShape bounding boxes replaced with a real
              Revit selection. Linked elements are converted to host-context
              references with Reference.CreateLinkReference() and pushed
              through Selection.SetReferences(), so the branch stays
              highlighted natively — nothing is created, nothing to clean up,
              and no transaction is needed for the highlight itself.
              The overlay dialog and its Remove Highlights logic are gone
              along with the geometry they existed to manage.

Compatible with: pyRevit 4.x, IronPython 2.7, Revit 2023–2027+
                 (Selection.SetReferences was added in the Revit 2023 API)
"""

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('System')

from Autodesk.Revit.DB import (
    FilteredElementCollector, RevitLinkInstance,
    BoundingBoxIntersectsFilter, BoundingBoxXYZ, Outline,
    Transform, XYZ, ElementId, BuiltInCategory,
    Transaction, View3D, Reference,
)
from Autodesk.Revit.UI import TaskDialog
from Autodesk.Revit.UI.Selection import ObjectType
import Autodesk.Revit.Exceptions as RvtEx
from System.Collections.Generic import List

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

doc      = __revit__.ActiveUIDocument.Document
uidoc    = __revit__.ActiveUIDocument
app      = __revit__.Application
rvt_year = int(app.VersionNumber)

# ── Tuneable constants ─────────────────────────────────────────────────────────
MATCH_TOLERANCE     = 0.05   # feet (~15 mm)
SECTION_BOX_PADDING = 1.0    # feet (~300 mm)

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
            'instance' : inst,          # needed for CreateLinkReference()
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

# ── Section box ────────────────────────────────────────────────────────────────

def apply_section_box(bbox, view):
    t = Transaction(doc, "MEP Branch Tracer - Section Box")
    t.Start()
    try:
        view.SetSectionBox(bbox)
        view.IsSectionBoxActive = True
        t.Commit()
    except Exception:
        t.RollBack()
        raise

# ── Selection highlighting ─────────────────────────────────────────────────────

def build_selection_references(host_elems, linked_elems, link_data):
    """Host elements and linked elements as one host-context reference list.

    Host elements go in as plain Reference(elem). Linked elements are rebuilt as
    whole-element references and converted with CreateLinkReference(), which is
    what makes them valid outside their own document.

    Returns (List[Reference], skipped_count).
    """
    refs    = List[Reference]()
    skipped = 0

    for elem in host_elems:
        try:
            refs.Add(Reference(elem))
        except Exception:
            skipped += 1

    for link_id, elems in linked_elems.items():
        ldata = link_data.get(link_id)
        inst  = ldata.get('instance') if ldata else None
        if inst is None:
            skipped += len(elems)
            continue
        for elem in elems:
            try:
                refs.Add(Reference(elem).CreateLinkReference(inst))
            except Exception:
                skipped += 1

    return refs, skipped

# ── Summary ────────────────────────────────────────────────────────────────────

def log_summary(host_elems, linked_elems, terminals, selected_count, skipped):
    """Category breakdown only — no element IDs.

    Delete this function and its call in main() if you want the tool silent.
    """
    total_linked = sum(len(v) for v in linked_elems.values())

    counts = {}
    for e in host_elems:
        label = cat_label(e)
        counts[label] = counts.get(label, 0) + 1
    for elems in linked_elems.values():
        for e in elems:
            label = cat_label(e)
            counts[label] = counts.get(label, 0) + 1

    log_header("MEP Branch Trace")
    log("Host model: **{}**  ·  Linked files: **{}** ({} elements)  "
        "·  Open terminals: **{}**".format(
            len(host_elems), len(linked_elems), total_linked, len(terminals)))
    log("")

    if counts:
        rows = [[cl, str(counts[cl])] for cl in sorted(counts)]
        log_table(["Category", "Count"], rows)

    log("**{} element(s) selected.**".format(selected_count))
    if skipped:
        log("*{} element(s) could not be turned into a selectable "
            "reference.*".format(skipped))

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

    if rvt_year < 2023:
        TaskDialog.Show(
            "MEP Branch Tracer",
            "Highlighting the branch by selection needs "
            "Selection.SetReferences(), added in the Revit 2023 API.\n\n"
            "This Revit is {0}.".format(rvt_year)
        )
        return

    try:
        ref = uidoc.Selection.PickObject(
            ObjectType.LinkedElement,
            "Pick a MEP element from a linked file to trace its branch"
        )
    except RvtEx.OperationCanceledException:
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

    link_data = get_link_data()
    if link_instance.Id not in link_data:
        link_data[link_instance.Id] = {
            'doc'      : link_doc,
            'transform': world_xform,
            'title'    : link_doc.Title,
            'instance' : link_instance,
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

    sel_refs, skipped = build_selection_references(host_elems, linked_elems, link_data)

    log_summary(host_elems, linked_elems, terminals, sel_refs.Count, skipped)

    if not HAS_OUTPUT:
        TaskDialog.Show("MEP Branch Tracer", "\n".join(_log_lines[-80:]))

    # Selection goes last: a committed transaction can clear it.
    if sel_refs.Count:
        uidoc.Selection.SetReferences(sel_refs)


if __name__ == '__main__':
    main()
# -*- coding: utf-8 -*-
"""DLC Room Areas - Revit adapter (Revit 2025/2026, IronPython 2.7).

Everything that touches the Revit API lives here; the measuring rules are in
engine.py and the geometry in geometry.py, both Revit-free and unit tested.
"""
from __future__ import division
import os
import tempfile

from Autodesk.Revit import DB

from . import engine
from . import geometry as g

SQFT_TO_SQM = 0.09290304
MM_TO_FT = 1.0 / 304.8


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------
def id_value(eid):
    """ElementId -> int. .Value (2024+); .IntegerValue was removed in 2026."""
    try:
        return int(eid.Value)
    except Exception:
        return int(eid.IntegerValue)


def is_invalid(eid):
    return eid is None or eid == DB.ElementId.InvalidElementId


def elem_name(el):
    """Element.Name is an explicit interface on some classes in IronPython."""
    if el is None:
        return ''
    try:
        return DB.Element.Name.GetValue(el)
    except Exception:
        try:
            return el.Name
        except Exception:
            return ''


def _bic_id(bic):
    return DB.ElementId(bic)


def category_is(el, bic):
    try:
        cat = el.Category
        return cat is not None and cat.Id == _bic_id(bic)
    except Exception:
        return False


def room_number(room):
    p = room.get_Parameter(DB.BuiltInParameter.ROOM_NUMBER)
    return p.AsString() if p is not None and p.AsString() else ''


def room_name(room):
    p = room.get_Parameter(DB.BuiltInParameter.ROOM_NAME)
    return p.AsString() if p is not None and p.AsString() else ''


def room_level_name(doc, room):
    try:
        return elem_name(doc.GetElement(room.LevelId))
    except Exception:
        return ''


def room_area_ft2(room):
    p = room.get_Parameter(DB.BuiltInParameter.ROOM_AREA)
    return p.AsDouble() if p is not None else 0.0


def is_placed(room):
    try:
        return room.Location is not None and room_area_ft2(room) > 1e-6
    except Exception:
        return False


def read_yes_no(el, pname):
    """True / False / None (parameter missing or never filled)."""
    p = el.LookupParameter(pname)
    if p is None or not p.HasValue:
        return None
    try:
        return p.AsInteger() == 1
    except Exception:
        return None


# --------------------------------------------------------------------------
# rooms in scope
# --------------------------------------------------------------------------
def collect_rooms(doc, uidoc, scope):
    """scope: 'ALL' | 'LEVEL' | 'SELECTION'. Returns (rooms, message)."""
    if scope == 'SELECTION':
        rooms = []
        for eid in uidoc.Selection.GetElementIds():
            el = doc.GetElement(eid)
            if el is not None and category_is(el, DB.BuiltInCategory.OST_Rooms):
                rooms.append(el)
        if not rooms:
            return [], 'No rooms are selected. Select rooms in a plan or ' \
                       'schedule, or choose another scope.'
    else:
        rooms = list(DB.FilteredElementCollector(doc)
                     .OfCategory(DB.BuiltInCategory.OST_Rooms)
                     .WhereElementIsNotElementType())
        if scope == 'LEVEL':
            lvl = getattr(doc.ActiveView, 'GenLevel', None)
            if lvl is None:
                return [], 'The active view has no level. Open a floor ' \
                           'plan, or choose another scope.'
            rooms = [r for r in rooms if r.LevelId == lvl.Id]
    placed = [r for r in rooms if is_placed(r)]
    msg = ''
    skipped = len(rooms) - len(placed)
    if skipped:
        msg = '%d unplaced / not enclosed / redundant room(s) skipped.' \
              % skipped
    return placed, msg


# --------------------------------------------------------------------------
# bounding element description
# --------------------------------------------------------------------------
def _wall_width(wall, flags):
    try:
        if wall.IsStackedWall:
            ids = list(wall.GetStackedWallMemberIds())
            if ids:
                flags.append('STACKED_WALL')
                member = wall.Document.GetElement(ids[0])
                return member.Width
    except Exception:
        pass
    try:
        return wall.Width
    except Exception:
        return None


def _wall_function(wall):
    try:
        wt = wall.WallType
        p = wt.get_Parameter(DB.BuiltInParameter.FUNCTION_PARAM)
        if p is None or not p.HasValue:
            return None
        return engine.FUNCTION_NAMES.get(p.AsInteger())
    except Exception:
        return None


def _is_curtain(wall):
    try:
        return wall.WallType.Kind == DB.WallKind.Curtain
    except Exception:
        return False


def describe_bounding(doc, seg):
    """Bounding element of a BoundarySegment -> partial segment dict."""
    info = {'kind': g.KIND_OTHER, 'width': None, 'function': None,
            'is_curtain': False, 'label': '', 'extra_flags': []}
    eid = seg.ElementId
    if is_invalid(eid):
        info['label'] = '(no element)'
        return info
    el = doc.GetElement(eid)
    prefix = ''
    link_eid = getattr(seg, 'LinkElementId', None)
    if isinstance(el, DB.RevitLinkInstance) and not is_invalid(link_eid):
        ldoc = el.GetLinkDocument()
        if ldoc is None:
            info['label'] = 'Unloaded link %s' % elem_name(el)
            return info
        prefix = '[%s] ' % (ldoc.Title or elem_name(el))
        el = ldoc.GetElement(link_eid)
        info['extra_flags'].append('LINKED_WALL')
    if el is None:
        info['label'] = prefix + '(missing element)'
        return info

    if isinstance(el, DB.Wall):
        info['kind'] = g.KIND_WALL
        info['width'] = _wall_width(el, info['extra_flags'])
        info['function'] = _wall_function(el)
        info['is_curtain'] = _is_curtain(el)
        info['label'] = '%s%s [%d]' % (prefix, elem_name(el.WallType),
                                       id_value(el.Id))
        if 'LINKED_WALL' in info['extra_flags'] and not prefix:
            info['extra_flags'].remove('LINKED_WALL')
        return info

    if 'LINKED_WALL' in info['extra_flags']:
        info['extra_flags'].remove('LINKED_WALL')
    if category_is(el, DB.BuiltInCategory.OST_RoomSeparationLines):
        info['kind'] = g.KIND_SEPARATION
        info['label'] = prefix + 'Room Separation [%d]' % id_value(el.Id)
    elif (category_is(el, DB.BuiltInCategory.OST_Columns) or
          category_is(el, DB.BuiltInCategory.OST_StructuralColumns)):
        info['kind'] = g.KIND_COLUMN
        info['label'] = prefix + 'Column [%d]' % id_value(el.Id)
    else:
        cat = getattr(el, 'Category', None)
        info['label'] = prefix + '%s [%d]' % (
            cat.Name if cat is not None else 'Element', id_value(el.Id))
    return info


# --------------------------------------------------------------------------
# boundary extraction
# --------------------------------------------------------------------------
def boundary_options():
    opts = DB.SpatialElementBoundaryOptions()
    opts.SpatialElementBoundaryLocation = \
        DB.SpatialElementBoundaryLocation.Finish
    return opts


def _room_phase(doc, room):
    try:
        p = room.get_Parameter(DB.BuiltInParameter.ROOM_PHASE)
        return doc.GetElement(p.AsElementId())
    except Exception:
        return None


def _probe_z(doc, room):
    z = 0.0
    try:
        z = doc.GetElement(room.LevelId).Elevation
    except Exception:
        pass
    try:
        p = room.get_Parameter(DB.BuiltInParameter.ROOM_LOWER_OFFSET)
        if p is not None:
            z += p.AsDouble()
    except Exception:
        pass
    return z + 1.0          # 1 ft above room base - inside every room volume


def extract_loops(doc, room, settings, opts=None):
    """Room -> oriented segment loops ready for engine.compute_room()."""
    opts = opts or boundary_options()
    raw = room.GetBoundarySegments(opts)
    loops = []
    if raw is None:
        return loops
    for seg_list in raw:
        loop = []
        for seg in seg_list:
            curve = seg.GetCurve()
            pts3 = list(curve.Tessellate())
            if len(pts3) < 2:
                continue
            s = describe_bounding(doc, seg)
            s['pts'] = [(p.X, p.Y) for p in pts3]
            loop.append(s)
        if loop:
            loops.append(loop)

    loops = engine.orient_segment_loops(loops)

    # probe behind every wall face (needed for QA, and for the decision when
    # the wall Function cannot be read)
    phase = _room_phase(doc, room)
    z = _probe_z(doc, room)
    gap = settings.get('PROBE_GAP', 200.0 * MM_TO_FT)
    for loop in loops:
        for s in loop:
            if s['kind'] != g.KIND_WALL:
                continue
            dist = (s['width'] or 0.0) + gap
            pt = engine.probe_point(s, dist)
            if pt is None or phase is None:
                s['room_behind'] = None
                continue
            try:
                other = doc.GetRoomAtPoint(DB.XYZ(pt[0], pt[1], z), phase)
                s['room_behind'] = other is not None and other.Id != room.Id
            except Exception:
                s['room_behind'] = None
    return loops


# --------------------------------------------------------------------------
# shared parameters
# --------------------------------------------------------------------------
SPF_HEADER = ('# This is a Revit shared parameter file.\r\n'
              '# Do not edit manually.\r\n'
              '*META\tVERSION\tMINVERSION\r\n'
              'META\t2\t1\r\n'
              '*GROUP\tID\tNAME\r\n'
              '*PARAM\tGUID\tNAME\tDATATYPE\tDATACATEGORY\tGROUP\tVISIBLE\t'
              'DESCRIPTION\tUSERMODIFIABLE\tHIDEWHENNOVALUE\r\n')


def _spec(kind):
    if kind == 'AREA':
        return DB.SpecTypeId.Area
    return DB.SpecTypeId.Boolean.YesNo


def _bindings_by_name(doc):
    found = {}
    it = doc.ParameterBindings.ForwardIterator()
    it.Reset()
    while it.MoveNext():
        found[it.Key.Name] = (it.Key, it.Current)
    return found


def check_parameters(doc, specs):
    """Report-only check. specs: [(name, guid, 'AREA'|'YESNO', description)].

    Returns (missing_names, problems) without changing the model.
    """
    rooms_cat = DB.Category.GetCategory(doc, DB.BuiltInCategory.OST_Rooms)
    bound = _bindings_by_name(doc)
    missing, problems = [], []
    for name, guid, kind, desc in specs:
        if name not in bound:
            missing.append(name)
            continue
        definition, binding = bound[name]
        try:
            if definition.GetDataType() != _spec(kind):
                problems.append(
                    'Parameter "%s" already exists but is not %s '
                    'parameter. Rename or delete it, then run again.'
                    % (name, 'an Area' if kind == 'AREA' else 'a Yes/No'))
                continue
        except Exception:
            pass
        if not isinstance(binding, DB.InstanceBinding):
            problems.append('Parameter "%s" exists as a TYPE parameter; it '
                            'must be an instance parameter on Rooms.' % name)
        elif not binding.Categories.Contains(rooms_cat):
            missing.append(name)
    return missing, problems


def ensure_parameters(doc, app, specs, group_name='DLC'):
    """Create / bind the room parameters. Call inside an open Transaction.

    Uses fixed GUIDs so every building model gets the same shared parameter
    and multi-model schedules line up. The user's shared parameter file
    setting is restored afterwards.
    """
    import System
    rooms_cat = DB.Category.GetCategory(doc, DB.BuiltInCategory.OST_Rooms)
    bound = _bindings_by_name(doc)
    created = []
    original = app.SharedParametersFilename
    tmp = os.path.join(tempfile.gettempdir(), 'DLC_RoomAreas_SharedParams.txt')
    fresh = [False]
    try:
        for name, guid, kind, desc in specs:
            if name in bound:
                definition, binding = bound[name]
                if isinstance(binding, DB.InstanceBinding) and \
                        not binding.Categories.Contains(rooms_cat):
                    cats = binding.Categories
                    cats.Insert(rooms_cat)
                    doc.ParameterBindings.ReInsert(
                        definition, DB.InstanceBinding(cats),
                        DB.GroupTypeId.Data)
                    created.append(name + ' (added to Rooms)')
                continue
            if not fresh[0]:
                # fresh file every run (binary mode keeps CRLF exact and no
                # stale definitions with old GUIDs can be picked up)
                with open(tmp, 'wb') as f:
                    f.write(SPF_HEADER.encode('ascii'))
                fresh[0] = True
            app.SharedParametersFilename = tmp
            spf = app.OpenSharedParameterFile()
            grp = spf.Groups.get_Item(group_name) or \
                spf.Groups.Create(group_name)
            definition = grp.Definitions.get_Item(name)
            if definition is None:
                opt = DB.ExternalDefinitionCreationOptions(name, _spec(kind))
                opt.GUID = System.Guid(guid)
                opt.Description = desc
                definition = grp.Definitions.Create(opt)
            cats = DB.CategorySet()
            cats.Insert(rooms_cat)
            ok = doc.ParameterBindings.Insert(
                definition, DB.InstanceBinding(cats), DB.GroupTypeId.Data)
            if not ok:
                raise RuntimeError('Revit refused to add parameter "%s".'
                                   % name)
            created.append(name)
    finally:
        try:
            app.SharedParametersFilename = original or ''
        except Exception:
            pass
    return created


def owned_by_other(doc, el):
    if not doc.IsWorkshared:
        return None
    try:
        st = DB.WorksharingUtils.GetCheckoutStatus(doc, el.Id)
        if st == DB.CheckoutStatus.OwnedByOtherUser:
            info = DB.WorksharingUtils.GetWorksharingTooltipInfo(doc, el.Id)
            return info.Owner or 'another user'
    except Exception:
        pass
    return None


def write_area(el, pname, value_ft2):
    p = el.LookupParameter(pname)
    if p is None:
        raise RuntimeError('Parameter %s is missing on this room.' % pname)
    if p.IsReadOnly:
        raise RuntimeError('Parameter %s is read-only (is it a formula or '
                           'a project parameter of another type?).' % pname)
    if not p.Set(float(value_ft2)):
        raise RuntimeError('Revit rejected the value for %s.' % pname)
